"""交互式正交寻路：避开卡片，并在局部距离、转弯和线路重叠间取平衡。"""
import heapq
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QPainterPathStroker


DEFAULT_CLEARANCE = 18.0
MIN_HARD_CLEARANCE = 2.0
# Normal lines are 2px and hover lines are 4px. Validate the complete 4px
# envelope so a route can still use a real narrow gap without touching a card.
ROUTE_SAFETY_STROKE_WIDTH = 4.0


def build_obstacle_groups(card_rects, clearance=DEFAULT_CLEARANCE):
    """按固定安全区合并相邻卡片，返回成员及完整组边界。"""
    entries = list(card_rects)
    if not entries:
        return []
    expanded = [
        rect.adjusted(-clearance, -clearance, clearance, clearance)
        for _card, rect in entries
    ]
    parents = list(range(len(entries)))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first, second):
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    epsilon = 0.01
    for first in range(len(entries)):
        a = expanded[first]
        first_rect = entries[first][1]
        for second in range(first + 1, len(entries)):
            b = expanded[second]
            second_rect = entries[second][1]
            overlap_x = max(
                0.0,
                min(first_rect.right(), second_rect.right())
                - max(first_rect.left(), second_rect.left()),
            )
            overlap_y = max(
                0.0,
                min(first_rect.bottom(), second_rect.bottom())
                - max(first_rect.top(), second_rect.top()),
            )
            aligned = (
                overlap_x >= min(first_rect.width(), second_rect.width()) * 0.5
                or overlap_y >= min(first_rect.height(), second_rect.height()) * 0.5
            )
            if (
                aligned
                and a.left() <= b.right() + epsilon
                and b.left() <= a.right() + epsilon
                and a.top() <= b.bottom() + epsilon
                and b.top() <= a.bottom() + epsilon
            ):
                union(first, second)

    indices_by_root = {}
    for index in range(len(entries)):
        indices_by_root.setdefault(find(index), []).append(index)

    groups = []
    for indices in indices_by_root.values():
        bounds = QRectF(entries[indices[0]][1])
        for index in indices[1:]:
            bounds = bounds.united(entries[index][1])
        groups.append((tuple(entries[index] for index in indices), bounds))
    return groups


def _reserved_path_segments(path):
    """提取正式路线的长直段，供寻路热路径做轻量重合判断。"""
    segments = []
    if path.isEmpty() or path.elementCount() < 2:
        return segments
    previous = path.elementAt(0)
    previous_point = (float(previous.x), float(previous.y))
    for index in range(1, path.elementCount()):
        element = path.elementAt(index)
        point = (float(element.x), float(element.y))
        if element.isLineTo():
            dx = point[0] - previous_point[0]
            dy = point[1] - previous_point[1]
            if abs(dy) <= 0.01 and abs(dx) > 0.01:
                segments.append((0, previous_point[1], *sorted((previous_point[0], point[0]))))
            elif abs(dx) <= 0.01 and abs(dy) > 0.01:
                segments.append((1, previous_point[0], *sorted((previous_point[1], point[1]))))
        previous_point = point
    return segments


def _segment_enters_rectangle(first, second, rectangle):
    epsilon = 0.01
    if abs(first.y() - second.y()) <= epsilon:
        return (
            rectangle.top() + epsilon < first.y() < rectangle.bottom() - epsilon
            and max(first.x(), second.x()) > rectangle.left() + epsilon
            and min(first.x(), second.x()) < rectangle.right() - epsilon
        )
    return (
        rectangle.left() + epsilon < first.x() < rectangle.right() - epsilon
        and max(first.y(), second.y()) > rectangle.top() + epsilon
        and min(first.y(), second.y()) < rectangle.bottom() - epsilon
    )


def _normalize_route_points(points, epsilon=1e-6):
    """Remove floating-point micro-slopes while preserving exact endpoints."""
    normalized = [QPointF(point) for point in points]
    for index in range(len(normalized) - 1):
        first, second = normalized[index:index + 2]
        if abs(first.x() - second.x()) <= epsilon:
            if index == len(normalized) - 2:
                first.setX(second.x())
            else:
                second.setX(first.x())
        if abs(first.y() - second.y()) <= epsilon:
            if index == len(normalized) - 2:
                first.setY(second.y())
            else:
                second.setY(first.y())
    return normalized


def _has_long_parallel_overlap(first, second, reserved_segments):
    horizontal = abs(first.y() - second.y()) <= 0.01
    orientation = 0 if horizontal else 1
    fixed = first.y() if horizontal else first.x()
    lower, upper = sorted(
        (first.x(), second.x()) if horizontal else (first.y(), second.y())
    )
    return any(
        segment_orientation == orientation
        and abs(segment_fixed - fixed) <= 7.5
        and min(upper, segment_upper) - max(lower, segment_lower) > 28.0
        for path_segments in reserved_segments
        for segment_orientation, segment_fixed, segment_lower, segment_upper in path_segments
    )


def _separate_parallel_lanes(
    points,
    rectangles,
    reserved_segments,
    center,
    source=None,
    target=None,
):
    """寻路后只平移实际重合的长直段，不向稀疏网格增加候选坐标。"""
    separated = list(points)

    def candidate_is_clear(candidate):
        last_segment = len(candidate) - 2
        return not any(
            _segment_enters_rectangle(
                a,
                b,
                rectangle.adjusted(
                    -ROUTE_SAFETY_STROKE_WIDTH / 2,
                    -ROUTE_SAFETY_STROKE_WIDTH / 2,
                    ROUTE_SAFETY_STROKE_WIDTH / 2,
                    ROUTE_SAFETY_STROKE_WIDTH / 2,
                ),
            )
            for segment_index, (a, b) in enumerate(zip(candidate, candidate[1:]))
            for rectangle in rectangles
            if not (
                (segment_index == 0 and rectangle == source)
                or (segment_index == last_segment and rectangle == target)
            )
        )

    def lane_offsets(first, second):
        horizontal = abs(first.y() - second.y()) <= 0.01
        fixed = first.y() if horizontal else first.x()
        center_fixed = center.y() if horizontal else center.x()
        outward = 14.0 if fixed >= center_fixed else -14.0
        return horizontal, (
            direction * outward * step
            for step in range(1, 9)
            for direction in (1.0, -1.0)
        )

    for index in range(1, len(separated) - 2):
        first, second = separated[index:index + 2]
        if not _has_long_parallel_overlap(first, second, reserved_segments):
            continue
        horizontal, offsets = lane_offsets(first, second)
        for offset in offsets:
            candidate = [QPointF(point) for point in separated]
            if horizontal:
                candidate[index].setY(first.y() + offset)
                candidate[index + 1].setY(second.y() + offset)
            else:
                candidate[index].setX(first.x() + offset)
                candidate[index + 1].setX(second.x() + offset)
            if not candidate_is_clear(candidate):
                continue
            if _has_long_parallel_overlap(
                candidate[index], candidate[index + 1], reserved_segments
            ):
                continue
            separated = candidate
            break

    return _simplify_route_points(separated)


def _simplify_route_points(points):
    """合并共线折点，同时消除沿同一通道原路折返形成的悬空尾巴。"""
    simplified = []
    for point in points:
        if simplified and point == simplified[-1]:
            continue
        while len(simplified) >= 2:
            p, q = simplified[-2:]
            u, v = q - p, point - q
            if abs(u.x() * v.y() - u.y() * v.x()) > 0.001:
                break
            # 三点共线时，p→q→point 可直接缩成 p→point。即使后半段
            # 与前半段反向，这也只会删除重复走过的通道，不会进入新区域。
            simplified.pop()
        simplified.append(point)
    return simplified


def _outer_return_route(start, end, source, target, obstacles, source_exit_x,
                        side, outer_margin, reserved_paths, hard_obstacles=None):
    """为跨越整组节点的回连生成单侧、不会重新钻入内部的外围通道。"""
    group_bounds = source.united(target)
    for rectangle in obstacles:
        group_bounds = group_bounds.united(rectangle)

    direction = 1.0 if side == "bottom" else -1.0
    base_y = (
        group_bounds.bottom() + outer_margin
        if side == "bottom"
        else group_bounds.top() - outer_margin
    )
    lane_step = 14.0
    route_stroker = QPainterPathStroker()
    route_stroker.setWidth(10.0)
    hard_stroker = QPainterPathStroker()
    hard_stroker.setWidth(ROUTE_SAFETY_STROKE_WIDTH)
    collision_obstacles = obstacles if hard_obstacles is None else hard_obstacles
    hard_obstacles = [
        rectangle
        for rectangle in collision_obstacles
        if rectangle != source and rectangle != target
    ]
    occupied_areas = []
    for reserved_path in reserved_paths:
        if reserved_path.isEmpty():
            continue
        occupied_stroker = QPainterPathStroker()
        occupied_stroker.setWidth(10.0)
        occupied = occupied_stroker.createStroke(reserved_path)
        occupied_areas.append((occupied, occupied.boundingRect()))

    def source_lane_x(preferred_x, lane_y):
        """Choose a source-side vertical lane that stays outside blocking cards."""
        lower_y, upper_y = sorted((start.y(), lane_y))
        blockers = [
            rectangle
            for rectangle in hard_obstacles
            if rectangle.right() > source.right()
            and rectangle.left() >= source.right() - 0.5
            and rectangle.bottom() > lower_y
            and rectangle.top() < upper_y
        ]
        if not blockers:
            return preferred_x
        route_margin = max(3.0, source_exit_x - source.right())
        left_limit = min(rectangle.left() for rectangle in blockers) - route_margin
        if source_exit_x <= left_limit:
            return min(preferred_x, left_limit)
        # A lower/upper card overlaps the source column. Move the vertical lane
        # beyond that complete stack instead of placing it inside the card edge.
        return max(
            preferred_x,
            max(rectangle.right() for rectangle in blockers) + route_margin,
        )

    # 已有外围回线占用任一长通道时继续向外分层。端口附近的交汇范围很短，
    # 不会超过阈值；源端、主横线或目标侧竖线发生长重合都会触发分槽。
    fallback = None
    for lane_index in range(9):
        lane_y = base_y + direction * lane_index * lane_step
        lane_x = group_bounds.left() - outer_margin - lane_index * lane_step
        lane_exit_x = source_lane_x(
            source_exit_x + lane_index * lane_step,
            lane_y,
        )
        candidate = QPainterPath(start)
        candidate.lineTo(QPointF(lane_exit_x, start.y()))
        candidate.lineTo(QPointF(lane_exit_x, lane_y))
        candidate.lineTo(QPointF(lane_x, lane_y))
        candidate.lineTo(QPointF(lane_x, end.y()))
        candidate.lineTo(end)
        hard_area = hard_stroker.createStroke(candidate)
        if any(hard_area.intersects(rectangle) for rectangle in hard_obstacles):
            continue

        points = _simplify_route_points([
            start,
            QPointF(lane_exit_x, start.y()),
            QPointF(lane_exit_x, lane_y),
            QPointF(lane_x, lane_y),
            QPointF(lane_x, end.y()),
            end,
        ])
        # 安全路线即使需要与端口附近的已有线短暂共用，也比穿过卡片优先。
        # 所有分槽都被占用时使用最外侧的安全候选。
        fallback = points
        candidate_area = route_stroker.createStroke(candidate)
        candidate_bounds = candidate_area.boundingRect()
        if not any(
            max(overlap.width(), overlap.height()) > 28.0
            for occupied, occupied_bounds in occupied_areas
            if candidate_bounds.intersects(occupied_bounds)
            if candidate_area.intersects(occupied)
            for overlap in [candidate_area.intersected(occupied).boundingRect()]
            if not overlap.isEmpty()
        ):
            return points
    return fallback


def _route_is_clear(points, obstacles, source, target):
    """Validate the painted route envelope against every non-endpoint card."""
    if not points:
        return False
    points = _normalize_route_points(points)
    path = QPainterPath(points[0])
    for point in points[1:]:
        path.lineTo(point)
    stroker = QPainterPathStroker()
    stroker.setWidth(ROUTE_SAFETY_STROKE_WIDTH)
    painted_area = stroker.createStroke(path)
    return not any(
        painted_area.intersects(rectangle.adjusted(0.25, 0.25, -0.25, -0.25))
        for rectangle in obstacles
        if rectangle != source and rectangle != target
    )


def _route_length(points):
    return sum(
        abs(second.x() - first.x()) + abs(second.y() - first.y())
        for first, second in zip(points, points[1:])
    )


def safe_orthogonal_route(
    start,
    end,
    source,
    target,
    local_obstacles,
    all_obstacles,
    *,
    clearance=DEFAULT_CLEARANCE,
    reserved_paths=(),
):
    """Return the clearest globally safe route available for the current geometry."""
    local_obstacles = list(local_obstacles)
    all_obstacles = list(all_obstacles)
    validation_obstacles = list(all_obstacles)
    for rectangle in local_obstacles:
        if (
            rectangle not in validation_obstacles
            and not rectangle.intersects(source)
            and not rectangle.intersects(target)
        ):
            validation_obstacles.append(rectangle)
    requested_clearance = max(float(clearance), MIN_HARD_CLEARANCE)
    clearance_levels = []
    for value in (
        requested_clearance,
        max(MIN_HARD_CLEARANCE, requested_clearance * 0.5),
        MIN_HARD_CLEARANCE,
    ):
        normalized = round(value, 6)
        if normalized not in clearance_levels:
            clearance_levels.append(normalized)

    obstacle_sets = [local_obstacles]
    if all_obstacles != local_obstacles:
        obstacle_sets.append(all_obstacles)
    if validation_obstacles not in obstacle_sets:
        obstacle_sets.append(validation_obstacles)
    for route_clearance in clearance_levels:
        for obstacles in obstacle_sets:
            points = orthogonal_route(
                start,
                end,
                source,
                target,
                obstacles,
                clearance=route_clearance,
                reserved_paths=reserved_paths,
                hard_obstacles=validation_obstacles,
            )
            if _route_is_clear(points, validation_obstacles, source, target):
                return points

        source_exit_x = source.right() + route_clearance
        candidates = [
            points
            for side in ("top", "bottom")
            for points in [_outer_return_route(
                start,
                end,
                source,
                target,
                all_obstacles,
                source_exit_x,
                side,
                max(28.0, route_clearance + 10.0),
                reserved_paths,
                validation_obstacles,
            )]
            if _route_is_clear(points, validation_obstacles, source, target)
        ]
        if candidates:
            return min(candidates, key=_route_length)
    return None


def orthogonal_route(start, end, source, target, obstacles, clearance=DEFAULT_CLEARANCE,
                     reserved_paths=(), hard_obstacles=None):
    """返回从右侧输出端口到左侧输入端口的正交折点。

    算法使用由障碍边界和通道中线组成的稀疏可见图。卡片是硬障碍；先求
    最短安全路径，再只对最终长距离共线的路段分槽，避免搜索规模随线数膨胀。
    """
    requested_clearance = float(clearance)
    # 只有源卡片与目标卡片之间的真实间距可以收缩端口安全距离。其他卡片始终
    # 使用固定安全区；相邻安全区自然连成障碍带，无关线路不能再从组内窄缝穿过。
    endpoint_clearance = requested_clearance
    source_target_overlap_x = min(source.right(), target.right()) > max(source.left(), target.left())
    source_target_overlap_y = min(source.bottom(), target.bottom()) > max(source.top(), target.top())
    source_target_vertical_gap = max(target.top() - source.bottom(), source.top() - target.bottom())
    source_target_horizontal_gap = max(target.left() - source.right(), source.left() - target.right())
    touching_seam = (
        source_target_overlap_x and abs(source_target_vertical_gap) <= 0.5
    ) or (
        source_target_overlap_y and abs(source_target_horizontal_gap) <= 0.5
    )
    if touching_seam:
        endpoint_clearance = 0.0
    else:
        endpoint_gaps = []
        if source_target_overlap_x and source_target_vertical_gap > 0:
            endpoint_gaps.append(source_target_vertical_gap)
        if source_target_overlap_y and source_target_horizontal_gap > 0:
            endpoint_gaps.append(source_target_horizontal_gap)
        if (
            not source_target_overlap_x
            and not source_target_overlap_y
            and source_target_vertical_gap > 0
            and source_target_horizontal_gap > 0
        ):
            endpoint_gaps.append(min(
                source_target_vertical_gap,
                source_target_horizontal_gap,
            ))
        if endpoint_gaps:
            endpoint_clearance = min(
                endpoint_clearance,
                max(4.0, min(endpoint_gaps) / 3),
            )

    # A neighbouring card can leave a real but very narrow channel immediately
    # outside an endpoint. Keep the non-endpoint obstacle clearance unchanged
    # and shorten only the port stub so its grid origin stays on that channel's
    # boundary instead of starting inside the expanded neighbour.
    source_exit_limits = [
        rectangle.left() - requested_clearance - source.right()
        for rectangle in obstacles
        if rectangle != source and rectangle != target
        and rectangle.left() >= source.right() - 0.5
        and rectangle.top() < start.y() < rectangle.bottom()
    ]
    target_entry_limits = [
        target.left() - requested_clearance - rectangle.right()
        for rectangle in obstacles
        if rectangle != source and rectangle != target
        and rectangle.right() <= target.left() + 0.5
        and rectangle.top() < end.y() < rectangle.bottom()
    ]
    if source_exit_limits:
        endpoint_clearance = min(endpoint_clearance, max(0.0, min(source_exit_limits)))
    if target_entry_limits:
        endpoint_clearance = min(endpoint_clearance, max(0.0, min(target_entry_limits)))

    rectangles = [
        rectangle.adjusted(-padding, -padding, padding, padding)
        for rectangle in obstacles
        for padding in [
            endpoint_clearance
            if rectangle == source or rectangle == target
            else requested_clearance
        ]
    ]
    clearance = endpoint_clearance
    snap = lambda value: round(float(value), 6)
    source_exit_x = snap(source.right() + clearance)
    group_margin = max(
        requested_clearance * 4,
        max(source.height(), target.height()) * 3,
    )
    group_area = source.united(target).adjusted(
        -group_margin, -group_margin, group_margin, group_margin,
    )
    route_group = [rect for rect in obstacles if rect.intersects(group_area)]
    other_obstacles = [rect for rect in route_group if rect != source and rect != target]
    source_is_bottommost = all(
        rect.bottom() <= source.bottom() + 0.5 for rect in route_group
    )
    source_is_topmost = all(
        rect.top() >= source.top() - 0.5 for rect in route_group
    )
    target_is_leftmost = all(
        rect.left() >= target.left() - 0.5 for rect in route_group
    )
    source_is_bottommost_in_column = all(
        min(rect.right(), source.right()) <= max(rect.left(), source.left())
        or rect.bottom() <= source.bottom() + 0.5
        for rect in route_group
    )
    source_is_topmost_in_column = all(
        min(rect.right(), source.right()) <= max(rect.left(), source.left())
        or rect.top() >= source.top() - 0.5
        for rect in route_group
    )
    target_is_leftmost_in_row = all(
        min(rect.bottom(), target.bottom()) <= max(rect.top(), target.top())
        or rect.left() >= target.left() - 0.5
        for rect in route_group
    )
    leftward_column_change = (
        target.left() <= source.left() - min(source.width(), target.width()) * 0.5
    )
    bottom_outer_candidate = leftward_column_change and (
        (source_is_bottommost and target_is_leftmost)
        or (source_is_bottommost_in_column and target_is_leftmost_in_row)
    )
    top_outer_candidate = leftward_column_change and (
        (source_is_topmost and target_is_leftmost)
        or (source_is_topmost_in_column and target_is_leftmost_in_row)
    )
    backward_connection = end.x() <= start.x()
    long_upward_return = (
        backward_connection
        and end.y() < start.y()
        and start.y() - end.y() >= max(source.height(), target.height()) * 2.0
        and bool(other_obstacles)
        and bottom_outer_candidate
    )
    long_downward_return = (
        backward_connection
        and end.y() > start.y()
        and end.y() - start.y() >= max(source.height(), target.height()) * 2.0
        and bool(other_obstacles)
        and top_outer_candidate
    )
    if long_upward_return or long_downward_return:
        outer_route = _outer_return_route(
            start,
            end,
            source,
            target,
            route_group,
            source_exit_x,
            "bottom" if long_upward_return else "top",
            max(28.0, requested_clearance + 10.0),
            reserved_paths,
            hard_obstacles,
        )
        if outer_route is not None:
            return outer_route

    source_target_vertical_channel = None
    if source.bottom() < target.top():
        source_target_vertical_channel = (
            source.bottom() + clearance + target.top() - clearance
        ) / 2
    elif target.bottom() < source.top():
        source_target_vertical_channel = (
            target.bottom() + clearance + source.top() - clearance
        ) / 2
    # The graph must own every obstacle-avoiding turn. Jumping vertically from
    # the port to a preselected channel bypassed collision checks and could cut
    # straight through a card in the same column.
    a = (source_exit_x, snap(start.y()))
    b = (snap(target.left() - clearance), snap(end.y()))

    reserved_segments = [
        segments
        for path in reserved_paths
        for segments in [_reserved_path_segments(path)]
        if segments
    ]

    # 障碍膨胀后的边界本身就是安全通道；不生成完整笛卡尔中线网格，避免
    # 大画布拖动节点时搜索规模成倍增加。
    xs = sorted(set(map(snap,
        [a[0], b[0], source.right(), target.left(),
         *[x for r in rectangles for x in (r.left(), r.right())]]
    )))
    ys = sorted(set(map(snap,
        [a[1], b[1], (a[1] + b[1]) / 2,
         *([] if source_target_vertical_channel is None else [source_target_vertical_channel]),
         *[y for r in rectangles for y in (r.top(), r.bottom())]]
    )))
    local_left = min(source.left(), target.left()) - clearance * 2
    local_right = max(source.right(), target.right()) + clearance * 2
    local_top = min(source.top(), target.top()) - clearance * 2
    local_bottom = max(source.bottom(), target.bottom()) + clearance * 2

    # 搜索只在相邻网格点间移动。先标出被卡片内部截断的相邻边，搜索时即可
    # 常数时间判断，避免同一条边从不同方向访问时反复遍历全部卡片。
    blocked_horizontal = set()
    blocked_vertical = set()
    horizontal_border_penalties = {}
    vertical_border_penalties = {}
    epsilon = 1e-5
    for rectangle in rectangles:
        horizontal_rows = [
            j for j, y in enumerate(ys)
            if rectangle.top() + epsilon < y < rectangle.bottom() - epsilon
        ]
        horizontal_edges = [
            i for i in range(len(xs) - 1)
            if xs[i + 1] > rectangle.left() + epsilon
            and xs[i] < rectangle.right() - epsilon
        ]
        blocked_horizontal.update(
            (i, j) for j in horizontal_rows for i in horizontal_edges
        )
        vertical_columns = [
            i for i, x in enumerate(xs)
            if rectangle.left() + epsilon < x < rectangle.right() - epsilon
        ]
        vertical_edges = [
            j for j in range(len(ys) - 1)
            if ys[j + 1] > rectangle.top() + epsilon
            and ys[j] < rectangle.bottom() - epsilon
        ]
        blocked_vertical.update(
            (i, j) for i in vertical_columns for j in vertical_edges
        )
        for boundary_y in (snap(rectangle.top()), snap(rectangle.bottom())):
            row = ys.index(boundary_y)
            for edge in horizontal_edges:
                shared = max(
                    0.0,
                    min(xs[edge + 1], rectangle.right())
                    - max(xs[edge], rectangle.left()),
                )
                if shared:
                    key = (edge, row)
                    horizontal_border_penalties[key] = (
                        horizontal_border_penalties.get(key, 0.0) + shared * 0.18
                    )
        for boundary_x in (snap(rectangle.left()), snap(rectangle.right())):
            column = xs.index(boundary_x)
            for edge in vertical_edges:
                shared = max(
                    0.0,
                    min(ys[edge + 1], rectangle.bottom())
                    - max(ys[edge], rectangle.top()),
                )
                if shared:
                    key = (column, edge)
                    vertical_border_penalties[key] = (
                        vertical_border_penalties.get(key, 0.0) + shared * 0.18
                    )

    origin = (xs.index(a[0]), ys.index(a[1]), 0)
    destination = (xs.index(b[0]), ys.index(b[1]))

    def heuristic(i, j, direction):
        dx = abs(xs[i] - b[0])
        dy = abs(ys[j] - b[1])
        turn_floor = 0.0
        if dx and dy:
            turn_floor = 24.0
        elif dx and direction == 1:
            turn_floor = 24.0
        elif dy and direction == 0:
            turn_floor = 24.0
        return dx + dy + turn_floor

    # Most routes visit only a small part of the sparse grid. Cache edge costs
    # when A* first reaches them instead of materialising the complete graph on
    # every mouse move. The cost formula and neighbour order remain unchanged.
    edge_cost_cache = {}

    def horizontal_edge_cost(edge, row):
        key = (0, edge, row)
        cached = edge_cost_cache.get(key)
        if cached is not None:
            return cached
        left, right = xs[edge], xs[edge + 1]
        y = ys[row]
        horizontal_outside = (
            local_left - right if right < local_left
            else left - local_right if left > local_right
            else 0.0
        )
        vertical_outside = (
            local_top - y if y < local_top
            else y - local_bottom if y > local_bottom
            else 0.0
        )
        cost = (
            right - left
            + horizontal_border_penalties.get((edge, row), 0.0)
            + (horizontal_outside + vertical_outside) * 0.35
        )
        edge_cost_cache[key] = cost
        return cost

    def vertical_edge_cost(column, edge):
        key = (1, column, edge)
        cached = edge_cost_cache.get(key)
        if cached is not None:
            return cached
        x = xs[column]
        top, bottom = ys[edge], ys[edge + 1]
        horizontal_outside = (
            local_left - x if x < local_left
            else x - local_right if x > local_right
            else 0.0
        )
        vertical_outside = (
            local_top - bottom if bottom < local_top
            else top - local_bottom if top > local_bottom
            else 0.0
        )
        cost = (
            bottom - top
            + vertical_border_penalties.get((column, edge), 0.0)
            + (horizontal_outside + vertical_outside) * 0.35
        )
        edge_cost_cache[key] = cost
        return cost

    queue = [(heuristic(origin[0], origin[1], origin[2]), 0.0, origin)]
    costs, parents = {origin: 0.0}, {}
    finish = None
    while queue:
        _estimate, cost, state = heapq.heappop(queue)
        if cost != costs[state]:
            continue
        i, j, direction = state
        if (i, j) == destination:
            finish = state
            break
        neighbours = []
        if i > 0 and (i - 1, j) not in blocked_horizontal:
            neighbours.append((i - 1, j, 0, horizontal_edge_cost(i - 1, j)))
        if i + 1 < len(xs) and (i, j) not in blocked_horizontal:
            neighbours.append((i + 1, j, 0, horizontal_edge_cost(i, j)))
        if j > 0 and (i, j - 1) not in blocked_vertical:
            neighbours.append((i, j - 1, 1, vertical_edge_cost(i, j - 1)))
        if j + 1 < len(ys) and (i, j) not in blocked_vertical:
            neighbours.append((i, j + 1, 1, vertical_edge_cost(i, j)))
        for ni, nj, nd, base_cost in neighbours:
            next_state = (ni, nj, nd)
            extra = base_cost
            if direction != nd:
                extra += 24.0
            # 最后一段必须从目标左侧接近，禁止从节点内部倒穿。
            if (ni, nj) == destination and nd != 0:
                extra += 48
            new_cost = cost + extra
            if new_cost < costs.get(next_state, float('inf')):
                costs[next_state] = new_cost
                parents[next_state] = state
                heapq.heappush(
                    queue,
                    (new_cost + heuristic(ni, nj, nd), new_cost, next_state),
                )
    if finish is None:
        return None  # 卡片重叠或端口被遮挡，没有合法通道。
    route = []
    while True:
        route.append(QPointF(xs[finish[0]], ys[finish[1]]))
        if finish == origin:
            break
        finish = parents[finish]
    points = [start]
    if abs(start.x() - a[0]) > 0.001 or abs(start.y() - a[1]) > 0.001:
        points.append(QPointF(a[0], start.y()))
    points.extend(reversed(route))
    points.append(end)
    points = _simplify_route_points(_normalize_route_points(points))
    # The search grid uses the preferred clearance, but lane separation only
    # needs to protect the real painted envelope. Reusing the expanded comfort
    # rectangles here rejected every neighbouring lane in a valid corridor and
    # forced unrelated routes onto the exact same coordinates.
    collision_rectangles = [source, target, *[
        rectangle
        for rectangle in (obstacles if hard_obstacles is None else hard_obstacles)
        if rectangle != source and rectangle != target
    ]]
    return _normalize_route_points(_separate_parallel_lanes(
        points,
        collision_rectangles,
        reserved_segments,
        source.united(target).center(),
        source,
        target,
    ))
