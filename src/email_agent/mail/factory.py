from pathlib import Path

from email_agent.config import AccountConfig
from email_agent.mail.gmail import GmailProvider
from email_agent.mail.imap import ImapProvider


def create_mail_provider(account_id: str, config: AccountConfig, root: Path):
    if config.provider == "gmail":
        return GmailProvider(account_id, config, root)
    return ImapProvider(account_id, config)
