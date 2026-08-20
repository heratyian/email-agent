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

`RuntimeFactory` builds the configured account, provider, database, model, and
bounded AI operations for one account. Services do not import CLI code.

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

## Message processing sequence

Each message is processed independently:

1. Fetch the message and thread from the provider.
2. Classify the message with validated structured output.
3. Generate a reply suggestion when classification recommends one.
4. Save the classification and pending draft locally.
5. Synchronize the configured category with the provider.
6. Mark the provider message as processed.
7. Mark local processing complete and record the run.

The local result is saved before mailbox changes. Local processing is completed
only after provider synchronization succeeds. A failed message remains eligible
for a later run. Other messages in the same batch continue processing.

The workflow is idempotent at the account and provider-message boundary. A retry
does not create duplicate pending drafts.

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

## Storage and migrations

SQLite stores message metadata, classifications, draft suggestions, category
synchronization state, and processing runs. It does not store raw email bodies.

Ordered migrations run automatically at startup in transactions and are recorded
in `schema_migrations`. Back up `data/email_agent.db` before an upgrade when it
contains important local suggestions or history.

## Diagnostic data

Normal logs omit message and draft bodies. Exact payloads may be logged only when
model tracing is explicitly enabled. See
[Observability and privacy](observability_and_privacy.md).
