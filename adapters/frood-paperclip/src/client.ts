/**
 * client.ts — Agent42Client: HTTP client wrapping all 4 sidecar endpoints.
 *
 * Endpoints:
 *   POST /sidecar/execute  — Bearer auth, 30s timeout, NO retry
 *   GET  /sidecar/health   — NO auth, 5s timeout, 1 retry on 5xx
 *   POST /memory/recall    — Bearer auth, 10s timeout, 1 retry on 5xx
 *   POST /memory/store     — Bearer auth, 10s timeout, 1 retry on 5xx
 *
 * Design decisions (per Phase 27 plan):
 *   - D-15: Use native fetch + AbortController (Node 18+ ships fetch)
 *   - D-16: No external HTTP libraries to minimise bundle size
 *   - D-17: Per-endpoint timeouts (execute 30s, health 5s, memory 10s)
 *   - D-18: execute() NEVER retries (idempotency guard server-side);
 *           health/memory retry once on 5xx with 1s backoff
 */

import type {
  SidecarExecuteRequest,
  SidecarExecuteResponse,
  SidecarHealthResponse,
  MemoryRecallRequest,
  MemoryRecallResponse,
  MemoryStoreRequest,
  MemoryStoreResponse,
} from "./types.js";

export class Agent42Client {
  constructor(
    private readonly baseUrl: string,
    private bearerToken: string,  // Mutable for token refresh (D-12)
  ) {}

  /** Update bearer token after auto-provisioning or refresh. */
  setBearerToken(token: string): void {
    this.bearerToken = token;
  }

  // -------------------------------------------------------------------------
  // Public API
  // -------------------------------------------------------------------------

  /**
   * POST /sidecar/execute
   * 202 Accepted is treated as success (resp.ok covers 200-299).
   * No retry — callers should not resubmit; server handles idempotency via runId.
   */
  async execute(body: SidecarExecuteRequest): Promise<SidecarExecuteResponse> {
    const resp = await this.fetchWithTimeout(
      `${this.baseUrl}/sidecar/execute`,
      {
        method: "POST",
        headers: this.authHeaders(),
        body: JSON.stringify(body),
      },
      30_000,
    );

    if (!resp.ok) {
      throw new Error(`Agent42Client.execute failed: HTTP ${resp.status}`);
    }

    return resp.json() as Promise<SidecarExecuteResponse>;
  }

  /**
   * GET /sidecar/health
   * Public endpoint — no Authorization header.
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
      10_000,
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
      10_000,
    );

    if (!resp.ok) {
      throw new Error(`Agent42Client.memoryStore failed: HTTP ${resp.status}`);
    }

    return resp.json() as Promise<MemoryStoreResponse>;
  }

  // -------------------------------------------------------------------------
  // Private helpers
  // -------------------------------------------------------------------------

  /**
   * Returns Content-Type + Authorization headers.
   * Omits Authorization if bearerToken is empty (e.g., health check path builds
   * its own headers without this helper).
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
   * fetchWithTimeout — wraps fetch with an AbortController timeout.
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
   * fetchWithRetry — calls fetchWithTimeout; on 5xx retries once after 1s.
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
