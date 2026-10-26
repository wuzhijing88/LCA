"""脚本专用环境设置、实际库清单和可取消的环境任务。"""

from __future__ import annotations

import threading

from PySide6.QtCore import QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from app_core.script_environments import EnvironmentError, EnvironmentManager, normalize_environment
from themes import ThemedComboBox
from ui.panels.managed_resources import PanelResources


class _EnvironmentWorker(QThread):
    progress = Signal(str)
    result = Signal(bool, str, object)

    def __init__(self, settings, operation):
        super().__init__()
        self.settings, self.operation = settings, operation
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            manager = EnvironmentManager(
                stop_checker=self.stop_event.is_set, progress=self.progress.emit
            )
            if self.operation == "delete":
                manager.delete()
            elif self.operation == "prepare":
                with manager.prepare(self.settings):
                    pass
            elif self.operation != "inspect":
                raise ValueError("未知的环境任务")
            snapshot = manager.inspect()
            if snapshot["exists"]:
                message = f"环境已就绪，已安装 {len(snapshot['packages'])} 个库"
            else:
                message = "脚本环境尚未创建，点击“准备环境”即可创建 script_venv"
            if self.operation == "delete":
                message = "脚本专用环境已删除，下次运行时重新创建"
            self.result.emit(True, message, snapshot)
        except Exception as exc:  # noqa: BLE001 -- background errors are shown in the dialog
            self.result.emit(False, str(exc), None)


def _dispose_worker(state):
    worker = state[0]
    if worker is not None:
        worker.progress.disconnect()
        worker.result.disconnect()
        worker.stop_event.set()
        worker.wait(20)
        state[0] = None


class ScriptEnvironmentDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("scriptEnvironmentDialog")
        self.setWindowTitle("脚本运行环境")
        self.resize(760, 680)
        self._state = [None]
        self._resources = PanelResources()
        self._closed = False
        self.destroyed.connect(lambda _=None, state=self._state: _dispose_worker(state))
        settings = normalize_environment(settings)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.mode = ThemedComboBox()
        self.mode.addItem("内置环境", "builtin")
        self.mode.addItem("独立环境", "isolated")
        self.mode.setCurrentIndex(self.mode.findData(settings["mode"]))
        form.addRow("运行环境", self.mode)
        self.mode_hint = QLabel()
        self.mode_hint.setObjectName("scriptEnvironmentHint")
        self.mode_hint.setWordWrap(True)
        form.addRow("", self.mode_hint)
        self.interpreter = QLineEdit()
        self.interpreter.setReadOnly(True)
        self.interpreter.setToolTip("实际运行路径自动显示；基础 Python 可在“安装依赖”页设置")
        form.addRow("Python 路径", self.interpreter)
        self.index = QLineEdit(settings["index_url"])
        form.addRow("软件源", self.index)
        layout.addLayout(form)

        self.tabs = QTabWidget()
        installed_page = QWidget()
        installed_layout = QVBoxLayout(installed_page)
        installed_layout.setContentsMargins(12, 12, 12, 12)
        installed_layout.setSpacing(10)
        installed_header = QHBoxLayout()
        self.package_status = QLabel("尚未读取")
        self.refresh_button = QPushButton("刷新列表")
        self.refresh_button.clicked.connect(self._refresh)
        installed_header.addWidget(self.package_status, 1)
        installed_header.addWidget(self.refresh_button)
        installed_layout.addLayout(installed_header)
        self.packages = QTableWidget(0, 2)
        self.packages.setHorizontalHeaderLabels(["库名称", "已安装版本"])
        self.packages.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.packages.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.packages.verticalHeader().hide()
        self.packages.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.packages.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        installed_layout.addWidget(self.packages)
        self.tabs.addTab(installed_page, "已安装库")

        dependency_page = QWidget()
        dependency_layout = QVBoxLayout(dependency_page)
        dependency_layout.setContentsMargins(12, 12, 12, 12)
        dependency_layout.setSpacing(10)
        dependency_layout.addWidget(QLabel("安装依赖（每行一个，可指定版本）"))
        self.requirements = QPlainTextEdit("\n".join(settings["requirements"]))
        self.requirements.setPlaceholderText("numpy==2.2.6\nopencv-python==4.13.0.90")
        dependency_layout.addWidget(self.requirements, 1)
        base_form = QFormLayout()
        base_row = QHBoxLayout()
        self.base_interpreter = QLineEdit(settings["interpreter"])
        self.base_interpreter.setPlaceholderText("自动下载并管理 Python 3.12.12")
        browse = QPushButton("选择解释器")
        browse.clicked.connect(self._browse)
        base_row.addWidget(self.base_interpreter, 1)
        base_row.addWidget(browse)
        base_form.addRow("基础 Python", base_row)
        dependency_layout.addLayout(base_form)
        note = QLabel("基础 Python 仅用于创建环境，变更后需删除并重建 script_venv。")
        note.setWordWrap(True)
        dependency_layout.addWidget(note)
        self.tabs.addTab(dependency_page, "安装依赖")
        layout.addWidget(self.tabs, 2)

        actions = QHBoxLayout()
        self.prepare_button = QPushButton("准备环境")
        self.prepare_button.clicked.connect(lambda: self._start("prepare"))
        self.delete_button = QPushButton("删除脚本环境")
        self.delete_button.clicked.connect(self._delete)
        self.cancel_button = QPushButton("停止")
        self.cancel_button.clicked.connect(self._stop)
        self.directory_button = QPushButton("打开环境目录")
        self.directory_button.clicked.connect(self._open_directory)
        for button in (self.prepare_button, self.cancel_button, self.delete_button, self.directory_button):
            actions.addWidget(button, 1)
        layout.addLayout(actions)
        self.status = QLabel("尚未检查")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("环境检查与安装进度会显示在这里")
        self.output.setMaximumBlockCount(400)
        layout.addWidget(self.output, 1)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._fields = [self.index, self.requirements, self.base_interpreter, browse]
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()

    def settings(self):
        return normalize_environment({
            "mode": self.mode.currentData(), "interpreter": self.base_interpreter.text(),
            "index_url": self.index.text().strip(),
            "requirements": [line.strip() for line in self.requirements.toPlainText().splitlines() if line.strip()],
        })

    def _clear_packages(self, message):
        self.packages.setRowCount(0)
        self.tabs.setTabText(0, "已安装库")
        self.package_status.setText(message)

    def _mode_changed(self):
        self._clear_packages("等待读取")
        if self.mode.currentData() == "isolated":
            self.mode_hint.setText("使用独立的脚本环境，可安装所需依赖；首次运行时自动准备。")
            self.interpreter.setText(str(EnvironmentManager().executable))
            self.interpreter.setCursorPosition(0)
            self.status.setText("正在读取脚本环境")
            QTimer.singleShot(0, self, self._refresh)
        else:
            self.mode_hint.setText("使用 LCA 自带的运行库，无需单独安装依赖。")
            self.interpreter.setText("LCA 内置运行库")
            self._clear_packages("内置环境使用 LCA 自带的库")
            self.status.setText("当前使用内置环境")
        self._update_enabled()

    def _update_enabled(self):
        running = self._state[0] is not None
        isolated = self.mode.currentData() == "isolated"
        self.mode.setEnabled(not running)
        for field in self._fields:
            field.setEnabled(isolated and not running)
        for button in (self.prepare_button, self.delete_button, self.refresh_button):
            button.setEnabled(isolated and not running)
        self.cancel_button.setEnabled(running)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not running)
        self.progress.setVisible(running)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择用于创建环境的完整 Python 解释器", self.base_interpreter.text(),
            "Python 解释器 (python.exe)",
        )
        if path:
            self.base_interpreter.setText(path)

    def _open_directory(self):
        root = EnvironmentManager().directory
        if not root.is_dir():
            self.status.setText("脚本环境尚未创建，请先准备环境")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(root))):
            self.status.setText("无法打开环境目录：" + str(root))

    def _delete(self):
        if QMessageBox.question(
            self, "删除脚本环境", "删除共用的 script_venv 及其中全部库？所有脚本下次使用时将重新准备环境。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            self._start("delete")

    def _refresh(self):
        if not self._closed and self.mode.currentData() == "isolated":
            self._start("inspect")

    def _start(self, operation):
        if self._closed or self._state[0] is not None:
            return
        try:
            settings = self.settings() if operation == "prepare" else None
        except EnvironmentError as exc:
            self.status.setText(str(exc))
            return
        self.output.clear()
        self._clear_packages("正在读取" if operation == "inspect" else "等待环境任务完成")
        self.status.setText({"prepare": "正在准备环境", "delete": "正在删除脚本环境", "inspect": "正在读取已安装库"}[operation])
        worker = _EnvironmentWorker(settings, operation)
        self._resources.own_thread(worker)
        worker.progress.connect(self.output.appendPlainText)
        worker.result.connect(self._on_result)
        worker.finished.connect(self._finished)
        self._state[0] = worker
        worker.start()
        self._update_enabled()

    def _finished(self):
        worker = self.sender()
        if self._state[0] is worker:
            self._state[0] = None
        self._update_enabled()

    def _on_result(self, ok, message, snapshot):
        self.status.setText(message)
        if not ok:
            self._clear_packages("读取失败，已安装库状态未知")
            return
        self.interpreter.setText(snapshot["executable"])
        self.interpreter.setCursorPosition(0)
        packages = snapshot["packages"]
        self.packages.setRowCount(len(packages))
        for row, (name, version) in enumerate(packages):
            self.packages.setItem(row, 0, QTableWidgetItem(name))
            self.packages.setItem(row, 1, QTableWidgetItem(version))
        self.tabs.setTabText(0, f"已安装库（{len(packages)}）")
        self.package_status.setText(f"共 {len(packages)} 个库" if snapshot["exists"] else "环境尚未创建")

    def _stop(self):
        if self._state[0] is not None:
            self._state[0].stop_event.set()
            self.status.setText("正在停止并清理环境任务")

    def _accept(self):
        try:
            self.settings()
        except EnvironmentError as exc:
            self.status.setText(str(exc))
            return
        self.accept()

    def done(self, result):
        self._closed = True
        _dispose_worker(self._state)
        super().done(result)
