# -*- coding: utf-8 -*-
"""
主题管理模块
提供亮色/深色主题切换和系统主题跟随功能
"""

from .theme_manager import (
    ThemeManager,
    ThemeWatcher,
    detect_system_theme,
    get_theme_manager,
    reset_theme_manager,
)

__all__ = [
    'ThemeManager',
    'ThemeWatcher',
    'detect_system_theme',
    'get_theme_manager',
    'reset_theme_manager',
]

__version__ = '1.0.0'
