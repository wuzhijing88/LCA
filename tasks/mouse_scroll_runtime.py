# -*- coding: utf-8 -*-
import pyautogui
import logging
from typing import Dict, Any, Optional, Tuple

import win32api
import win32con
import win32gui

WHEEL_DELTA = 120  # Standard value for mouse wheel delta

import cv2
import numpy as np
import os # For path checking if needed, though imdecode handles paths
import traceback # For detailed error logging
from utils.input.mouse_runtime import mouse_move_fixer
from utils.match.smart_image_matcher import normalize_match_image
from tasks.task_utils import (
    capture_window_smart as capture_window_wgc,
    capture_and_match_template_smart,
)

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

        try:
            client_coords_for_child = (found_client_x, found_client_y)
            flags = win32con.CWP_SKIPINVISIBLE | win32con.CWP_SKIPDISABLED | win32con.CWP_SKIPTRANSPARENT
            child_hwnd = win32gui.ChildWindowFromPointEx(target_hwnd, client_coords_for_child, flags)
            if child_hwnd:
                specific_scroll_hwnd = child_hwnd
                logger.info(f"滚动目标句柄切换为子窗口: {specific_scroll_hwnd}")
        except Exception as hwnd_err:
            logger.warning(f"获取子窗口句柄失败，回退父窗口句柄: {hwnd_err}", exc_info=True)

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

    优先使用截图子进程匹配（主进程不持有截图大对象）；仅在无有效窗口句柄时回退本地截图。
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
            try:
                found_screen_x, found_screen_y = win32gui.ClientToScreen(target_hwnd, (center_x_client, center_y_client))
            except Exception:
                found_screen_x, found_screen_y = center_x_client, center_y_client

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
        try:
            return bool(stop_checker())
        except Exception as exc:
            logger.debug(f"[鼠标滚轮] 控制检查失败: {exc}")
            return False

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

    foreground_input = get_foreground_input_manager()
    if foreground_input and execution_mode and execution_mode.startswith('foreground'):
        foreground_input.set_execution_mode(execution_mode)
        logger.info(f"[鼠标模式] 前台模式 - {execution_mode}（滚动）")

    # Normalize execution mode to avoid mixing foreground/background
    original_execution_mode = execution_mode or ""
    normalized_mode = original_execution_mode.strip().lower()
    use_simple_background = normalized_mode == "background_postmessage"
    postmessage_coords_are_screen = False
    if normalized_mode.startswith("foreground"):
        normalized_mode = "foreground"
    elif normalized_mode.startswith("background"):
        normalized_mode = "background"
    elif normalized_mode.startswith("emulator_"):
        normalized_mode = "background"
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
    current_scroll_target_hwnd = target_hwnd

    raw_image_path = params.get('image_path') # 原始图片路径

    # 【闪退修复】路径纠正：自动从images目录匹配同名图片
    from tasks.task_utils import correct_single_image_path
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

            # 调试信息：显示所有相关参数
            logger.info(f"调试参数: scroll_start_position='{scroll_position}', coordinate_mode='{coordinate_mode}'")
            logger.info(f"调试参数: scroll_x={params.get('scroll_x')}, scroll_y={params.get('scroll_y')}")
            logger.info(f"调试参数: 所有参数键={list(params.keys())}")

            try:
                if isinstance(scroll_position, str) and ',' in scroll_position:
                    raw_x, raw_y = map(int, scroll_position.split(','))
                    logger.info(f"成功解析scroll_start_position: ({raw_x}, {raw_y})")
                else:
                    # 兼容旧版本的 scroll_x 和 scroll_y 参数
                    raw_x = int(params.get('scroll_x', 500))
                    raw_y = int(params.get('scroll_y', 300))
                    logger.info(f"使用scroll_x/scroll_y参数: ({raw_x}, {raw_y})")
            except (ValueError, TypeError) as e:
                logger.warning(f"无法解析滚动坐标: {scroll_position}，错误: {e}，使用默认值 (500, 300)")
                raw_x, raw_y = 500, 300

            # 直接使用客户区坐标，不进行转换
            target_x, target_y = raw_x, raw_y
            logger.info(f"使用客户区坐标: ({target_x}, {target_y}) (模式: {coordinate_mode}, 执行模式: {execution_mode})")

        elif location_mode == "窗口中心":
            logger.info("起始位置模式：窗口中心。计算窗口中心...")
            if target_hwnd:
                try:
                    if not win32gui.IsWindow(target_hwnd):
                        logger.warning(f"无法移至中心：目标窗口句柄 {target_hwnd} 无效。将在当前位置滚动。")
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
                    logger.warning(f"计算窗口中心时出错: {move_err}。将在当前位置滚动。")
                    target_x, target_y = None, None
            else:
                logger.warning("请求移至中心，但未提供目标窗口句柄。将在当前位置滚动。")
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

            # 【修复】使用全局配置绑定的窗口句柄，而不是临时的 current_scroll_target_hwnd
            scroll_hwnd = target_hwnd
            logger.info(f"执行后台鼠标滚轮: 滚动目标句柄={scroll_hwnd}, 坐标={(target_x, target_y) if target_x is not None else '默认'}, 方向='{direction}', 次数={scroll_count}")
            # 获取默认坐标（窗口屏幕中心，而不是客户区）
            if target_x is None or target_y is None:
                try:
                    rect = win32gui.GetWindowRect(scroll_hwnd)
                    target_x = (rect[0] + rect[2]) // 2
                    target_y = (rect[1] + rect[3]) // 2
                    postmessage_coords_are_screen = True
                except Exception:
                    target_x, target_y = 0, 0
                    postmessage_coords_are_screen = True

            logger.debug(
                f"后台滚轮参数: 方向={direction}, 单刻度值={scroll_value_per_unit}, "
                f"总步数={scroll_count}, 间隔={interval}"
            )

            # 【多层级支持】后台滚轮：使用增强型子窗口查找器
            # 查找从根窗口到鼠标坐标位置的完整窗口链

            window_chain = [scroll_hwnd]
            window_coords = {}
            screen_x = screen_y = None

            try:
                if target_x is not None and target_y is not None:
                    from utils.window.enhanced_child_window_finder import EnhancedChildWindowFinder

                    finder = EnhancedChildWindowFinder()
                    # 将客户区坐标转换为屏幕坐标（如果需要）
                    try:
                        if postmessage_coords_are_screen or coordinate_mode == '屏幕坐标':
                            screen_x, screen_y = int(target_x), int(target_y)
                        else:
                            screen_x, screen_y = win32gui.ClientToScreen(scroll_hwnd, (target_x, target_y))
                        logger.info(f"[坐标转换] 目标坐标 -> 屏幕({screen_x}, {screen_y})")
                    except Exception:
                        screen_x, screen_y = target_x, target_y
                        logger.info(f"[坐标转换] 转换失败，使用原坐标({screen_x}, {screen_y})")
                    # 查找完整的窗口链：返回 (deepest_hwnd, chain_list, client_coords)
                    deepest_hwnd, chain_dicts, client_coords = finder.find_deepest_child(
                        scroll_hwnd, screen_x, screen_y
                    )

                    if chain_dicts and len(chain_dicts) > 0:
                        # chain_dicts 是字典列表，每个字典包含 'hwnd' 和坐标信息
                        window_chain = [c['hwnd'] for c in chain_dicts if 'hwnd' in c]
                        if window_chain:
                            logger.info(f"[多层级查找] 找到 {len(window_chain)} 层窗口链")
                            for i, c in enumerate(chain_dicts):
                                hwnd = c.get('hwnd')
                                if not hwnd:
                                    continue
                                client_x = c.get('client_x')
                                client_y = c.get('client_y')
                                if client_x is None or client_y is None:
                                    try:
                                        client_x, client_y = win32gui.ScreenToClient(hwnd, (screen_x, screen_y))
                                    except Exception:
                                        client_x, client_y = target_x, target_y
                                window_coords[hwnd] = (screen_x, screen_y)
                                logger.info(
                                    f"  第{i+1}层 0x{hwnd:08X}: 客户区坐标({client_x}, {client_y})"
                                )
                        else:
                            logger.debug("[多层级查找] 链路为空，使用原始窗口")
                            if postmessage_coords_are_screen or coordinate_mode == '屏幕坐标':
                                try:
                                    base_x, base_y = win32gui.ScreenToClient(scroll_hwnd, (screen_x, screen_y))
                                except Exception:
                                    base_x, base_y = target_x, target_y
                            else:
                                base_x, base_y = target_x, target_y
                            window_coords[scroll_hwnd] = (screen_x, screen_y)
                    else:
                        logger.debug("[多层级查找] 未找到多层窗口，使用原始窗口")
                        if postmessage_coords_are_screen or coordinate_mode == '屏幕坐标':
                            try:
                                base_x, base_y = win32gui.ScreenToClient(scroll_hwnd, (screen_x, screen_y))
                            except Exception:
                                base_x, base_y = target_x, target_y
                        else:
                            base_x, base_y = target_x, target_y
                        window_coords[scroll_hwnd] = (screen_x, screen_y)
                    if scroll_hwnd not in window_coords:
                        if postmessage_coords_are_screen or coordinate_mode == '屏幕坐标':
                            try:
                                base_x, base_y = win32gui.ScreenToClient(scroll_hwnd, (screen_x, screen_y))
                            except Exception:
                                base_x, base_y = target_x, target_y
                        else:
                            base_x, base_y = target_x, target_y
                        window_coords[scroll_hwnd] = (screen_x, screen_y)
            except ImportError:
                if screen_x is None or screen_y is None:
                    try:
                        if postmessage_coords_are_screen or coordinate_mode == '屏幕坐标':
                            screen_x, screen_y = int(target_x), int(target_y)
                        else:
                            screen_x, screen_y = win32gui.ClientToScreen(scroll_hwnd, (target_x, target_y))
                    except Exception:
                        screen_x, screen_y = target_x, target_y
                logger.debug("[多层级查找] EnhancedChildWindowFinder 不可用，使用原始窗口")
                if postmessage_coords_are_screen or coordinate_mode == '屏幕坐标':
                    try:
                        base_x, base_y = win32gui.ScreenToClient(scroll_hwnd, (target_x, target_y))
                    except Exception:
                        base_x, base_y = target_x, target_y
                else:
                    base_x, base_y = target_x, target_y
                window_coords[scroll_hwnd] = (screen_x, screen_y)
            except Exception as chain_find_err:
                if screen_x is None or screen_y is None:
                    try:
                        if postmessage_coords_are_screen or coordinate_mode == '屏幕坐标':
                            screen_x, screen_y = int(target_x), int(target_y)
                        else:
                            screen_x, screen_y = win32gui.ClientToScreen(scroll_hwnd, (target_x, target_y))
                    except Exception:
                        screen_x, screen_y = target_x, target_y
                logger.debug(f"[多层级查找] 失败: {chain_find_err}，使用原始窗口")
                if postmessage_coords_are_screen or coordinate_mode == '屏幕坐标':
                    try:
                        base_x, base_y = win32gui.ScreenToClient(scroll_hwnd, (target_x, target_y))
                    except Exception:
                        base_x, base_y = target_x, target_y
                else:
                    base_x, base_y = target_x, target_y
                window_coords[scroll_hwnd] = (screen_x, screen_y)

            # 执行滚轮操作
            try:
                logged_hwnds = set()
                for i in range(scroll_count):
                    if _control_requested():
                        return False, f'任务已停止 (滚动 {i+1})', None

                    send_targets = window_chain

                    logger.info(
                        f"  执行后台滚轮 {i+1}/{scroll_count}, 单步delta={scroll_value_per_unit}, "
                        f"向 {len(send_targets)} 层窗口发送消息"
                    )
                    try:
                        # 【向完整窗口链发送消息】
                        # 遍历所有窗口层级，从根窗口到最深层子窗口都尝试发送消息
                        for target_hwnd in send_targets:
                            if _control_requested():
                                return False, f'任务已停止 (滚动 {i+1})', None
                            if not win32gui.IsWindow(target_hwnd):
                                logger.info(f"  窗口 0x{target_hwnd:08X} 已失效，跳过")
                                continue

                            # 获取该窗口对应的坐标
                            coord_x, coord_y = window_coords.get(target_hwnd, (target_x, target_y))

                            try:
                                class_name = ""
                                if target_hwnd not in logged_hwnds:
                                    try:
                                        class_name = win32gui.GetClassName(target_hwnd)
                                    except Exception:
                                        class_name = ""
                                    if class_name:
                                        logger.info(f"[后台] 目标控件类名: {class_name}")
                                    else:
                                        logger.info("[后台] 目标控件类名: <unknown>")
                                    logged_hwnds.add(target_hwnd)
                                else:
                                    try:
                                        class_name = win32gui.GetClassName(target_hwnd)
                                    except Exception:
                                        class_name = ""

                                send_timeout = getattr(win32gui, "SendMessageTimeout", None)

                                def _send_message(msg, wparam, lparam):
                                    if use_simple_background:
                                        return win32gui.PostMessage(target_hwnd, msg, wparam, lparam)
                                    if send_timeout:
                                        return send_timeout(
                                            target_hwnd,
                                            msg,
                                            wparam,
                                            lparam,
                                            win32con.SMTO_ABORTIFHUNG,
                                            200,
                                        )
                                    return win32gui.SendMessage(target_hwnd, msg, wparam, lparam)

                                direction_down = direction == '向下'
                                delta_lines = 1 if direction_down else -1

                                edit_classes = {
                                    "Edit",
                                    "RICHEDIT50W",
                                    "RICHEDIT50A",
                                    "RichEdit20W",
                                    "RichEdit20A",
                                }

                                if class_name in edit_classes:
                                    result = _send_message(win32con.EM_LINESCROLL, 0, delta_lines)
                                    logger.info(
                                        f"  向窗口 0x{target_hwnd:08X} 发送EM_LINESCROLL, "
                                        f"lines={delta_lines}, 返回值: {result}"
                                    )
                                    continue

                                if class_name == "ListBox":
                                    top_index = _send_message(win32con.LB_GETTOPINDEX, 0, 0)
                                    if isinstance(top_index, tuple):
                                        top_index = top_index[0]
                                    if top_index is None:
                                        top_index = 0
                                    new_top = max(0, int(top_index) + delta_lines)
                                    result = _send_message(win32con.LB_SETTOPINDEX, new_top, 0)
                                    logger.info(
                                        f"  向窗口 0x{target_hwnd:08X} 发送LB_SETTOPINDEX, "
                                        f"top={new_top}, 返回值: {result}"
                                    )
                                    continue

                                if class_name == "SysListView32":
                                    lvm_scroll = 0x1014
                                    dy = 30 if direction_down else -30
                                    result = _send_message(lvm_scroll, 0, dy)
                                    logger.info(
                                        f"  向窗口 0x{target_hwnd:08X} 发送LVM_SCROLL, "
                                        f"dy={dy}, 返回值: {result}"
                                    )
                                    continue

                                if class_name == "SysTreeView32":
                                    tvm_scroll = 0x1114
                                    dy = 30 if direction_down else -30
                                    result = _send_message(tvm_scroll, 0, dy)
                                    logger.info(
                                        f"  向窗口 0x{target_hwnd:08X} 发送TVM_SCROLL, "
                                        f"dy={dy}, 返回值: {result}"
                                    )
                                    continue

                                screen_pt_x = int(coord_x)
                                screen_pt_y = int(coord_y)
                                try:
                                    client_x, client_y = win32gui.ScreenToClient(
                                        target_hwnd, (screen_pt_x, screen_pt_y)
                                    )
                                except Exception:
                                    client_x, client_y = screen_pt_x, screen_pt_y

                                lparam_move = win32api.MAKELONG(client_x & 0xFFFF, client_y & 0xFFFF)
                                lparam_wheel = win32api.MAKELONG(screen_pt_x & 0xFFFF, screen_pt_y & 0xFFFF)

                                wparam = win32api.MAKELONG(0, int(scroll_value_per_unit))
                                _send_message(win32con.WM_MOUSEMOVE, 0, lparam_move)
                                sleep_ok, stop_result = _sleep_with_control(0.005, "[后台鼠标滚轮] 发送前等待期间检测到暂停/停止请求")
                                if not sleep_ok:
                                    return stop_result

                                result = _send_message(win32con.WM_MOUSEWHEEL, wparam, lparam_wheel)
                                logger.info(
                                    f"  向窗口 0x{target_hwnd:08X} 发送WM_MOUSEWHEEL, "
                                    f"坐标({coord_x}, {coord_y}), delta={scroll_value_per_unit}, 返回值: {result}"
                                )
                            except Exception as hwnd_err:
                                logger.info(f"  向窗口 0x{target_hwnd:08X} 发送失败: {hwnd_err}")
                                continue
                        sleep_ok, stop_result = _sleep_with_control(0.02, "[后台鼠标滚轮] 单次滚动收尾等待期间检测到暂停/停止请求")
                        if not sleep_ok:
                            return stop_result
                    except Exception as scroll_err:
                        logger.warning(f"后台滚轮第 {i+1} 次操作时出错: {scroll_err}")
                        continue

                    if scroll_count > 1 and i < scroll_count - 1 and interval > 0:
                        sleep_chunk = 0.05
                        remaining_sleep = interval
                        while remaining_sleep > 0:
                            actual_sleep = min(sleep_chunk, remaining_sleep)
                            sleep_ok, stop_result = _sleep_with_control(actual_sleep, "后台鼠标滚轮任务在 interval sleep 期间被请求停止。")
                            if not sleep_ok:
                                return stop_result
                            remaining_sleep -= actual_sleep
            except Exception as background_err:
                logger.exception(f"后台鼠标滚轮操作时发生错误: {background_err}")
                return False, '执行下一步', None
            logger.info("后台鼠标滚轮操作完成。")
            from .task_utils import handle_success_action
            return handle_success_action(params, kwargs.get('card_id'), kwargs.get('stop_checker'))

        else: # Foreground
            mode_description = "前台"
            logger.info(f"执行{mode_description}鼠标滚轮: 目标屏幕坐标={(target_x, target_y) if target_x is not None else '当前'}, 方向='{direction}', 次数={scroll_count}")
            
            # 前台模式：激活目标窗口确保滚轮生效
            if target_hwnd:
                try:
                    if win32gui.IsWindow(target_hwnd):
                        logger.debug(f"前台模式：激活目标窗口 {target_hwnd}")
                        win32gui.SetForegroundWindow(target_hwnd)
                        sleep_ok, stop_result = _sleep_with_control(0.1, "[前台鼠标滚轮] 窗口激活等待期间检测到暂停/停止请求")
                        if not sleep_ok:
                            return stop_result
                except Exception as activate_err:
                    logger.debug(f"激活目标窗口时出错: {activate_err}，继续执行滚轮操作")
            
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
                    logger.warning(f"前台滚轮第 {i+1} 次操作时出错: {scroll_err}")
                    continue
                
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
