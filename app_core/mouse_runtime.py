import ctypes
import logging

logger = logging.getLogger(__name__)


class MouseMoveFixer:
    """鼠标移动修复器，统一使用客户区坐标，支持多显示器。"""

    def __init__(self):
        self.user32 = ctypes.windll.user32
        self._monitor_manager = None

    def _get_monitor_manager(self):
        if self._monitor_manager is None:
            try:
                from utils.multi_monitor_manager import get_multi_monitor_manager

                self._monitor_manager = get_multi_monitor_manager()
            except ImportError:
                pass
        return self._monitor_manager

    def get_virtual_screen_bounds(self):
        manager = self._get_monitor_manager()
        if manager:
            return manager.get_virtual_screen_bounds()

        sm_x_virtual_screen = 76
        sm_y_virtual_screen = 77
        sm_cx_virtual_screen = 78
        sm_cy_virtual_screen = 79

        left = self.user32.GetSystemMetrics(sm_x_virtual_screen)
        top = self.user32.GetSystemMetrics(sm_y_virtual_screen)
        width = self.user32.GetSystemMetrics(sm_cx_virtual_screen)
        height = self.user32.GetSystemMetrics(sm_cy_virtual_screen)
        return left, top, width, height

    def convert_client_to_screen(self, hwnd, client_x, client_y):
        try:
            from ctypes import wintypes

            point = wintypes.POINT(int(client_x), int(client_y))
            if self.user32.ClientToScreen(hwnd, ctypes.byref(point)):
                return point.x, point.y
            logger.warning("ClientToScreen转换失败")
            return client_x, client_y
        except Exception as exc:
            logger.error(f"坐标转换失败: {exc}")
            return client_x, client_y

    def convert_screen_to_client(self, hwnd, screen_x, screen_y):
        try:
            from ctypes import wintypes

            point = wintypes.POINT(int(screen_x), int(screen_y))
            if self.user32.ScreenToClient(hwnd, ctypes.byref(point)):
                return point.x, point.y
            logger.warning("ScreenToClient转换失败")
            return screen_x, screen_y
        except Exception as exc:
            logger.error(f"坐标转换失败: {exc}")
            return screen_x, screen_y

    def validate_client_coordinates(self, hwnd, client_x, client_y):
        try:
            import win32gui

            client_rect = win32gui.GetClientRect(hwnd)
            max_x = client_rect[2] - client_rect[0] - 1
            max_y = client_rect[3] - client_rect[1] - 1
            final_x = max(0, min(client_x, max_x))
            final_y = max(0, min(client_y, max_y))

            if final_x != client_x or final_y != client_y:
                logger.debug(
                    f"坐标修正: ({client_x}, {client_y}) -> ({final_x}, {final_y}) "
                    f"[客户区: 0,0-{max_x},{max_y}]"
                )
            return final_x, final_y
        except Exception as exc:
            logger.error(f"坐标验证失败: {exc}")
            return client_x, client_y

    def safe_move_to_client_coord(self, hwnd, client_x, client_y, duration=0):
        try:
            import pyautogui

            screen_x, screen_y = self.convert_client_to_screen(hwnd, client_x, client_y)
            v_left, v_top, v_width, v_height = self.get_virtual_screen_bounds()
            screen_x = max(v_left, min(screen_x, v_left + v_width - 1))
            screen_y = max(v_top, min(screen_y, v_top + v_height - 1))

            pyautogui.FAILSAFE = False
            pyautogui.PAUSE = 0
            pyautogui.moveTo(screen_x, screen_y, duration=duration)
            return True
        except Exception as exc:
            logger.error(f"前台鼠标移动失败: {exc}")
            return False

    def safe_send_background_message(self, hwnd, message, wparam, client_x, client_y):
        try:
            import win32api
            import win32gui

            final_x, final_y = self.validate_client_coordinates(hwnd, client_x, client_y)
            l_param = win32api.MAKELONG(final_x, final_y)
            result = win32gui.PostMessage(hwnd, message, wparam, l_param)
            return result != 0
        except Exception as exc:
            logger.error(f"后台消息发送失败: {exc}")
            return False

    def safe_move_to(self, x, y, duration=0, hwnd=None):
        try:
            import pyautogui

            pyautogui.FAILSAFE = False
            pyautogui.PAUSE = 0
            v_left, v_top, v_width, v_height = self.get_virtual_screen_bounds()
            final_x = max(v_left, min(x, v_left + v_width - 1))
            final_y = max(v_top, min(y, v_top + v_height - 1))
            pyautogui.moveTo(final_x, final_y, duration=duration)
            return True
        except Exception as exc:
            logger.error(f"安全鼠标移动失败: {exc}")
            return False


mouse_move_fixer = MouseMoveFixer()
