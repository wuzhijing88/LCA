#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单模板匹配接口
"""

import logging
import numpy as np
from typing import Optional, Tuple, Dict, Any

from .smart_image_matcher import match_template

logger = logging.getLogger(__name__)


def smart_match_template(haystack: np.ndarray,
                         needle: np.ndarray,
                         confidence: float = 0.8,
                         roi: Optional[Tuple[int, int, int, int]] = None) -> Dict[str, Any]:
    """
    简单模板匹配

    Args:
        haystack: 截图图像
        needle: 模板图像
        confidence: 置信度阈值(0-1)
        roi: 感兴趣区域 (x, y, w, h)

    Returns:
        dict: 匹配结果
    """
    # 参数验证
    if haystack is None or needle is None:
        return _create_failed_result(needle)

    if haystack.size == 0 or needle.size == 0:
        return _create_failed_result(needle)

    template_h, template_w = needle.shape[:2]

    result = match_template(haystack, needle, confidence, roi)

    if result.found:
        x, y, w, h = result.location
        center_x, center_y = result.center
        return {
            'found': True,
            'confidence': result.confidence,
            'location': (x, y, w, h),
            'center': (center_x, center_y),
            'match_location_tl': (x, y),
            'match_score': result.confidence,
            'template_w': w,
            'template_h': h,
            'method': result.method
        }
    else:
        return {
            'found': False,
            'confidence': result.confidence,
            'location': None,
            'center': None,
            'match_location_tl': None,
            'match_score': result.confidence,
            'template_w': template_w,
            'template_h': template_h,
            'method': result.method
        }


def _create_failed_result(needle: Optional[np.ndarray]) -> Dict[str, Any]:
    """创建失败结果"""
    template_h, template_w = (0, 0) if needle is None else needle.shape[:2]

    return {
        'found': False,
        'confidence': 0.0,
        'location': None,
        'center': None,
        'match_location_tl': None,
        'match_score': 0.0,
        'template_w': template_w,
        'template_h': template_h,
        'method': 'error'
    }
