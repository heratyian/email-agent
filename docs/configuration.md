# Gmail and IMAP setup

The demo needs no mailbox credentials. Use this guide only to connect a real
account. Private account configuration is stored in the ignored `accounts.yaml`
file.

## Gmail

Create an account from the personal template:

```bash
uv run email-agent account add you@gmail.com \
  --provider gmail \
  --template personal \
  --model-provider openai \
  --model gpt-5.4-mini
```

Complete [Gmail OAuth setup](gmail_oauth_setup.md), then validate and connect:

```bash
uv run email-agent account validate
uv run email-agent inbox --account you@gmail.com
```

Gmail uses `gmail.modify` to synchronize category labels and `gmail.compose` to
create drafts. Email Agent does not request permission to send email.

## IMAP

Create an account and name the environment variables that hold its credentials:

```bash
uv run email-agent account add you@example.com \
  --provider imap \
  --template personal \
  --model-provider openai \
  --model gpt-5.4-mini \
  --imap-host imap.example.com
```

The generator writes environment-variable names to `accounts.yaml`. Put their
credential values in `.env`:

```dotenv
YOU_EXAMPLE_COM_USERNAME=you@example.com
YOU_EXAMPLE_COM_PASSWORD=your-app-password
```

Use the environment-variable names in the account configuration:

```yaml
imap_host: imap.example.com
username_env: YOU_EXAMPLE_COM_USERNAME
password_env: YOU_EXAMPLE_COM_PASSWORD
```

IMAP copies categorized messages into folders by default. Copy mode requires
`UIDPLUS`. Optional move mode requires `MOVE`; the application does not use an
unsafe fallback when either capability is missing.

## Account configuration

Each account specifies:

- its mailbox provider;
- its chat model;
- account-specific triage and drafting prompt files; and
- category names and descriptions.

The account generator creates editable prompts under the ignored `prompts/`
directory. Category keys become Gmail labels or IMAP folder paths. See
[Categories and mailbox organization](categories.md).

Supported model providers are `openai`, `ollama`, and OpenAI-compatible APIs.
Ollama uses `OLLAMA_BASE_URL` when no model base URL is configured.

Run `uv run email-agent account validate` after changing configuration. Use
`uv run email-agent --help` for the complete account command reference.

## Local data

SQLite stores synchronized message bodies and workflow state in
`data/email_agent.db`. Chroma stores the triage-summary search index under
`data/`. Set `EMAIL_AGENT_DATABASE` in `.env` to change the SQLite path.

Treat both stores as private mailbox data. Deleting them also deletes local
triages and draft suggestions.
