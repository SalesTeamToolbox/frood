// Pool health: remember which models are down (quota, unavailable) so runs route around them
// instead of re-discovering the outage every call. Shared by oc-worker and router-health.
//
// File: ~/.config/orchestrator/pool-health.json  { "<provider/model>": { reason, until, since, detail } }
// An entry is "down" while now < until. Entries expire on their own; nothing has to clear them.
import "./no-window.mjs"; // hide console windows of every child process (Windows)
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const HOUR = 3600_000;

export function healthPath() {
  return path.join(process.env.ORCH_HOME || os.homedir(), ".config", "orchestrator", "pool-health.json");
}

export function readHealth() {
  try {
    return JSON.parse(fs.readFileSync(healthPath(), "utf8"));
  } catch {
    return {};
  }
}

function writeHealth(h) {
  const p = healthPath();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  const tmp = `${p}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(h, null, 2) + "\n");
  fs.renameSync(tmp, p); // atomic replace; last writer wins, entries are idempotent facts
}

/** Classify a run's errors: "quota" | "unavailable" | "rate-limit" | null, with a suggested outage length. */
export function classify(errors = []) {
  const text = errors.join("\n");
  const retry = text.match(/"retryAfterMs"\s*:\s*(\d+)/);
  // The plan does not include the model (e.g. CommandCode GOAT: Claude Opus, GPT-6 Sol). Not a quota:
  // it will not come back on its own, so hold it down for a week and let router-health re-check.
  if (/MODEL_NOT_IN_PLAN|not in (your )?plan|available in \w+ and above plans/i.test(text)) {
    return { reason: "not-in-plan", ms: 7 * 24 * HOUR };
  }
  // Output token limit / truncation (e.g., Nemotron "Response still truncated after two output token
  // limit continuations"): this is a model output constraint, not a pool failure. Treat as transient
  // so the model isn't marked down and the fallback chain doesn't trigger on output truncation.
  // Must run BEFORE the generic quota/limit check to avoid "limit" in "output token limit" matching quota.
  if (/output.?token.?limit|output.?limit|truncat|output.?exceeded/i.test(text)) {
    return { reason: "dropped", ms: 10 * 60_000 };
  }
  // Nvidia (nvidia/*) 429s are rate limits, not monthly quotas — they recover in minutes, not hours.
  // Treat as "rate-limit" with a short retry window so the same model can be retried after a brief wait.
  const isNvidia = /nvidia\//i.test(text);
  if (isNvidia && /429|rate.?limit|too many requests|rate limit exceeded/i.test(text)) {
    let ms = retry ? Number(retry[1]) : 5 * 60_000; // default 5 min if no retryAfterMs
    ms = Math.min(Math.max(ms, 60_000), 30 * 60_000); // clamp 1-30 min
    return { reason: "rate-limit", ms, scope: "model" };
  }
  if (/limit|quota|429|rate.?limit|insufficient|credit/i.test(text)) {
    // CommandCode says "Your limit resets at <ISO>" instead of retryAfterMs.
    const resets = text.match(/resets? at\s+(\d{4}-\d{2}-\d{2}T[\d:.]+Z)/i);
    let ms = retry ? Number(retry[1]) : resets ? Date.parse(resets[1]) - Date.now() : HOUR;
    ms = Math.min(Math.max(ms, 60_000), 7 * 24 * HOUR);
    // A weekly/plan limit takes out every model on that provider, not just the one that hit it.
    const scope = /weekly|monthly|your plan|plan limit|usage limit/i.test(text) ? "provider" : "model";
    return { reason: "quota", ms, scope };
  }
  // The connection dropped or the run went silent: this pool is flaky right now, retry it soon.
  // CommandCode transport timeouts ("Timed out waiting for response headers") land here so they
  // trigger the fallback chain and a short pool-down mark instead of a silent failed run.
  if (/ECONNRESET|socket hang up|ETIMEDOUT|EPIPE|fetch failed|other side closed|UND_ERR|stalled — no output|timeout|timed out/i.test(text)) {
    return { reason: "dropped", ms: 10 * 60_000 };
  }
  return null;
}

export function providerOf(model) {
  return model && model.includes("/") ? model.split("/")[0] : null;
}

export function markDown(model, { reason, ms, detail = "", scope = "model" }, now = Date.now()) {
  if (!model) return;
  const h = readHealth();
  const key = scope === "provider" && providerOf(model) ? `${providerOf(model)}/*` : model;
  h[key] = { reason, since: new Date(now).toISOString(), until: new Date(now + ms).toISOString(), detail: String(detail).slice(0, 200) };
  writeHealth(h);
}

export function markUp(model) {
  const h = readHealth();
  if (h[model]) {
    delete h[model];
    writeHealth(h);
  }
}

/** The outage record if `model` is currently known-down, else null. */
export function isDown(model, now = Date.now()) {
  if (!model) return null;
  const h = readHealth();
  for (const key of [model, `${providerOf(model)}/*`]) {
    const e = h[key];
    if (e && Date.parse(e.until) > now) return { ...e, key };
  }
  return null;
}

/** Model pinned by an installed OpenCode agent (frontmatter `model:`), or null. */
export function agentModel(agent) {
  const dirs = [path.join(process.env.ORCH_HOME || os.homedir(), ".config", "opencode", "agents"),
    path.join(process.env.ORCH_HOME || os.homedir(), ".config", "opencode", "agent")];
  for (const d of dirs) {
    try {
      const fm = fs.readFileSync(path.join(d, `${agent}.md`), "utf8").split(/\r?\n---/)[0];
      const m = fm.match(/^model:\s*(\S+)/m);
      if (m) return m[1];
    } catch {}
  }
  return null;
}

// ── provider policy (owner decisions in ~/.config/orchestrator/providers.json) ───────────────────────
// { "<provider>": { decision: "routed"|"ignored"|"free-only", allow: [globs], at, note } }
// `free-only` providers may be used only for models matching an owner-supplied glob (matched against the
// model id AFTER the provider prefix); free cannot be derived from the catalog, so the owner lists them.
export function providersPath() {
  return path.join(process.env.ORCH_HOME || os.homedir(), ".config", "orchestrator", "providers.json");
}

/**
 * Read providers.json. Only a missing file means "no policy" ({ok:true, data:{}}); a file that exists but does
 * not parse to an object is {ok:false}, and callers fail closed. Provider keys are lowercased.
 */
export function readProviders() {
  let text;
  try {
    text = fs.readFileSync(providersPath(), "utf8");
  } catch (e) {
    return e.code === "ENOENT" ? { ok: true, data: {} } : { ok: false, data: {} };
  }
  try {
    const raw = JSON.parse(text);
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return { ok: false, data: {} };
    return { ok: true, data: Object.fromEntries(Object.entries(raw).map(([k, v]) => [k.toLowerCase(), v])) };
  } catch {
    return { ok: false, data: {} };
  }
}

/** True when providers.json holds any `free-only` or `ignored` decision (or cannot be read). */
export function hasRestrictivePolicy() {
  const r = readProviders();
  // Anything other than an explicit "routed" counts as restrictive (unknown values fail closed).
  return !r.ok || Object.values(r.data).some((e) => e && e.decision !== "routed");
}

export function providerPolicy(model) {
  const p = providerOf(model)?.toLowerCase();
  if (!p) return null;
  const e = readProviders().data[p];
  return e ? { decision: e.decision, allow: Array.isArray(e.allow) ? e.allow : [] } : null;
}

// Never free even on an allowlisted free-only provider: non-text modalities the owner did not approve.
const DENY = ["*-image*", "*-tts*", "*live*", "*-audio*", "*embedding*"];

/**
 * False for: an unreadable providers.json (every model, fail closed), an `ignored` provider, or a `free-only`
 * provider when the model matches no allow glob or matches a built-in deny glob.
 */
export function modelAllowed(model) {
  if (!model) return true;
  if (!readProviders().ok) return false;
  const pol = providerPolicy(model);
  if (!pol) return true;
  if (pol.decision === "ignored") return false;
  if (pol.decision === "free-only") {
    const rest = model.slice(model.indexOf("/") + 1);
    if (DENY.some((g) => path.posix.matchesGlob(rest, g))) return false;
    return pol.allow.some((g) => path.posix.matchesGlob(rest, g));
  }
  // Only an explicit "routed" allows unrestricted use. Any other value (a hand-edited typo such as "free_only" or
  // "Free-Only") fails closed — senior review 2026-11-12.
  return pol.decision === "routed";
}

/** Why a model is not allowed (for receipts), or null. */
export function policyReason(model) {
  if (modelAllowed(model)) return null;
  if (!readProviders().ok) return "policy: providers.json unreadable";
  return `policy: ${providerPolicy(model).decision}`;
}

/** A model on a `free-only` provider that matches the allowlist counts as free. */
export function isPolicyFree(model) {
  return providerPolicy(model)?.decision === "free-only" && modelAllowed(model);
}

// Providers auto-recorded as routed when an installed agent pins them; every other connected provider needs an
// explicit owner decision in providers.json even if an agent already uses it.
export const SEED_PROVIDERS = new Set(["opencode", "opencode-go", "commandcode"]);

/** True when the provider of `model` is neither a seed provider nor has an owner decision. */
export function lacksDecision(model) {
  const p = providerOf(model)?.toLowerCase();
  return Boolean(p) && !SEED_PROVIDERS.has(p) && !readProviders().data[p];
}
