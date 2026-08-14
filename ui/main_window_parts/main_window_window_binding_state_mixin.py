import logging

from utils.window_binding_utils import (
    get_active_target_window_title,
    get_native_bound_windows,
    get_window_binding_mode,
    sync_runtime_window_binding_state,
)
from utils.window_identity import match_bound_window, refresh_bound_windows

logger = logging.getLogger(__name__)


class MainWindowWindowBindingStateMixin:

    def _sync_runtime_window_binding_state(self):

        if not hasattr(self, 'config') or not isinstance(self.config, dict):

            return

        self.native_bound_windows = get_native_bound_windows(self.config)

        self.native_window_binding_mode = get_window_binding_mode(self.config)

        self.bound_windows = self.native_bound_windows

        self.window_binding_mode = self.native_window_binding_mode

        sync_runtime_window_binding_state(self.config)
        self._publish_instance_bound_hwnds()

        if self.window_binding_mode == 'multiple':

            self.current_target_window_title = get_active_target_window_title(self.config)

        elif self.bound_windows:

            self.current_target_window_title = str(self.bound_windows[0].get('title', '') or '').strip() or None

    def get_bound_windows(self):

        return list(self.bound_windows or [])

    def _store_runtime_bound_windows_to_config(self):

        if not hasattr(self, 'config') or not isinstance(self.config, dict):

            return

        self.native_bound_windows = self.bound_windows

        self.native_window_binding_mode = self.window_binding_mode

        self.config['bound_windows'] = self.native_bound_windows

        self.config['window_binding_mode'] = self.native_window_binding_mode

        sync_runtime_window_binding_state(self.config)
        self._publish_instance_bound_hwnds()

    def _publish_instance_bound_hwnds(self):
        try:
            from utils.instance_runtime import publish_bound_hwnds

            publish_bound_hwnds(getattr(self, "bound_windows", None))
        except Exception:
            pass

    def _update_task_window_binding(self, task):

        """

        检查任务的窗口绑定信息（不修改绑定状态）

        Args:

            task: WorkflowTask对象

        """

        # 【关键修复】只验证窗口绑定，不修改任务的绑定状态

        # 如果窗口绑定失效，让 _create_executor 中的逻辑来处理

        if task.target_hwnd or task.target_window_title or getattr(task, 'bound_window_id', None):

            refresh_bound_windows(self.bound_windows)
            matched_window = match_bound_window(
                self.bound_windows,
                hwnd=task.target_hwnd,
                title=task.target_window_title,
                bind_id=getattr(task, 'bound_window_id', None),
            )

            if matched_window:

                new_hwnd = matched_window.get('hwnd')
                if new_hwnd and new_hwnd != task.target_hwnd:
                    logger.info(
                        f"任务 '{task.name}' 绑定窗口句柄已重连: {task.target_hwnd} => {new_hwnd}"
                    )
                    task.target_hwnd = new_hwnd
                if matched_window.get('title'):
                    task.target_window_title = matched_window.get('title')
                logger.info(f"任务 '{task.name}' 已绑定窗口 (HWND: {task.target_hwnd}, '{task.target_window_title}')，且窗口仍在全局设置中")

                self._update_task_execution_mode(task)

                return

            else:

                logger.warning(f"任务 '{task.name}' 绑定的窗口 (HWND: {task.target_hwnd}, '{task.target_window_title}') 已从全局设置中移除或被禁用")

                logger.warning("  保留任务的绑定信息，执行时将提示用户处理")

                self._update_task_execution_mode(task)

                return

        # 任务没有绑定窗口

        # [注意] 不自动设置窗口绑定，保持任务的"未绑定"状态

        # 执行时会使用全局配置的第一个窗口

        logger.info(f"任务 '{task.name}' 未绑定窗口，执行时将使用全局配置的第一个启用窗口")

        # 更新执行模式

        self._update_task_execution_mode(task)

    def is_hwnd_bound(self, hwnd):

        """

        检查指定句柄是否在全局绑定列表中

        Args:

            hwnd: 窗口句柄（可以是整数或字符串"ALL_BOUND"）

        Returns:

            bool: True如果句柄在绑定列表中，False否则

        """

        if not hwnd:

            return False

        # 特殊值"ALL_BOUND"总是返回False，因为它不是有效的窗口句柄

        if hwnd == "ALL_BOUND":

            logger.warning("检测到特殊标记ALL_BOUND，这不是有效的窗口句柄")

            return False

        # 检查句柄是否在绑定列表中

        for window in self.bound_windows:

            if window.get('hwnd') == hwnd:

                return True

        return False

    def validate_hwnd_or_get_first(self, hwnd):

        """

        验证句柄是否有效，如果无效则返回第一个绑定的窗口句柄

        Args:

            hwnd: 要验证的窗口句柄

        Returns:

            tuple: (valid_hwnd, is_original)

                   valid_hwnd - 有效的句柄（可能是原句柄或第一个窗口）

                   is_original - True如果返回的是原句柄，False如果是替换的

        """

        # 检查原句柄是否有效

        if hwnd and self.is_hwnd_bound(hwnd):

            return hwnd, True

        # 原句柄无效时，仅在只有一个可用绑定窗口时才允许自动切换

        valid_hwnds = []

        if self.bound_windows:

            for window_info in self.bound_windows:

                candidate_hwnd = window_info.get('hwnd')

                if candidate_hwnd and candidate_hwnd != "ALL_BOUND":

                    valid_hwnds.append(candidate_hwnd)

        if len(valid_hwnds) == 1:

            fallback_hwnd = valid_hwnds[0]

            logger.warning(f"原句柄 {hwnd} 无效或未绑定，已切换到唯一可用窗口: {fallback_hwnd}")

            return fallback_hwnd, False

        if len(valid_hwnds) > 1:

            logger.error(f"句柄 {hwnd} 无效，当前存在 {len(valid_hwnds)} 个可用绑定窗口，拒绝自动切换")

            return None, False

        # 没有可用的窗口

        logger.error(f"句柄 {hwnd} 无效且没有其他可用窗口")

        return None, False
