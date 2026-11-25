// cc-usage: normalizers, store (newest at wins, 8-week prune) and CLI exit codes. Hermetic via ORCH_HOME.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "cc-usage.mjs");
const FX = (n) => path.join(HERE, "fixtures", "cc-usage", n);

function sandbox() {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "ccu-"));
  const dir = path.join(home, ".config", "orchestrator");
  const run = (args, input) =>
    spawnSync(process.execPath, [BIN, ...args], { env: { ...process.env, ORCH_HOME: home }, input, encoding: "utf8", timeout: 20000 });
  return { home, dir, run };
}

test("app fixture normalizes to the record", () => {
  const s = sandbox();
  const r = s.run(["snapshot", "--from-app", "-"], fs.readFileSync(FX("app.json"), "utf8"));
  assert.equal(r.status, 0, r.stderr);
  const rec = JSON.parse(fs.readFileSync(path.join(s.dir, "cc-usage.json"), "utf8"));
  assert.equal(rec.source, "app");
  assert.deepEqual(rec.five_hour, { pct: 40, resets_at: "2026-01-07T05:00:00.000Z" });
  assert.deepEqual(rec.weekly, { pct: 42, resets_at: "2026-01-08T12:00:00.000Z" });
  assert.deepEqual(rec.fable, { pct: 13, resets_at: "2026-01-08T12:00:00.000Z" });
  assert.match(s.run(["latest", "--json"]).stdout, /"weekly"/);
});

test("statusline fixture normalizes; missing fable and window -> null", () => {
  const s = sandbox();
  const r = s.run(["snapshot", "--from-statusline", FX("statusline.json")]);
  assert.equal(r.status, 0, r.stderr);
  const rec = JSON.parse(fs.readFileSync(path.join(s.dir, "cc-usage.json"), "utf8"));
  assert.equal(rec.source, "statusline");
  assert.equal(rec.at, new Date(1767765600000).toISOString());
  assert.equal(rec.weekly.pct, 30);
  assert.equal(rec.weekly.resets_at, new Date(1768300000 * 1000).toISOString());
  assert.equal(rec.five_hour.pct, 12.5);
  assert.equal(rec.fable, null);
});

test("app with only a weekly window: five_hour and fable null", () => {
  const s = sandbox();
  const r = s.run(["snapshot", "--from-app", "-"], JSON.stringify([{ label: "Weekly · all models", percentUsed: 5, resetsAt: "2026-01-08T12:00:00Z" }]));
  assert.equal(r.status, 0, r.stderr);
  const rec = JSON.parse(fs.readFileSync(path.join(s.dir, "cc-usage.json"), "utf8"));
  assert.equal(rec.five_hour, null);
  assert.equal(rec.fable, null);
});

test("non-JSON or no weekly window exits 2 and leaves files untouched", () => {
  const s = sandbox();
  assert.equal(s.run(["snapshot", "--from-app", "-"], "not json").status, 2);
  assert.equal(s.run(["snapshot", "--from-app", "-"], JSON.stringify([{ label: "5-hour limit", percentUsed: 1, resetsAt: "2026-01-07T05:00:00Z" }])).status, 2);
  assert.equal(s.run(["snapshot", "--from-statusline", path.join(s.home, "missing.json")]).status, 2);
  assert.equal(fs.existsSync(path.join(s.dir, "cc-usage.json")), false);
  assert.equal(fs.existsSync(path.join(s.dir, "cc-usage.jsonl")), false);
});

test("newer at wins across sources; an older snapshot does not replace latest", () => {
  const s = sandbox();
  // A statusline sidecar saved an hour ago; the app snapshot is stamped "now", so it wins.
  const side = JSON.parse(fs.readFileSync(FX("statusline.json"), "utf8"));
  side.saved_at = Date.now() - 3600e3;
  const sidePath = path.join(s.home, "side.json");
  fs.writeFileSync(sidePath, JSON.stringify(side));
  s.run(["snapshot", "--from-statusline", sidePath]);
  s.run(["snapshot", "--from-app", "-"], fs.readFileSync(FX("app.json"), "utf8"));
  assert.equal(JSON.parse(fs.readFileSync(path.join(s.dir, "cc-usage.json"), "utf8")).source, "app");
  const r = s.run(["snapshot", "--from-statusline", sidePath]);
  assert.equal(r.status, 0);
  assert.equal(r.stdout.trim(), "older");
  assert.equal(JSON.parse(fs.readFileSync(path.join(s.dir, "cc-usage.json"), "utf8")).source, "app");
  const lines = fs.readFileSync(path.join(s.dir, "cc-usage.jsonl"), "utf8").trim().split("\n");
  assert.equal(lines.length, 2);
});

test("history is pruned past 8 weeks", async () => {
  const s = sandbox();
  fs.mkdirSync(s.dir, { recursive: true });
  const old = { at: new Date(Date.now() - 9 * 7 * 86400e3).toISOString(), source: "app", five_hour: null, weekly: { pct: 1, resets_at: null }, fable: null };
  fs.writeFileSync(path.join(s.dir, "cc-usage.jsonl"), JSON.stringify(old) + "\n");
  const r = s.run(["snapshot", "--from-app", "-"], fs.readFileSync(FX("app.json"), "utf8"));
  assert.equal(r.status, 0, r.stderr);
  const lines = fs.readFileSync(path.join(s.dir, "cc-usage.jsonl"), "utf8").trim().split("\n");
  assert.equal(lines.length, 1);
  assert.equal(JSON.parse(lines[0]).weekly.pct, 42);
});
