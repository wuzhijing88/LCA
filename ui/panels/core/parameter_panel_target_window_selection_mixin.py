from ..parameter_panel_support import *
from utils.window_binding_utils import (
    get_active_bound_window_hwnd,
    get_active_bound_windows,
    get_active_target_window_title,
)


class ParameterPanelTargetWindowSelectionMixin:
    def _get_target_window_hwnd(self):
        """获取目标窗口句柄（带全局验证）"""
        try:
            logger.info("获取目标窗口句柄...")

            # 首先检查参数面板自身是否有窗口句柄
            if hasattr(self, 'target_window_hwnd') and self.target_window_hwnd:
                logger.info(f"检测到标签页绑定的窗口句柄: {self.target_window_hwnd}")

                # 【关键修改】验证句柄是否仍在全局绑定列表中
                if self.main_window and hasattr(self.main_window, 'is_hwnd_bound'):
                    if self.main_window.is_hwnd_bound(self.target_window_hwnd):
                        logger.info(f"句柄 {self.target_window_hwnd} 已验证，在全局绑定列表中")
                        return self.target_window_hwnd
                    else:
                        logger.warning(f"句柄 {self.target_window_hwnd} 不在全局绑定列表中，静默切换到第一个有效句柄")
                        # 静默获取第一个有效句柄
                        validated_hwnd, is_original = self.main_window.validate_hwnd_or_get_first(self.target_window_hwnd)
                        if validated_hwnd:
                            logger.info(f"已静默切换到有效句柄: {validated_hwnd}（不修改标签页绑定）")
                            return validated_hwnd
                        else:
                            logger.warning(f"没有可用的全局绑定窗口，继续尝试其他方式获取")
                            # 继续往下执行
                else:
                    # 如果无法验证，直接返回
                    logger.warning("无法验证句柄有效性（未找到主窗口），使用标签页绑定的句柄")
                    return self.target_window_hwnd

            # 向上查找主窗口，获取绑定的窗口信息
            current_widget = self.parent()
            level = 0
            max_levels = 10

            while current_widget and level < max_levels:
                logger.debug(f"检查父级窗口 {level}: {type(current_widget).__name__}")

                # 检查是否有config属性（主窗口）
                if hasattr(current_widget, 'config'):
                    config = current_widget.config
                    if isinstance(config, dict):
                        hwnd = get_active_bound_window_hwnd(config)
                        if hwnd:
                            logger.info(f"从主窗口活动配置获取窗口句柄: {hwnd}")
                            return hwnd
                    elif hasattr(config, 'active_bound_windows') or hasattr(config, 'bound_windows'):
                        bound_windows = getattr(config, 'active_bound_windows', None)
                        if not isinstance(bound_windows, list):
                            bound_windows = getattr(config, 'bound_windows', None)
                        if bound_windows:
                            enabled_windows = [w for w in bound_windows if w.get('enabled', True)]
                            if enabled_windows:
                                hwnd = enabled_windows[0].get('hwnd')
                                logger.info(f"从主窗口配置对象获取窗口句柄: {hwnd}")
                                return hwnd

                # 检查是否有runner属性（参数面板）
                if hasattr(current_widget, 'runner') and hasattr(current_widget.runner, 'config'):
                    config = current_widget.runner.config
                    if isinstance(config, dict):
                        hwnd = get_active_bound_window_hwnd(config)
                        if hwnd:
                            logger.info(f"从runner活动配置获取窗口句柄: {hwnd}")
                            return hwnd
                    elif hasattr(config, 'active_bound_windows') or hasattr(config, 'bound_windows'):
                        bound_windows = getattr(config, 'active_bound_windows', None)
                        if not isinstance(bound_windows, list):
                            bound_windows = getattr(config, 'bound_windows', None)
                        if bound_windows:
                            enabled_windows = [w for w in bound_windows if w.get('enabled', True)]
                            if enabled_windows:
                                hwnd = enabled_windows[0].get('hwnd')
                                logger.info(f"从runner配置对象获取窗口句柄: {hwnd}")
                                return hwnd

                # 检查是否有bound_windows属性（主窗口直接属性）
                if hasattr(current_widget, 'bound_windows') and current_widget.bound_windows:
                    enabled_windows = [w for w in current_widget.bound_windows if w.get('enabled', True)]
                    if enabled_windows:
                        hwnd = enabled_windows[0].get('hwnd')
                        logger.info(f"从主窗口bound_windows获取窗口句柄: {hwnd}")
                        return hwnd

                # 检查是否有current_target_hwnd属性
                if hasattr(current_widget, 'current_target_hwnd') and current_widget.current_target_hwnd:
                    hwnd = current_widget.current_target_hwnd
                    logger.info(f"从主窗口current_target_hwnd获取窗口句柄: {hwnd}")
                    return hwnd

                current_widget = current_widget.parent()
                level += 1

            logger.warning("未找到任何绑定的窗口句柄")
            return None

        except Exception as e:
            logger.error(f"获取目标窗口句柄失败: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            return None

    def _get_first_window_for_selection(self):
        """获取第一个窗口用于框选区域或坐标选择"""
        try:
            # 首先检查参数面板自身是否有目标窗口信息
            if hasattr(self, 'target_window_title') and self.target_window_title:
                return self.target_window_title

            # 向上查找主窗口，获取绑定的窗口列表
            current_widget = self.parent()
            level = 0

            while current_widget and level < 10:  # 最多向上查找10层
                # 检查是否有bound_windows属性（多窗口模式）
                if hasattr(current_widget, 'bound_windows'):
                    bound_windows = current_widget.bound_windows
                    if bound_windows and len(bound_windows) > 0:
                        # 获取第一个启用的窗口
                        for window_info in bound_windows:
                            if window_info.get('enabled', True):
                                window_title = window_info.get('title')
                                if window_title:
                                    return window_title

                        # 如果没有启用的窗口，使用第一个窗口
                        first_window = bound_windows[0]
                        window_title = first_window.get('title')
                        if window_title:
                            return window_title

                # 检查是否有current_target_window_title属性（单窗口模式）
                if hasattr(current_widget, 'current_target_window_title'):
                    window_title = current_widget.current_target_window_title
                    if window_title:
                        return window_title

                # 检查是否有config属性
                if hasattr(current_widget, 'config'):
                    config = current_widget.config
                    if isinstance(config, dict):
                        target_window_title = get_active_target_window_title(config)
                        if target_window_title:
                            return target_window_title

                        bound_windows = get_active_bound_windows(config)
                        if bound_windows:
                            for window_info in bound_windows:
                                if window_info.get('enabled', True):
                                    window_title = window_info.get('title')
                                    if window_title:
                                        return window_title
                    elif config and hasattr(config, 'get'):
                        target_window_title = config.get('active_target_window_title') or config.get('target_window_title')
                        if target_window_title:
                            return target_window_title

                # 向上查找父窗口
                current_widget = current_widget.parent()
                level += 1

            return None
        except Exception as e:
            logger.error(f"获取第一个窗口失败: {e}")
            return None
