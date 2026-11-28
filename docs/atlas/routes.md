# Atlas topic — Frood route categories

This topic file groups Frood's public surface into route categories referenced by
`docs/ATLAS.md`. It is reference documentation only; it does not publish any
STT/Volnova code.

## Route categories

| Category | Scope | What it decides |
|---|---|---|
| Auth | `/api/login`, `/api/logout`, `/api/setup/*`, `/api/settings/password` | Whether a session is established, refreshed, or rejected |
| Health | `/health`, `/api/health`, `/api/setup/status` | Liveness and setup readiness |
| Memory | `/api/memory/search`, `/api/memory/stats`, `/api/knowledge/learn`, `/api/learnings/retrieve`, `/api/consolidate/trigger` | Recall, learnings, and memory-pipeline outcome |
| Effectiveness & recommendations | `/api/effectiveness/*`, `/api/recommendations/retrieve` | Tool success-rate tracking and next-tool recommendation |
| LLM proxy | `/llm/*`, `/v1/messages`, `/api/models/*` | Model routing tier and chat/completions outcome |
| Gateway | `/gw/v1/messages`, `/gw/v1/models`, `/gw/v1/routes`, `/gw/v1/messages/count_tokens` | Terminal Claude Code tier routing over OpenCode Go and Nvidia (plan_route candidate order, pace-gated Go, Nvidia fallback + 429 retry, route table, token/loopback gates) |
| Providers | `/api/providers`, `/api/settings/provider-status`, `/api/cc/pace`, `/api/models/health*` | Provider connectivity and paid/free classification |
| Tools | `/api/tools`, `/api/tools/{name}`, `/api/skills`, `/api/skills/{name}` | Tool/skill enabled/disabled state |
| CLI setup | `/api/cli-setup/detect`, `/api/cli-setup/wire` | Cross-CLI wiring state |
| Settings | `/api/settings/keys`, `/api/settings/env`, `/api/settings/storage*`, `/api/settings/probe-models`, `/api/settings/openrouter-status`, `/api/settings/rlm-status` | Runtime configuration and storage/backend mode |
| Apps Platform | `/api/apps*`, `/apps/{slug}*` | App create/start/stop/delete and reverse-proxy routing |
| WebSocket | `/ws` | Authenticated real-time event broadcast |
| Activity & reports | `/api/activity`, `/api/reports`, `/api/stats/tokens`, `/api/notifications/config` | Administrative analytics and telemetry |

## Outcome convention

Each `decides:` field in `docs/ATLAS.md` names the business outcome the route's
handler produces (for example: "session created or rejected", "learning
persisted to HISTORY.md", "provider classified free/paid"). A handler rename
must be reflected in the same commit's `docs/ATLAS.md`.
