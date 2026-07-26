"""Win32 WM_COPYDATA send + window discovery — the host's send side of CONTRACT.md.

The COPYDATASTRUCT definition here is deliberately duplicated (~15 lines) in
client/python/fasttool_palette's copydata module instead of shared via a
third package — not worth an extra package for a struct this small.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

WM_COPYDATA = 0x004A


class _COPYDATASTRUCT(ctypes.Structure):
    _fields_ = [
        ("dwData", ctypes.c_void_p),
        ("cbData", wintypes.DWORD),
        ("lpData", ctypes.c_void_p),
    ]


def find_window(title: str) -> int | None:
    """Return the hwnd of the top-level window with this exact title, or None."""
    hwnd = ctypes.windll.user32.FindWindowW(None, title)
    return hwnd or None


def encode_action_payload(action_id: str, yield_chords: list[str] | None = None) -> bytes:
    """Build the WM_COPYDATA payload bytes: the action id, optionally followed
    by a second NUL-terminated string listing the chords the host currently
    has registered (neutral format, space-separated -- see CONTRACT.md's
    "yield while active" section). A receiver that only reads up to the first
    NUL sees just the action id, so this is backward-compatible with older
    clients."""
    payload = action_id.encode("utf-8") + b"\x00"
    if yield_chords:
        payload += " ".join(yield_chords).encode("utf-8") + b"\x00"
    return payload


def send_action(
    hwnd: int,
    action_id: str,
    protocol_version: int = 1,
    yield_chords: list[str] | None = None,
) -> bool:
    """Send an action id to hwnd via WM_COPYDATA. Returns whether the receiver accepted it."""
    payload = encode_action_payload(action_id, yield_chords)
    buf = ctypes.create_string_buffer(payload)
    cds = _COPYDATASTRUCT(
        dwData=protocol_version,
        cbData=len(payload),
        lpData=ctypes.cast(buf, ctypes.c_void_p),
    )
    result = ctypes.windll.user32.SendMessageW(
        wintypes.HWND(hwnd), WM_COPYDATA, wintypes.WPARAM(0), ctypes.byref(cds)
    )
    return bool(result)
