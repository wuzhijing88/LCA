# -*- coding: utf-8 -*-
"""
截图统一入口（主进程实现）。

统一主进程截图链路，不再保留子进程接口。
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from utils.smart_image_matcher import normalize_match_image
from utils.resolution_aware_matcher import smart_match_template
from utils.screenshot_helper import (
    _capture_with_engine,
    cleanup_screenshot_engine,
    clear_screenshot_cache as _clear_screenshot_cache_impl,
    get_last_screenshot_error as _get_last_capture_error,
    get_screenshot_engine,
    get_screenshot_info,
)

logger = logging.getLogger(__name__)

_MOTION_STATE_LOCK = threading.RLock()
_MOTION_STATE: Dict[str, np.ndarray] = {}

_WORKER_LIMIT_LOCK = threading.Lock()
_WORKER_LIMIT_OVERRIDE: Optional[int] = None
_WORKER_GATE_LOCK = threading.Lock()
_WORKER_GATE: Optional[threading.BoundedSemaphore] = None
_WORKER_GATE_LIMIT: int = 0

_CAPTURE_SHARE_LOCK = threading.RLock()
_CAPTURE_INFLIGHT: Dict[Tuple[int, bool, str], "_CaptureInFlight"] = {}


class _CaptureInFlight:
    __slots__ = ("event", "frame", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.frame: Optional[np.ndarray] = None
        self.error: str = ""


def _normalize_engine(engine: Optional[str]) -> str:
    text = str(engine or "").strip().lower()
    if text in {"wgc", "printwindow", "gdi", "dxgi"}:
        return text
    try:
        current = str(get_screenshot_engine() or "wgc").strip().lower()
        if current in {"wgc", "printwindow", "gdi", "dxgi"}:
            return current
    except Exception:
        pass
    return "wgc"


def _normalize_roi(roi: Optional[Tuple[int, int, int, int]], width: int, height: int) -> Optional[Tuple[int, int, int, int]]:
    if not isinstance(roi, (list, tuple)) or len(roi) != 4:
        return None
    try:
        x, y, w, h = int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3])
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    if x < 0 or y < 0:
        return None
    x2 = min(width, x + w)
    y2 = min(height, y + h)
    if x >= x2 or y >= y2:
        return None
    return (x, y, x2 - x, y2 - y)


def _extract_roi_frame(frame: np.ndarray, roi: Optional[Tuple[int, int, int, int]]) -> np.ndarray:
    if frame is None or not isinstance(frame, np.ndarray) or frame.size <= 0:
        return frame
    normalized = _normalize_roi(roi, frame.shape[1], frame.shape[0])
    if normalized is None:
        return frame
    x, y, w, h = normalized
    return frame[y : y + h, x : x + w]


def _build_capture_key(hwnd: int, client_area_only: bool, engine_name: str) -> Tuple[int, bool, str]:
    return (int(hwnd), bool(client_area_only), str(engine_name or "wgc").strip().lower())


def _resolve_effective_worker_limit() -> int:
    hard = get_screenshot_worker_hard_limit()
    with _WORKER_LIMIT_LOCK:
        override = _WORKER_LIMIT_OVERRIDE
    if override is not None:
        return max(1, min(hard, int(override)))
    default_limit = min(3, hard)
    raw = os.getenv("LCA_SCREENSHOT_WORKER_LIMIT")
    if raw is None:
        return default_limit
    try:
        value = int(raw)
    except Exception:
        value = default_limit
    return max(1, min(hard, value))


def _acquire_capture_worker_slot(timeout: float) -> Optional[threading.BoundedSemaphore]:
    limit = _resolve_effective_worker_limit()
    semaphore: Optional[threading.BoundedSemaphore]
    with _WORKER_GATE_LOCK:
        global _WORKER_GATE, _WORKER_GATE_LIMIT
        if _WORKER_GATE is None or _WORKER_GATE_LIMIT != limit:
            _WORKER_GATE = threading.BoundedSemaphore(limit)
            _WORKER_GATE_LIMIT = limit
        semaphore = _WORKER_GATE
    if semaphore is None:
        return None
    wait_timeout = max(0.1, float(timeout))
    acquired = semaphore.acquire(timeout=wait_timeout)
    if not acquired:
        return None
    return semaphore


def _clear_shared_capture_state(hwnd: Optional[int] = None) -> None:
    with _CAPTURE_SHARE_LOCK:
        if hwnd is None:
            _CAPTURE_INFLIGHT.clear()
            return
        try:
            hwnd_value = int(hwnd)
        except Exception:
            return
        keys_to_remove = [key for key in _CAPTURE_INFLIGHT.keys() if int(key[0]) == hwnd_value]
        for key in keys_to_remove:
            _CAPTURE_INFLIGHT.pop(key, None)


def _build_capture_failed_error(engine: Optional[str]) -> str:
    try:
        detail = str(get_last_screenshot_error(engine=engine) or "").strip().lower()
    except Exception:
        detail = ""
    if detail:
        return f"capture_failed:{detail}"
    return "capture_failed"


def capture_window(
    hwnd: int,
    client_area_only: bool = True,
    use_cache: bool = False,
    timeout: float = 4.0,
    engine: Optional[str] = None,
    roi: Optional[Tuple[int, int, int, int]] = None,
) -> Optional[np.ndarray]:
    try:
        hwnd_value = int(hwnd)
    except Exception:
        return None
    if hwnd_value <= 0:
        return None

    engine_name = _normalize_engine(engine)
    timeout_value = max(0.1, float(timeout))
    capture_key = _build_capture_key(hwnd_value, bool(client_area_only), engine_name)
    frame: Optional[np.ndarray] = None

    owner = False
    inflight: Optional[_CaptureInFlight] = None
    # 同窗口同引擎并发请求：仅共享同一轮 in-flight 抓帧结果，抓帧完成即失效。
    with _CAPTURE_SHARE_LOCK:
        inflight = _CAPTURE_INFLIGHT.get(capture_key)
        if inflight is None:
            inflight = _CaptureInFlight()
            _CAPTURE_INFLIGHT[capture_key] = inflight
            owner = True

    if owner:
        slot = _acquire_capture_worker_slot(timeout_value)
        if slot is None:
            inflight.error = "capture_worker_limit_timeout"
            inflight.event.set()
            with _CAPTURE_SHARE_LOCK:
                _CAPTURE_INFLIGHT.pop(capture_key, None)
            return None
        try:
            captured = _capture_with_engine(
                hwnd=hwnd_value,
                client_area_only=bool(client_area_only),
                engine=engine_name,
                timeout=timeout_value,
            )
            if captured is not None and isinstance(captured, np.ndarray) and captured.size > 0:
                frame = captured
                inflight.frame = captured
            else:
                inflight.error = "capture_failed"
        finally:
            try:
                slot.release()
            except Exception:
                pass
            inflight.event.set()
            with _CAPTURE_SHARE_LOCK:
                _CAPTURE_INFLIGHT.pop(capture_key, None)
    else:
        wait_seconds = max(0.6, timeout_value + 0.3)
        if inflight is None or (not inflight.event.wait(timeout=wait_seconds)):
            return None
        frame = inflight.frame

    if frame is None or (not isinstance(frame, np.ndarray)) or frame.size <= 0:
        return None

    _ = bool(use_cache)
    if roi is not None:
        frame = _extract_roi_frame(frame, roi)
    return frame


def capture_and_match_template(
    hwnd: int,
    template: np.ndarray,
    confidence_threshold: float = 0.8,
    template_key: Optional[str] = None,
    client_area_only: bool = True,
    use_cache: bool = False,
    timeout: float = 4.0,
    engine: Optional[str] = None,
    roi: Optional[Tuple[int, int, int, int]] = None,
) -> Dict[str, Any]:
    failed = {
        "success": False,
        "matched": False,
        "confidence": 0.0,
        "location": None,
        "center": None,
        "screenshot_width": None,
        "screenshot_height": None,
        "screenshot_shape": None,
        "error": "unknown_error",
    }
    _ = template_key

    if template is None or (not isinstance(template, np.ndarray)) or template.size <= 0:
        failed["error"] = "invalid_template"
        return failed

    frame = capture_window(
        hwnd=hwnd,
        client_area_only=client_area_only,
        use_cache=use_cache,
        timeout=timeout,
        engine=engine,
    )
    if frame is None or frame.size <= 0:
        failed["error"] = _build_capture_failed_error(engine=engine)
        return failed
    try:
        frame_h, frame_w = int(frame.shape[0]), int(frame.shape[1])
        failed["screenshot_width"] = frame_w
        failed["screenshot_height"] = frame_h
        failed["screenshot_shape"] = (frame_h, frame_w)
    except Exception:
        pass

    template = normalize_match_image(template)
    if template is None:
        failed["error"] = "invalid_template_shape"
        return failed

    try:
        result = smart_match_template(
            haystack=frame,
            needle=template,
            confidence=float(confidence_threshold),
            roi=roi,
        )
    except Exception as exc:
        failed["error"] = str(exc) or type(exc).__name__
        return failed

    found = bool(result.get("found", False))
    confidence = float(result.get("confidence", 0.0) or 0.0)
    location = result.get("location")
    center = result.get("center")
    if found and isinstance(location, (list, tuple)) and len(location) == 4:
        try:
            location = (
                int(location[0]),
                int(location[1]),
                int(location[2]),
                int(location[3]),
            )
        except Exception:
            location = None
            found = False
    else:
        location = None
        if not found:
            center = None

    response = {
        "success": True,
        "matched": bool(found and confidence >= float(confidence_threshold)),
        "confidence": confidence,
        "location": location,
        "center": center,
        "screenshot_width": failed.get("screenshot_width"),
        "screenshot_height": failed.get("screenshot_height"),
        "screenshot_shape": failed.get("screenshot_shape"),
        "error": "",
    }
    return response


def _bgr_to_hsv_pixel(color_bgr: Tuple[int, int, int]) -> Tuple[int, int, int]:
    pixel = np.uint8([[[int(color_bgr[0]), int(color_bgr[1]), int(color_bgr[2])]]])
    hsv = cv2.cvtColor(pixel, cv2.COLOR_BGR2HSV)[0, 0]
    return int(hsv[0]), int(hsv[1]), int(hsv[2])


def _hsv_in_tolerance(pixel_hsv: Tuple[int, int, int], target_hsv: Tuple[int, int, int], h_tol: int, s_tol: int, v_tol: int) -> bool:
    ph, ps, pv = pixel_hsv
    th, ts, tv = target_hsv
    dh = min(abs(ph - th), 180 - abs(ph - th))
    return (dh <= h_tol) and (abs(ps - ts) <= s_tol) and (abs(pv - tv) <= v_tol)


def _parse_bgr(entry: Dict[str, Any]) -> Optional[Tuple[int, int, int]]:
    if not isinstance(entry, dict):
        return None
    bgr = entry.get("bgr")
    if isinstance(bgr, (list, tuple)) and len(bgr) == 3:
        try:
            return (int(bgr[0]), int(bgr[1]), int(bgr[2]))
        except Exception:
            return None
    rgb = entry.get("rgb")
    if isinstance(rgb, (list, tuple)) and len(rgb) == 3:
        try:
            r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
            return (b, g, r)
        except Exception:
            return None
    return None


def _collect_positions_from_mask(mask: np.ndarray, x_offset: int, y_offset: int, max_points: int = 8192) -> List[Tuple[int, int]]:
    ys, xs = np.where(mask > 0)
    if ys.size == 0:
        return []
    count = min(int(xs.size), int(max_points))
    positions: List[Tuple[int, int]] = []
    for i in range(count):
        positions.append((int(xs[i]) + x_offset, int(ys[i]) + y_offset))
    return positions


def capture_and_find_color(
    hwnd: int,
    color_mode: str,
    colors_data: List[Dict[str, Any]],
    h_tolerance: int = 10,
    s_tolerance: int = 40,
    v_tolerance: int = 40,
    min_pixel_count: int = 1,
    client_area_only: bool = True,
    use_cache: bool = False,
    timeout: float = 4.0,
    engine: Optional[str] = None,
    roi: Optional[Tuple[int, int, int, int]] = None,
) -> Dict[str, Any]:
    failed = {
        "success": False,
        "found": False,
        "positions": [],
        "center": None,
        "error": "unknown_error",
        "screenshot_width": None,
        "screenshot_height": None,
        "screenshot_shape": None,
    }

    frame = capture_window(
        hwnd=hwnd,
        client_area_only=client_area_only,
        use_cache=use_cache,
        timeout=timeout,
        engine=engine,
    )
    if frame is None or not isinstance(frame, np.ndarray) or frame.size <= 0:
        failed["error"] = _build_capture_failed_error(engine=engine)
        return failed

    h, w = frame.shape[:2]
    failed["screenshot_width"] = int(w)
    failed["screenshot_height"] = int(h)
    failed["screenshot_shape"] = (int(h), int(w))
    normalized_roi = _normalize_roi(roi, w, h)
    if normalized_roi is None:
        x_off, y_off = 0, 0
        search = frame
    else:
        x_off, y_off, rw, rh = normalized_roi
        search = frame[y_off : y_off + rh, x_off : x_off + rw]

    if search is None or search.size <= 0:
        failed["error"] = "empty_search_area"
        return failed

    hsv_img = cv2.cvtColor(search, cv2.COLOR_BGR2HSV)
    h_tol = max(0, min(90, int(h_tolerance)))
    s_tol = max(0, min(255, int(s_tolerance)))
    v_tol = max(0, min(255, int(v_tolerance)))
    threshold = max(1, int(min_pixel_count))

    parsed_colors: List[Tuple[int, int, int]] = []
    for item in (colors_data or []):
        color = _parse_bgr(item)
        if color is not None:
            parsed_colors.append(color)
    if not parsed_colors:
        failed["error"] = "invalid_colors_data"
        return failed

    mode = str(color_mode or "single").strip().lower()
    if mode not in {"single", "multi", "multipoint"}:
        mode = "single"

    positions: List[Tuple[int, int]] = []

    try:
        if mode in {"single", "multi"}:
            masks = []
            for bgr in parsed_colors:
                target_h, target_s, target_v = _bgr_to_hsv_pixel(bgr)
                lower = np.array(
                    [
                        max(0, target_h - h_tol),
                        max(0, target_s - s_tol),
                        max(0, target_v - v_tol),
                    ],
                    dtype=np.uint8,
                )
                upper = np.array(
                    [
                        min(179, target_h + h_tol),
                        min(255, target_s + s_tol),
                        min(255, target_v + v_tol),
                    ],
                    dtype=np.uint8,
                )
                mask = cv2.inRange(hsv_img, lower, upper)
                masks.append(mask)
                if mode == "single":
                    break
            if not masks:
                failed["error"] = "mask_build_failed"
                return failed
            merged = masks[0]
            for m in masks[1:]:
                merged = cv2.bitwise_or(merged, m)
            positions = _collect_positions_from_mask(merged, x_off, y_off)
        else:
            # multipoint: 第一组颜色作为锚点，其余颜色按 offset 校验
            first_item = colors_data[0] if colors_data else {}
            first_bgr = _parse_bgr(first_item)
            if first_bgr is None:
                failed["error"] = "invalid_anchor_color"
                return failed
            first_hsv = _bgr_to_hsv_pixel(first_bgr)
            lower = np.array(
                [
                    max(0, first_hsv[0] - h_tol),
                    max(0, first_hsv[1] - s_tol),
                    max(0, first_hsv[2] - v_tol),
                ],
                dtype=np.uint8,
            )
            upper = np.array(
                [
                    min(179, first_hsv[0] + h_tol),
                    min(255, first_hsv[1] + s_tol),
                    min(255, first_hsv[2] + v_tol),
                ],
                dtype=np.uint8,
            )
            anchor_mask = cv2.inRange(hsv_img, lower, upper)
            ys, xs = np.where(anchor_mask > 0)
            if ys.size > 0:
                extra_rules: List[Tuple[int, int, Tuple[int, int, int]]] = []
                for item in (colors_data[1:] or []):
                    if not isinstance(item, dict):
                        continue
                    offset = item.get("offset")
                    color = _parse_bgr(item)
                    if (
                        isinstance(offset, (list, tuple))
                        and len(offset) == 2
                        and color is not None
                    ):
                        try:
                            ox, oy = int(offset[0]), int(offset[1])
                        except Exception:
                            continue
                        extra_rules.append((ox, oy, _bgr_to_hsv_pixel(color)))

                limit = min(int(xs.size), 20000)
                for idx in range(limit):
                    x = int(xs[idx])
                    y = int(ys[idx])
                    matched = True
                    for ox, oy, hsv_target in extra_rules:
                        tx = x + ox
                        ty = y + oy
                        if tx < 0 or ty < 0 or tx >= hsv_img.shape[1] or ty >= hsv_img.shape[0]:
                            matched = False
                            break
                        pixel = hsv_img[ty, tx]
                        if not _hsv_in_tolerance(
                            (int(pixel[0]), int(pixel[1]), int(pixel[2])),
                            hsv_target,
                            h_tol,
                            s_tol,
                            v_tol,
                        ):
                            matched = False
                            break
                    if matched:
                        positions.append((x + x_off, y + y_off))
                        if len(positions) >= 8192:
                            break
    except Exception as exc:
        failed["error"] = str(exc) or type(exc).__name__
        return failed

    found = len(positions) >= threshold
    center = None
    if positions:
        center_x = int(round(sum(p[0] for p in positions) / len(positions)))
        center_y = int(round(sum(p[1] for p in positions) / len(positions)))
        center = (center_x, center_y)

    return {
        "success": True,
        "found": bool(found),
        "positions": positions if found else [],
        "center": center if found else None,
        "error": "",
        "pixel_count": int(len(positions)),
        "screenshot_width": failed.get("screenshot_width"),
        "screenshot_height": failed.get("screenshot_height"),
        "screenshot_shape": failed.get("screenshot_shape"),
    }


def capture_and_check_motion(
    hwnd: int,
    state_key: Optional[str],
    diff_threshold: int = 15,
    motion_threshold: int = 50,
    reset_baseline: bool = False,
    client_area_only: bool = True,
    use_cache: bool = False,
    timeout: float = 4.0,
    engine: Optional[str] = None,
    roi: Optional[Tuple[int, int, int, int]] = None,
) -> Dict[str, Any]:
    failed = {
        "success": False,
        "initialized": False,
        "motion_detected": False,
        "changed_pixels": 0,
        "shape_changed": False,
        "error": "unknown_error",
    }

    frame = capture_window(
        hwnd=hwnd,
        client_area_only=client_area_only,
        use_cache=use_cache,
        timeout=timeout,
        engine=engine,
        roi=roi,
    )
    if frame is None or frame.size <= 0:
        failed["error"] = _build_capture_failed_error(engine=engine)
        return failed

    if len(frame.shape) == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame.copy()

    key = str(state_key or f"default:{int(hwnd)}").strip() or f"default:{int(hwnd)}"
    diff_threshold_value = max(1, min(255, int(diff_threshold)))
    motion_threshold_value = max(1, int(motion_threshold))

    with _MOTION_STATE_LOCK:
        previous = _MOTION_STATE.get(key)
        if reset_baseline or previous is None:
            _MOTION_STATE[key] = gray
            return {
                "success": True,
                "initialized": True,
                "motion_detected": False,
                "changed_pixels": 0,
                "shape_changed": False,
                "error": "",
            }

        if previous.shape != gray.shape:
            _MOTION_STATE[key] = gray
            return {
                "success": True,
                "initialized": False,
                "motion_detected": False,
                "changed_pixels": 0,
                "shape_changed": True,
                "error": "",
            }

        diff = cv2.absdiff(previous, gray)
        _, mask = cv2.threshold(diff, diff_threshold_value, 255, cv2.THRESH_BINARY)
        changed_pixels = int(cv2.countNonZero(mask))
        motion_detected = changed_pixels >= motion_threshold_value
        _MOTION_STATE[key] = gray

    return {
        "success": True,
        "initialized": False,
        "motion_detected": bool(motion_detected),
        "changed_pixels": changed_pixels,
        "shape_changed": False,
        "error": "",
    }


def clear_motion_state(state_key: Optional[str] = None) -> bool:
    with _MOTION_STATE_LOCK:
        if state_key is None:
            _MOTION_STATE.clear()
            return True
        key = str(state_key).strip()
        if not key:
            return False
        _MOTION_STATE.pop(key, None)
        return True


def clear_screenshot_engine_cache(hwnd: Optional[int] = None) -> bool:
    try:
        _clear_screenshot_cache_impl(hwnd=hwnd)
        _clear_shared_capture_state(hwnd=hwnd)
        return True
    except Exception:
        return False


def clear_screenshot_cache(hwnd: Optional[int] = None, engine: Optional[str] = None) -> bool:
    _ = engine
    return clear_screenshot_engine_cache(hwnd=hwnd)


def cleanup_screenshot_engine_runtime(
    engine: Optional[str] = None,
    hwnd: Optional[int] = None,
    cleanup_d3d: bool = False,
) -> None:
    _ = engine
    _ = cleanup_d3d
    cleanup_screenshot_engine(hwnd=hwnd)
    _clear_shared_capture_state(hwnd=hwnd)


def cleanup_screenshot_runtime() -> None:
    cleanup_screenshot_engine(hwnd=None)
    _clear_shared_capture_state(hwnd=None)


def clear_screenshot_runtime_state(hwnd: Optional[int] = None) -> None:
    """仅清理运行态缓存，不触发引擎销毁。"""
    _clear_shared_capture_state(hwnd=hwnd)
    if hwnd is None:
        clear_motion_state(state_key=None)


def get_screenshot_capabilities() -> Dict[str, bool]:
    info = get_screenshot_info()
    return {
        "wgc": bool(info.get("wgc_available", False)),
        "printwindow": bool(info.get("printwindow_available", False)),
        "gdi": bool(info.get("gdi_available", False)),
        "dxgi": bool(info.get("dxgi_available", False)),
    }


def get_screenshot_stats(engine: Optional[str] = None) -> Dict[str, Any]:
    info = get_screenshot_info()
    stats = info.get("stats")
    payload = dict(stats) if isinstance(stats, dict) else {}
    payload["engine"] = _normalize_engine(engine)
    return payload


def get_last_screenshot_error(engine: Optional[str] = None) -> str:
    try:
        return str(_get_last_capture_error(engine=engine) or "")
    except Exception:
        return ""


def get_screenshot_worker_hard_limit() -> int:
    try:
        return max(1, int(os.cpu_count() or 1))
    except Exception:
        return 1


def set_screenshot_worker_limit(limit: Optional[int] = None) -> int:
    global _WORKER_LIMIT_OVERRIDE
    with _WORKER_LIMIT_LOCK:
        if limit is None:
            _WORKER_LIMIT_OVERRIDE = None
            hard = get_screenshot_worker_hard_limit()
            default_limit = min(3, hard)
            raw = os.getenv("LCA_SCREENSHOT_WORKER_LIMIT")
            if raw is None:
                value = default_limit
            else:
                try:
                    value = int(raw)
                except Exception:
                    value = default_limit
                value = max(1, min(hard, value))
        else:
            hard = get_screenshot_worker_hard_limit()
            try:
                value = int(limit)
            except Exception:
                value = hard
            value = max(1, min(hard, value))
            _WORKER_LIMIT_OVERRIDE = value
    with _WORKER_GATE_LOCK:
        global _WORKER_GATE, _WORKER_GATE_LIMIT
        _WORKER_GATE = None
        _WORKER_GATE_LIMIT = 0
    if limit is None:
        return value
    return value
