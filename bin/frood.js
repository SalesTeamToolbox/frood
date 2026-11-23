#!/usr/bin/env node
// frood — subcommand dispatcher for Frood commands.
//
// Usage: node bin/frood.js <subcommand> [args...]
//        node bin/frood.js --help
//
// Routes each frood-* subcommand to its underlying tool. The old `orchestrator`
// and `gauntlet` names are recognised here (backward-compat aliases are wired in
// M4); in M2 they print "not yet implemented" instead of crashing.

const { spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const WORKTREE_ROOT = path.resolve(__dirname, '..');
const ORCH_REPO = process.env.ORCH_REPO || path.join(WORKTREE_ROOT, 'orchestrator');

// name -> { description, usage, impl }
// impl: 'stub' (not yet implemented, M4) or [cmd, ...args] run with forwarded args.
const SUBCOMMANDS = [
  {
    name: 'orchestrator',
    description: 'Full orchestrator lifecycle — command alias handled in M4',
    usage: '/frood orchestrator [task or plan-path]',
    impl: 'stub',
  },
  {
    name: 'gauntlet',
    description: 'Execute one plan module under the gauntlet — command alias handled in M4',
    usage: '/frood gauntlet [plan-path] [module]',
    impl: 'stub',
  },
  {
    name: 'board',
    description: 'Ticket board — records and verifies evidence',
    usage: `node "${path.join(ORCH_REPO, 'bin', 'board.mjs')}" <command> [args]`,
    impl: [process.execPath, path.join(ORCH_REPO, 'bin', 'board.mjs')],
  },
  {
    name: 'desk',
    description: 'Flat-context /desk session — watches streams via bin/handoff.mjs',
    usage: `node "${path.join(ORCH_REPO, 'bin', 'desk.mjs')}" <command> [args]`,
    impl: [process.execPath, path.join(ORCH_REPO, 'bin', 'desk.mjs')],
  },
  {
    name: 'train',
    description: 'Release train — board verify, pytest, receipts, local-HEAD sha readback',
    usage: 'bash ops/train.sh <ticket>',
    impl: ['bash', path.join(WORKTREE_ROOT, 'ops', 'train.sh')],
  },
  {
    name: 'peer-mail',
    description: 'Cross-harness peer-mail — send/inbox/read/ack between sessions',
    usage: 'peer-mail <send|inbox|read|ack|sessions> ...',
    impl: [process.execPath, path.join(ORCH_REPO, 'bin', 'peer-mail')],
  },
  {
    name: 'egm',
    description: 'EGM (Elephant-Goldfish) review — pre-gauntlet plan review',
    usage: '/frood-egm egm-review <plan>  |  review-loop  |  drift-report',
    impl: 'stub',
  },
  {
    name: 'deploy',
    description: 'Deploy — deploy truth and shipped-sha readback',
    usage: '/frood-deploy <ticket> --sha <sha>',
    impl: 'stub',
  },
  {
    name: 'setup',
    description: 'Frood setup — one-time local setup after cloning',
    usage: 'bash setup.sh [sync-auth|create-shortcut|generate-claude-md|--quiet]',
    impl: ['bash', path.join(WORKTREE_ROOT, 'setup.sh')],
  },
  {
    name: 'health',
    description: 'Frood health check — scripts/setup_helpers.py health',
    usage: 'python scripts/setup_helpers.py health [project-dir]',
    impl: ['python', path.join(WORKTREE_ROOT, 'scripts', 'setup_helpers.py'), 'health'],
  },
  {
    name: 'learn',
    description: 'Phase-aware learning review — 5 phases, 23 lenses, session analysis, --apply for interactive fixes/PRs',
    usage: 'node bin/frood-learn.mjs <stream|session-id> [--phase <1|2|3|4|5>] [--lens <name>] [--no-mcp] [--propose] [--apply] [--report <path>] [--session <id>]',
    impl: [process.execPath, path.join(WORKTREE_ROOT, 'bin', 'frood-learn.mjs')],
  },
  {
    name: 'cc',
    description: 'Switch Claude Code LLM provider via Frood proxy (see frood-cc.md)',
    usage: '/frood-cc <provider>', // zen, opencode, cmdcode, nvidia, openrouter, cc, status
    impl: ['python', path.join(WORKTREE_ROOT, 'frood-cc-launcher.py')],
  },
];

function pad(s, n) {
  return s + ' '.repeat(Math.max(0, n - s.length));
}

function printHelp() {
  const widest = Math.max(...SUBCOMMANDS.map((s) => s.name.length));
  console.log('Frood subcommands:');
  console.log(`  Usage: node bin/frood.js <subcommand> [args...]`);
  console.log(`         node bin/frood.js <subcommand> --help`);
  console.log('');
  for (const sc of SUBCOMMANDS) {
    console.log(`  ${pad(sc.name, widest)}  ${sc.description}`);
  }
  console.log('');
  console.log('Subcommands `orchestrator` and `gauntlet` are recognised but not yet');
  console.log('implemented in M2 (aliases wired in M4) — they print "not yet implemented".');
  console.log('Run `node bin/frood.js <subcommand> --help` for a subcommand\'s usage.');
}

function printSubcommandHelp(name) {
  const sc = SUBCOMMANDS.find((s) => s.name === name);
  if (!sc) {
    console.error(`frood: unknown subcommand "${name}"`);
    console.error(`Run "node bin/frood.js --help" to list subcommands.`);
    process.exit(1);
  }
  console.log(`${sc.name} — ${sc.description}`);
  console.log(`Usage: ${sc.usage}`);
  if (sc.impl === 'stub') {
    console.log('Status: not yet implemented in M2 (command alias handled in M4).');
  } else {
    console.log(`Delegates to: ${sc.impl.join(' ')}`);
    console.log('Pass `--help` (or `-h`) to this subcommand to see the underlying tool\'s usage.');
  }
}

function runImpl(impl, args) {
  const [cmd, ...cmdArgs] = impl;
  const result = spawnSync(cmd, [...cmdArgs, ...args], {
    stdio: 'inherit',
    cwd: WORKTREE_ROOT,
    env: process.env,
  });
  if (result.error) {
    console.error(`frood: failed to run "${cmd}": ${result.error.message}`);
    process.exit(1);
  }
  process.exit(result.status === null ? 1 : result.status);
}

const argv = process.argv.slice(2);

if (argv.length === 0 || argv[0] === '--help' || argv[0] === '-h') {
  printHelp();
  process.exit(0);
}

const name = argv[0];
const rest = argv.slice(1);

if (rest.includes('--help') || rest.includes('-h')) {
  printSubcommandHelp(name);
  process.exit(0);
}

const sc = SUBCOMMANDS.find((s) => s.name === name);
if (!sc) {
  console.error(`frood: unknown subcommand "${name}"`);
  console.error(`Run "node bin/frood.js --help" to list subcommands.`);
  process.exit(1);
}

if (sc.impl === 'stub') {
  console.log(`frood: "${name}" — not yet implemented in M2 (command alias handled in M4).`);
  process.exit(0);
}

runImpl(sc.impl, rest);
