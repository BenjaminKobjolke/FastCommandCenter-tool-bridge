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

### Yielding hotkeys while a tool is active

`lpData` MAY carry a **second** NUL-terminated UTF-8 string after the action
id: a space-separated list of the chords the host currently has registered
globally, in neutral format (lowercase, `+`-joined, `win` for the Windows/Meta
key — e.g. `alt+q`, `ctrl+alt+space`). Example: `lpData` for `toggle` with one
owned chord is `b"toggle\x00alt+q\x00"`, `cbData = 13`.

This exists because `RegisterHotKey` (what the host uses) sits *after* a
low-level keyboard hook in Windows' input chain — a tool that installs its own
hook while active (e.g. AutoHotkey's `*`-wildcard hotkeys) can swallow a chord
before the host's `RegisterHotKey` ever sees it, even though the host, not the
tool, owns that chord. A tool that wants the host's chords to keep working
while it's active should, on activation, register each received chord as a
transparent pass-through in its own hook (AutoHotkey: `~<chord>::return` —
`~` doesn't consume the key) so it out-ranks any looser wildcard binding on
the same key, and remove them on deactivation.

A receiver that only parses up to the first NUL sees just the action id and
is unaffected — this field is purely additive, no version bump. An empty or
absent second string means the host currently owns no chords (or is an older
host); the tool should treat that the same as receiving no chords to yield.

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

## Settings protocol (v2)

Lets the host read and change a tool's **own** settings — its internal
keyboard shortcuts, tunables, colors, flags — without ever touching the
tool's config file itself. The tool remains the sole owner of how its
settings are persisted and applied; the host only ever sees typed values over
IPC. This is deliberately more than "read the tool's ini file from the host
side": the host cannot know how a given tool stores its config (ini, JSON,
registry, ...), so it never tries to.

### Why this needed a reply channel

Action-fire (v1) is one-way and stays that way. Settings needs the tool to
report *back* — its schema and current values, and later a fresh snapshot
after applying a change — which v1 explicitly deferred ("If a tool ever needs
to report status back, that is a v2 concern — out of scope here"). This is
that v2.

### The reply window: `FastToolIPC::host`

Symmetric with a tool's own `FastToolIPC::<tool-id>` window (see
"Discovery" above): the host creates one hidden, ordinary top-level window
titled exactly `FastToolIPC::host`. A tool sends its settings snapshot to the
host by resolving this window with `FindWindow(NULL, "FastToolIPC::host")`
and sending it a `WM_COPYDATA` message, the same primitive and direction the
host already uses to reach a tool — just reversed. Still fire-and-forget in
each direction; there is no synchronous request/response, only two
independent one-way sends.

### Envelope

`dwData = 2` marks a settings message (as opposed to `dwData = 1` for an
action-fire message). `lpData` holds two NUL-terminated UTF-8 strings back to
back — a `kind` tag, then a JSON body:

```
<kind>\0<json>\0
```

`cbData` is the total byte length of both parts, including both trailing NUL
bytes.

### Message kinds

| Kind | Direction | Body |
|---|---|---|
| `describe` | host → tool | `{}` — "send me your current settings" |
| `snapshot` | tool → host | `{"tool_id": "<id>", "settings": [ {...} ]}` — full current state |
| `set` | host → tool | `{"id": "<setting-id>", "value": <typed>}` |

**`describe`**: sent to a tool the same way an action is (find-or-launch via
`ipc_title`, see "Discovery"). Body is always `{}`.

**`snapshot`**: a tool sends this in response to `describe`, and again after
applying a `set` — so it doubles as both the answer to "what are your
settings?" and the acknowledgment/refresh after a change. There is no
separate ack message. `settings` is a list of setting objects (see "Setting
types" below); `tool_id` must match the sending tool's manifest `id`, so the
host can route the snapshot back to the right tool. Still fire-and-forget: if
a `set` never produces a `snapshot` in a reasonable time, the host degrades
to "the tool didn't respond" — it does not block waiting.

**`set`**: `id` is one of the setting ids the tool advertised in its last
`snapshot`. `value` is typed per that setting's `type` (below). The tool
persists it, reloads whatever internal state depends on it (a single hotkey
re-registration, a full restart — the tool's own call, invisible to the
host), and sends a fresh `snapshot` reflecting the applied state.

An unrecognized `kind`, or a `set` for an unknown `id`, is silently ignored —
same forward-compat rule as an unknown action id.

### Setting types

Every setting in a `snapshot`'s list has at least `id`, `label`, `type`,
`value`. All values are JSON-native so the host never has to understand a
tool's own native format (e.g. AutoHotkey hotkey syntax):

| `type` | `value` | Extra fields |
|---|---|---|
| `shortcut` | neutral chord string, e.g. `"alt+q"`, or a bare key `"q"` | — |
| `int` | integer | `min`, `max`, `step` (all optional) |
| `bool` | `true` / `false` | — |
| `enum` | string | `choices`: list of strings |
| `color` | `"#rrggbb"` | — |
| `string` | string | — |
| `directory` | directory path string | — |

`shortcut` reuses the **same neutral chord format** already defined above
under "Yielding hotkeys while a tool is active" (lowercase, `+`-joined,
`win` for the Windows/Meta key). A tool's client shim is responsible for
translating neutral ↔ its own native format (e.g. AutoHotkey `!q` for
`alt+q`) in both directions — the host only ever sends and receives neutral
chords.

Example `snapshot` body:

```json
{
  "tool_id": "fastkeyboardmouse",
  "settings": [
    {"id": "ToggleKey", "label": "Toggle mouse mode", "type": "shortcut", "value": "alt+q"},
    {"id": "BaseSpeed", "label": "Cursor speed", "type": "int", "value": 20, "min": 1, "max": 100, "step": 1},
    {"id": "DarkMode", "label": "Dark mode", "type": "bool", "value": true},
    {"id": "SpeedModifier", "label": "Speed boost key", "type": "enum", "value": "Shift", "choices": ["Shift", "Ctrl", "Alt"]},
    {"id": "IndicatorColor", "label": "Cursor indicator color", "type": "color", "value": "#00ff00"}
  ]
}
```

### Graceful degradation

A tool with no settings support (an older v1-only shim, or one that simply
declares no settings) never sends a `snapshot` back. The host waits briefly,
then shows "no editable settings" — no crash, no hang, and action-fire
continues to work exactly as before (v1 is untouched by any of this). An
older tool receiving a `describe` or `set` message doesn't need to recognize
`dwData = 2` at all to degrade safely: even a receiver that ignores `dwData`
and blindly parses `lpData` as an action id would just look up `"describe"`
or `"set"` in its action map, find nothing, and silently ignore it per the
existing unknown-action-id rule.

## Text provider protocol (v3)

Tools may declare live text sources alongside fixed actions:

```json
"text_providers": [
  {"id": "suggestions", "label": "FastTextSuggester", "min_chars": 0}
]
```

`dwData = 3` uses the same `kind\0json\0` envelope as settings v2. The host
sends `query` with `provider_id`, `session_id`, `request_id`, and `query`.
The tool replies to `FastToolIPC::host` with `results`, repeating all three
ids and returning `results: [{"title", "subtitle", "text"}]`. `text` is the
resolved value the host inserts and may differ from the displayed title.

A tool may send `activate_provider` with its `tool_id` and `provider_id` to
ask the host to open that provider, for example after asynchronous OCR.
Unknown providers, malformed bodies, and stale correlation ids are ignored.
The protocol is optional; v1/v2-only tools are unaffected.

## Versioning

`dwData` carries a protocol version so a future breaking wire change can be
detected. Action-fire is version **1**, settings is version **2**, and text
providers are version **3** (see
above) — both are live simultaneously, not a linear upgrade. Receivers should
ignore messages with an unrecognized `dwData` rather than crash
(forward-compat is more important than strict validation for a
fire-and-forget message).
