import logging

from PySide6.QtWidgets import QDialog

from app_core.config_sections import DEFAULT_HOTKEYS
from utils.plugin.settings_sync import (
    diff_plugin_settings,
    plugin_settings_view,
    sync_plugin_runtime_after_settings_change,
)
from utils.window.window_coordinate_common import center_window_on_widget_screen
from utils.window.window_activation_utils import show_and_activate_overlay
from utils.window.window_binding_utils import sync_runtime_window_binding_state

logger = logging.getLogger(__name__)


def _sync_foreground_input_runtime(config: dict) -> None:
    """应用执行模式/前台驱动配置，并让输入模拟器立即按新配置创建。

    前台一、前台二、后台和插件模式共用一个进程级驱动管理器；切换时必须
    先按当前执行模式选择配置，后台模式则主动释放前台驱动，避免旧状态串入
    新任务。
    """
    from utils.input.foreground_input_manager import get_foreground_input_manager
    from utils.input_simulation import global_input_simulator_manager
    from utils.input_simulation.mode_utils import (
        parse_foreground_backends,
        parse_foreground_py_backend,
        is_foreground_mode,
        is_plugin_input_backend,
        resolve_execution_mode,
    )

    foreground_input = get_foreground_input_manager()
    raw_execution_mode = str(config.get("execution_mode") or "background_sendmessage").strip().lower()
    execution_mode = resolve_execution_mode(config) or raw_execution_mode

    # 默认值也同步刷新，避免调用方省略 execution_mode/operation_mode 时继续
    # 使用设置前的缓存实例。
    global_input_simulator_manager.set_default_operation_mode(
        str(config.get("operation_mode") or "auto").strip().lower()
    )
    global_input_simulator_manager.set_default_execution_mode(execution_mode)

    if not is_foreground_mode(execution_mode) or is_plugin_input_backend(config):
        reset_runtime = getattr(foreground_input, "reset_runtime", None)
        if callable(reset_runtime):
            reset_runtime()
        else:  # 兼容旧版管理器/测试替身
            foreground_input.close()
        global_input_simulator_manager.clear_cache()
        return

    if execution_mode == "foreground_py":
        py_backend = parse_foreground_py_backend(config)
        mouse_backend, keyboard_backend = py_backend, py_backend
    else:
        mouse_backend, keyboard_backend = parse_foreground_backends(config)
    ib_driver = str(config.get('ibinputsimulator_driver', 'Logitech') or 'Logitech').strip()
    ib_driver_arg = str(config.get('ibinputsimulator_driver_arg', '') or '').strip()
    ib_ahk_path = str(config.get('ibinputsimulator_ahk_path', '') or '').strip()
    ib_ahk_dir = str(config.get('ibinputsimulator_ahk_dir', '') or '').strip()
    if 'ibinputsimulator' in (mouse_backend, keyboard_backend):
        foreground_input.set_ibinputsimulator_driver(
            ib_driver,
            ib_driver_arg,
            ib_ahk_path,
            ib_ahk_dir,
        )
    foreground_input.set_forced_modes(mouse_backend, keyboard_backend)
    global_input_simulator_manager.clear_cache()


_RUNTIME_RECYCLE_KEYS = (
    "execution_mode",
    "native_execution_mode",
    "operation_mode",
    "input_backend",
    "foreground_mouse_driver_backend",
    "foreground_keyboard_driver_backend",
    "foreground_py_backend",
    "ibinputsimulator_driver",
    "ibinputsimulator_driver_arg",
    "ibinputsimulator_ahk_path",
    "ibinputsimulator_ahk_dir",
)


def _runtime_settings_view(config: dict) -> tuple:
    """预热工作流子进程在启动时固化的那部分配置。"""
    return tuple(str(config.get(key) if config.get(key) is not None else "") for key in _RUNTIME_RECYCLE_KEYS)


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
        logger.info(f"GlobalSettingsDialog 返回的 bound_windows: {len(settings.get('bound_windows', []))} 个")
        logger.info(f"  窗口列表: {[w.get('title') for w in settings.get('bound_windows', [])]}")
        # 更新本地设置
        self.current_target_window_title = settings.get('active_target_window_title') or settings.get('target_window_title')
        self.current_execution_mode = str(settings.get('execution_mode') or 'background_sendmessage')
        self.operation_mode = settings.get(
            'operation_mode', self.config.get('operation_mode', 'auto')
        )
        self.custom_width = settings.get('custom_width', 0)
        self.custom_height = settings.get('custom_height', 0)
        self.native_window_binding_mode = settings.get('window_binding_mode', 'single')
        self.window_binding_mode = self.native_window_binding_mode
        self.native_bound_windows = settings.get('bound_windows', [])
        self.bound_windows = self.native_bound_windows
        self.multi_window_delay = settings.get('multi_window_delay', 500)
        logger.info(f"更新后 MainWindow.bound_windows: {len(self.bound_windows)} 个")
        # 快捷键设置
        self.start_task_hotkey = settings.get('start_task_hotkey', DEFAULT_HOTKEYS['start_task_hotkey'])
        self.stop_task_hotkey = settings.get('stop_task_hotkey', DEFAULT_HOTKEYS['stop_task_hotkey'])
        self.pause_workflow_hotkey = settings.get('pause_workflow_hotkey', DEFAULT_HOTKEYS['pause_workflow_hotkey'])
        self.record_hotkey = settings.get('record_hotkey', DEFAULT_HOTKEYS['record_hotkey'])
        self.replay_hotkey = settings.get('replay_hotkey', DEFAULT_HOTKEYS['replay_hotkey'])
        self.close_listen_hotkey = settings.get('close_listen_hotkey', DEFAULT_HOTKEYS['close_listen_hotkey'])
        # 更新配置字典
        previous_plugin_settings = plugin_settings_view(self.config)
        previous_runtime_settings = _runtime_settings_view(self.config)
        self.config.update(settings)
        self.config['bound_windows'] = self.native_bound_windows
        self.config['window_binding_mode'] = self.native_window_binding_mode
        sync_runtime_window_binding_state(self.config)
        self._sync_runtime_window_binding_state()
        # 先落盘再同步运行时：运行时各处都通过 utils.runtime_config 读磁盘配置，
        # 若先同步再保存，它们会在这段时间里读到旧值。
        try:
            from app_core.config_store import save_config
            save_config(self.config)
            logger.info("配置已保存到文件")
        except Exception as e:
            logger.error(f"保存全局设置时出错: {e}", exc_info=True)
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "保存设置错误", f"保存全局设置时出错: {e}")
            except Exception as msg_error:
                logger.error(f"显示错误消息框失败: {msg_error}")
        # 同步前台驱动配置到运行时管理器
        try:
            _sync_foreground_input_runtime(self.config)
        except Exception as e:
            logger.warning(f"同步前台驱动设置失败: {e}")
        # 执行模式 / 键鼠后端 / 前台驱动 / Ib 驱动任一变化都要回收预热子进程，
        # 否则它们继续按启动时的旧配置初始化输入模拟器。
        if previous_runtime_settings != _runtime_settings_view(self.config):
            try:
                from task_workflow.workflow_worker_pool import recycle_warm_workflow_workers

                recycle_warm_workflow_workers()
            except Exception:
                logger.debug("按执行配置回收预热工作流子进程失败", exc_info=True)
        # Refresh task execution modes after settings change
        if hasattr(self, 'task_manager'):
            for task in self.task_manager.get_all_tasks():
                self._update_task_execution_mode(task)
        logger.info(f"更新配置字典后，self.config['bound_windows']: {len(self.config.get('bound_windows', []))} 个")
        # 应用截图引擎设置（异步切换，避免设置保存时阻塞主线程）
        screenshot_engine = settings.get('screenshot_engine', 'wgc')
        requested_engine = str(screenshot_engine or "").strip().lower()
        self._schedule_runtime_screenshot_engine_switch(requested_engine)
        self._reload_main_schedule_from_config()
        # 更新快捷键
        self._update_hotkeys()
        control_center = getattr(self, "control_center", None)
        if control_center is not None:
            try:
                from ui.control_center_parts.control_center_policy import (
                    CONTROL_CENTER_FOREGROUND_BLOCK_MESSAGE,
                    control_center_allows_execution_mode,
                )

                if not control_center_allows_execution_mode(self.current_execution_mode):
                    from PySide6.QtWidgets import QMessageBox

                    control_center.close()
                    QMessageBox.warning(self, "中控已关闭", CONTROL_CENTER_FOREGROUND_BLOCK_MESSAGE)
                else:
                    if hasattr(control_center, "_refresh_shortcuts"):
                        control_center._refresh_shortcuts()
                    self._disable_main_window_hotkeys()
            except RuntimeError:
                pass
        self._sync_control_center_action_enabled()
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
        # 用户在前台模式中选择 Interception 后，必须再次明确同意才能安装。
        try:
            from utils.input.interception_installation_prompt import request_interception_installation
            request_interception_installation(self, self.config)
        except Exception as install_prompt_error:
            logger.error(f"处理 Interception 安装确认时出错: {install_prompt_error}", exc_info=True)
        self._sync_plugin_runtime_after_settings(previous_plugin_settings)

    def _sync_plugin_runtime_after_settings(self, previous_plugin_settings: dict) -> None:
        """插件参数变了就解绑/重起宿主，并按新参数重新试绑整份绑定列表。"""
        try:
            diff = diff_plugin_settings(previous_plugin_settings, self.config)
            if not diff.changed:
                return
            sync_plugin_runtime_after_settings_change(diff)
            if not diff.needs_reprobe:
                return
            windows = [w for w in (self.config.get('bound_windows') or []) if isinstance(w, dict)]
            if not windows:
                return
            from ui.plugin_bind_probe import schedule_bound_windows_plugin_bind_probe

            def _persist_probe_stamps(results) -> None:
                failed = sum(1 for _info, result in results if not result.ok)
                logger.info("插件参数变更后重新试绑 %d 个窗口，失败 %d 个", len(results), failed)
                try:
                    from app_core.config_store import save_config
                    save_config(self.config)
                except Exception as save_error:
                    logger.warning("保存插件试绑结果失败: %s", save_error)

            # 设置页已经实时展示过试绑结果；保存后的复检只更新戳记和日志，避免连续弹窗。
            schedule_bound_windows_plugin_bind_probe(
                self,
                windows,
                self.config,
                on_done=_persist_probe_stamps,
                notify=False,
            )
        except Exception as sync_error:
            logger.warning("同步插件运行时设置失败: %s", sync_error, exc_info=True)

    def _is_task_running_for_settings(self) -> bool:
        manager = getattr(self, "task_state_manager", None)
        if manager is None:
            return False
        get_state = getattr(manager, "get_current_state", None)
        if callable(get_state):
            try:
                return str(get_state() or "") in ("starting", "running", "stopping")
            except Exception:
                return False
        return False

    def _sync_global_settings_action_enabled(self) -> None:
        action = getattr(self, "global_settings_action", None)
        if action is None:
            return
        running = self._is_task_running_for_settings()
        action.setEnabled(not running)
        action.setToolTip(
            "任务运行中不能修改全局设置" if running
            else "配置目标窗口、执行模式和自定义分辨率等全局选项"
        )

    def open_global_settings(self):
        """打开全局设置对话框"""
        from ..global_settings_parts.global_settings_dialog import GlobalSettingsDialog
        try:
            if self._is_task_running_for_settings():
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.information(
                    self,
                    "任务运行中",
                    "任务运行期间不能修改全局设置，请先停止任务。",
                )
                return
            if self._global_settings_dialog is not None:
                dialog = self._global_settings_dialog
                if dialog.isVisible():
                    self._present_global_settings_dialog(dialog)
                    return
                self._present_global_settings_dialog(dialog)
                return
            logger.info(f"打开全局设置前，MainWindow.config 中的 bound_windows: {len(self.config.get('bound_windows', []))} 个")
            dialog = GlobalSettingsDialog(
                self.config,
                self
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
