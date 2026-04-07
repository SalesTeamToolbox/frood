/**
 * worker.ts -- Plugin lifecycle: setup, onHealth, onShutdown.
 *
 * CRITICAL: Config is accessed via ctx.config.get() inside setup(),
 * NOT via a separate initialize() export (Pitfall 1).
 * CRITICAL: Lifecycle hook is onHealth() not health() (Pitfall 2).
 */
import { definePlugin, runWorker } from "@paperclipai/plugin-sdk";
import type { PluginContext } from "@paperclipai/plugin-sdk";
import { Agent42Client } from "./client.js";
import { registerTools } from "./tools.js";

let client: Agent42Client | null = null;

// Terminal session tracking (Phase 36) — maps sessionId to WebSocket
const terminalSessions = new Map<string, WebSocket>();

const plugin = definePlugin({
  async setup(ctx: PluginContext) {
    const config = await ctx.config.get();

    // Validate required fields (D-19)
    const baseUrl = config.agent42BaseUrl as string;
    const apiKey = config.apiKey as string;
    if (!baseUrl || !apiKey) {
      throw new Error("agent42BaseUrl and apiKey are required in plugin config");
    }
    const timeoutMs = (config.timeoutMs as number) ?? 10_000;

    client = new Agent42Client(baseUrl, apiKey, timeoutMs);

    // Register all tools synchronously before setup() resolves (Pitfall 6)
    registerTools(ctx, client);

    // Register agent.run.started event for auto-memory observability (ADV-01, D-13)
    ctx.events.on("agent.run.started", async (event) => {
      ctx.logger.info("Agent run started — auto-memory active", {
        agentId: event.entityId,
        companyId: event.companyId,
      });
    });

    // Register UI data handlers (D-16) — one per UI panel
    ctx.data.register("agent-profile", async (params) => {
      const agentId = params?.agentId as string | undefined;
      if (!agentId || !client) return null;
      try {
        return await client.getAgentProfile(agentId);
      } catch (e) {
        ctx.logger.warn("agent-profile data handler failed", { error: String(e) });
        return null;
      }
    });

    ctx.data.register("provider-health", async (_params) => {
      if (!client) return null;
      try {
        return await client.health();
      } catch (e) {
        ctx.logger.warn("provider-health data handler failed", { error: String(e) });
        return null;
      }
    });

    ctx.data.register("available-models", async (_params) => {
      if (!client) return null;
      try {
        return await client.getModels();
      } catch (e) {
        ctx.logger.warn("available-models data handler failed", { error: String(e) });
        return null;
      }
    });

    ctx.data.register("memory-run-trace", async (params) => {
      const runId = params?.runId as string | undefined;
      if (!runId || !client) return null;
      try {
        return await client.getMemoryRunTrace(runId);
      } catch (e) {
        ctx.logger.warn("memory-run-trace data handler failed", { error: String(e) });
        return null;
      }
    });

    ctx.data.register("routing-decisions", async (params) => {
      const agentId = params?.agentId as string | undefined;
      const hours = (params?.hours as number) ?? 24;
      if (!client) return null;
      try {
        return await client.getAgentSpend(agentId ?? "", hours);
      } catch (e) {
        ctx.logger.warn("routing-decisions data handler failed", { error: String(e) });
        return null;
      }
    });

    ctx.data.register("agent-effectiveness", async (params) => {
      const agentId = params?.agentId as string | undefined;
      if (!agentId || !client) return null;
      try {
        return await client.getAgentEffectiveness(agentId);
      } catch (e) {
        ctx.logger.warn("agent-effectiveness data handler failed", { error: String(e) });
        return null;
      }
    });

    // -- Phase 36: Data handlers for Paperclip integration --

    ctx.data.register("tools-skills", async (_params) => {
      if (!client) return null;
      try {
        const [toolsRes, skillsRes] = await Promise.all([
          client.getTools(),
          client.getSkills(),
        ]);
        return { tools: toolsRes.tools, skills: skillsRes.skills };
      } catch (e) {
        ctx.logger.warn("tools-skills data handler failed", { error: String(e) });
        return null;
      }
    });

    ctx.data.register("apps-list", async (_params) => {
      if (!client) return null;
      try {
        return await client.getApps();
      } catch (e) {
        ctx.logger.warn("apps-list data handler failed", { error: String(e) });
        return null;
      }
    });

    ctx.data.register("agent42-settings", async (_params) => {
      if (!client) return null;
      try {
        return await client.getSettings();
      } catch (e) {
        ctx.logger.warn("agent42-settings data handler failed", { error: String(e) });
        return null;
      }
    });

    ctx.data.register("memory-stats", async (_params) => {
      if (!client) return null;
      try {
        return await client.getMemoryStats();
      } catch (e) {
        ctx.logger.warn("memory-stats data handler failed", { error: String(e) });
        return null;
      }
    });

    ctx.data.register("storage-status", async (_params) => {
      if (!client) return null;
      try {
        return await client.getStorageStatus();
      } catch (e) {
        ctx.logger.warn("storage-status data handler failed", { error: String(e) });
        return null;
      }
    });

    // -- Phase 36: Action handlers --

    ctx.actions.register("app-start", async (params) => {
      const appId = params?.appId as string;
      if (!appId || !client) return { ok: false, message: "Missing appId or client" };
      try {
        return await client.startApp(appId);
      } catch (e) {
        ctx.logger.warn("app-start action failed", { error: String(e) });
        return { ok: false, message: String(e) };
      }
    });

    ctx.actions.register("app-stop", async (params) => {
      const appId = params?.appId as string;
      if (!appId || !client) return { ok: false, message: "Missing appId or client" };
      try {
        return await client.stopApp(appId);
      } catch (e) {
        ctx.logger.warn("app-stop action failed", { error: String(e) });
        return { ok: false, message: String(e) };
      }
    });

    ctx.actions.register("update-agent42-settings", async (params) => {
      const keyName = params?.key_name as string;
      const value = params?.value as string;
      if (!keyName || !client) return { ok: false, message: "Missing key_name or client" };
      try {
        return await client.updateSettings({ key_name: keyName, value: value ?? "" });
      } catch (e) {
        ctx.logger.warn("update-agent42-settings action failed", { error: String(e) });
        return { ok: false, message: String(e) };
      }
    });

    ctx.actions.register("toggle-tool", async (params) => {
      const name = params?.name as string;
      const enabled = params?.enabled as boolean;
      if (!name || enabled === undefined || !client) return { ok: false, message: "Missing name/enabled or client" };
      try {
        return await client.toggleTool(name, enabled);
      } catch (e) {
        ctx.logger.warn("toggle-tool action failed", { error: String(e) });
        return { ok: false, message: String(e) };
      }
    });

    ctx.actions.register("toggle-skill", async (params) => {
      const name = params?.name as string;
      const enabled = params?.enabled as boolean;
      if (!name || enabled === undefined || !client) return { ok: false, message: "Missing name/enabled or client" };
      try {
        return await client.toggleSkill(name, enabled);
      } catch (e) {
        ctx.logger.warn("toggle-skill action failed", { error: String(e) });
        return { ok: false, message: String(e) };
      }
    });

    ctx.actions.register("purge-memory", async (params) => {
      const collection = params?.collection as string;
      if (!collection || !client) return { ok: false, message: "Missing collection or client" };
      try {
        return await client.purgeMemory(collection);
      } catch (e) {
        ctx.logger.warn("purge-memory action failed", { error: String(e) });
        return { ok: false, message: String(e) };
      }
    });

    // -- Phase 36: Terminal stream and action handlers (PAPERCLIP-01) --
    // Per D-01: Terminal communicates with Agent42 sidecar via WebSocket for real-time interaction
    // Per D-12: Real-time updates via WebSocket connections

    ctx.actions.register("terminal-start", async (params) => {
      const sessionId = (params?.sessionId as string) ?? crypto.randomUUID();
      if (!client) return { ok: false, sessionId, message: "Client not initialized" };

      try {
        const config = await ctx.config.get();
        const httpBaseUrl = config.agent42BaseUrl as string;
        const apiKey = config.apiKey as string;

        // Per CLAUDE.md rule 6: NEVER log/expose API keys in URLs or server logs.
        // Request a short-lived session token via authenticated REST endpoint,
        // then open WebSocket with that token (short-lived, not the API key).
        const tokenResp = await fetch(`${httpBaseUrl}/ws/terminal-token`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Authorization": `Bearer ${apiKey}` },
        });
        if (!tokenResp.ok) throw new Error(`Terminal token request failed: HTTP ${tokenResp.status}`);
        const { token: wsToken } = (await tokenResp.json()) as { token: string };

        const wsBaseUrl = httpBaseUrl.replace(/^http/, "ws");
        const wsUrl = `${wsBaseUrl}/ws/terminal?session=${encodeURIComponent(wsToken)}`;

        const ws = new WebSocket(wsUrl);
        terminalSessions.set(sessionId, ws);

        ws.onmessage = (event) => {
          ctx.streams.emit("terminal-output", {
            sessionId,
            text: typeof event.data === "string" ? event.data : "",
            ts: Date.now(),
          });
        };

        ws.onerror = (err) => {
          ctx.logger.warn("Terminal WebSocket error", { sessionId, error: String(err) });
          ctx.streams.emit("terminal-output", {
            sessionId,
            text: "\r\n[Terminal connection error]\r\n",
            ts: Date.now(),
          });
        };

        ws.onclose = () => {
          terminalSessions.delete(sessionId);
          ctx.streams.emit("terminal-output", {
            sessionId,
            text: "\r\n[Terminal session closed]\r\n",
            ts: Date.now(),
          });
        };

        return { ok: true, sessionId };
      } catch (e) {
        ctx.logger.warn("terminal-start failed", { error: String(e) });
        return { ok: false, sessionId, message: String(e) };
      }
    });

    ctx.actions.register("terminal-input", async (params) => {
      const sessionId = params?.sessionId as string;
      const data = params?.data as string;
      if (!sessionId || !data) return { ok: false };
      const ws = terminalSessions.get(sessionId);
      if (!ws || ws.readyState !== WebSocket.OPEN) return { ok: false, message: "No active session" };
      ws.send(data);
      return { ok: true };
    });

    // Per research Pitfall 4: Explicit cleanup to prevent PTY resource leaks
    ctx.actions.register("terminal-close", async (params) => {
      const sessionId = params?.sessionId as string;
      if (!sessionId) return { ok: false };
      const ws = terminalSessions.get(sessionId);
      if (ws) {
        ws.close();
        terminalSessions.delete(sessionId);
      }
      return { ok: true };
    });

    // -- Phase 41: Agent42 Adapter actions (ABACUS-04, ABACUS-05) --
    // These replace claude_local for Paperclip autonomous execution.
    // All agent tasks route through Agent42 -> Abacus RouteLLM API.
    // Zero Claude CLI processes spawned. TOS compliant.

    ctx.actions.register("adapter-run", async (params) => {
      const task = params?.task as string;
      const agentId = params?.agentId as string;
      if (!task || !agentId || !client) {
        return { ok: false, message: "Missing task, agentId, or client not initialized" };
      }
      try {
        const result = await client.adapterRun({
          task,
          agentId,
          role: params?.role as string | undefined,
          provider: params?.provider as string | undefined,
          model: params?.model as string | undefined,
          tools: params?.tools as string[] | undefined,
          maxIterations: params?.maxIterations as number | undefined,
        });
        return { ok: true, ...result };
      } catch (e) {
        ctx.logger.warn("adapter-run failed", { error: String(e) });
        return { ok: false, message: String(e) };
      }
    });

    ctx.actions.register("adapter-status", async (params) => {
      const runId = params?.runId as string;
      if (!runId || !client) {
        return { ok: false, message: "Missing runId or client not initialized" };
      }
      try {
        const result = await client.adapterStatus(runId);
        return { ok: true, ...result };
      } catch (e) {
        ctx.logger.warn("adapter-status failed", { error: String(e) });
        return { ok: false, message: String(e) };
      }
    });

    ctx.actions.register("adapter-cancel", async (params) => {
      const runId = params?.runId as string;
      if (!runId || !client) {
        return { ok: false, message: "Missing runId or client not initialized" };
      }
      try {
        const result = await client.adapterCancel(runId);
        return { ok: true, ...result };
      } catch (e) {
        ctx.logger.warn("adapter-cancel failed", { error: String(e) });
        return { ok: false, message: String(e) };
      }
    });

    // Register learning extraction job handler (D-17, D-19, D-20)
    ctx.jobs.register("extract-learnings", async (_job) => {
      if (!client) {
        ctx.logger.warn("extract-learnings: client not initialized — skipping");
        return;
      }

      // Read watermark to avoid re-processing (D-20)
      let sinceTs: string | null = null;
      try {
        const lastLearnAt = await ctx.state.get({
          scopeKind: "instance",
          stateKey: "last-learn-at",
        });
        sinceTs = (lastLearnAt as string) ?? null;
      } catch {
        // First run — no watermark yet
      }

      try {
        const result = await client.extractLearnings({
          sinceTs,
          batchSize: 20,
        });
        ctx.logger.info("extract-learnings completed", {
          extracted: result.extracted,
          skipped: result.skipped,
        });
      } catch (e) {
        ctx.logger.error("extract-learnings job failed", { error: String(e) });
        return; // Don't update watermark on failure
      }

      // Update watermark (D-20)
      try {
        await ctx.state.set(
          { scopeKind: "instance", stateKey: "last-learn-at" },
          new Date().toISOString(),
        );
      } catch (e) {
        ctx.logger.warn("Failed to update learn watermark", { error: String(e) });
      }
    });

    ctx.logger.info("Agent42 plugin ready", { baseUrl });
  },

  async onHealth() {
    if (!client) {
      return { status: "error" as const, message: "Client not initialized" };
    }
    try {
      const h = await client.health();
      return {
        status: (h.status === "ok" ? "ok" : "degraded") as "ok" | "degraded",
        details: h as unknown as Record<string, unknown>,
      };
    } catch (e) {
      return { status: "error" as const, message: String(e) };
    }
  },

  async onShutdown() {
    client?.destroy();
    client = null;
  },
});

export default plugin;
runWorker(plugin, import.meta.url);
