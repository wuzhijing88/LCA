import logging
import os
import sys

from PySide6.QtWidgets import QMessageBox
from app_core.client_identity import get_hardware_id
from app_core.plugin_activation_service import prepare_plugin_mode_activation

from utils.window_binding_utils import (
    get_active_target_window_title,
    normalize_plugin_bound_windows,
    normalize_plugin_ola_binding,
    sync_runtime_window_binding_state,
)

logger = logging.getLogger(__name__)


class GlobalSettingsDialogSaveMixin:

    def _on_accept(self):

        """处理确定按钮点击事件，确保配置被正确保存"""

        try:

            # 确保绑定窗口配置被保存

            logger.info(f"全局设置对话框确定：准备保存配置，当前绑定窗口数量: {len(self.bound_windows)}")

            logger.info(f"  当前 bound_windows 内容: {[w.get('title') for w in self.bound_windows]}")

            # 关键修复：确保 current_config 的引用被更新

            # 不仅更新字典中的值，还要确保列表引用被更新

            self.current_config['bound_windows'] = self.bound_windows[:]  # 创建副本以避免引用问题

            self.current_config['window_binding_mode'] = self.window_binding_mode

            # 关键修复：保存自定义分辨率配置

            if hasattr(self, '_sync_plugin_bound_window_binding_from_controls'):

                self._sync_plugin_bound_window_binding_from_controls()

            self.plugin_default_ola_binding = normalize_plugin_ola_binding(
                getattr(self, 'plugin_default_ola_binding', {}),
                fallback=self.current_config.get('plugin_settings', {}).get('ola_binding', {}),
            )

            self.plugin_bound_windows = normalize_plugin_bound_windows(
                self.plugin_bound_windows,
                default_binding=self.plugin_default_ola_binding,
            )

            self.plugin_window_binding_mode = 'multiple' if len(self.plugin_bound_windows) > 1 else 'single'

            self.current_config['plugin_bound_windows'] = self.plugin_bound_windows[:]

            self.current_config['plugin_window_binding_mode'] = self.plugin_window_binding_mode

            self.current_config['custom_width'] = self.width_spinbox.value()

            self.current_config['custom_height'] = self.height_spinbox.value()

            # 保存截图格式配置

            if hasattr(self, 'screenshot_format_combo'):

                screenshot_format = self.screenshot_format_combo.currentData()

                if screenshot_format:

                    self.current_config['screenshot_format'] = screenshot_format

            selected_mouse_backend = 'interception'

            if hasattr(self, 'foreground_driver_combo'):

                selected_mouse_backend = self.foreground_driver_combo.currentData()

                if not selected_mouse_backend:

                    selected_mouse_backend = self.FOREGROUND_DRIVER_BACKEND_MAP.get(

                        self.foreground_driver_combo.currentText(),

                        'interception',

                    )

            selected_keyboard_backend = 'interception'

            if hasattr(self, 'foreground_keyboard_driver_combo'):

                selected_keyboard_backend = self.foreground_keyboard_driver_combo.currentData()

                if not selected_keyboard_backend:

                    selected_keyboard_backend = self.FOREGROUND_DRIVER_BACKEND_MAP.get(

                        self.foreground_keyboard_driver_combo.currentText(),

                        'interception',

                    )

            normalized_mouse_backend = str(selected_mouse_backend or 'interception').strip().lower()

            normalized_keyboard_backend = str(selected_keyboard_backend or 'interception').strip().lower()

            self.current_config['foreground_mouse_driver_backend'] = normalized_mouse_backend

            self.current_config['foreground_keyboard_driver_backend'] = normalized_keyboard_backend

            # 兼容旧版本配置键

            self.current_config['foreground_driver_backend'] = normalized_mouse_backend

            selected_ib_driver = 'Logitech'

            if hasattr(self, 'ib_driver_combo'):

                selected_ib_driver = self.ib_driver_combo.currentData()

                if not selected_ib_driver:

                    selected_ib_driver = self.IB_DRIVER_MAP.get(self.ib_driver_combo.currentText(), 'Logitech')

            self.current_config['ibinputsimulator_driver'] = str(selected_ib_driver or 'Logitech').strip()

            self.current_config.setdefault('ibinputsimulator_ahk_path', '')

            self.current_config.setdefault('ibinputsimulator_ahk_dir', '')

            # 保存更新检查配置

            if hasattr(self, 'enable_update_check'):

                self.current_config['enable_update_check'] = self.enable_update_check.isChecked()

            # 保存窗口行为配置

            if hasattr(self, 'card_snap_checkbox'):

                self.current_config['enable_card_snap'] = self.card_snap_checkbox.isChecked()

            if hasattr(self, 'parameter_panel_snap_checkbox'):

                self.current_config['enable_parameter_panel_snap'] = self.parameter_panel_snap_checkbox.isChecked()

            if hasattr(self, 'canvas_grid_checkbox'):

                self.current_config['enable_canvas_grid'] = self.canvas_grid_checkbox.isChecked()

            if hasattr(self, 'floating_status_window_checkbox'):

                self.current_config['enable_floating_status_window'] = self.floating_status_window_checkbox.isChecked()

            if hasattr(self, 'connection_line_animation_checkbox'):

                self.current_config['enable_connection_line_animation'] = self.connection_line_animation_checkbox.isChecked()

            if hasattr(self, '_build_ntfy_settings_from_form'):

                self.current_config['ntfy_settings'] = self._build_ntfy_settings_from_form()

            # 注意：定时设置已移至主窗口，不在全局设置中保存

            # 保存插件设置配置

            if hasattr(self, 'plugin_enabled_check'):

                plugin_enabled = self.plugin_enabled_check.isChecked()

                ola_auth = (
                    self._collect_current_plugin_ola_auth()
                    if hasattr(self, '_collect_current_plugin_ola_auth')
                    else {'user_code': '', 'soft_code': '', 'feature_list': ''}
                )

                # 二次确认：如果启用插件模式，再次检查授权

                if plugin_enabled and not self._ensure_plugin_activation_ready_before_save():
                    return

                if plugin_enabled and False:

                    # 首先检查服务器验证状态

                    import os

                    import sys

                    try:



                        # 获取硬件ID

                        hardware_id = get_hardware_id()

                        if hardware_id:

                            # 查询服务器验证状态

                            http_session = None

                            try:

                                registration_result = attempt_client_registration(hardware_id, http_session)

                            finally:

                                try:

                                    http_session.close()

                                except Exception:

                                    pass

                            if registration_result.get("success", False):

                                server_license_validation_enabled = registration_result.get("license_validation_enabled", True)

                                logger.info(f"二次确认：服务器许可证验证状态: {'开启' if server_license_validation_enabled else '关闭'}")

                                # 如果服务器验证已关闭，跳过授权文件检查

                                if not server_license_validation_enabled:

                                    logger.info("二次确认：服务器验证已关闭，插件模式无需授权验证")

                                    # 继续保存配置，不需要检查授权文件

                                else:

                                    # 服务器验证开启，需要检查授权文件

                                    license_file = LICENSE_FILE

                                    if not os.path.exists(license_file):

                                        logger.warning("二次确认：插件模式启用但未找到授权文件")

                                        QMessageBox.critical(

                                            self,

                                            "插件模式需要授权",

                                            "启用插件模式需要有效的授权码。\n请先完成授权验证。"

                                        )

                                        return  # 不关闭对话框，让用户重新选择

                    except Exception as e:

                        logger.warning(f"二次确认：检查服务器验证状态时出错: {e}")

                        # 如果无法连接服务器，为了保险起见，检查授权文件

                        license_file = LICENSE_FILE

                        if not os.path.exists(license_file):

                            logger.warning("二次确认：无法验证服务器状态且未找到授权文件")

                            QMessageBox.critical(

                                self,

                                "插件模式需要授权",

                                "无法连接到服务器验证状态。\n如果服务器要求验证，请先完成授权。"

                            )

                            return  # 不关闭对话框，让用户重新选择

                default_ola_binding = normalize_plugin_ola_binding(
                    getattr(self, 'plugin_default_ola_binding', {}),
                    fallback=self.current_config.get('plugin_settings', {}).get('ola_binding', {}),
                )

                plugin_settings = {

                    'enabled': plugin_enabled,

                    'preferred_plugin': 'ola',  # 启用插件时默认使用OLA

                    'ola_binding': default_ola_binding,

                    'ola_auth': dict(ola_auth),

                }

                self.current_config['plugin_settings'] = plugin_settings

                logger.info(f"  已更新插件设置: 启用={plugin_settings['enabled']}")

                logger.info(f"  OLA绑定参数: display={plugin_settings['ola_binding']['display_mode']}, mouse={plugin_settings['ola_binding']['mouse_mode']}, keypad={plugin_settings['ola_binding']['keypad_mode']}, mode={plugin_settings['ola_binding']['mode']}, trajectory={plugin_settings['ola_binding']['mouse_move_with_trajectory']}, input_lock={plugin_settings['ola_binding']['input_lock']}, sim_mode_type={plugin_settings['ola_binding']['sim_mode_type']}, pubstr={plugin_settings['ola_binding']['pubstr'] if plugin_settings['ola_binding']['pubstr'] else '(无)'}")

                # 应用插件模式切换

                try:

                    from app_core.plugin_bridge import get_plugin_mode_last_error, set_plugin_mode

                    if plugin_settings['enabled']:

                        # 【修复】检查set_plugin_mode的返回值

                        success = set_plugin_mode(
                            plugin_settings['preferred_plugin'],
                            runtime_config_override=ola_auth,
                        )

                        if success:

                            logger.info(f"  已切换到插件模式: {plugin_settings['preferred_plugin']}")

                        else:

                            logger.error(f"  切换到插件模式失败（授权验证未通过），自动禁用插件模式")

                            failure_message = get_plugin_mode_last_error() or (
                                "插件模式授权验证失败。\n\n"
                                "可能的原因：\n"
                                "- 授权码已过期\n"
                                "- 授权码无效\n"
                                "- 授权文件被篡改\n\n"
                                "插件模式已被禁用。"
                            )

                            # 授权失败，强制禁用插件模式

                            plugin_settings['enabled'] = False

                            self.current_config['plugin_settings'] = plugin_settings

                            # 显示错误消息

                            QMessageBox.critical(

                                self,

                                "插件模式启用失败",

                                failure_message

                            )

                    else:

                        set_plugin_mode('disabled')

                        logger.info("  已禁用插件系统")

                except Exception as plugin_error:

                    logger.error(f"  应用插件设置失败: {plugin_error}")

            logger.info(f"  已更新 current_config['bound_windows']: {len(self.current_config['bound_windows'])} 个窗口")

            logger.info(f"  已更新 current_config['custom_width']: {self.current_config['custom_width']}")

            logger.info(f"  已更新 current_config['custom_height']: {self.current_config['custom_height']}")

            # 保存配置（这会更新文件）

            self._save_bound_windows_config()

            # 关键修复：清除所有缓存，确保下次运行使用新配置

            try:

                from utils.input_simulation import global_input_simulator_manager

                global_input_simulator_manager.clear_cache()

                logger.info("已清除输入缓存")

            except Exception as e:

                logger.warning(f"清除输入缓存失败: {e}")

            try:

                from utils.input_simulation.plugin_simulator import clear_global_bound_windows

                clear_global_bound_windows()

            except Exception as e:

                logger.warning(f"清除插件绑定窗口缓存失败: {e}")

            # 【关键修复】清除OLA多实例管理器的所有实例缓存

            try:

                from plugins.adapters.ola.multi_instance_manager import OLAMultiInstanceManager

                manager = OLAMultiInstanceManager()

                manager.release_all()

                logger.info("已清除OLA多实例管理器缓存")

            except Exception as e:

                logger.warning(f"清除OLA多实例管理器缓存失败: {e}")

            # 调用默认的accept方法

            self.accept()

        except Exception as e:

            logger.error(f"处理确定按钮失败: {e}")

            import traceback

            logger.error(traceback.format_exc())

            # 即使出错也要关闭对话框

            self.accept()

    def _ensure_plugin_activation_ready_before_save(self) -> bool:

        hardware_id = str(get_hardware_id() or "").strip()

        activation_result = prepare_plugin_mode_activation(hardware_id)

        if activation_result.success:

            return True

        QMessageBox.critical(

            self,

            activation_result.title or "插件模式需要授权",

            activation_result.message or "启用插件模式需要有效的授权码。",

        )

        return False

    def _ensure_plugin_activation_ready_before_save(self) -> bool:

        hardware_id = str(get_hardware_id() or "").strip()

        activation_result = prepare_plugin_mode_activation(hardware_id)

        if activation_result.success:

            return True

        QMessageBox.critical(

            self,

            activation_result.title or "\u63d2\u4ef6\u6a21\u5f0f\u9700\u8981\u6388\u6743",

            activation_result.message or "\u542f\u7528\u63d2\u4ef6\u6a21\u5f0f\u9700\u8981\u6709\u6548\u7684\u6388\u6743\u7801\u3002",

        )

        return False

    def get_target_window_title(self):

        """获取目标窗口标题"""

        if self.window_binding_mode == 'single':

            return self.title_edit.text() or None

        else:

            # 多窗口模式返回None，使用get_bound_windows获取窗口列表

            return None

    def get_execution_mode(self):

        """获取执行模式"""

        internal_mode = self.mode_combo.currentData()

        if internal_mode:

            return internal_mode

        selected_display_mode = self.mode_combo.currentText()

        return self.MODE_INTERNAL_MAP.get(selected_display_mode, 'foreground_driver')

    def get_custom_width(self):

        """获取自定义宽度"""

        return self.width_spinbox.value()

    def get_custom_height(self):

        """获取自定义高度"""

        return self.height_spinbox.value()

    def get_window_binding_mode(self):

        """获取窗口绑定模式"""

        return self.window_binding_mode

    def get_bound_windows(self):

        """获取绑定的窗口列表"""

        return self.bound_windows.copy()

    def get_plugin_bound_windows(self):

        default_binding = normalize_plugin_ola_binding(
            getattr(self, 'plugin_default_ola_binding', {}),
            fallback=self.current_config.get('plugin_settings', {}).get('ola_binding', {}),
        )

        return normalize_plugin_bound_windows(self.plugin_bound_windows, default_binding=default_binding)

    def get_multi_window_delay(self):

        """获取多窗口启动延迟"""

        return self.multi_window_delay

    def _get_combo_data(self, combo):

        """从QComboBox获取数据，兼容currentData方法"""

        if combo is None:

            return None

        current_index = combo.currentIndex()

        if current_index >= 0:

            data = combo.itemData(current_index)

            if data is not None:

                return data

        return combo.currentText() if hasattr(combo, 'currentText') else None

    def get_settings(self) -> dict:

        """Returns the edited settings as a dictionary."""

        # ===== 插件启用时强制使用插件模式，否则使用原生前后台 =====

        plugin_enabled = self.plugin_enabled_check.isChecked()

        if plugin_enabled:

            internal_mode = 'plugin_mode'

        else:

            internal_mode = self.mode_combo.currentData()

            if not internal_mode:

                selected_display_mode = self.mode_combo.currentText()

                internal_mode = self.MODE_INTERNAL_MAP.get(selected_display_mode, 'foreground_driver')

        # 根据绑定窗口数量决定窗口绑定模式

        native_bound_windows = self.get_bound_windows()

        plugin_bound_windows = self.get_plugin_bound_windows()

        native_window_count = len(native_bound_windows)

        plugin_window_count = len(plugin_bound_windows)

        window_binding_mode = 'multiple' if native_window_count > 1 else 'single'

        plugin_window_binding_mode = 'multiple' if plugin_window_count > 1 else 'single'

        active_bound_windows = plugin_bound_windows if plugin_enabled else native_bound_windows

        active_window_binding_mode = plugin_window_binding_mode if plugin_enabled else window_binding_mode

        # 获取截图引擎设置

        screenshot_engine_display = self.screenshot_engine_combo.currentText()

        screenshot_engine = self.screenshot_engine_map.get(screenshot_engine_display, 'wgc')

        settings = {

            'execution_mode': internal_mode,

            'operation_mode': 'auto',  # 默认使用自动检测

            'custom_width': self.width_spinbox.value(),

            'custom_height': self.height_spinbox.value(),

            'screenshot_format': self.screenshot_format_combo.currentData() if hasattr(self, 'screenshot_format_combo') else self.current_config.get('screenshot_format', 'bmp'),

            'screenshot_engine': screenshot_engine,  # 添加截图引擎设置

            'foreground_driver_backend': (

                self.foreground_driver_combo.currentData() if hasattr(self, 'foreground_driver_combo') else self.current_config.get('foreground_driver_backend', 'interception')

            ),

            'foreground_mouse_driver_backend': (

                self.foreground_driver_combo.currentData() if hasattr(self, 'foreground_driver_combo') else self.current_config.get('foreground_mouse_driver_backend', self.current_config.get('foreground_driver_backend', 'interception'))

            ),

            'foreground_keyboard_driver_backend': (

                self.foreground_keyboard_driver_combo.currentData() if hasattr(self, 'foreground_keyboard_driver_combo') else self.current_config.get('foreground_keyboard_driver_backend', self.current_config.get('foreground_driver_backend', 'interception'))

            ),

            'ibinputsimulator_driver': (

                self.ib_driver_combo.currentData() if hasattr(self, 'ib_driver_combo') else self.current_config.get('ibinputsimulator_driver', 'Logitech')

            ),

            'ibinputsimulator_driver_arg': self.current_config.get('ibinputsimulator_driver_arg', ''),

            'ibinputsimulator_ahk_path': self.current_config.get('ibinputsimulator_ahk_path', ''),

            'ibinputsimulator_ahk_dir': self.current_config.get('ibinputsimulator_ahk_dir', ''),

            'enable_canvas_grid': self.canvas_grid_checkbox.isChecked() if hasattr(self, 'canvas_grid_checkbox') else self.current_config.get('enable_canvas_grid', True),

            'enable_card_snap': self.card_snap_checkbox.isChecked() if hasattr(self, 'card_snap_checkbox') else self.current_config.get('enable_card_snap', True),

            'enable_parameter_panel_snap': self.parameter_panel_snap_checkbox.isChecked() if hasattr(self, 'parameter_panel_snap_checkbox') else self.current_config.get('enable_parameter_panel_snap', True),

            'enable_floating_status_window': self.floating_status_window_checkbox.isChecked() if hasattr(self, 'floating_status_window_checkbox') else self.current_config.get('enable_floating_status_window', True),

            'enable_connection_line_animation': self.connection_line_animation_checkbox.isChecked() if hasattr(self, 'connection_line_animation_checkbox') else self.current_config.get('enable_connection_line_animation', True),

            'enable_update_check': self.enable_update_check.isChecked() if hasattr(self, 'enable_update_check') else self.current_config.get('enable_update_check', False),

            'ntfy_settings': self._build_ntfy_settings_from_form() if hasattr(self, '_build_ntfy_settings_from_form') else self.current_config.get('ntfy_settings', {}),

            'window_binding_mode': window_binding_mode,

            'plugin_window_binding_mode': plugin_window_binding_mode,

            'bound_windows': native_bound_windows,

            'plugin_bound_windows': plugin_bound_windows,

            'active_bound_windows': active_bound_windows,

            'active_window_binding_mode': active_window_binding_mode,

            'multi_window_delay': self.multi_window_delay,

            # 快捷键设置 - 从QComboBox获取实际值(itemData)

            'start_task_hotkey': self._get_combo_data(self.start_task_hotkey) or 'XButton1',

            'stop_task_hotkey': self._get_combo_data(self.stop_task_hotkey) or 'XButton2',

            'pause_workflow_hotkey': self._get_combo_data(self.pause_workflow_hotkey) or 'F11',

            'record_hotkey': self._get_combo_data(self.record_hotkey) or 'F12',

            'replay_hotkey': self._get_combo_data(self.replay_hotkey) or 'F10',

            # 插件设置 - 确保同步到MainWindow

            'plugin_settings': self.current_config.get('plugin_settings', {})

        }

        # 根据窗口数量设置target_window_title

        active_window_count = len(active_bound_windows)

        if active_window_count == 1:

            # 单窗口：使用第一个绑定窗口的标题

            settings['target_window_title'] = active_bound_windows[0]['title']

        else:

            # 多窗口或无窗口：不设置target_window_title

            settings['target_window_title'] = None

        settings['active_target_window_title'] = get_active_target_window_title({
            'plugin_settings': settings.get('plugin_settings', {}),
            'bound_windows': settings.get('bound_windows', []),
            'plugin_bound_windows': settings.get('plugin_bound_windows', []),
            'window_binding_mode': settings.get('window_binding_mode', 'single'),
            'plugin_window_binding_mode': settings.get('plugin_window_binding_mode', 'single'),
            'active_bound_windows': active_bound_windows,
            'active_window_binding_mode': active_window_binding_mode,
            'target_window_title': settings.get('target_window_title'),
        })

        sync_runtime_window_binding_state(settings)

        return settings
