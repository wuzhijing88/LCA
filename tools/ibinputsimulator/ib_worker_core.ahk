#Requires AutoHotkey v2.0

global _ib_pressed_keys := Map()
global _ib_pressed_buttons := Map()

IbWorkerMain(driverName, driverArg := "") {
    try {
        ; Force mode=0 during bootstrap. Hook mode can fail in some packaged envs
        ; and is not required because IbSend() toggles hook per call.
        if driverArg != ""
            IbSendInit(driverName, 0, driverArg)
        else
            IbSendInit(driverName, 0)
    } catch as initErr {
        _ib_write_err("0", _ib_format_init_error(initErr))
        ExitApp(2)
    }

    CoordMode("Mouse", "Screen")

    FileAppend("READY`n", "*")

    stdin := FileOpen("*", "r `n", "UTF-8")
    if !IsObject(stdin) {
        _ib_write_err("0", "stdin open failed")
        ExitApp(3)
    }

    ; 使用阻塞读取避免轮询Sleep引入的10~20ms命令处理延迟
    Loop {
        rawLine := stdin.ReadLine()
        if rawLine = "" {
            if stdin.AtEOF
                break
            continue
        }

        line := Trim(rawLine, "`r`n")
        if line = ""
            continue

        _ib_handle_line(line)
    }

    try _ib_release_all_inputs()
    try IbSendDestroy()
    ExitApp(0)
}

_ib_handle_line(line) {
    parts := StrSplit(line, "`t")
    if parts.Length < 2
        return

    reqId := parts[1]
    method := parts[2]
    args := []

    if parts.Length >= 3 {
        Loop parts.Length - 2 {
            args.Push(_ib_decode_token(parts[A_Index + 2]))
        }
    }

    try {
        tokens := _ib_dispatch(method, args)
        _ib_write_ok(reqId, tokens*)
    } catch as opErr {
        _ib_write_err(reqId, opErr.Message)
    }
}

_ib_dispatch(method, args) {
    if method = "ping"
        return []

    if method = "exit" {
        _ib_release_all_inputs()
        ExitApp(0)
    }

    if method = "release_all_inputs" {
        _ib_release_all_inputs()
        return []
    }

    if method = "get_screen_size"
        return ["n:" A_ScreenWidth, "n:" A_ScreenHeight]

    if method = "get_mouse_position" {
        MouseGetPos(&mx, &my)
        return ["n:" mx, "n:" my]
    }

    if method = "move_mouse" {
        x := _ib_to_int(_ib_arg(args, 1, 0), 0)
        y := _ib_to_int(_ib_arg(args, 2, 0), 0)
        absolute := _ib_to_bool(_ib_arg(args, 3, true), true)
        _ib_move_cursor(x, y, absolute)
        return []
    }

    if method = "click_mouse" {
        x := _ib_arg(args, 1, "")
        y := _ib_arg(args, 2, "")
        button := _ib_normalize_button(_ib_arg(args, 3, "left"))
        clicks := _ib_to_int(_ib_arg(args, 4, 1), 1)
        intervalMs := _ib_to_int(_ib_to_number(_ib_arg(args, 5, 0.0), 0.0) * 1000.0, 0)
        durationMs := _ib_to_int(_ib_to_number(_ib_arg(args, 6, 0.0), 0.0) * 1000.0, 0)

        if x = "" || y = ""
            throw Error("MouseCoordinatesRequired")
        tx := _ib_to_int(x, 0)
        ty := _ib_to_int(y, 0)

        if clicks < 1
            clicks := 1

        Loop clicks {
            if durationMs > 0 {
                _ib_mouse_down(button, tx, ty)
                _ib_precise_hold_sleep_ms(durationMs)
                _ib_mouse_up(button, tx, ty)
            } else {
                _ib_mouse_click(button, tx, ty)
            }

            if A_Index < clicks && intervalMs > 0
                _ib_precise_sleep_ms(intervalMs)
        }
        return []
    }

    if method = "mouse_down" {
        x := _ib_arg(args, 1, "")
        y := _ib_arg(args, 2, "")
        button := _ib_normalize_button(_ib_arg(args, 3, "left"))
        if x = "" || y = ""
            throw Error("MouseCoordinatesRequired")
        tx := _ib_to_int(x, 0)
        ty := _ib_to_int(y, 0)
        _ib_mouse_down(button, tx, ty)
        _ib_track_mouse_button_down(button, tx, ty)
        return []
    }

    if method = "mouse_up" {
        x := _ib_arg(args, 1, "")
        y := _ib_arg(args, 2, "")
        button := _ib_normalize_button(_ib_arg(args, 3, "left"))
        if x = "" || y = ""
            throw Error("MouseCoordinatesRequired")
        _ib_mouse_up(button, _ib_to_int(x, 0), _ib_to_int(y, 0))
        _ib_track_mouse_button_up(button)
        return []
    }

    if method = "drag_mouse" {
        sx := _ib_to_int(_ib_arg(args, 1, 0), 0)
        sy := _ib_to_int(_ib_arg(args, 2, 0), 0)
        ex := _ib_to_int(_ib_arg(args, 3, 0), 0)
        ey := _ib_to_int(_ib_arg(args, 4, 0), 0)
        button := _ib_normalize_button(_ib_arg(args, 5, "left"))
        duration := _ib_to_number(_ib_arg(args, 6, 0.0), 0.0)

        _ib_set_cursor(sx, sy)
        _ib_mouse_down(button, sx, sy)

        _ib_drag_move_segment_with_py_profile(sx, sy, ex, ey, duration)

        _ib_mouse_up(button, ex, ey)
        return []
    }

    if method = "drag_path" {
        pointsText := _ib_arg(args, 1, "")
        duration := _ib_to_number(_ib_arg(args, 2, 0.0), 0.0)
        button := _ib_normalize_button(_ib_arg(args, 3, "left"))
        timestampsText := _ib_arg(args, 4, "")

        points := _ib_parse_points(pointsText)
        if points.Length < 2
            throw Error("invalid drag path")

        ts := _ib_parse_numbers(timestampsText)

        first := points[1]
        _ib_set_cursor(first[1], first[2])
        _ib_mouse_down(button, first[1], first[2])

        if ts.Length = points.Length {
            prev := _ib_to_number(ts[1], 0.0)
            prevPoint := points[1]
            Loop points.Length - 1 {
                p := points[A_Index + 1]
                cur := _ib_to_number(ts[A_Index + 1], prev)
                segDuration := cur - prev
                if segDuration < 0
                    segDuration := 0
                _ib_drag_move_segment_with_py_profile(
                    prevPoint[1],
                    prevPoint[2],
                    p[1],
                    p[2],
                    segDuration
                )
                prev := cur
                prevPoint := p
            }
        } else {
            seg := points.Length - 1
            if seg < 1
                seg := 1
            segDuration := duration / seg
            prevPoint := points[1]
            Loop points.Length - 1 {
                p := points[A_Index + 1]
                _ib_drag_move_segment_with_py_profile(
                    prevPoint[1],
                    prevPoint[2],
                    p[1],
                    p[2],
                    segDuration
                )
                prevPoint := p
            }
        }

        last := points[points.Length]
        _ib_mouse_up(button, last[1], last[2])
        return []
    }

    if method = "scroll_mouse" {
        direction := StrLower(Trim(_ib_arg(args, 1, "down")))
        clicks := _ib_to_int(_ib_arg(args, 2, 1), 1)
        x := _ib_arg(args, 3, "")
        y := _ib_arg(args, 4, "")

        if clicks < 1
            clicks := 1

        if x != "" && y != ""
            _ib_set_cursor(_ib_to_int(x, 0), _ib_to_int(y, 0))

        wheelToken := direction = "up" ? "{WheelUp}" : "{WheelDown}"
        Loop clicks
            IbSend(wheelToken)
        return []
    }

    if method = "key_down" {
        key := _ib_normalize_key(_ib_arg(args, 1, ""))
        if key = ""
            throw Error("empty key")
        IbSend("{" key " down}")
        _ib_track_key_down(key)
        return []
    }

    if method = "key_up" {
        key := _ib_normalize_key(_ib_arg(args, 1, ""))
        if key = ""
            throw Error("empty key")
        IbSend("{" key " up}")
        _ib_track_key_up(key)
        return []
    }

    if method = "press_key" {
        key := _ib_normalize_key(_ib_arg(args, 1, ""))
        holdMs := _ib_to_number(_ib_arg(args, 2, 0.0), 0.0) * 1000.0
        if key = ""
            throw Error("empty key")

        if holdMs < 0
            holdMs := 0

        keyDownSent := false
        try {
            IbSend("{" key " down}")
            keyDownSent := true
            _ib_track_key_down(key)
            if holdMs > 0
                _ib_precise_hold_sleep_ms(holdMs)
            IbSend("{" key " up}")
            keyDownSent := false
            _ib_track_key_up(key)
        } finally {
            if keyDownSent {
                try IbSend("{" key " up}")
                _ib_track_key_up(key)
            }
        }
        return []
    }

    if method = "modified_key_press" {
        key := _ib_normalize_key(_ib_arg(args, 1, ""))
        holdMs := _ib_to_number(_ib_arg(args, 2, 0.0), 0.0) * 1000.0
        if key = ""
            throw Error("empty key")

        if holdMs < 0
            holdMs := 0

        heldKeys := []
        if args.Length >= 3 {
            Loop args.Length - 2 {
                heldKey := _ib_normalize_key(_ib_arg(args, A_Index + 2, ""))
                if heldKey != ""
                    heldKeys.Push(heldKey)
            }
        }

        chordText := _ib_build_modifier_chord_text(heldKeys, key)
        if chordText != "" {
            ; Logitech 后端对跨请求/显式 down-up 修饰状态不稳定；
            ; AHK 热键语法会在单次 SendInput 内生成标准修饰组合。
            IbSend(chordText)
            _ib_track_key_up(key)
            return []
        }

        downText := ""
        for _, heldKey in heldKeys {
            downText .= "{" heldKey " down}"
            _ib_track_key_down(heldKey)
        }
        downText .= "{" key " down}"

        keyDownSent := false
        try {
            ; Logitech/IbInputSimulator 需要把修饰键与主键放在同一次 IbSend 中，
            ; 否则 hook 在多次请求之间开关后，目标可能只收到裸主键。
            IbSend(downText)
            keyDownSent := true
            _ib_track_key_down(key)
            if holdMs > 0
                _ib_precise_hold_sleep_ms(holdMs)
            IbSend("{" key " up}")
            keyDownSent := false
            _ib_track_key_up(key)
        } finally {
            if keyDownSent {
                try IbSend("{" key " up}")
                _ib_track_key_up(key)
            }
        }
        return []
    }

    if method = "hotkey" {
        if args.Length < 1
            throw Error("empty hotkey")

        keys := []
        for _, item in args {
            keyName := _ib_normalize_key(item)
            if keyName != ""
                keys.Push(keyName)
        }

        if keys.Length < 1
            throw Error("empty hotkey")

        for _, keyName in keys {
            IbSend("{" keyName " down}")
            _ib_track_key_down(keyName)
        }

        _ib_precise_hold_sleep_ms(_ib_random_press_hold_ms())

        Loop keys.Length {
            idx := keys.Length - A_Index + 1
            keyName := keys[idx]
            IbSend("{" keyName " up}")
            _ib_track_key_up(keyName)
        }
        return []
    }

    if method = "type_text" {
        text := _ib_arg(args, 1, "")
        if text = ""
            return []
        IbSend("{Text}" text)
        return []
    }

    throw Error("unsupported method")
}

_ib_write_ok(reqId, tokens*) {
    line := "OK`t" reqId
    for _, token in tokens
        line .= "`t" token
    FileAppend(line "`n", "*")
}

_ib_write_err(reqId, message) {
    safeMsg := _ib_encode_string_token(message)
    FileAppend("ERR`t" reqId "`t" safeMsg "`n", "*")
}

_ib_format_init_error(errObj) {
    parts := []
    messageText := ""
    try messageText := Trim(errObj.Message)
    if messageText != ""
        parts.Push(messageText)

    whatText := ""
    try whatText := Trim(errObj.What)
    if whatText != ""
        parts.Push("what=" whatText)

    fileText := ""
    try fileText := Trim(errObj.File)
    if fileText != ""
        parts.Push("file=" fileText)

    lineText := ""
    try lineText := errObj.Line ""
    if lineText != ""
        parts.Push("line=" lineText)

    if A_LastError
        parts.Push("last_error=" A_LastError)

    if parts.Length = 0
        return "worker init failed"

    result := ""
    for _, item in parts {
        if result != ""
            result .= " | "
        result .= item
    }
    return result
}

_ib_arg(args, index, defaultValue := "") {
    if index >= 1 && index <= args.Length
        return args[index]
    return defaultValue
}

_ib_track_key_down(keyName) {
    global _ib_pressed_keys
    key := Trim(keyName)
    if key = ""
        return
    _ib_pressed_keys[key] := true
}

_ib_track_key_up(keyName) {
    global _ib_pressed_keys
    key := Trim(keyName)
    if key = ""
        return
    if _ib_pressed_keys.Has(key)
        _ib_pressed_keys.Delete(key)
}

_ib_build_modifier_chord_text(heldKeys, keyName) {
    if !IsObject(heldKeys) || heldKeys.Length < 1
        return ""

    prefix := ""
    seen := Map()
    for _, heldKey in heldKeys {
        token := _ib_modifier_prefix_token(heldKey)
        if token = ""
            return ""
        if seen.Has(token)
            continue
        seen[token] := true
        prefix .= token
    }

    if prefix = ""
        return ""

    return prefix _ib_key_send_token(keyName)
}

_ib_modifier_prefix_token(keyName) {
    key := StrLower(Trim(keyName))
    if key = "ctrl" || key = "control" || key = "lctrl" || key = "rctrl"
        return "^"
    if key = "alt" || key = "lalt" || key = "ralt"
        return "!"
    if key = "shift" || key = "lshift" || key = "rshift"
        return "+"
    if key = "lwin" || key = "rwin" || key = "win"
        return "#"
    return ""
}

_ib_key_send_token(keyName) {
    key := Trim(keyName)
    if key = ""
        return ""

    lowerKey := StrLower(key)
    if StrLen(key) = 1 {
        if RegExMatch(lowerKey, "^[a-z0-9]$")
            return lowerKey
        return "{" key "}"
    }

    return "{" key "}"
}

_ib_track_mouse_button_down(buttonName, x := "", y := "") {
    global _ib_pressed_buttons
    button := _ib_normalize_button(buttonName)
    tx := _ib_to_int(x, "")
    ty := _ib_to_int(y, "")
    if tx = "" || ty = "" {
        _ib_pressed_buttons[button] := true
        return
    }
    _ib_pressed_buttons[button] := [tx, ty]
}

_ib_track_mouse_button_up(buttonName) {
    global _ib_pressed_buttons
    button := _ib_normalize_button(buttonName)
    if _ib_pressed_buttons.Has(button)
        _ib_pressed_buttons.Delete(button)
}

_ib_release_all_inputs() {
    global _ib_pressed_keys, _ib_pressed_buttons

    pendingKeys := []
    for keyName, _ in _ib_pressed_keys
        pendingKeys.Push(keyName)

    for _, keyName in pendingKeys {
        try IbSend("{" keyName " up}")
    }

    pendingButtons := []
    for buttonName, buttonMeta in _ib_pressed_buttons
        pendingButtons.Push([buttonName, buttonMeta])

    if pendingButtons.Length > 0 {
        for _, item in pendingButtons {
            buttonName := item[1]
            buttonMeta := item[2]
            releaseX := ""
            releaseY := ""
            if IsObject(buttonMeta) && buttonMeta.Length >= 2 {
                releaseX := _ib_to_int(buttonMeta[1], "")
                releaseY := _ib_to_int(buttonMeta[2], "")
            }
            if releaseX = "" || releaseY = ""
                MouseGetPos(&releaseX, &releaseY)
            try _ib_mouse_up(buttonName, releaseX, releaseY)
        }
    }

    _ib_pressed_keys := Map()
    _ib_pressed_buttons := Map()
}

_ib_normalize_button(name) {
    key := StrLower(Trim(name))
    if key = "right" || key = "r" || key = "rbutton" || key = "右键"
        return "right"
    if key = "middle" || key = "m" || key = "mbutton" || key = "中键"
        return "middle"
    return "left"
}

_ib_mouse_down(button, x := "", y := "") {
    _ib_mouse_click(button, x, y, "D")
}

_ib_mouse_up(button, x := "", y := "") {
    _ib_mouse_click(button, x, y, "U")
}

_ib_emit_button_event_at_target(btn, tx, ty, downOrUp) {
    ; D/U 事件始终携带目标坐标，禁止使用当前坐标发包。
    ; 这样即使发生瞬时指针扰动，也不会退化为“在原位置点击”。
    IbMouseClick(btn, tx, ty, 1, 0, downOrUp)
}

_ib_button_to_ahk_name(button) {
    if button = "right"
        return "Right"
    if button = "middle"
        return "Middle"
    return "Left"
}

_ib_mouse_click(button, x := "", y := "", downOrUp := "") {
    if downOrUp != "" && downOrUp != "D" && downOrUp != "U"
        throw Error("UnsupportedMouseAction")
    if x = "" || y = ""
        throw Error("MouseCoordinatesRequired")

    btn := _ib_button_to_ahk_name(button)
    tx := _ib_to_int(x, 0)
    ty := _ib_to_int(y, 0)
    isDown := (downOrUp = "D")
    cursorClipped := false
    downSent := false
    mouseMoveBlocked := false
    if !_ib_ensure_cursor_at_point(tx, ty)
        throw Error("TargetVerifyFailed")
    ; 校准失败直接禁止发送任何点击消息。
    try {
        if downOrUp = "" {
            cursorClipped := _ib_clip_cursor_to_point(tx, ty)
            _ib_precise_sleep_ms(1)
            ; 完整点击：按下->随机按住->弹起，并保证异常时必定补发弹起。
            ; 期间阻止物理鼠标移动，避免微抖导致游戏判定为拖拽。
            try {
                BlockInput("MouseMove")
                mouseMoveBlocked := true
            } catch {
                mouseMoveBlocked := false
            }
            _ib_emit_button_event_at_target(btn, tx, ty, "D")
            downSent := true
            _ib_precise_sleep_ms(_ib_random_atomic_click_hold_ms())
            _ib_emit_button_event_at_target(btn, tx, ty, "U")
            downSent := false
            return
        }
        if isDown {
            cursorClipped := _ib_clip_cursor_to_point(tx, ty)
            _ib_precise_sleep_ms(12)
            _ib_emit_button_event_at_target(btn, tx, ty, downOrUp)
            return
        }
        ; 显式长按流程弹起同样固定发往目标坐标。
        cursorClipped := _ib_clip_cursor_to_point(tx, ty)
        _ib_precise_sleep_ms(1)
        _ib_emit_button_event_at_target(btn, tx, ty, downOrUp)
        return
    } finally {
        if downSent {
            try _ib_emit_button_event_at_target(btn, tx, ty, "U")
        }
        if mouseMoveBlocked {
            try BlockInput("MouseMoveOff")
        }
        if cursorClipped
            _ib_release_cursor_clip()
    }
}

_ib_clip_cursor_to_point(x, y) {
    tx := _ib_to_int(x, 0)
    ty := _ib_to_int(y, 0)
    rect := Buffer(16, 0)
    NumPut("Int", tx, rect, 0)
    NumPut("Int", ty, rect, 4)
    NumPut("Int", tx + 1, rect, 8)
    NumPut("Int", ty + 1, rect, 12)
    return DllCall("User32\ClipCursor", "Ptr", rect.Ptr, "Int")
}

_ib_release_cursor_clip() {
    DllCall("User32\ClipCursor", "Ptr", 0, "Int")
}

_ib_is_cursor_at_point(x, y, tolerance := 1) {
    tx := _ib_to_int(x, 0)
    ty := _ib_to_int(y, 0)
    tol := _ib_to_int(tolerance, 1)
    if tol < 0
        tol := 0
    MouseGetPos(&cx, &cy)
    return Abs(cx - tx) <= tol && Abs(cy - ty) <= tol
}

_ib_any_mouse_button_down() {
    return GetKeyState("LButton", "P")
        || GetKeyState("RButton", "P")
        || GetKeyState("MButton", "P")
}

_ib_wait_cursor_stable_at_point(x, y, tolerance := 1, timeoutMs := 14, stableSamples := 2) {
    tx := _ib_to_int(x, 0)
    ty := _ib_to_int(y, 0)
    maxMs := _ib_to_int(timeoutMs, 14)
    if maxMs < 1
        maxMs := 1
    requiredHits := _ib_to_int(stableSamples, 2)
    if requiredHits < 1
        requiredHits := 1
    hitCount := 0

    Loop maxMs {
        if _ib_is_cursor_at_point(tx, ty, tolerance) {
            hitCount += 1
            if hitCount >= requiredHits
                return true
        } else {
            hitCount := 0
        }
        _ib_precise_sleep_ms(1)
    }

    return _ib_is_cursor_at_point(tx, ty, tolerance)
}

_ib_ensure_cursor_at_point(x, y, tolerance := 1, attempts := 5) {
    tx := _ib_to_int(x, 0)
    ty := _ib_to_int(y, 0)
    maxAttempts := _ib_to_int(attempts, 5)
    if maxAttempts < 1
        maxAttempts := 1

    if _ib_wait_cursor_stable_at_point(tx, ty, tolerance, 8, 2)
        return true

    if _ib_any_mouse_button_down()
        return false

    Loop maxAttempts {
        if _ib_any_mouse_button_down()
            break
        try {
            _ib_set_cursor(tx, ty)
        } catch {
            DllCall("User32\SetCursorPos", "Int", tx, "Int", ty)
        }
        if _ib_wait_cursor_stable_at_point(tx, ty, tolerance, 14, 2)
            return true
    }

    return _ib_wait_cursor_stable_at_point(tx, ty, tolerance, 10, 2)
}

_ib_set_cursor(x, y) {
    tx := _ib_to_int(x, 0)
    ty := _ib_to_int(y, 0)
    ; 优先系统级瞬移，减少驱动移动路径对前台游戏视角的干扰。
    DllCall("User32\SetCursorPos", "Int", tx, "Int", ty)
    _ib_precise_sleep_ms(2)
    MouseGetPos(&cx, &cy)
    if Abs(cx - tx) <= 1 && Abs(cy - ty) <= 1
        return
    ; 回退到驱动移动，确保在受限场景仍可落位。
    IbMouseMove(tx, ty, 0)
    _ib_precise_sleep_ms(3)
    MouseGetPos(&cx2, &cy2)
    if Abs(cx2 - tx) > 1 || Abs(cy2 - ty) > 1
        throw Error("DriverMoveFailed")
}

_ib_move_cursor(x, y, absolute := true) {
    if absolute {
        _ib_set_cursor(x, y)
        return
    }

    dx := _ib_to_int(x, 0)
    dy := _ib_to_int(y, 0)
    if dx = 0 && dy = 0
        return

    ; 相对移动必须直接走驱动相对注入，不能转绝对坐标校验。
    ; 锁鼠标/第一人称视角场景下，绝对落点校验会稳定误判为失败。
    IbMouseMove(dx, dy, 0, "R")
}

_ib_drag_move_segment_with_py_profile(startX, startY, endX, endY, durationSec) {
    sx := _ib_to_int(startX, 0)
    sy := _ib_to_int(startY, 0)
    ex := _ib_to_int(endX, sx)
    ey := _ib_to_int(endY, sy)
    safeDuration := _ib_to_number(durationSec, 0.0)
    if safeDuration < 0
        safeDuration := 0.0

    ; 与前台二(PyAutoGUI)对齐：
    ; 1) duration <= 0.1 秒：直接到终点（近似瞬移）
    ; 2) 否则按每步最小 0.05 秒分段（约 20 FPS）
    if safeDuration <= 0.1 {
        _ib_set_cursor(ex, ey)
        return
    }

    steps := _ib_to_int(safeDuration / 0.05, 1)
    if steps < 1
        steps := 1
    stepDelayMs := _ib_to_int((safeDuration * 1000.0) / steps, 1)
    if stepDelayMs < 1
        stepDelayMs := 1

    Loop steps {
        ratio := A_Index / steps
        nx := _ib_to_int(sx + (ex - sx) * ratio, sx)
        ny := _ib_to_int(sy + (ey - sy) * ratio, sy)
        _ib_set_cursor(nx, ny)
        _ib_precise_sleep_ms(stepDelayMs)
    }
}

_ib_normalize_key(keyName) {
    key := Trim(keyName)
    if key = ""
        return ""

    lowerKey := StrLower(key)
    static keyMap := Map(
        "ctrl", "Ctrl",
        "control", "Ctrl",
        "alt", "Alt",
        "shift", "Shift",
        "win", "LWin",
        "lwin", "LWin",
        "rwin", "RWin",
        "enter", "Enter",
        "return", "Enter",
        "tab", "Tab",
        "space", "Space",
        "esc", "Esc",
        "escape", "Esc",
        "backspace", "Backspace",
        "delete", "Delete",
        "up", "Up",
        "down", "Down",
        "left", "Left",
        "right", "Right"
    )

    if keyMap.Has(lowerKey)
        return keyMap[lowerKey]

    if RegExMatch(lowerKey, "^f([1-9]|1[0-9]|2[0-4])$")
        return "F" SubStr(lowerKey, 2)

    return key
}

_ib_parse_points(serialized) {
    points := []
    text := Trim(serialized)
    if text = ""
        return points

    for _, pair in StrSplit(text, ";") {
        if pair = ""
            continue
        xy := StrSplit(pair, ",")
        if xy.Length < 2
            continue
        points.Push([_ib_to_int(xy[1], 0), _ib_to_int(xy[2], 0)])
    }
    return points
}

_ib_parse_numbers(serialized) {
    values := []
    text := Trim(serialized)
    if text = ""
        return values

    for _, part in StrSplit(text, ";") {
        if part = ""
            continue
        values.Push(_ib_to_number(part, 0.0))
    }
    return values
}

_ib_random_press_hold_ms() {
    return Random(50, 80)
}

_ib_random_atomic_click_hold_ms() {
    ; 对齐前台二：原子点击按住时长固定 50ms，避免随机抖动造成体感不一致。
    return 50
}


_ib_precise_sleep_ms(ms) {
    targetMs := _ib_to_number(ms, 0.0)
    if targetMs <= 0
        return

    static qpf := 0
    if qpf = 0 {
        freq := 0
        DllCall("Kernel32\QueryPerformanceFrequency", "Int64*", &freq)
        qpf := freq
    }
    if qpf <= 0 {
        Sleep(_ib_to_int(targetMs, 0))
        return
    }

    startCounter := 0
    DllCall("Kernel32\QueryPerformanceCounter", "Int64*", &startCounter)
    targetTicks := targetMs * qpf / 1000.0

    ; 长时长先粗睡眠到截止前20ms，再用高精度轮询收尾，避免Windows调度导致超睡。
    if targetMs >= 25.0 {
        coarseMs := _ib_to_int(targetMs - 20.0, 0)
        if coarseMs > 0
            DllCall("Kernel32\Sleep", "UInt", coarseMs)
    }

    Loop {
        nowCounter := 0
        DllCall("Kernel32\QueryPerformanceCounter", "Int64*", &nowCounter)
        elapsedTicks := (nowCounter - startCounter)
        if elapsedTicks >= targetTicks
            break
        remainingTicks := (targetTicks - elapsedTicks)
        ; 剩余时间较长时让出调度，末段改为忙等待避免额外调度抖动
        if remainingTicks > (qpf / 1000.0 * 0.8)
            DllCall("Kernel32\Sleep", "UInt", 0)
    }
}

_ib_precise_hold_sleep_ms(ms) {
    targetMs := _ib_to_number(ms, 0.0)
    if targetMs <= 0
        return

    static qpf := 0
    if qpf = 0 {
        freq := 0
        DllCall("Kernel32\QueryPerformanceFrequency", "Int64*", &freq)
        qpf := freq
    }
    if qpf <= 0 {
        _ib_precise_sleep_ms(targetMs)
        return
    }

    ; 对按住阶段启用高精度定时与更高线程优先级，压低高负载场景下的长尾抖动。
    timerRaised := false
    threadHandle := 0
    hasOriginalPriority := false
    originalPriority := 0
    THREAD_PRIORITY_HIGHEST := 2
    THREAD_PRIORITY_ERROR_RETURN := 2147483647

    try {
        try {
            beginResult := DllCall("Winmm\timeBeginPeriod", "UInt", 1, "UInt")
            if beginResult = 0
                timerRaised := true
        } catch {
        }

        try {
            threadHandle := DllCall("Kernel32\GetCurrentThread", "Ptr")
            if threadHandle {
                priority := DllCall("Kernel32\GetThreadPriority", "Ptr", threadHandle, "Int")
                if priority != THREAD_PRIORITY_ERROR_RETURN {
                    originalPriority := priority
                    hasOriginalPriority := true
                    if priority < THREAD_PRIORITY_HIGHEST
                        DllCall("Kernel32\SetThreadPriority", "Ptr", threadHandle, "Int", THREAD_PRIORITY_HIGHEST)
                }
            }
        } catch {
        }

        startCounter := 0
        DllCall("Kernel32\QueryPerformanceCounter", "Int64*", &startCounter)
        targetTicks := targetMs * qpf / 1000.0

        Loop {
            nowCounter := 0
            DllCall("Kernel32\QueryPerformanceCounter", "Int64*", &nowCounter)
            elapsedTicks := (nowCounter - startCounter)
            if elapsedTicks >= targetTicks
                break

            remainingTicks := (targetTicks - elapsedTicks)
            remainingMs := (remainingTicks * 1000.0) / qpf

            ; 保持阶段优先精度：保留>=12ms的收口窗口，降低系统调度导致的超睡。
            if remainingMs > 18.0 {
                sleepMs := _ib_to_int(remainingMs - 12.0, 0)
                if sleepMs > 0
                    DllCall("Kernel32\Sleep", "UInt", sleepMs)
                else
                    DllCall("Kernel32\Sleep", "UInt", 0)
            } else if remainingMs > 2.0 {
                DllCall("Kernel32\Sleep", "UInt", 0)
            }
        }
    } finally {
        if hasOriginalPriority && threadHandle {
            try DllCall("Kernel32\SetThreadPriority", "Ptr", threadHandle, "Int", originalPriority)
        }
        if timerRaised {
            try DllCall("Winmm\timeEndPeriod", "UInt", 1, "UInt")
        }
    }
}

_ib_to_int(value, defaultValue := 0) {
    try {
        return Round(value + 0)
    } catch {
        return defaultValue
    }
}

_ib_to_number(value, defaultValue := 0.0) {
    try {
        return value + 0
    } catch {
        return defaultValue
    }
}

_ib_to_bool(value, defaultValue := false) {
    if value = ""
        return defaultValue
    if IsNumber(value)
        return (value + 0) != 0

    text := StrLower(Trim(value))
    if text = "" || text = "0" || text = "false" || text = "no"
        return false
    return true
}

_ib_decode_token(token) {
    if token = "~"
        return ""

    prefix := SubStr(token, 1, 2)
    body := SubStr(token, 3)

    if prefix = "s:"
        return _ib_base64_decode(body)
    if prefix = "n:"
        return _ib_to_number(body, 0)
    if prefix = "b:"
        return body = "1"

    return token
}

_ib_encode_string_token(text) {
    return "s:" _ib_base64_encode(text)
}

_ib_base64_encode(text) {
    if text = ""
        return ""

    bytes := StrPut(text, "UTF-8") - 1
    if bytes <= 0
        return ""

    inBuf := Buffer(bytes, 0)
    StrPut(text, inBuf, "UTF-8")

    outChars := 0
    if !DllCall("Crypt32\CryptBinaryToStringW", "Ptr", inBuf.Ptr, "UInt", bytes, "UInt", 0x40000001, "Ptr", 0, "UIntP", &outChars)
        throw Error("base64 encode failed")

    outBuf := Buffer(outChars * 2, 0)
    if !DllCall("Crypt32\CryptBinaryToStringW", "Ptr", inBuf.Ptr, "UInt", bytes, "UInt", 0x40000001, "Ptr", outBuf.Ptr, "UIntP", &outChars)
        throw Error("base64 encode failed")

    encoded := StrGet(outBuf)
    encoded := StrReplace(encoded, "`r", "")
    encoded := StrReplace(encoded, "`n", "")
    return encoded
}

_ib_base64_decode(encoded) {
    if encoded = ""
        return ""

    bytes := 0
    if !DllCall("Crypt32\CryptStringToBinaryW", "Str", encoded, "UInt", 0, "UInt", 1, "Ptr", 0, "UIntP", &bytes, "Ptr", 0, "Ptr", 0)
        throw Error("base64 decode failed")

    outBuf := Buffer(bytes, 0)
    if !DllCall("Crypt32\CryptStringToBinaryW", "Str", encoded, "UInt", 0, "UInt", 1, "Ptr", outBuf.Ptr, "UIntP", &bytes, "Ptr", 0, "Ptr", 0)
        throw Error("base64 decode failed")

    return StrGet(outBuf, bytes, "UTF-8")
}



