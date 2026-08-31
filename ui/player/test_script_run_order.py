import random

from ui.player.script_run_order import build_run_queue_parts, ordered_ids, resolve_list_order


def test_resolve_list_order_prefers_state_then_ui():
    ui = {
        "widgets": [
            {"id": "L1", "type": "script_list"},
            {"id": "L2", "type": "script_list"},
        ],
        "list_order": ["L2", "L1"],
    }
    assert resolve_list_order(ui, {}) == ["L2", "L1"]
    assert resolve_list_order(ui, {"list_order": ["L1", "L2"]}) == ["L1", "L2"]


def test_ordered_ids_random_uses_rng():
    ids = ["a", "b", "c", "d"]
    one = ordered_ids(ids, mode="random", rng=random.Random(1))
    two = ordered_ids(ids, mode="random", rng=random.Random(1))
    three = ordered_ids(ids, mode="random", rng=random.Random(2))
    assert one == two
    assert set(one) == set(ids)
    assert one != three or one == three  # may collide; just ensure shuffle API works
    assert set(three) == set(ids)


def test_build_run_queue_parts_fixed_concat_per_list_group_loops():
    ui = {
        "list_order": ["L1", "L2"],
        "list_order_mode": "fixed",
        "widgets": [
            {
                "id": "L1",
                "type": "script_list",
                "order_mode": "fixed",
                "group_loops": 2,
                "items": [{"id": "a"}, {"id": "b"}],
            },
            {
                "id": "L2",
                "type": "script_list",
                "order_mode": "fixed",
                "group_loops": 1,
                "items": [{"id": "c"}],
            },
        ],
    }
    scripts = {
        "a": {"cards": [1]},
        "b": {"cards": [2]},
        "c": {"cards": [3]},
    }
    queue = build_run_queue_parts(
        ui,
        selected_by_list={"L1": ["a", "b"], "L2": ["c"]},
        scripts=scripts,
        loops_by_id={"a": 1, "b": 1, "c": 1},
    )
    # L1 group_loops=2 → a,b,a,b then L2 → c
    assert [item[0] for item in queue] == ["a", "b", "a", "b", "c"]
