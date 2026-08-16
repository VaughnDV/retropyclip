from __future__ import annotations

import os
from enum import Enum
from typing import Any


class PastePreparation(Enum):
    READY = "ready"
    PERMISSION_REQUIRED = "permission_required"
    TARGET_UNAVAILABLE = "target_unavailable"


_permission_prompt_requested = False


class MacOSPasteTarget:
    """The app that was active immediately before the history window opened."""

    def __init__(self, application: Any) -> None:
        self._application = application

    @classmethod
    def capture(cls) -> MacOSPasteTarget | None:
        try:
            import AppKit
        except ImportError:
            return None

        application = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if application is None or application.processIdentifier() == os.getpid():
            return None
        return cls(application)

    def prepare(self) -> PastePreparation:
        global _permission_prompt_requested

        try:
            import AppKit
            import ApplicationServices
        except ImportError:
            return PastePreparation.TARGET_UNAVAILABLE

        if self._application.isTerminated():
            return PastePreparation.TARGET_UNAVAILABLE
        if not ApplicationServices.AXIsProcessTrusted():
            if not _permission_prompt_requested:
                _permission_prompt_requested = True
                ApplicationServices.AXIsProcessTrustedWithOptions(
                    {ApplicationServices.kAXTrustedCheckOptionPrompt: True}
                )
            return PastePreparation.PERMISSION_REQUIRED

        options = (
            AppKit.NSApplicationActivateIgnoringOtherApps
            | AppKit.NSApplicationActivateAllWindows
        )
        if not self._application.activateWithOptions_(options):
            return PastePreparation.TARGET_UNAVAILABLE
        return PastePreparation.READY

    @staticmethod
    def send_paste_keystroke() -> None:
        """Post Command+V after the destination app has regained focus."""

        try:
            import Quartz
        except ImportError:
            return

        key_down = Quartz.CGEventCreateKeyboardEvent(None, 9, True)
        key_up = Quartz.CGEventCreateKeyboardEvent(None, 9, False)
        if key_down is None or key_up is None:
            return
        Quartz.CGEventSetFlags(key_down, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventSetFlags(key_up, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, key_down)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, key_up)
