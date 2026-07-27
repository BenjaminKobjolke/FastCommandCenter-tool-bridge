# FastCommandCenter-tool-bridge

Lets [FastCommandCenter](../FastCommandCenter) become the single global-hotkey
authority for the other FastTools apps, instead of each app registering its
own OS hotkey. See [`CONTRACT.md`](CONTRACT.md) for the wire protocol.

## Layout

- `CONTRACT.md` — the wire spec. Source of truth for every piece below.
- `client/ahk/FastToolPalette.ahk` — AutoHotkey v1 include for AHK-based tools
  (FastKeyboardMouse, FastWindowLayout). Vendor a copy into the tool's repo.
- `client/python/fasttool_palette/` — Python client package for Python-based
  tools (FastTextSuggester, FastHotkeyExecuter). Add as a path/git dependency.
- `host/fasttool_host/` — the host-side package FastCommandCenter depends on:
  loads `fasttool.json` manifests, launches/tracks tools, sends actions.
- `examples/fasttool.json` — a reference manifest.

Protocol v3 text providers let tools answer live palette queries and return
resolved insertion text without exposing their data files to the host.

## Who depends on what

| Consumer | Takes | How |
|---|---|---|
| FastCommandCenter | `host/fasttool_host` | Python path/git dependency (`pyproject.toml`, like `command-palette`) |
| FastTextSuggester, FastHotkeyExecuter | `client/python/fasttool_palette` | Python path/git dependency |
| FastKeyboardMouse, FastWindowLayout | `client/ahk/FastToolPalette.ahk` | vendored copy in the tool's `lib\` — bump manually on contract changes |

## Tests

Each Python package has its own unit tests (`uv run pytest` inside
`host/fasttool_host` or `client/python/fasttool_palette`). The AHK include has
no automated tests — verify via a tool's own end-to-end check.
