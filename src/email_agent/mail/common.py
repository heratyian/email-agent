from __future__ import annotations

from bs4 import BeautifulSoup


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    return BeautifulSoup(value, "html.parser").get_text("\n", strip=True)
