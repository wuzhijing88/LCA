# -*- coding: utf-8 -*-
"""插件键鼠：只走大漠 BindWindow(Ex)，不套原生消息/驱动。"""

from __future__ import annotations

from typing import Optional

from utils.input.input_timing import DEFAULT_KEY_HOLD_SECONDS
from utils.input.key_repeat import hold_with_system_repeat
from utils.plugin.dx_input import PluginDxInput
from utils.precise_sleep import precise_sleep
from utils.window.hwnd_utils import as_hwnd

from .base import BaseInputSimulator
from .drag_path import prepare_drag_path, iter_drag_samples


class PluginInputSimulator(BaseInputSimulator):
    """大漠键鼠适配器。坐标一律客户区。"""

    supports_atomic_click_hold = True

    def __init__(self, hwnd: int):
        super().__init__(hwnd)
        self._dx = PluginDxInput(int(self.hwnd))
        self._owned_dx = self._dx

    def close(self) -> None:
        owned_dx = self.__dict__.get("_owned_dx")
        if owned_dx is not None:
            if not owned_dx.close():
                raise RuntimeError("插件鼠标输入释放失败")
            self._owned_dx = None
        self._dx = None

    def _input(self) -> PluginDxInput:
        if self._dx is None:
            raise RuntimeError("插件输入模拟器已关闭")
        return self._dx

    def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.1,
        duration: Optional[float] = None,
    ) -> bool:
        return bool(self._input().click(int(x), int(y), button, clicks, interval, duration))

    def mouse_down(self, x: int, y: int, button: str = "left", is_screen_coord: bool = False) -> bool:
        client_x, client_y = self._to_client(x, y, is_screen_coord)
        return bool(self._input().move_to(client_x, client_y) and self._input().mouse_down(button))

    def mouse_up(self, x: int, y: int, button: str = "left", is_screen_coord: bool = False) -> bool:
        return bool(self._input().mouse_up(button))

    def double_click(
        self,
        x: int,
        y: int,
        button: str = "left",
        interval: Optional[float] = None,
        hold_duration: Optional[float] = None,
    ) -> bool:
        return bool(
            self._input().double_click(
                int(x), int(y), button=button, interval=interval, hold_duration=hold_duration
            )
        )

    def move_mouse(self, x: int, y: int) -> bool:
        return bool(self._input().move_to(int(x), int(y)))

    def mouse_move(self, x: int, y: int) -> bool:
        return self.move_mouse(x, y)

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 1.0,
        button: str = "left",
    ) -> bool:
        return self.drag_path([(int(start_x), int(start_y)), (int(end_x), int(end_y))], duration, button)

    def drag_path(self, path_points: list, duration: float = 1.0, button: str = "left", timestamps: list = None) -> bool:
        """以共用路径采样调用大漠按下、移动、弹起，坐标均为客户区。"""
        points, segment_durations = prepare_drag_path(path_points, duration, timestamps)
        if button not in {"left", "right", "middle"}:
            raise ValueError(f"插件拖拽按钮无效：{button!r}")
        start_x, start_y = points[0]
        try:
            if not self.mouse_down(start_x, start_y, button=button):
                return False
            for wait, point_x, point_y in iter_drag_samples(points, segment_durations):
                if wait > 0:
                    precise_sleep(wait)
                if not self.move_mouse(point_x, point_y):
                    return False
        finally:
            end_x, end_y = points[-1]
            released = bool(self.mouse_up(end_x, end_y, button=button))
        return released

    def scroll(self, x: int, y: int, delta: int) -> bool:
        return bool(self._input().wheel(int(x), int(y), int(delta)))

    def send_key(self, vk_code: int, scan_code: int = 0, extended: bool = False) -> bool:
        _ = scan_code, extended
        return bool(self._input().key_press(int(vk_code)))

    def send_key_down(self, vk_code: int, scan_code: int = 0, extended: bool = False) -> bool:
        _ = scan_code, extended
        return bool(self._input().key_down(int(vk_code)))

    def send_key_up(self, vk_code: int, scan_code: int = 0, extended: bool = False) -> bool:
        _ = scan_code, extended
        return bool(self._input().key_up(int(vk_code)))

    def send_key_repeat(self, vk_code: int, scan_code: int = 0, extended: bool = False) -> bool:
        return self.send_key_down(vk_code, scan_code, extended)

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
        return hold_with_system_repeat(
            down=lambda: self.send_key_down(vk_code, scan_code, extended),
            up=lambda: self.send_key_up(vk_code, scan_code, extended),
            repeat=lambda: self.send_key_repeat(vk_code, scan_code, extended),
            duration=duration,
            sleep=lambda seconds: precise_sleep(seconds),
            enable_repeat=bool(enable_repeat),
            repeat_interval=repeat_interval,
            stop_checker=stop_checker,
        )

    def send_text(self, text: str, stop_checker=None, delay: Optional[float] = None) -> bool:
        return bool(self._input().send_text(
            str(text or ""), stop_checker=stop_checker, delay=0.0 if delay is None else delay,
        ))

    def send_key_combination(self, keys: list, hold_duration: float = DEFAULT_KEY_HOLD_SECONDS) -> bool:
        for key in keys:
            if not self.send_key_down(int(key)):
                return False
        precise_sleep(max(0.0, float(hold_duration)))
        for key in reversed(keys):
            if not self.send_key_up(int(key)):
                return False
        return True

    def press_key_combination(self, keys: list) -> bool:
        for key in keys:
            if not self.send_key_down(int(key)):
                return False
        return True

    def release_key_combination(self, keys: list) -> bool:
        for key in reversed(keys):
            if not self.send_key_up(int(key)):
                return False
        return True

    def _to_client(self, x: int, y: int, is_screen_coord: bool) -> tuple[int, int]:
        if not is_screen_coord:
            return int(x), int(y)
        try:
            import win32gui

            return win32gui.ScreenToClient(as_hwnd(self.hwnd), (int(x), int(y)))
        except Exception as exc:
            raise RuntimeError("插件输入客户区坐标转换失败") from exc
