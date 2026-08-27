# -*- coding: utf-8 -*-
"""点阵字库 OCR 任务：兼容大漠/OP 字库，结果写入与 OCR文字识别相同的上下文。"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from tasks.ocr_region_recognition import (
    CAPTURE_AVAILABLE,
    PYWIN32_AVAILABLE,
    _align_window_image_to_client_area,
    _cache_ocr_result_snapshot,
    _capture_window_for_ocr,
    _check_target_text_with_position,
    _extract_effective_ocr_roi,
    _format_ocr_text_preview,
    _handle_failure,
    _handle_success,
    _remember_ocr_source_for_jump,
    _resolve_region_params,
    _should_save_ocr_context,
)
from tasks.task_utils import get_recorded_region_binding_mismatch_detail

try:
    import win32gui
except ImportError:
    win32gui = None

logger = logging.getLogger(__name__)

TASK_TYPE = "点阵字库OCR"
TASK_NAME = "点阵字库OCR"


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _window_title(hwnd: Optional[int]) -> str:
    if not hwnd or win32gui is None:
        return f"HWND_{hwnd or 0}"
    try:
        title = win32gui.GetWindowText(int(hwnd))
        return title or f"HWND_{hwnd}"
    except Exception:
        return f"HWND_{hwnd}"


def _load_library(params: Dict[str, Any]):
    from services.dict_ocr_service import load_dict_library

    dict_file = str(params.get("dict_file") or "").strip()
    if not dict_file:
        raise ValueError("未选择字库文件")
    return load_dict_library(dict_file)


def _recognize_region(roi_image, params: Dict[str, Any], library) -> List[Dict[str, Any]]:
    from services.dict_ocr_service import recognize_or_find

    target_text = str(params.get("target_text") or "")
    color_format = str(params.get("color_format") or "")
    similarity = _safe_float(params.get("similarity", 0.9), 0.9)
    results = recognize_or_find(
        image=roi_image,
        library=library,
        target_text=target_text,
        color_format=color_format,
        similarity=similarity,
    )
    return [item for item in results if isinstance(item, dict)]


def _match_dict_target(
    results: List[Dict[str, Any]],
    target_text: str,
    match_mode: str,
) -> Tuple[bool, Optional[dict]]:
    targets = [part.strip() for part in re.split(r"[|｜]", str(target_text or "")) if part.strip()]
    if not targets:
        return _check_target_text_with_position(results, "", match_mode)
    for target in targets:
        found, matched = _check_target_text_with_position(results, target, match_mode)
        if found:
            return True, matched
    return False, None


def _save_ocr_context(
    card_id: Optional[int],
    params: Dict[str, Any],
    results: List[Dict[str, Any]],
    target_text: str,
    match_mode: str,
    final_x: int,
    final_y: int,
    target_hwnd: Optional[int],
    success_jump_id: Any,
) -> None:
    if not _should_save_ocr_context(card_id, params):
        return
    try:
        from task_workflow.workflow_context import get_workflow_context, set_ocr_results

        set_ocr_results(card_id, results)
        context = get_workflow_context()
        context.set_card_data(card_id, "ocr_target_text", target_text)
        context.set_card_data(card_id, "ocr_match_mode", match_mode)
        context.set_card_data(card_id, "ocr_region_offset", (final_x, final_y))
        context.set_card_data(card_id, "ocr_window_hwnd", target_hwnd)
        _remember_ocr_source_for_jump(context, success_jump_id, card_id)
    except Exception:
        logger.debug("[字库OCR] 写入识别上下文失败", exc_info=True)


def execute_task(
    params: Dict[str, Any],
    counters: Dict[str, int],
    execution_mode: str,
    target_hwnd: Optional[int],
    window_region: Optional[Tuple[int, int, int, int]],
    card_id: Optional[int] = None,
    **kwargs,
) -> Tuple[bool, str, Optional[int]]:
    stop_checker = kwargs.get("stop_checker")
    region_mode, region_x, region_y, region_width, region_height = _resolve_region_params(params)
    target_text = str(params.get("target_text") or "")
    match_mode = str(params.get("match_mode") or "包含")
    on_success_action = params.get("on_success", "执行下一步")
    success_jump_id = params.get("success_jump_target_id")
    on_failure_action = params.get("on_failure", "执行下一步")
    failure_jump_id = params.get("failure_jump_target_id")

    def fail(detail: str):
        try:
            from task_workflow.workflow_context import get_workflow_context

            get_workflow_context().clear_card_ocr_context(card_id)
        except Exception:
            pass
        return _handle_failure(
            on_failure_action,
            failure_jump_id,
            card_id,
            stop_checker,
            params,
            detail=detail,
        )

    if stop_checker and stop_checker():
        return False, "停止工作流", None

    if region_mode == "指定区域":
        binding_mismatch_detail = get_recorded_region_binding_mismatch_detail(params, target_hwnd)
        if binding_mismatch_detail:
            logger.error("[字库OCR] %s", binding_mismatch_detail)
            return fail(binding_mismatch_detail)

    if not target_hwnd or not PYWIN32_AVAILABLE or win32gui is None:
        return fail(f"需要有效的窗口句柄 (句柄: {target_hwnd})")
    if not win32gui.IsWindow(int(target_hwnd)):
        return fail(f"窗口句柄无效: {target_hwnd}")
    if win32gui.IsIconic(int(target_hwnd)):
        return fail("目标窗口已最小化")
    if not CAPTURE_AVAILABLE:
        return fail("截图引擎不可用")

    try:
        library = _load_library(params)
    except Exception as exc:
        return fail(str(exc))

    try:
        from task_workflow.workflow_context import get_workflow_context

        get_workflow_context().clear_card_ocr_context(card_id)
    except Exception:
        pass

    window_image = _capture_window_for_ocr(int(target_hwnd), timeout=4.0)
    if window_image is None:
        return fail(f"截图失败，窗口句柄={target_hwnd}")
    window_image = _align_window_image_to_client_area(window_image, target_hwnd)
    if window_image is None or window_image.size == 0:
        return fail(f"截图数据无效，窗口句柄={target_hwnd}")

    roi_image, final_x, final_y, _final_w, _final_h, region_desc = _extract_effective_ocr_roi(
        window_image=window_image,
        region_mode=region_mode,
        region_x=region_x,
        region_y=region_y,
        region_width=region_width,
        region_height=region_height,
        fallback_log_prefix="[字库OCR]",
    )
    if roi_image is None or roi_image.size == 0:
        return fail(f"无法提取识别区域: {region_desc}")

    if stop_checker and stop_checker():
        return False, "停止工作流", None

    try:
        results = _recognize_region(roi_image, params, library)
    except Exception as exc:
        logger.error("[字库OCR] 识别失败: %s", exc, exc_info=True)
        return fail(f"字库识别失败: {exc}")

    _cache_ocr_result_snapshot(
        card_id,
        results,
        target_text=target_text,
        match_mode=match_mode,
        region_offset=(final_x, final_y),
        window_hwnd=target_hwnd,
    )

    found_target, _matched = _match_dict_target(results, target_text, match_mode)
    if not found_target:
        preview = _format_ocr_text_preview(results)
        if target_text:
            detail = f"未匹配到目标文字，匹配方式={match_mode}，目标='{target_text}'，识别结果={preview}"
        else:
            detail = "字库未识别到任何文字"
        return fail(detail)

    if on_success_action == "继续执行本步骤":
        try:
            from task_workflow.workflow_context import get_workflow_context

            get_workflow_context().clear_card_ocr_context(card_id)
        except Exception:
            pass
    else:
        _save_ocr_context(
            card_id,
            params,
            results,
            target_text,
            match_mode,
            final_x,
            final_y,
            target_hwnd,
            success_jump_id,
        )
    return _handle_success(on_success_action, success_jump_id, card_id, stop_checker, params)


def get_params_definition() -> Dict[str, Dict[str, Any]]:
    return {
        "---dict_settings---": {"type": "separator", "label": "字库设置"},
        "dict_file": {
            "label": "字库文件",
            "type": "file",
            "default": "",
            "required": True,
            "file_filter": "字库文件 (*.txt *.dict);;所有文件 (*.*)",
            "tooltip": "支持大漠文本字库（HEX$字$左.右.数量$高度）、OP 文本字库和 OP 二进制 .dict",
        },
        "open_dict_maker_button": {
            "label": "制作字库",
            "type": "button",
            "button_text": "制作字库",
            "tooltip": "框选文字、点字取色、提取点阵并保存成大漠兼容字库，不需要大漠综合工具",
            "action": "open_dict_maker",
        },
        "color_format": {
            "label": "文字颜色",
            "type": "str",
            "default": "",
            "tooltip": "大漠颜色格式，例如 ffffff-101010 或 000000-000000|ffffff-101010。留空则自动二值化",
        },
        "similarity": {
            "label": "相似度",
            "type": "float",
            "default": 0.9,
            "min": 0.1,
            "max": 1.0,
            "step": 0.05,
            "tooltip": "点阵匹配阈值，对应大漠 Ocr/FindStr 的 sim，越高越严格",
        },
        "---region_settings---": {"type": "separator", "label": "识别区域设置"},
        "region_mode": {
            "label": "区域模式",
            "type": "select",
            "options": ["指定区域", "整个窗口"],
            "default": "指定区域",
            "tooltip": "选择识别范围",
        },
        "---coordinate_mode---": {
            "type": "separator",
            "label": "指定区域模式",
            "condition": {"param": "region_mode", "value": "指定区域"},
        },
        "ocr_region_selector_tool": {
            "label": "框选识别区域",
            "type": "button",
            "button_text": "框选识别指定区域",
            "tooltip": "在绑定窗口中框选识别区域",
            "condition": {"param": "region_mode", "value": "指定区域"},
            "widget_hint": "ocr_region_selector",
        },
        "region_coordinates": {
            "label": "指定的区域",
            "type": "text",
            "default": "未指定识别区域",
            "readonly": True,
            "tooltip": "由框选工具自动填写",
            "condition": {"param": "region_mode", "value": "指定区域"},
        },
        "region_x": {"type": "hidden", "default": 0, "condition": {"param": "region_mode", "value": "指定区域"}},
        "region_y": {"type": "hidden", "default": 0, "condition": {"param": "region_mode", "value": "指定区域"}},
        "region_width": {"type": "hidden", "default": 0, "condition": {"param": "region_mode", "value": "指定区域"}},
        "region_height": {"type": "hidden", "default": 0, "condition": {"param": "region_mode", "value": "指定区域"}},
        "region_hwnd": {"type": "hidden", "default": 0, "condition": {"param": "region_mode", "value": "指定区域"}},
        "region_window_title": {"type": "hidden", "default": "", "condition": {"param": "region_mode", "value": "指定区域"}},
        "region_window_class": {"type": "hidden", "default": "", "condition": {"param": "region_mode", "value": "指定区域"}},
        "region_client_width": {"type": "hidden", "default": 0, "condition": {"param": "region_mode", "value": "指定区域"}},
        "region_client_height": {"type": "hidden", "default": 0, "condition": {"param": "region_mode", "value": "指定区域"}},
        "test_dict_ocr_button": {
            "label": "测试识别",
            "type": "button",
            "button_text": "测试输出识别文字",
            "tooltip": "用当前字库、颜色和区域做一次识别，结果输出到记事本",
            "action": "test_dict_ocr_output",
        },
        "---target_text---": {"type": "separator", "label": "目标文字设置"},
        "target_text": {
            "label": "需要识别的文字",
            "type": "str",
            "default": "",
            "tooltip": "对应大漠 FindStr。留空则识别区域内全部字库文字；可用 | 表示“或”，例如 确定|取消",
        },
        "match_mode": {
            "label": "匹配模式",
            "type": "select",
            "options": ["包含", "完全匹配"],
            "default": "包含",
            "tooltip": "判断识别结果是否命中目标文字",
        },
        "---next_step_delay---": {"type": "separator", "label": "下一步延迟执行"},
        "enable_next_step_delay": {
            "label": "启用下一步延迟执行",
            "type": "bool",
            "default": False,
            "tooltip": "识别完成后等待一段时间再执行下一步",
        },
        "delay_mode": {
            "label": "延迟模式",
            "type": "select",
            "options": ["固定延迟", "随机延迟"],
            "default": "固定延迟",
            "tooltip": "选择固定或随机延迟",
            "condition": {"param": "enable_next_step_delay", "value": True},
        },
        "fixed_delay": {
            "label": "固定延迟 (秒)",
            "type": "float",
            "default": 0.2,
            "min": 0.0,
            "max": 60.0,
            "decimals": 2,
            "condition": {
                "param": "delay_mode",
                "value": "固定延迟",
                "and": {"param": "enable_next_step_delay", "value": True},
            },
        },
        "min_delay": {
            "label": "最小延迟 (秒)",
            "type": "float",
            "default": 0.1,
            "min": 0.0,
            "max": 60.0,
            "decimals": 2,
            "condition": {
                "param": "delay_mode",
                "value": "随机延迟",
                "and": {"param": "enable_next_step_delay", "value": True},
            },
        },
        "max_delay": {
            "label": "最大延迟 (秒)",
            "type": "float",
            "default": 0.4,
            "min": 0.0,
            "max": 60.0,
            "decimals": 2,
            "condition": {
                "param": "delay_mode",
                "value": "随机延迟",
                "and": {"param": "enable_next_step_delay", "value": True},
            },
        },
        "---post_execute---": {"type": "separator", "label": "执行后操作"},
        "on_success": {
            "type": "select",
            "label": "找到文字时",
            "options": ["执行下一步", "跳转到步骤", "停止工作流", "继续执行本步骤"],
            "default": "执行下一步",
        },
        "success_jump_target_id": {
            "type": "int",
            "label": "成功跳转目标 ID",
            "required": False,
            "widget_hint": "card_selector",
            "condition": {"param": "on_success", "value": "跳转到步骤"},
        },
        "on_failure": {
            "type": "select",
            "label": "未找到文字时",
            "options": ["执行下一步", "跳转到步骤", "停止工作流", "继续执行本步骤"],
            "default": "执行下一步",
        },
        "failure_jump_target_id": {
            "type": "int",
            "label": "失败跳转目标 ID",
            "required": False,
            "widget_hint": "card_selector",
            "condition": {"param": "on_failure", "value": "跳转到步骤"},
        },
    }


def open_dict_maker(params: Dict[str, Any], **kwargs) -> bool:
    from ui.dialogs.dict_maker_dialog import DictMakerDialog, apply_dict_maker_result_to_panel

    parent = kwargs.get("parameter_panel") or kwargs.get("main_window")
    dialog = DictMakerDialog(
        parent,
        target_hwnd=kwargs.get("target_hwnd"),
        params=params or {},
    )
    if dialog.exec():
        apply_dict_maker_result_to_panel(
            kwargs.get("parameter_panel"),
            dialog.saved_dict_path,
            dialog.saved_color_format,
        )
        return True
    return True


def test_dict_ocr_output(params: Dict[str, Any], **kwargs) -> bool:
    import subprocess
    import tempfile

    target_hwnd = kwargs.get("target_hwnd")
    try:
        if not target_hwnd:
            logger.error("[字库OCR测试] 未找到目标窗口句柄")
            return False
        binding_mismatch_detail = get_recorded_region_binding_mismatch_detail(params, target_hwnd)
        if binding_mismatch_detail:
            logger.error("[字库OCR测试] %s", binding_mismatch_detail)
            return False
        if not CAPTURE_AVAILABLE:
            logger.error("[字库OCR测试] 截图引擎不可用")
            return False

        library = _load_library(params)
        region_mode, region_x, region_y, region_width, region_height = _resolve_region_params(params)
        full_image = _capture_window_for_ocr(int(target_hwnd), timeout=4.0)
        if full_image is None:
            logger.error("[字库OCR测试] 无法捕获窗口图像")
            return False
        full_image = _align_window_image_to_client_area(full_image, target_hwnd, diag_prefix="[字库OCR测试]")
        roi_image, _x, _y, _w, _h, region_desc = _extract_effective_ocr_roi(
            window_image=full_image,
            region_mode=region_mode,
            region_x=region_x,
            region_y=region_y,
            region_width=region_width,
            region_height=region_height,
            fallback_log_prefix="[字库OCR测试]",
        )
        if roi_image is None or roi_image.size == 0:
            logger.error("[字库OCR测试] 提取的区域为空")
            return False

        results = _recognize_region(roi_image, params, library)
        output_lines = [
            "=" * 60,
            "点阵字库OCR测试结果",
            "=" * 60,
            f"窗口: {_window_title(target_hwnd)}",
            f"字库: {library.path}",
            f"字形数: {len(library)}",
            f"字库格式: {library.format_name or '未知'}",
            f"颜色: {params.get('color_format') or '自动二值化'}",
            f"相似度: {params.get('similarity', 0.9)}",
            f"区域: {region_desc}",
            f"识别时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"识别数量: {len(results)} 段文字",
            "=" * 60,
            "",
        ]
        if results:
            for index, result in enumerate(results, 1):
                output_lines.append(f"{index}. 文字: {result.get('text', '')}")
                output_lines.append(f"   相似度: {float(result.get('confidence') or 0):.3f}")
                bbox = result.get("bbox")
                if bbox:
                    output_lines.append(f"   位置: {bbox}")
                output_lines.append("")
        else:
            output_lines.extend(
                [
                    "未识别到任何文字",
                    "",
                    "建议:",
                    "1. 检查字库是否对应当前字体",
                    "2. 按大漠格式填写文字颜色，例如 ffffff-101010",
                    "3. 适当降低相似度",
                    "4. 确认框选区域里确实有这些字",
                ]
            )
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".txt", delete=False) as handle:
            handle.write("\n".join(output_lines))
            temp_file = handle.name
        subprocess.Popen(["notepad.exe", temp_file])
        logger.info("[字库OCR测试] 已输出 %s 段文字", len(results))
        return True
    except Exception as exc:
        logger.error("[字库OCR测试] 测试失败: %s", exc, exc_info=True)
        return False
    finally:
        try:
            from utils.capture.screenshot_helper import clear_screenshot_cache

            clear_screenshot_cache(target_hwnd if target_hwnd else None)
        except Exception:
            pass
        try:
            from services.screenshot_pool import clear_screenshot_runtime_state

            clear_screenshot_runtime_state(hwnd=target_hwnd if target_hwnd else None)
        except Exception:
            pass
