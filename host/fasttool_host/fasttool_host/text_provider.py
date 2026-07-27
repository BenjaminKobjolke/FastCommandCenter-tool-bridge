"""Typed models for protocol-v3 text-provider replies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class TextProviderError(ValueError):
    """A text-provider message is malformed."""


@dataclass(frozen=True)
class ToolTextProvider:
    id: str
    label: str
    min_chars: int = 0


@dataclass(frozen=True)
class ToolTextResult:
    title: str
    text: str
    subtitle: str = ""

    @staticmethod
    def from_dict(data: dict[str, Any]) -> ToolTextResult:
        try:
            return ToolTextResult(
                title=str(data["title"]),
                text=str(data["text"]),
                subtitle=str(data.get("subtitle", "")),
            )
        except KeyError as exc:
            raise TextProviderError(f"result missing required field {exc}") from exc


@dataclass(frozen=True)
class ToolTextResults:
    tool_id: str
    provider_id: str
    session_id: str
    request_id: str
    results: tuple[ToolTextResult, ...]

    @staticmethod
    def from_dict(data: dict[str, Any]) -> ToolTextResults:
        try:
            raw_results = data["results"]
            if not isinstance(raw_results, list):
                raise TypeError
            return ToolTextResults(
                tool_id=str(data["tool_id"]),
                provider_id=str(data["provider_id"]),
                session_id=str(data["session_id"]),
                request_id=str(data["request_id"]),
                results=tuple(ToolTextResult.from_dict(item) for item in raw_results),
            )
        except KeyError as exc:
            raise TextProviderError(f"results missing required field {exc}") from exc
        except (TypeError, AttributeError) as exc:
            raise TextProviderError("results must be a list of objects") from exc


@dataclass(frozen=True)
class ToolTextProviderActivation:
    tool_id: str
    provider_id: str

    @staticmethod
    def from_dict(data: dict[str, Any]) -> ToolTextProviderActivation:
        try:
            return ToolTextProviderActivation(
                tool_id=str(data["tool_id"]), provider_id=str(data["provider_id"])
            )
        except KeyError as exc:
            raise TextProviderError(f"activation missing required field {exc}") from exc
