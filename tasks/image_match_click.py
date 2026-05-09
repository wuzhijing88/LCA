# 图片点击任务模块
import time
import logging  # 导入logging模块
import random  # 导入random模块
import re
# Import Optional and Tuple for older Python versions
from typing import Dict, Any, Optional, Tuple
import os # Import os for path check
import traceback # Import traceback for printing exception details
from tasks.task_utils import coerce_bool, coerce_float, coerce_int, capture_and_match_template_smart
from tasks.click_action_executor import execute_simulator_click_action
from tasks.click_simulator_adapters import (
    PluginSimulatorAdapter,
)
from tasks.click_param_resolver import resolve_click_params
from tasks.virtual_mouse_state import (
    get_virtual_mouse_coords as _read_virtual_mouse_coords,
    is_virtual_mouse_enabled as _read_virtual_mouse_enabled,
    sync_virtual_mouse_position,
)
from utils.input_timing import (
    DEFAULT_CLICK_HOLD_SECONDS,
    DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
)
from utils.smart_image_matcher import normalize_match_image
from utils.window_binding_utils import get_plugin_bind_args

# 安全导入 OpenCV 和 NumPy
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError as e:
    CV2_AVAILABLE = False
    logging.getLogger(__name__).warning(f"OpenCV或NumPy不可用，图片识别功能将被禁用: {e}")

# Import necessary modules for background execution (requires pywin32)
try:
    import win32gui
    import win32ui
    import win32con
    import win32api
    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False

# Print warning only if execution mode requires it later
# print("警告: pywin32 模块未安装，后台模式将不可用。请运行 'pip install pywin32'")

# Import screenshot helper (智能混合截图)
try:
    from tasks.task_utils import capture_window_smart, is_smart_capture_available, precise_sleep

    # 保持兼容性 - 旧代码使用的变量名
    capture_window_wgc = capture_window_smart

    logger = logging.getLogger(__name__)
    if is_smart_capture_available():
        logger.info("[图片识别] 使用 WGC 通过句柄精确捕获（支持后台）")
    else:
        logger.warning("[图片识别] 截图引擎不可用")
except ImportError as e:
    logger = logging.getLogger(__name__)
    logger.error(f"无法导入截图助手: {e}")
    capture_window_wgc = None
    from utils.precise_sleep import precise_sleep

# Import click utilities
try:
    from utils.win32_utils import click_background
except ImportError:
    click_background = None
    logger.warning("无法导入点击功能")

# 初始化logger
logger = logging.getLogger(__name__)

# 检查截图功能是否可用
if capture_window_wgc is None or click_background is None:
    logger.warning("无法导入截图和点击功能，后台模式可能不可用")

# 高级图像处理功能已移除

# import os # Import os for path normalization - Removed

TASK_NAME = "图片点击"


def _normalize_image_position_mode(value: Any) -> str:
    mode = str(value or "").strip()
    if mode in ("精准坐标", "精准点击", "精确坐标", "精确点击", "无偏移", "原始坐标"):
        return "精准坐标"
    if mode in ("固定偏移", "固定"):
        return "固定偏移"
    if mode in ("随机偏移", "随机"):
        return "随机偏移"
    return "精准坐标"


def locate_image_in_window(
    params: Dict[str, Any],
    target_hwnd: Optional[int],
    card_id: Optional[int] = None,
    capture_timeout: Optional[float] = None,
) -> Tuple[bool, Optional[Tuple[int, int, int, int, int, int]], Optional[str]]:
    """使用当前正式找图链路执行一次定位。"""
    if not CV2_AVAILABLE:
        return False, None, None

    try:
        hwnd = int(target_hwnd) if target_hwnd is not None else 0
    except Exception:
        hwnd = 0
    if hwnd <= 0:
        return False, None, None

    raw_image_path = str((params or {}).get('image_path') or '').strip()
    if not raw_image_path:
        raw_image_paths = str((params or {}).get('image_paths') or '').strip()
        if raw_image_paths:
            for raw_line in re.split(r'[\r\n;]+', raw_image_paths):
                line = raw_line.strip()
                if not line or line.startswith('#'):
                    continue
                if '  # ' in line:
                    line = line.split('  # ', 1)[0].strip()
                if line:
                    raw_image_path = line
                    break

    if not raw_image_path:
        return False, None, None

    try:
        from tasks.task_utils import correct_single_image_path, safe_imread
    except Exception as exc:
        logger.warning(f"定位图片失败：加载找图依赖异常: {exc}")
        return False, None, None

    absolute_image_path = correct_single_image_path(raw_image_path, card_id)
    if not absolute_image_path:
        logger.warning(f"定位图片失败：图片路径无效: {raw_image_path}")
        return False, None, None

    needle_image_raw = safe_imread(absolute_image_path, flags=cv2.IMREAD_UNCHANGED)
    if needle_image_raw is None:
        logger.warning(f"定位图片失败：模板读取失败: {absolute_image_path}")
        return False, None, absolute_image_path

    needle_match_image = normalize_match_image(needle_image_raw)

    if needle_match_image is None or getattr(needle_match_image, 'size', 0) <= 0:
        logger.warning("定位图片失败：模板规范化结果无效")
        return False, None, absolute_image_path

    try:
        template_h, template_w = needle_match_image.shape[:2]
    except Exception:
        return False, None, absolute_image_path
    if template_w <= 0 or template_h <= 0:
        return False, None, absolute_image_path

    confidence = coerce_float((params or {}).get('confidence', 0.8), 0.8)
    use_recognition_region = coerce_bool((params or {}).get('use_recognition_region', False))
    recognition_region = None
    if use_recognition_region:
        region_x = coerce_int((params or {}).get('recognition_region_x', 0), 0)
        region_y = coerce_int((params or {}).get('recognition_region_y', 0), 0)
        region_w = coerce_int((params or {}).get('recognition_region_width', 0), 0)
        region_h = coerce_int((params or {}).get('recognition_region_height', 0), 0)
        if region_w > 0 and region_h > 0:
            recognition_region = (region_x, region_y, region_w, region_h)

    if capture_timeout is None:
        timeout_value = coerce_float((params or {}).get('capture_timeout', 1.2), 1.2)
    else:
        timeout_value = coerce_float(capture_timeout, 1.2)

    match_response = capture_and_match_template_smart(
        target_hwnd=hwnd,
        template=needle_match_image,
        confidence_threshold=float(confidence),
        template_key=str(absolute_image_path),
        capture_timeout=max(0.3, float(timeout_value)),
        roi=recognition_region,
        client_area_only=True,
        use_cache=False,
    )

    if not match_response or not bool(match_response.get("success")):
        return False, None, absolute_image_path

    raw_location = match_response.get("location")
    if not (isinstance(raw_location, (list, tuple)) and len(raw_location) == 4):
        return False, None, absolute_image_path

    try:
        match_score = float(match_response.get("confidence", 0.0) or 0.0)
    except Exception:
        match_score = 0.0

    try:
        match_x = int(raw_location[0])
        match_y = int(raw_location[1])
        match_w = int(raw_location[2])
        match_h = int(raw_location[3])
    except Exception:
        return False, None, absolute_image_path

    if not bool(match_response.get("matched", False)) or match_score < confidence:
        return False, None, absolute_image_path

    screenshot_w = match_response.get("screenshot_width")
    screenshot_h = match_response.get("screenshot_height")
    if screenshot_w is None or screenshot_h is None:
        screenshot_shape = match_response.get("screenshot_shape")
        if isinstance(screenshot_shape, (list, tuple)) and len(screenshot_shape) >= 2:
            try:
                screenshot_h = int(screenshot_shape[0])
                screenshot_w = int(screenshot_shape[1])
            except Exception:
                screenshot_w = 0
                screenshot_h = 0

    if screenshot_w is None:
        screenshot_w = 0
    if screenshot_h is None:
        screenshot_h = 0

    return True, (
        int(match_x),
        int(match_y),
        int(match_w),
        int(match_h),
        int(screenshot_w),
        int(screenshot_h),
    ), absolute_image_path


# Define activation helper function (or assume it's imported from utils)
def _activate_window_foreground(target_hwnd: Optional[int], logger):
    # 工具 修复：简化窗口激活逻辑
    import os
    is_multi_window_mode = os.environ.get('MULTI_WINDOW_MODE') == 'true'

    if is_multi_window_mode:
        logger.debug(f"靶心 多窗口模式：跳过窗口激活，窗口 {target_hwnd}")
        return True  # 在多窗口模式下，不激活窗口但返回成功

    # ... (Activation logic as defined above) ...
    if not target_hwnd or not PYWIN32_AVAILABLE:
        if not target_hwnd:
             logger.debug("前台模式执行，但未提供目标窗口句柄，无法激活。")
        elif not PYWIN32_AVAILABLE:
             logger.warning("无法激活目标窗口：缺少 'pywin32' 库。")
        return False
    try:
        if not win32gui.IsWindow(target_hwnd):
            logger.warning(f"无法激活目标窗口：句柄 {target_hwnd} 无效或已销毁。")
            return False
        current_foreground_hwnd = win32gui.GetForegroundWindow()
        if current_foreground_hwnd == target_hwnd:
            logger.debug(f"目标窗口 {target_hwnd} 已是前台窗口，无需激活。")
            return True
        if win32gui.IsIconic(target_hwnd):
            logger.info(f"目标窗口 {target_hwnd} 已最小化，尝试恢复并激活...")
            win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
            precise_sleep(0.15)
            win32gui.SetForegroundWindow(target_hwnd)
            precise_sleep(0.15)
            logger.info(f"窗口 {target_hwnd} 已尝试恢复并设置为前台。")
        else:
            logger.info(f"尝试将窗口 {target_hwnd} 设置为前台...")
            win32gui.SetForegroundWindow(target_hwnd)
            precise_sleep(0.1)
        return True
    except Exception as e:
        logger.warning(f"设置前台窗口 {target_hwnd} 时出错: {e}。")
        return False


def _is_virtual_mouse_enabled() -> bool:
    return _read_virtual_mouse_enabled()


def _get_virtual_mouse_coords() -> Optional[Tuple[int, int]]:
    return _read_virtual_mouse_coords()

# 任务类型标识
TASK_TYPE = "图片点击" # Get logger instance


def requires_input_lock(_params: Dict[str, Any]) -> bool:
    # 点击阶段已由 click_action_executor 内部统一串行，这里不再整卡占用输入锁。
    return False

def get_params_definition() -> Dict[str, Dict[str, Any]]:
    """Returns the parameter definitions for the Find Image and Click task."""
    from .task_utils import get_standard_next_step_delay_params, get_standard_action_params, merge_params_definitions

    # 原有的图像识别点击参数
    image_click_params = {
        # Pre-condition parameters removed as the core task logic handles image finding
        # --- Task Specific Parameters ---
        "---task_params---": {"type": "separator", "label": "主要任务参数"},
        "image_path": {"label": "目标图片路径", "type": "file", "required": True, "description": "需要查找并点击的图片文件。"},
        "confidence": {
            "label": "查找置信度",
            "type": "float",
            "default": 0.8,
            "min": 0.1,
            "max": 1.0,
            "decimals": 2,
            "tooltip": "图片匹配的相似度阈值 (0.1 到 1.0)。"
        },
        "test_recognition": {
            "label": "测试图片识别",
            "type": "button",
            "button_text": "测试识别",
            "action": "test_image_recognition",
            "tooltip": "点击进行图片识别测试，查看当前参数的识别效果"
        },
        "enable_click": {
            "label": "启用点击",
            "type": "bool",
            "default": True,
            "tooltip": "关闭后仅识别并写入坐标，不执行点击"
        },
        "button": {"label": "鼠标按钮", "type": "select", "options": ["左键", "右键", "中键"], "default": "左键"},
        "click_action": {
            "label": "点击动作",
            "type": "select",
            "options": ["完整点击", "双击", "仅按下", "仅松开"],
            "default": "完整点击",
            "tooltip": "完整点击=按下+松开，双击=连续两次完整点击，仅按下=只按下不松开，仅松开=只松开不按下"
        },
        "enable_auto_release": {
            "label": "启用自动弹起",
            "type": "bool",
            "default": True,
            "tooltip": "启用后，按下鼠标一定时间后自动释放",
            "condition": {"param": "click_action", "value": "仅按下"}
        },
        "hold_duration": {
            "label": "按下持续时间(秒)",
            "type": "float",
            "default": DEFAULT_CLICK_HOLD_SECONDS,
            "min": 0.01,
            "max": 10.0,
            "step": 0.01,
            "decimals": 2,
            "tooltip": "仅在'仅按下'动作且启用自动弹起时，按下后保持的时间",
            "condition": {"param": "click_action", "value": "仅按下"}
        },
        "clicks": {"label": "点击次数", "type": "int", "default": 1, "min": 1},
        "interval": {
            "label": "点击间隔(秒)",
            "type": "float",
            "default": DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
            "min": 0.0,
            "decimals": 2,
        },

        # X and Y are removed as they are determined by the image location

        # --- Retry Mechanism ---
        "---retry---": {"type": "separator", "label": "失败重试设置"},
        "enable_retry": {
            "label": "启用失败重试",
            "type": "bool",
            "default": False,
            "tooltip": "如果查找失败，是否进行重试。"
        },
        "retry_attempts": {
            "label": "最大重试次数",
            "type": "int",
            "default": 3,
            "min": 1,
            "tooltip": "启用重试时，查找失败后最多重试几次。",
            "condition": {"param": "enable_retry", "value": True}
        },
        "retry_interval": {
            "label": "重试间隔(秒)",
            "type": "float",
            "default": 0.5,
            "min": 0.1,
            "decimals": 2,
            "tooltip": "每次重试之间的等待时间。",
            "condition": {"param": "enable_retry", "value": True}
        },

        # --- 点击位置偏移设置 ---
        "---click_offset---": {"type": "separator", "label": "点击位置偏移设置"},
        "offset_selector_tool": {
            "label": "偏移选择",
            "type": "button",
            "button_text": "拖拽选择偏移",
            "tooltip": "从目标点拖拽选择固定偏移距离，会自动切换为固定偏移",
            "widget_hint": "offset_selector",
            "related_params": ["fixed_offset_x", "fixed_offset_y", "image_position_mode"],
        },
        "image_position_mode": {
            "label": "点击位置",
            "type": "select",
            "options": ["精准坐标", "固定偏移", "随机偏移"],
            "default": "精准坐标",
            "tooltip": "精准坐标：使用图片中心精确点击\n固定偏移：先在图片中心基础上添加固定偏移，再可选叠加随机偏移\n随机偏移：在图片中心基础上添加随机偏移"
        },
        "fixed_offset_x": {
            "label": "固定X偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在图片中心位置上增加固定的X偏移（正数向右，负数向左）",
            "condition": {"param": "image_position_mode", "value": "固定偏移"}
        },
        "fixed_offset_y": {
            "label": "固定Y偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在图片中心位置上增加固定的Y偏移（正数向下，负数向上）",
            "condition": {"param": "image_position_mode", "value": "固定偏移"}
        },
        "random_offset_x": {
            "label": "随机X偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "X轴随机偏移范围，实际偏移在 [-X, +X] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {"param": "image_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
        },
        "random_offset_y": {
            "label": "随机Y偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "Y轴随机偏移范围，实际偏移在 [-Y, +Y] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {"param": "image_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
        },

        # --- Post-Execution Actions ---
        "---post_exec---": {"type": "separator", "label": "执行后操作"},
        # Labels updated to reflect overall task success/failure
        "on_success": {"type": "select", "label": "执行成功时", "options": ["继续执行本步骤", "执行下一步", "跳转到步骤", "停止工作流"], "default": "执行下一步"},
        "success_jump_target_id": {"type": "int", "label": "成功跳转目标 ID", "required": False,
                                    "widget_hint": "card_selector",
                                    "condition": {"param": "on_success", "value": "跳转到步骤"}},
        "on_failure": {"type": "select", "label": "执行失败时", "options": ["继续执行本步骤", "执行下一步", "跳转到步骤", "停止工作流"], "default": "执行下一步"},
        "failure_jump_target_id": {"type": "int", "label": "失败跳转目标 ID", "required": False,
                                     "widget_hint": "card_selector",
                                     "condition": {"param": "on_failure", "value": "跳转到步骤"}}
    }

    def _append_enable_click_condition(param_key: str) -> None:
        param_def = image_click_params.get(param_key)
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
        "button",
        "click_action",
        "enable_auto_release",
        "hold_duration",
        "clicks",
        "interval",
        "---click_offset---",
        "offset_selector_tool",
        "image_position_mode",
        "fixed_offset_x",
        "fixed_offset_y",
        "random_offset_x",
        "random_offset_y",
    ):
        _append_enable_click_condition(click_param)

    # 合并所有参数定义
    return merge_params_definitions(
        image_click_params,
        get_standard_next_step_delay_params(),
        get_standard_action_params()
    )

# Modified execute signature to accept execution_mode and target_hwnd
def execute_task(params: Dict[str, Any], counters: Dict[str, int], execution_mode: str, target_hwnd: Optional[int], window_region: Optional[Tuple[int, int, int, int]], card_id: Optional[int], **kwargs) -> Tuple[bool, str, Optional[int]]:
    """Executes the Find Image and Click task in the specified mode."""

    # 检查 OpenCV 是否可用
    if not CV2_AVAILABLE:
        logger.error("OpenCV 或 NumPy 不可用，无法执行图片识别任务")
        logger.error("请安装依赖: pip install opencv-python numpy")
        from .task_utils import handle_failure_action
        return handle_failure_action(params, card_id)

    # 从 kwargs 中获取 get_image_data 函数
    get_image_data = kwargs.get('get_image_data', None)


    # 1. 参数获取与检查
    # window_title now comes from the executor based on MainWindow settings
    raw_image_path = params.get('image_path')

    # 【闪退修复】路径纠正：自动从images目录匹配同名图片
    from tasks.task_utils import correct_single_image_path
    absolute_image_path = correct_single_image_path(raw_image_path, card_id) if raw_image_path else None

    confidence = coerce_float(params.get('confidence', 0.8), 0.8)
    enable_click = coerce_bool(params.get('enable_click', True))
    button_param = params.get('button', '左键')
    click_button, clicks, interval, click_action, enable_auto_release, hold_duration = resolve_click_params(
        params,
        button_key="button",
        clicks_key="clicks",
        interval_key="interval",
        action_key="click_action",
        auto_release_key="enable_auto_release",
        hold_duration_key="hold_duration",
        mode_label="图片点击",
        logger_obj=logger,
        log_hold_mode=False,
    )
    # --- 新增：获取重试参数 ---
    enable_retry = coerce_bool(params.get('enable_retry', False))
    max_attempts = coerce_int(params.get('retry_attempts', 3), 3) if enable_retry else 1 # 如果不启用，只尝试1次
    retry_interval = coerce_float(params.get('retry_interval', 0.5), 0.5)
    stop_checker = kwargs.get('stop_checker', None)
    capture_timeout = coerce_float(params.get('capture_timeout', 1.2), 1.2)
    capture_timeout = max(0.3, float(capture_timeout))

    def _is_stop_requested() -> bool:
        try:
            return bool(stop_checker and stop_checker())
        except Exception:
            return False

    def _wait_with_stop(total_wait: float) -> bool:
        try:
            wait_seconds = max(0.0, float(total_wait))
        except (TypeError, ValueError):
            wait_seconds = 0.0
        if wait_seconds <= 0:
            return True
        elapsed = 0.0
        check_interval = 0.1
        while elapsed < wait_seconds:
            if _is_stop_requested():
                return False
            sleep_time = min(check_interval, wait_seconds - elapsed)
            precise_sleep(sleep_time)
            elapsed += sleep_time
        return not _is_stop_requested()
    # -------------------------
    # --- 新增：获取识别区域参数 ---
    use_recognition_region = coerce_bool(params.get('use_recognition_region', False))
    recognition_region_x = coerce_int(params.get('recognition_region_x', 0), 0)
    recognition_region_y = coerce_int(params.get('recognition_region_y', 0), 0)
    recognition_region_width = coerce_int(params.get('recognition_region_width', 0), 0)
    recognition_region_height = coerce_int(params.get('recognition_region_height', 0), 0)
    # --- 获取点击偏移参数 ---
    image_position_mode = _normalize_image_position_mode(params.get('image_position_mode', '精准坐标'))
    fixed_offset_x = coerce_int(params.get('fixed_offset_x', 0), 0)
    fixed_offset_y = coerce_int(params.get('fixed_offset_y', 0), 0)
    random_offset_x = coerce_int(params.get('random_offset_x', 5), 5)
    random_offset_y = coerce_int(params.get('random_offset_y', 5), 5)

    # 验证识别区域参数
    recognition_region = None
    if use_recognition_region and recognition_region_width > 0 and recognition_region_height > 0:
        recognition_region = (
            recognition_region_x,
            recognition_region_y,
            recognition_region_width,
            recognition_region_height
        )
        logger.info(f"使用识别区域: X={recognition_region_x}, Y={recognition_region_y}, "
                   f"宽度={recognition_region_width}, 高度={recognition_region_height}")
    # -------------------------

    on_success_action = params.get('on_success', '执行下一步')
    success_jump_id = params.get('success_jump_target_id')
    on_failure_action = params.get('on_failure', '执行下一步')
    failure_jump_id = params.get('failure_jump_target_id')
    
    # --- ADDED: Construct absolute path and validate ---
    if not absolute_image_path:
        logger.error("参数错误：图片路径无效或解析失败。")
        success = False
    else:
        try:
            # Construct and normalize the absolute path
            # absolute_image_path = os.path.normpath(os.path.join(images_dir, relative_image_path)) # Remove path construction
            # 只显示图片名称，不显示完整路径
            if absolute_image_path.startswith('memory://'):
                image_name = absolute_image_path.replace('memory://', '')
            else:
                # 确保 os 模块可用
                import os
                image_name = os.path.basename(absolute_image_path)
            logger.info(f"[找图] 使用模板: {image_name} ({absolute_image_path})")
            # Optional: Check existence here, though _resolve_image_paths should have done it
            # if not os.path.exists(absolute_image_path):
            #      logger.error(f"文件未找到: {absolute_image_path}")
            #      success = False
            #      absolute_image_path = None # Ensure it's None if not found
            pass # Assume existence check was done by executor for now
        except Exception as path_e:
            logger.error(f"验证绝对图片路径时出错: {path_e}", exc_info=True)
            # success = False # No need to set success here, path check below handles it
            absolute_image_path = None
            
    # If path resolution failed (absolute_image_path is None), determine failure action immediately
    if absolute_image_path is None:
        logger.debug("图片路径无效，执行失败操作。")
        # 使用统一的失败处理
        from .task_utils import handle_failure_action
        return handle_failure_action(params, card_id)
    # --- END PATH CONSTRUCTION ---

    # ===== 插件系统集成 =====
    # 【关键修复】只有在execution_mode为plugin_mode时才使用插件系统
    # 这样确保插件模式和原有模式（包括MuMu模拟器模式）严格隔离
    try:
        from app_core.plugin_bridge import is_plugin_enabled, plugin_find_pic
        if _is_stop_requested():
            logger.warning("[停止请求] 图片点击任务开始前检测到停止请求，立即终止")
            return False, '停止工作流', None

        # 检查两个条件：1) 插件系统已启用 2) execution_mode明确指定为plugin_mode
        if is_plugin_enabled() and str(execution_mode or '').strip().lower().startswith('plugin'):
            logger.info("[插件模式] 使用插件系统进行找图和点击")

            # 获取窗口客户区尺寸作为识别基准区域
            if not target_hwnd or not PYWIN32_AVAILABLE:
                logger.error("[插件模式] 需要有效的窗口句柄")
                from .task_utils import handle_failure_action
                return handle_failure_action(params, card_id)

            # 验证窗口句柄是否有效
            if not win32gui.IsWindow(target_hwnd):
                logger.error(f"[插件模式] 目标窗口{target_hwnd}无效或已关闭")
                from .task_utils import handle_failure_action
                return handle_failure_action(params, card_id)

            # [修复] 插件模式不激活窗口，由插件自行处理后台截图
            # OLA插件的后台绑定模式可以在不激活窗口的情况下进行截图和操作
            logger.debug("[插件模式] 使用后台模式，不激活目标窗口")

            # 获取客户区尺寸
            client_rect = win32gui.GetClientRect(target_hwnd)
            client_w = client_rect[2] - client_rect[0]
            client_h = client_rect[3] - client_rect[1]

            # 确定识别区域
            if recognition_region:
                search_x1, search_y1 = recognition_region[0], recognition_region[1]
                search_x2 = search_x1 + recognition_region[2]
                search_y2 = search_y1 + recognition_region[3]
                logger.info(f"[插件找图] 使用识别区域: ({search_x1}, {search_y1}) 到 ({search_x2}, {search_y2})")
            else:
                search_x1, search_y1 = 0, 0
                search_x2, search_y2 = client_w, client_h
                logger.info(f"[插件找图] 使用全窗口区域: ({search_x1}, {search_y1}) 到 ({search_x2}, {search_y2})")

            # 执行找图（带重试）
            found_location = None
            for attempt in range(1, max_attempts + 1):
                if attempt > 1:
                    logger.info(f"[插件找图] 第{attempt}次尝试...")
                    if not _wait_with_stop(retry_interval):
                        logger.warning("[停止请求] 插件找图重试等待中检测到停止请求，立即终止")
                        return False, '停止工作流', None

                # 调用插件找图
                found_location = plugin_find_pic(
                    hwnd=target_hwnd,
                    x1=search_x1,
                    y1=search_y1,
                    x2=search_x2,
                    y2=search_y2,
                    pic_name=absolute_image_path,
                    similarity=confidence
                )

                if found_location:
                    logger.info(f"[插件找图] 第{attempt}次尝试成功，OLA返回坐标: {found_location}")
                    # 添加坐标合理性检查
                    loc_x, loc_y = found_location
                    if loc_x < 0 or loc_y < 0 or loc_x >= client_w or loc_y >= client_h:
                        logger.warning(f"[插件找图] 警告：坐标可能异常! OLA返回({loc_x}, {loc_y})，窗口客户区尺寸: {client_w}x{client_h}")
                    break

            if not found_location:
                logger.warning("[插件找图] 未找到目标图片")
                from .task_utils import handle_failure_action
                return handle_failure_action(params, card_id)

            # OLA返回的坐标是匹配区域的左上角，需要加上图片尺寸的一半才是中心点
            # 读取图片尺寸
            template_w = 0
            template_h = 0
            try:
                # cv2 和 numpy 已在文件顶部导入，无需重复导入
                img_np = np.fromfile(absolute_image_path, dtype=np.uint8)
                template_img = cv2.imdecode(img_np, cv2.IMREAD_UNCHANGED)
                if template_img is not None:
                    template_h, template_w = template_img.shape[:2]
                    center_offset_x = template_w // 2
                    center_offset_y = template_h // 2
                    logger.debug(f"[插件找图] 图片尺寸: {template_w}x{template_h}, 中心偏移: ({center_offset_x}, {center_offset_y})")
                else:
                    logger.warning("[插件找图] 无法加载图片获取尺寸，使用原始坐标")
                    center_offset_x = center_offset_y = 0
            except Exception as e:
                logger.warning(f"[插件找图] 获取图片尺寸失败: {e}，使用原始坐标")
                center_offset_x = center_offset_y = 0

            # 计算点击坐标（从左上角转换为中心点）
            click_x, click_y = found_location
            click_x += center_offset_x
            click_y += center_offset_y
            logger.info(f"[插件点击] 匹配位置(左上角): {found_location}, 中心点: ({click_x}, {click_y})")

            # 根据点击位置模式决定是否应用偏移（与原有模式保持一致）
            if image_position_mode == '精准坐标':
                # 精准坐标：不应用任何偏移
                logger.info(f"[插件点击] 精准坐标模式，不应用偏移")
            elif image_position_mode == '固定偏移':
                # 固定偏移：先应用固定偏移，再在偏移后的坐标上叠加随机偏移
                if fixed_offset_x != 0 or fixed_offset_y != 0:
                    click_x += fixed_offset_x
                    click_y += fixed_offset_y
                    logger.info(f"[插件点击] 固定偏移模式: ({fixed_offset_x}, {fixed_offset_y})")
                if random_offset_x > 0 or random_offset_y > 0:
                    offset_x = random.randint(-random_offset_x, random_offset_x) if random_offset_x > 0 else 0
                    offset_y = random.randint(-random_offset_y, random_offset_y) if random_offset_y > 0 else 0
                    click_x += offset_x
                    click_y += offset_y
                    logger.info(f"[插件点击] 固定偏移后叠加随机偏移: ({offset_x}, {offset_y})")
            else:
                # 随机偏移（默认）
                if random_offset_x > 0 or random_offset_y > 0:
                    offset_x = random.randint(-random_offset_x, random_offset_x) if random_offset_x > 0 else 0
                    offset_y = random.randint(-random_offset_y, random_offset_y) if random_offset_y > 0 else 0
                    click_x += offset_x
                    click_y += offset_y
                    logger.info(f"[插件点击] 随机偏移模式: ({offset_x}, {offset_y})")

            virtual_mouse_enabled = _is_virtual_mouse_enabled()
            if virtual_mouse_enabled:
                virtual_coords = _get_virtual_mouse_coords()
                if virtual_coords:
                    logger.info(
                        "[插件点击] 虚拟鼠标当前位置: (%s, %s)，将移动到目标坐标后点击",
                        virtual_coords[0],
                        virtual_coords[1],
                    )
                else:
                    logger.warning("[插件点击] 虚拟鼠标已启用，但未获取到当前位置，将直接按目标坐标执行")

            logger.info(f"[插件点击] 最终点击坐标: ({click_x}, {click_y})")

            if card_id is not None:
                try:
                    from task_workflow.workflow_context import get_workflow_context
                    context = get_workflow_context()
                    base_center_x = found_location[0] + center_offset_x
                    base_center_y = found_location[1] + center_offset_y
                    offset_dx = click_x - base_center_x
                    offset_dy = click_y - base_center_y
                    bbox_x1 = bbox_y1 = bbox_x2 = bbox_y2 = None
                    if template_w > 0 and template_h > 0:
                        bbox_x1 = int(found_location[0] + offset_dx)
                        bbox_y1 = int(found_location[1] + offset_dy)
                        bbox_x2 = int(found_location[0] + template_w - 1 + offset_dx)
                        bbox_y2 = int(found_location[1] + template_h - 1 + offset_dy)
                    context.set_card_data(card_id, "image_target_x", int(click_x))
                    context.set_card_data(card_id, "image_target_y", int(click_y))
                    context.set_card_data(card_id, "image_target_x1", bbox_x1)
                    context.set_card_data(card_id, "image_target_y1", bbox_y1)
                    context.set_card_data(card_id, "image_target_x2", bbox_x2)
                    context.set_card_data(card_id, "image_target_y2", bbox_y2)
                except Exception as exc:
                    logger.debug("[插件找图] 保存坐标失败: %s", exc)

            if not enable_click:
                logger.info("[插件点击] 仅识别模式，跳过点击")
                from .task_utils import handle_success_action
                return handle_success_action(params, card_id, kwargs.get('stop_checker'))

            logger.info(f"[插件点击] 动作: {click_action}, 按钮: {click_button}, 次数: {clicks}")

            # 【关键修复】在同一绑定周期内执行点击，避免重复绑定导致坐标问题
            # 直接使用plugin_bridge获取已绑定的插件进行点击
            click_success = False
            try:
                from app_core.plugin_bridge import get_plugin_manager, get_cached_config
                from plugins.core.interface import PluginCapability

                pm = get_plugin_manager()
                if not pm or not pm.is_enabled():
                    logger.error("[插件点击] 插件管理器不可用")
                    from .task_utils import handle_failure_action
                    return handle_failure_action(params, card_id)

                # 获取插件
                plugin = pm.get_preferred_plugin(PluginCapability.MOUSE_CLICK)
                if not plugin:
                    logger.error("[插件点击] 无法获取鼠标点击插件")
                    from .task_utils import handle_failure_action
                    return handle_failure_action(params, card_id)

                # 读取OLA绑定参数
                config = get_cached_config()
                bind_args = get_plugin_bind_args(config, hwnd=target_hwnd)
                mouse_move_with_trajectory = bind_args['mouse_move_with_trajectory']

                if not plugin.bind_window(
                    target_hwnd,
                    bind_args['display_mode'],
                    bind_args['mouse_mode'],
                    bind_args['keypad_mode'],
                    bind_args['bind_mode'],
                    input_lock=bind_args['input_lock'],
                    mouse_move_with_trajectory=bind_args['mouse_move_with_trajectory'],
                    pubstr=bind_args['pubstr'],
                ):
                    logger.error(f"[插件点击] 绑定窗口失败: {target_hwnd}")
                    from .task_utils import handle_failure_action
                    return handle_failure_action(params, card_id)

                # 在同一绑定周期内执行点击（OLA坐标是客户区坐标，直接使用）
                plugin_adapter = PluginSimulatorAdapter(
                    plugin=plugin,
                    plugin_capability=PluginCapability,
                    mouse_move_with_trajectory=mouse_move_with_trajectory,
                    hwnd=target_hwnd,
                )
                if click_action == '仅按下' and not enable_auto_release:
                    logger.info("[插件点击] 鼠标按下不自动释放")

                click_success = execute_simulator_click_action(
                    simulator=plugin_adapter,
                    x=click_x,
                    y=click_y,
                    button=click_button,
                    click_action=click_action,
                    clicks=clicks,
                    interval=interval,
                    hold_duration=hold_duration,
                    auto_release=enable_auto_release,
                    mode_label="插件点击",
                    logger_obj=logger,
                    single_click_retry=False,
                    require_atomic_hold=False,
                    move_before_click=virtual_mouse_enabled,
                    stop_checker=stop_checker,
                    execution_mode=execution_mode,
                    target_hwnd=target_hwnd,
                    task_type=TASK_TYPE,
                )
                if not click_success:
                    logger.error(f"[插件点击] 点击失败")

            except Exception as e:
                logger.error(f"[插件点击] 执行点击失败: {e}", exc_info=True)
                click_success = False

            if click_success:
                if virtual_mouse_enabled:
                    sync_virtual_mouse_position(int(click_x), int(click_y), persist_global=False)
                logger.info(f"[插件点击] 点击成功（{clicks}次）")
                from .task_utils import handle_success_action
                return handle_success_action(params, card_id)
            else:
                logger.error("[插件点击] 点击失败")
                from .task_utils import handle_failure_action
                return handle_failure_action(params, card_id)

    except ImportError:
        logger.error("插件系统不可用，请检查插件配置")
        from .task_utils import handle_failure_action
        return handle_failure_action(params, card_id)
    except Exception as e:
        logger.error(f"插件系统执行失败: {e}", exc_info=True)
        from .task_utils import handle_failure_action
        return handle_failure_action(params, card_id)
    # ===== 插件系统集成结束 =====



    # 2. 查找并点击逻辑
    found = False
    location = None
    click_success = False
    needle_image_processed = None  # 初始化变量以避免 UnboundLocalError
    needle_match_image = None

    # 【新增】初始化所有需要清理的图片变量
    needle_image_raw = None
    screenshot_img = None
    haystack_processed = None
    result_matrix = None
    match_result = None
    template_h = 0
    template_w = 0

    # 固定使用绑定窗口搜索
    # 【优化】在找图开始前清除WGC缓存，确保获取新帧
    # 只清除缓存，不销毁捕获器，避免频繁重建开销
    try:
        from utils.screenshot_helper import clear_screenshot_cache
        clear_screenshot_cache(target_hwnd)
        logger.debug(f"[找图] 已清除窗口 {target_hwnd} 的帧缓存")
    except Exception as e:
        logger.debug(f"[找图] 清除帧缓存失败: {e}")

    # 绑定窗口搜索阶段
    for attempt in range(1, max_attempts + 1):
        if _is_stop_requested():
            logger.warning("[停止请求] 找图尝试前检测到停止请求，立即终止")
            return False, '停止工作流', None
        # 只显示图片名称，不显示路径前缀
        if absolute_image_path.startswith('memory://'):
            image_name = absolute_image_path.replace('memory://', '')
        else:
            # 确保 os 模块可用
            import os
            image_name = os.path.basename(absolute_image_path)
        # 执行模式中文映射
        mode_names = {
            'foreground_driver': '\u524d\u53f0\u4e00',
            'foreground_py': '\u524d\u53f0\u4e8c',
            'background_sendmessage': '\u540e\u53f0\u4e00',
            'background_postmessage': '\u540e\u53f0\u4e8c',
            'foreground': '\u524d\u53f0',
            'background': '\u540e\u53f0',
        }
        mode_name = mode_names.get((execution_mode or '').strip().lower(), execution_mode or '\u672a\u77e5')
        logger.info(f"[{mode_name}] 第 {attempt}/{max_attempts} 次尝试查找图片: '{image_name}'")

        # 每次循环开始时重置匹配结果，防止复用上一次的结果
        match_score = 0.0
        match_location_tl = (0, 0)
        try:
            if needle_image_processed is None or needle_match_image is None:
                # --- Load Needle Image (using absolute path) ---
                logger.debug(f"加载模板图片: {absolute_image_path}")

                # --- MODIFIED: Support both memory and file modes ---
                needle_image_raw = None

                # 【性能优化】优先从模板缓存加载
                needle_image_raw = None
                try:
                    from utils.template_preloader import get_global_preloader
                    preloader = get_global_preloader()
                    needle_image_raw = preloader.get_template(absolute_image_path)
                    if needle_image_raw is not None:
                        import os
                        image_name = absolute_image_path.replace('memory://', '') if absolute_image_path.startswith('memory://') else os.path.basename(absolute_image_path)
                        logger.debug(f"[性能优化] 使用缓存的模板: '{image_name}'")
                except Exception as e:
                    logger.debug(f"[性能优化] 模板缓存读取失败: {e}")

                # 如果缓存未命中，正常加载
                if needle_image_raw is None:
                    if absolute_image_path.startswith('memory://'):
                        # 纯内存模式：使用 get_image_data 获取图片数据
                        if get_image_data is None:
                            # 确保 os 模块可用
                            import os
                            image_name = absolute_image_path.replace('memory://', '') if absolute_image_path.startswith('memory://') else os.path.basename(absolute_image_path)
                            logger.error(f"缺少 get_image_data 函数: '{image_name}'")
                            found = False; location = None; click_success = False
                            break

                        try:
                            # 获取图片数据
                            image_data = get_image_data(absolute_image_path)
                            if not image_data:
                                # 确保 os 模块可用
                                import os
                                image_name = absolute_image_path.replace('memory://', '') if absolute_image_path.startswith('memory://') else os.path.basename(absolute_image_path)
                                logger.error(f"无法从内存获取图片数据: '{image_name}'")
                                found = False; location = None; click_success = False
                                break

                            # 使用 cv2.imdecode 从内存数据解码图片
                            image_array = np.frombuffer(image_data, dtype=np.uint8)
                            # 验证数组有效性
                            if image_array is None or len(image_array) == 0:
                                import os
                                image_name = absolute_image_path.replace('memory://', '') if absolute_image_path.startswith('memory://') else os.path.basename(absolute_image_path)
                                logger.error(f"图片数据数组无效或为空: '{image_name}'")
                                found = False; location = None; click_success = False
                                break
                            needle_image_raw = cv2.imdecode(image_array, cv2.IMREAD_UNCHANGED)
                            # 确保 os 模块可用
                            import os
                            image_name = absolute_image_path.replace('memory://', '') if absolute_image_path.startswith('memory://') else os.path.basename(absolute_image_path)
                            logger.debug(f"成功 图片加载成功: '{image_name}'")

                        except Exception as e:
                            # 确保 os 模块可用
                            import os
                            image_name = absolute_image_path.replace('memory://', '') if absolute_image_path.startswith('memory://') else os.path.basename(absolute_image_path)
                            logger.error(f"图片加载失败: '{image_name}', 错误: {e}")
                            found = False; location = None; click_success = False
                            break
                    else:
                        # 传统文件模式：使用 np.fromfile 读取文件（用于编辑器）
                        try:
                            file_array = np.fromfile(absolute_image_path, dtype=np.uint8)
                            # 验证文件数组有效性
                            if file_array is None or len(file_array) == 0:
                                import os
                                image_name = os.path.basename(absolute_image_path)
                                logger.error(f"文件数据数组无效或为空: '{image_name}'")
                                found = False; location = None; click_success = False
                                break
                            needle_image_raw = cv2.imdecode(file_array, cv2.IMREAD_UNCHANGED)
                            # 只显示图片名称，不显示完整路径
                            # 确保 os 模块可用
                            import os
                            image_name = os.path.basename(absolute_image_path)
                            logger.debug(f"从文件加载图片成功: '{image_name}'")
                        except Exception as e:
                            # 只显示图片名称，不显示完整路径
                            # 确保 os 模块可用
                            import os
                            image_name = os.path.basename(absolute_image_path)
                            logger.error(f"从文件加载图片失败: '{image_name}', 错误: {e}")
                            found = False; location = None; click_success = False
                            break

                if needle_image_raw is None:
                    logger.error(f"无法加载模板图片: '{absolute_image_path}'")
                    found = False; location = None; click_success = False
                    break # Exit retry loop if image can't be loaded

                # --- 处理模板图片格式 ---
                needle_image_processed = normalize_match_image(needle_image_raw)

                if needle_image_processed is None:
                     logger.error(f"模板图片 '{absolute_image_path}' 规范化失败。")
                     found = False; location = None; click_success = False
                     break

                template_h, template_w = needle_image_processed.shape[:2]
                if template_h <= 0 or template_w <= 0:
                    logger.error(f"无效的模板图片尺寸: {template_w}x{template_h} ('{absolute_image_path}')") # Log absolute path
                    found = False; location = None; click_success = False
                    break # Exit retry loop for invalid template size

                needle_match_image = needle_image_processed

            # 注释：不再需要DPI缩放
            # 1. 截图工具保存时已归一化为100% DPI (逻辑像素)
            # 2. WGC截图也会自动归一化为100% DPI (逻辑像素)
            # 3. 模板和截图尺寸自然匹配，无需缩放

            # --- 工具 统一使用后台识别方法 ---
            # 不再区分前台后台模式，统一使用后台识别方法以提高稳定性和准确性
            logger.debug("统一使用后台识别方法 (Win32 API + OpenCV)")
            if True:  # 原来的前台和后台模式都使用后台识别方法
                if not PYWIN32_AVAILABLE or not target_hwnd:
                    logger.error("统一后台识别方法需要 pywin32 库和有效的窗口句柄。")
                    found = False; location = None
                    break # Cannot proceed

            # 统一走本地截图引擎执行“截图+匹配”，主进程只接收匹配结果，避免整帧回传和主进程大数组复制。
            logger.debug(f"使用后台截图匹配(本地引擎): HWND={target_hwnd}")
            if _is_stop_requested():
                logger.warning("[停止请求] 本地引擎匹配前检测到停止请求，立即终止")
                return False, '停止工作流', None

            roi_param = None
            if recognition_region is not None:
                try:
                    rx, ry, rw, rh = recognition_region
                    rx = int(rx)
                    ry = int(ry)
                    rw = int(rw)
                    rh = int(rh)
                    if rw > 0 and rh > 0:
                        roi_param = (rx, ry, rw, rh)
                except Exception:
                    roi_param = None

            match_response = capture_and_match_template_smart(
                target_hwnd=target_hwnd,
                template=needle_match_image,
                confidence_threshold=float(confidence),
                template_key=(str(absolute_image_path) if absolute_image_path else None),
                capture_timeout=max(0.3, float(capture_timeout)),
                roi=roi_param,
                client_area_only=True,
                use_cache=False,
            )

            if _is_stop_requested():
                logger.warning("[停止请求] 本地引擎匹配后检测到停止请求，立即终止")
                return False, '停止工作流', None

            if not match_response or not bool(match_response.get("success")):
                if isinstance(match_response, dict):
                    err_msg = str(match_response.get("error") or "unknown_error")
                else:
                    err_msg = "unknown_error"
                logger.error(f"[统一后台识别] 本地引擎截图匹配失败: {err_msg}")
            else:
                try:
                    match_score = float(match_response.get("confidence", 0.0) or 0.0)
                except Exception:
                    match_score = 0.0
                logger.info(f"[模板匹配] 分数: {match_score:.4f}, 阈值: {confidence:.4f}, 方法: local_engine")

                parsed_location = None
                raw_location = match_response.get("location")
                if isinstance(raw_location, (list, tuple)) and len(raw_location) == 4:
                    try:
                        parsed_location = (
                            int(raw_location[0]),
                            int(raw_location[1]),
                            int(raw_location[2]),
                            int(raw_location[3]),
                        )
                    except Exception:
                        parsed_location = None

                screenshot_w = match_response.get("screenshot_width")
                screenshot_h = match_response.get("screenshot_height")
                if screenshot_w is None or screenshot_h is None:
                    screenshot_shape = match_response.get("screenshot_shape")
                    if isinstance(screenshot_shape, (list, tuple)) and len(screenshot_shape) >= 2:
                        try:
                            screenshot_h = int(screenshot_shape[0])
                            screenshot_w = int(screenshot_shape[1])
                        except Exception:
                            screenshot_h = None
                            screenshot_w = None

                if bool(match_response.get("matched", False)) and parsed_location is not None and match_score >= confidence:
                    found = True
                    match_x, match_y, match_w, match_h = parsed_location
                    if match_w > 0 and match_h > 0:
                        template_w = int(match_w)
                        template_h = int(match_h)
                    if screenshot_w is None:
                        screenshot_w = 0
                    if screenshot_h is None:
                        screenshot_h = 0

                    location = (
                        int(match_x),
                        int(match_y),
                        int(template_w),
                        int(template_h),
                        int(screenshot_w),
                        int(screenshot_h),
                    )
                    center_x = int(match_x) + int(template_w) // 2
                    center_y = int(match_y) + int(template_h) // 2
                    logger.info(f"[统一后台识别] 尝试 {attempt}: 图片找到! "
                                f"客户区坐标 (左上角): ({match_x}, {match_y}), "
                                f"中心点: ({center_x}, {center_y}), "
                                f"截图尺寸: {screenshot_w}x{screenshot_h}")
                    break
                else:
                    logger.info(
                        f"[统一后台识别] 尝试 {attempt}: 未找到图片 "
                        f"(置信度 {match_score:.4f} < 阈值 {confidence:.4f})。"
                    )

        except Exception as find_err:
            # 显示错误详细信息
            # 只显示图片名称，不显示路径前缀
            if absolute_image_path.startswith('memory://'):
                image_name = absolute_image_path.replace('memory://', '')
            else:
                # 确保 os 模块可用
                import os
                image_name = os.path.basename(absolute_image_path)
            mode_name = mode_names.get(execution_mode, execution_mode)
            logger.error(f"[{mode_name}] 第 {attempt} 次尝试查找图片 '{image_name}' 时发生意外错误: {find_err}", exc_info=True)
            found = False # Ensure found is False on error
        finally:
            # 每轮重试结束立即释放大对象引用，避免在长重试链路中累积驻留内存
            screenshot_img = None
            haystack_processed = None
            result_matrix = None
            match_result = None

        # If not found and more attempts remain, wait
        if not found and attempt < max_attempts:
            # 【修复】清理WGC捕获器，确保下次重试使用新帧
            try:
                from utils.screenshot_helper import clear_screenshot_cache
                clear_screenshot_cache(target_hwnd)
                logger.debug(f"[找图重试] 已清除窗口 {target_hwnd} 的帧缓存")
            except Exception as e:
                logger.debug(f"[找图重试] 清除帧缓存失败: {e}")

            # 【关键修复】在等待重试前检查停止请求
            stop_checker = kwargs.get('stop_checker')
            if stop_checker and stop_checker():
                logger.warning(f"[停止请求] 找图重试等待前检测到停止请求，立即终止")
                return False, '停止工作流', None

            logger.debug(f"等待 {retry_interval} 秒后重试...")

            # 【关键修复】将长时间 sleep 拆分为多个短 sleep，每个都检查停止
            total_wait = retry_interval
            check_interval = 0.1  # 每100ms检查一次停止信号
            elapsed = 0

            while elapsed < total_wait:
                precise_sleep(min(check_interval, total_wait - elapsed))
                elapsed += check_interval

                # 每次短暂 sleep 后都检查停止请求
                if stop_checker and stop_checker():
                    logger.warning(f"[停止请求] 找图重试等待中检测到停止请求，立即终止")
                    return False, '停止工作流', None

    # --- End Retry Loop ---

    # 固定使用绑定窗口搜索

    # --- Perform Click Action if Found ---
    if found and location:
        click_success = not enable_click

        # 解析location元组
        if len(location) >= 6:
            # 新格式: (x, y, width, height, screenshot_w, screenshot_h)
            left_x, top_y, template_w, template_h, screenshot_width, screenshot_height = location[:6]
        else:
            # 旧格式兼容: (x, y, width, height)
            left_x, top_y, template_w, template_h = location[:4]
            screenshot_width = None
            screenshot_height = None

        # 【关键修复】简化坐标计算，与文字点击保持一致
        # WGC截图返回的坐标直接作为客户区坐标使用
        logger.info(f"=== 坐标转换开始 ===")
        logger.info(f"  识别到的位置(截图坐标): ({left_x}, {top_y}) [{template_w}x{template_h}]")

        # 直接计算中心点（识别到的坐标就是客户区坐标）
        center_x = left_x + template_w // 2
        center_y = top_y + template_h // 2

        logger.info(f"  中心点(客户区坐标): ({center_x}, {center_y})")

        # 根据点击位置模式决定是否应用偏移
        # 初始化偏移范围变量（用于日志记录）
        actual_range_x = 0
        actual_range_y = 0
        offset_x = 0
        offset_y = 0

        if image_position_mode == '精准坐标':
            # 精准坐标：直接使用中心点，不应用任何偏移
            click_x = center_x
            click_y = center_y
            logger.info(f"  [精准坐标模式] 使用中心点，无偏移")
        elif image_position_mode == '固定偏移':
            # 固定偏移：先应用固定偏移，再在偏移后的坐标上叠加随机偏移
            click_x = center_x + fixed_offset_x
            click_y = center_y + fixed_offset_y
            offset_x = fixed_offset_x
            offset_y = fixed_offset_y
            logger.info(f"  [固定偏移模式] 固定偏移: ({fixed_offset_x}, {fixed_offset_y})")
            if random_offset_x > 0 or random_offset_y > 0:
                extra_offset_x = random.randint(-max(0, int(random_offset_x)), max(0, int(random_offset_x))) if random_offset_x > 0 else 0
                extra_offset_y = random.randint(-max(0, int(random_offset_y)), max(0, int(random_offset_y))) if random_offset_y > 0 else 0
                click_x += extra_offset_x
                click_y += extra_offset_y
                offset_x += extra_offset_x
                offset_y += extra_offset_y
                logger.info(
                    f"  [固定偏移模式] 叠加随机偏移: ({extra_offset_x}, {extra_offset_y}) "
                    f"[范围: ±{max(0, int(random_offset_x))}, ±{max(0, int(random_offset_y))}]"
                )
        else:
            # 随机偏移：使用参数面板配置范围，并限制在目标模板半径内。
            max_abs_offset_x = max(0, template_w // 2)
            max_abs_offset_y = max(0, template_h // 2)
            actual_range_x = min(max(0, int(random_offset_x)), max_abs_offset_x)
            actual_range_y = min(max(0, int(random_offset_y)), max_abs_offset_y)
            offset_x = random.randint(-actual_range_x, actual_range_x) if actual_range_x > 0 else 0
            offset_y = random.randint(-actual_range_y, actual_range_y) if actual_range_y > 0 else 0
            click_x = center_x + offset_x
            click_y = center_y + offset_y
            logger.info(f"  [随机偏移模式] 偏移: ({offset_x}, {offset_y}) [范围: ±{actual_range_x}, ±{actual_range_y}]")

        virtual_mouse_enabled = _is_virtual_mouse_enabled()
        if virtual_mouse_enabled:
            virtual_coords = _get_virtual_mouse_coords()
            if virtual_coords:
                logger.info(
                    "  虚拟鼠标当前位置: (%s, %s)，将移动到目标坐标后点击",
                    virtual_coords[0],
                    virtual_coords[1],
                )
            else:
                logger.warning("  虚拟鼠标已启用，但未获取到当前位置，将直接按目标坐标执行")

        logger.info(f"  最终点击位置(客户区坐标): ({click_x}, {click_y})")
        logger.info(f"=== 坐标转换结束 ===")

        if card_id is not None:
            try:
                from task_workflow.workflow_context import get_workflow_context
                context = get_workflow_context()
                bbox_x1 = bbox_y1 = bbox_x2 = bbox_y2 = None
                if template_w > 0 and template_h > 0:
                    bbox_x1 = int(left_x + offset_x)
                    bbox_y1 = int(top_y + offset_y)
                    bbox_x2 = int(left_x + template_w - 1 + offset_x)
                    bbox_y2 = int(top_y + template_h - 1 + offset_y)
                context.set_card_data(card_id, "image_target_x", int(click_x))
                context.set_card_data(card_id, "image_target_y", int(click_y))
                context.set_card_data(card_id, "image_target_x1", bbox_x1)
                context.set_card_data(card_id, "image_target_y1", bbox_y1)
                context.set_card_data(card_id, "image_target_x2", bbox_x2)
                context.set_card_data(card_id, "image_target_y2", bbox_y2)
            except Exception as exc:
                logger.debug("[找图点击] 保存坐标失败: %s", exc)

        # click_x和click_y是客户区坐标，可以直接用于各种点击模式
        dpi_adjusted_click_x = click_x
        dpi_adjusted_click_y = click_y

        # 添加详细的点击位置诊断
        _diagnose_click_position(target_hwnd, left_x, top_y, center_x, center_y, dpi_adjusted_click_x, dpi_adjusted_click_y, template_w, template_h)

        effective_execution_mode = execution_mode
        if virtual_mouse_enabled:
            logger.info(f"[虚拟鼠标] 已启用，保持执行模式: {effective_execution_mode}")

        # 判断执行模式类型
        is_background_click_mode = effective_execution_mode.startswith('background')
        is_foreground_click_mode = effective_execution_mode.startswith('foreground')

        if not enable_click:
            logger.info("[找图点击] 仅识别模式，跳过点击")
        elif is_foreground_click_mode:
            # 前台模式：将客户区坐标转换为屏幕坐标
            logger.info(f"[前台点击] 客户区坐标: ({dpi_adjusted_click_x}, {dpi_adjusted_click_y})")

            try:
                # 验证窗口句柄是否有效
                if not PYWIN32_AVAILABLE:
                    logger.error("[前台点击] pywin32库不可用")
                    click_success = False
                elif not target_hwnd:
                    logger.error("[前台点击] 目标窗口句柄无效")
                    click_success = False
                elif not win32gui.IsWindow(target_hwnd):
                    logger.error(f"[前台点击] 目标窗口{target_hwnd}无效或已关闭")
                    click_success = False
                else:
                    from ctypes import wintypes
                    import ctypes

                    # 使用ClientToScreen转换客户区坐标为屏幕坐标
                    point = wintypes.POINT(int(dpi_adjusted_click_x), int(dpi_adjusted_click_y))
                    user32 = ctypes.WinDLL("user32", use_last_error=True)
                    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
                    user32.ClientToScreen.restype = wintypes.BOOL
                    result = user32.ClientToScreen(wintypes.HWND(target_hwnd), ctypes.byref(point))

                    if result:
                        screen_click_x, screen_click_y = point.x, point.y
                        logger.info(f"[前台点击] 坐标转换: 客户区({dpi_adjusted_click_x}, {dpi_adjusted_click_y}) -> 屏幕({screen_click_x}, {screen_click_y})")
                    else:
                        logger.error("[前台点击] ClientToScreen转换失败，终止本次点击以避免非客户区偏移")
                        raise RuntimeError("ClientToScreen转换失败")

                    # 工具 修复：简化窗口激活逻辑
                    import os
                    is_multi_window_mode = os.environ.get('MULTI_WINDOW_MODE') == 'true'

                    # 只在前台模式且非多窗口模式下激活窗口
                    should_activate = (effective_execution_mode.startswith('foreground') and not is_multi_window_mode)

                    if should_activate:
                        # 严格模式：点击阶段不再做窗口激活，避免插入额外系统动作。
                        logger.info("[前台点击] 严格模式：跳过点击前窗口激活")
                    else:
                        reason = "多窗口模式" if is_multi_window_mode else "非前台模式"
                        logger.info(f"靶心 [{reason}] 跳过窗口激活，直接在窗口 {target_hwnd} 中点击")

                    logger.info(f"[前台点击] 执行点击: 屏幕坐标({screen_click_x}, {screen_click_y}), 按钮={button_param}, 动作={click_action}, 次数={clicks}")

                    from utils.input_simulation import global_input_simulator_manager

                    input_sim = global_input_simulator_manager.get_simulator(
                        hwnd=target_hwnd,
                        execution_mode=effective_execution_mode,
                    )
                    if input_sim is None:
                        logger.error(f"[前台点击] 获取输入模拟器失败: hwnd={target_hwnd}, mode={effective_execution_mode}")
                        click_success = False
                    else:
                        logger.info(f"[前台模式] 执行点击操作，动作={click_action}")
                        if click_action == '仅按下' and not enable_auto_release:
                            logger.info("[前台模式] 鼠标按下不自动释放")

                        click_success = execute_simulator_click_action(
                            simulator=input_sim,
                            x=screen_click_x,
                            y=screen_click_y,
                            button=click_button,
                            click_action=click_action,
                            clicks=clicks,
                            interval=interval,
                            hold_duration=hold_duration,
                            auto_release=enable_auto_release,
                            mode_label="前台模式",
                            logger_obj=logger,
                            single_click_retry=True,
                            require_atomic_hold=True,
                            move_before_click=virtual_mouse_enabled,
                            stop_checker=stop_checker,
                            execution_mode=effective_execution_mode,
                            target_hwnd=target_hwnd,
                            task_type=TASK_TYPE,
                        )

                        if click_success:
                            logger.info("[前台点击] 点击操作完成")

            except Exception as click_err:
                logger.error(f"[前台点击] 点击操作时发生错误: {click_err}", exc_info=True)
                click_success = False

        elif is_background_click_mode:
            # 后台模式：使用后台点击
            logger.info(f"[后台点击] 模板尺寸: {template_w}x{template_h}, 动态偏移范围: [+/-{actual_range_x}, +/-{actual_range_y}]")
            logger.info(f"[后台点击] 计算中心点: ({center_x}, {center_y}), 应用偏移: ({offset_x},{offset_y}), DPI调整后点击坐标: ({dpi_adjusted_click_x}, {dpi_adjusted_click_y}), 按钮={button_param}, 动作={click_action}, 次数={clicks}")
            logger.info(f"[后台点击] 执行模式: {effective_execution_mode}")
            try:
                # 验证窗口句柄是否有效
                if not PYWIN32_AVAILABLE:
                    logger.error("[后台点击] pywin32库不可用")
                    click_success = False
                elif not target_hwnd:
                    logger.error("[后台点击] 目标窗口句柄无效")
                    click_success = False
                elif not win32gui.IsWindow(target_hwnd):
                    logger.error(f"[后台点击] 目标窗口{target_hwnd}无效或已关闭")
                    click_success = False
                else:
                    # 统一通过全局模拟器管理器获取实例，保证并发窗口链路一致
                    from utils.input_simulation import global_input_simulator_manager

                    input_sim = global_input_simulator_manager.get_simulator(
                        hwnd=target_hwnd,
                        execution_mode=effective_execution_mode,
                    )
                    if input_sim is None:
                        logger.error(f"[后台点击] 获取输入模拟器失败: hwnd={target_hwnd}, mode={effective_execution_mode}")
                        click_success = False
                    else:
                        if click_action == '仅按下' and not enable_auto_release:
                            logger.info("[后台点击] 鼠标按下不自动释放")
                        click_success = execute_simulator_click_action(
                            simulator=input_sim,
                            x=dpi_adjusted_click_x,
                            y=dpi_adjusted_click_y,
                            button=click_button,
                            click_action=click_action,
                            clicks=clicks,
                            interval=interval,
                            hold_duration=hold_duration,
                            auto_release=enable_auto_release,
                            mode_label="后台点击",
                            logger_obj=logger,
                            single_click_retry=False,
                            require_atomic_hold=True,
                            move_before_click=virtual_mouse_enabled,
                            stop_checker=stop_checker,
                            execution_mode=effective_execution_mode,
                            target_hwnd=target_hwnd,
                            task_type=TASK_TYPE,
                        )

                        if click_success:
                            logger.info("后台点击操作成功。")
                        else:
                            logger.warning("警告: 后台点击失败。")

            except Exception as click_err:
                 logger.error(f"[后台点击] 点击操作时发生异常: {click_err}", exc_info=True)
                 click_success = False

    if found and enable_click and click_success and virtual_mouse_enabled:
        sync_virtual_mouse_position(int(click_x), int(click_y), persist_global=False)

    # Determine final success based on finding AND clicking
    # If not found, click_success remains False
    success = found and click_success

    try:
        # 3. 根据结果确定下一步
        if success:
            # 只显示图片名称，不显示完整路径
            if absolute_image_path.startswith('memory://'):
                image_name = absolute_image_path.replace('memory://', '')
            else:
                # 确保 os 模块可用
                import os
                image_name = os.path.basename(absolute_image_path)
            logger.info(f"任务 '{TASK_NAME}' (图片: '{image_name}') 执行成功。")
            # 使用统一的成功处理（包含延迟）
            from .task_utils import handle_success_action
            return handle_success_action(params, card_id, kwargs.get('stop_checker'))
        else: # Handle overall failure (either not found or click failed)
            # 只显示图片名称，不显示完整路径
            if absolute_image_path.startswith('memory://'):
                image_name = absolute_image_path.replace('memory://', '')
            else:
                # 确保 os 模块可用
                import os
                image_name = os.path.basename(absolute_image_path)
            logger.info(f"任务 '{TASK_NAME}' (图片: '{image_name}') 执行失败 (未找到或点击失败)。")
            # 使用统一的失败处理
            from .task_utils import handle_failure_action
            return handle_failure_action(params, card_id)

        # --- ADDED: Store confidence values in counters REGARDLESS of success/failure (if matching occurred) ---
        if card_id is not None:
            req_conf_key = f'__required_confidence_{card_id}'
            act_conf_key = f'__actual_confidence_{card_id}'

            # Store required confidence (should always be available if task ran)
            counters[req_conf_key] = confidence
            logger.debug(f"  Storing required confidence to counters: {req_conf_key} = {confidence}")

            # Store actual confidence IF matching was performed (max_val exists)
            if 'max_val' in locals() or 'max_val' in globals(): # Check if max_val was defined
                # Ensure max_val is float before storing
                try:
                     actual_conf_float = float(max_val)
                     counters[act_conf_key] = actual_conf_float
                     logger.debug(f"  Storing actual confidence to counters: {act_conf_key} = {actual_conf_float}")
                except (ValueError, TypeError):
                     logger.warning(f"  未能将实际置信度 ({max_val}) 转换为浮点数存储。")
                     counters[act_conf_key] = -1.0 # Indicate conversion failure
            else:
                # Indicate that matching likely didn't occur or max_val wasn't found
                counters[act_conf_key] = -1.0 # Use -1.0 to signify not available/not found
                logger.debug(f"  本地作用域未找到实际置信度(max_val)，写入 {act_conf_key} = -1.0")
        else:
            logger.warning("无法存储置信度到 counters：未提供 card_id。")
        # --- END ADDED ---

    finally:
        # 结束时统一释放函数级图像引用，避免跨任务残留
        needle_image_raw = None
        needle_image_processed = None
        needle_match_image = None
        screenshot_img = None
        haystack_processed = None
        result_matrix = None
        match_result = None

# Example (for testing standalone)
if __name__ == '__main__':
    # --- 测试后台截图 ---
    # !!! 重要：修改为你想要测试的窗口标题 或 部分标题 !!!
    # test_target_title = "无标题 - 记事本" # 例如：中文记事本
    # test_target_title = "Untitled - Notepad" # 例如：英文记事本
    test_target_title_part = "剑网3无界" # 使用部分标题查找

    test_hwnd = None

    if PYWIN32_AVAILABLE:
        try:
            # --- MODIFIED: Find window by partial title ---
            logger.info(f"尝试通过部分标题 '{test_target_title_part}' 查找窗口...")
            top_windows = []
            # Define callback function inline or ensure it's defined correctly
            def enum_window_callback(hwnd, param):
                param.append(hwnd)
                return True # Must return True to continue enumeration

            win32gui.EnumWindows(enum_window_callback, top_windows)
            found_title = "" # Store the title of the found window
            for hwnd_item in top_windows:
                window_title = win32gui.GetWindowText(hwnd_item)
                if test_target_title_part in window_title:
                    test_hwnd = hwnd_item
                    found_title = window_title # Store the full title
                    logger.info(f"找到匹配窗口: '{found_title}'，HWND: {test_hwnd}")
                    break # Use the first match
            # --- END MODIFICATION ---

            # Ensure win32gui is imported (should be from top level) - No longer needed FindWindow call

            if test_hwnd:
                # logger.info(f"找到窗口 '{found_title}'，HWND: {test_hwnd}") # Log already happened

                # 1. 执行智能截图（WGC）
                logger.info("使用 WGC 进行窗口截图...")
                screenshot = capture_window_wgc(test_hwnd, client_area_only=True)

                # 2. 检查并保存截图
                if screenshot is not None and isinstance(screenshot, np.ndarray):
                    logger.info(f"后台截图成功，截图尺寸: {screenshot.shape}")
                    save_path = "_test_find_image_click_screenshot.png"
                    try:
                        # Ensure cv2 and os are imported (should be from top level)
                        cv2.imwrite(save_path, screenshot)
                        # Use os.path.abspath for clearer path reporting
                        # 确保 os 模块可用
                        import os
                        logger.info(f"截图已保存到: {os.path.abspath(save_path)}")
                    except Exception as e:
                        logger.error(f"保存截图 '{save_path}' 失败: {e}", exc_info=True)
                else:
                    logger.error("后台截图失败或返回无效结果 (None 或非 NumPy 数组)。")

            else:
                logger.error(f"找不到标题包含 '{test_target_title_part}' 的窗口。请确保窗口已打开。") # Updated error message
        except Exception as e:
            logger.error(f"查找窗口 '{test_target_title_part}' 或执行截图时发生错误: {e}", exc_info=True) # Updated error message
    else:
        logger.error("pywin32 库未安装，无法执行后台截图测试。请运行: pip install pywin32")

    logger.info("image_match_click.py 模块测试结束。")

def _diagnose_click_position(target_hwnd: int, left_x: int, top_y: int, center_x: int, center_y: int,
                           click_x: int, click_y: int, template_w: int, template_h: int):
    """
    诊断点击位置，帮助调试点击偏移问题
    """
    pass

def test_image_recognition(params: Dict[str, Any], target_hwnd: Optional[int] = None, main_window=None, parameter_panel=None):
    """
    测试图片识别功能，在绑定窗口上绘制找到的图片区域（使用统一测试模块）

    Args:
        params: 参数字典，包含image_path、confidence等
        target_hwnd: 目标窗口句柄
        main_window: 主窗口对象（用于隐藏）
        parameter_panel: 参数面板对象（用于隐藏）
    """
    try:
        from tasks.image_match_probe import test_image_recognition as unified_test
        unified_test(params, target_hwnd, main_window, parameter_panel)
    except Exception as e:
        logger.error(f"调用统一测试函数失败: {e}", exc_info=True)



