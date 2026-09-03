# -*- coding: utf-8 -*-

"""
点击绑定窗口的指定坐标任务模块
支持前台和后台模式，可以精确点击指定的坐标位置
"""

import logging
import random
import ctypes
import json
import re
from typing import Dict, Any, Optional, Tuple
from utils.input.input_timing import (
    DEFAULT_CLICK_HOLD_SECONDS,
    DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
)

# 安全导入 wintypes
try:
    from ctypes import wintypes
    WINTYPES_AVAILABLE = True
except ImportError:
    WINTYPES_AVAILABLE = False
    # 创建一个简单的 POINT 类作为备用
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                   ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    # 创建一个模拟的 wintypes 模块
    class MockWinTypes:
        POINT = POINT
        RECT = RECT

    wintypes = MockWinTypes()

# 初始化logger（必须在使用前定义）
logger = logging.getLogger(__name__)

# WinAPI 原型（避免 64 位下句柄/返回值截断导致闪退）
_CLICK_USER32 = None
try:
    if hasattr(wintypes, "HWND") and hasattr(wintypes, "BOOL") and hasattr(wintypes, "POINT"):
        _CLICK_USER32 = ctypes.WinDLL("user32", use_last_error=True)
        _CLICK_USER32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        _CLICK_USER32.ScreenToClient.restype = wintypes.BOOL
        _CLICK_USER32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        _CLICK_USER32.ClientToScreen.restype = wintypes.BOOL
        _CLICK_USER32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        _CLICK_USER32.GetWindowRect.restype = wintypes.BOOL
except Exception:
    _CLICK_USER32 = None


def _safe_screen_to_client(hwnd: int, point) -> bool:
    try:
        if _CLICK_USER32 and hasattr(wintypes, "HWND"):
            return bool(_CLICK_USER32.ScreenToClient(wintypes.HWND(hwnd), ctypes.byref(point)))
        return bool(ctypes.windll.user32.ScreenToClient(hwnd, ctypes.byref(point)))
    except Exception:
        return False


def _safe_client_to_screen(hwnd: int, point) -> bool:
    try:
        if _CLICK_USER32 and hasattr(wintypes, "HWND"):
            return bool(_CLICK_USER32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(point)))
        return bool(ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(point)))
    except Exception:
        return False


def _client_to_screen_compensated(hwnd: int, client_x: int, client_y: int, max_iter: int = 3) -> Optional[Tuple[int, int]]:
    """
    客户区->屏幕坐标闭环补偿。
    通过 ClientToScreen 后再 ScreenToClient 回读，迭代抵消固定偏差（如右下偏几像素）。
    """
    try:
        base_hwnd = int(hwnd)
        target_x = int(client_x)
        target_y = int(client_y)
    except Exception:
        return None

    point = wintypes.POINT(target_x, target_y)
    if not _safe_client_to_screen(base_hwnd, point):
        return None

    screen_x = int(point.x)
    screen_y = int(point.y)

    rounds = max(0, int(max_iter))
    for _ in range(rounds):
        back_point = wintypes.POINT(int(screen_x), int(screen_y))
        if not _safe_screen_to_client(base_hwnd, back_point):
            break

        err_x = int(back_point.x) - target_x
        err_y = int(back_point.y) - target_y
        if err_x == 0 and err_y == 0:
            break

        screen_x -= err_x
        screen_y -= err_y

    return int(screen_x), int(screen_y)


def _safe_get_window_rect(hwnd: int) -> Optional[Any]:
    try:
        rect = wintypes.RECT()
        if _CLICK_USER32 and hasattr(wintypes, "HWND"):
            ok = bool(_CLICK_USER32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)))
        else:
            ok = bool(ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)))
        return rect if ok else None
    except Exception:
        return None


def _activate_window_foreground(target_hwnd: Optional[int]) -> None:
    """前台点击前激活当前绑定窗口。"""
    if not target_hwnd or not PYWIN32_AVAILABLE:
        return
    from utils.window.virtual_desktop import skip_cross_desktop_activation

    if skip_cross_desktop_activation(target_hwnd, log_prefix="坐标点击"):
        return
    try:
        hwnd = int(target_hwnd)
    except Exception:
        return
    try:
        if not win32gui.IsWindow(hwnd):
            return
        if win32gui.IsIconic(hwnd):
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            except Exception:
                pass
        try:
            win32gui.BringWindowToTop(hwnd)
        except Exception:
            pass
        try:
            win32gui.SetActiveWindow(hwnd)
        except Exception:
            pass
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
    except Exception:
        return


def _window_to_client_coords(hwnd: int, window_x: int, window_y: int) -> Optional[Tuple[int, int]]:
    """将窗口坐标（相对窗口左上角）转换为客户区坐标。"""
    try:
        if PYWIN32_AVAILABLE and hasattr(win32gui, 'IsIconic') and win32gui.IsIconic(int(hwnd)):
            return None
    except Exception:
        pass

    rect = _safe_get_window_rect(int(hwnd))
    if rect is None:
        return None

    point = wintypes.POINT(int(rect.left) + int(window_x), int(rect.top) + int(window_y))
    if not _safe_screen_to_client(int(hwnd), point):
        return None
    return int(point.x), int(point.y)


def _normalize_coordinate_mode(value: Any) -> str:
    mode = str(value or '').strip()
    if mode in ('窗口坐标', '窗口'):
        return '窗口坐标'
    if mode in ('屏幕坐标', '屏幕'):
        return '屏幕坐标'
    if mode in ('客户区坐标', '客户区'):
        return '客户区坐标'
    return '客户区坐标'


def _normalize_position_mode(value: Any) -> str:
    mode = str(value or '').strip()
    if mode in ('精准坐标', '精准点击', '精确坐标', '精确点击', '无偏移', '原始坐标'):
        return '精准坐标'
    if mode in ('固定偏移', '固定'):
        return '固定偏移'
    if mode in ('随机偏移', '随机'):
        return '随机偏移'
    return '精准坐标'


def _apply_random_offset_with_bounds(
    base_x: int,
    base_y: int,
    random_offset_x: int,
    random_offset_y: int,
    coordinate_hwnd: Optional[int],
) -> tuple[int, int, int, int, int, int]:
    """在给定基准坐标上追加随机偏移，并尽量限制在窗口客户区内。"""
    actual_range_x = max(0, int(random_offset_x or 0))
    actual_range_y = max(0, int(random_offset_y or 0))
    if coordinate_hwnd and PYWIN32_AVAILABLE:
        try:
            client_rect = win32gui.GetClientRect(coordinate_hwnd)
            client_width = client_rect[2] - client_rect[0]
            client_height = client_rect[3] - client_rect[1]
            actual_range_x = min(actual_range_x, int(base_x), max(0, client_width - 1 - int(base_x)))
            actual_range_y = min(actual_range_y, int(base_y), max(0, client_height - 1 - int(base_y)))
            actual_range_x = max(0, actual_range_x)
            actual_range_y = max(0, actual_range_y)
        except Exception:
            actual_range_x = max(0, int(random_offset_x or 0))
            actual_range_y = max(0, int(random_offset_y or 0))

    offset_x = random.randint(-actual_range_x, actual_range_x) if actual_range_x > 0 else 0
    offset_y = random.randint(-actual_range_y, actual_range_y) if actual_range_y > 0 else 0
    return int(base_x) + offset_x, int(base_y) + offset_y, offset_x, offset_y, actual_range_x, actual_range_y


_COORD_NUM_PATTERN = re.compile(r"[-+]?\d*\.?\d+")


def _coerce_int_value(value: Any) -> Optional[int]:
    """将不同类型输入安全转换为整数，失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            return None
    return None


def _extract_coordinate_pair(value: Any) -> Optional[Tuple[int, int]]:
    """从列表/字典/字符串中提取 (x, y) 坐标。"""
    if value is None:
        return None

    if isinstance(value, (list, tuple)) and len(value) >= 2:
        x_val = _coerce_int_value(value[0])
        y_val = _coerce_int_value(value[1])
        if x_val is not None and y_val is not None:
            return x_val, y_val

    if isinstance(value, dict):
        for x_key, y_key in (("x", "y"), ("X", "Y"), ("坐标X", "坐标Y")):
            if x_key in value and y_key in value:
                x_val = _coerce_int_value(value.get(x_key))
                y_val = _coerce_int_value(value.get(y_key))
                if x_val is not None and y_val is not None:
                    return x_val, y_val

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None

        # 允许 JSON 结构字符串："[100,200]" / "{\"x\":100,\"y\":200}"
        if (text.startswith('{') and text.endswith('}')) or (text.startswith('[') and text.endswith(']')):
            try:
                parsed = json.loads(text)
                pair = _extract_coordinate_pair(parsed)
                if pair is not None:
                    return pair
            except Exception:
                pass

        nums = _COORD_NUM_PATTERN.findall(text.replace('，', ','))
        if len(nums) >= 2:
            try:
                return int(float(nums[0])), int(float(nums[1]))
            except ValueError:
                return None

    return None

# 导入通用坐标系统
from utils.universal_coordinate_system import (
    CoordinateInfo, CoordinateType, ClickMode
)
from utils.input_simulation.mode_utils import (
    is_foreground_mode,
    normalize_execution_mode,
)
from .click_action_executor import execute_simulator_click_action
from .click_param_resolver import resolve_click_params
from .task_utils import coerce_bool, precise_sleep
# Windows API 相关导入
try:
    import win32gui
    import win32con
    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False

# 前台输入驱动管理器导入（自动处理 Interception/Win32 回退）
try:
    from utils.input.foreground_input_manager import get_foreground_input_manager
    foreground_input = get_foreground_input_manager()
    FOREGROUND_INPUT_AVAILABLE = True
except ImportError:
    FOREGROUND_INPUT_AVAILABLE = False
    foreground_input = None

# 任务类型标识
TASK_TYPE = "点击指定坐标"
TASK_NAME = "点击指定坐标"

def execute_task(params: Dict[str, Any], counters: Dict[str, int], execution_mode: str,
                target_hwnd: Optional[int], window_region: Optional[Tuple[int, int, int, int]],
                card_id: Optional[int] = None, **kwargs) -> Tuple[bool, str, Optional[int]]:
    """
    执行点击指定坐标任务

    Args:
        params: 任务参数
        counters: 计数器
        execution_mode: 执行模式 ('foreground' 或 'background')
        target_hwnd: 目标窗口句柄
        window_region: 窗口区域
        card_id: 卡片ID
        **kwargs: 其他参数

    Returns:
        Tuple[bool, str, Optional[int]]: (成功状态, 动作, 下一个卡片ID)
    """

    # 获取参数
    coordinate_x = params.get('coordinate_x', 0)
    coordinate_y = params.get('coordinate_y', 0)
    coordinate_value = params.get('coordinate_value')
    coordinate_text = params.get('coordinate_text')
    coordinate_mode = _normalize_coordinate_mode(params.get('coordinate_mode', '客户区坐标'))
    enable_click = coerce_bool(params.get('enable_click', True))
    button, clicks, interval, click_action, _, hold_duration = resolve_click_params(
        params,
        button_key="button",
        clicks_key="clicks",
        interval_key="interval",
        action_key="click_action",
        fallback_action_key="coordinate_click_action",
        auto_release_key="enable_auto_release",
        hold_duration_key="hold_duration",
        mode_label="点击坐标",
        logger_obj=logger,
        log_hold_mode=False,
    )

    # 获取固定偏移和随机偏移范围参数
    position_mode = _normalize_position_mode(
        params.get('position_mode', params.get('coordinate_position_mode', '精准坐标'))
    )  # 精准坐标、固定偏移、随机偏移
    fixed_offset_x = params.get('fixed_offset_x', params.get('coordinate_fixed_offset_x', 0))
    fixed_offset_y = params.get('fixed_offset_y', params.get('coordinate_fixed_offset_y', 0))
    random_offset_x = params.get('random_offset_x', params.get('coordinate_random_offset_x', 5))
    random_offset_y = params.get('random_offset_y', params.get('coordinate_random_offset_y', 5))

    # 获取执行后操作参数
    on_success_action = params.get('on_success', '执行下一步')
    success_jump_id = params.get('success_jump_target_id')
    on_failure_action = params.get('on_failure', '执行下一步')
    failure_jump_id = params.get('failure_jump_target_id')

    if not enable_click:
        logger.info("已关闭点击执行，本次仅保留流程动作并直接成功")
        from .task_utils import handle_success_action
        return handle_success_action(params, card_id, kwargs.get('stop_checker'))

    # 参数验证
    parsed_pair = None
    if coordinate_value not in (None, ""):
        parsed_pair = _extract_coordinate_pair(coordinate_value)
    if parsed_pair is None and coordinate_text not in (None, ""):
        parsed_pair = _extract_coordinate_pair(coordinate_text)
    if parsed_pair is None:
        parsed_pair = _extract_coordinate_pair([coordinate_x, coordinate_y])

    if parsed_pair is None:
        logger.error(f"坐标参数解析失败: coordinate_value={coordinate_value}, coordinate_text={coordinate_text}, coordinate_x={coordinate_x}, coordinate_y={coordinate_y}")
        return _handle_failure(on_failure_action, failure_jump_id, card_id)

    coordinate_x, coordinate_y = parsed_pair

    try:
        clicks = int(clicks)
        interval = float(interval)
        fixed_offset_x = int(fixed_offset_x)
        fixed_offset_y = int(fixed_offset_y)
        random_offset_x = int(random_offset_x)
        random_offset_y = int(random_offset_y)
    except (ValueError, TypeError) as e:
        logger.error(f"参数类型错误: {e}")
        return _handle_failure(on_failure_action, failure_jump_id, card_id)

    if coordinate_x < 0 or coordinate_y < 0:
        logger.error(f"坐标值不能为负数: ({coordinate_x}, {coordinate_y})")
        return _handle_failure(on_failure_action, failure_jump_id, card_id)

    # 执行模式中文映射
    def _format_execution_mode_name(mode: str) -> str:
        if not mode:
            return "未知"
        mode = mode.strip().lower()
        if mode == 'foreground_driver':
            return '前台一'
        if mode == 'foreground_py':
            return '前台二'
        if mode == 'background_sendmessage':
            return '后台一'
        if mode == 'background_postmessage':
            return '后台二'
        if mode.startswith('background'):
            return '后台'
        if mode.startswith('foreground'):
            return '前台'
        return mode

    mode_name = _format_execution_mode_name(execution_mode)
    coordinate_hwnd = target_hwnd

    logger.info(f"准备执行点击坐标: ({coordinate_x}, {coordinate_y}), 坐标模式='{coordinate_mode}', "
                f"按钮='{button}', 次数={clicks}, 模式='{mode_name}', 位置模式='{position_mode}', "
                f"固定偏移=({fixed_offset_x}, {fixed_offset_y}), 随机偏移范围X={random_offset_x}, Y={random_offset_y}")
    
    try:
        # 根据坐标模式创建正确的坐标信息
        if coordinate_mode == '客户区坐标':
            # 客户区坐标是基于窗口的物理坐标，不需要转换
            coord_info = CoordinateInfo(
                x=coordinate_x, y=coordinate_y,
                coord_type=CoordinateType.PHYSICAL,  # 客户区坐标是物理坐标
                source_window=coordinate_hwnd
            )
            logger.info(f"创建客户区坐标: ({coordinate_x}, {coordinate_y}) - 物理坐标")
            # 强制刷新日志
            import sys
            sys.stdout.flush()
            sys.stderr.flush()
        elif coordinate_mode == '窗口坐标':
            if coordinate_hwnd and PYWIN32_AVAILABLE:
                try:
                    if not win32gui.IsWindow(coordinate_hwnd):
                        logger.error(f"窗口句柄无效，无法转换窗口坐标: {coordinate_hwnd}")
                        return _handle_failure(on_failure_action, failure_jump_id, card_id)

                    converted = _window_to_client_coords(int(coordinate_hwnd), int(coordinate_x), int(coordinate_y))
                    if converted is None:
                        logger.error("窗口坐标转换为客户区坐标失败")
                        return _handle_failure(on_failure_action, failure_jump_id, card_id)

                    client_x, client_y = converted
                    coord_info = CoordinateInfo(
                        x=client_x, y=client_y,
                        coord_type=CoordinateType.PHYSICAL,
                        source_window=coordinate_hwnd
                    )
                    logger.info(f"窗口坐标转换: ({coordinate_x}, {coordinate_y}) -> 客户区({client_x}, {client_y})")
                except Exception as e:
                    logger.error(f"窗口坐标转换失败: {e}")
                    return _handle_failure(on_failure_action, failure_jump_id, card_id)
            else:
                logger.error("窗口坐标模式需要有效窗口句柄和pywin32")
                return _handle_failure(on_failure_action, failure_jump_id, card_id)
        else:
            # 屏幕坐标需要转换为客户区坐标
            if coordinate_hwnd and PYWIN32_AVAILABLE:
                try:
                    if not PYWIN32_AVAILABLE:
                        logger.error("pywin32不可用，无法进行坐标转换")
                        return _handle_failure(on_failure_action, failure_jump_id, card_id)

                    point = wintypes.POINT(coordinate_x, coordinate_y)
                    if _safe_screen_to_client(int(coordinate_hwnd), point):
                        client_x, client_y = point.x, point.y
                        coord_info = CoordinateInfo(
                            x=client_x, y=client_y,
                            coord_type=CoordinateType.PHYSICAL,
                            source_window=coordinate_hwnd
                        )
                        logger.info(f"屏幕坐标转换: ({coordinate_x}, {coordinate_y}) -> 客户区({client_x}, {client_y})")
                    else:
                        logger.error("屏幕坐标转换为客户区坐标失败")
                        return _handle_failure(on_failure_action, failure_jump_id, card_id)
                except Exception as e:
                    logger.error(f"坐标转换失败: {e}")
                    return _handle_failure(on_failure_action, failure_jump_id, card_id)
            else:
                # 如果没有窗口句柄，直接使用屏幕坐标
                coord_info = CoordinateInfo(
                    x=coordinate_x, y=coordinate_y,
                    coord_type=CoordinateType.PHYSICAL
                )
                logger.warning("没有窗口句柄，直接使用屏幕坐标")

        # 根据点击位置模式决定是否应用偏移
        if position_mode == '精准坐标':
            # 精准坐标：不应用任何偏移
            logger.info("[精准坐标模式] 使用原始坐标，无偏移")
        elif position_mode == '固定偏移':
            # 固定偏移：先应用固定偏移，再在偏移后的坐标上叠加随机偏移
            if fixed_offset_x != 0 or fixed_offset_y != 0:
                original_x, original_y = coord_info.x, coord_info.y
                coord_info.x += fixed_offset_x
                coord_info.y += fixed_offset_y
                logger.info(f"[固定偏移模式] 原始({original_x}, {original_y}) -> 偏移后({coord_info.x}, {coord_info.y})")
            if random_offset_x > 0 or random_offset_y > 0:
                random_base_x, random_base_y = coord_info.x, coord_info.y
                (
                    coord_info.x,
                    coord_info.y,
                    offset_x,
                    offset_y,
                    actual_range_x,
                    actual_range_y,
                ) = _apply_random_offset_with_bounds(
                    random_base_x,
                    random_base_y,
                    random_offset_x,
                    random_offset_y,
                    coordinate_hwnd,
                )
                logger.info(
                    f"[固定偏移模式] 在偏移后坐标({random_base_x}, {random_base_y})上叠加随机偏移"
                    f" -> ({coord_info.x}, {coord_info.y}), 偏移量=({offset_x}, {offset_y}) "
                    f"[范围: ±{actual_range_x}, ±{actual_range_y}]"
                )
        else:
            # 随机偏移（默认）：使用用户指定的xy轴随机范围，限制在窗口内
            try:
                original_x, original_y = coord_info.x, coord_info.y
                (
                    coord_info.x,
                    coord_info.y,
                    offset_x,
                    offset_y,
                    actual_range_x,
                    actual_range_y,
                ) = _apply_random_offset_with_bounds(
                    original_x,
                    original_y,
                    random_offset_x,
                    random_offset_y,
                    coordinate_hwnd,
                )
                logger.info(f"[随机偏移模式] 原始({original_x}, {original_y}) -> 偏移后({coord_info.x}, {coord_info.y}), 偏移量=({offset_x}, {offset_y}) [范围: ±{actual_range_x}, ±{actual_range_y}]")
            except Exception as offset_error:
                logger.error(f"应用随机偏移失败: {offset_error}", exc_info=True)

        logger.debug(f"[DEBUG] 准备确定点击模式: execution_mode={execution_mode}")

        effective_execution_mode = execution_mode

        # 根据执行模式设置前台输入管理器的强制模式（严格隔离）
        if FOREGROUND_INPUT_AVAILABLE and is_foreground_mode(effective_execution_mode):
            foreground_input.set_execution_mode(effective_execution_mode)
            logger.info(f"[鼠标模式] 前台模式 - {effective_execution_mode}")

        # 确定点击模式 - 使用标准化的执行模式判断
        normalized_mode = normalize_execution_mode(effective_execution_mode)
        # 设置点击模式
        if normalized_mode == 'background':
            click_mode = ClickMode.BACKGROUND
        else:
            click_mode = ClickMode.FOREGROUND

        # 关键修复：前台模式在坐标换算前先激活，避免激活后窗口状态变化引入统一偏差
        if normalized_mode == 'foreground':
            _activate_window_foreground(target_hwnd)

        # 关键修复：前台模式下的坐标处理（参考文字点击的正确实现）
        if normalized_mode == 'foreground':
            # 前台模式强制要求“客户区 -> 屏幕”转换成功，禁止失败后继续点击，避免点歪。
            if not coordinate_hwnd or not PYWIN32_AVAILABLE:
                logger.error("[前台模式] 无有效窗口句柄或pywin32不可用，禁止继续点击以避免坐标偏移")
                return _handle_failure(on_failure_action, failure_jump_id, card_id)
            try:
                if not win32gui.IsWindow(coordinate_hwnd):
                    logger.error("[前台模式] 窗口句柄无效，禁止继续点击以避免坐标偏移")
                    return _handle_failure(on_failure_action, failure_jump_id, card_id)

                compensated = _client_to_screen_compensated(
                    int(coordinate_hwnd),
                    int(coord_info.x),
                    int(coord_info.y),
                    max_iter=3,
                )
                if compensated is None:
                    logger.error("[前台模式] 客户区->屏幕坐标转换失败，禁止继续点击以避免坐标偏移")
                    return _handle_failure(on_failure_action, failure_jump_id, card_id)

                final_x, final_y = compensated
                logger.info(f"[前台模式] 客户区->屏幕: ({coord_info.x}, {coord_info.y}) -> ({final_x}, {final_y})")
            except Exception as e:
                logger.error(f"[前台模式] 坐标转换异常，禁止继续点击以避免坐标偏移: {e}")
                return _handle_failure(on_failure_action, failure_jump_id, card_id)
        else:
            # 后台模式：直接使用客户区坐标（与文字点击一致）
            final_x, final_y = coord_info.x, coord_info.y
            logger.info(f"[{mode_name}模式] 使用客户区坐标: ({final_x}, {final_y})")

        logger.info("=== 坐标处理完成 ===")
        logger.info(f"最终点击坐标: ({final_x}, {final_y}), 模式: {effective_execution_mode}, 动作: {click_action}")

        # 执行点击 - 优先使用新的输入模拟模块
        force_move_before_click = True
        success = _click_with_new_simulator(
            target_hwnd, final_x, final_y, button, clicks, interval,
            effective_execution_mode, click_action, hold_duration,
            move_before_click=force_move_before_click,
        )

        if success:
            logger.info(f"坐标点击成功: ({final_x}, {final_y})")
            # 使用统一的成功处理（包含延迟）
            from .task_utils import handle_success_action
            return handle_success_action(params, card_id, kwargs.get('stop_checker'))
        else:
            logger.error(f"坐标点击失败: ({final_x}, {final_y})")
            # 使用统一的失败处理
            from .task_utils import handle_failure_action
            return handle_failure_action(params, card_id)
            
    except Exception as e:
        logger.error(f"执行点击坐标时发生错误: {e}", exc_info=True)
        from .task_utils import handle_failure_action
        return handle_failure_action(params, card_id)

def _handle_success(action: str, jump_id: Optional[int], card_id: Optional[int]) -> Tuple[bool, str, Optional[int]]:
    """处理成功情况"""
    from .task_utils import resolve_step_action_result

    result = resolve_step_action_result(
        success=True,
        action=action,
        jump_id=jump_id,
        card_id=card_id,
    )
    if result[1] == '继续执行本步骤':
        # 【防闪退】添加最小延迟防止无限快速循环导致闪退
        precise_sleep(0.01)
    return result

def _handle_failure(action: str, jump_id: Optional[int], card_id: Optional[int]) -> Tuple[bool, str, Optional[int]]:
    """处理失败情况"""
    from .task_utils import resolve_step_action_result

    result = resolve_step_action_result(
        success=False,
        action=action,
        jump_id=jump_id,
        card_id=card_id,
    )
    if result[1] == '继续执行本步骤':
        # 【防闪退】添加最小延迟防止无限快速循环导致闪退
        precise_sleep(0.01)
    return result

# 旧的DPI处理函数已移除，现在使用统一DPI处理器

def get_params_definition() -> Dict[str, Dict[str, Any]]:
    """获取参数定义"""
    from .task_utils import get_standard_next_step_delay_params, get_standard_click_offset_params, merge_params_definitions

    # 原有的点击坐标参数
    click_params = {
        "---coordinate_settings---": {"type": "separator", "label": "坐标设置"},
        "coordinate_x": {
            "label": "X坐标",
            "type": "int",
            "default": 0,
            "min": 0,
            "tooltip": "点击位置的X坐标"
        },
        "coordinate_y": {
            "label": "Y坐标",
            "type": "int",
            "default": 0,
            "min": 0,
            "tooltip": "点击位置的Y坐标"
        },
        "coordinate_selector_tool": {
            "label": "坐标获取工具",
            "type": "button",
            "button_text": "点击获取坐标",
            "tooltip": "点击后可以在目标窗口中选择坐标位置",
            "widget_hint": "coordinate_selector"
        },
        "coordinate_mode": {
            "label": "坐标模式",
            "type": "select",
            "options": ["客户区坐标", "窗口坐标", "屏幕坐标"],
            "default": "客户区坐标",
            "tooltip": "客户区坐标相对于窗口内容区域，窗口坐标相对于窗口左上角，屏幕坐标相对于整个屏幕"
        },
        "---click_settings---": {"type": "separator", "label": "点击设置"},
        "enable_click": {
            "label": "启用点击",
            "type": "bool",
            "default": True,
            "tooltip": "关闭后不执行点击，仅按成功流程继续"
        },
        "button": {
            "label": "鼠标按钮",
            "type": "select",
            "options": ["左键", "右键", "中键"],
            "default": "左键",
            "tooltip": "选择要点击的鼠标按钮"
        },
        "click_action": {
            "label": "点击动作",
            "type": "select",
            "options": ["完整点击", "双击", "仅按下", "仅松开"],
            "default": "完整点击",
            "tooltip": "完整点击=按下+松开，双击=发送标准双击消息序列，仅按下=只按下不松开，仅松开=只松开不按下"
        },
        "hold_duration": {
            "label": "按下持续时间(秒)",
            "type": "float",
            "default": DEFAULT_CLICK_HOLD_SECONDS,
            "min": 0.01,
            "max": 10.0,
            "step": 0.01,
            "decimals": 2,
            "tooltip": "仅在'仅按下'动作时，按下后保持的时间",
            "condition": {"param": "click_action", "value": "仅按下"}
        },
        "clicks": {
            "label": "点击次数",
            "type": "int",
            "default": 1,
            "min": 1,
            "max": 10,
            "tooltip": "连续点击的次数"
        },
        "interval": {
            "label": "点击间隔(秒)",
            "type": "float",
            "default": DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
            "min": 0.0,
            "max": 5.0,
            "decimals": 2,
            "tooltip": "多次点击之间的时间间隔"
        },

        "---post_execute---": {"type": "separator", "label": "执行后操作"},
        "on_success": {
            "type": "select",
            "label": "执行成功时",
            "options": ["继续执行本步骤", "执行下一步", "跳转到步骤", "停止工作流"],
            "default": "执行下一步"
        },
        "success_jump_target_id": {
            "type": "int",
            "label": "成功跳转目标 ID",
            "required": False,
            "widget_hint": "card_selector",
            "condition": {"param": "on_success", "value": "跳转到步骤"}
        },
        "on_failure": {
            "type": "select",
            "label": "执行失败时",
            "options": ["继续执行本步骤", "执行下一步", "跳转到步骤", "停止工作流"],
            "default": "执行下一步"
        },
        "failure_jump_target_id": {
            "type": "int",
            "label": "失败跳转目标 ID",
            "required": False,
            "widget_hint": "card_selector",
            "condition": {"param": "on_failure", "value": "跳转到步骤"}
        }
    }

    # 合并延迟参数和偏移参数
    merged = merge_params_definitions(
        click_params,
        get_standard_click_offset_params(),
        get_standard_next_step_delay_params()
    )
    # 坐标点击默认优先精准，避免旧数据缺参时误走随机偏移
    if "position_mode" in merged and isinstance(merged["position_mode"], dict):
        merged["position_mode"]["default"] = "精准坐标"

    def _append_enable_click_condition(param_key: str) -> None:
        param_def = merged.get(param_key)
        if not isinstance(param_def, dict):
            return
        click_enabled_condition = {"param": "enable_click", "value": True}
        existing_condition = param_def.get("condition")
        if existing_condition is None:
            param_def["condition"] = click_enabled_condition
            return
        if isinstance(existing_condition, list):
            param_def["condition"] = list(existing_condition) + [click_enabled_condition]
            return
        if isinstance(existing_condition, dict):
            and_condition = existing_condition.get("and")
            if and_condition is None:
                existing_condition["and"] = click_enabled_condition
            elif isinstance(and_condition, list):
                existing_condition["and"] = list(and_condition) + [click_enabled_condition]
            else:
                existing_condition["and"] = [and_condition, click_enabled_condition]

    for click_param in (
        "---click_settings---",
        "button",
        "click_action",
        "hold_duration",
        "clicks",
        "interval",
        "---click_offset---",
        "offset_selector_tool",
        "position_mode",
        "fixed_offset_x",
        "fixed_offset_y",
        "random_offset_x",
        "random_offset_y",
    ):
        _append_enable_click_condition(click_param)
    return merged

def _perform_simulator_click(simulator, x: int, y: int, button: str, click_action: str,
                            clicks: int, interval: float, hold_duration: float, mode_label: str,
                            require_atomic_hold: bool = False,
                            move_before_click: bool = False,
                            execution_mode: Optional[str] = None,
                            target_hwnd: Optional[int] = None) -> bool:
    logger.info(
        f"[{mode_label}模式] 执行点击: 坐标({x}, {y}), 按钮={button}, 动作={click_action}, 次数={clicks}"
    )
    is_foreground_single_click = (
        is_foreground_mode(execution_mode)
        and str(click_action or "").strip() == "完整点击"
        and int(clicks or 1) == 1
    )
    max_attempts = 3 if is_foreground_single_click else 1
    success = False

    for attempt_index in range(max_attempts):
        success = execute_simulator_click_action(
            simulator=simulator,
            x=x,
            y=y,
            button=button,
            click_action=click_action,
            clicks=clicks,
            interval=interval,
            hold_duration=hold_duration,
            auto_release=True,
            mode_label=f"{mode_label}模式",
            logger_obj=logger,
            single_click_retry=is_foreground_mode(execution_mode),
            require_atomic_hold=require_atomic_hold,
            move_before_click=move_before_click,
            execution_mode=execution_mode,
            target_hwnd=target_hwnd,
            task_type=TASK_TYPE,
        )
        if success:
            break
        if attempt_index < (max_attempts - 1):
            logger.warning(
                f"[{mode_label}模式] 这次没点上，再试一次（{attempt_index + 2}/{max_attempts}）"
            )
            precise_sleep(0.12)

    if success:
        logger.info(f"[{mode_label}模式] 点击成功")
    else:
        logger.warning(f"[{mode_label}模式] 点击失败")
    return success


def _click_with_new_simulator(hwnd: int, x: int, y: int, button: str = 'left',
                             clicks: int = 1, interval: float = DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS, execution_mode: str = 'background',
                             click_action: str = '完整点击', hold_duration: float = DEFAULT_CLICK_HOLD_SECONDS,
                             move_before_click: bool = False) -> Optional[bool]:
    """
    使用输入模拟器执行点击（前台/后台统一入口）

    Args:
        hwnd: 窗口句柄
        x, y: 坐标
        button: 按钮类型
        clicks: 点击次数
        interval: 点击间隔
        execution_mode: 执行模式
        click_action: 点击动作 ('完整点击', '双击', '仅按下', '仅松开')
        hold_duration: 仅按下时的持续时间

    Returns:
        bool: 是否成功
    """
    try:
        logger.info(f"[_click_with_new_simulator] 开始点击: hwnd={hwnd}, 坐标=({x}, {y}), 模式={execution_mode}")

        # 校验窗口句柄
        if not hwnd:
            logger.error("[_click_with_new_simulator] 窗口句柄为空")
            return False

        try:
            if not win32gui.IsWindow(hwnd):
                logger.error(f"[_click_with_new_simulator] 窗口句柄无效: {hwnd}")
                return False
        except Exception as e:
            logger.error(f"[_click_with_new_simulator] 校验窗口句柄失败: {e}")
            return False

        normalized_mode = normalize_execution_mode(execution_mode)
        from utils.input_simulation import global_input_simulator_manager
        simulator = global_input_simulator_manager.get_simulator(hwnd, "auto", execution_mode)

        if not simulator:
            logger.error(f"[{normalized_mode}模式] 输入模拟器不可用")
            return False

        mode_label = {
            'foreground_driver': '前台一',
            'foreground_py': '前台二',
            'background_sendmessage': '后台一',
            'background_postmessage': '后台二',
        }.get(execution_mode, {
            'foreground': '前台',
            'background': '后台',
        }.get(normalized_mode, normalized_mode))
        return _perform_simulator_click(
            simulator,
            x,
            y,
            button,
            click_action,
            clicks,
            interval,
            hold_duration,
            mode_label,
            require_atomic_hold=True,
            move_before_click=move_before_click,
            execution_mode=execution_mode,
            target_hwnd=hwnd,
        )

    except ImportError:
        logger.error("输入模拟器模块不可用")
        return False
    except Exception as e:
        logger.error(f"输入模拟器点击失败: {e}")
        return False

# DPI修正函数已移除，Interception驱动自动处理DPI

if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(level=logging.DEBUG)
    
    test_params = {
        'coordinate_x': 200,
        'coordinate_y': 300,
        'coordinate_mode': '客户区坐标',
        'button': '左键',
        'clicks': 1,
        'interval': DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
        'position_mode': '随机偏移',
        'random_offset_x': 5,
        'random_offset_y': 5
    }
    
    result = execute_task(test_params, {}, 'foreground', None, None)
    logger.info(f"测试结果: {result}")
