"""Host-side half of the FastTool bridge — see CONTRACT.md at the repo root."""

from .bridge import ToolAction, ToolBridge
from .manifest import ManifestError, ToolActionDef, ToolLaunch, ToolManifest, ToolTextProviderDef
from .settings import SettingsError, ToolSetting, ToolSettings
from .text_provider import (
    TextProviderError,
    ToolTextProvider,
    ToolTextProviderActivation,
    ToolTextResult,
    ToolTextResults,
)

__all__ = [
    "ManifestError",
    "SettingsError",
    "ToolAction",
    "ToolActionDef",
    "ToolBridge",
    "ToolLaunch",
    "ToolManifest",
    "ToolTextProviderDef",
    "ToolSetting",
    "ToolSettings",
    "TextProviderError",
    "ToolTextProvider",
    "ToolTextProviderActivation",
    "ToolTextResult",
    "ToolTextResults",
]
