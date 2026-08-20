# Categories and mailbox organization

Categories are the single organization concept in Email Agent. Define them under
each account in `accounts.yaml`:

```yaml
categories:
  agent/action: Requires a reply, decision, or other action from me.
  agent/receipts: Purchases, invoices, and payment confirmations.
  agent/newsletters: Subscriptions and recurring publications.
  agent/reference: Useful information requiring no action.
```

The description teaches the classifier when to use the category. The key is the
exact Gmail label or IMAP folder path.

## Naming rules

A category key must be lowercase ASCII text. Each `/`-separated segment may use
letters, numbers, and underscores. Use `travel` for a top-level destination or
`agent/travel` for a nested destination.

Messages that do not clearly match a configured category remain Uncategorized.
They still receive a priority, summary, and reply recommendation, but Email Agent
does not apply a label or folder.

`accounts.yaml` is the only category-routing authority. Email Agent does not
translate obsolete category names.

## Gmail behavior

For Gmail, Email Agent applies the category as a label. Reclassification replaces
the previous agent-managed label. It leaves unrelated labels unchanged.

Gmail accounts must not set `category_action`. Label synchronization requires the
`gmail.modify` OAuth scope. Draft upload also requires `gmail.compose`. See
[Gmail OAuth setup](gmail_oauth_setup.md) when adding these permissions to an
existing token.

## IMAP behavior

IMAP accounts copy messages into category folders by default. The Inbox copy
remains in place. Safe replacement requires the server's standard `UIDPLUS`
capability so Email Agent can track the copied message.

Set `category_action: move` to remove categorized messages from Inbox. Move mode
also requires the server's `MOVE` capability. Email Agent refuses an unsafe
fallback when the required capability is unavailable.

Reclassification replaces the previous agent-managed folder copy. It leaves the
original Inbox message unchanged in copy mode.

## Change a taxonomy

After changing category keys or descriptions, reclassify and synchronize recent
stored messages:

```bash
uv run email-agent classify --account you@example.com --all
```

Review the proposed taxonomy before running this command. It can change Gmail
labels or IMAP category locations.
