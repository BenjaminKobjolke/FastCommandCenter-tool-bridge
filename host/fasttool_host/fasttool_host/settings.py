"""Typed models for a tool's own settings -- the host's half of CONTRACT.md's
"Settings protocol (v2)". These are a thin typed wrapper over a `snapshot`
message's JSON body, not a validator: CONTRACT.md's "Setting types" table is
the source of truth for what's valid per `type`. Pure stdlib, no win32 -- see
copydata.py for the wire encoding these travel over.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class SettingsError(ValueError):
    """A `snapshot` message's body is missing a required field or otherwise
    malformed. Callers decoding an incoming snapshot catch this and drop the
    message -- a malformed snapshot from one tool must not crash the host,
    same rule as ManifestError in manifest.py."""


@dataclass(frozen=True)
class ToolSetting:
    """One editable setting, as reported by a tool's `snapshot` message.

    `min`/`max`/`step` are meaningful for `type == "int"`; `choices` for
    `type == "enum"`; both are None for every other type.
    """

    id: str
    label: str
    type: str  # shortcut | int | bool | enum | color | string | directory
    value: Any
    min: int | None = None
    max: int | None = None
    step: int | None = None
    choices: tuple[str, ...] | None = None

    @staticmethod
    def from_dict(data: dict[str, Any]) -> ToolSetting:
        try:
            setting_id = data["id"]
            label = data["label"]
            setting_type = data["type"]
        except KeyError as exc:
            raise SettingsError(f"setting missing required field {exc}") from exc
        choices = data.get("choices")
        return ToolSetting(
            id=setting_id,
            label=label,
            type=setting_type,
            value=data.get("value"),
            min=data.get("min"),
            max=data.get("max"),
            step=data.get("step"),
            choices=tuple(choices) if choices is not None else None,
        )


@dataclass(frozen=True)
class ToolSettings:
    """A tool's full settings snapshot -- the payload of a `snapshot` message."""

    tool_id: str
    settings: tuple[ToolSetting, ...]

    @staticmethod
    def from_dict(data: dict[str, Any]) -> ToolSettings:
        try:
            tool_id = data["tool_id"]
            settings_data = data["settings"]
        except KeyError as exc:
            raise SettingsError(f"snapshot missing required field {exc}") from exc
        try:
            settings = tuple(ToolSetting.from_dict(s) for s in settings_data)
        except TypeError as exc:
            raise SettingsError("snapshot 'settings' must be a list") from exc
        return ToolSettings(tool_id=tool_id, settings=settings)
