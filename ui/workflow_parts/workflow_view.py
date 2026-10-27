from contextlib import ExitStack
import weakref
from PySide6.QtCore import Slot

from .workflow_view_common import *
from .workflow_view_card_layout_mixin import WorkflowViewCardLayoutMixin
from .workflow_view_clipboard_undo_mixin import WorkflowViewClipboardUndoMixin
from .workflow_view_connection_mixin import WorkflowViewConnectionMixin
from .workflow_view_canvas_mixin import WorkflowViewCanvasMixin
from .connection_controller import ConnectionController
from .connection_gesture import ConnectionGesture
from .connection_line import batch_line_display_updates
from .workflow_view_delete_edit_mixin import WorkflowViewDeleteEditMixin
from .workflow_view_identity_mixin import WorkflowViewIdentityMixin
from .workflow_view_io_mixin import WorkflowViewIoMixin
from .workflow_view_render_mixin import WorkflowViewRenderMixin


class WorkflowView(
    WorkflowViewRenderMixin,
    WorkflowViewCardLayoutMixin,
    WorkflowViewConnectionMixin,
    WorkflowViewCanvasMixin,
    WorkflowViewIoMixin,
    WorkflowViewClipboardUndoMixin,
    WorkflowViewDeleteEditMixin,
    WorkflowViewIdentityMixin,
    QGraphicsView,
):
    """The main view widget displaying the workflow scene with task cards."""
    card_moved = Signal(int, QPointF)
    request_paste_card = Signal(QPointF)
    card_added = Signal(TaskCard)
    connection_added = Signal(object, object, str)
    connection_deleted = Signal(object)
    card_deleted = Signal(int)
    test_card_execution_requested = Signal(int)
    test_flow_execution_requested = Signal(int)
    open_sub_workflow_requested = Signal(str)
    copied_card_data: Optional[Dict[str, Any]] = None

    def __init__(self, task_modules: Dict[str, Any], images_dir: str, parent=None):
        super().__init__(parent)
        self.setObjectName("workflowView")
        self.task_modules = task_modules # <-- Store task modules correctly
        self.images_dir = images_dir # <<< ADDED: Store images_dir
        self.workflow_metadata: Dict[str, Any] = {}
        self.main_window = None  # 主窗口引用，用于检查运行状态
        self.task_id = None  # 所属工作流任务 ID，用于绑定工作流上下文
        self.editing_enabled = True  # 是否允许编辑（运行时设为False）

        # 隐藏QAbstractScrollArea默认边框，只保留滚动条本体
        self.setFrameShape(QFrame.Shape.NoFrame)

        # Scene setup
        self.scene = QGraphicsScene(self)
        # --- MODIFIED: Start with a smaller initial scene rect ---
        self.scene.setSceneRect(-500, -300, 1000, 600) # Reasonable starting size
        # -----------------------------------------------------
        self.setScene(self.scene)
        
        # --- MODIFIED: Change Scroll Bar Policy ---
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # 注释已清理（原注释编码损坏）
        self._corner_widget = QWidget(self)
        self._corner_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._corner_widget.setStyleSheet("background: transparent; border: none;")
        self.setCornerWidget(self._corner_widget)
        # ---------------------------------------

        # Render hints - 激进性能优化
        self.setRenderHint(QPainter.RenderHint.Antialiasing, False)  # 禁用抗锯齿提升性能
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        # 注释已清理（原注释编码损坏）

        # 优化渲染性能
        self.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing, False)
        self.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontSavePainterState, False)

        # 场景索引优化
        if self.scene:
            self.scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.BspTreeIndex)

        # 禁用默认拖拽，手动实现平移以提升流畅度
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setInteractive(True)

        # 注释已清理（原注释编码损坏）
        self._is_panning = False
        self._pan_start_x = 0
        self._pan_start_y = 0
        self._last_pan_step_ms = 0.0
        self._pan_frame_interval_ms = 16
        self._drag_preview_mode = False
        self._drag_preview_saved_state: Dict[str, Any] = {}

        # 设置焦点策略，确保能接收键盘事件
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # 确保视图可以接收键盘事件
        self.setFocus()

        # Context menu setup
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)  # 恢复此连接

        # Set window title
        self.setWindowTitle("工作流视图")
        
        # Enable drag and drop
        self.setAcceptDrops(True)

        self.zoom_factor_base = 1.15

        self.connections: List[ConnectionLine] = []
        self._connection_controller = ConnectionController(self)
        self._connection_gesture = ConnectionGesture(self)
        self._canvas_connections_paused = False

        # Store cards for easy access
        self.cards: Dict[int, TaskCard] = {}
        self._viewport_cards = weakref.WeakSet()
        self._cache_policy_cache_disabled: Optional[bool] = None
        self._cache_policy_shadow_disabled: Optional[bool] = None
        self._card_cache_zoom: Optional[float] = None
        self._render_cache_guard_timer: Optional[QTimer] = None
        self._dragging_item = None

        self._render_cache_guard_timer = QTimer(self)
        self._render_cache_guard_timer.setInterval(15000)
        self._render_cache_guard_timer.timeout.connect(self._on_render_cache_guard_tick)

        self._deferred_view_position_timer: Optional[QTimer] = QTimer(self)
        self._deferred_view_position_timer.setSingleShot(True)
        self._deferred_view_position_timer.setInterval(100)
        self._deferred_view_position_timer.timeout.connect(self._apply_deferred_view_position)
        self._deferred_view_position_pending = False
        self._deferred_view_center: Optional[QPointF] = None

        # --- Demo Setup Removed --- 
        # The user will add cards manually now

        # Restore state variables for right-click handling in the view
        self._original_drag_mode = self.dragMode()
        self._right_mouse_pressed = False
        self._last_right_click_global_pos: Optional[QPointF] = None # Keep for potential future use, but not used now
        self._last_right_click_view_pos_f: Optional[QPointF] = None # <-- ADDED: Store precise view pos (float)
        # 注意：copied_card_data 使用类变量，不在此初始化，以支持跨标签页粘贴

        # 撤销系统
        self.undo_stack: List[Dict[str, Any]] = []  # 撤销历史栈
        self.max_undo_steps = 50  # 最大撤销步数
        self._deleting_card = False  # 标志：正在删除卡片，防止连线删除触发额外撤销
        self._deleting_cards = set()  # BUG FIX: 使用集合存储正在删除的卡片ID，防止重复删除
        self._loading_workflow = False  # 标志：正在加载工作流，防止连线删除触发撤销保存
        self._rerouting_connections = False
        self._updating_sequence = False  # 标志：正在更新序列显示，防止连线重建触发撤销保存
        self._undoing_operation = False  # 标志：正在执行撤销操作，防止撤销过程中的操作触发新的撤销保存
        
        # --- ADDED: Connect scroll bar signals for dynamic scene expansion ---
        # --- RE-ENABLED: Uncommented to restore dynamic scene expansion --- 
        self.horizontalScrollBar().valueChanged.connect(self._handle_scroll_change)
        self.verticalScrollBar().valueChanged.connect(self._handle_scroll_change)
        # --------------------------------------------------------------------
        # --- END ADDED ---

        # <<< ADDED: Track flashing cards >>>
        self.flashing_card_ids = set()
        # <<< END ADDED >>>

        # 网格设置
        self._grid_enabled = False
        self._grid_spacing = 20  # 网格点间距
        self._grid_dot_size = 1.4  # 网格点大小
        self._card_snap_enabled = True  # 卡片间吸附（卡片对齐）开关

        # 页面可能由外部直接关闭（例如窗口退出或标签页容器被销毁），
        # 不能只依赖 WorkflowTabWidget 的关闭路径来释放场景资源。
        self._resources_cleaned_up = False
        # 主窗口关闭不会向子视图递送 closeEvent，应用退出必须主动卸载。
        QApplication.instance().aboutToQuit.connect(self.dispose_resources)

    def clear_workflow(self):
        if not self._loading_workflow and self._is_workflow_running():
            return False
        with batch_line_display_updates():
            self._cancel_deferred_view_position()
            self._cancel_canvas_panning()
            self._cleanup_drag_state()
            self._clear_all_snap_guide_lines(commit=False)
            self.set_canvas_drag_paused(False)
            result = WorkflowViewCardLayoutMixin.clear_workflow(self)
            self._viewport_cards.clear()
            self.flashing_card_ids.clear()
            self._sync_scene_rect_to_content()
        return result

    @Slot()
    def dispose_resources(self):
        """关闭与清空共用资源卸载入口，关闭时不受运行状态限制。"""
        if self._resources_cleaned_up:
            return
        self._resources_cleaned_up = True
        # 清场失败仍释放其余资源，异常由调用方接收，不静默吞掉。
        with ExitStack() as cleanup:
            cleanup.callback(self._connection_controller.dispose)
            cleanup.callback(self.set_canvas_drag_paused, False)
            cleanup.callback(self._release_render_cache_guard)
            cleanup.callback(self._release_deferred_view_position)
            cleanup.callback(self._connection_gesture.dispose)
            QApplication.instance().aboutToQuit.disconnect(self.dispose_resources)
            loading = self._loading_workflow
            self._loading_workflow = True
            try:
                self.clear_workflow()
            finally:
                self._loading_workflow = loading

    def _release_render_cache_guard(self):
        timer, self._render_cache_guard_timer = self._render_cache_guard_timer, None
        if timer is not None:
            timer.stop()
            timer.timeout.disconnect(self._on_render_cache_guard_tick)
            timer.deleteLater()

    def _release_deferred_view_position(self):
        self._cancel_deferred_view_position()
        timer, self._deferred_view_position_timer = self._deferred_view_position_timer, None
        if timer is not None:
            timer.timeout.disconnect(self._apply_deferred_view_position)
            timer.deleteLater()

    def closeEvent(self, event):
        self.dispose_resources()
        super().closeEvent(event)
