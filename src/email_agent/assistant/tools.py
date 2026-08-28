from __future__ import annotations

from langchain_core.tools import StructuredTool


def make_assistant_tools(application):
    """Expose existing application operations as constrained LangChain tools."""

    def fetch_inbox(account_id: str, limit: int = 20):
        """Synchronize and return the newest messages for one account."""
        return application.run_inbox(account_id, limit)

    def search_inbox(account_id: str, query: str):
        """Search the existing local triage index without changing it."""
        return application.search_inbox(account_id, query)

    def show_message(account_id: str, message_id: int):
        """Return one message and its stored triage by local ID."""
        if application.message_account(message_id) != account_id:
            raise LookupError(f"message {message_id} does not belong to account {account_id}")
        return application.show_message(message_id)

    def triage_messages(account_id: str, message_id: int | None = None):
        """Triage messages and synchronize their configured mailbox labels."""
        return application.triage(account_id, message_id=message_id)

    def generate_draft(account_id: str, message_id: int, instruction: str | None = None):
        """Generate a local reply suggestion for one message."""
        if application.message_account(message_id) != account_id:
            raise LookupError(f"message {message_id} does not belong to account {account_id}")
        return application.generate_draft(message_id, instruction)

    def list_drafts(account_id: str):
        """Return pending local reply suggestions for one account."""
        return application.list_drafts(account_id)

    def upload_draft(account_id: str, message_id: int):
        """Upload one local suggestion to mailbox drafts without sending it."""
        if application.message_account(message_id) != account_id:
            raise LookupError(f"message {message_id} does not belong to account {account_id}")
        return application.upload_draft(message_id)

    functions = (
        fetch_inbox,
        search_inbox,
        show_message,
        triage_messages,
        generate_draft,
        list_drafts,
        upload_draft,
    )
    return {function.__name__: StructuredTool.from_function(function) for function in functions}
