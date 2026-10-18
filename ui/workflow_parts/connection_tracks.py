"""最少拐角的正交路径；轨道只在端点限定的通道内分配。"""
from math import inf

from .connection_geometry import EdgeRoute

PORT_STUB = 24.0
TRACK_SPACING = 16.0


def _stub_bounds(start, stop):
    low, high = sorted((start, stop))
    span = high - low
    if span <= PORT_STUB * 2:
        middle = low + span / 2
        return middle, middle
    return low + PORT_STUB, high - PORT_STUB


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

    def overlaps(self, start, stop, position, minimum=0.0):
        """返回指定轨道上是否已有超过 minimum 的重叠线段。"""
        left, right = sorted((start, stop))
        return any(
            occupied_position == position
            and min(right, occupied_stop) - max(left, occupied_start) > minimum
            for occupied_position, occupied_start, occupied_stop in self.segments
        )

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


class _TargetApproaches:
    """为同一目标卡片的回程线分配不同的目标侧竖轨。"""
    def __init__(self):
        self._tracks = {}

    def reserve(self, route):
        if len(route.points) < 6:
            return
        target_id = route.key[1]
        self._tracks.setdefault(target_id, []).append(route.points[-2][0])

    def choose(self, target_id, preferred, span, columns, low=None):
        start, stop = sorted(span)
        tracks = list(self._tracks.get(target_id, ()))
        # 同一目标即使各自的高度区间不重叠，也保持目标前方的视觉分轨；
        # 其他目标只需避让当前批次中实际重叠的竖轨。
        tracks.extend(position for position, occupied_start, occupied_stop in columns.segments
                      if min(stop, occupied_stop) > max(start, occupied_start))
        if not tracks:
            return preferred
        if low is not None and low > preferred:
            raise ValueError("目标侧竖轨范围无效")
        # 目标端口位于卡片左侧，向左展开不会侵入目标卡片；
        # 第一条仍使用原来的 24 场景单位短引线。
        candidate = preferred
        while any(abs(candidate - track) < TRACK_SPACING for track in tracks):
            next_candidate = candidate - TRACK_SPACING
            if low is not None and next_candidate < low:
                return low
            candidate = next_candidate
        return candidate


class OrthogonalRouter:
    """顺向边直连或共用一条竖轨，回程边使用一条横轨；保留边只登记。"""
    def plan(self, requests, retained=()):
        columns, rows = _Lanes(0), _Lanes(1)
        target_approaches = _TargetApproaches()
        for route in retained:
            columns.reserve(route.points)
            rows.reserve(route.points)
            target_approaches.reserve(route)
        routes = {}
        for request in sorted(requests, key=self._order):
            if request.key in routes:
                raise ValueError("规划批次中存在重复连线")
            route = EdgeRoute(request.key, self._route(request, columns, rows, target_approaches))
            routes[request.key] = route
            columns.reserve(route.points)
            rows.reserve(route.points)
            target_approaches.reserve(route)
        return routes

    @staticmethod
    def _order(edge):
        sx, sy = edge.source
        tx, ty = edge.target
        return (tx <= sx, sy != ty, abs(tx - sx) + abs(ty - sy), edge.key)

    @staticmethod
    def _route(edge, columns, rows, target_approaches):
        sx, sy = edge.source
        tx, ty = edge.target
        if tx > sx:
            if sy == ty:
                # 随机分支允许同一输出端口连接多个目标。多条同排直线会
                # 完整叠在一起，第二条开始改走卡片外侧的 U 形通道。
                # 间距小于两个端口短桩时没有可用的中间通道，保留直连。
                if edge.key[2] == "random" and tx - sx > PORT_STUB * 2 \
                        and rows.overlaps(sx, tx, sy, PORT_STUB):
                    x1, x2 = _stub_bounds(sx, tx)
                    top = min(edge.source_bounds[1], edge.target_bounds[1], sy) - PORT_STUB
                    bottom = max(edge.source_bounds[1] + edge.source_bounds[3],
                                 edge.target_bounds[1] + edge.target_bounds[3], sy) + PORT_STUB
                    above = rows.choose(x1, x2, top, high=top)
                    below = rows.choose(x1, x2, bottom, low=bottom)
                    row = min((above, below), key=lambda y: (abs(y - sy), y))
                    x1 = columns.choose(sy, row, x1, x1, x2)
                    x2 = target_approaches.choose(edge.key[1], x2, (row, ty), columns, low=x1)
                    # 两条竖轨都被压到同一坐标时，继续生成 U 形会在同一条
                    # 竖线上往返，形成视觉上的折叠回头；没有可分开的横向
                    # 通道时保留直连，避免产生自相邻的怪异路径。
                    if x2 <= x1:
                        return ((sx, sy), (tx, ty))
                    return ((sx, sy), (x1, sy), (x1, row),
                            (x2, row), (x2, ty), (tx, ty))
                return ((sx, sy), (tx, ty))
            column_low, column_high = _stub_bounds(sx, tx)
            column = columns.choose(sy, ty, (sx + tx) / 2, column_low, column_high)
            return ((sx, sy), (column, sy), (column, ty), (tx, ty))

        x1, x2 = sx + PORT_STUB, tx - PORT_STUB
        if sy != ty:
            row_low, row_high = _stub_bounds(sy, ty)
            row = rows.choose(x1, x2, (sy + ty) / 2, row_low, row_high)
        else:
            top = min(edge.source_bounds[1], edge.target_bounds[1], sy) - PORT_STUB
            bottom = max(edge.source_bounds[1] + edge.source_bounds[3],
                         edge.target_bounds[1] + edge.target_bounds[3], sy) + PORT_STUB
            above = rows.choose(x1, x2, top, high=top)
            below = rows.choose(x1, x2, bottom, low=bottom)
            row = min((above, below), key=lambda y: (abs(y - sy), y))
        if edge.key[2] == "random":
            # 回程随机分支可能从同一个输出端口离开多个目标。源侧竖轨
            # 也必须登记和分轨，否则同一侧的第三条线会折叠在已有竖轨上。
            x1 = columns.choose(sy, row, x1, low=x1)
        x2 = target_approaches.choose(edge.key[1], x2, (row, ty), columns)
        return ((sx, sy), (x1, sy), (x1, row), (x2, row), (x2, ty), (tx, ty))
