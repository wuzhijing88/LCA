from __future__ import annotations

import os
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QPushButton

from app_core.maps.record import load_map
from ui.maps import stitcher_dialog
from ui.maps.stitcher_dialog import MapStitcherDialog


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance
    instance.closeAllWindows()
    instance.shutdown()


def _button(dialog: MapStitcherDialog, text: str) -> QPushButton:
    matches = [
        button
        for button in dialog.findChildren(QPushButton)
        if button.text() == text
    ]
    assert len(matches) == 1
    return matches[0]


def test_toolbar_uses_exclusive_mode_buttons_without_combo(app):
    dialog = MapStitcherDialog()
    assert not dialog.findChildren(QComboBox)

    goal = _button(dialog, "终点")
    route = _button(dialog, "线路")
    paint = _button(dialog, "涂墙")
    assert all(button.isCheckable() for button in (goal, route, paint))

    route.click()
    assert route.isChecked()
    assert not goal.isChecked()
    assert not paint.isChecked()
    dialog.close()


def test_capture_crops_minimap_and_appends_tile(app, monkeypatch):
    frame = np.zeros((12, 14, 3), dtype=np.uint8)
    frame[3:8, 2:6] = 73
    monkeypatch.setattr(
        stitcher_dialog,
        "capture_window_smart",
        lambda hwnd: frame if hwnd == 99 else None,
    )
    dialog = MapStitcherDialog(minimap_rect=(2, 3, 4, 5), target_hwnd=99)

    dialog._capture_minimap()

    assert len(dialog._tiles) == 1
    assert dialog._tiles[0].shape == (5, 4, 3)
    assert int(dialog._tiles[0][0, 0, 0]) == 73
    assert dialog._origins == [(0, 0)]
    dialog.close()


def test_save_progress_stays_open_and_complete_accepts(app, monkeypatch):
    saved_records = []

    def fake_apply(record, payload):
        updated = SimpleNamespace(map_id="map-1", name=payload["name"])
        saved_records.append(updated)
        return updated

    monkeypatch.setattr(stitcher_dialog, "apply_editor_payload", fake_apply)
    dialog = MapStitcherDialog()
    dialog._tiles = [np.zeros((6, 7, 3), dtype=np.uint8)]
    dialog._origins = [(0, 0)]
    dialog._goal = (3, 4)
    dialog._name_edit.setText("续编地图")

    assert dialog._save_progress()
    assert dialog.result() == 0
    assert dialog._record is saved_records[-1]
    assert dialog.saved_option == "续编地图 — map-1"

    dialog._complete()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert len(saved_records) == 2


def test_saved_progress_can_be_loaded_for_resume(app, monkeypatch, tmp_path):
    monkeypatch.setenv("LCA_USER_DATA_DIR", str(tmp_path))
    dialog = MapStitcherDialog()
    dialog._tiles = [np.full((6, 7, 3), 25, dtype=np.uint8)]
    dialog._origins = [(0, 0)]
    dialog._goal = (3, 4)
    dialog._name_edit.setText("可续编地图")

    assert dialog._save_progress()
    map_id = dialog._record.map_id
    dialog.close()

    resumed = MapStitcherDialog(record=load_map(map_id))
    assert resumed._name_edit.text() == "可续编地图"
    assert resumed._goal == (3, 4)
    assert len(resumed._tiles) == 1
    assert int(resumed._tiles[0][0, 0, 0]) == 25
    resumed.close()
