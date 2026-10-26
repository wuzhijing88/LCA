"""
普通窗口输入模拟模块
针对普通应用程序窗口的键盘鼠标模拟
"""

import ctypes
import math
import time
from functools import wraps
import win32gui
import win32con
import win32api
from utils.window.enhanced_child_window_finder import (
    resolve_background_mouse_targets, resolve_background_key_targets,
)
from utils.window.enhanced_window_activator import get_window_activator
from .mode_utils import get_foreground_driver_backends, get_ibinputsimulator_config
from typing import Optional, List, Any, Tuple
from .base import BaseInputSimulator, ElementNotFoundError
from .drag_path import prepare_drag_path, iter_drag_samples
from utils.window.hwnd_utils import as_hwnd
from utils.input.input_timing import (
    DEFAULT_CLICK_HOLD_SECONDS,
    DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
    DEFAULT_KEY_HOLD_SECONDS,
)
from utils.input.key_repeat import hold_with_system_repeat
from utils.precise_sleep import precise_sleep as _shared_precise_sleep
from utils.input.uiautomation_runtime import import_uiautomation


def _precise_sleep(duration: float) -> None:
    _shared_precise_sleep(duration)


_DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS = DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS
_FOREGROUND_DRAG_MIN_DURATION_SECONDS = 0.1
_FOREGROUND_DRAG_MIN_SLEEP_SECONDS = 0.05
_FOREGROUND_CLICK_CONFIRM_TIMEOUT_MS = 200
_BACKGROUND_MESSAGE_CONFIRM_TIMEOUT_MS = 200
_FOREGROUND_DOUBLE_CLICK_THRESHOLD_RATIO = 0.8


def _get_system_double_click_time_seconds() -> float:
    """读取 Windows 双击时间，读取失败时终止双击。"""
    milliseconds = int(ctypes.windll.user32.GetDoubleClickTime())
    if milliseconds <= 0:
        raise RuntimeError("无法读取系统双击时间")
    return milliseconds / 1000.0


def _clamp_foreground_double_click_interval(interval: float) -> float:
    """给真实前台输入留出调度余量，避免第二击越过系统双击阈值。"""
    safe_interval = max(0.0, float(interval or 0.0))
    system_threshold = _get_system_double_click_time_seconds()
    safe_upper_bound = max(0.001, system_threshold * _FOREGROUND_DOUBLE_CLICK_THRESHOLD_RATIO)
    return min(safe_interval, safe_upper_bound)


_MOUSE_BUTTON_MESSAGES = {
    "left": (win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP, win32con.WM_LBUTTONDBLCLK, win32con.MK_LBUTTON),
    "right": (win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONUP, win32con.WM_RBUTTONDBLCLK, win32con.MK_RBUTTON),
    "middle": (win32con.WM_MBUTTONDOWN, win32con.WM_MBUTTONUP, win32con.WM_MBUTTONDBLCLK, win32con.MK_MBUTTON),
}
_MOUSE_MESSAGE_BUTTONS = {
    message: (button, up, message == up)
    for button, (down, up, double, _) in _MOUSE_BUTTON_MESSAGES.items()
    for message in (down, up, double)
}


def _mouse_button_messages(button):
    if button not in _MOUSE_BUTTON_MESSAGES:
        raise ValueError(f"不支持的鼠标按钮：{button!r}")
    return _MOUSE_BUTTON_MESSAGES[button]


def _background_action(method):
    """一次外层动作负责清理；按住跨动作保留，清理失败禁止继续输入。"""
    @wraps(method)
    def run(self, *args, **kwargs):
        if self._closed:
            return False
        if self.use_foreground:
            return method(self, *args, **kwargs)
        if not self._background_action_depth and self._background_cleanup_required:
            try:
                self._cleanup_background_state()
            except Exception:
                self.logger.error("上次后台输入尚未释放", exc_info=True)
                return False
        self._background_action_depth += 1
        succeeded = False
        try:
            if self._physical_mouse_block is not None:
                self._physical_mouse_block.check()
            succeeded = method(self, *args, **kwargs)
        finally:
            self._background_action_depth -= 1
            if not self._background_action_depth:
                try:
                    if not succeeded:
                        self._cleanup_background_state()
                    elif not self._pending_mouse_releases and not self._pending_key_releases:
                        self._deactivate_background_targets()
                except Exception:
                    self._background_cleanup_required = True
                    self.logger.error("后台输入状态未能完整释放", exc_info=True)
                    succeeded = False
        return succeeded
    return run


class StandardWindowInputSimulator(BaseInputSimulator):
    """原生窗口输入，后台一、二共用目标解析与输入生命周期。"""
    supports_atomic_click_hold = True

    def __init__(
        self,
        hwnd: int,
        use_foreground: bool = False,
        foreground_driver: str = "interception",
        enable_activation_sequence: bool = False,
        enable_message_guard: bool = True,
        execution_mode: str = "background_sendmessage",
        background_hierarchy_broadcast: bool = False,
        physical_mouse_block_targets: tuple = (),
    ):
        """
        初始化普通窗口输入模拟器

        Args:
            hwnd: 目标窗口句柄
            use_foreground: 是否使用前台模式（驱动级）
            enable_activation_sequence: 是否启用完整激活消息序列（仅后台模式）
            enable_message_guard: 是否探测接收线程响应（后台消息 + 前台点击收敛）
            background_hierarchy_broadcast: 鼠标向命中层级广播，键盘只发送最终接收控件
        """
        self.use_foreground = use_foreground
        self.foreground_driver = foreground_driver
        self.driver = None
        # 记录最近一次成功文本输入的控件句柄（用于后续回车等按键发送）
        self._last_input_control_hwnd = None
        self._virtual_cursor = None
        self._pending_mouse_releases = {}
        self._pending_key_releases = {}
        self._fake_active_targets = set()
        self._background_action_depth = 0
        self._background_cleanup_required = False
        self._queued_background_input = False
        self._closed = False
        self.window_activator = None
        self._physical_mouse_block = None

        # 增强功能开关
        self.enable_activation_sequence = enable_activation_sequence
        self.enable_message_guard = enable_message_guard
        self.execution_mode = (execution_mode or "").strip().lower()
        self.use_async_message = (not use_foreground) and self.execution_mode == "background_postmessage"

        self.background_hierarchy_broadcast = (not use_foreground) and background_hierarchy_broadcast

        # 先建立空的资源状态，基类验证失败后仍可安全关闭。
        super().__init__(hwnd)
        if not use_foreground and self.execution_mode not in {"background_sendmessage", "background_postmessage"}:
            raise ValueError(f"不支持的后台执行模式：{execution_mode!r}")

        # 初始化增强模块
        if not use_foreground:
            if self.enable_activation_sequence:
                self.window_activator = get_window_activator()
            if physical_mouse_block_targets:
                from utils.input.physical_mouse_block import physical_mouse_block_manager

                self._physical_mouse_block = physical_mouse_block_manager.acquire(physical_mouse_block_targets)
        
    def _ensure_driver(self) -> bool:
        """按现行配置从输入管理器取得前台驱动。"""
        if not self.use_foreground:
            return False
        try:
            from utils.input.foreground_input_manager import get_foreground_input_manager

            fg_manager = get_foreground_input_manager()
            if self.foreground_driver == "pyautogui":
                fg_manager.set_forced_mode("pyautogui")
                if fg_manager.initialize():
                    self.driver = fg_manager.get_active_driver()
                    return self.driver is not None
                self.driver = None
                return False

            mouse_backend, keyboard_backend = get_foreground_driver_backends(self.execution_mode)
            ib_driver, ib_driver_arg, ib_ahk_path, ib_ahk_dir = get_ibinputsimulator_config()
            if 'ibinputsimulator' in (mouse_backend, keyboard_backend):
                fg_manager.set_ibinputsimulator_driver(ib_driver, ib_driver_arg, ib_ahk_path, ib_ahk_dir)

            # Re-apply the selected modes on every use.  set_forced_modes() is
            # a no-op when the configuration is unchanged, but it tears down
            # the old global drivers when the user switched backends.  This is
            # essential for cached StandardWindowInputSimulator instances:
            # their previous self.driver may point at a driver already closed
            # by the manager.
            fg_manager.set_forced_modes(mouse_backend, keyboard_backend)

            if fg_manager.initialize():
                self.driver = fg_manager.get_active_driver()
                return self.driver is not None

            self.driver = None
            return False
        except Exception as e:
            self.logger.error(f"前台驱动初始化失败：{e}")
            self.driver = None
            return False

    def _get_foreground_mouse_backend(self) -> str:
        mouse_backend, _ = get_foreground_driver_backends(self.execution_mode)
        return str(mouse_backend).strip().lower()

    def _get_virtual_screen_bounds(self) -> Tuple[int, int, int, int]:
        """获取虚拟桌面边界，兼容负坐标多屏布局。"""
        left = int(win32api.GetSystemMetrics(76))   # SM_XVIRTUALSCREEN
        top = int(win32api.GetSystemMetrics(77))    # SM_YVIRTUALSCREEN
        width = int(win32api.GetSystemMetrics(78))  # SM_CXVIRTUALSCREEN
        height = int(win32api.GetSystemMetrics(79)) # SM_CYVIRTUALSCREEN

        if width <= 0 or height <= 0:
            raise RuntimeError("virtual screen size invalid")

        return left, top, left + width - 1, top + height - 1

    def close(self) -> None:
        """关闭后禁止再次输入；释放失败保留记录，允许管理器重试关闭。"""
        self._closed = True
        try:
            self._cleanup_background_state()
        finally:
            if self._physical_mouse_block is not None:
                self._physical_mouse_block.close()
                self._physical_mouse_block = None
        self.driver = None
        self._last_input_control_hwnd = None
        self._virtual_cursor = None
        self.window_activator = None

    def _cleanup_background_state(self) -> None:
        self._background_cleanup_required = True
        try:
            self._release_pending_inputs()
        finally:
            self._deactivate_background_targets()
        self._background_cleanup_required = False

    def _release_receivers(self, receivers, wparam=0) -> bool:
        """显式松开、失败回收和关闭共用发送记录；销毁的窗口直接注销。"""
        for receiver, (message, lparam) in list(receivers.items()):
            try:
                if self._is_window_alive(receiver):
                    self._send_message(receiver, message, wparam, lparam)
                    if self._queued_background_input:
                        if not self._confirm_background_message_delivery([receiver]):
                            raise RuntimeError("接收窗口无响应")
                receivers.pop(receiver)
            except Exception as exc:
                self.logger.error("后台输入释放失败：窗口 %s，%s", receiver, exc)
        return not receivers

    def _release_pending_inputs(self) -> None:
        mouse = self._pending_mouse_releases
        keys = self._pending_key_releases
        for button, receivers in list(mouse.items()):
            if self._release_receivers(receivers, self._mouse_button_flags(exclude=button)):
                mouse.pop(button)
        for key, receivers in list(keys.items()):
            if self._release_receivers(receivers, key):
                keys.pop(key)
        if mouse or keys:
            raise RuntimeError("输入实例未能完整释放按键或鼠标状态")

    def _deactivate_background_targets(self) -> None:
        activator = self.window_activator
        targets = self._fake_active_targets
        if activator is not None:
            use_post = self.use_async_message or self._queued_background_input
            for target in list(targets):
                if activator.deactivate(self.hwnd, target, use_post_message=use_post):
                    targets.remove(target)
        if targets:
            raise RuntimeError("输入实例未能完整释放后台假激活状态")
        self._queued_background_input = False

    _QUEUE_INPUT_MESSAGES = {
        win32con.WM_KEYDOWN,
        win32con.WM_KEYUP,
        win32con.WM_SYSKEYDOWN,
        win32con.WM_SYSKEYUP,
        win32con.WM_CHAR,
    }

    def _send_message(self, hwnd: int, msg: int, wparam: int, lparam: int):
        # 记事本等标准窗只处理消息队列里的按键：SendMessage(KEYDOWN) 不会走 TranslateMessage，也就没有字。
        # 按键/字符一律进队列；同一按住期间的后续输入保持队列顺序。
        if (not self.use_foreground) and (msg in self._QUEUE_INPUT_MESSAGES or self.use_async_message or self._queued_background_input):
            self._queued_background_input = True
            return win32gui.PostMessage(hwnd, msg, wparam, lparam)
        if not self.use_foreground:
            return win32gui.SendMessageTimeout(
                hwnd, msg, wparam, lparam, win32con.SMTO_ABORTIFHUNG, _BACKGROUND_MESSAGE_CONFIRM_TIMEOUT_MS,
            )
        return win32gui.SendMessage(hwnd, msg, wparam, lparam)

    def _confirm_click_delivery(self, screen_x: int, screen_y: int) -> bool:
        """只确认实际命中窗口，不能用另一个窗口的响应代替。"""
        try:
            receiver = win32gui.WindowFromPoint((int(screen_x), int(screen_y)))
            if not receiver or not win32gui.IsWindow(receiver) or not self._is_descendant(self.hwnd, receiver):
                return False
            win32gui.SendMessageTimeout(receiver, win32con.WM_NULL, 0, 0,
                                        win32con.SMTO_ABORTIFHUNG, _FOREGROUND_CLICK_CONFIRM_TIMEOUT_MS)
            return True
        except Exception:
            return False

    def _collect_message_guard_targets(self, hwnds=None) -> list[int]:
        """确认调用方给出的实际接收窗口，不追加替代窗口。"""
        targets = []
        for value in ([self.hwnd] if hwnds is None else hwnds):
            hwnd = int(value)
            if not hwnd or not win32gui.IsWindow(hwnd):
                raise RuntimeError("消息确认接收窗口无效")
            if hwnd not in targets:
                targets.append(hwnd)
        return targets

    def _confirm_background_message_delivery(
        self,
        hwnds=None,
        timeout_ms: int = _BACKGROUND_MESSAGE_CONFIRM_TIMEOUT_MS,
    ) -> bool:
        """探测接收线程响应；WM_NULL 不代表已投递输入已处理完毕。"""
        if self.use_foreground or (not self.enable_message_guard):
            return True

        try:
            targets = self._collect_message_guard_targets(hwnds)
            if not targets:
                return False
            for hwnd in targets:
                win32gui.SendMessageTimeout(hwnd, win32con.WM_NULL, 0, 0,
                                            win32con.SMTO_ABORTIFHUNG, max(1, int(timeout_ms)))
            return True
        except Exception:
            return False

    def _make_lparam(self, scan_code: int, extended: bool, repeat: int, prev_down: bool, transition: bool) -> int:
        """Generate lparam for key messages."""
        lparam = repeat & 0xFFFF
        lparam |= (scan_code & 0xFF) << 16
        if extended:
            lparam |= 1 << 24
        if prev_down:
            lparam |= 1 << 30
        if transition:
            lparam |= 1 << 31
        return lparam

    def _make_mouse_lparam(self, x: int, y: int) -> int:
        return win32api.MAKELONG(x & 0xFFFF, y & 0xFFFF)

    def _vk_to_driver_key(self, vk_code) -> str:
        """将虚拟键码转换为前台驱动可识别的按键字符串。"""
        if isinstance(vk_code, str):
            text = vk_code.strip()
            return text.lower() if text else ""

        try:
            vk = int(vk_code)
        except Exception:
            return ""

        key_map = {
            win32con.VK_SHIFT: "shift",
            win32con.VK_LSHIFT: "lshift",
            win32con.VK_RSHIFT: "rshift",
            win32con.VK_CONTROL: "ctrl",
            win32con.VK_LCONTROL: "lctrl",
            win32con.VK_RCONTROL: "rctrl",
            win32con.VK_MENU: "alt",
            win32con.VK_LMENU: "lalt",
            win32con.VK_RMENU: "ralt",
            win32con.VK_RETURN: "enter",
            win32con.VK_SPACE: "space",
            win32con.VK_TAB: "tab",
            win32con.VK_BACK: "backspace",
            win32con.VK_ESCAPE: "esc",
            win32con.VK_DELETE: "delete",
            win32con.VK_INSERT: "insert",
            win32con.VK_HOME: "home",
            win32con.VK_END: "end",
            win32con.VK_PRIOR: "pageup",
            win32con.VK_NEXT: "pagedown",
            win32con.VK_UP: "up",
            win32con.VK_DOWN: "down",
            win32con.VK_LEFT: "left",
            win32con.VK_RIGHT: "right",
        }

        if vk in key_map:
            return key_map[vk]

        if ord('A') <= vk <= ord('Z'):
            return chr(vk).lower()
        if ord('0') <= vk <= ord('9'):
            return chr(vk)

        if win32con.VK_NUMPAD0 <= vk <= win32con.VK_NUMPAD9:
            return f"numpad{vk - win32con.VK_NUMPAD0}"
        if win32con.VK_F1 <= vk <= win32con.VK_F12:
            return f"f{vk - win32con.VK_F1 + 1}"

        return ""

    def _is_descendant(self, root_hwnd: int, child_hwnd: int) -> bool:
        try:
            return root_hwnd == child_hwnd or bool(win32gui.IsChild(root_hwnd, child_hwnd))
        except Exception:
            return False

    def _resolve_mouse_message_targets(self, client_x: int, client_y: int):
        if not self.background_hierarchy_broadcast:
            return resolve_background_mouse_targets(self.hwnd, client_x, client_y, False)
        if self._is_desktop_target():
            return self._resolve_desktop_icon_layer_targets(client_x, client_y)
        return resolve_background_mouse_targets(self.hwnd, client_x, client_y, True)

    @staticmethod
    def _screen_to_window_client(hwnd: int, screen_x: int, screen_y: int):
        """鼠标消息的 lParam 是接收窗口的客户区坐标。

        必须用 ScreenToClient 换算：GetWindowRect 含边框/标题栏，顶层窗口（乃至带边框的子控件）
        用它减会整体偏掉一个边框。
        """
        try:
            client_x, client_y = win32gui.ScreenToClient(int(hwnd), (int(screen_x), int(screen_y)))
            return int(client_x), int(client_y)
        except Exception as exc:
            raise RuntimeError("鼠标坐标转换失败") from exc

    def _is_desktop_target(self) -> bool:
        try:
            from utils.window.window_identity import is_desktop_window

            return bool(is_desktop_window(self.hwnd))
        except Exception as exc:
            raise RuntimeError("无法确定目标是否为桌面") from exc

    def _resolve_desktop_icon_layer_targets(self, client_x: int, client_y: int):
        """绑定「桌面」时把后台消息定向到图标层 (Progman → SHELLDLL_DefView → SysListView32)。

        桌面窗口的"子窗口"是所有顶层窗口，按点位向下找会落到任务栏、透明覆盖层或别的程序上；
        用户绑定桌面要操作的是桌面本身。图标层不可用时直接失败。
        """
        from utils.window.window_identity import find_desktop_icon_layer

        host, defview, listview = find_desktop_icon_layer()
        if not defview or not listview or not win32gui.IsWindow(int(listview)):
            raise RuntimeError("桌面图标层不可用")
        screen_x, screen_y = win32gui.ClientToScreen(self.hwnd, (int(client_x), int(client_y)))
        chain = [self.hwnd]
        for hwnd in (host, defview, listview):
            if hwnd and hwnd not in chain:
                try:
                    if win32gui.IsWindow(hwnd):
                        chain.append(int(hwnd))
                except Exception:
                    continue
        coords = {self.hwnd: (int(client_x), int(client_y))}
        for hwnd in chain[1:]:
            coords[hwnd] = self._screen_to_window_client(hwnd, screen_x, screen_y)
        if not getattr(self, "_desktop_icon_layer_logged", False):
            self._desktop_icon_layer_logged = True
            self.logger.info(
                "目标是桌面，后台消息定向到图标层: host=0x%X defview=0x%X listview=0x%X",
                int(host or 0), int(defview or 0), int(listview or 0),
            )
        return chain, coords

    def get_virtual_cursor(self) -> Tuple[int, int]:
        if self._virtual_cursor:
            return int(self._virtual_cursor[0]), int(self._virtual_cursor[1])
        raise RuntimeError("后台鼠标位置未知，请先执行带坐标的鼠标动作")

    def _remember_cursor(self, x: int, y: int) -> None:
        self._virtual_cursor = (int(x), int(y))

    def _remember_target_control(self, window_chain) -> None:
        if not window_chain:
            raise RuntimeError("后台输入接收窗口未知")
        receiver = int(window_chain[-1])
        if not receiver or not win32gui.IsWindow(receiver):
            raise RuntimeError("后台输入接收窗口已失效")
        self._last_input_control_hwnd = receiver

    def _background_key_targets(self):
        if not self.background_hierarchy_broadcast:
            return resolve_background_key_targets(self.hwnd, False)
        held_targets = list(dict.fromkeys(
            hwnd for receivers in self._pending_key_releases.values() for hwnd in receivers
        ))
        if held_targets:
            if len(held_targets) != 1:
                raise RuntimeError("后台按键接收控件状态不一致")
            return held_targets
        if self._virtual_cursor is not None:
            chain, _ = self._resolve_mouse_message_targets(*self._virtual_cursor)
            return [chain[-1]]
        return resolve_background_key_targets(self.hwnd, True, self._last_input_control_hwnd)

    def _mouse_button_flags(self, exclude=None) -> int:
        flags = sum(_MOUSE_BUTTON_MESSAGES[button][3] for button in self._pending_mouse_releases if button != exclude)
        if self._pending_key_releases.keys() & {win32con.VK_CONTROL, win32con.VK_LCONTROL, win32con.VK_RCONTROL}:
            flags |= win32con.MK_CONTROL
        if self._pending_key_releases.keys() & {win32con.VK_SHIFT, win32con.VK_LSHIFT, win32con.VK_RSHIFT}:
            flags |= win32con.MK_SHIFT
        return flags

    def _mouse_action_targets(self, x, y, receivers=None):
        if receivers is None:
            receivers = list(dict.fromkeys(
                hwnd for pending in self._pending_mouse_releases.values() for hwnd in pending
            ))
        if not receivers:
            return self._resolve_mouse_message_targets(x, y)
        if not self.background_hierarchy_broadcast:
            return [self.hwnd], {self.hwnd: (x, y)}
        screen = win32gui.ClientToScreen(self.hwnd, (x, y))
        # 按下记录按接收层到主窗口排列；解析结果统一还原为主窗口到接收层。
        return list(reversed(receivers)), {hwnd: self._screen_to_window_client(hwnd, *screen) for hwnd in receivers}

    def _is_window_alive(self, hwnd) -> bool:
        return bool(hwnd) and bool(win32gui.IsWindow(int(hwnd)))

    def _activate_background_control(self, control_hwnd: int, *, for_mouse=False) -> None:
        if self.use_foreground or not self.enable_activation_sequence:
            return
        if self.window_activator is None:
            raise RuntimeError("后台假激活器不可用")
        target = int(control_hwnd)
        if target in self._fake_active_targets:
            return
        for previous in list(self._fake_active_targets - {target}):
            if not self.window_activator.deactivate(
                self.hwnd, previous,
                use_post_message=self.use_async_message or self._queued_background_input,
            ):
                raise RuntimeError("上一个控件的后台假激活未解除")
            self._fake_active_targets.remove(previous)
        self._fake_active_targets.add(target)
        if not for_mouse:
            activated = self.window_activator.activate_for_keyboard(
                self.hwnd, target, use_post_message=self.use_async_message or self._queued_background_input,
            )
        else:
            activated = self.window_activator.activate_for_click(
                self.hwnd, target,
                use_post_message=self.use_async_message or self._queued_background_input,
            )
        if not activated:
            raise RuntimeError("后台假激活失败")

    def _send_mouse_message_to_chain(self, window_chain, window_coords, msg: int, wparam: int) -> bool:
        """接收层优先广播，防止父层消耗同位置移动；松开沿用按下顺序。"""
        targets = list(dict.fromkeys(reversed(window_chain))) if self.background_hierarchy_broadcast else [self.hwnd]
        if not targets or any(not self._is_window_alive(hwnd) or hwnd not in window_coords for hwnd in targets):
            return False
        info = _MOUSE_MESSAGE_BUTTONS.get(msg)
        if info is not None:
            button, up, releasing = info
            pending = self._pending_mouse_releases.setdefault(button, {})
            if releasing:
                receivers = list(pending) or targets
                for hwnd in receivers:
                    if hwnd in window_coords:
                        pending[hwnd] = (up, self._make_mouse_lparam(*window_coords[hwnd]))
                released = self._release_receivers(pending, wparam)
                if released:
                    self._pending_mouse_releases.pop(button)
                return released
        delivered = True
        for hwnd in targets:
            lparam = self._make_mouse_lparam(*window_coords[hwnd])
            if info is not None:
                pending[hwnd] = (up, lparam)
            elif msg == win32con.WM_MOUSEMOVE:
                for held in self._pending_mouse_releases.values():
                    if hwnd in held:
                        held[hwnd] = (held[hwnd][0], lparam)
            try:
                self._send_message(hwnd, msg, wparam, lparam)
            except Exception:
                delivered = False
        return delivered

    @_background_action
    def send_key_to_control(self, control_hwnd: int, vk_code: int, scan_code: int = 0, extended: bool = False) -> bool:
        """向指定控件发送按键"""
        try:
            if self.background_hierarchy_broadcast and not control_hwnd:
                return False
            targets = resolve_background_key_targets(self.hwnd, self.background_hierarchy_broadcast, control_hwnd)
            try:
                if not self._press_background_key(targets, vk_code, scan_code, extended):
                    return False
                _precise_sleep(0.01)
            finally:
                released = self.send_key_up(vk_code, scan_code, extended)
            return released
        except Exception:
            return False

    @_background_action
    def move_mouse(self, x: int, y: int) -> bool:
        try:
            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                return self.driver.move_mouse(int(x), int(y), absolute=True)
            client_x, client_y = int(x), int(y)
            window_chain, window_coords = self._mouse_action_targets(client_x, client_y)
            self._activate_background_control(window_chain[-1], for_mouse=True)
            wparam = self._mouse_button_flags()
            if not self._send_mouse_message_to_chain(window_chain, window_coords, win32con.WM_MOUSEMOVE, wparam):
                return False
            self._remember_cursor(client_x, client_y)
            self._remember_target_control(window_chain)
            return True
        except Exception:
            return False

    @_background_action
    def mouse_down(self, x: int, y: int, button: str = 'left') -> bool:
        try:
            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                return self.driver.mouse_down(int(x), int(y), button=button)
            client_x, client_y = int(x), int(y)
            msg, _, _, mask = _mouse_button_messages(button)
            window_chain, window_coords = self._mouse_action_targets(client_x, client_y)
            self._activate_background_control(window_chain[-1], for_mouse=True)
            wparam = self._mouse_button_flags() | mask
            if not self._send_mouse_message_to_chain(window_chain, window_coords, msg, wparam):
                return False
            self._remember_cursor(client_x, client_y)
            self._remember_target_control(window_chain)
            return True
        except Exception:
            return False

    @_background_action
    def mouse_up(self, x: int, y: int, button: str = 'left') -> bool:
        try:
            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                return self.driver.mouse_up(int(x), int(y), button=button)
            client_x, client_y = int(x), int(y)
            _, msg, _, _ = _mouse_button_messages(button)
            pending = self._pending_mouse_releases.get(button)
            window_chain, window_coords = self._mouse_action_targets(
                client_x, client_y, list(pending) if pending else None,
            )
            if not self._send_mouse_message_to_chain(
                window_chain, window_coords, msg, self._mouse_button_flags(exclude=button),
            ):
                return False
            self._remember_cursor(client_x, client_y)
            self._remember_target_control(window_chain)
            return True
        except Exception:
            return False

    @_background_action
    def double_click(
        self,
        x: int,
        y: int,
        button: str = 'left',
        interval: Optional[float] = None,
        hold_duration: Optional[float] = None,
    ) -> bool:
        """真正的双击。

        后台消息模式下两次单击永远不会被系统合成 WM_xBUTTONDBLCLK，必须自己发完整序列
        DOWN → UP → DBLCLK → UP；插件走大漠 LeftDoubleClick；前台由驱动打两次真实点击让系统合成。
        """
        safe_interval = _DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS if interval is None else float(interval)
        safe_hold = DEFAULT_CLICK_HOLD_SECONDS if hold_duration is None else float(hold_duration)
        if not math.isfinite(safe_interval) or not math.isfinite(safe_hold) or safe_interval < 0 or safe_hold < 0:
            raise ValueError("双击时间参数无效")
        try:
            if self.use_foreground:
                foreground_interval = _clamp_foreground_double_click_interval(safe_interval)
                if foreground_interval < safe_interval:
                    self.logger.debug(
                        "前台双击间隔 %.3fs 超过安全阈值，已收敛为 %.3fs",
                        safe_interval,
                        foreground_interval,
                    )
                return self._foreground_click(
                    int(x),
                    int(y),
                    button,
                    2,
                    foreground_interval,
                    safe_hold,
                    atomic_sequence=True,
                )
            return self._background_click(int(x), int(y), button, 2, safe_interval, safe_hold)
        except Exception:
            return False

    @_background_action
    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int,
             duration: float = 1.0, button: str = 'left') -> bool:
        try:
            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                mouse_backend = self._get_foreground_mouse_backend()
                if mouse_backend in ("pyautogui", "ibinputsimulator"):
                    return bool(
                        self.driver.drag_mouse(
                            int(start_x),
                            int(start_y),
                            int(end_x),
                            int(end_y),
                            button=button,
                            duration=duration,
                        )
                    )
                return self.drag_path(
                    [(int(start_x), int(start_y)), (int(end_x), int(end_y))],
                    duration=duration,
                    button=button,
                    timestamps=None,
                )
            return self.drag_path(
                [(start_x, start_y), (end_x, end_y)], duration=duration, button=button,
            )
        except Exception:
            return False

    def _foreground_move_segment_with_duration(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float,
    ) -> bool:
        try:
            sx = int(start_x)
            sy = int(start_y)
            ex = int(end_x)
            ey = int(end_y)
            safe_duration = max(0.0, float(duration or 0.0))
        except Exception:
            return False

        # 与前台二(PyAutoGUI)对齐:
        # duration <= 0.1 视为瞬移；否则每步最小睡眠 0.05s（约20FPS上限）
        if safe_duration <= _FOREGROUND_DRAG_MIN_DURATION_SECONDS:
            return bool(self.driver.move_mouse(ex, ey, absolute=True))

        total_steps = max(1, int(safe_duration / _FOREGROUND_DRAG_MIN_SLEEP_SECONDS))
        step_sleep = safe_duration / total_steps

        for step in range(1, total_steps + 1):
            progress = step / total_steps
            current_x = int(sx + (ex - sx) * progress)
            current_y = int(sy + (ey - sy) * progress)
            if not bool(self.driver.move_mouse(current_x, current_y, absolute=True)):
                return False
            if step_sleep > 0:
                _precise_sleep(step_sleep)

        return True

    @_background_action
    def drag_path(self, path_points: list, duration: float = 1.0, button: str = 'left', timestamps: list = None) -> bool:
        """沿路径拖拽；后台共用按下、移动、松开及开关控制。"""
        try:
            normalized_points, segment_durations = prepare_drag_path(path_points, duration, timestamps)
            if button not in {"left", "right", "middle"}:
                raise ValueError("拖拽按钮无效")

            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                mouse_backend = self._get_foreground_mouse_backend()
                if mouse_backend in ("pyautogui", "ibinputsimulator"):
                    return bool(
                        self.driver.drag_path(
                            normalized_points,
                            duration,
                            button=button,
                            timestamps=timestamps,
                        )
                    )

                start_x, start_y = normalized_points[0]
                end_x, end_y = normalized_points[-1]

                if not bool(self.driver.move_mouse(start_x, start_y, absolute=True)):
                    return False
                if not bool(self.driver.mouse_down(start_x, start_y, button=button)):
                    return False

                try:
                    prev_x, prev_y = normalized_points[0]
                    for (x, y), segment_duration in zip(normalized_points[1:], segment_durations):
                        if not self._foreground_move_segment_with_duration(
                            prev_x, prev_y, x, y, segment_duration,
                        ):
                            return False
                        prev_x, prev_y = x, y
                finally:
                    released = bool(self.driver.mouse_up(end_x, end_y, button=button))
                return released

            start_x, start_y = normalized_points[0]
            end_x, end_y = normalized_points[-1]
            try:
                if not self.mouse_down(start_x, start_y, button=button):
                    return False
                for wait, point_x, point_y in iter_drag_samples(normalized_points, segment_durations):
                    if wait > 0:
                        _precise_sleep(wait)
                    if not self.move_mouse(point_x, point_y):
                        return False
            finally:
                released = bool(self.mouse_up(end_x, end_y, button=button))
            return released
        except Exception:
            return False

    @_background_action
    def scroll(self, x: int, y: int, delta: int) -> bool:
        try:
            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                direction = 'up' if delta > 0 else 'down'
                clicks = int(abs(delta))
                return self.driver.scroll_mouse(direction, clicks, x=int(x), y=int(y))

            client_x, client_y = int(x), int(y)
            if delta == 0:
                return True
            window_chain, window_coords = self._resolve_mouse_message_targets(client_x, client_y)
            self._activate_background_control(window_chain[-1], for_mouse=True)
            root_x, root_y = window_coords[self.hwnd]
            screen_x, screen_y = win32gui.ClientToScreen(self.hwnd, (int(root_x), int(root_y)))

            # 窗口可能按最近一次鼠标移动确定滚动区域；滚轮消息中的坐标不会更新悬停位置。
            button_flags = self._mouse_button_flags()
            if not self._send_mouse_message_to_chain(window_chain, window_coords, win32con.WM_MOUSEMOVE, button_flags):
                return False
            self._remember_cursor(client_x, client_y)

            wparam = (delta & 0xFFFF) << 16 | button_flags
            lparam = self._make_mouse_lparam(int(screen_x), int(screen_y))

            targets = window_chain
            for hwnd_to_send in targets:
                self._send_scroll_to_receiver(hwnd_to_send, delta, wparam, lparam)
            if not self._confirm_background_message_delivery(targets):
                return False
            return True
        except Exception:
            return False

    def _send_scroll_to_receiver(self, hwnd, delta, wparam, lparam):
        """标准控件使用其原生滚动接口，其余窗口接收 WM_MOUSEWHEEL。"""
        class_name = win32gui.GetClassName(hwnd)
        lines = (-1 if delta > 0 else 1) * max(1, abs(int(delta)) // 120)
        if class_name in {"Edit", "RICHEDIT50W", "RICHEDIT50A", "RichEdit20W", "RichEdit20A"}:
            self._send_message(hwnd, win32con.EM_LINESCROLL, 0, lines)
        elif class_name == "ListBox":
            direction = win32con.SB_LINEUP if lines < 0 else win32con.SB_LINEDOWN
            for _ in range(abs(lines)):
                self._send_message(hwnd, win32con.WM_VSCROLL, direction, 0)
        elif class_name == "SysListView32":
            self._send_message(hwnd, 0x1014, 0, 30 * lines)  # LVM_SCROLL
        else:
            self._send_message(hwnd, win32con.WM_MOUSEWHEEL, wparam, lparam)

    @_background_action
    def send_key_down(self, vk_code: int, scan_code: int = 0, extended: bool = False) -> bool:
        try:
            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                key_name = self._vk_to_driver_key(vk_code)
                if not key_name:
                    return False
                return bool(self.driver.key_down(key_name))

            return self._press_background_key(self._background_key_targets(), vk_code, scan_code, extended)
        except Exception:
            return False

    def _press_background_key(self, targets, vk_code, scan_code, extended) -> bool:
        if len(targets) != 1:
            raise RuntimeError("后台按键必须使用唯一的接收控件")
        if scan_code == 0:
            scan_code = win32api.MapVirtualKey(vk_code, 0)
        self._activate_background_control(targets[-1])
        pending = self._pending_key_releases.setdefault(vk_code, {})
        up = self._make_lparam(scan_code, extended, 1, True, True)
        for target in targets:
            down = self._make_lparam(scan_code, extended, 1, target in pending, False)
            pending[target] = (win32con.WM_KEYUP, up)
            self._send_message(target, win32con.WM_KEYDOWN, vk_code, down)
        return self._confirm_background_message_delivery(targets)

    @_background_action
    def send_key_repeat(self, vk_code: int, scan_code: int = 0, extended: bool = False) -> bool:
        """补发一次 WM_KEYDOWN（已按下位），模拟系统键盘连发。"""
        try:
            if scan_code == 0:
                scan_code = win32api.MapVirtualKey(vk_code, 0)
            lparam = self._make_lparam(scan_code, extended, 1, True, False)
            pending = self._pending_key_releases.get(vk_code)
            if not pending:
                return False
            window_chain = list(pending)
            for hwnd_to_send in window_chain:
                self._send_message(hwnd_to_send, win32con.WM_KEYDOWN, vk_code, lparam)
            if not self._confirm_background_message_delivery(window_chain):
                return False
            return True
        except Exception:
            return False

    @_background_action
    def send_key_up(self, vk_code: int, scan_code: int = 0, extended: bool = False) -> bool:
        try:
            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                key_name = self._vk_to_driver_key(vk_code)
                if not key_name:
                    return False
                return bool(self.driver.key_up(key_name))

            if scan_code == 0:
                scan_code = win32api.MapVirtualKey(vk_code, 0)
            lparam = self._make_lparam(scan_code, extended, 1, True, True)
            pending = self._pending_key_releases.get(vk_code)
            window_chain = list(pending) if pending else self._background_key_targets()
            receivers = pending if pending is not None else {
                hwnd: (win32con.WM_KEYUP, lparam) for hwnd in window_chain
            }
            released = self._release_receivers(receivers, vk_code)
            if pending is not None and not pending:
                self._pending_key_releases.pop(vk_code)
            return released and bool(window_chain)

        except Exception:
            return False

    @_background_action
    def send_key(self, vk_code: int, scan_code: int = 0, extended: bool = False) -> bool:
        try:
            try:
                pressed = self.send_key_down(vk_code, scan_code, extended)
            finally:
                released = self.send_key_up(vk_code, scan_code, extended)
            return pressed and released
        except Exception:
            return False

    @_background_action
    def send_key_hold(
        self,
        vk_code: int,
        duration: float = 0.0,
        scan_code: int = 0,
        extended: bool = False,
        enable_repeat: bool = True,
        repeat_interval: Optional[float] = None,
        stop_checker=None,
    ) -> bool:
        """按住指定时长；enable_repeat 为真时按间隔或系统键盘重复率补发。"""
        try:
            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                key_name = self._vk_to_driver_key(vk_code)
                if not key_name:
                    return False
                return hold_with_system_repeat(
                    down=lambda: bool(self.driver.key_down(key_name)),
                    up=lambda: bool(self.driver.key_up(key_name)),
                    repeat=lambda: bool(self.driver.key_up(key_name)) and bool(self.driver.key_down(key_name)),
                    duration=duration,
                    sleep=lambda seconds: _shared_precise_sleep(seconds, spin_threshold=0.05, coarse_slice=0.005),
                    enable_repeat=bool(enable_repeat),
                    repeat_interval=repeat_interval,
                    stop_checker=stop_checker,
                )

            return hold_with_system_repeat(
                down=lambda: bool(self.send_key_down(vk_code, scan_code, extended)),
                up=lambda: bool(self.send_key_up(vk_code, scan_code, extended)),
                repeat=lambda: bool(self.send_key_repeat(vk_code, scan_code, extended)),
                duration=duration,
                sleep=lambda seconds: _shared_precise_sleep(seconds, spin_threshold=0.05, coarse_slice=0.005),
                enable_repeat=bool(enable_repeat),
                repeat_interval=repeat_interval,
                stop_checker=stop_checker,
            )
        except InterruptedError:
            raise
        except Exception:
            return False

    @_background_action
    def send_key_combination(self, keys: list, hold_duration: float = DEFAULT_KEY_HOLD_SECONDS) -> bool:
        try:
            try:
                pressed = self.press_key_combination(keys)
                if pressed:
                    _precise_sleep(max(0.0, float(hold_duration)))
            finally:
                released = self.release_key_combination(keys)
            return pressed and released
        except Exception:
            return False

    @_background_action
    def press_key_combination(self, keys: list) -> bool:
        try:
            for key in keys:
                if not self.send_key_down(key):
                    return False
            return True
        except Exception:
            return False

    @_background_action
    def release_key_combination(self, keys: list) -> bool:
        try:
            released = True
            for key in reversed(keys):
                if not self.send_key_up(key):
                    released = False
            return released
        except Exception:
            return False

    @_background_action
    def send_text(self, text: str, stop_checker=None, delay: Optional[float] = None) -> bool:
        try:
            if stop_checker and stop_checker():
                raise InterruptedError("文字输入已停止")
            from utils.input.simulated_text import _code_units, send_simulated_text

            pause = 0.008 if delay is None else float(delay)
            if not math.isfinite(pause) or pause < 0:
                raise ValueError("文字输入间隔必须是大于等于零的有限数字")
            if self.use_foreground:
                return send_simulated_text(
                    self.hwnd, text, delay=pause, stop_checker=stop_checker, use_focus=True,
                )
            units = _code_units(text)
            if not units:
                return True
            if self.background_hierarchy_broadcast and self._is_desktop_target():
                raise ValueError("桌面无法后台输入文字，请绑定目标窗口或选择前台模式")
            targets = resolve_background_key_targets(
                self.hwnd, self.background_hierarchy_broadcast, self._last_input_control_hwnd,
            )
            self._activate_background_control(targets[-1])
            for index, unit in enumerate(units):
                if stop_checker and stop_checker():
                    raise InterruptedError("文字输入已停止")
                for receiver in targets:
                    if not self._is_window_alive(receiver):
                        return False
                    self._send_message(receiver, win32con.WM_CHAR, unit, 1)
                if pause > 0 and (delay is None or index + 1 < len(units)):
                    _precise_sleep(pause)
            if not self._confirm_background_message_delivery(targets):
                return False
            self._last_input_control_hwnd = targets[-1]
            return True
        except InterruptedError:
            raise
        except Exception:
            return False

    def _background_click(
        self,
        x: int,
        y: int,
        button: str,
        clicks: int,
        interval: float,
        duration: Optional[float] = None,
    ) -> bool:
        try:
            if self._pending_mouse_releases:
                return False
            client_x, client_y = int(x), int(y)
            safe_clicks = int(clicks)
            safe_interval = float(interval)
            safe_hold_duration = DEFAULT_CLICK_HOLD_SECONDS if duration is None else float(duration)
            if safe_clicks <= 0 or safe_clicks != float(clicks) or not math.isfinite(safe_interval) or not math.isfinite(safe_hold_duration) or safe_interval < 0 or safe_hold_duration < 0:
                raise ValueError("点击次数或时间参数无效")

            down_msg, up_msg, double_msg, wparam_down = _mouse_button_messages(button)
            held_flags = self._mouse_button_flags()
            wparam_down |= held_flags
            presses = (down_msg, double_msg) if safe_clicks == 2 else (down_msg,) * safe_clicks
            window_chain, window_coords = self._resolve_mouse_message_targets(client_x, client_y)
            self._activate_background_control(window_chain[-1], for_mouse=True)
            if self.enable_message_guard and not self._send_mouse_message_to_chain(
                window_chain, window_coords, win32con.WM_MOUSEMOVE, held_flags,
            ):
                return False
            for i, press_msg in enumerate(presses):
                if i > 0 and safe_interval > 0:
                    _precise_sleep(safe_interval)
                released = False
                try:
                    if not self._send_mouse_message_to_chain(window_chain, window_coords, press_msg, wparam_down):
                        return False
                    if safe_hold_duration > 0:
                        _precise_sleep(safe_hold_duration)
                finally:
                    released = self._send_mouse_message_to_chain(window_chain, window_coords, up_msg, held_flags)
                if not released:
                    return False
            self._remember_cursor(client_x, client_y)
            self._remember_target_control(window_chain)
            if self.enable_message_guard and not self._confirm_background_message_delivery(window_chain):
                self.logger.error("后台点击接收线程无响应或窗口已失效")
                return False
            return True
        except Exception:
            return False

    @_background_action
    def click(
        self,
        x: int,
        y: int,
        button: str = 'left',
        clicks: int = 1,
        interval: float = 0.1,
        duration: Optional[float] = None,
    ) -> bool:
        """鼠标点击"""
        try:
            if self.use_foreground:
                return self._foreground_click(x, y, button, clicks, interval, duration)
            else:
                return self._background_click(x, y, button, clicks, interval, duration)
        except Exception as e:
            self.logger.error(f"普通窗口点击失败: {e}")
            return False
    
    def _foreground_click(
        self,
        x: int,
        y: int,
        button: str,
        clicks: int,
        interval: float,
        duration: Optional[float] = None,
        *,
        atomic_sequence: bool = False,
    ) -> bool:
        """Foreground click helper."""
        try:
            if not self._ensure_driver():
                self.logger.error("前台驱动不可用")
                return False

            if not self._ensure_foreground_ready(timeout=0.15):
                front = ""
                try:
                    front = (win32gui.GetWindowText(win32gui.GetForegroundWindow()) or "").strip()
                except Exception:
                    front = ""
                if front:
                    self.logger.error(f"要点的窗口不在最前面（现在最前面是「{front}」），已取消点击")
                else:
                    self.logger.error("要点的窗口不在最前面，已取消点击")
                return False

            try:
                target_x = int(x)
                target_y = int(y)
            except Exception:
                self.logger.error(f"coords invalid: ({x}, {y})")
                return False

            try:
                v_left, v_top, v_right, v_bottom = self._get_virtual_screen_bounds()
            except Exception as e:
                self.logger.error(f"虚拟屏幕边界不可用：{e}")
                return False
            if target_x < v_left or target_y < v_top or target_x > v_right or target_y > v_bottom:
                self.logger.error(
                    f"coords out of virtual screen: ({target_x}, {target_y}), "
                    f"bounds: ({v_left}, {v_top})-({v_right}, {v_bottom})"
                )
                return False

            safe_clicks = int(clicks)
            safe_interval = float(interval)
            safe_duration = 0.0 if duration is None else float(duration)
            if safe_clicks <= 0 or safe_clicks != float(clicks) or not math.isfinite(safe_interval) or not math.isfinite(safe_duration) or safe_interval < 0 or safe_duration < 0:
                raise ValueError("点击次数或时间参数无效")

            if not hasattr(self.driver, "click_mouse"):
                self.logger.error("前台点击驱动不可用")
                return False

            # 前台点击前先强制落位一次，避免首击阶段被底层驱动"旧坐标"消费。
            try:
                if not bool(self.driver.move_mouse(target_x, target_y, absolute=True)):
                    return False
                _precise_sleep(0.006)
            except Exception:
                return False

            if atomic_sequence:
                click_ok = bool(
                    self.driver.click_mouse(
                        target_x,
                        target_y,
                        button=button,
                        clicks=safe_clicks,
                        interval=safe_interval,
                        duration=safe_duration,
                    )
                )
                if not click_ok:
                    return False
            else:
                for click_index in range(safe_clicks):
                    if click_index > 0 and safe_interval > 0:
                        _precise_sleep(safe_interval)
                    click_ok = bool(
                        self.driver.click_mouse(
                            target_x,
                            target_y,
                            button=button,
                            clicks=1,
                            interval=0.0,
                            duration=safe_duration,
                        )
                    )
                    if not click_ok:
                        return False
            if self.enable_message_guard:
                if not self._confirm_click_delivery(target_x, target_y):
                    self.logger.warning("点击发出去了，但没确认到结果")
                    return False
            return True
        except Exception as e:
            self.logger.debug(f"[前台点击] 执行失败：{e}")
            return False

    def _ensure_foreground_ready(self, timeout: float = 0.15) -> bool:
        """普通窗口须在前台才发真实点击；桌面层不检查。"""
        if not self.use_foreground:
            return True
        if not self.hwnd:
            return False

        try:
            if not win32gui.IsWindow(self.hwnd):
                return False
        except Exception:
            return False

        try:
            from utils.window.window_identity import is_desktop_window

            if is_desktop_window(self.hwnd):
                return True
        except Exception:
            pass

        try:
            if self._is_foreground_target_window(win32gui.GetForegroundWindow()):
                return True
        except Exception:
            pass

        from utils.window.virtual_desktop import skip_cross_desktop_activation

        if skip_cross_desktop_activation(self.hwnd, log_prefix="前台点击"):
            return False

        try:
            if win32gui.IsIconic(self.hwnd):
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
        except Exception:
            pass
        try:
            win32gui.BringWindowToTop(self.hwnd)
        except Exception:
            pass
        try:
            win32gui.SetActiveWindow(self.hwnd)
        except Exception:
            pass
        try:
            win32gui.SetForegroundWindow(self.hwnd)
        except Exception:
            pass

        deadline = time.perf_counter() + max(0.02, float(timeout))
        while time.perf_counter() <= deadline:
            try:
                if self._is_foreground_target_window(win32gui.GetForegroundWindow()):
                    return True
            except Exception:
                return False
            _precise_sleep(0.002)
        return False

    def _is_foreground_target_window(self, foreground_hwnd: int) -> bool:
        try:
            fg_hwnd = as_hwnd(foreground_hwnd)
            target_hwnd = as_hwnd(self.hwnd)
        except Exception:
            return False
        if fg_hwnd == 0 or target_hwnd == 0:
            return False
        if fg_hwnd == target_hwnd:
            return True
        try:
            fg_root = as_hwnd(win32gui.GetAncestor(fg_hwnd, win32con.GA_ROOT))
            target_root = as_hwnd(win32gui.GetAncestor(target_hwnd, win32con.GA_ROOT))
            if fg_root != 0 and target_root != 0 and fg_root == target_root:
                return True
        except Exception:
            return False
        return False

    # ========== UIAutomation 元素操作方法 ==========

    def _get_window_control(self):
        """
        获取窗口对应的UIAutomation控件对象

        Returns:
            uiautomation.Control 对象，失败返回 None
        """
        try:
            auto = import_uiautomation()
            return auto.ControlFromHandle(self.hwnd)
        except ImportError:
            self.logger.error("uiautomation 库未安装，请运行: pip install uiautomation")
            return None
        except Exception as e:
            self.logger.error(f"获取窗口控件失败: {e}")
            return None

    def _get_document_control(self, window_control):
        """
        获取浏览器的Document控件（网页内容区域）

        对于Chrome/Edge浏览器，需要先找到DocumentControl才能正确搜索网页元素

        Returns:
            DocumentControl 或 None
        """
        try:
            auto = import_uiautomation()

            # 尝试获取DocumentControl（网页内容区域）
            doc = window_control.DocumentControl(searchDepth=8)
            if doc and doc.Exists(maxSearchSeconds=1):
                self.logger.debug(f"[元素点击] 找到DocumentControl: {doc.Name}")
                return doc

            return None
        except Exception as e:
            self.logger.debug(f"[元素点击] 获取DocumentControl失败: {e}")
            return None

    def _build_search_conditions(
        self,
        name: str = None,
        automation_id: str = None,
        class_name: str = None,
        control_type: str = None,
        search_depth: int = 10,
        found_index: int = None
    ) -> dict:
        """
        构建UIAutomation搜索条件

        Args:
            name: 元素名称
            automation_id: 自动化ID
            class_name: 类名
            control_type: 控件类型字符串

        Returns:
            搜索条件字典
        """
        conditions = {'searchDepth': search_depth}

        if name is not None:
            conditions['Name'] = name
        if automation_id is not None:
            conditions['AutomationId'] = automation_id
        if class_name is not None:
            conditions['ClassName'] = class_name
        if found_index is not None:
            conditions['foundIndex'] = max(1, int(found_index) + 1)

        return conditions

    def _find_element_by_conditions(self, window_control, name, automation_id, class_name, control_type, search_depth, found_index=None):
        """使用UIAutomation原生搜索元素（快速）"""
        try:
            auto = import_uiautomation()
            conditions = self._build_search_conditions(name, automation_id, class_name, control_type, search_depth, found_index)

            # 使用具体的控件类搜索更快
            if control_type:
                control_class = self._get_control_class(control_type)
                return control_class(searchFromControl=window_control, **conditions)
            return window_control.Control(**conditions)
        except Exception:
            return None



    def _get_control_class(self, control_type: str):
        """只接受当前 UIAutomation 库提供的控件类，不替换未知类型。"""
        auto = import_uiautomation()
        control_class = getattr(auto, control_type)
        if not isinstance(control_class, type) or not issubclass(control_class, auto.Control):
            raise ValueError(f"不支持的控件类型：{control_type!r}")
        return control_class

    def click_element(
        self,
        name: str = None,
        automation_id: str = None,
        class_name: str = None,
        control_type: str = None,
        found_index: int = 0,
        search_depth: int = 10,
        timeout: float = 5.0,
        use_invoke: bool = True,
        strict_invoke: bool = False,
        button: str = 'left'
    ) -> bool:
        """
        点击UI元素（基于UIAutomation）

        通过控件属性定位元素并点击。

        Args:
            name: 元素名称（Name属性）
            automation_id: 自动化ID（AutomationId属性）
            class_name: 类名（ClassName属性）
            control_type: 控件类型（如 "ButtonControl", "EditControl"）
            found_index: 匹配到多个元素时选择第几个（从0开始）
            search_depth: 搜索深度
            timeout: 超时时间（秒）
            use_invoke: True使用Invoke模式（不移动鼠标），False使用坐标点击
            strict_invoke: True 时 Invoke/坐标不可用直接失败，不执行隐式 Click 回退
            button: 鼠标按钮 ('left', 'right', 'middle')

        Returns:
            bool: 操作是否成功

        Raises:
            ElementNotFoundError: 未找到指定元素
            TimeoutError: 查找元素超时
        """
        try:
            auto = import_uiautomation()

            self.logger.info(
                f"[元素点击] 开始查找元素: name={name}, automation_id={automation_id}, "
                f"class_name={class_name}, control_type={control_type}"
            )

            # 获取窗口控件
            window_control = self._get_window_control()
            if not window_control:
                raise ElementNotFoundError(f"无法获取窗口控件 (hwnd={self.hwnd})")

            # 设置超时
            auto.SetGlobalSearchTimeout(timeout)

            # 对于浏览器，先尝试获取DocumentControl
            search_root = window_control
            doc_control = self._get_document_control(window_control)
            if doc_control:
                search_root = doc_control
                self.logger.debug("[元素点击] 在DocumentControl中搜索")

            # 查找元素 - 使用多种策略
            element = None

            # 策略1: 在DocumentControl中精确搜索
            element = self._find_element_by_conditions(
                search_root, name, automation_id, class_name, control_type, search_depth, found_index
            )
            if not element or not element.Exists(maxSearchSeconds=timeout):
                raise ElementNotFoundError(
                    f"未找到元素: name={name}, automation_id={automation_id}, "
                    f"class_name={class_name}, control_type={control_type}"
                )

            self.logger.info(f"[元素点击] 找到元素: {element.Name}, 类型: {element.ControlTypeName}")

            # 执行点击
            if use_invoke:
                # 尝试使用 Invoke 模式（不移动鼠标）
                try:
                    invoke_pattern = element.GetInvokePattern()
                    if invoke_pattern:
                        invoke_pattern.Invoke()
                        self.logger.info("[元素点击] 使用 Invoke 模式点击成功")
                        return True
                    self.logger.error("元素不支持 Invoke 模式")
                    return False
                except Exception as invoke_error:
                    self.logger.error(f"元素 Invoke 点击失败：{invoke_error}")
                    return False

            # 使用坐标点击
            rect = element.BoundingRectangle
            if rect.width() > 0 and rect.height() > 0:
                # 计算中心点（屏幕坐标）
                center_x = rect.left + rect.width() // 2
                center_y = rect.top + rect.height() // 2

                self.logger.info(f"[元素点击] 使用坐标点击: ({center_x}, {center_y})")

                if self.use_foreground:
                    # 前台模式直接点击屏幕坐标
                    return self._foreground_click(center_x, center_y, button, 1, 0.1)
                else:
                    # 后台模式需要转换为客户区坐标
                    try:
                        client_x, client_y = win32gui.ScreenToClient(self.hwnd, (center_x, center_y))
                        return self.click(client_x, client_y, button, 1, 0.1)
                    except Exception as coord_error:
                        self.logger.error(f"[元素点击] 坐标转换失败: {coord_error}")
                        return False
            else:
                self.logger.error("元素边界无效，无法点击")
                return False

        except ImportError:
            raise NotImplementedError("uiautomation 库未安装，请运行: pip install uiautomation")
        except ElementNotFoundError:
            raise
        except TimeoutError:
            raise
        except Exception as e:
            self.logger.error(f"[元素点击] 失败: {e}", exc_info=True)
            return False

    def find_element(
        self,
        name: str = None,
        automation_id: str = None,
        class_name: str = None,
        control_type: str = None,
        search_depth: int = 10,
        timeout: float = 5.0
    ) -> Optional[Any]:
        """
        查找UI元素

        Args:
            name: 元素名称
            automation_id: 自动化ID
            class_name: 类名
            control_type: 控件类型
            search_depth: 搜索深度
            timeout: 超时时间（秒）

        Returns:
            找到的元素对象，未找到返回None
        """
        try:
            auto = import_uiautomation()

            window_control = self._get_window_control()
            if not window_control:
                return None

            auto.SetGlobalSearchTimeout(timeout)

            # 策略1: 条件搜索
            element = self._find_element_by_conditions(
                window_control, name, automation_id, class_name, control_type, search_depth, 0
            )
            if element and element.Exists(maxSearchSeconds=1):
                return element

            return None

        except ImportError:
            raise NotImplementedError("uiautomation 库未安装")
        except Exception as e:
            self.logger.error(f"[元素查找] 失败: {e}")
            return None

    def find_all_elements(
        self,
        name: str = None,
        automation_id: str = None,
        class_name: str = None,
        control_type: str = None,
        search_depth: int = 10,
        timeout: float = 5.0
    ) -> List[Any]:
        """
        查找所有匹配的UI元素

        Args:
            name: 元素名称
            automation_id: 自动化ID
            class_name: 类名
            control_type: 控件类型
            search_depth: 搜索深度
            timeout: 超时时间（秒）

        Returns:
            匹配的元素列表
        """
        try:
            auto = import_uiautomation()

            window_control = self._get_window_control()
            if not window_control:
                return []

            auto.SetGlobalSearchTimeout(timeout)

            # 获取所有子元素
            results = []

            def match_element(element) -> bool:
                """检查元素是否匹配条件"""
                try:
                    if name is not None and element.Name != name:
                        return False
                    if automation_id is not None and element.AutomationId != automation_id:
                        return False
                    if class_name is not None and element.ClassName != class_name:
                        return False
                    if control_type is not None:
                        if element.ControlTypeName != control_type:
                            return False
                    return True
                except Exception:
                    return False

            def search_children(parent, depth: int):
                """递归搜索子元素"""
                if depth > search_depth:
                    return

                try:
                    for child in parent.GetChildren():
                        if match_element(child):
                            results.append(child)
                        search_children(child, depth + 1)
                except Exception:
                    pass

            search_children(window_control, 0)

            self.logger.debug(f"[元素查找] 找到 {len(results)} 个匹配元素")
            return results

        except ImportError:
            raise NotImplementedError("uiautomation 库未安装")
        except Exception as e:
            self.logger.error(f"[元素查找] 失败: {e}")
            return []

    def get_element_text(
        self,
        name: str = None,
        automation_id: str = None,
        class_name: str = None,
        control_type: str = None,
        search_depth: int = 10,
        timeout: float = 5.0
    ) -> Optional[str]:
        """
        获取UI元素的文本内容

        Args:
            name: 元素名称
            automation_id: 自动化ID
            class_name: 类名
            control_type: 控件类型
            search_depth: 搜索深度
            timeout: 超时时间（秒）

        Returns:
            元素文本，未找到返回None
        """
        try:
            element = self.find_element(
                name, automation_id, class_name, control_type, search_depth, timeout
            )

            if element:
                # 尝试多种方式获取文本
                try:
                    # 优先使用 ValuePattern
                    value_pattern = element.GetValuePattern()
                    if value_pattern:
                        return value_pattern.Value
                except Exception:
                    pass

                try:
                    # 尝试 TextPattern
                    text_pattern = element.GetTextPattern()
                    if text_pattern:
                        return text_pattern.DocumentRange.GetText(-1)
                except Exception:
                    pass

                self.logger.error("元素不支持读取文本的模式")
                return None

            return None

        except Exception as e:
            self.logger.error(f"[获取元素文本] 失败: {e}")
            return None

    def set_element_value(
        self,
        value: str,
        name: str = None,
        automation_id: str = None,
        class_name: str = None,
        control_type: str = None,
        search_depth: int = 10,
        timeout: float = 5.0
    ) -> bool:
        """
        设置UI元素的值

        Args:
            value: 要设置的值
            name: 元素名称
            automation_id: 自动化ID
            class_name: 类名
            control_type: 控件类型
            search_depth: 搜索深度
            timeout: 超时时间（秒）

        Returns:
            是否成功
        """
        try:
            element = self.find_element(
                name, automation_id, class_name, control_type, search_depth, timeout
            )

            if element:
                try:
                    # 尝试使用 ValuePattern
                    value_pattern = element.GetValuePattern()
                    if value_pattern:
                        value_pattern.SetValue(value)
                        self.logger.info(f"[设置元素值] 使用 ValuePattern 设置成功: {value}")
                        return True
                except Exception as vp_error:
                    self.logger.debug(f"[设置元素值] ValuePattern 失败: {vp_error}")

                self.logger.error("元素不支持 ValuePattern 设置值")
                return False

            return False

        except Exception as e:
            self.logger.error(f"[设置元素值] 失败: {e}")
            return False
