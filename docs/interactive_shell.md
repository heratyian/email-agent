# Interactive shell

The interactive shell is the easiest way to use Email Agent manually:

```bash
uv run email-agent
```

The current shell uses deterministic slash commands. Natural-language routing is
planned for phase 3 but is not enabled yet. If text does not start with `/`, the
shell directs you to `/help`.

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

## Design status

The shell currently contains no natural-language router. The architectural reason
is recorded in [ADR 0001](adr/0001-deterministic-interactive-shell.md). Phase 3 is
defined in [the interactive shell specification](interactive_shell_spec.md).
