#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工作流任务管理器
负责管理多个工作流任务的创建、执行、删除等操作
"""

import logging
from functools import partial
from typing import Dict, List, Optional, Any, Tuple
from PySide6.QtCore import QObject, Signal

from task_workflow.workflow_task import WorkflowTask
from task_workflow.workspace import get_effective_workflow_images_dir

logger = logging.getLogger(__name__)


class WorkflowTaskManager(QObject):
    """工作流任务管理器"""

    # 信号定义
    task_added = Signal(int)  # task_id
    task_removed = Signal(int)  # task_id
    task_status_changed = Signal(int, str)  # task_id, status
    all_tasks_completed = Signal(bool, str)  # success, result_type(completed/failed/stopped)

    def __init__(self, task_modules: Dict[str, Any], images_dir: str, config: dict, parent=None):
        """
        初始化任务管理器

        Args:
            task_modules: 任务模块字典
            images_dir: 图片目录
            config: 全局配置
            parent: 父对象
        """
        super().__init__(parent)

        self.task_modules = task_modules
        self.images_dir = images_dir
        self.config = config

        self.tasks: Dict[int, WorkflowTask] = {}  # {task_id: WorkflowTask}
        self.next_task_id = 1
        self._last_execute_error_message = ""

        # 当前执行状态
        self._is_executing = False
        self._executing_task_ids: List[int] = []

        # 跳转配置
        self.jump_enabled = True  # 全局跳转开关
        self._current_jump_depth = 0  # 当前跳转深度
        # 移除跳转次数限制，允许无限循环，用户可以通过停止按钮停止

        logger.info("工作流任务管理器初始化完成")

    @staticmethod
    def _task_has_running_thread(task: Optional[WorkflowTask]) -> bool:
        if task is None:
            return False
        try:
            thread = getattr(task, "executor_thread", None)
            return bool(thread and thread.isRunning())
        except Exception as exc:
            logger.error("读取任务运行句柄失败: task_id=%s, error=%s", getattr(task, "task_id", None), exc)
            return True

    @classmethod
    def _task_has_active_runtime(cls, task: Optional[WorkflowTask]) -> bool:
        if task is None:
            return False

        if cls._task_has_running_thread(task):
            return True

        executor = getattr(task, "executor", None)
        if executor is None:
            return False
        try:
            return bool(executor.is_running())
        except Exception:
            return True


    def has_active_runtime_tasks(self, task_ids: Optional[List[int]] = None) -> bool:
        if task_ids is None:
            tasks = self.get_all_tasks()
        else:
            tasks = [
                self.tasks[task_id]
                for task_id in task_ids
                if task_id in self.tasks
            ]

        for task in tasks:
            if self._task_has_active_runtime(task):
                return True

        return False

    @staticmethod
    def _resolve_execution_result(task_statuses: List[str]) -> Tuple[bool, str]:
        normalized_statuses = [
            str(status or "").strip().lower()
            for status in task_statuses
            if str(status or "").strip()
        ]

        if any(status == 'stopped' for status in normalized_statuses):
            return False, 'stopped'

        if normalized_statuses and all(status == 'completed' for status in normalized_statuses):
            return True, 'completed'

        return False, 'failed'

    @staticmethod
    def _workflow_contains_yolo_task(workflow_data: Any) -> bool:
        if not isinstance(workflow_data, dict):
            return False
        cards = workflow_data.get("cards")
        if not isinstance(cards, list):
            return False
        for card in cards:
            if not isinstance(card, dict):
                continue
            task_type = str(card.get("task_type") or "").strip()
            if task_type and "YOLO" in task_type.upper():
                return True
        return False

    @staticmethod
    def _format_execution_mode_label(mode: str) -> str:
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode.startswith("foreground"):
            return "前台模式"
        if normalized_mode.startswith("background"):
            return "后台模式"
        return normalized_mode or "未知模式"

    @staticmethod
    def _format_screenshot_engine_label(engine: str) -> str:
        normalized_engine = str(engine or "").strip().lower()
        from utils.capture.engine_ids import screenshot_engine_label

        return screenshot_engine_label(normalized_engine)

    def _set_last_execute_error(self, message: str) -> None:
        self._last_execute_error_message = str(message or "").strip()

    def get_last_execute_error_message(self) -> str:
        return str(getattr(self, "_last_execute_error_message", "") or "").strip()

    def _validate_yolo_runtime_for_tasks(self, tasks: List[Any]) -> Tuple[bool, str]:
        yolo_tasks = [
            task for task in tasks
            if self._workflow_contains_yolo_task(getattr(task, "workflow_data", None))
        ]
        if not yolo_tasks:
            return True, ""

        task_names = "、".join(
            str(getattr(task, "name", "") or "").strip() or f"任务{idx + 1}"
            for idx, task in enumerate(yolo_tasks[:3])
        )
        if len(yolo_tasks) > 3:
            task_names = f"{task_names} 等{len(yolo_tasks)}个任务"

        screenshot_engine = str(self.config.get("screenshot_engine", "") or "").strip().lower()
        from utils.capture.engine_ids import (
            is_native_screenshot_engine,
            is_supported_screenshot_engine,
        )
        from task_workflow.yolo_backend import (
            YOLO_BACKEND_NATIVE,
            collect_yolo_backends,
        )

        if screenshot_engine and not is_supported_screenshot_engine(screenshot_engine):
            return False, (
                f"任务“{task_names}”包含YOLO，当前截图引擎为"
                f"{self._format_screenshot_engine_label(screenshot_engine)}。"
                "YOLO可用当前支持的截图引擎，请到全局设置切换后重试。"
            )

        backends = []
        for task in yolo_tasks:
            backends.extend(collect_yolo_backends((getattr(task, "workflow_data", None) or {}).get("cards")))
        unique = set(backends)
        if YOLO_BACKEND_NATIVE in unique and screenshot_engine and not is_native_screenshot_engine(screenshot_engine):
            return False, (
                f"任务“{task_names}”使用原生YOLO，当前截图引擎为"
                f"{self._format_screenshot_engine_label(screenshot_engine)}。"
                "请到全局设置改成 DXGI / GDI / WGC / PrintWindow。"
            )

        return True, ""

    def _validate_wgc_desktop_for_tasks(self, tasks: List[Any]) -> Tuple[bool, str]:
        from utils.window.window_identity import (
            WGC_DESKTOP_ENGINE_MESSAGE,
            is_wgc_with_desktop_target,
        )

        windows = list(self.config.get("bound_windows") or [])
        title = str(self.config.get("target_window_title") or "").strip()
        if title:
            windows.append({
                "title": title,
                "hwnd": self.config.get("target_hwnd"),
            })
        for task in tasks or []:
            windows.append({
                "title": getattr(task, "target_window_title", None),
                "hwnd": getattr(task, "target_hwnd", None),
            })
            workflow_data = getattr(task, "workflow_data", None) or {}
            if isinstance(workflow_data, dict):
                windows.append({
                    "title": workflow_data.get("target_window_title"),
                    "hwnd": workflow_data.get("target_hwnd"),
                })

        engine = str(self.config.get("screenshot_engine") or "").strip().lower()
        if is_wgc_with_desktop_target(engine, windows):
            return False, WGC_DESKTOP_ENGINE_MESSAGE
        return True, ""

    def add_task(self, name: str, filepath: str, workflow_data: dict) -> int:
        """
        添加新任务

        Args:
            name: 任务名称
            filepath: 任务文件路径
            workflow_data: 工作流数据

        Returns:
            新任务的ID
        """
        # 找最小可用ID（复用已删除的ID）
        task_id = 1
        while task_id in self.tasks:
            task_id += 1
        # 更新next_task_id以保持一致性
        if task_id >= self.next_task_id:
            self.next_task_id = task_id + 1

        # 创建任务对象
        task_images_dir = get_effective_workflow_images_dir(workflow_data, self.images_dir)

        task = WorkflowTask(
            task_id=task_id,
            name=name,
            filepath=filepath,
            workflow_data=workflow_data,
            task_modules=self.task_modules,
            images_dir=task_images_dir,
            config=self.config,
            parent=self
        )

        # 连接任务信号
        task.status_changed.connect(partial(self._on_task_status_changed, task_id))
        task.runtime_cleanup_finished.connect(partial(self._on_task_runtime_cleanup_finished, task_id))

        # 添加到管理器
        self.tasks[task_id] = task
        self.task_added.emit(task_id)

        logger.info(f"添加任务成功: ID={task_id}, 名称='{name}'")
        return task_id

    def remove_task(self, task_id: int) -> bool:
        """
        Remove an idle task. Active runtime cleanup is an explicit operation.

        Args:
            task_id: task id

        Returns:
            True when removed immediately, False when the task is active or missing
        """
        if task_id not in self.tasks:
            logger.warning("移除任务失败：未找到 task_id=%s", task_id)
            return False

        task = self.tasks[task_id]
        status = str(getattr(task, "status", "") or "")
        is_active_status = status in ("running", "paused", "starting", "stopping")
        runtime_active = self._task_has_active_runtime(task)
        runtime_references_present = (
            getattr(task, "executor", None) is not None
            or getattr(task, "executor_thread", None) is not None
        )
        if is_active_status or runtime_active or runtime_references_present:
            logger.error(
                "拒绝移除活动任务: task_id=%s, status=%s, runtime_active=%s, runtime_refs=%s",
                task_id,
                status,
                runtime_active,
                runtime_references_present,
            )
            return False

        del self.tasks[task_id]
        self.task_removed.emit(task_id)
        try:
            task.deleteLater()
        except RuntimeError:
            pass

        logger.info("Task removed: ID=%s, name='%s'", task_id, task.name)
        return True

    def get_task(self, task_id: int) -> Optional[WorkflowTask]:
        """获取任务对象"""
        return self.tasks.get(task_id)

    def find_task_by_filepath(self, filepath: str) -> Optional[WorkflowTask]:
        """按文件路径或来源引用查找任务。"""
        from task_workflow.workspace import favorite_path_key, workflow_path_keys

        candidates = set(workflow_path_keys(filepath))
        if not candidates:
            return None
        for task in self.tasks.values():
            task_filepath = str(getattr(task, 'filepath', '') or '')
            if task_filepath and favorite_path_key(task_filepath) in candidates:
                return task
            source_ref = str(getattr(task, 'source_ref', '') or '')
            if source_ref and favorite_path_key(source_ref) in candidates:
                return task
        return None

    def get_all_tasks(self) -> List[WorkflowTask]:
        """获取所有任务列表（按ID排序）"""
        return [self.tasks[tid] for tid in sorted(self.tasks.keys())]

    def get_enabled_tasks(self) -> List[WorkflowTask]:
        """获取所有启用的任务，first_execute=True的任务排在最前面"""
        enabled = [task for task in self.get_all_tasks() if task.enabled]
        # 将first_execute=True的任务排在最前面
        enabled.sort(key=lambda t: (not getattr(t, 'first_execute', False)))
        return enabled

    def get_executable_tasks(self) -> List[WorkflowTask]:
        """获取所有可执行的任务"""
        return [task for task in self.get_all_tasks() if task.can_execute()]

    def execute_all(self, current_task_id: Optional[int] = None) -> bool:
        """
        执行所有可执行的任务（或执行指定的当前任务）

        Args:
            current_task_id: 当前任务ID（跳转模式下使用，None表示执行所有）

        Returns:
            是否成功启动执行
        """
        if self._is_executing:
            logger.warning("已有任务正在执行中")
            return False

        self._set_last_execute_error("")

        all_tasks = self.get_all_tasks()
        logger.info("========== 检查首个执行任务 ==========")
        first_execute_tasks = [
            task
            for task in all_tasks
            if bool(getattr(task, 'first_execute', False)) and task.can_execute()
        ]
        if len(first_execute_tasks) > 1:
            task_names = "、".join(task.name for task in first_execute_tasks)
            self._set_last_execute_error(f"只能配置一个首个执行任务: {task_names}")
            logger.error(self._last_execute_error_message)
            return False

        if first_execute_tasks:
            task = first_execute_tasks[0]
            logger.info("使用明确配置的首个执行任务: '%s'", task.name)
        else:
            if current_task_id is None:
                self._set_last_execute_error("必须明确指定当前任务")
                logger.error(self._last_execute_error_message)
                return False
            task = self.get_task(current_task_id)
            if task is None:
                self._set_last_execute_error(f"任务ID {current_task_id} 不存在")
                logger.error(self._last_execute_error_message)
                return False

        if not task.can_execute():
            self._set_last_execute_error(
                f"任务 '{task.name}' 当前状态不允许启动: {task.status}"
            )
            logger.error(self._last_execute_error_message)
            return False

        valid_runtime, error_message = self._validate_yolo_runtime_for_tasks([task])
        if not valid_runtime:
            self._set_last_execute_error(error_message)
            logger.warning("任务启动前校验失败: %s", error_message)
            return False

        valid_wgc_desktop, wgc_desktop_error = self._validate_wgc_desktop_for_tasks([task])
        if not valid_wgc_desktop:
            self._set_last_execute_error(wgc_desktop_error)
            logger.warning("任务启动前校验失败: %s", wgc_desktop_error)
            return False

        logger.info("执行任务: '%s'", task.name)
        thread = task.execute_async()
        if thread is not None:
            self._is_executing = True
            self._executing_task_ids = [task.task_id]
            return True

        self._is_executing = False
        self._executing_task_ids = []
        self._set_last_execute_error(f"任务 '{task.name}' 启动失败")
        logger.error(self._last_execute_error_message)
        return False

    def execute_task(self, task_id: int) -> bool:
        """通过唯一管理入口启动明确任务。"""
        return self.execute_all(current_task_id=task_id)

    def stop_task(self, task_id: int) -> bool:
        """停止单个任务"""
        task = self.get_task(task_id)
        if task is None:
            logger.error("停止失败: 任务ID %s 不存在", task_id)
            return False
        return bool(task.stop())

    def stop_all(self):
        """停止所有任务(包括运行中和暂停的)"""
        attempted_count = 0
        stopped_count = 0
        for task in self.get_all_tasks():
            thread_running = self._task_has_running_thread(task)

            if task.status in ('running', 'paused') or thread_running:
                attempted_count += 1
                if task.stop():
                    stopped_count += 1

        # 停止时统一清理YOLO运行时（含遗留子进程兜底）
        try:
            from utils.runtime_image_cleanup import cleanup_yolo_runtime_on_stop
            cleanup_yolo_runtime_on_stop(
                release_engine=True,
                compact_memory=True,
            )
        except Exception:
            pass

        if stopped_count > 0:
            logger.info(f"已停止 {stopped_count} 个任务")
        return attempted_count > 0 and stopped_count == attempted_count

    def pause_all_tasks(self):
        """暂停所有正在运行的任务"""
        logger.info("暂停所有正在运行的任务")

        attempted_count = 0
        paused_count = 0
        for task in self.get_all_tasks():
            if task.status == 'running':
                attempted_count += 1
                logger.info(f"暂停任务 {task.task_id}")
                if task.pause():
                    paused_count += 1

        logger.info(f"已暂停 {paused_count} 个任务")
        return attempted_count > 0 and paused_count == attempted_count

    def resume_all_tasks(self):
        """恢复所有暂停的任务"""
        logger.info("恢复所有暂停的任务")

        attempted_count = 0
        resumed_count = 0
        for task in self.get_all_tasks():
            if task.status == 'paused':
                attempted_count += 1
                logger.info(f"恢复任务 {task.task_id}")
                if task.resume():
                    resumed_count += 1

        logger.info(f"已恢复 {resumed_count} 个任务")
        return attempted_count > 0 and resumed_count == attempted_count

    def get_pause_state(self) -> str:
        active_count = 0
        running_count = 0
        paused_count = 0

        for task in self.get_all_tasks():
            status = str(getattr(task, "status", "") or "").strip().lower()
            runtime_active = self._task_has_active_runtime(task)

            if status == "paused" and runtime_active:
                active_count += 1
                paused_count += 1
                continue

            if status == "running":
                active_count += 1
                running_count += 1

        if running_count > 0:
            return "running"
        if paused_count > 0:
            return "paused"
        if self._is_executing and active_count == 0:
            return "running"
        return "idle"

    def save_task(self, task_id: int) -> bool:
        """保存任务到文件"""
        task = self.get_task(task_id)
        if not task:
            logger.error(f"保存失败: 任务ID {task_id} 不存在")
            return False

        return task.save_and_backup()

    def save_all_modified(self) -> int:
        """
        保存所有已修改的任务

        Returns:
            保存成功的任务数量
        """
        saved_count = 0

        for task in self.get_all_tasks():
            if task.modified:
                if task.save_and_backup():
                    saved_count += 1

        logger.info(f"已保存 {saved_count} 个已修改的任务")
        return saved_count

    def _on_task_status_changed(self, task_id: int, status: str):
        """Handle task status updates and finalize execution when possible."""
        self.task_status_changed.emit(task_id, status)

        self._finalize_execution_if_ready()

    def _on_task_runtime_cleanup_finished(self, task_id: int) -> None:
        if task_id not in self.tasks:
            return
        self._finalize_execution_if_ready()

    def _finalize_execution_if_ready(self) -> bool:
        if not self._is_executing:
            return False

        tracked_task_ids = [
            tid for tid in self._executing_task_ids
            if tid in self.tasks
        ]
        if not tracked_task_ids:
            self._is_executing = False
            self._executing_task_ids = []
            return False

        all_completed = all(
            self.tasks[tid].status in ['completed', 'failed', 'stopped']
            for tid in tracked_task_ids
        )
        if not all_completed:
            return False

        if self.has_active_runtime_tasks(tracked_task_ids):
            logger.info("Task runtime cleanup is still in progress; defer all_tasks_completed")
            return False

        task_statuses = [
            self.tasks[tid].status
            for tid in tracked_task_ids
        ]
        all_success, result_type = self._resolve_execution_result(task_statuses)

        self._is_executing = False
        self._executing_task_ids = []
        self.all_tasks_completed.emit(all_success, result_type)

        if result_type == 'stopped':
            logger.info("Workflow execution finished: stopped")
        elif all_success:
            logger.info("Workflow execution finished: success")
        else:
            logger.info("Workflow execution finished: failed")
        return True

    def clear_all(self):
        """清空所有任务"""
        logger.info("清空所有任务")

        if self.has_active_runtime_tasks() or any(
            str(task.status or "") in {"starting", "running", "paused", "stopping"}
            for task in self.get_all_tasks()
        ):
            logger.error("存在活动任务，拒绝清空任务管理器")
            return False

        # 清空任务列表
        task_ids = list(self.tasks.keys())
        for task_id in task_ids:
            self.remove_task(task_id)

        logger.info("所有任务已清空")
        return True

    def get_task_count(self) -> int:
        """获取任务数量"""
        return len(self.tasks)

    def get_running_count(self) -> int:
        """获取正在运行的任务数量"""
        return sum(1 for task in self.get_all_tasks() if task.status == 'running')

    def find_jump_target(self, source_task: WorkflowTask) -> Optional[int]:
        """
        查找跳转目标任务

        Args:
            source_task: 源任务

        Returns:
            目标任务ID，如果没有找到则返回None
        """
        logger.info("========== 查找跳转目标 ==========")
        logger.info(f"  源任务: {source_task.name} (ID={source_task.task_id})")
        logger.info(f"  stop_reason: {source_task.stop_reason}")
        logger.info(f"  jump_rules: {getattr(source_task, 'jump_rules', {})}")

        if not source_task.stop_reason:
            logger.info("  结果: stop_reason为空，不跳转")
            logger.info("==================================")
            return None

        # 从任务的jump_rules中查找目标
        jump_rules = getattr(source_task, 'jump_rules', {})
        target_info = jump_rules.get(source_task.stop_reason)

        logger.info(f"  查找 jump_rules['{source_task.stop_reason}'] = {target_info}")

        if target_info is None:
            logger.info("  结果: 未配置跳转")
            logger.info("==================================")
            return None

        if not isinstance(target_info, dict):
            raise TypeError(
                f"跳转规则必须使用对象格式 {{'id': int}}: reason={source_task.stop_reason}"
            )
        target_id = target_info.get('id')
        if isinstance(target_id, bool) or not isinstance(target_id, int):
            raise TypeError(
                f"跳转目标ID必须是整数: reason={source_task.stop_reason}, value={target_id!r}"
            )
        if target_id in self.tasks:
            target_task = self.tasks[target_id]
            logger.info(f"  结果: 通过ID找到跳转目标 -> '{target_task.name}' (ID={target_id})")
            logger.info("==================================")
            return target_id
        raise ValueError(f"跳转目标任务不存在: {target_id}")

    def __repr__(self):
        return f"<WorkflowTaskManager tasks={len(self.tasks)}>"
