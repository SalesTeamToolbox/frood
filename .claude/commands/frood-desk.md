---
description: Flat-context /desk session — watches streams via bin/handoff.mjs; delegates to node {{ORCH_REPO}}/bin/desk.mjs
argument-hint: "<command> [args]"  # status, models, watch, daemon, step, verdict, merge-check, ...
---

The Frood orchestration desk. Delegates to `node {{ORCH_REPO}}/bin/desk.mjs`,
which watches streams through `bin/handoff.mjs` from a flat-context `/desk`
session.

**Usage:**
```
/frood-desk status [--json]
/frood-desk models
/frood-desk watch --events [--interval 30] [--once] [--until-event <sec>] [--by cc|oc]
/frood-desk daemon start [--interval 30] [--by cc|oc]  |  daemon status  |  daemon stop
/frood-desk step <stream> <key> [--by cc|oc]
/frood-desk verdict <stream> <run> --findings <path>
/frood-desk merge-check <stream> <run>
/frood-desk --help
```

This runs `node {{ORCH_REPO}}/bin/desk.mjs <command> [args]`. `--help` prints
the desk's full usage and exits 0.

`status` prints a `watch <live|stale|none>` line naming the desk-watch lock
owner, then per-stream rows, then per-run rows. `daemon start` double-forks a
headless watch loop; prefer `systemctl --user start orchestrator-desk-daemon`
when installed but inactive.
