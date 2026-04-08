/**
 * index.ts — Default export: ServerAdapterModule for the Agent42 Paperclip adapter.
 *
 * This is the entry point that Paperclip discovers and loads.
 * The type "agent42_local" identifies this adapter in Paperclip's adapter registry.
 *
 * Usage:
 *   Paperclip loads this module, reads `type` to match configured adapters,
 *   then calls execute() for each heartbeat and testEnvironment() during setup.
 *
 * ESM-only: all local imports use .js extensions (NodeNext module resolution).
 */

import type { ServerAdapterModule } from "@paperclipai/adapter-utils";
import { execute, testEnvironment } from "./adapter.js";
import { sessionCodec } from "./session.js";

const adapter: ServerAdapterModule = {
  type: "agent42_local",
  execute,
  testEnvironment,
  sessionCodec,
};

export default adapter;
