---
description: Run a process-aware learning review (/frood learn) — analyze real session artifacts
argument-hint: "<stream> [--phase <n>] [--lens <name>] [--no-mcp] [--report <path>]"
---

# /frood learn

Run a structured learning review of a stream by analyzing **real session artifacts**:
- Desk daemon logs (verdict-failed, worker-timeout, worker-error, etc.)
- Worker/critic receipts (token usage, timing, errors)
- Stream handoffs (waiting fields, next pointers, staleness)
- Peer-mail sync (session ID drift, ack timeouts)
- Critic rounds efficiency
- Board gate failures

## Run

```bash
node {{ORCH_REPO}}/../bin/frood-learn.mjs $ARGUMENTS
```

Run the command above with the user's arguments and relay the summary. Findings
tagged `source: "session-data"` are computed from the artifacts actually read;
`source: "heuristic"` findings are pattern advice with no measured numbers.

## Arguments

- `<stream|session-id>` — the stream/ticket slug or OpenCode session ID to review (required unless `--help`)
- `--phase <n>` — learning phase:
  - `1` — **communication patterns** (lenses: `peer-mail`, `desk-operations`, `subagent-coordination`, `handoff-quality`)
  - `2` — **error handling & recovery** (lenses: `error-propagation`, `retry-recovery`, `dead-letter-handling`, `circuit-breakers`)
  - `3` — **coordination & sync** (lenses: `process-coordination`, `cross-harness-sync`, `handoff-quality`, `process-metrics`)
  - `4` — **work logic & code quality** (lenses: `async-patterns`, `file-ops`, `sandbox-compliance`, `deployment-drift`, `atlas-adherence`)
  - `5` — **OpenCode session analysis** (lenses: `session-summary`, `error-patterns`, `tool-efficiency`, `frood-code-changes`, `local-code-changes`, `session-length`)
- `--lens <name>` — lens within the phase (defaults to the phase's first lens)
- `--no-mcp` — disable MCP skill invocation; use built-in prompts only
- `--report <path>` — write the JSON findings report here
- `--propose` — send the findings as a community PR proposal (needs the community PR API; exits non-zero when it is not deployed)
- `--apply` — **interactive mode**: categorize findings and apply fixes or create PRs
- `--session <id>` — explicit OpenCode session ID (for phase 5)
- `--no-children` — skip collecting and reviewing the stream's child sessions (output matches the default run without a children section)
- `--help` / `-h` — show usage

## Phase 1 — Communication Patterns

| Lens | Focus | Data Source |
|---|---|---|
| `peer-mail` | Message latency, round-trip times | Stream events with `latency_ms` |
| `desk-operations` | Daemon stability, restarts | Desk daemon logs |
| `subagent-coordination` | Worker-critic round efficiency | Critic findings, worker receipts |
| `handoff-quality` | Stream handoff completeness | Stream state (`waiting`, `next`) |

## Phase 2 — Error Handling & Recovery

| Lens | Focus | Data Source |
|---|---|---|
| `error-propagation` | Verdict-failed, worker-error, critic-failed, no-ticket | Desk daemon logs |
| `retry-recovery` | Worker-timeout, run-dead, receipt analysis; per run: start delay (slot/server wait), agent activity after the kill (with git writes), tool calls over 5 min | Desk daemon logs, worker receipts, `~/.local/share/opencode/opencode.db` (read-only, joined by each run's session id) |
| `dead-letter-handling` | Worker-blocked patterns | Desk daemon logs |
| `circuit-breakers` | Review-unlinked, agent-senior, critic rounds | Desk daemon logs, critic findings |

## Phase 3 — Coordination & Sync

| Lens | Focus | Data Source |
|---|---|---|
| `process-coordination` | Subagent orchestration depth | Worker receipts |
| `cross-harness-sync` | Claude Code ↔ OpenCode state sync | Peer-mail events |
| `handoff-quality` | Stream handoff fidelity | Stream state (`waiting`, `next`) |
| `process-metrics` | End-to-end cycle time (with start delays), critic efficiency | Worker receipts, orchestrator receipts, opencode.db |

## Phase 4 — Work Logic & Code Quality

| Lens | Focus | Data Source |
|---|---|---|
| `async-patterns` | Blocking I/O, missing await, async function usage | Worker diffs (git show) |
| `file-ops` | Heredoc usage, hardcoded paths, temp files | Worker diffs |
| `sandbox-compliance` | Missing sandbox.resolve_path(), sandbox disabled, path traversal | Worker diffs |
| `deployment-drift` | Localhost binding, debug mode, console.log vs logging | Worker diffs + CLAUDE.md |
| `atlas-adherence` | ATLAS best-practices section, pitfalls archive, convention violations | ATLAS.md, CLAUDE.md, pitfalls-archive.md |

## Phase 5 — OpenCode Session Analysis

| Lens | Focus | Data Source |
|---|---|---|
| `session-summary` | Agent turns, commands, files, errors, prompts | OpenCode session messages |
| `error-patterns` | Shell/background/assistant errors, HTTP codes | Session message text |
| `tool-efficiency` | Tools used (deploy, prisma, shell, etc.) | Session message types |
| `frood-code-changes` | Frood repo file modifications | File paths in snapshots |
| `local-code-changes` | Local/project file modifications | File paths in snapshots |
| `session-length` | Session duration, iteration patterns | Time spans, user prompts |
| `blocked-actions` | Claude Code tool calls denied by the permission classifier; board/handoff writes are severity high | Claude Code child transcript (session-data) |
| `board-integrity` | Stream ticket merged to main with no recorded rounds/gates/signoffs | Stream run dirs + repo board tickets |

## Child sessions

A default run `/frood-learn <stream>` (phases 1-4, without `--no-children`) also collects the
stream's child sessions and reviews each through the phase-5 lenses:

- OpenCode workers/critics: the `ses_...` ids carried on stream events (written by `oc-worker`).
- Claude Code subagents: `agent-*.jsonl` under the orchestrator session's `subagents/` folder (the
  orchestrator session id is the stream's `held_session` / `session`).
- Nested Claude Code sessions: ids recorded on the stream via `handoff.mjs child`.
- Claimants (sessions that held the stream lease), role `orchestrator`: from `claim` events written to
  `<stream>.events.jsonl` by `handoff.mjs claim`, from the stream's current `held_session` / `session`,
  and — for streams that predate claim events — from the board ticket with the same id as the stream
  (`<stream.repo>/.opencode/board/tickets/<id>.json`), `history[]` entries with `cmd` `claim` or `attach`
  and a `by` that is a UUID. A CC claimant's own transcript is reviewed and its `subagents/` are collected;
  an OpenCode claimant goes through the OpenCode reader.

Each child finding is tagged with `role` (worker / critic / scout / senior / nested / orchestrator),
`harness` (opencode / claude-code), `model` when known, and `session` id. A child whose transcript is
missing or aged out is listed with `status: "missing"` and a one-line note; the run never crashes on it.
A `child` event whose session starts with `local_` (the desktop app's id, not a transcript id) is mapped
to its transcript id through the app's session metadata (`cliSessionId`); if that metadata is gone it is listed
as `missing` with the reason. Nested sessions record themselves with `$CLAUDE_CODE_SESSION_ID` (`/frood-next`).
When a session is both a claimant and a `child` event, one child is kept and role `nested` wins over
`orchestrator`. The report gains a top-level `children` array (omitted with `--no-children`).
Archived sessions are still reviewed: archiving keeps the transcript (`~/.claude/projects/…`), which is what
`/frood-learn` reads. Claude Code deletes transcripts older than `cleanupPeriodDays` either way.

On Claude Code children, `readClaudeCodeJSONL` also scans the transcript for tool calls denied by the
permission classifier. Each denial becomes a `blocked-actions` finding (area: `permissions`): board/handoff
writes (`board.mjs round|signoff|gates|ready|close|claim`, `handoff.mjs write|note|child|done`) are
severity `high` with the consequence (the step was not recorded, so the desk cannot merge; the owner must)
and the fix (allow the command in the session's permission settings, or run it from the parent session);
every other denial is severity `medium`. A `custom-title` line sets the child's session title (last wins);
a `local_` child with no custom title falls back to the desktop app metadata `title`.

At stream level, the `board-integrity` finding fires when a ticket on the stream has its branch merged to
local `main` but its board record has empty `rounds`, `gates` and `signoffs`. If a child review found a
denied board write, the finding links to that session.

## Retention

Claude Code deletes transcripts after `cleanupPeriodDays` (default ~30; unset on this machine). To keep
child transcripts available beyond that, `frood-learn` copies each **Claude Code** child transcript it reads
(a nested-session `.jsonl` or a subagent `agent-*.jsonl`) to
`~/.config/orchestrator/learnings/<stream>/children/` (outside every repo, so transcripts that can hold
secrets never reach `.opencode/reports` and a commit). OpenCode transcripts live in the single shared
`~/.local/share/opencode/opencode.db`, which `frood-learn` never copies: it is shared by every OpenCode
session, so copying it would leak other sessions' transcripts, and opencode.db retention is OpenCode's own.
Alternatively, raise `cleanupPeriodDays` in your Claude Code settings; document the chosen value here.

## Meta-review exclusion (enforced)

Learning hooks are never in scope for any phase:

- `learning-engine.py`
- `knowledge-learn.py`
- `knowledge-learn-worker.py`

Any finding touching these files is dropped from the report.

## MCP

The CLI attempts the `frood_process_review` MCP skill when available and
`--no-mcp` is not set. When MCP is unavailable (or `--no-mcp` is given), it
falls back to built-in prompts and records the fallback in the report.

## Examples

```
/frood learn gsuite --phase 2
/frood learn gsuite --phase 2 --lens retry-recovery --no-mcp
/frood learn video-studio-m4 --phase 3 --lens process-metrics
/frood learn atlas-wiring --phase 1 --lens desk-operations --report /tmp/report.json
/frood learn frood-cmd-m4 --phase 4 --lens async-patterns
/frood learn frood-cmd-m4 --phase 4 --lens sandbox-compliance --no-mcp
/frood learn frood-cmd-m4 --phase 4 --lens atlas-adherence --report /tmp/atlas-report.json

# Interactive apply mode (categorizes findings, creates PRs or local fixes)
/frood learn gsuite --phase 2 --apply
/frood learn frood-cmd-m4 --phase 4 --apply
/frood learn frood-cmd-m4 --phase 4 --lens atlas-adherence --apply

# OpenCode session analysis (phase 5)
/frood learn ses_df5f6f1f9ffeNgND1IUBfkyxXG --phase 5
/frood learn --phase 5 --session ses_df5f6f1f9ffeNgND1IUBfkyxXG
/frood learn ses_df5f6f1f9ffeNgND1IUBfkyxXG --phase 5 --lens error-patterns --apply

/frood learn --help
```

## Output

A JSON findings report is written (default:
`.opencode/reports/frood-learn-<stream>-phase<n>.json`) and a human summary is
printed to stdout. The report includes the phase, lens, findings (each tagged
with source: `mcp:frood_process_review` or `builtin`), the MCP
availability/fallback reason, the enforced meta-review exclusion list, and — on
stream runs — a `children` array with one entry per child session (each tagged
with `role`, `harness`, `model`, `session` and `status`).

## Cross-harness compatibility

Same command syntax works in both Claude Code and OpenCode.
