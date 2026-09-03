"""进程级环境变量默认值，需要在 numpy / Qt 加载之前设置。"""

from __future__ import annotations

import os

_NUMERIC_THREAD_ENV_NAMES = (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "GOTO_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)


def set_numeric_thread_env_defaults() -> None:
    """限制 BLAS / OpenMP 线程数，避免识别库在多窗口任务里抢占 CPU。"""
    default_threads = os.environ.get("LCA_NUMERIC_THREADS_DEFAULT", "1").strip() or "1"
    for env_name in _NUMERIC_THREAD_ENV_NAMES:
        if not os.environ.get(env_name):
            os.environ[env_name] = default_threads


def suppress_qt_platform_warnings() -> None:
    rule = "qt.qpa.window=false"
    existing = os.environ.get("QT_LOGGING_RULES", "")
    if rule not in existing:
        os.environ["QT_LOGGING_RULES"] = f"{existing};{rule}" if existing else rule
