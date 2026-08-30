# Architecture and safety boundaries

Email Agent is one Python application. The CLI and interactive shell share the
same application services and persistence layer.

## Package responsibilities

- `config/` loads and validates account configuration.
- `providers/` adapts Gmail and IMAP operations. The demo supplies a local
  synthetic provider through the same interface.
- `accounts/` owns account configuration generation and validation.
- `inbox/` owns inbox synchronization and message retrieval.
- `triage/` owns triage output, prompting, model interaction, and workflow logic.
- `drafting/` owns draft output, prompting, model interaction, and workflow logic.
- `search/` owns planned vector retrieval and exact SQL filtering.
- `assistant/` owns typed intents, LangChain tool adapters, session context,
  confirmation state, and the conversational LangGraph.
- `llm/` owns shared model construction, embeddings, prompt utilities, and tracing.
- `persistence/` owns SQLite models, connection management, and migrations.
- `cli/` owns Typer declarations, the shell, logging, and terminal rendering.

`application.py` is the terminal-independent façade shared by the CLI and
conversational tools. Feature packages contain their own workflow and model-facing
code instead of depending on generic technical service or AI packages.

`RuntimeFactory` provides workflow-specific constructors for inbox,
triage, drafting, search, and assistant runtimes. Each runtime includes only the
configured dependencies needed for that workflow. Feature workflows do not
import CLI code.

## Command flow

Typer commands and shell commands call the deterministic `EmailApplication`
façade. It coordinates feature workflows and returns results for terminal
rendering.

```text
Typer command ─┐
               ├── EmailApplication ── feature workflow
Shell command ─┘
```

Plain text is interpreted by a structured model call and routed through an
explicit graph. The graph invokes narrow LangChain tools backed by the same
application façade as slash commands. The model never receives a provider object,
database handle, or credential. Triage and provider draft upload require a separate
confirmation turn; no send-email tool exists.

## Message workflow

Inbox synchronization, triage, and drafting are separate operations:

1. `inbox` fetches recent provider messages, assigns stable local IDs, and shows
   any existing triage or draft state. It does not invoke a model.
2. `triage` processes untriaged messages with validated structured output,
   saves each result, synchronizes the configured provider category, and updates
   the account's triage-summary vector index.
3. `draft` generates a pending local suggestion for one triaged message.
4. Draft upload creates a provider draft only after an explicit command.

The one-to-one triage row is the source of truth that model triage completed.
Provider category synchronization has separate pending state on that row. A
failed provider update is retried by a later `triage` run without invoking the
model again. Other messages in the same batch continue processing.

Triage is idempotent at the account and provider-message boundary. Draft
generation is always explicit and may replace only a pending local suggestion.
The read-only `search` workflow plans one semantic query and optional exact
filters. Chroma returns candidate message IDs. SQLite applies the filters. Search never writes to either store.

## Draft lifecycle

A generated reply is a pending local suggestion. Regeneration may replace only a
pending suggestion. It must not alter a draft that has already been uploaded to
the mailbox.

Upload creates a provider draft associated with the original message or thread.
It removes the suggestion from the local review queue. Email Agent has no send
operation.

Deletion dismisses a pending local suggestion. It does not delete an uploaded
provider draft.

## Account boundaries

Local messages and drafts retain their account identity. Account-scoped commands
validate that a requested message belongs to the active account before provider
access or mailbox changes.

Provider identifiers are interpreted only with their stored account and mailbox
location. Runtime construction always begins with a validated account key.

## Model boundary

Models perform bounded tasks:

- Triage one message and its thread.
- Draft one suggested reply from a triage and thread.
- Plan a semantic query and explicit filters for read-only search.
- Select one supported conversational intent.

Model-produced triage, drafts, search plans, and intents use validated
structured output. Python owns provider calls, loops, retries, persistence,
category changes, confirmations, and draft upload.

## Storage

SQLite stores synchronized plain-text message bodies, message metadata,
triages, draft suggestions, category synchronization state, and processing
runs. The database is a disposable local cache. After a schema change, delete
`data/email_agent.db` and run `inbox` to synchronize messages again. Deleting the
database also deletes local triages and draft suggestions.

## Diagnostic data

Normal logs omit message and draft bodies. Exact payloads may be logged only when
model tracing is explicitly enabled. See
[Observability and privacy](observability_and_privacy.md).
