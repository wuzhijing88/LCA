"""原生与声明式参数面板共用的控件适配层。"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from contextlib import ExitStack
from functools import partial
import html
import weakref

from PySide6.QtCore import QObject, QSignalBlocker, Signal, Slot, Qt
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QCheckBox, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QRadioButton, QSizePolicy, QVBoxLayout, QWidget
from shiboken6 import isValid

from app_core.card_plugin_conditions import validate_effective_value
from app_core.card_plugin_presentation import parameter_presentation
from ui.widgets.custom_widgets import CustomDropdown


class ParameterNumberEdit(QLineEdit):
    def __init__(self, kind, parent):
        super().__init__(parent)
        self._kind = kind
        self._limits = {}

    def set_limits(self, definition):
        self._limits = {key: definition[key] for key in ("min", "max", "step", "decimals") if key in definition}

    def keyPressEvent(self, event):
        if event.key() not in (Qt.Key.Key_Up, Qt.Key.Key_Down) or event.modifiers() != Qt.KeyboardModifier.NoModifier:
            super().keyPressEvent(event)
            return
        if self.isReadOnly():
            return
        try:
            direction = 1 if event.key() == Qt.Key.Key_Up else -1
            if self._kind == "int":
                candidate = int(self.text().strip()) + direction * self._limits.get("step", 1)
                value = candidate
            else:
                current = Decimal(self.text().strip())
                if not current.is_finite():
                    return
                candidate = current + direction * Decimal(str(self._limits.get("step", 1)))
                value = float(candidate)
            validate_effective_value(value, {**self._limits, "type": self._kind, "required": True}, "数值")
        except (InvalidOperation, ValueError, OverflowError):
            return
        self.setText(str(int(candidate)) if self._kind == "int" else str(candidate))
        event.accept()


class RadioChoiceInput(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.button_group = QButtonGroup(self)
        self.button_group.buttonToggled.connect(self._selection_changed)
        self._choices = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

    @Slot(QAbstractButton, bool)
    def _selection_changed(self, button, checked):
        if checked:
            self.changed.emit()

    def currentData(self):
        button = self.button_group.checkedButton()
        return button.property("value") if button is not None else None

    def _fit_choices(self):
        for button in self.button_group.buttons():
            button.setToolTip(button.text())
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def set_choices(self, choices, selected, *, compact=False):
        if choices == self._choices:
            with QSignalBlocker(self.button_group):
                for button in self.button_group.buttons():
                    if button.property("value") == selected:
                        button.setChecked(True)
            if compact:
                self._fit_choices()
            return
        with QSignalBlocker(self.button_group):
            for button in self.button_group.buttons():
                button.blockSignals(True)
                self.button_group.removeButton(button)
                self.layout().removeWidget(button)
                button.hide()
                button.deleteLater()
            self._choices = list(choices)
            for title, value in choices:
                button = QRadioButton(title, self)
                button.setProperty("value", value)
                self.button_group.addButton(button)
                self.layout().addWidget(button)
                button.setChecked(value == selected)
        if compact:
            self._fit_choices()


class ParameterEditor(QObject):
    changed = Signal()

    def __init__(self, control, input_widget, read, write, signal):
        super().__init__(control)
        self.control = control
        self.input = input_widget
        self.browse_button = None
        self.tool_button = None
        self.preview = None
        self._preview_directory = ""
        self._read = read
        self._read_view = input_widget.text if isinstance(input_widget, QLineEdit) else read
        self._write = write
        self._closed = False
        self._signal = signal
        control.parameter_editor = self
        input_widget.parameter_editor = self
        signal.connect(self._notify)
        owner = weakref.ref(self)

        def release(_object=None):
            editor = owner()
            if editor is not None:
                editor.close()

        self._destroy_callback = release
        control.destroyed.connect(release)

    @Slot()
    def _notify(self):
        if not self._closed:
            self.changed.emit()

    def read(self):
        if self._closed:
            raise RuntimeError("参数控件已释放")
        return self._read()

    def write(self, value):
        if self._closed:
            raise RuntimeError("参数控件已释放")
        with QSignalBlocker(self.input):
            self._write(value)

    def update_definition(self, definition):
        if isinstance(self.input, ParameterNumberEdit):
            self.input.set_limits(definition)

    def decorate(self, presentation):
        if "工具" not in presentation and not presentation.get("预览"):
            return
        original = self.control
        wrapper = QWidget(original.parentWidget())
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(original)
        original.destroyed.disconnect(self._destroy_callback)
        if original is not self.input:
            del original.parameter_editor
        self.setParent(wrapper)
        self.control = wrapper
        wrapper.parameter_editor = self
        wrapper.destroyed.connect(self._destroy_callback)
        if "工具" in presentation:
            tool = presentation["工具"]
            self.tool_button = QPushButton(tool["类型"], wrapper)
            targets = "、".join(f"{role}→{name}" for role, name in tool["写入"].items())
            details = f"确认后整组写入：{targets}。取消不修改参数。"
            details = "窗口来源：当前全局绑定窗口。" + details
            self.tool_button.setToolTip("<p>" + html.escape(details) + "</p>")
            layout.addWidget(self.tool_button)
        if presentation.get("预览"):
            from ui.panels.parameter_image_preview import ParameterImagePreview
            self.preview = ParameterImagePreview(wrapper)
            layout.addWidget(self.preview)
            self.input.textChanged.connect(self.sync_preview)

    def configure_preview(self, directory):
        self._preview_directory = directory
        self.sync_preview()

    @Slot()
    def sync_preview(self):
        if self.preview is not None:
            path = self.input.text()
            if path != self.preview._declared_path or self._preview_directory != self.preview._images_dir:
                self.preview.set_image_path(path, self._preview_directory)

    def set_options(self, options, selected, status=None):
        choices = [(option, option) for option in options]
        if selected not in options:
            title = f"{status}：{selected}" if status else f"当前值不在可选项中：{selected}"
            choices.insert(0, (title, selected))
        widget = self.input
        if isinstance(widget, RadioChoiceInput):
            widget.set_choices(choices, selected, compact=True)
        elif isinstance(widget, CustomDropdown):
            if choices == [(widget.itemText(index), widget.itemData(index)) for index in range(widget.count())]:
                return
            with QSignalBlocker(widget):
                widget.clear()
                for title, value in choices:
                    widget.addItem(title, value)
                widget.setCurrentIndex(widget.findData(selected))
        else:
            raise ValueError("当前参数控件不支持选项")

    def close(self):
        if self._closed:
            return
        self._closed = True
        if isValid(self.control):
            self.control.destroyed.disconnect(self._destroy_callback)
        if isValid(self.input):
            if self.preview is not None:
                self.input.textChanged.disconnect(self.sync_preview)
                self.preview.release()
            self._signal.disconnect(self._notify)
            if isinstance(self.input, ParameterNumberEdit):
                self.input.set_limits({})
        # 输入与外层控件可能是同一个对象，按身份保证只解除一次引用。
        widgets = (self.input,) if self.input is self.control else (self.input, self.control)
        for widget in widgets:
            if isValid(widget):
                del widget.parameter_editor
        self._signal = None
        self._read = None
        self._read_view = None
        self._write = None
        self._destroy_callback = None
        self.browse_button = None
        self.tool_button = None
        self.preview = None
        self._preview_directory = ""
        self.input = None
        self.control = None


def apply_editor_values(editors, values):
    snapshots = {name: editors[name]._read_view() for name in values}
    with ExitStack() as stack:
        for name in values:
            stack.enter_context(QSignalBlocker(editors[name].input))
        try:
            for name, value in values.items():
                editors[name].write(value)
        except Exception:
            for name, value in snapshots.items():
                editors[name]._write(value)
            raise


def _read_number(widget, kind):
    text = widget.text()
    try:
        return int(text.strip()) if kind == "int" else float(text.strip())
    except ValueError:
        return text


def _write_line(widget, value):
    widget.setText(str(value))


def _line_editor(definition, value, parent, presentation, numeric_steps):
    kind = definition["type"]
    widget = ParameterNumberEdit(kind, parent) if numeric_steps and kind in {"int", "float"} else QLineEdit(parent)
    widget.setText("" if value is None else str(value))
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    if kind == "text":
        widget.setCursorPosition(0)
    placeholders = {"int": "请输入整数", "float": "请输入小数"}
    widget.setPlaceholderText(presentation.get("占位", placeholders.get(kind, "")))
    widget.setReadOnly(definition.get("readonly", False))
    if presentation["控件"] == "密码框":
        widget.setEchoMode(QLineEdit.EchoMode.Password)
    read = partial(_read_number, widget, kind) if kind in {"int", "float"} else widget.text
    editor = ParameterEditor(widget, widget, read, partial(_write_line, widget), widget.textChanged)
    editor.update_definition(definition)
    return editor


def _multiline_editor(definition, value, parent, presentation, numeric_steps):
    widget = QPlainTextEdit(parent)
    widget.setPlainText(str(value))
    widget.setPlaceholderText(presentation.get("占位", ""))
    widget.setReadOnly(definition.get("readonly", False))
    widget.ensurePolished()
    if "height" in definition:
        widget.setFixedHeight(definition["height"])
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    else:
        widget.setMaximumHeight(100)
    return ParameterEditor(widget, widget, widget.toPlainText, widget.setPlainText, widget.textChanged)


def _checkbox_editor(definition, value, parent, presentation, numeric_steps):
    if not isinstance(value, bool):
        return _line_editor(definition, value, parent, presentation, numeric_steps)
    widget = QCheckBox(parent)
    widget.setChecked(value)
    widget.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, False)
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    widget.setMouseTracking(False)
    return ParameterEditor(widget, widget, widget.isChecked, widget.setChecked, widget.toggled)


def _choice_editor(definition, value, parent, presentation, numeric_steps):
    widget = CustomDropdown(parent)
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    editor = ParameterEditor(widget, widget, widget.currentData, partial(_select_dropdown_value, widget), widget.currentIndexChanged)
    if definition.get("options"):
        editor.set_options(definition["options"], value)
    return editor


def _select_dropdown_value(widget, value):
    index = widget.findData(value)
    if index < 0:
        raise ValueError("参数值不在当前选项中")
    widget.setCurrentIndex(index)


def _radio_editor(definition, value, parent, presentation, numeric_steps):
    widget = RadioChoiceInput(parent)
    options = definition["options"]
    choices = [(str(title), key) for key, title in options.items()] if isinstance(options, dict) else [(str(option), option) for option in options]
    widget.set_choices(choices, value)
    return ParameterEditor(widget, widget, widget.currentData, partial(_select_radio_value, widget), widget.changed)


def _select_radio_value(widget, value):
    for button in widget.button_group.buttons():
        if button.property("value") == value:
            button.setChecked(True)
            return
    raise ValueError("参数值不在当前单选项中")


def _file_editor(definition, value, parent, presentation, numeric_steps):
    control = QWidget(parent)
    layout = QHBoxLayout(control)
    layout.setContentsMargins(0, 0, 0, 0)
    widget = QLineEdit(str(value) if value else "", control)
    widget.setPlaceholderText(presentation.get("占位", "点击选择文件或手动输入路径..."))
    layout.addWidget(widget)
    button = QPushButton("浏览...", control)
    layout.addWidget(button)
    editor = ParameterEditor(control, widget, widget.text, widget.setText, widget.textChanged)
    editor.browse_button = button
    return editor


_EDITORS = {
    "文本框": _line_editor, "密码框": _line_editor, "只读文本": _line_editor,
    "整数输入": _line_editor, "小数输入": _line_editor, "多行文本": _multiline_editor,
    "复选框": _checkbox_editor, "下拉框": _choice_editor,
    "单选按钮": _radio_editor, "文件选择": _file_editor,
}


def create_parameter_editor(definition, value, parent, *, numeric_steps=True):
    presentation = parameter_presentation(definition)
    control = presentation["控件"]
    if control not in _EDITORS:
        raise ValueError(f"不支持的参数控件：{control}")
    editor = _EDITORS[control](definition, value, parent, presentation, numeric_steps)
    try:
        editor.decorate(presentation)
    except Exception:
        editor.close()
        editor.parent().deleteLater()
        raise
    return editor
