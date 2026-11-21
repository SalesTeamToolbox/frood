#!/usr/bin/env node
// Remove a merged worktree even when an MCP server is pinning it.
//
//   node bin/wt-finish.mjs <worktree> [--base <ref>] [--delete-branch] [--dry-run] [--json]
//
// Why: the OpenCode service spawns MCP servers per session directory - a Python MCP server (`mcp_server.py serve`) and
// peer-mail (`opencode-peer-mail/dist/index.js`) - with the ticket worktree as their cwd. They outlive the run,
// so `git worktree remove` fails ("Invalid argument") and leaves the directory behind (found 2026-11-13, three
// orphans cleaned by hand). A shell or agent session found in the worktree is NOT ours to kill.
//
// Checks, in order; the first failure prints one `FAIL <check> <detail>` line on stdout and exits:
//   1. not-a-worktree (2)  2. dirty (3)  3. not-merged (3)  4. busy (4)  5. remove (5)  6. branch (5)
//   nested (5), scan (5) and links (5) are refusals added for safety (see below).
//   8. success: `OK <worktree> killed=<n>` (0); `--dry-run`: `DRY <worktree>` + `would-kill`/`busy` lines;
//      `--json` replaces the text lines with {ok, check, worktree, killed, busy} and keeps the exit codes.
//
// Safety (this kills processes on a machine shared with other agent sessions):
// - A process is a holder only because its cwd is inside the worktree. The command line is used only to decide
//   kill-vs-refuse among holders already matched by cwd, never to find them.
// - MCP is decided from the program and its script argument alone (never later argv): an OpenCode worker carries its
//   whole Mandate in argv, and this ticket's own Mandate names `mcp_server.py`, so matching the whole command line
//   would turn a live worker into a kill target instead of `FAIL busy`.
// - Patterns: `mcp_server.py`, `opencode-peer-mail`; ORCH_WT_MCP_PATTERNS (comma-separated substrings) replaces them.
// - A kill is one pid, never a process tree: `taskkill /PID n /F` (no /T) or SIGKILL. The pid's start time comes from
//   the same process handle as its cwd, and is re-read right before the kill; a differing or missing start time skips
//   the kill (pid reuse).
// - Any other holder (a shell, an agent session) makes it FAIL busy: nothing is killed, nothing removed.
// - Every symlink/junction in the tree that git does not track is unlinked before removal, and the walk is repeated
//   before each `git worktree remove`. `git worktree remove` (like rm -rf) follows a junction into its target and
//   empties it - the 2026-11-13 incident was a nested verify worktree's `node_modules`. A link that survives the
//   unlink stops the run with `FAIL links` instead of handing it to git. A link git tracks is kept (unlinking a
//   tracked link would dirty the worktree that check 2 just approved). The walk never descends into a link.
// - Refuses when another registered worktree is nested under the target (`FAIL nested`) and when the process listing
//   cannot see this process's own cwd (`FAIL scan`, fail closed: no holders can be trusted then).
import "./no-window.mjs"; // hide console windows of every child process (Windows)
import fs from "node:fs";
import path from "node:path";
import { spawnSync, execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { parsePsLine, processStart } from "./proc-tree.mjs";

const IS_WIN = process.platform === "win32";
const SEP = IS_WIN ? "\\" : "/";
const DEFAULT_MCP = ["mcp_server.py", "opencode-peer-mail"];
const CMD_MAX = 80;
const LAUNCH = process.argv[1] ? path.resolve(process.argv[1]) : "";

// ------------------------------------------------------------------ paths

// Absolute path, normalized for comparison: win32 is case-insensitive and git prints forward slashes, so both
// are folded to one form; the trailing separator is dropped (except at a drive/posix root).
export function normPath(p) {
  if (typeof p !== "string" || !p) return null;
  let s;
  try {
    s = path.resolve(p);
  } catch {
    return null;
  }
  if (IS_WIN) s = s.replace(/\//g, "\\").toLowerCase();
  if (s.length > 1) s = s.replace(/[\\/]+$/, "");
  return s || SEP;
}

// True only for the directory itself or a path below it, on a separator boundary, so `wt2` is not inside `wt`.
export function isInside(cwd, root) {
  const c = normPath(cwd);
  const r = normPath(root);
  if (!c || !r) return false;
  if (c === r) return true;
  return c.startsWith(r.endsWith(SEP) ? r : r + SEP);
}

// ------------------------------------------------------------------ processes

// Command lines are display/decision only: `cmd` never decides WHICH process is a holder (cwd does).
const CSHARP = String.raw`
using System;
using System.Runtime.InteropServices;
using System.Text;

public class WtPeb {
  [StructLayout(LayoutKind.Sequential)]
  public struct PBI {
    public IntPtr ExitStatus;
    public IntPtr PebBaseAddress;
    public IntPtr AffinityMask;
    public IntPtr BasePriority;
    public IntPtr UniqueProcessId;
    public IntPtr InheritedFromUniqueProcessId;
  }

  public class ProcInfo {
    public string Cwd;
    public long Start = -1; // ms since the Unix epoch (UTC); -1 when unknown
  }

  [DllImport("ntdll.dll")]
  public static extern int NtQueryInformationProcess(IntPtr handle, int cls, ref PBI pbi, int len, out int ret);

  [DllImport("kernel32.dll", SetLastError = true)]
  public static extern IntPtr OpenProcess(uint access, bool inherit, int pid);

  [DllImport("kernel32.dll", SetLastError = true)]
  public static extern bool ReadProcessMemory(IntPtr handle, IntPtr addr, byte[] buf, IntPtr size, out IntPtr read);

  [DllImport("kernel32.dll", SetLastError = true)]
  public static extern bool GetProcessTimes(IntPtr handle, out long creation, out long exited, out long kernel, out long user);

  [DllImport("kernel32.dll")]
  public static extern bool CloseHandle(IntPtr handle);

  // cwd and start time from the SAME handle, so the pair always describes one process (a pid can be recycled
  // between two reads).
  public static ProcInfo Info(int pid) {
    IntPtr h = IntPtr.Zero;
    try {
      // PROCESS_QUERY_INFORMATION (0x0400) | PROCESS_VM_READ (0x0010). A process we may not open (another
      // user, protected, WOW64 quirk) throws or yields a null handle: it has neither a cwd nor a start for us.
      h = OpenProcess(0x0410u, false, pid);
      if (h == IntPtr.Zero) return null;
      ProcInfo info = new ProcInfo();
      long creation, exited, kernel, user;
      if (GetProcessTimes(h, out creation, out exited, out kernel, out user)) info.Start = FileTimeMs(creation);
      info.Cwd = CwdFrom(h);
      return info;
    } catch {
      return null;
    } finally {
      if (h != IntPtr.Zero) CloseHandle(h);
    }
  }

  static long FileTimeMs(long ft) {
    if (ft <= 0) return -1;
    return (long)((ft - 116444736000000000L) / 10000L);
  }

  static string CwdFrom(IntPtr h) {
    PBI pbi = new PBI();
    int ret;
    if (NtQueryInformationProcess(h, 0, ref pbi, Marshal.SizeOf(typeof(PBI)), out ret) != 0) return null;
    if (pbi.PebBaseAddress == IntPtr.Zero) return null;
    // x64: PEB + 0x20 -> RTL_USER_PROCESS_PARAMETERS; + 0x38 -> CURDIR; UNICODE_STRING.Buffer at + 8.
    IntPtr pp = ReadPtr(h, Add(pbi.PebBaseAddress, 0x20));
    if (pp == IntPtr.Zero) return null;
    byte[] us = Read(h, Add(pp, 0x38), 16);
    if (us == null) return null;
    int len = BitConverter.ToUInt16(us, 0);
    long buf = BitConverter.ToInt64(us, 8);
    if (len <= 0 || buf == 0) return null;
    byte[] bytes = Read(h, new IntPtr(buf), len);
    if (bytes == null) return null;
    return Encoding.Unicode.GetString(bytes).TrimEnd('\\');
  }

  static IntPtr Add(IntPtr p, int off) { return new IntPtr(p.ToInt64() + off); }

  static byte[] Read(IntPtr h, IntPtr addr, int size) {
    byte[] b = new byte[size];
    IntPtr got;
    if (!ReadProcessMemory(h, addr, b, new IntPtr(size), out got)) return null;
    return b;
  }

  static IntPtr ReadPtr(IntPtr h, IntPtr addr) {
    byte[] b = Read(h, addr, 8);
    if (b == null) return IntPtr.Zero;
    return new IntPtr(BitConverter.ToInt64(b, 0));
  }
}
`;

// WMI has no cwd, so every cwd comes from the process PEB - one PowerShell call, one Add-Type, all processes.
function winScript() {
  return [
    "$ErrorActionPreference='SilentlyContinue'",
    "$compiled=$true",
    "$src=@'",
    CSHARP.trim(),
    "'@",
    "try { Add-Type -TypeDefinition $src -ErrorAction Stop } catch { $compiled=$false }",
    "$rows=New-Object System.Collections.ArrayList",
    "foreach ($p in Get-CimInstance Win32_Process) {",
    "  $id=[int]$p.ProcessId",
    "  $cwd=$null",
    "  $start=$null",
    "  if ($compiled) { try { $info=[WtPeb]::Info($id); if ($info) { $cwd=$info.Cwd; if ($info.Start -gt 0) { $start=$info.Start } } } catch { $cwd=$null; $start=$null } }",
    "  [void]$rows.Add([pscustomobject]@{ pid=$id; ppid=[int]$p.ParentProcessId; cmd=[string]$p.CommandLine; cwd=$cwd; start=$start })",
    "}",
    "ConvertTo-Json -Compress -InputObject @($rows)",
  ].join("\n");
}

function parseRows(text) {
  const t = String(text || "").trim();
  if (!t) return [];
  let body = t;
  const at = t.search(/[[{]/);
  if (at > 0) body = t.slice(at);
  let v;
  try {
    // PowerShell does not escape every control character in a CommandLine; one stray 0x1A anywhere would make the
    // whole table unparseable, so blank them first (the same rule proc-tree.mjs uses).
    v = JSON.parse(body.replace(/[\x00-\x1f]/g, " "));
  } catch {
    return [];
  }
  const arr = Array.isArray(v) ? v : [v];
  const out = [];
  for (const r of arr) {
    const pid = Number(r?.pid);
    if (!Number.isInteger(pid) || pid <= 0) continue;
    const ppid = Number(r?.ppid);
    const start = Number(r?.start);
    out.push({
      pid,
      ppid: Number.isInteger(ppid) ? ppid : 0,
      cmd: String(r?.cmd ?? ""),
      cwd: typeof r?.cwd === "string" && r.cwd ? r.cwd : null,
      // Same ISO form proc-tree's processStart() returns, so the two compare with ===.
      start: Number.isFinite(start) && start > 0 ? new Date(start).toISOString() : null,
    });
  }
  return out;
}

function winProcesses() {
  const out = execFileSync("powershell", ["-NoProfile", "-NonInteractive", "-Command", winScript()], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
    windowsHide: true,
    maxBuffer: 64 * 1024 * 1024,
    timeout: 60_000,
  });
  return parseRows(out);
}

function posixProcesses() {
  const rows = [];
  const ps = execFileSync("ps", ["-eo", "pid=,ppid=,lstart=,args="], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
    maxBuffer: 64 * 1024 * 1024,
    timeout: 20_000,
    env: { ...process.env, LC_ALL: "C" },
  });
  for (const line of String(ps).split(/\r?\n/)) {
    const row = parsePsLine(line);
    if (row) rows.push({ pid: row.pid, ppid: row.ppid, cmd: row.cmd, cwd: null, start: row.start });
  }
  if (fs.existsSync("/proc/self/cwd")) {
    for (const r of rows) {
      try {
        r.cwd = fs.readlinkSync(`/proc/${r.pid}/cwd`).replace(/ \(deleted\)$/, "");
      } catch {}
    }
  } else {
    // No procfs: one lsof for every pid, matched back to the `ps` rows.
    try {
      const out = execFileSync("lsof", ["-a", "-d", "cwd", "-Fpn"], {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "ignore"],
        maxBuffer: 64 * 1024 * 1024,
        timeout: 20_000,
      });
      const byPid = new Map(rows.map((r) => [r.pid, r]));
      let cur = null;
      for (const line of String(out).split(/\r?\n/)) {
        if (line.startsWith("p")) cur = Number(line.slice(1));
        else if (line.startsWith("n") && cur) {
          const row = byPid.get(cur);
          if (row) row.cwd = line.slice(1);
        }
      }
    } catch {}
  }
  return rows;
}

// [{pid, ppid, cmd, cwd, start}] for every process this user can inspect; cwd/start are null when unreadable.
// Any failure gives an empty list - finish() then fails closed with `FAIL scan`.
export function listProcesses() {
  try {
    return IS_WIN ? winProcesses() : posixProcesses();
  } catch {
    return [];
  }
}

// Absolute cwd of one process, or null (gone, unreadable, not ours). Reads the same table, so it costs a scan.
export function cwdOf(pid) {
  const n = Number(pid);
  if (!Number.isInteger(n) || n <= 0) return null;
  const row = listProcesses().find((r) => r.pid === n);
  if (!row?.cwd) return null;
  try {
    return path.resolve(row.cwd);
  } catch {
    return null;
  }
}

// ------------------------------------------------------------------ holders

export function mcpPatterns(env = process.env) {
  const raw = env.ORCH_WT_MCP_PATTERNS;
  if (raw === undefined) return [...DEFAULT_MCP];
  return String(raw)
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

// Split a command line into words: double quotes (Windows) and single quotes (posix) group, everything else splits.
function cmdTokens(cmd) {
  const out = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  let m;
  while ((m = re.exec(String(cmd || "")))) out.push(m[1] ?? m[2] ?? m[3]);
  return out;
}

// The program and its script argument only - never later argv. An OpenCode worker runs
// `opencode run ... <whole Mandate>` with the worktree as cwd, so the free text must never decide MCP.
export function mcpTarget(cmd) {
  const t = cmdTokens(cmd);
  if (!t.length) return "";
  let script = "";
  for (let i = 1; i < t.length; i++) {
    if (!t[i].startsWith("-")) {
      script = t[i];
      break;
    }
  }
  return script ? `${t[0]} ${script}` : t[0];
}

function isMcp(cmd, patterns) {
  const target = mcpTarget(cmd).toLowerCase();
  if (!target) return false;
  return patterns.some((p) => target.includes(String(p).toLowerCase()));
}

function ancestorsOf(pid, byPid) {
  const seen = new Set([pid]);
  let cur = byPid.get(pid)?.ppid;
  for (let i = 0; cur && i < 128 && !seen.has(cur); i++) {
    seen.add(cur);
    cur = byPid.get(cur)?.ppid;
  }
  return seen;
}

// Every process whose cwd is the worktree or inside it, minus this process, its ancestors and pid <= 4.
// `mcp` is the only thing the command line is used for; `start` came from the same handle as `cwd`.
export function scanHolders(procs, worktree, patterns = DEFAULT_MCP) {
  const byPid = new Map(procs.map((p) => [p.pid, p]));
  const skip = ancestorsOf(process.pid, byPid);
  const out = [];
  for (const p of procs) {
    if (!Number.isInteger(p.pid) || p.pid <= 4 || skip.has(p.pid)) continue;
    if (!isInside(p.cwd, worktree)) continue;
    out.push({ pid: p.pid, cmd: String(p.cmd || ""), mcp: isMcp(p.cmd, patterns), start: p.start ?? null });
  }
  return out;
}

// ------------------------------------------------------------------ kill

// Kill exactly one pid, never its descendants (no /T): a stale-ppid process must not be taken along.
function killOne(pid) {
  if (!Number.isInteger(pid) || pid <= 4) return false;
  try {
    if (IS_WIN) return spawnSync("taskkill", ["/PID", String(pid), "/F"], { windowsHide: true, stdio: "ignore", timeout: 15_000 }).status === 0;
    process.kill(pid, "SIGKILL");
    return true;
  } catch {
    return false;
  }
}

// Kill holder `h` only when the start time recorded with its cwd still matches the live process.
// `deps` lets tests inject `start` and `kill`.
export function killHolder(h, deps = {}) {
  const start = deps.start ?? processStart;
  const kill = deps.kill ?? killOne;
  if (!h || !h.start) return false;
  if (start(h.pid) !== h.start) return false;
  return kill(h.pid);
}

// ------------------------------------------------------------------ git

function git(dir, args, timeout = 120_000) {
  const r = spawnSync("git", ["-C", dir, ...args], {
    encoding: "utf8",
    windowsHide: true,
    timeout,
    maxBuffer: 32 * 1024 * 1024,
  });
  return {
    code: r.error ? 127 : (r.status ?? 1),
    out: String(r.stdout || ""),
    err: r.error ? String(r.error.message) : String(r.stderr || ""),
  };
}

function parseWorktrees(text) {
  const out = [];
  let cur = null;
  for (const line of String(text).split(/\r?\n/)) {
    if (line.startsWith("worktree ")) {
      cur = { path: line.slice("worktree ".length).trim(), branch: null, head: null };
      out.push(cur);
    } else if (!cur) continue;
    else if (line.startsWith("HEAD ")) cur.head = line.slice(5).trim();
    else if (line.startsWith("branch ")) cur.branch = line.slice(7).trim().replace(/^refs\/heads\//, "");
  }
  return out;
}

// ------------------------------------------------------------------ links

// Unlink a symlink/junction itself. On win32 a junction is removed by rmdir (unlink gets EPERM on a directory).
// Returns whether the link is gone: the caller refuses to hand a surviving link to `git worktree remove`.
function unlinkOne(p) {
  try {
    fs.unlinkSync(p);
    return true;
  } catch {}
  try {
    fs.rmdirSync(p);
    return true;
  } catch {}
  return false;
}

// Every symlink/junction in the tree, as worktree-relative paths with forward slashes (git's form).
// Never descends into a link, and skips `.git` (a linked worktree's `.git` is a file; a real one is git's).
export function walkLinks(root, rel = "", out = []) {
  let entries;
  try {
    entries = fs.readdirSync(path.join(root, rel), { withFileTypes: true });
  } catch {
    return out;
  }
  for (const e of entries) {
    if (e.name === ".git") continue;
    const r = rel ? `${rel}/${e.name}` : e.name;
    const p = path.join(root, r);
    let st;
    try {
      st = fs.lstatSync(p);
    } catch {
      continue;
    }
    if (st.isSymbolicLink()) {
      out.push(r); // never descend through it
      continue;
    }
    if (st.isDirectory()) walkLinks(root, r, out);
  }
  return out;
}

// Unlink every link git does not track, then re-walk and return the untracked links that survived (a lock, a
// permission problem): the caller translates any survivor into `FAIL links` and does not call git.
export function clearLinks(root, keep = new Set(), unlink = unlinkOne) {
  for (const rel of walkLinks(root)) {
    if (keep.has(rel)) continue;
    unlink(path.join(root, rel));
  }
  return walkLinks(root).filter((rel) => !keep.has(rel));
}

// ------------------------------------------------------------------ cli

function parseArgs(argv) {
  const o = { worktree: null, base: "main", deleteBranch: false, dryRun: false, json: false };
  const pos = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--base") {
      const v = argv[++i];
      if (!v || v.startsWith("-")) return { error: "--base needs a ref" };
      o.base = v;
    } else if (a.startsWith("--base=")) {
      const v = a.slice("--base=".length);
      if (!v || v.startsWith("-")) return { error: "--base needs a ref" };
      o.base = v;
    } else if (a === "--delete-branch") o.deleteBranch = true;
    else if (a === "--dry-run") o.dryRun = true;
    else if (a === "--json") o.json = true;
    else if (a === "-h" || a === "--help") return { help: true };
    else if (a.startsWith("-")) return { error: `unknown option ${a}` };
    else pos.push(a);
  }
  if (pos.length !== 1) return { error: pos.length ? "exactly one <worktree> path" : "missing <worktree>" };
  o.worktree = pos[0];
  return o;
}

const USAGE = "usage: node bin/wt-finish.mjs <worktree> [--base <ref>] [--delete-branch] [--dry-run] [--json]";

function trunc(s, n = CMD_MAX) {
  const t = String(s ?? "").replace(/\s+/g, " ").trim();
  return t.length > n ? `${t.slice(0, Math.max(0, n - 3))}...` : t;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function fail(check, lines) {
  return { ok: false, check, killed: [], busy: [], lines: Array.isArray(lines) ? lines : [lines] };
}

// The listing must show this process's own cwd: without it no holder row can be trusted, so nothing is unlinked or
// removed on a blind scan.
function scanOk(procs) {
  return procs.some((p) => p.pid === process.pid && p.cwd);
}

// ------------------------------------------------------------------ finish

// Run the whole sequence and return {ok, check, worktree, killed, busy, lines, [wouldKill]}.
// `deps` is a test seam only: {list: () => rows, unlink: (abs) => boolean}.
export async function finish(argv, env = process.env, deps = {}) {
  const opts = parseArgs(argv);
  if (opts.help) return { ok: true, check: "help", worktree: "", killed: [], busy: [], lines: [USAGE] };
  if (opts.error) return { ...fail("usage", [`FAIL usage ${opts.error}`]), usage: true, opts };

  const list = deps.list ?? listProcesses;
  const unlink = deps.unlink ?? unlinkOne;
  const wt = path.resolve(opts.worktree);
  const patterns = mcpPatterns(env);
  const res = (check, lines, extra = {}) => ({ ok: false, check, worktree: wt, killed: [], busy: [], lines, ...extra });
  const done = (v) => ({ ...v, worktree: v.worktree ?? wt, opts });

  // 1. registered, and not the main worktree.
  const listed = git(wt, ["worktree", "list", "--porcelain"]);
  if (listed.code !== 0) return done(res("not-a-worktree", [`FAIL not-a-worktree cannot read worktree list: ${trunc(listed.err, 120)}`]));
  const trees = parseWorktrees(listed.out);
  const want = normPath(wt);
  const mine = trees.find((t) => normPath(t.path) === want);
  if (!mine) return done(res("not-a-worktree", ["FAIL not-a-worktree not a registered worktree"]));
  if (trees[0] === mine) return done(res("not-a-worktree", ["FAIL not-a-worktree is the main worktree"]));
  const main = path.resolve(trees[0].path);

  // 1b. another worktree nested under this one: removing the parent would leave it registered against a dead path.
  const nested = trees.find((t) => t !== mine && isInside(t.path, wt));
  if (nested) return done(res("nested", [`FAIL nested ${path.resolve(nested.path)}`]));

  // 2. clean.
  const status = git(wt, ["status", "--porcelain"]);
  if (status.code !== 0) return done(res("git", [`FAIL git status failed: ${trunc(status.err, 120)}`]));
  if (status.out.trim()) return done(res("dirty", ["FAIL dirty"]));

  // 3. merged into --base in the main repo.
  const head = git(wt, ["rev-parse", "HEAD"]);
  if (head.code !== 0) return done(res("git", [`FAIL git rev-parse HEAD failed: ${trunc(head.err, 120)}`]));
  const anc = git(main, ["merge-base", "--is-ancestor", head.out.trim(), opts.base]);
  if (anc.code !== 0) return done(res("not-merged", ["FAIL not-merged"]));

  // 4. holders: kill MCP servers, refuse anything else.
  let procs = list();
  if (!scanOk(procs)) return done(res("scan", [`FAIL scan no cwd for pid ${process.pid} in the process listing`]));
  const holders = scanHolders(procs, wt, patterns);
  const busy = holders.filter((h) => !h.mcp);
  const mcp = holders.filter((h) => h.mcp);

  if (opts.dryRun) {
    const lines = [`DRY ${wt}`];
    for (const h of mcp) lines.push(`would-kill ${h.pid} ${trunc(h.cmd)}`);
    for (const h of busy) lines.push(`busy ${h.pid} ${trunc(h.cmd)}`);
    return done({ ok: busy.length === 0, check: busy.length ? "busy" : "ok", worktree: wt, killed: [], busy: busy.map((h) => ({ pid: h.pid, cmd: h.cmd })), wouldKill: mcp.map((h) => ({ pid: h.pid, cmd: h.cmd })), lines });
  }

  if (busy.length) {
    return done(
      res(
        "busy",
        busy.map((h) => `FAIL busy ${h.pid} ${trunc(h.cmd)}`),
        { busy: busy.map((h) => ({ pid: h.pid, cmd: h.cmd })) },
      ),
    );
  }

  const killed = [];
  for (const h of mcp) if (killHolder(h)) killed.push({ pid: h.pid, cmd: h.cmd });

  // 5. links out of the way. `git worktree remove` follows a junction into its target, so every untracked link in
  // the tree is unlinked first - and the walk is repeated right before each removal, refusing if one survived.
  const tracked = git(wt, ["ls-files", "-z"]);
  if (tracked.code !== 0) return done(res("git", [`FAIL git ls-files failed: ${trunc(tracked.err, 120)}`], { killed }));
  const keep = new Set(tracked.out.split("\0").filter(Boolean));
  const linksLeft = () => {
    const left = clearLinks(wt, keep, unlink);
    return left.length ? left : null;
  };
  let left = linksLeft();
  if (left) return done(res("links", [`FAIL links ${path.join(wt, left[0])}`], { killed }));

  // 6. remove; if it fails or the directory survives, wait, kill MCPs again and retry once.
  let rm = git(main, ["worktree", "remove", wt]);
  if (rm.code !== 0 || fs.existsSync(wt)) {
    await sleep(1000);
    procs = list();
    if (!scanOk(procs)) return done(res("scan", [`FAIL scan no cwd for pid ${process.pid} in the process listing`], { killed }));
    for (const h of scanHolders(procs, wt, patterns)) {
      if (!h.mcp) continue;
      if (killHolder(h)) killed.push({ pid: h.pid, cmd: h.cmd });
    }
    left = linksLeft();
    if (left) return done(res("links", [`FAIL links ${path.join(wt, left[0])}`], { killed }));
    rm = git(main, ["worktree", "remove", wt]);
  }
  if (rm.code !== 0 || fs.existsSync(wt)) {
    return done(res("remove", [`FAIL remove ${trunc(rm.err, 120) || "worktree remove failed"}`], { killed }));
  }

  // 7. the branch, only when asked, and only -d (merged).
  if (opts.deleteBranch) {
    if (!mine.branch) {
      return done(res("branch", ["FAIL branch no branch recorded (detached HEAD); the worktree was already removed"], { killed }));
    }
    const del = git(main, ["branch", "-d", mine.branch]);
    if (del.code !== 0) {
      return done(res("branch", [`FAIL branch ${trunc(del.err, 120) || "branch -d failed"}; the worktree was already removed`], { killed }));
    }
  }

  // 8. done.
  return done({ ok: true, check: "ok", worktree: wt, killed, busy: [], lines: [`OK ${wt} killed=${killed.length}`] });
}

export function render(r) {
  const opts = r.opts || {};
  if (opts.json) {
    return JSON.stringify({
      ok: Boolean(r.ok),
      check: r.check,
      worktree: r.worktree || "",
      killed: (r.killed || []).map((k) => ({ pid: k.pid, cmd: k.cmd })),
      busy: (r.busy || []).map((b) => ({ pid: b.pid, cmd: b.cmd })),
    });
  }
  return (r.lines || []).join("\n");
}

export function exitCode(r) {
  if (r.check === "help") return 0;
  if (r.ok) return 0;
  if (r.check === "usage" || r.check === "not-a-worktree" || r.check === "git") return 2;
  if (r.check === "dirty" || r.check === "not-merged") return 3;
  if (r.check === "busy") return 4;
  return 5; // remove, branch, links, nested, scan
}

async function main(argv) {
  const r = await finish(argv);
  const text = render(r);
  if (text) console.log(text);
  return exitCode(r);
}

if (LAUNCH === fileURLToPath(import.meta.url)) {
  process.exitCode = await main(process.argv.slice(2));
}
