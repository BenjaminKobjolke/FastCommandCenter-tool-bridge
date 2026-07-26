"""Decode a WM_COPYDATA message's payload — the client's receive side of
CONTRACT.md, for both action-fire (v1) and the settings protocol (v2). Also
the client's SEND side of v2: a tool reports its settings to the host's
`FastToolIPC::host` window the same way the host reaches a tool, just
reversed (find_window + send_settings, mirroring fasttool_host.copydata's
find_window/send_action).

The COPYDATASTRUCT definition here is deliberately duplicated (~10 lines) in
host/fasttool_host's copydata module instead of shared via a third package —
not worth an extra package for a struct this small. Pure ctypes, no windll
calls except in find_window/send_settings, so the pure decode/encode
functions are testable without creating a real window.
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
        ("cbData", ctypes.c_uint32),
        ("lpData", ctypes.c_void_p),
    ]


def read_copydata_struct(lparam: int) -> tuple[int, bytes] | None:
    """Extract ``(dwData, raw lpData bytes)`` from a WM_COPYDATA message's
    lParam -- the generic read step behind both decode_copydata (action,
    dwData=1) and decode_settings_payload (settings, dwData=2). Returns None
    for a null/empty message rather than raising -- an unrecognized message
    should never take a tool down."""
    if not lparam:
        return None
    cds = ctypes.cast(lparam, ctypes.POINTER(_COPYDATASTRUCT)).contents
    if not cds.lpData or cds.cbData == 0:
        return None
    raw = ctypes.string_at(cds.lpData, cds.cbData)
    return int(cds.dwData or 0), raw


def decode_copydata(lparam: int) -> str | None:
    """Extract the UTF-8 action id from a WM_COPYDATA message's lParam.

    Returns None for an empty/malformed payload rather than raising — an
    unrecognized message should never take a tool down.
    """
    decoded = read_copydata_struct(lparam)
    if decoded is None:
        return None
    _, raw = decoded
    return raw.split(b"\x00", 1)[0].decode("utf-8")


def decode_settings_payload(payload: bytes) -> tuple[str, dict[str, Any]] | None:
    """Inverse of encode_settings_payload: ``"<kind>\\0<json>\\0"`` bytes ->
    ``(kind, body)``. Returns None for a malformed payload (missing NUL
    separators, invalid JSON, a non-object body) rather than raising -- same
    rule as decode_copydata."""
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


def encode_settings_payload(kind: str, body: dict[str, Any]) -> bytes:
    """Build the WM_COPYDATA payload for a settings message: the ``kind``
    tag, then the JSON body, each its own NUL-terminated UTF-8 string -- see
    CONTRACT.md's "Settings protocol (v2)" envelope."""
    payload = kind.encode("utf-8") + b"\x00"
    payload += json.dumps(body).encode("utf-8") + b"\x00"
    return payload


def find_window(title: str) -> int | None:
    """Return the hwnd of the top-level window with this exact title, or
    None. Used to resolve the host's `FastToolIPC::host` reply window."""
    hwnd = ctypes.windll.user32.FindWindowW(None, title)
    return hwnd or None


def send_settings(hwnd: int, kind: str, body: dict[str, Any]) -> bool:
    """Send a settings message (dwData=2) to hwnd via WM_COPYDATA. Returns
    whether the receiver accepted it. This is how a tool reports its
    `snapshot` to the host's `FastToolIPC::host` window."""
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
