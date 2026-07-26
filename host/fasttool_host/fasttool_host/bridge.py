"""ToolBridge: turns fasttool.json manifests into bindable actions and fires them.

fire() runs on the Qt GUI thread (called from a palette command / hotkey
dispatch), so waiting for a just-launched tool to open its IPC window is done
via QTimer polling, never a blocking sleep — a blocking wait here would
freeze the whole palette while a tool starts up.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QProcess, QTimer

from .copydata import find_window, send_action
from .manifest import ToolManifest, discover_manifests

_LAUNCH_POLL_INTERVAL_MS = 50
_LAUNCH_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class ToolAction:
    """One bindable palette command, derived from a manifest action."""

    command_id: str
    title: str
    tool_id: str
    action_id: str


def _command_id(tool_id: str, action_id: str) -> str:
    return f"tool.{tool_id}.{action_id}"


class ToolBridge:
    """Loads fasttool.json manifests and fires their actions over WM_COPYDATA.

    Launches are QProcess-managed: a tool this bridge had to start is tracked
    and terminated on shutdown(). A tool found already running (via
    FindWindow) is left running — only processes this bridge itself launched
    are killed.
    """

    def __init__(self) -> None:
        self._manifests: dict[str, ToolManifest] = {}
        self._processes: dict[str, QProcess] = {}

    def load(self, tool_dirs: list[Path]) -> list[ToolAction]:
        self._manifests = {manifest.id: manifest for manifest in discover_manifests(tool_dirs)}
        return [
            ToolAction(
                command_id=_command_id(manifest.id, action.id),
                title=f"{manifest.name}: {action.label}",
                tool_id=manifest.id,
                action_id=action.id,
            )
            for manifest in self._manifests.values()
            for action in manifest.actions
        ]

    def fire(self, tool_id: str, action_id: str, yield_chords: list[str] | None = None) -> None:
        """Send ``action_id`` to the tool. ``yield_chords`` (neutral format,
        e.g. ["alt+q"]) is the set of chords the host currently has registered
        globally -- passed through to the tool so it can stop swallowing them
        while active (see CONTRACT.md's "yield while active" section)."""
        manifest = self._manifests.get(tool_id)
        if manifest is None:
            return
        hwnd = find_window(manifest.ipc_title)
        if hwnd is not None:
            send_action(hwnd, action_id, yield_chords=yield_chords)
            return
        self._launch(manifest)
        self._poll_for_window(
            manifest, action_id, time.monotonic() + _LAUNCH_TIMEOUT_S, yield_chords
        )

    def _launch(self, manifest: ToolManifest) -> None:
        existing = self._processes.get(manifest.id)
        if existing is not None and existing.state() != QProcess.ProcessState.NotRunning:
            return  # already launching/running from a previous fire()
        process = QProcess()
        process.setWorkingDirectory(str(manifest.manifest_dir))
        # These are GUI helper processes that never expect piped stdio; route
        # to the null device rather than QProcess's default pipes.
        process.setStandardInputFile(QProcess.nullDevice())
        process.setStandardOutputFile(QProcess.nullDevice())
        process.setStandardErrorFile(QProcess.nullDevice())
        process.start(str(manifest.exe_path), list(manifest.launch.args))
        self._processes[manifest.id] = process

    def _poll_for_window(
        self,
        manifest: ToolManifest,
        action_id: str,
        deadline: float,
        yield_chords: list[str] | None = None,
    ) -> None:
        hwnd = find_window(manifest.ipc_title)
        if hwnd is not None:
            send_action(hwnd, action_id, yield_chords=yield_chords)
            return
        if time.monotonic() >= deadline:
            return  # tool never opened its IPC window in time; drop the action
        QTimer.singleShot(
            _LAUNCH_POLL_INTERVAL_MS,
            lambda: self._poll_for_window(manifest, action_id, deadline, yield_chords),
        )

    def shutdown(self) -> None:
        """Terminate every tool instance this bridge itself launched."""
        for process in self._processes.values():
            if process.state() != QProcess.ProcessState.NotRunning:
                process.terminate()
                if not process.waitForFinished(2000):
                    process.kill()
        self._processes.clear()
