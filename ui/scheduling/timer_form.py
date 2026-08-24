# -*- coding: utf-8 -*-
from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app_core.scheduling.text import normalize_unit, unit_label
from ui.widgets.custom_widgets import CustomDropdown

TimerComboBox = CustomDropdown

FORM_LABEL_WIDTH = 120
FORM_VALUE_WIDTH = 100
FORM_UNIT_WIDTH = 88
FORM_TIME_WIDTH = 88
FORM_MODE_WIDTH = 120
FORM_BUTTON_WIDTH = 88
FORM_ROW_SPACING = 8
FORM_TAB_SPACING = 10
FORM_TAB_MARGINS = (16, 16, 16, 16)
FORM_DIALOG_MARGINS = (16, 16, 16, 16)
FORM_DIALOG_SPACING = 12

_SUFFIX_HOUR = " \u65f6"
_SUFFIX_MINUTE = " \u5206"
_REPEAT_LABEL = "\u91cd\u590d\u6a21\u5f0f:"
_ONCE_LABEL = "\u4ec5\u4e00\u6b21"
_DAILY_LABEL = "\u6bcf\u5929"
_STOP_ALL_LABEL = "\u505c\u6b62\u5b9a\u65f6\u5668"
_CANCEL_LABEL = "\u53d6\u6d88"
_OK_LABEL = "\u786e\u5b9a"
_TARGET_LABEL = "\u76ee\u6807\u7a97\u53e3:"
_CHOOSE_WINDOW_LABEL = "\u9009\u62e9\u7a97\u53e3"


class TimerSpinBox(QSpinBox):
    """Spin box that ignores wheel input so form scrolling stays stable."""

    def wheelEvent(self, event):
        event.ignore()


def apply_timer_dialog_font(widget):
    # Keep the app QSS font. Forcing a family here made CJK in spinboxes worse.
    return widget


_WESTERN_DIGITS = QLocale(QLocale.Language.C)


def make_form_label(text):
    label = QLabel(text)
    label.setObjectName("timerFormLabel")
    label.setFixedWidth(FORM_LABEL_WIDTH)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return label


def add_labeled_row(layout, label_text, *widgets):
    row = QHBoxLayout()
    row.setSpacing(FORM_ROW_SPACING)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(make_form_label(label_text), 0, Qt.AlignmentFlag.AlignVCenter)
    for widget in widgets:
        row.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
    row.addStretch(1)
    layout.addLayout(row)
    return row


def new_form_container(parent=None):
    box = QWidget(parent)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(FORM_TAB_SPACING)
    return box, layout


def fit_timer_spinbox(spin, min_width=FORM_VALUE_WIDTH):
    # zh-TW/zh-HK QSpinBox uses Hangzhou numerals (〩 looks like 夕).
    spin.setLocale(_WESTERN_DIGITS)
    spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    spin.setFixedWidth(int(min_width))
    spin.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return spin


def fit_timer_combo(combo, min_width=FORM_UNIT_WIDTH):
    combo.setFixedWidth(int(min_width))
    combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return combo


def fill_unit_combo(combo, units, current, default=None):
    allowed = tuple(units)
    fallback = default or (allowed[0] if allowed else "minutes")
    combo.clear()
    for key in allowed:
        combo.addItem(unit_label(key, default=fallback), key)
    key = normalize_unit(current, default=fallback, allowed=allowed)
    index = combo.findData(key)
    if index >= 0:
        combo.setCurrentIndex(index)
    return combo


def combo_unit_key(combo, default="minutes", allowed=None):
    data = combo.currentData() if hasattr(combo, "currentData") else None
    if data:
        return normalize_unit(data, default=default, allowed=allowed)
    text = combo.currentText() if hasattr(combo, "currentText") else ""
    return normalize_unit(text, default=default, allowed=allowed)


def create_timer_dialog_shell(parent, title, width=600, height=460):
    dialog = QDialog(parent)
    apply_timer_dialog_font(dialog)
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    dialog.setMinimumWidth(560)
    dialog.setMaximumWidth(760)
    dialog.setMinimumHeight(400)
    dialog.setMaximumHeight(560)
    dialog.resize(width, height)
    dialog.setSizeGripEnabled(True)
    main_layout = QVBoxLayout(dialog)
    main_layout.setSpacing(FORM_DIALOG_SPACING)
    main_layout.setContentsMargins(*FORM_DIALOG_MARGINS)
    tab_widget = QTabWidget(dialog)
    main_layout.addWidget(tab_widget, 1)
    return dialog, main_layout, tab_widget


def add_enable_checkbox(layout, text, checked):
    checkbox = QCheckBox(text)
    checkbox.setChecked(bool(checked))
    layout.addWidget(checkbox)
    return checkbox


def add_time_row(layout, parent, label, hour, minute, spinbox_cls=None):
    spinbox_cls = spinbox_cls or TimerSpinBox
    hour_box = spinbox_cls(parent)
    hour_box.setRange(0, 23)
    hour_box.setValue(int(hour))
    hour_box.setSuffix(_SUFFIX_HOUR)
    fit_timer_spinbox(hour_box, FORM_TIME_WIDTH)
    minute_box = spinbox_cls(parent)
    minute_box.setRange(0, 59)
    minute_box.setValue(int(minute))
    minute_box.setSuffix(_SUFFIX_MINUTE)
    fit_timer_spinbox(minute_box, FORM_TIME_WIDTH)
    colon = QLabel(":")
    colon.setFixedWidth(10)
    colon.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
    add_labeled_row(layout, label, hour_box, colon, minute_box)
    return hour_box, minute_box


def add_repeat_row(layout, parent, current, combo_cls=None):
    combo_cls = combo_cls or TimerComboBox
    combo = combo_cls(parent)
    combo.addItem(_ONCE_LABEL, "once")
    combo.addItem(_DAILY_LABEL, "daily")
    fit_timer_combo(combo, FORM_UNIT_WIDTH)
    index = combo.findData(current)
    if index >= 0:
        combo.setCurrentIndex(index)
    add_labeled_row(layout, _REPEAT_LABEL, combo)
    return combo


def add_duration_row(layout, parent, label, value, unit, units, spinbox_cls=None, combo_cls=None):
    spinbox_cls = spinbox_cls or TimerSpinBox
    combo_cls = combo_cls or TimerComboBox
    spin = spinbox_cls(parent)
    spin.setRange(1, 999999)
    spin.setValue(int(value))
    combo = combo_cls(parent)
    fill_unit_combo(combo, units, unit)
    fit_timer_spinbox(spin, FORM_VALUE_WIDTH)
    fit_timer_combo(combo, FORM_UNIT_WIDTH)
    add_labeled_row(layout, label, spin, combo)
    return spin, combo


def add_combo_row(layout, parent, label, items, current=None, combo_cls=None, min_width=FORM_UNIT_WIDTH):
    combo_cls = combo_cls or TimerComboBox
    combo = combo_cls(parent)
    for text, data in items:
        combo.addItem(text, data)
    if current is not None:
        index = combo.findData(current)
        if index >= 0:
            combo.setCurrentIndex(index)
    fit_timer_combo(combo, min_width)
    add_labeled_row(layout, label, combo)
    return combo


def add_spin_row(layout, parent, label, value, minimum, maximum, suffix="", spinbox_cls=None, min_width=FORM_VALUE_WIDTH):
    spinbox_cls = spinbox_cls or TimerSpinBox
    spin = spinbox_cls(parent)
    spin.setRange(int(minimum), int(maximum))
    spin.setValue(int(value))
    if suffix:
        spin.setSuffix(suffix)
    fit_timer_spinbox(spin, min_width)
    add_labeled_row(layout, label, spin)
    return spin


def add_target_row(layout, summary_text, button_text=_CHOOSE_WINDOW_LABEL):
    summary = QLabel(summary_text)
    summary.setObjectName("timerTargetSummary")
    summary.setWordWrap(True)
    summary.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    button = QPushButton(button_text)
    button.setFixedWidth(FORM_BUTTON_WIDTH)
    row = QHBoxLayout()
    row.setSpacing(FORM_ROW_SPACING)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(make_form_label(_TARGET_LABEL), 0, Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(summary, 1, Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
    layout.addLayout(row)
    return summary, button


def add_next_preview_label(layout, text=""):
    label = QLabel(text)
    label.setObjectName("timerHintLabel")
    label.setWordWrap(True)
    row = QHBoxLayout()
    row.setSpacing(FORM_ROW_SPACING)
    row.setContentsMargins(0, 0, 0, 0)
    spacer = QWidget()
    spacer.setFixedWidth(FORM_LABEL_WIDTH)
    row.addWidget(spacer)
    row.addWidget(label, 1)
    layout.addLayout(row)
    return label


def add_timer_dialog_buttons(main_layout):
    button_layout = QHBoxLayout()
    button_layout.setSpacing(FORM_ROW_SPACING)
    button_layout.addStretch()
    stop_all = QPushButton(_STOP_ALL_LABEL)
    cancel_btn = QPushButton(_CANCEL_LABEL)
    ok_btn = QPushButton(_OK_LABEL)
    stop_all.setMinimumWidth(108)
    cancel_btn.setFixedWidth(FORM_BUTTON_WIDTH)
    ok_btn.setFixedWidth(FORM_BUTTON_WIDTH)
    button_layout.addWidget(stop_all)
    button_layout.addWidget(cancel_btn)
    button_layout.addWidget(ok_btn)
    main_layout.addLayout(button_layout)
    return {"stop_all": stop_all, "cancel": cancel_btn, "ok": ok_btn}


def new_tab(tab_widget, title):
    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.setSpacing(FORM_TAB_SPACING)
    layout.setContentsMargins(*FORM_TAB_MARGINS)
    tab_widget.addTab(tab, title)
    return tab, layout
