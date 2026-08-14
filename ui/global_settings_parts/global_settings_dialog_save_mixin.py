import logging

from utils.input_simulation.mode_utils import require_foreground_backend
from utils.window_binding_utils import (
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
            # 确保绑定窗口配置被保存
            logger.info(f"全局设置对话框确定：准备保存配置，当前绑定窗口数量: {len(self.bound_windows)}")
            logger.info(f"  当前 bound_windows 内容: {[w.get('title') for w in self.bound_windows]}")
            # 关键修复：确保 current_config 的引用被更新
            # 不仅更新字典中的值，还要确保列表引用被更新
            self.current_config['bound_windows'] = self.bound_windows[:]  # 创建副本以避免引用问题
            self.current_config['window_binding_mode'] = self.window_binding_mode
            # 保存自定义分辨率配置
            self.current_config['custom_width'] = self.width_spinbox.value()
            self.current_config['custom_height'] = self.height_spinbox.value()
            # 保存截图格式配置
            if hasattr(self, 'screenshot_format_combo'):
                screenshot_format = self.screenshot_format_combo.currentData()
                if screenshot_format:
                    self.current_config['screenshot_format'] = screenshot_format
            selected_mouse_backend = None
            if hasattr(self, 'foreground_driver_combo'):
                selected_mouse_backend = self.foreground_driver_combo.currentData()
            selected_keyboard_backend = None
            if hasattr(self, 'foreground_keyboard_driver_combo'):
                selected_keyboard_backend = self.foreground_keyboard_driver_combo.currentData()
            normalized_mouse_backend = require_foreground_backend(selected_mouse_backend)
            normalized_keyboard_backend = require_foreground_backend(selected_keyboard_backend)
            self.current_config['foreground_mouse_driver_backend'] = normalized_mouse_backend
            self.current_config['foreground_keyboard_driver_backend'] = normalized_keyboard_backend
            self.current_config.pop('foreground_driver_backend', None)
            selected_ib_driver = 'Logitech'
            if hasattr(self, 'ib_driver_combo'):
                selected_ib_driver = self.ib_driver_combo.currentData()
                if not selected_ib_driver:
                    selected_ib_driver = self.IB_DRIVER_MAP.get(self.ib_driver_combo.currentText(), 'Logitech')
            self.current_config['ibinputsimulator_driver'] = str(selected_ib_driver or 'Logitech').strip()
            self.current_config.setdefault('ibinputsimulator_ahk_path', '')
            self.current_config.setdefault('ibinputsimulator_ahk_dir', '')
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
            # 注意：定时设置已移至主窗口，不在全局设置中保存
            logger.info(f"  已更新 current_config['bound_windows']: {len(self.current_config['bound_windows'])} 个窗口")
            logger.info(f"  已更新 current_config['custom_width']: {self.current_config['custom_width']}")
            logger.info(f"  已更新 current_config['custom_height']: {self.current_config['custom_height']}")
            # 保存配置（这会更新文件）
            self._save_bound_windows_config()
            # 调用默认的accept方法
            self.accept()
        except Exception as e:
            logger.error(f"处理确定按钮失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # 即使出错也要关闭对话框
            self.accept()
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
        internal_mode = self.mode_combo.currentData()
        if not internal_mode:
            selected_display_mode = self.mode_combo.currentText()
            internal_mode = self.MODE_INTERNAL_MAP.get(selected_display_mode, 'foreground_driver')
        # 根据绑定窗口数量决定窗口绑定模式
        bound_windows = self.get_bound_windows()
        window_count = len(bound_windows)
        window_binding_mode = 'multiple' if window_count > 1 else 'single'
        active_bound_windows = bound_windows
        active_window_binding_mode = window_binding_mode
        # 获取截图引擎设置
        screenshot_engine_display = self.screenshot_engine_combo.currentText()
        screenshot_engine = self.screenshot_engine_map.get(screenshot_engine_display)
        if not screenshot_engine:
            raise ValueError(f"未知的截图引擎选项: {screenshot_engine_display!r}")
        settings = {
            'execution_mode': internal_mode,
            'operation_mode': 'auto',  # 默认使用自动检测
            'custom_width': self.width_spinbox.value(),
            'custom_height': self.height_spinbox.value(),
            'screenshot_format': self.screenshot_format_combo.currentData() if hasattr(self, 'screenshot_format_combo') else self.current_config.get('screenshot_format', 'bmp'),
            'screenshot_engine': screenshot_engine,  # 添加截图引擎设置
            'foreground_mouse_driver_backend': require_foreground_backend(
                self.foreground_driver_combo.currentData() if hasattr(self, 'foreground_driver_combo') else self.current_config.get('foreground_mouse_driver_backend')
            ),
            'foreground_keyboard_driver_backend': require_foreground_backend(
                self.foreground_keyboard_driver_combo.currentData() if hasattr(self, 'foreground_keyboard_driver_combo') else self.current_config.get('foreground_keyboard_driver_backend')
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
            # 快捷键设置 - 从QComboBox获取实际值(itemData)
            'start_task_hotkey': self._get_combo_data(self.start_task_hotkey) or 'XButton1',
            'stop_task_hotkey': self._get_combo_data(self.stop_task_hotkey) or 'XButton2',
            'pause_workflow_hotkey': self._get_combo_data(self.pause_workflow_hotkey) or 'F11',
            'record_hotkey': self._get_combo_data(self.record_hotkey) or 'F12',
            'replay_hotkey': self._get_combo_data(self.replay_hotkey) or 'F10',
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
