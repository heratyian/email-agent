from pathlib import Path

from email_agent.config import AccountConfig
from email_agent.providers.gmail import GmailProvider
from email_agent.providers.imap import ImapProvider


def create_mail_provider(account_id: str, config: AccountConfig, root: Path):
    if config.provider == "gmail":
        return GmailProvider(account_id, config, root)
    if config.provider == "imap":
        return ImapProvider(account_id, config)
    from email_agent.demo import DemoProvider

    return DemoProvider(account_id, root)
