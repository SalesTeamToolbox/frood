/**
 * client.ts -- Agent42Client: HTTP client wrapping all 6 sidecar endpoints.
 *
 * Endpoints:
 *   GET  /sidecar/health                    -- NO auth, 5s timeout, 1 retry on 5xx
 *   POST /memory/recall                     -- Bearer auth, timeoutMs, 1 retry on 5xx
 *   POST /memory/store                      -- Bearer auth, timeoutMs, 1 retry on 5xx
 *   POST /routing/resolve                   -- Bearer auth, timeoutMs, 1 retry on 5xx
 *   POST /effectiveness/recommendations     -- Bearer auth, timeoutMs, 1 retry on 5xx
 *   POST /mcp/tool                          -- Bearer auth, timeoutMs, 1 retry on 5xx
 *
 * Design decisions (per Phase 28 plan):
 *   - Native fetch + AbortController (Node 18+ ships fetch natively)
 *   - No external HTTP libraries to minimise bundle size
 *   - Per-endpoint timeouts (health 5s, all POST endpoints use constructor timeoutMs)
 *   - All POST endpoints retry once on 5xx with 1s backoff
 */
import type { SidecarHealthResponse, MemoryRecallRequest, MemoryRecallResponse, MemoryStoreRequest, MemoryStoreResponse, RoutingResolveRequest, RoutingResolveResponse, EffectivenessRequest, EffectivenessResponse, MCPToolRequest, MCPToolResponse, AgentProfileResponse, AgentEffectivenessResponse, RoutingHistoryResponse, MemoryRunTraceResponse, AgentSpendResponse, ExtractLearningsRequest, ExtractLearningsResponse, ToolsListResponse, SkillsListResponse, AppsListResponse, AppActionResponse, SettingsResponse, SettingsUpdateRequest, SettingsUpdateResponse } from "./types.js";
export declare class Agent42Client {
    private readonly baseUrl;
    private readonly bearerToken;
    private readonly timeoutMs;
    constructor(baseUrl: string, bearerToken: string, timeoutMs?: number);
    /**
     * GET /sidecar/health
     * Public endpoint -- no Authorization header.
     * Retries once on 5xx with 1s delay.
     */
    health(): Promise<SidecarHealthResponse>;
    /**
     * POST /memory/recall
     * Bearer auth required.
     * Retries once on 5xx with 1s delay.
     */
    memoryRecall(body: MemoryRecallRequest): Promise<MemoryRecallResponse>;
    /**
     * POST /memory/store
     * Bearer auth required.
     * Retries once on 5xx with 1s delay.
     */
    memoryStore(body: MemoryStoreRequest): Promise<MemoryStoreResponse>;
    /**
     * POST /routing/resolve
     * Bearer auth required.
     * Retries once on 5xx with 1s delay.
     */
    routeTask(body: RoutingResolveRequest): Promise<RoutingResolveResponse>;
    /**
     * POST /effectiveness/recommendations
     * Bearer auth required.
     * Retries once on 5xx with 1s delay.
     */
    toolEffectiveness(body: EffectivenessRequest): Promise<EffectivenessResponse>;
    /**
     * POST /mcp/tool
     * Bearer auth required.
     * Retries once on 5xx with 1s delay.
     */
    mcpTool(body: MCPToolRequest): Promise<MCPToolResponse>;
    /**
     * GET /agent/{agentId}/profile
     * Bearer auth required. Retries once on 5xx.
     */
    getAgentProfile(agentId: string): Promise<AgentProfileResponse>;
    /**
     * GET /agent/{agentId}/effectiveness
     * Bearer auth required. Retries once on 5xx.
     */
    getAgentEffectiveness(agentId: string): Promise<AgentEffectivenessResponse>;
    /**
     * GET /agent/{agentId}/routing-history?limit=N
     * Bearer auth required. Retries once on 5xx.
     */
    getRoutingHistory(agentId: string, limit?: number): Promise<RoutingHistoryResponse>;
    /**
     * GET /memory/run-trace/{runId}
     * Bearer auth required. Retries once on 5xx.
     */
    getMemoryRunTrace(runId: string): Promise<MemoryRunTraceResponse>;
    /**
     * GET /agent/{agentId}/spend?hours=N
     * Bearer auth required. Retries once on 5xx.
     */
    getAgentSpend(agentId: string, hours?: number): Promise<AgentSpendResponse>;
    /**
     * POST /memory/extract
     * Bearer auth required. Retries once on 5xx.
     */
    extractLearnings(body: ExtractLearningsRequest): Promise<ExtractLearningsResponse>;
    /** GET /tools — list all registered tools */
    getTools(): Promise<ToolsListResponse>;
    /** GET /skills — list all loaded skills */
    getSkills(): Promise<SkillsListResponse>;
    /** GET /apps — list all sandboxed apps */
    getApps(): Promise<AppsListResponse>;
    /** POST /apps/{appId}/start — start a sandboxed app */
    startApp(appId: string): Promise<AppActionResponse>;
    /** POST /apps/{appId}/stop — stop a sandboxed app */
    stopApp(appId: string): Promise<AppActionResponse>;
    /** GET /settings — get masked API keys and config */
    getSettings(): Promise<SettingsResponse>;
    /** POST /settings — update a single API key */
    updateSettings(body: SettingsUpdateRequest): Promise<SettingsUpdateResponse>;
    /**
     * destroy() -- no-op for clean shutdown.
     * Native fetch has no persistent connections to close, but provided for
     * symmetric API with any future implementation using keep-alive.
     */
    destroy(): void;
    /**
     * Returns Content-Type + Authorization headers.
     */
    private authHeaders;
    /**
     * fetchWithTimeout -- wraps fetch with an AbortController timeout.
     * Clears the timeout in a finally block to prevent timer leaks.
     */
    private fetchWithTimeout;
    /**
     * fetchWithRetry -- calls fetchWithTimeout; on 5xx retries once after 1s.
     * Returns the Response (caller checks resp.ok and throws if needed).
     */
    private fetchWithRetry;
}
