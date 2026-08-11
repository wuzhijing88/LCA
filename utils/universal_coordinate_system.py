"""
通用坐标系统 - 统一处理所有坐标相关操作
基于通用分辨率适配器，提供标准化的坐标处理接口

功能：
1. 坐标选择和获取
2. OCR区域选择和识别
3. 图片点击坐标处理
4. 坐标点击处理
5. 坐标转换和验证
"""

import logging
import time
import ctypes
from ctypes import wintypes
from typing import Tuple, Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum
import random

try:
    from .universal_resolution_adapter import (
        get_universal_adapter, CoordinateInfo, CoordinateType,
        REFERENCE_WIDTH, REFERENCE_HEIGHT
    )
except ImportError:
    # 如果适配器不可用，使用默认值
    REFERENCE_WIDTH = 1280
    REFERENCE_HEIGHT = 720

    class CoordinateType:
        REFERENCE = "reference"
        PHYSICAL = "physical"
        LOGICAL = "logical"

    class CoordinateInfo:
        def __init__(self, x=0, y=0, width=0, height=0, coord_type=None, source_window=None, timestamp=0.0):
            self.x = x
            self.y = y
            self.width = width
            self.height = height
            self.coord_type = coord_type or CoordinateType.PHYSICAL
            self.source_window = source_window
            self.timestamp = timestamp

    def get_universal_adapter():
        class MockAdapter:
            def get_window_state(self, hwnd):
                return None
        return MockAdapter()

logger = logging.getLogger(__name__)

class ClickMode(Enum):
    """点击模式"""
    FOREGROUND = "foreground"  # 前台点击
    BACKGROUND = "background"  # 后台点击
    HOOK = "hook"              # Hook点击

class CoordinateSource(Enum):
    """坐标来源"""
    COORDINATE_SELECTOR = "coordinate_selector"  # 坐标选择器
    OCR_REGION_SELECTOR = "ocr_region_selector"  # OCR区域选择器
    IMAGE_RECOGNITION = "image_recognition"      # 图片识别
    MANUAL_INPUT = "manual_input"               # 手动输入
    TASK_PARAMETER = "task_parameter"           # 任务参数

@dataclass

class UniversalCoordinateSystem:
    """通用坐标系统"""
    
    def __init__(self):
        self.adapter = get_universal_adapter()
        self.user32 = ctypes.windll.user32
        logger.info("通用坐标系统初始化完成")
    
    def create_coordinate_info(self, x: int, y: int, width: int = 0, height: int = 0,
                             source: CoordinateSource = CoordinateSource.MANUAL_INPUT,
                             source_hwnd: Optional[int] = None) -> CoordinateInfo:
        """创建坐标信息对象"""
        return CoordinateInfo(
            x=x, y=y, width=width, height=height,
            coord_type=CoordinateType.PHYSICAL,  # 默认为物理坐标
            source_window=source_hwnd,
            timestamp=time.time()
        )
    
    def normalize_coordinate(self, coord_info: CoordinateInfo, source_hwnd: int) -> CoordinateInfo:
        """将坐标标准化为基准坐标系"""
        if coord_info.coord_type == CoordinateType.REFERENCE:
            return coord_info
        
        # 转换为基准坐标系
        normalized = self.adapter.convert_to_reference(coord_info, source_hwnd)
        logger.debug(f"坐标标准化: ({coord_info.x}, {coord_info.y}) -> ({normalized.x}, {normalized.y})")
        return normalized
    
    def denormalize_coordinate(self, coord_info: CoordinateInfo, target_hwnd: int) -> CoordinateInfo:
        """将基准坐标系转换为目标窗口坐标"""
        if coord_info.coord_type != CoordinateType.REFERENCE:
            logger.warning("输入坐标不是基准坐标系")
            return coord_info
        
        # 转换为目标窗口坐标
        denormalized = self.adapter.convert_from_reference(coord_info, target_hwnd)
        logger.debug(f"坐标反标准化: ({coord_info.x}, {coord_info.y}) -> ({denormalized.x}, {denormalized.y})")
        return denormalized
    
    def process_click_coordinate(self, coord_info: CoordinateInfo, target_hwnd: int,
                               click_mode: ClickMode = ClickMode.BACKGROUND,
                               fixed_offset_x: int = 0, fixed_offset_y: int = 0,
                               random_offset_range: int = 0) -> Tuple[int, int]:
        """
        处理点击坐标

        参数:
            coord_info: 坐标信息对象
            target_hwnd: 目标窗口句柄
            click_mode: 点击模式
            fixed_offset_x: 固定偏移X（像素）
            fixed_offset_y: 固定偏移Y（像素）
            random_offset_range: 随机偏移范围（像素），在[-range, +range]内随机偏移

        返回:
            处理后的坐标 (x, y)
        """
        try:
            # 如果是基准坐标，转换为目标窗口坐标
            if coord_info.coord_type == CoordinateType.REFERENCE:
                target_coord = self.denormalize_coordinate(coord_info, target_hwnd)
            else:
                target_coord = coord_info

            logger.info(f"[坐标处理] 原始坐标: ({coord_info.x}, {coord_info.y})")
            logger.info(f"[坐标处理] 处理后坐标: ({target_coord.x}, {target_coord.y})")
            logger.info(f"[坐标处理] 点击模式: {click_mode.value}")

            # 应用固定偏移
            offset_x = target_coord.x + fixed_offset_x
            offset_y = target_coord.y + fixed_offset_y

            # 应用随机偏移
            if random_offset_range > 0:
                random_x = random.randint(-random_offset_range, random_offset_range)
                random_y = random.randint(-random_offset_range, random_offset_range)
                offset_x += random_x
                offset_y += random_y
                logger.info(f"[坐标偏移] 固定偏移: ({fixed_offset_x}, {fixed_offset_y}), 随机偏移: ({random_x}, {random_y})")
            elif fixed_offset_x != 0 or fixed_offset_y != 0:
                logger.info(f"[坐标偏移] 固定偏移: ({fixed_offset_x}, {fixed_offset_y})")

            # 根据点击模式进行坐标转换
            if click_mode == ClickMode.FOREGROUND:
                # 前台模式：转换为屏幕坐标
                screen_x, screen_y = self._convert_to_screen_coordinates(
                    offset_x, offset_y, target_hwnd
                )
                logger.info(f"[坐标处理] 前台点击坐标: 客户区({offset_x}, {offset_y}) -> 屏幕({screen_x}, {screen_y})")
                return screen_x, screen_y
            elif click_mode == ClickMode.HOOK:
                # Hook模式：使用客户区坐标（与后台模式相同）
                logger.info(f"[坐标处理] Hook点击坐标: 客户区({offset_x}, {offset_y})")
                return offset_x, offset_y
            else:
                # 后台模式：使用客户区坐标
                logger.info(f"[坐标处理] 后台点击坐标: 客户区({offset_x}, {offset_y})")
                return offset_x, offset_y

        except Exception as e:
            logger.error(f"处理点击坐标失败: {e}")
            logger.error(f"回退到原始坐标: ({coord_info.x}, {coord_info.y})")
            return coord_info.x, coord_info.y
    
    def process_ocr_region(self, coord_info: CoordinateInfo, target_hwnd: int) -> Tuple[int, int, int, int]:
        """处理OCR区域坐标"""
        try:
            # 如果是基准坐标，转换为目标窗口坐标
            if coord_info.coord_type == CoordinateType.REFERENCE:
                target_coord = self.denormalize_coordinate(coord_info, target_hwnd)
            else:
                target_coord = coord_info
            
            logger.debug(f"OCR区域处理: ({target_coord.x}, {target_coord.y}, {target_coord.width}, {target_coord.height})")
            return target_coord.x, target_coord.y, target_coord.width, target_coord.height
            
        except Exception as e:
            logger.error(f"处理OCR区域失败: {e}")
            return coord_info.x, coord_info.y, coord_info.width, coord_info.height
    
    def _convert_to_screen_coordinates(self, client_x: int, client_y: int, hwnd: int) -> Tuple[int, int]:
        """将客户区坐标转换为屏幕坐标（每次都实时获取窗口位置）"""
        try:
            # 记录转换前的坐标
            logger.debug(f"[坐标转换] 客户区坐标: ({client_x}, {client_y}), 窗口: {hwnd}")

            # 修复：每次转换前实时获取窗口信息（避免窗口移动后坐标失效）
            try:
                window_rect = wintypes.RECT()
                client_rect = wintypes.RECT()
                # 实时获取窗口和客户区矩形
                self.user32.GetWindowRect(hwnd, ctypes.byref(window_rect))
                self.user32.GetClientRect(hwnd, ctypes.byref(client_rect))

                logger.debug(f"[坐标转换] 实时获取窗口矩形: ({window_rect.left}, {window_rect.top}, {window_rect.right}, {window_rect.bottom})")
                logger.debug(f"[坐标转换] 实时获取客户区矩形: ({client_rect.left}, {client_rect.top}, {client_rect.right}, {client_rect.bottom})")
            except Exception as debug_error:
                logger.debug(f"[坐标转换] 实时获取窗口信息失败: {debug_error}")

            # 执行坐标转换（ClientToScreen 会使用窗口的最新位置）
            point = wintypes.POINT(int(client_x), int(client_y))
            result = self.user32.ClientToScreen(hwnd, ctypes.byref(point))

            if result:
                screen_x, screen_y = point.x, point.y
                logger.debug(f"[坐标转换] 转换成功: 客户区({client_x}, {client_y}) -> 屏幕({screen_x}, {screen_y})")
                return screen_x, screen_y
            else:
                logger.warning(f"[坐标转换] ClientToScreen转换失败，使用原始坐标")
                return client_x, client_y

        except Exception as e:
            logger.error(f"[坐标转换] 转换失败: {e}")
            return client_x, client_y
    
    def validate_coordinate(self, coord_info: CoordinateInfo, target_hwnd: int) -> bool:
        """验证坐标是否在窗口范围内"""
        try:
            window_state = self.adapter.get_window_state(target_hwnd)
            if not window_state:
                return False
            
            # 转换为目标窗口坐标进行验证
            if coord_info.coord_type == CoordinateType.REFERENCE:
                target_coord = self.denormalize_coordinate(coord_info, target_hwnd)
            else:
                target_coord = coord_info
            
            # 检查坐标是否在窗口客户区范围内
            valid_x = 0 <= target_coord.x <= window_state.width
            valid_y = 0 <= target_coord.y <= window_state.height
            
            if target_coord.width > 0 and target_coord.height > 0:
                # 检查区域是否完全在窗口内
                valid_region = (target_coord.x + target_coord.width <= window_state.width and
                              target_coord.y + target_coord.height <= window_state.height)
                return valid_x and valid_y and valid_region
            else:
                return valid_x and valid_y
                
        except Exception as e:
            logger.error(f"坐标验证失败: {e}")
            return False
    
    def apply_random_offset(self, coord_info: CoordinateInfo, offset_range: int = 5) -> CoordinateInfo:
        """应用随机偏移"""
        if offset_range <= 0:
            return coord_info
        
        import random
        offset_x = random.randint(-offset_range, offset_range)
        offset_y = random.randint(-offset_range, offset_range)
        
        new_coord = CoordinateInfo(
            x=coord_info.x + offset_x,
            y=coord_info.y + offset_y,
            width=coord_info.width,
            height=coord_info.height,
            coord_type=coord_info.coord_type,
            source_window=coord_info.source_window,
            timestamp=time.time()
        )
        
        logger.debug(f"随机偏移: ({coord_info.x}, {coord_info.y}) -> ({new_coord.x}, {new_coord.y})")
        return new_coord
    
    def get_window_center(self, hwnd: int) -> CoordinateInfo:
        """获取窗口中心坐标"""
        window_state = self.adapter.get_window_state(hwnd)
        if not window_state:
            return CoordinateInfo(x=0, y=0)
        
        center_x = window_state.width // 2
        center_y = window_state.height // 2
        
        return CoordinateInfo(
            x=center_x,
            y=center_y,
            coord_type=CoordinateType.PHYSICAL,
            source_window=hwnd,
            timestamp=time.time()
        )
    
    def diagnose_coordinate_system(self, hwnd: int) -> Dict[str, Any]:
        """诊断坐标系统状态"""
        try:
            window_state = self.adapter.get_window_state(hwnd)
            if not window_state:
                return {"error": "无法获取窗口状态"}
            
            # 测试坐标转换
            test_coord = CoordinateInfo(x=100, y=100, coord_type=CoordinateType.PHYSICAL)
            normalized = self.normalize_coordinate(test_coord, hwnd)
            denormalized = self.denormalize_coordinate(normalized, hwnd)
            
            return {
                "window_state": {
                    "title": window_state.title,
                    "size": f"{window_state.width}x{window_state.height}",
                    "dpi": window_state.dpi,
                    "scale_factor": window_state.scale_factor
                },
                "coordinate_test": {
                    "original": f"({test_coord.x}, {test_coord.y})",
                    "normalized": f"({normalized.x}, {normalized.y})",
                    "denormalized": f"({denormalized.x}, {denormalized.y})",
                    "conversion_accuracy": abs(test_coord.x - denormalized.x) + abs(test_coord.y - denormalized.y)
                },
                "reference_system": {
                    "reference_resolution": f"{REFERENCE_WIDTH}x{REFERENCE_HEIGHT}",
                    "scale_ratio_x": window_state.width / REFERENCE_WIDTH,
                    "scale_ratio_y": window_state.height / REFERENCE_HEIGHT,
                    "dpi_ratio": window_state.scale_factor
                }
            }
            
        except Exception as e:
            return {"error": f"诊断失败: {e}"}

# 全局实例
_coordinate_system = None

def get_universal_coordinate_system() -> UniversalCoordinateSystem:
    """获取全局通用坐标系统实例"""
    global _coordinate_system
    if _coordinate_system is None:
        _coordinate_system = UniversalCoordinateSystem()
    return _coordinate_system

# 便捷函数
def create_coordinate_from_selector(x: int, y: int, source_hwnd: int) -> CoordinateInfo:
    """从坐标选择器创建坐标信息"""
    return CoordinateInfo(
        x=x, y=y,
        coord_type=CoordinateType.PHYSICAL,
        source_window=source_hwnd,
        timestamp=time.time()
    )

def create_region_from_ocr_selector(x: int, y: int, width: int, height: int, source_hwnd: int) -> CoordinateInfo:
    """从OCR区域选择器创建区域信息"""
    return CoordinateInfo(
        x=x, y=y, width=width, height=height,
        coord_type=CoordinateType.PHYSICAL,
        source_window=source_hwnd,
        timestamp=time.time()
    )

def create_coordinate_from_image_recognition(x: int, y: int, source_hwnd: int) -> CoordinateInfo:
    """从图片识别创建坐标信息"""
    return CoordinateInfo(
        x=x, y=y,
        coord_type=CoordinateType.PHYSICAL,
        source_window=source_hwnd,
        timestamp=time.time()
    )



