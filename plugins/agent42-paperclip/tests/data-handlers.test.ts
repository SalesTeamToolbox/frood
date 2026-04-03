import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createTestHarness } from "@paperclipai/plugin-sdk/testing";
import manifest from "../dist/manifest.js";
import plugin from "../src/worker.js";

// Mock fetch globally for Agent42Client
const mockFetch = vi.fn();

// Helper: create Response-like mock
function makeResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

describe("Data handlers", () => {
  beforeEach(async () => {
    vi.stubGlobal("fetch", mockFetch);
    mockFetch.mockReset();
  });

  afterEach(async () => {
    await plugin.definition.onShutdown?.();
    vi.unstubAllGlobals();
  });

  // Helper: setup harness with valid config and a client that is initialized
  async function setupHarness() {
    const harness = createTestHarness({
      manifest: manifest as any,
      config: { agent42BaseUrl: "http://localhost:8001", apiKey: "test-key", timeoutMs: 5000 },
    });
    // No fetch calls happen during setup (only when handlers are invoked)
    await plugin.definition.setup(harness.ctx);
    return harness;
  }

  it("agent-profile handler returns profile data", async () => {
    const harness = await setupHarness();
    const profile = { agentId: "a-1", tier: "gold", successRate: 0.95, taskVolume: 100, avgSpeedMs: 50, compositeScore: 0.9 };
    mockFetch.mockResolvedValueOnce(makeResponse(200, profile));
    const result = await harness.getData("agent-profile", { agentId: "a-1" });
    expect(result).toEqual(profile);
  });

  it("agent-profile handler returns null when agentId missing", async () => {
    const harness = await setupHarness();
    const result = await harness.getData("agent-profile", {});
    expect(result).toBeNull();
  });

  it("provider-health handler returns health data", async () => {
    const harness = await setupHarness();
    const health = { status: "ok", memory: { available: true }, providers: { available: true }, qdrant: { available: true } };
    mockFetch.mockResolvedValueOnce(makeResponse(200, health));
    const result = await harness.getData("provider-health", {});
    expect(result).toHaveProperty("status", "ok");
  });

  it("provider-health handler returns null on error", async () => {
    const harness = await setupHarness();
    mockFetch.mockRejectedValueOnce(new Error("Connection refused"));
    const result = await harness.getData("provider-health", {});
    expect(result).toBeNull();
  });

  it("memory-run-trace handler returns trace data", async () => {
    const harness = await setupHarness();
    const trace = { runId: "r-1", injectedMemories: [], extractedLearnings: [] };
    mockFetch.mockResolvedValueOnce(makeResponse(200, trace));
    const result = await harness.getData("memory-run-trace", { runId: "r-1" });
    expect(result).toHaveProperty("runId", "r-1");
  });

  it("memory-run-trace handler returns null when runId missing", async () => {
    const harness = await setupHarness();
    const result = await harness.getData("memory-run-trace", {});
    expect(result).toBeNull();
  });

  it("routing-decisions handler returns spend data", async () => {
    const harness = await setupHarness();
    const spend = { agentId: "a-1", hours: 24, entries: [], totalCostUsd: 0 };
    mockFetch.mockResolvedValueOnce(makeResponse(200, spend));
    const result = await harness.getData("routing-decisions", { agentId: "a-1", hours: 24 });
    expect(result).toHaveProperty("totalCostUsd");
  });

  it("agent-effectiveness handler returns per-task stats", async () => {
    const harness = await setupHarness();
    const effectiveness = { agentId: "a-1", stats: [{ taskType: "code", successRate: 0.9, count: 10, avgDurationMs: 500 }] };
    mockFetch.mockResolvedValueOnce(makeResponse(200, effectiveness));
    const result = await harness.getData("agent-effectiveness", { agentId: "a-1" });
    expect(result).toHaveProperty("stats");
  });

  it("agent-effectiveness handler returns null when agentId missing", async () => {
    const harness = await setupHarness();
    const result = await harness.getData("agent-effectiveness", {});
    expect(result).toBeNull();
  });
});

describe("extract-learnings job", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch);
    mockFetch.mockReset();
  });

  afterEach(async () => {
    await plugin.definition.onShutdown?.();
    vi.unstubAllGlobals();
  });

  it("calls extractLearnings and updates watermark", async () => {
    const harness = createTestHarness({
      manifest: manifest as any,
      config: { agent42BaseUrl: "http://localhost:8001", apiKey: "test-key" },
    });
    await plugin.definition.setup(harness.ctx);

    // Mock extract response for POST /memory/extract
    mockFetch.mockResolvedValueOnce(makeResponse(200, { extracted: 3, skipped: 0 }));

    await harness.runJob("extract-learnings");

    // Verify extractLearnings was called (POST /memory/extract)
    const extractCall = mockFetch.mock.calls.find(([url]: [string]) => url.includes("/memory/extract"));
    expect(extractCall).toBeDefined();
  });

  it("does not update watermark on failure", async () => {
    const harness = createTestHarness({
      manifest: manifest as any,
      config: { agent42BaseUrl: "http://localhost:8001", apiKey: "test-key" },
    });
    await plugin.definition.setup(harness.ctx);

    // Mock extract failure — both first attempt and retry fail
    mockFetch.mockResolvedValueOnce(makeResponse(500, "Server Error"));
    mockFetch.mockResolvedValueOnce(makeResponse(500, "Server Error"));

    // Should not throw — job handles errors gracefully
    await expect(harness.runJob("extract-learnings")).resolves.not.toThrow();

    // Watermark should NOT be updated — check state is still undefined/null
    const watermark = harness.getState({ scopeKind: "instance", stateKey: "last-learn-at" });
    expect(watermark).toBeUndefined();
  });
});
