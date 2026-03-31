import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { Agent42Client } from "../src/client.js";
import type {
  MemoryRecallRequest,
  MemoryStoreRequest,
  RoutingResolveRequest,
  EffectivenessRequest,
  MCPToolRequest,
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
});
