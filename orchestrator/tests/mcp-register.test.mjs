// mcp-register: peer-mail is registered with Claude Code (user scope) from OpenCode's own entry.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { wantedPeerMail, registeredPeerMail, peerMailDrift, registerPeerMail } from "../bin/mcp-register.mjs";

const OC_CMD = ["node", "/opt/peer-mail/dist/index.js"];

function home({ oc, cc } = {}) {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), "mcpreg-"));
  if (oc !== undefined) {
    fs.mkdirSync(path.join(h, ".config", "opencode"), { recursive: true });
    fs.writeFileSync(path.join(h, ".config", "opencode", "opencode.json"), JSON.stringify(oc));
  }
  if (cc !== undefined) fs.writeFileSync(path.join(h, ".claude.json"), JSON.stringify(cc));
  return h;
}
const ocWith = (entry) => ({ mcp: { "peer-mail": entry } });
const LOCAL = { type: "local", command: OC_CMD };
const ccWith = (command, args) => ({ mcpServers: { "peer-mail": { type: "stdio", command, args, env: {} } } });

test("wantedPeerMail reads OpenCode's local peer-mail entry; nothing when absent, disabled, remote or malformed", () => {
  assert.deepEqual(wantedPeerMail(home({ oc: ocWith(LOCAL) })), { command: "node", args: ["/opt/peer-mail/dist/index.js"] });
  assert.deepEqual(wantedPeerMail(home({ oc: { mcp: { servers: { "peer-mail": LOCAL } } } })), { command: "node", args: ["/opt/peer-mail/dist/index.js"] }, "nested mcp.servers shape");
  assert.equal(wantedPeerMail(home()), null, "no opencode.json");
  assert.equal(wantedPeerMail(home({ oc: { mcp: {} } })), null, "no entry");
  assert.equal(wantedPeerMail(home({ oc: ocWith({ ...LOCAL, disabled: true }) })), null, "disabled");
  assert.equal(wantedPeerMail(home({ oc: ocWith({ type: "remote", url: "https://x" }) })), null, "remote");
  assert.equal(wantedPeerMail(home({ oc: ocWith({ type: "local", command: [] }) })), null, "empty command");
  const bad = home();
  fs.mkdirSync(path.join(bad, ".config", "opencode"), { recursive: true });
  fs.writeFileSync(path.join(bad, ".config", "opencode", "opencode.json"), "{ not json");
  assert.equal(wantedPeerMail(bad), null, "unparseable");
});

test("peerMailDrift: none when registered identically or when OpenCode has no entry; drift when missing or different", () => {
  assert.equal(peerMailDrift(home({ oc: ocWith(LOCAL), cc: ccWith("node", ["/opt/peer-mail/dist/index.js"]) })), null);
  assert.equal(peerMailDrift(home({ cc: {} })), null, "nothing wanted");
  const missing = peerMailDrift(home({ oc: ocWith(LOCAL), cc: { mcpServers: {} } }));
  assert.equal(missing.registered, null);
  const differs = peerMailDrift(home({ oc: ocWith(LOCAL), cc: ccWith("node", ["/old/index.js"]) }));
  assert.deepEqual(differs.registered, { command: "node", args: ["/old/index.js"] });
  assert.equal(registeredPeerMail(home({ oc: ocWith(LOCAL) })), null, "no ~/.claude.json at all");
});

test("registerPeerMail: adds when missing, replaces when different, does nothing when current", () => {
  const calls = [];
  const run = (a) => calls.push(a.join(" "));
  const logs = [];
  assert.equal(registerPeerMail({ home: home({ oc: ocWith(LOCAL), cc: {} }), run, log: (l) => logs.push(l) }), "registered");
  assert.deepEqual(calls, ["mcp add -s user peer-mail -- node /opt/peer-mail/dist/index.js"]);
  calls.length = 0;
  assert.equal(registerPeerMail({ home: home({ oc: ocWith(LOCAL), cc: ccWith("node", ["/old/index.js"]) }), run, log: () => {} }), "registered");
  assert.deepEqual(calls, ["mcp remove -s user peer-mail", "mcp add -s user peer-mail -- node /opt/peer-mail/dist/index.js"]);
  calls.length = 0;
  assert.equal(registerPeerMail({ home: home({ oc: ocWith(LOCAL), cc: ccWith("node", ["/opt/peer-mail/dist/index.js"]) }), run, log: () => {} }), "ok");
  assert.deepEqual(calls, [], "current: the CLI is not called");
});

test("registerPeerMail: dry run calls nothing; a failing or missing CLI warns and never throws", () => {
  const h = home({ oc: ocWith(LOCAL), cc: {} });
  let called = false;
  const logs = [];
  assert.equal(registerPeerMail({ home: h, dryRun: true, run: () => (called = true), log: (l) => logs.push(l) }), "skipped");
  assert.equal(called, false);
  assert.match(logs[0], /^would register MCP peer-mail/);
  const warn = [];
  const boom = () => {
    throw Object.assign(new Error("spawnSync claude ENOENT\nmore"), { code: "ENOENT" });
  };
  assert.equal(registerPeerMail({ home: h, run: boom, log: (l) => warn.push(l) }), "failed");
  assert.match(warn[0], /^warning: could not register MCP peer-mail .*ENOENT\); run: claude mcp add -s user peer-mail -- node \/opt\/peer-mail\/dist\/index\.js$/);
});

test("OpenCode-only machine (no ~/.claude.json): out of scope, nothing registered, no drift", () => {
  const h = home({ oc: ocWith(LOCAL) });
  fs.mkdirSync(path.join(h, ".claude", "commands"), { recursive: true }); // what this installer itself creates
  assert.equal(peerMailDrift(h), null, "~/.claude/ alone does not mean Claude Code is installed");
  let called = false;
  assert.equal(registerPeerMail({ home: h, run: () => (called = true), log: () => {} }), "ok");
  assert.equal(called, false);
  fs.writeFileSync(path.join(h, ".claude.json"), "{}");
  assert.notEqual(peerMailDrift(h), null, "~/.claude.json puts it in scope");
});

test("install.mjs: --check warns about a missing peer-mail but still passes; ORCH_SKIP_MCP silences it", async () => {
  const { spawnSync } = await import("node:child_process");
  const INSTALL = path.resolve(import.meta.dirname, "..", "bin", "install.mjs");
  const h = home({ oc: ocWith(LOCAL), cc: { mcpServers: {} } });
  const run = (args, extra = {}) =>
    spawnSync(process.execPath, [INSTALL, ...args], { env: { ...process.env, ORCH_HOME: h, ORCH_SKIP_ROUTING: "1", ...extra }, encoding: "utf8" });
  const inst = run([], { ORCH_SKIP_MCP: "1" }); // files only: the real CLI is never spawned
  assert.equal(inst.status, 0, inst.stderr);
  assert.doesNotMatch(inst.stdout, /MCP/);
  const chk = run(["--check"]);
  assert.equal(chk.status, 0, chk.stdout + chk.stderr);
  assert.match(chk.stdout, /^WARN MCP peer-mail not registered in Claude Code user scope \(OpenCode runs: node \/opt\/peer-mail\/dist\/index\.js\) — run install$/m);
  assert.match(chk.stdout, /check: OK/);
  const quiet = run(["--check"], { ORCH_SKIP_MCP: "1" });
  assert.equal(quiet.status, 0);
  assert.doesNotMatch(quiet.stdout, /MCP/);
});
