#!/usr/bin/env node
// Worktree fence: keeps a headless run inside its own worktree.
//
//   Allowed write roots for a run with --dir <D> and --out <O>:
//     <D>; the directory of <O> (the report folder); os.tmpdir(); /tmp.
//   Every path is resolved with path.resolve and compared by real path, so a
//   symlink (e.g. .venv) that points outside is not itself an escape.
//   Detection has two parts:
//     B) exact: scan the run's own events for write-file tool_use parts whose
//        path resolves outside the allowed roots. Only completed write events
//        count as this run's own writes.
//     C) backstop: if <D> is a linked worktree, snapshot `git -C <main>
//        status --porcelain -z` before the run and after each attempt; paths
//        that turned dirty are `suspected` (attribution not exact, never reverted).
//
//   Response: for each exact escaped path inside main's git tree that is a
//   single tracked regular file and whose writes this run provably authored
//   (replay of its completed write events over the index blob byte-equals the
//   current file content), append its git diff to <O>.escaped.patch and
//   restore it. When in any doubt, the path goes in `left` with a note, its
//   diff is saved, and nothing is changed.
//
//   This module is pure (no opencode, no slots). oc-worker.mjs wires it in.
//
// Usage:
//   import { allowedRoots, isOutside, scanEvents, findMain, gitStatusZ,
//            parseStatusZ, underMain, appendDiff, restorePath,
//            foldEscapes, finalizeEscapes, footer, editFenceConfig,
//            mergeEditFence } from "./worktree-fence.mjs";

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";

const WRITE_TOOLS = new Set(["edit", "write", "patch", "multiedit"]);

// ---------------------------------------------------------------- allowed roots

// Allowed write roots for a run with --dir <D> and --out <O>:
//   <D>; dir of <O>; os.tmpdir(); /tmp. All resolved with path.resolve.
//   `extra` (optional) adds another root, e.g. the --report directory.
export function allowedRoots(dir, out, extra) {
  const roots = new Set();
  const add = (p) => {
    try {
      roots.add(path.resolve(p));
    } catch {}
  };
  add(dir);
  add(path.dirname(path.resolve(out)));
  if (extra) add(extra);
  add(os.tmpdir());
  add("/tmp");
  return roots;
}

// ---------------------------------------------------------------- real path helpers

// Real path of p if it exists, else the resolved path itself.
export function realPath(p) {
  try {
    return fs.realpathSync(p);
  } catch {
    return path.resolve(p);
  }
}

// Is lexical path under root? (no symlink resolution)
function underLexical(absPath, root) {
  return absPath === root || absPath.startsWith(root + path.sep);
}

// Is absPath under any of the roots? A path is inside when EITHER its lexical
// path (resolved against --dir) OR its realpath is under an allowed root. So a
// symlink like D/.venv -> main/.venv is never an escape, whether the target
// exists or not.
function underRoot(absPath, roots) {
  for (const root of roots) {
    if (underLexical(absPath, root)) return true;
    try {
      const rp = realPath(absPath);
      const rroot = realPath(root);
      if (rp === rroot || rp.startsWith(rroot + path.sep)) return true;
    } catch {}
  }
  return false;
}

// Is p outside all allowed roots?
export function isOutside(p, roots) {
  return !underRoot(path.resolve(p), roots);
}

// ---------------------------------------------------------------- event scanning

// Write event recorded for one escaped path: { tool, status, input }.
class WriteEvent {
  constructor({ tool, status, input }) {
    this.tool = tool;
    this.status = status;
    this.input = input;
  }
  get completed() {
    return this.status === "completed";
  }
}

// Collect the file paths touched by one tool_use part.
// Real OpenCode 2.4.1 shape: { type: "tool_use", part: { type: "tool",
//   tool: "edit", state: { status: "completed", input: { path,
//   oldString, newString } } } }.
// Accepts `part.tool` or `part.name` for the tool name, and
// `part.state?.input` or `part.input` for the input. Path keys: `path`,
// `filePath`, `file_path`. Text keys: `oldString`/`newString`/`content` and
// `old_string`/`new_string`.
function toolPaths(part) {
  const input = part.state?.input ?? part.input ?? {};
  const tool = String(part.tool ?? part.name ?? "");
  const files = [];

  if (WRITE_TOOLS.has(tool)) {
    if (tool === "patch") {
      if (Array.isArray(input.paths)) files.push(...input.paths);
      if (input.path) files.push(input.path);
      if (input.new_path) files.push(input.new_path);
      if (input.old_path) files.push(input.old_path);
    } else if (tool === "multiedit") {
      if (input.filePath) files.push(input.filePath);
      if (Array.isArray(input.edits)) {
        for (const ed of input.edits) {
          if (ed && ed.filePath) files.push(ed.filePath);
        }
      }
    } else {
      if (input.filePath) files.push(input.filePath);
      if (input.path) files.push(input.path);
      if (input.file_path) files.push(input.file_path);
    }
  } else if (
    input.filePath ||
    input.file_path ||
    (input.path &&
      (input.content ||
        input.new_text ||
        input.old_text ||
        input.new_str ||
        input.old_str ||
        input.newString ||
        input.oldString))
  ) {
    if (input.filePath) files.push(input.filePath);
    if (input.file_path) files.push(input.file_path);
    if (input.path) files.push(input.path);
  }

  return files.filter((f) => f && typeof f === "string");
}

// Build one write event for a tool_use part, or null when it is not a write.
function writeEventFor(part) {
  const input = part.state?.input ?? part.input ?? {};
  const tool = String(part.tool ?? part.name ?? "");
  if (!WRITE_TOOLS.has(tool)) return null;
  const status = part.state?.status ?? "";
  return new WriteEvent({ tool, status, input });
}

// Scan events text (newline-delimited JSON) for write-file tool_use parts
// whose path resolves outside the allowed roots. Returns
// { escaped: Map<absPath, WriteEvent[]> } mapping each escaped absolute path
// to the ordered list of this attempt's write events for it.
export function scanEvents(eventsText, roots, dir) {
  const base = path.resolve(dir || "");
  const escaped = new Map();
  for (const line of String(eventsText || "").split(/\r?\n/)) {
    if (!line.trim()) continue;
    let e;
    try {
      e = JSON.parse(line);
    } catch {
      continue;
    }
    if (!e || typeof e !== "object") continue;
    const part = e.part || {};
    if (!part || typeof part !== "object") continue;
    if (e.type !== "tool_use" && e.type !== "toolUse") continue;
    const ev = writeEventFor(part);
    if (!ev) continue;
    for (const f of toolPaths(part)) {
      const abs = path.resolve(base, f);
      if (!isOutside(abs, roots)) continue;
      let list = escaped.get(abs);
      if (!list) {
        list = [];
        escaped.set(abs, list);
      }
      list.push(ev);
    }
  }
  return { escaped };
}

// Has at least one completed write event for this path?
export function hasCompletedWrite(events) {
  return events.some((ev) => ev.completed);
}

// ---------------------------------------------------------------- main checkout

// Find the main checkout for a linked worktree <dir>.
// Returns null when <dir> is not a linked worktree (common dir == git dir)
// or git is unavailable. Always returns an absolute path.
export function findMain(dir) {
  let commonDir, gitDir;
  try {
    commonDir = execFileSync("git", ["-C", dir, "rev-parse", "--path-format=absolute", "--git-common-dir"], {
      encoding: "utf8", windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"], timeout: 10000,
    }).trim();
    gitDir = execFileSync("git", ["-C", dir, "rev-parse", "--path-format=absolute", "--git-dir"], {
      encoding: "utf8", windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"], timeout: 10000,
    }).trim();
  } catch {
    return null;
  }
  if (!commonDir || commonDir === gitDir) return null;
  // main checkout is the parent of the common (.git) dir
  const main = path.resolve(path.dirname(commonDir));
  // The parent of the common dir is the top level only when it really is the
  // repo's working tree. With a bare repo or a --separate-git-dir sitting
  // inside another repo's working tree, `ls-files --full-name` names are
  // relative to the true top level while `diff`/`checkout -C <main>` read them
  // relative to <main> — so they would address the wrong file. Confirm <main>
  // is the real top level before trusting it.
  try {
    const top = execFileSync("git", ["-C", main, "rev-parse", "--show-toplevel"], {
      encoding: "utf8", windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"], timeout: 10000,
    }).trim();
    if (!top || fs.realpathSync(top) !== fs.realpathSync(main)) return null;
  } catch {
    return null;
  }
  return main;
}

// Snapshot `git -C dir status --porcelain -z`. Returns null on failure.
export function gitStatusZ(dir, timeoutMs = 10000) {
  try {
    return execFileSync("git", ["-C", dir, "status", "--porcelain", "-z"], {
      encoding: "utf8", windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"], timeout: timeoutMs,
      maxBuffer: 10 * 1024 * 1024,
    });
  } catch {
    return null;
  }
}

// Parse `git status --porcelain -z` output into a Map<path, status>.
// A record is `XY path\0`; renames/copies are `XY source\0dest\0`. Both
// source and destination are recorded.
export function parseStatusZ(text) {
  const m = new Map();
  if (!text) return m;
  let i = 0;
  const n = text.length;
  while (i < n) {
    const status = text.slice(i, i + 2);
    i += 2;
    if (text[i] === " ") i++;
    const j = text.indexOf("\0", i);
    const p = j === -1 ? text.slice(i) : text.slice(i, j);
    i = j === -1 ? n : j + 1;
    if (p) m.set(p, status);
    // For a rename/copy, also record the destination path.
    if ((status[0] === "R" || status[0] === "C") && i < n) {
      const k = text.indexOf("\0", i);
      const dest = k === -1 ? text.slice(i) : text.slice(i, k);
      i = k === -1 ? n : k + 1;
      if (dest) m.set(dest, status);
    }
  }
  return m;
}

// Is abs under the main checkout directory (compared by real path on both sides)?
export function underMain(abs, main) {
  const rp = realPath(abs);
  const rm = realPath(main);
  return rp === rm || rp.startsWith(rm + path.sep);
}

// Resolve abs to a repo-relative name (forward slashes) via
// `git --literal-pathspecs -C main ls-files --full-name -z -- <rel>`.
// Returns null when not exactly one tracked entry (covers directories,
// untracked files, the repo root, and unreadable repos).
export function trackedName(main, abs) {
  try {
    const rel = path.relative(main, abs);
    const out = gitLiteral(main, ["ls-files", "--full-name", "-z", "--", rel], 10000);
    if (out === null) return null;
    const entries = out.toString("utf8").split("\0").filter(Boolean);
    if (entries.length !== 1) return null;
    const name = entries[0];
    if (name === "") return null; // repo root
    return name;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------- git diff + restore

// Run a git command in <main> with --literal-pathspecs. Returns raw Bytes
// (Buffer) — never a decoded string, so invalid UTF-8 survives byte-exact.
// Never throws. Returns null on failure.
export function gitLiteral(main, argv, timeoutMs = 10000, maxBuffer = 64 * 1024 * 1024) {
  try {
    return execFileSync("git", ["--literal-pathspecs", "-C", main, ...argv], {
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"], timeout: timeoutMs,
      maxBuffer,
    });
  } catch {
    return null;
  }
}

// Append `git --literal-pathspecs -C main diff --binary -- <name>` to
// patchFile as raw bytes. Returns true only when git exited 0 and its bytes
// were appended. An empty diff also counts as true. Never throws.
export function appendDiff(main, name, patchFile) {
  const diffBuf = gitLiteral(main, ["diff", "--binary", "--", name], 10000, 64 * 1024 * 1024);
  if (diffBuf === null) return false;
  try {
    fs.mkdirSync(path.dirname(patchFile), { recursive: true });
    fs.appendFileSync(patchFile, diffBuf);
  } catch {
    return false;
  }
  return true;
}

// Restore the tracked file <name> in main with
// `git --literal-pathspecs -C main checkout -- <name>`. Returns true on
// success, false on failure (never throws). Only safe to call on a single
// tracked regular file.
export function restorePath(main, name) {
  try {
    execFileSync("git", ["--literal-pathspecs", "-C", main, "checkout", "--", name], {
      encoding: "utf8", windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"], timeout: 10000,
    });
    return true;
  } catch {
    return false;
  }
}

// Read the index blob for <name> as raw bytes (Buffer). Returns null on failure.
// Callers must round-trip-check before treating it as text.
export function indexBlob(main, name) {
  const out = gitLiteral(main, ["show", ":0:" + name], 10000, 64 * 1024 * 1024);
  return out === null ? null : out;
}

// ---------------------------------------------------------------- replay guard

// Replay this run's completed write events for one path over the index blob.
// Returns the resulting content string, or null when the replay fails.
//   - write sets content to input.content
//   - edit replaces oldString with newString (first occurrence, or every
//     occurrence when input.replaceAll). Fails if oldString is not found.
//   - patch / multiedit: not replayable -> fail.
export function replayWrites(indexContent, events) {
  if (indexContent === null) return null;
  let content = indexContent;
  for (const ev of events) {
    if (!ev.completed) continue;
    const input = ev.input || {};
    if (ev.tool === "write") {
      content = input.content != null ? String(input.content) : content;
    } else if (ev.tool === "edit") {
      const oldS = input.oldString != null ? String(input.oldString) : "";
      const newS = input.newString != null ? String(input.newString) : "";
      if (!oldS) {
        // nothing to replace: treat as a set to newString
        content = newS;
        continue;
      }
      if (!content.includes(oldS)) return null; // oldString not found: replay fails
      if (input.replaceAll) {
        content = content.split(oldS).join(newS);
      } else {
        content = content.replace(oldS, newS);
      }
    } else {
      // patch / multiedit: cannot replay exactly -> fail
      return null;
    }
  }
  return content;
}

// ---------------------------------------------------------------- full check

// Run the escape check over one batch of event lines and fold the result into
// an accumulating state. `state` is { paths, restored, left, suspected, notes,
// eventsByPath } and is mutated and returned. `eventsByPath` maps abs path to
// the accumulated list of this run's write events across attempts.
// `beforeStatus` is the pre-run porcelain map of main (null when C does not
// apply).
export function foldEscapes(state, { lines, roots, dir, main, beforeStatus, out }) {
  const scan = scanEvents(lines.join("\n"), roots, dir);
  const patchFile = out + ".escaped.patch";
  for (const [abs, events] of scan.escaped) {
    // accumulate this run's write events for the path (across attempts)
    let prior = state.eventsByPath.get(abs);
    if (!prior) {
      prior = [];
      state.eventsByPath.set(abs, prior);
    }
    prior.push(...events);

    const alreadyKnown = state.paths.includes(abs);
    if (!alreadyKnown) state.paths.push(abs);

    // An already-restored path that gets a new completed write in a later
    // attempt must be re-checked through all guards with the full event list.
    const reProcess = alreadyKnown && state.restored.includes(abs) && events.some((ev) => ev.completed);
    if (alreadyKnown && !reProcess) continue;
    if (reProcess) {
      const idx = state.restored.indexOf(abs);
      if (idx !== -1) state.restored.splice(idx, 1);
    }
    const leftNote = reProcess ? `${abs}: written again in a later attempt` : null;

    if (!main || !underMain(abs, main)) continue; // outside any git tree: record only

    const name = trackedName(main, abs);
    const completed = hasCompletedWrite(events);

    // Restore only a single tracked regular file.
    const isRegularFile = name !== null && (() => {
      try { return fs.lstatSync(abs).isFile(); } catch { return false; }
    })();

    if (!isRegularFile) {
      state.left.push(abs);
      state.notes.push(leftNote || `${abs}: not a single tracked regular file`);
      continue;
    }

    // A path with no completed write event is never restored.
    if (!completed) {
      state.left.push(abs);
      state.notes.push(leftNote || `${abs}: attempted (no completed write)`);
      continue;
    }

    // Save the diff before any restore.
    const diffSaved = name !== null ? appendDiff(main, name, patchFile) : false;
    if (!diffSaved) {
      state.left.push(abs);
      state.notes.push(leftNote || `${abs}: diff not saved`);
      continue;
    }

    // Was it clean in a non-null pre-run snapshot? A null snapshot means we
    // cannot know whether the path was clean, so it is never restored.
    const rel = name; // forward-slash repo-relative name
    if (beforeStatus === null || beforeStatus === undefined) {
      state.left.push(abs);
      state.notes.push(leftNote || `${abs}: no snapshot`);
      continue;
    }
    const wasClean = !beforeStatus.has(rel);
    if (!wasClean) {
      state.left.push(abs);
      state.notes.push(leftNote || `${abs}: dirty before run`);
      continue;
    }

    // Replay guard: replay this run's completed writes over the index blob and
    // compare byte-for-byte with the current file content. Runs on strings only
    // when both the blob and the current file round-trip as UTF-8; otherwise
    // the path goes to `left` with `not valid UTF-8`.
    const indexContent = indexBlob(main, name); // Buffer | null
    let currentBuf = null;
    try { currentBuf = fs.readFileSync(abs); } catch {}
    const indexOk = indexContent !== null && Buffer.from(indexContent.toString("utf8")).equals(indexContent);
    const currentOk = currentBuf !== null && Buffer.from(currentBuf.toString("utf8")).equals(currentBuf);
    if (!indexOk || !currentOk) {
      state.left.push(abs);
      state.notes.push(leftNote || `${abs}: not valid UTF-8`);
      continue;
    }
    const replayed = replayWrites(indexContent.toString("utf8"), prior);
    const replayOk = replayed !== null && Buffer.from(replayed, "utf8").equals(currentBuf);

    if (replayOk) {
      if (restorePath(main, name)) state.restored.push(abs);
      else {
        state.left.push(abs);
        state.notes.push(leftNote || `${abs}: restore failed`);
      }
    } else {
      state.left.push(abs);
      state.notes.push(leftNote || `${abs}: replay mismatch`);
    }
  }
  // suspected: main-checkout paths that turned dirty with no tool event
  if (main && beforeStatus) {
    const after = parseStatusZ(gitStatusZ(main));
    const exact = new Set(state.paths);
    const seenSuspected = new Set(state.suspected);
    for (const [p] of after) {
      if (beforeStatus.has(p)) continue; // already dirty pre-run
      if (exact.has(p)) continue; // already an exact escape
      if (seenSuspected.has(p)) continue; // already reported
      seenSuspected.add(p);
      state.suspected.push(p);
    }
  }
  return state;
}

// ---------------------------------------------------------------- finalize escapes

// Finalize the escape check into a receipt fragment.
// Returns { escaped } (only when something escaped or was suspected) plus a
// note string. The `escaped-worktree:` errors[] entry is added by oc-worker
// only when at least one escaped path has a completed write.
export function finalizeEscapes(state) {
  const found =
    state.paths.length || state.restored.length || state.left.length || state.suspected.length;
  if (!found) return { escaped: null, note: "" };
  const escaped = {
    paths: state.paths,
    ...(state.restored.length ? { restored: state.restored } : {}),
    ...(state.left.length ? { left: state.left } : {}),
    ...(state.suspected.length ? { suspected: state.suspected } : {}),
  };
  return { escaped, note: "" };
}

// ---------------------------------------------------------------- prompt footer

// The worktree paragraph appended to the agent prompt. `<main>` is included
// only when a linked worktree / main checkout was found.
export function footer(dir, out, main) {
  const reportDir = path.dirname(path.resolve(out));
  const mainPart = main
    ? ` A path outside it, such as ${main}/orchestrator/…, is another checkout's copy: read it if you need to, but make the edit to the same relative path under ${dir}.`
    : "";
  return (
    `\nYour worktree is ${dir}. Create and edit files only under it (plus the report folder ${reportDir}).` +
    mainPart +
    "\n"
  );
}

// ---------------------------------------------------------------- OpenCode edit fence

// The per-run OpenCode edit-fence config (opt-in via ORCH_EDIT_FENCE=1).
export function editFenceConfig(dir, out) {
  const d = path.resolve(dir);
  const o = path.dirname(path.resolve(out));
  const t = os.tmpdir();
  return JSON.stringify({
    permission: {
      edit: {
        "*": "deny",
        [`${d}/**`]: "allow",
        [`${o}/**`]: "allow",
        [`${t}/**`]: "allow",
      },
    },
  });
}

// Merge the fence config into an existing OPENCODE_CONFIG_CONTENT value.
// Returns the merged config text (the fence's edit permissions take effect;
// a pre-existing top-level "permission" key is merged at the edit level).
export function mergeEditFence(existing, dir, out) {
  let base = {};
  if (existing) {
    try {
      const parsed = JSON.parse(existing);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) base = parsed;
    } catch {
      base = {};
    }
  }
  const fence = JSON.parse(editFenceConfig(dir, out));
  if (!base.permission || typeof base.permission !== "object" || Array.isArray(base.permission)) {
    base.permission = {};
  }
  if (!base.permission.edit || typeof base.permission.edit !== "object" || Array.isArray(base.permission.edit)) {
    base.permission.edit = {};
  }
  const fenceEdit = fence.permission.edit;
  for (const [k, v] of Object.entries(fenceEdit)) {
    base.permission.edit[k] = v;
  }
  return JSON.stringify(base);
}
