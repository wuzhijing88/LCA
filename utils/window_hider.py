#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
窗口隐藏管理器 - 统一管理应用窗口的隐藏和恢复
用于各种工具（截图、取色、窗口选择等）启动时隐藏主窗口和弹窗
"""

import logging
from typing import Optional, List, Dict
from PySide6.QtWidgets import QWidget

from utils.window_activation_utils import show_and_activate_overlay, show_and_raise_widget

logger = logging.getLogger(__name__)


class WindowHider:
    """
    窗口隐藏管理器

    功能：
    1. 隐藏主窗口、参数面板、弹窗等
    2. 记录每个窗口的原始可见状态
    3. 工具关闭时恢复窗口显示

    使用方式：
        hider = WindowHider()
        hider.add_window(main_window, "主窗口")
        hider.add_window(param_panel, "参数面板")
        hider.hide_all()  # 隐藏所有窗口
        # ... 工具操作 ...
        hider.restore_all()  # 恢复所有窗口
    """

    def __init__(self):
        """初始化窗口隐藏管理器"""
        self._windows: Dict[str, Dict] = {}  # {name: {widget: QWidget, was_visible: bool}}
        logger.debug("窗口隐藏管理器已创建")

    def add_window(self, widget: Optional[QWidget], name: str = "未命名窗口", was_visible: Optional[bool] = None) -> bool:
        """
        添加需要管理的窗口

        Args:
            widget: Qt窗口部件
            name: 窗口名称（用于日志）
            was_visible: 明确指定窗口的原始可见状态（None表示自动检测当前状态）

        Returns:
            bool: 是否成功添加
        """
        if widget is None:
            logger.debug(f"窗口 '{name}' 为空，跳过添加")
            return False

        if name in self._windows:
            logger.warning(f"窗口 '{name}' 已存在，将覆盖")

        # 记录窗口和原始可见状态
        # 如果明确指定了was_visible参数，使用指定值；否则自动检测当前状态
        if was_visible is None:
            was_visible = widget.isVisible()

        self._windows[name] = {
            'widget': widget,
            'was_visible': was_visible
        }

        logger.debug(f"添加窗口: '{name}' (原始可见状态: {was_visible}, 当前可见: {widget.isVisible()})")
        return True

    def add_windows_from_parent(self, parent: Optional[QWidget]) -> None:
        """
        从父窗口自动添加主窗口和参数面板

        Args:
            parent: 父窗口（通常是参数面板或对话框）
        """
        if parent is None:
            logger.debug("父窗口为空，无法自动添加窗口")
            return

        # 添加父窗口（可能是参数面板）
        self.add_window(parent, "父窗口（参数面板）")

        # 尝试获取主窗口（通过Qt的window()方法获取顶层窗口）
        main_window = parent.window()
        if main_window and main_window != parent:
            self.add_window(main_window, "主窗口")
            logger.debug("已自动添加主窗口和父窗口")
        else:
            logger.debug("父窗口就是主窗口，只添加一个窗口")

    def hide_all(self) -> int:
        """
        隐藏所有已添加的窗口

        Returns:
            int: 成功隐藏的窗口数量
        """
        hidden_count = 0

        for name, info in self._windows.items():
            widget = info['widget']
            was_visible = info['was_visible']

            if was_visible:
                try:
                    widget.hide()
                    hidden_count += 1
                    logger.info(f"隐藏窗口: '{name}'")
                except Exception as e:
                    logger.error(f"隐藏窗口 '{name}' 失败: {e}")
            else:
                logger.debug(f"窗口 '{name}' 原本就不可见，跳过隐藏")

        if hidden_count > 0:
            logger.info(f"成功隐藏 {hidden_count} 个窗口")

        return hidden_count

    def restore_all(self) -> int:
        """
        恢复所有窗口到原始可见状态

        Returns:
            int: 成功恢复的窗口数量
        """
        restored_count = 0

        for name, info in self._windows.items():
            widget = info['widget']
            was_visible = info['was_visible']

            if was_visible:
                try:
                    if widget.isWindow():
                        show_and_activate_overlay(widget, log_prefix=f"{name}恢复", focus=False)
                    else:
                        show_and_raise_widget(widget, log_prefix=f"{name}恢复")

                    restored_count += 1
                    logger.info(f"恢复窗口: '{name}'")
                except Exception as e:
                    logger.error(f"恢复窗口 '{name}' 失败: {e}")
            else:
                logger.debug(f"窗口 '{name}' 原本不可见，跳过恢复")

        if restored_count > 0:
            logger.info(f"成功恢复 {restored_count} 个窗口")

        return restored_count

    def clear(self) -> None:
        """清空所有已添加的窗口"""
        count = len(self._windows)
        self._windows.clear()
        logger.debug(f"清空窗口列表，共移除 {count} 个窗口")

    def get_window_count(self) -> int:
        """获取已添加的窗口数量"""
        return len(self._windows)

    def get_window_names(self) -> List[str]:
        """获取所有已添加窗口的名称"""
        return list(self._windows.keys())


def create_hider_from_parent(parent: Optional[QWidget]) -> WindowHider:
    """
    便捷函数：从父窗口创建WindowHider并自动添加相关窗口

    Args:
        parent: 父窗口（通常是参数面板或对话框）

    Returns:
        WindowHider: 已配置好的窗口隐藏管理器

    示例:
        >>> hider = create_hider_from_parent(self.parent())
        >>> hider.hide_all()
        >>> # ... 工具操作 ...
        >>> hider.restore_all()
    """
    hider = WindowHider()
    hider.add_windows_from_parent(parent)
    return hider


# 示例用法
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    logger.info("=" * 60)
    logger.info("窗口隐藏管理器示例")
    logger.info("=" * 60)

    # 模拟示例
    logger.info("\n创建WindowHider:")
    hider = WindowHider()

    logger.info(f"当前管理的窗口数量: {hider.get_window_count()}")

    # 在实际使用中，这里会传入真实的QWidget对象
    # hider.add_window(main_window, "主窗口")
    # hider.add_window(param_panel, "参数面板")
    # hider.hide_all()
    # ... 工具操作 ...
    # hider.restore_all()

    logger.info("\n示例完成")
