"""Agent42 sidecar — lightweight FastAPI server for Paperclip integration.

create_sidecar_app() returns a FastAPI instance with only sidecar routes:
- GET  /sidecar/health                    — public, no auth (D-05)
- POST /sidecar/execute                   — Bearer auth required (D-04)
- POST /memory/recall                     — Bearer auth required (MEM-04, D-13)
- POST /memory/store                      — Bearer auth required (MEM-04, D-14)
- POST /routing/resolve                   — Bearer auth required (PLUG-04, Phase 28)
- POST /effectiveness/recommendations     — Bearer auth required (PLUG-05, Phase 28)
- POST /mcp/tool                          — Bearer auth required (PLUG-06, Phase 28)
- GET  /agent/{agent_id}/profile          — Bearer auth required (Phase 29, D-09)
- GET  /agent/{agent_id}/effectiveness    — Bearer auth required (Phase 29, D-10)
- GET  /agent/{agent_id}/routing-history  — Bearer auth required (Phase 29, D-11)
- GET  /memory/run-trace/{run_id}         — Bearer auth required (Phase 29, D-13)
- GET  /agent/{agent_id}/spend            — Bearer auth required (Phase 29, D-14)
- POST /memory/extract                    — Bearer auth required (Phase 29, D-19)

This is a SEPARATE app factory from dashboard/server.py:create_app() per D-01.
"""

import asyncio
import logging
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.agent_manager import PROVIDER_MODELS
from core.config import settings
from core.memory_bridge import MemoryBridge
from core.reward_system import TierDeterminator
from core.sidecar_models import (
    AdapterExecutionContext,
    AgentEffectivenessResponse,
    AgentProfileResponse,
    AgentSpendResponse,
    EffectivenessRequest,
    EffectivenessResponse,
    ExecuteResponse,
    ExtractLearningsRequest,
    ExtractLearningsResponse,
    HealthResponse,
    MCPToolRequest,
    MCPToolResponse,
    MemoryRecallRequest,
    MemoryRecallResponse,
    MemoryRunTraceResponse,
    MemoryStoreRequest,
    MemoryStoreResponse,
    MemoryTraceItem,
    ModelsResponse,
    ProviderModelItem,
    ProviderStatusDetail,
    RoutingHistoryEntry,
    RoutingHistoryResponse,
    RoutingResolveRequest,
    RoutingResolveResponse,
    SidecarAppActionResponse,
    SidecarAppItem,
    SidecarAppsResponse,
    SidecarSettingsKeyEntry,
    SidecarSettingsResponse,
    SidecarSettingsUpdateRequest,
    SidecarSettingsUpdateResponse,
    SidecarSkillItem,
    SidecarSkillsResponse,
    SidecarToolItem,
    SidecarToolsResponse,
    SpendEntry,
    TaskTypeStats,
    ToolEffectivenessItem,
)
from core.sidecar_orchestrator import (
    SidecarOrchestrator,
    is_duplicate_run,
    register_run,
)
from core.tiered_routing_bridge import TieredRoutingBridge
from dashboard.auth import get_current_user

logger = logging.getLogger("frood.sidecar")


class SidecarTokenRequest(BaseModel):
    """Request body for POST /sidecar/token. D-05: dispatch on field presence."""

    username: str = ""
    password: str = ""
    api_key: str = ""


class SidecarTokenResponse(BaseModel):
    """Response for POST /sidecar/token. D-07: 24h token."""

    token: str
    expires_in: int = 86400


def create_sidecar_app(
    memory_store: Any = None,
    agent_manager: Any = None,
    effectiveness_store: Any = None,
    reward_system: Any = None,
    qdrant_store: Any = None,
    mcp_registry: Any = None,  # MCPRegistryAdapter for /mcp/tool proxy (Phase 28)
    tool_registry: Any = None,  # Phase 36: tools listing
    skill_loader: Any = None,  # Phase 36: skills listing
    app_manager: Any = None,  # Phase 36: apps listing / start / stop
    key_store: Any = None,  # Phase 36: settings management
    device_store: Any = None,  # Phase 53: DeviceStore for /sidecar/token api_key path (D-09)
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
        mcp_registry: MCPRegistryAdapter instance or None (for /mcp/tool proxy)
        tool_registry: ToolRegistry instance or None (Phase 36: GET /tools)
        skill_loader: SkillLoader instance or None (Phase 36: GET /skills)
        app_manager: AppManager instance or None (Phase 36: GET/POST /apps)
        key_store: KeyStore instance or None (Phase 36: GET/POST /settings)
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

        # Add per-provider availability to provider_status dict (D-12)
        configured_providers: dict[str, bool] = {}
        for attr in (
            "openai_api_key",
            "anthropic_api_key",
            "openrouter_api_key",
            "groq_api_key",
            "synthetic_api_key",
        ):
            provider_name = attr.replace("_api_key", "")
            configured_providers[provider_name] = bool(getattr(settings, attr, ""))
        provider_status["configured"] = configured_providers

        # Build providers_detail list (D-07)
        providers_detail_list: list[ProviderStatusDetail] = []
        _provider_key_map = {
            "zen": "zen_api_key",
            "openrouter": "openrouter_api_key",
            "anthropic": "anthropic_api_key",
            "openai": "openai_api_key",
            "synthetic": "synthetic_api_key",
        }
        for pname, attr_name in _provider_key_map.items():
            is_configured = bool(getattr(settings, attr_name, ""))
            model_count = len(set(PROVIDER_MODELS.get(pname, {}).values()))
            providers_detail_list.append(
                ProviderStatusDetail(
                    name=pname,
                    configured=is_configured,
                    connected=is_configured,  # Stub: equals configured until Phase 32/33 add real probes
                    model_count=model_count,
                    last_check=0.0,  # Stub: Phase 32/33 will populate with real check timestamps
                )
            )

        return HealthResponse(
            status="ok",
            memory=memory_status,
            providers=provider_status,
            providers_detail=providers_detail_list,
            qdrant=qdrant_status,
        )

    # -- Models endpoint (public -- no auth, consistent with /sidecar/health) --

    @app.get("/sidecar/models", response_model=ModelsResponse)
    async def sidecar_models() -> ModelsResponse:
        """Return available models grouped by provider (D-05).

        Public endpoint — no Bearer auth required. Consistent with /sidecar/health.
        Currently returns models from PROVIDER_MODELS registry.
        Will return dynamic Synthetic.new models once Phase 33 is implemented.
        """
        items: list[ProviderModelItem] = []
        provider_names: list[str] = []
        for provider, category_map in PROVIDER_MODELS.items():
            provider_names.append(provider)
            model_to_cats: dict[str, list[str]] = {}
            for cat, model_id in category_map.items():
                model_to_cats.setdefault(model_id, []).append(cat)
            for model_id, cats in model_to_cats.items():
                items.append(
                    ProviderModelItem(
                        model_id=model_id,
                        display_name=model_id,
                        provider=provider,
                        categories=sorted(cats),
                        available=True,
                    )
                )
        # Synthetic.new stub — Phase 33 will populate with real models
        if "synthetic" not in provider_names:
            provider_names.append("synthetic")
        return ModelsResponse(models=items, providers=sorted(provider_names))

    # -- Token endpoint (public — issues JWTs for external consumers, Phase 53) --

    @app.post("/sidecar/token", response_model=SidecarTokenResponse)
    async def sidecar_token(req: SidecarTokenRequest, request: Request) -> SidecarTokenResponse:
        """Issue a JWT for external consumers (Paperclip adapters, automation).

        Accepts either username+password OR api_key (ak_... device key).
        Rate limited on both paths. DeviceStore is optional — omitted means
        password-only mode. AUTH-01, D-05 through D-09.
        """
        from dashboard.auth import check_rate_limit, create_token, verify_password

        client_ip = request.client.host if request.client else "unknown"

        if not check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Too many attempts.")

        if req.api_key:
            # Device key path (D-06)
            if device_store is None:
                raise HTTPException(status_code=503, detail="Device auth not available")
            device = device_store.validate_api_key(req.api_key)
            if not device:
                raise HTTPException(status_code=401, detail="Invalid API key")
            username = f"device:{device.device_id}"
        else:
            # Password path (D-06)
            if not req.username or not req.password:
                raise HTTPException(status_code=401, detail="Invalid credentials")
            if req.username != settings.dashboard_username or not verify_password(req.password):
                raise HTTPException(status_code=401, detail="Invalid credentials")
            username = req.username

        token = create_token(username)
        return SidecarTokenResponse(token=token, expires_in=86400)

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

    # -- Routing resolve endpoint (Bearer auth required, PLUG-04, Phase 28) --

    @app.post("/routing/resolve", response_model=RoutingResolveResponse)
    async def routing_resolve(
        req: RoutingResolveRequest,
        _user: str = Depends(get_current_user),
    ) -> RoutingResolveResponse:
        """Resolve optimal provider+model for a task type (PLUG-04)."""
        try:
            decision = await tiered_routing_bridge.resolve(
                role=req.task_type,
                agent_id=req.agent_id,
                preferred_provider="",
            )
            return RoutingResolveResponse(
                provider=decision.provider,
                model=decision.model,
                tier=decision.tier,
                task_category=decision.task_category,
            )
        except Exception as exc:
            logger.warning("Routing resolve failed: %s", exc)
            return RoutingResolveResponse(provider="", model="", tier="", task_category="")

    # -- Effectiveness recommendations endpoint (Bearer auth required, PLUG-05, Phase 28) --

    @app.post("/effectiveness/recommendations", response_model=EffectivenessResponse)
    async def effectiveness_recommendations(
        req: EffectivenessRequest,
        _user: str = Depends(get_current_user),
    ) -> EffectivenessResponse:
        """Return top tools by success rate for a task type (PLUG-05)."""
        if not effectiveness_store:
            return EffectivenessResponse(tools=[])
        try:
            recs = await effectiveness_store.get_recommendations(
                task_type=req.task_type,
                min_observations=5,
                top_k=3,
            )
            items = [
                ToolEffectivenessItem(
                    name=r.get("tool_name", r.get("name", "")),
                    success_rate=float(r.get("success_rate", 0.0)),
                    observations=int(r.get("invocations", r.get("observations", 0))),
                )
                for r in recs
            ]
            return EffectivenessResponse(tools=items)
        except Exception as exc:
            logger.warning("Effectiveness recommendations failed: %s", exc)
            return EffectivenessResponse(tools=[])

    # -- MCP tool proxy endpoint (Bearer auth + allowlist required, PLUG-06, Phase 28) --

    @app.post("/mcp/tool", response_model=MCPToolResponse)
    async def mcp_tool_proxy(
        req: MCPToolRequest,
        _user: str = Depends(get_current_user),
    ) -> MCPToolResponse | JSONResponse:
        """Execute an allowlisted MCP tool (PLUG-06, D-05 through D-09)."""
        # Allowlist check
        allowlist_str = settings.mcp_tool_allowlist
        if not allowlist_str:
            return MCPToolResponse(result=None, error="MCP tool proxy disabled (empty allowlist)")
        allowlist = {t.strip() for t in allowlist_str.split(",") if t.strip()}
        if req.tool_name not in allowlist:
            # Return 403 for non-allowlisted tools
            return JSONResponse(
                status_code=403,
                content={"result": None, "error": f"Tool '{req.tool_name}' not in allowlist"},
            )
        if not mcp_registry:
            return MCPToolResponse(result=None, error="MCP registry not available")
        try:
            content_blocks = await mcp_registry.call_tool(req.tool_name, req.params)
            # Extract text from content blocks
            texts = [getattr(b, "text", str(b)) for b in content_blocks]
            return MCPToolResponse(result="\n".join(texts), error=None)
        except Exception as exc:
            logger.warning("MCP tool proxy failed for %s: %s", req.tool_name, exc)
            return MCPToolResponse(result=None, error=str(exc))

    # -------------------------------------------------------------------------
    # Phase 29 — Plugin UI data endpoints
    # -------------------------------------------------------------------------

    @app.get("/agent/{agent_id}/profile", response_model=AgentProfileResponse)
    async def agent_profile(
        agent_id: str,
        _user: str = Depends(get_current_user),
    ) -> AgentProfileResponse:
        """Return agent tier, success rate, and task volume (D-09, D-15)."""
        if not effectiveness_store:
            return AgentProfileResponse(agent_id=agent_id)
        stats = await effectiveness_store.get_agent_stats(agent_id)
        # Determine tier using TierDeterminator with task_volume as obs_count
        tier = "bronze"
        try:
            det = TierDeterminator()
            obs_count = stats.get("task_volume", 0) if stats else 0
            score = stats.get("success_rate", 0.0) if stats else 0.0
            tier = det.determine(score=score, observation_count=obs_count)
        except Exception:
            pass
        if not stats:
            return AgentProfileResponse(agent_id=agent_id, tier=tier)
        return AgentProfileResponse(
            agent_id=agent_id,
            tier=tier,
            success_rate=stats.get("success_rate", 0.0),
            task_volume=stats.get("task_volume", 0),
            avg_speed_ms=stats.get("avg_speed", 0.0),
        )

    @app.get("/agent/{agent_id}/effectiveness", response_model=AgentEffectivenessResponse)
    async def agent_effectiveness(
        agent_id: str,
        _user: str = Depends(get_current_user),
    ) -> AgentEffectivenessResponse:
        """Return per-task-type success rate breakdown for an agent (D-10, D-15)."""
        if not effectiveness_store:
            return AgentEffectivenessResponse(agent_id=agent_id)
        rows = await effectiveness_store.get_aggregated_stats(agent_id=agent_id)
        stats = [
            TaskTypeStats(
                task_type=r.get("task_type", ""),
                success_rate=float(r.get("success_rate", 0.0)),
                count=int(r.get("invocations", r.get("count", 0))),
                avg_duration_ms=float(r.get("avg_duration_ms", r.get("avg_duration", 0.0))),
            )
            for r in rows
        ]
        return AgentEffectivenessResponse(agent_id=agent_id, stats=stats)

    @app.get("/agent/{agent_id}/routing-history", response_model=RoutingHistoryResponse)
    async def agent_routing_history(
        agent_id: str,
        limit: int = 20,
        _user: str = Depends(get_current_user),
    ) -> RoutingHistoryResponse:
        """Return recent routing decisions for an agent (D-11, D-15)."""
        if not effectiveness_store:
            return RoutingHistoryResponse(agent_id=agent_id)
        rows = await effectiveness_store.get_routing_history(agent_id, limit=limit)
        entries = [
            RoutingHistoryEntry(
                run_id=r.get("run_id", ""),
                provider=r.get("provider", ""),
                model=r.get("model", ""),
                tier=r.get("tier", ""),
                task_category=r.get("task_category", ""),
                ts=r.get("ts", 0.0),
            )
            for r in rows
        ]
        return RoutingHistoryResponse(agent_id=agent_id, entries=entries)

    @app.get("/memory/run-trace/{run_id}", response_model=MemoryRunTraceResponse)
    async def memory_run_trace(
        run_id: str,
        _user: str = Depends(get_current_user),
    ) -> MemoryRunTraceResponse:
        """Return recalled memories and extracted learnings tagged with run_id (D-13, D-15)."""
        injected: list[MemoryTraceItem] = []
        extracted: list[MemoryTraceItem] = []
        if memory_bridge and memory_bridge.memory_store:
            qdrant = getattr(memory_bridge.memory_store, "_qdrant", None)
            if qdrant and getattr(qdrant, "is_available", False):
                try:
                    from qdrant_client.models import FieldCondition, Filter, MatchValue

                    run_filter = Filter(
                        must=[FieldCondition(key="run_id", match=MatchValue(value=run_id))]
                    )
                    # Search MEMORY + HISTORY for recalled memories tagged with this run_id
                    for coll_suffix in (qdrant.MEMORY, qdrant.HISTORY):
                        try:
                            coll_name = qdrant._collection_name(coll_suffix)
                            results = qdrant._client.scroll(
                                collection_name=coll_name,
                                scroll_filter=run_filter,
                                limit=100,
                            )
                            for pt in results[0]:
                                p = pt.payload or {}
                                injected.append(
                                    MemoryTraceItem(
                                        text=p.get("text", ""),
                                        score=p.get("score", 0.0),
                                        source=p.get("source", ""),
                                    )
                                )
                        except Exception:
                            pass
                    # Search KNOWLEDGE for extracted learnings tagged with this run_id
                    try:
                        kn_name = qdrant._collection_name(qdrant.KNOWLEDGE)
                        kn_results = qdrant._client.scroll(
                            collection_name=kn_name,
                            scroll_filter=run_filter,
                            limit=100,
                        )
                        for pt in kn_results[0]:
                            p = pt.payload or {}
                            extracted.append(
                                MemoryTraceItem(
                                    text=p.get("text", ""),
                                    source=p.get("source", ""),
                                    tags=p.get("tags", []),
                                )
                            )
                    except Exception:
                        pass
                except Exception as exc:
                    logger.warning("memory_run_trace failed: %s", exc)
        return MemoryRunTraceResponse(
            run_id=run_id,
            injected_memories=injected,
            extracted_learnings=extracted,
        )

    @app.get("/agent/{agent_id}/spend", response_model=AgentSpendResponse)
    async def agent_spend(
        agent_id: str,
        hours: int = 24,
        _user: str = Depends(get_current_user),
    ) -> AgentSpendResponse:
        """Return token spend distribution grouped by provider over last N hours (D-14, D-15)."""
        if not effectiveness_store:
            return AgentSpendResponse(agent_id=agent_id, hours=hours)
        rows = await effectiveness_store.get_agent_spend(agent_id=agent_id, hours=hours)
        entries = [
            SpendEntry(
                provider=r.get("provider", ""),
                model=r.get("model", ""),
                input_tokens=r.get("input_tokens", 0),
                output_tokens=r.get("output_tokens", 0),
                cost_usd=r.get("cost_usd", 0.0),
                hour_bucket=r.get("hour_bucket", ""),
            )
            for r in rows
        ]
        total = sum(e.cost_usd for e in entries)
        return AgentSpendResponse(
            agent_id=agent_id,
            hours=hours,
            entries=entries,
            total_cost_usd=total,
        )

    @app.post("/memory/extract", response_model=ExtractLearningsResponse)
    async def memory_extract(
        req: ExtractLearningsRequest,
        _user: str = Depends(get_current_user),
    ) -> ExtractLearningsResponse:
        """Drain pending transcripts and trigger learning extraction (D-19, D-15)."""
        if not effectiveness_store or not memory_bridge:
            return ExtractLearningsResponse(extracted=0, skipped=0)
        try:
            pending = await effectiveness_store.drain_pending_transcripts(batch_size=req.batch_size)
            extracted_count = 0
            skipped = 0
            for t in pending:
                try:
                    await memory_bridge.learn_async(
                        summary=t["summary"],
                        agent_id=t["agent_id"],
                        company_id=t.get("company_id", ""),
                        task_type=t.get("task_type", ""),
                        run_id=t.get("run_id", ""),
                    )
                    extracted_count += 1
                except Exception:
                    skipped += 1
            return ExtractLearningsResponse(extracted=extracted_count, skipped=skipped)
        except Exception as exc:
            logger.warning("memory_extract failed: %s", exc)
            return ExtractLearningsResponse(extracted=0, skipped=0)

    # -------------------------------------------------------------------------
    # Phase 36 — Paperclip Integration Core endpoints
    # -------------------------------------------------------------------------

    # -- Tools listing --
    @app.get("/tools", response_model=SidecarToolsResponse)
    async def list_sidecar_tools(_user: str = Depends(get_current_user)) -> SidecarToolsResponse:
        """List all registered tools for Paperclip dashboard."""
        if tool_registry is None:
            return SidecarToolsResponse(tools=[])
        raw_tools = tool_registry.list_tools()
        items = [
            SidecarToolItem(
                name=t.get("name", ""),
                display_name=t.get("display_name", t.get("name", "")),
                description=t.get("description", ""),
                enabled=not t.get("disabled", False),
                source=t.get("source", "builtin"),
            )
            for t in raw_tools
        ]
        return SidecarToolsResponse(tools=items)

    # -- Skills listing --
    @app.get("/skills", response_model=SidecarSkillsResponse)
    async def list_sidecar_skills(_user: str = Depends(get_current_user)) -> SidecarSkillsResponse:
        """List all loaded skills for Paperclip dashboard."""
        if skill_loader is None:
            return SidecarSkillsResponse(skills=[])
        raw_skills = skill_loader.all_skills()
        items = [
            SidecarSkillItem(
                name=s.get("name", ""),
                display_name=s.get("display_name", s.get("name", "")),
                description=s.get("description", ""),
                enabled=not s.get("disabled", False),
                path=s.get("path", ""),
            )
            for s in raw_skills
        ]
        return SidecarSkillsResponse(skills=items)

    # -- Apps listing --
    @app.get("/apps", response_model=SidecarAppsResponse)
    async def list_sidecar_apps(_user: str = Depends(get_current_user)) -> SidecarAppsResponse:
        """List all sandboxed apps for Paperclip dashboard."""
        if app_manager is None:
            return SidecarAppsResponse(apps=[])
        raw_apps = (
            await app_manager.list_apps()
            if asyncio.iscoroutinefunction(app_manager.list_apps)
            else app_manager.list_apps()
        )
        items = []
        for a in raw_apps:
            items.append(
                SidecarAppItem(
                    id=getattr(a, "id", str(a)) if not isinstance(a, dict) else a.get("id", ""),
                    name=getattr(a, "name", "") if not isinstance(a, dict) else a.get("name", ""),
                    status=(
                        getattr(a, "status", "stopped")
                        if not isinstance(a, dict)
                        else a.get("status", "stopped")
                    ),
                    port=(getattr(a, "port", None) if not isinstance(a, dict) else a.get("port")),
                    created_at=str(
                        getattr(a, "created_at", "")
                        if not isinstance(a, dict)
                        else a.get("created_at", "")
                    ),
                )
            )
        return SidecarAppsResponse(apps=items)

    # -- App start/stop actions --
    @app.post("/apps/{app_id}/start", response_model=SidecarAppActionResponse)
    async def start_sidecar_app(
        app_id: str,
        _user: str = Depends(get_current_user),
    ) -> SidecarAppActionResponse:
        """Start a sandboxed app."""
        if app_manager is None:
            return SidecarAppActionResponse(ok=False, message="App manager not available")
        try:
            await app_manager.start_app(app_id)
            return SidecarAppActionResponse(ok=True, message=f"App {app_id} started")
        except Exception as exc:
            return SidecarAppActionResponse(ok=False, message=str(exc))

    @app.post("/apps/{app_id}/stop", response_model=SidecarAppActionResponse)
    async def stop_sidecar_app(
        app_id: str,
        _user: str = Depends(get_current_user),
    ) -> SidecarAppActionResponse:
        """Stop a sandboxed app."""
        if app_manager is None:
            return SidecarAppActionResponse(ok=False, message="App manager not available")
        try:
            await app_manager.stop_app(app_id)
            return SidecarAppActionResponse(ok=True, message=f"App {app_id} stopped")
        except Exception as exc:
            return SidecarAppActionResponse(ok=False, message=str(exc))

    # -- Settings management --
    @app.get("/settings", response_model=SidecarSettingsResponse)
    async def get_sidecar_settings(
        _user: str = Depends(get_current_user),
    ) -> SidecarSettingsResponse:
        """Return masked API keys for Paperclip settings page."""
        if key_store is None:
            return SidecarSettingsResponse(keys=[])
        from core.key_store import ADMIN_CONFIGURABLE_KEYS

        masked = key_store.get_masked_keys()
        items = [
            SidecarSettingsKeyEntry(
                name=key_name,
                masked_value=masked.get(key_name, {}).get("masked_value", ""),
                is_set=masked.get(key_name, {}).get("configured", False),
                source=masked.get(key_name, {}).get("source", "none"),
            )
            for key_name in sorted(ADMIN_CONFIGURABLE_KEYS)
        ]
        return SidecarSettingsResponse(keys=items)

    @app.post("/settings", response_model=SidecarSettingsUpdateResponse)
    async def update_sidecar_settings(
        req: SidecarSettingsUpdateRequest,
        _user: str = Depends(get_current_user),
    ) -> SidecarSettingsUpdateResponse:
        """Update a single API key from Paperclip settings page."""
        from fastapi import HTTPException as _HTTPException

        from core.key_store import ADMIN_CONFIGURABLE_KEYS

        if key_store is None:
            raise _HTTPException(status_code=503, detail="Key store not available")
        if req.key_name not in ADMIN_CONFIGURABLE_KEYS:
            raise _HTTPException(status_code=400, detail=f"Key {req.key_name} is not configurable")
        if req.value == "":
            key_store.delete_key(req.key_name)
        else:
            key_store.set_key(req.key_name, req.value)
        return SidecarSettingsUpdateResponse(ok=True, key_name=req.key_name)

    # -- Memory stats proxy (D-13) --
    @app.get("/memory-stats")
    async def sidecar_memory_stats(
        _user: str = Depends(get_current_user),
    ):
        """Proxy memory stats for Paperclip settings page (per D-13)."""
        try:
            from dashboard.server import _memory_stats

            avg_latency = _memory_stats["total_latency_ms"] / max(_memory_stats["recall_count"], 1)
            return {
                "recall_count": _memory_stats["recall_count"],
                "learn_count": _memory_stats["learn_count"],
                "error_count": _memory_stats["error_count"],
                "avg_latency_ms": round(avg_latency, 1),
                "period_start": _memory_stats["last_reset"],
            }
        except Exception:
            return {
                "recall_count": 0,
                "learn_count": 0,
                "error_count": 0,
                "avg_latency_ms": 0,
                "period_start": 0,
            }

    # -- Storage status proxy (D-12) --
    @app.get("/storage-status")
    async def sidecar_storage_status(
        _user: str = Depends(get_current_user),
    ):
        """Proxy storage configuration status for Paperclip settings page (per D-12)."""
        qdrant_available = qdrant_store is not None and getattr(qdrant_store, "is_available", False)
        return {
            "mode": "qdrant" if qdrant_available else "file",
            "qdrant_available": qdrant_available,
            "learning_enabled": settings.learning_enabled,
        }

    # -- Memory purge proxy (D-15) --
    @app.delete("/memory/{collection}")
    async def sidecar_purge_memory(
        collection: str,
        _user: str = Depends(get_current_user),
    ):
        """Purge a Qdrant memory collection via sidecar (per D-15)."""
        from fastapi import HTTPException as _HTTPException

        valid_collections = {"memory", "knowledge", "history"}
        if collection not in valid_collections:
            raise _HTTPException(
                status_code=400,
                detail=f"Invalid collection '{collection}'. Must be one of: {', '.join(sorted(valid_collections))}",
            )
        if not qdrant_store or not getattr(qdrant_store, "is_available", False):
            raise _HTTPException(status_code=503, detail="Qdrant store not available")
        success = await asyncio.get_running_loop().run_in_executor(
            None, qdrant_store.clear_collection, collection
        )
        if not success:
            raise _HTTPException(status_code=500, detail=f"Failed to purge '{collection}'")
        return {"ok": True, "collection": collection}

    # -- Tool / Skill toggle endpoints (D-18, D-19) --
    class SidecarToggleRequest(BaseModel):
        enabled: bool

    @app.patch("/tools/{name}")
    async def toggle_sidecar_tool(
        name: str,
        req: SidecarToggleRequest,
        _user: str = Depends(get_current_user),
    ):
        """Toggle a tool enabled/disabled from Paperclip (per D-18/D-19)."""
        from fastapi import HTTPException as _HTTPException

        if tool_registry is None:
            raise _HTTPException(status_code=503, detail="Tool registry not available")
        if not tool_registry.set_enabled(name, req.enabled):
            raise _HTTPException(status_code=404, detail=f"Tool '{name}' not found")
        return {"name": name, "enabled": req.enabled}

    @app.patch("/skills/{name}")
    async def toggle_sidecar_skill(
        name: str,
        req: SidecarToggleRequest,
        _user: str = Depends(get_current_user),
    ):
        """Toggle a skill enabled/disabled from Paperclip (per D-18/D-19)."""
        from fastapi import HTTPException as _HTTPException

        if skill_loader is None:
            raise _HTTPException(status_code=503, detail="Skill loader not available")
        if not skill_loader.set_enabled(name, req.enabled):
            raise _HTTPException(status_code=404, detail=f"Skill '{name}' not found")
        return {"name": name, "enabled": req.enabled}

    return app
