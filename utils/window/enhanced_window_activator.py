"""
后台激活消息序列：不改前台、不改真实焦点，只用消息让目标窗口“以为”自己被点击激活了。

- WA_CLICKACTIVE 点击激活
- 键盘激活模式：键盘输入前先来一次点击激活
- 完整消息序列：WM_NCHITTEST、WM_NCACTIVATE、WM_ACTIVATEAPP、WM_ACTIVATE、WM_SETFOCUS、WM_MOUSEACTIVATE…
- PostMessage 异步发送可选

这里刻意不用 AttachThreadInput：整套流程只发消息，附加线程输入对它毫无帮助，
反而会在解除附加的瞬间把目标线程的焦点/激活状态搅乱——资源管理器随后收到的
双击就只当成“选中”，文件永远打不开。
"""

import win32gui
import win32con
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Windows 常量补充
WM_NCACTIVATE = 0x0086
WM_ACTIVATEAPP = 0x001C
WM_NCHITTEST = 0x0084
WM_NCMOUSEMOVE = 0x00A0
WM_NCLBUTTONDOWN = 0x00A1
WM_SETCURSOR = 0x0020
WM_KILLFOCUS = 0x0008


class EnhancedWindowActivator:
    """后台激活器：向目标窗口发送完整的“被点击激活”消息序列。"""

    def __init__(self, enable_logging: bool = False):
        self.enable_logging = enable_logging

    def _makelong(self, low: int, high: int) -> int:
        """组合两个16位值为一个32位值"""
        return ((int(high) & 0xFFFF) << 16) | (int(low) & 0xFFFF)

    @staticmethod
    def _window_thread_id(hwnd: int) -> int:
        try:
            import win32process

            thread_id, _pid = win32process.GetWindowThreadProcessId(int(hwnd))
            return int(thread_id or 0)
        except Exception:
            return 0

    @staticmethod
    def _client_point_for(target_hwnd: int, parent_hwnd: int, client_x: int, client_y: int):
        """鼠标消息的坐标必须是接收窗口自己的客户区坐标；传进来的是父窗口客户区坐标。"""
        if int(target_hwnd) == int(parent_hwnd):
            return int(client_x), int(client_y)
        try:
            screen_x, screen_y = win32gui.ClientToScreen(int(parent_hwnd), (int(client_x), int(client_y)))
            return win32gui.ScreenToClient(int(target_hwnd), (screen_x, screen_y))
        except Exception:
            return int(client_x), int(client_y)

    def _send_nchittest(self, hwnd: int, screen_x: int, screen_y: int) -> int:
        """
        发送 WM_NCHITTEST 消息，获取命中测试结果

        这是成熟方案的关键步骤：告诉窗口鼠标在哪个区域
        """
        try:
            lparam = self._makelong(screen_x, screen_y)
            result = win32gui.SendMessage(hwnd, WM_NCHITTEST, 0, lparam)
            if self.enable_logging:
                logger.debug(f"[WM_NCHITTEST] hwnd=0x{hwnd:08X}, 结果={result}")
            return result
        except Exception as e:
            if self.enable_logging:
                logger.debug(f"[WM_NCHITTEST] 失败: {e}")
            return win32con.HTCLIENT  # 默认返回客户区

    def activate_for_click(
        self,
        parent_hwnd: int,
        child_hwnd: int,
        client_x: int,
        client_y: int,
        button: str = 'left',
        use_post_message: bool = False
    ) -> bool:
        """
        为点击操作激活窗口（v2.1 完整消息序列版）

        完整消息序列（模拟真实用户操作）:
        1. WM_NCHITTEST - 命中测试（告诉窗口鼠标位置）
        2. WM_NCACTIVATE - 非客户区激活（标题栏高亮）
        3. WM_ACTIVATEAPP - 应用程序激活
        4. WM_ACTIVATE (WA_CLICKACTIVE) - 窗口激活（点击激活类型）
        5. WM_SETFOCUS - 设置键盘焦点
        6. WM_MOUSEACTIVATE - 鼠标激活
        7. WM_SETCURSOR - 设置光标
        8. WM_MOUSEMOVE - 鼠标移动到目标位置

        Args:
            parent_hwnd: 父窗口句柄
            child_hwnd: 子控件句柄
            client_x: 客户区坐标 X
            client_y: 客户区坐标 Y
            button: 鼠标按钮
            use_post_message: 是否使用 PostMessage（异步，减少阻塞）

        Returns:
            bool: 是否成功
        """
        # 选择发送函数
        send_fn = win32gui.PostMessage if use_post_message else win32gui.SendMessage
        target_tid = self._window_thread_id(parent_hwnd)

        try:
            # 获取屏幕坐标用于命中测试
            try:
                screen_x, screen_y = win32gui.ClientToScreen(parent_hwnd, (client_x, client_y))
            except Exception:
                screen_x, screen_y = client_x, client_y

            # ========== 步骤1: WM_NCHITTEST - 命中测试 ==========
            try:
                if self.enable_logging:
                    logger.debug("[激活序列] 步骤1: WM_NCHITTEST")
                hit_result = self._send_nchittest(parent_hwnd, screen_x, screen_y)
            except Exception as e:
                if self.enable_logging:
                    logger.warning(f"[激活序列] WM_NCHITTEST 失败: {e}")
                hit_result = win32con.HTCLIENT

            # ========== 步骤2: WM_NCACTIVATE - 非客户区激活 ==========
            try:
                if self.enable_logging:
                    logger.debug("[激活序列] 步骤2: WM_NCACTIVATE")
                # wParam=TRUE 表示激活（标题栏高亮）
                send_fn(parent_hwnd, WM_NCACTIVATE, True, 0)
            except Exception as e:
                if self.enable_logging:
                    logger.warning(f"[激活序列] WM_NCACTIVATE 失败: {e}")

            # ========== 步骤3: WM_ACTIVATEAPP - 应用程序激活 ==========
            try:
                if self.enable_logging:
                    logger.debug("[激活序列] 步骤3: WM_ACTIVATEAPP")
                # wParam=TRUE 表示激活，lParam=目标线程ID
                send_fn(parent_hwnd, WM_ACTIVATEAPP, True, target_tid if target_tid else 0)
            except Exception as e:
                if self.enable_logging:
                    logger.warning(f"[激活序列] WM_ACTIVATEAPP 失败: {e}")

            # ========== 步骤4: WM_ACTIVATE (WA_CLICKACTIVE) ==========
            try:
                if self.enable_logging:
                    logger.debug("[激活序列] 步骤4: WM_ACTIVATE (WA_CLICKACTIVE)")
                # 使用 WA_CLICKACTIVE (2) 更精确模拟鼠标点击激活
                send_fn(parent_hwnd, win32con.WM_ACTIVATE, win32con.WA_CLICKACTIVE, 0)
                time.sleep(0.005)  # 5ms 延迟
            except Exception as e:
                if self.enable_logging:
                    logger.warning(f"[激活序列] WM_ACTIVATE 失败: {e}")

            # ========== 步骤5: WM_SETFOCUS - 设置焦点 ==========
            target_hwnd = child_hwnd if child_hwnd else parent_hwnd
            try:
                if self.enable_logging:
                    logger.debug(f"[激活序列] 步骤5: WM_SETFOCUS -> 0x{target_hwnd:08X}")
                send_fn(target_hwnd, win32con.WM_SETFOCUS, 0, 0)
            except Exception as e:
                if self.enable_logging:
                    logger.warning(f"[激活序列] WM_SETFOCUS 失败: {e}")

            # ========== 步骤6: WM_MOUSEACTIVATE ==========
            try:
                if self.enable_logging:
                    logger.debug("[激活序列] 步骤6: WM_MOUSEACTIVATE")
                if button == 'left':
                    mouse_msg = win32con.WM_LBUTTONDOWN
                elif button == 'right':
                    mouse_msg = win32con.WM_RBUTTONDOWN
                elif button == 'middle':
                    mouse_msg = win32con.WM_MBUTTONDOWN
                else:
                    mouse_msg = win32con.WM_LBUTTONDOWN

                lparam_ma = self._makelong(mouse_msg, hit_result)
                send_fn(parent_hwnd, win32con.WM_MOUSEACTIVATE, parent_hwnd, lparam_ma)
            except Exception as e:
                if self.enable_logging:
                    logger.warning(f"[激活序列] WM_MOUSEACTIVATE 失败: {e}")

            # ========== 步骤7: WM_SETCURSOR ==========
            try:
                if self.enable_logging:
                    logger.debug("[激活序列] 步骤7: WM_SETCURSOR")
                lparam_cursor = self._makelong(hit_result, win32con.WM_MOUSEMOVE)
                send_fn(target_hwnd, WM_SETCURSOR, target_hwnd, lparam_cursor)
            except Exception as e:
                if self.enable_logging:
                    logger.warning(f"[激活序列] WM_SETCURSOR 失败: {e}")

            # ========== 步骤8: WM_MOUSEMOVE ==========
            try:
                move_x, move_y = self._client_point_for(target_hwnd, parent_hwnd, client_x, client_y)
                if self.enable_logging:
                    logger.debug(f"[激活序列] 步骤8: WM_MOUSEMOVE -> ({move_x}, {move_y})")
                lparam_move = self._makelong(move_x, move_y)
                send_fn(target_hwnd, win32con.WM_MOUSEMOVE, 0, lparam_move)
            except Exception as e:
                if self.enable_logging:
                    logger.warning(f"[激活序列] WM_MOUSEMOVE 失败: {e}")

            if self.enable_logging:
                logger.info(f"[激活序列] 完成 ({'异步' if use_post_message else '标准'}模式)")

            return True

        except Exception as e:
            logger.error(f"[激活序列] 激活失败: {e}")
            return False

    def activate_for_keyboard(
        self,
        parent_hwnd: int,
        child_hwnd: Optional[int] = None,
        client_x: int = 100,
        client_y: int = 100
    ) -> bool:
        """
        为键盘输入激活窗口（键盘专用激活 v2.0）

        借鉴 Jiao-Jiao-Assistant 的技术:
        "首步为键盘，先发送一次左键点击以激活后台窗口"

        适用场景:
        - 部分全屏或独占输入应用需要先点击激活才能接收键盘输入
        - 某些应用的键盘消息会被忽略，需要先激活

        Args:
            parent_hwnd: 父窗口句柄
            child_hwnd: 子控件句柄（可选，默认使用父窗口）
            client_x: 点击位置 X（默认100）
            client_y: 点击位置 Y（默认100）

        Returns:
            bool: 是否成功
        """
        try:
            target_hwnd = child_hwnd if child_hwnd else parent_hwnd

            if self.enable_logging:
                logger.debug(f"[键盘激活] 准备通过左键点击激活窗口 0x{parent_hwnd:08X}")

            # ========== 步骤1: 完整的点击激活序列 ==========
            self.activate_for_click(
                parent_hwnd=parent_hwnd,
                child_hwnd=target_hwnd,
                client_x=client_x,
                client_y=client_y,
                button='left'
            )

            # ========== 步骤2: 发送一次快速左键点击 (Jiao-Jiao 技术) ==========
            try:
                click_x, click_y = self._client_point_for(target_hwnd, parent_hwnd, client_x, client_y)
                if self.enable_logging:
                    logger.debug(f"[键盘激活] 发送左键点击到 ({click_x}, {click_y})")

                lparam = self._makelong(click_x, click_y)

                win32gui.SendMessage(target_hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
                time.sleep(0.01)
                win32gui.SendMessage(target_hwnd, win32con.WM_LBUTTONUP, 0, lparam)

                # Jiao-Jiao 的延迟: 50ms
                time.sleep(0.05)

                if self.enable_logging:
                    logger.info("[键盘激活] 完成键盘激活序列，窗口已就绪接收键盘输入")

                return True

            except Exception as e:
                if self.enable_logging:
                    logger.warning(f"[键盘激活] 点击发送失败: {e}")
                return False

        except Exception as e:
            logger.error(f"[键盘激活] 激活失败: {e}")
            return False

    def activate_for_drag(
        self,
        parent_hwnd: int,
        child_hwnd: int,
        client_x: int,
        client_y: int
    ) -> bool:
        """
        为拖拽操作激活窗口（拖拽专用激活）

        与点击激活的区别：
        - 不发送实际的点击消息
        - 只发送激活和焦点消息
        - 适合需要精确控制拖拽起点的场景

        Args:
            parent_hwnd: 父窗口句柄
            child_hwnd: 子控件句柄
            client_x: 客户区坐标 X
            client_y: 客户区坐标 Y

        Returns:
            bool: 是否成功
        """
        target_tid = self._window_thread_id(parent_hwnd)

        try:
            # 获取屏幕坐标
            try:
                screen_x, screen_y = win32gui.ClientToScreen(parent_hwnd, (client_x, client_y))
            except Exception:
                screen_x, screen_y = client_x, client_y

            # 步骤1: WM_NCHITTEST - 命中测试
            try:
                if self.enable_logging:
                    logger.debug("[拖拽激活] 步骤1: WM_NCHITTEST")
                self._send_nchittest(parent_hwnd, screen_x, screen_y)
            except Exception as e:
                if self.enable_logging:
                    logger.debug(f"[拖拽激活] WM_NCHITTEST 异常: {e}")

            # 步骤2: WM_NCACTIVATE - 非客户区激活
            try:
                if self.enable_logging:
                    logger.debug("[拖拽激活] 步骤2: WM_NCACTIVATE")
                win32gui.SendMessage(parent_hwnd, WM_NCACTIVATE, True, 0)
            except Exception as e:
                if self.enable_logging:
                    logger.debug(f"[拖拽激活] WM_NCACTIVATE 异常: {e}")

            # 步骤3: WM_ACTIVATEAPP - 应用程序激活
            try:
                if self.enable_logging:
                    logger.debug("[拖拽激活] 步骤3: WM_ACTIVATEAPP")
                win32gui.SendMessage(parent_hwnd, WM_ACTIVATEAPP, True, target_tid if target_tid else 0)
            except Exception as e:
                if self.enable_logging:
                    logger.debug(f"[拖拽激活] WM_ACTIVATEAPP 异常: {e}")

            # 步骤4: WM_ACTIVATE
            try:
                if self.enable_logging:
                    logger.debug("[拖拽激活] 步骤4: WM_ACTIVATE")
                win32gui.SendMessage(parent_hwnd, win32con.WM_ACTIVATE, win32con.WA_CLICKACTIVE, 0)
                time.sleep(0.005)
            except Exception as e:
                if self.enable_logging:
                    logger.debug(f"[拖拽激活] WM_ACTIVATE 异常: {e}")

            # 步骤5: WM_SETFOCUS - 设置焦点到目标窗口
            target_hwnd = child_hwnd if child_hwnd else parent_hwnd
            try:
                if self.enable_logging:
                    logger.debug(f"[拖拽激活] 步骤5: WM_SETFOCUS -> 0x{target_hwnd:08X}")
                win32gui.SendMessage(target_hwnd, win32con.WM_SETFOCUS, 0, 0)
            except Exception as e:
                if self.enable_logging:
                    logger.debug(f"[拖拽激活] WM_SETFOCUS 异常: {e}")

            # 步骤6: WM_MOUSEMOVE - 鼠标移动到起点（无需点击）
            try:
                move_x, move_y = self._client_point_for(target_hwnd, parent_hwnd, client_x, client_y)
                if self.enable_logging:
                    logger.debug(f"[拖拽激活] 步骤6: WM_MOUSEMOVE 到 ({move_x}, {move_y})")
                win32gui.SendMessage(target_hwnd, win32con.WM_MOUSEMOVE, 0, self._makelong(move_x, move_y))
            except Exception as e:
                if self.enable_logging:
                    logger.debug(f"[拖拽激活] WM_MOUSEMOVE 异常: {e}")

            if self.enable_logging:
                logger.info("[拖拽激活] 完成，窗口已激活，准备接收拖拽操作")
            return True

        except Exception as e:
            logger.error(f"[拖拽激活] 激活失败: {e}")
            return False

    def ensure_window_restored(self, hwnd: int) -> bool:
        """
        确保窗口不是最小化状态

        Args:
            hwnd: 窗口句柄

        Returns:
            bool: 是否成功
        """
        try:
            placement = win32gui.GetWindowPlacement(hwnd)
            show_cmd = placement[1]

            if show_cmd == win32con.SW_SHOWMINIMIZED:
                from utils.window.virtual_desktop import skip_cross_desktop_activation

                if skip_cross_desktop_activation(hwnd, log_prefix="窗口恢复"):
                    return False
                if self.enable_logging:
                    logger.info(f"窗口 0x{hwnd:08X} 处于最小化状态，正在恢复...")

                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                time.sleep(0.2)  # 等待窗口恢复
                return True

            return True
        except Exception as e:
            logger.error(f"恢复窗口状态失败: {e}")
            return False


# 全局单例
_global_activator = None

def get_window_activator(enable_logging: bool = False) -> EnhancedWindowActivator:
    """获取全局窗口激活器实例"""
    global _global_activator
    if _global_activator is None:
        _global_activator = EnhancedWindowActivator(enable_logging=enable_logging)
    return _global_activator
