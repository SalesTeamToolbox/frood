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
