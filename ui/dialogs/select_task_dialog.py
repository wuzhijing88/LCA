from typing import List, Optional

import copy
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QSizePolicy, QButtonGroup, QFrame, QScrollArea, QStyle, QStyleOptionButton, QStylePainter,
)
from PySide6.QtCore import Qt, Signal

from app_core.card_plugins import BUNDLE_PARAMETER, CardPluginStore, InvalidInstalledCardPlugin, PLUGIN_TASK_TYPE, input_parameter_key
from themes import apply_rounded_popup


class _TaskTypeButton(QPushButton):
    """任务类型按钮：单击选中，双击直接确认添加。"""
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class _PluginTaskButton(_TaskTypeButton):
    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        content = self.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, self)
        name = " ".join(self.text().split())
        option.text = self.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, max(0, content.width()))
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        painter.end()


class SelectTaskDialog(QDialog):
    """显示内置卡片及已安装插件；选择结果携带精确插件快照。"""
    def __init__(self, task_types: List[str], parent=None, plugin_store=None):
        super().__init__(parent)
        self.setObjectName("taskSelectionDialog")
        apply_rounded_popup(self, frameless=False)
        self.setWindowTitle("选择任务类型")
        self.setMinimumWidth(420)
        self.resize(460, 500)
        self._builtin_types = list(task_types)
        self._store = CardPluginStore() if plugin_store is None else plugin_store
        self._plugin_choices = {}
        self._selected_task_type: Optional[str] = None
        self.task_buttons = {}
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(15)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.info_label = QLabel("请选择要添加的任务类型，双击可直接添加：")
        self.info_label.setObjectName("infoLabel")
        self.main_layout.addWidget(self.info_label)
        self.plugin_status = QLabel()
        self.plugin_status.setTextFormat(Qt.TextFormat.PlainText)
        self.plugin_status.setWordWrap(True)
        self.main_layout.addWidget(self.plugin_status)
        frame = QFrame()
        self._grid = QGridLayout(frame)
        self._grid.setSpacing(8)
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        self._scroll = QScrollArea()
        self._scroll.setObjectName("taskGridScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setWidget(frame)
        self.main_layout.addWidget(self._scroll, 1)
        buttons = QHBoxLayout()
        manage = QPushButton("管理插件")
        manage.clicked.connect(self._manage_plugins)
        buttons.addWidget(manage)
        buttons.addStretch()
        self.ok_button = QPushButton("确定")
        self.ok_button.setObjectName("okButton")
        self.ok_button.setDefault(True)
        self.ok_button.setMinimumHeight(32)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.setMinimumHeight(32)
        buttons.addWidget(self.ok_button)
        buttons.addWidget(self.cancel_button)
        self.main_layout.addLayout(buttons)
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.refresh_choices()

    def refresh_choices(self):
        previous = self._selected_task_type
        self._selected_task_type = None
        self._plugin_choices.clear()
        for button in self.task_buttons.values():
            self.button_group.removeButton(button)
            self._grid.removeWidget(button)
            button.deleteLater()
        self.task_buttons.clear()
        labels = {name: name for name in self._builtin_types}
        try:
            invalid = []
            for plugin in self._store.inspect_installed():
                if isinstance(plugin, InvalidInstalledCardPlugin):
                    invalid.append(str(plugin.path) + "：" + plugin.error)
                    continue
                key = "脚本卡片@" + plugin.digest
                self._plugin_choices[key] = plugin
                labels[key] = plugin.manifest["name"]
            self.plugin_status.setText("以下失效插件未加载，请在管理插件中处理：\n" + "\n".join(invalid) if invalid else "")
        except Exception as exc:
            self._plugin_choices.clear()
            labels = {name: name for name in self._builtin_types}
            self.plugin_status.setText("插件列表不可用：" + str(exc))
        for index, (key, label) in enumerate(labels.items()):
            if key in self._plugin_choices:
                manifest = self._plugin_choices[key].manifest
                button = _PluginTaskButton(" ".join(label.split()))
                button.setAccessibleName(label)
                button.setToolTip(label + "\n" + manifest["id"] + "\n" + manifest["description"])
            else:
                button = _TaskTypeButton(label)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setCheckable(True)
            button.setMinimumHeight(36)
            button.setMinimumWidth(150)
            button.setObjectName("taskButton")
            self.button_group.addButton(button)
            self.task_buttons[key] = button
            self._grid.addWidget(button, index // 2, index % 2)
            button.clicked.connect(lambda checked, choice=key: self._on_task_selected(choice))
            button.double_clicked.connect(lambda choice=key: self._on_task_double_clicked(choice))
        if labels:
            selected = previous if previous in labels else next(iter(labels))
            self.task_buttons[selected].setChecked(True)
            self._selected_task_type = selected
        self.ok_button.setEnabled(bool(labels))

    def _manage_plugins(self):
        from ui.dialogs.card_plugin_manager_dialog import CardPluginManagerDialog
        dialog = CardPluginManagerDialog(self, store=self._store)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()
        self.refresh_choices()

    def _on_task_selected(self, task_type: str):
        self._selected_task_type = task_type

    def _on_task_double_clicked(self, task_type: str):
        self._on_task_selected(task_type)
        self.accept()

    def selected_task_type(self) -> Optional[str]:
        if self._selected_task_type in self._plugin_choices:
            return PLUGIN_TASK_TYPE
        return self._selected_task_type

    def selected_task_parameters(self):
        if self._selected_task_type not in self._plugin_choices:
            raise ValueError("当前选择不是卡片插件")
        bundle = self._plugin_choices[self._selected_task_type].load()
        result = {input_parameter_key(key): copy.deepcopy(definition["default"]) for key, definition in bundle.manifest["parameters"].items()}
        result[BUNDLE_PARAMETER] = bundle.snapshot()
        return result
