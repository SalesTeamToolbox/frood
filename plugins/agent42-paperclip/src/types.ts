/**
 * types.ts -- TypeScript interfaces mirroring Agent42 sidecar Pydantic models.
 *
 * CRITICAL: top_k and score_threshold are snake_case (no camelCase alias on Python side).
 * All other fields use camelCase per sidecar Pydantic aliases.
 */

// -- Health --
export interface SidecarHealthResponse {
  status: string;
  memory: { available: boolean; [key: string]: unknown };
  providers: { available: boolean; [key: string]: unknown };
  qdrant: { available: boolean; [key: string]: unknown };
}

// -- Memory Recall (POST /memory/recall) --
export interface MemoryRecallRequest {
  query: string;
  agentId: string;
  companyId?: string;
  /**
   * NOTE: No camelCase alias on the Python side -- must be sent as top_k, NOT topK.
   */
  top_k?: number;           // snake_case -- NO alias on Python side (Pitfall 3)
  /**
   * NOTE: No alias -- must be sent as score_threshold.
   */
  score_threshold?: number;  // snake_case -- NO alias on Python side (Pitfall 3)
}

export interface MemoryItem {
  text: string;
  score: number;
  source: string;
  metadata: Record<string, unknown>;
}

export interface MemoryRecallResponse {
  memories: MemoryItem[];
}

// -- Memory Store (POST /memory/store) --
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
   * NOTE: No alias -- returned as point_id, not pointId.
   */
  point_id: string;  // snake_case -- NO alias on Python side
}

// -- Routing Resolve (POST /routing/resolve) --
export interface RoutingResolveRequest {
  taskType: string;
  agentId: string;
  qualityTarget?: string;
}

export interface RoutingResolveResponse {
  provider: string;
  model: string;
  tier: string;
  taskCategory: string;
}

// -- Effectiveness (POST /effectiveness/recommendations) --
export interface EffectivenessRequest {
  taskType: string;
  agentId?: string;
}

export interface ToolEffectivenessItem {
  name: string;
  successRate: number;
  observations: number;
}

export interface EffectivenessResponse {
  tools: ToolEffectivenessItem[];
}

// -- MCP Tool Proxy (POST /mcp/tool) --
export interface MCPToolRequest {
  toolName: string;
  params: Record<string, unknown>;
}

export interface MCPToolResponse {
  result: unknown;
  error: string | null;
}

// -- Agent Profile (GET /agent/{agentId}/profile) -- per D-09
export interface AgentProfileResponse {
  agentId: string;
  tier: string;
  successRate: number;
  taskVolume: number;
  avgSpeedMs: number;
  compositeScore: number;
}

// -- Agent Effectiveness (GET /agent/{agentId}/effectiveness) -- per D-10
export interface TaskTypeStats {
  taskType: string;
  successRate: number;
  count: number;
  avgDurationMs: number;
}

export interface AgentEffectivenessResponse {
  agentId: string;
  stats: TaskTypeStats[];
}

// -- Routing History (GET /agent/{agentId}/routing-history) -- per D-11
export interface RoutingHistoryEntry {
  runId: string;
  provider: string;
  model: string;
  tier: string;
  taskCategory: string;
  ts: number;
}

export interface RoutingHistoryResponse {
  agentId: string;
  entries: RoutingHistoryEntry[];
}

// -- Memory Run Trace (GET /memory/run-trace/{runId}) -- per D-13
export interface MemoryTraceItem {
  text: string;
  score: number;
  source: string;
  tags: string[];
}

export interface MemoryRunTraceResponse {
  runId: string;
  injectedMemories: MemoryTraceItem[];
  extractedLearnings: MemoryTraceItem[];
}

// -- Agent Spend (GET /agent/{agentId}/spend) -- per D-14
export interface SpendEntry {
  provider: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
  hourBucket: string;
}

export interface AgentSpendResponse {
  agentId: string;
  hours: number;
  entries: SpendEntry[];
  totalCostUsd: number;
}

// -- Extract Learnings (POST /memory/extract) -- per D-19
export interface ExtractLearningsRequest {
  sinceTs: string | null;
  batchSize: number;
}

export interface ExtractLearningsResponse {
  extracted: number;
  skipped: number;
}
