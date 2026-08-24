from ..parameter_panel_support import *


class ParameterPanelWindowDragMixin:

    def _is_interactive_child_widget(self, widget):
        interactive_types = (
            QLineEdit,
            QSpinBox,
            QDoubleSpinBox,
            QTextEdit,
            QPlainTextEdit,
            QComboBox,
            QPushButton,
        )
        current_widget = widget
        while current_widget and current_widget != self:
            if isinstance(current_widget, interactive_types):
                return True
            current_widget = current_widget.parent()
        return False

    def _is_close_button_clicked(self, event) -> bool:
        if not hasattr(self, 'close_button') or not hasattr(self, 'title_frame'):
            return False
        close_button_rect = self.close_button.geometry()
        close_button_global = self.title_frame.mapToParent(close_button_rect.topLeft())
        close_button_window_rect = QRect(close_button_global, close_button_rect.size())
        return close_button_window_rect.contains(event.pos())

    def _begin_panel_drag(self, event):
        self._mouse_pressed = True
        self._mouse_press_pos = event.globalPosition().toPoint()
        self._window_pos_before_move = self.pos()
        self._parent_pos_before_move = self.parent_window.pos() if self.parent_window else QPoint()
        self._panel_parent_offset = self._window_pos_before_move - self._parent_pos_before_move
        self._is_dragging = False
        event.accept()

    def _move_parent_window_with_panel(self, new_panel_pos):
        if not self.parent_window or not self._snap_to_parent_enabled:
            return
        panel_parent_offset = getattr(self, '_panel_parent_offset', QPoint(self.parent_window.width() + 2, 0))
        main_window_new_x = new_panel_pos.x() - panel_parent_offset.x()
        main_window_new_y = new_panel_pos.y() - panel_parent_offset.y()
        self.parent_window.move(main_window_new_x, main_window_new_y)

    def mousePressEvent(self, event):
        clicked_widget = self.childAt(event.pos())
        if clicked_widget and self._is_interactive_child_widget(clicked_widget):
            super().mousePressEvent(event)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_close_button_clicked(event):
                self.hide_panel()
                event.accept()
                return
            self._begin_panel_drag(event)
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._mouse_pressed and event.buttons() == Qt.MouseButton.LeftButton:
            if not self._is_dragging:
                self._is_dragging = True
                logger.debug('Start dragging parameter panel')
            global_pos = event.globalPosition().toPoint()
            delta = global_pos - self._mouse_press_pos
            new_panel_pos = self._window_pos_before_move + delta
            self.move(new_panel_pos)
            self._move_parent_window_with_panel(new_panel_pos)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_dragging:
                logger.debug('Finish dragging parameter panel')
            self._mouse_pressed = False
            self._is_dragging = False
            event.accept()
            return

        super().mouseReleaseEvent(event)
