"""Sidecar orchestrator — drives the execute -> callback lifecycle.

Receives AdapterExecutionContext payloads, checks idempotency,
executes agent tasks asynchronously, and POSTs results back to
Paperclip's callback URL when complete.
"""

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from core.config import settings
from core.sidecar_models import AdapterExecutionContext, CallbackPayload
from core.url_policy import set_current_run_id

logger = logging.getLogger("frood.sidecar.orchestrator")

# Idempotency guard: runId -> expiry timestamp (D-08)
_active_runs: dict[str, float] = {}
RUN_TTL_SECONDS = 3600  # 1 hour default


def _prune_expired_runs() -> None:
    """Remove expired entries from the active runs dict."""
    now = time.time()
    expired = [k for k, exp in _active_runs.items() if exp < now]
    for k in expired:
        del _active_runs[k]


def is_duplicate_run(run_id: str) -> bool:
    """Check if a runId is already active (idempotency guard).

    Also prunes expired entries on each call.
    Returns True if the run_id is already registered and not expired.
    """
    _prune_expired_runs()
    return run_id in _active_runs and time.time() < _active_runs[run_id]


def register_run(run_id: str) -> None:
    """Register a runId as active with TTL-based expiry."""
    _active_runs[run_id] = time.time() + RUN_TTL_SECONDS


def unregister_run(run_id: str) -> None:
    """Remove a runId from the active runs dict after completion."""
    _active_runs.pop(run_id, None)


class SidecarOrchestrator:
    """Orchestrates sidecar execution and callback delivery."""

    def __init__(
        self,
        memory_store: Any = None,
        agent_manager: Any = None,
        effectiveness_store: Any = None,
        reward_system: Any = None,
        memory_bridge: Any = None,
        tiered_routing_bridge: Any = None,
        tool_registry: Any = None,
    ):
        self.memory_store = memory_store
        self.agent_manager = agent_manager
        self.effectiveness_store = effectiveness_store
        self.reward_system = reward_system
        self.memory_bridge = memory_bridge
        self.tiered_routing_bridge = tiered_routing_bridge
        self.tool_registry = tool_registry
        self._http: httpx.AsyncClient | None = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Lazy-init httpx client (per pitfall 6: create once, close properly)."""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def _execute_research_workflow(
        self, run_id: str, ctx: AdapterExecutionContext,
        provider: str, model: str,
    ) -> dict[str, Any]:
        """Multi-phase research workflow: search → fetch → import, repeated.

        Instead of one big LLM call with 25 iterations, runs 3-4 focused
        phases with small tool sets and targeted prompts. Each phase gets
        only the tools it needs and a clear, short instruction.
        """
        import json as _json
        import random

        task_prompt = ctx.task or ""
        total_input = 0
        total_output = 0
        all_results: list[str] = []

        # Force research onto free tool-use models. Router can land on premium
        # models like anthropic/claude-sonnet-4-6 which our OpenRouter key can't
        # afford; override to zen/nemotron and let the fallback chain handle it.
        provider = "zen"
        model = "nemotron-3-super-free"

        # Extract API config from the task prompt
        api_token = "3399cb9b2df4c5bfb7d1204d326cb64d04ffaf5314f7115a98a1ca9a7f7bd80f"
        api_base = "https://synergicsolar.com/api/v1/prospects"

        # Pre-fetch known prospect names from Odoo so we can tell the model to skip them.
        # Without this, the model keeps rediscovering the same popular companies.
        known_companies: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                stats_resp = await client.get(
                    f"{api_base}/recent-names?limit=200",
                    headers={"Authorization": f"Bearer {api_token}"},
                )
                if stats_resp.status_code == 200:
                    data = stats_resp.json()
                    known_companies = data.get("names", [])[:200]
        except Exception as exc:
            logger.warning("Failed to fetch known prospect names: %s", exc)

        # Rotate target region per run to force breadth
        target_regions = [
            "California", "Texas", "Florida", "Arizona", "Nevada", "Colorado",
            "North Carolina", "New York", "New Jersey", "Massachusetts",
            "Illinois", "Georgia", "Virginia", "Washington", "Oregon",
            "Pennsylvania", "Ohio", "Michigan", "Utah", "New Mexico",
        ]
        target_region = random.choice(target_regions)
        logger.info("Research run %s targeting region: %s (known prospects: %d)",
                    run_id, target_region, len(known_companies))

        # Build exclusion list for the prompt (cap at 100 for context size)
        exclusion_hint = ""
        if known_companies:
            sample = known_companies[:100]
            exclusion_hint = (
                f"\n\nIMPORTANT: These {len(sample)} companies are ALREADY in our database. "
                f"DO NOT include them in your output (we already have them):\n"
                + ", ".join(sample[:50])
                + (f"\n... and {len(sample) - 50} more" if len(sample) > 50 else "")
            )

        # --- Phase 1: Search (web_search only) ---
        search_prompt = f"""You are a solar dealer research agent. Phase 1: SEARCH ONLY.

{task_prompt}

TARGET REGION FOR THIS RUN: {target_region}
Focus searches on cities/regions in {target_region}. Different cities per query.

RULES:
- Use ONLY web_search. DO NOT use python_exec, web_fetch, or http_request.
- Run 10-15 varied search queries — use DIFFERENT cities, DIFFERENT keywords, DIFFERENT source types.
- Query variety suggestions:
  * "solar installer [city] [state]"
  * "independent solar dealer [city]"
  * "site:yelp.com solar {target_region}"
  * "site:bbb.org solar {target_region}"
  * "best rated solar companies [city]"
  * "[city] solar reviews"
  * Small/medium businesses, NOT national chains (skip SunPower, Sunrun, Tesla, Vivint)
- Aim for 20+ UNIQUE companies across all queries.
- After your last search, output the final JSON array as your response text.{exclusion_hint}

Output format (after searches are done):
[{{"name": "...", "city": "...", "state": "...", "website": "...", "source_query": "..."}}, ...]

DO NOT fetch websites. DO NOT import. DO NOT format with python — just output the JSON directly in your text response.
CRITICAL: Exclude any company name that appears in the "already in our database" list above."""

        logger.info("Research phase 1: SEARCH (run %s)", run_id)
        search_result = await self._call_provider(
            provider, model,
            [{"role": "user", "content": search_prompt}],
            f"{run_id}-search", agent_id=ctx.agent_id,
            task_type="research", phase="search",
        )
        total_input += search_result.get("input_tokens", 0)
        total_output += search_result.get("output_tokens", 0)
        search_output = search_result.get("summary", "")
        all_results.append(f"SEARCH: {search_output[:3000]}")

        if search_result.get("error"):
            return {**search_result, "summary": f"Search phase failed: {search_result['error']}"}

        # --- Phase 2: Fetch contact info (web_fetch + http_request for raw HTML) ---
        fetch_prompt = f"""You are a solar dealer research agent. Phase 2: FETCH CONTACT INFO.

Here are the companies found in the search phase:
{search_output[:5000]}

TOOLS AVAILABLE:
- web_fetch(url) — returns clean text of a page. Use first to find visible emails/phones.
- http_request(url, method="GET") — returns raw HTML. Use to find mailto: hrefs that web_fetch strips.

YOUR GOAL: Include EVERY company in the output — maximum QUANTITY, not quality.
We have a form-submitter agent that will handle companies without emails.

STRATEGY FOR EACH COMPANY (max 2 tool calls per company, move on fast):
1. Try web_fetch on `<website>/contact` (use http_request if web_fetch fails or returns empty).
2. Extract whatever you can: email, phone, contact form URL.

INCLUSION RULES — keep the company in the output ALWAYS if:
- You found a real email → set `email`
- You found a phone number → set `phone`
- You fetched a /contact page that had a form → set `contact_form_url` to that /contact URL
- Even if the site returned 403/500/blocked → still include with just `website` and `contact_form_url` = "{{website}}/contact" (the form submitter will try it)
- Even if you couldn't reach the site at all → still include with just `website`

NEVER skip a company. The form submitter handles the edge cases.

SKIP a company ONLY if the search phase flagged it as a known duplicate (in the exclusion list from search).

After fetching, output the final JSON array as your text response:
[{{"name": "...", "contact_name": "...", "email": "...", "phone": "...", "contact_form_url": "...", "website": "...", "city": "...", "state_code": "...", "company_size": "1-10"}}, ...]

Output ALL companies from the search phase. Leave unknown fields as empty strings."""

        logger.info("Research phase 2: FETCH (run %s)", run_id)
        fetch_result = await self._call_provider(
            provider, model,
            [{"role": "user", "content": fetch_prompt}],
            f"{run_id}-fetch", agent_id=ctx.agent_id,
            task_type="research", phase="fetch",
        )
        total_input += fetch_result.get("input_tokens", 0)
        total_output += fetch_result.get("output_tokens", 0)
        fetch_output = fetch_result.get("summary", "")
        all_results.append(f"FETCH: {fetch_output[:3000]}")

        if fetch_result.get("error"):
            return {**fetch_result, "input_tokens": total_input, "output_tokens": total_output}

        # --- Phase 3: Deduplicate + Import (http_request only, 3 iterations max) ---
        import_prompt = f"""You are a solar dealer research agent. Phase 3: check for duplicates and import new prospects.

Here are the enriched companies with emails:
{fetch_output[:4000]}

Step 1: Check duplicates by calling:
POST {api_base}/check-duplicates
Authorization: Bearer {api_token}
Content-Type: application/json
Body: {{"companies": [list of {{"email": "...", "name": "..."}}]}}

Step 2: Import non-duplicates by calling:
POST {api_base}/import
Authorization: Bearer {api_token}
Content-Type: application/json
Body: {{"batch_name": "Research Import", "source": "web_search", "target_region": "...", "prospects": [array of prospect objects]}}

Each prospect needs: name, contact_name, email, phone, website, city, state_code, company_size, source (use "web_search"), ai_research_notes (2 sentences), ai_personalization_context (2 bullet points about pain point + Synergic angle).

Synergic value props: keep your brand, PPW commissions, team hierarchy with overrides, AI tools, Dealer>Pro>Master growth path.

Step 3: Report what was imported vs skipped."""

        logger.info("Research phase 3: IMPORT (run %s)", run_id)
        import_result = await self._call_provider(
            provider, model,
            [{"role": "user", "content": import_prompt}],
            f"{run_id}-import", agent_id=ctx.agent_id,
            task_type="research", phase="import",
        )
        total_input += import_result.get("input_tokens", 0)
        total_output += import_result.get("output_tokens", 0)
        import_output = import_result.get("summary", "")
        all_results.append(f"IMPORT: {import_output[:500]}")

        summary = f"Research workflow complete.\n\n" + "\n\n".join(all_results)

        return {
            "summary": summary,
            "provider": provider,
            "model": model,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cost_usd": 0.0,
        }

    # Business hours configuration (US Eastern)
    # Email tasks only run Mon-Sat, 7 AM - 9 PM ET
    _BUSINESS_HOURS = {
        "email": {"days": (0, 1, 2, 3, 4, 5), "start_hour": 7, "end_hour": 21, "tz": "US/Eastern"},
    }

    def _is_within_business_hours(self, task_type: str) -> tuple[bool, str]:
        """Check if the current time is within business hours for the task type.

        Returns (allowed, reason). Tasks without business hour config are always allowed.
        """
        config = self._BUSINESS_HOURS.get(task_type)
        if not config:
            return True, ""

        from datetime import datetime, timezone
        try:
            import zoneinfo
            tz = zoneinfo.ZoneInfo(config["tz"])
        except Exception:
            return True, ""  # If timezone unavailable, allow

        now = datetime.now(tz)
        day_of_week = now.weekday()  # 0=Monday, 6=Sunday
        hour = now.hour

        if day_of_week not in config["days"]:
            day_name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day_of_week]
            return False, f"Outside business days ({day_name}). Email runs Mon-Sat only."

        if hour < config["start_hour"] or hour >= config["end_hour"]:
            return False, f"Outside business hours ({hour}:00 ET). Email runs {config['start_hour']}AM-{config['end_hour'] - 12}PM ET."

        return True, ""

    async def execute_sync(self, run_id: str, ctx: AdapterExecutionContext) -> dict[str, Any]:
        """Execute an agent task synchronously and return the result.

        Called directly from the route handler. Returns a dict with
        summary, provider, model, input_tokens, output_tokens, cost_usd.
        """
        # Scope URL-policy request counting to this run so each heartbeat
        # gets its own budget instead of sharing one process-wide counter.
        set_current_run_id(run_id)

        task_type = ctx.task_type or ctx.context.get("taskType", "")

        # Business hours guard — skip email tasks outside Mon-Sat 7AM-9PM ET
        allowed, reason = self._is_within_business_hours(task_type)
        if not allowed:
            logger.info("Skipping run %s: %s", run_id, reason)
            return {
                "summary": f"Skipped: {reason}",
                "output": f"Skipped: {reason}",
                "provider": "",
                "model": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
            }

        logger.info(
            "Executing run %s for agent %s (wake_reason=%s)",
            run_id, ctx.agent_id, ctx.wake_reason,
        )

        # Memory recall
        recalled_memories: list[dict] = []
        if self.memory_bridge and ctx.agent_id:
            try:
                recalled_memories = await asyncio.wait_for(
                    self.memory_bridge.recall(
                        query=ctx.task or ctx.task_id,
                        agent_id=ctx.agent_id,
                        company_id=ctx.company_id,
                        top_k=5,
                        run_id=run_id,
                    ),
                    timeout=0.2,
                )
            except Exception:
                pass  # Non-critical

        # Routing
        routing = None
        if self.tiered_routing_bridge and ctx.agent_id:
            try:
                routing = await self.tiered_routing_bridge.resolve(
                    role=ctx.context.get("agentRole", ""),
                    agent_id=ctx.agent_id,
                    preferred_provider=ctx.adapter_config.preferred_provider,
                    preferred_model=ctx.context.get("model", ""),
                    task_type=ctx.task_type or ctx.context.get("taskType", ""),
                )
                logger.info(
                    "Routing run %s: provider=%s model=%s",
                    run_id, routing.provider, routing.model,
                )
            except Exception as exc:
                logger.warning("Routing failed for run %s: %s", run_id, exc)

        # Log routing decision
        if routing and self.effectiveness_store:
            try:
                await self.effectiveness_store.log_routing_decision(
                    run_id=run_id, agent_id=ctx.agent_id, company_id=ctx.company_id,
                    provider=routing.provider, model=routing.model,
                    tier=routing.tier, task_category=routing.task_category,
                )
            except Exception:
                pass

        # LLM call — route research tasks to multi-phase workflow
        provider_name = routing.provider if routing else "zen"
        model_name = routing.model if routing else "minimax-m2.5-free"
        effective_task_type = ctx.task_type or ctx.context.get("taskType", "")

        # Detect research tasks by task_type or agent role
        is_research = (
            effective_task_type == "research"
            or ctx.context.get("agentRole") == "researcher"
            or "research agent" in (ctx.task or "").lower()[:200]
        )

        if is_research:
            logger.info("Run %s: using multi-phase research workflow", run_id)
            result = await self._execute_research_workflow(
                run_id, ctx, provider_name, model_name,
            )
        else:
            task_prompt = ctx.task or ctx.context.get("task", "") or f"Execute task for agent {ctx.agent_id}"
            messages: list[dict[str, str]] = []
            if recalled_memories:
                mem_text = "\n".join(f"- {m['text']}" for m in recalled_memories)
                messages.append({"role": "system", "content": f"Relevant context:\n{mem_text}"})
            messages.append({"role": "user", "content": task_prompt})

            llm_response = await self._call_provider(
                provider_name, model_name, messages, run_id, agent_id=ctx.agent_id,
                task_type=effective_task_type,
            )

            summary = llm_response.get("summary", "")
            if llm_response.get("error"):
                summary = f"LLM error: {llm_response['error']}"

            result = {
                "summary": summary,
                "provider": provider_name,
                "model": model_name,
                "input_tokens": llm_response.get("input_tokens", 0),
                "output_tokens": llm_response.get("output_tokens", 0),
                "cost_usd": llm_response.get("cost_usd", 0.0),
            }

        # Log spend
        if self.effectiveness_store:
            try:
                await self.effectiveness_store.log_spend(
                    agent_id=ctx.agent_id, company_id=ctx.company_id,
                    provider=provider_name, model=model_name,
                    input_tokens=result["input_tokens"], output_tokens=result["output_tokens"],
                    cost_usd=result["cost_usd"],
                )
            except Exception:
                pass

        # Fire-and-forget learning extraction
        summary = result.get("summary", "")
        if self.memory_bridge and ctx.agent_id and summary:
            asyncio.create_task(
                self.memory_bridge.learn_async(
                    summary=summary, agent_id=ctx.agent_id,
                    company_id=ctx.company_id,
                    task_type=ctx.context.get("taskType", ""),
                    run_id=run_id,
                )
            )

        return result

    async def execute_async(self, run_id: str, ctx: AdapterExecutionContext) -> None:
        """Execute an agent task and POST results to Paperclip callback.

        This method runs as a background task (not awaited in the route handler).
        """
        # Scope URL-policy request counting to this run so each heartbeat
        # gets its own budget instead of sharing one process-wide counter.
        set_current_run_id(run_id)

        result: dict[str, Any] = {}
        usage: dict[str, Any] = {}
        status = "completed"
        error: str | None = None

        try:
            logger.info(
                "Executing run %s for agent %s (wake_reason=%s)",
                run_id,
                ctx.agent_id,
                ctx.wake_reason,
            )

            # Step 1: Memory recall with hard timeout (MEM-01, MEM-02, per D-01, D-02)
            recalled_memories: list[dict] = []
            if self.memory_bridge and ctx.agent_id:
                try:
                    recalled_memories = await asyncio.wait_for(
                        self.memory_bridge.recall(
                            query=ctx.context.get("taskDescription", "") or ctx.task_id,
                            agent_id=ctx.agent_id,
                            company_id=ctx.company_id,
                            top_k=5,
                            run_id=run_id,
                        ),
                        timeout=0.2,  # 200ms hard limit (MEM-02)
                    )
                    logger.info(
                        "Recalled %d memories for agent %s in run %s",
                        len(recalled_memories),
                        ctx.agent_id,
                        run_id,
                    )
                except TimeoutError:
                    logger.warning(
                        "Memory recall timed out for run %s — proceeding without memories",
                        run_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "Memory recall failed for run %s: %s — proceeding without memories",
                        run_id,
                        exc,
                    )

            # Step 1.5: Routing resolution (ROUTE-01 through ROUTE-04)
            # TODO(phase-27): Verify agentRole key name against real Paperclip payload
            routing = None
            if self.tiered_routing_bridge and ctx.agent_id:
                try:
                    routing = await self.tiered_routing_bridge.resolve(
                        role=ctx.context.get("agentRole", ""),
                        agent_id=ctx.agent_id,
                        preferred_provider=ctx.adapter_config.preferred_provider,
                    )
                    logger.info(
                        "Routing run %s: agent=%s role=%s tier=%s provider=%s model=%s base_cat=%s cat=%s",
                        run_id,
                        ctx.agent_id,
                        ctx.context.get("agentRole", ""),
                        routing.tier,
                        routing.provider,
                        routing.model,
                        routing.base_category,
                        routing.task_category,
                    )
                except Exception as exc:
                    logger.warning(
                        "Routing resolution failed for run %s: %s -- using defaults",
                        run_id,
                        exc,
                    )

            # Log routing decision for history queries (D-11)
            if routing and self.effectiveness_store:
                try:
                    await self.effectiveness_store.log_routing_decision(
                        run_id=run_id,
                        agent_id=ctx.agent_id,
                        company_id=ctx.company_id,
                        provider=routing.provider,
                        model=routing.model,
                        tier=routing.tier,
                        task_category=routing.task_category,
                    )
                except Exception as exc:
                    logger.debug("Failed to log routing decision: %s", exc)

            # Step 1.6: Auto-memory injection (ADV-01, D-12, D-14, D-15, D-16)
            if recalled_memories and getattr(ctx.adapter_config, "auto_memory", True):
                ctx.context["memoryContext"] = {
                    "memories": [
                        {"text": m["text"], "score": m["score"], "source": m.get("source", "")}
                        for m in recalled_memories
                    ],
                    "injectedAt": datetime.now(UTC).isoformat(),
                    "count": len(recalled_memories),
                }
                logger.info(
                    "Auto-injected %d memories into context for run %s",
                    len(recalled_memories),
                    run_id,
                )

            # Step 1.7: Strategy detection (D-17, D-18, D-19)
            strategy = ctx.context.get("strategy", "standard")
            known_strategies = {"standard", "fan-out", "wave"}
            if strategy not in known_strategies:
                logger.warning(
                    "Unknown strategy '%s' for run %s — falling back to 'standard'",
                    strategy,
                    run_id,
                )
                strategy = "standard"
            if strategy != "standard":
                logger.info(
                    "Run %s using strategy '%s' for agent %s",
                    run_id,
                    strategy,
                    ctx.agent_id,
                )

            # Step 2: Execute LLM call via resolved provider
            provider_name = routing.provider if routing else "zen"
            model_name = routing.model if routing else "minimax-m2.5-free"
            task_prompt = ctx.task or ctx.context.get("task", "") or f"Execute task for agent {ctx.agent_id}"

            # Build messages with optional memory context
            system_parts = []
            if recalled_memories:
                mem_text = "\n".join(f"- {m['text']}" for m in recalled_memories)
                system_parts.append(f"Relevant context from previous runs:\n{mem_text}")
            system_msg = "\n\n".join(system_parts) if system_parts else None

            messages: list[dict[str, str]] = []
            if system_msg:
                messages.append({"role": "system", "content": system_msg})
            messages.append({"role": "user", "content": task_prompt})

            llm_response = await self._call_provider(
                provider_name, model_name, messages, run_id, agent_id=ctx.agent_id,
            )

            summary = llm_response.get("summary", "")
            input_tokens = llm_response.get("input_tokens", 0)
            output_tokens = llm_response.get("output_tokens", 0)
            cost_usd = llm_response.get("cost_usd", 0.0)
            llm_error = llm_response.get("error")

            if llm_error:
                logger.warning("LLM call failed for run %s: %s", run_id, llm_error)
                # Still report as completed with the error in summary
                summary = f"LLM error: {llm_error}"

            result = {
                "summary": summary,
                "output": summary,
                "wakeReason": ctx.wake_reason,
                "taskId": ctx.task_id,
                "recalledMemories": len(recalled_memories),
                "provider": provider_name,
                "model": model_name,
            }
            usage = {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "costUsd": cost_usd,
                "model": model_name,
                "provider": provider_name,
            }

            # Log spend for 24h aggregation (D-14)
            if self.effectiveness_store:
                try:
                    await self.effectiveness_store.log_spend(
                        agent_id=ctx.agent_id,
                        company_id=ctx.company_id,
                        provider=usage.get("provider", ""),
                        model=usage.get("model", ""),
                        input_tokens=usage.get("inputTokens", 0),
                        output_tokens=usage.get("outputTokens", 0),
                        cost_usd=usage.get("costUsd", 0.0),
                    )
                except Exception as exc:
                    logger.debug("Failed to log spend: %s", exc)

        except Exception as exc:
            logger.error("Run %s failed: %s", run_id, exc, exc_info=True)
            status = "failed"
            error = str(exc)

        finally:
            # Step 3: POST callback to Paperclip — never delayed by learn_async (D-05)
            await self._post_callback(run_id, status, result, usage, error)

            # Capture transcript for deferred learning extraction (D-18)
            if self.effectiveness_store and result.get("summary"):
                try:
                    await self.effectiveness_store.save_transcript(
                        run_id=run_id,
                        agent_id=ctx.agent_id,
                        company_id=ctx.company_id,
                        task_type=ctx.context.get("taskType", ""),
                        summary=result.get("summary", ""),
                    )
                except Exception as exc:
                    logger.debug("Failed to save transcript: %s", exc)

            # Step 4: Fire-and-forget learning extraction AFTER callback (MEM-03, D-05)
            if self.memory_bridge and ctx.agent_id and result.get("summary"):
                asyncio.create_task(
                    self.memory_bridge.learn_async(
                        summary=result.get("summary", ""),
                        agent_id=ctx.agent_id,
                        company_id=ctx.company_id,
                        task_type=ctx.context.get("taskType", ""),
                        run_id=run_id,
                    )
                )

            unregister_run(run_id)

    # Tool whitelists per task type — only expose relevant tools.
    # NOTE: research phases use more specific whitelists, see _execute_research_workflow.
    _TASK_TOOL_WHITELIST: dict[str, set[str]] = {
        "research": {"web_search", "web_fetch", "http_request"},  # NO python_exec — model wastes iterations
        "email": {"python_exec", "http_request"},
        "coding": {"python_exec", "git", "run_tests", "run_linter", "code_intel"},
        "monitoring": {"python_exec", "http_request"},
    }

    # Per-phase tool whitelists for the research workflow (override the task whitelist)
    _RESEARCH_PHASE_TOOLS: dict[str, set[str]] = {
        "search": {"web_search"},                   # SEARCH phase: ONLY search
        "fetch":  {"web_fetch", "http_request"},    # FETCH phase: web_fetch (text) + http_request (raw HTML for mailto:)
        "import": {"http_request"},                 # IMPORT phase: ONLY http_request (call APIs)
    }

    # Max tool-call iterations per task type (default 25 for uncategorized)
    _TASK_MAX_ITERATIONS: dict[str, int] = {
        "research": 15,
        "email": 10,
        "monitoring": 5,
    }

    def _get_tool_schemas(self, task_type: str = "", phase: str = "") -> list[dict]:
        """Get OpenAI function-calling schemas, filtered by task type (and research phase).

        For research tasks, phase-specific whitelists override the task-type whitelist,
        ensuring each phase only sees the tools it needs (avoids model distraction).
        """
        if not self.tool_registry:
            return []

        # Research phases use per-phase whitelists
        if task_type == "research" and phase in self._RESEARCH_PHASE_TOOLS:
            whitelist = self._RESEARCH_PHASE_TOOLS[phase]
        else:
            whitelist = self._TASK_TOOL_WHITELIST.get(task_type)

        schemas = []
        for tool in self.tool_registry._tools.values():
            if tool.name in self.tool_registry._disabled:
                continue
            if whitelist and tool.name not in whitelist:
                continue
            schemas.append(tool.to_schema())
        return schemas

    async def _execute_tool_call(self, name: str, arguments: dict, agent_id: str) -> str:
        """Execute a tool call and return the result as a string."""
        if not self.tool_registry:
            return "Error: tool registry not available"
        try:
            result = await self.tool_registry.execute(tool_name=name, agent_id=agent_id, **arguments)
            if result.success:
                return result.output or "OK"
            return f"Error: {result.error}"
        except Exception as exc:
            return f"Error executing {name}: {exc}"

    async def _call_provider(
        self,
        provider: str,
        model: str,
        messages: list[dict],
        run_id: str,
        agent_id: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call the LLM provider with tool-use loop.

        Returns dict with: summary, input_tokens, output_tokens, cost_usd, error.
        Falls back through providers on failure. Handles tool calls in a loop
        (max 15 iterations) until the model returns a text response.
        """
        import json as _json
        import os

        provider_config = {
            "zen": {
                "url": "https://opencode.ai/zen/v1/chat/completions",
                "key_env": "ZEN_API_KEY",
            },
            "nvidia": {
                "url": "https://integrate.api.nvidia.com/v1/chat/completions",
                "key_env": "NVIDIA_API_KEY",
            },
            "openrouter": {
                "url": "https://openrouter.ai/api/v1/chat/completions",
                "key_env": "OPENROUTER_API_KEY",
            },
        }

        task_type = kwargs.get("task_type", "")
        phase = kwargs.get("phase", "")

        # Build ordered (provider, model) attempts for this task type.
        # First try the requested provider/model, then fall back through Zen models and other providers.
        if task_type == "research":
            zen_models_to_try = ["nemotron-3-super-free", "minimax-m2.5-free"]
        else:
            zen_models_to_try = ["minimax-m2.5-free", "nemotron-3-super-free"]

        attempts: list[tuple[str, str]] = [(provider, model)]
        for zm in zen_models_to_try:
            if (provider, model) != ("zen", zm):
                attempts.append(("zen", zm))
        # NVIDIA fallback — meta/llama-3.1-70b-instruct has strong tool-calling on free tier
        attempts.append(("nvidia", "meta/llama-3.1-70b-instruct"))
        attempts.append(("nvidia", "nvidia/llama-3.1-nemotron-70b-instruct"))
        attempts.append(("openrouter", "google/gemini-2.0-flash-001"))

        # Deduplicate while preserving order
        seen = set()
        dedup_attempts: list[tuple[str, str]] = []
        for prov_model in attempts:
            if prov_model not in seen:
                seen.add(prov_model)
                dedup_attempts.append(prov_model)
        attempts = dedup_attempts

        tool_schemas = self._get_tool_schemas(task_type, phase=phase)
        total_input = 0
        total_output = 0
        last_error = ""

        for prov, attempt_model in attempts:
            config = provider_config.get(prov)
            if not config:
                continue
            api_key = os.environ.get(config["key_env"], "")
            if not api_key:
                last_error = f"{config['key_env']} not set"
                continue

            use_model = attempt_model
            logger.info("Calling %s/%s for run %s (tools=%d)", prov, use_model, run_id, len(tool_schemas))

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            # Copy messages for this provider attempt
            conv = list(messages)
            max_iterations = self._TASK_MAX_ITERATIONS.get(task_type, 25)
            provider_failed = False  # True if loop exited due to HTTP error

            try:
                # Per-call timeout 90s — nemotron-3-super-free can be slow with growing context
                async with httpx.AsyncClient(timeout=90.0) as client:
                    for iteration in range(max_iterations):
                        payload: dict[str, Any] = {
                            "model": use_model,
                            "messages": conv,
                            "max_tokens": 4096,
                        }
                        if tool_schemas:
                            payload["tools"] = tool_schemas

                        resp = await client.post(config["url"], headers=headers, json=payload)
                        if resp.status_code == 429:
                            # Rate limited — check retry-after to decide retry vs fail-fast
                            retry_after = 5.0
                            try:
                                retry_after = float(resp.headers.get("retry-after", "5"))
                            except Exception:
                                pass
                            if retry_after > 30:
                                # Long rate limit (model quota exhausted) — fall through to next provider/model
                                last_error = f"HTTP 429: rate limited for {retry_after:.0f}s, giving up on {prov}/{use_model}"
                                logger.warning("%s for run %s", last_error, run_id)
                                provider_failed = True
                                break
                            logger.warning("Rate limited on %s, sleeping %.1fs", prov, retry_after)
                            await asyncio.sleep(retry_after)
                            continue
                        if resp.status_code >= 400:
                            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                            logger.warning("Provider %s failed for run %s: %s", prov, run_id, last_error)
                            provider_failed = True
                            break

                        data = resp.json()
                        resp_usage = data.get("usage", {})
                        total_input += resp_usage.get("prompt_tokens", 0)
                        total_output += resp_usage.get("completion_tokens", 0)

                        choices = data.get("choices", [])
                        if not choices:
                            last_error = "Empty choices in response"
                            break

                        msg = choices[0].get("message", {})
                        finish = choices[0].get("finish_reason", "")
                        tool_calls = msg.get("tool_calls")

                        # If model wants to call tools
                        if tool_calls and finish in ("tool_calls", "stop"):
                            # Append assistant message with tool calls
                            conv.append(msg)

                            for tc in tool_calls:
                                fn = tc.get("function", {})
                                tool_name = fn.get("name", "")
                                try:
                                    tool_args = _json.loads(fn.get("arguments", "{}"))
                                except _json.JSONDecodeError:
                                    tool_args = {}

                                logger.info(
                                    "Run %s tool call [%d]: %s(%s)",
                                    run_id, iteration, tool_name,
                                    str(tool_args)[:100],
                                )

                                tool_result = await self._execute_tool_call(
                                    tool_name, tool_args, agent_id,
                                )

                                # Truncate tool results aggressively for research to keep context small
                                # Research context grows fast with many search/fetch results.
                                # web_fetch results are MUCH bigger (full HTML) than web_search results.
                                if task_type == "research":
                                    max_tool_chars = 2000 if tool_name == "web_fetch" else 3000
                                else:
                                    max_tool_chars = 8000
                                conv.append({
                                    "role": "tool",
                                    "tool_call_id": tc.get("id", ""),
                                    "content": tool_result[:max_tool_chars],
                                })

                            continue  # Next iteration — model sees tool results

                        # Model returned text (no tool calls) — we're done
                        content = msg.get("content", "")
                        return {
                            "summary": content,
                            "input_tokens": total_input,
                            "output_tokens": total_output,
                            "cost_usd": 0.0,
                        }

                    # If the loop exited due to HTTP error, skip salvage (this provider is broken)
                    # and fall through to the outer loop for the next (provider, model) attempt.
                    if provider_failed:
                        continue

                    # Loop ended at max iterations with successful API calls — try to salvage.
                    # First, ask model for a final summary without tools.
                    conv.append({
                        "role": "user",
                        "content": "Provide your final output now as text. DO NOT call any more tools — just output your results.",
                    })
                    try:
                        final_payload: dict[str, Any] = {
                            "model": use_model,
                            "messages": conv,
                            "max_tokens": 4096,
                        }
                        # No tools in payload — force text response
                        final_resp = await client.post(config["url"], headers=headers, json=final_payload)
                        if final_resp.status_code < 400:
                            final_data = final_resp.json()
                            final_usage = final_data.get("usage", {})
                            total_input += final_usage.get("prompt_tokens", 0)
                            total_output += final_usage.get("completion_tokens", 0)
                            final_choices = final_data.get("choices", [])
                            if final_choices:
                                final_content = final_choices[0].get("message", {}).get("content", "")
                                if final_content:
                                    return {
                                        "summary": final_content,
                                        "input_tokens": total_input,
                                        "output_tokens": total_output,
                                        "cost_usd": 0.0,
                                    }
                    except Exception as exc:
                        logger.warning("Forced summary failed for run %s: %s", run_id, exc)

                    # Last-resort: dump tool results from conv as raw summary
                    tool_results = []
                    for m in conv:
                        if m.get("role") == "tool":
                            content = m.get("content", "")
                            if content:
                                tool_results.append(str(content)[:1500])
                    if tool_results:
                        salvaged = "Tool results collected (model failed to summarize):\n\n" + "\n\n---\n\n".join(tool_results[:10])
                        return {
                            "summary": salvaged,
                            "input_tokens": total_input,
                            "output_tokens": total_output,
                            "cost_usd": 0.0,
                        }

                    return {
                        "summary": f"Reached {max_iterations} tool-call iterations" + (f" — {last_error}" if last_error else ""),
                        "input_tokens": total_input,
                        "output_tokens": total_output,
                        "cost_usd": 0.0,
                    }

            except Exception as exc:
                last_error = str(exc)
                logger.warning("Provider %s threw for run %s: %s", prov, run_id, exc, exc_info=True)
                continue

        return {"summary": "", "error": last_error or "All providers failed", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    async def _post_callback(
        self,
        run_id: str,
        status: str,
        result: dict[str, Any],
        usage: dict[str, Any],
        error: str | None,
    ) -> None:
        """POST execution results back to Paperclip's callback endpoint."""
        callback_url = settings.paperclip_api_url
        if not callback_url:
            logger.warning(
                "PAPERCLIP_API_URL not configured — skipping callback for run %s",
                run_id,
            )
            return

        url = f"{callback_url.rstrip('/')}/api/heartbeat-runs/{run_id}/callback"
        payload = CallbackPayload(
            run_id=run_id,
            status=status,
            result=result,
            usage=usage,
            error=error,
        )

        try:
            client = await self._get_http_client()
            resp = await client.post(
                url,
                json=payload.model_dump(by_alias=True),
                headers={"Content-Type": "application/json"},
            )
            logger.info(
                "Callback for run %s: %s %s",
                run_id,
                resp.status_code,
                url,
            )
        except Exception as exc:
            logger.error(
                "Callback failed for run %s to %s: %s",
                run_id,
                url,
                exc,
            )

    async def shutdown(self) -> None:
        """Close the httpx client (per pitfall 6)."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None
