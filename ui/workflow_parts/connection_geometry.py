"""与 Qt、卡片和场景无关的连线几何模型。"""
from dataclasses import dataclass
from math import isfinite

Point = tuple[float, float]
EdgeKey = tuple[int, int, str]
LINE_TYPES = frozenset(("sequential", "success", "failure", "random"))


def orthogonal_points(points) -> tuple[Point, ...]:
    result = []
    for raw in points:
        if len(raw) != 2:
            raise ValueError("连线坐标必须包含横纵坐标")
        point = (float(raw[0]), float(raw[1]))
        if not all(isfinite(value) for value in point):
            raise ValueError("连线坐标必须是有限数值")
        if result and point == result[-1]:
            continue
        if result and point[0] != result[-1][0] and point[1] != result[-1][1]:
            raise ValueError("连线必须由水平或垂直线段组成")
        while len(result) > 1:
            a, b = result[-2:]
            same_x = a[0] == b[0] == point[0]
            same_y = a[1] == b[1] == point[1]
            dot = (b[0] - a[0]) * (point[0] - b[0]) + (b[1] - a[1]) * (point[1] - b[1])
            if not (same_x or same_y) or dot <= 0:
                break
            result.pop()
        result.append(point)
    if len(result) < 2:
        raise ValueError("连线必须包含至少两个不同的点")
    return tuple(result)


@dataclass(frozen=True)
class EdgeRequest:
    key: EdgeKey
    source: Point
    target: Point
    source_bounds: tuple[float, float, float, float]
    target_bounds: tuple[float, float, float, float]

    def __post_init__(self):
        if self.key[2] not in LINE_TYPES:
            raise ValueError("不支持的连线端口")
        if not all(isfinite(v) for group in (self.source, self.target, self.source_bounds, self.target_bounds) for v in group):
            raise ValueError("连线端点和卡片边界必须是有限数值")


@dataclass(frozen=True)
class EdgeRoute:
    key: EdgeKey
    points: tuple[Point, ...]

    def __post_init__(self):
        object.__setattr__(self, "points", orthogonal_points(self.points))
