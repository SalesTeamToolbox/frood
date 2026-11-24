import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync, spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { check } from "../bin/desk-check.mjs";
import { appendAck, appendEvent, orchRoot } from "../bin/handoff.mjs";
import { processStart } from "../bin/proc-tree.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "desk-check.mjs");
const CLEAN = [];
// Captured at module load: the one directory a test must never resolve a lock path into.
const REAL_HOME = os.homedir();
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

function home() {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), "orch-check-"));
  CLEAN.push(h);
  return h;
}
const sdir = (h) => path.join(h, ".config", "orchestrator", "streams");
function mkStream(h, name = "m6a") {
  fs.mkdirSync(sdir(h), { recursive: true });
  fs.writeFileSync(
    path.join(sdir(h), `${name}.json`),
    JSON.stringify({ name, repo: "", plan: "", status: "active", next: "n", done: "", waiting: "", written_at: new Date().toISOString(), written_by: "", consumed_at: null, done_at: null }),
  );
}
function inHome(h, fn) {
  const saved = process.env.ORCH_HOME;
  process.env.ORCH_HOME = h;
  if (path.resolve(orchRoot()) === path.resolve(REAL_HOME)) {
    if (saved === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = saved;
    throw new Error("orchRoot resolved to the real home — refusing");
  }
  try {
    return fn();
  } finally {
    if (saved === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = saved;
  }
}
const lockDirOf = (h) => path.join(h, ".config", "orchestrator", "desk-watch.lock");
const done = (run) => ({ key: `run:${run}:done`, kind: "run-done", run, out: `/x/${run}.md`, agent: "worker", exit: 0, outcome: "done", at: new Date().toISOString() });

test("check: empty board is code 0", () => {
  const h = home();
  assert.deepEqual(inHome(h, () => check()), { code: 0 });
});

test("check: pending events with no watcher pages (code 1)", () => {
  const h = home();
  mkStream(h);
  inHome(h, () => appendEvent("m6a", done("worker-r1")));
  const r = inHome(h, () => check());
  assert.equal(r.code, 1);
  assert.match(r.text, /1 unhandled event\(s\) on m6a\(1\); no watcher — open a \/frood-desk/);
});

test("check: an unresolved ESCALATE alone does not page (the daemon mails the holder)", () => {
  const h = home();
  mkStream(h);
  inHome(h, () => appendAck("m6a", "run:t1/worker-r1:done", "ESCALATE worker-blocked /x/out.md", { ticket: "t1" }));
  assert.deepEqual(inHome(h, () => check()), { code: 0 });
});

test("check: pending events with a live watcher is code 0", () => {
  const h = home();
  mkStream(h);
  inHome(h, () => appendEvent("m6a", done("worker-r1")));
  fs.mkdirSync(lockDirOf(h), { recursive: true });
  fs.writeFileSync(
    path.join(lockDirOf(h), "owner"),
    JSON.stringify({ pid: process.pid, pid_start: processStart(process.pid), at: new Date().toISOString(), token: "self", by: "oc" }),
  );
  assert.deepEqual(inHome(h, () => check()), { code: 0 });
});

test("check: pending events with a stale watcher pages and names it", () => {
  const h = home();
  mkStream(h);
  inHome(h, () => appendEvent("m6a", done("worker-r1")));
  fs.mkdirSync(lockDirOf(h), { recursive: true });
  fs.writeFileSync(
    path.join(lockDirOf(h), "owner"),
    JSON.stringify({ pid: process.pid, pid_start: "2020-01-01T00:00:00.000Z", at: new Date(Date.now() - 3600000).toISOString(), token: "recycled" }),
  );
  const r = inHome(h, () => check());
  assert.equal(r.code, 1);
  assert.match(r.text, new RegExp(`stale watcher \\(pid ${process.pid}, pid recycled \\(start mismatch\\)\\)`));
});

test("check CLI: exits 0/1/2 with ORCH_NO_NOTIFY=1", () => {
  const h = home();
  const env = { ...process.env, ORCH_HOME: h, ORCH_NO_NOTIFY: "1" };
  const cli = (args) => spawnSync(process.execPath, [BIN, ...args], { env, encoding: "utf8" });
  assert.equal(cli([]).status, 0);
  mkStream(h);
  fs.appendFileSync(path.join(sdir(h), "m6a.events.jsonl"), JSON.stringify(done("worker-r1")) + "\n");
  const paged = cli([]);
  assert.equal(paged.status, 1, paged.stderr);
  assert.match(paged.stdout, /open a \/frood-desk/);
  assert.equal(cli(["--nope"]).status, 2);
});

test("desk-check syncs a holder tab to its stream's work (best effort, exit code unchanged)", async (t) => {
  // The stub runs in its own process: spawnSync blocks this loop, so an
  // in-process stub server could never accept the CLI's connection (deadlock).
  const stubDir = fs.mkdtempSync(path.join(os.tmpdir(), "orch-dc-stub-"));
  CLEAN.push(stubDir);
  const stubFile = path.join(stubDir, "stub-server.mjs");
  fs.writeFileSync(stubFile, `
    import http from "node:http";
    let title = "Next m6a";
    const seen = [];
    const srv = http.createServer((req, res) => {
      let body = "";
      req.on("data", (d) => (body += d));
      req.on("end", () => {
        if (req.method === "GET") {
          res.writeHead(200, { "content-type": "application/json" });
          res.end(JSON.stringify({ data: { id: "ses_holder", title } }));
        } else {
          try { title = JSON.parse(body).title; seen.push(title); } catch {}
          res.writeHead(204);
          res.end();
        }
      });
    });
    srv.listen(0, "127.0.0.1", () => { console.log("READY " + srv.address().port); });
    process.on("message", (m) => { if (m === "dump") process.send(seen); });
  `);
  const { spawn: spawnChild } = await import("node:child_process");
  const stubCheck = spawnSync(process.execPath, ["--check", stubFile], { encoding: "utf8" });
  assert.equal(stubCheck.status, 0, stubCheck.stderr);
  const child = spawnChild(process.execPath, [stubFile], { stdio: ["ignore", "pipe", "inherit", "ipc"] });
  t.after(() => child.kill());
  const port = await new Promise((resolve, reject) => {
    const to = setTimeout(() => reject(new Error("stub never became ready")), 10_000);
    child.stdout.on("data", (d) => {
      const m = /READY (\d+)/.exec(d.toString());
      if (m) { clearTimeout(to); resolve(Number(m[1])); }
    });
    child.on("error", reject);
  });
  const h = home();
  mkStream(h);
  const svc = path.join(h, "service.json");
  fs.writeFileSync(svc, JSON.stringify({ url: `http://127.0.0.1:${port}`, password: "pw" }));
  fs.writeFileSync(
    path.join(sdir(h), "m6a.json"),
    JSON.stringify({ name: "m6a", repo: "sales-team-toolbox", plan: "", status: "active", held_by: "oc", held_session: "ses_holder", next: "/frood-gauntlet plan-a.md m3 -- pipeline", done: "", waiting: "", written_at: new Date().toISOString(), written_by: "", consumed_at: new Date().toISOString(), done_at: null }),
  );
  const env = { ...process.env, ORCH_HOME: h, ORCH_NO_NOTIFY: "1", SERVICE_JSON: svc };
  const r = spawnSync(process.execPath, [BIN], { env, encoding: "utf8", timeout: 60_000 });
  assert.equal(r.status, 0, r.stderr); // no unhandled events: code 0, sync best-effort
  const titles = await new Promise((resolve) => {
    const to = setTimeout(() => resolve(null), 5_000);
    child.once("message", (m) => { clearTimeout(to); resolve(m); });
    child.send("dump");
  });
  assert.deepEqual(titles, ["[m6a] sales-team-toolbox: m3 — pipeline"], JSON.stringify(titles));
});
