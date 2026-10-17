"""使用 Win32 客户区命中查询，取得从绑定窗口到接收控件的完整层级。"""

import logging
import ctypes
from ctypes import wintypes

import win32con
import win32gui
import win32process

logger = logging.getLogger(__name__)


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


_get_gui_thread_info = ctypes.WinDLL("user32", use_last_error=True).GetGUIThreadInfo
_get_gui_thread_info.argtypes = (wintypes.DWORD, ctypes.POINTER(_GUITHREADINFO))
_get_gui_thread_info.restype = wintypes.BOOL


def _focused_input_hwnd(root: int) -> int:
    """只读目标线程的焦点，不关联输入队列，也不改变系统焦点。"""
    thread_id, _ = win32process.GetWindowThreadProcessId(root)
    if not thread_id:
        raise RuntimeError("无法确定后台输入窗口线程")
    info = _GUITHREADINFO(cbSize=ctypes.sizeof(_GUITHREADINFO))
    if not _get_gui_thread_info(thread_id, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    focus = int(info.hwndFocus or 0)
    if focus and (focus == root or win32gui.IsChild(root, focus)):
        return focus
    return root


def resolve_background_key_targets(root: int, hierarchy_broadcast: bool, control_hwnd=None) -> list[int]:
    """关闭广播时直接使用绑定主窗口；开启后只解析它的直属祖先链。"""
    root = int(root)
    if not win32gui.IsWindow(root):
        raise RuntimeError("后台输入主窗口已失效")
    if not hierarchy_broadcast:
        return [root]
    current = _focused_input_hwnd(root) if control_hwnd is None else int(control_hwnd)
    chain = []
    while current and current not in chain and len(chain) < 64:
        if not win32gui.IsWindow(current):
            raise RuntimeError("后台输入窗口层级已失效")
        chain.append(current)
        if current == root:
            return list(reversed(chain))
        current = int(win32gui.GetParent(current) or 0)
    raise RuntimeError("无法确定后台输入的完整窗口层级")


def resolve_background_mouse_targets(root: int, x: int, y: int, hierarchy_broadcast: bool):
    """鼠标、滚轮和拖拽共用的目标解析；关闭广播不执行任何子窗口查询。"""
    root, x, y = int(root), int(x), int(y)
    if not win32gui.IsWindow(root):
        raise RuntimeError("后台输入主窗口已失效")
    if not hierarchy_broadcast:
        return [root], {root: (x, y)}
    screen_x, screen_y = win32gui.ClientToScreen(root, (x, y))
    receiver, chain, _ = get_child_window_finder().find_deepest_child(root, screen_x, screen_y)
    targets = [int(item["hwnd"]) for item in chain]
    if not targets or targets[0] != root or targets[-1] != receiver or len(set(targets)) != len(targets):
        raise RuntimeError("无法确定后台输入的完整窗口层级")
    coords = {target: win32gui.ScreenToClient(target, (screen_x, screen_y)) for target in targets}
    return targets, coords


class EnhancedChildWindowFinder:
    def __init__(self, enable_logging: bool = False):
        self.enable_logging = enable_logging

    def find_deepest_child(self, root_hwnd: int, screen_x: int, screen_y: int):
        """返回命中窗口、完整层级和客户区坐标；查询失败不切换查找方式。"""
        current = int(root_hwnd)
        chain = []
        seen = set()
        while current not in seen and len(chain) < 64:
            if not current or not win32gui.IsWindow(current):
                raise RuntimeError("鼠标命中查询包含无效窗口")
            seen.add(current)
            client_x, client_y = win32gui.ScreenToClient(current, (int(screen_x), int(screen_y)))
            chain.append({
                "hwnd": current,
                "class_name": win32gui.GetClassName(current),
                "window_text": win32gui.GetWindowText(current),
                "client_x": client_x,
                "client_y": client_y,
                "screen_x": screen_x,
                "screen_y": screen_y,
            })
            # 显式广播包含可见渲染层；禁用或透明样式不代表它不接收窗口消息。
            child = win32gui.ChildWindowFromPointEx(current, (client_x, client_y), win32con.CWP_SKIPINVISIBLE)
            if not child:
                raise RuntimeError("鼠标命中查询失败或坐标不在目标客户区内")
            if child == current:
                if self.enable_logging:
                    logger.debug("命中窗口层级：%s", [item["hwnd"] for item in chain])
                return current, chain, (client_x, client_y)
            if win32gui.GetParent(child) != current:
                raise RuntimeError("鼠标命中查询返回了非直属子窗口")
            current = int(child)
        raise RuntimeError("鼠标命中窗口层级存在循环或超过深度上限")


_global_finder = None


def get_child_window_finder(enable_logging: bool = False) -> EnhancedChildWindowFinder:
    global _global_finder
    if _global_finder is None:
        _global_finder = EnhancedChildWindowFinder(enable_logging=enable_logging)
    return _global_finder
