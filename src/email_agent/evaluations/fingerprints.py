# evaluations/fingerprints.py

import hashlib


def prompt_hash(prompt: str) -> str:
    """Return a short, stable fingerprint for a rendered prompt."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]