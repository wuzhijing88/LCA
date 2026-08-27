import sys
import os     # 用于路径和退出
import atexit
import ctypes
import logging
from utils.dpi_awareness import enable_process_dpi_awareness
from app_core.runtime.worker_entry import (
    StandaloneSubprocessSpec,
    ensure_project_main_runtime,
    get_cli_argument_value,
    get_cli_int_argument_value,
    is_packaged_runtime,
    is_standalone_subprocess_active,
    resolve_main_executable,
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
    process_id = get_cli_argument_value(argv, "--process-id", "").strip()
    port = get_cli_int_argument_value(argv, "--port", 0)
    if not process_id:
        raise ValueError("--process-id is required for OCR worker")
    if port <= 0:
        raise ValueError("--port must be greater than zero for OCR worker")
    return process_id, port


def _build_match_subprocess_args(argv) -> tuple[str, int]:
    process_id = get_cli_argument_value(argv, "--process-id", "").strip()
    port = get_cli_int_argument_value(argv, "--port", 0)
    if not process_id:
        raise ValueError("--process-id is required for match worker")
    if port <= 0:
        raise ValueError("--port must be greater than zero for match worker")
    return process_id, port


def _build_workflow_subprocess_args(argv) -> tuple[int]:
    port = get_cli_int_argument_value(argv, "--port", 0)
    if port <= 0:
        raise ValueError("--port must be greater than zero for workflow worker")
    return (port,)


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
)

_IS_STANDALONE_SUBPROCESS = is_standalone_subprocess_active(
    sys.argv,
    _STANDALONE_SUBPROCESS_SPECS,
)

_standalone_exit_code = run_standalone_subprocess(sys.argv, _STANDALONE_SUBPROCESS_SPECS)
if _standalone_exit_code is not None:
    sys.exit(_standalone_exit_code)

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

    logging.info("[子进程隔离] 已创建 Qt 类占位符，避免加载 PySide6")
else:
    _IS_SUBPROCESS = False

if _IS_SUBPROCESS:
    try:
        from utils.instance_runtime import adopt_instance_slot_from_env

        adopt_instance_slot_from_env()
    except Exception:
        pass
# ============================================================

logger = logging.getLogger(__name__)

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

import time
import subprocess
from traceback import format_exception

# 添加当前目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
    logger.info(f"已添加 {current_dir} 到 Python 路径")

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


from app_core import logging_runtime as app_logging_runtime


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

# --- Admin elevation block --- #
# 自动提权逻辑：确保程序以管理员权限运行
# 兼容性：Windows 7/8/8.1/10/11 及 Server 版本
# <<<< UNCOMMENTED START >>>>
if os.name == 'nt' and not _IS_SUBPROCESS and not is_admin():
    reason_str = "程序需要管理员权限才能确保所有功能正常运行（全局快捷键、窗口操作等）"
    logging.warning("检测到程序未以管理员权限运行，正在尝试自动提权...")
    logging.info(f"  提权原因: {reason_str}")

    # 检测系统信息
    try:
        import platform
        win_version = platform.win32_ver()
        logging.info(f"  Windows版本: {win_version[0]} {win_version[1]} Build {win_version[2]}")
    except Exception:
        logging.info("  无法检测Windows版本信息")

    # 添加安全检查，确保在任何情况下都能正确退出
    elevation_success = False
    elevation_error = None

    try:
        # 打包后必须以当前 exe 提权：Nuitka standalone 的 sys.executable 就是 LCA.exe。
        # 工作目录必须是 exe 所在目录，否则相对路径/依赖 DLL 会找不到。
        if is_packaged_runtime():
            executable_to_run = resolve_main_executable() or os.path.abspath(sys.executable or sys.argv[0])
            if not executable_to_run.lower().endswith(".exe") or not os.path.isfile(executable_to_run):
                candidate = os.path.abspath(sys.argv[0])
                if candidate.lower().endswith(".exe") and os.path.isfile(candidate):
                    executable_to_run = candidate
            working_directory = os.path.dirname(executable_to_run)
            original_args = sys.argv[1:]
            params = subprocess.list2cmdline(original_args) if original_args else ""
            logging.info("  检测到打包环境，使用 exe 文件进行提权重启")
        else:
            executable_to_run = os.path.abspath(sys.executable)
            working_directory = os.path.dirname(os.path.abspath(__file__))
            script_path = os.path.abspath(__file__)
            original_args = sys.argv[1:]
            params = subprocess.list2cmdline([script_path] + original_args)
            logging.info("  检测到开发环境（Python），使用python.exe进行提权重启")

        logging.info(f"  可执行文件: {executable_to_run}")
        logging.info(f"  工作目录: {working_directory}")
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
            working_directory,  # lpDirectory
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
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                "无法自动获取管理员权限。\n请右键 LCA.exe，选择「以管理员身份运行」。",
                "LCA",
                0x00000010,  # MB_ICONERROR
            )
        except Exception:
            pass
    logging.info("=" * 80)

    try:
        sys.exit(0 if elevation_success else 1)
    finally:
        # 确保在任何情况下都能彻底退出（强制退出）
        os._exit(0 if elevation_success else 1)

elif os.name == 'nt' and not _IS_SUBPROCESS:
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

elif os.name != 'nt':
    # 非Windows系统
    logging.info("检测到非Windows系统，跳过管理员权限检查")
# <<<< UNCOMMENTED END >>>>

_EXIT_CLEANUP_JOIN_TIMEOUT_SEC = 2.0


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
    """保留统一清理回调接口。"""
    return None

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
            from utils.input.foreground_input_manager import get_foreground_input_manager
            fg_manager = get_foreground_input_manager()
            fg_manager.close()
            logging.info("前台输入驱动已清理")
        except Exception as e:
            logging.debug(f"清理前台输入驱动时出错: {e}")

        # 清理OCR服务池
        try:
            from services.multiprocess_ocr_pool import get_existing_multiprocess_ocr_pool
            pool = get_existing_multiprocess_ocr_pool()
            if pool is not None:
                pool.shutdown()
                logging.info("OCR服务池已清理")
        except Exception as e:
            logging.debug(f"清理OCR服务池时出错: {e}")

        # 清理当前主进程仍登记的所有 worker。
        try:
            from services.worker_process_cleanup import cleanup_all_registered_worker_processes
            cleaned_count = int(cleanup_all_registered_worker_processes() or 0)
            if cleaned_count > 0:
                logging.info(f"登记子进程已清理: {cleaned_count}")
        except Exception as e:
            logging.error(f"登记子进程清理失败: {e}")

        # 主进程不加载OCR引擎模块，OCR资源只由OCR子进程管理

        # 清理YOLO引擎
        if cleanup_yolo_runtime_resources(release_process=True, compact_memory=True):
            logging.info("YOLO运行时资源已清理")

        # 清理模板预加载缓存
        try:
            from utils.match.template_preloader import clear_global_cache
            clear_global_cache()
            logging.info("模板预加载缓存已清理")
        except Exception as e:
            logging.debug(f"清理模板预加载缓存时出错: {e}")

        # 清理模板匹配缓存
        try:
            from utils.match.template_matching import get_matcher
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
            from utils.capture.screenshot_helper import clear_screenshot_cache
            clear_screenshot_cache()
            logging.info("截图缓存已清理")
        except Exception as e:
            logging.debug(f"清理截图缓存时出错: {e}")

        # 清理截图引擎资源
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

from app_core.runtime.lifecycle import get_runtime_lifecycle

_runtime_lifecycle = get_runtime_lifecycle()
_runtime_lifecycle.register(
    "global-runtime-resources",
    cleanup_all_resources,
    priority=100,
    once=True,
)
atexit.register(lambda: _runtime_lifecycle.teardown(final=True))

# --- Configuration Loading ---
if not _IS_SUBPROCESS:
    try:
        from utils.instance_runtime import claim_instance_slot, release_instance_slot

        _instance_slot = claim_instance_slot()
        atexit.register(release_instance_slot)
        if _instance_slot > 1:
            app_logging_runtime.setup_logging_and_cleanup(cleanup_temp_files_cb=_cleanup_temp_files)
            from utils.app_paths import get_config_path as _get_instance_config_path

            logging.info(
                "多开实例已隔离: slot=%s config=%s",
                _instance_slot,
                _get_instance_config_path(),
            )
    except Exception as instance_claim_error:
        logging.warning("领取多开实例槽位失败，将继续使用主实例路径: %s", instance_claim_error)

from app_core.config_store import load_config, save_config

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
    from app_core.runtime.task_state_manager import TaskStateManager


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
            self.tray_icon.setToolTip(self._tray_tooltip())

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
                from utils.instance_runtime import create_app_settings

                settings = create_app_settings()
                settings.setValue("close_behavior", "ask")
                settings.setValue("close_behavior_remember", False)
            except Exception:
                pass
            if self.tray_icon:
                self.tray_icon.showMessage("设置已重置", "已清除关闭记住选择", QSystemTrayIcon.MessageIcon.Information, 2000)
        except Exception as exc:
            logging.error(f"清除关闭记住选择失败: {exc}")

    def _tray_app_name(self):
        try:
            from utils.instance_runtime import get_instance_display_name

            return get_instance_display_name("工作流自动化工具")
        except Exception:
            return "工作流自动化工具"

    def _tray_tooltip(self, status=None):
        if status:
            return f"{self._tray_app_name()}\n状态: {status}\n右键查看菜单"
        return f"{self._tray_app_name()}\n右键查看菜单"

    def update_tooltip(self, status):
        """更新托盘提示文本"""
        if self.tray_icon:
            self.tray_icon.setToolTip(self._tray_tooltip(status))

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
        except Exception:
            pass

        logging.info("紧急清理完成")

    except Exception as e:
        logging.error(f"紧急清理失败: {e}")
# --- END ADDED ---

if __name__ == "__main__" and not _IS_SUBPROCESS:
    # --- ADDED: Set the global exception hook at the very beginning ---
    sys.excepthook = global_exception_handler
    # -----------------------------------------------------------------

    logging.info("准备启动主程序...")

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
        install_global_ui_helpers,
        run_qt_event_loop,
        start_log_maintenance_loop,
    )

    app = create_application(sys.argv)

    tooltip_manager = install_global_ui_helpers(app)

    configure_application_icon(app)
    configure_application_presentation(app, tooltip_manager)


    # --- ADDED: Initialize State Management System ---
    logging.info("初始化任务状态管理系统...")
    task_state_manager = TaskStateManager()

    # 将task_state_manager设置为app的属性，使其全局可访问
    app.task_state_manager = task_state_manager
    logging.info("任务状态管理器已设置为全局可访问")

    # SimpleHotkeyListener 已被 MainWindow 的统一快捷键系统替代
    # MainWindow._update_hotkeys() 现在负责所有快捷键的注册和管理
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

    logging.info("本地离线模式已启用")

    logging.info("启动主程序...")

    # 工具 修复：添加主窗口创建的详细调试信息
    try:
        logging.info("开始创建主窗口...")

        # Create and show the main window with enhanced state management
        from utils.app_paths import get_images_dir

        main_window = MainWindow(
            task_modules=get_task_modules(),
            initial_config=config,
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

                    try:
                        from PySide6.QtWidgets import QMenu
                        from ui.system_parts.menu_style import polish_standard_edit_menu

                        if isinstance(obj, QMenu):
                            polish_standard_edit_menu(obj, frameless=False)
                            return False
                    except Exception:
                        pass

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
                        try:
                            from themes import get_theme_manager

                            get_theme_manager().apply_combo_popup_theme(popup, combo.view())
                        except Exception:
                            from themes.rounded_popup import COMBO_RADIUS, apply_rounded_popup

                            apply_rounded_popup(
                                popup,
                                radius=COMBO_RADIUS,
                                border_key="combo_popup_border",
                                frameless=True,
                                force_window=True,
                            )
                        if not popup.isVisible():
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
                            view.setAutoFillBackground(False)
                            if view.viewport():
                                view.viewport().setAutoFillBackground(False)
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

        # 启动后统一检查当前配置涉及的本地输入驱动。
        def check_input_driver_requirements():
            """检查罗技版本约束和 Interception 驱动状态。"""
            try:
                from PySide6.QtCore import QTimer
                from utils.input_simulation.mode_utils import (
                    parse_foreground_backends,
                    requires_interception_driver,
                )
                from utils.input.interception_installation_prompt import (
                    request_interception_installation,
                )
                from utils.input.logitech_runtime import (
                    detect_logitech_runtime,
                    is_logitech_ibinputsimulator_configured,
                )

                config = getattr(main_window, "config", {}) or {}
                execution_mode = str(config.get("execution_mode", "") or "").strip().lower()
                mouse_backend, keyboard_backend = parse_foreground_backends(config)

                if is_logitech_ibinputsimulator_configured(config):
                    logging.info("开始检查 Logitech 输入运行时...")
                    version_result = detect_logitech_runtime()
                    if version_result.compatible:
                        logging.info(
                            "罗技输入运行时检查通过: "
                            f"type={version_result.send_type}, "
                            f"version={version_result.detected_version}, "
                            f"source={version_result.source}"
                        )
                    else:
                        logging.warning(version_result.user_message().replace("\n", " "))

                        def show_logitech_version_dialog():
                            try:
                                from PySide6.QtWidgets import QMessageBox

                                msg_box = QMessageBox(main_window)
                                msg_box.setIcon(QMessageBox.Icon.Warning)
                                msg_box.setWindowTitle("罗技输入驱动不可用")
                                msg_box.setText(version_result.user_message())
                                msg_box.setInformativeText(
                                    "请安装指定版本后重启电脑和 LCA。\n"
                                    "指定版本：Logitech G HUB 2026.4，"
                                    "或 Logitech Gaming Software 9.02.65（二选一）。"
                                )
                                msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
                                msg_box.exec()
                            except Exception as dialog_error:
                                logging.error(f"显示罗技驱动版本提示失败: {dialog_error}")

                        QTimer.singleShot(200, show_logitech_version_dialog)

                logging.info("开始检查 Interception 驱动状态...")

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

                # 未安装时只询问，不得在初始化链路中自动安装。
                try:
                    from utils.input.interception_driver import get_driver
                    driver = get_driver()

                    if not driver.is_driver_registered():
                        logging.info("Interception 驱动未安装，等待用户确认是否安装")
                        QTimer.singleShot(
                            1000,
                            lambda: request_interception_installation(main_window, config),
                        )
                        return

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
        QTimer.singleShot(500, check_input_driver_requirements)
        logging.info("已安排输入驱动检查（延迟500ms）")
        # --- 驱动检查结束 ---

    except Exception as main_window_error:
        logging.critical(f"创建或显示主窗口时发生严重错误: {main_window_error}", exc_info=True)
        # 显示错误对话框
        try:
            show_critical_box(None, "启动错误", f"程序启动失败:\n{main_window_error}")
        except Exception:
            pass
        sys.exit(1)

    # 【主程序零OCR】不在主程序中初始化OCR服务
    # OCR服务将由多进程OCR池按需创建子进程来处理
    # 这样可以避免主程序加载 RapidOCR 和 ONNX Runtime，降低内存占用
    logging.info("启动 主程序不加载OCR，OCR服务将按需创建子进程处理")


    connect_main_window_runtime_bindings(
        task_state_manager=task_state_manager,
        main_window=main_window,
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
            task_state_manager=task_state_manager,
            main_window=main_window,
            system_tray=system_tray,
            cleanup_runtime_state_variables_cb=cleanup_runtime_state_variables,
            exit_cleanup_join_timeout_sec=_EXIT_CLEANUP_JOIN_TIMEOUT_SEC,
        )
        logging.info(f"应用程序正常退出，退出代码: {exit_code}")
        sys.exit(exit_code)
    except Exception as event_loop_error:
        logging.critical(
            f"启动 Qt 事件循环前发生错误: {event_loop_error}",
            exc_info=True,
        )
        sys.exit(1)










