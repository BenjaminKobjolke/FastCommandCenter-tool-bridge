# FastTool bridge contract

Wire protocol between **FastCommandCenter** (the host, single OS-hotkey
authority) and the FastTools apps it can launch and drive ("tools"). This
file is the source of truth — client shims (AHK, Python) and the host
implement exactly this.

## Why

Windows `RegisterHotKey` is exclusive per chord — two processes cannot both
own the same hotkey. FastCommandCenter is meant to be the single place users
configure every hotkey across every FastTools app. So when a tool is launched
by FastCommandCenter it must **not** register its own global hotkey; instead
FastCommandCenter owns the hotkey and tells the running tool which action to
perform. Run the tool directly (not through FastCommandCenter) and it behaves
exactly as before — self-registered hotkey, no bridge involved.

## Modes

A tool has exactly two modes, selected by a `--palette` command-line flag:

- **Standalone** (no flag): tool behaves exactly as it always has — reads its
  own config, registers its own global hotkey(s). No bridge code runs.
- **Palette-managed** (`--palette` flag present): tool skips its own global
  hotkey registration and instead opens an IPC listener (below), waiting for
  the host to send it actions.

## Discovery

Each palette-managed tool creates a **hidden, ordinary top-level window**
(not a message-only `HWND_MESSAGE` window — those are excluded from
`FindWindow` lookups) whose title is:

```
FastToolIPC::<tool-id>
```

`<tool-id>` is the tool's id from its `fasttool.json` (below), e.g.
`FastToolIPC::fastkeyboardmouse`.

The host resolves a tool by calling `FindWindow(NULL, "FastToolIPC::<tool-id>")`:

- **Found** → tool is already running in palette mode; send the action directly.
- **Not found** → launch the tool with `--palette`, wait for the window to
  appear (poll `FindWindow` briefly), then send the action.

## Message

Actions are sent as a Win32 `WM_COPYDATA` message:

```
SendMessage(hwnd, WM_COPYDATA /* 0x004A */, 0, &cds)
```

`cds` is a `COPYDATASTRUCT`:

| Field | Value |
|---|---|
| `dwData` | protocol version, an integer tag. Current version: `1`. |
| `cbData` | byte length of `lpData`, **including** a trailing NUL byte. |
| `lpData` | the action id, UTF-8 encoded, NUL-terminated. |

Example: sending the `toggle` action encodes `lpData` as `b"toggle\x00"` (7
bytes), `cbData = 7`, `dwData = 1`.

The receiver looks up the decoded action id in its registered action map and
invokes it. **An unknown action id is silently ignored** — this keeps the
contract forward-compatible (a newer host can be paired with an older tool
without crashing it).

This is fire-and-forget: the host does not wait for or receive a reply. If a
tool ever needs to report status back, that is a v2 concern — out of scope
here.

## Manifest — `fasttool.json`

Every palette-managed tool ships a `fasttool.json` file next to its
executable, describing itself to the host:

```json
{
  "id": "fastkeyboardmouse",
  "name": "Fast Keyboard Mouse",
  "ipc_title": "FastToolIPC::fastkeyboardmouse",
  "launch": {
    "exe": "FastKeyboardMouse.exe",
    "args": ["--palette"]
  },
  "actions": [
    { "id": "toggle", "label": "Toggle mouse mode" }
  ]
}
```

- `id` — stable identifier, used to build the host's command id
  (`tool.<id>.<action-id>`) and must match the id passed to the client shim's
  init call.
- `ipc_title` — must equal `FastToolIPC::<id>`. Kept explicit (not derived) so
  the manifest is fully self-describing.
- `launch.exe` / `launch.args` — resolved relative to the manifest's folder.
  `args` must include `--palette` (the manifest is the single place this is
  declared; the host does not hardcode it).
- `actions` — static list of `{id, label}`. The action set for a tool is
  fixed and small (checked against all four known FastTools apps); there is
  no dynamic/runtime action discovery in this version of the contract.

The host is configured with a list of folders to scan for `fasttool.json`
files — adding a tool to FastCommandCenter means dropping a manifest next to
its exe and adding that folder to the host's `tool_dirs` config (in
FastCommandCenter, done through the palette's own `Tools: manage folders`
command, never by hand-editing config). Tools ship no knowledge of the host.

A missing or malformed `fasttool.json` (invalid JSON, a missing required
field, an `ipc_title` that doesn't match `FastToolIPC::<id>`) is **skipped,
not raised** — `fasttool_host.manifest.discover_manifests` swallows
`ManifestError` per folder. One bad or half-written tool folder must not take
down the whole host on startup.

## Versioning

`dwData` carries a protocol version so a future breaking wire change can be
detected. This version of the contract is **1**. Receivers should ignore
messages with an unrecognized version rather than crash (forward-compat is
more important than strict validation for a fire-and-forget hotkey action).
