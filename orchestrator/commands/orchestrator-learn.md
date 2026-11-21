---
description: Post-session learning review — spawns subagents to analyze a completed orchestrator session and identify improvements to the process and subagent behavior
argument-hint: "[stream-name | ticket-slug]"  # cc-only
---

Review a completed orchestrator session (or specific ticket) to find patterns of waste, loops, misconfigurations, and missed shortcuts. The learnings feed back into future mandates, routing, and agent prompts.

This command is run **after** a session ends and a handoff is made for `/next`. It reads the session's artifacts and spawns focused subagents to produce a learning report.

## Frood Integration (Optional)

When the **Frood MCP server** is configured and running (`.mcp.json` + `enabledMcpjsonServers`), this command can leverage Frood's tooling layer:

| Frood Tool | Use in `/orchestrator-learn` |
|------------|------------------------------|
| `memory` | Store/retrieve learnings across sessions; project-scoped memory for each stream |
| `knowledge` | Query project-specific knowledge (conventions, past decisions, server configs) |
| `context_assembler` | Smart retrieval of relevant context from artifacts + memory |
| `behaviour` | Track agent behavior patterns across sessions |
| `node_sync` | Sync learnings across machines/nodes |
| `summarizer` | Summarize large artifact sets before subagent analysis |

**Frood Skills as MCP Prompts** (43 skills available):
- `frood_memory` — Manage persistent memory (recall, store, log, forget)
- `frood_code_review` — Structured code review patterns
- `frood_debugging` — Systematic debugging methodology
- `frood_data_analysis` — Analyze metrics and patterns
- `frood_security_audit` — Security-focused review
- `frood_refactoring` — Refactoring patterns
- `frood_git_workflow` — Git best practices
- `frood_project_planning` — Planning and estimation

To use Frood skills in this command, invoke via MCP prompt: `frood_<skill_name>` with relevant context.

## Usage

```
/orchestrator-learn <stream-name>        # review a specific workstream
/orchestrator-learn <ticket-slug>        # review a specific ticket's full lifecycle
/orchestrator-learn                      # list recent streams/tickets and ask which to review
```

## Data Sources (read automatically)

| Source | Location | What it tells |
|--------|----------|---------------|
| Worker reports | `.opencode/reports/<ticket>/report.md` | What the worker did, files touched, commands run |
| Critic findings | `.opencode/reports/<ticket>/findings-r<N>.md` | What the critic caught, round count, verdict |
| Senior review | `.opencode/reports/<ticket>/senior.md` | Final blockers, if any |
| Orchestrator receipt | `.opencode/reports/<ticket>/orchestrator-receipt.md` | End-to-end summary, re-pooling, test results |
| Worker receipts | `.opencode/reports/<ticket>/worker-r<N>.md.receipt.json` | Model, tokens, cost, duration, fallbacks |
| Handoff stream | `~/.config/orchestrator/streams/<name>.json` + `.events.jsonl` | Session boundaries, desk events, escalations |
| Board ticket | `.opencode/board/tickets/<id>.json` | Ticket lifecycle, EGM status, guarded paths |
| oc-worker active | `node bin/oc-worker.mjs active --json` | Currently running/previous runs with timing |

### Frood-Enhanced Sources (when MCP server available)

| Source | Tool | What it tells |
|--------|------|---------------|
| Project memory | `frood_memory` (search/recall) | Past learnings, decisions, conventions, server configs |
| Knowledge base | `frood_knowledge` (query) | Project-specific facts, APIs, configs, past incidents |
| Context assembly | `frood_context_assembler` | Smart context retrieval from artifacts + memory |
| Behavior log | `frood_behaviour` | Historical agent behavior patterns across sessions |

## Subagents Spawned

The command spawns **3 parallel subagents**, each with a distinct lens:

### 1. `pattern-detector` (scout model)
**Focus:** Recurring anti-patterns across the session
- Agent loops: same error → same fix attempt → repeat (e.g. wrong connection method tried 3×)
- Tool misuse: `grep` where `search_symbols` would work; `bash` where `read` suffices
- Re-derivation: facts re-discovered that were in handoff/peer-mail/atlas
- Config drift: routing rule says X, but worker used Y; EGM waived but trigger existed
- Missed shortcuts: existing helper/script/tool not used (mail server, `board.mjs`, `wt-finish`)

### 2. `efficiency-analyzer` (worker model)
**Focus:** Token/time waste and process friction
- Round count: tickets that took 3 critic rounds (what was missed in round 1?)
- Model fallbacks: how many re-pools, were they necessary, did free-first hurt?
- Idle/stalled time: `oc-worker active` shows `IDLE`, `STALE`, `OVERDUE` runs
- Test re-runs: mandates that re-ran full suite unnecessarily
- Handoff overhead: sessions that re-read context already in plan file

### 3. `tool-usage-reviewer` (critic model)
**Focus:** Whether agents used the right tools for the job
- jcodemunch vs Grep: symbol searches done with text grep
- Board CLI vs manual git: tickets moved by hand instead of `board.mjs`
- Peer-mail vs chat: cross-session facts sent via peer-mail but re-asked
- Worktree hygiene: `wt-finish` not called, junctions left behind
- Atlas updates: map entries missing for changed symbols/routes

## Output

A learning report written to:
```
.opencode/reports/<ticket>/learn-<timestamp>.md
~/.config/orchestrator/learnings/<stream-or-ticket>-<timestamp>.md
```

The report contains:

```
# Orchestrator Learning Report — <stream/ticket> — <date>

## Executive Summary
<2-3 sentences: what was the biggest waste, what would save the most tokens/time>

## Pattern Detector Findings
- [ ] Loop detected: <description> — occurred <N> times — <recommendation>
- [ ] Re-derivation: <fact> was in <source> but re-discovered at <step>
- [ ] Config drift: <rule> said <X> but <agent> did <Y>
- [ ] Missed shortcut: <tool/script> exists for <task> but not used

## Efficiency Analyzer Findings
- Round efficiency: <ticket> took <N> critic rounds; round 1 missed <X>
- Re-pooling: <N> fallbacks; <necessary|avoidable> — <reason>
- Timing: worker-r1 took <X>m (expected <Y>m); idle <Z>m
- Test waste: full suite re-run at <step> when <targeted> would suffice

## Tool Usage Reviewer Findings
- jcodemunch: <N> symbol searches done via grep; <time> lost
- Board: <N> manual ticket moves; `board.mjs <cmd>` would be atomic
- Peer-mail: <N> facts sent via mail but re-asked in next session
- Worktree: <N> junctions not cleaned; `wt-finish` not run
- Atlas: <N> changed symbols without map update

## Actionable Improvements (Prioritized)
1. **High impact, low effort** — e.g. "Add mail server connection example to worker prompt"
2. **High impact, medium effort** — e.g. "Update routing rule to prefer model X for task Y"
3. **Process change** — e.g. "Require atlas update in mandate template"

## Learnings for Future Mandates
- Add to worker prompt: "<specific instruction>"
- Add to critic prompt: "<specific check>"
- Update routing: "<model> for <role> when <condition>"
- New skill/convention: "<name> — <purpose>"

## Artifacts Referenced
- Worker reports: <paths>
- Critic findings: <paths>
- Senior review: <path>
- Receipts: <paths>
- Stream events: <path>
```

## Implementation

```bash
# 1. Resolve the target (stream or ticket) to a set of report directories
# 2. Collect all artifact paths
# 3. If Frood MCP available: use context_assembler to pre-fetch relevant context
# 4. Spawn 3 subagents in parallel with the collected context
# 5. Wait for all three, merge their outputs into the report
# 6. If Frood MCP available: store learnings via frood_memory (project-scoped)
# 7. Write report to both locations
# 8. Print summary to user with top 3 actionable items
```

### With Frood Skills (Optional Enhancement)

When Frood MCP is available, the subagents can invoke relevant skills:

```bash
# Pattern detector uses debugging skill for loop analysis
frood_debugging --task_type "pattern_analysis" --context "<artifact_summary>"

# Efficiency analyzer uses data_analysis skill for metrics
frood_data_analysis --task_type "efficiency_metrics" --context "<metrics_data>"

# Tool usage reviewer uses code_review skill for tool audit
frood_code_review --task_type "tool_usage_audit" --context "<tool_usage_data>"
```

The orchestrator session running this command would invoke these via MCP prompts.

## Example

```
/orchestrator-learn video-studio-m4
# → reviews the video-studio-m4 workstream, all its tickets

/orchestrator-learn m6a-desk-minors
# → reviews just that ticket's full lifecycle

/orchestrator-learn
# → lists recent streams/tickets and asks which to review
```

## Notes

- This command **does not modify** any orchestrator config, routing, or prompts directly. It produces a report that the owner (or a future `/model-router-refresh` / prompt edit session) acts on.
- Run it in a **fresh session** (or after `/clear`) so the subagents have clean context — they only need the artifact files, not the session history.
- The subagents are read-only (scout/worker/critic roles); they never edit files.
- Learnings accumulate in `~/.config/orchestrator/learnings/` — future `/orchestrator` sessions can read this directory via a scout to avoid repeating known mistakes.
- **Frood MCP is optional** — the command works fully without it. When available, it enhances context retrieval, memory persistence, and skill invocation.
- To enable Frood: ensure `.mcp.json` exists in project root with `frood` server config, and `enabledMcpjsonServers: ["frood"]` in `.claude/settings.local.json`.
