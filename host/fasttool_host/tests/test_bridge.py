import json
from pathlib import Path
from unittest.mock import patch

from fasttool_host.bridge import ToolBridge

VALID = {
    "id": "fastkeyboardmouse",
    "name": "Fast Keyboard Mouse",
    "ipc_title": "FastToolIPC::fastkeyboardmouse",
    "launch": {"exe": "FastKeyboardMouse.exe", "args": ["--palette"]},
    "actions": [{"id": "toggle", "label": "Toggle mouse mode"}],
}

MULTI_ACTION = {
    "id": "fasttextsuggester",
    "name": "Fast Text Suggester",
    "ipc_title": "FastToolIPC::fasttextsuggester",
    "launch": {"exe": "FastTextSuggester.exe", "args": ["--palette"]},
    "actions": [
        {"id": "capture", "label": "Capture"},
        {"id": "suggestion", "label": "Suggestion"},
    ],
}


def write_manifest(tool_dir: Path, data: dict) -> None:
    tool_dir.mkdir()
    (tool_dir / "fasttool.json").write_text(json.dumps(data), encoding="utf-8")


def test_load_derives_one_command_per_action(tmp_path: Path) -> None:
    tool_a = tmp_path / "a"
    write_manifest(tool_a, VALID)
    tool_b = tmp_path / "b"
    write_manifest(tool_b, MULTI_ACTION)

    actions = ToolBridge().load([tool_a, tool_b])

    command_ids = {a.command_id for a in actions}
    assert command_ids == {
        "tool.fastkeyboardmouse.toggle",
        "tool.fasttextsuggester.capture",
        "tool.fasttextsuggester.suggestion",
    }


def test_load_action_title_combines_tool_name_and_action_label(tmp_path: Path) -> None:
    tool_a = tmp_path / "a"
    write_manifest(tool_a, VALID)

    actions = ToolBridge().load([tool_a])

    assert actions[0].title == "Fast Keyboard Mouse: Toggle mouse mode"


def test_fire_with_unknown_tool_id_is_a_no_op(tmp_path: Path) -> None:
    bridge = ToolBridge()
    bridge.load([])

    bridge.fire("no-such-tool", "toggle")  # must not raise


def test_load_with_no_manifests_returns_empty_list(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    actions = ToolBridge().load([empty_dir])

    assert actions == []


def test_manifests_exposes_every_loaded_manifest(tmp_path: Path) -> None:
    tool_a = tmp_path / "a"
    write_manifest(tool_a, VALID)
    tool_b = tmp_path / "b"
    write_manifest(tool_b, MULTI_ACTION)
    bridge = ToolBridge()

    bridge.load([tool_a, tool_b])

    ids = {m.id for m in bridge.manifests}
    names = {m.name for m in bridge.manifests}
    assert ids == {"fastkeyboardmouse", "fasttextsuggester"}
    assert names == {"Fast Keyboard Mouse", "Fast Text Suggester"}


def test_manifests_is_empty_before_load(tmp_path: Path) -> None:
    bridge = ToolBridge()

    assert bridge.manifests == []


def test_describe_settings_with_unknown_tool_id_is_a_no_op(tmp_path: Path) -> None:
    bridge = ToolBridge()
    bridge.load([])

    bridge.describe_settings("no-such-tool")  # must not raise


def test_set_setting_with_unknown_tool_id_is_a_no_op(tmp_path: Path) -> None:
    bridge = ToolBridge()
    bridge.load([])

    bridge.set_setting("no-such-tool", "ToggleKey", "alt+q")  # must not raise


def test_settings_received_signal_exists_and_is_connectable(tmp_path: Path) -> None:
    bridge = ToolBridge()

    received: list[object] = []
    bridge.settings_received.connect(received.append)  # must not raise


def test_shutdown_with_no_launched_processes_stops_the_settings_receiver(tmp_path: Path) -> None:
    bridge = ToolBridge()
    bridge.load([])

    bridge.shutdown()  # must not raise; also tears down the receiver window


def test_query_text_sends_only_to_a_declared_provider(tmp_path: Path) -> None:
    tool_dir = tmp_path / "text"
    write_manifest(
        tool_dir,
        {
            **VALID,
            "text_providers": [{"id": "suggestions", "label": "FastTextSuggester"}],
        },
    )
    bridge = ToolBridge()
    bridge.load([tool_dir])

    with patch.object(bridge, "_send_or_launch") as send:
        bridge.query_text("fastkeyboardmouse", "suggestions", "s", "r", "hello")
        bridge.query_text("fastkeyboardmouse", "unknown", "s", "r", "hello")

    send.assert_called_once()
