"""脚本卡片的静态输入面板，复用原生行布局、控件与文件入口。"""
from __future__ import annotations

import copy
from PySide6.QtCore import QObject, QEvent, Slot, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from shiboken6 import isValid

from app_core.card_plugins import BUNDLE_PARAMETER, CardPluginError, bundle_from_parameters, input_parameter_key
from app_core.card_plugin_conditions import resolve_parameters, validate_effective_value, validate_inputs
from app_core.card_plugin_presentation import parameter_presentation
from task_workflow.expr import contains_interpolation
from ui.panels.parameter_editors import create_parameter_editor
from ui.panels.parameter_form import ParameterForm
from ui.panels.card_plugin_tool_controller import PluginToolController


class PluginParameterController(QObject):
    def __init__(self, panel):
        bundle = bundle_from_parameters(panel.current_parameters)
        super().__init__(panel)
        self.panel = panel
        self.definitions = bundle.manifest["parameters"]
        self.rows, self.inputs, self.labels, self.editors = {}, {}, {}, {}
        self._connections = []
        self._states = {}
        self._closed = False
        self.form = ParameterForm(panel)
        self.tool_controller = PluginToolController(self)
        self._viewport = panel.scroll_area.viewport()
        self._has_preview = any(item.get("resource_kind") == "image" for item in self.definitions.values())
        if self._has_preview:
            self._viewport.installEventFilter(self)
            for signal in (panel.scroll_area.verticalScrollBar().valueChanged, panel.scroll_area.horizontalScrollBar().valueChanged, self.form._layout_timer.timeout):
                signal.connect(self.refresh_viewport)
                self._connections.append((signal, self.refresh_viewport))
        panel.installEventFilter(self)
        panel.destroyed.connect(self._on_panel_destroyed)

    def eventFilter(self, watched, event):
        if watched is self._viewport and event.type() in (QEvent.Type.Resize, QEvent.Type.Show) and not self._closed:
            self.form._schedule_layout()
        if watched is self.panel and event.type() == QEvent.Type.DeferredDelete:
            from ui.panels.card_plugin_state import release_card_plugin_panel
            release_card_plugin_panel(watched)
        return False

    def _release_bindings(self):
        self._closed = True
        self.tool_controller.close()
        if self._has_preview and isValid(self._viewport):
            self._viewport.removeEventFilter(self)
        self._viewport = None
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections.clear()
        for editor in self.editors.values():
            editor.close()
        self.editors.clear()
        self.form.close()
        self.rows.clear()
        self.inputs.clear()
        self.labels.clear()
        self.definitions.clear()
        self._states.clear()

    @Slot()
    def _on_panel_destroyed(self):
        if not self._closed:
            self._release_bindings()
        self.panel = None

    def build(self):
        panel = self.panel
        if not self.definitions:
            panel._create_empty_parameter_state()
            return
        for name, definition in self.definitions.items():
            storage = input_parameter_key(name)
            row = QWidget(panel)
            row.setObjectName("pluginParameterRow")
            layout = QVBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(panel.content_layout.spacing())
            control_row, control_layout = panel._create_parameter_row(name, definition)
            label = control_layout.itemAt(0).widget()
            label.setTextFormat(Qt.TextFormat.PlainText)
            editor = create_parameter_editor(definition, panel.current_parameters[storage], row)
            self.editors[name] = editor
            panel._register_widget(storage, editor.input)
            if editor.tool_button is not None:
                editor.tool_button.setProperty("pluginToolParameter", name)
                editor.tool_button.clicked.connect(self.tool_controller.start)
                self._connections.append((editor.tool_button.clicked, self.tool_controller.start))
            if editor.preview is not None:
                editor.configure_preview(str(panel.images_dir or ""))
                editor.preview.clicked.connect(self.tool_controller.open_image)
                self._connections.append((editor.preview.clicked, self.tool_controller.open_image))
            if editor.browse_button is not None:
                editor.browse_button.setProperty("pluginParameterName", name)
                editor.browse_button.clicked.connect(self.browse)
                self._connections.append((editor.browse_button.clicked, self.browse))
            panel._attach_created_widget_row(name, definition["type"], layout, control_row, control_layout, editor.control, param_def=definition)
            hint = QLabel(row)
            hint.setTextFormat(Qt.TextFormat.PlainText)
            hint.setObjectName("pluginParameterHint")
            hint.setWordWrap(True)
            hint_row = QWidget(row)
            hint_layout = QHBoxLayout(hint_row)
            hint_layout.setContentsMargins(0, 0, 0, 0)
            hint_layout.addSpacing(label.width() + control_layout.spacing())
            hint.setFixedWidth(editor.control.width())
            hint_layout.addWidget(hint)
            hint_layout.addStretch()
            layout.addWidget(hint_row)
            self.form.add(name, row, parameter_presentation(definition))
            self.rows[name], self.inputs[name], self.labels[name] = row, editor.input, (label, hint)
            editor.changed.connect(self.refresh)
            self._connections.append((editor.changed, self.refresh))
        self.form.finish()
        self.refresh()

    def values(self):
        return {name: editor.read() for name, editor in self.editors.items()}

    def collect(self, *, strict=False, require_complete=True):
        values = self.values()
        if strict:
            try:
                values, _states = validate_inputs(self.definitions, values, allow_unresolved=True, require_complete=require_complete)
            except CardPluginError:
                self.refresh()
                raise
        return {BUNDLE_PARAMETER: copy.deepcopy(self.panel.current_parameters[BUNDLE_PARAMETER]), **{input_parameter_key(name): value for name, value in values.items()}}

    @Slot()
    def refresh(self):
        if self._closed:
            return
        values = self.values()
        resolution = resolve_parameters(self.definitions, values)
        errors = {}
        for name, definition in self.definitions.items():
            editor = self.editors[name]
            label, hint = self.labels[name]
            label.setText(definition["label"] + (" *" if definition["required"] else ""))
            error = ""
            value = values[name]
            if not (isinstance(value, str) and contains_interpolation(value)):
                try:
                    validate_effective_value(value, definition, f"参数 {name}")
                except CardPluginError as caught:
                    error = str(caught)
            if error:
                errors[name] = error
            for widget in (editor.input, hint):
                if widget.property("pluginRuleError") != bool(error):
                    widget.setProperty("pluginRuleError", bool(error))
                    widget.style().unpolish(widget)
                    widget.style().polish(widget)
            hint.setText(error)
            hint.parentWidget().setVisible(bool(error))
            details = [definition.get("tooltip", "")]
            details.extend(f"{title}：{definition[field]}" for title, field in (("最小", "min"), ("最大", "max"), ("步长", "step"), ("小数位", "decimals")) if field in definition)
            if error:
                details.append(error)
            tooltip = "；".join(part for part in details if part)
            label.setToolTip(tooltip)
            editor.input.setToolTip(tooltip)
        self._states = resolution.states
        self.form.refresh(resolution.states, errors)
        self.tool_controller.refresh(resolution.states)
        self.refresh_viewport()

    @Slot()
    def refresh_viewport(self):
        if self._closed or not self._has_preview:
            return
        pending = self.form._layout_timer.isActive()
        for editor in self.editors.values():
            if editor.preview is None:
                continue
            editor.sync_preview()
            preview = editor.preview
            preview.set_viewport_active((not pending or preview.is_valid) and preview.isVisible() and not preview.visibleRegion().isEmpty())

    @Slot()
    def browse(self):
        name = self.sender().property("pluginParameterName")
        definition = self.panel.param_definitions[input_parameter_key(name)]
        self.panel._select_file(self.editors[name].input, definition)

    def apply(self, auto_close):
        self._commit_parameters(self.collect(strict=True), auto_close)

    def save_draft(self):
        self._commit_parameters(self.collect(strict=True, require_complete=False), False)

    def _commit_parameters(self, values, auto_close):
        from ui.panels.parameter_compare import collect_changed_parameters
        changes = collect_changed_parameters(self.panel._opened_parameters_snapshot, values)
        self.panel.current_parameters = copy.deepcopy(values)
        if changes:
            self.panel.parameters_changed.emit(self.panel.current_card_id, copy.deepcopy(values))
        self.panel._opened_parameters_snapshot = copy.deepcopy(values)
        if auto_close:
            self.panel._finish_hiding_panel()

    def close(self):
        if self._closed:
            return
        self.panel.removeEventFilter(self)
        self.panel.destroyed.disconnect(self._on_panel_destroyed)
        self._release_bindings()
        self.panel = None
        self.deleteLater()


def create_plugin_parameters(panel):
    controller = PluginParameterController(panel)
    panel._plugin_parameter_controller = controller
    controller.build()


def release_plugin_parameters(panel):
    controller = getattr(panel, "_plugin_parameter_controller", None)
    panel._plugin_parameter_controller = None
    if controller is not None:
        controller.close()
