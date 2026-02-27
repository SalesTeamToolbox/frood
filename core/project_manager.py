"""
Project lifecycle manager — groups tasks into projects with aggregate tracking.

Projects provide a higher-level organizational unit above tasks. Each project
can have many tasks, a linked chat session, an optional app, and a GitHub repo.

Follows the AppManager pattern: in-memory dict + JSON persistence.
"""

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles

if TYPE_CHECKING:
    from core.task_queue import TaskQueue

logger = logging.getLogger("agent42.project_manager")


class ProjectStatus(str, Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


@dataclass
class Project:
    """A project that groups related tasks."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    description: str = ""
    status: str = "planning"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    tags: list = field(default_factory=list)
    chat_session_id: str = ""
    app_id: str = ""
    github_repo: str = ""
    assigned_team: str = ""
    priority: int = 0  # 0=normal, 1=high, 2=urgent
    color: str = ""  # Kanban card accent color
    memory_dir: str = ""  # Path to project-specific memory directory

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


class ProjectManager:
    """Manages project lifecycle and task aggregation."""

    def __init__(self, projects_dir: str | Path, task_queue: "TaskQueue"):
        self._dir = Path(projects_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._data_path = self._dir / "projects.json"
        self._projects: dict[str, Project] = {}
        self._task_queue = task_queue

    # -- Persistence -----------------------------------------------------------

    async def load(self):
        """Load projects from JSON file."""
        if not self._data_path.exists():
            return
        try:
            async with aiofiles.open(self._data_path) as f:
                raw = await f.read()
            data = json.loads(raw)
            for entry in data:
                project = Project.from_dict(entry)
                self._projects[project.id] = project
            logger.info("Loaded %d projects", len(self._projects))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load projects: %s", e)

    async def _persist(self):
        """Save projects to JSON file."""
        data = [p.to_dict() for p in self._projects.values()]
        async with aiofiles.open(self._data_path, "w") as f:
            await f.write(json.dumps(data, indent=2))

    # -- CRUD ------------------------------------------------------------------

    async def create(
        self,
        name: str,
        description: str = "",
        tags: list | None = None,
        **kwargs,
    ) -> Project:
        """Create a new project."""
        project = Project(
            name=name,
            description=description,
            tags=tags or [],
            **{k: v for k, v in kwargs.items() if k in Project.__dataclass_fields__},
        )
        self._projects[project.id] = project
        await self._persist()
        logger.info("Created project %s: %s", project.id, name)
        return project

    async def get(self, project_id: str) -> Project | None:
        """Get a project by ID."""
        return self._projects.get(project_id)

    def list_projects(self, include_archived: bool = False) -> list[Project]:
        """List all projects, sorted by updated_at descending."""
        projects = list(self._projects.values())
        if not include_archived:
            projects = [p for p in projects if p.status != ProjectStatus.ARCHIVED.value]
        projects.sort(key=lambda p: p.updated_at, reverse=True)
        return projects

    async def update(self, project_id: str, **kwargs) -> Project | None:
        """Update project fields."""
        project = self._projects.get(project_id)
        if not project:
            return None
        for key, value in kwargs.items():
            if key in Project.__dataclass_fields__ and key != "id":
                setattr(project, key, value)
        project.updated_at = time.time()
        await self._persist()
        return project

    async def set_status(self, project_id: str, status: str) -> Project | None:
        """Change project status."""
        if status not in [s.value for s in ProjectStatus]:
            return None
        return await self.update(project_id, status=status)

    async def archive(self, project_id: str, app_manager=None) -> bool:
        """Archive a project and its associated app (if any)."""
        project = self._projects.get(project_id)
        if not project:
            return False
        if project.app_id and app_manager:
            try:
                await app_manager.delete(project.app_id)
            except ValueError:
                logger.warning(
                    "App %s not found when archiving project %s",
                    project.app_id,
                    project_id,
                )
        result = await self.set_status(project_id, ProjectStatus.ARCHIVED.value)
        return result is not None

    async def delete(self, project_id: str, app_manager=None) -> bool:
        """Permanently delete a project and its associated app (if any)."""
        project = self._projects.get(project_id)
        if not project:
            return False
        if project.app_id and app_manager:
            try:
                await app_manager.delete(project.app_id)
            except ValueError:
                logger.warning(
                    "App %s not found when deleting project %s",
                    project.app_id,
                    project_id,
                )
        del self._projects[project_id]
        await self._persist()
        logger.info("Deleted project %s", project_id)
        return True

    # -- Task aggregation ------------------------------------------------------

    def get_project_tasks(self, project_id: str) -> list:
        """Get all tasks associated with a project."""
        return [t for t in self._task_queue.all_tasks() if t.project_id == project_id]

    def project_stats(self, project_id: str) -> dict:
        """Compute aggregate task progress for a project."""
        from core.task_queue import TaskStatus

        tasks = self.get_project_tasks(project_id)
        total = len(tasks)
        done = sum(1 for t in tasks if t.status in (TaskStatus.DONE, TaskStatus.ARCHIVED))
        running = sum(1 for t in tasks if t.status == TaskStatus.RUNNING)
        failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
        pending = sum(1 for t in tasks if t.status in (TaskStatus.PENDING, TaskStatus.ASSIGNED))
        blocked = sum(1 for t in tasks if t.status == TaskStatus.BLOCKED)
        review = sum(1 for t in tasks if t.status == TaskStatus.REVIEW)
        return {
            "total": total,
            "done": done,
            "running": running,
            "failed": failed,
            "pending": pending,
            "blocked": blocked,
            "review": review,
        }

    def get_project_memory(
        self,
        project_id: str,
        global_store=None,
        qdrant_store=None,
        redis_backend=None,
    ):
        """Get a ProjectMemoryStore for a project.

        Returns None if the project doesn't exist or global_store is missing.
        Lazily initializes the project's memory directory.
        """
        project = self._projects.get(project_id)
        if not project or not global_store:
            return None

        from memory.project_memory import ProjectMemoryStore

        base_dir = self._dir
        memory = ProjectMemoryStore(
            project_id=project_id,
            base_dir=base_dir,
            global_store=global_store,
            qdrant_store=qdrant_store,
            redis_backend=redis_backend,
        )

        # Persist the memory_dir reference on the project if not set
        if not project.memory_dir:
            project.memory_dir = str(base_dir / "projects" / project_id)

        return memory

    def board(self) -> dict[str, list[dict]]:
        """Group projects by status for Kanban board view.

        Returns a dict with status keys mapping to lists of project dicts,
        each augmented with computed ``stats`` from task aggregation.
        """
        columns: dict[str, list[dict]] = {s.value: [] for s in ProjectStatus}
        for project in self._projects.values():
            d = project.to_dict()
            d["stats"] = self.project_stats(project.id)
            target = columns.get(project.status)
            if target is not None:
                target.append(d)
        return columns
