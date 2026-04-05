"""Agent Manager — CRUD for custom AI agents.

Agents are user-defined configurations that specify:
- Which tools the agent can use
- Which skills inform its behavior
- What AI provider/model to use
- Scheduling (always-on, cron, manual)
- Memory scope and iteration limits
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Optional import for Synthetic.new API client
try:
    from providers.synthetic_api import SyntheticApiClient

    _synthetic_client = SyntheticApiClient()
except ImportError:
    _synthetic_client = None

logger = logging.getLogger("agent42.agent_manager")

# Module-level settings reference — used by _get_tier_semaphore() and get_effective_limits().
# Monkeypatched in tests via monkeypatch.setattr("core.agent_manager.settings", ...).
# Deferred import avoids circular-import risk at module load time.
from core.config import settings

# ── Model mapping per provider ────────────────────────────────────────────
# Each agent task type maps to the best model per provider.
# This enables concurrent agent teams — each agent uses a different model,
# avoiding rate limit conflicts on any single model.

PROVIDER_MODELS = {
    "claudecode": {
        "fast": "claude-haiku-4-5-20251001",
        "general": "claude-sonnet-4-6-20260217",
        "reasoning": "claude-opus-4-6-20260205",
        "coding": "claude-sonnet-4-6-20260217",
        "content": "claude-sonnet-4-6-20260217",
        "research": "claude-opus-4-6-20260205",
        "strategy": "claude-opus-4-6-20260205",
        "analysis": "claude-sonnet-4-6-20260217",
    },
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
    "abacus": {
        "fast": "gemini-3-flash",  # Free tier
        "general": "gpt-5-mini",  # Free tier
        "reasoning": "claude-opus-4-6",  # Premium
        "coding": "claude-sonnet-4-6",  # Premium
        "content": "gpt-5",  # Premium
        "research": "claude-opus-4-6",  # Premium
        "monitoring": "gemini-3-flash",  # Free tier
        "marketing": "gpt-5-mini",  # Free tier
        "analysis": "claude-sonnet-4-6",  # Premium
        "lightweight": "llama-4",  # Free tier
    },
}


def refresh_synthetic_models(force: bool = False) -> bool:
    """Refresh Synthetic.new model mappings from API.

    Args:
        force: If True, bypass cache and fetch from API regardless

    Returns:
        True if models were successfully refreshed, False otherwise
    """
    global PROVIDER_MODELS

    if _synthetic_client is None:
        logger.warning("Synthetic.new API client not available")
        return False

    try:
        import asyncio

        # Check if we're in an async context
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context, run the async function
            models = asyncio.run(_synthetic_client.refresh_models(force=force))
        except RuntimeError:
            # No running loop, run in a new event loop
            models = asyncio.run(_synthetic_client.refresh_models(force=force))

        if models:
            # Update the PROVIDER_MODELS mapping with dynamic models
            dynamic_mapping = _synthetic_client.update_provider_models_mapping()
            if dynamic_mapping:
                PROVIDER_MODELS["synthetic"] = dynamic_mapping
                logger.info(
                    f"Updated Synthetic.new model mappings: {len(dynamic_mapping)} categories"
                )
                return True
            else:
                logger.warning("No dynamic mappings generated from Synthetic.new models")
                return False
        else:
            logger.warning("No models fetched from Synthetic.new API")
            return False
    except Exception as e:
        logger.error(f"Error refreshing Synthetic.new models: {e}")
        return False


async def start_synthetic_model_refresh_task() -> None:
    """Start a background task to periodically refresh Synthetic.new models."""
    global PROVIDER_MODELS

    if _synthetic_client is None:
        logger.info("Synthetic.new API client not available, skipping background refresh")
        return

    from core.config import settings

    refresh_interval_hours = settings.model_catalog_refresh_hours or 24.0
    refresh_interval_seconds = refresh_interval_hours * 3600

    logger.info(f"Starting Synthetic.new model refresh task (every {refresh_interval_hours} hours)")

    while True:
        try:
            await asyncio.sleep(refresh_interval_seconds)
            logger.info("Refreshing Synthetic.new models...")
            success = refresh_synthetic_models()
            if success:
                logger.info("Successfully refreshed Synthetic.new models")
            else:
                logger.warning("Failed to refresh Synthetic.new models")
        except asyncio.CancelledError:
            logger.info("Synthetic.new model refresh task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in Synthetic.new model refresh task: {e}")


# ── Tier-to-model-category upgrade map (Phase 3: Resource Enforcement) ───────
# Maps reward tier to an upgraded task category for model routing.
# "provisional" and "" (no tier) are deliberately absent — they fall back to
# the caller's task_category with no upgrade applied (D-10, D-11).
_TIER_CATEGORY_UPGRADE: dict[str, str] = {
    "gold": "reasoning",
    "silver": "general",
    "bronze": "fast",
}


def resolve_model(provider: str, task_category: str, tier: str = "") -> str:
    """Resolve the best model for a provider + task category.

    Args:
        provider: Provider key (e.g. "anthropic", "synthetic").
        task_category: Base task category (e.g. "general", "fast", "coding").
        tier: Optional reward tier ("gold", "silver", "bronze", or "").
            When a named tier is provided, it upgrades the effective category
            via _TIER_CATEGORY_UPGRADE. Empty string or unrecognized tiers
            (e.g. "provisional") pass through unchanged — backward compat (D-03).

    Returns the model ID string. Falls back to 'general' if the
    task category isn't mapped for the given provider.
    """
    effective_category = _TIER_CATEGORY_UPGRADE.get(tier, task_category)
    models = PROVIDER_MODELS.get(provider, PROVIDER_MODELS.get("anthropic", {}))
    return models.get(effective_category, models.get("general", "claude-sonnet-4-6"))


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

    # -- Rewards tier fields (Phase 2) ----------------------------------------
    reward_tier: str = ""  # Computed tier: 'provisional'/'bronze'/'silver'/'gold'
    tier_override: str | None = None  # Admin override; None means "use computed tier" (D-03)
    performance_score: float = 0.0  # Last computed composite score
    tier_computed_at: str = ""  # ISO timestamp of last computation

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = time.time()
        if not self.updated_at:
            self.updated_at = time.time()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["effective_tier"] = self.effective_tier()
        return d

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

    def effective_tier(self) -> str:
        """Return the active tier for this agent.

        Returns tier_override when set (not None), otherwise reward_tier.
        This is the single read point for Phase 3 enforcement and Phase 4 dashboard.
        None is the sentinel for "no override" per D-03.
        """
        return self.tier_override if self.tier_override is not None else self.reward_tier


class AgentManager:
    """Manages custom agent configurations."""

    def __init__(self, agents_dir: str | Path):
        self.agents_dir = Path(agents_dir)
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self._agents: dict[str, AgentConfig] = {}
        # Tier concurrency semaphores — created lazily in async context (Pitfall 1)
        self._tier_semaphores: dict[str, asyncio.Semaphore] = {}
        self._load_all()

        # Start background task to refresh Synthetic.new models
        self._start_background_tasks()

    def _start_background_tasks(self):
        """Start background tasks for model refresh."""
        try:
            # Create a task to refresh Synthetic.new models periodically
            import asyncio

            from core.agent_manager import start_synthetic_model_refresh_task

            # Check if we're in an async context
            try:
                loop = asyncio.get_running_loop()
                # Schedule the task to run in the background
                loop.create_task(start_synthetic_model_refresh_task())
            except RuntimeError:
                # No running loop, create a new one
                pass  # Skip for now, task will be started when the app runs
        except Exception as e:
            logger.warning(f"Failed to start background model refresh task: {e}")

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

    def _get_tier_semaphore(self, tier: str) -> "asyncio.Semaphore | None":
        """Return the concurrency semaphore for the given tier, or None if uncapped.

        Semaphores are created lazily (on first call from an async context) to
        avoid RuntimeError from creating asyncio primitives outside an event loop
        (Pitfall 1). The dict _tier_semaphores is initialized empty in __init__.

        Returns None when:
        - rewards_enabled is False (no enforcement)
        - tier is empty string (no tier assigned)
        - tier is "provisional" (treated identically to no tier — D-10, D-11)
        - tier is unrecognized (unknown strings are uncapped)
        """

        if not settings.rewards_enabled or not tier or tier == "provisional":
            return None

        if tier not in self._tier_semaphores:
            cap_map = {
                "bronze": settings.rewards_bronze_max_concurrent,
                "silver": settings.rewards_silver_max_concurrent,
                "gold": settings.rewards_gold_max_concurrent,
            }
            cap = cap_map.get(tier)
            if cap is None:
                return None  # Unknown tier string — no cap (Pitfall 3)
            self._tier_semaphores[tier] = asyncio.Semaphore(cap)

        return self._tier_semaphores[tier]

    def get_effective_limits(self, agent_id: str) -> dict:
        """Return the effective resource limits for an agent based on its tier.

        Returns:
            dict with keys:
                model_tier (str): Model category for routing ("reasoning", "general", "fast", or "")
                rate_multiplier (float): Rate limit multiplier (1.0 = baseline)
                max_concurrent (int): Max concurrent tasks (0 = uncapped)

        When rewards_enabled=False or agent has no/provisional tier, returns safe defaults
        identical to pre-rewards behavior (D-09, D-10).
        """

        agent = self._agents.get(agent_id)
        tier = agent.effective_tier() if agent else ""

        # No enforcement: rewards disabled or tier is empty/provisional
        if not settings.rewards_enabled or not tier or tier == "provisional":
            return {"model_tier": "", "rate_multiplier": 1.0, "max_concurrent": 0}

        multiplier_map = {
            "bronze": settings.rewards_bronze_rate_limit_multiplier,
            "silver": settings.rewards_silver_rate_limit_multiplier,
            "gold": settings.rewards_gold_rate_limit_multiplier,
        }
        concurrent_map = {
            "bronze": settings.rewards_bronze_max_concurrent,
            "silver": settings.rewards_silver_max_concurrent,
            "gold": settings.rewards_gold_max_concurrent,
        }
        category_map = _TIER_CATEGORY_UPGRADE  # gold→reasoning, silver→general, bronze→fast

        return {
            "model_tier": category_map.get(tier, ""),
            "rate_multiplier": multiplier_map.get(tier, 1.0),
            "max_concurrent": concurrent_map.get(tier, 0),
        }

    @staticmethod
    def get_templates() -> dict:
        return AGENT_TEMPLATES

    @staticmethod
    def get_provider_models() -> dict:
        return PROVIDER_MODELS

    @staticmethod
    def resolve_model_for(provider: str, task_category: str) -> str:
        return resolve_model(provider, task_category)
