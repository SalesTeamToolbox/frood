---
name: browser-load-test
description: Run Playwright-based load test against the Agent42 dashboard to find concurrent agent limits.
always: false
task_types: [debugging]
---

# Browser Load Test

You are running a Playwright-based load test against the Agent42 dashboard. This skill stress-tests the system to find the real concurrent agent limit by submitting tasks through the browser UI and API, monitoring status, and capturing screenshots.

## Prerequisites

Ensure dependencies are installed:
```
pip install playwright httpx
playwright install chromium
```

## Running the Load Test

### Quick Start (defaults)

```bash
# Terminal 1 — Log monitor (optional but recommended)
python load_test_monitor.py

# Terminal 2 — Load test
python load_test.py
```

### With Options

```bash
# Show browser window (useful for debugging)
python load_test.py --no-headless

# Custom URL / credentials
python load_test.py --url http://myserver:8000 --password "mypass"

# Monitor a remote log file
python load_test_monitor.py --log-file /path/to/agent42.log --all
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT42_URL` | `http://localhost:8000` | Dashboard URL |
| `AGENT42_USER` | `admin` | Login username |
| `AGENT42_PASS` | (configured) | Login password |

## Test Phases

| Phase | Tasks | Delay | Purpose |
|-------|-------|-------|---------|
| **Warmup** | 4 simple content/research | 2s | Baseline — confirm dispatch works |
| **Teams** | 8 complex marketing/coding/strategy | 3s | Trigger team formation, multiply agents |
| **Stress** | 20 rapid-fire content tasks | 0.5s | Fill queue until saturation |
| **Cooldown** | None (monitor) | 3s polls | Wait for queue to drain |

## What to Look For

### Saturation Detection
The test automatically detects saturation: 3 consecutive polls where pending tasks > 2 but active agents aren't increasing. This means the system has hit its real concurrency ceiling.

### Key Metrics
- **Peak active agents** vs **effective_max** — how close did we get to the reported limit?
- **Team runs** — did complex tasks trigger team formation?
- **Saturation point** — at what agent count did the system stop scaling?
- **Rate limit errors** — check the log monitor for 429s from Gemini/OpenRouter

### Screenshots
Screenshots are saved to `.agent42/screenshots/load_test/` at key moments:
- After login
- After each phase completes
- At peak stress
- Final state after cooldown

### Metrics JSON
A `metrics_*.json` file is saved alongside screenshots with full time-series data (snapshots array) for post-analysis.

## Interpreting Results

| Scenario | Meaning |
|----------|---------|
| Peak agents = effective_max | System scales fully — memory estimate is accurate |
| Peak agents << effective_max | API rate limits are the real bottleneck, not memory |
| Saturation detected early | Reduce `AGENT_DISPATCH_DELAY` or increase API quotas |
| Many 429s in logs | Gemini/OR rate limits hit — consider staggering or adding providers |
| Teams formed | Complex tasks correctly triggered multi-agent coordination |
| Tasks stuck pending | Dispatch loop may be blocked — check for deadlocks in logs |

## Log Monitor Categories

The companion `load_test_monitor.py` filters logs by color:

| Color | Category | Example Patterns |
|-------|----------|-----------------|
| Red | Errors | `ERROR`, `Exception`, `Traceback`, `crash` |
| Yellow | Rate limits | `429`, `timeout`, `retry`, `quota` |
| Cyan | Capacity | `effective_max`, `dispatch`, `memory available` |
| Green | Lifecycle | `team formed`, `agent started`, `task DONE` |

## Customization

To modify task definitions, edit the `WARMUP_TASKS`, `TEAM_TASKS`, and `STRESS_TASKS` lists in `load_test.py`. Each task needs:
- `title` — short descriptive title
- `description` — full task instructions
- `task_type` — valid TaskType value (`content`, `research`, `coding`, `marketing`, etc.)
- `priority` — optional, 0=normal, 1=high (use for team-triggering tasks)
