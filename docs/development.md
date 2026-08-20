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
- Make schema changes through ordered, transactional migrations.

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

Add schema changes as the next ordered migration in
`src/email_agent/db/migrations.py`. Migrations must upgrade an existing database
in place and run in a transaction. Add a focused migration test that starts from
the previous schema state.

Do not assume that a user has a fresh database.

## Documentation style

Use Simplified Technical English. Lead with the user task or safety consequence.
Keep the README short and link to focused documents for reference detail.

Treat CLI `--help` and shell `/help` as the current command reference.
Documentation should use representative examples instead of copying every option
and help string.
