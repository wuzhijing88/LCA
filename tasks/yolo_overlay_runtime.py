# -*- coding: utf-8 -*-
"""YOLO 检测结果的叠加层与目标追踪运行时。

包含两条独立于任务执行的后台链路：
- 叠加层绘制：原生 Win32 分层窗口（utils.window.native_detection_overlay）或 Qt 覆盖窗口，
  在目标窗口上方画出检测框；
- 目标追踪：在两次检测之间用光流/模板跟踪平滑框位置，避免叠加层抖动。

所有状态都是进程级的模块变量，由 tasks.yolo_detection 在执行时驱动，
由 app_core.runtime.runtime_image_cleanup 在停止/退出时清理。
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from tasks.task_utils import precise_sleep
from utils.window.hwnd_utils import as_hwnd
from utils.window.native_detection_overlay import Win32OverlayWindow

logger = logging.getLogger(__name__)


def close_detection_window():
    """兼容接口，已移除预览功能"""
    hide_detections_overlay()


def stop_realtime_preview():
    """兼容接口，已移除预览功能"""
    hide_detections_overlay()


def close_all_yolo_windows():
    """兼容接口，已移除预览功能"""
    hide_detections_overlay()


# 窗口绘制overlay相关
_overlay_instance = None


_overlay_lock = threading.Lock()


_overlay_event = threading.Event()


_overlay_detections = None


_overlay_hwnd = None


_overlay_frame_shape = None


_overlay_thread = None


_overlay_active = False


_overlay_shutdown_requested = False


_overlay_dirty = False


_overlay_refresh_interval = 0.05  # Lower refresh to reduce overhead, event wakes on updates.


_qt_overlay_manager = None


_qt_overlay_invoker = None


_qt_overlay_latest = None


_qt_overlay_latest_lock = threading.Lock()


_qt_overlay_pending = False


_qt_overlay_flush_scheduled = False


_overlay_force_clear = False


_overlay_force_clear_lock = threading.Lock()


_overlay_last_detections = []


_overlay_last_hwnd = None


_overlay_last_frame_shape = None


_overlay_last_update_ts = 0.0


_tracking_thread = None


_tracking_active = False


_tracking_lock = threading.Lock()


_tracking_state = None


_tracking_interval = 0.01


_tracking_downscale = 0.5


_tracking_timeout = 0.25


_tracking_max_delta = 18


_tracking_point_spread = 0.25


_tracking_min_points = 3


_tracking_flow_mad = 6.0


_tracking_jump_guard = 8.0


_tracking_deadband = 0.3


_tracking_smooth_factor = 0.62


_tracking_model_guard = 14.0


_tracking_model_guard_small = 3.0


_tracking_adaptive_min_alpha = 0.2


_tracking_adaptive_delta = 24.0


_tracking_model_fresh = 0.08


_tracking_static_exp = 0.8


_tracking_static_deadband = 0.6


_tracking_missing_timeout = 1.0


_tracking_match_iou = 0.45


_tracking_blend_alpha = 0.35


_tracking_flow_win = 11


_tracking_flow_levels = 2


_tracking_flow_iters = 10


_tracking_draw_gap = 0.05


_overlay_render_mode = "稳定优先"


_overlay_render_mode_lock = threading.Lock()


_target_not_found_log_lock = threading.Lock()


_target_not_found_log_state: Dict[str, Dict[str, Any]] = {}


_target_not_found_log_interval = 0.5


_target_not_found_state_limit = 128


_capture_fail_log_lock = threading.Lock()


_capture_fail_log_state: Dict[str, Dict[str, Any]] = {}


_capture_fail_log_interval = 1.0


_capture_fail_state_limit = 128


def _normalize_overlay_render_mode(mode_value: Any) -> str:
    # 兼容旧配置字段，但统一固定为稳定优先。
    _ = mode_value
    return "稳定优先"


def _set_overlay_render_mode(mode_value: Any) -> str:
    global _overlay_render_mode
    normalized = _normalize_overlay_render_mode(mode_value)
    with _overlay_render_mode_lock:
        _overlay_render_mode = normalized
    return normalized


def _get_overlay_hold_last_duration() -> float:
    return max(_tracking_draw_gap * 2.0, 0.12)


def _get_overlay_empty_grace() -> float:
    return max(_get_overlay_hold_last_duration(), _tracking_draw_gap * 3.0, 0.18)


def _get_overlay_stale_duration() -> float:
    return max(_tracking_draw_gap * 5.0, 0.25)


def _normalize_overlay_frame_shape(frame_shape: Any) -> Optional[Tuple[int, ...]]:
    if frame_shape is None:
        return None
    try:
        shape = tuple(int(v) for v in tuple(frame_shape)[:3])
    except Exception:
        return None
    if len(shape) < 2:
        return None
    if shape[0] <= 0 or shape[1] <= 0:
        return None
    return shape


def _normalize_overlay_detections(detections: Optional[List[Any]]) -> List[Dict[str, Any]]:
    if not detections:
        return []

    normalized: List[Dict[str, Any]] = []
    now = time.perf_counter()
    for det in detections:
        try:
            if isinstance(det, dict):
                x1 = det.get("x1")
                y1 = det.get("y1")
                x2 = det.get("x2")
                y2 = det.get("y2")
                class_name = str(det.get("class_name", ""))
                confidence = float(det.get("confidence", 0.0) or 0.0)
                ts = float(det.get("ts", now) or now)
                source = str(det.get("source", "model") or "model")
            else:
                x1 = getattr(det, "x1", None)
                y1 = getattr(det, "y1", None)
                x2 = getattr(det, "x2", None)
                y2 = getattr(det, "y2", None)
                class_name = str(getattr(det, "class_name", ""))
                confidence = float(getattr(det, "confidence", 0.0) or 0.0)
                ts = float(getattr(det, "ts", now) or now)
                source = str(getattr(det, "source", "model") or "model")
            if None in (x1, y1, x2, y2):
                continue

            nx1 = int(round(float(x1)))
            ny1 = int(round(float(y1)))
            nx2 = int(round(float(x2)))
            ny2 = int(round(float(y2)))
            if nx2 <= nx1:
                nx2 = nx1 + 1
            if ny2 <= ny1:
                ny2 = ny1 + 1

            normalized.append({
                "x1": nx1,
                "y1": ny1,
                "x2": nx2,
                "y2": ny2,
                "class_name": class_name,
                "confidence": confidence,
                "ts": ts,
                "source": source,
            })
        except Exception:
            continue

    return normalized


def _clear_native_overlay_cache_locked() -> None:
    global _overlay_last_detections, _overlay_last_hwnd, _overlay_last_frame_shape, _overlay_last_update_ts
    _overlay_last_detections = []
    _overlay_last_hwnd = None
    _overlay_last_frame_shape = None
    _overlay_last_update_ts = 0.0


def _clear_overlay_runtime_state_locked() -> None:
    global _overlay_detections, _overlay_hwnd, _overlay_frame_shape, _overlay_dirty
    _overlay_detections = None
    _overlay_hwnd = None
    _overlay_frame_shape = None
    _overlay_dirty = True
    _clear_native_overlay_cache_locked()


def _reset_overlay_singleton_reference() -> None:
    overlay_cls = globals().get("Win32OverlayWindow")
    if overlay_cls is None:
        return
    try:
        overlay_cls._instance = None
    except Exception:
        pass


def _get_overlay_render_mode() -> str:
    with _overlay_render_mode_lock:
        return _overlay_render_mode


def _make_target_not_found_key(card_id: Optional[int], hwnd: Optional[int], target_classes: Optional[List[str]]) -> str:
    card_key = str(card_id) if card_id is not None else "none"
    hwnd_key = str(int(hwnd)) if hwnd else "0"
    class_key = ",".join(sorted([str(name).strip() for name in (target_classes or []) if str(name).strip()])) or "all"
    return f"{card_key}:{hwnd_key}:{class_key}"


def _log_target_not_found_throttled(card_id: Optional[int], hwnd: Optional[int], target_classes: Optional[List[str]]) -> None:
    key = _make_target_not_found_key(card_id, hwnd, target_classes)
    now = time.perf_counter()
    with _target_not_found_log_lock:
        state = _target_not_found_log_state.get(key)
        if state is None:
            if len(_target_not_found_log_state) >= _target_not_found_state_limit:
                oldest_key = None
                oldest_ts = now
                for existing_key, existing_state in _target_not_found_log_state.items():
                    ts = float(existing_state.get("last_ts", now))
                    if ts <= oldest_ts:
                        oldest_ts = ts
                        oldest_key = existing_key
                if oldest_key is not None:
                    _target_not_found_log_state.pop(oldest_key, None)
            state = {"last_ts": 0.0, "suppressed": 0}
            _target_not_found_log_state[key] = state

        last_ts = float(state.get("last_ts", 0.0))
        if (now - last_ts) >= _target_not_found_log_interval:
            suppressed = int(state.get("suppressed", 0))
            state["last_ts"] = now
            state["suppressed"] = 0
            if suppressed > 0:
                logger.warning("Target not detected (suppressed=%d)", suppressed)
            else:
                logger.warning("Target not detected")
        else:
            state["suppressed"] = int(state.get("suppressed", 0)) + 1


def _clear_target_not_found_state(card_id: Optional[int], hwnd: Optional[int], target_classes: Optional[List[str]]) -> None:
    key = _make_target_not_found_key(card_id, hwnd, target_classes)
    with _target_not_found_log_lock:
        _target_not_found_log_state.pop(key, None)


def _make_capture_fail_key(card_id: Optional[int], hwnd: Optional[int]) -> str:
    card_key = str(card_id) if card_id is not None else "none"
    hwnd_key = str(int(hwnd)) if hwnd else "0"
    return f"{card_key}:{hwnd_key}"


def _log_capture_fail_throttled(card_id: Optional[int], hwnd: Optional[int], reason: str) -> None:
    key = _make_capture_fail_key(card_id, hwnd)
    now = time.perf_counter()
    with _capture_fail_log_lock:
        state = _capture_fail_log_state.get(key)
        if state is None:
            if len(_capture_fail_log_state) >= _capture_fail_state_limit:
                oldest_key = None
                oldest_ts = now
                for existing_key, existing_state in _capture_fail_log_state.items():
                    ts = float(existing_state.get("last_ts", now))
                    if ts <= oldest_ts:
                        oldest_ts = ts
                        oldest_key = existing_key
                if oldest_key is not None:
                    _capture_fail_log_state.pop(oldest_key, None)
            state = {"last_ts": 0.0, "suppressed": 0}
            _capture_fail_log_state[key] = state

        last_ts = float(state.get("last_ts", 0.0))
        if (now - last_ts) >= _capture_fail_log_interval:
            suppressed = int(state.get("suppressed", 0))
            state["last_ts"] = now
            state["suppressed"] = 0
            if suppressed > 0:
                logger.warning("YOLO截图失败(%s), suppressed=%d", reason, suppressed)
            else:
                logger.warning("YOLO截图失败(%s)", reason)
        else:
            state["suppressed"] = int(state.get("suppressed", 0)) + 1


def _clear_capture_fail_state(card_id: Optional[int], hwnd: Optional[int]) -> None:
    key = _make_capture_fail_key(card_id, hwnd)
    with _capture_fail_log_lock:
        _capture_fail_log_state.pop(key, None)


def _is_tracking_state_live(state: Optional[Dict[str, Any]], now_ts: Optional[float] = None) -> bool:
    if not isinstance(state, dict):
        return False
    boxes = state.get("boxes") or []
    if not boxes:
        return False
    try:
        last_update = float(state.get("last_update", 0.0))
    except Exception:
        last_update = 0.0
    if last_update <= 0.0:
        return False
    if now_ts is None:
        now_ts = time.perf_counter()
    max_age = max(_tracking_timeout, _tracking_draw_gap, 0.08)
    return (now_ts - last_update) <= max_age


def _box_iou(box_a: Dict[str, Any], box_b: Dict[str, Any]) -> float:
    try:
        ax1 = float(box_a.get("x1", 0.0))
        ay1 = float(box_a.get("y1", 0.0))
        ax2 = float(box_a.get("x2", 0.0))
        ay2 = float(box_a.get("y2", 0.0))
        bx1 = float(box_b.get("x1", 0.0))
        by1 = float(box_b.get("y1", 0.0))
        bx2 = float(box_b.get("x2", 0.0))
        by2 = float(box_b.get("y2", 0.0))
    except Exception:
        return 0.0

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    iw = max(0.0, inter_x2 - inter_x1)
    ih = max(0.0, inter_y2 - inter_y1)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    a_area = max(1.0, (ax2 - ax1) * (ay2 - ay1))
    b_area = max(1.0, (bx2 - bx1) * (by2 - by1))
    return inter / float(a_area + b_area - inter)


def _box_center_distance(box_a: Dict[str, Any], box_b: Dict[str, Any]) -> float:
    ax = (float(box_a.get("x1", 0.0)) + float(box_a.get("x2", 0.0))) * 0.5
    ay = (float(box_a.get("y1", 0.0)) + float(box_a.get("y2", 0.0))) * 0.5
    bx = (float(box_b.get("x1", 0.0)) + float(box_b.get("x2", 0.0))) * 0.5
    by = (float(box_b.get("y1", 0.0)) + float(box_b.get("y2", 0.0))) * 0.5
    return math.hypot(ax - bx, ay - by)


def _dedupe_boxes(
    boxes: List[Dict[str, Any]],
    iou_threshold: float = 0.72,
    center_threshold: float = 6.0,
) -> List[Dict[str, Any]]:
    if not boxes:
        return []

    ranked = []
    for box in boxes:
        if not isinstance(box, dict):
            continue
        try:
            x1 = int(box.get("x1", 0))
            y1 = int(box.get("y1", 0))
            x2 = int(box.get("x2", 0))
            y2 = int(box.get("y2", 0))
        except Exception:
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        data = dict(box)
        data["x1"] = x1
        data["y1"] = y1
        data["x2"] = x2
        data["y2"] = y2
        conf = float(data.get("confidence", 0.0) or 0.0)
        hits = int(data.get("hits", 0) or 0)
        last_seen = float(data.get("last_seen", data.get("ts", 0.0)) or 0.0)
        ranked.append((conf, hits, last_seen, data))

    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    merged: List[Dict[str, Any]] = []
    for _, _, _, box in ranked:
        merged_index = -1
        for idx, kept in enumerate(merged):
            if str(kept.get("class_name", "")) != str(box.get("class_name", "")):
                continue
            iou = _box_iou(kept, box)
            distance = _box_center_distance(kept, box)
            kw = max(1.0, float(kept["x2"] - kept["x1"]))
            kh = max(1.0, float(kept["y2"] - kept["y1"]))
            bw = max(1.0, float(box["x2"] - box["x1"]))
            bh = max(1.0, float(box["y2"] - box["y1"]))
            dynamic_center_limit = max(center_threshold, 0.12 * max(kw, kh, bw, bh))
            w_ratio = min(kw, bw) / max(kw, bw)
            h_ratio = min(kh, bh) / max(kh, bh)
            size_similarity = min(w_ratio, h_ratio)
            center_merge_ok = distance <= dynamic_center_limit and size_similarity >= 0.55
            if iou >= iou_threshold or center_merge_ok:
                merged_index = idx
                break

        if merged_index < 0:
            merged.append(dict(box))
            continue

        kept = merged[merged_index]
        kept_conf = float(kept.get("confidence", 0.0) or 0.0)
        box_conf = float(box.get("confidence", 0.0) or 0.0)
        kept_hits = float(int(kept.get("hits", 0) or 0))
        box_hits = float(int(box.get("hits", 0) or 0))
        weight_kept = max(0.2, kept_conf + 0.02 * kept_hits)
        weight_box = max(0.2, box_conf + 0.02 * box_hits)
        total_weight = weight_kept + weight_box

        nx1 = int(round((kept["x1"] * weight_kept + box["x1"] * weight_box) / total_weight))
        ny1 = int(round((kept["y1"] * weight_kept + box["y1"] * weight_box) / total_weight))
        nx2 = int(round((kept["x2"] * weight_kept + box["x2"] * weight_box) / total_weight))
        ny2 = int(round((kept["y2"] * weight_kept + box["y2"] * weight_box) / total_weight))
        if nx2 <= nx1:
            nx2 = nx1 + 1
        if ny2 <= ny1:
            ny2 = ny1 + 1

        kept["x1"] = nx1
        kept["y1"] = ny1
        kept["x2"] = nx2
        kept["y2"] = ny2
        kept["confidence"] = max(kept_conf, box_conf)
        kept["hits"] = max(int(kept_hits), int(box_hits))
        kept["last_seen"] = max(
            float(kept.get("last_seen", kept.get("ts", 0.0)) or 0.0),
            float(box.get("last_seen", box.get("ts", 0.0)) or 0.0),
        )
        kept["ts"] = max(
            float(kept.get("ts", 0.0) or 0.0),
            float(box.get("ts", 0.0) or 0.0),
        )
        kept["vx"] = (
            float(kept.get("vx", 0.0) or 0.0) * weight_kept
            + float(box.get("vx", 0.0) or 0.0) * weight_box
        ) / total_weight
        kept["vy"] = (
            float(kept.get("vy", 0.0) or 0.0) * weight_kept
            + float(box.get("vy", 0.0) or 0.0) * weight_box
        ) / total_weight

    return merged


def _overlay_drawing_loop():
    """Background draw loop driven by an event with a low-rate fallback tick."""
    global _overlay_instance, _overlay_active, _overlay_detections, _overlay_hwnd, _overlay_frame_shape, _overlay_dirty
    global _overlay_force_clear
    global _overlay_last_detections, _overlay_last_hwnd, _overlay_last_frame_shape, _overlay_last_update_ts
    global _overlay_thread, _overlay_shutdown_requested

    current_thread = threading.current_thread()

    try:
        while True:
            with _overlay_lock:
                is_active = bool(_overlay_active)
                shutdown_requested = bool(_overlay_shutdown_requested)
            if shutdown_requested:
                break

            _overlay_event.wait(_overlay_refresh_interval if is_active else None)
            _overlay_event.clear()

            with _overlay_lock:
                is_active = bool(_overlay_active)
                shutdown_requested = bool(_overlay_shutdown_requested)
                overlay_ref = _overlay_instance
            if shutdown_requested:
                break
            if not is_active:
                if overlay_ref is not None:
                    try:
                        overlay_ref.hide()
                    except Exception:
                        pass
                continue

            try:
                with _overlay_lock:
                    if _overlay_instance is None:
                        _overlay_instance = Win32OverlayWindow.get_instance()
                    hwnd = _overlay_hwnd
                    detections = _overlay_detections
                    frame_shape = _overlay_frame_shape
                    last_detections = list(_overlay_last_detections)
                    last_hwnd = _overlay_last_hwnd
                    last_frame_shape = _overlay_last_frame_shape
                    last_update_ts = _overlay_last_update_ts
                    force_redraw = _overlay_dirty
                    _overlay_dirty = False

                now = time.perf_counter()
                stale_duration = _get_overlay_stale_duration()
                hold_last_duration = _get_overlay_hold_last_duration()
                empty_grace = _get_overlay_empty_grace()
                with _overlay_force_clear_lock:
                    force_clear = bool(_overlay_force_clear)
                    if force_clear:
                        _overlay_force_clear = False

                if as_hwnd(hwnd) == 0:
                    if _overlay_instance is not None:
                        _overlay_instance.hide()
                    with _overlay_lock:
                        _overlay_detections = []
                        _overlay_hwnd = None
                        _overlay_frame_shape = None
                        _clear_native_overlay_cache_locked()
                    continue

                render_detections = detections
                render_frame_shape = frame_shape

                if render_detections:
                    if last_update_ts > 0.0 and now - last_update_ts > stale_duration:
                        if _overlay_instance is not None:
                            _overlay_instance.hide()
                        with _overlay_lock:
                            _overlay_detections = []
                            _overlay_hwnd = hwnd
                            _overlay_frame_shape = frame_shape
                            _clear_native_overlay_cache_locked()
                        continue
                else:
                    if force_clear:
                        if _overlay_instance is not None:
                            _overlay_instance.hide()
                        with _overlay_lock:
                            _overlay_detections = []
                            _overlay_frame_shape = frame_shape
                            _clear_native_overlay_cache_locked()
                        continue
                    if int(last_hwnd or 0) != int(hwnd or 0) or not last_detections or last_update_ts <= 0.0:
                        if _overlay_instance is not None:
                            _overlay_instance.hide()
                        with _overlay_lock:
                            _overlay_detections = []
                            _overlay_frame_shape = frame_shape
                            _clear_native_overlay_cache_locked()
                        continue

                    age = now - last_update_ts
                    if age > stale_duration or age > empty_grace:
                        if _overlay_instance is not None:
                            _overlay_instance.hide()
                        with _overlay_lock:
                            _overlay_detections = []
                            _overlay_frame_shape = frame_shape
                            _clear_native_overlay_cache_locked()
                        continue

                    if age <= hold_last_duration:
                        render_detections = last_detections
                        render_frame_shape = last_frame_shape or frame_shape
                        force_redraw = True
                    else:
                        continue

                if not render_detections:
                    if _overlay_instance is not None:
                        _overlay_instance.hide()
                    continue

                _overlay_instance.render(hwnd, render_detections, render_frame_shape, force_redraw=force_redraw)
            except Exception as e:
                logger.debug(f"悬浮绘制循环失败：{e}")
    finally:
        overlay_ref = None
        should_shutdown = False
        with _overlay_lock:
            overlay_ref = _overlay_instance
            should_shutdown = bool(_overlay_shutdown_requested)
            if should_shutdown:
                _overlay_instance = None
            if _overlay_thread is current_thread:
                _overlay_thread = None
            _overlay_active = False
            _overlay_shutdown_requested = False
            _clear_overlay_runtime_state_locked()

        if overlay_ref is not None:
            try:
                overlay_ref.hide()
            except Exception:
                pass
        if should_shutdown and overlay_ref is not None:
            try:
                overlay_ref.shutdown()
            except Exception:
                pass
        if should_shutdown:
            _reset_overlay_singleton_reference()


def _draw_detections_with_qt(hwnd: int, detections: List, frame_shape: Tuple) -> bool:
    try:
        from PySide6.QtWidgets import QApplication, QWidget
        from PySide6.QtCore import Qt, QTimer, QThread, QObject, Signal
        from PySide6.QtGui import QPainter, QPen, QColor, QFont
    except Exception:
        return False

    app = QApplication.instance()
    if app is None:
        return False

    if not detections:
        now_ts = time.perf_counter()
        with _tracking_lock:
            tracking_state = _tracking_state
        if _is_tracking_state_live(tracking_state, now_ts):
            return True

    def normalize_detections():
        if not detections:
            return []
        normalized = []
        now = time.perf_counter()
        for det in detections:
            try:
                if isinstance(det, dict):
                    normalized.append({
                        "x1": int(det.get("x1", 0)),
                        "y1": int(det.get("y1", 0)),
                        "x2": int(det.get("x2", 0)),
                        "y2": int(det.get("y2", 0)),
                        "class_name": str(det.get("class_name", "")),
                        "confidence": float(det.get("confidence", 0.0)),
                        "vx": float(det.get("vx", 0.0)),
                        "vy": float(det.get("vy", 0.0)),
                        "ts": float(det.get("ts", now)),
                        "source": det.get("source", "model"),
                    })
                    continue

                x1 = getattr(det, "x1", None)
                y1 = getattr(det, "y1", None)
                x2 = getattr(det, "x2", None)
                y2 = getattr(det, "y2", None)
                if x1 is None or y1 is None or x2 is None or y2 is None:
                    continue

                normalized.append({
                    "x1": int(x1),
                    "y1": int(y1),
                    "x2": int(x2),
                    "y2": int(y2),
                    "class_name": str(getattr(det, "class_name", "")),
                    "confidence": float(getattr(det, "confidence", 0.0)),
                    "vx": float(getattr(det, "vx", 0.0)),
                    "vy": float(getattr(det, "vy", 0.0)),
                    "ts": float(getattr(det, "ts", now)),
                    "source": getattr(det, "source", "model"),
                })
            except Exception:
                continue
        return normalized

    global _qt_overlay_latest, _qt_overlay_pending, _qt_overlay_manager
    global _qt_overlay_flush_scheduled, _qt_overlay_invoker
    normalized = normalize_detections()
    with _qt_overlay_latest_lock:
        _qt_overlay_latest = (hwnd, normalized, frame_shape)
        _qt_overlay_pending = True

    # 快速路径：manager 已存在时直接更新，避免重复执行下面的类定义逻辑。
    existing_manager = _qt_overlay_manager
    if existing_manager is not None:
        def flush_existing_manager():
            global _qt_overlay_flush_scheduled, _qt_overlay_pending, _qt_overlay_latest
            _qt_overlay_flush_scheduled = False
            with _qt_overlay_latest_lock:
                if not _qt_overlay_pending:
                    return
                data = _qt_overlay_latest
                _qt_overlay_pending = False

            manager = _qt_overlay_manager
            if manager is None:
                return
            if not data:
                manager.hide_overlay()
                return

            target_hwnd, dets, frame_shape_value = data
            manager.update_overlay(target_hwnd, dets, frame_shape_value)

        if not _qt_overlay_flush_scheduled:
            _qt_overlay_flush_scheduled = True
            if QThread.currentThread() == app.thread():
                flush_existing_manager()
            else:
                if _qt_overlay_invoker is None:
                    class Invoker(QObject):
                        invoke = Signal(object)

                        def __init__(self):
                            super().__init__()
                            self.invoke.connect(self._run)

                        def _run(self, callback):
                            try:
                                callback()
                            except Exception:
                                pass

                    invoker = Invoker()
                    invoker.moveToThread(app.thread())
                    _qt_overlay_invoker = invoker

                _qt_overlay_invoker.invoke.emit(flush_existing_manager)
        return True

    class _YoloOverlayWidget(QWidget):
        def __init__(self, target_hwnd: int):
            super().__init__(None)
            self.target_hwnd = target_hwnd
            self._detections = []
            self._frame_shape = None
            self._client_native_rect = None
            self._client_physical_size = (0, 0)
            self._pen = QPen(QColor(0, 255, 0), 2)
            self._font = QFont("Microsoft YaHei", 9)
            # 低延迟补偿：在检测帧之间做轻量速度外推，降低视觉拖尾。
            self._prediction_max_dt = 0.05
            self._prediction_drop_dt = 0.12
            self._prediction_lead = 1.0
            self._latency_compensation = 0.008
            self._prediction_max_offset = 20.0

            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool |
                Qt.WindowType.WindowTransparentForInput
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

            self._timer = QTimer(self)
            self._timer.timeout.connect(self._position_overlay)
            repaint_interval = 10
            self._timer.start(repaint_interval)
            self._repaint_timer = QTimer(self)
            self._repaint_timer.timeout.connect(self.update)
            self._repaint_timer.start(repaint_interval)
            self._position_overlay()

        def _position_overlay(self):
            try:
                from utils.window.window_overlay_utils import (
                    get_window_client_overlay_metrics,
                    sync_overlay_geometry,
                )

                sync_overlay_geometry(self)
                metrics = get_window_client_overlay_metrics(self.target_hwnd)
                if not metrics:
                    self.hide()
                    return
                native_rect = metrics.get("native_rect")
                if not native_rect or len(native_rect) != 4:
                    self.hide()
                    return
                self._client_native_rect = tuple(int(v) for v in native_rect)
                physical_size = metrics.get("physical_size", (0, 0))
                self._client_physical_size = (
                    max(1, int(physical_size[0])) if len(physical_size) >= 1 else 1,
                    max(1, int(physical_size[1])) if len(physical_size) >= 2 else 1,
                )
            except Exception as e:
                logger.debug(f"Qt 悬浮层定位失败：{e}")

        def update_detections(self, new_detections: List, frame_shape_value: Tuple):
            self._detections = new_detections or []
            self._frame_shape = frame_shape_value
            if not self.isVisible():
                self.show()
            self._position_overlay()
            self.update()

        def paintEvent(self, event):
            if not self._detections:
                return

            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            if not self._client_native_rect or len(self._client_native_rect) != 4:
                painter.end()
                return

            from utils.window.window_overlay_utils import map_native_rect_to_local

            client_left, client_top, client_right, client_bottom = self._client_native_rect
            client_w = max(1, int(client_right - client_left))
            client_h = max(1, int(client_bottom - client_top))

            source_w = client_w
            source_h = client_h
            if self._client_physical_size[0] > 0 and self._client_physical_size[1] > 0:
                source_w, source_h = self._client_physical_size
            if self._frame_shape and len(self._frame_shape) >= 2:
                source_h = int(self._frame_shape[0])
                source_w = int(self._frame_shape[1])

            scale_x = client_w / float(source_w) if source_w > 0 else 1.0
            scale_y = client_h / float(source_h) if source_h > 0 else 1.0

            painter.setPen(self._pen)
            painter.setFont(self._font)

            now = time.perf_counter()

            for det in self._detections:
                source = det.get("source")
                ts = det.get("ts", now)
                dt = now - ts
                if dt > self._prediction_drop_dt:
                    continue
                if dt < 0:
                    dt = 0
                if source == "tracking" or (source == "model" and _tracking_active):
                    dt = 0.0
                    vx = 0.0
                    vy = 0.0
                else:
                    dt = min((dt + self._latency_compensation) * self._prediction_lead, self._prediction_max_dt)
                    vx = det.get("vx", 0.0)
                    vy = det.get("vy", 0.0)
                dx = vx * dt
                dy = vy * dt
                if dt > 0:
                    if dx > self._prediction_max_offset:
                        dx = self._prediction_max_offset
                    elif dx < -self._prediction_max_offset:
                        dx = -self._prediction_max_offset
                    if dy > self._prediction_max_offset:
                        dy = self._prediction_max_offset
                    elif dy < -self._prediction_max_offset:
                        dy = -self._prediction_max_offset
                px1 = det["x1"] + dx
                py1 = det["y1"] + dy
                px2 = det["x2"] + dx
                py2 = det["y2"] + dy

                native_left = int(round(client_left + (px1 * scale_x)))
                native_top = int(round(client_top + (py1 * scale_y)))
                native_right = int(round(client_left + (px2 * scale_x)))
                native_bottom = int(round(client_top + (py2 * scale_y)))
                if native_right <= native_left:
                    native_right = native_left + 1
                if native_bottom <= native_top:
                    native_bottom = native_top + 1

                draw_rect = map_native_rect_to_local(
                    self,
                    (native_left, native_top, native_right, native_bottom),
                )
                if draw_rect.isEmpty():
                    continue

                painter.drawRect(draw_rect)
                label = f'{det["class_name"]} {det["confidence"]:.2f}'
                painter.drawText(int(draw_rect.left()), max(0, int(draw_rect.top()) - 4), label)

            painter.end()

        def closeEvent(self, event):
            try:
                if self._timer:
                    self._timer.stop()
                if self._repaint_timer:
                    self._repaint_timer.stop()
            except Exception:
                pass
            super().closeEvent(event)

    class _YoloOverlayManager(QObject):
        def __init__(self):
            super().__init__()
            self.overlay = None
            self._last_update_ts = 0.0
            self._last_dets = []
            self._last_frame_shape = None
            self._last_hwnd = None
            self._tracks = []
            self._render_mode = "稳定优先"
            self._smoothing_alpha = 0.34
            self._velocity_alpha = 0.28
            self._jitter_threshold = 2
            self._track_iou_threshold = 0.33
            self._track_ttl = 0.10
            self._min_hits = 1
            self._empty_grace = _get_overlay_empty_grace()
            self._stale_duration = _get_overlay_stale_duration()
            self._hold_last_duration = _get_overlay_hold_last_duration()
            self._confidence_alpha_up = 0.35
            self._confidence_alpha_down = 0.08
            self._confidence_hold_motion = 4
            self._max_tracks = 64
            self._apply_render_mode(_get_overlay_render_mode())
            self._cleanup_timer = QTimer(self)
            self._cleanup_timer.timeout.connect(self._cleanup_if_stale)
            self._cleanup_timer.start(50)

        @staticmethod
        def _promote_overlay_window(widget):
            try:
                import ctypes

                hwnd = as_hwnd(widget.winId())
                if hwnd == 0:
                    return

                user32 = ctypes.windll.user32
                user32.SetWindowPos(
                    hwnd,
                    -1,
                    0,
                    0,
                    0,
                    0,
                    0x0001 | 0x0002 | 0x0010 | 0x0040,
                )
            except Exception:
                pass

        def _apply_render_mode(self, mode_value: Any) -> None:
            mode = _normalize_overlay_render_mode(mode_value)
            if mode == self._render_mode:
                return
            self._render_mode = mode
            self._smoothing_alpha = 0.34
            self._velocity_alpha = 0.28
            self._jitter_threshold = 2
            self._track_iou_threshold = 0.33
            self._track_ttl = 0.10
            self._empty_grace = _get_overlay_empty_grace()
            self._stale_duration = _get_overlay_stale_duration()
            self._hold_last_duration = _get_overlay_hold_last_duration()
            repaint_interval = 10
            if self.overlay is not None:
                try:
                    if hasattr(self.overlay, "_timer") and self.overlay._timer is not None:
                        self.overlay._timer.setInterval(repaint_interval)
                    if hasattr(self.overlay, "_repaint_timer") and self.overlay._repaint_timer is not None:
                        self.overlay._repaint_timer.setInterval(repaint_interval)
                except Exception:
                    pass

        def _cleanup_if_stale(self):
            if self.overlay is None:
                return
            if self._last_update_ts <= 0:
                return
            if time.perf_counter() - self._last_update_ts > self._stale_duration:
                self.hide_overlay()

        def _track_and_smooth(self, dets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            def _iou(a: Dict[str, Any], b: Dict[str, Any]) -> float:
                ax1, ay1, ax2, ay2 = a["x1"], a["y1"], a["x2"], a["y2"]
                bx1, by1, bx2, by2 = b["x1"], b["y1"], b["x2"], b["y2"]
                inter_x1 = max(ax1, bx1)
                inter_y1 = max(ay1, by1)
                inter_x2 = min(ax2, bx2)
                inter_y2 = min(ay2, by2)
                iw = max(0, inter_x2 - inter_x1)
                ih = max(0, inter_y2 - inter_y1)
                inter = iw * ih
                if inter <= 0:
                    return 0.0
                a_area = max(1, (ax2 - ax1) * (ay2 - ay1))
                b_area = max(1, (bx2 - bx1) * (by2 - by1))
                return inter / float(a_area + b_area - inter)

            now = time.perf_counter()
            tracking_update = bool(dets) and all(det.get("source") == "tracking" for det in dets)
            if tracking_update:
                smoothing_alpha = min(self._smoothing_alpha, 0.28)
                jitter_threshold = max(self._jitter_threshold, 2)
            else:
                smoothing_alpha = self._smoothing_alpha
                jitter_threshold = self._jitter_threshold
            dets = _dedupe_boxes(dets, iou_threshold=0.75, center_threshold=6.0)

            def _center(box: Dict[str, Any]) -> Tuple[float, float]:
                return (
                    (box["x1"] + box["x2"]) / 2.0,
                    (box["y1"] + box["y2"]) / 2.0,
                )

            def _update_track_from_det(trk: Dict[str, Any], det: Dict[str, Any]) -> None:
                prev_cx = (trk["x1"] + trk["x2"]) / 2.0
                prev_cy = (trk["y1"] + trk["y2"]) / 2.0
                new_cx = (det["x1"] + det["x2"]) / 2.0
                new_cy = (det["y1"] + det["y2"]) / 2.0
                dt = max(1e-3, now - trk.get("last_seen", now))
                raw_vx = (new_cx - prev_cx) / dt
                raw_vy = (new_cy - prev_cy) / dt
                source = det.get("source")
                prev_w = max(2.0, float(trk["x2"] - trk["x1"]))
                prev_h = max(2.0, float(trk["y2"] - trk["y1"]))
                motion_dist = math.hypot(new_cx - prev_cx, new_cy - prev_cy)
                motion_scale = max(8.0, (prev_w + prev_h) * 0.35)
                motion_ratio = min(1.0, motion_dist / motion_scale)

                # 自适应平滑：静止时保持稳定，快速位移时快速贴合，降低“框拖尾”。
                alpha = smoothing_alpha + (1.0 - smoothing_alpha) * (0.82 * motion_ratio)
                if source == "tracking":
                    alpha = min(alpha, 0.62)
                if source == "tracking":
                    # 纯tracking帧只更新中心，宽高冻结，避免“时大时小”抖动。
                    target_w = prev_w
                    target_h = prev_h
                    size_alpha = 0.0
                else:
                    target_w = max(2.0, float(det["x2"] - det["x1"]))
                    target_h = max(2.0, float(det["y2"] - det["y1"]))
                    size_ratio_limit = 1.10
                    min_ratio_limit = 1.0 / size_ratio_limit
                    target_w = max(prev_w * min_ratio_limit, min(target_w, prev_w * size_ratio_limit))
                    target_h = max(prev_h * min_ratio_limit, min(target_h, prev_h * size_ratio_limit))
                    size_alpha = min(0.5, min(alpha, 0.22) + 0.18 * motion_ratio)
                smooth_cx = prev_cx + alpha * (new_cx - prev_cx)
                smooth_cy = prev_cy + alpha * (new_cy - prev_cy)
                smooth_w = prev_w + size_alpha * (target_w - prev_w)
                smooth_h = prev_h + size_alpha * (target_h - prev_h)

                deadband = max(0.25, (jitter_threshold * 0.5) * (1.0 - 0.85 * motion_ratio))
                if abs(smooth_cx - prev_cx) < deadband:
                    smooth_cx = prev_cx
                if abs(smooth_cy - prev_cy) < deadband:
                    smooth_cy = prev_cy
                if abs(smooth_w - prev_w) < 1.0:
                    smooth_w = prev_w
                if abs(smooth_h - prev_h) < 1.0:
                    smooth_h = prev_h

                sx1 = int(round(smooth_cx - smooth_w * 0.5))
                sy1 = int(round(smooth_cy - smooth_h * 0.5))
                sx2 = int(round(smooth_cx + smooth_w * 0.5))
                sy2 = int(round(smooth_cy + smooth_h * 0.5))
                if sx2 <= sx1:
                    sx2 = sx1 + 1
                if sy2 <= sy1:
                    sy2 = sy1 + 1

                prev_vx = trk.get("vx", raw_vx)
                prev_vy = trk.get("vy", raw_vy)
                v_alpha = min(0.85, self._velocity_alpha + 0.35 * motion_ratio)
                if source == "tracking":
                    v_alpha = min(v_alpha, 0.62)
                vx = prev_vx + v_alpha * (raw_vx - prev_vx)
                vy = prev_vy + v_alpha * (raw_vy - prev_vy)

                det_conf = det.get("confidence")
                prev_conf = trk.get("confidence")
                if prev_conf is None:
                    prev_conf = float(det_conf or 0.0)
                if det_conf is None:
                    det_conf = prev_conf
                det_conf = float(det_conf)
                if source == "tracking":
                    conf_value = prev_conf
                else:
                    if det_conf < prev_conf:
                        motion = max(
                            abs(det["x1"] - trk["x1"]),
                            abs(det["y1"] - trk["y1"]),
                            abs(det["x2"] - trk["x2"]),
                            abs(det["y2"] - trk["y2"]),
                        )
                        if motion <= self._confidence_hold_motion:
                            det_conf = prev_conf
                    if det_conf >= prev_conf:
                        conf_alpha = self._confidence_alpha_up
                    else:
                        conf_alpha = self._confidence_alpha_down
                    conf_value = prev_conf + conf_alpha * (det_conf - prev_conf)
                    conf_value = max(0.0, min(1.0, conf_value))

                trk.update({
                    "x1": sx1,
                    "y1": sy1,
                    "x2": sx2,
                    "y2": sy2,
                    "class_name": det.get("class_name", ""),
                    "confidence": conf_value,
                    "last_seen": now,
                    "vx": vx,
                    "vy": vy,
                    "hits": trk.get("hits", 0) + 1,
                })

            pairs = []
            for ti, trk in enumerate(self._tracks):
                for di, det in enumerate(dets):
                    if trk.get("class_name") != det.get("class_name"):
                        continue
                    iou = _iou(trk, det)
                    if iou >= self._track_iou_threshold:
                        pairs.append((iou, ti, di))
            pairs.sort(reverse=True)

            used_tracks = set()
            used_dets = set()
            for iou, ti, di in pairs:
                if ti in used_tracks or di in used_dets:
                    continue
                used_tracks.add(ti)
                used_dets.add(di)
                _update_track_from_det(self._tracks[ti], dets[di])

            if len(used_dets) < len(dets) and len(used_tracks) < len(self._tracks):
                fallback_pairs = []
                for ti, trk in enumerate(self._tracks):
                    if ti in used_tracks:
                        continue
                    tcx, tcy = _center(trk)
                    tw = max(1.0, float(trk["x2"] - trk["x1"]))
                    th = max(1.0, float(trk["y2"] - trk["y1"]))
                    gap_limit = max(14.0, 0.65 * max(tw, th) + 18.0)
                    for di, det in enumerate(dets):
                        if di in used_dets:
                            continue
                        if trk.get("class_name") != det.get("class_name"):
                            continue
                        dcx, dcy = _center(det)
                        dist = math.hypot(dcx - tcx, dcy - tcy)
                        if dist <= gap_limit:
                            fallback_pairs.append((dist, ti, di))
                fallback_pairs.sort(key=lambda item: item[0])
                for _, ti, di in fallback_pairs:
                    if ti in used_tracks or di in used_dets:
                        continue
                    used_tracks.add(ti)
                    used_dets.add(di)
                    _update_track_from_det(self._tracks[ti], dets[di])

            if not tracking_update or not self._tracks:
                for di, det in enumerate(dets):
                    if di in used_dets:
                        continue
                    self._tracks.append({
                        "x1": det["x1"],
                        "y1": det["y1"],
                        "x2": det["x2"],
                        "y2": det["y2"],
                        "class_name": det.get("class_name", ""),
                        "confidence": det.get("confidence", 0.0),
                        "last_seen": now,
                        "vx": 0.0,
                        "vy": 0.0,
                        "hits": 1,
                    })

            kept_tracks = []
            for trk in self._tracks:
                if now - trk.get("last_seen", now) <= self._track_ttl:
                    kept_tracks.append(trk)
            self._tracks = _dedupe_boxes(kept_tracks, iou_threshold=0.66, center_threshold=6.0)
            if len(self._tracks) > self._max_tracks:
                self._tracks.sort(
                    key=lambda trk: (
                        float(trk.get("confidence", 0.0) or 0.0),
                        int(trk.get("hits", 0) or 0),
                        float(trk.get("last_seen", trk.get("ts", 0.0)) or 0.0),
                    ),
                    reverse=True,
                )
                self._tracks = self._tracks[:self._max_tracks]

            visible = []
            for trk in self._tracks:
                if trk.get("hits", 0) >= self._min_hits:
                    visible.append({
                        "x1": trk["x1"],
                        "y1": trk["y1"],
                        "x2": trk["x2"],
                        "y2": trk["y2"],
                        "class_name": trk.get("class_name", ""),
                        "confidence": trk.get("confidence", 0.0),
                        "vx": trk.get("vx", 0.0),
                        "vy": trk.get("vy", 0.0),
                        "ts": trk.get("last_seen", now),
                        "source": "model",
                    })

            return visible

        def update_overlay(self, target_hwnd: int, dets: List, frame_shape_value: Tuple):
            global _overlay_force_clear
            self._apply_render_mode(_get_overlay_render_mode())
            if not dets:
                force_clear = False
                with _overlay_force_clear_lock:
                    if _overlay_force_clear:
                        force_clear = True
                        _overlay_force_clear = False
                if force_clear:
                    self.hide_overlay()
                    return
                now = time.perf_counter()
                if self.overlay is None or not self._last_dets:
                    return
                if now - self._last_update_ts <= self._hold_last_duration:
                    self.overlay.update_detections(
                        self._last_dets,
                        self._last_frame_shape or frame_shape_value,
                    )
                    return
                if now - self._last_update_ts > self._empty_grace:
                    self.hide_overlay()
                return
            if self.overlay is None or self.overlay.target_hwnd != target_hwnd:
                if self.overlay is not None:
                    self.overlay.close()
                self._tracks = []
                self._last_dets = []
                self._last_frame_shape = None
                self.overlay = _YoloOverlayWidget(target_hwnd)
                self.overlay.show()
                self.overlay.raise_()
                self.overlay.update()
                self._promote_overlay_window(self.overlay)
                QTimer.singleShot(50, lambda: self._promote_overlay_window(self.overlay))
                QTimer.singleShot(150, lambda: self._promote_overlay_window(self.overlay))
                QTimer.singleShot(300, lambda: self._promote_overlay_window(self.overlay))
            if (
                self._last_frame_shape is not None
                and frame_shape_value is not None
                and len(self._last_frame_shape) >= 2
                and len(frame_shape_value) >= 2
            ):
                old_h, old_w = int(self._last_frame_shape[0]), int(self._last_frame_shape[1])
                new_h, new_w = int(frame_shape_value[0]), int(frame_shape_value[1])
                if abs(old_h - new_h) > 2 or abs(old_w - new_w) > 2:
                    self._tracks = []
            stable = self._track_and_smooth(dets)
            self.overlay.update_detections(stable, frame_shape_value)
            self._last_update_ts = time.perf_counter()
            self._last_dets = stable
            self._last_frame_shape = frame_shape_value
            self._last_hwnd = target_hwnd
            if not stable:
                return

        def hide_overlay(self):
            if self.overlay is not None:
                self.overlay.close()
                self.overlay = None
            self._last_dets = []
            self._last_frame_shape = None
            self._last_hwnd = None
            self._last_update_ts = 0.0
            self._tracks = []

        def shutdown(self):
            try:
                if self._cleanup_timer is not None:
                    self._cleanup_timer.stop()
                    try:
                        self._cleanup_timer.timeout.disconnect()
                    except Exception:
                        pass
            except Exception:
                pass
            self.hide_overlay()

    def run_in_ui_thread(func):
        global _qt_overlay_invoker
        if QThread.currentThread() == app.thread():
            func()
            return

        if _qt_overlay_invoker is None:
            class Invoker(QObject):
                invoke = Signal(object)

                def __init__(self):
                    super().__init__()
                    self.invoke.connect(self._run)

                def _run(self, callback):
                    try:
                        callback()
                    except Exception as e:
                        logger.debug(f"Qt 悬浮层调用器执行失败：{e}")

            invoker = Invoker()
            invoker.moveToThread(app.thread())
            _qt_overlay_invoker = invoker

        _qt_overlay_invoker.invoke.emit(func)

    def flush_latest():
        global _qt_overlay_flush_scheduled, _qt_overlay_manager, _qt_overlay_pending, _qt_overlay_latest
        _qt_overlay_flush_scheduled = False
        with _qt_overlay_latest_lock:
            if not _qt_overlay_pending:
                return
            data = _qt_overlay_latest
            _qt_overlay_pending = False

        if _qt_overlay_manager is None:
            _qt_overlay_manager = _YoloOverlayManager()
            _qt_overlay_manager.moveToThread(app.thread())

        if not data:
            _qt_overlay_manager.hide_overlay()
            return

        target_hwnd, dets, frame_shape_value = data
        _qt_overlay_manager.update_overlay(target_hwnd, dets, frame_shape_value)

    if not _qt_overlay_flush_scheduled:
        _qt_overlay_flush_scheduled = True
        run_in_ui_thread(flush_latest)
    return True


def _should_use_qt_overlay(hwnd: int) -> bool:
    """
    Qt overlay 仅用于本应用自身窗口。

    外部目标窗口优先走原生 Win32 overlay；否则 Qt 分支一旦被选中，
    原生绘制链就永远不会执行，外部窗口出现静默不显示时无法兜底。
    """
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        return False

    app = QApplication.instance()
    if app is None:
        return False

    try:
        target_hwnd = as_hwnd(hwnd)
    except Exception:
        return False
    if target_hwnd == 0:
        return False

    try:
        for widget in app.topLevelWidgets():
            try:
                if as_hwnd(widget.winId()) == target_hwnd:
                    return True
            except Exception:
                continue
    except Exception:
        return False
    return False


def _schedule_native_overlay(hwnd: int, detections: List, frame_shape: Tuple) -> None:
    global _overlay_thread, _overlay_active, _overlay_hwnd, _overlay_detections, _overlay_frame_shape, _overlay_dirty
    global _overlay_last_detections, _overlay_last_hwnd, _overlay_last_frame_shape, _overlay_last_update_ts
    global _overlay_force_clear, _overlay_shutdown_requested

    normalized_detections = _normalize_overlay_detections(detections)
    normalized_frame_shape = _normalize_overlay_frame_shape(frame_shape)
    now = time.perf_counter()
    thread_to_start = None

    if normalized_detections:
        with _overlay_force_clear_lock:
            _overlay_force_clear = False

    with _overlay_lock:
        if _overlay_thread is None or not _overlay_thread.is_alive():
            thread_to_start = threading.Thread(
                target=_overlay_drawing_loop,
                daemon=True,
                name="YoloOverlayRender",
            )
            _overlay_thread = thread_to_start
        _overlay_active = True
        _overlay_shutdown_requested = False
        _overlay_hwnd = hwnd
        _overlay_detections = normalized_detections
        _overlay_frame_shape = normalized_frame_shape
        _overlay_dirty = True
        if normalized_detections:
            _overlay_last_detections = list(normalized_detections)
            _overlay_last_hwnd = hwnd
            _overlay_last_frame_shape = normalized_frame_shape
            _overlay_last_update_ts = now
        elif int(_overlay_last_hwnd or 0) != int(hwnd or 0):
            _clear_native_overlay_cache_locked()

    if thread_to_start is not None:
        thread_to_start.start()
        logger.debug("Overlay thread started")

    _overlay_event.set()


def _shutdown_native_overlay_runtime(wait_timeout: float = 1.5) -> bool:
    global _overlay_thread, _overlay_active, _overlay_shutdown_requested, _overlay_instance

    with _overlay_lock:
        thread_ref = _overlay_thread
        overlay_ref = _overlay_instance
        _overlay_active = False
        _overlay_shutdown_requested = True
        _clear_overlay_runtime_state_locked()

    with _overlay_force_clear_lock:
        global _overlay_force_clear
        _overlay_force_clear = False

    _overlay_event.set()

    if thread_ref is not None and thread_ref.is_alive():
        thread_ref.join(timeout=max(0.1, float(wait_timeout)))
        if thread_ref.is_alive():
            return False

    overlay_to_shutdown = None
    with _overlay_lock:
        if _overlay_thread is not None and not _overlay_thread.is_alive():
            _overlay_thread = None
        if _overlay_instance is not None:
            overlay_to_shutdown = _overlay_instance
            _overlay_instance = None
        _overlay_active = False
        _overlay_shutdown_requested = False
        _clear_overlay_runtime_state_locked()

    if overlay_ref is not None:
        try:
            overlay_ref.hide()
        except Exception:
            pass

    if overlay_to_shutdown is not None:
        try:
            overlay_to_shutdown.shutdown()
        except Exception:
            return False
    _reset_overlay_singleton_reference()
    return True


def _emit_overlay_update_request(executor: Any, hwnd: int, detections: List, frame_shape: Tuple) -> bool:
    signal_obj = getattr(executor, "overlay_update_requested", None)
    if signal_obj is None:
        return False

    try:
        hwnd_value = int(hwnd)
    except Exception:
        return False
    if hwnd_value <= 0:
        return False

    payload: Dict[str, Any] = {
        "action": "update",
        "hwnd": hwnd_value,
        "detections": _normalize_overlay_detections(detections),
    }
    normalized_frame_shape = _normalize_overlay_frame_shape(frame_shape)
    payload["frame_shape"] = list(normalized_frame_shape) if normalized_frame_shape is not None else None

    try:
        signal_obj.emit(payload)
        return True
    except Exception as e:
        logger.debug("悬浮层更新信号发送失败：%s", e)
        return False


def _dispatch_overlay_update(hwnd: int, detections: List, frame_shape: Tuple, executor: Any = None) -> None:
    if _emit_overlay_update_request(executor, hwnd, detections, frame_shape):
        return
    _schedule_native_overlay(hwnd, detections, frame_shape)


def _update_tracking_state(hwnd: int, detections: List, frame_shape: Tuple,
                           screenshot: Optional[np.ndarray], tracking_engine: Optional[str] = None,
                           executor: Any = None):
    global _tracking_state, _tracking_active, _tracking_thread

    if not detections:
        if screenshot is None:
            with _tracking_lock:
                _tracking_state = None
        else:
            with _tracking_lock:
                if _tracking_state is not None:
                    _tracking_state["hwnd"] = hwnd
                    if frame_shape is not None:
                        _tracking_state["frame_shape"] = frame_shape
                    if tracking_engine:
                        _tracking_state["tracking_engine"] = tracking_engine
                    _tracking_state["executor"] = executor
        return
    if screenshot is None:
        with _tracking_lock:
            _tracking_state = None
        return

    def _iou(a: Dict[str, Any], b: Dict[str, Any]) -> float:
        ax1, ay1, ax2, ay2 = a["x1"], a["y1"], a["x2"], a["y2"]
        bx1, by1, bx2, by2 = b["x1"], b["y1"], b["x2"], b["y2"]
        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        iw = max(0, inter_x2 - inter_x1)
        ih = max(0, inter_y2 - inter_y1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        a_area = max(1, (ax2 - ax1) * (ay2 - ay1))
        b_area = max(1, (bx2 - bx1) * (by2 - by1))
        return inter / float(a_area + b_area - inter)

    try:
        prev_state = None
        with _tracking_lock:
            prev_state = _tracking_state
        try:
            if prev_state and int(prev_state.get("hwnd") or 0) != int(hwnd or 0):
                prev_state = None
        except Exception:
            prev_state = None
        prev_model_boxes = []
        prev_model_ts = None
        if prev_state:
            prev_model_boxes = prev_state.get("model_boxes") or []
            prev_model_ts = prev_state.get("last_model_update")

        frame = screenshot
        if len(frame.shape) == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        elif len(frame.shape) == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

        frame_h, frame_w = frame.shape[:2]
        if frame_shape and len(frame_shape) >= 2:
            src_h = int(frame_shape[0])
            src_w = int(frame_shape[1])
            # 跟踪帧与检测帧尺寸不一致时，直接禁用跟踪，避免跨坐标系抖动。
            if abs(frame_h - src_h) > 2 or abs(frame_w - src_w) > 2:
                with _tracking_lock:
                    _tracking_state = None
                return

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if _tracking_downscale != 1.0:
            gray = cv2.resize(gray, None, fx=_tracking_downscale, fy=_tracking_downscale, interpolation=cv2.INTER_LINEAR)

        boxes = []
        model_boxes = []
        now = time.perf_counter()
        for det in detections:
            x1 = int(det.x1)
            y1 = int(det.y1)
            x2 = int(det.x2)
            y2 = int(det.y2)
            if frame_shape and len(frame_shape) >= 2:
                max_h, max_w = frame_shape[:2]
                x1 = max(0, min(x1, max_w - 1))
                x2 = max(0, min(x2, max_w - 1))
                y1 = max(0, min(y1, max_h - 1))
                y2 = max(0, min(y2, max_h - 1))
            boxes.append({
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "class_name": str(det.class_name),
                "confidence": float(det.confidence),
                "vx": 0.0,
                "vy": 0.0,
                "dx": 0.0,
                "dy": 0.0,
                "ts": now,
            })
            model_boxes.append({
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "class_name": str(det.class_name),
                "confidence": float(det.confidence),
                "vx": 0.0,
                "vy": 0.0,
                "ts": now,
            })

        if prev_model_boxes:
            dt_model = max(1e-3, now - (prev_model_ts or now))
            pairs = []
            for pi, prev_box in enumerate(prev_model_boxes):
                for ci, cur_box in enumerate(model_boxes):
                    if prev_box.get("class_name") != cur_box.get("class_name"):
                        continue
                    iou = _iou(prev_box, cur_box)
                    if iou >= _tracking_match_iou:
                        pairs.append((iou, pi, ci))
            pairs.sort(reverse=True)
            used_prev = set()
            used_cur = set()
            for _, pi, ci in pairs:
                if pi in used_prev or ci in used_cur:
                    continue
                used_prev.add(pi)
                used_cur.add(ci)
                prev_box = prev_model_boxes[pi]
                cur_box = model_boxes[ci]
                prev_cx = (prev_box["x1"] + prev_box["x2"]) / 2.0
                prev_cy = (prev_box["y1"] + prev_box["y2"]) / 2.0
                cur_cx = (cur_box["x1"] + cur_box["x2"]) / 2.0
                cur_cy = (cur_box["y1"] + cur_box["y2"]) / 2.0
                cur_box["vx"] = (cur_cx - prev_cx) / dt_model
                cur_box["vy"] = (cur_cy - prev_cy) / dt_model

        state = {
            "hwnd": hwnd,
            "frame_shape": frame_shape,
            "gray": gray,
            "boxes": boxes,
            "model_boxes": model_boxes,
            "last_update": now,
            "last_model_update": now,
            "last_model_seen": now,
        }
        state["executor"] = executor

        with _tracking_lock:
            if tracking_engine:
                state["tracking_engine"] = tracking_engine
            _tracking_state = state

        if _tracking_thread is None or not _tracking_thread.is_alive():
            _tracking_active = True
            _tracking_thread = threading.Thread(target=_tracking_loop, daemon=True)
            _tracking_thread.start()
    except Exception as e:
        logger.debug(f"跟踪状态更新失败：{e}")


def _capture_tracking_frame(hwnd: int, engine: Optional[str]) -> Optional[np.ndarray]:
    try:
        from utils.capture.screenshot_helper import _capture_with_engine, get_screenshot_engine

        try:
            hwnd_value = int(hwnd)
        except Exception:
            return None
        if hwnd_value <= 0:
            return None

        if not engine:
            engine = get_screenshot_engine()

        engine_name = str(engine or "").strip().lower()
        if engine_name not in {"dxgi", "gdi", "wgc", "printwindow"}:
            return None

        return _capture_with_engine(
            hwnd=hwnd_value,
            client_area_only=True,
            engine=engine_name,
            timeout=0.8,
        )
    except Exception as e:
        logger.debug("跟踪截图失败：%s", e)
    return None


def _tracking_loop():
    global _tracking_state, _tracking_active
    def _iou(a: Dict[str, Any], b: Dict[str, Any]) -> float:
        ax1, ay1, ax2, ay2 = a["x1"], a["y1"], a["x2"], a["y2"]
        bx1, by1, bx2, by2 = b["x1"], b["y1"], b["x2"], b["y2"]
        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        iw = max(0, inter_x2 - inter_x1)
        ih = max(0, inter_y2 - inter_y1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        a_area = max(1, (ax2 - ax1) * (ay2 - ay1))
        b_area = max(1, (bx2 - bx1) * (by2 - by1))
        return inter / float(a_area + b_area - inter)

    capture_fail_streak = 0
    while _tracking_active:
        if _get_overlay_render_mode() != "稳定优先":
            with _tracking_lock:
                _tracking_state = None
            precise_sleep(_tracking_interval)
            continue

        with _tracking_lock:
            state = _tracking_state

        if not state or not state.get("boxes"):
            capture_fail_streak = 0
            precise_sleep(_tracking_interval)
            continue

        now = time.perf_counter()
        hwnd = state.get("hwnd")
        frame_shape = state.get("frame_shape")
        executor = state.get("executor")
        last_model_seen = state.get("last_model_seen", state.get("last_model_update", now))
        if now - last_model_seen > _tracking_missing_timeout:
            with _tracking_lock:
                _tracking_state = None
            _dispatch_overlay_update(hwnd, [], frame_shape, executor=executor)
            precise_sleep(_tracking_interval)
            continue

        try:
            tracking_engine = state.get("tracking_engine")
            frame = _capture_tracking_frame(hwnd, tracking_engine)
            if frame is None:
                capture_fail_streak += 1
                if capture_fail_streak >= 3:
                    with _tracking_lock:
                        current_state = _tracking_state
                        if current_state is not None and int(current_state.get("hwnd") or 0) == int(hwnd or 0):
                            _tracking_state = None
                    _dispatch_overlay_update(hwnd, [], frame_shape, executor=executor)
                    capture_fail_streak = 0
                precise_sleep(_tracking_interval)
                continue
            capture_fail_streak = 0
            if len(frame.shape) == 3 and frame.shape[2] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            elif len(frame.shape) == 2:
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if _tracking_downscale != 1.0:
                gray = cv2.resize(gray, None, fx=_tracking_downscale, fy=_tracking_downscale, interpolation=cv2.INTER_LINEAR)
        except Exception:
            capture_fail_streak += 1
            precise_sleep(_tracking_interval)
            continue

        prev_gray = state.get("gray")
        if prev_gray is None or prev_gray.shape != gray.shape:
            with _tracking_lock:
                if _tracking_state is not None:
                    _tracking_state["gray"] = gray
                    _tracking_state["last_update"] = now
            precise_sleep(_tracking_interval)
            continue

        pts = []
        point_to_box = []
        for idx, box in enumerate(state.get("boxes", [])):
            x1 = box["x1"]
            y1 = box["y1"]
            x2 = box["x2"]
            y2 = box["y2"]
            cx = (x1 + x2) / 2.0
            cy = (y1 + y2) / 2.0
            dx = (x2 - x1) * _tracking_point_spread
            dy = (y2 - y1) * _tracking_point_spread
            candidates = [
                (cx, cy),
                (x1 + dx, y1 + dy),
                (x2 - dx, y1 + dy),
                (x1 + dx, y2 - dy),
                (x2 - dx, y2 - dy),
            ]
            for px, py in candidates:
                pts.append([px * _tracking_downscale, py * _tracking_downscale])
                point_to_box.append(idx)

        if not pts:
            precise_sleep(_tracking_interval)
            continue

        pts_np = np.array(pts, dtype=np.float32).reshape(-1, 1, 2)
        next_pts, st, _ = cv2.calcOpticalFlowPyrLK(
            prev_gray, gray, pts_np, None,
            winSize=(_tracking_flow_win, _tracking_flow_win),
            maxLevel=_tracking_flow_levels,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, _tracking_flow_iters, 0.03)
        )

        dt = max(1e-3, now - state.get("last_update", now))
        updated_boxes = []
        flow_by_box = {}
        if st is not None:
            for i in range(len(pts)):
                if st[i][0] == 0:
                    continue
                box_idx = point_to_box[i]
                dx = (next_pts[i][0][0] - pts_np[i][0][0]) / _tracking_downscale
                dy = (next_pts[i][0][1] - pts_np[i][0][1]) / _tracking_downscale
                flow_by_box.setdefault(box_idx, []).append((dx, dy))

        prev_boxes = state.get("boxes", [])
        model_boxes = state.get("model_boxes") or []
        model_dt = max(1e-3, now - state.get("last_model_update", now))

        def _expected_delta(box: Dict[str, Any]) -> Optional[Tuple[float, float]]:
            if not model_boxes:
                return None
            best_iou = 0.0
            best = None
            for mbox in model_boxes:
                if mbox.get("class_name") != box.get("class_name"):
                    continue
                iou = _iou(box, mbox)
                if iou > best_iou:
                    best_iou = iou
                    best = mbox
            if best is None or best_iou < _tracking_match_iou:
                return None
            return best.get("vx", 0.0) * model_dt, best.get("vy", 0.0) * model_dt

        def _clamp_box(x1: int, y1: int, x2: int, y2: int) -> Tuple[int, int, int, int]:
            if frame_shape and len(frame_shape) >= 2:
                max_h, max_w = frame_shape[:2]
                x1 = max(0, min(x1, max_w - 1))
                x2 = max(0, min(x2, max_w - 1))
                y1 = max(0, min(y1, max_h - 1))
                y2 = max(0, min(y2, max_h - 1))
            return x1, y1, x2, y2

        def _smooth_box(prev_box: Dict[str, Any], x1: int, y1: int, x2: int, y2: int) -> Tuple[int, int, int, int]:
            prev_cx = (prev_box["x1"] + prev_box["x2"]) / 2.0
            prev_cy = (prev_box["y1"] + prev_box["y2"]) / 2.0
            new_cx = (x1 + x2) / 2.0
            new_cy = (y1 + y2) / 2.0
            prev_w = max(2.0, float(prev_box["x2"] - prev_box["x1"]))
            prev_h = max(2.0, float(prev_box["y2"] - prev_box["y1"]))
            new_w = max(2.0, float(x2 - x1))
            new_h = max(2.0, float(y2 - y1))
            delta = math.hypot(new_cx - prev_cx, new_cy - prev_cy)
            if _tracking_adaptive_delta <= 0:
                alpha = 1.0
            else:
                alpha = max(_tracking_adaptive_min_alpha, min(1.0, delta / _tracking_adaptive_delta))
            size_alpha = min(alpha, 0.15)
            size_ratio_limit = 1.08
            min_ratio_limit = 1.0 / size_ratio_limit
            new_w = max(prev_w * min_ratio_limit, min(new_w, prev_w * size_ratio_limit))
            new_h = max(prev_h * min_ratio_limit, min(new_h, prev_h * size_ratio_limit))

            smooth_cx = prev_cx + alpha * (new_cx - prev_cx)
            smooth_cy = prev_cy + alpha * (new_cy - prev_cy)
            smooth_w = prev_w + size_alpha * (new_w - prev_w)
            smooth_h = prev_h + size_alpha * (new_h - prev_h)
            if abs(smooth_w - prev_w) < 1.0:
                smooth_w = prev_w
            if abs(smooth_h - prev_h) < 1.0:
                smooth_h = prev_h

            sx1 = int(round(smooth_cx - smooth_w * 0.5))
            sy1 = int(round(smooth_cy - smooth_h * 0.5))
            sx2 = int(round(smooth_cx + smooth_w * 0.5))
            sy2 = int(round(smooth_cy + smooth_h * 0.5))
            if sx2 <= sx1:
                sx2 = sx1 + 1
            if sy2 <= sy1:
                sy2 = sy1 + 1
            return sx1, sy1, sx2, sy2

        for idx, box in enumerate(prev_boxes):
            flows = flow_by_box.get(idx)
            if not flows or len(flows) < _tracking_min_points:
                expected = _expected_delta(box)
                if expected is not None:
                    dx, dy = expected
                    tracked = dict(box)
                    x1 = int(box["x1"] + dx)
                    y1 = int(box["y1"] + dy)
                    x2 = int(box["x2"] + dx)
                    y2 = int(box["y2"] + dy)
                    x1, y1, x2, y2 = _smooth_box(box, x1, y1, x2, y2)
                    x1, y1, x2, y2 = _clamp_box(x1, y1, x2, y2)
                    tracked["x1"] = x1
                    tracked["y1"] = y1
                    tracked["x2"] = x2
                    tracked["y2"] = y2
                    tracked["ts"] = now
                    tracked["dx"] = dx
                    tracked["dy"] = dy
                    tracked["vx"] = dx / dt
                    tracked["vy"] = dy / dt
                else:
                    tracked = dict(box)
                    tracked["ts"] = now
                    tracked["dx"] = box.get("dx", 0.0) * 0.5
                    tracked["dy"] = box.get("dy", 0.0) * 0.5
                    tracked["vx"] = tracked["dx"] / dt
                    tracked["vy"] = tracked["dy"] / dt
                updated_boxes.append(tracked)
                continue
            dxs = sorted([f[0] for f in flows])
            dys = sorted([f[1] for f in flows])
            mid = len(dxs) // 2
            dx = dxs[mid]
            dy = dys[mid]

            mad_x = sorted([abs(v - dx) for v in dxs])[mid]
            mad_y = sorted([abs(v - dy) for v in dys])[mid]
            if mad_x > _tracking_flow_mad or mad_y > _tracking_flow_mad:
                expected = _expected_delta(box)
                if expected is not None:
                    dx, dy = expected
                    tracked = dict(box)
                    x1 = int(box["x1"] + dx)
                    y1 = int(box["y1"] + dy)
                    x2 = int(box["x2"] + dx)
                    y2 = int(box["y2"] + dy)
                    x1, y1, x2, y2 = _smooth_box(box, x1, y1, x2, y2)
                    x1, y1, x2, y2 = _clamp_box(x1, y1, x2, y2)
                    tracked["x1"] = x1
                    tracked["y1"] = y1
                    tracked["x2"] = x2
                    tracked["y2"] = y2
                    tracked["ts"] = now
                    tracked["dx"] = dx
                    tracked["dy"] = dy
                    tracked["vx"] = dx / dt
                    tracked["vy"] = dy / dt
                else:
                    tracked = dict(box)
                    tracked["ts"] = now
                    tracked["dx"] = box.get("dx", 0.0) * 0.5
                    tracked["dy"] = box.get("dy", 0.0) * 0.5
                    tracked["vx"] = tracked["dx"] / dt
                    tracked["vy"] = tracked["dy"] / dt
                updated_boxes.append(tracked)
                continue

            if dx > _tracking_max_delta:
                dx = _tracking_max_delta
            elif dx < -_tracking_max_delta:
                dx = -_tracking_max_delta
            if dy > _tracking_max_delta:
                dy = _tracking_max_delta
            elif dy < -_tracking_max_delta:
                dy = -_tracking_max_delta

            prev_dx = box.get("dx", 0.0)
            prev_dy = box.get("dy", 0.0)
            expected = _expected_delta(box)
            if expected is not None:
                exp_dx, exp_dy = expected
                exp_mag = abs(exp_dx) + abs(exp_dy)
                flow_mag = dx * dx + dy * dy
                exp_flow_mag = exp_dx * exp_dx + exp_dy * exp_dy
                if exp_mag < 1.0 and (abs(dx) > _tracking_model_guard_small or abs(dy) > _tracking_model_guard_small):
                    dx, dy = 0.0, 0.0
                elif (dx * exp_dx + dy * exp_dy) < 0 and flow_mag > exp_flow_mag * 0.25:
                    dx, dy = exp_dx, exp_dy
                elif abs(dx - exp_dx) > _tracking_model_guard or abs(dy - exp_dy) > _tracking_model_guard:
                    dx, dy = exp_dx, exp_dy
                if exp_mag < _tracking_static_exp and abs(dx) < _tracking_static_deadband and abs(dy) < _tracking_static_deadband:
                    dx, dy = 0.0, 0.0
            if abs(dx - prev_dx) > _tracking_jump_guard or abs(dy - prev_dy) > _tracking_jump_guard:
                tracked = dict(box)
                if expected is not None:
                    dx, dy = expected
                    x1 = int(box["x1"] + dx)
                    y1 = int(box["y1"] + dy)
                    x2 = int(box["x2"] + dx)
                    y2 = int(box["y2"] + dy)
                    x1, y1, x2, y2 = _smooth_box(box, x1, y1, x2, y2)
                    x1, y1, x2, y2 = _clamp_box(x1, y1, x2, y2)
                    tracked["x1"] = x1
                    tracked["y1"] = y1
                    tracked["x2"] = x2
                    tracked["y2"] = y2
                    tracked["dx"] = dx
                    tracked["dy"] = dy
                else:
                    tracked["dx"] = prev_dx * 0.5
                    tracked["dy"] = prev_dy * 0.5
                    x1 = int(box["x1"] + tracked["dx"])
                    y1 = int(box["y1"] + tracked["dy"])
                    x2 = int(box["x2"] + tracked["dx"])
                    y2 = int(box["y2"] + tracked["dy"])
                    x1, y1, x2, y2 = _smooth_box(box, x1, y1, x2, y2)
                    x1, y1, x2, y2 = _clamp_box(x1, y1, x2, y2)
                    tracked["x1"] = x1
                    tracked["y1"] = y1
                    tracked["x2"] = x2
                    tracked["y2"] = y2
                tracked["ts"] = now
                tracked["vx"] = tracked["dx"] / dt
                tracked["vy"] = tracked["dy"] / dt
                updated_boxes.append(tracked)
                continue
            if abs(dx) < _tracking_deadband:
                dx = 0.0
            if abs(dy) < _tracking_deadband:
                dy = 0.0
            smooth = _tracking_smooth_factor
            dx = smooth * prev_dx + (1.0 - smooth) * dx
            dy = smooth * prev_dy + (1.0 - smooth) * dy
            vx = dx / dt
            vy = dy / dt

            x1 = int(box["x1"] + dx)
            y1 = int(box["y1"] + dy)
            x2 = int(box["x2"] + dx)
            y2 = int(box["y2"] + dy)
            x1, y1, x2, y2 = _smooth_box(box, x1, y1, x2, y2)
            x1, y1, x2, y2 = _clamp_box(x1, y1, x2, y2)

            updated_boxes.append({
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "class_name": box.get("class_name", ""),
                "confidence": box.get("confidence", 0.0),
                "vx": vx,
                "vy": vy,
                "dx": dx,
                "dy": dy,
                "ts": now,
            })

        model_boxes = state.get("model_boxes") or []
        if updated_boxes and model_boxes:
            age = max(0.0, now - state.get("last_model_update", now))
            timeout = max(_tracking_timeout, 1e-3)
            model_weight = max(0.0, min(1.0, 1.0 - age / timeout))
            tracking_weight = 1.0 - (1.0 - _tracking_blend_alpha) * model_weight
            used_models = set()
            for idx, tracked in enumerate(updated_boxes):
                best_iou = 0.0
                best_idx = -1
                for mi, mbox in enumerate(model_boxes):
                    if mi in used_models:
                        continue
                    if mbox.get("class_name") != tracked.get("class_name"):
                        continue
                    iou = _iou(tracked, mbox)
                    if iou > best_iou:
                        best_iou = iou
                        best_idx = mi
                if best_idx < 0 or best_iou < _tracking_match_iou:
                    if age < _tracking_model_fresh and idx < len(prev_boxes):
                        frozen = dict(prev_boxes[idx])
                        frozen["ts"] = now
                        frozen["vx"] = frozen.get("vx", 0.0) * 0.5
                        frozen["vy"] = frozen.get("vy", 0.0) * 0.5
                        frozen["dx"] = 0.0
                        frozen["dy"] = 0.0
                        frozen["source"] = "tracking"
                        updated_boxes[idx] = frozen
                    else:
                        tracked["source"] = "tracking"
                    continue
                used_models.add(best_idx)
                mbox = model_boxes[best_idx]
                alpha = tracking_weight
                tracked_cx = (tracked["x1"] + tracked["x2"]) * 0.5
                tracked_cy = (tracked["y1"] + tracked["y2"]) * 0.5
                tracked_w = max(2.0, float(tracked["x2"] - tracked["x1"]))
                tracked_h = max(2.0, float(tracked["y2"] - tracked["y1"]))
                model_cx = (mbox["x1"] + mbox["x2"]) * 0.5
                model_cy = (mbox["y1"] + mbox["y2"]) * 0.5
                model_w = max(2.0, float(mbox["x2"] - mbox["x1"]))
                model_h = max(2.0, float(mbox["y2"] - mbox["y1"]))

                size_alpha = min(alpha, 0.18)
                size_ratio_limit = 1.08
                min_ratio_limit = 1.0 / size_ratio_limit
                model_w = max(tracked_w * min_ratio_limit, min(model_w, tracked_w * size_ratio_limit))
                model_h = max(tracked_h * min_ratio_limit, min(model_h, tracked_h * size_ratio_limit))

                blend_cx = alpha * tracked_cx + (1.0 - alpha) * model_cx
                blend_cy = alpha * tracked_cy + (1.0 - alpha) * model_cy
                blend_w = tracked_w + size_alpha * (model_w - tracked_w)
                blend_h = tracked_h + size_alpha * (model_h - tracked_h)

                bx1 = int(round(blend_cx - blend_w * 0.5))
                by1 = int(round(blend_cy - blend_h * 0.5))
                bx2 = int(round(blend_cx + blend_w * 0.5))
                by2 = int(round(blend_cy + blend_h * 0.5))
                if bx2 <= bx1:
                    bx2 = bx1 + 1
                if by2 <= by1:
                    by2 = by1 + 1
                if frame_shape and len(frame_shape) >= 2:
                    max_h, max_w = frame_shape[:2]
                    bx1 = max(0, min(bx1, max_w - 1))
                    bx2 = max(0, min(bx2, max_w - 1))
                    by1 = max(0, min(by1, max_h - 1))
                    by2 = max(0, min(by2, max_h - 1))
                prev = prev_boxes[idx] if idx < len(prev_boxes) else tracked
                prev_cx = (prev["x1"] + prev["x2"]) / 2.0
                prev_cy = (prev["y1"] + prev["y2"]) / 2.0
                new_cx = (bx1 + bx2) / 2.0
                new_cy = (by1 + by2) / 2.0
                dx = new_cx - prev_cx
                dy = new_cy - prev_cy
                tracked.update({
                    "x1": bx1,
                    "y1": by1,
                    "x2": bx2,
                    "y2": by2,
                    "vx": dx / dt,
                    "vy": dy / dt,
                    "dx": dx,
                    "dy": dy,
                    "ts": now,
                    "source": "tracking",
                })
        updated_boxes = _dedupe_boxes(updated_boxes, iou_threshold=0.64, center_threshold=6.0)
        for tracked in updated_boxes:
            tracked.setdefault("source", "tracking")

        with _tracking_lock:
            if _tracking_state is not None:
                _tracking_state["gray"] = gray
                _tracking_state["boxes"] = updated_boxes
                _tracking_state["last_update"] = now

        model_age = max(0.0, now - state.get("last_model_update", now))
        if model_age >= _tracking_draw_gap:
            _dispatch_overlay_update(hwnd, updated_boxes, frame_shape, executor=executor)
        precise_sleep(_tracking_interval)


def draw_detections_on_window(hwnd: int, detections: List, frame_shape: Tuple, executor: Any = None):
    """Schedule overlay drawing without blocking inference."""
    _dispatch_overlay_update(hwnd, detections, frame_shape, executor=executor)


def hide_detections_overlay(release_runtime: bool = False):
    """Stop overlay drawing and release resources."""
    global _overlay_instance, _overlay_active, _overlay_thread, _overlay_detections, _overlay_hwnd, _overlay_frame_shape, _overlay_dirty
    global _qt_overlay_latest, _qt_overlay_pending, _qt_overlay_manager, _qt_overlay_invoker, _qt_overlay_flush_scheduled
    global _tracking_active, _tracking_thread, _tracking_state
    global _overlay_force_clear, _overlay_shutdown_requested
    global _overlay_last_detections, _overlay_last_hwnd, _overlay_last_frame_shape, _overlay_last_update_ts

    _set_overlay_render_mode("稳定优先")

    with _qt_overlay_latest_lock:
        _qt_overlay_latest = None
        _qt_overlay_pending = False
    _qt_overlay_flush_scheduled = False

    manager_ref = _qt_overlay_manager
    if manager_ref is not None:
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import QThread, QObject, Signal
        except Exception:
            try:
                if hasattr(manager_ref, "shutdown"):
                    manager_ref.shutdown()
                else:
                    manager_ref.hide_overlay()
            except Exception:
                pass
            try:
                if hasattr(manager_ref, "deleteLater"):
                    manager_ref.deleteLater()
            except Exception:
                pass
        else:
            app = QApplication.instance()

            def _shutdown():
                try:
                    if hasattr(manager_ref, "shutdown"):
                        manager_ref.shutdown()
                    else:
                        manager_ref.hide_overlay()
                except Exception:
                    pass
                try:
                    if hasattr(manager_ref, "deleteLater"):
                        manager_ref.deleteLater()
                except Exception:
                    pass

            if app is None or QThread.currentThread() == app.thread():
                _shutdown()
            else:
                if _qt_overlay_invoker is None:
                    class Invoker(QObject):
                        invoke = Signal(object)

                        def __init__(self):
                            super().__init__()
                            self.invoke.connect(self._run)

                        def _run(self, callback):
                            try:
                                callback()
                            except Exception:
                                pass

                    invoker = Invoker()
                    invoker.moveToThread(app.thread())
                    _qt_overlay_invoker = invoker

                _qt_overlay_invoker.invoke.emit(_shutdown)
    _qt_overlay_manager = None

    if release_runtime:
        if not _shutdown_native_overlay_runtime():
            logger.debug("悬浮层运行时关闭超时")
    else:
        overlay_ref = None
        with _overlay_lock:
            _overlay_active = False
            _overlay_shutdown_requested = False
            _clear_overlay_runtime_state_locked()
            overlay_ref = _overlay_instance

        with _overlay_force_clear_lock:
            _overlay_force_clear = False
        _overlay_event.set()

        if overlay_ref is not None:
            try:
                overlay_ref.hide()
            except Exception:
                pass

    _tracking_active = False
    with _tracking_lock:
        _tracking_state = None
    if _tracking_thread is not None and _tracking_thread.is_alive():
        _tracking_thread.join(timeout=1)
    _tracking_thread = None

    invoker_ref = _qt_overlay_invoker
    if invoker_ref is not None:
        try:
            if hasattr(invoker_ref, "deleteLater"):
                invoker_ref.deleteLater()
        except Exception:
            pass
    _qt_overlay_invoker = None


def cleanup_yolo_runtime_state(release_engine: bool = True, compact_memory: bool = True) -> bool:
    """统一清理YOLO运行时资源，确保停止后无残留引用。"""
    success = True

    try:
        hide_detections_overlay(release_runtime=True)
    except Exception:
        success = False

    try:
        import sys
        workflow_context_module = sys.modules.get("task_workflow.workflow_context")
        if workflow_context_module is not None:
            clear_all_yolo_runtime_data = getattr(workflow_context_module, "clear_all_yolo_runtime_data", None)
            if callable(clear_all_yolo_runtime_data):
                clear_all_yolo_runtime_data()
            else:
                get_current_context = getattr(workflow_context_module, "get_current_workflow_context", None)
                if callable(get_current_context):
                    context = get_current_context()
                    clear_all_yolo_data = getattr(context, "clear_all_yolo_data", None)
                    if callable(clear_all_yolo_data):
                        clear_all_yolo_data()
    except Exception:
        success = False

    if release_engine:
        try:
            import sys
            yolo_engine_module = sys.modules.get("utils.match.yolo_engine")
            if yolo_engine_module is not None:
                engine_cls = getattr(yolo_engine_module, "YOLOONNXEngine", None)
                if engine_cls is not None and hasattr(engine_cls, "clear_instances"):
                    engine_cls.clear_instances()
        except Exception:
            success = False
    else:
        # 停止任务时保留YOLO引擎热状态，避免下次启动重新加载模型导致卡顿。
        pass

    try:
        with _target_not_found_log_lock:
            _target_not_found_log_state.clear()
        with _capture_fail_log_lock:
            _capture_fail_log_state.clear()
    except Exception:
        success = False

    try:
        import gc
        gc.collect()
    except Exception:
        pass

    if compact_memory:
        try:
            import os
            if os.name == "nt":
                import ctypes
                msvcrt = ctypes.CDLL("msvcrt")
                heapmin = getattr(msvcrt, "_heapmin", None)
                if callable(heapmin):
                    heapmin()
        except Exception:
            pass

    return success
