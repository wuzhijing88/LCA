from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from task_workflow.thread_start import validate_thread_target
from ui.widgets.custom_widgets import CustomDropdown


class ThreadTargetSelector(QWidget):
    valueChanged = Signal()

    def __init__(self, choices, value, parent=None):
        super().__init__(parent)
        self._known_ids = {thread_id for _label, thread_id in choices}
        self.combo = CustomDropdown(self)
        self.combo.addItem("当前线程", "当前线程")
        self.combo.addItem("全部线程", "全部线程")
        self.combo.addItem("自定义多个线程", "自定义多个线程")
        self.threads = QListWidget(self)
        self.threads.setObjectName("threadTargetList")
        self.threads.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.threads.setMaximumHeight(180)
        if value != []:
            validate_thread_target(value)
        selected = value if isinstance(value, list) else []
        for label, thread_id in choices:
            self.combo.addItem(label, thread_id)
            self._add_thread(label, thread_id, thread_id in selected)
        for thread_id in selected:
            if thread_id not in self._known_ids:
                self._add_thread(f"目标线程不存在 (ID: {thread_id})", thread_id, True)
        if isinstance(value, list):
            self.combo.setCurrentIndex(2)
        else:
            validate_thread_target(value)
            index = self.combo.findData(value)
            if index < 0:
                self.combo.addItem(f"目标线程不存在 (ID: {value})", value)
                index = self.combo.count() - 1
            self.combo.setCurrentIndex(index)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo)
        layout.addWidget(self.threads)
        self.threads.setVisible(isinstance(value, list))
        self.combo.currentIndexChanged.connect(self._mode_changed)
        self.threads.itemChanged.connect(self._selection_changed)

    def _add_thread(self, label, thread_id, checked):
        item = QListWidgetItem(label, self.threads)
        item.setData(Qt.ItemDataRole.UserRole, thread_id)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def _mode_changed(self, _index):
        self.threads.setVisible(self.combo.currentData() == "自定义多个线程")
        self.valueChanged.emit()

    def _selection_changed(self, _item):
        self.valueChanged.emit()

    def value(self, *, for_submission=False):
        value = self.combo.currentData()
        if value == "自定义多个线程":
            value = [
                self.threads.item(index).data(Qt.ItemDataRole.UserRole)
                for index in range(self.threads.count())
                if self.threads.item(index).checkState() == Qt.CheckState.Checked
            ]
        if for_submission:
            validate_thread_target(value)
            selected = value if isinstance(value, list) else [value]
            missing = [target for target in selected if target not in {"当前线程", "全部线程"} and target not in self._known_ids]
            if missing:
                raise ValueError(f"目标线程不存在: {missing}")
        return value
