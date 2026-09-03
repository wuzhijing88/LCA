import copy
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QThread, QTimer

from app_core.config_sections import DEFAULT_HOTKEYS
from task_workflow.executor import WorkflowExecutor

logger = logging.getLogger(__name__)


class MainWindowInitStateMixin:
    def _verify_main_window_registration(self):
        return
    def _initialize_main_window_core_state(
        self,
        task_modules: Dict[str, Any],
        initial_config: dict,
        save_config_func,
        images_dir: str,
        task_state_manager=None,
    ):
        self.task_modules = task_modules # Store the task modules
        self.save_config_func = save_config_func # Store the save function
        self.images_dir = images_dir # <<< RE-ADDED: Store images directory
        self.current_save_path = None # Store path for potential future "Save" without dialog
        # --- MOVED: Initialize unsaved_changes early ---
        self.unsaved_changes = False
        # ---------------------------------------------
        self.executor_thread: Optional[QThread] = None # Thread for execution
        self.executor: Optional[WorkflowExecutor] = None # Executor instance
        self.config = copy.deepcopy(initial_config) # Store initial config
        self._global_settings_dialog = None
        self.enable_card_snap = self.config.get('enable_card_snap', True)
        self.enable_parameter_panel_snap = self.config.get('enable_parameter_panel_snap', True)
        self.enable_floating_status_window = self.config.get('enable_floating_status_window', True)
        self.enable_connection_line_animation = self.config.get('enable_connection_line_animation', True)
        if hasattr(self, '_set_line_animation_paused'):
            self._set_line_animation_paused("user_setting", not self.enable_connection_line_animation)
        self.multi_window_delay = self.config.get('multi_window_delay', 500)
        self._sync_runtime_window_binding_state()
        # 【关键修复】启动时验证绑定窗口是否仍然有效
        # 窗口句柄在每次程序启动时都会变化，需要重新验证
        self._validate_bound_windows_on_startup()
        # 根据窗口绑定模式设置当前目标窗口标题
        if self.window_binding_mode == 'multiple':
            # 多窗口模式：使用第一个启用的窗口标题
            if self.bound_windows:
                enabled_windows = [w for w in self.bound_windows if w.get('enabled', True)]
                if enabled_windows:
                    self.current_target_window_title = enabled_windows[0].get('title')
                else:
                    self.current_target_window_title = None
            else:
                self.current_target_window_title = None
        else:
            # 单窗口模式：使用配置中的 target_window_title
            self.current_target_window_title = self.config.get('target_window_title')
        self._sync_runtime_window_binding_state()
        if self.window_binding_mode != 'multiple' and not self.current_target_window_title:
            self.current_target_window_title = self.config.get('target_window_title')
        self.current_execution_mode = str(self.config.get('execution_mode') or 'background_sendmessage')
        logger.info(f"从配置加载执行模式: {self.current_execution_mode}")
        try:
            from utils.input.foreground_input_manager import get_foreground_input_manager
            from utils.input_simulation import global_input_simulator_manager
            from utils.input_simulation.mode_utils import parse_foreground_backends, resolve_execution_mode
            # 输入模拟器工厂的默认模式必须和配置一致，否则省略参数的调用方会
            # 用工厂自带的出厂默认值创建模拟器。
            global_input_simulator_manager.set_default_operation_mode(
                str(self.config.get('operation_mode') or 'auto').strip().lower()
            )
            global_input_simulator_manager.set_default_execution_mode(
                resolve_execution_mode(self.config) or self.current_execution_mode
            )
            foreground_input = get_foreground_input_manager()
            mouse_backend, keyboard_backend = parse_foreground_backends(self.config)
            ib_driver = str(self.config.get('ibinputsimulator_driver', 'Logitech') or 'Logitech').strip()
            ib_driver_arg = str(self.config.get('ibinputsimulator_driver_arg', '') or '').strip()
            ib_ahk_path = str(self.config.get('ibinputsimulator_ahk_path', '') or '').strip()
            ib_ahk_dir = str(self.config.get('ibinputsimulator_ahk_dir', '') or '').strip()
            if 'ibinputsimulator' in (mouse_backend, keyboard_backend):
                foreground_input.set_ibinputsimulator_driver(ib_driver, ib_driver_arg, ib_ahk_path, ib_ahk_dir)
            foreground_input.set_forced_modes(mouse_backend, keyboard_backend)
            if 'ibinputsimulator' in (mouse_backend, keyboard_backend):
                logger.info("检测到 Ib 前台驱动配置，主进程仅加载配置，不在启动阶段预初始化驱动实例")
        except Exception as e:
            logger.warning(f"加载前台驱动配置失败: {e}")
        logger.info(f"从配置加载窗口绑定模式: {self.window_binding_mode}, 目标窗口: {self.current_target_window_title}")
        # Store custom resolution from config
        self.custom_width = self.config.get('custom_width', 0)
        self.custom_height = self.config.get('custom_height', 0)
        # 操作模式配置 - 保留全局配置中的默认值
        self.operation_mode = self.config.get('operation_mode', 'auto')
        # 快捷键配置
        self.start_task_hotkey = self.config.get('start_task_hotkey', DEFAULT_HOTKEYS['start_task_hotkey'])
        self.stop_task_hotkey = self.config.get('stop_task_hotkey', DEFAULT_HOTKEYS['stop_task_hotkey'])
        self.pause_workflow_hotkey = self.config.get('pause_workflow_hotkey', DEFAULT_HOTKEYS['pause_workflow_hotkey'])
        self.record_hotkey = self.config.get('record_hotkey', DEFAULT_HOTKEYS['record_hotkey'])
        self.replay_hotkey = self.config.get('replay_hotkey', DEFAULT_HOTKEYS['replay_hotkey'])
        self.close_listen_hotkey = self.config.get('close_listen_hotkey', DEFAULT_HOTKEYS['close_listen_hotkey'])
        self._hotkey_listen_enabled = True
        # 应用截图引擎配置（异步初始化，避免主线程首屏阻塞）
        screenshot_engine = self.config.get('screenshot_engine', 'wgc')
        self._startup_engine_init_target = str(screenshot_engine or "").strip().lower()
        self._startup_engine_init_thread = None
        self._startup_engine_init_running = False
        self._runtime_engine_switch_target = ""
        self._runtime_engine_switch_thread = None
        self._runtime_engine_switch_running = False
        self._runtime_engine_switch_lock = threading.Lock()
        self._schedule_startup_screenshot_engine_init(self._startup_engine_init_target)
        # --- ADDED: Store state management systems ---
        self.task_state_manager = task_state_manager
        # 安全操作管理器已移除
        # ---------------------------------------------

        # --- ADDED: Store failed paths during execution ---
        self.failed_paths: List[Tuple[int, str]] = []
        # --------------------------------------------------
        # --- ADDED: Initialize stop task related state variables ---
        self._stop_request_in_progress = False  # 防止重复停止请求
        self._execution_finished_processed = False  # 防止重复处理执行完成事件
        self._execution_started_flag = False  # 标记任务是否已启动
        self._last_finished_task_id = None  # 最近一次完成执行的任务ID
        self._active_jump_timers = []  # 保存活动的跳转定时器，用于停止时取消
        self._jump_cancelled = False  # 标记跳转是否已被取消
        self._is_jumping = False  # 标记当前是否正在跳转过程中
        # ----------------------------------------------------------
        self._setup_main_schedule_runtime()
        # --- 运行时窗口监控定时器 ---
        self._window_monitor_timer = QTimer(self)
        self._window_monitor_timer.timeout.connect(self._check_window_validity_runtime)
        self._window_monitor_interval = 30000  # 每30秒检查一次
        self._window_invalid_count = {}  # 记录每个窗口连续失效次数
        self._window_monitor_enabled = True  # 默认启用
        # ------------------------------------------
        # --- ADDED: Parameter panel state ---
        self._parameter_panel_visible = False
        self._parameter_panel_reposition_timer = QTimer(self)
        self._parameter_panel_reposition_timer.setSingleShot(True)
        self._parameter_panel_reposition_timer.timeout.connect(self._reposition_parameter_panel_if_needed)
