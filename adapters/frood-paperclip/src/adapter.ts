/**
 * adapter.ts — execute() and testEnvironment() implementing the Paperclip ServerAdapterModule.
 *
 * These are the core business logic functions that bridge Paperclip's AdapterExecutionContext
 * to Agent42's sidecar POST format.
 *
 * Key mappings:
 *   - ctx.agent.adapterConfig (unknown) → SidecarConfig via parseSidecarConfig()
 *   - ctx.agent.id → fallback agentId when adapterConfig.agentId is absent (ADAPT-04)
 *   - adapterConfig.agentId populated in BOTH top-level and adapterConfig (D-14)
 *   - ctx.context.wakeReason → sidecar wakeReason, defaulting to "heartbeat" (ADAPT-03, D-11)
 *   - unknown wakeReason values log a warning but do NOT throw (D-12)
 *   - session state round-trips via sessionCodec, with executionCount tracking (ADAPT-05)
 *   - JSON.stringify(sessionState) → adapterConfig.sessionKey string (D-08)
 */

import type {
  AdapterExecutionContext,
  AdapterExecutionResult,
  AdapterEnvironmentTestContext,
  AdapterEnvironmentTestResult,
} from "@paperclipai/adapter-utils";
import { Agent42Client } from "./client.js";
import { parseSidecarConfig } from "./types.js";
import { sessionCodec } from "./session.js";
import type { SidecarExecuteRequest } from "./types.js";

// Known wakeReason values per D-11 / D-12
const KNOWN_WAKE_REASONS = new Set(["heartbeat", "task_assigned", "manual"]);

// ---------------------------------------------------------------------------
// execute()
// ---------------------------------------------------------------------------

/**
 * execute — maps a Paperclip AdapterExecutionContext to an Agent42 sidecar call.
 *
 * Returns an AdapterExecutionResult with:
 *   - exitCode: 0 on success, 1 on any error
 *   - sessionParams: updated state with incremented executionCount
 *   - sessionDisplayId: "run:{runId}"
 *   - summary: brief status description
 *
 * Never throws — all errors are captured into exitCode:1 + errorMessage.
 */
export async function execute(ctx: AdapterExecutionContext): Promise<AdapterExecutionResult> {
  // 1. Parse adapter config defensively (Pitfall 2 — adapterConfig is typed as unknown)
  const config = parseSidecarConfig(ctx.agent.adapterConfig);

  // 2. Resolve bearer token — auto-provision from apiKey if needed (D-11, D-13)
  let bearerToken = config.bearerToken;
  if (config.apiKey && !bearerToken) {
    try {
      bearerToken = await provisionToken(config.sidecarUrl, config.apiKey);
      await ctx.onLog("stdout", "[frood-adapter] Auto-provisioned bearer token from apiKey");
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return {
        exitCode: 1,
        signal: null,
        timedOut: false,
        errorMessage: `Token provisioning failed: ${msg}`,
        summary: `Failed: Token provisioning failed: ${msg}`,
      };
    }
  }

  // 3. Create HTTP client
  const client = new Agent42Client(config.sidecarUrl, bearerToken);

  // 4. Resolve agentId (ADAPT-04, D-13, D-14)
  //    Prefer the Agent42 agent UUID from adapterConfig; fall back to Paperclip agent ID
  const agentId = config.agentId || ctx.agent.id;

  // 5. Extract and validate wakeReason (ADAPT-03, D-11, D-12)
  const wakeReason = ((ctx.context as Record<string, unknown>)?.wakeReason as string) ?? "heartbeat";
  if (!KNOWN_WAKE_REASONS.has(wakeReason)) {
    await ctx.onLog(
      "stderr",
      `[frood-adapter] Warning: unknown wakeReason "${wakeReason}". Expected one of: ${[...KNOWN_WAKE_REASONS].join(", ")}`,
    );
  }

  // 6. Decode existing session state (ADAPT-05)
  const sessionState = ctx.runtime.sessionParams
    ? (sessionCodec.deserialize(ctx.runtime.sessionParams) ?? {})
    : {};

  // 7. Build sidecar POST body
  const sidecarBody: SidecarExecuteRequest = {
    runId: ctx.runId,
    agentId,                                           // top-level (D-14)
    companyId: ctx.agent.companyId,
    taskId: ((ctx.context as Record<string, unknown>)?.taskId as string) ?? "",
    wakeReason,                                        // from ctx.context (D-11)
    context: (ctx.context as Record<string, unknown>) ?? {},  // full Paperclip context passthrough
    adapterConfig: {
      sessionKey: JSON.stringify(sessionState),        // string encoding for Pydantic sessionKey (D-08)
      memoryScope: config.memoryScope ?? "agent",
      preferredProvider: config.preferredProvider ?? "",
      agentId,                                         // also in adapterConfig (D-14)
    },
  };

  // 8. Call sidecar and build result
  try {
    let resp: Awaited<ReturnType<typeof client.execute>>;
    try {
      resp = await client.execute(sidecarBody);
    } catch (firstErr) {
      // 401 retry with fresh token (D-12)
      const firstMsg = firstErr instanceof Error ? firstErr.message : String(firstErr);
      if (firstMsg.includes("HTTP 401") && config.apiKey) {
        await ctx.onLog("stdout", "[frood-adapter] 401 received, refreshing token...");
        const freshToken = await provisionToken(config.sidecarUrl, config.apiKey);
        client.setBearerToken(freshToken);
        resp = await client.execute(sidecarBody);
      } else {
        throw firstErr;
      }
    }

    // Build updated session state (ADAPT-05)
    const newSessionState: Record<string, unknown> = {
      ...sessionState,
      agentId,
      lastRunId: ctx.runId,
      executionCount: ((sessionState.executionCount as number) ?? 0) + 1,
    };

    return {
      exitCode: 0,
      signal: null,
      timedOut: false,
      summary: `Accepted (runId=${ctx.runId}, deduplicated=${resp.deduplicated})`,
      sessionParams: sessionCodec.serialize(newSessionState),
      sessionDisplayId: `run:${ctx.runId}`,
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      exitCode: 1,
      signal: null,
      timedOut: false,
      errorMessage: message,
      summary: `Failed: ${message}`,
    };
  }
}

// ---------------------------------------------------------------------------
// testEnvironment()
// ---------------------------------------------------------------------------

/**
 * testEnvironment — probes the Agent42 sidecar /health endpoint.
 *
 * Returns a structured AdapterEnvironmentTestResult with:
 *   - status: "pass" | "warn" | "fail"
 *   - checks: array of {code, level, message, hint?} diagnostics
 *   - testedAt: ISO timestamp
 */
export async function testEnvironment(
  ctx: AdapterEnvironmentTestContext,
): Promise<AdapterEnvironmentTestResult> {
  const config = parseSidecarConfig(ctx.config);
  const checks: AdapterEnvironmentTestResult["checks"] = [];
  let status: "pass" | "warn" | "fail" = "pass";

  if (!config.sidecarUrl) {
    checks.push({
      code: "missing_sidecar_url",
      level: "error",
      message: "sidecarUrl is not configured",
      hint: "Set sidecarUrl in adapter config",
    });
    status = "fail";
  } else {
    const client = new Agent42Client(config.sidecarUrl, config.bearerToken);
    try {
      const health = await client.health();

      // Success path — sidecar reachable
      checks.push({
        code: "sidecar_reachable",
        level: "info",
        message: `Agent42 sidecar reachable at ${config.sidecarUrl}`,
      });

      // Warn if subsystems are unavailable
      if (!health.memory.available) {
        checks.push({
          code: "memory_unavailable",
          level: "warn",
          message: "Memory subsystem reports unavailable",
          hint: "Ensure Qdrant is running and accessible",
        });
        if (status === "pass") status = "warn";
      }

      if (!health.qdrant.available) {
        checks.push({
          code: "qdrant_unavailable",
          level: "warn",
          message: "Qdrant reports unavailable",
          hint: "Start Qdrant or check connection settings",
        });
        if (status === "pass") status = "warn";
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      checks.push({
        code: "sidecar_unreachable",
        level: "error",
        message: `Cannot reach Agent42 sidecar: ${message}`,
        hint: `Verify Agent42 is running at ${config.sidecarUrl}`,
      });
      status = "fail";
    }
  }

  return {
    adapterType: ctx.adapterType,
    status,
    checks,
    testedAt: new Date().toISOString(),
  };
}

// ---------------------------------------------------------------------------
// provisionToken() — POST /sidecar/token with an API key to get a JWT (D-11)
// ---------------------------------------------------------------------------

async function provisionToken(sidecarUrl: string, apiKey: string): Promise<string> {
  const resp = await fetch(`${sidecarUrl}/sidecar/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!resp.ok) {
    throw new Error(`Token provisioning failed: HTTP ${resp.status}`);
  }
  const data = (await resp.json()) as { token: string; expires_in: number };
  return data.token;
}
