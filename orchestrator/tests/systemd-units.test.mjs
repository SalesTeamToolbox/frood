// The systemd units ship as templates (@NODE@/@REPO@/@BY@) rendered by
// ops/systemd/install.mjs. Hermetic: assert the templates supervise correctly and
// every placeholder they use is one the installer fills.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "ops", "systemd");

test("daemon unit supervises _run in the foreground with restarts", () => {
  const svc = fs.readFileSync(path.join(DIR, "orchestrator-desk-daemon.service"), "utf8");
  assert.match(svc, /^Type=simple$/m);
  assert.match(svc, /^Restart=always$/m);
  assert.match(svc, /^RestartSec=\d+$/m);
  assert.match(svc, /^RestartPreventExitStatus=3$/m); // exit 3 = live session owns the lock
  assert.match(svc, /^ExecStart=@NODE@ @REPO@\/bin\/desk\.mjs daemon _run --by @BY@ --interval \d+$/m);
  assert.doesNotMatch(svc, /daemon start/); // start double-forks: wrong under a supervisor
});

test("every template placeholder is one install.mjs fills", () => {
  const installer = fs.readFileSync(path.join(DIR, "install.mjs"), "utf8");
  const filled = new Set([...installer.matchAll(/"(@[A-Z]+@)"/g)].map((m) => m[1]));
  for (const f of fs.readdirSync(DIR)) {
    if (!f.endsWith(".service")) continue;
    const text = fs.readFileSync(path.join(DIR, f), "utf8");
    for (const m of text.matchAll(/@[A-Z]+@/g)) {
      assert.ok(filled.has(m[0]), `${f} uses ${m[0]}, which install.mjs does not fill`);
    }
  }
  assert.ok(filled.size > 0);
});

test("desk-check timer still pages every 5 minutes", () => {
  const timer = fs.readFileSync(path.join(DIR, "orchestrator-desk-check.timer"), "utf8");
  assert.match(timer, /^OnCalendar=\*:0\/5$/m);
});
