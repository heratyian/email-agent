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
uv run email-agent account add you@gmail.com \
  --provider gmail \
  --template personal \
  --model-provider openai \
  --model gpt-5.4-mini
```

For an IMAP customer-support mailbox:

```bash
uv run email-agent account add support@example.com \
  --provider imap \
  --imap-host imap.example.com \
  --template support \
  --model-provider ollama \
  --model qwen3
```

This creates or updates the ignored `accounts.yaml` and generates one editable system prompt at `prompts/<email-slug>/system.md`. Account-specific behavior, context, tone, and escalation judgment belong in that file; categories remain simple descriptions in YAML. Users address the mailbox by its actual email address. IMAP credentials stay in `.env`; YAML contains only their environment-variable names. Gmail OAuth files stay in the ignored `secrets/` directory.

Validate before connecting:

```bash
uv run email-agent account validate
uv run email-agent account
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
uv run email-agent inbox --account you@gmail.com --dry-run
uv run email-agent inbox --account you@gmail.com --reorganize
uv run email-agent inbox --account you@gmail.com --watch
uv run email-agent message done 1
uv run email-agent message snooze 1 --until tomorrow
uv run email-agent message reopen 1
uv run email-agent message show 1
uv run email-agent drafts --account you@gmail.com
uv run email-agent drafts show 1
uv run email-agent drafts review --account you@gmail.com
uv run email-agent drafts upload 1
uv run email-agent drafts delete 1
```

Add `-v` anywhere in the command for workflow details, or `-vv` for diagnostic provider and timing information:

```bash
uv run email-agent -v inbox --account you@gmail.com
uv run email-agent inbox --account you@gmail.com --dry-run -vv
```

Verbose logs are written to stderr, colored by severity in interactive terminals, and omit credentials, tokens, message bodies, and draft contents. Set `NO_COLOR=1` or redirect stderr to disable ANSI color.

To inspect the exact payload sent to the configured model, add `--trace-model` anywhere in the command. This logs complete system prompts, email/thread content, and structured model responses to stderr, so use it only in a trusted terminal:

```bash
uv run email-agent inbox --account you@gmail.com --trace-model
```

`-v`, `-vv`, and `--trace-model` are global and may appear before the command, after a nested command, or after command-specific options. They can also be combined:

```bash
uv run email-agent account add --help -vv
uv run email-agent inbox --account you@gmail.com -v --trace-model
```

`inbox` is the everyday command: it processes new mail, applies configured labels or folders, prepares appropriate drafts, and then displays the prioritized view. When only one account is configured, `--account` is optional. Each message has familiar, user-facing attributes:

- **Category** says what the message is about.
- **Priority** (`urgent`, `normal`, or `low`) controls its inbox section.
- **Draft ready** means the assistant recommends replying and prepared a draft.

The default inbox shows messages that still need attention. `message done LOCAL_ID` records that you handled one—possibly by phone, Slack, or another channel—without changing the email in the provider. `message snooze LOCAL_ID --until ...` hides it until later, and `message reopen LOCAL_ID` returns it to the open inbox. Use `--done`, `--snoozed`, or `--all` to change the view. Snooze accepts `tomorrow`, an ISO date, or an ISO datetime.

`message done --delete-draft` also removes an untouched generated draft. Uploaded drafts are always preserved in the mailbox. Read/unread status and internal processing bookkeeping remain separate and are not exposed as workflow concepts.

`inbox` handles each message independently. A model, mailbox, or storage error is reported for that message while the rest of the batch continues. Classification and draft results are saved before mailbox changes, and a message is marked processed only after synchronization succeeds; failed messages remain eligible for the next run without creating duplicate drafts. Add `--watch` to keep checking, `--dry-run` to classify without changing the mailbox or generating drafts, or `--reorganize` after changing category definitions.

### Categories and mailbox organization

Categories are the single organization concept. Define them directly under an account; the description teaches the classifier when to use each category:

```yaml
categories:
  agent/action: Requires a reply, decision, or other action from me.
  agent/receipts: Purchases, invoices, and payment confirmations.
  agent/newsletters: Subscriptions and recurring publications.
  agent/reference: Useful information requiring no action.
```

The category key is the exact lowercase Gmail label or IMAP folder path. Use `travel` for a top-level destination or `agent/travel` when you want a prefix. The normal `inbox` workflow applies it automatically: Gmail uses a label, while IMAP creates the folder hierarchy and copies the message without removing the Inbox copy. Reclassification replaces the previous agent-managed label or folder copy; unrelated labels and the original Inbox message are left alone.

IMAP accounts default to copying messages into category folders. Safe replacement requires the server's standard `UIDPLUS` support so the agent can track the copied message. Set `category_action: move` on the account to remove categorized messages from Inbox instead; move mode additionally requires the server's `MOVE` capability. The agent will refuse unsafe fallback behavior. Gmail accounts must omit this setting because labels do not copy messages.

Messages that do not clearly fit a configured category remain `Uncategorized`. They still receive a priority, summary, reply recommendation, and attention state, but no Gmail label or IMAP folder is applied.

`accounts.yaml` is the only category-routing authority; obsolete names are never translated implicitly. After changing the configured taxonomy, use `inbox --reorganize` to reclassify and resync recent stored messages. Reclassification preserves each message's open, snoozed, or done state.

Gmail organization and draft upload require the `gmail.modify` and `gmail.compose` OAuth scopes. Existing Gmail users must remove or move their configured token file once and run a command again to grant expanded permission; see [Gmail OAuth Setup](docs/gmail_oauth_setup.md).

`drafts review` cycles through suggestions. Upload saves a real draft in Gmail or the IMAP Drafts folder and removes it from the local review queue; it never sends email. Delete dismisses the local suggestion without changing the mailbox. Raw email bodies are not persisted; `message show` retrieves the current body from the mailbox using the stored provider ID.

## Architecture

The code is grouped by responsibility: `config/` defines and loads account configuration, `providers/` contains Gmail and IMAP adapters, `db/` owns SQLite persistence and migrations, `services/` implements application workflows, `ai/` owns model construction, prompts, and LangChain interactions, and `cli/` contains the Typer application, terminal logging, parsing, and rendering. Process-wide model-trace state lives in `diagnostics.py` so AI code does not depend on CLI formatting. `RuntimeFactory` builds typed dependencies for account commands, while `cli/app.py` declares commands and delegates their work. Shared email models and category rules remain outside AI because providers, storage, and services also use them. Sending is not implemented, so generated replies always remain local drafts for review.

SQLite schema changes are applied automatically at startup as ordered, transactional migrations recorded in `schema_migrations`. Existing v0.1 databases are upgraded in place; back up `data/email_agent.db` before upgrading if it contains important local drafts.

## Tests

```bash
uv run pytest
uv run ruff check .
```
