"""Win32 WM_COPYDATA send + window discovery — the host's send side of CONTRACT.md.

The COPYDATASTRUCT definition here is deliberately duplicated (~15 lines) in
client/python/fasttool_palette's copydata module instead of shared via a
third package — not worth an extra package for a struct this small.

Settings-protocol (v2) framing lives here too: ``encode_settings_payload``/
``decode_settings_payload`` are the pure kind+JSON envelope step (dwData=2,
see CONTRACT.md's "Settings protocol (v2)"), ``send_settings`` is their
send-side counterpart to ``send_action``, and ``read_copydata_struct`` is the
receive-side counterpart used by ``receiver.py`` to pull ``(dwData, raw
bytes)`` out of an incoming message before deciding which envelope decoder
applies.
"""

from __future__ import annotations

import ctypes
import json
from ctypes import wintypes
from typing import Any

WM_COPYDATA = 0x004A
SETTINGS_PROTOCOL_VERSION = 2


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


def encode_settings_payload(kind: str, body: dict[str, Any]) -> bytes:
    """Build the WM_COPYDATA payload for a settings message: the ``kind`` tag
    (``"describe"``/``"snapshot"``/``"set"``), then the JSON body, each its
    own NUL-terminated UTF-8 string -- see CONTRACT.md's "Settings protocol
    (v2)" envelope."""
    payload = kind.encode("utf-8") + b"\x00"
    payload += json.dumps(body).encode("utf-8") + b"\x00"
    return payload


def decode_settings_payload(payload: bytes) -> tuple[str, dict[str, Any]] | None:
    """Inverse of ``encode_settings_payload``. Returns None for a malformed
    payload (missing NUL separators, invalid JSON, a non-object body) rather
    than raising -- an unrecognized or corrupt message must never crash the
    host."""
    parts = payload.split(b"\x00")
    if len(parts) < 3:  # "kind\0json\0" splits into [kind, json, b""]
        return None
    kind_bytes, body_bytes = parts[0], parts[1]
    try:
        kind = kind_bytes.decode("utf-8")
        body = json.loads(body_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(body, dict):
        return None
    return kind, body


def send_settings(hwnd: int, kind: str, body: dict[str, Any]) -> bool:
    """Send a settings message (dwData=2) to hwnd via WM_COPYDATA. Returns
    whether the receiver accepted it. Used for both directions of the
    settings protocol -- the host sends ``describe``/``set`` to a tool's
    ``FastToolIPC::<id>`` window with this; a tool's client shim sends
    ``snapshot`` to the host's ``FastToolIPC::host`` window the same way."""
    payload = encode_settings_payload(kind, body)
    buf = ctypes.create_string_buffer(payload)
    cds = _COPYDATASTRUCT(
        dwData=SETTINGS_PROTOCOL_VERSION,
        cbData=len(payload),
        lpData=ctypes.cast(buf, ctypes.c_void_p),
    )
    result = ctypes.windll.user32.SendMessageW(
        wintypes.HWND(hwnd), WM_COPYDATA, wintypes.WPARAM(0), ctypes.byref(cds)
    )
    return bool(result)


def read_copydata_struct(lparam: int) -> tuple[int, bytes] | None:
    """Extract ``(dwData, raw lpData bytes)`` from an incoming WM_COPYDATA
    message's lParam. Returns None for a null/empty message rather than
    raising -- the receive side of the settings protocol (``receiver.py``)
    decides what to do with an unrecognized ``dwData`` from there, but must
    never crash the host on one."""
    if not lparam:
        return None
    cds = ctypes.cast(lparam, ctypes.POINTER(_COPYDATASTRUCT)).contents
    if not cds.lpData or cds.cbData == 0:
        return None
    raw = ctypes.string_at(cds.lpData, cds.cbData)
    return int(cds.dwData or 0), raw
