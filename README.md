# Email Agent

An account-configured Python/LangChain email assistant that retrieves mail, classifies it with validated structured output, and generates reviewable drafts. It never sends email.

## Quick start

```bash
uv sync --extra dev
cp .env.example .env
```

### Create an account

Each email address has one mailbox connection and one nested agent configuration. Create a Gmail account and personal agent together:

```bash
uv run email-agent account init you@gmail.com \
  --provider gmail \
  --template personal \
  --model-provider openai \
  --model gpt-5.4-mini
```

For an IMAP customer-support mailbox:

```bash
uv run email-agent account init support@example.com \
  --provider imap \
  --imap-host imap.example.com \
  --template customer_support \
  --model-provider ollama \
  --model qwen3
```

This creates or updates the ignored `accounts.yaml` and generates editable prompts under `prompts/<email-slug>/`. Connection settings and agent behavior remain separate internally, but users address the mailbox by its actual email address. IMAP credentials stay in `.env`; YAML contains only their environment-variable names. Gmail OAuth files stay in the ignored `secrets/` directory.

Validate before connecting:

```bash
uv run email-agent config validate
uv run email-agent accounts
```

### Email setup

- See [Gmail OAuth Setup](docs/gmail_oauth_setup.md) for Gmail.

### CLI commands

```bash
uv run email-agent inbox --account you@gmail.com
uv run email-agent inbox --account you@gmail.com --unread
uv run email-agent inbox --account you@gmail.com --unprocessed
uv run email-agent process --account you@gmail.com
uv run email-agent drafts --account you@gmail.com
uv run email-agent show 1
uv run email-agent draft 1
uv run email-agent approve 1
uv run email-agent monitor --account support@example.com --interval 300
```

`inbox` behaves like a normal mailbox view: it shows recent Inbox messages regardless of provider read state or local processing state, sorts newest-first, groups by classification, and labels each message `NEW`, `TRIAGED`, or `PROCESSED`.

- `NEW`: classified for the first time during the current `inbox` command.
- `TRIAGED`: classified previously but not handled by `process` or `monitor`.
- `PROCESSED`: full agent processing completed; a local draft was saved when required.

These workflow labels are independent of Gmail or IMAP read/unread state. Use `--unread` or `--unprocessed` for narrower operational views.

`approve` only changes local draft state. It does not send email. Raw email bodies are not persisted; `show` retrieves the current body from the mailbox using the stored provider ID.

## Architecture

`AccountConfig` contains a provider-specific mailbox connection and one `AgentConfig`. `MailProvider` normalizes Gmail and IMAP into the same models. `EmailPipeline` deterministically classifies, optionally drafts, applies safety checks, and persists workflow state. The model and prompts are selected from the account's nested agent configuration.

## Tests

```bash
uv run pytest
uv run ruff check .
```
