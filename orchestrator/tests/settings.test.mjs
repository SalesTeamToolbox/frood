// orchestrator/bin/settings.mjs — get / set / list + getSetting import.
// Every spawnSync carries a timeout; tests run under ORCH_HOME temp dirs only.
import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { getSetting } from "../bin/settings.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "settings.mjs");

const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

const TIMEOUT = 10_000;

function home() {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), "orch-settings-"));
  CLEAN.push(h);
  return h;
}

function settingsFile(h) {
  return path.join(h, ".config", "orchestrator", "settings.json");
}

// Run one test body with ORCH_HOME pointing at a fresh temp dir, restoring it after.
function withHome(fn) {
  const h = home();
  const saved = process.env.ORCH_HOME;
  process.env.ORCH_HOME = h;
  try {
    return fn(h);
  } finally {
    if (saved === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = saved;
  }
}

function cli(args, h) {
  const env = { ...process.env, ORCH_HOME: h };
  return spawnSync(process.execPath, [BIN, ...args], { env, encoding: "utf8", timeout: TIMEOUT });
}

test("no settings file: get archive_nested_sessions prints true", () => {
  withHome((h) => {
    const r = cli(["get", "archive_nested_sessions"], h);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(r.stdout.trim(), "true");
  });
});

test("getSetting mirrors the CLI when the file is missing", () => {
  withHome((h) => {
    assert.equal(getSetting("archive_nested_sessions"), true);
  });
});

test("set false then get prints false; file stays valid JSON and keeps other keys", () => {
  withHome((h) => {
    const file = settingsFile(h);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify({ archive_nested_sessions: true, other: "keep me" }), "utf8");

    const set = cli(["set", "archive_nested_sessions", "false"], h);
    assert.equal(set.status, 0, set.stderr);

    const got = cli(["get", "archive_nested_sessions"], h);
    assert.equal(got.status, 0, got.stderr);
    assert.equal(got.stdout.trim(), "false");

    const content = fs.readFileSync(file, "utf8");
    const parsed = JSON.parse(content); // must be valid JSON
    assert.equal(parsed.archive_nested_sessions, false);
    assert.equal(parsed.other, "keep me", "other keys in the file are kept");

    // getSetting import returns the same value
    assert.equal(getSetting("archive_nested_sessions"), false);
  });
});

test("corrupt file: defaults apply, exit 0", () => {
  withHome((h) => {
    const file = settingsFile(h);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, "{ not valid json", "utf8");

    const r = cli(["get", "archive_nested_sessions"], h);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(r.stdout.trim(), "true");

    assert.equal(getSetting("archive_nested_sessions"), true);
  });
});

test("unknown key: exit 2 and the file is unchanged", () => {
  withHome((h) => {
    const file = settingsFile(h);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify({ archive_nested_sessions: true }), "utf8");
    const before = fs.readFileSync(file, "utf8");

    const r = cli(["get", "no_such_key"], h);
    assert.equal(r.status, 2);

    const set = cli(["set", "no_such_key", "true"], h);
    assert.equal(set.status, 2);

    assert.equal(fs.readFileSync(file, "utf8"), before, "file unchanged on unknown key");
  });
});

test("non-boolean value: exit 2 and the file is unchanged", () => {
  withHome((h) => {
    const file = settingsFile(h);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify({ archive_nested_sessions: true }), "utf8");
    const before = fs.readFileSync(file, "utf8");

    for (const bad of ["yes", "1", "True", ""]) {
      const r = cli(["set", "archive_nested_sessions", bad], h);
      assert.equal(r.status, 2, `set ${JSON.stringify(bad)}`);
    }

    assert.equal(fs.readFileSync(file, "utf8"), before, "file unchanged on non-boolean value");
  });
});

test("list prints the effective settings as JSON", () => {
  withHome((h) => {
    const r = cli(["list"], h);
    assert.equal(r.status, 0, r.stderr);
    assert.deepEqual(JSON.parse(r.stdout), { archive_nested_sessions: true });
  });
});
