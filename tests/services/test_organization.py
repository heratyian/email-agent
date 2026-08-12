from types import SimpleNamespace

from email_agent.config import AgentConfig
from email_agent.models import EmailClassification, EmailMessage, EmailThread
from email_agent.services.organization import OrganizationService, OrganizationStatus


def classification(category: str | None) -> str:
    return EmailClassification(
        category=category,
        requires_reply=False,
        priority="normal",
        summary="Test message",
        confidence=0.9,
    ).model_dump_json()


def account():
    return SimpleNamespace(
        agent=AgentConfig.model_validate(
            {
                "model": {"provider": "openai", "model": "test"},
                "system_prompt": "prompts/test/system.md",
                "categories": {"action": "Requires action."},
            }
        )
    )


class FakeDatabase:
    def __init__(self, rows):
        self.rows = rows
        self.updated = []
        self.synced = []

    def list_categorized_messages(self, account_id, limit):
        return self.rows[:limit]

    def category_was_synced(self, message_id, destination):
        return False

    def current_category_sync(self, message_id):
        return None

    def update_classification(self, message_id, value):
        self.updated.append((message_id, value.category))

    def update_provider_location(self, message_id, provider_id, mailbox):
        raise AssertionError("No move result was returned")

    def mark_category_synced(self, message_id, destination, result=None):
        self.synced.append((message_id, destination))


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
    return {
        "id": local_id,
        "provider_uid": str(local_id),
        "provider_mailbox": "INBOX",
        "subject": f"Message {local_id}",
        "classification": classification(category),
    }


def test_organization_service_reports_mixed_message_outcomes():
    database = FakeDatabase([row(1, "action"), row(2, None), row(3, "obsolete")])
    provider = FakeProvider()

    report = OrganizationService(
        "person@example.com", account(), provider, database
    ).run()

    assert report.changed == 1
    assert report.uncategorized == 1
    assert report.failed == 1
    assert provider.synced == [("1", "action")]
    assert database.synced == [(1, "action")]
    assert report.items[2].status is OrganizationStatus.FAILED
    assert "unknown category" in report.items[2].error


def test_dry_run_reclassification_has_no_side_effects():
    database = FakeDatabase([row(1, "obsolete")])
    provider = FakeProvider()

    class Agents:
        def classify(self, message, thread):
            return EmailClassification(
                category="action",
                requires_reply=True,
                priority="normal",
                summary="Needs action",
                confidence=0.9,
            )

    report = OrganizationService(
        "person@example.com", account(), provider, database, Agents()
    ).run(dry_run=True, reclassify_all=True)

    assert report.changed == 1
    assert report.items[0].status is OrganizationStatus.PREVIEW
    assert report.items[0].reclassified_as == "action"
    assert database.updated == []
    assert database.synced == []
    assert provider.synced == []
