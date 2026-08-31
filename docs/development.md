# Development and evaluation

Email Agent uses Python 3.11 or later and `uv`.

```bash
uv sync --extra dev
cp .env.example .env
```

Keep `.env`, `accounts.yaml`, prompts, OAuth clients, and tokens out of version
control. Follow [AGENTS.md](../AGENTS.md) for repository conventions.

## Checks

Run a focused test while developing. Before finishing, run:

```bash
uv run ruff check .
uv run pytest
git diff --check
```

Peewee models and `src/email_agent/persistence/schema.sql` must change together.
The database is a disposable cache, but deleting it also deletes local triages
and draft suggestions.

## LangSmith evaluations

Set `LANGSMITH_API_KEY`. To assign datasets to the Email Agent application in
LangSmith, also set the resource-tag value printed by:

```bash
uv run python scripts/langsmith_application_tag_value_id.py
```

```dotenv
LANGSMITH_APPLICATION_TAG_VALUE_ID=the-printed-uuid
```

Run an evaluation against the checked-in synthetic `personal` profile:

```bash
uv run email-agent evaluate triage
uv run email-agent evaluate drafting
uv run email-agent evaluate search
uv run email-agent evaluate assistant
```

| Evaluation | What it measures |
| --- | --- |
| Triage | Category, reply requirement, priority, and escalation |
| Drafting | Recipient, escalation, length, grounding, instructions, tone, and safety |
| Search | Plan accuracy, retrieval precision and recall, first result, and exclusions |
| Assistant | Action, route, message reference, arguments, and confirmation policy |

Search evaluation creates a temporary SQLite database and Chroma index and runs
the production search pipeline. Assistant evaluation isolates natural-language
routing; it does not execute the graph's tools.

LangSmith creates a dataset on the first run and reuses it later. Existing
datasets are not overwritten. After changing checked-in examples, use a new name:

```bash
uv run email-agent evaluate search --dataset search-personal-v2
```

Keep evaluation examples synthetic. Convert real failures into sanitized
regression cases with the corrected expected behavior.
