---
name: prod-check
description: Run all production health checks via SSH in one pass
disable-model-invocation: true
---

# /prod-check

Run all six production health checks against the Agent42 server via SSH and produce a summary report.

## Prerequisites

The SSH config alias `agent42-prod` must be configured. This connects to:
- **Server:** Contabo VPS at 163.245.217.2:2222
- **User:** `deploy`
- **Service:** `agent42.service` (systemd)

**Before running any checks**, verify SSH connectivity:

```bash
ssh agent42-prod "echo OK"
```

If this command fails or times out, STOP and tell the developer:

> SSH connection to `agent42-prod` failed. Ensure your `~/.ssh/config` has an entry for `agent42-prod` pointing to 163.245.217.2 on port 2222 with user `deploy` and a valid key.

Do NOT proceed with health checks if the SSH verification fails.

## Health Checks

Run each check as a separate Bash tool call so you can analyze results step-by-step. Do NOT batch them into a single command.

### Check 1: Systemd Service Status

```bash
ssh agent42-prod "sudo systemctl status agent42 --no-pager -l"
```

**Report:** Whether the service is `active (running)` or inactive/failed, uptime duration, any recent restarts visible in the output, and memory usage if shown.

### Check 2: Recent Logs (last 50 lines)

```bash
ssh agent42-prod "tail -50 ~/agent42/agent42.log"
```

**Report:** Count of lines containing `ERROR` or `WARNING`, whether any stack traces are present, and the timestamp of the last log entry.

### Check 3: Qdrant Health

```bash
ssh agent42-prod "curl -s http://localhost:6333/healthz"
```

**Report:** Whether the response indicates healthy status. If the response is empty or contains an error, report unhealthy with the response content.

### Check 4: Redis Ping

```bash
ssh agent42-prod "redis-cli ping"
```

**Report:** `PONG` = healthy. Anything else (including no response, connection refused, or error messages) = problem.

### Check 5: Dashboard HTTP Check

```bash
ssh agent42-prod "curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/health"
```

**Report:** Status code `200` = healthy. Any other status code = problem. Include the actual status code in the report.

### Check 6: Disk Usage

```bash
ssh agent42-prod "df -h / /var/lib/qdrant"
```

**Report:** Usage percentage for each mount point. Warn if any mount exceeds 80% usage.

## Output Format

After running all six checks, summarize results in this table:

| Check | Status | Details |
|-------|--------|---------|
| Agent42 Service | OK/WARN/FAIL | [active/inactive, uptime, restarts] |
| Logs | OK/WARN/FAIL | [error count, warning count, last activity] |
| Qdrant | OK/WARN/FAIL | [health response] |
| Redis | OK/WARN/FAIL | [ping response] |
| Dashboard | OK/WARN/FAIL | [HTTP status code] |
| Disk | OK/WARN/FAIL | [usage percentages per mount] |

### Status Criteria

- **OK** -- Check passed with no issues
- **WARN** -- Check passed but with concerns (e.g., disk > 80%, warnings in logs, high restart count)
- **FAIL** -- Check failed (service down, connection refused, unhealthy response)

## Overall Assessment

After the summary table, provide an overall verdict:

- **ALL HEALTHY** -- All checks returned OK
- **DEGRADED** -- One or more checks returned WARN, but no FAIL
- **CRITICAL** -- One or more checks returned FAIL

If DEGRADED or CRITICAL, list specific recommended actions (e.g., "Restart agent42 service", "Investigate Qdrant connection", "Clear disk space on /var/lib/qdrant").

## What NOT to Do

- Do NOT batch all SSH commands into a single call -- run each check separately
- Do NOT use `!` backtick syntax to auto-run commands at skill load time
- Do NOT create any Python scripts -- this is a pure instruction skill
- Do NOT attempt to fix issues automatically -- only report and recommend
