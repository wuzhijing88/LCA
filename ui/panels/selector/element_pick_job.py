"""元素拾取后台任务；线程只读取系统元素，不持有任何界面对象。"""
import ctypes
import ctypes.wintypes
from threading import Event

from utils.input.uiautomation_runtime import import_uiautomation, uiautomation_thread_context


def pick_element(confirm: Event, cancelled: Event, progress):
    from utils.window.element_picker import ElementInfo

    auto = import_uiautomation()
    user32 = ctypes.windll.user32
    previous = None
    with uiautomation_thread_context(auto):
        while not cancelled.wait(0.01):
            if user32.GetAsyncKeyState(0x1B) & 0x8000:
                return None
            point = ctypes.wintypes.POINT()
            if not user32.GetCursorPos(ctypes.byref(point)):
                raise OSError("无法读取鼠标位置")
            element = auto.ControlFromPoint(point.x, point.y)
            if element is None:
                continue
            rect = element.BoundingRectangle
            if rect is None or rect.width() <= 0 or rect.height() <= 0:
                continue
            bounds = (rect.left, rect.top, rect.width(), rect.height())
            if bounds != previous:
                progress(bounds)
                previous = bounds
            if confirm.is_set() or user32.GetAsyncKeyState(0x02) & 0x8000:
                return ElementInfo(
                    name=element.Name,
                    automation_id=element.AutomationId,
                    class_name=element.ClassName,
                    control_type=element.ControlTypeName,
                    bounding_rect=bounds,
                )
    return None
