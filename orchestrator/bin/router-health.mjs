#!/usr/bin/env node
// Periodic self-correction for model routing. Cheap; safe to run at every orchestrator start.
//
//   node router-health.mjs [--probe | --probe-all] [--if-stale <hours>] [--models-file <file>] [--auth-file <file>] [--json]
//   node router-health.mjs --decide <provider-id> routed|ignored [--note <text>]
//   node router-health.mjs --decide <provider-id> free-only --allow "<glob>[,<glob>...]"   (globs match the id after the provider/)
//   node router-health.mjs --free
//   node router-health.mjs --probe-free
//
// For each role chain (agents in fallback order) it:
//   1. reads the model each installed OpenCode agent pins;
//   2. marks a model `unavailable` in pool-health if it is missing from live `opencode models`;
//   3. with --probe, sends each not-known-down model a one-word prompt ("PONG") and marks it down/up
//      from the result (quota/unavailable errors only — anything else is reported, not marked); a quota mark (which
//      can last days) is re-tested once per run, and a model that answers also clears its provider-wide mark;
//   4. prints, per role, the first healthy agent to dispatch and why earlier ones were skipped.
// It never edits agents or rules and never promotes a model outside the chains below: choosing a NEW
// model stays a human decision via /frood-model-router-refresh (bake-off evidence first).
// --if-stale N: exit 0 immediately when the last check is younger than N hours.
// Pace (cc-pacing M4): every run except --decide reads `cc-pace.mjs status --json` once, before the --if-stale
//   early return, and in text mode prints `pace: <cc-pace status line>` as the first stdout line (both paths).
//   OVER adds `pace: OVER — conserve: ...` right after it, then `pace: OVER — critic and senior via oc-worker --role,
//   not Agent(critic|senior) unless guarded`. UNDER (cc-pacing-v2 A4) changes only the worker, worker-strong, critic
//   and senior lines to `use cc-<role> (pace UNDER), fallback <agent>` (PACE_POLICY in pace-read.mjs), except when
//   that cc agent is down in pool-health (isDown) or, for senior, while Fable is over: then the line is today's.
//   --json adds a top-level `pace` key; the stamp never holds it.
// --free: prints a FREE INVENTORY section after the role lines (also included in default output)
// --probe-free: probes every unused, allowed free model (max 12, serial), writes free-inventory.json, never marks down/up
// Exit: 0 every role has a healthy agent, 1 some role has none, 2 usage error.
import "./no-window.mjs"; // hide console windows of every child process (Windows)
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn, execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { agentModel, providerOf, readProviders, SEED_PROVIDERS, classify, isDown, markDown, markUp, readHealth, providerPolicy, modelAllowed, policyReason } from "./pool-health.mjs";
import { collectUsage, poolHeadroom, loadLimits, LOW_HEADROOM_PCT_DEFAULT } from "./usage.mjs";
import { opencodeBin } from "./oc-worker.mjs";
import { CHAINS } from "./chains.mjs";
import { readPace, PACE_POLICY } from "./pace-read.mjs";
import { statusLine as paceStatusLine } from "./cc-pace.mjs";

// Probing these costs real money per call (a large system prompt on a strong model — Sonnet ~$0.07)
// and they run rarely; --probe skips them unless --probe-all. Existence + real failures still mark them.
const EXPENSIVE_ROLES = new Set(["senior"]);

const orchDir = () => path.join(process.env.ORCH_HOME || os.homedir(), ".config", "orchestrator");
const decisionsPath = () => path.join(orchDir(), "providers.json");

// Provider ids from `opencode auth list` display names ("OpenCode Console" -> opencode), matched against
// the prefixes of `opencode models`. Rows are the lines ending in `stored`; the first column is the name.
export function connectedProviders(authText, modelIds = []) {
  const prefixes = new Set([...modelIds].filter((m) => m.includes("/")).map((m) => m.split("/")[0]));
  const ids = new Set();
  for (const raw of String(authText).split(/\r?\n/)) {
    const line = raw.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "").replace(/^[^A-Za-z0-9]+/, "").trim();
    if (!/\bstored$/.test(line)) continue;
    const name = line.replace(/\s*\bstored$/, "").split(/\s{2,}/)[0].trim().toLowerCase();
    if (!name) continue;
    const dashed = name.replace(/\s+/g, "-");
    const first = name.split(/\s+/)[0];
    ids.add(prefixes.has(dashed) ? dashed : prefixes.has(first) ? first : dashed);
  }
  return [...ids].sort();
}

function writeFileAtomic(file, text) {
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, text);
  fs.renameSync(tmp, file);
}

// Provider keys are lowercase. Only a missing file is empty; one that exists but is unreadable is never overwritten.
function readDecisions() {
  return readProviders().data;
}
function writeDecision(id, decision, note = "", allow = undefined) {
  const cur = readProviders();
  if (!cur.ok) throw new Error(`${decisionsPath()} exists but cannot be parsed — fix or remove it before recording decisions`);
  const d = cur.data;
  d[id.toLowerCase()] = { decision, ...(allow ? { allow } : {}), at: new Date().toISOString(), note };
  fs.mkdirSync(orchDir(), { recursive: true });
  writeFileAtomic(decisionsPath(), JSON.stringify(d, null, 2) + "\n");
}


// Connected providers with no decision. Providers pinned by an installed chain agent are auto-routed.
export function detectNewProviders({ authFile, live } = {}) {
  if (process.env.ORCH_NO_AUTH) return { providers: [], note: "ORCH_NO_AUTH set — new-provider detection skipped" };
  if (!readProviders().ok) return { providers: [], note: "providers.json exists but cannot be parsed — new-provider detection skipped" };
  let auth;
  try {
    const bin = opencodeBin();
    auth = authFile ? fs.readFileSync(authFile, "utf8") : execFileSync(bin.cmd, [...(bin.pre || []), "auth", "list"], { encoding: "utf8", timeout: 60000, stdio: ["ignore", "pipe", "ignore"] });
  } catch {
    return { providers: [], note: "`opencode auth list` unavailable — new-provider detection skipped" };
  }
  const ids = live ? [...live] : [];
  const inChain = new Set();
  for (const chain of Object.values(CHAINS)) for (const a of chain) { const p = providerOf(agentModel(a)); if (p) inChain.add(p); }
  const decisions = readDecisions();
  const providers = [];
  for (const id of connectedProviders(auth, ids)) {
    if (decisions[id]) continue;
    if (inChain.has(id) && SEED_PROVIDERS.has(id)) { writeDecision(id, "routed", "in a chain"); continue; }
    providers.push({ id, models: ids.filter((m) => m.startsWith(id + "/")).length });
  }
  return { providers };
}

const stampPath = () => path.join(process.env.ORCH_HOME || os.homedir(), ".config", "orchestrator", "router-health.json");
const freeInventoryPath = () => path.join(orchDir(), "free-inventory.json");

// Read OpenCode model catalog from ~/.cache/opencode/models.json or ORCH_OC_CATALOG
// Real structure: { "<provider>": { "models": { "<id>": { "cost": {...} } } } } (no wrapper key)
function readCatalog() {
  const catalogPath = process.env.ORCH_OC_CATALOG || path.join(os.homedir(), ".cache", "opencode", "models.json");
  try {
    return JSON.parse(fs.readFileSync(catalogPath, "utf8"));
  } catch {
    return null;
  }
}

// Check if a model is zero-cost according to the catalog
function isZeroCostCatalog(model, catalog) {
  if (!catalog) return false;
  const [prov, ...rest] = model.split("/");
  if (!prov || rest.length === 0) return false;
  const modelId = rest.join("/");
  const provCatalog = catalog[prov];
  if (!provCatalog || !provCatalog.models) return false;
  const modelInfo = provCatalog.models[modelId];
  if (!modelInfo || !modelInfo.cost) return false;
  return modelInfo.cost.input === 0 && modelInfo.cost.output === 0;
}

// Check if a model has the trains-on-data tag (contributor or iceman)
function hasTrainsOnData(model) {
  return model.includes("contributor") || model.includes("iceman");
}

// Static list of known vision-capable models (fallback when catalog lacks vision field)
// Updated via /frood-model-router-refresh; sources: provider docs, bake-off results
const VISION_CAPABLE_MODELS = new Set([
  // Nvidia Nemotron 3.5 Super VL - vision capable, rate-limited (free pool)
  "nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b",
  // Muse on Go - vision capable (per plan constraint #4)
  "opencode-go/muse-spark-1.3-contributor",
  "opencode-go/muse-spark-1.2-contributor",
]);

// Check if a model is vision-capable (catalog-based with static fallback)
function isVisionCapable(model, catalog) {
  // First check static list (authoritative, updated via model-router-refresh)
  if (VISION_CAPABLE_MODELS.has(model)) return true;
  // Fallback: check catalog for vision capability field (if provider adds it in future)
  if (catalog) {
    const [prov, ...rest] = model.split("/");
    if (prov && rest.length > 0) {
      const modelId = rest.join("/");
      const provCatalog = catalog[prov];
      if (provCatalog && provCatalog.models && provCatalog.models[modelId]) {
        const modelInfo = provCatalog.models[modelId];
        if (modelInfo.vision === true) return true;
      }
    }
  }
  return false;
}

// Nemotron 3.5 VL rate limit note
function getNemotronRateLimitNote(model) {
  return model === "nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b"
    ? "vision-capable, rate-limited (free pool, patience-based cooldown via pool-health)"
    : null;
}

function liveModels(file) {
  try {
    const text = file ? fs.readFileSync(file, "utf8") : execFileSync(opencodeBin().cmd, [...(opencodeBin().pre || []), "models"], { encoding: "utf8", timeout: 120000, stdio: ["ignore", "pipe", "ignore"] });
    return new Set(text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean));
  } catch {
    return null;
  }
}

function probe(agent, timeoutMs = 90000) {
  return new Promise((resolve) => {
    const bin = opencodeBin();
    const child = spawn(bin.cmd, [...(bin.pre || []), "run", "--format", "json", "--agent", agent, "--title", `orch router-health probe ${agent}`, "Reply with exactly: PONG"], { stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
    let out = "";
    let err = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    const t = setTimeout(() => {
      try {
        if (process.platform === "win32") execFileSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
        else child.kill("SIGKILL");
      } catch {}
    }, timeoutMs);
    child.on("close", (code) => {
      clearTimeout(t);
      const errors = out.split("\n").filter((l) => /"type":"error"/.test(l)).concat(code ? [err.slice(-300)] : []);
      resolve({ ok: /PONG/i.test(out) && !errors.length, errors, code });
    });
    child.on("error", (e) => resolve({ ok: false, errors: [String(e)], code: -1 }));
  });
}

// Probe a model and return {ok, errors, code, seconds}
// Title exactly "orch router-health free probe", --title before --model
export async function probeModel(model, timeoutMs = 90000) {
  const start = Date.now();
  return new Promise((resolve) => {
    const bin = opencodeBin();
    const child = spawn(bin.cmd, [...(bin.pre || []), "run", "--format", "json", "--title", "orch router-health free probe", "--model", model, "Reply with exactly: PONG"], { stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
    let out = "";
    let err = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    const t = setTimeout(() => {
      try {
        if (process.platform === "win32") execFileSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
        else child.kill("SIGKILL");
      } catch {}
    }, timeoutMs);
    child.on("close", (code) => {
      clearTimeout(t);
      const seconds = (Date.now() - start) / 1000;
      const errors = out.split("\n").filter((l) => /"type":"error"/.test(l)).concat(code ? [err.slice(-300)] : []);
      resolve({ ok: /PONG/i.test(out) && !errors.length, errors, code, seconds });
    });
    child.on("error", (e) => resolve({ ok: false, errors: [String(e)], code: -1, seconds: (Date.now() - start) / 1000 }));
  });
}

function readFreeInventory() {
  try {
    return JSON.parse(fs.readFileSync(freeInventoryPath(), "utf8"));
  } catch {
    return {};
  }
}

function writeFreeInventory(inv) {
  fs.mkdirSync(orchDir(), { recursive: true });
  writeFileAtomic(freeInventoryPath(), JSON.stringify(inv, null, 2) + "\n");
}

function classifyProbe(errors = [], model = null) {
  const cls = classify(errors, model);
  return cls ? cls.reason : "unknown";
}

export async function check({ probeModels = false, probeAll = false, models = undefined, newProviders = [], free = false, probeFree = false, authFile = undefined } = {}) {
  const live = models === undefined ? liveModels() : models;
  const report = { checked_at: new Date().toISOString(), live_models: live ? live.size : null, roles: {}, notes: [], new_providers: newProviders, free_inventory: null };
  // Read catalog once for vision detection and zero-cost detection
  const catalog = readCatalog();
  if (!live) {
    report.notes.push("`opencode models` unavailable — existence check skipped");
    // Still include free_inventory with unavailable message
    report.free_inventory = { counts: { live: 0, in_chains: 0, blocked: 0, unused: 0, down: 0 }, models: [], unavailable: true };
  }

  // --- Free inventory: ALWAYS compute when live is available ---
  if (live) {
    // Collect candidate free models
    const chainModels = new Set();
    for (const chain of Object.values(CHAINS)) {
      for (const a of chain) {
        const m = agentModel(a);
        if (m) chainModels.add(m);
      }
    }
    // Get connected providers (for skipping catalog-only providers without auth)
    // SEED_PROVIDERS (opencode, opencode-go) are exempt from auth check
    let connectedProviderIds = new Set();
    if (!process.env.ORCH_NO_AUTH) {
      try {
        const bin = opencodeBin();
        const auth = authFile ? fs.readFileSync(authFile, "utf8") : execFileSync(bin.cmd, [...(bin.pre || []), "auth", "list"], { encoding: "utf8", timeout: 60000, stdio: ["ignore", "pipe", "ignore"] });
        connectedProviderIds = new Set(connectedProviders(auth, [...live]));
      } catch {
        // auth unavailable, skip
      }
    }
    // Candidate free models:
    // (a) -free suffix (any provider in live list)
    // (b) :free suffix (any provider in live list)
    // (c) zero-cost models from catalog (cost.input === 0 && cost.output === 0) that are in live list
    // Skip providers with no providers.json entry and no auth (catalog-only providers)
    const candidates = [];
    for (const id of live) {
      if (!id.includes("/")) continue;
      const prov = id.split("/")[0];
      const rest = id.slice(prov.length + 1);
      // Check if provider has a decision in providers.json or is connected
      const hasDecision = !!providerPolicy(id);
      const isConnected = connectedProviderIds.has(prov);
      // Skip catalog-only providers (no decision, no auth) — SEED_PROVIDERS exempt
      if (!hasDecision && !isConnected && !SEED_PROVIDERS.has(prov)) continue;

      const isFreeSuffix = rest.endsWith("-free");
      const isFreeColon = rest.endsWith(":free");
      const isZeroCost = isZeroCostCatalog(id, catalog);
      const isFreeOnlyProvider = providerPolicy(id)?.decision === "free-only";

      if (isFreeSuffix || isFreeColon || isZeroCost || isFreeOnlyProvider) {
        candidates.push(id);
      }
    }
    // Determine state for each candidate (precedence: blocked > in-chain > down > unused)
    const freeInv = readFreeInventory();
    let counts = { live: 0, in_chains: 0, blocked: 0, unused: 0, down: 0 };
    const modelDetails = [];
    for (const m of candidates.sort()) {
      counts.live++;
      let state, agents = [], reason = null, probeInfo = null;
      const down = isDown(m);
      if (!modelAllowed(m)) {
        state = "blocked";
        reason = policyReason(m);
        counts.blocked++;
      } else if (chainModels.has(m)) {
        state = "in-chain";
        for (const [role, chain] of Object.entries(CHAINS)) {
          for (const a of chain) {
            if (agentModel(a) === m) agents.push(a);
          }
        }
        counts.in_chains++;
      } else if (down) {
        state = "down";
        reason = `${down.reason} until ${down.until}`;
        counts.down++;
        probeInfo = freeInv[m] ? { ok: freeInv[m].ok, seconds: freeInv[m].seconds, class: freeInv[m].class, at: freeInv[m].at } : { ok: false, class: "never probed" };
      } else {
        state = "unused";
        counts.unused++;
        probeInfo = freeInv[m] ? { ok: freeInv[m].ok, seconds: freeInv[m].seconds, class: freeInv[m].class, at: freeInv[m].at } : { ok: false, class: "never probed" };
      }
      modelDetails.push({ model: m, state, agents, reason, probe: probeInfo, trainsOnData: hasTrainsOnData(m), vision: isVisionCapable(m, catalog), nemotronRateLimit: getNemotronRateLimitNote(m) });
    }
    report.free_inventory = { counts, models: modelDetails };
  }

  // --- Probe free models ---
  if (probeFree && live && report.free_inventory) {
    const unusedModels = report.free_inventory.models
      .filter((m) => m.state === "unused")
      .map((m) => m.model)
      .sort();
    const toProbe = unusedModels.slice(0, 12);
    const notProbed = unusedModels.slice(12);
    const freeInv = readFreeInventory();
    for (const m of toProbe) {
      const result = await probeModel(m);
      const cls = classifyProbe(result.errors, m);
      freeInv[m] = { ok: result.ok, seconds: result.seconds, class: cls, at: new Date().toISOString() };
    }
    // Do NOT persist an entry for a model past the probe cap: the file holds measured results only, and an un-probed
    // model is printed as "never probed" at output time (the report marks it "not probed (cap 12)" below). Persisting
    // `never probed` here contradicted that and made an old inventory look like a set of failed probes.
    writeFreeInventory(freeInv);
    // Re-read to include probe results in report
    const updatedInv = readFreeInventory();
    for (const md of report.free_inventory.models) {
      if (md.state === "unused" && updatedInv[md.model]) {
        md.probe = { ok: updatedInv[md.model].ok, seconds: updatedInv[md.model].seconds, class: updatedInv[md.model].class, at: updatedInv[md.model].at };
      } else if (md.state === "down" && updatedInv[md.model]) {
        md.probe = { ok: updatedInv[md.model].ok, seconds: updatedInv[md.model].seconds, class: updatedInv[md.model].class, at: updatedInv[md.model].at };
      }
    }
    // Mark capped models in report for output
    for (const m of notProbed) {
      const md = report.free_inventory.models.find(x => x.model === m);
      if (md) md.probe = { ok: false, seconds: 0, class: "not probed (cap 12)", at: new Date().toISOString() };
    }
  }

  // --- Role health checks ---
  // Local usage ledger (bin/usage.mjs): pools under the headroom floor are
  // skipped like down pools, so dispatch prefers pools with room. Free and
  // unmetered models are never skipped for headroom. External spend is
  // invisible, so this is preference only — quota failures still mark down.
  const usageLimits = loadLimits();
  const usage = collectUsage(undefined, Date.now(), usageLimits);
  const floor = (usageLimits.low_headroom_pct ?? LOW_HEADROOM_PCT_DEFAULT) / 100;
  if (usageLimits.missing) report.notes.push("usage: no usage-limits.json — Go monthly assumed $60; create one to set your plan cap");
  const probed = new Map();
  // Quota marks are re-tested on --probe instead of being trusted until they expire: a quota's retry-after can be
  // days away (a monthly cap), and a renewed or topped-up plan never tells us. One re-test per mark key per run, so a
  // provider-wide mark that is still real costs one call, not one per model on that provider.
  const retested = new Set();
  for (const [role, chain] of Object.entries(CHAINS)) {
    const rows = [];
    for (const agent of chain) {
      const model = agentModel(agent);
      if (!model) {
        rows.push({ agent, model: null, state: "not-installed" });
        continue;
      }
      if (live && !live.has(model)) markDown(model, { reason: "unavailable", ms: 24 * 3600_000, detail: "missing from `opencode models`" });
      let down = isDown(model);
      const canProbe = probeModels && (probeAll || !EXPENSIVE_ROLES.has(role));
      let retestKey = null;
      if (down && canProbe && down.reason === "quota" && !retested.has(down.key) && !probed.has(model)) {
        retestKey = down.key;
        retested.add(retestKey);
        down = null; // fall through to the probe below; success clears the mark (model and provider-wide)
      }
      if (!down && canProbe) {
        if (!probed.has(model)) probed.set(model, await probe(agent));
        const p = probed.get(model);
        if (p.ok) markUp(model);
        else {
          const cls = classify(p.errors, model);
          if (cls) markDown(model, { ...cls, detail: p.errors[0] || "" });
          else {
            rows.push({ agent, model, state: "probe-failed", detail: (p.errors[0] || `exit ${p.code}`).slice(0, 160) });
            // An unclassified failure says nothing about the quota: let the next model under this mark re-test it.
            if (retestKey) retested.delete(retestKey);
            continue; // reported as probe-failed (a quota mark it was re-testing stays, so it is skipped either way)
          }
        }
        down = isDown(model);
      }
      let row = down
        ? { agent, model, state: "down", detail: `${down.reason} until ${down.until}` }
        : { agent, model, state: "healthy", vision: isVisionCapable(model, catalog) };
      if (row.state === "healthy" && usage.pools) {
        const cut = model.indexOf("/");
        const h = cut === -1 ? null : poolHeadroom(usage, model.slice(0, cut), model.slice(cut + 1));
        if (h) {
          row.headroom = Math.round(h.headroom * 100) / 100;
          if (h.headroom < floor) {
            row.state = "low-headroom";
            row.detail = `headroom ${Math.round(h.headroom * 100)}% (${h.label}) under the ${Math.round(floor * 100)}% floor`;
          }
        }
      }
      rows.push(row);
    }
    const use = rows.find((r) => r.state === "healthy");
    report.roles[role] = { use: use ? use.agent : null, chain: rows };
  }
  report.usage = usage.pools ? { floor_pct: Math.round(floor * 100), ...usage } : usage;
  fs.mkdirSync(path.dirname(stampPath()), { recursive: true });
  fs.writeFileSync(stampPath(), JSON.stringify({ ...report, pool_health: readHealth() }, null, 2) + "\n");
  return report;
}

/** The `under` pace prefix of a role line: `cc-<role> (pace UNDER), fallback ` for a PACE_POLICY role whose cc agent
 *  is not down (pool-health isDown) — senior not while Fable is over; "" otherwise (today's line). */
export function pacePrefixFor(role, pace, down = isDown) {
  if (pace?.state !== "under" || !Object.hasOwn(PACE_POLICY, role)) return "";
  if (role === "senior" && pace.fable?.state === "over") return "";
  const cc = PACE_POLICY[role];
  let isOut = false;
  try {
    isOut = !!down(cc);
  } catch {
    isOut = false;
  }
  return isOut ? "" : `${cc} (pace UNDER), fallback `;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const argv = process.argv.slice(2);
  const flag = (k) => argv.includes(k);
  const val = (k) => (argv.includes(k) ? argv[argv.indexOf(k) + 1] : undefined);
  const stale = val("--if-stale");
  const decideAt = argv.indexOf("--decide");
  if (decideAt >= 0) {
    const [id, decision] = [argv[decideAt + 1], argv[decideAt + 2]];
    const allow = (val("--allow") || "").split(",").map((g) => g.trim()).filter(Boolean);
    if (!id || !["routed", "ignored", "free-only"].includes(decision) || (decision === "free-only" && !allow.length)) {
      console.error("usage: router-health --decide <id> routed|ignored [--note <text>]\n       router-health --decide <id> free-only --allow \"<glob>[,<glob>...]\"");
      process.exit(2);
    }
    try {
      writeDecision(id, decision, val("--note") || "", decision === "free-only" ? allow : undefined);
    } catch (e) {
      console.error(`router-health: ${e.message}`);
      process.exit(2);
    }
    console.log(`${id}: ${decision}${decision === "free-only" ? ` (allow ${allow.join(", ")})` : ""}`);
    process.exit(0);
  }
  // Pace first: before the --if-stale early return, so a fresh skip still shows it.
  const pace = readPace();
  if (!flag("--json")) {
    console.log(`pace: ${paceStatusLine(pace)}`);
    if (pace.state === "over") {
      console.log("pace: OVER — conserve: no Fable senior unless guarded; scouts haiku");
      console.log("pace: OVER — critic and senior via oc-worker --role, not Agent(critic|senior) unless guarded");
    }
  }
  const mf = val("--models-file");
  const live = liveModels(mf);
  // Detection is cheap, so it runs even when --if-stale skips the probes.
  const detected = detectNewProviders({ authFile: val("--auth-file"), live });
  const printNew = () => {
    for (const p of detected.providers) console.log(`NEW PROVIDER: ${p.id} — connected, ${p.models} models, not in any chain. Evaluate (probe + bake-off) or ignore: router-health --decide ${p.id} routed|ignored${p.models === 0 ? " (no models matched this provider id — check the name mapping)" : ""}`);
    if (detected.note) console.log(`note: ${detected.note}`);
    for (const [id, e] of Object.entries(readDecisions())) if (e.decision === "free-only") console.log(`free-only provider: ${id} — allowed models: ${(e.allow || []).join(", ")}`);
  };
  if (stale) {
    try {
      const age = Date.now() - Date.parse(JSON.parse(fs.readFileSync(stampPath(), "utf8")).checked_at);
      if (age < Number(stale) * 3600_000) {
        console.log(`router-health: fresh (checked ${Math.round(age / 60000)} min ago) — skipped`);
        printNew();
        try { // keep the stamp's new_providers current without re-probing
          const stamp = JSON.parse(fs.readFileSync(stampPath(), "utf8"));
          writeFileAtomic(stampPath(), JSON.stringify({ ...stamp, new_providers: detected.providers }, null, 2) + "\n");
        } catch {}
        process.exit(0);
      }
    } catch {}
  }
  const report = await check({ probeModels: flag("--probe") || flag("--probe-all"), probeAll: flag("--probe-all"), models: live, newProviders: detected.providers, free: flag("--free"), probeFree: flag("--probe-free"), authFile: val("--auth-file") });
  if (flag("--json")) console.log(JSON.stringify({ ...report, pace }, null, 2));
  else {
    for (const [role, r] of Object.entries(report.roles)) {
      const why = r.chain.filter((c) => c.state !== "healthy").map((c) => `${c.agent}: ${c.state}${c.detail ? ` (${c.detail})` : ""}`);
      const visionInfo = r.use ? (r.chain.find(c => c.agent === r.use)?.vision ? " 👁" : "") : "";
      const pacePrefix = pacePrefixFor(role, pace);
      console.log(`${role.padEnd(14)} use ${pacePrefix}${r.use || "NONE — no healthy agent in chain"}${visionInfo}${why.length ? `   [skipped ${why.join("; ")}]` : ""}`);
    }
    for (const n of report.notes) console.log(`note: ${n}`);
    // Print free inventory summary ALWAYS (when live available), details only with --free/--probe-free
    if (report.free_inventory) {
      if (report.free_inventory.unavailable) {
        console.log("free inventory: unavailable (opencode models failed)");
      } else {
        const c = report.free_inventory.counts;
        console.log(`free models: ${c.live} live, ${c.in_chains} in chains, ${c.blocked} blocked by policy, ${c.unused} unused, ${c.down} down — router-health --free`);
        if (flag("--free") || flag("--probe-free")) {
          for (const m of report.free_inventory.models) {
            let line = `${m.model}  `;
            if (m.state === "in-chain") line += `in-chain ${m.agents.join(",")}`;
            else if (m.state === "blocked") line += `blocked (${m.reason})`;
            else if (m.state === "down") line += `down (${m.reason})`;
            else line += "unused";
            if (m.trainsOnData) line += " trains-on-data";
            if (m.vision) line += " 👁";
            if (m.nemotronRateLimit) line += ` (${m.nemotronRateLimit})`;
            if (m.probe) {
              if (m.probe.class === "never probed") line += " — never probed";
              else if (m.probe.class.startsWith("not probed")) line += ` — ${m.probe.class}`;
              else if (m.probe.ok) line += ` — ok ${m.probe.seconds.toFixed(1)}s`;
              else line += ` — fail ${m.probe.class}`;
            }
            console.log(line);
          }
          if (report.free_inventory.models.some((m) => m.state === "unused" && m.probe?.ok)) {
            console.log("promote: /frood-model-router-refresh + owner approval");
          }
        }
      }
    }
    printNew();
  }
  process.exit(Object.values(report.roles).every((r) => r.use) ? 0 : 1);
}
