"""原生后台与插件共用的拖拽路径校验和分段采样。"""

import math


def prepare_drag_path(path_points, duration, timestamps):
    """在发送输入前校验完整路径，并计算每段持续时间。"""
    if not isinstance(path_points, (list, tuple)) or len(path_points) < 2:
        raise ValueError("拖拽路径必须包含至少两个坐标点")
    try:
        duration_value = float(duration)
    except (TypeError, ValueError):
        raise ValueError("拖拽时间无效") from None
    if isinstance(duration, bool) or not math.isfinite(duration_value) or duration_value < 0:
        raise ValueError("拖拽时间无效")

    points = []
    for point in path_points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError("拖拽路径点无效")
        coordinates = []
        for value in point:
            try:
                coordinate = int(value)
                if isinstance(value, bool) or coordinate != float(value):
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                raise ValueError("拖拽路径点必须是整数") from None
            coordinates.append(coordinate)
        points.append(tuple(coordinates))

    if timestamps is None:
        return points, [duration_value / (len(points) - 1)] * (len(points) - 1)
    if not isinstance(timestamps, (list, tuple)) or len(timestamps) != len(points):
        raise ValueError("拖拽时间戳数量与路径点数量不一致")
    stamps = []
    for value in timestamps:
        try:
            stamp = float(value)
        except (TypeError, ValueError):
            raise ValueError("拖拽时间戳无效") from None
        if isinstance(value, bool) or not math.isfinite(stamp) or stamp < 0:
            raise ValueError("拖拽时间戳无效")
        if stamps and stamp < stamps[-1]:
            raise ValueError("拖拽时间戳必须递增")
        stamps.append(stamp)
    return points, [end - start for start, end in zip(stamps, stamps[1:])]


def iter_drag_samples(points, segment_durations):
    """逐段按 60 Hz 插值，保留每个路径节点及零时长节点。"""
    for start, end, duration in zip(points, points[1:], segment_durations):
        steps = max(1, math.ceil(duration * 60.0))
        wait = duration / steps
        for step in range(1, steps + 1):
            progress = step / steps
            yield (
                wait,
                int(start[0] + (end[0] - start[0]) * progress),
                int(start[1] + (end[1] - start[1]) * progress),
            )
