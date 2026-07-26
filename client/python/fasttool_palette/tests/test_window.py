"""End-to-end: real WM_COPYDATA send (via ctypes, mirroring fasttool_host's
send side) into a real FastToolPalette window, verifying the whole receive
pipeline — not just the pure-function pieces covered by the other test files.
"""

import ctypes
import time
from ctypes import wintypes

from fasttool_palette import FastToolPalette

WM_COPYDATA = 0x004A


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


def _poll_until(palette: FastToolPalette, timeout_s: float = 2.0) -> list[str]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        received = palette.poll()
        if received:
            return received
        time.sleep(0.02)
    return []


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
