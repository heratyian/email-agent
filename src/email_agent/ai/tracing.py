import json
import logging

from email_agent.diagnostics import model_tracing_enabled

logger = logging.getLogger(__name__)


def trace_payload(task: str, system: str, user: str) -> None:
    """Log an exact model request when explicit model tracing is enabled."""
    if model_tracing_enabled():
        logger.info("MODEL TRACE %s system prompt:\n%s", task, system)
        logger.info("MODEL TRACE %s user prompt:\n%s", task, user)


def trace_response(task: str, response: dict) -> None:
    """Log an exact structured response when model tracing is enabled."""
    if model_tracing_enabled():
        logger.info("MODEL TRACE %s structured response:\n%s", task, json.dumps(response, indent=2))
