"""管理员权限检查与自动提权（Windows）。

程序依赖全局快捷键、窗口操作与输入驱动，必须以管理员身份运行；
未提权时通过 ShellExecuteW("runas") 重启自身，并退出当前进程以避免双实例。
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import time

from app_core.runtime.worker_entry import is_packaged_runtime, resolve_main_executable

_SHELL_EXECUTE_ERROR_MESSAGES = {
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
    32: "DLL未找到",
}


def is_admin() -> bool:
    """检查当前进程是否具有管理员权限。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except AttributeError:
        logging.warning("IsUserAnAdmin API 不可用，假设无管理员权限")
        return False
    except Exception as e:
        logging.error(f"检查管理员权限时发生异常: {e}")
        return False


def _resolve_relaunch_target(entry_file: str) -> tuple[str, str, str]:
    """返回 (可执行文件, 参数串, 工作目录)。打包后以自身 exe 提权，开发态以 python.exe + 脚本提权。"""
    original_args = sys.argv[1:]
    if is_packaged_runtime():
        executable_to_run = resolve_main_executable() or os.path.abspath(sys.executable or sys.argv[0])
        if not executable_to_run.lower().endswith(".exe") or not os.path.isfile(executable_to_run):
            candidate = os.path.abspath(sys.argv[0])
            if candidate.lower().endswith(".exe") and os.path.isfile(candidate):
                executable_to_run = candidate
        working_directory = os.path.dirname(executable_to_run)
        params = subprocess.list2cmdline(original_args) if original_args else ""
        logging.info("  检测到打包环境，使用 exe 文件进行提权重启")
    else:
        executable_to_run = os.path.abspath(sys.executable)
        working_directory = os.path.dirname(os.path.abspath(entry_file))
        params = subprocess.list2cmdline([os.path.abspath(entry_file)] + original_args)
        logging.info("  检测到开发环境（Python），使用python.exe进行提权重启")
    return executable_to_run, params, working_directory


def _request_elevation(entry_file: str) -> tuple[bool, str | None]:
    """发起 UAC 提权请求。返回 (是否成功发出, 失败原因)。"""
    try:
        executable_to_run, params, working_directory = _resolve_relaunch_target(entry_file)
        logging.info(f"  可执行文件: {executable_to_run}")
        logging.info(f"  工作目录: {working_directory}")
        logging.info(f"  启动参数: {params if params else '(无)'}")

        # ShellExecuteW 返回值 > 32 表示成功，0-32 为错误码
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable_to_run,
            params,
            working_directory,
            1,  # SW_SHOWNORMAL
        )
        if result > 32:
            logging.info(f"提权请求已成功发送（返回值: {result}）")
            logging.info("  UAC对话框应已显示，等待用户确认...")
            time.sleep(1)
            return True, None

        error_msg = _SHELL_EXECUTE_ERROR_MESSAGES.get(result, f"未知错误码 {result}")
        elevation_error = f"ShellExecuteW失败: {error_msg} (返回值: {result})"
        logging.error(f"提权请求失败: {elevation_error}")
        if result == 5:
            logging.warning("  可能原因：用户取消了UAC提权对话框，或UAC被管理员策略禁用")
        return False, elevation_error
    except AttributeError as e:
        elevation_error = f"ShellExecuteW API不可用: {e}"
        logging.error(f"提权失败: {elevation_error}")
        logging.error("  当前Windows版本可能不支持此API")
        return False, elevation_error
    except Exception as e:
        elevation_error = f"未知异常: {e}"
        logging.error(f"请求管理员权限时发生异常: {elevation_error}", exc_info=True)
        logging.error("  建议：请尝试手动右键 -> 以管理员身份运行此程序")
        return False, elevation_error


def ensure_admin_privileges_or_exit(entry_file: str) -> None:
    """非管理员时尝试提权并退出当前进程；已是管理员则仅记录日志。非 Windows 直接放行。"""
    if os.name != "nt":
        logging.info("检测到非Windows系统，跳过管理员权限检查")
        return

    if is_admin():
        logging.info("=" * 80)
        logging.info("程序已以管理员权限运行")
        logging.info("  全局快捷键和窗口操作功能可正常使用")
        logging.info("=" * 80)
        return

    logging.warning("检测到程序未以管理员权限运行，正在尝试自动提权...")
    logging.info("  提权原因: 程序需要管理员权限才能确保所有功能正常运行（全局快捷键、窗口操作等）")
    try:
        import platform

        win_version = platform.win32_ver()
        logging.info(f"  Windows版本: {win_version[0]} {win_version[1]} Build {win_version[2]}")
    except Exception:
        logging.info("  无法检测Windows版本信息")

    elevation_success, elevation_error = _request_elevation(entry_file)

    # 无论提权是否成功都必须退出：成功时新进程已启动，留下当前进程会形成双实例。
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
        os._exit(0 if elevation_success else 1)
