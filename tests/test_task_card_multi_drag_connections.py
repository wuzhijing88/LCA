from types import SimpleNamespace
from unittest.mock import Mock

from ui.workflow_parts.task_card import TaskCard


class _Connection:
    def __init__(self, scene):
        self._scene = scene
        self.update_path = Mock()

    def scene(self):
        return self._scene


class _Card:
    def __init__(self, scene, connections):
        self._scene = scene
        self.connections = connections

    def scene(self):
        return self._scene


def test_refresh_dragged_connections_updates_each_connection_once():
    scene = object()
    first = _Connection(scene)
    second = _Connection(scene)
    primary = _Card(scene, [first])
    partner = _Card(scene, [first, second])
    view = SimpleNamespace()
    primary._dragging_multi_selection = True
    primary._other_selected_cards_start_positions = {partner: None}
    primary.scene = lambda: scene

    TaskCard._refresh_dragged_connections(primary)

    first.update_path.assert_called_once_with()
    second.update_path.assert_called_once_with()
