"""TieredRoutingBridge — maps Paperclip roles to Frood provider/model selection.

Composes RewardSystem + TierDeterminator + resolve_model() into a single
resolve() method. Follows the MemoryBridge pattern: dedicated core/*.py class,
constructed once in create_sidecar_app(), injected into SidecarOrchestrator.

Design decisions:
- role→category mapping is a static dict constant (D-01, D-02, D-03)
- Tier upgrade delegates to resolve_model() — no duplicate logic (D-05)
- Provider chain: preferredProvider > zen > openrouter > anthropic > openai (D-06)
- obs_count=0 is passed to TierDeterminator as safe default (Pitfall 1 from
  RESEARCH.md): new sidecar agents start provisional, never prematurely Bronze.
  Wire real obs_count from EffectivenessStore in Phase 27+.
- cost_estimate=0.0 until AgentRuntime wires real token counts (D-09)
- reward_system=None is gracefully handled: tier="" returned, no crash (ROUTE-02)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("frood.sidecar.routing")

# ---------------------------------------------------------------------------
# Role → Task Category Mapping (ROUTE-01, D-01, D-02, D-03)
# ---------------------------------------------------------------------------
# Maps Paperclip agent roles to Frood task categories.
# Unknown or empty roles fall back to "general" (D-02).
# No prefix-tolerant matching — roles are a known enum (D-03).

_ROLE_CATEGORY_MAP: dict[str, str] = {
    "engineer": "coding",
    "cto": "coding",
    "researcher": "research",
    "writer": "content",
    "cmo": "marketing",
    "pm": "general",
    "analyst": "analysis",
    "designer": "content",
    "qa": "coding",
    "devops": "coding",
    "ceo": "reasoning",
    "cfo": "analysis",
    "general": "general",
}

# Direct task-type-to-category mapping (takes priority over role mapping)
_TASK_TYPE_CATEGORY_MAP: dict[str, str] = {
    "research": "research",
    "coding": "coding",
    "content": "content",
    "marketing": "marketing",
    "analysis": "analysis",
    "reasoning": "reasoning",
    "monitoring": "monitoring",
    "fast": "fast",
    "general": "general",
}

# ---------------------------------------------------------------------------
# Static Pricing Table (ROUTE-04, D-10)
# ---------------------------------------------------------------------------
# Per-token costs: (input_per_token_usd, output_per_token_usd)
# Values based on published pricing as of 2026-03-29.
# Synthetic values are estimates — update when Synthetic.new publishes
# official pricing. See RESEARCH.md for confidence levels.

_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-haiku-4-5-20251001": (0.80 / 1_000_000, 4.00 / 1_000_000),
    "claude-sonnet-4-6-20260217": (3.00 / 1_000_000, 15.00 / 1_000_000),
    "claude-opus-4-6-20260205": (15.00 / 1_000_000, 75.00 / 1_000_000),
    # OpenRouter
    "google/gemini-2.0-flash-001": (0.10 / 1_000_000, 0.40 / 1_000_000),
    "anthropic/claude-sonnet-4-6": (3.00 / 1_000_000, 15.00 / 1_000_000),
    "anthropic/claude-opus-4-6": (15.00 / 1_000_000, 75.00 / 1_000_000),
    # OpenAI
    "gpt-4o-mini": (0.15 / 1_000_000, 0.60 / 1_000_000),
    "gpt-4o": (2.50 / 1_000_000, 10.00 / 1_000_000),
    "o3": (10.00 / 1_000_000, 40.00 / 1_000_000),
    # Zen — free tier models (zero cost)
    "qwen3.6-plus-free": (0.0, 0.0),
    "minimax-m2.5-free": (0.0, 0.0),
    "nemotron-3-super-free": (0.0, 0.0),
    "big-pickle": (0.0, 0.0),
}

# Fallback pricing for unknown models: conservative estimate
_PRICING_FALLBACK: tuple[float, float] = (5.00 / 1_000_000, 15.00 / 1_000_000)


# ---------------------------------------------------------------------------
# RoutingDecision Dataclass (D-12)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutingDecision:
    """Immutable result of a TieredRoutingBridge.resolve() call.

    Fields:
        provider:       Provider key, e.g. "synthetic", "anthropic", "openrouter"
        model:          Resolved model ID string
        tier:           Agent reward tier: "gold" / "silver" / "bronze" /
                        "provisional" / "" (when reward_system is None)
        task_category:  Effective category after tier upgrade (for logging observability)
        base_category:  Category from role mapping before tier upgrade applied
        cost_estimate:  Estimated cost in USD (0.0 until AgentRuntime wired, Phase 27+)
    """

    provider: str
    model: str
    tier: str
    task_category: str
    base_category: str
    cost_estimate: float


# ---------------------------------------------------------------------------
# TieredRoutingBridge (D-11, D-12, D-13, D-14)
# ---------------------------------------------------------------------------


class TieredRoutingBridge:
    """Orchestrator-owned routing interface for sidecar agents.

    Composes RewardSystem (tier lookup) + TierDeterminator (score→tier) +
    resolve_model() (provider+category+tier→model) into a single resolve() call.

    Follows the MemoryBridge architectural pattern:
    - Constructed once in create_sidecar_app()
    - Injected into SidecarOrchestrator alongside memory_bridge
    - Internal only — no HTTP endpoint in Phase 26 (endpoint deferred to Phase 28)
    """

    def __init__(
        self,
        reward_system: Any = None,
        tier_determinator: Any = None,
    ) -> None:
        self._reward_system = reward_system
        # Create a default TierDeterminator if none provided
        if tier_determinator is None:
            from core.reward_system import TierDeterminator

            tier_determinator = TierDeterminator()
        self._tier_determinator = tier_determinator

    async def resolve(
        self,
        role: str | None,
        agent_id: str,
        preferred_provider: str = "",
        preferred_model: str = "",
        task_type: str = "",
    ) -> RoutingDecision:
        """Resolve provider + model for a Paperclip agent.

        Args:
            role:               Paperclip agent role ("engineer", "researcher",
                                "cmo", etc.). Unknown/None roles fall back to
                                "general" category.
            agent_id:           Agent identifier for tier lookup.
            preferred_provider: Optional provider override. When set,
                                this provider is used regardless of other config.
            preferred_model:    Optional model override. When set, skip all
                                category/tier resolution and use this model directly.
            task_type:          Optional task type hint from the execution context
                                (e.g. "research", "coding"). Takes priority over
                                role-based category mapping when present.

        Returns:
            RoutingDecision with resolved provider, model, tier, and categories.
        """
        from core.agent_manager import _TIER_CATEGORY_UPGRADE, resolve_model

        # 1. Tier determination
        if self._reward_system is None:
            tier = ""
        else:
            score = await self._reward_system.score(agent_id)
            tier = self._tier_determinator.determine(score, observation_count=0)

        # 2. Category resolution: task_type > role mapping > "general"
        if task_type and task_type in _TASK_TYPE_CATEGORY_MAP:
            base_category = _TASK_TYPE_CATEGORY_MAP[task_type]
        else:
            base_category = _ROLE_CATEGORY_MAP.get(role or "", "general")

        # 3. Provider selection chain
        if preferred_provider:
            provider = preferred_provider
        elif os.environ.get("ZEN_API_KEY"):
            provider = "zen"
        elif os.environ.get("OPENROUTER_API_KEY"):
            provider = "openrouter"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif os.environ.get("OPENAI_API_KEY"):
            provider = "openai"
        else:
            provider = "zen"

        # 4. Model resolution: preferred_model > resolve_model(category+tier)
        if preferred_model:
            model = preferred_model
        else:
            model = resolve_model(provider, base_category, tier)

        # 5. Effective task_category for observability
        task_category = _TIER_CATEGORY_UPGRADE.get(tier, base_category)

        logger.debug(
            "Routing: agent=%s role=%r task_type=%r tier=%s base_cat=%s "
            "task_cat=%s provider=%s model=%s preferred_model=%r",
            agent_id, role, task_type, tier, base_category,
            task_category, provider, model, preferred_model,
        )

        return RoutingDecision(
            provider=provider,
            model=model,
            tier=tier,
            task_category=task_category,
            base_category=base_category,
            cost_estimate=0.0,
        )

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost in USD from static pricing table (ROUTE-04, D-10).

        Args:
            model:         Model ID string (e.g. "claude-sonnet-4-6-20260217")
            input_tokens:  Number of input/prompt tokens
            output_tokens: Number of output/completion tokens

        Returns:
            Estimated cost in USD, or 0.0 when token counts are zero.
            Uses _PRICING_FALLBACK for models not in the pricing table.
        """
        price = _MODEL_PRICING.get(model, _PRICING_FALLBACK)
        return round(input_tokens * price[0] + output_tokens * price[1], 8)
