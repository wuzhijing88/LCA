"""
普通窗口输入模拟模块
针对普通应用程序窗口的键盘鼠标模拟
"""

import time
import win32gui
import win32con
import win32api
from ..enhanced_child_window_finder import get_child_window_finder
from ..enhanced_window_activator import get_window_activator
from .mode_utils import get_foreground_driver_backends, get_ibinputsimulator_config
from typing import Optional, List, Any, Tuple
from .base import BaseInputSimulator, ElementNotFoundError
from utils.input_timing import (
    DEFAULT_CLICK_HOLD_SECONDS,
    DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
    DEFAULT_KEY_HOLD_SECONDS,
)
from utils.precise_sleep import precise_sleep as _shared_precise_sleep
from utils.uiautomation_runtime import import_uiautomation


def _precise_sleep(duration: float) -> None:
    _shared_precise_sleep(duration)


_DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS = DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS
_FOREGROUND_DRAG_MIN_DURATION_SECONDS = 0.1
_FOREGROUND_DRAG_MIN_SLEEP_SECONDS = 0.05
_FOREGROUND_CLICK_CONFIRM_TIMEOUT_MS = 200
_BACKGROUND_MESSAGE_CONFIRM_TIMEOUT_MS = 200


class StandardWindowInputSimulator(BaseInputSimulator):
    """普通窗口输入模拟器 (v2.0)"""
    supports_atomic_click_hold = True

    def __init__(
        self,
        hwnd: int,
        use_foreground: bool = False,
        foreground_driver: str = "interception",
        enable_deep_child_search: bool = True,
        enable_activation_sequence: bool = True,
        enable_message_guard: bool = True,
        execution_mode: str = "background"
    ):
        """
        初始化普通窗口输入模拟器

        Args:
            hwnd: 目标窗口句柄
            use_foreground: 是否使用前台模式（驱动级）
            enable_deep_child_search: 是否启用深度子控件查找（仅后台模式）
            enable_activation_sequence: 是否启用完整激活消息序列（仅后台模式）
            enable_message_guard: 是否启用消息送达保障（后台消息 + 前台点击收敛）
        """
        super().__init__(hwnd)
        self.use_foreground = use_foreground
        self.foreground_driver = foreground_driver
        self.driver = None
        self._ib_runtime_signature = None
        # 记录最近一次成功文本输入的控件句柄（用于后续回车等按键发送）
        self._last_input_control_hwnd = None

        # 增强功能开关
        self.enable_deep_child_search = enable_deep_child_search
        self.enable_activation_sequence = enable_activation_sequence
        self.enable_message_guard = enable_message_guard
        self.execution_mode = (execution_mode or "").strip().lower()
        self.use_async_message = (not use_foreground) and self.execution_mode == "background_postmessage"

        # 初始化增强模块
        if not use_foreground:
            if self.enable_deep_child_search:
                try:
                    self.child_finder = get_child_window_finder(enable_logging=False)
                except Exception:
                    pass
            if self.enable_activation_sequence:
                self.window_activator = get_window_activator(enable_logging=False)
        
    def _ensure_driver(self) -> bool:
        """Ensure foreground driver is initialized."""
        if self.driver:
            return True
        if not self.use_foreground:
            return False
        try:
            from utils.foreground_input_manager import get_foreground_input_manager

            fg_manager = get_foreground_input_manager()
            if self.foreground_driver == "pyautogui":
                fg_manager.set_forced_mode("pyautogui")
                if fg_manager.initialize():
                    self.driver = fg_manager.get_active_driver()
                    return self.driver is not None
                return False

            mouse_backend, keyboard_backend = get_foreground_driver_backends(self.execution_mode)
            ib_driver, ib_driver_arg, ib_ahk_path, ib_ahk_dir = get_ibinputsimulator_config()
            runtime_signature = (
                mouse_backend,
                keyboard_backend,
                ib_driver,
                ib_driver_arg,
                ib_ahk_path,
                ib_ahk_dir,
            )

            if self.driver and self._ib_runtime_signature == runtime_signature:
                active_driver = fg_manager.get_active_driver()
                if active_driver is self.driver:
                    return True

            if 'ibinputsimulator' in (mouse_backend, keyboard_backend):
                fg_manager.set_ibinputsimulator_driver(ib_driver, ib_driver_arg, ib_ahk_path, ib_ahk_dir)

            fg_manager.set_forced_modes(mouse_backend, keyboard_backend)

            for attempt in range(2):
                if fg_manager.initialize():
                    self.driver = fg_manager.get_active_driver()
                    self._ib_runtime_signature = runtime_signature
                    return self.driver is not None
                if attempt == 0:
                    _precise_sleep(0.25)

            self.driver = None
            self._ib_runtime_signature = None
            return False
        except Exception as e:
            self.logger.error(f"前台驱动初始化失败：{e}")
            self.driver = None
            self._ib_runtime_signature = None
            return False

    def _get_foreground_mouse_backend(self) -> str:
        """获取当前前台鼠标后端，优先读取 execution_mode 映射。"""
        try:
            mouse_backend, _ = get_foreground_driver_backends(self.execution_mode)
            backend = str(mouse_backend or "").strip().lower()
            if backend:
                return backend
        except Exception:
            pass
        return str(self.foreground_driver or "").strip().lower()

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
        """释放实例级引用，避免线程级缓存淘汰后对象长时间占用内存。"""
        try:
            self.driver = None
            self._ib_runtime_signature = None
            self._last_input_control_hwnd = None
            if hasattr(self, "child_finder"):
                self.child_finder = None
            if hasattr(self, "window_activator"):
                self.window_activator = None
        except Exception:
            pass

    _ASYNC_SAFE_MESSAGES = {
        win32con.WM_LBUTTONDOWN,
        win32con.WM_LBUTTONUP,
        win32con.WM_LBUTTONDBLCLK,
        win32con.WM_RBUTTONDOWN,
        win32con.WM_RBUTTONUP,
        win32con.WM_RBUTTONDBLCLK,
        win32con.WM_MBUTTONDOWN,
        win32con.WM_MBUTTONUP,
        win32con.WM_MBUTTONDBLCLK,
        win32con.WM_MOUSEMOVE,
        win32con.WM_MOUSEWHEEL,
        win32con.WM_KEYDOWN,
        win32con.WM_KEYUP,
        win32con.WM_SYSKEYDOWN,
        win32con.WM_SYSKEYUP,
        win32con.WM_CHAR,
    }

    def _send_message(self, hwnd: int, msg: int, wparam: int, lparam: int):
        if self.use_async_message and msg in self._ASYNC_SAFE_MESSAGES:
            return win32gui.PostMessage(hwnd, msg, wparam, lparam)
        return win32gui.SendMessage(hwnd, msg, wparam, lparam)

    def _confirm_click_delivery(self, screen_x: int, screen_y: int) -> bool:
        """
        确认点击消息已被目标窗口线程处理完成（前台模式）。
        通过 SendMessageTimeout(WM_NULL) 做线程消息队列同步，不使用固定sleep兜底。
        """
        send_timeout = getattr(win32gui, "SendMessageTimeout", None)
        if not callable(send_timeout):
            return False

        candidate_hwnds = []
        try:
            point_hwnd = win32gui.WindowFromPoint((int(screen_x), int(screen_y)))
            if point_hwnd and win32gui.IsWindow(point_hwnd):
                candidate_hwnds.append(int(point_hwnd))
                try:
                    root_hwnd = win32gui.GetAncestor(point_hwnd, win32con.GA_ROOT)
                    if root_hwnd and win32gui.IsWindow(root_hwnd):
                        candidate_hwnds.append(int(root_hwnd))
                except Exception:
                    pass
        except Exception:
            pass

        try:
            if self.hwnd and win32gui.IsWindow(self.hwnd):
                candidate_hwnds.append(int(self.hwnd))
        except Exception:
            pass

        dedup_hwnds = []
        seen = set()
        for hwnd in candidate_hwnds:
            if hwnd and hwnd not in seen:
                dedup_hwnds.append(hwnd)
                seen.add(hwnd)

        for hwnd in dedup_hwnds:
            try:
                send_timeout(
                    hwnd,
                    win32con.WM_NULL,
                    0,
                    0,
                    win32con.SMTO_ABORTIFHUNG,
                    _FOREGROUND_CLICK_CONFIRM_TIMEOUT_MS,
                )
                return True
            except Exception:
                continue

        return False

    def _collect_message_guard_targets(self, hwnds=None) -> list[int]:
        """Collect message-guard target hwnds."""
        candidates = []
        raw_hwnds = list(hwnds or [])
        if self.hwnd:
            raw_hwnds.append(self.hwnd)

        for raw_hwnd in raw_hwnds:
            try:
                hwnd = int(raw_hwnd or 0)
            except Exception:
                continue
            if not hwnd:
                continue
            try:
                if not win32gui.IsWindow(hwnd):
                    continue
            except Exception:
                continue

            candidates.append(hwnd)
            try:
                root_hwnd = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
                if root_hwnd and win32gui.IsWindow(root_hwnd):
                    candidates.append(int(root_hwnd))
            except Exception:
                pass

        dedup_hwnds = []
        seen = set()
        for hwnd in candidates:
            if hwnd and hwnd not in seen:
                dedup_hwnds.append(hwnd)
                seen.add(hwnd)
        return dedup_hwnds

    def _confirm_background_message_delivery(
        self,
        hwnds=None,
        timeout_ms: int = _BACKGROUND_MESSAGE_CONFIRM_TIMEOUT_MS,
    ) -> bool:
        """Confirm background message chain processed."""
        if self.use_foreground or (not self.enable_message_guard):
            return True

        send_timeout = getattr(win32gui, "SendMessageTimeout", None)
        if not callable(send_timeout):
            return not self.use_async_message

        targets = self._collect_message_guard_targets(hwnds)
        if not targets:
            return False

        delivered = False
        for hwnd in targets:
            try:
                send_timeout(
                    hwnd,
                    win32con.WM_NULL,
                    0,
                    0,
                    win32con.SMTO_ABORTIFHUNG,
                    max(1, int(timeout_ms)),
                )
                delivered = True
            except Exception:
                continue

        if delivered:
            return True
        return not self.use_async_message

    def _get_control_chain(self, control_hwnd: int):
        """获取控件及其父窗口链，用于将按键消息发送到合适的目标"""
        control_chain = [control_hwnd]
        try:
            parent_hwnd = control_hwnd
            while True:
                parent = win32gui.GetParent(parent_hwnd)
                if not parent or parent == 0:
                    break
                if parent == self.hwnd or parent in control_chain:
                    control_chain.append(parent)
                    break
                control_chain.append(parent)
                parent_hwnd = parent
        except Exception:
            pass
        return control_chain

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
            current = child_hwnd
            while current and current != root_hwnd:
                current = win32gui.GetParent(current)
            return current == root_hwnd
        except Exception:
            return False

    def _find_best_click_target(self, x: int, y: int):
        root_hwnd = self.hwnd
        target_hwnd = root_hwnd
        target_x, target_y = int(x), int(y)
        # Normalize client coords when DPI virtualization is in effect
        try:
            screen0_x, screen0_y = win32gui.ClientToScreen(root_hwnd, (0, 0))
            screen1_x, screen1_y = win32gui.ClientToScreen(root_hwnd, (int(x), int(y)))
            delta_x = screen1_x - screen0_x
            delta_y = screen1_y - screen0_y
            if abs(delta_x - int(x)) > 2 or abs(delta_y - int(y)) > 2:
                # Likely physical -> logical mismatch, use logical deltas for Win32 messages
                target_x = int(delta_x)
                target_y = int(delta_y)
                self.logger.info(
                    f"[click-target] DPI坐标修正: input=({x},{y}) -> logical=({target_x},{target_y}), "
                    f"delta=({delta_x},{delta_y})"
                )
            screen_x = screen0_x + target_x
            screen_y = screen0_y + target_y
        except Exception:
            return target_hwnd, target_x, target_y

        candidates = []

        # Strategy 1: deep child finder
        if hasattr(self, 'child_finder') and self.child_finder:
            try:
                deepest_hwnd, chain_dicts, _ = self.child_finder.find_deepest_child(
                    root_hwnd, screen_x, screen_y
                )
                if deepest_hwnd and win32gui.IsWindow(deepest_hwnd):
                    candidates.append((deepest_hwnd, "deepest"))
                if chain_dicts:
                    for c in chain_dicts:
                        hwnd = c.get('hwnd')
                        if hwnd and win32gui.IsWindow(hwnd):
                            candidates.append((hwnd, "chain"))
            except Exception:
                pass

        # Strategy 2: WindowFromPoint
        try:
            hwnd_wfp = win32gui.WindowFromPoint((int(screen_x), int(screen_y)))
            if hwnd_wfp and win32gui.IsWindow(hwnd_wfp) and self._is_descendant(root_hwnd, hwnd_wfp):
                candidates.append((hwnd_wfp, "wfp"))
        except Exception:
            pass

        # Strategy 3: ChildWindowFromPointEx
        try:
            child_hwnd = win32gui.ChildWindowFromPointEx(
                root_hwnd, (int(target_x), int(target_y)),
                win32con.CWP_SKIPINVISIBLE | win32con.CWP_SKIPDISABLED | win32con.CWP_SKIPTRANSPARENT
            )
            if child_hwnd and win32gui.IsWindow(child_hwnd):
                candidates.append((child_hwnd, "child"))
        except Exception:
            pass

        # Strategy 4: enumerate all descendants and pick smallest rect containing point
        try:
            all_children = []
            def _enum_child(hwnd, lparam):
                all_children.append(hwnd)
                return True
            win32gui.EnumChildWindows(root_hwnd, _enum_child, None)
            for hwnd in all_children:
                try:
                    rect = win32gui.GetWindowRect(hwnd)
                    if rect and rect[0] <= screen_x <= rect[2] and rect[1] <= screen_y <= rect[3]:
                        candidates.append((hwnd, "enum"))
                except Exception:
                    continue
        except Exception:
            pass

        # Choose best candidate by smallest area (more specific)
        best_hwnd = None
        best_area = None
        candidate_details = []
        seen = set()
        for hwnd, source in candidates:
            if hwnd in seen:
                continue
            seen.add(hwnd)
            try:
                rect = win32gui.GetWindowRect(hwnd)
                area = max(1, (rect[2] - rect[0]) * (rect[3] - rect[1]))
                candidate_details.append((area, hwnd, rect, source))
                if best_area is None or area < best_area:
                    best_area = area
                    best_hwnd = hwnd
            except Exception:
                continue

        if best_hwnd and win32gui.IsWindow(best_hwnd):
            target_hwnd = best_hwnd
            try:
                # Decide whether input coords are already relative to target
                use_direct = False
                try:
                    root_rect = win32gui.GetClientRect(root_hwnd)
                    root_w = root_rect[2] - root_rect[0]
                    root_h = root_rect[3] - root_rect[1]
                except Exception:
                    root_w = root_h = None
                try:
                    target_client = win32gui.GetClientRect(target_hwnd)
                    target_w = target_client[2] - target_client[0]
                    target_h = target_client[3] - target_client[1]
                except Exception:
                    target_w = target_h = None

                if target_hwnd != root_hwnd and root_w and root_h and target_w and target_h:
                    # If target is nearly as large as root, treat coords as target-relative
                    if target_w >= int(root_w * 0.8) and target_h >= int(root_h * 0.8):
                        use_direct = True
                    # Exact match also qualifies
                    if abs(target_w - root_w) <= 2 and abs(target_h - root_h) <= 2:
                        use_direct = True

                if use_direct:
                    target_x, target_y = int(target_x), int(target_y)
                    self.logger.info(
                        f"[click-target] 使用直接坐标: target=0x{target_hwnd:08X}, "
                        f"input=({target_x},{target_y}), size=({target_w}x{target_h}), root=({root_w}x{root_h})"
                    )
                else:
                    target_x, target_y = win32gui.ScreenToClient(target_hwnd, (int(screen_x), int(screen_y)))
            except Exception:
                pass
        else:
            best_hwnd = root_hwnd

        # Debug summary (limited)
        try:
            class_name = win32gui.GetClassName(best_hwnd) if best_hwnd else ""
        except Exception:
            class_name = ""
        try:
            window_text = win32gui.GetWindowText(best_hwnd) if best_hwnd else ""
        except Exception:
            window_text = ""

        # If render-surface class is detected, prefer root window for click dispatch
        try:
            class_lower = (class_name or "").lower()
            text_lower = (window_text or "").lower()
            if target_hwnd != root_hwnd and (
                "nemu" in class_lower or "nemu" in text_lower or "display" in text_lower or "render" in class_lower
            ):
                # Map display coords to root client coords using window rect offset
                try:
                    root_client_screen = win32gui.ClientToScreen(root_hwnd, (0, 0))
                    target_rect = win32gui.GetWindowRect(target_hwnd)
                    offset_x = int(target_rect[0] - root_client_screen[0])
                    offset_y = int(target_rect[1] - root_client_screen[1])
                    mapped_x = int(x) + offset_x
                    mapped_y = int(y) + offset_y
                except Exception:
                    offset_x = 0
                    offset_y = 0
                    mapped_x = int(x)
                    mapped_y = int(y)

                target_hwnd = root_hwnd
                target_x, target_y = mapped_x, mapped_y
                self.logger.info(
                    f"[click-target] render-surface检测，改为根窗口: root=0x{root_hwnd:08X}, "
                    f"input=({x},{y}) offset=({offset_x},{offset_y}) mapped=({target_x},{target_y}), "
                    f"class='{class_name}', text='{window_text[:30] if window_text else ''}'"
                )
        except Exception:
            pass
        try:
            best_rect = win32gui.GetWindowRect(best_hwnd) if best_hwnd else None
        except Exception:
            best_rect = None
        if not candidate_details:
            self.logger.warning(
                f"[click-target] 未找到子控件命中点，回退到根窗口: hwnd={root_hwnd}, "
                f"client=({x},{y}), screen=({screen_x},{screen_y})"
            )
        else:
            # Top 3 smallest candidates
            candidate_details.sort(key=lambda item: item[0])
            top_details = candidate_details[:3]
            top_str = "; ".join(
                f"hwnd=0x{h:08X}, area={a}, src={s}" for a, h, _, s in top_details
            )
            self.logger.info(
                f"[click-target] 选中 hwnd=0x{best_hwnd:08X} class='{class_name}' text='{window_text[:30] if window_text else ''}' "
                f"client=({target_x},{target_y}) screen=({screen_x},{screen_y}) rect={best_rect}, "
                f"candidates={len(candidate_details)} top=[{top_str}]"
            )

        return target_hwnd, int(target_x), int(target_y)

    def _get_window_chain(self):
        """Get window chain for background message dispatch."""
        chain = [self.hwnd]
        try:
            if hasattr(self, 'child_finder') and self.child_finder:
                deepest_hwnd, chain_dicts, _ = self.child_finder.find_deepest_child(
                    self.hwnd, 0, 0
                )
                if chain_dicts and len(chain_dicts) > 1:
                    chain = [c['hwnd'] for c in chain_dicts if 'hwnd' in c]
        except Exception:
            pass
        return chain

    def _resolve_mouse_message_targets(self, client_x: int, client_y: int):
        """
        解析后台鼠标消息目标链路（与拖拽链路保持一致）。
        返回:
            (window_chain, window_coords)
            window_chain: [hwnd1, hwnd2, ...]
            window_coords: {hwnd: (x, y), ...}
        """
        root_hwnd = self.hwnd
        safe_x = int(client_x)
        safe_y = int(client_y)
        window_chain = [root_hwnd]
        window_coords = {root_hwnd: (safe_x, safe_y)}

        try:
            if not (hasattr(self, 'child_finder') and self.child_finder):
                return window_chain, window_coords

            screen_x, screen_y = win32gui.ClientToScreen(root_hwnd, (safe_x, safe_y))
            _, chain_dicts, _ = self.child_finder.find_deepest_child(root_hwnd, screen_x, screen_y)

            resolved_chain = []
            if chain_dicts:
                for item in chain_dicts:
                    hwnd = item.get('hwnd')
                    if not hwnd:
                        continue
                    try:
                        hwnd = int(hwnd)
                        if not win32gui.IsWindow(hwnd):
                            continue
                    except Exception:
                        continue
                    if hwnd not in resolved_chain:
                        resolved_chain.append(hwnd)

            if resolved_chain:
                if resolved_chain[0] != root_hwnd:
                    resolved_chain.insert(0, root_hwnd)
                window_chain = resolved_chain

                for hwnd in window_chain:
                    try:
                        rect = win32gui.GetWindowRect(hwnd)
                        window_coords[hwnd] = (
                            int(screen_x - rect[0]),
                            int(screen_y - rect[1]),
                        )
                    except Exception:
                        window_coords[hwnd] = (safe_x, safe_y)
        except Exception as e:
            self.logger.debug(f"[鼠标链] 构建失败：{e}")

        return window_chain, window_coords

    def _send_mouse_message_to_chain(self, window_chain, window_coords, msg: int, wparam: int) -> bool:
        """向窗口链发送鼠标消息，至少一个句柄成功即视为成功。"""
        delivered = False
        for target_hwnd in window_chain:
            coord_x, coord_y = window_coords.get(target_hwnd, window_coords.get(self.hwnd, (0, 0)))
            lparam = self._make_mouse_lparam(int(coord_x), int(coord_y))
            try:
                self._send_message(target_hwnd, msg, wparam, lparam)
                delivered = True
            except Exception:
                continue
        return delivered

    def _screen_to_client(self, x: int, y: int):
        try:
            return win32gui.ScreenToClient(self.hwnd, (int(x), int(y)))
        except Exception:
            return int(x), int(y)

    def send_key_to_last_control(self, vk_code: int, scan_code: int = 0, extended: bool = False) -> bool:
        """向最近一次文本输入的控件发送按键（用于回车等）"""
        if not self._last_input_control_hwnd:
            return False
        return self.send_key_to_control(self._last_input_control_hwnd, vk_code, scan_code, extended)

    def send_key_to_control(self, control_hwnd: int, vk_code: int, scan_code: int = 0, extended: bool = False) -> bool:
        """向指定控件发送按键"""
        try:
            if not control_hwnd:
                return False
            if scan_code == 0:
                scan_code = win32api.MapVirtualKey(vk_code, 0)

            lparam_down = self._make_lparam(scan_code, extended, 1, False, False)
            lparam_up = self._make_lparam(scan_code, extended, 1, True, False)

            control_chain = self._get_control_chain(control_hwnd)
            for hwnd_to_send in control_chain:
                try:
                    self._send_message(hwnd_to_send, win32con.WM_KEYDOWN, vk_code, lparam_down)
                except Exception:
                    pass
            if not self._confirm_background_message_delivery(control_chain):
                return False

            _precise_sleep(0.01)

            for hwnd_to_send in control_chain:
                try:
                    self._send_message(hwnd_to_send, win32con.WM_KEYUP, vk_code, lparam_up)
                except Exception:
                    pass
            if not self._confirm_background_message_delivery(control_chain):
                return False

            return True
        except Exception:
            return False

    def move_mouse(self, x: int, y: int) -> bool:
        try:
            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                return self.driver.move_mouse(int(x), int(y), absolute=True)
            client_x, client_y = int(x), int(y)
            window_chain, window_coords = self._resolve_mouse_message_targets(client_x, client_y)
            return self._send_mouse_message_to_chain(window_chain, window_coords, win32con.WM_MOUSEMOVE, 0)
        except Exception:
            return False

    def mouse_down(self, x: int, y: int, button: str = 'left') -> bool:
        try:
            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                return self.driver.mouse_down(int(x), int(y), button=button)
            client_x, client_y = int(x), int(y)
            msg = win32con.WM_LBUTTONDOWN if button == 'left' else (
                win32con.WM_RBUTTONDOWN if button == 'right' else win32con.WM_MBUTTONDOWN
            )
            wparam = win32con.MK_LBUTTON if button == 'left' else (
                win32con.MK_RBUTTON if button == 'right' else win32con.MK_MBUTTON
            )
            window_chain, window_coords = self._resolve_mouse_message_targets(client_x, client_y)
            return self._send_mouse_message_to_chain(window_chain, window_coords, msg, wparam)
        except Exception:
            return False

    def mouse_up(self, x: int, y: int, button: str = 'left') -> bool:
        try:
            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                return self.driver.mouse_up(int(x), int(y), button=button)
            client_x, client_y = int(x), int(y)
            msg = win32con.WM_LBUTTONUP if button == 'left' else (
                win32con.WM_RBUTTONUP if button == 'right' else win32con.WM_MBUTTONUP
            )
            window_chain, window_coords = self._resolve_mouse_message_targets(client_x, client_y)
            return self._send_mouse_message_to_chain(window_chain, window_coords, msg, 0)
        except Exception:
            return False

    def double_click(self, x: int, y: int, button: str = 'left') -> bool:
        try:
            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                interval = _DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS
                first_ok = bool(
                    self.driver.click_mouse(
                        int(x),
                        int(y),
                        button=button,
                        clicks=1,
                        interval=0.0,
                        duration=0.0,
                    )
                )
                if not first_ok:
                    return False
                if interval > 0:
                    _precise_sleep(interval)
                return bool(
                    self.driver.click_mouse(
                        int(x),
                        int(y),
                        button=button,
                        clicks=1,
                        interval=0.0,
                        duration=0.0,
                    )
                )
            client_x, client_y = int(x), int(y)
            msg = win32con.WM_LBUTTONDBLCLK if button == 'left' else (
                win32con.WM_RBUTTONDBLCLK if button == 'right' else win32con.WM_MBUTTONDBLCLK
            )
            window_chain, window_coords = self._resolve_mouse_message_targets(client_x, client_y)
            return self._send_mouse_message_to_chain(window_chain, window_coords, msg, 0)
        except Exception:
            return False

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
            if not self.mouse_down(start_x, start_y, button=button):
                return False
            _precise_sleep(max(0.01, duration / 10.0))
            self.move_mouse(end_x, end_y)
            _precise_sleep(0.01)
            return self.mouse_up(end_x, end_y, button=button)
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

    def drag_path(self, path_points: list, duration: float = 1.0, button: str = 'left', timestamps: list = None) -> bool:
        """沿路径拖拽（支持前台驱动）"""
        try:
            if not path_points or len(path_points) < 2:
                return False

            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                mouse_backend = self._get_foreground_mouse_backend()
                if mouse_backend in ("pyautogui", "ibinputsimulator"):
                    return bool(
                        self.driver.drag_path(
                            path_points,
                            duration,
                            button=button,
                            timestamps=timestamps,
                        )
                    )

                try:
                    normalized_points = []
                    for point in path_points:
                        if not point or len(point) < 2:
                            continue
                        normalized_points.append((int(point[0]), int(point[1])))
                except Exception:
                    return False

                if len(normalized_points) < 2:
                    return False

                start_x, start_y = normalized_points[0]
                end_x, end_y = normalized_points[-1]

                if not bool(self.driver.move_mouse(start_x, start_y, absolute=True)):
                    return False
                if not bool(self.driver.mouse_down(start_x, start_y, button=button)):
                    return False

                try:
                    if timestamps and len(timestamps) == len(normalized_points):
                        safe_timestamps = []
                        for ts in timestamps:
                            try:
                                safe_timestamps.append(float(ts))
                            except Exception:
                                safe_timestamps.append(0.0)

                        prev_time = safe_timestamps[0]
                        prev_x, prev_y = normalized_points[0]
                        for (x, y), ts in zip(normalized_points[1:], safe_timestamps[1:]):
                            segment_duration = max(0.0, ts - prev_time)
                            if not self._foreground_move_segment_with_duration(
                                prev_x,
                                prev_y,
                                x,
                                y,
                                segment_duration,
                            ):
                                return False
                            prev_x, prev_y = x, y
                            prev_time = ts
                    else:
                        step_duration = max(0.0, float(duration or 0.0)) / max(1, len(normalized_points) - 1)
                        prev_x, prev_y = normalized_points[0]
                        for x, y in normalized_points[1:]:
                            if not self._foreground_move_segment_with_duration(
                                prev_x,
                                prev_y,
                                x,
                                y,
                                step_duration,
                            ):
                                return False
                            prev_x, prev_y = x, y
                finally:
                    self.driver.mouse_up(end_x, end_y, button=button)
                return True

            # 后台模式：退化为首尾拖拽
            start_x, start_y = path_points[0]
            end_x, end_y = path_points[-1]
            return self.drag(start_x, start_y, end_x, end_y, duration=duration, button=button)
        except Exception:
            return False

    def scroll(self, x: int, y: int, delta: int) -> bool:
        try:
            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                direction = 'up' if delta > 0 else 'down'
                clicks = int(abs(delta))
                return self.driver.scroll_mouse(direction, clicks, x=int(x), y=int(y))

            client_x, client_y = int(x), int(y)
            window_chain, window_coords = self._resolve_mouse_message_targets(client_x, client_y)
            root_x, root_y = window_coords.get(self.hwnd, (client_x, client_y))
            try:
                screen_x, screen_y = win32gui.ClientToScreen(self.hwnd, (int(root_x), int(root_y)))
            except Exception:
                screen_x, screen_y = int(root_x), int(root_y)

            wparam = (delta & 0xFFFF) << 16
            lparam = self._make_mouse_lparam(int(screen_x), int(screen_y))

            delivered = False
            for hwnd_to_send in window_chain:
                try:
                    self._send_message(hwnd_to_send, win32con.WM_MOUSEWHEEL, wparam, lparam)
                    delivered = True
                except Exception:
                    continue

            if not delivered:
                return False
            if not self._confirm_background_message_delivery(window_chain):
                return False
            return True
        except Exception:
            return False

    def send_key_down(self, vk_code: int, scan_code: int = 0, extended: bool = False) -> bool:
        try:
            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                key_name = self._vk_to_driver_key(vk_code)
                if not key_name:
                    return False
                return bool(self.driver.key_down(key_name))

            if scan_code == 0:
                scan_code = win32api.MapVirtualKey(vk_code, 0)
            lparam = self._make_lparam(scan_code, extended, 1, False, False)
            window_chain = self._get_window_chain()
            for hwnd_to_send in window_chain:
                try:
                    self._send_message(hwnd_to_send, win32con.WM_KEYDOWN, vk_code, lparam)
                except Exception:
                    pass
            if not self._confirm_background_message_delivery(window_chain):
                return False
            return True
        except Exception:
            return False

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
            window_chain = self._get_window_chain()
            for hwnd_to_send in window_chain:
                try:
                    self._send_message(hwnd_to_send, win32con.WM_KEYUP, vk_code, lparam)
                except Exception:
                    pass
            if not self._confirm_background_message_delivery(window_chain):
                return False
            return True
        except Exception:
            return False

    def send_key(self, vk_code: int, scan_code: int = 0, extended: bool = False) -> bool:
        try:
            return self.send_key_down(vk_code, scan_code, extended) and self.send_key_up(vk_code, scan_code, extended)
        except Exception:
            return False

    def send_key_hold(self, vk_code: int, duration: float = 0.0, scan_code: int = 0, extended: bool = False) -> bool:
        """
        按键保持（优先显式 down->hold->up，确保保持时长可控）。
        """
        try:
            safe_duration = max(0.0, float(duration))
        except Exception:
            safe_duration = 0.0

        try:
            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                key_name = self._vk_to_driver_key(vk_code)
                if not key_name:
                    return False
                # 前台优先走驱动原子按住，避免 down/up 两次调用被并发插队导致时长漂移。
                press_key_fn = getattr(self.driver, "press_key", None)
                if callable(press_key_fn):
                    return bool(press_key_fn(key_name, safe_duration))
                key_down_fn = getattr(self.driver, "key_down", None)
                key_up_fn = getattr(self.driver, "key_up", None)
                if callable(key_down_fn) and callable(key_up_fn):
                    down_sent = False
                    try:
                        if not bool(key_down_fn(key_name)):
                            return False
                        down_sent = True
                        if safe_duration > 0:
                            _shared_precise_sleep(safe_duration, spin_threshold=0.05, coarse_slice=0.005)
                        if not bool(key_up_fn(key_name)):
                            return False
                        down_sent = False
                        return True
                    finally:
                        if down_sent:
                            try:
                                key_up_fn(key_name)
                            except Exception:
                                pass

            if not self.send_key_down(vk_code, scan_code, extended):
                return False
            try:
                if safe_duration > 0:
                    _shared_precise_sleep(safe_duration, spin_threshold=0.05, coarse_slice=0.005)
            finally:
                return bool(self.send_key_up(vk_code, scan_code, extended))
        except Exception:
            return False

    def send_key_combination(self, keys: list, hold_duration: float = DEFAULT_KEY_HOLD_SECONDS) -> bool:
        try:
            for key in keys:
                self.send_key_down(key)
            _precise_sleep(max(0.0, float(hold_duration)))
            for key in reversed(keys):
                self.send_key_up(key)
            return True
        except Exception:
            return False

    def press_key_combination(self, keys: list) -> bool:
        try:
            for key in keys:
                self.send_key_down(key)
            return True
        except Exception:
            return False

    def release_key_combination(self, keys: list) -> bool:
        try:
            for key in reversed(keys):
                self.send_key_up(key)
            return True
        except Exception:
            return False

    def _find_and_send_to_input_control(self, text: str, stop_checker=None) -> bool:
        """Find an input control and send text."""
        try:
            if stop_checker and stop_checker():
                raise InterruptedError("stop requested")
            focused = self._find_focused_child_control()
            if focused:
                if self._send_text_to_specific_control(focused, text, stop_checker=stop_checker):
                    return True
            for control_hwnd, _, _ in self._find_all_input_controls():
                if stop_checker and stop_checker():
                    raise InterruptedError("stop requested")
                if self._send_text_to_specific_control(control_hwnd, text, stop_checker=stop_checker):
                    return True
            return False
        except InterruptedError:
            raise
        except Exception:
            return False

    def send_text(self, text: str, stop_checker=None) -> bool:
        try:
            if stop_checker and stop_checker():
                raise InterruptedError("stop requested")
            if self.use_foreground:
                if not self._ensure_driver():
                    return False
                try:
                    return self.driver.type_text(text)
                except Exception:
                    return self._sendinput_to_focused(text)
            return self._find_and_send_to_input_control(text, stop_checker=stop_checker)
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
            client_x, client_y = int(x), int(y)
            try:
                safe_clicks = max(1, int(clicks))
            except Exception:
                safe_clicks = 1
            try:
                safe_interval = max(0.0, float(interval))
            except Exception:
                safe_interval = 0.0
            try:
                safe_hold_duration = (
                    DEFAULT_CLICK_HOLD_SECONDS if duration is None else max(0.0, float(duration))
                )
            except Exception:
                safe_hold_duration = DEFAULT_CLICK_HOLD_SECONDS

            if button == 'left':
                down_msg, up_msg = win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP
                wparam_down = win32con.MK_LBUTTON
            elif button == 'right':
                down_msg, up_msg = win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONUP
                wparam_down = win32con.MK_RBUTTON
            else:
                down_msg, up_msg = win32con.WM_MBUTTONDOWN, win32con.WM_MBUTTONUP
                wparam_down = win32con.MK_MBUTTON

            window_chain, window_coords = self._resolve_mouse_message_targets(client_x, client_y)
            if len(window_chain) > 1:
                self.logger.info(f"[click-chain] multi-layer targets={len(window_chain)}")
            else:
                self.logger.info(f"[click-chain] single target: 0x{self.hwnd:08X}")

            for i in range(safe_clicks):
                if i > 0 and safe_interval > 0:
                    _precise_sleep(safe_interval)
                if self.enable_message_guard:
                    self._send_mouse_message_to_chain(
                        window_chain,
                        window_coords,
                        win32con.WM_MOUSEMOVE,
                        0,
                    )
                if not self._send_mouse_message_to_chain(
                    window_chain,
                    window_coords,
                    down_msg,
                    wparam_down,
                ):
                    return False
                if safe_hold_duration > 0:
                    _precise_sleep(safe_hold_duration)
                if not self._send_mouse_message_to_chain(
                    window_chain,
                    window_coords,
                    up_msg,
                    0,
                ):
                    return False
            return True
        except Exception:
            return False

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
    ) -> bool:
        """Foreground click helper."""
        try:
            if not self._ensure_driver():
                self.logger.error("前台驱动不可用")
                return False

            if not self._ensure_foreground_ready(timeout=0.15):
                self.logger.error("[foreground_click] target window is not foreground")
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

            try:
                safe_clicks = max(1, int(clicks))
            except Exception:
                safe_clicks = 1
            try:
                safe_interval = max(0.0, float(interval))
            except Exception:
                safe_interval = 0.0
            try:
                safe_duration = 0.0 if duration is None else max(0.0, float(duration))
            except Exception:
                safe_duration = 0.0

            if not hasattr(self.driver, "click_mouse"):
                self.logger.error("[foreground_click] driver missing click_mouse")
                return False

            # 前台点击前先强制落位一次，避免首击阶段被底层驱动“旧坐标”消费。
            try:
                if hasattr(self.driver, "move_mouse"):
                    if not bool(self.driver.move_mouse(target_x, target_y, absolute=True)):
                        return False
                    _precise_sleep(0.006)
            except Exception:
                return False

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
                    self.logger.warning("[foreground_click] 点击完成确认失败")
                    return False
            return True
        except Exception as e:
            self.logger.debug(f"[前台点击] 执行失败：{e}")
            return False

    def _ensure_foreground_ready(self, timeout: float = 0.15) -> bool:
        """确保目标窗口在发送前台输入前已成为前台窗口。"""
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
            if self._is_foreground_target_window(win32gui.GetForegroundWindow()):
                return True
        except Exception:
            pass

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
            fg_hwnd = int(foreground_hwnd or 0)
            target_hwnd = int(self.hwnd or 0)
        except Exception:
            return False
        if fg_hwnd <= 0 or target_hwnd <= 0:
            return False
        if fg_hwnd == target_hwnd:
            return True
        try:
            fg_root = int(win32gui.GetAncestor(fg_hwnd, win32con.GA_ROOT) or 0)
            target_root = int(win32gui.GetAncestor(target_hwnd, win32con.GA_ROOT) or 0)
            if fg_root > 0 and target_root > 0 and fg_root == target_root:
                return True
        except Exception:
            return False
        return False

    def _vk_to_focused(self, text: str) -> bool:
        """Send text by virtual key codes to focused control."""
        try:
            import win32api
            import win32con
            import win32gui
            import time

            self.logger.debug("[focused_vk] start")

            for char in text:
                vk_code = win32api.VkKeyScan(char)

                if vk_code != -1:
                    vk = vk_code & 0xFF
                    shift = (vk_code >> 8) & 0x01

                    try:
                        if shift:
                            self.send_key_down(win32con.VK_SHIFT)
                            self.send_key(vk)
                            self.send_key_up(win32con.VK_SHIFT)
                        else:
                            self.send_key(vk)

                        self.logger.debug(
                            f"[focused_vk] sent '{char}' (VK: {vk})"
                        )

                    except Exception as vk_error:
                        self.logger.debug(
                            f"[focused_vk] vk send failed, fallback WM_CHAR: {vk_error}"
                        )
                        self._send_message(self.hwnd, win32con.WM_CHAR, ord(char), 0)
                else:
                    self._send_message(self.hwnd, win32con.WM_CHAR, ord(char), 0)
                    self.logger.debug(f"[focused_vk] WM_CHAR '{char}'")

                _precise_sleep(0.05)

            self.logger.info("[focused_vk] done")
            return True

        except Exception as e:
            self.logger.debug(f"[聚焦按键] 执行失败：{e}")
            return False

    def _sendinput_to_focused(self, text: str) -> bool:
        """SendInput方法（全局输入，但输入框有焦点）"""
        try:
            import ctypes
            from ctypes import wintypes, Structure
            import time

            self.logger.debug("[焦点SendInput] 开始尝试SendInput")

            # 定义INPUT结构
            class KEYBDINPUT(Structure):
                _fields_ = [
                    ("wVk", wintypes.WORD),
                    ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))
                ]

            class INPUT(Structure):
                class _INPUT(ctypes.Union):
                    _fields_ = [("ki", KEYBDINPUT)]
                _anonymous_ = ("_input",)
                _fields_ = [
                    ("type", wintypes.DWORD),
                    ("_input", _INPUT)
                ]

            INPUT_KEYBOARD = 1
            KEYEVENTF_UNICODE = 0x0004

            for char in text:
                # 创建INPUT结构
                inputs = (INPUT * 1)()
                inputs[0].type = INPUT_KEYBOARD
                inputs[0].ki.wVk = 0
                inputs[0].ki.wScan = ord(char)
                inputs[0].ki.dwFlags = KEYEVENTF_UNICODE
                inputs[0].ki.time = 0
                inputs[0].ki.dwExtraInfo = None

                # 发送输入
                result = ctypes.windll.user32.SendInput(1, inputs, ctypes.sizeof(INPUT))

                if result:
                    self.logger.debug(f"[焦点SendInput] 成功发送字符 '{char}'")
                else:
                    self.logger.debug(f"[焦点SendInput] 发送字符 '{char}' 失败")
                    return False

                _precise_sleep(0.05)

            self.logger.info("[焦点SendInput] SendInput方法完成")
            return True

        except Exception as e:
            self.logger.debug(f"[焦点SendInput] 失败: {e}")
            return False

    def _find_focused_child_control(self) -> int:
        """寻找当前有焦点的子控件"""
        try:
            import win32gui
            import win32process
            import win32api
            import ctypes

            self.logger.debug("[寻找焦点控件] 开始寻找有焦点的子控件")

            # 通过AttachThreadInput获取焦点
            try:
                current_thread = win32api.GetCurrentThreadId()
                target_thread, _ = win32process.GetWindowThreadProcessId(self.hwnd)

                if current_thread != target_thread:
                    attach_result = ctypes.windll.user32.AttachThreadInput(current_thread, target_thread, True)

                    if attach_result:
                        try:
                            focused_hwnd = win32gui.GetFocus()
                            if focused_hwnd and focused_hwnd != self.hwnd:
                                self.logger.debug(f"[寻找焦点控件] 找到焦点控件: {focused_hwnd}")
                                return focused_hwnd
                        finally:
                            ctypes.windll.user32.AttachThreadInput(current_thread, target_thread, False)
            except Exception as e:
                self.logger.debug(f"[寻找焦点控件] AttachThreadInput失败: {e}")

            return 0

        except Exception as e:
            self.logger.debug(f"[寻找焦点控件] 失败: {e}")
            return 0

    def _find_all_input_controls(self) -> list:
        """枚举所有可能的输入框子控件"""
        try:
            import win32gui

            self.logger.debug("[枚举输入控件] 开始枚举所有可能的输入控件")

            input_controls = []

            def enum_child_proc(hwnd_child, lparam):
                try:
                    class_name = win32gui.GetClassName(hwnd_child)
                    window_text = win32gui.GetWindowText(hwnd_child)

                    # 输入控件类名列表
                    input_classes = [
                        'Edit', 'RichEdit', 'RichEdit20A', 'RichEdit20W', 'RICHEDIT50W',
                        'ComboBox', 'ListBox', 'Static', 'Button'
                    ]

                    is_input_class = any(input_class in class_name for input_class in input_classes)
                    is_visible = win32gui.IsWindowVisible(hwnd_child)

                    if is_input_class or (is_visible and window_text):
                        input_controls.append((hwnd_child, class_name, window_text))
                        self.logger.debug(f"[枚举输入控件] 找到候选控件: {hwnd_child} ({class_name}) '{window_text}'")

                except:
                    pass

                return True

            try:
                win32gui.EnumChildWindows(self.hwnd, enum_child_proc, 0)
            except:
                pass

            # 按优先级排序
            def control_priority(control):
                hwnd_child, class_name, window_text = control
                if 'Edit' in class_name or 'RichEdit' in class_name:
                    return 0
                elif 'ComboBox' in class_name:
                    return 1
                elif window_text:
                    return 2
                else:
                    return 3

            input_controls.sort(key=control_priority)

            self.logger.debug(f"[枚举输入控件] 总共找到 {len(input_controls)} 个候选控件")
            return input_controls

        except InterruptedError:
            raise
        except Exception as e:
            self.logger.debug(f"[枚举输入控件] 失败: {e}")
            return []

    def _send_text_to_specific_control(self, control_hwnd: int, text: str, stop_checker=None) -> bool:
        """向特定的控件发送文本 - 支持多层窗口链"""
        try:
            if stop_checker and stop_checker():
                raise InterruptedError("stop requested")
            import win32gui
            import win32con
            import pyperclip
            import ctypes
            import time

            self.logger.debug(f"[发送到控件] 开始向控件 {control_hwnd} 发送文本: '{text}'")

            # 获取控件信息
            try:
                class_name = win32gui.GetClassName(control_hwnd)
                window_text = win32gui.GetWindowText(control_hwnd)
                self.logger.debug(f"[发送到控件] 控件信息: 类名={class_name}, 文本='{window_text}'")
            except:
                class_name = "Unknown"
                window_text = ""

            # 获取多层窗口链（控件及其所有父窗口）
            control_chain = self._get_control_chain(control_hwnd)
            self.logger.debug(f"[send_to_control] control chain len: {len(control_chain)}")

            # 方法1：WM_CHAR逐字符发送 - 对中文最有效
            try:
                self.logger.debug("[发送到控件] 尝试WM_CHAR逐字符发送中文")

                for char in text:
                    if stop_checker and stop_checker():
                        raise InterruptedError("stop requested")
                    char_code = ord(char)
                    # 向控件链的第一个有效窗口发送WM_CHAR
                    for hwnd_char in control_chain:
                        try:
                            self._send_message(hwnd_char, win32con.WM_CHAR, char_code, 0)
                            break  # 发送成功后停止遍历
                        except Exception as char_err:
                            self.logger.debug(f"[发送到控件] WM_CHAR失败 (hwnd={hwnd_char}, char={char}): {char_err}")
                    _precise_sleep(0.05)

                if not self._confirm_background_message_delivery(control_chain):
                    self.logger.debug("[文本发送] WM_CHAR 完成确认失败")
                    return False

                self.logger.info(f"[发送到控件] WM_CHAR逐字符发送完成")
                self._last_input_control_hwnd = control_hwnd
                return True

            except InterruptedError:
                raise
            except Exception as char_error:
                self.logger.debug(f"[发送到控件] WM_CHAR方法失败: {char_error}")

            # 方法2：剪贴板粘贴（备选方案）
            try:
                if stop_checker and stop_checker():
                    raise InterruptedError("stop requested")
                self.logger.debug("[发送到控件] 尝试剪贴板粘贴")

                from utils.input_guard import acquire_input_guard

                clipboard_owner = f"clipboard_paste:hwnd={control_hwnd}"
                with acquire_input_guard(owner=clipboard_owner, resource="global_clipboard") as (acquired, _wait_ms):
                    if not acquired:
                        self.logger.debug("[文本发送] 获取剪贴板锁失败")
                        return False

                    original_clipboard = ""
                    clipboard_snapshot_available = False
                    try:
                        try:
                            original_clipboard = pyperclip.paste()
                            clipboard_snapshot_available = True
                        except Exception:
                            clipboard_snapshot_available = False

                        pyperclip.copy(text)
                        _precise_sleep(0.15)

                        paste_sent = False
                        for hwnd_paste in control_chain:
                            try:
                                result = self._send_message(hwnd_paste, win32con.WM_PASTE, 0, 0)
                                self.logger.debug(f"[text-send] WM_PASTE result (hwnd={hwnd_paste}): {result}")
                                paste_sent = True
                                break
                            except Exception as paste_err:
                                self.logger.debug(f"[文本发送] WM_PASTE 执行失败 (hwnd={hwnd_paste})：{paste_err}")

                        if not paste_sent:
                            return False
                        if not self._confirm_background_message_delivery(control_chain):
                            self.logger.debug("[文本发送] WM_PASTE 完成确认失败")
                            return False

                        _precise_sleep(0.3)
                        self._last_input_control_hwnd = control_hwnd
                        self.logger.debug(f"[text-send] clipboard paste path executed")
                        return True
                    finally:
                        if clipboard_snapshot_available:
                            try:
                                pyperclip.copy(original_clipboard)
                            except Exception:
                                pass

            except InterruptedError:
                raise
            except Exception as clipboard_error:
                self.logger.debug(f"[发送到控件] 剪贴板方法失败: {clipboard_error}")

            return False

        except InterruptedError:
            raise
        except Exception as e:
            self.logger.debug(f"[发送到控件] 发送失败: {e}")
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

            # 如果没找到DocumentControl，尝试找PaneControl
            pane = window_control.PaneControl(searchDepth=5, ClassName='Chrome_RenderWidgetHostHWND')
            if pane and pane.Exists(maxSearchSeconds=1):
                self.logger.debug(f"[元素点击] 找到Chrome RenderWidget")
                return pane

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
            try:
                conditions['foundIndex'] = max(1, int(found_index) + 1)
            except Exception:
                pass

        return conditions

    def _find_element_by_conditions(self, window_control, name, automation_id, class_name, control_type, search_depth, found_index=None):
        """使用UIAutomation原生搜索元素（快速）"""
        try:
            auto = import_uiautomation()
            conditions = self._build_search_conditions(name, automation_id, class_name, control_type, search_depth, found_index)

            # 使用具体的控件类搜索更快
            if control_type:
                control_class = self._get_control_class(control_type)
                if control_class:
                    return control_class(searchFromControl=window_control, **conditions)
            return window_control.Control(**conditions)
        except:
            return None

    def _find_elements_by_traversal(self, window_control, name, automation_id, class_name, control_type, search_depth, found_index: int = None):
        """遍历搜索元素"""
        results = []
        expected_type_name = control_type.replace('Control', '') if control_type is not None else None
        expected_type_id = None
        auto = None
        if control_type is not None:
            try:
                auto = import_uiautomation()
                expected_type_id = getattr(auto.ControlType, control_type, None)
            except Exception:
                auto = None
        stop_at = None
        if found_index is not None:
            try:
                stop_at = max(0, int(found_index))
            except Exception:
                stop_at = None

        def match_element(element) -> bool:
            try:
                # 先检查最快排除的属性
                if expected_type_id is not None:
                    if element.ControlType != expected_type_id:
                        return False
                elif expected_type_name is not None:
                    element_type = element.ControlTypeName
                    if element_type != expected_type_name:
                        return False
                if class_name is not None and element.ClassName != class_name:
                    return False
                if name is not None and element.Name != name:
                    return False
                if automation_id is not None and element.AutomationId != automation_id:
                    return False
                return True
            except:
                return False

        if auto is None:
            try:
                auto = import_uiautomation()
            except Exception:
                auto = None

        if auto and hasattr(auto, 'WalkControl'):
            try:
                for child, _depth in auto.WalkControl(window_control, False, search_depth):
                    if match_element(child):
                        results.append(child)
                        if stop_at is not None and len(results) > stop_at:
                            return results
                return results
            except Exception:
                results = []

        def search_children(parent, depth: int):
            if depth > search_depth:
                return False
            try:
                for child in parent.GetChildren():
                    if match_element(child):
                        results.append(child)
                        if stop_at is not None and len(results) > stop_at:
                            return True
                    if search_children(child, depth + 1):
                        return True
            except:
                return False
            return False

        search_children(window_control, 0)
        return results

    def _get_fast_traversal_depth(self, search_depth, name, automation_id, class_name, control_type):
        """根据条件强度给出较小的遍历深度（失败时仍会回退到完整深度）"""
        try:
            depth = int(search_depth)
        except Exception:
            return search_depth
        if depth <= 10:
            return depth
        if automation_id:
            return min(depth, 12)
        criteria = 0
        if name:
            criteria += 1
        if class_name:
            criteria += 1
        if control_type:
            criteria += 1
        if criteria >= 3:
            return min(depth, 12)
        if criteria == 2:
            return min(depth, 18)
        if criteria == 1:
            return min(depth, 22)
        return depth

    def _get_control_class(self, control_type: str):
        """
        根据控件类型字符串获取对应的控件类

        Args:
            control_type: 控件类型字符串，如 "ButtonControl", "EditControl"

        Returns:
            uiautomation 控件类
        """
        try:
            auto = import_uiautomation()

            control_map = {
                'ButtonControl': auto.ButtonControl,
                'EditControl': auto.EditControl,
                'TextControl': auto.TextControl,
                'CheckBoxControl': auto.CheckBoxControl,
                'RadioButtonControl': auto.RadioButtonControl,
                'ComboBoxControl': auto.ComboBoxControl,
                'ListControl': auto.ListControl,
                'ListItemControl': auto.ListItemControl,
                'MenuControl': auto.MenuControl,
                'MenuItemControl': auto.MenuItemControl,
                'TreeControl': auto.TreeControl,
                'TreeItemControl': auto.TreeItemControl,
                'TabControl': auto.TabControl,
                'TabItemControl': auto.TabItemControl,
                'HyperlinkControl': auto.HyperlinkControl,
                'ImageControl': auto.ImageControl,
                'WindowControl': auto.WindowControl,
                'PaneControl': auto.PaneControl,
                'GroupControl': auto.GroupControl,
                'ScrollBarControl': auto.ScrollBarControl,
                'SliderControl': auto.SliderControl,
                'SpinnerControl': auto.SpinnerControl,
                'ProgressBarControl': auto.ProgressBarControl,
                'DataGridControl': auto.DataGridControl,
                'DataItemControl': auto.DataItemControl,
                'DocumentControl': auto.DocumentControl,
                'ToolBarControl': auto.ToolBarControl,
                'ToolTipControl': auto.ToolTipControl,
                'StatusBarControl': auto.StatusBarControl,
                'HeaderControl': auto.HeaderControl,
                'HeaderItemControl': auto.HeaderItemControl,
                'SplitButtonControl': auto.SplitButtonControl,
                'TableControl': auto.TableControl,
                'ThumbControl': auto.ThumbControl,
                'TitleBarControl': auto.TitleBarControl,
                'SeparatorControl': auto.SeparatorControl,
                'SemanticZoomControl': auto.SemanticZoomControl,
                'AppBarControl': auto.AppBarControl,
                'CustomControl': auto.CustomControl,
                'Control': auto.Control,
            }

            return control_map.get(control_type, auto.Control)

        except ImportError:
            return None

    _ASYNC_SAFE_MESSAGES = {
        win32con.WM_LBUTTONDOWN,
        win32con.WM_LBUTTONUP,
        win32con.WM_LBUTTONDBLCLK,
        win32con.WM_RBUTTONDOWN,
        win32con.WM_RBUTTONUP,
        win32con.WM_RBUTTONDBLCLK,
        win32con.WM_MBUTTONDOWN,
        win32con.WM_MBUTTONUP,
        win32con.WM_MBUTTONDBLCLK,
        win32con.WM_MOUSEMOVE,
        win32con.WM_MOUSEWHEEL,
        win32con.WM_KEYDOWN,
        win32con.WM_KEYUP,
        win32con.WM_SYSKEYDOWN,
        win32con.WM_SYSKEYUP,
        win32con.WM_CHAR,
    }

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
            # 策略2: 在DocumentControl中遍历搜索
            if not element or not element.Exists(maxSearchSeconds=1):
                self.logger.debug("[元素点击] 精确搜索失败，尝试遍历搜索")
                fast_depth = self._get_fast_traversal_depth(
                    search_depth, name, automation_id, class_name, control_type
                )
                elements = self._find_elements_by_traversal(
                    search_root, name, automation_id, class_name, control_type, fast_depth, found_index
                )
                if (not elements or len(elements) <= found_index) and fast_depth < search_depth:
                    elements = self._find_elements_by_traversal(
                        search_root, name, automation_id, class_name, control_type, search_depth, found_index
                    )
                if elements and len(elements) > found_index:
                    element = elements[found_index]

            # 策略3: 如果在DocumentControl中没找到，回退到窗口搜索
            if (not element or not element.Exists(maxSearchSeconds=1)) and search_root != window_control:
                self.logger.debug("[元素点击] DocumentControl中未找到，回退到窗口搜索")
                element = self._find_element_by_conditions(
                    window_control, name, automation_id, class_name, control_type, search_depth, found_index
                )
                if not element or not element.Exists(maxSearchSeconds=1):
                    fast_depth = self._get_fast_traversal_depth(
                        search_depth, name, automation_id, class_name, control_type
                    )
                    elements = self._find_elements_by_traversal(
                        window_control, name, automation_id, class_name, control_type, fast_depth, found_index
                    )
                    if (not elements or len(elements) <= found_index) and fast_depth < search_depth:
                        elements = self._find_elements_by_traversal(
                            window_control, name, automation_id, class_name, control_type, search_depth, found_index
                        )
                    if elements and len(elements) > found_index:
                        element = elements[found_index]

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
                except Exception as invoke_error:
                    self.logger.debug(f"[元素点击] Invoke 模式失败: {invoke_error}，回退到坐标点击")

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
                        return self._background_click(client_x, client_y, button, 1, 0.1)
                    except Exception as coord_error:
                        self.logger.error(f"[元素点击] 坐标转换失败: {coord_error}")
                        # 回退到 uiautomation 的 Click 方法
                        element.Click()
                        return True
            else:
                # BoundingRectangle 无效，使用 uiautomation 的 Click 方法
                element.Click()
                self.logger.info("[元素点击] 使用 uiautomation.Click() 成功")
                return True

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

            # 策略2: 遍历搜索
            fast_depth = self._get_fast_traversal_depth(
                search_depth, name, automation_id, class_name, control_type
            )
            elements = self._find_elements_by_traversal(
                window_control, name, automation_id, class_name, control_type, fast_depth, 0
            )
            if not elements and fast_depth < search_depth:
                elements = self._find_elements_by_traversal(
                    window_control, name, automation_id, class_name, control_type, search_depth, 0
                )
            if elements:
                return elements[0]

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
                    if control_type is not None and element.ControlTypeName != control_type.replace('Control', ''):
                        return False
                    return True
                except:
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
                except:
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
                except:
                    pass

                try:
                    # 尝试 TextPattern
                    text_pattern = element.GetTextPattern()
                    if text_pattern:
                        return text_pattern.DocumentRange.GetText(-1)
                except:
                    pass

                # 回退到 Name 属性
                return element.Name

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

                # 回退到模拟输入
                try:
                    element.Click()
                    import time
                    _precise_sleep(0.1)

                    # 清空现有内容
                    auto = import_uiautomation()
                    auto.SendKeys('{Ctrl}a{Delete}')
                    _precise_sleep(0.05)

                    # 输入新值
                    auto.SendKeys(value, interval=0.01)
                    self.logger.info(f"[设置元素值] 使用模拟输入设置成功: {value}")
                    return True
                except Exception as input_error:
                    self.logger.error(f"[设置元素值] 模拟输入失败: {input_error}")
                    return False

            raise ElementNotFoundError("未找到目标元素")

        except ElementNotFoundError:
            raise
        except Exception as e:
            self.logger.error(f"[设置元素值] 失败: {e}")
            return False
