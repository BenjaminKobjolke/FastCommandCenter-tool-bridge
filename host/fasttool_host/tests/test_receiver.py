"""End-to-end: real WM_COPYDATA send (via ctypes, mirroring the client
shim's send side, see fasttool_palette's own test_window.py) into a real
SettingsReceiver window, verifying the whole receive pipeline for the
settings protocol (v2) -- not just the pure-function pieces covered by
test_copydata.py and test_settings.py.

Payload bytes are hand-built here rather than via fasttool_host.copydata's
own encode_settings_payload, same reasoning as fasttool_palette's test_window
tests: exercising the receive path independent of this repo's own send-side
implementation.
"""

import ctypes
import json
import time
from ctypes import wintypes

from PySide6.QtCore import QCoreApplication

from fasttool_host.receiver import SettingsReceiver
from fasttool_host.settings import ToolSettings

WM_COPYDATA = 0x004A


class _COPYDATASTRUCT(ctypes.Structure):
    _fields_ = [
        ("dwData", ctypes.c_void_p),
        ("cbData", wintypes.DWORD),
        ("lpData", ctypes.c_void_p),
    ]


def _send_settings_message(hwnd: int, kind: str, body: dict) -> None:
    payload = kind.encode("utf-8") + b"\x00" + json.dumps(body).encode("utf-8") + b"\x00"
    buf = ctypes.create_string_buffer(payload)
    cds = _COPYDATASTRUCT(dwData=2, cbData=len(payload), lpData=ctypes.cast(buf, ctypes.c_void_p))
    ctypes.windll.user32.SendMessageW(
        wintypes.HWND(hwnd), WM_COPYDATA, wintypes.WPARAM(0), ctypes.byref(cds)
    )


def _app() -> QCoreApplication:
    # SettingsReceiver's emit() happens off the GUI thread; delivering a
    # queued cross-thread signal requires an event loop to actually spin
    # (see core/hotkey_bridge.py in FastCommandCenter for the same pattern
    # this mirrors) -- a bare QCoreApplication is enough, no widgets needed.
    return QCoreApplication.instance() or QCoreApplication([])


def _pump_until(condition, timeout_s: float = 2.0) -> bool:
    app = _app()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_receiver_emits_snapshot_received_on_incoming_snapshot() -> None:
    _app()
    receiver = SettingsReceiver()
    assert receiver.hwnd is not None
    received: list[ToolSettings] = []
    receiver.snapshot_received.connect(received.append)

    body = {
        "tool_id": "fastkeyboardmouse",
        "settings": [
            {
                "id": "ToggleKey",
                "label": "Toggle mouse mode",
                "type": "shortcut",
                "value": "alt+q",
            }
        ],
    }
    _send_settings_message(receiver.hwnd, "snapshot", body)

    assert _pump_until(lambda: len(received) == 1)
    assert received[0].tool_id == "fastkeyboardmouse"
    assert received[0].settings[0].id == "ToggleKey"
    assert received[0].settings[0].value == "alt+q"

    receiver.stop()


def test_receiver_ignores_non_snapshot_kind() -> None:
    _app()
    receiver = SettingsReceiver()
    assert receiver.hwnd is not None
    received: list[ToolSettings] = []
    receiver.snapshot_received.connect(received.append)

    _send_settings_message(receiver.hwnd, "describe", {})
    _pump_until(lambda: False, timeout_s=0.3)  # nothing should ever arrive

    assert received == []

    receiver.stop()


def test_receiver_ignores_malformed_snapshot_body() -> None:
    _app()
    receiver = SettingsReceiver()
    assert receiver.hwnd is not None
    received: list[ToolSettings] = []
    receiver.snapshot_received.connect(received.append)

    _send_settings_message(receiver.hwnd, "snapshot", {"tool_id": "x"})  # missing "settings"
    _pump_until(lambda: False, timeout_s=0.3)

    assert received == []

    receiver.stop()
