"""
Email sending tool — sends outbound email via Mailbaby SMTP relay.

Credentials are read from environment variables only — never passed as
tool parameters. This keeps the password out of LLM-generated code,
agent instructions, and tool call logs.

Environment variables (configured in /opt/frood/.env):
    MAILBABY_SMTP_PASSWORD  — Mailbaby SMTP password (required)
    MAILBABY_SMTP_HOST      — relay host (default: relay.mailbaby.net)
    MAILBABY_SMTP_PORT      — port (default: 587)
    MAILBABY_SMTP_USER      — username (default: mb44866)
    MAILBABY_FROM_EMAIL     — sender address (default: arianna@synergicsolar.com)
    MAILBABY_FROM_NAME      — sender display name (default: Arianna Dar)
"""

import asyncio
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

from tools.base import Tool, ToolResult

logger = logging.getLogger("frood.tools.email_send")


class EmailSendTool(Tool):
    """Send an outbound email via Mailbaby SMTP relay.

    Uses fixed sender identity (arianna@synergicsolar.com) and Mailbaby
    relay credentials from environment. Supports HTML + plain-text multipart.
    """

    @property
    def name(self) -> str:
        return "send_email"

    @property
    def description(self) -> str:
        return (
            "Send an outbound email via Mailbaby SMTP relay. "
            "Always sends from arianna@synergicsolar.com. "
            "Provide body_html for rich email, body_text for plain fallback "
            "(at least one required). "
            "Returns 'sent' on success or an error message."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address.",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line.",
                },
                "body_html": {
                    "type": "string",
                    "description": "HTML email body. Recommended for outreach emails.",
                },
                "body_text": {
                    "type": "string",
                    "description": "Plain-text fallback body. Used when body_html is not provided or as multipart alternative.",
                },
                "reply_to": {
                    "type": "string",
                    "description": "Optional Reply-To address. Defaults to the From address.",
                },
                "in_reply_to_subject": {
                    "type": "string",
                    "description": "Optional: original email subject for threading (prepend 'Re: ' if replying).",
                },
            },
            "required": ["to", "subject"],
        }

    async def execute(self, **kwargs) -> ToolResult:
        to = (kwargs.get("to") or "").strip()
        subject = (kwargs.get("subject") or "").strip()
        body_html = (kwargs.get("body_html") or "").strip()
        body_text = (kwargs.get("body_text") or "").strip()
        reply_to = (kwargs.get("reply_to") or "").strip()

        if not to:
            return ToolResult(success=False, error="'to' is required")
        if not subject:
            return ToolResult(success=False, error="'subject' is required")
        if not body_html and not body_text:
            return ToolResult(success=False, error="At least one of body_html or body_text is required")

        smtp_host = os.environ.get("MAILBABY_SMTP_HOST", "relay.mailbaby.net")
        smtp_port = int(os.environ.get("MAILBABY_SMTP_PORT", "587"))
        smtp_user = os.environ.get("MAILBABY_SMTP_USER", "mb44866")
        smtp_pass = os.environ.get("MAILBABY_SMTP_PASSWORD", "")
        from_email = os.environ.get("MAILBABY_FROM_EMAIL", "arianna@synergicsolar.com")
        from_name = os.environ.get("MAILBABY_FROM_NAME", "Arianna Dar")

        if not smtp_pass:
            return ToolResult(
                success=False,
                error="MAILBABY_SMTP_PASSWORD not set in environment — cannot send email",
            )

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._send_smtp(
                    smtp_host, smtp_port, smtp_user, smtp_pass,
                    from_email, from_name, to, subject,
                    body_html, body_text, reply_to,
                ),
            )
            return result
        except Exception as exc:
            logger.error("send_email unexpected error to %s: %s", to, exc)
            return ToolResult(success=False, error=str(exc))

    def _send_smtp(
        self,
        host: str, port: int, user: str, password: str,
        from_email: str, from_name: str,
        to: str, subject: str,
        body_html: str, body_text: str, reply_to: str,
    ) -> ToolResult:
        """Blocking SMTP send — run in executor to avoid blocking the event loop."""
        try:
            msg = MIMEMultipart("alternative") if body_html else MIMEText(body_text, "plain", "utf-8")

            from_addr = formataddr((from_name, from_email))
            msg["From"] = from_addr
            msg["To"] = to
            msg["Subject"] = subject
            msg["Date"] = formatdate(localtime=False)
            msg["Message-ID"] = make_msgid(domain="synergicsolar.com")
            msg["Reply-To"] = reply_to or from_addr

            if body_html:
                if body_text:
                    msg.attach(MIMEText(body_text, "plain", "utf-8"))
                msg.attach(MIMEText(body_html, "html", "utf-8"))

            with smtplib.SMTP(host, port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(user, password)
                server.sendmail(from_email, [to], msg.as_string())

            msg_id = msg["Message-ID"]
            logger.info("send_email: sent to %s subject=%r msg_id=%s", to, subject, msg_id)
            return ToolResult(success=True, output=f"sent (message-id: {msg_id})")

        except smtplib.SMTPAuthenticationError as exc:
            logger.error("send_email SMTP auth failed: %s", exc)
            return ToolResult(success=False, error=f"SMTP authentication failed: {exc}")
        except smtplib.SMTPRecipientsRefused as exc:
            logger.error("send_email recipient refused %s: %s", to, exc)
            return ToolResult(success=False, error=f"Recipient refused: {exc}")
        except smtplib.SMTPException as exc:
            logger.error("send_email SMTP error to %s: %s", to, exc)
            return ToolResult(success=False, error=f"SMTP error: {exc}")
        except OSError as exc:
            logger.error("send_email connection error to %s:%d: %s", host, port, exc)
            return ToolResult(success=False, error=f"Connection error: {exc}")
