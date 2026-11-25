#!/usr/bin/env node
// Tiny settings store for orchestrator preferences.
//
//   node bin/settings.mjs get <key>      prints the effective value, exit 0 (unknown key: exit 2)
//   node bin/settings.mjs set <key> <true|false>   writes atomically, exit 0 (unknown key / non-boolean: exit 2)
//   node bin/settings.mjs list           prints the effective settings as JSON, exit 0
//
// State: <ORCH_HOME || ~>/.config/orchestrator/settings.json
//   Missing or unreadable file  -> the defaults apply (every install is on by default).
//   Corrupt file                -> the defaults apply, exit 0.
//
// Defaults (from code): { "archive_nested_sessions": true }
//   `install.mjs` is intentionally not edited: the default ships from here.
//
// Exports `getSetting(key)` for other scripts.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// Known keys and their defaults. Adding a key here turns it on by default for
// every install without touching install.mjs.
export const DEFAULTS = Object.freeze({ archive_nested_sessions: true });

export function settingsFile() {
  return path.join(process.env.ORCH_HOME || os.homedir(), ".config", "orchestrator", "settings.json");
}

// Read the file, or {} when missing, unreadable or corrupt: defaults apply.
export function readSettings() {
  try {
    const parsed = JSON.parse(fs.readFileSync(settingsFile(), "utf8"));
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
    return {};
  } catch {
    return {};
  }
}

// Effective value for a known key: the file's value, else the default.
// Unknown keys return undefined (the CLI treats them as an error, exit 2).
export function getSetting(key) {
  if (!(key in DEFAULTS)) return undefined;
  const file = readSettings();
  return key in file ? file[key] : DEFAULTS[key];
}

// All effective settings (defaults overlaid with the file's known keys).
export function effectiveSettings() {
  const out = {};
  for (const key of Object.keys(DEFAULTS)) out[key] = getSetting(key);
  return out;
}

function writeSettings(key, value) {
  const file = settingsFile();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const current = readSettings();
  current[key] = value;
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(current, null, 2) + "\n", { encoding: "utf8" });
  fs.renameSync(tmp, file); // atomic on the same filesystem
}

function isBooleanString(v) {
  return v === "true" || v === "false";
}

async function main(argv) {
  const [cmd, key, value] = argv;
  switch (cmd) {
    case "get":
      if (!key) {
        console.error("usage: settings.mjs get <key>");
        return 2;
      }
      if (!(key in DEFAULTS)) {
        console.error(`settings: unknown key "${key}"`);
        return 2;
      }
      console.log(String(getSetting(key)));
      return 0;
    case "set":
      if (!key || value === undefined) {
        console.error('usage: settings.mjs set <key> <true|false>');
        return 2;
      }
      if (!(key in DEFAULTS)) {
        console.error(`settings: unknown key "${key}"`);
        return 2; // file unchanged
      }
      if (!isBooleanString(value)) {
        console.error(`settings: value for "${key}" must be true or false, got "${value}"`);
        return 2; // file unchanged
      }
      writeSettings(key, value === "true");
      return 0;
    case "list":
      console.log(JSON.stringify(effectiveSettings()));
      return 0;
    default:
      console.error('usage: settings.mjs <get <key> | set <key> <true|false> | list>');
      return 2;
  }
}

const isMain =
  process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname);
if (isMain) process.exit(await main(process.argv.slice(2)));
