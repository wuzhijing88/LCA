# -*- coding: utf-8 -*-
"""独立的 AI 助手窗口，不占用右侧参数面板。"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QBuffer, QEvent, QIODevice, QObject, QUrl, Qt, QThread, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
    QGuiApplication,
    QImage,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app_core.ai_assistant import (
    AI_IMAGE_MIMES,
    AI_WORKFLOW_EXTS,
    AIProviderConfig,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    FILE_ONLY_PROMPT,
    MAX_AI_IMAGE_BYTES,
    MAX_AI_IMAGES_PER_TURN,
    MAX_AI_WORKFLOW_FILE_BYTES,
    MAX_AI_WORKFLOW_FILES_PER_TURN,
    REVIEW_WORKFLOW_PROMPT,
    attachable_image_mime,
    attachable_workflow_suffix,
    build_ai_chat_messages,
    complete_ai_chat,
    chat_system_prompt,
    editor_task_types,
    editor_workflow_bundle,
    format_uploaded_workflows_context,
    load_ai_provider_settings,
    normalize_ai_base_url,
    proposal_source_workflow,
    save_ai_provider_settings,
    uploaded_workflow_for_apply,
)
from app_core.ai_workflow import (
    apply_editor_workflow,
    build_workflow_from_proposal,
    parse_workflow_proposal,
    write_workflow_lca,
)
from app_core.lca_format.constants import LCA_EXTENSION, LCA_SAVE_FILTER
from app_core.ai_chat_format import format_ai_thinking_html, format_ai_transcript_html
from app_core.ai_sessions import (
    append_message,
    chat_history,
    create_session,
    delete_session,
    get_session,
    latest_attached_files,
    latest_user_files,
    load_ai_sessions,
    rename_session,
    save_ai_sessions,
    set_current_session,
    write_session_files,
    write_session_images,
)
from utils.window.window_activation_utils import show_and_raise_widget
from utils.window.window_coordinate_common import (
    center_window_on_widget_screen,
    clamp_preferred_window_size,
    get_available_geometry_for_widget,
)

logger = logging.getLogger(__name__)
SETTINGS_VISIBLE_KEY = "ai/settings_visible"
GEOMETRY_KEY = "ai/window_geometry"
_IMAGE_FILE_FILTER = "图片 (*.png *.jpg *.jpeg *.webp *.gif);;所有文件 (*.*)"
_WORKFLOW_FILE_FILTER = "工作流 (*.json *.lca)"
_PREVIEW_MIN_SCALE = 0.05
_PREVIEW_MAX_SCALE = 16.0
_PREVIEW_ZOOM_STEP = 1.15


class _AIWorker(QThread):
    completed = Signal(str, str)
    failed = Signal(str)
    progressed = Signal(str)

    def __init__(self, config: AIProviderConfig, messages, parent=None):
        super().__init__(parent)
        self._config = config
        self._messages = messages

    def run(self) -> None:
        try:
            text, thinking = complete_ai_chat(
                self._config,
                self._messages,
                progress=self.progressed.emit,
            )
            self.completed.emit(text, thinking)
        except Exception as exc:
            self.failed.emit(str(exc))


class _AIPromptEnterFilter(QObject):
    def eventFilter(self, watched, event) -> bool:
        dialog = self.parent()
        event_type = event.type()
        if event_type in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if dialog is not None and dialog.can_accept_drop_mime(event.mimeData()):
                event.acceptProposedAction()
                return True
            return False
        if event_type == QEvent.Type.Drop:
            if dialog is not None and dialog.attach_from_mime(event.mimeData()):
                event.acceptProposedAction()
                return True
            return False
        if event_type != QEvent.Type.KeyPress:
            return False
        if event.matches(QKeySequence.StandardKey.Paste):
            mime = QGuiApplication.clipboard().mimeData()
            if dialog is None or mime is None:
                return False
            paths = [url.toLocalFile() for url in (mime.urls() or []) if url.toLocalFile()]
            image_paths = [
                path for path in paths
                if os.path.splitext(path)[1].lower() in AI_IMAGE_MIMES
            ]
            workflow_paths = [
                path for path in paths
                if os.path.splitext(path)[1].lower() in AI_WORKFLOW_EXTS
            ]
            if image_paths or workflow_paths or (mime.hasImage() and not mime.hasText()):
                dialog.attach_from_mime(mime)
                return True
            return False
        if event.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return False
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            return False
        if dialog is not None and hasattr(dialog, "send_current_prompt"):
            dialog.send_current_prompt()
            return True
        return False


class _ClickableThumb(QLabel):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class _PreviewHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiImagePreviewHeader")
        self._drag_offset = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class AIImagePreviewView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiImagePreviewView")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = None
        self._fitted = False

    def load_pixmap(self, pixmap: QPixmap) -> None:
        self._scene.clear()
        self._item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(self._item.boundingRect())
        self.resetTransform()
        self._fitted = False

    def current_scale(self) -> float:
        return abs(self.transform().m11())

    def fit_image(self) -> None:
        if self._item is None:
            return
        self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)
        self._fitted = True

    def zoom_by(self, factor: float) -> None:
        if factor <= 0:
            return
        scale = self.current_scale() * factor
        if scale < _PREVIEW_MIN_SCALE or scale > _PREVIEW_MAX_SCALE:
            return
        self.scale(factor, factor)
        self._fitted = False

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        self.zoom_by(_PREVIEW_ZOOM_STEP if delta > 0 else 1 / _PREVIEW_ZOOM_STEP)
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fitted:
            self.fit_image()


class AIImagePreviewDialog(QDialog):
    """原图预览：滚轮缩放，右上角 × 关闭。"""

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.setObjectName("aiImagePreviewDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("图片")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setMinimumSize(360, 280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)

        header = _PreviewHeader(self)
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(0, 0, 0, 4)
        header_row.setSpacing(0)
        header_row.addStretch(1)
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("aiImagePreviewClose")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.clicked.connect(self.close)
        header_row.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(header)

        self.image_view = AIImagePreviewView(self)
        layout.addWidget(self.image_view, 1)

        self._apply_theme_chrome()
        self._register_theme_callback()
        self.load_pixmap(pixmap)
        self._place_window(parent)

    def load_pixmap(self, pixmap: QPixmap) -> None:
        self.image_view.load_pixmap(pixmap)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_theme_chrome()
        self.image_view.fit_image()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def _place_window(self, parent) -> None:
        available = get_available_geometry_for_widget(parent or self)
        pixmap = self.image_view._item.pixmap() if self.image_view._item is not None else QPixmap()
        preferred_w = int(pixmap.width() or 640) + 24
        preferred_h = int(pixmap.height() or 480) + 52
        width, height = clamp_preferred_window_size(
            min(max(preferred_w, 480), int(available.width() * 0.9)),
            min(max(preferred_h, 360), int(available.height() * 0.9)),
            available,
        )
        self.resize(width, height)
        center_window_on_widget_screen(self, parent)

    def _apply_theme_chrome(self) -> None:
        from themes.rounded_popup import MENU_RADIUS, apply_native_window_corners, apply_rounded_popup

        apply_rounded_popup(
            self,
            radius=MENU_RADIUS,
            border_key="border",
            frameless=False,
            force_window=True,
            paint=True,
        )
        apply_native_window_corners(self)

    def _register_theme_callback(self) -> None:
        try:
            from themes import get_theme_manager

            get_theme_manager().register_theme_change_callback(self._on_theme_changed)
        except Exception:
            return

        def _forget(_=None, callback=self._on_theme_changed) -> None:
            try:
                from themes import get_theme_manager

                get_theme_manager().unregister_theme_change_callback(callback)
            except Exception:
                pass

        self.destroyed.connect(_forget)

    def _on_theme_changed(self, _theme=None) -> None:
        widgets = [self, *self.findChildren(QWidget)]
        style = self.style()
        for widget in widgets:
            style.unpolish(widget)
            style.polish(widget)
            widget.update()
        self._apply_theme_chrome()


def _widget_alive(widget) -> bool:
    if widget is None:
        return False
    try:
        from shiboken6 import isValid

        return bool(isValid(widget))
    except Exception:
        try:
            widget.objectName()
            return True
        except RuntimeError:
            return False


def open_ai_assistant_dialog(main_window):
    existing = getattr(main_window, "_ai_assistant_dialog", None) if main_window is not None else None
    if _widget_alive(existing):
        existing.refresh_for_main_window(main_window)
        show_and_raise_widget(existing, log_prefix="AI 助手")
        existing.activateWindow()
        return existing
    dialog = AIAssistantDialog(main_window)
    if main_window is not None:
        main_window._ai_assistant_dialog = dialog

        def _forget(_result=0, window=main_window, assistant=dialog) -> None:
            if getattr(window, "_ai_assistant_dialog", None) is assistant:
                window._ai_assistant_dialog = None

        dialog.finished.connect(_forget)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog


class AIAssistantDialog(QDialog):
    """左侧会话、右侧对话，服务设置默认收起。"""

    def __init__(self, main_window=None):
        super().__init__(main_window)
        self.main_window = main_window
        self._store: Dict[str, Any] = {}
        self._session_id = ""
        self._loading_session = False
        self._worker: Optional[_AIWorker] = None
        self._copy_payloads: List[str] = []
        self._image_paths: List[str] = []
        self._image_preview: Optional[AIImagePreviewDialog] = None
        self._pending_images: List[Dict[str, Any]] = []
        self._pending_files: List[Dict[str, Any]] = []
        self._thinking_live = False
        self._prompt_filter = _AIPromptEnterFilter(self)
        self._build_ui()
        self._load_sessions()
        self._load_provider_into_form()
        self._refresh_session_list()
        self._render_chat()
        self._register_theme_callback()

    def refresh_for_main_window(self, main_window=None) -> None:
        if main_window is not None:
            self.main_window = main_window

    def _build_ui(self) -> None:
        self.setObjectName("aiAssistantDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("AI 助手")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setAcceptDrops(True)
        self.setMinimumSize(820, 540)
        available = get_available_geometry_for_widget(self.parentWidget() or self)
        width, height = clamp_preferred_window_size(980, 680, available)
        self.resize(width, height)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(self._build_header())
        layout.addWidget(self._build_settings_panel())
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("aiAssistantSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_session_panel())
        splitter.addWidget(self._build_chat_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 740])
        layout.addWidget(splitter, 1)
        if not self._restore_geometry():
            center_window_on_widget_screen(self, self.parentWidget())

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        title = QLabel("AI 助手")
        title.setObjectName("aiAssistantTitle")
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        self.settings_button = QPushButton("设置")
        self.settings_button.setCheckable(True)
        self.settings_button.setChecked(self._load_settings_visible())
        self.settings_button.clicked.connect(self._toggle_settings)
        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(self.settings_button)
        return row

    def _build_settings_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("aiSettingsPanel")
        form = QFormLayout(panel)
        form.setContentsMargins(0, 0, 0, 4)
        form.setSpacing(6)
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText(DEFAULT_BASE_URL)
        self.base_url_edit.editingFinished.connect(self._complete_base_url)
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText(DEFAULT_MODEL)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("只保存在本机，不写入工作流")
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 300)
        self.timeout_spin.setValue(90)
        form.addRow("服务地址", self.base_url_edit)
        form.addRow("模型", self.model_edit)
        form.addRow("API Key", self.api_key_edit)
        form.addRow("超时(秒)", self.timeout_spin)
        self.settings_panel = panel
        panel.setVisible(self.settings_button.isChecked())
        return panel

    def _build_session_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("aiSessionPanel")
        panel.setMinimumWidth(180)
        panel.setMaximumWidth(280)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(6)
        heading = QLabel("会话")
        heading.setObjectName("aiSessionHeading")
        heading_font = heading.font()
        heading_font.setBold(True)
        heading.setFont(heading_font)
        self.session_list = QListWidget()
        self.session_list.setObjectName("aiSessionList")
        self.session_list.currentItemChanged.connect(self._on_session_item_changed)
        new_button = QPushButton("新建")
        rename_button = QPushButton("改名")
        delete_button = QPushButton("删除")
        new_button.clicked.connect(self._on_new_session)
        rename_button.clicked.connect(self._on_rename_session)
        delete_button.clicked.connect(self._on_delete_session)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(4)
        buttons.addWidget(new_button)
        buttons.addWidget(rename_button)
        buttons.addWidget(delete_button)
        layout.addWidget(heading)
        layout.addWidget(self.session_list, 1)
        layout.addLayout(buttons)
        self._session_buttons = (new_button, rename_button, delete_button)
        return panel

    def _build_chat_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("aiChatPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(8)
        self.chat_view = QTextBrowser()
        self.chat_view.setObjectName("aiChatView")
        self.chat_view.setReadOnly(True)
        self.chat_view.setOpenExternalLinks(False)
        self.chat_view.setOpenLinks(False)
        self.chat_view.setMinimumHeight(260)
        self.chat_view.document().setDefaultStyleSheet(
            "p { margin-top: 0px; margin-bottom: 0px; }"
            "pre { margin-top: 0px; margin-bottom: 0px; }"
            "a { text-decoration: none; }"
        )
        self.chat_view.anchorClicked.connect(self._on_chat_anchor)
        layout.addWidget(self.chat_view, 1)
        self.image_strip = QWidget()
        self.image_strip.setObjectName("aiImageStrip")
        self.image_strip_layout = QHBoxLayout(self.image_strip)
        self.image_strip_layout.setContentsMargins(0, 0, 0, 0)
        self.image_strip_layout.setSpacing(8)
        self.image_strip.setVisible(False)
        layout.addWidget(self.image_strip)
        self.file_strip = QWidget()
        self.file_strip.setObjectName("aiFileStrip")
        self.file_strip_layout = QHBoxLayout(self.file_strip)
        self.file_strip_layout.setContentsMargins(0, 0, 0, 0)
        self.file_strip_layout.setSpacing(8)
        self.file_strip.setVisible(False)
        layout.addWidget(self.file_strip)
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setObjectName("aiPromptEdit")
        self.prompt_edit.setPlaceholderText(
            "输入问题，Enter 发送，Shift+Enter 换行。可添加、粘贴或拖入图片，或上传 .json / .lca 工作流。也可点「审查工作流」。"
        )
        self.prompt_edit.setFixedHeight(92)
        self.prompt_edit.setAcceptDrops(True)
        self.prompt_edit.installEventFilter(self._prompt_filter)
        layout.addWidget(self.prompt_edit)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel("")
        self.status_label.setObjectName("aiAssistantStatus")
        self.status_label.setWordWrap(True)
        self.image_button = QPushButton("图片")
        self.image_button.clicked.connect(self._on_pick_images)
        self.file_button = QPushButton("文件")
        self.file_button.clicked.connect(self._on_pick_files)
        self.review_button = QPushButton("审查工作流")
        self.review_button.clicked.connect(self.review_current_workflow)
        self.send_button = QPushButton("发送")
        self.send_button.setProperty("primary", True)
        self.send_button.clicked.connect(self.send_current_prompt)
        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.image_button)
        footer.addWidget(self.file_button)
        footer.addWidget(self.review_button)
        footer.addWidget(self.send_button)
        layout.addLayout(footer)
        return panel

    def _register_theme_callback(self) -> None:
        try:
            from themes import get_theme_manager

            get_theme_manager().register_theme_change_callback(self._on_theme_changed)
        except Exception:
            return

        def _forget(_=None, callback=self._on_theme_changed) -> None:
            try:
                from themes import get_theme_manager

                get_theme_manager().unregister_theme_change_callback(callback)
            except Exception:
                pass

        self.destroyed.connect(_forget)

    def _on_theme_changed(self, _theme=None) -> None:
        widgets = [self, *self.findChildren(QWidget)]
        style = self.style()
        for widget in widgets:
            style.unpolish(widget)
            style.polish(widget)
            widget.update()
        self._render_chat()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._persist_sessions()
        self._save_provider_from_form()
        self._save_window_state()
        super().closeEvent(event)

    def _load_settings_visible(self) -> bool:
        try:
            from utils.instance_runtime import create_app_settings

            return bool(create_app_settings().value(SETTINGS_VISIBLE_KEY, False, type=bool))
        except Exception:
            return False

    def _toggle_settings(self) -> None:
        visible = self.settings_button.isChecked()
        self.settings_panel.setVisible(visible)
        try:
            from utils.instance_runtime import create_app_settings

            create_app_settings().setValue(SETTINGS_VISIBLE_KEY, visible)
        except Exception:
            logger.debug("保存 AI 设置展开状态失败", exc_info=True)

    def _restore_geometry(self) -> bool:
        try:
            from utils.instance_runtime import create_app_settings

            geometry = create_app_settings().value(GEOMETRY_KEY)
            if geometry is not None:
                return bool(self.restoreGeometry(geometry))
        except Exception:
            logger.debug("恢复 AI 窗口尺寸失败", exc_info=True)
        return False

    def _save_window_state(self) -> None:
        try:
            from utils.instance_runtime import create_app_settings

            create_app_settings().setValue(GEOMETRY_KEY, self.saveGeometry())
        except Exception:
            logger.debug("保存 AI 窗口尺寸失败", exc_info=True)

    def _load_provider_into_form(self) -> None:
        values = load_ai_provider_settings()
        self.base_url_edit.setText(str(values.get("base_url") or DEFAULT_BASE_URL))
        self.model_edit.setText(str(values.get("model") or DEFAULT_MODEL))
        self.api_key_edit.setText(str(values.get("api_key") or ""))
        self.timeout_spin.setValue(int(values.get("timeout") or 90))

    def _complete_base_url(self) -> None:
        completed = normalize_ai_base_url(self.base_url_edit.text())
        if self.base_url_edit.text() != completed:
            self.base_url_edit.setText(completed)

    def _save_provider_from_form(self) -> None:
        self._complete_base_url()
        try:
            save_ai_provider_settings(
                base_url=self.base_url_edit.text(),
                model=self.model_edit.text(),
                api_key=self.api_key_edit.text(),
                timeout=int(self.timeout_spin.value()),
            )
        except Exception:
            logger.debug("保存 AI 设置失败", exc_info=True)

    def _provider_config(self) -> AIProviderConfig:
        return AIProviderConfig(
            str(self.base_url_edit.text() or "").strip(),
            str(self.model_edit.text() or "").strip(),
            str(self.api_key_edit.text() or ""),
            int(self.timeout_spin.value() or 90),
        )

    def _current_session(self) -> Optional[Dict[str, Any]]:
        return get_session(self._store, self._session_id)

    def _load_sessions(self) -> None:
        self._store = load_ai_sessions()
        current = get_session(self._store)
        if current is None:
            current = create_session(self._store)
            save_ai_sessions(self._store)
        self._session_id = str(current.get("id") or "")

    def _persist_sessions(self) -> None:
        if not self._store:
            return
        try:
            save_ai_sessions(self._store)
        except Exception:
            logger.debug("保存 AI 会话失败", exc_info=True)

    def _refresh_session_list(self) -> None:
        self._loading_session = True
        try:
            self.session_list.clear()
            current_item = None
            for session in self._store.get("sessions") or []:
                item = QListWidgetItem(str(session.get("title") or "新对话"))
                item.setData(Qt.ItemDataRole.UserRole, session.get("id"))
                self.session_list.addItem(item)
                if session.get("id") == self._session_id:
                    current_item = item
            if current_item is not None:
                self.session_list.setCurrentItem(current_item)
            elif self.session_list.count():
                self.session_list.setCurrentRow(0)
        finally:
            self._loading_session = False

    def _theme_colors(self) -> Dict[str, str]:
        from themes import theme_color

        return {
            "text": theme_color("text"),
            "muted": theme_color("text_secondary"),
            "user": theme_color("accent"),
            "assistant": theme_color("success"),
            "surface": theme_color("surface"),
            "canvas": theme_color("canvas"),
            "border": theme_color("border"),
            "accent": theme_color("accent"),
        }

    def _render_chat(self) -> None:
        if not hasattr(self, "chat_view") or self.chat_view is None:
            return
        session = self._current_session()
        colors = self._theme_colors()
        html, payloads, image_paths = format_ai_transcript_html(
            list((session or {}).get("messages") or []),
            colors,
        )
        if self._thinking_live:
            live = format_ai_thinking_html("", colors, live=True)
            html = f"{html}<div>{live}</div>"
        self._copy_payloads = payloads
        self._image_paths = image_paths
        self.chat_view.setHtml(html)
        scrollbar = self.chat_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_chat_anchor(self, url: QUrl) -> None:
        if url.scheme() in {"http", "https"}:
            QDesktopServices.openUrl(url)
            return
        raw = url.toString()
        index_text = raw.split(":", 1)[-1]
        try:
            index = int(index_text)
        except ValueError:
            index = -1
        if url.scheme() == "apply":
            self._apply_workflow_payload(index)
            return
        if url.scheme() == "download":
            self._download_workflow_payload(index)
            return
        if url.scheme() == "image":
            self._preview_chat_image(index)
            return
        if url.scheme() != "copy":
            return
        if index < 0 or index >= len(self._copy_payloads):
            self._set_status("没有可复制的内容。")
            return
        QGuiApplication.clipboard().setText(self._copy_payloads[index])
        self._set_status("已复制。")

    def _preview_chat_image(self, index: int) -> None:
        if index < 0 or index >= len(self._image_paths):
            self._set_status("找不到图片文件。")
            return
        self._open_image_preview(path=self._image_paths[index])

    def _open_image_preview(self, *, path: str = "", data: bytes = b"") -> None:
        pixmap = QPixmap()
        if path:
            pixmap.load(path)
        elif data:
            pixmap.loadFromData(data)
        if pixmap.isNull():
            QMessageBox.warning(self, "无法打开图片", "找不到图片文件。")
            return
        existing = self._image_preview
        if _widget_alive(existing):
            existing.load_pixmap(pixmap)
            existing.image_view.fit_image()
            show_and_raise_widget(existing, log_prefix="图片")
            existing.activateWindow()
            return
        dialog = AIImagePreviewDialog(pixmap, self)
        self._image_preview = dialog

        def _forget(_result=0, window=self, preview=dialog) -> None:
            if getattr(window, "_image_preview", None) is preview:
                window._image_preview = None

        dialog.finished.connect(_forget)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _apply_workflow_payload(self, index: int) -> None:
        if index < 0 or index >= len(self._copy_payloads):
            self._set_status("没有可应用的工作流修正。")
            return
        body = self._copy_payloads[index]
        try:
            ops = parse_workflow_proposal(body)
        except ValueError as exc:
            QMessageBox.warning(self, "无法应用", str(exc))
            self._set_status(str(exc))
            return
        uploaded_files = latest_user_files(self._current_session())
        source_workflow = None
        confirm = f"把这份修正写入当前正在编辑的工作流？共 {len(ops)} 项操作。此操作可撤销。"
        if uploaded_files:
            source_name = str(uploaded_files[0].get("name") or "工作流文件")
            confirm = (
                f"把这份修正按上传的「{source_name}」写入当前正在编辑的工作流？"
                f"共 {len(ops)} 项操作。当前画布会被替换成修正后的结果。"
                "此操作可撤销，不会改磁盘上的原文件。"
            )
            try:
                source_workflow = uploaded_workflow_for_apply(uploaded_files)
            except Exception as exc:
                QMessageBox.warning(self, "无法应用", str(exc))
                self._set_status(str(exc))
                return
        choice = QMessageBox.question(
            self,
            "应用工作流",
            confirm,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        try:
            result = apply_editor_workflow(
                self.main_window,
                body,
                source_workflow=source_workflow,
            )
        except Exception as exc:
            QMessageBox.warning(self, "应用失败", str(exc))
            self._set_status(str(exc))
            return
        self._set_status(
            f"已应用到当前工作流：{result['ops']} 项操作，"
            f"现在有 {result['cards']} 张卡片、{result['connections']} 条连线。"
        )

    def _download_workflow_payload(self, index: int) -> None:
        if index < 0 or index >= len(self._copy_payloads):
            self._set_status("没有可下载的工作流修正。")
            return
        body = self._copy_payloads[index]
        try:
            parse_workflow_proposal(body)
            source, display_name = proposal_source_workflow(
                self.main_window,
                latest_user_files(self._current_session()),
            )
            types = editor_task_types(self.main_window)
            if not types:
                raise RuntimeError("当前编辑器没有现行卡片目录")
            workflow = build_workflow_from_proposal(
                body,
                source,
                known_task_types=types,
            )
        except Exception as exc:
            QMessageBox.warning(self, "无法下载", str(exc))
            self._set_status(str(exc))
            return
        default_name = f"{display_name}{LCA_EXTENSION}"
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "下载工作流",
            default_name,
            LCA_SAVE_FILTER,
        )
        if not path:
            return
        try:
            saved = write_workflow_lca(path, workflow, display_name=display_name)
        except Exception as exc:
            QMessageBox.warning(self, "下载失败", str(exc))
            self._set_status(str(exc))
            return
        self._set_status(
            f"已下载工作流：{os.path.basename(str(saved))}，"
            f"{len(workflow.get('cards') or [])} 张卡片、"
            f"{len(workflow.get('connections') or [])} 条连线。"
        )

    def _append_chat_message(self, role: str, content: str, images=None, files=None, thinking: str = "") -> None:
        if not self._session_id:
            self._load_sessions()
        append_message(
            self._store,
            self._session_id,
            role,
            content,
            images=images,
            files=files,
            thinking=thinking,
        )
        save_ai_sessions(self._store)
        self._refresh_session_list()
        self._render_chat()

    def _switch_session(self, session_id: str) -> None:
        if not session_id or session_id == self._session_id:
            return
        set_current_session(self._store, session_id)
        self._session_id = session_id
        save_ai_sessions(self._store)
        self._refresh_session_list()
        self._render_chat()

    def _on_session_item_changed(self, current, _previous) -> None:
        if self._loading_session or current is None:
            return
        session_id = current.data(Qt.ItemDataRole.UserRole)
        if session_id:
            self._switch_session(str(session_id))

    def _on_new_session(self) -> None:
        session = create_session(self._store)
        self._session_id = str(session["id"])
        save_ai_sessions(self._store)
        self._refresh_session_list()
        self._render_chat()
        self._set_status("已新建对话。")
        self.prompt_edit.setFocus()

    def _on_rename_session(self) -> None:
        session = self._current_session()
        if session is None:
            return
        title, ok = QInputDialog.getText(self, "重命名对话", "对话名称：", text=str(session.get("title") or ""))
        if not ok:
            return
        rename_session(self._store, self._session_id, title)
        save_ai_sessions(self._store)
        self._refresh_session_list()

    def _on_delete_session(self) -> None:
        session = self._current_session()
        if session is None:
            return
        choice = QMessageBox.question(
            self,
            "删除对话",
            f"删除「{session.get('title') or '新对话'}」？此操作不能恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        next_session = delete_session(self._store, self._session_id)
        self._session_id = str((next_session or {}).get("id") or "")
        save_ai_sessions(self._store)
        self._refresh_session_list()
        self._render_chat()
        self._set_status("对话已删除。")

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _set_busy(self, busy: bool) -> None:
        for widget in (
            self.base_url_edit,
            self.model_edit,
            self.api_key_edit,
            self.timeout_spin,
            self.prompt_edit,
            self.image_button,
            self.image_strip,
            self.file_button,
            self.file_strip,
            self.session_list,
            self.settings_button,
            self.review_button,
            *self._session_buttons,
        ):
            widget.setEnabled(not busy)
        self.send_button.setEnabled(not busy)

    def _is_current_worker(self, worker) -> bool:
        return worker is None or worker is self._worker

    def send_current_prompt(self) -> None:
        if not self.send_button.isEnabled():
            return
        prompt = self.prompt_edit.toPlainText().strip()
        pending = list(self._pending_images)
        pending_files = list(self._pending_files)
        if not prompt and not pending and not pending_files:
            QMessageBox.warning(self, "缺少内容", "请先输入要发送的内容，或添加图片、工作流文件。")
            return
        if not prompt and pending_files:
            prompt = FILE_ONLY_PROMPT
        if not self._session_id:
            self._load_sessions()
        images = []
        files = []
        if pending:
            try:
                images = write_session_images(self._session_id, pending)
            except Exception as exc:
                QMessageBox.warning(self, "无法添加图片", str(exc))
                return
        if pending_files:
            try:
                files = write_session_files(self._session_id, pending_files)
            except Exception as exc:
                QMessageBox.warning(self, "无法添加文件", str(exc))
                return
        self.prompt_edit.clear()
        self._pending_images.clear()
        self._pending_files.clear()
        self._refresh_pending_images()
        self._refresh_pending_files()
        self._send_prompt(prompt, images, files)

    def review_current_workflow(self) -> None:
        if not self.send_button.isEnabled():
            return
        self._send_prompt(REVIEW_WORKFLOW_PROMPT)

    def _send_prompt(self, prompt: str, images=None, files=None) -> None:
        self._save_provider_from_form()
        self._append_chat_message("user", prompt, images, files=files)
        try:
            context, workflow_images = editor_workflow_bundle(self.main_window)
            uploaded = format_uploaded_workflows_context(
                files or latest_attached_files(self._current_session())
            )
            messages = build_ai_chat_messages(
                chat_system_prompt(
                    workflow_context=context,
                    uploaded_workflow_context=uploaded,
                ),
                chat_history(self._current_session()),
                extra_images=workflow_images,
            )
        except Exception as exc:
            self._set_status(str(exc))
            return
        self._thinking_live = False
        self._set_status("正在请求 AI 服务…")
        self._set_busy(True)
        self._worker = _AIWorker(self._provider_config(), messages, self)
        self._worker.completed.connect(self._on_reply)
        self._worker.failed.connect(self._on_reply_failed)
        self._worker.progressed.connect(self._on_reply_progress)
        self._worker.finished.connect(self._on_reply_finished)
        self._worker.start()

    def _on_reply_finished(self) -> None:
        worker = self.sender()
        if not self._is_current_worker(worker) or not _widget_alive(self):
            return
        self._set_busy(False)
        if worker is self._worker:
            self._worker = None
        if worker is not None:
            worker.deleteLater()

    def _on_reply_progress(self, line: str) -> None:
        if not self._is_current_worker(self.sender()) or not _widget_alive(self):
            return
        text = str(line or "").strip()
        if not text:
            return
        self._set_status(text)
        if not self._thinking_live:
            self._thinking_live = True
            self._render_chat()

    def _on_reply(self, text: str, thinking: str = "") -> None:
        if not self._is_current_worker(self.sender()) or not _widget_alive(self):
            return
        self._thinking_live = False
        self._append_chat_message("assistant", text)
        self._set_status("已回复。")

    def _on_reply_failed(self, message: str) -> None:
        if not self._is_current_worker(self.sender()) or not _widget_alive(self):
            return
        self._thinking_live = False
        self._append_chat_message("assistant", f"请求失败：{message}")
        self._set_status(f"请求失败：{message}")

    def dragEnterEvent(self, event) -> None:
        if self.can_accept_drop_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self.can_accept_drop_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if self.attach_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def can_accept_image_mime(self, mime) -> bool:
        if mime is None:
            return False
        if mime.hasImage():
            return True
        for url in mime.urls() or []:
            path = url.toLocalFile()
            if os.path.splitext(path)[1].lower() in AI_IMAGE_MIMES:
                return True
        return False

    def can_accept_drop_mime(self, mime) -> bool:
        if mime is None:
            return False
        if self.can_accept_image_mime(mime):
            return True
        for url in mime.urls() or []:
            if url.toLocalFile():
                return True
        return False

    def attach_from_mime(self, mime) -> bool:
        if mime is None:
            return False
        errors: List[str] = []
        unsupported: List[str] = []
        attached = False
        paths = [url.toLocalFile() for url in (mime.urls() or []) if url.toLocalFile()]
        for path in paths:
            ext = os.path.splitext(path)[1].lower()
            try:
                if ext in AI_IMAGE_MIMES:
                    self._attach_image_path(path)
                    attached = True
                elif ext in AI_WORKFLOW_EXTS:
                    self._attach_workflow_path(path)
                    attached = True
                else:
                    unsupported.append(os.path.basename(path) or path)
            except Exception as exc:
                errors.append(str(exc))
        if not paths and mime.hasImage():
            try:
                self._attach_qimage(mime)
                attached = True
            except Exception as exc:
                errors.append(str(exc))
        if unsupported:
            QMessageBox.warning(
                self,
                "不支持的文件",
                "只支持上传 .json 或 .lca 工作流，以及 PNG / JPG / WEBP / GIF 图片。\n"
                + "、".join(unsupported),
            )
        if errors:
            QMessageBox.warning(self, "无法添加", errors[0])
        return attached or bool(unsupported)

    def _on_pick_images(self) -> None:
        paths, _selected = QFileDialog.getOpenFileNames(
            self,
            "选择图片",
            "",
            _IMAGE_FILE_FILTER,
        )
        for path in paths:
            try:
                self._attach_image_path(path)
            except Exception as exc:
                QMessageBox.warning(self, "无法添加图片", str(exc))
                return

    def _on_pick_files(self) -> None:
        paths, _selected = QFileDialog.getOpenFileNames(
            self,
            "选择工作流",
            "",
            _WORKFLOW_FILE_FILTER,
        )
        for path in paths:
            try:
                self._attach_workflow_path(path)
            except Exception as exc:
                QMessageBox.warning(self, "无法添加文件", str(exc))
                return

    def _attach_image_path(self, path: str) -> None:
        mime = attachable_image_mime(path)
        size = os.path.getsize(path)
        if size <= 0:
            raise ValueError("图片文件是空的")
        if size > MAX_AI_IMAGE_BYTES:
            raise ValueError(f"图片太大，单张不能超过 {MAX_AI_IMAGE_BYTES // (1024 * 1024)} MB")
        with open(path, "rb") as handle:
            data = handle.read()
        self._add_pending_image(data, mime, os.path.basename(path))

    def _attach_qimage(self, mime) -> None:
        raw = mime.imageData()
        image = QImage()
        if isinstance(raw, QImage):
            image = raw
        elif isinstance(raw, QPixmap):
            image = raw.toImage()
        if image.isNull():
            image = QGuiApplication.clipboard().image()
        if image.isNull():
            raise ValueError("剪贴板里没有可用的图片")
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise ValueError("无法读取这张图片")
        self._add_pending_image(bytes(buffer.data()), "image/png", "粘贴.png")

    def _add_pending_image(self, data: bytes, mime: str, name: str) -> None:
        if len(self._pending_images) >= MAX_AI_IMAGES_PER_TURN:
            raise ValueError(f"一次最多添加 {MAX_AI_IMAGES_PER_TURN} 张图片")
        if not data:
            raise ValueError("图片文件是空的")
        if len(data) > MAX_AI_IMAGE_BYTES:
            raise ValueError(f"图片太大，单张不能超过 {MAX_AI_IMAGE_BYTES // (1024 * 1024)} MB")
        attachable_image_mime(mime=mime)
        self._pending_images.append(
            {"data": data, "mime": mime, "name": name or "图片"}
        )
        self._refresh_pending_images()

    def _remove_pending_image(self, index: int) -> None:
        if 0 <= index < len(self._pending_images):
            del self._pending_images[index]
            self._refresh_pending_images()

    def _refresh_pending_images(self) -> None:
        while self.image_strip_layout.count():
            item = self.image_strip_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.image_strip.setVisible(bool(self._pending_images))
        for index, item in enumerate(self._pending_images):
            self.image_strip_layout.addWidget(self._make_image_chip(index, item))
        self.image_strip_layout.addStretch(1)

    def _make_image_chip(self, index: int, item: Dict[str, Any]) -> QWidget:
        chip = QWidget()
        chip.setObjectName("aiImageChip")
        layout = QVBoxLayout(chip)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        thumb = _ClickableThumb()
        thumb.setObjectName("aiImageThumb")
        thumb.setFixedSize(64, 64)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap()
        pixmap.loadFromData(item.get("data") or b"")
        if not pixmap.isNull():
            thumb.setPixmap(
                pixmap.scaled(
                    64,
                    64,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            thumb.setText("图片")
        payload = item.get("data") or b""
        thumb.clicked.connect(lambda _=False, blob=payload: self._open_image_preview(data=blob))
        remove = QPushButton("移除")
        remove.clicked.connect(lambda _=False, pos=index: self._remove_pending_image(pos))
        layout.addWidget(thumb)
        layout.addWidget(remove)
        return chip

    def _attach_workflow_path(self, path: str) -> None:
        attachable_workflow_suffix(path)
        size = os.path.getsize(path)
        if size <= 0:
            raise ValueError("工作流文件是空的")
        if size > MAX_AI_WORKFLOW_FILE_BYTES:
            raise ValueError(
                f"工作流文件太大，单个不能超过 {MAX_AI_WORKFLOW_FILE_BYTES // (1024 * 1024)} MB"
            )
        with open(path, "rb") as handle:
            data = handle.read()
        self._add_pending_file(data, os.path.basename(path))

    def _add_pending_file(self, data: bytes, name: str) -> None:
        if len(self._pending_files) >= MAX_AI_WORKFLOW_FILES_PER_TURN:
            raise ValueError(f"一次最多上传 {MAX_AI_WORKFLOW_FILES_PER_TURN} 个工作流文件")
        if not data:
            raise ValueError("工作流文件是空的")
        if len(data) > MAX_AI_WORKFLOW_FILE_BYTES:
            raise ValueError(
                f"工作流文件太大，单个不能超过 {MAX_AI_WORKFLOW_FILE_BYTES // (1024 * 1024)} MB"
            )
        filename = str(name or "").strip() or "workflow.json"
        attachable_workflow_suffix(filename)
        self._pending_files.append({"data": bytes(data), "name": filename})
        self._refresh_pending_files()

    def _remove_pending_file(self, index: int) -> None:
        if 0 <= index < len(self._pending_files):
            del self._pending_files[index]
            self._refresh_pending_files()

    def _refresh_pending_files(self) -> None:
        while self.file_strip_layout.count():
            item = self.file_strip_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.file_strip.setVisible(bool(self._pending_files))
        for index, item in enumerate(self._pending_files):
            self.file_strip_layout.addWidget(self._make_file_chip(index, item))
        self.file_strip_layout.addStretch(1)

    def _make_file_chip(self, index: int, item: Dict[str, Any]) -> QWidget:
        chip = QWidget()
        chip.setObjectName("aiFileChip")
        layout = QVBoxLayout(chip)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        name = QLabel(str(item.get("name") or "工作流文件"))
        name.setObjectName("aiFileChipName")
        name.setWordWrap(True)
        name.setFixedWidth(96)
        name.setToolTip(str(item.get("name") or "工作流文件"))
        remove = QPushButton("移除")
        remove.clicked.connect(lambda _=False, pos=index: self._remove_pending_file(pos))
        layout.addWidget(name)
        layout.addWidget(remove)
        return chip
