from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from retropyclip.crypto.envelope import MIN_PASSPHRASE_LENGTH
from retropyclip.runtime import Runtime
from retropyclip.ui.macos_paste import MacOSPasteTarget, PastePreparation
from retropyclip.ui.tray import TrayController


def test_tray_builds_history_actions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETROPYCLIP_HOME", str(tmp_path / "home"))
    # Keep this widget test isolated from the real foreground macOS application.
    monkeypatch.setattr(MacOSPasteTarget, "capture", lambda: None)
    runtime = Runtime.open()
    runtime.repository.create_local_clip(
        "saved item",
        device_id=runtime.settings.device_id,
        device_name=runtime.settings.device_name,
        max_bytes=runtime.settings.max_item_bytes,
        history_limit=runtime.settings.history_limit,
    )

    application = QApplication.instance() or QApplication([])
    controller = TrayController(application, register_hotkey=False)

    history = next(action.menu() for action in controller.menu.actions() if action.text() == "History")
    assert history is not None
    group = history.actions()[0].menu()
    assert group is not None
    assert group.actions()[0].text() == "saved item"

    controller._toggle_history()
    assert controller.history_popup.isVisible()
    assert controller.history_popup.list.count() == 1
    controller.history_popup.search.setText("saved")
    assert not controller.history_popup.list.item(0).isHidden()

    item_rect = controller.history_popup.list.visualItemRect(
        controller.history_popup.list.item(0)
    )
    QTest.mouseClick(
        controller.history_popup.list.viewport(),
        Qt.LeftButton,
        pos=item_rect.center(),
    )
    assert application.clipboard().text() == "saved item"
    assert not controller.history_popup.isVisible()

    controller._toggle_history()
    QTest.keyClick(controller.history_popup.search, Qt.Key_Return)
    assert application.clipboard().text() == "saved item"
    assert not controller.history_popup.isVisible()

    application.clipboard().dataChanged.disconnect(controller._clipboard_changed)
    application.clipboard().setText("externally copied item")
    QTest.qWait(300)
    assert controller.runtime.repository.list_history(limit=1)[0].record.text == "externally copied item"

    class FakePasteTarget:
        sent = False

        @staticmethod
        def prepare() -> PastePreparation:
            return PastePreparation.READY

        def send_paste_keystroke(self) -> None:
            self.sent = True

    paste_target = FakePasteTarget()
    monkeypatch.setattr("retropyclip.ui.tray.platform.system", lambda: "Darwin")
    controller._history_paste_target = paste_target  # type: ignore[assignment]
    controller._select_history_text("selected for automatic paste")
    QTest.qWait(200)
    assert application.clipboard().text() == "selected for automatic paste"
    assert paste_target.sent

    controller._cleanup()
    controller._cleanup()
    assert not controller.tray.isVisible()
    assert controller.tray.contextMenu() is None


def test_tray_rejects_short_sync_passphrase_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RETROPYCLIP_HOME", str(tmp_path / "home"))
    application = QApplication.instance() or QApplication([])
    controller = TrayController(application, register_hotkey=False)
    warnings: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "retropyclip.ui.tray.QInputDialog.getText",
        lambda *_args: ("x" * (MIN_PASSPHRASE_LENGTH - 1), True),
    )
    monkeypatch.setattr(
        "retropyclip.ui.tray.QMessageBox.warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    controller._start_sync()

    assert controller.sync_future is None
    assert warnings == [
        (
            "Passphrase too short",
            "Use at least 12 characters. Nothing was uploaded; choose a longer "
            "passphrase and try Sync Now again.",
        )
    ]

    controller._cleanup()
