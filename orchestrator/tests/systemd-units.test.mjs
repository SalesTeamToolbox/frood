// The systemd units ship as templates (@NODE@/@REPO@/@BY@) rendered by
// ops/systemd/install.mjs. Hermetic: assert the templates supervise correctly and
// every placeholder they use is one the installer fills.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "ops", "systemd");

test("daemon unit supervises _run in the foreground with restarts", () => {
  const svc = fs.readFileSync(path.join(DIR, "orchestrator-desk-daemon.service"), "utf8");
  assert.match(svc, /^Type=simple$/m);
  assert.match(svc, /^Restart=always$/m);
  assert.match(svc, /^RestartSec=\d+$/m);
  assert.match(svc, /^RestartPreventExitStatus=3$/m); // exit 3 = live session owns the lock
  assert.match(svc, /^ExecStart=@NODE@ @REPO@\/bin\/desk\.mjs daemon _run --by @BY@ --interval \d+$/m);
  assert.doesNotMatch(svc, /daemon start/); // start double-forks: wrong under a supervisor
});

test("daemon unit: a stop or restart signals the daemon only, never the runs it launched", () => {
  const svc = fs.readFileSync(path.join(DIR, "orchestrator-desk-daemon.service"), "utf8");
  // control-group (the default) and mixed both kill the detached oc-worker critics/workers left in the cgroup.
  assert.match(svc, /^KillMode=process$/m);
});

test("every template placeholder is one install.mjs fills", () => {
  const installer = fs.readFileSync(path.join(DIR, "install.mjs"), "utf8");
  const filled = new Set([...installer.matchAll(/"(@[A-Z]+@)"/g)].map((m) => m[1]));
  assert.ok(filled.has("@PATH@"), "install.mjs fills @PATH@");
  for (const f of fs.readdirSync(DIR)) {
    if (!f.endsWith(".service")) continue;
    const text = fs.readFileSync(path.join(DIR, f), "utf8");
    for (const m of text.matchAll(/@[A-Z]+@/g)) {
      assert.ok(filled.has(m[0]), `${f} uses ${m[0]}, which install.mjs does not fill`);
    }
  }
  assert.ok(filled.size > 0);
});

test("desk-check timer still pages every 5 minutes", () => {
  const timer = fs.readFileSync(path.join(DIR, "orchestrator-desk-check.timer"), "utf8");
  assert.match(timer, /^OnCalendar=\*:0\/5$/m);
});

test("both service units set PATH via @PATH@", () => {
  for (const f of ["orchestrator-desk-daemon.service", "orchestrator-desk-check.service"]) {
    const text = fs.readFileSync(path.join(DIR, f), "utf8");
    assert.match(text, /^Environment=PATH=@PATH@$/m, `${f} sets Environment=PATH=@PATH@`);
  }
});

// loadUnitPath imports install.mjs hermetically: ORCH_INSTALL_NO_SYSTEMD=1 keeps the
// installer from writing unit files or calling systemctl while exposing the pure unitPath.
async function loadUnitPath() {
  process.env.ORCH_INSTALL_NO_SYSTEMD = "1";
  const mod = await import(path.join(DIR, "install.mjs"));
  return mod.unitPath;
}

test("unitPath: node dir first, existing-only, de-duped, ends with system dirs", async () => {
  const unitPath = await loadUnitPath();
  const nodeDir = "/opt/node/bin";
  const ocDir = "/opt/opencode/bin";
  const claudeDir = "/opt/claude/bin";
  const shims = "/tmp/x/.local/share/mise/shims";
  const localBin = "/tmp/x/.local/bin";
  const which = (cmd) => {
    if (cmd === "opencode") return ocDir + "/opencode";
    if (cmd === "claude") return claudeDir + "/claude";
    return null;
  };
  const existing = new Set([nodeDir, ocDir, claudeDir, shims, localBin, "/usr/local/bin", "/usr/bin", "/bin"]);
  const exists = (d) => existing.has(d);
  const p = unitPath({ node: nodeDir + "/node", which, home: "/tmp/x", exists });
  const parts = p.split(":");
  assert.equal(parts[0], nodeDir); // node's directory first
  assert.ok(parts.includes(ocDir), "opencode dir included");
  assert.ok(parts.includes(claudeDir), "claude dir included");
  assert.ok(parts.includes(shims), "mise shims included");
  assert.ok(parts.includes(localBin), ".local/bin included");
  assert.ok(parts.includes("/usr/local/bin"), "system dir included");
  assert.ok(parts.includes("/usr/bin"), "system dir included");
  assert.equal(parts[parts.length - 1], "/bin"); // ends with /bin
  assert.equal(new Set(parts).size, parts.length, "no duplicate directories");
});

test("unitPath: drops missing and duplicate directories", async () => {
  const unitPath = await loadUnitPath();
  const nodeDir = "/opt/node/bin";
  const shims = "/tmp/x/.local/share/mise/shims";
  const which = () => null; // opencode and claude not found
  const exists = (d) => d === nodeDir || d === "/usr/bin" || d === "/bin";
  const p = unitPath({ node: nodeDir + "/node", which, home: "/tmp/x", exists });
  const parts = p.split(":");
  assert.ok(parts.includes(nodeDir));
  assert.ok(!parts.includes(shims), "missing mise shims dropped");
  assert.equal(parts[0], nodeDir);
  assert.equal(parts[parts.length - 1], "/bin");
});

test("unitPath: opencode not found still returns a PATH", async () => {
  const unitPath = await loadUnitPath();
  const which = (cmd) => null;
  const exists = (d) => ["/usr/local/bin", "/usr/bin", "/bin"].includes(d);
  const p = unitPath({ node: "/opt/node/bin/node", which, home: "/tmp/x", exists });
  assert.ok(p, "returns a PATH even when opencode is not found");
  assert.ok(!p.includes("opencode"));
  assert.ok(p.includes("/usr/bin"));
  assert.ok(p.includes("/bin"));
});

test("install: opencode missing still installs a PATH and warns", () => {
  const INSTALL = path.join(DIR, "install.mjs");
  const nodeDir = path.dirname(process.execPath);
  const res = spawnSync(process.execPath, [INSTALL], {
    env: { ...process.env, ORCH_INSTALL_NO_SYSTEMD: "1", PATH: `${nodeDir}:/usr/local/bin:/usr/bin:/bin` },
    encoding: "utf8",
    timeout: 60000,
  });
  assert.equal(res.status, 0, res.stderr);
  assert.match(res.stderr, /opencode not found on PATH/);
});
