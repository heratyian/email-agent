from types import SimpleNamespace

from email_agent.ai.outputs import ClassificationOutput
from email_agent.config import AgentConfig
from email_agent.db import CategorySync, Classification, Message, initialize_database
from email_agent.providers.models import EmailMessage, EmailThread
from email_agent.services.organization import OrganizationService, OrganizationStatus


def classification(category: str | None) -> ClassificationOutput:
    return ClassificationOutput(
        category=category,
        requires_reply=False,
        priority="normal",
        summary="Test message",
        confidence=0.9,
    )


def account():
    return SimpleNamespace(
        agent=AgentConfig.model_validate(
            {
                "model": {"provider": "openai", "model": "test"},
                "classification_prompt": "prompts/test/classification.md",
                "draft_prompt": "prompts/test/draft.md",
                "categories": {"action": "Requires action."},
            }
        )
    )


class FakeProvider:
    def __init__(self):
        self.synced = []

    @staticmethod
    def category_sync_key(destination):
        return destination

    def sync_category(self, message_id, destination, mailbox="INBOX", previous=None):
        self.synced.append((message_id, destination))

    def get_message(self, message_id, mailbox="INBOX"):
        return EmailMessage.model_construct(provider_id=message_id)

    def get_thread(self, message_id, mailbox="INBOX"):
        return EmailThread(messages=[])


def row(local_id: int, category: str | None):
    message = Message.create(
        id=local_id,
        account_id="person@example.com",
        provider_message_id=str(local_id),
        provider_uid=str(local_id),
        provider_mailbox="INBOX",
        from_address="sender@example.com",
        subject=f"Message {local_id}",
        received_at="2026-01-01T00:00:00+00:00",
    )
    Classification.save_for(message, classification(category))
    return message


def test_organization_service_reports_mixed_message_outcomes(tmp_path):
    initialize_database(tmp_path / "test.db")
    row(1, "action")
    row(2, None)
    row(3, "obsolete")
    provider = FakeProvider()

    report = OrganizationService("person@example.com", account(), provider).run()

    assert report.changed == 1
    assert report.uncategorized == 1
    assert report.failed == 1
    assert provider.synced == [("1", "action")]
    assert CategorySync.is_active(1, "action")
    assert report.items[2].status is OrganizationStatus.FAILED
    assert "unknown category" in report.items[2].error


def test_dry_run_reclassification_has_no_side_effects(tmp_path):
    initialize_database(tmp_path / "test.db")
    stored = row(1, "obsolete")
    provider = FakeProvider()

    class Agents:
        def classify(self, message, thread):
            return ClassificationOutput(
                category="action",
                requires_reply=True,
                priority="normal",
                summary="Needs action",
                confidence=0.9,
            )

    report = OrganizationService(
        "person@example.com", account(), provider, Agents()
    ).run(dry_run=True, reclassify_all=True)

    assert report.changed == 1
    assert report.items[0].status is OrganizationStatus.PREVIEW
    assert report.items[0].reclassified_as == "action"
    assert stored.classification_value().category == "obsolete"
    assert not CategorySync.select().exists()
    assert provider.synced == []
