import base64
import json
from datetime import UTC, datetime, timedelta
from email import message_from_bytes
from email.policy import default

from email_agent.config import AccountConfig
from email_agent.providers.base import CategorySyncState
from email_agent.providers.gmail import GmailProvider
from email_agent.providers.imap import ImapProvider
from email_agent.providers.models import EmailMessage


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def account(provider: str, **values) -> AccountConfig:
    return AccountConfig.model_validate(
        {
            "provider": provider,
            "email": "person@example.com",
            "model": {"provider": "openai", "model": "test-model"},
            "classification_prompt": "prompts/test/classification.md",
            "draft_prompt": "prompts/test/draft.md",
            **values,
        }
    )


def source_message() -> EmailMessage:
    return EmailMessage(
        provider_id="source-1",
        thread_id="thread-1",
        account_id="person@example.com",
        from_address="sender@example.com",
        subject="Question",
        received_at=datetime.now(UTC),
        message_id="<source@example.com>",
        in_reply_to="<parent@example.com>",
        references=["<root@example.com>", "<parent@example.com>"],
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
        self.list_calls = 0

    def create(self, mailbox):
        self.created.append(mailbox)
        return "OK", []

    def list(self):
        self.list_calls += 1
        return "OK", [b'(\\Noselect) "." ""']

    def uid(self, command, message_id, mailbox):
        self.copied.append((command, message_id, mailbox))
        return "OK", []

    def response(self, code):
        assert code == "COPYUID"
        return "COPYUID", [b"12345 42 99"]

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
    monkeypatch.setattr(provider, "_connect", lambda mailbox="INBOX": client)

    result = provider.sync_category("42", "Email Agent/Action")

    assert client.created == ['"Email Agent"', '"Email Agent.Action"']
    assert client.copied == [("copy", "42", '"Email Agent.Action"')]
    assert client.logged_out is True
    assert client.list_calls == 1
    assert result.provider_id == "99"
    assert result.mailbox == "Email Agent.Action"
    assert result.source_moved is False


def test_imap_category_copy_replaces_tracked_previous_copy(monkeypatch):
    provider = ImapProvider(
        "support",
        account(
            "imap",
            username_env="USER_ENV",
            password_env="PASSWORD_ENV",
            imap_host="imap.example.com",
        ),
    )
    source = FakeImapClient()

    class CleanupClient:
        def __init__(self):
            self.calls = []
            self.logged_out = False

        def uid(self, *args):
            self.calls.append(args)
            return "OK", []

        def logout(self):
            self.logged_out = True

    cleanup = CleanupClient()
    monkeypatch.setattr(
        provider, "_connect", lambda mailbox="INBOX": cleanup if mailbox == "old" else source
    )

    provider.sync_category(
        "42",
        "new",
        previous=CategorySyncState("old", provider_id="17", mailbox="old"),
    )

    assert cleanup.calls == [
        ("store", "17", "+FLAGS.SILENT", "(\\Deleted)"),
        ("expunge", "17"),
    ]
    assert cleanup.logged_out is True


class FakeMoveImapClient(FakeImapClient):
    capabilities = (b"IMAP4REV1", b"MOVE", b"UIDPLUS")

    def capability(self):
        return "OK", [b"IMAP4rev1 MOVE UIDPLUS"]

    def uid(self, command, message_id, mailbox):
        self.copied.append((command, message_id, mailbox))
        return "OK", [None]

    def response(self, code):
        assert code == "COPYUID"
        return "COPYUID", [b"12345 42 99"]


def test_imap_category_move_returns_new_folder_scoped_uid(monkeypatch):
    provider = ImapProvider(
        "support",
        account(
            "imap",
            username_env="USER_ENV",
            password_env="PASSWORD_ENV",
            imap_host="imap.example.com",
            category_action="move",
        ),
    )
    client = FakeMoveImapClient()
    monkeypatch.setattr(provider, "_connect", lambda mailbox="INBOX": client)

    result = provider.sync_category("42", "agent/action")

    assert client.copied == [("move", "42", '"agent.action"')]
    assert result.provider_id == "99"
    assert result.mailbox == "agent.action"
    assert provider.category_sync_key("agent/action") == "move:agent/action"


def test_imap_uploads_message_to_advertised_drafts_folder(monkeypatch):
    provider = ImapProvider(
        "person@example.com",
        account(
            "imap",
            username_env="USER_ENV",
            password_env="PASSWORD_ENV",
            imap_host="imap.example.com",
        ),
    )

    class DraftClient(FakeImapClient):
        def list(self):
            return "OK", [b'(\\HasNoChildren \\Drafts) "/" "INBOX.Drafts"']

        def append(self, mailbox, flags, date_time, message):
            self.appended = (mailbox, flags, message)
            return "OK", []

        def response(self, code):
            assert code == "APPENDUID"
            return "APPENDUID", [b"12345 88"]

    client = DraftClient()
    monkeypatch.setattr(provider, "_connect", lambda mailbox="INBOX": client)

    provider_id = provider.upload_draft(
        source_message(),
        recipient="sender@example.com",
        subject="Re: Question",
        body="Here is the answer.",
    )

    assert provider_id == "88"
    assert client.appended[0] == '"INBOX.Drafts"'
    assert client.appended[1] == "(\\Draft)"
    uploaded = message_from_bytes(client.appended[2], policy=default)
    assert uploaded["To"] == "sender@example.com"
    assert uploaded["In-Reply-To"] == "<source@example.com>"
    assert uploaded["References"] == (
        "<root@example.com> <parent@example.com> <source@example.com>"
    )
    assert uploaded.get_content().strip() == "Here is the answer."


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

    def drafts(self):
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


def test_gmail_uploads_threaded_draft_without_sending(tmp_path, monkeypatch):
    provider = GmailProvider("personal", account("gmail"), tmp_path)
    service = FakeGmailService([])

    def create(**kwargs):
        service.calls.append(("create-draft", kwargs))
        return Executable({"id": "draft-1"})

    monkeypatch.setattr(service, "create", create)
    monkeypatch.setattr(provider, "_client", lambda: service)

    provider_id = provider.upload_draft(
        source_message(),
        recipient="sender@example.com",
        subject="Re: Question",
        body="Here is the answer.",
    )

    assert provider_id == "draft-1"
    payload = service.calls[0][1]["body"]["message"]
    uploaded = message_from_bytes(base64.urlsafe_b64decode(payload["raw"]), policy=default)
    assert payload["threadId"] == "thread-1"
    assert uploaded["To"] == "sender@example.com"
    assert uploaded["In-Reply-To"] == "<source@example.com>"
    assert uploaded["References"] == (
        "<root@example.com> <parent@example.com> <source@example.com>"
    )
    assert uploaded.get_content().strip() == "Here is the answer."


def test_gmail_category_sync_creates_missing_label(tmp_path, monkeypatch):
    provider = GmailProvider("personal", account("gmail"), tmp_path)
    service = FakeGmailService([])
    monkeypatch.setattr(provider, "_client", lambda: service)

    provider.sync_category("gmail-message", "Email Agent/Receipts")

    assert service.calls[0][0] == "create"
    assert service.calls[0][1]["body"]["name"] == "Email Agent/Receipts"
    assert service.calls[1][1]["body"] == {"addLabelIds": ["new-label"]}


def test_gmail_category_sync_replaces_only_previous_managed_label(tmp_path, monkeypatch):
    provider = GmailProvider("personal", account("gmail"), tmp_path)
    service = FakeGmailService(
        [
            {"id": "old-label", "name": "action"},
            {"id": "new-label", "name": "travel"},
            {"id": "user-label", "name": "family"},
        ]
    )
    monkeypatch.setattr(provider, "_client", lambda: service)

    provider.sync_category(
        "gmail-message", "travel", previous=CategorySyncState(destination="action")
    )

    assert service.calls == [
        (
            "modify",
            {
                "userId": "me",
                "id": "gmail-message",
                "body": {
                    "addLabelIds": ["new-label"],
                    "removeLabelIds": ["old-label"],
                },
            },
        )
    ]


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
