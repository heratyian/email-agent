from datetime import UTC, datetime

from email_agent.ai.outputs import ClassificationOutput, DraftOutput
from email_agent.config import Settings
from email_agent.db import Classification, Draft, Message, database, initialize_database
from email_agent.providers.models import EmailMessage, EmailThread
from email_agent.runtime import RuntimeFactory
from email_agent.services import AccountService, DraftService, MessageService
from email_agent.services.drafts import reply_subject


def write_settings(root):
    (root / "accounts.yaml").write_text(
        """
accounts:
  person@example.com:
    provider: gmail
    model: {provider: openai, model: test}
    classification_prompt: prompts/person/classification.md
    draft_prompt: prompts/person/draft.md
"""
    )
    prompt_dir = root / "prompts/person"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "classification.md").write_text("Escalate sensitive messages.")
    (prompt_dir / "draft.md").write_text("Write concise replies.")
    return Settings(root)


def message() -> EmailMessage:
    return EmailMessage(
        provider_id="provider-1",
        account_id="person@example.com",
        from_address="sender@example.com",
        subject="Question",
        received_at=datetime.now(UTC),
    )


def classification() -> ClassificationOutput:
    return ClassificationOutput(
        category="action",
        requires_reply=True,
        priority="normal",
        summary="A question",
        confidence=0.9,
    )


def test_runtime_factory_initializes_account_dependencies_and_database(tmp_path):
    runtime = RuntimeFactory(write_settings(tmp_path)).for_inbox("person@example.com")

    assert runtime.account_id == "person@example.com"
    assert runtime.account.email == "person@example.com"
    assert runtime.classifier is None
    assert runtime.drafter is None
    assert database.database == runtime.settings.database_path


def test_account_service_validates_prompt_files(tmp_path):
    write_settings(tmp_path)
    assert AccountService(tmp_path).validate() == ["person@example.com"]


def test_message_service_retrieves_provider_message(tmp_path, monkeypatch):
    settings = write_settings(tmp_path)
    initialize_database(settings.database_path)
    source = message()
    stored = Message.upsert_email(source)
    Classification.save_for(stored, classification())
    service = MessageService(settings)

    class Provider:
        def get_message(self, provider_id, mailbox):
            return source

    monkeypatch.setattr(
        "email_agent.services.messages.create_mail_provider",
        lambda account_id, account, root: Provider(),
    )
    details = service.show(stored.id)
    assert details.message.subject == "Question"
    assert details.classification.category == "action"


def test_draft_service_uploads_to_mailbox_and_removes_item_from_queue(tmp_path, monkeypatch):
    initialize_database(tmp_path / "email-agent.db")
    source = message()
    reply = DraftOutput(
        recipient="sender@example.com",
        subject="Re: Question",
        body="Here is the answer.",
        reasoning_summary="Answer directly.",
        confidence=0.9,
    )
    stored = Message.upsert_email(source)
    Classification.save_for(stored, classification())
    Draft.replace_generated(stored, reply)
    settings = write_settings(tmp_path)

    class Provider:
        def get_message(self, provider_id, mailbox):
            return source

        def upload_draft(self, source, **draft):
            assert draft["body"] == "Here is the answer."
            assert draft["subject"] == "Re: Question"
            return "mailbox-draft-1"

    monkeypatch.setattr(
        "email_agent.services.drafts.create_mail_provider",
        lambda account_id, account, root: Provider(),
    )
    service = DraftService()

    assert Draft.latest_for_message(1).subject == "Re: Question"
    assert service.source_message(1, settings).content == source.content
    assert service.upload(1, settings) == "mailbox-draft-1"
    assert Draft.latest_for_message(1).status == "uploaded"
    assert list(Draft.pending()) == []


def test_reply_subject_uses_original_subject_without_duplicate_prefix():
    assert reply_subject("Question") == "Re: Question"
    assert reply_subject("Re: Question") == "Re: Question"
    assert reply_subject("re: Question") == "re: Question"
    assert reply_subject("") == "Re: (no subject)"


def test_draft_model_removes_suggestion_from_review_queue(tmp_path):
    initialize_database(tmp_path / "email-agent.db")
    source = message()
    stored = Message.upsert_email(source)
    Classification.save_for(stored, classification())
    Draft.replace_generated(
        stored,
        DraftOutput(
            recipient="sender@example.com",
            subject="Re: Question",
            body="No thanks.",
            reasoning_summary="Decline.",
            confidence=0.9,
        ),
    )

    Draft.change_generated_status(1, "rejected")

    assert Draft.latest_for_message(1).status == "rejected"
    assert list(Draft.pending()) == []


def test_draft_service_generates_and_replaces_local_suggestion(tmp_path):
    initialize_database(tmp_path / "email-agent.db")
    source = message()
    stored = Message.upsert_email(source)
    Classification.save_for(stored, classification())

    class Provider:
        def get_message(self, provider_id, mailbox):
            return source

        def get_thread(self, provider_id, mailbox):
            return EmailThread(messages=[source])

    class Agents:
        calls = 0

        def draft(self, message, thread, stored_classification):
            self.calls += 1
            return DraftOutput(
                recipient=message.from_address,
                subject="Re: Question",
                body=f"Generated answer {self.calls}.",
                reasoning_summary="Answer the question.",
                confidence=0.9,
            )

    agents = Agents()
    service = DraftService()

    first = service.generate(stored.id, Provider(), agents)
    second = service.generate(stored.id, Provider(), agents)

    assert first.body == "Generated answer 1."
    assert second.body == "Generated answer 2."
    assert Draft.latest_for_message(stored.id).body == "Generated answer 2."
    assert len(list(Draft.pending())) == 1
