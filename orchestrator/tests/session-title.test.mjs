// session-title: rename goes through the server API (Basic auth), never raw sqlite,
// so connected UIs refresh the tab.
import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import fs from "node:fs";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { parseArgs, renameSession, serviceFile, sessionId } from "../bin/session-title.mjs";

function stubServer({ status = 204, password = "pw" } = {}) {
  const seen = {};
  const srv = http.createServer((req, res) => {
    let body = "";
    req.on("data", (d) => (body += d));
    req.on("end", () => {
      seen.method = req.method;
      seen.url = req.url;
      seen.auth = req.headers.authorization;
      seen.body = body;
      res.writeHead(status);
      res.end();
    });
  });
  return new Promise((resolve) => {
    srv.listen(0, "127.0.0.1", () => {
      resolve({ srv, seen, url: `http://127.0.0.1:${srv.address().port}`, password });
    });
  });
}

test("parseArgs and sessionId", () => {
  assert.deepEqual(parseArgs(["--title", "t"]), { opts: { title: "t" } });
  assert.ok(parseArgs([]).error);
  assert.ok(parseArgs(["--bogus", "x"]).error);
  assert.equal(sessionId({ session: "ses_a" }), "ses_a");
  const saved = process.env.OPENCODE_SESSION_ID;
  process.env.OPENCODE_SESSION_ID = "ses_env";
  assert.equal(sessionId({}), "ses_env");
  if (saved === undefined) delete process.env.OPENCODE_SESSION_ID;
  else process.env.OPENCODE_SESSION_ID = saved;
});

test("renameSession PATCHes title with Basic auth", async (t) => {
  const { srv, seen, url, password } = await stubServer();
  t.after(() => srv.close());
  await renameSession(url, password, "ses_1", "[m6a] repo: mod — what");
  assert.equal(seen.method, "PATCH");
  assert.equal(seen.url, "/api/session/ses_1");
  assert.equal(seen.auth, "Basic " + Buffer.from("opencode:pw").toString("base64"));
  assert.deepEqual(JSON.parse(seen.body), { title: "[m6a] repo: mod — what" });
});

test("renameSession throws on non-2xx", async (t) => {
  const { srv, url } = await stubServer({ status: 404 });
  t.after(() => srv.close());
  await assert.rejects(renameSession(url, "pw", "ses_nope", "t"), /HTTP 404/);
});

test("serviceFile honors XDG_STATE_HOME and SERVICE_JSON", () => {
  assert.ok(serviceFile().endsWith(path.join("opencode", "service.json")));
  const tmp = path.join(mkdtempSync(path.join(tmpdir(), "svc-")), "service.json");
  process.env.SERVICE_JSON = tmp;
  assert.equal(serviceFile(), tmp);
  delete process.env.SERVICE_JSON;
});

test("--for-stream renames the holder to the stream's current work", async (t) => {
  const seen = [];
  const srv = http.createServer((req, res) => {
    let body = "";
    req.on("data", (d) => (body += d));
    req.on("end", () => {
      seen.push({ method: req.method, url: req.url, body });
      if (req.method === "GET") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ data: { id: "ses_holder", title: srv.title || "Next video-studio" } }));
      } else {
        try { srv.title = JSON.parse(body).title; } catch {}
        res.writeHead(204);
        res.end();
      }
    });
  });
  await new Promise((r) => srv.listen(0, "127.0.0.1", r));
  t.after(() => srv.close());
  const url = `http://127.0.0.1:${srv.address().port}`;
  const home = mkdtempSync(path.join(tmpdir(), "oc-title-"));
  const sdir = path.join(home, ".config", "orchestrator", "streams");
  fs.mkdirSync(sdir, { recursive: true });
  fs.writeFileSync(path.join(sdir, "video-studio.json"), JSON.stringify({
    name: "video-studio", status: "active", held_session: "ses_holder", claim: null,
    next: "/gauntlet plan-a.md m3 -- pipeline stages", repo: "/r/sales-team-toolbox",
  }));
  const { syncStreamTitle, readService } = await import("../bin/session-title.mjs");
  const savedHome = process.env.ORCH_HOME;
  const savedSvc = process.env.SERVICE_JSON;
  process.env.ORCH_HOME = home;
  process.env.SERVICE_JSON = path.join(home, "service.json");
  fs.writeFileSync(process.env.SERVICE_JSON, JSON.stringify({ url, password: "pw" }));
  try {
    const { svc } = readService();
    assert.equal(await syncStreamTitle("video-studio", svc), "renamed");
    assert.equal(seen.length, 2);
    assert.equal(seen[0].method, "GET");
    assert.equal(seen[1].method, "PATCH");
    assert.deepEqual(JSON.parse(seen[1].body), { title: "[video-studio] sales-team-toolbox: m3 — pipeline stages" });
    // second call: already correct, no PATCH
    seen.length = 0;
    assert.equal(await syncStreamTitle("video-studio", svc), "current");
    assert.equal(seen.filter((s) => s.method === "PATCH").length, 0);
    // unknown stream and holder-less stream are skipped, never throw
    assert.equal(await syncStreamTitle("missing", svc), "skipped");
  } finally {
    if (savedHome === undefined) delete process.env.ORCH_HOME; else process.env.ORCH_HOME = savedHome;
    if (savedSvc === undefined) delete process.env.SERVICE_JSON; else process.env.SERVICE_JSON = savedSvc;
  }
});
