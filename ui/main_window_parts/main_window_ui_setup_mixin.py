import logging
import os
from typing import Any, Dict

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..widgets.custom_title_bar import CustomTitleBar
from ..panels.parameter_panel import ParameterPanel
from utils.app_paths import get_resource_path
from utils.window_coordinate_common import (
    clamp_preferred_window_size,
    get_available_geometry_for_widget,
)

logger = logging.getLogger(__name__)


class MainWindowUiSetupMixin:
    def _setup_main_window_ui(self):
        # --- Initial Window Setup ---
        available_geometry = get_available_geometry_for_widget(global_pos=QCursor.pos())
        initial_width, initial_height = clamp_preferred_window_size(1000, 700, available_geometry)
        if available_geometry and not available_geometry.isEmpty():
            initial_x = available_geometry.left() + max(0, (available_geometry.width() - initial_width) // 2)
            initial_y = available_geometry.top() + max(0, (available_geometry.height() - initial_height) // 2)
        else:
            initial_x, initial_y = 100, 100
        self.setGeometry(initial_x, initial_y, initial_width, initial_height) # Slightly larger window
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        # 使用不透明背景，避免输入控件/弹出层在透明窗口下渲染异常
        # Store corner radius for consistent use
        self._corner_radius = 10.0
        # Apply rounded corners (Windows 11 native API or Windows 10 custom painting)
        # Set FORCE_CUSTOM_ROUNDED=1 environment variable to test Windows 10 mode on Windows 11
        force_custom = os.environ.get('FORCE_CUSTOM_ROUNDED', '0') == '1'
        self._is_win11_rounded = False
        if not force_custom:
            try:
                import ctypes
                from ctypes import wintypes
                hwnd = int(self.winId())
                # Try Windows 11 DWM API first
                DWMWA_WINDOW_CORNER_PREFERENCE = 33
                DWMWCP_ROUND = 2
                preference = wintypes.DWORD(DWMWCP_ROUND)
                result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    DWMWA_WINDOW_CORNER_PREFERENCE,
                    ctypes.byref(preference),
                    ctypes.sizeof(preference)
                )
                if result == 0:
                    self._is_win11_rounded = True
                    logger.info("已应用 Windows 11 原生圆角效果")
                else:
                    raise Exception("DWM API 调用失败")
            except Exception as e:
                logger.info(f"Windows 11 圆角 API 不可用，将使用自定义绘制圆角: {e}")
                # Windows 10 will use custom painting in paintEvent
        else:
            logger.info("强制使用自定义绘制圆角模式（Windows 10 兼容模式）")
        # 设置窗口图标
        try:
            from PySide6.QtGui import QIcon
            icon_path = get_resource_path("icon.ico")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
                logger.info(f"窗口图标已设置: {icon_path}")
            else:
                logger.warning(f"图标文件不存在: {icon_path}")
        except Exception as e:
            logger.warning(f"设置窗口图标失败: {e}")
        # 确保主窗口能够接收键盘事件（特别是F10）
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_KeyCompression, False)  # 禁用按键压缩，确保所有按键事件都被处理
        # 多任务系统初始化 ---
        from ..workflow_parts.workflow_task_manager import WorkflowTaskManager
        from ..workflow_parts.workflow_tab_widget import WorkflowTabWidget
        from ..workflow_parts.task_execution_panel import TaskExecutionPanel
        # 创建任务管理器
        self.task_manager = WorkflowTaskManager(
            task_modules=self.task_modules,
            images_dir=self.images_dir,
            config=self.config,
            parent=self
        )
        # 连接任务管理器信号，用于更新工具栏按钮状态
        self.task_manager.task_status_changed.connect(self._on_task_status_changed)
        self.task_manager.all_tasks_completed.connect(self._on_all_tasks_completed)
        # 创建标签页控件（替代原来的单个workflow_view）
        self.workflow_tab_widget = WorkflowTabWidget(
            task_manager=self.task_manager,
            task_modules=self.task_modules,
            images_dir=self.images_dir,
            parent=self
        )
        self.workflow_tab_widget.setObjectName("workflowTabs")
        self.workflow_tab_widget.tabBar().setObjectName("workflowTabBar")
        # 兼容性：保留workflow_view引用（指向当前选中的WorkflowView）
        self.workflow_view = None  # 将在标签页切换时更新
        # 创建任务执行控制面板（已移至全局设置，保留对象但不显示）
        self.execution_panel = TaskExecutionPanel(
            task_manager=self.task_manager,
            parent=self
        )
        # 执行面板永久隐藏（功能已移至全局设置）
        self.execution_panel.setVisible(False)
        self.execution_panel.hide()
        # 多任务系统初始化完成 ---
        # --- ADDED: Initialize parameter panel ---
        self.parameter_panel = ParameterPanel(parent=self)
        self.parameter_panel.parameters_changed.connect(self._on_parameter_changed)
        self.parameter_panel.panel_closed.connect(self._on_parameter_panel_closed)
        self.parameter_panel.request_delete_random_connection.connect(self._on_delete_random_connection)
        self.parameter_panel.custom_name_changed.connect(self._on_card_custom_name_changed)
        # 连接收藏功能信号
        self.parameter_panel.workflow_execute_requested.connect(self._on_favorite_workflow_execute)
        self.parameter_panel.workflow_open_requested.connect(self._on_favorite_workflow_open)
        self.parameter_panel.batch_execute_requested.connect(self._on_batch_workflow_execute)
        self.parameter_panel.workflow_check_changed.connect(self._on_favorite_workflow_check_changed)
        self.parameter_panel.favorites_opened.connect(self._on_favorites_opened)
        # 应用参数面板吸附设置
        self.parameter_panel.set_snap_to_parent_enabled(self.enable_parameter_panel_snap)
        # --- MOVED: Create actions AFTER workflow_view exists ---
        self._create_actions()
        # ------------------------------------------------------
        # 连接标签页切换信号，更新workflow_view引用
        self.workflow_tab_widget.current_workflow_changed.connect(self._on_current_workflow_changed)
        self.workflow_tab_widget.workflow_renamed.connect(self._on_workflow_renamed)
        # 连接任务管理器信号，控制UI显示/隐藏
        self.task_manager.task_added.connect(self._on_task_count_changed)
        self.task_manager.task_removed.connect(self._on_task_count_changed)
        # 任务运行时信号绑定表（用于成对解绑，避免残留回调）
        self._task_signal_bindings: Dict[int, Dict[str, Any]] = {}
        # 运行变量持久化统计
        self._runtime_var_persist_stats: Dict[str, Any] = {
            "calls": 0,
            "serialize_calls": 0,
            "save_failed": 0,
            "last_task_id": None,
        }
        self.task_manager.task_added.connect(self._on_task_added_for_jump)  # 连接任务的跳转信号
        self.task_manager.task_removed.connect(self._on_task_removed_for_jump)
        # 补连已有任务（避免启动时加载的任务未绑定信号）
        try:
            for task in self.task_manager.get_all_tasks():
                self._on_task_added_for_jump(task.task_id)
        except Exception as exc:
            logger.warning(f"初始化任务信号绑定失败: {exc}")
        # Central Widget setup
        self.central_container = QWidget(self)
        self.main_layout = QVBoxLayout(self.central_container)
        # Add small margins to prevent content from covering rounded corners
        self.main_layout.setContentsMargins(1, 1, 1, 1)
        self.main_layout.setSpacing(0)
        # --- Custom Title Bar ---
        # Create the list of actions AFTER _create_actions has run
        title_bar_actions = [self.toggle_action, self.save_action, self.load_action, self.new_workflow_action, self.run_action, self.debug_run_action, self.timer_action, self.variable_pool_action, self.global_settings_action]
        self.title_bar = CustomTitleBar(self, actions=title_bar_actions)
        self.main_layout.addWidget(self.title_bar)
        self.title_bar.set_file_actions_visible(self.file_actions_visible)
        # 为定时器按钮设置特殊样式（放大字体和颜色）
        if self.timer_action in self.title_bar.action_buttons:
            timer_button = self.title_bar.action_buttons[self.timer_action]
            timer_button.setIconSize(QSize(26, 26))  # 设置图标大小
            # 不再使用硬编码样式，让全局主题控制按钮样式
            # 按钮样式现在由 themes/dark.qss 和 themes/light.qss 中的 #CustomTitleBar QToolButton 统一管理
        if self.run_action in self.title_bar.action_buttons:
            run_button = self.title_bar.action_buttons[self.run_action]
            run_button.setIconSize(QSize(24, 24))
        # 初始化工具栏（注释代码已移除）
        # --- Add DPI Notification Widget ---
        from ..system_parts.dpi_notification_widget import DPINotificationWidget
        self.dpi_notification = DPINotificationWidget(self)
        self.dpi_notification.hide()  # 初始隐藏
        self.dpi_notification.recalibrate_requested.connect(self._handle_dpi_recalibration)
        self.dpi_notification.dismiss_requested.connect(self._handle_dpi_dismiss)
        self.dpi_notification.auto_adjust_requested.connect(self._handle_dpi_auto_adjust)
        self.main_layout.addWidget(self.dpi_notification)
        # 设置统一DPI处理器和变化检测
        self._setup_dpi_monitoring()
        # 添加标签页控件（替代原来的单个workflow_view）
        self.main_layout.addWidget(self.workflow_tab_widget)
        # <<< ADDED: Prevent child widgets from filling background over rounded corners >>>
        self.central_container.setAutoFillBackground(False)
        self.workflow_tab_widget.setAutoFillBackground(False)
        # -----------------------------------------------------------------------------
        # 任务执行控制面板已移至全局设置，此处不再显示
        # self.main_layout.addWidget(self.execution_panel)
        # --- ADDED: Step Detail Label ---
        self.step_detail_label = QLabel("等待执行...")
        self.step_detail_label.setObjectName("stepDetailLabel")
        self.step_detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.step_detail_label.setMaximumHeight(50)
        self._set_step_detail_style()
        self.main_layout.addWidget(self.step_detail_label)
        font = self.step_detail_label.font()
        font.setPointSize(9)
        font.setBold(True)
        self.step_detail_label.setFont(font)
        # 注册主题切换回调，确保状态栏跟随主题变化
        try:
            from themes import get_theme_manager
            theme_manager = get_theme_manager()
            def on_theme_changed_status_bar(_theme_name):
                self._set_step_detail_style()
                self._refresh_theme_sensitive_action_icons()
            self._status_bar_theme_callback = on_theme_changed_status_bar
            theme_manager.register_theme_change_callback(on_theme_changed_status_bar)
        except Exception as e:
            logging.warning(f"注册状态栏主题回调失败: {e}")
        # 注册主题切换回调，确保卡片颜色跟随主题变化
        try:
            from themes import get_theme_manager
            theme_manager = get_theme_manager()
            def on_theme_changed_cards(_theme_name):
                try:
                    if hasattr(self, 'workflow_view') and self.workflow_view:
                        self.workflow_view.refresh_all_cards_theme()
                    if hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget:
                        for view in self.workflow_tab_widget.task_views.values():
                            if hasattr(view, 'refresh_all_cards_theme'):
                                view.refresh_all_cards_theme()
                except Exception as exc:
                    logging.warning(f"刷新卡片主题失败: {exc}")
            self._card_theme_callback = on_theme_changed_cards
            theme_manager.register_theme_change_callback(on_theme_changed_cards)
        except Exception as e:
            logging.warning(f"注册卡片主题回调失败: {e}")
        # --- END ADDED --- 
        self.setCentralWidget(self.central_container) # Set the container as central widget
        # --- ADDED: Connect task card parameter editing to parameter panel ---
        self._connect_parameter_panel_signals()
    def _finalize_main_window_startup(self):
        # Set initial window title including target
        self._update_main_window_title()

        # --- Apply Initial Window Resize (if configured) ---
        self._initial_window_resize_started = False
        self._initial_window_resize_thread = None
        self._schedule_initial_window_resize()
        # -----------------------------------------------------
        # --- Start DPI Monitoring ---
        self.start_dpi_monitoring()
        # ----------------------------
        # --- 连接快捷键信号到槽函数 ---
        # keyboard 回调通过发射信号，确保在主线程执行
        self.hotkey_start_signal.connect(self.safe_start_tasks)
        self.hotkey_stop_signal.connect(self.safe_stop_tasks)
        logger.info("快捷键信号已连接到安全执行方法")
        # ----------------------------
        # --- 设置全局快捷键 ---
        self._update_hotkeys()
        # ---------------------
        # --- 初始化浮动状态窗口 ---
        self._init_floating_status_window()
        # -------------------------
        # 首次启动提示：显示多任务系统使用提示
        QTimer.singleShot(500, self._show_welcome_hint)
    def keyPressEvent(self, event: QEvent) -> None:
        """Handle key presses for shortcuts like Ctrl+S, Ctrl+O, etc."""
        # 注意：F9/F10 等功能键由 keyboard 库的全局快捷键系统处理
        # 这里只处理 Ctrl 组合键等非全局快捷键
        # --- 已禁用：F9/F10 硬编码处理（现由 keyboard 库统一管理）---
        # 原因：keyboard 库使用 suppress=True 全局拦截快捷键
        #      在 keyPressEvent 中处理会导致重复执行和冲突
        # if event.key() == Qt.Key.Key_F10:
        #     self.safe_stop_tasks()
        # elif event.key() == Qt.Key.Key_F9:
        #     self.run_workflow()
        # ---------------------------------------------------------------
        # 处理其他快捷键（例如 Ctrl+S, Ctrl+O 等）
        super().keyPressEvent(event) # Pass all keys to the base class
    def changeEvent(self, event: QEvent) -> None:
        # Keep changeEvent for maximize icon updates
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            current_state = self.windowState()
            logger.debug(f"[主窗口] changeEvent - WindowStateChange: current_state={current_state}, isMinimized={self.isMinimized()}")
            if hasattr(self, 'title_bar') and self.title_bar and hasattr(self.title_bar, '_update_maximize_icon'):
                # 使用定时器延迟更新，确保状态变化完全完成
                QTimer.singleShot(10, lambda: self.title_bar._update_maximize_icon(self.windowState()))
            # 同步参数面板的窗口状态（从任务栏恢复时触发）
            if hasattr(self, 'parameter_panel'):
                logger.debug(f"[主窗口] 调用 parameter_panel.sync_window_state({self.windowState()})")
                self.parameter_panel.sync_window_state(self.windowState())
            # 更新浮动窗口可见性
            if hasattr(self, '_floating_controller') and self._floating_controller:
                self._floating_controller.on_main_window_state_changed(self.isMinimized())
        elif event.type() == QEvent.Type.ActivationChange:
            # 智能激活同步：保护参数面板输入框焦点
            if hasattr(self, 'parameter_panel'):
                self._smart_sync_parameter_panel_activation()
    def setWindowTitle(self, title: str) -> None:
        # 限制标题长度，防止遮挡顶部按钮
        max_length = 50  # 最大字符数
        if len(title) > max_length:
            title = title[:max_length - 3] + "..."  # 截断并添加省略号
        if hasattr(self, 'title_bar') and self.title_bar:
            self.title_bar.setWindowTitle(title)
        else:
            super().setWindowTitle(title) 
    def showEvent(self, event):
        """处理窗口显示事件"""
        super().showEvent(event)
        # 触发窗口显示信号（用于更新对话框等待逻辑）
        self.windowShown.emit()
        # 启动定时启动功能检查定时器
        if self._schedule_enabled:
            self._start_schedule_timer()
        # 启动定时停止功能检查定时器
        if self._global_timer_enabled:
            if not self._stop_timer.isActive():
                self._stop_timer.start(1000)  # 每1秒检查，确保准时触发
                logger.info(f"定时停止功能已启用，将在 {self._stop_hour:02d}:{self._stop_minute:02d} 停止")
        # 启动定时暂停功能检查定时器
        if getattr(self, '_timed_pause_enabled', False):
            self._start_timed_pause_timer()
        # 自动加载最近打开的工作流
        if not hasattr(self, '_workflows_auto_loaded'):
            self._workflows_auto_loaded = True
            QTimer.singleShot(200, self._auto_load_recent_workflows)
    def _apply_force_down_popup_to_widget(self, widget):
        """No-op: legacy popup adjustment removed."""
        return
    def paintEvent(self, event):
        """Use default painting to avoid custom side effects."""
        super().paintEvent(event)
    def _apply_rounded_combobox_style(self, widget):
        """No-op: legacy combobox popup styling removed."""
        return
