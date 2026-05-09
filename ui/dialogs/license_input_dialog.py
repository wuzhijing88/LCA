import logging

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app_core.plugin_activation_service import validate_plugin_license_key

logger = logging.getLogger(__name__)


class _LicenseValidationWorker(QThread):
    validation_finished = Signal(bool, int, str, str)

    def __init__(self, hardware_id: str, license_key: str, session: object, parent=None):
        super().__init__(parent)
        self.hardware_id = str(hardware_id or "").strip()
        self.license_key = str(license_key or "").strip()
        self.session = session

    def run(self):
        try:
            result = validate_plugin_license_key(
                hardware_id=self.hardware_id,
                license_key=self.license_key,
                session=self.session,
            )
            self.validation_finished.emit(
                result.success,
                result.status_code,
                result.message,
                result.license_type,
            )
        except Exception as exc:
            logger.error(f"许可证校验工作线程失败：{exc}", exc_info=True)
            self.validation_finished.emit(
                False,
                0,
                f"\u6388\u6743\u9a8c\u8bc1\u8fc7\u7a0b\u4e2d\u53d1\u751f\u5f02\u5e38\uff1a{exc}",
                "unknown",
            )


class LicenseInputDialog(QDialog):
    def __init__(self, hardware_id: str, http_session: object = None, parent=None):
        super().__init__(parent)
        self.hardware_id = str(hardware_id or "").strip()
        self.http_session = http_session
        self._validated_license_key = ""
        self._validation_worker = None

        self.setWindowTitle("\u63d2\u4ef6\u6388\u6743\u9a8c\u8bc1")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        intro_label = QLabel(
            "\u8bf7\u8f93\u5165\u6388\u6743\u7801\u5e76\u5b8c\u6210\u5728\u7ebf\u9a8c\u8bc1\u3002"
            "\u9a8c\u8bc1\u901a\u8fc7\u540e\u4f1a\u4fdd\u5b58\u5230\u672c\u5730\u6388\u6743\u7f13\u5b58\u3002"
        )
        intro_label.setWordWrap(True)
        layout.addWidget(intro_label)

        hardware_layout = QHBoxLayout()
        hardware_title = QLabel("\u673a\u5668\u7801")
        hardware_title.setMinimumWidth(56)
        self.hardware_value_label = QLabel(self._format_hardware_id(self.hardware_id))
        self.hardware_value_label.setTextInteractionFlags(
            self.hardware_value_label.textInteractionFlags()
        )
        hardware_layout.addWidget(hardware_title)
        hardware_layout.addWidget(self.hardware_value_label, 1)
        layout.addLayout(hardware_layout)

        key_layout = QVBoxLayout()
        key_label = QLabel("\u6388\u6743\u7801")
        self.license_key_edit = QLineEdit()
        self.license_key_edit.setPlaceholderText("\u8bf7\u8f93\u5165\u6388\u6743\u7801")
        self.license_key_edit.returnPressed.connect(self._start_validation)
        key_layout.addWidget(key_label)
        key_layout.addWidget(self.license_key_edit)
        layout.addLayout(key_layout)

        self.status_label = QLabel("\u7b49\u5f85\u8f93\u5165\u6388\u6743\u7801\u3002")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.cancel_button = self.button_box.button(QDialogButtonBox.StandardButton.Cancel)
        self.ok_button.setText("\u9a8c\u8bc1\u5e76\u4fdd\u5b58")
        self.cancel_button.setText("\u53d6\u6d88")
        self.button_box.accepted.connect(self._start_validation)
        self.button_box.rejected.connect(self.reject)

        self.retry_button = QPushButton("\u91cd\u8bd5")
        self.retry_button.setVisible(False)
        self.retry_button.clicked.connect(self._start_validation)
        self.button_box.addButton(self.retry_button, QDialogButtonBox.ButtonRole.ActionRole)

        layout.addWidget(self.button_box)

    @staticmethod
    def _format_hardware_id(hardware_id: str) -> str:
        value = str(hardware_id or "").strip()
        if len(value) <= 20:
            return value or "\u672a\u83b7\u53d6"
        return f"{value[:12]}...{value[-8:]}"

    def _set_busy(self, busy: bool, message: str) -> None:
        self.license_key_edit.setEnabled(not busy)
        self.ok_button.setEnabled(not busy)
        self.cancel_button.setEnabled(not busy)
        self.retry_button.setVisible(not busy and self.retry_button.isVisible())
        self.status_label.setText(message)

    def _start_validation(self) -> None:
        if self._validation_worker is not None and self._validation_worker.isRunning():
            return

        license_key = self.license_key_edit.text().strip()
        if not license_key:
            self.retry_button.setVisible(False)
            self.status_label.setText("\u8bf7\u8f93\u5165\u6388\u6743\u7801\u3002")
            QMessageBox.warning(
                self,
                "\u6388\u6743\u7801\u4e3a\u7a7a",
                "\u8bf7\u8f93\u5165\u6388\u6743\u7801\u540e\u518d\u9a8c\u8bc1\u3002",
            )
            return

        self.retry_button.setVisible(False)
        self._set_busy(True, "\u6b63\u5728\u9a8c\u8bc1\u6388\u6743\uff0c\u8bf7\u7a0d\u5019...")

        worker = _LicenseValidationWorker(
            hardware_id=self.hardware_id,
            license_key=license_key,
            session=self.http_session,
            parent=self,
        )
        worker.validation_finished.connect(self._on_validation_finished)
        worker.finished.connect(worker.deleteLater)
        self._validation_worker = worker
        worker.start()

    def _on_validation_finished(self, success: bool, status_code: int, message: str, license_type: str) -> None:
        self._validation_worker = None
        self.license_key_edit.setEnabled(True)
        self.ok_button.setEnabled(True)
        self.cancel_button.setEnabled(True)

        if success:
            self._validated_license_key = self.license_key_edit.text().strip()
            self.status_label.setText(message)
            logger.info(f"license dialog validation succeeded: {license_type}")
            self.accept()
            return

        self.retry_button.setVisible(True)
        self.status_label.setText(message)
        logger.warning(f"许可证弹窗校验失败：{status_code}")
        QMessageBox.warning(self, "\u6388\u6743\u9a8c\u8bc1\u5931\u8d25", message)

    def get_license_key(self) -> str:
        return self._validated_license_key or self.license_key_edit.text().strip()
