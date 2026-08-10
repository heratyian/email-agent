from datetime import UTC, datetime

from email_agent.config import Settings
from email_agent.models import DraftReply, EmailClassification, EmailMessage, EmailThread
from email_agent.pipeline import EmailPipeline
from email_agent.storage import Database


class FakeProvider:
    def __init__(self, message):
        self.message = message

    def get_new_messages(self, limit=20):
        return [self.message]

    def get_thread(self, message_id):
        return EmailThread(messages=[self.message])

    def mark_processed(self, message_id):
        pass


class FakeAgents:
    def classify(self, message, thread):
        return EmailClassification(
            category="support_request",
            requires_reply=True,
            priority="normal",
            intent="login_problem",
            summary="Cannot log in",
            confidence=0.95,
        )

    def draft(self, message, thread, classification):
        return DraftReply(
            recipient=message.from_address,
            subject="Re: Login",
            body="Please share the error message.\n\nThanks,\nReceipt AI Support",
            reasoning_summary="More diagnostic detail is needed.",
            confidence=0.9,
        )


def test_pipeline_classifies_and_stores_local_draft(tmp_path):
    message = EmailMessage(
        provider_id="abc",
        account_id="receipt_ai_support",
        from_address="customer@example.com",
        subject="Login",
        text_body="I cannot log in",
        received_at=datetime.now(UTC),
    )
    profile = Settings().profile("receipt_ai_support")
    db = Database(tmp_path / "test.db")
    results = EmailPipeline(profile, FakeProvider(message), FakeAgents(), db).process()
    assert results[0].classification.intent == "login_problem"
    assert results[0].draft.status == "generated"
    assert len(db.list_drafts()) == 1
    assert EmailPipeline(profile, FakeProvider(message), FakeAgents(), db).process() == []
