import sys
import os     # 用于路径和退出
import atexit
import ctypes
import logging
from urllib.parse import urlparse
from app_core.client_identity import attempt_client_registration as _shared_attempt_client_registration
from app_core.client_identity import get_hardware_id as _shared_get_hardware_id
from utils.dpi_awareness import enable_process_dpi_awareness
from utils.worker_entry import (
    StandaloneSubprocessSpec,
    ensure_project_main_runtime,
    get_cli_argument_value,
    get_cli_int_argument_value,
    is_packaged_runtime,
    is_standalone_subprocess_active,
    run_standalone_subprocess,
)

# 避免运行入口脚本后再次 `import main` 时触发二次执行
if __name__ == "__main__":
    sys.modules.setdefault("main", sys.modules[__name__])


def _set_numeric_thread_env_defaults() -> None:
    default_threads = os.environ.get("LCA_NUMERIC_THREADS_DEFAULT", "1").strip() or "1"
    for env_name in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "GOTO_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "BLIS_NUM_THREADS",
    ):
        if not os.environ.get(env_name):
            os.environ[env_name] = default_threads


_set_numeric_thread_env_defaults()


enable_process_dpi_awareness()


def _suppress_qt_warnings():
    rule = "qt.qpa.window=false"
    existing = os.environ.get("QT_LOGGING_RULES", "")
    if rule not in existing:
        os.environ["QT_LOGGING_RULES"] = f"{existing};{rule}" if existing else rule

_suppress_qt_warnings()

# 统一打包环境识别：支持改名后的发布版可执行文件（不再依赖 main.exe 固定名称）
if not getattr(sys, 'frozen', False) and is_packaged_runtime():
    sys.frozen = True  # 手动补齐标记，兼容依赖 sys.frozen 的路径分支

def _install_root_log_translator() -> None:
    try:
        from utils.log_message_translator import install_log_message_translator
        install_log_message_translator(logging.getLogger())
    except Exception:
        pass


def _ensure_standalone_subprocess_file_logging(log_level: int = logging.INFO) -> None:
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    log_format = (
        "%(asctime)s - %(levelname)s - [pid=%(process)d] - [%(module)s:%(lineno)d] - %(message)s"
    )
    try:
        import datetime as _datetime
        from utils.app_paths import get_logs_dir

        log_dir = get_logs_dir("LCA")
        log_path = os.path.join(log_dir, f"app_{_datetime.date.today():%Y-%m-%d}.log")
        file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        file_handler.setLevel(int(log_level))
        file_handler.setFormatter(logging.Formatter(log_format))
        root_logger.setLevel(int(log_level))
        root_logger.addHandler(file_handler)
    except Exception:
        logging.basicConfig(
            level=int(log_level),
            format=log_format,
        )


def _build_ocr_subprocess_args(argv) -> tuple[str, int]:
    return (
        get_cli_argument_value(argv, "--process-id", "unknown"),
        get_cli_int_argument_value(argv, "--port", 0),
    )


def _build_match_subprocess_args(argv) -> tuple[str, int]:
    return (
        get_cli_argument_value(argv, "--process-id", "unknown"),
        get_cli_int_argument_value(argv, "--port", 0),
    )


def _build_workflow_subprocess_args(argv) -> tuple[int]:
    return (get_cli_int_argument_value(argv, "--port", 0),)


def _build_map_navigation_subprocess_args(argv) -> tuple[str, str]:
    return (
        get_cli_argument_value(argv, "--input", ""),
        get_cli_argument_value(argv, "--output", ""),
    )


def _log_ocr_subprocess_start(logger, _argv, args) -> None:
    _install_root_log_translator()
    process_id, port = args
    logger.info("=" * 80)
    logger.info("[OCR子进程-命令行检测] 检测到 --ocr-worker 参数")
    logger.info(f"[OCR子进程-命令行检测] 进程ID: {process_id}")
    logger.info(f"[OCR子进程-命令行检测] 通信端口: {port}")
    logger.info("=" * 80)


def _log_workflow_subprocess_start(logger, _argv, args) -> None:
    _ensure_standalone_subprocess_file_logging(logging.INFO)
    _install_root_log_translator()
    (port,) = args
    logger.info("=" * 80)
    logger.info("[工作流子进程][命令行检测] 检测到 --workflow-worker 参数")
    logger.info(f"[工作流子进程][命令行检测] 通信端口: {port}")
    logger.info("=" * 80)


def _log_map_navigation_subprocess_start(logger, _argv, args) -> None:
    _ensure_standalone_subprocess_file_logging(logging.INFO)
    _install_root_log_translator()
    input_path, output_path = args
    logger.info("=" * 80)
    logger.info("[地图导航子进程][命令行检测] 检测到 --map-navigation-worker 参数")
    logger.info(f"[地图导航子进程][命令行检测] 输入文件: {input_path}")
    logger.info(f"[地图导航子进程][命令行检测] 输出文件: {output_path}")
    logger.info("=" * 80)


_STANDALONE_SUBPROCESS_SPECS = (
    StandaloneSubprocessSpec(
        flag="--ocr-worker",
        module_name="services.multiprocess_ocr_worker",
        callable_name="run_ocr_worker_standalone",
        logger_name="OCR_SUBPROCESS",
        error_label="OCR子进程",
        log_level=logging.DEBUG,
        log_format="%(asctime)s - %(levelname)s - [pid=%(process)d] - [%(funcName)s:%(lineno)d] - %(message)s",
        args_factory=_build_ocr_subprocess_args,
        startup_hook=_log_ocr_subprocess_start,
    ),
    StandaloneSubprocessSpec(
        flag="--match-worker",
        module_name="services.multiprocess_match_worker",
        callable_name="run_match_worker_standalone",
        logger_name="MATCH_SUBPROCESS",
        error_label="MATCH子进程",
        log_level=logging.INFO,
        log_format="%(asctime)s - %(levelname)s - [pid=%(process)d] - [%(funcName)s:%(lineno)d] - %(message)s",
        args_factory=_build_match_subprocess_args,
    ),
    StandaloneSubprocessSpec(
        flag="--workflow-worker",
        module_name="task_workflow.process_worker",
        callable_name="run_workflow_worker_standalone",
        logger_name="WORKFLOW_SUBPROCESS",
        error_label="WORKFLOW子进程",
        log_level=logging.INFO,
        log_format="%(asctime)s - %(levelname)s - [pid=%(process)d] - [%(funcName)s:%(lineno)d] - %(message)s",
        configure_root_logging=False,
        args_factory=_build_workflow_subprocess_args,
        startup_hook=_log_workflow_subprocess_start,
    ),
    StandaloneSubprocessSpec(
        flag="--map-navigation-worker",
        module_name="services.map_navigation.subprocess_runner",
        callable_name="run_map_navigation_subprocess_standalone",
        logger_name="MAP_NAVIGATION_SUBPROCESS",
        error_label="地图导航子进程",
        log_level=logging.INFO,
        log_format="%(asctime)s - %(levelname)s - [pid=%(process)d] - [%(funcName)s:%(lineno)d] - %(message)s",
        args_factory=_build_map_navigation_subprocess_args,
        startup_hook=_log_map_navigation_subprocess_start,
    ),
    StandaloneSubprocessSpec(
        flag="--mcp-server",
        module_name="services.mcp.mcp_openai_server",
        callable_name="main",
        logger_name="MCP_SUBPROCESS",
        error_label="MCP子进程",
        log_level=logging.INFO,
        log_format="%(asctime)s - %(levelname)s - [pid=%(process)d] - [%(module)s:%(lineno)d] - %(message)s",
    ),
)

_IS_STANDALONE_SUBPROCESS = is_standalone_subprocess_active(
    sys.argv,
    _STANDALONE_SUBPROCESS_SPECS,
)

if run_standalone_subprocess(sys.argv, _STANDALONE_SUBPROCESS_SPECS):
    sys.exit(0)

import json   # 用于JSON数据处理

import multiprocessing as _mp
_mp.freeze_support()  # 支持打包后的 exe

# 判断是否为子进程（包括独立 worker / multiprocessing 子进程）
if _IS_STANDALONE_SUBPROCESS or _mp.current_process().name != 'MainProcess':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - [pid=%(process)d] - [%(module)s:%(lineno)d] - %(message)s'
    )
    if not _IS_STANDALONE_SUBPROCESS:  # 避免与独立入口重复日志
        logging.info(f"[子进程隔离] {_mp.current_process().name} 检测到，跳过 main.py 主程序代码")
    # 不要使用 sys.exit()，让模块加载自然完成，multiprocessing 会处理后续
    # 通过设置一个标志来跳过后续代码
    _IS_SUBPROCESS = True

    class _FakeQtClass:
        """假的 Qt 类，用于子进程中占位"""
        def __init__(self, *args, **kwargs):
            pass
        def __getattr__(self, name):
            return _FakeQtClass()

    # 创建假的 Qt 模块和类
    class _FakeSignal:
        """假的 Signal 类"""
        def __init__(self, *args, **kwargs):
            pass
        def emit(self, *args, **kwargs):
            pass
        def connect(self, *args, **kwargs):
            pass

    # 创建一个通用的假枚举类
    class _FakeEnum:
        """假的枚举类，支持任意属性访问"""
        def __getattr__(self, name):
            return _FakeEnum()
        def __call__(self, *args, **kwargs):
            return _FakeEnum()

    # 注入假的 Qt 类到全局命名空间（用于类定义）
    # QtCore 类
    QThread = _FakeQtClass
    QObject = _FakeQtClass
    Signal = _FakeSignal
    QTimer = _FakeQtClass
    Qt = _FakeEnum()  # 支持 Qt.xxx 访问

    # QtWidgets 类
    QApplication = _FakeQtClass
    QMessageBox = _FakeEnum()  # 支持 QMessageBox.Icon.Critical 等
    QDialog = _FakeQtClass
    QLineEdit = _FakeQtClass
    QLabel = _FakeQtClass
    QPushButton = _FakeQtClass
    QVBoxLayout = _FakeQtClass
    QHBoxLayout = _FakeQtClass
    QSpacerItem = _FakeQtClass
    QSizePolicy = _FakeEnum()
    QDialogButtonBox = _FakeEnum()
    QSystemTrayIcon = _FakeEnum()  # 支持 QSystemTrayIcon.MessageIcon.Information 等
    QMenu = _FakeQtClass

    # QtGui 类
    QAction = _FakeQtClass
    QIcon = _FakeQtClass
    QColor = _FakeQtClass

    logging.info(f"[子进程隔离] 已创建 Qt 类占位符，避免加载 PySide6")
else:
    _IS_SUBPROCESS = False
# ============================================================

# Nuitka hint: include OLA package for plugin system
try:
    import OLA  # noqa: F401 - 仅用于Nuitka包含提示
except ImportError:
    pass  # 开发环境可能找不到,忽略

logger = logging.getLogger(__name__)
from app_core.mouse_runtime import mouse_move_fixer

# 工具 修复：设置虚拟环境路径，确保使用 venv 中的依赖
def setup_virtual_environment():
    return ensure_project_main_runtime(
        entry_file=__file__,
        argv=sys.argv[1:],
        logger=logger,
        runtime_label="主进程",
    )

# 设置虚拟环境
setup_virtual_environment()

import datetime # <-- Import datetime
from datetime import datetime as dt, timezone # <-- 添加timezone用于UTC时间处理
import glob     # <-- Import glob

import time   # <-- Import time for sleep in listener
import threading # <-- Import threading for async OCR initialization
import socket    # <-- 添加socket导入用于网络连接检查
import secrets   # <-- 添加secrets导入用于生成会话令牌
import base64    # <-- 添加base64导入用于加密
import subprocess  # <-- Used for safe Windows command-line quoting
from typing import Optional, Dict, Tuple, Any, List
from traceback import format_exception # <-- ADDED: For global_exception_handler

# --- ADDED: Licensing & HTTP Imports ---
import requests
import platform
import uuid
import hashlib
import hmac
import urllib3 # To disable SSL warnings if needed
try:
    from urllib3.util import connection as _urllib3_connection

    _urllib3_connection.allowed_gai_family = lambda: socket.AF_INET
except Exception:
    pass
# -------------------------------------

# --- REMOVED: Unused import publish dialog ---

# 添加当前目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
    logger.info(f"已添加 {current_dir} 到 Python 路径")

# --- ADDED: Import keyboard library ---
try:
    import keyboard
    KEYBOARD_LIB_AVAILABLE = True
    logging.info("keyboard 库已成功导入")
except ImportError:
    KEYBOARD_LIB_AVAILABLE = False
    logging.warning("'keyboard' 库未安装，全局热键功能将不可用。请运行 'pip install keyboard'。")

# --- ADDED: Check admin privileges ---
def is_admin():
    """检查是否以管理员权限运行

    Returns:
        bool: True表示具有管理员权限，False表示没有
    """
    try:
        import ctypes
        # IsUserAnAdmin 在所有Windows版本中都可用
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except AttributeError:
        # 极少数情况下API不可用（例如非常老的Windows版本）
        logging.warning("IsUserAnAdmin API 不可用，假设无管理员权限")
        return False
    except Exception as e:
        # 捕获所有其他异常
        logging.error(f"检查管理员权限时发生异常: {e}")
        return False

def request_admin_privileges():
    """请求管理员权限（已废弃，使用自动提权逻辑）

    注意：此函数已被自动提权逻辑替代，保留仅为向后兼容
    """
    logging.warning("request_admin_privileges() 已废弃，请使用自动提权逻辑")
    return is_admin()

def show_admin_privilege_dialog():
    """显示管理员权限提示对话框"""
    from PySide6.QtWidgets import QMessageBox, QApplication

    # 确保有QApplication实例
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    msg = QMessageBox()
    msg.setWindowTitle("需要管理员权限")
    msg.setIcon(QMessageBox.Icon.Information)
    msg.setText("检测到程序未以管理员权限运行")
    msg.setInformativeText(
        "为了使用全局热键功能（在主窗口未激活时也能使用F9/F10），\n"
        "程序需要管理员权限。\n\n"
        "您可以选择：\n"
        "• 重新以管理员身份运行（推荐）\n"
        "• 继续使用（仅在主窗口激活时热键有效）"
    )

    restart_btn = msg.addButton("重新以管理员身份运行", QMessageBox.ButtonRole.AcceptRole)
    continue_btn = msg.addButton("继续使用", QMessageBox.ButtonRole.RejectRole)

    msg.setDefaultButton(restart_btn)
    place_dialog_on_screen(msg, reference_widget=app.activeWindow() if app is not None else None)
    msg.exec()

    if msg.clickedButton() == restart_btn:
        return True
    else:
        return False
# ------------------------------------

# --- ADDED: For GetClientRect ---
from ctypes import wintypes
# ------------------------------
from app_core import license_runtime as app_license_runtime
from app_core import license_store as app_license_store
from app_core import runtime_security as app_runtime_security
from app_core import logging_runtime as app_logging_runtime


def _trim_main_process_memory() -> float:
    """尽量回收主进程工作集，返回估算释放量（MB）。"""
    memory_before = None
    memory_after = None
    process = None

    try:
        import psutil
        process = psutil.Process()
        memory_before = process.memory_info().rss / 1024 / 1024
    except Exception:
        process = None

    try:
        import gc
        gc.collect()
    except Exception:
        pass

    if os.name == "nt":
        try:
            import ctypes

            try:
                msvcrt = ctypes.CDLL("msvcrt")
                if hasattr(msvcrt, "_heapmin"):
                    msvcrt._heapmin()
            except Exception:
                pass

            try:
                kernel32 = ctypes.windll.kernel32
                psapi = ctypes.windll.psapi
                current_process = kernel32.GetCurrentProcess()
                psapi.EmptyWorkingSet(current_process)
            except Exception:
                pass
        except Exception:
            pass

    if process is not None:
        try:
            memory_after = process.memory_info().rss / 1024 / 1024
        except Exception:
            memory_after = None

    if memory_before is not None and memory_after is not None:
        return memory_before - memory_after
    return 0.0


class MainProcessMemoryWatchdog:
    """Lightweight main-process memory watchdog.

    Keeps UI animation enabled, and only performs conservative cleanup when RSS
    crosses a soft limit while workflow is idle.
    """

    def __init__(self, task_state_manager=None):
        self._task_state_manager = task_state_manager
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread = None
        self._running = False
        self._check_interval_sec = max(5.0, float(os.getenv("LCA_MAIN_MEM_WATCHDOG_INTERVAL_SEC", "20") or 20))
        self._soft_limit_mb = max(256.0, float(os.getenv("LCA_MAIN_MEM_WATCHDOG_THRESHOLD_MB", "700") or 700))
        self._last_cleanup_ts = 0.0
        self._min_cleanup_gap_sec = max(10.0, float(os.getenv("LCA_MAIN_MEM_WATCHDOG_GAP_SEC", "60") or 60))
        self._last_rss_mb = 0.0
        self._last_diag_ts = 0.0
        self._diag_growth_trigger_mb = max(
            16.0,
            float(os.getenv("LCA_MAIN_MEM_DIAG_GROWTH_MB", "64") or 64),
        )
        self._diag_min_interval_sec = max(
            15.0,
            float(os.getenv("LCA_MAIN_MEM_DIAG_INTERVAL_SEC", "120") or 120),
        )

    def start(self) -> bool:
        if self._running:
            return True
        self._stop_event.clear()
        self._wake_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="MainMemoryWatchdog",
            daemon=True,
        )
        self._thread.start()
        self._running = True
        logging.info(
            "[内存巡检] 已启动 (interval=%.0fs, soft_limit=%.0fMB)",
            self._check_interval_sec,
            self._soft_limit_mb,
        )
        return True

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            try:
                thread.join(timeout=max(0.1, float(timeout)))
            except Exception:
                pass
        self._thread = None
        self._running = False

    def request_check(self) -> None:
        self._wake_event.set()

    def _is_workflow_running(self) -> bool:
        manager = self._task_state_manager
        if manager is None:
            return False
        try:
            state = str(getattr(manager, "_current_state", "") or "").strip().lower()
            return state in {"starting", "running", "stopping"}
        except Exception:
            return False

    @staticmethod
    def _get_rss_mb() -> float:
        try:
            import psutil

            return float(psutil.Process().memory_info().rss) / 1024.0 / 1024.0
        except Exception:
            return 0.0

    @staticmethod
    def _get_private_mb() -> float:
        try:
            import psutil

            process = psutil.Process()
            full = process.memory_full_info()
            if hasattr(full, "uss"):
                return float(full.uss) / 1024.0 / 1024.0
            if hasattr(full, "private"):
                return float(full.private) / 1024.0 / 1024.0
        except Exception:
            pass
        return 0.0

    def _log_idle_memory_diagnostics(self, rss_mb: float) -> None:
        now = time.time()
        last_rss = float(self._last_rss_mb or 0.0)
        delta = rss_mb - last_rss if last_rss > 0.0 else 0.0
        should_log = (
            (delta >= self._diag_growth_trigger_mb)
            and ((now - float(self._last_diag_ts or 0.0)) >= self._diag_min_interval_sec)
        )
        if not should_log:
            return
        self._last_diag_ts = now

        private_mb = self._get_private_mb()
        thread_count = 0
        try:
            thread_count = int(threading.active_count())
        except Exception:
            thread_count = 0

        line_stats = None
        try:
            from ui.workflow_parts.connection_line import get_line_animation_stats
            line_stats = get_line_animation_stats()
        except Exception:
            line_stats = None

        card_stats = None
        try:
            from ui.workflow_parts.task_card import TaskCard
            card_stats = TaskCard.get_gradient_animation_stats()
        except Exception:
            card_stats = None

        gc_counts = None
        try:
            import gc
            gc_counts = tuple(int(v) for v in gc.get_count())
        except Exception:
            gc_counts = None

        logging.warning(
            "[内存诊断] idle_rss=%.1fMB delta=%.1fMB private=%.1fMB threads=%s line_anim=%s card_anim=%s gc=%s",
            rss_mb,
            delta,
            private_mb,
            thread_count,
            line_stats,
            card_stats,
            gc_counts,
        )

    def _cleanup_if_needed(self, rss_mb: float) -> None:
        if rss_mb <= self._soft_limit_mb:
            return
        now = time.time()
        if (now - float(self._last_cleanup_ts)) < self._min_cleanup_gap_sec:
            return
        self._last_cleanup_ts = now

        before = rss_mb
        try:
            from utils.runtime_image_cleanup import cleanup_runtime_image_memory

            cleanup_runtime_image_memory(
                reason="watchdog",
                cleanup_screenshot_engines=False,
                cleanup_template_cache=True,
            )
        except Exception:
            pass

        try:
            trimmed = _trim_main_process_memory()
            if trimmed > 0.5:
                logging.info("[内存巡检] 主进程修剪释放约 %.1f MB", trimmed)
        except Exception:
            pass

        after = self._get_rss_mb()
        if after > 0:
            logging.info("[内存巡检] RSS: %.1f MB -> %.1f MB", before, after)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if not self._is_workflow_running():
                    rss_mb = self._get_rss_mb()
                    if rss_mb > 0:
                        self._log_idle_memory_diagnostics(rss_mb)
                        self._cleanup_if_needed(rss_mb)
                        self._last_rss_mb = rss_mb
            except Exception as exc:
                logging.debug(f"[内存巡检] 处理异常: {exc}")

            self._wake_event.wait(timeout=self._check_interval_sec)
            self._wake_event.clear()
# --- Constants for Licensing ---
#  防逆向优化：混淆敏感信息
# psutil 已改为延迟导入（在需要时 import），减少启动内存



#  增强反调试检测（严格模式，检测到威胁直接退出）
def _0x4a2b():
    """兼容保留：现已停用反调试/反反编译检测。"""
    return False

#  混淆字符串解码器
def _0x7c9d(_data):
    """混淆数据解码 - 双重base64解码"""
    try:
        # 第一次base64解码
        _first = base64.b64decode(_data).decode('utf-8')
        # 第二次base64解码
        _result = base64.b64decode(_first).decode('utf-8')
        return _result
    except:
        return ""

#  开源版占位服务器配置 - 双重base64编码
_0x1234 = "YUhSMGNITTZMeTlsZUdGdGNHeGxMbWx1ZG1Gc2FXUT0="  # https://example.invalid
_0x5678 = "YUhSMGNITTZMeTlsZUdGdGNHeGxMbWx1ZG1Gc2FXUT0="  # https://example.invalid

def _0xdef0():
    """获取混淆后的服务器地址"""
    _0x4a2b()  # 反调试检测
    _auth = _0x7c9d(_0x1234)
    _config = _0x7c9d(_0x5678)
    return _auth, _config

# 锁定 安全改进: 不在代码中硬编码真实服务器地址
# 从环境变量或仅内置默认值加载服务器配置，不自动生成敏感配置文件
DEFAULT_SERVER_URL = os.getenv("AUTH_SERVER_URL", "https://example.invalid")  # 从环境变量读取
DEFAULT_SERVER_CONFIG_URL = os.getenv("CONFIG_SERVER_URL", "https://example.invalid")  # 从环境变量读取

# 内置的真实服务器地址 (仅程序内部使用) - 已混淆
_INTERNAL_AUTH_SERVER, _INTERNAL_CONFIG_SERVER = _0xdef0()

#  优化的代码完整性检查
def _0xcafe():
    """兼容保留：现已停用代码完整性检查。"""
    return True

#  内存保护机制
def _0xf00d():
    """兼容保留：现已停用内存保护检查。"""
    return False

#  增强的字节码保护和代码混淆
def _0x1337():
    """兼容保留：现已停用字节码保护与动态混淆。"""
    return True

#  字节码完整性检查器
def _0xbyte():
    """兼容保留：现已停用字节码完整性检查。"""
    return False

#  高级Python反编译保护
def _report_anti_decompile_threats(threats, source="反编译保护"):
    """兼容保留：现已停用反编译威胁上报。"""
    return False

def _0xpyprotect():
    """兼容保留：现已停用 Python 反编译保护。"""
    return False

#  多重虚假分支混淆
def _0xdead():
    """虚假验证路径1 - 永远不会被执行"""
    _fake_server = "https://fake.example.com"
    _fake_key = "FAKE-KEY-12345"
    return False, 404, "fake"

def _0xbabe():
    """虚假验证路径2 - 干扰分析"""
    _fake_hwid = "0" * 64
    _fake_salt = "fake_salt_2024"
    _fake_hash = hashlib.sha256(f"{_fake_hwid}{_fake_salt}".encode()).hexdigest()
    return False, 403, "invalid"

def _0xface():
    """虚假验证路径3 - 混淆真实逻辑"""
    _fake_validation = True
    for i in range(10):
        _fake_validation = not _fake_validation
    return _fake_validation, 200, "success"

# 内置服务器地址配置 - 与前文混淆配置保持同源，避免域名分叉
_INTERNAL_AUTH_SERVER, _INTERNAL_CONFIG_SERVER = _0xdef0()

# 读取服务器配置文件
def load_server_config():
    """加载服务器配置（仅使用内置配置；忽略外部文件）"""
    config_file = "server_config.json"

    if os.path.exists(config_file):
        logging.warning(f"检测到 {config_file}，但已忽略外部配置；仅使用内置服务器配置。")

    return {
        "auth_server_url": _INTERNAL_AUTH_SERVER,
        "config_server_url": _INTERNAL_CONFIG_SERVER,
        "verify_ssl": True,
        "description": "内置服务器配置"
    }

server_config = load_server_config()
SERVER_URL = server_config.get("auth_server_url", _INTERNAL_AUTH_SERVER)
SERVER_CONFIG_URL = server_config.get("config_server_url", _INTERNAL_CONFIG_SERVER)
# 锁定 不再硬编码任务服务器地址
TASK_SERVER_URL = server_config.get("task_server_url", _INTERNAL_CONFIG_SERVER)

# 强制要求服务地址使用 HTTPS 协议
def _enforce_https_url(url_name: str, url_value: str):
    if not isinstance(url_value, str) or not url_value.lower().startswith("https://"):
        logging.critical(f"{url_name} 必须使用 https:// 协议地址: {url_value}")
        os._exit(1)

# 强制要求服务域名在白名单内
def _enforce_whitelisted_host(url_name: str, url_value: str, allowed_hosts: set):
    try:
        parsed = urlparse(url_value)
        host = parsed.hostname
    except Exception:
        host = None
    if not host or host not in allowed_hosts:
        logging.critical(f"{url_name} 域名不在白名单内: {url_value}")
        os._exit(1)

_ALLOWED_HOSTS = {urlparse(_INTERNAL_AUTH_SERVER).hostname, urlparse(_INTERNAL_CONFIG_SERVER).hostname}
_ALLOWED_HOSTS = {h for h in _ALLOWED_HOSTS if h}
if not _ALLOWED_HOSTS:
    logging.critical("服务域名白名单为空，程序无法启动")
    os._exit(1)

_enforce_https_url("SERVER_URL", SERVER_URL)
_enforce_https_url("SERVER_CONFIG_URL", SERVER_CONFIG_URL)
_enforce_https_url("TASK_SERVER_URL", TASK_SERVER_URL)

_enforce_whitelisted_host("SERVER_URL", SERVER_URL, _ALLOWED_HOSTS)
_enforce_whitelisted_host("SERVER_CONFIG_URL", SERVER_CONFIG_URL, _ALLOWED_HOSTS)
_enforce_whitelisted_host("TASK_SERVER_URL", TASK_SERVER_URL, _ALLOWED_HOSTS)

AUTH_ENDPOINT = "/api/ping_auth"  # 使用服务器实际存在的编辑器验证端点
LICENSE_FILE = app_license_store.LICENSE_FILE

# --- CAUTION: SSL Verification ---
# 在开发环境中使用自签名证书 (adhoc) 时，可能需要禁用 SSL 验证。
# 在生产环境中，你应该使用有效的证书，并将此设为 True。
VERIFY_SSL = server_config.get("verify_ssl", True)  # True 使用系统默认 CA 证书校验
if VERIFY_SSL is not True and (not isinstance(VERIFY_SSL, str) or not VERIFY_SSL.strip()):
    logging.critical("VERIFY_SSL 必须为 True 或非空证书文件路径")
    os._exit(1)




# --- 严禁通过 verify=False 关闭 SSL 验证 ---
# if not VERIFY_SSL: # Check if VERIFY_SSL is explicitly False, not just any non-True value
if VERIFY_SSL is False:
    logging.critical("禁止关闭 SSL 验证，VERIFY_SSL=False 不被允许")
    os._exit(1)
elif VERIFY_SSL is True:
    logging.info("将使用系统默认 CA 证书进行 SSL 验证")
elif isinstance(VERIFY_SSL, str):
    # 添加调试信息
    current_dir = os.getcwd()
    abs_cert_path = os.path.abspath(VERIFY_SSL)
    logging.debug(f"当前工作目录: {current_dir}")
    logging.debug(f"证书文件相对路径: {VERIFY_SSL}")
    logging.debug(f"证书文件绝对路径: {abs_cert_path}")

    if not os.path.exists(VERIFY_SSL):
        logging.critical(f"指定 SSL 证书文件不存在: {VERIFY_SSL}，程序无法启动")
        os._exit(1)
    else:
        logging.info(f"将使用指定的证书文件进行 SSL 验证: {VERIFY_SSL}")
# ------------------------------------------

# --- ADDED: Safe Error Message Function ---
def sanitize_error_message(error_msg: str) -> str:
    """
    清理错误信息中的敏感内容，防止IP地址、端口等敏感信息泄露到日志中
    """
    import re
    
    # 移除IP地址和端口信息的模式
    patterns = [
        # HTTPConnectionPool模式: host='IP', port=PORT
        r"host='[\d\.]+', port=\d+",
        # 直接的IP:PORT模式  
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+",
        # HTTPConnectionPool完整信息
        r"HTTPConnectionPool\(host='[^']+', port=\d+\)",
        # URL中的IP地址
        r"https?://[\d\.]+:\d+",
        # 其他可能的敏感路径
        r"/api/[a-zA-Z_/]+",
    ]
    
    sanitized_msg = error_msg
    for pattern in patterns:
        sanitized_msg = re.sub(pattern, "[SERVER_INFO]", sanitized_msg)
    
    # 如果包含连接相关错误，提供更简洁的描述
    if "Read timed out" in sanitized_msg or "Connection" in sanitized_msg:
        return "连接服务器超时或网络不可用"
    elif "Max retries exceeded" in sanitized_msg:
        return "服务器连接重试次数已达上限"
    elif "Connection refused" in sanitized_msg:
        return "服务器拒绝连接"
    elif "Name or service not known" in sanitized_msg:
        return "服务器地址解析失败"
    
    try:
        from utils.log_message_translator import translate_log_message

        return translate_log_message(sanitized_msg)
    except Exception:
        return sanitized_msg

def sanitize_sensitive_data(data, data_type="unknown"):
    """
    清理敏感数据用于日志输出，防止CSRF token、许可证密钥等敏感信息泄露
    """
    import re

    if isinstance(data, dict):
        sanitized = {}
        for key, value in data.items():
            key_lower = key.lower()
            if any(sensitive in key_lower for sensitive in ['csrf', 'token', 'key', 'password', 'secret', 'auth', 'hw_id']):
                if isinstance(value, str) and len(value) > 8:
                    sanitized[key] = f"{value[:4]}***{value[-4:]}"
                else:
                    sanitized[key] = "***"
            elif key_lower == 'set-cookie' and isinstance(value, str):
                # 特殊处理set-cookie头部，清理其中的敏感token
                sanitized_cookie = re.sub(r'csrftoken=[^;,\s]*', 'csrftoken=***', value)
                sanitized_cookie = re.sub(r'sessionid=[^;,\s]*', 'sessionid=***', sanitized_cookie)
                sanitized_cookie = re.sub(r'token=[^;,\s]*', 'token=***', sanitized_cookie, flags=re.IGNORECASE)
                sanitized[key] = sanitized_cookie
            else:
                sanitized[key] = value
        return sanitized
    elif isinstance(data, str):
        # 清理字符串中的敏感信息
        data = re.sub(r'csrftoken=[^;,\s]*', 'csrftoken=***', data)
        data = re.sub(r'sessionid=[^;,\s]*', 'sessionid=***', data)
        data = re.sub(r'token=[^&\s]*', 'token=***', data, flags=re.IGNORECASE)
        data = re.sub(r'key=[^&\s]*', 'key=***', data, flags=re.IGNORECASE)
        data = re.sub(r'hw_id=[^&\s]*', 'hw_id=***', data, flags=re.IGNORECASE)
        return data
    else:
        return str(data)


def _cleanup_temp_files():
    """清理程序产生的临时文件"""
    import tempfile

    current_time = time.time()
    max_age_seconds = 3 * 24 * 3600  # 3天

    # 1. 清理工作流临时备份目录
    workflow_temp_dir = os.path.join(tempfile.gettempdir(), 'workflow_temp_backups')
    if os.path.exists(workflow_temp_dir):
        try:
            deleted_count = 0
            for filename in os.listdir(workflow_temp_dir):
                filepath = os.path.join(workflow_temp_dir, filename)
                try:
                    file_age = current_time - os.path.getmtime(filepath)
                    if file_age > max_age_seconds:
                        os.remove(filepath)
                        deleted_count += 1
                except (OSError, PermissionError):
                    pass
            if deleted_count > 0:
                logger.info(f"临时备份清理: 删除 {deleted_count} 个过期文件")
        except (OSError, PermissionError) as e:
            logger.warning(f"临时备份清理失败: {e}")

    # 2. 清理OCR测试临时文件（记事本打开的txt文件）
    temp_dir = tempfile.gettempdir()
    try:
        for filename in os.listdir(temp_dir):
            if filename.startswith('tmp') and filename.endswith('.txt'):
                filepath = os.path.join(temp_dir, filename)
                try:
                    file_age = current_time - os.path.getmtime(filepath)
                    # 超过1天的临时txt文件
                    if file_age > 24 * 3600:
                        os.remove(filepath)
                except (OSError, PermissionError):
                    pass
    except (OSError, PermissionError):
        pass


# --- Call Setup Early in the script ---
app_logging_runtime.setup_logging_and_cleanup(cleanup_temp_files_cb=_cleanup_temp_files)

# is_admin 函数已在文件开头定义（第253行），无需重复定义

def check_uac_enabled():
    """检查UAC是否启用

    Returns:
        bool: True表示UAC已启用，False表示UAC已禁用
    """
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
            0,
            winreg.KEY_READ
        )
        value, _ = winreg.QueryValueEx(key, "EnableLUA")
        winreg.CloseKey(key)
        is_enabled = (value == 1)
        logging.debug(f"UAC状态检测: EnableLUA = {value}, UAC启用 = {is_enabled}")
        return is_enabled
    except Exception as e:
        logging.warning(f"无法检测UAC状态: {e}，默认假设UAC已启用")
        return True  # 默认假设UAC启用
# --- END is_admin definition ---

_SINGLE_INSTANCE_MUTEX_NAME = "Local\\LCA_MainInstanceMutex"
_single_instance_mutex_handle = None


def _show_existing_instance_hint():
    """提示用户已有实例在运行。"""
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            "LCA 已在运行。\n请从系统托盘恢复窗口。",
            "LCA",
            0x00000040,  # MB_ICONINFORMATION
        )
    except Exception:
        pass


def _is_existing_instance_running() -> bool:
    """仅探测是否存在已持有互斥锁的实例，不占用互斥锁。"""
    if os.name != "nt":
        return False

    try:
        kernel32 = ctypes.windll.kernel32
        synchronize = 0x00100000  # SYNCHRONIZE
        mutex_handle = kernel32.OpenMutexW(synchronize, False, _SINGLE_INSTANCE_MUTEX_NAME)
        if mutex_handle:
            kernel32.CloseHandle(mutex_handle)
            return True
    except Exception:
        return False

    return False


def _acquire_single_instance_lock() -> bool:
    """获取主实例互斥锁，返回是否成功。"""
    global _single_instance_mutex_handle
    if os.name != "nt":
        return True

    try:
        kernel32 = ctypes.windll.kernel32
        mutex_handle = kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_MUTEX_NAME)
        if not mutex_handle:
            logging.error("主实例互斥锁创建失败，启动终止")
            return False

        last_error = kernel32.GetLastError()
        already_exists = 183  # ERROR_ALREADY_EXISTS
        if last_error == already_exists:
            kernel32.CloseHandle(mutex_handle)
            return False

        _single_instance_mutex_handle = mutex_handle
        return True
    except Exception as e:
        logging.error(f"主实例互斥锁初始化异常: {e}")
        return False


def _release_single_instance_lock():
    """释放主实例互斥锁。"""
    global _single_instance_mutex_handle
    if os.name != "nt":
        return

    try:
        if _single_instance_mutex_handle:
            ctypes.windll.kernel32.CloseHandle(_single_instance_mutex_handle)
            _single_instance_mutex_handle = None
    except Exception:
        _single_instance_mutex_handle = None

# --- Admin elevation block --- #
# 自动提权逻辑：确保程序以管理员权限运行
# 兼容性：Windows 7/8/8.1/10/11 及 Server 版本
# <<<< UNCOMMENTED START >>>>
if os.name == "nt" and not _IS_SUBPROCESS and _is_existing_instance_running():
    logging.warning("检测到已有实例在运行，当前启动请求已取消。")
    _show_existing_instance_hint()
    try:
        sys.exit(0)
    finally:
        os._exit(0)

if os.name == 'nt' and not is_admin():
    reason_str = "程序需要管理员权限才能确保所有功能正常运行（全局快捷键、窗口操作等）"
    logging.warning(f"检测到程序未以管理员权限运行，正在尝试自动提权...")
    logging.info(f"  提权原因: {reason_str}")

    # 检测系统信息
    try:
        import platform
        win_version = platform.win32_ver()
        logging.info(f"  Windows版本: {win_version[0]} {win_version[1]} Build {win_version[2]}")
    except:
        logging.info("  无法检测Windows版本信息")

    # 添加安全检查，确保在任何情况下都能正确退出
    elevation_success = False
    elevation_error = None

    try:
        # 检测是否为打包环境
        # Nuitka 打包后：
        #   - sys.argv[0] 指向 main.exe（这是我们需要的）
        #   - sys.executable 可能指向内部的 python.exe（错误的）
        # PyInstaller 打包后：
        #   - sys.executable 指向 exe 文件
        #   - sys.frozen = True

        # 优先使用 sys.argv[0] 获取主程序路径
        main_exe_path = os.path.abspath(sys.argv[0])
        sys_exe_path = os.path.abspath(sys.executable)
        try:
            sys_exe_path = os.path.realpath(sys_exe_path)
        except Exception:
            pass

        is_nuitka = '__compiled__' in dir(sys.modules.get('__main__', None))
        is_pyinstaller = getattr(sys, 'frozen', False)
        is_exe_file = main_exe_path.lower().endswith('.exe')

        if is_exe_file or is_nuitka or is_pyinstaller:
            # 打包环境
            # Nuitka: 使用 sys.argv[0] 获取 main.exe 路径
            # PyInstaller: 使用 sys.executable
            if is_nuitka and is_exe_file:
                executable_to_run = main_exe_path
                packager = "Nuitka"
            elif is_pyinstaller:
                executable_to_run = sys_exe_path
                packager = "PyInstaller"
            else:
                # 兜底：如果 argv[0] 是 exe 就用它
                executable_to_run = main_exe_path if is_exe_file else sys_exe_path
                packager = "EXE"

            original_args = sys.argv[1:]
            params = subprocess.list2cmdline(original_args) if original_args else ""
            logging.info(f"  检测到打包环境（{packager}），使用exe文件进行提权重启")
        else:
            # 开发环境：使用python解释器
            executable_to_run = sys_exe_path
            # 开发环境使用当前脚本的绝对路径
            script_path = os.path.abspath(__file__)
            original_args = sys.argv[1:]
            params = subprocess.list2cmdline([script_path] + original_args)
            logging.info("  检测到开发环境（Python），使用python.exe进行提权重启")

        logging.info(f"  可执行文件: {executable_to_run}")
        logging.info(f"  启动参数: {params if params else '(无)'}")

        # 尝试提权 - ShellExecuteW
        # 返回值含义：
        #   > 32: 成功
        #   0-32: 失败（具体错误码见MSDN文档）
        result = ctypes.windll.shell32.ShellExecuteW(
            None,           # hwnd
            "runas",        # lpOperation - 以管理员身份运行
            executable_to_run,  # lpFile
            params,         # lpParameters
            None,           # lpDirectory - 使用当前目录
            1               # nShowCmd - SW_SHOWNORMAL
        )

        if result > 32:
            # 成功：ShellExecuteW 返回值 > 32 表示成功
            logging.info(f"提权请求已成功发送（返回值: {result}）")
            logging.info("  UAC对话框应已显示，等待用户确认...")
            elevation_success = True

            # 给UAC对话框一些时间显示
            import time
            time.sleep(1)
        else:
            # 失败：ShellExecuteW 返回值 <= 32 表示错误
            error_messages = {
                0: "内存不足或资源耗尽",
                2: "文件未找到",
                3: "路径未找到",
                5: "访问被拒绝",
                8: "内存不足",
                10: "Windows版本错误",
                11: "EXE文件无效",
                26: "共享冲突",
                27: "文件名关联不完整或无效",
                28: "DDE事务超时",
                29: "DDE事务失败",
                30: "DDE事务繁忙",
                31: "没有关联的应用程序",
                32: "DLL未找到"
            }
            error_msg = error_messages.get(result, f"未知错误码 {result}")
            elevation_error = f"ShellExecuteW失败: {error_msg} (返回值: {result})"
            logging.error(f"提权请求失败: {elevation_error}")

            # 用户可能取消了UAC对话框
            if result == 5:
                logging.warning("  可能原因：用户取消了UAC提权对话框，或UAC被管理员策略禁用")

    except AttributeError as e:
        elevation_error = f"ShellExecuteW API不可用: {e}"
        logging.error(f"提权失败: {elevation_error}")
        logging.error("  当前Windows版本可能不支持此API")

    except Exception as e:
        elevation_error = f"未知异常: {e}"
        logging.error(f"请求管理员权限时发生异常: {elevation_error}", exc_info=True)
        logging.error("  建议：请尝试手动右键 -> 以管理员身份运行此程序")

    # 关键修复：无论提权是否成功，都必须退出当前进程
    # 原因：如果提权成功，新的管理员进程将启动；当前进程必须退出以避免双实例
    logging.info("=" * 80)
    if elevation_success:
        logging.info("提权流程已完成，等待管理员权限进程启动")
        logging.info("  当前非管理员进程即将退出...")
    else:
        logging.warning("提权流程失败，程序无法以管理员权限运行")
        if elevation_error:
            logging.warning(f"  失败原因: {elevation_error}")
        logging.warning("  程序将退出，请手动以管理员身份运行")
    logging.info("=" * 80)

    try:
        sys.exit(0 if elevation_success else 1)
    finally:
        # 确保在任何情况下都能彻底退出（强制退出）
        os._exit(0 if elevation_success else 1)

elif os.name == 'nt':
    # 已经具有管理员权限
    if is_admin():
        logging.info("=" * 80)
        logging.info("程序已以管理员权限运行")
        logging.info("  全局快捷键和窗口操作功能可正常使用")
        logging.info("=" * 80)
    else:
        # 理论上不应该到达这里
        logging.critical("权限检查异常：is_admin() 返回 False 但未进入提权流程。为安全起见退出。")
        try:
            sys.exit(1)
        finally:
            os._exit(1)

else:
    # 非Windows系统
    logging.info("检测到非Windows系统，跳过管理员权限检查")
# <<<< UNCOMMENTED END >>>>

get_hardware_id = _shared_get_hardware_id
_encrypt_license_key = app_license_store.encrypt_license_key
_decrypt_license_key = app_license_store.decrypt_license_key
load_local_license = app_license_store.load_local_license
save_local_license = app_license_store.save_local_license

def enforce_online_validation(hardware_id: str, license_key: str) -> tuple:
    """ 强制在线验证，禁止离线使用"""
    try:
        #  优化：减少重复的安全检查调用
        _0x4a2b()  # 反调试检测

        #  虚假分支混淆
        if len(hardware_id) == 0:  # 永远不会执行
            return _0xdead()

        logging.info("开始强制在线验证...")

        # 检查网络连接
        if not check_network_connectivity():
            logging.critical(" 强制在线验证失败：无网络连接，禁止离线使用")
            return False, 503, None

        # 执行在线验证（使用v2 API）
        is_valid, status_code, license_type, extra_info = validate_license_with_server_v2(hardware_id, license_key)

        if is_valid:
            # 生成会话令牌
            import secrets
            session_token = secrets.token_hex(32)
            sys._auth_session_token = session_token
            sys._last_validation_time = time.time()

            # 记录额外的验证信息
            validation_mode = extra_info.get('validation_mode', 'unknown')
            logging.info(f"强制在线验证成功(v2)，会话令牌已生成 - 验证模式: {validation_mode}")
            return True, status_code, license_type
        else:
            logging.critical(f" 强制在线验证失败：状态码 {status_code}")
            return False, status_code, None

    except Exception as e:
        logging.critical(f" 强制在线验证异常: {e}")
        return False, 500, None

def check_network_connectivity() -> bool:
    """检查网络连接性"""
    try:
        import socket
        # 尝试连接到多个知名服务器
        test_hosts = [
            ("8.8.8.8", 53),      # Google DNS
            ("1.1.1.1", 53),      # Cloudflare DNS
            ("208.67.222.222", 53) # OpenDNS
        ]

        for host, port in test_hosts:
            try:
                with socket.create_connection((host, port), timeout=3):
                    pass
                return True
            except:
                continue

        return False
    except Exception as e:
        logging.warning(f"网络连接检查异常: {e}")
        return False

def runtime_license_check():
    """运行时授权检查，防止打包后绕过授权验证"""
    try:
        # 检查授权验证标记
        if not hasattr(sys, '_license_validated') or not getattr(sys, '_license_validated', False):
            logging.critical(" 运行时授权检查失败：未找到有效的授权验证标记")
            return False

        # 检查硬件ID文件
        from utils.app_paths import get_hardware_id_path
        if not os.path.exists(get_hardware_id_path()):
            logging.critical(" 运行时授权检查失败：硬件ID文件不存在")
            return False

        #  强化：检查授权会话令牌
        if not hasattr(sys, '_auth_session_token') or not getattr(sys, '_auth_session_token', None):
            logging.critical(" 运行时授权检查失败：未找到有效的会话令牌")
            return False

        #  强化：检查最后验证时间
        if hasattr(sys, '_last_validation_time'):
            last_validation = getattr(sys, '_last_validation_time', 0)
            current_time = time.time()
            # 如果超过30分钟未验证，需要重新验证
            if current_time - last_validation > 1800:  # 30分钟
                logging.warning(" 运行时授权检查：验证时间过期，需要重新验证")
                return False

        return True
    except Exception as e:
        logging.critical(f" 运行时授权检查异常: {e}")
        return False


# ============================================================
# 插件授权后台监控线程
# ============================================================

_plugin_auth_monitor = None
_exit_cleanup_thread = None
_EXIT_CLEANUP_JOIN_TIMEOUT_SEC = 2.0


class PluginAuthorizationMonitor(threading.Thread):
    """
    插件授权后台监控线程
    - 随机间隔检查授权的有效性和时效性
    - 验证失败后重试3次
    - 重试失败后退出程序并弹窗提示
    """

    def __init__(self, hardware_id: str, license_key: str, app_instance=None):
        super().__init__(daemon=True)
        self.hardware_id = hardware_id
        self.license_key = license_key
        self.app_instance = app_instance  # QApplication 实例，用于弹窗
        self.running = True
        self._stop_event = threading.Event()
        self.max_retry = 3  # 最大重试次数
        self.min_check_interval = 300  # 最小检查间隔（秒） - 5分钟
        self.max_check_interval = 900  # 最大检查间隔（秒） - 15分钟
        logging.info("插件授权监控线程已初始化")

    def run(self):
        """线程主循环"""
        import random
        import time

        # 首次检查延迟
        initial_delay = random.randint(60, 180)  # 1-3分钟后首次检查
        logging.info(f"插件授权监控线程已启动，将在 {initial_delay} 秒后进行首次检查")
        if self._stop_event.wait(initial_delay):
            return

        while self.running and not self._stop_event.is_set():
            try:
                # 随机检查间隔
                check_interval = random.randint(self.min_check_interval, self.max_check_interval)
                logging.info(f"插件授权监控：下次检查将在 {check_interval} 秒后")

                # 执行授权验证
                retry_count = 0
                validation_success = False

                while retry_count < self.max_retry and not validation_success:
                    if self._stop_event.is_set():
                        return
                    if retry_count > 0:
                        logging.warning(f"插件授权验证失败，正在进行第 {retry_count + 1} 次重试...")
                        if self._stop_event.wait(5):
                            return

                    try:
                        logging.info("插件授权监控：开始后台在线验证...")
                        is_valid, status_code, license_type = enforce_online_validation(
                            self.hardware_id,
                            self.license_key
                        )

                        if is_valid:
                            logging.info(f"插件授权验证成功，授权类型: {license_type}")
                            validation_success = True
                        else:
                            logging.error(f"插件授权验证失败，状态码: {status_code}")
                            retry_count += 1
                    except Exception as e:
                        logging.error(f"插件授权验证异常: {e}", exc_info=True)
                        retry_count += 1

                # 检查验证结果
                if not validation_success:
                    logging.critical(f"插件授权验证失败，已重试 {self.max_retry} 次，程序将退出")
                    self._show_expiry_dialog_and_exit()
                    return  # 退出线程

                # 等待下次检查
                if self._stop_event.wait(check_interval):
                    return

            except Exception as e:
                logging.error(f"插件授权监控线程异常: {e}", exc_info=True)
                if self._stop_event.wait(60):
                    return  # 异常后等待1分钟再继续

    def stop(self):
        """停止监控线程"""
        self.running = False
        self._stop_event.set()
        logging.info("插件授权监控线程已停止")

    def _show_expiry_dialog_and_exit(self):
        """显示授权失效对话框并退出程序"""
        try:
            from PySide6.QtWidgets import QMessageBox, QApplication
            from PySide6.QtCore import QMetaObject, Qt, QTimer

            def show_dialog():
                """在主线程中显示对话框"""
                msg_box = QMessageBox()
                msg_box.setWindowTitle("插件授权已失效")
                msg_box.setIcon(QMessageBox.Icon.Critical)
                msg_box.setText(
                    "插件模式授权验证失败\n\n"
                    "您的授权码已失效或过期。\n"
                    "验证已重试3次均失败。\n\n"
                    "可能的原因：\n"
                    "- 授权码已过期\n"
                    "- 网络连接失败\n"
                    "- 服务器拒绝授权\n\n"
                    "程序将立即退出。"
                )
                msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
                msg_box.setWindowFlags(msg_box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
                place_dialog_on_screen(
                    msg_box,
                    reference_widget=QApplication.activeWindow() if QApplication.instance() else None,
                )
                msg_box.exec()

                # 强制退出程序
                logging.critical("用户确认授权失效对话框，程序即将退出...")
                QApplication.quit()
                os._exit(1)

            # 如果有 QApplication 实例，在主线程中显示对话框
            if self.app_instance and QApplication.instance():
                # 使用 QMetaObject.invokeMethod 在主线程中执行
                QMetaObject.invokeMethod(
                    self.app_instance,
                    "_plugin_auth_failed",
                    Qt.ConnectionType.QueuedConnection
                )

                # 由于 invokeMethod 可能不生效，我们也直接显示对话框
                QTimer.singleShot(100, show_dialog)
            else:
                # 没有 QApplication，直接退出
                logging.critical("插件授权失效，程序退出")
                os._exit(1)

        except Exception as e:
            logging.error(f"显示授权失效对话框失败: {e}", exc_info=True)
            # 无论如何都要退出
            os._exit(1)


def _start_plugin_license_monitor(hardware_id: str, license_key: str, app_instance) -> None:
    """启动插件授权监控线程（自动替换旧实例）。"""
    global _plugin_auth_monitor
    cleanup_license_monitoring()
    monitor = PluginAuthorizationMonitor(
        hardware_id=hardware_id,
        license_key=license_key,
        app_instance=app_instance,
    )
    monitor.start()
    _plugin_auth_monitor = monitor


def auto_detect_network_quality() -> dict:
    """自动检测网络质量并返回适合的配置"""
    try:
        import socket
        import time

        # 测试网络延迟和稳定性
        test_hosts = [
            ("8.8.8.8", 53),
            ("1.1.1.1", 53),
            ("208.67.222.222", 53)
        ]

        successful_tests = 0
        total_latency = 0

        for host, port in test_hosts:
            try:
                start_time = time.time()
                with socket.create_connection((host, port), timeout=5):
                    pass
                latency = (time.time() - start_time) * 1000  # 转换为毫秒
                total_latency += latency
                successful_tests += 1
            except:
                continue

        if successful_tests == 0:
            # 网络不可用，使用保守配置
            return {
                'interval': 900,
                'max_retries': 6,
                'base_delay': 3.0,
                'max_delay': 180.0,
                'failure_threshold': 10,
                'profile': 'offline'
            }

        # 【闪退修复】防止除零错误：检查test_hosts是否为空
        if not test_hosts or len(test_hosts) == 0:
            logger.warning("测试主机列表为空，使用默认网络配置")
            return {
                'interval': 1800,
                'max_retries': 3,
                'base_delay': 1.0,
                'max_delay': 60.0,
                'failure_threshold': 5,
                'profile': 'default'
            }

        success_rate = successful_tests / len(test_hosts)
        avg_latency = total_latency / successful_tests if successful_tests > 0 else 1000

        if success_rate >= 0.8 and avg_latency < 100:
            # 优秀网络
            return {
                'interval': 2400,
                'max_retries': 2,
                'base_delay': 1.0,
                'max_delay': 30.0,
                'failure_threshold': 3,
                'profile': 'excellent'
            }
        elif success_rate >= 0.6 and avg_latency < 300:
            # 良好网络
            return {
                'interval': 1800,
                'max_retries': 3,
                'base_delay': 1.0,
                'max_delay': 60.0,
                'failure_threshold': 5,
                'profile': 'good'
            }
        else:
            # 较差网络
            return {
                'interval': 1200,
                'max_retries': 5,
                'base_delay': 2.0,
                'max_delay': 120.0,
                'failure_threshold': 8,
                'profile': 'poor'
            }

    except Exception as e:
        logging.warning(f"网络质量检测失败: {e}，使用默认配置")
        return {
            'interval': 1800,
            'max_retries': 3,
            'base_delay': 1.0,
            'max_delay': 60.0,
            'failure_threshold': 5,
            'profile': 'default'
        }


def cleanup_license_monitoring():
    """清理许可证监控资源。"""
    global _plugin_auth_monitor
    monitor = _plugin_auth_monitor
    _plugin_auth_monitor = None
    if monitor is None:
        return

    try:
        monitor.stop()
    except Exception as e:
        logging.debug(f"停止插件授权监控线程时出错: {e}")

    try:
        if monitor.is_alive():
            monitor.join(timeout=2.0)
    except Exception as e:
        logging.debug(f"等待插件授权监控线程退出时出错: {e}")

# 注册程序退出时的清理函数
atexit.register(cleanup_license_monitoring)

def cleanup_yolo_runtime_resources(
    release_process: bool = True,
    compact_memory: bool = True,
) -> bool:
    """清理YOLO运行时资源（仅清理已存在实例，不创建新实例）。"""
    cleaned = False
    try:
        from utils.runtime_image_cleanup import cleanup_yolo_runtime_on_stop

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

def cleanup_runtime_state_variables():
    """清理主进程运行期标记变量，避免旧状态残留。"""
    try:
        runtime_marker_names = (
            "_auth_session_token",
            "_last_validation_time",
            "_license_validated",
            "_registration_verified",
            "_registration_hwid",
        )
        for marker_name in runtime_marker_names:
            try:
                if hasattr(sys, marker_name):
                    delattr(sys, marker_name)
            except Exception:
                pass
    except Exception as e:
        logging.debug(f"清理运行期标记变量时出错: {e}")

    try:
        global _SECURITY_CHECK_CACHE
        if isinstance(_SECURITY_CHECK_CACHE, dict):
            _SECURITY_CHECK_CACHE.clear()
    except Exception as e:
        logging.debug(f"清理安全检查缓存时出错: {e}")

    try:
        global _FUNC_TABLE
        if isinstance(_FUNC_TABLE, dict):
            _FUNC_TABLE.clear()
    except Exception as e:
        logging.debug(f"清理函数调用表时出错: {e}")

    try:
        global config
        if isinstance(config, dict):
            config.clear()
    except Exception as e:
        logging.debug(f"清理全局配置缓存时出错: {e}")

# 清理所有资源
def cleanup_all_resources():
    """清理所有全局资源"""
    try:
        # 清理输入模拟器缓存（含各类驱动实例）
        try:
            from utils.input_simulation import global_input_simulator_manager
            global_input_simulator_manager.clear_cache()
            logging.info("输入模拟器缓存已清理")
        except Exception as e:
            logging.debug(f"清理输入模拟器缓存时出错: {e}")

        # 清理前台输入驱动（包含 IbInputSimulator AHK worker）
        try:
            from utils.foreground_input_manager import get_foreground_input_manager
            fg_manager = get_foreground_input_manager()
            fg_manager.close()
            logging.info("前台输入驱动已清理")
        except Exception as e:
            logging.debug(f"清理前台输入驱动时出错: {e}")

        # 清理OCR服务池
        # 【插件模式隔离】插件模式下跳过OCR服务池清理
        try:
            from app_core.plugin_bridge import is_plugin_enabled
            plugin_enabled = is_plugin_enabled()
        except ImportError:
            plugin_enabled = False
        except Exception:
            plugin_enabled = True  # 异常时跳过清理

        if not plugin_enabled:
            try:
                from services.multiprocess_ocr_pool import get_existing_multiprocess_ocr_pool
                pool = get_existing_multiprocess_ocr_pool()
                if hasattr(pool, 'shutdown'):
                    pool.shutdown()
                    logging.info("OCR服务池已清理")
            except Exception as e:
                logging.debug(f"清理OCR服务池时出错: {e}")
        else:
            logging.debug("插件模式已启用，跳过OCR服务池清理")

        # 统一兜底：无论池是否初始化、插件是否启用，都执行孤儿 worker 清理。
        try:
            from services.multiprocess_ocr_pool import cleanup_orphan_ocr_subprocesses
            cleaned_count = int(cleanup_orphan_ocr_subprocesses(main_pid=os.getpid()) or 0)
            if cleaned_count > 0:
                logging.info(f"OCR孤儿子进程已清理: {cleaned_count}")
        except Exception as e:
            logging.debug(f"OCR孤儿子进程兜底清理失败: {e}")

        # 主进程不加载OCR引擎模块，OCR资源只由OCR子进程管理

        # 清理YOLO引擎
        if cleanup_yolo_runtime_resources(release_process=True, compact_memory=True):
            logging.info("YOLO运行时资源已清理")

        # 清理地图导航子程序与运行态
        try:
            from utils.runtime_image_cleanup import cleanup_map_navigation_runtime_on_stop

            cleanup_map_navigation_runtime_on_stop(
                release_bundle_cache=True,
                auto_close_only=False,
                include_orphans=True,
            )
            logging.info("地图导航运行时资源已清理")
        except Exception as e:
            logging.debug(f"清理地图导航运行时资源时出错: {e}")

        # 清理模板预加载缓存
        try:
            from utils.template_preloader import clear_global_cache
            clear_global_cache()
            logging.info("模板预加载缓存已清理")
        except Exception as e:
            logging.debug(f"清理模板预加载缓存时出错: {e}")

        # 清理模板匹配缓存
        try:
            from utils.template_matching import get_matcher
            matcher = get_matcher()
            if hasattr(matcher, 'template_cache'):
                matcher.template_cache.clear()
            logging.info("模板匹配缓存已清理")
        except Exception as e:
            logging.debug(f"清理模板匹配缓存时出错: {e}")

        # 清理工作流上下文缓存
        try:
            from task_workflow.workflow_context import clear_all_workflow_contexts
            clear_all_workflow_contexts()
            logging.info("工作流上下文已清理")
        except Exception as e:
            logging.debug(f"清理工作流上下文时出错: {e}")

        # 清理移动检测缓存
        try:
            from tasks.conditional_control import clear_all_motion_cache
            clear_all_motion_cache()
            logging.info("移动检测缓存已清理")
        except Exception as e:
            logging.debug(f"清理移动检测缓存时出错: {e}")

        # 清理截图缓存
        try:
            from utils.screenshot_helper import clear_screenshot_cache
            clear_screenshot_cache()
            logging.info("截图缓存已清理")
        except Exception as e:
            logging.debug(f"清理截图缓存时出错: {e}")

        # 清理截图引擎资源
        try:
            from utils.screenshot_helper import cleanup_all_screenshot_engines
            cleanup_all_screenshot_engines()
            logging.info("截图引擎资源已清理")
        except Exception as e:
            logging.debug(f"清理截图引擎资源时出错: {e}")

        # 关闭异步截图管道
        try:
            from utils.async_screenshot import shutdown_global_pipeline
            shutdown_global_pipeline()
            logging.info("异步截图管道已关闭")
        except Exception as e:
            logging.debug(f"关闭异步截图管道时出错: {e}")

        logging.info("资源清理完成")

    except Exception as e:
        logging.error(f"清理资源时出错: {e}", exc_info=True)
    finally:
        try:
            cleanup_runtime_state_variables()
        except Exception as e:
            logging.debug(f"清理运行期状态变量失败: {e}")

atexit.register(cleanup_all_resources)

#  安全检查调度器
_SECURITY_CHECK_CACHE = {}
_LAST_SECURITY_CHECK = 0

def _0xc0de():
    """ 智能安全检查调度器"""
    global _LAST_SECURITY_CHECK
    import time

    current_time = time.time()
    #  优化：限制安全检查频率，避免性能影响
    if current_time - _LAST_SECURITY_CHECK < 1.0:  # 1秒内不重复检查
        return True

    _LAST_SECURITY_CHECK = current_time
    _0x4a2b()  # 反调试检测
    return True

#  函数间接调用表 - 防止直接函数名分析
_FUNC_TABLE = {}

def _0xfeed(func_id: int, *args, **kwargs):
    """ 间接函数调用器"""
    _0xc0de()  # 智能安全检查
    if func_id in _FUNC_TABLE:
        return _FUNC_TABLE[func_id](*args, **kwargs)
    return None

def _0xbeef(func_id: int, func_obj):
    """ 注册函数到间接调用表"""
    _FUNC_TABLE[func_id] = func_obj

#  优化的运行时代码生成器
def _0x8bad():
    """ 运行时生成验证代码（优化版）"""
    try:
        #  优化：检查是否已生成，避免重复执行
        if '_runtime_validator' in globals():
            return True

        # 动态生成验证逻辑
        _validation_code = """
def _runtime_validator(hw_id, key):
    import hashlib
    import time

    # 动态验证逻辑
    _check1 = len(hw_id) == 64
    _check2 = key.startswith('ED-')
    _check3 = time.time() > 1000000000

    return _check1 and _check2 and _check3
"""

        # 执行动态代码
        exec(_validation_code, globals())
        return True
    except:
        return False


def _run_main_runtime_validator(hw_id: str, key: str) -> bool:
    _0x8bad()
    validator = globals().get("_runtime_validator")
    if validator is None:
        return True
    return bool(validator(hw_id, key))


def _license_runtime_validator_bridge(hw_id: str, key: str) -> bool:
    return _run_main_runtime_validator(hw_id, key)


def _configure_runtime_security_hooks() -> None:
    app_runtime_security.configure_runtime_security(
        guard_cb=None,
        validator_cb=_license_runtime_validator_bridge,
    )


_configure_runtime_security_hooks()

def client_login_handshake(hw_id: str, license_key: str) -> tuple[bool, str, dict]:
    """客户端握手协议 - 与服务器进行握手认证

    Args:
        hw_id: 硬件ID
        license_key: 许可证密钥

    Returns:
        tuple: (success, session_token, info_dict)
        info_dict包含: handshake_token, challenge, error等信息
    """
    try:
        import secrets
        import hmac

        # 生成客户端参数
        client_nonce = secrets.token_hex(16)
        client_timestamp = int(datetime.datetime.now(timezone.utc).timestamp())

        # 步骤1: 请求握手初始化（v2.1版本）
        init_data = {
            'hardware_id': hw_id,
            'client_nonce': client_nonce,
            'client_timestamp': client_timestamp
        }

        logging.info(f"握手协议v2.1[步骤1]: 发起握手初始化请求")
        init_response = requests.post(
            f"{SERVER_URL}/api/v2.1/client/handshake/initiate",
            json=init_data,
            timeout=5,
            verify=VERIFY_SSL,
            allow_redirects=False
        )

        if init_response.status_code != 200:
            logging.error(f"握手初始化失败: {init_response.status_code}")
            if init_response.status_code == 403:
                return False, "", {'error': '硬件ID已被封禁', 'status_code': 403}
            return False, "", {'error': '握手初始化失败', 'status_code': init_response.status_code}

        init_json = init_response.json()
        if not init_json.get('success'):
            return False, "", {'error': '握手初始化返回失败', 'message': init_json.get('message')}

        handshake_token = init_json.get('handshake_token')
        server_challenge = init_json.get('server_challenge')
        server_nonce = init_json.get('server_nonce')
        server_timestamp = init_json.get('server_timestamp')
        client_nonce_echo = init_json.get('client_nonce_echo')
        token_hmac = init_json.get('token_hmac')

        required_fields = [
            handshake_token, server_challenge, server_nonce,
            server_timestamp, client_nonce_echo, token_hmac
        ]
        if not all(required_fields):
            logging.error(f"握手响应缺少必要字段")
            return False, "", {'error': '握手响应格式错误'}

        if client_nonce_echo != client_nonce:
            logging.error(f"握手响应中的client_nonce_echo不匹配")
            return False, "", {'error': '握手令牌被篡改'}

        logging.info(f"握手协议v2.1[步骤1]: 成功获得握手令牌和服务器挑战")

        # 步骤2: 生成客户端握手响应（HMAC-SHA256）
        SECRET_KEY = str(os.environ.get('AUTH_SECRET_KEY', '') or '').strip()
        if len(SECRET_KEY) < 24 or SECRET_KEY.lower() == 'default-secret-key-change-in-production':
            return False, "", {'error': 'AUTH_SECRET_KEY 未配置或不安全', 'status_code': 500}
        response_data = f"{server_challenge}|{license_key}|{server_nonce}|{client_nonce}|{server_timestamp}"
        client_response = hmac.new(SECRET_KEY.encode(), response_data.encode(), hashlib.sha256).hexdigest()

        # 步骤3: 发送握手认证
        auth_data = {
            'hardware_id': hw_id,
            'license_key': license_key,
            'handshake_token': handshake_token,
            'server_challenge': server_challenge,
            'server_nonce': server_nonce,
            'server_timestamp': server_timestamp,
            'client_response': client_response,
            'client_timestamp': client_timestamp,
            'client_nonce': client_nonce,
            'token_hmac': token_hmac
        }

        logging.info(f"握手协议v2.1[步骤2]: 发送握手认证请求")
        auth_response = requests.post(
            f"{SERVER_URL}/api/v2.1/client/handshake/authenticate",
            json=auth_data,
            timeout=5,
            verify=VERIFY_SSL,
            allow_redirects=False
        )

        if auth_response.status_code != 200:
            logging.error(f"握手认证失败: {auth_response.status_code}")
            if auth_response.status_code == 409:
                return False, "", {'error': '硬件ID已在线，不允许重复登录', 'status_code': 409}
            elif auth_response.status_code == 401:
                return False, "", {'error': '握手验证失败，响应无效', 'status_code': 401}
            return False, "", {'error': '握手认证失败', 'status_code': auth_response.status_code}

        auth_json = auth_response.json()
        if not auth_json.get('success'):
            return False, "", {'error': '握手认证返回失败', 'message': auth_json.get('message')}

        session_token = auth_json.get('session_token')
        if not session_token:
            logging.error(f"握手认证响应缺少session_token")
            return False, "", {'error': '握手认证响应格式错误'}

        logging.info(f"握手协议v2.1[步骤2]: 握手认证成功，已获得会话令牌")

        return True, session_token, {
            'handshake_token': handshake_token,
            'login_status': 'authenticated',
            'protocol_version': '2.1',
            'message': '握手协议v2.1认证成功',
            'server_time': datetime.datetime.now(timezone.utc).isoformat()
        }

    except requests.exceptions.Timeout:
        logging.error("握手协议v2.1请求超时")
        return False, "", {'error': 'Handshake timeout'}
    except requests.exceptions.ConnectionError as e:
        logging.error(f"握手协议v2.1连接失败: {e}")
        return False, "", {'error': 'Connection failed'}
    except Exception as e:
        logging.error(f"握手协议v2.1异常: {e}")
        import traceback
        logging.debug(traceback.format_exc())
        return False, "", {'error': str(e)}


def client_logout(hw_id: str, session_token: str) -> bool:
    """客户端离线协议 - 向服务器发送离线通知

    注意: 这是可选的。客户端不需要主动调用此函数。
    服务器会在下一次握手认证时自动标记旧会话为离线。
    此函数仅在正常关闭时调用，作为礼貌通知。

    Args:
        hw_id: 硬件ID
        session_token: 会话令牌

    Returns:
        bool: 是否成功离线
    """
    if not session_token or not hw_id:
        return False

    try:
        logout_data = {
            'session_token': session_token,
            'hardware_id': hw_id
        }

        logging.info(f"客户端离线: 发送离线请求（可选）")
        response = requests.post(
            f"{SERVER_URL}/api/client/offline",
            json=logout_data,
            timeout=3,
            verify=VERIFY_SSL,
            allow_redirects=False
        )

        if response.status_code == 200:
            response_json = response.json()
            if response_json.get('success'):
                logging.info(f"客户端离线成功")
                return True

        logging.debug(f"客户端离线请求返回状态码: {response.status_code}")
        return False

    except Exception as e:
        logging.debug(f"客户端离线异常（非致命）: {e}")
        return False


def client_heartbeat_with_fallback(hw_id: str, session_token: str, license_key: str, max_retries: int = 3) -> tuple[bool, str]:
    """客户端心跳 - 保持会话活跃，失败时自动重新握手

    Args:
        hw_id: 硬件ID
        session_token: 会话令牌
        license_key: 许可证密钥（用于失败时重新握手）
        max_retries: 最大重试次数

    Returns:
        tuple: (success, new_or_existing_token)
        如果心跳失败且重新握手成功，返回新token
        如果心跳成功，返回原token
    """
    if not session_token or not hw_id:
        return False, ""

    try:
        heartbeat_data = {'session_token': session_token}

        logging.info(f"客户端心跳: 发送心跳请求")
        response = requests.post(
            f"{SERVER_URL}/api/client/heartbeat",
            json=heartbeat_data,
            timeout=5,
            verify=VERIFY_SSL,
            allow_redirects=False
        )

        if response.status_code == 200:
            logging.debug(f"客户端心跳: 心跳确认")
            return True, session_token

        # 心跳失败 - 会话无效或过期
        if response.status_code == 401:
            logging.warning(f"客户端心跳失败: 会话无效或已过期 (401)")
            logging.info(f"客户端心跳: 尝试自动重新握手")

            # 自动重新握手
            for attempt in range(1, max_retries + 1):
                logging.info(f"客户端心跳: 重新握手尝试 {attempt}/{max_retries}")
                success, new_token, info = client_login_handshake(hw_id, license_key)

                if success:
                    logging.info(f"客户端心跳: 重新握手成功，获得新的会话令牌")
                    return True, new_token
                else:
                    error_msg = info.get('error', '未知错误')
                    status_code = info.get('status_code', 0)
                    logging.warning(f"客户端心跳: 重新握手失败 (尝试 {attempt}) - {error_msg} ({status_code})")

                    # 硬件ID被封禁 - 不再重试
                    if status_code == 403:
                        logging.error(f"客户端心跳: 硬件ID已被封禁，无法继续")
                        return False, ""

                    # 短暂延迟后重试
                    if attempt < max_retries:
                        time.sleep(1)

            return False, ""

        # 其他错误
        logging.error(f"客户端心跳失败: HTTP {response.status_code}")
        return False, session_token

    except requests.exceptions.Timeout:
        logging.error(f"客户端心跳: 请求超时")
        return False, session_token
    except requests.exceptions.ConnectionError as e:
        logging.error(f"客户端心跳: 连接失败 - {e}")
        return False, session_token
    except Exception as e:
        logging.error(f"客户端心跳: 异常 - {e}")
        return False, session_token


def validate_license_with_server_v2(hw_id: str, key: str) -> tuple[bool, int, str, dict]:
    """新一代许可证验证 - v2.1版本（使用增强握手协议）

    Args:
        hw_id: 硬件ID
        key: 许可证密钥

    Returns:
        tuple: (is_valid, status_code, license_type, extra_info)
        extra_info包含: validation_mode, remaining_days, is_permanent等
    """
    _0x4a2b()
    _0x8bad()

    if not _run_main_runtime_validator(hw_id, key):
        return False, 400, "invalid", {}

    extra_info = {}

    try:
        import hashlib
        current_time = int(datetime.datetime.now(timezone.utc).timestamp())
        client_nonce = secrets.token_hex(16)

        logging.info(f"客户端: 开始v2.1握手协议 - 硬件ID: {hw_id[:16]}...")

        initiate_data = {
            'hardware_id': hw_id,
            'client_nonce': client_nonce,
            'client_timestamp': current_time
        }

        response = requests.post(
            f"{SERVER_URL}/api/v2.1/client/handshake/initiate",
            json=initiate_data,
            timeout=5,
            verify=VERIFY_SSL,
            allow_redirects=False
        )

        if response.status_code != 200:
            logging.error(f"握手初始化失败: {response.status_code}")
            return False, response.status_code, "unknown", {}

        init_response = response.json()
        if not init_response.get('success'):
            logging.error(f"握手初始化被拒绝: {init_response.get('message')}")
            return False, 400, "unknown", {}

        handshake_token = init_response.get('handshake_token')
        server_challenge = init_response.get('server_challenge')
        server_nonce = init_response.get('server_nonce')
        server_timestamp = init_response.get('server_timestamp')
        token_hmac = init_response.get('token_hmac')

        logging.info(f"客户端: 握手初始化成功，收到服务器挑战")

        SECRET_KEY = str(os.environ.get('AUTH_SECRET_KEY', '') or '').strip()
        if len(SECRET_KEY) < 24 or SECRET_KEY.lower() == 'default-secret-key-change-in-production':
            return False, 500, "unknown", {}
        data_for_response = f"{server_challenge}|{key}|{server_nonce}|{client_nonce}|{server_timestamp}"
        client_response = hmac.new(SECRET_KEY.encode(), data_for_response.encode(), hashlib.sha256).hexdigest()

        auth_data = {
            'hardware_id': hw_id,
            'license_key': key,
            'handshake_token': handshake_token,
            'server_challenge': server_challenge,
            'server_nonce': server_nonce,
            'server_timestamp': server_timestamp,
            'client_response': client_response,
            'client_timestamp': current_time,
            'client_nonce': client_nonce,
            'token_hmac': token_hmac
        }

        response = requests.post(
            f"{SERVER_URL}/api/v2.1/client/handshake/authenticate",
            json=auth_data,
            timeout=5,
            verify=VERIFY_SSL,
            allow_redirects=False
        )

        status_code = response.status_code
        logging.info(f"客户端: 握手认证响应状态码: {status_code}")

        if status_code == 200:
            try:
                response_json = response.json()

                if response_json.get("success"):
                    license_type = response_json.get("license_type", "unknown")
                    extra_info = {
                        'validation_mode': response_json.get('validation_mode', 'full'),
                        'license_validation_enabled': response_json.get('license_validation_enabled', True),
                        'remaining_days': response_json.get('remaining_days'),
                        'is_permanent': response_json.get('is_permanent', False),
                        'expires_at': response_json.get('expires_at'),
                        'server_time': response_json.get('server_time'),
                        'api_version': response_json.get('api_version', '2.1'),
                        'session_token': response_json.get('session_token')
                    }

                    logging.info(f"v2.1许可证验证成功 - 类型: {license_type}, 握手协议完成")
                    return True, status_code, license_type, extra_info
                else:
                    error_code = response_json.get('error_code', 'UNKNOWN')
                    message = response_json.get('message', '验证失败')
                    logging.error(f"v2.1许可证验证失败: {error_code} - {message}")
                    return False, status_code, "unknown", {'error_code': error_code, 'message': message}

            except json.JSONDecodeError:
                logging.error("客户端: v2.1响应不是有效的JSON")
                return False, status_code, "unknown", {'error': 'Invalid JSON response'}

        elif status_code == 401:
            logging.error(f"v2.1许可证验证失败: 握手认证被拒绝 (401)")
            return False, status_code, "unknown", {}
        elif status_code == 403:
            try:
                response_json = response.json()
                if response_json.get('is_banned'):
                    logging.error(f"v2.1验证失败: 硬件ID已被封禁")
                    return False, status_code, "banned", {'is_banned': True}
            except:
                pass
            return False, status_code, "forbidden", {}
        else:
            logging.error(f"v2.1握手认证返回意外状态码: {status_code}")
            return False, status_code, "unknown", {}

    except requests.exceptions.Timeout:
        logging.error("v2.1握手请求超时")
        return False, 0, "timeout", {'error': 'Request timeout'}
    except requests.exceptions.ConnectionError as e:
        logging.error(f"v2.1握手连接失败: {e}")
        return False, 0, "connection_error", {'error': 'Connection failed'}
    except Exception as e:
        logging.error(f"v2.1握手异常: {e}")
        return False, 0, "exception", {'error': str(e)}

def validate_license_with_server(hw_id: str, key: str) -> tuple[bool, int, str]:
    """ Validates the HW ID and license key with the server using HTTPS.
       Returns a tuple: (is_valid: bool, status_code: int, license_type: str)
    """
    #  优化：减少重复的安全检查
    _0x4a2b()  # 反调试检测
    _0x8bad()  # 运行时代码生成（带缓存）

    #  动态验证检查
    if not _run_main_runtime_validator(hw_id, key):
        return False, 400, "invalid"

    headers = {
        'X-Hardware-ID': hw_id,
        'Authorization': f'Bearer {key}'
    }
    status_code = 0 # Default status code
    max_retries = 2  # 启动优化：减少重试次数
    retry_delay = 1  # 启动优化：减少重试延迟
    
    # --- 添加客户端日志 ---

    # ---------------------

    for attempt in range(max_retries):
        try:
            logging.info(f"客户端: 发送验证请求到端点 {AUTH_ENDPOINT} (尝试 {attempt + 1}/{max_retries})")
            # --- MODIFIED: Disable redirects and check response content ---
            # 启动 性能优化：减少超时时间，提高响应速度
            response = requests.get(
                f"{SERVER_URL}{AUTH_ENDPOINT}",
                headers=headers,
                timeout=3,  # 启动优化：进一步减少到3秒
                verify=VERIFY_SSL,
                allow_redirects=False # <-- Don't follow redirects for API calls
            )
            # -------------------------------------------------------------
            status_code = response.status_code 
            
            logging.info(f"客户端: 收到响应状态码: {status_code}")
            response_text = "" # Initialize
            response_json = None
            try:
                response_text = response.text
                # Try to parse JSON only if response indicates JSON (e.g., status 200, 401)
                if 200 <= status_code < 300 or status_code == 401: # Consider other API error codes if applicable
                    try:
                        response_json = response.json()
                    except json.JSONDecodeError:
                        logging.warning("客户端: 响应不是有效的 JSON。")
                        response_json = None # Ensure it's None if parsing fails
            except Exception as e:
                logging.error(f"客户端: 读取响应内容出错: {e}")

            logging.info(f"服务器响应状态码(原始): {status_code}") # Log original status code
            
            # --- MODIFIED: Stricter Success Check ---
            if status_code == 200 and response_json and response_json.get("message") == "认证成功":
                # 获取许可证类型信息
                license_type = response_json.get("license_type", "unknown")
                logging.info(f"许可证验证成功 (通过状态码和响应内容)，许可证类型: {license_type}")
                return True, status_code, license_type
            # ---------------------------------------
            elif status_code == 401: # Unauthorized - Expected for auth failure
                error_msg = "未提供详细错误信息"
                if response_json: # Check if we successfully parsed JSON
                    error_msg = response_json.get("error", error_msg)
                elif response_text: # Fallback to raw text if no JSON
                    error_msg = response_text[:100] # Log part of the text
                logging.warning(f"许可证验证失败: 未授权 (401)。密钥无效、过期、禁用或与硬件不匹配。服务器错误详情: {error_msg}")
                return False, status_code, "unknown"
            else:
                # Handle other status codes (like 3xx redirects if allow_redirects was True, or 5xx server errors)
                logging.error(f"许可证验证时服务器返回意外状态码: {status_code}")
                # logging.error(f"服务器响应内容(部分): {response_text[:200]}...") # Already logged non-JSON response above
                # If status is 302, it likely means auth failed and server tried to redirect to login
                if status_code == 302:
                    logging.error("收到状态码 302，表示服务器认证失败并尝试重定向到登录页 (可能是因为allow_redirects=True 或服务器配置问题)。")
                
                if attempt < max_retries - 1: # 如果不是最后一次尝试
                    logging.info(f"将在{retry_delay}秒后重试...")
                    time.sleep(retry_delay)
                    continue # Go to the next attempt
                return False, status_code, "unknown"
                
        except requests.exceptions.Timeout:
            logging.error(f"客户端: 连接服务器超时 (尝试 {attempt + 1}/{max_retries}).")
            if attempt < max_retries - 1:
                logging.info(f"将在{retry_delay}秒后重试...")
                time.sleep(retry_delay)
            else:
                return False, status_code, "unknown" # Return after max retries
        except requests.exceptions.SSLError as e:
            sanitized_error = sanitize_error_message(str(e))
            logging.error(f"发生 SSL 错误 (尝试 {attempt + 1}/{max_retries}): {sanitized_error}")
            logging.error("如果服务器使用自签名证书，请确保 main.py 中的 VERIFY_SSL 设置为 False。")
            logging.error("如果服务器使用有效证书，请检查证书配置和客户端系统信任存储。")
            # SSL errors are often configuration issues, retrying immediately might not help
            # but we'll follow the retry pattern for consistency here.
            if attempt < max_retries - 1:
                logging.info(f"将在{retry_delay}秒后重试...")
                time.sleep(retry_delay)
            else:
                return False, status_code, "unknown" # SSL error, no meaningful status code from server
        except requests.exceptions.RequestException as e: # Catches ConnectionError, HTTPError etc.
            sanitized_error = sanitize_error_message(str(e))
            logging.error(f"连接验证端点时发生网络错误 (尝试 {attempt + 1}/{max_retries}): {sanitized_error}")
            if attempt < max_retries - 1:
                logging.info(f"将在{retry_delay}秒后重试...")
                time.sleep(retry_delay)
            else:
                return False, status_code, "unknown" # Network error, no meaningful status code from server
        except Exception as e:
            logging.error(f"验证过程中发生未知错误 (尝试 {attempt + 1}/{max_retries}): {e}", exc_info=True)
            if attempt < max_retries - 1:
                logging.info(f"将在{retry_delay}秒后重试...")
                time.sleep(retry_delay)
            else:
                return False, status_code, "unknown" # Generic error, no meaningful status code from server

    logging.error(f"验证尝试达到最大次数 ({max_retries}) 后失败。")
    return False, status_code, "unknown" # Fallback if all retries fail

attempt_client_registration = _shared_attempt_client_registration


def _attempt_v1_registration(hw_id: str, session: requests.Session, csrf_token: str) -> dict:
    """使用v1 API进行注册（回退方案）"""
    logging.info("使用v1 API进行注册...")

    try:
        # 准备v1请求头
        headers = {
            'Referer': SERVER_URL
        }

        if csrf_token:
            headers['X-CSRFToken'] = csrf_token

        # v1 API的简单payload
        v1_payload = {
            "hardware_id": hw_id
        }

        response = session.post(
            f"{SERVER_URL}/api/licensing/register_client",
            json=v1_payload,
            headers=headers,
            timeout=8,
            verify=VERIFY_SSL
        )
        _log_registration_redirect_warning(response, "v1 register")

        status_code = response.status_code
        logging.info(f"客户端注册(v1)响应状态码: {status_code}")

        response_json = None
        try:
            response_json = response.json()
        except json.JSONDecodeError:
            logging.warning("v1客户端注册响应不是有效的 JSON。")

        # v1 API: 201=新注册, 409=已存在
        if status_code in [201, 409, 200]:
            logging.info(f"硬件 ID 注册成功(v1)。状态: {'新注册' if status_code == 201 else '已存在'}")

            # 检查是否被封禁
            if response_json and response_json.get("is_banned", False):
                logging.critical("硬件 ID 已被封禁！")
                return {
                    "success": False,
                    "is_banned": True,
                    "ban_reason": response_json.get("ban_reason", "未提供原因"),
                    "license_validation_enabled": response_json.get("license_validation_enabled", True)
                }

            # 获取许可证验证状态
            license_validation_enabled = response_json.get("license_validation_enabled", True) if response_json else True
            logging.info(f"服务器许可证验证状态: {'开启' if license_validation_enabled else '关闭'}")

            return {
                "success": True,
                "is_banned": False,
                "license_validation_enabled": license_validation_enabled
            }

        elif status_code == 403:
            error_code = ""
            if isinstance(response_json, dict):
                error_code = str(response_json.get("error_code", "") or "").strip().upper()
            is_banned = bool(isinstance(response_json, dict) and response_json.get("is_banned", False)) or error_code == "HARDWARE_BANNED"
            error_msg = "请求被拒绝"
            if isinstance(response_json, dict):
                error_msg = str(
                    response_json.get("message")
                    or response_json.get("error")
                    or response_json.get("ban_reason")
                    or response_json.get("detail")
                    or error_msg
                ).strip()
            if is_banned:
                logging.critical(f"硬件 ID 已被封禁。原因: {error_msg}")
                return {"success": False, "is_banned": True, "ban_reason": error_msg, "status_code": status_code, "error": error_msg}
            logging.warning(f"v1硬件 ID 注册失败。状态码: {status_code}, 错误: {error_msg}")
            return {"success": False, "is_banned": False, "status_code": status_code, "error": error_msg}

        elif status_code == 429:
            error_msg = "客户端数量已达到上限，请联系管理员"
            if isinstance(response_json, dict):
                error_msg = str(
                    response_json.get("message")
                    or response_json.get("error")
                    or response_json.get("detail")
                    or error_msg
                ).strip()
            logging.warning(f"v1硬件 ID 注册失败。状态码: {status_code}, 错误: {error_msg}")
            return {"success": False, "is_banned": False, "status_code": status_code, "error": error_msg}

        else:
            error_msg = "未提供详细错误信息"
            if response_json:
                error_msg = response_json.get("message", response_json.get("error", response_json.get("detail", error_msg)))
            elif response.text:
                error_msg = response.text[:100]
            logging.warning(f"v1硬件 ID 注册失败。状态码: {status_code}, 错误: {error_msg}")
            return {"success": False, "is_banned": False, "status_code": status_code, "error": str(error_msg)}

    except requests.exceptions.RequestException as e:
        logging.error(f"v1注册请求异常: {e}")
        return {"success": False, "is_banned": False}
    except Exception as e:
        logging.error(f"v1注册过程中发生未知错误: {e}", exc_info=True)
        return {"success": False, "is_banned": False}

# --- ADDED: Function to attempt HWID migration ---
def attempt_migration(old_hw_id: str, license_key: str, session: requests.Session) -> Optional[str]:
    """
    Attempts to migrate an old hardware ID to the new format on the server.
    Returns the new hardware ID (SHA256) if successful, otherwise None.
    """


    MIGRATION_ENDPOINT = "/api/licensing/migrate_hwid"

    # --- ADDED: Ensure CSRF token is in session and header for migration POST ---
    # Fetch CSRF token to ensure session has the cookie and we get the value for the header
    # --- MODIFIED: Get CSRF token from JSON response body for migration ---
    csrf_token_value = None # Initialize
    try:

        csrf_response = session.get(
            f"{SERVER_URL}/api/get_csrf_for_client",
            timeout=10,
            verify=VERIFY_SSL
        )
        csrf_response.raise_for_status()

        # Get token from JSON body
        response_json = csrf_response.json()
        csrf_token_value = response_json.get('csrf_token')

        if not csrf_token_value:
            logging.warning("未在 CSRF token 响应的 JSON 体中找到 'csrf_token' 字段进行迁移请求。POST 可能失败。")
            if not session.cookies:
                 logging.error("在 CSRF token GET 请求后，session cookies 为空。无法进行迁移请求。")
                 return None # Fail if no cookies were set at all
            else:
                 logging.debug("DEBUG: Session cookies were set, but 'csrf_token' not found in JSON for migration. Proceeding, but POST might fail.")
    # --- END MODIFIED ---

    except requests.exceptions.RequestException as e:
        sanitized_error = sanitize_error_message(str(e))
        logging.error(f"获取迁移请求所需的 CSRF token 时发生网络或HTTP错误: {sanitized_error}")
        return None # Abort migration attempt if CSRF token cannot be fetched
    except Exception as e:
        logging.error(f"获取CSRF token时发生未知错误: {e}", exc_info=True)
        return None


    headers = {
        'X-Hardware-ID-Old': old_hw_id,
        'Authorization': f'Bearer {license_key}',
        'X-Migration-Attempt': 'true',
        'Referer': SERVER_URL # Needed for CSRF validation
    }
    # --- ADDED: Add X-CSRFToken header if token value was obtained ---
    if csrf_token_value:
        headers['X-CSRFToken'] = csrf_token_value

    else:
        logging.warning("CSRF token from JSON not available for migration. Migration POST will not include X-CSRFToken header.")
    # --- END ADDED ---


    payload = {
         "old_hardware_id": old_hw_id,
    }

    try:
        response = session.post(
            f"{SERVER_URL}{MIGRATION_ENDPOINT}",
            headers=headers, # <-- Pass the headers dictionary
            timeout=15,
            verify=VERIFY_SSL,
            json=payload
        )
        status_code = response.status_code
        logging.info(f"硬件ID迁移请求响应状态码: {status_code}")

        response_json = None
        try:
            response_json = response.json()
        except json.JSONDecodeError:
             logging.warning("硬件ID迁移响应不是有效的 JSON。")

        if status_code == 200: # Success
            new_hw_id = response_json.get("new_hardware_id") if response_json else None
            if new_hw_id and isinstance(new_hw_id, str) and len(new_hw_id) == 64:
                logging.info("服务器成功迁移硬件ID")
                return new_hw_id # Return the new SHA256 ID
            else:
                logging.error("迁移成功响应，但服务器未返回有效的 'new_hardware_id'。")
                return None
        elif status_code == 400: # Bad Request
            error_msg = response_json.get("error", response.text[:100]) if response_json else response.text[:100]
            logging.warning(f"硬件ID迁移请求无效 (400)。错误: {error_msg}")
            return None
        elif status_code == 401: # Unauthorized
             error_msg = response_json.get("error", response.text[:100]) if response_json else response.text[:100]
             logging.warning(f"硬件ID迁移需要认证 (401)。旧ID或密钥无效。错误: {error_msg}")
             return None
        elif status_code == 404: # Not Found
             logging.error("硬件ID迁移端点不存在 (404)。服务器尚未实现迁移功能。")
             return None
        else: # Other errors
            error_msg = response_json.get("error", response.text[:100]) if response_json else response.text[:100]
            logging.error(f"硬件ID迁移时服务器返回意外状态码: {status_code}. 错误: {error_msg}")
            return None

    except requests.exceptions.RequestException as e:
        sanitized_error = sanitize_error_message(str(e))
        logging.error(f"连接服务器进行硬件ID迁移时发生网络错误: {sanitized_error}")
        return None
    except Exception as e:
        logging.error(f"硬件ID迁移过程中发生未知错误: {e}", exc_info=True)
        return None
# --- END ADDED ---

# --- ADDED: Function to bind license to HWID (Definition) ---
def bind_license_to_hwid(hw_id: str, license_key: str, session: requests.Session) -> bool:
    """将许可证绑定到特定硬件ID (与服务器API /api/licensing/bind_license 通信)

    Args:
        hw_id: 硬件ID.
        license_key: 许可证密钥.
        session: requests.Session 对象.

    Returns:
        True 如果绑定成功, 否则 False.
    """


    BIND_ENDPOINT = "/api/licensing/bind_license" # 定义绑定端点
    csrf_token_value = None

    try:
        # 1. 获取CSRF token (与注册和迁移逻辑类似)

        csrf_response = session.get(
            f"{SERVER_URL}/api/get_csrf_for_client",
            timeout=10,
            verify=VERIFY_SSL
        )
        csrf_response.raise_for_status()
        response_json = csrf_response.json()
        csrf_token_value = response_json.get('csrf_token')

        if not csrf_token_value:
            logging.warning("未在 CSRF token 响应的 JSON 体中找到 'csrf_token' 字段进行绑定请求。POST 可能失败。")
            if not session.cookies:
                logging.error("在 CSRF token GET 请求后，session cookies 为空。无法进行绑定请求。")
                return False

    except requests.exceptions.RequestException as e:
        sanitized_error = sanitize_error_message(str(e))
        logging.error(f"获取绑定请求所需的 CSRF token 时发生网络或HTTP错误: {sanitized_error}")
        return False
    except Exception as e:
        logging.error(f"获取CSRF token时发生未知错误: {e}", exc_info=True)
        return False

    # 2. 准备并发送绑定请求
    headers = {
        'Referer': SERVER_URL, # CSRF通常需要 Referer
        'Authorization': f'Bearer {license_key}' # 假设绑定操作也需要许可证密钥进行认证
    }
    if csrf_token_value:
        headers['X-CSRFToken'] = csrf_token_value

    else:
        logging.warning("CSRF token from JSON not available for binding. Binding POST will not include X-CSRFToken header.")

    payload = {
        "hardware_id": hw_id,
        "license_key": license_key # 服务器可能也需要在payload中验证密钥
    }

    try:
        response = session.post(
            f"{SERVER_URL}{BIND_ENDPOINT}",
            json=payload,
            headers=headers,
            timeout=15,
            verify=VERIFY_SSL
        )
        status_code = response.status_code
        logging.info(f"许可证绑定请求响应状态码: {status_code}")
        response_data = None
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            logging.warning("许可证绑定响应不是有效的JSON")

        if status_code == 200: # 假设成功是200 OK

            return True
        elif status_code == 400: # Bad request
            error_msg = response_data.get("error", "请求无效") if response_data else response.text[:100]
            logging.warning(f"许可证绑定失败 (400 - 请求无效): {error_msg}")
            return False
        elif status_code == 401: # Unauthorized
            error_msg = response_data.get("error", "未授权") if response_data else response.text[:100]
            logging.warning(f"许可证绑定失败 (401 - 未授权): {error_msg}")
            return False
        elif status_code == 404: # Not found (e.g. license key or hwid does not exist to be bound)
            error_msg = response_data.get("error", "资源未找到") if response_data else response.text[:100]
            logging.warning(f"许可证绑定失败 (404 - 未找到): {error_msg}")
            return False
        elif status_code == 409: # Conflict (e.g. license already bound to a different hwid)
            error_msg = response_data.get("error", "冲突") if response_data else response.text[:100]
            logging.warning(f"许可证绑定失败 (409 - 冲突): {error_msg}")
            return False
        else:
            error_msg = response_data.get("error", f"未知错误: {response.text[:100]}") if response_data else f"未知错误: {response.text[:100]}"
            logging.error(f"许可证绑定时服务器返回意外状态码: {status_code}. 错误: {error_msg}")
            return False

    except requests.exceptions.RequestException as e:
        sanitized_error = sanitize_error_message(str(e))
        logging.error(f"连接服务器进行许可证绑定时发生网络错误: {sanitized_error}")
        return False
    except Exception as e:
        logging.error(f"许可证绑定过程中发生未知错误: {e}", exc_info=True)
        return False
# --- END ADDED ---

# --- Function to check window resolution ---
RESOLUTION_CHECK_TOLERANCE = 2 # Allow +/- 2 pixels difference

def check_resolution_and_needs_admin(config_data):
    """Checks target window client resolution and determines if admin rights might be needed."""
    logging.info("检查窗口分辨率以确定是否需要提权...")

    target_title = config_data.get('target_window_title')
    target_width = config_data.get('custom_width')
    target_height = config_data.get('custom_height')
    if not target_title or not target_width or not target_height or target_width <= 0 or target_height <= 0:
        logging.warning("配置中缺少目标窗口标题或有效的目标宽高，假定需要提权。")
        return True # Need admin if config is incomplete

    logging.info(f"目标窗口: '{target_title}', 目标客户区尺寸: {target_width}x{target_height}")

    hwnd = find_enhanced_window_handle(target_title)

    if not hwnd:
        logging.warning(f"未找到标题为 '{target_title}' 的窗口，假定需要提权。")
        return True # Need admin if window not found

    # logging.info(f"找到窗口句柄: {hwnd}")

    # GetClientRect requires wintypes.RECT
    # --- ADDED: Get DPI for scaling ---
    user32 = ctypes.windll.user32  # 工具 修复：重新定义user32
    dpi = user32.GetDpiForWindow(hwnd) if hasattr(user32, 'GetDpiForWindow') else 96 # Fallback to 96 if API not available (older Windows)
    scale_factor = dpi / 96.0
    logging.info(f"窗口 DPI: {dpi} (缩放因子: {scale_factor:.2f})")
    # -----------------------------------
    rect = wintypes.RECT()
    if user32.GetClientRect(hwnd, ctypes.byref(rect)):
        client_width = rect.right - rect.left
        client_height = rect.bottom - rect.top
        logging.info(f"窗口 '{target_title}' 的客户区尺寸: {client_width}x{client_height}")

        # 工具 Bug修复：DPI缩放计算错误！
        # GetClientRect返回的是逻辑像素，不需要再乘以缩放因子
        # 如果要获取物理像素，应该乘以缩放因子，但这里应该使用逻辑像素进行比较
        # 因为配置中的尺寸通常是逻辑尺寸
        scaled_width = client_width   # 直接使用逻辑像素
        scaled_height = client_height # 直接使用逻辑像素
        logging.info(f"应用 DPI 缩放后的客户区尺寸 (估算): {scaled_width}x{scaled_height}")

        # --- MODIFIED: Check with tolerance ---
        width_match = abs(scaled_width - target_width) <= RESOLUTION_CHECK_TOLERANCE
        height_match = abs(scaled_height - target_height) <= RESOLUTION_CHECK_TOLERANCE
        if width_match and height_match:
            logging.info(f"窗口客户区尺寸在容差 ({RESOLUTION_CHECK_TOLERANCE}像素) 内匹配配置。跳过提权请求。")
            return False # Resolution matches, DO NOT need admin for this reason
        else:
            logging.warning(f"窗口客户区尺寸 ({scaled_width}x{scaled_height}) 与配置 ({target_width}x{target_height}) 不匹配 (容差: {RESOLUTION_CHECK_TOLERANCE})。假定需要提权。")
            return True # Resolution mismatch, need admin
    else:
        # Attempt to get error details
        error_code = ctypes.get_last_error()
        error_message = ctypes.FormatError(error_code) if error_code != 0 else "未知错误"
        logging.error(f"调用 GetClientRect 失败，错误码: {error_code} ({error_message})。假定需要提权。")
        return True # Failed to get client rect, assume need admin

# --- Configuration Loading ---
from app_core.config_store import CONFIG_FILE, load_config, save_config

def find_enhanced_window_handle(window_title):
    """增强的窗口查找函数"""
    if not window_title:
        logging.error("窗口标题为空")
        return None

    logging.info(f"搜索 尝试查找窗口: '{window_title}'")

    # 使用统一的窗口查找工具
    try:
        from utils.window_finder import WindowFinder
        hwnd = WindowFinder.find_unique_window_exact(window_title)
        if hwnd:
            logging.info(f"成功 统一窗口查找工具找到窗口: {hwnd}")
            return hwnd
        logging.warning(f"未找到可唯一确认的目标窗口: '{window_title}'")
    except Exception as e:
        logging.warning(f"统一窗口查找工具失败: {e}")

    return None

# Load configuration EARLY
config = load_config()

# 【关键】子进程不需要加载 GUI 库，跳过这些导入
if not _IS_SUBPROCESS:
    from PySide6.QtWidgets import (QApplication, QMessageBox, QDialog,
                                   QLineEdit, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
                                   QSpacerItem, QSizePolicy, QDialogButtonBox, QSystemTrayIcon, QMenu) # <<< MODIFIED: Added QSystemTrayIcon, QMenu
    from PySide6.QtCore import QThread, QObject, Signal, QTimer, Qt # <<< MODIFIED: Removed unused imports
    from PySide6.QtGui import QAction, QIcon, QColor # <<< ADDED: For system tray and theme control
    from ui.system_parts.message_box_translator import place_dialog_on_screen, show_critical_box
    from ui.main_window_parts.main_window import MainWindow # Import MainWindow
    from tasks import get_task_modules

# --- ADDED: Global Variables for License Type ---
VALIDATED_LICENSE_TYPE = "unknown" # Store the validated license type

# --- ADDED: NetworkTask Class (Skeleton for asynchronous operations) ---
class NetworkTask(QThread):
    finished = Signal(bool, int, str, str)  # Signal: success(bool), status_code(int), message(str), license_type(str)

    def __init__(self, task_type: str, params: dict, session: Optional[requests.Session] = None, parent=None):
        super().__init__(parent)
        self.task_type = task_type
        self.params = params
        self.session = session if session else requests.Session() # Use provided or new session
        self._owns_session = session is None  # 标记是否拥有session，用于清理时判断
        # 安全考虑：禁用可能泄露敏感参数的调试日志
        # logging.debug(f"NetworkTask initialized for task: {self.task_type} with params: {params}")
        logging.debug(f"NetworkTask initialized for task: {self.task_type}")

    def run(self):
        logging.info(f"NetworkTask started for: {self.task_type}")
        try:
            if self.task_type == "validate_license":
                hw_id = self.params.get("hw_id")
                key = self.params.get("key")
                if not hw_id or not key:
                    logging.error("Validate_license task missing hw_id or key.")
                    self.finished.emit(False, 0, "内部错误: 缺少验证参数。", "unknown")
                    return
                # 使用v2 API进行验证
                is_valid, status_code, license_type, extra_info = validate_license_with_server_v2(hw_id, key)
                # Message can be more specific based on status_code if needed
                if is_valid:
                    validation_mode = extra_info.get('validation_mode', 'full')
                    message = f"许可证验证成功 (v2 - {validation_mode})。"
                else:
                    error_msg = extra_info.get('message', '')
                    message = f"许可证验证失败 (状态码: {status_code})。{error_msg}" if error_msg else f"许可证验证失败 (状态码: {status_code})。"
                    if status_code == 401 and not is_valid:
                        message = "许可证密钥无效、过期、已禁用或与硬件ID不匹配。"
                self.finished.emit(is_valid, status_code, message, license_type)

            elif self.task_type == "register_client":
                hw_id = self.params.get("hw_id")
                if not hw_id:
                    logging.error("Register_client task missing hw_id.")
                    self.finished.emit(False, 0, "内部错误: 缺少注册参数。", "unknown")
                    return
                registration_result = attempt_client_registration(hw_id, self.session)
                is_registered = bool(registration_result.get("success", False))
                status_code = int(registration_result.get("status_code", 201 if is_registered else 0) or 0)
                message = "客户端注册成功或已存在。"
                if not is_registered:
                    message = str(registration_result.get("error") or "客户端注册失败。")
                self.finished.emit(is_registered, status_code, message, "unknown")

            elif self.task_type == "migrate_hwid":
                old_hw_id = self.params.get("old_hw_id")
                license_key = self.params.get("license_key")
                if not old_hw_id or not license_key:
                    logging.error("Migrate_hwid task missing old_hw_id or license_key.")
                    self.finished.emit(False, 0, "内部错误: 缺少迁移参数。", "unknown")
                    return
                migrated_hw_id_or_none = attempt_migration(old_hw_id, license_key, self.session)
                is_migrated = bool(migrated_hw_id_or_none)
                status_code = 200 if is_migrated else 0 # Simplified
                message = f"硬件ID迁移成功。新ID: {migrated_hw_id_or_none[:8]}..." if is_migrated else "硬件ID迁移失败。"
                # We might want to emit the new_hw_id as well if successful
                # For now, keeping the signal signature simple (bool, int, str, str)
                self.finished.emit(is_migrated, status_code, message, "unknown")

            elif self.task_type == "bind_license":
                hw_id = self.params.get("hw_id")
                license_key = self.params.get("license_key")
                if not hw_id or not license_key:
                    logging.error("Bind_license task missing hw_id or license_key.")
                    self.finished.emit(False, 0, "内部错误: 缺少绑定参数。", "unknown")
                    return
                is_bound = bind_license_to_hwid(hw_id, license_key, self.session)
                status_code = 200 if is_bound else 0 # Simplified
                message = "许可证绑定成功。" if is_bound else "许可证绑定失败。"
                self.finished.emit(is_bound, status_code, message, "unknown")

            else:
                logging.warning(f"未知网络任务类型: {self.task_type}")
                self.finished.emit(False, 0, f"未知任务类型: {self.task_type}", "unknown")

        except Exception as e:
            logging.error(f"网络任务 '{self.task_type}' 执行过程中发生严重错误: {e}", exc_info=True)
            self.finished.emit(False, 0, f"执行 '{self.task_type}' 时发生内部错误。", "unknown")
        finally:
            # 清理session资源（仅当该线程创建了session时）
            if self._owns_session and self.session:
                try:
                    self.session.close()
                    logging.debug(f"NetworkTask session closed for: {self.task_type}")
                except Exception as e:
                    logging.debug(f"关闭session时出错: {e}")
            logging.info(f"NetworkTask finished for: {self.task_type}")
# --- END ADDED ---

# --- ADDED: Task State Manager ---
class TaskStateManager(QObject):
    """任务状态管理器，防止重复操作和状态冲突"""
    task_state_changed = Signal(str)  # "starting", "running", "stopping", "stopped"

    def __init__(self):
        super().__init__()
        self._current_state = "stopped"
        self._state_lock = False
        self._stop_request_pending = False
        self._ocr_cleanup_timer = None  # 【OCR延迟清理】30秒延迟清理定时器
        self._ocr_hot_reset_timer = None  # 【OCR热重置】3秒延迟热重置定时器
        self._ocr_cleanup_cancelled = False  # 【修复】防止已触发的清理执行
        self._ocr_cleanup_generation = 0  # 清理代际号，用于失效旧停止周期的清理任务
        self._ocr_cleanup_idle_threshold_sec = 3.0  # 清理前要求OCR连续空闲秒数
        self._ocr_cleanup_recheck_min_sec = 0.2  # 空闲不足时的最小重试间隔
        self._background_threads = []
        self._background_threads_lock = threading.Lock()

    def get_current_state(self):
        return self._current_state

    def is_state_changing(self):
        return self._state_lock

    def is_running(self):
        """检查任务是否正在运行"""
        return self._current_state in ["starting", "running"]

    def _is_cleanup_context_valid(self, generation: int) -> bool:
        """检查清理上下文是否仍然有效（防止旧清理任务干扰新任务）"""
        if self._ocr_cleanup_cancelled:
            return False
        if generation != self._ocr_cleanup_generation:
            return False
        if self._current_state in ["starting", "running"]:
            return False
        return True

    def _get_ocr_cleanup_remaining_idle_sec(self, idle_seconds: float) -> float:
        """返回OCR达到空闲阈值还需等待的秒数（0表示可清理）"""
        try:
            target_idle = float(idle_seconds)
        except (TypeError, ValueError):
            target_idle = 3.0
        if target_idle < 0:
            target_idle = 0.0

        try:
            from services.multiprocess_ocr_pool import get_existing_multiprocess_ocr_pool
            pool = get_existing_multiprocess_ocr_pool()
            if pool is None:
                return 0.0

            # OCR池已关闭时视为空闲，避免无意义等待
            if bool(getattr(pool, "_is_shutdown", False)) or (hasattr(pool, "_running") and not bool(getattr(pool, "_running"))):
                return 0.0

            if hasattr(pool, "get_hot_reset_remaining_idle_sec"):
                remaining_idle = float(pool.get_hot_reset_remaining_idle_sec(target_idle))
            else:
                return 0.0

            if remaining_idle < 0:
                remaining_idle = 0.0

            # 无OCR进程时视为空闲，避免因池状态差异导致清理线程长时间挂起
            if remaining_idle >= target_idle and hasattr(pool, "get_stats"):
                try:
                    stats = pool.get_stats() or {}
                    total_processes = int(stats.get("total_processes", 0))
                    if total_processes <= 0:
                        return 0.0
                except Exception:
                    pass

            return remaining_idle
        except Exception as e:
            logging.warning(f"[OCR清理判定] 查询OCR空闲状态失败，按可清理处理: {e}")
            return 0.0

    def _prune_background_threads(self):
        with self._background_threads_lock:
            alive_threads = []
            for thread_ref in self._background_threads:
                if thread_ref is None:
                    continue
                try:
                    if thread_ref.is_alive():
                        alive_threads.append(thread_ref)
                except Exception:
                    continue
            self._background_threads = alive_threads

    def _start_background_thread(self, target, name: str, daemon: bool = True):
        thread_ref = threading.Thread(target=target, daemon=daemon, name=name)
        with self._background_threads_lock:
            alive_threads = []
            for existing_thread in self._background_threads:
                if existing_thread is None:
                    continue
                try:
                    if existing_thread.is_alive():
                        alive_threads.append(existing_thread)
                except Exception:
                    continue
            alive_threads.append(thread_ref)
            self._background_threads = alive_threads
        thread_ref.start()
        return thread_ref

    def _wait_background_threads(self, timeout: float = 2.0):
        try:
            wait_timeout = max(0.0, float(timeout))
        except (TypeError, ValueError):
            wait_timeout = 2.0
        deadline = time.time() + wait_timeout
        current_thread = threading.current_thread()
        while True:
            with self._background_threads_lock:
                join_candidates = []
                for thread_ref in self._background_threads:
                    if thread_ref is None:
                        continue
                    if thread_ref is current_thread:
                        continue
                    try:
                        if thread_ref.is_alive():
                            join_candidates.append(thread_ref)
                    except Exception:
                        continue
                self._background_threads = join_candidates
            if not join_candidates:
                return
            remaining = deadline - time.time()
            if remaining <= 0:
                return
            join_slice = min(0.2, remaining)
            for thread_ref in join_candidates:
                try:
                    thread_ref.join(join_slice)
                except Exception:
                    continue

    def _stop_and_delete_timer(self, timer_ref):
        if timer_ref is None:
            return None
        try:
            if timer_ref.isActive():
                timer_ref.stop()
        except Exception:
            pass
        try:
            timer_ref.timeout.disconnect()
        except Exception:
            pass
        try:
            timer_ref.deleteLater()
        except Exception:
            pass
        return None

    def shutdown(self, timeout: float = 2.0):
        """应用退出时停止内部清理定时器和后台线程。"""
        self._ocr_cleanup_cancelled = True
        self._ocr_cleanup_generation += 1
        self._ocr_cleanup_timer = self._stop_and_delete_timer(self._ocr_cleanup_timer)
        self._ocr_hot_reset_timer = self._stop_and_delete_timer(self._ocr_hot_reset_timer)
        self._wait_background_threads(timeout=timeout)

    def request_start(self):
        """请求启动任务"""
        logging.info(f"收到启动请求 - 当前状态: {self._current_state}, 状态锁: {self._state_lock}, 停止请求: {self._stop_request_pending}")

        # 【OCR延迟清理】如果有待执行的OCR清理定时器，取消它（30秒内重新启动）
        if self._ocr_cleanup_timer is not None:
            self._ocr_cleanup_timer = self._stop_and_delete_timer(self._ocr_cleanup_timer)
            logging.info("[OCR延迟清理] 检测到30秒内重新启动，取消OCR子进程清理定时器")

        # 【OCR热重置】如果有待执行的3秒热重置，启动新任务时取消
        if self._ocr_hot_reset_timer is not None:
            self._ocr_hot_reset_timer = self._stop_and_delete_timer(self._ocr_hot_reset_timer)
            logging.info("[OCR热重置] 检测到重新启动，取消3秒延迟热重置定时器")

        # 【修复】设置取消标志并推进代际，失效所有待执行清理
        self._ocr_cleanup_cancelled = True
        self._ocr_cleanup_generation += 1
        self._wait_background_threads(timeout=0.3)
        logging.debug("[OCR延迟清理] 设置取消标志并推进清理代际，防止任何待执行的清理")

        # 如果任务已经停止，强制重置所有锁定标志
        if self._current_state == "stopped":
            if self._state_lock or self._stop_request_pending:
                logging.info("任务已停止，强制重置所有锁定标志以允许启动")
                self._state_lock = False
                self._stop_request_pending = False

        if self._state_lock:
            logging.warning(f"任务状态正在改变中，忽略启动请求 (状态: {self._current_state}, 锁: {self._state_lock})")
            return False

        if self._current_state in ["starting", "running"]:
            logging.warning(f"任务已在运行状态 ({self._current_state})，忽略启动请求")
            return False

        self._state_lock = True
        self._current_state = "starting"
        self.task_state_changed.emit("starting")
        logging.info("任务状态: 正在启动...")
        return True

    def request_stop(self):
        """请求停止任务"""
        # 幂等处理：已停止/停止中时不再重复进入停止流程，避免重复触发重清理
        if self._current_state == "stopped":
            self._state_lock = False
            self._stop_request_pending = False
            logging.info("任务已停止，忽略重复停止请求")
            return True

        if self._current_state == "stopping" and self._stop_request_pending:
            logging.info("停止请求已在处理中，忽略重复停止请求")
            return True

        self._state_lock = True
        self._stop_request_pending = True
        self._current_state = "stopping"
        self.task_state_changed.emit("stopping")
        logging.info("任务状态: 正在停止...")
        return True

    def confirm_stopped(self):
        """确认任务已停止"""
        from PySide6.QtCore import QTimer, QThread

        # 跨线程调用时，切回对象所属线程执行，避免 QTimer(parent=self) 线程不匹配
        if QThread.currentThread() != self.thread():
            QTimer.singleShot(0, self, self.confirm_stopped)
            return

        # 无论当前状态如何，都强制重置到停止状态
        old_state = self._current_state
        self._current_state = "stopped"
        self._state_lock = False
        self._stop_request_pending = False

        # 幂等处理：若已处于停止态，仅同步状态，不重复触发重量级清理链路
        if old_state == "stopped":
            logging.debug("任务状态: 已处于停止态，跳过重复停止清理")
            return

        # 停止后立即释放YOLO推理会话，防止无任务时长期占用内存
        if cleanup_yolo_runtime_resources(release_process=False, compact_memory=False):
            logging.info("停止任务后已释放YOLO模型资源")

        # 【OCR延迟清理】取消之前的定时器（如果有）
        if self._ocr_cleanup_timer is not None:
            self._ocr_cleanup_timer = self._stop_and_delete_timer(self._ocr_cleanup_timer)
            logging.debug("[OCR延迟清理] 已清理之前的OCR清理定时器")

        # 【OCR热重置】取消之前的3秒热重置定时器（如果有）
        if self._ocr_hot_reset_timer is not None:
            self._ocr_hot_reset_timer = self._stop_and_delete_timer(self._ocr_hot_reset_timer)
            logging.debug("[OCR热重置] 已清理之前的3秒热重置定时器")

        # 清理 hover 诊断/追踪缓存，避免停止任务后继续占用内存
        try:
            from ui.workflow_parts.task_card import clear_hover_diagnostics_cache
            clear_hover_diagnostics_cache()
            logging.debug("[诊断清理] 已清理 hover 诊断/追踪缓存")
        except Exception as e:
            logging.debug(f"[诊断清理] 清理 hover 诊断/追踪缓存失败: {e}")

        # 清理Qt像素图全局缓存，释放大量卡片渲染缓存占用
        try:
            from PySide6.QtGui import QPixmapCache
            QPixmapCache.clear()
            logging.debug("[诊断清理] 已清理 QPixmapCache")
        except Exception as e:
            logging.debug(f"[诊断清理] 清理 QPixmapCache 失败: {e}")

        # 【修复】重置取消标志并推进代际，开启新的停止清理周期
        self._ocr_cleanup_cancelled = False
        self._ocr_cleanup_generation += 1
        cleanup_generation = self._ocr_cleanup_generation
        idle_threshold_sec = self._ocr_cleanup_idle_threshold_sec
        idle_recheck_min_sec = self._ocr_cleanup_recheck_min_sec

        def is_cleanup_context_valid():
            return self._is_cleanup_context_valid(cleanup_generation)

        def get_remaining_idle_sec():
            return self._get_ocr_cleanup_remaining_idle_sec(idle_threshold_sec)

        # 停止任务后按“连续空闲阈值”触发OCR热重置（期间有OCR活动则重置计时）
        def hot_reset_ocr_background():
            try:
                if not is_cleanup_context_valid():
                    return
                if get_remaining_idle_sec() > 0:
                    return

                from services.multiprocess_ocr_pool import get_existing_multiprocess_ocr_pool
                pool = get_existing_multiprocess_ocr_pool()
                if pool is None:
                    logging.debug("[OCR热重置] OCR池未初始化，跳过热重置")
                    return
                if hasattr(pool, 'hot_reset_all_idle_workers'):
                    reset_ok = bool(pool.hot_reset_all_idle_workers())
                    if reset_ok:
                        logging.debug("[OCR热重置] 已完成空闲子进程热重置")
                    else:
                        logging.debug("[OCR热重置] 当前无空闲子进程可热重置或重置未执行")
            except Exception as e:
                logging.warning(f"[OCR热重置] 停止任务后热重置失败: {e}")

        def schedule_hot_reset_timer(delay_sec: float):
            if not is_cleanup_context_valid():
                return

            delay_ms = max(1, int(max(0.0, float(delay_sec)) * 1000))
            if self._ocr_hot_reset_timer is not None:
                try:
                    if self._ocr_hot_reset_timer.isActive():
                        self._ocr_hot_reset_timer.stop()
                    try:
                        self._ocr_hot_reset_timer.timeout.disconnect()
                    except:
                        pass
                    self._ocr_hot_reset_timer.deleteLater()
                except Exception:
                    pass
                finally:
                    self._ocr_hot_reset_timer = None

            self._ocr_hot_reset_timer = QTimer(self)
            self._ocr_hot_reset_timer.setSingleShot(True)
            self._ocr_hot_reset_timer.timeout.connect(delayed_hot_reset)
            self._ocr_hot_reset_timer.start(delay_ms)

        def delayed_hot_reset():
            timer_ref = self._ocr_hot_reset_timer
            self._ocr_hot_reset_timer = None
            if timer_ref is not None:
                try:
                    timer_ref.deleteLater()
                except Exception:
                    pass

            if not is_cleanup_context_valid():
                logging.debug("[OCR热重置] 清理上下文已失效，跳过热重置")
                return

            remaining_idle_sec = get_remaining_idle_sec()
            if remaining_idle_sec > 0:
                next_delay_sec = max(idle_recheck_min_sec, remaining_idle_sec)
                schedule_hot_reset_timer(next_delay_sec)
                logging.debug(
                    f"[OCR热重置] 检测到近期仍有OCR活动，"
                    f"将在空闲倒计时后重试（剩余约 {remaining_idle_sec:.2f}s）"
                )
                return

            self._start_background_thread(
                target=hot_reset_ocr_background,
                daemon=True,
                name="OCR-HotReset-OnStop",
            )
            logging.debug(f"[OCR热重置] OCR已连续空闲{idle_threshold_sec:.1f}秒，已启动后台热重置线程")

        schedule_hot_reset_timer(idle_threshold_sec)
        logging.debug(f"[OCR热重置] 已启动“空闲{idle_threshold_sec:.1f}秒后热重置”检测（期间有OCR活动会自动重置计时）")

        # 【OCR延迟清理】启动延迟清理定时器，如果仍空闲才执行OCR子进程清理
        def schedule_ocr_cleanup_timer(delay_sec: float):
            if not is_cleanup_context_valid():
                return

            delay_ms = max(1, int(max(0.0, float(delay_sec)) * 1000))
            if self._ocr_cleanup_timer is not None:
                try:
                    if self._ocr_cleanup_timer.isActive():
                        self._ocr_cleanup_timer.stop()
                    try:
                        self._ocr_cleanup_timer.timeout.disconnect()
                    except:
                        pass
                    self._ocr_cleanup_timer.deleteLater()
                except Exception:
                    pass
                finally:
                    self._ocr_cleanup_timer = None

            self._ocr_cleanup_timer = QTimer(self)
            self._ocr_cleanup_timer.setSingleShot(True)
            self._ocr_cleanup_timer.timeout.connect(delayed_ocr_cleanup)
            self._ocr_cleanup_timer.start(delay_ms)

        def delayed_ocr_cleanup():
            """延迟后执行OCR清理（停止后立即强制回收）"""
            timer_ref = self._ocr_cleanup_timer
            self._ocr_cleanup_timer = None
            if timer_ref is not None:
                try:
                    timer_ref.deleteLater()
                except Exception:
                    pass

            if not is_cleanup_context_valid():
                logging.debug("[OCR延迟清理] 清理上下文已失效，跳过OCR清理")
                return

            # 【插件模式隔离】检查是否启用了插件模式，插件模式不需要清理OCR子进程
            try:
                from app_core.plugin_bridge import is_plugin_enabled
                plugin_enabled = is_plugin_enabled()
            except ImportError:
                plugin_enabled = False
            except Exception as e:
                logging.warning(f"[OCR延迟清理] 检查插件模式时发生异常: {e}，仅执行孤儿进程兜底清理")
                plugin_enabled = True

            if plugin_enabled:
                logging.debug("[OCR延迟清理] 检测到插件模式已启用，跳过OCR池清理，仅执行孤儿进程兜底清理")

            def cleanup_ocr_background():
                """后台清理OCR子进程，避免卡住UI"""
                try:
                    if not is_cleanup_context_valid():
                        logging.debug("[后台清理] OCR清理上下文失效，取消本次清理")
                        return

                    from services.multiprocess_ocr_pool import (
                        cleanup_orphan_ocr_subprocesses,
                        get_existing_multiprocess_ocr_pool,
                    )
                    logging.debug("[后台清理] 开始强制清理所有OCR子进程...")
                    if not plugin_enabled:
                        pool = get_existing_multiprocess_ocr_pool()
                        if pool is not None:
                            stats = pool.get_stats()
                            logging.debug(f"[后台清理] 当前OCR进程数: {stats.get('total_processes', 0)}")
                            pool.cleanup_all_processes_force()
                            stats = pool.get_stats()
                            logging.debug(f"[后台清理] 清理后OCR进程数: {stats.get('total_processes', 0)}")

                    cleaned_count = int(cleanup_orphan_ocr_subprocesses(main_pid=os.getpid()) or 0)
                    if cleaned_count > 0:
                        logging.info(f"[后台清理] OCR孤儿子进程已清理: {cleaned_count}")
                    else:
                        logging.debug("[后台清理] 未发现需要清理的OCR孤儿子进程")
                except Exception as e:
                    logging.error(f"[后台清理] OCR进程清理失败: {e}")
                    import traceback
                    logging.error(traceback.format_exc())

            self._start_background_thread(
                target=cleanup_ocr_background,
                daemon=True,
                name="OCR-Cleanup",
            )
            logging.debug("[后台清理] OCR清理线程已启动，不阻塞UI")

        schedule_ocr_cleanup_timer(0.2)
        logging.debug("[OCR延迟清理] 已启动立即清理定时器（停止后强制回收OCR子进程）")

        # 【后台清理】将所有耗时的清理操作放到后台线程，且仅在OCR空闲后执行
        def cleanup_resources_background():
            """后台清理所有资源，避免卡住UI"""
            try:
                import time

                while True:
                    if not is_cleanup_context_valid():
                        logging.debug("[后台清理] 清理上下文已失效，跳过资源清理")
                        return
                    remaining_idle_sec = get_remaining_idle_sec()
                    if remaining_idle_sec <= 0:
                        break
                    sleep_sec = max(idle_recheck_min_sec, min(1.0, remaining_idle_sec))
                    time.sleep(sleep_sec)

                # 【优化】记录清理前的内存占用
                memory_before = 0
                try:
                    import psutil
                    process = psutil.Process()
                    memory_before = process.memory_info().rss / 1024 / 1024
                    logging.debug(f"[后台清理] 清理前内存占用: {memory_before:.1f} MB")
                except:
                    pass

                if not is_cleanup_context_valid():
                    logging.debug("[后台清理] 资源清理开始前检测到上下文失效，跳过")
                    return

                # 1. 先关闭异步截图管道，避免清理引擎时仍有任务占用
                try:
                    from utils.async_screenshot import shutdown_global_pipeline
                    shutdown_global_pipeline()
                except Exception as e:
                    logging.warning(f"[后台清理] 关闭异步截图管道失败: {e}")

                # 2. 释放截图引擎资源（包含WGC捕获器/线程/帧池）
                try:
                    from utils.screenshot_helper import cleanup_all_screenshot_engines
                    cleanup_all_screenshot_engines()
                except Exception as e:
                    logging.warning(f"[后台清理] 截图引擎资源释放失败: {e}")

                # 3. 清理图片识别缓存（并行识别器缓存）
                try:
                    try:
                        from tasks.parallel_image_recognition import get_existing_parallel_recognizer
                        parallel_recognizer = get_existing_parallel_recognizer()
                        if parallel_recognizer and hasattr(parallel_recognizer, 'cleanup'):
                            parallel_recognizer.cleanup()
                            logging.debug("[后台清理] 已清理并行识别器缓存")
                    except ImportError:
                        pass
                    except Exception as e:
                        logging.warning(f"[后台清理] 并行识别器缓存清理失败: {e}")
                except Exception as e:
                    logging.warning(f"[后台清理] 图片识别缓存清理失败: {e}")

                # 4. 尝试清理numpy数组缓存（如果有）
                try:
                    import numpy as np
                    if hasattr(np, '_clear_internal_caches'):
                        np._clear_internal_caches()
                        logging.debug("[后台清理] numpy缓存已清理")
                except Exception:
                    pass

                # 5. 清理OpenCV缓存（如果有）
                try:
                    import cv2
                    if hasattr(cv2, 'destroyAllWindows'):
                        cv2.destroyAllWindows()
                except Exception:
                    pass

                # 6. 主动触发GC，尽快回收可释放对象
                try:
                    import gc
                    gc.collect()
                except Exception:
                    pass

                # 6.1 主进程工作集修剪（不改业务逻辑，仅做内存回收）
                try:
                    trimmed_mb = _trim_main_process_memory()
                    if trimmed_mb > 1.0:
                        logging.debug(f"[后台清理] 主进程内存修剪完成，释放约 {trimmed_mb:.1f} MB")
                except Exception as e:
                    logging.debug(f"[后台清理] 主进程内存修剪失败: {e}")

                # 7. 输出内存使用统计
                try:
                    import psutil
                    process = psutil.Process()
                    memory_after = process.memory_info().rss / 1024 / 1024

                    if memory_before > 0:
                        memory_freed = memory_before - memory_after
                        if memory_freed > 0:
                            logging.debug(f"[后台清理] 内存清理效果: 释放 {memory_freed:.1f} MB")
                        elif memory_freed < -5:
                            logging.warning(f"[后台清理] 清理期间内存增加了 {abs(memory_freed):.1f} MB")
                        else:
                            logging.debug(f"[后台清理] 当前内存占用: {memory_after:.1f} MB (变化: {memory_freed:+.1f} MB)")
                    else:
                        logging.debug(f"[后台清理] 当前内存占用: {memory_after:.1f} MB")
                except Exception:
                    pass

                logging.debug("[后台清理] 资源清理完成")
            except Exception as e:
                logging.error(f"[后台清理] 资源清理失败: {e}")
                import traceback
                logging.error(traceback.format_exc())

        self._start_background_thread(
            target=cleanup_resources_background,
            daemon=True,
            name="Resource-Cleanup",
        )
        logging.debug("[后台清理] 资源清理线程已启动，不阻塞UI")

        # 发出状态变化信号
        self.task_state_changed.emit("stopped")

        if old_state != "stopped":
            logging.info(f"任务状态: {old_state} -> stopped (已完全停止)")
        else:
            logging.info("任务状态: 确认已停止，重置所有锁定标志")

    def confirm_started(self):
        """确认任务已启动"""
        if self._current_state == "starting":
            self._current_state = "running"
            self._state_lock = False  # 启动完成后释放锁
            self.task_state_changed.emit("running")
            logging.info("任务状态: 已成功启动并运行")

    def reset_state(self):
        """重置状态 (应急使用)"""
        logging.warning("强制重置任务状态管理器")
        self.shutdown(timeout=0.5)
        self._current_state = "stopped"
        self._state_lock = False
        self._stop_request_pending = False
        self.task_state_changed.emit("stopped")

# 安全操作管理器已移除

# --- ADDED: Simplified Windows API Hotkey Implementation ---



# ============================================================
class SystemTrayManager(QObject):
    """系统托盘管理器，提供备用的启动/停止控制"""
    start_requested = Signal()
    stop_requested = Signal()
    show_window_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tray_icon = None
        self.main_window = None
        self._task_state_signal = None
        self._task_state_slot = None

    def attach_task_state_binding(self, signal_obj, slot_obj):
        """记录任务状态信号绑定，供 cleanup 时精确断连。"""
        self._task_state_signal = signal_obj
        self._task_state_slot = slot_obj

    def setup_tray(self, main_window):
        """设置系统托盘"""
        self.main_window = main_window

        if not QSystemTrayIcon.isSystemTrayAvailable():
            logging.warning("系统托盘不可用")
            return False

        try:
            # 创建托盘图标
            self.tray_icon = QSystemTrayIcon(self)

            # 设置图标（使用icon.ico图标文件）
            try:
                from PySide6.QtWidgets import QApplication
                from PySide6.QtGui import QIcon

                # 使用相对路径，支持开发和打包环境
                if getattr(sys, 'frozen', False):
                    # 打包后的环境（兼容Nuitka和PyInstaller）
                    if hasattr(sys, '_MEIPASS'):
                        base_path = sys._MEIPASS
                    else:
                        exe_path = os.path.abspath(sys.executable)
                        try:
                            exe_path = os.path.realpath(exe_path)
                        except Exception:
                            pass
                        base_path = os.path.dirname(exe_path)
                else:
                    # 开发环境
                    base_path = os.path.dirname(os.path.abspath(__file__))

                icon_path = os.path.join(base_path, "resources", "icon.ico")

                if os.path.exists(icon_path):
                    # 使用icon.ico图标文件
                    icon = QIcon(icon_path)
                    self.tray_icon.setIcon(icon)
                    logging.info(f" 系统托盘图标已设置: {icon_path}")
                else:
                    # 如果图标文件不存在，尝试使用应用程序图标
                    icon = main_window.windowIcon()
                    if icon.isNull():
                        # 使用系统默认图标
                        app = QApplication.instance()
                        if app:
                            icon = app.style().standardIcon(app.style().StandardPixmap.SP_ComputerIcon)
                    self.tray_icon.setIcon(icon)
                    logging.warning(f" 指定的图标文件不存在: {icon_path}，使用默认图标")
            except Exception as e:
                # 创建默认图标
                logging.warning(f"设置托盘图标时出错: {e}，使用默认图标")
                try:
                    from PySide6.QtGui import QPixmap, QIcon
                    from PySide6.QtCore import Qt
                    pixmap = QPixmap(16, 16)
                    pixmap.fill(Qt.GlobalColor.blue)
                    self.tray_icon.setIcon(QIcon(pixmap))
                except Exception as icon_error:
                    logging.error(f"创建默认图标失败: {icon_error}")
                    # 如果连默认图标都创建失败，就不设置图标

            # 创建右键菜单
            from PySide6.QtWidgets import QMenu
            from PySide6.QtGui import QAction
            from ui.system_parts.menu_style import apply_unified_menu_style

            tray_menu = apply_unified_menu_style(QMenu(), frameless=True)

            # 显示主窗口
            show_action = QAction("显示主窗口", self)
            show_action.triggered.connect(self.show_window_requested.emit)
            tray_menu.addAction(show_action)

            tray_menu.addSeparator()

            # 启动任务
            start_action = QAction("启动任务 (F9)", self)
            start_action.triggered.connect(self._on_start_requested)
            tray_menu.addAction(start_action)

            # 停止任务
            stop_action = QAction("停止任务 (F10)", self)
            stop_action.triggered.connect(self._on_stop_requested)
            tray_menu.addAction(stop_action)

            tray_menu.addSeparator()

            # 清除关闭记住选择
            reset_close_action = QAction("清除关闭记住选择", self)
            reset_close_action.triggered.connect(self._on_reset_close_choice)
            tray_menu.addAction(reset_close_action)

            tray_menu.addSeparator()

            # 退出程序
            quit_action = QAction("退出程序", self)
            app = QApplication.instance()
            if app:
                quit_action.triggered.connect(app.quit)
            tray_menu.addAction(quit_action)

            self.tray_icon.setContextMenu(tray_menu)

            # 设置提示文本
            self.tray_icon.setToolTip("工作流自动化工具\n右键查看菜单")

            # 双击显示主窗口
            self.tray_icon.activated.connect(self._on_tray_activated)

            # 显示托盘图标
            self.tray_icon.show()

            logging.info(" 系统托盘已设置，可作为热键的备用控制方式")
            return True

        except Exception as e:
            logging.error(f"设置系统托盘失败: {e}")
            return False

    def _on_tray_activated(self, reason):
        """托盘图标激活处理"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_window_requested.emit()

    def _on_start_requested(self):
        """启动任务请求"""
        logging.info(" 系统托盘请求启动任务")
        self.start_requested.emit()

    def _on_stop_requested(self):
        """停止任务请求"""
        logging.info(" 系统托盘请求停止任务")
        self.stop_requested.emit()

    def _on_reset_close_choice(self):
        """清除关闭记住选择"""
        try:
            if self.main_window is not None and hasattr(self.main_window, "config"):
                self.main_window.config["close_behavior"] = "ask"
                self.main_window.config["close_behavior_remember"] = False
                if hasattr(self.main_window, "save_config_func") and callable(self.main_window.save_config_func):
                    self.main_window.save_config_func(self.main_window.config)
            try:
                from PySide6.QtCore import QSettings
                settings = QSettings("LCA", "LCA")
                settings.setValue("close_behavior", "ask")
                settings.setValue("close_behavior_remember", False)
            except Exception:
                pass
            if self.tray_icon:
                self.tray_icon.showMessage("设置已重置", "已清除关闭记住选择", QSystemTrayIcon.MessageIcon.Information, 2000)
        except Exception as exc:
            logging.error(f"清除关闭记住选择失败: {exc}")

    def update_tooltip(self, status):
        """更新托盘提示文本"""
        if self.tray_icon:
            self.tray_icon.setToolTip(f"工作流自动化工具\n状态: {status}\n右键查看菜单")

    def show_message(self, title, message, icon=QSystemTrayIcon.MessageIcon.Information):
        """显示托盘通知"""
        if self.tray_icon:
            self.tray_icon.showMessage(title, message, icon, 3000)  # 3秒显示时间

    def cleanup(self):
        """清理系统托盘资源和信号连接"""
        try:
            if self._task_state_signal is not None and self._task_state_slot is not None:
                try:
                    self._task_state_signal.disconnect(self._task_state_slot)
                except (TypeError, RuntimeError):
                    pass
                finally:
                    self._task_state_signal = None
                    self._task_state_slot = None
            if self.tray_icon:
                # 隐藏托盘图标
                self.tray_icon.hide()
                # 断开所有信号连接
                try:
                    self.start_requested.disconnect()
                except TypeError:
                    pass
                try:
                    self.stop_requested.disconnect()
                except TypeError:
                    pass
                try:
                    self.show_window_requested.disconnect()
                except TypeError:
                    pass
                # 删除托盘图标
                self.tray_icon.deleteLater()
                self.tray_icon = None
                logging.info("系统托盘已清理")
        except Exception as e:
            logging.error(f"清理系统托盘时出错: {e}")

# 【关键】主程序入口 - 只有主进程才执行
# 子进程（如OCR工作进程）会跳过整个 if __name__ == "__main__" 块
# multiprocessing 会自动调用 target 函数（如 ocr_worker_main）
# ============================================================
# --- ADDED: Define Application Root ---
# Best effort to find the script's directory, works well for direct execution and some freezing tools.
try:
    # If running as a script
    APP_ROOT = os.path.abspath(os.path.dirname(sys.argv[0]))
except NameError:
    # Fallback if sys.argv[0] is not defined (e.g., interactive session)
    APP_ROOT = os.path.abspath(os.path.dirname(__file__))

logging.info(f"应用程序根目录: {APP_ROOT}")
# ---------------------------------------------------------

# --- ADDED: Enhanced Global Exception Handler Function ---
def global_exception_handler(exctype, value, traceback_obj):
    """增强的全局异常处理函数，防止程序闪退并提供详细的错误信息。"""
    # 用户主动中断（Ctrl+C / IDE停止）按正常退出处理，避免误报严重异常
    if exctype is KeyboardInterrupt:
        logging.info("收到键盘中断信号，程序正常退出。")
        try:
            _emergency_cleanup()
        except Exception:
            pass
        sys.exit(0)

    error_message = "发生了一个意外错误。程序将尝试继续运行，但建议保存工作并重启。"

    # 记录详细的异常信息
    logging.critical("捕获到未处理的全局异常!", exc_info=(exctype, value, traceback_obj))

    # 检查是否是致命错误
    is_fatal = _is_fatal_exception(exctype, value)

    # 尝试紧急清理
    try:
        _emergency_cleanup()
    except Exception as cleanup_ex:
        logging.error(f"紧急清理失败: {cleanup_ex}")

    # 尝试以安全的方式显示错误给用户
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance():
            # 使用 QMessageBox 显示更友好的错误信息
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("程序异常" if not is_fatal else "严重错误")
            msg_box.setText(error_message if not is_fatal else "发生了严重错误，程序必须退出。")

            # 提供详细信息
            detailed_text = "\n".join(format_exception(exctype, value, traceback_obj))
            msg_box.setDetailedText(detailed_text)

            if is_fatal:
                msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
                msg_box.setInformativeText("请保存重要数据并重启程序。")
            else:
                msg_box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Ignore)
                msg_box.setInformativeText("您可以选择继续运行，但建议保存工作并重启程序。")

            place_dialog_on_screen(msg_box, reference_widget=QApplication.activeWindow())
            result = msg_box.exec()

            # 如果是致命错误或用户选择退出
            if is_fatal or result == QMessageBox.StandardButton.Ok:
                logging.info("用户选择退出或遇到致命错误，程序即将退出")
                sys.exit(1)
        else:
            # Fallback if no QApplication
            print(f"CRITICAL ERROR: {error_message}", file=sys.stderr)
            print("--- TRACEBACK ---", file=sys.stderr)
            print("\n".join(format_exception(exctype, value, traceback_obj)), file=sys.stderr)
            print("-----------------", file=sys.stderr)
            if is_fatal:
                sys.exit(1)

    except Exception as e_handler_ex:
        # 如果在显示错误时也发生错误，记录下来
        logging.error(f"在全局异常处理器中显示错误时发生错误: {e_handler_ex}", exc_info=True)
        print(f"EXCEPTION IN EXCEPTION HANDLER: {e_handler_ex}", file=sys.stderr)
        print("Original error was not shown in GUI.", file=sys.stderr)
        if is_fatal:
            sys.exit(1)

def _is_fatal_exception(exctype, value):
    """判断异常是否是致命的"""
    fatal_exceptions = [
        MemoryError,
        SystemExit,
        KeyboardInterrupt,
    ]

    # 检查异常类型
    if exctype in fatal_exceptions:
        return True

    # 检查异常消息中的关键词
    error_msg = str(value).lower()
    fatal_keywords = [
        'segmentation fault',
        'access violation',
        'stack overflow',
        'out of memory',
        'corrupted',
    ]

    return any(keyword in error_msg for keyword in fatal_keywords)

def _emergency_cleanup():
    """紧急清理函数"""
    try:
        logging.info("执行紧急清理...")

        # 处理Qt事件
        try:
            from PySide6.QtWidgets import QApplication
            if QApplication.instance():
                QApplication.processEvents()
        except:
            pass

        # 清理许可证监控
        try:
            cleanup_license_monitoring()
        except:
            pass

        logging.info("紧急清理完成")

    except Exception as e:
        logging.error(f"紧急清理失败: {e}")
# --- END ADDED ---

if __name__ == "__main__" and not _IS_SUBPROCESS:
    # --- ADDED: Set the global exception hook at the very beginning ---
    sys.excepthook = global_exception_handler
    # -----------------------------------------------------------------

    if not _acquire_single_instance_lock():
        logging.warning("主实例锁获取失败或已有主实例运行，当前进程退出。")
        _show_existing_instance_hint()
        try:
            sys.exit(0)
        finally:
            os._exit(0)
    atexit.register(_release_single_instance_lock)

    #  注册关键函数到间接调用表
    _0xbeef(0x1001, validate_license_with_server)
    _0xbeef(0x1002, enforce_online_validation)
    _0xbeef(0x1003, _encrypt_license_key)
    _0xbeef(0x1004, _decrypt_license_key)

    logging.info(" 应用程序安全启动。")

    logging.info("开始授权验证...")

    # 工具 修复：确保我们在正确的执行路径上（已通过管理员权限检查）
    if os.name == 'nt' and not is_admin():
        logging.critical("严重错误：代码执行到此处但仍然没有管理员权限！这不应该发生。")
        logging.critical("可能的原因：管理员权限提升逻辑存在问题。程序将立即退出。")
        sys.exit(1)

    from app_core.app_runtime_bootstrap import (
        configure_application_icon,
        configure_application_presentation,
        connect_main_window_runtime_bindings,
        create_application,
        initialize_plugin_system_background,
        install_global_ui_helpers,
        run_qt_event_loop,
        start_log_maintenance_loop,
    )

    app = create_application(sys.argv)

    tooltip_manager = install_global_ui_helpers(app)

    plugin_init_thread = initialize_plugin_system_background(timeout_seconds=3.0)

    configure_application_icon(app, sys, __file__)
    configure_application_presentation(app, tooltip_manager, Qt)


    # --- ADDED: Initialize State Management System ---
    logging.info("初始化任务状态管理系统...")
    task_state_manager = TaskStateManager()

    # 将task_state_manager设置为app的属性，使其全局可访问
    app.task_state_manager = task_state_manager
    logging.info("任务状态管理器已设置为全局可访问")

    main_process_memory_watchdog = None
    try:
        main_process_memory_watchdog = MainProcessMemoryWatchdog(task_state_manager=task_state_manager)
        main_process_memory_watchdog.start()
    except Exception as mem_watchdog_error:
        logging.warning(f"[内存巡检] 启动失败: {mem_watchdog_error}")
        main_process_memory_watchdog = None

    # --- MODIFIED: Disable Simple Hotkey Listener (Now handled by MainWindow) ---
    # SimpleHotkeyListener 已被 MainWindow 的统一快捷键系统替代
    # MainWindow._update_hotkeys() 现在负责所有快捷键的注册和管理
    # 这样可以支持动态修改快捷键并立即生效
    simple_hotkey_listener = None
    system_tray = None

    # 检查管理员权限
    admin_status = is_admin()
    logging.info(f" 管理员权限状态: {' 已获得' if admin_status else ' 未获得'}")

    # 不再启动独立的热键监听器，快捷键将由 MainWindow 统一管理
    # 原有的 SimpleHotkeyListener 代码已注释，保留以供参考
    # try:
    #     logging.info(" 启动热键监听器...")
    #     simple_hotkey_listener = SimpleHotkeyListener()
    #
    #     if simple_hotkey_listener.start_listening():
    #         logging.info(" 热键监听器启动成功")
    #     else:
    #         logging.warning(" 热键监听器启动失败")
    #         simple_hotkey_listener = None
    #
    # except Exception as e:
    #     logging.error(f"创建热键监听器失败: {e}")
    #     simple_hotkey_listener = None

    logging.info(" 快捷键系统将由 MainWindow 统一管理")

    # 设置系统托盘作为备用控制方式
    try:
        system_tray = SystemTrayManager()
        logging.info(" 系统托盘管理器已创建，将在主窗口创建后设置")
    except Exception as e:
        logging.warning(f"创建系统托盘管理器失败: {e}")
        system_tray = None  # 确保变量存在

    # ==================== 密钥验证相关代码 ====================
    # 以下代码用于硬件ID获取和许可证密钥验证

    hardware_id = get_hardware_id()
    if not hardware_id:
        logging.critical("无法获取硬件 ID，程序无法继续。")
        show_critical_box(None, "错误", "无法获取必要的硬件信息以进行授权。\n请检查系统设置或联系支持。")
        sys.exit(1)

    #  优化：尝试从加密缓存加载许可证密钥，但仍需在线验证
    license_key = load_local_license()
    if license_key:
        logging.info(" 从加密缓存加载到许可证密钥，将进行在线验证")
    else:
        logging.info(" 未找到缓存的许可证密钥，需要用户输入")

    is_validated = False
    last_status_code = 0

    # We need a session object. It's good practice to create it once and reuse.
    # Let's make it available for both registration and validation.
    http_session = requests.Session()

    # --- ADDED: Initial check and potential migration attempt ---
    # Determine if the current hardware_id is likely an old format from the file
    is_old_format_hwid = isinstance(hardware_id, str) and len(hardware_id) != 64

    #  强化：跳过迁移逻辑，因为不再使用本地许可证文件
    # 所有验证都必须通过在线方式进行
    logging.info(" 强制在线验证模式：跳过本地许可证文件和迁移逻辑")

    # After potential migration attempt (or if not needed), proceed with standard validation/input loop.
    # If migration succeeded, hardware_id is now the new SHA256 ID.
    # If migration failed or wasn't needed, hardware_id is either the original valid ID, the old format ID, or None.

    # We now enter a loop that continues until is_validated becomes True
    # If is_validated was already True after initial checks (e.g., valid local HWID + Key), this loop is skipped.
    # Note: Initial validation with local key is now handled BEFORE this loop if hardware_id is already a valid SHA256.
    # If hardware_id was old format and migration failed, we enter this loop.

    # ============================================================================
    # 【安全关键】硬件ID注册 - 所有模式都必须完成，不可跳过
    # ============================================================================
    # 注意：硬件ID注册与插件模式的授权验证是两个独立的安全层：
    # 1. 硬件ID注册：所有用户（插件模式/非插件模式）都必须完成，用于追踪和管理客户端
    # 2. 授权验证：仅在插件模式且服务器开启验证时需要，用于验证付费授权
    # ============================================================================

    logging.info("【安全检查】开始强制硬件ID注册（所有模式必须完成）...")
    try:
        initial_registration_result = attempt_client_registration(hardware_id, http_session)
    finally:
        try:
            http_session.close()
        except Exception:
            pass

    # 【安全关键】检查注册结果 - 必须成功，否则退出程序
    if initial_registration_result.get("is_banned", False):
        ban_reason = initial_registration_result.get("ban_reason", "未提供原因")
        logging.critical(f"【安全阻止】硬件ID已被封禁: {ban_reason}")
        show_critical_box(
            None,
            "账号已被封禁",
            f"您的硬件ID已被封禁，无法使用本软件。\n\n"
            f"封禁原因: {ban_reason}\n\n"
            f"如有疑问，请联系技术支持。"
        )
        sys.exit(1)

    if not initial_registration_result.get("success", False):
        logging.critical("【安全失败】硬件ID注册失败，程序无法继续运行")
        failure_reason = str(initial_registration_result.get("error") or "").strip()
        if not failure_reason:
            status_code = initial_registration_result.get("status_code")
            failure_reason = f"注册失败，状态码: {status_code}" if status_code else "网络异常，请重启软件"
        show_critical_box(
            None,
            "注册失败",
            f"{failure_reason}\n\n如果网络是校园网或公司网，可能无法连接。"
        )
        sys.exit(1)

    logging.info("【安全通过】硬件ID注册成功")

    logging.info("【安全通过】硬件ID未被封禁")

    # 获取服务器的验证状态（仅影响插件模式的授权验证，不影响硬件ID注册）
    server_license_validation_enabled = initial_registration_result.get("license_validation_enabled", True)
    logging.info(f"服务器许可证验证状态: {'开启' if server_license_validation_enabled else '关闭'}")

    # ============================================================================
    # 【第二层安全】插件模式授权验证（可选，根据服务器开关决定）
    # ============================================================================
    # 注意：此处的验证与上面的硬件ID注册是两个不同的安全层：
    # - 硬件ID注册：已在上方完成，所有用户必须通过，不可跳过
    # - 授权验证：仅在插件模式启用且服务器开关开启时需要
    # ============================================================================

    # 检查是否启用了插件模式
    try:
        from utils.app_paths import get_config_path
        config_path = get_config_path()
        plugin_mode_enabled = False
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                plugin_mode_enabled = config_data.get('plugin_settings', {}).get('enabled', False)
        logging.info(f"插件模式状态: {'已启用' if plugin_mode_enabled else '未启用'}")
    except Exception as e:
        logging.warning(f"读取插件模式配置失败: {e}")
        plugin_mode_enabled = False

    # 插件模式验证逻辑（根据服务器验证开关决定）
    # 注意：此处只验证授权码，硬件ID注册已在上方强制完成
    if plugin_mode_enabled:
        logging.info("检测到插件模式已启用")

        # 插件模式下，根据服务器验证开关来决定是否需要验证授权码
        if server_license_validation_enabled:
            logging.info("服务器验证开关已开启，插件模式需要进行授权验证")

            # 检查是否有有效的授权码
            if not license_key or license_key == "SERVER_VALIDATION_DISABLED":
                logging.critical("插件模式已启用且服务器要求验证，但未找到有效的授权码")
                show_critical_box(
                    None,
                    "插件模式需要授权",
                    "检测到配置文件中已启用插件模式，且服务器要求授权验证，但未找到有效的授权码。\n\n"
                    "插件模式需要有效的授权才能使用。\n"
                    "程序启动后，请在全局设置中禁用插件模式，或完成授权验证。\n\n"
                    "本次运行将临时禁用插件模式（不修改配置文件）。"
                )
                # 【修复】仅在内存中禁用，不修改config.json，保留用户配置
                logging.info("临时禁用插件模式（本次运行），配置文件保持不变")
                plugin_mode_enabled = False
            else:
                # 服务器验证开关已开启，强制进行在线验证，确保授权码有效且未过期
                logging.info("插件模式：开始强制在线验证授权码的有效性和时效性...")
                try:
                    is_valid, status_code, license_type = enforce_online_validation(hardware_id, license_key)

                    if not is_valid:
                        logging.critical(f"插件模式授权验证失败：状态码 {status_code}")
                        show_critical_box(
                            None,
                            "插件授权验证失败",
                            f"插件模式授权验证失败（状态码：{status_code}）。\n\n"
                            "可能的原因：\n"
                            "- 授权码已过期\n"
                            "- 授权码无效\n"
                            "- 网络连接失败\n\n"
                            "插件模式将被自动禁用。"
                        )

                        # 删除无效的授权文件
                        try:
                            if os.path.exists(LICENSE_FILE):
                                os.remove(LICENSE_FILE)
                                logging.info("已删除无效的授权文件")
                        except:
                            pass

                        # 【修复】仅在内存中禁用，不修改config.json，保留用户配置
                        logging.info("临时禁用插件模式（授权验证失败），配置文件保持不变")
                        plugin_mode_enabled = False
                    else:
                        # 更新授权类型（VALIDATED_LICENSE_TYPE 已在模块级别定义）
                        VALIDATED_LICENSE_TYPE = license_type
                        logging.info(f"插件模式授权验证成功，授权类型: {license_type}")

                        # 【新增】启动插件授权后台监控线程
                        try:
                            _start_plugin_license_monitor(
                                hardware_id=hardware_id,
                                license_key=license_key,
                                app_instance=app,
                            )
                            logging.info("插件授权后台监控线程已启动")
                        except Exception as monitor_error:
                            logging.error(f"启动插件授权监控线程失败: {monitor_error}", exc_info=True)

                except Exception as e:
                    logging.error(f"插件模式授权验证异常: {e}", exc_info=True)
                    show_critical_box(
                        None,
                        "插件授权验证异常",
                        f"插件模式授权验证过程中发生异常：{str(e)}\n\n"
                        "插件模式将被自动禁用。"
                    )
                    plugin_mode_enabled = False
        else:
            # 服务器验证开关已关闭，插件模式不需要验证授权码
            # 但硬件ID注册已在上方强制完成，这是不可跳过的
            logging.info("服务器验证开关已关闭，插件模式无需授权验证")
            logging.info("注意：虽然跳过授权验证，但硬件ID注册已强制完成")
            # 设置默认的授权类型，允许插件模式正常运行
            VALIDATED_LICENSE_TYPE = "PLUGIN_NO_VALIDATION"
            logging.info("已设置插件模式为无需验证状态")

    # 非插件模式：只需要注册硬件ID（已完成），无需验证授权码
    # 插件模式：已在上面的逻辑中处理授权验证
    # 注意：无论哪种模式，硬件ID注册都已在前面强制完成
    if not plugin_mode_enabled:
        logging.info("非插件模式：硬件ID已注册（上方完成），无需验证授权码")
        is_validated = True
        license_key = "NO_LICENSE_REQUIRED"
        sys._license_validated = True
        VALIDATED_LICENSE_TYPE = "EDITOR"

        # 设置注册验证标记（反调试检查需要）
        sys._registration_verified = os.urandom(32).hex()
        sys._registration_hwid = hardware_id

        logging.info("非插件模式授权验证成功（仅硬件ID注册）")
    elif plugin_mode_enabled and not server_license_validation_enabled:
        # 插件模式但服务器验证关闭：硬件ID已注册（上方完成），无需验证授权码
        logging.info("插件模式且服务器验证关闭：无需验证授权码")
        is_validated = True
        license_key = "SERVER_VALIDATION_DISABLED"
        sys._license_validated = True
        VALIDATED_LICENSE_TYPE = "EDITOR"

        # 设置注册验证标记（反调试检查需要）
        sys._registration_verified = os.urandom(32).hex()
        sys._registration_hwid = hardware_id

        logging.info("插件模式授权验证成功（服务器禁用验证模式）")
    elif plugin_mode_enabled and server_license_validation_enabled:
        # 插件模式且服务器验证开启：已在上面的代码中处理过验证逻辑
        # 这里检查验证是否成功
        if license_key and license_key not in ["NO_LICENSE_REQUIRED", "SERVER_VALIDATION_DISABLED"]:
            logging.info("插件模式验证已完成，继续启动流程")
            is_validated = True
            sys._license_validated = True
            sys._registration_verified = os.urandom(32).hex()
            sys._registration_hwid = hardware_id
        else:
            logging.warning("插件模式验证未完成，可能已被禁用")
            is_validated = True  # 允许继续，因为插件模式可能已被自动禁用
            license_key = "NO_LICENSE_REQUIRED"
            sys._license_validated = True
            VALIDATED_LICENSE_TYPE = "EDITOR"
            sys._registration_verified = os.urandom(32).hex()
            sys._registration_hwid = hardware_id

    # 旧的验证逻辑已被移除，新逻辑如下：
    # - 非插件模式：只需注册硬件ID，无需验证授权码
    # - 插件模式+服务器验证关闭：无需验证授权码
    # - 插件模式+服务器验证开启：需要验证授权码
    #
    # 如果服务器关闭了验证，直接跳过许可证验证（但插件模式除外）
    # if not server_license_validation_enabled:
    # --- END MODIFIED validation/input loop ---

    # This block is reached ONLY if is_validated is True (loop condition is false)
    logging.info("锁定 授权验证成功，启动主程序...")
    logging.info(f"搜索 授权信息: 硬件ID=***..., 许可证={'已验证' if license_key else '未知'}")
    # ==================== 密钥验证相关代码结束 ====================

    # 反调试：多重验证标记检查（防止跳过注册流程）
    # 检查1：验证标记是否存在
    if not hasattr(sys, '_registration_verified'):
        os._exit(1)

    # 检查2：验证标记是否有效
    if not sys._registration_verified or len(sys._registration_verified) != 64:
        os._exit(1)

    # 检查3：硬件ID是否匹配
    if not hasattr(sys, '_registration_hwid'):
        os._exit(1)

    # 检查4：硬件ID格式验证
    _current_hwid = get_hardware_id()
    if sys._registration_hwid != _current_hwid:
        os._exit(1)

    # 工具 修复：添加主窗口创建的详细调试信息
    try:
        logging.info("开始创建主窗口...")

        # Create and show the main window with enhanced state management
        from utils.app_paths import get_images_dir

        main_window = MainWindow(
            task_modules=get_task_modules(),
            initial_config=config,
            hardware_id=hardware_id, # Use the final, validated HWID
            license_key=license_key, # Use the validated license key
            save_config_func=save_config,
            images_dir=get_images_dir("LCA"),
            task_state_manager=task_state_manager  # 传递任务状态管理器
        )
        logging.info("主窗口创建成功，准备显示...")

        main_window.show()
        logging.info("主窗口显示成功")

        # 主题切换回调已由各个 WorkflowView 自行注册，无需在此处理

        # 设置通用分辨率适配器的配置文件路径（用于支持动态参考分辨率）
        try:
            from utils.universal_resolution_adapter import get_universal_adapter
            from utils.app_paths import get_config_path
            config_path = get_config_path()
            get_universal_adapter().set_main_config_path(config_path)
            logging.info(f"已设置通用分辨率适配器配置文件路径: {config_path}")
        except Exception as adapter_error:
            logging.warning(f"设置通用分辨率适配器配置路径失败: {adapter_error}")

        # 强制所有 QComboBox 向下展开
        # Ensure QComboBox popups open downward and keep rounded corners.
        try:
            from PySide6.QtCore import QObject, QEvent, QTimer, Qt
            from PySide6.QtWidgets import QApplication, QAbstractItemView, QComboBox, QWidget, QFrame

            class ComboBoxPopupFixer(QObject):
                def __init__(self, radius: int = 8, parent=None):
                    super().__init__(parent)
                    self._radius = radius

                def eventFilter(self, obj, event):
                    if event.type() not in (QEvent.Type.Show, QEvent.Type.ShowToParent):
                        return False

                    popup = None
                    combo = None

                    try:
                        if isinstance(obj, QAbstractItemView):
                            popup = obj.window()
                            if popup:
                                combo = popup.parentWidget()
                        else:
                            class_name = obj.metaObject().className() if hasattr(obj, "metaObject") else ""
                            if class_name == "QComboBoxPrivateContainer":
                                popup = obj
                                combo = obj.parentWidget()
                    except Exception:
                        return False

                    if not popup or not combo or not isinstance(combo, QComboBox):
                        return False

                    if popup.property("_combo_popup_fixing"):
                        return False

                    popup.setProperty("_combo_popup_fixing", True)
                    QTimer.singleShot(0, lambda: self._fix_popup(combo, popup))
                    return False

                def _fix_popup(self, combo, popup):
                    try:
                        if not popup or not combo or not popup.isVisible():
                            return

                        popup.setContentsMargins(0, 0, 0, 0)
                        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
                        popup.setAutoFillBackground(True)
                        popup.setStyleSheet("")

                        flags = popup.windowFlags()
                        desired = (
                            flags
                            | Qt.WindowType.Popup
                            | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint
                        )
                        if flags != desired:
                            popup.setWindowFlags(desired)
                            popup.show()

                        combo_rect = combo.rect()
                        combo_bottom_left = combo.mapToGlobal(combo_rect.bottomLeft())
                        popup.move(combo_bottom_left)

                        max_visible = 8
                        combo.setMaxVisibleItems(max_visible)
                        view = combo.view()
                        if view:
                            view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                            view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                            view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
                            view.setAutoFillBackground(True)
                            if view.viewport():
                                view.viewport().setAutoFillBackground(True)
                                view.viewport().setContentsMargins(0, 0, 0, 0)
                            view.setContentsMargins(0, 0, 0, 0)
                            view.setFrameShape(QFrame.Shape.NoFrame)
                            view.setLineWidth(0)
                            view.setMidLineWidth(0)

                            # Force-hide the built-in up/down scroller widgets (triangles)
                            for child in popup.findChildren(QWidget):
                                name = child.objectName()
                                class_name = child.metaObject().className() if hasattr(child, "metaObject") else ""
                                if (
                                    name in ("qt_scrollarea_up_button", "qt_scrollarea_down_button",
                                             "qt_scrollarea_up_scroller", "qt_scrollarea_down_scroller")
                                    or "Scroller" in class_name
                                ):
                                    child.hide()
                                    child.setEnabled(False)
                                    child.setFixedSize(0, 0)

                            # Enforce popup height to max_visible items
                            try:
                                item_count = combo.count()
                                visible_count = min(item_count, max_visible) if item_count > 0 else max_visible
                                row_height = view.sizeHintForRow(0) if item_count > 0 else view.sizeHint().height()
                                if row_height <= 0:
                                    row_height = view.fontMetrics().height() + 8
                                spacing = view.spacing() if hasattr(view, "spacing") else 0
                                margins = view.contentsMargins()
                                desired_view_height = (
                                    row_height * visible_count
                                    + max(0, visible_count - 1) * spacing
                                    + margins.top()
                                    + margins.bottom()
                                    + view.frameWidth() * 2
                                )
                                extra = max(0, popup.height() - view.height())
                                view.setMinimumHeight(desired_view_height)
                                view.setMaximumHeight(desired_view_height)
                                popup.setFixedHeight(extra + desired_view_height)
                            except Exception:
                                pass

                        screen = combo.screen() or QApplication.primaryScreen()
                        if screen:
                            screen_geometry = screen.availableGeometry()
                            popup_rect = popup.geometry()
                            if popup_rect.bottom() > screen_geometry.bottom():
                                new_height = screen_geometry.bottom() - combo_bottom_left.y() - 5
                                if new_height > 0 and new_height < popup.height():
                                    popup.setFixedHeight(new_height)
                                    popup.move(combo_bottom_left)

                        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                    finally:
                        if popup:
                            popup.setProperty("_combo_popup_fixing", False)

            app = QApplication.instance()
            if app:
                app._combo_popup_fixer = ComboBoxPopupFixer(parent=app)
                app.installEventFilter(app._combo_popup_fixer)
                logging.info("Installed global QComboBox popup fixer.")
        except Exception as popup_fix_error:
            logging.warning(f"安装 QComboBox 下拉修复器失败：{popup_fix_error}")

        # --- 新增：首次启动时检查并安装 Interception 驱动 ---
        def check_and_install_interception_driver():
            """首次启动时检查并安装 Interception 驱动"""
            try:
                from PySide6.QtCore import QTimer
                import os
                from utils.input_simulation.mode_utils import requires_interception_driver

                logging.info("开始检查 Interception 驱动状态...")

                config = getattr(main_window, "config", {}) or {}
                execution_mode = str(config.get("execution_mode", "") or "").strip().lower()
                legacy_backend = str(config.get("foreground_driver_backend", "interception") or "interception").strip().lower()
                mouse_backend = str(config.get("foreground_mouse_driver_backend", legacy_backend) or legacy_backend).strip().lower()
                keyboard_backend = str(config.get("foreground_keyboard_driver_backend", legacy_backend) or legacy_backend).strip().lower()

                if not requires_interception_driver(
                    execution_mode,
                    mouse_backend=mouse_backend,
                    keyboard_backend=keyboard_backend,
                ):
                    logging.info(
                        "当前启动配置不依赖 Interception，跳过驱动检查: "
                        f"mode={execution_mode or 'unknown'}, mouse={mouse_backend}, keyboard={keyboard_backend}"
                    )
                    return

                # 检查驱动安装程序是否存在
                installer_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             "Interception", "command line installer", "install-interception.exe")

                if not os.path.exists(installer_path):
                    logging.warning(f"Interception 驱动安装程序不存在: {installer_path}")
                    return

                # 尝试检测驱动是否已安装（通过尝试加载DLL）
                try:
                    from utils.interception_driver import get_driver
                    driver = get_driver()

                    # 尝试初始化驱动（不显示重启提示）
                    if driver.initialize():
                        logging.info("Interception 驱动已安装且可用")
                        # 保持驱动上下文，避免后续使用时重复初始化和DPI检测
                        return

                    prompt_config = driver.get_restart_prompt_config()
                    if prompt_config:
                        logging.info("检测到驱动需要提示用户处理")

                        # 延迟显示重启提示（避免阻塞主窗口显示）
                        def show_restart_dialog():
                            try:
                                from PySide6.QtWidgets import QMessageBox
                                msg_box = QMessageBox(main_window)
                                msg_box.setIcon(QMessageBox.Icon.Information)
                                title, message, informative_text = prompt_config
                                msg_box.setWindowTitle(title)
                                msg_box.setText(message)
                                msg_box.setInformativeText(informative_text)
                                msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
                                msg_box.exec()
                                logging.info("用户已确认重启提示")
                            except Exception as e:
                                logging.error(f"显示重启提示时出错: {e}")

                        # 延迟2秒显示，确保主窗口完全初始化
                        QTimer.singleShot(2000, show_restart_dialog)
                        logging.info("已安排显示驱动提示（延迟2秒）")
                    else:
                        logging.info("Interception 驱动未安装或初始化失败（未触发处理提示）")

                except Exception as driver_error:
                    logging.info(f"驱动检查过程中出现异常: {driver_error}")
                    # 不影响程序启动

            except Exception as e:
                logging.warning(f"检查 Interception 驱动时出错: {e}")
                # 不影响程序启动

        # 延迟执行驱动检查，确保主窗口完全显示后再检查
        from PySide6.QtCore import QTimer
        QTimer.singleShot(500, check_and_install_interception_driver)
        logging.info("已安排 Interception 驱动检查（延迟500ms）")
        # --- 驱动检查结束 ---

    except Exception as main_window_error:
        logging.critical(f"创建或显示主窗口时发生严重错误: {main_window_error}", exc_info=True)
        # 显示错误对话框
        try:
            show_critical_box(None, "启动错误", f"程序启动失败:\n{main_window_error}")
        except:
            pass
        sys.exit(1)

    # 【主程序零OCR】不在主程序中初始化OCR服务
    # OCR服务将由多进程OCR池按需创建子进程来处理
    # 这样可以避免主程序加载FastDeploy等OCR库，降低内存占用
    logging.info("启动 主程序不加载OCR，OCR服务将按需创建子进程处理")


    connect_main_window_runtime_bindings(
        task_state_manager=task_state_manager,
        main_window=main_window,
        simple_hotkey_listener=simple_hotkey_listener,
        system_tray=system_tray,
        queued_connection=Qt.QueuedConnection,
    )


    log_maintenance_loop = start_log_maintenance_loop(
        app,
        lambda: app_logging_runtime.LogMaintenanceLoop(cleanup_temp_files_cb=_cleanup_temp_files),
    )

    try:
        exit_code = run_qt_event_loop(
            app=app,
            log_maintenance_loop=log_maintenance_loop,
            plugin_init_thread=plugin_init_thread,
            main_process_memory_watchdog=main_process_memory_watchdog,
            task_state_manager=task_state_manager,
            main_window=main_window,
            system_tray=system_tray,
            cleanup_runtime_state_variables_cb=cleanup_runtime_state_variables,
            trim_main_process_memory_cb=_trim_main_process_memory,
            exit_cleanup_join_timeout_sec=_EXIT_CLEANUP_JOIN_TIMEOUT_SEC,
        )
        logging.info(f"应用程序正常退出，退出代码: {exit_code}")
        _release_single_instance_lock()
        sys.exit(exit_code)
    except Exception:
        _release_single_instance_lock()
        sys.exit(1)










