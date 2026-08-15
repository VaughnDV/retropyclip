from __future__ import annotations

import ctypes
import platform
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

CARBON_PATH = "/System/Library/Frameworks/Carbon.framework/Carbon"
K_EVENT_CLASS_KEYBOARD = int.from_bytes(b"keyb", "big")
K_EVENT_HOT_KEY_PRESSED = 6
K_VIRTUAL_KEY_V = 0x09
CMD_KEY = 1 << 8
SHIFT_KEY = 1 << 9
NO_ERR = 0


class GlobalHotKeyError(RuntimeError):
    pass


class EventTypeSpec(ctypes.Structure):
    _fields_ = [("event_class", ctypes.c_uint32), ("event_kind", ctypes.c_uint32)]


class EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("identifier", ctypes.c_uint32)]


EventHandlerCallback = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
)


class MacOSHistoryHotKey(QObject):
    """Register Cmd+Shift+V through Carbon without Accessibility permission."""

    activated = Signal()

    def __init__(self, callback: Callable[[], None], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.activated.connect(callback)
        self._carbon: ctypes.CDLL | None = None
        self._handler_callback: EventHandlerCallback | None = None
        self._handler_ref = ctypes.c_void_p()
        self._hotkey_ref = ctypes.c_void_p()
        self._registered = False

    @property
    def registered(self) -> bool:
        return self._registered

    def register(self) -> None:
        if self._registered:
            return
        if platform.system() != "Darwin":
            raise GlobalHotKeyError("global Cmd+Shift+V is currently implemented for macOS")

        carbon = ctypes.cdll.LoadLibrary(CARBON_PATH)
        self._configure_functions(carbon)
        event_type = EventTypeSpec(K_EVENT_CLASS_KEYBOARD, K_EVENT_HOT_KEY_PRESSED)

        @EventHandlerCallback
        def handler(
            next_handler: ctypes.c_void_p,
            event: ctypes.c_void_p,
            user_data: ctypes.c_void_p,
        ) -> int:
            del next_handler, event, user_data
            self.activated.emit()
            return NO_ERR

        target = carbon.GetApplicationEventTarget()
        status = carbon.InstallEventHandler(
            target,
            handler,
            1,
            ctypes.byref(event_type),
            None,
            ctypes.byref(self._handler_ref),
        )
        if status != NO_ERR:
            raise GlobalHotKeyError(f"could not install the macOS hotkey handler ({status})")

        hotkey_id = EventHotKeyID(int.from_bytes(b"RPCH", "big"), 1)
        status = carbon.RegisterEventHotKey(
            K_VIRTUAL_KEY_V,
            CMD_KEY | SHIFT_KEY,
            hotkey_id,
            target,
            0,
            ctypes.byref(self._hotkey_ref),
        )
        if status != NO_ERR:
            carbon.RemoveEventHandler(self._handler_ref)
            self._handler_ref = ctypes.c_void_p()
            if status == -9878:
                raise GlobalHotKeyError("Cmd+Shift+V is already registered by another application")
            raise GlobalHotKeyError(f"could not register Cmd+Shift+V ({status})")

        self._carbon = carbon
        self._handler_callback = handler
        self._registered = True

    def close(self) -> None:
        if not self._registered or self._carbon is None:
            return
        self._carbon.UnregisterEventHotKey(self._hotkey_ref)
        self._carbon.RemoveEventHandler(self._handler_ref)
        self._registered = False
        self._hotkey_ref = ctypes.c_void_p()
        self._handler_ref = ctypes.c_void_p()
        self._handler_callback = None
        self._carbon = None

    @staticmethod
    def _configure_functions(carbon: ctypes.CDLL) -> None:
        carbon.GetApplicationEventTarget.argtypes = []
        carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
        carbon.InstallEventHandler.argtypes = [
            ctypes.c_void_p,
            EventHandlerCallback,
            ctypes.c_uint32,
            ctypes.POINTER(EventTypeSpec),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        carbon.InstallEventHandler.restype = ctypes.c_int32
        carbon.RegisterEventHotKey.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            EventHotKeyID,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        carbon.RegisterEventHotKey.restype = ctypes.c_int32
        carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        carbon.UnregisterEventHotKey.restype = ctypes.c_int32
        carbon.RemoveEventHandler.argtypes = [ctypes.c_void_p]
        carbon.RemoveEventHandler.restype = ctypes.c_int32
