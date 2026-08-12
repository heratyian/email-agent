from __future__ import annotations

import email
import imaplib
import logging
import os
import re
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from email_agent.config import AccountConfig
from email_agent.mail.base import CategorySyncResult, CategorySyncState
from email_agent.mail.common import html_to_text
from email_agent.models import Draft, EmailMessage, EmailThread

logger = logging.getLogger(__name__)


def _header(value: str | None) -> str:
    return str(make_header(decode_header(value or "")))


class ImapProvider:
    """IMAP adapter that preserves unread state and copies mail into category folders."""

    def __init__(self, account_id: str, config: AccountConfig):
        self.account_id, self.config = account_id, config

    def _connect(self, mailbox: str = "INBOX"):
        username = os.getenv(self.config.username_env or "")
        password = os.getenv(self.config.password_env or "")
        if not username or not password:
            raise RuntimeError(
                f"Set {self.config.username_env} and {self.config.password_env} before connecting"
            )
        client = imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port)
        client.login(username, password)
        status, _ = client.select(self._mailbox(mailbox), readonly=False)
        if status != "OK":
            client.logout()
            raise RuntimeError(f"Could not select IMAP folder: {mailbox}")
        return client

    def _parse(self, provider_id: str, raw: bytes, mailbox: str = "INBOX") -> EmailMessage:
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
            mailbox=mailbox,
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
            messages = [self._fetch(client, value.decode(), "INBOX") for value in ids]
            logger.debug(
                "IMAP search returned %d message(s); unread_only=%s",
                len(messages),
                unread_only,
            )
            return messages
        finally:
            client.logout()

    def _fetch(self, client, message_id: str, mailbox: str = "INBOX") -> EmailMessage:
        status, data = client.uid("fetch", message_id, "(BODY.PEEK[])")
        if status != "OK" or not data or not isinstance(data[0], tuple):
            raise KeyError(f"Message not found: {message_id}")
        return self._parse(message_id, data[0][1], mailbox)

    def get_message(self, message_id: str, mailbox: str = "INBOX") -> EmailMessage:
        client = self._connect(mailbox)
        try:
            return self._fetch(client, message_id, mailbox)
        finally:
            client.logout()

    def get_thread(self, message_id: str, mailbox: str = "INBOX") -> EmailThread:
        return EmailThread(messages=[self.get_message(message_id, mailbox)])

    def create_draft(self, message_id: str, body: str) -> Draft:
        raise NotImplementedError("IMAP drafts are stored locally by the application")

    def mark_processed(self, message_id: str) -> None:
        return None

    @staticmethod
    def _mailbox(value: str) -> str:
        """Quote an ASCII mailbox name for an IMAP command."""
        return f'"{value.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'

    def sync_category(
        self,
        message_id: str,
        destination: str | None,
        source_mailbox: str = "INBOX",
        previous: CategorySyncState | None = None,
    ) -> CategorySyncResult | None:
        """Replace the previous managed folder copy or move with ``destination``."""
        action = self.config.category_action or "copy"
        logger.debug(
            "Synchronizing IMAP category: action=%s destination=%s previous=%s",
            action,
            destination or "uncategorized",
            previous.destination if previous else "none",
        )
        if destination is None:
            if action == "copy":
                self._delete_previous_copy(previous)
                return None
            destination = "INBOX"
        client = self._connect(source_mailbox)
        try:
            delimiter = self._folder_delimiter(client)
            parts = destination.split("/")
            provider_name = delimiter.join(parts) if delimiter else " - ".join(parts)
            mailbox = self._mailbox(provider_name)
            if delimiter:
                for depth in range(1, len(parts)):
                    self._ensure_folder(client, delimiter.join(parts[:depth]))
            self._ensure_folder(client, provider_name)
            if action == "copy":
                status, _ = client.uid("copy", message_id, mailbox)
                if status != "OK":
                    raise RuntimeError(f"Could not copy message to IMAP folder: {destination}")
                destination_uid = self._copy_uid(client)
                self._delete_previous_copy(previous)
                return CategorySyncResult(destination_uid, provider_name, source_moved=False)
            capabilities = self._capabilities(client)
            logger.debug("IMAP capabilities relevant to organization: %s", sorted(capabilities))
            missing = {"MOVE", "UIDPLUS"} - capabilities
            if missing:
                required = ", ".join(sorted(missing))
                raise RuntimeError(
                    f"IMAP move requires server capability: {required}; use category_action: copy"
                )
            status, _ = client.uid("move", message_id, mailbox)
            if status != "OK":
                raise RuntimeError(f"Could not move message to IMAP folder: {destination}")
            destination_uid = self._copy_uid(client)
            return CategorySyncResult(provider_id=destination_uid, mailbox=provider_name)
        finally:
            client.logout()

    @staticmethod
    def _copy_uid(client) -> str:
        """Return the destination UID reported by a UIDPLUS COPY or MOVE."""
        response, data = client.response("COPYUID")
        if response != "COPYUID" or not data or not data[0]:
            raise RuntimeError("IMAP category sync requires server UIDPLUS support (COPYUID)")
        copy_uid = data[0].decode() if isinstance(data[0], bytes) else data[0]
        destination_uid = copy_uid.split()[-1]
        if not destination_uid.isdigit():
            raise RuntimeError("IMAP server returned an invalid destination UID")
        return destination_uid

    def _delete_previous_copy(self, previous: CategorySyncState | None) -> None:
        """Delete only a previously tracked managed copy, leaving the Inbox original intact."""
        if not previous or not previous.provider_id or not previous.mailbox:
            return
        client = self._connect(previous.mailbox)
        try:
            status, _ = client.uid("store", previous.provider_id, "+FLAGS.SILENT", "(\\Deleted)")
            if status != "OK":
                raise RuntimeError("Could not remove the previous IMAP category copy")
            status, _ = client.uid("expunge", previous.provider_id)
            if status != "OK":
                raise RuntimeError("Could not expunge the previous IMAP category copy")
        finally:
            client.logout()

    @staticmethod
    def _capabilities(client) -> set[str]:
        """Refresh capabilities after authentication, when servers may add extensions."""
        status, rows = client.capability()
        if status == "OK" and rows:
            text = b" ".join(rows).decode() if isinstance(rows[0], bytes) else " ".join(rows)
            return {value.upper() for value in text.split()}
        return {
            value.decode().upper() if isinstance(value, bytes) else value.upper()
            for value in client.capabilities
        }

    def category_sync_key(self, destination: str) -> str:
        """Distinguish move completion from legacy/default copy completion."""
        return (
            f"move:{destination}"
            if (self.config.category_action or "copy") == "move"
            else destination
        )

    @staticmethod
    def _folder_delimiter(client) -> str | None:
        """Discover the hierarchy delimiter advertised by the IMAP server."""
        status, rows = client.list()
        if status != "OK" or not rows:
            return "/"
        text = rows[0].decode(errors="replace") if isinstance(rows[0], bytes) else rows[0]
        match = re.search(r'\([^)]*\)\s+(?:"([^"]+)"|NIL)\s+', text)
        return match.group(1) if match else "/"

    def _ensure_folder(self, client, name: str) -> None:
        status, _ = client.create(self._mailbox(name))
        if status not in {"OK", "NO"}:
            raise RuntimeError(f"Could not create IMAP folder: {name}")
