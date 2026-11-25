#!/usr/bin/env node
/*
 * frood-learn — /frood learn
 *
 * Process-aware learning review CLI for the Frood intelligence layer.
 * Reviews HOW work gets done by analyzing REAL session artifacts:
 * - desk daemon logs (verdict-failed, worker-timeout, worker-error, etc.)
 * - worker/critic receipts (token usage, timing, errors)
 * - stream handoffs (waiting fields, next pointers, staleness)
 * - peer-mail sync (session ID drift, ack timeouts)
 * - critic rounds efficiency
 * - board gate failures
 *
 *   /frood learn <stream> --phase 1          # Phase 1: communication patterns
 *   /frood learn <stream> --phase 2          # Phase 2: error handling & recovery
 *   /frood learn <stream> --phase 3          # Phase 3: coordination & sync
 *   /frood learn <stream> --phase 3 --lens process-coordination
 *   /frood learn --help
 *
 * Writes a structured findings report (JSON) and prints a human summary to stdout.
 * MCP skill invocation (`frood_process_review`) is attempted when available and
 * --no-mcp is not set; otherwise built-in prompts are used (fallback).
 *
 * Meta-review exclusion (REQUIRED): learning hooks are never in scope:
 *   learning-engine.py, knowledge-learn.py, knowledge-learn-worker.py
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { spawnSync } from "child_process";
import readline from "readline";

// ---------------------------------------------------------------------------
// Phase / lens definitions — PROCESS-ORIENTED
// ---------------------------------------------------------------------------

const PHASES = {
  1: {
    name: "Phase 1 — communication patterns",
    lenses: ["peer-mail", "desk-operations", "subagent-coordination", "handoff-quality"],
    defaultLens: "peer-mail",
  },
  2: {
    name: "Phase 2 — error handling & recovery",
    lenses: ["error-propagation", "retry-recovery", "dead-letter-handling", "circuit-breakers"],
    defaultLens: "error-propagation",
  },
  3: {
    name: "Phase 3 — coordination & sync",
    lenses: ["process-coordination", "cross-harness-sync", "handoff-quality", "process-metrics"],
    defaultLens: "process-coordination",
  },
  4: {
    name: "Phase 4 — work logic & code quality",
    lenses: ["async-patterns", "file-ops", "sandbox-compliance", "deployment-drift", "atlas-adherence"],
    defaultLens: "async-patterns",
  },
  5: {
    name: "Phase 5 — OpenCode session analysis",
    lenses: ["session-summary", "error-patterns", "tool-efficiency", "frood-code-changes", "local-code-changes", "session-length"],
    defaultLens: "session-summary",
  },
};

// Learning hooks excluded from meta-review (never in scope for any phase/lens)
const META_REVIEW_EXCLUSION = [
  "learning-engine.py",
  "knowledge-learn.py",
  "knowledge-learn-worker.py",
];

// ---------------------------------------------------------------------------
// Children (stream -> child session) collection
// ---------------------------------------------------------------------------

// OpenCode session ids carried on stream events look like `ses_...`.
const SESSION_RE = /^ses_[A-Za-z0-9_-]+$/;
// Valid child roles, mirrored from handoff.mjs so the two stay in sync.
const CHILD_ROLES = ["worker", "critic", "scout", "senior", "nested", "orchestrator"];
// Valid harnesses a child event may record.
const CHILD_HARNESSES = ["opencode", "claude-code"];

// Where child transcripts are copied for retention (outside every repo, so
// transcripts that can hold secrets never reach .opencode/reports and a commit).
const LEARNINGS_ROOT = path.join(
  process.env.HOME || process.env.USERPROFILE,
  ".config",
  "orchestrator",
  "learnings",
);

// ---------------------------------------------------------------------------
// Argument parsing
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const args = {
    stream: null,
    phase: null,
    lens: null,
    propose: false,
    noMcp: false,
    report: null,
    apply: false,
    autoDetect: false,
    sessionId: null,
    noChildren: false,
    quick: false, // -a / --auto flag
  };

  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    const v = () => argv[++i];
    if (k === "--phase") args.phase = parseInt(v(), 10);
    else if (k === "--lens") args.lens = v();
    else if (k === "--propose") args.propose = true;
    else if (k === "--no-mcp") args.noMcp = true;
    else if (k === "--report") args.report = v();
    else if (k === "--apply" || k === "-a") { args.apply = true; args.noMcp = true; args.quick = true; }
    else if (k === "--auto" || k === "-A") { args.apply = true; args.noMcp = true; args.quick = true; }
    else if (k === "--auto-detect") args.autoDetect = true;
    else if (k === "--session") args.sessionId = v();
    else if (k === "--no-children") args.noChildren = true;
    else if (k === "--help" || k === "-h") { printUsage(); process.exit(0); }
    else if (!args.stream && !k.startsWith("--")) args.stream = k;
    else if (k.startsWith("--")) { console.error(`frood-learn: unknown flag ${k}`); process.exit(2); }
    else if (!args.stream) args.stream = k;
  }
  return args;
}

function autoDetectStream(args) {
  // 1. Check explicit --session flag
  if (args.sessionId) {
    const streamFromSession = findStreamBySession(args.sessionId);
    if (streamFromSession) return streamFromSession;
  }

  // 2. Check OPENCODE_SESSION_ID env var
  const sessionId = process.env.OPENCODE_SESSION_ID;
  if (sessionId) {
    const streamFromSession = findStreamBySession(sessionId);
    if (streamFromSession) return streamFromSession;
  }

  // 3. Check current working directory for git repo and recent streams
  const cwd = process.cwd();
  const repoName = path.basename(cwd);
  const streamFromRepo = findStreamByRepo(cwd, repoName);
  if (streamFromRepo) return streamFromRepo;

  // 4. Check for recent active streams
  const recentStream = findRecentActiveStream();
  if (recentStream) return recentStream;

  return null;
}

function findStreamBySession(sessionId) {
  const streamsDir = path.join(ORCH_ROOT, "streams");
  if (!fs.existsSync(streamsDir)) return null;

  const files = fs.readdirSync(streamsDir).filter(f => f.endsWith(".json"));
  for (const file of files) {
    try {
      const streamPath = path.join(streamsDir, file);
      const stream = JSON.parse(fs.readFileSync(streamPath, "utf8"));
      if (stream.held_session === sessionId || stream.claim === sessionId) {
        return stream.name;
      }
    } catch {}
  }
  return null;
}

function findStreamByRepo(cwd, repoName) {
  const streamsDir = path.join(ORCH_ROOT, "streams");
  if (!fs.existsSync(streamsDir)) return null;

  const files = fs.readdirSync(streamsDir).filter(f => f.endsWith(".json"));
  const matching = [];
  for (const file of files) {
    try {
      const streamPath = path.join(streamsDir, file);
      const stream = JSON.parse(fs.readFileSync(streamPath, "utf8"));
      // Match by repo path or repo name
      if (stream.repo === cwd || stream.repo?.includes(repoName)) {
        matching.push(stream);
      }
    } catch {}
  }

  if (matching.length === 1) return matching[0].name;
  if (matching.length > 1) {
    // Return most recently active
    matching.sort((a, b) => new Date(b.written_at || 0) - new Date(a.written_at || 0));
    return matching[0].name;
  }
  return null;
}

function findRecentActiveStream() {
  const streamsDir = path.join(ORCH_ROOT, "streams");
  if (!fs.existsSync(streamsDir)) return null;

  const files = fs.readdirSync(streamsDir).filter(f => f.endsWith(".json"));
  const active = [];
  for (const file of files) {
    try {
      const streamPath = path.join(streamsDir, file);
      const stream = JSON.parse(fs.readFileSync(streamPath, "utf8"));
      if (stream.status === "active" || stream.held_session) {
        active.push(stream);
      }
    } catch {}
  }

  if (active.length > 0) {
    active.sort((a, b) => new Date(b.written_at || 0) - new Date(a.written_at || 0));
    return active[0].name;
  }
  return null;
}

function listAvailableStreams() {
  const streamsDir = path.join(ORCH_ROOT, "streams");
  if (!fs.existsSync(streamsDir)) {
    console.error("  (no streams found)");
    return;
  }

  const files = fs.readdirSync(streamsDir).filter(f => f.endsWith(".json"));
  for (const file of files) {
    try {
      const streamPath = path.join(streamsDir, file);
      const stream = JSON.parse(fs.readFileSync(streamPath, "utf8"));
      const status = stream.status || "unknown";
      const repo = stream.repo ? path.basename(stream.repo) : "unknown";
      const held = stream.held_session ? ` (held by ${stream.held_session.slice(0, 12)}...)` : "";
      console.error(`  ${stream.name} — ${status} [${repo}]${held}`);
    } catch {}
  }
}

// ---------------------------------------------------------------------------
// OpenCode session analysis (reads from opencode.db)
// ---------------------------------------------------------------------------

const OPENCODE_DB = path.join(process.env.HOME || process.env.USERPROFILE, ".local", "share", "opencode", "opencode.db");

function readOpenCodeSession(sessionId) {
  if (!fs.existsSync(OPENCODE_DB)) {
    console.error(`OpenCode database not found at ${OPENCODE_DB}`);
    return null;
  }

  // Get session info - use JSON output mode
  const sessionQuery = `
    SELECT json_group_array(json_object(
      'id', id,
      'title', title,
      'time_created', time_created,
      'time_updated', time_updated
    )) FROM session_v2 WHERE id = '${sessionId.replace(/'/g, "''")}'
  `;
  const sessionResult = spawnSync("sqlite3", [OPENCODE_DB, sessionQuery], { encoding: "utf8" });
  if (sessionResult.status !== 0 || !sessionResult.stdout.trim() || sessionResult.stdout.trim() === "[]") {
    return null;
  }
  const sessions = JSON.parse(sessionResult.stdout.trim());
  if (!sessions.length) return null;
  const session = sessions[0];

  // Get messages - use JSON output to avoid pipe separator issues
  const messagesQuery = `
    SELECT json_group_array(json_object(
      'type', type,
      'data', data,
      'time_created', time_created
    )) FROM session_message WHERE session_id = '${sessionId.replace(/'/g, "''")}' ORDER BY seq
  `;
  const messagesResult = spawnSync("sqlite3", [OPENCODE_DB, messagesQuery], { encoding: "utf8" });
  if (messagesResult.status !== 0 || !messagesResult.stdout.trim() || messagesResult.stdout.trim() === "[]") {
    session.messages = [];
    return session;
  }
  const messagesData = JSON.parse(messagesResult.stdout.trim());
  session.messages = messagesData.map(m => ({
    type: m.type,
    data: JSON.parse(m.data),
    time_created: m.time_created,
  }));

  return session;
}

// Shared session analysis used by both the OpenCode reader (opencode.db) and the
// Claude Code reader (JSONL transcripts). Produces the phase-5 lens findings
// (session-summary, error-patterns, tool-efficiency, frood-code-changes,
// local-code-changes, session-length) from a normalized message list.
function analyzeSessionData(messages, sessionId, title, startedAt, updatedAt, model) {
  const findings = [];

  if (!messages) return findings;

  // Analyze session for patterns
  let shellCommands = 0;
  let backgroundShellCommands = 0;
  let fileEdits = 0;
  let errors = 0;
  let toolCalls = 0;
  let agentTurns = 0;
  const toolsUsed = new Set();
  const filesModified = new Set();
  const errorPatterns = [];
  const userPrompts = [];
  const assistantErrors = [];

  for (const msg of messages) {
    if (msg.type === "assistant") {
      agentTurns++;
      // Check for tool calls in assistant messages
      if (msg.data.snapshot && msg.data.snapshot.files) {
        for (const f of msg.data.snapshot.files) {
          filesModified.add(f);
        }
      }
      // Check for tool calls via finish type
      if (msg.data.finish === "tool-calls" || msg.data.rawFinish === "tool_calls") {
        toolCalls++;
      }
      // Check for errors in assistant output (text content)
      if (msg.data.content && Array.isArray(msg.data.content)) {
        for (const c of msg.data.content) {
          if (c.text && (c.text.includes("error") || c.text.includes("Error") || c.text.includes("FAILED") || c.text.includes("failed"))) {
            errors++;
            assistantErrors.push(c.text.slice(0, 200));
          }
        }
      }
      // Check snapshot end state for errors
      if (msg.data.snapshot && msg.data.snapshot.end) {
        // Could check git diff for error patterns
      }
    }
    else if (msg.type === "shell") {
      shellCommands++;
      const text = msg.data.text || "";
      if (text.includes("error") || text.includes("Error") || text.includes("FAILED") || text.includes("failed")) {
        errors++;
        errorPatterns.push(text.slice(0, 200));
      }
      // Extract tools from shell commands
      if (text.includes("npm") || text.includes("node") || text.includes("python") || text.includes("bash") || text.includes("deploy")) {
        toolsUsed.add("shell");
      }
    }
    else if (msg.type === "background-result") {
      // Background shell commands (like deploy)
      backgroundShellCommands++;
      const text = msg.data.text || "";
      if (text.includes("error") || text.includes("Error") || text.includes("FAILED") || text.includes("failed") || text.includes("502") || text.includes("503") || text.includes("500")) {
        errors++;
        errorPatterns.push(text.slice(0, 200));
      }
      if (text.includes("deploy") || text.includes("DEPLOY")) {
        toolsUsed.add("deploy");
      }
      if (text.includes("prisma") || text.includes("migration") || text.includes("schema")) {
        toolsUsed.add("prisma");
      }
    }
    else if (msg.type === "user") {
      userPrompts.push(msg.data.text || "");
    }
    else if (msg.type === "synthetic") {
      // Synthetic messages contain tool results (like shell commands)
      backgroundShellCommands++;
      const text = msg.data.text || "";
      const desc = msg.data.description || "";

      // Check for errors in the full output
      if (text.includes("error") || text.includes("Error") || text.includes("FAILED") || text.includes("failed") || text.includes("502") || text.includes("503") || text.includes("500")) {
        errors++;
        errorPatterns.push(text.slice(0, 200));
      }
      if (desc.includes("deploy") || desc.includes("DEPLOY") || text.includes("deploy") || text.includes("DEPLOY")) {
        toolsUsed.add("deploy");
      }
      if (desc.includes("prisma") || desc.includes("migration") || desc.includes("schema") || text.includes("prisma") || text.includes("migration") || text.includes("schema")) {
        toolsUsed.add("prisma");
      }
      if (desc.includes("shell") || desc.includes("bash") || desc.includes("node") || desc.includes("npm") || desc.includes("python")) {
        toolsUsed.add("shell");
      }
    }
  }

  const minutes = startedAt !== null && updatedAt !== null
    ? Math.round((updatedAt - startedAt) / 1000 / 60)
    : 0;

  // Finding: Session overview
  findings.push({
    area: "session-overview",
    focus: "session summary",
    lens: "session-summary",
    status: "analyzed",
    detail: `Session "${title || ""}" (${sessionId}): ${agentTurns} agent turns, ${shellCommands} shell commands, ${backgroundShellCommands} background commands, ${toolCalls} tool call rounds, ${filesModified.size} files modified, ${errors} errors detected, ${userPrompts.length} user prompts.${model ? ` Model: ${model}.` : ""}`,
    recommendation: "Review session timeline for patterns. High error count may indicate environment issues.",
    evidence: [sessionId],
    source: "opencode-session",
    category: "local-environment",
  });

  // Finding: Error patterns
  if (errors > 0) {
    const allErrors = [...errorPatterns, ...assistantErrors];
    findings.push({
      area: "error-handling",
      focus: "session errors",
      lens: "error-patterns",
      status: "analyzed",
      detail: `Found ${errors} errors in session (shell: ${shellCommands}, background: ${backgroundShellCommands}, assistant: ${assistantErrors.length}). Patterns: ${[...new Set(allErrors.slice(0, 5))].join("; ")}.`,
      recommendation: "Investigate recurring errors. Add error handling or fix environment issues. Consider automated health checks.",
      evidence: [sessionId],
      source: "opencode-session",
      category: "local-environment",
    });
  }

  // Finding: Tool usage
  if (toolsUsed.size > 0) {
    findings.push({
      area: "tool-usage",
      focus: "tools used in session",
      lens: "tool-efficiency",
      status: "analyzed",
      detail: `Tools used: ${[...toolsUsed].join(", ")}. ${shellCommands} shell commands, ${backgroundShellCommands} background commands executed.`,
      recommendation: "Consider if repetitive shell/deploy commands could be automated via scripts or CI/CD.",
      evidence: [sessionId],
      source: "opencode-session",
      category: "local-environment",
    });
  }

  // Finding: Files modified
  if (filesModified.size > 0) {
    const froodFiles = [...filesModified].filter(f => f.includes("frood") || f.includes("dashboard") || f.includes("core") || f.includes("bin/") || f.includes(".claude"));
    const localFiles = [...filesModified].filter(f => !f.includes("frood") && !f.includes("dashboard") && !f.includes("core") && !f.includes("bin/") && !f.includes(".claude"));

    if (froodFiles.length > 0) {
      findings.push({
        area: "code-changes",
        focus: "Frood codebase modifications",
        lens: "frood-code-changes",
        status: "analyzed",
        detail: `Modified ${froodFiles.length} Frood-related files: ${froodFiles.slice(0, 5).join(", ")}${froodFiles.length > 5 ? "..." : ""}`,
        recommendation: "Review changes for adherence to Frood conventions (async I/O, sandbox, ATLAS). Consider PR if improvements.",
        evidence: froodFiles.slice(0, 10),
        source: "opencode-session",
        category: "frood-code",
      });
    }

    if (localFiles.length > 0) {
      findings.push({
        area: "code-changes",
        focus: "local/project files modified",
        lens: "local-code-changes",
        status: "analyzed",
        detail: `Modified ${localFiles.length} local/project files: ${localFiles.slice(0, 5).join(", ")}${localFiles.length > 5 ? "..." : ""}`,
        recommendation: "Review for environment-specific patterns (hardcoded paths, localhost, debug logging).",
        evidence: localFiles.slice(0, 10),
        source: "opencode-session",
        category: "local-environment",
      });
    }

    // Specific finding for schema-heavy changes
    const schemaFiles = [...filesModified].filter(f => f.includes("schema") || f.includes("migration") || f.includes("prisma"));
    if (schemaFiles.length > 2) {
      findings.push({
        area: "code-changes",
        focus: "schema/database changes",
        lens: "schema-changes",
        status: "analyzed",
        detail: `Modified ${schemaFiles.length} schema/migration files: ${schemaFiles.join(", ")}. Multiple iterations suggest trial-and-error or evolving requirements.`,
        recommendation: "Schema changes should be planned upfront. Consider using a design doc or mandate before modifying. Ensure migrations are tested.",
        evidence: schemaFiles,
        source: "opencode-session",
        category: "local-environment",
      });
    }
  }

  // Finding: Agent efficiency
  if (agentTurns > 10) {
    findings.push({
      area: "agent-efficiency",
      focus: "long session",
      lens: "session-length",
      status: "analyzed",
      detail: `Session had ${agentTurns} agent turns over ${minutes} minutes.`,
      recommendation: "Long sessions may indicate unclear objectives or iterative trial-and-error. Consider breaking into smaller tasks with clear mandates.",
      evidence: [sessionId],
      source: "opencode-session",
      category: "local-environment",
    });
  }

  // Finding: User prompt patterns
  if (userPrompts.length > 0) {
    const continuationPrompts = userPrompts.filter(p =>
      p.toLowerCase().includes("still") ||
      p.toLowerCase().includes("again") ||
      p.toLowerCase().includes("error") ||
      p.toLowerCase().includes("failed") ||
      p.toLowerCase().includes("didn't work")
    );
    if (continuationPrompts.length > 2) {
      findings.push({
        area: "agent-efficiency",
        focus: "iterative debugging",
        lens: "iteration-patterns",
        status: "analyzed",
        detail: `User sent ${continuationPrompts.length} continuation/debugging prompts (e.g., "still failing", "error", "didn't work"). Suggests agent struggled to resolve issue.`,
        recommendation: "When agent struggles, consider: clearer mandate, breaking task into smaller pieces, or human intervention. Add pre-flight checks to catch issues earlier.",
        evidence: [sessionId],
        source: "opencode-session",
        category: "local-environment",
      });
    }
  }

  return findings;
}

function analyzeOpenCodeSession(session) {
  const findings = [];

  if (!session || !session.messages) return findings;

  return analyzeSessionData(
    session.messages,
    session.id,
    session.title,
    session.time_created,
    session.time_updated,
    null,
  );
}

// ---------------------------------------------------------------------------
// Claude Code JSONL reader (new): reads a Claude Code transcript (a nested
// session .jsonl file or a subagent agent-*.jsonl) into the normalized shape
// analyzeSessionData expects. One reader per harness: opencode.db (above) and
// Claude Code JSONL (here).
// ---------------------------------------------------------------------------

function readClaudeCodeJSONL(filePath) {
  let raw;
  try {
    raw = fs.readFileSync(filePath, "utf8");
  } catch {
    return null;
  }
  const messages = [];
  let id = null;
  let title = null;
  let model = null;
  let startedAt = null;
  let updatedAt = null;
  let agentTurns = 0;
  // In-progress assistant message being assembled from stream_event blocks.
  let curAssistant = null; // { content: string[], files: string[], finish: string|null }

  const touch = (t) => {
    if (!t) return;
    if (!startedAt || t < startedAt) startedAt = t;
    if (!updatedAt || t > updatedAt) updatedAt = t;
  };

  const flushAssistant = () => {
    if (!curAssistant) return;
    agentTurns++;
    const content = curAssistant.content.length ? [{ text: curAssistant.content.join("") }] : [];
    messages.push({
      type: "assistant",
      data: {
        content,
        finish: curAssistant.finish || "stop",
        snapshot: curAssistant.files.length ? { files: curAssistant.files } : null,
      },
      time_created: curAssistant.at,
    });
    curAssistant = null;
  };

  for (const line of raw.split(/\r?\n/)) {
    if (!line.trim()) continue;
    let v;
    try { v = JSON.parse(line); } catch { continue; }
    if (!v || typeof v !== "object") continue;
    touch(v.time_created || v.timestamp);

    if (v.type === "system" && v.subtype === "init") {
      id = v.session_id || id;
      model = v.model || model;
      title = title || "Claude Code session";
    } else if (v.type === "result") {
      id = v.session_id || id;
      model = v.model || model;
    } else if (v.type === "stream_event") {
      const ev = v.event || {};
      if (!ev || typeof ev !== "object") continue;
      if (ev.type === "message_start" && ev.message) {
        id = ev.message.id || id;
        model = ev.message.model || model;
        title = title || (ev.message.title || "Claude Code session");
        flushAssistant();
        curAssistant = { content: [], files: [], finish: null, at: ev.message.time_created || v.time_created };
      } else if (ev.type === "content_block_start") {
        const cb = ev.content_block || {};
        if (cb.type === "tool_use" && curAssistant) {
          const input = cb.input || {};
          const target = input.path || input.file || input.target || "";
          if (target && !curAssistant.files.includes(target)) curAssistant.files.push(target);
        }
      } else if (ev.type === "content_block_delta" && curAssistant) {
        const d = ev.delta || {};
        if (d.type === "text_delta" && d.text) curAssistant.content.push(d.text);
        if (d.type === "input_json_delta" && d.partial_json) {
          try {
            const patch = JSON.parse(d.partial_json);
            const target = patch.path || patch.file || patch.target || "";
            if (target && !curAssistant.files.includes(target)) curAssistant.files.push(target);
          } catch {}
        }
      } else if (ev.type === "message_stop") {
        if (curAssistant) curAssistant.finish = "stop";
        flushAssistant();
      }
    }
  }
  flushAssistant();

  if (!id) id = path.basename(filePath, ".jsonl");
  if (!startedAt) startedAt = null;
  if (!updatedAt) updatedAt = null;

  return { id, title, messages, model, startedAt, updatedAt, agentTurns };
}

// Orchestrator session id -> Claude Code subagent transcripts
// (~/.claude/projects/<repo-slug>/<session-id>/subagents/agent-*.jsonl).
function readClaudeCodeSubagents(orchSessionId) {
  const projectsDir = path.join(process.env.HOME || process.env.USERPROFILE, ".claude", "projects");
  const out = [];
  if (!fs.existsSync(projectsDir)) return out;
  let projectFolders;
  try {
    projectFolders = fs.readdirSync(projectsDir);
  } catch {
    return out;
  }
  for (const project of projectFolders) {
    const subagentsDir = path.join(projectsDir, project, orchSessionId, "subagents");
    let files;
    try {
      files = fs.readdirSync(subagentsDir);
    } catch {
      continue;
    }
    for (const f of files.sort()) {
      if (!/^agent-.*\.jsonl$/.test(f)) continue;
      const filePath = path.join(subagentsDir, f);
      const parsed = readClaudeCodeJSONL(filePath);
      if (!parsed) continue;
      out.push({
        session: parsed.session || parsed.id || path.basename(f, ".jsonl").replace(/^agent-/, ""),
        role: "scout",
        harness: "claude-code",
        filePath,
        ...parsed,
      });
    }
  }
  return out;
}

// Nested Claude Code session recorded on the stream: a top-level
// ~/.claude/projects/<repo-slug>/<session-id>.jsonl file.
function findClaudeCodeNestedSession(sessionId) {
  const projectsDir = path.join(process.env.HOME || process.env.USERPROFILE, ".claude", "projects");
  if (!fs.existsSync(projectsDir)) return null;
  let projectFolders;
  try {
    projectFolders = fs.readdirSync(projectsDir);
  } catch {
    return null;
  }
  for (const project of projectFolders) {
    const candidate = path.join(projectsDir, project, `${sessionId}.jsonl`);
    try {
      if (fs.statSync(candidate).isFile()) return candidate;
    } catch {}
  }
  return null;
}

// Copy a child transcript we have read into the learnings area (retention option b),
// outside every repo so transcripts that can hold secrets never reach .opencode/reports
// and a commit. Never throws.
function copyChildTranscript(sourcePath, streamName, sessionId, harness) {
  if (!sourcePath || !fs.existsSync(sourcePath)) return false;
  const destDir = path.join(LEARNINGS_ROOT, streamName, "children");
  try {
    fs.mkdirSync(destDir, { recursive: true });
  } catch {
    return false;
  }
  const ext = path.extname(sourcePath) || (harness === "opencode" ? ".db" : ".jsonl");
  const dest = path.join(destDir, `${sessionId}${ext}`);
  try {
    fs.copyFileSync(sourcePath, dest);
    return true;
  } catch {
    return false;
  }
}

// Collect every child session of a stream:
//  - OpenCode workers/critics: `ses_...` ids carried on stream events.
//  - Nested Claude Code sessions: `child` events recorded on the stream.
//  - Claude Code subagents: agent-*.jsonl under the orchestrator session's subagents/.
function collectChildren(streamName) {
  const children = [];
  const seen = new Set();
  const events = readStreamEvents(streamName);
  const stream = readStreamState(streamName);

  const add = (session, harness, role, source) => {
    if (!session || seen.has(session)) return;
    seen.add(session);
    children.push({ session, harness, role, source });
  };

  // OpenCode children: session ids on stream events, with role from the event's agent.
  const ocRoleBySession = new Map();
  for (const e of events) {
    if (e.session && SESSION_RE.test(e.session)) {
      if (!ocRoleBySession.has(e.session)) ocRoleBySession.set(e.session, e.agent);
    }
  }
  for (const [session, agent] of ocRoleBySession) {
    add(session, "opencode", agent && CHILD_ROLES.includes(agent) ? agent : "worker", "stream-event");
  }

  // Nested Claude Code sessions recorded via `child` events.
  for (const e of events) {
    if ((e.event === "child" || e.kind === "child") && e.session) {
      const role = e.role && CHILD_ROLES.includes(e.role) ? e.role : "nested";
      const harness = e.harness || "claude-code";
      const filePath = harness === "claude-code" ? findClaudeCodeNestedSession(e.session) : null;
      add(e.session, harness, role, "child-event");
      const child = children[children.length - 1];
      if (filePath) child.filePath = filePath;
    }
  }

  // Claude Code subagents of the orchestrator session (held_session / session on the stream).
  const orchSessionId = (stream && (stream.held_session || stream.session)) || null;
  if (orchSessionId) {
    for (const sa of readClaudeCodeSubagents(orchSessionId)) {
      add(sa.session, sa.harness, sa.role, "subagent");
      // attach filePath for review; not part of the public child descriptor
      const child = children[children.length - 1];
      child.filePath = sa.filePath;
    }
  }

  return children;
}

// Tag a finding with the child's role/harness/model/session so every child
// finding is attributable in the merged report.
function tagChildFindings(findings, child) {
  return findings.map((f) => ({
    ...f,
    role: child.role,
    harness: child.harness,
    ...(child.model ? { model: child.model } : {}),
    session: child.session,
  }));
}

// Review one child session through the phase-5 lenses. Never crashes on a
// missing or aged-out transcript; reports status "missing" instead.
function reviewChild(child, streamName) {
  const report = {
    session: child.session,
    harness: child.harness,
    role: child.role,
    model: child.model,
    status: "missing",
    note: null,
    findings: [],
    transcriptCopied: false,
  };

  let parsed;
  if (child.harness === "opencode") {
    const session = readOpenCodeSession(child.session);
    if (!session) {
      report.note = `OpenCode session ${child.session} not found in ${OPENCODE_DB}`;
      return report;
    }
    parsed = {
      id: session.id,
      title: session.title,
      messages: session.messages,
      model: null,
      startedAt: session.time_created,
      updatedAt: session.time_updated,
    };
    // OpenCode transcript lives in the single opencode.db; copy that db once per stream.
  } else {
    parsed = readClaudeCodeJSONL(child.filePath);
    if (!parsed) {
      report.note = `Claude Code transcript for ${child.session} not found at ${child.filePath}`;
      return report;
    }
    report.transcriptCopied = copyChildTranscript(child.filePath, streamName, child.session, child.harness);
  }

  child.model = parsed.model || child.model;
  report.model = parsed.model || child.model;
  report.status = "analyzed";
  report.note = null;

  const findings = analyzeSessionData(
    parsed.messages,
    parsed.id,
    parsed.title,
    parsed.startedAt,
    parsed.updatedAt,
    parsed.model,
  );
  report.findings = tagChildFindings(findings, child);
  return report;
}

// ---------------------------------------------------------------------------
// Real session data readers
// ---------------------------------------------------------------------------

// Orchestrator data lives in ~/.config/orchestrator (not in the project)
const ORCH_ROOT = path.join(process.env.HOME || process.env.USERPROFILE, ".config", "orchestrator");

function readDeskDaemonLogs() {
  const logPath = path.join(ORCH_ROOT, "desk-daemon", "daemon.log");
  if (!fs.existsSync(logPath)) return [];
  const content = fs.readFileSync(logPath, "utf8");
  return content.split("\n").filter(line => line.trim());
}

function readStreamState(streamName) {
  const streamPath = path.join(ORCH_ROOT, "streams", `${streamName}.json`);
  if (!fs.existsSync(streamPath)) return null;
  return JSON.parse(fs.readFileSync(streamPath, "utf8"));
}

function readStreamEvents(streamName) {
  const eventsPath = path.join(ORCH_ROOT, "streams", `${streamName}.events.jsonl`);
  if (!fs.existsSync(eventsPath)) return [];
  return fs.readFileSync(eventsPath, "utf8").split("\n")
    .filter(l => l.trim())
    .map(l => { try { return JSON.parse(l); } catch { return null; } })
    .filter(Boolean);
}

// The escalations the desk daemon recorded for ONE stream. dpage writes a row per escalation, stream
// included, so this is the per-stream source; daemon.log interleaves every stream and is not.
function readStreamEscalations(streamName) {
  const p = path.join(ORCH_ROOT, "desk-daemon", "escalations.jsonl");
  if (!fs.existsSync(p)) return [];
  return fs.readFileSync(p, "utf8").split("\n")
    .filter(l => l.trim())
    .map(l => { try { return JSON.parse(l); } catch { return null; } })
    .filter(e => e && e.stream === streamName);
}

// The report directories a stream's runs wrote to: every event's `out` sits in its ticket's run dir,
// wherever that repo lives. This is what ties a receipt to a stream.
function streamRunDirs(streamName) {
  return [...new Set(readStreamEvents(streamName).map(e => (e.out ? path.dirname(e.out) : null)).filter(Boolean))];
}

// Worker receipts of this stream's runs only (all rounds). Until 2026-11-24 this read every ticket dir
// under both report roots, so a review of one stream reported totals for all of them.
function readWorkerReceipts(streamName) {
  const receipts = [];
  for (const dir of streamRunDirs(streamName)) {
    if (!fs.existsSync(dir)) continue;
    for (const f of fs.readdirSync(dir).sort()) {
      if (!/^worker-r\d+\.md\.receipt\.json$/.test(f)) continue;
      try {
        receipts.push(JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")));
      } catch {}
    }
  }
  return receipts;
}

function readCriticFindings(reportDir) {
  // Check both project and global opencode reports
  const reportPaths = [
    path.join(process.cwd(), ".opencode", "reports"),
    path.join(process.env.HOME || process.env.USERPROFILE, ".opencode", "reports"),
  ];
  for (const reportPath of reportPaths) {
    const criticPath = path.join(reportPath, reportDir, "critic-r1.md");
    if (fs.existsSync(criticPath)) {
      return fs.readFileSync(criticPath, "utf8");
    }
  }
  return null;
}

// Count the critic-rN.md round files really present for a stream's report dir.
function countCriticRounds(reportDir) {
  let max = 0;
  const reportPaths = [
    path.join(process.cwd(), ".opencode", "reports"),
    path.join(process.env.HOME || process.env.USERPROFILE, ".opencode", "reports"),
  ];
  for (const reportPath of reportPaths) {
    const dir = path.join(reportPath, reportDir);
    if (!reportDir || !fs.existsSync(dir)) continue;
    for (const f of fs.readdirSync(dir)) {
      const m = f.match(/^critic-r(\d+)\.md$/);
      if (m) max = Math.max(max, parseInt(m[1], 10));
    }
  }
  return max;
}

function readStreamHandoffs(streamName) {
  const streamPath = path.join(ORCH_ROOT, "streams", `${streamName}.json`);
  if (!fs.existsSync(streamPath)) return null;
  return JSON.parse(fs.readFileSync(streamPath, "utf8"));
}

function readPeerMailEvents() {
  const peerMailDir = path.join(ORCH_ROOT, "peer-mail");
  if (!fs.existsSync(peerMailDir)) return [];
  const files = fs.readdirSync(peerMailDir);
  const events = [];
  for (const file of files) {
    if (file.endsWith(".jsonl")) {
      const content = fs.readFileSync(path.join(peerMailDir, file), "utf8");
      for (const line of content.split("\n")) {
        if (!line.trim()) continue;
        try { events.push(JSON.parse(line)); } catch {}
      }
    }
  }
  return events;
}

function readWorkerDiffs(reportDir) {
  const diffs = [];
  const reportPaths = [
    path.join(process.cwd(), ".opencode", "reports"),
    path.join(process.env.HOME || process.env.USERPROFILE, ".opencode", "reports"),
  ];
  for (const reportPath of reportPaths) {
    if (!fs.existsSync(reportPath)) continue;
    const entries = fs.readdirSync(reportPath);
    for (const entry of entries) {
      // First try to get diff from worker report
      for (let i = 1; i <= 10; i++) {
        const workerReportPath = path.join(reportPath, entry, `worker-r${i}.md`);
        if (fs.existsSync(workerReportPath)) {
          try {
            const content = fs.readFileSync(workerReportPath, "utf8");
            // Extract diff from worker report
            const diffMatch = content.match(/```diff\n([\s\S]*?)\n```/);
            if (diffMatch) {
              diffs.push({
                reportDir: entry,
                diff: diffMatch[1],
                fullReport: content,
              });
              continue;
            }
            // Try to extract commit SHA from report
            const commitMatch = content.match(/committed as `([a-f0-9]{7,40})`/);
            if (commitMatch) {
              const sha = commitMatch[1];
              // Get diff from git
              const result = spawnSync("git", ["show", sha, "--no-merges", "--format=", "-p"], {
                cwd: process.cwd(),
                encoding: "utf8",
                timeout: 5000,
              });
              if (result.status === 0 && result.stdout.trim()) {
                diffs.push({
                  reportDir: entry,
                  diff: result.stdout.trim(),
                  fullReport: content,
                  commit: sha,
                });
                continue;
              }
            }
          } catch {}
        }
      }
      // Also try to get diff from orchestrator receipt which may have the base/head
      const orchReceiptPath = path.join(reportPath, entry, "orchestrator-receipt.md");
      if (fs.existsSync(orchReceiptPath)) {
        try {
          const content = fs.readFileSync(orchReceiptPath, "utf8");
          const branchMatch = content.match(/branch\s+(\S+)/);
          const shaMatch = content.match(/head\s+sha\s+([a-f0-9]{7,40})/i);
          if (branchMatch || shaMatch) {
            // Try to get diff from the branch or sha
            const ref = shaMatch ? shaMatch[1] : branchMatch[1];
            const result = spawnSync("git", ["diff", "origin/main...HEAD", "--", "."], {
              cwd: process.cwd(),
              encoding: "utf8",
              timeout: 5000,
            });
            if (result.status === 0 && result.stdout.trim()) {
              diffs.push({
                reportDir: entry,
                diff: result.stdout.trim(),
                fullReport: content,
                commit: ref,
              });
            }
          }
        } catch {}
      }
    }
  }
  return diffs;
}

function readAtlasBestPractices() {
  const atlasPath = path.join(process.cwd(), "docs", "ATLAS.md");
  if (!fs.existsSync(atlasPath)) return null;
  return fs.readFileSync(atlasPath, "utf8");
}

function readClaudeMd() {
  const claudePath = path.join(process.cwd(), "CLAUDE.md");
  if (!fs.existsSync(claudePath)) return null;
  return fs.readFileSync(claudePath, "utf8");
}

function readPitfallsArchive() {
  const pitfallsPath = path.join(process.cwd(), ".claude", "reference", "pitfalls-archive.md");
  if (!fs.existsSync(pitfallsPath)) return null;
  return fs.readFileSync(pitfallsPath, "utf8");
}

// ---------------------------------------------------------------------------
// Real finding generators — analyze ACTUAL session data
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Per-run join: stream events + opencode.db (learn-runs ticket)
// Joins each stream run (queued + run-done) to its OpenCode session to surface
// start delay, after-kill activity and long tool calls. Read-only: a missing
// opencode.db or missing table yields no findings and never crashes.
// ---------------------------------------------------------------------------

function buildRunTimeline(events) {
  const runs = {};
  for (const e of events) {
    const key = String(e.key || "");
    const mq = key.match(/^run:(.+):queued$/);
    const md = key.match(/^run:(.+):done$/);
    if (mq) {
      runs[mq[1]] = runs[mq[1]] || {};
      runs[mq[1]].queued = { at: e.at, out: e.out, run: e.run, session: e.session };
    }
    if (md) {
      runs[md[1]] = runs[md[1]] || {};
      runs[md[1]].done = { at: e.at, outcome: e.outcome, exit: e.exit, session: e.session, run: e.run, out: e.out };
    }
  }
  return runs;
}

function isoToMs(s) {
  if (!s) return null;
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d.getTime();
}

function dbQuery(dbPath, sql) {
  if (!fs.existsSync(dbPath)) return null;
  const result = spawnSync("sqlite3", [dbPath, sql], { encoding: "utf8", timeout: 30000 });
  if (result.status !== 0) return null;
  const out = result.stdout.trim();
  if (!out || out === "[]") return null;
  try { return JSON.parse(out); } catch { return null; }
}

// First session_message at/after fromMs; returns its time_created (ms) or null.
function sessionFirstMessageAtOrAfter(dbPath, sessionId, fromMs) {
  const safe = sessionId.replace(/'/g, "''");
  const sql = `SELECT json_group_array(json_object('time_created', time_created)) FROM session_message WHERE session_id = '${safe}' AND time_created >= ${fromMs} ORDER BY seq LIMIT 1`;
  const rows = dbQuery(dbPath, sql);
  if (!rows || !rows.length) return null;
  return Number(rows[0].time_created);
}

// Tool session_part rows for a session in (fromMs, toMs]; parsed data.
function sessionToolParts(dbPath, sessionId, fromMs, toMs) {
  const safe = sessionId.replace(/'/g, "''");
  const upper = toMs ? `AND time_updated <= ${toMs}` : "";
  const sql = `SELECT json_group_array(json_object('message_id', message_id, 'ordinal', ordinal, 'data', data, 'time_created', time_created, 'time_updated', time_updated)) FROM session_part WHERE session_id = '${safe}' AND type = 'tool' AND time_updated > ${fromMs} ${upper} ORDER BY time_updated`;
  const rows = dbQuery(dbPath, sql);
  if (!rows || !rows.length) return [];
  return rows.map((r) => {
    let data = null;
    try { data = JSON.parse(r.data); } catch {}
    return { message_id: r.message_id, ordinal: r.ordinal, time_created: r.time_created, time_updated: r.time_updated, data };
  });
}

// Per-run opencode join findings for one stream.
function perRunOpencodeFindings(stream) {
  const findings = [];
  const dbPath = OPENCODE_DB;
  if (!fs.existsSync(dbPath)) return findings;

  const events = readStreamEvents(stream);
  const runs = buildRunTimeline(events);
  const queuedEvents = events.filter((e) => String(e.key || "").endsWith(":queued"));

  for (const [run, tl] of Object.entries(runs)) {
    const done = tl.done;
    const queued = tl.queued;
    if (!done || !done.session) continue;
    const doneMs = isoToMs(done.at);
    if (doneMs === null) continue;

    // --- start delay: first message at/after queued.at minus queued.at ---
    if (queued && queued.at) {
      const qMs = isoToMs(queued.at);
      if (qMs !== null) {
        // oc-worker's own record of the slot wait (receipt queued_s) wins; else first prompt message - queued.at.
        let receiptQueuedS = null;
        try {
          const rc = done.out ? JSON.parse(fs.readFileSync(done.out + ".receipt.json", "utf8")) : null;
          if (rc && Number.isFinite(rc.queued_s)) receiptQueuedS = rc.queued_s;
        } catch {}
        const firstMsg = receiptQueuedS === null ? sessionFirstMessageAtOrAfter(dbPath, done.session, qMs) : null;
        if (receiptQueuedS !== null || firstMsg !== null) {
          const delayMs = receiptQueuedS !== null ? receiptQueuedS * 1000 : firstMsg - qMs;
          if (delayMs > 120 * 1000) {
            const delayMin = Math.round(delayMs / 1000 / 60);
            findings.push({
              area: "process-metrics",
              focus: "start delay",
              lens: "retry-recovery",
              status: "analyzed",
              detail: `${run}: waited ${delayMin} min before opencode got its prompt (worker slot or server queue)`,
              recommendation: "Raise WORKER_SLOTS / add a progress heartbeat so a queued run is visible instead of silently waiting.",
              evidence: [run, done.session],
              source: "opencode-session",
            });
          }
        }
      }
    }

    // --- after-kill activity: parts after run-done.at + 60s, bounded by next queued resume ---
    if (["timeout", "stalled", "error"].includes(done.outcome)) {
      const afterKillFrom = doneMs + 60 * 1000;
      let resumeBoundMs = null;
      const currentDir = done.out ? path.dirname(done.out) : null;
      for (const qe of queuedEvents) {
        const qeMs = isoToMs(qe.at);
        if (qeMs === null || qeMs <= doneMs) continue;
        const sameSession = qe.session && qe.session === done.session;
        const sameDir = currentDir && qe.out && path.dirname(qe.out) === currentDir;
        if (sameSession || sameDir) {
          resumeBoundMs = qeMs;
          break;
        }
      }
      const parts = sessionToolParts(dbPath, done.session, afterKillFrom, resumeBoundMs);
      let toolCalls = 0;
      const gitWrites = [];
      let lastUpdated = afterKillFrom;
      for (const p of parts) {
        toolCalls++;
        lastUpdated = Math.max(lastUpdated, p.time_updated);
        const data = p.data;
        const input = data && data.state && data.state.input;
        const cmd = input && input.command;
        if (cmd && /\bgit\s+(?:-C\s+\S+\s+)?(add|commit|stash|reset|checkout)\b/.test(cmd)) {
          gitWrites.push(cmd.trim().slice(0, 100));
        }
      }
      if (toolCalls > 0) {
        const keptMin = Math.round(Math.max(0, lastUpdated - afterKillFrom) / 1000 / 60);
        findings.push({
          area: "desk-operations",
          focus: "after-kill activity",
          lens: "retry-recovery",
          status: "analyzed",
          severity: "high",
          detail: `${run}: agent kept working ${keptMin} min after the kill: ${toolCalls} tool calls, git writes: ${gitWrites.join("; ")}`,
          recommendation: "Name ticket killed-run-stops-agent / --standalone so a killed run's agent is stopped instead of left to keep committing.",
          evidence: [run, done.session],
          source: "opencode-session",
        });
      }
    }

    // --- long tool calls: shell part duration > 5 min, or still open at run-done ---
    const allParts = sessionToolParts(dbPath, done.session, 0, null);
    for (const p of allParts) {
      const data = p.data;
      const state = data && data.state;
      const t = state && state.time;
      const input = state && state.input;
      const cmd = input && input.command;
      const name = data && data.name;
      if (!cmd || (name !== "shell" && name !== "bash")) continue;
      const created = t && t.created;
      const completed = t && t.completed;
      let longMin = null;
      let stillOpen = false;
      if (completed !== undefined && completed !== null && created !== undefined && created !== null) {
        const durMs = completed - created;
        if (durMs > 5 * 60 * 1000) longMin = Math.round(durMs / 1000 / 60);
      } else if (created !== undefined && created !== null && created <= doneMs) {
        stillOpen = true;
      }
      if (longMin !== null) {
        findings.push({
          area: "process-metrics",
          focus: "long tool call",
          lens: "retry-recovery",
          status: "analyzed",
          detail: `${run}: shell part ran ${longMin} min: ${String(cmd).slice(0, 100)}`,
          recommendation: "Add a timeout to long shell calls (spawnSync { timeout } / `timeout `) so a hung tool cannot outlive its run.",
          evidence: [run, done.session],
          source: "opencode-session",
        });
      } else if (stillOpen) {
        findings.push({
          area: "process-metrics",
          focus: "long tool call",
          lens: "retry-recovery",
          status: "analyzed",
          detail: `${run}: shell part still open at run-done: ${String(cmd).slice(0, 100)}`,
          recommendation: "Add a timeout to long shell calls (spawnSync { timeout } / `timeout `) so a hung tool cannot outlive its run.",
          evidence: [run, done.session],
          source: "opencode-session",
        });
      }
    }
  }
  return findings;
}

function analyzeCommunicationPatterns(stream, args) {
  const findings = [];
  const streamState1 = readStreamState(args.stream);
  const events = readStreamEvents(args.stream);
  const handoff = readStreamHandoffs(args.stream);
  const peerMailEvents = readPeerMailEvents();

  // Peer-mail latency analysis -> peer-mail lens
  if (peerMailEvents.length > 0) {
    const latencies = peerMailEvents
      .filter(e => e.latency_ms)
      .map(e => e.latency_ms)
      .sort((a, b) => a - b);
    if (latencies.length > 0) {
      const median = latencies[Math.floor(latencies.length / 2)];
      const p95 = latencies[Math.floor(latencies.length * 0.95)];
      findings.push({
        area: "peer-mail",
        focus: "message latency",
        lens: "peer-mail",
        status: "analyzed",
        detail: `peer-mail round-trip latency: median ${median}ms, p95 ${p95}ms across ${latencies.length} messages.`,
        recommendation: "Add async batching for non-critical notifications; reserve synchronous path for escalations.",
        evidence: [".config/orchestrator/peer-mail/*.jsonl"],
        source: "session-data",
      });
    }
  }

  // Desk daemon stability -> desk-operations lens
  const deskLogs = readDeskDaemonLogs();
  const restarts = deskLogs.filter(l => l.includes("restarted") || l.includes("PID recycle")).length;
  if (restarts > 0) {
    findings.push({
      area: "desk-operations",
      focus: "desk daemon stability",
      lens: "desk-operations",
      status: "analyzed",
      detail: `${restarts} desk daemon log line(s) mention a restart or PID recycle (of ${deskLogs.length} log lines read).`,
      recommendation: "Add systemd watchdog for desk-daemon; implement heartbeat health check in desk.mjs.",
      evidence: [".config/orchestrator/desk-daemon/daemon.log", "bin/desk.mjs"],
      source: "session-data",
    });
  }

  // Subagent coordination - worker-critic rounds -> subagent-coordination lens
  const criticFindings = readCriticFindings(args.stream);
  if (criticFindings) {
    const rounds = countCriticRounds(args.stream);
    findings.push({
      area: "subagent-coordination",
      focus: "worker-critic round efficiency",
      lens: "subagent-coordination",
      status: "analyzed",
      detail: `${rounds} critic round file(s) (critic-r1..r${rounds}.md) found for "${args.stream}".`,
      recommendation: "Add pre-flight test checklist to worker prompt; enforce 'test-first' in mandate template.",
      evidence: [".opencode/reports/*/worker-r*.md", ".opencode/reports/*/critic-r*.md"],
      source: "session-data",
    });
  }

  // Handoff quality -> handoff-quality lens
  if (handoff) {
    const missingWaiting = !handoff.waiting || handoff.waiting.trim() === "";
    const staleNext = handoff.next && (Date.now() - new Date(handoff.next).getTime()) > 48 * 3600 * 1000;
    if (missingWaiting || staleNext) {
      findings.push({
        area: "handoff-quality",
        focus: "stream handoff completeness",
        lens: "handoff-quality",
        status: "analyzed",
        detail: `Handoff ${missingWaiting ? "missing 'waiting' field" : ""} ${staleNext ? "stale 'next' pointer" : ""}.`,
        recommendation: "Add handoff validation gate in desk.mjs; require 'waiting' field for non-done states.",
        evidence: [".config/orchestrator/streams/*.json", "bin/handoff.mjs"],
        source: "session-data",
      });
    }
  }

  // Cross-harness sync -> cross-harness-sync lens (not in phase 1, but we can add it)
  const peerMailDir = path.join(ORCH_ROOT, "peer-mail");
  if (fs.existsSync(peerMailDir)) {
    findings.push({
      area: "cross-harness-sync",
      focus: "Claude Code ↔ OpenCode handoff",
      lens: "subagent-coordination", // Map to closest phase 1 lens
      status: "heuristic",
      detail: `A peer-mail directory exists (${peerMailEvents.length} event(s) read); this review does not measure session-id correlation across handoffs.`,
      recommendation: "Check that handoffs carry an explicit session-id correlation and that ack timeouts suit your workflow.",
      evidence: [".config/orchestrator/peer-mail/", "bin/handoff.mjs"],
      source: "heuristic",
    });
  }

  return findings;
}

function analyzeErrorHandlingPatterns(stream, args) {
  const findings = [];
  const escalations = readStreamEscalations(args.stream);
  const count = (p) => escalations.filter(e => String(e.reason ?? "").includes(p)).length;

  // Desk daemon escalations on THIS stream, by kind
  const errorPatterns = {
    "verdict-failed": { lens: "error-propagation", count: count("verdict-failed") },
    "worker-timeout": { lens: "retry-recovery", count: count("worker-timeout") },
    "worker-error": { lens: "error-propagation", count: count("worker-error") },
    "worker-no_pool": { lens: "retry-recovery", count: count("worker-no_pool") },
    "worker-blocked": { lens: "dead-letter-handling", count: count("worker-blocked") },
    "critic-failed": { lens: "error-propagation", count: count("critic-failed") },
    "review-unlinked": { lens: "circuit-breakers", count: count("review-unlinked") },
    "agent-senior": { lens: "circuit-breakers", count: count("agent-senior") },
    "run-dead": { lens: "retry-recovery", count: count("run-dead") },
    "no-ticket": { lens: "error-propagation", count: count("no-ticket") },
  };

  for (const [pattern, data] of Object.entries(errorPatterns)) {
    if (data.count > 0) {
      findings.push({
        area: "desk-operations",
        focus: pattern.replace(/[-_]/g, " "),
        lens: data.lens,
        status: "analyzed",
        detail: `${data.count} occurrences of "${pattern}" escalated on stream "${args.stream}" (of ${escalations.length} escalation(s) for it).`,
        recommendation: getErrorRecommendation(pattern),
        evidence: [".config/orchestrator/desk-daemon/escalations.jsonl"],
        source: "session-data",
      });
    }
  }

  // Worker receipt analysis -> retry-recovery lens
  const receipts = readWorkerReceipts(args.stream);
  if (receipts.length > 0) {
    const totalTokens = receipts.reduce((sum, r) => sum + (r.tokens?.input || 0) + (r.tokens?.output || 0), 0);
    const totalTime = receipts.reduce((sum, r) => sum + (r.seconds || 0), 0);
    const maxSilence = Math.max(...receipts.map(r => r.max_silence_s || 0));
    const errorCount = receipts.filter(r => r.errors && r.errors.length > 0).length;

    findings.push({
      area: "subagent-coordination",
      focus: "worker-critic round efficiency",
      lens: "retry-recovery",
      status: "analyzed",
      detail: `Analyzed ${receipts.length} worker receipts: ${totalTokens.toLocaleString()} tokens, ${totalTime}s total, max silence ${maxSilence}s, ${errorCount} with errors.`,
      recommendation: "Add pre-flight test checklist to worker prompt; enforce 'test-first' in mandate template.",
      evidence: [".opencode/reports/*/worker-r*.md.receipt.json"],
      source: "session-data",
    });
  }

  // Critic round analysis -> circuit-breakers lens
  const criticFindings = readCriticFindings(args.stream);
  if (criticFindings) {
    const rounds = countCriticRounds(args.stream);
    findings.push({
      area: "subagent-coordination",
      focus: "worker-critic round efficiency",
      lens: "circuit-breakers",
      status: "analyzed",
      detail: `${rounds} critic round file(s) found for "${args.stream}".`,
      recommendation: "Add pre-flight test checklist to worker prompt; enforce 'test-first' in mandate template.",
      evidence: [".opencode/reports/*/worker-r*.md", ".opencode/reports/*/critic-r*.md"],
      source: "session-data",
    });
  }

  // Per-run opencode join: start delay, after-kill activity, long tool calls.
  findings.push(...perRunOpencodeFindings(args.stream));

  return findings;
}

function getErrorRecommendation(pattern) {
  const recs = {
    "verdict-failed": "Validate worktree exists before verdict; auto-create worktree on claim.",
    "worker-timeout": "Check the start-delay, after-kill and long-tool findings for this run before raising the timeout — a queued worker slot, an orphaned agent still committing, or a hung shell call is usually the cause, not the timeout value itself.",
    "worker-error": "Improve error context in worker receipts; add stack trace capture.",
    "worker-no_pool": "Every worker pool was down (quota or out of credits): run router-health, then top up or drop the exhausted pool; the Claude Code worker fallback covers the run meanwhile.",
    "worker-blocked": "Add automatic unblock after timeout; escalate to desk daemon.",
    "critic-failed": "Improve critic prompt to handle edge cases; add fallback to human review.",
    "review-unlinked": "Link critic findings to worker run in board.mjs round recording.",
    "agent-senior": "Auto-assign senior for guarded paths; reduce manual escalation.",
    "run-dead": "Improve run-dead detection; adopt worktree if agent still alive (see video-studio-m4).",
    "no-ticket": "Auto-create ticket from desk event; prevent orphan events.",
  };
  return recs[pattern] || "Investigate root cause and add automated handling.";
}

function analyzeCoordinationPatterns(stream, args) {
  const findings = [];
  const streamState2 = readStreamState(args.stream);
  const peerMailEvents = readPeerMailEvents();

  // Process coordination - subagent depth -> process-coordination lens
  findings.push({
    area: "process-coordination",
    focus: "subagent orchestration depth",
    lens: "process-coordination",
    status: "heuristic",
    detail: "Orchestration depth is not measured from receipts. Deep subagent hierarchies tend to dilute context and inflate token use.",
    recommendation: "Keep orchestration depth shallow; flatten reviewer hierarchies via a synthesizer pattern.",
    evidence: [".opencode/reports/*/worker-r*.md", "bin/oc-worker.mjs"],
    source: "heuristic",
  });

  // Cross-harness sync -> cross-harness-sync lens
  if (peerMailEvents.length > 0) {
    const crossSession = peerMailEvents.filter(e => e.session_id && e.from_session !== e.to_session).length;
    findings.push({
      area: "cross-harness-sync",
      focus: "Claude Code ↔ OpenCode state sync",
      lens: "cross-harness-sync",
      status: "heuristic",
      detail: `${peerMailEvents.length} peer-mail event(s) read; ${crossSession} cross-session message(s) (from_session differs from to_session). Normal traffic looks like this; real session-id drift is not measured.`,
      recommendation: "If handoffs lose context, check that session ids are correlated across the handoff.mjs claim.",
      evidence: [".config/orchestrator/peer-mail/", "bin/handoff.mjs", "bin/peer-mail"],
      source: "heuristic",
    });
  }

  // Handoff quality -> handoff-quality lens
  if (streamState2) {
    const missingWaiting = !streamState2.waiting || streamState2.waiting.trim() === "";
    const staleNext = streamState2.next && (Date.now() - new Date(streamState2.next).getTime()) > 72 * 3600 * 1000;
    if (missingWaiting || staleNext) {
      findings.push({
        area: "handoff-quality",
        focus: "stream handoff fidelity",
        lens: "handoff-quality",
        status: "analyzed",
        detail: `Handoff ${missingWaiting ? "missing 'waiting' field" : ""} ${staleNext ? "stale 'next' pointer" : ""}.`,
        recommendation: "Add handoff validation in bin/handoff.mjs claim; require 'waiting' for non-done states.",
        evidence: [".config/orchestrator/streams/*.json", "bin/handoff.mjs"],
        source: "session-data",
      });
    }
  }

  // Process metrics from receipts -> process-metrics lens
  const receipts = readWorkerReceipts(args.stream);
  if (receipts.length > 0) {
    const totalTime = receipts.reduce((sum, r) => sum + (r.seconds || 0), 0);
    const avgTime = totalTime / receipts.length;
    const medianTime = receipts.map(r => r.seconds || 0).sort((a, b) => a - b)[Math.floor(receipts.length / 2)];
    const maxSilence = Math.max(...receipts.map(r => r.max_silence_s || 0));

    // Start-delay numbers from the per-run opencode join, folded into cycle time.
    const runFindings = perRunOpencodeFindings(args.stream);
    const startDelays = runFindings.filter((f) => f.focus === "start delay").map((f) => f.detail);
    let detail = `Avg worker time: ${(avgTime / 60).toFixed(1)}m; median: ${(medianTime / 60).toFixed(1)}m; max silence: ${maxSilence}s.`;
    if (startDelays.length) detail += " " + startDelays.join(" ");

    findings.push({
      area: "process-metrics",
      focus: "end-to-end cycle time",
      lens: "process-metrics",
      status: "analyzed",
      detail,
      recommendation: "Add SLA tracking to board.mjs; alert on tickets >12h without critic round.",
      evidence: [".opencode/reports/*/orchestrator-receipt.md", "bin/board.mjs"],
      source: "session-data",
    });

    const criticRounds = countCriticRounds(args.stream);
    if (criticRounds > 0) {
      findings.push({
        area: "process-metrics",
        focus: "critic round efficiency",
        lens: "process-metrics",
        status: "analyzed",
        detail: `${criticRounds} critic round file(s) vs ${receipts.length} worker receipt(s) for "${args.stream}".`,
        recommendation: "Add 'critic readiness' pre-check to worker prompt; fail fast on common patterns.",
        evidence: [".opencode/reports/*/critic-r*.md", "bin/oc-worker.mjs"],
        source: "session-data",
      });
    }
  }

  return findings;
}

// ---------------------------------------------------------------------------
// Phase 4 — Work Logic & Code Quality (analyzes actual diffs)
// ---------------------------------------------------------------------------

function analyzeWorkLogicPatterns(stream, args) {
  const findings = [];
  const diffs = readWorkerDiffs(args.stream);
  const atlas = readAtlasBestPractices();
  const claudeMd = readClaudeMd();
  const pitfalls = readPitfallsArchive();

  if (diffs.length === 0) {
    findings.push({
      area: "work-logic",
      focus: "no diffs found",
      lens: "async-patterns",
      status: "skipped",
      detail: "No worker diffs found in session reports.",
      recommendation: "Ensure workers produce diffs in their reports (```diff blocks).",
      evidence: [".opencode/reports/*/worker-r*.md"],
      source: "session-data",
    });
    return findings;
  }

  // Combine all diffs for analysis
  const allDiffs = diffs.map(d => d.diff).join("\n\n");

  // 1. Async patterns analysis -> async-patterns lens
  const asyncFindings = analyzeAsyncPatterns(allDiffs, diffs);
  findings.push(...asyncFindings);

  // 2. File operations analysis -> file-ops lens
  const fileOpsFindings = analyzeFileOperations(allDiffs, diffs);
  findings.push(...fileOpsFindings);

  // 3. Sandbox compliance -> sandbox-compliance lens
  const sandboxFindings = analyzeSandboxCompliance(allDiffs, diffs);
  findings.push(...sandboxFindings);

  // 4. Deployment drift (local vs prod) -> deployment-drift lens
  const deployFindings = analyzeDeploymentDrift(allDiffs, diffs, claudeMd);
  findings.push(...deployFindings);

  // 5. ATLAS adherence -> atlas-adherence lens
  const atlasFindings = analyzeAtlasAdherence(allDiffs, diffs, atlas, claudeMd, pitfalls);
  findings.push(...atlasFindings);

  return findings;
}

function analyzeAsyncPatterns(allDiffs, diffs) {
  const findings = [];

  // Check for blocking I/O patterns
  const blockingPatterns = [
    { pattern: /fs\.readFileSync\(/g, name: "fs.readFileSync", fix: "Use aiofiles.read() or fs.promises.readFile()" },
    { pattern: /fs\.writeFileSync\(/g, name: "fs.writeFileSync", fix: "Use aiofiles.write() or fs.promises.writeFile()" },
    { pattern: /fs\.existsSync\(/g, name: "fs.existsSync", fix: "Use fs.promises.access() or aiofiles.access()" },
    { pattern: /fs\.mkdirSync\(/g, name: "fs.mkdirSync", fix: "Use fs.promises.mkdir() or aiofiles.mkdir()" },
    { pattern: /child_process\.execSync\(/g, name: "child_process.execSync", fix: "Use async exec() with await" },
    { pattern: /child_process\.spawnSync\(/g, name: "child_process.spawnSync", fix: "Use spawn() with promise wrapper" },
    { pattern: /\breadFileSync\b/g, name: "readFileSync (any)", fix: "Use async file reading" },
    { pattern: /\bwriteFileSync\b/g, name: "writeFileSync (any)", fix: "Use async file writing" },
    { pattern: /\.sync\(/g, name: ".sync() methods", fix: "Use async equivalents" },
    { pattern: /subprocess\.run\([^)]*capture_output=True[^)]*\)/g, name: "subprocess.run with capture_output", fix: "Use asyncio.create_subprocess_exec" },
  ];

  for (const { pattern, name, fix } of blockingPatterns) {
    const matches = allDiffs.match(pattern);
    if (matches && matches.length > 0) {
      findings.push({
        area: "async-patterns",
        focus: "blocking I/O detected",
        lens: "async-patterns",
        status: "analyzed",
        detail: `Found ${matches.length} occurrence(s) of blocking ${name} in worker diffs.`,
        recommendation: fix,
        evidence: diffs.map(d => d.reportDir).slice(0, 3),
        source: "diff-analysis",
      });
    }
  }

  // Check for missing await on async functions
  const missingAwait = allDiffs.match(/(\w+\.(?:read|write|mkdir|access|exec|fetch|query|find|search)\([^)]*\))/g);
  if (missingAwait) {
    const unawaited = missingAwait.filter(m => !m.includes("await") && !m.includes(".then(")).length;
    if (unawaited > 0) {
      findings.push({
        area: "async-patterns",
        focus: "missing await",
        lens: "async-patterns",
        status: "analyzed",
        detail: `Found ${unawaited} potential missing await on async calls.`,
        recommendation: "Add 'await' before async function calls; ensure calling function is async.",
        evidence: diffs.map(d => d.reportDir).slice(0, 3),
        source: "diff-analysis",
      });
    }
  }

  // Check for proper async function declarations
  const asyncFuncs = allDiffs.match(/async\s+function\s+\w+|const\s+\w+\s*=\s*async\s*\(/g);
  if (asyncFuncs) {
    findings.push({
      area: "async-patterns",
      focus: "async function usage",
      lens: "async-patterns",
      status: "analyzed",
      detail: `Found ${asyncFuncs.length} async function declarations in diffs.`,
      recommendation: "Ensure all async functions are properly awaited; avoid fire-and-forget unless intentional.",
      evidence: diffs.map(d => d.reportDir).slice(0, 3),
      source: "diff-analysis",
    });
  }

  return findings;
}

function analyzeFileOperations(allDiffs, diffs) {
  const findings = [];

  // Check for heredoc/inline content patterns that should be proper files
  const heredocPatterns = [
    { pattern: /<<\s*['"]?EOF['"]?/g, name: "heredoc (<<EOF)", fix: "Write to proper file via aiofiles.write() or use template files" },
    { pattern: /cat\s+>\s+\S+\s*<<</g, name: "cat heredoc", fix: "Use aiofiles.write() with proper content" },
    { pattern: /echo\s+['"].*['"]\s*>\s+\S+/g, name: "echo redirect", fix: "Use aiofiles.write() for file creation" },
    { pattern: /printf\s+['"].*['"]\s*>\s+\S+/g, name: "printf redirect", fix: "Use aiofiles.write() for file creation" },
  ];

  for (const { pattern, name, fix } of heredocPatterns) {
    const matches = allDiffs.match(pattern);
    if (matches && matches.length > 0) {
      findings.push({
        area: "file-ops",
        focus: "inline content writing",
        lens: "file-ops",
        status: "analyzed",
        detail: `Found ${matches.length} occurrence(s) of ${name} in worker diffs.`,
        recommendation: fix,
        evidence: diffs.map(d => d.reportDir).slice(0, 3),
        source: "diff-analysis",
      });
    }
  }

  // Check for hardcoded paths
  const hardcodedPaths = allDiffs.match(/(?:\/home\/|\/tmp\/|\/opt\/|\/var\/|\/etc\/)[\w\-\/\.]+/g);
  if (hardcodedPaths) {
    const uniquePaths = [...new Set(hardcodedPaths)];
    findings.push({
      area: "file-ops",
      focus: "hardcoded paths",
      lens: "file-ops",
      status: "analyzed",
      detail: `Found ${uniquePaths.length} unique hardcoded absolute paths: ${uniquePaths.slice(0, 5).join(", ")}${uniquePaths.length > 5 ? "..." : ""}`,
      recommendation: "Use sandbox.resolve_path() for all file operations; use environment variables for config paths.",
      evidence: diffs.map(d => d.reportDir).slice(0, 3),
      source: "diff-analysis",
    });
  }

  // Check for proper temp file usage
  const tempFiles = allDiffs.match(/(?:tempfile|tmpfile|NamedTemporaryFile|temp\.mkstemp)/g);
  if (tempFiles) {
    findings.push({
      area: "file-ops",
      focus: "temp file usage",
      lens: "file-ops",
      status: "analyzed",
      detail: `Found ${tempFiles.length} temp file operations.`,
      recommendation: "Use /tmp/opencode for approved temp directory; cleanup explicitly in finally blocks.",
      evidence: diffs.map(d => d.reportDir).slice(0, 3),
      source: "diff-analysis",
    });
  }

  return findings;
}

function analyzeSandboxCompliance(allDiffs, diffs) {
  const findings = [];

  // Check for sandbox.resolve_path() usage
  const sandboxCalls = allDiffs.match(/sandbox\.resolve_path\(/g);
  const fileOps = allDiffs.match(/(?:open|read|write|mkdir|access|stat)\s*\(/g) || [];

  if (fileOps.length > 0 && (!sandboxCalls || sandboxCalls.length === 0)) {
    findings.push({
      area: "sandbox-compliance",
      focus: "missing sandbox validation",
      lens: "sandbox-compliance",
      status: "analyzed",
      detail: `Found ${fileOps.length} file operations but ${sandboxCalls?.length || 0} sandbox.resolve_path() calls.`,
      recommendation: "All file paths must go through sandbox.resolve_path() before operations. Never disable sandbox in prod.",
      evidence: diffs.map(d => d.reportDir).slice(0, 3),
      source: "diff-analysis",
    });
  }

  // Check for SANDBOX_ENABLED=false or similar
  const sandboxDisabled = allDiffs.match(/SANDBOX_ENABLED\s*=\s*false|sandbox.*disable|disable.*sandbox/gi);
  if (sandboxDisabled) {
    findings.push({
      area: "sandbox-compliance",
      focus: "sandbox disabled",
      lens: "sandbox-compliance",
      status: "analyzed",
      detail: `Found ${sandboxDisabled.length} occurrence(s) of sandbox disable patterns.`,
      recommendation: "NEVER disable sandbox in production. Use allowlist/deny modes for command filtering instead.",
      evidence: diffs.map(d => d.reportDir).slice(0, 3),
      source: "diff-analysis",
    });
  }

  // Check for path traversal risks
  const pathTraversal = allDiffs.match(/\.\.[\/\\]/g);
  if (pathTraversal) {
    findings.push({
      area: "sandbox-compliance",
      focus: "path traversal risk",
      lens: "sandbox-compliance",
      status: "analyzed",
      detail: `Found ${pathTraversal.length} potential path traversal patterns (../ or ..\\)`,
      recommendation: "Always use sandbox.resolve_path() which normalizes and validates paths.",
      evidence: diffs.map(d => d.reportDir).slice(0, 3),
      source: "diff-analysis",
    });
  }

  return findings;
}

function analyzeDeploymentDrift(allDiffs, diffs, claudeMd) {
  const findings = [];

  // Check for local-only patterns vs production
  const localPatterns = [
    { pattern: /localhost|127\.0\.0\.1|0\.0\.0\.0/g, name: "localhost binding", fix: "Use environment-specific config; production needs nginx/firewall" },
    { pattern: /\.env\.local|\.env\.development/g, name: "local env files", fix: "Use .env.example + environment-specific .env; never commit secrets" },
    { pattern: /debug\s*=\s*true|DEBUG\s*=\s*1/gi, name: "debug mode enabled", fix: "Use environment-specific config; production should have debug=false" },
    { pattern: /console\.log|print\(/g, name: "debug logging", fix: "Use proper logging library with levels; avoid console.log/print in production code" },
  ];

  for (const { pattern, name, fix } of localPatterns) {
    const matches = allDiffs.match(pattern);
    if (matches && matches.length > 0) {
      findings.push({
        area: "deployment-drift",
        focus: "local vs prod pattern",
        lens: "deployment-drift",
        status: "analyzed",
        detail: `Found ${matches.length} occurrence(s) of ${name} in worker diffs.`,
        recommendation: fix,
        evidence: diffs.map(d => d.reportDir).slice(0, 3),
        source: "diff-analysis",
      });
    }
  }

  // Check CLAUDE.md for deployment-specific guidance
  if (claudeMd) {
    const hasDeploymentSection = claudeMd.includes("deployment") || claudeMd.includes("deploy") || claudeMd.includes("production");
    if (!hasDeploymentSection) {
      findings.push({
        area: "deployment-drift",
        focus: "missing deployment docs",
        lens: "deployment-drift",
        status: "analyzed",
        detail: "CLAUDE.md lacks deployment/production section.",
        recommendation: "Add deployment section to CLAUDE.md with local vs prod differences, env vars, nginx config, etc.",
        evidence: ["CLAUDE.md"],
        source: "repo-config",
      });
    }
  }

  return findings;
}

function analyzeAtlasAdherence(allDiffs, diffs, atlas, claudeMd, pitfalls) {
  const findings = [];

  if (!atlas) {
    findings.push({
      area: "atlas-adherence",
      focus: "ATLAS missing",
      lens: "atlas-adherence",
      status: "analyzed",
      detail: "No docs/ATLAS.md found in repository.",
      recommendation: "Create docs/ATLAS.md with screen→route→handler→outcome map. Add best-practices section for this repo.",
      evidence: ["docs/ATLAS.md"],
      source: "repo-config",
    });
    return findings;
  }

  // Check if ATLAS has best-practices section
  const hasBestPractices = atlas.toLowerCase().includes("best practice") || atlas.toLowerCase().includes("convention") || atlas.toLowerCase().includes("guideline");
  if (!hasBestPractices) {
    findings.push({
      area: "atlas-adherence",
      focus: "missing best practices",
      lens: "atlas-adherence",
      status: "analyzed",
      detail: "ATLAS.md exists but lacks best-practices/conventions section.",
      recommendation: "Add a 'Best Practices' section to ATLAS.md with repo-specific patterns: async rules, sandbox usage, deployment, testing, etc.",
      evidence: ["docs/ATLAS.md"],
      source: "repo-config",
    });
  }

  // Check for pitfalls archive
  if (!pitfalls) {
    findings.push({
      area: "atlas-adherence",
      focus: "pitfalls archive missing",
      lens: "atlas-adherence",
      status: "analyzed",
      detail: "No .claude/reference/pitfalls-archive.md found.",
      recommendation: "Create pitfalls-archive.md to capture non-obvious issues (like #1-124 in Frood) so agents don't relearn them.",
      evidence: [".claude/reference/pitfalls-archive.md"],
      source: "repo-config",
    });
  }

  // Analyze diffs for patterns that violate known conventions from CLAUDE.md
  if (claudeMd) {
    const rules = [
      { pattern: "All I/O is async", check: /fs\.readFileSync|fs\.writeFileSync|fs\.existsSync/g, name: "async I/O rule" },
      { pattern: "Frozen config", check: /Settings.*dataclass|from_env\(\)/g, name: "frozen config pattern" },
      { pattern: "Graceful degradation", check: /optional|graceful|fallback/gi, name: "graceful degradation" },
      { pattern: "Sandbox always on", check: /sandbox\.resolve_path/g, name: "sandbox validation" },
      { pattern: "NEVER log API keys", check: /console\.log.*[Aa][Pp][Ii]|print.*[Pp][Aa][Ss][Ss]|logger.*[Kk][Ee][Yy]/g, name: "secret logging" },
    ];

    for (const { pattern: rulePattern, check, name } of rules) {
      if (claudeMd.includes(rulePattern)) {
        const violations = allDiffs.match(check);
        if (violations && violations.length > 0) {
          findings.push({
            area: "atlas-adherence",
            focus: `convention violation: ${name}`,
            lens: "atlas-adherence",
            status: "analyzed",
            detail: `Found ${violations.length} potential violation(s) of "${rulePattern}" convention.`,
            recommendation: `Follow ${name} convention from CLAUDE.md. Review diff for compliance.`,
            evidence: diffs.map(d => d.reportDir).slice(0, 3),
            source: "diff-analysis",
          });
        }
      }
    }
  }

  // Check for test patterns
  const testPatterns = allDiffs.match(/(?:test_|\.test\.|describe\(|it\(|pytest|vitest|jest)/g);
  if (!testPatterns || testPatterns.length === 0) {
    findings.push({
      area: "atlas-adherence",
      focus: "missing tests",
      lens: "atlas-adherence",
      status: "analyzed",
      detail: "No test patterns found in worker diffs.",
      recommendation: "New modules need tests/test_*.py. Follow project test conventions.",
      evidence: diffs.map(d => d.reportDir).slice(0, 3),
      source: "diff-analysis",
    });
  }

  return findings;
}

// ---------------------------------------------------------------------------
// MCP integration
// ---------------------------------------------------------------------------

function isMcpAvailable() {
  const mcpConfigPath = path.join(process.cwd(), ".mcp.json");
  if (!fs.existsSync(mcpConfigPath)) return false;
  try {
    const config = JSON.parse(fs.readFileSync(mcpConfigPath, "utf8"));
    return config.mcpServers?.frood !== undefined;
  } catch {
    return false;
  }
}

async function invokeMcpProcessReview(stream) {
  const hook = process.env.FROOD_LEARN_MCP_HOOK;
  if (!hook) return { used: false, reason: "no MCP hook configured (FROOD_LEARN_MCP_HOOK)" };

  try {
    const result = spawnSync(process.execPath, [
      "-e",
      `const { spawn } = require('child_process'); const cp = spawn('${hook.replace(/"/g, '\\"')}', ['${stream}'], { stdio: ['pipe', 'pipe', 'pipe'] }); cp.stdin.end(); let out = ''; cp.stdout.on('data', d => out += d); cp.on('close', () => { try { console.log(out) } catch(e) { console.error(out) } });`
    ], { encoding: "utf8", timeout: 30000, stdio: ['ignore', 'pipe', 'pipe'] });

    if (result.error || result.status !== 0) {
      return { used: false, reason: `MCP hook failed: ${result.error?.message || result.stderr}` };
    }
    return { used: true, data: result.stdout.trim() };
  } catch (e) {
    return { used: false, reason: `MCP invocation error: ${e.message}` };
  }
}

// ---------------------------------------------------------------------------
// Report assembly
// ---------------------------------------------------------------------------

function writeReport(report, reportPath) {
  const dir = path.dirname(reportPath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n");
  console.log(`Report written to: ${reportPath}`);
}

// ---------------------------------------------------------------------------
// Console summary
// ---------------------------------------------------------------------------

function printSummary(args, mcpResult, findings) {
  const phaseDef = PHASES[args.phase];
  const lens = args.lens || phaseDef.defaultLens;
  const displayStream = args.phase === 5 ? (args.sessionId || args.stream) : args.stream;
  console.log(`\n== /frood learn — ${phaseDef.name} ===`);
  console.log(`Stream:     ${displayStream}`);
  console.log(`Lens:       ${args.lens || phaseDef.defaultLens} (available: ${phaseDef.lenses.join(", ")})`);
  console.log(`Findings:   ${findings.length}`);

  // Show category breakdown
  const froodCode = findings.filter(f => f.category === "frood-code").length;
  const localEnv = findings.filter(f => f.category === "local-environment").length;
  console.log(`Categories: 📦 Frood code: ${froodCode} | 🏠 Local env: ${localEnv}`);

  console.log(`MCP:        ${mcpResult.used ? "available" : "fallback"} — ${mcpResult.reason}`);
  console.log(`Excluded:   ${META_REVIEW_EXCLUSION.join(", ")}\n`);

  for (const f of findings) {
    const catIcon = f.category === "frood-code" ? "📦" : "🏠";
    console.log(`  ${catIcon} [${f.area}] ${f.focus}: ${f.status} — ${f.detail} (${f.source})`);
  }
  console.log(`\nDone.`);

  if (args.apply) {
    console.log(`\n💡 Run with --apply to interactively fix or create PRs`);
  }
}

// ---------------------------------------------------------------------------
// Finding categorization: Frood code vs Local environment
// ---------------------------------------------------------------------------

function categorizeFinding(finding) {
  const detail = finding.detail.toLowerCase();
  const evidence = finding.evidence?.join(" ").toLowerCase() || "";
  const area = finding.area.toLowerCase();
  const focus = finding.focus.toLowerCase();
  const recommendation = finding.recommendation?.toLowerCase() || "";
  const source = finding.source.toLowerCase();

  // Frood codebase indicators
  const froodCodeIndicators = [
    "frood", "dashboard/", "core/", "mcp_server", "bin/frood", ".claude/commands/frood",
    "async i/o rule", "frozen config", "graceful degradation", "sandbox always on",
    "never log api keys", "atlas.md", "pitfalls-archive", "learning-engine",
    "knowledge-learn", "orchestrator", "gauntlet", "community/pr", "webhooks/github"
  ];

  // Local environment indicators
  const localEnvIndicators = [
    "/home/", "/tmp/", "/opt/", "/var/", "/etc/", "localhost", "127.0.0.1", "0.0.0.0",
    "console.log", "print(", "debug", "debug mode", "env.local", ".env.development",
    "sandbox.disabled", "path traversal", "hardcoded path", "heredoc", "cat <<",
    "echo >", "printf >", "tempfile", "/tmp/opencode"
  ];

  // Check source first
  if (source === "repo-config") {
    // Repo config issues (ATLAS, CLAUDE.md, pitfalls) are Frood code issues
    return "frood-code";
  }
  if (source === "diff-analysis") {
    // Check if diff is in Frood repo files
    const froodFiles = evidence.match(/(?:frood|dashboard|core|bin\/frood|\.claude\/commands)/);
    if (froodFiles) return "frood-code";
  }

  // Score-based categorization
  let froodScore = 0;
  let localScore = 0;

  const allText = `${detail} ${evidence} ${area} ${focus} ${recommendation}`;

  for (const indicator of froodCodeIndicators) {
    if (allText.includes(indicator.toLowerCase())) froodScore++;
  }
  for (const indicator of localEnvIndicators) {
    if (allText.includes(indicator.toLowerCase())) localScore++;
  }

  // Phase-based defaults
  if (finding.lens === "atlas-adherence" || finding.lens === "sandbox-compliance") {
    froodScore += 2;
  }
  if (finding.lens === "deployment-drift" || finding.lens === "file-ops") {
    localScore += 1;
  }

  // Special cases
  if (detail.includes("frood") || detail.includes("orchestrator") || detail.includes("gauntlet")) {
    froodScore += 3;
  }
  if (detail.includes("desk daemon") || detail.includes("peer-mail") || detail.includes("worker receipt")) {
    // Process findings are local orchestration issues
    localScore += 2;
  }

  return froodScore > localScore ? "frood-code" : "local-environment";
}

function categorizeFindings(findings) {
  return findings.map((f, i) => ({
    ...f,
    id: f.id || (i + 1),
    category: categorizeFinding(f),
  }));
}

// ---------------------------------------------------------------------------
// Interactive apply/PR mode (readline-based, no external deps)
// ---------------------------------------------------------------------------

function askQuestion(question, choices) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
    });

    console.log(`\n${question}`);
    choices.forEach((c, i) => {
      const marker = i === 0 ? "→ " : "  ";
      console.log(`  ${marker}${c.name}`);
    });
    console.log(`  (1-${choices.length}, default 1): `);

    rl.on("line", (input) => {
      const idx = parseInt(input.trim()) - 1;
      const choice = choices[idx >= 0 && idx < choices.length ? idx : 0];
      rl.close();
      resolve(choice.value);
    });
  });
}

async function interactiveApply(args, categorizedFindings) {
  const froodCode = categorizedFindings.filter(f => f.category === "frood-code");
  const localEnv = categorizedFindings.filter(f => f.category === "local-environment");

  console.log(`\n=== /frood learn — Apply Fixes ===`);
  console.log(`Stream: ${args.stream} | Phase: ${args.phase}`);
  console.log(`\nFindings categorized:`);
  console.log(`  📦 Frood code issues (can PR upstream): ${froodCode.length}`);
  console.log(`  🏠 Local environment issues (stay private): ${localEnv.length}\n`);

  const actions = [];

  // Handle Frood code issues
  if (froodCode.length > 0) {
    console.log(`\n--- Frood Code Issues (upstream PR candidates) ---`);
    for (const f of froodCode) {
      console.log(`  [${f.id}] ${f.focus}: ${f.detail.substring(0, 80)}...`);
    }

    const froodAction = await askQuestion("What to do with Frood code issues?", [
      { name: "Generate local PR templates (--propose)", value: "template" },
      { name: "Create PR(s) via Community API", value: "pr" },
      { name: "Apply fixes locally to this Frood repo", value: "local" },
      { name: "Skip - review manually later", value: "skip" },
    ]);

    if (froodAction === "pr") {
      actions.push({ type: "pr", findings: froodCode });
    } else if (froodAction === "template") {
      actions.push({ type: "template", findings: froodCode });
    } else if (froodAction === "local") {
      actions.push({ type: "local", findings: froodCode });
    }
  }

  // Handle local environment issues
  if (localEnv.length > 0) {
    console.log(`\n--- Local Environment Issues (private) ---`);
    for (const f of localEnv) {
      console.log(`  [${f.id}] ${f.focus}: ${f.detail.substring(0, 80)}...`);
    }

    const localAction = await askQuestion("What to do with local environment issues?", [
      { name: "Save to local learnings (private)", value: "save" },
      { name: "Generate fix scripts for manual review", value: "scripts" },
      { name: "Apply fixes to local config/files", value: "apply" },
      { name: "Skip - review manually later", value: "skip" },
    ]);

    if (localAction === "apply") {
      actions.push({ type: "apply-local", findings: localEnv });
    } else if (localAction === "scripts") {
      actions.push({ type: "scripts", findings: localEnv });
    } else if (localAction === "save") {
      actions.push({ type: "save-local", findings: localEnv });
    }
  }

  // Execute actions
  for (const action of actions) {
    await executeAction(action, args);
  }
}

async function executeAction(action, args) {
  switch (action.type) {
    case "pr":
      await createCommunityPRs(action.findings, args);
      break;
    case "template":
      await generatePRTemplates(action.findings, args);
      break;
    case "local":
      await applyLocalFixes(action.findings, args, true); // frood repo
      break;
    case "apply-local":
      await applyLocalFixes(action.findings, args, false); // local env
      break;
    case "scripts":
      await generateFixScripts(action.findings, args);
      break;
    case "save-local":
      await saveLocalLearnings(action.findings, args);
      break;
  }
}

async function createCommunityPRs(findings, args) {
  console.log(`\n📤 Creating Community PRs for ${findings.length} Frood code issues...`);

  // Group by area for coherent PRs
  const byArea = {};
  for (const f of findings) {
    if (!byArea[f.area]) byArea[f.area] = [];
    byArea[f.area].push(f);
  }

  for (const [area, areaFindings] of Object.entries(byArea)) {
    const title = `fix: ${area} — ${areaFindings[0].focus}`;
    const body = generatePRBody(area, areaFindings);
    const affectedFiles = areaFindings.flatMap(f => f.evidence).filter(Boolean);

    const proposal = {
      title,
      body,
      affected_files: affectedFiles,
      source: "frood-learn",
      stream: args.stream,
      phase: args.phase,
    };

    const r = await postCommunityPR(proposal);
    if (r.ok) {
      console.log(`  ✅ PR created: ${r.response?.pr_url || r.response?.id}`);
    } else {
      console.log(`  ${r.message}`);
      // Fall back to a local template
      await generatePRTemplates(areaFindings, args);
    }
  }
}

const COMMUNITY_API_MISSING = "community PR API is not deployed in this Frood; proposal not sent";

// POST one proposal to the community PR API. Never throws; never fakes success.
async function postCommunityPR(proposal) {
  const base = (process.env.FROOD_API_URL || "http://localhost:8000").replace(/\/+$/, "");
  try {
    const res = await fetch(`${base}/api/community/pr`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(proposal),
    });
    if (res.status === 404 || res.status === 405) return { ok: false, message: COMMUNITY_API_MISSING };
    if (!res.ok) return { ok: false, message: `community PR API rejected the proposal (HTTP ${res.status}); proposal not sent` };
    let response = null;
    try { response = await res.json(); } catch {}
    return { ok: true, response };
  } catch {
    return { ok: false, message: COMMUNITY_API_MISSING };
  }
}

// --propose: send the Frood-code findings as community PR proposals; exit non-zero on failure.
async function proposeFindings(findings, args) {
  const eligible = findings.filter(f => f.category === "frood-code" && f.source !== "heuristic");
  const pool = eligible.length ? eligible : findings.filter(f => f.source !== "heuristic");
  if (pool.length === 0) {
    console.error("no findings eligible to propose; nothing sent");
    process.exit(1);
  }
  const proposal = {
    title: `learn: ${args.stream} phase ${args.phase}`,
    body: generatePRBody(args.stream, pool.map(f => ({ ...f, stream: args.stream, phase: args.phase }))),
    affected_files: pool.flatMap(f => f.evidence).filter(Boolean),
    source: "frood-learn",
    stream: args.stream,
    phase: args.phase,
  };
  const r = await postCommunityPR(proposal);
  if (!r.ok) {
    console.error(r.message);
    process.exit(1);
  }
  console.log(`PR proposal sent: ${r.response?.pr_url || r.response?.id || "ok"}`);
}

function generatePRBody(area, findings) {
  let body = `## Summary\n`;
  body += `Auto-generated from \`/frood learn ${findings[0].stream} --phase ${findings[0].phase}\`\n\n`;
  body += `## Findings\n\n`;

  for (const f of findings) {
    body += `### ${f.focus}\n`;
    body += `${f.detail}\n\n`;
    body += `**Recommendation:** ${f.recommendation}\n\n`;
    body += `**Evidence:** ${f.evidence.join(", ")}\n\n`;
  }

  body += `## Checklist\n`;
  body += `- [ ] Code changes implemented\n`;
  body += `- [ ] Tests added/updated\n`;
  body += `- [ ] Documentation updated\n`;
  body += `- [ ] Changelog entry added\n`;
  body += `- [ ] All CI checks pass\n`;

  return body;
}

async function generatePRTemplates(findings, args) {
  console.log(`\n📝 Generating PR templates for ${findings.length} findings...`);

  const templateDir = path.join(process.cwd(), ".frood", "pr-templates", args.stream, `phase${args.phase}`);
  fs.mkdirSync(templateDir, { recursive: true });

  const byArea = {};
  for (const f of findings) {
    if (!byArea[f.area]) byArea[f.area] = [];
    byArea[f.area].push(f);
  }

  for (const [area, areaFindings] of Object.entries(byArea)) {
    const filename = `${area}-${Date.now()}.md`;
    const filepath = path.join(templateDir, filename);

    let content = `# PR Proposal: ${area}\n\n`;
    content += `Generated: ${new Date().toISOString()}\n`;
    content += `Stream: ${args.stream}\n`;
    content += `Phase: ${args.phase}\n\n`;
    content += `## Description\n\n`;
    content += `Auto-generated from \`frood-learn ${args.stream} --phase ${args.phase}\`\n\n`;
    content += `## Findings\n\n`;

    for (const f of areaFindings) {
      content += `### ${f.focus}\n`;
      content += `${f.detail}\n\n`;
      content += `**Recommendation:** ${f.recommendation}\n\n`;
      content += `**Evidence:** ${f.evidence.join(", ")}\n\n`;
    }

    content += `## Proposed Changes\n\n`;
    content += `<!-- Describe the specific code changes needed -->\n\n`;
    content += `## Test Plan\n\n`;
    content += `- [ ] Unit tests\n`;
    content += `- [ ] Integration tests\n`;
    content += `- [ ] Manual verification\n\n`;
    content += `## Checklist\n`;
    content += `- [ ] Code changes implemented\n`;
    content += `- [ ] Tests added/updated\n`;
    content += `- [ ] Documentation updated\n`;
    content += `- [ ] Changelog entry added\n`;

    fs.writeFileSync(filepath, content);
    console.log(`  ✅ Template: ${filepath}`);
  }

  console.log(`\n📁 Templates saved to: ${templateDir}`);
  console.log(`   Submit via: frood-learn --propose --phase ${args.phase} --stream ${args.stream}`);
}

async function applyLocalFixes(findings, args, isFroodRepo) {
  console.log(`\n🔧 Applying ${findings.length} fixes locally...`);
  console.log(`   Target: ${isFroodRepo ? "Frood repository" : "local environment"}`);
  console.log(`   ⚠️  This feature requires implementation of specific fix generators`);
  console.log(`   For now, generating fix scripts instead...`);
  await generateFixScripts(findings, args);
}

async function generateFixScripts(findings, args) {
  console.log(`\n📜 Generating fix scripts for ${findings.length} findings...`);

  const scriptDir = path.join(process.cwd(), ".frood", "fix-scripts", args.stream, `phase${args.phase}`);
  fs.mkdirSync(scriptDir, { recursive: true });

  for (const f of findings) {
    const scriptName = `fix-${f.area}-${f.focus.replace(/\s+/g, "-")}.sh`;
    const scriptPath = path.join(scriptDir, scriptName);

    let script = `#!/bin/bash\n`;
    script += `# Fix for: ${f.focus}\n`;
    script += `# Generated: ${new Date().toISOString()}\n`;
    script += `# Stream: ${args.stream}, Phase: ${args.phase}\n\n`;
    script += `set -euo pipefail\n\n`;
    script += `echo "Applying fix: ${f.focus}"\n`;
    script += `echo "Recommendation: ${f.recommendation}"\n\n`;

    // Generate specific fix commands based on finding type
    if (f.area === "async-patterns" && f.focus.includes("blocking")) {
      script += `# Replace blocking I/O with async equivalents\n`;
      script += `# Example: sed -i 's/fs.readFileSync/fs.promises.readFile/g' **/*.js\n`;
    } else if (f.area === "file-ops" && f.focus.includes("hardcoded")) {
      script += `# Replace hardcoded paths with sandbox.resolve_path()\n`;
      script += `# Example: sed -i 's|/home/user/project|sandbox.resolve_path("project")|g' **/*.py\n`;
    } else if (f.area === "sandbox-compliance") {
      script += `# Add sandbox.resolve_path() calls before file operations\n`;
    } else if (f.area === "deployment-drift") {
      script += `# Move localhost/debug config to environment-specific files\n`;
    } else if (f.area === "atlas-adherence") {
      script += `# Update ATLAS.md with best-practices section\n`;
    }

    script += `\necho "Fix script generated. Review and execute manually."\n`;

    fs.writeFileSync(scriptPath, script);
    fs.chmodSync(scriptPath, 0o755);
    console.log(`  ✅ Script: ${scriptPath}`);
  }

  console.log(`\n📁 Scripts saved to: ${scriptDir}`);
  console.log(`   Run with: bash <script-name>.sh`);
}

async function saveLocalLearnings(findings, args) {
  console.log(`\n💾 Saving ${findings.length} local learnings...`);

  const learningsDir = path.join(process.cwd(), ".frood", "learnings", args.stream);
  fs.mkdirSync(learningsDir, { recursive: true });

  const learningFile = path.join(learningsDir, `phase${args.phase}-${Date.now()}.json`);

  const learning = {
    timestamp: new Date().toISOString(),
    stream: args.stream,
    phase: args.phase,
    phaseName: PHASES[args.phase]?.name,
    findings: findings.map(f => ({
      id: f.id,
      area: f.area,
      focus: f.focus,
      detail: f.detail,
      recommendation: f.recommendation,
      evidence: f.evidence,
      category: f.category,
    })),
  };

  fs.writeFileSync(learningFile, JSON.stringify(learning, null, 2));
  console.log(`  ✅ Saved: ${learningFile}`);

  // Also update a local index
  const indexFile = path.join(learningsDir, "index.json");
  let index = { learnings: [] };
  if (fs.existsSync(indexFile)) {
    index = JSON.parse(fs.readFileSync(indexFile, "utf8"));
  }
  index.learnings.push({
    file: path.basename(learningFile),
    timestamp: learning.timestamp,
    phase: args.phase,
    count: findings.length,
  });
  fs.writeFileSync(indexFile, JSON.stringify(index, null, 2));
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function printUsage() {
  console.log(`Usage: frood-learn [<stream|session-id>] [options]`);
  console.log(``);
  console.log(`Options:`);
  console.log(`  --phase <1|2|3|4|5>  Learning phase (default: 1)`);
  console.log(`  --lens <name>         Lens within phase (defaults to phase's default)`);
  console.log(`  --no-mcp              Disable MCP skill; use built-in prompts only`);
  console.log(`  --report <path>       Write JSON findings report to path`);
  console.log(`  --propose             Send findings to the community PR API (exits non-zero if it is not deployed)`);
  console.log(`  --apply, -a           Interactive mode: apply fixes or create PRs`);
  console.log(`  --auto, -A            QUICK: phase 5 + apply + no-mcp (current session)`);
  console.log(`  --auto-detect         Auto-detect stream from current context (default when <stream> omitted)`);
  console.log(`  --session <id>        Explicit OpenCode session ID (for phase 5)`);
  console.log(`  --no-children         Skip collecting/reviewing the stream's child sessions`);
  console.log(`  --help, -h            Show this help`);
  console.log(``);
  console.log(`Phases:`);
  console.log(`  1  communication patterns      lenses: peer-mail, desk-operations, subagent-coordination, handoff-quality`);
  console.log(`  2  error handling & recovery   lenses: error-propagation, retry-recovery, dead-letter-handling, circuit-breakers`);
  console.log(`  3  coordination & sync         lenses: process-coordination, cross-harness-sync, handoff-quality, process-metrics`);
  console.log(`  4  work logic & code quality   lenses: async-patterns, file-ops, sandbox-compliance, deployment-drift, atlas-adherence`);
  console.log(`  5  OpenCode session analysis   lenses: session-summary, error-patterns, tool-efficiency, frood-code-changes, local-code-changes, session-length`);
  console.log(``);
  console.log(`Quick start (current session):`);
  console.log(`  frood-learn -a          # analyze current session, interactive, no MCP`);
  console.log(`  frood-learn --auto      # same as -a`);
  console.log(``);
  console.log(`Examples:`);
  console.log(`  frood-learn gsuite --phase 2`);
  console.log(`  frood-learn --phase 2 --no-mcp           # auto-detect from current session/repo`);
  console.log(`  frood-learn frood-cmd-m4 --phase 4 --lens async-patterns`);
  console.log(`  frood-learn frood-cmd-m4 --phase 4 --apply`);
  console.log(`  frood-learn ses_df5f6f1f9ffeNgND1IUBfkyxXG --phase 5  # analyze OpenCode session`);
  console.log(`  frood-learn --phase 5 --session ses_df5f6f1f9ffeNgND1IUBfkyxXG`);
  console.log(`  frood-learn --help`);
  process.exit(0);
}

// ---------------------------------------------------------------------------
// Main entry
// ---------------------------------------------------------------------------

async function main() {
  const args = parseArgs(process.argv.slice(2));

  // Quick mode (-a/--auto): phase 5 + apply + no-mcp (MUST BE FIRST)
  if (args.quick) {
    args.phase = 5;
    args.apply = true;
    args.noMcp = true;
  }

  // Default phase to 1 if not specified
  if (args.phase === null) args.phase = 1;

  // If first argument looks like a session ID (starts with ses_) and no explicit --phase, default to phase 5
  if (args.stream && args.stream.startsWith("ses_") && !process.argv.includes("--phase")) {
    console.log("🔍 Detected session ID, using phase 5 (OpenCode session analysis)");
    args.phase = 5;
  }

  if (args.phase === null || !PHASES[args.phase]) {
    console.error(`Error: --phase must be 1, 2, 3, 4, or 5. Got: ${args.phase ?? "missing"}`);
    process.exit(2);
  }

  // Auto-detect stream if not provided (for phases 1-4)
  if (!args.stream && args.phase !== 5) {
    console.log("🔍 Auto-detecting stream from current context...");
    args.stream = autoDetectStream(args);
    if (!args.stream) {
      console.error("Error: Could not auto-detect stream. Please specify <stream> explicitly or run with --auto-detect to see candidates.");
      console.error("Available streams:");
      listAvailableStreams();
      process.exit(2);
    }
    console.log(`   Detected: ${args.stream}`);
  }

  // For phase 5, auto-detect current OpenCode session if not provided
  if (args.phase === 5 && !args.stream && !args.sessionId) {
    const envSessionId = process.env.OPENCODE_SESSION_ID;
    if (envSessionId) {
      if (!args.quick) console.log(`🔍 Auto-detected current session: ${envSessionId}`);
      args.sessionId = envSessionId;
    } else {
      console.error("Error: Phase 5 requires --session <session-id> or <session-id> as argument");
      console.error("       (OPENCODE_SESSION_ID env var not found)");
      process.exit(2);
    }
  }

  // For phase 5, use sessionId from stream arg if provided
  if (args.phase === 5 && args.stream && args.stream.startsWith("ses_")) {
    args.sessionId = args.sessionId || args.stream;
  }

  // For phase 5, use sessionId as stream identifier for report
  const reportStream = args.phase === 5 ? (args.sessionId || args.stream) : args.stream;

  const phaseDef = PHASES[args.phase];
  if (args.lens && !phaseDef.lenses.includes(args.lens)) {
    console.error(`Error: lens "${args.lens}" not valid for phase ${args.phase}. Valid: ${phaseDef.lenses.join(", ")}`);
    process.exit(2);
  }

  // Check Frood MCP availability
  const mcpAvailable = isMcpAvailable();
  const mcpResult = args.noMcp
    ? { used: false, reason: "--no-mcp set; using built-in prompts" }
    : mcpAvailable
      ? await invokeMcpProcessReview(args.stream)
      : { used: false, reason: "Frood MCP not configured (.mcp.json missing frood server)" };

  // Select appropriate findings generator based on phase
  let findings;
  if (args.phase === 1) {
    findings = analyzeCommunicationPatterns(args.stream, args);
  } else if (args.phase === 2) {
    findings = analyzeErrorHandlingPatterns(args.stream, args);
  } else if (args.phase === 3) {
    findings = analyzeCoordinationPatterns(args.stream, args);
  } else if (args.phase === 4) {
    findings = analyzeWorkLogicPatterns(args.stream, args);
  } else if (args.phase === 5) {
    // Phase 5: analyze OpenCode session directly
    const sessionId = args.sessionId || args.stream; // stream arg holds session ID for phase 5
    if (!sessionId) {
      console.error("Error: Phase 5 requires --session <session-id> or <session-id> as argument");
      process.exit(2);
    }
    console.log(`📖 Reading OpenCode session: ${sessionId}`);
    const session = readOpenCodeSession(sessionId);
    if (!session) {
      console.error(`Error: Session ${sessionId} not found in OpenCode database`);
      process.exit(2);
    }
    findings = analyzeOpenCodeSession(session);
  } else {
    console.error(`Error: phase ${args.phase} not implemented`);
    process.exit(2);
  }

  // Filter by lens if specified
  if (args.lens) {
    findings = findings.filter(f => f.lens === args.lens);
  }

  // Meta-review exclusion enforcement
  const before = findings.length;
  const filteredFindings = findings.filter((f) => {
    const haystack = JSON.stringify(f).toLowerCase();
    return !META_REVIEW_EXCLUSION.some((hook) => haystack.includes(hook.toLowerCase()));
  });
  if (filteredFindings.length < before) {
    console.log(`[meta-review] Dropped ${before - filteredFindings.length} findings touching learning hooks`);
  }

  // Categorize findings: Frood code vs Local environment
  const categorizedFindings = categorizeFindings(filteredFindings);

  // Children: collect & review every child session of this stream through the
  // phase-5 lenses. Only on stream runs (phases 1-4); --session (phase 5) is
  // unchanged and --no-children skips this entirely.
  let children = [];
  const isStreamRun = Boolean(args.stream) && !args.stream.startsWith("ses_") && args.phase !== 5;
  if (isStreamRun && !args.noChildren) {
    for (const child of collectChildren(args.stream)) {
      children.push(reviewChild(child, args.stream));
    }
  }

  // Build and write report (include category)
  const report = {
    schema: 1,
    stream: args.stream,
    phase: args.phase,
    phaseName: PHASES[args.phase].name,
    lens: args.lens || PHASES[args.phase].defaultLens,
    lensesAvailable: PHASES[args.phase].lenses,
    timestamp: new Date().toISOString(),
    findings: categorizedFindings.map((f, i) => ({
      id: i + 1,
      area: f.area,
      focus: f.focus,
      status: f.status,
      detail: f.detail,
      recommendation: f.recommendation,
      evidence: f.evidence,
      source: f.source,
      category: f.category,
    })),
    children: isStreamRun && !args.noChildren
      ? children.map((c) => ({
        session: c.session,
        harness: c.harness,
        role: c.role,
        model: c.model,
        status: c.status,
        note: c.note,
        transcriptCopied: c.transcriptCopied,
        findings: c.findings,
      }))
      : undefined,
    mcp: { available: isMcpAvailable(), ...mcpResult },
    metaReviewExclusion: META_REVIEW_EXCLUSION,
  };

  const reportPath = args.report || path.join(process.cwd(), ".opencode", "reports", `frood-learn-${reportStream}-phase${args.phase}.json`);
  writeReport(report, reportPath);

  printSummary(args, mcpResult, categorizedFindings);

  if (args.propose) {
    await proposeFindings(categorizedFindings, args);
  }

  // Interactive apply mode
  if (args.apply) {
    await interactiveApply(args, categorizedFindings);
  }
}

main().catch(e => {
  console.error("frood-learn failed:", e.message);
  process.exit(1);
});
