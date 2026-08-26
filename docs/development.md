# Development

Email Agent uses Python 3.11 or later, `uv` for dependency and command execution,
Ruff for linting, pytest for tests, Typer for commands, Pydantic for validated
data, and SQLite through the application database layer.

## Set up the project

```bash
uv sync --extra dev
cp .env.example .env
```

Private runtime files such as `.env`, `accounts.yaml`, prompts, OAuth clients, and
tokens must remain outside version control.

## Repository conventions

Follow [AGENTS.md](../AGENTS.md) for the complete development doctrine. In
particular:

- Use descriptive domain names and explicit Python.
- Keep side effects in deterministic services.
- Keep services independent of CLI presentation.
- Reuse `RuntimeFactory` for runtime construction.
- Preserve account boundaries and per-message failure isolation.
- Do not expose providers, database handles, credentials, or write-capable tools
  to models.
- Treat the SQLite database as a disposable local cache.

## Run focused checks

Run the narrowest useful test while developing:

```bash
uv run pytest tests/services/test_processing_inbox_and_routing.py
uv run pytest tests/cli/test_shell.py
```

Before considering a change complete, run:

```bash
uv run ruff check .
uv run pytest
git diff --check
```

Review the final diff for unnecessary dependencies, configuration, abstractions,
comments, and files.

## Database changes

Update the Peewee models and `src/email_agent/db/schema.sql` together. Delete
`data/email_agent.db` after a schema change so the application creates the current
schema. The email provider remains the source of truth, but deleting the database
also deletes local classifications and draft suggestions.

## Documentation style

Use Simplified Technical English. Lead with the user task or safety consequence.
Keep the README short and link to focused documents for reference detail.

Treat CLI `--help` and shell `/help` as the current command reference.
Documentation should use representative examples instead of copying every option
and help string.

## Classification evaluation

Set `LANGSMITH_API_KEY` and run the checked-in synthetic classification dataset
against the self-contained `personal` evaluation profile:

```bash
uv run email-agent evaluate classification --profile personal
```

The command does not load `accounts.yaml`, connect to a mailbox, or initialize the
email database. The profile owns its model configuration, prompts, categories,
and synthetic examples under
`src/email_agent/evaluations/profiles/personal/`.

The first run creates the `email-agent-classification-personal` dataset in
LangSmith. Later runs reuse that dataset and create a new experiment. The
evaluation reports exact-match scores for category, reply requirement, priority,
and escalation requirement. Use a new dataset name after changing examples:

```bash
uv run email-agent evaluate classification \
  --profile personal \
  --dataset email-agent-classification-personal-v2
```

Copy the complete profile directory to create another evaluation profile. Keep
personally identifiable mailbox content out of checked-in evaluation data.
