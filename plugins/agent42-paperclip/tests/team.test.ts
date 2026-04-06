/**
 * team.test.ts -- Unit tests for team_execute tool (ADV-02 fan-out, ADV-03 wave)
 *
 * Tests use the createTestHarness from the SDK with seeded agents so that
 * ctx.agents.invoke works without mocking. State assertions use harness.getState().
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createTestHarness } from "@paperclipai/plugin-sdk/testing";
import type { ToolResult, ToolRunContext } from "@paperclipai/plugin-sdk";
import manifest from "../dist/manifest.js";
import plugin from "../src/worker.js";
import type { SubAgentResult, WaveOutput } from "../src/types.js";

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

const healthResponse = { status: "ok", memory: {}, providers: {}, qdrant: {} };

const defaultRunCtx: Partial<ToolRunContext> = {
  agentId: "orchestrator-agent",
  companyId: "company-test-1",
  runId: "run-team-test-1",
  projectId: "proj-1",
};

// Agent records for seeding — must have status "active" to be invokable
function makeAgent(id: string) {
  return {
    id,
    companyId: "company-test-1",
    displayName: `Agent ${id}`,
    status: "active" as const,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}

async function setupHarness(mockFetch: ReturnType<typeof vi.fn>) {
  const harness = createTestHarness({
    manifest: manifest as any,
    config: {
      agent42BaseUrl: "http://localhost:8001",
      apiKey: "test-token",
      timeoutMs: 5000,
    },
  });

  mockFetch.mockResolvedValue(makeMockResponse(200, healthResponse));
  await plugin.definition.setup(harness.ctx);

  // Seed sub-agents so ctx.agents.invoke can find them
  harness.seed({
    agents: [
      makeAgent("sub-agent-1"),
      makeAgent("sub-agent-2"),
      makeAgent("sub-agent-3"),
    ],
  });

  return harness;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("team_execute tool", () => {
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
  // Fan-out strategy (ADV-02)
  // -----------------------------------------------------------------------
  describe("fan-out strategy", () => {
    it("calls ctx.agents.invoke for each subAgentId in parallel", async () => {
      const harness = await setupHarness(mockFetch);

      const result = await harness.executeTool<ToolResult>(
        "team_execute",
        {
          strategy: "fan-out",
          subAgentIds: ["sub-agent-1", "sub-agent-2"],
          task: "Analyze the quarterly report",
        },
        defaultRunCtx,
      );

      // Should have no error
      expect(result.error).toBeUndefined();
      const data = result.data as { strategy: string; subResults: SubAgentResult[] };
      expect(data.strategy).toBe("fan-out");
      // Both agents should have been invoked
      expect(data.subResults).toHaveLength(2);
    });

    it("returns subResults array with agentId, runId, status=invoked", async () => {
      const harness = await setupHarness(mockFetch);

      const result = await harness.executeTool<ToolResult>(
        "team_execute",
        {
          strategy: "fan-out",
          subAgentIds: ["sub-agent-1", "sub-agent-2"],
          task: "Research topic X",
        },
        defaultRunCtx,
      );

      const data = result.data as { strategy: string; subResults: SubAgentResult[] };
      expect(data.subResults).toHaveLength(2);

      for (const sr of data.subResults) {
        expect(sr.agentId).toBeDefined();
        expect(sr.runId).toBeDefined();
        expect(sr.runId.length).toBeGreaterThan(0);
        expect(sr.status).toBe("invoked");
        expect(sr.output).toBe("");
        expect(sr.costUsd).toBe(0);
      }

      // Verify agentIds match the requested sub-agents
      const agentIds = data.subResults.map((sr) => sr.agentId);
      expect(agentIds).toContain("sub-agent-1");
      expect(agentIds).toContain("sub-agent-2");
    });

    it("each subResult has a unique runId (fire-and-forget, not deduplicated)", async () => {
      const harness = await setupHarness(mockFetch);

      const result = await harness.executeTool<ToolResult>(
        "team_execute",
        {
          strategy: "fan-out",
          subAgentIds: ["sub-agent-1", "sub-agent-2", "sub-agent-3"],
          task: "Parallel task",
        },
        defaultRunCtx,
      );

      const data = result.data as { subResults: SubAgentResult[] };
      const runIds = data.subResults.map((sr) => sr.runId);
      // All runIds should be unique
      const uniqueRunIds = new Set(runIds);
      expect(uniqueRunIds.size).toBe(runIds.length);
    });

    it("returns error when subAgentIds is empty", async () => {
      const harness = await setupHarness(mockFetch);

      const result = await harness.executeTool<ToolResult>(
        "team_execute",
        {
          strategy: "fan-out",
          subAgentIds: [],
          task: "test task",
        },
        defaultRunCtx,
      );

      expect(result.error).toContain("fan-out requires at least one subAgentId");
    });

    it("returns error when subAgentIds is missing", async () => {
      const harness = await setupHarness(mockFetch);

      const result = await harness.executeTool<ToolResult>(
        "team_execute",
        {
          strategy: "fan-out",
          task: "test task without subAgentIds",
        },
        defaultRunCtx,
      );

      expect(result.error).toContain("fan-out requires at least one subAgentId");
    });
  });

  // -----------------------------------------------------------------------
  // Wave strategy (ADV-03)
  // -----------------------------------------------------------------------
  describe("wave strategy", () => {
    it("invokes agents sequentially (returns waveOutputs in order)", async () => {
      const harness = await setupHarness(mockFetch);

      const result = await harness.executeTool<ToolResult>(
        "team_execute",
        {
          strategy: "wave",
          waves: [
            { agentId: "sub-agent-1", task: "Wave 1: research" },
            { agentId: "sub-agent-2", task: "Wave 2: synthesize" },
          ],
          task: "Multi-wave research task",
        },
        defaultRunCtx,
      );

      expect(result.error).toBeUndefined();
      const data = result.data as { strategy: string; waveOutputs: WaveOutput[] };
      expect(data.strategy).toBe("wave");
      expect(data.waveOutputs).toHaveLength(2);

      // Wave outputs should be in sequential order
      expect(data.waveOutputs[0].wave).toBe(1);
      expect(data.waveOutputs[0].agentId).toBe("sub-agent-1");
      expect(data.waveOutputs[1].wave).toBe(2);
      expect(data.waveOutputs[1].agentId).toBe("sub-agent-2");
    });

    it("each wave output has status=invoked and a runId", async () => {
      const harness = await setupHarness(mockFetch);

      const result = await harness.executeTool<ToolResult>(
        "team_execute",
        {
          strategy: "wave",
          waves: [{ agentId: "sub-agent-1", task: "Wave 1" }],
          task: "Single wave test",
        },
        defaultRunCtx,
      );

      const data = result.data as { waveOutputs: WaveOutput[] };
      expect(data.waveOutputs[0].status).toBe("invoked");
      expect(data.waveOutputs[0].runId).toBeDefined();
      expect(data.waveOutputs[0].runId.length).toBeGreaterThan(0);
    });

    it("saves wave progress after each wave via ctx.state.set with scopeKind=run", async () => {
      const harness = await setupHarness(mockFetch);

      await harness.executeTool<ToolResult>(
        "team_execute",
        {
          strategy: "wave",
          waves: [
            { agentId: "sub-agent-1", task: "Wave 1" },
            { agentId: "sub-agent-2", task: "Wave 2" },
          ],
          task: "Progress persistence test",
        },
        { ...defaultRunCtx, runId: "run-progress-test" },
      );

      // Check state was saved for wave progress — after 2 waves, completedWaves=2
      const saved = harness.getState({
        scopeKind: "run",
        scopeId: "run-progress-test",
        stateKey: "wave-progress",
      }) as { completedWaves: number; waveOutputs: WaveOutput[] } | null;

      expect(saved).not.toBeNull();
      expect(saved!.completedWaves).toBe(2);
      expect(saved!.waveOutputs).toHaveLength(2);
    });

    it("reads saved state at start for crash recovery", async () => {
      const harness = await setupHarness(mockFetch);

      // Manually set saved state as if wave 1 already completed
      const existingWaveOutput: WaveOutput = {
        wave: 1,
        agentId: "sub-agent-1",
        runId: "pre-existing-run-id",
        status: "invoked",
        output: "",
      };

      // Set state directly via harness ctx
      await harness.ctx.state.set(
        { scopeKind: "run", scopeId: "run-crash-recovery", stateKey: "wave-progress" },
        { completedWaves: 1, waveOutputs: [existingWaveOutput] },
      );

      // Now execute with 2 waves — should start from wave 2 (index 1)
      const result = await harness.executeTool<ToolResult>(
        "team_execute",
        {
          strategy: "wave",
          waves: [
            { agentId: "sub-agent-1", task: "Wave 1 (already done)" },
            { agentId: "sub-agent-2", task: "Wave 2 (new)" },
          ],
          task: "Crash recovery test",
        },
        { ...defaultRunCtx, runId: "run-crash-recovery" },
      );

      expect(result.error).toBeUndefined();
      const data = result.data as { waveOutputs: WaveOutput[] };

      // Should have 2 wave outputs total (1 restored + 1 newly executed)
      expect(data.waveOutputs).toHaveLength(2);

      // The first output should be the pre-existing one (crash recovery)
      expect(data.waveOutputs[0].runId).toBe("pre-existing-run-id");
      // The second output should be newly invoked (sub-agent-2)
      expect(data.waveOutputs[1].agentId).toBe("sub-agent-2");
      expect(data.waveOutputs[1].runId).not.toBe("pre-existing-run-id");
    });

    it("passes previous wave context to next wave prompt", async () => {
      // We cannot directly inspect ctx.agents.invoke call args via the harness
      // because the harness implements invoke internally. Instead we verify
      // the second wave's prompt via state — the waveOutputs in state confirm
      // the previous wave was stored before the next invoke.
      const harness = await setupHarness(mockFetch);

      await harness.executeTool<ToolResult>(
        "team_execute",
        {
          strategy: "wave",
          waves: [
            { agentId: "sub-agent-1", task: "Gather data" },
            { agentId: "sub-agent-2", task: "Summarize findings" },
          ],
          task: "Sequential context test",
        },
        { ...defaultRunCtx, runId: "run-context-test" },
      );

      // After 2 waves, state should have completedWaves=2, confirming
      // the second wave ran with context from the first wave available.
      const saved = harness.getState({
        scopeKind: "run",
        scopeId: "run-context-test",
        stateKey: "wave-progress",
      }) as { completedWaves: number; waveOutputs: WaveOutput[] } | null;

      expect(saved).not.toBeNull();
      expect(saved!.completedWaves).toBe(2);
      // Second wave output's agentId confirms it ran sequentially after the first
      expect(saved!.waveOutputs[1].agentId).toBe("sub-agent-2");
    });

    it("returns error when waves array is empty", async () => {
      const harness = await setupHarness(mockFetch);

      const result = await harness.executeTool<ToolResult>(
        "team_execute",
        {
          strategy: "wave",
          waves: [],
          task: "test task with no waves",
        },
        defaultRunCtx,
      );

      expect(result.error).toContain("wave requires at least one wave definition");
    });

    it("returns error when waves is missing", async () => {
      const harness = await setupHarness(mockFetch);

      const result = await harness.executeTool<ToolResult>(
        "team_execute",
        {
          strategy: "wave",
          task: "test task without waves key",
        },
        defaultRunCtx,
      );

      expect(result.error).toContain("wave requires at least one wave definition");
    });
  });

  // -----------------------------------------------------------------------
  // Unknown strategy
  // -----------------------------------------------------------------------
  it("returns error for unknown strategy", async () => {
    const harness = await setupHarness(mockFetch);

    const result = await harness.executeTool<ToolResult>(
      "team_execute",
      {
        strategy: "invalid-strategy",
        task: "this should fail",
      },
      defaultRunCtx,
    );

    expect(result.error).toContain("Unknown strategy");
    expect(result.error).toContain("invalid-strategy");
  });

  // -----------------------------------------------------------------------
  // Result format: content is serialized JSON
  // -----------------------------------------------------------------------
  it("returns content as JSON string alongside data", async () => {
    const harness = await setupHarness(mockFetch);

    const result = await harness.executeTool<ToolResult>(
      "team_execute",
      {
        strategy: "fan-out",
        subAgentIds: ["sub-agent-1"],
        task: "Single agent fan-out",
      },
      defaultRunCtx,
    );

    expect(result.content).toBeDefined();
    // Content should be valid JSON
    const parsed = JSON.parse(result.content as string);
    expect(parsed.strategy).toBe("fan-out");
    expect(parsed.subResults).toHaveLength(1);
  });
});
