from __future__ import annotations

import email
import imaplib
import os
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from email_agent.config import AccountConfig
from email_agent.mail.common import html_to_text
from email_agent.models import Draft, EmailMessage, EmailThread


def _header(value: str | None) -> str:
    return str(make_header(decode_header(value or "")))


class ImapProvider:
    """Read-only IMAP adapter that uses BODY.PEEK to preserve unread state."""

    def __init__(self, account_id: str, config: AccountConfig):
        self.account_id, self.config = account_id, config

    def _connect(self):
        username = os.getenv(self.config.username_env or "")
        password = os.getenv(self.config.password_env or "")
        if not username or not password:
            raise RuntimeError(
                f"Set {self.config.username_env} and {self.config.password_env} before connecting"
            )
        client = imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port)
        client.login(username, password)
        client.select("INBOX")
        return client

    def _parse(self, provider_id: str, raw: bytes) -> EmailMessage:
        msg = email.message_from_bytes(raw)
        text, html = None, None
        for part in msg.walk() if msg.is_multipart() else [msg]:
            if part.get_content_disposition() == "attachment":
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            decoded = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            if part.get_content_type() == "text/plain" and text is None:
                text = decoded
            elif part.get_content_type() == "text/html" and html is None:
                html = decoded
        sender_name, sender_address = parseaddr(_header(msg.get("From")))
        try:
            received = parsedate_to_datetime(msg.get("Date"))
        except (TypeError, ValueError, OverflowError):
            received = None
        received = received or datetime.now(UTC)
        if received.tzinfo is None:
            received = received.replace(tzinfo=UTC)
        references = (msg.get("References") or "").split()
        return EmailMessage(
            provider_id=provider_id,
            thread_id=msg.get("In-Reply-To") or msg.get("Message-ID"),
            account_id=self.account_id,
            from_address=sender_address,
            from_name=sender_name or None,
            to=[address for _, address in getaddresses(msg.get_all("To", []))],
            cc=[address for _, address in getaddresses(msg.get_all("Cc", []))],
            subject=_header(msg.get("Subject")) or "(no subject)",
            text_body=text or html_to_text(html),
            html_body=html,
            received_at=received,
            in_reply_to=msg.get("In-Reply-To"),
            references=references,
        )

    def get_messages(self, limit: int = 20, *, unread_only: bool = False) -> list[EmailMessage]:
        """Return recent messages, optionally restricted to unread mail."""
        if limit < 1:
            return []
        client = self._connect()
        try:
            criterion = "UNSEEN" if unread_only else "ALL"
            status, data = client.uid("search", None, criterion)
            if status != "OK" or not data:
                raise RuntimeError("IMAP message search failed")
            ids = reversed(data[0].split()[-limit:])
            return [self._fetch(client, value.decode()) for value in ids]
        finally:
            client.logout()

    def get_new_messages(self, limit: int = 20) -> list[EmailMessage]:
        """Return unread messages for the processing workflow."""
        return self.get_messages(limit, unread_only=True)

    def _fetch(self, client, message_id: str) -> EmailMessage:
        status, data = client.uid("fetch", message_id, "(BODY.PEEK[])")
        if status != "OK" or not data or not isinstance(data[0], tuple):
            raise KeyError(f"Message not found: {message_id}")
        return self._parse(message_id, data[0][1])

    def get_message(self, message_id: str) -> EmailMessage:
        client = self._connect()
        try:
            return self._fetch(client, message_id)
        finally:
            client.logout()

    def get_thread(self, message_id: str) -> EmailThread:
        return EmailThread(messages=[self.get_message(message_id)])

    def create_draft(self, message_id: str, body: str) -> Draft:
        raise NotImplementedError("IMAP drafts are stored locally by the application")

    def mark_processed(self, message_id: str) -> None:
        return None
