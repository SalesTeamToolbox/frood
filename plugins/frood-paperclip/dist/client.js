/**
 * client.ts -- FroodClient: HTTP client wrapping all 6 sidecar endpoints.
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
export class FroodClient {
    baseUrl;
    bearerToken;
    timeoutMs;
    constructor(baseUrl, bearerToken, timeoutMs = 10_000) {
        this.baseUrl = baseUrl;
        this.bearerToken = bearerToken;
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
    async health() {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/sidecar/health`, {
            method: "GET",
            headers: { "Content-Type": "application/json" },
        }, 5_000);
        if (!resp.ok) {
            throw new Error(`FroodClient.health failed: HTTP ${resp.status}`);
        }
        return resp.json();
    }
    /**
     * POST /memory/recall
     * Bearer auth required.
     * Retries once on 5xx with 1s delay.
     */
    async memoryRecall(body) {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/memory/recall`, {
            method: "POST",
            headers: this.authHeaders(),
            body: JSON.stringify(body),
        }, this.timeoutMs);
        if (!resp.ok) {
            throw new Error(`FroodClient.memoryRecall failed: HTTP ${resp.status}`);
        }
        return resp.json();
    }
    /**
     * POST /memory/store
     * Bearer auth required.
     * Retries once on 5xx with 1s delay.
     */
    async memoryStore(body) {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/memory/store`, {
            method: "POST",
            headers: this.authHeaders(),
            body: JSON.stringify(body),
        }, this.timeoutMs);
        if (!resp.ok) {
            throw new Error(`FroodClient.memoryStore failed: HTTP ${resp.status}`);
        }
        return resp.json();
    }
    /**
     * POST /routing/resolve
     * Bearer auth required.
     * Retries once on 5xx with 1s delay.
     */
    async routeTask(body) {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/routing/resolve`, {
            method: "POST",
            headers: this.authHeaders(),
            body: JSON.stringify(body),
        }, this.timeoutMs);
        if (!resp.ok) {
            throw new Error(`FroodClient.routeTask failed: HTTP ${resp.status}`);
        }
        return resp.json();
    }
    /**
     * POST /effectiveness/recommendations
     * Bearer auth required.
     * Retries once on 5xx with 1s delay.
     */
    async toolEffectiveness(body) {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/effectiveness/recommendations`, {
            method: "POST",
            headers: this.authHeaders(),
            body: JSON.stringify(body),
        }, this.timeoutMs);
        if (!resp.ok) {
            throw new Error(`FroodClient.toolEffectiveness failed: HTTP ${resp.status}`);
        }
        return resp.json();
    }
    /**
     * POST /mcp/tool
     * Bearer auth required.
     * Retries once on 5xx with 1s delay.
     */
    async mcpTool(body) {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/mcp/tool`, {
            method: "POST",
            headers: this.authHeaders(),
            body: JSON.stringify(body),
        }, this.timeoutMs);
        if (!resp.ok) {
            throw new Error(`FroodClient.mcpTool failed: HTTP ${resp.status}`);
        }
        return resp.json();
    }
    /**
     * GET /agent/{agentId}/profile
     * Bearer auth required. Retries once on 5xx.
     */
    async getAgentProfile(agentId) {
        const url = `${this.baseUrl}/agent/${encodeURIComponent(agentId)}/profile`;
        const resp = await this.fetchWithRetry(url, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.getAgentProfile failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /**
     * GET /agent/{agentId}/effectiveness
     * Bearer auth required. Retries once on 5xx.
     */
    async getAgentEffectiveness(agentId) {
        const url = `${this.baseUrl}/agent/${encodeURIComponent(agentId)}/effectiveness`;
        const resp = await this.fetchWithRetry(url, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.getAgentEffectiveness failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /**
     * GET /agent/{agentId}/routing-history?limit=N
     * Bearer auth required. Retries once on 5xx.
     */
    async getRoutingHistory(agentId, limit = 20) {
        const url = `${this.baseUrl}/agent/${encodeURIComponent(agentId)}/routing-history?limit=${limit}`;
        const resp = await this.fetchWithRetry(url, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.getRoutingHistory failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /**
     * GET /memory/run-trace/{runId}
     * Bearer auth required. Retries once on 5xx.
     */
    async getMemoryRunTrace(runId) {
        const url = `${this.baseUrl}/memory/run-trace/${encodeURIComponent(runId)}`;
        const resp = await this.fetchWithRetry(url, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.getMemoryRunTrace failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /**
     * GET /agent/{agentId}/spend?hours=N
     * Bearer auth required. Retries once on 5xx.
     */
    async getAgentSpend(agentId, hours = 24) {
        const url = `${this.baseUrl}/agent/${encodeURIComponent(agentId)}/spend?hours=${hours}`;
        const resp = await this.fetchWithRetry(url, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.getAgentSpend failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /**
     * POST /memory/extract
     * Bearer auth required. Retries once on 5xx.
     */
    async extractLearnings(body) {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/memory/extract`, { method: "POST", headers: this.authHeaders(), body: JSON.stringify(body) }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.extractLearnings failed: HTTP ${resp.status}`);
        return resp.json();
    }
    // -------------------------------------------------------------------------
    // Phase 35 -- Provider Model Discovery methods
    // -------------------------------------------------------------------------
    /**
     * GET /sidecar/models
     * Public endpoint -- no Authorization header (per D-05).
     * Returns available models grouped by provider.
     * Retries once on 5xx with 1s delay.
     */
    async getModels() {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/sidecar/models`, {
            method: "GET",
            headers: { "Content-Type": "application/json" },
        }, 5_000);
        if (!resp.ok) {
            throw new Error(`FroodClient.getModels failed: HTTP ${resp.status}`);
        }
        return resp.json();
    }
    // -------------------------------------------------------------------------
    // Phase 36 — Paperclip Integration Core methods
    // -------------------------------------------------------------------------
    /** GET /tools — list all registered tools */
    async getTools() {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/tools`, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.getTools failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /** GET /skills — list all loaded skills */
    async getSkills() {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/skills`, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.getSkills failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /** PATCH /tools/{name} — toggle tool enabled/disabled (Phase 40 D-18) */
    async toggleTool(name, enabled) {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/tools/${encodeURIComponent(name)}`, { method: "PATCH", headers: this.authHeaders(), body: JSON.stringify({ enabled }) }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.toggleTool failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /** PATCH /skills/{name} — toggle skill enabled/disabled (Phase 40 D-18) */
    async toggleSkill(name, enabled) {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/skills/${encodeURIComponent(name)}`, { method: "PATCH", headers: this.authHeaders(), body: JSON.stringify({ enabled }) }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.toggleSkill failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /** GET /memory-stats — 24h memory operation counters (Phase 40 D-13) */
    async getMemoryStats() {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/memory-stats`, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.getMemoryStats failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /** GET /storage-status — storage backend configuration (Phase 40 D-12) */
    async getStorageStatus() {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/storage-status`, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.getStorageStatus failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /** DELETE /memory/{collection} — purge a memory collection (Phase 40 D-15) */
    async purgeMemory(collection) {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/memory/${encodeURIComponent(collection)}`, { method: "DELETE", headers: this.authHeaders() }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.purgeMemory failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /** GET /apps — list all sandboxed apps */
    async getApps() {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/apps`, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.getApps failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /** POST /apps/{appId}/start — start a sandboxed app */
    async startApp(appId) {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/apps/${encodeURIComponent(appId)}/start`, { method: "POST", headers: this.authHeaders() }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.startApp failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /** POST /apps/{appId}/stop — stop a sandboxed app */
    async stopApp(appId) {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/apps/${encodeURIComponent(appId)}/stop`, { method: "POST", headers: this.authHeaders() }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.stopApp failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /** GET /settings — get masked API keys and config */
    async getSettings() {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/settings`, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.getSettings failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /** POST /settings — update a single API key */
    async updateSettings(body) {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/settings`, { method: "POST", headers: this.authHeaders(), body: JSON.stringify(body) }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.updateSettings failed: HTTP ${resp.status}`);
        return resp.json();
    }
    // -------------------------------------------------------------------------
    // Phase 41 -- Frood Adapter methods (ABACUS-04)
    // Replaces claude_local: routes Paperclip agent tasks through Frood HTTP API
    // which uses tiered routing (Abacus RouteLLM) instead of spawning Claude CLI.
    // -------------------------------------------------------------------------
    /**
     * POST /adapter/run
     * Start an agent task routed through Frood (Abacus RouteLLM, NOT Claude CLI).
     * Bearer auth required. Retries once on 5xx.
     */
    async adapterRun(body) {
        const resp = await this.fetchWithRetry(`${this.baseUrl}/adapter/run`, { method: "POST", headers: this.authHeaders(), body: JSON.stringify(body) }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.adapterRun failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /**
     * GET /adapter/status/{runId}
     * Check status of an adapter-launched agent run.
     * Bearer auth required. Retries once on 5xx.
     */
    async adapterStatus(runId) {
        const url = `${this.baseUrl}/adapter/status/${encodeURIComponent(runId)}`;
        const resp = await this.fetchWithRetry(url, { method: "GET", headers: this.authHeaders() }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.adapterStatus failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /**
     * POST /adapter/cancel/{runId}
     * Cancel a running adapter-launched agent.
     * Bearer auth required. Retries once on 5xx.
     */
    async adapterCancel(runId) {
        const url = `${this.baseUrl}/adapter/cancel/${encodeURIComponent(runId)}`;
        const resp = await this.fetchWithRetry(url, { method: "POST", headers: this.authHeaders() }, this.timeoutMs);
        if (!resp.ok)
            throw new Error(`FroodClient.adapterCancel failed: HTTP ${resp.status}`);
        return resp.json();
    }
    /**
     * destroy() -- no-op for clean shutdown.
     * Native fetch has no persistent connections to close, but provided for
     * symmetric API with any future implementation using keep-alive.
     */
    destroy() {
        // no-op: native fetch does not maintain persistent connections
    }
    // -------------------------------------------------------------------------
    // Private helpers
    // -------------------------------------------------------------------------
    /**
     * Returns Content-Type + Authorization headers.
     */
    authHeaders() {
        const headers = {
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
    async fetchWithTimeout(url, init, timeoutMs) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
        try {
            return await fetch(url, { ...init, signal: controller.signal });
        }
        finally {
            clearTimeout(timeoutId);
        }
    }
    /**
     * fetchWithRetry -- calls fetchWithTimeout; on 5xx retries once after 1s.
     * Returns the Response (caller checks resp.ok and throws if needed).
     */
    async fetchWithRetry(url, init, timeoutMs) {
        const firstResp = await this.fetchWithTimeout(url, init, timeoutMs);
        if (firstResp.status >= 500) {
            // Wait 1s then retry once
            await new Promise((r) => setTimeout(r, 1000));
            return this.fetchWithTimeout(url, init, timeoutMs);
        }
        return firstResp;
    }
}
