# Configuration

Email Agent loads private account configuration from `accounts.yaml` in the
project root. Each top-level key under `accounts` is the mailbox's canonical
email address.

Use the account generator instead of writing a new account from scratch:

```bash
uv run email-agent account add you@gmail.com \
  --provider gmail \
  --template personal \
  --model-provider openai \
  --model gpt-5.4-mini
```

The generator creates or updates `accounts.yaml` and creates an editable system
prompt under `prompts/`. Both locations are ignored by Git.

Validate configuration before connecting to a provider:

```bash
uv run email-agent account validate
```

## Account fields

Every account defines:

- `provider`: `gmail` or `imap`.
- `model`: the model provider, model name, temperature, and optional base URL.
- `system_prompt`: the prompt file used for classification and drafting.
- `categories`: category names and descriptions.

Gmail accounts also define paths for the OAuth client and token files. Keep these
files under the ignored `secrets/` directory. See [Gmail OAuth setup](gmail_oauth_setup.md).

IMAP accounts define:

- `imap_host` and optional `imap_port`.
- `username_env` and `password_env`, which name environment variables.
- Optional `category_action`, set to `copy` or `move`.

Store the IMAP username and password in `.env`. Store only their environment
variable names in `accounts.yaml`.

## Model providers

Supported model providers are `openai`, `ollama`, and `compatible`.

An Ollama model uses `OLLAMA_BASE_URL` when no `base_url` is configured. The
default is `http://localhost:11434`.

A compatible OpenAI-style provider requires `model.base_url`.

## Database location

Email Agent stores workflow metadata in `data/email_agent.db` by default. Set
`EMAIL_AGENT_DATABASE` in `.env` to use another path. A relative path is resolved
from the project root.

Raw email bodies are not stored in this database. Commands that display a message
retrieve its current body from the provider.

## System prompts

The system prompt defines account-specific behavior, context, tone, reply style,
and escalation judgment. Category descriptions belong in `accounts.yaml`; do not
duplicate the category taxonomy in the prompt.

## Categories

Category keys become Gmail labels or IMAP folder paths. See
[Categories and mailbox organization](categories.md) for naming rules and provider
behavior.
