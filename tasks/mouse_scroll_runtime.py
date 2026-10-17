# -*- coding: utf-8 -*-
import pyautogui
import logging
from typing import Dict, Any, Optional, Tuple

import win32gui

WHEEL_DELTA = 120  # Standard value for mouse wheel delta

import cv2
import numpy as np
import os # For path checking if needed, though imdecode handles paths
import traceback # For detailed error logging
from utils.input.mouse_runtime import mouse_move_fixer
from utils.match.smart_image_matcher import normalize_match_image
from tasks.task_utils import capture_and_match_template_smart

logger = logging.getLogger(__name__)

def _find_image_background(target_hwnd, full_image_path, template_match_image, confidence_val, params, kwargs, counters) -> Tuple[bool, Optional[int], Optional[int], Optional[int]]:
    """Helper to find image in background mode. Returns (found, client_x, client_y, specific_scroll_hwnd).

    注意：匹配逻辑已迁移到截图子进程，主进程仅接收小结果。
    """
    image_found_bg = False
    found_client_x, found_client_y = None, None
    specific_scroll_hwnd = target_hwnd

    if not target_hwnd or not win32gui.IsWindow(target_hwnd):
        logger.error(f"后台模式错误：目标窗口句柄 {target_hwnd} 无效或已销毁")
        return False, None, None, target_hwnd

    logger.debug("[后台模式] 使用截图子进程执行截图+匹配")

    match_response = capture_and_match_template_smart(
        target_hwnd=target_hwnd,
        template=template_match_image,
        confidence_threshold=float(confidence_val),
        template_key=(str(full_image_path) if full_image_path else None),
        capture_timeout=0.8,
        roi=None,
        client_area_only=True,
        use_cache=False,
    )

    if not match_response or not bool(match_response.get("success")):
        err = (match_response or {}).get("error") if isinstance(match_response, dict) else "unknown_error"
        logger.error(f"后台子进程匹配失败: {err}")
        return False, None, None, target_hwnd

    try:
        score = float(match_response.get("confidence", 0.0) or 0.0)
    except Exception:
        score = 0.0

    raw_location = match_response.get("location")
    parsed_location = None
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

    if bool(match_response.get("matched", False)) and parsed_location is not None and score >= confidence_val:
        image_found_bg = True
        top_left_x, top_left_y, template_w, template_h = parsed_location
        found_client_x = int(top_left_x) + int(template_w) // 2
        found_client_y = int(top_left_y) + int(template_h) // 2
        logger.info(f"后台图片找到，客户区中心坐标: ({found_client_x}, {found_client_y})")

        from utils.runtime_config import get_runtime_config
        from utils.input_simulation.mode_utils import parse_background_options
        from utils.window.enhanced_child_window_finder import resolve_background_mouse_targets

        hierarchy_broadcast, _ = parse_background_options(get_runtime_config())
        targets, _ = resolve_background_mouse_targets(
            target_hwnd, found_client_x, found_client_y, hierarchy_broadcast,
        )
        specific_scroll_hwnd = targets[-1]

        find_location_only = params.get('find_location_only', False)
        if find_location_only:
            card_id = kwargs.get('card_id')
            if card_id is not None:
                counters[f'__found_hwnd_{card_id}'] = specific_scroll_hwnd
                counters[f'__found_client_x_{card_id}'] = found_client_x
                counters[f'__found_client_y_{card_id}'] = found_client_y
                logger.info("仅查找模式(后台)：已保存句柄和客户区坐标")
            else:
                logger.warning("仅查找模式(后台)：缺少 card_id，无法保存定位信息")
                image_found_bg = False
    else:
        logger.warning(f"后台图片未找到(置信度 {score:.4f} < {confidence_val})")

    return image_found_bg, found_client_x, found_client_y, specific_scroll_hwnd


def _find_image_foreground(target_hwnd, full_image_path, template_match_image, confidence_val, params, kwargs, counters) -> Tuple[bool, Optional[int], Optional[int]]:
    """Helper to find image in foreground mode. Returns (found, screen_x, screen_y).

    使用目标窗口截图子进程匹配；窗口无效时直接失败。
    """
    image_found_fg = False
    found_screen_x, found_screen_y = None, None

    if target_hwnd and win32gui.IsWindow(target_hwnd):
        logger.debug("[前台模式] 使用截图子进程执行截图+匹配")
        match_response = capture_and_match_template_smart(
            target_hwnd=target_hwnd,
            template=template_match_image,
            confidence_threshold=float(confidence_val),
            template_key=(str(full_image_path) if full_image_path else None),
            capture_timeout=0.8,
            roi=None,
            client_area_only=True,
            use_cache=False,
        )

        if not match_response or not bool(match_response.get("success")):
            err = (match_response or {}).get("error") if isinstance(match_response, dict) else "unknown_error"
            logger.error(f"前台子进程匹配失败: {err}")
            return False, None, None

        try:
            score = float(match_response.get("confidence", 0.0) or 0.0)
        except Exception:
            score = 0.0

        raw_location = match_response.get("location")
        parsed_location = None
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

        if bool(match_response.get("matched", False)) and parsed_location is not None and score >= confidence_val:
            image_found_fg = True
            top_left_x, top_left_y, template_w, template_h = parsed_location
            center_x_client = int(top_left_x) + int(template_w) // 2
            center_y_client = int(top_left_y) + int(template_h) // 2
            found_screen_x, found_screen_y = win32gui.ClientToScreen(target_hwnd, (center_x_client, center_y_client))

            logger.info(f"前台图片找到，屏幕坐标: ({found_screen_x}, {found_screen_y})")

            find_location_only = params.get('find_location_only', False)
            if find_location_only:
                card_id = kwargs.get('card_id')
                if card_id is not None:
                    counters[f'__found_screen_x_{card_id}'] = found_screen_x
                    counters[f'__found_screen_y_{card_id}'] = found_screen_y
                    logger.info("仅查找模式(前台)：已保存屏幕坐标")
                else:
                    logger.warning("仅查找模式(前台)：缺少 card_id，无法保存定位信息")
                    image_found_fg = False
        else:
            logger.warning(f"前台图片未找到(置信度 {score:.4f} < {confidence_val})")

        return image_found_fg, found_screen_x, found_screen_y

    logger.error("前台图片定位失败：缺少有效窗口句柄，无法使用子进程匹配")
    return False, None, None
def execute_mouse_scroll(params: Dict[str, Any], counters: Dict[str, int], execution_mode: str, target_hwnd: Optional[int], window_region: Optional[Tuple[int, int, int, int]], **kwargs) -> Tuple[bool, str, Optional[int]]:
    logger.debug(f"MouseScroll Task: Received kwargs: {kwargs}")
    stop_checker = kwargs.get('stop_checker')
    card_id = kwargs.get('card_id')  # 获取card_id用于路径纠正

    from tasks.task_utils import interruptible_sleep

    def _control_requested() -> bool:
        if not callable(stop_checker):
            return False
        return bool(stop_checker())

    def _sleep_with_control(duration: float, stop_message: str) -> Tuple[bool, Optional[Tuple[bool, str, Optional[int]]]]:
        safe_duration = max(0.0, float(duration or 0.0))
        if safe_duration <= 0:
            return True, None
        try:
            interruptible_sleep(safe_duration, stop_checker)
        except InterruptedError:
            logger.info(stop_message)
            return False, (False, '任务已停止', None)
        if _control_requested():
            logger.info(stop_message)
            return False, (False, '任务已停止', None)
        return True, None

    direction = params.get('direction', '向下')
    try:
        scroll_count = int(params.get('scroll_count', 1))
        interval = float(params.get('interval', 0.1))
    except (ValueError, TypeError) as e:
        logger.error(f"无效的滚动或间隔参数: {e}")
        return False, '执行下一步', None

    location_mode = params.get('location_mode', '窗口中心')
    coordinate_mode = params.get('coordinate_mode', '客户区坐标')
    scroll_value_per_unit = WHEEL_DELTA
    if direction == '向下':
        scroll_value_per_unit = -scroll_value_per_unit

    # 新增：根据执行模式设置前台输入管理器的强制模式（在标准化之前）
    from utils.input.foreground_input_manager import get_foreground_input_manager

    if execution_mode and execution_mode.startswith('foreground'):
        foreground_input = get_foreground_input_manager()
        foreground_input.set_execution_mode(execution_mode)
        logger.info(f"[鼠标模式] 前台模式 - {execution_mode}（滚动）")

    # Normalize execution mode to avoid mixing foreground/background
    original_execution_mode = execution_mode or ""
    normalized_mode = original_execution_mode.strip().lower()
    postmessage_coords_are_screen = False
    if normalized_mode.startswith("foreground"):
        normalized_mode = "foreground"
    elif normalized_mode.startswith("background"):
        normalized_mode = "background"
    else:
        logger.error("未知的滚轮执行模式：%r", original_execution_mode)
        return False, '执行下一步', None
    if original_execution_mode:
        logger.debug(f"标准化执行模式: {original_execution_mode} -> {normalized_mode}")
    
    def _format_execution_mode_name(mode: str) -> str:
        if not mode:
            return "未知"
        mode = mode.strip().lower()
        if mode == "foreground_driver":
            return "前台一"
        if mode == "foreground_py":
            return "前台二"
        if mode == "background_sendmessage":
            return "后台一"
        if mode == "background_postmessage":
            return "后台二"
        if mode.startswith("background"):
            return "后台"
        if mode.startswith("foreground"):
            return "前台"
        return mode
    
    mode_name = _format_execution_mode_name(original_execution_mode)
    logger.info(f"准备执行鼠标滚轮: 方向='{direction}', 步数={scroll_count}, 起始位置模式='{location_mode}', 模式='{mode_name}' (原始: {original_execution_mode or '未知'})")

    target_x, target_y = None, None

    from task_workflow.resource_path import unwrap_resource_path
    from tasks.task_utils import correct_single_image_path

    raw_image_path = unwrap_resource_path(params.get('image_path')) or ""
    image_path_param = correct_single_image_path(raw_image_path, card_id) if raw_image_path else None

    confidence_val = float(params.get('confidence', 0.8))


    # --- Location Determination ---
    try:
        if location_mode == "图片位置":
            if not image_path_param: # Use the renamed variable
                logger.error("错误：选择了图片位置模式，但未提供图片路径。")
                return False, '执行下一步', None

            full_image_path = image_path_param
            relative_filename = os.path.basename(full_image_path)

            try: # Inner try for image processing and finding
                img_np = np.fromfile(full_image_path, dtype=np.uint8)
                template_img_bgr_or_bgra = cv2.imdecode(img_np, cv2.IMREAD_UNCHANGED)
                if template_img_bgr_or_bgra is None:
                    logger.error(f"无法加载或解码模板图片: {full_image_path}")
                    return False, '执行下一步', None
                
                template_match_image = normalize_match_image(template_img_bgr_or_bgra)
                if template_match_image is None:
                    logger.error(f"模板图片规范化失败: {full_image_path}")
                    return False, '执行下一步', None
                
                logger.info(f"准备查找图片: '{relative_filename}' (置信度 >= {confidence_val})")

                image_found_flag = False
                if normalized_mode == 'background':
                    if not target_hwnd:
                        logger.error("后台图片定位需要目标窗口句柄。")
                        return False, '执行下一步', None
                    image_found_flag, found_cx, found_cy, _specific_hwnd = _find_image_background(
                        target_hwnd, full_image_path, template_match_image, confidence_val, params, kwargs, counters
                    )
                    if image_found_flag:
                        target_x, target_y = found_cx, found_cy
                else: # Foreground
                    image_found_flag, found_sx, found_sy = _find_image_foreground(
                        target_hwnd, full_image_path, template_match_image, confidence_val, params, kwargs, counters
                    )
                    if image_found_flag:
                        target_x, target_y = found_sx, found_sy
                
                if params.get('find_location_only', False) and image_found_flag:
                    logger.info("仅查找模式成功完成。")
                    return True, '执行下一步', None
                if not image_found_flag:
                    logger.error("图片定位失败：未找到指定的图片。")
                    return False, '执行下一步', None

            except Exception as img_proc_err: # Catch errors from image processing/finding
                logger.error(f"处理或查找图片时发生错误: {img_proc_err}", exc_info=True)
                return False, '执行下一步', None
            # End of the inner try-except for image processing

        elif location_mode == "指定坐标":
            # 解析滚动起始位置坐标
            scroll_position = params.get('scroll_start_position', '500,300')
            coordinate_mode = params.get('coordinate_mode', '客户区坐标')  # 获取坐标模式
            postmessage_coords_are_screen = coordinate_mode == '屏幕坐标'

            if not isinstance(scroll_position, str) or scroll_position.count(',') != 1:
                raise ValueError("滚动起点必须是横坐标,纵坐标")
            raw_x, raw_y = map(int, scroll_position.split(','))

            # 直接使用客户区坐标，不进行转换
            target_x, target_y = raw_x, raw_y
            logger.info(f"使用客户区坐标: ({target_x}, {target_y}) (模式: {coordinate_mode}, 执行模式: {execution_mode})")

        elif location_mode == "窗口中心":
            logger.info("起始位置模式：窗口中心。计算窗口中心...")
            if target_hwnd:
                try:
                    if not win32gui.IsWindow(target_hwnd):
                        raise RuntimeError("无法确定滚轮窗口中心：目标窗口已失效")
                    else:
                        if normalized_mode == 'background':
                            client_rect = win32gui.GetClientRect(target_hwnd)
                            target_x = (client_rect[2] - client_rect[0]) // 2
                            target_y = (client_rect[3] - client_rect[1]) // 2
                            logger.info(f"后台模式：滚动定位到目标窗口客户区中心: ({target_x}, {target_y})")
                        else: # Foreground
                            rect = win32gui.GetWindowRect(target_hwnd)
                            target_x = (rect[0] + rect[2]) // 2
                            target_y = (rect[1] + rect[3]) // 2
                            logger.info(f"前台模式：滚动定位到目标窗口屏幕中心: ({target_x}, {target_y})")
                except Exception as move_err: # Corrected indent for this except
                    raise RuntimeError("无法确定滚轮窗口中心") from move_err
            else:
                raise RuntimeError("无法确定滚轮窗口中心：未绑定目标窗口")
        # else: location_mode == "当前位置" (or default if "当前位置" was an option)
            # target_x, target_y remain None, scrolling happens at current mouse pos
    
    except Exception as setup_err: # This is the except for the outer try block for location determination
         logger.error(f"确定滚动位置时发生错误: {setup_err}", exc_info=True)
         return False, '执行下一步', None
    # End of the outer try-except for location determination

    # --- 执行滚动 ---
    try:
        if normalized_mode == 'background':
            if not target_hwnd:
                logger.error("无法执行后台滚动：缺少有效的目标窗口句柄。")
                return False, '执行下一步', None
            if not win32gui.IsWindow(target_hwnd):
                logger.error(f"后台滚动错误：目标滚动窗口句柄 {target_hwnd} 无效。")
                return False, '执行下一步', None

            scroll_hwnd = target_hwnd
            logger.info(f"执行后台鼠标滚轮: 滚动目标句柄={scroll_hwnd}, 坐标={(target_x, target_y) if target_x is not None else '默认'}, 方向='{direction}', 次数={scroll_count}")
            if target_x is None or target_y is None:
                rect = win32gui.GetWindowRect(scroll_hwnd)
                target_x = (rect[0] + rect[2]) // 2
                target_y = (rect[1] + rect[3]) // 2
                postmessage_coords_are_screen = True

            logger.debug(
                f"后台滚轮参数: 方向={direction}, 单刻度值={scroll_value_per_unit}, "
                f"总步数={scroll_count}, 间隔={interval}"
            )

            from utils.input_simulation.factory import global_input_simulator_manager

            if postmessage_coords_are_screen or coordinate_mode == '屏幕坐标':
                client_x, client_y = win32gui.ScreenToClient(scroll_hwnd, (int(target_x), int(target_y)))
            else:
                client_x, client_y = int(target_x), int(target_y)
            simulator = global_input_simulator_manager.create_temporary_simulator(
                scroll_hwnd, execution_mode=original_execution_mode,
            )
            if simulator is None:
                raise RuntimeError("无法创建后台滚轮输入实例")
            try:
                for i in range(scroll_count):
                    if _control_requested():
                        return False, '任务已停止', None
                    if not simulator.scroll(client_x, client_y, scroll_value_per_unit):
                        return False, '后台滚轮发送失败', None
                    sleep_ok, stop_result = _sleep_with_control(0.02, "后台滚轮收尾等待期间已停止")
                    if not sleep_ok:
                        return stop_result
                    if i < scroll_count - 1 and interval > 0:
                        sleep_ok, stop_result = _sleep_with_control(interval, "后台滚轮间隔等待期间已停止")
                        if not sleep_ok:
                            return stop_result
            finally:
                global_input_simulator_manager.close_simulator(simulator)
            logger.info("后台鼠标滚轮操作完成。")
            from .task_utils import handle_success_action
            return handle_success_action(params, kwargs.get('card_id'), kwargs.get('stop_checker'))

        else: # Foreground
            mode_description = "前台"
            logger.info(f"执行{mode_description}鼠标滚轮: 目标屏幕坐标={(target_x, target_y) if target_x is not None else '当前'}, 方向='{direction}', 次数={scroll_count}")
            
            # 前台模式：激活目标窗口确保滚轮生效
            if target_hwnd:
                try:
                    from utils.window.virtual_desktop import skip_cross_desktop_activation

                    if skip_cross_desktop_activation(target_hwnd, log_prefix="前台鼠标滚轮"):
                        pass
                    elif win32gui.IsWindow(target_hwnd):
                        logger.debug(f"前台模式：激活目标窗口 {target_hwnd}")
                        win32gui.SetForegroundWindow(target_hwnd)
                        sleep_ok, stop_result = _sleep_with_control(0.1, "[前台鼠标滚轮] 窗口激活等待期间检测到暂停/停止请求")
                        if not sleep_ok:
                            return stop_result
                except Exception as activate_err:
                    raise RuntimeError("前台滚轮激活目标窗口失败") from activate_err
            
            # 移动到目标位置（如果指定）
            if target_x is not None and target_y is not None:
                if _control_requested(): return False, '任务已停止', None
                try:
                    logger.debug(f"前台移动鼠标到目标位置: ({target_x}, {target_y})")

                    # 使用统一的鼠标移动器（客户区坐标）
                    if coordinate_mode == '客户区坐标':
                        mouse_move_fixer.move_to_client_coord(target_hwnd, target_x, target_y)
                        logger.info(f"前台滚轮移动: 客户区坐标({target_x}, {target_y})")
                    else:
                        pyautogui.moveTo(target_x, target_y, duration=0.1)
                        logger.info(f"前台滚轮移动: 屏幕坐标({target_x}, {target_y})")

                    sleep_ok, stop_result = _sleep_with_control(0.05, "[前台鼠标滚轮] 鼠标移动收尾等待期间检测到暂停/停止请求")
                    if not sleep_ok:
                        return stop_result
                except Exception as move_err:
                     logger.error(f"前台移动鼠标失败: {move_err}")
                     return False, f'前台移动鼠标失败: {move_err}', None

            logger.debug(
                f"前台滚轮参数: 方向={direction}, 单刻度值={scroll_value_per_unit}, "
                f"总步数={scroll_count}, 间隔={interval}"
            )
            
            for i in range(scroll_count):
                if _control_requested(): return False, f'任务已停止 (滚动 {i+1})', None
                logger.debug(f"执行前台滚轮 {i+1}/{scroll_count}: 单步delta={scroll_value_per_unit}")
                try:
                    pyautogui.scroll(scroll_value_per_unit)
                    sleep_ok, stop_result = _sleep_with_control(0.02, "[前台鼠标滚轮] 单次滚动收尾等待期间检测到暂停/停止请求")
                    if not sleep_ok:
                        return stop_result
                except Exception as scroll_err:
                    raise RuntimeError(f"前台滚轮第 {i+1} 次操作失败") from scroll_err
                
                if scroll_count > 1 and i < scroll_count - 1 and interval > 0:
                    sleep_chunk = 0.05 
                    remaining_sleep = interval
                    while remaining_sleep > 0:
                        actual_sleep = min(sleep_chunk, remaining_sleep)
                        sleep_ok, stop_result = _sleep_with_control(actual_sleep, "前台鼠标滚轮任务在 interval sleep 期间被请求停止。")
                        if not sleep_ok:
                            return stop_result
                        remaining_sleep -= actual_sleep
            logger.info(f"{mode_description} 鼠标滚轮操作完成。")
            # 使用统一的成功处理（包含延迟）
            from .task_utils import handle_success_action
            return handle_success_action(params, kwargs.get('card_id'), kwargs.get('stop_checker'))
            
    except Exception as scroll_err:
        logger.exception(f"执行鼠标滚轮操作时发生错误: {scroll_err}")
        return False, '执行下一步', None
