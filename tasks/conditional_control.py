# -*- coding: utf-8 -*-
import logging
import time
import threading  # 用于线程锁
import operator # For counter comparison
from typing import Dict, Any, Optional, Tuple, List
import os # <-- ADDED Import
from tasks.task_utils import coerce_bool

# Try importing image processing libraries
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

# Try importing pyautogui for image finding & screenshot
try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

# Try importing pywin32 for potential future window/pixel checks
try:
    import win32gui
    import win32con
    WINDOWS_AVAILABLE = True
    PYWIN32_AVAILABLE = True # Add alias for consistency
except ImportError:
    WINDOWS_AVAILABLE = False
    PYWIN32_AVAILABLE = False # Add alias for consistency

# 定义logger（必须在使用前定义）
logger = logging.getLogger(__name__)

# --- Comparison Operators Mapping ---
COMPARISON_OPERATORS = {
    '==': operator.eq,
    '!=': operator.ne,
    '<': operator.lt,
    '<=': operator.le,
    '>': operator.gt,
    '>=': operator.ge,
}

COUNTER_RESET_TIMINGS = {"条件满足时", "条件不满足时"}


def _normalize_counter_reset_timing(value: Any) -> str:
    """规范化计数器重置时机配置。"""
    text = str(value or "").strip()
    if text in COUNTER_RESET_TIMINGS:
        return text
    return "条件满足时"


def _should_reset_counter(
    params: Dict[str, Any],
    *,
    condition_met: bool,
    on_success_action: str,
) -> bool:
    """根据参数决定计数器是否需要在本次执行后重置。"""
    reset_enabled = params.get("enable_counter_reset")

    # 兼容旧工作流：未配置新参数时保持原有行为。
    if reset_enabled is None:
        return condition_met and on_success_action != "继续执行本步骤"

    if not coerce_bool(reset_enabled):
        return False

    reset_timing = _normalize_counter_reset_timing(
        params.get("counter_reset_timing", "条件满足时")
    )
    return condition_met if reset_timing == "条件满足时" else not condition_met


def _reset_counter_if_needed(
    params: Dict[str, Any],
    counters: Dict[str, int],
    *,
    current_card_id: Optional[int],
    condition_type: str,
    condition_met: bool,
    on_success_action: str,
) -> None:
    """按配置重置条件控制计数器。"""
    if condition_type != "计数器判断" or current_card_id is None:
        return

    if not _should_reset_counter(
        params,
        condition_met=condition_met,
        on_success_action=on_success_action,
    ):
        return

    exec_count_key = f"__card_exec_count_{current_card_id}"
    counters[exec_count_key] = 0
    logger.info("计数器已重置: card_id=%s", current_card_id)

# Define activation helper function (copied for now)
def _activate_window_foreground(target_hwnd: Optional[int], logger):
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
            time.sleep(0.15)
            win32gui.SetForegroundWindow(target_hwnd)
            time.sleep(0.15)
            logger.info(f"窗口 {target_hwnd} 已尝试恢复并设置为前台。")
        else:
            logger.info(f"尝试将窗口 {target_hwnd} 设置为前台...")
            win32gui.SetForegroundWindow(target_hwnd)
            time.sleep(0.1)
        return True
    except Exception as e:
        logger.warning(f"设置前台窗口 {target_hwnd} 时出错: {e}。")
        return False

# --- Image Preprocessing Helper ---
def _preprocess_image(img, method: str, threshold_val: int = 128, 
                      canny_thresh1: int = 100, canny_thresh2: int = 200,
                      scale_factor: float = 2.0):
    if not CV2_AVAILABLE:
        logger.warning("无法预处理图像：缺少 'opencv-python' 库。")
        return img # Return original if cv2 not available
        
    if img is None:
        logger.error("无法预处理图像：图像数据为空。")
        return None
        
    processed_img = img
    gray_img = None # Cache grayscale image if needed multiple times

    try:
        # 智能放大处理
        if method == '智能放大':
            h, w = img.shape[:2]
            if h < 50 or w < 50:  # 如果宽或高小于50像素
                new_width = int(w * scale_factor)
                new_height = int(h * scale_factor)
                processed_img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
                logger.debug(f"图片从 {w}x{h} 放大到 {new_width}x{new_height}")
            return processed_img
            
        # Ensure grayscale for methods that need it
        if method in ['灰度化', '二值化', '边缘检测 (Canny)']:
            if len(img.shape) == 3:
                # 根据通道数选择正确的转换
                if img.shape[2] == 4:
                    gray_img = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
                else:
                    gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            else:
                gray_img = img # Already grayscale
                
        # Apply selected method
        if method == '灰度化':
            processed_img = gray_img
        elif method == '二值化':
            _, processed_img = cv2.threshold(gray_img, threshold_val, 255, cv2.THRESH_BINARY)
        elif method == '边缘检测 (Canny)':
             # Apply Canny edge detection
             processed_img = cv2.Canny(gray_img, canny_thresh1, canny_thresh2)
        # '无' or unknown method: return original (BGR or original gray/BGRA)
        # If no processing was done, return the original image
        elif method == '无':
             processed_img = img # Return the original color/unchanged image
             
        return processed_img
    except Exception as e:
        logger.exception(f"图像预处理 ('{method}') 时出错: {e}")
        return img # Return original on error

# --- ADDED: Helper function for motion detection ---
def _check_motion(
    params: Dict[str, Any],
    execution_mode: str,
    target_hwnd: Optional[int],
    prev_image: Optional[np.ndarray],
    *,
    state_key: Optional[str] = None,
    reset_baseline: bool = False,
) -> Tuple[bool, Optional[np.ndarray]]:
    """移动检测在主进程截图链路执行，主进程不保留帧数据。"""
    try:
        from services.screenshot_pool import capture_and_check_motion
    except Exception as exc:
        logger.error("移动检测失败：截图接口不可用: %s", exc)
        return False, None

    if not target_hwnd:
        logger.error("移动检测失败：缺少目标窗口句柄 (HWND)。")
        return False, None

    try:
        param_x = int(params.get('minimap_x', 0) or 0)
        param_y = int(params.get('minimap_y', 0) or 0)
        param_width = int(params.get('minimap_width', 50) or 0)
        param_height = int(params.get('minimap_height', 50) or 0)
    except Exception:
        param_x, param_y, param_width, param_height = 0, 0, 50, 50

    try:
        motion_threshold = int(params.get('motion_threshold', 50) or 50)
    except Exception:
        motion_threshold = 50
    try:
        diff_threshold = int(params.get('pixel_diff_threshold', 15) or 15)
    except Exception:
        diff_threshold = 15

    motion_threshold = max(1, motion_threshold)
    diff_threshold = max(1, min(255, diff_threshold))

    roi = None
    if param_width > 0 and param_height > 0:
        roi = (param_x, param_y, param_width, param_height)

    if state_key is None:
        state_key = f"hwnd:{int(target_hwnd)}|mode:{execution_mode or ''}|roi:{param_x},{param_y},{param_width},{param_height}"
    else:
        state_key = str(state_key)

    try:
        response = capture_and_check_motion(
            hwnd=int(target_hwnd),
            state_key=state_key,
            diff_threshold=diff_threshold,
            motion_threshold=motion_threshold,
            reset_baseline=bool(reset_baseline),
            client_area_only=True,
            use_cache=False,
            timeout=4.0,
            roi=roi,
        )
    except Exception as exc:
        logger.exception("移动检测调用异常: %s", exc)
        return False, None

    if not response.get('success'):
        logger.error("移动检测失败: %s", response.get('error'))
        return False, None

    initialized = bool(response.get('initialized', False))
    motion_detected = bool(response.get('motion_detected', False))
    changed_pixels = int(response.get('changed_pixels', 0) or 0)
    shape_changed = bool(response.get('shape_changed', False))

    if initialized:
        logger.info("  首次检测，已建立基准帧。")
    else:
        logger.info(f"  像素变化统计: {changed_pixels}")
        if shape_changed:
            logger.info("  图像尺寸变化，已重建基准帧。")
        logger.info(f"  移动检测结果: {'检测到移动' if motion_detected else '未检测到移动'}")

    return motion_detected, None

# -------------------------------------------------

# ==================================
#  Task Execution Logic
# ==================================

# --- motion state now managed in screenshot runtime ---
def _cleanup_motion_cache():
    """移动检测状态由截图运行态统一管理。"""
    clear_all_motion_cache()


def clear_all_motion_cache():
    """清理移动检测基线状态。"""
    try:
        from services.screenshot_pool import clear_motion_state
        clear_motion_state(state_key=None)
    except Exception as exc:
        logger.debug("[内存清理] 清理移动状态失败: %s", exc)
# -----------------------------------------------------------

def _execute_condition_control(params: Dict[str, Any], counters: Dict[str, int], execution_mode: str, target_hwnd: Optional[int], card_id: Optional[int], get_image_data=None, stop_checker=None) -> tuple[bool, str, Optional[int]]:
    """评估条件（计数器判断、时间判断、移动检测），并返回对应动作。"""
    condition_type = params.get('condition_type', '计数器判断')
    # Get current card ID passed by executor
    current_card_id = card_id # Use the passed ID
    if current_card_id is None:
         # Should not happen if executor passes it
         logger.warning("execute 函数未收到有效的 card_id，计数器判断将无法工作。")
         # Log warning instead of error if None is passed somehow
    # --------------------------------------------------

    # Increment and get execution count for this specific card
    current_exec_count = 0
    if current_card_id is not None:
        exec_count_key = f"__card_exec_count_{current_card_id}"
        old_count = counters.get(exec_count_key, 0)
        current_exec_count = old_count + 1
        counters[exec_count_key] = current_exec_count # Update counter

    logger.info(f"评估条件控制: 类型='{condition_type}'")

    # Get post-execution parameters
    on_success_action = params.get('on_success', '执行下一步')
    success_jump_id_str = params.get('success_jump_target_id')
    on_failure_action = params.get('on_failure', '执行下一步')
    failure_jump_id_str = params.get('failure_jump_target_id')

    logger.info(f"[参数调试] on_success={on_success_action}, on_failure={on_failure_action}")

    condition_met = False # Default to condition not met
    try:
        if condition_type == '计数器判断':
            # --- NEW Logic: Check THIS card's execution count ---
            target_count = params.get('target_execution_count', 1) # Get the target count param
            comparison_op_str = params.get('counter_comparison', '>=') # Get comparison operator string
            comparison_op = COMPARISON_OPERATORS.get(comparison_op_str) # Get the actual operator function

            if current_card_id is None:
                 logger.error("计数器判断失败，因为无法获取当前卡片ID。")
                 condition_met = False # Fail explicitly if ID is missing
            elif comparison_op is None:
                 logger.error(f"计数器判断失败：未知的比较运算符 '{comparison_op_str}'。")
                 condition_met = False
            else:
                condition_met = comparison_op(current_exec_count, target_count) # Perform comparison

                # 注意：计数器重置逻辑移到了返回结果的地方，避免变量作用域问题

        elif condition_type == '移动检测':
            # 移动检测逻辑：建立基线 -> 等待 -> 再次对比
            interval = params.get('check_interval', 0.5)
            logger.info(f"[移动检测] 开始检测 (间隔={interval}s)")

            if current_card_id is None:
                 logger.error("移动检测失败，因为无法获取当前卡片ID。")
                 condition_met = False
            else:
                state_key = (
                    f"cond_ctrl:{int(current_card_id)}:hwnd:{int(target_hwnd or 0)}:"
                    f"mode:{execution_mode or ''}:"
                    f"roi:{params.get('minimap_x', 0)},{params.get('minimap_y', 0)},"
                    f"{params.get('minimap_width', 0)},{params.get('minimap_height', 0)}"
                )

                # 第一次：建立基线
                _check_motion(
                    params,
                    execution_mode,
                    target_hwnd,
                    None,
                    state_key=state_key,
                    reset_baseline=True,
                )

                # 等待间隔时间（可中断）
                logger.info(f"[移动检测] 等待 {interval}s 后进行二次检测...")
                wait_elapsed = 0.0
                wait_check_interval = 0.1  # 每100ms检查一次停止信号

                while wait_elapsed < interval:
                    if stop_checker and stop_checker():
                        logger.info("[移动检测] 等待期间检测到用户停止信号")
                        return False, '停止工作流', None

                    sleep_time = min(wait_check_interval, interval - wait_elapsed)
                    time.sleep(sleep_time)
                    wait_elapsed += sleep_time

                # 第二次：与基线对比
                condition_met, _ = _check_motion(
                    params,
                    execution_mode,
                    target_hwnd,
                    None,
                    state_key=state_key,
                    reset_baseline=False,
                )
                logger.info(f"[移动检测] 二次检测完成，结果: {'检测到移动' if condition_met else '未检测到移动'}")


        elif condition_type == '时间判断':
            # 时间判断逻辑：检查是否到达预设时间或超过指定时长
            logger.info(f"[时间判断] 开始检测时间条件")
            if current_card_id is None:
                logger.error("时间判断失败，因为无法获取当前卡片ID。")
                condition_met = False
            else:
                condition_met, time_msg = _evaluate_time_condition(params, counters, current_card_id)
                logger.info(f"[时间判断] {time_msg}")

                # 如果条件不满足，且启用了检查间隔，则等待一段时间（避免CPU占用过高）
                if not condition_met:
                    enable_interval = params.get('enable_check_interval', True)
                    if enable_interval:
                        check_interval = params.get('check_interval_time', 1.0)
                        if check_interval > 0:
                            logger.debug(f"[时间判断] 等待 {check_interval} 秒后再次检查")
                            # 使用可中断的等待
                            wait_elapsed = 0.0
                            wait_check_interval = 0.1  # 每100ms检查一次停止信号

                            while wait_elapsed < check_interval:
                                if stop_checker and stop_checker():
                                    logger.info("[时间判断] 等待期间检测到用户停止信号")
                                    return False, '停止工作流', None

                                sleep_time = min(wait_check_interval, check_interval - wait_elapsed)
                                time.sleep(sleep_time)
                                wait_elapsed += sleep_time


        else:
             # This case might still be reachable if params are manually edited or corrupted
             raise ValueError(f"未知的条件类型: '{condition_type}'")

        # --- Parse jump targets ---
        success_jump_id = None
        if on_success_action == '跳转到步骤' and success_jump_id_str is not None:
            try:
                success_jump_id = int(success_jump_id_str)
            except (ValueError, TypeError):
                logger.error(f"错误 无效的成功跳转目标ID '{success_jump_id_str}'")
        elif on_success_action == '跳转到步骤':
            logger.error(f"错误 跳转操作但跳转目标ID为空: success_jump_id_str={success_jump_id_str}")
        
        failure_jump_id = None
        if on_failure_action == '跳转到步骤' and failure_jump_id_str is not None:
            try: failure_jump_id = int(failure_jump_id_str)
            except (ValueError, TypeError): logger.error(f"无效的失败跳转目标ID '{failure_jump_id_str}'")

        # --- Return based on condition and actions ---
        if condition_met:
            logger.info("条件满足，执行成功操作。")
            _reset_counter_if_needed(
                params,
                counters,
                current_card_id=current_card_id,
                condition_type=condition_type,
                condition_met=True,
                on_success_action=on_success_action,
            )

            if on_success_action == '跳转到步骤' and success_jump_id is not None:
                # --- ADD DEBUG LOG ---
                result_tuple = (True, '跳转到步骤', success_jump_id)
                logger.debug(f"[COND_CTRL Return Debug] Condition Met, Jump: Returning {result_tuple}")
                # ---------------------
                return result_tuple # Ensure jump ID is returned
            elif on_success_action == '停止工作流':
                # --- ADD DEBUG LOG ---
                result_tuple = (True, '停止工作流', None)
                logger.debug(f"[COND_CTRL Return Debug] Condition Met, Stop: Returning {result_tuple}")
                # ---------------------
                return result_tuple
            elif on_success_action == '继续执行本步骤':
                # --- ADD DEBUG LOG ---
                result_tuple = (True, '继续执行本步骤', card_id)
                logger.debug(f"[COND_CTRL Return Debug] Condition Met, Execute This Step: Returning {result_tuple}")
                # ---------------------
                return result_tuple
            else: # 执行下一步
                # --- ADD DEBUG LOG ---
                result_tuple = (True, '执行下一步', None)
                logger.debug(f"[COND_CTRL Return Debug] Condition Met, Next Step: Returning {result_tuple}")
                # ---------------------
                return result_tuple
        else:
            logger.info(f"条件不满足，执行失败操作: on_failure='{on_failure_action}'")
            _reset_counter_if_needed(
                params,
                counters,
                current_card_id=current_card_id,
                condition_type=condition_type,
                condition_met=False,
                on_success_action=on_success_action,
            )
            if on_failure_action == '跳转到步骤' and failure_jump_id is not None:
                result_tuple = (False, '跳转到步骤', failure_jump_id, '条件不满足')
                logger.info(f"[条件控制返回] {result_tuple}")
                return result_tuple
            elif on_failure_action == '停止工作流':
                result_tuple = (False, '停止工作流', None, '条件不满足')
                logger.info(f"[条件控制返回] {result_tuple}")
                return result_tuple
            elif on_failure_action == '继续执行本步骤':
                result_tuple = (False, '继续执行本步骤', card_id, '条件不满足')
                logger.info(f"[条件控制返回] {result_tuple}")
                return result_tuple
            else: # 执行下一步
                result_tuple = (False, '执行下一步', None, '条件不满足')
                logger.info(f"[条件控制返回] {result_tuple}")
                return result_tuple

    except Exception as e:
        logger.exception(f"评估条件 '{condition_type}' 时发生错误: {e}")
        # Default to failure action on error
        failure_jump_id = None # Reset just in case
        on_failure_action = params.get('on_failure', '执行下一步') # Get failure action from params
        failure_jump_id_str = params.get('failure_jump_target_id') # Get failure jump ID str from params
        determined_action = '执行下一步' # Default action on error
        determined_jump_id = None

        if on_failure_action == '跳转到步骤' and failure_jump_id_str is not None:
            try: 
                failure_jump_id = int(failure_jump_id_str)
                determined_action = '跳转到步骤'
                determined_jump_id = failure_jump_id
            except (ValueError, TypeError): 
                logger.error(f"错误处理中：无效的失败跳转目标ID '{failure_jump_id_str}'，将执行下一步。")
                determined_action = '执行下一步' # Fallback if jump ID is invalid
                determined_jump_id = None
        elif on_failure_action == '停止工作流':
            determined_action = '停止工作流'
            determined_jump_id = None
        elif on_failure_action == '继续执行本步骤':
            determined_action = '继续执行本步骤'
            determined_jump_id = card_id
        # else: action remains '执行下一步'
        
        # --- ADD DEBUG LOG for exception case --- 
        result_tuple = (False, determined_action, determined_jump_id, f"评估条件失败：{e}")
        logger.debug(f"[COND_CTRL Return Debug] Exception Fallback: Returning {result_tuple}")
        # -----------------------------------------
        return result_tuple

# Renamed from execute to execute_task for consistency with executor expectations
def execute_task(params: Dict[str, Any], counters: Dict[str, int], execution_mode: str, target_hwnd: Optional[int], window_region=None, card_id: Optional[int] = None, **kwargs) -> tuple:
    """主入口函数，调用内部的 execute logic。失败时会附带第 4 个详情字段。"""
    logger.debug(f"条件控制 execute_task (card_id={card_id}) called with params: {params}, mode: {execution_mode}, hwnd: {target_hwnd}, region: {window_region}") # Log removed images_dir
    
    # 从 kwargs 中获取 get_image_data 函数
    get_image_data = kwargs.get('get_image_data', None)
    
    try:
        # --- REMOVED images_dir from execute call ---
        # The execute function handles the core logic and returns the jump ID now
        result = _execute_condition_control(
            params=params,
            counters=counters,
            execution_mode=execution_mode,
            target_hwnd=target_hwnd,
            card_id=card_id, # Pass card_id through
            get_image_data=get_image_data, # Pass get_image_data through
            stop_checker=kwargs.get('stop_checker') # Pass stop_checker through
        )
        success, action, jump_target_id = result[:3]
        detail = result[3] if len(result) >= 4 else None
        # ---------------------------------
        logger.debug(f"条件控制 execute_task (card_id={card_id}) returning: success={success}, action='{action}', jump={jump_target_id}")
        if str(detail or "").strip():
            return success, action, jump_target_id, str(detail).strip()
        return success, action, jump_target_id
    except Exception as e:
        logger.exception(f"执行条件控制任务 (card_id={card_id}) 时发生未预料的错误: {e}")
        # Fallback to failure action
        on_failure_action = params.get('on_failure', '执行下一步')
        failure_jump_id_str = params.get('failure_jump_target_id') # Get failure jump ID str from params
        failure_jump_id = None
        if on_failure_action == '跳转到步骤' and failure_jump_id_str is not None:
            try: failure_jump_id = int(failure_jump_id_str)
            except (ValueError, TypeError): pass
            
        if on_failure_action == '跳转到步骤' and failure_jump_id is not None:
            return False, '跳转到步骤', failure_jump_id
        elif on_failure_action == '停止工作流': 
            return False, '停止工作流', None
        elif on_failure_action == '继续执行本步骤': 
            return False, '继续执行本步骤', card_id
        else: 
            return False, '执行下一步', None

# ==================================
#  Task Parameter Definition
# ==================================
def get_params_definition() -> Dict[str, Dict[str, Any]]:
    """定义条件控制任务的参数"""
    return {
        "condition_type": {
            "label": "条件类型",
            "type": "select",
            "options": ["计数器判断", "时间判断", "移动检测"],
            "default": "计数器判断",
            "tooltip": "选择用于决定工作流路径的条件类型。"
        },

        # 计数器判断参数
        "---counter_condition_params---": {
            "type": "separator",
            "label": "计数器判断参数",
            "condition": {"param": "condition_type", "value": "计数器判断"}
        },
        "target_execution_count": {
            "label": "本步骤执行次数",
            "type": "int",
            "default": 1,
            "min": 1,
            "tooltip": "当此卡片被执行达到该次数时，条件视为满足。",
            "condition": {"param": "condition_type", "value": "计数器判断"}
        },
        "counter_comparison": {
            "label": "比较方式",
            "type": "select",
            "options": [">=", ">", "==", "<=", "<", "!="],
            "default": ">=",
            "tooltip": "如何比较当前执行次数与目标次数。",
            "condition": {"param": "condition_type", "value": "计数器判断"}
        },
        "enable_counter_reset": {
            "label": "重置计数器",
            "type": "bool",
            "default": True,
            "tooltip": "启用后，按指定时机把当前条件控制卡片的计数器清零。",
            "condition": {"param": "condition_type", "value": "计数器判断"}
        },
        "counter_reset_timing": {
            "label": "重置时机",
            "type": "select",
            "options": ["条件满足时", "条件不满足时"],
            "default": "条件满足时",
            "tooltip": "仅在启用计数器重置后生效。",
            "condition": [
                {"param": "condition_type", "value": "计数器判断"},
                {"param": "enable_counter_reset", "value": True}
            ]
        },

        # 移动检测参数
        "---motion_detection_params---": {
            "type": "separator",
            "label": "移动检测参数",
            "condition": {"param": "condition_type", "value": "移动检测"}
        },
        "motion_region_selector": {
            "label": "区域获取工具",
            "type": "button",
            "button_text": "选择检测区域",
            "tooltip": "点击选择要监控移动的区域",
            "widget_hint": "motion_region_selector",
            "condition": {"param": "condition_type", "value": "移动检测"}
        },
        "motion_detection_region": {
            "label": "移动识别区域",
            "type": "text",
            "default": "X=1150, Y=40, 宽度=50, 高度=50",
            "tooltip": "当前设置的移动检测区域",
            "readonly": True,
            "condition": {"param": "condition_type", "value": "移动检测"}
        },
        "minimap_x": {
            "label": "区域 X",
            "type": "hidden",
            "default": 1150,
            "tooltip": "要监控的区域左上角的 X 坐标。",
            "condition": {"param": "condition_type", "value": "移动检测"}
        },
        "minimap_y": {
            "label": "区域 Y",
            "type": "hidden",
            "default": 40,
            "tooltip": "要监控的区域左上角的 Y 坐标。",
            "condition": {"param": "condition_type", "value": "移动检测"}
        },
        "minimap_width": {
            "label": "区域宽度",
            "type": "hidden",
            "default": 50,
            "min": 1,
            "tooltip": "要监控的区域的宽度 (像素)。",
            "condition": {"param": "condition_type", "value": "移动检测"}
        },
        "minimap_height": {
            "label": "区域高度",
            "type": "hidden",
            "default": 50,
            "min": 1,
            "tooltip": "要监控的区域的高度 (像素)。",
            "condition": {"param": "condition_type", "value": "移动检测"}
        },
        "check_interval": {
            "label": "检查间隔(秒)",
            "type": "float",
            "default": 0.5,
            "min": 0.05,
            "decimals": 2,
            "tooltip": "捕获两次截图进行比较的时间间隔。",
            "condition": {"param": "condition_type", "value": "移动检测"}
        },
        "motion_threshold": {
            "label": "运动阈值(像素数)",
            "type": "int",
            "default": 50,
            "min": 1,
            "tooltip": "区域内有多少像素发生显著变化才算作移动。",
            "condition": {"param": "condition_type", "value": "移动检测"}
        },
        "pixel_diff_threshold": {
            "label": "像素差异阈值",
            "type": "int",
            "default": 15,
            "min": 1,
            "max": 255,
            "tooltip": "单个像素的灰度值变化超过此阈值才算作变化。降低此值可提高敏感度。",
            "condition": {"param": "condition_type", "value": "移动检测"}
        },

        # 时间判断参数
        "---time_condition_params---": {
            "type": "separator",
            "label": "时间判断参数",
            "condition": {"param": "condition_type", "value": "时间判断"}
        },
        "time_mode": {
            "label": "时间模式",
            "type": "select",
            "options": ["到达指定时间", "倒计时判断"],
            "default": "到达指定时间",
            "tooltip": "到达指定时间：判断当前时间是否到达预设时间\n倒计时判断：从变量获取剩余时间并倒计时",
            "condition": {"param": "condition_type", "value": "时间判断"}
        },
        "preset_hour": {
            "label": "时",
            "type": "int",
            "default": 14,
            "min": 0,
            "max": 23,
            "inline_start": True,
            "inline_label": "预设时间",
            "tooltip": "小时 (0-23)",
            "condition": [
                {"param": "condition_type", "value": "时间判断"},
                {"param": "time_mode", "value": "到达指定时间"}
            ]
        },
        "preset_minute": {
            "label": "分",
            "type": "int",
            "default": 30,
            "min": 0,
            "max": 59,
            "inline_continue": True,
            "tooltip": "分钟 (0-59)",
            "condition": [
                {"param": "condition_type", "value": "时间判断"},
                {"param": "time_mode", "value": "到达指定时间"}
            ]
        },
        "preset_second": {
            "label": "秒",
            "type": "int",
            "default": 0,
            "min": 0,
            "max": 59,
            "inline_end": True,
            "tooltip": "秒 (0-59)",
            "condition": [
                {"param": "condition_type", "value": "时间判断"},
                {"param": "time_mode", "value": "到达指定时间"}
            ]
        },
        "enable_timeout": {
            "label": "启用超时判定",
            "type": "bool",
            "default": False,
            "tooltip": "启用后，如果当前时间超过预设时间太久，将视为失败",
            "condition": [
                {"param": "condition_type", "value": "时间判断"},
                {"param": "time_mode", "value": "到达指定时间"}
            ]
        },
        "timeout_minutes": {
            "label": "超时分钟数",
            "type": "int",
            "default": 10,
            "min": 1,
            "tooltip": "当前时间超过预设时间多少分钟后，判定为超时失败",
            "condition": [
                {"param": "condition_type", "value": "时间判断"},
                {"param": "time_mode", "value": "到达指定时间"},
                {"param": "enable_timeout", "value": True}
            ]
        },
        # 倒计时模式参数
        "countdown_variable": {
            "label": "倒计时变量名",
            "type": "text",
            "default": "extracted_var",
            "tooltip": "从变量提取卡片存储的变量名，该变量包含倒计时数据（如 {'HH': 0, 'MM': 14, 'SS': 30}）",
            "condition": [
                {"param": "condition_type", "value": "时间判断"},
                {"param": "time_mode", "value": "倒计时判断"}
            ]
        },
        "countdown_field_hour": {
            "label": "时字段名",
            "type": "text",
            "default": "HH",
            "tooltip": "变量中表示小时的字段名，留空表示无小时字段",
            "condition": [
                {"param": "condition_type", "value": "时间判断"},
                {"param": "time_mode", "value": "倒计时判断"}
            ]
        },
        "countdown_field_minute": {
            "label": "分字段名",
            "type": "text",
            "default": "MM",
            "tooltip": "变量中表示分钟的字段名，留空表示无分钟字段",
            "condition": [
                {"param": "condition_type", "value": "时间判断"},
                {"param": "time_mode", "value": "倒计时判断"}
            ]
        },
        "countdown_field_second": {
            "label": "秒字段名",
            "type": "text",
            "default": "SS",
            "tooltip": "变量中表示秒的字段名，留空表示无秒字段",
            "condition": [
                {"param": "condition_type", "value": "时间判断"},
                {"param": "time_mode", "value": "倒计时判断"}
            ]
        },
        "enable_check_interval": {
            "label": "启用检查间隔",
            "type": "bool",
            "default": True,
            "tooltip": "启用后，每次检查之间会等待指定时间，避免CPU占用过高",
            "condition": [
                {"param": "condition_type", "value": "时间判断"},
                {"param": "on_failure", "value": "继续执行本步骤"}
            ]
        },
        "check_interval_time": {
            "label": "检查间隔(秒)",
            "type": "float",
            "default": 1.0,
            "min": 0.1,
            "decimals": 1,
            "tooltip": "每次时间检查之间的等待时间",
            "condition": [
                {"param": "condition_type", "value": "时间判断"},
                {"param": "on_failure", "value": "继续执行本步骤"},
                {"param": "enable_check_interval", "value": True}
            ]
        },

        # --- Post-Execution Actions --- 
         "---post_exec---": {"type": "separator", "label": "执行后操作"},
         "on_success": {"type": "select", "label": "条件满足时", "options": ["继续执行本步骤", "执行下一步", "跳转到步骤", "停止工作流"], "default": "执行下一步", "tooltip": "当条件评估为真时执行的操作。"},
         "success_jump_target_id": {"type": "int", "label": "满足跳转目标 ID", "required": False,
                                    "widget_hint": "card_selector", # Specify combo box should use card IDs
                                    "condition": {"param": "on_success", "value": "跳转到步骤"}},
         "on_failure": {"type": "select", "label": "条件不满足时", "options": ["继续执行本步骤", "执行下一步", "跳转到步骤", "停止工作流"], "default": "执行下一步", "tooltip": "当条件评估为假时执行的操作。'执行下一步' 将沿 'failure' 连接线执行。"},
         "failure_jump_target_id": {"type": "int", "label": "不满足跳转目标 ID", "required": False,
                                     "widget_hint": "card_selector", # Specify combo box should use card IDs
                                     "condition": {"param": "on_failure", "value": "跳转到步骤"}}
    } 

def _evaluate_time_condition(params: Dict[str, Any], counters: Dict[str, int], card_id: Optional[int]) -> Tuple[bool, str]:
    """检查时间条件是否满足

    Args:
        params: 参数字典
        counters: 计数器字典，用于存储首次执行时间
        card_id: 卡片ID

    Returns:
        Tuple[bool, str]: (条件是否满足, 状态消息)
            - True: 时间条件满足
            - False: 时间条件不满足（未到时间或超时）
    """
    from datetime import datetime, timedelta

    time_mode = params.get('time_mode', '到达指定时间')

    try:
        current_time = datetime.now()

        if time_mode == '到达指定时间':
            # 模式1: 判断当前时间是否到达预设时间
            preset_hour = params.get('preset_hour', 14)
            preset_minute = params.get('preset_minute', 30)
            preset_second = params.get('preset_second', 0)
            enable_timeout = params.get('enable_timeout', False)
            timeout_minutes = params.get('timeout_minutes', 10)

            # 从三个参数构建预设时间
            try:
                today = current_time.date()
                preset_time = datetime.combine(today, datetime.min.time().replace(
                    hour=int(preset_hour),
                    minute=int(preset_minute),
                    second=int(preset_second)
                ))
            except (ValueError, TypeError) as e:
                logger.error(f"时间参数错误: 时={preset_hour}, 分={preset_minute}, 秒={preset_second}, 错误: {e}")
                return False, f"时间参数错误: {preset_hour}:{preset_minute}:{preset_second}"

            # 检查是否到达预设时间
            if current_time < preset_time:
                wait_seconds = int((preset_time - current_time).total_seconds())
                wait_minutes = wait_seconds // 60
                wait_secs = wait_seconds % 60

                if wait_minutes > 0:
                    msg = f"未到预设时间 {preset_time.strftime('%H:%M:%S')}, 还需等待 {wait_minutes}分{wait_secs}秒"
                else:
                    msg = f"未到预设时间 {preset_time.strftime('%H:%M:%S')}, 还需等待 {wait_secs}秒"

                logger.info(f"[时间判断] {msg}")
                return False, msg

            # 检查是否超时
            if enable_timeout:
                timeout_time = preset_time + timedelta(minutes=timeout_minutes)
                if current_time > timeout_time:
                    over_seconds = int((current_time - timeout_time).total_seconds())
                    over_minutes = over_seconds // 60
                    over_secs = over_seconds % 60

                    if over_minutes > 0:
                        msg = f"已超过预设时间 {timeout_minutes} 分钟 (超时 {over_minutes}分{over_secs}秒), 判定为失败"
                    else:
                        msg = f"已超过预设时间 {timeout_minutes} 分钟 (超时 {over_secs}秒), 判定为失败"

                    logger.warning(f"[时间判断] {msg}")
                    return False, msg

            # 时间满足条件
            msg = f"当前时间 {current_time.strftime('%Y-%m-%d %H:%M:%S')} 已到达预设时间 {preset_time.strftime('%H:%M:%S')}"
            logger.info(f"[时间判断] ✓ {msg}")
            return True, msg

        elif time_mode == '倒计时判断':
            # 模式2: 后台倒计时 - 从变量获取初始时间，启动后台计时器
            countdown_variable = params.get('countdown_variable', 'extracted_var').strip()
            field_hour = params.get('countdown_field_hour', 'HH').strip()
            field_minute = params.get('countdown_field_minute', 'MM').strip()
            field_second = params.get('countdown_field_second', 'SS').strip()

            # 生成计时器键名（基于卡片ID）
            timer_key = f"__countdown_timer_{card_id}"
            start_time_key = f"__countdown_start_{card_id}"
            total_seconds_key = f"__countdown_total_{card_id}"

            # 检查是否已有运行中的计时器
            if timer_key in counters:
                # 计时器已启动，计算剩余时间
                start_time = counters.get(start_time_key)
                total_seconds = counters.get(total_seconds_key, 0)

                if start_time is None:
                    msg = "计时器数据损坏，重新初始化"
                    logger.warning(f"[时间判断] {msg}")
                    del counters[timer_key]
                else:
                    # 计算已过去的时间
                    elapsed = (datetime.now() - start_time).total_seconds()
                    remaining = total_seconds - elapsed

                    if remaining <= 0:
                        # 倒计时结束，清除计时器
                        del counters[timer_key]
                        del counters[start_time_key]
                        del counters[total_seconds_key]

                        msg = f"倒计时已结束 (总时长: {int(total_seconds//3600):02d}:{int((total_seconds%3600)//60):02d}:{int(total_seconds%60):02d})"
                        logger.info(f"[时间判断] ✓ {msg}")
                        return True, msg
                    else:
                        # 倒计时未结束
                        remain_h = int(remaining // 3600)
                        remain_m = int((remaining % 3600) // 60)
                        remain_s = int(remaining % 60)

                        msg = f"倒计时进行中 (剩余: {remain_h:02d}:{remain_m:02d}:{remain_s:02d})"
                        logger.info(f"[时间判断] {msg}")
                        return False, msg

            # 首次执行，从变量获取倒计时并启动计时器
            try:
                from task_workflow.workflow_context import get_workflow_context
                context = get_workflow_context()
                countdown_data = context.get_global_var(countdown_variable)

                if countdown_data is None:
                    msg = f"未找到倒计时变量 '{countdown_variable}'"
                    logger.warning(f"[时间判断] {msg}")
                    return False, msg

                # 提取时、分、秒
                hours = 0
                minutes = 0
                seconds = 0

                if isinstance(countdown_data, dict):
                    # 字典格式，按字段名提取
                    if field_hour:
                        hours = int(countdown_data.get(field_hour, 0))
                    if field_minute:
                        minutes = int(countdown_data.get(field_minute, 0))
                    if field_second:
                        seconds = int(countdown_data.get(field_second, 0))
                elif isinstance(countdown_data, list):
                    # 列表格式，按索引提取
                    if len(countdown_data) >= 3:
                        hours = int(countdown_data[0])
                        minutes = int(countdown_data[1])
                        seconds = int(countdown_data[2])
                    elif len(countdown_data) == 2:
                        minutes = int(countdown_data[0])
                        seconds = int(countdown_data[1])
                    elif len(countdown_data) == 1:
                        seconds = int(countdown_data[0])
                elif isinstance(countdown_data, (int, float)):
                    # 单个数字，视为秒数
                    seconds = int(countdown_data)
                else:
                    msg = f"倒计时变量 '{countdown_variable}' 格式不支持: {type(countdown_data)}"
                    logger.error(f"[时间判断] {msg}")
                    return False, msg

                # 计算总秒数
                total_seconds = hours * 3600 + minutes * 60 + seconds

                if total_seconds <= 0:
                    msg = f"倒计时初始值无效 ({hours:02d}:{minutes:02d}:{seconds:02d})"
                    logger.warning(f"[时间判断] {msg}")
                    return False, msg

                # 启动计时器
                counters[timer_key] = True
                counters[start_time_key] = datetime.now()
                counters[total_seconds_key] = total_seconds

                msg = f"倒计时已启动 (总时长: {hours:02d}:{minutes:02d}:{seconds:02d})"
                logger.info(f"[时间判断] {msg}")
                return False, msg

            except ImportError:
                msg = "无法导入工作流上下文模块"
                logger.error(f"[时间判断] {msg}")
                return False, msg
            except (ValueError, TypeError, KeyError) as e:
                msg = f"解析倒计时数据失败: {e}"
                logger.error(f"[时间判断] {msg}")
                return False, msg

        else:
            logger.error(f"未知的时间模式: {time_mode}")
            return False, f"未知的时间模式: {time_mode}"

    except Exception as e:
        logger.exception(f"评估时间条件时发生错误: {e}")
        return False, f"时间判断异常: {str(e)}"



def test_image_recognition(params: Dict[str, Any], target_hwnd: Optional[int] = None, main_window=None, parameter_panel=None):
    """测试图片识别功能，在绑定窗口上绘制找到的图片区域（使用统一测试模块）"""
    try:
        from tasks.image_match_probe import test_image_recognition as unified_test
        unified_test(params, target_hwnd, main_window, parameter_panel)
    except Exception as e:
        logger.error(f"调用统一测试函数失败: {e}", exc_info=True)


# --- Test Block ---
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.info("开始 ConditionalControlTask 模块测试...")

    # --- 测试子进程截图接口 ---
    # !!! 重要：修改为你想要测试的窗口标题 或 部分标题 !!!
    test_target_title_part = "剑网3无界" # 使用部分标题查找
    test_hwnd = None
    
    # --- BEGIN: Add project root to sys.path (if needed for direct run) ---
    # import os
    # import sys
    # current_dir = os.path.dirname(os.path.abspath(__file__))
    # project_root = os.path.dirname(current_dir)
    # if project_root not in sys.path:
    #     sys.path.insert(0, project_root)
    #     print(f"Added project root: {project_root}")
    # # Re-import if necessary after path change
    # try:
    #     from services.screenshot_pool import capture_window
    # except ImportError:
    #      logger.error("Failed to import utils after path mod.")
    #      capture_window = None
    # --- END --- 

    # Ensure necessary imports are available
    try:
        import cv2
        import numpy as np
        import os
        from services.screenshot_pool import capture_window
        # Check pywin32 availability (assuming defined at module level)
        if PYWIN32_AVAILABLE:
            try:
                # --- MODIFIED: Find window by partial title --- 
                logger.info(f"尝试通过部分标题 '{test_target_title_part}' 查找窗口...")
                top_windows = []
                def enum_window_callback(hwnd, param):
                    param.append(hwnd)
                    return True
                win32gui.EnumWindows(enum_window_callback, top_windows)
                found_title = ""
                for hwnd_item in top_windows:
                    window_title = win32gui.GetWindowText(hwnd_item)
                    if test_target_title_part in window_title:
                        test_hwnd = hwnd_item
                        found_title = window_title
                        logger.info(f"找到匹配窗口: '{found_title}'，HWND: {test_hwnd}")
                        break # Use the first match
                # --- END MODIFICATION ---

                if test_hwnd:
                    # 1. 执行后台截图
                    logger.info("尝试使用 capture_window 进行后台截图...")
                    screenshot = capture_window(
                        hwnd=int(test_hwnd),
                        client_area_only=True,
                        use_cache=False,
                        timeout=4.0,
                    )
                    
                    # 2. 检查截图结果（调试保存已禁用）
                    if screenshot is not None and isinstance(screenshot, np.ndarray):
                        logger.info(f"后台截图成功，截图尺寸: {screenshot.shape}")
                        # 调试截图保存已禁用（减少打包大小）
                        # save_path = "_test_conditional_control_screenshot.png"
                        # cv2.imwrite(save_path, screenshot)
                    else:
                        logger.error("后台截图失败或返回无效结果。")
                        
                else:
                    logger.error(f"找不到标题包含 '{test_target_title_part}' 的窗口。")
            except Exception as e:
                logger.error(f"查找窗口或执行截图时发生错误: {e}", exc_info=True)
        else:
            logger.error("pywin32 库未安装，无法执行后台截图测试。")
    except ImportError as imp_err:
        logger.error(f"测试后台截图所需库导入失败: {imp_err}. 请确保已安装 OpenCV (cv2), NumPy, pywin32.")

    logger.info("ConditionalControlTask 模块测试结束。")





