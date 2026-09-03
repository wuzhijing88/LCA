#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工作流标签页控件
支持多任务标签页管理，每个标签页对应一个工作流任务
"""

import logging
import os
import json
from pathlib import Path
from app_core.lca_format.constants import LCA_FILE_FILTER, LCA_SAVE_FILTER
from task_workflow.workflow_payload import load_workflow_file
from utils.app_paths import get_config_path
from utils.window.hwnd_utils import as_hwnd
from typing import Dict, Optional, List, Any
from PySide6.QtWidgets import (QTabWidget, QTabBar, QWidget, QPushButton,
                               QFileDialog, QMessageBox, QMenu)
from PySide6.QtCore import Qt, Signal, QPoint, Slot
from PySide6.QtGui import QWheelEvent

from ..workflow_parts.workflow_view import WorkflowView
from ..workflow_parts.workflow_task_manager import WorkflowTaskManager
from ..system_parts.menu_style import apply_unified_menu_style

logger = logging.getLogger(__name__)

_VIEW_STATE_SETTINGS_KEY = "workflow_view_states_v1"
_WORKFLOW_FILE_SUFFIXES = {".json", ".lca"}


def _strip_workflow_suffix(name: object) -> str:
    text = str(name or "")
    suffix = Path(text).suffix.lower()
    return text[: -len(suffix)] if suffix in _WORKFLOW_FILE_SUFFIXES else text


class WorkflowTabWidget(QTabWidget):
    """
    工作流标签页控件

    特点：
    1. 支持多标签页，每个标签页显示一个工作流
    2. 标签页可关闭（带×按钮）
    3. 右键菜单（关闭、关闭其他、关闭所有、重命名）
    4. 标签页状态指示（未保存、正在运行等）
    5. 最后一个标签页固定为"+"导入按钮
    """

    # 信号定义
    workflow_imported = Signal(int)  # task_id
    workflow_closed = Signal(int)  # task_id
    workflow_renamed = Signal(int, str, str, str)  # task_id, old_filepath, new_filepath, new_name
    current_workflow_changed = Signal(int)  # task_id

    def __init__(self, task_manager: WorkflowTaskManager,
                 task_modules: dict, images_dir: str, parent=None):
        """
        初始化标签页控件

        Args:
            task_manager: 任务管理器
            task_modules: 任务模块字典
            images_dir: 图片目录
            parent: 父控件
        """
        super().__init__(parent)

        self.task_manager = task_manager
        self.task_modules = task_modules
        self.images_dir = images_dir

        # 映射：标签页索引 → 任务ID
        self.tab_to_task: Dict[int, int] = {}
        # 映射：任务ID → 标签页索引
        self.task_to_tab: Dict[int, int] = {}
        # 映射：任务ID → WorkflowView
        self.task_views: Dict[int, WorkflowView] = {}
        # 任务运行时信号源缓存（用于移除时解绑，防止残留回调）
        self._task_runtime_signal_tasks: Dict[int, object] = {}

        # 标志：是否正在删除标签页（阻止误触发导入对话框）
        self._is_removing_tab = False

        # 标志：是否正在自动加载（禁止记录到最近打开列表）
        self._is_auto_loading = False
        # 标志：导入时是否自动激活新标签页
        self._activate_new_tab_on_add = True

        # 记录每个工作流路径对应的画布视图状态（缩放 + 视图中心）
        self._persisted_view_states: Dict[str, Dict[str, List[float]]] = self._load_persisted_view_states()

        self._init_ui()
        self._connect_signals()

        logger.info("工作流标签页控件初始化完成")

    def _init_ui(self):
        """初始化UI"""
        # 设置标签页可关闭
        self.setTabsClosable(True)
        self.setMovable(True)  # 标签页可拖动排序
        self.setDocumentMode(True)  # 文档模式（更紧凑的标签栏）

        # 强制去掉标签栏基线与pane边框，避免顶部/右侧细线残留
        self.tabBar().setDrawBase(False)
        self.setStyleSheet("QTabWidget::pane { border: none; top: 0px; }")

        # 启用滚动按钮（左右切换箭头），避免标签页过多时窗口变宽
        self.setUsesScrollButtons(True)

        # 初始状态：没有任务时隐藏标签栏
        self.tabBar().setVisible(False)

        # 不再使用硬编码样式，让全局主题控制标签页样式
        # 标签页样式现在由 themes/dark.qss 和 themes/light.qss 统一管理

        # 添加"+"导入按钮标签页
        self._add_import_tab()

        # 启用右键菜单
        self.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabBar().customContextMenuRequested.connect(self._show_tab_context_menu)

    def _connect_signals(self):
        """连接信号"""
        # 标签页关闭信号
        self.tabCloseRequested.connect(self._on_tab_close_requested)

        # 当前标签页变化信号（用于发送工作流变化信号，但不触发导入）
        self.currentChanged.connect(self._on_current_changed)

        # 标签页点击信号（用于处理"+"按钮点击）
        self.tabBar().tabBarClicked.connect(self._on_tab_clicked)

        # 标签页移动信号（拖动排序后触发）
        self.tabBar().tabMoved.connect(self._on_tab_moved)

        # 连接任务管理器信号
        self.task_manager.task_added.connect(self._on_task_added)
        self.task_manager.task_removed.connect(self._on_task_removed)
        self.task_manager.task_status_changed.connect(self._on_task_status_changed)

    def _build_view_state_key(self, filepath: Optional[str]) -> str:
        """将任务文件路径归一化为持久化键。"""
        if not filepath:
            return ""
        if not isinstance(filepath, str):
            raise TypeError("画布视图状态路径必须是字符串")
        return os.path.normcase(os.path.abspath(filepath))

    def _normalize_view_state_payload(self, payload: Any) -> Optional[Dict[str, List[float]]]:
        """校验并标准化画布视图状态结构。"""
        if not isinstance(payload, dict):
            return None

        transform = payload.get("view_transform")
        center = payload.get("view_center")
        if not isinstance(transform, list) or len(transform) != 9:
            return None
        if not isinstance(center, list) or len(center) != 2:
            return None

        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in transform + center):
            return None

        return {
            "view_transform": list(transform),
            "view_center": list(center),
        }

    def _load_persisted_view_states(self) -> Dict[str, Dict[str, List[float]]]:
        """从 QSettings 加载画布视图持久化数据。"""
        normalized: Dict[str, Dict[str, List[float]]] = {}
        try:
            from utils.instance_runtime import create_app_settings

            settings = create_app_settings()
            raw_payload = settings.value(_VIEW_STATE_SETTINGS_KEY, "")
            if not isinstance(raw_payload, str):
                raise TypeError("画布视图持久化状态必须是 JSON 字符串")
            raw_payload = raw_payload.strip()
            parsed_payload: Dict[str, Any] = json.loads(raw_payload) if raw_payload else {}

            if not isinstance(parsed_payload, dict):
                return normalized

            for raw_key, raw_state in parsed_payload.items():
                state_key = self._build_view_state_key(str(raw_key))
                state_payload = self._normalize_view_state_payload(raw_state)
                if state_key and state_payload:
                    normalized[state_key] = state_payload
        except Exception as exc:
            logger.warning(f"加载画布视图持久化状态失败: {exc}")
        return normalized

    def _flush_persisted_view_states(self) -> None:
        """将画布视图持久化数据写入 QSettings。"""
        try:
            from utils.instance_runtime import create_app_settings

            settings = create_app_settings()
            settings.setValue(
                _VIEW_STATE_SETTINGS_KEY,
                json.dumps(self._persisted_view_states, ensure_ascii=False),
            )
        except Exception as exc:
            logger.warning(f"保存画布视图持久化状态失败: {exc}")

    def _capture_view_state_from_view(self, workflow_view: WorkflowView) -> Optional[Dict[str, List[float]]]:
        """从 WorkflowView 读取当前缩放与中心点。"""
        if workflow_view is None:
            return None
        try:
            transform = workflow_view.transform()
            viewport_center_view = workflow_view.viewport().rect().center()
            scene_center_point = workflow_view.mapToScene(viewport_center_view)
            payload = {
                "view_transform": [
                    transform.m11(), transform.m12(), transform.m13(),
                    transform.m21(), transform.m22(), transform.m23(),
                    transform.m31(), transform.m32(), transform.m33(),
                ],
                "view_center": [scene_center_point.x(), scene_center_point.y()],
            }
            return self._normalize_view_state_payload(payload)
        except Exception as exc:
            logger.warning(f"读取画布视图状态失败: {exc}")
            return None

    def _persist_task_view_state(self, task: Any, workflow_view: Optional[WorkflowView]) -> bool:
        """持久化单个任务的画布视图状态。"""
        state_key = self._build_view_state_key(getattr(task, "filepath", None))
        if not state_key or workflow_view is None:
            return False

        state_payload = self._capture_view_state_from_view(workflow_view)
        if not state_payload:
            return False

        self._persisted_view_states[state_key] = state_payload
        return True

    def _get_workflow_data_with_persisted_view(self, task) -> dict:
        """加载任务时注入已持久化的画布视图状态。"""
        workflow_data = task.workflow_data if isinstance(task.workflow_data, dict) else {}
        if not isinstance(workflow_data, dict):
            return workflow_data

        state_key = self._build_view_state_key(getattr(task, "filepath", None))
        persisted_state = self._persisted_view_states.get(state_key) if state_key else None
        if not persisted_state:
            return workflow_data

        merged_data = dict(workflow_data)
        merged_data["view_transform"] = list(persisted_state["view_transform"])
        merged_data["view_center"] = list(persisted_state["view_center"])
        return merged_data

    def _capture_current_tab_restore_state(self) -> dict:
        """记录后台导入前的当前标签页。"""
        return {
            "widget": self.currentWidget(),
            "index": self.currentIndex(),
        }

    def _restore_current_tab_after_background_import(self, restore_state: Optional[dict]) -> None:
        """后台导入完成后恢复原来的当前标签页。"""
        if not isinstance(restore_state, dict):
            return

        previous_widget = restore_state.get("widget")
        if previous_widget is not None:
            restored_index = self.indexOf(previous_widget)
            if restored_index >= 0:
                self.setCurrentIndex(restored_index)
                self._activate_current_task_session()
                return

        previous_index = restore_state.get("index", -1)
        if isinstance(previous_index, bool) or not isinstance(previous_index, int):
            raise TypeError("恢复标签页索引必须是整数")

        if 0 <= previous_index < self.count():
            self.setCurrentIndex(previous_index)
            self._activate_current_task_session()

    def persist_open_view_states(self) -> None:
        """将当前所有打开工作流的画布视图状态持久化到 QSettings。"""
        updated = False
        for task_id, workflow_view in list(self.task_views.items()):
            try:
                task = self.task_manager.get_task(task_id)
                if self._persist_task_view_state(task, workflow_view):
                    updated = True
            except Exception as exc:
                logger.warning(f"持久化任务 {task_id} 的画布视图状态失败: {exc}")

        if updated:
            self._flush_persisted_view_states()

    def _add_import_tab(self):
        """添加"+"导入按钮标签页"""
        placeholder = QWidget()
        import_tab_index = self.addTab(placeholder, "+")

        # 设置"+"标签页不可关闭
        close_button = self.tabBar().tabButton(import_tab_index, QTabBar.ButtonPosition.RightSide)
        if close_button:
            close_button.resize(0, 0)  # 隐藏关闭按钮

    def import_workflow(self, filepath: str = None, activate_tab: bool = True) -> Optional[int]:
        """
        导入工作流（支持批量导入）

        Args:
            filepath: 工作流文件路径（None则弹出文件选择对话框，支持多选）

        Returns:
            最后导入的任务ID，失败返回None
        """
        logger.info("import_workflow() 开始执行")
        logger.info(f"   传入参数 filepath={filepath}")

        # 直接检查任务生命周期，不依赖当前活动窗口或 UI 状态。
        active_tasks = [
            task
            for task in self.task_manager.get_all_tasks()
            if self._task_has_active_close_state(task)
        ]
        if active_tasks or self._global_runtime_blocks_import():
            logger.warning(
                "工作流或全局运行态处于活动/清理状态，禁止导入: task_ids=%s",
                [getattr(task, 'task_id', None) for task in active_tasks],
            )
            QMessageBox.warning(self, "无法导入", "工作流正在执行或清理，请先明确停止并等待清理完成。")
            return None

        # 如果没有指定文件路径，弹出文件选择对话框（支持多选）
        if not filepath:
            logger.info("   filepath为空，准备打开文件选择对话框（多选）...")
            logger.info(f"   self={self}")
            logger.info(f"   self.parent()={self.parent()}")
            logger.info(f"   self.isVisible()={self.isVisible()}")
            logger.info(f"   self.isEnabled()={self.isEnabled()}")

            try:
                logger.info("   正在调用 QFileDialog.getOpenFileNames()...")

                # 尝试使用主窗口作为父控件，而不是self（TabWidget）
                from PySide6.QtWidgets import QApplication
                main_window = QApplication.activeWindow()
                if main_window:
                    logger.info(f"   使用主窗口作为父控件: {main_window}")
                    parent_widget = main_window
                else:
                    logger.info("   使用self作为父控件")
                    parent_widget = self

                # 改用 getOpenFileNames 支持多选
                from utils.app_paths import get_workflows_dir
                filepaths, _ = QFileDialog.getOpenFileNames(
                    parent_widget,
                    "导入工作流（可多选）",
                    get_workflows_dir(),
                    LCA_FILE_FILTER
                )
                logger.info(f"   QFileDialog.getOpenFileNames() 返回: {len(filepaths)} 个文件")
            except Exception as e:
                logger.error(f"   QFileDialog.getOpenFileNames() 抛出异常: {e}", exc_info=True)
                return None

            if not filepaths:
                logger.info("   filepaths为空，用户取消或未选择文件")
                return None  # 用户取消

            # 批量导入多个文件
            last_task_id = None
            success_count = 0
            error_files = []
            restore_state = None if activate_tab else self._capture_current_tab_restore_state()

            for filepath in filepaths:
                task_id = self._import_single_workflow(filepath, activate_tab=activate_tab)
                if task_id is not None:
                    last_task_id = task_id
                    success_count += 1
                else:
                    error_files.append(os.path.basename(filepath))

            if restore_state is not None:
                self._restore_current_tab_after_background_import(restore_state)

            # 显示导入结果
            if success_count > 0:
                if len(error_files) > 0:
                    QMessageBox.warning(
                        self,
                        "部分导入成功",
                        f"成功导入 {success_count} 个工作流\n\n失败文件：\n" + "\n".join(error_files)
                    )
                else:
                    QMessageBox.information(
                        self,
                        "导入成功",
                        f"成功导入 {success_count} 个工作流"
                    )

            return last_task_id

        else:
            # 单个文件导入
            restore_state = None if activate_tab else self._capture_current_tab_restore_state()
            task_id = self._import_single_workflow(filepath, activate_tab=activate_tab)
            if restore_state is not None:
                self._restore_current_tab_after_background_import(restore_state)
            return task_id

    def _import_single_workflow(self, filepath: str, activate_tab: bool = True) -> Optional[int]:
        """
        导入单个工作流文件

        Args:
            filepath: 工作流文件路径

        Returns:
            新任务的ID，失败返回None
        """

        # 检查文件是否存在
        if not str(filepath).startswith("memory://") and not os.path.exists(filepath):
            QMessageBox.critical(self, "导入失败", f"文件不存在: {filepath}")
            return None

        try:
            # 加载工作流数据
            workflow_data = load_workflow_file(filepath)
            jump_config, window_binding = self._validate_workflow_import_data(workflow_data, filepath)

            # 生成任务名称
            name = os.path.basename(filepath)

            # 添加任务到管理器
            previous_activate_flag = self._activate_new_tab_on_add
            self._activate_new_tab_on_add = bool(activate_tab)
            try:
                task_id = self.task_manager.add_task(name, filepath, workflow_data)
            finally:
                self._activate_new_tab_on_add = previous_activate_flag
            # 加载已经通过严格校验的跳转配置
            task = self.task_manager.get_task(task_id)
            if task and jump_config is not None:
                task.jump_enabled = jump_config['enabled']
                task.jump_rules = jump_config['rules'].copy()
                task.jump_delay = jump_config['delay']
                task.first_execute = jump_config['first_execute']
                logger.info(f"已加载跳转配置: enabled={task.jump_enabled}, rules={task.jump_rules}, delay={task.jump_delay}秒, first_execute={task.first_execute}")

            # 窗口句柄在创建任务前已经验证，不允许失效后自动解绑。
            if task and window_binding is not None:
                task.bound_window_id = window_binding['bound_window_id']
                task.target_window_title = window_binding['target_window_title']
                task.target_hwnd = window_binding['target_hwnd']
                if task.target_hwnd is not None:
                    logger.info(f"已加载窗口绑定: '{task.target_window_title}' (HWND: {task.target_hwnd})")

            logger.info(f"工作流导入成功: {filepath}")
            self.workflow_imported.emit(task_id)

            # 保存到最近打开列表（自动加载时跳过）
            if not self._is_auto_loading:
                self._save_to_recent_workflows(filepath)

            return task_id

        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "导入失败", f"无法解析文件:\n{e}")
            return None
        except Exception as e:
            logger.error(f"导入工作流失败: {e}", exc_info=True)
            QMessageBox.critical(self, "导入失败", f"导入失败:\n{e}")
            return None

    def _validate_workflow_import_data(self, workflow_data: Any, filepath: str):
        """校验当前版本工作流格式，并把失效 HWND 迁移到当前全局绑定。

        无法可信匹配时保留原绑定并继续导入，避免每次弹窗打断。
        """
        if not isinstance(workflow_data, dict):
            raise TypeError("工作流根节点必须是字典")
        if not isinstance(workflow_data.get('cards'), list):
            raise TypeError("工作流 cards 必须是列表")
        if not isinstance(workflow_data.get('connections'), list):
            raise TypeError("工作流 connections 必须是列表")

        from task_workflow.workflow_sanitize import sanitize_workflow_data

        sanitize_workflow_data(workflow_data)
        jump_config = workflow_data.get('jump_config')
        if jump_config is not None:
            if not isinstance(jump_config, dict):
                raise TypeError("工作流 jump_config 必须是字典")
            required_jump_keys = {'enabled', 'rules', 'delay', 'first_execute'}
            if set(jump_config) != required_jump_keys:
                raise ValueError("工作流 jump_config 字段不完整或包含未知字段")
            if not isinstance(jump_config['enabled'], bool):
                raise TypeError("工作流 jump_config.enabled 必须是布尔值")
            if not isinstance(jump_config['first_execute'], bool):
                raise TypeError("工作流 jump_config.first_execute 必须是布尔值")
            delay = jump_config['delay']
            if isinstance(delay, bool) or not isinstance(delay, (int, float)) or delay < 0:
                raise TypeError("工作流 jump_config.delay 必须是非负数")
            rules = jump_config['rules']
            if not isinstance(rules, dict):
                raise TypeError("工作流 jump_config.rules 必须是字典")
            for reason, target in rules.items():
                if not isinstance(reason, str) or not reason.strip():
                    raise TypeError("工作流跳转原因必须是非空字符串")
                if not isinstance(target, dict) or set(target) != {'id'}:
                    raise TypeError(f"跳转规则 '{reason}' 必须使用 {{'id': 整数}} 格式")
                target_id = target['id']
                if isinstance(target_id, bool) or not isinstance(target_id, int) or target_id <= 0:
                    raise TypeError(f"跳转规则 '{reason}' 的 id 必须是正整数")

        window_binding = workflow_data.get('window_binding')
        if window_binding is not None:
            if not isinstance(window_binding, dict):
                raise TypeError("工作流 window_binding 必须是字典")
            required_window_keys = {'bound_window_id', 'target_window_title', 'target_hwnd'}
            if set(window_binding) != required_window_keys:
                raise ValueError("工作流 window_binding 字段不完整或包含未知字段")
            if not isinstance(window_binding['target_window_title'], str):
                raise TypeError("工作流 target_window_title 必须是字符串")
            target_hwnd = window_binding['target_hwnd']
            if target_hwnd is None:
                if window_binding['bound_window_id'] is not None or window_binding['target_window_title']:
                    raise ValueError("未绑定窗口时 bound_window_id 必须为 null 且标题必须为空")
            else:
                if isinstance(target_hwnd, bool):
                    raise TypeError("工作流 target_hwnd 必须是正整数或 null")
                normalized_hwnd = as_hwnd(target_hwnd)
                if normalized_hwnd == 0:
                    raise TypeError("工作流 target_hwnd 必须是正整数或 null")
                window_binding['target_hwnd'] = normalized_hwnd
                if not window_binding['target_window_title'].strip():
                    raise ValueError("已绑定窗口时 target_window_title 不能为空")
                from utils.window.window_identity import resolve_workflow_window_binding

                config = getattr(self.task_manager, 'config', {})
                bound_windows = config.get('bound_windows', []) if isinstance(config, dict) else []
                resolved_binding = resolve_workflow_window_binding(window_binding, bound_windows)
                if resolved_binding is None:
                    logger.warning(
                        "工作流绑定窗口已失效（HWND: %s），已保留原配置并继续导入: %s",
                        normalized_hwnd,
                        filepath,
                    )
                else:
                    if resolved_binding['target_hwnd'] != normalized_hwnd:
                        logger.info(
                            "导入时刷新工作流绑定窗口: %s => %s (%s)",
                            normalized_hwnd,
                            resolved_binding['target_hwnd'],
                            resolved_binding['target_window_title'],
                        )
                    window_binding.update(resolved_binding)

        return jump_config, window_binding

    def _get_current_workflow_filepath(self) -> Optional[str]:
        task_id = self.get_current_task_id()
        if task_id is None:
            return None
        task = self.task_manager.get_task(task_id)
        return getattr(task, "filepath", None) if task else None

    @staticmethod
    def _resolve_explicit_sub_workflow_path(filepath: str, parent_workflow_file: Optional[str]) -> str:
        """只按调用方给出的明确路径解析，不搜索或猜测同名文件。"""
        if not isinstance(filepath, str) or not filepath.strip():
            raise ValueError("未指定子工作流文件")
        filepath = filepath.strip()
        if filepath.startswith("memory://"):
            return filepath
        try:
            from app_core.lca_format.session import get_current_session

            session = get_current_session()
            logical_path = filepath.replace("\\", "/").lstrip("/")
            if session is not None and session.get_bytes(logical_path) is not None:
                return "memory://" + logical_path
        except Exception:
            pass
        if os.path.isabs(filepath):
            resolved = os.path.abspath(os.path.normpath(filepath))
        else:
            if not isinstance(parent_workflow_file, str) or not parent_workflow_file.strip():
                raise ValueError("相对子工作流路径缺少父工作流文件")
            parent_path = os.path.abspath(os.path.normpath(parent_workflow_file))
            parent_dir = parent_path if os.path.isdir(parent_path) else os.path.dirname(parent_path)
            resolved = os.path.abspath(os.path.normpath(os.path.join(parent_dir, filepath)))
        if not resolved.startswith("memory://") and not os.path.isfile(resolved):
            raise FileNotFoundError(f"子工作流文件不存在: {resolved}")
        return resolved

    def open_sub_workflow(self, filepath: str, parent_workflow_file: Optional[str] = None) -> Optional[int]:
        """
        打开子工作流进行编辑（在新标签页中）

        与普通导入的区别：
        1. 标签页标题带"子流程:"前缀
        2. 如果文件已打开，直接切换到该标签页

        Args:
            filepath: 子工作流文件路径

        Returns:
            任务ID，失败返回None
        """
        logger.info(f"[子工作流] 打开子工作流: {filepath}")

        if not filepath:
            QMessageBox.warning(self, "打开失败", "未指定子工作流文件")
            return None

        parent_file = parent_workflow_file or self._get_current_workflow_filepath()
        try:
            resolved_filepath = self._resolve_explicit_sub_workflow_path(filepath, parent_file)
        except (TypeError, ValueError, FileNotFoundError) as exc:
            QMessageBox.warning(self, "打开失败", str(exc))
            return None

        filepath = resolved_filepath

        # 检查是否已经打开了这个文件
        for task_id, view in self.task_views.items():
            task = self.task_manager.get_task(task_id)
            if task and task.filepath == filepath:
                # 已打开，切换到该标签页
                tab_index = self.task_to_tab.get(task_id)
                if tab_index is not None:
                    logger.info(f"[子工作流] 文件已打开，切换到标签页 {tab_index}")
                    self.setCurrentIndex(tab_index)
                    return task_id

        # 文件未打开，导入它
        try:
            workflow_data = load_workflow_file(filepath)
            jump_config, window_binding = self._validate_workflow_import_data(workflow_data, filepath)

            # 生成标签页名称（带子流程前缀）
            base_name = os.path.basename(filepath)
            name = f"子流程:{base_name}"

            # 添加任务到管理器
            task_id = self.task_manager.add_task(name, filepath, workflow_data)

            # 标记为子工作流（可选，用于后续识别）
            task = self.task_manager.get_task(task_id)
            if task:
                task.is_sub_workflow = True
                if jump_config is not None:
                    task.jump_enabled = jump_config['enabled']
                    task.jump_rules = jump_config['rules'].copy()
                    task.jump_delay = jump_config['delay']
                    task.first_execute = jump_config['first_execute']
                if window_binding is not None:
                    task.bound_window_id = window_binding['bound_window_id']
                    task.target_window_title = window_binding['target_window_title']
                    task.target_hwnd = window_binding['target_hwnd']

            logger.info(f"[子工作流] 打开成功: {filepath}, task_id={task_id}")
            self.workflow_imported.emit(task_id)

            return task_id

        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "打开失败", f"无法解析文件:\n{e}")
            return None
        except Exception as e:
            logger.error(f"[子工作流] 打开失败: {e}", exc_info=True)
            QMessageBox.critical(self, "打开失败", f"打开子工作流失败:\n{e}")
            return None

    def create_blank_workflow(self, name: str = None) -> Optional[int]:
        """
        创建空白工作流

        Args:
            name: 工作流名称（None则使用默认名称）

        Returns:
            新任务的ID，失败返回None
        """
        try:
            from utils.app_paths import get_workflows_dir

            # 如果没有提供名称，使用默认名称
            if not name:
                # 生成默认名称：未命名工作流1, 未命名工作流2, ...
                count = 1
                while True:
                    name = f"未命名工作流{count}"
                    # 检查是否已存在同名任务
                    exists = False
                    for task in self.task_manager.get_all_tasks():
                        if task.name == name or task.name == f"{name}.lca":
                            exists = True
                            break
                    if os.path.exists(os.path.join(get_workflows_dir(), f"{name}.lca")):
                        exists = True
                    if not exists:
                        break
                    count += 1

            # 创建空白工作流数据
            workflow_data = {
                'cards': [],
                'connections': [],
                'metadata': {
                    'created': 'blank',
                    'version': '1.0'
                }
            }

            # 添加任务到管理器（预设 workflows 目录作为首次保存目标）
            default_filepath = os.path.join(get_workflows_dir(), f"{name}.lca")
            task_id = self.task_manager.add_task(name, default_filepath, workflow_data)
            self.workflow_imported.emit(task_id)

            return task_id

        except Exception as e:
            logger.error(f"创建空白工作流失败: {e}", exc_info=True)
            QMessageBox.critical(self, "创建失败", f"创建空白工作流失败:\n{e}")
            return None

    def _on_task_added(self, task_id: int):
        """任务添加回调"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return

        # 如果是第一个任务，显示标签栏
        if len(self.task_views) == 0:
            logger.info("添加第一个任务，显示标签栏")
            self.tabBar().setVisible(True)

        # 创建WorkflowView
        workflow_view = WorkflowView(
            task_modules=self.task_modules,
            images_dir=getattr(task, 'images_dir', self.images_dir),
            parent=self
        )
        workflow_view.task_id = task_id

        metadata = task.workflow_data.get('metadata') if isinstance(task.workflow_data, dict) else {}
        workflow_view.workflow_metadata = dict(metadata) if isinstance(metadata, dict) else {}

        # 设置main_window引用，用于检查运行状态
        workflow_view.main_window = self.window()

        # 强制初始化WorkflowView的交互属性
        from PySide6.QtWidgets import QGraphicsView
        from PySide6.QtCore import Qt

        workflow_view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        workflow_view.setInteractive(True)
        workflow_view.setEnabled(True)
        workflow_view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        workflow_view.viewport().setMouseTracking(True)

        logger.info("WorkflowView创建完成:")
        logger.info(f"   dragMode: {workflow_view.dragMode()}")
        logger.info(f"   interactive: {workflow_view.isInteractive()}")
        logger.info(f"   enabled: {workflow_view.isEnabled()}")
        logger.info(f"   focusPolicy: {workflow_view.focusPolicy()}")

        # 加载工作流数据（优先应用退出时持久化的视图状态）
        workflow_data_for_load = self._get_workflow_data_with_persisted_view(task)
        workflow_view.load_workflow(workflow_data_for_load)
        # 导入校验后全局状态仍可能变化；内部加载可完成，但运行期间的新视图必须保持只读。
        workflow_view.editing_enabled = not self._global_runtime_blocks_import()

        # 加载后再次确保拖拽模式正确（加载可能会改变设置）
        workflow_view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        logger.info(f"   加载后dragMode: {workflow_view.dragMode()}")

        # 应用网格/卡片吸附设置
        try:
            main_win = self.window()
            if main_win and hasattr(main_win, 'config'):
                grid_enabled = bool(main_win.config.get('enable_canvas_grid', True))
                card_snap_enabled = bool(main_win.config.get('enable_card_snap', True))
                workflow_view.set_grid_enabled(grid_enabled)
                workflow_view.set_card_snap_enabled(card_snap_enabled)
        except Exception:
            pass

        # 连接WorkflowView的信号，标记任务为已修改
        workflow_view.card_added.connect(lambda: self._mark_task_modified(task_id))
        workflow_view.card_deleted.connect(lambda: self._mark_task_modified(task_id))
        # 【修复】连线修改时也立即更新workflow_data（原本就有，但确认一下）
        workflow_view.connection_added.connect(lambda start_card, end_card, conn_type: self._mark_task_modified(task_id))
        workflow_view.connection_deleted.connect(lambda conn: self._mark_task_modified(task_id))
        workflow_view.card_moved.connect(lambda: self._mark_task_modified(task_id))
        # 【新增】连接变化时刷新参数面板（用于随机跳转等动态参数）
        # 注意：connection_deleted信号发出时，conn.start_item可能已被清空，需要在连接前保存
        workflow_view.connection_added.connect(lambda start_card, end_card, conn_type: self._on_connection_changed(start_card))
        workflow_view.connection_deleted.connect(lambda conn: self._on_connection_deleted_for_random_jump(conn, task_id))

        # 测试入口直接连接主窗口处理器；没有连接时菜单点击只会发射信号而不会执行。
        main_window = self.window()
        if main_window is None:
            raise RuntimeError("创建工作流视图时未找到主窗口，无法绑定测试执行入口")
        workflow_view.test_card_execution_requested.connect(
            main_window._handle_test_card_execution,
            Qt.ConnectionType.QueuedConnection,
        )
        workflow_view.test_flow_execution_requested.connect(
            main_window._handle_test_flow_execution,
            Qt.ConnectionType.QueuedConnection,
        )
        # 连接子工作流打开信号
        workflow_view.open_sub_workflow_requested.connect(self.open_sub_workflow)

        # 连接任务的卡片状态信号到WorkflowView
        # 使用默认连接方式（AutoConnection），让Qt自动选择最佳连接类型
        task.card_executing.connect(
            self._on_task_card_executing,
            Qt.ConnectionType.QueuedConnection
        )
        task.card_finished.connect(
            self._on_task_card_finished,
            Qt.ConnectionType.QueuedConnection
        )
        self._task_runtime_signal_tasks[task_id] = task

        # 插入标签页（在"+"之前）
        insert_index = self.count() - 1  # "+"标签页的索引
        tab_index = self.insertTab(insert_index, workflow_view, task.name)

        # 设置自定义关闭按钮（带X图标）
        self._set_custom_close_button(tab_index)

        logger.info(f"标签页插入: insert_index={insert_index}, 返回tab_index={tab_index}")

        # 关键修复：insertTab后需要重建映射，因为所有索引都可能改变
        # 先将新view记录到task_views
        self.task_views[task_id] = workflow_view

        # 重建所有映射关系
        self._rebuild_mappings()

        logger.info("映射关系重建完成:")
        logger.info(f"   tab_to_task: {self.tab_to_task}")
        logger.info(f"   task_to_tab: {self.task_to_tab}")

        # 切换到新标签页
        if self._activate_new_tab_on_add:
            self.setCurrentIndex(tab_index)
            self._activate_current_task_session()

        # 更新标签页状态
        self._update_tab_status(task_id)

        logger.debug(f"标签页已添加: task_id={task_id}, tab_index={tab_index}, name='{task.name}'")

    def _set_custom_close_button(self, tab_index: int):
        """为标签页设置自定义关闭按钮"""
        close_button = QPushButton("×")
        close_button.setFixedSize(16, 16)
        # 不再使用硬编码样式，让全局主题控制关闭按钮样式
        # 关闭按钮样式现在由 themes/dark.qss 和 themes/light.qss 中的 QTabBar::close-button 统一管理
        close_button.setObjectName("tabCloseButton")
        # 使用property存储初始的tab_index，点击时动态查找正确的索引
        close_button.setProperty("initial_tab_index", tab_index)
        close_button.clicked.connect(self._on_close_button_clicked)
        self.tabBar().setTabButton(tab_index, QTabBar.ButtonPosition.RightSide, close_button)

    def _on_close_button_clicked(self):
        """关闭按钮点击处理"""
        sender_button = self.sender()
        if not sender_button:
            return

        # 遍历所有标签页，找到这个按钮对应的标签页
        for i in range(self.count()):
            button = self.tabBar().tabButton(i, QTabBar.ButtonPosition.RightSide)
            if button == sender_button:
                self._on_tab_close_requested(i)
                return

    def _on_task_removed(self, task_id: int):
        """任务删除回调"""
        task_signal_source = self._task_runtime_signal_tasks.pop(task_id, None)
        if task_signal_source is not None:
            try:
                task_signal_source.card_executing.disconnect(self._on_task_card_executing)
            except (TypeError, RuntimeError):
                pass
            try:
                task_signal_source.card_finished.disconnect(self._on_task_card_finished)
            except (TypeError, RuntimeError):
                pass
            session_path = str(
                getattr(task_signal_source, "lca_session_path", "") or ""
            ).strip()
            if session_path and not any(
                str(getattr(task, "lca_session_path", "") or "").strip()
                == session_path
                for task in self.task_manager.get_all_tasks()
            ):
                from app_core.lca_format.session import clear_path

                clear_path(session_path)

        if task_id not in self.task_to_tab:
            logger.warning(f"尝试删除不存在的任务: task_id={task_id}")
            return

        try:
            from task_workflow.workflow_vars import clear_context_for_task

            clear_context_for_task(task_id)
        except Exception as exc:
            logger.warning(f"清理工作流上下文失败: {exc}")

        tab_index = self.task_to_tab[task_id]
        logger.info(f"删除任务标签页: task_id={task_id}, tab_index={tab_index}")
        workflow_widget = self.widget(tab_index)

        # 关闭标签页前先记住当前视图状态，避免重启后丢失最后一次缩放/位置
        try:
            if isinstance(workflow_widget, WorkflowView):
                if self._persist_task_view_state(task_signal_source, workflow_widget):
                    self._flush_persisted_view_states()
        except Exception as exc:
            logger.warning(f"关闭标签页时保存画布视图状态失败: {exc}")

        # 计算删除后应该切换到的索引
        # 优先选择右边的标签，如果没有右边的就选左边的
        next_index = tab_index  # 默认位置
        if tab_index < self.count() - 2:  # 右边还有其他任务标签（不包括"+"标签）
            next_index = tab_index  # 删除后，右边的标签会移到当前位置
            logger.debug(f"删除后将切换到右边的标签（删除后的索引: {next_index}）")
        elif tab_index > 0:  # 左边有其他任务标签
            next_index = tab_index - 1  # 切换到左边的标签
            logger.debug(f"删除后将切换到左边的标签（索引: {next_index}）")
        else:  # 只有一个标签
            next_index = -1  # 标记为无效
            logger.debug("这是最后一个标签，删除后将没有任务")

        # 先从task_views中删除
        if task_id in self.task_views:
            del self.task_views[task_id]
            logger.debug(f"已从task_views删除: task_id={task_id}")

        # 设置标志，防止removeTab触发currentChanged时误触发导入对话框
        self._is_removing_tab = True
        try:
            # 移除标签页（这会改变所有后续标签的索引）
            self.removeTab(tab_index)
            logger.debug(f"已移除标签页: index={tab_index}")
        finally:
            # 确保标志被重置
            self._is_removing_tab = False

        # 主窗口可能仍持有被关闭页的 workflow_view 引用，先清空再销毁页面对象。
        try:
            main_window = self.window()
            if (
                main_window is not None
                and hasattr(main_window, "workflow_view")
                and getattr(main_window, "workflow_view", None) is workflow_widget
            ):
                try:
                    if hasattr(main_window, "_disconnect_workflow_selection_signal"):
                        main_window._disconnect_workflow_selection_signal(workflow_widget)
                except Exception:
                    pass
                main_window.workflow_view = None
        except Exception:
            pass

        # removeTab 只会移除页签，不会销毁页面对象；这里必须显式释放。
        self._dispose_workflow_widget(workflow_widget)

        # 关键：直接重建映射，不要手动删除（因为索引已经变化）
        self._rebuild_mappings()
        logger.debug("映射关系已重建")

        # 删除后切换到合适的标签页
        if len(self.task_views) > 0 and next_index >= 0:
            # 确保next_index有效
            if next_index >= self.count() - 1:
                next_index = self.count() - 2  # 最后一个任务标签

            logger.info(f"删除后切换到标签页: index={next_index}")
            self.setCurrentIndex(next_index)
            self._previous_valid_index = next_index
        else:
            # 没有任务了，重置为-1（表示无效）
            self._previous_valid_index = -1
            logger.debug("没有任务了，重置 _previous_valid_index = -1")

        # 如果没有任务了，隐藏标签栏
        if len(self.task_views) == 0:
            logger.info("所有任务已关闭，隐藏标签栏")
            self.tabBar().setVisible(False)

        logger.debug(f"标签页已删除: task_id={task_id}")

    def _dispose_workflow_widget(self, workflow_widget: Optional[QWidget]) -> None:
        """显式销毁已关闭标签页的页面对象，避免内存残留。"""
        if workflow_widget is None:
            return

        try:
            if isinstance(workflow_widget, WorkflowView):
                try:
                    workflow_widget.main_window = None
                except Exception:
                    pass

                # WorkflowView 覆盖了 scene 为属性，不是 QGraphicsView.scene() 方法。
                # 这里统一兼容属性/方法两种形态，避免拿不到场景导致信号无法解绑。
                scene = getattr(workflow_widget, "scene", None)
                if callable(scene):
                    try:
                        scene = scene()
                    except Exception:
                        scene = None

                try:
                    workflow_widget.undo_stack.clear()
                except Exception:
                    pass
                try:
                    workflow_widget.flashing_card_ids.clear()
                except Exception:
                    pass
                try:
                    workflow_widget._deleting_cards.clear()
                except Exception:
                    pass

                if scene is not None:
                    try:
                        scene.clear()
                    except Exception:
                        pass

                try:
                    workflow_widget.cards.clear()
                except Exception:
                    pass
                try:
                    workflow_widget.connections.clear()
                except Exception:
                    pass
        except Exception as exc:
            logger.warning(f"清理已关闭工作流页面失败: {exc}")

        try:
            workflow_widget.setParent(None)
        except Exception:
            pass

        try:
            workflow_widget.deleteLater()
        except RuntimeError:
            pass

    @Slot(int)
    def _on_task_card_executing(self, card_id: int):
        """在主线程更新卡片执行中状态。"""
        sender_task = self.sender()
        task_id = getattr(sender_task, "task_id", None)
        if task_id is None:
            return

        workflow_view = self.task_views.get(task_id)
        if workflow_view is None:
            return

        try:
            workflow_view.set_card_state(card_id, "executing")
        except RuntimeError:
            pass

    @Slot(int, bool)
    def _on_task_card_finished(self, card_id: int, success: bool):
        """在主线程更新卡片完成状态。"""
        sender_task = self.sender()
        task_id = getattr(sender_task, "task_id", None)
        if task_id is None:
            return

        workflow_view = self.task_views.get(task_id)
        if workflow_view is None:
            return

        try:
            workflow_view.set_card_state(card_id, "success" if success else "failure")
        except RuntimeError:
            pass

    def _on_task_status_changed(self, task_id: int, status: str):
        """任务状态变化回调"""
        self._update_tab_status(task_id)

    def _task_has_active_close_state(self, task) -> bool:
        """关闭标签前执行与任务管理器一致的严格活动态检查。"""
        status = str(getattr(task, "status", "") or "").strip().lower()
        if status in {"running", "paused", "starting", "stopping"}:
            return True
        if getattr(task, "executor", None) is not None or getattr(task, "executor_thread", None) is not None:
            return True
        return bool(self.task_manager._task_has_active_runtime(task))

    def _global_runtime_blocks_import(self) -> bool:
        """全局状态机仍在运行周期时禁止创建新的工作流视图。"""
        main_window = self.window()
        state_manager = getattr(main_window, "task_state_manager", None)
        if state_manager is None:
            return False
        try:
            state = str(state_manager.get_current_state() or "").strip().lower()
        except Exception as exc:
            logger.warning("读取全局任务状态失败，保守禁止导入: %s", exc)
            return True
        if state not in {"starting", "running", "paused", "stopping", "stopped"}:
            logger.warning("检测到未知全局任务状态，保守禁止导入: %r", state)
            return True
        return state != "stopped"

    def close_tab(self, index: int) -> bool:
        """关闭一个工作流标签：有未保存更改时先问用户（保存 / 放弃 / 取消），与关闭程序时的逻辑一致。

        所有"关闭某个工作流"的入口（标签 ×、右键菜单、收藏勾选/移除）都应走这里；
        `close_tab_silent` 只留给启动阶段按收藏同步标签这种不可能有未保存编辑的场景。
        返回是否真的关闭了。
        """
        return self._on_tab_close_requested(index)

    def _on_tab_close_requested(self, index: int) -> bool:
        """标签页关闭请求"""
        # "+"标签页不可关闭
        if index == self.count() - 1:
            return False

        if index not in self.tab_to_task:
            return False

        task_id = self.tab_to_task[index]
        task = self.task_manager.get_task(task_id)

        if not task:
            return False

        if self._task_has_active_close_state(task):
            logger.warning("拒绝关闭活动任务标签: task_id=%s, status=%s", task_id, task.status)
            QMessageBox.warning(
                self,
                "无法关闭",
                f"任务 '{task.name}' 仍处于活动或清理状态，请先明确停止并等待清理完成。",
            )
            return False

        # 检查是否有未保存的更改
        if task.modified:
            reply = QMessageBox.question(
                self,
                "未保存的更改",
                f"任务 '{task.name}' 有未保存的更改，关闭前是否保存？",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )

            if reply == QMessageBox.StandardButton.Save:
                # 更新工作流数据
                if task_id in self.task_views:
                    workflow_view = self.task_views[task_id]
                    workflow_data = workflow_view.serialize_workflow()
                    task.update_workflow_data(workflow_data)

                # 如果任务没有文件路径（新建的空白工作流），使用另存为
                if not task.filepath:
                    self._save_task_as(task_id)
                    # 检查是否保存成功（用户可能取消）
                    if not task.filepath:
                        logger.info("用户取消了另存为，不关闭标签页")
                        return False
                else:
                    if not self._persist_task(task):
                        QMessageBox.warning(self, "保存失败", f"无法保存任务 '{task.name}'")
                        return False
            elif reply == QMessageBox.StandardButton.Cancel:
                return False

        # 删除任务。失败即明确拒绝，不停止、不排队、不延迟重试。
        if self.task_manager.remove_task(task_id):
            if task.filepath:
                self._remove_from_recent_workflows(task.filepath)
            self.workflow_closed.emit(task_id)
            return True
        logger.error("关闭标签失败，任务管理器拒绝移除: task_id=%s", task_id)
        return False

    def close_tab_silent(self, index: int) -> bool:
        """静默关闭标签页（不弹出确认框）"""
        # "+"标签页不可关闭
        if index == self.count() - 1:
            return False

        if index not in self.tab_to_task:
            return False

        task_id = self.tab_to_task[index]
        task = self.task_manager.get_task(task_id)

        if not task:
            return False

        if self._task_has_active_close_state(task):
            logger.warning("静默关闭被拒绝：任务仍处于活动或清理状态: task_id=%s", task_id)
            return False

        # 静默仅表示不弹窗，不表示可以隐式改变任务运行状态。
        if self.task_manager.remove_task(task_id):
            if task.filepath:
                self._remove_from_recent_workflows(task.filepath)
            self.workflow_closed.emit(task_id)
            return True
        logger.error("静默关闭失败，任务管理器拒绝移除: task_id=%s", task_id)
        return False

    def _on_tab_clicked(self, index: int):
        """标签页被点击时触发"""
        logger.info(f"标签页点击事件触发: index={index}, count={self.count()}")

        # 如果正在删除标签页，不处理
        if self._is_removing_tab:
            logger.info("   正在删除标签页，跳过处理")
            return

        # 点击"+"标签页，导入工作流
        if index == self.count() - 1:
            logger.info(f"确认点击了 '+' 导入按钮 (index={index})")

            # 保存之前的索引
            previous_index = getattr(self, '_previous_valid_index', 0)
            logger.info(f"   之前的标签页索引: {previous_index}")

            # 导入工作流
            logger.info("   正在调用 import_workflow()...")
            task_id = self.import_workflow()
            logger.info(f"   import_workflow() 返回: task_id={task_id}")

            # 如果导入失败（用户取消或出错），切换回之前的标签页
            if task_id is None:
                logger.info("   用户取消导入或导入失败，切换回之前的标签页")
                # 检查previous_index是否有效
                if previous_index >= 0 and previous_index < self.count() - 1:
                    logger.info(f"   切换回索引 {previous_index}")
                    self.setCurrentIndex(previous_index)
                elif self.count() > 1:
                    # 如果之前没有有效索引，但现在有任务，切换到第一个
                    logger.info("   切换到第一个标签页 (index=0)")
                    self.setCurrentIndex(0)
                # else: 没有任何任务标签，保持在"+"标签（但标签栏是隐藏的）
            else:
                logger.info(f"   导入成功！task_id={task_id}")
            # else: 导入成功，_on_task_added 会自动切换到新标签页

    def _activate_current_task_session(self) -> None:
        from app_core.lca_format.session import activate, deactivate, register

        task_id = self.get_current_task_id()
        task = self.task_manager.get_task(task_id) if task_id is not None else None
        session = getattr(task, "lca_session", None) if task is not None else None
        session_path = str(getattr(task, "lca_session_path", "") or "").strip()
        if session is not None and session_path:
            register(session_path, session)
            activate(session_path)
            return
        deactivate()

    def _on_current_changed(self, index: int):
        """当前标签页变化"""
        logger.info(f"标签页变化事件触发: index={index}, count={self.count()}")

        # 如果正在删除标签页，不处理
        if self._is_removing_tab:
            logger.info("   正在删除标签页，跳过处理")
            return

        # 如果切换到"+"标签页，不处理（由 _on_tab_clicked 处理）
        if index == self.count() - 1:
            logger.info("   切换到 '+' 标签页，等待用户点击")
            return

        # 保存当前有效的标签页索引（非"+"标签页）
        self._previous_valid_index = index
        logger.debug(f"保存当前有效索引: {index}")

        # 发送当前工作流变化信号
        if index in self.tab_to_task:
            task_id = self.tab_to_task[index]
            self._activate_current_task_session()
            logger.debug(f"切换到任务: task_id={task_id}")
            self.current_workflow_changed.emit(task_id)
        else:
            logger.debug(f"索引 {index} 不在 tab_to_task 映射中")

    def _on_tab_moved(self, from_index: int, to_index: int):
        """
        标签页移动事件处理（拖动排序后触发）

        Args:
            from_index: 原始索引
            to_index: 移动后的索引
        """
        logger.info(f"标签页移动: {from_index} -> {to_index}")

        # 重建映射关系
        self._rebuild_mappings()

        logger.info("标签页移动后，映射关系已更新")

    def _show_tab_context_menu(self, pos: QPoint):
        """显示标签页右键菜单"""
        tab_index = self.tabBar().tabAt(pos)

        # "+"标签页不显示菜单
        if tab_index == self.count() - 1 or tab_index not in self.tab_to_task:
            return

        task_id = self.tab_to_task[tab_index]
        task = self.task_manager.get_task(task_id)

        if not task:
            return

        # 创建右键菜单
        menu = apply_unified_menu_style(QMenu(self), frameless=True)

        # 保存（无图标）
        save_action = menu.addAction("保存")
        save_action.setEnabled(task.modified)
        save_action.triggered.connect(lambda: self._save_task(task_id))

        # 另存为（无图标）
        save_as_action = menu.addAction("另存为...")
        save_as_action.triggered.connect(lambda: self._save_task_as(task_id))

        # 重命名（无图标）
        rename_action = menu.addAction("重命名")
        rename_action.triggered.connect(lambda: self._rename_task(task_id))

        # 分隔线
        menu.addSeparator()

        # 关闭（无图标）
        close_action = menu.addAction("关闭")
        close_action.triggered.connect(lambda: self._on_tab_close_requested(tab_index))

        # 关闭所有（无图标）
        close_all_action = menu.addAction("关闭所有")
        close_all_action.triggered.connect(self._close_all_tabs)

        # 显示菜单
        menu.exec(self.tabBar().mapToGlobal(pos))

    def _mark_task_modified(self, task_id: int):
        """标记任务为已修改 - 【性能优化】只更新状态，不序列化"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return

        # 【性能优化】只标记为已修改，不立即序列化
        # 序列化将在用户主动保存时进行
        task.modified = True
        self._update_tab_status(task_id)

    def _on_connection_changed(self, start_card):
        """连接变化时刷新参数面板（用于随机跳转等动态参数）

        注意：此方法现在主要用于处理非拖拽创建的连接变化
        拖拽创建连接时，workflow_view.py 的 mouseReleaseEvent 会直接刷新参数面板
        """
        if not start_card:
            return

        # 只处理随机跳转卡片
        if not hasattr(start_card, 'task_type') or start_card.task_type != '随机跳转':
            return

        # 检查参数面板是否正在显示这个卡片
        main_window = self.parent()
        if not main_window or not hasattr(main_window, 'parameter_panel'):
            return

        parameter_panel = main_window.parameter_panel
        if not hasattr(parameter_panel, 'current_card_id'):
            return

        # 如果参数面板正在显示这个卡片，更新连接数据
        if parameter_panel.current_card_id == start_card.card_id:
            # 获取当前工作流视图
            current_task_id = self.get_current_task_id()
            if current_task_id is None:
                return
            workflow_view = self.task_views.get(current_task_id)
            if not workflow_view:
                return

            # 重新收集随机跳转连接
            random_jump_connections = []
            for conn in getattr(workflow_view, 'connections', []):
                if (hasattr(conn, 'start_item') and hasattr(conn, 'end_item') and
                    hasattr(conn, 'line_type') and conn.start_item and
                    conn.start_item.card_id == start_card.card_id and
                    conn.line_type == 'random'):
                    target_card = conn.end_item
                    if target_card:
                        random_jump_connections.append({
                            'card_id': target_card.card_id,
                            'task_type': target_card.task_type
                        })

            # 更新参数面板的连接数据并刷新
            parameter_panel.current_parameters['_random_connections'] = random_jump_connections
            parameter_panel._refresh_conditional_widgets()

    def _on_connection_deleted_for_random_jump(self, conn, task_id: int):
        """处理连接删除时的随机跳转参数面板更新

        注意：connection_deleted信号发出时，conn.start_item已被清空
        所以需要检查当前显示的参数面板是否是随机跳转卡片
        """
        # 检查参数面板是否正在显示随机跳转卡片
        main_window = self.parent()
        if not main_window or not hasattr(main_window, 'parameter_panel'):
            return

        parameter_panel = main_window.parameter_panel
        if not hasattr(parameter_panel, 'current_card_id') or not hasattr(parameter_panel, 'current_task_type'):
            return

        # 只处理随机跳转卡片
        if parameter_panel.current_task_type != '随机跳转':
            return

        # 获取当前工作流视图
        workflow_view = self.task_views.get(task_id)
        if not workflow_view:
            return

        current_card_id = parameter_panel.current_card_id

        # 重新收集该随机跳转卡片的所有连接
        random_jump_connections = []
        for c in getattr(workflow_view, 'connections', []):
            if (hasattr(c, 'start_item') and hasattr(c, 'end_item') and
                hasattr(c, 'line_type') and c.start_item and
                c.start_item.card_id == current_card_id and
                c.line_type == 'random'):
                target_card = c.end_item
                if target_card:
                    random_jump_connections.append({
                        'card_id': target_card.card_id,
                        'task_type': target_card.task_type
                    })

        # 更新参数面板的连接数据并刷新
        parameter_panel.current_parameters['_random_connections'] = random_jump_connections
        parameter_panel._refresh_conditional_widgets()

    def _update_tab_status(self, task_id: int):
        """更新标签页状态显示"""
        if task_id not in self.task_to_tab:
            return

        tab_index = self.task_to_tab[task_id]
        task = self.task_manager.get_task(task_id)

        if not task:
            return

        # 构建标签页文本
        name = _strip_workflow_suffix(task.name)

        # 添加修改标记
        modified_mark = '*' if task.modified else ''

        # 设置标签页文本（不使用图标和颜色）
        tab_text = f"{name}{modified_mark}"
        self.setTabText(tab_index, tab_text)

        # 设置标签页工具提示
        tooltip = f"任务: {task.name}\n路径: {task.filepath}\n状态: {task.status}"
        self.setTabToolTip(tab_index, tooltip)

    def _persist_task(self, task, *, old_filepath: str | None = None, workflow_data=None) -> bool:
        previous = old_filepath if old_filepath is not None else (task.filepath or "")
        if not task.save_and_backup(workflow_data=workflow_data):
            return False
        new_filepath = task.filepath or ""
        if previous and new_filepath:
            from task_workflow.workspace import favorite_path_key

            if favorite_path_key(previous) != favorite_path_key(new_filepath):
                self.workflow_renamed.emit(task.task_id, previous, new_filepath, task.name)
        return True

    def _save_task(self, task_id: int):
        """保存任务"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return

        # 更新任务的工作流数据
        if task_id in self.task_views:
                workflow_view = self.task_views[task_id]
                # 使用 serialize_workflow() 而不是 save_workflow(filepath)
                workflow_data = workflow_view.serialize_workflow()
                task.update_workflow_data(workflow_data)

        # 如果任务没有文件路径（新建的空白工作流），使用另存为
        if not task.filepath:
            logger.info(f"任务 '{task.name}' 没有保存路径，使用另存为")
            self._save_task_as(task_id)
            return

        if self._persist_task(task):
            QMessageBox.information(self, "保存成功", f"任务 '{task.name}' 已保存")
            self._update_tab_status(task_id)
        else:
            QMessageBox.warning(self, "保存失败", f"无法保存任务 '{task.name}'")

    def _save_task_as(self, task_id: int):
        """任务另存为"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        old_filepath = task.filepath or ""
        old_name = task.name

        # 更新任务的工作流数据
        if task_id in self.task_views:
            workflow_view = self.task_views[task_id]
            # 使用 serialize_workflow() 而不是 save_workflow(filepath)
            workflow_data = workflow_view.serialize_workflow()
            task.update_workflow_data(workflow_data)

        # 选择保存路径
        from utils.app_paths import get_workflows_dir
        default_save_path = task.filepath or os.path.join(get_workflows_dir(), task.name or "workflow.lca")
        default_save_path = os.path.splitext(default_save_path)[0] + ".lca"
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "另存为",
            default_save_path,
            LCA_SAVE_FILTER
        )

        if not filepath:
            return
        if not filepath.lower().endswith(".lca"):
            filepath += ".lca"

        # 更新任务文件路径
        task.filepath = filepath
        task.name = os.path.basename(filepath)

        if self._persist_task(task, old_filepath=old_filepath):
            QMessageBox.information(self, "保存成功", f"任务已另存为: {filepath}")
            self._update_tab_status(task_id)
        else:
            task.filepath = old_filepath
            task.name = old_name
            QMessageBox.warning(self, "保存失败", f"无法保存到: {filepath}")

    def _rename_task(self, task_id: int):
        """重命名任务"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        old_filepath = task.filepath or ""

        from PySide6.QtWidgets import QInputDialog

        # 获取当前名称（去掉工作流文件后缀）
        current_name = _strip_workflow_suffix(task.name)

        new_name, ok = QInputDialog.getText(
            self,
            "重命名任务",
            "请输入新名称:",
            text=current_name
        )

        requested_name = _strip_workflow_suffix(Path(str(new_name or "").strip()).name)
        if ok and requested_name and requested_name != current_name:
            # 更新任务名称
            old_name = task.name
            task.name = requested_name

            # 如果有文件路径，更新文件路径（保持目录不变，只改文件名）
            if task.filepath:
                old_path = Path(task.filepath)
                suffix = old_path.suffix.lower()
                if suffix not in _WORKFLOW_FILE_SUFFIXES:
                    suffix = ".json"
                new_filename = f"{requested_name}{suffix}"
                new_filepath = str(old_path.with_name(new_filename))

                # 重命名文件
                try:
                    if os.path.exists(task.filepath):
                        os.rename(task.filepath, new_filepath)
                        task.filepath = new_filepath
                        task.name = new_filename
                        logger.info(f"文件已重命名: {task.filepath} -> {new_filepath}")
                    else:
                        # 文件不存在（可能是新建的未保存工作流），只更新内存中的名称
                        task.filepath = new_filepath
                        task.name = new_filename
                        logger.info(f"更新文件路径（文件不存在）: {new_filepath}")
                except OSError as e:
                    logger.error(f"重命名文件失败: {e}")
                    QMessageBox.warning(self, "重命名失败", f"无法重命名文件: {e}")
                    task.name = old_name  # 恢复旧名称
                    return
            else:
                # 没有文件路径（新建的空白工作流），只更新名称
                task.name = requested_name

            task_session = getattr(task, "lca_session", None)
            if task_session is not None and old_filepath.lower().endswith(".lca"):
                from app_core.lca_format.session import (
                    activate,
                    clear_path,
                    get_active,
                    register,
                )

                was_active = get_active() is task_session
                clear_path(old_filepath)
                register(task.filepath, task_session)
                task.lca_session_path = os.path.abspath(task.filepath)
                if was_active:
                    activate(task.filepath)

            # 标记为已修改
            task.modified = True

            # 更新标签页显示
            self._update_tab_status(task_id)

            # 发送重命名信号
            self.workflow_renamed.emit(task_id, old_filepath, task.filepath or "", requested_name)
            logger.info(f"任务已重命名: {task_id} -> '{requested_name}'")

    def _close_other_tabs(self, keep_index: int):
        """关闭除指定索引外的所有标签页"""
        # 从后往前关闭（避免索引变化）
        for i in range(self.count() - 2, -1, -1):  # 不包括"+"标签页
            if i != keep_index:
                self._on_tab_close_requested(i)

    def _close_all_tabs(self):
        """关闭所有标签页"""
        # 从后往前关闭（避免索引变化）
        for i in range(self.count() - 2, -1, -1):  # 不包括"+"标签页
            self._on_tab_close_requested(i)

    def _rebuild_mappings(self):
        """重新建立映射关系（标签页索引可能变化）"""
        self.tab_to_task.clear()
        self.task_to_tab.clear()

        for i in range(self.count() - 1):  # 不包括"+"标签页
            widget = self.widget(i)
            # 通过widget找到对应的task_id
            for task_id, view in self.task_views.items():
                if view == widget:
                    self.tab_to_task[i] = task_id
                    self.task_to_tab[task_id] = i
                    break

    def get_current_task_id(self) -> Optional[int]:
        """获取当前选中的任务ID"""
        index = self.currentIndex()
        task_id = self.tab_to_task.get(index)
        if task_id is not None:
            return task_id

        current_widget = self.currentWidget()
        if current_widget is not None:
            for mapped_task_id, workflow_view in self.task_views.items():
                if workflow_view == current_widget:
                    self.tab_to_task[index] = mapped_task_id
                    self.task_to_tab[mapped_task_id] = index
                    return mapped_task_id

        self._rebuild_mappings()
        return self.tab_to_task.get(index)

    def get_current_workflow_view(self) -> Optional[WorkflowView]:
        """获取当前选中的WorkflowView"""
        task_id = self.get_current_task_id()
        if task_id:
            return self.task_views.get(task_id)
        return None

    def set_editing_enabled(self, enabled: bool):
        """设置是否允许编辑工作流（运行时禁止编辑）"""
        for workflow_view in self.task_views.values():
            workflow_view.editing_enabled = enabled
        logger.info(f"工作流编辑{'已启用' if enabled else '已禁用'}")

    def has_unsaved_changes(self) -> bool:
        """检查是否有未保存的更改"""
        for task in self.task_manager.get_all_tasks():
            if task.modified:
                return True
        return False

    def _is_backup_path(self, filepath: str) -> bool:
        if not filepath:
            return False
        try:
            normalized = os.path.normcase(os.path.normpath(filepath))
        except Exception:
            return False
        parts = [part for part in normalized.replace("/", os.sep).split(os.sep) if part]
        backup_dir_names = {"backups", "backup", "\u5907\u4efd"}
        return any(part in backup_dir_names for part in parts)

    def _save_to_recent_workflows(self, filepath: str):
        """保存工作流路径到最近打开列表"""
        try:
            if self._is_backup_path(filepath):
                logger.info(f"已跳过备份目录中的工作流: {filepath}")
                return

            config_path = get_config_path()

            if not os.path.exists(config_path):
                logger.warning(f"配置文件不存在: {config_path}")
                return

            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            recent_workflows = config.get('recent_workflows', [])

            # 移除已存在的相同路径
            if filepath in recent_workflows:
                recent_workflows.remove(filepath)

            # 添加到列表开头
            recent_workflows.insert(0, filepath)

            # 限制最多保存10个
            recent_workflows = recent_workflows[:10]

            config['recent_workflows'] = recent_workflows

            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)

            logger.info(f"已保存到最近打开列表: {filepath}")

        except Exception as e:
            logger.error(f"保存最近打开列表失败: {e}")

    def save_current_workflows_to_recent(self):
        """保存当前所有打开的工作流到最近打开列表"""
        try:
            # 获取所有已打开的工作流文件路径(按标签页顺序)
            current_workflows = []
            for tab_index in range(self.count()):
                # 跳过"+"导入标签页
                if self.tabBar().tabText(tab_index) == "+":
                    continue

                task_id = self.tab_to_task.get(tab_index)
                if task_id is not None:
                    task = self.task_manager.get_task(task_id)
                    if task and hasattr(task, 'filepath') and task.filepath:
                        if self._is_backup_path(task.filepath):
                            continue
                        current_workflows.append(task.filepath)

            if not current_workflows:
                logger.info("当前没有打开的工作流需要保存")
                return

            config_path = get_config_path()

            if not os.path.exists(config_path):
                logger.warning(f"配置文件不存在: {config_path}")
                return

            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # 获取现有的最近工作流列表
            recent_workflows = config.get('recent_workflows', [])

            # 先从现有列表中移除所有当前打开的工作流
            for filepath in current_workflows:
                if filepath in recent_workflows:
                    recent_workflows.remove(filepath)

            # 将当前打开的工作流添加到列表开头(保持标签页顺序)
            # 最后打开的在最前面
            for filepath in reversed(current_workflows):
                recent_workflows.insert(0, filepath)

            # 限制最多保存10个
            recent_workflows = recent_workflows[:10]

            config['recent_workflows'] = recent_workflows

            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)

            logger.info(f"已保存 {len(current_workflows)} 个当前打开的工作流到最近列表")

        except Exception as e:
            logger.error(f"保存当前工作流列表失败: {e}")

    def _remove_from_recent_workflows(self, filepath: str):
        """从最近打开列表移除工作流路径"""
        try:
            config_path = get_config_path()

            if not os.path.exists(config_path):
                return

            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            recent_workflows = config.get('recent_workflows', [])

            # 移除路径
            if filepath in recent_workflows:
                recent_workflows.remove(filepath)
                config['recent_workflows'] = recent_workflows

                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=4, ensure_ascii=False)

                logger.info(f"已从最近打开列表移除: {filepath}")

        except Exception as e:
            logger.error(f"从最近打开列表移除失败: {e}")

    def load_recent_workflows(self) -> List[str]:
        """加载最近打开的工作流列表"""
        config_path = get_config_path()
        if not os.path.exists(config_path):
            return []

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        if not isinstance(config, dict):
            raise TypeError("配置文件根节点必须是字典")

        recent_workflows = config.get('recent_workflows', [])
        if not isinstance(recent_workflows, list):
            raise TypeError("recent_workflows 必须是列表")

        normalized_paths = []
        seen_paths = set()
        for index, filepath in enumerate(recent_workflows):
            if not isinstance(filepath, str) or not filepath.strip():
                raise TypeError(f"recent_workflows[{index}] 必须是非空字符串")
            if self._is_backup_path(filepath):
                raise ValueError(f"最近工作流不能指向备份目录: {filepath}")
            absolute_path = os.path.abspath(os.path.normpath(filepath))
            if not os.path.isfile(absolute_path):
                raise FileNotFoundError(f"最近工作流不存在: {absolute_path}")
            dedup_key = os.path.normcase(absolute_path)
            if dedup_key in seen_paths:
                raise ValueError(f"最近工作流存在重复路径: {absolute_path}")
            seen_paths.add(dedup_key)
            normalized_paths.append(absolute_path)
        return normalized_paths

    def auto_load_recent_workflows(self):
        """自动加载最近打开的工作流（保持顺序）"""
        try:
            recent_workflows = self.load_recent_workflows()

            if not recent_workflows:
                logger.info("没有最近打开的工作流")
                return

            logger.info(f"开始自动加载 {len(recent_workflows)} 个最近打开的工作流")

            # 整批先校验，防止格式错误导致只加载一部分标签页。
            for filepath in recent_workflows:
                workflow_data = load_workflow_file(filepath)
                self._validate_workflow_import_data(workflow_data, filepath)

            # 设置自动加载标志，防止重复记录
            self._is_auto_loading = True

            for filepath in recent_workflows:
                task_id = self.import_workflow(filepath)
                if task_id is None:
                    raise RuntimeError(f"自动加载工作流失败: {filepath}")

            logger.info("最近打开的工作流加载完成")

        except Exception as e:
            logger.error(f"自动加载工作流已停止: {e}")
            QMessageBox.critical(self, "自动加载失败", str(e))
        finally:
            self._is_auto_loading = False

    def wheelEvent(self, event: QWheelEvent):
        """
        处理鼠标滚轮事件，用于滚动标签栏

        当标签页过多时，可以使用滚轮左右滚动标签栏
        """
        # 获取滚轮滚动方向
        delta = event.angleDelta().y()

        # 获取标签栏
        tab_bar = self.tabBar()

        # 判断是否需要滚动（标签页数量超过可视区域）
        if tab_bar.count() > 1:
            # 向上滚动（远离用户）= 向右移动标签栏
            # 向下滚动（靠近用户）= 向左移动标签栏
            if delta > 0:
                # 向上滚，显示左边的标签
                current_index = self.currentIndex()
                if current_index > 0:
                    self.setCurrentIndex(current_index - 1)
            else:
                # 向下滚，显示右边的标签
                current_index = self.currentIndex()
                # 排除最后一个"+"标签页
                if current_index < self.count() - 2:
                    self.setCurrentIndex(current_index + 1)

        # 接受事件，防止传递给父控件
        event.accept()

    def set_all_grid_enabled(self, enabled: bool):
        """设置所有WorkflowView的网格启用状态"""
        for workflow_view in self.task_views.values():
            workflow_view.set_grid_enabled(enabled)

    def set_all_card_snap_enabled(self, enabled: bool):
        """设置所有WorkflowView的卡片吸附启用状态。"""
        for workflow_view in self.task_views.values():
            workflow_view.set_card_snap_enabled(enabled)
