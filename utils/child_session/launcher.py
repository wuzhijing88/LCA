# -*- coding: utf-8 -*-
"""用任务计划程序把进程以管理员身份送到指定 Child Session。"""

from __future__ import annotations

import os
import uuid

from utils.child_session.native import try_get_child_session_id
from utils.win32com_runtime import prepare_win32com_runtime

TASK_ACTION_EXECUTE = 0
TASK_CREATE = 2
TASK_LOGON_INTERACTIVE_TOKEN = 3
TASK_RUNLEVEL_HIGHEST = 1
TASK_RUN_USE_SESSION_ID = 0x4


def launch_elevated(
    child_session_id: int,
    executable_path: str,
    arguments: str = "",
    working_directory: str = "",
) -> None:
    full_path = os.path.abspath(executable_path)
    if not os.path.isfile(full_path):
        raise FileNotFoundError(f"要启动的程序不存在: {full_path}")
    if not full_path.lower().endswith(".exe"):
        raise ValueError("当前只允许选择 .exe 程序")
    cwd = working_directory or os.path.dirname(full_path)
    _launch_with_temporary_task(int(child_session_id), full_path, str(arguments or ""), cwd)


def _launch_with_temporary_task(
    child_session_id: int,
    executable_path: str,
    arguments: str,
    working_directory: str,
) -> None:
    actual_id = try_get_child_session_id()
    if actual_id != child_session_id:
        current = "无" if actual_id is None else str(actual_id)
        raise RuntimeError(
            f"目标 Child Session 已发生变化。请求会话为 {child_session_id}，当前会话为 {current}。"
        )

    prepare_win32com_runtime()
    import win32api
    import win32con
    import win32com.client

    account_name = win32api.GetUserNameEx(win32con.NameSamCompatible)
    scheduler_type = win32com.client.Dispatch("Schedule.Service")
    scheduler_type.Connect()
    root_folder = scheduler_type.GetFolder("\\")
    task_name = f"LCA-ChildSession-ElevatedLaunch-{uuid.uuid4().hex}"
    task_registered = False

    try:
        task_definition = scheduler_type.NewTask(0)
        task_definition.RegistrationInfo.Author = "LCA"
        task_definition.RegistrationInfo.Description = (
            f"临时启动 {os.path.basename(executable_path)} 到 Child Session {child_session_id}"
        )
        task_definition.Settings.Enabled = True
        task_definition.Settings.Hidden = True
        task_definition.Settings.AllowDemandStart = True
        task_definition.Settings.DisallowStartIfOnBatteries = False
        task_definition.Settings.StopIfGoingOnBatteries = False
        task_definition.Settings.ExecutionTimeLimit = "PT0S"
        task_definition.Principal.UserId = account_name
        task_definition.Principal.LogonType = TASK_LOGON_INTERACTIVE_TOKEN
        task_definition.Principal.RunLevel = TASK_RUNLEVEL_HIGHEST
        action = task_definition.Actions.Create(TASK_ACTION_EXECUTE)
        action.Path = executable_path
        action.Arguments = arguments
        action.WorkingDirectory = working_directory
        registered = root_folder.RegisterTaskDefinition(
            task_name,
            task_definition,
            TASK_CREATE,
            account_name,
            None,
            TASK_LOGON_INTERACTIVE_TOKEN,
            None,
        )
        task_registered = True
        # None 会被任务计划程序当成非法参数（0x80070057）。空字符串才是“不附加参数、沿用会话用户”。
        running = registered.RunEx(
            "",
            TASK_RUN_USE_SESSION_ID,
            int(child_session_id),
            "",
        )
        if running is None:
            raise RuntimeError("任务计划程序没有返回运行实例。")
    finally:
        if task_registered:
            root_folder.DeleteTask(task_name, 0)
