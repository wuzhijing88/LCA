"""最少拐角的正交路径；轨道只在端点限定的通道内分配。"""
from math import inf

from .connection_geometry import EdgeRoute

PORT_STUB = 24.0
TRACK_SPACING = 16.0


class _Lanes:
    """登记主干的固定坐标及跨度；axis 为 0 时分配竖轨，为 1 时分配横轨。"""
    def __init__(self, axis):
        self.axis = axis
        self.segments = []

    def reserve(self, points):
        middle = points[1:-1] if len(points) > 2 else points
        axis, span = self.axis, 1 - self.axis
        for a, b in zip(middle, middle[1:]):
            if a[axis] == b[axis] and a[span] != b[span]:
                self.segments.append((a[axis], min(a[span], b[span]), max(a[span], b[span])))

    def choose(self, start, stop, preferred, low=-inf, high=inf):
        """在允许范围内优先保持间距，再选离中点最近的位置。"""
        if low > high:
            raise ValueError("连线轨道范围无效")
        left, right = sorted((start, stop))
        occupied = sorted({position for position, start, stop in self.segments
                           if min(right, stop) > max(left, start)})
        boundaries = [-inf, *occupied, inf]
        preferred = min(max(preferred, low), high)
        best = None
        for a, b in zip(boundaries, boundaries[1:]):
            start, stop = max(a, low), min(b, high)
            if start > stop:
                continue
            spaced_start = max(start, a + TRACK_SPACING)
            spaced_stop = min(stop, b - TRACK_SPACING)
            if spaced_start <= spaced_stop:
                position = min(max(preferred, spaced_start), spaced_stop)
                clearance = TRACK_SPACING
            else:
                position = min(max((a + b) / 2, start), stop)
                clearance = min(position - a, b - position)
            score = (-clearance, abs(position - preferred), position)
            if best is None or score < best:
                best = score
        return best[2]


class OrthogonalRouter:
    """顺向边直连或共用一条竖轨，回程边使用一条横轨；保留边只登记。"""
    def plan(self, requests, retained=()):
        columns, rows = _Lanes(0), _Lanes(1)
        for route in retained:
            columns.reserve(route.points)
            rows.reserve(route.points)
        routes = {}
        for request in sorted(requests, key=self._order):
            if request.key in routes:
                raise ValueError("规划批次中存在重复连线")
            route = EdgeRoute(request.key, self._route(request, columns, rows))
            routes[request.key] = route
            columns.reserve(route.points)
            rows.reserve(route.points)
        return routes

    @staticmethod
    def _order(edge):
        sx, sy = edge.source
        tx, ty = edge.target
        return (tx <= sx, sy != ty, abs(tx - sx) + abs(ty - sy), edge.key)

    @staticmethod
    def _route(edge, columns, rows):
        sx, sy = edge.source
        tx, ty = edge.target
        if tx > sx:
            if sy == ty:
                return ((sx, sy), (tx, ty))
            margin = min(PORT_STUB, (tx - sx) / 2)
            column = columns.choose(sy, ty, (sx + tx) / 2, sx + margin, tx - margin)
            return ((sx, sy), (column, sy), (column, ty), (tx, ty))

        x1, x2 = sx + PORT_STUB, tx - PORT_STUB
        if sy != ty:
            low, high = sorted((sy, ty))
            margin = min(PORT_STUB, (high - low) / 2)
            row = rows.choose(x1, x2, (sy + ty) / 2, low + margin, high - margin)
        else:
            top = min(edge.source_bounds[1], edge.target_bounds[1], sy) - PORT_STUB
            bottom = max(edge.source_bounds[1] + edge.source_bounds[3],
                         edge.target_bounds[1] + edge.target_bounds[3], sy) + PORT_STUB
            above = rows.choose(x1, x2, top, high=top)
            below = rows.choose(x1, x2, bottom, low=bottom)
            row = min((above, below), key=lambda y: (abs(y - sy), y))
        return ((sx, sy), (x1, sy), (x1, row), (x2, row), (x2, ty), (tx, ty))
