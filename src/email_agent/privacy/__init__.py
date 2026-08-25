"""Privacy controls applied before data leaves the application."""

from email_agent.privacy.redaction import SensitiveDataError, redact

__all__ = ["SensitiveDataError", "redact"]
