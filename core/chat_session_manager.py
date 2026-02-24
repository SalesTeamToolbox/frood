"""
Chat session manager with per-session JSONL message persistence.

Manages dashboard chat and code sessions. Each session stores messages
in a separate JSONL file for append-only, efficient persistence.

Follows the AppManager pattern: in-memory dict + JSON registry file.
"""

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

import aiofiles

logger = logging.getLogger("agent42.chat_session_manager")


class ChatSessionType(str, Enum):
    CHAT = "chat"
    CODE = "code"


@dataclass
class ChatSession:
    """Metadata for a single chat session."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = "New Chat"
    session_type: str = "chat"  # "chat" or "code"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    message_count: int = 0
    last_message_preview: str = ""
    # Code-page specific fields
    project_id: str = ""
    app_id: str = ""
    deployment_target: str = ""  # "local" or "remote"
    ssh_host: str = ""
    github_repo: str = ""
    archived: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ChatSession":
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


class ChatSessionManager:
    """Manages chat sessions with per-session JSONL message persistence.

    Session metadata is stored in ``sessions.json`` in the sessions directory.
    Each session's messages are stored in ``{session_id}.jsonl``.
    All file I/O uses aiofiles for async compatibility.
    """

    def __init__(self, sessions_dir: str | Path):
        self._dir = Path(sessions_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, ChatSession] = {}
        self._data_path = self._dir / "sessions.json"

    # -- Persistence -----------------------------------------------------------

    async def load(self):
        """Load session registry from disk."""
        if not self._data_path.exists():
            return
        try:
            async with aiofiles.open(self._data_path) as f:
                raw = await f.read()
            data = json.loads(raw)
            for entry in data:
                session = ChatSession.from_dict(entry)
                self._sessions[session.id] = session
            logger.info("Loaded %d chat sessions", len(self._sessions))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load chat sessions: %s", e)

    async def _persist(self):
        """Save session registry to disk."""
        data = [s.to_dict() for s in self._sessions.values()]
        async with aiofiles.open(self._data_path, "w") as f:
            await f.write(json.dumps(data, indent=2))

    # -- Session CRUD ----------------------------------------------------------

    async def create(
        self,
        title: str = "New Chat",
        session_type: str = "chat",
        **kwargs,
    ) -> ChatSession:
        """Create a new chat session."""
        session = ChatSession(
            title=title,
            session_type=session_type,
            **{k: v for k, v in kwargs.items() if k in ChatSession.__dataclass_fields__},
        )
        self._sessions[session.id] = session
        await self._persist()
        logger.info("Created chat session %s (type=%s)", session.id, session_type)
        return session

    async def get(self, session_id: str) -> ChatSession | None:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    def list_sessions(
        self,
        session_type: str = "",
        include_archived: bool = False,
    ) -> list[ChatSession]:
        """List sessions, optionally filtered by type."""
        sessions = list(self._sessions.values())
        if session_type:
            sessions = [s for s in sessions if s.session_type == session_type]
        if not include_archived:
            sessions = [s for s in sessions if not s.archived]
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    async def update(self, session_id: str, **kwargs) -> ChatSession | None:
        """Update session fields."""
        session = self._sessions.get(session_id)
        if not session:
            return None
        for key, value in kwargs.items():
            if key in ChatSession.__dataclass_fields__ and key != "id":
                setattr(session, key, value)
        session.updated_at = time.time()
        await self._persist()
        return session

    async def rename(self, session_id: str, title: str) -> ChatSession | None:
        """Rename a session."""
        return await self.update(session_id, title=title)

    async def archive(self, session_id: str) -> bool:
        """Archive a session (soft delete)."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        session.archived = True
        session.updated_at = time.time()
        await self._persist()
        return True

    async def delete(self, session_id: str) -> bool:
        """Permanently delete a session and its messages."""
        if session_id not in self._sessions:
            return False
        del self._sessions[session_id]
        # Remove message file
        msg_path = self._messages_path(session_id)
        if msg_path.exists():
            msg_path.unlink()
        await self._persist()
        logger.info("Deleted chat session %s", session_id)
        return True

    # -- Message I/O -----------------------------------------------------------

    def _messages_path(self, session_id: str) -> Path:
        """Get the JSONL file path for a session's messages."""
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
        return self._dir / f"{safe_id}.jsonl"

    async def add_message(self, session_id: str, message: dict):
        """Append a message to the session's JSONL file.

        Also updates session metadata (updated_at, message_count, preview).
        """
        session = self._sessions.get(session_id)
        if not session:
            logger.warning("add_message: session %s not found", session_id)
            return

        # Ensure message has required fields
        if "id" not in message:
            message["id"] = uuid.uuid4().hex[:12]
        if "timestamp" not in message:
            message["timestamp"] = time.time()

        # Append to JSONL
        path = self._messages_path(session_id)
        line = json.dumps(message) + "\n"
        async with aiofiles.open(path, "a") as f:
            await f.write(line)

        # Update session metadata
        session.message_count += 1
        session.updated_at = time.time()
        content = message.get("content", "")
        session.last_message_preview = content[:100] if content else ""

        # Auto-generate title from first user message (only if title is still default)
        if session.message_count == 1 and message.get("role") == "user" and session.title == "New Chat":
            session.title = content[:60] + ("..." if len(content) > 60 else "")

        await self._persist()

    async def get_messages(self, session_id: str, limit: int = 200) -> list[dict]:
        """Read the last N messages from a session's JSONL file."""
        path = self._messages_path(session_id)
        if not path.exists():
            return []

        messages = []
        try:
            async with aiofiles.open(path) as f:
                async for line in f:
                    line = line.strip()
                    if line:
                        try:
                            messages.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError as e:
            logger.warning("Failed to read messages for session %s: %s", session_id, e)
            return []

        # Return last N messages
        if limit and len(messages) > limit:
            return messages[-limit:]
        return messages

    async def clear_messages(self, session_id: str):
        """Clear all messages in a session."""
        path = self._messages_path(session_id)
        if path.exists():
            async with aiofiles.open(path, "w") as f:
                await f.write("")
        session = self._sessions.get(session_id)
        if session:
            session.message_count = 0
            session.last_message_preview = ""
            session.updated_at = time.time()
            await self._persist()

    # -- Default session (backward compatibility) ------------------------------

    async def get_or_create_default(self, session_type: str = "chat") -> ChatSession:
        """Get or lazily create the default session for backward compat."""
        default_id = f"default_{session_type}"
        session = self._sessions.get(default_id)
        if session:
            return session
        session = ChatSession(
            id=default_id,
            title="Chat" if session_type == "chat" else "Code",
            session_type=session_type,
        )
        self._sessions[session.id] = session
        await self._persist()
        return session
