// cc-pacing M6: the handoff card template carries the pace. `commands/frood-orchestrator.md`'s card fence has a
// `Pace:` line after `Done:` and a `Reset:` line after `Pace:`, every card line fits 100 chars, the prose states
// the omit rules, and `commands/frood-gauntlet.md`'s handoff-card bullet names `Pace:`.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CMD = (n) => fs.readFileSync(path.join(HERE, "..", "commands", n), "utf8");

// The ``` fence whose body holds the `── HANDOFF` header line.
function cardFence(md) {
  const lines = md.split(/\r?\n/);
  const opens = [];
  for (let i = 0; i < lines.length; i++) if (/^\s*```\s*$/.test(lines[i])) opens.push(i);
  for (let k = 0; k + 1 < opens.length; k += 2) {
    const body = lines.slice(opens[k] + 1, opens[k + 1]);
    if (body.some((l) => l.includes("── HANDOFF"))) return { body, after: lines.slice(opens[k + 1] + 1).join("\n") };
  }
  return null;
}

test("orchestrator card: Pace: after Done:, Reset: after Pace:, every line ≤ 100 chars", () => {
  const card = cardFence(CMD("frood-orchestrator.md"));
  assert.ok(card, "handoff card fence found");
  const idx = (label) => card.body.findIndex((l) => l.trim().startsWith(label));
  const done = idx("Done:");
  const pace = idx("Pace:");
  const reset = idx("Reset:");
  assert.ok(done >= 0 && pace >= 0 && reset >= 0, "Done:, Pace: and Reset: lines present");
  assert.equal(pace, done + 1, "Pace: right after Done:");
  assert.equal(reset, pace + 1, "Reset: right after Pace:");
  for (const l of card.body) assert.ok(l.length <= 100, `card line over 100 chars: ${l}`);
});

test("orchestrator card prose: omit rules for Pace:/Reset: and info-only (never NEEDS YOU by itself)", () => {
  const { after } = cardFence(CMD("frood-orchestrator.md"));
  const prose = after.slice(0, after.indexOf("\n4. ")).replace(/\s+/g, " ");
  assert.match(prose, /cc-pace\.mjs status/);
  assert.match(prose, /cc-pace\.mjs advise/);
  assert.match(prose, /omit it when the pace is off/);
  assert.match(prose, /omit it when advise prints nothing/);
  assert.match(prose, /does NOT by itself make the status NEEDS YOU/);
  assert.match(prose, /Omit a line only when it would be `none`/);
});

test("gauntlet handoff-card bullet names the Pace: line", () => {
  const bullet = CMD("frood-gauntlet.md").split(/\r?\n- /).find((b) => b.startsWith("End the message with the handoff card"));
  assert.ok(bullet, "handoff-card bullet found");
  assert.match(bullet, /`Pace:`/);
  assert.match(bullet, /`Reset:`/);
});
