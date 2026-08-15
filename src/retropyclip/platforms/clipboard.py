from __future__ import annotations

import os
import platform
import shutil
import struct
import subprocess
import sys
import threading
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import BinaryIO


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
            import AppKit

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
            ["wl-paste", "--type", "text"],
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


class WaylandClipboardWatcher:
    """Receive clipboard changes from one persistent wl-paste process."""

    _header = struct.Struct("!Q")
    _maximum_frame_bytes = 1024 * 1024

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._pending: deque[str] = deque()
        self._lock = threading.Lock()

    def start(self) -> None:
        if self.is_running():
            return
        if not shutil.which("wl-paste"):
            raise ClipboardUnavailable("install wl-clipboard for Wayland clipboard watching")
        command = [
            "wl-paste",
            "--type",
            "text",
            "--watch",
            sys.executable,
            "-m",
            "retropyclip.platforms.wayland_watch_frame",
        ]
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as error:
            raise ClipboardUnavailable("could not start the Wayland clipboard watcher") from error
        assert self._process.stdout is not None
        self._thread = threading.Thread(
            target=self._consume,
            args=(self._process.stdout,),
            name="retropyclip-wayland-watch",
            daemon=True,
        )
        self._thread.start()

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def take_pending(self) -> list[str]:
        with self._lock:
            values = list(self._pending)
            self._pending.clear()
        return values

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._process = None
        self._thread = None

    def _consume(self, stream: BinaryIO) -> None:
        while True:
            header = self._read_exact(stream, self._header.size)
            if header is None:
                return
            size = self._header.unpack(header)[0]
            if size > self._maximum_frame_bytes:
                if not self._discard(stream, size):
                    return
                continue
            payload = self._read_exact(stream, size)
            if payload is None:
                return
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                continue
            with self._lock:
                self._pending.append(text)

    @staticmethod
    def _read_exact(stream: BinaryIO, size: int) -> bytes | None:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = stream.read(remaining)
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    @staticmethod
    def _discard(stream: BinaryIO, size: int) -> bool:
        remaining = size
        while remaining:
            chunk = stream.read(min(remaining, 65_536))
            if not chunk:
                return False
            remaining -= len(chunk)
        return True


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
