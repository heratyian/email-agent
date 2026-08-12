"""External mailbox provider adapters."""

from email_agent.providers.base import MailProvider
from email_agent.providers.factory import create_mail_provider

__all__ = ["MailProvider", "create_mail_provider"]
