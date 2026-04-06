"""Pydantic v2 models for the Agent42 sidecar API (Paperclip integration)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AdapterConfig(BaseModel):
    """Paperclip adapter config passed inside AdapterExecutionContext."""

    model_config = ConfigDict(populate_by_name=True)

    session_key: str = Field(default="", alias="sessionKey")
    memory_scope: str = Field(default="agent", alias="memoryScope")
    preferred_provider: str = Field(default="", alias="preferredProvider")
    agent_id: str = Field(default="", alias="agentId")
    auto_memory: bool = Field(default=True, alias="autoMemory")


class AdapterExecutionContext(BaseModel):
    """Paperclip heartbeat execution payload sent to POST /sidecar/execute."""

    model_config = ConfigDict(populate_by_name=True)

    run_id: str = Field(..., alias="runId")
    agent_id: str = Field(..., alias="agentId")
    company_id: str = Field(default="", alias="companyId")
    task_id: str = Field(default="", alias="taskId")
    wake_reason: str = Field(default="heartbeat", alias="wakeReason")
    context: dict[str, Any] = Field(default_factory=dict)
    adapter_config: AdapterConfig = Field(default_factory=AdapterConfig, alias="adapterConfig")


class ExecuteResponse(BaseModel):
    """Response body for POST /sidecar/execute (202 Accepted)."""

    model_config = ConfigDict(populate_by_name=True)

    status: str = "accepted"
    external_run_id: str = Field(default="", alias="externalRunId")
    deduplicated: bool = False


class CallbackPayload(BaseModel):
    """Payload POSTed back to Paperclip's callback endpoint on completion."""

    model_config = ConfigDict(populate_by_name=True)

    run_id: str = Field(..., alias="runId")
    status: str = "completed"  # completed | failed
    result: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class HealthResponse(BaseModel):
    """Response body for GET /sidecar/health."""

    status: str = "ok"
    memory: dict[str, Any] = Field(default_factory=dict)
    providers: dict[str, Any] = Field(default_factory=dict)
    qdrant: dict[str, Any] = Field(default_factory=dict)


class MemoryRecallRequest(BaseModel):
    """Request body for POST /memory/recall (MEM-04, D-13)."""

    model_config = ConfigDict(populate_by_name=True)

    query: str
    agent_id: str = Field(..., alias="agentId")
    company_id: str = Field(default="", alias="companyId")
    top_k: int = Field(default=5, ge=1, le=50)
    score_threshold: float = Field(default=0.25, ge=0.0, le=1.0)


class MemoryItem(BaseModel):
    """A single recalled memory entry."""

    text: str
    score: float
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryRecallResponse(BaseModel):
    """Response body for POST /memory/recall (D-13)."""

    memories: list[MemoryItem] = Field(default_factory=list)


class MemoryStoreRequest(BaseModel):
    """Request body for POST /memory/store (MEM-04, D-14)."""

    model_config = ConfigDict(populate_by_name=True)

    text: str
    section: str = ""
    tags: list[str] = Field(default_factory=list)
    agent_id: str = Field(..., alias="agentId")
    company_id: str = Field(default="", alias="companyId")


class MemoryStoreResponse(BaseModel):
    """Response body for POST /memory/store."""

    stored: bool = True
    point_id: str = ""


class MCPToolRequest(BaseModel):
    """Request body for POST /mcp/tool (PLUG-06, D-09)."""

    model_config = ConfigDict(populate_by_name=True)

    tool_name: str = Field(..., alias="toolName")
    params: dict[str, Any] = Field(default_factory=dict)


class MCPToolResponse(BaseModel):
    """Response body for POST /mcp/tool."""

    result: Any = None
    error: str | None = None


class RoutingResolveRequest(BaseModel):
    """Request body for POST /routing/resolve (PLUG-04)."""

    model_config = ConfigDict(populate_by_name=True)

    task_type: str = Field(..., alias="taskType")
    agent_id: str = Field(..., alias="agentId")
    quality_target: str = Field(default="", alias="qualityTarget")


class RoutingResolveResponse(BaseModel):
    """Response body for POST /routing/resolve."""

    model_config = ConfigDict(populate_by_name=True)

    provider: str
    model: str
    tier: str
    task_category: str = Field(default="", alias="taskCategory")


class EffectivenessRequest(BaseModel):
    """Request body for POST /effectiveness/recommendations (PLUG-05)."""

    model_config = ConfigDict(populate_by_name=True)

    task_type: str = Field(..., alias="taskType")
    agent_id: str = Field(default="", alias="agentId")


class ToolEffectivenessItem(BaseModel):
    """Single tool effectiveness entry."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    success_rate: float = Field(default=0.0, alias="successRate")
    observations: int = 0


class EffectivenessResponse(BaseModel):
    """Response body for POST /effectiveness/recommendations."""

    tools: list[ToolEffectivenessItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase 29 — Plugin UI & Learning Extraction models
# ---------------------------------------------------------------------------


class AgentProfileResponse(BaseModel):
    """Response body for GET /agent/{agent_id}/profile (D-09)."""

    model_config = ConfigDict(populate_by_name=True)

    agent_id: str = Field(..., alias="agentId")
    tier: str = "bronze"
    success_rate: float = Field(default=0.0, alias="successRate")
    task_volume: int = Field(default=0, alias="taskVolume")
    avg_speed_ms: float = Field(default=0.0, alias="avgSpeedMs")
    composite_score: float = Field(default=0.0, alias="compositeScore")


class TaskTypeStats(BaseModel):
    """Per-task-type effectiveness stats."""

    model_config = ConfigDict(populate_by_name=True)

    task_type: str = Field(default="", alias="taskType")
    success_rate: float = Field(default=0.0, alias="successRate")
    count: int = 0
    avg_duration_ms: float = Field(default=0.0, alias="avgDurationMs")


class AgentEffectivenessResponse(BaseModel):
    """Response body for GET /agent/{agent_id}/effectiveness (D-10)."""

    model_config = ConfigDict(populate_by_name=True)

    agent_id: str = Field(..., alias="agentId")
    stats: list[TaskTypeStats] = Field(default_factory=list)


class RoutingHistoryEntry(BaseModel):
    """Single routing decision entry."""

    model_config = ConfigDict(populate_by_name=True)

    run_id: str = Field(default="", alias="runId")
    provider: str = ""
    model: str = ""
    tier: str = ""
    task_category: str = Field(default="", alias="taskCategory")
    ts: float = 0.0


class RoutingHistoryResponse(BaseModel):
    """Response body for GET /agent/{agent_id}/routing-history (D-11)."""

    model_config = ConfigDict(populate_by_name=True)

    agent_id: str = Field(..., alias="agentId")
    entries: list[RoutingHistoryEntry] = Field(default_factory=list)


class MemoryTraceItem(BaseModel):
    """A single recalled memory or extracted learning in a run trace."""

    text: str = ""
    score: float = 0.0
    source: str = ""
    tags: list[str] = Field(default_factory=list)


class MemoryRunTraceResponse(BaseModel):
    """Response body for GET /memory/run-trace/{run_id} (D-13)."""

    model_config = ConfigDict(populate_by_name=True)

    run_id: str = Field(..., alias="runId")
    injected_memories: list[MemoryTraceItem] = Field(default_factory=list, alias="injectedMemories")
    extracted_learnings: list[MemoryTraceItem] = Field(
        default_factory=list, alias="extractedLearnings"
    )


class SpendEntry(BaseModel):
    """Single spend aggregation row."""

    model_config = ConfigDict(populate_by_name=True)

    provider: str = ""
    model: str = ""
    input_tokens: int = Field(default=0, alias="inputTokens")
    output_tokens: int = Field(default=0, alias="outputTokens")
    cost_usd: float = Field(default=0.0, alias="costUsd")
    hour_bucket: str = Field(default="", alias="hourBucket")


class AgentSpendResponse(BaseModel):
    """Response body for GET /agent/{agent_id}/spend (D-14)."""

    model_config = ConfigDict(populate_by_name=True)

    agent_id: str = Field(default="", alias="agentId")
    hours: int = 24
    entries: list[SpendEntry] = Field(default_factory=list)
    total_cost_usd: float = Field(default=0.0, alias="totalCostUsd")


class ExtractLearningsRequest(BaseModel):
    """Request body for POST /memory/extract (D-19)."""

    model_config = ConfigDict(populate_by_name=True)

    since_ts: str | None = Field(default=None, alias="sinceTs")
    batch_size: int = Field(default=20, alias="batchSize")


class ExtractLearningsResponse(BaseModel):
    """Response body for POST /memory/extract."""

    extracted: int = 0
    skipped: int = 0


# ---------------------------------------------------------------------------
# Phase 30 — TeamTool + Auto Memory models
# ---------------------------------------------------------------------------


class SubAgentResult(BaseModel):
    """Result from a single sub-agent invocation in fan-out strategy."""

    model_config = ConfigDict(populate_by_name=True)

    agent_id: str = Field(..., alias="agentId")
    run_id: str = Field(default="", alias="runId")
    status: str = "invoked"
    output: str = ""
    cost_usd: float = Field(default=0.0, alias="costUsd")


class WaveOutput(BaseModel):
    """Output from a single wave in wave strategy execution."""

    model_config = ConfigDict(populate_by_name=True)

    wave: int = 1
    agent_id: str = Field(default="", alias="agentId")
    run_id: str = Field(default="", alias="runId")
    status: str = "invoked"
    output: str = ""


class TeamExecuteRequest(BaseModel):
    """Request body for team strategy execution (fan-out or wave)."""

    model_config = ConfigDict(populate_by_name=True)

    run_id: str = Field(..., alias="runId")
    agent_id: str = Field(..., alias="agentId")
    company_id: str = Field(default="", alias="companyId")
    strategy: str = "standard"
    sub_agent_ids: list[str] = Field(default_factory=list, alias="subAgentIds")
    waves: list[dict[str, Any]] = Field(default_factory=list)
    task: str = ""
    context: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Phase 36 — Paperclip Integration Core models
# ---------------------------------------------------------------------------


class SidecarToolItem(BaseModel):
    """A single tool entry returned by GET /tools."""

    name: str
    display_name: str = ""
    description: str = ""
    enabled: bool = True
    source: str = "builtin"  # "builtin" | "mcp" | "plugin"


class SidecarToolsResponse(BaseModel):
    """Response body for GET /tools."""

    tools: list[SidecarToolItem] = Field(default_factory=list)


class SidecarSkillItem(BaseModel):
    """A single skill entry returned by GET /skills."""

    name: str
    display_name: str = ""
    description: str = ""
    enabled: bool = True
    path: str = ""


class SidecarSkillsResponse(BaseModel):
    """Response body for GET /skills."""

    skills: list[SidecarSkillItem] = Field(default_factory=list)


class SidecarAppItem(BaseModel):
    """A single app entry returned by GET /apps."""

    id: str
    name: str
    status: str = "stopped"
    port: int | None = None
    created_at: str = ""


class SidecarAppsResponse(BaseModel):
    """Response body for GET /apps."""

    apps: list[SidecarAppItem] = Field(default_factory=list)


class SidecarAppActionResponse(BaseModel):
    """Response body for POST /apps/{app_id}/start and POST /apps/{app_id}/stop."""

    ok: bool
    message: str = ""


class SidecarSettingsKeyEntry(BaseModel):
    """A single API key entry in GET /settings response."""

    name: str
    masked_value: str
    is_set: bool
    source: str = "none"  # "admin" | "env" | "none" — per D-07


class SidecarSettingsResponse(BaseModel):
    """Response body for GET /settings."""

    keys: list[SidecarSettingsKeyEntry] = Field(default_factory=list)


class SidecarSettingsUpdateRequest(BaseModel):
    """Request body for POST /settings."""

    key_name: str
    value: str


class SidecarSettingsUpdateResponse(BaseModel):
    """Response body for POST /settings."""

    ok: bool
    key_name: str
