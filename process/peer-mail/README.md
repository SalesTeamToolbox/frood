# process/peer-mail — vendored peer-mail MCP server (optional companion)

This directory vendors a minimal, self-contained **peer-mail MCP server** as an
optional companion for Frood. It implements the peer-mail protocol (session ids,
inbox/read/ack/send/outbox/sessions) so that sessions can exchange wake-ups and
links on the same machine — never dumps, never anything private.

## Status: optional, setup-required

This is **not** "out of the box" and is **not required for Frood to function**.
Frood works perfectly well without it. Public users who want peer-mail set it up
themselves on their own machine; it is local-only infrastructure.

## What it does / does not proxy

- Does: carry short wake-up messages and links between sessions on one machine.
- Does not: proxy anything private, do not forward mail off the machine, do not
  call any external service, do not touch Frood's memory, Qdrant, Redis, or
  vault. All mailbox state lives in a local SQLite file you control.

## Files

- `peer_mail_server.py` — the server. Stdlib only (Python 3.11+), speaks
  JSON-RPC 2.0 over stdio. No external dependencies, no `mcp` package required.
- `README.md` — this file.

## Running the server

Pick a mailbox location (default is `~/.local/share/frood-peer-mail/mailbox.db`):

```bash
# default mailbox location
python process/peer-mail/peer_mail_server.py

# or override the mailbox path
PEER_MAIL_DB=~/.local/share/frood-peer-mail/mailbox.db \
  python process/peer-mail/peer_mail_server.py
```

The server stays attached to stdio: read one JSON-RPC request per line from
stdin, write one response per line to stdout.

## Wiring it into an MCP host (example `.mcp.json`)

```json
{
  "mcpServers": {
    "frood-peer-mail": {
      "command": "python3",
      "args": ["/absolute/path/to/frood/process/peer-mail/peer_mail_server.py"],
      "env": {
        "PEER_MAIL_DB": "/absolute/path/to/.local/share/frood-peer-mail/mailbox.db"
      }
    }
  }
}
```

`PEER_MAIL_DB` is optional; without it the default path under your home dir is
used. Point it at a path only your user can read.

## Protocol (tools)

| Tool | Purpose |
|------|---------|
| `peer_inbox(for_session_id, limit=20)` | Unread messages first (newest first), then recently read. |
| `peer_read(for_session_id, id)` | Read one message — only its recipient may read it; marks it read. |
| `peer_ack(id, reply_body?)` | Mark a message acked (picked up). With `reply_body`, delivers a reply to the original sender as a new unread message — that's the wake-up. |
| `peer_send(to_session_id, subject, body, from_session_id?, from_title?, from_branch?)` | Send a message to another session. Returns the message id. |
| `peer_outbox(for_session_id)` | Messages this session sent that have been acked (picked up). |
| `peer_sessions()` | Session ids seen in the mailbox ("who is around"). |

Session ids are opaque strings assigned by the harness out of band (the same id
the peer-mail SessionStart hook injects). Nothing here hard-codes or commits a
real session id.

## Data retention

Expired messages (`expires_at` in the past) are filtered out of inbox/outbox but
are never auto-deleted, so local history is preserved. There is no committed
mailbox and no session history in this tree — pass bars require none.

## Tests

`tests/test_peer_mail.py` — two-session wake-up test: session A sends, session B
reads/acks (with a reply back to A), and session A's inbox shows the wake-up.

## Related

- Orchestrator hook: `hooks/peer-mail-session-id.js` (in the orchestrator repo)
  injects a session's id at SessionStart and lists unread subjects.
- Peer-mail carries wake-ups and links between sessions, never dumps.
