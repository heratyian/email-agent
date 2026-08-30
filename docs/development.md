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
uv run pytest tests/triage/test_workflow.py
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

Update the Peewee models and `src/email_agent/persistence/schema.sql` together. Delete
`data/email_agent.db` after a schema change so the application creates the current
schema. The email provider remains the source of truth, but deleting the database
also deletes local triages and draft suggestions.

## Documentation style

Use Simplified Technical English. Lead with the user task or safety consequence.
Keep the README short and link to focused documents for reference detail.

Treat CLI `--help` and shell `/help` as the current command reference.
Documentation should use representative examples instead of copying every option
and help string.

## Triage evaluation

Set `LANGSMITH_API_KEY` and `LANGSMITH_APPLICATION_TAG_VALUE_ID`, then run the
checked-in synthetic triage dataset against the self-contained `personal`
evaluation profile:

```bash
uv run python scripts/langsmith_application_tag_value_id.py
```

Copy the printed UUID to `LANGSMITH_APPLICATION_TAG_VALUE_ID` in `.env`. The
script reads the `Application: email-agent` resource-tag value from the current
LangSmith workspace.

```bash
uv run email-agent evaluate triage --profile personal
```

The command does not load `accounts.yaml`, connect to a mailbox, or initialize the
email database. The profile owns its model configuration, prompts, categories,
and synthetic examples under
`src/email_agent/evaluations/profiles/personal/`.

The first run creates the `triage-personal` dataset in LangSmith and
assigns it to the configured application. Later runs reuse that dataset and create
a new experiment. The evaluation reports exact-match scores for category, reply
requirement, priority, and escalation requirement. Use a new dataset name after
changing examples:

```bash
uv run email-agent evaluate triage \
  --profile personal \
  --dataset triage-personal-v2
```

Copy the complete profile directory to create another evaluation profile. Keep
personally identifiable mailbox content out of checked-in evaluation data.

## Drafting evaluation

Run the checked-in drafting scenarios against the same self-contained profile:

```bash
uv run email-agent evaluate drafting --profile personal
```

The first run creates the `drafting-personal` dataset and assigns it to the
configured LangSmith application. The evaluation checks recipient, escalation,
and length deterministically. One structured model-judge call reports separate
scores for required content, grounding, instruction following, tone, and safety.

Drafting examples define required and forbidden behavior instead of one exact
reply. Keep examples synthetic. When a real draft fails, add a sanitized
reconstruction with the corrected criteria and retain it as a regression case.

## Inbox search evaluation

Run the production hybrid search pipeline against a fixed synthetic mailbox:

```bash
uv run email-agent evaluate search --profile personal
```

The command creates a temporary SQLite database and Chroma index, seeds the
checked-in triaged corpus, and runs each query through the production pipeline.
It uses the profile's chat and embedding model, so it requires the model API key.
The temporary data is deleted after the blocking evaluation completes.

The LangSmith experiment reports planner field accuracy, retrieval precision and
recall, first-result accuracy, and excluded-result accuracy. Message keys in the
dataset are stable across database runs. The evaluation runs one example at a
time because all examples share the same temporary local index.

Add sanitized regression cases to `search_examples.json`. Add a message to
`search_corpus.json` only when the scenario needs evidence that is not already in
the corpus. Use a new dataset name after changing examples because existing
LangSmith datasets are not overwritten automatically.

## Assistant orchestration evaluation

Run the assistant router against synthetic shell requests:

```bash
uv run email-agent evaluate assistant --profile personal
```

The `assistant-personal` dataset covers action selection, message references,
arguments, confirmations, cancellations, and unsupported requests. It does not
execute tools or access a mailbox, so failures stay isolated to routing.

The LangSmith experiment reports action, graph route, message reference,
argument, and confirmation-policy accuracy separately. Add sanitized routing
regressions to `assistant_examples.json`. Use a new dataset name after changing
examples because existing LangSmith datasets are not overwritten automatically.
