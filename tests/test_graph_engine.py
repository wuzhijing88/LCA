from task_workflow.graph_engine import GraphEngine


def test_graph_engine_prefers_outcome_edge_before_sequential():
    graph = GraphEngine(
        [
            {"start_card_id": 1, "end_card_id": 2, "type": "sequential"},
            {"start_card_id": 1, "end_card_id": 3, "type": "failure"},
        ]
    )

    assert graph.next_card(1, True) == 2
    assert graph.next_card(1, False) == 3


def test_graph_engine_uses_injected_random_choice():
    graph = GraphEngine(
        [
            {"start_card_id": 1, "end_card_id": 10, "type": "random"},
            {"start_card_id": 1, "end_card_id": 20, "type": "random"},
        ]
    )

    def choose_last(items, **_kwargs):
        return [items[-1]]

    assert graph.next_card(1, True, random_choices=choose_last) == 20


def test_graph_engine_exposes_defensive_connection_copies():
    graph = GraphEngine([{"start_card_id": "1", "end_card_id": "2"}])
    first = graph.as_connection_map()
    first[1][0]["end_card_id"] = 99

    assert graph.next_card(1, True) == 2


def test_graph_engine_detects_reachable_closed_cycle():
    cycle = GraphEngine.detect_closed_cycle(
        {1: {2}, 2: {1}, 3: set()},
        terminal_possible={3},
        start_card_id=1,
    )

    assert cycle == {"cards": [1, 2], "start_card_id": 1}


def test_graph_engine_allows_cycle_with_outgoing_exit():
    cycle = GraphEngine.detect_closed_cycle(
        {1: {2}, 2: {1, 3}, 3: set()},
        terminal_possible={3},
        start_card_id=1,
    )

    assert cycle is None
