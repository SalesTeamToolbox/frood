"""TieredRoutingBridge — maps Paperclip roles to Agent42 provider/model selection.

Composes RewardSystem + TierDeterminator + resolve_model() into a single
resolve() method. Follows the MemoryBridge pattern: dedicated core/*.py class,
constructed once in create_sidecar_app(), injected into SidecarOrchestrator.

Design decisions:
- role→category mapping is a static dict constant (D-01, D-02, D-03)
- Tier upgrade delegates to resolve_model() — no duplicate logic (D-05)
- Provider chain: preferredProvider > synthetic (with key) > anthropic (D-06)
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

logger = logging.getLogger("agent42.sidecar.routing")

# ---------------------------------------------------------------------------
# Role → Task Category Mapping (ROUTE-01, D-01, D-02, D-03)
# ---------------------------------------------------------------------------
# Maps Paperclip agent roles to Agent42 task categories.
# Unknown or empty roles fall back to "general" (D-02).
# No prefix-tolerant matching — roles are a known enum (D-03).

_ROLE_CATEGORY_MAP: dict[str, str] = {
    "engineer": "coding",
    "researcher": "research",
    "writer": "content",
    "analyst": "strategy",
    # Note: "analyst" → "strategy" resolves via general-fallback on synthetic provider
    # because PROVIDER_MODELS["synthetic"] has no "strategy" key. This is D-07
    # intended behavior: resolve_model() falls back to "general" on unmapped categories.
}

# ---------------------------------------------------------------------------
# Static Pricing Table (ROUTE-04, D-10)
# ---------------------------------------------------------------------------
# Per-token costs: (input_per_token_usd, output_per_token_usd)
# Values based on published pricing as of 2026-03-29.
# Synthetic (StrongWall) values are estimates — update when StrongWall publishes
# official pricing. See RESEARCH.md for confidence levels.

_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-haiku-4-5-20251001": (0.80 / 1_000_000, 4.00 / 1_000_000),
    "claude-sonnet-4-6-20260217": (3.00 / 1_000_000, 15.00 / 1_000_000),
    "claude-opus-4-6-20260205": (15.00 / 1_000_000, 75.00 / 1_000_000),
    # Synthetic (StrongWall) — estimated pricing, LOW confidence
    "hf:zai-org/GLM-4.7-Flash": (0.10 / 1_000_000, 0.30 / 1_000_000),
    "hf:zai-org/GLM-4.7": (0.50 / 1_000_000, 1.50 / 1_000_000),
    "hf:moonshotai/Kimi-K2-Thinking": (2.00 / 1_000_000, 8.00 / 1_000_000),
    "hf:Qwen/Qwen3-Coder-480B-A35B-Instruct": (1.00 / 1_000_000, 3.00 / 1_000_000),
    "hf:Qwen/Qwen3.5-397B-A17B": (1.00 / 1_000_000, 3.00 / 1_000_000),
    "hf:moonshotai/Kimi-K2.5": (1.00 / 1_000_000, 3.00 / 1_000_000),
    "hf:deepseek-ai/DeepSeek-R1-0528": (2.00 / 1_000_000, 8.00 / 1_000_000),
    "hf:meta-llama/Llama-3.3-70B-Instruct": (0.30 / 1_000_000, 0.80 / 1_000_000),
    "hf:MiniMaxAI/MiniMax-M2.5": (0.50 / 1_000_000, 1.50 / 1_000_000),
    # OpenRouter
    "google/gemini-2.0-flash-001": (0.10 / 1_000_000, 0.40 / 1_000_000),
    "anthropic/claude-sonnet-4-6": (3.00 / 1_000_000, 15.00 / 1_000_000),
    "anthropic/claude-opus-4-6": (15.00 / 1_000_000, 75.00 / 1_000_000),
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
    ) -> RoutingDecision:
        """Resolve provider + model for a Paperclip agent role.

        Args:
            role:               Paperclip agent role ("engineer", "researcher",
                                "writer", "analyst", or any string). Unknown/None
                                roles fall back to "general" category (D-02).
            agent_id:           Agent identifier for tier lookup.
            preferred_provider: Optional provider override (D-06). When set,
                                this provider is used regardless of other config.

        Returns:
            RoutingDecision with resolved provider, model, tier, categories,
            and cost_estimate=0.0 (populated in Phase 27+ when AgentRuntime
            wires real token counts, per D-09).
        """
        from core.agent_manager import _TIER_CATEGORY_UPGRADE, resolve_model

        # 1. Tier determination (ROUTE-02, D-04)
        #    Graceful degradation: when reward_system is None, skip tier lookup
        #    and return tier="" (no upgrade applied).
        if self._reward_system is None:
            tier = ""
        else:
            # obs_count=0 is the safe default (Pitfall 1 from RESEARCH.md).
            # TierDeterminator returns "provisional" when obs_count < min_observations (default 10).
            # This prevents premature Bronze assignment for new sidecar agents.
            # TODO (Phase 27): wire real obs_count from EffectivenessStore.get_agent_stats()
            score = await self._reward_system.score(agent_id)
            tier = self._tier_determinator.determine(score, observation_count=0)

        # 2. Role → base category (ROUTE-01, D-01, D-02)
        base_category = _ROLE_CATEGORY_MAP.get(role or "", "general")

        # 3. Provider selection chain (ROUTE-03, D-06, D-07, D-08)
        if preferred_provider:
            provider = preferred_provider  # (1) explicit override
        elif os.environ.get("SYNTHETIC_API_KEY"):
            provider = "synthetic"  # (2) L1 workhorse default
        else:
            provider = "anthropic"  # (3) fallback when synthetic key missing

        # 4. resolve_model() handles: tier upgrade + category→model + unknown-category fallback
        #    (D-05, D-07): gold→reasoning, silver→general, bronze→fast, provisional→unchanged
        model = resolve_model(provider, base_category, tier)

        # 5. Compute effective task_category for log observability (success criterion 2)
        #    This captures whether the tier upgrade changed the category.
        task_category = _TIER_CATEGORY_UPGRADE.get(tier, base_category)

        logger.debug(
            "Routing: agent=%s role=%r tier=%s base_cat=%s task_cat=%s provider=%s model=%s",
            agent_id,
            role,
            tier,
            base_category,
            task_category,
            provider,
            model,
        )

        return RoutingDecision(
            provider=provider,
            model=model,
            tier=tier,
            task_category=task_category,
            base_category=base_category,
            cost_estimate=0.0,  # D-09: populated in Phase 27+ when AgentRuntime provides tokens
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
