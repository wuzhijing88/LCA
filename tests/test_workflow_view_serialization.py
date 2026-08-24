import math

import pytest

import ui.workflow_parts.workflow_view_serialization_mixin as serialization_module
from ui.workflow_parts.workflow_view_loading_mixin import WorkflowViewLoadingMixin
from ui.workflow_parts.workflow_view_serialization_mixin import WorkflowViewSerializationMixin


class _Point:
    def __init__(self, x, y):
        self._x = x
        self._y = y

    def x(self):
        return self._x

    def y(self):
        return self._y


class _Rect:
    def center(self):
        return _Point(5, 6)


class _Viewport:
    def rect(self):
        return _Rect()


class _Transform:
    def __init__(self, values=None):
        self.values = values or (1, 0, 0, 0, 1, 0, 0, 0, 1)

    def __getattr__(self, name):
        if name.startswith("m") and len(name) == 3:
            row = int(name[1]) - 1
            column = int(name[2]) - 1
            return lambda: self.values[row * 3 + column]
        raise AttributeError(name)


class _Scene:
    def __init__(self):
        self.scene_items = []

    def items(self):
        return list(self.scene_items)


class _Card:
    def __init__(self, card_id, scene, *, x=0, y=0, parameters=None):
        self.card_id = card_id
        self.task_type = "测试卡片"
        self.parameters = parameters if parameters is not None else {}
        self.custom_name = None
        self.connections = []
        self._scene = scene
        self._x = x
        self._y = y

    def scene(self):
        return self._scene

    def x(self):
        return self._x

    def y(self):
        return self._y


class _Connection:
    def __init__(self, start_card, end_card, line_type):
        self.start_item = start_card
        self.end_item = end_card
        self.line_type = line_type


class _View(WorkflowViewSerializationMixin):
    def __init__(self):
        self.scene = _Scene()
        self.cards = {}
        self.connections = []
        self.workflow_metadata = {"owner": {"name": "测试"}}
        self.transform_value = _Transform()
        self.sync_called = False
        self.references_validated = False

    def _sync_connections_with_scene(self):
        self.sync_called = True

    def _validate_card_references(self):
        self.references_validated = True

    def _validate_registered_connection(self, connection):
        if not isinstance(connection, _Connection):
            raise TypeError("无效连接")
        return connection.start_item, connection.end_item, connection.line_type

    def transform(self):
        return self.transform_value

    def viewport(self):
        return _Viewport()

    def mapToScene(self, _point):
        return _Point(10, 20)


@pytest.fixture(autouse=True)
def _patch_qt_types(monkeypatch):
    monkeypatch.setattr(serialization_module, "TaskCard", _Card)
    monkeypatch.setattr(serialization_module, "ConnectionLine", _Connection)


def _populated_view():
    view = _View()
    card7 = _Card(7, view.scene, x=70, parameters={"nested": {"value": 7}})
    card1 = _Card(1, view.scene, x=10, parameters={"nested": {"value": 1}})
    view.cards = {7: card7, 1: card1}
    view.connections = [
        _Connection(card7, card1, "failure"),
        _Connection(card1, card7, "success"),
    ]
    view.scene.scene_items = [card7, card1, *view.connections]
    return view, card1, card7


def test_serialization_is_stable_and_does_not_modify_metadata():
    view, _card1, _card7 = _populated_view()

    data = view.serialize_workflow()

    assert view.sync_called
    assert view.references_validated
    assert [card["id"] for card in data["cards"]] == [1, 7]
    assert data["connections"] == [
        {"start_card_id": 1, "end_card_id": 7, "type": "success"},
        {"start_card_id": 7, "end_card_id": 1, "type": "failure"},
    ]
    assert data["metadata"] == {"owner": {"name": "测试"}}
    assert "created_date" not in data["metadata"]
    assert "engine_version" not in data["metadata"]
    WorkflowViewLoadingMixin._validate_current_workflow_data(data)


def test_serialization_returns_deeply_isolated_data():
    view, card1, _card7 = _populated_view()

    data = view.serialize_workflow()
    data["cards"][0]["parameters"]["nested"]["value"] = 99
    data["metadata"]["owner"]["name"] = "已修改"

    assert card1.parameters["nested"]["value"] == 1
    assert view.workflow_metadata["owner"]["name"] == "测试"


def test_serialization_rejects_card_key_mismatch():
    view = _View()
    view.cards = {1: _Card(2, view.scene)}

    with pytest.raises(ValueError, match="不一致"):
        view.serialize_workflow()


def test_serialization_rejects_invalid_card_key_before_sorting():
    view = _View()
    view.cards = {1: _Card(1, view.scene), "2": _Card(2, view.scene)}

    with pytest.raises(TypeError, match="字典键必须是非负整数"):
        view.serialize_workflow()


def test_serialization_rejects_invalid_connection():
    view = _View()
    card = _Card(1, view.scene)
    view.cards = {1: card}
    view.connections = [object()]

    with pytest.raises(TypeError, match="无效连接"):
        view.serialize_workflow()


def test_serialization_rejects_unregistered_scene_card():
    view = _View()
    view.scene.scene_items = [_Card(9, view.scene)]

    with pytest.raises(ValueError, match="未登记卡片"):
        view.serialize_workflow()


def test_serialization_rejects_unregistered_scene_connection():
    view = _View()
    card = _Card(1, view.scene)
    connection = _Connection(card, card, "success")
    view.cards = {1: card}
    view.scene.scene_items = [card, connection]

    with pytest.raises(ValueError, match="未登记连接"):
        view.serialize_workflow()


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_serialization_rejects_non_finite_coordinates(value):
    view = _View()
    view.cards = {1: _Card(1, view.scene, x=value)}

    with pytest.raises(TypeError, match="pos_x 必须是有限数字"):
        view.serialize_workflow()


def test_serialization_rejects_non_json_parameters():
    view = _View()
    view.cards = {1: _Card(1, view.scene, parameters={"invalid": object()})}

    with pytest.raises(TypeError, match="无法保存为 JSON"):
        view.serialize_workflow()


def test_serialization_rejects_invalid_metadata_instead_of_replacing_it():
    view = _View()
    view.workflow_metadata = None

    with pytest.raises(TypeError, match="metadata 必须是字典"):
        view.serialize_workflow()
