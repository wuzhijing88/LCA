import unittest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QPainterPathStroker
from ui.workflow_parts.connection_routing import (
    _has_long_parallel_overlap,
    _reserved_path_segments,
    _separate_parallel_lanes,
    _simplify_route_points,
    build_obstacle_groups,
    orthogonal_route,
    safe_orthogonal_route,
)


class RoutingTests(unittest.TestCase):
    def test_lane_separation_ignores_only_expected_endpoint_contact(self):
        source = QRectF(16.37, -31.0, 200.0, 60.0)
        target = QRectF(0.0, 352.0, 200.0, 60.0)
        points = [
            QPointF(209.57, -1.0),
            QPointF(234.37, -1.0),
            QPointF(234.37, 82.0),
            QPointF(-21.0, 82.0),
            QPointF(-21.0, 382.0),
            QPointF(6.8, 382.0),
        ]
        occupied = QPainterPath(QPointF(459.2, 130.0))
        for point in (
            QPointF(484.0, 130.0),
            QPointF(484.0, 82.0),
            QPointF(-21.0, 82.0),
            QPointF(-21.0, 177.0),
            QPointF(3.8, 177.0),
        ):
            occupied.lineTo(point)
        reserved = [_reserved_path_segments(occupied)]

        separated = _separate_parallel_lanes(
            points,
            [source, target],
            reserved,
            source.united(target).center(),
            source,
            target,
        )

        self.assertNotEqual(separated, points)
        self.assertFalse(any(
            _has_long_parallel_overlap(first, second, reserved)
            for first, second in zip(separated[1:-2], separated[2:-1])
        ))

    def test_endpoint_stub_shrinks_to_fit_real_narrow_side_channel(self):
        source = QRectF(28.0, 155.0, 200.0, 60.0)
        target = QRectF(303.0, 27.0, 200.0, 60.0)
        side_card = QRectF(230.627, 149.0, 200.0, 60.0)
        start = QPointF(221.2, 200.0)
        end = QPointF(309.8, 72.0)
        obstacles = [source, target, side_card]

        points = safe_orthogonal_route(
            start,
            end,
            source,
            target,
            obstacles,
            obstacles,
        )

        self.assertIsNotNone(points)
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        stroker = QPainterPathStroker()
        stroker.setWidth(4.0)
        self.assertFalse(stroker.createStroke(path).intersects(side_card.adjusted(0.25, 0.25, -0.25, -0.25)))

    def test_subpixel_endpoint_rounding_does_not_create_false_collision(self):
        source = QRectF(-32.0, 7.000000000000004, 200.0, 60.0)
        target = QRectF(879.0, 233.0, 200.0, 60.0)
        nearby = QRectF(301.0, 24.0, 200.0, 60.0)
        start = QPointF(161.2, 52.00000000000001)
        end = QPointF(885.8, 278.0)

        points = safe_orthogonal_route(
            start,
            end,
            source,
            target,
            [source, target, nearby],
            [source, target, nearby],
        )

        self.assertIsNotNone(points)
        self.assertEqual(points[0], start)
        self.assertEqual(points[-1], end)

    def test_obstacle_groups_merge_close_aligned_cards_only(self):
        aligned = [
            ("upper", QRectF(300, 100, 170, 80)),
            ("lower", QRectF(300, 210, 170, 80)),
        ]
        diagonal = ("diagonal", QRectF(455, 305, 170, 80))

        groups = build_obstacle_groups([*aligned, diagonal])

        self.assertEqual(len(groups), 2)
        member_sets = [{card for card, _rect in members} for members, _bounds in groups]
        self.assertIn({"upper", "lower"}, member_sets)
        self.assertIn({"diagonal"}, member_sets)

    def test_collinear_channel_backtrack_is_removed(self):
        points = _simplify_route_points([
            QPointF(950, 84),
            QPointF(974, 84),
            QPointF(974, 130),
            QPointF(974, 42),
            QPointF(16, 42),
        ])
        self.assertEqual(points, [
            QPointF(950, 84),
            QPointF(974, 84),
            QPointF(974, 42),
            QPointF(16, 42),
        ])

    def test_narrow_forward_gap_does_not_wrap_source(self):
        source,target=QRectF(400,70,170,52),QRectF(592,138,170,52)
        points=self.route(source,target)
        self.assertIsNotNone(points)
        self.assertGreaterEqual(min(p.y() for p in points),source.center().y())
        self.assertGreaterEqual(min(p.x() for p in points),source.right())
        self.assertLessEqual(max(p.x() for p in points),target.left())

    def route(self, source, target, others=()):
        start = QPointF(source.right(), source.center().y())
        end = QPointF(target.left(), target.center().y())
        return orthogonal_route(start, end, source, target, [source, target, *others])

    def test_adjacent_rows_do_not_use_whole_canvas(self):
        source, target = QRectF(630,360,170,52), QRectF(800,490,170,52)
        distant = [QRectF(160,60,170,52), QRectF(1300,350,170,52), QRectF(800,800,170,52)]
        points = self.route(source,target,distant)
        self.assertIsNotNone(points)
        self.assertLess(max(p.x() for p in points),1000)
        self.assertGreater(min(p.x() for p in points),600)
        self.assertLess(max(p.y() for p in points),550)

    def test_upward_connection_can_take_local_gap(self):
        source, target = QRectF(550,360,170,52), QRectF(350,30,170,52)
        points = self.route(source,target,[QRectF(2000,2000,170,52)])
        self.assertLess(max(p.x() for p in points),800)
        self.assertLess(max(p.y() for p in points),450)
        self.assertLess(points[2].y(), source.top())

    def test_backward_downward_connection_exits_toward_target(self):
        source = QRectF(470, 150, 265, 80)
        target = QRectF(470, 360, 265, 80)
        points = self.route(source, target)
        self.assertIsNotNone(points)
        self.assertGreater(points[2].y(), source.bottom())

    def test_obstacle_is_avoided(self):
        source, target = QRectF(0,0,170,52), QRectF(600,0,170,52)
        obstacle = QRectF(300,-30,170,120)
        points = self.route(source,target,[obstacle])
        self.assertIsNotNone(points)
        for a,b in zip(points,points[1:]):
            if a.y()==b.y():
                self.assertFalse(obstacle.top()<a.y()<obstacle.bottom() and max(a.x(),b.x())>obstacle.left() and min(a.x(),b.x())<obstacle.right())
            else:
                self.assertFalse(obstacle.left()<a.x()<obstacle.right() and max(a.y(),b.y())>obstacle.top() and min(a.y(),b.y())<obstacle.bottom())

    def test_unrelated_line_does_not_thread_close_vertical_stack(self):
        source = QRectF(0, 169, 170, 52)
        target = QRectF(700, 169, 170, 52)
        upper = QRectF(300, 100, 170, 80)
        lower = QRectF(300, 210, 170, 80)
        points = self.route(source, target, (upper, lower))

        self.assertIsNotNone(points)
        group_top = upper.top() - 18.0
        group_bottom = lower.bottom() + 18.0
        crossing_segments = [
            first.y()
            for first, second in zip(points, points[1:])
            if abs(first.y() - second.y()) <= 0.001
            and max(first.x(), second.x()) > upper.left()
            and min(first.x(), second.x()) < upper.right()
        ]
        self.assertTrue(crossing_segments)
        self.assertTrue(all(
            y <= group_top + 0.01 or y >= group_bottom - 0.01
            for y in crossing_segments
        ))

    def test_distant_nodes_do_not_lengthen_route(self):
        a,b=QRectF(500,0,170,52),QRectF(300,200,170,52)
        self.assertEqual(self.route(a,b),self.route(a,b,[QRectF(3000,4000,170,52)]))

    def test_long_return_avoids_reserved_local_lane(self):
        cards = [
            QRectF(20, 30, 170, 52),
            QRectF(385, 145, 170, 52),
            QRectF(385, 235, 170, 52),
            QRectF(385, 370, 170, 52),
        ]
        source, target = cards[3], cards[0]
        occupied_lane = QPainterPath(QPointF(573, 171))
        occupied_lane.lineTo(QPointF(573, 396))
        points = orthogonal_route(
            QPointF(source.right(), source.center().y()),
            QPointF(target.left(), target.center().y()),
            source,
            target,
            cards,
            reserved_paths=[occupied_lane],
        )
        self.assertIsNotNone(points)
        # 长回环从源卡片下方退出，避免沿已有右侧竖向通道向上重叠。
        self.assertGreater(points[2].y(), source.bottom())

    def test_close_vertical_stack_uses_real_gaps_instead_of_outer_loop(self):
        cards = [
            QRectF(70, 75, 300, 90),
            QRectF(460, 75, 300, 90),
            QRectF(460, 195, 300, 90),
            QRectF(460, 315, 300, 90),
        ]
        source, target = cards[1], cards[2]
        points = orthogonal_route(
            QPointF(source.right(), source.center().y()),
            QPointF(target.left(), target.center().y()),
            source,
            target,
            cards,
        )
        self.assertIsNotNone(points)
        # 两卡只有 30px 间距，仍应穿过真实间隙，不得绕到整列卡片底部。
        gap_points = [point for point in points if source.bottom() < point.y() < target.top()]
        self.assertTrue(gap_points)
        self.assertLess(max(point.y() for point in points), target.bottom())
        self.assertGreater(min(point.x() for point in points), cards[0].right())

    def test_touching_staggered_cards_use_shared_edge_seam(self):
        source = QRectF(441, 83, 228, 68)
        target = QRectF(643, 151, 230, 70)
        points = self.route(source, target)
        self.assertIsNotNone(points)
        self.assertTrue(any(abs(point.y() - 151.0) <= 0.5 for point in points))
        self.assertGreaterEqual(min(point.x() for point in points), target.left())
        self.assertLessEqual(max(point.x() for point in points), source.right() + 1.0)
        self.assertLessEqual(max(point.y() for point in points), target.center().y())

    def test_large_vertical_gap_prefers_middle_channel_over_card_edge(self):
        source = QRectF(372, 219, 229, 68)
        target = QRectF(441, 536, 229, 68)
        points = self.route(source, target)
        self.assertIsNotNone(points)
        expected_middle = (source.bottom() + target.top()) / 2
        self.assertTrue(any(abs(point.y() - expected_middle) <= 0.5 for point in points))

    def test_fractional_clearance_does_not_misclassify_boundary_as_blocked(self):
        source = QRectF(530, 122, 200, 60)
        target = QRectF(310, 174, 200, 60)
        points = orthogonal_route(
            QPointF(723.2, 152),
            QPointF(316.8, 204),
            source,
            target,
            [source, target],
        )
        self.assertIsNotNone(points)
        self.assertGreater(len(points), 2)

    def test_bottommost_last_node_returns_below_before_connecting_to_head(self):
        cards = [
            QRectF(50, 40, 300, 90),
            QRectF(440, 40, 300, 90),
            QRectF(440, 160, 300, 90),
            QRectF(440, 280, 300, 90),
            QRectF(440, 520, 300, 90),
        ]
        source, target = cards[-1], cards[0]
        points = self.route(source, target, cards[1:-1])
        self.assertIsNotNone(points)
        self.assertGreater(points[2].y(), source.bottom())
        self.assertGreaterEqual(max(point.y() for point in points), source.bottom())

    def test_bottommost_return_uses_group_exterior_even_when_middle_gap_is_empty(self):
        cards = [
            QRectF(60, 210, 170, 52),
            QRectF(335, 90, 170, 52),
            QRectF(575, 100, 170, 52),
            QRectF(835, 330, 170, 52),
        ]
        source, target = cards[-1], cards[0]
        points = self.route(source, target, cards[1:-1])
        self.assertIsNotNone(points)
        group_bottom = max(card.bottom() for card in cards)
        long_horizontal_y = [
            first.y()
            for first, second in zip(points, points[1:])
            if abs(first.y() - second.y()) <= 0.001
            and abs(first.x() - second.x()) > 400
        ]
        self.assertTrue(long_horizontal_y)
        self.assertTrue(all(y >= group_bottom + 28 for y in long_horizontal_y))

    def test_multiple_outer_returns_use_separate_lanes(self):
        cards = [
            QRectF(60, 210, 170, 52),
            QRectF(335, 90, 170, 52),
            QRectF(575, 100, 170, 52),
            QRectF(835, 330, 170, 52),
        ]
        source, target = cards[-1], cards[0]
        start = QPointF(source.right(), source.center().y())
        end = QPointF(target.left(), target.center().y())
        first = orthogonal_route(start, end, source, target, cards)
        occupied = QPainterPath(first[0])
        for point in first[1:]:
            occupied.lineTo(point)
        second = orthogonal_route(
            start, end, source, target, cards, reserved_paths=[occupied],
        )
        self.assertGreater(max(point.y() for point in second), max(point.y() for point in first))
        self.assertGreater(second[1].x(), first[1].x())

    def test_outer_lane_expansion_never_enters_adjacent_card(self):
        target = QRectF(245, 0, 200, 60)
        source = QRectF(490, 200, 200, 60)
        adjacent = QRectF(735, 200, 200, 60)
        start = QPointF(683.2, 230)
        end = QPointF(251.8, 30)
        source_exit_x = source.right() + 18.0
        group_bounds = source.united(target).united(adjacent)
        reserved = []
        for lane_index in range(8):
            lane_y = group_bounds.bottom() + 28.0 + lane_index * 14.0
            lane_x = group_bounds.left() - 28.0 - lane_index * 14.0
            lane_exit_x = source_exit_x + lane_index * 14.0
            path = QPainterPath(start)
            path.lineTo(QPointF(lane_exit_x, start.y()))
            path.lineTo(QPointF(lane_exit_x, lane_y))
            path.lineTo(QPointF(lane_x, lane_y))
            path.lineTo(QPointF(lane_x, end.y()))
            path.lineTo(end)
            reserved.append(path)

        points = orthogonal_route(
            start,
            end,
            source,
            target,
            [source, target, adjacent],
            reserved_paths=reserved,
        )
        self.assertIsNotNone(points)
        routed = QPainterPath(points[0])
        for point in points[1:]:
            routed.lineTo(point)
        stroker = QPainterPathStroker()
        stroker.setWidth(3.0)
        self.assertFalse(stroker.createStroke(routed).intersects(adjacent))

    def test_outer_target_lane_checks_cards_outside_local_route_group(self):
        target = QRectF(735, 300, 200, 60)
        source = QRectF(980, 100, 200, 60)
        local_left_card = QRectF(490, 100, 200, 60)
        omitted_left_card = QRectF(245, 100, 200, 60)
        start = QPointF(source.right(), source.center().y())
        end = QPointF(target.left(), target.center().y())
        reserved = []
        for lane_index in range(8):
            lane_y = 72.0 - lane_index * 14.0
            lane_x = local_left_card.left() - 28.0 - lane_index * 14.0
            lane_exit_x = source.right() + 18.0 + lane_index * 14.0
            path = QPainterPath(start)
            path.lineTo(QPointF(lane_exit_x, start.y()))
            path.lineTo(QPointF(lane_exit_x, lane_y))
            path.lineTo(QPointF(lane_x, lane_y))
            path.lineTo(QPointF(lane_x, end.y()))
            path.lineTo(end)
            reserved.append(path)

        points = orthogonal_route(
            start,
            end,
            source,
            target,
            [source, target, local_left_card],
            reserved_paths=reserved,
            hard_obstacles=[source, target, local_left_card, omitted_left_card],
        )
        self.assertIsNotNone(points)
        routed = QPainterPath(points[0])
        for point in points[1:]:
            routed.lineTo(point)
        stroker = QPainterPathStroker()
        stroker.setWidth(3.0)
        self.assertFalse(stroker.createStroke(routed).intersects(omitted_left_card))

    def test_outer_returns_to_same_target_separate_target_side(self):
        cards = [
            QRectF(20, 40, 230, 60),
            QRectF(430, 120, 230, 60),
            QRectF(430, 330, 230, 60),
            QRectF(430, 540, 230, 60),
        ]
        target = cards[0]
        first = self.route(cards[2], target, (cards[1], cards[3]))
        occupied = QPainterPath(first[0])
        for point in first[1:]:
            occupied.lineTo(point)
        second = orthogonal_route(
            QPointF(cards[3].right(), cards[3].center().y()),
            QPointF(target.left(), target.center().y()),
            cards[3], target, cards, reserved_paths=[occupied],
        )
        self.assertLess(min(point.x() for point in second), min(point.x() for point in first))

    def test_adjacent_vertical_chain_does_not_become_group_outer_return(self):
        cards = [QRectF(440, 40 + index * 110, 300, 60) for index in range(5)]
        source, target = cards[0], cards[1]
        points = self.route(source, target, cards[2:])
        self.assertIsNotNone(points)
        self.assertGreaterEqual(min(point.y() for point in points), source.top())
        self.assertGreaterEqual(min(point.x() for point in points), source.left() - 18.0)

    def test_wide_vertical_chain_adjacent_edge_stays_local(self):
        cards = [QRectF(440, 40 + index * 150, 300, 60) for index in range(5)]
        points = self.route(cards[0], cards[1], cards[2:])
        self.assertIsNotNone(points)
        self.assertGreaterEqual(min(point.y() for point in points), cards[0].top())
        self.assertLess(max(point.y() for point in points), cards[2].top())

    def test_last_card_of_right_column_wraps_outside_to_next_column(self):
        cards = [
            QRectF(60, 80, 200, 60),
            QRectF(318, 80, 200, 60),
            QRectF(559, 0, 200, 60),
            QRectF(559, 80, 200, 60),
            QRectF(559, 166, 200, 60),
            *[QRectF(782, y, 200, 60) for y in (80, 150, 220, 290, 360, 430, 500, 570)],
            *[QRectF(293, y, 200, 60) for y in (226, 296, 366, 436, 506, 576, 646, 716)],
        ]
        source, target = cards[12], cards[13]
        points = self.route(source, target, [card for card in cards if card not in (source, target)])
        self.assertIsNotNone(points)
        group_bottom = max(card.bottom() for card in cards)
        self.assertGreaterEqual(max(point.y() for point in points), group_bottom + 28.0)
        self.assertFalse(any(290.0 < point.y() < source.top() for point in points[2:-2]))

    def test_topmost_source_returns_above_before_connecting_downward(self):
        cards = [
            QRectF(440, 40, 300, 90),
            QRectF(440, 160, 300, 90),
            QRectF(440, 280, 300, 90),
            QRectF(440, 400, 300, 90),
            QRectF(50, 520, 300, 90),
        ]
        source, target = cards[0], cards[-1]
        points = self.route(source, target, cards[1:-1])
        self.assertIsNotNone(points)
        self.assertLess(points[2].y(), source.top())
        self.assertLessEqual(min(point.y() for point in points), source.top())

    def test_top_return_keeps_fixed_margin_when_internal_gaps_are_narrow(self):
        cards = [
            QRectF(440, 90, 300, 68),
            QRectF(440, 178, 300, 68),
            QRectF(440, 266, 300, 68),
            QRectF(60, 420, 300, 68),
        ]
        source, target = cards[0], cards[-1]
        points = self.route(source, target, cards[1:-1])
        self.assertIsNotNone(points)
        group_top = min(card.top() for card in cards)
        self.assertLessEqual(min(point.y() for point in points), group_top - 28)
