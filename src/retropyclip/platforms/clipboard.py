from __future__ import annotations

import os
import platform
import shutil
import subprocess
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass


class ClipboardUnavailable(RuntimeError):
    pass


class ClipboardAdapter(ABC):
    name = "unavailable"
    supports_concealed_markers = False

    @abstractmethod
    def read_text(self) -> str | None:
        """Return exact text or None when the clipboard has no plain-text representation."""

    @abstractmethod
    def set_text(self, text: str) -> None:
        """Replace the clipboard with a plain-text representation."""

    def is_concealed(self) -> bool:
        return False


class MacOSClipboard(ClipboardAdapter):
    name = "macOS pbcopy/pbpaste"

    def __init__(self) -> None:
        if not shutil.which("pbcopy") or not shutil.which("pbpaste"):
            raise ClipboardUnavailable("pbcopy and pbpaste are not available")
        try:
            import AppKit  # type: ignore[import-not-found]

            self._appkit = AppKit
            self.supports_concealed_markers = True
        except ImportError:
            self._appkit = None

    def read_text(self) -> str | None:
        result = subprocess.run(
            ["pbpaste"], check=False, capture_output=True, timeout=3
        )
        if result.returncode != 0:
            return None
        try:
            return result.stdout.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def set_text(self, text: str) -> None:
        result = subprocess.run(
            ["pbcopy"], input=text.encode("utf-8"), check=False, capture_output=True, timeout=3
        )
        if result.returncode != 0:
            raise ClipboardUnavailable("macOS rejected clipboard text")

    def is_concealed(self) -> bool:
        if self._appkit is None:
            return False
        pasteboard = self._appkit.NSPasteboard.generalPasteboard()
        types = {str(value) for value in (pasteboard.types() or [])}
        concealed = {
            "org.nspasteboard.ConcealedType",
            "org.nspasteboard.TransientType",
            "com.agilebits.onepassword",
        }
        return bool(types & concealed)


class WaylandClipboard(ClipboardAdapter):
    name = "Wayland wl-clipboard"

    def __init__(self) -> None:
        if not shutil.which("wl-copy") or not shutil.which("wl-paste"):
            raise ClipboardUnavailable("install wl-clipboard for Wayland clipboard access")

    def read_text(self) -> str | None:
        result = subprocess.run(
            ["wl-paste", "--type", "text/plain"],
            check=False,
            capture_output=True,
            timeout=3,
        )
        if result.returncode != 0:
            return None
        try:
            return result.stdout.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def set_text(self, text: str) -> None:
        result = subprocess.run(
            ["wl-copy", "--type", "text/plain;charset=utf-8"],
            input=text.encode("utf-8"),
            check=False,
            capture_output=True,
            timeout=3,
        )
        if result.returncode != 0:
            raise ClipboardUnavailable("Wayland compositor rejected clipboard text")


class X11Clipboard(ClipboardAdapter):
    name = "X11 clipboard"

    def __init__(self) -> None:
        if shutil.which("xclip"):
            self.tool = "xclip"
        elif shutil.which("xsel"):
            self.tool = "xsel"
        else:
            raise ClipboardUnavailable("install xclip or xsel for X11 clipboard access")
        self.name = f"X11 {self.tool}"

    def read_text(self) -> str | None:
        command = (
            ["xclip", "-selection", "clipboard", "-o"]
            if self.tool == "xclip"
            else ["xsel", "--clipboard", "--output"]
        )
        result = subprocess.run(command, check=False, capture_output=True, timeout=3)
        if result.returncode != 0:
            return None
        try:
            return result.stdout.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def set_text(self, text: str) -> None:
        command = (
            ["xclip", "-selection", "clipboard", "-in"]
            if self.tool == "xclip"
            else ["xsel", "--clipboard", "--input"]
        )
        result = subprocess.run(
            command, input=text.encode("utf-8"), check=False, capture_output=True, timeout=3
        )
        if result.returncode != 0:
            raise ClipboardUnavailable(f"{self.tool} rejected clipboard text")


class HeadlessClipboard(ClipboardAdapter):
    name = "headless"

    def read_text(self) -> str | None:
        raise ClipboardUnavailable("this session has no desktop clipboard")

    def set_text(self, text: str) -> None:
        raise ClipboardUnavailable("this session has no desktop clipboard; use 'show' instead")


def detect_clipboard() -> ClipboardAdapter:
    if platform.system() == "Darwin":
        return MacOSClipboard()
    if os.environ.get("WAYLAND_DISPLAY"):
        return WaylandClipboard()
    if os.environ.get("DISPLAY"):
        return X11Clipboard()
    return HeadlessClipboard()


@dataclass(frozen=True, slots=True)
class ClipboardCapabilities:
    platform: str
    session: str
    adapter: str
    can_read: bool
    can_write: bool
    concealed_markers: bool


def capabilities() -> ClipboardCapabilities:
    system = platform.system()
    if system == "Darwin":
        session = "Aqua"
    elif os.environ.get("WAYLAND_DISPLAY"):
        session = "Wayland"
    elif os.environ.get("DISPLAY"):
        session = "X11"
    else:
        session = "headless"
    try:
        adapter = detect_clipboard()
        available = not isinstance(adapter, HeadlessClipboard)
        return ClipboardCapabilities(
            platform=system,
            session=session,
            adapter=adapter.name,
            can_read=available,
            can_write=available,
            concealed_markers=adapter.supports_concealed_markers,
        )
    except ClipboardUnavailable as error:
        return ClipboardCapabilities(
            platform=system,
            session=session,
            adapter=str(error),
            can_read=False,
            can_write=False,
            concealed_markers=False,
        )


class ClipboardMonitor:
    def __init__(
        self,
        adapter: ClipboardAdapter,
        callback: Callable[[str], None],
        *,
        should_capture: Callable[[], bool],
        interval: float = 0.5,
    ) -> None:
        self.adapter = adapter
        self.callback = callback
        self.should_capture = should_capture
        self.interval = interval
        self._stop = threading.Event()
        self._last: str | None = None

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                current = self.adapter.read_text()
                if current is not None and current != self._last:
                    self._last = current
                    if self.should_capture() and not self.adapter.is_concealed():
                        self.callback(current)
            except (ClipboardUnavailable, OSError, subprocess.SubprocessError):
                pass
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
