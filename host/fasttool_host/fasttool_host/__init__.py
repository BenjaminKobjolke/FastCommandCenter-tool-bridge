"""Host-side half of the FastTool bridge — see CONTRACT.md at the repo root."""

from .bridge import ToolAction, ToolBridge
from .manifest import ManifestError, ToolActionDef, ToolLaunch, ToolManifest
from .settings import SettingsError, ToolSetting, ToolSettings

__all__ = [
    "ManifestError",
    "SettingsError",
    "ToolAction",
    "ToolActionDef",
    "ToolBridge",
    "ToolLaunch",
    "ToolManifest",
    "ToolSetting",
    "ToolSettings",
]
