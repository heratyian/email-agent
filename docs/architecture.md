# Architecture and safety boundaries

Email Agent is one Python application. The CLI and interactive shell share the
same application services and persistence layer.

## Package responsibilities

- `config/` loads and validates account configuration.
- `providers/` adapts Gmail and IMAP operations.
- `db/` owns SQLite persistence and migrations.
- `services/` owns provider-independent application workflows.
- `ai/` owns model construction, prompts, and structured model calls.
- `cli/` owns Typer declarations, the shell, logging, and terminal rendering.

`RuntimeFactory` provides workflow-specific constructors for inbox,
classification, drafting, and search runtimes. Each runtime includes only the
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

Inbox synchronization, classification, and drafting are separate operations:

1. `inbox` fetches recent provider messages, assigns stable local IDs, and shows
   any existing classification or draft state. It does not invoke a model.
2. `classify` classifies unclassified messages with validated structured output,
   saves each result, and synchronizes the configured provider category.
3. `draft` generates a pending local suggestion for one classified message.
4. Draft upload creates a provider draft only after an explicit command.

Classification is completed locally only after provider synchronization succeeds.
A failed message remains eligible for a later run. Other messages in the same
batch continue processing.

Classification is idempotent at the account and provider-message boundary. Draft
generation is always explicit and may replace only a pending local suggestion.

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

- Classify one message and its thread.
- Draft one suggested reply from a classification and thread.

Both tasks use validated structured output and no tools. Python owns provider
calls, loops, retries, persistence, category changes, and draft upload.

## Storage

SQLite stores synchronized plain-text message bodies, message metadata,
classifications, draft suggestions, category synchronization state, and processing
runs. The database is a disposable local cache. After a schema change, delete
`data/email_agent.db` and run `inbox` to synchronize messages again. Deleting the
database also deletes local classifications and draft suggestions.

## Diagnostic data

Normal logs omit message and draft bodies. Exact payloads may be logged only when
model tracing is explicitly enabled. See
[Observability and privacy](observability_and_privacy.md).
