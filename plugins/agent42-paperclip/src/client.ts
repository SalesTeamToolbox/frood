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

import type {
  SidecarHealthResponse,
  MemoryRecallRequest,
  MemoryRecallResponse,
  MemoryStoreRequest,
  MemoryStoreResponse,
  RoutingResolveRequest,
  RoutingResolveResponse,
  EffectivenessRequest,
  EffectivenessResponse,
  MCPToolRequest,
  MCPToolResponse,
  AgentProfileResponse,
  AgentEffectivenessResponse,
  RoutingHistoryResponse,
  MemoryRunTraceResponse,
  AgentSpendResponse,
  ExtractLearningsRequest,
  ExtractLearningsResponse,
  ToolsListResponse,
  SkillsListResponse,
  AppsListResponse,
  AppActionResponse,
  SettingsResponse,
  SettingsUpdateRequest,
  SettingsUpdateResponse,
  AdapterRunRequest,
  AdapterRunResponse,
  AdapterStatusResponse,
  AdapterCancelResponse,
  MemoryStatsResponse,
  StorageStatusResponse,
  ToggleResponse,
  PurgeMemoryResponse,
} from "./types.js";

export class Agent42Client {
  private readonly timeoutMs: number;

  constructor(
    private readonly baseUrl: string,
    private readonly bearerToken: string,
    timeoutMs = 10_000,
  ) {
    this.timeoutMs = timeoutMs;
  }

  // -------------------------------------------------------------------------
  // Public API
  // -------------------------------------------------------------------------

  /**
   * GET /sidecar/health
   * Public endpoint -- no Authorization header.
   * Retries once on 5xx with 1s delay.
   */
  async health(): Promise<SidecarHealthResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/sidecar/health`,
      {
        method: "GET",
        headers: { "Content-Type": "application/json" },
      },
      5_000,
    );

    if (!resp.ok) {
      throw new Error(`Agent42Client.health failed: HTTP ${resp.status}`);
    }

    return resp.json() as Promise<SidecarHealthResponse>;
  }

  /**
   * POST /memory/recall
   * Bearer auth required.
   * Retries once on 5xx with 1s delay.
   */
  async memoryRecall(body: MemoryRecallRequest): Promise<MemoryRecallResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/memory/recall`,
      {
        method: "POST",
        headers: this.authHeaders(),
        body: JSON.stringify(body),
      },
      this.timeoutMs,
    );

    if (!resp.ok) {
      throw new Error(`Agent42Client.memoryRecall failed: HTTP ${resp.status}`);
    }

    return resp.json() as Promise<MemoryRecallResponse>;
  }

  /**
   * POST /memory/store
   * Bearer auth required.
   * Retries once on 5xx with 1s delay.
   */
  async memoryStore(body: MemoryStoreRequest): Promise<MemoryStoreResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/memory/store`,
      {
        method: "POST",
        headers: this.authHeaders(),
        body: JSON.stringify(body),
      },
      this.timeoutMs,
    );

    if (!resp.ok) {
      throw new Error(`Agent42Client.memoryStore failed: HTTP ${resp.status}`);
    }

    return resp.json() as Promise<MemoryStoreResponse>;
  }

  /**
   * POST /routing/resolve
   * Bearer auth required.
   * Retries once on 5xx with 1s delay.
   */
  async routeTask(body: RoutingResolveRequest): Promise<RoutingResolveResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/routing/resolve`,
      {
        method: "POST",
        headers: this.authHeaders(),
        body: JSON.stringify(body),
      },
      this.timeoutMs,
    );

    if (!resp.ok) {
      throw new Error(`Agent42Client.routeTask failed: HTTP ${resp.status}`);
    }

    return resp.json() as Promise<RoutingResolveResponse>;
  }

  /**
   * POST /effectiveness/recommendations
   * Bearer auth required.
   * Retries once on 5xx with 1s delay.
   */
  async toolEffectiveness(body: EffectivenessRequest): Promise<EffectivenessResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/effectiveness/recommendations`,
      {
        method: "POST",
        headers: this.authHeaders(),
        body: JSON.stringify(body),
      },
      this.timeoutMs,
    );

    if (!resp.ok) {
      throw new Error(`Agent42Client.toolEffectiveness failed: HTTP ${resp.status}`);
    }

    return resp.json() as Promise<EffectivenessResponse>;
  }

  /**
   * POST /mcp/tool
   * Bearer auth required.
   * Retries once on 5xx with 1s delay.
   */
  async mcpTool(body: MCPToolRequest): Promise<MCPToolResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/mcp/tool`,
      {
        method: "POST",
        headers: this.authHeaders(),
        body: JSON.stringify(body),
      },
      this.timeoutMs,
    );

    if (!resp.ok) {
      throw new Error(`Agent42Client.mcpTool failed: HTTP ${resp.status}`);
    }

    return resp.json() as Promise<MCPToolResponse>;
  }

  /**
   * GET /agent/{agentId}/profile
   * Bearer auth required. Retries once on 5xx.
   */
  async getAgentProfile(agentId: string): Promise<AgentProfileResponse> {
    const url = `${this.baseUrl}/agent/${encodeURIComponent(agentId)}/profile`;
    const resp = await this.fetchWithRetry(url, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
    if (!resp.ok) throw new Error(`Agent42Client.getAgentProfile failed: HTTP ${resp.status}`);
    return resp.json() as Promise<AgentProfileResponse>;
  }

  /**
   * GET /agent/{agentId}/effectiveness
   * Bearer auth required. Retries once on 5xx.
   */
  async getAgentEffectiveness(agentId: string): Promise<AgentEffectivenessResponse> {
    const url = `${this.baseUrl}/agent/${encodeURIComponent(agentId)}/effectiveness`;
    const resp = await this.fetchWithRetry(url, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
    if (!resp.ok) throw new Error(`Agent42Client.getAgentEffectiveness failed: HTTP ${resp.status}`);
    return resp.json() as Promise<AgentEffectivenessResponse>;
  }

  /**
   * GET /agent/{agentId}/routing-history?limit=N
   * Bearer auth required. Retries once on 5xx.
   */
  async getRoutingHistory(agentId: string, limit = 20): Promise<RoutingHistoryResponse> {
    const url = `${this.baseUrl}/agent/${encodeURIComponent(agentId)}/routing-history?limit=${limit}`;
    const resp = await this.fetchWithRetry(url, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
    if (!resp.ok) throw new Error(`Agent42Client.getRoutingHistory failed: HTTP ${resp.status}`);
    return resp.json() as Promise<RoutingHistoryResponse>;
  }

  /**
   * GET /memory/run-trace/{runId}
   * Bearer auth required. Retries once on 5xx.
   */
  async getMemoryRunTrace(runId: string): Promise<MemoryRunTraceResponse> {
    const url = `${this.baseUrl}/memory/run-trace/${encodeURIComponent(runId)}`;
    const resp = await this.fetchWithRetry(url, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
    if (!resp.ok) throw new Error(`Agent42Client.getMemoryRunTrace failed: HTTP ${resp.status}`);
    return resp.json() as Promise<MemoryRunTraceResponse>;
  }

  /**
   * GET /agent/{agentId}/spend?hours=N
   * Bearer auth required. Retries once on 5xx.
   */
  async getAgentSpend(agentId: string, hours = 24): Promise<AgentSpendResponse> {
    const url = `${this.baseUrl}/agent/${encodeURIComponent(agentId)}/spend?hours=${hours}`;
    const resp = await this.fetchWithRetry(url, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
    if (!resp.ok) throw new Error(`Agent42Client.getAgentSpend failed: HTTP ${resp.status}`);
    return resp.json() as Promise<AgentSpendResponse>;
  }

  /**
   * POST /memory/extract
   * Bearer auth required. Retries once on 5xx.
   */
  async extractLearnings(body: ExtractLearningsRequest): Promise<ExtractLearningsResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/memory/extract`,
      { method: "POST", headers: this.authHeaders(), body: JSON.stringify(body) },
      this.timeoutMs,
    );
    if (!resp.ok) throw new Error(`Agent42Client.extractLearnings failed: HTTP ${resp.status}`);
    return resp.json() as Promise<ExtractLearningsResponse>;
  }

  // -------------------------------------------------------------------------
  // Phase 36 — Paperclip Integration Core methods
  // -------------------------------------------------------------------------

  /** GET /tools — list all registered tools */
  async getTools(): Promise<ToolsListResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/tools`,
      { method: "GET", headers: this.authHeaders() },
      this.timeoutMs,
    );
    if (!resp.ok) throw new Error(`Agent42Client.getTools failed: HTTP ${resp.status}`);
    return resp.json() as Promise<ToolsListResponse>;
  }

  /** GET /skills — list all loaded skills */
  async getSkills(): Promise<SkillsListResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/skills`,
      { method: "GET", headers: this.authHeaders() },
      this.timeoutMs,
    );
    if (!resp.ok) throw new Error(`Agent42Client.getSkills failed: HTTP ${resp.status}`);
    return resp.json() as Promise<SkillsListResponse>;
  }

  /** PATCH /tools/{name} — toggle tool enabled/disabled (Phase 40 D-18) */
  async toggleTool(name: string, enabled: boolean): Promise<ToggleResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/tools/${encodeURIComponent(name)}`,
      { method: "PATCH", headers: this.authHeaders(), body: JSON.stringify({ enabled }) },
      this.timeoutMs,
    );
    if (!resp.ok) throw new Error(`Agent42Client.toggleTool failed: HTTP ${resp.status}`);
    return resp.json() as Promise<ToggleResponse>;
  }

  /** PATCH /skills/{name} — toggle skill enabled/disabled (Phase 40 D-18) */
  async toggleSkill(name: string, enabled: boolean): Promise<ToggleResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/skills/${encodeURIComponent(name)}`,
      { method: "PATCH", headers: this.authHeaders(), body: JSON.stringify({ enabled }) },
      this.timeoutMs,
    );
    if (!resp.ok) throw new Error(`Agent42Client.toggleSkill failed: HTTP ${resp.status}`);
    return resp.json() as Promise<ToggleResponse>;
  }

  /** GET /memory-stats — 24h memory operation counters (Phase 40 D-13) */
  async getMemoryStats(): Promise<MemoryStatsResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/memory-stats`,
      { method: "GET", headers: this.authHeaders() },
      this.timeoutMs,
    );
    if (!resp.ok) throw new Error(`Agent42Client.getMemoryStats failed: HTTP ${resp.status}`);
    return resp.json() as Promise<MemoryStatsResponse>;
  }

  /** GET /storage-status — storage backend configuration (Phase 40 D-12) */
  async getStorageStatus(): Promise<StorageStatusResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/storage-status`,
      { method: "GET", headers: this.authHeaders() },
      this.timeoutMs,
    );
    if (!resp.ok) throw new Error(`Agent42Client.getStorageStatus failed: HTTP ${resp.status}`);
    return resp.json() as Promise<StorageStatusResponse>;
  }

  /** DELETE /memory/{collection} — purge a memory collection (Phase 40 D-15) */
  async purgeMemory(collection: string): Promise<PurgeMemoryResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/memory/${encodeURIComponent(collection)}`,
      { method: "DELETE", headers: this.authHeaders() },
      this.timeoutMs,
    );
    if (!resp.ok) throw new Error(`Agent42Client.purgeMemory failed: HTTP ${resp.status}`);
    return resp.json() as Promise<PurgeMemoryResponse>;
  }

  /** GET /apps — list all sandboxed apps */
  async getApps(): Promise<AppsListResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/apps`,
      { method: "GET", headers: this.authHeaders() },
      this.timeoutMs,
    );
    if (!resp.ok) throw new Error(`Agent42Client.getApps failed: HTTP ${resp.status}`);
    return resp.json() as Promise<AppsListResponse>;
  }

  /** POST /apps/{appId}/start — start a sandboxed app */
  async startApp(appId: string): Promise<AppActionResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/apps/${encodeURIComponent(appId)}/start`,
      { method: "POST", headers: this.authHeaders() },
      this.timeoutMs,
    );
    if (!resp.ok) throw new Error(`Agent42Client.startApp failed: HTTP ${resp.status}`);
    return resp.json() as Promise<AppActionResponse>;
  }

  /** POST /apps/{appId}/stop — stop a sandboxed app */
  async stopApp(appId: string): Promise<AppActionResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/apps/${encodeURIComponent(appId)}/stop`,
      { method: "POST", headers: this.authHeaders() },
      this.timeoutMs,
    );
    if (!resp.ok) throw new Error(`Agent42Client.stopApp failed: HTTP ${resp.status}`);
    return resp.json() as Promise<AppActionResponse>;
  }

  /** GET /settings — get masked API keys and config */
  async getSettings(): Promise<SettingsResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/settings`,
      { method: "GET", headers: this.authHeaders() },
      this.timeoutMs,
    );
    if (!resp.ok) throw new Error(`Agent42Client.getSettings failed: HTTP ${resp.status}`);
    return resp.json() as Promise<SettingsResponse>;
  }

  /** POST /settings — update a single API key */
  async updateSettings(body: SettingsUpdateRequest): Promise<SettingsUpdateResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/settings`,
      { method: "POST", headers: this.authHeaders(), body: JSON.stringify(body) },
      this.timeoutMs,
    );
    if (!resp.ok) throw new Error(`Agent42Client.updateSettings failed: HTTP ${resp.status}`);
    return resp.json() as Promise<SettingsUpdateResponse>;
  }

  // -------------------------------------------------------------------------
  // Phase 41 -- Agent42 Adapter methods (ABACUS-04)
  // Replaces claude_local: routes Paperclip agent tasks through Agent42 HTTP API
  // which uses tiered routing (Abacus RouteLLM) instead of spawning Claude CLI.
  // -------------------------------------------------------------------------

  /**
   * POST /adapter/run
   * Start an agent task routed through Agent42 (Abacus RouteLLM, NOT Claude CLI).
   * Bearer auth required. Retries once on 5xx.
   */
  async adapterRun(body: AdapterRunRequest): Promise<AdapterRunResponse> {
    const resp = await this.fetchWithRetry(
      `${this.baseUrl}/adapter/run`,
      { method: "POST", headers: this.authHeaders(), body: JSON.stringify(body) },
      this.timeoutMs,
    );
    if (!resp.ok) throw new Error(`Agent42Client.adapterRun failed: HTTP ${resp.status}`);
    return resp.json() as Promise<AdapterRunResponse>;
  }

  /**
   * GET /adapter/status/{runId}
   * Check status of an adapter-launched agent run.
   * Bearer auth required. Retries once on 5xx.
   */
  async adapterStatus(runId: string): Promise<AdapterStatusResponse> {
    const url = `${this.baseUrl}/adapter/status/${encodeURIComponent(runId)}`;
    const resp = await this.fetchWithRetry(url, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
    if (!resp.ok) throw new Error(`Agent42Client.adapterStatus failed: HTTP ${resp.status}`);
    return resp.json() as Promise<AdapterStatusResponse>;
  }

  /**
   * POST /adapter/cancel/{runId}
   * Cancel a running adapter-launched agent.
   * Bearer auth required. Retries once on 5xx.
   */
  async adapterCancel(runId: string): Promise<AdapterCancelResponse> {
    const url = `${this.baseUrl}/adapter/cancel/${encodeURIComponent(runId)}`;
    const resp = await this.fetchWithRetry(url, { method: "POST", headers: this.authHeaders() }, this.timeoutMs);
    if (!resp.ok) throw new Error(`Agent42Client.adapterCancel failed: HTTP ${resp.status}`);
    return resp.json() as Promise<AdapterCancelResponse>;
  }

  /**
   * destroy() -- no-op for clean shutdown.
   * Native fetch has no persistent connections to close, but provided for
   * symmetric API with any future implementation using keep-alive.
   */
  destroy(): void {
    // no-op: native fetch does not maintain persistent connections
  }

  // -------------------------------------------------------------------------
  // Private helpers
  // -------------------------------------------------------------------------

  /**
   * Returns Content-Type + Authorization headers.
   */
  private authHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (this.bearerToken) {
      headers["Authorization"] = `Bearer ${this.bearerToken}`;
    }
    return headers;
  }

  /**
   * fetchWithTimeout -- wraps fetch with an AbortController timeout.
   * Clears the timeout in a finally block to prevent timer leaks.
   */
  private async fetchWithTimeout(
    url: string,
    init: RequestInit,
    timeoutMs: number,
  ): Promise<Response> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    try {
      return await fetch(url, { ...init, signal: controller.signal });
    } finally {
      clearTimeout(timeoutId);
    }
  }

  /**
   * fetchWithRetry -- calls fetchWithTimeout; on 5xx retries once after 1s.
   * Returns the Response (caller checks resp.ok and throws if needed).
   */
  private async fetchWithRetry(
    url: string,
    init: RequestInit,
    timeoutMs: number,
  ): Promise<Response> {
    const firstResp = await this.fetchWithTimeout(url, init, timeoutMs);

    if (firstResp.status >= 500) {
      // Wait 1s then retry once
      await new Promise<void>((r) => setTimeout(r, 1000));
      return this.fetchWithTimeout(url, init, timeoutMs);
    }

    return firstResp;
  }
}
