# Plan: nested sessions in the Claude desktop sidebar, as the Frood standard

## Handoff

- Done (2026-11-24): M1 merged fast-forward to local `main` (c92cc27e, d766499a, 17042135) and installed;
  `install.mjs --check` clean. Worker: worker-nvidia (Nemotron), 1 run. Critic: Sonnet, CHANGES_REQUESTED then
  APPROVED. Reports: `.opencode/reports/nested-sessions/`.
- Gaps: board gate `make check` not run (docs-only, no Python touched). The ticket stays `working` with the
  critic's sign-off: releasing it needs the owner (`--by human`). `main` is not pushed, so branch
  `worktree/nested-sessions` is still there.
- Orchestrator tests: 455/458; the failures are on `main` already (desk status ×2, oc-worker orphan grandchild, flaky).
- Follow-up done (9ba716c0): frood-handback.md — CC→OC keeps "new tab" (OpenCode has no session tool); OC→CC now lets the live Claude Code session continue in place. Stream finished.

## What Volnova does (evidence, 2026-11-24)

- Volnova's orchestrator session *Residential/commercial submission process review* (`local_990de9c1…`) started
  every module as its own session with the desktop app's `start_session` tool: M2, M3, M4, M5 each have
  `parentSessionId = local_990de9c1…` (`get_session`), a short `name` (`m2-lender-once`, `m5-commercial-states`)
  and a plain-language title (`M2: residential lender asked once`). The sidebar draws them nested under the parent.
- The parent stays the one place the owner talks to: when a child ends a turn the app wakes the parent with a
  note, and the parent reports it in one line (`M5 is running in …; I'll pass on its report`).
- STT does the same (`STT resume` → `Mail import H1 t4c/t5/t6`, `Support-desk mailbox SSRF fix`).
- Frood's own sessions do not: `Frood-next parallel dispatch` (×2), `Frood-next OCW orphan test`,
  `Frood-next desk cleanups` have no `startedBy` — opened by hand in a new tab, as the commands tell the owner.
- Nothing in Volnova's repo causes this (no `start_session`/sidebar text in its CLAUDE.md or `.claude/`). It is
  the Volnova session choosing the app's tool over the Frood command's "Fresh tab" advice. So the standard has to
  live in the Frood commands, which install globally and so apply in every repo Frood runs in.

## Why it nests and why ours does not

Nesting = `parentSessionId`, set only when a live session calls `start_session`. A tab opened by hand, a
`claude://code/new?...` URL (orphan-notice) or a terminal `claude` is top level. Sidebar groups are not involved
(the owner has none; the Sessions section groups by project).

## Decisions (recommended defaults)

1. **Module boundary (Claude desktop):** the options become
   - *Start the next module in a nested session (Recommended)* — this session calls `start_session`
     (`initiation: user_asked`, `context: fresh`, `prompt: /frood-next <stream>` + a short brief, `background`:
     goal, plan path, what landed), stays the owner's thread and reports the child's notes;
   - *Continue in this session*; *Stop here*. "Fresh tab" goes (it is how sessions end up un-nested).
2. **Parallel dispatch:** each ticket session is started with `start_session` from the dispatching session —
   never "by hand" — then recorded with `board.mjs session <ticket> --session <local_… id>`.
3. **One level only:** a session started by a parent does not start the next module itself; at its boundary it
   reports and stops, and the parent starts the next one. Keeps the sidebar a flat list under one parent (as in
   Volnova). If the owner talks to the child directly and asks it to go on, it continues in place.
4. **Names:** title `<Module>: <plain outcome>` (under 60 chars, a stranger can read it); `name` = stream or ticket
   slug cut to 24 chars.
5. **`/frood-ticket`:** in the desktop app it offers to start the session now, nested (a `start_session` card),
   instead of ending with "Run /frood-next in a fresh session". Outside the app the old line stays.
6. **Unchanged:** OpenCode (no desktop tool; `oc-only` text stays); terminal `claude`; the orphan notice
   (`claude://`) — the stream's parent is dead by definition there, so top level is right.

## Backlog (build order)

### M1 — command text (one module, docs-only)

Files (all `orchestrator/`): `commands/frood-orchestrator.md` (module-boundary options, Dispatch in parallel —
`cc-only` blocks), `commands/frood-next.md` (opening line; nested-child boundary rule), `commands/frood-ticket.md`
(closing line), `README.md` (one line on the standard). Then `node orchestrator/bin/install.mjs` from the Frood root.

Blast radius: these are prompt text; callers are every session that runs the commands (all repos). Behaviour
change = how the next session is started; board, streams, desk, train unchanged. `orchestrator-handoff.js` title hook
still names hand-opened tabs — unchanged.

Pass bars:
- `node orchestrator/bin/install.mjs --check` clean (no drift, routing lint passes).
- `node --test orchestrator/tests/` green (install + atlas-wiring tests read these files).
- `grep -rn "Fresh tab" orchestrator/commands` empty in `cc-only`/shared text; `oc-only` text untouched.
- Rendered CC copy in `~/.claude/commands/` shows the new options; OpenCode copy does not.

EGM: **waived** — no new module/dir, no data model or stored format, no route/CLI flag/config format change,
1 top-level dir (`orchestrator/`), no security/tenancy/money. Prompt text in existing command files.
Handling: direct (≤4 files, docs-only, low blast radius) — single worker, orchestrator re-runs the gates.

### Follow-up (not in M1)

- Orphan notice could peer-mail the stream's last live parent to start the child nested instead of opening a
  top-level `claude://` session, when that parent is still alive.

## Gates

`node orchestrator/bin/install.mjs --check` · `node --test orchestrator/tests/` · `make lint` not affected (no Python).
