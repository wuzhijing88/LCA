# -*- coding: utf-8 -*-
"""UI元素拾取工具

通过UIAutomation获取鼠标位置下的UI元素属性。
"""

import time
import threading
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass

from utils.uiautomation_runtime import (
    import_uiautomation,
    is_uiautomation_available,
    uiautomation_thread_context,
)

try:
    auto = import_uiautomation()
    UIAUTOMATION_AVAILABLE = True
except Exception:
    auto = None
    UIAUTOMATION_AVAILABLE = False

import logging
logger = logging.getLogger(__name__)


@dataclass
class ElementInfo:
    """UI元素信息"""
    name: str = ""
    automation_id: str = ""
    class_name: str = ""
    control_type: str = ""
    bounding_rect: tuple = (0, 0, 0, 0)
    is_enabled: bool = True
    is_visible: bool = True


class ElementPicker:
    """UI元素拾取器

    使用方法:
        picker = ElementPicker()
        picker.start_picking(delay=3, callback=on_element_picked)
    """

    def __init__(self):
        self._picking = False
        self._thread: Optional[threading.Thread] = None

    @staticmethod
    def is_available() -> bool:
        """检查UIAutomation是否可用"""
        return is_uiautomation_available()

    def start_picking(self, delay: float = 3.0, callback: Optional[Callable[[Optional[ElementInfo]], None]] = None):
        """开始元素拾取

        Args:
            delay: 延迟时间(秒)，给用户时间将鼠标移动到目标元素
            callback: 回调函数，接收ElementInfo或None(失败时)
        """
        if self._picking:
            logger.warning("元素拾取正在进行中")
            return

        if not UIAUTOMATION_AVAILABLE:
            logger.error("UIAutomation模块不可用")
            if callback:
                callback(None)
            return

        self._picking = True
        self._thread = threading.Thread(
            target=self._do_picking,
            args=(delay, callback),
            daemon=True
        )
        self._thread.start()

    def _do_picking(self, delay: float, callback: Optional[Callable[[Optional[ElementInfo]], None]]):
        """执行元素拾取（在后台线程中）"""
        try:
            local_auto = import_uiautomation()
            with uiautomation_thread_context(local_auto):
                time.sleep(delay)

                element = local_auto.ControlFromCursor()
                if element:
                    info = ElementInfo(
                        name=element.Name or "",
                        automation_id=element.AutomationId or "",
                        class_name=element.ClassName or "",
                        control_type=element.ControlTypeName or "",
                        bounding_rect=element.BoundingRectangle,
                        is_enabled=element.IsEnabled,
                        is_visible=not element.IsOffscreen
                    )
                    logger.info(f"拾取到元素: Name={info.name}, AutomationId={info.automation_id}, "
                               f"ClassName={info.class_name}, ControlType={info.control_type}")
                    if callback:
                        callback(info)
                else:
                    logger.warning("未找到鼠标位置下的元素")
                    if callback:
                        callback(None)

        except Exception as e:
            logger.error(f"元素拾取失败: {e}")
            if callback:
                callback(None)
        finally:
            self._picking = False

    def is_picking(self) -> bool:
        """是否正在拾取"""
        return self._picking
