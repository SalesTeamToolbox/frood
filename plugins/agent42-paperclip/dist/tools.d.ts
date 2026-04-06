/**
 * tools.ts -- Register all 5 agent tools via ctx.tools.register().
 *
 * All tool handlers auto-inject agentId and companyId from runCtx (D-11).
 * Tool input schemas use camelCase field names (D-10).
 * Response shapes are simplified for agent consumption (D-16).
 */
import type { PluginContext } from "@paperclipai/plugin-sdk";
import type { Agent42Client } from "./client.js";
export declare function registerTools(ctx: PluginContext, client: Agent42Client): void;
