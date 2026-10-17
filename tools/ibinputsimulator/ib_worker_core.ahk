#Requires AutoHotkey v2.0

global _ib_pressed_keys := Map()
global _ib_pressed_buttons := Map()
global _ib_driver_name := ""
global _ib_stop_path := ""

IbWorkerMain(driverName, driverArg, stopPath) {
    global _ib_driver_name, _ib_stop_path
    _ib_driver_name := StrLower(Trim(driverName))
    _ib_stop_path := stopPath
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

    try {
        if parts.Length >= 3 {
            Loop parts.Length - 2 {
                args.Push(_ib_decode_token(parts[A_Index + 2]))
            }
        }

        tokens := _ib_dispatch(method, args)
        _ib_write_ok(reqId, tokens*)
    } catch as opErr {
        _ib_write_err(reqId, opErr.Message)
    }
}

_ib_dispatch(method, args) {
    if method != "release_all_inputs" && method != "exit" && method != "mouse_up" && method != "key_up"
        _ib_check_stop()
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
        x := _ib_to_int(_ib_arg(args, 1))
        y := _ib_to_int(_ib_arg(args, 2))
        absolute := _ib_to_bool(_ib_arg(args, 3))
        _ib_move_cursor(x, y, absolute)
        return []
    }

    if method = "click_mouse" {
        x := _ib_arg(args, 1)
        y := _ib_arg(args, 2)
        button := _ib_normalize_button(_ib_arg(args, 3))
        clicks := _ib_to_int(_ib_arg(args, 4))
        intervalMs := _ib_to_int(_ib_to_number(_ib_arg(args, 5)) * 1000.0)
        durationMs := _ib_to_int(_ib_to_number(_ib_arg(args, 6)) * 1000.0)

        if x = "" || y = ""
            throw Error("MouseCoordinatesRequired")
        tx := _ib_to_int(x)
        ty := _ib_to_int(y)

        if clicks < 1
            throw Error("鼠标次数必须是正整数")

        if intervalMs < 0 || durationMs < 0
            throw Error("点击时间不能为负数")
        Loop clicks {
            holdMs := durationMs > 0 ? durationMs : _ib_random_atomic_click_hold_ms()
            _ib_mouse_click(button, tx, ty, "", holdMs)

            if A_Index < clicks && intervalMs > 0
                _ib_precise_sleep_ms(intervalMs)
        }
        return []
    }

    if method = "mouse_down" {
        x := _ib_arg(args, 1)
        y := _ib_arg(args, 2)
        button := _ib_normalize_button(_ib_arg(args, 3))
        if x = "" || y = ""
            throw Error("MouseCoordinatesRequired")
        tx := _ib_to_int(x)
        ty := _ib_to_int(y)
        _ib_mouse_down(button, tx, ty)
        return []
    }

    if method = "mouse_up" {
        x := _ib_arg(args, 1)
        y := _ib_arg(args, 2)
        button := _ib_normalize_button(_ib_arg(args, 3))
        if x = "" || y = ""
            throw Error("MouseCoordinatesRequired")
        _ib_mouse_up(button, _ib_to_int(x), _ib_to_int(y))
        return []
    }

    if method = "drag_mouse" {
        sx := _ib_to_int(_ib_arg(args, 1))
        sy := _ib_to_int(_ib_arg(args, 2))
        ex := _ib_to_int(_ib_arg(args, 3))
        ey := _ib_to_int(_ib_arg(args, 4))
        button := _ib_normalize_button(_ib_arg(args, 5))
        duration := _ib_to_number(_ib_arg(args, 6))

        _ib_set_cursor(sx, sy)
        _ib_mouse_down(button, sx, sy)

        _ib_drag_move_segment_with_py_profile(sx, sy, ex, ey, duration, button)

        _ib_mouse_up(button, ex, ey)
        return []
    }

    if method = "drag_path" {
        pointsText := _ib_arg(args, 1)
        duration := _ib_to_number(_ib_arg(args, 2))
        button := _ib_normalize_button(_ib_arg(args, 3))
        timestampsText := _ib_arg(args, 4)

        points := _ib_parse_points(pointsText)
        if points.Length < 2
            throw Error("invalid drag path")

        ts := _ib_parse_numbers(timestampsText)
        if ts.Length > 0 && ts.Length != points.Length
            throw Error("拖拽时间戳数量与路径点数量不一致")
        prevTime := 0
        for _, stamp in ts {
            if stamp < prevTime
                throw Error("拖拽时间戳必须递增")
            prevTime := stamp
        }

        first := points[1]
        _ib_set_cursor(first[1], first[2])
        _ib_mouse_down(button, first[1], first[2])

        if ts.Length = points.Length {
            prev := _ib_to_number(ts[1])
            prevPoint := points[1]
            Loop points.Length - 1 {
                p := points[A_Index + 1]
                cur := _ib_to_number(ts[A_Index + 1])
                segDuration := cur - prev
                if segDuration < 0
                    segDuration := 0
                _ib_drag_move_segment_with_py_profile(
                    prevPoint[1],
                    prevPoint[2],
                    p[1],
                    p[2],
                    segDuration,
                    button
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
                    segDuration,
                    button
                )
                prevPoint := p
            }
        }

        last := points[points.Length]
        _ib_mouse_up(button, last[1], last[2])
        return []
    }

    if method = "scroll_mouse" {
        direction := StrLower(Trim(_ib_arg(args, 1)))
        clicks := _ib_to_int(_ib_arg(args, 2))
        x := _ib_arg(args, 3)
        y := _ib_arg(args, 4)

        if clicks < 1
            throw Error("鼠标次数必须是正整数")

        if x != "" && y != ""
            _ib_set_cursor(_ib_to_int(x), _ib_to_int(y))

        if direction != "up" && direction != "down"
            throw Error("不支持的滚轮方向")
        wheelToken := direction = "up" ? "{WheelUp}" : "{WheelDown}"
        Loop clicks
            IbSend(wheelToken)
        return []
    }

    if method = "key_down" {
        _ib_key_down(_ib_arg(args, 1))
        return []
    }

    if method = "key_up" {
        _ib_key_up(_ib_arg(args, 1))
        return []
    }

    if method = "press_key" {
        key := _ib_normalize_key(_ib_arg(args, 1))
        holdMs := _ib_to_number(_ib_arg(args, 2)) * 1000.0
        if key = ""
            throw Error("empty key")

        if holdMs < 0
            throw Error("按键保持时间不能为负数")

        keyDownSent := false
        try {
            _ib_key_down(key)
            keyDownSent := true
            if holdMs > 0
                _ib_hold_with_typematic(key, holdMs)
            _ib_key_up(key)
            keyDownSent := false
        } finally {
            if keyDownSent {
                try _ib_key_up(key)
            }
        }
        return []
    }

    if method = "modified_key_press" {
        key := _ib_normalize_key(_ib_arg(args, 1))
        holdMs := _ib_to_number(_ib_arg(args, 2)) * 1000.0
        if key = ""
            throw Error("empty key")

        if holdMs < 0
            throw Error("按键保持时间不能为负数")

        heldKeys := []
        if args.Length >= 3 {
            Loop args.Length - 2 {
                heldKey := _ib_normalize_key(_ib_arg(args, A_Index + 2))
                if heldKey != ""
                    heldKeys.Push(heldKey)
            }
        }

        for _, heldKey in heldKeys {
            _ib_key_down(heldKey)
        }

        keyDownSent := false
        try {
            _ib_key_down(key)
            keyDownSent := true
            if holdMs > 0
                _ib_hold_with_typematic(key, holdMs)
            _ib_key_up(key)
            keyDownSent := false
        } finally {
            if keyDownSent {
                try _ib_key_up(key)
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
            _ib_key_down(keyName)
        }

        _ib_precise_hold_sleep_ms(_ib_random_press_hold_ms())

        Loop keys.Length {
            idx := keys.Length - A_Index + 1
            keyName := keys[idx]
            _ib_key_up(keyName)
        }
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

_ib_arg(args, index) {
    if index < 1 || index > args.Length
        throw Error("输入请求缺少参数")
    return args[index]
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

_ib_key_down(keyName) {
    key := _ib_normalize_key(keyName)
    if key = ""
        throw Error("empty key")
    _ib_send_key_event(key, true)
    _ib_track_key_down(key)
}

_ib_key_up(keyName) {
    key := _ib_normalize_key(keyName)
    if key = ""
        throw Error("empty key")
    _ib_send_key_event(key, false)
    _ib_track_key_up(key)
}

_ib_send_key_event(keyName, keyDown) {
    ; 不走 IbSend("{key down}")：它每次开关 SendInput hook，罗技后端会把已按下的键冲掉，
    ; 自定义脚本 按键("right", 秒=4) 就会变成只点一下。
    vk := GetKeyVK(keyName)
    if vk = 0
        throw Error("unknown key")
    sc := GetKeySC(keyName)
    KEYEVENTF_EXTENDEDKEY := 0x0001
    KEYEVENTF_KEYUP := 0x0002
    flags := 0
    if (sc & 0x100)
        flags |= KEYEVENTF_EXTENDEDKEY
    if !keyDown
        flags |= KEYEVENTF_KEYUP
    DllCall("IbInputSimulator\IbSend_keybd_event", "UChar", vk, "UChar", sc & 0xFF, "UInt", flags, "UPtr", 0)
}

_ib_keyboard_repeat_delay_ms() {
    ; SPI_GETKEYBOARDDELAY: 0..3 → (n+1)*250 毫秒
    delay := 0
    if !DllCall("User32\SystemParametersInfoW", "UInt", 0x16, "UInt", 0, "Int*", &delay, "UInt", 0, "Int")
        throw Error("读取键盘重复延迟失败")
    if delay < 0 || delay > 3
        throw Error("键盘重复延迟无效")
    return (delay + 1) * 250
}

_ib_keyboard_repeat_interval_ms() {
    ; SPI_GETKEYBOARDSPEED: 0..31 → 约 2.5~30 次/秒
    speed := 0
    if !DllCall("User32\SystemParametersInfoW", "UInt", 0x0A, "UInt", 0, "Int*", &speed, "UInt", 0, "Int")
        throw Error("读取键盘重复速率失败")
    if speed < 0 || speed > 31
        throw Error("键盘重复速率无效")
    rps := 2.5 + speed * (27.5 / 31.0)
    return 1000.0 / rps
}

_ib_hold_with_typematic(key, holdMs) {
    ; 人手按住会先停顿再连发。罗技 HID 按住不会连发，必须在同一驱动通道上补 make/break。
    targetMs := _ib_to_number(holdMs)
    if targetMs <= 0
        return

    delayMs := _ib_keyboard_repeat_delay_ms()
    intervalMs := _ib_keyboard_repeat_interval_ms()

    static qpf := 0
    if qpf = 0 {
        freq := 0
        DllCall("Kernel32\QueryPerformanceFrequency", "Int64*", &freq)
        qpf := freq
    }
    if qpf <= 0
        throw Error("高精度计时不可用")

    startCounter := 0
    DllCall("Kernel32\QueryPerformanceCounter", "Int64*", &startCounter)
    targetTicks := targetMs * qpf / 1000.0

    firstMs := delayMs
    if firstMs > targetMs
        firstMs := targetMs
    _ib_precise_hold_sleep_ms(firstMs)

    Loop {
        nowCounter := 0
        DllCall("Kernel32\QueryPerformanceCounter", "Int64*", &nowCounter)
        elapsedTicks := nowCounter - startCounter
        if elapsedTicks >= targetTicks
            break

        _ib_key_up(key)
        _ib_key_down(key)

        nowCounter := 0
        DllCall("Kernel32\QueryPerformanceCounter", "Int64*", &nowCounter)
        remainingMs := ((targetTicks - (nowCounter - startCounter)) * 1000.0) / qpf
        if remainingMs <= 0
            break
        slice := intervalMs
        if slice > remainingMs
            slice := remainingMs
        _ib_precise_hold_sleep_ms(slice)
    }
}

_ib_track_mouse_button_down(buttonName, x := "", y := "") {
    global _ib_pressed_buttons
    button := _ib_normalize_button(buttonName)
    tx := _ib_to_int(x)
    ty := _ib_to_int(y)
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
    failures := []
    pendingKeys := []
    for keyName, _ in _ib_pressed_keys
        pendingKeys.Push(keyName)
    for _, keyName in pendingKeys {
        try _ib_key_up(keyName)
        catch as err
            failures.Push(err.Message)
    }
    pendingButtons := []
    for buttonName, _ in _ib_pressed_buttons
        pendingButtons.Push(buttonName)
    for _, buttonName in pendingButtons {
        try _ib_mouse_up(buttonName)
        catch as err
            failures.Push(err.Message)
    }
    if failures.Length > 0
        throw Error("输入释放失败：" failures[1])
}

_ib_normalize_button(name) {
    key := StrLower(Trim(name))
    if key != "left" && key != "right" && key != "middle"
        throw Error("不支持的鼠标按钮：" name)
    return key
}

_ib_mouse_down(button, x := "", y := "") {
    _ib_track_mouse_button_down(button, x, y)
    _ib_mouse_click(button, x, y, "D")
}

_ib_mouse_up(button, x := "", y := "") {
    ; 弹起只有按钮事件：不校准、不移动，不受坐标查询失败影响。
    normalized := _ib_normalize_button(button)
    _ib_send_mouse_button_event(_ib_button_to_ahk_name(normalized), "U")
    _ib_track_mouse_button_up(normalized)
}

_ib_send_mouse_button_event(btn, downOrUp) {
    ; 不走 IbMouseClick：罗技后端在开关 SendInput hook 时可能只吃移动包，按下/松开被丢掉。
    MOUSEEVENTF_LEFTDOWN := 0x0002
    MOUSEEVENTF_LEFTUP := 0x0004
    MOUSEEVENTF_RIGHTDOWN := 0x0008
    MOUSEEVENTF_RIGHTUP := 0x0010
    MOUSEEVENTF_MIDDLEDOWN := 0x0020
    MOUSEEVENTF_MIDDLEUP := 0x0040
    isDown := (downOrUp = "D")
    if btn = "Right"
        flags := isDown ? MOUSEEVENTF_RIGHTDOWN : MOUSEEVENTF_RIGHTUP
    else if btn = "Middle"
        flags := isDown ? MOUSEEVENTF_MIDDLEDOWN : MOUSEEVENTF_MIDDLEUP
    else
        flags := isDown ? MOUSEEVENTF_LEFTDOWN : MOUSEEVENTF_LEFTUP
    DllCall("IbInputSimulator\IbSend_mouse_event", "UInt", flags, "UInt", 0, "UInt", 0, "UInt", 0, "UPtr", 0)
}

_ib_send_mouse_move_with_button(button, dx, dy) {
    ; 罗技报告的按钮位是每包状态。运行库的移动包不会自动继承按下位，
    ; 拖拽移动必须在每个相对位移包里继续携带当前按钮。
    normalized := _ib_normalize_button(button)
    MOUSEEVENTF_MOVE := 0x0001
    MOUSEEVENTF_LEFTDOWN := 0x0002
    MOUSEEVENTF_RIGHTDOWN := 0x0008
    MOUSEEVENTF_MIDDLEDOWN := 0x0020
    if normalized = "right"
        flags := MOUSEEVENTF_MOVE | MOUSEEVENTF_RIGHTDOWN
    else if normalized = "middle"
        flags := MOUSEEVENTF_MOVE | MOUSEEVENTF_MIDDLEDOWN
    else
        flags := MOUSEEVENTF_MOVE | MOUSEEVENTF_LEFTDOWN
    DllCall(
        "IbInputSimulator\IbSend_mouse_event",
        "UInt", flags,
        "UInt", dx,
        "UInt", dy,
        "UInt", 0,
        "UPtr", 0
    )
}

_ib_emit_button_event_at_target(btn, tx, ty, downOrUp) {
    ; D/U 事件始终携带目标坐标，禁止使用当前坐标发包。
    ; 这样即使发生瞬时指针扰动，也不会退化为“在原位置点击”。
    if _ib_is_logitech_driver() {
        _ib_send_mouse_button_event(btn, downOrUp)
        return
    }
    IbMouseClick(btn, tx, ty, 1, 0, downOrUp)
}

_ib_button_to_ahk_name(button) {
    if button = "right"
        return "Right"
    if button = "middle"
        return "Middle"
    return "Left"
}

_ib_mouse_click(button, x := "", y := "", downOrUp := "", holdMs := 50) {
    if downOrUp = "U" {
        _ib_mouse_up(button)
        return
    }
    if downOrUp != "" && downOrUp != "D"
        throw Error("不支持的鼠标动作")
    if x = "" || y = ""
        throw Error("鼠标操作需要坐标")
    button := _ib_normalize_button(button)
    btn := _ib_button_to_ahk_name(button)
    tx := _ib_to_int(x)
    ty := _ib_to_int(y)
    if _ib_any_mouse_button_down() || !_ib_ensure_cursor_at_point(tx, ty, 1, 5)
        throw Error("鼠标未到达点击位置或按钮尚未松开")

    previousClip := _ib_clip_cursor_to_point(tx, ty)
    if !IsObject(previousClip)
        throw Error("无法限制点击期间的鼠标活动范围")
    downSent := false
    try {
        _ib_precise_sleep_ms(1)
        _ib_track_mouse_button_down(button, tx, ty)
        downSent := true
        _ib_emit_button_event_at_target(btn, tx, ty, "D")
        if downOrUp = "D" {
            downSent := false
            return
        }
        _ib_precise_hold_sleep_ms(holdMs)
    } finally {
        try {
            if downSent
                _ib_mouse_up(button)
        } finally {
            _ib_release_cursor_clip(previousClip)
        }
    }
}

_ib_clip_cursor_to_point(x, y) {
    previousClip := Buffer(16, 0)
    if !DllCall("User32\GetClipCursor", "Ptr", previousClip.Ptr, "Int")
        return false
    rect := Buffer(16, 0)
    NumPut("Int", _ib_to_int(x), rect, 0)
    NumPut("Int", _ib_to_int(y), rect, 4)
    NumPut("Int", _ib_to_int(x) + 1, rect, 8)
    NumPut("Int", _ib_to_int(y) + 1, rect, 12)
    if !DllCall("User32\ClipCursor", "Ptr", rect.Ptr, "Int")
        return false
    return previousClip
}

_ib_release_cursor_clip(previousClip) {
    if !DllCall("User32\ClipCursor", "Ptr", previousClip.Ptr, "Int")
        throw Error("无法恢复鼠标活动范围")
}

_ib_is_cursor_at_point(x, y, tolerance := 1) {
    tx := _ib_to_int(x)
    ty := _ib_to_int(y)
    tol := _ib_to_int(tolerance)
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
    tx := _ib_to_int(x)
    ty := _ib_to_int(y)
    maxMs := _ib_to_int(timeoutMs)
    if maxMs < 1
        maxMs := 1
    requiredHits := _ib_to_int(stableSamples)
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

_ib_ensure_cursor_at_point(x, y, tolerance := 1, attempts := 5, allowButtonDown := false) {
    tx := _ib_to_int(x)
    ty := _ib_to_int(y)
    maxAttempts := _ib_to_int(attempts)
    if maxAttempts < 1
        maxAttempts := 1

    if _ib_wait_cursor_stable_at_point(tx, ty, tolerance, 8, 2)
        return true

    ; 按下前发现有键按着说明状态脏了，不许移动；弹起 / 拖拽中途则必须允许移动。
    if !allowButtonDown && _ib_any_mouse_button_down()
        return false

    Loop maxAttempts {
        if !allowButtonDown && _ib_any_mouse_button_down()
            break
        _ib_set_cursor(tx, ty)
        if _ib_wait_cursor_stable_at_point(tx, ty, tolerance, 14, 2)
            return true
    }

    return _ib_wait_cursor_stable_at_point(tx, ty, tolerance, 10, 2)
}

_ib_is_logitech_driver() {
    global _ib_driver_name
    return _ib_driver_name = "logitech" || _ib_driver_name = "logitechghubnew"
}

_ib_set_cursor(x, y, heldButton := "") {
    tx := _ib_to_int(x)
    ty := _ib_to_int(y)
    if _ib_is_logitech_driver() {
        Loop 4 {
            MouseGetPos(&cx, &cy)
            dx := tx - cx
            dy := ty - cy
            if Abs(dx) <= 1 && Abs(dy) <= 1
                return
            if heldButton != ""
                _ib_send_mouse_move_with_button(heldButton, dx, dy)
            else
                IbMouseMove(dx, dy, 0, "R")
            _ib_precise_sleep_ms(3)
            if _ib_is_cursor_at_point(tx, ty, 1)
                return
        }
    } else {
        IbMouseMove(tx, ty, 0)
        _ib_precise_sleep_ms(3)
    }
    if !_ib_is_cursor_at_point(tx, ty, 1)
        throw Error("鼠标移动失败")
}

_ib_move_cursor(x, y, absolute := true) {
    if absolute {
        _ib_set_cursor(x, y)
        return
    }

    dx := _ib_to_int(x)
    dy := _ib_to_int(y)
    if dx = 0 && dy = 0
        return

    ; 相对移动必须直接走驱动相对注入，不能转绝对坐标校验。
    ; 锁鼠标/第一人称视角场景下，绝对落点校验会稳定误判为失败。
    IbMouseMove(dx, dy, 0, "R")
}

_ib_drag_move_segment_with_py_profile(startX, startY, endX, endY, durationSec, button := "") {
    sx := _ib_to_int(startX)
    sy := _ib_to_int(startY)
    ex := _ib_to_int(endX)
    ey := _ib_to_int(endY)
    safeDuration := _ib_to_number(durationSec)
    if safeDuration < 0
        safeDuration := 0.0

    ; 与前台二(PyAutoGUI)对齐：
    ; 1) duration <= 0.1 秒：直接到终点（近似瞬移）
    ; 2) 否则按每步最小 0.05 秒分段（约 20 FPS）
    if safeDuration <= 0.1 {
        _ib_set_cursor(ex, ey, button)
        return
    }

    steps := _ib_to_int(safeDuration / 0.05)
    if steps < 1
        steps := 1
    stepDelayMs := _ib_to_int((safeDuration * 1000.0) / steps)
    if stepDelayMs < 1
        stepDelayMs := 1

    Loop steps {
        ratio := A_Index / steps
        nx := _ib_to_int(sx + (ex - sx) * ratio)
        ny := _ib_to_int(sy + (ey - sy) * ratio)
        _ib_set_cursor(nx, ny, button)
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
        xy := StrSplit(pair, ",")
        if xy.Length != 2
            throw Error("拖拽坐标格式无效")
        points.Push([_ib_to_int(xy[1]), _ib_to_int(xy[2])])
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
            throw Error("拖拽时间戳格式无效")
        values.Push(_ib_to_number(part))
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
    targetMs := _ib_to_number(ms)
    if targetMs <= 0
        return

    static qpf := 0
    if qpf = 0 {
        freq := 0
        DllCall("Kernel32\QueryPerformanceFrequency", "Int64*", &freq)
        qpf := freq
    }
    if qpf <= 0
        throw Error("高精度计时不可用")

    startCounter := 0
    DllCall("Kernel32\QueryPerformanceCounter", "Int64*", &startCounter)
    targetTicks := targetMs * qpf / 1000.0

    Loop {
        _ib_check_stop()
        nowCounter := 0
        DllCall("Kernel32\QueryPerformanceCounter", "Int64*", &nowCounter)
        elapsedTicks := (nowCounter - startCounter)
        if elapsedTicks >= targetTicks
            break
        remainingTicks := (targetTicks - elapsedTicks)
        ; 剩余时间较长时让出调度，末段改为忙等待避免额外调度抖动
        if remainingTicks > (qpf / 1000.0 * 20)
            DllCall("Kernel32\Sleep", "UInt", 10)
        else if remainingTicks > (qpf / 1000.0 * 0.8)
            DllCall("Kernel32\Sleep", "UInt", 0)
    }
}

_ib_precise_hold_sleep_ms(ms) {
    targetMs := _ib_to_number(ms)
    if targetMs <= 0
        return

    static qpf := 0
    if qpf = 0 {
        freq := 0
        DllCall("Kernel32\QueryPerformanceFrequency", "Int64*", &freq)
        qpf := freq
    }
    if qpf <= 0
        throw Error("高精度计时不可用")

    ; 对按住阶段启用高精度定时与更高线程优先级，压低高负载场景下的长尾抖动。
    timerRaised := false
    threadHandle := 0
    hasOriginalPriority := false
    originalPriority := 0
    THREAD_PRIORITY_HIGHEST := 2
    THREAD_PRIORITY_ERROR_RETURN := 2147483647

    try {
        beginResult := DllCall("Winmm\timeBeginPeriod", "UInt", 1, "UInt")
        if beginResult != 0
            throw Error("无法设置保持阶段的计时精度")
        timerRaised := true
        threadHandle := DllCall("Kernel32\GetCurrentThread", "Ptr")
        if !threadHandle
            throw Error("无法读取当前输入线程")
        priority := DllCall("Kernel32\GetThreadPriority", "Ptr", threadHandle, "Int")
        if priority = THREAD_PRIORITY_ERROR_RETURN
            throw Error("无法读取输入线程优先级")
        originalPriority := priority
        hasOriginalPriority := true
        if priority < THREAD_PRIORITY_HIGHEST && !DllCall("Kernel32\SetThreadPriority", "Ptr", threadHandle, "Int", THREAD_PRIORITY_HIGHEST)
            throw Error("无法设置输入线程优先级")

        startCounter := 0
        DllCall("Kernel32\QueryPerformanceCounter", "Int64*", &startCounter)
        targetTicks := targetMs * qpf / 1000.0

        Loop {
            _ib_check_stop()
            nowCounter := 0
            DllCall("Kernel32\QueryPerformanceCounter", "Int64*", &nowCounter)
            elapsedTicks := (nowCounter - startCounter)
            if elapsedTicks >= targetTicks
                break

            remainingTicks := (targetTicks - elapsedTicks)
            remainingMs := (remainingTicks * 1000.0) / qpf

            ; 保持阶段优先精度：保留>=12ms的收口窗口，降低系统调度导致的超睡。
            if remainingMs > 18.0 {
                sleepMs := _ib_to_int(remainingMs - 12.0)
                if sleepMs > 10
                    sleepMs := 10
                if sleepMs > 0
                    DllCall("Kernel32\Sleep", "UInt", sleepMs)
                else
                    DllCall("Kernel32\Sleep", "UInt", 0)
            } else if remainingMs > 2.0 {
                DllCall("Kernel32\Sleep", "UInt", 0)
            }
        }
    } finally {
        try {
            if hasOriginalPriority && threadHandle && !DllCall("Kernel32\SetThreadPriority", "Ptr", threadHandle, "Int", originalPriority)
                throw Error("无法恢复输入线程优先级")
        } finally {
            if timerRaised && DllCall("Winmm\timeEndPeriod", "UInt", 1, "UInt") != 0
                throw Error("无法恢复计时精度")
        }
    }
}

_ib_check_stop() {
    global _ib_stop_path
    if _ib_stop_path != "" && FileExist(_ib_stop_path)
        throw Error("输入已停止")
}

_ib_to_int(value) {
    return Round(value + 0)
}

_ib_to_number(value) {
    return value + 0
}

_ib_to_bool(value) {
    if value != 0 && value != 1
        throw Error("布尔参数无效")
    return value = 1
}

_ib_decode_token(token) {
    if token = "~"
        return ""

    prefix := SubStr(token, 1, 2)
    body := SubStr(token, 3)

    if prefix = "s:"
        return _ib_base64_decode(body)
    if prefix = "n:"
        return _ib_to_number(body)
    if prefix = "b:" && (body = "0" || body = "1")
        return body = "1"

    throw Error("输入令牌格式无效")
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


