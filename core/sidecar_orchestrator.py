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
Companies without any contact channel still get stored for manual review.

STRATEGY FOR EACH COMPANY (max 2 tool calls per company, move on fast):
1. Try web_fetch on `<website>/contact` (use http_request if web_fetch fails or returns empty).
2. Extract whatever you can: email, phone, contact form URL.

INCLUSION RULES — always keep the company in the output, but ONLY fill
fields you actually verified via a successful fetch. Empty strings for
fields you couldn't confirm.

- You found a real email address in the page text → set `email`
- You found a phone number in the page text → set `phone`
- IMPORTANT: Only set `contact_form_url` when BOTH are true:
    (a) The fetch returned a real contact page — NOT a 404 page,
        NOT a redirect to the homepage, NOT a directory/listing site
        like yelp.com or bbb.org
    (b) The fetched page contains visible form fields (a message
        textarea and at least a name or email input)
  If the fetch failed (403/500/timeout) or returned a 404 "page not
  found" or redirected away, leave `contact_form_url` as empty string.
  DO NOT guess `{{website}}/contact` as a fallback — a downstream agent
  tries to submit forms at these URLs, and fake URLs waste its time
  and produce misleading audit logs.
- Site completely unreachable → include with just `website` set, all
  other contact fields empty string

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

        # --- Phase 3: Deterministic import (pure Python, no LLM) ---
        #
        # Previous versions asked the LLM to call /check-duplicates and /import
        # via the http_request tool. This failed repeatedly: small/reasoning
        # models dropped the required `url` parameter, hallucinated company
        # lists when grounding was thin, or gave up after long reasoning.
        # None of that work actually needed a model — it's two HTTP calls
        # against a payload the LLM already produced in phase 2. So we do
        # them directly. The /import endpoint handles its own duplicate
        # checking internally (see synergic_solar/controllers/prospect_api.py,
        # import_prospects() line 149), so /check-duplicates is redundant here.
        logger.info("Research phase 3: IMPORT (run %s, deterministic)", run_id)

        prospects = self._parse_json_array(fetch_output)
        if not prospects:
            import_summary = (
                "Import skipped: phase 2 produced no parseable JSON array. "
                "Check the FETCH phase output above."
            )
            logger.warning("Research run %s phase 3 aborted: %s", run_id, import_summary)
        else:
            import_payload = {
                "batch_name": f"Research Import — {target_region}",
                "source": "web_search",
                "target_region": target_region,
                "prospects": prospects,
            }
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        f"{api_base}/import",
                        headers={
                            "Authorization": f"Bearer {api_token}",
                            "Content-Type": "application/json",
                        },
                        json=import_payload,
                    )
                    if resp.status_code < 400:
                        result = resp.json()
                        import_summary = (
                            f"Imported {result.get('new_created', 0)} new prospects, "
                            f"skipped {result.get('duplicates_skipped', 0)} duplicates "
                            f"(submitted {result.get('total_submitted', len(prospects))}, "
                            f"batch {result.get('batch_id')})"
                        )
                        logger.info("Research run %s phase 3: %s", run_id, import_summary)
                    else:
                        import_summary = (
                            f"Import HTTP {resp.status_code}: {resp.text[:200]}"
                        )
                        logger.warning(
                            "Research run %s phase 3 failed: %s", run_id, import_summary,
                        )
            except Exception as exc:
                import_summary = f"Import request threw: {exc}"
                logger.warning(
                    "Research run %s phase 3 threw: %s", run_id, exc,
                )

        all_results.append(f"IMPORT: {import_summary}")

        summary = f"Research workflow complete.\n\n" + "\n\n".join(all_results)

        return {
            "summary": summary,
            "provider": provider,
            "model": model,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cost_usd": 0.0,
        }

    async def _execute_form_submit_workflow(
        self, run_id: str, ctx: AdapterExecutionContext,
        provider: str, model: str,
    ) -> dict[str, Any]:
        """Arianna-FormSubmit workflow: submit contact forms on prospects
        without a deliverable email address.

        Architecture follows the lesson from the research workflow refactor:
        mechanical work in code, creative work in the LLM, seam at the data
        boundary.

        Mechanical (pure Python, no LLM):
          - Query Odoo for eligible prospects (/form-candidates)
          - Navigate to each contact form via Playwright
          - Detect fields, fill, submit (or dry-run fill)
          - Log outcome back to Odoo (/mark-form-submitted)

        Creative (one narrow LLM call per prospect):
          - Generate a 2-3 sentence personalized message using the prospect's
            ai_personalization_context + city + company name

        DRY_RUN is controlled by the ARIANNA_FORM_SUBMIT_DRY_RUN env var.
        Defaults to TRUE so a fresh deploy can never accidentally submit
        real forms — you have to flip it off explicitly.
        """
        import os

        api_token = "3399cb9b2df4c5bfb7d1204d326cb64d04ffaf5314f7115a98a1ca9a7f7bd80f"
        api_base = "https://synergicsolar.com/api/v1/prospects"
        limit = int(os.environ.get("ARIANNA_FORM_SUBMIT_LIMIT", "5"))
        dry_run = os.environ.get(
            "ARIANNA_FORM_SUBMIT_DRY_RUN", "true",
        ).lower() not in ("false", "0", "no", "off")

        # Business-hours guard: reuse the email agent's Mon-Sat 7-9 ET window.
        # Form submissions are outbound contact and should follow the same
        # "don't contact people at 3 AM on Sunday" rule as emails.
        allowed, reason = self._is_within_business_hours("form_submit")
        if not allowed:
            logger.info("Skipping form-submit run %s: %s", run_id, reason)
            return {
                "summary": f"Skipped: {reason}",
                "provider": provider,
                "model": model,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
            }

        logger.info(
            "Form-submit run %s: limit=%d dry_run=%s", run_id, limit, dry_run,
        )

        # --- Phase 1: Fetch eligible candidates from Odoo ---
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{api_base}/form-candidates?limit={limit}",
                    headers={"Authorization": f"Bearer {api_token}"},
                )
                if resp.status_code >= 400:
                    return self._form_submit_abort(
                        run_id, provider, model,
                        f"form-candidates fetch failed: HTTP {resp.status_code} — {resp.text[:200]}",
                    )
                candidates = resp.json().get("prospects", [])
        except Exception as exc:
            return self._form_submit_abort(
                run_id, provider, model,
                f"form-candidates fetch threw: {exc}",
            )

        if not candidates:
            logger.info("Form-submit run %s: no eligible prospects, exiting cleanly", run_id)
            return {
                "summary": "No eligible prospects for form submission.",
                "provider": provider,
                "model": model,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
            }

        logger.info(
            "Form-submit run %s: %d candidates to process", run_id, len(candidates),
        )

        # --- Phase 2: For each candidate, personalize message + submit form ---
        from core.form_submitter import submit_contact_form

        # Import playwright lazily — the module may not be installed in every
        # frood deployment, and we don't want to break the orchestrator just
        # because form-submit isn't wired up yet.
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            return self._form_submit_abort(
                run_id, provider, model,
                f"playwright not installed: {exc}",
            )

        total_input = 0
        total_output = 0
        outcomes: dict[str, int] = {
            "success": 0,
            "submitted_unconfirmed": 0,
            "dry_run": 0,
            "captcha_blocked": 0,
            "no_form_detected": 0,
            "errored": 0,
        }
        details: list[str] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                for idx, prospect in enumerate(candidates):
                    prospect_id = prospect.get("id")
                    prospect_name = prospect.get("name", "?")
                    logger.info(
                        "Form-submit run %s: processing [%d/%d] %s (id=%s)",
                        run_id, idx + 1, len(candidates), prospect_name, prospect_id,
                    )

                    # 2a. LLM call — narrow creative task, no tool use
                    message_result = await self._generate_form_message(
                        provider, model, prospect, run_id,
                    )
                    total_input += message_result.get("input_tokens", 0)
                    total_output += message_result.get("output_tokens", 0)
                    message = (message_result.get("summary") or "").strip()

                    if not message:
                        logger.warning(
                            "Form-submit run %s: empty message for prospect %s — skipping",
                            run_id, prospect_id,
                        )
                        outcomes["errored"] += 1
                        await self._log_form_submission(
                            api_base, api_token, prospect_id,
                            {
                                "status": "errored",
                                "message_sent": "",
                                "evidence": "LLM produced empty message",
                            },
                            dry_run,
                        )
                        continue

                    # 2b. Playwright fill + submit (or dry-run)
                    prospect_with_message = {**prospect, "message": message}
                    try:
                        outcome = await submit_contact_form(
                            browser, prospect_with_message, dry_run=dry_run,
                        )
                    except Exception as exc:
                        logger.exception(
                            "Form-submit run %s: submit_contact_form threw for %s",
                            run_id, prospect_id,
                        )
                        outcome = {
                            "status": "errored",
                            "evidence": f"submit_contact_form exception: {exc}",
                            "message_sent": message,
                        }

                    outcome_status = outcome.get("status", "errored")

                    # Captcha-blocked = permanently queued for VA manual submission.
                    # Generate a proper outreach email so the VA can act immediately,
                    # then mark the prospect with human_follow_up (removes from queue).
                    if outcome_status == "captcha_blocked":
                        email_result = await self._generate_human_followup_email(
                            provider, model, prospect, run_id,
                        )
                        total_input += email_result.get("input_tokens", 0)
                        total_output += email_result.get("output_tokens", 0)
                        email_draft = (email_result.get("summary") or "").strip()
                        # Parse subject from first line if the model followed the format
                        lines = email_draft.splitlines()
                        draft_subject = ""
                        draft_body = email_draft
                        if lines and lines[0].lower().startswith("subject:"):
                            draft_subject = lines[0][8:].strip()
                            draft_body = "\n".join(lines[1:]).lstrip()
                        outcome = {
                            **outcome,
                            "status": "human_follow_up",
                            "draft_subject": draft_subject,
                            "draft_email": draft_body,
                        }
                        outcome_status = "human_follow_up"
                        logger.info(
                            "Form-submit run %s: prospect %s captcha-blocked → "
                            "queued for VA, email drafted",
                            run_id, prospect_id,
                        )

                    outcomes[outcome_status] = outcomes.get(outcome_status, 0) + 1
                    details.append(
                        f"[{idx + 1}] {prospect_name}: {outcome_status} "
                        f"— {outcome.get('evidence', '')[:120]}"
                    )

                    # 2c. Writeback to Odoo
                    await self._log_form_submission(
                        api_base, api_token, prospect_id, outcome, dry_run,
                    )
            finally:
                await browser.close()

        summary_lines = [
            f"Form-submit run complete. dry_run={dry_run}. Processed {len(candidates)} prospects.",
            "",
            "Outcomes: "
            + ", ".join(f"{k}={v}" for k, v in outcomes.items() if v > 0),
            "",
            *details,
        ]
        summary = "\n".join(summary_lines)

        logger.info(
            "Form-submit run %s complete: %s",
            run_id,
            ", ".join(f"{k}={v}" for k, v in outcomes.items() if v > 0),
        )

        return {
            "summary": summary,
            "provider": provider,
            "model": model,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cost_usd": 0.0,
        }

    def _form_submit_abort(
        self, run_id: str, provider: str, model: str, reason: str,
    ) -> dict[str, Any]:
        """Shared abort-with-log path for _execute_form_submit_workflow."""
        logger.warning("Form-submit run %s aborted: %s", run_id, reason)
        return {
            "summary": f"Form-submit aborted: {reason}",
            "provider": provider,
            "model": model,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "error": reason,
        }

    async def _generate_form_message(
        self,
        provider: str,
        model: str,
        prospect: dict,
        run_id: str,
    ) -> dict[str, Any]:
        """Generate a 2-3 sentence personalized contact-form message for one
        prospect. Narrow creative task, one LLM call, no tools.
        """
        prospect_name = prospect.get("name", "")
        city = prospect.get("city", "")
        state = prospect.get("state_code", "")
        context_hint = (prospect.get("ai_personalization_context") or "").strip()
        research_notes = (prospect.get("ai_research_notes") or "").strip()

        prompt = f"""You are Arianna Dar, Synergic Solar's dealer outreach specialist.
Write a short, friendly message to paste into {prospect_name}'s website contact form.

Company: {prospect_name}
Location: {city}, {state}
What we know about them: {research_notes or "(no research notes available)"}
Personalization hints: {context_hint or "(no hints — keep it generic but warm)"}

Rules:
- 2 to 3 sentences, 50 to 90 words total.
- Friendly and confident, not salesy. No emojis. No buzzwords.
- Mention Synergic Solar's dealer program and that independent dealers keep their own brand.
- End with: "Reply to arianna@synergicsolar.com if you'd like to learn more."
- Do NOT include a subject line, greeting, or signature — the form has separate fields for those. Just the message body.

Output the message text only. No preamble, no quotes, no markdown."""

        result = await self._call_provider(
            provider, model,
            [{"role": "user", "content": prompt}],
            f"{run_id}-formsubmit-msg-{prospect.get('id', 'x')}",
            agent_id="form_submit",
            task_type="form_submit",
            phase="generate_message",
        )
        return result

    async def _generate_human_followup_email(
        self,
        provider: str,
        model: str,
        prospect: dict,
        run_id: str,
    ) -> dict[str, Any]:
        """Generate a full outreach email for a VA to paste into a captcha-protected
        contact form. Returns subject + body so the VA can act immediately.
        """
        prospect_name = prospect.get("name", "")
        contact_name = prospect.get("contact_name", "") or "there"
        city = prospect.get("city", "")
        state = prospect.get("state_code", "")
        context_hint = (prospect.get("ai_personalization_context") or "").strip()
        research_notes = (prospect.get("ai_research_notes") or "").strip()

        prompt = f"""You are Arianna Dar, Synergic Solar's dealer outreach specialist.
Write a complete outreach email for a VA to paste into {prospect_name}'s contact form.
The form has captcha so our automation cannot submit it — a human will do it.

Company: {prospect_name}
Contact: {contact_name}
Location: {city}, {state}
Research notes: {research_notes or "(none)"}
Personalization hints: {context_hint or "(none)"}

Rules:
- Start with a subject line on the very first line, formatted as: Subject: <subject text>
- Then a blank line, then the email body.
- Body: 3-4 short paragraphs, professional but warm tone. No emojis. No buzzwords.
- Mention that independent solar dealers keep their own brand under Synergic's program.
- Include a call to action: reply to arianna@synergicsolar.com or visit synergicsolar.com/dealer
- Sign off as: Arianna Dar | Synergic Solar | arianna@synergicsolar.com

Output ONLY the subject line + email body. No preamble, no markdown, no quotes."""

        return await self._call_provider(
            provider, model,
            [{"role": "user", "content": prompt}],
            f"{run_id}-humanfollowup-{prospect.get('id', 'x')}",
            agent_id="form_submit",
            task_type="form_submit",
            phase="generate_message",
        )

    async def _log_form_submission(
        self,
        api_base: str,
        api_token: str,
        prospect_id: Any,
        outcome: dict,
        dry_run: bool,
    ) -> None:
        """POST the form-submit outcome to Odoo so it's captured in the
        prospect interaction table. Errors here are logged and swallowed —
        a failed writeback must not break the run loop.
        """
        payload = {
            "status": outcome.get("status", "errored"),
            "message_sent": outcome.get("message_sent", ""),
            "response_text": outcome.get("evidence", ""),
            "screenshot_path": (
                outcome.get("screenshot_post") or outcome.get("screenshot_pre") or ""
            ),
            "dry_run": dry_run,
        }
        # Pass through human_follow_up email draft if present
        if outcome.get("draft_subject"):
            payload["draft_subject"] = outcome["draft_subject"]
        if outcome.get("draft_email"):
            payload["draft_email"] = outcome["draft_email"]
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{api_base}/{prospect_id}/mark-form-submitted",
                    headers={
                        "Authorization": f"Bearer {api_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if resp.status_code >= 400:
                    logger.warning(
                        "mark-form-submitted returned HTTP %d for prospect %s: %s",
                        resp.status_code, prospect_id, resp.text[:200],
                    )
        except Exception as exc:
            logger.warning(
                "mark-form-submitted request threw for prospect %s: %s",
                prospect_id, exc,
            )

    # =====================================================================
    # Arianna-Email deterministic workflow
    # =====================================================================

    async def _execute_email_monitor_workflow(
        self, run_id: str, ctx: AdapterExecutionContext,
        provider: str, model: str,
    ) -> dict[str, Any]:
        """Arianna-Email workflow: inbox triage + nurture follow-ups.

        Replaces the previous LLM-driven tool loop which had two fatal
        failure modes (spam loop from iteration cap starving log-email
        calls, and the LLM silently dropping prospect_type on installer
        replies). All control flow is now Python; the LLM is used only
        for narrow body-generation tasks (1 call per outbound email).

        Phase 1: Fetch unread emails from IMAP (mark read immediately).
        Phase 2: For each reply — classify intent + prospect_type,
                 look up or create the prospect, draft a reply body
                 (1 LLM call), send, mark-responded, log both directions.
        Phase 3: Fetch nurture candidates.
        Phase 4: For each nurture — draft a personalized body (1 LLM call),
                 send, log the outbound interaction so the cooldown kicks in.
        """
        import os

        from core import email_monitor as em

        _bypass_biz_hours_email = os.environ.get(
            "ARIANNA_BYPASS_BUSINESS_HOURS", ""
        ).lower() in ("true", "1", "yes", "on")

        if ctx.wake_reason == "heartbeat" and not _bypass_biz_hours_email:
            allowed, reason = self._is_within_business_hours("email")
            if not allowed:
                logger.info("Skipping email run %s: %s", run_id, reason)
                return {
                    "summary": f"Skipped: {reason}",
                    "provider": provider, "model": model,
                    "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
                }

        imap_password = os.environ.get("ARIANNA_IMAP_AUTH", "")
        max_replies = int(os.environ.get("ARIANNA_EMAIL_REPLY_LIMIT", "10"))
        max_nurture = int(os.environ.get("ARIANNA_EMAIL_NURTURE_LIMIT", "5"))

        total_input = 0
        total_output = 0
        reply_stats: dict[str, int] = {
            "opt_out": 0, "negative": 0, "positive": 0, "neutral": 0,
            "new_senders": 0, "send_failures": 0,
        }
        nurture_stats = {"sent": 0, "failed": 0}
        reply_details: list[str] = []
        nurture_details: list[str] = []

        # ---------- Phase 1: Fetch unread emails ----------
        logger.info("Email run %s: fetching unread emails", run_id)
        unread = em.fetch_unread_emails(imap_password, max_count=max_replies)
        logger.info(
            "Email run %s: %d unread emails fetched (marked read)",
            run_id, len(unread),
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            # ---------- Phase 2: Handle each reply ----------
            for email_data in unread:
                sender_email = email_data["sender_email"]
                sender_name = email_data["sender_name"]
                subject = email_data["subject"]
                body_text = email_data["body_text"]

                if em._is_system_sender(sender_email):
                    logger.info(
                        "Email run %s: skipping system sender %s",
                        run_id, sender_email,
                    )
                    continue

                intent = em.classify_intent(subject, body_text)
                prospect_type = em.classify_prospect_type(subject, body_text)
                reply_stats[intent] = reply_stats.get(intent, 0) + 1

                # Look up or create the prospect
                match = await em.check_duplicate(client, sender_email, sender_name)
                if match and match.get("prospect_id"):
                    prospect_id = match["prospect_id"]
                else:
                    prospect_id = await em.import_new_prospect(
                        client, sender_email, sender_name,
                    )
                    if prospect_id:
                        reply_stats["new_senders"] += 1

                if not prospect_id:
                    reply_details.append(
                        f"[reply] {sender_email}: failed to resolve prospect — skipped"
                    )
                    continue

                # mark-responded only for actionable (non opt-out / non negative) intents
                assigned_dealer = None
                dealer_referral_code = None
                if intent in ("positive", "neutral"):
                    mark_resp = await em.mark_responded(
                        client, prospect_id,
                        {
                            "email_subject": subject,
                            "email_body": body_text[:4000],
                            "sentiment": "positive" if intent == "positive" else "neutral",
                            "contact_name": sender_name or "",
                            "prospect_type": prospect_type,
                            "source_tag": "Arianna Business Development",
                        },
                    )
                    if mark_resp:
                        assigned_dealer = mark_resp.get("assigned_dealer") or mark_resp.get("assigned_to")
                        dealer_referral_code = mark_resp.get("dealer_referral_code") or ""

                # Draft the reply body (1 LLM call)
                reply_prompt = em.build_reply_prompt(
                    email_data, intent, prospect_type,
                    assigned_dealer=assigned_dealer,
                    dealer_referral_code=dealer_referral_code,
                )
                llm_resp = await self._call_provider(
                    provider, model,
                    [{"role": "user", "content": reply_prompt}],
                    f"{run_id}-emailreply-{prospect_id}",
                    agent_id="email", task_type="email",
                    phase="generate_reply",
                )
                total_input += llm_resp.get("input_tokens", 0)
                total_output += llm_resp.get("output_tokens", 0)
                body_plain = (llm_resp.get("summary") or "").strip()

                if not body_plain:
                    reply_details.append(
                        f"[reply] {sender_email}: LLM returned empty body — skipped send"
                    )
                    reply_stats["send_failures"] += 1
                    continue

                reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
                body_html = em.wrap_body_with_signature(em.plain_text_to_html(body_plain))

                ok, detail = await em.send_outbound_email(
                    sender_email, reply_subject, body_html,
                )
                if not ok:
                    reply_details.append(
                        f"[reply] {sender_email}: send_email failed — {detail[:120]}"
                    )
                    reply_stats["send_failures"] += 1
                    continue

                # Log inbound (original reply) + outbound (our response)
                await em.log_email_to_crm(
                    client, prospect_id, {
                        "direction": "inbound",
                        "sender_name": sender_name or sender_email,
                        "sender_email": sender_email,
                        "subject": subject,
                        "body_text": body_text[:4000],
                    },
                )
                await em.log_email_to_crm(
                    client, prospect_id, {
                        "direction": "outbound",
                        "sender_name": "Arianna Dar",
                        "sender_email": "arianna@synergicsolar.com",
                        "recipient_email": sender_email,
                        "subject": reply_subject,
                        "body_html": body_html,
                    },
                )

                reply_details.append(
                    f"[reply] {sender_email} ({intent}/{prospect_type}) → sent"
                )

            # ---------- Phase 3+4: Nurture candidates ----------
            logger.info("Email run %s: fetching nurture candidates", run_id)
            candidates = await em.fetch_nurture_candidates(client, max_nurture)
            logger.info(
                "Email run %s: %d nurture candidates", run_id, len(candidates),
            )

            for candidate in candidates:
                prospect_id = candidate.get("id")
                recipient = (candidate.get("email") or "").strip()
                if not prospect_id or not recipient:
                    continue

                prompt = em.build_nurture_prompt(candidate)
                llm_resp = await self._call_provider(
                    provider, model,
                    [{"role": "user", "content": prompt}],
                    f"{run_id}-nurture-{prospect_id}",
                    agent_id="email", task_type="email",
                    phase="generate_nurture",
                )
                total_input += llm_resp.get("input_tokens", 0)
                total_output += llm_resp.get("output_tokens", 0)
                body_plain = (llm_resp.get("summary") or "").strip()

                if not body_plain:
                    nurture_stats["failed"] += 1
                    nurture_details.append(
                        f"[nurture] {recipient}: LLM returned empty body"
                    )
                    continue

                last_subject = (candidate.get("last_outbound_subject") or "").strip()
                subject = f"Re: {last_subject}" if last_subject else "Following up on the Synergic dealer program"
                body_html = em.wrap_body_with_signature(em.plain_text_to_html(body_plain))

                ok, detail = await em.send_outbound_email(
                    recipient, subject, body_html,
                )
                if not ok:
                    nurture_stats["failed"] += 1
                    nurture_details.append(
                        f"[nurture] {recipient}: send_email failed — {detail[:120]}"
                    )
                    continue

                # Log outbound — bumps outreach_step on the prospect so the
                # cooldown filter excludes them from the next batch.
                logged = await em.log_email_to_crm(
                    client, prospect_id, {
                        "direction": "outbound",
                        "sender_name": "Arianna Dar",
                        "sender_email": "arianna@synergicsolar.com",
                        "recipient_email": recipient,
                        "subject": subject,
                        "body_html": body_html,
                    },
                )
                nurture_stats["sent"] += 1
                nurture_details.append(
                    f"[nurture] {recipient}: sent"
                    + ("" if logged else " (WARNING: log-email failed)")
                )

        # ---------- Phase 5: Build summary ----------
        summary_parts = [
            "## Arianna Email Monitor — Deterministic Workflow",
            "",
            f"**Inbox:** {len(unread)} unread emails fetched",
        ]
        if unread:
            summary_parts.append(
                "- Intent breakdown: "
                + ", ".join(
                    f"{k}={v}" for k, v in reply_stats.items() if v > 0
                )
            )
        summary_parts.extend([
            "",
            f"**Nurture:** {nurture_stats['sent']} sent, {nurture_stats['failed']} failed",
        ])
        if reply_details:
            summary_parts.extend(["", "### Reply handling"] + reply_details)
        if nurture_details:
            summary_parts.extend(["", "### Nurture follow-ups"] + nurture_details)

        summary = "\n".join(summary_parts)

        logger.info(
            "Email run %s complete: replies=%d nurture_sent=%d nurture_failed=%d",
            run_id, len(unread), nurture_stats["sent"], nurture_stats["failed"],
        )

        return {
            "summary": summary,
            "provider": provider,
            "model": model,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cost_usd": 0.0,
        }

    # Business hours configuration (US Eastern)
    # Email + form-submit tasks only run Mon-Sat, 7 AM - 9 PM ET.
    # Same rationale: these are outbound contact to real people, and it's
    # inappropriate to contact a prospect at 3 AM on Sunday regardless of
    # whether the channel is email or a website contact form.
    _BUSINESS_HOURS = {
        "email": {"days": (0, 1, 2, 3, 4, 5), "start_hour": 7, "end_hour": 21, "tz": "US/Eastern"},
        "form_submit": {"days": (0, 1, 2, 3, 4, 5), "start_hour": 7, "end_hour": 21, "tz": "US/Eastern"},
    }

    def _is_within_business_hours(self, task_type: str) -> tuple[bool, str]:
        """Check if the current time is within business hours for the task type.

        Returns (allowed, reason). Tasks without business hour config are always allowed.

        Per-task override env var: set
        `FROOD_IGNORE_BUSINESS_HOURS_<TASK_TYPE_UPPER>=true` to bypass the
        check for one task type. Targeted at smoke-testing new agents
        outside their normal window — a global override would be too easy
        to leave on and accidentally fire email runs at 3 AM Sunday.
        """
        import os

        override_var = f"FROOD_IGNORE_BUSINESS_HOURS_{task_type.upper()}"
        if os.environ.get(override_var, "").lower() in ("true", "1", "yes", "on"):
            return True, ""

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
            return False, f"Outside business days ({day_name}). {task_type} runs Mon-Sat only."

        if hour < config["start_hour"] or hour >= config["end_hour"]:
            return False, f"Outside business hours ({hour}:00 ET). {task_type} runs {config['start_hour']}AM-{config['end_hour'] - 12}PM ET."

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

        # Business hours guard — skip email tasks outside Mon-Sat 7AM-9PM ET.
        # Bypassed for non-heartbeat wake reasons (manual triggers,
        # task_assigned dispatches) — if someone is explicitly running the
        # agent, they want it to run now regardless of the clock.
        # Also bypassable globally via ARIANNA_BYPASS_BUSINESS_HOURS=true
        # for operator testing / debugging (Paperclip's "Run Heartbeat"
        # button sends wakeReason=heartbeat, so the wake-reason check
        # doesn't help for UI-initiated manual runs).
        import os as _os_bh
        _bypass_biz_hours = _os_bh.environ.get(
            "ARIANNA_BYPASS_BUSINESS_HOURS", ""
        ).lower() in ("true", "1", "yes", "on")

        if ctx.wake_reason == "heartbeat" and not _bypass_biz_hours:
            allowed, reason = self._is_within_business_hours(task_type)
            if not allowed:
                logger.info(
                    "Skipping run %s (heartbeat outside hours): %s",
                    run_id, reason,
                )
                # Surface the configured provider/model so the caller can
                # see the config even on skipped cycles.
                configured_provider = (
                    ctx.adapter_config.preferred_provider
                    or ctx.context.get("provider", "")
                    or ""
                )
                configured_model = (
                    ctx.context.get("model", "")
                    or ctx.context.get("modelOverride", "")
                    or ""
                )
                return {
                    "summary": f"Skipped: {reason}",
                    "output": f"Skipped: {reason}",
                    "provider": configured_provider,
                    "model": configured_model,
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
        # Paperclip's live adapter (dist/server/execute.js) does NOT send an
        # adapterConfig block — it forwards adapter fields via the context
        # dict instead. Read provider from context.provider as a fallback
        # (the canonical adapter_config.preferred_provider path is kept for
        # the TS reference adapter in adapters/frood-paperclip/).
        routing = None
        if self.tiered_routing_bridge and ctx.agent_id:
            try:
                route_preferred_provider = (
                    ctx.adapter_config.preferred_provider
                    or ctx.context.get("provider", "")
                    or ""
                )
                route_preferred_model = (
                    ctx.context.get("model", "")
                    or ctx.context.get("modelOverride", "")
                    or ""
                )
                routing = await self.tiered_routing_bridge.resolve(
                    role=ctx.context.get("agentRole", ""),
                    agent_id=ctx.agent_id,
                    preferred_provider=route_preferred_provider,
                    preferred_model=route_preferred_model,
                    task_type=ctx.task_type or ctx.context.get("taskType", ""),
                )
                logger.info(
                    "Routing run %s: provider=%s model=%s "
                    "(preferred_provider=%r preferred_model=%r)",
                    run_id, routing.provider, routing.model,
                    route_preferred_provider, route_preferred_model,
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

        # Detect form-submit tasks (Arianna-FormSubmit) — deterministic
        # Playwright-based form filler with one LLM call per prospect for
        # message personalization.
        is_form_submit = (
            effective_task_type == "form_submit"
            or ctx.context.get("agentRole") == "form_submitter"
            or "form submit" in (ctx.task or "").lower()[:200]
        )

        # Detect email monitor tasks (Arianna-Email) — deterministic
        # IMAP + Odoo API workflow with narrow LLM calls for body drafting.
        # Matches on explicit task_type OR agent role OR task prompt wording.
        task_text = (ctx.task or "").lower()[:300]
        is_email_monitor = (
            effective_task_type == "email"
            or ctx.context.get("agentRole") == "email_monitor"
            or "email monitor" in task_text
            or "arianna-email" in task_text
            or "arianna email" in task_text
            or "inbox triage" in task_text
            or "nurture follow" in task_text
        )

        if is_research:
            logger.info("Run %s: using multi-phase research workflow", run_id)
            result = await self._execute_research_workflow(
                run_id, ctx, provider_name, model_name,
            )
        elif is_form_submit:
            logger.info("Run %s: using form-submit workflow", run_id)
            result = await self._execute_form_submit_workflow(
                run_id, ctx, provider_name, model_name,
            )
        elif is_email_monitor:
            logger.info("Run %s: using email-monitor workflow", run_id)
            result = await self._execute_email_monitor_workflow(
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
        "email": {"send_email", "python_exec", "http_request"},
        "coding": {"python_exec", "git", "run_tests", "run_linter", "code_intel"},
        "monitoring": {"python_exec", "http_request"},
        # form_submit's only LLM call is _generate_form_message which
        # produces a short text response with no tool use. Exposing the
        # full 34-tool catalog was wasting ~6800 input tokens per call
        # on unused schemas. Empty set = no tools in the payload.
        "form_submit": set(),
    }

    # Per-phase tool whitelists for the research workflow (override the task whitelist)
    _RESEARCH_PHASE_TOOLS: dict[str, set[str]] = {
        "search": {"web_search"},                   # SEARCH phase: ONLY search
        "fetch":  {"web_fetch", "http_request"},    # FETCH phase: web_fetch (text) + http_request (raw HTML for mailto:)
        "import": {"http_request"},                 # IMPORT phase: ONLY http_request (call APIs)
    }

    # Max tool-call iterations per task type (default 25 for uncategorized)
    # email: 1 IMAP check + 1 follow-up-candidates + 5 sends + 5 log-email
    #        + 2 buffer for inbound reply handling (check-duplicates,
    #        mark-responded) = 14. Set to 18 for extra headroom; any lower
    #        and the last 1-2 log-email calls get dropped, causing nurture
    #        dedup to miss those prospects and triggering a spam loop.
    _TASK_MAX_ITERATIONS: dict[str, int] = {
        "research": 15,
        "email": 18,
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

        # Distinguish "no entry in whitelist dict" (None → allow all tools)
        # from "empty set" (→ allow no tools, e.g. for form_submit's
        # message-generation call which should be pure text).
        if whitelist == set():
            return []

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

    @staticmethod
    def _extract_message_content(msg: dict) -> str:
        """Extract textual content from an LLM response message.

        Prefers `content`, but falls back to `reasoning_content` for reasoning
        models (e.g. nvidia/llama-3.3-nemotron-super-49b-v1.5) that return
        `content: null` with the actual output buried in `reasoning_content`.
        Returns an empty string if neither is present.
        """
        content = msg.get("content")
        if content:
            return content
        reasoning = msg.get("reasoning_content") or msg.get("reasoning")
        return reasoning or ""

    @staticmethod
    def _parse_json_array(text: str) -> list[dict]:
        """Extract the first JSON array-of-objects from a text blob.

        LLM outputs for the research FETCH phase are typically a JSON array
        of company dicts, but models often wrap the array in markdown code
        fences (```json ... ```) or prefix it with explanatory prose. This
        helper is tolerant of those cases so the deterministic import phase
        doesn't need the LLM to produce perfectly clean output.

        Returns [] on any parse failure — caller must handle the empty case.
        """
        import json as _json
        import re

        if not text:
            return []

        # Prefer a JSON array inside a fenced code block when present.
        fence_match = re.search(
            r"```(?:json)?\s*(\[.*?\])\s*```",
            text,
            re.DOTALL,
        )
        if fence_match:
            candidate = fence_match.group(1)
        else:
            # Otherwise, take the substring between the first '[' and the
            # last ']'. This assumes the array is the dominant payload.
            start = text.find("[")
            end = text.rfind("]")
            if start == -1 or end == -1 or end < start:
                return []
            candidate = text[start : end + 1]

        try:
            data = _json.loads(candidate)
        except _json.JSONDecodeError:
            return []

        if not isinstance(data, list):
            return []
        # Only keep dict entries — ignores stray strings/numbers from a
        # malformed array.
        return [x for x in data if isinstance(x, dict)]

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
        # NVIDIA fallbacks — ordered best-to-worst for agentic/tool-use tasks.
        # minimaxai/minimax-m2.7 is the primary NVIDIA fallback: strong tool-use,
        # self-learning architecture, confirmed available on NVIDIA NIM.
        # minimaxai/minimax-m2.5 is the same family, also on NIM, as secondary.
        # meta/llama-3.1-70b-instruct handles simple tool use but gives up
        # early on multi-phase research salvage.
        # llama-3.3-nemotron-super-49b-v1.5 is reasoning-mode (content=null,
        # output in reasoning_content) — the _extract_message_content helper
        # handles that shape, but the model hallucinates when it should call
        # tools mid-workflow, so keep it as last-resort backup.
        attempts.append(("nvidia", "minimaxai/minimax-m2.7"))
        attempts.append(("nvidia", "minimaxai/minimax-m2.5"))
        attempts.append(("nvidia", "meta/llama-3.1-70b-instruct"))
        attempts.append(("nvidia", "nvidia/llama-3.3-nemotron-super-49b-v1.5"))
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
                            # 8192 headroom — reasoning models (e.g. NVIDIA
                            # llama-3.3-nemotron-super-49b) can burn hundreds
                            # to thousands of tokens on reasoning_content
                            # before emitting the final answer. Non-reasoning
                            # models pay only for what they actually generate.
                            "max_tokens": 8192,
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
                                    str(tool_args)[:400],
                                )

                                tool_result = await self._execute_tool_call(
                                    tool_name, tool_args, agent_id,
                                )

                                # DEBUG-level — enable on demand when diagnosing
                                # LLMs that generate malformed tool_call arguments.
                                logger.debug(
                                    "Run %s tool result [%d]: %s",
                                    run_id, iteration,
                                    str(tool_result)[:400],
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

                        # Model returned text (no tool calls) — we're done.
                        # Use _extract_message_content so reasoning models
                        # (content=null, answer in reasoning_content) are
                        # handled the same as normal models.
                        content = self._extract_message_content(msg)
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
                            "max_tokens": 8192,  # headroom for reasoning models
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
                                final_msg = final_choices[0].get("message", {})
                                final_content = self._extract_message_content(final_msg)
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
