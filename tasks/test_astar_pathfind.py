from tasks import get_available_tasks, get_task_module
from tasks.astar_pathfind import get_params_definition, requires_input_lock, validate_card_params


def test_task_is_registered():
    assert "A*寻路" in get_available_tasks()
    assert get_task_module("A*寻路") is not None


def test_params_include_death_and_keys():
    params = get_params_definition()
    assert "death_image_paths" in params
    assert "open_stitcher" in params
    assert params["open_stitcher"]["action"] == "open_map_stitcher"
    assert requires_input_lock({}) is True


def test_validate_card_params_requires_death():
    error = validate_card_params({"map_option": "x — x", "death_image_paths": ""})
    assert error and "死亡" in error
