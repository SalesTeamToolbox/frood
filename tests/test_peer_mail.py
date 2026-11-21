"""Two-session wake-up test for the vendored peer-mail MCP server.

Session A sends a message to session B; session B reads and acks it (with a
reply back to A). The test asserts:

- B's inbox shows the message unread (wake-up arrived).
- B can read it (only the recipient may); A cannot read B's message.
- B's ack with a reply delivers a new unread message to A's inbox (wake-up).
- A's outbox shows the original message acked (picked up).

Both sessions share one server process / one mailbox, exactly as two sessions
on the same machine would. Session ids are generated at runtime — no session id
or mailbox history is committed to the tree.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER = REPO_ROOT / "process" / "peer-mail" / "peer_mail_server.py"


class PeerMailError(Exception):
    pass


class PeerMailClient:
    """One JSON-RPC client over the stdio peer-mail server.

    Multiple logical sessions share the same client (and therefore the same
    mailbox) by supplying different session ids per call.
    """

    def __init__(self, db_path: Path):
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            env={**_env_with_db(db_path)},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )

    def rpc(self, method: str, params: dict):
        request = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": method, "params": params}
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(request) + "\n")
        self.proc.stdin.flush()
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        if not line:
            raise PeerMailError(f"server closed stdout for {method}")
        response = json.loads(line)
        if "error" in response:
            raise PeerMailError(f"{method}: {response['error']}")
        return response.get("result")

    def close(self):
        try:
            if self.proc.stdin is not None:
                self.proc.stdin.close()
        except Exception:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _env_with_db(db_path: Path) -> dict:
    env = dict(__import__("os").environ)
    env["PEER_MAIL_DB"] = str(db_path)
    return env


def _session_id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------


class TestPeerMailServerRuns:
    def test_server_lists_tools(self, tmp_path):
        db = tmp_path / "mailbox.db"
        client = PeerMailClient(db)
        try:
            tools = client.rpc("tools/list", {})["tools"]
            names = {t["name"] for t in tools}
            expected = {
                "peer_inbox",
                "peer_read",
                "peer_ack",
                "peer_send",
                "peer_outbox",
                "peer_sessions",
            }
            assert expected <= names, names
        finally:
            client.close()


class TestWakeupTwoSessions:
    def test_a_sends_b_reads_acks(self, tmp_path):
        db = tmp_path / "mailbox.db"
        client = PeerMailClient(db)
        try:
            a_id = _session_id()
            b_id = _session_id()

            # Session A sends a wake-up to session B.
            sent = client.rpc(
                "peer_send",
                {
                    "to_session_id": b_id,
                    "subject": "wake up",
                    "body": "ping from A",
                    "from_session_id": a_id,
                    "from_title": "Session A",
                    "from_branch": "feat/m4-peer-mail",
                },
            )
            msg_id = sent["id"]
            assert isinstance(msg_id, str) and msg_id

            # Session B's inbox shows it unread.
            inbox_b = client.rpc("peer_inbox", {"for_session_id": b_id, "limit": 5})
            assert len(inbox_b) == 1
            m = inbox_b[0]
            assert m["id"] == msg_id
            assert m["to_session"] == b_id
            assert m["from_session"] == a_id
            assert m["subject"] == "wake up"
            assert m["status"] == "unread"

            # Only B (the recipient) may read it; A may not.
            assert client.rpc("peer_read", {"for_session_id": a_id, "id": msg_id}) is None
            read_b = client.rpc("peer_read", {"for_session_id": b_id, "id": msg_id})
            assert read_b is not None
            assert read_b["body"] == "ping from A"
            assert read_b["status"] == "read"

            # B acks with a reply; the reply lands in A's inbox unread (wake-up).
            acked = client.rpc("peer_ack", {"id": msg_id, "reply_body": "received loud and clear"})
            assert acked["id"] == msg_id
            assert acked["reply_id"]

            inbox_a = client.rpc("peer_inbox", {"for_session_id": a_id})
            replies = [x for x in inbox_a if x["reply_to"] == msg_id]
            assert len(replies) == 1
            assert replies[0]["status"] == "unread"
            assert replies[0]["subject"] == "Re: wake up"
            assert replies[0]["body"] == "received loud and clear"

            # A's outbox shows the original message acked (picked up).
            outbox_a = client.rpc("peer_outbox", {"for_session_id": a_id})
            picked = [x for x in outbox_a if x["id"] == msg_id]
            assert len(picked) == 1
            assert picked[0]["status"] == "acked"

            # Both sessions are known.
            sessions = client.rpc("peer_sessions", {})
            session_ids = {s["id"] for s in sessions}
            assert a_id in session_ids and b_id in session_ids
        finally:
            client.close()

    def test_ack_without_reply(self, tmp_path):
        db = tmp_path / "mailbox.db"
        client = PeerMailClient(db)
        try:
            a_id = _session_id()
            b_id = _session_id()
            sent = client.rpc(
                "peer_send",
                {"to_session_id": b_id, "subject": "no reply", "from_session_id": a_id},
            )
            msg_id = sent["id"]
            client.rpc("peer_read", {"for_session_id": b_id, "id": msg_id})
            acked = client.rpc("peer_ack", {"id": msg_id})
            assert acked["id"] == msg_id
            assert acked["reply_id"] is None
            # A's inbox: no new message (no reply was requested).
            inbox_a = client.rpc("peer_inbox", {"for_session_id": a_id})
            assert inbox_a == []
        finally:
            client.close()
