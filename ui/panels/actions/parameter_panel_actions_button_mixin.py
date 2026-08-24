from ..parameter_panel_support import *
from utils.window_binding_utils import get_active_bound_window_hwnd


class ParameterPanelActionsButtonMixin:
    _BACKGROUND_ACTIONS = {'test_ocr_output', 'test_image_recognition', 'test_color_recognition'}
    _HIDE_WINDOW_ACTIONS = {'test_image_recognition', 'test_color_recognition'}

    def _handle_button_click(self, name: str, param_def: Dict[str, Any]):
        """Handle button click."""
        widget_hint = param_def.get('widget_hint', '')
        action = param_def.get('action', '')

        if widget_hint == 'refresh_dynamic_options':
            self._handle_refresh_dynamic_options(param_def)
            return

        if not action:
            logger.warning(f"未处理的按钮点击: {name}, widget_hint: {widget_hint}")
            return

        logger.info(f"执行按钮action: {action}")
        action_func = self._resolve_button_action(action)
        if action_func is None:
            logger.debug(f"任务模块中未找到action函数: {action}")
            return

        try:
            current_params = self._collect_current_parameters()
            target_hwnd = self._get_button_action_target_hwnd()
            if self._should_run_action_in_background(action):
                self._start_background_action(action, action_func, current_params, target_hwnd)
                return

            result = self._invoke_button_action(action_func, current_params, target_hwnd)
            if result is False:
                logger.warning(f"执行action失败: {action}")
                return
            logger.info(f"成功执行action: {action}")
        except Exception as e:
            logger.error(f"执行action失败: {action}, 错误: {e}", exc_info=True)

    def _resolve_button_action(self, action: str):
        if hasattr(self, 'task_module') and self.task_module and hasattr(self.task_module, action):
            return getattr(self.task_module, action)

        if not hasattr(self, 'current_task_type') or not self.current_task_type:
            return None

        try:
            from tasks import get_task_module

            logger.debug(f"从 TASK_MODULES 查找 action: {action}，任务类型: {self.current_task_type}")
            task_module = get_task_module(self.current_task_type)
            if task_module is None:
                logger.debug(f"未找到任务类型 {self.current_task_type} 对应的模块")
                return None
            logger.debug(f"找到任务模块: {task_module}, 检查是否有 {action} 属性")
            if hasattr(task_module, action):
                logger.debug(f"成功找到 action 函数: {action}")
                return getattr(task_module, action)
        except Exception as e:
            logger.debug(f"从 TASK_MODULES 获取 action 时出错: {e}")
        return None

    def _get_button_action_target_hwnd(self):
        if not hasattr(self, 'main_window') or not self.main_window:
            return None
        if hasattr(self.main_window, 'bound_windows') and isinstance(self.main_window.bound_windows, list):
            for window_info in self.main_window.bound_windows:
                if not isinstance(window_info, dict):
                    continue
                if not window_info.get('enabled', True):
                    continue
                hwnd = window_info.get('hwnd')
                if hwnd:
                    return hwnd
        if hasattr(self.main_window, 'config') and isinstance(self.main_window.config, dict):
            return get_active_bound_window_hwnd(self.main_window.config)
        return None

    def _should_run_action_in_background(self, action: str) -> bool:
        return action in self._BACKGROUND_ACTIONS

    def _start_background_action(self, action: str, action_func, current_params: Dict[str, Any], target_hwnd) -> None:
        import threading

        self._prepare_background_action_ui(action)

        def run_action_in_background():
            try:
                result = self._invoke_button_action(action_func, current_params, target_hwnd)
                if result is False:
                    logger.warning(f"后台执行action失败: {action}")
                    return
                logger.info(f"后台执行action成功: {action}")
            except Exception as e:
                logger.error(f"后台执行action失败: {action}, 错误: {e}", exc_info=True)

        thread = threading.Thread(target=run_action_in_background, daemon=True)
        thread.start()
        logger.info(f"已启动后台线程执行action: {action}")

    def _prepare_background_action_ui(self, action: str) -> None:
        if action not in self._HIDE_WINDOW_ACTIONS:
            return
        import time

        try:
            self.hide()
            if self.main_window:
                self.main_window.hide()
            time.sleep(0.2)
        except Exception as e:
            logger.warning(f"隐藏窗口失败: {e}")

    def _invoke_button_action(self, action_func, current_params: Dict[str, Any], target_hwnd):
        return action_func(
            current_params,
            target_hwnd=target_hwnd,
            main_window=self.main_window,
            parameter_panel=self,
        )
