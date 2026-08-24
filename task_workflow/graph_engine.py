"""Pure workflow graph traversal independent from Qt and task I/O."""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Optional


class GraphValidationError(ValueError):
    pass


class GraphEngine:
    def __init__(self, connections: Iterable[Mapping[str, Any]]):
        self._connections: dict[int, list[dict[str, Any]]] = {}
        for index, connection in enumerate(connections or []):
            if not isinstance(connection, Mapping):
                raise GraphValidationError(f"connection {index} must be a mapping")
            start = _card_id(connection.get("start_card_id"))
            end = _card_id(connection.get("end_card_id"))
            if start is None or end is None:
                raise GraphValidationError(f"connection {index} must have integer start/end ids")
            normalized = dict(connection)
            normalized["start_card_id"] = start
            normalized["end_card_id"] = end
            normalized["type"] = str(connection.get("type") or "sequential").strip().lower()
            self._connections.setdefault(start, []).append(normalized)

    def connections_from(self, card_id: Any) -> tuple[dict[str, Any], ...]:
        normalized = _card_id(card_id)
        if normalized is None:
            return ()
        return tuple(self._connections.get(normalized, ()))

    def has_next(self, card_id: Any, success: bool) -> bool:
        connections = self.connections_from(card_id)
        if not connections:
            return False
        wanted = "success" if success else "failure"
        return any(
            connection["type"] in {"random", wanted, "sequential"}
            for connection in connections
        )

    def next_card(
        self,
        card_id: Any,
        success: bool,
        *,
        random_weight: Optional[Callable[[dict[str, Any]], float]] = None,
        random_choices: Callable[..., list[dict[str, Any]]] = random.choices,
    ) -> Optional[int]:
        connections = self.connections_from(card_id)
        random_connections = [item for item in connections if item["type"] == "random"]
        if random_connections:
            weights = [
                max(0.0, float(random_weight(item))) if random_weight else 1.0
                for item in random_connections
            ]
            if not any(weights):
                weights = [1.0] * len(random_connections)
            return int(random_choices(random_connections, weights=weights, k=1)[0]["end_card_id"])

        wanted = "success" if success else "failure"
        for connection in connections:
            if connection["type"] == wanted:
                return int(connection["end_card_id"])
        for connection in connections:
            if connection["type"] == "sequential":
                return int(connection["end_card_id"])
        return None

    def as_connection_map(self) -> dict[int, list[dict[str, Any]]]:
        return {
            card_id: [dict(connection) for connection in connections]
            for card_id, connections in self._connections.items()
        }

    @staticmethod
    def detect_closed_cycle(
        graph: Mapping[int, set[int]],
        terminal_possible: set[int],
        start_card_id: Any,
    ) -> Optional[dict[str, Any]]:
        start = _card_id(start_card_id)
        if start is None or start not in graph:
            return None
        reachable: set[int] = set()
        pending = [start]
        while pending:
            current = pending.pop()
            if current in reachable or current not in graph:
                continue
            reachable.add(current)
            pending.extend(next_id for next_id in graph.get(current, set()) if next_id not in reachable)

        index = 0
        indexes: dict[int, int] = {}
        lowlinks: dict[int, int] = {}
        stack: list[int] = []
        on_stack: set[int] = set()
        components: list[set[int]] = []

        def strong_connect(node: int) -> None:
            nonlocal index
            indexes[node] = index
            lowlinks[node] = index
            index += 1
            stack.append(node)
            on_stack.add(node)
            for next_node in graph.get(node, set()):
                if next_node not in reachable:
                    continue
                if next_node not in indexes:
                    strong_connect(next_node)
                    lowlinks[node] = min(lowlinks[node], lowlinks[next_node])
                elif next_node in on_stack:
                    lowlinks[node] = min(lowlinks[node], indexes[next_node])
            if lowlinks[node] == indexes[node]:
                component: set[int] = set()
                while stack:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.add(member)
                    if member == node:
                        break
                components.append(component)

        for card_id in sorted(reachable):
            if card_id not in indexes:
                strong_connect(card_id)
        for component in components:
            has_cycle = len(component) > 1 or any(
                card_id in graph.get(card_id, set()) for card_id in component
            )
            has_outgoing = any(
                next_id not in component
                for card_id in component
                for next_id in graph.get(card_id, set())
            )
            has_terminal_exit = any(card_id in terminal_possible for card_id in component)
            if has_cycle and not has_outgoing and not has_terminal_exit:
                return {"cards": sorted(component), "start_card_id": start}
        return None


def _card_id(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["GraphEngine", "GraphValidationError"]
