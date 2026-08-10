# Email Agent

A profile-driven Python/LangChain email assistant that retrieves unread mail, classifies it with validated structured output, and generates reviewable drafts. It never sends email.

## Quick start

```bash
uv sync --extra dev
cp .env.example .env
```

### Initialize local configuration

Runtime mailbox configuration, agent profiles, and use-case-specific prompts are private and ignored by Git. Initialize them from the sanitized examples after cloning:

```bash
cp examples/accounts.yaml accounts.yaml
mkdir -p profiles prompts
cp -R examples/profiles/. profiles/
cp -R examples/prompts/. prompts/
```

Then edit `accounts.yaml`, the files under `profiles/`, and the corresponding prompt directories for your own mailboxes and behavior. Store credentials only in `.env` or the ignored `secrets/` directory—never in YAML profiles or prompt files.

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
