import json
from pathlib import Path

import pytest

from fasttool_host.manifest import ManifestError, discover_manifests, load_manifest

VALID = {
    "id": "fastkeyboardmouse",
    "name": "Fast Keyboard Mouse",
    "ipc_title": "FastToolIPC::fastkeyboardmouse",
    "launch": {"exe": "FastKeyboardMouse.exe", "args": ["--palette"]},
    "actions": [{"id": "toggle", "label": "Toggle mouse mode"}],
}


def write_manifest(tmp_path: Path, data: dict, name: str = "fasttool.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_manifest_parses_valid_file(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, VALID)

    manifest = load_manifest(path)

    assert manifest.id == "fastkeyboardmouse"
    assert manifest.name == "Fast Keyboard Mouse"
    assert manifest.ipc_title == "FastToolIPC::fastkeyboardmouse"
    assert manifest.launch.exe == "FastKeyboardMouse.exe"
    assert manifest.launch.args == ("--palette",)
    assert len(manifest.actions) == 1
    assert manifest.actions[0].id == "toggle"
    assert manifest.actions[0].label == "Toggle mouse mode"
    assert manifest.manifest_dir == tmp_path
    assert manifest.exe_path == (tmp_path / "FastKeyboardMouse.exe").resolve()


def test_load_manifest_rejects_mismatched_ipc_title(tmp_path: Path) -> None:
    data = {**VALID, "ipc_title": "FastToolIPC::wrong"}
    path = write_manifest(tmp_path, data)

    with pytest.raises(ManifestError, match="ipc_title"):
        load_manifest(path)


def test_load_manifest_rejects_missing_field(tmp_path: Path) -> None:
    data = {k: v for k, v in VALID.items() if k != "launch"}
    path = write_manifest(tmp_path, data)

    with pytest.raises(ManifestError, match="missing required field"):
        load_manifest(path)


def test_load_manifest_rejects_empty_actions(tmp_path: Path) -> None:
    data = {**VALID, "actions": []}
    path = write_manifest(tmp_path, data)

    with pytest.raises(ManifestError, match="actions must not be empty"):
        load_manifest(path)


def test_load_manifest_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "fasttool.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ManifestError, match="could not read/parse"):
        load_manifest(path)


def test_discover_manifests_skips_folders_without_manifest(tmp_path: Path) -> None:
    with_manifest = tmp_path / "with_manifest"
    with_manifest.mkdir()
    write_manifest(with_manifest, VALID)
    without_manifest = tmp_path / "without_manifest"
    without_manifest.mkdir()

    manifests = discover_manifests([with_manifest, without_manifest])

    assert len(manifests) == 1
    assert manifests[0].id == "fastkeyboardmouse"


def test_discover_manifests_skips_malformed_manifest_instead_of_raising(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    write_manifest(broken, {**VALID, "ipc_title": "FastToolIPC::wrong"})
    healthy = tmp_path / "healthy"
    healthy.mkdir()
    write_manifest(healthy, {**VALID, "id": "other", "ipc_title": "FastToolIPC::other"})

    manifests = discover_manifests([broken, healthy])

    assert [m.id for m in manifests] == ["other"]


def test_discover_manifests_handles_multiple_tools(tmp_path: Path) -> None:
    tool_a = tmp_path / "a"
    tool_a.mkdir()
    write_manifest(tool_a, VALID)
    tool_b = tmp_path / "b"
    tool_b.mkdir()
    write_manifest(
        tool_b,
        {
            **VALID,
            "id": "fasttextsuggester",
            "ipc_title": "FastToolIPC::fasttextsuggester",
            "actions": [
                {"id": "capture", "label": "Capture"},
                {"id": "suggestion", "label": "Suggestion"},
            ],
        },
    )

    manifests = discover_manifests([tool_a, tool_b])

    assert {m.id for m in manifests} == {"fastkeyboardmouse", "fasttextsuggester"}
