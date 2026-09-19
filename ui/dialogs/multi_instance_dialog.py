# -*- coding: utf-8 -*-
"""中控多开器：选择程序并启动多个实例。"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
)

from utils.app_paths import get_user_data_dir
from utils.window.multi_instance import (
    MODE_CLOSE_MUTEX,
    LaunchRequest,
    LaunchResult,
    MutexOccupancy,
    launch_instances,
)
from utils.window.window_coordinate_common import center_window_on_widget_screen

logger = logging.getLogger(__name__)

_SETTINGS_NAME = "multi_instance.json"
_LABEL_WIDTH = 40
_BUTTON_WIDTH = 72
_COUNT_WIDTH = 88
_SKIP_STATUS_MARKERS = (
    "互斥",
    "句柄",
    "单开锁",
    "SM0:",
    "Mutex",
    "Mpay",
    "WilStaging",
    "WilError",
    "DBWin",
    "MidiMapper",
    "DDraw",
    "ZonesCache",
)


class _LaunchWorker(QThread):
    log_line = Signal(str)
    finished_result = Signal(object)

    def __init__(self, request: LaunchRequest, occupancy: MutexOccupancy, parent=None):
        super().__init__(parent)
        self._request = request
        self._occupancy = occupancy
        self._stop = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        result = launch_instances(
            self._request,
            occupancy=self._occupancy,
            should_stop=self._stop.is_set,
            log=self.log_line.emit,
        )
        if self._stop.is_set():
            return
        self.finished_result.emit(result)


class _LaunchWorkerKeeper(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers: list[_LaunchWorker] = []

    def retain(self, worker: _LaunchWorker) -> None:
        if worker in self._workers:
            return
        self._workers.append(worker)
        worker.finished.connect(self._on_finished)
        if not worker.isRunning():
            self._release(worker)

    def _on_finished(self) -> None:
        worker = self.sender()
        if isinstance(worker, _LaunchWorker):
            self._release(worker)

    def _release(self, worker: _LaunchWorker) -> None:
        if worker not in self._workers:
            return
        self._workers.remove(worker)
        worker.deleteLater()


_worker_keeper_instance: Optional[_LaunchWorkerKeeper] = None


def _worker_keeper() -> _LaunchWorkerKeeper:
    global _worker_keeper_instance
    if _worker_keeper_instance is None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        _worker_keeper_instance = _LaunchWorkerKeeper(app)
    return _worker_keeper_instance


class MultiInstanceDialog(QDialog):
    instances_ready = Signal(list)

    def __init__(self, parent=None, occupancy: Optional[MutexOccupancy] = None):
        super().__init__(parent)
        self.setObjectName("multiInstanceDialog")
        self.setWindowTitle("多开器")
        self._occupancy = occupancy if occupancy is not None else MutexOccupancy()
        self._worker: Optional[_LaunchWorker] = None
        self._working_dir = ""
        self._started = 0
        self._aborted = False
        self._build_ui()
        self._load_settings()
        self.setMinimumWidth(420)
        self.adjustSize()
        self.setFixedHeight(self.sizeHint().height())
        center_window_on_widget_screen(self, self.parentWidget())

    def _build_ui(self) -> None:
        grid = QGridLayout(self)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        program_label = self._form_label("程序")
        self.exe_edit = QLineEdit()
        self.exe_edit.setPlaceholderText("选择要多开的程序")
        self.exe_browse = QPushButton("浏览")
        self.exe_browse.setMinimumWidth(_BUTTON_WIDTH)
        self.exe_browse.clicked.connect(self._browse_exe)
        grid.addWidget(program_label, 0, 0)
        grid.addWidget(self.exe_edit, 0, 1)
        grid.addWidget(self.exe_browse, 0, 2)

        count_label = self._form_label("数量")
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 32)
        self.count_spin.setValue(2)
        self.count_spin.setFixedWidth(_COUNT_WIDTH)
        self.count_spin.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        self.add_to_center_check = QCheckBox("启动后添加到中控列表")
        self.add_to_center_check.setChecked(True)
        count_row = QWidget()
        count_layout = QHBoxLayout(count_row)
        count_layout.setContentsMargins(0, 0, 0, 0)
        count_layout.setSpacing(12)
        count_layout.addWidget(self.count_spin, 0, Qt.AlignmentFlag.AlignVCenter)
        count_layout.addWidget(self.add_to_center_check, 0, Qt.AlignmentFlag.AlignVCenter)
        count_layout.addStretch(1)
        grid.addWidget(count_label, 1, 0)
        grid.addWidget(count_row, 1, 1, 1, 2)

        buttons = QWidget()
        action_row = QHBoxLayout(buttons)
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self.start_btn = QPushButton("启动")
        self.start_btn.setProperty("primary", True)
        self.start_btn.setMinimumWidth(_BUTTON_WIDTH)
        self.start_btn.clicked.connect(self._start_launch)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setMinimumWidth(_BUTTON_WIDTH)
        self.stop_btn.clicked.connect(self._stop_launch)
        action_row.addWidget(self.start_btn)
        action_row.addWidget(self.stop_btn)
        action_row.addStretch(1)
        grid.addWidget(buttons, 2, 1, 1, 2)

        self.status_label = QLabel("选择程序后点启动。")
        self.status_label.setWordWrap(True)
        grid.addWidget(self.status_label, 3, 1, 1, 2)

    def _form_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFixedWidth(_LABEL_WIDTH)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return label

    def _browse_exe(self) -> None:
        start = str(self.exe_edit.text() or "").strip()
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "选择程序",
            os.path.dirname(start) if start else "",
            "程序 (*.exe);;所有文件 (*.*)",
        )
        if not path:
            return
        self.exe_edit.setText(path)
        self._working_dir = os.path.dirname(path)

    def _append_log(self, message: str) -> None:
        from shiboken6 import isValid

        if not isValid(self) or not isValid(self.status_label):
            return
        text = self._friendly_status(message)
        if text:
            self.status_label.setText(text)

    def _friendly_status(self, message: str) -> str:
        raw = str(message or "").strip()
        if not raw:
            return ""
        if any(marker in raw for marker in _SKIP_STATUS_MARKERS):
            return ""
        if raw.startswith("已启动进程"):
            self._started += 1
            return f"正在启动第 {self._started} 个…"
        if raw.startswith("后续实例改为启动"):
            name = raw.split("启动", 1)[-1].strip()
            return f"正在启动 {name}"
        if raw.startswith("已有游戏进程"):
            return "已检测到游戏，改为直接启动。"
        if raw.startswith("已关联进程"):
            return "已找到游戏进程。"
        if raw.startswith("找到 ") and "窗口" in raw:
            return raw
        if raw.startswith("进程已启动，但未找到窗口"):
            return "程序已启动，窗口稍后可在中控里绑定。"
        if raw.startswith("开始多开"):
            return raw.replace("开始多开：", "正在启动 ")
        if raw.startswith("正在停止"):
            return "正在停止…"
        if raw.startswith("多开失败") or raw.startswith("已停止"):
            return raw
        return ""

    def _build_request(self) -> Optional[LaunchRequest]:
        exe = str(self.exe_edit.text() or "").strip()
        if not exe:
            QMessageBox.warning(self, "无法启动", "请先选择程序。")
            return None
        if not os.path.isfile(exe):
            QMessageBox.warning(self, "无法启动", f"找不到程序: {exe}")
            return None
        working_dir = str(self._working_dir or "").strip() or os.path.dirname(exe)
        return LaunchRequest(
            exe_path=exe,
            working_dir=working_dir,
            count=int(self.count_spin.value()),
            interval_sec=2.0,
            mode=MODE_CLOSE_MUTEX,
        )

    def _start_launch(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        request = self._build_request()
        if request is None:
            return
        self._save_settings()
        self._started = 0
        self._aborted = False
        self.status_label.setText(f"正在启动 {request.count} 个…")
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        self._worker = _LaunchWorker(request, self._occupancy, self)
        self._worker.log_line.connect(self._append_log)
        self._worker.finished_result.connect(self._on_launch_finished)
        self._worker.finished.connect(self._on_worker_finished)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._worker.start()

    def _stop_launch(self) -> None:
        worker = self._worker
        if worker is None:
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            return
        self._aborted = True
        worker.request_stop()
        self.stop_btn.setEnabled(False)
        self.status_label.setText("正在停止…")

    def _on_worker_finished(self) -> None:
        from shiboken6 import isValid

        if not isValid(self):
            return
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if self._aborted:
            self.status_label.setText("已停止多开。")

    def _detach_running_worker(self) -> None:
        worker = self._worker
        if worker is None:
            return
        self._aborted = True
        worker.request_stop()
        for signal, slot in (
            (worker.log_line, self._append_log),
            (worker.finished_result, self._on_launch_finished),
            (worker.finished, self._on_worker_finished),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        worker.setParent(None)
        _worker_keeper().retain(worker)
        self._worker = None

    def _on_launch_finished(self, result: object) -> None:
        from shiboken6 import isValid

        if not isValid(self) or self._aborted:
            return
        payload = result if isinstance(result, LaunchResult) else LaunchResult()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if payload.errors:
            self.status_label.setText(payload.errors[-1])
            QMessageBox.warning(self, "多开未完成", "\n".join(payload.errors))
            return
        windows = list(payload.windows or [])
        add_to_center = self.add_to_center_check.isChecked()
        if windows:
            if add_to_center:
                self.status_label.setText(f"已启动，已加入中控 {len(windows)} 个窗口。")
                self.instances_ready.emit(windows)
            else:
                self.status_label.setText(f"已启动，找到 {len(windows)} 个窗口。")
            return
        if payload.pids:
            if add_to_center:
                self.status_label.setText("程序已启动，窗口稍后可在中控里绑定。")
            else:
                self.status_label.setText("程序已启动。")
            return
        self.status_label.setText("没有启动新的实例。")

    def closeEvent(self, event) -> None:
        self._detach_running_worker()
        self._save_settings()
        super().closeEvent(event)

    def _settings_path(self) -> str:
        return os.path.join(get_user_data_dir("LCA"), _SETTINGS_NAME)

    def _load_settings(self) -> None:
        path = self._settings_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("读取多开器配置失败: %s", exc)
            return
        if not isinstance(data, dict):
            return
        exe = str(data.get("exe_path") or "").strip()
        self.exe_edit.setText(exe)
        self._working_dir = str(data.get("working_dir") or "").strip() or (os.path.dirname(exe) if exe else "")
        self.count_spin.setValue(max(1, min(32, int(data.get("count") or 2))))
        self.add_to_center_check.setChecked(bool(data.get("add_to_center", True)))

    def _save_settings(self) -> None:
        exe = str(self.exe_edit.text() or "").strip()
        data: Dict[str, Any] = {
            "exe_path": exe,
            "working_dir": str(self._working_dir or "").strip() or (os.path.dirname(exe) if exe else ""),
            "count": int(self.count_spin.value()),
            "add_to_center": self.add_to_center_check.isChecked(),
        }
        path = self._settings_path()
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.warning("保存多开器配置失败: %s", exc)
