#!/usr/bin/env node
// Rename an OpenCode session tab: PATCH the background server (same discovery and
// Basic auth the `opencode api` subcommand uses), so connected UIs refresh the tab
// instead of showing the auto-generated title. Claude Code tabs are named by the
// orchestrator-handoff.js hook (sessionTitle); this is the OpenCode equivalent.
//
//   node bin/session-title.mjs --title "[video-studio] sales-team-toolbox: m3 — pipeline"
//   node bin/session-title.mjs --session ses_abc123 --title "desk: video-studio"
//   node bin/session-title.mjs --for-stream video-studio   (rename the stream's session to its current work)
//
// --for-stream resolves the stream's holder (claim.session, else held_session) and renames
// it to the stream's title, but only when the current title does not already name the stream.
// Session defaults to $OPENCODE_SESSION_ID. Exit 0 renamed (or already correct), 1 server/rename
// failed, 2 usage error. SERVICE_JSON overrides the state file (tests).
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { readStream, streamTitle } from "./handoff.mjs";

export function serviceFile() {
  if (process.env.SERVICE_JSON) return process.env.SERVICE_JSON;
  const state = process.env.XDG_STATE_HOME ?? path.join(os.homedir(), ".local", "state");
  return path.join(state, "opencode", "service.json");
}

export function sessionId(opts) {
  return opts.session ?? process.env.OPENCODE_SESSION_ID ?? "";
}

export async function renameSession(baseUrl, password, id, title) {
  const res = await fetch(new URL(`/api/session/${id}`, baseUrl).href, {
    method: "PATCH",
    headers: {
      authorization: "Basic " + Buffer.from(`opencode:${password}`).toString("base64"),
      "content-type": "application/json",
    },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`PATCH /api/session/${id}: HTTP ${res.status}`);
}

async function getTitle(baseUrl, password, id) {
  const res = await fetch(new URL(`/api/session/${id}`, baseUrl).href, {
    headers: { authorization: "Basic " + Buffer.from(`opencode:${password}`).toString("base64") },
  });
  if (res.status === 404) return null; // session gone: nothing to rename
  if (!res.ok) throw new Error(`GET /api/session/${id}: HTTP ${res.status}`);
  return (await res.json())?.data?.title ?? (await res.json())?.title ?? null;
}

/**
 * Rename a stream's holder to the stream's current work — but only when the tab
 * does not already name the stream. Returns "renamed" | "current" | "skipped".
 * Never throws: callers (desk-check's 5-minute sweep) must not fail on a cosmetic step.
 */
export async function syncStreamTitle(streamName, svc) {
  let s;
  try {
    s = readStream(streamName);
  } catch {
    return "skipped";
  }
  if (!s) return "skipped";
  const holder = s.claim?.session || s.held_session || null;
  if (typeof holder !== "string" || !holder) return "skipped";
  const want = streamTitle({ ...s, name: streamName });
  if (!want) return "skipped";
  try {
    const cur = await getTitle(svc.url, svc.password, holder);
    if (cur == null) return "skipped";
    if (String(cur).startsWith(`[${streamName}]`)) return "current";
    await renameSession(svc.url, svc.password, holder, want);
    return "renamed";
  } catch {
    return "skipped";
  }
}

/** Every active stream whose holder tab does not name it. For the desk-check sweep. */
export async function syncAllStreamTitles(svc, listStreams) {
  const out = [];
  for (const s of listStreams()) {
    if (!s || s.status === "parked" || s.status === "done") continue;
    const r = await syncStreamTitle(s.name, svc);
    if (r === "renamed") out.push(s.name);
  }
  return out;
}

export function readService() {
  const file = serviceFile();
  try {
    const svc = JSON.parse(fs.readFileSync(file, "utf8"));
    if (!svc?.url || !svc?.password) return { error: `service file ${file} has no url/password` };
    return { svc };
  } catch {
    return { error: `cannot read service file ${file} (is the background service running?)` };
  }
}

export function parseArgs(argv) {
  const opts = {};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--title") opts.title = argv[++i] ?? "";
    else if (argv[i] === "--session") opts.session = argv[++i] ?? "";
    else if (argv[i] === "--for-stream") opts.forStream = argv[++i] ?? "";
    else return { error: `unknown flag ${argv[i]} (usage: session-title.mjs --title "..." [--session <id>] | --for-stream <name>)` };
  }
  if (opts.forStream) {
    if (opts.title || opts.session) return { error: "--for-stream takes no --title/--session" };
    return { opts };
  }
  if (!opts.title) return { error: "usage: session-title.mjs --title \"...\" [--session <id>] | --for-stream <name>" };
  return { opts };
}

async function main(argv) {
  const parsed = parseArgs(argv);
  if (parsed.error) {
    console.error(`session-title: ${parsed.error}`);
    return 2;
  }
  const { error, svc } = readService();
  if (error) {
    console.error(`session-title: ${error}`);
    return 1;
  }
  if (parsed.opts.forStream) {
    const r = await syncStreamTitle(parsed.opts.forStream, svc);
    if (r === 'renamed') console.log(`session-title: stream ${parsed.opts.forStream} tab renamed to its current work`);
    else console.log(`session-title: stream ${parsed.opts.forStream} tab ${r} (nothing to do)`);
    return 0; // a cosmetic step never fails the caller
  }
  const id = sessionId(parsed.opts);
  if (!id) {
    console.error("session-title: no session id ($OPENCODE_SESSION_ID empty and no --session)");
    return 2;
  }
  try {
    await renameSession(svc.url, svc.password, id, parsed.opts.title);
  } catch (e) {
    console.error(`session-title: ${e.message}`);
    return 1;
  }
  console.log(`session-title: renamed ${id} to "${parsed.opts.title}"`);
  return 0;
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname);
if (isMain) process.exit(await main(process.argv.slice(2)));
