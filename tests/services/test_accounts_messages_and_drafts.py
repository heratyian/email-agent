from datetime import UTC, datetime

from email_agent.config import Settings
from email_agent.db import Database
from email_agent.models import DraftReply, EmailClassification, EmailMessage
from email_agent.runtime import RuntimeFactory
from email_agent.services import AccountService, DraftService, MessageService


def write_settings(root):
    (root / "accounts.yaml").write_text(
        """
accounts:
  person@example.com:
    provider: gmail
    model: {provider: openai, model: test}
    system_prompt: prompts/person/system.md
"""
    )
    prompt = root / "prompts/person/system.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Help with email.")
    return Settings(root)


def message() -> EmailMessage:
    return EmailMessage(
        provider_id="provider-1",
        account_id="person@example.com",
        from_address="sender@example.com",
        subject="Question",
        received_at=datetime.now(UTC),
    )


def classification() -> EmailClassification:
    return EmailClassification(
        category="action",
        requires_reply=True,
        priority="normal",
        summary="A question",
        confidence=0.9,
    )


def test_runtime_factory_builds_typed_account_dependencies_without_connecting(tmp_path):
    runtime = RuntimeFactory(write_settings(tmp_path)).for_account(
        "person@example.com", with_agents=False
    )

    assert runtime.account_id == "person@example.com"
    assert runtime.account.email == "person@example.com"
    assert runtime.agents is None
    assert runtime.database.path == runtime.settings.database_path


def test_account_service_validates_prompt_files(tmp_path):
    write_settings(tmp_path)
    assert AccountService(tmp_path).validate() == ["person@example.com"]


def test_message_service_retrieves_provider_message(tmp_path, monkeypatch):
    settings = write_settings(tmp_path)
    database = Database(settings.database_path)
    source = message()
    local_id = database.save_triage(source, classification())
    service = MessageService(settings, database)

    class Provider:
        def get_message(self, provider_id, mailbox):
            return source

    monkeypatch.setattr(
        "email_agent.services.messages.create_mail_provider",
        lambda account_id, account, root: Provider(),
    )
    details = service.show(local_id)
    assert details.message.subject == "Question"
    assert details.classification["category"] == "action"


def test_draft_service_uploads_to_mailbox_and_removes_item_from_queue(tmp_path, monkeypatch):
    database = Database(tmp_path / "email-agent.db")
    source = message()
    reply = DraftReply(
        recipient="sender@example.com",
        subject="Re: Question",
        body="Here is the answer.",
        reasoning_summary="Answer directly.",
        confidence=0.9,
    )
    database.save_result(source, classification(), reply)
    settings = write_settings(tmp_path)

    class Provider:
        def get_message(self, provider_id, mailbox):
            return source

        def upload_draft(self, source, **draft):
            assert draft["body"] == "Here is the answer."
            return "mailbox-draft-1"

    monkeypatch.setattr(
        "email_agent.services.drafts.create_mail_provider",
        lambda account_id, account, root: Provider(),
    )
    service = DraftService(database, settings)

    assert service.get(1)["subject"] == "Re: Question"
    assert service.source_message(1).content == source.content
    assert service.upload(1) == "mailbox-draft-1"
    assert service.get(1)["status"] == "uploaded"
    assert service.list() == []


def test_draft_service_deletes_suggestion_from_review_queue(tmp_path):
    database = Database(tmp_path / "email-agent.db")
    database.save_result(
        message(),
        classification(),
        DraftReply(
            recipient="sender@example.com",
            subject="Re: Question",
            body="No thanks.",
            reasoning_summary="Decline.",
            confidence=0.9,
        ),
    )

    service = DraftService(database)
    service.delete(1)

    assert service.get(1)["status"] == "rejected"
    assert service.list() == []
