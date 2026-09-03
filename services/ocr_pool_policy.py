"""按截图引擎看管 OCR 保底进程：原生与插件都预热 RapidOCR（插件只换截图来源）。"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from utils.capture.engine_ids import canonicalize_screenshot_engine

logger = logging.getLogger(__name__)

_PREWARM_LOCK = threading.Lock()
_PREWARM_ACTIVE = False


def resolve_screenshot_engine() -> str:
    try:
        from utils.capture.screenshot_helper import get_screenshot_engine

        current = canonicalize_screenshot_engine(get_screenshot_engine() or "")
        if current:
            return current
    except Exception:
        logger.debug("读取运行时截图引擎失败", exc_info=True)
    try:
        from app_core.config_store import load_config

        return canonicalize_screenshot_engine((load_config() or {}).get("screenshot_engine") or "wgc")
    except Exception:
        logger.debug("读取配置截图引擎失败", exc_info=True)
        return "wgc"


def get_multiprocess_ocr_pool():
    from services.multiprocess_ocr_pool import get_multiprocess_ocr_pool as _get

    return _get()


def get_existing_multiprocess_ocr_pool():
    from services.multiprocess_ocr_pool import get_existing_multiprocess_ocr_pool as _get

    return _get()


def sync_ocr_pool_to_screenshot_engine(engine: object) -> str:
    """截图引擎切换时保持 RapidOCR 池可用；插件模式不再注销 OCR。"""
    _ = canonicalize_screenshot_engine(engine)
    pool = get_multiprocess_ocr_pool()
    pool.set_keep_warm(True)
    pool.ensure_warm_workers()
    logger.info("已同步 OCR 保底进程（引擎=%s）", _ or "unknown")
    return "warmed"


def apply_ocr_pool_stop_policy(engine: Optional[object] = None) -> None:
    _ = canonicalize_screenshot_engine(engine) if engine else resolve_screenshot_engine()
    pool = get_existing_multiprocess_ocr_pool()
    if pool is None:
        return
    pool.set_keep_warm(True)
    pool.release_window_assignments()
    pool.ensure_warm_workers()


def schedule_ocr_pool_prewarm() -> bool:
    """后台预热 OCR；原生/插件都需要 RapidOCR 识字。"""
    global _PREWARM_ACTIVE
    engine = resolve_screenshot_engine()
    with _PREWARM_LOCK:
        if _PREWARM_ACTIVE:
            return False
        _PREWARM_ACTIVE = True

    def _worker() -> None:
        global _PREWARM_ACTIVE
        try:
            sync_ocr_pool_to_screenshot_engine(engine)
        except Exception:
            logger.debug("预热 OCR 子进程失败", exc_info=True)
        finally:
            with _PREWARM_LOCK:
                _PREWARM_ACTIVE = False

    worker = threading.Thread(target=_worker, name="ocr-prewarm", daemon=True)
    try:
        worker.start()
    except Exception:
        with _PREWARM_LOCK:
            _PREWARM_ACTIVE = False
        logger.debug("启动 OCR 预热线程失败", exc_info=True)
        return False
    return True
