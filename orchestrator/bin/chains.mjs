// One source of truth for every worker/critic/scout/senior/orchestrator chain.
// Both `bin/router-health.mjs` and `bin/oc-worker.mjs` import CHAINS from here so
// there is a single chain definition and no import cycle between them.
//
// Oc-worker `--role <name>` expands to `--agent <first>` --fallback <rest>` from CHAINS[role].
// See orchestrator/rules/01-orchestrator-models.md and bin/check-routing.mjs for how
// hand-typed dispatch chains are linted against this file.
export const CHAINS = {
  // Cross-provider diversity at positions 1-2 prevents single-provider quota from killing the chain
  // Routine tickets: Nvidia first (no monthly quota — only per-minute 429s, which oc-worker
  // resumes rather than skips). Never hand-type this chain; use `--role worker`.
  worker: ["worker-nvidia", "worker", "worker-burst", "worker-alt", "worker-free"],
  // worker-strong: add Nvidia + Zen free fallbacks (was all-paid, dead when Go+CmdC cap) — unchanged
  "worker-strong": ["worker-strong", "worker-burst", "worker-nvidia", "worker-alt", "worker-free"],
  // critic: Go Haiku as position 2 (cross-family vs CmdC Haiku pos 1)
  critic: ["critic", "critic-go", "critic-alt", "critic-nvidia", "critic-free"],
  // scout: add Nvidia + CmdC fallbacks (was Zen-only, dead when Zen caps)
  scout: ["scout", "worker-nvidia", "critic-nvidia", "worker-alt"],
  senior: ["senior", "senior-alt", "senior-nvidia", "senior-free"],
  // orchestrator: add Nvidia (was Go→CmdC→Zen only, no Nvidia)
  orchestrator: ["orchestrator", "orchestrator-alt", "orchestrator-nvidia", "orchestrator-free"],
};

export function chainFor(role) {
  const chain = CHAINS[role];
  if (!chain) throw new Error(`unknown role ${role}; known roles: ${Object.keys(CHAINS).join(", ")}`);
  return chain;
}

export default CHAINS;
