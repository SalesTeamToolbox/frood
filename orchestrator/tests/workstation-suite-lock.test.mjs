import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "os";
import path from "path";
import { fileURLToPath } from "node:url";
import { spawn, spawnSync } from "node:child_process";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const LOCK = path.join(HERE, "..", "ops", "workstation", "suite-lock.sh");
const REPO_ROOT = path.join(HERE, "..", "..");
const MAKEFILE = path.join(REPO_ROOT, "Makefile");

const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

function tmp() {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "ws-lock-"));
  CLEAN.push(d);
  return d;
}

// Runs `timeout 60 bash <scriptFile>` from `cwd`, killing the whole promise if it exceeds 65 s.
function runHolder(cwd, scriptFile) {
  return new Promise((resolve) => {
    const child = spawn("timeout", ["60", "bash", scriptFile], { cwd, encoding: "utf8" });
    let out = "";
    child.stdout.on("data", (d) => { out += d; });
    const t = setTimeout(() => { child.kill("SIGKILL"); resolve({ code: -1, out: "TIMEOUT\n" + out }); }, 65000);
    child.on("close", (code) => { clearTimeout(t); resolve({ code, out }); });
  });
}

// A holder: source the lock, record times around the critical section, print one line.
// `n` = holder name; `root` = shared SUITE_LOCK_ROOT.
function holderScript(n, root) {
  return [
    "set -u",
    `source "${LOCK}"`,
    `export SUITE_LOCK_ROOT="${root}"`,
    "export SUITE_LOCK_POLL=1 SUITE_LOCK_BEAT=1 SUITE_LOCK_STALE=6 SUITE_LOCK_WAITER_STALE=5",
    "start=$(date +%s.%N)",
    `suite_lock_acquire "holder ${n}"`,
    "hs=$(date +%s.%N)",
    "sleep 0.2",
    "he=$(date +%s.%N)",
    "suite_lock_release",
    "end=$(date +%s.%N)",
    `echo "${n} $start $hs $he $end"`,
  ].join("\n");
}

function parse(out) {
  const line = out.trim().split(/\n/).find((l) => /^[AB] \d+\.\d+/.test(l));
  assert.ok(line, "holder data line not found in: " + out);
  const [, start, hs, he, end] = line.split(/\s+/).map(Number);
  return { start, hs, he, end };
}

test("two holders from different repos serialize on one box-wide lock", async () => {
  const root = tmp();

  // repoA: a git repo; repoB: not a git repo. Both share SUITE_LOCK_ROOT.
  const repoA = tmp();
  fs.mkdirSync(repoA, { recursive: true });
  const ga = spawnSync("git", ["init"], { cwd: repoA, stdio: "ignore" });
  assert.equal(ga.status, 0, "repoA is a git repo");

  const repoB = tmp();
  fs.mkdirSync(repoB, { recursive: true });

  const fa = path.join(repoA, "holderA.sh");
  const fb = path.join(repoB, "holderB.sh");
  fs.writeFileSync(fa, holderScript("A", root));
  fs.writeFileSync(fb, holderScript("B", root));

  // Run both concurrently from different cwds.
  const [ra, rb] = await Promise.all([runHolder(repoA, fa), runHolder(repoB, fb)]);
  assert.equal(ra.code, 0, "holder A exited 0: " + ra.out);
  assert.equal(rb.code, 0, "holder B exited 0: " + rb.out);

  const pa = parse(ra.out);
  const pb = parse(rb.out);
  assert.ok(pa.hs < pa.he, "holder A actually held the lock");
  assert.ok(pb.hs < pb.he, "holder B actually held the lock");

  // The two critical sections must not overlap.
  assert.ok(
    pa.he <= pb.hs || pb.he <= pa.hs,
    `critical sections overlap: A[${pa.hs},${pa.he}] B[${pb.hs},${pb.he}]`
  );
});

test("make -n test recipe sources, acquires and releases the box-wide lock", () => {
  const makefile = fs.readFileSync(MAKEFILE, "utf8");
  assert.ok(makefile.includes("orchestrator/ops/workstation/suite-lock.sh"), "recipe sources suite-lock.sh");
  assert.ok(makefile.includes("suite_lock_acquire"), "recipe acquires the lock");
  assert.ok(makefile.includes("suite_lock_release"), "recipe releases the lock");

  // SUITE_LOCK=0 must not remove the recipe text (it only skips at run time).
  const r = spawnSync("make", ["-n", "test"], {
    cwd: REPO_ROOT,
    env: { ...process.env, SUITE_LOCK: "0" },
    encoding: "utf8",
  });
  assert.equal(r.status, 0, "make -n test succeeded: " + r.stderr);
  const out = r.stdout;
  assert.ok(out.includes("suite-lock.sh"), "SUITE_LOCK=0 make -n test prints the source line: " + out);
  assert.ok(out.includes("suite_lock_acquire"), "SUITE_LOCK=0 make -n test prints the acquire line: " + out);
  assert.ok(out.includes("suite_lock_release"), "SUITE_LOCK=0 make -n test prints the release line: " + out);
});

// ----------------------------------------------------------- (a) Makefile test trap (ws-guard-followups)

// Poll `fn` every 50 ms up to `capMs`; throw (failing the test) past the cap.
async function pollFor(fn, capMs, what) {
  const deadline = Date.now() + capMs;
  for (;;) {
    if (fn()) return;
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${what}`);
    await new Promise((r) => setTimeout(r, 50));
  }
}

function writeFake(dir, name, body) {
  const p = path.join(dir, name);
  fs.writeFileSync(p, body);
  fs.chmodSync(p, 0o755);
  return p;
}

test("make test: SIGTERM to the make pid kills the pytest child and releases the lock", { timeout: 30_000 }, async () => {
  const root = tmp();
  const bin = tmp();
  const pidfile = path.join(bin, "pytest.pid");
  const fake = writeFake(bin, "fake-pytest", '#!/bin/sh\necho $$ > "$FAKE_PYTEST_PIDFILE"\nexec sleep 60\n');
  const child = spawn("make", ["-C", REPO_ROOT, "test", `PYTEST=${fake}`], {
    env: { ...process.env, SUITE_LOCK_ROOT: root, SUITE_LOCK_POLL: "0.2", FAKE_PYTEST_PIDFILE: pidfile },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let fakePid = null;
  try {
    await pollFor(() => fs.existsSync(pidfile) && fs.existsSync(path.join(root, "held")), 10000, "fake pytest start and lock held");
    fakePid = Number(fs.readFileSync(pidfile, "utf8").trim());
    assert.ok(Number.isInteger(fakePid) && fakePid > 0, "the pidfile holds the fake pytest pid");
    child.kill("SIGTERM"); // the make pid only, never the fake directly
    await pollFor(() => {
      let alive = true;
      try {
        process.kill(fakePid, 0);
      } catch {
        alive = false;
      }
      return !alive && !fs.existsSync(path.join(root, "held"));
    }, 5000, "fake pytest gone and lock released within 5 s of SIGTERM");
    await pollFor(() => child.exitCode !== null || child.signalCode !== null, 5000, "make exit");
    assert.ok(child.exitCode !== null || child.signalCode !== null, "make is gone after SIGTERM");
  } finally {
    try {
      if (child.exitCode === null && child.signalCode === null && child.pid) child.kill("SIGKILL");
    } catch {}
    if (fakePid) {
      try {
        process.kill(fakePid, "SIGKILL");
      } catch {}
    }
  }
});

test("make test: a pytest that exits 0 leaves make at 0 with the lock released", { timeout: 30_000 }, () => {
  const root = tmp();
  const bin = tmp();
  const fake = writeFake(bin, "ok-pytest", "#!/bin/sh\nexit 0\n");
  const r = spawnSync("make", ["-C", REPO_ROOT, "test", `PYTEST=${fake}`], {
    env: { ...process.env, SUITE_LOCK_ROOT: root, SUITE_LOCK_POLL: "0.2" },
    encoding: "utf8",
    timeout: 25000,
  });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(fs.existsSync(path.join(root, "held")), false, "the normal path releases the lock");
});

test("make test trap with pytest not started (pid unset): SIGTERM still exits 143 and releases the lock", { timeout: 30_000 }, async () => {
  // The race senior review caught: a signal between trap installation and
  // `pid=$!` (pytest never started). The trap block is extracted from the
  // Makefile test recipe itself (`$$` unescaped the way make unescapes it),
  // so this runs the shipped code, not a copy: a recipe reshape breaks the
  // extraction loudly instead of silently testing a stale copy.
  const recipe = fs.readFileSync(MAKEFILE, "utf8").split("\n");
  const start = recipe.findIndex((l) => /^\s*pid=;/.test(l));
  const end = recipe.findIndex((l, i) => i > start && /trap cleanup_int INT/.test(l));
  assert.ok(start >= 0 && end > start, "the Makefile test recipe initialises pid and installs TERM/INT traps");
  const trapBlock = recipe
    .slice(start, end + 1)
    .map((l) => l.replace(/^\s+/, "").replace(/\s*\\$/, "").replace(/\$\$/g, "$"))
    .join("\n");
  assert.match(trapBlock, /if \[ -n "\$pid" \]/, "the trap guards the unset pid");

  const root = tmp();
  const bin = tmp();
  const sleeperFile = path.join(bin, "sleeper.pid");
  const harness = writeFake(bin, "trap-nopid.sh", [
    "#!/bin/bash",
    `source "${LOCK}"`,
    `export SUITE_LOCK_ROOT="${root}"`,
    "export SUITE_LOCK_POLL=0.2",
    'suite_lock_acquire "trap-nopid test" || exit 1',
    trapBlock,
    `sleep 60 & echo $! > "${sleeperFile}" # heartbeat stand-in: never exits on its own`,
    "wait # bare wait: hangs forever unless the trap skips the unset pid",
    "",
  ].join("\n"));
  const child = spawn("bash", [harness], { env: { ...process.env }, stdio: ["ignore", "pipe", "pipe"] });
  let sleeper = null;
  try {
    await pollFor(
      () => fs.existsSync(path.join(root, "held")) && fs.existsSync(sleeperFile),
      10000,
      "lock held with pytest never started",
    );
    sleeper = Number(fs.readFileSync(sleeperFile, "utf8").trim());
    assert.ok(Number.isInteger(sleeper) && sleeper > 0, "the sleeper pid was recorded");
    child.kill("SIGTERM"); // the harness shell only
    await pollFor(() => child.exitCode !== null || child.signalCode !== null, 5000, "trap exit within 5 s of SIGTERM");
    assert.equal(child.exitCode, 143, "the TERM trap exits 143 with pid unset");
    assert.equal(fs.existsSync(path.join(root, "held")), false, "the lock is released");
  } finally {
    try {
      if (child.exitCode === null && child.signalCode === null && child.pid) child.kill("SIGKILL");
    } catch {}
    if (sleeper) {
      try {
        process.kill(sleeper, "SIGKILL");
      } catch {}
    }
  }
});

// ----------------------------------------------------------- suite-lock-home-guard

// Runs `timeout <sec> bash <scriptFile>` with the given env; captures stdout+stderr.
// The external `timeout` bounds every run so a hung acquire cannot hang this suite.
function runBash(scriptFile, env, timeoutSec) {
  return spawnSync("timeout", [String(timeoutSec), "bash", scriptFile], { env, encoding: "utf8" });
}

function acquireScript(rootEnv, extra) {
  return [
    "set -u",
    `source "${LOCK}"`,
    "export SUITE_LOCK_POLL=0.2 SUITE_LOCK_BEAT=1 SUITE_LOCK_STALE=6 SUITE_LOCK_WAITER_STALE=5",
    ...(rootEnv ? [`export SUITE_LOCK_ROOT="${rootEnv}"`] : []),
    ...(extra || []),
    "suite_lock_acquire \"guard-test\" 2>&1",
    "code=$?",
    "echo ACQUIRE_CODE $code",
    "exit $code",
  ].join("\n");
}

test("HOME unset: getent passwd home becomes the lock root; lock acquired and released", () => {
  const home = tmp();
  const bin = tmp();
  writeFake(bin, "getent", `#!/bin/sh\necho "nobody:x:65534:65534:nobody:${home}:/bin/sh"\n`);

  const script = path.join(tmp(), "getent-home.sh");
  fs.writeFileSync(script, [
    "set -u",
    `source "${LOCK}"`,
    "export SUITE_LOCK_POLL=0.2 SUITE_LOCK_BEAT=1 SUITE_LOCK_STALE=6 SUITE_LOCK_WAITER_STALE=5",
    "suite_lock_acquire \"guard-test\" || { echo ACQUIRE_FAIL; exit 1; }",
    `echo "DIR ${home}/.local/state/frood-workstation/suite-lock"`,
    "[ -d \"$SUITE_LOCK_DIR/queue\" ] && echo QUEUE_OK || echo QUEUE_FAIL",
    "suite_lock_release",
    "echo RELEASED",
  ].join("\n"));
  fs.chmodSync(script, 0o755);

  const env = { ...process.env };
  delete env.HOME;
  env.PATH = `${bin}:${env.PATH ?? ""}`;

  const r = runBash(script, env, 15);
  assert.equal(r.status, 0, `expected acquire to succeed: ${r.stderr}`);
  assert.ok(
    r.stdout.includes(`DIR ${home}/.local/state/frood-workstation/suite-lock`),
    "lock root is the passwd home under /.local/state/frood-workstation/suite-lock: " + r.stdout,
  );
  assert.ok(r.stdout.includes("QUEUE_OK"), "queue dir exists while held: " + r.stdout);
  assert.ok(r.stdout.includes("RELEASED"), "release ran: " + r.stdout);
  assert.equal(
    fs.existsSync(path.join(home, ".local/state/frood-workstation/suite-lock/held")),
    false,
    "lock released: held removed",
  );
});

test("HOME unset with no passwd home: acquire fails fast with return 2 and ERROR line", () => {
  const bin = tmp();
  writeFake(bin, "getent", "#!/bin/sh\nexit 0\n"); // prints nothing -> no passwd home

  const script = path.join(tmp(), "nohome.sh");
  fs.writeFileSync(script, acquireScript(undefined));
  fs.chmodSync(script, 0o755);

  const env = { ...process.env };
  delete env.HOME;
  env.PATH = `${bin}:${env.PATH ?? ""}`;

  const start = Date.now();
  const r = runBash(script, env, 10);
  const elapsed = Date.now() - start;
  assert.ok(elapsed < 5000, `expected fail fast (<5 s), took ${elapsed} ms: ${r.stdout}`);
  assert.equal(r.status, 2, `expected status 2, got ${r.status}: ${r.stdout}`);
  assert.ok(
    r.stdout.includes("==> suite lock: ERROR: cannot place the box-wide lock"),
    "ERROR line present: " + r.stdout,
  );
  assert.ok(r.stdout.includes("ACQUIRE_CODE 2"), "propagated return 2: " + r.stdout);
});

test("unwritable SUITE_LOCK_ROOT: acquire returns 2 within 5 s, ERROR names the dir, no ticket left", () => {
  const parent = tmp();
  fs.chmodSync(parent, 0o500); // cannot create anything beneath it
  const root = path.join(parent, "lockedroot");

  const script = path.join(tmp(), "unwritable.sh");
  fs.writeFileSync(script, acquireScript(root));
  fs.chmodSync(script, 0o755);

  const env = { ...process.env };
  env.PATH = `${process.env.PATH ?? ""}`;

  const start = Date.now();
  const r = runBash(script, env, 6);
  const elapsed = Date.now() - start;
  assert.ok(elapsed < 5000, `expected fail fast (<5 s), took ${elapsed} ms: ${r.stdout}`);
  assert.equal(r.status, 2, `expected status 2, got ${r.status}: ${r.stdout}`);
  assert.ok(
    r.stdout.includes(`==> suite lock: ERROR: cannot create ${root}:`),
    "ERROR names the dir: " + r.stdout,
  );
  assert.ok(r.stdout.includes("ACQUIRE_CODE 2"), "propagated return 2: " + r.stdout);
  assert.equal(fs.existsSync(root), false, "no root dir created");
  assert.equal(fs.existsSync(path.join(root, "queue")), false, "no ticket/queue left behind");
  fs.chmodSync(parent, 0o755); // so the tmp() cleanup can remove the dir
});
