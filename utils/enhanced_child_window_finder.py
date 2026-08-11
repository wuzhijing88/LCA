"""
增强的子窗口查找模块

v2.0 优化:
1. 结合 WindowFromPoint、RealChildWindowFromPoint 进行更精确的句柄定位
2. 多策略查找：优先使用 RealChildWindowFromPoint，回退到 ChildWindowFromPointEx
3. 增加 DPI 感知处理
"""

import win32gui
import win32con
import win32api
import ctypes
from ctypes import wintypes
import logging
from typing import Tuple, List, Dict, Optional

logger = logging.getLogger(__name__)

# Windows API 定义
user32 = ctypes.windll.user32

# RealChildWindowFromPoint - 更精确的子窗口查找，忽略分组控件
try:
    RealChildWindowFromPoint = user32.RealChildWindowFromPoint
    RealChildWindowFromPoint.argtypes = [wintypes.HWND, wintypes.POINT]
    RealChildWindowFromPoint.restype = wintypes.HWND
    HAS_REAL_CHILD = True
except AttributeError:
    HAS_REAL_CHILD = False

# WindowFromPoint - 从屏幕坐标获取窗口
try:
    WindowFromPoint = user32.WindowFromPoint
    WindowFromPoint.argtypes = [wintypes.POINT]
    WindowFromPoint.restype = wintypes.HWND
except AttributeError:
    pass


class EnhancedChildWindowFinder:
    """增强的子窗口查找器 - 支持深度递归查找 (v2.0)"""

    # ChildWindowFromPointEx 的标志位
    CWP_ALL = 0x0000  # 不跳过任何窗口
    CWP_SKIPINVISIBLE = 0x0001  # 跳过不可见的窗口
    CWP_SKIPDISABLED = 0x0002  # 跳过禁用的窗口
    CWP_SKIPTRANSPARENT = 0x0004  # 跳过透明的窗口

    def __init__(self, enable_logging: bool = False):
        """
        初始化查找器

        Args:
            enable_logging: 是否启用详细日志输出
        """
        self.enable_logging = enable_logging
        self.has_real_child = HAS_REAL_CHILD

    def _create_point(self, x: int, y: int) -> wintypes.POINT:
        """创建 POINT 结构"""
        pt = wintypes.POINT()
        pt.x = x
        pt.y = y
        return pt

    def find_window_from_point(self, screen_x: int, screen_y: int) -> int:
        """
        使用 WindowFromPoint 从屏幕坐标获取窗口句柄

        Args:
            screen_x: 屏幕坐标 X
            screen_y: 屏幕坐标 Y

        Returns:
            窗口句柄
        """
        try:
            pt = self._create_point(screen_x, screen_y)
            hwnd = WindowFromPoint(pt)
            if self.enable_logging:
                logger.debug(f"[WindowFromPoint] 屏幕({screen_x},{screen_y}) -> hwnd=0x{hwnd:08X}")
            return hwnd
        except Exception as e:
            if self.enable_logging:
                logger.debug(f"[WindowFromPoint] 失败: {e}")
            return 0

    def find_real_child(self, parent_hwnd: int, client_x: int, client_y: int) -> int:
        """
        使用 RealChildWindowFromPoint 查找真实子控件

        相比 ChildWindowFromPoint，RealChildWindowFromPoint:
        - 会忽略分组框（GroupBox）等容器控件
        - 直接返回实际接收输入的控件
        - 对于复杂嵌套的控件层级更准确

        Args:
            parent_hwnd: 父窗口句柄
            client_x: 客户区坐标 X
            client_y: 客户区坐标 Y

        Returns:
            子控件句柄，失败返回 0
        """
        if not self.has_real_child:
            return 0

        try:
            pt = self._create_point(client_x, client_y)
            child = RealChildWindowFromPoint(parent_hwnd, pt)

            if child and child != parent_hwnd and win32gui.IsWindow(child):
                if self.enable_logging:
                    try:
                        class_name = win32gui.GetClassName(child)
                    except:
                        class_name = "Unknown"
                    logger.debug(f"[RealChildWindowFromPoint] ({client_x},{client_y}) -> 0x{child:08X} ({class_name})")
                return child
            return 0
        except Exception as e:
            if self.enable_logging:
                logger.debug(f"[RealChildWindowFromPoint] 失败: {e}")
            return 0

    def find_deepest_child(
        self,
        root_hwnd: int,
        screen_x: int,
        screen_y: int,
        skip_flags: int = None,
        use_multi_strategy: bool = True
    ) -> Tuple[int, List[Dict], Tuple[int, int]]:
        """
        递归查找最深层的子控件（v2.0 多策略版本）

        查找策略（按优先级）:
        1. RealChildWindowFromPoint - 最精确，忽略容器控件
        2. ChildWindowFromPointEx - 标准方法，支持标志位过滤
        3. WindowFromPoint 验证 - 作为最终结果的交叉验证

        Args:
            root_hwnd: 根窗口句柄
            screen_x: 屏幕坐标 X
            screen_y: 屏幕坐标 Y
            skip_flags: 跳过标志位（默认跳过不可见、禁用、透明的控件）
            use_multi_strategy: 是否使用多策略查找（默认True）

        Returns:
            Tuple[int, List[Dict], Tuple[int, int]]:
                - 最深层控件的句柄
                - 完整的控件链路（从根到最深层）
                - 最深层控件的客户区坐标 (x, y)
        """
        # 默认跳过不可见、禁用、透明的控件
        if skip_flags is None:
            skip_flags = (
                self.CWP_SKIPINVISIBLE |
                self.CWP_SKIPDISABLED |
                self.CWP_SKIPTRANSPARENT
            )

        chain = []
        current = root_hwnd

        # 策略0: 使用 WindowFromPoint 获取初始参考
        wfp_hwnd = 0
        if use_multi_strategy:
            wfp_hwnd = self.find_window_from_point(screen_x, screen_y)
            if self.enable_logging and wfp_hwnd:
                logger.debug(f"[策略0] WindowFromPoint 参考句柄: 0x{wfp_hwnd:08X}")

        while True:
            try:
                # 转换为当前控件的客户区坐标
                cx, cy = win32gui.ScreenToClient(current, (screen_x, screen_y))
            except Exception as e:
                if self.enable_logging:
                    logger.debug(f"ScreenToClient 失败: {e}")
                break

            # 获取控件信息
            try:
                class_name = win32gui.GetClassName(current)
            except Exception:
                class_name = ''

            try:
                window_text = win32gui.GetWindowText(current)
            except Exception:
                window_text = ''

            # 记录到链路
            chain.append({
                'hwnd': current,
                'class_name': class_name,
                'window_text': window_text,
                'client_x': cx,
                'client_y': cy,
                'screen_x': screen_x,
                'screen_y': screen_y
            })

            if self.enable_logging:
                logger.debug(
                    f"层级 {len(chain)}: hwnd=0x{current:08X}, "
                    f"class={class_name}, text={window_text[:20] if window_text else ''}, "
                    f"client=({cx},{cy})"
                )

            # ========== 多策略查找子控件 ==========
            child = None

            # 策略1: 优先使用 RealChildWindowFromPoint（更精确）
            if use_multi_strategy and self.has_real_child:
                real_child = self.find_real_child(current, cx, cy)
                if real_child and real_child != current:
                    child = real_child
                    if self.enable_logging:
                        logger.debug(f"[策略1] RealChildWindowFromPoint 找到: 0x{child:08X}")

            # 策略2: 使用 ChildWindowFromPointEx（标准方法）
            if not child:
                try:
                    child = win32gui.ChildWindowFromPointEx(current, (cx, cy), skip_flags)
                    if child and child != current and self.enable_logging:
                        logger.debug(f"[策略2] ChildWindowFromPointEx 找到: 0x{child:08X}")
                except Exception as e:
                    if self.enable_logging:
                        logger.debug(f"ChildWindowFromPointEx 失败: {e}")
                    child = None

            # 终止条件：没有子控件，或子控件就是自己，或子控件无效
            if not child or child == current or not win32gui.IsWindow(child):
                break

            current = child

        # 返回最深层控件
        if not chain:
            return root_hwnd, [], (0, 0)

        deepest_hwnd = chain[-1]['hwnd']
        deepest_client_xy = (chain[-1]['client_x'], chain[-1]['client_y'])

        # 策略3: 与 WindowFromPoint 结果交叉验证
        if use_multi_strategy and wfp_hwnd and wfp_hwnd != deepest_hwnd:
            # 检查 WindowFromPoint 返回的是否是更深层的控件
            if self._is_descendant(root_hwnd, wfp_hwnd):
                # 验证 wfp_hwnd 是否比当前结果更深
                wfp_depth = self._get_window_depth(root_hwnd, wfp_hwnd)
                current_depth = len(chain)
                if wfp_depth > current_depth:
                    if self.enable_logging:
                        logger.debug(f"[策略3] WindowFromPoint 更深: 0x{wfp_hwnd:08X} (深度{wfp_depth} > {current_depth})")
                    # 更新为 WindowFromPoint 的结果
                    try:
                        wfp_cx, wfp_cy = win32gui.ScreenToClient(wfp_hwnd, (screen_x, screen_y))
                        deepest_hwnd = wfp_hwnd
                        deepest_client_xy = (wfp_cx, wfp_cy)
                    except:
                        pass

        if self.enable_logging:
            logger.info(
                f"深度查找完成: 找到 {len(chain)} 层控件, "
                f"最深层=0x{deepest_hwnd:08X}"
            )

        return deepest_hwnd, chain, deepest_client_xy

    def _is_descendant(self, ancestor_hwnd: int, hwnd: int) -> bool:
        """检查 hwnd 是否是 ancestor_hwnd 的后代"""
        try:
            current = hwnd
            max_depth = 50  # 防止无限循环
            for _ in range(max_depth):
                parent = win32gui.GetParent(current)
                if not parent:
                    return False
                if parent == ancestor_hwnd:
                    return True
                current = parent
            return False
        except:
            return False

    def _get_window_depth(self, root_hwnd: int, hwnd: int) -> int:
        """获取窗口相对于根窗口的深度"""
        try:
            depth = 0
            current = hwnd
            max_depth = 50
            for _ in range(max_depth):
                if current == root_hwnd:
                    return depth
                parent = win32gui.GetParent(current)
                if not parent:
                    break
                current = parent
                depth += 1
            return depth
        except:
            return 0

    def find_simple_child(self, hwnd_parent: int, x: int, y: int) -> int:
        """
        简单查找（仅第一层子控件）

        Args:
            hwnd_parent: 父窗口句柄
            x: 客户区坐标 X
            y: 客户区坐标 Y

        Returns:
            int: 子控件句柄，如果没有则返回父窗口句柄
        """
        try:
            child = win32gui.ChildWindowFromPoint(hwnd_parent, (x, y))
            if child and win32gui.IsWindow(child):
                return child
        except Exception:
            pass
        return hwnd_parent

    def client_to_screen(self, hwnd: int, x: int, y: int) -> Tuple[Optional[int], Optional[int]]:
        """
        客户区坐标转屏幕坐标

        Args:
            hwnd: 窗口句柄
            x: 客户区坐标 X
            y: 客户区坐标 Y

        Returns:
            Tuple[Optional[int], Optional[int]]: 屏幕坐标 (x, y)，失败返回 (None, None)
        """
        try:
            screen_pos = win32gui.ClientToScreen(hwnd, (x, y))
            return screen_pos[0], screen_pos[1]
        except Exception as e:
            logger.error(f"客户区坐标转屏幕坐标失败: {e}")
            return None, None

    def get_control_hierarchy_info(self, chain: List[Dict]) -> str:
        """
        格式化输出控件层级信息（用于调试）

        Args:
            chain: 控件链路

        Returns:
            str: 格式化的层级信息
        """
        if not chain:
            return "无控件链路"

        lines = [f"控件层级 (共 {len(chain)} 层):"]
        for i, node in enumerate(chain):
            indent = "  " * i
            hwnd_str = f"0x{node['hwnd']:08X}"
            class_str = node['class_name'] or '(无类名)'
            text_str = node['window_text'][:30] if node['window_text'] else '(无标题)'
            coord_str = f"client=({node['client_x']}, {node['client_y']})"
            lines.append(f"{indent}└─ L{i}: {hwnd_str} | {class_str} | {text_str} | {coord_str}")

        return "\n".join(lines)


# 全局单例
_global_finder = None

def get_child_window_finder(enable_logging: bool = False) -> EnhancedChildWindowFinder:
    """获取全局子窗口查找器实例"""
    global _global_finder
    if _global_finder is None:
        _global_finder = EnhancedChildWindowFinder(enable_logging=enable_logging)
    return _global_finder
