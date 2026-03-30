/**
 * session.test.ts — Tests for the AdapterSessionCodec implementation.
 *
 * Tests cover:
 *   - serialize: null handling, identity for valid Records
 *   - deserialize: null/undefined/non-object safety, valid Records, forward-compatibility
 *   - getDisplayId: null handling, agentId prefix, missing agentId
 *   - round-trip: serialize -> deserialize produces deep-equal original
 */

import { describe, it, expect } from "vitest";
import { sessionCodec } from "../src/session.js";

describe("sessionCodec", () => {
  // ---------------------------------------------------------------------------
  // serialize
  // ---------------------------------------------------------------------------
  describe("serialize", () => {
    it("returns null when params is null", () => {
      expect(sessionCodec.serialize(null)).toBeNull();
    });

    it("returns the same Record shape for valid params", () => {
      const state = { agentId: "abc", lastRunId: "run1", executionCount: 3 };
      const result = sessionCodec.serialize(state);
      expect(result).toEqual({ agentId: "abc", lastRunId: "run1", executionCount: 3 });
    });

    it("preserves unknown/future fields (forward-compatibility)", () => {
      const state = { agentId: "abc", futureField: 42, nested: { x: 1 } };
      const result = sessionCodec.serialize(state);
      expect(result).toEqual({ agentId: "abc", futureField: 42, nested: { x: 1 } });
    });

    it("returns a copy (not the same reference)", () => {
      const state = { agentId: "abc" };
      const result = sessionCodec.serialize(state);
      expect(result).not.toBe(state);
    });
  });

  // ---------------------------------------------------------------------------
  // deserialize
  // ---------------------------------------------------------------------------
  describe("deserialize", () => {
    it("returns null when raw is null", () => {
      expect(sessionCodec.deserialize(null)).toBeNull();
    });

    it("returns null when raw is undefined", () => {
      expect(sessionCodec.deserialize(undefined)).toBeNull();
    });

    it("returns null when raw is a string", () => {
      expect(sessionCodec.deserialize("not-an-object")).toBeNull();
    });

    it("returns null when raw is a number", () => {
      expect(sessionCodec.deserialize(42)).toBeNull();
    });

    it("returns null when raw is an array", () => {
      expect(sessionCodec.deserialize(["a", "b"])).toBeNull();
    });

    it("returns the same Record shape for valid input", () => {
      const raw = { agentId: "abc", lastRunId: "run1", executionCount: 3 };
      const result = sessionCodec.deserialize(raw);
      expect(result).toEqual({ agentId: "abc", lastRunId: "run1", executionCount: 3 });
    });

    it("preserves unknown fields (D-10 forward-compatibility)", () => {
      const raw = { agentId: "abc", futureField: 42 };
      const result = sessionCodec.deserialize(raw);
      expect(result).toEqual({ agentId: "abc", futureField: 42 });
    });

    it("returns a copy (not the same reference)", () => {
      const raw = { agentId: "abc" };
      const result = sessionCodec.deserialize(raw);
      expect(result).not.toBe(raw);
    });
  });

  // ---------------------------------------------------------------------------
  // round-trip
  // ---------------------------------------------------------------------------
  describe("round-trip (serialize -> deserialize)", () => {
    it("produces deep-equal original state", () => {
      const original = { agentId: "abc", lastRunId: "run1", executionCount: 3 };
      const serialized = sessionCodec.serialize(original);
      const restored = sessionCodec.deserialize(serialized);
      expect(restored).toEqual(original);
    });

    it("preserves unknown future fields across round-trip (D-10)", () => {
      const original = { agentId: "abc", futureField: 42 };
      const serialized = sessionCodec.serialize(original);
      const restored = sessionCodec.deserialize(serialized);
      expect(restored).toEqual(original);
      expect((restored as Record<string, unknown>)["futureField"]).toBe(42);
    });
  });

  // ---------------------------------------------------------------------------
  // getDisplayId
  // ---------------------------------------------------------------------------
  describe("getDisplayId", () => {
    it("returns null when params is null", () => {
      expect(sessionCodec.getDisplayId!(null)).toBeNull();
    });

    it("returns null when params has no agentId", () => {
      expect(sessionCodec.getDisplayId!({})).toBeNull();
    });

    it("returns null when agentId is not a string", () => {
      expect(sessionCodec.getDisplayId!({ agentId: 123 })).toBeNull();
    });

    it("returns 'agent42:{agentId}' when agentId is present", () => {
      expect(sessionCodec.getDisplayId!({ agentId: "agent-123" })).toBe("agent42:agent-123");
    });
  });
});
