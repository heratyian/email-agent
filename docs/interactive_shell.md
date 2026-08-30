# Interactive shell

The interactive shell is the easiest way to use Email Agent manually:

```bash
uv run email-agent
```

The shell accepts constrained natural-language requests and deterministic slash
commands. Both interfaces call the same application handlers.

```text
> fetch my five newest messages
> find messages about the interview that need a reply
> draft a concise reply to message 203
> upload that draft
Upload the suggestion for message #203 to mailbox drafts? [yes/no]
```

Triage and mailbox draft upload require a separate confirmation turn. Read-only
operations and local draft generation run immediately. The assistant cannot send
email, delete data, or change accounts; use explicit slash commands for other
supported shell operations.

Triage requires confirmation because the current workflow also synchronizes the
configured Gmail label or IMAP folder. Generating a draft is local; uploading it
changes the mailbox.

## Select an account

If one account is configured, the shell selects it automatically. If several
accounts are configured, select an account by number or email address:

```text
Choose an account:
1. personal@example.com
2. support@example.com

> 2
```

The selected account remains active for the shell session. Use `/account` to list
accounts and `/account EMAIL` to switch accounts.

## Commands

Type `/help` in the shell for the current command reference.

```text
/inbox [limit]
/triage [LOCAL_ID]
/show LOCAL_ID
/draft LOCAL_ID [instruction]
/drafts
/review
/upload LOCAL_ID
/delete-draft LOCAL_ID
/account [EMAIL]
/verbose [off|on|debug]
/trace-model [off|on]
/help
/quit
```

### Synchronize the inbox

`/inbox` fetches recent messages for the active account and shows them newest
first. It assigns stable local IDs, but it does not use AI, change mailbox labels,
or prepare replies. Pass a positive limit to change the default batch size:

```text
> /inbox 10
```

The `DRAFT?` column shows `READY` for a local suggestion waiting for review and
`UPLOADED` after a suggestion has been copied to the mailbox Drafts folder.
Rejected suggestions leave the column empty. Uploaded drafts do not return to the
local review queue.

### Triage messages

`/triage` processes all stored messages that do not have completed
triage. Run `/inbox` first to synchronize recent messages. Triage
saves category, priority, and reply requirements, then synchronizes the configured
Gmail label or IMAP category folder:

```text
> /triage
```

Pass a local ID to triage or retriage one message:

```text
> /triage 203
```

### Show a message

`/show LOCAL_ID` retrieves the original message from its provider and displays
its stored triage:

```text
> /show 203
```

Local message IDs belong to one account. The shell refuses to use a message that
does not belong to the active account.

### Generate a draft suggestion

`/draft LOCAL_ID` generates or regenerates a pending local suggestion from an
existing triage. Add one-time guidance after the ID:

```text
> /draft 203 Politely decline and keep the reply under 50 words.
```

The guidance applies only to that generation. Regeneration replaces only the
pending local suggestion. It does not change an uploaded mailbox draft.

### Review draft suggestions

Use `/drafts` to list pending suggestions and `/review` to review them. During
review, choose whether to upload, delete, keep, or stop reviewing.

`/upload LOCAL_ID` uploads a suggestion to the provider's Drafts folder. It never
sends the message. `/delete-draft LOCAL_ID` removes the pending local suggestion
without changing an uploaded mailbox draft.

These slash commands are explicit authorization for their documented effects.
Conversational triage and upload requests are not authorization until confirmed.

### Change diagnostics

`/verbose on` shows workflow information. `/verbose debug` adds provider and
timing diagnostics. `/verbose off` restores normal output.

`/trace-model on` logs complete model inputs and outputs for the current shell
session. The shell displays a privacy warning when tracing is enabled. Read
[Observability and privacy](observability_and_privacy.md) before using it.

## Exit and errors

Use `/quit`, `/exit`, `quit`, or end-of-file to exit. An invalid command or an
operation failure returns to the prompt. Press Ctrl-C during an operation to
cancel it. At an empty prompt, press Ctrl-C twice to exit.

## Conversational state

The shell remembers result IDs and the most recently generated draft for the
current session. References such as "that message" resolve only when the target
is unambiguous. Switching accounts clears this context. Slash commands remain the
most predictable interface for scripts and exact operations.
