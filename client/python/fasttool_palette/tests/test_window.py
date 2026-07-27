"""End-to-end: real WM_COPYDATA send (via ctypes, mirroring fasttool_host's
send side) into a real FastToolPalette window, verifying the whole receive
pipeline — not just the pure-function pieces covered by the other test files.
Also covers the settings protocol (v2): a fake `FastToolIPC::host` window
(_FakeHost, below) stands in for the real host so a describe/set round trip
can be observed without a real host process.
"""

import ctypes
import itertools
import json
import time
from ctypes import wintypes

import win32api
import win32gui

from fasttool_palette.copydata import decode_settings_payload, read_copydata_struct
from fasttool_palette.window import HOST_IPC_TITLE, FastToolPalette, TextSuggestion

WM_COPYDATA = 0x004A
_fake_host_class_ids = itertools.count()


class _COPYDATASTRUCT(ctypes.Structure):
    _fields_ = [
        ("dwData", ctypes.c_void_p),
        ("cbData", wintypes.DWORD),
        ("lpData", ctypes.c_void_p),
    ]


def _send(hwnd: int, action_id: str) -> None:
    payload = action_id.encode("utf-8") + b"\x00"
    buf = ctypes.create_string_buffer(payload)
    cds = _COPYDATASTRUCT(dwData=1, cbData=len(payload), lpData=ctypes.cast(buf, ctypes.c_void_p))
    ctypes.windll.user32.SendMessageW(
        wintypes.HWND(hwnd), WM_COPYDATA, wintypes.WPARAM(0), ctypes.byref(cds)
    )


def _send_settings_message(hwnd: int, kind: str, body: dict) -> None:
    payload = kind.encode("utf-8") + b"\x00" + json.dumps(body).encode("utf-8") + b"\x00"
    buf = ctypes.create_string_buffer(payload)
    cds = _COPYDATASTRUCT(dwData=2, cbData=len(payload), lpData=ctypes.cast(buf, ctypes.c_void_p))
    ctypes.windll.user32.SendMessageW(
        wintypes.HWND(hwnd), WM_COPYDATA, wintypes.WPARAM(0), ctypes.byref(cds)
    )


def _poll_until(palette: FastToolPalette, timeout_s: float = 2.0) -> list[str]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        received = palette.poll()
        if received:
            return received
        time.sleep(0.02)
    return []


class _FakeHost:
    """Stands in for the real host's `FastToolIPC::host` window: captures
    every settings message sent to it, so a tool's snapshot reply can be
    asserted on without a real host process. Each instance uses a unique
    window class name (tests construct several in one process; a window
    CLASS is process-wide, so a repeated fixed name would collide -- see
    fasttool_host's receiver.py, which has the same problem for real)."""

    def __init__(self) -> None:
        self.received: list[tuple[str, dict]] = []
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self._wndproc  # type: ignore[misc]
        wc.lpszClassName = f"FastToolPaletteTestFakeHost::{next(_fake_host_class_ids)}"  # type: ignore[misc]
        wc.hInstance = win32api.GetModuleHandle(None)  # type: ignore[misc]
        class_atom = win32gui.RegisterClass(wc)
        self.hwnd = win32gui.CreateWindow(
            class_atom, HOST_IPC_TITLE, 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None
        )

    def _wndproc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg == WM_COPYDATA:
            decoded = read_copydata_struct(lparam)
            if decoded is not None:
                dw_data, raw = decoded
                if dw_data == 2:
                    envelope = decode_settings_payload(raw)
                    if envelope is not None:
                        self.received.append(envelope)
            return True
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def close(self) -> None:
        win32gui.DestroyWindow(self.hwnd)


def _poll_settings_until(
    palette: FastToolPalette, fake_host: _FakeHost, timeout_s: float = 2.0
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        palette.poll()
        if fake_host.received:
            return True
        time.sleep(0.02)
    return False


def test_palette_receives_action_sent_via_wm_copydata() -> None:
    palette = FastToolPalette("test-tool-window-1")
    assert palette.hwnd is not None

    _send(palette.hwnd, "toggle")

    assert _poll_until(palette) == ["toggle"]


def test_poll_returns_empty_when_nothing_received() -> None:
    palette = FastToolPalette("test-tool-window-2")

    assert palette.poll() == []


def test_unrecognized_message_does_not_crash_the_window() -> None:
    palette = FastToolPalette("test-tool-window-3")
    assert palette.hwnd is not None

    ctypes.windll.user32.SendMessageW(wintypes.HWND(palette.hwnd), 0x0400, 0, 0)  # WM_USER

    assert palette.poll() == []


def test_describe_replies_with_a_snapshot_of_registered_settings() -> None:
    palette = FastToolPalette("test-tool-settings-1")
    assert palette.hwnd is not None
    fake_host = _FakeHost()
    try:
        state = {"speed": 20}
        palette.add_setting(
            "BaseSpeed",
            "Cursor speed",
            "int",
            getter=lambda: state["speed"],
            setter=lambda v: state.__setitem__("speed", v),
            min=1,
            max=100,
            step=1,
        )

        _send_settings_message(palette.hwnd, "describe", {})

        assert _poll_settings_until(palette, fake_host)
        kind, body = fake_host.received[0]
        assert kind == "snapshot"
        assert body == {
            "tool_id": "test-tool-settings-1",
            "settings": [
                {
                    "id": "BaseSpeed",
                    "label": "Cursor speed",
                    "type": "int",
                    "value": 20,
                    "min": 1,
                    "max": 100,
                    "step": 1,
                }
            ],
        }
    finally:
        fake_host.close()


def test_set_calls_the_registered_setter_and_replies_with_the_updated_snapshot() -> None:
    palette = FastToolPalette("test-tool-settings-2")
    assert palette.hwnd is not None
    fake_host = _FakeHost()
    try:
        state = {"speed": 20}
        palette.add_setting(
            "BaseSpeed",
            "Cursor speed",
            "int",
            getter=lambda: state["speed"],
            setter=lambda v: state.__setitem__("speed", v),
        )

        _send_settings_message(palette.hwnd, "set", {"id": "BaseSpeed", "value": 42})

        assert _poll_settings_until(palette, fake_host)
        assert state["speed"] == 42
        kind, body = fake_host.received[0]
        assert kind == "snapshot"
        assert body["settings"][0]["value"] == 42
    finally:
        fake_host.close()


def test_set_with_unknown_setting_id_is_silently_ignored() -> None:
    palette = FastToolPalette("test-tool-settings-3")
    assert palette.hwnd is not None
    fake_host = _FakeHost()
    try:
        setter_calls = []
        palette.add_setting(
            "X", "X", "bool", getter=lambda: True, setter=lambda v: setter_calls.append(v)
        )

        _send_settings_message(palette.hwnd, "set", {"id": "NoSuchSetting", "value": False})
        time.sleep(0.2)
        palette.poll()

        assert setter_calls == []
        assert fake_host.received == []
    finally:
        fake_host.close()


def test_text_query_runs_registered_provider_during_poll(monkeypatch) -> None:
    palette = FastToolPalette("test-tool-text-provider")
    sent = []

    def record_send(hwnd, version, kind, body):
        sent.append((hwnd, version, kind, body))
        return True

    monkeypatch.setattr("fasttool_palette.window.find_window", lambda _title: 123)
    monkeypatch.setattr("fasttool_palette.window.send_json", record_send)
    palette.add_text_provider(
        "suggestions",
        lambda query, session: [TextSuggestion(title=query, text=f"{session}:{query}")],
    )
    palette._text_queue.put(
        (
            "query",
            {
                "provider_id": "suggestions",
                "session_id": "session-1",
                "request_id": "request-1",
                "query": "hello",
            },
        )
    )

    palette.poll()

    assert sent[0][2] == "results"
    assert sent[0][3]["results"] == [
        {"title": "hello", "text": "session-1:hello", "subtitle": ""}
    ]
