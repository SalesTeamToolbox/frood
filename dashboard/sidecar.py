"""Agent42 sidecar — lightweight FastAPI server for Paperclip integration.

create_sidecar_app() returns a FastAPI instance with only sidecar routes:
- GET  /sidecar/health   — public, no auth (D-05)
- POST /sidecar/execute  — Bearer auth required (D-04)

This is a SEPARATE app factory from dashboard/server.py:create_app() per D-01.
"""

import logging
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI

from core.sidecar_models import (
    AdapterExecutionContext,
    ExecuteResponse,
    HealthResponse,
)
from core.sidecar_orchestrator import (
    SidecarOrchestrator,
    is_duplicate_run,
    register_run,
)
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

    orchestrator = SidecarOrchestrator(
        memory_store=memory_store,
        agent_manager=agent_manager,
        effectiveness_store=effectiveness_store,
        reward_system=reward_system,
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

    return app
