import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

const workerSource = readFileSync(resolve(__dirname, "../worker.ts"), "utf-8");

describe("Phase 36: Worker data handlers", () => {
  it("registers tools-skills data handler", () => {
    expect(workerSource).toContain('ctx.data.register("tools-skills"');
  });

  it("registers apps-list data handler", () => {
    expect(workerSource).toContain('ctx.data.register("apps-list"');
  });

  it("registers agent42-settings data handler", () => {
    expect(workerSource).toContain('ctx.data.register("agent42-settings"');
  });

  it("calls client.getTools() in tools-skills handler", () => {
    expect(workerSource).toContain("client.getTools()");
  });

  it("calls client.getSkills() in tools-skills handler", () => {
    expect(workerSource).toContain("client.getSkills()");
  });

  it("calls client.getApps() in apps-list handler", () => {
    expect(workerSource).toContain("client.getApps()");
  });

  it("calls client.getSettings() in agent42-settings handler", () => {
    expect(workerSource).toContain("client.getSettings()");
  });
});

describe("Phase 36: Worker action handlers", () => {
  it("registers app-start action handler", () => {
    expect(workerSource).toContain('ctx.actions.register("app-start"');
  });

  it("registers app-stop action handler", () => {
    expect(workerSource).toContain('ctx.actions.register("app-stop"');
  });

  it("registers update-agent42-settings action handler", () => {
    expect(workerSource).toContain('ctx.actions.register("update-agent42-settings"');
  });

  it("registers terminal-start action handler", () => {
    expect(workerSource).toContain('ctx.actions.register("terminal-start"');
  });

  it("registers terminal-input action handler", () => {
    expect(workerSource).toContain('ctx.actions.register("terminal-input"');
  });

  it("registers terminal-close action handler (Pitfall 4 prevention)", () => {
    expect(workerSource).toContain('ctx.actions.register("terminal-close"');
  });
});

describe("Phase 36: Worker terminal stream", () => {
  it("emits terminal-output stream events", () => {
    expect(workerSource).toContain('ctx.streams.emit("terminal-output"');
  });

  it("tracks terminal sessions in a Map", () => {
    expect(workerSource).toContain("terminalSessions");
    expect(workerSource).toMatch(/new Map/);
  });

  it("uses short-lived session token for terminal WebSocket auth (CLAUDE.md rule 6)", () => {
    // Verify the implementation uses /ws/terminal-token (POST) rather than exposing API key
    expect(workerSource).toContain("/ws/terminal-token");
    expect(workerSource).toContain("wsToken");
  });

  it("cleans up session on WebSocket close", () => {
    expect(workerSource).toContain("terminalSessions.delete(sessionId)");
  });
});
