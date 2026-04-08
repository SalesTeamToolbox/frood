/**
 * adapter.test.ts — Tests for the execute(), testEnvironment(), and index.ts default export.
 *
 * Mock strategy: vi.stubGlobal("fetch", vi.fn()) intercepts all HTTP calls
 * without requiring a live server or MSW.
 *
 * Test groups:
 *   1. execute() — flow, agentId extraction, wakeReason mapping, session state, error handling
 *   2. testEnvironment() — pass/warn/fail outcomes, health checks
 *   3. default export — index.ts shape (ServerAdapterModule)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { execute, testEnvironment } from "../src/adapter.js";
import type {
  AdapterExecutionContext,
  AdapterEnvironmentTestContext,
} from "@paperclipai/adapter-utils";
import adapter from "../src/index.js";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

/**
 * mockFetchResponse — creates a minimal Response-like object that vitest fetch mocks accept.
 */
function mockFetchResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  };
}

/**
 * makePaperclipCtx — minimal AdapterExecutionContext factory.
 * Overrides are shallow-merged into the default structure.
 */
function makePaperclipCtx(
  overrides: Partial<{
    runId: string;
    agentId: string;
    companyId: string;
    adapterConfig: Record<string, unknown>;
    sessionParams: Record<string, unknown> | null;
    context: Record<string, unknown>;
    onLog: (stream: "stdout" | "stderr", chunk: string) => Promise<void>;
  }> = {},
): AdapterExecutionContext {
  const onLog = overrides.onLog ?? vi.fn(async () => {});
  return {
    runId: overrides.runId ?? "run-001",
    agent: {
      id: overrides.agentId ?? "paperclip-agent-uuid",
      companyId: overrides.companyId ?? "company-001",
      name: "Test Agent",
      adapterType: "agent42_local",
      adapterConfig: overrides.adapterConfig ?? {
        sidecarUrl: "http://localhost:8000",
        bearerToken: "test-token",
        agentId: "agent42-uuid",
        preferredProvider: "cerebras",
        memoryScope: "agent",
      },
    },
    runtime: {
      sessionId: null,
      sessionParams: overrides.sessionParams !== undefined ? overrides.sessionParams : null,
      sessionDisplayId: null,
      taskKey: null,
    },
    config: {},
    context: overrides.context ?? { wakeReason: "heartbeat" },
    onLog,
  } as unknown as AdapterExecutionContext;
}

const DEFAULT_EXECUTE_RESPONSE = {
  status: "accepted",
  externalRunId: "ext-run-001",
  deduplicated: false,
};

const DEFAULT_HEALTH_RESPONSE = {
  status: "ok",
  memory: { available: true },
  providers: { available: true },
  qdrant: { available: true },
};

// ---------------------------------------------------------------------------
// execute()
// ---------------------------------------------------------------------------

describe("execute", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      mockFetchResponse(202, DEFAULT_EXECUTE_RESPONSE)
    ));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts to /sidecar/execute with correct runId", async () => {
    const ctx = makePaperclipCtx({ runId: "run-xyz" });
    await execute(ctx);

    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toContain("/sidecar/execute");
    const body = JSON.parse(call[1].body);
    expect(body.runId).toBe("run-xyz");
  });

  it("posts correct agentId (from adapterConfig.agentId)", async () => {
    const ctx = makePaperclipCtx({
      adapterConfig: {
        sidecarUrl: "http://localhost:8000",
        bearerToken: "tok",
        agentId: "agent42-configured-uuid",
      },
      agentId: "paperclip-agent-uuid",
    });
    await execute(ctx);

    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(call[1].body);
    expect(body.agentId).toBe("agent42-configured-uuid");
  });

  it("falls back to ctx.agent.id when adapterConfig.agentId is absent (ADAPT-04)", async () => {
    const ctx = makePaperclipCtx({
      adapterConfig: {
        sidecarUrl: "http://localhost:8000",
        bearerToken: "tok",
        // no agentId
      },
      agentId: "paperclip-fallback-id",
    });
    await execute(ctx);

    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(call[1].body);
    expect(body.agentId).toBe("paperclip-fallback-id");
  });

  it("falls back to ctx.agent.id when adapterConfig.agentId is empty string (ADAPT-04)", async () => {
    const ctx = makePaperclipCtx({
      adapterConfig: {
        sidecarUrl: "http://localhost:8000",
        bearerToken: "tok",
        agentId: "",
      },
      agentId: "paperclip-fallback-empty",
    });
    await execute(ctx);

    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(call[1].body);
    expect(body.agentId).toBe("paperclip-fallback-empty");
  });

  it("populates agentId in BOTH top-level and adapterConfig.agentId (D-14)", async () => {
    const ctx = makePaperclipCtx({
      adapterConfig: {
        sidecarUrl: "http://localhost:8000",
        bearerToken: "tok",
        agentId: "agent42-uuid",
      },
    });
    await execute(ctx);

    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(call[1].body);
    expect(body.agentId).toBe("agent42-uuid");
    expect(body.adapterConfig.agentId).toBe("agent42-uuid");
  });

  it("extracts wakeReason from ctx.context.wakeReason (ADAPT-03)", async () => {
    const ctx = makePaperclipCtx({
      context: { wakeReason: "task_assigned" },
    });
    await execute(ctx);

    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(call[1].body);
    expect(body.wakeReason).toBe("task_assigned");
  });

  it("defaults wakeReason to 'heartbeat' when ctx.context.wakeReason is absent", async () => {
    const ctx = makePaperclipCtx({ context: {} });
    await execute(ctx);

    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(call[1].body);
    expect(body.wakeReason).toBe("heartbeat");
  });

  it("logs warning to stderr for unknown wakeReason but does NOT throw (D-12)", async () => {
    const onLog = vi.fn(async (_stream: string, _chunk: string) => {});
    const ctx = makePaperclipCtx({
      context: { wakeReason: "unknown_mystery_reason" },
      onLog,
    });
    const result = await execute(ctx);

    // Should not throw — result should be successful
    expect(result.exitCode).toBe(0);
    // onLog must have been called with stderr and the unknown value
    const stderrCalls = (onLog.mock.calls as Array<[string, string]>).filter(([s]) => s === "stderr");
    expect(stderrCalls.length).toBeGreaterThan(0);
    const stderrMsg = stderrCalls.map(([, m]) => m).join("");
    expect(stderrMsg).toContain("unknown_mystery_reason");
  });

  it("passes full ctx.context dict in POST body context field", async () => {
    const ctx = makePaperclipCtx({
      context: { wakeReason: "heartbeat", taskId: "task-42", extra: true },
    });
    await execute(ctx);

    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(call[1].body);
    expect(body.context).toMatchObject({ wakeReason: "heartbeat", taskId: "task-42", extra: true });
  });

  it("returns exitCode:0, signal:null, timedOut:false on success", async () => {
    const ctx = makePaperclipCtx();
    const result = await execute(ctx);

    expect(result.exitCode).toBe(0);
    expect(result.signal).toBeNull();
    expect(result.timedOut).toBe(false);
  });

  it("returns updated sessionParams with incremented executionCount (ADAPT-05)", async () => {
    const ctx = makePaperclipCtx({
      sessionParams: { agentId: "prev-agent", executionCount: 5 },
    });
    const result = await execute(ctx);

    expect(result.sessionParams).toBeDefined();
    expect((result.sessionParams as Record<string, unknown>).executionCount).toBe(6);
  });

  it("starts executionCount at 1 when no previous session state", async () => {
    const ctx = makePaperclipCtx({ sessionParams: null });
    const result = await execute(ctx);

    expect((result.sessionParams as Record<string, unknown>).executionCount).toBe(1);
  });

  it("returns sessionDisplayId formatted as 'run:{runId}'", async () => {
    const ctx = makePaperclipCtx({ runId: "run-abc" });
    const result = await execute(ctx);

    expect(result.sessionDisplayId).toBe("run:run-abc");
  });

  it("returns summary containing runId and deduplicated status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      mockFetchResponse(202, { ...DEFAULT_EXECUTE_RESPONSE, deduplicated: true })
    ));
    const ctx = makePaperclipCtx({ runId: "run-001" });
    const result = await execute(ctx);

    expect(result.summary).toContain("run-001");
    expect(result.summary).toContain("deduplicated=true");
  });

  it("decodes existing sessionParams from ctx.runtime.sessionParams (ADAPT-05)", async () => {
    const ctx = makePaperclipCtx({
      sessionParams: { agentId: "stored-agent", lastRunId: "run-prev", executionCount: 10 },
    });
    const result = await execute(ctx);

    const newState = result.sessionParams as Record<string, unknown>;
    expect(newState.lastRunId).toBe("run-001");  // updated to current run
    expect(newState.executionCount).toBe(11);
  });

  it("sends serialized session state as adapterConfig.sessionKey in POST body (D-08)", async () => {
    const ctx = makePaperclipCtx({
      sessionParams: { agentId: "abc", executionCount: 3 },
    });
    await execute(ctx);

    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(call[1].body);
    expect(typeof body.adapterConfig.sessionKey).toBe("string");
    const parsed = JSON.parse(body.adapterConfig.sessionKey);
    expect(parsed.agentId).toBe("abc");
    expect(parsed.executionCount).toBe(3);
  });

  it("returns exitCode:1 with errorMessage on sidecar HTTP error (ADAPT-02)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      mockFetchResponse(500, { error: "internal server error" })
    ));
    const ctx = makePaperclipCtx();
    const result = await execute(ctx);

    expect(result.exitCode).toBe(1);
    expect(result.errorMessage).toBeTruthy();
    expect(typeof result.errorMessage).toBe("string");
  });

  it("returns exitCode:1 when network fetch throws", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network error")));
    const ctx = makePaperclipCtx();
    const result = await execute(ctx);

    expect(result.exitCode).toBe(1);
    expect(result.errorMessage).toContain("Network error");
  });
});

// ---------------------------------------------------------------------------
// testEnvironment()
// ---------------------------------------------------------------------------

describe("testEnvironment", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function makeTestCtx(config: Record<string, unknown> = {}): AdapterEnvironmentTestContext {
    return {
      companyId: "company-001",
      adapterType: "agent42_local",
      config: {
        sidecarUrl: "http://localhost:8000",
        bearerToken: "test-token",
        agentId: "agent42-uuid",
        ...config,
      },
    } as unknown as AdapterEnvironmentTestContext;
  }

  it("returns status:'pass' when health check succeeds (ADAPT-01)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      mockFetchResponse(200, DEFAULT_HEALTH_RESPONSE)
    ));
    const ctx = makeTestCtx();
    const result = await testEnvironment(ctx);

    expect(result.status).toBe("pass");
    expect(result.adapterType).toBe("agent42_local");
    expect(typeof result.testedAt).toBe("string");
  });

  it("returns structured checks array with sidecar_reachable info on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      mockFetchResponse(200, DEFAULT_HEALTH_RESPONSE)
    ));
    const ctx = makeTestCtx();
    const result = await testEnvironment(ctx);

    const reachableCheck = result.checks.find((c) => c.code === "sidecar_reachable");
    expect(reachableCheck).toBeDefined();
    expect(reachableCheck!.level).toBe("info");
  });

  it("returns status:'fail' with error check when sidecarUrl is missing", async () => {
    const ctx: AdapterEnvironmentTestContext = {
      companyId: "company-001",
      adapterType: "agent42_local",
      config: {},  // no sidecarUrl
    } as unknown as AdapterEnvironmentTestContext;

    const result = await testEnvironment(ctx);

    expect(result.status).toBe("fail");
    const urlCheck = result.checks.find((c) => c.code === "missing_sidecar_url");
    expect(urlCheck).toBeDefined();
    expect(urlCheck!.level).toBe("error");
  });

  it("returns status:'fail' with sidecar_unreachable check when health endpoint throws", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));
    const ctx = makeTestCtx();
    const result = await testEnvironment(ctx);

    expect(result.status).toBe("fail");
    const unreachableCheck = result.checks.find((c) => c.code === "sidecar_unreachable");
    expect(unreachableCheck).toBeDefined();
    expect(unreachableCheck!.level).toBe("error");
  });

  it("returns status:'fail' when health endpoint returns non-ok status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      mockFetchResponse(503, { error: "Service Unavailable" })
    ));
    const ctx = makeTestCtx();
    const result = await testEnvironment(ctx);

    expect(result.status).toBe("fail");
  });

  it("includes testedAt as ISO timestamp", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      mockFetchResponse(200, DEFAULT_HEALTH_RESPONSE)
    ));
    const ctx = makeTestCtx();
    const result = await testEnvironment(ctx);

    expect(new Date(result.testedAt).getTime()).not.toBeNaN();
  });
});

// ---------------------------------------------------------------------------
// default export (index.ts)
// ---------------------------------------------------------------------------

describe("default export", () => {
  it("has type 'agent42_local'", () => {
    expect(adapter.type).toBe("agent42_local");
  });

  it("has execute as a function", () => {
    expect(typeof adapter.execute).toBe("function");
  });

  it("has testEnvironment as a function", () => {
    expect(typeof adapter.testEnvironment).toBe("function");
  });

  it("has sessionCodec with serialize, deserialize, getDisplayId", () => {
    expect(adapter.sessionCodec).toBeDefined();
    expect(typeof adapter.sessionCodec!.serialize).toBe("function");
    expect(typeof adapter.sessionCodec!.deserialize).toBe("function");
    expect(typeof adapter.sessionCodec!.getDisplayId).toBe("function");
  });
});
