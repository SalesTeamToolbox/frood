# Plan — frood-learn-children

## Handoff

- Done:      all 6 modules merged to main (ff) at 7f4fdf00 (79c293ab, 9dad012f, 7f4fdf00). 4 review rounds:
             r1 desk critic APPROVED; r2 CC critic CHANGES_REQUESTED (CC reader parsed an invented format);
             r3 orchestrator real-shape check (subagent id = parent sessionId, hard-coded role, file/shell lens
             inputs); r4 CC critic APPROVED. make check 2161 passed / 2 skipped; handoff tests 58/0. Commands installed;
             --check clean. Worktree removed.
- Next:      nothing on this ticket. Follow-ups: 4 minor findings in findings-r4.md; desk bugs (see report).
- Waiting:   owner: `board close frood-learn-children --by human --sha 7f4fdf00` (board stayed `working`).

## Goal

`/frood-learn <stream>` reviews the stream's child sessions by default: OpenCode workers/critics (ses_ ids in the
stream events), Claude Code subagents (`<parent-session>/subagents/agent-*.jsonl`) and nested Claude Code sessions
(ids recorded on the stream). Each child gets the phase-5 lenses; findings merge into one report tagged with role,
harness, model and session. Full spec: the Mandate.

## Backlog (build order — one ticket, one worker run, modules are commits inside it)

1. **Child recording** — `handoff.mjs child` subcommand + `child` event kind; `desk.mjs` events reader still quiet
   on it; one line each in `frood-orchestrator.md` and `frood-ticket.md` to call it after `start_session`.
   Test: `orchestrator/tests/handoff.test.mjs`.
2. **Child discovery** — in `bin/frood-learn.mjs`, collect children from `<stream>.events.jsonl` (`ses_` ids, `child`
   events, orchestrator session id → its `subagents/` folder). Missing transcripts → `status: "missing"`.
3. **Claude Code JSONL reader** — map a CC transcript onto the inputs the phase-5 lenses already take from
   `opencode.db` (turns, tool calls, errors, files, prompts, timestamps, model).
4. **Per-child review + merged report** — run phase-5 lenses per child, tag findings, add `children` array;
   `--no-children` flag; `--session` unchanged.
5. **Retention** — option (b) preferred: copy each child transcript read to
   `~/.config/orchestrator/learnings/<stream>/children/` (never into a repo); document `cleanupPeriodDays` in
   `orchestrator/commands/frood-learn.md`.
6. **Docs** — `orchestrator/commands/frood-learn.md`: default child review, `--no-children`, report fields.

## Hard constraints

- Tests use fixture transcripts under a temp HOME only; never the real `~/.claude/projects` or `opencode.db`.
- Never touch `~/Vault` / `~/.vault`. Transcript copies stay outside every repo (public-guard; secrets).
- Process safety rule from the Mandate applies to every test and tool run.
- After editing `orchestrator/commands/*.md`, run `node orchestrator/bin/install.mjs` from the Frood root
  (`--check` for drift) so the installed commands match.

## Pass bars

- `make check` green.
- `timeout 120 node --test orchestrator/tests/handoff.test.mjs` green.
- New tests listed in the Mandate's Pass bars.
- Manual: `node bin/frood-learn.mjs <real stream with ses_ events> --phase 1 --no-mcp` lists its children.

## Gates

`.opencode/board/adapter.json`: `make check`. No EGM, no senior (no path in scope is guarded). Critic loop as usual.
