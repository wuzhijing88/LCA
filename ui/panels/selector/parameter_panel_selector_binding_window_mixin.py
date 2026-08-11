from ..parameter_panel_support import *
from utils.window_binding_utils import (
    get_active_bound_window_hwnd,
    get_active_bound_windows,
    get_active_target_window_title,
)


class ParameterPanelSelectorBindingWindowMixin:
    def _get_enabled_bound_windows_for_selector(self) -> List[Dict[str, Any]]:
        candidates = []

        try:
            if self.main_window is not None:
                if hasattr(self.main_window, "bound_windows") and isinstance(self.main_window.bound_windows, list):
                    candidates = self.main_window.bound_windows
                elif hasattr(self.main_window, "config"):
                    config = self.main_window.config
                    if isinstance(config, dict):
                        candidates = get_active_bound_windows(config)
                    else:
                        active_windows = getattr(config, "active_bound_windows", None)
                        if isinstance(active_windows, list):
                            candidates = active_windows
                        elif hasattr(config, "bound_windows"):
                            candidates = config.bound_windows or []

            if not candidates and self.parent_window is not None:
                if hasattr(self.parent_window, "bound_windows") and isinstance(self.parent_window.bound_windows, list):
                    candidates = self.parent_window.bound_windows
                elif hasattr(self.parent_window, "config"):
                    config = self.parent_window.config
                    if isinstance(config, dict):
                        candidates = get_active_bound_windows(config)
                    else:
                        active_windows = getattr(config, "active_bound_windows", None)
                        if isinstance(active_windows, list):
                            candidates = active_windows
                        elif hasattr(config, "bound_windows"):
                            candidates = config.bound_windows or []
        except Exception as e:
            logger.debug(f"绑定窗口选择器来源失败：{e}")
            return []

        enabled_windows = []
        for window_info in candidates or []:
            if not isinstance(window_info, dict):
                continue
            if not window_info.get("enabled", True):
                continue
            enabled_windows.append(window_info)
        return enabled_windows

    def _get_bound_window_hwnd(self) -> Optional[int]:
        """获取当前绑定的窗口句柄（带全局验证）"""
        try:
            # 1. 优先使用传入的target_window_hwnd(来自标签页绑定或全局配置)
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
                            # 继续往下执行，尝试从全局配置获取
                else:
                    # 如果无法验证（没有主窗口），直接返回
                    logger.warning("无法验证句柄有效性（未找到主窗口），使用标签页绑定的句柄")
                    return self.target_window_hwnd

            # 2. 回退到从parent_window的config获取
            if self.parent_window:
                # 检查 parent_window 是否有 config 属性
                if hasattr(self.parent_window, 'config'):
                    config = self.parent_window.config

                    # config 可能是字典
                    if isinstance(config, dict):
                        hwnd = get_active_bound_window_hwnd(config)
                        if hwnd:
                            logger.info(f"从活动配置获取窗口句柄: {hwnd}")
                            return hwnd

                        target_window_title = get_active_target_window_title(config)
                        if target_window_title:
                            # 需要通过标题查找窗口句柄
                            try:
                                import win32gui
                                def find_window_by_title(title):
                                    windows = []
                                    def enum_windows_callback(hwnd, _):
                                        if win32gui.IsWindowVisible(hwnd):
                                            window_title = win32gui.GetWindowText(hwnd)
                                            if window_title == title:
                                                windows.append(hwnd)
                                    win32gui.EnumWindows(enum_windows_callback, None)
                                    if len(windows) == 1:
                                        return windows[0]
                                    if len(windows) > 1:
                                        logger.warning(f"通过标题找到多个同名窗口，拒绝自动选择: {title} -> {windows}")
                                    return None

                                hwnd = find_window_by_title(target_window_title)
                                if hwnd:
                                    logger.info(f"通过标题查找到窗口句柄: {hwnd}")
                                    return hwnd
                            except Exception as e:
                                logger.warning(f"通过标题查找窗口句柄失败: {e}")

                    # config 可能是对象
                    else:
                        active_windows = getattr(config, 'active_bound_windows', None)
                        if not isinstance(active_windows, list):
                            active_windows = getattr(config, 'bound_windows', None)

                        if active_windows:
                            enabled_windows = [w for w in active_windows if w.get('enabled', True)]
                            if enabled_windows:
                                hwnd = enabled_windows[0].get('hwnd')
                                if hwnd:
                                    logger.info(f"从活动配置对象获取窗口句柄: {hwnd}")
                                    return hwnd

                        target_window_title = getattr(config, 'active_target_window_title', None) or getattr(config, 'target_window_title', None)
                        if target_window_title:
                            # 通过标题查找
                            try:
                                import win32gui
                                def find_window_by_title(title):
                                    windows = []
                                    def enum_windows_callback(hwnd, _):
                                        if win32gui.IsWindowVisible(hwnd):
                                            window_title = win32gui.GetWindowText(hwnd)
                                            if window_title == title:
                                                windows.append(hwnd)
                                    win32gui.EnumWindows(enum_windows_callback, None)
                                    if len(windows) == 1:
                                        return windows[0]
                                    if len(windows) > 1:
                                        logger.warning(f"通过标题找到多个同名窗口，拒绝自动选择: {title} -> {windows}")
                                    return None

                                hwnd = find_window_by_title(target_window_title)
                                if hwnd:
                                    logger.info(f"通过标题查找到窗口句柄: {hwnd}")
                                    return hwnd
                            except Exception as e:
                                logger.warning(f"通过标题查找窗口句柄失败: {e}")

            logger.warning("未找到任何窗口句柄")
            return None

        except Exception as e:
            logger.error(f"获取绑定窗口句柄时出错: {e}")
            import traceback
            logger.error(f"错误详情:\n{traceback.format_exc()}")
            return None
