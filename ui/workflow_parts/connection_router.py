"""正交连线路由：四连通 A*，绕开卡片障碍。"""

from __future__ import annotations

import heapq
import math
from collections import deque
from typing import Dict, List, Optional, Sequence, Set, Tuple

GRID_CELL = 10.0
OBSTACLE_INFLATE = 10.0
PORT_STUB = 20.0
INCOMING_SHARE = 80.0
SEARCH_MARGINS = (160.0, 320.0)
INDEX_CELL = 160.0
ROUTE_QUERY_PAD = SEARCH_MARGINS[-1] + PORT_STUB + OBSTACLE_INFLATE
STEP_COST = 1
TURN_PENALTY = 2
KEEP_OUT_PENALTY = 8
OCCUPY_PENALTY = 80
ASTAR_VISIT_LIMIT = 12000
ASTAR_STRICT_VISIT_LIMIT = 2500
ASTAR_STACKED_VISIT_LIMIT = 2000

_EPS = 1e-9
_DIR_EAST = 0
_DIR_NORTH = 1
_DIR_WEST = 2
_DIR_SOUTH = 3
_DIRECTIONS = (
    (1, 0),
    (0, -1),
    (-1, 0),
    (0, 1),
)

Point = Tuple[float, float]
Rect = Tuple[float, float, float, float]
Cell = Tuple[int, int]


class ExistingPath:
    """已有连线的缓存：折线、包围盒、占用格、汇入短桩。"""

    __slots__ = ("points", "aabb", "interior", "approach")

    def __init__(self, points: Sequence[Point]):
        self.points = [_as_point(point) for point in points]
        if len(self.points) < 2:
            raise ValueError("已有连线路径点不足")
        self.aabb = _polyline_aabb(self.points)
        self.interior = interior_cells_along_polyline(self.points)
        self.approach = incoming_approach_cells(self.points)


def _polyline_aabb(points: Sequence[Point]) -> Optional[Tuple[float, float, float, float]]:
    if not points:
        return None
    min_x = max_x = points[0][0]
    min_y = max_y = points[0][1]
    for x, y in points[1:]:
        if x < min_x:
            min_x = x
        elif x > max_x:
            max_x = x
        if y < min_y:
            min_y = y
        elif y > max_y:
            max_y = y
    return (min_x, min_y, max_x, max_y)


def _aabb_overlap(
    left: Tuple[float, float, float, float],
    right: Tuple[float, float, float, float],
) -> bool:
    return left[0] <= right[2] and right[0] <= left[2] and left[1] <= right[3] and right[1] <= left[3]


def _inflate_aabb(
    box: Optional[Tuple[float, float, float, float]],
    pad: float,
) -> Optional[Tuple[float, float, float, float]]:
    if box is None:
        return None
    return (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)


def _rects_overlapping_aabb(
    rects: Sequence[Rect],
    box: Optional[Tuple[float, float, float, float]],
    pad: float = 0.0,
) -> List[Rect]:
    if box is None:
        return list(rects)
    query = _inflate_aabb(box, pad)
    if query is None:
        return list(rects)
    nearby: List[Rect] = []
    for rect in rects:
        rx, ry, rw, rh = rect
        if _aabb_overlap(query, (rx, ry, rx + rw, ry + rh)):
            nearby.append(rect)
    return nearby


def _path_points(path) -> Sequence[Point]:
    if isinstance(path, ExistingPath):
        return path.points
    return path


def rect_aabb(rect: Rect) -> Tuple[float, float, float, float]:
    x, y, w, h = rect
    return (x, y, x + w, y + h)


def _segment_rect(start: Point, end: Point, pad: float) -> Rect:
    x0 = min(start[0], end[0]) - pad
    y0 = min(start[1], end[1]) - pad
    x1 = max(start[0], end[0]) + pad
    y1 = max(start[1], end[1]) + pad
    return (x0, y0, x1 - x0, y1 - y0)


def corridor_rects(start_pt: Point, end_pt: Point, pad: float) -> List[Rect]:
    """预览折线加宽后的走廊矩形，用来取附近障碍并限制 A* 搜索。"""
    points = preview_drag_connection(start_pt, end_pt, incoming=True)
    rects: List[Rect] = []
    for left, right in zip(points, points[1:]):
        rects.append(_segment_rect(left, right, pad))
    if not rects:
        rects.append(_segment_rect(start_pt, end_pt, pad))
    return rects


def _bucket_keys(aabb: Tuple[float, float, float, float], cell: float):
    x0, y0, x1, y1 = aabb
    bx0 = math.floor(x0 / cell)
    by0 = math.floor(y0 / cell)
    bx1 = math.floor(x1 / cell)
    by1 = math.floor(y1 / cell)
    for bx in range(bx0, bx1 + 1):
        for by in range(by0, by1 + 1):
            yield (bx, by)


class RouteIndex:
    """网格桶：插入包围盒，查询只扫与搜索盒相交的桶。"""

    def __init__(self, cell: float = INDEX_CELL):
        if not math.isfinite(cell) or cell <= 0.0:
            raise ValueError("索引格子必须是正有限数")
        self.cell = float(cell)
        self._buckets: Dict[Tuple[int, int], List[object]] = {}

    def insert(self, aabb, item) -> None:
        if aabb is None:
            return
        for key in _bucket_keys(aabb, self.cell):
            bucket = self._buckets.get(key)
            if bucket is None:
                self._buckets[key] = [item]
            else:
                bucket.append(item)

    def query(self, aabb) -> List:
        if aabb is None:
            return []
        found: List = []
        seen = set()
        self._collect(aabb, found, seen)
        return found

    def query_rects(self, rects: Sequence[Rect]) -> List:
        found: List = []
        seen = set()
        for rect in rects:
            self._collect(rect_aabb(rect), found, seen)
        return found

    def _collect(self, aabb, found, seen) -> None:
        for key in _bucket_keys(aabb, self.cell):
            bucket = self._buckets.get(key)
            if not bucket:
                continue
            for item in bucket:
                marker = id(item)
                if marker in seen:
                    continue
                seen.add(marker)
                found.append(item)


class RouteWorld:
    """一次重算的绕障索引：附近卡片、附近已有线，以及汇入同一终点的线。"""

    def __init__(self, card_rects):
        self.cards = RouteIndex()
        self.wires = RouteIndex()
        self.wires_to_end: Dict[int, List[ExistingPath]] = {}
        if card_rects is None:
            raise TypeError("卡片矩形索引不能为空")
        for marker, rect in card_rects.items():
            typed = _as_rect(rect)
            self.cards.insert(rect_aabb(typed), (marker, typed))

    def add_wire(self, record: ExistingPath, end_marker: int) -> None:
        if not isinstance(record, ExistingPath):
            raise TypeError("已有连线必须是 ExistingPath")
        self.wires.insert(record.aabb, record)
        bucket = self.wires_to_end.get(end_marker)
        if bucket is None:
            self.wires_to_end[end_marker] = [record]
        else:
            bucket.append(record)

    def nearby(self, start_pt, end_pt, start_marker, end_marker):
        start = _as_point(start_pt)
        end = _as_point(end_pt)
        corridors = corridor_rects(start, end, ROUTE_QUERY_PAD)
        obstacles: List[Rect] = []
        for marker, rect in self.cards.query_rects(corridors):
            if marker != start_marker and marker != end_marker:
                obstacles.append(rect)
        existing = self.wires.query_rects(corridors)
        seen = {id(item) for item in existing}
        for record in self.wires_to_end.get(end_marker, ()):
            marker = id(record)
            if marker in seen:
                continue
            seen.add(marker)
            existing.append(record)
        return obstacles, existing

    def obstacles(self, start_pt, end_pt, start_marker, end_marker) -> List[Rect]:
        obstacles, _existing = self.nearby(start_pt, end_pt, start_marker, end_marker)
        return obstacles

    def existing(self, start_pt, end_pt, end_marker) -> List[ExistingPath]:
        _obstacles, existing = self.nearby(start_pt, end_pt, None, end_marker)
        return existing


def point_to_cell(x: float, y: float) -> Cell:
    return (math.floor(x / GRID_CELL), math.floor(y / GRID_CELL))


def cell_center(cell: Cell) -> Point:
    cx, cy = cell
    return ((cx + 0.5) * GRID_CELL, (cy + 0.5) * GRID_CELL)


def inflate_rect(rect: Rect, padding: float = OBSTACLE_INFLATE) -> Rect:
    x, y, w, h = rect
    return (x - padding, y - padding, w + 2.0 * padding, h + 2.0 * padding)


def start_end_stacked(start_rect, end_rect, obstacles) -> bool:
    """起点或终点卡片是否叠上或贴上其它卡片。"""
    start = inflate_rect(_as_rect(start_rect), OBSTACLE_INFLATE) if start_rect is not None else None
    end = inflate_rect(_as_rect(end_rect), OBSTACLE_INFLATE) if end_rect is not None else None
    if start is None and end is None:
        return False
    for raw in obstacles:
        rect = _as_rect(raw)
        if start is not None and _rects_overlap(start, rect):
            return True
        if end is not None and _rects_overlap(end, rect):
            return True
    return False


def cells_along_polyline(points: Sequence[Point]) -> Set[Cell]:
    """返回正交折线覆盖的网格格子，供后续连线占用。"""
    cells: Set[Cell] = set()
    if not points:
        return cells
    cleaned = [_as_point(p) for p in points]
    for start, end in zip(cleaned, cleaned[1:]):
        cells.update(_cells_along_segment(start, end))
    if not cells:
        cells.add(point_to_cell(*cleaned[0]))
    return cells


def interior_cells_along_polyline(points: Sequence[Point]) -> Set[Cell]:
    """去掉两端端口格子后的占用格，端口格可共享，走廊不可再走。"""
    cleaned = [_as_point(p) for p in points]
    cells = cells_along_polyline(cleaned)
    if not cleaned:
        return set()
    cells.discard(point_to_cell(*cleaned[0]))
    cells.discard(point_to_cell(*cleaned[-1]))
    return cells


def _unique_polyline(points: Sequence[Point]) -> List[Point]:
    unique: List[Point] = []
    for raw in points:
        point = _as_point(raw)
        if unique and _same_point(unique[-1], point):
            continue
        unique.append(point)
    return unique


def _coincident_port_path(port: Point) -> List[Point]:
    """输出口和输入口重合时画一小段正交回路，避免零长度折线。"""
    x, y = _as_point(port)
    stub = PORT_STUB
    return [
        (x, y),
        (x + stub, y),
        (x + stub, y + stub),
        (x, y + stub),
        (x, y),
    ]


def _finalize_path(points: Sequence[Point]) -> List[Point]:
    """去掉重合点后做正交化简，避免口边留下重复顶点。"""
    cleaned = _unique_polyline(points)
    if len(cleaned) < 2:
        if not cleaned:
            raise ValueError("连线路径点不足")
        return _coincident_port_path(cleaned[0])
    simplified = simplify_orthogonal(cleaned)
    if len(_unique_polyline(simplified)) < 2:
        return _coincident_port_path(cleaned[0])
    return simplified


def simplify_orthogonal(points: Sequence[Point]) -> List[Point]:
    """去掉重合点与共线中间点，路径必须已经是正交折线。"""
    cleaned: List[Point] = []
    for raw in points:
        point = _as_point(raw)
        if cleaned and _same_point(cleaned[-1], point):
            continue
        if cleaned and not _axis_aligned(cleaned[-1], point):
            raise ValueError("连线路径必须是水平或垂直折线")
        cleaned.append(point)
    if len(cleaned) <= 2:
        return cleaned
    simplified = [cleaned[0]]
    for index in range(1, len(cleaned) - 1):
        if _collinear(simplified[-1], cleaned[index], cleaned[index + 1]):
            continue
        simplified.append(cleaned[index])
    simplified.append(cleaned[-1])
    return simplified


def path_hits_obstacles(points: Sequence[Point], obstacles: Sequence[Rect]) -> bool:
    """折线是否与卡片原始矩形的 10px 外扩区域相交。"""
    if len(points) < 2:
        return False
    inflated = [inflate_rect(_as_rect(rect)) for rect in obstacles]
    cleaned = [_as_point(p) for p in points]
    for start, end in zip(cleaned, cleaned[1:]):
        if _same_point(start, end):
            continue
        if not _axis_aligned(start, end):
            raise ValueError("连线路径必须是水平或垂直折线")
        for rect in inflated:
            if _segment_hits_rect(start, end, rect):
                return True
    return False


def path_enters_card_bodies(points: Sequence[Point], obstacles: Sequence[Rect]) -> bool:
    """折线是否进入卡片原始矩形的开区间内部。贴边不算穿过。"""
    return _path_enters_foreign_bodies(points, obstacles, None, None)


def incoming_approach_cells(points: Sequence[Point]) -> Set[Cell]:
    """输入端靠近端口的一小段可共用；长距离竖直接入的走廊不可再被别的线占用。"""
    cleaned = [_as_point(p) for p in points]
    if len(cleaned) < 2:
        return set()
    last = cleaned[-1]
    prev = cleaned[-2]
    if abs(last[0] - prev[0]) < _EPS:
        span = min(PORT_STUB, abs(prev[1] - last[1]))
        direction = 1.0 if prev[1] > last[1] else -1.0
        return _cells_along_segment(last, (last[0], last[1] + direction * span))
    cells = _cells_along_segment(prev, last)
    if len(cleaned) >= 3:
        last_horizontal = abs(last[1] - prev[1]) < _EPS
        prev_vertical = abs(prev[0] - cleaned[-3][0]) < _EPS
        if last_horizontal and prev_vertical:
            corner = prev
            far = cleaned[-3]
            span = min(INCOMING_SHARE, abs(far[1] - corner[1]))
            direction = -1.0 if far[1] < corner[1] else 1.0
            limited = (corner[0], corner[1] + direction * span)
            cells.update(_cells_along_segment(corner, limited))
    return cells


def _arrives_at_end(
    path: Sequence[Point],
    end_pt: Optional[Point],
    end_card: Optional[Rect],
) -> bool:
    path = _path_points(path)
    if not path:
        return False
    last = _as_point(path[-1])
    if end_pt is not None and _same_point(last, end_pt):
        return True
    if end_pt is None or end_card is None:
        return False
    _x, y, _w, h = end_card
    return (
        abs(last[0] - end_pt[0]) <= PORT_STUB + GRID_CELL
        and y - GRID_CELL <= last[1] <= y + h + GRID_CELL
    )


def paths_conflict(left, right, end_pt=None, end_card=None) -> bool:
    """垂直交叉必须绕开。汇入同一张卡片时共线重叠走同一路径；其它共线重叠只允许进端口短桩。"""
    a = [_as_point(p) for p in _path_points(left)]
    b = [_as_point(p) for p in _path_points(right)]
    box_a = _polyline_aabb(a)
    box_b = _polyline_aabb(b)
    if box_a is not None and box_b is not None and not _aabb_overlap(box_a, box_b):
        return False
    if _paths_perpendicular_cross(a, b):
        return True
    overlap = interior_cells_along_polyline(a) & interior_cells_along_polyline(b)
    if not overlap:
        return False
    dest = None if end_pt is None else _as_point(end_pt)
    card = None if end_card is None else _as_rect(end_card)
    if _arrives_at_end(a, dest, card) and _arrives_at_end(b, dest, card):
        return False
    shareable = incoming_approach_cells(a) | incoming_approach_cells(b)
    for point in _shared_endpoints(a, b):
        incoming = _same_point(point, a[-1]) or _same_point(point, b[-1])
        if incoming:
            shareable.update(_cells_along_segment(point, (point[0] - PORT_STUB, point[1])))
        else:
            shareable.update(_cells_along_segment(point, (point[0] + PORT_STUB, point[1])))
    return bool(overlap.difference(shareable))


def path_crosses_path(left, right) -> bool:
    """两条正交折线是否交叉或共线重叠。仅在端点相触不算穿过。

    汇入同一端口时，接入短桩上的共线重叠不算穿过。
    """
    a = [_as_point(p) for p in _path_points(left)]
    b = [_as_point(p) for p in _path_points(right)]
    if len(a) < 2 or len(b) < 2:
        return False
    box_a = _polyline_aabb(a)
    box_b = _polyline_aabb(b)
    if box_a is not None and box_b is not None and not _aabb_overlap(box_a, box_b):
        return False
    shared_ends = _shared_endpoints(a, b)
    for s0, s1 in zip(a, a[1:]):
        if _same_point(s0, s1):
            continue
        for t0, t1 in zip(b, b[1:]):
            if _same_point(t0, t1):
                continue
            if not _segments_cross_or_overlap(s0, s1, t0, t1):
                continue
            if shared_ends and _overlap_is_shared_stub(s0, s1, t0, t1, shared_ends):
                continue
            return True
    return False


def preview_drag_connection(
    start,
    end,
    *,
    incoming: bool = False,
    end_face_x: Optional[float] = None,
) -> List[Point]:
    """拉线预览用的正交折线：只跟端口和光标，不绕障、不自检。"""
    start_pt = _as_point(start)
    end_pt = _as_point(end)
    del incoming, end_face_x
    if _same_point(start_pt, end_pt):
        return _coincident_port_path(start_pt)
    points = [start_pt]
    dx = end_pt[0] - start_pt[0]
    dy = end_pt[1] - start_pt[1]
    mouth = PORT_STUB + GRID_CELL
    if abs(dy) > abs(dx) and -_EPS <= dx <= mouth:
        elbow = (end_pt[0], start_pt[1])
    elif dx < _EPS or abs(dy) > abs(dx):
        elbow = (start_pt[0], end_pt[1])
    else:
        elbow = (end_pt[0], start_pt[1])
    if not _same_point(points[-1], elbow):
        points.append(elbow)
    if not _same_point(points[-1], end_pt):
        points.append(end_pt)
    simplified = simplify_orthogonal(points)
    unique: List[Point] = []
    for point in simplified:
        if unique and _same_point(unique[-1], point):
            continue
        unique.append(point)
    if len(unique) < 2:
        return [start_pt, end_pt] if _axis_aligned(start_pt, end_pt) else [start_pt, elbow, end_pt]
    return unique


def route_connection(
    start,
    end,
    obstacles,
    *,
    occupied=None,
    existing=None,
    start_rect=None,
    end_rect=None,
) -> List[Point]:
    """计算从输出端口到输入端口的正交折线。

    start / end 为场景坐标。输出端沿端口高度水平直出，输入端沿端口 x 直进，
    口边不再额外横折。
    obstacles、start_rect、end_rect 均为卡片原始矩形 (x, y, w, h)，
    其它卡片按 10px 外扩后再作为障碍。
    其它卡片的端口短桩外围加绕行代价，避免贴着邻卡接入段走。
    occupied 为已被既有连线占用的网格格子，绕行时加代价。
    existing 为已有连线折线，禁止穿过。
    起点/终点卡片除整条出边走廊外整张阻挡；其它卡片整张阻挡。
    出边走廊是卡片出边向外 20px、高度为卡片外扩后全高，被挡住时
    沿边向上/下离开，不把端口和远处可走格用 L 形硬折。
    搜索范围以本线两端和已有折线为界再外扩，不把整张画布都纳入。
    仍无路径则失败。
    """
    start_pt = _as_point(start)
    end_pt = _as_point(end)
    other_rects = [_as_rect(rect) for rect in obstacles]
    start_card = _as_rect(start_rect) if start_rect is not None else None
    end_card = _as_rect(end_rect) if end_rect is not None else None
    existing_paths = _as_existing_paths(existing)
    search_box = _inflate_aabb(_polyline_aabb([start_pt, end_pt]), SEARCH_MARGINS[-1] + PORT_STUB)
    local_existing: List[ExistingPath] = []
    prefer_cells: Set[Cell] = set()
    for other in existing_paths:
        arrives = _arrives_at_end(other.points, end_pt, end_card)
        nearby = (
            search_box is None
            or other.aabb is None
            or _aabb_overlap(search_box, other.aabb)
        )
        if not arrives and not nearby:
            continue
        local_existing.append(other)
        if arrives:
            prefer_cells.update(other.interior)
    occupied_cells: Set[Cell] = set()
    if local_existing:
        for other in local_existing:
            occupied_cells.update(other.interior)
    else:
        occupied_cells.update(_as_occupied(occupied))
    occupied_cells.difference_update(_own_stub_cells(start_pt, end_pt))
    for other in local_existing:
        occupied_cells.difference_update(other.approach)
        if _arrives_at_end(other.points, end_pt, end_card):
            occupied_cells.difference_update(other.interior)
    local_rects = _rects_overlapping_aabb(other_rects, search_box)

    start_stub = start_pt
    end_stub = end_pt

    direct = preview_drag_connection(
        start_pt,
        end_pt,
        incoming=end_card is not None,
        end_face_x=None if end_card is None else end_card[0],
    )
    if _direct_route_usable(
        direct, local_rects, start_card, end_card, occupied_cells, local_existing
    ):
        return _finalize_path(
            _flatten_short_stairs(
                direct,
                start_card,
                end_card,
                local_rects,
                start_pt,
                end_pt,
                occupied_cells,
                local_existing,
                True,
            )
        )

    stacked = start_end_stacked(start_card, end_card, local_rects)
    margins = (SEARCH_MARGINS[-1],) if stacked else SEARCH_MARGINS
    path = None
    for margin in margins:
        path = _route_with_margin(
            start_pt,
            end_pt,
            start_stub,
            end_stub,
            local_rects,
            start_card,
            end_card,
            occupied_cells,
            local_existing,
            margin,
            prefer_cells,
            skip_strict=stacked,
        )
        if path is not None:
            break
    if path is None:
        raise RuntimeError("无法为连线找到绕开卡片和已有连线的正交路径")

    pierce_rects = list(local_rects)
    if start_card is not None:
        pierce_rects.append(start_card)
    if end_card is not None:
        pierce_rects.append(end_card)
    if _path_enters_foreign_bodies(
        path, pierce_rects, start_card, end_card, start_pt=start_pt, end_pt=end_pt
    ):
        raise RuntimeError("连线路由结果穿过了卡片障碍，属于实现错误")
    if _path_crosses_existing(path, local_existing, end_pt, end_card):
        raise RuntimeError("连线路由结果穿过了已有连线，属于实现错误")
    return _finalize_path(path)


def _direct_route_usable(
    path: Sequence[Point],
    other_rects: Sequence[Rect],
    start_card: Optional[Rect],
    end_card: Optional[Rect],
    occupied_cells: Set[Cell],
    existing_paths: Sequence[Sequence[Point]],
) -> bool:
    if len(_unique_polyline(path)) < 2:
        return False
    if path[1][0] < path[0][0] - _EPS:
        return False
    pierce_rects = list(other_rects)
    if start_card is not None:
        pierce_rects.append(start_card)
    if end_card is not None:
        pierce_rects.append(end_card)
    if _path_enters_foreign_bodies(
        path, pierce_rects, start_card, end_card, start_pt=path[0], end_pt=path[-1]
    ):
        return False
    foreign_keepout = [
        inflate_rect(rect, max(0.0, PORT_STUB - OBSTACLE_INFLATE))
        for rect in other_rects
    ]
    if foreign_keepout and path_hits_obstacles(path, foreign_keepout):
        return False
    terminals = [rect for rect in (start_card, end_card) if rect is not None]
    if len(path) > 2:
        interior = path[1:-1]
        if len(interior) >= 2 and _path_enters_foreign_bodies(interior, terminals, None, None):
            return False
    if occupied_cells and interior_cells_along_polyline(path) & occupied_cells:
        return False
    if _path_crosses_existing(path, existing_paths, path[-1], end_card):
        return False
    return True


def _as_point(value) -> Point:
    if isinstance(value, tuple) and len(value) == 2:
        x, y = value
        if isinstance(x, float) and isinstance(y, float) and math.isfinite(x) and math.isfinite(y):
            return value
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise TypeError("坐标必须是 (x, y)")
    x = float(value[0])
    y = float(value[1])
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("坐标必须是有限数字")
    return (x, y)


def _as_rect(value) -> Rect:
    if isinstance(value, tuple) and len(value) == 4:
        x, y, w, h = value
        if (
            isinstance(x, float)
            and isinstance(y, float)
            and isinstance(w, float)
            and isinstance(h, float)
            and math.isfinite(x)
            and math.isfinite(y)
            and math.isfinite(w)
            and math.isfinite(h)
            and w >= 0
            and h >= 0
        ):
            return value
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        raise TypeError("矩形必须是 (x, y, w, h)")
    x, y, w, h = (float(part) for part in value)
    if not all(math.isfinite(part) for part in (x, y, w, h)):
        raise ValueError("矩形必须是有限数字")
    if w < 0 or h < 0:
        raise ValueError("矩形宽高不能为负")
    return (x, y, w, h)


def _as_occupied(occupied) -> Set[Cell]:
    if occupied is None:
        return set()
    if isinstance(occupied, set):
        return occupied
    cells: Set[Cell] = set()
    keys = occupied.keys() if isinstance(occupied, dict) else occupied
    for item in keys:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise TypeError("占用格子必须是 (cx, cy)")
        cells.add((int(item[0]), int(item[1])))
    return cells


def _as_existing_paths(existing) -> List[ExistingPath]:
    if existing is None:
        return []
    if not existing:
        return []
    if isinstance(existing[0], ExistingPath):
        return existing
    return [ExistingPath(item) for item in existing]


def _path_crosses_existing(
    path: Sequence[Point],
    existing_paths: Sequence[ExistingPath],
    end_pt: Optional[Point] = None,
    end_card: Optional[Rect] = None,
) -> bool:
    path_pts = [_as_point(p) for p in _path_points(path)]
    path_box = _polyline_aabb(path_pts)
    for other in existing_paths:
        other_pts = other.points if isinstance(other, ExistingPath) else _path_points(other)
        other_box = other.aabb if isinstance(other, ExistingPath) else _polyline_aabb(other_pts)
        if path_box is not None and other_box is not None and not _aabb_overlap(path_box, other_box):
            continue
        if paths_conflict(path_pts, other_pts, end_pt=end_pt, end_card=end_card):
            return True
    return False


def _open_intervals_overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    lo = max(min(a0, a1), min(b0, b1))
    hi = min(max(a0, a1), max(b0, b1))
    return hi - lo > _EPS


def _segments_cross_or_overlap(a0: Point, a1: Point, b0: Point, b1: Point) -> bool:
    if not _axis_aligned(a0, a1) or not _axis_aligned(b0, b1):
        raise ValueError("连线路径必须是水平或垂直折线")
    a_horizontal = abs(a0[1] - a1[1]) < _EPS
    b_horizontal = abs(b0[1] - b1[1]) < _EPS
    if a_horizontal and b_horizontal:
        if abs(a0[1] - b0[1]) >= _EPS:
            return False
        return _open_intervals_overlap(a0[0], a1[0], b0[0], b1[0])
    if not a_horizontal and not b_horizontal:
        if abs(a0[0] - b0[0]) >= _EPS:
            return False
        return _open_intervals_overlap(a0[1], a1[1], b0[1], b1[1])
    return _segments_perpendicular_cross(a0, a1, b0, b1)


def _segments_perpendicular_cross(a0: Point, a1: Point, b0: Point, b1: Point) -> bool:
    a_horizontal = abs(a0[1] - a1[1]) < _EPS
    b_horizontal = abs(b0[1] - b1[1]) < _EPS
    if a_horizontal == b_horizontal:
        return False
    if a_horizontal:
        y = a0[1]
        x0, x1 = (a0[0], a1[0]) if a0[0] <= a1[0] else (a1[0], a0[0])
        x = b0[0]
        y0, y1 = (b0[1], b1[1]) if b0[1] <= b1[1] else (b1[1], b0[1])
    else:
        y = b0[1]
        x0, x1 = (b0[0], b1[0]) if b0[0] <= b1[0] else (b1[0], b0[0])
        x = a0[0]
        y0, y1 = (a0[1], a1[1]) if a0[1] <= a1[1] else (a1[1], a0[1])
    return (x0 + _EPS < x < x1 - _EPS) and (y0 + _EPS < y < y1 - _EPS)


def _paths_perpendicular_cross(left: Sequence[Point], right: Sequence[Point]) -> bool:
    a = [_as_point(p) for p in left]
    b = [_as_point(p) for p in right]
    if len(a) < 2 or len(b) < 2:
        return False
    for s0, s1 in zip(a, a[1:]):
        if _same_point(s0, s1):
            continue
        for t0, t1 in zip(b, b[1:]):
            if _same_point(t0, t1):
                continue
            if _segments_perpendicular_cross(s0, s1, t0, t1):
                return True
    return False


def _same_point(left: Point, right: Point) -> bool:
    return abs(left[0] - right[0]) < _EPS and abs(left[1] - right[1]) < _EPS


def _axis_aligned(left: Point, right: Point) -> bool:
    return abs(left[0] - right[0]) < _EPS or abs(left[1] - right[1]) < _EPS


def _collinear(a: Point, b: Point, c: Point) -> bool:
    return (
        abs(a[0] - b[0]) < _EPS and abs(b[0] - c[0]) < _EPS
    ) or (
        abs(a[1] - b[1]) < _EPS and abs(b[1] - c[1]) < _EPS
    )


def _rects_overlap(left: Rect, right: Rect) -> bool:
    ax, ay, aw, ah = left
    bx, by, bw, bh = right
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def _segment_hits_rect(start: Point, end: Point, rect: Rect) -> bool:
    rx, ry, rw, rh = rect
    x1, y1 = start
    x2, y2 = end
    if abs(y1 - y2) < _EPS:
        if y1 < ry or y1 > ry + rh:
            return False
        return min(x1, x2) <= rx + rw and max(x1, x2) >= rx
    if abs(x1 - x2) < _EPS:
        if x1 < rx or x1 > rx + rw:
            return False
        return min(y1, y2) <= ry + rh and max(y1, y2) >= ry
    raise ValueError("连线路径必须是水平或垂直折线")


def _segment_enters_rect_open(start: Point, end: Point, rect: Rect) -> bool:
    rx, ry, rw, rh = rect
    if rw <= _EPS or rh <= _EPS:
        return False
    x1, y1 = start
    x2, y2 = end
    rx1 = rx + rw
    ry1 = ry + rh
    if abs(y1 - y2) < _EPS:
        if y1 <= ry or y1 >= ry1:
            return False
        lo, hi = (x1, x2) if x1 <= x2 else (x2, x1)
        return lo < rx1 and hi > rx
    if abs(x1 - x2) < _EPS:
        if x1 <= rx or x1 >= rx1:
            return False
        lo, hi = (y1, y2) if y1 <= y2 else (y2, y1)
        return lo < ry1 and hi > ry
    raise ValueError("连线路径必须是水平或垂直折线")


def _open_overlap(a0: float, a1: float, b0: float, b1: float) -> Optional[Tuple[float, float]]:
    lo = max(min(a0, a1), b0)
    hi = min(max(a0, a1), b1)
    if hi - lo <= _EPS:
        return None
    return (lo, hi)


def _covers_open_interval(lo: float, hi: float, spans: Sequence[Tuple[float, float]]) -> bool:
    if hi - lo <= _EPS:
        return True
    cursor = lo
    for start, end in sorted(spans):
        if end <= cursor + _EPS:
            continue
        if start > cursor + _EPS:
            return False
        cursor = max(cursor, end)
        if cursor >= hi - _EPS:
            return True
    return cursor >= hi - _EPS


def _allowed_spans_along_axis(
    axis_value: float,
    horizontal: bool,
    allowed: Sequence[Rect],
) -> List[Tuple[float, float]]:
    spans: List[Tuple[float, float]] = []
    for rx, ry, rw, rh in allowed:
        if horizontal:
            if axis_value < ry or axis_value > ry + rh:
                continue
            spans.append((rx, rx + rw))
        else:
            if axis_value < rx or axis_value > rx + rw:
                continue
            spans.append((ry, ry + rh))
    return spans


def _segment_hits_foreign(
    start: Point,
    end: Point,
    obstacle: Rect,
    allowed: Sequence[Rect],
) -> bool:
    if not _segment_enters_rect_open(start, end, obstacle):
        return False
    ox, oy, ow, oh = obstacle
    ox1 = ox + ow
    oy1 = oy + oh
    x1, y1 = start
    x2, y2 = end
    if abs(y1 - y2) < _EPS:
        overlap = _open_overlap(x1, x2, ox, ox1)
        if overlap is None:
            return False
        return not _covers_open_interval(
            overlap[0],
            overlap[1],
            _allowed_spans_along_axis(y1, True, allowed),
        )
    overlap = _open_overlap(y1, y2, oy, oy1)
    if overlap is None:
        return False
    return not _covers_open_interval(
        overlap[0],
        overlap[1],
        _allowed_spans_along_axis(x1, False, allowed),
    )


def _path_enters_foreign_bodies(
    points: Sequence[Point],
    obstacles: Sequence[Rect],
    start_card: Optional[Rect],
    end_card: Optional[Rect],
    *,
    start_pt: Optional[Point] = None,
    end_pt: Optional[Point] = None,
) -> bool:
    if len(points) < 2 or not obstacles:
        return False
    cleaned = [_as_point(p) for p in points]
    typed_obstacles = [_as_rect(rect) for rect in obstacles]
    for start, end in zip(cleaned, cleaned[1:]):
        if _same_point(start, end):
            continue
        if not _axis_aligned(start, end):
            raise ValueError("连线路径必须是水平或垂直折线")
        seg_box = (
            min(start[0], end[0]),
            min(start[1], end[1]),
            max(start[0], end[0]),
            max(start[1], end[1]),
        )
        allowed: List[Rect] = []
        if (
            start_card is not None
            and start_pt is not None
            and (_same_point(start, start_pt) or _same_point(end, start_pt))
        ):
            allowed.append(start_card)
        if (
            end_card is not None
            and end_pt is not None
            and (_same_point(start, end_pt) or _same_point(end, end_pt))
        ):
            other = end if _same_point(start, end_pt) else start
            if other[0] <= end_pt[0] + GRID_CELL:
                allowed.append(end_card)
        for rect in typed_obstacles:
            rx, ry, rw, rh = rect
            if not _aabb_overlap(seg_box, (rx, ry, rx + rw, ry + rh)):
                continue
            if _segment_hits_foreign(start, end, rect, allowed):
                return True
    return False


def _shared_endpoints(left: Sequence[Point], right: Sequence[Point]) -> List[Point]:
    shared: List[Point] = []
    for point in (left[0], left[-1]):
        if _same_point(point, right[0]) or _same_point(point, right[-1]):
            shared.append(point)
    return shared


def _segment_overlap_points(a0: Point, a1: Point, b0: Point, b1: Point) -> Optional[Tuple[Point, Point]]:
    if not _axis_aligned(a0, a1) or not _axis_aligned(b0, b1):
        raise ValueError("连线路径必须是水平或垂直折线")
    a_horizontal = abs(a0[1] - a1[1]) < _EPS
    b_horizontal = abs(b0[1] - b1[1]) < _EPS
    if a_horizontal != b_horizontal:
        return None
    if a_horizontal:
        if abs(a0[1] - b0[1]) >= _EPS:
            return None
        lo = max(min(a0[0], a1[0]), min(b0[0], b1[0]))
        hi = min(max(a0[0], a1[0]), max(b0[0], b1[0]))
        if hi - lo <= _EPS:
            return None
        y = a0[1]
        return ((lo, y), (hi, y))
    if abs(a0[0] - b0[0]) >= _EPS:
        return None
    lo = max(min(a0[1], a1[1]), min(b0[1], b1[1]))
    hi = min(max(a0[1], a1[1]), max(b0[1], b1[1]))
    if hi - lo <= _EPS:
        return None
    x = a0[0]
    return ((x, lo), (x, hi))


def _overlap_is_shared_stub(
    a0: Point,
    a1: Point,
    b0: Point,
    b1: Point,
    shared_ends: Sequence[Point],
) -> bool:
    overlap = _segment_overlap_points(a0, a1, b0, b1)
    if overlap is None:
        return False
    left, right = overlap
    stub = PORT_STUB + GRID_CELL
    for end in shared_ends:
        if (
            abs(left[0] - end[0]) <= stub + _EPS
            and abs(left[1] - end[1]) <= stub + _EPS
            and abs(right[0] - end[0]) <= stub + _EPS
            and abs(right[1] - end[1]) <= stub + _EPS
        ):
            return True
    return False


def _own_stub_cells(start_pt: Point, end_pt: Point) -> Set[Cell]:
    """当前连线离开输出端口的格子和输入端口格子，可与已有线共享。"""
    cells = _cells_along_segment(start_pt, (start_pt[0] + PORT_STUB, start_pt[1]))
    cells.update(_cells_along_segment(start_pt, (start_pt[0], start_pt[1] - PORT_STUB)))
    cells.update(_cells_along_segment(start_pt, (start_pt[0], start_pt[1] + PORT_STUB)))
    cells.add(point_to_cell(*end_pt))
    return cells


def _cells_along_segment(start: Point, end: Point) -> Set[Cell]:
    if _same_point(start, end):
        return {point_to_cell(*start)}
    if not _axis_aligned(start, end):
        raise ValueError("连线路径必须是水平或垂直折线")
    cells: Set[Cell] = set()
    if abs(start[1] - end[1]) < _EPS:
        cy = math.floor(start[1] / GRID_CELL)
        x0, x1 = (start[0], end[0]) if start[0] <= end[0] else (end[0], start[0])
        cx0 = math.floor(x0 / GRID_CELL)
        cx1 = math.floor(x1 / GRID_CELL)
        for cx in range(cx0, cx1 + 1):
            cells.add((cx, cy))
        return cells
    cx = math.floor(start[0] / GRID_CELL)
    y0, y1 = (start[1], end[1]) if start[1] <= end[1] else (end[1], start[1])
    cy0 = math.floor(y0 / GRID_CELL)
    cy1 = math.floor(y1 / GRID_CELL)
    for cy in range(cy0, cy1 + 1):
        cells.add((cx, cy))
    return cells


def _cell_rect(cell: Cell) -> Rect:
    cx, cy = cell
    return (cx * GRID_CELL, cy * GRID_CELL, GRID_CELL, GRID_CELL)


def _cells_overlapping_rect(
    rect: Rect,
    bounds: Optional[Tuple[int, int, int, int]] = None,
) -> Set[Cell]:
    """返回与矩形闭区间相交的网格格；可裁到搜索边界。"""
    x, y, w, h = rect
    if w <= _EPS or h <= _EPS:
        return set()
    cx0 = math.floor(x / GRID_CELL)
    cy0 = math.floor(y / GRID_CELL)
    cx1 = math.ceil((x + w) / GRID_CELL) - 1
    cy1 = math.ceil((y + h) / GRID_CELL) - 1
    if bounds is not None:
        min_cx, min_cy, max_cx, max_cy = bounds
        cx0 = max(cx0, min_cx)
        cy0 = max(cy0, min_cy)
        cx1 = min(cx1, max_cx)
        cy1 = min(cy1, max_cy)
    if cx1 < cx0 or cy1 < cy0:
        return set()
    cells: Set[Cell] = set()
    for cx in range(cx0, cx1 + 1):
        for cy in range(cy0, cy1 + 1):
            cells.add((cx, cy))
    return cells


def _in_bounds(cell: Cell, bounds: Tuple[int, int, int, int]) -> bool:
    cx, cy = cell
    min_cx, min_cy, max_cx, max_cy = bounds
    return min_cx <= cx <= max_cx and min_cy <= cy <= max_cy


def _face_corridor(card: Rect, going_right: bool, port: Optional[Point] = None) -> Rect:
    inflated = inflate_rect(card)
    width = 2.0 * GRID_CELL
    if going_right:
        left = card[0] + card[2]
        if port is not None:
            left = min(left, port[0])
        right = card[0] + card[2] + width
        return (left, inflated[1], max(width, right - left), inflated[3])
    left = card[0] - width
    right = card[0]
    if port is not None:
        right = max(right, port[0] + GRID_CELL)
    else:
        right = card[0] + width
    return (left, inflated[1], max(width, right - left), inflated[3])


def _collect_extent_points(
    start_pt: Point,
    end_pt: Point,
    start_stub: Point,
    end_stub: Point,
    other_rects: Sequence[Rect],
    start_card: Optional[Rect],
    end_card: Optional[Rect],
    existing_paths: Sequence[Sequence[Point]],
) -> Tuple[List[Point], List[Rect]]:
    points = [start_pt, end_pt, start_stub, end_stub]
    rects: List[Rect] = []
    if start_card is not None:
        rects.append(start_card)
    if end_card is not None:
        rects.append(end_card)
    return points, rects


def _search_bounds(points: Sequence[Point], rects: Sequence[Rect], margin: float) -> Tuple[int, int, int, int]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    for x, y, w, h in rects:
        xs.append(x)
        xs.append(x + w)
        ys.append(y)
        ys.append(y + h)
    min_x = min(xs) - margin
    min_y = min(ys) - margin
    max_x = max(xs) + margin
    max_y = max(ys) + margin
    min_cx = math.floor(min_x / GRID_CELL)
    min_cy = math.floor(min_y / GRID_CELL)
    max_cx = math.floor(max_x / GRID_CELL)
    max_cy = math.floor(max_y / GRID_CELL)
    if max_cx - min_cx < 2:
        max_cx = min_cx + 2
    if max_cy - min_cy < 2:
        max_cy = min_cy + 2
    return (min_cx, min_cy, max_cx, max_cy)


def _world_rect_from_bounds(bounds: Tuple[int, int, int, int]) -> Rect:
    min_cx, min_cy, max_cx, max_cy = bounds
    return (
        min_cx * GRID_CELL,
        min_cy * GRID_CELL,
        (max_cx - min_cx + 1) * GRID_CELL,
        (max_cy - min_cy + 1) * GRID_CELL,
    )


def _make_blocker(
    other_rects: Sequence[Rect],
    start_card: Optional[Rect],
    end_card: Optional[Rect],
    bounds: Tuple[int, int, int, int],
    start_pt: Optional[Point] = None,
    end_pt: Optional[Point] = None,
    corridors: Optional[Sequence[Rect]] = None,
):
    world = _world_rect_from_bounds(bounds)
    blocked_cells: Set[Cell] = set()
    keepout_cells: Set[Cell] = set()
    for rect in other_rects:
        inflated = inflate_rect(rect)
        if _rects_overlap(inflated, world):
            blocked_cells.update(_cells_overlapping_rect(inflated, bounds))
        keepout_rect = inflate_rect(rect, PORT_STUB)
        if _rects_overlap(keepout_rect, world):
            keepout_cells.update(_cells_overlapping_rect(keepout_rect, bounds))
    if start_card is not None:
        start_blocked = _cells_overlapping_rect(inflate_rect(start_card), bounds)
        start_corridor = _face_corridor(start_card, True, start_pt)
        start_blocked.difference_update(_cells_overlapping_rect(start_corridor, bounds))
        blocked_cells.update(start_blocked)
    if end_card is not None:
        end_blocked = _cells_overlapping_rect(inflate_rect(end_card), bounds)
        end_corridor = _face_corridor(end_card, False, end_pt)
        end_blocked.difference_update(_cells_overlapping_rect(end_corridor, bounds))
        blocked_cells.update(end_blocked)
    if end_pt is not None and end_card is not None:
        mouth = (
            min(end_card[0], end_pt[0]) - 4.0 * GRID_CELL,
            end_card[1] - 4.0 * GRID_CELL,
            8.0 * GRID_CELL,
            end_card[3] + 8.0 * GRID_CELL,
        )
        mouth_limit = end_pt[0] - GRID_CELL
        for cell in _cells_overlapping_rect(mouth, bounds):
            cx, _cy = cell_center(cell)
            if cx < mouth_limit:
                keepout_cells.add(cell)
    keepout_cells.difference_update(blocked_cells)
    if corridors:
        walkable_cells: Set[Cell] = set()
        for rect in corridors:
            walkable_cells.update(_cells_overlapping_rect(rect, bounds))
        walkable_cells.difference_update(blocked_cells)

        def blocked(cell: Cell) -> bool:
            return cell not in walkable_cells

    else:

        def blocked(cell: Cell) -> bool:
            return cell in blocked_cells

    def keepout(cell: Cell) -> bool:
        return cell in keepout_cells

    return blocked, keepout


def _leave_dir(start_pt: Point, end_pt: Point) -> int:
    dx = end_pt[0] - start_pt[0]
    dy = end_pt[1] - start_pt[1]
    if abs(dy) > abs(dx) or dx < _EPS:
        return _DIR_NORTH if dy < 0 else _DIR_SOUTH
    return _DIR_EAST


def _neighbor_order(prefer_dir: int) -> List[int]:
    return [prefer_dir] + [index for index in range(4) if index != prefer_dir]


def _cell_is_open(
    cell: Cell,
    blocked,
    bounds: Tuple[int, int, int, int],
    occupied: Set[Cell],
    corridor: Optional[Rect],
) -> bool:
    if not _in_bounds(cell, bounds) or blocked(cell) or cell in occupied:
        return False
    if corridor is None:
        return True
    return _rects_overlap(_cell_rect(cell), corridor)


def _nearest_free_cell(
    origin: Cell,
    blocked,
    bounds: Tuple[int, int, int, int],
    prefer_dir: int,
    corridor: Optional[Rect],
    occupied: Set[Cell],
) -> Optional[Cell]:
    pending = deque([origin])
    seen = {origin}
    order = _neighbor_order(prefer_dir)
    while pending:
        cell = pending.popleft()
        if _cell_is_open(cell, blocked, bounds, occupied, corridor):
            return cell
        for direction in order:
            dx, dy = _DIRECTIONS[direction]
            nxt = (cell[0] + dx, cell[1] + dy)
            if nxt in seen or not _in_bounds(nxt, bounds):
                continue
            seen.add(nxt)
            pending.append(nxt)
    return None


def _pick_terminal_cell(
    point: Point,
    blocked,
    bounds: Tuple[int, int, int, int],
    prefer_dir: int,
    corridor: Optional[Rect],
    occupied: Set[Cell],
) -> Optional[Cell]:
    origin = point_to_cell(*point)
    if _cell_is_open(origin, blocked, bounds, occupied, corridor):
        return origin
    found = _nearest_free_cell(origin, blocked, bounds, prefer_dir, corridor, occupied)
    if found is not None:
        return found
    if _cell_is_open(origin, blocked, bounds, occupied, None):
        return origin
    return _nearest_free_cell(origin, blocked, bounds, prefer_dir, None, occupied)


def _dedupe_orthogonal(points: Sequence[Point]) -> List[Point]:
    cleaned: List[Point] = []
    for point in points:
        if cleaned and _same_point(cleaned[-1], point):
            continue
        if cleaned and not _axis_aligned(cleaned[-1], point):
            raise ValueError("连线路径必须是水平或垂直折线")
        cleaned.append(point)
    return cleaned


def _via_column(port: Point, cell_pt: Point, col_x: float) -> List[Point]:
    return _dedupe_orthogonal([port, (col_x, port[1]), (col_x, cell_pt[1]), cell_pt])


def _via_port_axis(port: Point, cell_pt: Point) -> List[Point]:
    return _dedupe_orthogonal([port, (port[0], cell_pt[1]), cell_pt])


def _link_port_to_cell(
    port: Point,
    cell_pt: Point,
    card: Optional[Rect],
    going_right: bool,
    other_rects: Sequence[Rect],
    start_card: Optional[Rect],
    end_card: Optional[Rect],
    occupied: Set[Cell],
    existing_paths: Sequence[Sequence[Point]],
    block_occupied: bool = True,
    dest_pt: Optional[Point] = None,
) -> Optional[List[Point]]:
    def _usable(candidate: List[Point]) -> bool:
        obstacles = list(other_rects)
        if start_card is not None:
            obstacles.append(start_card)
        if end_card is not None:
            obstacles.append(end_card)
        if _path_enters_foreign_bodies(
            candidate,
            obstacles,
            start_card,
            end_card,
            start_pt=port if going_right else None,
            end_pt=None if going_right else port,
        ):
            return False
        if block_occupied and occupied and interior_cells_along_polyline(candidate) & occupied:
            return False
        return not _path_crosses_existing(candidate, existing_paths, dest_pt, end_card)

    candidates: List[List[Point]] = []
    if going_right:
        if _axis_aligned(port, cell_pt):
            candidates.append(_dedupe_orthogonal([port, cell_pt]))
        if abs(cell_pt[1] - port[1]) > _EPS:
            candidates.append(_via_port_axis(port, cell_pt))
        candidates.append(_via_column(port, cell_pt, cell_pt[0]))
    else:
        if _axis_aligned(port, cell_pt):
            candidates.append(_dedupe_orthogonal([port, cell_pt]))
        candidates.append(_via_port_axis(port, cell_pt))
    for candidate in candidates:
        if _usable(candidate):
            return candidate
    return None


def _pick_port_link(
    port: Point,
    centers: Sequence[Point],
    card: Optional[Rect],
    going_right: bool,
    other_rects: Sequence[Rect],
    start_card: Optional[Rect],
    end_card: Optional[Rect],
    occupied: Set[Cell],
    existing_paths: Sequence[Sequence[Point]],
    block_occupied: bool,
    dest_pt: Optional[Point] = None,
) -> Optional[Tuple[List[Point], int]]:
    """把端口接到 A* 折线。输入沿端口 x 接入，输出沿端口 y 水平直出。"""

    def _link(cell_pt: Point) -> Optional[List[Point]]:
        return _link_port_to_cell(
            port,
            cell_pt,
            card,
            going_right,
            other_rects,
            start_card,
            end_card,
            occupied,
            existing_paths,
            block_occupied=block_occupied,
            dest_pt=dest_pt,
        )

    if going_right:
        for index in range(len(centers)):
            link = _link(centers[index])
            if link is not None:
                return link, index
        return None

    axis_limit = PORT_STUB + GRID_CELL
    for index in range(len(centers) - 1, -1, -1):
        if abs(centers[index][0] - port[0]) > axis_limit:
            continue
        link = _link(centers[index])
        if link is not None:
            return link, index
    for index in range(len(centers) - 1, -1, -1):
        link = _link(centers[index])
        if link is not None:
            return link, index
    return None


def _extend_unique(path: List[Point], points: Sequence[Point]) -> None:
    for point in points:
        if path and _same_point(path[-1], point):
            continue
        path.append(point)


def _astar(
    start_cell: Cell,
    goal_cell: Cell,
    blocked,
    bounds: Tuple[int, int, int, int],
    occupied: Set[Cell],
    keepout=None,
    blocked_cells=None,
    prefer_cells=None,
    start_dir: int = _DIR_EAST,
    visit_limit: int = ASTAR_VISIT_LIMIT,
) -> Optional[List[Cell]]:
    if start_cell == goal_cell:
        return [start_cell]
    gx, gy = goal_cell
    start_state = (start_cell[0], start_cell[1], start_dir)
    best_g: Dict[Tuple[int, int, int], int] = {start_state: 0}
    came_from: Dict[Tuple[int, int, int], Optional[Tuple[int, int, int]]] = {start_state: None}
    heap = [(abs(start_cell[0] - gx) + abs(start_cell[1] - gy), 0, 0, start_cell[0], start_cell[1], start_dir)]
    seq = 1
    visits = 0
    limit = visit_limit
    while heap:
        visits += 1
        if visits > limit:
            return None
        _f, g, _seq, cx, cy, direction = heapq.heappop(heap)
        state = (cx, cy, direction)
        recorded = best_g.get(state)
        if recorded is None or g > recorded:
            continue
        if (cx, cy) == goal_cell:
            cells: List[Cell] = []
            cursor: Optional[Tuple[int, int, int]] = state
            while cursor is not None:
                cells.append((cursor[0], cursor[1]))
                cursor = came_from.get(cursor)
            cells.reverse()
            unique: List[Cell] = []
            for cell in cells:
                if not unique or unique[-1] != cell:
                    unique.append(cell)
            return unique
        for nxt_dir, (dx, dy) in enumerate(_DIRECTIONS):
            nxt = (cx + dx, cy + dy)
            if not _in_bounds(nxt, bounds) or blocked(nxt):
                continue
            if (
                blocked_cells is not None
                and nxt in blocked_cells
                and nxt != start_cell
                and nxt != goal_cell
            ):
                continue
            cost = g + STEP_COST
            if nxt_dir != direction:
                cost += TURN_PENALTY
            if nxt in occupied and nxt != start_cell and nxt != goal_cell:
                cost += OCCUPY_PENALTY
            on_shared = bool(prefer_cells and nxt in prefer_cells)
            if keepout is not None and keepout(nxt) and not on_shared:
                cost += KEEP_OUT_PENALTY
            if on_shared:
                cost -= STEP_COST
            nxt_state = (nxt[0], nxt[1], nxt_dir)
            if cost >= best_g.get(nxt_state, cost + 1):
                continue
            best_g[nxt_state] = cost
            came_from[nxt_state] = state
            heuristic = abs(nxt[0] - gx) + abs(nxt[1] - gy)
            heapq.heappush(heap, (cost + heuristic, cost, seq, nxt[0], nxt[1], nxt_dir))
            seq += 1
    return None


def _cells_to_points(cells: Sequence[Cell]) -> List[Point]:
    return [cell_center(cell) for cell in cells]


def _snap_incoming_to_port_axis(centers: Sequence[Point], port: Point) -> List[Point]:
    snapped = list(centers)
    limit = PORT_STUB + GRID_CELL
    axis_from = len(snapped)
    for index in range(len(snapped) - 1, -1, -1):
        if abs(snapped[index][0] - port[0]) > limit:
            break
        axis_from = index
        snapped[index] = (port[0], snapped[index][1])
    if 0 < axis_from < len(snapped):
        prev = snapped[axis_from - 1]
        first = snapped[axis_from]
        if not _same_point(prev, first) and not _axis_aligned(prev, first):
            snapped.insert(axis_from, (first[0], prev[1]))
    return snapped


def _point_in_open_rect(point: Point, rect: Rect) -> bool:
    x, y, w, h = rect
    return x < point[0] < x + w and y < point[1] < y + h


def _flatten_last_on_input(
    candidate: Sequence[Point],
    end_pt: Point,
    end_card: Optional[Rect],
) -> bool:
    last = candidate[-1]
    prev = candidate[-2]
    if abs(last[0] - prev[0]) < _EPS and abs(last[0] - end_pt[0]) < _EPS:
        return True
    if abs(last[1] - prev[1]) >= _EPS or abs(last[1] - end_pt[1]) >= _EPS:
        return False
    if prev[0] > last[0] + _EPS:
        return False
    mouth_left = last[0] - PORT_STUB - GRID_CELL
    if end_card is not None:
        mouth_left = min(mouth_left, end_card[0] - PORT_STUB - GRID_CELL)
    return prev[0] < mouth_left - _EPS


def _flatten_score(
    candidate: Sequence[Point],
    start_pt: Point,
    end_pt: Point,
    end_card: Optional[Rect],
) -> Tuple[int, int, int]:
    first_on_out = (
        abs(candidate[0][1] - candidate[1][1]) < _EPS
        and abs(candidate[0][1] - start_pt[1]) < _EPS
    ) or (
        abs(candidate[0][0] - candidate[1][0]) < _EPS
        and abs(candidate[0][0] - start_pt[0]) < _EPS
    )
    return (
        0 if _flatten_last_on_input(candidate, end_pt, end_card) else 1,
        0 if first_on_out else 1,
        len(candidate),
    )


def _flatten_candidate_ok(
    candidate: Sequence[Point],
    start_pt: Point,
    end_pt: Point,
    start_card: Optional[Rect],
    end_card: Optional[Rect],
    obstacles: Sequence[Rect],
    terminals: Sequence[Rect],
    occupied_cells: Set[Cell],
    existing: Sequence[Sequence[Point]],
    block_occupied: bool,
) -> Optional[List[Point]]:
    try:
        cleaned = simplify_orthogonal(candidate)
    except ValueError:
        return None
    if not cleaned or not _same_point(cleaned[0], start_pt) or not _same_point(cleaned[-1], end_pt):
        return None
    if cleaned[1][0] < cleaned[0][0] - _EPS:
        return None
    if _path_enters_foreign_bodies(
        cleaned,
        obstacles,
        start_card,
        end_card,
        start_pt=start_pt,
        end_pt=end_pt,
    ):
        return None
    for vertex in cleaned[1:-1]:
        for rect in terminals:
            if _point_in_open_rect(vertex, rect):
                return None
    if block_occupied and occupied_cells and interior_cells_along_polyline(cleaned) & occupied_cells:
        return None
    if _path_crosses_existing(cleaned, existing, end_pt, end_card):
        return None
    return cleaned


def _flatten_pick_better(
    option: Sequence[Point],
    require_shorter: bool,
    cleaned: Sequence[Point],
    seen: Set[Tuple[Point, ...]],
    original_score: Tuple[int, int, int],
    best: Optional[List[Point]],
    best_score: Optional[Tuple[int, int, int]],
    start_pt: Point,
    end_pt: Point,
    start_card: Optional[Rect],
    end_card: Optional[Rect],
    obstacles: Sequence[Rect],
    terminals: Sequence[Rect],
    occupied_cells: Set[Cell],
    existing: Sequence[Sequence[Point]],
    block_occupied: bool,
) -> Tuple[Optional[List[Point]], Optional[Tuple[int, int, int]]]:
    candidate = _flatten_candidate_ok(
        option,
        start_pt,
        end_pt,
        start_card,
        end_card,
        obstacles,
        terminals,
        occupied_cells,
        existing,
        block_occupied,
    )
    if candidate is None:
        return best, best_score
    if require_shorter and len(candidate) >= len(cleaned):
        return best, best_score
    key = tuple(candidate)
    if key in seen:
        return best, best_score
    score = _flatten_score(candidate, start_pt, end_pt, end_card)
    if score >= original_score:
        return best, best_score
    if best is None or score < best_score:
        return candidate, score
    return best, best_score


def _flatten_short_stairs(
    path: Sequence[Point],
    start_card: Optional[Rect],
    end_card: Optional[Rect],
    other_rects: Sequence[Rect],
    start_pt: Point,
    end_pt: Point,
    occupied: Optional[Set[Cell]] = None,
    existing_paths: Optional[Sequence[Sequence[Point]]] = None,
    block_occupied: bool = True,
) -> List[Point]:
    """两连直角能收成一折就收；优先最后一段贴输入 x、第一段贴输出 y。"""
    obstacles = list(other_rects)
    if start_card is not None:
        obstacles.append(start_card)
    if end_card is not None:
        obstacles.append(end_card)
    occupied_cells = occupied if occupied is not None else set()
    existing = existing_paths if existing_paths is not None else []
    terminals = [rect for rect in (start_card, end_card) if rect is not None]
    try:
        cleaned = simplify_orthogonal(path)
    except ValueError:
        return list(path)
    seen = {tuple(cleaned)}
    for _ in range(min(8, max(1, len(cleaned)))):
        if len(cleaned) < 3:
            break
        original_score = _flatten_score(cleaned, start_pt, end_pt, end_card)
        best: Optional[List[Point]] = None
        best_score: Optional[Tuple[int, int, int]] = None
        index = 0
        while index <= len(cleaned) - 3:
            a, b, c = cleaned[index], cleaned[index + 1], cleaned[index + 2]
            vertical_ab = abs(a[0] - b[0]) < _EPS and abs(a[1] - b[1]) > _EPS
            horizontal_bc = abs(b[1] - c[1]) < _EPS and abs(b[0] - c[0]) > _EPS
            horizontal_ab = abs(a[1] - b[1]) < _EPS and abs(a[0] - b[0]) > _EPS
            vertical_bc = abs(b[0] - c[0]) < _EPS and abs(b[1] - c[1]) > _EPS
            if (vertical_ab and horizontal_bc) or (horizontal_ab and vertical_bc):
                best, best_score = _flatten_pick_better(
                    cleaned[:index] + [a, (c[0], a[1]), c] + cleaned[index + 3 :],
                    False,
                    cleaned,
                    seen,
                    original_score,
                    best,
                    best_score,
                    start_pt,
                    end_pt,
                    start_card,
                    end_card,
                    obstacles,
                    terminals,
                    occupied_cells,
                    existing,
                    block_occupied,
                )
                best, best_score = _flatten_pick_better(
                    cleaned[:index] + [a, (a[0], c[1]), c] + cleaned[index + 3 :],
                    False,
                    cleaned,
                    seen,
                    original_score,
                    best,
                    best_score,
                    start_pt,
                    end_pt,
                    start_card,
                    end_card,
                    obstacles,
                    terminals,
                    occupied_cells,
                    existing,
                    block_occupied,
                )
            if index <= len(cleaned) - 4:
                d = cleaned[index + 3]
                vertical_cd = abs(c[0] - d[0]) < _EPS and abs(c[1] - d[1]) > _EPS
                horizontal_cd = abs(c[1] - d[1]) < _EPS and abs(c[0] - d[0]) > _EPS
                two_turns = (vertical_ab and horizontal_bc and vertical_cd) or (
                    horizontal_ab and vertical_bc and horizontal_cd
                )
                if two_turns:
                    best, best_score = _flatten_pick_better(
                        cleaned[: index + 1] + [(d[0], a[1]), d] + cleaned[index + 4 :],
                        True,
                        cleaned,
                        seen,
                        original_score,
                        best,
                        best_score,
                        start_pt,
                        end_pt,
                        start_card,
                        end_card,
                        obstacles,
                        terminals,
                        occupied_cells,
                        existing,
                        block_occupied,
                    )
                    best, best_score = _flatten_pick_better(
                        cleaned[: index + 1] + [(a[0], d[1]), d] + cleaned[index + 4 :],
                        True,
                        cleaned,
                        seen,
                        original_score,
                        best,
                        best_score,
                        start_pt,
                        end_pt,
                        start_card,
                        end_card,
                        obstacles,
                        terminals,
                        occupied_cells,
                        existing,
                        block_occupied,
                    )
            index += 1
        if best is None:
            break
        seen.add(tuple(best))
        cleaned = best
    return cleaned


def _route_with_margin(
    start_pt: Point,
    end_pt: Point,
    start_stub: Point,
    end_stub: Point,
    other_rects: Sequence[Rect],
    start_card: Optional[Rect],
    end_card: Optional[Rect],
    occupied: Set[Cell],
    existing_paths: Sequence[Sequence[Point]],
    margin: float,
    prefer_cells: Optional[Set[Cell]] = None,
    skip_strict: bool = False,
) -> Optional[List[Point]]:
    extent_points, extent_rects = _collect_extent_points(
        start_pt, end_pt, start_stub, end_stub, other_rects, start_card, end_card, existing_paths
    )
    bounds = _search_bounds(extent_points, extent_rects, margin)
    corridors = corridor_rects(start_pt, end_pt, margin)
    blocked, keepout = _make_blocker(
        other_rects,
        start_card,
        end_card,
        bounds,
        start_pt,
        end_pt,
        corridors=corridors,
    )
    start_corridor = _face_corridor(start_card, True, start_pt) if start_card is not None else None
    end_corridor = _face_corridor(end_card, False, end_pt) if end_card is not None else None
    leave_dir = _leave_dir(start_pt, end_pt)
    incoming_dir = _DIR_SOUTH if start_pt[1] >= end_pt[1] else _DIR_NORTH

    def _search(block_occupied: bool, visit_limit: int) -> Optional[List[Point]]:
        extra_blocked: Set[Cell] = set()
        pick_occupied = occupied if block_occupied else extra_blocked
        start_cell = _pick_terminal_cell(
            start_stub, blocked, bounds, leave_dir, start_corridor, pick_occupied
        )
        goal_cell = _pick_terminal_cell(
            end_stub, blocked, bounds, incoming_dir, end_corridor, pick_occupied
        )
        if start_cell is None or goal_cell is None:
            return None
        local_blocked = set(extra_blocked)
        if block_occupied:
            local_blocked.update(occupied)
        for _attempt in range(4):
            cells = _astar(
                start_cell,
                goal_cell,
                blocked,
                bounds,
                occupied,
                keepout,
                blocked_cells=local_blocked if local_blocked else None,
                prefer_cells=prefer_cells,
                start_dir=leave_dir,
                visit_limit=visit_limit,
            )
            if cells is None:
                return None
            route_cells = list(cells)
            while len(route_cells) > 1 and route_cells[0] in local_blocked:
                route_cells.pop(0)
            while len(route_cells) > 1 and route_cells[-1] in local_blocked:
                route_cells.pop()
            centers = _snap_incoming_to_port_axis(_cells_to_points(route_cells), end_pt)
            picked_in = _pick_port_link(
                end_pt,
                centers,
                end_card,
                False,
                other_rects,
                start_card,
                end_card,
                occupied,
                existing_paths,
                block_occupied,
                dest_pt=end_pt,
            )
            if picked_in is None:
                local_blocked.update(route_cells[1:-1])
                extra_blocked.update(route_cells[1:-1])
                continue
            tail, attach_index = picked_in
            picked_out = _pick_port_link(
                start_pt,
                centers[: attach_index + 1],
                start_card,
                True,
                other_rects,
                start_card,
                end_card,
                occupied,
                existing_paths,
                block_occupied,
                dest_pt=end_pt,
            )
            if picked_out is None:
                local_blocked.update(route_cells[1:-1])
                extra_blocked.update(route_cells[1:-1])
                continue
            head, out_index = picked_out
            path: List[Point] = []
            _extend_unique(path, head)
            _extend_unique(path, centers[out_index : attach_index + 1])
            _extend_unique(path, reversed(tail))
            try:
                simplified = _flatten_short_stairs(
                    simplify_orthogonal(path),
                    start_card,
                    end_card,
                    other_rects,
                    start_pt,
                    end_pt,
                    occupied,
                    existing_paths,
                    block_occupied,
                )
            except ValueError:
                local_blocked.update(route_cells[1:-1])
                extra_blocked.update(route_cells[1:-1])
                continue
            pierce_rects = list(other_rects)
            if start_card is not None:
                pierce_rects.append(start_card)
            if end_card is not None:
                pierce_rects.append(end_card)
            if _path_enters_foreign_bodies(
                simplified,
                pierce_rects,
                start_card,
                end_card,
                start_pt=start_pt,
                end_pt=end_pt,
            ):
                hit = interior_cells_along_polyline(simplified)
                local_blocked.update(hit)
                extra_blocked.update(hit)
                continue
            if (
                block_occupied
                and occupied
                and interior_cells_along_polyline(simplified) & occupied
            ):
                hit = interior_cells_along_polyline(simplified)
                local_blocked.update(hit)
                extra_blocked.update(hit)
                continue
            if _path_crosses_existing(simplified, existing_paths, end_pt, end_card):
                hit = interior_cells_along_polyline(simplified)
                local_blocked.update(hit)
                extra_blocked.update(hit)
                continue
            return _finalize_path(simplified)
        return None

    if (occupied or existing_paths) and not skip_strict:
        found = _search(True, ASTAR_STRICT_VISIT_LIMIT)
        if found is not None:
            return found
    relaxed_limit = ASTAR_STACKED_VISIT_LIMIT if skip_strict else ASTAR_VISIT_LIMIT
    return _search(False, relaxed_limit)
