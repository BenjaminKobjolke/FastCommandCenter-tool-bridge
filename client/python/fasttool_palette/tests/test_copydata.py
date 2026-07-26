import ctypes

from fasttool_palette.copydata import _COPYDATASTRUCT, decode_copydata


def test_decode_copydata_reads_utf8_action_id() -> None:
    payload = b"toggle\x00"
    buf = ctypes.create_string_buffer(payload)
    cds = _COPYDATASTRUCT(dwData=1, cbData=len(payload), lpData=ctypes.cast(buf, ctypes.c_void_p))

    assert decode_copydata(ctypes.addressof(cds)) == "toggle"


def test_decode_copydata_handles_non_ascii_utf8() -> None:
    payload = "Umlaut-ä-action".encode() + b"\x00"
    buf = ctypes.create_string_buffer(payload)
    cds = _COPYDATASTRUCT(dwData=1, cbData=len(payload), lpData=ctypes.cast(buf, ctypes.c_void_p))

    assert decode_copydata(ctypes.addressof(cds)) == "Umlaut-ä-action"


def test_decode_copydata_returns_none_for_null_lparam() -> None:
    assert decode_copydata(0) is None


def test_decode_copydata_returns_none_for_empty_payload() -> None:
    cds = _COPYDATASTRUCT(dwData=1, cbData=0, lpData=None)

    assert decode_copydata(ctypes.addressof(cds)) is None
