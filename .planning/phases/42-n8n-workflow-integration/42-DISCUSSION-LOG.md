# Phase 42: N8N Workflow Integration - Discussion Log (Assumptions Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-04-05
**Phase:** 42-n8n-workflow-integration
**Mode:** assumptions
**Areas analyzed:** Tool Design, N8N API Integration, Configuration, Deployment, Security, Workflow Creation

## Assumptions Presented

### Tool Architecture
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Two tools inheriting Tool ABC, registered in _build_registry() | Confident | tools/base.py:31-66, mcp_server.py |
| httpx.AsyncClient for N8N API calls | Confident | tools/web_search.py:69-78, tools/http_client.py |
| ToolResult return type with output/error/success | Confident | tools/base.py:18-28 |

### Configuration
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| n8n_url and n8n_api_key in Settings dataclass | Confident | core/config.py frozen dataclass + from_env() pattern |
| Graceful degradation when N8N not configured | Confident | All optional services follow this pattern |
| N8N_ALLOW_CODE_NODES security flag | Likely | Follows existing security-gate patterns |

### N8N API
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| REST API v1 with X-N8N-API-KEY header auth | Likely | Standard N8N documentation |
| Endpoints: workflows, execute, executions | Likely | Standard N8N REST API |
| 30s trigger timeout, 10s list/status timeout | Likely | Matches existing httpx timeout patterns |

### Deployment
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Docker n8nio/n8n on port 5678 | Likely | Standard N8N deployment |
| SQLite default (no extra DB needed) | Likely | Matches Agent42's minimal dependency approach |
| Added to existing docker-compose for production | Likely | docker-compose.paperclip.yml pattern from Phase 31 |

### Workflow Creation
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| LLM generates N8N workflow JSON from natural language | Likely | Similar to template_tool.py pattern |
| Templates in tools/n8n_templates/ reduce hallucination | Likely | Pattern from template_tool.py |
| Dangerous node restriction by default | Confident | Follows security-gate patterns |

### Security
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| UrlPolicy SSRF protection on N8N URL | Confident | tools/http_client.py:140-143 |
| Rate limiting via rate_limiter.py | Confident | core/rate_limiter.py pattern |
| API key in key_store.py | Confident | core/key_store.py pattern |

## Corrections Made

No corrections — all assumptions auto-confirmed (--auto mode).

## Auto-Resolved

- N8N API endpoint paths: auto-selected standard v1 REST API (Likely → proceeding with documented defaults)
- Workflow creation strategy: auto-selected template-assisted LLM generation (Likely → safest approach)
