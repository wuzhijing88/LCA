from ..parameter_panel_support import *


class ParameterPanelTargetWindowResolutionMixin:
    def _get_target_hwnd_with_info(self) -> tuple[Optional[int], Optional[str]]:
        """获取目标窗口句柄和窗口标题"""
        try:
            import win32gui

            logger.debug("开始获取目标窗口句柄和信息...")

            # 检查父窗口是否存在
            if not self.parent_window:
                logger.error("父窗口不存在")
                return None, None

            # 从绑定窗口列表获取第一个有效窗口（多窗口时使用第一个）
            if hasattr(self.parent_window, 'bound_windows'):
                bound_windows = self.parent_window.bound_windows
                logger.debug(f"找到绑定窗口列表，共 {len(bound_windows)} 个窗口")

                if bound_windows:
                    # 使用第一个窗口进行录制
                    first_window = bound_windows[0]
                    window_title = first_window.get('title', '未知')
                    hwnd = first_window.get('hwnd')
                    enabled = first_window.get('enabled', True)

                    logger.info(f"多窗口录制：使用第一个窗口 - {window_title} (句柄: {hwnd}, 启用: {enabled})")

                    if hwnd and win32gui.IsWindow(hwnd):
                        logger.info(f"选择录制窗口: {window_title} (句柄: {hwnd})")
                        return hwnd, window_title
                    else:
                        logger.warning(f"第一个窗口句柄已失效: {window_title} (句柄: {hwnd})")
            else:
                logger.debug("父窗口没有bound_windows属性")

            # 检查是否有current_target_hwnd
            if hasattr(self.parent_window, 'current_target_hwnd'):
                hwnd = self.parent_window.current_target_hwnd
                if hwnd and win32gui.IsWindow(hwnd):
                    window_title = win32gui.GetWindowText(hwnd)
                    logger.info(f"使用current_target_hwnd: {hwnd} ({window_title})")
                    return hwnd, window_title
                elif hwnd:
                    logger.warning(f"current_target_hwnd已失效: {hwnd}")
            else:
                logger.debug("父窗口没有current_target_hwnd属性")

            logger.error("未找到任何有效的绑定窗口句柄")
            return None, None

        except Exception as e:
            logger.error(f"获取目标窗口句柄失败: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            return None, None

    def _get_target_hwnd(self) -> Optional[int]:
        """获取目标窗口句柄 - 直接使用全局设置中的绑定窗口"""
        try:
            import win32gui

            logger.debug("开始获取目标窗口句柄...")

            # 检查父窗口是否存在
            if not self.parent_window:
                logger.error("父窗口不存在")
                return None

            # 从绑定窗口列表获取第一个有效窗口
            if hasattr(self.parent_window, 'bound_windows'):
                bound_windows = self.parent_window.bound_windows
                logger.debug(f"找到绑定窗口列表，共 {len(bound_windows)} 个窗口")

                for i, window_info in enumerate(bound_windows):
                    window_title = window_info.get('title', '未知')
                    hwnd = window_info.get('hwnd')
                    enabled = window_info.get('enabled', True)

                    logger.debug(f"检查窗口 {i+1}: {window_title}, hwnd={hwnd}, enabled={enabled}")

                    if enabled and hwnd:
                        # 验证窗口句柄是否有效
                        if win32gui.IsWindow(hwnd):
                            logger.info(f"找到有效的绑定窗口: {window_title} (句柄: {hwnd})")
                            return hwnd
                        else:
                            logger.warning(f"绑定窗口句柄已失效: {window_title} (句柄: {hwnd})")

                # 如果没有启用的窗口，尝试使用第一个窗口
                if bound_windows:
                    first_window = bound_windows[0]
                    hwnd = first_window.get('hwnd')
                    if hwnd and win32gui.IsWindow(hwnd):
                        logger.info(f"使用第一个绑定窗口: {first_window.get('title', '未知')} (句柄: {hwnd})")
                        return hwnd
            else:
                logger.debug("父窗口没有bound_windows属性")

            # 检查是否有current_target_hwnd
            if hasattr(self.parent_window, 'current_target_hwnd'):
                hwnd = self.parent_window.current_target_hwnd
                if hwnd and win32gui.IsWindow(hwnd):
                    logger.info(f"使用current_target_hwnd: {hwnd}")
                    return hwnd
                elif hwnd:
                    logger.warning(f"current_target_hwnd已失效: {hwnd}")
            else:
                logger.debug("父窗口没有current_target_hwnd属性")

            logger.error("全局设置中没有有效的绑定窗口句柄")
            return None

        except Exception as e:
            logger.error(f"获取目标窗口句柄失败: {e}")
            return None
