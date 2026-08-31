"""共用定时闹钟编辑器：运行窗面板与设置对话框共用。"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from PySide6.QtCore import QTime, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from app_core.player.package import normalize_schedule_alarms


class ScheduleAlarmsEditor(QWidget):
    """固定槽位闹钟：启用 + HH:mm。"""

    alarms_changed = Signal()

    def __init__(
        self,
        parent=None,
        *,
        alarms: Optional[List[Mapping[str, Any]]] = None,
        title: str = "定时（到点自动开始）",
        interactive: bool = True,
        slots: int = 4,
    ):
        super().__init__(parent)
        self.setObjectName("ScheduleAlarmsEditor")
        self._interactive = bool(interactive)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        if title:
            layout.addWidget(QLabel(str(title)))
        self._rows: List[Dict[str, Any]] = []
        for alarm in normalize_schedule_alarms(alarms, slots=slots):
            row = QFrame(self)
            row.setFrameShape(QFrame.Shape.NoFrame)
            row.setAutoFillBackground(False)
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(6)
            enabled = QCheckBox("启用")
            enabled.setChecked(bool(alarm.get("enabled")))
            enabled.setEnabled(self._interactive)
            time_edit = QTimeEdit(row)
            time_edit.setDisplayFormat("HH:mm")
            time_edit.setTime(QTime(int(alarm.get("hour") or 0), int(alarm.get("minute") or 0)))
            time_edit.setEnabled(self._interactive)
            time_edit.setAutoFillBackground(False)
            row_l.addWidget(enabled)
            row_l.addWidget(time_edit, 1)
            layout.addWidget(row)
            self._rows.append({"enabled": enabled, "time": time_edit})
            if self._interactive:
                enabled.toggled.connect(lambda *_: self.alarms_changed.emit())
                time_edit.timeChanged.connect(lambda *_: self.alarms_changed.emit())

    def alarm_rows(self) -> List[Dict[str, Any]]:
        return list(self._rows)

    def alarms(self) -> List[Dict[str, Any]]:
        return normalize_schedule_alarms(
            [
                {
                    "enabled": bool(row["enabled"].isChecked()),
                    "hour": int(row["time"].time().hour()),
                    "minute": int(row["time"].time().minute()),
                }
                for row in self._rows
            ]
        )

    def set_alarms(self, alarms: Optional[List[Mapping[str, Any]]]) -> None:
        normalized = normalize_schedule_alarms(alarms)
        for index, row in enumerate(self._rows):
            alarm = normalized[index] if index < len(normalized) else {"enabled": False, "hour": 8, "minute": 0}
            row["enabled"].blockSignals(True)
            row["time"].blockSignals(True)
            row["enabled"].setChecked(bool(alarm.get("enabled")))
            row["time"].setTime(QTime(int(alarm.get("hour") or 0), int(alarm.get("minute") or 0)))
            row["enabled"].blockSignals(False)
            row["time"].blockSignals(False)
