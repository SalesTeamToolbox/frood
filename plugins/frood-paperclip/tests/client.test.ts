import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { Agent42Client } from "../src/client.js";
import type {
  MemoryRecallRequest,
  MemoryStoreRequest,
  RoutingResolveRequest,
  EffectivenessRequest,
  MCPToolRequest,
  ExtractLearningsRequest,
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
    client = new Agent42Client("http://localhost:8001", "test-token", 5000);
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllTimers();
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

    it("calls GET /sidecar/health without Authorization header", async () => {
      const mockFetch = vi.fn().mockResolvedValue(makeMockResponse(200, healthResponse));
      vi.stubGlobal("fetch", mockFetch);

      await client.health();

      expect(mockFetch).toHaveBeenCalledOnce();
      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("http://localhost:8001/sidecar/health");
      expect(init.method).toBe("GET");
      expect((init.headers as Record<string, string>)?.["Authorization"]).toBeUndefined();
    });

    it("returns parsed SidecarHealthResponse", async () => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeMockResponse(200, healthResponse)));

      const result = await client.health();
      expect(result).toEqual(healthResponse);
    });

    it("retries once on 500 — calls fetch twice and returns second result", async () => {
      vi.useFakeTimers();
      const mockFetch = vi
        .fn()
        .mockResolvedValueOnce(makeMockResponse(500, {}))
        .mockResolvedValueOnce(makeMockResponse(200, healthResponse));
      vi.stubGlobal("fetch", mockFetch);

      const promise = client.health();
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
    it("sends correct body with snake_case fields (top_k not topK)", async () => {
      const recallRequest: MemoryRecallRequest = {
        query: "find recent tasks",
        agentId: "agent-456",
        top_k: 5,
        score_threshold: 0.7,
      };
      const mockFetch = vi.fn().mockResolvedValue(makeMockResponse(200, { memories: [] }));
      vi.stubGlobal("fetch", mockFetch);

      await client.memoryRecall(recallRequest);

      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("http://localhost:8001/memory/recall");
      expect(init.method).toBe("POST");
      const body = JSON.parse(init.body as string);
      // Must use snake_case -- NO camelCase alias on Python side
      expect(body).toHaveProperty("top_k", 5);
      expect(body).toHaveProperty("score_threshold", 0.7);
      expect(body).not.toHaveProperty("topK");
      expect(body).not.toHaveProperty("scoreThreshold");
    });

    it("includes Bearer auth header", async () => {
      const mockFetch = vi.fn().mockResolvedValue(makeMockResponse(200, { memories: [] }));
      vi.stubGlobal("fetch", mockFetch);

      await client.memoryRecall({ query: "test", agentId: "agent-1" });

      const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer test-token");
    });
  });

  // -------------------------------------------------------------------------
  // memoryStore()
  // -------------------------------------------------------------------------
  describe("memoryStore()", () => {
    it("sends correct body with text, agentId, and tags", async () => {
      const storeRequest: MemoryStoreRequest = {
        text: "agent completed task X with strategy Y",
        agentId: "agent-456",
        tags: ["task", "success"],
        section: "outcomes",
      };
      const mockFetch = vi.fn().mockResolvedValue(
        makeMockResponse(200, { stored: true, point_id: "uuid-123" })
      );
      vi.stubGlobal("fetch", mockFetch);

      const result = await client.memoryStore(storeRequest);

      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("http://localhost:8001/memory/store");
      expect(init.method).toBe("POST");
      const body = JSON.parse(init.body as string);
      expect(body.text).toBe("agent completed task X with strategy Y");
      expect(body.agentId).toBe("agent-456");
      expect(body.tags).toEqual(["task", "success"]);
      expect(result).toEqual({ stored: true, point_id: "uuid-123" });
    });
  });

  // -------------------------------------------------------------------------
  // routeTask()
  // -------------------------------------------------------------------------
  describe("routeTask()", () => {
    it("sends taskType and agentId in POST to /routing/resolve", async () => {
      const routeRequest: RoutingResolveRequest = {
        taskType: "engineer",
        agentId: "agent-789",
      };
      const mockFetch = vi.fn().mockResolvedValue(
        makeMockResponse(200, {
          provider: "cerebras",
          model: "llama3.1-70b",
          tier: "free",
          taskCategory: "coding",
        })
      );
      vi.stubGlobal("fetch", mockFetch);

      const result = await client.routeTask(routeRequest);

      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("http://localhost:8001/routing/resolve");
      expect(init.method).toBe("POST");
      const body = JSON.parse(init.body as string);
      expect(body.taskType).toBe("engineer");
      expect(body.agentId).toBe("agent-789");
      expect(result.provider).toBe("cerebras");
    });
  });

  // -------------------------------------------------------------------------
  // toolEffectiveness()
  // -------------------------------------------------------------------------
  describe("toolEffectiveness()", () => {
    it("sends taskType in POST to /effectiveness/recommendations", async () => {
      const effectRequest: EffectivenessRequest = { taskType: "researcher" };
      const mockFetch = vi.fn().mockResolvedValue(
        makeMockResponse(200, {
          tools: [{ name: "memory_tool", successRate: 0.95, observations: 12 }],
        })
      );
      vi.stubGlobal("fetch", mockFetch);

      const result = await client.toolEffectiveness(effectRequest);

      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("http://localhost:8001/effectiveness/recommendations");
      expect(init.method).toBe("POST");
      const body = JSON.parse(init.body as string);
      expect(body.taskType).toBe("researcher");
      expect(result.tools[0].name).toBe("memory_tool");
    });
  });

  // -------------------------------------------------------------------------
  // mcpTool()
  // -------------------------------------------------------------------------
  describe("mcpTool()", () => {
    it("sends toolName and params in POST to /mcp/tool", async () => {
      const mcpRequest: MCPToolRequest = {
        toolName: "content_analyzer",
        params: { text: "analyze this" },
      };
      const mockFetch = vi.fn().mockResolvedValue(
        makeMockResponse(200, { result: { score: 0.8 }, error: null })
      );
      vi.stubGlobal("fetch", mockFetch);

      const result = await client.mcpTool(mcpRequest);

      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("http://localhost:8001/mcp/tool");
      expect(init.method).toBe("POST");
      const body = JSON.parse(init.body as string);
      expect(body.toolName).toBe("content_analyzer");
      expect(body.params).toEqual({ text: "analyze this" });
      expect(result.error).toBeNull();
    });

    it("throws on non-ok response (403)", async () => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(makeMockResponse(403, {})));

      await expect(
        client.mcpTool({ toolName: "forbidden_tool", params: {} })
      ).rejects.toThrow("403");
    });
  });

  // -------------------------------------------------------------------------
  // destroy()
  // -------------------------------------------------------------------------
  describe("destroy()", () => {
    it("does not throw when called", () => {
      expect(() => client.destroy()).not.toThrow();
    });
  });

  // -------------------------------------------------------------------------
  // getAgentProfile()
  // -------------------------------------------------------------------------
  describe("getAgentProfile()", () => {
    it("calls GET /agent/{id}/profile with auth", async () => {
      const profile = { agentId: "a-1", tier: "gold", successRate: 0.95, taskVolume: 100, avgSpeedMs: 50, compositeScore: 0.9 };
      const mockFetch = vi.fn().mockResolvedValue(makeMockResponse(200, profile));
      vi.stubGlobal("fetch", mockFetch);

      const result = await client.getAgentProfile("a-1");

      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("http://localhost:8001/agent/a-1/profile");
      expect(init.method).toBe("GET");
      expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer test-token");
      expect(result).toEqual(profile);
    });
  });

  // -------------------------------------------------------------------------
  // getAgentEffectiveness()
  // -------------------------------------------------------------------------
  describe("getAgentEffectiveness()", () => {
    it("calls GET /agent/{id}/effectiveness with auth", async () => {
      const effectiveness = { agentId: "a-1", stats: [{ taskType: "code", successRate: 0.9, count: 10, avgDurationMs: 500 }] };
      const mockFetch = vi.fn().mockResolvedValue(makeMockResponse(200, effectiveness));
      vi.stubGlobal("fetch", mockFetch);

      const result = await client.getAgentEffectiveness("a-1");

      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("http://localhost:8001/agent/a-1/effectiveness");
      expect(init.method).toBe("GET");
      expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer test-token");
      expect(result).toHaveProperty("stats");
    });
  });

  // -------------------------------------------------------------------------
  // getRoutingHistory()
  // -------------------------------------------------------------------------
  describe("getRoutingHistory()", () => {
    it("calls GET with limit query param", async () => {
      const history = { agentId: "a-1", entries: [] };
      const mockFetch = vi.fn().mockResolvedValue(makeMockResponse(200, history));
      vi.stubGlobal("fetch", mockFetch);

      await client.getRoutingHistory("a-1");

      const [url] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("http://localhost:8001/agent/a-1/routing-history?limit=20");
    });

    it("uses custom limit parameter", async () => {
      const history = { agentId: "a-1", entries: [] };
      const mockFetch = vi.fn().mockResolvedValue(makeMockResponse(200, history));
      vi.stubGlobal("fetch", mockFetch);

      await client.getRoutingHistory("a-1", 50);

      const [url] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toContain("?limit=50");
    });
  });

  // -------------------------------------------------------------------------
  // getMemoryRunTrace()
  // -------------------------------------------------------------------------
  describe("getMemoryRunTrace()", () => {
    it("calls GET /memory/run-trace/{runId} with auth", async () => {
      const trace = { runId: "r-1", injectedMemories: [], extractedLearnings: [] };
      const mockFetch = vi.fn().mockResolvedValue(makeMockResponse(200, trace));
      vi.stubGlobal("fetch", mockFetch);

      const result = await client.getMemoryRunTrace("r-1");

      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("http://localhost:8001/memory/run-trace/r-1");
      expect(init.method).toBe("GET");
      expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer test-token");
      expect(result).toHaveProperty("runId", "r-1");
    });
  });

  // -------------------------------------------------------------------------
  // getAgentSpend()
  // -------------------------------------------------------------------------
  describe("getAgentSpend()", () => {
    it("calls GET with hours query param", async () => {
      const spend = { agentId: "a-1", hours: 24, entries: [], totalCostUsd: 0 };
      const mockFetch = vi.fn().mockResolvedValue(makeMockResponse(200, spend));
      vi.stubGlobal("fetch", mockFetch);

      await client.getAgentSpend("a-1");

      const [url] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("http://localhost:8001/agent/a-1/spend?hours=24");
    });
  });

  // -------------------------------------------------------------------------
  // extractLearnings()
  // -------------------------------------------------------------------------
  describe("extractLearnings()", () => {
    it("calls POST /memory/extract with body", async () => {
      const extractRequest: ExtractLearningsRequest = { sinceTs: null, batchSize: 20 };
      const mockFetch = vi.fn().mockResolvedValue(makeMockResponse(200, { extracted: 3, skipped: 0 }));
      vi.stubGlobal("fetch", mockFetch);

      const result = await client.extractLearnings(extractRequest);

      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("http://localhost:8001/memory/extract");
      expect(init.method).toBe("POST");
      const body = JSON.parse(init.body as string);
      expect(body).toEqual({ sinceTs: null, batchSize: 20 });
      expect(result).toEqual({ extracted: 3, skipped: 0 });
    });
  });
});
