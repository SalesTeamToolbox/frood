import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createTestHarness } from "@paperclipai/plugin-sdk/testing";
import type { ToolResult } from "@paperclipai/plugin-sdk";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import manifest from "../dist/manifest.js";
import plugin from "../src/worker.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

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

  it("setup() registers agent-profile data handler", async () => {
    const harness = createTestHarness({
      manifest: manifest as any,
      config: {
        agent42BaseUrl: "http://localhost:8001",
        apiKey: "test-token",
      },
    });

    await plugin.definition.setup(harness.ctx);

    // agent-profile returns null when agentId is missing — just verify handler is registered
    const result = await harness.getData("agent-profile", {});
    expect(result).toBeNull();
  });

  it("setup() registers extract-learnings job handler", async () => {
    const harness = createTestHarness({
      manifest: manifest as any,
      config: {
        agent42BaseUrl: "http://localhost:8001",
        apiKey: "test-token",
      },
    });

    await plugin.definition.setup(harness.ctx);

    // Mock extractLearnings POST /memory/extract
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ extracted: 2, skipped: 0 }),
    } as unknown as Response);

    // Should complete without throwing
    await expect(harness.runJob("extract-learnings")).resolves.not.toThrow();
  });

  it("manifest includes agents.invoke, events.subscribe, plugin.state.read capabilities", () => {
    // Use dist/manifest.js (manifest.json was replaced by manifest.ts in Phase 36-01)
    expect(manifest.capabilities).toContain("agents.invoke");
    expect(manifest.capabilities).toContain("events.subscribe");
    expect(manifest.capabilities).toContain("plugin.state.read");
  });
});
