import logging
import os
import threading

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox



def create_application(argv):
    return QApplication(argv)


def install_global_ui_helpers(app):
    from ui.widgets.custom_tooltip import get_tooltip_manager
    tooltip_manager = get_tooltip_manager()
    tooltip_manager.install(app)
    tooltip_manager.set_theme("light")
    return tooltip_manager


def configure_application_icon(app, sys_module, entry_file: str):
    try:
        if getattr(sys_module, "frozen", False):
            if hasattr(sys_module, "_MEIPASS"):
                base_path = sys_module._MEIPASS
            else:
                exe_path = os.path.abspath(sys_module.executable)
                try:
                    exe_path = os.path.realpath(exe_path)
                except Exception:
                    pass
                base_path = os.path.dirname(exe_path)
        else:
            base_path = os.path.dirname(os.path.abspath(entry_file))

        icon_path = os.path.join(base_path, "resources", "icon.ico")
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
            logging.info(f"应用程序图标已设置: {icon_path}")
        else:
            logging.warning(f"图标文件不存在: {icon_path}")
    except Exception as error:
        logging.warning(f"设置应用程序图标失败: {error}")



def configure_application_presentation(app, tooltip_manager, qt_module):
    try:
        if hasattr(qt_module.ApplicationAttribute, "AA_DisableWindowContextHelpButton"):
            app.setAttribute(qt_module.ApplicationAttribute.AA_DisableWindowContextHelpButton, True)
    except AttributeError:
        pass

    from PySide6.QtWidgets import QToolTip
    QToolTip.setFont(app.font())

    from ui.system_parts.message_box_translator import setup_message_box_translations
    setup_message_box_translations()

    try:
        from themes import get_theme_manager
        from utils.app_paths import get_config_path

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
    except Exception as error:
        logging.error(f"主题管理器初始化失败: {error}", exc_info=True)
        app.setStyle("Fusion")


def connect_main_window_runtime_bindings(
    task_state_manager,
    main_window,
    simple_hotkey_listener,
    system_tray,
    queued_connection,
):
    try:
        logging.info("开始连接运行时状态管理链路")
        task_state_manager.task_state_changed.connect(main_window.handle_task_state_change)

        if simple_hotkey_listener:
            simple_hotkey_listener.start_requested.connect(main_window.safe_start_tasks, queued_connection)
            simple_hotkey_listener.stop_requested.connect(main_window.safe_stop_tasks, queued_connection)
        else:
            logging.info("快捷键由 MainWindow 直接管理")

        if system_tray:
            try:
                if system_tray.setup_tray(main_window):
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
                    logging.warning("系统托盘设置失败")
            except Exception as tray_error:
                logging.error(f"设置系统托盘时出错: {tray_error}")

        logging.info("运行时状态管理链路已完成")
    except Exception as error:
        logging.error(f"连接运行时状态管理链路失败: {error}", exc_info=True)


def start_log_maintenance_loop(app, loop_factory):
    log_maintenance_loop = None
    try:
        log_maintenance_loop = loop_factory()
        log_maintenance_loop.start()
        app.log_maintenance_loop = log_maintenance_loop
    except Exception as error:
        logging.warning(f"[日志维护] 启动失败: {error}")
        log_maintenance_loop = None
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
        try:
            from utils.input_simulation import global_input_simulator_manager
            global_input_simulator_manager.clear_cache()
            logging.info("[后台清理] 输入模拟器缓存已清理")
        except Exception as error:
            logging.error(f"[后台清理] 输入模拟器缓存清理失败: {error}")

        try:
            from utils.foreground_input_manager import get_foreground_input_manager
            get_foreground_input_manager().close()
            logging.info("[后台清理] 前台输入驱动已关闭")
        except Exception as error:
            logging.error(f"[后台清理] 前台输入驱动清理失败: {error}")

        try:
            if system_tray:
                logging.info("[后台清理] 清理系统托盘...")
                system_tray.cleanup()
        except Exception as error:
            logging.error(f"[后台清理] 系统托盘清理失败: {error}")

        try:
            from utils.window_handle_manager import get_window_handle_manager
            get_window_handle_manager().stop_monitoring()
            logging.info("[后台清理] 窗口句柄监控已停止")
        except Exception as error:
            logging.error(f"[后台清理] 窗口句柄监控清理失败: {error}")

        try:
            from services.multiprocess_ocr_pool import get_existing_multiprocess_ocr_pool
            logging.info("[后台清理] 强制清理所有 OCR 子进程...")
            pool = get_existing_multiprocess_ocr_pool()
            if pool is not None:
                pool.cleanup_all_processes_force()
                logging.info("[后台清理] OCR 子进程已清理")

            from services.multiprocess_ocr_pool import cleanup_orphan_ocr_subprocesses
            cleaned_count = int(cleanup_orphan_ocr_subprocesses(main_pid=os.getpid()) or 0)
            if cleaned_count > 0:
                logging.info(f"[后台清理] OCR 孤儿子进程已清理: {cleaned_count}")
        except Exception as error:
            logging.error(f"[后台清理] OCR 清理失败: {error}")

        try:
            from utils.screenshot_helper import cleanup_all_screenshot_engines
            cleanup_all_screenshot_engines()
        except Exception as error:
            logging.error(f"[后台清理] 截图子系统清理失败: {error}")

        logging.info("[后台清理] 所有清理工作完成，程序可以安全退出")

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
            logging.warning(f"[运行态变量] 清理失败: {error}")

        try:
            if task_state_manager is not None and main_window is not None:
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

    try:
        logging.info("准备启动 Qt 事件循环...")
        app.aboutToQuit.connect(on_about_to_quit)
        logging.info("Qt 事件循环已启动，程序正在运行...")
        try:
            exit_code = app.exec()
        except KeyboardInterrupt:
            logging.info("Qt 事件循环收到键盘中断，准备退出程序")
            exit_code = 0

        try:
            if exit_cleanup_thread is not None and exit_cleanup_thread.is_alive():
                exit_cleanup_thread.join(timeout=float(exit_cleanup_join_timeout_sec))
        except Exception as error:
            logging.warning(f"[退出清理] 等待后台清理线程失败: {error}")
        return exit_code
    except Exception as error:
        logging.critical(f"Qt 事件循环启动失败: {error}", exc_info=True)
        try:
            from ui.system_parts.message_box_translator import show_critical_box

            show_critical_box(None, "程序错误", f"程序运行时发生严重错误\n{error}")
        except Exception:
            pass
        raise
