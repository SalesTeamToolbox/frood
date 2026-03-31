import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createTestHarness } from "@paperclipai/plugin-sdk/testing";
import type { ToolResult, ToolRunContext } from "@paperclipai/plugin-sdk";
import manifest from "../manifest.json" with { type: "json" };
import plugin from "../src/worker.js";

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

const defaultRunCtx: Partial<ToolRunContext> = {
  agentId: "agent-test-1",
  companyId: "company-test-1",
  runId: "run-1",
  projectId: "proj-1",
};

const defaultConfig = {
  agent42BaseUrl: "http://localhost:8001",
  apiKey: "test-token",
  timeoutMs: 5000,
};

// ---------------------------------------------------------------------------
// Setup helpers
// ---------------------------------------------------------------------------

async function setupHarness(mockFetch: ReturnType<typeof vi.fn>) {
  const harness = createTestHarness({
    manifest: manifest as any,
    config: defaultConfig,
  });

  // Health endpoint for setup
  mockFetch.mockResolvedValue(
    makeMockResponse(200, { status: "ok", memory: {}, providers: {}, qdrant: {} })
  );

  await plugin.definition.setup(harness.ctx);
  return harness;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Plugin Tools", () => {
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockFetch = vi.fn();
    vi.stubGlobal("fetch", mockFetch);
  });

  afterEach(async () => {
    await plugin.definition.onShutdown?.();
    vi.unstubAllGlobals();
  });

  // -----------------------------------------------------------------------
  // memory_recall (PLUG-02)
  // -----------------------------------------------------------------------
  describe("memory_recall", () => {
    it("returns memories from sidecar", async () => {
      const harness = await setupHarness(mockFetch);
      mockFetch.mockResolvedValue(
        makeMockResponse(200, {
          memories: [{ text: "test memory", score: 0.9, source: "kb", metadata: {} }],
        })
      );

      const result = await harness.executeTool<ToolResult>(
        "memory_recall",
        { query: "find tasks" },
        defaultRunCtx,
      );

      expect(result.data).toBeDefined();
      const data = result.data as { memories: { text: string; score: number; source: string }[] };
      expect(data.memories).toHaveLength(1);
      expect(data.memories[0].text).toBe("test memory");
      expect(data.memories[0].score).toBe(0.9);
    });

    it("sends top_k and score_threshold in snake_case", async () => {
      const harness = await setupHarness(mockFetch);
      mockFetch.mockResolvedValue(makeMockResponse(200, { memories: [] }));

      await harness.executeTool<ToolResult>(
        "memory_recall",
        { query: "q", topK: 3, scoreThreshold: 0.5 },
        defaultRunCtx,
      );

      // Find the POST /memory/recall call (not the health call)
      const recallCall = mockFetch.mock.calls.find(
        ([url]: [string]) => typeof url === "string" && url.includes("/memory/recall")
      );
      expect(recallCall).toBeDefined();
      const body = JSON.parse(recallCall![1].body as string);
      expect(body).toHaveProperty("top_k", 3);
      expect(body).toHaveProperty("score_threshold", 0.5);
      expect(body).not.toHaveProperty("topK");
      expect(body).not.toHaveProperty("scoreThreshold");
    });

    it("returns error when sidecar fails", async () => {
      const harness = await setupHarness(mockFetch);
      mockFetch.mockRejectedValue(new Error("Network error"));

      const result = await harness.executeTool<ToolResult>(
        "memory_recall",
        { query: "test" },
        defaultRunCtx,
      );

      expect(result.error).toContain("memory_recall failed");
    });
  });

  // -----------------------------------------------------------------------
  // memory_store (PLUG-03)
  // -----------------------------------------------------------------------
  describe("memory_store", () => {
    it("stores content and returns pointId", async () => {
      const harness = await setupHarness(mockFetch);
      mockFetch.mockResolvedValue(
        makeMockResponse(200, { stored: true, point_id: "pt-123" })
      );

      const result = await harness.executeTool<ToolResult>(
        "memory_store",
        { content: "learned thing", tags: ["test"] },
        defaultRunCtx,
      );

      const data = result.data as { stored: boolean; pointId: string };
      expect(data.stored).toBe(true);
      expect(data.pointId).toBe("pt-123");
    });

    it("maps content param to text field", async () => {
      const harness = await setupHarness(mockFetch);
      mockFetch.mockResolvedValue(
        makeMockResponse(200, { stored: true, point_id: "pt-456" })
      );

      await harness.executeTool<ToolResult>(
        "memory_store",
        { content: "my learning" },
        defaultRunCtx,
      );

      const storeCall = mockFetch.mock.calls.find(
        ([url]: [string]) => typeof url === "string" && url.includes("/memory/store")
      );
      expect(storeCall).toBeDefined();
      const body = JSON.parse(storeCall![1].body as string);
      expect(body.text).toBe("my learning");
      expect(body).not.toHaveProperty("content");
    });
  });

  // -----------------------------------------------------------------------
  // route_task (PLUG-04)
  // -----------------------------------------------------------------------
  describe("route_task", () => {
    it("returns routing recommendation", async () => {
      const harness = await setupHarness(mockFetch);
      mockFetch.mockResolvedValue(
        makeMockResponse(200, {
          provider: "synthetic",
          model: "hf:zai-org/GLM-4.7",
          tier: "bronze",
          taskCategory: "coding",
        })
      );

      const result = await harness.executeTool<ToolResult>(
        "route_task",
        { taskType: "engineer" },
        defaultRunCtx,
      );

      const data = result.data as { provider: string; model: string; tier: string; taskCategory: string };
      expect(data.provider).toBe("synthetic");
      expect(data.model).toBe("hf:zai-org/GLM-4.7");
      expect(data.tier).toBe("bronze");
      expect(data.taskCategory).toBe("coding");
    });
  });

  // -----------------------------------------------------------------------
  // tool_effectiveness (PLUG-05)
  // -----------------------------------------------------------------------
  describe("tool_effectiveness", () => {
    it("returns top tools", async () => {
      const harness = await setupHarness(mockFetch);
      mockFetch.mockResolvedValue(
        makeMockResponse(200, {
          tools: [{ name: "code_intel", successRate: 0.95, observations: 42 }],
        })
      );

      const result = await harness.executeTool<ToolResult>(
        "tool_effectiveness",
        { taskType: "coding" },
        defaultRunCtx,
      );

      const data = result.data as { tools: { name: string; successRate: number }[] };
      expect(data.tools).toHaveLength(1);
      expect(data.tools[0].name).toBe("code_intel");
    });
  });

  // -----------------------------------------------------------------------
  // mcp_tool_proxy (PLUG-06)
  // -----------------------------------------------------------------------
  describe("mcp_tool_proxy", () => {
    it("proxies tool call and returns result", async () => {
      const harness = await setupHarness(mockFetch);
      mockFetch.mockResolvedValue(
        makeMockResponse(200, { result: "analysis output", error: null })
      );

      const result = await harness.executeTool<ToolResult>(
        "mcp_tool_proxy",
        { toolName: "content_analyzer", params: { text: "hello" } },
        defaultRunCtx,
      );

      const data = result.data as { result: unknown };
      expect(data.result).toBe("analysis output");
    });

    it("returns error when sidecar returns error", async () => {
      const harness = await setupHarness(mockFetch);
      mockFetch.mockResolvedValue(
        makeMockResponse(200, { result: null, error: "Tool not in allowlist" })
      );

      const result = await harness.executeTool<ToolResult>(
        "mcp_tool_proxy",
        { toolName: "shell", params: {} },
        defaultRunCtx,
      );

      expect(result.error).toContain("mcp_tool_proxy");
    });

    it("does not inject agentId for mcp_tool_proxy", async () => {
      const harness = await setupHarness(mockFetch);
      mockFetch.mockResolvedValue(
        makeMockResponse(200, { result: "ok", error: null })
      );

      await harness.executeTool<ToolResult>(
        "mcp_tool_proxy",
        { toolName: "content_analyzer", params: {} },
        defaultRunCtx,
      );

      const mcpCall = mockFetch.mock.calls.find(
        ([url]: [string]) => typeof url === "string" && url.includes("/mcp/tool")
      );
      expect(mcpCall).toBeDefined();
      const body = JSON.parse(mcpCall![1].body as string);
      expect(body).not.toHaveProperty("agentId");
    });
  });

  // -----------------------------------------------------------------------
  // Cross-cutting: agentId/companyId injection
  // -----------------------------------------------------------------------
  describe("agentId/companyId injection", () => {
    it("all identity-aware tools inject agentId from runCtx", async () => {
      const harness = await setupHarness(mockFetch);
      mockFetch.mockResolvedValue(makeMockResponse(200, { memories: [] }));

      await harness.executeTool<ToolResult>(
        "memory_recall",
        { query: "test" },
        { agentId: "custom-agent", companyId: "custom-company", runId: "r1", projectId: "p1" },
      );

      const recallCall = mockFetch.mock.calls.find(
        ([url]: [string]) => typeof url === "string" && url.includes("/memory/recall")
      );
      const body = JSON.parse(recallCall![1].body as string);
      expect(body.agentId).toBe("custom-agent");
      expect(body.companyId).toBe("custom-company");
    });
  });
});
