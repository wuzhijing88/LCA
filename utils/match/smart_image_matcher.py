#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单模板匹配器
"""

import logging
import cv2
import numpy as np
from typing import Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """匹配结果"""
    found: bool
    confidence: float
    center: Optional[Tuple[int, int]] = None
    location: Optional[Tuple[int, int, int, int]] = None
    method: str = "template"


def normalize_match_image(image: Optional[np.ndarray], mode: str = "彩色") -> Optional[np.ndarray]:
    """Normalize template-match inputs without discarding color channels."""
    if image is None or (not isinstance(image, np.ndarray)) or image.size == 0:
        return None

    try:
        mode_key = str(mode or "彩色").strip().casefold()
        gray = mode_key in {"灰度", "gray", "grey", "grayscale"}
        if image.ndim == 2:
            return np.ascontiguousarray(image if gray else cv2.cvtColor(np.ascontiguousarray(image), cv2.COLOR_GRAY2BGR))

        if image.ndim != 3:
            return None

        channels = int(image.shape[2])
        if channels == 3:
            value = np.ascontiguousarray(image)
            return cv2.cvtColor(value, cv2.COLOR_BGR2GRAY) if gray else value
        if channels == 4:
            value = cv2.cvtColor(np.ascontiguousarray(image), cv2.COLOR_BGRA2BGR)
            return cv2.cvtColor(value, cv2.COLOR_BGR2GRAY) if gray else value
        if channels == 1:
            return cv2.cvtColor(np.ascontiguousarray(image[:, :, 0]), cv2.COLOR_GRAY2BGR)
        return None
    except Exception:
        return None


def _rotate_template(template: np.ndarray, angle: float) -> np.ndarray:
    if abs(float(angle)) < 1e-6:
        return template
    h, w = template.shape[:2]
    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, float(angle), 1.0)
    cos_v, sin_v = abs(matrix[0, 0]), abs(matrix[0, 1])
    nw, nh = int(round(h * sin_v + w * cos_v)), int(round(h * cos_v + w * sin_v))
    matrix[0, 2] += nw / 2.0 - center[0]
    matrix[1, 2] += nh / 2.0 - center[1]
    border = 0 if template.ndim == 2 else (0, 0, 0)
    return cv2.warpAffine(template, matrix, (max(1, nw), max(1, nh)), borderValue=border)


def _angles(value) -> list:
    if value is None or value == "":
        return [0.0]
    raw = value if isinstance(value, (list, tuple, set)) else [value]
    result = []
    for item in raw:
        try:
            angle = float(item)
        except (TypeError, ValueError) as exc:
            raise ValueError("旋转角度必须是数字") from exc
        if not np.isfinite(angle) or angle < -180 or angle > 180:
            raise ValueError("旋转角度必须在 -180 到 180 之间")
        if all(abs(angle - old) > 1e-6 for old in result):
            result.append(angle)
    return result[:21] or [0.0]


def match_template(screenshot: np.ndarray,
                   template: np.ndarray,
                   confidence: float = 0.8,
                   roi: Optional[Tuple[int, int, int, int]] = None,
                   mode: str = "彩色",
                   rotation=0) -> MatchResult:
    """
    简单模板匹配

    Args:
        screenshot: 截图图像
        template: 模板图像
        confidence: 置信度阈值(0-1)
        roi: 感兴趣区域 (x, y, w, h)

    Returns:
        MatchResult: 匹配结果
    """
    # 参数验证
    if screenshot is None or template is None:
        return MatchResult(found=False, confidence=0.0, method="error")

    if screenshot.size == 0 or template.size == 0:
        return MatchResult(found=False, confidence=0.0, method="error")

    # ROI处理
    search_img = screenshot
    roi_offset = (0, 0)
    if roi is not None:
        x, y, w, h = roi
        if x >= 0 and y >= 0 and x + w <= screenshot.shape[1] and y + h <= screenshot.shape[0]:
            search_img = screenshot[y:y+h, x:x+w]
            roi_offset = (x, y)

    try:
        search_match_image = normalize_match_image(search_img, mode)
        template_base = normalize_match_image(template, mode)
        if template_base is None:
            return MatchResult(found=False, confidence=0.0, method="error")

        best = None
        for angle in _angles(rotation):
            template_match_image = _rotate_template(template_base, angle)
            if search_match_image.shape[0] < template_match_image.shape[0] or search_match_image.shape[1] < template_match_image.shape[1]:
                continue
            result = cv2.matchTemplate(search_match_image, template_match_image, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if best is None or max_val > best[0]:
                best = (max_val, max_loc, template_match_image)
        if best is None:
            return MatchResult(found=False, confidence=0.0, method="size_error")
        max_val, max_loc, template_match_image = best
        if search_match_image is None:
            return MatchResult(found=False, confidence=0.0, method="error")

        # 尺寸检查
        if (
            search_match_image.shape[0] < template_match_image.shape[0]
            or search_match_image.shape[1] < template_match_image.shape[1]
        ):
            return MatchResult(found=False, confidence=0.0, method="size_error")

        # 执行匹配
        # 检查置信度
        if max_val >= confidence:
            template_h, template_w = template_match_image.shape[:2]
            final_x = max_loc[0] + roi_offset[0]
            final_y = max_loc[1] + roi_offset[1]
            center_x = final_x + template_w // 2
            center_y = final_y + template_h // 2

            return MatchResult(
                found=True,
                confidence=float(max_val),
                center=(center_x, center_y),
                location=(final_x, final_y, template_w, template_h),
                method="template"
            )
        else:
            return MatchResult(
                found=False,
                confidence=float(max_val),
                method="template"
            )

    except Exception as e:
        logger.error(f"模板匹配失败: {e}")
        return MatchResult(found=False, confidence=0.0, method="error")


def match_template_all(
    screenshot: np.ndarray,
    template: np.ndarray,
    confidence: float = 0.8,
    roi: Optional[Tuple[int, int, int, int]] = None,
    max_count: int = 20,
    mode: str = "彩色",
    rotation=0,
) -> list:
    """同一模板的全部命中，按分数从高到低，邻近峰会合并。"""
    if mode not in {"彩色", "灰度"}:
        raise ValueError("图像模式必须是彩色或灰度")
    if not np.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("阈值必须在0到1之间")
    if isinstance(max_count, bool) or not isinstance(max_count, int) or max_count <= 0:
        raise ValueError("最多必须是正整数")
    search = normalize_match_image(screenshot, mode)
    if search is None:
        raise ValueError("截图格式无效")
    roi_x = roi_y = 0
    if roi is not None:
        roi_x, roi_y, roi_w, roi_h = roi
        if roi_x < 0 or roi_y < 0 or roi_w <= 0 or roi_h <= 0 or roi_x + roi_w > search.shape[1] or roi_y + roi_h > search.shape[0]:
            raise ValueError("区域超出截图范围")
        search = search[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]
    search_match_image = search
    template_match_image = normalize_match_image(template, mode)
    if template_match_image is None:
        raise ValueError("模板格式无效")
    heats = []
    for angle in _angles(rotation):
        rotated = _rotate_template(template_match_image, angle)
        if rotated.shape[0] <= search.shape[0] and rotated.shape[1] <= search.shape[1]:
            heat = cv2.matchTemplate(search_match_image, rotated, cv2.TM_CCOEFF_NORMED)
            if not np.isfinite(heat).all():
                raise ValueError("模板匹配产生无效分数")
            heats.append((heat, rotated.shape[:2]))
    if not heats:
        raise ValueError("模板尺寸大于识别区域")
    found = []
    while len(found) < max_count:
        candidates = [(cv2.minMaxLoc(work), index) for index, (work, _size) in enumerate(heats)]
        (_min_val, max_val, _min_loc, max_loc), index = max(candidates, key=lambda candidate: candidate[0][1])
        if max_val < confidence:
            break
        template_h, template_w = heats[index][1]
        left = int(max_loc[0]) + roi_x
        top = int(max_loc[1]) + roi_y
        found.append(
            MatchResult(
                found=True,
                confidence=float(max_val),
                center=(left + template_w // 2, top + template_h // 2),
                location=(left, top, template_w, template_h),
                method="template",
            )
        )
        center_x, center_y = max_loc[0] + template_w // 2, max_loc[1] + template_h // 2
        gap = max(8, min(template_w, template_h) // 2)
        for work, (height, width) in heats:
            x, y = center_x - width // 2, center_y - height // 2
            x0, y0 = max(0, x - gap), max(0, y - gap)
            x1, y1 = min(work.shape[1], x + gap + 1), min(work.shape[0], y + gap + 1)
            work[y0:y1, x0:x1] = -np.inf
    return found
