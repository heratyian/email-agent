# Email Agent

A profile-driven Python/LangChain email assistant that retrieves unread mail, classifies it with validated structured output, and generates reviewable drafts. It never sends email.

## Quick start

```bash
uv sync --extra dev
cp .env.example .env
```

### Initialize local configuration

Runtime mailbox configuration, generated agent profiles, and use-case-specific prompts are private and ignored by Git. Generate a Gmail account configuration with:

```bash
uv run email-agent account init personal_gmail --provider gmail
```

This creates the ignored `accounts.yaml` and points OAuth files at `secrets/personal_gmail_credentials.json` and `secrets/personal_gmail_token.json`. For an IMAP mailbox:

```bash
uv run email-agent account init customer_support \
  --provider imap \
  --email support@example.com \
  --imap-host imap.example.com
```

IMAP credential values remain in `.env`; the generated YAML contains only their environment-variable names. After creating an account, generate a profile and its editable prompts from either the `personal` or `customer_support` template:

```bash
uv run email-agent profile init personal \
  --account personal_gmail \
  --template personal \
  --provider openai \
  --model gpt-5.4-mini
```

For a support mailbox:

```bash
uv run email-agent profile init customer_support \
  --account customer_support \
  --template customer_support \
  --provider ollama \
  --model qwen3
```

The generator requires an explicit model provider (`openai`, `ollama`, or `compatible`) and model name; templates do not choose a model. It creates `profiles/<name>.yaml` and `prompts/<name>/`, and refuses to overwrite existing files unless `--force` is supplied. Edit the generated profile and prompts for your use case. Store credentials only in `.env` or the ignored `secrets/` directory—never in YAML profiles or prompt files.

Validate the resulting configuration before connecting to a mailbox:

```bash
uv run email-agent config validate
uv run email-agent accounts
uv run email-agent process --profile receipt_ai_support --limit 10
```

### LLM Model Setup

The default profiles use Ollama (`qwen3`). Run Ollama locally or change `model.provider` and `model.model` in a profile to `openai` and an available model.

### Email Setup

- See [Gmail OAuth Setup](docs/gmail_oauth_setup.md) for Gmail.

### CLI Commands

```bash
uv run email-agent inbox --profile personal
uv run email-agent process --profile personal
uv run email-agent drafts --profile personal
uv run email-agent show 1
uv run email-agent draft 1
uv run email-agent approve 1
uv run email-agent monitor --profile receipt_ai_support --interval 300
```

`approve` marks a local draft approved for later review; it does not send or expose a send capability. IMAP drafts remain local in SQLite. Gmail native draft creation is intentionally deferred until the user explicitly saves one in a later milestone.

Configuration lives in `profiles/`; all prompt content lives in `prompts/`. Credentials are read only from environment variables or ignored OAuth files. Raw email bodies are not logged and only minimal message metadata is persisted.

## Architecture

`MailProvider` normalizes Gmail and IMAP into the same models. `EmailPipeline` deterministically retrieves a message, asks separate LangChain agents for classification and drafting, applies safety checks, and persists the result. The model is selected by profile through one factory.

## Tests

```bash
uv run pytest
uv run ruff check .
```
