# fasttool-palette

Python client half of the [FastTool bridge](../../../CONTRACT.md), for
Python-based FastTools apps (FastTextSuggester, FastHotkeyExecuter).

## Usage

Near the top of the host app's startup, before it registers its own global
hotkeys:

```python
from fasttool_palette import FastToolPalette, palette_mode

if palette_mode():
    palette = FastToolPalette("fasttextsuggester")
else:
    palette = None
    register_own_hotkeys()  # only when NOT palette-managed
```

Drain received actions from the app's own event loop — window messages are
delivered on a background thread, so `poll()` is the thread-safe hand-off
point (never touch Tkinter/etc. from inside the bridge's own thread):

```python
def on_tick():
    if palette is not None:
        for action_id in palette.poll():
            if action_id == "capture":
                handle_capture_hotkey()
            elif action_id == "suggestion":
                handle_suggestion_hotkey()
    root.after(50, on_tick)
```

`palette_mode()` just checks for `--palette` on the command line — wire it
into the app's existing argument parsing however it already works.
