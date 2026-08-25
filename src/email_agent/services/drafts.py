import logging

from email_agent.ai.agents import EmailAgents
from email_agent.config import Settings
from email_agent.db import Draft, Message
from email_agent.providers import create_mail_provider
from email_agent.providers.base import MailProvider
from email_agent.providers.models import EmailMessage

logger = logging.getLogger(__name__)


def reply_subject(original_subject: str) -> str:
    """Return one stable reply subject without stacking ``Re:`` prefixes."""
    subject = original_subject.strip() or "(no subject)"
    return subject if subject.casefold().startswith("re:") else f"Re: {subject}"


class DraftService:
    """Generate and synchronize draft suggestions with mailbox providers."""

    def source_message(self, message_id: int, settings: Settings) -> EmailMessage:
        """Retrieve the original mailbox message for one local draft."""
        message_row = Message.get_or_none(Message.id == message_id)
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
    ) -> Draft:
        """Generate or replace a local reply suggestion for one tracked message."""
        message_row = Message.get_or_none(Message.id == message_id)
        if not message_row:
            raise LookupError("message not found")
        classification = message_row.classification_value()
        if classification is None:
            raise LookupError("message has not been classified")
        source = provider.get_message(
            message_row.provider_uid, message_row.provider_mailbox
        )
        thread = provider.get_thread(
            message_row.provider_uid, message_row.provider_mailbox
        )
        if instruction:
            reply = agents.draft(source, thread, classification, instruction=instruction)
        else:
            reply = agents.draft(source, thread, classification)
        draft = Draft.replace_generated(message_row, reply)
        logger.info("Generated draft suggestion for local message %s", message_id)
        return draft

    def upload(self, message_id: int, settings: Settings) -> str:
        """Upload one suggestion to its mailbox Drafts folder without sending."""
        draft = Draft.latest_for_message(message_id)
        if draft is None:
            raise LookupError("draft not found")
        source = self.source_message(message_id, settings)
        account = settings.account(source.account_id)
        provider = create_mail_provider(source.account_id, account, settings.root)
        provider_id = provider.upload_draft(
            source,
            recipient=draft.recipient,
            subject=reply_subject(source.subject),
            body=draft.body,
        )
        if not Draft.change_generated_status(message_id, "uploaded"):
            raise LookupError("draft not found")
        logger.info("Uploaded draft for local message %s", message_id)
        return provider_id
