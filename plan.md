# Implementation Plan: Modularity + Dynamic Model Routing

## Overview

Two features to make Agent42 truly extensible and self-improving:

1. **Tool Plugin System** — Drop-in custom tools without modifying core code
2. **Dynamic Model Routing** — Auto-discover, evaluate, and rank free LLMs for each task type

---

## Part 1: Tool Plugin Auto-Discovery

### Goal
Users drop a `.py` file into a configurable directory and Agent42 auto-discovers, validates, and registers it — no core modifications needed.

### New Files

#### `tools/context.py` — Dependency injection container
```python
@dataclass
class ToolContext:
    """Injectable context for custom tools."""
    sandbox: WorkspaceSandbox
    command_filter: CommandFilter
    task_queue: TaskQueue
    workspace: str
    tool_registry: ToolRegistry  # For tools that spawn other tools
```

#### `tools/plugin_loader.py` — Auto-discovery engine
- Scans configured directory for `.py` files
- Imports each module, finds `Tool` subclasses
- Reads `requires: ClassVar[list[str]]` from each tool class to know what dependencies to inject
- Instantiates and registers via `ToolContext`
- Logs warnings for invalid tools (missing ABC methods, import errors)
- Security: validates tool names (alphanumeric + underscores only), prevents collision with built-in tools

### Modified Files

| File | Change |
|------|--------|
| `core/config.py` | Add `custom_tools_dir: str` field + `CUSTOM_TOOLS_DIR` env var |
| `agent42.py` | After `_register_tools()`, call `PluginLoader.load_all()` |
| `.env.example` | Document `CUSTOM_TOOLS_DIR` |

### How It Works

```python
# Example custom tool: custom_tools/my_tool.py
from tools.base import Tool, ToolResult

class MyTool(Tool):
    requires = ["sandbox"]  # Declares needed dependencies

    def __init__(self, sandbox=None, **kwargs):
        self._sandbox = sandbox

    @property
    def name(self) -> str: return "my_custom_tool"
    # ... rest of Tool ABC
```

### Dependency Injection Flow
1. `PluginLoader` builds a `ToolContext` from Agent42's initialized components
2. For each discovered Tool subclass, reads its `requires` class variable
3. Passes only the requested dependencies as kwargs to `__init__`
4. Falls back gracefully — if a tool requires something unavailable, log warning and skip

---

## Part 2: Dynamic Model Routing

### Goal
Agent42 automatically keeps its model routing up-to-date by:
1. **Catalog sync** — Periodically fetching new free models from OpenRouter
2. **Outcome tracking** — Recording which models succeed/fail per task type
3. **Web research** — Checking authoritative benchmark sources for model rankings
4. **Trial system** — Testing new/unproven models on a small % of tasks before promoting

### Resolution Priority (unchanged for admin, new dynamic layer)
```
1. Admin env var override  (AGENT42_CODING_MODEL=...)  — always wins
2. Dynamic routing         (from outcome data + research)  — NEW
3. Hardcoded FREE_ROUTING  (current defaults)              — fallback
```

### New Files

#### `agents/model_catalog.py` — OpenRouter catalog sync
- Fetches `https://openrouter.ai/api/v1/models` periodically (configurable, default every 24h)
- Filters for free models (pricing.prompt == "0")
- Extracts: model ID, context window, architecture, modality, throughput
- Stores discovered models in `data/model_catalog.json`
- Auto-registers new free models in `ProviderRegistry` as `or-free-{slug}` keys
- Graceful degradation: if API unreachable, uses cached catalog

#### `agents/model_evaluator.py` — Outcome tracking + ranking
- Records per-model, per-task-type metrics after each task:
  - Success rate (task completed vs failed)
  - Iteration efficiency (fewer iterations = better)
  - Critic scores (from the iteration engine's critic)
  - Token efficiency (output quality per token)
- Stores data in `data/model_performance.json`
- Computes composite score: `0.4*success + 0.3*efficiency + 0.2*critic_score + 0.1*token_efficiency`
- Periodic re-ranking (every N tasks or every M hours, configurable)
- **Trial system**: New/unproven models get assigned to `MODEL_TRIAL_PERCENTAGE` (default 10%) of tasks. After `MIN_TRIALS` (default 5) completions, they get a ranking and may be promoted.

#### `agents/model_researcher.py` — Benchmark research
- Async task that runs periodically (configurable, default weekly)
- Fetches authoritative benchmark sources via web search:
  - LMSys Chatbot Arena leaderboard
  - OpenRouter model stats/rankings
  - HuggingFace Open LLM Leaderboard
  - Artificial Analysis quality/speed benchmarks
- Uses an LLM call to extract structured rankings from fetched content
- Produces `data/model_research.json` with model-to-score mappings by capability (coding, reasoning, writing, etc.)
- Research scores factor into the composite ranking as a "prior" for models with insufficient outcome data

### Modified Files

| File | Change |
|------|--------|
| `agents/model_router.py` | Add `_check_dynamic_routing()` between admin override and hardcoded defaults; add `record_outcome()` method; add trial selection logic |
| `agents/learner.py` | After reflection, call `model_router.record_outcome()` with task results |
| `agents/iteration_engine.py` | Pass critic scores to model evaluator |
| `providers/registry.py` | Add `register_models_from_catalog()` for bulk registration of discovered models |
| `core/config.py` | Add settings: `MODEL_ROUTING_FILE`, `MODEL_CATALOG_REFRESH_HOURS`, `MODEL_TRIAL_PERCENTAGE`, `MODEL_MIN_TRIALS`, `MODEL_RESEARCH_ENABLED`, `MODEL_RESEARCH_INTERVAL_HOURS` |
| `agent42.py` | Initialize `ModelCatalog` + `ModelEvaluator`; schedule periodic refresh tasks |
| `.env.example` | Document all new settings |

### Data Flow

```
Task Completed
     │
     ├─→ learner.py: reflect on task
     │       │
     │       └─→ model_evaluator.record_outcome(model, task_type, metrics)
     │                │
     │                └─→ Updates data/model_performance.json
     │
     ├─→ Periodic: model_catalog.refresh()
     │       │
     │       └─→ Fetches OpenRouter /models → data/model_catalog.json
     │           Auto-registers new free models
     │
     ├─→ Periodic: model_researcher.research()
     │       │
     │       └─→ Web search benchmarks → data/model_research.json
     │
     └─→ Periodic: model_evaluator.rerank()
             │
             └─→ Combines: outcomes + research + catalog metadata
                 Writes: data/dynamic_routing.json
                 ModelRouter picks up on next task
```

### Dynamic Routing File Format
```json
{
  "last_updated": "2026-02-22T12:00:00Z",
  "routing": {
    "coding": {
      "primary": "or-free-qwen-coder",
      "critic": "or-free-deepseek-r1",
      "confidence": 0.87,
      "sample_size": 42,
      "max_iterations": 8
    }
  },
  "trials": {
    "or-free-new-model-xyz": {
      "task_types_trialed": ["coding", "debugging"],
      "completions": 3,
      "min_required": 5
    }
  }
}
```

---

## Part 3: Testing

### New Test Files
| File | Tests |
|------|-------|
| `tests/test_plugin_loader.py` | Tool discovery, dependency injection, collision prevention, invalid tool handling |
| `tests/test_model_catalog.py` | OpenRouter API mocking, catalog parsing, auto-registration, cache fallback |
| `tests/test_model_evaluator.py` | Outcome recording, ranking calculation, trial system, reranking |
| `tests/test_model_researcher.py` | Web research mocking, score extraction, graceful degradation |
| `tests/test_dynamic_routing.py` | End-to-end: resolution priority, dynamic override of defaults, trial assignment |

---

## Implementation Order

| Step | Task | Dependencies |
|------|------|-------------|
| 1 | `tools/context.py` + `tools/plugin_loader.py` | None |
| 2 | Config additions (`core/config.py`, `.env.example`) | None |
| 3 | Integrate plugin loader in `agent42.py` | Steps 1-2 |
| 4 | Tests for plugin system | Steps 1-3 |
| 5 | `agents/model_catalog.py` (OpenRouter sync) | None |
| 6 | `agents/model_evaluator.py` (outcome tracking + ranking) | None |
| 7 | `agents/model_researcher.py` (web benchmark research) | None |
| 8 | Integrate into `model_router.py` (dynamic routing layer) | Steps 5-7 |
| 9 | Wire learner.py + iteration_engine.py for outcome recording | Step 8 |
| 10 | Integrate in `agent42.py` (startup, periodic tasks) | Steps 8-9 |
| 11 | Tests for model routing | Steps 5-10 |
| 12 | Config + docs updates | All |

Steps 1-4 (plugin system) and steps 5-7 (model components) can be done in parallel.
