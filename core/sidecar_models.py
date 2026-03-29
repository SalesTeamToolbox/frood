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
