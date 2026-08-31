# -*- coding: utf-8 -*-
"""播放器全局设置：热键、绑定、列表/工作流顺序、定时、分辨率。"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app_core.hotkey_spec import display_hotkey, normalize_hotkey
from app_core.player.player_ui_state import extract_settings_from_ui
from ui.player.script_run_order import resolve_list_order


def _script_lists(ui: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    widgets = []
    for widget in (ui or {}).get("widgets") or []:
        if isinstance(widget, Mapping) and str(widget.get("type") or "") == "script_list":
            widgets.append(dict(widget))
    return widgets


class PlayerSettingsDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        ui: Optional[dict] = None,
        state: Optional[dict] = None,
        on_bind: Optional[Callable[[], None]] = None,
    ):
        super().__init__(parent)
        self.setObjectName("PlayerSettingsDialog")
        self.setWindowTitle("设置")
        self.setModal(True)
        self.resize(480, 420)
        self._ui = dict(ui or {})
        self._state = dict(state or {})
        self._on_bind = on_bind
        seed = extract_settings_from_ui(self._ui)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)
        hint = QLabel("选项保存在本机 userdata；随机顺序每次开始时重新洗牌。")
        hint.setWordWrap(True)
        root.addWidget(hint)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_general_tab(seed), "常规")
        tabs.addTab(self._build_bind_tab(), "绑定窗口")
        tabs.addTab(self._build_list_order_tab(), "脚本列表顺序")
        tabs.addTab(self._build_item_order_tab(), "工作流顺序")
        tabs.addTab(self._build_schedule_tab(), "定时")
        tabs.addTab(self._build_size_tab(), "窗口分辨率")
        root.addWidget(tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_general_tab(self, seed: dict) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)
        form.setSpacing(8)
        self._start_hotkey = QLineEdit(display_hotkey(seed.get("start_hotkey")))
        self._stop_hotkey = QLineEdit(display_hotkey(seed.get("stop_hotkey")))
        self._pause_hotkey = QLineEdit(display_hotkey(seed.get("pause_hotkey")))
        for edit, tip in (
            (self._start_hotkey, "开始任务热键"),
            (self._stop_hotkey, "停止任务热键"),
            (self._pause_hotkey, "暂停/继续热键"),
        ):
            edit.setPlaceholderText("例如 F6")
            edit.setToolTip(tip)
        form.addRow("开始热键", self._start_hotkey)
        form.addRow("停止热键", self._stop_hotkey)
        form.addRow("暂停热键", self._pause_hotkey)
        self._auto_start = QCheckBox("打开后自动执行")
        self._auto_start.setChecked(bool(seed.get("auto_start")))
        self._exit_on_finish = QCheckBox("结束后退出程序")
        self._exit_on_finish.setChecked(bool(seed.get("exit_on_finish")))
        self._notify_on_finish = QCheckBox("完成后系统/托盘通知")
        self._notify_on_finish.setChecked(bool(seed.get("notify_on_finish", True)))
        form.addRow("", self._auto_start)
        form.addRow("", self._exit_on_finish)
        form.addRow("", self._notify_on_finish)
        return page

    def _build_bind_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("绑定目标窗口后，脚本将在该窗口内执行。"))
        btn = QPushButton("绑定窗口…")
        btn.clicked.connect(self._do_bind)
        layout.addWidget(btn)
        layout.addStretch(1)
        return page

    def _do_bind(self):
        if callable(self._on_bind):
            self._on_bind()

    def _build_list_order_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        row.addWidget(QLabel("列表间顺序"))
        self._list_mode = QComboBox()
        self._list_mode.addItem("固定顺序", "fixed")
        self._list_mode.addItem("随机", "random")
        mode = str(self._state.get("list_order_mode") or self._ui.get("list_order_mode") or "fixed")
        idx = self._list_mode.findData(mode if mode in ("fixed", "random") else "fixed")
        if idx >= 0:
            self._list_mode.setCurrentIndex(idx)
        row.addWidget(self._list_mode, 1)
        layout.addLayout(row)
        self._list_order = QListWidget()
        titles = {
            str(w.get("id") or ""): str(w.get("title") or w.get("id") or "脚本列表")
            for w in _script_lists(self._ui)
        }
        for lid in resolve_list_order(self._ui, self._state):
            if not lid or lid.startswith("__anon_"):
                continue
            item = QListWidgetItem(titles.get(lid, lid))
            item.setData(Qt.ItemDataRole.UserRole, lid)
            self._list_order.addItem(item)
        layout.addWidget(self._list_order, 1)
        btns = QHBoxLayout()
        up = QPushButton("上移")
        down = QPushButton("下移")
        up.clicked.connect(lambda: self._move_row(self._list_order, -1))
        down.clicked.connect(lambda: self._move_row(self._list_order, 1))
        btns.addWidget(up)
        btns.addWidget(down)
        layout.addLayout(btns)
        return page

    def _build_item_order_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        self._item_list_pick = QComboBox()
        for widget in _script_lists(self._ui):
            lid = str(widget.get("id") or "").strip()
            if not lid:
                continue
            self._item_list_pick.addItem(str(widget.get("title") or lid), lid)
        self._item_list_pick.currentIndexChanged.connect(self._reload_item_order_list)
        layout.addWidget(self._item_list_pick)
        row = QHBoxLayout()
        row.addWidget(QLabel("该列表内顺序"))
        self._item_mode = QComboBox()
        self._item_mode.addItem("固定顺序", "fixed")
        self._item_mode.addItem("随机", "random")
        row.addWidget(self._item_mode, 1)
        layout.addLayout(row)
        self._item_order = QListWidget()
        layout.addWidget(self._item_order, 1)
        btns = QHBoxLayout()
        up = QPushButton("上移")
        down = QPushButton("下移")
        up.clicked.connect(lambda: self._move_row(self._item_order, -1))
        down.clicked.connect(lambda: self._move_row(self._item_order, 1))
        btns.addWidget(up)
        btns.addWidget(down)
        layout.addLayout(btns)
        self._item_modes_cache: Dict[str, str] = dict(self._state.get("list_order_modes") or {})
        self._item_orders_cache: Dict[str, List[str]] = {
            str(k): list(v)
            for k, v in dict(self._state.get("list_item_order") or {}).items()
            if isinstance(v, list)
        }
        self._reload_item_order_list()
        return page

    def _reload_item_order_list(self):
        if not hasattr(self, "_item_order"):
            return
        # persist previous
        prev_id = getattr(self, "_item_current_list_id", "")
        if prev_id:
            self._item_modes_cache[prev_id] = str(self._item_mode.currentData() or "fixed")
            self._item_orders_cache[prev_id] = [
                str(self._item_order.item(i).data(Qt.ItemDataRole.UserRole) or "")
                for i in range(self._item_order.count())
                if self._item_order.item(i) is not None
            ]
        lid = str(self._item_list_pick.currentData() or "").strip()
        self._item_current_list_id = lid
        widget = next((w for w in _script_lists(self._ui) if str(w.get("id") or "") == lid), {})
        mode = self._item_modes_cache.get(lid) or widget.get("order_mode") or "fixed"
        idx = self._item_mode.findData(mode if mode in ("fixed", "random") else "fixed")
        if idx >= 0:
            self._item_mode.setCurrentIndex(idx)
        preferred = self._item_orders_cache.get(lid) or [
            str(item.get("id") or "")
            for item in (widget.get("items") or [])
            if isinstance(item, Mapping) and item.get("id")
        ]
        titles = {
            str(item.get("id") or ""): str(item.get("title") or item.get("id") or "")
            for item in (widget.get("items") or [])
            if isinstance(item, Mapping)
        }
        self._item_order.clear()
        seen = set()
        for sid in preferred:
            if not sid or sid in seen or sid not in titles:
                continue
            seen.add(sid)
            row = QListWidgetItem(titles[sid])
            row.setData(Qt.ItemDataRole.UserRole, sid)
            self._item_order.addItem(row)
        for sid, title in titles.items():
            if sid in seen:
                continue
            row = QListWidgetItem(title)
            row.setData(Qt.ItemDataRole.UserRole, sid)
            self._item_order.addItem(row)

    def _build_schedule_tab(self) -> QWidget:
        from ui.player.schedule_alarms_editor import ScheduleAlarmsEditor

        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("与运行界面「定时执行」面板共用同一套编辑器；保存后两边同步。"))
        alarms = self._state.get("schedule_alarms")
        if not isinstance(alarms, list):
            alarms = None
            for widget in (self._ui.get("widgets") or []):
                if isinstance(widget, dict) and widget.get("type") == "schedule":
                    alarms = widget.get("alarms") or []
                    break
        self._schedule_editor = ScheduleAlarmsEditor(
            page,
            alarms=alarms,
            title="定时（到点自动开始）",
            interactive=True,
        )
        layout.addWidget(self._schedule_editor)
        layout.addStretch(1)
        return page

    def _build_size_tab(self) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)
        window = self._ui.get("window") if isinstance(self._ui.get("window"), dict) else {}
        w = int(self._state.get("window_width") or window.get("width") or 480)
        h = int(self._state.get("window_height") or window.get("height") or 360)
        self._width = QSpinBox()
        self._width.setRange(240, 3840)
        self._width.setValue(max(240, w))
        self._height = QSpinBox()
        self._height.setRange(180, 2160)
        self._height.setValue(max(180, h))
        form.addRow("宽度", self._width)
        form.addRow("高度", self._height)
        return page

    def _move_row(self, list_w: QListWidget, delta: int):
        row = list_w.currentRow()
        if row < 0:
            return
        target = row + int(delta)
        if target < 0 or target >= list_w.count():
            return
        item = list_w.takeItem(row)
        list_w.insertItem(target, item)
        list_w.setCurrentRow(target)

    def settings_payload(self) -> Dict[str, Any]:
        def _hotkey(edit: QLineEdit) -> str:
            spec = normalize_hotkey(edit.text())
            return spec or str(edit.text() or "").strip()

        return {
            "start_hotkey": _hotkey(self._start_hotkey),
            "stop_hotkey": _hotkey(self._stop_hotkey),
            "pause_hotkey": _hotkey(self._pause_hotkey),
            "auto_start": self._auto_start.isChecked(),
            "exit_on_finish": self._exit_on_finish.isChecked(),
            "notify_on_finish": self._notify_on_finish.isChecked(),
        }

    def result_state(self) -> Dict[str, Any]:
        self._reload_item_order_list()  # flush current item list into cache
        list_order = [
            str(self._list_order.item(i).data(Qt.ItemDataRole.UserRole) or "")
            for i in range(self._list_order.count())
            if self._list_order.item(i) is not None
        ]
        alarms = []
        if hasattr(self, "_schedule_editor") and self._schedule_editor is not None:
            alarms = self._schedule_editor.alarms()
        return {
            "list_order": [x for x in list_order if x],
            "list_order_mode": str(self._list_mode.currentData() or "fixed"),
            "list_item_order": dict(self._item_orders_cache),
            "list_order_modes": dict(self._item_modes_cache),
            "window_width": int(self._width.value()),
            "window_height": int(self._height.value()),
            "schedule_alarms": alarms,
        }
