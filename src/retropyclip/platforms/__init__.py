"""Operating-system clipboard adapters."""

from retropyclip.platforms.clipboard import (
    ClipboardAdapter,
    ClipboardUnavailable,
    detect_clipboard,
)

__all__ = ["ClipboardAdapter", "ClipboardUnavailable", "detect_clipboard"]
