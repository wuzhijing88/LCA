# -*- coding: utf-8 -*-
"""
点击执行适配器
将不同输入后端适配为 click_action_executor 所需接口：
- click(x, y, button, clicks, interval)
- mouse_down(x, y, button)
- mouse_up(x, y, button)
"""

from __future__ import annotations

from typing import Any



class ForegroundDriverSimulatorAdapter:
    """前台驱动适配器（click_mouse/mouse_down/mouse_up）。"""
    supports_atomic_click_hold = True

    def __init__(self, driver: Any):
        self._driver = driver

    def move_mouse(self, x: int, y: int, absolute: bool = True) -> bool:
        if not hasattr(self._driver, "move_mouse"):
            raise AttributeError("驱动不支持move_mouse方法")
        return bool(self._driver.move_mouse(int(x), int(y), absolute=bool(absolute)))

    def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.0,
        duration: float = 0.0,
    ) -> bool:
        if not hasattr(self._driver, "click_mouse"):
            raise AttributeError("驱动不支持click_mouse方法")
        try:
            safe_duration = max(0.0, float(duration))
        except Exception:
            safe_duration = 0.0
        return bool(
            self._driver.click_mouse(
                x=int(x),
                y=int(y),
                button=button,
                clicks=int(clicks),
                interval=float(interval),
                duration=safe_duration,
            )
        )

    def mouse_down(self, x: int, y: int, button: str = "left") -> bool:
        if not hasattr(self._driver, "mouse_down"):
            raise AttributeError("驱动不支持mouse_down方法")
        return bool(
            self._driver.mouse_down(
                x=int(x),
                y=int(y),
                button=button,
            )
        )

    def mouse_up(self, x: int, y: int, button: str = "left") -> bool:
        if not hasattr(self._driver, "mouse_up"):
            raise AttributeError("驱动不支持mouse_up方法")
        return bool(
            self._driver.mouse_up(
                x=int(x),
                y=int(y),
                button=button,
            )
        )
