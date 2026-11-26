// Read the Claude Code weekly pace for routing (cc-pacing M4). One child process per call:
//   readPace({ timeoutMs }) runs `node <bin>/cc-pace.mjs status --json` (spawnSync, default timeout 10 s, the
//   caller's env, so ORCH_HOME and ORCH_NO_PACE apply) and returns the parsed object. It never throws: a non-zero
//   exit, a timeout, unparsable stdout or a missing file give { state: "unknown", reason: "pace read failed: <why>" }.
//   ORCH_PACE_BIN overrides the cc-pace.mjs path (tests: a missing file or a counting wrapper).
//   paceChain(role, chain, pace) puts cc-worker first only for role "worker" when the pace is "under"; any other
//   case returns the chain unchanged. ccPaceRecord(pace, prepended) is the receipt's `cc_pace` field.
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

/** cc-worker first only for --role worker on an `under` pace; otherwise the same chain contents. */
export function paceChain(role, chain, pace) {
  if (role === "worker" && pace?.state === "under") return ["cc-worker", ...chain];
  return chain;
}

const num = (v) => (Number.isFinite(v) ? v : null);

/** The receipt's cc_pace: { state, weekly, projected, at, prepended }; absent values are null. */
export function ccPaceRecord(pace, prepended = false) {
  const p = pace && typeof pace === "object" ? pace : {};
  return {
    state: typeof p.state === "string" ? p.state : "unknown",
    weekly: num(p.weekly),
    projected: num(p.projected),
    at: typeof p.at === "string" ? p.at : null,
    prepended: prepended === true,
  };
}
