"""Decode a WM_COPYDATA message's payload — the client's receive side of
CONTRACT.md.

The COPYDATASTRUCT definition here is deliberately duplicated (~10 lines) in
host/fasttool_host's copydata module instead of shared via a third package —
not worth an extra package for a struct this small. Pure ctypes, no windll
calls, so this is testable without creating a real window.
"""

from __future__ import annotations

import ctypes


class _COPYDATASTRUCT(ctypes.Structure):
    _fields_ = [
        ("dwData", ctypes.c_void_p),
        ("cbData", ctypes.c_uint32),
        ("lpData", ctypes.c_void_p),
    ]


def decode_copydata(lparam: int) -> str | None:
    """Extract the UTF-8 action id from a WM_COPYDATA message's lParam.

    Returns None for an empty/malformed payload rather than raising — an
    unrecognized message should never take a tool down.
    """
    if not lparam:
        return None
    cds = ctypes.cast(lparam, ctypes.POINTER(_COPYDATASTRUCT)).contents
    if not cds.lpData or cds.cbData == 0:
        return None
    raw = ctypes.string_at(cds.lpData, cds.cbData)
    return raw.split(b"\x00", 1)[0].decode("utf-8")
