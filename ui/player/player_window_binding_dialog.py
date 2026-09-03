# -*- coding: utf-8 -*-
"""独立程序窗口绑定对话框：点选绑定 / 移除，写入 userdata 配置。"""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app_core.config_store import save_config
from app_core.player.window_resolution import (
    adjust_window_to_required_client_size,
    ensure_bound_windows_resolution,
    format_size,
    get_window_client_size,
    normalize_required_client_size,
)
from utils.window.hwnd_utils import as_hwnd, get_window_text
from utils.window.window_activation_utils import (
    schedule_overlay_activation_boost,
    show_and_activate_overlay,
    show_and_raise_widget,
)
from utils.window.window_identity import apply_window_identity, is_window_alive, refresh_bound_windows

logger = logging.getLogger(__name__)


def _display_title(window_info: dict) -> str:
    title = str(window_info.get("title") or "").strip() or "未命名窗口"
    hwnd = as_hwnd(window_info.get("hwnd"))
    alive = is_window_alive(hwnd) if hwnd else False
    mark = "在线" if alive else "离线"
    if hwnd:
        return f"{title}  [{mark}]  HWND={hwnd}"
    return f"{title}  [{mark}]"


class PlayerWindowBindingDialog(QDialog):
    """精简绑定界面：列表 + 点选绑定 + 移除。"""

    def __init__(
        self,
        config: dict,
        *,
        host_window=None,
        on_saved: Optional[Callable[[dict], None]] = None,
        persist_config: bool = True,
        required_client_width: int = 0,
        required_client_height: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("绑定窗口")
        self.setModal(True)
        self.resize(480, 360)
        self._config = dict(config or {})
        self._host_window = host_window
        self._on_saved = on_saved
        self._persist_config = bool(persist_config)
        self._required_size = normalize_required_client_size(
            required_client_width, required_client_height
        )
        self._bound_windows: List[dict] = [
            dict(item)
            for item in (self._config.get("bound_windows") or [])
            if isinstance(item, dict)
        ]
        self._picker = None
        self._picker_cleared_modal = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        hint_text = (
            "请绑定工作流要操作的目标窗口。\n"
            "点击「点选绑定」后，在屏幕上点击目标窗口即可。"
        )
        if self._required_size != (0, 0):
            hint_text += (
                f"\n本程序要求目标窗口客户区为 {format_size(self._required_size)}；"
                "绑定后会自动调整，失败则需手动调到该尺寸后再绑定。"
            )
        hint = QLabel(hint_text)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._list = QListWidget(self)
        layout.addWidget(self._list, 1)

        row = QHBoxLayout()
        self._pick_button = QPushButton("点选绑定")
        self._pick_button.clicked.connect(self._start_picker)
        self._remove_button = QPushButton("移除所选")
        self._remove_button.clicked.connect(self._remove_selected)
        self._refresh_button = QPushButton("刷新状态")
        self._refresh_button.clicked.connect(self._refresh_list)
        row.addWidget(self._pick_button)
        row.addWidget(self._remove_button)
        row.addWidget(self._refresh_button)
        row.addStretch(1)
        layout.addLayout(row)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        ok_button = QPushButton("确定")
        ok_button.setDefault(True)
        ok_button.clicked.connect(self.accept)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        bottom.addWidget(ok_button)
        bottom.addWidget(cancel_button)
        layout.addLayout(bottom)

        self._refresh_list()

    @property
    def bound_windows(self) -> List[dict]:
        return list(self._bound_windows)

    def _refresh_list(self) -> None:
        refresh_bound_windows(self._bound_windows)
        self._list.clear()
        for window_info in self._bound_windows:
            item = QListWidgetItem(self._display_window(window_info))
            item.setData(Qt.ItemDataRole.UserRole, window_info)
            self._list.addItem(item)
        self._remove_button.setEnabled(self._list.count() > 0)

    def _display_window(self, window_info: dict) -> str:
        text = _display_title(window_info)
        hwnd = as_hwnd(window_info.get("hwnd"))
        if self._required_size == (0, 0) or not hwnd or not is_window_alive(hwnd):
            return text
        actual = get_window_client_size(hwnd)
        if actual is None:
            return f"{text}  [无法读取尺寸]"
        if actual == self._required_size:
            return f"{text}  {format_size(actual)}"
        return f"{text}  {format_size(actual)} ≠ {format_size(self._required_size)}"

    def _reject_resolution(self, title: str, hwnd: Any) -> bool:
        """尺寸不符时先自动调整；仍失败则提示手动调整并拒绝本次绑定。"""
        if self._required_size == (0, 0):
            return False
        if not hwnd:
            QMessageBox.warning(self, "无法绑定", "无法读取该窗口，请重试。")
            return True
        ok, message = adjust_window_to_required_client_size(
            hwnd,
            self._required_size[0],
            self._required_size[1],
            title=title,
        )
        if ok:
            return False
        QMessageBox.warning(
            self,
            "分辨率调整失败",
            message
            or (
                f"无法将「{title}」调整为 {format_size(self._required_size)}。\n"
                "请手动调整窗口客户区后再绑定。"
            ),
        )
        return True

    def _is_already_bound(self, hwnd: int, title: str) -> bool:
        hwnd = as_hwnd(hwnd)
        title = str(title or "").strip()
        for window_info in self._bound_windows:
            if hwnd and as_hwnd(window_info.get("hwnd")) == hwnd:
                return True
            if title and str(window_info.get("title") or "").strip() == title and not hwnd:
                return True
        return False

    def _start_picker(self) -> None:
        try:
            from ui.selectors.window_picker import WindowPickerOverlay
        except Exception as exc:
            QMessageBox.critical(self, "无法启动", f"窗口选择工具不可用: {exc}")
            return

        host = self._host_window
        host_was_visible = bool(host.isVisible()) if host is not None else False
        self_was_visible = self.isVisible()
        self._picker_cleared_modal = False
        if self.isModal():
            self.setModal(False)
            self._picker_cleared_modal = True
        if host is not None:
            host.hide()
        self.hide()

        self._picker = WindowPickerOverlay(
            self,
            host,
            parent_was_visible=self_was_visible,
            main_window_was_visible=host_was_visible,
        )
        self._picker.window_selected.connect(self._on_window_picked)
        self._picker.picker_closed.connect(self._restore_after_picker)
        if show_and_activate_overlay(
            self._picker,
            log_prefix="独立程序窗口选择覆盖层",
            focus=True,
        ):
            schedule_overlay_activation_boost(
                self._picker,
                log_prefix="独立程序窗口选择覆盖层",
                intervals_ms=(50, 150, 300),
                focus=True,
            )

    def _on_window_picked(self, hwnd: Any, title: str) -> None:
        hwnd = as_hwnd(hwnd)
        safe_title = str(title or "").strip()
        if not safe_title and hwnd:
            safe_title = get_window_text(hwnd)
        if not safe_title:
            safe_title = f"窗口_{hwnd}" if hwnd else "未知窗口"

        if self._is_already_bound(hwnd, safe_title):
            QMessageBox.information(self, "提示", f"窗口已绑定：{safe_title}")
            self._restore_after_picker()
            return
        if self._reject_resolution(safe_title, hwnd):
            self._restore_after_picker()
            return

        window_info = {"title": safe_title, "enabled": True}
        if hwnd:
            apply_window_identity(window_info, hwnd)
        self._bound_windows.append(window_info)
        self._refresh_list()
        logger.info("独立程序已绑定窗口: %s hwnd=%s", safe_title, hwnd)
        self._restore_after_picker()
        self._probe_plugin_bind_for_window(window_info)

    def _probe_plugin_bind_for_window(self, window_info: dict) -> None:
        from ui.plugin_bind_probe import schedule_dialog_plugin_bind_probe

        schedule_dialog_plugin_bind_probe(
            self,
            (window_info or {}).get("hwnd"),
            self._config,
            window_info,
            (window_info or {}).get("title"),
        )

    def _restore_after_picker(self) -> None:
        if getattr(self, "_picker_cleared_modal", False):
            self.setModal(True)
            self._picker_cleared_modal = False
        show_and_activate_overlay(self, log_prefix="独立程序绑定对话框恢复", focus=True)
        host = self._host_window
        if host is not None:
            show_and_raise_widget(host, log_prefix="独立程序窗口恢复")

    def _remove_selected(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._bound_windows):
            QMessageBox.information(self, "提示", "请先选择要移除的窗口")
            return
        title = str(self._bound_windows[row].get("title") or "窗口")
        reply = QMessageBox.question(
            self,
            "确认移除",
            f"确定移除「{title}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._bound_windows.pop(row)
        self._refresh_list()

    def accept(self) -> None:
        refresh_bound_windows(self._bound_windows)
        if self._required_size != (0, 0):
            errors = ensure_bound_windows_resolution(
                self._bound_windows,
                self._required_size[0],
                self._required_size[1],
            )
            if errors:
                QMessageBox.warning(
                    self,
                    "分辨率调整失败",
                    "以下窗口未能自动调整到要求尺寸，请手动调整后再保存：\n\n"
                    + "\n".join(errors),
                )
                self._refresh_list()
                return
        mode = "multiple" if len(self._bound_windows) > 1 else "single"
        self._config["bound_windows"] = list(self._bound_windows)
        self._config["window_binding_mode"] = mode
        if mode == "single" and self._bound_windows:
            self._config["target_window_title"] = self._bound_windows[0].get("title")
        else:
            self._config["target_window_title"] = None
        if self._persist_config:
            try:
                save_config(self._config)
            except Exception as exc:
                logger.error("保存窗口绑定失败: %s", exc, exc_info=True)
                QMessageBox.critical(self, "保存失败", str(exc))
                return
        if callable(self._on_saved):
            try:
                self._on_saved(dict(self._config))
            except Exception:
                logger.debug("绑定保存回调失败", exc_info=True)
        super().accept()


def open_player_window_binding_dialog(
    host_window,
    config: dict,
    *,
    on_saved: Optional[Callable[[dict], None]] = None,
    persist_config: bool = True,
    required_client_width: int = 0,
    required_client_height: int = 0,
) -> Optional[dict]:
    dialog = PlayerWindowBindingDialog(
        config,
        host_window=host_window,
        on_saved=on_saved,
        persist_config=persist_config,
        required_client_width=required_client_width,
        required_client_height=required_client_height,
        parent=host_window,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.bound_windows
