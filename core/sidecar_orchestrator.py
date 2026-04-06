"""Sidecar orchestrator — drives the execute -> callback lifecycle.

Receives AdapterExecutionContext payloads, checks idempotency,
executes agent tasks asynchronously, and POSTs results back to
Paperclip's callback URL when complete.
"""

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from core.config import settings
from core.sidecar_models import AdapterExecutionContext, CallbackPayload

logger = logging.getLogger("agent42.sidecar.orchestrator")

# Idempotency guard: runId -> expiry timestamp (D-08)
_active_runs: dict[str, float] = {}
RUN_TTL_SECONDS = 3600  # 1 hour default


def _prune_expired_runs() -> None:
    """Remove expired entries from the active runs dict."""
    now = time.time()
    expired = [k for k, exp in _active_runs.items() if exp < now]
    for k in expired:
        del _active_runs[k]


def is_duplicate_run(run_id: str) -> bool:
    """Check if a runId is already active (idempotency guard).

    Also prunes expired entries on each call.
    Returns True if the run_id is already registered and not expired.
    """
    _prune_expired_runs()
    return run_id in _active_runs and time.time() < _active_runs[run_id]


def register_run(run_id: str) -> None:
    """Register a runId as active with TTL-based expiry."""
    _active_runs[run_id] = time.time() + RUN_TTL_SECONDS


def unregister_run(run_id: str) -> None:
    """Remove a runId from the active runs dict after completion."""
    _active_runs.pop(run_id, None)


class SidecarOrchestrator:
    """Orchestrates sidecar execution and callback delivery."""

    def __init__(
        self,
        memory_store: Any = None,
        agent_manager: Any = None,
        effectiveness_store: Any = None,
        reward_system: Any = None,
        memory_bridge: Any = None,
        tiered_routing_bridge: Any = None,
    ):
        self.memory_store = memory_store
        self.agent_manager = agent_manager
        self.effectiveness_store = effectiveness_store
        self.reward_system = reward_system
        self.memory_bridge = memory_bridge
        self.tiered_routing_bridge = tiered_routing_bridge
        self._http: httpx.AsyncClient | None = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Lazy-init httpx client (per pitfall 6: create once, close properly)."""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def execute_async(self, run_id: str, ctx: AdapterExecutionContext) -> None:
        """Execute an agent task and POST results to Paperclip callback.

        This method runs as a background task (not awaited in the route handler).
        """
        result: dict[str, Any] = {}
        usage: dict[str, Any] = {}
        status = "completed"
        error: str | None = None

        try:
            logger.info(
                "Executing run %s for agent %s (wake_reason=%s)",
                run_id,
                ctx.agent_id,
                ctx.wake_reason,
            )

            # Step 1: Memory recall with hard timeout (MEM-01, MEM-02, per D-01, D-02)
            recalled_memories: list[dict] = []
            if self.memory_bridge and ctx.agent_id:
                try:
                    recalled_memories = await asyncio.wait_for(
                        self.memory_bridge.recall(
                            query=ctx.context.get("taskDescription", "") or ctx.task_id,
                            agent_id=ctx.agent_id,
                            company_id=ctx.company_id,
                            top_k=5,
                            run_id=run_id,
                        ),
                        timeout=0.2,  # 200ms hard limit (MEM-02)
                    )
                    logger.info(
                        "Recalled %d memories for agent %s in run %s",
                        len(recalled_memories),
                        ctx.agent_id,
                        run_id,
                    )
                except TimeoutError:
                    logger.warning(
                        "Memory recall timed out for run %s — proceeding without memories",
                        run_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "Memory recall failed for run %s: %s — proceeding without memories",
                        run_id,
                        exc,
                    )

            # Step 1.5: Routing resolution (ROUTE-01 through ROUTE-04)
            # TODO(phase-27): Verify agentRole key name against real Paperclip payload
            routing = None
            if self.tiered_routing_bridge and ctx.agent_id:
                try:
                    routing = await self.tiered_routing_bridge.resolve(
                        role=ctx.context.get("agentRole", ""),
                        agent_id=ctx.agent_id,
                        preferred_provider=ctx.adapter_config.preferred_provider,
                    )
                    logger.info(
                        "Routing run %s: agent=%s role=%s tier=%s provider=%s model=%s base_cat=%s cat=%s",
                        run_id,
                        ctx.agent_id,
                        ctx.context.get("agentRole", ""),
                        routing.tier,
                        routing.provider,
                        routing.model,
                        routing.base_category,
                        routing.task_category,
                    )
                except Exception as exc:
                    logger.warning(
                        "Routing resolution failed for run %s: %s -- using defaults",
                        run_id,
                        exc,
                    )

            # Log routing decision for history queries (D-11)
            if routing and self.effectiveness_store:
                try:
                    await self.effectiveness_store.log_routing_decision(
                        run_id=run_id,
                        agent_id=ctx.agent_id,
                        company_id=ctx.company_id,
                        provider=routing.provider,
                        model=routing.model,
                        tier=routing.tier,
                        task_category=routing.task_category,
                    )
                except Exception as exc:
                    logger.debug("Failed to log routing decision: %s", exc)

            # Step 1.6: Auto-memory injection (ADV-01, D-12, D-14, D-15, D-16)
            if recalled_memories and getattr(ctx.adapter_config, "auto_memory", True):
                ctx.context["memoryContext"] = {
                    "memories": [
                        {"text": m["text"], "score": m["score"], "source": m.get("source", "")}
                        for m in recalled_memories
                    ],
                    "injectedAt": datetime.now(UTC).isoformat(),
                    "count": len(recalled_memories),
                }
                logger.info(
                    "Auto-injected %d memories into context for run %s",
                    len(recalled_memories),
                    run_id,
                )

            # Step 1.7: Strategy detection (D-17, D-18, D-19)
            strategy = ctx.context.get("strategy", "standard")
            known_strategies = {"standard", "fan-out", "wave"}
            if strategy not in known_strategies:
                logger.warning(
                    "Unknown strategy '%s' for run %s — falling back to 'standard'",
                    strategy,
                    run_id,
                )
                strategy = "standard"
            if strategy != "standard":
                logger.info(
                    "Run %s using strategy '%s' for agent %s",
                    run_id,
                    strategy,
                    ctx.agent_id,
                )

            # Step 2: Agent execution stub (Phase 24 — full AgentRuntime wired later)
            # recalled_memories stored in context for when AgentRuntime is wired (D-04)
            result = {
                "summary": f"Executed task for agent {ctx.agent_id}",
                "wakeReason": ctx.wake_reason,
                "taskId": ctx.task_id,
                "recalledMemories": len(recalled_memories),
                "autoMemory": {
                    "count": len(recalled_memories),
                    "injectedAt": ctx.context.get("memoryContext", {}).get("injectedAt"),
                }
                if recalled_memories and getattr(ctx.adapter_config, "auto_memory", True)
                else None,
            }
            usage = {
                "inputTokens": 0,
                "outputTokens": 0,
                "costUsd": 0.0,
                "model": routing.model if routing else "",
                "provider": routing.provider if routing else "",
            }

            # Log spend for 24h aggregation (D-14)
            if self.effectiveness_store:
                try:
                    await self.effectiveness_store.log_spend(
                        agent_id=ctx.agent_id,
                        company_id=ctx.company_id,
                        provider=usage.get("provider", ""),
                        model=usage.get("model", ""),
                        input_tokens=usage.get("inputTokens", 0),
                        output_tokens=usage.get("outputTokens", 0),
                        cost_usd=usage.get("costUsd", 0.0),
                    )
                except Exception as exc:
                    logger.debug("Failed to log spend: %s", exc)

        except Exception as exc:
            logger.error("Run %s failed: %s", run_id, exc, exc_info=True)
            status = "failed"
            error = str(exc)

        finally:
            # Step 3: POST callback to Paperclip — never delayed by learn_async (D-05)
            await self._post_callback(run_id, status, result, usage, error)

            # Capture transcript for deferred learning extraction (D-18)
            if self.effectiveness_store and result.get("summary"):
                try:
                    await self.effectiveness_store.save_transcript(
                        run_id=run_id,
                        agent_id=ctx.agent_id,
                        company_id=ctx.company_id,
                        task_type=ctx.context.get("taskType", ""),
                        summary=result.get("summary", ""),
                    )
                except Exception as exc:
                    logger.debug("Failed to save transcript: %s", exc)

            # Step 4: Fire-and-forget learning extraction AFTER callback (MEM-03, D-05)
            if self.memory_bridge and ctx.agent_id and result.get("summary"):
                asyncio.create_task(
                    self.memory_bridge.learn_async(
                        summary=result.get("summary", ""),
                        agent_id=ctx.agent_id,
                        company_id=ctx.company_id,
                        task_type=ctx.context.get("taskType", ""),
                        run_id=run_id,
                    )
                )

            unregister_run(run_id)

    async def _post_callback(
        self,
        run_id: str,
        status: str,
        result: dict[str, Any],
        usage: dict[str, Any],
        error: str | None,
    ) -> None:
        """POST execution results back to Paperclip's callback endpoint."""
        callback_url = settings.paperclip_api_url
        if not callback_url:
            logger.warning(
                "PAPERCLIP_API_URL not configured — skipping callback for run %s",
                run_id,
            )
            return

        url = f"{callback_url.rstrip('/')}/api/heartbeat-runs/{run_id}/callback"
        payload = CallbackPayload(
            run_id=run_id,
            status=status,
            result=result,
            usage=usage,
            error=error,
        )

        try:
            client = await self._get_http_client()
            resp = await client.post(
                url,
                json=payload.model_dump(by_alias=True),
                headers={"Content-Type": "application/json"},
            )
            logger.info(
                "Callback for run %s: %s %s",
                run_id,
                resp.status_code,
                url,
            )
        except Exception as exc:
            logger.error(
                "Callback failed for run %s to %s: %s",
                run_id,
                url,
                exc,
            )

    async def shutdown(self) -> None:
        """Close the httpx client (per pitfall 6)."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None
