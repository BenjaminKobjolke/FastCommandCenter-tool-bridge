; FastToolPalette.ahk — AutoHotkey v1 client shim for the FastCommandCenter
; tool bridge. See CONTRACT.md (repo root) for the wire protocol this
; implements. Vendor a copy of this file into the tool's lib\ folder — this
; repo is the source of truth, bump the copy when CONTRACT.md changes.
;
; Usage, near the top of the host script's auto-execute section, BEFORE it
; registers its own global hotkey(s):
;
;   #Include lib\FastToolPalette.ahk
;   FastToolPalette_Init("fastkeyboardmouse", {toggle: "ToggleController"})
;   if (!FastToolPalette_IsActive())
;       RegisterToggleHotkey()   ; only self-register when NOT palette-managed
;
; The second argument to Init maps each action id (as declared in the tool's
; fasttool.json) to an AHK label name. When FastCommandCenter sends that
; action id over WM_COPYDATA, this include does `Gosub, <label>`. An unknown
; action id is silently ignored, per CONTRACT.md.
;
; In standalone mode (no --palette on the command line) Init is a no-op: no
; window is created, no message hook installed, FastToolPalette_IsActive()
; returns false, and the host script behaves exactly as it always has.
;
; Yielding hotkeys while active: each WM_COPYDATA send may carry the host's
; currently-registered chords alongside the action id (see CONTRACT.md's
; "Yielding hotkeys while a tool is active"). A tool whose own active-mode
; hotkeys use AutoHotkey's `*` wildcard (matches a key regardless of held
; modifiers) can end up swallowing a host chord that shares that key, so the
; host's global hotkey never fires. Call
; FastToolPalette_ApplyYieldChords()/FastToolPalette_RemoveYieldChords() from
; the label(s) that turn the tool's own hotkeys on/off, so the host's chords
; keep working while the tool is active:
;
;   ToggleController:
;       ToolActive := !ToolActive
;       if (ToolActive) {
;           RegisterControllerHotkeys()
;           FastToolPalette_ApplyYieldChords()
;       } else {
;           UnregisterControllerHotkeys()
;           FastToolPalette_RemoveYieldChords()
;       }
;   return
;
; Settings protocol (v2): a tool exposes its own settings (internal
; shortcuts, tunables, ...) so the host can edit them WITHOUT ever touching
; the tool's own config file -- the tool owns read/write/reload, the host
; only ever sees typed values over IPC. See the "Settings protocol (v2)"
; section below and CONTRACT.md for the full wire format. Usage, after Init:
;
;   FastToolPalette_AddSetting("ToggleKey", "Toggle mouse mode", "shortcut", Func("GetToggleKey"), Func("SetToggleKey"))
;   FastToolPalette_AddSetting("BaseSpeed", "Cursor speed", "int", Func("GetBaseSpeed"), Func("SetBaseSpeed"), {min: 1, max: 100, step: 1})

FastToolPalette_Mode := false
FastToolPalette_Id := ""
FastToolPalette_Actions := {}
FastToolPalette_YieldChords := []

FastToolPalette_Init(id, actionLabels) {
    global FastToolPalette_Mode, FastToolPalette_Id, FastToolPalette_Actions

    FastToolPalette_Mode := false
    for index, arg in A_Args
        if (arg = "--palette")
            FastToolPalette_Mode := true

    if (!FastToolPalette_Mode)
        return

    FastToolPalette_Id := id
    FastToolPalette_Actions := actionLabels

    ; A hidden, ordinary top-level window (not +HWND_MESSAGE — those are
    ; excluded from FindWindow lookups) so the host can discover it by title.
    Gui, FastToolIPC:New, +HwndFastToolPalette_Hwnd -Caption, FastToolIPC::%id%
    Gui, FastToolIPC:Show, Hide

    OnMessage(0x4A, "FastToolPalette_OnCopyData") ; WM_COPYDATA
}

FastToolPalette_IsActive() {
    global FastToolPalette_Mode
    return FastToolPalette_Mode
}

FastToolPalette_OnCopyData(wParam, lParam) {
    global FastToolPalette_Actions, FastToolPalette_YieldChords

    ; COPYDATASTRUCT { ULONG_PTR dwData; DWORD cbData; PVOID lpData; } —
    ; dwData sits at offset 0, lpData at offset 2*A_PtrSize on both 32- and
    ; 64-bit (the DWORD cbData field is padded out to pointer size before
    ; it). This is the canonical AutoHotkey WM_COPYDATA receiving pattern.
    dwData := NumGet(lParam + 0, "UPtr")
    StringAddress := NumGet(lParam + 2 * A_PtrSize, "UPtr")
    cbData := NumGet(lParam + A_PtrSize, "UInt")

    FastToolPalette_DebugLog("OnCopyData dwData=" . dwData . " cbData=" . cbData)

    ; dwData=2 is a settings-protocol (v2) message -- a completely different
    ; envelope (kind + JSON body, see below) from an action-fire message.
    ; Older hosts never send this, so a tool without settings support simply
    ; never sees dwData=2 and this branch never runs.
    if (dwData = 2) {
        FastToolPalette_HandleSettingsMessage(StringAddress, cbData)
        return true
    }

    actionId := StrGet(StringAddress, "UTF-8")

    ; A second NUL-terminated UTF-8 string may follow: the host's currently
    ; owned chords, space-separated (CONTRACT.md's "Yielding hotkeys while a
    ; tool is active"). Absent on an older host, so this defaults to none.
    actionIdBytes := StrPut(actionId, "UTF-8")
    if (cbData > actionIdBytes) {
        chordsStr := StrGet(StringAddress + actionIdBytes, "UTF-8")
        FastToolPalette_YieldChords := StrSplit(chordsStr, " ")
    } else {
        FastToolPalette_YieldChords := []
    }

    if (FastToolPalette_Actions.HasKey(actionId)) {
        label := FastToolPalette_Actions[actionId]
        Gosub, %label%
    }
    return true
}

; ==================== Yielding hotkeys while active ====================
;
; The host's global hotkeys use Win32 RegisterHotKey, which sits AFTER a
; low-level keyboard hook in Windows' input chain. A tool whose own
; active-mode hotkeys use AutoHotkey's `*` wildcard (matches a key regardless
; of held modifiers) installs exactly such a hook, so it can swallow a chord
; the host owns before RegisterHotKey ever sees it. Registering the host's
; chord here as `~<chord>` is a transparent, non-consuming hotkey that AHK
; matches ahead of a looser wildcard binding on the same key, letting the key
; fall through to the host.

FastToolPalette_YieldRegistered := []

FastToolPalette_ApplyYieldChords() {
    global FastToolPalette_YieldChords, FastToolPalette_YieldRegistered

    FastToolPalette_RemoveYieldChords()
    for index, chord in FastToolPalette_YieldChords {
        if (chord = "")
            continue
        hk := FastToolPalette_ChordToAhk(chord)
        Hotkey, %hk%, FastToolPalette_YieldNoOp, On
        FastToolPalette_YieldRegistered.Push(hk)
    }
}

FastToolPalette_RemoveYieldChords() {
    global FastToolPalette_YieldRegistered

    for index, hk in FastToolPalette_YieldRegistered
        Hotkey, %hk%, Off
    FastToolPalette_YieldRegistered := []
}

; "ctrl+alt+q" (CONTRACT.md's neutral chord format) -> "~^!q" (AHK, pass-through).
; The "~" makes this non-consuming; a plain settable/registerable hotkey
; string (no "~") is FastToolPalette_NeutralToNative, below, which this
; reuses so the modifier-symbol mapping lives in exactly one place.
FastToolPalette_ChordToAhk(chord) {
    return "~" . FastToolPalette_NeutralToNative(chord)
}

FastToolPalette_YieldNoOp() {
    return
}

; ==================== Settings protocol (v2) ====================
;
; See CONTRACT.md's "Settings protocol (v2)". The host asks "what are your
; settings?" (describe) and "change this one" (set); this tool answers with
; its current values (snapshot) both times -- there's no separate ack, a set
; is acknowledged by the fresh snapshot that follows it. Everything here is
; generic wire-format plumbing; a host script wires its OWN settings via
; FastToolPalette_AddSetting (see the usage note at the top of this file) --
; this include never knows what "ToggleKey" or "BaseSpeed" mean.

FastToolPalette_SettingIds := []
FastToolPalette_SettingDefs := {}

; type is one of "shortcut"/"int"/"bool"/"enum"/"color" (CONTRACT.md's
; "Setting types"). getter() takes no args, returns the CURRENT value
; already in CONTRACT.md's neutral format -- a "shortcut" getter returns a
; neutral chord string like "alt+q", translated from AHK's own hotkey syntax
; via FastToolPalette_NativeToNeutral (below). setter(value) receives that
; same neutral format and is responsible for persisting it (IniWrite or
; equivalent) AND reloading whatever depends on it -- this include owns
; neither, only the wire format. extra is an object with any of
; min/max/step (type "int") or choices (type "enum"), or omitted.
FastToolPalette_AddSetting(id, label, type, getter, setter, extra := "") {
    global FastToolPalette_SettingIds, FastToolPalette_SettingDefs
    FastToolPalette_SettingIds.Push(id)
    FastToolPalette_SettingDefs[id] := {label: label, type: type, getter: getter, setter: setter, extra: extra}
}

; Routes a decoded dwData=2 message: "<kind>\0<json>\0" starting at `address`,
; `cbData` total bytes across both parts (see CONTRACT.md's envelope).
FastToolPalette_HandleSettingsMessage(address, cbData) {
    kind := StrGet(address, "UTF-8")
    kindBytes := StrPut(kind, "UTF-8") - 1  ; StrPut's count includes the NUL; back it out
    FastToolPalette_DebugLog("HandleSettingsMessage kind=" . kind . " kindBytes=" . kindBytes . " cbData=" . cbData)
    if (cbData <= kindBytes + 1) {
        FastToolPalette_DebugLog("HandleSettingsMessage: no body, returning")
        return  ; no body present -- malformed, ignore per CONTRACT.md
    }

    bodyJson := StrGet(address + kindBytes + 1, "UTF-8")

    ; A tool-side getter/setter bug (a bad Bind(), a missing global
    ; declaration, ...) would otherwise fail silently -- AHK's default
    ; unhandled-exception dialog is easy to miss on a message-handler call
    ; stack the user never sees. Logging it here turned out to matter in
    ; practice: it's how the two real bugs in this file (an empty-string
    ; "NULL" passed to FindWindow, and SendMessage's WinTitle resolution
    ; silently failing against a hidden window) actually got found.
    try {
        if (kind = "describe")
            FastToolPalette_SendSnapshot()
        else if (kind = "set")
            FastToolPalette_HandleSet(bodyJson)
        ; an unrecognized kind is silently ignored, same rule as an unknown
        ; action id -- keeps this forward-compatible with a newer host.
    } catch e {
        FastToolPalette_DebugLog("EXCEPTION in HandleSettingsMessage: " . e.Message . " (what=" . e.what . " line=" . e.line . ")")
    }
}

FastToolPalette_HandleSet(bodyJson) {
    global FastToolPalette_SettingDefs

    id := FastToolPalette_JsonExtractString(bodyJson, "id")
    if (id = "" || !FastToolPalette_SettingDefs.HasKey(id))
        return  ; unknown setting id -- silently ignored, per CONTRACT.md

    def := FastToolPalette_SettingDefs[id]
    value := FastToolPalette_JsonExtractValue(bodyJson, "value", def.type)
    if (def.type = "shortcut")
        value := FastToolPalette_NeutralToNative(value)

    def.setter.Call(value)

    ; No separate ack -- the fresh snapshot below both confirms the change
    ; took effect and gives the host the tool's authoritative post-apply
    ; state (a setter may clamp/normalize what it was asked to store).
    FastToolPalette_SendSnapshot()
}

FastToolPalette_SendSnapshot() {
    global FastToolPalette_Id, FastToolPalette_SettingIds, FastToolPalette_SettingDefs

    FastToolPalette_DebugLog("SendSnapshot: id=" . FastToolPalette_Id . " settingCount=" . FastToolPalette_SettingIds.Length())

    settingParts := []
    for index, id in FastToolPalette_SettingIds {
        def := FastToolPalette_SettingDefs[id]
        value := def.getter.Call()
        settingParts.Push(FastToolPalette_EncodeSetting(id, def, value))
    }

    json := "{""tool_id"":""" . FastToolPalette_JsonEscape(FastToolPalette_Id) . ""","
    json .= """settings"":[" . FastToolPalette_JoinComma(settingParts) . "]}"

    FastToolPalette_DebugLog("SendSnapshot: json length=" . StrLen(json))

    FastToolPalette_SendToHost("snapshot", json)
}

FastToolPalette_EncodeSetting(id, def, value) {
    json := "{""id"":""" . FastToolPalette_JsonEscape(id) . ""","
    json .= """label"":""" . FastToolPalette_JsonEscape(def.label) . ""","
    json .= """type"":""" . def.type . ""","

    if (def.type = "int")
        json .= """value"":" . value
    else if (def.type = "bool")
        json .= """value"":" . (value ? "true" : "false")
    else if (def.type = "shortcut")
        json .= """value"":""" . FastToolPalette_JsonEscape(FastToolPalette_NativeToNeutral(value)) . """"
    else  ; enum / color -- plain JSON strings
        json .= """value"":""" . FastToolPalette_JsonEscape(value) . """"

    if (IsObject(def.extra)) {
        if (def.extra.HasKey("min"))
            json .= ",""min"":" . def.extra.min
        if (def.extra.HasKey("max"))
            json .= ",""max"":" . def.extra.max
        if (def.extra.HasKey("step"))
            json .= ",""step"":" . def.extra.step
        if (def.extra.HasKey("choices")) {
            choiceParts := []
            for i, c in def.extra.choices
                choiceParts.Push("""" . FastToolPalette_JsonEscape(c) . """")
            json .= ",""choices"":[" . FastToolPalette_JoinComma(choiceParts) . "]"
        }
    }

    json .= "}"
    return json
}

; Sends "<kind>\0<json>\0" (CONTRACT.md's settings envelope, dwData=2) to the
; host's FastToolIPC::host window. Fire-and-forget, same as the host's own
; sends to a tool -- if the host isn't running (no reply window found), this
; silently drops rather than erroring; there is nothing to retry onto.
FastToolPalette_SendToHost(kind, json) {
    ; "Ptr", 0 for lpClassName -- NOT "Str", "" (an actual empty string,
    ; which matches a window whose CLASS NAME is empty -- none exist, so
    ; that silently always returned 0). NULL is what tells FindWindow to
    ; match any class, same as passing NULL from C.
    hostHwnd := DllCall("FindWindow", "Ptr", 0, "Str", "FastToolIPC::host", "Ptr")
    FastToolPalette_DebugLog("SendToHost: kind=" . kind . " hostHwnd=" . hostHwnd)
    if (!hostHwnd)
        return

    kindBytes := StrPut(kind, "UTF-8") - 1
    jsonBytes := StrPut(json, "UTF-8") - 1
    totalBytes := kindBytes + 1 + jsonBytes + 1  ; both parts NUL-terminated

    VarSetCapacity(buf, totalBytes, 0)
    StrPut(kind, &buf, "UTF-8")
    StrPut(json, &buf + kindBytes + 1, "UTF-8")

    VarSetCapacity(cds, 3 * A_PtrSize, 0)
    NumPut(2, cds, 0, "UPtr")                   ; dwData: settings protocol version
    NumPut(totalBytes, cds, A_PtrSize, "UInt")  ; cbData
    NumPut(&buf, cds, 2 * A_PtrSize, "UPtr")    ; lpData

    ; DllCall directly against the raw hwnd, NOT the `SendMessage` command
    ; with a `ahk_id` WinTitle target: that command re-resolves its target
    ; through AHK's own window-matching engine, which (unlike the raw
    ; FindWindow call above) respects DetectHiddenWindows -- off by default,
    ; so it silently fails to target a hidden window like the host's reply
    ; window. This mirrors exactly how the host's own send_action/
    ; send_settings (fasttool_host/copydata.py) already send: a raw
    ; SendMessageW DllCall against the hwnd, no window-title matching at all.
    result := DllCall("SendMessageW", "Ptr", hostHwnd, "UInt", 0x4A, "Ptr", 0, "Ptr", &cds, "Ptr")
    FastToolPalette_DebugLog("SendToHost: SendMessageW result=" . result . " totalBytes=" . totalBytes)
}

; ==================== Debug logging ====================
;
; One line per stage of the describe/set -> snapshot round trip, appended to
; palette_debug.log next to this tool's exe. Deliberately always-on rather
; than gated behind a flag: this protocol crosses two processes and a Win32
; IPC boundary, exactly where a MsgBox can't help (a silently-dropped
; SendMessage, a window that can't be found) -- and it's how the two real
; bugs in this file were actually found. See docs/EXTERNAL_TOOLS.md's
; "Debugging the settings protocol" (FastCommandCenter repo) for how to read
; it and tools/diag_settings.py, its Python-side counterpart.
;
; ponytail: append-only, never rotated or size-capped -- delete the file
; yourself if it grows large. Fine for a personal dev tool; add rotation
; only if this ever ships somewhere that matters.
FastToolPalette_DebugLog(message) {
    FileAppend, % A_Now . " " . message . "`n", %A_ScriptDir%\palette_debug.log
}

; ---- Minimal JSON, scoped to exactly the shapes this protocol needs -----
;
; Not a general JSON parser/encoder: every body here is a small, flat,
; known-shape object (CONTRACT.md's message kinds), so hand-rolled
; extraction/escaping is simpler and has no external dependency to vendor.

FastToolPalette_JsonExtractString(json, key) {
    needle := """" . key . """\s*:\s*""((?:[^""\\]|\\.)*)"""
    if !RegExMatch(json, needle, m)
        return ""
    return FastToolPalette_JsonUnescape(m1)
}

FastToolPalette_JsonExtractValue(json, key, type) {
    if (type = "int") {
        if RegExMatch(json, """" . key . """\s*:\s*(-?\d+)", m)
            return m1 + 0
        return 0
    } else if (type = "bool") {
        if RegExMatch(json, """" . key . """\s*:\s*(true|false)", m)
            return (m1 = "true")
        return false
    } else {
        ; shortcut / enum / color -- all plain JSON strings
        return FastToolPalette_JsonExtractString(json, key)
    }
}

FastToolPalette_JsonEscape(s) {
    s := StrReplace(s, "\", "\\")
    s := StrReplace(s, """", "\""")
    return s
}

FastToolPalette_JsonUnescape(s) {
    s := StrReplace(s, "\""", """")
    s := StrReplace(s, "\\", "\")
    return s
}

FastToolPalette_JoinComma(arr) {
    out := ""
    for i, v in arr
        out .= (i = 1 ? "" : ",") . v
    return out
}

; ---- Neutral <-> AHK native chord translation ----------------------------
;
; "Neutral" is CONTRACT.md's chord format (lowercase, "+"-joined, "win" for
; the Windows/Meta key -- the same format used for yield-chords, above).
; "Native" is plain AHK hotkey syntax with no "~" prefix (unlike
; FastToolPalette_ChordToAhk, which is specifically the yield pass-through
; variant) -- what a shortcut setting's getter/setter actually stores. A
; bare key with no modifiers (e.g. neutral "q") round-trips as itself; a
; tool that additionally registers such a key with AHK's "*" wildcard prefix
; (matches regardless of held modifiers) does that at registration time --
; the "*" is never part of the persisted/reported value.

FastToolPalette_NeutralToNative(chord) {
    static modMap := {ctrl: "^", alt: "!", shift: "+", win: "#"}

    prefix := ""
    key := ""
    for index, part in StrSplit(chord, "+") {
        partLower := part
        StringLower, partLower, partLower
        if (modMap.HasKey(partLower))
            prefix .= modMap[partLower]
        else
            key := part
    }
    return prefix . key
}

FastToolPalette_NativeToNeutral(hk) {
    static prefixMap := {"^": "ctrl", "!": "alt", "+": "shift", "#": "win"}

    mods := []
    pos := 1
    Loop, Parse, hk
    {
        ch := A_LoopField
        if (prefixMap.HasKey(ch)) {
            mods.Push(prefixMap[ch])
            pos += 1
        } else {
            break
        }
    }
    key := SubStr(hk, pos)
    parts := mods.Clone()
    parts.Push(key)
    return FastToolPalette_JoinPlus(parts)
}

FastToolPalette_JoinPlus(arr) {
    out := ""
    for i, v in arr
        out .= (i = 1 ? "" : "+") . v
    return out
}
