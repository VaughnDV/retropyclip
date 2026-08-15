from __future__ import annotations

import hashlib
import re


class InvalidClip(ValueError):
    """Raised when clipboard content cannot be stored."""


def normalize_text(text: str) -> str:
    """Normalize line endings only; preserve all other user text exactly."""
    if not isinstance(text, str):
        raise InvalidClip("clipboard content is not text")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def validate_text(text: str, max_bytes: int) -> str:
    normalized = normalize_text(text)
    if not normalized:
        raise InvalidClip("empty clipboard text is not stored")
    size = len(normalized.encode("utf-8"))
    if size > max_bytes:
        raise InvalidClip(f"clipboard text is {size} bytes; limit is {max_bytes} bytes")
    return normalized


def local_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def one_line_preview(text: str, width: int = 80) -> str:
    display = re.sub(r"\s+", " ", text).strip()
    if not display:
        display = "(whitespace)"
    if len(display) <= width:
        return display
    if width < 2:
        return "…"
    return display[: width - 1] + "…"
