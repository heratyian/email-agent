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
  --template support \
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
uv run email-agent inbox --account you@gmail.com --snoozed
uv run email-agent inbox --account you@gmail.com --done
uv run email-agent inbox --account you@gmail.com --all
uv run email-agent process --account you@gmail.com
uv run email-agent done 1
uv run email-agent snooze 1 --until tomorrow
uv run email-agent reopen 1
uv run email-agent drafts --account you@gmail.com
uv run email-agent show 1
uv run email-agent draft 1
uv run email-agent approve 1
uv run email-agent monitor --account support@example.com --interval 300
```

`inbox` is the assistant's prioritized view of recent mail. Each message has familiar, user-facing attributes:

- **Category** says what the message is about.
- **Priority** (`urgent`, `normal`, or `low`) controls its inbox section.
- **Draft ready** means the assistant recommends replying and prepared a draft.

The default inbox shows messages that still need attention. `done LOCAL_ID` records that you handled one—possibly by phone, Slack, or another channel—without changing the email in the provider. `snooze LOCAL_ID --until ...` hides it until later, and `reopen LOCAL_ID` returns it to the open inbox. Use `--done`, `--snoozed`, or `--all` to change the view. Snooze accepts `tomorrow`, an ISO date, or an ISO datetime.

`done --delete-draft` also removes an untouched generated draft. Reviewed or approved drafts are always preserved. Read/unread status and internal processing bookkeeping remain separate and are not exposed as workflow concepts.

`approve` only changes local draft state. It does not send email. Raw email bodies are not persisted; `show` retrieves the current body from the mailbox using the stored provider ID.

## Architecture

`AccountConfig` contains a provider-specific mailbox connection and one `AgentConfig`. `MailProvider` normalizes Gmail and IMAP into the same models. `EmailPipeline` deterministically classifies, optionally drafts, applies safety checks, and persists workflow state. The model and prompts are selected from the account's nested agent configuration.

## Tests

```bash
uv run pytest
uv run ruff check .
```
