// Make every child process this Node process starts hide its console window (Windows only).
//
// Why: a process with no console of its own (the OpenCode service, a detached dashboard rebuild, a test runner
// started by one) makes each console child it spawns — git, node, pwsh — open a NEW visible window that steals
// focus. Found 2026-11-12: a worker's `npm test` flashed dozens of windows and blocked the owner's desktop.
//
// Import it first (side effect), or preload it: `node --import ./bin/no-window.mjs ...`. Explicit
// `windowsHide: false` in a call still wins.
import cp from "node:child_process";
import { syncBuiltinESMExports } from "node:module";

const PATCHED = Symbol.for("orchestrator.noWindow");

if (process.platform === "win32" && !cp[PATCHED]) {
  const withHide = (opts) => (opts && typeof opts === "object" ? { windowsHide: true, ...opts } : { windowsHide: true });
  // Signatures: fn(cmd, args?, options?, cb?) — the options object is the first plain object after cmd.
  const wrap = (name) => {
    const orig = cp[name];
    cp[name] = function patched(cmd, ...rest) {
      let i = rest.findIndex((x) => x && typeof x === "object" && !Array.isArray(x));
      if (i === -1) {
        // insert options after args array (or right after cmd when there is no args array)
        i = Array.isArray(rest[0]) ? 1 : 0;
        if (typeof rest[i] === "function" || rest[i] === undefined) rest.splice(i, 0, {});
        else rest.splice(i, 0, {});
      }
      rest[i] = withHide(rest[i]);
      return orig.call(this, cmd, ...rest);
    };
  };
  for (const name of ["spawn", "spawnSync", "execFile", "execFileSync", "exec", "execSync", "fork"]) wrap(name);
  cp[PATCHED] = true;
  syncBuiltinESMExports(); // so `import { spawnSync } from "node:child_process"` elsewhere sees the patch
}
