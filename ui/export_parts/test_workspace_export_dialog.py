import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidgetItem

from ui.export_parts.workspace_export_dialog import WorkspaceExportPickerDialog


def _qapp():
    return QApplication.instance() or QApplication([])


def test_picker_requires_at_least_one():
    _qapp()
    catalog = [
        {"id": "a", "title": "A", "filepath": r"D:\ws\a.lca"},
        {"id": "b", "title": "B", "filepath": r"D:\ws\b.lca"},
    ]
    dlg = WorkspaceExportPickerDialog(catalog)
    for i in range(dlg._list.count()):
        item = dlg._list.item(i)
        item.setCheckState(Qt.CheckState.Unchecked)
    assert dlg._can_accept() is False
    assert dlg._ok_btn.isEnabled() is False
    dlg._list.item(0).setCheckState(Qt.CheckState.Checked)
    dlg._refresh_ok()
    assert dlg._can_accept() is True
    dlg.close()


def test_picker_returns_checked_subset_preserving_order():
    _qapp()
    catalog = [
        {"id": "a", "title": "A", "filepath": "a.lca", "workflow_data": {"cards": [1]}},
        {"id": "b", "title": "B", "filepath": "b.lca", "workflow_data": {"cards": [2]}},
        {"id": "c", "title": "C", "filepath": "c.lca", "workflow_data": {"cards": [3]}},
    ]
    dlg = WorkspaceExportPickerDialog(catalog, preselected_ids={"a", "c"})
    selected = dlg.selected_catalog()
    assert [item["id"] for item in selected] == ["a", "c"]
    assert selected[0]["title"] == "A"
    dlg.close()


def test_picker_defaults_all_checked_when_no_preselect():
    _qapp()
    catalog = [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}]
    dlg = WorkspaceExportPickerDialog(catalog)
    assert {dlg._list.item(i).checkState() for i in range(dlg._list.count())} == {
        Qt.CheckState.Checked
    }
    assert [x["id"] for x in dlg.selected_catalog()] == ["a", "b"]
    dlg.close()
