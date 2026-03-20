# Pitfalls Research

**Domain:** Adding bi-directional vector sync, enterprise RBAC, multi-agent orchestration, cross-platform setup, and deep jcodemunch integration to an existing Python/FastAPI AI agent platform (Agent42)
**Researched:** 2026-03-17
**Confidence:** HIGH - grounded in direct codebase analysis, Qdrant distributed docs, and patterns from 116 existing documented pitfalls

---

## Critical Pitfalls

### Pitfall 1: Qdrant Embedded File Lock Prevents Bi-Directional Sync

**What goes wrong:**
Agent42 NodeSyncTool uses rsync to sync MEMORY.md and HISTORY.md markdown files, then calls reindex_memory() on the destination. When upgrading to bi-directional Qdrant sync (syncing vector points directly between laptop and VPS), the embedded Qdrant instance holds a RocksDB file lock for its entire process lifetime. The local Agent42 process holds the lock. A sync daemon or import script trying to write to the same embedded database directory while the main process is running will get QDRANT_LOCKED or RocksDB Resource temporarily unavailable errors.

This is not an edge case - any sync that runs while the MCP server is serving Claude Code tool calls will hit this. The embedded mode limitation is architectural: only one writer at a time is supported.

**Why it happens:**
Developers assume that because Qdrant has a Python client and replication features, it is straightforward to sync two Qdrant instances. But Qdrant built-in replication (Raft consensus) is for cluster-mode deployments behind a single URL, not for syncing two independent standalone instances. The GitHub discussion on qdrant/qdrant#4622 explicitly confirms: cross-cluster replication is not currently supported; the feature is on the roadmap. Embedded mode adds a second layer: even if you implement point-by-point sync, you cannot write to the embedded DB while the main process holds the file lock.

**How to avoid:**
1. Do not attempt Qdrant-native replication between embedded instances. There is no supported API for this.
2. Sync at the payload level via point export/import. Use qdrant-client scroll() to export points from source, filter for points modified since last sync (by timestamp payload field), serialize to JSONL, transfer via rsync or scp, then import into destination using upsert(). This works for embedded mode because the import runs ONLY when the main Agent42 process is not running.
3. Enforce a sync window: sync only runs when Agent42 is idle (not during active tool calls). Add a _sync_lock asyncio.Lock to prevent concurrent sync and writes. The daemon polls the Agent42 health endpoint before syncing; if active, defer.
4. Conflict resolution policy: use timestamp payload field as the authoritative merge key. Newer timestamp wins for memory collection. For history collection, use append-merge (union of point IDs). For effectiveness collection, take the maximum invocations count per (tool_name, task_type) pair.
5. Accept the rsync-first approach as correct for markdown files. The existing NodeSyncTool rsync path for MEMORY.md and HISTORY.md is the right solution for the file layer. Only add Qdrant-level sync for the effectiveness and knowledge collections, where structured query access justifies the complexity.

**Warning signs:**
- _ensure_db() or Qdrant search() begins returning StorageError: locked during sync.
- reindex_memory() takes longer than normal (sign that an import is competing with a live search).
- Qdrant embedded logs show Failed to acquire write lock during Agent42 startup.

**Phase to address:** Memory Sync Upgrade - must define the sync window protocol before writing any Qdrant sync code.

---

### Pitfall 2: RBAC Role Decorator Silently Breaks All Existing Single-User API Callers

**What goes wrong:**
The current dashboard/auth.py has a single user (admin) with JWT auth and no concept of roles. Adding RBAC by decorating existing endpoints with role requirements looks safe because there is only one user and that user would be admin. But the change breaks:

- Device API keys (ak_ prefixed tokens): these authenticate as device user with auth_type api_key, not as admin. Any RBAC check that requires the admin role will reject all device tokens unless device tokens are explicitly mapped to a role.
- MCP server calls: mcp_server.py calls internal FastAPI endpoints directly. If those endpoints suddenly require a role that the MCP service account does not have, calls silently fail with 403.
- Cowork daemon: coworker-daemon.sh updates work orders via python3 core/work_order.py. If that update path calls any authenticated dashboard endpoint, it will break without a daemon service token.

**Why it happens:**
Single-user-to-multi-user migration is treated as additive (add roles to existing system), but existing callers were never designed with roles in mind. The AuthContext dataclass has user, auth_type, device_id, device_name - there is no roles field. Adding RBAC requires modifying AuthContext and every caller simultaneously.

**How to avoid:**
1. Extend AuthContext with roles: list[str] at the data model level first, before any endpoint changes. Default to roles=[admin] for the existing single admin user and roles=[device] for device API keys.
2. Add role assignment to device registration in DeviceStore. New devices get roles=[agent] by default. Existing devices auto-migrate to [agent] on next load.
3. New require_role() dependency must explicitly handle all auth_type values - not just jwt. A device calling an admin endpoint should return 403 with a clear error message, not a confusing JWT decode error.
4. Audit all endpoints that are currently unprotected or loosely protected before adding role guards. The /api/health endpoint intentionally has no auth - RBAC must not be applied to it.
5. Use a roles lookup approach (roles stored in a users.json file alongside agents.json) rather than embedding roles in JWT claims, to avoid invalidating all existing JWTs and to allow immediate role revocation.

**Warning signs:**
- Device health broadcasts from HeartbeatService stop updating dashboard after RBAC deployment (device token rejected).
- Cowork daemon work order updates return 403 in daemon logs.
- python -m pytest tests/test_security.py fails after RBAC changes with unexpected 403 responses.

**Phase to address:** RBAC Foundation - AuthContext role extension must precede any endpoint role decorators.

---

### Pitfall 3: Bi-Directional HISTORY.md Merge Splits on Wrong Delimiter

**What goes wrong:**
The current NodeSyncTool._merge() uses a newline-dashes-newline string as the entry separator in HISTORY.md and deduplicates by string equality of entries. This works today because HISTORY.md is simple. When the memory system starts writing richer structured entries (with task_id, task_type, timestamps in payload), history entries become longer and more structured. The split produces wrong results for:

1. Any markdown entry that contains a horizontal rule within its content (a valid markdown element using three dashes).
2. Entries that differ only by whitespace normalization (a line ending difference between Windows CRLF local and Linux LF remote counts as a different entry, producing duplicate entries on merge).
3. Concurrent writes from multi-agent orchestration where two agents write HISTORY.md entries at nearly the same time - the merge sees different snapshots and produces a conflict.

**Why it happens:**
The rsync-based approach treats HISTORY.md as a flat text file. Simple string set deduplication assumes entries are semantically identical if and only if they are byte-identical. As entries become structured (JSON-in-markdown, or richer metadata), byte equality is no longer semantic equality.

**How to avoid:**
1. Switch to JSONL format for HISTORY.md entries above a version marker. Each entry is a JSON object on a single line. Deduplication is by entry_id field (UUID), not string content. This survives whitespace normalization issues.
2. If keeping markdown format, use a unique HTML comment on the first line of each entry as the deduplication key. The merge logic reads this comment rather than comparing full entry text.
3. Enforce LF line endings on HISTORY.md via .gitattributes. Add text eol=lf for markdown files. This eliminates CRLF/LF divergence as a merge conflict source (Windows CRLF breaking bash is already documented in Agent42 CLAUDE.md - same root cause).
4. For multi-agent orchestration: each agent appends to a staging file (HISTORY-{agent_id}.md) and a consolidation step merges staging files into HISTORY.md at task completion. This avoids concurrent write races.

**Warning signs:**
- HISTORY.md size grows faster than expected (duplicate entries with whitespace differences).
- merge action output shows N from remote and N from local but the merged file is much larger than either source.
- Horizontal rules in note content cause incorrect entry splits in the merged file.

**Phase to address:** Memory Sync Upgrade - merge logic rewrite must happen at the same time as the sync implementation, not as a follow-up.

---

### Pitfall 4: Multi-Agent Orchestration Creates asyncio Contention on Shared EffectivenessStore

**What goes wrong:**
EffectivenessStore opens a new aiosqlite connection for every record() call via async-with aiosqlite.connect(self._db_path). With a single agent this is fine - one connection at a time. With multi-agent orchestration where 3 to 5 agents execute concurrently, each firing multiple tool calls per second, you get 15 to 25 concurrent SQLite write connections. SQLite WAL mode allows concurrent reads but only one writer at a time. The other writers get SQLITE_BUSY errors. The current exception handler silently sets self._available = False on any exception, so the first write collision disables tracking for the rest of the session.

Additionally: aiosqlite runs each connection in a background thread. With 25 connections, the asyncio thread pool is saturated with SQLite threads, starving the main event loop of worker threads for other async I/O.

**Why it happens:**
The fire-and-forget asyncio.create_task(store.record(...)) pattern was designed for single-agent use where there is at most one pending write at a time. The multi-agent extension multiplies the concurrency without changing the connection model.

**How to avoid:**
1. Replace per-call connect() with a persistent connection held open for the process lifetime. aiosqlite supports this: hold self._conn as an instance variable, close it in an async def close() method called at shutdown. All record() calls share this one connection and its single background thread.
2. Add a write queue: self._write_queue = asyncio.Queue(). record() puts to the queue (O(1), non-blocking). A background asyncio.Task drains the queue in batches of 50 and does a single executemany() insert. This eliminates write contention entirely.
3. Preserve the graceful degradation contract: if the write queue overflows (set maxsize=10000), drop records silently. Tracking loss is acceptable; blocking agent execution is not.
4. Test with asyncio.gather() on 10 concurrent record() calls in tests/test_effectiveness.py before releasing multi-agent support.

**Warning signs:**
- EffectivenessStore write failed: database is locked in logs after enabling 2+ concurrent agents.
- self._available becomes False after the first multi-agent session.
- SQLite DB file exists but get_aggregated_stats() returns empty after multi-agent runs.

**Phase to address:** Multi-Agent Orchestration Foundation - connection model must be upgraded before any multi-agent execution path is wired up.

---

### Pitfall 5: jcodemunch Tool Calls Fail Silently When Index Is Stale or Repo Is Not Indexed

**What goes wrong:**
The current jcodemunch integration is hook-based: the context-loader.py hook fires on UserPromptSubmit and pre-fetches symbols. When deepening integration to direct API calls from Agent42 tools (e.g., code_intel tool calling jcodemunch search_symbols), a common failure mode emerges: the jcodemunch index for a repo is stale (not re-indexed after recent file changes) or the repo is not indexed at all. The tool call returns an empty result set. The agent treats empty results as no symbols found rather than index is stale and proceeds with wrong assumptions, silently producing incorrect code analysis.

This is particularly bad in the cowork daemon context: the daemon clones a branch and starts editing files, but jcodemunch index still points to the pre-clone state. Symbol lookups return stale locations. The agent edits the wrong lines.

**Why it happens:**
jcodemunch search_symbols returns empty arrays (not errors) when a repo is not indexed. Empty array and no results found are indistinguishable from the caller perspective. The correct call sequence - list_repos, then check if indexed, then index_folder, then search_symbols - is only documented in CLAUDE.md as a manual workflow, not enforced programmatically.

**How to avoid:**
1. Wrap all jcodemunch tool calls in a guard that checks list_repos() first. If the repo identifier is not in the list, call index_folder() before proceeding. This adds 2 to 5 seconds for initial indexing but is idempotent.
2. After git checkout or git pull in the cowork daemon, trigger an incremental re-index. Add this as a post-checkout step in coworker-daemon.sh using the jcodemunch index_folder call with incremental: true.
3. Distinguish no results from not indexed: after receiving empty results from search_symbols, verify with list_repos(). If the repo is not in the list, return a ToolResult with a structured error: jcodemunch index not found - run index_folder first. This surfaces the real problem instead of an empty result.
4. Add a repo-freshness check: store the last git HEAD hash at index time. Before each jcodemunch query session, compare to current HEAD. If different, queue an incremental re-index.
5. Note on licensing: jcodemunch is free for non-commercial use. Commercial deployments require a paid license.

**Warning signs:**
- search_symbols returns empty array for a well-known function name in the current codebase.
- Agent produces code that references the wrong line numbers or non-existent function signatures.
- jcodemunch list_repos does not include the current AGENT42_WORKSPACE repo path.

**Phase to address:** jcodemunch Deep Integration - the list_repos guard and post-checkout re-index must be in the first integration PR, not added after no-results bugs are reported.

---

### Pitfall 6: Cross-Platform Setup Script Breaks on Windows Due to Path and Activation Differences

**What goes wrong:**
setup.sh uses source .venv/bin/activate which is Bash-only. On Windows (where Agent42 is actively developed), the equivalent is .venv/Scripts/Activate.ps1 for PowerShell. When adding a Windows PowerShell setup path, additional platform differences cause failures:

1. Path separators: python3 -m venv .venv works on both platforms, but source .venv/bin/activate fails on Windows. PowerShell uses Set-ExecutionPolicy and Activate.ps1.
2. Python binary name: Windows uses python (not python3). A Windows user running setup.sh in Git Bash gets a python3 call that may resolve to nothing.
3. nvm portability: The setup.sh installs nvm via curl-to-bash. This does not work in PowerShell. Windows uses nvm-windows from a different project.
4. CRLF contamination: If setup.sh is committed with Windows CRLF line endings, the script will fail on Linux. This is documented in Agent42 CLAUDE.md but not yet prevented by .gitattributes.
5. PowerShell Execution Policy: A freshly installed Windows system has Restricted execution policy. Activate.ps1 will fail with cannot be loaded because running scripts is disabled.

**Why it happens:**
Bash-first development ignores Windows until Windows users report failures. The existing setup.sh was written entirely for Linux/macOS. Agent42 is actively developed on Windows but the setup script has not been updated to support Windows workflows.

**How to avoid:**
1. Create a parallel setup.ps1 for Windows. It mirrors setup.sh logic but uses Windows-native commands. Use python instead of python3, use .venv/Scripts/Activate.ps1, and use nvm-windows for Node.js version management.
2. Add a platform detection wrapper: a top-level setup.sh that detects the OS and delegates to setup-linux.sh, or prints guidance for Windows users, is cleaner than one script that tries to handle both.
3. Enforce LF on all shell scripts via .gitattributes: add text eol=lf for .sh files and text eol=crlf for .ps1 files to prevent CRLF contamination in either direction.
4. For setup.ps1, add an execution policy check at the top.
5. Test the Windows path explicitly on a clean Windows 11 system.
6. Document the Windows development path clearly in README.md as a first-class setup path, not an afterthought.

**Warning signs:**
- setup.sh has CRLF line endings in git diff output (should be LF only).
- Windows users report python3 not found when running setup.
- PowerShell users see cannot be loaded when activating the venv.

**Phase to address:** Unified Setup Automation - Windows setup path must be complete before GA, not post-launch.

---

### Pitfall 7: RBAC Permission Check Bypassed by Existing ApprovalGate and Device Auth Code Paths

**What goes wrong:**
Agent42 has an ApprovalGate that allows human review of protected actions, and a DeviceStore that issues ak_ prefixed API keys for registered devices. When RBAC is added, new role checks may be added to REST endpoints but not to these alternative code paths:

1. ApprovalGate.request_approval() sends a payload to the dashboard for human review. If the approval itself triggers a backend action, that action bypasses any role check on the REST endpoint because it goes through the approval gate internal callback, not through the authenticated REST handler.
2. Device API keys are issued with auth_type api_key. If the new role-checking dependency short-circuits for API keys (returning early when auth_type is api_key), then any device can call any admin endpoint.
3. The existing 8-layer security model was designed as defense-in-depth for a single-user system. RBAC must be layered on top of these mechanisms, not as a replacement. Developers often disable one layer when adding another, breaking the defense-in-depth guarantee.

**Why it happens:**
RBAC is typically bolt-on. When adding it to an existing system, developers focus on the normal REST auth path and miss alternative entry points: webhooks, device tokens, internal callbacks, daemon service calls.

**How to avoid:**
1. Audit every non-JWT auth code path before implementing RBAC. In Agent42 these are: ak_ device tokens, COWORK_SERVICE_TOKEN (if added for daemon), internal core/work_order.py CLI calls.
2. Assign roles to service accounts explicitly: cowork daemon gets roles=[cowork_daemon]. Device tokens get roles=[device]. Each role is defined in a roles.json config with explicit permission grants.
3. ApprovalGate callbacks must carry an approved_by field that is checked against the approver roles. An approval from a device role account must not be able to approve admin-level actions.
4. Do not short-circuit RBAC for api_key auth_type - instead, look up the device roles and apply the same role check. Return 403 with a clear error message when the device role is insufficient.
5. Write a security regression test suite that specifically tests RBAC with device tokens, cowork daemon tokens, and expired JWT tokens. Run this as part of CI.

**Warning signs:**
- A device API key can call /api/admin/settings without a 403 response.
- The approval gate approves a protected action from an unauthenticated callback URL.
- After RBAC deployment, the cowork daemon can no longer update work order status (role not mapped).

**Phase to address:** RBAC Foundation - alternative auth path audit must be a mandatory pre-condition. Add to the phase acceptance criteria.

---

### Pitfall 8: Multi-Agent Orchestration Race Condition on Shared Agent State File

**What goes wrong:**
AgentManager stores agent state in a JSON file. When multiple agents run concurrently and each updates its own status (in-progress, completed, failed), each does a read-modify-write cycle on the shared JSON file:

- Agent A reads agents.json, modifies entry A, writes agents.json
- Agent B reads agents.json, modifies entry B, writes agents.json
- Agent A write is overwritten by Agent B read-modify-write because Agent B read before Agent A wrote

With asyncio and a single event loop, this race only happens if there is an await between the read and write. Since aiofiles.open() is async, any agent that reads the file, yields to the event loop (for example during an LLM call), and then writes back will overwrite concurrent agent updates.

This exact pattern caused pitfall 83 (dashboard doCreateTask() called twice), pitfall 87 (heartbeat overwrites task/tool counts), and pitfall 91 (critics racing each other). Multi-agent orchestration amplifies the risk.

**Why it happens:**
JSON files are not atomic. Read-modify-write is not atomic. asyncio creates the illusion of sequential execution but yields between reads and writes.

**How to avoid:**
1. Use an asyncio.Lock per agent state file stored on the AgentManager instance. All reads and writes to agents.json must acquire this lock.
2. Alternatively, switch to SQLite for agent state. aiosqlite with a targeted UPDATE by ID is atomic per row and eliminates the entire read-modify-write problem.
3. Each agent writes only to its own namespace. Instead of one agents.json file, use agents/{agent_id}/state.json. An agent only ever writes to its own state file - no cross-agent file contention.
4. The cowork daemon already uses a git-commit-based state write pattern (commits work order JSON files). This is safe because git commits are atomic at the file level. The same pattern should be used for agent state in multi-agent mode.
5. Add a version field to agent state files. On write, check that version has not changed since the read. If it has, retry with the latest state. This is an optimistic concurrency check.

**Warning signs:**
- Agent status shows stale data in the dashboard after a multi-agent run (shows in-progress when completed).
- Work order status updates are missing for some agents in a team.
- Agent state file has the wrong number of entries after a concurrent run.

**Phase to address:** Multi-Agent Orchestration Foundation - agent state persistence must be concurrency-safe before the first multi-agent test run.

---

### Pitfall 9: GSD Autonomous Mode Leaves Stale Environment Variables in Concurrent Sessions

**What goes wrong:**
The cowork daemon uses unset CLAUDECODE before launching auto-resume.sh to prevent nested-session error (documented in coworker-daemon.sh). When multi-agent orchestration runs multiple Claude Code sessions concurrently (two agents working on different branches simultaneously), each session spawns a subprocess. The unset CLAUDECODE in the parent shell does not propagate to subshells that were already started. If the orchestrator dispatches Agent B while Agent A is already running, Agent B inherits whatever CLAUDECODE value Agent A set in its subprocess environment.

More critically: GSD autonomous mode adds its own environment variables for workstream/phase context. If two agents run simultaneously from the same GSD invocation, they share these environment variables and produce conflicting workstream state writes.

**Why it happens:**
Environment variable isolation is assumed but not enforced. Bash unset in a parent shell does not affect already-running subprocesses. The daemon was designed for sequential work order execution - concurrent dispatch exposes this assumption.

**How to avoid:**
1. Each agent must run in an isolated subprocess with a clean environment. Use asyncio.create_subprocess_exec() with an explicit env= parameter that contains only the required variables for that agent. Do not inherit the parent process environment.
2. For GSD phase context, use per-agent temp directories. Each agent gets its own TMPDIR and a separate .planning/ state path. The orchestrator creates these before dispatch and cleans them up after completion.
3. The CLAUDECODE variable conflict is already partially mitigated by the daemon unset approach - but that only works for sequential execution. For concurrent execution, explicitly set CLAUDECODE to empty string in the subprocess env dict rather than relying on inherited env state.
4. Add a concurrent execution preflight check to the orchestrator: before dispatching two agents to the same branch, verify there is no running Claude Code session on that branch. Use a branch-keyed lock file in a temp directory with timeout.

**Warning signs:**
- Two concurrent agents produce git commits on the same branch with conflicting content.
- GSD phase state files show interleaved writes from two agents (identifiable by different timestamps within the same file).
- CLAUDECODE errors appear in the second agent logs when launched while first is running.

**Phase to address:** Multi-Agent Orchestration Foundation - environment isolation must be explicit and tested with a two-agent concurrent run before shipping orchestration features.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|------------------|
| Add role guards to endpoints without auditing device/daemon code paths | Appears to add RBAC | Device and daemon calls break silently; requires emergency hotfix | Never - audit first |
| Use a single admin role for all existing users during RBAC migration | Zero migration friction | RBAC provides no benefit - every user is admin; role differentiation impossible without re-auth | Only as a 24-hour migration window, not permanent |
| Sync Qdrant by stopping the service, rsyncing the data directory, and restarting | Simple, works once | Sync window requires Agent42 downtime; data directory format may differ between Qdrant versions | Acceptable for one-time migration, never for routine sync |
| Implement multi-agent orchestration using asyncio.gather() on existing sequential agent code | Fast to implement | Shared mutable state (agents.json, EffectivenessStore) causes data races under concurrency | Only for read-only parallel tasks (research agents) |
| Write setup.ps1 as a thin wrapper that calls WSL to run setup.sh | Reuses existing script | Requires WSL installed; does not work on fresh Windows installs without WSL | Only if explicitly supporting WSL-only Windows setup |
| Keep jcodemunch integration as hook-only with no direct tool API calls | No change to existing tools | jcodemunch stays a passive observer; agents cannot query code intelligence on-demand | Acceptable if deep integration is explicitly out of scope for a phase |
| Store RBAC role assignments in JWT claims | Simpler lookup (no DB call per request) | Role changes require all tokens to expire (up to 24h delay); cannot revoke permissions immediately | Never for admin or security-sensitive roles; acceptable for low-privilege read-only roles |

---

## Integration Gotchas

Common mistakes when connecting to existing system components.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Qdrant embedded sync | Attempting upsert() into embedded DB while Agent42 is running | Export points to JSONL when idle, import only during maintenance window; use sync_lock to enforce |
| AuthContext plus RBAC | Adding roles field to JWT payload without bumping token version | Add a ver: 2 claim to RBAC tokens; get_current_user() treats missing ver as legacy single-user admin; avoids invalidating existing sessions |
| EffectivenessStore plus multi-agent | Opening one aiosqlite.connect() per record() call under concurrency | Single persistent connection plus write queue; drains in background task at 50-record batches |
| NodeSyncTool plus Qdrant points | Calling reindex_memory() after syncing assumes it syncs vector points | Qdrant point sync and markdown sync are separate operations; re-index only affects the embedding layer, not the vector store directly |
| jcodemunch plus cowork daemon | Daemon runs git checkout new-branch but never triggers jcodemunch re-index | Add index_folder incremental call as post-checkout step in daemon |
| RBAC plus existing require_admin | Existing require_admin in dashboard/auth.py does not check roles - it only checks if the user is the configured admin username | Do not rename require_admin without also updating its implementation to use the new AuthContext.roles field |
| Windows setup plus Python venv | python3 -m venv .venv creates .venv/Scripts/ on Windows, not .venv/bin/ | Detect platform before activation and use platform-appropriate activate script |
| Multi-agent plus AGENT_DISPATCH_DELAY | Pitfall 93 raised AGENT_DISPATCH_DELAY to 2.0s to prevent API rate spikes - multi-agent must not bypass this | Dispatch delay must apply per-agent-slot; 5 agents with 2s delay still hit the same rate limits without per-slot staggering |

---

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Scanning all Qdrant points for sync delta | Sync takes minutes instead of seconds as collections grow | Add updated_at payload index and filter by updated_at greater than last_sync_timestamp; sync only changed points | At approximately 5,000 points (typical after 6 months of use) |
| Loading full agents.json for each agent status update | Read-modify-write on a growing file; each update re-parses all agents | Switch to per-agent state files or SQLite; update only the agent own row | At approximately 20 agents (reads approach 1MB+ per update cycle) |
| jcodemunch full re-index on every git pull in daemon | Re-index takes 30-60s for large codebases; daemon stalls | Use incremental re-index; only re-index modified files | At codebases over 5,000 files (re-index takes longer than work order execution) |
| RBAC role lookup per request without caching | Role lookup hits users.json on every authenticated request; 36+ MCP tools times N concurrent agents equals many file reads per second | Cache role lookups in memory with a 60s TTL; invalidate on role change events | At more than 3 concurrent agents making rapid tool calls |
| Multi-agent LLM dispatch without per-provider rate limit awareness | All agents route to the same provider simultaneously; 429s cause cascading retry storms (pitfall 93 context) | Extend AGENT_DISPATCH_DELAY to be provider-aware: agents using the same provider are staggered more aggressively | At more than 2 concurrent agents using the same L1/L2 model |

---

## Security Mistakes

Domain-specific security issues beyond general web security.

| Mistake | Risk | Prevention |
|---------|------|------------|
| RBAC roles.json stored in the Agent42 workspace directory | An agent with filesystem tool access can read and modify its own role assignments | Store roles.json outside the sandbox workspace path (e.g., ~/.agent42/roles.json, not inside AGENT42_WORKSPACE) |
| Multi-agent orchestration shares a single JWT_SECRET for service-to-service tokens | If a service token is compromised, all agents are compromised | Use short-lived (15m) service tokens with a separate SERVICE_JWT_SECRET; rotate on each work order dispatch |
| Qdrant sync transfers raw vector payloads including user data or file contents stored in memory entries | Sync destination may have different access controls than source | Apply the same sanitization pipeline (strip secrets, redact paths) to exported Qdrant points that is applied on entry |
| PowerShell setup.ps1 downloads and runs scripts from the internet without hash verification | Supply chain attack on nvm-windows or Node.js installer | Pin installer URLs and verify SHA256 checksums before execution using Get-FileHash pattern |
| Cowork daemon uses git add -A for auto-commits | Accidentally stages .env, API keys, or generated credential files | Use git add -u (modified tracked files only) or an explicit whitelist; add a pre-commit check that rejects commits containing known secret patterns |

---

## UX Pitfalls

Common user experience mistakes in this domain.

| Pitfall | User Impact | Better Approach |
|---------|-------------|------------------|
| RBAC login page does not indicate what roles a user has | User cannot tell why they are being denied access to a feature | Show current role in the dashboard header; show insufficient permissions on blocked actions with the required role |
| Multi-agent view launches all agents simultaneously with no progress indication | User sees no feedback for 30-60 seconds while agents initialize | Show per-agent initializing, running, completed status cards in real-time via the existing WebSocket heartbeat |
| Setup script prints Setup complete before testing that Agent42 actually starts | User thinks setup succeeded but first run fails with a missing dependency | Add a smoke test at the end of setup using a check-config flag that validates config and exits 0/1 without starting the server |
| jcodemunch index not found error surfaced as a raw tool error to the LLM | LLM hallucinates a workaround instead of triggering reindex | Return a structured error with action_required run index_folder and the code_intel tool should automatically trigger re-index before retrying |
| Windows PowerShell setup shows no progress during pip install (long pause with no output) | User thinks the script is hung after 2 minutes of silence | Add explicit progress messages before long steps and print estimated durations |

---

## "Looks Done But Is Not" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Bi-directional memory sync:** Verify that sync runs correctly when the EffectivenessStore SQLite DB is also present - sync must include the SQLite DB or explicitly document that effectiveness data is node-local only.
- [ ] **RBAC migration:** Verify that all existing device API keys (ak_ prefix) in production have been assigned a role in roles.json - unassigned devices will 403 on first post-RBAC authenticated call.
- [ ] **Multi-agent orchestration:** Verify that two concurrent agents can complete a task without producing merge conflicts in agents.json or the work orders directory - run a two-agent smoke test before calling the feature done.
- [ ] **jcodemunch deep integration:** Verify that the repo is in list_repos() before any search_symbols call - the integration is not done if it silently returns empty results on unstale repos.
- [ ] **Windows setup:** Verify that setup.ps1 creates a working venv, installs all requirements, and starts Agent42 successfully on a clean Windows 11 machine with no prior Python environment.
- [ ] **RBAC plus existing security layers:** Verify that WorkspaceSandbox, CommandFilter, and ApprovalGate still enforce their respective controls after RBAC is added - run the existing tests/test_security.py and tests/test_sandbox.py suites without modification and confirm they pass.
- [ ] **Cowork daemon auto-commit safety:** Verify that the daemon auto-commit does not stage .env or any file matching key/token/secret patterns - test with a mock .env change present in the working tree.
- [ ] **Sync conflict resolution:** Verify that running merge twice in a row produces the same result (idempotent) - a non-idempotent merge is a bug that will compound with each sync cycle.

---

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Qdrant embedded DB locked by sync attempt | LOW | Restart Agent42 (releases file lock); EffectivenessStore._available resets to optimistic on restart; data from failed sync is still on source, re-run sync during next idle window |
| RBAC migration breaks device token auth | MEDIUM | Temporarily add roles admin to all device tokens in roles.json to restore access; then audit and assign appropriate roles one device at a time; no token regeneration needed |
| HISTORY.md merge produces duplicates | LOW | Run a deduplication pass (sort unique on JSONL entry IDs or Python equivalent for markdown); re-run reindex; takes under 1 minute |
| Multi-agent run corrupts agents state file | MEDIUM | Restore from git history; re-run failed agents; implement asyncio.Lock before next run |
| jcodemunch index stale after branch switch | LOW | Run index_folder with incremental: true from Claude Code or as a post-checkout hook; takes 5-30 seconds depending on codebase size |
| Windows CRLF contamination in setup scripts | LOW | Apply sed CRLF strip on bash scripts; add text eol=lf to .gitattributes for .sh files to prevent recurrence |
| Cowork daemon stages .env in auto-commit | HIGH | Immediately revert commit and force-push; rotate all API keys and passwords in .env; audit git history for any pushed .env content |

---

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Qdrant embedded lock prevents sync | Memory Sync Upgrade | Run node_sync merge while Agent42 is actively serving tool calls - must not produce lock errors; sync must wait for idle window |
| RBAC breaks device/daemon auth paths | RBAC Foundation | After RBAC deployment, cowork daemon updates a work order status successfully; device health heartbeat continues; tests/test_security.py passes |
| HISTORY.md merge splits on wrong delimiter | Memory Sync Upgrade | Run merge twice in a row - output is identical (idempotent); merge handles entries containing horizontal rules without treating them as separators |
| EffectivenessStore contention under multi-agent | Multi-Agent Foundation | Run 5 concurrent agents; EffectivenessStore.is_available remains True throughout; aggregated stats reflect all agent tool calls |
| jcodemunch stale index | jcodemunch Deep Integration | After git checkout feature-branch, run a search_symbols call - must return results from the new branch or return structured reindex needed error |
| Windows setup script breaks | Unified Setup Automation | setup.ps1 completes successfully on a fresh Windows 11 VM with only PowerShell 7 pre-installed |
| RBAC permission check bypassed | RBAC Foundation | Device API key cannot call /api/admin/settings; must get 403 with role-insufficient error |
| Multi-agent agents state race | Multi-Agent Foundation | Two concurrent agents completing at the same time produce correct final state - verified by checking both agents show completed status |
| GSD stale environment variables | Multi-Agent Foundation | Second agent launched concurrently with first does not inherit first agent subprocess environment |
| RBAC ApprovalGate bypass | RBAC Foundation | Approval callback from a device role account cannot approve an admin-level action; returns 403 |

---

## Sources

- Qdrant distributed deployment documentation: https://qdrant.tech/documentation/guides/distributed_deployment/
- Qdrant cross-cluster sync discussion (confirmed not supported): https://github.com/orgs/qdrant/discussions/4622
- jcodemunch-mcp GitHub (tree-sitter AST indexing, list_repos guard pattern): https://github.com/jgravelle/jcodemunch-mcp
- FastAPI RBAC patterns (Permit.io tutorial): https://www.permit.io/blog/fastapi-rbac-full-implementation-tutorial
- asyncio race conditions: https://superfastpython.com/asyncio-race-conditions/
- Multi-agent orchestration resource conflicts: https://gerred.github.io/building-an-agentic-system/second-edition/part-iv-advanced-patterns/chapter-10-multi-agent-orchestration.html
- Cross-platform PowerShell scripting tips: https://jdhitsolutions.com/blog/scripting/7361/powershell-7-cross-platform-scripting-tips-and-traps/
- aiosqlite concurrent write contention: https://github.com/omnilib/aiosqlite/issues/258
- Existing codebase: tools/node_sync.py, dashboard/auth.py, memory/effectiveness.py, tools/registry.py, core/agent_manager.py, scripts/cowork/coworker-daemon.sh, setup.sh
- Agent42 CLAUDE.md pitfalls 83, 87, 91, 93, 94, 104-108, 113 (directly inform multi-agent race, RBAC, sync, and setup pitfalls above)

---
*Pitfalls research for: bi-directional vector sync, enterprise RBAC, multi-agent orchestration, cross-platform setup, and deep jcodemunch integration added to Agent42*
*Researched: 2026-03-17*
