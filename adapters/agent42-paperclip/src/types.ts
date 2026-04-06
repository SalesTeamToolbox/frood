/**
 * types.ts — Contract definitions for Agent42 sidecar communication.
 *
 * All interfaces mirror the Python Pydantic models in core/sidecar_models.py.
 * Field naming follows the camelCase aliases in the Python models (per the sidecar endpoint contracts).
 *
 * NOTE on mixed-case fields:
 *   - MemoryRecallRequest.top_k and score_threshold have NO camelCase alias on the Python side.
 *     They MUST be sent as top_k / score_threshold, never topK / scoreThreshold.
 *   - MemoryStoreResponse.point_id has no alias either.
 */

// ---------------------------------------------------------------------------
// Adapter config
// ---------------------------------------------------------------------------

/**
 * SidecarConfig — what the adapter extracts from ctx.agent.adapterConfig.
 * Parsed defensively via parseSidecarConfig() since adapterConfig is typed as `unknown`.
 */
export interface SidecarConfig {
  sidecarUrl: string;
  bearerToken: string;
  agentId: string;         // Agent42 agent UUID for memory/effectiveness
  preferredProvider: string;
  memoryScope: string;     // "agent" | "company"
}

/**
 * parseSidecarConfig — defensive parser for ctx.agent.adapterConfig.
 *
 * If raw is null/undefined/non-object, returns defaults with sidecarUrl: "".
 * Never throws.
 */
export function parseSidecarConfig(raw: unknown): SidecarConfig {
  const defaults: SidecarConfig = {
    sidecarUrl: "",
    bearerToken: "",
    agentId: "",
    preferredProvider: "",
    memoryScope: "agent",
  };

  if (raw === null || raw === undefined || typeof raw !== "object") {
    return defaults;
  }

  const r = raw as Record<string, unknown>;

  return {
    sidecarUrl: typeof r["sidecarUrl"] === "string" ? r["sidecarUrl"] : defaults.sidecarUrl,
    bearerToken: typeof r["bearerToken"] === "string" ? r["bearerToken"] : defaults.bearerToken,
    agentId: typeof r["agentId"] === "string" ? r["agentId"] : defaults.agentId,
    preferredProvider: typeof r["preferredProvider"] === "string" ? r["preferredProvider"] : defaults.preferredProvider,
    memoryScope: typeof r["memoryScope"] === "string" ? r["memoryScope"] : defaults.memoryScope,
  };
}

// ---------------------------------------------------------------------------
// POST /sidecar/execute — 202 Accepted, Bearer auth required
// ---------------------------------------------------------------------------

export interface SidecarExecuteRequest {
  runId: string;
  agentId: string;
  companyId?: string;
  taskId?: string;
  wakeReason?: string;
  context?: Record<string, unknown>;
  adapterConfig?: {
    sessionKey?: string;
    memoryScope?: string;
    preferredProvider?: string;
    agentId?: string;
  };
}

export interface SidecarExecuteResponse {
  status: string;
  externalRunId: string;
  deduplicated: boolean;
}

// ---------------------------------------------------------------------------
// GET /sidecar/health — NO auth
// ---------------------------------------------------------------------------

export interface SidecarHealthResponse {
  status: string;
  memory: { available: boolean; [key: string]: unknown };
  providers: { available: boolean; [key: string]: unknown };
  qdrant: { available: boolean; [key: string]: unknown };
}

// ---------------------------------------------------------------------------
// POST /memory/recall — Bearer auth required
// ---------------------------------------------------------------------------

export interface MemoryRecallRequest {
  query: string;
  agentId: string;
  companyId?: string;
  /**
   * NOTE: No camelCase alias on the Python side — must be sent as top_k, NOT topK.
   */
  top_k?: number;
  /**
   * NOTE: No alias — must be sent as score_threshold.
   */
  score_threshold?: number;
}

export interface MemoryRecallResponse {
  memories: Array<{
    text: string;
    score: number;
    source: string;
    metadata: Record<string, unknown>;
  }>;
}

// ---------------------------------------------------------------------------
// POST /memory/store — Bearer auth required
// ---------------------------------------------------------------------------

export interface MemoryStoreRequest {
  text: string;
  section?: string;
  tags?: string[];
  agentId: string;
  companyId?: string;
}

export interface MemoryStoreResponse {
  stored: boolean;
  /**
   * NOTE: No alias — returned as point_id, not pointId.
   */
  point_id: string;
}
