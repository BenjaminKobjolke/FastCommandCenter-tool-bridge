"""encode_action_payload -- the pure framing step behind send_action's
WM_COPYDATA lpData. send_action itself needs a real hwnd (ctypes/Win32) and
isn't exercised here, same reason ToolBridge.fire()'s QProcess/QTimer path
isn't unit-tested (see fasttool_host's own docstrings)."""

from fasttool_host.copydata import encode_action_payload


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
