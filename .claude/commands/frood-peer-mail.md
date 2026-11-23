---
description: Cross-harness peer-mail — send/read/ack messages between agent sessions; delegates to the orchestrator peer-mail tooling
argument-hint: "<send|inbox|read|ack|sessions> ..."  # peer_sessions, peer_send, peer_inbox, peer_read, peer_ack
---

Cross-harness peer-mail between agent sessions. Both Claude Code and OpenCode
share the same peer-mail MCP (`peer_sessions`, `peer_send`, `peer_inbox`,
`peer_read`, `peer_ack`). The board is the truth; peer-mail only wakes a
long-lived session (e.g. "ticket X ready for review", with the report link —
never the dump).

**Usage:**
```
/frood-peer-mail sessions
/frood-peer-mail inbox [--for-session <id>] [--limit <n>]
/frood-peer-mail read <message-id>
/frood-peer-mail ack <message-id> [--reply <body>]
/frood-peer-mail send <to-session-id> <subject> <body>
/frood-peer-mail --help
```

This delegates to the orchestrator's peer-mail tooling
(`node orchestrator/bin/peer-mail` where available, otherwise the peer-mail
MCP tools). Address sessions only by exact id from `peer_sessions`.

Headless workers launched by `oc-worker` need no peer-mail: the orchestrator
reads their report file directly.
