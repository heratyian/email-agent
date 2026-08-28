import logging
import os
import sys

LEVEL_STYLES = {
    logging.DEBUG: "90",
    logging.INFO: "36",
    logging.WARNING: "33",
    logging.ERROR: "31",
    logging.CRITICAL: "1;91",
}


class ColorLogFormatter(logging.Formatter):
    """Apply terminal-safe colors to complete log lines by severity."""

    def __init__(self, *, use_color: bool):
        super().__init__("%(levelname)s %(name)s: %(message)s")
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        if not self.use_color:
            return message
        code = LEVEL_STYLES.get(record.levelno)
        return f"\033[{code}m{message}\033[0m" if code else message


def configure_logging(verbosity: int) -> None:
    """Configure colored CLI diagnostics."""
    level = logging.DEBUG if verbosity >= 2 else logging.INFO if verbosity == 1 else logging.WARNING
    logger = logging.getLogger("email_agent")
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    use_color = (
        bool(getattr(handler.stream, "isatty", lambda: False)()) and "NO_COLOR" not in os.environ
    )
    handler.setFormatter(ColorLogFormatter(use_color=use_color))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def warn_model_tracing() -> None:
    """Ensure and announce logging for sensitive exact model payloads."""
    logger = logging.getLogger("email_agent")
    logger.setLevel(min(logger.level, logging.INFO))
    logging.getLogger(__name__).warning(
        "Model tracing is enabled; logs may contain complete email and draft content"
    )
