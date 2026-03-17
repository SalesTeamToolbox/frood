# Pitfalls Research

**Domain:** Task-level memory scoping, effectiveness tracking, and recommendation engines added to an existing AI agent memory platform
**Researched:** 2026-03-17
**Confidence:** HIGH (grounded in existing codebase, verified with Qdrant docs and current research)

---

## Critical Pitfalls

### Pitfall 1: Qdrant Payload Schema Divergence Between Embedded and Server Mode

**What goes wrong:**
New `task_id` and `task_type` fields are added to Qdrant payloads for new entries, but the 10,000+ existing points in `agent42_memory` and `agent42_history` collections have no such fields. Queries that filter on `task_id` or `task_type` silently return empty results for all pre-existing entries — not an error, just missing data. Developers see "no historical learnings" even though memory is full.

The problem is worse in embedded mode (`.agent42/qdrant/`) because the client holds a file lock for the entire process lifetime. A background task trying to batch-upsert metadata updates on old points will contend with foreground search queries, causing `QDRANT_LOCKED` or `RocksDB lock` errors that are swallowed in the current `except Exception: pass` blocks.

**Why it happens:**
Qdrant uses a schemaless payload model — adding new fields to new points does not backfill old ones. The current `upsert_vectors()` in `qdrant_store.py` merges fields from the `payload` argument, so old points created without `task_id` simply have no such key. When `search_with_lifecycle()` adds a `task_type` filter condition, it correctly excludes all legacy points.

**How to avoid:**
1. Design all new `task_type` and `task_id` filters to be **opt-in additive**, not required. The `search_with_lifecycle()` method already takes optional `project_filter` — follow the same pattern: pass `task_type_filter` only when explicitly scoping.
2. For legacy point migration: do NOT batch-upsert all existing points. Instead, add a lightweight `set_payload` sweep during the Phase 1 initializer that marks existing points with `task_type: "legacy"` and `task_id: ""`. Use Qdrant's `scroll()` API with batches of 100, with `await asyncio.sleep(0.01)` between batches to avoid lock contention.
3. In embedded mode, never run migration during app startup. Schedule it as a one-time background task triggered after the first query completes.
4. Add a payload index for `task_type` only after migration sweep completes (`client.create_payload_index()`), because indexing a field that doesn't exist on 80% of points wastes memory and skews HNSW scoring.

**Warning signs:**
- `search_with_lifecycle()` returns 0 results for `task_type` queries even though memory collection has 5,000+ points.
- Embedded Qdrant logs show `RocksDB: Resource temporarily unavailable` errors.
- `collection_count()` returns non-zero but `task_type`-filtered queries return empty.

**Phase to address:** Phase 1 (task metadata schema) — must define the nullable/optional payload contract before any task metadata is written.

---

### Pitfall 2: Learning Extraction Generates Noise That Poisons Future Recommendations

**What goes wrong:**
The automated post-task learning extractor calls an LLM with the agent's tool call log, task outcome, and duration. When tasks fail or partially succeed, the LLM extracts "learnings" that are actually confabulations: "Always use flask because it works well" from a single successful Flask task, or "shell tool is unreliable" from one timeout. These get stored in the `agent42_knowledge` Qdrant collection with `confidence: 0.5`. The lifecycle scoring system then gradually boosts confidence every time the learning is recalled. Within 20 task cycles, a spurious learning has `confidence: 0.9` and is surfacing in every recommendation.

Research confirms this: directly applying a vanilla LLM as a trajectory evaluator leads to more severe negative impacts than a small but high-quality manually-curated dataset (arXiv 2505.16067).

**Why it happens:**
The extraction prompt is run without a minimum-evidence threshold. The LLM optimizes for producing plausible-sounding learnings, not accurate generalizations. Single-task evidence is insufficient for any statistical claim about tool effectiveness.

**How to avoid:**
1. **Minimum evidence threshold:** Never promote a learning to `confidence > 0.6` until it has been observed in at least 3 independent tasks of the same type. Store `evidence_count` in the Qdrant payload and cap confidence progression: `new_confidence = min(0.5 + 0.1 * evidence_count, 0.85)`.
2. **Contradiction detection:** Before storing a new learning, semantic search the `knowledge` collection for similar claims. If a new learning contradicts an existing one (cosine similarity > 0.85, but content is semantically opposite), flag both for human review rather than blindly upsering.
3. **Extraction scope limit:** The LLM extractor should only output learnings that reference observable events (specific tool names, durations, error codes), not generalizations. Use a structured output schema with `tool_name`, `task_type`, `observed_behavior`, and `confidence_justification` fields — reject free-text assertions.
4. **Quarantine period:** New learnings go into a `status: "pending"` state for 48 hours. They are excluded from recommendations until confirmed by a second matching observation or manual review.

**Warning signs:**
- The `knowledge` collection grows faster than 10 entries per day without user intervention.
- Recommendations reference a tool/skill for a task type it was only used once on.
- Confidence values on `knowledge` entries increase every week even for tasks that are failing.

**Phase to address:** Phase 2 (learning extraction) — the quarantine and evidence threshold logic must be in the first implementation, not added later when noise is already accumulated.

---

### Pitfall 3: Context Injection Causes "Context Rot" — More Memory Hurts More Than Helps

**What goes wrong:**
The proactive context injection system retrieves the top-5 task learnings and injects them into agent prompts. For long-running tasks (10+ iteration loops), the agent's context grows with each recommendation call. Chroma Research (2025) documented "context rot": every frontier model tested exhibited measurable performance degradation as context length increases — not from token limits, but from distractor interference. Topically-related-but-factually-irrelevant retrieved content appeared most frequently in hallucinated responses (HaluMem paper, arXiv 2511.03506).

In Agent42's case: a coding task injected with "past Flask learnings" while building a Django app creates exactly this distractor pattern. The agent starts referencing Flask patterns in Django code.

**Why it happens:**
Semantic similarity (cosine distance on MiniLM-L6-v2 embeddings) retrieves content that is topic-adjacent, not task-specific. "Flask app" and "Django app" share high embedding similarity. The `build_context_semantic()` method in `store.py` does not distinguish between "relevant to this task type" and "relevant to this specific task goal".

**How to avoid:**
1. **Gate injection on score threshold:** Only inject learnings with `adjusted_score > 0.80` (not the current 0.60 display default). A learning with 0.65 similarity is probably a distractor.
2. **Cap injected learning tokens:** Hard limit of 500 tokens for proactive learning injection regardless of `top_k`. Truncate rather than exclude — a summary is better than omitting all context.
3. **Task-type exact match first:** When `task_type` is known (e.g., `coding/flask`), retrieval must filter to `task_type == current_task_type` before falling back to semantic similarity. This eliminates cross-domain distractors.
4. **Inject at task start only:** Inject learnings once at the beginning of a task, not on every agent iteration. The current `build_context_semantic()` is called inside the agent loop and accumulates on each call.
5. **A/B test injection quality:** Before enabling proactive injection by default, measure task success rate with and without it on the same task types. Roll out per task type, not globally.

**Warning signs:**
- Agent iteration count increases after enabling learning injection (more loops = more confusion).
- Task failure rate increases for task types that have few historical learnings (noise dominates signal).
- Agent outputs reference tools or frameworks not relevant to the current task.

**Phase to address:** Phase 3 (proactive context injection) — score threshold and task-type exact match must be implemented before injection is enabled, not as a post-launch tuning exercise.

---

### Pitfall 4: Tool Effectiveness Tracking Adds Synchronous Latency to Every Tool Call

**What goes wrong:**
The naive approach wraps every `ToolRegistry.execute()` call with timing and outcome capture, then writes to Qdrant on each call. With 36+ tools and agents running 50–100 tool calls per task, this adds a Qdrant write (`set_payload` or `upsert_single`) on every tool invocation. In embedded mode, Qdrant writes are synchronous and file-locked — 3–15ms each. A 100-call task now adds 300–1500ms of overhead. In the MCP server context (stdio transport), this latency is visible to the user as perceptible lag between Claude Code tool calls.

Benchmarks from agent observability tools (LangSmith, Langfuse) show that instrumentation tools with synchronous execution-path involvement add 12–15% latency overhead. For Agent42's MCP server, which must respond within Claude Code's tool call timeout, any synchronous write in the hot path is unacceptable.

**Why it happens:**
Developers instrument first, optimize later. The `ToolRegistry.execute()` method is the obvious injection point, but it's also on the critical path. Post-call writes feel like they should be fast ("it's just metadata"), but Qdrant embedded writes involve WAL flushes.

**How to avoid:**
1. **Decouple tracking from execution:** Use an in-memory `collections.deque(maxlen=1000)` buffer per tool. Append tracking records (`tool_name`, `task_id`, `duration_ms`, `success`, `task_type`) to the buffer during execution. A background `asyncio.Task` (created once at startup, not per-call) drains the buffer every 5 seconds and batch-writes to Qdrant.
2. **Never write to Qdrant in `execute()` hot path.** The only acceptable side effect during execution is an O(1) in-memory append.
3. **Use a separate `effectiveness` collection** (not `history` or `memory`) so tracking writes don't compete with search operations on the primary collections.
4. **Graceful degradation:** If the background drain task fails (Qdrant unavailable), the buffer fills up and old entries are evicted. Tracking data is lost but execution is unaffected. Log at WARNING level when buffer utilization exceeds 80%.
5. **Sample, don't capture all:** For tools called > 100 times per day (e.g., `shell`, `memory`, `filesystem`), sample at 20% rather than 100%. The statistics are valid at that volume.

**Warning signs:**
- MCP tool call response time increases after enabling tracking.
- `tools.registry` logs show timing for `execute()` growing over time.
- Agent42's asyncio event loop lag metric (if measured) increases during heavy task execution.

**Phase to address:** Phase 2 (effectiveness tracking) — buffered async drain must be the implementation from day one. A synchronous prototype is acceptable only in tests against a mock Qdrant.

---

### Pitfall 5: Memory Bloat From Storing Every Task Outcome

**What goes wrong:**
The learning extractor runs after every task and stores: (a) a learning in `knowledge`, (b) a task outcome summary in `history`, and (c) task metadata payload updates in `memory`. For a platform running 20 tasks/day, after 6 months there are 3,600 task outcome entries in `history` and 3,600+ learning candidates in `knowledge`. The JSON fallback store (`embeddings.json`) has a 5,000-entry hard cap and will begin evicting legitimate memories. Qdrant collections grow unbounded with no TTL.

More critically: the `index_memory()` method in `embeddings.py` calls `clear_collection(MEMORY)` and re-indexes on every `update_memory()` call. If task outcomes are appended to MEMORY.md (a tempting shortcut), this triggers a full re-index on every task completion — `embed_texts()` cost on 200+ chunks, multiplied by 20 tasks/day.

**Why it happens:**
"Store everything, decide what to keep later" is a common pattern that defers the hard deduplication problem. The lifecycle scoring system was designed to handle this via decay — but decay only penalizes entries that are never recalled, not entries that are wrong or redundant.

**How to avoid:**
1. **Task outcomes go to `history`, not `memory`.** The MEMORY.md / `agent42_memory` collection is for durable consolidated facts. Task outcomes belong in `agent42_history`. Never call `update_memory()` or `append_to_section()` from the learning extractor.
2. **Knowledge collection TTL policy:** Entries in `agent42_knowledge` with `evidence_count < 2` and age > 30 days are candidates for deletion. Implement a `prune_knowledge()` method that runs weekly (cron job), not on every task.
3. **Outcome deduplication:** Before storing a task outcome in history, check for a near-duplicate from the same `task_type` in the last 7 days (Jaccard similarity > 0.80 on the summary text). Skip storage if a near-duplicate exists; increment `evidence_count` on the existing entry instead.
4. **Keep task outcomes thin:** Store `{task_type, tool_name, outcome: pass/fail, duration_bucket, key_error}` — not full agent transcripts. Full transcripts belong in log files, not Qdrant.
5. **Respect the JSON 5,000-entry cap:** The JSON fallback store evicts by timestamp (oldest first). Task tracking entries should have `source: "effectiveness"` so `_search_json()` can skip them for memory/history searches, preventing tracking data from evicting user memories.

**Warning signs:**
- `embeddings.json` reaches 4,000+ entries and new memories aren't persisting after system restarts.
- `collection_count("knowledge")` grows past 1,000 without manual pruning.
- `index_memory()` is called more than 5 times per minute in logs.

**Phase to address:** Phase 1 (task metadata schema) and Phase 2 (learning extraction) — storage strategy must be defined upfront. Retrofitting TTL and separation policies after the collections are polluted requires a full migration.

---

### Pitfall 6: Circular Dependency Between Learning Extraction and the Memory Store

**What goes wrong:**
The learning extractor calls an LLM (via `ModelRouter`) to summarize task outcomes. That LLM call itself is a tool invocation, which fires the effectiveness tracker, which tries to log to memory, which triggers `_schedule_reindex()`, which creates an asyncio Task. If the memory store's `reindex_memory()` also needs an LLM call for embeddings (via the OpenAI API path), you now have:

`Learning Extractor → ModelRouter → LLM Call → [records effectiveness] → MemoryStore.log_event_semantic → EmbeddingStore.embed_text → OpenAI API`

At 20 tasks/day, this is a quiet embedding API cost multiplier. More dangerously: if the LLM call for extraction fails with a rate limit, the error propagates into the memory store's reindex, masking where the failure originated.

With the local ONNX model (the typical path on this platform), the circular dependency doesn't cause a cost issue but can still cause asyncio loop contention: `_schedule_reindex()` uses `loop.create_task()`, and if the learning extractor is itself running inside a task, the new reindex task may not run until the extractor task yields — which it won't if the extractor is awaiting an LLM call.

**Why it happens:**
Learning extraction feels like a memory operation, so it naturally reaches for `MemoryStore` methods. But extraction is a compute-heavy summarization step that should be architecturally separate from the lightweight record-keeping that `MemoryStore` does.

**How to avoid:**
1. **Extract learnings as pure data first.** The extractor produces a structured `LearningRecord` dataclass (`task_type`, `tool_name`, `outcome`, `summary`, `raw_confidence`). This record is NOT passed through `MemoryStore` — it is queued into the effectiveness buffer (see Pitfall 4).
2. **Embed and store as a separate async pipeline step.** A dedicated `LearningPersistService` reads from the effectiveness buffer, embeds the records (single batch call), and upserts to `agent42_knowledge`. This runs on a timer, never inside the task execution path.
3. **The learning extractor must NOT call `log_event_semantic()` or `append_to_section()`.** These are user-facing memory operations. Automated extraction uses its own write path to `agent42_knowledge` only.
4. **Isolate LLM calls for extraction.** Use a dedicated, low-priority model slot (e.g., Gemini 2.0 Flash, not the task's primary model). Rate-limit extraction to 1 LLM call per completed task, queued, not inline with task completion.

**Warning signs:**
- `asyncio` warnings about tasks taking > 5 seconds to be scheduled after creation.
- `memory` logger shows `auto-reindex` runs happening during active task execution.
- OPENAI_API_KEY quota spikes coincide with task completion events.

**Phase to address:** Phase 2 (learning extraction) — the `LearningPersistService` architecture must be defined before writing the extractor, to prevent the extractor from taking the path of least resistance into `MemoryStore`.

---

### Pitfall 7: Recommendation Engine Over-Fits to Small Sample Sizes (Cold Start)

**What goes wrong:**
After 5 Flask tasks all succeed using the `shell` tool, the recommendation engine reports "shell: 100% success rate for flask/coding tasks" and promotes it with `confidence: 0.9`. The next Flask task gets a strong "use shell" recommendation even if a better approach exists. After a single Django task fails due to a missing venv, "python_exec: 0% success for app_create tasks" is stored and python_exec is demoted for all future app creation tasks.

At the platform's expected scale (one developer, 5–30 tasks/day), the recommendation engine will always be operating on statistically insufficient data for most task-type/tool combinations. A 100% success rate on 5 samples is not evidence of a reliable pattern — it's noise that happens to look like signal.

**Why it happens:**
Success rate is the obvious metric. Developers implement `success_count / total_count` without a minimum-sample guard, then use the resulting fractions directly as confidence scores.

**How to avoid:**
1. **Never surface a recommendation with fewer than 5 observations.** Below 5, the display says "insufficient data" — do not promote or demote any tool. Store the data, do not act on it.
2. **Use a Bayesian credible interval, not a point estimate.** For a tool with 3 successes out of 4 attempts, the 95% credible interval for success rate is approximately [0.40, 0.98] — far too wide to recommend confidently. A Wilson score interval or Beta distribution mean is more honest. Implementation: `adjusted_rate = (successes + 1) / (total + 2)` (Laplace smoothing) gives a conservative estimate that approaches the true rate as evidence grows.
3. **Decay recommendations with time.** A tool's effectiveness in December may not predict January performance (library updates, environment changes). Apply a 90-day half-life: `effective_rate = observed_rate * (0.5 ** (days_since_last_observation / 90))`. This prevents stale recommendations from dominating.
4. **Show confidence intervals to the user, not point estimates.** "shell: 78% ± 23% (n=8)" is more honest and useful than "shell: 78%".
5. **Global priors.** Before any task-type-specific observations accumulate, initialize tool effectiveness from the global history collection. A tool used successfully 200 times globally gets a prior of 0.7, not 0.5. This prevents cold-start over-demotion from a single early failure.

**Warning signs:**
- A rarely-used tool shows `confidence: 0.9` after fewer than 5 observations.
- Recommendations change dramatically (inversion) after a single new task.
- The recommendations dashboard shows certainty (> 85%) on task types with fewer than 10 historical tasks.

**Phase to address:** Phase 3 (recommendations engine) — Laplace smoothing and minimum-sample guards must be in the first recommendations implementation, not added after users report "the system keeps recommending the wrong tool."

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Store full agent transcript in Qdrant history | Easy to retrieve context; no summarization needed | Qdrant `history` collection grows 10x faster; recall gets dominated by task verbosity, not task relevance | Never — always summarize before storing |
| Use `update_memory()` for task outcomes | Reuses existing code path | Triggers `_schedule_reindex()` on every task — full MEMORY.md re-embed on every completion | Never — use `log_event_semantic()` instead |
| Write effectiveness data synchronously in `execute()` | Simple, testable | Adds 3–15ms latency per tool call in embedded Qdrant mode; visible in MCP stdio transport | Only in unit tests against mock Qdrant |
| Set `confidence: 0.9` on first learning extraction | Learnings surface immediately | Spurious learnings reach high confidence before enough evidence; hard to demote once used | Never — start at 0.3, require 3+ observations to exceed 0.7 |
| Single `knowledge` collection for all task types | Simpler collection management | Task-type filtering requires scanning all knowledge entries; OR conditions slow with large payloads | Acceptable up to ~5,000 entries; after that, consider per-task-type sub-collections |
| Inject all available learnings into agent prompt | Maximizes context completeness | Context rot — topically related but task-irrelevant memories degrade output quality (Chroma Research 2025) | Never — always filter by score threshold and task_type match |
| Run learning extraction synchronously at task end | Simple: "task completes → learning extracted" | Delays task completion acknowledgment to user; LLM call for extraction adds 2–8s to perceived task time | Only for offline batch processing, not live task completion |

---

## Integration Gotchas

Common mistakes when connecting to existing system components.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Qdrant embedded mode | Calling `set_payload()` inside a `loop.create_task()` created during an active Qdrant write | Serialize all Qdrant writes through the background drain service; never nest Qdrant calls inside Qdrant callbacks |
| `search_with_lifecycle()` | Adding required `task_type` filter condition — excludes all legacy points without the field | Use `must_not` + `should` pattern: include entries where `task_type == target` OR `task_type` field is absent |
| `_make_point_id()` deterministic UUID | Generating the same UUID for a task outcome stored twice (same text) — silently overwrites first entry | Include `task_id` + `timestamp` in the UUID seed for task-specific entries to prevent collisions |
| JSON fallback store (5,000 cap) | Effectiveness tracking entries occupy budget meant for user memories | Tag effectiveness entries with `source: "effectiveness"`; filter them out of memory/history searches; evict them first |
| `_schedule_reindex()` in `update_memory()` | Learning extractor calls `append_to_section()` — triggers background reindex during heavy task load | Learning extractor must never call `update_memory()` or `append_to_section()`; use direct Qdrant upsert only |
| `ProjectMemoryStore` budget split (60/40) | Task-level learnings added to project memory erode the 60% budget for human-authored project context | Task learnings go to global `agent42_knowledge` collection only; `ProjectMemoryStore` remains for project conventions and user preferences |
| `ToolContext` injection | Adding `effectiveness_tracker` to `ToolContext` and injecting into all tools | Tools must not depend on tracker; inject tracker only into the `ToolRegistry` wrapper layer, not individual tools |
| Redis embedding cache | Task outcome texts are cached as embeddings — Redis memory grows unbounded | Add TTL (24h) to effectiveness-related embedding cache entries; use a separate Redis key namespace (`eff:`) |

---

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Embedding every task outcome individually | Embedding cost grows linearly with task count; noticeable after 50+ tasks/day | Batch-embed task outcomes in groups of 10–20 in the background drain service | At ~20 tasks/day with OpenAI API; ONNX is faster but still single-threaded |
| Linear scan on `knowledge` collection for recommendations | `_search_json()` scans all 5,000 entries on every task start | Create a Qdrant payload index on `task_type` field after Phase 1 migration; always use Qdrant path for recommendations | JSON fallback breaks at ~500 knowledge entries (perceptible latency in MCP calls) |
| `search_with_lifecycle()` fetching `top_k * 3` for re-ranking | With `top_k=10`, fetches 30 results per search — acceptable now, expensive with 50K+ history entries | Add `task_type` filter to reduce candidate set before fetching; or reduce `fetch_k` multiplier from 3x to 2x | At ~50K history entries in server mode Qdrant |
| `collection_count()` called on every `is_available` check | Qdrant server health probe on every tool call | Cache already implemented in `_check_health()` (60s TTL) — do not bypass the cache in new code paths | At > 10 RPS to the MCP server (health probe becomes a bottleneck) |
| Strengthening all recalled memories on every search | `record_recall()` does one `retrieve()` + one `set_payload()` per result — 2N Qdrant RPCs per search | Batch recalls: collect all point IDs from a search, then do one batched `retrieve()` call and one batched `set_payload()` call | At top_k > 5 results per search; currently `record_recall()` is called in a loop |

---

## Security Mistakes

Domain-specific security issues beyond general web security.

| Mistake | Risk | Prevention |
|---------|------|------------|
| Storing raw tool call arguments in `knowledge` entries | Tool calls may contain file paths, API keys, or user data — persisted permanently in Qdrant | Sanitize before storing: strip absolute paths (replace with relative), redact strings matching `*_KEY`, `*_TOKEN`, `*_SECRET` patterns |
| Task outcome summaries generated by LLM contain hallucinated credentials | LLM may fabricate example API keys or passwords in "helpful" summaries that get stored as memory | Validate extracted learning text against credential patterns before storing; reject any entry containing strings that match `sk-`, `ghp_`, `Bearer ` prefixes |
| Effectiveness data leaks cross-agent information | Tool success/failure rates aggregate across all agents — an agent can infer what other agents have been doing | If multi-tenant isolation is required, scope `effectiveness` collection by agent_id, not globally |
| Proactive context injection includes secrets from past tasks | A past task stored its workspace path or environment variables; injection surfaces them in a new task | Apply the same sanitization rules on injection output as on storage input; post-filter injected text before appending to prompt |

---

## UX Pitfalls

Common user experience mistakes in this domain.

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Showing raw confidence scores (0.73) in recommendations | Opaque numbers don't convey meaning; users don't know if 0.73 is good or bad | Map to categorical labels: < 0.5 = "Limited data", 0.5–0.7 = "Emerging pattern", 0.7–0.85 = "Established", > 0.85 = "Strong signal (N observations)" |
| Surfacing recommendations for every task type, including types with 1 observation | Users see "recommendation" for a tool based on a single data point — erodes trust when the recommendation is wrong | Hard gate: only surface recommendations for task types with ≥ 5 observations |
| Learning extraction silently fails — user thinks the system is learning when it isn't | User expects automated learning but no learnings are being stored; trust erodes over time | Log extraction outcomes visibly: "Extracted 2 learnings from task X" in the dashboard activity feed |
| Post-task learning notification appears before the task result | Distraction — user focused on the task outcome, not the learning metadata | Show learning extraction as a collapsible "What was learned" section, not a primary notification |
| Recommendations change dramatically week-over-week as small samples fluctuate | User loses confidence in the recommendation system | Show trend direction ("improving", "stable", "declining") in addition to current rate; suppress recommendations when evidence_count < 5 |

---

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Task metadata added to Qdrant payloads:** Verify that legacy points (pre-v1.4) have been backfilled with `task_type: "legacy"` and that search filters use `should` conditions, not required `must` conditions, for `task_type`.
- [ ] **Learning extraction running:** Verify by checking `knowledge` collection count increases after task completion — the extractor can be wired up but silently fail if the LLM call rate-limits.
- [ ] **Effectiveness tracking not adding latency:** Measure MCP tool call P95 response time before and after enabling tracking; confirm < 5ms overhead per call.
- [ ] **Recommendations showing only for sufficient evidence:** Query the recommendations endpoint for a task type with exactly 4 observations — it must return "insufficient data", not a recommendation.
- [ ] **Context injection gated by score threshold:** Artificially inject a low-relevance learning (cosine similarity 0.55) and verify it does NOT appear in the agent's prompt.
- [ ] **JSON fallback store not polluted by tracking data:** With Qdrant unavailable, run 20 tasks and confirm `embeddings.json` entries with `source: "effectiveness"` are not returned in memory/history searches.
- [ ] **Graceful degradation maintained:** With both Qdrant and Redis unavailable, a task should complete successfully — learning extraction should silently no-op, not raise exceptions.
- [ ] **Memory bloat check:** After 100 tasks, verify MEMORY.md has not grown (task outcomes must be in HISTORY.md only) and `embeddings.json` is below 2,000 entries.

---

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Qdrant collections polluted with noisy learnings | MEDIUM | Run `clear_collection("knowledge")`; replay task history through extraction with updated evidence threshold; knowledge rebuilds from scratch in days |
| JSON fallback store at 5,000 entries, user memories evicted | MEDIUM | Export current entries; filter out all `source: "effectiveness"` entries manually; reimport clean set; enforce source separation going forward |
| Legacy Qdrant points missing `task_type` causing empty recommendation queries | LOW | Run one-time `scroll()` + `set_payload()` sweep to backfill `task_type: "legacy"` on all existing points; takes minutes in embedded mode |
| Recommendations confidently wrong (high confidence, wrong tool) | HIGH | Set `status: "quarantined"` on affected knowledge entries via Qdrant dashboard; adjust evidence threshold; re-run extraction against ground-truth task outcomes if available |
| Learning extractor coupled to MemoryStore, now triggering full re-indexes on every task | MEDIUM | Extract `LearningPersistService` into its own class that writes directly to Qdrant without calling `MemoryStore.update_memory()`; no data migration needed |
| Context injection degrading task quality (context rot) | LOW | Disable injection (`PROACTIVE_INJECTION_ENABLED=false` config flag) — task quality immediately restores; investigate score threshold before re-enabling |

---

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Qdrant payload schema divergence | Phase 1: Task metadata schema | Query existing collection with `task_type` filter; confirm both legacy and new entries are returned |
| Learning extraction noise | Phase 2: Learning extraction | Inject 5 identical synthetic tasks; verify only 1 consolidated learning is stored, not 5 |
| Context rot from injection | Phase 3: Proactive injection | Measure iteration count on a set of 10 benchmark tasks with and without injection; must not increase |
| Tracking latency on hot path | Phase 2: Effectiveness tracking | P95 MCP tool call latency must be within 5ms of baseline (before tracking) |
| Memory bloat from task outcomes | Phase 1: Task metadata schema | After 50 test tasks, MEMORY.md must be unchanged; HISTORY.md must have 50 new entries; `knowledge` collection must have ≤ 20 entries (deduplication working) |
| Circular dependency, extractor/store | Phase 2: Learning extraction | Learning extractor must pass code review confirming it never calls `MemoryStore.update_memory()` or `append_to_section()` |
| Recommendation cold start overfitting | Phase 3: Recommendations engine | Recommendations for task types with < 5 observations must return "insufficient data" in all UI and API surfaces |

---

## Sources

- Qdrant Payload documentation: [https://qdrant.tech/documentation/concepts/payload/](https://qdrant.tech/documentation/concepts/payload/)
- Qdrant Filtering guide: [https://qdrant.tech/articles/vector-search-filtering/](https://qdrant.tech/articles/vector-search-filtering/)
- Chroma Research — Context Rot (2025): [https://research.trychroma.com/context-rot](https://research.trychroma.com/context-rot)
- HaluMem: Evaluating Hallucinations in Memory Systems of Agents (arXiv 2511.03506): [https://arxiv.org/pdf/2511.03506](https://arxiv.org/pdf/2511.03506)
- How Memory Management Impacts LLM Agents (arXiv 2505.16067): [https://arxiv.org/html/2505.16067v2](https://arxiv.org/html/2505.16067v2)
- Agent Observability Overhead Benchmarks — LangSmith/Langfuse (2025): [https://research.aimultiple.com/agentic-monitoring/](https://research.aimultiple.com/agentic-monitoring/)
- Cold Start Problem in Recommender Systems: [https://en.wikipedia.org/wiki/Cold_start_(recommender_systems)](https://en.wikipedia.org/wiki/Cold_start_(recommender_systems))
- Existing codebase: `memory/qdrant_store.py`, `memory/store.py`, `memory/embeddings.py`, `tools/memory_tool.py`, `memory/project_memory.py`
- Agent42 CLAUDE.md pitfalls #109–116 (Qdrant availability, store fallback, circular imports)

---
*Pitfalls research for: task-level memory scoping, effectiveness tracking, and recommendation engines added to Agent42*
*Researched: 2026-03-17*
