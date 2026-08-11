"""
通用分辨率适配器 - 统一处理所有分辨率和DPI相关问题
支持任何分辨率、任何DPI的完美适配

设计原则：
1. 以1280x720@100%DPI为基准坐标系
2. 所有坐标都转换为基准坐标系进行存储和传输
3. 执行时根据实际窗口状态进行实时转换
4. 提供统一的API接口，隐藏复杂的转换逻辑
"""

import logging
import threading
import time
import os
import ctypes
from ctypes import wintypes
from typing import Dict, Tuple, Optional, Any, List
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

# 导入配置管理器
try:
    from .universal_config_manager import get_universal_config
except ImportError:
    # 如果配置管理器不可用，使用默认值
    def get_universal_config():
        class DefaultConfig:
            def get_reference_resolution(self):
                return {'width': 1280, 'height': 720, 'dpi': 96, 'scale_factor': 1.0}
            def get_cache_timeout(self):
                return 1.0
            def is_caching_enabled(self):
                return True
        return DefaultConfig()

# 基准分辨率和DPI（从配置文件获取）
def get_reference_config():
    config = get_universal_config()
    ref_config = config.get_reference_resolution()
    return (
        ref_config.get('width', 1280),
        ref_config.get('height', 720),
        ref_config.get('dpi', 96),
        ref_config.get('scale_factor', 1.0)
    )

REFERENCE_WIDTH, REFERENCE_HEIGHT, REFERENCE_DPI, REFERENCE_SCALE = get_reference_config()

class CoordinateType(Enum):
    """坐标类型枚举"""
    REFERENCE = "reference"  # 基准坐标系 (1280x720@100%DPI)
    PHYSICAL = "physical"    # 物理坐标 (实际像素)
    LOGICAL = "logical"      # 逻辑坐标 (DPI缩放前)

@dataclass
class WindowState:
    """窗口状态信息"""
    hwnd: int
    title: str
    width: int
    height: int
    dpi: int
    scale_factor: float
    client_rect: Tuple[int, int, int, int]
    window_rect: Tuple[int, int, int, int]
    last_update: float

@dataclass
class CoordinateInfo:
    """坐标信息"""
    x: int
    y: int
    width: int = 0
    height: int = 0
    coord_type: CoordinateType = CoordinateType.REFERENCE
    source_window: Optional[int] = None
    timestamp: float = 0.0

class UniversalResolutionAdapter:
    """通用分辨率适配器"""

    def __init__(self):
        self._lock = threading.RLock()
        self._window_states: Dict[int, WindowState] = {}

        # 从配置获取缓存设置
        config = get_universal_config()
        self._cache_timeout = config.get_cache_timeout()
        self._caching_enabled = config.is_caching_enabled()
        self._window_state_ttl_sec = self._read_float_env(
            "LCA_UNIVERSAL_WINDOW_STATE_TTL_SEC",
            900.0,
            10.0,
            7200.0,
        )
        self._window_state_entry_limit = self._read_int_env(
            "LCA_UNIVERSAL_WINDOW_STATE_LIMIT",
            1024,
            64,
            16384,
        )
        self._window_state_prune_interval_sec = self._read_float_env(
            "LCA_UNIVERSAL_WINDOW_STATE_PRUNE_INTERVAL_SEC",
            15.0,
            1.0,
            300.0,
        )
        self._last_window_state_prune_time = 0.0

        # Windows API
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

        # 用于存储主配置文件路径（用于获取 custom_width/height）
        self._main_config_path = None

        # 尝试加载高级DPI API
        try:
            self.shcore = ctypes.WinDLL("shcore", use_last_error=True)
            self._has_advanced_dpi = True
        except:
            self.shcore = None
            self._has_advanced_dpi = False

        try:
            self.user32.GetDC.argtypes = [wintypes.HWND]
            self.user32.GetDC.restype = wintypes.HDC
            self.user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
            self.user32.ReleaseDC.restype = ctypes.c_int
            self.gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
            self.gdi32.GetDeviceCaps.restype = ctypes.c_int
        except Exception:
            pass

        logger.info("通用分辨率适配器初始化完成")

    @staticmethod
    def _read_float_env(name: str, default: float, min_value: float, max_value: float) -> float:
        raw_value = os.environ.get(name)
        if raw_value is None:
            return default
        try:
            parsed_value = float(raw_value)
        except (TypeError, ValueError):
            return default
        if parsed_value < min_value:
            return min_value
        if parsed_value > max_value:
            return max_value
        return parsed_value

    @staticmethod
    def _read_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
        raw_value = os.environ.get(name)
        if raw_value is None:
            return default
        try:
            parsed_value = int(raw_value)
        except (TypeError, ValueError):
            return default
        if parsed_value < min_value:
            return min_value
        if parsed_value > max_value:
            return max_value
        return parsed_value

    def _enforce_window_state_limit_locked(self) -> int:
        overflow = len(self._window_states) - self._window_state_entry_limit
        if overflow <= 0:
            return 0

        removed = 0
        sorted_entries = sorted(
            self._window_states.items(),
            key=lambda item: float(getattr(item[1], "last_update", 0.0) or 0.0),
        )
        for hwnd, _ in sorted_entries[:overflow]:
            if hwnd in self._window_states:
                self._window_states.pop(hwnd, None)
                removed += 1
        return removed

    def _prune_window_states_if_needed(self, now: Optional[float] = None, force: bool = False) -> int:
        current_time = float(now if now is not None else time.time())
        if (
            not force
            and (current_time - self._last_window_state_prune_time) < self._window_state_prune_interval_sec
        ):
            return 0

        self._last_window_state_prune_time = current_time
        if not self._window_states:
            return 0

        stale_hwnds = []
        for hwnd, state in list(self._window_states.items()):
            last_update = float(getattr(state, "last_update", 0.0) or 0.0)
            if (current_time - last_update) > self._window_state_ttl_sec:
                stale_hwnds.append(hwnd)
                continue
            try:
                if not self.user32.IsWindow(hwnd):
                    stale_hwnds.append(hwnd)
            except Exception:
                stale_hwnds.append(hwnd)

        removed = 0
        for hwnd in stale_hwnds:
            if hwnd in self._window_states:
                self._window_states.pop(hwnd, None)
                removed += 1

        removed += self._enforce_window_state_limit_locked()
        return removed

    def cleanup_invalid_window_states(self):
        """【闪退修复】清理失效的窗口状态缓存，防止内存泄漏和访问失效句柄"""
        with self._lock:
            removed_count = self._prune_window_states_if_needed(now=time.time(), force=True)
            if removed_count > 0:
                logger.info(f"清理了 {removed_count} 个失效窗口状态")

    def set_main_config_path(self, config_path: str):
        """设置主配置文件路径，用于读取 custom_width/height"""
        self._main_config_path = config_path
        logger.debug(f"设置主配置文件路径: {config_path}")

    def get_dynamic_reference_resolution(self, hwnd: int = None) -> Tuple[int, int]:
        """
        获取动态参考分辨率

        如果禁用了分辨率修改（custom_width = 0），则使用窗口的实际大小作为参考分辨率
        否则使用配置的 custom_width/height 或默认的 REFERENCE_WIDTH/HEIGHT

        Args:
            hwnd: 窗口句柄，如果提供且禁用了分辨率修改，将使用该窗口的实际大小

        Returns:
            Tuple[int, int]: (参考宽度, 参考高度)
        """
        try:
            # 尝试读取主配置文件中的 custom_width/height
            custom_width = 0
            custom_height = 0

            if self._main_config_path:
                import json
                try:
                    with open(self._main_config_path, 'r', encoding='utf-8') as f:
                        main_config = json.load(f)
                        custom_width = main_config.get('custom_width', 0)
                        custom_height = main_config.get('custom_height', 0)
                except Exception as e:
                    logger.debug(f"读取主配置文件失败: {e}")

            # 如果禁用了分辨率修改（custom_width/height 都为 0）
            if custom_width <= 0 or custom_height <= 0:
                # 如果提供了窗口句柄，使用窗口的实际大小
                if hwnd:
                    window_state = self.get_window_state(hwnd, force_refresh=True)
                    if window_state:
                        logger.debug(f"禁用分辨率修改，使用窗口实际大小: {window_state.width}x{window_state.height}")
                        return (window_state.width, window_state.height)

                # 否则使用默认的参考分辨率
                logger.debug(f"使用默认参考分辨率: {REFERENCE_WIDTH}x{REFERENCE_HEIGHT}")
                return (REFERENCE_WIDTH, REFERENCE_HEIGHT)
            else:
                # 使用配置的自定义分辨率
                logger.debug(f"使用配置的自定义分辨率: {custom_width}x{custom_height}")
                return (custom_width, custom_height)

        except Exception as e:
            logger.error(f"获取动态参考分辨率失败: {e}")
            return (REFERENCE_WIDTH, REFERENCE_HEIGHT)

    def get_window_state(self, hwnd: int, force_refresh: bool = False) -> Optional[WindowState]:
        """获取窗口状态信息"""
        if not hwnd or not self.user32.IsWindow(hwnd):
            return None
            
        current_time = time.time()

        with self._lock:
            self._prune_window_states_if_needed(now=current_time, force=False)
            # 检查缓存（如果启用）
            if (self._caching_enabled and not force_refresh and
                hwnd in self._window_states):
                state = self._window_states[hwnd]
                if current_time - state.last_update < self._cache_timeout:
                    return state
            
            # 获取新的窗口状态
            state = self._detect_window_state(hwnd)
            if state:
                self._window_states[hwnd] = state
                self._enforce_window_state_limit_locked()
                logger.debug(f"窗口状态更新: {state.title} ({state.width}x{state.height}, DPI:{state.dpi})")
            
            return state
    
    def _detect_window_state(self, hwnd: int) -> Optional[WindowState]:
        """检测窗口状态"""
        try:
            # 获取窗口标题
            title_length = self.user32.GetWindowTextLengthW(hwnd)
            if title_length > 0:
                title_buffer = ctypes.create_unicode_buffer(title_length + 1)
                self.user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)
                title = title_buffer.value
            else:
                title = ""
            
            # 获取窗口矩形
            window_rect = wintypes.RECT()
            if not self.user32.GetWindowRect(hwnd, ctypes.byref(window_rect)):
                return None
                
            # 获取客户区矩形
            client_rect = wintypes.RECT()
            if not self.user32.GetClientRect(hwnd, ctypes.byref(client_rect)):
                return None
            
            # 计算客户区尺寸
            width = client_rect.right - client_rect.left
            height = client_rect.bottom - client_rect.top
            
            # 获取DPI信息
            dpi, scale_factor = self._get_window_dpi(hwnd)
            
            return WindowState(
                hwnd=hwnd,
                title=title,
                width=width,
                height=height,
                dpi=dpi,
                scale_factor=scale_factor,
                client_rect=(client_rect.left, client_rect.top, client_rect.right, client_rect.bottom),
                window_rect=(window_rect.left, window_rect.top, window_rect.right, window_rect.bottom),
                last_update=time.time()
            )
            
        except Exception as e:
            logger.error(f"检测窗口状态失败: {e}")
            return None
    
    def _get_window_dpi(self, hwnd: int) -> Tuple[int, float]:
        """获取窗口DPI信息"""
        try:
            # 方法1: 使用GetDpiForWindow (Windows 10 1607+)
            if hasattr(self.user32, 'GetDpiForWindow'):
                try:
                    dpi = self.user32.GetDpiForWindow(hwnd)
                    if dpi > 0:
                        scale_factor = dpi / REFERENCE_DPI
                        return dpi, scale_factor
                except:
                    pass
            
            # 方法2: 使用系统DPI
            hdc = self.user32.GetDC(0)
            if hdc:
                try:
                    dpi = self.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
                    if dpi > 0:
                        scale_factor = dpi / REFERENCE_DPI
                        return dpi, scale_factor
                finally:
                    self.user32.ReleaseDC(0, hdc)
            
            # 默认值
            return REFERENCE_DPI, REFERENCE_SCALE
            
        except Exception as e:
            logger.debug(f"获取DPI失败: {e}")
            return REFERENCE_DPI, REFERENCE_SCALE
    
    def convert_to_reference(self, coord_info: CoordinateInfo, source_hwnd: int) -> CoordinateInfo:
        """将坐标转换为基准坐标系"""
        if coord_info.coord_type == CoordinateType.REFERENCE:
            return coord_info

        window_state = self.get_window_state(source_hwnd)
        if not window_state:
            logger.warning(f"无法获取窗口状态，使用原始坐标: {source_hwnd}")
            return coord_info

        # 获取动态参考分辨率
        ref_width, ref_height = self.get_dynamic_reference_resolution(source_hwnd)

        # 【闪退修复】检查窗口尺寸有效性，防止除零错误
        if window_state.width <= 0 or window_state.height <= 0:
            logger.error(f"无效的窗口尺寸: {window_state.width}x{window_state.height}，无法转换坐标")
            return coord_info

        # 【闪退修复】检查参考分辨率有效性
        if ref_width <= 0 or ref_height <= 0:
            logger.error(f"无效的参考分辨率: {ref_width}x{ref_height}，无法转换坐标")
            return coord_info

        # Scale by client-area size only. GetClientRect already returns logical pixels.
        width_ratio = ref_width / window_state.width
        height_ratio = ref_height / window_state.height

        x_ratio = width_ratio
        y_ratio = height_ratio
        # 转换坐标
        ref_x = int(coord_info.x * x_ratio)
        ref_y = int(coord_info.y * y_ratio)
        ref_width_val = int(coord_info.width * x_ratio) if coord_info.width > 0 else 0
        ref_height_val = int(coord_info.height * y_ratio) if coord_info.height > 0 else 0

        logger.debug(f"坐标转换为基准: ({coord_info.x}, {coord_info.y}) -> ({ref_x}, {ref_y})")
        logger.debug(f"转换比例: x={x_ratio:.3f}, y={y_ratio:.3f}, 参考分辨率: {ref_width}x{ref_height}")

        return CoordinateInfo(
            x=ref_x,
            y=ref_y,
            width=ref_width_val,
            height=ref_height_val,
            coord_type=CoordinateType.REFERENCE,
            source_window=source_hwnd,
            timestamp=time.time()
        )
    
    def convert_from_reference(self, coord_info: CoordinateInfo, target_hwnd: int) -> CoordinateInfo:
        """将基准坐标系转换为目标窗口坐标"""
        if coord_info.coord_type != CoordinateType.REFERENCE:
            logger.warning("输入坐标不是基准坐标系")
            return coord_info

        window_state = self.get_window_state(target_hwnd)
        if not window_state:
            logger.warning(f"无法获取窗口状态，使用原始坐标: {target_hwnd}")
            return coord_info

        # 获取动态参考分辨率
        ref_width, ref_height = self.get_dynamic_reference_resolution(target_hwnd)

        # 【闪退修复】检查参考分辨率有效性，防止除零错误
        if ref_width <= 0 or ref_height <= 0:
            logger.error(f"无效的参考分辨率: {ref_width}x{ref_height}，无法转换坐标")
            return coord_info

        # 【闪退修复】检查窗口尺寸有效性
        if window_state.width <= 0 or window_state.height <= 0:
            logger.error(f"无效的窗口尺寸: {window_state.width}x{window_state.height}，无法转换坐标")
            return coord_info

        # Scale by client-area size only. GetClientRect already returns logical pixels.
        width_ratio = window_state.width / ref_width
        height_ratio = window_state.height / ref_height

        x_ratio = width_ratio
        y_ratio = height_ratio
        # 转换坐标
        target_x = int(coord_info.x * x_ratio)
        target_y = int(coord_info.y * y_ratio)
        target_width = int(coord_info.width * x_ratio) if coord_info.width > 0 else 0
        target_height = int(coord_info.height * y_ratio) if coord_info.height > 0 else 0

        logger.debug(f"基准坐标转换为目标: ({coord_info.x}, {coord_info.y}) -> ({target_x}, {target_y})")
        logger.debug(f"转换比例: x={x_ratio:.3f}, y={y_ratio:.3f}, 参考分辨率: {ref_width}x{ref_height}")

        return CoordinateInfo(
            x=target_x,
            y=target_y,
            width=target_width,
            height=target_height,
            coord_type=CoordinateType.PHYSICAL,
            source_window=target_hwnd,
            timestamp=time.time()
        )
    
    def adjust_window_resolution(self, hwnd: int, target_width: int = REFERENCE_WIDTH,
                               target_height: int = REFERENCE_HEIGHT) -> bool:
        """调整窗口分辨率到指定尺寸"""
        try:
            if not hwnd or not self.user32.IsWindow(hwnd):
                logger.error(f"无效的窗口句柄: {hwnd}")
                return False

            # 获取当前窗口状态
            current_state = self.get_window_state(hwnd, force_refresh=True)
            if not current_state:
                logger.error(f"无法获取窗口状态: {hwnd}")
                return False

            logger.info(f"[HWND:{hwnd}] 调整窗口分辨率: {current_state.title} "
                       f"{current_state.width}x{current_state.height} -> {target_width}x{target_height}")

            # 如果已经是目标尺寸，跳过调整
            if current_state.width == target_width and current_state.height == target_height:
                logger.info(f"[HWND:{hwnd}] 窗口已经是目标尺寸: {target_width}x{target_height}")
                return True

            # 检查窗口是否可以调整大小
            if not self._can_resize_window(hwnd):
                logger.warning(f"[HWND:{hwnd}] 窗口不支持调整大小: {current_state.title}")
                return False

            # 检查是否为子窗口
            parent_hwnd = self.user32.GetParent(hwnd)
            is_child_window = parent_hwnd != 0

            logger.info(f"[HWND:{hwnd}] 父窗口检测: 父HWND={parent_hwnd}, 是子窗口={is_child_window}")

            resize_target_hwnd = parent_hwnd if is_child_window else hwnd
            self._prepare_window_for_resize(resize_target_hwnd)

            if is_child_window:
                logger.info(f"[HWND:{hwnd}] 检测到子窗口，将调整父子窗口")
                return self._adjust_parent_and_child_window(parent_hwnd, hwnd, target_width, target_height)
            else:
                logger.info(f"[HWND:{hwnd}] 检测到普通窗口，直接调整")
                return self._adjust_single_window_direct(hwnd, target_width, target_height)

        except Exception as e:
            logger.error(f"[HWND:{hwnd}] 调整窗口分辨率时发生错误: {e}")
            return False

    def _can_resize_window(self, hwnd: int) -> bool:
        """检查窗口是否可以调整大小"""
        try:
            # 获取窗口样式
            GWL_STYLE = -16
            style = self.user32.GetWindowLongW(hwnd, GWL_STYLE)

            # 检查窗口样式标志
            WS_THICKFRAME = 0x00040000  # 可调整大小的边框

            # 如果窗口有可调整大小的边框，则认为可以调整
            can_resize = bool(style & WS_THICKFRAME)

            if not can_resize:
                logger.debug(f"[HWND:{hwnd}] 窗口样式不支持调整大小: 0x{style:08X}")

            return can_resize

        except Exception as e:
            logger.error(f"检查窗口是否可调整大小时发生错误: {e}")
            # 出错时假设可以调整，让后续逻辑处理
            return True

    @staticmethod
    def _normalize_window_dimension(value: int, minimum: int = 1) -> int:
        try:
            normalized = int(value)
        except Exception:
            normalized = int(minimum)
        return max(int(minimum), normalized)

    def _prepare_window_for_resize(self, hwnd: int):
        """在调整大小前恢复最小化/最大化窗口，避免窗口状态导致调整失败。"""
        try:
            if not hwnd or not self.user32.IsWindow(hwnd):
                return

            SW_RESTORE = 9
            restored = False

            if self.user32.IsIconic(hwnd):
                logger.info(f"[HWND:{hwnd}] 窗口处于最小化状态，先恢复并强制激活")
                self.user32.ShowWindow(hwnd, SW_RESTORE)
                restored = True

            elif self.user32.IsZoomed(hwnd):
                logger.info(f"[HWND:{hwnd}] 窗口处于最大化状态，先恢复正常再调整")
                self.user32.ShowWindow(hwnd, SW_RESTORE)
                restored = True

            if restored:
                time.sleep(0.2)
                try:
                    self.user32.SetForegroundWindow(hwnd)
                except Exception:
                    pass
                try:
                    self.user32.SetActiveWindow(hwnd)
                except Exception:
                    pass
                try:
                    self.user32.BringWindowToTop(hwnd)
                except Exception:
                    pass
                self._force_window_refresh(hwnd)
                time.sleep(0.1)
                with self._lock:
                    self._window_states.pop(hwnd, None)

        except Exception as e:
            logger.warning(f"[HWND:{hwnd}] 调整前准备窗口状态失败: {e}")

    def _resolve_retry_window_size(self, updated_state: WindowState, target_width: int, target_height: int) -> Tuple[int, int]:
        window_rect = updated_state.window_rect
        current_window_width = max(1, int(window_rect[2] - window_rect[0]))
        current_window_height = max(1, int(window_rect[3] - window_rect[1]))
        width_delta = int(target_width) - int(updated_state.width)
        height_delta = int(target_height) - int(updated_state.height)
        retry_width = self._normalize_window_dimension(current_window_width + width_delta)
        retry_height = self._normalize_window_dimension(current_window_height + height_delta)
        return retry_width, retry_height

    def _adjust_single_window_direct(self, hwnd: int, target_width: int, target_height: int) -> bool:
        """直接调整单个窗口（优化版）

        使用多种方法确保窗口分辨率调整成功：
        1. 优先使用 AdjustWindowRectExForDpi 计算精确的窗口尺寸（DPI感知）
        2. 使用差值法作为备选
        3. 多次尝试调整直到成功
        """
        try:
            current_state = self.get_window_state(hwnd, force_refresh=True)
            if not current_state:
                return False

            # 获取窗口样式用于精确计算
            GWL_STYLE = -16
            GWL_EXSTYLE = -20
            style = self.user32.GetWindowLongW(hwnd, GWL_STYLE)
            ex_style = self.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

            # 检查窗口是否有菜单
            has_menu = bool(self.user32.GetMenu(hwnd))

            # 获取窗口DPI
            dpi = REFERENCE_DPI
            if hasattr(self.user32, 'GetDpiForWindow'):
                try:
                    window_dpi = self.user32.GetDpiForWindow(hwnd)
                    if window_dpi > 0:
                        dpi = window_dpi
                except:
                    pass

            logger.debug(f"窗口样式: style=0x{style:08X}, ex_style=0x{ex_style:08X}, has_menu={has_menu}, DPI={dpi}")

            # 方法1: 使用 AdjustWindowRectExForDpi（Windows 10 1607+）
            new_window_width = None
            new_window_height = None

            try:
                if hasattr(self.user32, 'AdjustWindowRectExForDpi'):
                    rect = wintypes.RECT()
                    rect.left = 0
                    rect.top = 0
                    rect.right = target_width
                    rect.bottom = target_height

                    result = self.user32.AdjustWindowRectExForDpi(
                        ctypes.byref(rect),
                        style,
                        has_menu,
                        ex_style,
                        dpi
                    )

                    if result:
                        new_window_width = rect.right - rect.left
                        new_window_height = rect.bottom - rect.top
                        logger.info(f"[AdjustWindowRectExForDpi] 计算窗口尺寸: {new_window_width}x{new_window_height} (DPI={dpi})")
            except Exception as e:
                logger.debug(f"AdjustWindowRectExForDpi 不可用: {e}")

            # 方法2: 使用 AdjustWindowRectEx（非DPI感知，作为备选）
            if new_window_width is None:
                try:
                    rect = wintypes.RECT()
                    rect.left = 0
                    rect.top = 0
                    rect.right = target_width
                    rect.bottom = target_height

                    result = self.user32.AdjustWindowRectEx(
                        ctypes.byref(rect),
                        style,
                        has_menu,
                        ex_style
                    )

                    if result:
                        new_window_width = rect.right - rect.left
                        new_window_height = rect.bottom - rect.top
                        logger.info(f"[AdjustWindowRectEx] 计算窗口尺寸: {new_window_width}x{new_window_height}")
                except Exception as e:
                    logger.debug(f"AdjustWindowRectEx 失败: {e}")

            # 方法3: 使用差值法（最可靠的备选方案）
            if new_window_width is None:
                window_rect = current_state.window_rect
                border_width = (window_rect[2] - window_rect[0]) - current_state.width
                border_height = (window_rect[3] - window_rect[1]) - current_state.height
                new_window_width = self._normalize_window_dimension(target_width + border_width)
                new_window_height = self._normalize_window_dimension(target_height + border_height)
                logger.info(f"[差值法] 计算窗口尺寸: {new_window_width}x{new_window_height} (边框: {border_width}x{border_height})")

            # 获取当前窗口位置
            window_rect = current_state.window_rect
            current_left = window_rect[0]
            current_top = window_rect[1]

            new_window_width = self._normalize_window_dimension(new_window_width)
            new_window_height = self._normalize_window_dimension(new_window_height)

            # 多次尝试调整（最多3次）
            max_attempts = 3
            for attempt in range(max_attempts):
                logger.info(f"[调整尝试 {attempt + 1}/{max_attempts}] 目标窗口尺寸: {new_window_width}x{new_window_height}")

                # 尝试使用 SetWindowPos
                # SWP_NOZORDER (0x0004) - 保持Z顺序不变
                # SWP_NOACTIVATE (0x0010) - 不激活窗口
                # SWP_FRAMECHANGED (0x0020) - 强制重新计算边框（重要！）
                success = self.user32.SetWindowPos(
                    hwnd, 0, current_left, current_top, new_window_width, new_window_height,
                    0x0004 | 0x0010 | 0x0020  # SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
                )

                if not success:
                    error_code = ctypes.windll.kernel32.GetLastError()
                    logger.warning(f"SetWindowPos 返回失败 (错误代码: {error_code})，尝试 MoveWindow")

                    # 备选：使用 MoveWindow
                    success = self.user32.MoveWindow(
                        hwnd, current_left, current_top,
                        new_window_width, new_window_height, True  # True = 重绘窗口
                    )

                    if not success:
                        error_code = ctypes.windll.kernel32.GetLastError()
                        logger.warning(f"MoveWindow 也失败 (错误代码: {error_code})")

                # 等待窗口系统更新
                time.sleep(0.15)

                # 强制刷新窗口
                self._force_window_refresh(hwnd)

                time.sleep(0.1)

                # 清除缓存
                with self._lock:
                    if hwnd in self._window_states:
                        del self._window_states[hwnd]

                # 验证调整结果
                updated_state = self.get_window_state(hwnd, force_refresh=True)
                if updated_state:
                    actual_width = updated_state.width
                    actual_height = updated_state.height
                    width_diff = abs(actual_width - target_width)
                    height_diff = abs(actual_height - target_height)

                    logger.info(f"[验证] 实际客户区: {actual_width}x{actual_height}, 差值: {width_diff}x{height_diff}")

                    if width_diff == 0 and height_diff == 0:
                        logger.info(f"窗口分辨率调整完全成功!")
                        return True
                    elif width_diff <= 5 and height_diff <= 5:
                        logger.info(f"窗口分辨率调整成功（误差在允许范围内）")
                        return True
                    else:
                        # Retry based on current outer size to avoid negative window dimensions
                        logger.info("[retry] recalculating window size from current outer rect...")
                        retry_window_width, retry_window_height = self._resolve_retry_window_size(
                            updated_state,
                            target_width,
                            target_height,
                        )
                        if retry_window_width == new_window_width and retry_window_height == new_window_height:
                            logger.info("[retry] window size is unchanged; stop main resize loop and switch to fallback")
                            break
                        new_window_width = retry_window_width
                        new_window_height = retry_window_height
                        continue
                else:
                    logger.warning(f"无法获取更新后的窗口状态")

            # 最终检查
            final_state = self.get_window_state(hwnd, force_refresh=True)
            if final_state:
                final_width_diff = abs(final_state.width - target_width)
                final_height_diff = abs(final_state.height - target_height)

                if final_width_diff <= 10 and final_height_diff <= 10:
                    logger.info(f"窗口分辨率调整基本成功: 实际 {final_state.width}x{final_state.height}")
                    return True
                else:
                    logger.warning(f"窗口分辨率调整未达到目标: 目标 {target_width}x{target_height}, 实际 {final_state.width}x{final_state.height}")
                    # 尝试备用方法
                    return self._adjust_window_fallback(hwnd, target_width, target_height)

            return False

        except Exception as e:
            logger.error(f"直接调整窗口时发生错误: {e}", exc_info=True)
            return False

    def _force_window_refresh(self, hwnd: int):
        """强制刷新窗口，确保尺寸变化生效"""
        try:
            # 发送窗口消息强制刷新
            WM_SIZE = 0x0005
            WM_WINDOWPOSCHANGED = 0x0047
            WM_NCCALCSIZE = 0x0083
            WM_NCPAINT = 0x0085
            WM_PAINT = 0x000F

            # 获取当前客户区尺寸
            client_rect = wintypes.RECT()
            self.user32.GetClientRect(hwnd, ctypes.byref(client_rect))
            width = client_rect.right - client_rect.left
            height = client_rect.bottom - client_rect.top

            # 发送 WM_SIZE 消息
            SIZE_RESTORED = 0
            lparam = (height << 16) | width
            self.user32.SendMessageW(hwnd, WM_SIZE, SIZE_RESTORED, lparam)

            # 发送 WM_NCCALCSIZE 强制重新计算非客户区
            self.user32.SendMessageW(hwnd, WM_NCCALCSIZE, True, 0)

            # 发送 WM_NCPAINT 重绘非客户区
            self.user32.SendMessageW(hwnd, WM_NCPAINT, 1, 0)

            # 强制重绘
            self.user32.InvalidateRect(hwnd, None, True)
            self.user32.UpdateWindow(hwnd)

            logger.debug(f"[强制刷新] 已发送刷新消息到窗口 {hwnd}")

        except Exception as e:
            logger.debug(f"强制刷新窗口失败: {e}")

    def _adjust_window_fallback(self, hwnd: int, target_width: int, target_height: int) -> bool:
        """备用窗口调整方法（优化版）

        提供多种备选方案：
        1. 使用 win32gui（如果可用）
        2. 使用 MoveWindow API
        3. 使用 WM_SIZING + WM_SIZE 消息组合
        4. 强制窗口样式重置
        """
        try:
            logger.info(f"使用备用方法调整窗口: HWND={hwnd}, 目标大小={target_width}x{target_height}")

            current_state = self.get_window_state(hwnd, force_refresh=True)
            if not current_state:
                logger.error("无法获取窗口状态")
                return False

            window_rect = current_state.window_rect
            border_width = (window_rect[2] - window_rect[0]) - current_state.width
            border_height = (window_rect[3] - window_rect[1]) - current_state.height
            new_window_width = self._normalize_window_dimension(target_width + border_width)
            new_window_height = self._normalize_window_dimension(target_height + border_height)

            # 方法1: 尝试使用 win32gui（更可靠的 Python 绑定）
            try:
                import win32gui
                import win32con

                logger.info("[备用方法1] 尝试使用 win32gui.SetWindowPos")

                # 先尝试移除最大化状态（如果有）
                placement = win32gui.GetWindowPlacement(hwnd)
                if placement[1] == win32con.SW_SHOWMAXIMIZED:
                    logger.info("窗口处于最大化状态，先恢复正常")
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    time.sleep(0.2)

                # 使用 SetWindowPos
                win32gui.SetWindowPos(
                    hwnd,
                    win32con.HWND_TOP,
                    window_rect[0], window_rect[1],
                    new_window_width, new_window_height,
                    win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED
                )

                time.sleep(0.15)
                self._force_window_refresh(hwnd)
                time.sleep(0.1)

                # 验证
                with self._lock:
                    if hwnd in self._window_states:
                        del self._window_states[hwnd]

                updated_state = self.get_window_state(hwnd, force_refresh=True)
                if updated_state:
                    width_diff = abs(updated_state.width - target_width)
                    height_diff = abs(updated_state.height - target_height)
                    if width_diff <= 10 and height_diff <= 10:
                        logger.info(f"[备用方法1] win32gui.SetWindowPos 成功: {updated_state.width}x{updated_state.height}")
                        return True
                    else:
                        logger.warning(f"[备用方法1] 差值仍然较大: {width_diff}x{height_diff}")

            except ImportError:
                logger.debug("win32gui 不可用")
            except Exception as e:
                logger.warning(f"[备用方法1] 失败: {e}")

            # 方法2: 使用 MoveWindow API
            try:
                logger.info("[备用方法2] 尝试使用 MoveWindow")

                success = self.user32.MoveWindow(
                    hwnd, window_rect[0], window_rect[1],
                    new_window_width, new_window_height, True
                )

                if success:
                    time.sleep(0.15)
                    self._force_window_refresh(hwnd)
                    time.sleep(0.1)

                    with self._lock:
                        if hwnd in self._window_states:
                            del self._window_states[hwnd]

                    updated_state = self.get_window_state(hwnd, force_refresh=True)
                    if updated_state:
                        width_diff = abs(updated_state.width - target_width)
                        height_diff = abs(updated_state.height - target_height)
                        if width_diff <= 10 and height_diff <= 10:
                            logger.info(f"[备用方法2] MoveWindow 成功: {updated_state.width}x{updated_state.height}")
                            return True
                else:
                    error_code = ctypes.windll.kernel32.GetLastError()
                    logger.warning(f"[备用方法2] MoveWindow 返回失败 (错误代码: {error_code})")

            except Exception as e:
                logger.warning(f"[备用方法2] 失败: {e}")

            # 方法3: 使用 WM_SIZING + WM_SIZE 消息组合
            try:
                logger.info("[备用方法3] 尝试使用 WM_SIZING + WM_SIZE 消息")

                WM_SIZING = 0x0214
                WM_SIZE = 0x0005
                WM_EXITSIZEMOVE = 0x0232
                SIZE_RESTORED = 0
                WMSZ_BOTTOMRIGHT = 8

                # 创建 RECT 结构
                sizing_rect = wintypes.RECT()
                sizing_rect.left = window_rect[0]
                sizing_rect.top = window_rect[1]
                sizing_rect.right = window_rect[0] + new_window_width
                sizing_rect.bottom = window_rect[1] + new_window_height

                # 发送 WM_SIZING 消息
                self.user32.SendMessageW(hwnd, WM_SIZING, WMSZ_BOTTOMRIGHT, ctypes.byref(sizing_rect))
                time.sleep(0.05)

                # 发送 WM_SIZE 消息
                lparam = wintypes.LPARAM((int(target_height) << 16) | (int(target_width) & 0xFFFF))
                self.user32.SendMessageW(hwnd, WM_SIZE, SIZE_RESTORED, lparam)
                time.sleep(0.05)

                # 发送 WM_EXITSIZEMOVE 表示调整结束
                self.user32.SendMessageW(hwnd, WM_EXITSIZEMOVE, 0, 0)

                time.sleep(0.15)
                self._force_window_refresh(hwnd)
                time.sleep(0.1)

                with self._lock:
                    if hwnd in self._window_states:
                        del self._window_states[hwnd]

                updated_state = self.get_window_state(hwnd, force_refresh=True)
                if updated_state:
                    width_diff = abs(updated_state.width - target_width)
                    height_diff = abs(updated_state.height - target_height)
                    if width_diff <= 10 and height_diff <= 10:
                        logger.info(f"[备用方法3] 消息组合成功: {updated_state.width}x{updated_state.height}")
                        return True

            except Exception as e:
                logger.warning(f"[备用方法3] 失败: {e}")

            # 方法4: 强制修改窗口样式后重新调整
            try:
                logger.info("[备用方法4] 尝试修改窗口样式后重新调整")

                GWL_STYLE = -16
                WS_THICKFRAME = 0x00040000
                SWP_FRAMECHANGED = 0x0020
                SWP_NOMOVE = 0x0002
                SWP_NOZORDER = 0x0004
                SWP_NOACTIVATE = 0x0010

                # 获取当前样式
                current_style = self.user32.GetWindowLongW(hwnd, GWL_STYLE)

                # 临时添加可调整大小的边框样式
                new_style = current_style | WS_THICKFRAME
                self.user32.SetWindowLongW(hwnd, GWL_STYLE, new_style)

                # 通知系统样式已更改
                self.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                    SWP_NOMOVE | 0x0001 | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)  # SWP_NOSIZE = 0x0001

                time.sleep(0.1)

                # 现在尝试调整大小
                success = self.user32.SetWindowPos(
                    hwnd, 0, window_rect[0], window_rect[1],
                    new_window_width, new_window_height,
                    SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
                )

                time.sleep(0.15)

                # 恢复原始样式
                self.user32.SetWindowLongW(hwnd, GWL_STYLE, current_style)
                self.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                    SWP_NOMOVE | 0x0001 | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)

                self._force_window_refresh(hwnd)
                time.sleep(0.1)

                with self._lock:
                    if hwnd in self._window_states:
                        del self._window_states[hwnd]

                updated_state = self.get_window_state(hwnd, force_refresh=True)
                if updated_state:
                    width_diff = abs(updated_state.width - target_width)
                    height_diff = abs(updated_state.height - target_height)
                    if width_diff <= 10 and height_diff <= 10:
                        logger.info(f"[备用方法4] 样式修改后调整成功: {updated_state.width}x{updated_state.height}")
                        return True

            except Exception as e:
                logger.warning(f"[备用方法4] 失败: {e}")

            logger.error("所有备用调整方法都失败")
            return False

        except Exception as e:
            logger.error(f"备用窗口调整方法发生错误: {e}", exc_info=True)
            return False

    def _adjust_parent_and_child_window(self, parent_hwnd: int, child_hwnd: int,
                                      target_width: int, target_height: int) -> bool:
        """调整父窗口和子窗口的大小（适用于模拟器等场景）"""
        try:
            # 获取父窗口标题
            parent_title_length = self.user32.GetWindowTextLengthW(parent_hwnd)
            if parent_title_length > 0:
                parent_title_buffer = ctypes.create_unicode_buffer(parent_title_length + 1)
                self.user32.GetWindowTextW(parent_hwnd, parent_title_buffer, parent_title_length + 1)
                parent_title = parent_title_buffer.value
            else:
                parent_title = "未知父窗口"

            # 获取子窗口标题
            child_title_length = self.user32.GetWindowTextLengthW(child_hwnd)
            if child_title_length > 0:
                child_title_buffer = ctypes.create_unicode_buffer(child_title_length + 1)
                self.user32.GetWindowTextW(child_hwnd, child_title_buffer, child_title_length + 1)
                child_title = child_title_buffer.value
            else:
                child_title = "未知子窗口"

            logger.info(f"[父子调整] 父窗口='{parent_title}' (HWND: {parent_hwnd}), "
                       f"子窗口='{child_title}' (HWND: {child_hwnd})")

            # 获取父窗口矩形
            parent_window_rect = wintypes.RECT()
            parent_client_rect = wintypes.RECT()
            self.user32.GetWindowRect(parent_hwnd, ctypes.byref(parent_window_rect))
            self.user32.GetClientRect(parent_hwnd, ctypes.byref(parent_client_rect))

            # 获取子窗口矩形
            child_window_rect = wintypes.RECT()
            child_client_rect = wintypes.RECT()
            self.user32.GetWindowRect(child_hwnd, ctypes.byref(child_window_rect))
            self.user32.GetClientRect(child_hwnd, ctypes.byref(child_client_rect))

            # 计算当前尺寸
            current_parent_width = parent_window_rect.right - parent_window_rect.left
            current_parent_height = parent_window_rect.bottom - parent_window_rect.top
            current_child_client_width = child_client_rect.right - child_client_rect.left
            current_child_client_height = child_client_rect.bottom - child_client_rect.top

            logger.info(f"当前父窗口大小: {current_parent_width}x{current_parent_height}")
            logger.info(f"当前子窗口客户区: {current_child_client_width}x{current_child_client_height}")

            # 计算需要调整的差值
            width_diff = target_width - current_child_client_width
            height_diff = target_height - current_child_client_height

            logger.info(f"需要调整的差值: 宽度{width_diff}, 高度{height_diff}")

            # 计算新的父窗口大小
            new_parent_width = current_parent_width + width_diff
            new_parent_height = current_parent_height + height_diff

            logger.info(f"新的父窗口大小: {new_parent_width}x{new_parent_height}")

            # 调整父窗口大小（使用与单窗口模式相同的方法）
            try:
                import win32gui
                import win32con

                # 使用win32gui.SetWindowPos，与单窗口模式保持一致
                success = win32gui.SetWindowPos(
                    parent_hwnd, win32con.HWND_TOP,
                    parent_window_rect.left, parent_window_rect.top,
                    new_parent_width, new_parent_height,
                    win32con.SWP_NOMOVE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
                )
            except ImportError:
                # 如果win32gui不可用，回退到ctypes方法
                success = self.user32.SetWindowPos(
                    parent_hwnd, 0,  # HWND_TOP
                    parent_window_rect.left, parent_window_rect.top,
                    new_parent_width, new_parent_height,
                    0x0004 | 0x0010  # SWP_NOZORDER | SWP_NOACTIVATE
                )

            if not success:
                error_code = ctypes.windll.kernel32.GetLastError()
                logger.warning(f"SetWindowPos返回失败: 错误代码 {error_code}，但继续检查实际效果")
                # 不立即返回False，继续检查实际调整效果
            else:
                logger.info(f"父窗口 '{parent_title}' SetWindowPos调用成功")

            # 等待窗口调整完成
            import time
            time.sleep(0.1)

            # 尝试强制刷新子窗口
            logger.info(f"尝试强制刷新子窗口: {child_title}")

            # 方法1: 发送WM_SIZE消息给子窗口
            WM_SIZE = 0x0005
            SIZE_RESTORED = 0
            self.user32.SendMessageW(child_hwnd, WM_SIZE, SIZE_RESTORED,
                                   (target_height << 16) | target_width)

            # 方法2: 尝试直接调整子窗口大小
            child_window_rect = wintypes.RECT()
            self.user32.GetWindowRect(child_hwnd, ctypes.byref(child_window_rect))

            # 计算子窗口的边框
            child_client_rect_before = wintypes.RECT()
            self.user32.GetClientRect(child_hwnd, ctypes.byref(child_client_rect_before))

            child_border_width = (child_window_rect.right - child_window_rect.left) - (child_client_rect_before.right - child_client_rect_before.left)
            child_border_height = (child_window_rect.bottom - child_window_rect.top) - (child_client_rect_before.bottom - child_client_rect_before.top)

            new_child_window_width = target_width + child_border_width
            new_child_window_height = target_height + child_border_height

            logger.info(f"尝试直接调整子窗口: {new_child_window_width}x{new_child_window_height}")

            # 调整子窗口大小
            child_success = self.user32.SetWindowPos(
                child_hwnd, 0,
                0, 0,  # 保持位置不变
                new_child_window_width, new_child_window_height,
                0x0002 | 0x0001 | 0x0010  # SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE
            )

            if child_success:
                logger.info("[雷电模拟器] 子窗口直接调整API调用成功")
            else:
                error_code = ctypes.windll.kernel32.GetLastError()
                logger.warning(f"[雷电模拟器] 子窗口直接调整失败: 错误代码 {error_code}")

            # 方法3: 发送额外的窗口消息来强制刷新
            WM_WINDOWPOSCHANGED = 0x0047
            WM_PAINT = 0x000F
            WM_NCPAINT = 0x0085

            self.user32.SendMessageW(child_hwnd, WM_WINDOWPOSCHANGED, 0, 0)
            self.user32.SendMessageW(child_hwnd, WM_PAINT, 0, 0)
            self.user32.SendMessageW(child_hwnd, WM_NCPAINT, 1, 0)

            # 对于雷电模拟器，等待更长时间
            logger.info("[雷电模拟器] 等待窗口调整生效...")
            time.sleep(0.5)

            # 清除缓存
            with self._lock:
                if parent_hwnd in self._window_states:
                    del self._window_states[parent_hwnd]
                if child_hwnd in self._window_states:
                    del self._window_states[child_hwnd]

            # 验证子窗口的客户区是否达到目标大小
            new_child_client_rect = wintypes.RECT()
            self.user32.GetClientRect(child_hwnd, ctypes.byref(new_child_client_rect))
            new_child_client_width = new_child_client_rect.right - new_child_client_rect.left
            new_child_client_height = new_child_client_rect.bottom - new_child_client_rect.top

            logger.info(f"[雷电模拟器] 第一次调整后子窗口客户区: {new_child_client_width}x{new_child_client_height}")

            if new_child_client_width == target_width and new_child_client_height == target_height:
                logger.info(f"[雷电模拟器] 父子窗口调整完全成功: {child_title}")
                return True
            else:
                logger.warning(f"[雷电模拟器] 需要微调: 期望 {target_width}x{target_height}, "
                             f"实际 {new_child_client_width}x{new_child_client_height}")

                # 计算差值并进行微调（模仿单窗口模式的逻辑）
                width_diff = abs(new_child_client_width - target_width)
                height_diff = abs(new_child_client_height - target_height)

                if width_diff > 5 or height_diff > 5:
                    logger.info("[雷电模拟器] 差距较大，尝试微调父窗口...")

                    fine_tune_width = target_width - new_child_client_width
                    fine_tune_height = target_height - new_child_client_height

                    final_parent_width = new_parent_width + fine_tune_width
                    final_parent_height = new_parent_height + fine_tune_height

                    logger.info(f"[雷电模拟器] 微调差值: 宽度{fine_tune_width}, 高度{fine_tune_height}")
                    logger.info(f"[雷电模拟器] 最终父窗口大小: {final_parent_width}x{final_parent_height}")

                    # 执行微调
                    try:
                        import win32gui
                        import win32con

                        fine_tune_success = win32gui.SetWindowPos(
                            parent_hwnd, win32con.HWND_TOP,
                            parent_window_rect.left, parent_window_rect.top,
                            final_parent_width, final_parent_height,
                            win32con.SWP_NOMOVE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
                        )

                        if fine_tune_success:
                            logger.info("[雷电模拟器] 微调执行成功")

                            # 等待微调生效
                            time.sleep(0.2)

                            # 再次验证
                            final_child_client_rect = wintypes.RECT()
                            self.user32.GetClientRect(child_hwnd, ctypes.byref(final_child_client_rect))
                            final_width = final_child_client_rect.right - final_child_client_rect.left
                            final_height = final_child_client_rect.bottom - final_child_client_rect.top

                            logger.info(f"[雷电模拟器] 微调后子窗口客户区: {final_width}x{final_height}")

                            # 更新结果
                            new_child_client_width = final_width
                            new_child_client_height = final_height
                        else:
                            logger.warning("[雷电模拟器] 微调执行失败")

                    except ImportError:
                        logger.warning("[雷电模拟器] win32gui不可用，跳过微调")

                # 最终判断
                final_width_diff = abs(new_child_client_width - target_width)
                final_height_diff = abs(new_child_client_height - target_height)

                if final_width_diff <= 10 and final_height_diff <= 10:
                    logger.info(f"[雷电模拟器] 调整成功（允许小误差）: 差值 {final_width_diff}x{final_height_diff}")
                    return True
                else:
                    logger.error(f"[雷电模拟器] 调整失败: 差值过大 {final_width_diff}x{final_height_diff}")
                    return False

        except Exception as e:
            logger.error(f"调整父子窗口时发生错误: {e}")
            return False

    def debug_window_info(self, hwnd: int) -> Dict[str, Any]:
        """调试窗口信息"""
        try:
            if not hwnd or not self.user32.IsWindow(hwnd):
                return {"error": "无效的窗口句柄"}

            # 获取窗口标题
            title_length = self.user32.GetWindowTextLengthW(hwnd)
            if title_length > 0:
                title_buffer = ctypes.create_unicode_buffer(title_length + 1)
                self.user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)
                title = title_buffer.value
            else:
                title = ""

            # 获取窗口矩形
            window_rect = wintypes.RECT()
            client_rect = wintypes.RECT()

            self.user32.GetWindowRect(hwnd, ctypes.byref(window_rect))
            self.user32.GetClientRect(hwnd, ctypes.byref(client_rect))

            # 获取窗口类名
            class_name_buffer = ctypes.create_unicode_buffer(256)
            self.user32.GetClassNameW(hwnd, class_name_buffer, 256)
            class_name = class_name_buffer.value

            # 获取窗口状态
            is_visible = bool(self.user32.IsWindowVisible(hwnd))
            is_enabled = bool(self.user32.IsWindowEnabled(hwnd))
            is_iconic = bool(self.user32.IsIconic(hwnd))
            is_zoomed = bool(self.user32.IsZoomed(hwnd))

            return {
                "hwnd": hwnd,
                "title": title,
                "class_name": class_name,
                "window_rect": (window_rect.left, window_rect.top, window_rect.right, window_rect.bottom),
                "client_rect": (client_rect.left, client_rect.top, client_rect.right, client_rect.bottom),
                "client_size": (client_rect.right - client_rect.left, client_rect.bottom - client_rect.top),
                "window_size": (window_rect.right - window_rect.left, window_rect.bottom - window_rect.top),
                "is_visible": is_visible,
                "is_enabled": is_enabled,
                "is_iconic": is_iconic,
                "is_zoomed": is_zoomed
            }

        except Exception as e:
            return {"error": f"获取窗口信息失败: {e}"}

# 全局实例
_universal_adapter = None
_adapter_lock = threading.Lock()

def get_universal_adapter() -> UniversalResolutionAdapter:
    """获取全局通用分辨率适配器实例"""
    global _universal_adapter
    if _universal_adapter is None:
        with _adapter_lock:
            if _universal_adapter is None:
                _universal_adapter = UniversalResolutionAdapter()
    return _universal_adapter
