import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QWidget,
)

from ui.player.player_chrome import (
    PLAYER_SHELL_RADIUS,
    SCRIPT_ITEM_LOOPS_ROLE,
    SCRIPT_ITEM_TITLE_ROLE,
    apply_player_rounded_window,
    apply_script_run_status,
    group_loops_from_refs,
    paint_player_background,
    player_fill_qss,
    player_window_surface_qss,
    populate_custom_player_body,
    resolve_player_background_color,
    resolve_widget_color,
    script_loops_from_refs,
    selected_script_ids_from_refs,
)


def _qapp():
    return QApplication.instance() or QApplication([])


def test_player_fill_qss_uses_shell_radius():
    qss = player_fill_qss("PlayerBg", "#112233")
    compact = qss.replace(" ", "")
    assert "#112233" in qss
    assert f"border-radius:{PLAYER_SHELL_RADIUS}px" in compact


def test_player_window_surface_qss_keeps_main_window_transparent():
    qss = player_window_surface_qss()
    compact = qss.replace(" ", "")
    assert "QMainWindow#PlayerWindow" in qss
    assert "background:transparent" in compact


def test_apply_player_rounded_window_disables_square_fill():
    _qapp()
    window = QMainWindow()
    window.setObjectName("PlayerWindow")
    apply_player_rounded_window(window)
    assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert window.autoFillBackground() is False
    window.close()


def test_paint_player_background_fill_is_rounded():
    _qapp()
    body = QWidget()
    body.resize(200, 120)
    fill = paint_player_background(body, {"mode": "color", "color": "#445566"}, load_pixmap=lambda _p: None)
    compact = fill.styleSheet().replace(" ", "")
    assert f"border-radius:{PLAYER_SHELL_RADIUS}px" in compact
    assert fill.autoFillBackground() is False
    body.deleteLater()


def test_player_button_style_locks_disabled_colors():
    """禁用态必须自带主题色，避免宿主浅色 QSS 把深色窗按钮刷白。"""
    from PySide6.QtWidgets import QPushButton

    from ui.player.player_chrome import apply_player_button_style

    _qapp()
    btn = QPushButton("暂停")
    apply_player_button_style(btn, {"type": "button", "action": "pause"})
    compact = btn.styleSheet().replace(" ", "").lower()
    assert "qpushbutton:disabled" in compact
    assert "background-color:" in compact
    btn.deleteLater()


def test_theme_default_background_and_text_follow_active_theme():
    """导出时烘焙的浅色默认 canvas/text，在深色主题下应跟随当前主题。"""
    from themes import get_theme_manager, theme_color

    _qapp()
    app = QApplication.instance()
    mgr = get_theme_manager()
    prev = mgr.get_theme_mode()
    try:
        mgr.apply_theme(app, "dark")
        dark_canvas = theme_color("canvas").lower()
        dark_text = theme_color("text").lower()
        assert resolve_player_background_color({"mode": "color", "color": "#fafafa"}).lower() == dark_canvas
        assert resolve_player_background_color({"mode": "color", "color": "#ffffff"}).lower() == dark_canvas
        assert resolve_player_background_color({"mode": "color", "color": "#00bcd4"}).lower() == "#00bcd4"
        assert resolve_widget_color({"color": "#333333"}, "color", "text").lower() == dark_text
        assert resolve_widget_color({"color": "#ff00aa"}, "color", "text").lower() == "#ff00aa"

        body = QWidget()
        body.resize(200, 120)
        fill = paint_player_background(
            body, {"mode": "color", "color": "#fafafa"}, load_pixmap=lambda _p: None
        )
        assert dark_canvas in fill.styleSheet().replace(" ", "").lower()
        body.deleteLater()
    finally:
        mgr.apply_theme(app, prev)


def test_script_row_once_check_and_clear():
    from PySide6.QtCore import Qt

    from ui.player.player_chrome import (
        PlayerScriptListView,
        PlayerScriptTaskRow,
        clear_once_script_checks,
        selected_script_ids_from_refs,
    )

    _qapp()
    list_w = PlayerScriptListView()
    row = PlayerScriptTaskRow("a", "日常", 1, checked=False, interactive=True, parent=list_w)
    item = QListWidgetItem()
    item.setData(Qt.ItemDataRole.UserRole, "a")
    item.setSizeHint(row.sizeHint())
    list_w.addItem(item)
    list_w.setItemWidget(item, row)
    refs = {"script_list_widget": list_w}
    assert selected_script_ids_from_refs(refs) == []
    row._check.setCheckState(Qt.CheckState.PartiallyChecked)
    assert row.is_once()
    assert selected_script_ids_from_refs(refs) == ["a"]
    clear_once_script_checks(refs)
    assert not row.is_once()
    assert selected_script_ids_from_refs(refs) == []
    list_w.deleteLater()


def test_script_list_view_move_row_keeps_item_widget():
    from PySide6.QtCore import Qt

    from ui.player.player_chrome import PlayerScriptListView, PlayerScriptTaskRow

    _qapp()
    list_w = PlayerScriptListView()
    rows = []
    for sid in ("a", "b", "c"):
        row = PlayerScriptTaskRow(sid, sid.upper(), 1, parent=list_w)
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, sid)
        item.setSizeHint(row.sizeHint())
        list_w.addItem(item)
        list_w.setItemWidget(item, row)
        rows.append(row)
    assert list_w.move_row(0, 2) is True
    assert [list_w.item(i).data(Qt.ItemDataRole.UserRole) for i in range(3)] == ["b", "a", "c"]
    assert list_w.itemWidget(list_w.item(1)) is rows[0]
    assert list_w.move_row(2, 0) is True
    assert [list_w.item(i).data(Qt.ItemDataRole.UserRole) for i in range(3)] == ["c", "b", "a"]
    list_w.deleteLater()


def test_populate_schedule_and_log_toolbar():
    from PySide6.QtWidgets import QFrame, QToolButton

    from ui.player.player_chrome import schedule_alarms_from_refs

    _qapp()
    body = QWidget()
    opened = {"n": 0}
    refs = populate_custom_player_body(
        body,
        {
            "window": {"width": 360, "height": 320},
            "widgets": [
                {
                    "type": "schedule",
                    "title": "定时",
                    "x": 8,
                    "y": 8,
                    "w": 220,
                    "h": 150,
                    "alarms": [{"enabled": True, "hour": 9, "minute": 30}],
                },
                {
                    "type": "log",
                    "x": 8,
                    "y": 170,
                    "w": 300,
                    "h": 120,
                },
            ],
        },
        load_pixmap=lambda _p: QPixmap(),
        on_open_log_dir=lambda: opened.__setitem__("n", opened["n"] + 1),
    )
    assert body.findChild(QFrame, "PlayerSchedule") is not None
    alarms = schedule_alarms_from_refs(refs)
    assert alarms[0]["enabled"] is True
    assert alarms[0]["hour"] == 9
    assert alarms[0]["minute"] == 30
    tools = body.findChildren(QToolButton)
    labels = {btn.text() for btn in tools}
    assert {"清空", "复制", "目录"}.issubset(labels)
    for btn in tools:
        if btn.text() == "目录":
            btn.click()
            break
    assert opened["n"] == 1
    body.deleteLater()


def test_populate_progress_and_settings_button():
    from PySide6.QtWidgets import QProgressBar, QPushButton

    from ui.player.player_chrome import set_progress_widget_state

    _qapp()
    body = QWidget()
    clicked = {"n": 0}
    refs = populate_custom_player_body(
        body,
        {
            "window": {"width": 320, "height": 200},
            "widgets": [
                {
                    "type": "progress",
                    "title": "进度",
                    "x": 8,
                    "y": 8,
                    "w": 280,
                    "h": 28,
                },
                {
                    "type": "button",
                    "action": "settings",
                    "text": "设置",
                    "x": 8,
                    "y": 70,
                    "w": 80,
                    "h": 32,
                },
            ],
        },
        load_pixmap=lambda _p: QPixmap(),
        on_settings=lambda: clicked.__setitem__("n", clicked["n"] + 1),
    )
    assert isinstance(refs["progress_bar"], QProgressBar)
    assert refs["progress_bar"] is refs["progress_frame"]
    assert body.findChild(QProgressBar, "PlayerProgressBar") is refs["progress_bar"]
    qss = refs["progress_bar"].styleSheet().replace(" ", "").lower()
    assert "qprogressbar#playerprogressbar{border:1pxsolid" in qss
    set_progress_widget_state(
        refs, text="执行中 · 日常 · 队列 1/2", value=1, maximum=2
    )
    assert "日常" in refs["progress_bar"].format()
    assert refs["progress_bar"].value() == 1
    btn = refs["settings_button"]
    assert isinstance(btn, QPushButton)
    btn.click()
    assert clicked["n"] == 1
    body.deleteLater()


def test_panel_widgets_have_no_card_chrome():
    """脚本列表/日志/定时/进度：外框无底色无描边，跟主题窗融合。"""
    from PySide6.QtWidgets import QFrame

    _qapp()
    body = QWidget()
    refs = populate_custom_player_body(
        body,
        {
            "window": {"width": 420, "height": 360},
            "widgets": [
                {
                    "type": "script_list",
                    "title": "脚本",
                    "x": 8,
                    "y": 8,
                    "w": 180,
                    "h": 160,
                    "bg_color": "#ff0000",
                    "items": [{"id": "a", "title": "日常", "checked": True, "loops": 1}],
                },
                {
                    "type": "log",
                    "x": 200,
                    "y": 8,
                    "w": 180,
                    "h": 160,
                    "bg_color": "#00ff00",
                },
                {
                    "type": "schedule",
                    "x": 8,
                    "y": 180,
                    "w": 180,
                    "h": 120,
                    "bg_color": "#0000ff",
                },
                {
                    "type": "progress",
                    "x": 200,
                    "y": 180,
                    "w": 180,
                    "h": 28,
                    "bg_color": "#ffff00",
                },
            ],
        },
        load_pixmap=lambda _p: QPixmap(),
    )
    for name in ("PlayerScriptList", "PlayerLogFrame", "PlayerSchedule"):
        frame = body.findChild(QFrame, name)
        assert frame is not None, name
        compact = frame.styleSheet().replace(" ", "").lower()
        assert f"qframe#{name.lower()}{{background:transparent;border:1pxsolid" in compact, name
        assert "#ff0000" not in compact and "#00ff00" not in compact
        assert "#0000ff" not in compact
    script_frame = body.findChild(QFrame, "PlayerScriptList")
    script_qss = script_frame.styleSheet().replace(" ", "").lower()
    assert "qspinbox{" in script_qss and "background:transparent" in script_qss
    assert "qlistwidget::viewport" in script_qss
    assert "qcheckbox::indicator{" in script_qss
    assert "background-color:#ff0000" not in script_qss
    # Unchecked indicator must not keep a solid canvas/white fill on custom backgrounds.
    assert "qcheckbox::indicator{width:16px;height:16px;border:1pxsolid" in script_qss
    assert "background:transparent" in script_qss.split("qcheckbox::indicator{")[1].split("}")[0]
    assert "qlistwidget::item:hover" in script_qss
    assert "margin:0px" in script_qss
    list_w = refs["script_list_widget"]
    assert list_w.selectionMode() == QAbstractItemView.SelectionMode.NoSelection

    log_frame = body.findChild(QFrame, "PlayerLogFrame")
    log_qss = log_frame.styleSheet().replace(" ", "").lower()
    assert "qtextedit::viewport" in log_qss or "qabstractscrollarea::viewport" in log_qss

    schedule_frame = body.findChild(QFrame, "PlayerSchedule")
    schedule_qss = schedule_frame.styleSheet().replace(" ", "").lower()
    assert "qtimeedit{" in schedule_qss and "background:transparent" in schedule_qss
    assert "qcheckbox::indicator{" in schedule_qss
    from PySide6.QtWidgets import QProgressBar

    progress = body.findChild(QProgressBar, "PlayerProgressBar")
    assert progress is not None
    progress_qss = progress.styleSheet().replace(" ", "").lower()
    assert "qprogressbar#playerprogressbar{border:1pxsolid" in progress_qss
    assert "#ffff00" not in progress_qss
    body.deleteLater()


def test_populate_script_list_has_inline_loops_like_maa():
    _qapp()
    body = QWidget()
    refs = populate_custom_player_body(
        body,
        {
            "window": {"width": 320, "height": 260},
            "widgets": [
                {
                    "type": "script_list",
                    "title": "脚本",
                    "x": 8,
                    "y": 8,
                    "w": 280,
                    "h": 200,
                    "group_loops": 2,
                    "items": [
                        {"id": "a", "title": "日常", "checked": True, "loops": 3},
                        {"id": "b", "title": "刷图", "checked": False, "loops": 1},
                    ],
                }
            ],
        },
        load_pixmap=lambda _p: QPixmap(),
    )
    assert refs["script_list_widget"] is not None
    assert refs["group_loop_spin"].value() == 2
    assert script_loops_from_refs(refs)["a"] == 3
    assert group_loops_from_refs(refs) == 2
    assert selected_script_ids_from_refs(refs) == ["a"]
    group_bar = body.findChild(QFrame, "PlayerGroupLoopBar")
    assert group_bar is not None
    group_qss = group_bar.parent().styleSheet().replace(" ", "").lower()
    assert "qframe#playergrouploopbar{background:transparent;border:none;}" in group_qss
    list_w = refs["script_list_widget"]
    row_a = list_w.itemWidget(list_w.item(0))
    row_a._spin.setValue(5)
    assert script_loops_from_refs(refs)["a"] == 5
    apply_script_run_status(
        refs,
        active_id="a",
        loop_index=2,
        loop_total=5,
        state="running",
        waiting_ids=[],
    )
    assert "执行中" in row_a._status.text()
    assert body.findChild(QWidget, "PlayerLoopSettings") is None
    body.deleteLater()


def test_apply_script_run_status_marks_active_item():
    _qapp()
    list_w = QListWidget()
    for sid, title, loops in (("a", "日常", 1), ("b", "刷图", 3)):
        item = QListWidgetItem(title)
        item.setData(Qt.ItemDataRole.UserRole, sid)
        item.setData(SCRIPT_ITEM_TITLE_ROLE, title)
        item.setData(SCRIPT_ITEM_LOOPS_ROLE, loops)
        list_w.addItem(item)
    apply_script_run_status(
        {"script_list_widget": list_w},
        active_id="b",
        loop_index=2,
        loop_total=3,
        state="running",
        waiting_ids=["a"],
    )
    assert "执行中 2/3" in list_w.item(1).text()
    assert "执行中" not in list_w.item(0).text()
    list_w.deleteLater()
