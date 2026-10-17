"""画布选择、平移和鼠标事件分发。"""
from .workflow_view_common import *
from .connection_line import clear_line_hover
from shiboken6 import isValid


class WorkflowViewCanvasMixin:
    def _cancel_canvas_panning(self):
        """恢复平移持有的显示状态；Qt 销毁时也可释放全局动画开关。"""
        self._is_panning = False
        self._last_pan_step_ms = 0.0
        self._set_drag_preview_mode(False)
        if isValid(self):
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._connection_gesture.active:
            self._cleanup_drag_state()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            lines = [item for item in self.scene.selectedItems() if isinstance(item, ConnectionLine)]
            if lines:
                for line in lines:
                    line.setSelected(False)
                clear_line_hover(self.scene)
                event.accept()
                return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        """处理多选、背景平移和普通卡片点击。"""
        self._hide_card_tooltip_overlay()
        item_at_pos = self.itemAt(event.position().toPoint())
        modifiers = event.modifiers()

        if (
            event.button() == Qt.MouseButton.LeftButton
            and modifiers == Qt.KeyboardModifier.ControlModifier
        ):
            if isinstance(item_at_pos, TaskCard):
                item_at_pos.setSelected(not item_at_pos.isSelected())
                event.accept()
                return
            if item_at_pos is None:
                self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
                super().mousePressEvent(event)
                return

        if event.button() == Qt.MouseButton.LeftButton and item_at_pos is None:
            self._stop_all_flashing()
            if not self.hasFocus():
                self.setFocus()
            if modifiers != Qt.KeyboardModifier.ControlModifier:
                clear_line_hover(self.scene)
                self.scene.clearSelection()
                self._is_panning = True
                self._set_drag_preview_mode(True)
                self._last_pan_step_ms = 0.0
                self._pan_start_x = event.position().toPoint().x()
                self._pan_start_y = event.position().toPoint().y()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self._clear_all_card_tooltips()
                event.accept()
            return

        if event.button() == Qt.MouseButton.RightButton:
            self._last_right_click_view_pos_f = event.position()
            event.accept()
            return

        if not self.hasFocus():
            self.setFocus()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        """处理连线拖拽、卡片拖动和画布平移。"""
        if self._is_panning:
            self._hide_card_tooltip_overlay()
            now_ms = time.perf_counter() * 1000.0
            if (
                self._pan_frame_interval_ms > 0
                and self._last_pan_step_ms > 0.0
                and now_ms - self._last_pan_step_ms < float(self._pan_frame_interval_ms)
            ):
                event.accept()
                return
            self._last_pan_step_ms = now_ms
            delta_x = event.position().toPoint().x() - self._pan_start_x
            delta_y = event.position().toPoint().y() - self._pan_start_y
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta_x)
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta_y)
            self._pan_start_x = event.position().toPoint().x()
            self._pan_start_y = event.position().toPoint().y()
            event.accept()
            return

        if self._connection_gesture.active:
            self.update_drag_line(self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """结束画布平移、连线拖拽或普通 Qt 拖动。"""
        if self._is_panning:
            self._is_panning = False
            self._last_pan_step_ms = 0.0
            self._set_drag_preview_mode(False)
            self._handle_scroll_change(0)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._hide_card_tooltip_overlay()
            event.accept()
            return

        if self._connection_gesture.active:
            self.end_drag_line(self.mapToScene(event.position().toPoint()))
            event.accept()
            return

        super().mouseReleaseEvent(event)
        if self.dragMode() == QGraphicsView.DragMode.RubberBandDrag:
            self.setDragMode(self._original_drag_mode)

    def leaveEvent(self, event):
        """指针离开视图时取消尚未完成的交互。"""
        if self._connection_gesture.active:
            self._cleanup_drag_state()
        if self._drag_preview_mode:
            self._cancel_canvas_panning()
        self._clear_all_snap_guide_lines()
        super().leaveEvent(event)

    def focusOutEvent(self, event):
        """视图失焦时取消尚未完成的交互。"""
        if self._connection_gesture.active:
            self._cleanup_drag_state()
        if self._drag_preview_mode:
            self._cancel_canvas_panning()
        self._clear_all_snap_guide_lines()
        super().focusOutEvent(event)

    def _clear_all_snap_guide_lines(self, *, commit=True):
        """清除所有卡片拖动状态和吸附辅助线。"""
        for card in self.cards.values():
            card._cancel_drag_state(commit=commit)

