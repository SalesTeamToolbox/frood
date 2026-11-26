#!/usr/bin/env node
// Shared scope fence: `checkScope({ repo, base, sha, scope })` compares
// `git diff --name-only base..sha` (run with cwd = `repo`) against the ticket's
// `--scope` globs, with a hard deny list a worker's diff may never touch.
//
// `matchAny` / `matchGlob` live here and are re-imported by `board.mjs` — there
// is exactly one glob matcher for scope, deny, guarded and EGM paths. Do not
// write a second matcher.
import path from "node:path";
import { spawnSync } from "node:child_process";

// Hard deny list: orchestrator-owned state a worker's diff may never edit,
// even when `--scope` covers it.
export const DENY = [".claude/plans/**", ".opencode/**"];

// Globs (B10): P matches G iff P matches G, or one of P's ancestor directories
// matches G. So scope "auth/login.ts" matches "**/auth" through its parent dir,
// even though the file itself never does.
function matchGlob(p, g) {
  const P = String(p).replace(/\\/g, "/").replace(/^\.\//, "");
  if (path.posix.matchesGlob(P, g)) return true;
  const ancestors = P.split("/");
  ancestors.pop();
  while (ancestors.length) {
    if (path.posix.matchesGlob(ancestors.join("/"), g)) return true;
    ancestors.pop();
  }
  return false;
}
export const matchAny = (p, globs) => globs.some((g) => matchGlob(p, g));

const isDenied = (p) => matchAny(p, DENY);

const SCOPE_TIMEOUT_MS = Number(process.env.SCOPE_TIMEOUT_MS) || 30_000;

// A deleted or renamed file counts by its old and new paths: `--no-renames`
// forces git to list a deleted file's old path and a renamed file's old path
// plus its new path (git otherwise collapses a rename to its new path), so
// both are checked against scope and the deny list.
export function checkScope({ repo, base, sha, scope }) {
  const out = spawnSync("git", ["-C", repo, "diff", "--no-renames", "--name-only", `${base}..${sha}`], {
    encoding: "utf8",
    timeout: SCOPE_TIMEOUT_MS,
    windowsHide: true,
  });
  if (out.error || (out.status != null && out.status !== 0)) {
    // The diff cannot be computed: fail closed. No path can be named, so `error` carries the reason.
    const why = String(out.error?.message ?? out.stderr ?? "").trim().split("\n")[0] || `git diff exited ${out.status}`;
    return { ok: false, outOfScope: [], denied: [], error: why };
  }
  const paths = String(out.stdout || "")
    .split("\n")
    .map((p) => p.trim())
    .filter(Boolean);
  const outOfScope = [];
  const denied = [];
  for (const p of paths) {
    if (isDenied(p)) {
      denied.push(p);
    } else if (!matchAny(p, scope)) {
      outOfScope.push(p);
    }
  }
  return { ok: outOfScope.length === 0 && denied.length === 0, outOfScope, denied, error: null };
}
