from __future__ import annotations

from collections.abc import Iterable

from preserve import PreserveConfig, Scrubber, ScrubResult


class SensitiveDataError(ValueError):
    """Raised when content is too sensitive to send to a model."""


CUSTOM_PATTERNS = [
    {
        "name": "credential_assignment",
        "regex": (
            r"(?i)\b(?:password|passwd|api[_ -]?key|access[_ -]?token|auth[_ -]?token)"
            r"\s*[:=]\s*\S+"
        ),
        "replacement_type": "CREDENTIAL",
    },
    {
        "name": "authorization_bearer",
        "regex": r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}",
        "replacement_type": "CREDENTIAL",
    },
    {
        "name": "private_key",
        "regex": r"(?i)-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        "replacement_type": "CREDENTIAL",
    },
    {
        "name": "sensitive_url",
        "regex": (
            r"(?i)https?://[^\s<>]+[?&](?:token|code|key|signature|sig|auth|password)="
            r"[^\s<>]+"
        ),
        "replacement_type": "SENSITIVE_URL",
    },
    {
        "name": "north_american_phone",
        "regex": r"(?<!\w)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\w)",
        "replacement_type": "PHONE",
    },
]


def redact(text: str, *, known_names: Iterable[str] = ()) -> ScrubResult:
    """Pseudonymize text with a reversible mapping managed by preserve-pii."""
    scrubber = Scrubber(
        PreserveConfig(
            custom_patterns=CUSTOM_PATTERNS,
            known_names=list(known_names),
            use_allowlist=False,
            use_name_scorer=False,
            use_normalcy_scanner=False,
        )
    )
    result = scrubber.scrub(text)
    if any(match.replacement_type == "CREDENTIAL" for match in result.detections):
        raise SensitiveDataError("Possible credential found; content was not sent to the model")
    return result
