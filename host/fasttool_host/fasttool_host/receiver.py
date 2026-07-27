"""Hidden `FastToolIPC::host` window -- the host's receive side of
CONTRACT.md's "Settings protocol (v2)". A tool's client shim sends its
`snapshot` here the same way the host sends actions to a tool: FindWindow by
title, then WM_COPYDATA -- just reversed.

Win32 message delivery is thread-affine (a window only receives messages on
the thread that created it), so -- same reasoning as the client's own
receive-side window (client/python/fasttool_palette/fasttool_palette/window.py's
`_IPCWindow`/`FastToolPalette`) -- this runs its own background thread with
its own message pump, never the Qt GUI thread. Decoded snapshots cross back
to the GUI thread via a Qt Signal: emitting a signal from a non-GUI thread on
a queued connection is thread-safe and handled automatically by Qt (same
pattern as FastCommandCenter's core/hotkey_bridge.py for its winhotkeys
callback).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import win32api
import win32con
import win32gui
import winerror
from PySide6.QtCore import QObject, Signal

from .copydata import (
    SETTINGS_PROTOCOL_VERSION,
    TEXT_PROVIDER_PROTOCOL_VERSION,
    decode_settings_payload,
    read_copydata_struct,
)
from .settings import SettingsError, ToolSettings
from .text_provider import (
    TextProviderError,
    ToolTextProviderActivation,
    ToolTextResults,
)

HOST_IPC_TITLE = "FastToolIPC::host"


class _ReceiverWindow:
    """A hidden, ordinary top-level window (findable via FindWindow, not a
    message-only HWND_MESSAGE window) that decodes incoming WM_COPYDATA
    settings messages and hands them to a callback. Mirrors
    fasttool_palette.window._IPCWindow, the client's equivalent for the
    opposite direction."""

    def __init__(self, on_message: Callable[[int, str, dict[str, Any]], None]) -> None:
        self._on_message = on_message
        wc = win32gui.WNDCLASS()
        # The class-level wndproc is just a DefWindowProc placeholder: a
        # window CLASS is process-wide (RegisterClass with the same name
        # twice fails, see below), but each SettingsReceiver instance needs
        # its OWN callback -- sharing the class's wndproc would mean a
        # second instance silently receives the first instance's callback.
        # SetWindowLong below installs this instance's real wndproc on this
        # specific window instead, the standard "subclassing" pattern.
        wc.lpfnWndProc = win32gui.DefWindowProc  # type: ignore[misc]
        class_name = f"FastToolPaletteWindowClass::{HOST_IPC_TITLE}"
        wc.lpszClassName = class_name  # type: ignore[misc]
        wc.hInstance = win32api.GetModuleHandle(None)  # type: ignore[misc]
        try:
            class_atom: Any = win32gui.RegisterClass(wc)
        except win32gui.error as exc:
            # ToolBridge is normally constructed once per process, but tests
            # (and any future caller creating more than one) construct many
            # in a single process -- a second RegisterClass legitimately
            # fails with "class already exists" rather than something being
            # wrong. CreateWindow accepts the class name string just as well
            # as the atom, so fall back to that instead of treating this as
            # fatal.
            if exc.winerror != winerror.ERROR_CLASS_ALREADY_EXISTS:
                raise
            class_atom = class_name
        self.hwnd = win32gui.CreateWindow(
            class_atom, HOST_IPC_TITLE, 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None
        )
        win32gui.SetWindowLong(self.hwnd, win32con.GWL_WNDPROC, self._wndproc)

    def _wndproc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg == win32con.WM_COPYDATA:
            decoded = read_copydata_struct(lparam)
            if decoded is not None:
                dw_data, raw = decoded
                if dw_data in (SETTINGS_PROTOCOL_VERSION, TEXT_PROVIDER_PROTOCOL_VERSION):
                    envelope = decode_settings_payload(raw)
                    if envelope is not None:
                        self._on_message(dw_data, *envelope)
            return True
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


class SettingsReceiver(QObject):
    """Runs the hidden `FastToolIPC::host` window on a background thread and
    emits `snapshot_received` on the GUI thread whenever a tool reports its
    settings (in response to `describe`, or after applying a `set`).
    `ToolBridge` owns one instance; call `stop()` on app shutdown.

    An unrecognized `kind` (not `"snapshot"`) or a malformed body is dropped
    silently -- a bad message from one tool must never take the host down,
    same rule as everywhere else in this protocol.
    """

    snapshot_received = Signal(ToolSettings)
    text_results_received = Signal(ToolTextResults)
    text_provider_activation_requested = Signal(ToolTextProviderActivation)

    def __init__(self) -> None:
        super().__init__()
        self._ready = threading.Event()
        self.hwnd: int | None = None
        self._thread_id: int | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)

    def _run(self) -> None:
        self._thread_id = win32api.GetCurrentThreadId()
        window = _ReceiverWindow(self._on_message)
        self.hwnd = window.hwnd
        self._ready.set()
        win32gui.PumpMessages()

    def _on_message(self, version: int, kind: str, body: dict[str, Any]) -> None:
        try:
            if version == SETTINGS_PROTOCOL_VERSION and kind == "snapshot":
                self.snapshot_received.emit(ToolSettings.from_dict(body))
            elif version == TEXT_PROVIDER_PROTOCOL_VERSION and kind == "results":
                self.text_results_received.emit(ToolTextResults.from_dict(body))
            elif version == TEXT_PROVIDER_PROTOCOL_VERSION and kind == "activate_provider":
                activation = ToolTextProviderActivation.from_dict(body)
                self.text_provider_activation_requested.emit(activation)
        except (SettingsError, TextProviderError):
            return

    def stop(self) -> None:
        """Stop the background message pump. Safe to call once; the window
        and its thread are not reused after this (mirrors ToolBridge's own
        one-shot shutdown())."""
        if self._thread_id is not None:
            win32api.PostThreadMessage(self._thread_id, win32con.WM_QUIT, 0, 0)
            self._thread_id = None
