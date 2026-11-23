#!/usr/bin/env node
/**
 * Orchestrator stream handoff hook (Claude Code SessionStart + UserPromptSubmit).
 * UserPromptSubmit: on `/frood-next [stream]` or `/frood-gauntlet <plan> <module>`, names the session tab after the work.
 * Managed in the Frood repo's orchestrator/ directory ({{ORCH_REPO}}/hooks) — edit there, then install.
 *
 * After `/clear` (or a fresh start), tell the new session which orchestrator streams are still waiting and how many
 * desk events nobody has handled yet, so the owner only has to type `/frood-next <stream>` or `/frood-desk`.
 * Lease lines: on every prompt and on every session start (resume and compact included) the hook reads the stream pointers
 * and says "held by OpenCode, stand down" for a stream OpenCode took over, or "handed back, run /frood-next" once it returns it.
 * Only active pointers with a lease produce a line, so streams without lease fields keep the output empty.
 * Never breaks session start: any failure exits 0 with no output.
 */
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

// The Frood repo's orchestrator/ directory this hook ships with. The installer bakes the real path in ({{ORCH_REPO}});
// running the hook straight from a checkout sets ORCH_REPO, and an un-rendered token falls back to
// the pointer reader below instead of importing anything.
const REPO = process.env.ORCH_REPO || "{{ORCH_REPO}}";
const STALE_MS = 72 * 3600_000;
const NAME_RE = /^[a-z0-9][a-z0-9-]{0,39}$/;

const root = () => process.env.ORCH_HOME || os.homedir();
const streamsDir = () => path.join(root(), ".config", "orchestrator", "streams");
const cut = (s, n) => (s.length > n ? s.slice(0, n) : s);

// The module owns the data model; importing it has no side effects and it is the only path that runs migrate().
async function loadHandoff() {
  try {
    return await import(pathToFileURL(path.join(REPO, "bin", "handoff.mjs")).href);
  } catch {
    return null;
  }
}

// Fallback when the module cannot be imported: the pointers alone, read-only, no migration and no events.
function readPointers() {
  const out = [];
  let files = [];
  try {
    files = fs.readdirSync(streamsDir());
  } catch {
    return out;
  }
  for (const file of files) {
    const m = /^(.*)\.json$/.exec(file);
    if (!m || !NAME_RE.test(m[1])) continue;
    try {
      const s = JSON.parse(fs.readFileSync(path.join(streamsDir(), file), "utf8"));
      if (!s || s.status !== "active" || s.consumed_at) continue;
      if (!(Date.now() - Date.parse(s.written_at) <= STALE_MS)) continue;
      out.push({ name: m[1], next: String(s.next || ""), written_at: s.written_at, held_by: s.held_by ?? null, state: "pending" });
    } catch {}
  }
  return out;
}

// Lease lines: read the pointer files only (no handoff.mjs, no migrate, no events). Newest first, at most 6.
function leaseLines() {
  const found = [];
  let files = [];
  try {
    files = fs.readdirSync(streamsDir());
  } catch {
    return [];
  }
  for (const file of files) {
    const m = /^(.*)\.json$/.exec(file);
    if (!m || !NAME_RE.test(m[1])) continue;
    try {
      const s = JSON.parse(fs.readFileSync(path.join(streamsDir(), file), "utf8"));
      if (!s || s.status !== "active") continue;
      const when = Date.parse(s.held_at || s.written_at);
      const at = Number.isFinite(when) ? when : 0;
      if (s.held_by === "oc") {
        found.push({ at, line: `orchestrator stream ${m[1]} is held by OpenCode (session ${s.held_session || "-"}) since ${s.held_at} — do not act on it here (no dispatch, merge or handoff write); it comes back with a handback.` });
      } else if (!s.held_by && s.handback_to === "cc") {
        found.push({ at, line: `orchestrator stream ${m[1]} was handed back to Claude Code — run /frood-next ${m[1]} (and /frood-desk if you run the desk).` });
      }
    } catch {}
  }
  return found.sort((a, b) => b.at - a.at).slice(0, 6).map((x) => x.line);
}

function context(streams, eventCount, eventStreams) {
  const lines = [];
  const pending = streams
    .filter((s) => s.state === "pending" && s.held_by !== "oc") // an oc-held stream is covered by its lease line
    .sort((a, b) => Date.parse(b.written_at) - Date.parse(a.written_at))
    .slice(0, 6);
  for (const s of pending) lines.push(`orchestrator stream ${s.name}: next = ${cut(String(s.next || ""), 120)}`);
  if (eventCount > 0) lines.push(`${eventCount} unhandled desk events across ${eventStreams} streams — run /frood-desk`);
  if (lines.length) {
    lines.push("When the owner types /frood-next (or asks to continue), run /frood-next <stream> for the named stream — do not start other work first.");
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------- session title (UserPromptSubmit)
// `/frood-next` and `/frood-gauntlet` would otherwise leave the tab named after the bare command. Name it after the work instead:
// "<repo>: <module> — <what>" from the stream's `next` line, or from /frood-gauntlet's own arguments.
const TITLE_MAX = 60;
const base = (p) => String(p || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "";
const planSlug = (p) => base(p).replace(/\.md$/i, "").replace(/^plan-/, "");

function titleFromGauntlet(repo, args) {
  const m = /^\s*(\S+)\s+(\S+)(?:\s+[—–-]+\s+([^;]+))?/.exec(String(args || ""));
  if (!m) return "";
  const what = (m[3] || "").trim() || planSlug(m[1]);
  return cut(`${repo ? `${repo}: ` : ""}${m[2]} — ${what}`, TITLE_MAX);
}

function titleFromStream(s) {
  const repo = base(s.repo);
  const next = String(s.next || "").trim();
  const g = /^\/frood-gauntlet\s+(.*)$/.exec(next);
  const fromG = g ? titleFromGauntlet(repo, g[1]) : "";
  const streamPrefix = `[${s.name}] `;
  let title;
  if (fromG) {
    title = `${streamPrefix}${fromG}`;
  } else if (next) {
    title = `${streamPrefix}${repo ? `${repo}: ` : ""}${next.replace(/^\/\S+\s*/, "")}`;
  } else {
    title = `${streamPrefix}${repo ? `${repo}: ` : ""}${s.name}`;
  }
  return cut(title, TITLE_MAX);
}

async function sessionTitle(input) {
  const prompt = String(input.prompt || "").trim();
  const g = /^\/frood-gauntlet\s+(.+)$/s.exec(prompt);
  if (g) return titleFromGauntlet(base(input.cwd), g[1].split("\n")[0]);
  const n = /^\/frood-next(?:\s+(\S+))?\s*$/.exec(prompt.split("\n")[0]);
  if (!n) return "";
  const mod = await loadHandoff();
  let streams = [];
  if (mod) {
    try {
      mod.migrate();
    } catch {}
    try {
      streams = mod.listStreams();
    } catch {}
  } else {
    streams = readPointers();
  }
  streams = streams.filter((s) => s.state !== "corrupt");
  const pick = n[1] && NAME_RE.test(n[1]) ? streams.find((s) => s.name === n[1]) : undefined;
  const pending = streams.filter((s) => s.state === "pending");
  const s = pick ?? (!n[1] && pending.length === 1 ? pending[0] : undefined);
  return s ? titleFromStream(s) : "";
}

async function main(raw) {
  const input = JSON.parse(raw || "{}");
  if (input.hook_event_name === "UserPromptSubmit") {
    const title = await sessionTitle(input);
    const lines = leaseLines();
    if (!title && !lines.length) return;
    const out = { hookEventName: "UserPromptSubmit" };
    if (lines.length) out.additionalContext = lines.join("\n");
    if (title) out.sessionTitle = title;
    return JSON.stringify({ hookSpecificOutput: out });
  }
  const source = input.source || "";
  const lease = leaseLines();
  const emit = (text) => JSON.stringify({ hookSpecificOutput: { hookEventName: "SessionStart", additionalContext: text } });
  // same conversation continues: no handoff context, but a lost or returned stream is still worth saying
  if (source === "resume" || source === "compact") return lease.length ? emit(lease.join("\n")) : undefined;

  const mod = await loadHandoff();
  let text = "";
  if (mod) {
    try {
      mod.migrate();
    } catch {}
    let streams = [];
    try {
      streams = mod.listStreams();
    } catch {}
    let eventCount = 0;
    let eventStreams = 0;
    for (const s of streams) {
      if (s.state === "corrupt" || s.status !== "active") continue;
      let n = 0;
      try {
        n = mod.unhandled(s.name).length;
      } catch {}
      if (n > 0) {
        eventCount += n;
        eventStreams++;
      }
    }
    text = context(streams, eventCount, eventStreams);
  } else {
    text = context(readPointers(), 0, 0);
  }
  text = [text, ...lease].filter(Boolean).join("\n");
  if (!text) return;
  return emit(text);
}

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (d) => (raw += d));
process.stdin.on("error", () => process.exit(0));
process.stdin.on("end", () => {
  main(raw).then(
    (out) => {
      if (!out) process.exit(0);
      // exit from the write callback: on a pipe the write is async and process.exit would truncate it
      process.stdout.write(out, () => process.exit(0));
    },
    () => process.exit(0),
  );
});
// A hook that hangs blocks session start; give the import and the reads a bounded amount of time.
setTimeout(() => process.exit(0), 10_000).unref();
