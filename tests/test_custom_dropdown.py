import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from ui.scheduling.timer_form import (
    FORM_LABEL_WIDTH,
    FORM_TIME_WIDTH,
    FORM_UNIT_WIDTH,
    FORM_VALUE_WIDTH,
    TimerComboBox,
    add_duration_row,
    add_repeat_row,
    add_spin_row,
    add_time_row,
)
from ui.widgets.custom_widgets import CustomDropdown


class CustomDropdownEditableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_editable_api_matches_combobox(self):
        widget = CustomDropdown()
        widget.addItem("选项A", "选项A")
        widget.setEditable(True)
        self.assertTrue(widget.isEditable())
        self.assertTrue(hasattr(widget, "editTextChanged"))
        self.assertIsNotNone(widget.lineEdit())

        received = []
        widget.editTextChanged.connect(received.append)
        widget.setEditText("自定义文本")
        self.assertEqual(widget.currentText(), "自定义文本")

        widget.lineEdit().setText("另一段文本")
        self.assertEqual(widget.currentText(), "另一段文本")
        self.assertIn("另一段文本", received)
        widget.deleteLater()


class TimerDialogDropdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_timer_form_uses_themed_dropdown(self):
        parent = QWidget()
        layout = QVBoxLayout(parent)

        repeat = add_repeat_row(layout, parent, "daily")
        self.assertIsInstance(repeat, TimerComboBox)
        self.assertIsInstance(repeat, CustomDropdown)
        self.assertEqual(repeat.currentData(), "daily")

        _spin, unit = add_duration_row(
            layout, parent, "时长:", 5, "minutes", ("minutes", "seconds")
        )
        self.assertIsInstance(unit, CustomDropdown)
        self.assertEqual(unit.currentData(), "minutes")
        parent.deleteLater()

    def test_timer_form_rows_share_label_and_field_columns(self):
        parent = QWidget()
        parent.resize(560, 360)
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        hour, minute = add_time_row(layout, parent, "启动时间:", 8, 30)
        repeat = add_repeat_row(layout, parent, "daily")
        spin, unit = add_duration_row(
            layout, parent, "暂停最小时长:", 5, "minutes", ("minutes", "seconds")
        )
        probability = add_spin_row(layout, parent, "触发概率:", 20, 0, 100, suffix=" %")

        parent.show()
        self.app.processEvents()

        labels = [
            widget
            for widget in parent.findChildren(QLabel)
            if widget.objectName() == "timerFormLabel"
        ]
        self.assertEqual(len(labels), 4)
        self.assertEqual({label.width() for label in labels}, {FORM_LABEL_WIDTH})

        field_xs = {
            hour.mapTo(parent, hour.rect().topLeft()).x(),
            repeat.mapTo(parent, repeat.rect().topLeft()).x(),
            spin.mapTo(parent, spin.rect().topLeft()).x(),
            probability.mapTo(parent, probability.rect().topLeft()).x(),
        }
        self.assertEqual(len(field_xs), 1)
        self.assertEqual(hour.width(), FORM_TIME_WIDTH)
        self.assertEqual(minute.width(), FORM_TIME_WIDTH)
        self.assertEqual(repeat.width(), FORM_UNIT_WIDTH)
        self.assertEqual(spin.width(), FORM_VALUE_WIDTH)
        self.assertEqual(unit.width(), FORM_UNIT_WIDTH)
        self.assertEqual(probability.width(), FORM_VALUE_WIDTH)
        parent.deleteLater()


if __name__ == "__main__":
    unittest.main()
