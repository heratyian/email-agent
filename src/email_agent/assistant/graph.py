from __future__ import annotations

from langgraph.graph import END, StateGraph

from email_agent.assistant.interpreter import assistant_route, interpret_assistant_request
from email_agent.assistant.models import (
    AssistantIntentOutput,
    AssistantState,
    AssistantTurn,
    PendingAction,
)
from email_agent.assistant.tools import make_assistant_tools


class AssistantConversation:
    """Stateful, constrained LangGraph conversation over application tools."""

    def __init__(self, account_id: str, model, application):
        self.account_id = account_id
        self.planner = model.with_structured_output(AssistantIntentOutput)
        self.tools = make_assistant_tools(application)
        self.graph = self._build_graph()
        # TODO: refactor state into langraph checkpointing,
        # so that the conversation can be resumed after a restart
        self.state: AssistantState = {
            "account_id": account_id,
            "pending_action": None,
            "last_message_ids": [],
            "last_draft_message_id": None,
        }

    def invoke(self, user_input: str) -> AssistantTurn:
        """Run one conversational turn and retain only useful session context."""
        result = self.graph.invoke(
            {**self.state, "user_input": user_input},
            config={
                "tags": ["email-agent", "conversational-assistant"],
                "metadata": {
                    "workflow": "conversational-email-assistant",
                    "account_id": self.account_id,
                },
            },
        )
        self.state = {
            "account_id": self.account_id,
            "pending_action": result.get("pending_action"),
            "last_message_ids": result.get("last_message_ids", []),
            "last_draft_message_id": result.get("last_draft_message_id"),
        }
        return result["turn"]

    def _build_graph(self):
        graph = StateGraph(AssistantState)
        graph.add_node("interpret", self._interpret)
        graph.add_node("inbox", self._inbox)
        graph.add_node("search", self._search)
        graph.add_node("show", self._show)
        graph.add_node("prepare_triage", self._prepare_triage)
        graph.add_node("draft", self._draft)
        graph.add_node("drafts", self._drafts)
        graph.add_node("prepare_upload", self._prepare_upload)
        graph.add_node("confirm", self._confirm)
        graph.add_node("cancel", self._cancel)
        graph.add_node("unsupported", self._unsupported)
        graph.set_entry_point("interpret")
        graph.add_conditional_edges("interpret", self._route)
        for node in (
            "inbox",
            "search",
            "show",
            "prepare_triage",
            "draft",
            "drafts",
            "prepare_upload",
            "confirm",
            "cancel",
            "unsupported",
        ):
            graph.add_edge(node, END)
        return graph.compile()

    def _interpret(self, state: AssistantState) -> dict:
        return {"intent": interpret_assistant_request(self.planner, state)}

    @staticmethod
    def _route(state: AssistantState) -> str:
        return assistant_route(state["intent"])

    def _inbox(self, state: AssistantState) -> dict:
        items = self.tools["fetch_inbox"].invoke(
            {"account_id": state["account_id"], "limit": state["intent"].limit}
        )
        return {
            "turn": AssistantTurn(kind="inbox", payload=items),
            "last_message_ids": [item.local_id for item in items],
        }

    def _search(self, state: AssistantState) -> dict:
        query = state["intent"].query or state["user_input"]
        response = self.tools["search_inbox"].invoke(
            {"account_id": state["account_id"], "query": query}
        )
        return {
            "turn": AssistantTurn(kind="search", payload=response),
            "last_message_ids": [item.message_id for item in response.results],
        }

    def _show(self, state: AssistantState) -> dict:
        message_id = self._message_id(state)
        details = self.tools["show_message"].invoke(
            {"account_id": state["account_id"], "message_id": message_id}
        )
        return {
            "turn": AssistantTurn(kind="message", payload=details),
            "last_message_ids": [message_id],
        }

    def _prepare_triage(self, state: AssistantState) -> dict:
        pending = PendingAction(action="triage", message_id=state["intent"].message_id)
        return {
            "pending_action": pending,
            "turn": AssistantTurn(kind="text", message=pending.describe()),
        }

    def _draft(self, state: AssistantState) -> dict:
        message_id = self._draft_message_id(state)
        draft = self.tools["generate_draft"].invoke(
            {
                "account_id": state["account_id"],
                "message_id": message_id,
                "instruction": state["intent"].instruction,
            }
        )
        return {
            "turn": AssistantTurn(kind="draft", payload=draft),
            "last_message_ids": [message_id],
            "last_draft_message_id": message_id,
        }

    def _drafts(self, state: AssistantState) -> dict:
        drafts = self.tools["list_drafts"].invoke({"account_id": state["account_id"]})
        return {
            "turn": AssistantTurn(kind="drafts", payload=drafts),
            "last_draft_message_id": drafts[0].message_id if len(drafts) == 1 else None,
        }

    def _prepare_upload(self, state: AssistantState) -> dict:
        message_id = self._message_id(state, draft=True)
        pending = PendingAction(action="upload", message_id=message_id)
        return {
            "pending_action": pending,
            "turn": AssistantTurn(kind="text", message=pending.describe()),
        }

    def _confirm(self, state: AssistantState) -> dict:
        pending = state.get("pending_action")
        if pending is None:
            return {"turn": AssistantTurn(kind="text", message="There is nothing to confirm.")}
        if pending.action == "triage":
            results = self.tools["triage_messages"].invoke(
                {"account_id": state["account_id"], "message_id": pending.message_id}
            )
            return {
                "pending_action": None,
                "turn": AssistantTurn(kind="triage", payload=results),
            }
        self.tools["upload_draft"].invoke(
            {"account_id": state["account_id"], "message_id": pending.message_id}
        )
        return {
            "pending_action": None,
            "turn": AssistantTurn(
                kind="text",
                message="Uploaded to mailbox drafts. No email was sent.",
            ),
        }

    @staticmethod
    def _cancel(state: AssistantState) -> dict:
        return {
            "pending_action": None,
            "turn": AssistantTurn(kind="text", message="Cancelled."),
        }

    @staticmethod
    def _unsupported(state: AssistantState) -> dict:
        explanation = state["intent"].explanation
        message = explanation or (
            "I can fetch, search, show, triage, draft, list drafts, and upload drafts. "
            "Include a local message ID when the target is ambiguous."
        )
        return {"turn": AssistantTurn(kind="text", message=message)}

    @staticmethod
    def _message_id(state: AssistantState, *, draft: bool = False) -> int:
        explicit = state["intent"].message_id
        if explicit is not None:
            return explicit
        if draft and state.get("last_draft_message_id") is not None:
            return state["last_draft_message_id"]
        recent = state.get("last_message_ids", [])
        if len(recent) == 1:
            return recent[0]
        raise ValueError("Include a local message ID; the target is ambiguous.")

    def _draft_message_id(self, state: AssistantState) -> int:
        """Resolve a draft target from context or one unambiguous search result."""
        try:
            return self._message_id(state)
        except ValueError:
            query = state["intent"].query
            if not query:
                raise
        response = self.tools["search_inbox"].invoke(
            {"account_id": state["account_id"], "query": query}
        )
        if len(response.results) != 1:
            raise ValueError(
                "The draft target is ambiguous. Search first, then include a local message ID."
            )
        return response.results[0].message_id
