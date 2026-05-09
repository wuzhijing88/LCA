import copy
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QThread, QTimer

from task_workflow.executor import WorkflowExecutor

logger = logging.getLogger(__name__)


class MainWindowInitStateMixin:
    def _verify_main_window_registration(self):
        return

    def _initialize_main_window_core_state(
        self,
        task_modules: Dict[str, Any],
        initial_config: dict,
        hardware_id: str,
        license_key: str,
        save_config_func,
        images_dir: str,
        task_state_manager=None,
    ):
        from .main_window_support import normalize_execution_mode_setting

        self.task_modules = task_modules # Store the task modules

        self.save_config_func = save_config_func # Store the save function

        self.hardware_id = hardware_id # Store validated HW ID

        self.license_key = license_key # Store validated license key

        # 【插件模式授权检查】在主窗口初始化时检查插件模式配置

        # 如果配置中启用了插件模式但没有有效授权，自动禁用

        # 注意：SERVER_VALIDATION_DISABLED表示服务器验证关闭，这是有效状态

        plugin_settings = initial_config.get('plugin_settings', {})

        plugin_enabled = plugin_settings.get('enabled', False)

        if plugin_enabled:

            # 只有在真正没有授权码时才禁用（SERVER_VALIDATION_DISABLED是有效状态）

            if not license_key or (license_key != "SERVER_VALIDATION_DISABLED" and license_key in ["NO_LICENSE_REQUIRED"]):

                logger.critical("检测到配置中启用了插件模式，但未找到有效的授权码")

                logger.warning("将自动禁用插件模式，用户需要在全局设置中重新授权后才能启用")

                # 禁用插件模式

                if 'plugin_settings' not in initial_config:

                    initial_config['plugin_settings'] = {}

                initial_config['plugin_settings']['enabled'] = False

                # 立即保存配置

                try:

                    save_config_func(initial_config)

                    logger.info("已自动禁用插件模式并保存配置")

                except Exception as save_error:

                    logger.error(f"保存禁用插件模式配置失败: {save_error}")

            else:

                logger.info("插件模式本地检查通过")

        self.images_dir = images_dir # <<< RE-ADDED: Store images directory

        self.current_save_path = None # Store path for potential future "Save" without dialog

        # --- MOVED: Initialize unsaved_changes early ---

        self.unsaved_changes = False

        # ---------------------------------------------

        self.executor_thread: Optional[QThread] = None # Thread for execution

        self.executor: Optional[WorkflowExecutor] = None # Executor instance

        self.config = copy.deepcopy(initial_config) # Store initial config

        self._global_settings_dialog = None

        self._init_ntfy_notifier()

        # 新增的窗口绑定配置

        self.config.setdefault('plugin_bound_windows', [])

        self.config.setdefault('plugin_window_binding_mode', 'single')

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

        self.current_execution_mode = normalize_execution_mode_setting(

            self.config.get('execution_mode', 'background_sendmessage')

        ) # Load from config

        logger.info(f"从配置加载执行模式: {self.current_execution_mode}")

        try:

            from utils.foreground_input_manager import get_foreground_input_manager

            foreground_input = get_foreground_input_manager()

            legacy_backend = str(self.config.get('foreground_driver_backend', 'interception') or 'interception').strip().lower()

            mouse_backend = str(self.config.get('foreground_mouse_driver_backend', legacy_backend) or legacy_backend).strip().lower()

            keyboard_backend = str(self.config.get('foreground_keyboard_driver_backend', legacy_backend) or legacy_backend).strip().lower()

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

        # 操作模式配置 - 默认使用自动检测

        self.operation_mode = 'auto'

        # 快捷键配置

        self.start_task_hotkey = self.config.get('start_task_hotkey', 'XButton1')

        self.stop_task_hotkey = self.config.get('stop_task_hotkey', 'XButton2')

        self.pause_workflow_hotkey = self.config.get('pause_workflow_hotkey', 'F11')

        self.record_hotkey = self.config.get('record_hotkey', 'F12')

        self.replay_hotkey = self.config.get('replay_hotkey', 'F10')

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

        # --- ADDED: Global timer for auto-stop ---

        self._global_timer = QTimer(self)

        self._global_timer.setSingleShot(True)  # 设置为单次触发

        self._global_timer.timeout.connect(self._on_global_timer_timeout)

        # 从配置加载定时器设置

        self._global_timer_enabled = self.config.get('timer_enabled', False)

        self._global_timer_duration = 0  # 秒

        # 随机暂停功能相关变量

        self._random_pause_enabled = self.config.get('pause_enabled', False)

        self._random_pause_timer = QTimer(self)  # 随机暂停检查定时器

        self._random_pause_timer.timeout.connect(self._on_random_pause_check)

        self._is_paused = False  # 当前是否处于暂停状态

        self._pause_probability = self.config.get('pause_probability', 20)

        self._pause_check_interval = self.config.get('pause_check_interval', 30)

        self._pause_check_interval_unit = self.config.get('pause_check_interval_unit', '秒')

        self._pause_min_value = self.config.get('pause_min_value', 60)

        self._pause_min_unit = self.config.get('pause_min_unit', '秒')

        self._pause_max_value = self.config.get('pause_max_value', 120)

        self._pause_max_unit = self.config.get('pause_max_unit', '秒')

        # 定时暂停功能相关变量

        self._timed_pause_enabled = self.config.get('timed_pause_enabled', False)

        self._timed_pause_hour = self.config.get('timed_pause_hour', 12)

        self._timed_pause_minute = self.config.get('timed_pause_minute', 0)

        self._timed_pause_repeat = self.config.get('timed_pause_repeat', 'daily')

        self._timed_pause_duration_value = self.config.get('timed_pause_duration_value', 10)

        self._timed_pause_duration_unit = self.config.get('timed_pause_duration_unit', '分钟')

        self._timed_pause_timer = QTimer(self)

        self._timed_pause_timer.timeout.connect(self._check_timed_pause_time)

        self._timed_pause_executed = False

        self._timed_pause_last_exec_date = None

        self._timed_pause_resume_timer = QTimer(self)

        self._timed_pause_resume_timer.setSingleShot(True)

        self._timed_pause_resume_timer.timeout.connect(self._on_timed_pause_resume_timeout)

        self._auto_pause_source = None  # random / timed

        # ------------------------------------------

        # --- 定时启动功能相关变量 ---

        self._schedule_enabled = self.config.get('enable_schedule', False)

        self._schedule_hour = self.config.get('schedule_hour', 9)

        self._schedule_minute = self.config.get('schedule_minute', 0)

        self._schedule_repeat = self.config.get('schedule_repeat', 'daily')

        schedule_mode = str(self.config.get('schedule_mode', 'fixed_time') or '').strip().lower()

        self._schedule_mode = 'interval' if schedule_mode == 'interval' else 'fixed_time'

        try:

            self._schedule_interval_value = max(1, int(self.config.get('schedule_interval_value', 5) or 5))

        except (TypeError, ValueError):

            self._schedule_interval_value = 5

        schedule_interval_unit = str(self.config.get('schedule_interval_unit', '分钟') or '').strip()

        self._schedule_interval_unit = schedule_interval_unit if schedule_interval_unit in ('秒', '分钟', '小时') else '分钟'

        self._schedule_next_trigger_monotonic = None

        self._schedule_timer = QTimer(self)

        self._schedule_timer.timeout.connect(self._check_schedule_time)

        self._schedule_executed = False  # 标记当天定时任务是否已执行

        self._schedule_last_exec_date = None  # 上次执行日期

        # ------------------------------------------

        # --- 定时停止功能相关变量 ---

        self._stop_hour = self.config.get('stop_hour', 17)

        self._stop_minute = self.config.get('stop_minute', 0)

        self._stop_repeat = self.config.get('stop_repeat', 'daily')

        self._stop_timer = QTimer(self)

        self._stop_timer.timeout.connect(self._check_stop_time)

        self._stop_executed = False  # 标记当天定时停止是否已执行

        self._stop_last_exec_date = None  # 上次执行日期

        # 同一分钟内多种定时动作冲突时，按优先级处理：停止 > 定时暂停 > 定时启动

        self._timer_slot_key = None

        self._timer_slot_priority = -1

        self._timer_slot_action = None

        # ------------------------------------------

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
