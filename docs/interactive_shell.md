# Interactive shell

Start the shell with the configured account, or create the synthetic demo:

```bash
uv run email-agent
uv run email-agent demo
```

The shell accepts constrained natural-language requests and deterministic slash
commands. Both call the same application services.

```text
> fetch my five newest messages
> find messages about the interview that need a reply
> draft a concise reply to message 203
> upload that draft
Upload the suggestion for message #203 to mailbox drafts? [yes/no]
```

Triage and mailbox draft upload require a separate confirmation turn. Read-only
operations and local draft generation run immediately. The assistant cannot send
email, delete data, or change accounts.

## Slash commands

Type `/help` for the current command reference. The primary workflow is:

```text
/inbox [limit]
/triage [LOCAL_ID]
/search QUERY
/show LOCAL_ID
/draft LOCAL_ID [instruction]
/drafts
/review
/upload LOCAL_ID
```

`/inbox` synchronizes messages without invoking a model. `/triage` saves
structured analysis, synchronizes the configured category, and updates the search
index. `/draft` creates a local suggestion. `/upload` creates a provider draft but
never sends it.

Local message IDs belong to one account. If several accounts are configured, the
shell asks which one to use. `/account` changes the active account and clears
conversational context.

The shell remembers recent result IDs and the latest local draft. References such
as “that message” work only when the target is unambiguous. Use explicit IDs and
slash commands for scripts or exact operations.

Use `/verbose` for workflow diagnostics and `/trace-model` for complete model
inputs and outputs. Read [Observability and privacy](observability_and_privacy.md)
before tracing mailbox content.
