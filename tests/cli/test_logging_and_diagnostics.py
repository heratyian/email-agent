import logging

from email_agent.ai.agents import EmailAgents
from email_agent.cli.logging import ColorLogFormatter, configure_logging, warn_model_tracing
from email_agent.diagnostics import configure_model_tracing, model_tracing_enabled


def test_verbose_levels_filter_application_logs(capsys):
    logger = logging.getLogger("email_agent.test")

    configure_logging(1)
    logger.info("workflow detail")
    logger.debug("diagnostic detail")
    assert "workflow detail" in capsys.readouterr().err

    configure_logging(2)
    logger.debug("diagnostic detail")
    assert "diagnostic detail" in capsys.readouterr().err

    configure_logging(0)
    logger.info("hidden detail")
    assert "hidden detail" not in capsys.readouterr().err


def test_color_formatter_styles_terminal_output_only():
    record = logging.LogRecord("email_agent.test", logging.INFO, __file__, 1, "hello", (), None)

    colored = ColorLogFormatter(use_color=True).format(record)
    plain = ColorLogFormatter(use_color=False).format(record)

    assert "\x1b[" in colored
    assert "INFO email_agent.test: hello" in colored
    assert plain == "INFO email_agent.test: hello"


def test_model_tracing_is_explicit_and_emits_warning(capsys):
    configure_logging(0)
    configure_model_tracing(True)
    warn_model_tracing()

    assert model_tracing_enabled() is True
    assert "may contain complete email" in capsys.readouterr().err

    configure_model_tracing(False)
    assert model_tracing_enabled() is False


def test_model_trace_logs_exact_payload_only_when_enabled(capsys):
    configure_logging(0)
    configure_model_tracing(False)
    EmailAgents._trace_payload("classification", "system secret", "email secret")
    assert "email secret" not in capsys.readouterr().err

    configure_model_tracing(True)
    warn_model_tracing()
    capsys.readouterr()
    EmailAgents._trace_payload("classification", "system secret", "email secret")
    output = capsys.readouterr().err
    assert "system secret" in output
    assert "email secret" in output
    configure_model_tracing(False)
