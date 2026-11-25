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
availability/fallback reason, and the enforced meta-review exclusion list.

## Cross-harness compatibility

Same command syntax works in both Claude Code and OpenCode.
