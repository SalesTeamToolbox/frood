"""
WorkspaceRegistry — per-workspace root path registry with JSON persistence.

Follows the ProjectManager pattern: in-memory dict + atomic JSON persistence.
Provides CRUD operations, default workspace seeding, and workspace_id resolution
for the multi-project workspace feature (v2.1).

Workspace data model:
  - id: 12-char hex UUID (uuid4)
  - name: human-readable display name
  - root_path: absolute resolved path to the project directory
  - created_at/updated_at: Unix timestamps
  - ordering: integer sort order for UI display
"""

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import aiofiles

logger = logging.getLogger("agent42.workspace_registry")


@dataclass
class Workspace:
    """A workspace that maps a name to a root directory path."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    root_path: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    ordering: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Workspace":
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


class WorkspaceRegistry:
    """Registry that maps workspace IDs to their root paths.

    Persists to a JSON file with atomic write (temp + os.replace).
    Supports CRUD operations, default workspace seeding, and ID resolution.
    """

    def __init__(self, data_path: Path):
        self._path = Path(data_path)
        self._workspaces: dict[str, Workspace] = {}
        self._default_id: str | None = None

    # -- Persistence -----------------------------------------------------------

    async def load(self):
        """Load workspaces from JSON file. Silently ignores missing/corrupt files."""
        if not self._path.exists():
            return
        try:
            async with aiofiles.open(self._path) as f:
                raw = await f.read()
            data = json.loads(raw)
            for entry in data.get("workspaces", []):
                ws = Workspace.from_dict(entry)
                self._workspaces[ws.id] = ws
            self._default_id = data.get("default_id")
            logger.info("Loaded %d workspaces", len(self._workspaces))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load workspaces: %s", e)

    async def _persist(self):
        """Atomically save workspaces to JSON file via temp+replace."""
        data = {
            "workspaces": [ws.to_dict() for ws in self._workspaces.values()],
            "default_id": self._default_id,
        }
        tmp_path = str(self._path) + ".tmp"
        async with aiofiles.open(tmp_path, "w") as f:
            await f.write(json.dumps(data, indent=2))
        os.replace(tmp_path, self._path)

    # -- Seeding ---------------------------------------------------------------

    async def seed_default(self, workspace_path: str):
        """Seed a default workspace from workspace_path if registry is empty.

        Idempotent: does nothing if workspaces already exist (D-10).
        Uses the directory name as the display name, falling back to "Default"
        for degenerate names like '.', '', or '/' (D-09).
        """
        if self._workspaces:
            return

        resolved = Path(workspace_path).resolve()
        name = resolved.name
        if name in (".", "", "/"):
            name = "Default"

        ws = Workspace(
            name=name,
            root_path=str(resolved),
        )
        self._workspaces[ws.id] = ws
        self._default_id = ws.id
        await self._persist()
        logger.info("Seeded default workspace: %s -> %s", name, resolved)

    # -- Accessors -------------------------------------------------------------

    def get_default(self) -> "Workspace | None":
        """Return the default workspace, or None if none is set."""
        if self._default_id is None:
            return None
        return self._workspaces.get(self._default_id)

    def resolve(self, workspace_id: "str | None") -> "Workspace | None":
        """Resolve workspace_id to a Workspace.

        - None -> return the default workspace
        - valid ID -> return that workspace
        - unknown ID -> return None
        """
        if workspace_id is None:
            return self.get_default()
        return self._workspaces.get(workspace_id)

    def list_all(self) -> list[Workspace]:
        """Return all registered workspaces."""
        return list(self._workspaces.values())

    # -- CRUD ------------------------------------------------------------------

    async def create(self, name: str, root_path: str) -> Workspace:
        """Create and register a new workspace.

        Raises ValueError if root_path does not exist or is not a directory.
        """
        resolved = Path(root_path).resolve()
        if not resolved.exists():
            raise ValueError(f"Path does not exist: {root_path}")
        if not resolved.is_dir():
            raise ValueError(f"Path is not a directory: {root_path}")

        ws = Workspace(
            name=name,
            root_path=str(resolved),
        )
        self._workspaces[ws.id] = ws
        await self._persist()
        logger.info("Created workspace %s: %s -> %s", ws.id, name, resolved)
        return ws

    async def update(
        self,
        workspace_id: str,
        name: "str | None" = None,
        ordering: "int | None" = None,
    ) -> "Workspace | None":
        """Update workspace fields. Returns updated workspace or None if not found."""
        ws = self._workspaces.get(workspace_id)
        if ws is None:
            return None
        if name is not None:
            ws.name = name
        if ordering is not None:
            ws.ordering = ordering
        ws.updated_at = time.time()
        await self._persist()
        return ws

    async def delete(self, workspace_id: str) -> bool:
        """Remove a workspace. Returns True on success, False if not found.

        If the deleted workspace was the default, reassigns default to the
        first remaining workspace (or None if no workspaces remain).
        """
        if workspace_id not in self._workspaces:
            return False
        del self._workspaces[workspace_id]
        if self._default_id == workspace_id:
            remaining = list(self._workspaces.keys())
            self._default_id = remaining[0] if remaining else None
        await self._persist()
        logger.info("Deleted workspace %s", workspace_id)
        return True
