# fasttool-host

Host-side half of the [FastTool bridge](../../CONTRACT.md). FastCommandCenter
depends on this package to discover `fasttool.json` manifests, turn them into
bindable actions, and fire those actions at running (or not-yet-running)
tools over `WM_COPYDATA`.

## Usage

```python
from pathlib import Path
from fasttool_host import ToolBridge

bridge = ToolBridge()
actions = bridge.load([Path("D:/GIT/.../FastKeyboardMouse")])
# actions: list[ToolAction] — one per tool action, command_id "tool.<id>.<action>"

bridge.fire("fastkeyboardmouse", "toggle")  # finds or launches the tool, sends the action

bridge.shutdown()  # terminates any tools this bridge itself launched
```

## Reloading after the configured folders change

`ToolBridge.load()` can be called again on the same instance — it replaces
the manifest set but leaves any already-tracked launched-process state
untouched. Reuse the existing bridge rather than constructing a new
`ToolBridge()`, or you lose track of instances it already launched:

```python
actions = bridge.load(new_tool_dirs)  # same bridge, refreshed manifest set
```

(FastCommandCenter's `core/tool_commands.py` wraps exactly this pattern —
`build_tool_commands(settings_store, bridge)` — for its `Tools: manage
folders` palette command.)

A folder whose `fasttool.json` is missing or malformed is skipped, not
raised — see CONTRACT.md.

See `tests/` for the manifest-parsing contract (win32-free, runs anywhere).
