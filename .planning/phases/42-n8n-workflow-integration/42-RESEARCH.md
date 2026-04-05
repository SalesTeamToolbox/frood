# Phase 42: N8N Workflow Integration — Research

**Researched:** 2026-04-05
**Domain:** N8N REST API v1, Docker deployment, workflow JSON schema
**Confidence:** HIGH (primary findings from official OpenAPI spec and GitHub source)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Two separate tools — `n8n_workflow` (list/trigger/monitor) and `n8n_create_workflow` (design and deploy from natural language)
- **D-02:** Both inherit from `Tool` ABC in `tools/base.py`, return `ToolResult`, registered in `mcp_server.py` `_build_registry()`
- **D-03:** Both use `httpx.AsyncClient` for N8N API calls
- **D-04:** `list` — returns all workflows with id, name, active status, tags
- **D-05:** `trigger` — executes a workflow by ID with optional input JSON, returns execution ID
- **D-06:** `status` — polls execution by ID, returns state and output data
- **D-07:** `output` — retrieves completed execution output data
- **D-08:** `n8n_create_workflow` — NL description → N8N workflow JSON → POST to N8N API
- **D-09:** Workflow templates stored in `tools/n8n_templates/`
- **D-10:** Generated workflows validated before deployment — reject dangerous nodes unless `N8N_ALLOW_CODE_NODES=true`
- **D-11:** Add `n8n_url` and `n8n_api_key` to `Settings` in `core/config.py`
- **D-12:** Env vars: `N8N_URL` and `N8N_API_KEY`
- **D-13:** Add `N8N_ALLOW_CODE_NODES` (bool, default false)
- **D-14:** Graceful degradation — return "N8N not configured" when URL/key missing
- **D-15:** Auth via `X-N8N-API-KEY` header
- **D-16:** API base: `{N8N_URL}/api/v1/` with endpoints: workflows, workflows/{id}/execute, executions/{id}
- **D-17:** Timeout 30s trigger, 10s list/status
- **D-18:** N8N via Docker (`n8nio/n8n`) on port 5678
- **D-19:** Local dev: `docker run` documented in `.env.example`
- **D-20:** Production (Contabo VPS): persistent Docker container, added to existing docker-compose
- **D-21:** N8N URL validated through `UrlPolicy` SSRF checks
- **D-22:** Rate limiting via `core/rate_limiter.py` — 10 trigger calls/minute default
- **D-23:** Workflow creation restricts dangerous N8N nodes by default

### Claude's Discretion

- Exact N8N template file format and bundled template selection
- Error message wording and retry logic
- Execution polling interval (suggest 2s)
- Whether to cache workflow list locally

### Deferred Ideas (OUT OF SCOPE)

- Workflow marketplace/sharing between Agent42 instances
- N8N credential management through Agent42 UI
- Scheduled/cron workflow triggers from Agent42
- Workflow versioning and rollback
- N8N cluster mode for high-availability
</user_constraints>

---

## Summary

N8N provides a public REST API v1 (OpenAPI spec version 1.1.1) that covers workflow CRUD, execution management, credentials, tags, variables, and more. The API uses a simple API key authentication model via `X-N8N-API-KEY` header.

**Critical finding:** There is NO dedicated `POST /workflows/{id}/execute` endpoint in N8N's public API. Direct workflow execution by ID is not supported via the REST API. The correct approach is to use **webhook-triggered workflows** — a workflow with a Webhook trigger node exposes a URL at `{N8N_URL}/webhook/{path}` that accepts HTTP requests. This means `n8n_workflow trigger` must work differently than D-16 assumes: instead of calling `/api/v1/workflows/{id}/execute`, the tool must store and call the workflow's webhook URL.

**Primary recommendation:** Design `n8n_workflow trigger` to call the workflow's webhook URL (stored as a tag or returned when listing workflows), not a direct execution API endpoint. The REST API is used for list/status/output; webhook URL is used for trigger.

**Second critical finding:** Execution status polling via `GET /executions/{id}` requires `?includeData=true` to get output data. The status field is present on single-execution responses but has a known bug where it may be absent from list responses in some versions.

---

## Section 1: Authentication

**Confidence: HIGH** — Verified from official OpenAPI spec and documentation.

### API Key Header

```
X-N8N-API-KEY: <your-api-key>
```

Header name: `X-N8N-API-KEY` (exact, case-sensitive per HTTP convention).

### Creating an API Key

1. Log in to N8N → Settings → n8n API
2. Click "Create an API key"
3. Set a Label and Expiration time
4. Copy the key immediately — it is not shown again
5. On enterprise plans: select Scopes (see below)

### API Key Scopes (Enterprise only)

Non-enterprise keys have full access. Enterprise keys can be scoped to:

| Scope | Capability |
|-------|-----------|
| `workflow:read` | List and retrieve workflows |
| `workflow:create` | Create new workflows |
| `workflow:update` | Update existing workflows |
| `workflow:delete` | Delete workflows |
| `workflow:execute` | [UNVERIFIED - may not apply to webhook trigger] |
| `credential:read/create/update/delete` | Credential management |
| `execution:read` | Get execution by ID |
| `execution:list` | List executions |

### curl Example

```bash
curl -X GET \
  -H "X-N8N-API-KEY: n8n_api_your_key_here" \
  -H "Content-Type: application/json" \
  http://localhost:5678/api/v1/workflows
```

### Enabling the Public API

The public API is **enabled by default** (`N8N_PUBLIC_API_DISABLED=false`). To disable:

```bash
N8N_PUBLIC_API_DISABLED=true
```

Swagger UI (API playground) can be disabled separately:
```bash
N8N_PUBLIC_API_SWAGGERUI_DISABLED=true
```

---

## Section 2: Workflow CRUD Endpoints

**Confidence: HIGH** — Verified from official OpenAPI spec (n8n-docs/docs/api/v1/openapi.yml).

All endpoints use base URL: `{N8N_URL}/api/v1/`

### 2.1 List Workflows

```
GET /api/v1/workflows
```

**Query parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `active` | boolean | Filter by active status |
| `tags` | string | Filter by tag names |
| `name` | string | Filter by workflow name |
| `limit` | integer | Page size (default: 100, max: 250) |
| `cursor` | string | Pagination cursor from previous response |
| `excludePinnedData` | boolean | Exclude pinned test data |

**Response:**
```json
{
  "data": [
    {
      "id": "abc123",
      "name": "My Workflow",
      "active": true,
      "tags": [{"id": "tag1", "name": "automation"}],
      "createdAt": "2024-01-01T00:00:00.000Z",
      "updatedAt": "2024-01-15T10:30:00.000Z",
      "versionId": "v1"
    }
  ],
  "nextCursor": "MTIzZTQ1NjctZTg5Yi0x..."
}
```

**Pagination pattern:**
```python
# Fetch all workflows
cursor = None
all_workflows = []
while True:
    params = {"limit": 250}
    if cursor:
        params["cursor"] = cursor
    resp = await client.get("/api/v1/workflows", params=params)
    data = resp.json()
    all_workflows.extend(data["data"])
    cursor = data.get("nextCursor")
    if not cursor:
        break
```

### 2.2 Get Single Workflow

```
GET /api/v1/workflows/{id}
```

**Response:** Full workflow object including nodes, connections, settings (same schema as create response).

### 2.3 Create Workflow

```
POST /api/v1/workflows
```

**Required fields:** `name`, `nodes`, `connections`, `settings`

**Minimal valid request body:**
```json
{
  "name": "My Automation",
  "nodes": [
    {
      "id": "node-uuid-1",
      "name": "Webhook",
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 2,
      "position": [250, 300],
      "parameters": {
        "httpMethod": "POST",
        "path": "my-automation",
        "responseMode": "onReceived"
      }
    }
  ],
  "connections": {},
  "settings": {
    "executionOrder": "v1"
  }
}
```

**Response:** Full workflow object with assigned `id`.

### 2.4 Update Workflow

```
PUT /api/v1/workflows/{id}
```

Same body schema as create. Automatically re-publishes if workflow is already active.

### 2.5 Delete Workflow

```
DELETE /api/v1/workflows/{id}
```

Returns the deleted workflow object.

### 2.6 Activate / Deactivate Workflow

```
POST /api/v1/workflows/{id}/activate
POST /api/v1/workflows/{id}/deactivate
```

Activate accepts optional body: `{ "versionId": "...", "name": "...", "description": "..." }`

Returns the updated workflow object. A workflow must be saved AND active for its webhook URL to be live.

---

## Section 3: Execution Endpoints and Trigger Strategy

**Confidence: HIGH for endpoints; HIGH for the "no direct execute" finding**

### CRITICAL: No Direct Execute Endpoint

There is **no `POST /api/v1/workflows/{id}/execute` endpoint** in the N8N public API. This contradicts D-16 in CONTEXT.md, which needs a design revision.

The only documented execution trigger method via REST is the **webhook trigger** pattern.

### Trigger Strategy: Webhook-Based Execution

Workflows must have a **Webhook trigger node** (`n8n-nodes-base.webhook`). The agent calls the webhook URL directly, not the API.

**Webhook URL format:**
- Production (workflow active): `{N8N_URL}/webhook/{path}`
- Test (workflow inactive): `{N8N_URL}/webhook-test/{path}`

**Trigger a workflow:**
```bash
curl -X POST \
  http://localhost:5678/webhook/my-automation \
  -H "Content-Type: application/json" \
  -d '{"input_param": "value", "data": {"key": "value"}}'
```

No API key is required for webhook calls (the webhook URL itself is the auth). The webhook path is set in the node's `parameters.path` field when creating/editing the workflow.

**Implication for `n8n_workflow trigger`:** The tool needs to know the webhook URL, not just the workflow ID. This means either:
1. Store the webhook path as a workflow tag (e.g., `webhook:my-automation`)
2. Fetch the workflow JSON and extract `nodes[type=webhook].parameters.path`
3. Require the caller to pass a webhook path explicitly

Option 2 is the most robust: call `GET /api/v1/workflows/{id}`, find the webhook node, construct the URL.

### 3.1 List Executions

```
GET /api/v1/executions
```

**Query parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `workflowId` | string | Filter by workflow |
| `status` | enum | `canceled`, `error`, `success`, `waiting` |
| `includeData` | boolean | Include execution output data |
| `limit` | integer | Page size (default: 100, max: 250) |
| `cursor` | string | Pagination cursor |

**Known bug:** `status=running` is NOT accepted as a filter value despite being documented in some places. The status field may be absent from list response items in some N8N versions (bug #20706).

### 3.2 Get Execution (for status/output)

```
GET /api/v1/executions/{id}
GET /api/v1/executions/{id}?includeData=true
```

**Response (without includeData):**
```json
{
  "id": 1234,
  "status": "success",
  "finished": true,
  "mode": "webhook",
  "startedAt": "2024-01-01T10:00:00.000Z",
  "stoppedAt": "2024-01-01T10:00:05.123Z",
  "workflowId": "abc123",
  "retryOf": null,
  "retrySuccessId": null,
  "waitTill": null
}
```

**Response (with includeData=true) — execution data structure:**
```json
{
  "id": 1234,
  "status": "success",
  "data": {
    "resultData": {
      "runData": {
        "Webhook": [
          {
            "startTime": 1704067205000,
            "executionTime": 12,
            "data": {
              "main": [[
                {"json": {"input": "value"}, "pairedItem": {"item": 0}}
              ]]
            }
          }
        ],
        "HTTP Request": [
          {
            "data": {
              "main": [[
                {"json": {"response": "data"}}
              ]]
            }
          }
        ]
      }
    }
  }
}
```

The last node's output is in `data.resultData.runData[<last_node_name>][0].data.main[0]` — an array of `{"json": {...}}` items.

### Execution Status Values

| Status | Meaning |
|--------|---------|
| `new` | Queued, not started |
| `running` | Currently executing |
| `success` | Completed successfully |
| `error` | Completed with error |
| `canceled` | Manually canceled |
| `crashed` | Crashed unexpectedly |
| `waiting` | Waiting for external event (e.g., wait node) |
| `unknown` | Status cannot be determined |

### 3.3 Delete Execution

```
DELETE /api/v1/executions/{id}
```

### 3.4 Stop Execution

```
POST /api/v1/executions/{id}/stop
POST /api/v1/executions/stop   # body: {"status": ["running"]}
```

### Execution Polling Pattern

Since webhook triggers are fire-and-forget, the execution ID is NOT returned by the webhook call. To get execution results:

```python
# Option 1: Poll GET /executions?workflowId={id}&limit=1 after trigger
# Sort by most recent — the latest execution is the one just triggered
# This is racy in concurrent environments

# Option 2: Use webhook "Respond to Webhook" node to return data inline
# The webhook call blocks until the workflow completes and returns data
# Set responseMode="lastNode" on the webhook node

# Option 3: Two-phase — trigger returns immediately, caller polls by workflowId
```

**Recommended:** Use `responseMode=lastNode` on webhook nodes so the HTTP response contains the workflow output. This makes trigger synchronous and eliminates the need for polling.

---

## Section 4: Workflow JSON Schema

**Confidence: HIGH** — Verified from official OpenAPI spec and GitHub source.

### Complete Workflow Object

```json
{
  "id": "workflow-id-string",
  "name": "Workflow Name",
  "active": false,
  "nodes": [...],
  "connections": {...},
  "settings": {
    "executionOrder": "v1",
    "saveExecutionProgress": false,
    "saveManualExecutions": true,
    "saveDataErrorExecution": "all",
    "saveDataSuccessExecution": "errors",
    "executionTimeout": -1,
    "timezone": "UTC",
    "callerPolicy": "workflowsFromSameOwner"
  },
  "staticData": null,
  "pinData": null,
  "versionId": "version-uuid",
  "tags": [{"id": "tag-id", "name": "tag-name"}],
  "meta": {
    "templateCredsSetupCompleted": true,
    "instanceId": "source-instance-id"
  },
  "createdAt": "2024-01-01T00:00:00.000Z",
  "updatedAt": "2024-01-15T10:30:00.000Z"
}
```

### Node Object Schema

```json
{
  "id": "unique-uuid-per-node",
  "name": "Display Name",
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.1,
  "position": [250, 300],
  "parameters": {
    "httpMethod": "GET",
    "url": "https://api.example.com/data"
  },
  "credentials": {
    "credentialTypeName": {
      "id": "credential-id",
      "name": "My API Credential"
    }
  },
  "disabled": false,
  "webhookId": "only-for-webhook-nodes"
}
```

**Required node fields:** `id` (unique UUID), `name`, `type`, `typeVersion`, `position`
**Optional:** `parameters`, `credentials`, `disabled`, `webhookId`

### Connections Object Schema

```json
{
  "connections": {
    "Source Node Name": {
      "main": [
        [
          {
            "node": "Target Node Name",
            "type": "main",
            "index": 0
          }
        ]
      ]
    }
  }
}
```

- Key is the source node's `name` (not `id`)
- `main` is an array of output ports
- Each port is an array of connections (supporting fan-out)
- `index` refers to the target node's input port number

### Minimal Webhook Workflow Template

```json
{
  "name": "Agent Task: {description}",
  "active": false,
  "nodes": [
    {
      "id": "trigger-node-uuid",
      "name": "Webhook",
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 2,
      "position": [250, 300],
      "parameters": {
        "httpMethod": "POST",
        "path": "{unique-slug}",
        "responseMode": "lastNode",
        "responseData": "allEntries"
      }
    }
  ],
  "connections": {},
  "settings": {
    "executionOrder": "v1"
  }
}
```

---

## Section 5: Webhook Triggers

**Confidence: HIGH**

### Webhook URL Formats

| Environment | URL Pattern | Requires |
|-------------|-------------|----------|
| Production (active workflow) | `{N8N_URL}/webhook/{path}` | Workflow must be active |
| Test (inactive workflow) | `{N8N_URL}/webhook-test/{path}` | N8N editor open and listening |

The `{path}` value comes from the webhook node's `parameters.path` field. It can be:
- A UUID (auto-generated default)
- A human-readable slug like `process-images`
- A path with parameters: `process/:category`

**Important:** Paths are case-sensitive.

### Webhook Trigger Node Type

```
n8n-nodes-base.webhook
typeVersion: 2
```

### Passing Data to Webhook

```bash
# POST with JSON body
curl -X POST http://localhost:5678/webhook/my-path \
  -H "Content-Type: application/json" \
  -d '{"key": "value"}'

# GET with query params
curl "http://localhost:5678/webhook/my-path?param1=value1"
```

Data is available inside the workflow as:
- `$json.body` — parsed JSON body (POST)
- `$json.query` — query parameters
- `$json.headers` — request headers
- `$json.params` — URL path parameters

### Webhook Response Modes

| Mode | Behavior |
|------|---------|
| `onReceived` | Responds immediately with 200, workflow runs async |
| `lastNode` | Blocks until workflow completes, returns last node output |
| `responseNode` | A "Respond to Webhook" node controls the response |

**For `n8n_workflow trigger` use `lastNode`** — this makes execution synchronous and eliminates polling complexity. The HTTP response IS the workflow output.

**Payload size limit:** 16MB maximum.

---

## Section 6: Dangerous Node Types to Block

**Confidence: HIGH** — Confirmed from official docs and community reports.

### Dangerous Node Type Strings

| Risk Level | Node Type String | Description |
|-----------|-----------------|-------------|
| CRITICAL | `n8n-nodes-base.executeCommand` | Executes arbitrary shell commands on host |
| CRITICAL | `n8n-nodes-base.ssh` | SSH into remote systems and run commands |
| HIGH | `n8n-nodes-base.code` | Executes arbitrary JavaScript or Python code |
| HIGH | `n8n-nodes-base.git` | Git operations — CVE-2025-65964 (RCE via git hooks) |
| MEDIUM | `n8n-nodes-base.localFileTrigger` | Watches local filesystem paths |
| MEDIUM | `n8n-nodes-base.readBinaryFiles` | Reads arbitrary files from local filesystem |
| MEDIUM | `n8n-nodes-base.writeBinaryFile` | Writes arbitrary files to local filesystem |

### Default Blocked Nodes (N8N v2+)

As of N8N v2.0, the following are **blocked by default** via `NODES_EXCLUDE`:
```
n8n-nodes-base.executeCommand
n8n-nodes-base.localFileTrigger
```

`n8n-nodes-base.executeCommand` was effectively removed from the UI in v2.0 but the type string still exists in older workflows.

### Agent42 Blocklist for `n8n_create_workflow`

```python
DANGEROUS_NODE_TYPES = {
    "n8n-nodes-base.executeCommand",
    "n8n-nodes-base.ssh",
    "n8n-nodes-base.code",
    "n8n-nodes-base.git",
    "n8n-nodes-base.localFileTrigger",
    "n8n-nodes-base.readBinaryFiles",
    "n8n-nodes-base.writeBinaryFile",
}

def validate_workflow_nodes(nodes: list, allow_code: bool = False) -> list[str]:
    """Returns list of violations. Empty = safe."""
    violations = []
    blocked = DANGEROUS_NODE_TYPES
    if allow_code:
        blocked = blocked - {"n8n-nodes-base.code"}
    for node in nodes:
        if node.get("type") in blocked:
            violations.append(
                f"Node '{node['name']}' uses blocked type '{node['type']}'"
            )
    return violations
```

### N8N-Side NODES_EXCLUDE Configuration

To enforce blocking at the N8N Docker level (belt-and-suspenders):
```bash
NODES_EXCLUDE='["n8n-nodes-base.executeCommand","n8n-nodes-base.ssh","n8n-nodes-base.localFileTrigger"]'
```

Note: `NODES_EXCLUDE` takes a **JSON array as a string** in the env var.

---

## Section 7: Docker Setup

**Confidence: HIGH** — From official Docker README and docs.

### Image

```
docker.n8n.io/n8nio/n8n   # Official registry (preferred)
n8nio/n8n                  # Docker Hub mirror
```

### Local Dev (Single Container)

```bash
docker volume create n8n_data

docker run -d \
  --name n8n \
  --restart unless-stopped \
  -p 5678:5678 \
  -e N8N_ENCRYPTION_KEY=<generate-with-openssl-rand-hex-32> \
  -e GENERIC_TIMEZONE="America/New_York" \
  -e TZ="America/New_York" \
  -e N8N_RUNNERS_ENABLED=true \
  -v n8n_data:/home/node/.n8n \
  docker.n8n.io/n8nio/n8n
```

Access N8N at `http://localhost:5678`. Create API key at Settings → n8n API.

### Production Docker Compose (Contabo VPS)

```yaml
services:
  n8n:
    image: docker.n8n.io/n8nio/n8n
    restart: unless-stopped
    ports:
      - "5678:5678"
    environment:
      N8N_ENCRYPTION_KEY: ${N8N_ENCRYPTION_KEY}
      WEBHOOK_URL: http://163.245.217.2:5678/   # or https://your-domain.com/
      N8N_HOST: 163.245.217.2
      N8N_PORT: 5678
      N8N_PROTOCOL: http
      GENERIC_TIMEZONE: "UTC"
      TZ: "UTC"
      N8N_RUNNERS_ENABLED: "true"
      EXECUTIONS_DATA_PRUNE: "true"
      EXECUTIONS_DATA_MAX_AGE: 336     # 14 days in hours
      NODES_EXCLUDE: '["n8n-nodes-base.executeCommand","n8n-nodes-base.localFileTrigger"]'
    volumes:
      - n8n_data:/home/node/.n8n

volumes:
  n8n_data:
```

### Key Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `N8N_PORT` | 5678 | HTTP port |
| `N8N_HOST` | localhost | Hostname for URL construction |
| `N8N_PROTOCOL` | `http` | `http` or `https` |
| `WEBHOOK_URL` | auto-calculated | Override full webhook base URL (critical behind proxy) |
| `N8N_ENCRYPTION_KEY` | auto-generated | **Must be set** for credential security; if lost, credentials are unreadable |
| `GENERIC_TIMEZONE` | system | Timezone for Schedule nodes |
| `TZ` | system | System timezone |
| `N8N_RUNNERS_ENABLED` | `false` (v1) | Enable task runners for code execution isolation |
| `N8N_PUBLIC_API_DISABLED` | `false` | Disable the public REST API |
| `N8N_PUBLIC_API_SWAGGERUI_DISABLED` | `false` | Disable Swagger UI |
| `NODES_EXCLUDE` | `["n8n-nodes-base.executeCommand","n8n-nodes-base.localFileTrigger"]` | JSON array of blocked node types |
| `NODES_INCLUDE` | all | JSON array of exclusively allowed node types |
| `N8N_COMMUNITY_PACKAGES_ENABLED` | `true` | Allow installing community nodes |
| `EXECUTIONS_DATA_PRUNE` | `false` | Auto-delete old execution logs |
| `EXECUTIONS_DATA_MAX_AGE` | 336 | Hours to retain execution data |
| `DB_TYPE` | `sqlite` | Database: `sqlite` or `postgresdb` |

### Data Persistence

**Critical:** `/home/node/.n8n` contains:
- SQLite database (workflows, credentials, executions)
- `config` file with encryption key if not set via env var
- Execution logs

Always mount a named volume: `-v n8n_data:/home/node/.n8n`

---

## Section 8: Error Responses and Rate Limiting

**Confidence: MEDIUM** — Verified from OpenAPI spec; error body format verified by community reports.

### HTTP Status Codes

| Code | Meaning | When |
|------|---------|------|
| 200 | OK | Successful GET/DELETE |
| 201 | Created | Successful POST |
| 204 | No Content | Successful PUT/DELETE with no body |
| 400 | Bad Request | Invalid request body or parameters |
| 401 | Unauthorized | Missing or invalid `X-N8N-API-KEY` |
| 403 | Forbidden | Valid key but insufficient scope |
| 404 | Not Found | Resource ID doesn't exist |
| 409 | Conflict | Duplicate resource (e.g., duplicate tag name) |
| 422 | Unprocessable | Validation failed (e.g., missing required fields) |

### Error Response Body Format

```json
{
  "message": "Workflow not found"
}
```

Or for validation errors:
```json
{
  "message": "\"name\" is required"
}
```

### Rate Limiting

N8N has **no built-in API rate limiting** on the public API. Agent42 must enforce its own limit (D-22: 10 trigger calls/minute via `core/rate_limiter.py`).

Webhooks (large payloads) are limited to **16MB per request**.

### Common Error Patterns

1. **401 on every call:** API key not passed via `X-N8N-API-KEY` header (not Bearer, not query param)
2. **404 on execution poll:** N8N prunes old executions — `EXECUTIONS_DATA_MAX_AGE` may be too short
3. **Webhook 404:** Workflow is not active — use `/webhook-test/` for inactive workflows
4. **Webhook 404 on production URL:** `WEBHOOK_URL` env var not set correctly when behind a proxy
5. **Empty execution data:** `includeData=true` not passed to `GET /executions/{id}`

---

## Architecture Patterns

### Pattern 1: n8n_workflow Tool Action Routing

```python
class N8nWorkflowTool(Tool):
    async def execute(self, action: str, **kwargs) -> ToolResult:
        if not self._settings.n8n_url or not self._settings.n8n_api_key:
            return ToolResult(
                success=False,
                error="N8N not configured. Set N8N_URL and N8N_API_KEY."
            )
        match action:
            case "list":    return await self._list_workflows()
            case "trigger": return await self._trigger_workflow(**kwargs)
            case "status":  return await self._get_status(**kwargs)
            case "output":  return await self._get_output(**kwargs)
```

### Pattern 2: Webhook-Based Trigger (Synchronous)

```python
async def _trigger_workflow(self, workflow_id: str, input_data: dict = None) -> ToolResult:
    # 1. Get workflow to find webhook node and path
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{self._base_url}/workflows/{workflow_id}",
            headers=self._auth_headers
        )
    workflow = resp.json()

    # 2. Find webhook node
    webhook_node = next(
        (n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.webhook"),
        None
    )
    if not webhook_node:
        return ToolResult(success=False, error="Workflow has no webhook trigger node")

    # 3. Call webhook URL directly (no API key needed)
    webhook_path = webhook_node["parameters"]["path"]
    webhook_url = f"{self._n8n_url}/webhook/{webhook_path}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            webhook_url,
            json=input_data or {},
            headers={"Content-Type": "application/json"}
        )
    return ToolResult(output=resp.text, success=resp.is_success)
```

### Pattern 3: Config Addition Pattern (matching existing code)

```python
# In core/config.py Settings dataclass (add after existing tool config):
n8n_url: str = ""          # N8N instance URL, e.g. http://localhost:5678
n8n_api_key: str = ""      # N8N public API key (X-N8N-API-KEY header)
n8n_allow_code_nodes: bool = False  # Allow code/ssh/exec nodes in generated workflows

# In from_env():
n8n_url=os.getenv("N8N_URL", "").rstrip("/"),
n8n_api_key=os.getenv("N8N_API_KEY", ""),
n8n_allow_code_nodes=os.getenv("N8N_ALLOW_CODE_NODES", "false").lower() == "true",
```

### Pattern 4: Workflow Template Structure

Templates in `tools/n8n_templates/` should be minimal JSON skeletons that the `n8n_create_workflow` tool fills in. Suggested format:

```
tools/n8n_templates/
├── webhook_to_http.json       # Webhook → HTTP Request chain
├── webhook_to_transform.json  # Webhook → data transform → respond
├── scheduled_api_poll.json    # Schedule → HTTP Request → store
└── README.md                  # Template selection guide
```

Each template is a valid minimal workflow JSON with placeholder values like `{WEBHOOK_PATH}`, `{TARGET_URL}`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| N8N authentication | Custom auth middleware | `X-N8N-API-KEY` header on httpx client | Standard API key pattern |
| Workflow execution trigger | Direct `/execute` API endpoint | Webhook trigger pattern | No execute endpoint exists |
| Execution result retrieval | Custom polling loop | `GET /executions/{id}?includeData=true` | API provides this |
| Node blocking | Custom sandbox | Validate node types before POST + NODES_EXCLUDE env var | Belt-and-suspenders |
| Pagination | Manual page tracking | cursor-based pattern from N8N API | Built into the API |

---

## Common Pitfalls

### Pitfall 1: Assuming a Direct Execute Endpoint Exists
**What goes wrong:** Code calls `POST /api/v1/workflows/{id}/execute` and gets 404.
**Why it happens:** N8N's public API does not expose a workflow execution endpoint by ID. This is a deliberate design choice — workflows should have trigger nodes.
**How to avoid:** Design `trigger` action to call the workflow's webhook URL, not an API endpoint.
**Warning signs:** D-16 in CONTEXT.md references `/workflows/{id}/execute` — this endpoint does not exist and must be redesigned.

### Pitfall 2: Polling for Execution Results
**What goes wrong:** Tool triggers via webhook, then tries to poll `GET /executions?workflowId=X` but the execution ID isn't returned by the webhook call.
**Why it happens:** Webhook calls don't return an execution ID in the response — they're fire-and-forget by default.
**How to avoid:** Use `responseMode: "lastNode"` on the webhook node, making the HTTP call synchronous. The webhook response IS the workflow output.
**Warning signs:** Needing to correlate executions by timestamp is fragile in concurrent environments.

### Pitfall 3: Missing `includeData=true` on Execution GET
**What goes wrong:** `GET /executions/{id}` returns status and metadata but `data` field is empty/null.
**Why it happens:** N8N omits execution output data by default to save bandwidth.
**How to avoid:** Always append `?includeData=true` when fetching execution results.
**Warning signs:** `data` key is null or absent in execution response.

### Pitfall 4: N8N_ENCRYPTION_KEY Not Set
**What goes wrong:** Credentials become unreadable after container restart because the key regenerates.
**Why it happens:** If not set via env var, N8N generates a key and stores it in `/home/node/.n8n/config`. A new container generates a new key.
**How to avoid:** Always set `N8N_ENCRYPTION_KEY` explicitly in docker-compose. Generate with `openssl rand -hex 32`.
**Warning signs:** N8N UI shows "invalid credentials" after restart.

### Pitfall 5: Webhook URL Not Set Behind Proxy
**What goes wrong:** Webhooks don't work when N8N is behind nginx/Caddy — URLs are constructed with `localhost:5678` instead of the public URL.
**Why it happens:** N8N auto-calculates webhook URLs from `N8N_HOST`/`N8N_PORT`, not the proxy address.
**How to avoid:** Set `WEBHOOK_URL=https://your-domain.com/` explicitly in docker-compose when behind a reverse proxy.
**Warning signs:** Webhook URLs in N8N UI show `localhost:5678` when they should show the public domain.

### Pitfall 6: Workflow Not Active → Webhook 404
**What goes wrong:** Calling `/webhook/{path}` returns 404 on a newly created workflow.
**Why it happens:** Workflows start as `active: false`. The production webhook URL only works for active workflows.
**How to avoid:** After creating a workflow, call `POST /api/v1/workflows/{id}/activate` before attempting to trigger it.
**Warning signs:** Webhook call returns 404 immediately after successful workflow creation.

### Pitfall 7: Node Names in Connections (Not IDs)
**What goes wrong:** AI-generated workflow JSON uses node `id` values as connection keys and the workflow fails validation.
**Why it happens:** Connections are keyed by node `name` (display name), not by node `id`.
**How to avoid:** In `n8n_create_workflow`, ensure connection object keys match the node `name` field exactly.
**Warning signs:** Workflow saves but nodes appear disconnected in N8N editor.

---

## Code Examples

### Complete API Client Pattern

```python
# Source: N8N OpenAPI spec, Agent42 httpx patterns (tools/http_client.py, tools/web_search.py)

import httpx

class N8nApiClient:
    def __init__(self, base_url: str, api_key: str):
        self._base = base_url.rstrip("/") + "/api/v1"
        self._headers = {
            "X-N8N-API-KEY": api_key,
            "Content-Type": "application/json",
        }

    async def list_workflows(self, active: bool = None) -> list[dict]:
        params = {"limit": 250}
        if active is not None:
            params["active"] = str(active).lower()

        all_workflows = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            while True:
                resp = await client.get(
                    f"{self._base}/workflows",
                    headers=self._headers,
                    params=params
                )
                resp.raise_for_status()
                data = resp.json()
                all_workflows.extend(data["data"])
                cursor = data.get("nextCursor")
                if not cursor:
                    break
                params["cursor"] = cursor
        return all_workflows

    async def get_execution(self, exec_id: int, include_data: bool = True) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._base}/executions/{exec_id}",
                headers=self._headers,
                params={"includeData": "true" if include_data else "false"}
            )
            resp.raise_for_status()
            return resp.json()

    async def create_workflow(self, workflow: dict) -> dict:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base}/workflows",
                headers=self._headers,
                json=workflow
            )
            resp.raise_for_status()
            return resp.json()

    async def activate_workflow(self, workflow_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self._base}/workflows/{workflow_id}/activate",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()
```

### Extract Workflow Output from Execution Data

```python
def extract_last_node_output(execution: dict) -> list[dict]:
    """Extract the final node's output items from execution data."""
    run_data = execution.get("data", {}).get("resultData", {}).get("runData", {})
    if not run_data:
        return []
    # Last node = last key in runData (Python 3.7+ dicts preserve insertion order)
    last_node_name = list(run_data.keys())[-1]
    node_runs = run_data[last_node_name]
    if not node_runs:
        return []
    # Extract json items from main output
    main_output = node_runs[0].get("data", {}).get("main", [[]])
    if not main_output:
        return []
    return [item.get("json", {}) for item in main_output[0]]
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `n8n-nodes-base.executeCommand` enabled | Disabled by default in NODES_EXCLUDE | N8N v2.0 (2024) | RCE prevention |
| Basic Auth for dashboard | Email/password login flow | N8N v1.x | N8N_BASIC_AUTH_* still works but deprecated |
| Sequential execution order | `executionOrder: "v1"` required in settings | N8N v1.0 | Must specify in workflow settings or behavior is undefined |

**Deprecated/outdated:**
- `N8N_BASIC_AUTH_ACTIVE` + `N8N_BASIC_AUTH_USER` + `N8N_BASIC_AUTH_PASSWORD`: Still functional but legacy. Current auth is email/password.
- `n8n-nodes-base.executeCommand`: Removed from UI in v2.0. Older workflows using it will error with "Unrecognized node type" on v2+.

---

## Open Questions

1. **Webhook execution ID retrieval**
   - What we know: Webhook calls don't return execution ID in response by default
   - What's unclear: Does `responseMode: "lastNode"` prevent getting the execution ID for audit purposes?
   - Recommendation: Design `trigger` to use `lastNode` mode for synchronous results; if execution ID is needed for audit, implement a post-trigger lookup: `GET /executions?workflowId={id}&limit=1`

2. **N8N API key creation automation**
   - What we know: API keys are created via the N8N UI (Settings → n8n API)
   - What's unclear: Is there a CLI or bootstrap API to create the first API key programmatically for Docker setup?
   - Recommendation: [UNVERIFIED] N8N may support `N8N_API_KEY` as an env var to pre-seed the first key. Document manual steps in `.env.example` for now.

3. **D-16 correctness**
   - What we know: `/api/v1/workflows/{id}/execute` does NOT exist
   - What's unclear: Whether D-16 was written with incorrect assumptions or refers to webhooks
   - Recommendation: Planner must revise D-16. The trigger mechanism is webhook URL, not a REST execute endpoint. Update to: "Trigger via `{N8N_URL}/webhook/{path}`; poll via `GET /api/v1/executions?workflowId={id}`"

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker | N8N local dev | [UNVERIFIED - not checked on this machine] | — | Manual N8N install via npm |
| httpx | API calls | Already in project deps | — | — |
| Python 3.11+ | Tool runtime | Already in project | — | — |
| N8N instance | All tool actions | Graceful degradation if absent | — | Return "N8N not configured" |

**Missing dependencies with no fallback:**
- N8N instance itself: without a running N8N, tools return degraded responses (by design per D-14)

**Missing dependencies with fallback:**
- Docker: N8N can also be installed as `npm install -g n8n` if Docker unavailable

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing in project) |
| Config file | `pytest.ini` or `pyproject.toml` |
| Quick run command | `python -m pytest tests/test_n8n_tool.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req | Behavior | Test Type | Automated Command | File Exists? |
|-----|----------|-----------|-------------------|-------------|
| D-04 | `n8n_workflow list` returns structured data | unit (mock httpx) | `pytest tests/test_n8n_tool.py::test_list_workflows -x` | No — Wave 0 |
| D-05 | `n8n_workflow trigger` calls webhook URL | unit (mock httpx) | `pytest tests/test_n8n_tool.py::test_trigger_workflow -x` | No — Wave 0 |
| D-06 | `n8n_workflow status` polls execution | unit (mock httpx) | `pytest tests/test_n8n_tool.py::test_get_status -x` | No — Wave 0 |
| D-07 | `n8n_workflow output` extracts node data | unit | `pytest tests/test_n8n_tool.py::test_get_output -x` | No — Wave 0 |
| D-08 | `n8n_create_workflow` generates valid JSON | unit | `pytest tests/test_n8n_create_tool.py::test_workflow_generation -x` | No — Wave 0 |
| D-10 | Dangerous nodes rejected | unit | `pytest tests/test_n8n_create_tool.py::test_node_validation -x` | No — Wave 0 |
| D-14 | Graceful degradation when unconfigured | unit | `pytest tests/test_n8n_tool.py::test_unconfigured -x` | No — Wave 0 |
| D-22 | Rate limiting enforced | unit | `pytest tests/test_n8n_tool.py::test_rate_limiting -x` | No — Wave 0 |

### Wave 0 Gaps

- [ ] `tests/test_n8n_tool.py` — covers D-04 through D-07, D-14, D-22
- [ ] `tests/test_n8n_create_tool.py` — covers D-08, D-10, node validation
- [ ] Mock fixtures for N8N API responses (workflow list, execution status)

---

## Project Constraints (from CLAUDE.md)

| Directive | Constraint |
|-----------|-----------|
| All I/O is async | Use `httpx.AsyncClient`, `asyncio`. Never `requests`, never blocking I/O |
| Frozen config | Add fields to `Settings` dataclass + `from_env()` + `.env.example` |
| Graceful degradation | Missing N8N URL/key never crashes; returns descriptive error |
| Sandbox always on | N8N URL must pass through `sandbox.resolve_path()` or `UrlPolicy` check |
| Never log API keys | Do NOT log `N8N_API_KEY` values even at DEBUG level |
| Validate paths | N8N URL validated through `UrlPolicy` SSRF checks (D-21) |
| New tools → test file | `tests/test_n8n_tool.py` required |

---

## Sources

### Primary (HIGH confidence)
- `github.com/n8n-io/n8n-docs` — Official OpenAPI spec (`docs/api/v1/openapi.yml`) — all endpoints, schemas, status enums, auth scheme
- `github.com/n8n-io/n8n` — Docker README (`docker/images/n8n/README.md`) — docker run commands, env vars, volume paths
- `github.com/n8n-io/n8n-docs` — nodes.md (`docs/hosting/configuration/environment-variables/nodes.md`) — NODES_EXCLUDE format, defaults

### Secondary (MEDIUM confidence)
- [N8N Authentication Docs](https://docs.n8n.io/api/authentication/) — API key header name, scopes
- [N8N Webhook Node Docs](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/) — URL format, response modes
- [N8N Execute Command Docs](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.executecommand/) — node type string confirmed
- [N8N SSH Docs](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.ssh/) — node type string confirmed
- Community report (github.com/n8n-io/n8n/issues/212895) — confirmed no direct execute endpoint

### Tertiary (LOW confidence)
- [latenode.com Docker guide](https://latenode.com/blog/...) — production docker-compose example (not official, but consistent with official docs)
- Community posts about `executeCommand` removal in v2.0 — confirmed by multiple community sources

---

## Metadata

**Confidence breakdown:**
- Authentication: HIGH — verified from OpenAPI spec and official docs
- Workflow CRUD endpoints: HIGH — directly from OpenAPI spec
- Execute/trigger mechanism: HIGH (finding) + MEDIUM (implementation details) — confirmed no execute endpoint exists, webhook approach well-documented
- Workflow JSON schema: HIGH — from OpenAPI spec
- Dangerous node type strings: HIGH — confirmed by official docs URLs and community issues
- Docker setup: HIGH — from official Docker README
- Error codes: MEDIUM — from OpenAPI spec (error bodies from community reports)

**Research date:** 2026-04-05
**Valid until:** 2026-07-05 (stable API, 90 days reasonable)
