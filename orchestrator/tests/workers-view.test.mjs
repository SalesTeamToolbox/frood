import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "workers-view.mjs");
const FIX = path.join(HERE, "fixtures", "workers-view");
const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

// scenario: { runs, board: [{id, stage, session?, worker?}], dispatch: "text" | "FAIL", pace?: "line" } (runs/board "FAIL" = child fails)
function view(s, args = []) {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "wv-"));
  CLEAN.push(d);
  const tdir = path.join(d, ".opencode", "board", "tickets");
  fs.mkdirSync(tdir, { recursive: true });
  const put = (name, v) => {
    const p = path.join(d, name);
    fs.writeFileSync(p, typeof v === "string" ? v : JSON.stringify(v));
    return p;
  };
  const env = { ...process.env, WV_OCW_CLI: path.join(FIX, "ocw.mjs"), WV_BOARD_CLI: path.join(FIX, "board.mjs"), WV_DISPATCH_CLI: path.join(FIX, "dispatch.mjs") };
  env.WV_FIX_OCW = s.runs === "FAIL" ? "FAIL" : put("runs.json", s.runs ?? []);
  const board = s.board ?? [];
  env.WV_FIX_BOARD = board === "FAIL" ? "FAIL" : put("board.json", board.map(({ worker, ...row }) => row));
  for (const t of board === "FAIL" ? [] : board) fs.writeFileSync(path.join(tdir, `${t.id}.json`), JSON.stringify({ assignment: { worker: t.worker ?? null } }));
  env.WV_FIX_DISPATCH = s.dispatch === "FAIL" ? "FAIL" : put("dispatch.txt", s.dispatch ?? "");
  Object.assign(env, s.env);
  // A pace script that does not exist -> skipped; else a one-line script.
  env.WV_PACE_CLI = path.join(d, "no-pace.mjs");
  if (s.pace) {
    fs.writeFileSync(env.WV_PACE_CLI, `console.log(${JSON.stringify(s.pace)});`);
  }
  const r = spawnSync(process.execPath, [BIN, "--repo", d, ...args.map((a) => (a === "@html" ? path.join(d, "out.html") : a))], { env, encoding: "utf8", timeout: 60_000 });
  return { ...r, dir: d };
}
const run = (o) => ({ agent: "worker", state: "RUNNING", elapsed: "3m", outAge: "10s", detail: "", title: "orch worker x", stream: null, ...o });
const json = (s) => JSON.parse(view(s, ["--json"]).stdout);

test("0 runs: says so, exits 0", () => {
  const r = view({});
  assert.equal(r.status, 0);
  assert.match(r.stdout, /no live runs/);
  assert.deepEqual(json({}).runs, []);
});

test("1 run: row carries oc-worker's state verbatim, ticket and round from pid / out", () => {
  const s = {
    runs: [run({ pid: 111, out: "/o/worker-r2.md", state: "QUIET", detail: "silent 25m past idle-min 20m" })],
    board: [{ id: "t-a", stage: "working", session: "local_abc", worker: { pid: 111, out_path: "/o/worker-r2.md" } }],
  };
  const d = json(s);
  assert.equal(d.runs.length, 1);
  assert.equal(d.runs[0].state, "QUIET");
  assert.equal(d.runs[0].ticket, "t-a");
  assert.equal(d.runs[0].round, 2);
  assert.equal(d.runs[0].session_link, "claude://claude.ai/epitaxy/local_abc");
  assert.deepEqual(d.no_live_run, []);
  assert.match(view(s).stdout, /QUIET\tworker\tt-a\t2\t3m\t10s\t111\tclaude:\/\/claude.ai\/epitaxy\/local_abc/);
});

test("6 runs: all listed, every vocabulary state kept", () => {
  const states = ["RUNNING", "STARTING", "QUIET", "OVERDUE", "HEARTBEAT-STALE", "STALE"];
  const d = json({ runs: states.map((state, i) => run({ pid: 200 + i, out: `/o/w${i}.md`, state })) });
  assert.deepEqual(d.runs.map((r) => r.state), states);
  assert.deepEqual(d.runs.map((r) => r.round), Array(6).fill(null));
  assert.equal(d.runs[0].ticket, null);
  assert.match(view({ runs: [run({ pid: 1, out: "/o/w.md" })] }).stdout, /RUNNING\tworker\t—\t—/);
});

test("working ticket with no live run shows NO LIVE RUN", () => {
  const s = { board: [{ id: "t-dead", stage: "working", owner: "o", worker: { pid: 999, out_path: "/gone.md" } }, { id: "t-nowk", stage: "working" }] };
  const d = json(s);
  assert.deepEqual(d.no_live_run.map((n) => n.ticket), ["t-dead", "t-nowk"]);
  assert.ok(d.no_live_run.every((n) => n.state === "NO LIVE RUN"));
  assert.match(view(s).stdout, /NO LIVE RUN\tt-dead/);
});

test("join is by pid / out_path, never by title", () => {
  const s = {
    runs: [run({ pid: 5, out: "/o/a-r1.md", title: "t-b" }), run({ pid: 6, out: "/o/zzz-r3.md", title: "t-b" })],
    board: [
      { id: "t-b", stage: "working", worker: { pid: 77, out_path: "/o/zzz-r3.md" } }, // matches run 2 by out_path only
      { id: "t-c", stage: "working", worker: { pid: 5, out_path: "/else.md" } }, // matches run 1 by pid only
    ],
  };
  const d = json(s);
  assert.equal(d.runs[0].ticket, "t-c");
  assert.equal(d.runs[1].ticket, "t-b");
  assert.deepEqual(d.no_live_run, []);
  // a title equal to a ticket id with no pid/out match stays unmatched
  const d2 = json({ runs: [run({ pid: 9, out: "/x.md", title: "t-b" })], board: [{ id: "t-b", stage: "working", worker: { pid: 1, out_path: "/y.md" } }] });
  assert.equal(d2.runs[0].ticket, null);
  assert.equal(d2.no_live_run[0].ticket, "t-b");
});

test("round is parsed from -r<N> in the out filename", () => {
  const rounds = (outs) => json({ runs: outs.map((out, i) => run({ pid: 300 + i, out })) }).runs.map((r) => r.round);
  assert.deepEqual(rounds(["/o/worker-r2.md", "/o/critic-r10.md", "/o/worker.md", "/o/r3/worker.md", undefined]), [2, 10, null, null, null]);
});

test("a failing child degrades only its own section", () => {
  const board = [{ id: "t-q", stage: "queued" }];
  const noRuns = view({ runs: "FAIL", board, dispatch: "held: t-q — waiting on t-x\n" });
  assert.equal(noRuns.status, 0);
  assert.match(noRuns.stdout, /runs: unavailable/);
  assert.match(noRuns.stdout, /held: t-q — waiting on t-x/);
  const noBoard = view({ runs: [run({ pid: 1, out: "/o/w-r1.md" })], board: "FAIL" });
  assert.match(noBoard.stdout, /tickets: unavailable/);
  assert.match(noBoard.stdout, /RUNNING\tworker/);
  const j = json({ runs: "FAIL" });
  assert.equal(j.runs, null);
  assert.ok(j.errors.runs);
  assert.deepEqual(j.no_live_run, []);
});

test("held tickets show their reason; dispatch failure prints 'held: unavailable'", () => {
  const board = [{ id: "t-q", stage: "queued" }, { id: "t-r", stage: "queued" }];
  const ok = view({ board, dispatch: "group 1: t-r\nheld: t-q — waiting on t-r (in flight, shared file: t-r: a.js)\n" });
  assert.match(ok.stdout, /held: t-q — waiting on t-r \(in flight, shared file: t-r: a\.js\)/);
  assert.doesNotMatch(ok.stdout, /group 1/);
  assert.match(view({ board, dispatch: "FAIL" }).stdout, /held: unavailable/);
  // no queued ids -> dispatch is not asked at all (a failing dispatch stays silent)
  assert.doesNotMatch(view({ board: [{ id: "t-w", stage: "working" }], dispatch: "FAIL" }).stdout, /held:/);
});

test("pace line only when cc-pace exists", () => {
  assert.doesNotMatch(view({}).stdout, /pace:/);
  assert.match(view({ pace: "5h 40% / wk 20%" }).stdout, /^pace: 5h 40% \/ wk 20%/);
  assert.equal(json({ pace: "x" }).pace, "x");
});

test("--html writes a self-contained, escaped, self-refreshing page", () => {
  const r = view({ runs: [run({ pid: 1, out: "/o/w-r1.md", detail: "<b>&" })] }, ["--html", "@html", "--watch", "0"]);
  assert.equal(r.status, 0);
  const html = fs.readFileSync(path.join(r.dir, "out.html"), "utf8");
  assert.match(html, /<meta http-equiv="refresh" content="15">/);
  assert.match(html, /RUNNING/);
  assert.match(html, /&lt;b&gt;&amp;/);
  assert.doesNotMatch(html, /<b>/);
  assert.ok(!fs.existsSync(path.join(r.dir, "out.html.tmp")));
});

test("bad arguments exit 2", () => {
  assert.equal(view({}, ["--nope"]).status, 2);
  assert.equal(spawnSync(process.execPath, [BIN, "--html"], { encoding: "utf8", timeout: 20_000 }).status, 2);
});

test("a hung child is killed at the timeout and degrades only its own section", () => {
  const t0 = Date.now();
  const r = view({ board: [{ id: "t-w", stage: "working" }], env: { WV_OCW_CLI: path.join(FIX, "hang.mjs"), WV_CHILD_TIMEOUT_MS: "700" } }, ["--json"]);
  const d = JSON.parse(r.stdout);
  assert.ok(Date.now() - t0 < 20_000);
  assert.equal(d.runs, null);
  assert.match(d.errors.runs, /timed out/);
  assert.deepEqual(d.no_live_run.map((n) => n.ticket), ["t-w"]);
});

test("the overall budget stops later children once it is spent", () => {
  const board = [{ id: "t-q", stage: "queued" }];
  const d = JSON.parse(view({ board, env: { WV_OCW_CLI: path.join(FIX, "hang.mjs"), WV_CHILD_TIMEOUT_MS: "5000", WV_BUDGET_MS: "600" } }, ["--json"]).stdout);
  assert.match(d.errors.runs, /timed out/);
  assert.match(d.errors.board, /no time left/);
});

test("when several tickets match one pid, the working ticket wins", () => {
  const d = json({
    runs: [run({ pid: 42, out: "/o/w-r1.md" })],
    board: [
      { id: "t-old", stage: "shipped", worker: { pid: 42, out_path: "/old.md" } },
      { id: "t-now", stage: "working", worker: { pid: 42, out_path: "/o/w-r1.md" } },
      { id: "t-zzz", stage: "closed", worker: { pid: 42, out_path: "/z.md" } },
    ],
  });
  assert.equal(d.runs[0].ticket, "t-now");
});

test("a linked git worktree reads the main repo's board", () => {
  const git = (cwd, ...a) => {
    const r = spawnSync("git", a, { cwd, encoding: "utf8", timeout: 30_000 });
    assert.equal(r.status, 0, r.stderr);
  };
  const main = fs.mkdtempSync(path.join(os.tmpdir(), "wv-git-"));
  CLEAN.push(main);
  git(main, "init", "-q");
  git(main, "-c", "user.name=t", "-c", "user.email=t@e.x", "commit", "-q", "--allow-empty", "-m", "i");
  const wt = `${main}-linked`;
  CLEAN.push(wt);
  git(main, "worktree", "add", "-q", wt);
  fs.mkdirSync(path.join(main, ".opencode", "board", "tickets"), { recursive: true });
  fs.writeFileSync(path.join(main, ".opencode", "board", "tickets", "t-m.json"), JSON.stringify({ assignment: { worker: { pid: 77, out_path: "/o/m-r4.md" } } }));
  const f = path.join(main, "f.json");
  fs.writeFileSync(f, JSON.stringify([{ id: "t-m", stage: "working" }]));
  fs.writeFileSync(path.join(main, "r.json"), JSON.stringify([{ agent: "worker", state: "RUNNING", pid: 77, out: "/o/m-r4.md" }]));
  const env = { ...process.env, WV_OCW_CLI: path.join(FIX, "ocw.mjs"), WV_FIX_OCW: path.join(main, "r.json"), WV_BOARD_CLI: path.join(FIX, "board.mjs"), WV_FIX_BOARD: f, WV_PACE_CLI: path.join(main, "none.mjs") };
  const r = spawnSync(process.execPath, [BIN, "--json", "--repo", wt], { env, encoding: "utf8", timeout: 30_000 });
  const d = JSON.parse(r.stdout);
  assert.equal(d.runs[0].ticket, "t-m"); // only the main repo holds the ticket file
  assert.deepEqual(d.no_live_run, []);
});
