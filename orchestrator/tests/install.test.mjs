import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { renderForHarness, addManagedHeader, render, MANAGED, REPO_FWD } from "../bin/install.mjs";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const INSTALL = path.join(REPO, "bin", "install.mjs");

function freshHome() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "orch-home-"));
}
function run(home, ...args) {
  return spawnSync(process.execPath, [INSTALL, ...args], {
    env: { ...process.env, ORCH_HOME: home, ORCH_SKIP_ROUTING: "1", ORCH_SKIP_WORKSTATION: "1" },
    encoding: "utf8",
  });
}

test("renderForHarness keeps own tags, drops the other harness, strips markers", () => {
  const src = [
    "---",
    "description: x",
    'argument-hint: "[a]"  # cc-only',
    "agent: build  # oc-only",
    "---",
    "shared",
    "<!-- cc-only -->",
    "claude line",
    "<!-- /cc-only -->",
    "<!-- oc-only -->",
    "opencode line",
    "<!-- /oc-only -->",
    "inline cc <!-- cc-only -->",
  ].join("\n");
  const cc = renderForHarness(src, "cc");
  const oc = renderForHarness(src, "oc");
  assert.match(cc, /argument-hint: "\[a\]"\n/);
  assert.doesNotMatch(cc, /agent: build|opencode line|cc-only|oc-only/);
  assert.match(cc, /claude line/);
  assert.match(cc, /inline cc$/);
  assert.match(oc, /agent: build\n/);
  assert.doesNotMatch(oc, /argument-hint|claude line|inline cc|cc-only|oc-only/);
  assert.match(oc, /opencode line/);
});

test("unclosed block is an error, not silent truncation", () => {
  assert.throws(() => renderForHarness("a\n<!-- oc-only -->\nb", "cc"), /unclosed/);
});

test("managed header goes after frontmatter, never before it", () => {
  const out = addManagedHeader("---\ndescription: x\n---\nbody\n");
  assert.ok(out.startsWith("---\ndescription: x\n---\n" + MANAGED + "\nbody"));
  assert.ok(addManagedHeader("plain\n").startsWith(MANAGED));
});

test("install-time tokens render the repo and the install home, in .md and .js alike", () => {
  const home = freshHome();
  const prev = process.env.ORCH_HOME;
  process.env.ORCH_HOME = home;
  try {
    const src = path.join(freshHome(), "both.md");
    fs.writeFileSync(src, "---\ndescription: x\n---\nrepo {{ORCH_REPO}} home {{HOME}}\n");
    const md = render(src, "cc");
    assert.ok(md.includes(`repo ${REPO_FWD} home ${home.replace(/\\/g, "/")}`), md);
    assert.doesNotMatch(md, /\{\{ORCH_REPO\}\}|\{\{HOME\}\}/);
    assert.match(md, /managed by Frood \(/);

    // Hooks (.js) get the same treatment, and no managed header is added to them.
    const hook = path.join(freshHome(), "hook.js");
    fs.writeFileSync(hook, 'const REPO = "{{ORCH_REPO}}";\n');
    assert.equal(render(hook, "cc"), `const REPO = "${REPO_FWD}";\n`);

    assert.ok(MANAGED.includes(REPO_FWD) && !MANAGED.includes("{{ORCH_REPO}}"), MANAGED);
  } finally {
    if (prev === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = prev;
  }
});

test("install is idempotent and --check detects drift, missing and orphans", () => {
  const home = freshHome();
  const first = run(home);
  assert.equal(first.status, 0, first.stderr);
  assert.match(first.stdout, /create .*orchestrator\.md/);

  const cmd = path.join(home, ".claude", "commands", "frood-gauntlet.md");
  const ocCmd = path.join(home, ".config", "opencode", "commands", "frood-gauntlet.md");
  assert.ok(fs.existsSync(cmd) && fs.existsSync(ocCmd));
  assert.match(fs.readFileSync(cmd, "utf8"), /argument-hint/);
  assert.doesNotMatch(fs.readFileSync(ocCmd, "utf8"), /argument-hint|cc-only/);
  // OpenCode-only entries never land in Claude Code
  assert.ok(!fs.existsSync(path.join(home, ".claude", "commands", "frood-egm-review.md")));

  const second = run(home);
  assert.equal(second.status, 0);
  assert.match(second.stdout, /up to date/);

  assert.equal(run(home, "--check").status, 0);

  fs.appendFileSync(cmd, "\nhand edit\n");
  const drift = run(home, "--check");
  assert.equal(drift.status, 1);
  assert.match(drift.stdout, /DRIFT differs: .*gauntlet\.md/);

  fs.rmSync(ocCmd);
  assert.match(run(home, "--check").stdout, /DRIFT missing: .*gauntlet\.md/);

  // reinstall restores + backs up the hand-edited file
  assert.equal(run(home).status, 0);
  assert.equal(run(home, "--check").status, 0);
  const backups = path.join(home, ".config", "orchestrator", "backups");
  assert.ok(fs.readdirSync(backups).length >= 1, "a backup was written before overwriting");

  // orphan: a file recorded as installed but no longer in the manifest
  const statePath = path.join(home, ".config", "orchestrator", "installed.json");
  const state = JSON.parse(fs.readFileSync(statePath, "utf8"));
  const orphan = path.join(home, ".claude", "commands", "retired.md");
  fs.writeFileSync(orphan, "old");
  state.files.push(orphan);
  fs.writeFileSync(statePath, JSON.stringify(state));
  assert.match(run(home, "--check").stdout, /orphan.*retired\.md/);
  run(home);
  assert.ok(!fs.existsSync(orphan), "install removes orphans (after backup)");
});

// A rename in the manifest is an install-time event, not a drift to remember: the state file still names
// the old target, so install removes (and backs up) it, exactly as it does for any other orphan.
test("a renamed source removes the previously installed target (renamed command), backed up", () => {
  const home = freshHome();
  assert.equal(run(home).status, 0);

  const cmdDir = path.join(home, ".claude", "commands");
  const ocDir = path.join(home, ".config", "opencode", "commands");
  const statePath = path.join(home, ".config", "orchestrator", "installed.json");
  const state = JSON.parse(fs.readFileSync(statePath, "utf8"));

  // Put the home back into its pre-rename shape: the old names on disk and in installed.json,
  // the new ones absent — what an install from the parent commit left behind.
  const oldTargets = [
    path.join(cmdDir, "next.md"),
    path.join(ocDir, "next.md"),
    path.join(cmdDir, "orchestrator-learn.md"),
  ];
  const newTargets = [path.join(cmdDir, "frood-next.md"), path.join(ocDir, "frood-next.md")];
  state.files = state.files.filter((f) => !newTargets.includes(f));
  for (const t of oldTargets) {
    fs.writeFileSync(t, "old command\n");
    state.files.push(t);
  }
  for (const t of newTargets) fs.rmSync(t);
  fs.writeFileSync(statePath, JSON.stringify(state, null, 2));
  const drift = run(home, "--check");
  assert.equal(drift.status, 1, "a stale target is drift, not a silent survivor");
  assert.match(drift.stdout, /orphan.*next\.md/);
  assert.match(drift.stdout, /missing: .*frood-next\.md/);

  const reinstall = run(home);
  assert.equal(reinstall.status, 0, reinstall.stderr + reinstall.stdout);
  assert.match(reinstall.stdout, /remove orphan .*next\.md/);
  for (const t of oldTargets) assert.ok(!fs.existsSync(t), `${path.basename(t)} is gone after the rename`);
  assert.ok(fs.existsSync(path.join(cmdDir, "frood-next.md")), "the new name is installed for cc");
  assert.ok(fs.existsSync(path.join(ocDir, "frood-next.md")), "both harnesses follow the rename");
  assert.equal(run(home, "--check").status, 0, "the re-install is clean");

  // backed up first, like every other removal
  const backups = path.join(home, ".config", "orchestrator", "backups");
  const stamps = fs.readdirSync(backups);
  const backedUp = stamps.some((s) => fs.existsSync(path.join(backups, s, ".claude", "commands", "next.md")));
  assert.ok(backedUp, "the removed old command was backed up");
  // and the state file no longer names it, so a later install does not look for it again
  const after = JSON.parse(fs.readFileSync(statePath, "utf8"));
  assert.ok(!after.files.includes(path.join(cmdDir, "next.md")));
});

test("--dry-run writes nothing", () => {
  const home = freshHome();
  const r = run(home, "--dry-run");
  assert.equal(r.status, 0);
  assert.match(r.stdout, /would create/);
  assert.ok(!fs.existsSync(path.join(home, ".claude")));
});

test("never touches files it does not own", () => {
  const home = freshHome();
  const mine = path.join(home, ".claude", "commands", "personal.md");
  fs.mkdirSync(path.dirname(mine), { recursive: true });
  fs.writeFileSync(mine, "keep me");
  run(home);
  run(home);
  assert.equal(fs.readFileSync(mine, "utf8"), "keep me");
  assert.equal(run(home, "--check").status, 0);
});

test("lease commands render the right holder token per harness; frood-harness.md installs to OpenCode", () => {
  const home = freshHome();
  const r = run(home);
  assert.equal(r.status, 0, r.stderr + r.stdout);
  const ccDir = path.join(home, ".claude", "commands");
  const ocDir = path.join(home, ".config", "opencode", "commands");
  for (const f of ["frood-next.md", "frood-orchestrator.md", "frood-handback.md"]) {
    const cc = fs.readFileSync(path.join(ccDir, f), "utf8");
    const oc = fs.readFileSync(path.join(ocDir, f), "utf8");
    assert.match(cc, /--by cc\b/, `${f} cc has --by cc`);
    assert.doesNotMatch(cc, /--by oc\b/, `${f} cc has no --by oc`);
    assert.match(oc, /--by oc\b/, `${f} oc has --by oc`);
    assert.doesNotMatch(oc, /--by cc\b/, `${f} oc has no --by cc`);
  }
  const ocHarness = fs.readFileSync(path.join(ocDir, "frood-harness.md"), "utf8");
  assert.ok(ocHarness.includes(`${REPO_FWD}/hooks/cross-harness-statusline.js`), ocHarness);
  assert.doesNotMatch(ocHarness, /\.claude\/hooks|allowed-tools/);
  const ccHarness = fs.readFileSync(path.join(ccDir, "frood-harness.md"), "utf8");
  assert.match(ccHarness, /allowed-tools: Bash\(node:\*\)\n/);
  assert.match(ccHarness, /\.claude\/hooks\/cross-harness-statusline\.js" --text`\n/);
  assert.ok(!ccHarness.includes(`${REPO_FWD}/hooks/cross`), ccHarness);
});

// A mid-line `<!-- cc-only -->…<!-- /cc-only -->` is not understood by renderForHarness (whole-line blocks and
// end-of-line tags only), so both renders used to carry both harness texts plus the raw markers.
const HARNESS_MARKER = /<!--\s*\/?(cc|oc)-only/;
const CC_EXIT2 = "Fix the session id and retry once";
const OC_EXIT2 = "Retry the claim once without `--session`";

function checkNextExit2(text) {
  const cc = renderForHarness(text, "cc");
  const oc = renderForHarness(text, "oc");
  assert.doesNotMatch(cc, HARNESS_MARKER);
  assert.doesNotMatch(oc, HARNESS_MARKER);
  assert.ok(cc.includes(CC_EXIT2), "cc render lacks the cc Exit-2 text");
  assert.ok(!cc.includes(OC_EXIT2), "cc render carries the oc Exit-2 text");
  assert.ok(oc.includes(OC_EXIT2), "oc render lacks the oc Exit-2 text");
  assert.ok(!oc.includes(CC_EXIT2), "oc render carries the cc Exit-2 text");
}

test("frood-next Exit-2 bullet renders exactly one harness text per harness, no raw markers", () => {
  checkNextExit2(fs.readFileSync(path.join(REPO, "commands", "frood-next.md"), "utf8"));
});

test("no (cc|oc)-only marker survives either render of any command file", () => {
  const dir = path.join(REPO, "commands");
  const files = fs.readdirSync(dir).filter((f) => f.endsWith(".md"));
  assert.ok(files.length > 0);
  for (const f of files) {
    const text = fs.readFileSync(path.join(dir, f), "utf8");
    for (const h of ["cc", "oc"]) {
      const out = addManagedHeader(renderForHarness(text, h));
      const bad = out.split("\n").find((l) => HARNESS_MARKER.test(l));
      assert.equal(bad, undefined, `${f} (${h}) keeps a harness marker: ${bad}`);
    }
  }
});

// --------------------------------------------------------------- workstation install

// Fake systemctl: logs every argv line to sysdir/calls.log and prints `active` for is-active.
// `isActiveOutput` overrides what is-active prints (to exercise the inactive drift case).
function makeFakeSystemctl(sysdir, isActiveOutput = "active") {
  const fake = path.join(sysdir, "systemctl");
  fs.writeFileSync(
    fake,
    `#!/bin/sh\nprintf '%s\\n' "$*" >> "${sysdir}/calls.log"\ncase "$2" in is-active) echo "${isActiveOutput}";; esac\nexit 0\n`,
  );
  fs.chmodSync(fake, 0o755);
  return fake;
}

function runWs(home, systemctl, ...args) {
  return spawnSync(process.execPath, [INSTALL, ...args], {
    env: { ...process.env, ORCH_HOME: home, ORCH_SKIP_ROUTING: "1", ORCH_SYSTEMCTL: systemctl },
    encoding: "utf8",
  });
}

function wsLib(home) {
  return path.join(home, ".local", "lib", "frood-workstation");
}
function wsUnit(home) {
  return path.join(home, ".config", "systemd", "user");
}

test("workstation install copies libs + unit and enables via the fake systemctl", () => {
  const home = freshHome();
  const sysdir = tmp2();
  const fake = makeFakeSystemctl(sysdir);
  const r = runWs(home, fake);
  assert.equal(r.status, 0, r.stderr + r.stdout);
  assert.ok(fs.existsSync(path.join(wsLib(home), "agent-priority.mjs")), "guard installed");
  assert.ok(fs.existsSync(path.join(wsLib(home), "suite-lock.sh")), "lock installed");
  assert.ok(fs.existsSync(path.join(wsUnit(home), "frood-agent-priority.service")), "unit installed");
  const calls = fs.readFileSync(path.join(sysdir, "calls.log"), "utf8").trim().split("\n").filter(Boolean);
  assert.ok(calls.includes("--user daemon-reload"), "daemon-reload: " + JSON.stringify(calls));
  assert.ok(
    calls.includes("--user enable --now frood-agent-priority.service"),
    "enable --now: " + JSON.stringify(calls),
  );
  // --check is clean after install
  assert.equal(runWs(home, fake, "--check").status, 0, "--check after install: " + runWs(home, fake, "--check").stdout);
});

test("workstation --check detects drift and missing copies", () => {
  const home = freshHome();
  const sysdir = tmp2();
  const fake = makeFakeSystemctl(sysdir);
  assert.equal(runWs(home, fake).status, 0);
  assert.equal(runWs(home, fake, "--check").status, 0);

  const guard = path.join(wsLib(home), "agent-priority.mjs");
  fs.appendFileSync(guard, "\n// hand edit\n");
  const drifted = runWs(home, fake, "--check");
  assert.equal(drifted.status, 1, "modified copy is drift");
  assert.match(drifted.stdout, /DRIFT differs: .*agent-priority\.mjs/);

  fs.rmSync(path.join(wsLib(home), "suite-lock.sh"));
  const missing = runWs(home, fake, "--check");
  assert.equal(missing.status, 1, "missing copy is drift");
  assert.match(missing.stdout, /DRIFT missing: .*suite-lock\.sh/);

  // reinstall restores and --check is clean again
  assert.equal(runWs(home, fake).status, 0);
  assert.equal(runWs(home, fake, "--check").status, 0);
});

test("workstation --check reports inactive unit as drift", () => {
  const home = freshHome();
  const sysdir = tmp2();
  const fake = makeFakeSystemctl(sysdir, "inactive");
  assert.equal(runWs(home, fake).status, 0);
  const inactive = runWs(home, fake, "--check");
  assert.equal(inactive.status, 1, "inactive unit is drift");
  assert.match(inactive.stdout, /is not active/);
});

test("workstation --uninstall-workstation removes copies and unit, leaves state dir", () => {
  const home = freshHome();
  const sysdir = tmp2();
  const fake = makeFakeSystemctl(sysdir);
  const stateDir = path.join(home, ".local", "state", "frood-workstation");
  fs.mkdirSync(stateDir, { recursive: true });
  fs.writeFileSync(path.join(stateDir, "sentinel"), "keep me");

  assert.equal(runWs(home, fake).status, 0);
  assert.ok(fs.existsSync(path.join(wsLib(home), "agent-priority.mjs")));

  const u = runWs(home, fake, "--uninstall-workstation");
  assert.equal(u.status, 0, u.stderr + u.stdout);
  assert.ok(!fs.existsSync(path.join(wsUnit(home), "frood-agent-priority.service")), "unit removed");
  assert.ok(!fs.existsSync(path.join(wsLib(home), "agent-priority.mjs")), "guard removed");
  assert.ok(!fs.existsSync(path.join(wsLib(home), "suite-lock.sh")), "lock removed");
  assert.ok(fs.existsSync(path.join(stateDir, "sentinel")), "state dir left intact");
  const calls = fs.readFileSync(path.join(sysdir, "calls.log"), "utf8").trim().split("\n").filter(Boolean);
  assert.ok(calls.includes("--user disable --now frood-agent-priority.service"), "disable --now: " + JSON.stringify(calls));
  assert.ok(calls.includes("--user daemon-reload"), "daemon-reload after uninstall: " + JSON.stringify(calls));
});

test("workstation --uninstall-workstation with ORCH_SKIP_WORKSTATION=1 prints the skip line and touches nothing", () => {
  const home = freshHome();
  const sysdir = tmp2();
  const fake = makeFakeSystemctl(sysdir);
  // Pre-create the workstation files; the skip branch must leave them alone.
  fs.mkdirSync(path.join(wsLib(home)), { recursive: true });
  fs.mkdirSync(path.join(wsUnit(home)), { recursive: true });
  fs.writeFileSync(path.join(wsLib(home), "agent-priority.mjs"), "// guard\n");
  fs.writeFileSync(path.join(wsLib(home), "suite-lock.sh"), "# lock\n");
  fs.writeFileSync(path.join(wsUnit(home), "frood-agent-priority.service"), "[Unit]\n");
  const u = spawnSync(process.execPath, [INSTALL, "--uninstall-workstation"], {
    env: { ...process.env, ORCH_HOME: home, ORCH_SKIP_ROUTING: "1", ORCH_SKIP_WORKSTATION: "1", ORCH_SYSTEMCTL: fake },
    encoding: "utf8",
  });
  assert.equal(u.status, 0, u.stderr + u.stdout);
  assert.match(u.stdout, /workstation: skipped \(ORCH_SKIP_WORKSTATION=1\)/);
  assert.ok(fs.existsSync(path.join(wsLib(home), "agent-priority.mjs")), "guard untouched");
  assert.ok(fs.existsSync(path.join(wsLib(home), "suite-lock.sh")), "lock untouched");
  assert.ok(fs.existsSync(path.join(wsUnit(home), "frood-agent-priority.service")), "unit untouched");
  const callsLog = path.join(sysdir, "calls.log");
  assert.ok(!fs.existsSync(callsLog), "fake systemctl must never be called on the skip path");
});

test("workstation install in a sandbox home never calls systemctl", () => {
  const home = freshHome();
  function runSandbox(...args) {
    return spawnSync(process.execPath, [INSTALL, ...args], {
      env: { ...process.env, ORCH_HOME: home, ORCH_SKIP_ROUTING: "1" },
      encoding: "utf8",
    });
  }
  const r = runSandbox();
  assert.equal(r.status, 0, r.stderr + r.stdout);
  assert.ok(fs.existsSync(path.join(wsLib(home), "agent-priority.mjs")), "guard copied");
  assert.ok(fs.existsSync(path.join(wsLib(home), "suite-lock.sh")), "lock copied");
  assert.ok(fs.existsSync(path.join(wsUnit(home), "frood-agent-priority.service")), "unit copied");
  assert.match(r.stdout, /workstation: sandbox home, systemctl not called/);
  // --check is clean and does not probe the real unit state
  const c = runSandbox("--check");
  assert.equal(c.status, 0, c.stdout + c.stderr);
  assert.match(c.stdout, /check: OK/);
});

test("workstation uninstall in a sandbox home never calls systemctl", () => {
  const home = freshHome();
  const sysdir = tmp2();
  const fake = makeFakeSystemctl(sysdir);
  // Create the workstation files manually (do not use install, which would call systemctl)
  fs.mkdirSync(path.join(wsLib(home)), { recursive: true });
  fs.mkdirSync(path.join(wsUnit(home)), { recursive: true });
  fs.writeFileSync(path.join(wsLib(home), "agent-priority.mjs"), "// guard\n");
  fs.writeFileSync(path.join(wsLib(home), "suite-lock.sh"), "# lock\n");
  fs.writeFileSync(path.join(wsUnit(home), "frood-agent-priority.service"), "[Unit]\n");
  assert.ok(fs.existsSync(path.join(wsLib(home), "agent-priority.mjs")));
  // Run uninstall with ORCH_HOME set and no ORCH_SYSTEMCTL; fake systemctl on PATH
  const u = spawnSync(process.execPath, [INSTALL, "--uninstall-workstation"], {
    env: { ...process.env, ORCH_HOME: home, ORCH_SKIP_ROUTING: "1", PATH: `${sysdir}${path.delimiter}${process.env.PATH}` },
    encoding: "utf8",
  });
  assert.equal(u.status, 0, u.stderr + u.stdout);
  assert.ok(!fs.existsSync(path.join(wsLib(home), "agent-priority.mjs")), "guard removed from sandbox");
  assert.ok(!fs.existsSync(path.join(wsLib(home), "suite-lock.sh")), "lock removed from sandbox");
  assert.ok(!fs.existsSync(path.join(wsUnit(home), "frood-agent-priority.service")), "unit removed from sandbox");
  // The fake systemctl must never have been called
  const callsLog = path.join(sysdir, "calls.log");
  assert.ok(!fs.existsSync(callsLog) || fs.readFileSync(callsLog, "utf8").trim() === "", "fake systemctl must never be called in sandbox uninstall");
});

test("workstation --dry-run never writes files or calls systemctl", () => {
  const home = freshHome();
  const sysdir = tmp2();
  const fake = makeFakeSystemctl(sysdir);
  const r = spawnSync(process.execPath, [INSTALL, "--dry-run"], {
    env: { ...process.env, ORCH_HOME: home, ORCH_SKIP_ROUTING: "1", ORCH_SYSTEMCTL: fake },
    encoding: "utf8",
  });
  assert.equal(r.status, 0, r.stderr + r.stdout);
  assert.match(r.stdout, /workstation: would copy/, "should print would-copy lines");
  assert.match(r.stdout, /workstation: dry run — no files written/, "should print dry run notice");
  // No files written
  assert.ok(!fs.existsSync(path.join(wsLib(home), "agent-priority.mjs")), "guard not written in dry run");
  assert.ok(!fs.existsSync(path.join(wsLib(home), "suite-lock.sh")), "lock not written in dry run");
  assert.ok(!fs.existsSync(path.join(wsUnit(home), "frood-agent-priority.service")), "unit not written in dry run");
  // Fake systemctl never called
  const callsLog = path.join(sysdir, "calls.log");
  assert.ok(!fs.existsSync(callsLog) || fs.readFileSync(callsLog, "utf8").trim() === "", "fake systemctl must never be called in dry run");
});

// tmp2 is a separate temp allocator so workstation tests don't collide with freshHome users.
function tmp2() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "ws-install-"));
}
