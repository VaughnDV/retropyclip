from __future__ import annotations

import platform
import signal
import subprocess
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

try:
    from PySide6.QtCore import QLockFile, QObject, QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QInputDialog,
        QLineEdit,
        QMenu,
        QMessageBox,
        QSpinBox,
        QSystemTrayIcon,
    )
except ImportError as error:  # pragma: no cover - depends on optional GUI install
    raise SystemExit("The tray app needs the GUI extra: uv sync --extra gui") from error

from retropyclip.config import AppPaths
from retropyclip.core.models import SyncReport, format_utc
from retropyclip.core.text import InvalidClip, one_line_preview
from retropyclip.crypto.envelope import MIN_PASSPHRASE_LENGTH, CryptoError
from retropyclip.platforms.clipboard import (
    ClipboardUnavailable,
    WaylandClipboard,
    WaylandClipboardWatcher,
    detect_clipboard,
)
from retropyclip.runtime import Runtime
from retropyclip.sync.backend import AuthenticationRequired, BackendError
from retropyclip.sync.engine import SyncDisabled
from retropyclip.ui.history_popup import HistoryPopup
from retropyclip.ui.macos_hotkey import GlobalHotKeyError, MacOSHistoryHotKey
from retropyclip.ui.macos_paste import MacOSPasteTarget, PastePreparation

ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
_controller: TrayController | None = None
_instance_lock: QLockFile | None = None


class PreferencesDialog(QDialog):
    def __init__(self, runtime: Runtime) -> None:
        super().__init__()
        self.runtime = runtime
        self.setWindowTitle("RetroPyClip Preferences")
        self.setMinimumWidth(360)
        layout = QFormLayout(self)

        self.device_name = QLineEdit(runtime.settings.device_name)
        self.device_name.setAccessibleName("Device name")
        layout.addRow("Device name", self.device_name)

        self.history_limit = QSpinBox()
        self.history_limit.setRange(1, 100_000)
        self.history_limit.setValue(runtime.settings.history_limit)
        self.history_limit.setAccessibleName("History item limit")
        layout.addRow("History limit", self.history_limit)

        self.max_size = QSpinBox()
        self.max_size.setRange(1, 1024)
        self.max_size.setSuffix(" KiB")
        self.max_size.setValue(runtime.settings.max_item_bytes // 1024)
        self.max_size.setAccessibleName("Maximum clipboard item size in kibibytes")
        layout.addRow("Maximum item size", self.max_size)

        self.local_only = QCheckBox("Never connect to Drive")
        self.local_only.setChecked(runtime.settings.local_only)
        layout.addRow("Local-only mode", self.local_only)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def accept(self) -> None:
        self.runtime.settings.device_name = self.device_name.text().strip()
        self.runtime.settings.history_limit = self.history_limit.value()
        self.runtime.settings.max_item_bytes = self.max_size.value() * 1024
        self.runtime.settings.local_only = self.local_only.isChecked()
        try:
            self.runtime.config.save(self.runtime.settings)
            self.runtime.repository.enforce_retention(self.runtime.settings.history_limit)
        except ValueError as error:
            QMessageBox.warning(self, "Invalid preferences", str(error))
            return
        super().accept()


class TrayController(QObject):
    def __init__(self, application: QApplication, *, register_hotkey: bool = True) -> None:
        super().__init__()
        self.application = application
        self._cleanup_done = False
        self._quit_requested = False
        self.runtime = Runtime.open()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="retropyclip-sync")
        self.sync_future: Future[SyncReport] | None = None
        self.native_clipboard = None
        with suppress(ClipboardUnavailable):
            self.native_clipboard = detect_clipboard()
        self._last_observed_clipboard_text = self._read_current_clipboard()
        self.wayland_watcher: WaylandClipboardWatcher | None = None
        if isinstance(self.native_clipboard, WaylandClipboard):
            watcher = WaylandClipboardWatcher()
            with suppress(ClipboardUnavailable):
                watcher.start()
                self.wayland_watcher = watcher

        self.tray = QSystemTrayIcon(self._icon("idle"), self)
        self.tray.setToolTip("RetroPyClip — local clipboard history")
        self.menu = QMenu()
        self._submenus: list[QMenu] = []
        self.tray.setContextMenu(self.menu)
        self.application.clipboard().dataChanged.connect(self._clipboard_changed)
        self.history_popup = HistoryPopup(self._select_history_text)
        self._history_paste_target: MacOSPasteTarget | None = None
        self.history_hotkey: MacOSHistoryHotKey | None = None
        self.hotkey_error: str | None = None
        if register_hotkey and platform.system() == "Darwin":
            try:
                self.history_hotkey = MacOSHistoryHotKey(self._toggle_history, self)
                self.history_hotkey.register()
            except GlobalHotKeyError as error:
                self.history_hotkey = None
                self.hotkey_error = str(error)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.rebuild_menu)
        self.refresh_timer.start(10_000)
        self.future_timer = QTimer(self)
        self.future_timer.timeout.connect(self._check_sync_future)
        self.capture_timer = QTimer(self)
        self.capture_timer.timeout.connect(self._capture_current_clipboard)
        self.capture_timer.start(max(100, int(self.runtime.settings.clipboard_poll_seconds * 1000)))

        self.rebuild_menu()
        self.tray.show()
        self.application.aboutToQuit.connect(self._cleanup)

    @staticmethod
    def _icon(state: str) -> QIcon:
        path = ASSET_DIR / f"tray-{state}.svg"
        if not path.exists():
            path = ASSET_DIR / "tray-idle.svg"
        return QIcon(str(path))

    def rebuild_menu(self) -> None:
        self.runtime.reload_settings()
        self.menu.clear()
        self._submenus.clear()
        status = self.runtime.sync_status()
        state = str(status.get("state", "local")) if status else "local"
        status_action = self.menu.addAction(f"STATUS: {state.replace('_', ' ').upper()}")
        status_action.setEnabled(False)

        open_history = self.menu.addAction("Open History    ⌘⇧V")
        open_history.triggered.connect(self._toggle_history)
        if self.hotkey_error:
            shortcut_status = self.menu.addAction(f"Shortcut unavailable: {self.hotkey_error}")
            shortcut_status.setEnabled(False)
        self.menu.addSeparator()

        history_menu = QMenu("History", self.menu)
        self.menu.addMenu(history_menu)
        self._submenus.append(history_menu)
        items = self.runtime.repository.list_history(limit=self.runtime.settings.history_limit)
        if not items:
            empty = history_menu.addAction("No clips yet")
            empty.setEnabled(False)
        for start in range(0, len(items), 10):
            group = QMenu(f"{start + 1}-{min(start + 10, len(items))}", history_menu)
            history_menu.addMenu(group)
            self._submenus.append(group)
            for item in items[start : start + 10]:
                record = item.record
                label = one_line_preview(record.text or "", 58)
                action = group.addAction(label)
                action.setToolTip(
                    f"{record.captured_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')} — "
                    f"{record.device_name}"
                )
                action.triggered.connect(
                    lambda checked=False, text=record.text or "": self._copy_text(text)
                )

        snippets = QMenu("Snippets", self.menu)
        self.menu.addMenu(snippets)
        self._submenus.append(snippets)
        coming = snippets.addAction("Local snippets are planned after sync validation")
        coming.setEnabled(False)
        self.menu.addSeparator()

        sync_now = self.menu.addAction("Sync Now")
        sync_now.setEnabled(self.sync_future is None and not self.runtime.settings.local_only)
        sync_now.triggered.connect(self._start_sync)

        pause_capture = self.menu.addAction("Pause Capture")
        pause_capture.setCheckable(True)
        pause_capture.setChecked(not self.runtime.capture_enabled())
        pause_capture.triggered.connect(self._toggle_capture)
        pause_five = self.menu.addAction("Pause Capture for 5 Minutes")
        pause_five.triggered.connect(self._pause_five)

        pause_sync = self.menu.addAction("Pause Sync")
        pause_sync.setCheckable(True)
        pause_sync.setChecked(self.runtime.settings.sync_paused)
        pause_sync.triggered.connect(self._toggle_sync)
        self.menu.addSeparator()

        clear_local = self.menu.addAction("Clear Local History…")
        clear_local.triggered.connect(self._clear_local)
        clear_everywhere = self.menu.addAction("Clear Everywhere…")
        clear_everywhere.triggered.connect(self._clear_everywhere)
        self.menu.addSeparator()

        preferences = self.menu.addAction("Preferences…")
        preferences.triggered.connect(self._preferences)
        quit_action = self.menu.addAction("Quit")
        quit_action.triggered.connect(self._quit)

        if not self.runtime.capture_enabled():
            self.tray.setIcon(self._icon("paused"))
        elif state == "syncing":
            self.tray.setIcon(self._icon("syncing"))
        elif state in {"error", "authentication_required"}:
            self.tray.setIcon(self._icon("error"))
        elif state == "offline":
            self.tray.setIcon(self._icon("offline"))
        else:
            self.tray.setIcon(self._icon("idle"))

    def _clipboard_changed(self) -> None:
        self._capture_current_clipboard()
        # Some macOS clipboard owners provide their text lazily. Retrying shortly
        # after the notification catches data that was not ready on the first read.
        QTimer.singleShot(50, self._capture_current_clipboard)
        QTimer.singleShot(150, self._capture_current_clipboard)

    def _read_current_clipboard(self) -> str | None:
        if self.native_clipboard is not None and self.native_clipboard.is_concealed():
            return None
        clipboard = self.application.clipboard()
        mime = clipboard.mimeData()
        if not mime or not mime.hasText():
            return None
        text = clipboard.text()
        if (
            not text
            and self.native_clipboard is not None
            and not isinstance(self.native_clipboard, WaylandClipboard)
        ):
            with suppress(ClipboardUnavailable):
                return self.native_clipboard.read_text()
        return text

    def _capture_current_clipboard(self) -> None:
        if self.wayland_watcher is not None and self.wayland_watcher.is_running():
            for text in self.wayland_watcher.take_pending():
                self._capture_text(text)
            return
        text = self._read_current_clipboard()
        self._capture_text(text)

    def _capture_text(self, text: str | None) -> None:
        if not self.runtime.capture_enabled():
            self._last_observed_clipboard_text = text
            return
        if text is None or text == self._last_observed_clipboard_text:
            return
        self._last_observed_clipboard_text = text
        settings = self.runtime.reload_settings()
        try:
            _, created = self.runtime.repository.create_local_clip(
                text,
                device_id=settings.device_id,
                device_name=settings.device_name,
                max_bytes=settings.max_item_bytes,
                history_limit=settings.history_limit,
            )
        except InvalidClip:
            return
        if created:
            self.rebuild_menu()

    def _copy_text(self, text: str) -> None:
        self.runtime.repository.set_clipboard_suppression(text)
        self.application.clipboard().setText(text)
        if platform.system() == "Linux" and self.native_clipboard is not None:
            try:
                # On Wayland and X11 the process that owns the selection matters.
                # Let wl-copy/xclip become the final owner; Qt remains a fallback.
                self.native_clipboard.set_text(text)
            except (ClipboardUnavailable, OSError, subprocess.SubprocessError) as error:
                self.tray.showMessage(
                    "Clipboard fallback in use",
                    f"The native Linux clipboard utility failed: {error}",
                    QSystemTrayIcon.Warning,
                    6000,
                )

    def _select_history_text(self, text: str) -> None:
        self._copy_text(text)
        target = self._history_paste_target
        self._history_paste_target = None
        if platform.system() != "Darwin" or target is None:
            return

        preparation = target.prepare()
        if preparation is PastePreparation.READY:
            # Give the destination app a moment to restore its key window before
            # posting Command+V. The clipboard is already populated at this point.
            QTimer.singleShot(160, target.send_paste_keystroke)
        elif preparation is PastePreparation.PERMISSION_REQUIRED:
            self.tray.showMessage(
                "Allow automatic paste",
                "Enable Accessibility for RetroPyClip (or the terminal that launched it), "
                "then choose the clip again. It has still been copied.",
                QSystemTrayIcon.Information,
                8000,
            )
        else:
            self.tray.showMessage(
                "Clip copied",
                "The previous app could not be restored, so press Command+V to paste.",
                QSystemTrayIcon.Information,
                5000,
            )

    def _toggle_history(self) -> None:
        records = self.runtime.repository.list_history(limit=self.runtime.settings.history_limit)
        if self.history_popup.isVisible():
            self.history_popup.hide()
            return
        if platform.system() == "Darwin":
            self._history_paste_target = MacOSPasteTarget.capture()
            try:
                import AppKit  # type: ignore[import-not-found]

                AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            except ImportError:
                pass
        self.history_popup.show_browser(records)

    def _start_sync(self) -> None:
        passphrase, accepted = QInputDialog.getText(
            None,
            "RetroPyClip Sync",
            f"Sync passphrase (at least {MIN_PASSPHRASE_LENGTH} characters; never uploaded):",
            QLineEdit.Password,
        )
        if not accepted:
            return
        if len(passphrase) < MIN_PASSPHRASE_LENGTH:
            QMessageBox.warning(
                None,
                "Passphrase too short",
                f"Use at least {MIN_PASSPHRASE_LENGTH} characters. Nothing was uploaded; "
                "choose a longer passphrase and try Sync Now again.",
            )
            return
        if self.runtime.repository.get_meta("keyinfo") is None:
            confirmation, confirmed = QInputDialog.getText(
                None,
                "Confirm Sync Passphrase",
                "Enter the sync passphrase again:",
                QLineEdit.Password,
            )
            if not confirmed or confirmation != passphrase:
                QMessageBox.warning(None, "Passphrase mismatch", "The passphrases did not match.")
                return
        try:
            engine = self.runtime.sync_engine()
        except (AuthenticationRequired, BackendError) as error:
            QMessageBox.warning(None, "Sync unavailable", str(error))
            return
        self.sync_future = self.executor.submit(engine.sync, passphrase)
        passphrase = ""  # discard this UI reference; the worker retains only what it needs
        self.tray.setIcon(self._icon("syncing"))
        self.tray.setToolTip("RetroPyClip — syncing")
        self.future_timer.start(150)
        self.rebuild_menu()

    def _check_sync_future(self) -> None:
        if self.sync_future is None or not self.sync_future.done():
            return
        self.future_timer.stop()
        future = self.sync_future
        self.sync_future = None
        try:
            report = future.result()
            self.tray.showMessage(
                "RetroPyClip sync complete",
                f"Pulled {report.pulled}; pushed {report.pushed}; rejected {len(report.errors)}.",
                QSystemTrayIcon.Information,
                4000,
            )
        except (AuthenticationRequired, BackendError, CryptoError, SyncDisabled) as error:
            self.tray.showMessage(
                "RetroPyClip sync failed", str(error), QSystemTrayIcon.Warning, 6000
            )
        self.tray.setToolTip("RetroPyClip — local clipboard history")
        self.rebuild_menu()

    def _toggle_capture(self, paused: bool) -> None:
        self.runtime.settings.capture_paused = paused
        self.runtime.settings.pause_until = None
        self.runtime.config.save(self.runtime.settings)
        self.rebuild_menu()

    def _pause_five(self) -> None:
        self.runtime.settings.capture_paused = True
        self.runtime.settings.pause_until = format_utc(datetime.now(UTC) + timedelta(minutes=5))
        self.runtime.config.save(self.runtime.settings)
        self.rebuild_menu()

    def _toggle_sync(self, paused: bool) -> None:
        self.runtime.settings.sync_paused = paused
        self.runtime.config.save(self.runtime.settings)
        self.rebuild_menu()

    def _clear_local(self) -> None:
        answer = QMessageBox.question(
            None,
            "Clear Local History",
            "Hide all clipboard history on this device? Remote records will not be changed.",
        )
        if answer == QMessageBox.Yes:
            self.runtime.repository.clear_local()
            self.rebuild_menu()

    def _clear_everywhere(self) -> None:
        phrase, accepted = QInputDialog.getText(
            None,
            "Clear Everywhere",
            "Type CLEAR EVERYWHERE to queue encrypted deletion tombstones:",
        )
        if not accepted or phrase != "CLEAR EVERYWHERE":
            return
        count = self.runtime.repository.clear_everywhere(
            device_id=self.runtime.settings.device_id,
            device_name=self.runtime.settings.device_name,
        )
        QMessageBox.information(
            None,
            "Deletion queued",
            f"Queued {count} tombstone(s). Use Sync Now, then sync every other device.",
        )
        self.rebuild_menu()

    def _preferences(self) -> None:
        PreferencesDialog(self.runtime).exec()
        self.rebuild_menu()

    def _cleanup(self) -> None:
        if self._cleanup_done:
            return
        self._cleanup_done = True
        self.future_timer.stop()
        self.capture_timer.stop()
        self.refresh_timer.stop()
        if self.history_hotkey is not None:
            self.history_hotkey.close()
        if self.wayland_watcher is not None:
            self.wayland_watcher.close()
        self.history_popup.close()
        self.menu.close()
        self.tray.setContextMenu(None)
        # Hide the native status item while the Qt event loop is still alive.
        # Quitting immediately after hide can otherwise leave a stale macOS icon.
        self.tray.hide()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _quit(self) -> None:
        if self._quit_requested:
            return
        self._quit_requested = True
        self._cleanup()
        # Allow the native menu-bar removal to be processed before ending Qt.
        QTimer.singleShot(75, self.application.quit)


def main() -> int:
    global _controller, _instance_lock
    application = QApplication(sys.argv)
    application.setApplicationName("RetroPyClip")
    application.setQuitOnLastWindowClosed(False)
    paths = AppPaths.discover()
    paths.ensure()
    _instance_lock = QLockFile(str(paths.cache_dir / "tray.lock"))
    _instance_lock.setStaleLockTime(10_000)
    if not _instance_lock.tryLock(0):
        sys.stderr.write("RetroPyClip is already running in the menu bar.\n")
        return 0
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "RetroPyClip", "No system tray is available in this desktop session.")
        _instance_lock.unlock()
        return 1
    _controller = TrayController(application)
    signal.signal(signal.SIGINT, lambda *_: _controller._quit())
    signal.signal(signal.SIGTERM, lambda *_: _controller._quit())
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, lambda *_: _controller._quit())
    signal_timer = QTimer()
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(250)
    try:
        return application.exec()
    finally:
        _instance_lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
