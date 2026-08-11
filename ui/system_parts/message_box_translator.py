# -*- coding: utf-8 -*-
"""消息框翻译模块 - 确保所有对话框按钮都显示中文"""

import logging
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QMessageBox, QDialogButtonBox, QDialog, QWidget
from PySide6.QtCore import QObject, QEvent, Qt, QTimer

logger = logging.getLogger(__name__)

class MessageBoxTranslator(QObject):
    """消息框翻译器，自动将英文按钮翻译为中文"""

    def __init__(self):
        super().__init__()
        self.button_translations = {
            # QMessageBox 标准按钮翻译
            "OK": "确定",
            "Ok": "确定",
            "Cancel": "取消",
            "Yes": "是",
            "No": "否",
            "Close": "关闭",
            "Apply": "应用",
            "Reset": "重置",
            "Help": "帮助",
            "Save": "保存",
            "Discard": "丢弃",
            "Don't Save": "不保存",
            "Retry": "重试",
            "Ignore": "忽略",
            "Abort": "中止",
            "Open": "打开",
            "Save All": "全部保存",
            "Yes to All": "全部是",
            "No to All": "全部否",
            "Restore Defaults": "恢复默认",

            # 常见对话框按钮翻译
            "Browse": "浏览",
            "Select": "选择",
            "Accept": "接受",
            "Reject": "拒绝",
            "Continue": "继续",
            "Stop": "停止",
            "Start": "开始",
            "Finish": "完成",
            "Next": "下一步",
            "Previous": "上一步",
            "Back": "返回",
            "Forward": "前进",
            "Details": "详情",
            "Show Details": "显示详情",
            "Hide Details": "隐藏详情",
        }

    def eventFilter(self, obj, event):
        """事件过滤器，拦截并翻译按钮文本"""
        try:
            # 验证参数类型，防止TypeError崩溃
            from PySide6.QtCore import QObject, QEvent

            # 如果参数类型不正确，直接返回False
            if not isinstance(obj, QObject):
                logger.warning(f"eventFilter收到非QObject对象: {type(obj).__name__}")
                return False

            if not isinstance(event, QEvent):
                logger.warning(f"eventFilter收到非QEvent事件: {type(event).__name__}")
                return False

            # 参数类型正确，执行翻译逻辑
            if event.type() == QEvent.Type.Show:
                self.translate_widget_buttons(obj)

            return super().eventFilter(obj, event)

        except Exception as e:
            # 捕获所有异常，防止崩溃
            logger.error(f"eventFilter异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def translate_widget_buttons(self, widget):
        """翻译小部件中的所有按钮"""
        try:
            # 处理 QMessageBox
            if isinstance(widget, QMessageBox):
                self.translate_message_box(widget)

            # 处理包含 QDialogButtonBox 的对话框
            button_boxes = widget.findChildren(QDialogButtonBox)
            for button_box in button_boxes:
                self.translate_button_box(button_box)

            # 处理所有 QPushButton
            from PySide6.QtWidgets import QPushButton
            buttons = widget.findChildren(QPushButton)
            for button in buttons:
                self.translate_button(button)

        except Exception as e:
            # 静默处理翻译错误，避免影响正常功能
            pass

    def translate_message_box(self, message_box):
        """翻译 QMessageBox 的按钮"""
        try:
            # 获取所有标准按钮
            standard_buttons = message_box.standardButtons()

            # 翻译每个标准按钮
            button_map = {
                QMessageBox.StandardButton.Ok: "确定",
                QMessageBox.StandardButton.Cancel: "取消",
                QMessageBox.StandardButton.Yes: "是",
                QMessageBox.StandardButton.No: "否",
                QMessageBox.StandardButton.Close: "关闭",
                QMessageBox.StandardButton.Apply: "应用",
                QMessageBox.StandardButton.Reset: "重置",
                QMessageBox.StandardButton.Help: "帮助",
                QMessageBox.StandardButton.Save: "保存",
                QMessageBox.StandardButton.Discard: "丢弃",
                QMessageBox.StandardButton.Retry: "重试",
                QMessageBox.StandardButton.Ignore: "忽略",
                QMessageBox.StandardButton.Abort: "中止",
                QMessageBox.StandardButton.Open: "打开",
                QMessageBox.StandardButton.SaveAll: "全部保存",
                QMessageBox.StandardButton.YesToAll: "全部是",
                QMessageBox.StandardButton.NoToAll: "全部否",
                QMessageBox.StandardButton.RestoreDefaults: "恢复默认",
            }

            for std_button, chinese_text in button_map.items():
                if standard_buttons & std_button:
                    button = message_box.button(std_button)
                    if button:
                        button.setText(chinese_text)

        except Exception as e:
            pass

    def translate_button_box(self, button_box):
        """翻译 QDialogButtonBox 的按钮"""
        try:
            button_map = {
                QDialogButtonBox.StandardButton.Ok: "确定",
                QDialogButtonBox.StandardButton.Cancel: "取消",
                QDialogButtonBox.StandardButton.Yes: "是",
                QDialogButtonBox.StandardButton.No: "否",
                QDialogButtonBox.StandardButton.Close: "关闭",
                QDialogButtonBox.StandardButton.Apply: "应用",
                QDialogButtonBox.StandardButton.Reset: "重置",
                QDialogButtonBox.StandardButton.Help: "帮助",
                QDialogButtonBox.StandardButton.Save: "保存",
                QDialogButtonBox.StandardButton.Discard: "丢弃",
                QDialogButtonBox.StandardButton.Retry: "重试",
                QDialogButtonBox.StandardButton.Ignore: "忽略",
                QDialogButtonBox.StandardButton.Abort: "中止",
                QDialogButtonBox.StandardButton.Open: "打开",
                QDialogButtonBox.StandardButton.SaveAll: "全部保存",
                QDialogButtonBox.StandardButton.YesToAll: "全部是",
                QDialogButtonBox.StandardButton.NoToAll: "全部否",
                QDialogButtonBox.StandardButton.RestoreDefaults: "恢复默认",
            }

            for std_button, chinese_text in button_map.items():
                button = button_box.button(std_button)
                if button:
                    button.setText(chinese_text)

        except Exception as e:
            pass

    def translate_button(self, button):
        """翻译单个按钮"""
        try:
            current_text = button.text().strip()
            if current_text in self.button_translations:
                button.setText(self.button_translations[current_text])
        except Exception as e:
            pass

# 全局翻译器实例
class GlobalDialogScreenFixer(QObject):
    """Keep dialogs on the same screen as the triggering window."""

    def __init__(self):
        super().__init__()
        self._last_window = None
        self._last_non_dialog_window = None

    def eventFilter(self, obj, event):
        try:
            if not isinstance(obj, QObject) or not isinstance(event, QEvent):
                return False

            event_type = event.type()
            if event_type == QEvent.Type.WindowActivate:
                self._remember_window(obj)
            elif event_type in (QEvent.Type.Show, QEvent.Type.ShowToParent):
                self._schedule_fix(obj)

            return False
        except Exception:
            return False

    def _remember_window(self, obj):
        if not isinstance(obj, QWidget):
            return

        try:
            window = obj.window()
        except Exception:
            window = None

        if not isinstance(window, QWidget) or not window.isWindow():
            return

        self._last_window = window
        if not isinstance(window, QDialog):
            self._last_non_dialog_window = window

    def _schedule_fix(self, obj):
        if not isinstance(obj, QWidget):
            return

        try:
            dialog = obj.window()
        except Exception:
            dialog = obj

        if not self._should_fix(dialog):
            return

        try:
            if dialog.property("_lca_global_dialog_fix_pending"):
                return
            dialog.setProperty("_lca_global_dialog_fix_pending", True)
        except Exception:
            return

        def _first_pass():
            self._apply_fix(dialog)

        def _second_pass():
            try:
                self._apply_fix(dialog)
            finally:
                try:
                    dialog.setProperty("_lca_global_dialog_fix_pending", False)
                except Exception:
                    pass

        QTimer.singleShot(0, _first_pass)
        QTimer.singleShot(40, _second_pass)

    def _should_fix(self, dialog):
        if not isinstance(dialog, QDialog):
            return False
        if not dialog.isWindow():
            return False

        try:
            if bool(dialog.property("_lca_screen_fix_disabled")):
                return False
        except Exception:
            pass

        try:
            flags = dialog.windowFlags()
            if flags & Qt.WindowType.Popup:
                return False
            if flags & Qt.WindowType.ToolTip:
                return False
        except Exception:
            pass

        try:
            if dialog.isFullScreen():
                return False
        except Exception:
            pass

        return True

    def _resolve_reference_widget(self, dialog):
        candidates = []

        try:
            parent = dialog.parentWidget()
            if parent is not None:
                candidates.append(parent.window() if hasattr(parent, "window") else parent)
        except Exception:
            pass

        app = QApplication.instance()
        if app is not None:
            try:
                focus_widget = app.focusWidget()
                if focus_widget is not None:
                    candidates.append(focus_widget.window())
            except Exception:
                pass

            try:
                active_window = app.activeWindow()
                if active_window is not None and active_window is not dialog:
                    candidates.append(active_window.window() if hasattr(active_window, "window") else active_window)
            except Exception:
                pass

        candidates.extend([self._last_non_dialog_window, self._last_window])

        seen = set()
        for candidate in candidates:
            if not isinstance(candidate, QWidget):
                continue
            if candidate is dialog:
                continue

            marker = id(candidate)
            if marker in seen:
                continue
            seen.add(marker)
            return candidate

        return None

    def _apply_fix(self, dialog):
        if not self._should_fix(dialog):
            return

        try:
            from utils.window_coordinate_common import center_window_on_widget_screen
        except Exception:
            return

        reference_widget = self._resolve_reference_widget(dialog)
        center_window_on_widget_screen(dialog, reference_widget)


_message_box_translator = None
_dialog_screen_fixer = None
def setup_message_box_translations():

    """设置消息框翻译"""
    global _message_box_translator, _dialog_screen_fixer

    try:
        app = QApplication.instance()
        if app:
            if not _message_box_translator:
                _message_box_translator = MessageBoxTranslator()
                app.installEventFilter(_message_box_translator)

            if not _dialog_screen_fixer:
                _dialog_screen_fixer = GlobalDialogScreenFixer()
                app.installEventFilter(_dialog_screen_fixer)

            # 设置应用程序级别的按钮文本翻译
            app.setProperty("chinese_buttons", True)

    except Exception as e:
        # 静默处理设置错误
        pass


def _resolve_message_box_reference_widget(parent=None, reference_widget=None):
    candidates = []

    if isinstance(reference_widget, QWidget):
        candidates.append(reference_widget.window() if hasattr(reference_widget, "window") else reference_widget)

    if isinstance(parent, QWidget):
        candidates.append(parent.window() if hasattr(parent, "window") else parent)

    app = QApplication.instance()
    if app is not None:
        try:
            active_window = app.activeWindow()
            if isinstance(active_window, QWidget):
                candidates.append(active_window.window() if hasattr(active_window, "window") else active_window)
        except Exception:
            pass

        try:
            focus_widget = app.focusWidget()
            if isinstance(focus_widget, QWidget):
                candidates.append(focus_widget.window() if hasattr(focus_widget, "window") else focus_widget)
        except Exception:
            pass

    seen = set()
    for candidate in candidates:
        if not isinstance(candidate, QWidget):
            continue
        marker = id(candidate)
        if marker in seen:
            continue
        seen.add(marker)
        return candidate

    return None


def place_dialog_on_screen(dialog, parent=None, reference_widget=None, global_pos=None):
    if not isinstance(dialog, QWidget):
        return False

    if global_pos is None:
        try:
            global_pos = QCursor.pos()
        except Exception:
            global_pos = None

    try:
        from utils.window_coordinate_common import center_window_on_widget_screen
    except Exception:
        return False

    resolved_reference = _resolve_message_box_reference_widget(
        parent=parent,
        reference_widget=reference_widget,
    )
    return center_window_on_widget_screen(dialog, resolved_reference, global_pos)


def show_message_box(
    parent,
    title,
    text,
    *,
    icon=QMessageBox.Icon.NoIcon,
    buttons=QMessageBox.StandardButton.Ok,
    default_button=None,
    informative_text=None,
    detailed_text=None,
    window_flags=None,
    reference_widget=None,
):
    msg_parent = parent if isinstance(parent, QWidget) else None
    msg_box = QMessageBox(msg_parent)
    msg_box.setWindowTitle(title)
    msg_box.setText(text)
    msg_box.setIcon(icon)
    msg_box.setStandardButtons(buttons)

    if default_button is not None:
        try:
            msg_box.setDefaultButton(default_button)
        except Exception:
            pass

    if informative_text:
        msg_box.setInformativeText(informative_text)

    if detailed_text:
        msg_box.setDetailedText(detailed_text)

    if window_flags is not None:
        msg_box.setWindowFlags(window_flags)

    place_dialog_on_screen(msg_box, parent=msg_parent, reference_widget=reference_widget)
    return msg_box.exec()


def show_question_box(parent, title, text, buttons=None, default_button=None, reference_widget=None):
    """显示中文问题对话框"""
    if buttons is None:
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No

    if default_button is None:
        default_button = QMessageBox.StandardButton.No

    return show_message_box(
        parent,
        title,
        text,
        icon=QMessageBox.Icon.Question,
        buttons=buttons,
        default_button=default_button,
        reference_widget=reference_widget,
    )


def show_information_box(parent, title, text, reference_widget=None):
    """显示中文信息对话框"""
    return show_message_box(
        parent,
        title,
        text,
        icon=QMessageBox.Icon.Information,
        buttons=QMessageBox.StandardButton.Ok,
        reference_widget=reference_widget,
    )


def show_warning_box(parent, title, text, buttons=QMessageBox.StandardButton.Ok, default_button=None, reference_widget=None):
    return show_message_box(
        parent,
        title,
        text,
        icon=QMessageBox.Icon.Warning,
        buttons=buttons,
        default_button=default_button,
        reference_widget=reference_widget,
    )


def show_critical_box(parent, title, text, buttons=QMessageBox.StandardButton.Ok, default_button=None, reference_widget=None):
    return show_message_box(
        parent,
        title,
        text,
        icon=QMessageBox.Icon.Critical,
        buttons=buttons,
        default_button=default_button,
        reference_widget=reference_widget,
    )

