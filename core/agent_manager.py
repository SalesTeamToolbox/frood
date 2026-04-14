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

logger = logging.getLogger("frood.agent_manager")

# Module-level settings reference — used by _get_tier_semaphore() and get_effective_limits().
# Monkeypatched in tests via monkeypatch.setattr("core.agent_manager.settings", ...).
# Deferred import avoids circular-import risk at module load time.
from core.config import settings

# ── Model mapping per provider ────────────────────────────────────────────
# Each agent task type maps to the best model per provider.
# This enables concurrent agent teams — each agent uses a different model,
# avoiding rate limit conflicts on any single model.

PROVIDER_MODELS = {
    "zen": {
        "fast": "qwen3.6-plus-free",
        "general": "minimax-m2.5-free",
        "reasoning": "nemotron-3-super-free",
        "coding": "qwen3.6-plus-free",
        "content": "big-pickle",
        "research": "nemotron-3-super-free",
        "monitoring": "qwen3.6-plus-free",
        "marketing": "minimax-m2.5-free",
        "analysis": "nemotron-3-super-free",
        "lightweight": "qwen3.6-plus-free",
    },
    "nvidia": {
        # Real NVIDIA build.nvidia.com catalog IDs — verified via /v1/models 2026-04-14.
        # The previous `:free` suffixes were fabricated and returned 404; the fake entries
        # are gone. All IDs below exist in NVIDIA's live catalog.
        "fast": "meta/llama-3.2-3b-instruct",
        "general": "qwen/qwen3.5-397b-a17b",
        "reasoning": "qwen/qwq-32b",
        "coding": "qwen/qwen3-coder-480b-a35b-instruct",
        "content": "writer/palmyra-creative-122b",
        "research": "deepseek-ai/deepseek-v3.2",
        "monitoring": "meta/llama-3.2-1b-instruct",
        "marketing": "mistralai/mistral-large-3-675b-instruct-2512",
        "analysis": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "lightweight": "meta/llama-3.2-3b-instruct",
    },
    # OpenRouter disabled 2026-04-14 — key rotation pending. Key was returning 401
    # on /chat/completions (credits exhausted or stale). Re-enable by restoring this
    # block and ensuring OPENROUTER_API_KEY is set.
    # "openrouter": {
    #     "fast": "google/gemini-2.0-flash-001",
    #     "general": "anthropic/claude-sonnet-4-6",
    #     "reasoning": "anthropic/claude-opus-4-6",
    #     "coding": "anthropic/claude-sonnet-4-6",
    #     "content": "anthropic/claude-sonnet-4-6",
    # },
    "anthropic": {
        "fast": "claude-haiku-4-5-20251001",
        "general": "claude-sonnet-4-6-20260217",
        "reasoning": "claude-opus-4-6-20260205",
        "coding": "claude-sonnet-4-6-20260217",
        "content": "claude-sonnet-4-6-20260217",
    },
    "openai": {
        "fast": "gpt-4o-mini",
        "general": "gpt-4o",
        "reasoning": "o3",
        "coding": "gpt-4o",
        "content": "gpt-4o",
    },
}


# ── Zen model refresh ──────────────────────────────────────────────────────

# Optional import for Zen API client
try:
    from providers.zen_api import get_zen_client

    _zen_client = get_zen_client()
except ImportError:
    _zen_client = None

# Optional import for NVIDIA API client
try:
    from providers.nvidia_api import get_nvidia_client

    _nvidia_client = get_nvidia_client()
except ImportError:
    _nvidia_client = None

_ZEN_FREE_MODEL_CATEGORIES = {
    "fast": "qwen3.6-plus-free",
    "general": "minimax-m2.5-free",
    "reasoning": "nemotron-3-super-free",
    "coding": "qwen3.6-plus-free",
    "content": "big-pickle",
    "research": "nemotron-3-super-free",
    "monitoring": "qwen3.6-plus-free",
    "marketing": "minimax-m2.5-free",
    "analysis": "nemotron-3-super-free",
    "lightweight": "qwen3.6-plus-free",
}

_NVIDIA_FREE_MODEL_CATEGORIES = {
    # Real NVIDIA catalog IDs only — verified 2026-04-14.
    "fast": "meta/llama-3.2-3b-instruct",
    "general": "qwen/qwen3.5-397b-a17b",
    "reasoning": "qwen/qwq-32b",
    "coding": "qwen/qwen3-coder-480b-a35b-instruct",
    "content": "writer/palmyra-creative-122b",
    "research": "deepseek-ai/deepseek-v3.2",
    "monitoring": "meta/llama-3.2-1b-instruct",
    "marketing": "mistralai/mistral-large-3-675b-instruct-2512",
    "analysis": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "lightweight": "meta/llama-3.2-3b-instruct",
}


async def refresh_zen_models_async() -> bool:
    """Refresh Zen free model mappings from the live API.

    Fetches the current model list, identifies free models (suffix '-free'),
    and remaps categories based on known model capabilities. New free models
    not in the default mapping are added to the 'general' category.

    Returns True if the mapping was updated.
    """
    global PROVIDER_MODELS

    if _zen_client is None:
        logger.warning("Zen API client not available")
        return False

    try:
        models = await _zen_client.list_models()
        if not models:
            logger.warning("No models returned from Zen API")
            return False

        free_models = [m for m in models if m.endswith("-free")]
        logger.info("Zen API returned %d models (%d free): %s", len(models), len(free_models), free_models)

        # Start with the defaults, then override with what's actually available
        new_mapping = dict(_ZEN_FREE_MODEL_CATEGORIES)

        # Remove any default models that are no longer in the API
        available_set = set(models)
        for cat, model_id in list(new_mapping.items()):
            if model_id not in available_set:
                logger.info("Zen model %s no longer available — removing from %s category", model_id, cat)
                del new_mapping[cat]

        # Add any new free models not yet mapped
        mapped_models = set(new_mapping.values())
        for model_id in free_models:
            if model_id not in mapped_models:
                logger.info("New Zen free model discovered: %s", model_id)
                # Assign to first empty category slot, or add as 'general' fallback
                if "general" not in new_mapping:
                    new_mapping["general"] = model_id
                else:
                    # Store under its own name as a discoverable category
                    new_mapping[model_id] = model_id

        # Ensure 'general' always has a mapping
        if "general" not in new_mapping and free_models:
            new_mapping["general"] = free_models[0]

        PROVIDER_MODELS["zen"] = new_mapping
        logger.info("Updated Zen model mappings: %s", new_mapping)
        return True

    except Exception as e:
        logger.error("Error refreshing Zen models: %s", e)
        return False


def refresh_zen_models(force: bool = False) -> bool:
    """Sync wrapper for refresh_zen_models_async (for non-async callers)."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        # Already in async context — can't use asyncio.run, schedule as task
        logger.warning("refresh_zen_models called from async context — use refresh_zen_models_async instead")
        return False
    except RuntimeError:
        return asyncio.run(refresh_zen_models_async())


async def refresh_nvidia_models_async() -> bool:
    """Refresh NVIDIA model mappings from the live API."""
    global PROVIDER_MODELS

    if _nvidia_client is None:
        logger.warning("NVIDIA API client not available")
        return False

    try:
        models = await _nvidia_client.list_models()
        if not models:
            logger.warning("No models returned from NVIDIA API")
            return False

        free_models = [m for m in models if ":free" in m]
        logger.info("NVIDIA API returned %d models (%d free): %s", len(models), len(free_models), free_models)

        new_mapping = dict(_NVIDIA_FREE_MODEL_CATEGORIES)
        available_set = set(models)
        for cat, model_id in list(new_mapping.items()):
            if model_id not in available_set:
                logger.info("NVIDIA model %s no longer available — removing from %s", model_id, cat)
                del new_mapping[cat]

        if "general" not in new_mapping and free_models:
            new_mapping["general"] = free_models[0]

        PROVIDER_MODELS["nvidia"] = new_mapping
        logger.info("Updated NVIDIA model mappings: %s", new_mapping)
        return True

    except Exception as e:
        logger.error("Error refreshing NVIDIA models: %s", e)
        return False


def refresh_nvidia_models(force: bool = False) -> bool:
    """Sync wrapper for refresh_nvidia_models_async."""
    import asyncio
    try:
        asyncio.get_running_loop()
        logger.warning("refresh_nvidia_models called from async context")
        return False
    except RuntimeError:
        return asyncio.run(refresh_nvidia_models_async())


async def start_zen_model_refresh_task() -> None:
    """Start a background task to refresh Zen free models at startup and every 6 hours."""
    if _zen_client is None:
        logger.info("Zen API client not available, skipping background refresh")
        return

    refresh_interval_hours = 6.0
    refresh_interval_seconds = refresh_interval_hours * 3600

    # Refresh immediately at startup
    logger.info("Refreshing Zen free models at startup...")
    try:
        success = await refresh_zen_models_async()
        if success:
            logger.info("Startup Zen model refresh succeeded")
        else:
            logger.warning("Startup Zen model refresh failed — using defaults")
    except Exception as e:
        logger.error("Startup Zen model refresh error: %s", e)

    # Then refresh periodically
    logger.info("Starting Zen model refresh loop (every %.0f hours)", refresh_interval_hours)
    while True:
        try:
            await asyncio.sleep(refresh_interval_seconds)
            await refresh_zen_models_async()
        except asyncio.CancelledError:
            logger.info("Zen model refresh task cancelled")
            break
        except Exception as e:
            logger.error("Error in Zen model refresh task: %s", e)


async def start_nvidia_model_refresh_task() -> None:
    """Start a background task to refresh NVIDIA models at startup and every 6 hours."""
    if _nvidia_client is None:
        logger.info("NVIDIA API client not available, skipping background refresh")
        return

    refresh_interval_hours = 6.0
    refresh_interval_seconds = refresh_interval_hours * 3600

    # Refresh immediately at startup
    logger.info("Refreshing NVIDIA models at startup...")
    try:
        success = await refresh_nvidia_models_async()
        if success:
            logger.info("Startup NVIDIA model refresh succeeded")
        else:
            logger.warning("Startup NVIDIA model refresh failed — using defaults")
    except Exception as e:
        logger.error("Startup NVIDIA model refresh error: %s", e)

    logger.info("Starting NVIDIA model refresh loop (every %.0f hours)", refresh_interval_hours)
    while True:
        try:
            await asyncio.sleep(refresh_interval_seconds)
            await refresh_nvidia_models_async()
        except asyncio.CancelledError:
            logger.info("NVIDIA model refresh task cancelled")
            break
        except Exception as e:
            logger.error("Error in NVIDIA model refresh task: %s", e)


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


def get_fallback_models(provider: str, task_category: str, failed_model: str) -> list[str]:
    """Get ordered list of fallback models when a model is exhausted.

    Args:
        provider: Provider key (e.g. "zen", "nvidia", "openrouter")
        task_category: Task category (e.g. "fast", "general", "reasoning")
        failed_model: The model that failed (to skip it)

    Returns:
        Ordered list of model IDs to try as fallback, excluding failed_model.
    """
    if provider not in ["zen", "nvidia"]:
        return []

    current_models = PROVIDER_MODELS.get(provider, {})
    fallback_candidates = list(current_models.values())
    fallback_candidates = [m for m in fallback_candidates if m != failed_model]
    unique_fallbacks = list(dict.fromkeys(fallback_candidates))
    return unique_fallbacks


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
            import asyncio

            from core.agent_manager import start_zen_model_refresh_task

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(start_zen_model_refresh_task())
            except RuntimeError:
                pass  # No running loop — task starts when the app runs
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
