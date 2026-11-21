# Token proof — M7 (EGM-in-process + token-proof)

Fixture-replayable token benchmark for Frood's tiered router vs direct-premium.
Numbers are produced by `scripts/bench-tokens/bench-tokens.mjs` in offline
fixture mode (committed fixture diffs only, no live provider calls, no network)
and are committed here so the token claim is reproducible, not a static stale
table.

## Committed numbers (as of 2026-11-20)

| fixture | router-tokens | direct-premium-tokens | ratio | pass/fail |
|---|---|---|---|---|
| worker-codes-a-fixture-ticket | 83 | 83 | 1 | PASS |
| critic-reviews-a-fixture-diff | 75 | 75 | 1 | PASS |
| senior-signs-off-a-fixture | 74 | 74 | 1 | PASS |

- **router-tokens**: tokens charged when the request is routed through Frood's
  tiered router (workhorse/free model for the eligible tier), measured by
  Frood's router instrumentation.
- **direct-premium-tokens**: tokens charged when the same request goes straight
  to the premium model (no routing savings).
- **ratio**: router-tokens / direct-premium-tokens. `<= 1.0` means the router is
  at least as token-efficient as direct-premium.
- **pass/fail**: token-efficiency metric only (`PASS` when ratio <= 1.0).

## EGM gate (Part A)

The fixture `worker-codes-a-fixture-ticket` is **risky**: its diff creates
`tasks/`, a new top-level directory, which trips the EGM trigger for new
top-level directories. The EGM gate therefore blocks worker start until this
ticket is EGM-approved; it **pends approval**. The other two fixtures stay
within an existing top-level directory (`tasks/`) and do not trip an EGM
trigger.

## Rerun command

```bash
node scripts/bench-tokens/bench-tokens.mjs --fixtures scripts/bench-tokens/fixtures --offline
```

Exit code: 0 all pass, 1 any failure. The rerun is deterministic: same three
fixture tasks, same metric columns, identical pass/fail outcome.

## Fixture-mode CI note

CI runs the benchmark in fixture mode only — committed fixture diffs, `--offline`,
no live provider calls, no token burn against any provider ledger. No network
access is required or used.
