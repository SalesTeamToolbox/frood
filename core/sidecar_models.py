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
