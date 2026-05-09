import os
from typing import Optional


class MainWindowStatusMixin:
    def _update_main_window_title(self):

        """Updates the main window title to include the target window and unsaved status."""

        base_title = "自动化工作流"

        # 根据实际窗口数量显示不同的目标信息

        if hasattr(self, 'bound_windows') and self.bound_windows:

            enabled_count = sum(1 for w in self.bound_windows if w.get('enabled', True))

            total_count = len(self.bound_windows)

            # 只有当窗口数量 > 1 时才显示"多窗口"

            if total_count > 1:

                target_info = f" [多窗口: {enabled_count}/{total_count}]"

                # 更新 current_target_window_title 为第一个启用窗口的标题

                enabled_windows = [w for w in self.bound_windows if w.get('enabled', True)]

                if enabled_windows:

                    self.current_target_window_title = enabled_windows[0].get('title')

                else:

                    self.current_target_window_title = None

            else:

                # 单窗口模式：显示窗口标题

                enabled_windows = [w for w in self.bound_windows if w.get('enabled', True)]

                if enabled_windows:

                    self.current_target_window_title = enabled_windows[0].get('title')

                else:

                    self.current_target_window_title = None

                target_info = f" [目标: {self.current_target_window_title}]" if self.current_target_window_title else " [未绑定窗口]"

        else:

            # 没有绑定窗口

            target_info = " [未绑定窗口]"

            self.current_target_window_title = None

        file_info = f" - {os.path.basename(self.current_save_path)}" if self.current_save_path else ""

        # --- ADDED: Unsaved changes indicator ---

        unsaved_indicator = " (*)" if self.unsaved_changes and self.current_save_path else ""

        # ----------------------------------------

        full_title = base_title + target_info + file_info + unsaved_indicator # Add indicator

        # 使用统一的setWindowTitle方法，会自动处理长度限制

        self.setWindowTitle(full_title)

    def _set_step_detail_style(self, text_color: Optional[str] = None):

        """

        设置底部状态栏样式，根据当前主题动态调整

        Args:

            text_color: 文本颜色（可选），如果不指定则使用主题的默认文本颜色

        """

        if not hasattr(self, 'step_detail_label'):

            return

        # 获取主题颜色

        from .main_window_support import get_theme_color, is_dark_theme

        if text_color is None:

            text_color = get_theme_color('text', '#e0e0e0' if is_dark_theme() else '#333333')

        # 根据主题设置背景色

        if is_dark_theme():

            bg_color = get_theme_color('surface', '#2d2d2d')

        else:

            bg_color = 'rgba(180, 180, 180, 180)'

        style_cache_key = (text_color, bg_color)

        if getattr(self, "_step_detail_style_cache_key", None) == style_cache_key:

            return

        self._step_detail_style_cache_key = style_cache_key

        # 设置样式

        self.step_detail_label.setStyleSheet(f"""

            #stepDetailLabel {{

                background-color: {bg_color};

                color: {text_color};

                padding: 8px;

                border-radius: 5px;

                font-size: 9pt;

                border: none;

                font-weight: bold;

            }}

        """)

    def _position_qq_link_label(self):

        """将官网链接在状态栏内垂直居中定位"""

        if not hasattr(self, 'step_detail_label'):

            return

        if not self.step_detail_label:

            return

        try:

            content_rect = self.step_detail_label.contentsRect()

            step_fm = self.step_detail_label.fontMetrics()

            baseline = content_rect.center().y() + step_fm.ascent() - (step_fm.height() / 2.0)

            if hasattr(self, 'qq_link_label') and self.qq_link_label:

                self.qq_link_label.adjustSize()

                qq_fm = self.qq_link_label.fontMetrics()

                qq_y = int(round(baseline - qq_fm.ascent()))

                qq_y_min = content_rect.y()

                qq_y_max = content_rect.y() + max(0, content_rect.height() - self.qq_link_label.height())

                if qq_y < qq_y_min:

                    qq_y = qq_y_min

                elif qq_y > qq_y_max:

                    qq_y = qq_y_max

                qq_x = content_rect.x() + 10

                qq_max_x = content_rect.right() - self.qq_link_label.width()

                if qq_x > qq_max_x:

                    qq_x = max(content_rect.x(), qq_max_x)

                self.qq_link_label.move(qq_x, qq_y)

        except Exception:

            pass

    def update_status_bar_for_selection(self):

        """Updates the bottom status label to show only the selected card's title."""

        from ..workflow_parts.task_card import TaskCard

        active_workflow_view = getattr(self, "workflow_view", None)

        active_scene = getattr(active_workflow_view, "scene", None) if active_workflow_view else None

        if active_scene is None:

            current_text = self.step_detail_label.text()

            if "执行成功" not in current_text and "执行失败" not in current_text and "已停止" not in current_text and "错误" not in current_text:

                self.step_detail_label.setText("等待执行...")

            return

        sender = self.sender()

        sender_scene = sender if hasattr(sender, "selectedItems") else None

        # 忽略已关闭或非当前工作流画布发出的迟到信号，避免状态栏被旧场景污染

        if sender_scene is not None and sender_scene is not active_scene:

            return

        try:

            selected_items = active_scene.selectedItems()

        except Exception:

            return

        

        if len(selected_items) == 1 and isinstance(selected_items[0], TaskCard):

            card = selected_items[0]

            final_text = f"选中: {card.title}"

            self.step_detail_label.setText(final_text)

            self.step_detail_label.setToolTip("") # Clear tooltip from status bar

        else:

            # Resetting logic remains the same

            current_text = self.step_detail_label.text()

            if "执行成功" not in current_text and "执行失败" not in current_text and "已停止" not in current_text and "错误" not in current_text:

                 self.step_detail_label.setText("等待执行...")

    def _flush_pending_step_details(self):

        pending_text = getattr(self, "_pending_step_details", None)

        self._pending_step_details = None

        if not pending_text:

            return

        if self._is_stale_executor_signal():

            return

        self._apply_step_detail_text(pending_text)

        self._record_ntfy_execution_detail(pending_text)

    def _get_step_detail_text_color(self, step_details: str) -> str:

        from .main_window_support import get_theme_color, is_dark_theme, get_info_color, get_error_color

        text_color = get_theme_color('text', '#e0e0e0' if is_dark_theme() else '#333333')

        if "执行成功" in step_details:

            text_color = get_info_color()

        elif "执行失败" in step_details:

            text_color = get_error_color()

        elif "已停止" in step_details:

            text_color = get_info_color()

        return text_color

    def _apply_step_detail_text(self, step_details: str):

        import time

        if not hasattr(self, 'step_detail_label'):

            return

        last_text = getattr(self, "_step_detail_last_text", None)

        if last_text == step_details:

            self._step_detail_last_update_ts = time.monotonic()

            return

        self.step_detail_label.setText(step_details)

        self._set_step_detail_style(text_color=self._get_step_detail_text_color(step_details))

        self._position_qq_link_label()

        self._step_detail_last_text = step_details

        self._step_detail_last_update_ts = time.monotonic()

    def eventFilter(self, obj, event):

        from PySide6.QtCore import QEvent, QTimer

        if obj is getattr(self, 'step_detail_label', None):

            if event.type() in (

                QEvent.Type.Resize,

                QEvent.Type.LayoutRequest,

                QEvent.Type.FontChange,

                QEvent.Type.StyleChange,

                QEvent.Type.Polish,

                QEvent.Type.Show,

            ):

                QTimer.singleShot(0, self._position_qq_link_label)

        return super().eventFilter(obj, event)

    def _update_status_bar(self):

        """更新底部状态栏显示任务状态信息"""

        if not hasattr(self, 'step_detail_label'):

            return

        # 【关键修复】如果正在执行，不要覆盖详细步骤信息

        # 使用 _execution_started_flag 标志判断（比检查executor更可靠）

        if getattr(self, '_execution_started_flag', False):

            # 正在执行，跳过状态栏更新，保留详细步骤信息

            return

        # 非执行状态时，显示简单的等待提示

        status_text = "等待执行..."

        # 更新状态栏文本（样式由全局主题管理）

        self.step_detail_label.setText(status_text)
