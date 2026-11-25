// Suite-wide guard against fixture children (fake-opencode.mjs and anything it spawns) outliving the
// test process that launched them. Every spawn in these suites spreads `process.env`, so the
// FAKE_OC_SUITE marker reaches oc-worker and its agent, and any grandchild they detach.
//
// Usage (top of each test file, right after the imports, before any spawn):
//   import { installFixtureGuard } from "./fixtures/fixture-guard.mjs";
//   installFixtureGuard();

import fs from "node:fs";
import { after } from "node:test";
import assert from "node:assert/strict";

// Unique id for this test process. Set once; children inherit it via the spread env.
let SUITE_ID = null;

export function installFixtureGuard() {
  if (!process.env.FAKE_OC_SUITE) {
    process.env.FAKE_OC_SUITE = `${process.pid}-${Date.now()}`;
  }
  SUITE_ID = process.env.FAKE_OC_SUITE;
}

// Read one pid's /proc/environ and test whether it contains `FAKE_OC_SUITE=<id>`.
// Returns false when the environ cannot be read (gone, no permission, non-Linux).
function environHas(pid, needle) {
  try {
    const env = fs.readFileSync(`/proc/${pid}/environ`, { encoding: "latin1" });
    return env.split("\0").some((e) => e === needle);
  } catch {
    return false;
  }
}

// Pids (other than this process) whose environ carries the suite marker.
// Returns [] on platforms without /proc (non-Linux).
export function fixtureChildren(id) {
  if (process.platform !== "linux") return [];
  const own = process.pid;
  const needle = `FAKE_OC_SUITE=${id}`;
  let pids = [];
  try {
    pids = fs.readdirSync("/proc").filter((n) => /^\d+$/.test(n)).map(Number);
  } catch {
    return [];
  }
  return pids.filter((p) => p !== own && environHas(p, needle));
}

// SIGKILL each fixture child for `id`, ignoring ESRCH (already gone). Returns the pids killed.
export function reapFixtureChildren(id) {
  const killed = [];
  for (const pid of fixtureChildren(id)) {
    try {
      process.kill(pid, "SIGKILL");
      killed.push(pid);
    } catch (e) {
      if (e.code !== "ESRCH") throw e;
    }
  }
  return killed;
}

function cmdlineOf(pid) {
  try {
    return fs.readFileSync(`/proc/${pid}/cmdline`, { encoding: "latin1" }).replace(/\0/g, " ").trim();
  } catch {
    return `<unreadable:${pid}>`;
  }
}

// After the suite: reap any fixture child still alive, then fail if any survive.
// Polls at most 5 s for pids to vanish.
after(async () => {
  if (!SUITE_ID) return;
  const deadline = Date.now() + 5000;
  let killed = [];
  while (Date.now() < deadline) {
    killed = reapFixtureChildren(SUITE_ID);
    if (killed.length === 0) break;
    await new Promise((r) => setTimeout(r, 200));
  }
  const survivors = fixtureChildren(SUITE_ID);
  assert.deepEqual(
    [],
    survivors,
    `fixture children survived the suite: pids ${survivors.join(",")} cmdlines ${survivors.map(cmdlineOf).join("; ")}`,
  );
});
