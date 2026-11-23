// Fails when a tracked file names a private path, host or project.
//
// The list lives OUTSIDE the repo on purpose (it is personal data and must never ship):
//   ~/.config/orchestrator/private-strings.txt
// one literal per line (case-insensitive), `#` starts a comment. The real home is read here on
// purpose — ORCH_HOME is a test fixture, and this scan is about the owner's machine.
// No list file (a fresh clone, CI) = skipped with a message, not a failure.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const LIST = path.join(os.homedir(), ".config", "orchestrator", "private-strings.txt");

export function readList(file = LIST) {
  return fs
    .readFileSync(file, "utf8")
    .split(/\r?\n/)
    .map((l) => l.replace(/\s*#.*$/, "").trim())
    .filter(Boolean)
    .map((l) => l.toLowerCase());
}

/** Every tracked file with a match: [{ file, line, text, pattern }]. */
export function scan(patterns, repo = REPO, files = null) {
  const tracked = files ?? execFileSync("git", ["-C", repo, "ls-files", "-z"], { encoding: "utf8" }).split("\0").filter(Boolean);
  const hits = [];
  for (const file of tracked) {
    let buf;
    try {
      buf = fs.readFileSync(path.join(repo, file));
    } catch {
      continue; // tracked but deleted in the working tree: git diff is someone else's business
    }
    if (buf.includes(0)) continue; // binary
    const lines = buf.toString("utf8").split(/\r?\n/);
    for (let i = 0; i < lines.length; i++) {
      const low = lines[i].toLowerCase();
      for (const p of patterns) {
        if (low.includes(p)) hits.push({ file, line: i + 1, text: lines[i].slice(0, 120), pattern: p });
      }
    }
  }
  return hits;
}

test("no tracked file contains a private string", (t) => {
  if (!fs.existsSync(LIST)) {
    t.skip(`no private-string list at ${LIST} — nothing to scan`);
    return;
  }
  const hits = scan(readList());
  assert.deepEqual(
    hits.map((h) => `${h.file}:${h.line}: ${h.text.trim()}`),
    [],
    `tracked files name private strings (list: ${LIST})`,
  );
});
