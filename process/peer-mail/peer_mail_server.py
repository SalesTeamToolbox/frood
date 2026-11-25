#!/usr/bin/env python3
"""Vendored peer-mail MCP server — optional companion for Frood.

Self-contained (stdlib only). Speaks JSON-RPC 2.0 over stdio and implements the
peer-mail protocol (session ids, inbox/read/ack/send/outbox/sessions) backed by
a local SQLite mailbox.

Nothing is proxied anywhere: all mailbox state lives on the machine that runs
this server, under ``PEER_MAIL_DB`` (default
``~/.local/share/frood-peer-mail/mailbox.db``). It is OPTIONAL infrastructure —
Frood works without it, and public users set it up themselves. See README.md.

Usage::

    PEER_MAIL_DB=~/.local/share/frood-peer-mail/mailbox.db \\
        python process/peer-mail/peer_mail_server.py

Protocol (JSON-RPC 2.0, one request per line on stdin, one response per line on
stdout):

    initialize        -> capabilities
    tools/list        -> the peer_* tools below
    tools/call        -> invoke a tool, returns its result directly

Tools:
    peer_inbox(for_session_id, limit=20)
        Unread messages first (newest first), then recently read. Each entry:
        id, ts, from_session, from_title, from_branch, to_session, subject,
        body, status, reply_to, expires_at.
    peer_read(for_session_id, id)
        Returns the message only to its recipient; marks it read. None when the
        session is not the recipient or the message is gone/expired.
    peer_ack(id, reply_body=None)
        Marks a message acked (picked up). With reply_body, delivers a reply to
        the original sender as a new unread message (the "wake-up"). Returns
        {"id": ..., "reply_id": ... | None}.
    peer_send(to_session_id, subject, body="", from_session_id=None,
              from_title=None, from_branch=None)
        Sends a message. Returns {"id": <message id>}. Session ids are opaque
        strings supplied by callers (the harness assigns them out of band).
    peer_outbox(for_session_id)
        Messages sent by this session that have been acked (picked up).
    peer_sessions()
        Distinct session ids seen in the mailbox ("who is around").

Expired messages (expires_at in the past) are filtered out of inbox/outbox but
never auto-deleted, so history is preserved for the local user.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(os.path.expanduser("~/.local/share/frood-peer-mail/mailbox.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id            TEXT PRIMARY KEY,
    ts            INTEGER NOT NULL,
    from_session  TEXT NOT NULL,
    from_title    TEXT,
    from_branch   TEXT,
    to_session    TEXT NOT NULL,
    subject       TEXT NOT NULL,
    body          TEXT,
    status        TEXT NOT NULL DEFAULT 'unread',
    reply_to      TEXT,
    expires_at    INTEGER
);
"""

# Indexes run after _migrate(): a mailbox created by older peer-mail tooling has
# no reply_to column, and indexing it before the column exists fails.
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_messages_to_status ON messages(to_session, status);
CREATE INDEX IF NOT EXISTS idx_messages_from ON messages(from_session);
CREATE INDEX IF NOT EXISTS idx_messages_reply_to ON messages(reply_to);
"""

STATUS_UNREAD = "unread"
STATUS_READ = "read"
STATUS_ACKED = "acked"


def _now() -> int:
    return int(time.time() * 1000)


def _new_id() -> str:
    return uuid.uuid4().hex


class Mailbox:
    """Local SQLite mailbox. One instance per server process."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.executescript(INDEXES)
        self.conn.commit()

    def _migrate(self) -> None:
        """Bring a mailbox created by older tooling up to this schema (idempotent)."""
        cols = {row["name"] for row in self.conn.execute("PRAGMA table_info(messages)")}
        if "reply_to" not in cols:
            self.conn.execute("ALTER TABLE messages ADD COLUMN reply_to TEXT")

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    # -- writes ---------------------------------------------------------

    def send(
        self,
        from_session: str,
        to_session: str,
        subject: str,
        body: str = "",
        from_title: str | None = None,
        from_branch: str | None = None,
        reply_to: str | None = None,
        ttl_ms: int | None = None,
    ) -> str:
        mid = _new_id()
        ts = _now()
        expires_at = (ts + ttl_ms) if ttl_ms else None
        self.conn.execute(
            """
            INSERT INTO messages
                (id, ts, from_session, from_title, from_branch, to_session,
                 subject, body, status, reply_to, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unread', ?, ?)
            """,
            (
                mid,
                ts,
                from_session,
                from_title,
                from_branch,
                to_session,
                subject,
                body,
                reply_to,
                expires_at,
            ),
        )
        self.conn.commit()
        return mid

    def mark_read(self, msg_id: str) -> None:
        self.conn.execute(
            "UPDATE messages SET status = 'read' WHERE id = ? AND status = 'unread'",
            (msg_id,),
        )
        self.conn.commit()

    def mark_acked(self, msg_id: str) -> None:
        self.conn.execute("UPDATE messages SET status = 'acked' WHERE id = ?", (msg_id,))
        self.conn.commit()

    # -- reads ----------------------------------------------------------

    def _visible(self, for_session: str, limit: int):
        now = _now()
        rows = self.conn.execute(
            """
            SELECT * FROM messages
            WHERE to_session = ? AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY
                CASE WHEN status = 'unread' THEN 0 ELSE 1 END,
                ts DESC
            LIMIT ?
            """,
            (for_session, now, limit),
        )
        return [dict(r) for r in rows]

    def inbox(self, for_session: str, limit: int = 20):
        return self._visible(for_session, limit)

    def read(self, for_session: str, msg_id: str):
        row = self.conn.execute(
            "SELECT * FROM messages WHERE id = ? AND to_session = ?",
            (msg_id, for_session),
        ).fetchone()
        if row is None:
            return None
        self.mark_read(msg_id)
        result = dict(row)
        result["status"] = STATUS_READ
        return result

    def ack(self, msg_id: str, reply_body: str | None = None):
        row = self.conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
        if row is None:
            return None
        self.mark_acked(msg_id)
        reply_id = None
        if reply_body is not None:
            reply_id = self.send(
                from_session=row["to_session"],
                to_session=row["from_session"],
                subject=f"Re: {row['subject']}",
                body=reply_body,
                reply_to=msg_id,
            )
        self.conn.commit()
        return {"id": msg_id, "reply_id": reply_id}

    def outbox(self, for_session: str):
        now = _now()
        rows = self.conn.execute(
            """
            SELECT * FROM messages
            WHERE from_session = ? AND status = 'acked'
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY ts DESC
            """,
            (for_session, now),
        )
        return [dict(r) for r in rows]

    def sessions(self):
        rows = self.conn.execute(
            """
            SELECT DISTINCT from_session AS id FROM messages
            UNION
            SELECT DISTINCT to_session AS id FROM messages
            ORDER BY id
            """
        )
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "peer_inbox",
        "description": "List a session's inbox: unread first, then recently read.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "for_session_id": {
                    "type": "string",
                    "description": "session id to read the inbox for",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "max messages to return",
                },
            },
            "required": ["for_session_id"],
        },
    },
    {
        "name": "peer_read",
        "description": "Read a single message; only its recipient may read it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "for_session_id": {
                    "type": "string",
                    "description": "session id reading the message",
                },
                "id": {"type": "string", "description": "message id to read"},
            },
            "required": ["for_session_id", "id"],
        },
    },
    {
        "name": "peer_ack",
        "description": "Ack a message (picked up); optional reply wakes the sender.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "message id to ack"},
                "reply_body": {
                    "type": "string",
                    "description": "reply text sent back to the sender",
                },
            },
            "required": ["id"],
        },
    },
    {
        "name": "peer_send",
        "description": "Send a message to another session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to_session_id": {"type": "string", "description": "recipient session id"},
                "subject": {"type": "string", "description": "message subject"},
                "body": {"type": "string", "default": "", "description": "message body"},
                "from_session_id": {"type": "string", "description": "sender session id"},
                "from_title": {"type": "string", "description": "sender display title"},
                "from_branch": {"type": "string", "description": "sender branch"},
            },
            "required": ["to_session_id", "subject"],
        },
    },
    {
        "name": "peer_outbox",
        "description": "Messages this session sent that have been acked (picked up).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "for_session_id": {
                    "type": "string",
                    "description": "session id to read the outbox for",
                },
            },
            "required": ["for_session_id"],
        },
    },
    {
        "name": "peer_sessions",
        "description": "Session ids seen in the mailbox (who is around).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def _call_tool(name: str, arguments: dict, mb: Mailbox):
    if name == "peer_inbox":
        return mb.inbox(
            arguments["for_session_id"],
            int(arguments.get("limit", 20)),
        )
    if name == "peer_read":
        return mb.read(arguments["for_session_id"], arguments["id"])
    if name == "peer_ack":
        return mb.ack(arguments["id"], arguments.get("reply_body"))
    if name == "peer_send":
        mid = mb.send(
            from_session=arguments.get("from_session_id") or _new_id(),
            to_session=arguments["to_session_id"],
            subject=arguments["subject"],
            body=arguments.get("body", "") or "",
            from_title=arguments.get("from_title"),
            from_branch=arguments.get("from_branch"),
        )
        return {"id": mid}
    if name == "peer_outbox":
        return mb.outbox(arguments["for_session_id"])
    if name == "peer_sessions":
        return mb.sessions()
    raise ValueError(f"unknown tool: {name}")


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 over stdio
# ---------------------------------------------------------------------------


class JSONRPCError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


METHOD_NOT_FOUND = JSONRPCError(-32601, "method not found")
INVALID_PARAMS = JSONRPCError(-32602, "invalid params")
INTERNAL_ERROR = JSONRPCError(-32603, "internal error")


def _respond(rid: Any, result: Any) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _error(rid: Any, err: JSONRPCError) -> None:
    sys.stdout.write(
        json.dumps(
            {"jsonrpc": "2.0", "id": rid, "error": {"code": err.code, "message": err.message}}
        )
    )
    sys.stdout.write("\n")
    sys.stdout.flush()


def _handle(request: dict, mb: Mailbox) -> None:
    method = request.get("method")
    params = request.get("params") or {}
    rid = request.get("id")
    is_notification = rid is None

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "frood-peer-mail", "version": "0.1.0"},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str) or not name:
                raise INVALID_PARAMS
            result = _call_tool(name, arguments, mb)
        elif method == "initialized":
            # notification: nothing to do
            return
        elif method and method.startswith("peer_"):
            # Direct tool invocation (convenience framing alongside tools/call).
            result = _call_tool(method, params, mb)
            if not is_notification:
                _respond(rid, result)
            return
        else:
            raise METHOD_NOT_FOUND

        if not is_notification:
            _respond(rid, result)
    except JSONRPCError as err:
        if not is_notification:
            _error(rid, err)
    except Exception as exc:  # never crash session start / the loop
        if not is_notification:
            _error(rid, JSONRPCError(-32603, str(exc)))


def main() -> int:
    db_path = Path(os.environ.get("PEER_MAIL_DB", str(DEFAULT_DB)))
    mb = Mailbox(db_path)
    # Line-buffered so each response line reaches the client immediately.
    out = os.fdopen(sys.stdout.fileno(), "w", encoding="utf-8", newline="\n")
    sys.stdout = out
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                continue  # ignore malformed lines
            if isinstance(request, dict):
                _handle(request, mb)
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        mb.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
