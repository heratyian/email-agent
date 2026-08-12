from datetime import UTC, datetime, timedelta

from email_agent.config import Settings
from email_agent.models import DraftReply, EmailClassification, EmailMessage
from email_agent.runtime import RuntimeFactory
from email_agent.services import AccountService, DraftService, MessageService
from email_agent.storage import Database


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


def test_message_service_manages_attention_and_retrieves_provider_message(tmp_path, monkeypatch):
    settings = write_settings(tmp_path)
    database = Database(settings.database_path)
    source = message()
    local_id = database.save_triage(source, classification())
    service = MessageService(settings, database)

    assert service.done(local_id).subject == "Question"
    assert database.attention_state(local_id) == "done"
    service.snooze(local_id, datetime.now(UTC) + timedelta(days=1))
    assert database.attention_state(local_id) == "snoozed"
    service.reopen(local_id)
    assert database.attention_state(local_id) == "open"

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


def test_draft_service_gets_and_approves_one_message_draft(tmp_path):
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
    service = DraftService(database)

    assert service.get(1)["subject"] == "Re: Question"
    service.approve(1)
    assert service.get(1)["status"] == "approved"
