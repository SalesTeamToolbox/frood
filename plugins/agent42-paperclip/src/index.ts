/**
 * index.ts -- Package entry point.
 * Re-exports the plugin manifest and worker for Paperclip plugin loading.
 */
export { default as manifest } from "./manifest.js";
export { default as worker } from "./worker.js";
export type { Agent42Client } from "./client.js";
