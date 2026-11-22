---
description: Deploy — deploy truth and shipped-sha readback; delegates to orchestrator/ops/deploy
argument-hint: "<ticket> [--sha <sha>]"  # verify, shipped
---

Frood deploy. Delegates to the orchestrator deploy tooling
(`orchestrator/ops/deploy`), which records deploy truth (verified sha or stated
gap) and performs the local-HEAD sha readback. Frood public has no prod target,
so the readback is local `git rev-parse HEAD` only.

**Usage:**
```
/frood-deploy <ticket> --sha <sha>
/frood-deploy verify <ticket> --sha <sha>  |  shipped <ticket> --sha <sha>
/frood-deploy --help
```

Example:
```
/frood-deploy frood-cmd-m2 --sha abc1234
```

A merge is not a deploy: only report "deployed" after reading the sha back from
the running service. Workers never push, merge or deploy.
