# -*- coding: utf-8 -*-
from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app_core.scheduling.text import normalize_unit, unit_label

_SUFFIX_HOUR = " \u65f6"
_SUFFIX_MINUTE = " \u5206"
_REPEAT_LABEL = "\u91cd\u590d\u6a21\u5f0f:"
_ONCE_LABEL = "\u4ec5\u4e00\u6b21"
_DAILY_LABEL = "\u6bcf\u5929"
_STOP_ALL_LABEL = "\u505c\u6b62\u5b9a\u65f6\u5668"
_CANCEL_LABEL = "\u53d6\u6d88"
_OK_LABEL = "\u786e\u5b9a"


def apply_timer_dialog_font(widget):
    # Keep the app QSS font. Forcing a family here made CJK in spinboxes worse.
    return widget


_WESTERN_DIGITS = QLocale(QLocale.Language.C)


def fit_timer_spinbox(spin, min_width=100):
    # zh-TW/zh-HK QSpinBox uses Hangzhou numerals (〩 looks like 夕).
    spin.setLocale(_WESTERN_DIGITS)
    spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    hint_width = spin.sizeHint().width()
    spin.setMinimumWidth(max(min_width, hint_width + 20))
    return spin


def fit_timer_combo(combo, min_width=84):
    combo.setMinimumWidth(min_width)
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


def create_timer_dialog_shell(parent, title, width=620, height=440):
    dialog = QDialog(parent)
    apply_timer_dialog_font(dialog)
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    dialog.setMinimumWidth(560)
    dialog.setMaximumWidth(820)
    dialog.setMinimumHeight(380)
    dialog.setMaximumHeight(620)
    dialog.resize(width, height)
    dialog.setSizeGripEnabled(True)
    main_layout = QVBoxLayout(dialog)
    main_layout.setSpacing(10)
    main_layout.setContentsMargins(15, 15, 15, 15)
    tab_widget = QTabWidget(dialog)
    main_layout.addWidget(tab_widget)
    return dialog, main_layout, tab_widget


def add_enable_checkbox(layout, text, checked):
    checkbox = QCheckBox(text)
    checkbox.setChecked(bool(checked))
    layout.addWidget(checkbox)
    return checkbox


def add_time_row(layout, parent, label, hour, minute, spinbox_cls=None):
    spinbox_cls = spinbox_cls or QSpinBox
    row = QHBoxLayout()
    row.addWidget(QLabel(label))
    hour_box = spinbox_cls(parent)
    hour_box.setRange(0, 23)
    hour_box.setValue(int(hour))
    hour_box.setSuffix(_SUFFIX_HOUR)
    fit_timer_spinbox(hour_box)
    minute_box = spinbox_cls(parent)
    minute_box.setRange(0, 59)
    minute_box.setValue(int(minute))
    minute_box.setSuffix(_SUFFIX_MINUTE)
    fit_timer_spinbox(minute_box)
    row.addWidget(hour_box)
    row.addWidget(QLabel(":"))
    row.addWidget(minute_box)
    row.addStretch(1)
    layout.addLayout(row)
    return hour_box, minute_box


def add_repeat_row(layout, parent, current, combo_cls=None):
    combo_cls = combo_cls or QComboBox
    row = QHBoxLayout()
    row.addWidget(QLabel(_REPEAT_LABEL))
    combo = combo_cls(parent)
    combo.addItem(_ONCE_LABEL, "once")
    combo.addItem(_DAILY_LABEL, "daily")
    fit_timer_combo(combo)
    index = combo.findData(current)
    if index >= 0:
        combo.setCurrentIndex(index)
    row.addWidget(combo)
    row.addStretch(1)
    layout.addLayout(row)
    return combo


def add_duration_row(layout, parent, label, value, unit, units, spinbox_cls=None, combo_cls=None):
    spinbox_cls = spinbox_cls or QSpinBox
    combo_cls = combo_cls or QComboBox
    row = QHBoxLayout()
    row.addWidget(QLabel(label))
    spin = spinbox_cls(parent)
    spin.setRange(1, 999999)
    spin.setValue(int(value))
    combo = combo_cls(parent)
    fill_unit_combo(combo, units, unit)
    fit_timer_spinbox(spin, min_width=80)
    fit_timer_combo(combo, min_width=72)
    row.addWidget(spin)
    row.addWidget(combo)
    row.addStretch(1)
    layout.addLayout(row)
    return spin, combo


def add_next_preview_label(layout, text=""):
    label = QLabel(text)
    label.setWordWrap(True)
    layout.addWidget(label)
    return label


def add_timer_dialog_buttons(main_layout):
    button_layout = QHBoxLayout()
    button_layout.addStretch()
    stop_all = QPushButton(_STOP_ALL_LABEL)
    cancel_btn = QPushButton(_CANCEL_LABEL)
    ok_btn = QPushButton(_OK_LABEL)
    button_layout.addWidget(stop_all)
    button_layout.addWidget(cancel_btn)
    button_layout.addWidget(ok_btn)
    main_layout.addLayout(button_layout)
    return {"stop_all": stop_all, "cancel": cancel_btn, "ok": ok_btn}


def new_tab(tab_widget, title):
    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.setSpacing(10)
    layout.setContentsMargins(10, 10, 10, 10)
    tab_widget.addTab(tab, title)
    return tab, layout
