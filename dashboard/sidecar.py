"""Agent42 sidecar — lightweight FastAPI server for Paperclip integration.

create_sidecar_app() returns a FastAPI instance with only sidecar routes:
- GET  /sidecar/health   — public, no auth (D-05)
- POST /sidecar/execute  — Bearer auth required (D-04)
- POST /memory/recall    — Bearer auth required (MEM-04, D-13)
- POST /memory/store     — Bearer auth required (MEM-04, D-14)

This is a SEPARATE app factory from dashboard/server.py:create_app() per D-01.
"""

import asyncio
import logging
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI

from core.memory_bridge import MemoryBridge
from core.reward_system import TierDeterminator
from core.sidecar_models import (
    AdapterExecutionContext,
    ExecuteResponse,
    HealthResponse,
    MemoryRecallRequest,
    MemoryRecallResponse,
    MemoryStoreRequest,
    MemoryStoreResponse,
)
from core.sidecar_orchestrator import (
    SidecarOrchestrator,
    is_duplicate_run,
    register_run,
)
from core.tiered_routing_bridge import TieredRoutingBridge
from dashboard.auth import get_current_user

logger = logging.getLogger("agent42.sidecar")


def create_sidecar_app(
    memory_store: Any = None,
    agent_manager: Any = None,
    effectiveness_store: Any = None,
    reward_system: Any = None,
    qdrant_store: Any = None,
) -> FastAPI:
    """Create a lightweight FastAPI application for sidecar mode.

    Takes the same core service objects as create_app() but mounts
    only sidecar routes. No static file serving, no WebSocket manager,
    no dashboard UI.

    Args:
        memory_store: MemoryStore instance (for health check + future memory bridge)
        agent_manager: AgentManager instance (for agent config lookup)
        effectiveness_store: EffectivenessStore instance (for recording outcomes)
        reward_system: RewardSystem instance or None (for tier-based routing)
        qdrant_store: QdrantStore instance or None (for health check)
    """
    app = FastAPI(
        title="Agent42 Sidecar",
        description="Paperclip integration sidecar — adapter-friendly execution backend",
        docs_url=None,  # No Swagger UI in sidecar
        redoc_url=None,  # No ReDoc in sidecar
    )

    # Instantiate MemoryBridge once and share between routes and orchestrator (per P6)
    memory_bridge = MemoryBridge(memory_store=memory_store)

    # Construct TieredRoutingBridge once, share between orchestrator requests (per D-11, D-14)
    tiered_routing_bridge = TieredRoutingBridge(
        reward_system=reward_system,
        tier_determinator=TierDeterminator(),
    )

    orchestrator = SidecarOrchestrator(
        memory_store=memory_store,
        agent_manager=agent_manager,
        effectiveness_store=effectiveness_store,
        reward_system=reward_system,
        memory_bridge=memory_bridge,
        tiered_routing_bridge=tiered_routing_bridge,
    )

    @app.on_event("shutdown")
    async def _shutdown():
        await orchestrator.shutdown()

    # -- Health endpoint (public -- no auth per D-05) --

    @app.get("/sidecar/health", response_model=HealthResponse)
    async def sidecar_health() -> HealthResponse:
        """Return sidecar health status including memory, provider, and Qdrant connectivity.

        Public endpoint — no Bearer auth required. Matches the dashboard /health pattern
        and enables Paperclip testEnvironment() probe before credentials are provisioned.
        """
        memory_status: dict[str, Any] = {"available": memory_store is not None}
        qdrant_status: dict[str, Any] = {"available": qdrant_store is not None}
        provider_status: dict[str, Any] = {"available": True}

        # Check Qdrant connectivity if available
        if qdrant_store is not None:
            try:
                info = await qdrant_store.health_check()
                qdrant_status.update(info)
            except Exception as exc:
                qdrant_status["available"] = False
                qdrant_status["error"] = str(exc)

        return HealthResponse(
            status="ok",
            memory=memory_status,
            providers=provider_status,
            qdrant=qdrant_status,
        )

    # -- Execute endpoint (Bearer auth required per D-04) --

    @app.post(
        "/sidecar/execute",
        response_model=ExecuteResponse,
        status_code=202,
    )
    async def sidecar_execute(
        ctx: AdapterExecutionContext,
        background_tasks: BackgroundTasks,
        _user: str = Depends(get_current_user),
    ) -> ExecuteResponse:
        """Accept a Paperclip heartbeat execution request.

        Returns 202 Accepted immediately and executes the task in the background.
        When execution completes, results are POSTed to Paperclip's callback URL.

        Idempotency: if ctx.run_id is already active, returns without re-executing (D-08).
        """
        # Idempotency guard (D-08)
        if is_duplicate_run(ctx.run_id):
            logger.info("Duplicate run %s — returning cached acceptance", ctx.run_id)
            return ExecuteResponse(
                status="accepted",
                external_run_id=ctx.run_id,
                deduplicated=True,
            )

        # Register and launch background execution
        register_run(ctx.run_id)
        background_tasks.add_task(orchestrator.execute_async, ctx.run_id, ctx)

        logger.info(
            "Accepted run %s for agent %s (wake_reason=%s)",
            ctx.run_id,
            ctx.agent_id,
            ctx.wake_reason,
        )

        return ExecuteResponse(
            status="accepted",
            external_run_id=ctx.run_id,
            deduplicated=False,
        )

    # -- Memory recall endpoint (Bearer auth required per D-15) --

    @app.post("/memory/recall", response_model=MemoryRecallResponse)
    async def memory_recall(
        req: MemoryRecallRequest,
        _user: str = Depends(get_current_user),
    ) -> MemoryRecallResponse:
        """Retrieve relevant memories scoped to agent_id/company_id (MEM-04, D-13)."""
        if not memory_bridge or not memory_bridge.memory_store:
            return MemoryRecallResponse(memories=[])
        try:
            memories = await asyncio.wait_for(
                memory_bridge.recall(
                    query=req.query,
                    agent_id=req.agent_id,
                    company_id=req.company_id,
                    top_k=req.top_k,
                    score_threshold=req.score_threshold,
                ),
                timeout=0.2,
            )
        except TimeoutError:
            memories = []
        except Exception as exc:
            logger.warning("Memory recall route failed: %s", exc)
            memories = []
        return MemoryRecallResponse(
            memories=[
                {
                    "text": m["text"],
                    "score": m["score"],
                    "source": m.get("source", ""),
                    "metadata": m.get("metadata", {}),
                }
                for m in memories
            ]
        )

    # -- Memory store endpoint (Bearer auth required per D-15) --

    @app.post("/memory/store", response_model=MemoryStoreResponse)
    async def memory_store_endpoint(
        req: MemoryStoreRequest,
        _user: str = Depends(get_current_user),
    ) -> MemoryStoreResponse:
        """Store a pre-extracted learning scoped to agent_id/company_id (MEM-04, D-14)."""
        if not memory_bridge or not memory_bridge.memory_store:
            return MemoryStoreResponse(stored=False, point_id="")
        try:
            embeddings = memory_bridge.memory_store.embeddings
            if not embeddings or not embeddings.is_available:
                return MemoryStoreResponse(stored=False, point_id="")

            vector = await embeddings.embed_text(req.text)
            qdrant = memory_bridge.memory_store._qdrant
            if not qdrant or not qdrant.is_available:
                return MemoryStoreResponse(stored=False, point_id="")

            import time

            from memory.qdrant_store import QdrantStore

            payload = {
                "text": req.text,
                "section": req.section,
                "tags": req.tags,
                "agent_id": req.agent_id,
                "company_id": req.company_id,
                "source": "plugin_store",
                "timestamp": time.time(),
            }

            point_id = qdrant._make_point_id(req.text, f"plugin:{req.agent_id}")
            success = await asyncio.to_thread(
                qdrant.upsert_single,
                QdrantStore.KNOWLEDGE,
                req.text,
                vector,
                payload,
            )
            return MemoryStoreResponse(stored=success, point_id=point_id if success else "")
        except Exception as exc:
            logger.warning("Memory store route failed: %s", exc)
            return MemoryStoreResponse(stored=False, point_id="")

    return app
