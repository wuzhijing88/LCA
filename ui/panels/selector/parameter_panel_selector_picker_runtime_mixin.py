from ..parameter_panel_support import *
from utils.uiautomation_runtime import import_uiautomation, uiautomation_thread_context


class ParameterPanelSelectorPickerRuntimeMixin:
    def _pick_loop(self) -> None:
        import ctypes
        import time

        try:
            auto = import_uiautomation()
        except Exception as e:
            logger.error(f"[元素拾取] UIAutomation 初始化失败: {e}")
            self._cancel_current_element_pick()
            return

        last_rect = None
        last_element_hash = None
        keyboard_available, is_pressed = self._resolve_keyboard_listener()

        try:
            with uiautomation_thread_context(auto):
                while self._picking_active:
                    try:
                        if self._handle_pick_shortcuts(keyboard_available, is_pressed):
                            break

                        time.sleep(0.01)
                        element = self._get_element_at_cursor(auto, ctypes)
                        new_rect = self._extract_element_rect(element)
                        if new_rect is None:
                            time.sleep(0.05)
                            continue

                        element_hash = self._hash_element_identity(element)
                        if new_rect != last_rect or element_hash != last_element_hash:
                            last_rect = new_rect
                            last_element_hash = element_hash
                            self._current_element = element
                            logger.debug(f"[元素拾取] 检测到元素: {new_rect}, hash={element_hash}")
                            self._update_overlay_highlight(new_rect)

                        time.sleep(0.05)
                    except Exception as e:
                        logger.debug(f"元素拾取循环异常: {e}")
                        time.sleep(0.05)
        except Exception as e:
            logger.error(f"[元素拾取] UIAutomation 线程初始化失败: {e}")
            self._cancel_current_element_pick()

    def _resolve_keyboard_listener(self):
        try:
            from keyboard import is_pressed
            return True, is_pressed
        except ImportError:
            logger.warning("[元素拾取] keyboard库不可用，无法监听全局按键")
            return False, None

    def _handle_pick_shortcuts(self, keyboard_available: bool, is_pressed) -> bool:
        if keyboard_available and is_pressed is not None and is_pressed('esc'):
            logger.debug("[元素拾取] 检测到ESC键，取消拾取")
            self._cancel_current_element_pick()
            return True

        if self._is_global_right_button_pressed() and self._current_element:
            logger.debug("[元素拾取] 检测到右键，确认拾取")
            self._confirm_current_element_pick()
            return True

        return False

    def _is_global_right_button_pressed(self) -> bool:
        import ctypes
        return ctypes.windll.user32.GetAsyncKeyState(0x02) & 0x8000 != 0

    def _cancel_current_element_pick(self) -> None:
        if not getattr(self, '_picking_active', False):
            return
        self._picking_active = False
        self._picked_info = None
        self._queue_picker_overlay_close()
        self._queue_picker_callback('_on_picking_cancelled')

    def _confirm_current_element_pick(self) -> None:
        if not getattr(self, '_picking_active', False) or not self._current_element:
            return
        self._picking_active = False
        self._picked_info = self._build_picked_info_from_element(self._current_element)
        self._queue_picker_overlay_close()
        self._queue_picker_callback('_on_element_picked')

    def _build_picked_info_from_element(self, element):
        try:
            from utils.element_picker import ElementInfo

            rect = getattr(element, 'BoundingRectangle', None)
            return ElementInfo(
                name=self._safe_element_attr(element, 'Name'),
                automation_id=self._safe_element_attr(element, 'AutomationId'),
                class_name=self._safe_element_attr(element, 'ClassName'),
                control_type=self._safe_element_attr(element, 'ControlTypeName'),
                bounding_rect=(rect.left, rect.top, rect.width(), rect.height()) if rect else (0, 0, 0, 0),
            )
        except Exception as e:
            logger.error(f"[元素拾取] 获取属性失败: {e}")
            return None

    def _safe_element_attr(self, element, attr_name: str) -> str:
        try:
            return getattr(element, attr_name) or ""
        except Exception:
            return ""

    def _queue_picker_overlay_close(self) -> None:
        if hasattr(self, '_picker_overlay') and self._picker_overlay:
            self._picker_overlay.highlight_rect = None
            from PySide6.QtCore import QMetaObject, Qt as QtConst
            QMetaObject.invokeMethod(self._picker_overlay, 'close', QtConst.QueuedConnection)

    def _queue_picker_callback(self, method_name: str) -> None:
        from PySide6.QtCore import QMetaObject, Qt as QtConst
        QMetaObject.invokeMethod(self, method_name, QtConst.QueuedConnection)

    def _get_element_at_cursor(self, auto_module, ctypes_module):
        pt = ctypes_module.wintypes.POINT()
        ctypes_module.windll.user32.GetCursorPos(ctypes_module.byref(pt))
        return auto_module.ControlFromPoint(pt.x, pt.y)

    def _extract_element_rect(self, element):
        if not element:
            return None
        rect = getattr(element, 'BoundingRectangle', None)
        if not rect or rect.width() <= 0 or rect.height() <= 0:
            return None
        return (rect.left, rect.top, rect.width(), rect.height())

    def _hash_element_identity(self, element):
        try:
            return hash((element.ControlTypeName, element.AutomationId, element.Name))
        except Exception:
            return None

    def _update_overlay_highlight(self, new_rect) -> None:
        if hasattr(self, '_picker_overlay') and self._picker_overlay:
            self._picker_overlay.highlight_rect = new_rect
            logger.debug("[元素拾取] 设置highlight_rect并调用repaint")
            from PySide6.QtCore import QMetaObject, Qt as QtConst
            QMetaObject.invokeMethod(self._picker_overlay, 'repaint', QtConst.QueuedConnection)

    def _update_highlight_border(self):
        """Update highlight border."""
        try:
            rect = getattr(self, '_highlight_rect', None)
            if not rect:
                return
            x, y, w, h = rect
            if w <= 0 or h <= 0:
                return
            if hasattr(self, '_highlight_border') and self._highlight_border:
                self._highlight_border.setGeometry(int(x), int(y), int(w), int(h))
                self._highlight_border.show()
                self._highlight_border.update()
        except Exception as e:
            logger.error(f"更新高亮边框失败: {e}")
