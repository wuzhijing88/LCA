from .workflow_view_common import *
from .workflow_view_card_layout_mixin import WorkflowViewCardLayoutMixin
from .workflow_view_clipboard_undo_mixin import WorkflowViewClipboardUndoMixin
from .workflow_view_connection_mixin import WorkflowViewConnectionMixin
from .workflow_view_delete_edit_mixin import WorkflowViewDeleteEditMixin
from .workflow_view_identity_mixin import WorkflowViewIdentityMixin
from .workflow_view_io_mixin import WorkflowViewIoMixin
from .workflow_view_render_mixin import WorkflowViewRenderMixin


class WorkflowView(
    WorkflowViewRenderMixin,
    WorkflowViewCardLayoutMixin,
    WorkflowViewConnectionMixin,
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
            self.scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)

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

        # Line Dragging State
        self.connections: List[ConnectionLine] = []
        self.is_dragging_line = False
        self.drag_start_card: Optional[TaskCard] = None
        self.drag_start_port_type: Optional[str] = None
        self.temp_line: Optional[QGraphicsLineItem] = None
        self.temp_line_pen = QPen(Qt.GlobalColor.black, 1.0, Qt.PenStyle.DashLine) # Dashed line for temp
        self.temp_line_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        self.temp_line_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        self.temp_line_pen.setDashPattern([6, 4])
        self.temp_line_pen.setCosmetic(True)
        self.temp_line_snap_pen = QPen(QColor(0, 120, 215), 2.0, Qt.PenStyle.DashLine) # Blue, thicker when snapping
        self.temp_line_snap_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        self.temp_line_snap_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        self.temp_line_snap_pen.setDashPattern([6, 4])
        self.temp_line_snap_pen.setCosmetic(True)

        # Snapping state
        self.is_snapped = False
        self.snapped_target_card: Optional[TaskCard] = None

        # Store cards for easy access
        self.cards: Dict[int, TaskCard] = {}
        self._next_card_id = 0
        self._max_loaded_id = -1 # Track max ID during loading
        self._cache_policy_cache_disabled: Optional[bool] = None
        self._cache_policy_shadow_disabled: Optional[bool] = None
        self._render_cache_guard_timer: Optional[QTimer] = None
        self._dragging_item = None
        self._line_start_item: Optional[TaskCard] = None
        self._connection_type_to_draw: ConnectionType = ConnectionType.SUCCESS

        try:
            # Keep Qt render caches in a bounded loop during long-running animation sessions.
            self._render_cache_guard_timer = QTimer(self)
            self._render_cache_guard_timer.setInterval(15000)
            self._render_cache_guard_timer.timeout.connect(self._on_render_cache_guard_tick)
            self._render_cache_guard_timer.start()
        except Exception:
            self._render_cache_guard_timer = None

        # --- Log initialization --- 
        log_func = logging.info if logging.getLogger().hasHandlers() else print
        log_func("WorkflowView Initialized.")

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

        # 防重入标志：防止 _block_edit_if_running 循环弹窗
        self._is_showing_block_dialog = False

        # 网格设置
        self._grid_enabled = False
        self._grid_spacing = 20  # 网格点间距
        self._grid_dot_size = 1.4  # 网格点大小
        self._card_snap_enabled = True  # 卡片间吸附（卡片对齐）开关
