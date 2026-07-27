"""ToolBridge: turns fasttool.json manifests into bindable actions and fires
them, and (CONTRACT.md's "Settings protocol (v2)") asks a tool to report or
change its own settings.

fire()/describe_settings()/set_setting() all run on the Qt GUI thread (called
from a palette command / hotkey dispatch), so waiting for a just-launched
tool to open its IPC window is done via QTimer polling, never a blocking
sleep — a blocking wait here would freeze the whole palette while a tool
starts up.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QProcess, QTimer

from .copydata import (
    TEXT_PROVIDER_PROTOCOL_VERSION,
    find_window,
    send_action,
    send_json,
    send_settings,
)
from .manifest import ToolManifest, discover_manifests
from .receiver import SettingsReceiver

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
        # Created eagerly, not on first describe_settings()/set_setting()
        # call: a caller wires settings_received once at startup (see
        # FastCommandCenter's fastcommandcenter.py), before it ever fires a
        # describe -- the signal must already exist to be connectable.
        self._receiver = SettingsReceiver()
        self.settings_received = self._receiver.snapshot_received
        self.text_results_received = self._receiver.text_results_received
        self.text_provider_activation_requested = (
            self._receiver.text_provider_activation_requested
        )

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

    @property
    def manifests(self) -> list[ToolManifest]:
        """Every manifest loaded by the most recent load() call, in no
        particular order. Lets a caller build one Command per TOOL (not just
        per action) -- e.g. FastCommandCenter's "<name>: settings" command --
        by reusing this typed model instead of re-deriving tool id/name by
        parsing ToolAction.title."""
        return list(self._manifests.values())

    def fire(self, tool_id: str, action_id: str, yield_chords: list[str] | None = None) -> None:
        """Send ``action_id`` to the tool. ``yield_chords`` (neutral format,
        e.g. ["alt+q"]) is the set of chords the host currently has registered
        globally -- passed through to the tool so it can stop swallowing them
        while active (see CONTRACT.md's "yield while active" section)."""
        manifest = self._manifests.get(tool_id)
        if manifest is None:
            return
        self._send_or_launch(
            manifest, lambda hwnd: send_action(hwnd, action_id, yield_chords=yield_chords)
        )

    def describe_settings(self, tool_id: str) -> None:
        """Ask a tool to report its current settings -- find-or-launch it
        (same as fire()), then send a `describe` message (CONTRACT.md's
        "Settings protocol (v2)"). The reply arrives asynchronously as a
        `settings_received` signal; there is nothing to wait on here, this
        is only the send side of a fire-and-forget round trip. A tool that
        never responds (no v2 support, or just slow) simply never emits --
        callers time that out themselves rather than this method blocking."""
        manifest = self._manifests.get(tool_id)
        if manifest is None:
            return
        self._send_or_launch(manifest, lambda hwnd: send_settings(hwnd, "describe", {}))

    def set_setting(self, tool_id: str, setting_id: str, value: Any) -> None:
        """Ask a tool to persist a new value for one of its own settings
        (`setting_id` must be one it advertised in its last snapshot). The
        tool applies it, reloads whatever depends on it, and reports back a
        fresh `settings_received` snapshot -- there is no separate ack."""
        manifest = self._manifests.get(tool_id)
        if manifest is None:
            return
        body = {"id": setting_id, "value": value}
        self._send_or_launch(manifest, lambda hwnd: send_settings(hwnd, "set", body))

    def query_text(
        self,
        tool_id: str,
        provider_id: str,
        session_id: str,
        request_id: str,
        query: str,
    ) -> None:
        """Request live text results from a provider declared by the tool."""
        manifest = self._manifests.get(tool_id)
        if manifest is None or provider_id not in {p.id for p in manifest.text_providers}:
            return
        body = {
            "provider_id": provider_id,
            "session_id": session_id,
            "request_id": request_id,
            "query": query,
        }
        self._send_or_launch(
            manifest,
            lambda hwnd: send_json(hwnd, TEXT_PROVIDER_PROTOCOL_VERSION, "query", body),
        )

    def _send_or_launch(self, manifest: ToolManifest, send: Callable[[int], object]) -> None:
        """Find-or-launch ``manifest``'s tool, then call ``send(hwnd)`` once
        its IPC window exists. Shared by fire()/describe_settings()/
        set_setting() -- only what gets sent differs."""
        hwnd = find_window(manifest.ipc_title)
        if hwnd is not None:
            send(hwnd)
            return
        self._launch(manifest)
        self._poll_for_window(manifest, send, time.monotonic() + _LAUNCH_TIMEOUT_S)

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
        self, manifest: ToolManifest, send: Callable[[int], object], deadline: float
    ) -> None:
        hwnd = find_window(manifest.ipc_title)
        if hwnd is not None:
            send(hwnd)
            return
        if time.monotonic() >= deadline:
            return  # tool never opened its IPC window in time; drop the message
        QTimer.singleShot(
            _LAUNCH_POLL_INTERVAL_MS,
            lambda: self._poll_for_window(manifest, send, deadline),
        )

    def shutdown(self) -> None:
        """Terminate every tool instance this bridge itself launched, and
        stop the settings-reply receiver window."""
        for process in self._processes.values():
            if process.state() != QProcess.ProcessState.NotRunning:
                process.terminate()
                if not process.waitForFinished(2000):
                    process.kill()
        self._processes.clear()
        self._receiver.stop()
