# -*- coding: utf-8 -*-
"""
运行期图片内存清理工具。
目标：
1. 将图片相关缓存清理收敛到单一入口，避免清理链路分散。
2. 在停止任务/执行结束时稳定释放主进程中的图片对象引用。
"""

import gc
import logging
import os
import sys
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _trim_windows_heap() -> bool:
    """尝试触发 Windows 堆回收，帮助工作集回落。"""
    if os.name != "nt":
        return False
    try:
        import ctypes

        msvcrt = ctypes.CDLL("msvcrt")
        heapmin = getattr(msvcrt, "_heapmin", None)
        if callable(heapmin):
            heapmin()
            return True
    except Exception:
        return False
    return False


def _get_loaded_callable(module_name: str, func_name: str):
    """仅从已加载模块中获取可调用对象，避免清理路径引入额外模块负载。"""
    module = sys.modules.get(module_name)
    if module is None:
        return None
    func = getattr(module, func_name, None)
    if callable(func):
        return func
    return None


def cleanup_yolo_runtime_on_stop(
    release_engine: bool = True,
    compact_memory: bool = False,
) -> Dict[str, Any]:
    """停止链路专用：清理已加载 YOLO 运行态。"""
    result: Dict[str, Any] = {
        "runtime": False,
        "overlay_only": False,
        "engine": False,
    }

    try:
        cleanup_runtime = _get_loaded_callable(
            "tasks.yolo_detection",
            "cleanup_yolo_runtime_state",
        )
        if cleanup_runtime is not None:
            cleanup_runtime(
                release_engine=bool(release_engine),
                compact_memory=bool(compact_memory),
            )
            result["runtime"] = True
        else:
            hide_overlay = _get_loaded_callable(
                "tasks.yolo_detection",
                "hide_detections_overlay",
            )
            if hide_overlay is not None:
                hide_overlay()
                result["overlay_only"] = True
    except Exception as exc:
        logger.debug("停止时清理 YOLO 运行态失败: %s", exc)

    if release_engine:
        try:
            yolo_engine_module = sys.modules.get("utils.yolo_engine")
            if yolo_engine_module is not None:
                engine_cls = getattr(yolo_engine_module, "YOLOONNXEngine", None)
                clear_instances = getattr(engine_cls, "clear_instances", None)
                if callable(clear_instances):
                    clear_instances()
                    result["engine"] = True
        except Exception as exc:
            logger.debug("停止时清理 YOLO 引擎缓存失败: %s", exc)

    return result


def cleanup_runtime_image_memory(
    reason: str = "",
    cleanup_screenshot_engines: bool = False,
    cleanup_template_cache: bool = False,
) -> Dict[str, Any]:
    """清理运行期图片内存占用。"""
    result: Dict[str, Any] = {
        "reason": str(reason or ""),
        "motion_cache": False,
        "parallel_recognizer": False,
        "shared_capture": False,
        "yolo_overlay": False,
        "screenshot_cache": False,
        "screenshot_engine": False,
        "template_cache": False,
        "gc_collected": 0,
        "heap_trimmed": False,
    }

    try:
        clear_motion_cache = _get_loaded_callable(
            "tasks.conditional_control",
            "clear_all_motion_cache",
        )
        if clear_motion_cache is not None:
            clear_motion_cache()
            result["motion_cache"] = True
    except Exception as exc:
        logger.debug("清理移动检测缓存失败: %s", exc)

    try:
        cleanup_parallel = _get_loaded_callable(
            "tasks.parallel_image_recognition",
            "cleanup_parallel_recognizer",
        )
        if cleanup_parallel is not None:
            cleanup_parallel(reset_instance=True)
            result["parallel_recognizer"] = True
    except Exception as exc:
        logger.debug("清理并行识图实例失败: %s", exc)

    try:
        from task_workflow.workflow_context import get_workflow_context

        context = get_workflow_context()
        if context is not None and hasattr(context, "clear_shared_captures"):
            context.clear_shared_captures()
            result["shared_capture"] = True
    except Exception as exc:
        logger.debug("清理共享截图失败: %s", exc)

    try:
        cleanup_yolo_runtime = _get_loaded_callable(
            "tasks.yolo_detection",
            "cleanup_yolo_runtime_state",
        )
        if cleanup_yolo_runtime is not None:
            cleanup_yolo_runtime(release_engine=False, compact_memory=False)
            result["yolo_overlay"] = True
        else:
            hide_overlay = _get_loaded_callable(
                "tasks.yolo_detection",
                "hide_detections_overlay",
            )
            if hide_overlay is not None:
                hide_overlay()
                result["yolo_overlay"] = True
    except Exception as exc:
        logger.debug("清理检测叠加层失败: %s", exc)

    try:
        from utils.screenshot_helper import clear_screenshot_cache

        clear_screenshot_cache()
        result["screenshot_cache"] = True
    except Exception as exc:
        logger.debug("清理截图缓存失败: %s", exc)

    if cleanup_screenshot_engines:
        try:
            from utils.async_screenshot import shutdown_global_pipeline

            shutdown_global_pipeline()
        except Exception:
            pass
        try:
            from utils.screenshot_helper import cleanup_all_screenshot_engines

            cleanup_all_screenshot_engines()
            result["screenshot_engine"] = True
        except Exception as exc:
            logger.debug("清理截图引擎失败: %s", exc)

    if cleanup_template_cache:
        try:
            from utils.template_preloader import clear_global_cache

            clear_global_cache()
            result["template_cache"] = True
        except Exception as exc:
            logger.debug("清理模板缓存失败: %s", exc)

    try:
        result["gc_collected"] = int(gc.collect())
    except Exception:
        result["gc_collected"] = 0

    try:
        result["heap_trimmed"] = bool(_trim_windows_heap())
    except Exception:
        result["heap_trimmed"] = False

    return result
