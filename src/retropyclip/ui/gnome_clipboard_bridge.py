from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Slot
from PySide6.QtDBus import QDBusConnection

SERVICE_NAME = "io.github.VaughnDV.RetroPyClip"
OBJECT_PATH = "/io/github/VaughnDV/RetroPyClip"
INTERFACE_NAME = SERVICE_NAME


class GnomeClipboardBridge(QObject):
    """Receive clipboard text from the bundled GNOME Shell extension."""

    def __init__(
        self,
        callback: Callable[[str], None],
        parent: QObject | None = None,
        *,
        bus: QDBusConnection | None = None,
    ) -> None:
        super().__init__(parent)
        self._callback = callback
        self._bus = bus or QDBusConnection.sessionBus()
        self.available = False
        if not self._bus.isConnected() or not self._bus.registerService(SERVICE_NAME):
            return
        if not self._bus.registerObject(
            OBJECT_PATH,
            INTERFACE_NAME,
            self,
            QDBusConnection.ExportAllSlots,
        ):
            self._bus.unregisterService(SERVICE_NAME)
            return
        self.available = True

    @Slot(str, name="CaptureText")
    def capture_text(self, text: str) -> None:
        self._callback(text)

    def close(self) -> None:
        if not self.available:
            return
        self._bus.unregisterObject(OBJECT_PATH)
        self._bus.unregisterService(SERVICE_NAME)
        self.available = False
