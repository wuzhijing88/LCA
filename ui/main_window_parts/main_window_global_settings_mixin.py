import logging

from PySide6.QtWidgets import QDialog

from utils.window_coordinate_common import center_window_on_widget_screen
from utils.window_activation_utils import show_and_activate_overlay
from utils.window_binding_utils import sync_runtime_window_binding_state

logger = logging.getLogger(__name__)


class MainWindowGlobalSettingsMixin:
    def _present_global_settings_dialog(self, dialog) -> None:

        """统一展示并激活全局设置对话框。"""

        center_window_on_widget_screen(dialog, self)
        show_and_activate_overlay(dialog, log_prefix='全局设置对话框', focus=True)

    def _on_global_settings_finished(self, dialog, result):

        """全局设置对话框结束后的处理"""

        try:

            if result == QDialog.DialogCode.Accepted:

                settings = dialog.get_settings()

                self._apply_global_settings(settings)

        finally:

            if self._global_settings_dialog is dialog:

                self._global_settings_dialog = None

            if hasattr(dialog, "request_delete"):

                dialog.request_delete()

            else:

                dialog.deleteLater()

    def _apply_global_settings(self, settings: dict):

        """应用全局设置对话框返回的配置"""

        from .main_window_support import normalize_execution_mode_setting

        logger.info(f"GlobalSettingsDialog 返回的 bound_windows: {len(settings.get('bound_windows', []))} 个")

        logger.info(f"  窗口列表: {[w.get('title') for w in settings.get('bound_windows', [])]}")

        # 更新本地设置

        self.current_target_window_title = settings.get('active_target_window_title') or settings.get('target_window_title')

        self.current_execution_mode = normalize_execution_mode_setting(

            settings.get('execution_mode', 'background_sendmessage')

        )

        self.operation_mode = 'auto'  # 默认使用自动检测

        self.custom_width = settings.get('custom_width', 0)

        self.custom_height = settings.get('custom_height', 0)

        # 新增的配置项

        self.native_window_binding_mode = settings.get('window_binding_mode', 'single')

        self.plugin_window_binding_mode = settings.get('plugin_window_binding_mode', 'single')

        self.window_binding_mode = settings.get('active_window_binding_mode', self.native_window_binding_mode)

        self.native_bound_windows = settings.get('bound_windows', [])

        self.plugin_bound_windows = settings.get('plugin_bound_windows', [])

        self.bound_windows = settings.get('active_bound_windows', self.native_bound_windows)

        self.multi_window_delay = settings.get('multi_window_delay', 500)

        logger.info(f"更新后 MainWindow.bound_windows: {len(self.bound_windows)} 个")

        # 快捷键设置

        self.start_task_hotkey = settings.get('start_task_hotkey', 'XButton1')

        self.stop_task_hotkey = settings.get('stop_task_hotkey', 'XButton2')

        self.pause_workflow_hotkey = settings.get('pause_workflow_hotkey', 'F11')

        self.record_hotkey = settings.get('record_hotkey', 'F12')

        self.replay_hotkey = settings.get('replay_hotkey', 'F10')

        # 更新配置字典

        self.config.update(settings)

        self.config['bound_windows'] = self.native_bound_windows

        self.config['plugin_bound_windows'] = self.plugin_bound_windows

        self.config['window_binding_mode'] = self.native_window_binding_mode

        self.config['plugin_window_binding_mode'] = self.plugin_window_binding_mode

        sync_runtime_window_binding_state(self.config)

        self._sync_runtime_window_binding_state()

        if hasattr(self, '_ntfy_notifier') and self._ntfy_notifier:
            try:
                self._ntfy_notifier.reload_settings()
            except Exception as e:
                logger.warning(f"刷新 ntfy 配置失败: {e}")

        # 同步前台驱动配置到运行时管理器

        try:

            from utils.foreground_input_manager import get_foreground_input_manager

            from utils.input_simulation import global_input_simulator_manager

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

                logger.info("检测到 Ib 前台驱动配置变更，主进程仅同步配置，不在设置阶段预初始化驱动实例")

            foreground_input.close()
            global_input_simulator_manager.clear_cache()

        except Exception as e:

            logger.warning(f"同步前台驱动设置失败: {e}")

        # Refresh task execution modes after settings change

        if hasattr(self, 'task_manager'):

            for task in self.task_manager.get_all_tasks():

                self._update_task_execution_mode(task)

        logger.info(f"更新配置字典后，self.config['bound_windows']: {len(self.config.get('bound_windows', []))} 个")

        # 应用截图引擎设置（异步切换，避免设置保存时阻塞主线程）

        screenshot_engine = settings.get('screenshot_engine', 'wgc')

        requested_engine = str(screenshot_engine or "").strip().lower()

        self._schedule_runtime_screenshot_engine_switch(requested_engine)

        # 从配置更新定时启动相关变量

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

        # 从配置更新定时停止相关变量

        self._global_timer_enabled = self.config.get('timer_enabled', False)

        self._stop_hour = self.config.get('stop_hour', 17)

        self._stop_minute = self.config.get('stop_minute', 0)

        self._stop_repeat = self.config.get('stop_repeat', 'daily')

        # 从配置更新定时暂停相关变量

        self._timed_pause_enabled = self.config.get('timed_pause_enabled', False)

        self._timed_pause_hour = self.config.get('timed_pause_hour', 12)

        self._timed_pause_minute = self.config.get('timed_pause_minute', 0)

        self._timed_pause_repeat = self.config.get('timed_pause_repeat', 'daily')

        self._timed_pause_duration_value = self.config.get('timed_pause_duration_value', 10)

        self._timed_pause_duration_unit = self.config.get('timed_pause_duration_unit', '分钟')

        # 更新定时设置

        self._update_schedule_config()

        self._update_stop_config()

        self._update_timed_pause_config()

        # 更新快捷键

        self._update_hotkeys()

        logger.info("全局设置已更新:")

        logger.info(f"  窗口绑定模式: {self.window_binding_mode}")

        if self.window_binding_mode == 'single':

            logger.info(f"  目标窗口: {self.current_target_window_title or '未设置'}")

        else:

            logger.info(f"  绑定窗口数量: {len(self.bound_windows)}")

            enabled_count = sum(1 for w in self.bound_windows if w.get('enabled', True))

            logger.info(f"  启用窗口数量: {enabled_count}")

        logger.info(f"  执行模式: {self.current_execution_mode}")

        logger.info(f"  自定义分辨率: {self.custom_width}x{self.custom_height}")

        if self.window_binding_mode == 'multiple':

            logger.info(f"  多窗口启动延迟: {self.multi_window_delay}ms")

        # 工具 修复：安全地应用自定义分辨率（如果适用）

        try:

            logger.debug("开始应用自定义分辨率设置")

            if self.window_binding_mode == 'multiple':

                logger.debug("使用多窗口分辨率调整")

                self._apply_multi_window_resize()

            else:

                logger.debug("使用单窗口分辨率调整")

                self._apply_initial_window_resize()

            logger.debug("分辨率设置应用完成")

        except Exception as resize_error:

            logger.error(f"应用分辨率设置时发生错误: {resize_error}", exc_info=True)

            # 不中断程序，继续执行后续操作

        # 检查是否需要激活窗口（根据执行模式和窗口状态）

        self._check_window_activation_after_settings_update()

        # 更新窗口标题以显示目标窗口

        self._update_main_window_title()

        # 刷新所有 OCRRegionSelectorWidget 的绑定窗口显示

        self._refresh_all_ocr_region_selectors()

        # 应用画布网格设置

        if hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget:

            grid_enabled = settings.get('enable_canvas_grid', True)

            self.workflow_tab_widget.set_all_grid_enabled(grid_enabled)

            card_snap_enabled = settings.get('enable_card_snap', True)

            self.workflow_tab_widget.set_all_card_snap_enabled(card_snap_enabled)

        # 应用参数面板吸附设置

        parameter_panel_snap_enabled = settings.get('enable_parameter_panel_snap', True)

        self.enable_card_snap = settings.get('enable_card_snap', True)

        self.enable_parameter_panel_snap = parameter_panel_snap_enabled

        self.enable_floating_status_window = settings.get('enable_floating_status_window', True)

        self.enable_connection_line_animation = settings.get('enable_connection_line_animation', True)

        if hasattr(self, 'parameter_panel') and self.parameter_panel:

            self.parameter_panel.set_snap_to_parent_enabled(parameter_panel_snap_enabled)

        if hasattr(self, '_floating_controller') and self._floating_controller:

            self._floating_controller.set_enabled(self.enable_floating_status_window)

        if hasattr(self, '_set_line_animation_paused'):

            self._set_line_animation_paused("user_setting", not self.enable_connection_line_animation)

        # 即时应用自动更新检查开关（无需重启）

        try:

            if hasattr(self, 'update_integration') and self.update_integration:

                enable_update_check = bool(self.config.get('enable_update_check', False))

                self.update_integration.enable(enable_update_check)

        except Exception as update_error:

            logger.warning(f"应用更新检查开关失败: {update_error}")

        # 保存更新后的配置到文件

        try:

            from app_core.config_store import save_config

            save_config(self.config)

            logger.info("配置已保存到文件")

        except ImportError:

            logging.warning("警告: 无法导入 save_config, 全局设置未自动保存到文件。")

        except Exception as e:

            logging.error(f"错误: 保存全局设置时出错: {e}")

            logging.error(f"错误详细信息: {e}", exc_info=True)

            logger.error(f"保存配置时出错: {e}")

            try:

                from PySide6.QtWidgets import QMessageBox

                QMessageBox.critical(self, "保存设置错误", f"保存全局设置时出错: {e}")

            except Exception as msg_error:

                logging.error(f"显示消息框失败: {msg_error}")

                logger.error(f"显示错误消息框失败: {msg_error}")

    def open_global_settings(self):

        """打开全局设置对话框"""

        from ..global_settings_parts.global_settings_dialog import GlobalSettingsDialog

        try:

            if self._global_settings_dialog is not None:

                dialog = self._global_settings_dialog

                if dialog.isVisible():

                    self._present_global_settings_dialog(dialog)

                    return

                self._present_global_settings_dialog(dialog)

                return

            logger.info(f"打开全局设置前，MainWindow.config 中的 bound_windows: {len(self.config.get('bound_windows', []))} 个")

            # 传递 hardware_id 和 license_key 给全局设置对话框，用于插件模式授权验证

            dialog = GlobalSettingsDialog(

                self.config,

                self,

                hardware_id=self.hardware_id,

                license_key=self.license_key

            )

            self._global_settings_dialog = dialog

            dialog.finished.connect(lambda result, dlg=dialog: self._on_global_settings_finished(dlg, result))

            self._present_global_settings_dialog(dialog)

        except Exception as e:

            logging.error(f"打开全局设置对话框时出错: {e}")

            try:

                from ui.dialogs.custom_dialogs import ErrorWrapper

                ErrorWrapper.show_exception(

                    parent=self,

                    error=e,

                    title="设置错误",

                    context="打开全局设置"

                )

            except Exception as dialog_error:

                logging.error(f"显示错误对话框失败: {dialog_error}")

                # 回退到标准消息框

                try:

                    from PySide6.QtWidgets import QMessageBox

                    QMessageBox.critical(self, "错误", f"打开全局设置失败: {e}\n\n{dialog_error}")

                except Exception:

                    pass
