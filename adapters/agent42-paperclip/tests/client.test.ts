import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { Agent42Client } from "../src/client.js";
import type {
  SidecarExecuteRequest,
  MemoryRecallRequest,
  MemoryStoreRequest,
} from "../src/types.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeMockResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Agent42Client", () => {
  let client: Agent42Client;

  beforeEach(() => {
    client = new Agent42Client("http://localhost:8001", "test-token");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllTimers();
  });

  // -------------------------------------------------------------------------
  // execute()
  // -------------------------------------------------------------------------
  describe("execute()", () => {
    const validRequest: SidecarExecuteRequest = {
      runId: "run-123",
      agentId: "agent-456",
    };

    it("sends POST to /sidecar/execute with correct body and Authorization header", async () => {
      const mockFetch = vi.fn().mockResolvedValue(
        makeMockResponse(202, {
          status: "accepted",
          externalRunId: "ext-789",
          deduplicated: false,
        })
      );
      vi.stubGlobal("fetch", mockFetch);

      const result = await client.execute(validRequest);

      expect(mockFetch).toHaveBeenCalledOnce();
      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("http://localhost:8001/sidecar/execute");
      expect(init.method).toBe("POST");
      expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer test-token");
      expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
      expect(JSON.parse(init.body as string)).toEqual(validRequest);
      expect(result).toEqual({
        status: "accepted",
        externalRunId: "ext-789",
        deduplicated: false,
      });
    });

    it("treats 202 Accepted as success (not an error)", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          makeMockResponse(202, {
            status: "accepted",
            externalRunId: "ext-202",
            deduplicated: false,
          })
        )
      );

      await expect(client.execute(validRequest)).resolves.toMatchObject({
        status: "accepted",
      });
    });

    it("throws on 401 with status code in error message", async () => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeMockResponse(401, {})));

      await expect(client.execute(validRequest)).rejects.toThrow("401");
    });

    it("throws on 500 with status code in error message", async () => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeMockResponse(500, {})));

      await expect(client.execute(validRequest)).rejects.toThrow("500");
    });

    it("does NOT retry on 500 (idempotency guard server-side)", async () => {
      const mockFetch = vi.fn().mockResolvedValue(makeMockResponse(500, {}));
      vi.stubGlobal("fetch", mockFetch);

      await expect(client.execute(validRequest)).rejects.toThrow();
      expect(mockFetch).toHaveBeenCalledOnce();
    });
  });

  // -------------------------------------------------------------------------
  // health()
  // -------------------------------------------------------------------------
  describe("health()", () => {
    const healthResponse = {
      status: "ok",
      memory: { available: true },
      providers: { available: true },
      qdrant: { available: true },
    };

    it("sends GET to /sidecar/health WITHOUT Authorization header", async () => {
      const mockFetch = vi.fn().mockResolvedValue(makeMockResponse(200, healthResponse));
      vi.stubGlobal("fetch", mockFetch);

      const result = await client.health();

      expect(mockFetch).toHaveBeenCalledOnce();
      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("http://localhost:8001/sidecar/health");
      expect(init.method).toBe("GET");
      expect((init.headers as Record<string, string>)?.["Authorization"]).toBeUndefined();
      expect(result).toEqual(healthResponse);
    });

    it("throws on non-2xx response", async () => {
      // Two calls: first fails (5xx), retry also fails
      vi.stubGlobal(
        "fetch",
        vi.fn()
          .mockResolvedValueOnce(makeMockResponse(503, {}))
          .mockResolvedValueOnce(makeMockResponse(503, {}))
      );

      await expect(client.health()).rejects.toThrow("503");
    });

    it("retries once on 5xx with ~1s backoff before throwing", async () => {
      vi.useFakeTimers();

      const mockFetch = vi.fn()
        .mockResolvedValueOnce(makeMockResponse(503, {}))
        .mockResolvedValueOnce(makeMockResponse(200, healthResponse));

      vi.stubGlobal("fetch", mockFetch);

      const promise = client.health();
      // Allow microtask queue to run so first fetch completes
      await vi.runAllTimersAsync();

      const result = await promise;
      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(result).toEqual(healthResponse);

      vi.useRealTimers();
    });
  });

  // -------------------------------------------------------------------------
  // memoryRecall()
  // -------------------------------------------------------------------------
  describe("memoryRecall()", () => {
    it("sends POST to /memory/recall with top_k (not topK) in request body", async () => {
      const recallRequest: MemoryRecallRequest = {
        query: "find recent tasks",
        agentId: "agent-456",
        top_k: 5,
        score_threshold: 0.7,
      };

      const mockFetch = vi.fn().mockResolvedValue(
        makeMockResponse(200, { memories: [] })
      );
      vi.stubGlobal("fetch", mockFetch);

      await client.memoryRecall(recallRequest);

      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("http://localhost:8001/memory/recall");
      expect(init.method).toBe("POST");
      expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer test-token");

      const body = JSON.parse(init.body as string);
      // Must use snake_case per Research Pitfall 5
      expect(body).toHaveProperty("top_k", 5);
      expect(body).toHaveProperty("score_threshold", 0.7);
      expect(body).not.toHaveProperty("topK");
      expect(body).not.toHaveProperty("scoreThreshold");
    });

    it("returns MemoryRecallResponse with memories array", async () => {
      const expectedMemories = [
        {
          text: "agent completed task successfully",
          score: 0.92,
          source: "agent-456",
          metadata: { task_id: "t1" },
        },
      ];

      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          makeMockResponse(200, { memories: expectedMemories })
        )
      );

      const result = await client.memoryRecall({ query: "test", agentId: "agent-456" });
      expect(result.memories).toEqual(expectedMemories);
    });
  });

  // -------------------------------------------------------------------------
  // memoryStore()
  // -------------------------------------------------------------------------
  describe("memoryStore()", () => {
    it("sends POST to /memory/store with Authorization header and returns MemoryStoreResponse", async () => {
      const storeRequest: MemoryStoreRequest = {
        text: "agent completed task X with strategy Y",
        agentId: "agent-456",
        section: "outcomes",
        tags: ["task", "success"],
      };

      const mockFetch = vi.fn().mockResolvedValue(
        makeMockResponse(200, { stored: true, point_id: "uuid-123" })
      );
      vi.stubGlobal("fetch", mockFetch);

      const result = await client.memoryStore(storeRequest);

      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("http://localhost:8001/memory/store");
      expect(init.method).toBe("POST");
      expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer test-token");
      expect(result).toEqual({ stored: true, point_id: "uuid-123" });
    });
  });

  // -------------------------------------------------------------------------
  // fetchWithTimeout — abort behavior
  // -------------------------------------------------------------------------
  describe("timeout behavior", () => {
    it("passes AbortSignal to fetch and abort fires on timeout", async () => {
      vi.useFakeTimers();

      let capturedSignal: AbortSignal | undefined;

      // Mock fetch that captures the signal and hangs — we handle rejection via the promise chain
      const mockFetch = vi.fn().mockImplementation(
        (_url: string, init: RequestInit) => {
          capturedSignal = init.signal as AbortSignal;
          // Return a promise that resolves when abort fires, to avoid unhandled rejection
          return new Promise<Response>((resolve, reject) => {
            capturedSignal!.addEventListener("abort", () => {
              reject(new DOMException("The operation was aborted.", "AbortError"));
            });
          });
        }
      );
      vi.stubGlobal("fetch", mockFetch);

      const clientShort = new Agent42Client("http://localhost:8001", "test-token");
      // Catch to prevent unhandled rejection — we'll inspect the signal separately
      const promise = clientShort.health().catch(() => null);

      // Advance timers past the 5s health timeout
      await vi.advanceTimersByTimeAsync(6000);
      await promise;

      // The abort signal must have been passed and must now be aborted
      expect(capturedSignal).toBeDefined();
      expect(capturedSignal!.aborted).toBe(true);

      vi.useRealTimers();
    });
  });
});
