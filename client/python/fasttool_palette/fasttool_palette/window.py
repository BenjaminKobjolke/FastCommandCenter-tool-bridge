"""Hidden IPC window + background message pump — the client's receive side of
CONTRACT.md.

Win32 message delivery is thread-affine (a window only receives messages on
the thread that created it), so this runs on its own dedicated background
thread rather than the host app's thread — the host's own event loop
(Tkinter, etc.) must never be blocked or touched from here. poll() is the
thread-safe hand-off point.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable

import win32api
import win32con
import win32gui

from .copydata import decode_copydata


class _IPCWindow:
    """A hidden, ordinary top-level window (findable via FindWindow) that
    dispatches WM_COPYDATA payloads to a callback."""

    def __init__(self, title: str, on_action: Callable[[str], None]) -> None:
        self._on_action = on_action
        wc = win32gui.WNDCLASS()
        # typeshed marks these properties read-only; PyWNDCLASS is genuinely
        # mutable at runtime — this is the documented way to configure it.
        wc.lpfnWndProc = self._wndproc  # type: ignore[misc]
        wc.lpszClassName = f"FastToolPaletteWindowClass::{title}"  # type: ignore[misc]
        wc.hInstance = win32api.GetModuleHandle(None)  # type: ignore[misc]
        class_atom = win32gui.RegisterClass(wc)
        self.hwnd = win32gui.CreateWindow(
            class_atom, title, 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None
        )

    def _wndproc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg == win32con.WM_COPYDATA:
            action_id = decode_copydata(lparam)
            if action_id is not None:
                self._on_action(action_id)
            return True
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


class FastToolPalette:
    """Runs the hidden `FastToolIPC::<tool_id>` window and queues received
    action ids. Call poll() from the host app's own loop (e.g. a Tk
    `after(...)` tick) to drain and dispatch them safely on the host's thread.
    """

    def __init__(self, tool_id: str, ready_timeout_s: float = 5.0) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        self._ready = threading.Event()
        self.hwnd: int | None = None
        self._thread = threading.Thread(
            target=self._run, args=(f"FastToolIPC::{tool_id}",), daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=ready_timeout_s)

    def _run(self, title: str) -> None:
        window = _IPCWindow(title, self._queue.put)
        self.hwnd = window.hwnd
        self._ready.set()
        win32gui.PumpMessages()

    def poll(self) -> list[str]:
        """Return and clear all action ids received since the last poll()."""
        actions = []
        while True:
            try:
                actions.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return actions
