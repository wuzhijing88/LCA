import logging

from PySide6.QtWidgets import QMessageBox

from app_core.config_sections import DEFAULT_HOTKEYS
from app_core.hotkey_spec import normalize_hotkey
from utils.input_simulation.mode_utils import (
    PLUGIN_EXECUTION_MODE,
    require_foreground_backend,
    require_foreground_py_backend,
)
from utils.plugin.bind_modes import (
    normalize_plugin_bind_kind,
    normalize_plugin_bind_mode,
    normalize_plugin_keypad,
    normalize_plugin_mouse,
)
from utils.window.window_binding_utils import (
    get_active_target_window_title,
    sync_runtime_window_binding_state,
)

logger = logging.getLogger(__name__)


class GlobalSettingsDialogSaveMixin:

    def _on_accept(self):
        """处理确定按钮点击事件，确保配置被正确保存"""
        try:
            if hasattr(self, "_is_wgc_desktop_combination") and self._is_wgc_desktop_combination():
                self._warn_wgc_desktop_engine()
                return
            width = self.width_spinbox.value() if hasattr(self, "width_spinbox") else 0
            height = self.height_spinbox.value() if hasattr(self, "height_spinbox") else 0
            if (width > 0) != (height > 0):
                QMessageBox.warning(
                    self,
                    "分辨率未生效",
                    "绑定窗口分辨率的宽高需要同时大于 0 才会启用；若要禁用请把宽和高都设为 0。",
                )
                return
            if hasattr(self, "_finish_live_plugin_probe_for_accept"):
                self._finish_live_plugin_probe_for_accept()
            settings = self.get_settings()
            self._warn_plugin_display_mismatch_if_needed(settings)
            self.current_config.update(settings)
            logger.info(
                "全局设置对话框确定：准备保存配置，当前绑定窗口数量: %s",
                len(self.bound_windows),
            )
            self._save_bound_windows_config()
            self.accept()
        except Exception as e:
            logger.error(f"处理确定按钮失败: {e}", exc_info=True)
            QMessageBox.warning(self, "保存失败", f"全局设置没有保存：{e}")

    def _warn_plugin_display_mismatch_if_needed(self, settings: dict) -> None:
        from utils.capture.engine_ids import (
            is_plugin_screenshot_engine,
            to_dm_display_mode,
        )

        if str(settings.get("input_backend") or "").strip().lower() != "plugin":
            return
        engine = settings.get("screenshot_engine")
        if not is_plugin_screenshot_engine(engine):
            return
        input_display = settings.get("plugin_input_display")
        if to_dm_display_mode(engine) == to_dm_display_mode(input_display):
            return
        QMessageBox.warning(
            self,
            "插件绑定提示",
            "插件键鼠的绑定图显与当前插件截图引擎不同。"
            "大漠通常不能对同一窗口分离绑定；保存后仍会尝试用户选择，失败时运行时可能回退为同一 display。",
        )
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
        return self.MODE_INTERNAL_MAP.get(selected_display_mode, 'background_sendmessage')
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
    def get_multi_window_delay(self):
        """获取多窗口启动延迟"""
        value = self.current_config.get('multi_window_delay', 500)
        if isinstance(value, bool):
            return 500
        try:
            delay_ms = int(value)
        except (TypeError, ValueError):
            return 500
        return delay_ms if delay_ms >= 0 else 500
    def _get_combo_data(self, combo):
        """从下拉框或按键录取按钮读取值。"""
        if combo is None:
            return None
        if hasattr(combo, "key_value"):
            value = combo.key_value()
            return value or None
        current_index = combo.currentIndex()
        if current_index >= 0:
            data = combo.itemData(current_index)
            if data is not None:
                return data
        return combo.currentText() if hasattr(combo, 'currentText') else None
    def get_settings(self) -> dict:
        """Returns the edited settings as a dictionary."""
        internal_mode = self.mode_combo.currentData()
        if not internal_mode:
            selected_display_mode = self.mode_combo.currentText()
            internal_mode = self.MODE_INTERNAL_MAP.get(selected_display_mode, 'background_sendmessage')
        # 根据绑定窗口数量决定窗口绑定模式
        bound_windows = self.get_bound_windows()
        window_count = len(bound_windows)
        window_binding_mode = 'multiple' if window_count > 1 else 'single'
        active_bound_windows = bound_windows
        active_window_binding_mode = window_binding_mode
        input_backend = (
            self._selected_input_backend()
            if hasattr(self, "_selected_input_backend")
            else "native"
        )
        # 插件后端只能按后台消息执行，但不要覆盖原生模式的持久化值。
        # 这样在“原生 -> 插件 -> 原生”之间切换时，原生面板仍恢复用户上次选择。
        effective_execution_mode = (
            PLUGIN_EXECUTION_MODE if input_backend == "plugin" else internal_mode
        )
        if input_backend == "plugin" and hasattr(self, "plugin_screenshot_engine_combo"):
            screenshot_engine = self.plugin_screenshot_engine_combo.currentData()
            if not screenshot_engine:
                raise ValueError(
                    f"未知的插件截图引擎选项: {self.plugin_screenshot_engine_combo.currentText()!r}"
                )
        else:
            screenshot_engine = self.screenshot_engine_combo.currentData()
            if not screenshot_engine:
                screenshot_engine_display = self.screenshot_engine_combo.currentText()
                screenshot_engine = self.screenshot_engine_map.get(screenshot_engine_display)
            if not screenshot_engine:
                raise ValueError(
                    f"未知的截图引擎选项: {self.screenshot_engine_combo.currentText()!r}"
                )
        plugin_mouse = normalize_plugin_mouse(
            (self.plugin_mouse_combo.currentData() if hasattr(self, "plugin_mouse_combo") else None)
            or self.current_config.get("plugin_mouse", "normal")
        )
        plugin_keypad = normalize_plugin_keypad(
            (self.plugin_keypad_combo.currentData() if hasattr(self, "plugin_keypad_combo") else None)
            or self.current_config.get("plugin_keypad", "normal")
        )
        follow_display = True
        if hasattr(self, "plugin_input_display_follow_check"):
            follow_display = bool(self.plugin_input_display_follow_check.isChecked())
        if follow_display and hasattr(self, "_followed_plugin_input_display"):
            plugin_input_display = str(self._followed_plugin_input_display() or "normal").strip().lower()
        else:
            plugin_input_display = str(
                (self.plugin_input_display_combo.currentData() if hasattr(self, "plugin_input_display_combo") else None)
                or self.current_config.get("plugin_input_display", "normal")
                or "normal"
            ).strip().lower()
        if hasattr(self, "plugin_bind_mode_combo"):
            bind_raw = self.plugin_bind_mode_combo.currentData()
            if bind_raw is None:
                bind_raw = self.plugin_bind_mode_combo.currentText()
        else:
            bind_raw = self.current_config.get("plugin_bind_mode", 0)
        plugin_bind_mode = normalize_plugin_bind_mode(bind_raw)
        if hasattr(self, "plugin_bind_kind_combo"):
            kind_raw = self.plugin_bind_kind_combo.currentData()
        else:
            kind_raw = self.current_config.get("plugin_bind_kind", "basic")
        try:
            plugin_bind_kind = normalize_plugin_bind_kind(kind_raw)
        except ValueError:
            plugin_bind_kind = "basic"
        settings = {
            'execution_mode': effective_execution_mode,
            'native_execution_mode': internal_mode,
            # operation_mode 属于输入模拟器的独立默认值；设置页没有该控件时
            # 必须保留已有配置，不能因保存任意其它参数而重置。
            'operation_mode': self.current_config.get('operation_mode', 'auto'),
            'custom_width': self.width_spinbox.value(),
            'custom_height': self.height_spinbox.value(),
            'screenshot_format': self.screenshot_format_combo.currentData() if hasattr(self, 'screenshot_format_combo') else self.current_config.get('screenshot_format', 'bmp'),
            'screenshot_engine': screenshot_engine,  # 添加截图引擎设置
            "input_backend": input_backend,
            "plugin_mouse": plugin_mouse,
            "plugin_keypad": plugin_keypad,
            "plugin_input_display": plugin_input_display,
            "plugin_input_display_follow": follow_display,
            "plugin_bind_kind": plugin_bind_kind,
            "plugin_bind_mode": plugin_bind_mode,
            "plugin_text_ime": (
                bool(self.plugin_text_ime_check.isChecked())
                if hasattr(self, "plugin_text_ime_check")
                else bool(self.current_config.get("plugin_text_ime", False))
            ),
            "plugin_fake_active": (
                bool(self.plugin_fake_active_check.isChecked())
                if hasattr(self, "plugin_fake_active_check")
                else bool(self.current_config.get("plugin_fake_active", False))
            ),
            "plugin_reg_code": self.plugin_reg_code_edit.text() if hasattr(self, "plugin_reg_code_edit") else self.current_config.get("plugin_reg_code", ""),
            "plugin_extra_code": (
                self.plugin_extra_code_edit.text().strip()
                if hasattr(self, "plugin_extra_code_edit")
                else self.current_config.get("plugin_extra_code", "")
            ),
            'foreground_mouse_driver_backend': require_foreground_backend(
                (self.foreground_driver_combo.currentData() if hasattr(self, 'foreground_driver_combo') else None)
                or self.current_config.get('foreground_mouse_driver_backend', 'interception')
            ),
            'foreground_keyboard_driver_backend': require_foreground_backend(
                (self.foreground_keyboard_driver_combo.currentData() if hasattr(self, 'foreground_keyboard_driver_combo') else None)
                or self.current_config.get('foreground_keyboard_driver_backend', 'interception')
            ),
            'foreground_py_backend': require_foreground_py_backend(
                (self.foreground_py_backend_combo.currentData() if hasattr(self, 'foreground_py_backend_combo') else None)
                or self.current_config.get('foreground_py_backend', 'pyautogui')
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
            'window_binding_mode': window_binding_mode,
            'bound_windows': bound_windows,
            'active_bound_windows': active_bound_windows,
            'active_window_binding_mode': active_window_binding_mode,
            'multi_window_delay': self.get_multi_window_delay(),
            # 快捷键设置
            'start_task_hotkey': normalize_hotkey(self._get_combo_data(self.start_task_hotkey)) or DEFAULT_HOTKEYS['start_task_hotkey'],
            'stop_task_hotkey': normalize_hotkey(self._get_combo_data(self.stop_task_hotkey)) or DEFAULT_HOTKEYS['stop_task_hotkey'],
            'pause_workflow_hotkey': normalize_hotkey(self._get_combo_data(self.pause_workflow_hotkey)) or DEFAULT_HOTKEYS['pause_workflow_hotkey'],
            'record_hotkey': normalize_hotkey(self._get_combo_data(self.record_hotkey)) or DEFAULT_HOTKEYS['record_hotkey'],
            'replay_hotkey': normalize_hotkey(self._get_combo_data(self.replay_hotkey)) or DEFAULT_HOTKEYS['replay_hotkey'],
            'close_listen_hotkey': normalize_hotkey(self._get_combo_data(self.close_listen_hotkey)) or DEFAULT_HOTKEYS['close_listen_hotkey'],
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
            'bound_windows': settings.get('bound_windows', []),
            'window_binding_mode': settings.get('window_binding_mode', 'single'),
            'active_bound_windows': active_bound_windows,
            'active_window_binding_mode': active_window_binding_mode,
            'target_window_title': settings.get('target_window_title'),
        })
        sync_runtime_window_binding_state(settings)
        return settings
