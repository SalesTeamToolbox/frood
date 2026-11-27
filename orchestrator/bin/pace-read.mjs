// Read the Claude Code weekly pace for routing (cc-pacing M4). One child process per call:
//   readPace({ timeoutMs }) runs `node <bin>/cc-pace.mjs status --json` (spawnSync, default timeout 10 s, the
//   caller's env, so ORCH_HOME and ORCH_NO_PACE apply) and returns the parsed object. It never throws: a non-zero
//   exit, a timeout, unparsable stdout or a missing file give { state: "unknown", reason: "pace read failed: <why>" }.
//   ORCH_PACE_BIN overrides the cc-pace.mjs path (tests: a missing file or a counting wrapper).
//   PACE_POLICY maps a role to its Claude Code agent: worker → cc-worker, worker-strong → cc-worker-strong,
//   critic → cc-critic, senior → cc-senior (cc-pacing-v2 A4). paceChain(role, chain, pace) puts that agent first
//   when the pace is "under" (never twice), except senior while Fable is over (pace.fable.state "over"); every
//   other role (scout, orchestrator, …) and every other state returns the chain unchanged.
//   ccPaceRecord(pace, prepended, role) is the receipt's `cc_pace` field.
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const PACE_TIMEOUT_MS = 10000;

const failed = (why) => ({ state: "unknown", reason: `pace read failed: ${String(why).replace(/\s+/g, " ").trim().slice(0, 60)}` });

export function paceBin() {
  return process.env.ORCH_PACE_BIN || path.join(HERE, "cc-pace.mjs");
}

export function readPace({ timeoutMs = PACE_TIMEOUT_MS } = {}) {
  try {
    const bin = paceBin();
    if (!fs.existsSync(bin)) return failed(`missing ${path.basename(bin)}`);
    const r = spawnSync(process.execPath, [bin, "status", "--json"], { encoding: "utf8", timeout: timeoutMs, env: process.env, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
    if (r.error) return failed(r.error.code === "ETIMEDOUT" ? "timeout" : r.error.code || r.error.message);
    if (r.status !== 0) return failed(r.status == null ? `signal ${r.signal}` : `exit ${r.status}`);
    const line = String(r.stdout || "").trim().split(/\r?\n/).filter(Boolean).pop();
    let j;
    try {
      j = JSON.parse(line ?? "");
    } catch {
      return failed("unparsable output");
    }
    if (!j || typeof j !== "object" || typeof j.state !== "string") return failed("unparsable output");
    return j;
  } catch (e) {
    return failed(e?.message || "error");
  }
}

/** The role → Claude Code agent table for pace routing. scout and orchestrator are never paced. */
export const PACE_POLICY = Object.freeze({ worker: "cc-worker", "worker-strong": "cc-worker-strong", critic: "cc-critic", senior: "cc-senior" });

/** The role's cc agent first on an `under` pace (senior: not while Fable is over); otherwise the chain unchanged. */
export function paceChain(role, chain, pace) {
  if (pace?.state !== "under" || !Object.hasOwn(PACE_POLICY, role)) return chain;
  if (role === "senior" && pace.fable?.state === "over") return chain;
  const agent = PACE_POLICY[role];
  if (chain[0] === agent) return chain;
  return [agent, ...chain];
}

const num = (v) => (Number.isFinite(v) ? v : null);

/**
 * The ledger shadow (cc-pacing-v2 A2) for a receipt: {nowcast_weekly, ledger_rate} from a pace's `ledger`, or from a
 * record's own `shadow` (a detached child re-records the launcher's cc_pace); null when neither is an object.
 */
function shadowOf(p) {
  const src = p.ledger && typeof p.ledger === "object" ? p.ledger : p.shadow && typeof p.shadow === "object" ? p.shadow : null;
  return src ? { nowcast_weekly: num(src.nowcast_weekly), ledger_rate: num(src.ledger_rate) } : null;
}

/**
 * The receipt's cc_pace: { state, weekly, projected, at, prepended, role, shadow }; absent values are null. `role` is
 * the --role of the launch (null for --agent). Shadow only: never routes.
 */
export function ccPaceRecord(pace, prepended = false, role = null) {
  const p = pace && typeof pace === "object" ? pace : {};
  return {
    state: typeof p.state === "string" ? p.state : "unknown",
    weekly: num(p.weekly),
    projected: num(p.projected),
    at: typeof p.at === "string" ? p.at : null,
    prepended: prepended === true,
    role: typeof role === "string" && role ? role : null,
    shadow: shadowOf(p),
  };
}
