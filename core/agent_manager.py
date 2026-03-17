"""Agent Manager — CRUD for custom AI agents.

Agents are user-defined configurations that specify:
- Which tools the agent can use
- Which skills inform its behavior
- What AI provider/model to use
- Scheduling (always-on, cron, manual)
- Memory scope and iteration limits
"""

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger("agent42.agent_manager")

# ── Model mapping per provider ────────────────────────────────────────────
# Each agent task type maps to the best model per provider.
# This enables concurrent agent teams — each agent uses a different model,
# avoiding rate limit conflicts on any single model.

PROVIDER_MODELS = {
    "anthropic": {
        "fast": "claude-haiku-4-5-20251001",
        "general": "claude-sonnet-4-6-20260217",
        "reasoning": "claude-opus-4-6-20260205",
        "coding": "claude-sonnet-4-6-20260217",
        "content": "claude-sonnet-4-6-20260217",
    },
    "synthetic": {
        "fast": "hf:zai-org/GLM-4.7-Flash",
        "general": "hf:zai-org/GLM-4.7",
        "reasoning": "hf:moonshotai/Kimi-K2-Thinking",
        "coding": "hf:Qwen/Qwen3-Coder-480B-A35B-Instruct",
        "content": "hf:Qwen/Qwen3.5-397B-A17B",
        "research": "hf:moonshotai/Kimi-K2.5",
        "monitoring": "hf:zai-org/GLM-4.7-Flash",
        "marketing": "hf:MiniMaxAI/MiniMax-M2.5",
        "analysis": "hf:deepseek-ai/DeepSeek-R1-0528",
        "lightweight": "hf:meta-llama/Llama-3.3-70B-Instruct",
    },
    "openrouter": {
        "fast": "google/gemini-2.0-flash-001",
        "general": "anthropic/claude-sonnet-4-6",
        "reasoning": "anthropic/claude-opus-4-6",
        "coding": "anthropic/claude-sonnet-4-6",
        "content": "anthropic/claude-sonnet-4-6",
    },
}


def resolve_model(provider: str, task_category: str) -> str:
    """Resolve the best model for a provider + task category.

    Returns the model ID string. Falls back to 'general' if the
    task category isn't mapped for the given provider.
    """
    models = PROVIDER_MODELS.get(provider, PROVIDER_MODELS.get("anthropic", {}))
    return models.get(task_category, models.get("general", "claude-sonnet-4-6"))


# ── Agent Templates ──────────────────────────────────────────────────────
# Templates use task categories instead of hardcoded model names.
# The actual model is resolved at creation time based on the chosen provider.

AGENT_TEMPLATES = {
    "support": {
        "name": "Support Agent",
        "description": "Handles customer support — answers questions, troubleshoots issues, escalates when needed.",
        "tools": ["web_fetch", "http_request", "memory", "template", "knowledge", "web_search"],
        "skills": ["support", "communication", "troubleshooting"],
        "schedule": "always",
        "_task_category": "general",
        "max_iterations": 10,
    },
    "marketing": {
        "name": "Marketing Agent",
        "description": "Creates content, manages social media, tracks SEO, and builds campaigns.",
        "tools": ["web_search", "web_fetch", "content_analyzer", "template", "memory", "data"],
        "skills": ["marketing", "seo", "social-media", "content-writing", "email-marketing"],
        "schedule": "0 9 * * *",
        "_task_category": "marketing",
        "max_iterations": 15,
    },
    "devops": {
        "name": "DevOps Agent",
        "description": "Monitors deployments, runs health checks, manages infrastructure.",
        "tools": ["shell", "docker", "http_request", "git", "memory", "grep"],
        "skills": ["deployment", "server-management", "monitoring", "ci-cd"],
        "schedule": "*/5 * * * *",
        "_task_category": "fast",
        "max_iterations": 5,
    },
    "content": {
        "name": "Content Agent",
        "description": "Writes articles, documentation, release notes, and presentations.",
        "tools": ["web_search", "web_fetch", "template", "content_analyzer", "memory", "outline"],
        "skills": ["content-writing", "documentation", "release-notes", "presentation"],
        "schedule": "manual",
        "_task_category": "content",
        "max_iterations": 20,
    },
    "research": {
        "name": "Research Agent",
        "description": "Investigates topics, analyzes competitors, gathers data, produces reports.",
        "tools": ["web_search", "web_fetch", "data", "memory", "summarize", "content_analyzer"],
        "skills": ["research", "data-analysis", "competitive-analysis", "strategy-analysis"],
        "schedule": "manual",
        "_task_category": "reasoning",
        "max_iterations": 25,
    },
    "code-review": {
        "name": "Code Review Agent",
        "description": "Reviews code for bugs, security issues, and best practices.",
        "tools": ["read_file", "grep", "code_intel", "security_analyze", "git", "memory"],
        "skills": ["code-review", "security-audit", "refactoring", "testing"],
        "schedule": "manual",
        "_task_category": "coding",
        "max_iterations": 10,
    },
}


@dataclass
class AgentConfig:
    """Configuration for a custom agent."""

    id: str = ""
    name: str = ""
    description: str = ""
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    provider: str = "anthropic"
    provider_url: str = ""
    model: str = "claude-sonnet-4-6"
    schedule: str = "manual"
    memory_scope: str = "global"
    max_iterations: int = 10
    approval_required: bool = False
    status: str = "stopped"
    template: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    last_run_at: float = 0.0
    total_runs: int = 0
    total_tokens: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = time.time()
        if not self.updated_at:
            self.updated_at = time.time()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentConfig":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    @classmethod
    def from_template(cls, template_key: str, **overrides) -> "AgentConfig":
        tmpl = AGENT_TEMPLATES.get(template_key, {})
        config = {**tmpl, "template": template_key, **overrides}
        # Resolve model from task category + provider
        task_cat = config.pop("_task_category", "general")
        if "model" not in overrides:
            provider = config.get("provider", "anthropic")
            config["model"] = resolve_model(provider, task_cat)
        return cls.from_dict(config)


class AgentManager:
    """Manages custom agent configurations."""

    def __init__(self, agents_dir: str | Path):
        self.agents_dir = Path(agents_dir)
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self._agents: dict[str, AgentConfig] = {}
        self._load_all()

    def _load_all(self):
        """Load all agent configs from disk."""
        self._agents.clear()
        for f in self.agents_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                agent = AgentConfig.from_dict(data)
                self._agents[agent.id] = agent
            except Exception as e:
                logger.error(f"Failed to load agent {f}: {e}")
        logger.info(f"Loaded {len(self._agents)} agents")

    def _save(self, agent: AgentConfig):
        """Persist an agent config to disk."""
        agent.updated_at = time.time()
        path = self.agents_dir / f"{agent.id}.json"
        path.write_text(json.dumps(agent.to_dict(), indent=2), encoding="utf-8")

    def create(self, **kwargs) -> AgentConfig:
        """Create a new agent."""
        template = kwargs.pop("template", "")
        if template and template in AGENT_TEMPLATES:
            agent = AgentConfig.from_template(template, **kwargs)
        else:
            agent = AgentConfig.from_dict(kwargs)
        self._agents[agent.id] = agent
        self._save(agent)
        logger.info(f"Created agent: {agent.name} ({agent.id})")
        return agent

    def get(self, agent_id: str) -> AgentConfig | None:
        return self._agents.get(agent_id)

    def list_all(self) -> list[AgentConfig]:
        return list(self._agents.values())

    def update(self, agent_id: str, **kwargs) -> AgentConfig | None:
        agent = self._agents.get(agent_id)
        if not agent:
            return None
        for key, value in kwargs.items():
            if hasattr(agent, key) and key not in ("id", "created_at"):
                setattr(agent, key, value)
        self._save(agent)
        return agent

    def delete(self, agent_id: str) -> bool:
        agent = self._agents.pop(agent_id, None)
        if not agent:
            return False
        path = self.agents_dir / f"{agent_id}.json"
        path.unlink(missing_ok=True)
        logger.info(f"Deleted agent: {agent.name} ({agent_id})")
        return True

    def set_status(self, agent_id: str, status: str) -> AgentConfig | None:
        valid = {"active", "paused", "stopped", "running", "error"}
        if status not in valid:
            return None
        return self.update(agent_id, status=status)

    def record_run(self, agent_id: str, tokens_used: int = 0):
        agent = self._agents.get(agent_id)
        if agent:
            agent.total_runs += 1
            agent.total_tokens += tokens_used
            agent.last_run_at = time.time()
            self._save(agent)

    @staticmethod
    def get_templates() -> dict:
        return AGENT_TEMPLATES

    @staticmethod
    def get_provider_models() -> dict:
        return PROVIDER_MODELS

    @staticmethod
    def resolve_model_for(provider: str, task_category: str) -> str:
        return resolve_model(provider, task_category)
