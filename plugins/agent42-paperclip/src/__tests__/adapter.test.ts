/**
 * Tests for Agent42 adapter (Phase 41 — ABACUS-04, ABACUS-05).
 * Verifies adapter-run, adapter-status, adapter-cancel action handlers
 * and client methods work correctly.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

// Test the manifest declares agent42_sidecar adapter
describe("manifest", () => {
  it("declares agent42_sidecar adapter", async () => {
    const { default: manifest } = await import("../manifest.js");
    const adapters = (manifest as any).adapters;
    expect(adapters).toBeDefined();
    expect(adapters.length).toBeGreaterThanOrEqual(1);
    const sidecar = adapters.find((a: any) => a.id === "agent42_sidecar");
    expect(sidecar).toBeDefined();
    expect(sidecar.actions.run).toBe("adapter-run");
    expect(sidecar.actions.status).toBe("adapter-status");
    expect(sidecar.actions.cancel).toBe("adapter-cancel");
  });

  it("has adapters.register capability", async () => {
    const { default: manifest } = await import("../manifest.js");
    expect(manifest.capabilities).toContain("adapters.register" as any);
  });
});

// Test client adapter methods construct correct requests
describe("Agent42Client adapter methods", () => {
  const mockFetch = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch);
    mockFetch.mockReset();
  });

  it("adapterRun sends POST to /adapter/run", async () => {
    const { Agent42Client } = await import("../client.js");
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ runId: "run-1", status: "started", provider: "abacus", model: "gemini-3-flash" }),
    });

    const client = new Agent42Client("http://localhost:8001", "test-token");
    const result = await client.adapterRun({
      task: "analyze data",
      agentId: "agent-1",
      role: "analyst",
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8001/adapter/run",
      expect.objectContaining({ method: "POST" }),
    );
    expect(result.runId).toBe("run-1");
    expect(result.provider).toBe("abacus");
  });

  it("adapterStatus sends GET to /adapter/status/{runId}", async () => {
    const { Agent42Client } = await import("../client.js");
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ runId: "run-1", status: "completed", output: "done" }),
    });

    const client = new Agent42Client("http://localhost:8001", "test-token");
    const result = await client.adapterStatus("run-1");

    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8001/adapter/status/run-1",
      expect.objectContaining({ method: "GET" }),
    );
    expect(result.status).toBe("completed");
  });

  it("adapterCancel sends POST to /adapter/cancel/{runId}", async () => {
    const { Agent42Client } = await import("../client.js");
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ runId: "run-1", cancelled: true }),
    });

    const client = new Agent42Client("http://localhost:8001", "test-token");
    const result = await client.adapterCancel("run-1");

    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8001/adapter/cancel/run-1",
      expect.objectContaining({ method: "POST" }),
    );
    expect(result.cancelled).toBe(true);
  });

  it("adapterRun throws on non-ok response", async () => {
    const { Agent42Client } = await import("../client.js");
    mockFetch.mockResolvedValue({ ok: false, status: 500 });

    const client = new Agent42Client("http://localhost:8001", "test-token");
    await expect(client.adapterRun({ task: "test", agentId: "a1" })).rejects.toThrow("HTTP 500");
  });

  it("adapterStatus throws on non-ok response", async () => {
    const { Agent42Client } = await import("../client.js");
    mockFetch.mockResolvedValue({ ok: false, status: 404 });

    const client = new Agent42Client("http://localhost:8001", "test-token");
    await expect(client.adapterStatus("missing-run")).rejects.toThrow("HTTP 404");
  });

  it("adapterCancel throws on non-ok response", async () => {
    const { Agent42Client } = await import("../client.js");
    mockFetch.mockResolvedValue({ ok: false, status: 403 });

    const client = new Agent42Client("http://localhost:8001", "test-token");
    await expect(client.adapterCancel("run-2")).rejects.toThrow("HTTP 403");
  });
});

// Test worker registers adapter action handlers
describe("Phase 41: Worker adapter action handlers", () => {
  it("registers adapter-run action handler", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve, dirname } = await import("node:path");
    const { fileURLToPath } = await import("node:url");
    const __dirname = dirname(fileURLToPath(import.meta.url));
    const workerSource = readFileSync(resolve(__dirname, "../worker.ts"), "utf-8");
    expect(workerSource).toContain('ctx.actions.register("adapter-run"');
  });

  it("registers adapter-status action handler", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve, dirname } = await import("node:path");
    const { fileURLToPath } = await import("node:url");
    const __dirname = dirname(fileURLToPath(import.meta.url));
    const workerSource = readFileSync(resolve(__dirname, "../worker.ts"), "utf-8");
    expect(workerSource).toContain('ctx.actions.register("adapter-status"');
  });

  it("registers adapter-cancel action handler", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve, dirname } = await import("node:path");
    const { fileURLToPath } = await import("node:url");
    const __dirname = dirname(fileURLToPath(import.meta.url));
    const workerSource = readFileSync(resolve(__dirname, "../worker.ts"), "utf-8");
    expect(workerSource).toContain('ctx.actions.register("adapter-cancel"');
  });

  it("calls client.adapterRun() in adapter-run handler", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve, dirname } = await import("node:path");
    const { fileURLToPath } = await import("node:url");
    const __dirname = dirname(fileURLToPath(import.meta.url));
    const workerSource = readFileSync(resolve(__dirname, "../worker.ts"), "utf-8");
    expect(workerSource).toContain("client.adapterRun(");
  });

  it("calls client.adapterStatus() in adapter-status handler", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve, dirname } = await import("node:path");
    const { fileURLToPath } = await import("node:url");
    const __dirname = dirname(fileURLToPath(import.meta.url));
    const workerSource = readFileSync(resolve(__dirname, "../worker.ts"), "utf-8");
    expect(workerSource).toContain("client.adapterStatus(");
  });

  it("calls client.adapterCancel() in adapter-cancel handler", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve, dirname } = await import("node:path");
    const { fileURLToPath } = await import("node:url");
    const __dirname = dirname(fileURLToPath(import.meta.url));
    const workerSource = readFileSync(resolve(__dirname, "../worker.ts"), "utf-8");
    expect(workerSource).toContain("client.adapterCancel(");
  });
});

// Test TOS compliance: verify adapter description mentions no CLI spawning
describe("TOS compliance (ABACUS-05)", () => {
  it("adapter description states zero Claude CLI processes", async () => {
    const { default: manifest } = await import("../manifest.js");
    const sidecar = (manifest as any).adapters.find((a: any) => a.id === "agent42_sidecar");
    expect(sidecar.description).toContain("zero Claude CLI");
    expect(sidecar.description).toContain("TOS compliant");
  });

  it("worker does not import or call claude_local functions", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve, dirname } = await import("node:path");
    const { fileURLToPath } = await import("node:url");
    const __dirname = dirname(fileURLToPath(import.meta.url));
    const workerSource = readFileSync(resolve(__dirname, "../worker.ts"), "utf-8");
    // Only comments (starting with //) may reference claude_local as context — no actual code calls
    const codeLines = workerSource
      .split("\n")
      .filter((line: string) => !line.trimStart().startsWith("//"))
      .join("\n");
    expect(codeLines).not.toContain("claude_local");
  });
});
