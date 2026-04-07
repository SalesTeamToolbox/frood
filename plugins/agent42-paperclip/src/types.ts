/**
 * types.ts -- TypeScript interfaces mirroring Agent42 sidecar Pydantic models.
 *
 * CRITICAL: top_k and score_threshold are snake_case (no camelCase alias on Python side).
 * All other fields use camelCase per sidecar Pydantic aliases.
 */

// ---------------------------------------------------------------------------
// Phase 35 -- Provider Model Discovery + Enhanced Health
// ---------------------------------------------------------------------------

/** Single model entry from GET /sidecar/models (D-05) */
export interface ProviderModelItem {
  model_id: string;
  display_name: string;
  provider: string;
  categories: string[];
  available: boolean;
}

/** Response body for GET /sidecar/models (D-05) */
export interface ModelsResponse {
  models: ProviderModelItem[];
  providers: string[];
}

/** Per-provider status detail in enhanced health response (D-07) */
export interface ProviderStatusDetail {
  name: string;
  configured: boolean;
  connected: boolean;
  model_count: number;
  last_check: number;
}

// -- Health --
export interface SidecarHealthResponse {
  status: string;
  memory: { available: boolean; [key: string]: unknown };
  providers: { available: boolean; configured?: Record<string, boolean>; [key: string]: unknown };
  providers_detail?: ProviderStatusDetail[];
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

// ---------------------------------------------------------------------------
// Phase 30 — TeamTool + Auto Memory types
// ---------------------------------------------------------------------------

export interface SubAgentResult {
  agentId: string;
  runId: string;
  status: "invoked" | "completed" | "failed";
  output: string;
  costUsd: number;
}

export interface WaveOutput {
  wave: number;
  agentId: string;
  runId: string;
  status: "invoked" | "completed" | "failed";
  output: string;
}

export interface WaveDefinition {
  agentId: string;
  task: string;
}

export interface TeamExecuteParams {
  strategy: "fan-out" | "wave";
  subAgentIds?: string[];
  waves?: WaveDefinition[];
  task: string;
  context?: Record<string, unknown>;
}

export interface TeamExecuteResult {
  strategy: string;
  subResults?: SubAgentResult[];
  waveOutputs?: WaveOutput[];
}

// ---------------------------------------------------------------------------
// Phase 36 — Paperclip Integration Core types
// ---------------------------------------------------------------------------

// -- Tools (GET /tools) --
export interface ToolItem {
  name: string;
  display_name: string;
  description: string;
  enabled: boolean;
  source: string;  // "builtin" | "mcp" | "plugin"
}

export interface ToolsListResponse {
  tools: ToolItem[];
}

// -- Skills (GET /skills) --
export interface SkillItem {
  name: string;
  display_name: string;
  description: string;
  enabled: boolean;
  path: string;
}

export interface SkillsListResponse {
  skills: SkillItem[];
}

// -- Apps (GET /apps) --
export interface AppItem {
  id: string;
  name: string;
  status: string;  // "running" | "stopped" | "building" | "error"
  port: number | null;
  created_at: string;
}

export interface AppsListResponse {
  apps: AppItem[];
}

export interface AppActionResponse {
  ok: boolean;
  message: string;
}

// -- Settings (GET /settings, POST /settings) --
export interface SettingsKeyEntry {
  name: string;
  masked_value: string;
  is_set: boolean;
  source: "admin" | "env" | "none";  // Phase 40 D-07
}

export interface SettingsResponse {
  keys: SettingsKeyEntry[];
}

export interface SettingsUpdateRequest {
  key_name: string;
  value: string;
}

export interface SettingsUpdateResponse {
  ok: boolean;
  key_name: string;
}

// -- Memory Stats (GET /memory-stats) -- Phase 40 D-13
export interface MemoryStatsResponse {
  recall_count: number;
  learn_count: number;
  error_count: number;
  avg_latency_ms: number;
  period_start: number;
}

// -- Storage Status (GET /storage-status) -- Phase 40 D-12
export interface StorageStatusResponse {
  mode: string;
  qdrant_available: boolean;
  learning_enabled: boolean;
}

// -- Tool/Skill Toggle (PATCH /tools/{name}, /skills/{name}) -- Phase 40 D-18
export interface ToggleResponse {
  name: string;
  enabled: boolean;
}

// -- Memory Purge (DELETE /memory/{collection}) -- Phase 40 D-15
export interface PurgeMemoryResponse {
  ok: boolean;
  collection: string;
}

// -- Terminal session types --
export interface TerminalSessionInfo {
  session_id: string;
  status: string;
}

export interface TerminalOutputEvent {
  text: string;
  ts: number;
}

// ---------------------------------------------------------------------------
// Phase 41 -- Agent42 Adapter types (ABACUS-04)
// ---------------------------------------------------------------------------

/** POST /adapter/run -- route task through Agent42 instead of spawning Claude CLI */
export interface AdapterRunRequest {
  task: string;
  agentId: string;
  role?: string;          // Paperclip role (engineer, researcher, writer, analyst)
  provider?: string;      // Override provider (default: use tiered routing)
  model?: string;         // Override model (default: use tiered routing)
  tools?: string[];       // Agent42 tools to enable
  maxIterations?: number; // Max iterations (default: 10)
}

export interface AdapterRunResponse {
  runId: string;
  status: "started" | "queued" | "failed";
  provider: string;       // Resolved provider (e.g. "abacus")
  model: string;          // Resolved model (e.g. "gemini-3-flash")
  message?: string;
}

/** GET /adapter/status/{runId} */
export interface AdapterStatusResponse {
  runId: string;
  status: "running" | "completed" | "failed" | "cancelled" | "unknown";
  output?: string;
  costUsd?: number;
  durationMs?: number;
}

/** POST /adapter/cancel/{runId} */
export interface AdapterCancelResponse {
  runId: string;
  cancelled: boolean;
  message?: string;
}
