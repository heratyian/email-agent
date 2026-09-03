from __future__ import annotations

from email_agent.assistant.models import AssistantIntentOutput, AssistantState

ASSISTANT_PROMPT = """Interpret one request to an email assistant.

Choose exactly one supported action: inbox, search, show, triage, draft, drafts, or upload.
- confirm and cancel are reserved for deterministic pending-action handling. Do not choose them.
- inbox synchronizes and lists newest mail. Preserve a requested limit.
- search finds existing synchronized and triaged mail. Put the complete search request in query.
- show requires a local message ID.
- triage may target a local message ID or all pending messages.
- draft may use a local message ID or a query that identifies one message. Put a
  target description such as "from Maya" in query and writing guidance in instruction.
- drafts lists local suggestions waiting for review.
- upload requires a local message ID and uploads an existing suggestion. It never sends email.
- unsupported covers sending, deleting, changing accounts, or unclear requests.

Resolve phrases such as "that message" or "that draft" only from the session context below.
Do not invent a local ID. Return unsupported if a required ID is unavailable or ambiguous.
Return only the required schema.
"""

CONFIRMATIONS = {"yes", "y", "confirm", "confirmed", "do it", "go ahead"}
CANCELLATIONS = {"no", "n", "cancel", "never mind", "nevermind", "stop"}


def interpret_assistant_request(planner, state: AssistantState) -> AssistantIntentOutput:
    """Interpret one turn, including deterministic pending-action responses."""
    normalized = state["user_input"].strip().casefold()
    if state.get("pending_action") and normalized in CONFIRMATIONS:
        return AssistantIntentOutput(action="confirm")
    if state.get("pending_action") and normalized in CANCELLATIONS:
        return AssistantIntentOutput(action="cancel")
    if state.get("pending_action"):
        return AssistantIntentOutput(
            action="unsupported",
            explanation=("Confirm or cancel the pending action before starting another request."),
        )
    context = (
        f"Recent message IDs: {state.get('last_message_ids') or 'none'}\n"
        f"Most recent draft message ID: {state.get('last_draft_message_id') or 'none'}\n"
        f"User request: {state['user_input']}"
    )
    return AssistantIntentOutput.model_validate(
        planner.invoke(f"{ASSISTANT_PROMPT}\n\nSession context:\n{context}")
    )


def assistant_route(intent: AssistantIntentOutput) -> str:
    """Return the graph route selected for one interpreted intent."""
    return {
        "triage": "prepare_triage",
        "upload": "prepare_upload",
    }.get(intent.action, intent.action)
