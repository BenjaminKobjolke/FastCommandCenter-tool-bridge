import json
from pathlib import Path

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
