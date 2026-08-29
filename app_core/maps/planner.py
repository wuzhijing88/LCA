from __future__ import annotations

import heapq
import math
from typing import Optional

import numpy as np

from app_core.maps.record import CELL_BLOCKED, MapRecord, effective_goal
from app_core.maps.walkability import merged_walkability

_SQRT2 = math.sqrt(2)
_CARDINAL = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0))
_DIAGONAL = ((1, 1, _SQRT2), (1, -1, _SQRT2), (-1, 1, _SQRT2), (-1, -1, _SQRT2))


def pixel_to_cell(x: int, y: int, cell_size: int = 8) -> tuple[int, int]:
    size = int(cell_size)
    return (int(x) // size, int(y) // size)


def cell_to_pixel(cx: int, cy: int, cell_size: int = 8) -> tuple[int, int]:
    size = int(cell_size)
    half = size // 2
    return (int(cx) * size + half, int(cy) * size + half)


def build_grid(walkability: np.ndarray, cell_size: int = 8) -> np.ndarray:
    size = int(cell_size)
    height, width = walkability.shape[:2]
    rows = (height + size - 1) // size
    cols = (width + size - 1) // size
    grid = np.zeros((rows, cols), dtype=np.uint8)
    for cy in range(rows):
        y0 = cy * size
        y1 = min(y0 + size, height)
        for cx in range(cols):
            x0 = cx * size
            x1 = min(x0 + size, width)
            if np.any(walkability[y0:y1, x0:x1] == CELL_BLOCKED):
                grid[cy, cx] = 1
    return grid


def astar(
    grid: np.ndarray,
    start: tuple[int, int],
    goal: tuple[int, int],
    eight: bool = True,
) -> Optional[list[tuple[int, int]]]:
    height, width = grid.shape[:2]
    sx, sy = int(start[0]), int(start[1])
    gx, gy = int(goal[0]), int(goal[1])

    def walkable(x: int, y: int) -> bool:
        return 0 <= x < width and 0 <= y < height and int(grid[y, x]) == 0

    if not walkable(sx, sy) or not walkable(gx, gy):
        return None
    if (sx, sy) == (gx, gy):
        return [(sx, sy)]

    deltas = _CARDINAL + _DIAGONAL if eight else _CARDINAL

    def heuristic(x: int, y: int) -> float:
        dx = abs(x - gx)
        dy = abs(y - gy)
        if eight:
            return (max(dx, dy) - min(dx, dy)) + min(dx, dy) * _SQRT2
        return float(dx + dy)

    open_heap: list[tuple[float, float, int, int]] = [(heuristic(sx, sy), 0.0, sx, sy)]
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score: dict[tuple[int, int], float] = {(sx, sy): 0.0}
    closed: set[tuple[int, int]] = set()

    while open_heap:
        _f, g, x, y = heapq.heappop(open_heap)
        if (x, y) in closed:
            continue
        if (x, y) == (gx, gy):
            path = [(x, y)]
            while (x, y) in came_from:
                x, y = came_from[(x, y)]
                path.append((x, y))
            path.reverse()
            return path
        closed.add((x, y))
        for dx, dy, cost in deltas:
            nx, ny = x + dx, y + dy
            if not walkable(nx, ny) or (nx, ny) in closed:
                continue
            ng = g + cost
            if ng < g_score.get((nx, ny), float("inf")):
                g_score[(nx, ny)] = ng
                came_from[(nx, ny)] = (x, y)
                heapq.heappush(open_heap, (ng + heuristic(nx, ny), ng, nx, ny))
    return None


def nearest_route_index(
    position: tuple[int, int],
    route: list[tuple[int, int]],
    from_index: int = 0,
) -> int:
    if not route:
        return 0
    start = max(0, min(int(from_index), len(route) - 1))
    px, py = float(position[0]), float(position[1])
    best_i = start
    best_d = float("inf")
    for index in range(start, len(route)):
        rx, ry = route[index]
        dist = math.hypot(px - float(rx), py - float(ry))
        if dist < best_d:
            best_d = dist
            best_i = index
    return best_i


def plan_path(
    record: MapRecord,
    position: tuple[int, int],
    *,
    eight: bool = True,
    cell_size: int = 8,
    route_progress: int = 0,
) -> list[tuple[int, int]]:
    merged = merged_walkability(record.walkability, record.painted_blocked)
    grid = build_grid(merged, cell_size)
    start_cell = pixel_to_cell(int(position[0]), int(position[1]), cell_size)

    if record.route:
        join_at = nearest_route_index(position, record.route, from_index=route_progress)
        waypoints = record.route[join_at:]
        cells: list[tuple[int, int]] = []
        prev = start_cell
        for waypoint in waypoints:
            dest = pixel_to_cell(int(waypoint[0]), int(waypoint[1]), cell_size)
            segment = astar(grid, prev, dest, eight=eight)
            if segment is None:
                return []
            if cells:
                segment = segment[1:]
            cells.extend(segment)
            prev = dest
        return [cell_to_pixel(cx, cy, cell_size) for cx, cy in cells]

    goal = effective_goal(record)
    dest = pixel_to_cell(int(goal[0]), int(goal[1]), cell_size)
    segment = astar(grid, start_cell, dest, eight=eight)
    if segment is None:
        return []
    return [cell_to_pixel(cx, cy, cell_size) for cx, cy in segment]


def reached_goal(
    position: tuple[int, int],
    goal: tuple[int, int],
    radius_px: float = 8.0,
) -> bool:
    return math.hypot(float(position[0] - goal[0]), float(position[1] - goal[1])) < float(radius_px)
