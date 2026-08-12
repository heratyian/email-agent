from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from pathlib import Path

from email_agent.config import AccountConfig
from email_agent.models import Draft, EmailMessage, EmailThread
from email_agent.providers.base import CategorySyncState
from email_agent.providers.common import html_to_text

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
logger = logging.getLogger(__name__)


class GmailProvider:
    """Gmail adapter that reads mail and synchronizes agent categories as labels."""

    def __init__(self, account_id: str, config: AccountConfig, root: Path):
        self.account_id, self.config, self.root = account_id, config, root
        self._service = None

    def _path(self, configured: str | None, fallback: str) -> Path:
        path = Path(configured or fallback)
        return path if path.is_absolute() else self.root / path

    def _client(self):
        if self._service:
            return self._service
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        token_path = self._path(self.config.token_file, "secrets/gmail_token.json")
        credentials_path = self._path(
            self.config.credentials_file, "secrets/gmail_credentials.json"
        )
        credentials = None
        if token_path.exists():
            credentials = Credentials.from_authorized_user_file(str(token_path))
            if not credentials.has_scopes(SCOPES):
                raise RuntimeError(
                    "Gmail category sync needs gmail.modify permission. Delete or move "
                    f"{token_path}, then run the command again to authorize the new scope."
                )
        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
                if not credentials_path.exists():
                    raise RuntimeError(f"Gmail OAuth client file not found: {credentials_path}")
                credentials = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_path), SCOPES
                ).run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(credentials.to_json())
            token_path.chmod(0o600)
        self._service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        return self._service

    @staticmethod
    def _decode(value: str | None) -> str:
        if not value:
            return ""
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode(
            "utf-8", errors="replace"
        )

    def _parse(self, data: dict) -> EmailMessage:
        headers = {h["name"].lower(): h["value"] for h in data["payload"].get("headers", [])}
        text = html = None
        stack = [data["payload"]]
        while stack:
            part = stack.pop()
            stack.extend(part.get("parts", []))
            if part.get("filename"):
                continue
            headers_for_part = {
                header["name"].lower(): header["value"] for header in part.get("headers", [])
            }
            if "attachment" in headers_for_part.get("content-disposition", "").lower():
                continue
            mime = part.get("mimeType")
            body = self._decode(part.get("body", {}).get("data"))
            if mime == "text/plain" and body and text is None:
                text = body
            elif mime == "text/html" and body and html is None:
                html = body
        sender_name, sender_address = parseaddr(headers.get("from", ""))
        try:
            received = parsedate_to_datetime(headers.get("date", ""))
        except (TypeError, ValueError, OverflowError):
            received = None
        if received is None:
            received = datetime.fromtimestamp(int(data["internalDate"]) / 1000, tz=UTC)
        elif received.tzinfo is None:
            received = received.replace(tzinfo=UTC)
        return EmailMessage(
            provider_id=data["id"],
            thread_id=data.get("threadId"),
            account_id=self.account_id,
            from_address=sender_address,
            from_name=sender_name or None,
            to=[address for _, address in getaddresses([headers.get("to", "")])],
            cc=[address for _, address in getaddresses([headers.get("cc", "")])],
            subject=headers.get("subject", "(no subject)"),
            text_body=text or html_to_text(html),
            html_body=html,
            received_at=received,
            in_reply_to=headers.get("in-reply-to"),
            references=headers.get("references", "").split(),
        )

    def get_messages(self, limit: int = 20, *, unread_only: bool = False) -> list[EmailMessage]:
        """Return recent Inbox messages, optionally restricted to unread mail."""
        if limit < 1:
            return []
        service = self._client()
        query = "in:inbox is:unread" if unread_only else "in:inbox"
        result = service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
        logger.debug(
            "Gmail list returned %d message reference(s); unread_only=%s",
            len(result.get("messages", [])),
            unread_only,
        )
        messages = [self.get_message(item["id"]) for item in result.get("messages", [])]
        return sorted(messages, key=lambda message: message.received_at, reverse=True)

    def get_message(self, message_id: str, mailbox: str = "INBOX") -> EmailMessage:
        data = (
            self._client()
            .users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        return self._parse(data)

    def get_thread(self, message_id: str, mailbox: str = "INBOX") -> EmailThread:
        message = self.get_message(message_id, mailbox)
        data = (
            self._client()
            .users()
            .threads()
            .get(userId="me", id=message.thread_id, format="full")
            .execute()
        )
        return EmailThread(messages=[self._parse(item) for item in data.get("messages", [])])

    def create_draft(self, message_id: str, body: str) -> Draft:
        raise NotImplementedError("Native Gmail draft creation is disabled in this release")

    def mark_processed(self, message_id: str) -> None:
        return None

    def sync_category(
        self,
        message_id: str,
        destination: str | None,
        source_mailbox: str = "INBOX",
        previous: CategorySyncState | None = None,
    ) -> None:
        """Replace the previous agent-managed label without touching other labels."""
        service = self._client()
        labels = service.users().labels().list(userId="me").execute().get("labels", [])
        logger.debug("Gmail returned %d available labels", len(labels))
        by_name = {item.get("name", "").casefold(): item for item in labels}
        add_ids = []
        if destination is not None:
            label = by_name.get(destination.casefold())
            if label is None:
                label = (
                    service.users()
                    .labels()
                    .create(
                        userId="me",
                        body={
                            "name": destination,
                            "labelListVisibility": "labelShow",
                            "messageListVisibility": "show",
                        },
                    )
                    .execute()
                )
            add_ids.append(label["id"])
        remove_ids = []
        if previous and previous.destination != destination:
            old_label = by_name.get(previous.destination.casefold())
            if old_label is not None:
                remove_ids.append(old_label["id"])
        if not add_ids and not remove_ids:
            logger.debug("No Gmail label change required")
            return
        body = {}
        if add_ids:
            body["addLabelIds"] = add_ids
        if remove_ids:
            body["removeLabelIds"] = remove_ids
        (
            service.users()
            .messages()
            .modify(
                userId="me",
                id=message_id,
                body=body,
            )
            .execute()
        )
        logger.debug("Applied Gmail label changes: add=%d remove=%d", len(add_ids), len(remove_ids))

    @staticmethod
    def category_sync_key(destination: str) -> str:
        """Return the stable audit key for an idempotent Gmail label."""
        return destination
