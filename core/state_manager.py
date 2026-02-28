"""
Short-term state externalisation for session recovery.

STATE.md captures the current position in a project:
- Which phase/wave is active
- Which tasks are complete vs. pending
- Key decisions made during this session
- Accumulated context that would be lost on session boundary

Combined with PROJECT_SPEC.md and MEMORY.md, this enables instant session
recovery without re-reading all prior conversation history.

Inspired by the GSD framework's approach of externalising state to the
filesystem so that fresh-context agents can resume work immediately.
"""

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import aiofiles

logger = logging.getLogger("agent42.state_manager")

# Prevent accumulated_context from growing without bound.
_MAX_ACCUMULATED_CONTEXT_CHARS = 10_000


@dataclass
class ProjectState:
    """Short-term session state for a project."""

    project_id: str
    current_phase: str = ""
    current_wave: int = 0
    completed_task_ids: list[str] = field(default_factory=list)
    pending_task_ids: list[str] = field(default_factory=list)
    failed_task_ids: list[str] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)
    accumulated_context: str = ""
    plan_spec_path: str = ""  # Path to the active PLAN.md
    last_updated: float = field(default_factory=time.time)

    def to_markdown(self) -> str:
        """Render state as STATE.md for human readability and agent consumption."""
        lines = [
            f"# Project State: {self.project_id}\n",
            f"*Last updated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.last_updated))}*\n",
        ]

        if self.current_phase:
            lines.append(f"## Current Phase\n{self.current_phase}\n")
        if self.current_wave:
            lines.append(f"**Active wave:** {self.current_wave}\n")
        if self.plan_spec_path:
            lines.append(f"**Active plan:** `{self.plan_spec_path}`\n")

        if self.completed_task_ids:
            lines.append("## Completed Tasks")
            for tid in self.completed_task_ids:
                lines.append(f"- [x] {tid}")
            lines.append("")

        if self.pending_task_ids:
            lines.append("## Pending Tasks")
            for tid in self.pending_task_ids:
                lines.append(f"- [ ] {tid}")
            lines.append("")

        if self.failed_task_ids:
            lines.append("## Failed Tasks")
            for tid in self.failed_task_ids:
                lines.append(f"- [!] {tid}")
            lines.append("")

        if self.key_decisions:
            lines.append("## Key Decisions")
            for decision in self.key_decisions:
                lines.append(f"- {decision}")
            lines.append("")

        if self.accumulated_context:
            lines.append(f"## Accumulated Context\n{self.accumulated_context}\n")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectState":
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


class StateManager:
    """Manages per-project STATE.md files for session recovery."""

    def __init__(self, projects_dir: str | Path):
        self._dir = Path(projects_dir)

    def _project_dir(self, project_id: str) -> Path:
        return self._dir / "projects" / project_id

    async def save_state(self, state: ProjectState):
        """Persist state to STATE.md and state.json."""
        project_dir = self._project_dir(state.project_id)
        project_dir.mkdir(parents=True, exist_ok=True)

        # Enforce accumulated_context cap
        if len(state.accumulated_context) > _MAX_ACCUMULATED_CONTEXT_CHARS:
            state.accumulated_context = state.accumulated_context[-_MAX_ACCUMULATED_CONTEXT_CHARS:]

        async with aiofiles.open(project_dir / "STATE.md", "w") as f:
            await f.write(state.to_markdown())
        async with aiofiles.open(project_dir / "state.json", "w") as f:
            await f.write(json.dumps(state.to_dict(), indent=2))

        logger.debug("Saved state for project %s", state.project_id)

    async def load_state(self, project_id: str) -> ProjectState | None:
        """Load state from state.json, or None if no state exists."""
        state_path = self._project_dir(project_id) / "state.json"
        if not state_path.exists():
            return None
        try:
            async with aiofiles.open(state_path) as f:
                data = json.loads(await f.read())
            return ProjectState.from_dict(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load state for project %s: %s", project_id, e)
            return None

    async def update_task_completion(self, project_id: str, task_id: str):
        """Mark a task as completed in the project state."""
        state = await self.load_state(project_id)
        if not state:
            state = ProjectState(project_id=project_id)

        if task_id in state.pending_task_ids:
            state.pending_task_ids.remove(task_id)
        if task_id not in state.completed_task_ids:
            state.completed_task_ids.append(task_id)
        state.last_updated = time.time()
        await self.save_state(state)

    async def update_task_failure(self, project_id: str, task_id: str):
        """Mark a task as failed in the project state."""
        state = await self.load_state(project_id)
        if not state:
            state = ProjectState(project_id=project_id)

        if task_id in state.pending_task_ids:
            state.pending_task_ids.remove(task_id)
        if task_id not in state.failed_task_ids:
            state.failed_task_ids.append(task_id)
        state.last_updated = time.time()
        await self.save_state(state)

    async def record_decision(self, project_id: str, decision: str):
        """Record a key decision for session recovery."""
        state = await self.load_state(project_id)
        if not state:
            state = ProjectState(project_id=project_id)

        timestamp = time.strftime("%H:%M")
        state.key_decisions.append(f"[{timestamp}] {decision}")
        state.last_updated = time.time()
        await self.save_state(state)

    async def set_phase(self, project_id: str, phase: str, wave: int = 0):
        """Update the current phase and wave."""
        state = await self.load_state(project_id)
        if not state:
            state = ProjectState(project_id=project_id)

        state.current_phase = phase
        state.current_wave = wave
        state.last_updated = time.time()
        await self.save_state(state)
