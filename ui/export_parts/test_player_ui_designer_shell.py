import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app_core.player.package import default_player_ui
from ui.export_parts.player_ui_designer import PlayerUiDesignerDialog


def _qapp():
    return QApplication.instance() or QApplication([])


def test_designer_saves_seed_theme_and_layout():
    _qapp()
    seed = default_player_ui("演示", with_widgets=True)
    seed["theme"] = "dark"
    seed["layout"] = "tray"
    dialog = PlayerUiDesignerDialog(app_name="演示", ui=seed)
    payload = dialog._build_ui_payload()
    assert payload["theme"] == "dark"
    assert payload["layout"] == "tray"
    dialog.close()


def test_designer_canvas_matches_player_shell_radius():
    _qapp()
    from ui.export_parts.player_ui_designer import DesignerCanvas, designer_panel_item_qss
    from ui.player.player_chrome import PLAYER_PANEL_RADIUS, PLAYER_SHELL_RADIUS

    canvas = DesignerCanvas()
    assert canvas.CORNER_RADIUS == PLAYER_SHELL_RADIUS
    assert canvas.CORNER_RADIUS == 8
    qss = designer_panel_item_qss("#111111", "#333333", "#eeeeee", 12)
    compact = qss.replace(" ", "")
    assert "background:transparent" in compact
    assert "border:1pxsolid#333333" in compact
    assert f"border-radius:{PLAYER_PANEL_RADIUS}px" in compact
    canvas.deleteLater()


def test_designer_progress_preview_is_the_track_itself():
    """预览：整个控件区域就是轨道，不再套外框。"""
    from PySide6.QtGui import QImage

    from ui.export_parts.player_ui_designer import DesignerItem

    _qapp()
    item = DesignerItem(
        {
            "id": "progress_preview",
            "type": "progress",
            "title": "进度",
            "x": 0,
            "y": 0,
            "w": 220,
            "h": 28,
        }
    )
    item.resize(220, 28)
    item._refresh_look()
    assert item._caption == "待命"
    image = QImage(item.size(), QImage.Format.Format_ARGB32)
    image.fill(0)
    item.render(image)
    # 中心应有轨道底色像素
    sample = image.pixelColor(item.width() // 2, item.height() // 2)
    assert sample.alpha() > 0
    item.deleteLater()


def test_designer_log_preview_shows_toolbar_chips():
    """画布日志预览需画出清空/复制/目录，与运行窗顶栏一致。"""
    from ui.export_parts.player_ui_designer import DesignerItem

    _qapp()
    item = DesignerItem(
        {
            "id": "log_preview",
            "type": "log",
            "x": 0,
            "y": 0,
            "w": 230,
            "h": 120,
        }
    )
    item.resize(230, 120)
    item._refresh_look()
    assert "清空" in item._caption
    assert "复制" in item._caption
    assert "目录" in item._caption
    item.deleteLater()


def test_designer_can_switch_theme_and_layout():
    _qapp()
    dialog = PlayerUiDesignerDialog(app_name="演示")
    theme_index = dialog._theme_combo.findData("light")
    layout_index = dialog._layout_combo.findData("floating")
    assert theme_index >= 0
    assert layout_index >= 0
    dialog._theme_combo.setCurrentIndex(theme_index)
    dialog._layout_combo.setCurrentIndex(layout_index)
    payload = dialog._build_ui_payload()
    assert payload["theme"] == "light"
    assert payload["layout"] == "floating"
    dialog.close()


def test_host_theme_change_schedules_live_player_refresh():
    """主编辑器切主题时，已打开的调试窗应排队重建，而不是半套新主题。"""
    from themes import get_theme_manager

    app = _qapp()
    dialog = PlayerUiDesignerDialog(app_name="演示", live_run_context=lambda: {"workflow_data": {"cards": []}})
    dialog._live_player = object()  # 占位：表示调试窗仍打开
    called = {"n": 0}
    dialog._run_live = lambda: called.__setitem__("n", called["n"] + 1)

    mgr = get_theme_manager()
    prev = mgr.get_theme_mode()
    try:
        # 先落到一个已知主题，再切到另一侧以触发 token 变化
        other = "dark" if mgr.get_current_theme() != "dark" else "light"
        mgr.apply_theme(app, other)
        app.processEvents()
        assert dialog._live_refresh_pending is True or called["n"] >= 1
        app.processEvents()
        assert called["n"] >= 1
    finally:
        dialog._live_player = None
        mgr.apply_theme(app, prev)
        dialog.close()


def test_cancel_dev_player_theme_restore_skips_host_revert():
    from ui.export_parts.player_dev_run import cancel_dev_player_theme_restore

    class _Win:
        pass

    win = _Win()
    state = {"done": False}

    def _cancel():
        state["done"] = True

    win._cancel_dev_theme_restore = _cancel
    cancel_dev_player_theme_restore(win)
    assert state["done"] is True


def test_designer_add_menu_has_script_list_not_loop_settings():
    _qapp()
    catalog = [{"id": "a", "title": "日常"}, {"id": "b", "title": "刷图"}]
    dialog = PlayerUiDesignerDialog(app_name="演示", script_catalog=lambda: catalog)
    labels = [act.text() for act in dialog._add_menu.actions()]
    assert "脚本列表" in labels
    assert "循环设置" not in labels
    assert "进度条" in labels
    assert "设置按钮" in labels
    assert "定时执行" in labels
    dialog.close()


def test_designer_can_add_multiple_script_lists_with_exclusive_pool():
    _qapp()
    catalog = [
        {"id": "a", "title": "日常"},
        {"id": "b", "title": "刷图"},
    ]
    dialog = PlayerUiDesignerDialog(app_name="演示", script_catalog=lambda: catalog)
    # seed 默认已有一个脚本列表；再加一个应为空列表
    before = sum(1 for it in dialog.canvas._items.values() if it.data.get("type") == "script_list")
    first = next(it for it in dialog.canvas._items.values() if it.data.get("type") == "script_list")
    # 从第一个列表移出一项，应进入可分配池
    data = first.export_data()
    data["items"] = [data["items"][0]] if data.get("items") else []
    first.apply_data(data)
    dialog._add_script_list()
    lists = [it for it in dialog.canvas._items.values() if it.data.get("type") == "script_list"]
    assert len(lists) == before + 1
    empty = [it for it in lists if not (it.data.get("items") or [])]
    assert empty, "额外脚本列表应默认可为空以便互斥分配"
    dialog.canvas.select(empty[0].widget_id)
    dialog._fill_script_editor(list(empty[0].data.get("items") or []))
    assert dialog._script_pool.count() >= 1
    dialog.close()


def test_designer_keeps_script_list_loops_and_migrates_old_loop_settings():
    _qapp()
    seed = default_player_ui("演示", with_widgets=True)
    for widget in seed.get("widgets") or []:
        if widget.get("type") == "script_list":
            widget["group_loops"] = 1
            widget["items"] = [
                {"id": "a", "title": "日常", "checked": True, "loops": 1},
                {"id": "b", "title": "刷图", "checked": True, "loops": 1},
            ]
            break
    seed["widgets"].append(
        {
            "type": "loop_settings",
            "title": "循环",
            "group_loops": 2,
            "items": [
                {"id": "a", "title": "日常", "checked": True, "loops": 3},
                {"id": "b", "title": "刷图", "checked": True, "loops": 1},
            ],
        }
    )
    dialog = PlayerUiDesignerDialog(app_name="演示", ui=seed)
    payload = dialog._build_ui_payload()
    assert not any(w.get("type") == "loop_settings" for w in payload["widgets"])
    scripts = [w for w in payload["widgets"] if w.get("type") == "script_list"][0]
    assert scripts["group_loops"] == 2
    assert scripts["items"][0]["loops"] == 3
    dialog.close()


def test_script_item_display_shows_running_status():
    from ui.player.player_chrome import script_item_display_text

    assert script_item_display_text("日常", 1) == "日常"
    assert script_item_display_text("日常", 3) == "日常  ×3"
    assert "执行中 2/3" in script_item_display_text(
        "刷图", 3, status="running", loop_index=2, loop_total=3
    )


def _first_canvas_item(dialog):
    item = next(iter(dialog.canvas._items.values()))
    dialog.canvas.select(item.widget_id)
    return item


def test_designer_nudge_selected_moves_one_pixel():
    _qapp()
    seed = default_player_ui("演示", with_widgets=True)
    dialog = PlayerUiDesignerDialog(app_name="演示", ui=seed)
    item = _first_canvas_item(dialog)
    x0, y0 = int(item.data.get("x") or 0), int(item.data.get("y") or 0)
    assert dialog.canvas.nudge_selected(1, 0) is True
    assert int(item.data.get("x") or 0) == x0 + 1
    assert int(item.data.get("y") or 0) == y0
    assert dialog.canvas.nudge_selected(0, -1) is True
    assert int(item.data.get("y") or 0) == y0 - 1
    dialog.close()


def test_designer_nudge_selected_clamps_to_canvas():
    _qapp()
    seed = default_player_ui("演示", with_widgets=True)
    dialog = PlayerUiDesignerDialog(app_name="演示", ui=seed)
    item = _first_canvas_item(dialog)
    item.data["x"] = 0
    item.data["y"] = 0
    item._apply_geometry()
    assert dialog.canvas.nudge_selected(-4, -4) is False
    assert int(item.data.get("x") or 0) == 0
    assert int(item.data.get("y") or 0) == 0
    dialog.close()


def test_designer_arrow_keys_nudge_selected_widget():
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    app = _qapp()
    seed = default_player_ui("演示", with_widgets=True)
    dialog = PlayerUiDesignerDialog(app_name="演示", ui=seed)
    item = _first_canvas_item(dialog)
    dialog.canvas.setFocus()
    app.processEvents()
    x0 = int(item.data.get("x") or 0)
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    assert dialog._try_nudge_from_key(ev) is True
    assert int(item.data.get("x") or 0) == x0 + 1
    ev_shift = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert dialog._try_nudge_from_key(ev_shift) is True
    assert int(item.data.get("x") or 0) == x0 + 11
    dialog.close()


def test_designer_arrow_keys_do_not_steal_from_text_fields():
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    app = _qapp()
    seed = default_player_ui("演示", with_widgets=True)
    dialog = PlayerUiDesignerDialog(app_name="演示", ui=seed)
    item = _first_canvas_item(dialog)
    x0 = int(item.data.get("x") or 0)
    dialog._title_edit.setFocus()
    app.processEvents()
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    assert dialog._try_nudge_from_key(ev, focus_widget=dialog._title_edit) is False
    assert int(item.data.get("x") or 0) == x0
    dialog.close()
