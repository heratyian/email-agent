from email_agent.triage.models import TriageOutput


def category_destination(account, triage: TriageOutput) -> str | None:
    """Return the provider-neutral label or folder for a configured category."""
    key = triage.category
    if key is None:
        return None
    if key not in account.categories:
        matches = [
            candidate for candidate in account.categories if candidate.rsplit("/", 1)[-1] == key
        ]
        if len(matches) == 1:
            key = matches[0]
    if key not in account.categories:
        raise KeyError(f"unknown category {triage.category!r}")
    return key
