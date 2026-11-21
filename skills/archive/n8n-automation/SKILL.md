---
name: n8n-automation
description: Offload repetitive, deterministic tasks to N8N workflows instead of spending tokens on LLM reasoning. Agents should proactively identify automation opportunities.
always: true
task_types: [coding, devops, data-analysis, research, monitoring, deployment]
---

# N8N Workflow Automation

You have access to N8N — a workflow automation engine with 400+ integrations. Use it to **replace token-expensive repetitive work with deterministic workflows that run for free**.

## Decision Rule: Code vs Workflow

Before writing code or repeating a multi-step process, ask:

| Question | If Yes → |
|----------|----------|
| Does this task repeat across runs? | **Create a workflow** |
| Does it chain API calls without needing LLM reasoning? | **Create a workflow** |
| Is it bulk data processing, transformation, or forwarding? | **Create a workflow** |
| Does it need LLM judgment, creativity, or context? | Write code / do it directly |

**Rule of thumb:** If a task is deterministic (same input → same output), it belongs in N8N, not in an LLM.

## When to Use N8N

- **Bulk API calls** — polling endpoints, aggregating responses, webhook forwarding
- **Data transforms** — reshaping JSON, filtering, merging datasets
- **Image/file processing** — resize, convert, upload via third-party APIs
- **Notifications** — Slack, email, Discord alerts triggered by events
- **Scheduled checks** — health monitoring, status page updates
- **Integration glue** — connecting services that don't natively talk to each other

## How to Use

### Check for existing workflows first
```
n8n_workflow(action="list")
```

### Trigger an existing workflow
```
n8n_workflow(action="trigger", workflow_id="<id>", input_data={"key": "value"})
```

### Create a new workflow when none exists
```
n8n_create_workflow(
  description="Fetch weather data from OpenWeather API and post summary to Slack",
  template="webhook_to_http",
  target_url="https://api.openweathermap.org/data/2.5/weather"
)
```

### Monitor execution
```
n8n_workflow(action="status", execution_id="<id>")
n8n_workflow(action="output", execution_id="<id>")
```

## Available Templates

| Template | Pattern | Use when |
|----------|---------|----------|
| `webhook_to_http` | Webhook → HTTP Request | Proxying API calls, fetching external data |
| `webhook_to_transform` | Webhook → Set/Transform | Reshaping data, field mapping |
| `webhook_to_multi_step` | Webhook → HTTP → Transform | Fetch + transform pipeline |

## Cost Comparison

| Approach | Token Cost | Runs |
|----------|-----------|------|
| Agent does it each time | 1,000-5,000 tokens per run | Every time |
| Agent writes Python code | 2,000-5,000 tokens once | Needs agent to invoke |
| Agent creates N8N workflow | 500-800 tokens once | Runs forever, zero tokens |

**Always prefer the workflow approach for deterministic, repeatable tasks.**
