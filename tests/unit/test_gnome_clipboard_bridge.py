from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from retropyclip.ui.gnome_clipboard_bridge import (
    INTERFACE_NAME,
    OBJECT_PATH,
    SERVICE_NAME,
    GnomeClipboardBridge,
)


class FakeBus:
    def __init__(self) -> None:
        self.registered_service: str | None = None
        self.registered_object: tuple[str, str] | None = None
        self.unregistered_service: str | None = None
        self.unregistered_object: str | None = None

    @staticmethod
    def isConnected() -> bool:
        return True

    def registerService(self, service: str) -> bool:
        self.registered_service = service
        return True

    def registerObject(self, path: str, interface: str, *_args: object) -> bool:
        self.registered_object = (path, interface)
        return True

    def unregisterService(self, service: str) -> bool:
        self.unregistered_service = service
        return True

    def unregisterObject(self, path: str) -> None:
        self.unregistered_object = path


def test_gnome_bridge_exports_capture_method_and_cleans_up() -> None:
    captured: list[str] = []
    bus = FakeBus()
    bridge = GnomeClipboardBridge(captured.append, bus=bus)  # type: ignore[arg-type]

    assert bridge.available
    assert bus.registered_service == SERVICE_NAME
    assert bus.registered_object == (OBJECT_PATH, INTERFACE_NAME)

    bridge.capture_text("copied through GNOME")
    assert captured == ["copied through GNOME"]

    bridge.close()
    assert not bridge.available
    assert bus.unregistered_object == OBJECT_PATH
    assert bus.unregistered_service == SERVICE_NAME
