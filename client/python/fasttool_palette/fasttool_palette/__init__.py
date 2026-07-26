"""Python client shim for the FastTool bridge — see CONTRACT.md at the repo root."""

from .mode import PALETTE_FLAG, palette_mode
from .window import FastToolPalette

__all__ = ["PALETTE_FLAG", "FastToolPalette", "palette_mode"]
