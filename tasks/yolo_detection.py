#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
YOLO目标检测任务模块：参数定义、单次检测执行、结果写入工作流上下文。

叠加层绘制与目标追踪的后台运行时在 tasks.yolo_overlay_runtime。
"""

import ast
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

from tasks.yolo_overlay_runtime import (
    _clear_capture_fail_state,
    _clear_target_not_found_state,
    _log_capture_fail_throttled,
    _log_target_not_found_throttled,
    _set_overlay_render_mode,
    _update_tracking_state,
    draw_detections_on_window,
)

logger = logging.getLogger(__name__)

_missing_classes_file_warned = set()


def requires_input_lock(_params: Dict[str, Any]) -> bool:
    return False


def _notify_missing_classes_file(model_path: Path) -> None:
    try:
        try:
            key = str(model_path.resolve())
        except Exception:
            key = str(model_path)
        if key in _missing_classes_file_warned:
            return
        _missing_classes_file_warned.add(key)

        from PySide6.QtWidgets import QMessageBox, QApplication
        if QApplication.instance() is None:
            return

        classes_file = model_path.parent / "classes.txt"
        QMessageBox.warning(
            None,
            "提示",
            "无法从模型元数据获取类别，且未找到 classes.txt。\n"
            "类别将显示为 class_id，建议在同目录创建 classes.txt：\n"
            f"{classes_file}",
        )
    except Exception as e:
        logger.debug("显示缺少 classes.txt 提示失败：%s", e)

TASK_TYPE = "YOLO目标检测"
TASK_NAME = "YOLO目标检测"


def _read_classes_file(classes_file: Path) -> List[str]:
    encodings = ["utf-8", "gbk", "gb2312", "iso-8859-1"]
    for encoding in encodings:
        try:
            with open(classes_file, 'r', encoding=encoding) as f:
                class_names = [line.strip() for line in f if line.strip()]
            if class_names:
                return class_names
        except UnicodeDecodeError:
            continue
        except Exception:
            break
    return []


def _parse_class_names_value(value: Optional[str]) -> List[str]:
    if not value:
        return []
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except Exception:
            value = value.decode(errors="ignore")
    if not isinstance(value, str):
        return []

    try:
        parsed = json.loads(value)
    except Exception:
        try:
            parsed = ast.literal_eval(value)
        except Exception:
            return []

    if isinstance(parsed, dict):
        try:
            items = sorted(parsed.items(), key=lambda kv: int(kv[0]))
        except Exception:
            items = sorted(parsed.items(), key=lambda kv: str(kv[0]))
        return [str(v).strip() for _, v in items if str(v).strip()]

    if isinstance(parsed, list):
        return [str(v).strip() for v in parsed if str(v).strip()]

    return []


def _load_class_names_from_onnx(model_path: Path) -> List[str]:
    session = None
    try:
        import onnxruntime as ort
    except Exception as e:
        logger.warning("ONNX Runtime 不可用，无法读取类别名：%s", e)
        return []

    try:
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        session = ort.InferenceSession(
            str(model_path),
            sess_options=sess_options,
            providers=["CPUExecutionProvider"],
        )
        meta = session.get_modelmeta()
        custom_map = getattr(meta, "custom_metadata_map", None) or {}
        names_value = (
            custom_map.get("names")
            or custom_map.get("names_str")
            or custom_map.get("classes")
        )
        class_names = _parse_class_names_value(names_value)
        if class_names:
            logger.info("Loaded class names from ONNX metadata")
        return class_names
    except Exception as e:
        logger.warning("从 ONNX 元数据读取类别名失败：%s", e)
        return []
    finally:
        try:
            if session is not None:
                del session
        except Exception:
            pass


def get_model_classes(model_path: str = "") -> List[str]:
    """获取模型类别列表（支持ONNX）"""
    if not model_path or not model_path.strip():
        return ["全部类别"]

    try:
        # 解析路径
        path = Path(model_path)
        if not path.exists():
            project_root = Path(__file__).parent.parent
            candidates = [
                project_root / model_path,
                project_root / "yolo" / path.name,
                Path(model_path),
            ]
            for candidate in candidates:
                if candidate.exists():
                    path = candidate
                    break
            else:
                logger.warning(f"模型文件不存在: {model_path}")
                return ["全部类别"]

        # ONNX模型：优先读取模型元数据，其次读取classes.txt
        if path.suffix.lower() == '.onnx':
            metadata_names = _load_class_names_from_onnx(path)
            if metadata_names:
                return ["全部类别"] + metadata_names

            classes_file = path.parent / "classes.txt"
            if classes_file.exists():
                try:
                    class_list = _read_classes_file(classes_file)
                    if class_list:
                        logger.info(
                            "Loaded %d classes from %s",
                            len(class_list),
                            classes_file.name,
                        )
                        return ["全部类别"] + class_list
                except Exception as e:
                    logger.warning(f"读取 classes.txt 失败：{e}")

            _notify_missing_classes_file(path)
            logger.warning("未在 ONNX 元数据或 classes.txt 中找到类别名")
            return ["全部类别"]

        return ["全部类别"]
    except Exception as e:
        logger.warning(f"获取模型类别失败: {e}")
        import traceback
        traceback.print_exc()
        return ["全部类别"]


def execute_task(params: Dict[str, Any], counters: Dict[str, int], execution_mode: str,
                 target_hwnd: Optional[int], window_region: Optional[Tuple[int, int, int, int]],
                 card_id: Optional[int] = None, **kwargs) -> Tuple[bool, str, Optional[int]]:
    """执行YOLO检测任务"""
    executor = kwargs.get("executor")
    stop_checker = kwargs.get("stop_checker")

    def _stop_with_warning(message: str) -> Tuple[bool, str, Optional[int]]:
        try:
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance()
            if app is not None:
                def show_message():
                    QMessageBox.warning(None, "\u0059\u004f\u004c\u004f\u9650\u5236", message)

                QTimer.singleShot(0, app, show_message)
        except Exception as e:
            logger.debug("显示 YOLO 警告弹窗失败：%s", e)
        if executor is not None and hasattr(executor, "_stop_requested"):
            try:
                executor._stop_requested = True
            except Exception as e:
                logger.debug("请求停止工作流失败（YOLO）：%s", e)
        return _handle_result(False, "\u505c\u6b62\u5de5\u4f5c\u6d41", None, card_id)

    def _query_hwnd_state(hwnd_value: Optional[int]) -> Tuple[Optional[bool], Optional[bool]]:
        try:
            import win32gui
            if hwnd_value is None or int(hwnd_value) <= 0:
                return False, False
            hwnd_int = int(hwnd_value)
            return bool(win32gui.IsWindow(hwnd_int)), bool(win32gui.IsWindowVisible(hwnd_int))
        except Exception:
            return None, None

    def _is_stop_requested() -> bool:
        try:
            if callable(stop_checker) and bool(stop_checker()):
                return True
        except Exception:
            pass
        try:
            return bool(executor is not None and getattr(executor, "_stop_requested", False))
        except Exception:
            return False

    model_path = params.get('model_path', 'yolo/yolov8n.onnx')
    conf_threshold = params.get('confidence_threshold', 0.5)
    iou_threshold = params.get('iou_threshold', 0.45)
    target_classes_str = params.get('target_classes', '')
    on_failure = params.get('on_failure', '执行下一步')
    on_success = params.get('on_success', '执行下一步')
    failure_jump_id = params.get('failure_jump_target_id')

    normalized_mode = str(execution_mode or "").strip().lower()
    supports_yolo_mode = normalized_mode.startswith("foreground") or normalized_mode.startswith("background")

    if not supports_yolo_mode:
        logger.error("YOLO 不支持当前执行模式: %s", execution_mode)
        current_engine = "unknown"
        try:
            from utils.capture.screenshot_helper import get_screenshot_engine
            current_engine = str(get_screenshot_engine() or "").strip().lower() or "unknown"
        except Exception:
            pass
        warning_message = (
            "YOLO限制：只支持前台或后台模式。\n"
            "当前执行模式: {mode}\n"
            "当前截图引擎: {engine}\n\n"
            "请在全局设置切换为前台或后台。"
        ).format(mode=execution_mode, engine=current_engine)
        return _stop_with_warning(warning_message)

    try:
        from utils.capture.screenshot_helper import (
            get_screenshot_engine,
            get_screenshot_info,
            probe_dxgi_runtime_available,
        )

        current_engine = get_screenshot_engine()
        allowed_engines = {"dxgi", "gdi", "wgc", "printwindow"}
        if current_engine not in allowed_engines:
            logger.error(
                "YOLO 截图引擎不受支持，当前引擎=%s",
                current_engine,
            )
            warning_message = (
                "YOLO限制：截图引擎仅支持 DXGI / GDI / WGC / PrintWindow，"
                "当前引擎: {engine}。"
            ).format(engine=current_engine)
            return _stop_with_warning(warning_message)

        if current_engine == "dxgi":
            dxgi_available = False
            try:
                dxgi_available = bool(probe_dxgi_runtime_available())
            except Exception:
                dxgi_available = False
            if not dxgi_available:
                logger.warning("YOLO DXGI预检失败，将尝试实际抓图再判定")
        if current_engine == "gdi":
            gdi_available = False
            try:
                engine_info = get_screenshot_info()
                gdi_available = bool((engine_info or {}).get("gdi_available", False))
            except Exception:
                gdi_available = False
            if not gdi_available:
                logger.error("YOLO 需要 GDI，但当前 GDI 不可用")
                warning_message = "\u0059\u004f\u004c\u004f\u9650\u5236\uff1a\u0047\u0044\u0049\u4e0d\u53ef\u7528\u3002"
                return _stop_with_warning(warning_message)

    except Exception as e:
        logger.debug("检查 YOLO 截图引擎失败：%s", e)

    # 支持ROI区域参数
    use_region = params.get('use_region', False)
    region_x = params.get('region_x', 0)
    region_y = params.get('region_y', 0)
    region_width = params.get('region_width', 0)
    region_height = params.get('region_height', 0)

    selection_map = {'最近': 'nearest', '最大': 'largest', '置信度最高': 'highest_conf'}
    target_selection = selection_map.get(params.get('target_selection', '最近'), 'nearest')

    # 窗口绘制参数
    draw_on_window = params.get('draw_on_window', False)

    if not target_hwnd:
        logger.error("需要有效的窗口句柄")
        return _handle_result(False, on_failure, failure_jump_id, card_id)
    if _is_stop_requested():
        return _handle_result(False, "停止工作流", None, card_id)

    # 检查窗口是否有效
    try:
        import win32gui
        if not win32gui.IsWindow(target_hwnd):
            logger.error("目标窗口句柄已失效，强制停止工作流")
            return _stop_with_warning("目标窗口句柄已失效，请重新绑定后再执行YOLO任务。")
        if not win32gui.IsWindowVisible(target_hwnd):
            logger.error("目标窗口不可见（可能最小化或已隐藏），强制停止工作流")
            return _stop_with_warning("目标窗口不可见，请恢复窗口并重新绑定后再执行YOLO任务。")
    except Exception as e:
        logger.error(f"检查窗口有效性失败: {e}")
        return False, '停止工作流', None

    target_classes = None
    if target_classes_str and target_classes_str != "全部类别":
        target_classes = [target_classes_str.strip()]

    detect_classes = list(target_classes) if target_classes else None
    try:
        from utils.match.yolo_engine import get_yolo_engine

        raw_input_size = params.get('input_size', 416)
        try:
            input_size = int(raw_input_size) if raw_input_size is not None else None
        except Exception:
            input_size = 416
        if input_size is not None and input_size <= 0:
            input_size = None

        engine = get_yolo_engine(
            model_path=model_path,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
            input_size=input_size,
        )

        detections, screenshot = engine.detect_from_hwnd(
            target_hwnd,
            detect_classes,
            conf_threshold,
            execution_mode,
            iou_threshold,
            roi=(region_x, region_y, region_width, region_height) if use_region else None,
        )
        if _is_stop_requested():
            return _handle_result(False, "停止工作流", None, card_id)

        if screenshot is None:
            is_window, is_visible = _query_hwnd_state(target_hwnd)
            if is_window is False:
                return _stop_with_warning("目标窗口句柄已失效，请重新绑定后再执行YOLO任务。")
            if is_visible is False:
                return _stop_with_warning("目标窗口不可见，请恢复窗口并重新绑定后再执行YOLO任务。")

            _log_capture_fail_throttled(card_id, target_hwnd, "capture_failed")
            return _handle_result(False, on_failure, failure_jump_id, card_id)

        screenshot_shape = tuple(screenshot.shape) if screenshot is not None else None
        _clear_capture_fail_state(card_id, target_hwnd)

        target_detections = detections
        if target_classes:
            target_detections = [d for d in detections if d.class_name in target_classes]

        if not target_detections:
            _log_target_not_found_throttled(card_id, target_hwnd, target_classes)
            if draw_on_window:
                _set_overlay_render_mode("稳定优先")
                frame_shape = screenshot_shape
                _update_tracking_state(
                    target_hwnd,
                    [],
                    frame_shape,
                    screenshot,
                    tracking_engine=locals().get("current_engine"),
                    executor=executor,
                )
                draw_detections_on_window(target_hwnd, [], frame_shape, executor=executor)
            if card_id is not None:
                try:
                    from task_workflow.runtime_store import publish_perception

                    publish_perception(
                        card_id,
                        kind="yolo",
                        ok=False,
                        threshold=params.get("confidence_threshold"),
                    )
                except Exception:
                    pass
            return _handle_result(False, on_failure, failure_jump_id, card_id)


        selected = _select_target(target_detections, target_selection, screenshot_shape)
        if not selected:
            return _handle_result(False, on_failure, failure_jump_id, card_id)
        _clear_target_not_found_state(card_id, target_hwnd, target_classes)

        # 保存YOLO检测结果到上下文，供后续卡片读取上下文
        if card_id is not None:
            selection_strategy_cn = params.get('target_selection', '最近')
            _save_yolo_result_to_context(
                card_id, selected, target_detections, selection_strategy_cn,
                screenshot_shape,
                target_hwnd,
            )

        # 在窗口上绘制检测框
        if draw_on_window:
            _set_overlay_render_mode("稳定优先")
            draw_detections_on_window(target_hwnd, target_detections, screenshot_shape, executor=executor)
            _update_tracking_state(
                target_hwnd,
                target_detections,
                screenshot_shape,
                screenshot,
                tracking_engine=locals().get("current_engine"),
                executor=executor,
            )

        from .task_utils import handle_success_action
        return handle_success_action(params, card_id, kwargs.get('stop_checker'))

    except Exception as e:
        error_text = str(e or "").strip().lower()
        if "yolo_detect_cancelled" in error_text or "cancelled" in error_text:
            if _is_stop_requested():
                return _handle_result(False, "停止工作流", None, card_id)
            return _handle_result(False, on_failure, failure_jump_id, card_id)

        if "invalid_hwnd" in error_text:
            logger.error("YOLO检测失败: %s", e)
            return _stop_with_warning("目标窗口句柄已失效，请重新绑定后再执行YOLO任务。")

        if "window_not_visible" in error_text:
            logger.error("YOLO检测失败: %s", e)
            return _stop_with_warning("目标窗口不可见，请恢复窗口并重新绑定后再执行YOLO任务。")

        if "引擎不可用" in error_text:
            logger.error("YOLO检测失败: %s", e)
            return _stop_with_warning("YOLO截图引擎不可用，请检查截图引擎配置后重试。")

        if "capture_failed" in error_text or "capture_exception" in error_text:
            is_window, is_visible = _query_hwnd_state(target_hwnd)
            if is_window is False:
                logger.error("YOLO检测失败: %s", e)
                return _stop_with_warning("目标窗口句柄已失效，请重新绑定后再执行YOLO任务。")
            if is_visible is False:
                logger.error("YOLO检测失败: %s", e)
                return _stop_with_warning("目标窗口不可见，请恢复窗口并重新绑定后再执行YOLO任务。")

            _log_capture_fail_throttled(card_id, target_hwnd, error_text or "capture_failed")
            return _handle_result(False, on_failure, failure_jump_id, card_id)

        logger.error(f"YOLO检测失败: {e}")
        return _handle_result(False, on_failure, failure_jump_id, card_id)


def _select_target(detections: List, strategy: str, shape: Optional[Tuple]) -> Optional[Any]:
    """选择目标（ONNX版本：不支持track_id）"""
    if not detections:
        return None

    if shape:
        ref_x, ref_y = shape[1] // 2, shape[0] // 2
    else:
        ref_x, ref_y = 0, 0

    if strategy == 'nearest':
        return min(detections, key=lambda d: (d.center_x - ref_x) ** 2 + (d.center_y - ref_y) ** 2)

    if strategy == 'largest':
        return max(detections, key=lambda d: d.area)

    if strategy == 'highest_conf':
        return max(detections, key=lambda d: d.confidence)

    return detections[0]


def _save_yolo_result_to_context(card_id: int, selected, all_detections: List,
                                  selection_strategy: str, screenshot_shape: Optional[Tuple],
                                  target_hwnd: Optional[int] = None):
    """保存YOLO检测结果到上下文，供后续卡片读取上下文

    Args:
        card_id: 卡片ID
        selected: 选中的目标检测结果
        all_detections: 所有检测到的目标
        selection_strategy: 选择策略
        screenshot_shape: 截图尺寸
        target_hwnd: 目标窗口句柄（用于坐标缩放）
    """
    try:
        from task_workflow.workflow_context import set_yolo_result

        # 截图坐标直接使用，不需要缩放
        # 截图已是客户区的实际像素大小，检测坐标也基于此截图

        # 构建结果数据（使用原始检测坐标）
        target_x, target_y = int(selected.center_x), int(selected.center_y)
        x1, y1 = int(selected.x1), int(selected.y1)
        x2, y2 = int(selected.x2), int(selected.y2)

        result = {
            'target_x': target_x,
            'target_y': target_y,
            'x1': x1,
            'y1': y1,
            'x2': x2,
            'y2': y2,
            'width': x2 - x1,
            'height': y2 - y1,
            'class_name': selected.class_name,
            'confidence': selected.confidence,
            'selection_strategy': selection_strategy,
            'all_detections': [
                {
                    'x': int(det.center_x),
                    'y': int(det.center_y),
                    'x1': int(det.x1),
                    'y1': int(det.y1),
                    'x2': int(det.x2),
                    'y2': int(det.y2),
                    'class_name': det.class_name,
                    'confidence': det.confidence
                }
                for det in all_detections
            ] if all_detections else []
        }

        set_yolo_result(card_id, result)
        logger.info(f"YOLO结果已保存到上下文: 卡片{card_id}, 目标=({target_x}, {target_y}), 类别={selected.class_name}")

    except Exception as e:
        logger.warning(f"保存YOLO结果到上下文失败: {e}")


def _handle_result(success: bool, action: str, jump_id: Optional[int],
                   card_id: Optional[int]) -> Tuple[bool, str, Optional[int]]:
    """处理结果"""
    if action == '跳转到步骤':
        return success, '跳转到步骤', jump_id
    if action == '停止工作流':
        return success, '停止工作流', None
    if action == '继续执行本步骤':
        return success, '继续执行本步骤', card_id
    return success, '执行下一步', None


def get_params_definition() -> Dict[str, Dict[str, Any]]:
    """参数定义"""
    from tasks.task_utils import get_standard_next_step_delay_params, merge_params_definitions

    params = {
        "---model---": {"type": "separator", "label": "模型设置"},
        "yolo_backend": {
            "label": "YOLO后端",
            "type": "select",
            "options": ["原生"],
            "default": "原生",
            "tooltip": "本地 ONNX 推理",
        },
        "model_path": {
            "label": "模型路径", "type": "file",
            "file_types": ["ONNX模型 (*.onnx)", "所有文件 (*.*)"],
            "default": "", "tooltip": "仅支持ONNX格式模型",
        },
        "confidence_threshold": {
            "label": "置信度阈值", "type": "float",
            "default": 0.5, "min": 0.1, "max": 1.0, "decimals": 2,
            "tooltip": "低于此值的检测结果将被过滤"
        },
        "iou_threshold": {
            "label": "IoU阈值(NMS)", "type": "float",
            "default": 0.45, "min": 0.1, "max": 1.0, "decimals": 2,
            "tooltip": "重叠框过滤阈值，越低过滤越多重复框"
        },

        "---region---": {"type": "separator", "label": "识别区域"},
        "use_region": {
            "label": "限定识别区域", "type": "bool", "default": False,
            "tooltip": "仅在指定区域内进行检测，可提高性能"
        },
        "region_selector": {
            "label": "框选区域", "type": "ocr_region_selector",
            "widget_hint": "ocr_region_selector",
            "condition": {"param": "use_region", "value": True}
        },
        "region_coordinates": {
            "label": "区域坐标", "type": "text", "default": "未设置",
            "readonly": True,
            "condition": {"param": "use_region", "value": True},
            "tooltip": "框选区域后自动填充"
        },
        "region_x": {
            "type": "int", "default": 0, "hidden": True
        },
        "region_y": {
            "type": "int", "default": 0, "hidden": True
        },
        "region_width": {
            "type": "int", "default": 0, "hidden": True
        },
        "region_height": {
            "type": "int", "default": 0, "hidden": True
        },
        "region_hwnd": {
            "type": "int", "default": 0, "hidden": True
        },
        "region_window_title": {
            "type": "str", "default": "", "hidden": True
        },
        "region_window_class": {
            "type": "str", "default": "", "hidden": True
        },
        "region_client_width": {
            "type": "int", "default": 0, "hidden": True
        },
        "region_client_height": {
            "type": "int", "default": 0, "hidden": True
        },

        "---display---": {"type": "separator", "label": "显示设置"},
        "draw_on_window": {
            "label": "窗口内绘制", "type": "bool", "default": False,
            "tooltip": "直接在目标窗口上绘制检测框"
        },

        "---result---": {"type": "separator", "label": "结果处理"},
        "on_success": {
            "label": "成功时", "type": "select",
            "options": ["继续执行本步骤", "执行下一步", "跳转到步骤", "停止工作流"],
            "default": "执行下一步"
        },
        "success_jump_target_id": {
            "type": "int", "label": "成功跳转ID",
            "widget_hint": "card_selector",
            "condition": {"param": "on_success", "value": "跳转到步骤"}
        },
        "on_failure": {
            "label": "失败时", "type": "select",
            "options": ["继续执行本步骤", "执行下一步", "跳转到步骤", "停止工作流"],
            "default": "执行下一步"
        },
        "failure_jump_target_id": {
            "type": "int", "label": "失败跳转ID",
            "widget_hint": "card_selector",
            "condition": {"param": "on_failure", "value": "跳转到步骤"}
        }
    }

    return merge_params_definitions(params, get_standard_next_step_delay_params())

