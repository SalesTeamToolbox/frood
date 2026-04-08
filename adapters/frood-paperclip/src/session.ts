/**
 * session.ts — AdapterSessionCodec implementation for the Agent42 Paperclip adapter.
 *
 * Design notes (per Research Pattern 4, correcting D-08):
 *   - The AdapterSessionCodec interface uses serialize/deserialize (NOT encode/decode)
 *   - Session state is Record<string, unknown> — Paperclip stores the serialized Record directly
 *   - serialize/deserialize are near-identity: Paperclip handles its own storage serialization
 *   - Spreading in both directions preserves unknown fields (D-10 forward-compatibility)
 *   - deserialize performs defensive type-checking: rejects null/undefined/arrays/primitives
 */

import type { AdapterSessionCodec } from "@paperclipai/adapter-utils";

export const sessionCodec: AdapterSessionCodec = {
  /**
   * serialize — converts session state Record to storable form.
   *
   * Returns null for null input.
   * Returns a shallow copy of params, preserving all fields including unknown ones (D-10).
   */
  serialize(params: Record<string, unknown> | null): Record<string, unknown> | null {
    if (!params) return null;
    return { ...params };
  },

  /**
   * deserialize — parses raw session storage value into a typed Record.
   *
   * Returns null for null, undefined, non-objects, and arrays.
   * Returns a shallow copy of the raw object, preserving all fields (D-10).
   */
  deserialize(raw: unknown): Record<string, unknown> | null {
    if (raw == null || typeof raw !== "object" || Array.isArray(raw)) return null;
    return { ...(raw as Record<string, unknown>) };
  },

  /**
   * getDisplayId — returns a human-readable session identifier.
   *
   * Returns "agent42:{agentId}" when agentId is a string, null otherwise.
   */
  getDisplayId(params: Record<string, unknown> | null): string | null {
    if (!params?.agentId || typeof params.agentId !== "string") return null;
    return `agent42:${params.agentId}`;
  },
};
