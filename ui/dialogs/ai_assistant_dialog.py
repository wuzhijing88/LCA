# -*- coding: utf-8 -*-
"""独立的 AI 助手窗口，不占用右侧参数面板。"""

from __future__ import annotations

import logging
import os
import copy
import json
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QBuffer, QEvent, QIODevice, QObject, QTimer, QUrl, Qt, QThread, Signal, Slot
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
from shiboken6 import isValid

from ui.dialogs.dialog_manager import exec_dialog, get_dialog_manager, retire_dialog

from app_core.ai_assistant import (
    AI_IMAGE_MIMES,
    AI_WORKFLOW_EXTS,
    AIProviderConfig,
    DEFAULT_BASE_URL,
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
    collect_editor_workflow_snapshot,
    collect_workflow_resources,
    editor_task_types,
    editor_resource_dirs,
    format_editor_workflow_context,
    format_uploaded_workflows_context,
    inspect_uploaded_workflow_file,
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
from app_core.ai_chat_format import format_ai_transcript_html, iter_message_segments
from app_core.ai_stream import AICancellation, AIRequestCancelled
from app_core.ai_models import fetch_ai_models
from themes import ThemedComboBox
from app_core.ai_sessions import (
    MAX_ACTIVITY,
    MAX_SESSIONS,
    append_message,
    chat_history,
    create_session,
    delete_session,
    get_session,
    latest_attached_files,
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
_MAX_ACTIVE_TASKS = 4
_MAX_QUEUED_TURNS = 8


@dataclass
class _AIRequest:
    config: AIProviderConfig
    prompt: str
    images: list
    files: list
    context_files: list
    snapshot: dict
    resource_dirs: dict
    task_types: list


@dataclass
class _AIRun:
    worker: Any
    request: _AIRequest
    message: dict
    status: str = "正在请求 AI 服务…"
    content_parts: list = field(default_factory=list)
    round_content: bool = False
    next_request: Optional[_AIRequest] = None


class _AIWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)
    cancelled = Signal()
    event_received = Signal(object)

    def __init__(self, session_id: str, request: _AIRequest, history, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.request = request
        self.history = history
        self.cancel_token = AICancellation()

    def cancel(self):
        self.cancel_token.cancel()
        self.requestInterruption()

    def run(self) -> None:
        try:
            self.cancel_token.check()
            request = self.request
            workflow = request.snapshot.get("workflow")
            resources = collect_workflow_resources(workflow, request.resource_dirs, cancel=self.cancel_token)
            self.cancel_token.check()
            images = [{"path": item["abs_path"], "data_url": item["data_url"]}
                      for item in resources if item.get("attach_index", 0) > 0]
            messages = build_ai_chat_messages(
                chat_system_prompt(
                    workflow_context=format_editor_workflow_context(request.snapshot, resources=resources),
                    uploaded_workflow_context=format_uploaded_workflows_context(request.context_files),
                ), self.history, extra_images=images,
            )
            if request.context_files:
                source = inspect_uploaded_workflow_file(request.context_files[0]["path"],
                                                       display_name=request.context_files[0]["name"])
                workflow = source.get("workflow") if source.get("status") == "ok" else None
            text, _ = complete_ai_chat(
                request.config, messages, use_cache=False,
                on_event=self.event_received.emit, cancel=self.cancel_token,
                tool_context={"workflow": workflow, "task_types": request.task_types},
            )
            self.cancel_token.check()
            self.completed.emit(text)
        except AIRequestCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.history = []


class _AIModelsWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, config: AIProviderConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.cancel_token = AICancellation()

    def cancel(self):
        self.cancel_token.cancel()
        self.requestInterruption()

    def run(self):
        try:
            models = fetch_ai_models(self.config, cancel=self.cancel_token)
            self.cancel_token.check()
            self.completed.emit(models)
        except AIRequestCancelled:
            return
        except Exception as exc:
            self.failed.emit(str(exc).replace(self.config.api_key, "[已隐藏]")
                             if self.config.api_key else str(exc))


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
        from themes import get_theme_manager

        manager = get_theme_manager()
        callback = self._on_theme_changed
        manager.register_theme_change_callback(callback)
        self.destroyed.connect(lambda: manager.unregister_theme_change_callback(callback))

    def _on_theme_changed(self, _theme=None) -> None:
        widgets = [self, *self.findChildren(QWidget)]
        style = self.style()
        for widget in widgets:
            style.unpolish(widget)
            style.polish(widget)
            widget.update()
        self._apply_theme_chrome()


def _widget_alive(widget) -> bool:
    return widget is not None and isValid(widget)


def open_ai_assistant_dialog(main_window):
    def present(dialog):
        dialog.refresh_for_main_window(main_window)
        show_and_raise_widget(dialog, log_prefix="AI 助手")
        dialog.activateWindow()

    return get_dialog_manager(main_window).show(
        "ai_assistant", lambda: AIAssistantDialog(main_window),
        present=present, dispose=lambda dialog: dialog.request_delete(),
    )


class AIAssistantDialog(QDialog):
    """左侧会话、右侧对话，服务设置默认收起。"""

    def __init__(self, main_window=None):
        super().__init__(main_window)
        self.main_window = main_window
        self._owner = main_window
        if self._owner is not None:
            self._owner.installEventFilter(self)
        self._store: Dict[str, Any] = {}
        self._session_id = ""
        self._loading_session = False
        self._runs: Dict[str, _AIRun] = {}
        self._queues: Dict[str, list] = {}
        self._retry_requests: Dict[str, _AIRequest] = {}
        self._drafts: Dict[str, dict] = {}
        self._expanded_activity: Dict[str, set] = {}
        self._closing = False
        self._storage_error = ""
        self._retired = False
        self._retiring_workers = []
        self._models_worker = None
        self._model_workers = []
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(60)
        self._render_timer.timeout.connect(self._render_chat)
        self._checkpoint_timer = QTimer(self)
        self._checkpoint_timer.setSingleShot(True)
        self._checkpoint_timer.setInterval(1000)
        self._checkpoint_timer.timeout.connect(self._persist_sessions)
        self._copy_payloads: List[str] = []
        self._payload_contexts: List[dict] = []
        self._image_paths: List[str] = []
        self._image_preview: Optional[AIImagePreviewDialog] = None
        self._pending_images: List[Dict[str, Any]] = []
        self._pending_files: List[Dict[str, Any]] = []
        self._prompt_filter = _AIPromptEnterFilter(self)
        try:
            self._build_ui()
            self._load_sessions()
            self._load_provider_into_form()
            self._refresh_session_list()
            self._render_chat()
            self._register_theme_callback()
        except Exception:
            self._shutdown_runs()
            super().deleteLater()
            raise

    def refresh_for_main_window(self, main_window=None) -> None:
        if main_window is not None:
            self.main_window = main_window

    def _build_ui(self) -> None:
        self.setObjectName("aiAssistantDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
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
        self.get_button = QPushButton("获取API")
        self.get_button.setObjectName("aiAssistantGetButton")
        self.get_button.clicked.connect(self._open_product_website)
        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(self.get_button)
        row.addWidget(self.settings_button)
        return row

    def _open_product_website(self) -> None:
        QDesktopServices.openUrl(QUrl("https://lcaa.xyz/"))

    def _build_settings_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("aiSettingsPanel")
        form = QFormLayout(panel)
        form.setContentsMargins(0, 0, 0, 4)
        form.setSpacing(6)
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText(DEFAULT_BASE_URL)
        self.base_url_edit.editingFinished.connect(self._complete_base_url)
        self.model_combo = ThemedComboBox()
        self.model_combo.setObjectName("aiModelCombo")
        self.model_combo.setEditable(True)
        self.model_combo.setInsertPolicy(ThemedComboBox.InsertPolicy.NoInsert)
        self.model_combo.setMaxVisibleItems(12)
        self.model_combo.setMinimumContentsLength(20)
        self.model_combo.setSizeAdjustPolicy(
            ThemedComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.model_combo.lineEdit().setPlaceholderText("选择或填写模型")
        self.model_combo.setToolTip("获取服务返回的模型列表后选择，也可填写服务提供的模型 ID。")
        self.fetch_models_button = QPushButton("获取模型")
        self.fetch_models_button.setObjectName("aiFetchModelsButton")
        self.fetch_models_button.clicked.connect(self._fetch_models)
        model_row = QHBoxLayout()
        model_row.setContentsMargins(0, 0, 0, 0)
        model_row.setSpacing(6)
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(self.fetch_models_button)
        self.model_status = QLabel("尚未获取模型列表，当前模型的支持情况未知。")
        self.model_status.setWordWrap(True)
        self.model_status.setTextFormat(Qt.TextFormat.PlainText)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("只保存在本机，不写入工作流")
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 300)
        self.timeout_spin.setValue(90)
        form.addRow("服务地址", self.base_url_edit)
        form.addRow("模型", model_row)
        form.addRow("", self.model_status)
        form.addRow("API Key", self.api_key_edit)
        form.addRow("超时(秒)", self.timeout_spin)
        self.base_url_edit.textChanged.connect(self._invalidate_models)
        self.api_key_edit.textChanged.connect(self._invalidate_models)
        self.timeout_spin.valueChanged.connect(self._invalidate_models)
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
        self.queue_panel = QWidget()
        queue_layout = QVBoxLayout(self.queue_panel)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_header = QHBoxLayout()
        queue_header.addWidget(QLabel("待发送消息"))
        queue_header.addStretch(1)
        remove_queued = QPushButton("移除选中")
        remove_queued.clicked.connect(self._remove_queued_request)
        queue_header.addWidget(remove_queued)
        queue_layout.addLayout(queue_header)
        self.queue_list = QListWidget()
        self.queue_list.setMaximumHeight(80)
        queue_layout.addWidget(self.queue_list)
        self.queue_panel.hide()
        layout.addWidget(self.queue_panel)
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
        self.stop_button = QPushButton("停止")
        self.stop_button.setToolTip("停止当前任务并清空本会话的待发送队列，保留已收到的内容")
        self.stop_button.clicked.connect(self.stop_current_task)
        self.stop_button.setVisible(False)
        self.retry_button = QPushButton("重试")
        self.retry_button.clicked.connect(self.retry_current_task)
        self.retry_button.setVisible(False)
        self.steer_button = QPushButton("立即补充")
        self.steer_button.setToolTip("停止本轮，按输入框中的补充说明立即继续；其他排队消息保持原顺序")
        self.steer_button.clicked.connect(lambda: self.send_current_prompt(interrupt=True))
        self.steer_button.hide()
        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.image_button)
        footer.addWidget(self.file_button)
        footer.addWidget(self.review_button)
        footer.addWidget(self.retry_button)
        footer.addWidget(self.stop_button)
        footer.addWidget(self.steer_button)
        footer.addWidget(self.send_button)
        layout.addLayout(footer)
        return panel

    def _register_theme_callback(self) -> None:
        from themes import get_theme_manager

        manager = get_theme_manager()
        callback = self._on_theme_changed
        manager.register_theme_change_callback(callback)
        self.destroyed.connect(lambda: manager.unregister_theme_change_callback(callback))

    def _on_theme_changed(self, _theme=None) -> None:
        widgets = [self, *self.findChildren(QWidget)]
        style = self.style()
        for widget in widgets:
            style.unpolish(widget)
            style.polish(widget)
            widget.update()
        self._render_chat()

    def done(self, result) -> None:
        self._shutdown_runs()
        try:
            self._persist_sessions()
            self._save_provider_from_form()
            self._save_window_state()
        finally:
            super().done(result)
            self.request_delete()

    def request_delete(self):
        if self._retired:
            return
        self._retired = True
        self._shutdown_runs()
        self._persist_sessions()
        if self._image_preview is not None:
            self._image_preview.close()
            self._image_preview = None
        for worker in self._retiring_workers:
            for signal, slot in (
                (worker.completed, self._on_reply),
                (worker.failed, self._on_reply_failed),
                (worker.cancelled, self._on_reply_cancelled),
                (worker.event_received, self._on_run_event),
                (worker.finished, self._on_reply_finished),
            ):
                signal.disconnect(slot)
        for worker in self._model_workers:
            worker.completed.disconnect(self._on_models_loaded)
            worker.failed.disconnect(self._on_models_failed)
            worker.finished.disconnect(self._on_models_finished)
        retire_dialog(self, [*self._retiring_workers, *self._model_workers])

    def _shutdown_runs(self):
        if self._closing:
            return
        self._closing = True
        self._cancel_models_request()
        if self._owner is not None and isValid(self._owner):
            self._owner.removeEventFilter(self)
        self._render_timer.stop()
        self._checkpoint_timer.stop()
        self._flush_stream_content()
        for run in self._runs.values():
            run.worker.cancel()
            if run.next_request is not None:
                self._remove_request_attachments(run.next_request)
            if run.message.get("run_status") in {"running", "stopping"}:
                run.message["run_status"] = "cancelled"
                run.message["error"] = "窗口已关闭，本次任务已停止，部分内容不代表完整结论。"
            self._retiring_workers.append(run.worker)
        self._runs.clear()
        for session_id in list(self._queues):
            self._discard_queue(session_id)
        self._retry_requests.clear()
        self._drafts.clear()
        self._pending_images.clear()
        self._pending_files.clear()

    def deleteLater(self):
        if (self._runs or self._model_workers) and not self._closing:
            self.request_delete()
            return
        super().deleteLater()

    def eventFilter(self, watched, event):
        if watched is self._owner and event.type() == QEvent.Type.DeferredDelete:
            self.request_delete()
        return super().eventFilter(watched, event)

    def hideEvent(self, event):
        self._render_timer.stop()
        if self._models_worker is not None:
            self._cancel_models_request()
            self.model_status.setText("已取消获取模型，模型支持情况未知。")
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._render_chat()

    def _load_settings_visible(self) -> bool:
        try:
            from utils.instance_runtime import create_app_settings

            return bool(create_app_settings().value(SETTINGS_VISIBLE_KEY, False, type=bool))
        except Exception:
            return False

    def _toggle_settings(self) -> None:
        visible = self.settings_button.isChecked()
        self.settings_panel.setVisible(visible)
        if not visible and self._models_worker is not None:
            self._cancel_models_request()
            self.model_status.setText("已取消获取模型，模型支持情况未知。")
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
        self.base_url_edit.setText(values["base_url"])
        self.model_combo.setEditText(values["model"])
        self.api_key_edit.setText(values["api_key"])
        self.timeout_spin.setValue(values["timeout"])
        self.model_status.setText("尚未获取模型列表，当前模型的支持情况未知。")

    def _complete_base_url(self) -> None:
        if not self.base_url_edit.text().strip():
            return
        completed = normalize_ai_base_url(self.base_url_edit.text())
        if self.base_url_edit.text() != completed:
            self.base_url_edit.setText(completed)

    def _save_provider_from_form(self) -> None:
        self._complete_base_url()
        save_ai_provider_settings(
            base_url=self.base_url_edit.text(),
            model=self.model_combo.currentText(),
            api_key=self.api_key_edit.text(),
            timeout=int(self.timeout_spin.value()),
        )

    def _provider_config(self) -> AIProviderConfig:
        return AIProviderConfig(
            self.base_url_edit.text().strip(),
            self.model_combo.currentText().strip(),
            self.api_key_edit.text(),
            self.timeout_spin.value(),
        )

    def _clear_model_options(self):
        current = self.model_combo.currentText()
        self.model_combo.clear()
        self.model_combo.setEditText(current)

    def _cancel_models_request(self):
        if self._models_worker is not None:
            self._models_worker.cancel()
            self._models_worker = None
            self.fetch_models_button.setText("正在取消…")

    def _invalidate_models(self):
        self._cancel_models_request()
        self._clear_model_options()
        self.model_status.setText("服务设置已变更，请重新获取模型；当前模型支持情况未知。")

    def _fetch_models(self):
        if self._closing or self._model_workers:
            return
        config = self._provider_config()
        if not config.base_url or not config.api_key.strip():
            self.model_status.setText("请先填写服务地址和 API Key，再获取模型。")
            return
        self._clear_model_options()
        worker = _AIModelsWorker(config, self)
        self._models_worker = worker
        self._model_workers.append(worker)
        worker.completed.connect(self._on_models_loaded)
        worker.failed.connect(self._on_models_failed)
        worker.finished.connect(self._on_models_finished)
        self.fetch_models_button.setEnabled(False)
        self.fetch_models_button.setText("获取中…")
        self.model_combo.setEnabled(False)
        self.model_status.setText("正在获取当前服务支持的模型…")
        worker.start()

    @Slot(object)
    def _on_models_loaded(self, models):
        if self._closing or self.sender() is not self._models_worker:
            return
        current = self.model_combo.currentText().strip()
        self.model_combo.clear()
        self.model_combo.addItems(models)
        index = self.model_combo.findText(current, Qt.MatchFlag.MatchExactly)
        self.model_combo.setCurrentIndex(index)
        if index < 0:
            self.model_combo.setEditText("")
        self.model_status.setText(f"已获取 {len(models)} 个模型，请从下拉列表选择。")

    @Slot(str)
    def _on_models_failed(self, error):
        if self._closing or self.sender() is not self._models_worker:
            return
        self.model_status.setText(f"获取模型失败：{error}；模型支持情况未知，未自动切换模型。")

    @Slot()
    def _on_models_finished(self):
        if self._retired:
            return
        worker = self.sender()
        if worker is self._models_worker:
            self._models_worker = None
        self._model_workers.remove(worker)
        worker.completed.disconnect(self._on_models_loaded)
        worker.failed.disconnect(self._on_models_failed)
        worker.finished.disconnect(self._on_models_finished)
        worker.deleteLater()
        self.fetch_models_button.setEnabled(not self._closing)
        self.fetch_models_button.setText("获取模型")
        self.model_combo.setEnabled(not self._closing)

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
        self._flush_stream_content()
        self._checkpoint_timer.stop()
        try:
            save_ai_sessions(self._store)
            self._storage_error = ""
        except Exception as exc:
            self._storage_error = f"保存 AI 会话失败：{exc}；结果尚未持久保存。"
            self._set_status(self._storage_error)
            logger.debug("保存 AI 会话失败", exc_info=True)

    def _flush_stream_content(self):
        for run in self._runs.values():
            if run.message.get("run_status") in {"running", "stopping"}:
                run.message["content"] = "".join(run.content_parts).rstrip()

    def _refresh_session_list(self) -> None:
        self._loading_session = True
        try:
            self.session_list.clear()
            current_item = None
            for session in self._store.get("sessions") or []:
                session_id = session.get("id")
                label = str(session.get("title") or "新对话")
                run = self._runs.get(session_id)
                if run is not None:
                    label += " · " + {"running": "执行中", "stopping": "停止中", "completed": "已完成",
                                      "failed": "失败", "cancelled": "已停止"}[run.message["run_status"]]
                item = QListWidgetItem(label)
                item.setToolTip(label)
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
        self._render_timer.stop()
        self._flush_stream_content()
        scrollbar = self.chat_view.verticalScrollBar()
        position = scrollbar.value()
        follow = position >= scrollbar.maximum() - 24
        session = self._current_session()
        messages = list((session or {}).get("messages") or [])
        colors = self._theme_colors()
        html, payloads, image_paths = format_ai_transcript_html(
            messages, colors, expanded_activity=self._expanded_activity.get(self._session_id, set()),
        )
        contexts = []
        attached = []
        for message in messages:
            if message.get("role") == "user" and message.get("files"):
                attached = message["files"]
            for kind, _, _ in iter_message_segments(message.get("content", "")):
                if kind == "fence":
                    source_files = message.get("source_files", []) if message.get("role") == "assistant" else attached
                    contexts.append({"files": source_files, "message": message})
        self._payload_contexts = contexts
        self._copy_payloads = payloads
        self._image_paths = image_paths
        self.chat_view.setHtml(html)
        scrollbar.setValue(scrollbar.maximum() if follow else position)

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
        if url.scheme() == "activity":
            messages = (self._current_session() or {}).get("messages", [])
            if 0 <= index < len(messages):
                expanded = self._expanded_activity.setdefault(self._session_id, set())
                expanded.symmetric_difference_update({index})
                self._render_chat()
            return
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
        def present(dialog):
            dialog.load_pixmap(pixmap)
            dialog.image_view.fit_image()
            show_and_raise_widget(dialog, log_prefix="图片")
            dialog.activateWindow()

        def forget(_dialog, _result):
            self._image_preview = None

        self._image_preview = get_dialog_manager(self).show(
            "image_preview", lambda: AIImagePreviewDialog(pixmap, self),
            present=present, on_finished=forget,
        )

    def _apply_workflow_payload(self, index: int) -> None:
        if index < 0 or index >= len(self._copy_payloads):
            self._set_status("没有可应用的工作流修正。")
            return
        body = self._copy_payloads[index]
        try:
            context = self._workflow_payload_context(index)
            ops = parse_workflow_proposal(body)
        except ValueError as exc:
            QMessageBox.warning(self, "无法应用", str(exc))
            self._set_status(str(exc))
            return
        uploaded_files = context["files"]
        source_workflow = None
        confirm = f"是否覆盖当前正在编辑的工作流？共 {len(ops)} 项操作。"
        if uploaded_files:
            source_name = str(uploaded_files[0].get("name") or "工作流文件")
            confirm = (
                f"按上传的「{source_name}」生成修正结果，是否覆盖当前正在编辑的工作流？"
                f"共 {len(ops)} 项操作。不会改磁盘上的原文件。"
            )
            try:
                source_workflow = uploaded_workflow_for_apply(uploaded_files)
            except Exception as exc:
                QMessageBox.warning(self, "无法应用", str(exc))
                self._set_status(str(exc))
                return
        mode = self._choose_workflow_apply_mode(confirm)
        if mode is None:
            return
        try:
            self._verify_workflow_source(context)
            result = apply_editor_workflow(
                self.main_window,
                body,
                source_workflow=source_workflow,
                mode=mode,
            )
        except Exception as exc:
            QMessageBox.warning(self, "应用失败", str(exc))
            self._set_status(str(exc))
            return
        self._set_status(
            f"{'已覆盖当前工作流' if mode == 'replace' else '已保留原卡片并新增 AI 卡片'}：{result['ops']} 项操作，"
            f"现在有 {result['cards']} 张卡片、{result['connections']} 条连线。"
        )

    def _choose_workflow_apply_mode(self, confirm: str) -> Optional[str]:
        box = QMessageBox(self)
        box.setWindowTitle("应用工作流")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(confirm)
        box.setInformativeText(
            "覆盖：用 AI 结果替换当前画布。\n"
            "保留并新增：保留原卡片和连线，在旁边新增 AI 卡片。\n"
            "两种方式均可撤销。"
        )
        replace_button = box.addButton("覆盖当前工作流", QMessageBox.ButtonRole.YesRole)
        append_button = box.addButton("保留并新增", QMessageBox.ButtonRole.NoRole)
        cancel_button = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_button)
        box.setEscapeButton(cancel_button)

        def read_result(_result):
            clicked = box.clickedButton()
            if clicked is replace_button:
                return "replace"
            if clicked is append_button:
                return "append"
            return None

        return exec_dialog(box, read_result=read_result)

    def _download_workflow_payload(self, index: int) -> None:
        if index < 0 or index >= len(self._copy_payloads):
            self._set_status("没有可下载的工作流修正。")
            return
        body = self._copy_payloads[index]
        try:
            context = self._workflow_payload_context(index)
            parse_workflow_proposal(body)
            source, display_name = proposal_source_workflow(
                self.main_window,
                context["files"],
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
            self._verify_workflow_source(context)
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

    def _workflow_payload_context(self, index):
        if not 0 <= index < len(self._payload_contexts):
            raise ValueError("找不到该方案对应的会话上下文，请重新审查。")
        context = self._payload_contexts[index]
        message = context["message"]
        if message.get("run_status") != "completed":
            raise ValueError("该任务尚未完整完成，不能应用或下载其中的工作流。")
        self._verify_workflow_source(context)
        return context

    def _verify_workflow_source(self, context):
        message = context["message"]
        fingerprint = message.get("source_fingerprint")
        if fingerprint:
            current = collect_editor_workflow_snapshot(self.main_window)
            if current.get("status") == "error" or self._workflow_fingerprint(current.get("workflow")) != fingerprint:
                raise ValueError("当前画布与提交任务时不同，请重新审查后再应用或下载，避免覆盖后续修改。")

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
        if get_session(self._store, session_id) is None:
            return
        self._save_draft()
        set_current_session(self._store, session_id)
        self._session_id = session_id
        save_ai_sessions(self._store)
        self._refresh_session_list()
        self._restore_draft()
        self._refresh_controls()
        self._render_chat()

    def _save_draft(self):
        self._drafts[self._session_id] = {"prompt": self.prompt_edit.toPlainText(),
                                        "images": self._pending_images, "files": self._pending_files}

    def _restore_draft(self):
        draft = self._drafts.get(self._session_id, {})
        self.prompt_edit.setPlainText(draft.get("prompt", ""))
        self._pending_images = draft.get("images", [])
        self._pending_files = draft.get("files", [])
        self._refresh_pending_images()
        self._refresh_pending_files()
        self._expanded_activity.setdefault(self._session_id, set())
        self.chat_view.verticalScrollBar().setValue(self.chat_view.verticalScrollBar().maximum())

    def _on_session_item_changed(self, current, _previous) -> None:
        if self._loading_session or current is None:
            return
        session_id = current.data(Qt.ItemDataRole.UserRole)
        if session_id:
            self._switch_session(str(session_id))

    def _on_new_session(self) -> None:
        if len(self._store.get("sessions", [])) >= MAX_SESSIONS:
            self._set_status(f"最多保留 {MAX_SESSIONS} 个会话，请先删除不再需要的会话。")
            return
        self._save_draft()
        session = create_session(self._store)
        self._session_id = str(session["id"])
        save_ai_sessions(self._store)
        self._refresh_session_list()
        self._restore_draft()
        self._refresh_controls()
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
        if self._session_id in self._runs:
            self._set_status("请先停止本会话任务，待停止完成后再删除会话。")
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
        self._discard_queue(self._session_id)
        self._drafts.pop(self._session_id, None)
        self._expanded_activity.pop(self._session_id, None)
        self._retry_requests.pop(self._session_id, None)
        next_session = delete_session(self._store, self._session_id)
        self._session_id = str((next_session or {}).get("id") or "")
        save_ai_sessions(self._store)
        self._refresh_session_list()
        self._restore_draft()
        self._refresh_controls()
        self._render_chat()
        self._set_status("对话已删除。")

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _refresh_controls(self):
        run = self._runs.get(self._session_id)
        stopping = run is not None and run.message.get("run_status") == "stopping"
        self.send_button.setEnabled(not stopping and (run is not None or len(self._runs) < _MAX_ACTIVE_TASKS))
        self.send_button.setText("加入队列" if run is not None else "发送")
        self.stop_button.setVisible(run is not None)
        self.stop_button.setEnabled(not stopping)
        self.steer_button.setVisible(run is not None)
        self.steer_button.setEnabled(not stopping)
        self.retry_button.setVisible(run is None and self._session_id in self._retry_requests)
        self.review_button.setEnabled(self.send_button.isEnabled())
        queued = len(self._queues.get(self._session_id, []))
        selected = self.queue_list.currentRow()
        self.queue_list.clear()
        for request in self._queues.get(self._session_id, []):
            item = QListWidgetItem(request.prompt[:100] or "图片或工作流附件")
            item.setToolTip(request.prompt[:2000])
            self.queue_list.addItem(item)
        if queued:
            self.queue_list.setCurrentRow(min(max(selected, 0), queued - 1))
        self.queue_panel.setVisible(bool(queued))
        if run is not None:
            self._set_status(run.status + (f" · 待发送 {queued} 条" if queued else ""))
        elif self._session_id in self._retry_requests:
            self._set_status("任务未完成，可重试或发送补充说明。")
        else:
            self._set_status("")
        if self._storage_error:
            self._set_status(self._storage_error)

    def send_current_prompt(self, *, interrupt=False) -> None:
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
        images, files = [], []
        try:
            if pending:
                images = write_session_images(self._session_id, pending)
            if pending_files:
                files = write_session_files(self._session_id, pending_files)
            accepted = self._send_prompt(prompt, images, files, interrupt=interrupt)
        except Exception as exc:
            accepted = False
            QMessageBox.warning(self, "无法发送", str(exc))
        if not accepted:
            for item in images + files:
                if os.path.isfile(item["path"]):
                    os.remove(item["path"])
            return
        self.prompt_edit.clear()
        self._pending_images.clear()
        self._pending_files.clear()
        self._refresh_pending_images()
        self._refresh_pending_files()

    def review_current_workflow(self) -> None:
        if self.send_button.isEnabled():
            self._send_prompt(REVIEW_WORKFLOW_PROMPT)

    def _send_prompt(self, prompt: str, images=None, files=None, *, interrupt=False) -> bool:
        if self._closing:
            return False
        run = self._runs.get(self._session_id)
        if run is None and len(self._runs) >= _MAX_ACTIVE_TASKS:
            self._set_status(f"最多同时运行 {_MAX_ACTIVE_TASKS} 个会话，请先停止或等待其他任务。")
            return False
        if run is not None and run.message.get("run_status") == "stopping":
            return False
        if not interrupt and sum(len(queue) for queue in self._queues.values()) >= _MAX_QUEUED_TURNS:
            self._set_status(f"待发送队列最多 {_MAX_QUEUED_TURNS} 条，请先等待任务完成。")
            return False
        try:
            config = self._provider_config()
            if not config.base_url:
                raise ValueError("请先在设置中填写服务地址，不能自动使用默认服务")
            if not config.model:
                raise ValueError("请先在设置中选择或填写模型，不能自动使用默认模型")
            if not config.api_key.strip():
                raise ValueError("请先在设置中填写 API Key")
            self._save_provider_from_form()
            snapshot = copy.deepcopy(collect_editor_workflow_snapshot(self.main_window))
            if snapshot.get("status") == "error":
                raise ValueError("无法读取当前工作流：" + snapshot["error"])
            if len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8")) > MAX_AI_WORKFLOW_FILE_BYTES:
                raise ValueError("当前工作流快照超过 8 MB，不能提交 AI 任务")
            request = _AIRequest(config, prompt, list(images or []), list(files or []),
                                 list(files or latest_attached_files(self._current_session())),
                                 snapshot, dict(editor_resource_dirs(self.main_window)),
                                 list(editor_task_types(self.main_window)))
        except Exception as exc:
            self._set_status(str(exc))
            return False
        if run is not None:
            if interrupt:
                run.next_request = request
                run.message["run_status"] = "stopping"
                run.status = "正在停止本轮并接收补充说明…"
                run.worker.cancel()
            else:
                self._queues.setdefault(self._session_id, []).append(request)
            self._refresh_controls()
        else:
            self._start_request(self._session_id, request)
        return True

    @staticmethod
    def _workflow_fingerprint(workflow):
        return hashlib.sha256(json.dumps(workflow, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def _start_request(self, session_id, request, *, append_user=True):
        session = get_session(self._store, session_id)
        if session is None or self._closing:
            return
        if append_user:
            append_message(self._store, session_id, "user", request.prompt,
                           images=request.images, files=request.files)
        history = copy.deepcopy(chat_history(session))
        append_message(self._store, session_id, "assistant", "正在处理…")
        message = session["messages"][-1]
        message.update(content="", run_status="running", activity=[], plan=[])
        message["source_files"] = request.context_files
        if not request.context_files:
            message["source_fingerprint"] = self._workflow_fingerprint(request.snapshot.get("workflow"))
        worker = _AIWorker(session_id, request, history, self)
        self._runs[session_id] = _AIRun(worker, request, message)
        self._retry_requests.pop(session_id, None)
        worker.completed.connect(self._on_reply)
        worker.failed.connect(self._on_reply_failed)
        worker.cancelled.connect(self._on_reply_cancelled)
        worker.event_received.connect(self._on_run_event)
        worker.finished.connect(self._on_reply_finished)
        self._persist_sessions()
        self._refresh_session_list()
        self._refresh_controls()
        self._render_chat()
        worker.start()

    def _sender_run(self):
        worker = self.sender()
        if self._closing or worker is None:
            return None
        run = self._runs.get(worker.session_id)
        return run if run is not None and run.worker is worker else None

    def _on_run_event(self, event):
        run = self._sender_run()
        if run is None or run.message["run_status"] != "running":
            return
        kind = event["type"]
        update_controls = kind != "content" or not run.round_content
        if kind == "content":
            if not run.round_content:
                run.status = "正在输出回复…"
            run.content_parts.append(event["text"])
            run.round_content = True
        elif kind == "round":
            if run.round_content:
                run.content_parts.append("\n\n")
                run.round_content = False
            run.status = event["text"]
        elif kind == "plan":
            run.message["plan"] = event["steps"]
        else:
            run.status = event["text"]
            activity = run.message["activity"]
            activity.append(event["text"][:1000])
            del activity[:-MAX_ACTIVITY]
        if not self._checkpoint_timer.isActive():
            self._checkpoint_timer.start()
        if run.worker.session_id == self._session_id:
            if update_controls:
                self._refresh_controls()
            if self.isVisible() and not self._render_timer.isActive():
                self._render_timer.start()

    def _finish_run(self, status, error="", text=None):
        run = self._sender_run()
        if run is None:
            return
        if run.message["run_status"] == "stopping":
            status, error, text = "cancelled", "已停止；已收到的部分内容不代表完整结论。", None
        run.message["run_status"] = status
        run.message["content"] = text if text is not None else "".join(run.content_parts).rstrip()
        if error:
            run.message["error"] = error
        if status != "completed" and run.next_request is None:
            self._retry_requests[run.worker.session_id] = run.request
            self._discard_queue(run.worker.session_id)
        self._persist_sessions()
        self._refresh_session_list()
        if run.worker.session_id == self._session_id:
            self._render_chat()

    def _on_reply(self, text: str):
        self._finish_run("completed", text=text)

    def _on_reply_failed(self, message: str):
        self._finish_run("failed", "请求失败：" + message)

    def _on_reply_cancelled(self):
        self._finish_run("cancelled", "已停止；已收到的部分内容不代表完整结论。")

    def _on_reply_finished(self):
        run = self._sender_run()
        if run is None:
            return
        if run.message["run_status"] in {"running", "stopping"}:
            self._finish_run("failed", "后台任务在完成前退出，原因未知；本次结果不完整。")
        session_id = run.worker.session_id
        del self._runs[session_id]
        run.worker.deleteLater()
        if not self._runs:
            self._checkpoint_timer.stop()
        queue = self._queues.get(session_id, [])
        if run.next_request is not None:
            self._start_request(session_id, run.next_request)
        elif run.message["run_status"] == "completed" and queue:
            request = queue.pop(0)
            if not queue:
                self._queues.pop(session_id, None)
            self._start_request(session_id, request)
        self._refresh_session_list()
        self._refresh_controls()

    def _discard_queue(self, session_id):
        for request in self._queues.pop(session_id, []):
            self._remove_request_attachments(request)

    @staticmethod
    def _remove_request_attachments(request):
        for item in request.images + request.files:
            if os.path.isfile(item["path"]):
                os.remove(item["path"])

    def _remove_queued_request(self):
        queue = self._queues.get(self._session_id, [])
        index = self.queue_list.currentRow()
        if 0 <= index < len(queue):
            self._remove_request_attachments(queue.pop(index))
            if not queue:
                self._queues.pop(self._session_id, None)
            self._refresh_controls()

    def stop_current_task(self):
        run = self._runs.get(self._session_id)
        if run is None:
            return
        if run.next_request is not None:
            self._remove_request_attachments(run.next_request)
            run.next_request = None
        self._discard_queue(self._session_id)
        run.message["run_status"] = "stopping"
        run.status = "正在停止当前请求…"
        run.worker.cancel()
        self._refresh_controls()
        self._render_chat()

    def retry_current_task(self):
        if self._session_id in self._runs or len(self._runs) >= _MAX_ACTIVE_TASKS:
            return
        request = self._retry_requests.get(self._session_id)
        if request is not None:
            self._start_request(self._session_id, request, append_user=False)


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
        self._check_draft_size(len(data))
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
        self._check_draft_size(len(data))
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

    def _check_draft_size(self, extra):
        drafts = [draft for session_id, draft in self._drafts.items() if session_id != self._session_id]
        drafts.append({"images": self._pending_images, "files": self._pending_files})
        total = sum(len(item["data"]) for draft in drafts for item in draft.get("images", []) + draft.get("files", []))
        if total + extra > 64 * 1024 * 1024:
            raise ValueError("所有会话的待发送附件合计不能超过 64 MB，请先发送或移除附件。")

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
