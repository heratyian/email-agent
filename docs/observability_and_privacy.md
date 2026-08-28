# Observability and privacy

Email Agent provides workflow logging, exact model tracing, and optional LangSmith
tracing. These features have different privacy effects.

## Workflow logging

Add `-v` for workflow details or `-vv` for provider and timing diagnostics:

```bash
uv run email-agent -v inbox --account you@gmail.com
uv run email-agent inbox --account you@gmail.com -vv
```

The global flags may appear before or after a command and its options. Workflow
logs are written to standard error. They omit credentials, tokens, message bodies,
and draft contents.

Interactive terminals color logs by severity. Set `NO_COLOR=1` or redirect
standard error to disable ANSI color.

## Exact model tracing

Use `--trace-model` to print the complete payload sent to the model and the
structured response:

```bash
uv run email-agent triage --account you@gmail.com --trace-model
```

This output can contain complete system prompts, email messages, thread history,
drafting guidance, and generated drafts. Use it only in a trusted terminal. Do
not collect or share traced output unless the mailbox owner has approved the
retention and audience.

In the interactive shell, use `/trace-model on` and `/trace-model off`. The setting
lasts only for the current shell process.

## LangSmith tracing

LangChain model calls can be sent to LangSmith. Configure it in `.env`:

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=your-langsmith-api-key
LANGSMITH_PROJECT=email-agent
```

LangSmith tracing is independent of `--trace-model`. It sends traces to the
configured LangSmith workspace instead of printing exact model payloads in the
terminal. Traces can contain complete email content, system prompts, and generated
drafts.

Enable it only for a trusted workspace with suitable access and retention rules.
Set `LANGSMITH_TRACING=false` to disable it. To keep trace structure while hiding
model inputs and outputs, also set:

```dotenv
LANGSMITH_HIDE_INPUTS=true
LANGSMITH_HIDE_OUTPUTS=true
```

See the LangSmith documentation for
[observability](https://docs.langchain.com/langsmith/observability-quickstart) and
[input and output masking](https://docs.langchain.com/langsmith/mask-inputs-outputs).

## Credentials and stored data

- Keep `.env`, `accounts.yaml`, prompts, OAuth clients, and tokens out of Git.
- Never include credentials or tokens in model prompts.
- SQLite stores the plain-text bodies of messages synchronized by `inbox`.
- Protect and back up the database as mailbox data.
