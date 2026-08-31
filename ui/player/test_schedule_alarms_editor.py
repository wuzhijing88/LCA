import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.player.schedule_alarms_editor import ScheduleAlarmsEditor


def _qapp():
    return QApplication.instance() or QApplication([])


def test_schedule_alarms_editor_roundtrip():
    _qapp()
    editor = ScheduleAlarmsEditor(
        alarms=[{"enabled": True, "hour": 9, "minute": 30}, {"enabled": False, "hour": 12, "minute": 0}]
    )
    data = editor.alarms()
    assert data[0]["enabled"] is True
    assert data[0]["hour"] == 9
    assert data[0]["minute"] == 30
    editor.set_alarms([{"enabled": False, "hour": 7, "minute": 5}])
    data2 = editor.alarms()
    assert data2[0]["enabled"] is False
    assert data2[0]["hour"] == 7
    editor.deleteLater()
