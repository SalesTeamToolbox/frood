---
description: Release train — board verify, pinned pytest, receipts, local-HEAD sha readback; delegates to bash ops/train.sh
argument-hint: "<ticket>"  # e.g. frood-cmd-m2
---

The Frood release train. Delegates to `bash ops/train.sh <ticket>`, which runs
the per-ticket gate (lint + the focused pytest file for the ticket), writes
`<report>/receipt.md`, and prints the local-HEAD sha read back from
`git rev-parse HEAD`. Frood public has no prod target — the readback is local
`git rev-parse HEAD` only.

**Usage:**
```
/frood-train <ticket>
/frood-train --help
```

Example:
```
/frood-train frood-cmd-m2
```

This runs `bash ops/train.sh <ticket>` from the Frood repo root. Exit codes:
0 = pass, 1 = test failure, 2 = lint failure. Reports live under
`/home/user/.opencode/reports/frood-public/<ticket>/`.
