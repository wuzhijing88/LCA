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


def normalize_match_image(image: Optional[np.ndarray]) -> Optional[np.ndarray]:
    """Normalize template-match inputs without discarding color channels."""
    if image is None or (not isinstance(image, np.ndarray)) or image.size == 0:
        return None

    try:
        if image.ndim == 2:
            return cv2.cvtColor(np.ascontiguousarray(image), cv2.COLOR_GRAY2BGR)

        if image.ndim != 3:
            return None

        channels = int(image.shape[2])
        if channels == 3:
            return np.ascontiguousarray(image)
        if channels == 4:
            return cv2.cvtColor(np.ascontiguousarray(image), cv2.COLOR_BGRA2BGR)
        if channels == 1:
            return cv2.cvtColor(np.ascontiguousarray(image[:, :, 0]), cv2.COLOR_GRAY2BGR)
        return None
    except Exception:
        return None


def match_template(screenshot: np.ndarray,
                   template: np.ndarray,
                   confidence: float = 0.8,
                   roi: Optional[Tuple[int, int, int, int]] = None) -> MatchResult:
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
        search_match_image = normalize_match_image(search_img)
        template_match_image = normalize_match_image(template)

        if search_match_image is None or template_match_image is None:
            return MatchResult(found=False, confidence=0.0, method="error")

        # 尺寸检查
        if (
            search_match_image.shape[0] < template_match_image.shape[0]
            or search_match_image.shape[1] < template_match_image.shape[1]
        ):
            return MatchResult(found=False, confidence=0.0, method="size_error")

        # 执行匹配
        result = cv2.matchTemplate(search_match_image, template_match_image, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

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
