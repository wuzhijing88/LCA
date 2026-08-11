#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单模板匹配模块
"""

import logging
import numpy as np
from typing import Optional, Tuple

from .resolution_aware_matcher import smart_match_template

logger = logging.getLogger(__name__)


class EnhancedTemplateMatcher:
    """模板匹配器"""

    def __init__(self):
        self.template_cache = {}

    def match_template(self,
                      screenshot: np.ndarray,
                      template: np.ndarray,
                      confidence: float = 0.8,
                      roi: Optional[Tuple[int, int, int, int]] = None,
                      **kwargs) -> Optional[dict]:
        """
        模板匹配

        Args:
            screenshot: 截图图像
            template: 模板图像
            confidence: 置信度阈值(0-1)
            roi: 感兴趣区域 (x, y, w, h)

        Returns:
            dict: 匹配结果
        """
        if screenshot is None or template is None:
            return None

        result = smart_match_template(
            haystack=screenshot,
            needle=template,
            confidence=confidence,
            roi=roi,
        )

        if bool(result.get('found', False)):
            return {
                'found': True,
                'confidence': float(result.get('confidence', 0.0) or 0.0),
                'location': result.get('location'),
                'center': result.get('center'),
                'scale': 1.0,
                'method': str(result.get('method', 'template'))
            }
        else:
            return {
                'found': False,
                'confidence': float(result.get('confidence', 0.0) or 0.0)
            }


# 全局实例
_matcher_instance = None

def get_matcher() -> EnhancedTemplateMatcher:
    """获取全局匹配器实例"""
    global _matcher_instance
    if _matcher_instance is None:
        _matcher_instance = EnhancedTemplateMatcher()
    return _matcher_instance
