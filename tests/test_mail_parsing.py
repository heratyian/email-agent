import base64
from datetime import UTC

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
                "prompts": {
                    "system": "prompts/test/system.md",
                    "classify": "prompts/test/classify.md",
                    "reply": "prompts/test/reply.md",
                },
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
