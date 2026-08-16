"""Redact secrets from diagnostics that may later be stored or printed."""

from __future__ import annotations

import re
from collections.abc import Iterable

_TOKENISH = re.compile(
    r"""
    (?:ya29\.[A-Za-z0-9._-]+)
    | (?:1//[A-Za-z0-9_-]+)
    | (?:AIza[0-9A-Za-z_-]{20,})
    | (?:-----BEGIN [A-Z ]*PRIVATE KEY-----)
    """,
    re.VERBOSE,
)


def sanitize_diagnostic(message: str, *, secrets: Iterable[str] = ()) -> str:
    """Return a single-line diagnostic that must never contain secrets or clip text.

    Callers should pass passphrases, tokens, and clipboard strings they already
    hold so accidental interpolation is stripped even if a library includes them.
    """

    text = message.replace("\n", " ").replace("\r", " ")
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    text = _TOKENISH.sub("[redacted]", text)
    if len(text) > 500:
        text = text[:500]
    return text
