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

function git(repo, args) {
  return spawnSync("git", ["-C", repo, ...args], { encoding: "utf8", timeout: SCOPE_TIMEOUT_MS, windowsHide: true });
}

// The commit to diff from. `base` is the ticket's base_sha, which is not refreshed when the branch is rebased.
// With `baseRef` (the adapter's base ref, e.g. origin/main), the fence also considers its local branch
// counterpart: when baseRef names a remote-tracking ref <remote>/<branch> and refs/remotes/<baseRef> resolves,
// refs/heads/<branch> is a candidate too. For each candidate ref that resolves, let M = merge-base(ref, sha):
// - a candidate is accepted only when base is an ancestor of M and M != sha (a branch already merged into the
//   ref would give an empty diff and a vacuous pass);
// - diff from the newest accepted M (when both are accepted, the one the other is an ancestor of);
// - with none accepted, diff from `base` exactly as before.
// So a branch rebased onto a local main that is ahead of origin/main diffs from the local-main merge-base
// instead of the stale base_sha; a baseRef that lags the ticket base still falls back to `base`.
// A missing or unresolvable baseRef, or a failed merge-base, diffs from `base` as before.
// All git calls keep the existing timeout via the shared `git()` helper.
function isAncestor(repo, a, b) {
  const anc = git(repo, ["merge-base", "--is-ancestor", a, b]);
  return !anc.error && anc.status === 0;
}
function mergeBase(repo, ref, sha) {
  const mb = git(repo, ["merge-base", ref, sha]);
  if (mb.error || mb.status !== 0) return null;
  const m = String(mb.stdout || "").trim();
  return m || null;
}
function diffFrom(repo, base, sha, baseRef) {
  if (!baseRef) return base;
  // Candidate refs: baseRef itself, plus its local branch counterpart when baseRef is a remote-tracking ref
  // (<remote>/<branch>) that resolves under refs/remotes/.
  const refs = [baseRef];
  const slash = baseRef.indexOf("/");
  if (slash > 0) {
    const branch = baseRef.slice(slash + 1);
    const remoteRev = git(repo, ["rev-parse", "--verify", `refs/remotes/${baseRef}`]);
    if (!remoteRev.error && remoteRev.status === 0) {
      const localRev = git(repo, ["rev-parse", "--verify", `refs/heads/${branch}`]);
      if (!localRev.error && localRev.status === 0) refs.push(branch);
    }
  }
  let from = base;
  for (const ref of refs) {
    const m = mergeBase(repo, ref, sha);
    if (!m || m === sha) continue; // merged into the ref: empty diff would be a vacuous pass
    if (!isAncestor(repo, base, m)) continue; // base not an ancestor of M: stale, keep base
    // Accept the newest: the one the current `from` is an ancestor of.
    if (from === base || isAncestor(repo, from, m)) from = m;
  }
  return from;
}

// A deleted or renamed file counts by its old and new paths: `--no-renames`
// forces git to list a deleted file's old path and a renamed file's old path
// plus its new path (git otherwise collapses a rename to its new path), so
// both are checked against scope and the deny list. `-z` keeps non-ASCII paths
// unquoted (core.quotePath would otherwise wrap them in quotes and escape DENY).
// Returns `from`: the commit the diff was taken from.
export function checkScope({ repo, base, sha, scope, baseRef }) {
  const from = diffFrom(repo, base, sha, baseRef);
  const out = git(repo, ["diff", "--no-renames", "--name-only", "-z", `${from}..${sha}`]);
  if (out.error || (out.status != null && out.status !== 0)) {
    // The diff cannot be computed: fail closed. No path can be named, so `error` carries the reason.
    const why = String(out.error?.message ?? out.stderr ?? "").trim().split("\n")[0] || `git diff exited ${out.status}`;
    return { ok: false, outOfScope: [], denied: [], error: why, from };
  }
  const paths = String(out.stdout || "")
    .split("\0")
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
  return { ok: outOfScope.length === 0 && denied.length === 0, outOfScope, denied, error: null, from };
}
