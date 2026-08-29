from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from app_core.maps.death import is_death_state
from app_core.maps.keys import DEFAULT_KEYS_8, key_for_step, normalize_key_map
from app_core.maps.localize import heading_from_delta, locate_on_map
from app_core.maps.planner import pixel_to_cell, plan_path, reached_goal
from app_core.maps.record import MapRecord, effective_goal
from app_core.maps.walkability import flood_blocked, is_stuck, mark_footprints


@dataclass
class PathLoopConfig:
    match_fail_limit: int = 8
    stuck_limit: int = 8
    hold_seconds: float = 0.15
    stuck_px: float = 2.0
    arrive_px: float = 8.0
    hsv_tol: int = 12
    cell_size: int = 8
    marker: str = "圆点"
    map_rotates: bool = False
    direction_mode: str = "八向"
    key_map: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_KEYS_8))


def validate_run(
    record: MapRecord,
    death_templates: list[np.ndarray],
    marker: str,
    arrow_template: np.ndarray | None,
) -> str | None:
    if not death_templates:
        return "未配置死亡状态图"
    if marker == "箭头" and arrow_template is None:
        return "未配置箭头模板"
    try:
        effective_goal(record)
    except ValueError as exc:
        return str(exc)
    return None


def _next_step(
    path: list[tuple[int, int]],
    position: tuple[int, int],
    cell_size: int,
) -> tuple[int, int] | None:
    current_cell = pixel_to_cell(position[0], position[1], cell_size)
    for point in path:
        if pixel_to_cell(point[0], point[1], cell_size) != current_cell:
            return point
    return None


def run_path_loop(
    *,
    record: MapRecord,
    capture_minimap: Callable[[], np.ndarray | None],
    capture_frame: Callable[[], np.ndarray | None],
    death_templates: list[np.ndarray],
    arrow_template: np.ndarray | None,
    config: PathLoopConfig,
    hold_key: Callable[[str, float], bool],
    persist: Callable[[MapRecord], None],
    stop_checker: Callable[[], bool],
) -> tuple[bool, str]:
    validation_error = validate_run(record, death_templates, config.marker, arrow_template)
    if validation_error is not None:
        persist(record)
        return False, validation_error

    goal = effective_goal(record)
    keys = normalize_key_map(config.direction_mode, config.key_map)
    match_fail_count = 0
    stuck_count = 0
    last_pos: tuple[int, int] | None = None

    def finish(ok: bool, reason: str) -> tuple[bool, str]:
        persist(record)
        return ok, reason

    while True:
        if stop_checker():
            return finish(False, "已停止")

        frame = capture_frame()
        if frame is not None and is_death_state(frame, death_templates):
            continue

        minimap = capture_minimap()
        located = locate_on_map(
            minimap,
            record.image_bgr,
            marker=config.marker,
            map_rotates=config.map_rotates,
            arrow_template_bgr=arrow_template,
            last_pos=last_pos,
        )
        if not located.found:
            match_fail_count += 1
            if match_fail_count >= max(1, int(config.match_fail_limit)):
                return finish(False, "定位失败")
            continue

        match_fail_count = 0
        position = (located.x, located.y)
        if reached_goal(position, goal, radius_px=config.arrive_px):
            return finish(True, "到达终点")

        path = plan_path(
            record,
            position,
            eight=config.direction_mode == "八向",
            cell_size=config.cell_size,
        )
        next_pixel = _next_step(path, position, config.cell_size)
        if next_pixel is None:
            return finish(False, "无法规划")

        heading = located.heading_deg
        if heading is None and last_pos is not None:
            heading = heading_from_delta(last_pos, position)
        key = key_for_step(
            position,
            next_pixel,
            mode=config.direction_mode,
            key_map=keys,
            heading_deg=heading,
        )
        if not hold_key(key, config.hold_seconds):
            return finish(False, "已停止")

        if last_pos is not None and is_stuck(last_pos, position, thresh_px=config.stuck_px):
            record.walkability = flood_blocked(
                record.image_bgr,
                record.walkability,
                record.painted_blocked,
                next_pixel,
                hsv_tol=config.hsv_tol,
            )
            stuck_count += 1
            if stuck_count >= max(1, int(config.stuck_limit)):
                return finish(False, "卡住超限")
        else:
            record.walkability = mark_footprints(
                record.walkability,
                record.painted_blocked,
                [position],
            )
            stuck_count = 0
        last_pos = position
