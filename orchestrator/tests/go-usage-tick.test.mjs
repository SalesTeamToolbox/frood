// goUsageTick: throttled desk-check Go usage snapshot (go-pacing G3b). Hermetic: injected
// now/snap, temp state/log paths, ORCH_HOME pointed at a temp dir so the default jsonl store
// stays hermetic, and 127.0.0.1 servers closed in after(). No test reads the real db.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { goUsageTick } from "../bin/desk-check.mjs";
import { snapshot } from "../bin/go-usage.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DESK_CHECK = path.join(HERE, "..", "bin", "desk-check.mjs");

const FAKE_KEY = "fake-go-key-for-tick-tests";
const NOW = Date.parse("2026-12-03T00:00:00.000Z");
const MIN = 60_000;
const iso = (t) => new Date(t).toISOString();
const DAY = "2026-12-03";

function g0Body({ rolling = 1, weekly = 2, monthly = 1 } = {}) {
  return {
    usage: {
      rolling: { status: "ok", percent: rolling, resetsAt: iso(NOW + 2 * 3600 * 1000) },
      weekly: { status: "ok", percent: weekly, resetsAt: "2026-12-07T00:00:00.000Z" },
      monthly: { status: "ok", percent: monthly, resetsAt: "2026-12-26T21:24:37.000Z" },
    },
  };
}

/** Temp dir as ORCH_HOME (hermetic default jsonl) plus explicit temp state/log paths. */
function setup() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gou-tick-"));
  const prevHome = process.env.ORCH_HOME;
  process.env.ORCH_HOME = dir;
  return {
    dir,
    statePath: path.join(dir, "state", "go-usage-state.json"),
    logPath: path.join(dir, "logs", "go-usage.log"),
    jsonl: path.join(dir, ".config", "orchestrator", "go-usage.jsonl"),
    restore() {
      if (prevHome === undefined) delete process.env.ORCH_HOME;
      else process.env.ORCH_HOME = prevHome;
    },
  };
}

const readState = (p) => JSON.parse(fs.readFileSync(p, "utf8"));
const logLines = (p) => (fs.existsSync(p) ? fs.readFileSync(p, "utf8").split("\n").filter(Boolean) : []);
const okSnap = (at) => ({
  ok: true,
  snap: {
    at: iso(at),
    rolling: { pct: 1, status: "ok", resets_at: iso(at + 3600 * 1000) },
    weekly: null,
    monthly: null,
  },
});

test("due tick with an ok snap: one jsonl line, last_call = now, last_fail null", async () => {
  const s = setup();
  try {
    let calls = 0;
    const snap = async () => {
      calls++;
      return okSnap(NOW);
    };
    const r = await goUsageTick({ now: NOW, limits: {}, statePath: s.statePath, logPath: s.logPath, snap });
    assert.deepEqual(r, { called: true, ok: true });
    assert.equal(calls, 1);
    const st = readState(s.statePath);
    assert.equal(st.last_call, iso(NOW));
    assert.equal(st.last_fail, null);
    const lines = fs.readFileSync(s.jsonl, "utf8").split("\n").filter(Boolean);
    assert.equal(lines.length, 1);
    assert.equal(JSON.parse(lines[0]).at, iso(NOW));
    assert.equal(logLines(s.logPath).length, 0);
  } finally {
    s.restore();
  }
});

test("throttle: 5 min later not called, 15 min later called, 60 min limit holds the 15 min tick", async () => {
  const s = setup();
  try {
    let calls = 0;
    const snap = async () => {
      calls++;
      return okSnap(NOW + calls * MIN);
    };
    assert.deepEqual(await goUsageTick({ now: NOW, limits: {}, statePath: s.statePath, logPath: s.logPath, snap }), {
      called: true,
      ok: true,
    });
    assert.equal(calls, 1);
    assert.deepEqual(
      await goUsageTick({ now: NOW + 5 * MIN, limits: {}, statePath: s.statePath, logPath: s.logPath, snap }),
      { called: false },
    );
    assert.equal(calls, 1, "snap not called inside the interval");
    assert.deepEqual(
      await goUsageTick({ now: NOW + 15 * MIN, limits: {}, statePath: s.statePath, logPath: s.logPath, snap }),
      { called: true, ok: true },
    );
    assert.equal(calls, 2);
    // A 60 min minimum interval holds a tick 15 min after the last call.
    const slow = { go: { snapshot: { min_interval_min: 60 } } };
    assert.deepEqual(
      await goUsageTick({ now: NOW + 30 * MIN, limits: slow, statePath: s.statePath, logPath: s.logPath, snap }),
      { called: false },
    );
    assert.equal(calls, 2);
  } finally {
    s.restore();
  }
});

test("failing snap: one INFO line per (reason, UTC day), no jsonl append", async () => {
  const s = setup();
  try {
    const fail = (reason) => async () => ({ ok: false, reason });
    const at = (n) => ({ now: NOW + n * MIN, limits: {}, statePath: s.statePath, logPath: s.logPath });
    assert.deepEqual(await goUsageTick({ ...at(0), snap: fail("http 401") }), {
      called: true,
      ok: false,
      reason: "http 401",
    });
    assert.deepEqual(await goUsageTick({ ...at(15), snap: fail("http 401") }), {
      called: true,
      ok: false,
      reason: "http 401",
    });
    assert.equal(logLines(s.logPath).length, 1, "same reason same day logs once");
    assert.match(logLines(s.logPath)[0], /INFO go usage: http 401/);
    assert.deepEqual(readState(s.statePath).last_fail, { reason: "http 401", day: DAY });
    assert.deepEqual(await goUsageTick({ ...at(30), snap: fail("http 500") }), {
      called: true,
      ok: false,
      reason: "http 500",
    });
    assert.equal(logLines(s.logPath).length, 2, "a different reason the same day logs again");
    assert.deepEqual(await goUsageTick({ ...at(24 * 60), snap: fail("http 401") }), {
      called: true,
      ok: false,
      reason: "http 401",
    });
    assert.equal(logLines(s.logPath).length, 3, "the same reason the next UTC day logs again");
    assert.equal(fs.existsSync(s.jsonl), false, "failures never append to the jsonl store");
  } finally {
    s.restore();
  }
});

test("a throwing snap writes last_call first: no retry storm, nothing thrown out", async () => {
  const s = setup();
  try {
    const boom = async () => {
      throw new Error("boom");
    };
    assert.deepEqual(await goUsageTick({ now: NOW, limits: {}, statePath: s.statePath, logPath: s.logPath, snap: boom }), {
      called: true,
      ok: false,
      reason: "error",
    });
    assert.equal(readState(s.statePath).last_call, iso(NOW));
    let calls = 0;
    const counting = async () => {
      calls++;
      return okSnap(NOW + 5 * MIN);
    };
    assert.deepEqual(
      await goUsageTick({ now: NOW + 5 * MIN, limits: {}, statePath: s.statePath, logPath: s.logPath, snap: counting }),
      { called: false },
    );
    assert.equal(calls, 0, "the throwing tick already recorded last_call: no retry inside the interval");
    assert.equal(logLines(s.logPath).length, 0);
  } finally {
    s.restore();
  }
});

test("the fake key never lands in the state file, the log or the jsonl", async (t) => {
  const seen = { count: 0 };
  const server = http.createServer((req, res) => {
    seen.count++;
    if (seen.count === 1) {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify(g0Body()));
    } else {
      res.writeHead(401, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "nope" }));
    }
    void req;
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());
  const url = `http://127.0.0.1:${server.address().port}/usage`;
  const s = setup();
  try {
    const snap = () => snapshot({ url, key: FAKE_KEY });
    assert.deepEqual(await goUsageTick({ now: NOW, limits: {}, statePath: s.statePath, logPath: s.logPath, snap }), {
      called: true,
      ok: true,
    });
    assert.deepEqual(
      await goUsageTick({ now: NOW + 15 * MIN, limits: {}, statePath: s.statePath, logPath: s.logPath, snap }),
      { called: true, ok: false, reason: "http 401" },
    );
    assert.equal(seen.count, 2);
    for (const [name, file] of [["state", s.statePath], ["log", s.logPath], ["jsonl", s.jsonl]]) {
      const text = fs.readFileSync(file, "utf8");
      assert.ok(!text.includes(FAKE_KEY), `${name} file leaks the fake key`);
    }
    assert.equal(logLines(s.logPath).length, 1);
  } finally {
    s.restore();
  }
});
test("spawned desk-check CLI with no key: exit 0, empty stdout, one `no key` log line, no jsonl", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gou-tick-cli-"));
  const prevHome = process.env.ORCH_HOME;
  const prevDb = process.env.OPENCODE_DB;
  const prevKey = process.env.OPENCODE_GO_KEY;
  process.env.ORCH_HOME = dir;
  try {
    const env = {
      ...process.env,
      ORCH_HOME: dir,
      ORCH_NO_NOTIFY: "1",
      CC_SIDECAR: path.join(dir, "no-such-cc-sidecar.json"),
      ORCH_CC_PROJECTS: path.join(dir, "no-such-cc-projects"),
      OPENCODE_DB: path.join(dir, "no-such-opencode.db"),
    };
    delete env.OPENCODE_GO_KEY;
    const r = spawnSync(process.execPath, [DESK_CHECK], { env, encoding: "utf8", timeout: 30000 });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(r.stdout, "");
    const orchDir = path.join(dir, ".config", "orchestrator");
    const logLines = fs.readFileSync(path.join(orchDir, "go-usage.log"), "utf8").split("\n").filter(Boolean);
    assert.equal(logLines.length, 1);
    assert.match(logLines[0], /INFO go usage: no key/);
    assert.equal(fs.existsSync(path.join(orchDir, "go-usage.jsonl")), false, "no key means no request, no append");
  } finally {
    if (prevHome === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = prevHome;
    if (prevDb === undefined) delete process.env.OPENCODE_DB;
    else process.env.OPENCODE_DB = prevDb;
    if (prevKey === undefined) delete process.env.OPENCODE_GO_KEY;
    else process.env.OPENCODE_GO_KEY = prevKey;
  }
});
test("missing state is due; junk state is due and ends valid", async () => {
  const s = setup();
  try {
    const snap = async () => okSnap(NOW);
    assert.deepEqual(await goUsageTick({ now: NOW, limits: {}, statePath: s.statePath, logPath: s.logPath, snap }), {
      called: true,
      ok: true,
    });
    const s2 = setup();
    try {
      fs.mkdirSync(path.dirname(s2.statePath), { recursive: true });
      fs.writeFileSync(s2.statePath, "{not json");
      let calls = 0;
      const counting = async () => {
        calls++;
        return okSnap(NOW);
      };
      assert.deepEqual(
        await goUsageTick({ now: NOW, limits: {}, statePath: s2.statePath, logPath: s2.logPath, snap: counting }),
        { called: true, ok: true },
      );
      assert.equal(calls, 1);
      assert.equal(readState(s2.statePath).last_call, iso(NOW));
    } finally {
      s2.restore();
    }
  } finally {
    s.restore();
  }
});
