// Pool health: remember which models are down (quota, unavailable) so runs route around them
// instead of re-discovering the outage every call. Shared by oc-worker and router-health.
//
// Owner rule (2026-11-26): never spend the OpenCode Go allowance on a Claude model — Claude Code
// covers Claude on its own subscription. `isClaudeViaGo` / `modelAllowed` / `policyReason` enforce
// it: `opencode-go/claude*` and `opencode-go/*anthropic*` are refused before any providers.json
// lookup, so no owner decision can re-allow them.
//
// File: ~/.config/orchestrator/pool-health.json  { "<provider/model>": { reason, until, since, detail } }
// An entry is "down" while now < until. Entries expire on their own; nothing has to clear them.
import "./no-window.mjs"; // hide console windows of every child process (Windows)
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const HOUR = 3600_000;
/** Pool-health key of the headless Claude Code writer (oc-worker --agent cc-worker). */
export const CC_POOL = "cc-worker";
/** Every headless Claude Code agent (cc-worker, cc-worker-strong, cc-critic, cc-senior, ...) is keyed by its agent
 *  name, and every such key starts with this prefix. They share one Claude subscription, so they are one GROUP for
 *  subscription limits: isDown on a cc-* key is true while its own key is down, or while another cc-* key holds a
 *  live `quota` / `rate-limit` mark (a `dropped` / `provider-error` mark holds down only its own key);
 *  markGroupDown writes the same mark under every known cc key; markUp on a cc key clears its own key and the
 *  other cc-* marks (an answer proves the subscription is back), except, given opts.startedAt, a mark written
 *  after that run started. */
export const CC_PREFIX = "cc-";
export const isCcPool = (key) => typeof key === "string" && key.startsWith(CC_PREFIX);
const CC_WINDOW_MS = 5 * HOUR;
/** Mark reasons that are the subscription's, so one cc-* key's mark holds the whole cc group down. */
const GROUP_REASONS = new Set(["quota", "rate-limit"]);

/** Milliseconds until the reset a Claude limit message names, or null. Forms: "limit reached|<epoch seconds>",
 *  "resets at <ISO>", "resets 3pm" / "resets 3:30 pm" (next such local time). */
export function ccResetMs(text, now = Date.now()) {
  const epoch = text.match(/limit reached\|(\d{9,13})\b/i);
  if (epoch) {
    const n = Number(epoch[1]);
    return (n < 1e11 ? n * 1000 : n) - now;
  }
  const iso = text.match(/resets?\s+(?:at\s+)?(\d{4}-\d{2}-\d{2}T[\d:.]+Z)/i);
  if (iso) return Date.parse(iso[1]) - now;
  const clock = text.match(/resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b/i);
  if (clock) {
    let h = Number(clock[1]) % 12;
    if (clock[3].toLowerCase() === "pm") h += 12;
    const t = new Date(now);
    t.setHours(h, Number(clock[2] || 0), 0, 0);
    if (t.getTime() <= now) t.setDate(t.getDate() + 1);
    return t.getTime() - now;
  }
  return null;
}

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

/** Classify a run's errors: "quota" | "unavailable" | "absent" | "rate-limit" | null, with a suggested outage length.
 *  Pass the model that was called: Nvidia's 429 body names no model, so the error text alone cannot tell it apart. */
export function classify(errors = [], model = null) {
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
  // Claude Code (cc-*) limits. The pool key is the cc agent name, e.g. "cc-worker" (no provider prefix). A subscription usage limit
  // holds the pool down until the 5-hour window resets: the reset time when the text names one, else now + 5 h.
  // A plain 429 / rate_limit_error recovers in minutes, so it is a short "rate-limit". "overloaded" falls through
  // to the provider-error branch below.
  const isCc = isCcPool(model) || /Claude AI usage limit|5-hour limit|hit your limit/i.test(text);
  if (isCc && /usage limit|limit reached|hit your limit|5-hour limit|weekly limit|limit.{0,40}resets?/i.test(text)) {
    return { reason: "quota", ms: Math.min(Math.max(ccResetMs(text) ?? CC_WINDOW_MS, 60_000), 7 * 24 * HOUR), scope: "model" };
  }
  if (isCc && /rate.?limit|\b429\b|too many requests/i.test(text)) {
    return { reason: "rate-limit", ms: 5 * 60_000, scope: "model" };
  }
  // Nvidia (nvidia/*) 429s are rate limits, not monthly quotas — they recover in minutes, not hours.
  // Treat as "rate-limit" with a short retry window so the same model can be retried after a brief wait.
  // Know it by the model that was called: Nvidia's real 429 body ({"status":429,"title":"Too Many Requests"}) names no
  // model, so a text-only check sent it to the generic branch below as a 1-hour "quota" (2026-11-25).
  const isNvidia = providerOf(model) === "nvidia" || /nvidia\//i.test(text);
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
    // A weekly/plan limit takes out every model on that provider, not just the one that hit it. So does
    // an empty account ("insufficient credits", CommandCode 2026-11-24: two models on one provider both
    // failed on it, because only the first model was marked down).
    const scope = /weekly|monthly|your plan|plan limit|usage limit|insufficient credits|purchase more credits/i.test(text) ? "provider" : "model";
    return { reason: "quota", ms, scope };
  }
  // The harness no longer offers this model (a provider was removed: `{"type":"provider.no-route","message":"Model
  // unavailable: ..."}`). It will not come back on its own and the next run would pay the same dead hop, so hold the
  // one model down for a day. The scope is the model: the provider's other models may still be there.
  if (/provider\.no-route|Model unavailable|ProviderModelNotFound|provider \S+ not found/i.test(text)) {
    return { reason: "absent", ms: 24 * HOUR, scope: "model" };
  }
  // Restored 2026-11-24: these two branches were dropped by an unrelated commit on 2026-11-21 (the
  // /orchestrator-learn import), so a retired model or a broken provider never marked the pool down.
  if (/model.{0,40}(not found|unknown|unsupported|does not exist|no longer|deprecated|retired)|ModelNotFound|unknown model|404/i.test(text)) {
    return { reason: "unavailable", ms: 24 * HOUR };
  }
  // Any other provider-side failure (e.g. CommandCode's Anthropic shim rejecting a message shape:
  // "provider.invalid-request ... messages.3.role", seen 2026-11-12): this pool is broken right now.
  // Short outage, then it is retried — unlike quota, nothing tells us when it recovers.
  if (/"type"\s*:\s*"provider\.[a-z-]+"|provider\.(invalid-request|error|overloaded|unavailable|timeout)|\b5\d\d\b.*(error|unavailable)|overloaded/i.test(text)) {
    return { reason: "provider-error", ms: 15 * 60_000 };
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

/** markDown for a group: the same mark under every key in `keys` (one read, one write). The cc group uses it. */
export function markGroupDown(keys, { reason, ms, detail = "" }, now = Date.now()) {
  const list = [...new Set((keys || []).filter(Boolean))];
  if (!list.length) return;
  const h = readHealth();
  const mark = { reason, since: new Date(now).toISOString(), until: new Date(now + ms).toISOString(), detail: String(detail).slice(0, 200) };
  for (const k of list) h[k] = { ...mark };
  writeHealth(h);
}

// A model that just answered proves its provider is reachable, so a provider-wide mark (`go/*`, set from a
// monthly/plan quota) goes too. Without this, renewing a plan left the whole provider skipped until the old
// retry-after ran out (Go, 2026-11-21 -> 11-26: five days of no Go after the subscription was live again).
// opts.startedAt (ms): when the answering run started. For a cc key, another cc-* mark whose `since` is later than
// that is newer evidence (another run hit the limit while this one was answering) and stays; the key's own mark always
// goes. Without startedAt every cc-* mark goes (legacy callers). Non-cc keys ignore it.
export function markUp(model, opts = {}) {
  const h = readHealth();
  const startedAt = Number.isFinite(opts?.startedAt) ? opts.startedAt : null;
  const olderThanRun = (e) => {
    if (startedAt === null) return true;
    const since = Date.parse(e?.since);
    return !Number.isFinite(since) || since <= startedAt; // a mark with no readable `since` cannot prove it is newer
  };
  const keys = isCcPool(model)
    ? Object.keys(h).filter((k) => isCcPool(k) && (k === model || olderThanRun(h[k]))) // one Claude subscription
    : [model, providerOf(model) ? `${providerOf(model)}/*` : null].filter((k) => k && h[k]);
  if (keys.length) {
    for (const k of keys) delete h[k];
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
  // The cc group: a live subscription limit (quota / rate-limit) on any cc-* key holds every cc agent down (one
  // Claude subscription). Any other mark (dropped, provider-error, ...) is that agent's own trouble.
  if (isCcPool(model)) {
    for (const [key, e] of Object.entries(h)) {
      if (isCcPool(key) && e && GROUP_REASONS.has(e.reason) && Date.parse(e.until) > now) return { ...e, key };
    }
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
 * True for a Claude model routed through OpenCode Go (`opencode-go/claude*`,
 * `opencode-go/*anthropic*`, case-insensitive). The owner (2026-11-26) forbids
 * spending the Go allowance on Claude: Claude Code covers those on its own
 * subscription. Checked before any providers.json lookup, so no owner
 * decision can re-allow such a model.
 */
export function isClaudeViaGo(model) {
  if (typeof model !== "string") return false;
  const cut = model.indexOf("/");
  if (cut === -1) return false;
  if (model.slice(0, cut).toLowerCase() !== "opencode-go") return false;
  const rest = model.slice(cut + 1).toLowerCase();
  return rest.startsWith("claude") || rest.startsWith("anthropic") || rest.includes("anthropic");
}

/**
 * False for: a Claude model through OpenCode Go (owner rule, before any providers.json
 * lookup), an unreadable providers.json (every model, fail closed), an `ignored` provider,
 * or a `free-only` provider when the model matches no allow glob or matches a built-in deny glob.
 */
export function modelAllowed(model) {
  if (!model) return true;
  if (isClaudeViaGo(model)) return false;
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
  if (isClaudeViaGo(model)) return "policy: claude via go";
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
export const SEED_PROVIDERS = new Set(["opencode", "opencode-go"]);

/** True when the provider of `model` is neither a seed provider nor has an owner decision. */
export function lacksDecision(model) {
  const p = providerOf(model)?.toLowerCase();
  return Boolean(p) && !SEED_PROVIDERS.has(p) && !readProviders().data[p];
}
