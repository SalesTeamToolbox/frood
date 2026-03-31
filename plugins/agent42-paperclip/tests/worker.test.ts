import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createTestHarness } from "@paperclipai/plugin-sdk/testing";
import type { ToolResult } from "@paperclipai/plugin-sdk";
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

const healthyResponse = {
  status: "ok",
  memory: { available: true },
  providers: { available: true },
  qdrant: { available: true },
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Plugin Worker Lifecycle", () => {
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockFetch = vi.fn().mockResolvedValue(makeMockResponse(200, healthyResponse));
    vi.stubGlobal("fetch", mockFetch);
  });

  afterEach(async () => {
    await plugin.definition.onShutdown?.();
    vi.unstubAllGlobals();
  });

  it("setup() creates client from config", async () => {
    const harness = createTestHarness({
      manifest: manifest as any,
      config: {
        agent42BaseUrl: "http://localhost:8001",
        apiKey: "test-token",
        timeoutMs: 5000,
      },
    });

    await expect(plugin.definition.setup(harness.ctx)).resolves.not.toThrow();
  });

  it("setup() throws when agent42BaseUrl missing", async () => {
    const harness = createTestHarness({
      manifest: manifest as any,
      config: { agent42BaseUrl: "", apiKey: "test-token" },
    });

    await expect(plugin.definition.setup(harness.ctx)).rejects.toThrow(
      "agent42BaseUrl and apiKey are required"
    );
  });

  it("setup() throws when apiKey missing", async () => {
    const harness = createTestHarness({
      manifest: manifest as any,
      config: { agent42BaseUrl: "http://localhost:8001", apiKey: "" },
    });

    await expect(plugin.definition.setup(harness.ctx)).rejects.toThrow(
      "agent42BaseUrl and apiKey are required"
    );
  });

  it("setup() uses default timeoutMs when not provided", async () => {
    const harness = createTestHarness({
      manifest: manifest as any,
      config: {
        agent42BaseUrl: "http://localhost:8001",
        apiKey: "test-token",
      },
    });

    await expect(plugin.definition.setup(harness.ctx)).resolves.not.toThrow();
  });

  it("onHealth() returns ok when sidecar healthy", async () => {
    const harness = createTestHarness({
      manifest: manifest as any,
      config: {
        agent42BaseUrl: "http://localhost:8001",
        apiKey: "test-token",
      },
    });

    await plugin.definition.setup(harness.ctx);
    const health = await plugin.definition.onHealth!();
    expect(health.status).toBe("ok");
  });

  it("onHealth() returns error when sidecar unreachable", async () => {
    const harness = createTestHarness({
      manifest: manifest as any,
      config: {
        agent42BaseUrl: "http://localhost:8001",
        apiKey: "test-token",
      },
    });

    await plugin.definition.setup(harness.ctx);

    // Now make fetch fail
    mockFetch.mockRejectedValue(new Error("Connection refused"));

    const health = await plugin.definition.onHealth!();
    expect(health.status).toBe("error");
    expect(health.message).toContain("Connection refused");
  });

  it("onHealth() returns error when client not initialized", async () => {
    // Don't call setup — client is null
    const health = await plugin.definition.onHealth!();
    expect(health.status).toBe("error");
    expect(health.message).toContain("not initialized");
  });

  it("onShutdown() nulls client so onHealth returns error", async () => {
    const harness = createTestHarness({
      manifest: manifest as any,
      config: {
        agent42BaseUrl: "http://localhost:8001",
        apiKey: "test-token",
      },
    });

    await plugin.definition.setup(harness.ctx);
    await plugin.definition.onShutdown!();

    const health = await plugin.definition.onHealth!();
    expect(health.status).toBe("error");
    expect(health.message).toContain("not initialized");
  });
});
