# Phase 18: Agent Config Backend - Research

**Researched:** 2026-03-07
**Status:** Ready for planning

## 1. Existing Codebase Patterns

### JSON File Persistence with Mtime Caching
`ModelRouter._check_dynamic_routing()` (model_router.py:958-981) reads `data/dynamic_routing.json` lazily with mtime-based cache invalidation:
```python
mtime = routing_path.stat().st_mtime
if mtime != self._dynamic_cache_mtime or self._dynamic_cache is None:
    self._dynamic_cache = json.loads(routing_path.read_text())
    self._dynamic_cache_mtime = mtime
```
This pattern should be reused for `data/agent_routing.json` — same lazy read, same mtime caching.

### Agent Profile System
- `AgentProfile` dataclass (profile_loader.py:38) — has `name`, `description`, `preferred_skills`, `preferred_task_types`, `prompt_overlay`
- `ProfileLoader` (profile_loader.py:58) — `get(name)`, `all_profiles()`, `save_profile()`, `delete_profile()`
- `Task.profile` field (task_queue.py:~264) — stores profile name string, empty = default
- `Agent._resolve_profile(task)` (agent.py:~700) — resolves profile from task, falls back to `profile_loader.get_default()`

### Model Router Resolution Chain
`ModelRouter.get_routing(task_type, context_window)` (model_router.py:247-462):
1. Admin env override (`AGENT42_{TYPE}_MODEL`)
2. Dynamic routing from `data/dynamic_routing.json`
3. Hardcoded `FREE_ROUTING` dict (now `FALLBACK_ROUTING` alias)
4. Policy routing (OR credits)
4b. Gemini Pro upgrade for complex types
5. Trial injection
6. Context window adaptation
7. Primary model health check + API key validation
8. Critic model validation

**Key gap:** `get_routing()` takes `task_type` but NOT `profile_name` — needs a new parameter to look up per-profile overrides.

### Agent Routing Call Path
1. `Agent42._run_agent(task)` creates `Agent(task, ...)`
2. `Agent.__init__` creates `self.router = ModelRouter()`
3. `Agent.run()` calls `self.router.get_routing(task.task_type, context_window=task.context_window)`
4. `task.profile` is available at this point but NOT passed to `get_routing()`

### Dashboard API Patterns
- `/api/profiles` — GET list, POST create (server.py:1036-1065)
- Auth: `Depends(get_current_user)` for reads, `Depends(require_admin)` for writes
- Pattern: check if service exists, raise HTTPException(404) if not
- Pydantic models for request bodies (e.g., `ProfileCreateRequest`)

### Provider/Model Enumeration
- `ProviderRegistry.available_providers()` (registry.py:723) — lists all providers with availability
- `ModelRouter.available_providers()` (model_router.py:922) — delegates to registry
- `ModelRouter.available_models()` (model_router.py:926) — lists all registered models
- Provider availability: checks `os.getenv(provider_spec.api_key_env)`
- Health: `ModelCatalog.is_model_healthy(model_key)` + StrongWall health polling

## 2. Integration Points

### agents/model_router.py
- Add `profile_name: str = ""` parameter to `get_routing()`
- Add mtime-cached lazy reader for `data/agent_routing.json` (reuse `_check_dynamic_routing` pattern)
- Insert profile override check between admin override and dynamic routing
- Add method to resolve effective config: merge profile -> `_default` -> FALLBACK_ROUTING

### agents/agent.py
- `Agent.run()` line ~510: pass `task.profile` to `self.router.get_routing()`
- No other changes needed — profile name already on task

### dashboard/server.py
- Add endpoints: GET/PUT/DELETE `/api/agent-routing/{profile}`, GET `/api/agent-routing`
- Add endpoint: GET `/api/available-models` (grouped by tier, with health)
- Auth: `get_current_user` for reads, `require_admin` for writes
- Wire `model_router` instance from `create_app` closure

### data/agent_routing.json
- New file, auto-created if missing
- Structure: `{"_default": {"primary": "...", "critic": "...", "fallback": "..."}, "coder": {...}, ...}`
- Null/missing fields = inherit from parent level

## 3. Data Flow

### Write Path (API -> Disk)
1. PUT `/api/agent-routing/{profile}` with `{"primary": "strongwall-kimi-k2.5"}`
2. Server validates model keys exist in registry + provider has API key
3. Server reads `data/agent_routing.json`, updates profile entry, writes back
4. Next `get_routing()` call detects mtime change, reloads

### Read Path (get_routing with profile)
1. `Agent.run()` calls `get_routing(task_type, profile_name=task.profile)`
2. Admin override check (unchanged)
3. **NEW: Profile override check** — load `agent_routing.json`, look up `profile_name` then `_default`
4. Merge: profile fields override `_default` fields override FALLBACK_ROUTING fields
5. Critic auto-pair: if critic is null after merge but primary is set, critic = primary
6. Continue with existing policy/trial/health layers

### Effective Config Resolution
```
per-profile override  →  _default override  →  FALLBACK_ROUTING[task_type]
   (explicit)              (explicit)             (hardcoded)
```
Each level only stores explicitly set fields. Merge fills gaps from next level down.

## 4. Available Models Endpoint

### Tier Classification
- **L1**: Models from StrongWall provider (currently just `strongwall-kimi-k2.5`)
- **Fallback**: Models with `ModelTier.FREE` — Cerebras, Groq, Codestral, Gemini (when free tier), OR free models
- **L2**: Models with `ModelTier.PAID` or `ModelTier.CHEAP` from premium providers — Gemini Pro, Claude, GPT-4o, OR paid

### Health Integration
- `ModelCatalog.is_model_healthy(key)` returns bool
- StrongWall has dedicated health polling (Phase 16) with healthy/degraded/unhealthy states
- Combine into per-model `health` field: "healthy" | "degraded" | "unhealthy" | "unknown"

## 5. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Race condition on concurrent writes to agent_routing.json | Use atomic write (write to .tmp, rename) — same pattern as other data/ files |
| Invalid model key in override crashes routing | Validate model exists in MODELS dict + provider has API key on PUT |
| Stale mtime cache if file is written and read in same second | Accept: mtime resolution is 1s on most filesystems, next request catches up |
| Profile name in task doesn't match any override | Fall through to `_default` then FALLBACK_ROUTING — graceful |

---

*Research complete: 2026-03-07*
