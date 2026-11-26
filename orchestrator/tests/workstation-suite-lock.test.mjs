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
