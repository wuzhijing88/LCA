"""进程退出时的全局资源清理。

所有清理都只针对“已经创建过”的实例，绝不在退出路径上新建引擎或子进程；
因此这里全部使用函数内延迟导入，并容忍任一步骤失败。
"""

from __future__ import annotations

import atexit
import logging
import os
import tempfile
import time

from app_core.runtime.lifecycle import get_runtime_lifecycle

logger = logging.getLogger(__name__)

_WORKFLOW_TEMP_BACKUP_MAX_AGE_SEC = 3 * 24 * 3600
_OCR_TEMP_TXT_MAX_AGE_SEC = 24 * 3600


def cleanup_temp_files() -> None:
    """清理程序产生的过期临时文件（工作流临时备份、OCR 测试遗留的 txt）。"""
    current_time = time.time()
    temp_dir = tempfile.gettempdir()

    workflow_temp_dir = os.path.join(temp_dir, "workflow_temp_backups")
    if os.path.exists(workflow_temp_dir):
        try:
            deleted_count = 0
            for filename in os.listdir(workflow_temp_dir):
                filepath = os.path.join(workflow_temp_dir, filename)
                try:
                    if current_time - os.path.getmtime(filepath) > _WORKFLOW_TEMP_BACKUP_MAX_AGE_SEC:
                        os.remove(filepath)
                        deleted_count += 1
                except (OSError, PermissionError):
                    pass
            if deleted_count > 0:
                logger.info(f"临时备份清理: 删除 {deleted_count} 个过期文件")
        except (OSError, PermissionError) as e:
            logger.warning(f"临时备份清理失败: {e}")

    try:
        for filename in os.listdir(temp_dir):
            if filename.startswith("tmp") and filename.endswith(".txt"):
                filepath = os.path.join(temp_dir, filename)
                try:
                    if current_time - os.path.getmtime(filepath) > _OCR_TEMP_TXT_MAX_AGE_SEC:
                        os.remove(filepath)
                except (OSError, PermissionError):
                    pass
    except (OSError, PermissionError):
        pass


def cleanup_yolo_runtime_resources(
    release_process: bool = True,
    compact_memory: bool = True,
) -> bool:
    """清理YOLO运行时资源（仅清理已存在实例，不创建新实例）。"""
    cleaned = False
    try:
        from app_core.runtime.runtime_image_cleanup import cleanup_yolo_runtime_on_stop

        cleanup_result = cleanup_yolo_runtime_on_stop(
            release_engine=bool(release_process),
            compact_memory=bool(compact_memory),
        )
        cleaned = bool(
            cleanup_result.get("runtime")
            or cleanup_result.get("overlay_only")
            or cleanup_result.get("engine")
        )
    except Exception as e:
        logging.debug(f"清理YOLO运行时资源时出错: {e}")
    return cleaned


def cleanup_runtime_state_variables() -> None:
    """保留统一清理回调接口（当前无额外运行态变量需要清理）。"""
    return None


def cleanup_all_resources() -> None:
    """清理所有全局资源：输入驱动、OCR 池、登记的 worker、YOLO、模板/截图缓存、工作流上下文。"""
    try:
        try:
            from utils.input_simulation import global_input_simulator_manager

            global_input_simulator_manager.clear_cache()
            logging.info("输入模拟器缓存已清理")
        except Exception as e:
            logging.debug(f"清理输入模拟器缓存时出错: {e}")

        try:
            from utils.input.foreground_input_manager import get_foreground_input_manager

            get_foreground_input_manager().close()
            logging.info("前台输入驱动已清理")
        except Exception as e:
            logging.debug(f"清理前台输入驱动时出错: {e}")

        try:
            from services.multiprocess_ocr_pool import get_existing_multiprocess_ocr_pool

            pool = get_existing_multiprocess_ocr_pool()
            if pool is not None:
                pool.shutdown()
                logging.info("OCR服务池已清理")
        except Exception as e:
            logging.debug(f"清理OCR服务池时出错: {e}")

        try:
            from services.worker_process_cleanup import cleanup_all_registered_worker_processes

            cleaned_count = int(cleanup_all_registered_worker_processes() or 0)
            if cleaned_count > 0:
                logging.info(f"登记子进程已清理: {cleaned_count}")
        except Exception as e:
            logging.error(f"登记子进程清理失败: {e}")

        # 主进程不加载OCR引擎模块，OCR资源只由OCR子进程管理

        if cleanup_yolo_runtime_resources(release_process=True, compact_memory=True):
            logging.info("YOLO运行时资源已清理")

        try:
            from utils.match.template_preloader import clear_global_cache

            clear_global_cache()
            logging.info("模板预加载缓存已清理")
        except Exception as e:
            logging.debug(f"清理模板预加载缓存时出错: {e}")

        try:
            from utils.match.template_matching import get_matcher

            matcher = get_matcher()
            if hasattr(matcher, "template_cache"):
                matcher.template_cache.clear()
            logging.info("模板匹配缓存已清理")
        except Exception as e:
            logging.debug(f"清理模板匹配缓存时出错: {e}")

        try:
            from task_workflow.workflow_context import clear_all_workflow_contexts

            clear_all_workflow_contexts()
            logging.info("工作流上下文已清理")
        except Exception as e:
            logging.debug(f"清理工作流上下文时出错: {e}")

        try:
            from tasks.conditional_control import clear_all_motion_cache

            clear_all_motion_cache()
            logging.info("移动检测缓存已清理")
        except Exception as e:
            logging.debug(f"清理移动检测缓存时出错: {e}")

        try:
            from utils.capture.screenshot_helper import clear_screenshot_cache

            clear_screenshot_cache()
            logging.info("截图缓存已清理")
        except Exception as e:
            logging.debug(f"清理截图缓存时出错: {e}")

        try:
            from utils.capture.screenshot_helper import cleanup_all_screenshot_engines

            cleanup_all_screenshot_engines()
            logging.info("截图引擎资源已清理")
        except Exception as e:
            logging.debug(f"清理截图引擎资源时出错: {e}")

        logging.info("资源清理完成")
    except Exception as e:
        logging.error(f"清理资源时出错: {e}", exc_info=True)
    finally:
        try:
            cleanup_runtime_state_variables()
        except Exception as e:
            logging.debug(f"清理运行态失败: {e}")


def register_global_resource_cleanup(name: str = "global-runtime-resources", priority: int = 100) -> None:
    """把全局清理挂到统一生命周期，并保证进程退出时至少执行一次 teardown。"""
    lifecycle = get_runtime_lifecycle()
    lifecycle.register(name, cleanup_all_resources, priority=priority, once=True)
    atexit.register(lambda: lifecycle.teardown(final=True))
