#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
窗口隐藏管理器 - 统一管理应用窗口的隐藏和恢复
用于各种工具（截图、取色、窗口选择等）启动时隐藏主窗口和弹窗
"""

import logging
from typing import Optional, List, Dict
from PySide6.QtWidgets import QWidget

from utils.window.window_activation_utils import show_and_raise_widget

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
            'was_visible': was_visible,
            'hidden_by_us': False,
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

        self.add_visible_app_windows(exclude=(parent, main_window))

    def add_visible_app_windows(self, exclude=None) -> int:
        """把当前还能看见的应用窗口补进恢复清单，覆盖层自己除外。"""
        from PySide6.QtWidgets import QApplication

        exclude_ids = {id(item) for item in (exclude or ()) if item is not None}
        added = 0
        for widget in QApplication.topLevelWidgets():
            if id(widget) in exclude_ids:
                continue
            if "Overlay" in type(widget).__name__:
                continue
            try:
                if not widget.isWindow() or not widget.isVisible():
                    continue
            except RuntimeError:
                continue
            base_name = widget.objectName() or type(widget).__name__
            name = base_name
            index = 2
            while name in self._windows:
                if self._windows[name]['widget'] is widget:
                    name = ""
                    break
                name = f"{base_name}_{index}"
                index += 1
            if not name:
                continue
            if self.add_window(widget, name, was_visible=True):
                added += 1
        return added

    def hide_all(self) -> int:
        """
        隐藏所有已添加的窗口

        Returns:
            int: 成功隐藏的窗口数量
        """
        hidden_count = 0

        for name, info in self._windows.items():
            widget = info['widget']
            info['hidden_by_us'] = False
            try:
                if not widget.isVisible():
                    logger.debug(f"窗口 '{name}' 当前不可见，跳过隐藏")
                    continue
                widget.hide()
                info['hidden_by_us'] = True
                hidden_count += 1
                logger.info(f"隐藏窗口: '{name}'")
            except RuntimeError:
                logger.debug(f"隐藏窗口 '{name}' 时对象已销毁")
            except Exception as e:
                logger.error(f"隐藏窗口 '{name}' 失败: {e}")

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

            should_restore = bool(info.get('hidden_by_us')) or bool(was_visible)
            if not should_restore:
                logger.debug(f"窗口 '{name}' 无需恢复，跳过")
                continue
            try:
                widget.show()
                widget.raise_()
                if widget.isWindow():
                    widget.activateWindow()
                else:
                    show_and_raise_widget(widget, log_prefix=f"{name}恢复")
                info['hidden_by_us'] = False
                restored_count += 1
                logger.info(f"恢复窗口: '{name}'")
            except RuntimeError:
                logger.debug(f"恢复窗口 '{name}' 时对象已销毁")
            except Exception as e:
                logger.error(f"恢复窗口 '{name}' 失败: {e}")

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
