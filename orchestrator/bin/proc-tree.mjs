// Track the descendants of one process while it runs, and kill the ones left over when it is done.
//
// `taskkill /T` follows live parent links only: a child whose parent already exited is missed (a timed-out run once
// left `bash -v` children that later overwrote a file). A command line does not contain the cwd, so matching by path
// cannot work either. So: sample the process table while the run is alive, remember every descendant, and at the end
// kill what is still there.
//
//   const w = watch(rootPid, { since })   // since: ms epoch / Date / ISO — nothing older is ever touched
//   ...                                   // samples every everyMs (default 5000)
//   const killed = await w.sweep();       // one fresh sample, kills leftovers, returns [{pid, cmd}]
//   w.stop();                             // ends the sampler (Windows: the PowerShell loop); safe to call twice
//
// Clock handling: `since` and the rule-(c) "born while parent was seen alive" window are compared against
// `ps` start times, which on Linux come from the /proc boot-time clock, not Date.now(). That clock can lag
// wall time by ~1 s (NTP/suspend steps since boot), so `since` is shifted onto the ps clock by a measured
// skew ((btime + uptime) - Date.now()) before the one-second floor, and the same skew converts the wall-clock
// `seen` stamp to the ps clock. A failure reading /proc, macOS, or an injected `sample` leaves skew at 0
// (unchanged behaviour). Both sides of every `since` comparison then sit on the same clock, so the safety
// rule "never kill anything that started before `since`" still holds — it is just interpreted on ps's clock.
// - `clockSkewMs` (number, ms) overrides the measurement for unit tests; an injected sampler skips /proc.
//
// Safety (this code kills processes on a machine shared with other agent sessions):
// - Only processes that were descendants of rootPid in a sample, or live children of such a tracked pid (or of rootPid)
//   whose parent is gone and that started at/after `since`, are ever killed. The command line is NEVER used to match.
// - Pid reuse: a tracked process is the same one only if pid AND start (ISO string) are equal.
// - Never process.pid, its ancestors, rootPid's ancestors, pids <= 4, or anything that started before `since`.
// - Every failure (no powershell, parse error, ...) gives empty results; a watcher never fails a run.
// - ORCH_NO_PROCTREE=1 disables it. Windows runs ONE long-lived PowerShell loop per watcher; it is killed by stop(), on
//   process exit, and it ends by itself when this process is gone.
// - sweep() kills every victim as a single pid (never taskkill /T): every real descendant is already tracked, and /T could
//   follow a stale parent link to an unrelated process. Orphans (parent gone) are taken only if born while the parent was
//   last seen alive (+ one sample interval + 1 s), so a recycled-then-released pid never hands us a stranger's children.
// Accepted limits: a process spawned AND orphaned within one sample interval, whose own children are also gone, is missed;
//   a parent never seen alive in a sample (lived less than one interval) has no trusted orphans.
import { spawn, execFile, execFileSync } from "node:child_process";
import fs from "node:fs";

const WIN = process.platform === "win32";
const CIM =
  "ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,CommandLine," +
  "@{N='Start';E={$_.CreationDate.ToUniversalTime().ToString('o')}})";
const PS_ARGS = ["-NoProfile", "-NonInteractive", "-Command"];

function ms(t) {
  if (typeof t === "number") return t;
  const v = new Date(t).getTime();
  return Number.isFinite(v) ? v : NaN;
}

// raw CIM / ps rows -> [{pid, ppid, start, cmd}]
function normalize(rows) {
  const out = [];
  for (const r of Array.isArray(rows) ? rows : []) {
    const pid = Number(r.pid ?? r.ProcessId);
    const ppid = Number(r.ppid ?? r.ParentProcessId);
    const start = r.start ?? r.Start;
    if (!Number.isInteger(pid) || pid <= 0 || typeof start !== "string" || !start) continue;
    out.push({ pid, ppid: Number.isInteger(ppid) ? ppid : 0, start, cmd: String(r.cmd ?? r.CommandLine ?? "") });
  }
  return out;
}

export function parseJsonLine(line) {
  try {
    // PowerShell does not escape every control character in a CommandLine (one stray 0x1A in any process on the box would
    // otherwise make the whole sample unparseable), so blank them first.
    const v = JSON.parse(line.replace(/[\x00-\x1f]/g, " "));
    return normalize(Array.isArray(v) ? v : [v]);
  } catch {
    return null;
  }
}

function winOneShot() {
  return new Promise((resolve) => {
    try {
      execFile("powershell", [...PS_ARGS, CIM], { windowsHide: true, maxBuffer: 64 * 1024 * 1024, timeout: 20_000 }, (err, stdout) => {
        resolve(err ? [] : parseJsonLine(String(stdout).trim().split(/\r?\n/).pop()) || []);
      });
    } catch {
      resolve([]);
    }
  });
}

// One `ps -eo pid=,ppid=,lstart=,args=` line -> {pid, ppid, start (ISO), cmd}, or null.
export function parsePsLine(line) {
  const m = line.match(/^\s*(\d+)\s+(\d+)\s+(\w{3}\s+\w{3}\s+\d+\s+[\d:]+\s+\d{4})\s*(.*)$/);
  if (!m) return null;
  const d = new Date(m[3]);
  return Number.isNaN(d.getTime()) ? null : { pid: Number(m[1]), ppid: Number(m[2]), start: d.toISOString(), cmd: m[4] };
}

// How far the ps /proc clock runs behind Date.now(), in ms (ps_clock - wall_clock).
// procps derives `lstart` from boot time (/proc/stat btime) + /proc/uptime, which can lag the
// wall clock by ~1 s on a box whose clock stepped since boot (NTP, suspend). Measured 2026-11-24:
// skew ~-0.9 s; with lstart's one-second truncation on top, a process's lstart read 1.0-1.9 s behind
// its spawn Date.now(), so a process spawned just after `since` looked older than `since` and was
// never swept — a real leak, not a test bug.
// Returns 0 on macOS (no /proc) or when /proc cannot be read (falls back to today's behaviour).
export function procClockSkewMs() {
  if (process.platform !== "linux") return 0;
  try {
    const stat = fs.readFileSync("/proc/stat", "utf8");
    const btime = Number(stat.match(/^btime (\d+)/m)?.[1]);
    const uptime = Number(fs.readFileSync("/proc/uptime", "utf8").split(" ")[0]);
    if (!Number.isFinite(btime) || !Number.isFinite(uptime)) return 0;
    return (btime + uptime) * 1000 - Date.now();
  } catch {
    return 0;
  }
}

function posixSample() {
  return new Promise((resolve) => {
    try {
      execFile("ps", ["-eo", "pid=,ppid=,lstart=,args="], { maxBuffer: 64 * 1024 * 1024, timeout: 20_000, env: { ...process.env, LC_ALL: "C" } }, (err, stdout) => {
        if (err) return resolve([]);
        const rows = [];
        for (const line of String(stdout).split(/\r?\n/)) {
          const row = parsePsLine(line);
          if (row) rows.push(row);
        }
        resolve(normalize(rows));
      });
    } catch {
      resolve([]);
    }
  });
}

// Process start time as an ISO UTC string, or null when the process is gone (or the lookup fails). A pid alone can be
// recycled, so a tracked process is the same one only while pid AND start agree. Ported from board.mjs `workerStart`
// (board.mjs keeps its own copy and is not changed); the pid is validated before it reaches the command line.
export function processStart(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return null;
  const toIso = (raw) => {
    const d = Date.parse(String(raw).trim());
    return d > 0 ? new Date(d).toISOString() : null;
  };
  try {
    const out = WIN
      ? execFileSync("powershell", ["-NoProfile", "-Command", `(Get-Process -Id ${pid}).StartTime.ToUniversalTime().ToString('o')`], {
          encoding: "utf8",
          stdio: ["ignore", "pipe", "ignore"],
          windowsHide: true,
        })
      : execFileSync("ps", ["-o", "lstart=", "-p", String(pid)], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
    return toIso(out);
  } catch {
    return null;
  }
}

// The state letter of a /proc/<pid>/stat line (R S D Z T t W X x K P...), or null when it cannot be parsed.
// The comm field (inside parens) may itself contain parens, so the state is read after the LAST close paren.
export function procState(stat) {
  const i = String(stat ?? "").lastIndexOf(")");
  if (i < 0) return null;
  const s = String(stat).slice(i + 1).trim().split(/\s+/)[0];
  return s || null;
}

// True when pid exists but is a zombie (dead, awaiting reap): it runs nothing, writes nothing, holds no lock.
// process.kill(pid, 0) still succeeds on a zombie, so every liveness check must exclude them (a closed desk
// session's watcher reads as "running" until it is reaped otherwise). Linux-only; any lookup failure (gone,
// foreign user, non-Linux) reads as "not a zombie" and the caller's other checks decide.
export function isZombie(pid) {
  if (process.platform === "win32") return false;
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    return procState(fs.readFileSync(`/proc/${pid}/stat`, "utf8")) === "Z";
  } catch {
    return false;
  }
}

// Kill a pid and its live descendants. Always a Promise<boolean> (taskkill is async on win32).
export async function killPid(pid) {
  return defaultKill(pid, { tree: true });
}

// tree: also kill the pid's live descendants (/T). sweep() never asks for it: every real descendant is already tracked,
// and on Windows /T would also take a stale-ppid process that merely has a dead parent with the same pid number.
function defaultKill(pid, { tree = false } = {}) {
  if (WIN) {
    return new Promise((resolve) => {
      try {
        execFile("taskkill", ["/PID", String(pid), ...(tree ? ["/T"] : []), "/F"], { windowsHide: true }, (err) => resolve(!err));
      } catch {
        resolve(false);
      }
    });
  }
  try {
    process.kill(pid, "SIGKILL");
    return true;
  } catch {
    return false;
  }
}

function inert() {
  return { stop() {}, tracked: () => [], sweep: async () => [], observe: async () => {} };
}

export function watch(rootPid, { everyMs = 5000, since = Date.now(), sample, kill = defaultKill, now = Date.now, autoPoll = true, clockSkewMs } = {}) {
  if (process.env.ORCH_NO_PROCTREE === "1" || !Number.isInteger(rootPid) || rootPid <= 0) return inert();
  let sinceMs = ms(since);
  if (!Number.isFinite(sinceMs)) return inert();
  let skew = 0;
  if (clockSkewMs !== undefined) {
    // Injected skew for unit tests (an injected sampler skips /proc measurement).
    skew = Number(clockSkewMs) || 0;
    if (!sample) sinceMs = Math.floor((sinceMs + skew) / 1000) * 1000;
    else sinceMs = sinceMs + skew; // injected sampler carries ms resolution: no one-second floor
  } else if (!sample && !WIN) {
    skew = procClockSkewMs();                                    // 0 on macOS or when /proc is unreadable
    sinceMs = Math.floor((sinceMs + skew) / 1000) * 1000;        // ps lstart: 1 s resolution, on the /proc clock
  }

  const tracked = new Map(); // "pid@start" -> {pid, ppid, start, cmd}
  // rootStart is taken from the FIRST sample that shows rootPid (it was spawned just before the watcher started, so that
  // is its own start); once set it is never replaced, so a later holder of a recycled pid cannot become the parent.
  let rootStart = null;
  // lastSeen: ms (via now()) of the newest sample that showed rootPid (key "root") / a tracked entry (key "pid@start") alive
  // with the same start. Rule (c) only trusts a parent for children born while it was seen alive (see sweep()).
  const lastSeen = new Map();
  let stopped = false;
  let loop = null; // Windows PowerShell loop
  let timer = null;

  const startOk = (p) => ms(p.start) >= sinceMs;

  // Add every transitive descendant of rootPid in this sample to `tracked`.
  function track(rows) {
    const byPid = new Map(rows.map((p) => [p.pid, p]));
    const root = byPid.get(rootPid);
    if (root && !rootStart && startOk(root)) rootStart = root.start;
    if (root && rootStart && root.start !== rootStart) return; // rootPid now belongs to another process: nothing below it is ours
    const kids = new Map();
    for (const p of rows) {
      if (!kids.has(p.ppid)) kids.set(p.ppid, []);
      kids.get(p.ppid).push(p);
    }
    const seen = new Set([rootPid]);
    const queue = [{ pid: rootPid, start: rootStart }];
    while (queue.length) {
      const parent = queue.shift();
      for (const c of kids.get(parent.pid) || []) {
        if (seen.has(c.pid) || c.pid === process.pid) continue;
        if (!startOk(c)) continue; // linked through a reused pid, or older than the run
        if (parent.start && ms(c.start) < ms(parent.start)) continue;
        seen.add(c.pid);
        tracked.set(`${c.pid}@${c.start}`, c);
        queue.push(c);
      }
    }
    const t = now();
    if (root && rootStart && root.start === rootStart) lastSeen.set("root", t);
    for (const [key, e] of tracked) if (byPid.get(e.pid)?.start === e.start) lastSeen.set(key, t);
  }

  const fresh = async () => {
    try {
      return normalize(await (sample ? sample() : WIN ? winOneShot() : posixSample()));
    } catch {
      return [];
    }
  };
  const observe = async () => {
    try {
      track(await fresh());
    } catch {}
  };

  function startLoop() {
    try {
      const script = `while ([bool](Get-Process -Id ${process.pid} -ErrorAction SilentlyContinue)) { ${CIM}; Start-Sleep -Milliseconds ${everyMs} }`;
      loop = spawn("powershell", [...PS_ARGS, script], { windowsHide: true, stdio: ["ignore", "pipe", "ignore"] });
      loop.unref();
      loop.stdout.unref?.();
      loop.on("error", () => {});
      let buf = "";
      loop.stdout.on("data", (d) => {
        buf += d;
        let i;
        while ((i = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, i).trim();
          buf = buf.slice(i + 1);
          const rows = line ? parseJsonLine(line) : null;
          if (rows) {
            try {
              track(rows);
            } catch (e) { console.error("DBG", e); }
          }
        }
      });
    } catch {
      loop = null;
    }
  }

  const killLoop = () => {
    try {
      loop?.kill();
    } catch {}
  };
  const onExit = () => killLoop();

  if (sample) {
    if (everyMs > 0 && autoPoll) { // tests inject a sampler and drive it with observe()/sweep() themselves (autoPoll: false)
      timer = setInterval(observe, everyMs);
      timer.unref();
      observe();
    }
  } else if (WIN) {
    startLoop();
    process.on("exit", onExit);
  } else {
    timer = setInterval(observe, everyMs);
    timer.unref();
    observe();
  }

  function stop() {
    if (stopped) return;
    stopped = true;
    if (timer) clearInterval(timer);
    killLoop();
    process.removeListener("exit", onExit);
  }

  async function sweep() {
    try {
      const rows = await fresh();
      if (!rows.length) return [];
      track(rows);
      const live = new Map(rows.map((p) => [p.pid, p]));
      // Never kill this process or anything above it (ours, and rootPid's ancestors).
      const ancestors = new Set([process.pid]);
      for (const from of [process.pid, rootPid]) {
        let pid = live.get(from)?.ppid;
        for (let depth = 0; pid && depth < 64 && !ancestors.has(pid); depth++) {
          ancestors.add(pid);
          pid = live.get(pid)?.ppid;
        }
      }
      // A parent counts as gone ONLY when no live process holds its pid. A live holder with a different start is a
      // recycled pid (some unrelated program): its children are not ours, so rule (c) is skipped for that parent.
      const gone = (pid) => !live.has(pid);
      const victims = new Map();
      // (a) every tracked entry still alive with the same start
      for (const t of tracked.values()) {
        const p = live.get(t.pid);
        if (p && p.start === t.start) victims.set(p.pid, p);
      }
      // (c) children orphaned from a tracked parent (or rootPid) that is now gone
      // A child is only ours if it was born while its parent was still seen alive (+ one sample interval + 1 s): a pid that
      // was recycled and released again would otherwise hand us the children of an unrelated process.
      const parents = [{ pid: rootPid, start: rootStart, seen: lastSeen.get("root") }, ...[...tracked].map(([key, t]) => ({ pid: t.pid, start: t.start, seen: lastSeen.get(key) }))];
      for (const par of parents) {
        if (!gone(par.pid) || par.seen === undefined) continue;
        for (const p of rows) {
          if (p.ppid !== par.pid || !startOk(p)) continue;
          if (par.start && ms(p.start) < ms(par.start)) continue;
          if (ms(p.start) > par.seen + skew + everyMs + 1000) continue;
          if (!victims.has(p.pid)) victims.set(p.pid, p);
        }
      }
      const killed = [];
      for (const p of victims.values()) {
        if (ancestors.has(p.pid) || p.pid === rootPid || p.pid <= 4 || !startOk(p)) continue;
        const again = live.get(p.pid);
        if (!again || again.start !== p.start) continue;
        if (await kill(p.pid, { tree: false })) killed.push({ pid: p.pid, cmd: p.cmd });
      }
      return killed;
    } catch {
      return [];
    }
  }

  return { stop, sweep, observe, tracked: () => [...tracked.values()] };
}
