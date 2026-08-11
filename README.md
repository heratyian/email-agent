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

This creates or updates the ignored `accounts.yaml` and generates one editable system prompt at `prompts/<email-slug>/system.md`. Account-specific behavior, context, tone, and escalation judgment belong in that file; categories remain simple descriptions in YAML. Users address the mailbox by its actual email address. IMAP credentials stay in `.env`; YAML contains only their environment-variable names. Gmail OAuth files stay in the ignored `secrets/` directory.

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
uv run email-agent organize --account you@gmail.com --dry-run
uv run email-agent organize --account you@gmail.com
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

### Categories and mailbox organization

Categories are the single organization concept. Define them under an account's nested `agent` configuration; the description teaches the classifier when to use each category:

```yaml
categories:
  action: Requires a reply, decision, or other action from me.
  receipts: Purchases, invoices, and payment confirmations.
  newsletters: Subscriptions and recurring publications.
  reference: Useful information requiring no action.
organization:
  enabled: true
  prefix: Email Agent
```

`inbox` previews the selected category without changing the mailbox. `process` and `monitor` synchronize it to a lowercase path such as `email agent/receipts`: Gmail applies a user label, while IMAP creates the folder and copies the message into it without removing the Inbox copy. Set `organization.enabled: false` to keep categories local only.

Use `organize` to backfill categories already stored locally without reclassifying messages or creating drafts. Start with `--dry-run`; successful syncs are recorded locally so later runs skip them and IMAP copies are not duplicated. `--force` deliberately retries all matching messages and can therefore duplicate IMAP copies.

After changing the configured category taxonomy, stored messages may refer to categories that no longer exist. Use `organize --reclassify-unknown` to reclassify only those messages with the current taxonomy, or `--reclassify-all` when category meanings changed substantially. Reclassification preserves each message's open, snoozed, or done state. Combined with `--dry-run`, the model is called for a preview but neither the local classification nor mailbox is changed.

Enabling Gmail organization requires the `gmail.modify` OAuth scope. Existing Gmail users must remove or move their configured token file once and run a command again to grant the expanded permission; see [Gmail OAuth Setup](docs/gmail_oauth_setup.md).

`approve` only changes local draft state. It does not send email. Raw email bodies are not persisted; `show` retrieves the current body from the mailbox using the stored provider ID.

## Architecture

`AccountConfig` contains a provider-specific mailbox connection and one `AgentConfig`. `MailProvider` normalizes Gmail and IMAP into the same models. `EmailPipeline` deterministically classifies, optionally drafts, applies safety checks, and persists workflow state. Each nested agent selects its model, one system prompt, and simple category taxonomy.

## Tests

```bash
uv run pytest
uv run ruff check .
```
