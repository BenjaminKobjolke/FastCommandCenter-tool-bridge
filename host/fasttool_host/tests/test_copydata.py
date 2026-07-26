"""encode_action_payload/encode_settings_payload -- the pure framing steps
behind send_action's/send_settings's WM_COPYDATA lpData. send_action/
send_settings themselves need a real hwnd (ctypes/Win32) and aren't exercised
here, same reason ToolBridge.fire()'s QProcess/QTimer path isn't unit-tested
(see fasttool_host's own docstrings). read_copydata_struct is exercised via
its own real-hwnd path in test_receiver.py."""

from fasttool_host.copydata import (
    decode_settings_payload,
    encode_action_payload,
    encode_settings_payload,
)


def test_action_only_is_action_id_plus_single_nul() -> None:
    assert encode_action_payload("toggle") == b"toggle\x00"


def test_no_yield_chords_matches_action_only() -> None:
    assert encode_action_payload("toggle", None) == b"toggle\x00"
    assert encode_action_payload("toggle", []) == b"toggle\x00"


def test_yield_chords_appended_as_second_nul_terminated_string() -> None:
    assert encode_action_payload("toggle", ["alt+q"]) == b"toggle\x00alt+q\x00"


def test_multiple_yield_chords_are_space_joined() -> None:
    payload = encode_action_payload("toggle", ["alt+q", "ctrl+alt+space"])
    assert payload == b"toggle\x00alt+q ctrl+alt+space\x00"


def test_a_receiver_reading_only_the_first_nul_sees_just_the_action_id() -> None:
    # Backward compatibility: an older client's null-terminated read stops at
    # the first \x00 regardless of what follows.
    payload = encode_action_payload("toggle", ["alt+q"])
    first_nul = payload.index(b"\x00")
    assert payload[:first_nul].decode("utf-8") == "toggle"


def test_encode_settings_payload_is_kind_then_json_each_nul_terminated() -> None:
    payload = encode_settings_payload("describe", {})
    assert payload == b"describe\x00{}\x00"


def test_decode_settings_payload_round_trips_encode() -> None:
    body = {"tool_id": "fastkeyboardmouse", "settings": [{"id": "x", "value": 1}]}
    payload = encode_settings_payload("snapshot", body)

    assert decode_settings_payload(payload) == ("snapshot", body)


def test_decode_settings_payload_returns_none_for_missing_second_nul() -> None:
    assert decode_settings_payload(b"describe\x00") is None


def test_decode_settings_payload_returns_none_for_invalid_json() -> None:
    assert decode_settings_payload(b"describe\x00{not json}\x00") is None


def test_decode_settings_payload_returns_none_for_non_object_body() -> None:
    assert decode_settings_payload(b"describe\x00[1,2,3]\x00") is None


def test_decode_settings_payload_returns_none_for_empty_bytes() -> None:
    assert decode_settings_payload(b"") is None
