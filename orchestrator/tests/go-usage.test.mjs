// go-usage: key reader, G0 shape parser, snapshot fetch, jsonl store and CLI. Hermetic: temp
// sqlite dbs with a fake key, 127.0.0.1 servers closed in after(), CLI spawned with timeouts.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import {
  GO_USAGE_URL_DEFAULT,
  readGoKey,
  parseUsage,
  snapshot,
  appendSnapshot,
  readLatest,
  readHistory,
} from "../bin/go-usage.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "go-usage.mjs");
const FAKE_KEY = "fake-go-key-for-tests";
const OTHER_KEY = "other-fake-go-key-for-tests";

const iso = (t) => new Date(t).toISOString();
const NOW = Date.parse("2026-12-03T00:00:00.000Z");

function g0Body({ rolling = 1, weekly = 2, monthly = 1 } = {}) {
  return {
    usage: {
      rolling: { status: "ok", percent: rolling, resetsAt: iso(NOW + 2 * 3600 * 1000) },
      weekly: { status: "ok", percent: weekly, resetsAt: "2026-12-07T00:00:00.000Z" },
      monthly: { status: "ok", percent: monthly, resetsAt: "2026-12-26T21:24:37.000Z" },
    },
  };
}

function tempDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "gou-"));
}

/** Temp sqlite with a credential table; rows: [{key, active}]. Returns db path. */
function tempDb(rows = []) {
  const dir = tempDir();
  const dbPath = path.join(dir, "opencode.db");
  const db = new DatabaseSync(dbPath);
  db.exec("CREATE TABLE credential (integration_id TEXT, active INTEGER, value TEXT)");
  const ins = db.prepare("INSERT INTO credential (integration_id, active, value) VALUES ('opencode-go', ?, ?)");
  for (const r of rows) ins.run(r.active ? 1 : 0, JSON.stringify({ type: "api", key: r.key }));
  db.close();
  return dbPath;
}

/** 127.0.0.1 server; handler(req, body) -> [status, payload]. Tracks auth header and request count. */
async function localServer(t, handler) {
  const seen = { count: 0, auth: null, url: null };
  const server = http.createServer((req, res) => {
    let body = "";
    req.on("data", (c) => {
      body += c;
    });
    req.on("end", () => {
      seen.count++;
      seen.auth = req.headers.authorization || null;
      seen.url = req.url || "";
      const [status, payload, raw, contentType] = handler(req, body, seen);
      const text = raw != null ? raw : JSON.stringify(payload);
      res.writeHead(status, { "content-type": contentType || "application/json" });
      res.end(text);
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());
  const port = server.address().port;
  return { server, seen, url: `http://127.0.0.1:${port}/usage` };
}

test("200 with the G0 shape: ok, exact keys, Bearer header, URL carries no key", async (t) => {
  const { seen, url } = await localServer(t, () => [200, g0Body()]);
  const r = await snapshot({ url, now: NOW, key: FAKE_KEY });
  assert.equal(r.ok, true);
  assert.deepEqual(Object.keys(r.snap).sort(), ["at", "monthly", "rolling", "weekly"]);
  for (const w of ["rolling", "weekly", "monthly"]) {
    assert.deepEqual(Object.keys(r.snap[w]).sort(), ["pct", "resets_at", "status"]);
  }
  assert.equal(r.snap.rolling.pct, 1);
  assert.equal(r.snap.at, iso(NOW));
  assert.equal(seen.count, 1);
  assert.equal(seen.auth, `Bearer ${FAKE_KEY}`);
  assert.ok(!seen.url.includes(FAKE_KEY), seen.url);
  const flat = JSON.stringify(r);
  assert.ok(!flat.includes(FAKE_KEY), "returned object leaks the key");
});

test("401, 500, bad JSON and bad shape give stated reasons and no append", async (t) => {
  const { url } = await localServer(t, (req, _body, seen) => {
    if (seen.count === 1) return [401, { error: "x" }];
    if (seen.count === 2) return [500, { error: "x" }];
    if (seen.count === 3) return [200, null, "not json{"];
    return [200, { usage: 5 }];
  });
  assert.deepEqual(await snapshot({ url, now: NOW, key: FAKE_KEY }), { ok: false, reason: "http 401" });
  assert.deepEqual(await snapshot({ url, now: NOW, key: FAKE_KEY }), { ok: false, reason: "http 500" });
  assert.deepEqual(await snapshot({ url, now: NOW, key: FAKE_KEY }), { ok: false, reason: "bad json" });
  assert.deepEqual(await snapshot({ url, now: NOW, key: FAKE_KEY }), { ok: false, reason: "bad shape" });
});

test("hung server: a hanging 127.0.0.1 server plus a short-timeout fetchImpl gives timeout", async (t) => {
  const hanging = http.createServer(() => {
    /* never responds */
  });
  await new Promise((resolve) => hanging.listen(0, "127.0.0.1", resolve));
  t.after(() => hanging.close());
  const url = `http://127.0.0.1:${hanging.address().port}/usage`;
  const short = (u, init) => fetch(u, { headers: init && init.headers, signal: AbortSignal.timeout(50) });
  const r = await snapshot({ url, now: NOW, key: FAKE_KEY, fetchImpl: short });
  assert.deepEqual(r, { ok: false, reason: "timeout" });
  // Fake-timer path: a fetchImpl that throws TimeoutError at once.
  const instant = async () => {
    const e = new Error("The operation was aborted due to timeout");
    e.name = "TimeoutError";
    throw e;
  };
  assert.deepEqual(await snapshot({ url, now: NOW, key: FAKE_KEY, fetchImpl: instant }), {
    ok: false,
    reason: "timeout",
  });
});

test("no key: env unset and temp db without the row means no request", async (t) => {
  const { seen, url } = await localServer(t, () => [200, g0Body()]);
  const dbPath = tempDb([]);
  let calls = 0;
  const counting = (...a) => {
    calls++;
    return fetch(...a);
  };
  const r = await snapshot({ url, now: NOW, key: null, fetchImpl: counting });
  void seen;
  assert.deepEqual(r, { ok: false, reason: "no key" });
  assert.equal(calls, 0);
  const env = { ...process.env, OPENCODE_GO_KEY: "", OPENCODE_DB: dbPath };
  const r2 = await snapshot({
    url,
    now: NOW,
    fetchImpl: counting,
    key: readGoKey({ env, dbPath }),
  });
  assert.deepEqual(r2, { ok: false, reason: "no key" });
  assert.equal(calls, 0);
});

test("key omitted: OPENCODE_GO_KEY unset and a temp OPENCODE_DB row supplies the bearer", async (t) => {
  const { seen, url } = await localServer(t, () => [200, g0Body()]);
  const dbPath = tempDb([{ key: FAKE_KEY, active: true }]);
  const prevKey = process.env.OPENCODE_GO_KEY;
  const prevDb = process.env.OPENCODE_DB;
  delete process.env.OPENCODE_GO_KEY;
  process.env.OPENCODE_DB = dbPath;
  try {
    const r = await snapshot({ url, now: NOW });
    assert.equal(r.ok, true);
    assert.equal(r.snap.at, iso(NOW));
    assert.equal(seen.count, 1);
    assert.equal(seen.auth, `Bearer ${FAKE_KEY}`);
    assert.ok(!JSON.stringify(r).includes(FAKE_KEY), "returned object leaks the key");
  } finally {
    if (prevKey === undefined) delete process.env.OPENCODE_GO_KEY;
    else process.env.OPENCODE_GO_KEY = prevKey;
    if (prevDb === undefined) delete process.env.OPENCODE_DB;
    else process.env.OPENCODE_DB = prevDb;
  }
});

test("redirects are refused: a 302 to another loopback path gives error and never hits it", async (t) => {
  const hits = { target: 0 };
  const server = http.createServer((req, res) => {
    if (req.url === "/target") {
      hits.target++;
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify(g0Body()));
      return;
    }
    res.writeHead(302, { location: "/target" });
    res.end();
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());
  const url = `http://127.0.0.1:${server.address().port}/usage`;
  const r = await snapshot({ url, now: NOW, key: FAKE_KEY });
  assert.deepEqual(r, { ok: false, reason: "error" });
  assert.equal(hits.target, 0, "the redirect target must never be requested");
});

test("evil and ftp URLs are refused with no request", async () => {
  let calls = 0;
  const counting = async () => {
    calls++;
    return { status: 200, json: async () => g0Body() };
  };
  assert.deepEqual(await snapshot({ url: "http://evil.example/", key: FAKE_KEY, fetchImpl: counting }), {
    ok: false,
    reason: "refused url",
  });
  assert.deepEqual(await snapshot({ url: "ftp://example.com/x", key: FAKE_KEY, fetchImpl: counting }), {
    ok: false,
    reason: "refused url",
  });
  assert.deepEqual(
    await snapshot({ url: "http://[::1]/x", key: "", fetchImpl: counting }),
    { ok: false, reason: "no key" },
  );
  assert.equal(calls, 0);
});

test("readGoKey: env wins, db row read, inactive ignored, missing db and junk JSON give null", () => {
  const dbPath = tempDb([{ key: FAKE_KEY, active: true }]);
  assert.equal(readGoKey({ env: { OPENCODE_GO_KEY: OTHER_KEY, OPENCODE_DB: dbPath }, dbPath }), OTHER_KEY);
  assert.equal(readGoKey({ env: { OPENCODE_DB: dbPath }, dbPath }), FAKE_KEY);
  const inactive = tempDb([{ key: FAKE_KEY, active: false }]);
  assert.equal(readGoKey({ env: { OPENCODE_DB: inactive } }), null);
  assert.equal(readGoKey({ env: {}, dbPath: path.join(tempDir(), "missing.db") }), null);
  const junkDir = tempDir();
  const junkDb = path.join(junkDir, "opencode.db");
  const db = new DatabaseSync(junkDb);
  db.exec("CREATE TABLE credential (integration_id TEXT, active INTEGER, value TEXT)");
  db.prepare("INSERT INTO credential (integration_id, active, value) VALUES ('opencode-go', 1, 'not json')").run();
  db.close();
  assert.equal(readGoKey({ env: { OPENCODE_DB: junkDb } }), null);
});

test("parseUsage maps the G0 shape and nulls malformed meters", () => {
  const p = parseUsage(g0Body());
  assert.deepEqual(p.rolling, { pct: 1, status: "ok", resets_at: iso(NOW + 2 * 3600 * 1000) });
  assert.equal(parseUsage({ usage: 5 }), null);
  assert.equal(parseUsage(null), null);
  assert.equal(parseUsage({}), null);
  const badPct = g0Body();
  badPct.usage.weekly.percent = 101;
  assert.equal(parseUsage(badPct).weekly, null);
  const badReset = g0Body();
  badReset.usage.monthly.resetsAt = "not a date";
  assert.equal(parseUsage(badReset).monthly, null);
  const missing = { usage: { weekly: g0Body().usage.weekly } };
  assert.equal(parseUsage(missing).rolling, null);
  assert.ok(parseUsage(missing).weekly);
});

test("jsonl: append keeps lines within 8 weeks, drops older; corrupt lines skipped by readLatest", async (t) => {
  const dir = tempDir();
  const file = path.join(dir, "go-usage.jsonl");
  const oldSnap = { at: iso(NOW - 9 * 7 * 86400 * 1000), rolling: null, weekly: null, monthly: null };
  const midSnap = { at: iso(NOW - 7 * 86400 * 1000), rolling: { pct: 1, status: "ok", resets_at: iso(NOW) }, weekly: null, monthly: null };
  fs.writeFileSync(file, JSON.stringify(oldSnap) + "\n" + "corrupt{\n" + JSON.stringify(midSnap) + "\n");
  const { url } = await localServer(t, () => [200, g0Body({ rolling: 2 })]);
  const r = await snapshot({ url, now: NOW, key: FAKE_KEY });
  assert.equal(r.ok, true);
  const fresh = r.snap;
  appendSnapshot(fresh, { path: file });
  const text = fs.readFileSync(file, "utf8");
  assert.ok(!text.includes("corrupt"), text);
  assert.ok(!text.includes(oldSnap.at), "old line pruned");
  const hist = readHistory({ path: file });
  assert.equal(hist.length, 2);
  assert.equal(readLatest({ path: file }).at, iso(NOW));
  assert.ok(!text.includes(FAKE_KEY));
  const since = readHistory({ path: file, since: iso(NOW - 86400 * 1000) });
  assert.equal(since.length, 1);
  assert.equal(since[0].at, iso(NOW));
});

test("CLI snapshot with no key prints one line and exits 0; latest on empty prints no snapshot", () => {
  const home = tempDir();
  const dbPath = tempDb([]);
  const env = { ...process.env, ORCH_HOME: home, OPENCODE_DB: dbPath, OPENCODE_GO_KEY: "" };
  const run = (args) => spawnSync(process.execPath, [BIN, ...args], { env, encoding: "utf8", timeout: 20000 });
  const r = run(["snapshot"]);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout.trim(), /^go usage: no key$/);
  assert.ok(!String(r.stdout).includes(FAKE_KEY));
  assert.ok(!String(r.stderr).includes(FAKE_KEY));
  assert.equal(fs.existsSync(path.join(home, ".config", "orchestrator", "go-usage.jsonl")), false);
  const latest = run(["latest"]);
  assert.equal(latest.status, 0, latest.stderr);
  assert.match(latest.stdout.trim(), /no snapshot/);
});

test("thrown error messages never carry the key", async (t) => {
  const { url } = await localServer(t, () => [200, g0Body()]);
  const evil = async () => {
    throw new Error(`boom ${FAKE_KEY} boom`);
  };
  const r = await snapshot({ url, now: NOW, key: FAKE_KEY, fetchImpl: evil });
  assert.equal(r.ok, false);
  assert.ok(!JSON.stringify(r).includes(FAKE_KEY));
});
