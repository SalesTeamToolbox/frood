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
