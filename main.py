"""LCA 主入口。

本文件只负责“按正确顺序把各个运行时组件接起来”：
1. 进程环境（线程数、DPI、Qt 日志规则）
2. 独立 worker 子进程分流（OCR / 匹配 / 工作流），在加载任何 GUI 依赖之前完成
3. 播放器隔离、multiprocessing 子进程识别
4. 日志、管理员提权、全局资源清理注册、多开实例槽位、配置加载
5. 主进程：QApplication、托盘、主窗口 / 播放器、事件循环

具体实现分别位于 app_core.runtime.* 与 ui.system_parts.*。
"""

import logging
import os
import sys

from utils.dpi_awareness import enable_process_dpi_awareness
from app_core.runtime.process_env import set_numeric_thread_env_defaults, suppress_qt_platform_warnings
from app_core.runtime.worker_entry import (
    ensure_project_main_runtime,
    is_packaged_runtime,
    is_standalone_subprocess_active,
    run_standalone_subprocess,
)
from app_core.runtime.standalone_workers import STANDALONE_SUBPROCESS_SPECS

# 避免运行入口脚本后再次 `import main` 时触发二次执行
if __name__ == "__main__":
    sys.modules.setdefault("main", sys.modules[__name__])

set_numeric_thread_env_defaults()
enable_process_dpi_awareness()
suppress_qt_platform_warnings()

# 统一打包环境识别：支持改名后的发布版可执行文件（不再依赖 main.exe 固定名称）
if not getattr(sys, "frozen", False) and is_packaged_runtime():
    sys.frozen = True  # 手动补齐标记，兼容依赖 sys.frozen 的路径分支

# --- 独立 worker 子进程分流（必须先于任何 GUI 导入） ---
_IS_STANDALONE_SUBPROCESS = is_standalone_subprocess_active(sys.argv, STANDALONE_SUBPROCESS_SPECS)
_standalone_exit_code = run_standalone_subprocess(sys.argv, STANDALONE_SUBPROCESS_SPECS)
if _standalone_exit_code is not None:
    sys.exit(_standalone_exit_code)

# --- 独立播放器隔离 ---
_PLAYER_PACKAGE_DIR = None
_PLAYER_STARTUP_ERROR = None
try:
    from app_core.player.loader import apply_player_isolation

    _PLAYER_PACKAGE_DIR = apply_player_isolation(sys.argv)
except Exception as player_isolation_error:
    from app_core.player.loader import is_player_mode_requested, is_worker_argv

    if not is_worker_argv(sys.argv):
        try:
            requested = is_player_mode_requested(sys.argv)
        except Exception:
            requested = True
        if requested:
            _PLAYER_STARTUP_ERROR = player_isolation_error

import multiprocessing as _mp

_mp.freeze_support()  # 支持打包后的 exe

# multiprocessing 子进程会重新导入本模块：只做最小初始化，跳过全部主程序逻辑
_IS_SUBPROCESS = _IS_STANDALONE_SUBPROCESS or _mp.current_process().name != "MainProcess"
if _IS_SUBPROCESS:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - [pid=%(process)d] - [%(module)s:%(lineno)d] - %(message)s",
    )
    if not _IS_STANDALONE_SUBPROCESS:  # 避免与独立入口重复日志
        logging.info(f"[子进程隔离] {_mp.current_process().name} 检测到，跳过 main.py 主程序代码")
    try:
        from utils.instance_runtime import adopt_instance_slot_from_env

        adopt_instance_slot_from_env()
    except Exception:
        pass

logger = logging.getLogger(__name__)

# 确保使用 venv 中的依赖
ensure_project_main_runtime(
    entry_file=__file__,
    argv=sys.argv[1:],
    logger=logger,
    runtime_label="主进程",
)

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
    logger.info(f"已添加 {current_dir} 到 Python 路径")

from app_core import logging_runtime as app_logging_runtime
from app_core.runtime.resource_cleanup import (
    cleanup_runtime_state_variables,
    cleanup_temp_files,
    register_global_resource_cleanup,
)

app_logging_runtime.setup_logging_and_cleanup(cleanup_temp_files_cb=cleanup_temp_files)

# 管理员提权：未提权时会重启自身并退出当前进程（兼容 Windows 7/8/8.1/10/11 及 Server）
if not _IS_SUBPROCESS:
    from app_core.runtime.admin_elevation import ensure_admin_privileges_or_exit, is_admin

    ensure_admin_privileges_or_exit(__file__)

_EXIT_CLEANUP_JOIN_TIMEOUT_SEC = 2.0

register_global_resource_cleanup()

# --- 多开实例槽位与配置加载 ---
if not _IS_SUBPROCESS:
    try:
        from utils.instance_runtime import claim_instance_slot, release_instance_slot
        import atexit

        _instance_slot = claim_instance_slot()
        atexit.register(release_instance_slot)
        if _instance_slot > 1:
            app_logging_runtime.setup_logging_and_cleanup(cleanup_temp_files_cb=cleanup_temp_files)
            from utils.app_paths import get_config_path as _get_instance_config_path

            logging.info(
                "多开实例已隔离: slot=%s config=%s",
                _instance_slot,
                _get_instance_config_path(),
            )
    except Exception as instance_claim_error:
        logging.warning("领取多开实例槽位失败，将继续使用主实例路径: %s", instance_claim_error)

from app_core.config_store import load_config, save_config

# 旧版（程序目录内）用户数据只需要在主进程启动时检查一次；已迁移过则静默跳过
if not _IS_SUBPROCESS:
    try:
        from app_core.user_data_migration import migrate_default_user_data

        _migration = migrate_default_user_data()
        if _migration.performed and _migration.copied:
            logging.info("已迁移旧版用户数据: %s", ", ".join(_migration.copied))
    except Exception as migration_error:
        logging.warning("用户数据迁移失败，继续使用当前用户目录: %s", migration_error)

config = load_config()

# 子进程不需要加载 GUI 库
if not _IS_SUBPROCESS:
    from PySide6.QtCore import Qt
    from ui.system_parts.message_box_translator import show_critical_box
    from ui.main_window_parts.main_window import MainWindow
    from tasks import get_task_modules
    from app_core.runtime.task_state_manager import TaskStateManager

try:
    APP_ROOT = os.path.abspath(os.path.dirname(sys.argv[0]))
except NameError:
    APP_ROOT = os.path.abspath(os.path.dirname(__file__))

logging.info(f"应用程序根目录: {APP_ROOT}")


def _configure_resolution_adapter() -> None:
    """设置通用分辨率适配器的配置文件路径（用于支持动态参考分辨率）。"""
    try:
        from utils.universal_resolution_adapter import get_universal_adapter
        from utils.app_paths import get_config_path

        config_path = get_config_path()
        get_universal_adapter().set_main_config_path(config_path)
        logging.info(f"已设置通用分辨率适配器配置文件路径: {config_path}")
    except Exception as adapter_error:
        logging.warning(f"设置通用分辨率适配器配置路径失败: {adapter_error}")


def _run_player(app, tooltip_manager, system_tray, task_state_manager) -> int:
    from ui.player.player_app import run_player

    return run_player(
        app=app,
        package_dir=_PLAYER_PACKAGE_DIR,
        config=config,
        tooltip_manager=tooltip_manager,
        system_tray=system_tray,
        task_state_manager=task_state_manager,
        log_maintenance_loop_factory=lambda: app_logging_runtime.LogMaintenanceLoop(
            cleanup_temp_files_cb=cleanup_temp_files
        ),
        cleanup_runtime_state_variables_cb=cleanup_runtime_state_variables,
        exit_cleanup_join_timeout_sec=_EXIT_CLEANUP_JOIN_TIMEOUT_SEC,
    )


def _abort_if_player_only_executable() -> None:
    """exe 内嵌播放器入口印记：即使没有 package，也绝不能落到原版编辑器。"""
    try:
        from app_core.player.loader import is_player_only_executable

        if not is_player_only_executable():
            return
    except Exception:
        return
    msg = (
        "独立播放器未加载到程序包（package.lcap），已阻止启动编辑器。\n"
        "本程序为播放器身份；请完整重装独立程序后再试。"
    )
    logging.critical(msg)
    try:
        show_critical_box(None, "独立程序启动失败", msg)
    except Exception:
        pass
    sys.exit(1)


def _create_main_window(app, task_state_manager):
    from utils.app_paths import get_images_dir
    from ui.system_parts.combo_popup_fixer import install_combo_popup_fixer
    from ui.system_parts.input_driver_check import schedule_input_driver_check

    logging.info("开始创建主窗口...")
    main_window = MainWindow(
        task_modules=get_task_modules(),
        initial_config=config,
        save_config_func=save_config,
        images_dir=get_images_dir("LCA"),
        task_state_manager=task_state_manager,
    )
    logging.info("主窗口创建成功，准备显示...")
    main_window.show()
    logging.info("主窗口显示成功")

    _configure_resolution_adapter()
    install_combo_popup_fixer(app)
    schedule_input_driver_check(main_window, delay_ms=500)
    return main_window


if __name__ == "__main__" and not _IS_SUBPROCESS:
    from app_core.runtime.exception_hook import install_global_exception_hook

    install_global_exception_hook()

    logging.info("准备启动主程序...")

    if os.name == "nt" and not is_admin():
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
    from ui.system_parts.system_tray import SystemTrayManager

    app = create_application(sys.argv)

    tooltip_manager = install_global_ui_helpers(app)
    configure_application_icon(app)
    configure_application_presentation(app, tooltip_manager)

    logging.info("初始化任务状态管理系统...")
    task_state_manager = TaskStateManager()
    app.task_state_manager = task_state_manager  # 全局可访问
    logging.info("任务状态管理器已设置为全局可访问")

    # 快捷键由 MainWindow 统一管理；系统托盘作为备用控制方式
    logging.info(" 快捷键系统将由 MainWindow 统一管理")
    try:
        system_tray = SystemTrayManager()
        logging.info(" 系统托盘管理器已创建，将在主窗口创建后设置")
    except Exception as e:
        logging.warning(f"创建系统托盘管理器失败: {e}")
        system_tray = None

    logging.info(f" 管理员权限状态: {' 已获得' if is_admin() else ' 未获得'}")
    logging.info("本地离线模式已启用")

    if _PLAYER_STARTUP_ERROR is not None:
        logging.critical("独立程序启动失败: %s", _PLAYER_STARTUP_ERROR, exc_info=_PLAYER_STARTUP_ERROR)
        try:
            show_critical_box(None, "独立程序启动失败", str(_PLAYER_STARTUP_ERROR))
        except Exception:
            pass
        sys.exit(1)

    if _PLAYER_PACKAGE_DIR is not None:
        logging.info("以独立程序播放器模式启动: %s", _PLAYER_PACKAGE_DIR)
        try:
            sys.exit(_run_player(app, tooltip_manager, system_tray, task_state_manager))
        except SystemExit:
            raise
        except Exception as player_error:
            logging.critical("独立程序运行失败: %s", player_error, exc_info=True)
            try:
                show_critical_box(None, "独立程序启动失败", str(player_error))
            except Exception:
                pass
            sys.exit(1)

    _abort_if_player_only_executable()

    logging.info("启动主程序...")
    try:
        main_window = _create_main_window(app, task_state_manager)
    except Exception as main_window_error:
        logging.critical(f"创建或显示主窗口时发生严重错误: {main_window_error}", exc_info=True)
        try:
            show_critical_box(None, "启动错误", f"程序启动失败:\n{main_window_error}")
        except Exception:
            pass
        sys.exit(1)

    # 主程序零 OCR：OCR 引擎只在按需创建的子进程中加载，避免主进程引入 RapidOCR / ONNX Runtime
    logging.info("启动 主程序不加载OCR，OCR服务将按需创建子进程处理")

    connect_main_window_runtime_bindings(
        task_state_manager=task_state_manager,
        main_window=main_window,
        system_tray=system_tray,
        queued_connection=Qt.QueuedConnection,
    )

    log_maintenance_loop = start_log_maintenance_loop(
        app,
        lambda: app_logging_runtime.LogMaintenanceLoop(cleanup_temp_files_cb=cleanup_temp_files),
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
