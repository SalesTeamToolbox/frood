---
phase: 53-frontend-identity-sidecar-auth
plan: "02"
status: complete
completed: 2026-04-08T06:30:00.000Z
---

## Plan 53-02: Sidecar Token Provisioning

### What Was Built

Added POST /sidecar/token endpoint for external authentication:

1. **POST /sidecar/token Endpoint** — New endpoint in `dashboard/sidecar.py` that:
   - Accepts `username` + `password` (password flow)
   - Accepts `api_key` (API key flow)
   - Returns signed JWT (24h expiry)
   - Returns 401 for invalid credentials
   - Returns 503 for api_key path if DeviceStore unavailable
   - Rate limited

2. **DeviceStore Injection** — Modified `frood.py` to inject `device_store` into sidecar factory:
   - `_create_sidecar_app(device_store=self.device_store)`
   - Enables api_key validation

3. **Adapter Auto-Provisioning** — Added to `adapters/agent42-paperclip`:
   - `apiKey` field in `SidecarConfig` (types.ts)
   - `setBearerToken` method (client.ts)
   - `provisionToken()` function (adapter.ts)
   - Auto-fetches bearer token on first connect if apiKey configured
   - Auto-retries on 401 with fresh token

### Verification

- `POST /sidecar/token` endpoint exists in sidecar.py
- `SidecarTokenRequest` model accepts `username`, `password`, `api_key`
- `device_store=self.device_store` in frood.py
- `apiKey:` in types.ts
- `setBearerToken` in client.ts
- `provisionToken` in adapter.ts

### Notes

- Health endpoint (`GET /sidecar/health`) remains unauthenticated
- Backward compatible: adapters with existing `bearerToken` config work unchanged
- API key flow requires DeviceStore to be available (503 if missing)