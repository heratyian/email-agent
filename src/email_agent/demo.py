from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import yaml
from faker import Faker

from email_agent.config import Settings
from email_agent.persistence import Message, initialize_database
from email_agent.providers.base import CategorySyncState
from email_agent.providers.models import EmailMessage, EmailThread

DEMO_ACCOUNT_ID = "demo@example.test"
DEMO_MAILBOX_SIZE = 40
DEMO_MAILBOX_PATH = Path("data/demo_mailbox.json")
DEMO_PROMPT_DIRECTORY = "prompts/demo"


@dataclass(frozen=True)
class DemoInstallation:
    """Describe the synthetic account prepared for a demo session."""

    account_created: bool
    mailbox_created: bool
    message_count: int


class DemoProvider:
    """Read a persistent synthetic mailbox through the provider interface."""

    def __init__(self, account_id: str, root: Path):
        self.account_id = account_id
        self.mailbox_path = root / DEMO_MAILBOX_PATH

    def get_messages(self, limit: int = 20, *, unread_only: bool = False) -> list[EmailMessage]:
        """Return the newest messages without changing the synthetic mailbox."""
        messages = self._mailbox_messages()
        return sorted(messages, key=lambda message: message.received_at, reverse=True)[:limit]

    def get_message(self, message_id: str, mailbox: str = "INBOX") -> EmailMessage:
        row = Message.find_email(self.account_id, message_id)
        if row is None:
            raise LookupError("demo message not found; run inbox to synchronize it")
        return row.to_email()

    def get_thread(self, message_id: str, mailbox: str = "INBOX") -> EmailThread:
        return EmailThread(messages=[])

    def upload_draft(
        self,
        source: EmailMessage,
        *,
        recipient: str,
        subject: str,
        body: str,
    ) -> str:
        return f"demo-draft-{source.provider_id}"

    def mark_processed(self, message_id: str) -> None:
        return None

    def sync_category(
        self,
        message_id: str,
        destination: str | None,
        source_mailbox: str = "INBOX",
        previous: CategorySyncState | None = None,
    ) -> None:
        return None

    def category_sync_key(self, destination: str) -> str:
        return destination

    def _mailbox_messages(self) -> list[EmailMessage]:
        if not self.mailbox_path.is_file():
            raise RuntimeError("demo mailbox is missing; run 'email-agent demo' to create it")
        return [
            EmailMessage.model_validate(values)
            for values in json.loads(self.mailbox_path.read_text())
        ]


def install_demo(root: Path) -> DemoInstallation:
    """Create a persistent demo account and synthetic mailbox when missing."""
    root = root.resolve()
    account_created = _install_account(root)
    initialize_database(Settings(root).database_path)
    mailbox_created = _install_mailbox(root)
    return DemoInstallation(account_created, mailbox_created, DEMO_MAILBOX_SIZE)


def _install_account(root: Path) -> bool:
    accounts_path = root / "accounts.yaml"
    raw = yaml.safe_load(accounts_path.read_text()) if accounts_path.is_file() else None
    raw = raw or {"accounts": {}}
    if not isinstance(raw, dict) or not isinstance(raw.get("accounts"), dict):
        raise TypeError("accounts.yaml must contain an 'accounts' mapping")
    existing = raw["accounts"].get(DEMO_ACCOUNT_ID)
    if existing is not None and existing.get("provider") != "demo":
        raise ValueError(f"Account '{DEMO_ACCOUNT_ID}' already exists and is not a demo account")

    prompt_root = root / DEMO_PROMPT_DIRECTORY
    prompt_root.mkdir(parents=True, exist_ok=True)
    (prompt_root / "triage.md").write_text(
        "Prioritize security alerts, deadlines, and messages that require a response. "
        "Treat receipts and newsletters as low-risk unless their content indicates otherwise."
    )
    (prompt_root / "draft.md").write_text(
        "Write concise, professional, and friendly replies. Do not invent availability, "
        "approvals, prices, deadlines, or commitments."
        "Just use my name (Demo Person) in the signature."
    )
    raw["accounts"][DEMO_ACCOUNT_ID] = {
        "provider": "demo",
        "model": {"provider": "openai", "model": "gpt-5.4-mini"},
        "triage_prompt": f"{DEMO_PROMPT_DIRECTORY}/triage.md",
        "draft_prompt": f"{DEMO_PROMPT_DIRECTORY}/draft.md",
    }
    accounts_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return existing is None


def _install_mailbox(root: Path) -> bool:
    mailbox_path = root / DEMO_MAILBOX_PATH
    if mailbox_path.is_file():
        return False
    mailbox_path.parent.mkdir(parents=True, exist_ok=True)
    messages = _fake_messages(DEMO_MAILBOX_SIZE)
    mailbox_path.write_text(
        json.dumps([message.model_dump(mode="json") for message in messages], indent=2)
    )
    return True


def _fake_messages(count: int) -> list[EmailMessage]:
    fake = Faker()
    now = datetime.now(UTC)
    return [
        _fake_message(fake, index, now - timedelta(hours=index * 6 + fake.random_int(0, 5)))
        for index in range(count)
    ]


def _fake_message(fake: Faker, index: int, received_at: datetime) -> EmailMessage:
    scenario = index % 6
    if scenario == 0:
        sender = fake.name()
        subject = "Interview availability next week"
        body = "Could you meet Tuesday or Wednesday afternoon for a technical interview?"
    elif scenario == 1:
        sender = "Account Security"
        subject = f"New sign-in from {fake.city()}"
        body = "Review a new sign-in from an unfamiliar device and location."
    elif scenario == 2:
        sender = fake.name()
        subject = f"Approval needed: {fake.catch_phrase()} proposal"
        body = "Please review the attached proposal and confirm whether the team should proceed."
    elif scenario == 3:
        sender = fake.company()
        subject = f"Payment receipt #{fake.random_int(10000, 99999)}"
        body = (
            f"We received your payment of ${fake.random_int(100, 900)}.00. No action is required."
        )
    elif scenario == 4:
        sender = f"{fake.word().title()} Engineering Weekly"
        subject = "This week in reliable systems"
        body = "Five articles about queues, retries, and distributed systems."
    else:
        sender = f"{fake.city()} Technology Community"
        subject = "Local engineering meetup next Thursday"
        body = "Join local engineers for talks and networking next Thursday evening."
    address = re.sub(r"[^a-z0-9]+", ".", sender.casefold()).strip(".")
    return EmailMessage(
        provider_id=str(uuid4()),
        account_id=DEMO_ACCOUNT_ID,
        from_address=f"{address}@example.test",
        from_name=sender,
        subject=subject,
        text_body=body,
        received_at=received_at,
    )
