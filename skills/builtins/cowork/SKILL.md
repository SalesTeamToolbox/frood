---
name: cowork
description: Hand off work to VPS coworker daemon for autonomous execution, check status, or recall control back to laptop.
always: false
task_types: [coding, deployment]
---

# Cowork — VPS Autonomous Execution

This skill manages the cowork system: handing off feature builds to the VPS for
autonomous Claude Code execution, monitoring progress, and recalling control.

## Architecture

```
Laptop (you)                         VPS (agent42-prod)
─────────────                        ──────────────────
Claude Code                          coworker-daemon.sh
  + Agent42 MCP (local)                + auto-resume.sh
  │                                      + Claude Code (headless)
  │  1. /cowork handoff                  + Agent42 MCP (prod)
  │     → creates work order             │
  │     → git push                       │  picks up work order
  │     → SSH signal                     │  runs claude -p sessions
  │                                      │  commits progress
  │  2. /cowork status                   │  pushes results
  │     → SSH check                      │
  │                                      │
  │  3. /cowork recall                   │
  │     → SSH SIGUSR1 to daemon  ───────►│  graceful stop
  │     ← git pull results               │  commit + push
```

## Commands

### Handoff (send work to VPS)

When the user wants to hand off work, run the handoff script:

```bash
scripts/cowork/handoff.sh \
  --prompt "Build the caching layer with Redis fallback" \
  --branch feat/caching \
  --criteria "All tests pass" "CacheTool registered in mcp_server.py" \
  --max-sessions 10
```

Or hand off a GSD plan:

```bash
scripts/cowork/handoff.sh \
  --plan .planning/phases/14-caching/14-01-PLAN.md \
  --branch feat/caching
```

Before running handoff:
1. Ensure all current changes are committed
2. Verify the VPS is reachable: `ssh agent42-prod "echo ok"`
3. Verify Claude Code is authenticated on VPS: `ssh agent42-prod "claude --version"`

### Status (check VPS progress)

```bash
scripts/cowork/status.sh           # Quick check
scripts/cowork/status.sh --watch   # Auto-refresh every 30s
scripts/cowork/status.sh --detail  # Full work order dump
```

### Recall (take back control)

When the user wants to take back control from the VPS:

```bash
scripts/cowork/recall.sh                    # Auto-detect active work
scripts/cowork/recall.sh 20260316-143022    # Specific work order
scripts/cowork/recall.sh --force            # Force kill (use if graceful hangs)
```

After recall:
1. VPS commits all progress and pushes
2. Laptop pulls the changes
3. User continues with Claude Code locally
4. Work order status becomes "recalled"

### Re-queue (send recalled work back)

To resume work on VPS after recalling:

```bash
python3 core/work_order.py update <id> --status pending
git add .planning/work-orders/<id>.json && git commit -m "cowork: re-queue <id>" && git push
```

## Work Order Lifecycle

```
pending ──→ in-progress ──→ completed
  ↑              │
  │              ├──→ recalled ──→ pending (re-queue)
  │              │
  └── failed ────┘
```

## Important Notes

- **One CC session at a time**: Your Claude Code subscription likely allows one
  active session. If VPS is working, you cannot run CC on laptop simultaneously.
  Recall first, then continue locally.
- **VPS needs Claude auth**: Run `claude login` once on the VPS via SSH.
- **The daemon polls every 5 minutes**: After handoff, work starts within 5 min
  (or immediately if daemon is nudged by handoff script).
- **All work is committed**: Every phase completion and recall creates a git commit.
  Nothing is lost.
- **Tests are mandatory**: The work order includes a `must_run` command (default:
  `pytest`) that Claude Code executes after each phase.
