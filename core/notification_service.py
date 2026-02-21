"""
Webhook notification service — push alerts for task events, failures, and approvals.

Supports Slack, Discord, and email notifications. Auto-detects webhook format
from URL patterns. Includes retry with exponential backoff and SSRF protection.

Inspired by OpenClaw's push notification system.
"""

import asyncio
import json
import logging
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dataclasses import dataclass

import httpx

logger = logging.getLogger("agent42.notifications")

# Severity levels for notification routing
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

# Slack color mapping
_SLACK_COLORS = {
    SEVERITY_INFO: "#36a64f",
    SEVERITY_WARNING: "#ff9900",
    SEVERITY_CRITICAL: "#ff0000",
}

# Discord color mapping (decimal)
_DISCORD_COLORS = {
    SEVERITY_INFO: 3586116,      # green
    SEVERITY_WARNING: 16750848,  # orange
    SEVERITY_CRITICAL: 16711680, # red
}

# Events that trigger email notifications (critical events only)
_EMAIL_EVENTS = {"task_failed", "agent_stalled", "security_alert"}


@dataclass
class NotificationPayload:
    """Structured notification payload."""
    event: str
    timestamp: float
    task_id: str = ""
    title: str = ""
    details: str = ""
    severity: str = SEVERITY_INFO


class NotificationService:
    """Dispatch notifications to webhooks and email."""

    def __init__(
        self,
        webhook_urls: list[str] | None = None,
        allowed_events: list[str] | None = None,
        email_recipients: list[str] | None = None,
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
    ):
        self._webhook_urls = webhook_urls or []
        self._allowed_events = set(allowed_events) if allowed_events else set()
        self._email_recipients = email_recipients or []
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_user = smtp_user
        self._smtp_password = smtp_password

    async def notify(self, payload: NotificationPayload):
        """Send notification to all configured channels."""
        # Event filter
        if self._allowed_events and payload.event not in self._allowed_events:
            return

        tasks = []

        # Webhook notifications
        for url in self._webhook_urls:
            # SSRF protection on webhook URLs
            try:
                from core.url_policy import _is_ssrf_target
                ssrf = _is_ssrf_target(url)
                if ssrf:
                    logger.warning(f"Webhook URL blocked by SSRF: {url} — {ssrf}")
                    continue
            except ImportError:
                pass

            tasks.append(self._send_webhook(url, payload))

        # Email for critical events
        if payload.event in _EMAIL_EVENTS and self._email_recipients and self._smtp_host:
            tasks.append(self._send_email(payload))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_webhook(self, url: str, payload: NotificationPayload):
        """Send webhook with auto-format detection and retry."""
        body = self._format_webhook(url, payload)

        for attempt in range(3):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        url,
                        json=body,
                        timeout=10.0,
                        headers={"Content-Type": "application/json"},
                    )
                    if resp.status_code < 300:
                        logger.info(f"Webhook sent: {payload.event} -> {url[:50]}...")
                        return
                    logger.warning(f"Webhook failed ({resp.status_code}): {url[:50]}...")
            except Exception as e:
                logger.warning(f"Webhook error (attempt {attempt + 1}/3): {e}")

            # Exponential backoff: 1s, 2s, 4s
            await asyncio.sleep(2 ** attempt)

        logger.error(f"Webhook failed after 3 retries: {url[:50]}...")

    def _format_webhook(self, url: str, payload: NotificationPayload) -> dict:
        """Auto-detect webhook format from URL and format accordingly."""
        url_lower = url.lower()

        if "hooks.slack.com" in url_lower:
            return self._format_slack(payload)
        elif "discord.com/api/webhooks" in url_lower:
            return self._format_discord(payload)
        else:
            return self._format_generic(payload)

    @staticmethod
    def _format_slack(payload: NotificationPayload) -> dict:
        """Format as Slack Block Kit message."""
        color = _SLACK_COLORS.get(payload.severity, _SLACK_COLORS[SEVERITY_INFO])
        return {
            "attachments": [{
                "color": color,
                "blocks": [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": f"Agent42: {payload.event}"}
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Event:*\n{payload.event}"},
                            {"type": "mrkdwn", "text": f"*Severity:*\n{payload.severity}"},
                            {"type": "mrkdwn", "text": f"*Task:*\n{payload.task_id or 'N/A'}"},
                            {"type": "mrkdwn", "text": f"*Title:*\n{payload.title or 'N/A'}"},
                        ],
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": payload.details[:2000] if payload.details else "No details"},
                    },
                ],
            }],
        }

    @staticmethod
    def _format_discord(payload: NotificationPayload) -> dict:
        """Format as Discord embed."""
        color = _DISCORD_COLORS.get(payload.severity, _DISCORD_COLORS[SEVERITY_INFO])
        return {
            "embeds": [{
                "title": f"Agent42: {payload.event}",
                "color": color,
                "fields": [
                    {"name": "Event", "value": payload.event, "inline": True},
                    {"name": "Severity", "value": payload.severity, "inline": True},
                    {"name": "Task", "value": payload.task_id or "N/A", "inline": True},
                    {"name": "Title", "value": payload.title or "N/A", "inline": False},
                ],
                "description": payload.details[:4000] if payload.details else "No details",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(payload.timestamp)),
            }],
        }

    @staticmethod
    def _format_generic(payload: NotificationPayload) -> dict:
        """Format as generic JSON payload."""
        return {
            "event": payload.event,
            "timestamp": payload.timestamp,
            "task_id": payload.task_id,
            "title": payload.title,
            "details": payload.details,
            "severity": payload.severity,
            "source": "agent42",
        }

    async def _send_email(self, payload: NotificationPayload):
        """Send email notification for critical events via SMTP."""
        if not self._smtp_host or not self._email_recipients:
            return

        subject = f"[Agent42 {payload.severity.upper()}] {payload.event}: {payload.title or 'Alert'}"
        body = (
            f"Event: {payload.event}\n"
            f"Severity: {payload.severity}\n"
            f"Task ID: {payload.task_id or 'N/A'}\n"
            f"Title: {payload.title or 'N/A'}\n"
            f"Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(payload.timestamp))}\n\n"
            f"Details:\n{payload.details or 'No additional details.'}\n"
        )

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_smtp, subject, body)
            logger.info(f"Email sent: {payload.event} -> {len(self._email_recipients)} recipients")
        except Exception as e:
            logger.error(f"Email notification failed: {e}")

    def _send_smtp(self, subject: str, body: str):
        """Send email via SMTP (runs in executor to avoid blocking)."""
        msg = MIMEMultipart()
        msg["From"] = self._smtp_user
        msg["To"] = ", ".join(self._email_recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
            server.starttls()
            if self._smtp_user and self._smtp_password:
                server.login(self._smtp_user, self._smtp_password)
            server.send_message(msg)
