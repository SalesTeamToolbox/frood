"""
Email channel — IMAP/SMTP integration for receiving and sending emails.

Polls an IMAP inbox for new messages and sends replies via SMTP.
Essential for the existing EMAIL task type in Agent42.
"""

import asyncio
import email
import email.mime.text
import email.utils
import imaplib
import logging
import smtplib
import time

from channels.base import BaseChannel, InboundMessage, OutboundMessage

logger = logging.getLogger("agent42.channels.email")


class EmailChannel(BaseChannel):
    """Email channel using IMAP (receive) and SMTP (send)."""

    def __init__(self, config: dict):
        super().__init__("email", config)
        # IMAP settings
        self.imap_host = config.get("imap_host", "")
        self.imap_port = config.get("imap_port", 993)
        self.imap_user = config.get("imap_user", "")
        self.imap_password = config.get("imap_password", "")
        # SMTP settings
        self.smtp_host = config.get("smtp_host", "")
        self.smtp_port = config.get("smtp_port", 587)
        self.smtp_user = config.get("smtp_user", "")
        self.smtp_password = config.get("smtp_password", "")
        # Polling
        self.poll_interval = config.get("poll_interval", 60)
        self._task: asyncio.Task | None = None
        self._last_uid = 0

    async def start(self):
        if not self.imap_host or not self.imap_user:
            raise ValueError("Email IMAP configuration is required")

        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(f"Email channel started (polling {self.imap_host} every {self.poll_interval}s)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("Email channel stopped")

    async def send(self, message: OutboundMessage):
        """Send an email via SMTP."""
        if not self.smtp_host:
            logger.error("SMTP not configured — cannot send email")
            return

        msg = email.mime.text.MIMEText(message.content, "plain", "utf-8")
        msg["To"] = message.channel_id  # channel_id = recipient email
        msg["From"] = self.smtp_user
        msg["Subject"] = message.metadata.get("subject", "Agent42 Response")

        # Reply threading
        in_reply_to = message.metadata.get("message_id")
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._send_smtp, msg)

    def _send_smtp(self, msg: email.mime.text.MIMEText):
        """Synchronous SMTP send (run in executor)."""
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            logger.info(f"Email sent to {msg['To']}")
        except Exception as e:
            logger.error(f"Failed to send email: {e}")

    async def _poll_loop(self):
        """Poll IMAP inbox for new messages."""
        while self._running:
            try:
                loop = asyncio.get_event_loop()
                messages = await loop.run_in_executor(None, self._fetch_new_emails)
                for inbound in messages:
                    await self._enqueue(inbound)
            except Exception as e:
                logger.error(f"Email poll error: {e}", exc_info=True)

            await asyncio.sleep(self.poll_interval)

    def _fetch_new_emails(self) -> list[InboundMessage]:
        """Fetch unread emails from IMAP (synchronous)."""
        results = []
        try:
            conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
            conn.login(self.imap_user, self.imap_password)
            conn.select("INBOX")

            # Search for unseen messages
            _, msg_nums = conn.search(None, "UNSEEN")
            if not msg_nums[0]:
                conn.logout()
                return results

            for num in msg_nums[0].split():
                _, data = conn.fetch(num, "(RFC822)")
                if not data[0]:
                    continue

                raw = data[0][1]
                msg = email.message_from_bytes(raw)

                # Extract text body
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                            break
                else:
                    body = msg.get_payload(decode=True).decode("utf-8", errors="replace")

                sender = email.utils.parseaddr(msg.get("From", ""))

                results.append(InboundMessage(
                    channel_type="email",
                    channel_id=sender[1],  # sender's email address
                    sender_id=sender[1],
                    sender_name=sender[0] or sender[1],
                    content=body.strip(),
                    metadata={
                        "subject": msg.get("Subject", ""),
                        "message_id": msg.get("Message-ID", ""),
                        "date": msg.get("Date", ""),
                    },
                ))

            conn.logout()
        except Exception as e:
            logger.error(f"IMAP fetch error: {e}")

        return results
