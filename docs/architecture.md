# Architecture and safety boundaries

Email Agent is one Python application. The CLI and interactive shell share the
same application services and persistence layer.

## Package responsibilities

- `config/` loads and validates account configuration.
- `providers/` adapts Gmail and IMAP operations. The demo supplies a local
  synthetic provider through the same interface.
- `db/` owns SQLite persistence and migrations.
- `services/` owns provider-independent application workflows.
- `ai/` owns model construction, prompts, embeddings, and bounded structured model calls.                                                                                
- `search/` owns the LangGraph natural-language inbox search workflow.  
- `cli/` owns Typer declarations, the shell, logging, and terminal rendering.

`RuntimeFactory` provides workflow-specific constructors for inbox,
triage, drafting, and search runtimes. Each runtime includes only the
configured dependencies needed for that workflow. Services do not import CLI
code.

## Command flow

Typer commands and shell commands call deterministic handlers. Handlers coordinate
application services and return results for terminal rendering.

```text
Typer command ─┐
               ├── command handler ── application service
Shell command ─┘
```

Chat is an interface, not the architecture. The shell does not give a model a
provider object, database handle, credential, or write-capable tool.

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
The read-only `search` workflow searches the vector index but never writes to it.

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

Models perform two bounded tasks:

- Triage one message and its thread.
- Draft one suggested reply from a triage and thread.

Both tasks use validated structured output and no tools. Python owns provider
calls, loops, retries, persistence, category changes, and draft upload.

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
