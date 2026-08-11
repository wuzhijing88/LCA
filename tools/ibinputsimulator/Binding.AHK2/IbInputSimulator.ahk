; IbInputSimulator
; Description: Enable AHK to send keystrokes by drivers.
; Authors: Chaoses-Ib, Pennywise007
; Version: 0.4.1
; Homepage: https://github.com/Chaoses-Ib/IbInputSimulator

#Requires AutoHotkey v2.0 64-bit

#DllLoad "*i IbInputSimulator.dll"  ;DllCall("LoadLibrary") cannot locate DLL correctly

IbSendInit(send_type := "AnyDriver", mode := 1, args*){
    workding_dir := A_WorkingDir
    SetWorkingDir(A_ScriptDir)

    static hModule := DllCall("GetModuleHandle", "Str", "IbInputSimulator.dll", "Ptr")
    if (hModule == 0){
        if (A_PtrSize == 4)
            throw Error("SendLibLoadFailed: Please use AutoHotkey x64")
        else
            throw Error("SendLibLoadFailed: " A_LastError)
    }
    
    if (send_type == "AnyDriver")
        result := DllCall("IbInputSimulator\IbSendInit", "Int", 0, "Int", 0, "Ptr", 0, "Int")
    else if (send_type == "SendInput")
        result := DllCall("IbInputSimulator\IbSendInit", "Int", 1, "Int", 0, "Ptr", 0, "Int")
    else if (send_type == "Logitech")
        result := DllCall("IbInputSimulator\IbSendInit", "Int", 2, "Int", 0, "Ptr", 0, "Int")
    else if (send_type == "Razer")
        result := DllCall("IbInputSimulator\IbSendInit", "Int", 3, "Int", 0, "Ptr", 0, "Int")
    else if (send_type == "DD"){
        if (args.Length == 1)
            result := DllCall("IbInputSimulator\IbSendInit", "Int", 4, "Int", 0, "WStr", args[1], "Int")
        else
            result := DllCall("IbInputSimulator\IbSendInit", "Int", 4, "Int", 0, "Ptr", 0, "Int")
    } else if (send_type == "MouClassInputInjection"){
        if (args.Length != 1)
            throw Error("MouClassInputInjection: Please specify the process ID of the target process")
        result := DllCall("IbInputSimulator\IbSendInit", "Int", 5, "Int", 0, "UInt64", args[1], "Int")
    } else
        throw Error("Invalid send type")

    SetWorkingDir(workding_dir)

    if (result !== 0){
        error_text := [
            "InvalidArgument",
            "LibraryNotFound",
            "LibraryLoadFailed",
            "LibraryError",
            "DeviceCreateFailed",
            "DeviceNotFound",
            "DeviceOpenFailed"
        ]
        message := ""
        try message := error_text[result]
        if (message = "")
            message := "IbSendInitFailedCode:" result
        throw Error(message)
    }

    if (mode !== 0){
        IbSendMode(mode)
    }
}

IbSendMode(mode){
    static ahk_mode := ""
    if (mode == 1){
        DllCall("IbInputSimulator\IbSendInputHook", "Int", 1)
        ahk_mode := A_SendMode
        SendMode("Input")
    } else if (mode == 0){
        SendMode(ahk_mode)
        DllCall("IbInputSimulator\IbSendInputHook", "Int", 0)
    } else {
        throw Error("Invalid send mode")
    }
}

IbSendDestroy(){
    DllCall("IbInputSimulator\IbSendDestroy")
    ;DllCall("FreeLibrary", "Ptr", hModule)
}

IbSyncKeyStates(){
    DllCall("IbInputSimulator\IbSendSyncKeyStates")
}

IbSend(keys){
    DllCall("IbInputSimulator\IbSendInputHook", "Int", 1)  ;or IbSendMode(1)
    SendInput(keys)
    DllCall("IbInputSimulator\IbSendInputHook", "Int", 0)  ;or IbSendMode(0)
}

IbClick(args*){
    IbSendMode(1)
    Click(args*)
    IbSendMode(0)
}

IbMouseMove(args*){
    relative := false
    if (args.Length >= 4) {
        modeText := StrUpper(Trim(args[4]))
        relative := (modeText = "R" || modeText = "RELATIVE")
    }

    if relative {
        result := DllCall("IbInputSimulator\IbSendMouseMove", "Int", args[1], "Int", args[2], "Int", 1, "Int")
        if !result
            throw Error("IbSendMouseMoveFailed")
        return
    }

    IbSendMode(1)
    try {
        MouseMove(args*)
    } finally {
        IbSendMode(0)
    }
}

IbMouseClick(args*){
    IbSendMode(1)
    MouseClick(args*)
    IbSendMode(0)
}

IbMouseClickDrag(args*){
    IbSendMode(1)
    MouseClickDrag(args*)
    IbSendMode(0)
}
