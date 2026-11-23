// The unread badge counts only mail somebody can still read (m6a T5).
//
// Nobody but the recipient may read or ack mail, so mail addressed to a session that ended is
// unread forever and used to inflate the statusline/extension badge (owner saw ✉13 for 13 such
// messages). These tests drive the exported helpers against fixture databases in a temp dir and
// spawn the hook with --json / --text against a throwaway HOME - never the real mailbox.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { render } from "../bin/install.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HOOK = path.join(HERE, "..", "hooks", "cross-harness-statusline.js");
const require = createRequire(import.meta.url);

// Loading the module must not print, spawn or read stdin - if it did, the whole suite would hang.
const hook = require(HOOK);
const { recipientActivity, unreadTotal, recentUnread, mailLiveHours, renderText, renderHtml, loadConfig, ORCH_REPO_DIR, resolveFocus, mailThreads, readStreams, relatedSessions } = hook.__test;

const HOUR = 3600_000;
const DAY = 24 * HOUR;
const NOW = 1_780_000_000_000; // fixed clock for the in-process helpers

const SES_LIVE = "ses_live0000000000000000000";
const SES_IDLE = "ses_idle0000000000000000000";
const CC_LIVE = "aaaaaaaa-0000-4000-8000-000000000001";
const CC_STALE = "bbbbbbbb-0000-4000-8000-000000000002";
const UNKNOWN_SES = "ses_gone0000000000000000000";

function tmpDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

/** Mailbox fixture. `withExpiry: false` models an older mailbox (no expires_at column). */
function makeMailbox(file, rows, { withExpiry = true, peers = [] } = {}) {
  const { DatabaseSync } = require("node:sqlite");
  const db = new DatabaseSync(file);
  try {
    db.exec(
      `CREATE TABLE messages (
         id TEXT PRIMARY KEY, ts INTEGER, from_session TEXT, from_title TEXT, from_branch TEXT,
         to_session TEXT, subject TEXT, status TEXT${withExpiry ? ", expires_at INTEGER" : ""});`,
    );
    const sql = withExpiry
      ? "INSERT INTO messages (id, ts, from_session, from_title, from_branch, to_session, subject, status, expires_at) VALUES (?,?,?,?,?,?,?,?,?)"
      : "INSERT INTO messages (id, ts, from_session, from_title, from_branch, to_session, subject, status) VALUES (?,?,?,?,?,?,?,?)";
    const ins = db.prepare(sql);
    for (const r of rows) {
      const base = [r.id, r.ts, r.from ?? "ses_sender", "orch", "main", r.to, r.subject ?? `subj ${r.id}`, r.status ?? "unread"];
      if (withExpiry) ins.run(...base, r.expires ?? NOW + 7 * DAY);
      else ins.run(...base);
    }
    db.exec(
      `CREATE TABLE peers (
         session_id TEXT PRIMARY KEY, harness TEXT, title TEXT, directory TEXT, branch TEXT,
         first_seen INTEGER, last_seen INTEGER);`,
    );
    const pins = db.prepare("INSERT INTO peers (session_id, harness, title, directory, branch, first_seen, last_seen) VALUES (?,?,?,?,?,?,?)");
    for (const p of peers) pins.run(p.id, p.harness ?? "claude", p.title ?? "", p.directory ?? "", p.branch ?? "", NOW - 1 * HOUR, NOW - 1 * HOUR);
  } finally { db.close(); }
}

/** OpenCode fixture db with the columns the hook's session queries touch. */
function makeOcDb(file, sessions) {
  const { DatabaseSync } = require("node:sqlite");
  const db = new DatabaseSync(file);
  try {
    db.exec(
      `CREATE TABLE session_v2 (
         id TEXT PRIMARY KEY, title TEXT, agent TEXT, model TEXT, cost REAL,
         time_created INTEGER, time_updated INTEGER, parent_id TEXT,
         time_busy INTEGER, time_idle INTEGER, directory TEXT);`,
    );
    const ins = db.prepare(
      "INSERT INTO session_v2 (id, title, agent, model, cost, time_created, time_updated, parent_id, time_busy, time_idle, directory) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
    );
    for (const s of sessions) {
      ins.run(s.id, s.title ?? s.id, "worker", '{"providerID":"opencode","id":"mimo-v2.6-flash"}',
        0, s.updated, s.updated, null, s.updated, null, "/tmp/x");
    }
  } finally { db.close(); }
}

/** One transcript file per Claude Code session id, mtime = last activity. */
function makeTranscript(projectsDir, id, activityMs) {
  const dir = path.join(projectsDir, "-tmp-project");
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${id}.jsonl`);
  fs.writeFileSync(file, '{"type":"summary"}\n');
  fs.utimesSync(file, new Date(activityMs), new Date(activityMs));
}

/** The whole fixture world for the in-process helpers. */
function fixture(now = NOW) {
  const root = tmpDir("orch-mail-");
  const mailboxDb = path.join(root, "mailbox.db");
  const ocDb = path.join(root, "opencode.db");
  const projectsDir = path.join(root, "projects");
  makeOcDb(ocDb, [
    { id: SES_LIVE, updated: now - 1 * HOUR },
    { id: SES_IDLE, updated: now - 3 * DAY },
  ]);
  makeTranscript(projectsDir, CC_LIVE, now - 2 * HOUR);
  makeTranscript(projectsDir, CC_STALE, now - 5 * DAY);
  makeMailbox(mailboxDb, [
    { id: "m1", ts: now - 10 * 60_000, to: SES_LIVE },
    { id: "m2", ts: now - 20 * 60_000, to: SES_IDLE },
    { id: "m3", ts: now - 30 * 60_000, to: CC_LIVE },
    { id: "m4", ts: now - 40 * 60_000, to: CC_STALE },
    { id: "m5", ts: now - 50 * 60_000, to: UNKNOWN_SES },
    { id: "m6", ts: now - 60 * 60_000, to: SES_LIVE, expires: now - 1000 }, // already expired
  ]);
  return { root, mailboxDb, ocDb, projectsDir, now };
}

const optsOf = (f) => ({ mailboxDb: f.mailboxDb, ocDb: f.ocDb, projectsDir: f.projectsDir, now: f.now });

function withLiveHours(value, fn) {
  const before = process.env.ORCH_MAIL_LIVE_H;
  if (value === undefined) delete process.env.ORCH_MAIL_LIVE_H;
  else process.env.ORCH_MAIL_LIVE_H = String(value);
  try { return fn(); } finally {
    if (before === undefined) delete process.env.ORCH_MAIL_LIVE_H;
    else process.env.ORCH_MAIL_LIVE_H = before;
  }
}

test("requiring the hook starts nothing and prints nothing", () => {
  assert.equal(typeof hook.__test, "object");
  const r = spawnSync(process.execPath, ["-e", `require(${JSON.stringify(HOOK)})`], {
    encoding: "utf8", timeout: 30_000, windowsHide: true,
  });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stdout, "");
});

test("recipientActivity: opencode sessions and Claude Code transcripts, null when unknown", () => {
  const f = fixture();
  assert.equal(recipientActivity(SES_LIVE, optsOf(f)), f.now - 1 * HOUR);
  assert.equal(recipientActivity(SES_IDLE, optsOf(f)), f.now - 3 * DAY);
  assert.equal(recipientActivity(CC_LIVE, optsOf(f)), f.now - 2 * HOUR);
  assert.equal(recipientActivity(CC_STALE, optsOf(f)), f.now - 5 * DAY);
  assert.equal(recipientActivity(UNKNOWN_SES, optsOf(f)), null);
  assert.equal(recipientActivity("cccccccc-0000-4000-8000-000000000003", optsOf(f)), null);
  assert.equal(recipientActivity("", optsOf(f)), null);
});

test("recipientActivity falls back to the legacy `session` table", () => {
  const root = tmpDir("orch-mail-legacy-");
  const ocDb = path.join(root, "opencode.db");
  const { DatabaseSync } = require("node:sqlite");
  const db = new DatabaseSync(ocDb);
  try {
    db.exec("CREATE TABLE session (id TEXT PRIMARY KEY, time_updated INTEGER);");
    db.prepare("INSERT INTO session (id, time_updated) VALUES (?,?)").run(SES_LIVE, NOW - 2 * HOUR);
  } finally { db.close(); }
  assert.equal(recipientActivity(SES_LIVE, { ocDb, projectsDir: root }), NOW - 2 * HOUR);
});

test("unreadTotal: live vs idle, expired rows ignored", () => {
  const f = fixture();
  assert.deepEqual(unreadTotal(optsOf(f)), { live: 2, idle: 3 });
});

test("unreadTotal: ORCH_MAIL_LIVE_H widens the live window; bad values mean 24h", () => {
  const f = fixture();
  assert.deepEqual(withLiveHours(100, () => unreadTotal(optsOf(f))), { live: 3, idle: 2 });
  assert.deepEqual(unreadTotal(optsOf(f)), { live: 2, idle: 3 }); // restored
  assert.equal(withLiveHours(undefined, () => mailLiveHours()), 24);
  for (const bad of ["", "abc", "0", "-5"]) {
    assert.equal(withLiveHours(bad, () => mailLiveHours()), 24, `ORCH_MAIL_LIVE_H=${bad}`);
  }
  assert.equal(withLiveHours(72, () => mailLiveHours()), 72);
});

test("recentUnread: rows carry idle/active, newest first, liveOnly keeps live rows only", () => {
  const f = fixture();
  const all = recentUnread(20, optsOf(f));
  assert.deepEqual(all.map((r) => r.subject), ["subj m1", "subj m2", "subj m3", "subj m4", "subj m5"]);
  assert.deepEqual(all.map((r) => r.idle), [false, true, false, true, true]);
  assert.equal(all[0].active, f.now - 1 * HOUR);
  assert.equal(all[1].active, f.now - 3 * DAY);
  assert.equal(all[4].active, null);

  const live = recentUnread(20, { ...optsOf(f), liveOnly: true });
  assert.deepEqual(live.map((r) => r.subject), ["subj m1", "subj m3"]);
  assert.ok(live.every((r) => r.idle === false));
  assert.equal(recentUnread(1, { ...optsOf(f), liveOnly: true }).length, 1);
  assert.equal(recentUnread(2, optsOf(f)).length, 2);
});

test("an older mailbox without expires_at still counts unread mail", () => {
  const root = tmpDir("orch-mail-old-");
  const mailboxDb = path.join(root, "mailbox.db");
  const ocDb = path.join(root, "opencode.db");
  const projectsDir = path.join(root, "projects");
  makeOcDb(ocDb, [{ id: SES_LIVE, updated: NOW - 1 * HOUR }]);
  makeMailbox(mailboxDb, [{ id: "old1", ts: NOW - 60_000, to: SES_LIVE }], { withExpiry: false });
  const opts = { mailboxDb, ocDb, projectsDir, now: NOW };
  assert.deepEqual(unreadTotal(opts), { live: 1, idle: 0 });
  assert.equal(recentUnread(20, opts).length, 1);
});

// ── renderers: one spawn of --text / --json against a throwaway HOME ────────
// The renderers read the harness config (~/.claude/harness-config.json) to decide whether the
// peer-mail section is configured, so the rows only print when peerMailDist resolves. A temp
// HOME with a stub dist module makes that deterministic - and keeps the real mailbox out of it.
function spawnHome(now) {
  const home = tmpDir("orch-mail-home-");
  const p = (...s) => path.join(home, ...s);
  fs.mkdirSync(path.dirname(p(".local", "share", "opencode-peer-mail", "mailbox.db")), { recursive: true });
  fs.mkdirSync(path.dirname(p(".local", "share", "opencode", "opencode.db")), { recursive: true });
  fs.writeFileSync(p("peer-dist.mjs"), "export function listPeerSessions() { return []; }\n");
  fs.mkdirSync(p(".claude"), { recursive: true });
  fs.writeFileSync(p(".claude", "harness-config.json"), JSON.stringify({ peerMailDist: p("peer-dist.mjs") }));
  makeMailbox(p(".local", "share", "opencode-peer-mail", "mailbox.db"), [
    { id: "m1", ts: now - 5 * 60_000, to: SES_LIVE, expires: now + 7 * DAY },
    { id: "m2", ts: now - 15 * 60_000, to: SES_IDLE, expires: now + 7 * DAY },
    { id: "m3", ts: now - 25 * 60_000, to: CC_LIVE, expires: now + 7 * DAY },
    { id: "m4", ts: now - 35 * 60_000, to: CC_STALE, expires: now + 7 * DAY },
    { id: "m5", ts: now - 45 * 60_000, to: UNKNOWN_SES, expires: now + 7 * DAY },
    { id: "m6", ts: now - 55 * 60_000, to: SES_LIVE, expires: now - 1000 },
  ]);
  makeOcDb(p(".local", "share", "opencode", "opencode.db"), [
    { id: SES_LIVE, updated: now - 1 * HOUR },
    { id: SES_IDLE, updated: now - 3 * DAY },
  ]);
  makeTranscript(p(".claude", "projects"), CC_LIVE, now - 2 * HOUR);
  makeTranscript(p(".claude", "projects"), CC_STALE, now - 5 * DAY);
  // Background dashboard rebuilds spawn a detached process: keep them off in the fixture.
  fs.mkdirSync(p(".config", "orchestrator"), { recursive: true });
  fs.writeFileSync(p(".config", "orchestrator", "dashboard.off"), "");
  const env = { ...process.env, HOME: home, USERPROFILE: home };
  delete env.ORCH_MAIL_LIVE_H;
  return { home, env };
}

function runHook(args, env) {
  const r = spawnSync(process.execPath, [HOOK, ...args], { env, encoding: "utf8", timeout: 60_000, windowsHide: true });
  assert.equal(r.status, 0, r.stderr);
  return r.stdout;
}

test("--json keeps the extension contract: live count + live rows only", () => {
  const now = Date.now();
  const { env } = spawnHome(now);
  const lines = runHook(["--json"], env).split(/\r?\n/).filter(Boolean);
  const d = JSON.parse(lines[0]);
  assert.equal(typeof d.unread, "number");
  assert.equal(d.unread, 2);
  assert.equal(d.unreadIdle, 3);
  assert.ok(Array.isArray(d.unreadRows));
  assert.equal(d.unreadRows.length, 2);
  for (const row of d.unreadRows) {
    assert.equal(typeof row.subject, "string");
    assert.ok(Number.isFinite(row.ts));
    assert.equal(row.idle, false); // liveOnly: the extension's subject line is live mail
  }
});

test("--kick still runs as a script (oc-worker spawns it) and prints nothing", () => {
  // bin/oc-worker.mjs:754 spawns this file with --kick: guarding main() behind require.main
  // must not change that path. dashboard.off in the fixture keeps it from spawning a rebuild.
  const { env } = spawnHome(Date.now());
  assert.equal(runHook(["--kick"], env), "");
});

test("--text header counts live vs idle and marks idle rows", () => {
  const now = Date.now();
  const { env } = spawnHome(now);
  const out = runHook(["--text"], env);
  assert.match(out, /peer-mail: 2 unread \(3 to idle sessions\)/);
  assert.match(out, /\(idle 3d ago\)/); // SES_IDLE, 3 days without activity
  assert.match(out, /\(idle 5d ago\)/); // CC_STALE transcript
  assert.match(out, /\(idle \?\)/); // unknown recipient: activity unknowable
  // a live row carries no idle marker
  assert.doesNotMatch(out, /subj m1[^\n]*\(idle/);
});

test("--html marks idle rows dim and heads the table with the counts", () => {
  const now = Date.now();
  const { home, env } = spawnHome(now);
  runHook(["--html"], env);
  const html = fs.readFileSync(path.join(home, ".claude", "harness-dashboard.html"), "utf8");
  assert.match(html, /peer-mail: 2 unread \(3 to idle sessions\)/);
  // The fixture's peer-mail table is the only one whose rows carry a class: three idle rows.
  assert.equal((html.match(/<tr class="dim">/g) || []).length, 3);
  assert.match(html, /\(idle 3d ago\)/);
  assert.match(html, /\(idle 5d ago\)/);
  assert.match(html, /\(idle \?\)/);
});

test("renderText prints the counts header for a given full", () => {
  // Row marks are asserted through the --text spawn above; here the exported renderer gets a
  // fixture full, so the header line is checked without reading the real harness config.
  const f = fixture();
  const text = renderText({}, {
    unreadRows: recentUnread(20, optsOf(f)),
    unreadTotals: unreadTotal(optsOf(f)),
    remotes: [],
    trains: [],
    sessions: [],
    oc: null,
    orch: null,
    active: null,
  });
  assert.match(text, /peer-mail: 2 unread \(3 to idle sessions\)/);
});

// ── T8-minors: the router-health hint and the config cache ────────────────────

/** A `full` with no data, enough for renderHtml to reach the router-health hint row. */
const EMPTY_FULL = () => ({
  unreadRows: [],
  unreadTotals: { live: 0, idle: 0 },
  remotes: [],
  trains: [],
  sessions: [],
  oc: null,
  orch: { health: null, down: [], runs: [] },
  active: null,
});

test("the router-health hint names a real repo path, never the un-rendered {{ORCH_REPO}} token", () => {
  const repo = path.resolve(HERE, "..").replace(/\\/g, "/");
  // Run from the checkout: the source still carries the installer's token, so the module falls back to its own repo.
  const html = renderHtml({}, EMPTY_FULL());
  assert.doesNotMatch(html, /\{\{/, "no token reaches the dashboard");
  assert.ok(html.includes(`node ${repo}/bin/router-health.mjs --probe`), html.split("\n").find((l) => l.includes("router-health has not run")));
  assert.ok(!html.includes("\\"), "the hint path is forward-slashed");
  assert.equal(ORCH_REPO_DIR, repo);

  // The installer replaces every {{ORCH_REPO}} occurrence, so the installed hook resolves the same real path.
  const rendered = render(HOOK, "cc");
  assert.doesNotMatch(rendered, /\{\{ORCH_REPO\}\}/);
  assert.ok(rendered.includes(`const rendered = "${repo}";`), "the token in the constant is what the installer renders");
});

test("loadConfig re-reads an edited config: an edit, a removal and a file that appears", () => {
  const file = path.join(tmpDir("orch-cfg-"), "harness-config.json");
  assert.deepEqual(loadConfig(file), {}, "a missing file is an empty config");
  fs.writeFileSync(file, JSON.stringify({ repos: [{ label: "a", dir: "~/x" }] }));
  assert.equal(loadConfig(file).repos[0].label, "a");
  fs.writeFileSync(file, JSON.stringify({ repos: [{ label: "bb", dir: "~/x" }, { label: "c", dir: "~/y" }] }));
  assert.deepEqual(loadConfig(file).repos.map((r) => r.label), ["bb", "c"], "an edited config lands without a restart");
  fs.rmSync(file);
  assert.deepEqual(loadConfig(file), {}, "a removed config reads as no config");
  fs.writeFileSync(file, JSON.stringify({ peerMailDist: "~/dist/sessions.js" }));
  assert.equal(loadConfig(file).peerMailDist, "~/dist/sessions.js", "a config that appears is read");
});

// ── --json --for: related other-harness sessions ─────────────────────────────

const CC_PEER = "cccccccc-0000-4000-8000-000000000003";
const SES_OTHER = "ses_other00000000000000000";

function focusFixture() {
  const root = tmpDir("orch-focus-");
  const mailboxDb = path.join(root, "mailbox.db");
  const ocDb = path.join(root, "opencode.db");
  const projectsDir = path.join(root, "projects");
  makeOcDb(ocDb, [
    { id: SES_LIVE, updated: NOW - 1 * HOUR },
    { id: SES_OTHER, updated: NOW - 30 * 60_000 },
  ]);
  makeTranscript(projectsDir, CC_LIVE, NOW - 2 * HOUR);
  makeMailbox(mailboxDb, [
    { id: "f1", ts: NOW - 10 * 60_000, from: CC_PEER, to: SES_LIVE, subject: "blocked?", status: "unread" },
    { id: "f2", ts: NOW - 20 * 60_000, from: SES_LIVE, to: CC_PEER, subject: "re: blocked?", status: "read" },
    { id: "f3", ts: NOW - 5 * 60_000, from: SES_OTHER, to: SES_LIVE, subject: "same-harness noise", status: "unread" },
  ], {
    peers: [{ id: CC_PEER, harness: "claude", title: "CC One", directory: "/tmp/cc" }],
  });
  return { root, mailboxDb, ocDb, projectsDir };
}

function streamsFixture() {
  const dir = tmpDir("orch-streams-");
  const w = (name, s) => fs.writeFileSync(path.join(dir, `${name}.json`), JSON.stringify(s));
  w("video-studio", { status: "active", held_session: SES_LIVE, claim: { session: CC_PEER }, repo: "video-studio" });
  w("parked", { status: "parked", held_session: SES_LIVE, claim: { session: CC_PEER } });
  w("done", { status: "done", held_session: SES_LIVE });
  w("unrelated", { status: "active", held_session: SES_OTHER, claim: { session: CC_STALE } });
  fs.writeFileSync(path.join(dir, "nope.txt"), "not a stream");
  fs.writeFileSync(path.join(dir, "bad.json"), "{nope");
  return dir;
}

const SESSIONS = () => ([
  { session_id: CC_PEER, harness: "claude", title: "CC One", directory: "/tmp/cc", branch: "main", last_active: NOW - 1 * HOUR },
  { session_id: SES_OTHER, harness: "opencode", title: "other oc", directory: "/tmp/x", branch: null, last_active: NOW - 30 * 60_000 },
  { session_id: CC_STALE, harness: "claude", title: "CC stale", directory: "/tmp/old", branch: null, last_active: NOW - 5 * DAY },
]);

test("resolveFocus: OC db, peers registry, CC transcript, unknown", () => {
  const f = focusFixture();
  const o = { ocDb: f.ocDb, mailboxDb: f.mailboxDb, projectsDir: f.projectsDir };
  assert.deepEqual(resolveFocus(SES_LIVE, o), { id: SES_LIVE, harness: "opencode", title: SES_LIVE, directory: "/tmp/x" });
  assert.deepEqual(resolveFocus(CC_PEER, o), { id: CC_PEER, harness: "claude", title: "CC One", directory: "/tmp/cc" });
  assert.deepEqual(resolveFocus(CC_LIVE, o), { id: CC_LIVE, harness: "claude", title: "", directory: "" });
  assert.equal(resolveFocus(UNKNOWN_SES, o), null);
  assert.equal(resolveFocus("", o), null);
});

test("mailThreads: one row per counterpart, unread counts incoming only", () => {
  const f = focusFixture();
  const o = { mailboxDb: f.mailboxDb, now: NOW };
  const th = mailThreads(SES_LIVE, 8, o);
  assert.deepEqual(th.map((t) => t.peer_id), [SES_OTHER, CC_PEER]);
  const cc = th.find((t) => t.peer_id === CC_PEER);
  assert.equal(cc.incoming, true); // newest message in the thread is incoming
  assert.equal(cc.unread, 1, "the older incoming unread still counts");
  assert.equal(cc.last_subject, "blocked?");
  const other = th.find((t) => t.peer_id === SES_OTHER);
  assert.equal(other.incoming, true);
  assert.equal(other.unread, 1);
  assert.deepEqual(mailThreads("ses_nobody000000000000000", 8, o), []);
});

test("readStreams: held + claim sessions, skips parked/done/corrupt/junk", () => {
  const dir = streamsFixture();
  assert.deepEqual(readStreams(dir), [
    { name: "unrelated", repo: "", sessions: [SES_OTHER, CC_STALE] },
    { name: "video-studio", repo: "video-studio", sessions: [SES_LIVE, CC_PEER] },
  ]);
  assert.deepEqual(readStreams(path.join(dir, "missing")), []);
});

test("relatedSessions: other harnesses only, stream beats unread beats recency", () => {
  const focus = { id: SES_LIVE, harness: "opencode", title: "t", directory: "/tmp/x" };
  const streams = readStreams(streamsFixture());
  const threads = [
    { peer_id: CC_PEER, last_subject: "blocked?", incoming: true, unread: 0, ts: NOW - 10 * 60_000 },
    { peer_id: CC_STALE, last_subject: "old thread", incoming: true, unread: 1, ts: NOW - 4 * DAY },
  ];
  // SES_OTHER is same-harness (and newest): excluded even though it shares the directory.
  const rel = relatedSessions(focus, SESSIONS(), streams, threads);
  assert.deepEqual(rel.map((r) => r.session_id), [CC_PEER, CC_STALE]);
  assert.match(rel[0].via.join(" + "), /stream video-studio/);
  assert.match(rel[0].via.join(" + "), /mail: blocked\?/);
  assert.match(rel[1].via.join(" + "), /mail: old thread \(1 unread\)/);
  assert.equal(rel[1].unread, 1);
  assert.ok(rel.every((r) => r.harness !== "opencode"), "same-harness sessions are tabs already");
});

test("relatedSessions: same-dir and unknown ids stay out without a reason", () => {
  const focus = { id: SES_LIVE, harness: "opencode", title: "t", directory: "/tmp/x" };
  const rel = relatedSessions(focus, SESSIONS(), [], []);
  assert.deepEqual(rel, [], "no stream, no thread, and same-harness dir-mates excluded");
  const focCc = { id: CC_PEER, harness: "claude", title: "t", directory: "/tmp/cc" };
  const rel2 = relatedSessions(focCc, SESSIONS(), [], [{ peer_id: SES_LIVE, last_subject: "hi", incoming: true, unread: 1, ts: NOW }]);
  assert.equal(rel2.length, 1);
  assert.equal(rel2[0].session_id, SES_LIVE, "viewing from Claude: the related OC session shows");
});

test("--json --for: focus, myUnread, threads and a related CC row end to end", () => {
  const now = Date.now();
  const { home, env } = spawnHome(now);
  // A live OC session with a thread to CC_LIVE, and a stub peer row naming it.
  const { DatabaseSync } = require("node:sqlite");
  const mdb = new DatabaseSync(path.join(home, ".local", "share", "opencode-peer-mail", "mailbox.db"));
  try {
    mdb.prepare("INSERT INTO messages (id, ts, from_session, from_title, from_branch, to_session, subject, status, expires_at) VALUES (?,?,?,?,?,?,?,?,?)")
      .run("mx", now - 60_000, SES_LIVE, "OC One", "main", CC_LIVE, "need a reviewer", "unread", now + 7 * 24 * 3600_000);
  } finally { mdb.close(); }
  fs.writeFileSync(path.join(home, "peer-dist.mjs"),
    `export function listPeerSessions() { return [{ session_id: "${CC_LIVE}", harness: "claude", title: "CC One", directory: "/tmp/w", branch: "main", last_active: ${now - 120_000} }]; }\n`);
  fs.mkdirSync(path.join(home, ".config", "orchestrator", "streams"), { recursive: true });
  fs.writeFileSync(path.join(home, ".config", "orchestrator", "streams", "m6a.json"), JSON.stringify({
    status: "active", repo: "", held_session: SES_LIVE, claim: { session: CC_LIVE },
  }));
  const d = JSON.parse(runHook(["--json", "--for", SES_LIVE], env).split(/\r?\n/).filter(Boolean)[0]);
  assert.deepEqual(d.focus, { id: SES_LIVE, harness: "opencode", title: SES_LIVE, directory: "/tmp/x" });
  assert.equal(d.myUnread, 2, "spawnHome m1 plus the new thread message");
  assert.ok(d.threads.some((t) => t.peer_id === CC_LIVE && t.unread === 0 && t.incoming === false));
  assert.equal(d.related.length, 1);
  assert.equal(d.related[0].session_id, CC_LIVE);
  assert.match(d.related[0].via.join(" + "), /stream m6a/);
  assert.match(d.related[0].via.join(" + "), /mail: need a reviewer$/);
  // No --for: the contract is unchanged (no focus keys at all).
  const plain = JSON.parse(runHook(["--json"], env).split(/\r?\n/).filter(Boolean)[0]);
  assert.ok(!("focus" in plain) && !("related" in plain));
});
