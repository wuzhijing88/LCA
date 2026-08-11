"""
增强的窗口激活模块

v2.1 优化:
1. AttachThreadInput - 线程附加技术
2. WA_CLICKACTIVE - 精确的点击激活
3. GetLastError 错误码分析
4. 键盘激活模式 - 键盘输入前先点击激活
5. 完整的消息序列 - WM_NCHITTEST、WM_NCACTIVATE、WM_ACTIVATEAPP 等
6. PostMessage 异步发送优化
"""

import win32gui
import win32con
import win32api
import ctypes
from ctypes import wintypes
import time
import logging
from typing import Optional, Tuple

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
    """增强的窗口激活器 - 完整的激活消息序列 (v2.1)"""

    def __init__(self, enable_logging: bool = False, enable_thread_attach: bool = True):
        """
        初始化激活器

        Args:
            enable_logging: 是否启用详细日志输出
            enable_thread_attach: 是否启用线程附加技术
        """
        self.enable_logging = enable_logging
        self.enable_thread_attach = enable_thread_attach
        self.kernel32 = ctypes.windll.kernel32
        self.user32 = ctypes.windll.user32

    def _makelong(self, low: int, high: int) -> int:
        """组合两个16位值为一个32位值"""
        return ((int(high) & 0xFFFF) << 16) | (int(low) & 0xFFFF)

    def _attach_thread_input(self, hwnd: int) -> Tuple[bool, int, int]:
        """
        尝试附加到目标窗口的线程

        Args:
            hwnd: 目标窗口句柄

        Returns:
            Tuple[bool, int, int]: (是否成功附加, 当前线程ID, 目标线程ID)
        """
        if not self.enable_thread_attach:
            return False, 0, 0

        try:
            current_tid = self.kernel32.GetCurrentThreadId()
            target_tid = self.user32.GetWindowThreadProcessId(hwnd, None)

            if target_tid == 0 or current_tid == target_tid:
                return False, current_tid, target_tid

            attached = self.user32.AttachThreadInput(current_tid, target_tid, True)

            if attached:
                if self.enable_logging:
                    logger.debug(f"[线程附加] 成功: {current_tid} -> {target_tid}")
                return True, current_tid, target_tid

            error_code = self.kernel32.GetLastError()

            if error_code == 87:  # ERROR_INVALID_PARAMETER - 已附加
                if self.enable_logging:
                    logger.debug(f"[线程附加] 已附加 (错误码87)")
                return True, current_tid, target_tid
            elif error_code == 5:  # ERROR_ACCESS_DENIED
                if self.enable_logging:
                    logger.debug(f"[线程附加] 权限不足 (错误码5)")
                return False, current_tid, target_tid
            else:
                if self.enable_logging:
                    logger.debug(f"[线程附加] 失败 (错误码{error_code})")
                return False, current_tid, target_tid

        except Exception as e:
            if self.enable_logging:
                logger.debug(f"[线程附加] 异常: {e}")
            return False, 0, 0

    def _detach_thread_input(self, current_tid: int, target_tid: int) -> None:
        """解除线程附加"""
        if current_tid == 0 or target_tid == 0:
            return

        try:
            self.user32.AttachThreadInput(current_tid, target_tid, False)
            if self.enable_logging:
                logger.debug(f"[线程附加] 已解除: {current_tid} -x- {target_tid}")
        except Exception as e:
            if self.enable_logging:
                logger.debug(f"[线程附加] 解除异常: {e}")

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

        # ========== 步骤0: 线程附加 ==========
        attached, current_tid, target_tid = self._attach_thread_input(parent_hwnd)

        try:
            # 获取屏幕坐标用于命中测试
            try:
                screen_x, screen_y = win32gui.ClientToScreen(parent_hwnd, (client_x, client_y))
            except:
                screen_x, screen_y = client_x, client_y

            # ========== 步骤1: WM_NCHITTEST - 命中测试 ==========
            try:
                if self.enable_logging:
                    logger.debug(f"[激活序列] 步骤1: WM_NCHITTEST")
                hit_result = self._send_nchittest(parent_hwnd, screen_x, screen_y)
            except Exception as e:
                if self.enable_logging:
                    logger.warning(f"[激活序列] WM_NCHITTEST 失败: {e}")
                hit_result = win32con.HTCLIENT

            # ========== 步骤2: WM_NCACTIVATE - 非客户区激活 ==========
            try:
                if self.enable_logging:
                    logger.debug(f"[激活序列] 步骤2: WM_NCACTIVATE")
                # wParam=TRUE 表示激活（标题栏高亮）
                send_fn(parent_hwnd, WM_NCACTIVATE, True, 0)
            except Exception as e:
                if self.enable_logging:
                    logger.warning(f"[激活序列] WM_NCACTIVATE 失败: {e}")

            # ========== 步骤3: WM_ACTIVATEAPP - 应用程序激活 ==========
            try:
                if self.enable_logging:
                    logger.debug(f"[激活序列] 步骤3: WM_ACTIVATEAPP")
                # wParam=TRUE 表示激活，lParam=目标线程ID
                send_fn(parent_hwnd, WM_ACTIVATEAPP, True, target_tid if target_tid else 0)
            except Exception as e:
                if self.enable_logging:
                    logger.warning(f"[激活序列] WM_ACTIVATEAPP 失败: {e}")

            # ========== 步骤4: WM_ACTIVATE (WA_CLICKACTIVE) ==========
            try:
                if self.enable_logging:
                    logger.debug(f"[激活序列] 步骤4: WM_ACTIVATE (WA_CLICKACTIVE)")
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
                    logger.debug(f"[激活序列] 步骤6: WM_MOUSEACTIVATE")
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
                    logger.debug(f"[激活序列] 步骤7: WM_SETCURSOR")
                lparam_cursor = self._makelong(hit_result, win32con.WM_MOUSEMOVE)
                send_fn(target_hwnd, WM_SETCURSOR, target_hwnd, lparam_cursor)
            except Exception as e:
                if self.enable_logging:
                    logger.warning(f"[激活序列] WM_SETCURSOR 失败: {e}")

            # ========== 步骤8: WM_MOUSEMOVE ==========
            try:
                if self.enable_logging:
                    logger.debug(f"[激活序列] 步骤8: WM_MOUSEMOVE -> ({client_x}, {client_y})")
                lparam_move = win32api.MAKELONG(client_x, client_y)
                send_fn(target_hwnd, win32con.WM_MOUSEMOVE, 0, lparam_move)
            except Exception as e:
                if self.enable_logging:
                    logger.warning(f"[激活序列] WM_MOUSEMOVE 失败: {e}")

            mode_str = "线程附加+异步" if attached and use_post_message else \
                       "线程附加" if attached else \
                       "异步" if use_post_message else "标准"
            if self.enable_logging:
                logger.info(f"[激活序列] 完成 ({mode_str}模式)")

            return True

        except Exception as e:
            logger.error(f"[激活序列] 激活失败: {e}")
            return False

        finally:
            if attached:
                self._detach_thread_input(current_tid, target_tid)

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
        - 二重螺旋等游戏需要先点击激活才能接收键盘输入
        - 某些应用的键盘消息会被忽略，需要先激活

        Args:
            parent_hwnd: 父窗口句柄
            child_hwnd: 子控件句柄（可选，默认使用父窗口）
            client_x: 点击位置 X（默认100）
            client_y: 点击位置 Y（默认100）

        Returns:
            bool: 是否成功
        """
        # ========== 步骤0: 线程附加 ==========
        attached, current_tid, target_tid = self._attach_thread_input(parent_hwnd)

        try:
            target_hwnd = child_hwnd if child_hwnd else parent_hwnd

            if self.enable_logging:
                logger.debug(f"[键盘激活] 准备通过左键点击激活窗口 0x{parent_hwnd:08X}")

            # ========== 步骤1: 完整的点击激活序列 ==========
            # 调用现有的 activate_for_click 来执行完整激活
            self.activate_for_click(
                parent_hwnd=parent_hwnd,
                child_hwnd=target_hwnd,
                client_x=client_x,
                client_y=client_y,
                button='left'
            )

            # ========== 步骤2: 发送一次快速左键点击 (Jiao-Jiao 技术) ==========
            try:
                if self.enable_logging:
                    logger.debug(f"[键盘激活] 发送左键点击到 ({client_x}, {client_y})")

                lparam = win32api.MAKELONG(client_x, client_y)

                # 发送 WM_LBUTTONDOWN
                win32gui.SendMessage(target_hwnd, win32con.WM_LBUTTONDOWN, 0, lparam)
                time.sleep(0.01)

                # 发送 WM_LBUTTONUP
                win32gui.SendMessage(target_hwnd, win32con.WM_LBUTTONUP, 0, lparam)

                # Jiao-Jiao 的延迟: 50ms
                time.sleep(0.05)

                if self.enable_logging:
                    logger.info(f"[键盘激活] 完成键盘激活序列，窗口已就绪接收键盘输入")

                return True

            except Exception as e:
                if self.enable_logging:
                    logger.warning(f"[键盘激活] 点击发送失败: {e}")
                return False

        except Exception as e:
            logger.error(f"[键盘激活] 激活失败: {e}")
            return False

        finally:
            # ========== 清理: 解除线程附加 ==========
            if attached:
                self._detach_thread_input(current_tid, target_tid)

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
        # 线程附加
        attached, current_tid, target_tid = self._attach_thread_input(parent_hwnd)

        try:
            # 获取屏幕坐标
            try:
                screen_x, screen_y = win32gui.ClientToScreen(parent_hwnd, (client_x, client_y))
            except:
                screen_x, screen_y = client_x, client_y

            # 步骤1: WM_NCHITTEST - 命中测试
            try:
                if self.enable_logging:
                    logger.debug(f"[拖拽激活] 步骤1: WM_NCHITTEST")
                self._send_nchittest(parent_hwnd, screen_x, screen_y)
            except Exception as e:
                if self.enable_logging:
                    logger.debug(f"[拖拽激活] WM_NCHITTEST 异常: {e}")

            # 步骤2: WM_NCACTIVATE - 非客户区激活
            try:
                if self.enable_logging:
                    logger.debug(f"[拖拽激活] 步骤2: WM_NCACTIVATE")
                win32gui.SendMessage(parent_hwnd, WM_NCACTIVATE, True, 0)
            except Exception as e:
                if self.enable_logging:
                    logger.debug(f"[拖拽激活] WM_NCACTIVATE 异常: {e}")

            # 步骤3: WM_ACTIVATEAPP - 应用程序激活
            try:
                if self.enable_logging:
                    logger.debug(f"[拖拽激活] 步骤3: WM_ACTIVATEAPP")
                win32gui.SendMessage(parent_hwnd, WM_ACTIVATEAPP, True, target_tid if target_tid else 0)
            except Exception as e:
                if self.enable_logging:
                    logger.debug(f"[拖拽激活] WM_ACTIVATEAPP 异常: {e}")

            # 步骤4: WM_ACTIVATE
            try:
                if self.enable_logging:
                    logger.debug(f"[拖拽激活] 步骤4: WM_ACTIVATE")
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
                if self.enable_logging:
                    logger.debug(f"[拖拽激活] 步骤6: WM_MOUSEMOVE 到 ({client_x}, {client_y})")
                lparam = win32api.MAKELONG(client_x, client_y)
                win32gui.SendMessage(target_hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
            except Exception as e:
                if self.enable_logging:
                    logger.debug(f"[拖拽激活] WM_MOUSEMOVE 异常: {e}")

            if self.enable_logging:
                logger.info(f"[拖拽激活] 完成，窗口已激活，准备接收拖拽操作")
            return True

        except Exception as e:
            logger.error(f"[拖拽激活] 激活失败: {e}")
            return False

        finally:
            # 清理: 解除线程附加
            if attached:
                self._detach_thread_input(current_tid, target_tid)

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
