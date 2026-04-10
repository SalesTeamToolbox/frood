/**
 * types.ts -- TypeScript interfaces mirroring Frood sidecar Pydantic models.
 *
 * CRITICAL: top_k and score_threshold are snake_case (no camelCase alias on Python side).
 * All other fields use camelCase per sidecar Pydantic aliases.
 */
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
export interface SidecarHealthResponse {
    status: string;
    memory: {
        available: boolean;
        [key: string]: unknown;
    };
    providers: {
        available: boolean;
        configured?: Record<string, boolean>;
        [key: string]: unknown;
    };
    providers_detail?: ProviderStatusDetail[];
    qdrant: {
        available: boolean;
        [key: string]: unknown;
    };
}
export interface MemoryRecallRequest {
    query: string;
    agentId: string;
    companyId?: string;
    /**
     * NOTE: No camelCase alias on the Python side -- must be sent as top_k, NOT topK.
     */
    top_k?: number;
    /**
     * NOTE: No alias -- must be sent as score_threshold.
     */
    score_threshold?: number;
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
    point_id: string;
}
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
export interface MCPToolRequest {
    toolName: string;
    params: Record<string, unknown>;
}
export interface MCPToolResponse {
    result: unknown;
    error: string | null;
}
export interface AgentProfileResponse {
    agentId: string;
    tier: string;
    successRate: number;
    taskVolume: number;
    avgSpeedMs: number;
    compositeScore: number;
}
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
export interface ExtractLearningsRequest {
    sinceTs: string | null;
    batchSize: number;
}
export interface ExtractLearningsResponse {
    extracted: number;
    skipped: number;
}
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
export interface ToolItem {
    name: string;
    display_name: string;
    description: string;
    enabled: boolean;
    source: string;
}
export interface ToolsListResponse {
    tools: ToolItem[];
}
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
export interface AppItem {
    id: string;
    name: string;
    status: string;
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
export interface SettingsKeyEntry {
    name: string;
    masked_value: string;
    is_set: boolean;
    source: "admin" | "env" | "none";
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
export interface MemoryStatsResponse {
    recall_count: number;
    learn_count: number;
    error_count: number;
    avg_latency_ms: number;
    period_start: number;
}
export interface StorageStatusResponse {
    mode: string;
    qdrant_available: boolean;
    learning_enabled: boolean;
}
export interface ToggleResponse {
    name: string;
    enabled: boolean;
}
export interface PurgeMemoryResponse {
    ok: boolean;
    collection: string;
}
export interface TerminalSessionInfo {
    session_id: string;
    status: string;
}
export interface TerminalOutputEvent {
    text: string;
    ts: number;
}
/** POST /adapter/run -- route task through Frood instead of spawning Claude CLI */
export interface AdapterRunRequest {
    task: string;
    agentId: string;
    role?: string;
    provider?: string;
    model?: string;
    tools?: string[];
    maxIterations?: number;
}
export interface AdapterRunResponse {
    runId: string;
    status: "started" | "queued" | "failed";
    provider: string;
    model: string;
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
