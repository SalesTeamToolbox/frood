---
phase: quick
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - README.md
autonomous: true
requirements: [DOC-README]

must_haves:
  truths:
    - "README tool count matches actual MCP-registered tools (28, not 36+)"
    - "README skill count matches actual skills (47 builtin + 6 workspace = 53)"
    - "README badge versions are accurate (v2.0.0-alpha server, v3.0 platform vision)"
    - "README tool tables distinguish MCP-registered tools from CC-native/dashboard-only tools"
    - "README hooks section reflects all actual hooks in .claude/hooks/"
    - "README project structure reflects current codebase"
  artifacts:
    - path: "README.md"
      provides: "Accurate project documentation"
      min_lines: 700
  key_links:
    - from: "README.md tool tables"
      to: "mcp_server.py _build_registry()"
      via: "Tool names and counts must match"
      pattern: "28.*tools"
---

<objective>
Update README.md to accurately reflect the current Agent42 codebase state.

Purpose: The README has accumulated inaccuracies as the codebase evolved through v2.0 MCP pivot
and v3.0 agent platform work. Tool counts, skill counts, hook lists, and registered tools don't
match reality. This erodes trust for new users and contributors.

Output: An accurate README.md that matches the actual codebase.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@README.md
@mcp_server.py (lines 86-264 — _build_registry() shows actual registered tools)
@.claude/hooks/ (actual hook files)
@skills/builtins/ (47 builtin skill directories)
@skills/workspace/ (6 workspace skill directories)

<interfaces>
<!-- Key facts from codebase audit — executor should use these directly -->

Actual MCP-registered tools (28 total):
  Group A (no deps): ContentAnalyzerTool, DataTool, TemplateTool, OutlineTool, ScoringTool, PersonaTool, SecurityAuditTool
  Group B (workspace): GitTool, DiffTool, TestRunnerTool, LinterTool, CodeIntelTool, DependencyAuditTool, DockerTool, PythonExecTool, RepoMapTool, PRGeneratorTool, SecurityAnalyzerTool, SummarizerTool, FileWatcherTool, BrowserTool
  Group C (sandbox): VisionTool, KnowledgeTool
  Group E (lightweight): BehaviourTool, MemoryTool, WorkflowTool
  Special: ContextAssemblerTool, NodeSyncTool

NOT registered in MCP (CC-native — redundant):
  ReadFileTool, WriteFileTool, EditFileTool, ListDirTool, ShellTool, GrepTool, WebSearchTool, WebFetchTool, HttpClientTool

NOT registered in MCP (dashboard-only / future):
  SubagentTool, TeamTool, NotifyUserTool, ImageGenTool, VideoGenTool, ProjectInterviewTool, DynamicTool, CronTool, SSHTool, TunnelTool, AppTool, AppTestTool, MCPToolProxy

Skills: 47 builtins + 6 workspace = 53 total (README says 57)

Hooks in .claude/hooks/:
  context-loader.py, format-on-write.py, jcodemunch-reindex.py, jcodemunch-token-tracker.py,
  learning-engine.py, memory-learn.py, memory-recall.py, security-gate.py, security-monitor.py,
  security_config.py, session-handoff.py, test-validator.py
  (README only mentions 4: context-loader, security-monitor, test-validator, learning-engine)

SERVER_VERSION = "2.0.0-alpha" (README badge says 3.0.0)

Dashboard API: ~227 route decorators in server.py (README says 73)
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Audit and fix all numeric claims and badges</name>
  <files>README.md</files>
  <action>
Update the following inaccurate numbers/claims in README.md:

1. **Version badge**: Change `version-3.0.0-blue` to `version-3.0-blue` (keep 3.0 as the platform version — that's the v3.0 vision. The MCP server is 2.0.0-alpha internally but the user-facing brand is v3.0).

2. **Tool count badge and all inline references**: Change "36+" to "28+" everywhere it appears. The MCP server registers exactly 28 tools. Search for all occurrences of "36" in the file and update. Specifically:
   - Badge: `tools-28+-orange`
   - "36+ tools" in feature descriptions -> "28+ MCP tools"
   - Architecture diagram: "36+ Tools" -> "28+ MCP Tools"

3. **Skill count badge and inline references**: Change "57" to "53" everywhere. There are 47 builtin + 6 workspace = 53 skills. Specifically:
   - Badge: `skills-53-purple`
   - "57 skills" inline -> "53 skills"

4. **Tool table reorganization**: The current tool tables list tools that Claude Code provides natively (filesystem, shell, grep, web_search, web_fetch, http_request). These are NOT registered in the MCP server because they're redundant. Reorganize the tool section into:

   a. **MCP Tools (registered)** — The 28 tools that actually register in mcp_server.py. Group by their actual categories:
      - Memory and Context: memory, context (assembler), knowledge, node_sync, behaviour
      - Code Intelligence: code_intel, repo_map, python_exec, test_runner, linter
      - Git and Diff: git, diff, pr_generator
      - Security: security_analyze, security_audit, dependency_audit
      - DevOps: docker, browser, file_watcher, vision
      - Content and Data: content_analyzer, data, template, outline, scoring, summarizer
      - Orchestration: workflow, persona

   b. **Claude Code Native Tools (not registered — CC provides)** — Brief note explaining these are handled by CC itself: filesystem (read/write/edit/list), shell, grep, web search, web fetch, HTTP requests.

   c. **Dashboard-Only Tools (not in MCP)** — Brief note listing tools only available when running the full dashboard: subagent, team, notify, image_gen, video_gen, cron, ssh, tunnel, app, app_test, etc.

5. **Architecture diagram**: Update "36+ Tools | 57 Skills" to "28+ MCP Tools | 53 Skills". Also verify "73 API Routes" — if this number is clearly wrong, change to "200+ API Routes" based on the ~227 route decorators counted.

6. **mcp_server.py docstring** mentions "41+ tools" and "43 skills" — do NOT modify mcp_server.py (out of scope), but note the discrepancy. Only modify README.md.

Preserve the Hitchhiker's Guide humor/voice throughout. Do not change sections that are already accurate.
  </action>
  <verify>
    <automated>cd C:/Users/rickw/projects/agent42 && python -c "
import re
with open('README.md') as f:
    content = f.read()
# Check no '36' tool references remain
assert '36+' not in content, 'Still contains 36+ reference'
assert '36 tools' not in content, 'Still contains 36 tools reference'
# Check no '57' skill references remain
assert '57 skills' not in content, 'Still contains 57 skills reference'
assert '57-purple' not in content, 'Still contains 57 badge'
# Check new counts present
assert '28+' in content or '28 ' in content, 'Missing 28 tool count'
assert '53' in content, 'Missing 53 skill count'
print('All numeric checks passed')
"</automated>
  </verify>
  <done>All tool counts, skill counts, and badge numbers in README.md match the actual codebase. Tool tables clearly distinguish MCP-registered tools from CC-native and dashboard-only tools.</done>
</task>

<task type="auto">
  <name>Task 2: Update hooks section and project structure</name>
  <files>README.md</files>
  <action>
Update two sections in README.md:

1. **Hooks section** (under "Automated Development Workflow" / "Active Hooks"):
   The current table lists only 4 hooks. Update to include all active hooks in `.claude/hooks/`:

   | Hook | Trigger | Action |
   |------|---------|--------|
   | `context-loader.py` | UserPromptSubmit | Loads relevant lessons and reference docs based on work type |
   | `memory-recall.py` | UserPromptSubmit | Surfaces relevant memories from Qdrant before Claude thinks |
   | `security-monitor.py` | PostToolUse (Write/Edit) | Flags security-sensitive changes for review |
   | `security-gate.py` | PreToolUse | Blocks dangerous operations proactively |
   | `format-on-write.py` | PostToolUse (Write) | Auto-formats code on file writes |
   | `jcodemunch-reindex.py` | PostToolUse | Re-indexes codebase after file changes |
   | `jcodemunch-token-tracker.py` | PostToolUse | Tracks token usage for jcodemunch operations |
   | `session-handoff.py` | Stop | Captures session context for continuity |
   | `test-validator.py` | Stop | Validates tests pass, checks test coverage |
   | `learning-engine.py` | Stop | Records development patterns and vocabulary |
   | `memory-learn.py` | Stop | Captures learnings into memory system |

   Note: `security_config.py` is a config module not a hook — do NOT list it.

   Verify each hook's actual trigger by reading the first ~30 lines of each hook file to check for the hook_event_name handling. If the trigger description above is wrong, use the correct one from the file.

2. **Project structure tree**: Update to reflect current state:
   - Hooks directory should list the actual hooks (memory-recall.py, memory-learn.py, session-handoff.py, format-on-write.py, etc.) not the old 4-hook list
   - Verify other files/dirs in the tree are still accurate
   - Add `memory/qdrant_store.py` if not listed (it is listed)
   - Ensure `tools/memory_tool.py` is shown (it is shown)

Preserve Hitchhiker's Guide voice. Only change what's inaccurate.
  </action>
  <verify>
    <automated>cd C:/Users/rickw/projects/agent42 && python -c "
with open('README.md') as f:
    content = f.read()
# Check key hooks are mentioned
assert 'memory-recall' in content, 'Missing memory-recall hook'
assert 'memory-learn' in content, 'Missing memory-learn hook'
assert 'session-handoff' in content, 'Missing session-handoff hook'
assert 'format-on-write' in content or 'format_on_write' in content, 'Missing format-on-write hook'
assert 'security-gate' in content, 'Missing security-gate hook'
print('Hook section checks passed')
"</automated>
  </verify>
  <done>Hooks section lists all 11 active hooks with correct triggers. Project structure tree reflects current codebase layout.</done>
</task>

</tasks>

<verification>
After both tasks complete:
1. `python -c "with open('README.md') as f: content = f.read(); assert '36+' not in content; assert '57 skills' not in content; assert 'memory-recall' in content; print('README verification passed')"` — passes
2. Visual scan of README for consistency — no contradictory numbers between sections
</verification>

<success_criteria>
- All tool/skill counts match actual codebase (28 MCP tools, 53 skills)
- Tool tables distinguish MCP-registered from CC-native and dashboard-only
- All 11 hooks listed with correct triggers
- Project structure tree matches current files
- Hitchhiker's Guide voice preserved
- No broken markdown formatting
</success_criteria>

<output>
After completion, create `.planning/workstreams/per-project-task-memories/quick/260317-gsn-update-readme-md-documentation-to-reflec/260317-gsn-SUMMARY.md`
</output>
