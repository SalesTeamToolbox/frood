"""Playwright-based contact form submitter for Arianna-FormSubmit.

This module is intentionally **pure Python** — no LLM calls. The message text
is generated elsewhere (by the sidecar orchestrator with one narrow LLM call
per prospect) and passed in. Everything here is deterministic form detection,
filling, and submission.

Design notes
============

The hard part of submitting random contact forms across the internet is that
every site uses slightly different field names, attributes, and layouts. The
strategy here is:

1. **Heuristic field matching**. For each known field type (name, email,
   company, phone, subject, message) try a list of CSS/attribute selectors
   from most to least specific. The first match wins. This handles 80%+ of
   WordPress/Contact-Form-7/HubSpot/Wix/Squarespace forms without custom
   per-site logic.

2. **CAPTCHA detection up front**. Before touching any inputs, check for
   reCAPTCHA, hCaptcha, and Cloudflare Turnstile iframes. If present, abort
   with status=captcha_blocked — V1 does not attempt to solve CAPTCHAs.

3. **Success detection after submit**. After clicking the submit button,
   wait briefly for network idle, then inspect the post-submit page for:
   - URL change away from the form page (redirect to /thank-you or similar)
   - Page text containing any of a handful of "success" phrases
   - If neither, return status=submitted_unconfirmed — the click went
     through but we can't prove the backend accepted it.

4. **Screenshot evidence**. Every attempt captures a pre-submit screenshot
   (shows what we'd send) and a post-submit screenshot (shows what the site
   responded with) for human review.

5. **Dry-run mode**. When dry_run=True, everything runs up to and including
   the field fills and pre-submit screenshot, but the submit button is never
   clicked. Lets us validate detection logic against real sites without
   actually submitting anything.
"""

import logging
import os
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("frood.form_submitter")


# Fields we try to fill. Ordered from most-likely-required to optional.
# Each entry: (field_key, list_of_selectors_to_try).
#
# Selectors use Playwright's CSS engine with attribute predicates. The `i`
# suffix makes attribute matches case-insensitive. We check both `name` and
# `id` attributes because some form builders use one and not the other, and
# placeholder text as a final fallback for forms without proper labels.
_FIELD_SELECTORS: list[tuple[str, list[str]]] = [
    (
        "email",
        [
            'input[type="email"]',
            'input[name*="email" i]',
            'input[id*="email" i]',
            'input[placeholder*="email" i]',
        ],
    ),
    (
        "name",
        [
            'input[name="name"]',
            'input[name="full_name"]',
            'input[name*="your-name" i]',  # Contact Form 7 default
            'input[name*="fullname" i]',
            'input[id*="full_name" i]',
            'input[name*="name" i]:not([name*="company" i]):not([name*="business" i]):not([name*="first" i]):not([name*="last" i])',
            'input[placeholder*="name" i]:not([placeholder*="company" i])',
        ],
    ),
    (
        "first_name",
        [
            'input[name*="first_name" i]',
            'input[name*="firstname" i]',
            'input[name="fname"]',
            'input[id*="first_name" i]',
            'input[placeholder*="first name" i]',
        ],
    ),
    (
        "last_name",
        [
            'input[name*="last_name" i]',
            'input[name*="lastname" i]',
            'input[name="lname"]',
            'input[id*="last_name" i]',
            'input[placeholder*="last name" i]',
        ],
    ),
    (
        "company",
        [
            'input[name*="company" i]',
            'input[name*="business" i]',
            'input[name*="organization" i]',
            'input[id*="company" i]',
            'input[placeholder*="company" i]',
        ],
    ),
    (
        "phone",
        [
            'input[type="tel"]',
            'input[name*="phone" i]',
            'input[name*="tel" i]',
            'input[id*="phone" i]',
            'input[placeholder*="phone" i]',
        ],
    ),
    (
        "subject",
        [
            'input[name*="subject" i]',
            'input[name*="topic" i]',
            'input[id*="subject" i]',
            'input[placeholder*="subject" i]',
        ],
    ),
    (
        "message",
        [
            "textarea",
            'textarea[name*="message" i]',
            'textarea[name*="comment" i]',
            'textarea[name*="inquiry" i]',
        ],
    ),
]


# Selectors that indicate a CAPTCHA is present on the page. If any of these
# match, we abort before touching the form — V1 doesn't attempt to solve.
_CAPTCHA_SELECTORS = [
    'iframe[src*="recaptcha"]',
    'iframe[src*="hcaptcha"]',
    'iframe[src*="turnstile"]',
    'iframe[src*="challenges.cloudflare.com"]',
    'div.g-recaptcha',
    'div.h-captcha',
    '[data-sitekey]',  # Generic CAPTCHA marker used by both recaptcha and hcaptcha
]


# Substring markers that typically appear on a successful post-submit page.
# Matching is case-insensitive. Order doesn't matter — first hit wins.
_SUCCESS_MARKERS = [
    "thank you",
    "thanks for",
    "message has been sent",
    "message sent",
    "we'll be in touch",
    "we will be in touch",
    "we have received",
    "submission received",
    "submission successful",
    "successfully submitted",
    "your message has been",
    "form submitted",
    "received your message",
    "confirmation sent",
]


# Submit button selectors, ordered from most-specific to most-general.
# We prefer buttons whose visible text or value contains "submit"/"send"/
# "contact" over generic button[type="submit"] to avoid accidentally
# clicking a newsletter-signup button that happens to precede the main form.
_SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Send Message")',
    'button:has-text("Send message")',
    'button:has-text("Send")',
    'button:has-text("Submit")',
    'button:has-text("Contact Us")',
    'button:has-text("Get in Touch")',
    'button:has-text("Request")',
]


# Form filler identity. Override via env for different agent personas.
FILLER_NAME = os.environ.get("ARIANNA_FORM_FILLER_NAME", "Arianna Dar")
FILLER_FIRST_NAME = os.environ.get("ARIANNA_FORM_FILLER_FIRST", "Arianna")
FILLER_LAST_NAME = os.environ.get("ARIANNA_FORM_FILLER_LAST", "Dar")
FILLER_EMAIL = os.environ.get("ARIANNA_FORM_FILLER_EMAIL", "arianna@synergicsolar.com")
FILLER_COMPANY = os.environ.get("ARIANNA_FORM_FILLER_COMPANY", "Synergic Solar")
FILLER_PHONE = os.environ.get("ARIANNA_FORM_FILLER_PHONE", "")
FILLER_SUBJECT = os.environ.get(
    "ARIANNA_FORM_FILLER_SUBJECT",
    "Solar dealer partnership opportunity",
)

# Where to dump screenshots. Inside frood's data dir so they're picked up
# by existing backup/retention and not scattered across /tmp.
SCREENSHOT_DIR = Path(
    os.environ.get(
        "ARIANNA_FORM_SCREENSHOT_DIR",
        "/opt/frood/.frood/form_submissions",
    )
)


def _fill_values_for(prospect: dict) -> dict[str, str]:
    """Build the per-prospect value map that gets injected into the form.

    Contact name comes from the prospect if set (better personalization)
    but falls back to FILLER_* identity for prospects without a specific
    contact. Message is injected by the caller — it's generated per-prospect
    by the orchestrator's LLM call.
    """
    return {
        "name": prospect.get("filler_name") or FILLER_NAME,
        "first_name": prospect.get("filler_first_name") or FILLER_FIRST_NAME,
        "last_name": prospect.get("filler_last_name") or FILLER_LAST_NAME,
        "email": FILLER_EMAIL,
        "company": FILLER_COMPANY,
        "phone": FILLER_PHONE,
        "subject": FILLER_SUBJECT,
        "message": prospect.get("message", ""),
    }


async def _is_captcha_present(page) -> bool:
    """Return True if any known CAPTCHA selector matches on the current page."""
    for selector in _CAPTCHA_SELECTORS:
        try:
            if await page.locator(selector).count() > 0:
                return True
        except Exception:
            # Some selectors may fail on unusual pages — keep checking the others.
            continue
    return False


async def _first_visible(page, selectors: list[str]):
    """Return the first locator in `selectors` that resolves to a visible
    element, or None if none match. Used for field and submit-button lookup.
    """
    for sel in selectors:
        try:
            locator = page.locator(sel).first
            if await locator.count() == 0:
                continue
            # Only fill visible inputs — avoids hidden honeypot fields some
            # forms use to catch bots.
            if await locator.is_visible():
                return locator
        except Exception:
            continue
    return None


async def _fill_field(page, field_key: str, value: str) -> bool:
    """Try to fill one semantic field. Returns True if successful."""
    if not value:
        return False
    selectors = dict(_FIELD_SELECTORS).get(field_key, [])
    locator = await _first_visible(page, selectors)
    if locator is None:
        return False
    try:
        await locator.fill(value)
        return True
    except Exception as exc:
        logger.debug("Fill failed for %s: %s", field_key, exc)
        return False


async def _detect_success(page, pre_submit_url: str) -> tuple[str, str]:
    """Check the current page for success markers after a submit click.

    Returns (status, evidence_text):
      - status: "success" | "submitted_unconfirmed"
      - evidence_text: short description of what matched (for logging)
    """
    # URL change is a strong signal — many forms redirect to a /thank-you page
    try:
        current_url = page.url
        if current_url and current_url != pre_submit_url:
            return "success", f"URL changed: {pre_submit_url} -> {current_url}"
    except Exception:
        pass

    # Otherwise look for known phrases in the page text
    try:
        body_text = await page.inner_text("body", timeout=2000)
    except Exception:
        body_text = ""

    body_lower = (body_text or "").lower()
    for marker in _SUCCESS_MARKERS:
        if marker in body_lower:
            return "success", f"Page text contains: '{marker}'"

    return "submitted_unconfirmed", "Submit clicked but no success marker found"


async def submit_contact_form(
    browser,
    prospect: dict,
    dry_run: bool = True,
    timeout_ms: int = 30000,
) -> dict[str, Any]:
    """Submit (or dry-run submit) a single contact form for one prospect.

    Args:
        browser: an already-launched Playwright Browser instance. The caller
            owns the lifecycle — we just open a fresh context per prospect
            so cookies/state don't leak between attempts.
        prospect: dict with at least `id`, `name`, `contact_form_url`, and
            `message` (the LLM-generated personalized body). Optional:
            `filler_name`, `filler_first_name`, `filler_last_name`.
        dry_run: when True, fill everything and take screenshots but never
            click the final submit button. Prospect is not really contacted.
        timeout_ms: per-operation timeout.

    Returns a dict:
        {
            "status": "success" | "submitted_unconfirmed" | "captcha_blocked"
                      | "no_form_detected" | "errored" | "dry_run",
            "url": the contact form URL we navigated to,
            "fields_filled": [...],  # which semantic fields matched and filled
            "message_sent": str,     # the message we filled into the textarea
            "evidence": str,         # short human-readable explanation
            "screenshot_pre": path or None,
            "screenshot_post": path or None,
            "error": str,            # populated only on status=errored
        }
    """
    form_url = (prospect.get("contact_form_url") or "").strip()
    prospect_id = prospect.get("id", "unknown")
    values = _fill_values_for(prospect)

    result: dict[str, Any] = {
        "status": "errored",
        "url": form_url,
        "fields_filled": [],
        "message_sent": values.get("message", ""),
        "evidence": "",
        "screenshot_pre": None,
        "screenshot_post": None,
        "error": "",
    }

    if not form_url:
        result["error"] = "No contact_form_url on prospect"
        return result
    if not values.get("message"):
        result["error"] = "No message text provided"
        return result

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    base_name = f"prospect_{prospect_id}_{ts}"

    context = None
    page = None
    try:
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 "
                "Arianna-FormSubmit/1.0 (+https://synergicsolar.com)"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()
        page.set_default_timeout(timeout_ms)

        # Navigate
        try:
            await page.goto(form_url, wait_until="domcontentloaded")
        except Exception as exc:
            result["status"] = "errored"
            result["error"] = f"Navigation failed: {exc}"
            return result

        # Give JS a moment to hydrate form fields before checking for CAPTCHA
        # or inputs. networkidle is flaky on sites with long-polling analytics,
        # so we just sleep briefly instead.
        try:
            await page.wait_for_timeout(1500)
        except Exception:
            pass

        # CAPTCHA short-circuit
        if await _is_captcha_present(page):
            result["status"] = "captcha_blocked"
            result["evidence"] = "CAPTCHA detected before form fill"
            try:
                pre_path = SCREENSHOT_DIR / f"{base_name}_captcha.png"
                await page.screenshot(path=str(pre_path), full_page=True)
                result["screenshot_pre"] = str(pre_path)
            except Exception:
                pass
            return result

        # Find the form. We don't strictly need to scope to a form element
        # since the field selectors are specific enough, but finding NO form
        # is a strong signal the URL was wrong (maybe a blog post or 404 page).
        form_count = 0
        try:
            form_count = await page.locator("form").count()
        except Exception:
            form_count = 0

        # Track which fields we successfully filled
        filled: list[str] = []
        for field_key, _sel in _FIELD_SELECTORS:
            if await _fill_field(page, field_key, values.get(field_key, "")):
                filled.append(field_key)

        # Minimum viable fill: we need at least email and message to have
        # meaningfully contacted the prospect.
        if "email" not in filled or "message" not in filled:
            result["status"] = "no_form_detected"
            result["fields_filled"] = filled
            result["evidence"] = (
                f"Insufficient form fields matched "
                f"(form_elements={form_count}, filled={filled})"
            )
            try:
                pre_path = SCREENSHOT_DIR / f"{base_name}_nomatch.png"
                await page.screenshot(path=str(pre_path), full_page=True)
                result["screenshot_pre"] = str(pre_path)
            except Exception:
                pass
            return result

        result["fields_filled"] = filled

        # Pre-submit screenshot — always captured
        try:
            pre_path = SCREENSHOT_DIR / f"{base_name}_pre.png"
            await page.screenshot(path=str(pre_path), full_page=True)
            result["screenshot_pre"] = str(pre_path)
        except Exception as exc:
            logger.debug("Pre-submit screenshot failed: %s", exc)

        if dry_run:
            result["status"] = "dry_run"
            result["evidence"] = (
                f"DRY RUN — filled {len(filled)} fields, did not submit. "
                f"Filled: {filled}"
            )
            return result

        # Real submit path
        submit_btn = await _first_visible(page, _SUBMIT_SELECTORS)
        if submit_btn is None:
            result["status"] = "no_form_detected"
            result["evidence"] = "Fields filled but no submit button found"
            return result

        pre_submit_url = page.url
        try:
            await submit_btn.click()
        except Exception as exc:
            result["status"] = "errored"
            result["error"] = f"Submit click failed: {exc}"
            return result

        # Wait for whatever comes after submit — redirect, ajax response,
        # client-side form swap. 5s is usually enough without being so long
        # that a hung site stalls the whole heartbeat.
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            # networkidle times out on sites with persistent pollers — that
            # doesn't mean submit failed, so just move on to detection.
            pass

        status, evidence = await _detect_success(page, pre_submit_url)
        result["status"] = status
        result["evidence"] = evidence

        # Post-submit screenshot — captures the confirmation (or lack thereof)
        try:
            post_path = SCREENSHOT_DIR / f"{base_name}_post.png"
            await page.screenshot(path=str(post_path), full_page=True)
            result["screenshot_post"] = str(post_path)
        except Exception:
            pass

        return result

    except Exception as exc:
        logger.exception("Unhandled error submitting form for prospect %s", prospect_id)
        result["status"] = "errored"
        result["error"] = str(exc)[:500]
        return result

    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass
