"""Parse a tool's fasttool.json into typed manifest objects.

Pure stdlib, no win32 — this is the win32-free part of the bridge, covered by
unit tests. See CONTRACT.md for the manifest shape this parses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class ManifestError(ValueError):
    """A fasttool.json is missing a required field or otherwise malformed."""


@dataclass(frozen=True)
class ToolLaunch:
    exe: str
    args: tuple[str, ...]


@dataclass(frozen=True)
class ToolActionDef:
    id: str
    label: str


@dataclass(frozen=True)
class ToolTextProviderDef:
    id: str
    label: str
    min_chars: int = 0


@dataclass(frozen=True)
class ToolManifest:
    id: str
    name: str
    ipc_title: str
    launch: ToolLaunch
    actions: tuple[ToolActionDef, ...]
    text_providers: tuple[ToolTextProviderDef, ...]
    manifest_dir: Path

    @property
    def exe_path(self) -> Path:
        return (self.manifest_dir / self.launch.exe).resolve()


def load_manifest(path: Path) -> ToolManifest:
    """Parse and validate one fasttool.json file. Raises ManifestError on any problem."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"{path}: could not read/parse manifest: {exc}") from exc

    try:
        tool_id = data["id"]
        name = data["name"]
        ipc_title = data["ipc_title"]
        launch_data = data["launch"]
        actions_data = data.get("actions", [])
        text_providers_data = data.get("text_providers", [])
    except KeyError as exc:
        raise ManifestError(f"{path}: missing required field {exc}") from exc

    expected_title = f"FastToolIPC::{tool_id}"
    if ipc_title != expected_title:
        raise ManifestError(f"{path}: ipc_title {ipc_title!r} must equal {expected_title!r}")

    try:
        launch = ToolLaunch(exe=launch_data["exe"], args=tuple(launch_data.get("args", ())))
    except KeyError as exc:
        raise ManifestError(f"{path}: launch missing required field {exc}") from exc

    try:
        actions = tuple(ToolActionDef(id=a["id"], label=a["label"]) for a in actions_data)
    except KeyError as exc:
        raise ManifestError(f"{path}: action missing required field {exc}") from exc

    try:
        text_providers = tuple(
            ToolTextProviderDef(
                id=provider["id"],
                label=provider["label"],
                min_chars=int(provider.get("min_chars", 0)),
            )
            for provider in text_providers_data
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ManifestError(f"{path}: malformed text provider: {exc}") from exc

    if not actions and not text_providers:
        raise ManifestError(f"{path}: actions and text_providers must not both be empty")

    return ToolManifest(
        id=tool_id,
        name=name,
        ipc_title=ipc_title,
        launch=launch,
        actions=actions,
        text_providers=text_providers,
        manifest_dir=path.parent,
    )


def discover_manifests(tool_dirs: list[Path]) -> list[ToolManifest]:
    """Load fasttool.json from each folder that has one.

    Both a missing manifest and a malformed one are skipped, not raised: one
    bad tool folder must not take down the whole host (this runs on every
    app startup, not just when a folder is newly added).
    """
    manifests = []
    for tool_dir in tool_dirs:
        manifest_path = Path(tool_dir) / "fasttool.json"
        if not manifest_path.is_file():
            continue
        try:
            manifests.append(load_manifest(manifest_path))
        except ManifestError:
            continue
    return manifests
