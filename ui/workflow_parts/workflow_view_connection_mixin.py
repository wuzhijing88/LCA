"""工作流与连线子系统的集成边界；不承担路由或交互状态。"""
import logging

from .connection_line import set_line_animation_paused

logger = logging.getLogger(__name__)


class WorkflowViewConnectionMixin:
    def _mark_workflow_dirty(self):
        main = self.main_window
        if main is None:
            return
        tabs = getattr(main, "workflow_tab_widget", None)
        if tabs is not None and self.task_id is not None:
            tabs._mark_task_modified(self.task_id)
        elif hasattr(main, "_mark_unsaved_changes"):
            main._mark_unsaved_changes()

    def _refresh_connection_parameter_display(self, card):
        card.update_port_restrictions()
        card._tooltip_needs_update = True
        card.update()
        panel = getattr(self.main_window, "parameter_panel", None)
        if panel is None or not panel.is_panel_open() or panel.current_card_id != card.card_id:
            return
        panel.current_parameters = dict(card.parameters)
        panel._opened_parameters_snapshot = dict(card.parameters)
        loading = panel._loading_parameter_panel
        panel._loading_parameter_panel = True
        try:
            panel._rebuild_parameter_widgets()
        finally:
            panel._loading_parameter_panel = loading

    def _sync_connections_with_scene(self):
        errors = self._connection_controller.errors()
        if errors:
            raise RuntimeError("；".join(errors))
        return True

    def validate_connections(self):
        return len(self._connection_controller.errors())

    def add_connection(self, start_card, end_card, line_type):
        if not self._loading_workflow and (not self.editing_enabled or self._block_edit_if_running("添加连线")):
            return None
        try:
            return self._connection_controller.add(start_card, end_card, line_type)
        except (TypeError, ValueError, RuntimeError) as error:
            logger.error("添加连线失败：%s", error)
            return None

    def remove_connection(self, connection):
        if not self.editing_enabled or self._block_edit_if_running("删除连线"):
            return False
        try:
            return self._connection_controller.remove(connection)
        except (TypeError, ValueError, RuntimeError) as error:
            logger.error("删除连线失败：%s", error)
            return False

    def reroute_connections(self, cards=None):
        self._connection_controller.reroute(cards)

    def preview_moving_card_connections(self, cards):
        self._connection_controller.reroute(cards)

    def set_canvas_drag_paused(self, paused):
        paused = bool(paused)
        if paused != self._canvas_connections_paused:
            self._canvas_connections_paused = paused
            set_line_animation_paused("canvas_drag", paused)

    def start_drag_line(self, card, port_type):
        return self._connection_gesture.begin(card, port_type)

    def update_drag_line(self, position):
        return self._connection_gesture.move(position)

    def end_drag_line(self, position):
        return self._connection_gesture.finish(position)

    def _cleanup_drag_state(self):
        self._connection_gesture.cancel()

    def update_card_sequence_display(self):
        return self._connection_controller.update_sequence()

    def update_single_card_jump_connections(self, card_id):
        if card_id in self.cards:
            self._connection_controller.sync_jump_parameters(self.cards[card_id])
