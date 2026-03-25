# Common Pitfalls Archive (1-110)

These are resolved pitfalls from earlier development. Loaded on-demand by context-loader
when debugging, fixing bugs, or working on areas covered by these entries.

| # | Area | Pitfall | Correct Pattern |
|---|------|---------|-----------------|
| 1 | Config | Adding env var but not to `Settings` dataclass | Add to `Settings` + `from_env()` + `.env.example` |
| 2 | Async | Using blocking I/O (`open()`) in tools | Use `aiofiles.open()` for all file operations |
| 3 | Security | Disabling sandbox for convenience | Keep `SANDBOX_ENABLED=true`; use `resolve_path()` |
| 4 | Tools | Forgetting to register new tool | Add to `_register_tools()` in `agent42.py` |
| 5 | Tests | Hardcoding `/tmp` paths in tests | Use `tmp_path` fixture for test isolation |
| 6 | Providers | Hardcoding premium model as default | Use `FREE_ROUTING` dict, allow admin override via env |
| 7 | Memory | Not handling missing Qdrant/Redis | Check availability before use; fallback to files |
| 8 | Config | `DASHBOARD_HOST=0.0.0.0` exposed directly | Keep `127.0.0.1`; use nginx for external access |
| 9 | JWT | Not setting `JWT_SECRET` in `.env` | Random secret breaks sessions across restarts |
| 10 | Import | Importing optional deps at module level | Conditional import inside function/method body |
| 11 | Tools | Missing `**kwargs` in `execute()` signature | Always include `**kwargs` for forward compatibility |
| 12 | Security | Logging API keys or tokens | Never log secrets — even at DEBUG level |
| 13 | Shell | Using `subprocess.run(shell=True)` in tools | Route through `CommandFilter` and `Sandbox` |
| 14 | Config | Boolean env vars with wrong parsing | Use `.lower() in ("true", "1", "yes")` pattern |
| 15 | Tasks | Using wrong `TaskType` enum value | Check `core/task_queue.py` for valid values |
| 16 | Catalog | `CatalogEntry.to_dict()` format mismatch with `__init__` | `to_dict()` must output `{"id": ..., "pricing": {"prompt": ..., "completion": ...}}` matching constructor format |
| 17 | Tests | Floating-point equality in composite scores | Use `pytest.approx()` for float comparisons, not `==` |
| 18 | Init Order | `ModelEvaluator` must init before `Learner` | Learner takes `model_evaluator` param — ensure correct order in `agent42.py` |
| 19 | Extensions | `ToolExtension.extends` must match an already-registered tool name | Extensions for nonexistent tools are silently skipped with a warning |
| 20 | Tests | `cryptography` panics with `_cffi_backend` error | Install `cffi` (`pip install cffi`) before running dashboard/auth tests |
| 21 | Apps | App entry point missing PORT/HOST env var reading | Always read `os.environ.get("PORT", "8080")` — AppManager sets these |
| 22 | Apps | New `TaskType` not in `FREE_ROUTING` dict | Add routing entry to `agents/model_router.py` `FREE_ROUTING` for every new TaskType |
| 23 | Formatting | CI fails with `ruff format --check` after merge | Always run `make format` (or `ruff format .`) before committing — especially after merges that touch multiple files |
| 24 | Deploy | Hardcoded domain/port in install scripts and nginx config | Use `__DOMAIN__`/`__PORT__` placeholders in `nginx-agent42.conf`; `install-server.sh` prompts for values and sed-replaces |
| 25 | Deploy | Install scripts leak interactive output when composed | Use `--quiet` flag when calling `setup.sh` from `install-server.sh` to suppress banners and prompts |
| 26 | Dashboard | CSP `script-src 'self'` blocks all inline event handlers (`onclick`, `onsubmit`) | CSP must include `'unsafe-inline'` in `script-src` because `app.js` uses innerHTML with 55+ inline handlers |
| 27 | Startup | `agent42.log` owned by root (from systemd) blocks `deploy` user startup | Catch `PermissionError` on `FileHandler`; fall back to stdout-only logging |
| 28 | Auth | `passlib 1.7.4` crashes with `bcrypt >= 4.1` (wrap-bug detection hashes >72-byte secret) | Use `bcrypt` directly via `_BcryptContext` wrapper in `dashboard/auth.py`; do not use `passlib` |
| 29 | Tokens | `router.complete()` returns `(str, dict\|None)` tuple, not plain `str` | Always unpack: `text, usage = await router.complete(...)` or `text, _ = ...` if usage not needed |
| 30 | Session | `SessionManager.get_messages()` does not exist — use `get_history()` | Call `get_history(channel_type, channel_id, max_messages=N)` instead |
| 31 | Scope | Scope detection LLM call adds latency to every message | Scope check only runs when an active scope exists and task is not yet DONE/FAILED |
| 32 | Interview | New `TaskType.PROJECT_SETUP` not in `_TASK_TYPE_KEYWORDS` — it's triggered via complexity gating, not keywords | Detection flows through `ComplexityAssessor.needs_project_setup` and `IntentClassifier.needs_project_setup`, not keyword matching |
| 33 | Interview | Project interview tool stores state in `PROJECT.json` — if outputs dir changes, sessions are lost | Always use `settings.outputs_dir` consistently; sessions are keyed by `project_id` subdirectory |
| 34 | Dataclass | Duplicate field name in a `@dataclass` silently shadows the first definition — Python does not raise an error | Search for duplicate field names when adding fields to `Task` or other dataclasses; ruff does not catch this |
| 35 | Subprocess | `asyncio.wait_for(proc.communicate(), timeout=N)` cancels the coroutine but orphans the subprocess on `TimeoutError` | Always wrap in `try/except TimeoutError`, then call `proc.kill()` + `await proc.wait()` to reap the process |
| 36 | Async | `asyncio.get_event_loop()` is deprecated since Python 3.10; raises `DeprecationWarning` and may fail if no current loop | Use `asyncio.get_running_loop()` inside coroutines; use `asyncio.new_event_loop()` in non-async startup code |
| 37 | Tokens | CLAUDE.md loaded on every API call wastes ~5K tokens of rarely-needed reference content | Reference docs extracted to `.claude/reference/` and loaded on-demand by `context-loader.py` hook |
| 38 | Providers | `_build_client()` reading `settings.xxx_api_key` misses admin-configured keys — `settings` is frozen at import time, before `KeyStore.inject_into_environ()` runs | Use `os.getenv(spec.api_key_env, "")` in `_build_client()` and related methods so runtime admin keys are picked up |
| 39 | Fallback | `_complete_with_retry` retried 401 auth errors 3x, wasting quota; fallback chain only tried OpenRouter models even when Gemini/OpenAI keys were set | `_is_auth_error()` skips retries like 404 does; `_get_fallback_models()` appends native provider models (Gemini, OpenAI, etc.) when their `api_key_env` is set; fallback loop continues on all errors instead of breaking early |
| 40 | Debugging | Spending hours tracing production failures through code before checking server logs | **Always run `tail -100 ~/agent42/agent42.log` and `journalctl -u agent42 -n 100 --no-pager` first** — the log nearly always pinpoints the exact failure in seconds |
| 41 | Init | `Agent42.__init__()` calls `self.task_queue.on_update(self._on_task_update)` but `_on_task_update` was stripped from `origin/main` — service crashes with `AttributeError` and exits code 0 | Restore `agent42.py` from the branch: `git fetch origin && git checkout origin/dev -- agent42.py && sudo systemctl restart agent42` |
| 42 | Routing | `limit_remaining: null` in OR API misread as "no credits" | `null` = no per-key limit (uses account balance); only `0.0` = exhausted; always check `is_free_tier` first |
| 43 | Routing | Policy routing overrides dynamic routing results | Policy only runs when `dynamic` is None; dynamic routing takes precedence |
| 44 | Catalog | OR pricing is per-token not per-million | Multiply by 1,000,000 before comparing to $/M thresholds |
| 45 | Routing | "balanced" mode degrades silently to free-only when OR balance check fails | Network error on `/api/v1/auth/key` always returns `is_free_tier=True` — safe but silent; check logs for `"Failed to check OpenRouter account"` warnings |
| 46 | Embeddings | OpenRouter `/embeddings` endpoint returns 401 "User not found" for free-tier keys | Auto-detect skips OpenRouter; only OpenAI is used for embeddings. Set `OPENAI_API_KEY` or explicit `EMBEDDING_PROVIDER` |
| 47 | Embeddings | `build_context_semantic` crashes the entire task when embedding API fails at runtime | Wrapped `embeddings.search()` in try/except; falls back to `build_context()` on failure |
| 48 | Providers | `ProviderRegistry._clients` cached stale API keys forever — admin key updates had no effect | `get_client()` now tracks the key used per client and rebuilds when `os.environ` key changes |
| 49 | Retry | OpenAI SDK default `max_retries=2` adds ~2s of hidden retries before our code sees a 429 | Set `max_retries=0` in `_build_client()` — our `_complete_with_retry` handles retries/fallback |
| 50 | Routing | Gemini daily quota exhaustion (`limit: 0`) retried every iteration — 5-7s waste per call | `_failed_models` set tracks 429/404 models per-task; subsequent iterations skip them instantly |
| 51 | Fallback | `_get_fallback_models` included `gemini-2-flash` even when it just failed as primary (same-provider retry) | `_failed_models` propagated to `exclude` param — models that failed in any iteration are excluded from all fallbacks |
| 52 | Catalog | `or-free-devstral` free period ended (404 "free Devstral 2 period has ended") | Replaced with `or-free-qwen-coder` (Qwen3 Coder 480B) in all FREE_ROUTING critic slots |
| 53 | Retry | OpenRouter 402 "API key USD spend limit exceeded" from Venice backend not caught — fell through to generic retry | Added `_is_payment_error()` detecting 402/spend-limit; skips retries + adds to `_failed_models` like 429 |
| 54 | Registry | Dead `or-free-devstral` still in MODELS dict — appeared in fallback list via `free_models()` even after removal from FREE_ROUTING | Removed from MODELS; removing from FREE_ROUTING alone is not enough — `_get_fallback_models` iterates all free models |
| 55 | Security | OWASP/secrets scanner flags test files, security tools, and dashboard frontend as false positive vulnerabilities (177 CRITICAL) | Added `_SCAN_EXCLUDE_DIRS`, `_SCAN_EXCLUDE_FILES`, `_OWASP_EXCLUDE_DIRS` to `security_analyzer.py`; removed duplicate innerHTML regex; fixed overly-broad f-string SQL regex matching "deleted"/"updated" |
| 56 | Registry | 5 dead OpenRouter free models still in MODELS dict — 404s on every health check and appeared in fallback lists | Remove dead models from MODELS dict AND static fallback list in `iteration_engine.py`; pitfall #54 only covered devstral, same pattern recurred for deepseek-r1, llama4-maverick, gemini-flash, gemini-pro |
| 57 | Tools | `test_runner.py` uses `"python"` but production server only has `python3` — `FileNotFoundError: No such file or directory: 'python'` | Use `sys.executable` instead of hardcoded `"python"` for subprocess calls |
| 58 | Providers | `gemini-2.0-flash` deprecated by Google (404 "no longer available to new users") — all 15 task types fail on primary model | Updated `MODELS["gemini-2-flash"]` model_id to `gemini-2.5-flash`; internal key `gemini-2-flash` unchanged |
| 59 | RLM | `rlm.completion()` is synchronous — calling it directly blocks the async event loop | Always wrap in `loop.run_in_executor(None, lambda: rlm.completion(...))` with `asyncio.wait_for` timeout |
| 60 | RLM | RLM recursive sub-calls can produce runaway costs (10x+ expected) | Enforce `RLM_COST_LIMIT` per query and check global `SpendingTracker` before each RLM call |
| 61 | RLM | `rlms` package not installed but `RLM_ENABLED=true` — import fails at runtime | All `from rlm import ...` is inside method bodies behind try/except ImportError; `should_use_rlm()` returns False gracefully |
| 62 | Tools | `_run_tool_loop` re-fetched `all_schemas()` every round, bypassing task-type filtering — non-code tasks got code tools after first tool call | Use `schemas_for_task_type(task_type)` in the tool loop instead of `all_schemas()` |
| 63 | Tools | Free LLMs hallucinate tool calls not in schema — `_execute_tool_calls` had no task-type guard | Added execution-time enforcement: `_CODE_ONLY_TOOLS` blocked for non-`_CODE_TASK_TYPES` in `_execute_tool_calls()` |
| 64 | Async | `SessionManager.add_message()` and `set_active_scope()` used blocking `open()` from async handlers | Converted write-path methods to async with `aiofiles`; callers must use `await` |
| 65 | Tasks | ASSIGNED tasks never re-queued on restart — only RUNNING was reset to PENDING | `load_from_file()` now resets both RUNNING and ASSIGNED to PENDING |
| 66 | Memory | Memory is global — all tasks write to one MEMORY.md regardless of project | Use `ProjectMemoryStore` (created per-project under `projects_dir/{id}/`); falls through to global for standalone tasks |
| 67 | Critic | Critic only sees task + output text — misses tool usage context | `_critic_pass` now receives `tool_records` and `iteration_num`; includes compact tool summary for the critic |
| 68 | Context | Tool results accumulate unbounded in iteration loop — context rot | `_compact_tool_messages` truncates old tool messages to 200 chars when total exceeds 50K chars; last 2 tool messages kept intact |
| 69 | Teams | Team/subagent tasks don't inherit `project_id` — learnings scatter to global | `TeamTool`, `SubagentTool`, and manager tasks now propagate `project_id` from parent context |
| 70 | Tiers | L2 enabled but no premium API key set — L2 runs on suggested defaults that may lack keys | `get_l2_routing()` verifies API key availability; returns None if premium key not set -> L2 button hidden in dashboard |
| 71 | Escalation | L2 task fails — original L1 task stuck forever | L2 task failure handler in `_on_task_update()` resets L1 source task back to REVIEW status |
| 72 | Conversation | `_direct_response()` blocks event loop if model is slow | Wrapped in `asyncio.wait_for()` with 30s timeout; falls back to task creation on timeout/error |
| 73 | Teams | Team roles inherit tier from parent — L2 team = all premium tokens | Team roles default to L1 via `TeamContext.tier`; only explicitly configured roles use L2 |
| 74 | Serialization | `tier` field not surviving Task persist/restore | `to_dict()`/`from_dict()` handles via `asdict()` — new string fields serialize automatically |
| 75 | Comments | Task comments (`POST /api/tasks/{id}/comment`) were stored but never routed to the running agent or broadcast to chat | Comment endpoint now calls `route_message_to_task()` for active tasks, broadcasts `task_update`, and mirrors to chat session via `chat_message` event |
| 76 | Plans | Manager LLM returns free-text instead of JSON `PlanSpecification` | Always fall back to legacy unstructured path; parse with try/except in `_parse_plan_json()` |
| 77 | Waves | Circular dependencies in plan tasks cause infinite loop in `compute_waves()` | Topological sort must detect cycles and raise `ValueError` — tested in `test_plan_spec.py` |
| 78 | State | `STATE.md` grows unbounded with `accumulated_context` field | Cap at `_MAX_ACCUMULATED_CONTEXT_CHARS` (10K chars); `StateManager.save_state()` enforces this |
| 79 | Context | Context budget estimation uses chars/4 approximation, not actual tokens | Sufficient for threshold detection (50%/70%); not for exact token accounting |
| 80 | Context | Context overflow "error" strategy returns empty output when `primary_output` is still `""` | Guard: `if not primary_output.strip(): primary_output = "Context too large..."` before setting `history.final_output` |
| 81 | Chat | Agent processes dashboard chat messages in isolation — no conversation history | Pass `chat_session_manager` to Agent; load history in `_build_context()` via `origin_metadata["chat_session_id"]` |
| 82 | Prompts | System prompts encouraged confabulation — "never say you don't know" + memory skill implied cross-server recall | Added truthfulness guardrails to `GENERAL_ASSISTANT_PROMPT`, `platform-identity`, and `memory` skills; agent must only reference actual context, never fabricate |
| 83 | Dashboard | `submitCreateTask()` called `doCreateTask()` twice — copy-paste error with separate `projectId` and `repoId` calls | Merge all form fields into a single `doCreateTask(title, desc, type, projectId, repoId, branch)` call |
| 84 | Apps | `install_deps` only checks `apps/{id}/requirements.txt` but agents sometimes place it in `apps/{id}/src/` | Check `src/requirements.txt` as fallback in both `AppTool._install_deps()` and `AppManager._start_python_app()` |
| 85 | Classifier | "Build me a Flask app" misclassified as `marketing` by LLM — keyword fallback had no framework-specific terms | Add framework keywords (`flask app`, `django app`, etc.) to `APP_CREATE` in `_TASK_TYPE_KEYWORDS`; add classification rule to LLM prompt |
| 86 | Dashboard | `/api/reports` crashes with 500 if any service (`model_evaluator`, `model_catalog`, etc.) throws | Wrap endpoint in try/except returning valid empty report structure on failure |
| 87 | Heartbeat | `_monitor_loop` calls `get_health()` with no args — periodic WS broadcasts overwrite tools/tasks with 0 | Store `task_queue` and `tool_registry` on `HeartbeatService`; pass them in the broadcast loop |
| 88 | Heartbeat | `ctypes.windll.psapi.GetProcessMemoryInfo` silently returns 0 on Windows (missing argtypes) | Use `ctypes.WinDLL("psapi")` with explicit `argtypes`/`restype`; also fix macOS `ru_maxrss` bytes-vs-KB conversion |
| 89 | Dashboard | Chat session sidebar empty after server restart — WS reconnect doesn't reload data | Add `loadChatSessions(); loadCodeSessions(); loadTasks(); loadStatus();` to `ws.onopen` when `wsRetries > 0` |
| 90 | Routing | ComplexityAssessor, IntentClassifier, and Learner all used dead OR free models (`or-free-mistral-small`, `or-free-deepseek-chat`) — teams never formed, classification fell back to keywords, learning never happened | Route internal LLM consumers to `gemini-2-flash` (reliable, free tier); don't use OR free models for infrastructure-critical calls |
| 91 | Routing | Critics tried dead OR free models first, then fell back to Gemini — wasted 5-7s per iteration on 429 retries | Validate critic health/API key in `get_routing()` and pre-upgrade to `gemini-2-flash` before task execution begins |
| 92 | RLM | RLM threshold at 50K tokens triggered for most tasks, causing 3-5x token amplification and API rate-limit spikes | Raise `RLM_THRESHOLD_TOKENS` to 200K — RLM should only activate for genuinely massive contexts, not routine tasks |
| 93 | Dispatch | Multiple agents dispatched simultaneously cause Gemini 1M TPM rate-limit spikes | Add `AGENT_DISPATCH_DELAY` (default 2.0s) to stagger agent launches in `_process_queue()` |
| 94 | Deploy | `agent42.py` refactored command handlers into `commands.py` but file wasn't committed — `ModuleNotFoundError` on production startup | Always verify new module files are staged before pushing; `git status` shows untracked files that may be required imports |
| 95 | Auth | Bcrypt password hash in `.env` doesn't match intended password after manual edits — login silently fails with 401 | Regenerate hash on server: `python3 -c "import bcrypt; print(bcrypt.hashpw(b'password', bcrypt.gensalt()).decode())"` and update `.env`; restart service |
| 96 | Dashboard | `project_manager.all_projects()` renamed to `list_projects()` — `/api/reports` crashes with AttributeError | Check method names against current API when refactoring; `server.py` calls must match `project_manager` interface |
| 97 | Dashboard | `skill.enabled` attribute doesn't exist — use `skill_loader.is_enabled(s.name)` instead | Skills don't have an `enabled` field; enablement is managed by the SkillLoader, not the Skill object |
| 98 | Search | Brave Search returns 422 on production — API key or query format issue | `web_search` tool has DuckDuckGo fallback; search still works but with lower quality results. Check `BRAVE_API_KEY` in `.env` |
| 99 | AppTest | `AppTestTool._findings` accumulates across calls — stale findings leak into reports | Call `generate_report` to consume and clear findings, or check `_findings` list is reset between test sessions |
| 100 | AppTest | `app_test smoke_test` returns success even when health check fails | Tool always returns `ToolResult(success=True)` for completed checks — failures are in the output text and findings, not in `success=False` |
| 101 | Critic | Visual critic sends multimodal `content` (list of dicts) but some models only accept string content | `_extract_screenshot_b64` returns None on any failure — critic falls back to text-only; only vision-capable models get image |
| 102 | Apps | `pip install` fails on Ubuntu 24+ with "externally-managed-environment" (PEP 668) | `_ensure_app_venv()` creates a per-app `.venv`; both `_start_python_app()` and `_install_deps()` use the venv's Python for pip and app execution |
| 103 | Memory | `_direct_response()` and server.py conversational path skip memory loading — agent claims no memory of past conversations | Use `build_conversational_memory_context()` helper to inject MEMORY.md + HISTORY.md into system prompt for all response paths |
| 104 | Security | GitHub tokens stored as plaintext in `github_accounts.json` and `settings.json` | Use `core.encryption.encrypt_value()`/`decrypt_value()` with Fernet; legacy plaintext auto-migrates on next persist |
| 105 | Security | GitHub token embedded in clone/push URLs visible in `ps` and `/proc` | Use `core.git_auth.git_askpass_env()` context manager — token is injected via `GIT_ASKPASS` temp script, not URL |
| 106 | Security | `SANDBOX_ENABLED=false` silently disables all path restrictions | `config.py` force-enables sandbox when host is exposed or `SANDBOX_DISABLE_CONFIRM` not set; `sandbox.py` logs CRITICAL |
| 107 | Security | `zipfile.extractall()` vulnerable to zip-slip (path traversal via `../`) | Validate every `zf.namelist()` entry: reject absolute paths, `..` components, and resolved paths outside target |
| 108 | Security | Device API key hashes used plain SHA-256 (no secret) | `_hash_key()` uses HMAC-SHA256 keyed by JWT_SECRET; `validate_api_key()` auto-upgrades legacy SHA-256 hashes |
| 109 | Memory | `QdrantStore.is_available` only checked `self._client is not None` — returned True even when server was unreachable | `is_available` now probes via `get_collections()` with cached TTL (60s success, 15s fail); embedded mode skips probe |
| 110 | Memory | `EmbeddingStore.search()` took Qdrant path when `is_available=True` but never fell through to JSON on Qdrant failure | Refactored to try/except around Qdrant search; falls through to `_search_json()` on any exception |
