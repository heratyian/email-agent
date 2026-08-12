# Email Agent

An account-configured Python/LangChain email assistant that retrieves mail, classifies it with validated structured output, and generates reviewable drafts. It never sends email.

## Quick start

```bash
uv sync --extra dev
cp .env.example .env
```

### Create an account

Each email address is one complete mailbox configuration. Create a Gmail account with the personal template:

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

`process` handles each message independently. A model, mailbox, or storage error is reported for that message while the rest of the batch continues. Classification and draft results are saved before mailbox changes, and a message is marked processed only after synchronization succeeds; failed messages remain eligible for the next run without creating duplicate drafts.

### Categories and mailbox organization

Categories are the single organization concept. Define them directly under an account; the description teaches the classifier when to use each category:

```yaml
categories:
  agent/action: Requires a reply, decision, or other action from me.
  agent/receipts: Purchases, invoices, and payment confirmations.
  agent/newsletters: Subscriptions and recurring publications.
  agent/reference: Useful information requiring no action.
```

The category key is the exact lowercase Gmail label or IMAP folder path. Use `travel` for a top-level destination or `agent/travel` when you want a prefix. `inbox` previews the selected category without changing the mailbox. `process` and `monitor` apply it automatically: Gmail uses a label, while IMAP creates the folder hierarchy and copies the message without removing the Inbox copy. Reclassification replaces the previous agent-managed label or folder copy; unrelated labels and the original Inbox message are left alone.

IMAP accounts default to copying messages into category folders. Safe replacement requires the server's standard `UIDPLUS` support so the agent can track the copied message. Set `category_action: move` on the account to remove categorized messages from Inbox instead; move mode additionally requires the server's `MOVE` capability. The agent will refuse unsafe fallback behavior. Gmail accounts must omit this setting because labels do not copy messages.

Messages that do not clearly fit a configured category remain `Uncategorized`. They still receive a priority, summary, reply recommendation, and attention state, but no Gmail label or IMAP folder is applied. `organize` reports them separately rather than treating them as failures.

Use `organize` to backfill categories already stored locally without reclassifying messages or creating drafts. Start with `--dry-run`; successful syncs are recorded locally so later runs skip them and IMAP copies are not duplicated. `--force` deliberately retries all matching messages and can therefore duplicate IMAP copies.

After changing the configured category taxonomy, stored messages may refer to categories that no longer exist. Use `organize --reclassify-unknown` to reclassify only those messages with the current taxonomy, or `--reclassify-all` when category meanings changed substantially. Reclassification preserves each message's open, snoozed, or done state. Combined with `--dry-run`, the model is called for a preview but neither the local classification nor mailbox is changed.

Enabling Gmail organization requires the `gmail.modify` OAuth scope. Existing Gmail users must remove or move their configured token file once and run a command again to grant the expanded permission; see [Gmail OAuth Setup](docs/gmail_oauth_setup.md).

`approve` only changes local draft state. It does not send email. Raw email bodies are not persisted; `show` retrieves the current body from the mailbox using the stored provider ID.

## Architecture

`AccountConfig` contains the mailbox connection, model, system prompt, and categories in one flat structure. `MailProvider` normalizes Gmail and IMAP into the same models. Small application services handle accounts, inbox triage, processing, organization, messages, and drafts. `RuntimeFactory` builds the typed dependencies for account commands, while the CLI only parses options and renders results. Sending is not implemented, so generated replies always remain local drafts for review.

## Tests

```bash
uv run pytest
uv run ruff check .
```
