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

FastToolPalette_Mode := false
FastToolPalette_Actions := {}
FastToolPalette_YieldChords := []

FastToolPalette_Init(id, actionLabels) {
    global FastToolPalette_Mode, FastToolPalette_Actions

    FastToolPalette_Mode := false
    for index, arg in A_Args
        if (arg = "--palette")
            FastToolPalette_Mode := true

    if (!FastToolPalette_Mode)
        return

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
    ; lpData sits at offset 2*A_PtrSize on both 32- and 64-bit (the DWORD
    ; cbData field is padded out to pointer size before it). This is the
    ; canonical AutoHotkey WM_COPYDATA receiving pattern.
    StringAddress := NumGet(lParam + 2 * A_PtrSize, "UPtr")
    cbData := NumGet(lParam + A_PtrSize, "UInt")
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
FastToolPalette_ChordToAhk(chord) {
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
    return "~" . prefix . key
}

FastToolPalette_YieldNoOp() {
    return
}
