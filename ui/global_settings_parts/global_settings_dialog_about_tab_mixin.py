from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app_core.app_config import (
    APP_EDITION,
    APP_LICENSE_NAME,
    APP_NAME,
    APP_SUMMARY,
    app_source_url,
)
from ..main_window_parts.main_window_support import get_secondary_text_color, get_theme_color


def _about_label(text: str, *, color: str, size: int, weight: int = 400) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"color: {color}; font-size: {size}px; font-weight: {weight}; background: transparent;"
    )
    return label


class GlobalSettingsDialogAboutTabMixin:
    def _create_about_tab(self):
        about_tab = QWidget()
        about_layout = QVBoxLayout(about_tab)
        about_layout.setSpacing(0)
        about_layout.setContentsMargins(20, 18, 20, 14)

        text = get_theme_color("text", "#333333")
        secondary = get_secondary_text_color()
        border = get_theme_color("border", "#e0e0e0")
        surface = get_theme_color("surface", "#f5f5f5")

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        self.about_name_label = _about_label(APP_NAME, color=text, size=22, weight=600)
        self.about_edition_label = _about_label(APP_EDITION, color=get_theme_color("accent", "#0078d4"), size=11)
        self.about_edition_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.about_edition_label.setStyleSheet(
            f"color: {get_theme_color('accent', '#0078d4')};"
            f"background-color: {surface};"
            f"border: 1px solid {border};"
            "border-radius: 3px;"
            "padding: 2px 8px;"
            "font-size: 11px;"
        )
        header.addWidget(self.about_name_label, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.about_edition_label, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()
        about_layout.addLayout(header)

        summary_label = _about_label(APP_SUMMARY, color=secondary, size=12)
        summary_label.setWordWrap(True)
        summary_label.setContentsMargins(0, 8, 0, 0)
        about_layout.addWidget(summary_label)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {border}; border: none;")
        about_layout.addSpacing(16)
        about_layout.addWidget(divider)
        about_layout.addSpacing(16)

        about_layout.addWidget(_about_label("开源仓库", color=secondary, size=11))
        about_layout.addSpacing(6)

        repo_field = QFrame()
        repo_field.setObjectName("aboutRepoField")
        repo_field.setStyleSheet(
            f"QFrame#aboutRepoField {{"
            f"background-color: {surface};"
            f"border: 1px solid {border};"
            "border-radius: 4px;"
            "}"
        )
        repo_layout = QHBoxLayout(repo_field)
        repo_layout.setContentsMargins(10, 6, 6, 6)
        repo_layout.setSpacing(8)
        self.about_source_label = QLabel(app_source_url())
        self.about_source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.about_source_label.setWordWrap(False)
        self.about_source_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.about_source_label.setToolTip("开源仓库地址，可选择复制")
        self.about_source_label.setStyleSheet(f"color: {text}; font-size: 12px; background: transparent; border: none;")
        self.about_open_source_button = QPushButton("打开仓库")
        self.about_open_source_button.setFixedWidth(80)
        self.about_open_source_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.about_open_source_button.setToolTip("使用系统浏览器打开开源仓库")
        self.about_open_source_button.setProperty("primary", True)
        self.about_open_source_button.style().unpolish(self.about_open_source_button)
        self.about_open_source_button.style().polish(self.about_open_source_button)
        self.about_open_source_button.clicked.connect(self._open_source_repository)
        self.about_copy_source_button = QPushButton("复制地址")
        self.about_copy_source_button.setFixedWidth(80)
        self.about_copy_source_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.about_copy_source_button.setToolTip("复制完整开源地址到剪贴板")
        self.about_copy_source_button.clicked.connect(self._copy_source_repository)
        repo_layout.addWidget(self.about_source_label, 1)
        repo_layout.addWidget(self.about_open_source_button)
        repo_layout.addWidget(self.about_copy_source_button)
        about_layout.addWidget(repo_field)

        about_layout.addSpacing(16)
        about_layout.addWidget(_about_label("许可证", color=secondary, size=11))
        about_layout.addSpacing(4)
        self.about_license_label = _about_label(APP_LICENSE_NAME, color=text, size=12)
        self.about_license_label.setWordWrap(True)
        about_layout.addWidget(self.about_license_label)

        license_note = _about_label("对应源码通过上述仓库提供。", color=secondary, size=11)
        license_note.setContentsMargins(0, 4, 0, 0)
        about_layout.addWidget(license_note)
        about_layout.addStretch()
        self.tab_widget.addTab(about_tab, "关于")

    def _open_source_repository(self):
        QDesktopServices.openUrl(QUrl(app_source_url()))

    def _copy_source_repository(self):
        QApplication.clipboard().setText(app_source_url())
        self.about_copy_source_button.setText("已复制")
        self.about_copy_source_button.setEnabled(False)

        def restore():
            try:
                self.about_copy_source_button.setText("复制地址")
                self.about_copy_source_button.setEnabled(True)
            except RuntimeError:
                return

        QTimer.singleShot(1500, restore)
