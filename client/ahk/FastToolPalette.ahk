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

FastToolPalette_Mode := false
FastToolPalette_Actions := {}

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
    global FastToolPalette_Actions

    ; COPYDATASTRUCT { ULONG_PTR dwData; DWORD cbData; PVOID lpData; } —
    ; lpData sits at offset 2*A_PtrSize on both 32- and 64-bit (the DWORD
    ; cbData field is padded out to pointer size before it). This is the
    ; canonical AutoHotkey WM_COPYDATA receiving pattern.
    StringAddress := NumGet(lParam + 2 * A_PtrSize, "UPtr")
    actionId := StrGet(StringAddress, "UTF-8")

    if (FastToolPalette_Actions.HasKey(actionId)) {
        label := FastToolPalette_Actions[actionId]
        Gosub, %label%
    }
    return true
}
