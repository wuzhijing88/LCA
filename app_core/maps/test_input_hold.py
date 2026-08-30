from app_core.maps.input_hold import hold_key_via_keyboard_task


def test_hold_key_uses_unified_sequence_with_duration(monkeypatch):
    captured = {}

    def fake_execute(params, context, **kwargs):
        captured["params"] = params
        captured["context"] = context
        captured["kwargs"] = kwargs
        return True, "ok"

    monkeypatch.setattr("tasks.keyboard_input.execute_task", fake_execute)

    assert hold_key_via_keyboard_task(
        "w",
        0.15,
        execution_mode="前台",
        target_hwnd=123,
        stop_checker=lambda: False,
    )
    sequence = captured["params"]["combo_key_sequence_text"]
    assert "key_down(w)" in sequence
    assert "wait(0.15)" in sequence
    assert "key_up(w)" in sequence
    assert "main_key" not in captured["params"]
    assert "main_key_hold_duration" not in captured["params"]
