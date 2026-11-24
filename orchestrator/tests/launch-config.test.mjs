// Launch config: precedence, desktop argv, detection (stub xdg-mime), CLI, and the systemd installer's first-time step.
import { test, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { launchPlan } from "../bin/orphan-notice.mjs";
import { detectDefaultMode, parseChoice, choiceConfig, readLaunchConfig, writeLaunchConfig, effectiveLaunch } from "../bin/launch-config.mjs";

const BIN = path.resolve(import.meta.dirname, "..", "bin");
const CLI = path.join(BIN, "launch-config.mjs");
const INSTALL = path.resolve(import.meta.dirname, "..", "ops", "systemd", "install.mjs");
const CLEAN = [];
after(() => CLEAN.forEach((d) => fs.rmSync(d, { recursive: true, force: true })));
const mkdtemp = () => {
  const d = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "orch-launch-")));
  CLEAN.push(d);
  return d;
};
const cfgFile = (h) => path.join(h, ".config", "orchestrator", "launch.json");

function withEnv(env, fn) {
  const keys = ["ORCH_HOME", "ORCH_LAUNCH_CMD", "PATH", ...Object.keys(env)];
  const saved = Object.fromEntries(keys.map((k) => [k, process.env[k]]));
  Object.assign(process.env, env);
  for (const k of Object.keys(env)) if (env[k] === undefined) delete process.env[k];
  try {
    return fn();
  } finally {
    for (const k of keys) saved[k] === undefined ? delete process.env[k] : (process.env[k] = saved[k]);
  }
}
/** PATH dir holding an xdg-mime stub that prints `handler` (empty = nothing). */
function mimeStub(handler) {
  const d = mkdtemp();
  fs.writeFileSync(path.join(d, "xdg-mime"), `#!/bin/sh\n${handler ? `echo ${handler}\n` : ""}`, { mode: 0o755 });
  return `${d}${path.delimiter}${process.env.PATH}`;
}

test("detectDefaultMode: stubbed xdg-mime empty -> terminal, handler -> desktop; failure never throws", () => {
  withEnv({ PATH: mimeStub("") }, () => assert.equal(detectDefaultMode(), "terminal"));
  withEnv({ PATH: mimeStub("com.anthropic.Claude.desktop") }, () => assert.equal(detectDefaultMode(), "desktop"));
  assert.equal(detectDefaultMode(() => { throw new Error("boom"); }), "terminal");
  assert.equal(detectDefaultMode(() => "x.desktop\n"), "desktop");
});

test("precedence: ORCH_LAUNCH_CMD > launch.json > detected", () => {
  const h = mkdtemp();
  const path1 = mimeStub("com.anthropic.Claude.desktop");
  withEnv({ ORCH_HOME: h, ORCH_LAUNCH_CMD: undefined, PATH: path1 }, () => {
    assert.deepEqual(effectiveLaunch(), { mode: "desktop", source: "detected" });
    writeLaunchConfig({ mode: "terminal" });
    assert.deepEqual(effectiveLaunch(), { mode: "terminal", source: "config" });
    process.env.ORCH_LAUNCH_CMD = "my-launcher {stream}";
    assert.deepEqual(effectiveLaunch(), { mode: "custom", cmd: "my-launcher {stream}", source: "env" });
    assert.deepEqual(launchPlan("s1", {}).shell, "my-launcher s1");
  });
  fs.writeFileSync(cfgFile(h), "not json");
  withEnv({ ORCH_HOME: h, ORCH_LAUNCH_CMD: undefined, PATH: path1 }, () => assert.equal(readLaunchConfig(), null));
});

test("custom mode in launch.json runs its cmd via sh with substitutions", () => {
  const h = mkdtemp();
  withEnv({ ORCH_HOME: h, ORCH_LAUNCH_CMD: undefined }, () => {
    writeLaunchConfig({ mode: "custom", cmd: "run {stream} {harness}" });
    assert.equal(launchPlan("s1", { held_by: "oc" }).shell, "run s1 oc");
  });
});

test("desktop mode: exact xdg-open argv; oc-held stays on the terminal; missing repo omits folder", () => {
  const h = mkdtemp();
  const repo = mkdtemp();
  withEnv({ ORCH_HOME: h, ORCH_LAUNCH_CMD: undefined }, () => {
    writeLaunchConfig({ mode: "desktop" });
    const p = launchPlan("my-stream", { repo, held_by: "cc" });
    assert.deepEqual(p.argv, ["xdg-open", `claude://code/new?q=%2Ffrood-next%20my-stream&folder=${encodeURIComponent(repo)}`]);
    assert.equal(p.cwd, repo);
    assert.deepEqual(launchPlan("my-stream", { repo }).argv, p.argv); // unheld
    assert.deepEqual(launchPlan("my-stream", { repo, held_by: "oc" }).argv, ["xdg-terminal-exec", "--", "opencode", "--prompt", "/frood-next my-stream"]);
    assert.deepEqual(launchPlan("my-stream", { repo: path.join(h, "gone") }).argv, ["xdg-open", "claude://code/new?q=%2Ffrood-next%20my-stream"]);
    assert.deepEqual(launchPlan("my-stream", undefined).argv, ["xdg-open", "claude://code/new?q=%2Ffrood-next%20my-stream"]);
    writeLaunchConfig({ mode: "terminal" });
    assert.deepEqual(launchPlan("my-stream", { repo }).argv, ["xdg-terminal-exec", "--", "claude", "/frood-next my-stream"]);
  });
});

const cli = (h, args, env = {}) =>
  spawnSync(process.execPath, [CLI, ...args], { env: { ...process.env, ORCH_HOME: h, ORCH_LAUNCH_CMD: "", ...env }, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });

test("CLI: prints source, --set writes, custom needs --cmd", () => {
  const h = mkdtemp();
  const env = { PATH: mimeStub("") };
  assert.match(cli(h, [], env).stdout, /launch mode: terminal \(source: detected\)/);
  assert.equal(cli(h, ["--set", "desktop"], env).status, 0);
  assert.deepEqual(JSON.parse(fs.readFileSync(cfgFile(h), "utf8")), { mode: "desktop" });
  assert.match(cli(h, [], env).stdout, /launch mode: desktop \(source: config\)/);
  assert.match(cli(h, [], { ...env, ORCH_LAUNCH_CMD: "x" }).stdout, /\(source: env\)/);
  assert.equal(cli(h, ["--set", "custom"], env).status, 2);
  assert.equal(cli(h, ["--set", "bogus"], env).status, 2);
  assert.equal(cli(h, ["--set", "custom", "--cmd", "go {stream}"], env).status, 0);
  assert.deepEqual(JSON.parse(fs.readFileSync(cfgFile(h), "utf8")), { mode: "custom", cmd: "go {stream}" });
});

test("CLI --ask on a non-TTY writes the detected mode and never overwrites an existing file", () => {
  const h = mkdtemp();
  const r = cli(h, ["--ask"], { PATH: mimeStub("com.anthropic.Claude.desktop") });
  assert.match(r.stdout, /not interactive: saved the detected launch mode "desktop".*will not be re-detected/);
  assert.deepEqual(JSON.parse(fs.readFileSync(cfgFile(h), "utf8")), { mode: "desktop" });
  fs.writeFileSync(cfgFile(h), '{"mode":"terminal"}');
  const r2 = cli(h, ["--ask"], { PATH: mimeStub("com.anthropic.Claude.desktop") });
  assert.match(r2.stdout, /already exists/);
  assert.deepEqual(JSON.parse(fs.readFileSync(cfgFile(h), "utf8")), { mode: "terminal" });
});

test("systemd install.mjs first-time step writes launch.json only when absent (no systemctl)", () => {
  const h = mkdtemp();
  const run = (mime) => spawnSync(process.execPath, [INSTALL], { env: { ...process.env, ORCH_HOME: h, ORCH_LAUNCH_CMD: "", ORCH_INSTALL_NO_SYSTEMD: "1", PATH: mimeStub(mime) }, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  const r = run("com.anthropic.Claude.desktop");
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(JSON.parse(fs.readFileSync(cfgFile(h), "utf8")), { mode: "desktop" });
  assert.match(r.stdout, /launch-config\.mjs --set desktop\|terminal\|custom/);
  fs.writeFileSync(cfgFile(h), '{"mode":"terminal"}');
  assert.equal(run("com.anthropic.Claude.desktop").status, 0);
  assert.deepEqual(JSON.parse(fs.readFileSync(cfgFile(h), "utf8")), { mode: "terminal" });
});

test("parseChoice / choiceConfig: numbers, words, empty, invalid, out of range", () => {
  for (const [a, m] of [["1", "desktop"], ["2", "terminal"], ["3", "custom"], [" Desktop ", "desktop"], ["terminal", "terminal"]]) assert.equal(parseChoice(a, "x"), m);
  for (const a of ["", "  ", "0", "4", "99", "-1", "banana", undefined]) assert.equal(parseChoice(a, "terminal"), "terminal");
  assert.deepEqual(choiceConfig("custom", " go {stream} ", "desktop"), { mode: "custom", cmd: "go {stream}" });
  assert.deepEqual(choiceConfig("custom", "  ", "desktop"), { mode: "desktop" });
  assert.deepEqual(choiceConfig("terminal", "ignored", "desktop"), { mode: "terminal" });
});

test("CLI --ask on a real TTY: EOF at the prompt takes the detected default, writes it, exits 0", () => {
  const h = mkdtemp();
  const script = `
import os, pty, sys, time
pid, fd = pty.fork()
if pid == 0:
    os.execv(sys.argv[1], [sys.argv[1], sys.argv[2], "--ask"])
time.sleep(1.0)
os.write(fd, b"\x04")
out = b""
try:
    while True:
        d = os.read(fd, 4096)
        if not d: break
        out += d
except OSError:
    pass
_, st = os.waitpid(pid, 0)
sys.stdout.write(out.decode(errors="replace"))
sys.exit(os.waitstatus_to_exitcode(st))
`;
  const r = spawnSync("python3", ["-I", "-c", script, process.execPath, CLI], { env: { ...process.env, ORCH_HOME: h, ORCH_LAUNCH_CMD: "", PATH: mimeStub("com.anthropic.Claude.desktop") }, encoding: "utf8", timeout: 20000 });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.match(r.stdout, /launch mode: desktop/);
  assert.deepEqual(JSON.parse(fs.readFileSync(cfgFile(h), "utf8")), { mode: "desktop" });
});
