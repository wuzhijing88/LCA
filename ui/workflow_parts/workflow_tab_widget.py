#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工作流标签页控件
支持多任务标签页管理，每个标签页对应一个工作流任务
"""

import logging
import os
import json
from utils.app_paths import get_config_path
from typing import Dict, Optional, List, Any
from PySide6.QtWidgets import (QTabWidget, QTabBar, QWidget, QPushButton,
                               QFileDialog, QMessageBox, QMenu, QDialog)
from PySide6.QtCore import Qt, Signal, QPoint, Slot, QSettings
from PySide6.QtGui import QIcon, QAction, QWheelEvent, QColor

from utils.sub_workflow_path import get_workflow_base_dir, resolve_sub_workflow_path
from ..workflow_parts.workflow_view import WorkflowView
from ..workflow_parts.workflow_task_manager import WorkflowTaskManager
from ..system_parts.menu_style import apply_unified_menu_style
from task_workflow.workflow_vars import pick_variables_override
from task_workflow.runtime_var_store import (
    STORAGE_KIND,
    build_task_key,
    is_storage_manifest,
    load_runtime_snapshot,
    save_runtime_snapshot,
)

logger = logging.getLogger(__name__)

_VIEW_STATE_SETTINGS_KEY = "workflow_view_states_v1"


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
        try:
            return os.path.normcase(os.path.abspath(str(filepath)))
        except Exception:
            return str(filepath).strip().lower()

    def _normalize_view_state_payload(self, payload: Any) -> Optional[Dict[str, List[float]]]:
        """校验并标准化画布视图状态结构。"""
        if not isinstance(payload, dict):
            return None

        transform = payload.get("view_transform")
        center = payload.get("view_center")
        if not isinstance(transform, (list, tuple)) or len(transform) != 9:
            return None
        if not isinstance(center, (list, tuple)) or len(center) != 2:
            return None

        try:
            normalized_transform = [float(value) for value in transform]
            normalized_center = [float(value) for value in center]
        except (TypeError, ValueError):
            return None

        return {
            "view_transform": normalized_transform,
            "view_center": normalized_center,
        }

    def _load_persisted_view_states(self) -> Dict[str, Dict[str, List[float]]]:
        """从 QSettings 加载画布视图持久化数据。"""
        normalized: Dict[str, Dict[str, List[float]]] = {}
        try:
            settings = QSettings("LCA", "LCA")
            raw_payload = settings.value(_VIEW_STATE_SETTINGS_KEY, "")
            parsed_payload: Dict[str, Any] = {}
            if isinstance(raw_payload, str):
                raw_payload = raw_payload.strip()
                if raw_payload:
                    parsed_payload = json.loads(raw_payload)
            elif isinstance(raw_payload, dict):
                parsed_payload = raw_payload

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
            settings = QSettings("LCA", "LCA")
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
                return

        previous_index = restore_state.get("index", -1)
        try:
            previous_index = int(previous_index)
        except (TypeError, ValueError):
            previous_index = -1

        if 0 <= previous_index < self.count():
            self.setCurrentIndex(previous_index)

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

        # 检查是否有工作流正在执行
        from PySide6.QtWidgets import QApplication, QMessageBox
        main_window = QApplication.activeWindow()
        if main_window and hasattr(main_window, '_is_any_workflow_running'):
            if main_window._is_any_workflow_running():
                # 在底部状态栏显示警告
                if hasattr(main_window, 'step_detail_label'):
                    main_window.step_detail_label.setText("【警告】工作流正在执行中，无法导入新工作流")
                    main_window.step_detail_label.setStyleSheet("""
                        #stepDetailLabel {
                            background-color: rgba(180, 180, 180, 180);
                            color: #FF0000;
                            font-weight: bold;
                            border-radius: 5px;
                            padding: 8px;
                        }
                    """)
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(3000, lambda: main_window.step_detail_label.setText("任务执行中..."))

                logger.warning("工作流正在执行，禁止导入新工作流")
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
                    logger.info(f"   使用self作为父控件")
                    parent_widget = self

                # 改用 getOpenFileNames 支持多选
                from utils.app_paths import get_workflows_dir
                filepaths, _ = QFileDialog.getOpenFileNames(
                    parent_widget,
                    "导入工作流（可多选）",
                    get_workflows_dir(),
                    "JSON文件 (*.json);;所有文件 (*)"
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
        if not os.path.exists(filepath):
            QMessageBox.critical(self, "导入失败", f"文件不存在: {filepath}")
            return None

        try:
            # 加载工作流数据
            import json
            with open(filepath, 'r', encoding='utf-8') as f:
                workflow_data = json.load(f)
            workflow_data = self._sanitize_legacy_variables_on_import(workflow_data, filepath)

            # 验证数据格式
            if 'cards' not in workflow_data or not isinstance(workflow_data.get('cards'), list):
                QMessageBox.critical(self, "导入失败", "无效的工作流文件格式")
                return None

            # 生成任务名称
            name = os.path.basename(filepath)

            # 添加任务到管理器
            previous_activate_flag = self._activate_new_tab_on_add
            self._activate_new_tab_on_add = bool(activate_tab)
            try:
                task_id = self.task_manager.add_task(name, filepath, workflow_data)
            finally:
                self._activate_new_tab_on_add = previous_activate_flag
            # 加载跳转配置（如果存在）
            task = self.task_manager.get_task(task_id)
            if task and 'jump_config' in workflow_data:
                jump_config = workflow_data['jump_config']
                task.jump_enabled = jump_config.get('enabled', True)
                task.jump_rules = jump_config.get('rules', {}).copy()
                task.jump_delay = jump_config.get('delay', 0)
                task.first_execute = jump_config.get('first_execute', False)
                logger.info(f"已加载跳转配置: enabled={task.jump_enabled}, rules={task.jump_rules}, delay={task.jump_delay}秒, first_execute={task.first_execute}")

            # 加载窗口绑定配置（如果存在）
            if task and 'window_binding' in workflow_data:
                window_binding = workflow_data['window_binding']
                task.bound_window_id = window_binding.get('bound_window_id')
                task.target_window_title = window_binding.get('target_window_title', '')
                task.target_hwnd = window_binding.get('target_hwnd')

                # 如果保存的句柄有效,尝试验证并重新绑定
                if task.target_hwnd:
                    try:
                        import win32gui
                        if win32gui.IsWindow(task.target_hwnd):
                            logger.info(f"已加载窗口绑定: '{task.target_window_title}' (HWND: {task.target_hwnd})")
                        else:
                            logger.warning(f"保存的窗口句柄 {task.target_hwnd} 已失效,需要重新绑定")
                            task.target_hwnd = None
                    except Exception as e:
                        logger.warning(f"验证窗口句柄失败: {e}")
                        task.target_hwnd = None

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

    def _get_current_workflow_filepath(self) -> Optional[str]:
        task_id = self.get_current_task_id()
        if task_id is None:
            return None
        task = self.task_manager.get_task(task_id)
        return getattr(task, "filepath", None) if task else None

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
        resolved_filepath = resolve_sub_workflow_path(filepath, parent_workflow_file=parent_file)
        if not resolved_filepath:
            base_dir = get_workflow_base_dir(parent_file)
            extra_hint = f"\n\n已尝试主流程目录:\n{base_dir}" if base_dir else ""
            QMessageBox.warning(self, "打开失败", f"文件不存在:\n{filepath}{extra_hint}")
            return None

        if os.path.normcase(os.path.normpath(filepath)) != os.path.normcase(os.path.normpath(resolved_filepath)):
            logger.info(f"[子工作流] 已智能修正路径: {filepath} -> {resolved_filepath}")
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
            import json
            with open(filepath, 'r', encoding='utf-8') as f:
                workflow_data = json.load(f)
            workflow_data = self._sanitize_legacy_variables_on_import(workflow_data, filepath)

            # 验证数据格式
            if 'cards' not in workflow_data or not isinstance(workflow_data.get('cards'), list):
                # 检查是否是 .module 格式
                if 'workflow' in workflow_data:
                    workflow_data = workflow_data['workflow']
                else:
                    QMessageBox.critical(self, "打开失败", "无效的工作流文件格式")
                    return None

            # 生成标签页名称（带子流程前缀）
            base_name = os.path.basename(filepath)
            name = f"子流程:{base_name}"

            # 添加任务到管理器
            task_id = self.task_manager.add_task(name, filepath, workflow_data)

            # 标记为子工作流（可选，用于后续识别）
            task = self.task_manager.get_task(task_id)
            if task:
                task.is_sub_workflow = True

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
            # 如果没有提供名称，使用默认名称
            if not name:
                # 生成默认名称：未命名工作流1, 未命名工作流2, ...
                count = 1
                while True:
                    name = f"未命名工作流{count}"
                    # 检查是否已存在同名任务
                    exists = False
                    for task in self.task_manager.get_all_tasks():
                        if task.name == name or task.name == f"{name}.json":
                            exists = True
                            break
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
            from utils.app_paths import get_workflows_dir
            default_filepath = os.path.join(get_workflows_dir(), f"{name}.json")
            task_id = self.task_manager.add_task(name, default_filepath, workflow_data)
            self.workflow_imported.emit(task_id)

            return task_id

        except Exception as e:
            logger.error(f"创建空白工作流失败: {e}", exc_info=True)
            QMessageBox.critical(self, "创建失败", f"创建空白工作流失败:\n{e}")
            return None

    def _sanitize_legacy_variables_on_import(self, workflow_data: dict, filepath: str) -> dict:
        """导入工作流时清理旧版内嵌变量，并回写文件。"""
        if not isinstance(workflow_data, dict):
            return workflow_data

        sanitized = False

        def _clear_legacy_variables(container: dict, scope: str) -> None:
            nonlocal sanitized
            if not isinstance(container, dict):
                return
            if "variables" not in container:
                return
            if is_storage_manifest(container.get("variables")):
                return
            container.pop("variables", None)
            sanitized = True
            logger.info("检测到旧版工作流变量并已清空: file=%s, scope=%s", filepath, scope)

        # 标准工作流格式
        _clear_legacy_variables(workflow_data, "root")

        # 模块封装格式（workflow 内嵌）
        nested_workflow = workflow_data.get("workflow")
        if isinstance(nested_workflow, dict):
            _clear_legacy_variables(nested_workflow, "workflow")

        if sanitized and filepath:
            try:
                temp_path = f"{filepath}.tmp_sanitize_vars"
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(workflow_data, f, ensure_ascii=False, indent=2)
                os.replace(temp_path, filepath)
                logger.info("旧版内嵌变量清理结果已回写文件: %s", filepath)
            except Exception as save_exc:
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except Exception:
                    pass
                logger.warning("回写清理后的工作流文件失败: file=%s, error=%s", filepath, save_exc)

        return workflow_data

    def _normalize_runtime_manifest_for_task(self, task) -> None:
        """自愈历史 runtime manifest 的临时 task_key，统一迁移到稳定 path task_key。"""
        if task is None or not isinstance(getattr(task, "workflow_data", None), dict):
            return

        variables_data = task.workflow_data.get("variables")
        if not is_storage_manifest(variables_data):
            return

        stable_task_key = build_task_key(
            filepath=getattr(task, "filepath", None),
            task_id=getattr(task, "task_id", None),
            task_name=getattr(task, "name", None),
        )
        if not stable_task_key:
            return

        manifest_task_key = str(variables_data.get("task_key") or "").strip()
        if manifest_task_key == stable_task_key:
            return

        try:
            source_vars, source_sources = ({}, {})
            if manifest_task_key:
                source_vars, source_sources = load_runtime_snapshot(manifest_task_key)
            target_vars, _ = load_runtime_snapshot(stable_task_key)

            if source_vars and not target_vars:
                save_runtime_snapshot(
                    stable_task_key,
                    {
                        "global_vars": source_vars,
                        "var_sources": source_sources,
                    },
                )
                target_vars = dict(source_vars)

            normalized_manifest = {
                "storage": STORAGE_KIND,
                "task_key": stable_task_key,
                "count": len(target_vars) if isinstance(target_vars, dict) else 0,
            }
            task.workflow_data["variables"] = normalized_manifest

            # 尽量回写修复后的 manifest，避免下次重启再次命中旧 task_key。
            if getattr(task, "filepath", None):
                try:
                    task.save(workflow_data=dict(task.workflow_data))
                except Exception as save_exc:
                    logger.warning(f"回写修复后的变量标记失败: {save_exc}")

            logger.info(
                "已迁移工作流变量 task_key: task_id=%s, old=%s, new=%s",
                getattr(task, "task_id", None),
                manifest_task_key or "<empty>",
                stable_task_key,
            )
        except Exception as exc:
            logger.warning(f"迁移工作流变量 task_key 失败: {exc}")

    def _on_task_added(self, task_id: int):
        """任务添加回调"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return

        # 修复历史文件里使用 session task_key 的变量标记，避免重启后变量丢失。
        self._normalize_runtime_manifest_for_task(task)

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

        logger.info(f"WorkflowView创建完成:")
        logger.info(f"   dragMode: {workflow_view.dragMode()}")
        logger.info(f"   interactive: {workflow_view.isInteractive()}")
        logger.info(f"   enabled: {workflow_view.isEnabled()}")
        logger.info(f"   focusPolicy: {workflow_view.focusPolicy()}")

        # 加载工作流数据（优先应用退出时持久化的视图状态）
        workflow_data_for_load = self._get_workflow_data_with_persisted_view(task)
        workflow_view.load_workflow(workflow_data_for_load)

        # 加载后再次确保拖拽模式正确（加载可能会改变设置）
        workflow_view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        logger.info(f"   加载后dragMode: {workflow_view.dragMode()}")

        # 同步工作流变量快照到上下文
        try:
            from task_workflow.workflow_vars import update_context_from_variables
            variables_data = None
            if isinstance(task.workflow_data, dict):
                variables_data = task.workflow_data.get("variables")
            update_context_from_variables(task_id, variables_data)
        except Exception as exc:
            logger.warning(f"同步工作流变量上下文失败: {exc}")

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

        logger.info(f"映射关系重建完成:")
        logger.info(f"   tab_to_task: {self.tab_to_task}")
        logger.info(f"   task_to_tab: {self.task_to_tab}")

        # 切换到新标签页
        if self._activate_new_tab_on_add:
            self.setCurrentIndex(tab_index)

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

        if task_id not in self.task_to_tab:
            logger.warning(f"尝试删除不存在的任务: task_id={task_id}")
            return

        try:
            from task_workflow.workflow_vars import clear_context_for_task
            clear_context_for_task(task_id)
        except Exception as exc:
            logger.warning(f"清理工作流变量上下文失败: {exc}")

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
        logger.debug(f"映射关系已重建")

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

                # 关闭标签页时主动清理全局连线动画注册，避免残留强引用。
                try:
                    from ..workflow_parts.connection_line import _animated_lines, _animated_lines_lock, _unregister_animated_line
                    lines_to_cleanup = []
                    with _animated_lines_lock:
                        for line in list(_animated_lines):
                            if line is None:
                                continue

                            try:
                                line_scene = line.scene()
                            except RuntimeError:
                                line_scene = None
                            except Exception:
                                line_scene = None

                            if scene is not None and line_scene is scene:
                                lines_to_cleanup.append(line)

                    for line in lines_to_cleanup:
                        try:
                            if hasattr(line, "cleanup"):
                                line.cleanup()
                            else:
                                _unregister_animated_line(line)
                        except Exception:
                            _unregister_animated_line(line)
                except Exception as exc:
                    logger.warning(f"清理全局连线动画注册失败: {exc}")

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
                        scene.selectionChanged.disconnect()
                    except Exception:
                        pass
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

    def _on_tab_close_requested(self, index: int):
        """标签页关闭请求"""
        # "+"标签页不可关闭
        if index == self.count() - 1:
            return

        if index not in self.tab_to_task:
            return

        task_id = self.tab_to_task[index]
        task = self.task_manager.get_task(task_id)

        if not task:
            return

        # 检查任务是否正在运行/暂停/停止中（线程未完全退出前都视为活动态）
        thread_running = False
        try:
            thread = getattr(task, "executor_thread", None)
            thread_running = bool(thread and thread.isRunning())
        except Exception:
            thread_running = False
        status = str(getattr(task, "status", "") or "").strip()
        status_lower = status.lower()
        stop_reason = str(getattr(task, "stop_reason", "") or "").strip()
        stop_reason_lower = stop_reason.lower()
        active_status_values = {
            "running", "paused", "starting", "stopping",
            "运行中", "暂停", "暂停中", "启动中", "正在启动", "停止中", "正在停止",
        }
        terminal_status_values = {
            "idle", "completed", "failed", "stopped",
            "空闲", "已完成", "完成", "失败", "已停止", "停止",
        }
        is_active_status = status in active_status_values or status_lower in active_status_values
        is_terminal_status = status in terminal_status_values or status_lower in terminal_status_values
        is_user_stopping = (
            stop_reason in ("stopped", "已停止", "用户停止")
            or stop_reason_lower == "stopped"
            or status in ("stopped", "stopping", "已停止", "停止中", "正在停止")
        )

        if is_active_status or thread_running:
            # 已处于终态（完成/失败/已停止）时，即使线程仍在回收，也不再误提示“仍在执行”。
            if thread_running and (is_user_stopping or is_terminal_status):
                logger.info(
                    "任务 '%s' 已是终态但线程仍在退出中，跳过执行确认并继续关闭流程",
                    task.name,
                )
                try:
                    task.stop()
                except Exception:
                    pass
            else:
                reply = QMessageBox.question(
                    self,
                    "确认关闭",
                    f"任务 '{task.name}' 仍在执行，确定要关闭吗？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )

                if reply == QMessageBox.StandardButton.No:
                    return

                # 停止任务
                task.stop()

        # 检查是否有未保存的更改
        if task.modified:
            reply = QMessageBox.question(
                self,
                "保存更改",
                f"任务 '{task.name}' 有未保存的更改，是否保存？",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel
            )

            if reply == QMessageBox.StandardButton.Save:
                # 更新工作流数据
                if task_id in self.task_views:
                    workflow_view = self.task_views[task_id]
                    current_task_id = self.get_current_task_id()
                    variables_override = pick_variables_override(
                        target_task_id=task_id,
                        current_task_id=current_task_id,
                        task_workflow_data=task.workflow_data,
                    )
                    workflow_data = workflow_view.serialize_workflow(variables_override=variables_override)
                    task.update_workflow_data(workflow_data)

                # 如果任务没有文件路径（新建的空白工作流），使用另存为
                if not task.filepath:
                    self._save_task_as(task_id)
                    # 检查是否保存成功（用户可能取消）
                    if not task.filepath:
                        logger.info("用户取消了另存为，不关闭标签页")
                        return
                else:
                    if not task.save():
                        QMessageBox.warning(self, "保存失败", f"无法保存任务 '{task.name}'")
                        return
            elif reply == QMessageBox.StandardButton.Cancel:
                return

        # 从最近打开列表移除
        if task.filepath:
            self._remove_from_recent_workflows(task.filepath)

        # 删除任务（仅在线程退出后会真正删除）
        if self.task_manager.remove_task(task_id):
            self.workflow_closed.emit(task_id)
        else:
            logger.info(f"任务 '{task.name}' 仍在停止中，已延迟删除，稍后会自动关闭标签")

    def close_tab_silent(self, index: int):
        """静默关闭标签页（不弹出确认框）"""
        # "+"标签页不可关闭
        if index == self.count() - 1:
            return

        if index not in self.tab_to_task:
            return

        task_id = self.tab_to_task[index]
        task = self.task_manager.get_task(task_id)

        if not task:
            return

        # 如果任务仍在执行链路中，先停止
        thread_running = False
        try:
            thread = getattr(task, "executor_thread", None)
            thread_running = bool(thread and thread.isRunning())
        except Exception:
            thread_running = False
        status = str(getattr(task, "status", "") or "").strip()
        status_lower = status.lower()
        active_status_values = {
            "running", "paused", "starting", "stopping",
            "运行中", "暂停", "暂停中", "启动中", "正在启动", "停止中", "正在停止",
        }
        is_active_status = status in active_status_values or status_lower in active_status_values
        if is_active_status or thread_running:
            task.stop()

        # 从最近打开列表移除
        if task.filepath:
            self._remove_from_recent_workflows(task.filepath)

        # 删除任务（仅在线程退出后会真正删除）
        if self.task_manager.remove_task(task_id):
            self.workflow_closed.emit(task_id)

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

        logger.info(f"标签页移动后，映射关系已更新")

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
        name = task.name

        # 去掉文件后缀（如 .json）
        if '.' in name:
            name = os.path.splitext(name)[0]

        # 添加修改标记
        modified_mark = '*' if task.modified else ''

        # 设置标签页文本（不使用图标和颜色）
        tab_text = f"{name}{modified_mark}"
        self.setTabText(tab_index, tab_text)

        # 设置标签页工具提示
        tooltip = f"任务: {task.name}\n路径: {task.filepath}\n状态: {task.status}"
        self.setTabToolTip(tab_index, tooltip)

    def _save_task(self, task_id: int):
        """保存任务"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return

        # 更新任务的工作流数据
        if task_id in self.task_views:
                workflow_view = self.task_views[task_id]
                # 使用 serialize_workflow() 而不是 save_workflow(filepath)
                current_task_id = self.get_current_task_id()
                variables_override = pick_variables_override(
                    target_task_id=task_id,
                    current_task_id=current_task_id,
                    task_workflow_data=task.workflow_data,
                )
                workflow_data = workflow_view.serialize_workflow(variables_override=variables_override)
                task.update_workflow_data(workflow_data)

        # 如果任务没有文件路径（新建的空白工作流），使用另存为
        if not task.filepath:
            logger.info(f"任务 '{task.name}' 没有保存路径，使用另存为")
            self._save_task_as(task_id)
            return

        # 保存到文件
        if task.save():
            QMessageBox.information(self, "保存成功", f"任务 '{task.name}' 已保存")
            self._update_tab_status(task_id)
        else:
            QMessageBox.warning(self, "保存失败", f"无法保存任务 '{task.name}'")

    def _save_task_as(self, task_id: int):
        """任务另存为"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return

        # 更新任务的工作流数据
        if task_id in self.task_views:
            workflow_view = self.task_views[task_id]
            # 使用 serialize_workflow() 而不是 save_workflow(filepath)
            current_task_id = self.get_current_task_id()
            variables_override = pick_variables_override(
                target_task_id=task_id,
                current_task_id=current_task_id,
                task_workflow_data=task.workflow_data,
            )
            workflow_data = workflow_view.serialize_workflow(variables_override=variables_override)
            task.update_workflow_data(workflow_data)

        # 选择保存路径
        from utils.app_paths import get_workflows_dir
        default_save_path = task.filepath or os.path.join(get_workflows_dir(), task.name or "workflow.json")
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "另存为",
            default_save_path,
            "工作流文件 (*.json);;所有文件 (*)"
        )

        if not filepath:
            return

        # 更新任务文件路径
        task.filepath = filepath
        task.name = os.path.basename(filepath)

        # 保存到文件
        if task.save():
            QMessageBox.information(self, "保存成功", f"任务已另存为: {filepath}")
            self._update_tab_status(task_id)
        else:
            QMessageBox.warning(self, "保存失败", f"无法保存到: {filepath}")

    def _rename_task(self, task_id: int):
        """重命名任务"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return
        old_filepath = task.filepath or ""

        from PySide6.QtWidgets import QInputDialog

        # 获取当前名称（去掉.json后缀）
        current_name = task.name
        if current_name.endswith('.json'):
            current_name = current_name[:-5]

        new_name, ok = QInputDialog.getText(
            self,
            "重命名任务",
            "请输入新名称:",
            text=current_name
        )

        if ok and new_name and new_name != current_name:
            # 更新任务名称
            old_name = task.name
            task.name = new_name if not new_name.endswith('.json') else new_name

            # 如果有文件路径，更新文件路径（保持目录不变，只改文件名）
            if task.filepath:
                dir_path = os.path.dirname(task.filepath)
                # 确保新文件名有.json后缀
                new_filename = new_name if new_name.endswith('.json') else f"{new_name}.json"
                new_filepath = os.path.join(dir_path, new_filename)

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
                task.name = new_name

            # 标记为已修改
            task.modified = True

            # 更新标签页显示
            self._update_tab_status(task_id)

            # 发送重命名信号
            self.workflow_renamed.emit(task_id, old_filepath, task.filepath or "", new_name)
            logger.info(f"任务已重命名: {task_id} -> '{new_name}'")

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
        try:
            config_path = get_config_path()

            if not os.path.exists(config_path):
                return []

            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            recent_workflows = config.get('recent_workflows', [])

            # 过滤掉不存在的文件
            valid_workflows = [
                path for path in recent_workflows
                if os.path.exists(path) and not self._is_backup_path(path)
            ]

            # 如果有文件被过滤掉，更新配置
            if len(valid_workflows) != len(recent_workflows):
                config['recent_workflows'] = valid_workflows
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=4, ensure_ascii=False)
                logger.info(f"已清理无效或备份目录的工作流路径，保留 {len(valid_workflows)} 个")

            return valid_workflows

        except Exception as e:
            logger.error(f"加载最近打开列表失败: {e}")
            return []

    def auto_load_recent_workflows(self):
        """自动加载最近打开的工作流（保持顺序）"""
        try:
            recent_workflows = self.load_recent_workflows()

            if not recent_workflows:
                logger.info("没有最近打开的工作流")
                return

            logger.info(f"开始自动加载 {len(recent_workflows)} 个最近打开的工作流")

            # 设置自动加载标志，防止重复记录
            self._is_auto_loading = True

            for filepath in recent_workflows:
                try:
                    self.import_workflow(filepath)
                except Exception as e:
                    logger.error(f"自动加载工作流失败 {filepath}: {e}")

            # 恢复标志
            self._is_auto_loading = False

            logger.info("最近打开的工作流加载完成")

        except Exception as e:
            logger.error(f"自动加载工作流时出错: {e}")
            self._is_auto_loading = False

    def _auto_start_first_execute(self, task_id: int):
        """自动启动首个执行的工作流"""
        task = self.task_manager.get_task(task_id)
        if not task:
            logger.warning(f"无法找到任务 ID={task_id}")
            return

        if not task.first_execute:
            logger.info(f"任务 '{task.name}' 未标记为首个执行，跳过自动启动")
            return

        # 切换到对应的标签页
        tab_index = self.task_to_tab.get(task_id)
        if tab_index is not None:
            self.setCurrentIndex(tab_index)
            logger.info(f"已切换到标签页: {tab_index}")

        # 触发主窗口的执行按钮
        # 需要通过父窗口调用
        main_window = self.window()
        if hasattr(main_window, 'run_workflow'):
            logger.info(f"正在自动启动工作流: {task.name}")
            # 延迟一下确保标签页切换完成
            from PySide6.QtCore import QTimer
            QTimer.singleShot(300, main_window.run_workflow)
        else:
            logger.warning("无法找到主窗口的 run_workflow 方法")

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




