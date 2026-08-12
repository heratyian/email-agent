"""Process-wide diagnostic switches shared outside the CLI."""

_trace_model = False


def configure_model_tracing(enabled: bool) -> None:
    """Enable explicit, sensitive model payload tracing for this process."""
    global _trace_model
    _trace_model = enabled


def model_tracing_enabled() -> bool:
    """Return whether exact model payloads may be written to logs."""
    return _trace_model
