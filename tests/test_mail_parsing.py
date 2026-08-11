import base64
import json
from datetime import UTC, datetime, timedelta

from email_agent.config import AccountConfig
from email_agent.mail.gmail import GmailProvider
from email_agent.mail.imap import ImapProvider


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def account(provider: str, **values) -> AccountConfig:
    return AccountConfig.model_validate(
        {
            "provider": provider,
            "email": "person@example.com",
            "agent": {
                "name": "Test",
                "model": {"provider": "openai", "model": "test-model"},
                "system_prompt": "prompts/test/system.md",
            },
            **values,
        }
    )


def test_gmail_ignores_text_attachments_and_handles_missing_date(tmp_path):
    provider = GmailProvider("personal", account("gmail"), tmp_path)
    message = provider._parse(
        {
            "id": "1",
            "threadId": "t1",
            "internalDate": "1704067200000",
            "payload": {
                "mimeType": "multipart/mixed",
                "headers": [
                    {"name": "From", "value": "Person <person@example.com>"},
                    {"name": "Subject", "value": "Hello"},
                ],
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": _b64("actual body")}},
                    {
                        "mimeType": "text/plain",
                        "filename": "notes.txt",
                        "body": {"data": _b64("attachment body")},
                    },
                ],
            },
        }
    )
    assert message.text_body == "actual body"
    assert message.received_at.tzinfo == UTC


def test_imap_handles_message_without_date():
    provider = ImapProvider(
        "support",
        account(
            "imap",
            username_env="USER_ENV",
            password_env="PASSWORD_ENV",
            imap_host="imap.example.com",
        ),
    )
    message = provider._parse(
        "42",
        b"From: Person <person@example.com>\r\nSubject: Help\r\n\r\nPlease help",
    )
    assert message.text_body == "Please help"
    assert message.received_at.tzinfo == UTC


class FakeImapClient:
    def __init__(self):
        self.created = []
        self.copied = []
        self.logged_out = False

    def create(self, mailbox):
        self.created.append(mailbox)
        return "OK", []

    def list(self, reference, pattern):
        return "OK", [b'(\\Noselect) "." ""']

    def uid(self, command, message_id, mailbox):
        self.copied.append((command, message_id, mailbox))
        return "OK", []

    def logout(self):
        self.logged_out = True


def test_imap_category_sync_creates_folder_and_copies_message(monkeypatch):
    provider = ImapProvider(
        "support",
        account(
            "imap",
            username_env="USER_ENV",
            password_env="PASSWORD_ENV",
            imap_host="imap.example.com",
        ),
    )
    client = FakeImapClient()
    monkeypatch.setattr(provider, "_connect", lambda: client)

    provider.sync_category("42", "Email Agent/Action")

    assert client.created == ['"Email Agent"', '"Email Agent.Action"']
    assert client.copied == [("copy", "42", '"Email Agent.Action"')]
    assert client.logged_out is True


class Executable:
    def __init__(self, result, calls=None, call=None):
        self.result = result
        self.calls = calls
        self.call = call

    def execute(self):
        if self.calls is not None:
            self.calls.append(self.call)
        return self.result


class FakeGmailService:
    def __init__(self, labels):
        self.current_labels = labels
        self.calls = []

    def users(self):
        return self

    def labels(self):
        return self

    def messages(self):
        return self

    def list(self, **kwargs):
        return Executable({"labels": self.current_labels})

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return Executable({"id": "new-label", "name": kwargs["body"]["name"]})

    def modify(self, **kwargs):
        return Executable({}, self.calls, ("modify", kwargs))


def test_gmail_category_sync_reuses_existing_label(tmp_path, monkeypatch):
    provider = GmailProvider("personal", account("gmail"), tmp_path)
    service = FakeGmailService([{"id": "label-1", "name": "email agent/action"}])
    monkeypatch.setattr(provider, "_client", lambda: service)

    provider.sync_category("gmail-message", "Email Agent/Action")

    assert service.calls == [
        (
            "modify",
            {
                "userId": "me",
                "id": "gmail-message",
                "body": {"addLabelIds": ["label-1"]},
            },
        )
    ]


def test_gmail_category_sync_creates_missing_label(tmp_path, monkeypatch):
    provider = GmailProvider("personal", account("gmail"), tmp_path)
    service = FakeGmailService([])
    monkeypatch.setattr(provider, "_client", lambda: service)

    provider.sync_category("gmail-message", "Email Agent/Receipts")

    assert service.calls[0][0] == "create"
    assert service.calls[0][1]["body"]["name"] == "Email Agent/Receipts"
    assert service.calls[1][1]["body"] == {"addLabelIds": ["new-label"]}


def test_gmail_rejects_old_read_only_token_with_reauthorization_help(tmp_path):
    token = tmp_path / "token.json"
    token.write_text(
        json.dumps(
            {
                "token": "access-token",
                "refresh_token": "refresh-token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "client-id",
                "client_secret": "client-secret",
                "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
                "expiry": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
        )
    )
    provider = GmailProvider("personal", account("gmail", token_file=str(token)), tmp_path)

    try:
        provider._client()
    except RuntimeError as exc:
        assert "gmail.modify" in str(exc)
        assert str(token) in str(exc)
    else:
        raise AssertionError("read-only token should require reauthorization")
