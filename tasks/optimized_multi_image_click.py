"""多图识别：并行匹配后点击，不做预处理，不改走串行。"""

import time
import logging
from typing import Dict, Any, Optional, Tuple, List
from .parallel_image_recognition import get_parallel_recognizer, RecognitionMode, RecognitionResult
from tasks.multi_image_memory import (
    as_path_set,
    finish_multi_image_round,
    mark_multi_image_round_active,
    resolve_multi_image_flag,
    resolve_multi_image_remaining,
)
from tasks.task_utils import coerce_bool, interruptible_sleep

logger = logging.getLogger(__name__)


def _is_stop_requested(stop_checker=None) -> bool:
    if not callable(stop_checker):
        return False
    try:
        return bool(stop_checker())
    except Exception:
        return False


def _stop_result() -> Tuple[bool, str, Optional[int]]:
    return False, '停止工作流', None


def _sleep_with_stop(duration: float, stop_checker=None) -> bool:
    try:
        safe_duration = max(0.0, float(duration or 0.0))
    except Exception:
        safe_duration = 0.0
    if safe_duration <= 0.0:
        return not _is_stop_requested(stop_checker)
    interruptible_sleep(safe_duration, stop_checker)
    return not _is_stop_requested(stop_checker)

def execute_multi_image_click_optimized(params: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                                      card_id: Optional[int], get_image_data, on_success_action: str,
                                      success_jump_id: Optional[int], on_failure_action: str,
                                      failure_jump_id: Optional[int], stop_checker=None) -> Tuple[bool, str, Optional[int]]:
    """
    优化的多图片点击执行函数 - 并行处理版本
    
    主要优化：
    1. 并行图片识别：多张图片同时处理
    2. 智能截图复用：避免重复截图
    3. 批量点击处理：减少延迟累积
    4. 错误隔离：单张失败不影响其他
    """
    try:
        from task_workflow.workflow_context import get_workflow_context

        context = get_workflow_context()
        start_time = time.time()

        if _is_stop_requested(stop_checker):
            return _stop_result()

        # 获取参数
        from task_workflow.resource_path import format_resource_text

        image_paths_text = format_resource_text(params.get('image_paths', ''))
        click_all_found = resolve_multi_image_flag(params, 'click_all_found', False)
        clear_clicked_on_next_run = resolve_multi_image_flag(params, 'clear_clicked_on_next_run', False)

        if not image_paths_text:
            logger.error("多图识别模式下未配置图片路径")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        # 解析和验证图片路径
        image_paths = _parse_and_validate_image_paths(image_paths_text, card_id)
        if not image_paths:
            logger.error("多图识别模式下所有图片路径都无效")
            # 显示错误对话框提示用户
            raw_paths = [path.strip() for path in image_paths_text.split('\n') if path.strip()]
            _show_no_images_found_dialog(raw_paths)
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        logger.info(f"[多图识别] 开始并行识别，共{len(image_paths)}张图片，全部点击: {click_all_found}")

        remaining_images = resolve_multi_image_remaining(
            image_paths,
            card_id,
            click_all_found,
            context,
            clear_clicked_on_next_run=clear_clicked_on_next_run,
        )
        if not remaining_images:
            logger.error("多图识别模式下没有可处理的图片")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        recognition_results = _execute_parallel_recognition(
            remaining_images,
            params,
            execution_mode,
            target_hwnd,
            get_image_data,
            stop_checker,
        )

        if _is_stop_requested(stop_checker):
            return _stop_result()

        # 处理识别结果
        return _process_recognition_results(
            recognition_results, image_paths, params, execution_mode, target_hwnd,
            click_all_found, card_id, context, on_success_action, success_jump_id,
            on_failure_action, failure_jump_id, start_time, stop_checker
        )

    except Exception as e:
        logger.error(f"优化多图识别执行异常: {e}", exc_info=True)
        return _handle_failure(on_failure_action, failure_jump_id, card_id)

def _parse_and_validate_image_paths(image_paths_text: str, card_id: Optional[int]) -> List[str]:
    """解析和验证图片路径"""
    try:
        # 解析路径列表
        raw_paths = [path.strip() for path in image_paths_text.split('\n') if path.strip()]
        if not raw_paths:
            return []

        # 智能纠正路径
        from tasks.mouse_action_task import _correct_image_paths
        corrected_paths = _correct_image_paths(raw_paths)

        logger.debug(f"[路径解析] 原始: {len(raw_paths)}, 有效: {len(corrected_paths)}")
        return corrected_paths

    except Exception as e:
        logger.error(f"解析图片路径失败: {e}")
        return []

def _show_no_images_found_dialog(raw_paths: List[str]):
    """显示未找到图片的错误对话框 (从mouse_action_task导入)"""
    try:
        from tasks.mouse_action_task import _show_no_images_found_dialog as show_dialog
        show_dialog(raw_paths)
    except Exception as e:
        logger.error(f"显示错误对话框失败: {e}")

def _execute_parallel_recognition(image_paths: List[str], params: Dict[str, Any],
                                execution_mode: str, target_hwnd: Optional[int],
                                get_image_data=None, stop_checker=None) -> List[RecognitionResult]:
    """执行并行图片识别"""
    try:
        if _is_stop_requested(stop_checker):
            return []
        recognizer = get_parallel_recognizer()
        
        # 根据点击模式选择识别策略
        click_all_found = resolve_multi_image_flag(params, 'click_all_found', False)
        mode = RecognitionMode.ALL_MATCHES if click_all_found else RecognitionMode.FIRST_MATCH
        
        logger.info(f"[并行识别] 开始处理{len(image_paths)}张图片，模式={mode.value}")
        
        results = recognizer.recognize_images_parallel(
            image_paths=image_paths,
            params=params,
            execution_mode=execution_mode,
            target_hwnd=target_hwnd,
            mode=mode,
            get_image_data=get_image_data,
            stop_checker=stop_checker,
        )
        
        success_count = sum(1 for r in results if r.success)
        total_time = sum(r.processing_time for r in results)
        avg_time = total_time / len(results) if results else 0
        
        logger.info(f"[并行识别] 完成: {success_count}/{len(image_paths)}张成功，平均耗时={avg_time:.2f}s")
        return results
        
    except Exception as e:
        logger.error(f"并行识别失败: {e}")
        return []

def _process_recognition_results(recognition_results: List[RecognitionResult], 
                               image_paths: List[str], params: Dict[str, Any],
                               execution_mode: str, target_hwnd: Optional[int],
                               click_all_found: bool, card_id: Optional[int], context,
                               on_success_action: str, success_jump_id: Optional[int],
                               on_failure_action: str, failure_jump_id: Optional[int],
                               start_time: float, stop_checker=None) -> Tuple[bool, str, Optional[int]]:
    """处理识别结果并执行点击"""
    if _is_stop_requested(stop_checker):
        return _stop_result()
    
    if not recognition_results:
        logger.error("[结果处理] 没有识别结果")
        return _handle_failure(on_failure_action, failure_jump_id, card_id)
    
    # 筛选成功的结果。非“全部点击”模式无论并行任务完成顺序如何，
    # 都只能消费一个成功结果，避免多个并发 future 同时命中而被全部点击。
    successful_results = [r for r in recognition_results if r.success]
    if not click_all_found and successful_results:
        successful_results = [min(successful_results, key=lambda result: int(result.index))]
    
    if not successful_results:
        logger.warning(f"[结果处理] 所有图片识别失败: {len(recognition_results)}张")
        return _handle_all_failed(recognition_results, image_paths, click_all_found, card_id, context, on_failure_action, failure_jump_id)
    
    # 执行点击操作
    click_results = _execute_clicks_for_results(
        successful_results,
        params,
        execution_mode,
        target_hwnd,
        stop_checker,
    )

    if _is_stop_requested(stop_checker):
        return _stop_result()
    
    # 更新上下文记录
    _update_context_records(successful_results, click_results, card_id, context, click_all_found)
    
    # 判断最终结果
    total_time = time.time() - start_time
    return _determine_final_result(
        successful_results, click_results, image_paths, click_all_found,
        card_id, context, on_success_action, success_jump_id,
        on_failure_action, failure_jump_id, total_time
    )

def _execute_clicks_for_results(results: List[RecognitionResult], params: Dict[str, Any],
                               execution_mode: str, target_hwnd: Optional[int], stop_checker=None) -> List[bool]:
    """为识别成功的图片执行点击"""
    click_results = []
    enable_click = coerce_bool(params.get('image_enable_click', True))

    for result in results:
        if _is_stop_requested(stop_checker):
            break
        try:
            if not enable_click:
                logger.info(f"[点击执行] 仅识别模式，跳过点击: {result.image_name}")
                click_results.append(True)
                continue

            if result.center_x is None or result.center_y is None:
                logger.error(f"[点击执行] 识别成功但没有坐标: {result.image_name}")
                click_results.append(False)
                continue

            success = _execute_single_click(
                result.center_x,
                result.center_y,
                params,
                execution_mode,
                target_hwnd,
                stop_checker,
            )

            click_results.append(success)

            if success:
                logger.info(f"[点击执行] 成功点击: {result.image_name}")
                # 添加点击间隔
                click_delay = params.get('interval', 0.1)
                if click_delay > 0:
                    if not _sleep_with_stop(click_delay, stop_checker):
                        break
            else:
                logger.warning(f"[点击执行] 点击失败: {result.image_name}")

        except Exception as e:
            logger.error(f"点击执行异常: {result.image_name}, 错误: {e}")
            click_results.append(False)

    return click_results

def _execute_single_click(x: int, y: int, params: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int], stop_checker=None) -> bool:
    """执行单次点击

    注意：坐标点击模块(click_coordinate)会自动处理偏移,这里只需传递原始中心点坐标和偏移参数
    """
    try:
        from tasks.click_coordinate import execute_task as execute_click
        from tasks.click_param_resolver import resolve_click_params

        # 获取点击位置模式和偏移参数
        position_mode = params.get('image_position_mode', '精准坐标')
        click_button, click_count, click_interval, click_action, enable_auto_release, hold_duration = resolve_click_params(
            params,
            button_key="button",
            clicks_key="clicks",
            interval_key="interval",
            action_key="image_click_action",
            auto_release_key="image_enable_auto_release",
            hold_duration_key="image_hold_duration",
            hold_mode_key="image_hold_mode",
            hold_min_key="image_hold_duration_min",
            hold_max_key="image_hold_duration_max",
            mode_label="多图点击",
            logger_obj=logger,
            log_hold_mode=False,
        )
        logger.info(f"[多图点击] 位置模式: {position_mode}, 中心坐标: ({x}, {y})")

        # 根据位置模式设置偏移参数(不手动计算,交给click_coordinate处理)
        if position_mode == '固定偏移':
            fixed_offset_x = params.get('image_fixed_offset_x', 0)
            fixed_offset_y = params.get('image_fixed_offset_y', 0)
            random_offset_x = params.get('image_random_offset_x', 5)
            random_offset_y = params.get('image_random_offset_y', 5)
            coordinate_position_mode = '固定偏移'
            logger.info(f"[多图点击] 固定偏移模式: 中心({x},{y}), 偏移({fixed_offset_x},{fixed_offset_y})")
        elif position_mode == '随机偏移':
            fixed_offset_x = 0
            fixed_offset_y = 0
            random_offset_x = params.get('image_random_offset_x', 5)
            random_offset_y = params.get('image_random_offset_y', 5)
            coordinate_position_mode = '随机偏移'
            logger.info(f"[多图点击] 随机偏移模式: 中心({x},{y}), X范围={random_offset_x}, Y范围={random_offset_y})")
        else:  # 精准坐标
            fixed_offset_x = 0
            fixed_offset_y = 0
            random_offset_x = 0
            random_offset_y = 0
            coordinate_position_mode = '精准坐标'
            logger.info(f"[多图点击] 精准坐标模式: 中心({x},{y}), 无偏移")

        click_params = {
            'coordinate_x': x,
            'coordinate_y': y,
            'coordinate_mode': '客户区坐标',
            'position_mode': coordinate_position_mode,  # 关键：传递位置模式
            'button': click_button,
            'clicks': click_count,
            'interval': click_interval,
            'click_action': click_action,
            'enable_auto_release': enable_auto_release,
            'hold_duration': hold_duration,
            'fixed_offset_x': fixed_offset_x,
            'fixed_offset_y': fixed_offset_y,
            'random_offset_x': random_offset_x,
            'random_offset_y': random_offset_y
        }

        success, _, _ = execute_click(
            click_params,
            {},
            execution_mode,
            target_hwnd,
            None,
            None,
            stop_checker=stop_checker,
        )
        return success

    except Exception as e:
        logger.error(f"执行点击失败: ({x}, {y}), 错误: {e}")
        return False

def _update_context_records(results: List[RecognitionResult], click_results: List[bool], 
                          card_id: Optional[int], context, click_all_found: bool):
    """更新上下文记录"""
    if card_id is None:
        return
    
    clicked_images = as_path_set(context.get_card_data(card_id, 'clicked_images', set()))
    success_images = as_path_set(context.get_card_data(card_id, 'success_images', set()))
    
    for result, click_success in zip(results, click_results):
        if click_all_found:
            # 全部点击模式：只记录成功的
            if click_success:
                success_images.add(result.image_path)
        else:
            # 单次点击模式：记录所有尝试的
            clicked_images.add(result.image_path)
            if click_success:
                success_images.add(result.image_path)
    
    context.set_card_data(card_id, 'clicked_images', clicked_images)
    context.set_card_data(card_id, 'success_images', success_images)

def _handle_success(on_success_action: str, success_jump_id: Optional[int], card_id: Optional[int]) -> Tuple[bool, str, Optional[int]]:
    """处理成功情况"""
    from tasks.mouse_action_task import _handle_success as original_handle_success
    return original_handle_success(on_success_action, success_jump_id, card_id)

def _handle_failure(on_failure_action: str, failure_jump_id: Optional[int], card_id: Optional[int]) -> Tuple[bool, str, Optional[int]]:
    """处理失败情况"""
    from tasks.mouse_action_task import _handle_failure as original_handle_failure
    return original_handle_failure(on_failure_action, failure_jump_id, card_id)

def _handle_all_failed(results: List[RecognitionResult], image_paths: List[str], 
                      click_all_found: bool, card_id: Optional[int], context,
                      on_failure_action: str, failure_jump_id: Optional[int]) -> Tuple[bool, str, Optional[int]]:
    """处理全部失败情况"""
    logger.warning("[优化多图识别] 所有图片识别失败")
    if click_all_found and on_failure_action == '继续执行本步骤':
        mark_multi_image_round_active(context, card_id)
    else:
        finish_multi_image_round(context, card_id)
    return _handle_failure(on_failure_action, failure_jump_id, card_id)

def _determine_final_result(successful_results: List[RecognitionResult], click_results: List[bool],
                          image_paths: List[str], click_all_found: bool, card_id: Optional[int], context,
                          on_success_action: str, success_jump_id: Optional[int],
                          on_failure_action: str, failure_jump_id: Optional[int],
                          total_time: float) -> Tuple[bool, str, Optional[int]]:
    """确定最终结果"""
    
    successful_clicks = sum(click_results)
    
    logger.info(f"[优化多图识别] 总结: 识别成功{len(successful_results)}张，点击成功{successful_clicks}张，总耗时{total_time:.2f}s")
    
    if click_all_found:
        # 全部点击模式
        all_success_images = as_path_set(context.get_card_data(card_id, 'success_images', set()))
        if len(all_success_images) == len(image_paths):
            finish_multi_image_round(context, card_id)
            return _handle_success(on_success_action, success_jump_id, card_id)
        mark_multi_image_round_active(context, card_id)
        return True, '继续执行本步骤', card_id

    if successful_clicks > 0:
        finish_multi_image_round(context, card_id)
        return _handle_success(on_success_action, success_jump_id, card_id)

    mark_multi_image_round_active(context, card_id)
    return True, '继续执行本步骤', card_id
