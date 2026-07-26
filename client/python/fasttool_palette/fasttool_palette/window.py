"""Hidden IPC window + background message pump — the client's receive side of
CONTRACT.md: action-fire (v1) and the settings protocol (v2, "add_setting"
below).

Win32 message delivery is thread-affine (a window only receives messages on
the thread that created it), so this runs on its own dedicated background
thread rather than the host app's thread — the host's own event loop
(Tkinter, etc.) must never be blocked or touched from here. poll() is the
thread-safe hand-off point for BOTH action ids and settings messages: a
`describe`/`set` received on the background thread is queued, not acted on
immediately, so registered getter/setter callbacks always run on the same
thread that calls poll() -- ordinary (non-threadsafe) tool state is safe to
touch from them, same guarantee action dispatch already gives.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import win32api
import win32con
import win32gui

from .copydata import (
    SETTINGS_PROTOCOL_VERSION,
    decode_settings_payload,
    find_window,
    read_copydata_struct,
    send_settings,
)

HOST_IPC_TITLE = "FastToolIPC::host"


@dataclass(frozen=True)
class _SettingDef:
    label: str
    type: str
    getter: Callable[[], Any]
    setter: Callable[[Any], None]
    min: int | None = None
    max: int | None = None
    step: int | None = None
    choices: list[str] | None = None


class _IPCWindow:
    """A hidden, ordinary top-level window (findable via FindWindow) that
    decodes WM_COPYDATA payloads and hands them to a callback -- an action
    id (dwData=1) to `on_action`, a settings ``(kind, body)`` (dwData=2) to
    `on_settings_message`."""

    def __init__(
        self,
        title: str,
        on_action: Callable[[str], None],
        on_settings_message: Callable[[str, dict[str, Any]], None],
    ) -> None:
        self._on_action = on_action
        self._on_settings_message = on_settings_message
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
            decoded = read_copydata_struct(lparam)
            if decoded is not None:
                dw_data, raw = decoded
                if dw_data == SETTINGS_PROTOCOL_VERSION:
                    envelope = decode_settings_payload(raw)
                    if envelope is not None:
                        self._on_settings_message(*envelope)
                elif raw:
                    self._on_action(raw.split(b"\x00", 1)[0].decode("utf-8"))
            return True
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


class FastToolPalette:
    """Runs the hidden `FastToolIPC::<tool_id>` window and queues received
    action ids and settings messages. Call poll() from the host app's own
    loop (e.g. a Tk `after(...)` tick) to drain and dispatch them safely on
    the host's thread.
    """

    def __init__(self, tool_id: str, ready_timeout_s: float = 5.0) -> None:
        self._tool_id = tool_id
        self._queue: queue.Queue[str] = queue.Queue()
        self._settings_queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        self._setting_ids: list[str] = []
        self._setting_defs: dict[str, _SettingDef] = {}
        self._ready = threading.Event()
        self.hwnd: int | None = None
        self._thread = threading.Thread(
            target=self._run, args=(f"FastToolIPC::{tool_id}",), daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=ready_timeout_s)

    def _run(self, title: str) -> None:
        # NOT self._settings_queue.put directly: queue.Queue.put's signature
        # is put(item, block=True, timeout=None), so passing it as a 2-arg
        # (kind, body) callback would silently misroute `body` into `block`
        # instead of storing a (kind, body) tuple.
        window = _IPCWindow(
            title, self._queue.put, lambda kind, body: self._settings_queue.put((kind, body))
        )
        self.hwnd = window.hwnd
        self._ready.set()
        win32gui.PumpMessages()

    def add_setting(
        self,
        setting_id: str,
        label: str,
        type_: str,
        getter: Callable[[], Any],
        setter: Callable[[Any], None],
        *,
        min: int | None = None,
        max: int | None = None,
        step: int | None = None,
        choices: list[str] | None = None,
    ) -> None:
        """Expose one of this tool's own settings to the host (CONTRACT.md's
        "Settings protocol (v2)"). `type_` is one of "shortcut"/"int"/
        "bool"/"enum"/"color". `getter` takes no args and must return the
        current value already in CONTRACT.md's neutral format (e.g. a
        "shortcut" value like "alt+q"); `setter` takes one value in that
        same neutral format and is responsible for persisting it AND
        reloading whatever depends on it -- this class owns neither, only
        the wire format. Both are called from poll()'s caller thread, never
        the background IPC thread (see this module's docstring)."""
        self._setting_ids.append(setting_id)
        self._setting_defs[setting_id] = _SettingDef(
            label, type_, getter, setter, min, max, step, choices
        )

    def poll(self) -> list[str]:
        """Return and clear all action ids received since the last poll().

        Also drains and processes any settings messages received since the
        last call -- a `describe` triggers a snapshot reply, a `set` calls
        the matching registered setter then replies with a fresh snapshot --
        all synchronously, on the calling thread, before this returns.
        """
        self._drain_settings()
        actions = []
        while True:
            try:
                actions.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return actions

    def _drain_settings(self) -> None:
        while True:
            try:
                kind, body = self._settings_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "describe":
                self._send_snapshot()
            elif kind == "set":
                self._handle_set(body)
            # an unrecognized kind is silently ignored, per CONTRACT.md

    def _handle_set(self, body: dict[str, Any]) -> None:
        setting_id = body.get("id")
        definition = self._setting_defs.get(setting_id) if setting_id is not None else None
        if definition is None:
            return  # unknown setting id -- silently ignored, per CONTRACT.md
        definition.setter(body.get("value"))
        # No separate ack -- this snapshot both confirms the change took
        # effect and gives the host the tool's authoritative post-apply
        # state (a setter may clamp/normalize what it was asked to store).
        self._send_snapshot()

    def _send_snapshot(self) -> None:
        host_hwnd = find_window(HOST_IPC_TITLE)
        if host_hwnd is None:
            return  # host not running / no reply window yet -- nothing to retry onto
        settings = [self._encode_setting(setting_id) for setting_id in self._setting_ids]
        send_settings(host_hwnd, "snapshot", {"tool_id": self._tool_id, "settings": settings})

    def _encode_setting(self, setting_id: str) -> dict[str, Any]:
        definition = self._setting_defs[setting_id]
        entry: dict[str, Any] = {
            "id": setting_id,
            "label": definition.label,
            "type": definition.type,
            "value": definition.getter(),
        }
        if definition.min is not None:
            entry["min"] = definition.min
        if definition.max is not None:
            entry["max"] = definition.max
        if definition.step is not None:
            entry["step"] = definition.step
        if definition.choices is not None:
            entry["choices"] = list(definition.choices)
        return entry
