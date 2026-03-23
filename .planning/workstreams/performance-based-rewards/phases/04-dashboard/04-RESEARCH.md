# Phase 04: Dashboard - Research

**Researched:** 2026-03-23
**Domain:** FastAPI dashboard extension — REST API, WebSocket broadcast, and vanilla-JS frontend integration
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** All rewards endpoints added inline in `create_app()` using `@app.get/post/patch` with per-endpoint `Depends()` decorators — no `APIRouter` (none exists in codebase). Read endpoints use `Depends(get_current_user)`, mutations use `Depends(require_admin)`.
- **D-02:** Rewards API block gated behind `if agent_manager:` check, with `reward_system` parameter added to `create_app()` — follows existing optional capability injection pattern (`if project_manager:`, `if channel_manager:`).
- **D-03:** Endpoints:
  - `GET /api/rewards` — system status (enabled, config, tier counts)
  - `POST /api/rewards/toggle` — enable/disable via RewardsConfig.save() (ADMN-02)
  - `GET /api/agents/{id}/performance` — score, tier, task count, success rate
  - `PATCH /api/agents/{id}/reward-tier` — set tier_override via AgentManager.update()
  - `POST /api/admin/rewards/recalculate-all` — trigger immediate recalculation
- **D-04:** All endpoints return 401 for unauthenticated requests (TEST-04 verifies this for every endpoint).
- **D-05:** `tier_update` WebSocket event broadcast from two sources: (1) the override endpoint in server.py when admin sets override, (2) `TierRecalcLoop` after each recalculation cycle.
- **D-06:** `TierRecalcLoop` receives `ws_manager` as constructor argument and calls `ws_manager.broadcast("tier_update", data)` after updating tiers — matches `HeartbeatService` pattern for `system_health` events.
- **D-07:** Frontend `handleWSMessage` in `app.js` gets a new `tier_update` case that refreshes agent card badges without full page reload.
- **D-08:** `effective_tier` field added to `AgentConfig.to_dict()` — exposed via existing `GET /api/agents` response. No separate per-agent tier fetch (prevents N+1).
- **D-09:** Tier badge on agent cards — modify `_renderAgentCards()` in `app.js` to show Bronze/Silver/Gold/Provisional badge using the existing `badge-tier` CSS class pattern.
- **D-10:** Performance metrics panel per agent — score, tier, task count, success rate displayed when clicking an agent card. Data from `GET /api/agents/{id}/performance`.
- **D-11:** Rewards toggle in settings page — switch with confirmation dialog. Calls `POST /api/rewards/toggle`.
- **D-12:** Admin tier override UI — dropdown on agent detail view, calls `PATCH /api/agents/{id}/reward-tier`. Optional expiry date field.

### Claude's Discretion

- Exact CSS styling for tier badges (colors, positioning)
- Performance metrics panel layout and chart style
- Confirmation dialog copy for toggle
- Whether override expiry is a date picker or text input
- Error toast styling for failed operations

### Deferred Ideas (OUT OF SCOPE)

- Override expiry auto-enforcement (background job that clears expired overrides) — v2
- Tier change audit log display — v2
- Score trend charts (need 4+ weeks of data) — v2
- Fleet-level tier analytics dashboard — v2
- Hysteresis controls in settings — v2
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ADMN-02 | Admin can toggle rewards system on/off via dashboard without server restart | `POST /api/rewards/toggle` calls `RewardsConfig.save()`; mtime cache means all callers pick up the new value without restart |
| DASH-01 | Tier badge displayed on each agent card (Bronze/Silver/Gold/Provisional) | `effective_tier` exposed via `GET /api/agents` (already in `to_dict()` via `asdict()`); `_renderAgentCards()` extended with tier badge using `badge-tier` CSS class |
| DASH-02 | Performance metrics panel per agent showing score, tier, task count, success rate | `GET /api/agents/{id}/performance` returns all four fields; `agentShowDetail()` extended to fetch and render them |
| DASH-03 | Rewards system toggle switch with confirmation dialog in settings | Settings page extended with a toggle calling `POST /api/rewards/toggle`; confirmation via `confirm()` dialog |
| DASH-04 | Admin tier override UI with optional expiry date | Dropdown in `agentShowDetail()` calling `PATCH /api/agents/{id}/reward-tier`; expiry field as text input (ISO date) |
| DASH-05 | Real-time tier updates via WebSocket `tier_update` events | `TierRecalcLoop` gets `ws_manager` constructor arg and calls `broadcast("tier_update", ...)` after each recalc; `handleWSMessage` gets new `tier_update` case |
| TEST-04 | Dashboard API tests including 401 auth verification for all rewards endpoints | New `tests/test_rewards_api.py` using `TestClient(create_app(...))` pattern; one `401` assertion per endpoint; one happy-path assertion per endpoint |
</phase_requirements>

---

## Summary

Phase 4 is a pure integration phase — it wires previously built backend components (Phases 1-3) into the existing dashboard. The work breaks into three layers: (1) server-side REST endpoints in `dashboard/server.py`, (2) WebSocket broadcast from `TierRecalcLoop`, and (3) frontend changes in the compiled `dashboard/frontend/dist/app.js`.

The codebase already has every pattern this phase needs. The dashboard follows a strict convention: optional capabilities are injected as `create_app()` keyword arguments, each guarded by an `if capability:` block, with per-endpoint `Depends(get_current_user)` or `Depends(require_admin)`. The WebSocket broadcast infrastructure (`ws_manager.broadcast(event_type, data)`) is already used by heartbeat, app status, task, project, and chat events — `tier_update` is a new entry in the same dispatch table.

The most significant gap found during research is that `reward_system` is NOT currently passed to `create_app()` in `agent42.py` — it is constructed and started, but never exposed to the server. This is the primary wiring task. Similarly, `TierRecalcLoop` currently has no `ws_manager` parameter and does not broadcast after recalculation. Both are additive constructor changes, not refactors.

**Primary recommendation:** Follow the established `HeartbeatService` + `project_manager` patterns exactly — add `reward_system` param to `create_app()`, add `ws_manager` to `TierRecalcLoop.__init__()`, add rewards endpoint block gated on `if agent_manager and reward_system:`, extend frontend in-place. Test with `TestClient` pattern matching `test_auth_flow.py`.

---

## Standard Stack

### Core (all already present — no new installations)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | (existing) | REST API + WebSocket | Already powering the dashboard |
| pydantic | (existing) | Request body validation | Used by all existing endpoints |
| starlette | (existing) | HTTP/WS transport | FastAPI dependency |
| pytest + fastapi.testclient | (existing) | API tests without live server | Used by `test_auth_flow.py`, `test_resource_enforcement.py` |

### No new packages required

This phase adds endpoints, frontend code, and constructor arguments to existing classes. Zero new dependencies.

---

## Architecture Patterns

### Pattern 1: Optional Capability Injection in `create_app()`

The dashboard is parameterized — every optional subsystem is a keyword argument. The pattern from `channels`:

```python
# dashboard/server.py — existing pattern (line ~4396)
@app.get("/api/channels")
async def list_channels(_user: str = Depends(get_current_user)):
    if channel_manager:
        return channel_manager.list_channels()
    return []
```

For rewards, the block is gated on both `agent_manager` AND `reward_system` (D-02):

```python
# New pattern for this phase:
def create_app(
    ...
    agent_manager=None,   # already present
    reward_system=None,   # NEW: add this parameter
) -> FastAPI:
    ...
    if agent_manager and reward_system:
        class RewardsToggleRequest(BaseModel):
            enabled: bool

        class TierOverrideRequest(BaseModel):
            tier: str
            expires_at: str | None = None

        @app.get("/api/rewards")
        async def get_rewards_status(_user: str = Depends(get_current_user)):
            from core.rewards_config import RewardsConfig
            cfg = RewardsConfig.load()
            agents = _agent_manager.list_all()
            tier_counts = {"bronze": 0, "silver": 0, "gold": 0, "provisional": 0}
            for a in agents:
                t = a.effective_tier()
                if t in tier_counts:
                    tier_counts[t] += 1
            return {"enabled": cfg.enabled, "config": {...}, "tier_counts": tier_counts}

        @app.post("/api/rewards/toggle")
        async def toggle_rewards(
            req: RewardsToggleRequest,
            _admin: AuthContext = Depends(require_admin),
        ):
            from core.rewards_config import RewardsConfig
            cfg = RewardsConfig.load()
            updated = RewardsConfig(
                enabled=req.enabled,
                silver_threshold=cfg.silver_threshold,
                gold_threshold=cfg.gold_threshold,
            )
            updated.save()
            return {"enabled": req.enabled}
```

### Pattern 2: Auth Dependency Usage

**Reads** — return `_user: str = Depends(get_current_user)`:
```python
@app.get("/api/agents/{agent_id}/performance")
async def agent_performance(agent_id: str, _user: str = Depends(get_current_user)):
    ...
```

**Mutations** — return `_admin: AuthContext = Depends(require_admin)`:
```python
@app.patch("/api/agents/{agent_id}/reward-tier")
async def set_reward_tier(
    agent_id: str,
    req: TierOverrideRequest,
    _admin: AuthContext = Depends(require_admin),
):
    ...
```

`require_admin` blocks device API keys (returns 403), while `get_current_user` allows both JWT and API keys. Mutations must use `require_admin`.

### Pattern 3: WebSocket Broadcast from Background Service

Existing `HeartbeatService` pattern — the on_heartbeat callback broadcasts `system_health`. For `TierRecalcLoop`, add `ws_manager` to constructor and call after each tier update:

```python
# core/reward_system.py — TierRecalcLoop extension
class TierRecalcLoop:
    def __init__(
        self,
        agent_manager,
        reward_system: RewardSystem,
        effectiveness_store,
        interval: int = 900,
        ws_manager=None,        # NEW: optional, follows HeartbeatService pattern
    ) -> None:
        ...
        self._ws_manager = ws_manager

    async def _run_recalculation(self) -> None:
        changed = []
        for agent in agents:
            ...
            if tier != old_tier:
                changed.append({"agent_id": agent.id, "tier": tier, "score": score})
        # Broadcast all changes after loop — one WS message per cycle, not per agent
        if changed and self._ws_manager:
            await self._ws_manager.broadcast("tier_update", {"agents": changed})
```

The broadcast happens AFTER the loop — not per-agent. This matches the `system_health` pattern where one message carries the full state snapshot.

### Pattern 4: `effective_tier` Already in `to_dict()`

`AgentConfig.to_dict()` uses `asdict(self)` which automatically serializes ALL dataclass fields. `effective_tier` is a method, not a field, so it is NOT included automatically. D-08 requires adding it explicitly:

```python
# core/agent_manager.py
def to_dict(self) -> dict:
    d = asdict(self)
    d["effective_tier"] = self.effective_tier()   # add computed field
    return d
```

This is the single change that populates the tier badge on every agent card without an N+1 fetch.

### Pattern 5: Frontend JS Extension

The frontend is a single compiled `app.js` file at `dashboard/frontend/dist/app.js`. All changes are in-place edits to this file. No build step — the file is served as-is.

**Tier badge in `_renderAgentCards()` (line ~2249):** The card HTML currently shows one `badge-tier` for agent status. A second badge for reward tier is added inline:

```javascript
// Existing badge (status):
'<span class="badge-tier" style="background:' + color + ';color:#000">' + esc(a.status) + '</span>'

// Add after it (reward tier, only when present):
+ (a.effective_tier ? '<span class="badge-tier" style="background:' + tierColor(a.effective_tier) + ';color:#000;margin-left:0.3rem">' + esc(a.effective_tier) + '</span>' : '')
```

**`tier_update` case in `handleWSMessage()` (line ~488):**

```javascript
} else if (msg.type === "tier_update") {
    // Update in-state agents array with new tiers
    (msg.data.agents || []).forEach(function(u) {
        var idx = state.agents ? state.agents.findIndex(function(a) { return a.id === u.agent_id; }) : -1;
        if (idx >= 0) { state.agents[idx].effective_tier = u.tier; state.agents[idx].performance_score = u.score; }
    });
    if (state.page === "agents") renderAgents();
}
```

**Override dropdown in `agentShowDetail()` (line ~2372):** The detail view already fetches `/api/agents/{id}` and renders fields into a grid. Extend by appending a rewards section below the existing grid.

**Rewards toggle in settings page:** Find the settings page render function and add a toggle row. Use `confirm()` for the confirmation dialog (consistent with `agentDelete()` which uses `confirm("Delete this agent?")`).

### Recommended Project Structure (changes only)

```
dashboard/
├── server.py                    # Add reward_system param, add 5 endpoints
├── frontend/dist/
│   └── app.js                   # Add tier badges, tier_update WS case, override UI, toggle UI
core/
└── reward_system.py             # Add ws_manager param to TierRecalcLoop
agent42.py                       # Pass reward_system to create_app()
tests/
└── test_rewards_api.py          # New file: 401 tests + happy-path tests (TEST-04)
```

### Anti-Patterns to Avoid

- **Global endpoint definitions outside `create_app()`:** All agent/rewards endpoints live inside `create_app()`. If endpoints are defined at module level, they cannot be conditionally registered.
- **Broadcasting per-agent inside the recalc loop:** One `broadcast()` call per cycle (after the loop) prevents flooding the WebSocket with N messages for N agents.
- **Using `asdict()` and assuming methods are included:** `asdict()` only serializes dataclass fields. Methods like `effective_tier()` must be added explicitly to the dict.
- **Importing `rewards_config` at module level in `server.py`:** Import inside the endpoint function body (as `from core.rewards_config import RewardsConfig`) to avoid circular imports and keep optional-capability behavior consistent.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Request body validation | Custom parsing | `pydantic BaseModel` inside `create_app()` | Already used by every existing endpoint |
| Auth checking | Manual token inspection | `Depends(get_current_user)` / `Depends(require_admin)` | Handles JWT + API key, expiry, 401/403 |
| WebSocket broadcast | Custom WS loop | `ws_manager.broadcast(event_type, data)` | Handles dead connections, cleanup, JSON serialization |
| Config toggle persistence | Custom file write | `RewardsConfig.save()` | Atomic write via `os.replace()`, mtime cache invalidation |
| Agent update | Direct dict mutation | `_agent_manager.update(agent_id, **fields)` | Handles persistence, updated_at, unknown agent |

---

## Common Pitfalls

### Pitfall 1: `reward_system` not passed to `create_app()` (pre-existing gap)

**What goes wrong:** `reward_system` is constructed in `agent42.py` but the current `create_app()` call (line ~229) does not pass it. Adding rewards endpoints without also updating `agent42.py` means the block is always skipped (both params must be truthy per D-02).
**How to avoid:** Add `reward_system=self.reward_system` to the `create_app()` call in `agent42.py` as part of the wiring task.
**Warning signs:** Rewards endpoints always return 404 in integration tests.

### Pitfall 2: `effective_tier` not in `to_dict()` output

**What goes wrong:** `asdict()` only serializes declared `@dataclass` fields. `effective_tier()` is a method, not a field. The frontend receives `null`/`undefined` for `a.effective_tier`, and tier badges never appear.
**How to avoid:** Explicitly add `d["effective_tier"] = self.effective_tier()` after `asdict(self)` call.
**Warning signs:** Agent card tier badge is absent even when tiers are assigned.

### Pitfall 3: WS broadcast inside `if tier != old_tier` check

**What goes wrong:** Broadcasting one WS message per changed agent causes N separate `broadcast()` calls per recalc cycle. Each call iterates the full connection list.
**How to avoid:** Collect changed agents into a list during the loop, then broadcast once after the loop.
**Warning signs:** Many simultaneous WS messages arriving at the frontend during recalc.

### Pitfall 4: `require_admin` vs `get_current_user` confusion

**What goes wrong:** Using `get_current_user` on a mutation endpoint allows device API keys to toggle rewards or override tiers. `require_admin` explicitly blocks device keys with a 403.
**How to avoid:** All `POST`/`PATCH` rewards endpoints must use `Depends(require_admin)`.
**Warning signs:** TEST-04 test passes for 401 but a device API key can call toggle.

### Pitfall 5: Frontend `state.agents` array not available during WS event

**What goes wrong:** The `tier_update` WS handler tries to update `state.agents`, but this field does not exist in the initial `state` object — the agents page fetches fresh via API. If `state.agents` is undefined, `findIndex()` throws.
**How to avoid:** Guard with `state.agents ? ...` before findIndex, or initialize `agents: []` in the state object.
**Warning signs:** Console error in browser when `tier_update` arrives while on another page.

### Pitfall 6: Toggle confirmation dialog blocks async flow

**What goes wrong:** Using `await confirm()` or an async dialog where `confirm()` is expected causes the browser to hang.
**How to avoid:** Use synchronous `confirm("Enable/disable the rewards system?")` inside the click handler — matches the existing `agentDelete()` pattern.
**Warning signs:** Dashboard appears frozen after clicking toggle.

### Pitfall 7: `POST /api/rewards/toggle` returns 404 in tests

**What goes wrong:** If the test creates the app with `create_app(agent_manager=mock_am)` but does not pass `reward_system`, the rewards endpoint block is never registered (gated on both being truthy).
**How to avoid:** TEST-04 fixtures must pass both `agent_manager` AND a `reward_system` mock to `create_app()`.
**Warning signs:** 404 instead of 401 for unauthenticated test requests against rewards endpoints.

---

## Code Examples

Verified patterns from the actual codebase:

### Auth dependency — read endpoint
```python
# Source: dashboard/server.py line 3822
@app.get("/api/agents")
async def list_agents(_user: str = Depends(get_current_user)):
    return [a.to_dict() for a in _agent_manager.list_all()]
```

### Auth dependency — admin mutation endpoint
```python
# Source: dashboard/server.py line 4033
@app.patch("/api/tools/{name}")
async def toggle_tool(
    name: str, req: ToggleRequest, _admin: AuthContext = Depends(require_admin)
):
    ...
```

### Capability-gated endpoint block
```python
# Source: dashboard/server.py line 4393-4399
@app.get("/api/channels")
async def list_channels(_user: str = Depends(get_current_user)):
    if channel_manager:
        return channel_manager.list_channels()
    return []
```

### WebSocket broadcast
```python
# Source: dashboard/websocket_manager.py lines 70-83
async def broadcast(self, event_type: str, data: dict):
    message = json.dumps({"type": event_type, "data": data})
    dead: list[WSConnection] = []
    for conn in self._connections:
        try:
            await conn.ws.send_text(message)
        except Exception as e:
            dead.append(conn)
    for conn in dead:
        self._connections.remove(conn)
```

### Frontend WS event dispatch
```javascript
// Source: dashboard/frontend/dist/app.js line 488
function handleWSMessage(msg) {
  if (msg.type === "task_update") { ... }
  } else if (msg.type === "system_health") { ... }
  } else if (msg.type === "app_status") { ... }
  } else if (msg.type === "project_update") { ... }
  // tier_update case goes here, following same pattern
}
```

### Frontend agent card badge pattern
```javascript
// Source: dashboard/frontend/dist/app.js line 2249
'<span class="badge-tier" style="background:' + color + ';color:#000">' + esc(a.status) + '</span>'
```

### TestClient pattern for 401 testing
```python
# Source: tests/test_auth_flow.py line 127-156
@pytest.fixture
def client(self):
    from dashboard.server import create_app
    from dashboard.websocket_manager import WebSocketManager
    ws_manager = WebSocketManager()
    app = create_app(ws_manager=ws_manager, ...)
    with TestClient(app) as client:
        yield client

def test_protected_endpoint_requires_auth(self, client):
    res = client.get("/api/status")
    assert res.status_code == 401
```

### AgentConfig.to_dict() — current implementation
```python
# Source: core/agent_manager.py line 191
def to_dict(self) -> dict:
    return asdict(self)
```

### TierRecalcLoop — current `_run_recalculation` (no WS broadcast yet)
```python
# Source: core/reward_system.py line 419-450
async def _run_recalculation(self) -> None:
    agents = self._agent_manager.list_all()
    for agent in agents:
        if agent.tier_override is not None:
            continue
        ...
        if tier != old_tier:
            logger.info("Agent %s tier changed: %s -> %s", agent.id, old_tier, tier, score)
```

---

## Integration Points — Complete Map

| File | What Changes | Why |
|------|-------------|-----|
| `dashboard/server.py` | Add `reward_system=None` param to `create_app()` signature | D-02: capability injection |
| `dashboard/server.py` | Add rewards endpoint block (5 endpoints, gated on `if agent_manager and reward_system:`) | D-03 |
| `agent42.py` | Add `reward_system=self.reward_system` to `create_app()` call (~line 229) | Wire Phase 1-3 output into server |
| `core/reward_system.py` | Add `ws_manager=None` to `TierRecalcLoop.__init__()` | D-06 |
| `core/reward_system.py` | Collect changed agents, call `broadcast("tier_update", ...)` after loop in `_run_recalculation()` | D-05, DASH-05 |
| `core/agent_manager.py` | `to_dict()` adds `d["effective_tier"] = self.effective_tier()` | D-08, DASH-01 |
| `dashboard/frontend/dist/app.js` | `_renderAgentCards()` — add tier badge after status badge | D-09, DASH-01 |
| `dashboard/frontend/dist/app.js` | `agentShowDetail()` — fetch performance, add rewards section + override dropdown | D-10, D-12, DASH-02, DASH-04 |
| `dashboard/frontend/dist/app.js` | `handleWSMessage()` — add `tier_update` case | D-07, DASH-05 |
| `dashboard/frontend/dist/app.js` | Settings page render — add rewards toggle with confirm dialog | D-11, DASH-03 |
| `tests/test_rewards_api.py` | New file: TestClient-based tests for all 5 endpoints (401 + happy path) | TEST-04 |

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + fastapi.testclient (already installed) |
| Config file | `pyproject.toml` (asyncio_mode = "auto") |
| Quick run command | `python -m pytest tests/test_rewards_api.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ADMN-02 | `POST /api/rewards/toggle` — 401 unauthenticated, 200 with admin JWT | unit | `pytest tests/test_rewards_api.py::TestRewardsAuth::test_toggle_requires_auth -x` | Wave 0 |
| DASH-01 | `GET /api/agents` includes `effective_tier` field | unit | `pytest tests/test_rewards_api.py::TestRewardsEndpoints::test_agents_list_includes_effective_tier -x` | Wave 0 |
| DASH-02 | `GET /api/agents/{id}/performance` returns score, tier, task_count, success_rate | unit | `pytest tests/test_rewards_api.py::TestRewardsEndpoints::test_agent_performance -x` | Wave 0 |
| DASH-03 | Toggle switch calls correct endpoint — UI-only, no automated test | manual-only | N/A — visual confirmation | N/A |
| DASH-04 | Override dropdown — `PATCH /api/agents/{id}/reward-tier` sets tier_override | unit | `pytest tests/test_rewards_api.py::TestRewardsEndpoints::test_tier_override -x` | Wave 0 |
| DASH-05 | `tier_update` WS event emitted after recalc — WS test or mock | unit | `pytest tests/test_rewards_api.py::TestTierUpdateBroadcast -x` | Wave 0 |
| TEST-04 | All 5 endpoints return 401 for unauthenticated request | unit | `pytest tests/test_rewards_api.py::TestRewardsAuth -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_rewards_api.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_rewards_api.py` — covers ADMN-02, DASH-01, DASH-02, DASH-04, DASH-05, TEST-04

All other test infrastructure (conftest.py, pytest, TestClient) already exists.

---

## Environment Availability

Step 2.6: SKIPPED — no external dependencies. Phase adds endpoints and frontend edits to an existing server. All required libraries (FastAPI, pydantic, pytest) are already installed.

---

## Open Questions

1. **`state.agents` in frontend WS handler**
   - What we know: `handleWSMessage()` runs on every page. The `state` object at line 7 does not declare an `agents` key.
   - What's unclear: Is `state.agents` populated somewhere else, or only inside `renderAgents()` as a local variable?
   - Recommendation: Initialize `agents: []` in the state object alongside the other arrays (`tasks`, `apps`, etc.) so the `tier_update` handler can safely update it.

2. **Settings page render function name**
   - What we know: The settings page exists and has tabs (`settingsTab: "providers"`). The toggle goes on the settings page (D-11).
   - What's unclear: The exact function name and structure of the settings page render was not read during research.
   - Recommendation: Read the settings render function in `app.js` during implementation to find the correct insertion point (search for `settingsTab` or `renderSettings`).

3. **`GET /api/rewards` vs startup gate**
   - What we know: `Settings.rewards_enabled` (frozen) is the startup gate. `RewardsConfig` is the runtime toggle. The endpoint block is only registered when `settings.rewards_enabled=true` at startup (because `reward_system` is `None` otherwise).
   - What's unclear: If a user toggles rewards OFF via the dashboard (RewardsConfig), then restarts with `REWARDS_ENABLED=false`, the endpoints disappear. This is consistent with documented behavior.
   - Recommendation: Document this in `GET /api/rewards` response — add a field distinguishing `startup_enabled` (frozen Settings) from `runtime_enabled` (RewardsConfig).

---

## Sources

### Primary (HIGH confidence)
- `dashboard/server.py` — create_app() signature, endpoint patterns, auth dependencies, WebSocket endpoint, capability injection pattern (if project_manager, if channel_manager) — read directly
- `dashboard/websocket_manager.py` — broadcast() implementation — read directly
- `dashboard/frontend/dist/app.js` — handleWSMessage(), _renderAgentCards(), agentShowDetail(), state object, badge-tier CSS class usage — read directly
- `core/agent_manager.py` — AgentConfig fields, to_dict(), effective_tier() — read directly
- `core/reward_system.py` — TierRecalcLoop constructor, _run_recalculation() — read directly
- `core/rewards_config.py` — load(), save(), mtime cache pattern — read directly
- `agent42.py` — reward_system construction, create_app() call (confirms reward_system NOT currently passed) — read directly
- `dashboard/auth.py` — get_current_user, require_admin, AuthContext — read directly
- `tests/test_auth_flow.py` — TestClient fixture pattern — read directly

### Secondary (MEDIUM confidence)
- CONTEXT.md D-01 through D-12 — locked implementation decisions from discussion phase — read directly

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries are in-use; zero new packages
- Architecture: HIGH — patterns read directly from live code (server.py, app.js, auth.py)
- Pitfalls: HIGH — pitfall 1 (missing reward_system in create_app call) confirmed by direct code inspection of agent42.py line 229

**Research date:** 2026-03-23
**Valid until:** 2026-04-22 (stable codebase; patterns don't change between sessions)
