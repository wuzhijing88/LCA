# -*- coding: utf-8 -*-
"""消息框翻译模块 - 确保所有对话框按钮都显示中文"""

import logging
from dataclasses import dataclass
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QMessageBox, QDialogButtonBox, QDialog, QWidget
from PySide6.QtCore import QObject, QEvent, Qt, QTimer
from shiboken6 import isValid

from ui.dialogs.dialog_manager import exec_dialog

logger = logging.getLogger(__name__)

class _ApplicationEventFilter(QObject):
    """随应用退出摘除全局过滤器，直接销毁时也卸载关联资源。"""

    def __init__(self):
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("安装对话框过滤器前必须创建应用程序")
        super().__init__(app)
        self._application = app
        self._disposed = False
        self._quit_connection = app.aboutToQuit.connect(self.shutdown)
        self.destroyed.connect(lambda: self.shutdown())

    def shutdown(self):
        if self._disposed:
            return
        self._disposed = True
        self._release_resources()
        app, self._application = self._application, None
        if app is not None and isValid(app) and isValid(self):
            app.removeEventFilter(self)
        QObject.disconnect(self._quit_connection)

    def _release_resources(self):
        pass


class MessageBoxTranslator(_ApplicationEventFilter):
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
        if self._disposed or not isinstance(obj, QWidget) or not isValid(obj):
            return False
        try:
            if event.type() == QEvent.Type.Show:
                self.translate_widget_buttons(obj)
        except Exception:
            logger.exception("对话框按钮翻译失败")
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

        except Exception:
            logger.exception("窗口按钮翻译失败")

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

        except Exception:
            logger.exception("消息框按钮翻译失败")

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

        except Exception:
            logger.exception("对话框按钮组翻译失败")

    def translate_button(self, button):
        """翻译单个按钮"""
        try:
            current_text = button.text().strip()
            if current_text in self.button_translations:
                button.setText(self.button_translations[current_text])
        except Exception:
            logger.exception("按钮翻译失败")

# 全局翻译器实例
class GlobalDialogScreenFixer(_ApplicationEventFilter):
    """Keep dialogs on the same screen as the triggering window."""

    def __init__(self):
        super().__init__()
        self._last_window = None
        self._last_non_dialog_window = None
        self._pending_fixes = {}

    def eventFilter(self, obj, event):
        if self._disposed:
            return False
        try:
            if not isinstance(obj, QObject) or not isinstance(event, QEvent):
                return False

            event_type = event.type()
            if event_type == QEvent.Type.WindowActivate:
                self._remember_window(obj)
            elif event_type in (QEvent.Type.Show, QEvent.Type.ShowToParent):
                self._schedule_fix(obj)
            elif event_type == QEvent.Type.Hide and isinstance(obj, QDialog):
                self._cancel_fix(obj)

            return False
        except Exception:
            logger.exception("对话框屏幕定位失败")
            return False

    def _remember_window(self, obj):
        if not isinstance(obj, QWidget) or not isValid(obj):
            return

        window = obj.window()
        if not isValid(window) or not window.isWindow():
            return

        import weakref

        self._last_window = weakref.ref(window)
        if not isinstance(window, QDialog):
            self._last_non_dialog_window = weakref.ref(window)

    def _schedule_fix(self, obj):
        if self._disposed or not isinstance(obj, QWidget) or not isValid(obj):
            return
        dialog = obj.window()

        if not self._should_fix(dialog):
            return

        if dialog in self._pending_fixes:
            return
        dialog.setProperty("_lca_global_dialog_fix_pending", True)

        def _first_pass():
            self._apply_fix(dialog)

        def _second_pass():
            try:
                self._apply_fix(dialog)
            finally:
                self._cancel_fix(dialog)

        timers = (QTimer(self), QTimer(self))
        for timer in timers:
            timer.setSingleShot(True)
        timers[0].timeout.connect(_first_pass)
        timers[1].timeout.connect(_second_pass)
        destroyed_connection = dialog.destroyed.connect(lambda: self._cancel_fix(dialog))
        self._pending_fixes[dialog] = (timers, destroyed_connection)
        timers[0].start(0)
        timers[1].start(40)

    def _cancel_fix(self, dialog):
        entry = self._pending_fixes.pop(dialog, None)
        if entry is None:
            return
        timers, connection = entry
        QObject.disconnect(connection)
        for timer in timers:
            if isValid(timer):
                timer.stop()
                timer.deleteLater()
        if isValid(dialog):
            dialog.setProperty("_lca_global_dialog_fix_pending", False)

    def _release_resources(self):
        for dialog in list(self._pending_fixes):
            self._cancel_fix(dialog)
        self._last_window = None
        self._last_non_dialog_window = None

    def _should_fix(self, dialog):
        if self._disposed or not isinstance(dialog, QDialog) or not isValid(dialog):
            return False
        if not dialog.isWindow():
            return False

        return not (
            bool(dialog.property("_lca_screen_fix_disabled"))
            or dialog.windowType() in (Qt.WindowType.Popup, Qt.WindowType.ToolTip)
            or dialog.isFullScreen()
        )

    def _resolve_reference_widget(self, dialog):
        candidates = []

        parent = dialog.parentWidget()
        if parent is not None and isValid(parent):
            candidates.append(parent.window())

        app = QApplication.instance()
        if app is not None:
            focus_widget = app.focusWidget()
            if focus_widget is not None and isValid(focus_widget):
                candidates.append(focus_widget.window())
            active_window = app.activeWindow()
            if active_window is not None and isValid(active_window) and active_window is not dialog:
                candidates.append(active_window.window())

        candidates.extend(reference() for reference in (self._last_non_dialog_window, self._last_window)
                          if reference is not None)

        seen = set()
        for candidate in candidates:
            if not isinstance(candidate, QWidget) or not isValid(candidate):
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

        from utils.window.window_coordinate_common import center_window_on_widget_screen

        reference_widget = self._resolve_reference_widget(dialog)
        center_window_on_widget_screen(dialog, reference_widget)


_message_box_translator = None
_dialog_screen_fixer = None
def setup_message_box_translations():

    """设置消息框翻译"""
    global _message_box_translator, _dialog_screen_fixer

    app = QApplication.instance()
    if app is None:
        raise RuntimeError("安装对话框过滤器前必须创建应用程序")
    if _message_box_translator is None or not isValid(_message_box_translator) or _message_box_translator._disposed:
        _message_box_translator = MessageBoxTranslator()
        app.installEventFilter(_message_box_translator)
    if _dialog_screen_fixer is None or not isValid(_dialog_screen_fixer) or _dialog_screen_fixer._disposed:
        _dialog_screen_fixer = GlobalDialogScreenFixer()
        app.installEventFilter(_dialog_screen_fixer)
    app.setProperty("chinese_buttons", True)


def _resolve_message_box_reference_widget(parent=None, reference_widget=None):
    candidates = []

    if isinstance(reference_widget, QWidget) and isValid(reference_widget):
        candidates.append(reference_widget.window())

    if isinstance(parent, QWidget) and isValid(parent):
        candidates.append(parent.window())

    app = QApplication.instance()
    if app is not None:
        active_window = app.activeWindow()
        if isinstance(active_window, QWidget) and isValid(active_window):
            candidates.append(active_window.window())
        focus_widget = app.focusWidget()
        if isinstance(focus_widget, QWidget) and isValid(focus_widget):
            candidates.append(focus_widget.window())

    seen = set()
    for candidate in candidates:
        if not isinstance(candidate, QWidget) or not isValid(candidate):
            continue
        marker = id(candidate)
        if marker in seen:
            continue
        seen.add(marker)
        return candidate

    return None


def place_dialog_on_screen(dialog, parent=None, reference_widget=None, global_pos=None):
    if not isinstance(dialog, QWidget) or not isValid(dialog):
        return False

    if global_pos is None:
        global_pos = QCursor.pos()

    from utils.window.window_coordinate_common import center_window_on_widget_screen

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
    if parent is not None and (not isinstance(parent, QWidget) or not isValid(parent)):
        raise ValueError("消息框父窗口无效")
    msg_parent = parent
    msg_box = QMessageBox(msg_parent)
    msg_box.setWindowTitle(title)
    msg_box.setText(text)
    msg_box.setIcon(icon)
    msg_box.setStandardButtons(buttons)

    if default_button is not None:
        msg_box.setDefaultButton(default_button)

    if informative_text:
        msg_box.setInformativeText(informative_text)

    if detailed_text:
        msg_box.setDetailedText(detailed_text)

    if window_flags is not None:
        msg_box.setWindowFlags(window_flags)

    place_dialog_on_screen(msg_box, parent=msg_parent, reference_widget=reference_widget)
    return exec_dialog(msg_box)


@dataclass(frozen=True)
class RememberedQuestionResult:
    accepted: bool
    remember: bool


def show_remembered_question(parent, title, text, *, remember_text):
    """只返回明确的继续决定；取消、Esc 和关闭均不记住。"""
    from PySide6.QtWidgets import QCheckBox

    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Question)
    remember = QCheckBox(remember_text, box)
    box.setCheckBox(remember)
    continue_button = box.addButton("继续执行", QMessageBox.ButtonRole.AcceptRole)
    cancel_button = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(continue_button)
    box.setEscapeButton(cancel_button)
    place_dialog_on_screen(box, parent=parent)

    def read_result(_result):
        accepted = box.clickedButton() is continue_button
        return RememberedQuestionResult(accepted, accepted and remember.isChecked())

    return exec_dialog(box, read_result=read_result)


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

