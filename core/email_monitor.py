"""Arianna-Email deterministic workflow.

Replaces the LLM-driven tool-call loop for the email monitor agent. The
only LLM involvement is narrow body generation per outbound email:

  - 1 call per inbound reply to draft a warm response
  - 1 call per nurture candidate to personalize the follow-up body

Everything else (IMAP fetch, sender parsing, sentiment/opt-out detection,
prospect_type classification, Odoo API calls, send_email, log-email)
is pure Python.

Why this exists
---------------
The previous LLM-driven email loop had two fatal failure modes:

  1. The model would burn 8+ iterations on python_exec retries for the
     IMAP fetch, then run out of turns before completing log-email calls.
     Unlogged sends left prospects in the nurture candidate pool, which
     re-picked them every 30 minutes → spam loop. TJ Embler received ~20
     duplicate emails in 24 hours before we diagnosed the cause.

  2. The model silently dropped non-required tool-call fields — we saw
     it skip `prospect_type` on installer replies even though TJ
     explicitly wrote "we are a full in house EPC installer" and the
     AGENTS.md flow described the field.

Both classes of bug vanish when control flow is in Python. The LLM's
creative work (write a good email body) stays in the LLM. Mechanical
work is mechanical.
"""

from __future__ import annotations

import asyncio
import datetime
import email
import imaplib
import json
import logging
import os
import re
from email.header import decode_header
from typing import Any

import httpx

logger = logging.getLogger("frood.sidecar.email_monitor")


# =========================================================================
# Configuration
# =========================================================================

_ODOO_API_BASE = "https://synergicsolar.com/api/v1/prospects"
_ODOO_API_TOKEN = (
    "3399cb9b2df4c5bfb7d1204d326cb64d04ffaf5314f7115a98a1ca9a7f7bd80f"
)
_IMAP_HOST = "webmail.synergicsolar.com"
_IMAP_PORT = 993
_IMAP_USER = "arianna@synergicsolar.com"

_ARIANNA_SIGNATURE_HTML = (
    '<br><p style="color: #666; font-size: 13px;">&mdash;<br>'
    '<strong>Arianna Dar</strong><br>'
    "Synergic Solar<br>"
    '<a href="https://synergicsolar.com/dealers/signup" style="color: #0066cc;">'
    "Become a Dealer</a> | "
    '<a href="https://synergicsolar.com" style="color: #0066cc;">'
    "synergicsolar.com</a></p>"
)

# Skip these senders entirely — bounces, system messages, self-replies.
_SYSTEM_SENDER_PATTERNS = [
    r"arianna@synergicsolar\.com",
    r"noreply@",
    r"no-reply@",
    r"mailer-daemon@",
    r"postmaster@",
    r"mail delivery",
    r"cpanel@",
    r"reddit\.com",
    r"openai\.com",
    r"zendesk",
]


# =========================================================================
# Intent & prospect-type classifiers (deterministic, no LLM)
# =========================================================================

# Duplicate-email complaints & opt-out requests. Hard-stop the prospect.
_OPT_OUT_PATTERNS = [
    r"\bremove\s+(me|us)\s+from\b",
    r"\bremove\s+from\s+(your|the)\s+(list|mailing|email)",
    r"\bunsubscribe\b",
    r"\bstop\s+(emailing|sending|contacting)\b",
    r"\bnot\s+(interested|in\s+need)\b",
    r"\b(do\s+not|don'?t)\s+(contact|email|reach)\b",
    r"\btake\s+(me|us)\s+off\b",
    r"\bmultiple\s+emails\s+from\s+you\b",
    r"\b\d+\s+(of\s+)?(the\s+same\s+)?emails?\s+(from\s+you\s+)?in\s+the\s+past\b",
    r"\byou'?ve\s+emailed\s+me\s+\d+\s+times\b",
    r"\bupdate\s+your\s+automations?\b",
]

# Negative sentiment short of opt-out — still handle gently but not a lead.
_NEGATIVE_PATTERNS = [
    r"\bnot\s+a\s+(good\s+)?fit\b",
    r"\bnot\s+(at\s+this\s+time|right\s+now|currently)\b",
    r"\bno\s+thank\s*(s|you)\b",
    r"\bpass\b",
    r"\bdecline\b",
]

# Positive/interested sentiment.
_POSITIVE_PATTERNS = [
    r"\bwhen\s+can\s+we\s+(talk|chat|meet|connect)\b",
    r"\blet'?s\s+(talk|chat|set\s+up)\b",
    r"\bi'?m\s+interested\b",
    r"\byes[,.!\s]",
    r"\btell\s+me\s+more\b",
    r"\bhow\s+does\s+it\s+work\b",
    r"\bwhat'?s\s+(the\s+)?next\s+step\b",
    r"\bsounds\s+(good|great|interesting)\b",
    r"\bwould\s+love\s+to\b",
    r"\bwe'?d\s+like\s+to\b",
]

# Prospect-type classification — mirrors the Odoo-side classifier.
_INSTALLER_PATTERNS = [
    r"\bfull\s+in[\s-]?house\b",
    r"\bin[\s-]?house\s+EPC\b",
    r"\bEPC\s+(installer|contractor|partner|shop|company)\b",
    r"\bwe\s+are\s+an?\s+EPC\b",
    r"\bwe'?re\s+an?\s+EPC\b",
    r"\bwe\s+do\s+EPC\b",
    r"\binstall(ation)?\s+(crew|crews|team|footprint|capacity)\b",
    r"\bour\s+(own\s+)?install(ation)?\s+(crew|team|footprint|capacity)\b",
    r"\bwe\s+self[\s-]?perform\b",
    r"\bwe\s+self[\s-]?install\b",
    r"\binstall(ation)?\s+referrals?\b",
    r"\bwe\s+install(ed)?\s+(over\s+|more\s+than\s+)?\d+",
    r"\bour\s+crews?\b",
    r"\binstall\s+partner\b",
    r"\bwe\s+handle\s+install",
]

_SALES_PATTERNS = [
    r"\bD2D\b",
    r"\bdoor[\s-]to[\s-]door\b",
    r"\bour\s+sales\s+team\b",
    r"\bwe\s+sell\s+solar\b",
    r"\bsolar\s+brokers?\b",
    r"\bwe'?re\s+(a\s+)?dealer\b",
    r"\bwe\s+don'?t\s+install\b",
    r"\bwe\s+refer\s+install",
    r"\bpure\s+sales\b",
]

_HYBRID_PATTERNS = [
    r"\bsales\s+(and|&)\s+install",
    r"\bsell\s+(and|&)\s+install",
    r"\bfull[-\s]service\s+solar\b",
    r"\b(from|through)\s+sales\s+through\s+install",
    r"\bwe\s+handle\s+everything\s+from\s+sales",
]


def _any_match(patterns: list[str], text: str) -> bool:
    if not text:
        return False
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def classify_intent(subject: str, body: str) -> str:
    """Return one of: 'opt_out', 'negative', 'positive', 'neutral'."""
    blob = f"{subject or ''}\n{body or ''}".lower()
    if _any_match(_OPT_OUT_PATTERNS, blob):
        return "opt_out"
    if _any_match(_NEGATIVE_PATTERNS, blob):
        return "negative"
    if _any_match(_POSITIVE_PATTERNS, blob):
        return "positive"
    return "neutral"


def classify_prospect_type(subject: str, body: str) -> str:
    """Return 'installer', 'hybrid', or 'sales'."""
    blob = f"{subject or ''}\n{body or ''}".lower()
    if not blob.strip():
        return "sales"
    if _any_match(_HYBRID_PATTERNS, blob):
        return "hybrid"
    installer_hit = _any_match(_INSTALLER_PATTERNS, blob)
    sales_hit = _any_match(_SALES_PATTERNS, blob)
    if installer_hit and sales_hit:
        return "hybrid"
    if installer_hit:
        return "installer"
    return "sales"


# =========================================================================
# IMAP helpers
# =========================================================================


def _decode_header(raw: str) -> str:
    if not raw:
        return ""
    parts = decode_header(raw)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            try:
                out.append(text.decode(enc or "utf-8", errors="replace"))
            except LookupError:
                out.append(text.decode("utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _extract_sender_email(from_header: str) -> str:
    """Pull the email address out of a From header."""
    if not from_header:
        return ""
    m = re.search(r"[\w\.\+\-]+@[\w\.\-]+\.\w+", from_header)
    return m.group(0).lower() if m else ""


def _extract_sender_name(from_header: str) -> str:
    """Pull a display name out of a From header."""
    if not from_header:
        return ""
    # "Name" <email@example.com>  or  Name <email@example.com>
    m = re.match(r'\s*"?([^"<]+?)"?\s*<', from_header)
    if m:
        return m.group(1).strip()
    return ""


def _is_system_sender(email_addr: str) -> bool:
    if not email_addr:
        return True
    for pat in _SYSTEM_SENDER_PATTERNS:
        if re.search(pat, email_addr, re.IGNORECASE):
            return True
    return False


def _extract_body(msg: email.message.Message) -> tuple[str, str]:
    """Return (plain_text, html) bodies. Either may be empty."""
    plain = ""
    html = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain" and not plain:
                try:
                    plain = part.get_payload(decode=True).decode(
                        "utf-8", errors="replace",
                    )
                except Exception:
                    pass
            elif ct == "text/html" and not html:
                try:
                    html = part.get_payload(decode=True).decode(
                        "utf-8", errors="replace",
                    )
                except Exception:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                text = payload.decode("utf-8", errors="replace")
                if (msg.get_content_type() or "").lower() == "text/html":
                    html = text
                else:
                    plain = text
        except Exception:
            pass
    # If we only got HTML, strip it to approximate plain.
    if html and not plain:
        stripped = re.sub(r"<[^>]+>", "", html)
        plain = re.sub(r"\s+", " ", stripped).strip()
    return plain, html


def fetch_unread_emails(
    imap_password: str, max_count: int = 10,
) -> list[dict[str, Any]]:
    """Fetch unread emails from Arianna's inbox.

    CRITICAL: marks every fetched email as \\Seen immediately so a
    mid-cycle crash doesn't re-process the same emails on the next run
    and cause duplicate replies.
    """
    if not imap_password:
        logger.error("fetch_unread_emails: ARIANNA_IMAP_AUTH not set")
        return []

    results: list[dict[str, Any]] = []
    try:
        imap = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT)
        imap.login(_IMAP_USER, imap_password)
        imap.select("INBOX")
        status, data = imap.search(None, "UNSEEN")
        if status != "OK" or not data[0]:
            imap.logout()
            return []
        uids = data[0].split()[:max_count]
        for uid in uids:
            try:
                res, msg_data = imap.fetch(uid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                from_header = _decode_header(msg.get("From", ""))
                subject = _decode_header(msg.get("Subject", ""))
                sender_email = _extract_sender_email(from_header)
                sender_name = _extract_sender_name(from_header)
                plain, html = _extract_body(msg)
                results.append({
                    "uid": uid.decode(),
                    "from_header": from_header,
                    "sender_email": sender_email,
                    "sender_name": sender_name,
                    "subject": subject,
                    "body_text": plain,
                    "body_html": html,
                })
            except Exception as exc:
                logger.warning("Failed to parse email uid=%s: %s", uid, exc)
        # Mark them all as read BEFORE returning. If processing later
        # throws, we still don't re-read them.
        for uid in uids:
            try:
                imap.store(uid, "+FLAGS", "\\Seen")
            except Exception:
                pass
        imap.logout()
    except Exception as exc:
        logger.exception("IMAP fetch failed: %s", exc)
    return results


# =========================================================================
# Odoo API helpers
# =========================================================================


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_ODOO_API_TOKEN}",
        "Content-Type": "application/json",
    }


async def check_duplicate(
    client: httpx.AsyncClient, sender_email: str, sender_name: str,
) -> dict[str, Any] | None:
    """Look up an existing prospect by email or domain."""
    try:
        resp = await client.post(
            f"{_ODOO_API_BASE}/check-duplicates",
            headers=_auth_headers(),
            json={"companies": [{"email": sender_email, "name": sender_name or sender_email}]},
            timeout=30.0,
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
        matches = data.get("matches") or data.get("duplicates") or []
        if matches and isinstance(matches, list):
            match = matches[0]
            if isinstance(match, dict) and match.get("prospect_id"):
                return match
        return None
    except Exception as exc:
        logger.warning("check_duplicate failed: %s", exc)
        return None


async def import_new_prospect(
    client: httpx.AsyncClient, sender_email: str, sender_name: str,
) -> int | None:
    """Create a new prospect stub for an unknown sender."""
    try:
        resp = await client.post(
            f"{_ODOO_API_BASE}/import",
            headers=_auth_headers(),
            json={
                "batch_name": "Email Reply Import",
                "source": "manual",
                "prospects": [{
                    "name": sender_name or sender_email,
                    "contact_name": sender_name or "",
                    "email": sender_email,
                    "source": "manual",
                    "ai_research_notes": "Contacted Arianna directly via email.",
                }],
            },
            timeout=30.0,
        )
        if resp.status_code >= 400:
            logger.warning("import_new_prospect HTTP %s: %s", resp.status_code, resp.text[:300])
            return None
        data = resp.json()
        ids = data.get("prospect_ids") or data.get("created_ids") or []
        return ids[0] if ids else None
    except Exception as exc:
        logger.warning("import_new_prospect failed: %s", exc)
        return None


async def mark_responded(
    client: httpx.AsyncClient, prospect_id: int, payload: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        resp = await client.post(
            f"{_ODOO_API_BASE}/{prospect_id}/mark-responded",
            headers=_auth_headers(), json=payload, timeout=30.0,
        )
        if resp.status_code >= 400:
            logger.warning(
                "mark-responded HTTP %s for prospect %s: %s",
                resp.status_code, prospect_id, resp.text[:300],
            )
            return None
        return resp.json()
    except Exception as exc:
        logger.warning("mark-responded failed for %s: %s", prospect_id, exc)
        return None


async def log_email_to_crm(
    client: httpx.AsyncClient, prospect_id: int, payload: dict[str, Any],
) -> bool:
    try:
        resp = await client.post(
            f"{_ODOO_API_BASE}/{prospect_id}/log-email",
            headers=_auth_headers(), json=payload, timeout=30.0,
        )
        if resp.status_code >= 400:
            logger.warning(
                "log-email HTTP %s for prospect %s: %s",
                resp.status_code, prospect_id, resp.text[:300],
            )
            return False
        return True
    except Exception as exc:
        logger.warning("log-email failed for %s: %s", prospect_id, exc)
        return False


async def fetch_nurture_candidates(
    client: httpx.AsyncClient, limit: int,
) -> list[dict[str, Any]]:
    try:
        resp = await client.get(
            f"{_ODOO_API_BASE}/follow-up-candidates?limit={limit}",
            headers=_auth_headers(), timeout=30.0,
        )
        if resp.status_code >= 400:
            logger.warning(
                "follow-up-candidates HTTP %s: %s",
                resp.status_code, resp.text[:300],
            )
            return []
        return resp.json().get("prospects", [])
    except Exception as exc:
        logger.warning("fetch_nurture_candidates failed: %s", exc)
        return []


# =========================================================================
# Outbound email helpers (SMTP via Mailbaby EmailSendTool)
# =========================================================================


async def send_outbound_email(
    to: str, subject: str, body_html: str,
) -> tuple[bool, str]:
    """Send via the existing EmailSendTool (Mailbaby SMTP relay).

    Returns (success, detail).
    """
    from tools.email_send_tool import EmailSendTool
    tool = EmailSendTool()
    result = await tool.execute(to=to, subject=subject, body_html=body_html)
    if result.success:
        return True, result.output or "sent"
    return False, result.error or "unknown error"


def wrap_body_with_signature(inner_html: str) -> str:
    """Wrap an inner body fragment in the full Arianna HTML envelope."""
    return (
        '<html><body style="font-family: Arial, sans-serif; '
        'font-size: 14px; color: #333; line-height: 1.6;">'
        f"{inner_html}"
        f"{_ARIANNA_SIGNATURE_HTML}"
        "</body></html>"
    )


# =========================================================================
# LLM prompt builders (narrow creative tasks — 1 call per email body)
# =========================================================================


def build_nurture_prompt(candidate: dict[str, Any]) -> str:
    """Prompt for a short nurture follow-up body."""
    contact = (candidate.get("contact_name") or "").strip() or "there"
    company = (candidate.get("name") or "").strip()
    city = (candidate.get("city") or "").strip()
    state = (candidate.get("state_code") or "").strip()
    location = f"{city}, {state}".strip(", ") if (city or state) else ""
    last_subject = (candidate.get("last_outbound_subject") or "").strip()

    location_hint = (
        f"Reference that we work with dealers in {location} if it flows naturally."
        if location else ""
    )
    subject_hint = (
        f"This is a follow-up to our earlier email '{last_subject}'."
        if last_subject else ""
    )

    return (
        "You are Arianna Dar, Synergic Solar's dealer partnerships rep. Write a "
        "SHORT warm follow-up email to a dealer prospect who clicked an earlier "
        "email but hasn't replied yet. This is a nurture touch, not a first contact.\n\n"
        f"Prospect:\n"
        f"- Company: {company or '(unknown)'}\n"
        f"- Contact name: {contact}\n"
        f"- Location: {location or '(unknown)'}\n\n"
        f"{subject_hint}\n\n"
        "Voice rules:\n"
        "- 2 short paragraphs max, total 60-120 words\n"
        f"- Open with 'Hi {contact},'\n"
        "- Say something SPECIFIC about Synergic's value (commissions, "
        "nationwide install network, brand retention) — not a generic check-in\n"
        f"- {location_hint}\n"
        "- One concrete ask: offer a 20-minute intro call\n"
        "- Close with 'Best,' on its own line\n"
        "- NO greetings like 'Hope you're well', NO emojis, NO exclamation points, "
        "NO phrases like 'any questions I can answer'\n\n"
        "Output ONLY the plain-text email body. No subject line. No HTML. No signature "
        "(the signature is appended automatically). No preamble."
    )


def build_reply_prompt(
    email_data: dict[str, Any], intent: str, prospect_type: str,
    assigned_dealer: str | None = None, dealer_referral_code: str | None = None,
) -> str:
    """Prompt for drafting a reply to an inbound prospect message."""
    sender_name = (email_data.get("sender_name") or "").strip()
    first_name = sender_name.split()[0] if sender_name else "there"
    subject = email_data.get("subject", "")
    body_snippet = (email_data.get("body_text") or "")[:800]

    # Intent-specific guidance
    if intent == "opt_out":
        directive = (
            "This prospect is asking to be removed from our outreach. "
            "Write a SHORT, apologetic acknowledgment. Acknowledge the "
            "inconvenience, confirm we've removed them from our list, and "
            "wish them well. Do NOT pitch the program. Do NOT include a "
            "signup link. 2-3 sentences max."
        )
    elif intent == "negative":
        directive = (
            "This prospect is declining politely. Write a SHORT, gracious "
            "acknowledgment. Thank them for the response, leave the door "
            "open for the future, no pitch, no signup link. 2-3 sentences."
        )
    elif prospect_type == "installer":
        directive = (
            "This prospect is an INSTALLER (not a sales org). Write a SHORT "
            "warm reply that (a) acknowledges their install capabilities, "
            "(b) introduces our EPC partnership program — installation "
            "referrals from our national sales network, expanded product "
            "access with better pricing, and a FREE Pro Dealer membership "
            "bundled into installer onboarding, (c) tells them our CRO "
            "Brad Pereira personally reviews every EPC application and "
            "will reach out within one business day, (d) points them at "
            "https://synergicsolar.com/epc/signup to apply. Do NOT include "
            "a /dealers/signup link — the EPC track is separate."
        )
    elif prospect_type == "hybrid":
        directive = (
            "This prospect both sells AND installs. Write a SHORT warm "
            "reply that (a) leads with our dealer program (commissions, "
            "brand retention, national install network), (b) includes the "
            f"signup link https://synergicsolar.com/dealers/signup"
            f"{f'?ref={dealer_referral_code}' if dealer_referral_code else ''}, "
            "(c) also mentions we have a separate EPC partnership track "
            "since they run install crews, and our CRO Brad Pereira will "
            "reach out about that side in parallel."
        )
    else:
        # Positive or neutral sales-org reply
        directive = (
            "This prospect is interested. Write a SHORT warm reply that "
            f"introduces our dealer program"
            + (
                f" and mentions their assigned Synergic Mentor Dealer, "
                f"{assigned_dealer}, who will help them get onboarded"
                if assigned_dealer else ""
            )
            + ". Include the signup link "
            f"https://synergicsolar.com/dealers/signup"
            f"{f'?ref={dealer_referral_code}' if dealer_referral_code else ''}. "
            "Mention they can schedule a 20-minute intro call if they prefer. "
            "3-4 short paragraphs."
        )

    return (
        "You are Arianna Dar, Synergic Solar's dealer partnerships rep. "
        "Draft a warm, professional reply to an inbound prospect email.\n\n"
        f"Their email subject: {subject}\n"
        f"Their message:\n{body_snippet}\n\n"
        f"Task: {directive}\n\n"
        "Voice rules:\n"
        f"- Open with 'Hi {first_name},'\n"
        "- 3-4 short paragraphs\n"
        "- No emojis, no exclamation points, no marketing jargon\n"
        "- Close with 'Best,' on its own line\n\n"
        "Output ONLY the plain-text email body. No subject line. No HTML. "
        "No signature (it is appended automatically). No preamble."
    )


def plain_text_to_html(plain: str) -> str:
    """Convert plain-text LLM output into paragraph HTML suitable for
    wrap_body_with_signature. Splits on blank lines, escapes, wraps."""
    import html as htmllib
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", (plain or "").strip()) if p.strip()]
    return "".join(
        f"<p>{htmllib.escape(p).replace(chr(10), '<br>')}</p>"
        for p in paragraphs
    )
