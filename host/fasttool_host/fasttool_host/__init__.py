"""Host-side half of the FastTool bridge — see CONTRACT.md at the repo root."""

from .bridge import ToolAction, ToolBridge
from .manifest import ManifestError, ToolActionDef, ToolLaunch, ToolManifest

__all__ = [
    "ManifestError",
    "ToolAction",
    "ToolActionDef",
    "ToolBridge",
    "ToolLaunch",
    "ToolManifest",
]
