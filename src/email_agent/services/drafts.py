import logging

from email_agent.ai.agents import EmailAgents
from email_agent.ai.models import EmailClassification
from email_agent.config import Settings
from email_agent.db import Database, StoredDraft
from email_agent.models import EmailMessage
from email_agent.providers import create_mail_provider
from email_agent.providers.base import MailProvider

logger = logging.getLogger(__name__)


def reply_subject(original_subject: str) -> str:
    """Return one stable reply subject without stacking ``Re:`` prefixes."""
    subject = original_subject.strip() or "(no subject)"
    return subject if subject.casefold().startswith("re:") else f"Re: {subject}"


class DraftService:
    """List, retrieve, upload, and discard local draft suggestions."""

    def __init__(self, database: Database):
        self.database = database

    def list(self, account_id: str | None = None) -> list[StoredDraft]:
        rows = self.database.list_drafts(account_id)
        logger.info("Found %d local draft(s)", len(rows))
        logger.debug("Draft list filter: account=%s", account_id or "all")
        return rows

    def get(self, message_id: int) -> StoredDraft:
        row = self.database.get_draft(message_id)
        if not row:
            raise LookupError("draft not found")
        logger.info("Loaded draft for local message %s", message_id)
        logger.debug("Draft status for local message %s: %s", message_id, row.status)
        return row

    def source_message(self, message_id: int, settings: Settings) -> EmailMessage:
        """Retrieve the original mailbox message for one local draft."""
        message_row = self.database.show_message(message_id)
        if not message_row:
            raise LookupError("message not found")
        account_id = message_row.account_id
        account = settings.account(account_id)
        provider = create_mail_provider(account_id, account, settings.root)
        return provider.get_message(
            message_row.provider_uid, message_row.provider_mailbox
        )

    def generate(
        self,
        message_id: int,
        provider: MailProvider,
        agents: EmailAgents,
        instruction: str | None = None,
    ) -> StoredDraft:
        """Generate or replace a local reply suggestion for one tracked message."""
        message_row = self.database.show_message(message_id)
        if not message_row:
            raise LookupError("message not found")
        if not message_row.classification:
            raise LookupError("message has not been classified")
        source = provider.get_message(
            message_row.provider_uid, message_row.provider_mailbox
        )
        thread = provider.get_thread(
            message_row.provider_uid, message_row.provider_mailbox
        )
        classification = EmailClassification.model_validate(message_row.classification)
        if instruction:
            reply = agents.draft(source, thread, classification, instruction=instruction)
        else:
            reply = agents.draft(source, thread, classification)
        draft = self.database.replace_generated_draft(
            message_id,
            message_row.account_id,
            message_row.provider_message_id,
            reply,
        )
        logger.info("Generated draft suggestion for local message %s", message_id)
        return draft

    def upload(self, message_id: int, settings: Settings) -> str:
        """Upload one suggestion to its mailbox Drafts folder without sending."""
        draft = self.get(message_id)
        source = self.source_message(message_id, settings)
        account = settings.account(source.account_id)
        provider = create_mail_provider(source.account_id, account, settings.root)
        provider_id = provider.upload_draft(
            source,
            recipient=draft.recipient,
            subject=reply_subject(source.subject),
            body=draft.body,
        )
        if not self.database.mark_draft_uploaded(message_id):
            raise LookupError("draft not found")
        logger.info("Uploaded draft for local message %s", message_id)
        return provider_id

    def delete(self, message_id: int) -> None:
        """Remove one generated suggestion from the review queue."""
        if not self.database.reject_draft(message_id):
            raise LookupError("draft not found")
        logger.info("Deleted draft suggestion for local message %s", message_id)
