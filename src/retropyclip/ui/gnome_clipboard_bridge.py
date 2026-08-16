from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Slot
from PySide6.QtDBus import QDBusConnection

from retropyclip.config import MAX_CONFIGURABLE_ITEM_BYTES

SERVICE_NAME = "io.github.VaughnDV.RetroPyClip"
OBJECT_PATH = "/io/github/VaughnDV/RetroPyClip"
INTERFACE_NAME = SERVICE_NAME


class GnomeClipboardBridge(QObject):
    """Receive clipboard text from the bundled GNOME Shell extension.

    The well-known name is registered on the per-user session bus only. Other
    users and other machines cannot call CaptureText. A same-uid process can;
    that is inside the local-endpoint threat model.
    """

    def __init__(
        self,
        callback: Callable[[str], None],
        parent: QObject | None = None,
        *,
        bus: QDBusConnection | None = None,
        max_item_bytes: int = MAX_CONFIGURABLE_ITEM_BYTES,
    ) -> None:
        super().__init__(parent)
        self._callback = callback
        self._max_item_bytes = max_item_bytes
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
        if not isinstance(text, str) or not text or "\x00" in text:
            return
        if len(text.encode("utf-8", "ignore")) > self._max_item_bytes:
            return
        self._callback(text)

    def close(self) -> None:
        if not self.available:
            return
        self._bus.unregisterObject(OBJECT_PATH)
        self._bus.unregisterService(SERVICE_NAME)
        self.available = False
