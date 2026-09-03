import logging
import os
import threading

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QToolTip

from app_core.runtime.lifecycle import get_runtime_lifecycle
from utils.app_paths import get_config_path, get_resource_path


def create_application(argv):
    return QApplication(argv)


def install_global_ui_helpers(app):
    from ui.system_parts.menu_style import install_edit_menu_fixer
    from ui.widgets.custom_tooltip import get_tooltip_manager

    tooltip_manager = get_tooltip_manager()
    tooltip_manager.install(app)
    install_edit_menu_fixer(app)
    return tooltip_manager


def configure_application_icon(app):
    icon_path = get_resource_path("icon.ico")
    if not os.path.isfile(icon_path):
        logging.error(f"图标文件不存在: {icon_path}")
        return
    app.setWindowIcon(QIcon(icon_path))
    logging.info(f"应用程序图标已设置: {icon_path}")


def configure_application_presentation(app, tooltip_manager):
    QToolTip.setFont(app.font())

    from ui.system_parts.message_box_translator import setup_message_box_translations

    setup_message_box_translations()

    from themes import get_theme_manager

    config_path = get_config_path()
    theme_manager = get_theme_manager(config_path=config_path)
    theme_manager.apply_theme(app, "auto")
    tooltip_manager.set_theme(theme_manager.get_current_theme())
    theme_manager.register_theme_change_callback(tooltip_manager.set_theme)

    logging.info("主题管理器已初始化")
    logging.info(
        f"主题模式: {theme_manager.get_theme_mode()} ({theme_manager.THEMES[theme_manager.get_theme_mode()]})"
    )
    logging.info(f"实际主题: {theme_manager.get_current_theme()}")
    logging.info(f"深色模式: {'是' if theme_manager.is_dark_mode() else '否'}")


def connect_main_window_runtime_bindings(
    task_state_manager,
    main_window,
    system_tray,
    queued_connection,
):
    logging.info("开始连接运行时状态管理链路")
    task_state_manager.task_state_changed.connect(main_window.handle_task_state_change)

    if system_tray is None:
        logging.info("未创建系统托盘，跳过托盘接线")
    elif system_tray.setup_tray(main_window):
        main_window.system_tray_manager = system_tray
        system_tray.start_requested.connect(main_window.safe_start_tasks, queued_connection)
        system_tray.stop_requested.connect(main_window.safe_stop_tasks, queued_connection)
        system_tray.show_window_requested.connect(main_window.restore_main_window, queued_connection)

        def update_tray_tooltip(state):
            system_tray.update_tooltip(state)

        task_state_manager.task_state_changed.connect(update_tray_tooltip, queued_connection)
        system_tray.attach_task_state_binding(
            task_state_manager.task_state_changed,
            update_tray_tooltip,
        )
        logging.info("系统托盘已设置并完成信号接线")
    else:
        logging.error("系统托盘设置失败")

    logging.info("运行时状态管理链路已完成")


def schedule_startup_background_prewarms():
    try:
        from utils.plugin.runtime import schedule_plugin_host_prewarm

        schedule_plugin_host_prewarm()
    except Exception:
        logging.debug("后台预热插件宿主失败", exc_info=True)
    try:
        from services.ocr_pool_policy import schedule_ocr_pool_prewarm

        schedule_ocr_pool_prewarm()
    except Exception:
        logging.debug("后台预热 OCR 子进程失败", exc_info=True)
    try:
        from task_workflow.workflow_worker_pool import schedule_workflow_worker_prewarm

        schedule_workflow_worker_prewarm()
    except Exception:
        logging.debug("后台预热工作流子进程失败", exc_info=True)


def start_log_maintenance_loop(app, loop_factory):
    log_maintenance_loop = loop_factory()
    log_maintenance_loop.start()
    app.log_maintenance_loop = log_maintenance_loop
    threading.Thread(
        target=schedule_startup_background_prewarms,
        daemon=True,
        name="StartupPrewarmSchedule",
    ).start()
    return log_maintenance_loop


def run_qt_event_loop(
    app,
    log_maintenance_loop,
    task_state_manager,
    main_window,
    system_tray,
    cleanup_runtime_state_variables_cb,
    exit_cleanup_join_timeout_sec: float,
):
    exit_cleanup_thread = None

    def cleanup_background():
        if system_tray is not None:
            try:
                logging.info("[后台清理] 清理系统托盘...")
                system_tray.cleanup()
            except Exception as error:
                logging.error(f"[后台清理] 系统托盘清理失败: {error}")

        try:
            from utils.window.window_handle_manager import get_window_handle_manager

            get_window_handle_manager().stop_monitoring()
            logging.info("[后台清理] 窗口句柄监控已停止")
        except Exception as error:
            logging.error(f"[后台清理] 窗口句柄监控清理失败: {error}")

        logging.info("[后台清理] UI 资源清理完成，其他全局资源交由统一退出流程处理")

    def on_about_to_quit():
        nonlocal exit_cleanup_thread
        if getattr(app, "_exit_cleanup_started", False):
            return
        app._exit_cleanup_started = True
        logging.info("应用程序正常退出，UI 已关闭，开始后台清理")

        try:
            if log_maintenance_loop is not None:
                log_maintenance_loop.stop(timeout=1.0)
        except Exception as error:
            logging.warning(f"[日志维护] 停止失败: {error}")

        try:
            if task_state_manager is not None:
                task_state_manager.shutdown(timeout=2.5)
        except Exception as error:
            logging.warning(f"[任务状态管理] 停止后台清理线程失败: {error}")

        try:
            cleanup_runtime_state_variables_cb()
        except Exception as error:
            logging.warning(f"[运行态] 清理失败: {error}")

        try:
            from utils.plugin.runtime import terminate_plugin_host

            terminate_plugin_host()
        except Exception as error:
            logging.debug("退出时关闭插件宿主失败: %s", error)

        try:
            from task_workflow.workflow_worker_pool import shutdown_warm_workflow_workers

            shutdown_warm_workflow_workers()
        except Exception as error:
            logging.debug("退出时关闭预热工作流子进程失败: %s", error)

        teardown_results = get_runtime_lifecycle().teardown(final=True)
        failed_teardowns = [result for result in teardown_results if not result.ok]
        if failed_teardowns:
            logging.warning(
                "[退出清理] 生命周期步骤失败: %s",
                ", ".join(result.name for result in failed_teardowns),
            )

        if task_state_manager is not None and main_window is not None:
            try:
                task_state_manager.task_state_changed.disconnect(main_window.handle_task_state_change)
            except (TypeError, RuntimeError):
                pass

        exit_cleanup_thread = threading.Thread(
            target=cleanup_background,
            daemon=True,
            name="ExitCleanup",
        )
        exit_cleanup_thread.start()
        logging.info("[退出清理] 后台清理线程已启动，UI 即将关闭")

    logging.info("准备启动 Qt 事件循环...")
    app.aboutToQuit.connect(on_about_to_quit)
    logging.info("Qt 事件循环已启动，程序正在运行...")
    try:
        exit_code = app.exec()
    except KeyboardInterrupt:
        logging.info("Qt 事件循环收到键盘中断，准备退出程序")
        exit_code = 0

    if exit_cleanup_thread is not None and exit_cleanup_thread.is_alive():
        exit_cleanup_thread.join(timeout=float(exit_cleanup_join_timeout_sec))
    return exit_code
