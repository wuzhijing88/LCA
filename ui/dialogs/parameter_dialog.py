import logging

logger = logging.getLogger(__name__)



import sys
import os # <<< ADDED: Import os for path operations
import re
from functools import partial # <<< ADDED: Import partial
from typing import Dict, Any, Optional, Tuple, List, Set
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QDoubleSpinBox, QPushButton, QDialogButtonBox, QWidget,
    QFrame, QCheckBox, QFileDialog, QApplication,
    QRadioButton, QButtonGroup, QPlainTextEdit, QColorDialog, QListWidget,
    QMenu
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap, QImage, QPainter, QBrush, QIcon
import numpy as np
import cv2
from ..widgets.custom_widgets import CustomDropdown as QComboBox
from ..system_parts.menu_style import apply_unified_menu_style
from utils.thread_start_utils import is_thread_start_task_type
from services.screenshot_pool import capture_window
from utils.window_binding_utils import (
    get_active_bound_window_hwnd,
    get_active_bound_windows,
    get_active_target_window_title,
)
from utils.window_activation_utils import show_and_activate_overlay
from utils.window_finder import resolve_unique_window_hwnd


# ===== 自定义SpinBox类，禁用滚轮修改数值 =====
class NoWheelSpinBox(QSpinBox):
    """禁用滚轮事件的QSpinBox"""
    def wheelEvent(self, event):
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    """禁用滚轮事件的QDoubleSpinBox"""
    def wheelEvent(self, event):
        event.ignore()
# ================================================

class ParameterDialog(QDialog):
    """A dialog for editing task parameters."""

    # 信号：请求删除随机跳转连线，参数为目标卡片ID
    request_delete_random_connection = Signal(int)

    def __init__(self, param_definitions: Dict[str, Dict[str, Any]], 
                 current_parameters: Dict[str, Any], 
                 title: str,
                 task_type: str, # <<< ADDED: Explicit task_type parameter
                 # --- ADDED: Receive workflow cards info --- 
                 workflow_cards_info: Optional[Dict[int, tuple[str, int]]] = None, # {seq_id: (task_type, card_id)}
                 # -------------------------------------------
                 images_dir: Optional[str] = None, # <<< ADDED: Receive images_dir
                 editing_card_id: Optional[int] = None, # <<< ADDED: ID of the card being edited
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(500) # 加宽界面以提供更好的显示效果
        # 工具 修复：不设置固定初始大小，让对话框根据内容自动调整
        # self.resize(500, 400) # 设置初始大小

        # 样式由全局主题管理器控制

        self.param_definitions = param_definitions
        self.current_parameters = current_parameters.copy() # Work on a copy

        self.widgets: Dict[str, QWidget] = {} # To retrieve values later
        self.images_dir = images_dir # <<< ADDED: Store images_dir
        self.editing_card_id = editing_card_id # <<< ADDED: Store editing_card_id
        self.task_type = task_type # <<< ADDED: Store task_type
        self._normalize_task_specific_parameters()
        # Store row layout widgets for visibility control
        self.row_widgets: Dict[str, QWidget] = {}
        # Store jump target widgets specifically to enable/disable
        self.jump_target_widgets: Dict[str, QComboBox] = {} # <<< Changed type to QComboBox
        # --- ADDED: Store workflow info ---
        self.workflow_cards_info = workflow_cards_info if workflow_cards_info else {}
        # --- ADDED: Store dynamic module parameter widgets ---
        self.dynamic_param_widgets: List[QWidget] = []
        # ----------------------------------

        # 工具 简化：直接使用内联逻辑处理模拟鼠标操作参数

        # Main layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(12) # Increase spacing
        self.main_layout.setContentsMargins(15, 15, 15, 15) # Add margins

        # Parameter area layout
        self.params_layout = QVBoxLayout()
        self.params_layout.setSpacing(10) # Adjust spacing within params
        # TODO: Consider QScrollArea if parameters are numerous
        
        # --- Dynamically create widgets based on definitions ---
        self._create_widgets()
        self._setup_conditional_visibility() # Setup initial visibility/state

        self.main_layout.addLayout(self.params_layout)

        # --- Separator ---
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        # separator.setObjectName("dialogSeparator") # Assign object name for styling
        self.main_layout.addWidget(separator)

        # --- Dialog Buttons (修复版本) ---
        self.button_box = QDialogButtonBox()
        self.ok_button = QPushButton("确定")
        self.cancel_button = QPushButton("取消")

        # 工具 修复：直接连接按钮信号，不使用QDialogButtonBox的角色系统
        self.ok_button.clicked.connect(lambda: self._on_ok_clicked())
        self.cancel_button.clicked.connect(lambda: self._on_cancel_clicked())

        # 仍然添加到按钮框中以保持布局
        self.button_box.addButton(self.ok_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.button_box.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)

        # 工具 修复：不使用QDialogButtonBox的信号，因为它们有问题
        # self.button_box.accepted.connect(self.accept)
        # self.button_box.rejected.connect(self.reject)
        self.main_layout.addWidget(self.button_box)

        # 样式由全局主题管理器控制

        # 工具 修复：在初始化完成后调整对话框大小
        QTimer.singleShot(0, self._initial_size_adjustment)

    def _normalize_task_specific_parameters(self) -> None:
        if not self.task_type:
            return
        try:
            from tasks import get_task_module
            task_module = get_task_module(self.task_type)
        except Exception:
            task_module = None
        if task_module is None:
            return

        for hook_name in ("normalize_panel_parameters", "normalize_parameters"):
            normalize_hook = getattr(task_module, hook_name, None)
            if not callable(normalize_hook):
                continue
            try:
                normalized_params = normalize_hook(self.current_parameters)
                if isinstance(normalized_params, dict):
                    self.current_parameters = normalized_params
            except Exception as e:
                logger.warning(f"参数对话框任务参数归一化失败({hook_name}): {e}")
            break

    def _collect_all_workflow_cards_for_thread_selector(self) -> List[Tuple[int, str]]:
        cards: List[Tuple[int, str]] = []
        seen: Set[int] = set()
        for _, info in sorted((self.workflow_cards_info or {}).items(), key=lambda kv: kv[0]):
            if not isinstance(info, (tuple, list)) or len(info) < 2:
                continue
            task_type = str(info[0] or "未知任务")
            try:
                card_id = int(info[1])
            except Exception:
                continue
            if card_id in seen:
                continue
            seen.add(card_id)
            cards.append((card_id, task_type))
        cards.sort(key=lambda item: item[0])
        return cards

    def _get_active_workflow_view_for_thread_selector(self):
        current_widget = self.parent()
        for _ in range(12):
            if current_widget is None:
                break
            try:
                tab_widget = getattr(current_widget, "workflow_tab_widget", None)
                if tab_widget is not None:
                    current_task_id = tab_widget.get_current_task_id()
                    if (
                        current_task_id is not None
                        and hasattr(tab_widget, "task_views")
                        and current_task_id in tab_widget.task_views
                    ):
                        return tab_widget.task_views[current_task_id]
                workflow_view = getattr(current_widget, "workflow_view", None)
                if workflow_view is not None:
                    return workflow_view
            except Exception:
                pass
            current_widget = current_widget.parent()
        return None

    def _collect_workflow_connections_for_thread_selector(self) -> List[Tuple[int, int]]:
        workflow_view = self._get_active_workflow_view_for_thread_selector()
        if workflow_view is None or not hasattr(workflow_view, "connections"):
            return []

        connections: List[Tuple[int, int]] = []
        for conn in list(getattr(workflow_view, "connections", []) or []):
            try:
                start_item = getattr(conn, "start_item", None)
                end_item = getattr(conn, "end_item", None)
                if start_item is None or end_item is None:
                    continue
                start_id = int(getattr(start_item, "card_id"))
                end_id = int(getattr(end_item, "card_id"))
            except Exception:
                continue
            connections.append((start_id, end_id))
        return connections

    @staticmethod
    def _collect_reachable_card_ids_for_thread_selector(
        start_card_id: int,
        adjacency: Dict[int, Set[int]],
    ) -> Set[int]:
        visited: Set[int] = set()
        stack: List[int] = [int(start_card_id)]
        while stack:
            current_id = stack.pop()
            if current_id in visited:
                continue
            visited.add(current_id)
            for next_id in adjacency.get(current_id, set()):
                if next_id not in visited:
                    stack.append(next_id)
        return visited

    @staticmethod
    def _parse_thread_start_id_from_target(target_value: Any) -> Optional[int]:
        if target_value is None or isinstance(target_value, bool):
            return None
        if isinstance(target_value, int):
            return target_value if target_value >= 0 else None

        text = str(target_value).strip()
        if not text or text in {"当前线程", "全部线程"}:
            return None

        try:
            value = int(text)
            return value if value >= 0 else None
        except Exception:
            pass

        match = re.search(r"ID\s*[:：]\s*(-?\d+)", text)
        if not match:
            match = re.search(r"\(\s*ID\s*[:：]\s*(-?\d+)\s*\)", text)
        if not match:
            return None
        try:
            value = int(match.group(1))
            return value if value >= 0 else None
        except Exception:
            return None

    def _collect_filtered_workflow_cards_for_thread_target(self, target_value: Any) -> List[Tuple[int, str]]:
        all_cards = self._collect_all_workflow_cards_for_thread_selector()
        if not all_cards:
            return []

        start_card_ids = [card_id for card_id, task_type in all_cards if is_thread_start_task_type(task_type)]
        if not start_card_ids:
            return all_cards

        target_text = str(target_value or "").strip()
        if not target_text or target_text == "全部线程":
            return all_cards

        adjacency: Dict[int, Set[int]] = {}
        for start_id, end_id in self._collect_workflow_connections_for_thread_selector():
            adjacency.setdefault(start_id, set()).add(end_id)

        selected_start_id = self._parse_thread_start_id_from_target(target_value)
        if selected_start_id is not None and selected_start_id not in start_card_ids:
            selected_start_id = None

        if selected_start_id is None and target_text == "当前线程" and self.editing_card_id is not None:
            owner_start_ids: List[int] = []
            for start_id in start_card_ids:
                reachable = self._collect_reachable_card_ids_for_thread_selector(start_id, adjacency)
                if int(self.editing_card_id) in reachable:
                    owner_start_ids.append(start_id)
            if len(owner_start_ids) == 1:
                selected_start_id = owner_start_ids[0]

        if selected_start_id is None:
            return all_cards

        allowed_ids = self._collect_reachable_card_ids_for_thread_selector(selected_start_id, adjacency)
        filtered_cards = [item for item in all_cards if item[0] in allowed_ids]
        return filtered_cards if filtered_cards else all_cards

    def _refresh_workflow_card_selector_options(self):
        target_value: Any = self.current_parameters.get("target_thread")
        target_widget = self.widgets.get("target_thread")
        if isinstance(target_widget, QComboBox):
            selected = target_widget.currentData()
            target_value = selected if selected is not None else target_widget.currentText()
            self.current_parameters["target_thread"] = target_value

        card_items = self._collect_filtered_workflow_cards_for_thread_target(target_value)
        selector_widget = self.widgets.get("start_card_id")
        if not isinstance(selector_widget, QComboBox):
            return

        selected_card_id = selector_widget.currentData()
        selector_widget.blockSignals(True)
        try:
            selector_widget.clear()
            selector_widget.addItem("使用线程默认起点", None)
            for card_id, task_type in card_items:
                selector_widget.addItem(f"{task_type} (ID: {card_id})", int(card_id))

            if selected_card_id is not None:
                try:
                    parsed_id = int(selected_card_id)
                except Exception:
                    parsed_id = None
                if parsed_id is not None and parsed_id >= 0:
                    index = selector_widget.findData(parsed_id)
                    if index >= 0:
                        selector_widget.setCurrentIndex(index)
        finally:
            selector_widget.blockSignals(False)

    def _on_thread_target_selection_changed(self, param_name: str, combo_box: QComboBox):
        selected_value = combo_box.currentData()
        if selected_value is None:
            selected_value = combo_box.currentText()
        self.current_parameters[param_name] = selected_value
        self._refresh_workflow_card_selector_options()

    def _create_widgets(self):
        """Creates input widgets based on parameter definitions."""
        # Sort workflow cards by sequence ID for the dropdown
        sorted_workflow_items = sorted(self.workflow_cards_info.items())

        for name, param_def in self.param_definitions.items():
            should_hide = False # <<< Initialize should_hide at the START of the loop iteration

            param_type = param_def.get('type', 'text')
            label_text = param_def.get('label', name)
            default = param_def.get('default')
            description = param_def.get('description', '')
            options = param_def.get('options', [])
            # 工具 修复：优先使用current_parameters中的值，只有当值不存在时才使用默认值
            if name in self.current_parameters:
                current_value = self.current_parameters[name]
            else:
                current_value = default
            widget_hint = param_def.get('widget_hint')

            # Handle separators in dialog
            if param_type == 'separator':
                # Create a container widget for the separator
                separator_widget = QWidget()
                separator_layout = QVBoxLayout(separator_widget)
                separator_layout.setContentsMargins(0, 0, 0, 0)
                separator_layout.setSpacing(2)

                sep_label = QLabel(label_text)
                sep_label.setAlignment(Qt.AlignCenter)
                # 样式由全局主题管理器控制
                separator_layout.addWidget(sep_label)

                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setFrameShadow(QFrame.Shadow.Sunken)
                separator_layout.addWidget(line)

                # Store the separator widget for visibility control
                self.row_widgets[name] = separator_widget
                self.params_layout.addWidget(separator_widget)
                continue

            # Handle hidden parameters - store their values but don't create widgets
            if param_type == 'hidden':
                # 初始化隐藏参数存储
                if not hasattr(self, '_hidden_params'):
                    self._hidden_params = {}

                # 存储隐藏参数的当前值
                current_value = self.current_parameters.get(name, param_def.get('default'))
                self._hidden_params[name] = current_value
                continue

            # Standard parameter row (Label + Widget)
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0) # No margins for the inner layout
            label = QLabel(f"{label_text}:")
            label.setFixedWidth(120) # Align labels by width
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter) # Align text to the left
            row_layout.addWidget(label)

            widget: Optional[QWidget] = None 
            interactive_widget: Optional[QWidget] = None # Store the widget to get value from

            # <<< RESTRUCTURED LOGIC: Prioritize widget_hint >>>
            if widget_hint == 'colorpicker':
                color_widget_container = QWidget()
                color_widget_layout = QVBoxLayout(color_widget_container)
                color_widget_layout.setContentsMargins(0, 0, 0, 0)
                color_widget_layout.setSpacing(6)

                color_list = QListWidget()
                color_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
                color_list.setSpacing(2)
                raw_value = str(current_value) if current_value is not None else ""
                self._populate_color_list(color_list, raw_value)
                color_list.setProperty("raw_color_data", raw_value)
                item_count = color_list.count()
                color_list.setFixedHeight(min(150, max(60, item_count * 30 + 10)))
                color_widget_layout.addWidget(color_list)

                button_row = QHBoxLayout()
                button_row.setContentsMargins(0, 0, 0, 0)
                button_row.setSpacing(6)

                pick_button = QPushButton("屏幕取色")
                pick_button.clicked.connect(lambda checked=False, cl=color_list, param_name=name: self._select_color_rgb_list(cl, param_name))
                button_row.addWidget(pick_button)

                button_row.addStretch()
                color_widget_layout.addLayout(button_row)

                widget = color_widget_container
                interactive_widget = color_list


            elif widget_hint == 'workflow_selector':
                combo_box = QComboBox(self)

                def _normalize_workflow_value(value):
                    if value in (None, "", "当前工作流"):
                        return None
                    if value in ("全局变量", "global"):
                        return "global"
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        return None

                def _get_workflow_items():
                    items = []
                    current_task_id = None
                    task_manager = None
                    try:
                        from PySide6.QtWidgets import QApplication
                        main_window = QApplication.activeWindow()
                        if main_window and hasattr(main_window, "workflow_tab_widget") and main_window.workflow_tab_widget:
                            current_task_id = main_window.workflow_tab_widget.get_current_task_id()
                            task_manager = main_window.workflow_tab_widget.task_manager
                        if task_manager is None and main_window and hasattr(main_window, "task_manager"):
                            task_manager = main_window.task_manager
                    except Exception:
                        task_manager = None

                    if task_manager:
                        for task in task_manager.get_all_tasks():
                            if current_task_id is not None and task.task_id == current_task_id:
                                continue
                            items.append((f"工作流 {task.task_id} {task.name}", task.task_id))
                    return items

                combo_box.addItem("当前工作流", None)
                combo_box.addItem("全局变量", "global")
                for label, task_id in _get_workflow_items():
                    combo_box.addItem(label, task_id)

                current_value = _normalize_workflow_value(current_value)
                index = combo_box.findData(current_value)
                if current_value is None:
                    combo_box.setCurrentIndex(0)
                    self.current_parameters[name] = None
                elif index >= 0:
                    combo_box.setCurrentIndex(index)
                else:
                    combo_box.setCurrentIndex(0)
                    self.current_parameters[name] = None

                def _on_workflow_changed(index):
                    value = combo_box.itemData(index)
                    self.current_parameters[name] = value
                    if hasattr(self, "_workflow_dependent_refreshers"):
                        for refresher in self._workflow_dependent_refreshers.get(name, []):
                            refresher()

                combo_box.currentIndexChanged.connect(_on_workflow_changed)

                widget = combo_box
                interactive_widget = combo_box

            elif widget_hint == 'variable_card_selector':
                combo_box = QComboBox(self)

                def _normalize_card_value(value):
                    if value in (None, "", "全部"):
                        return None
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        return None

                def _normalize_workflow_value(value):
                    if value in (None, "", "当前工作流"):
                        return None
                    if value in ("全局变量", "global"):
                        return "global"
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        return None

                def _get_card_label(card_id: int, task_type: str = None, custom_name: str = None) -> str:
                    if custom_name:
                        return f"卡片 {card_id} {custom_name}"
                    if task_type:
                        return f"卡片 {card_id} {task_type}"
                    return f"卡片 {card_id}"

                def _get_task_manager():
                    task_manager = None
                    try:
                        from PySide6.QtWidgets import QApplication
                        main_window = QApplication.activeWindow()
                        if main_window and hasattr(main_window, "workflow_tab_widget") and main_window.workflow_tab_widget:
                            task_manager = main_window.workflow_tab_widget.task_manager
                        if task_manager is None and main_window and hasattr(main_window, "task_manager"):
                            task_manager = main_window.task_manager
                    except Exception:
                        task_manager = None
                    return task_manager

                def _get_cards_for_current() -> dict:
                    labels = {}
                    try:
                        from PySide6.QtWidgets import QApplication
                        current_workflow_view = None
                        main_window = QApplication.activeWindow()
                        if main_window and hasattr(main_window, "workflow_tab_widget") and main_window.workflow_tab_widget:
                            current_task_id = main_window.workflow_tab_widget.get_current_task_id()
                            if current_task_id is not None and current_task_id in main_window.workflow_tab_widget.task_views:
                                current_workflow_view = main_window.workflow_tab_widget.task_views[current_task_id]
                        if current_workflow_view is None and main_window and hasattr(main_window, "workflow_view"):
                            current_workflow_view = main_window.workflow_view
                        if current_workflow_view and hasattr(current_workflow_view, "cards"):
                            for card_id, card in current_workflow_view.cards.items():
                                labels[int(card_id)] = _get_card_label(
                                    card_id,
                                    task_type=getattr(card, "task_type", None),
                                    custom_name=getattr(card, "custom_name", None),
                                )
                    except Exception:
                        pass

                    if labels:
                        return labels

                    for _, (task_type, info_card_id) in (self.workflow_cards_info or {}).items():
                        if isinstance(info_card_id, int):
                            labels[info_card_id] = _get_card_label(info_card_id, task_type=task_type)
                    return labels

                def _get_cards_for_task(task_id: int) -> dict:
                    labels = {}
                    try:
                        task_manager = _get_task_manager()
                        task = task_manager.get_task(task_id) if task_manager else None
                        cards = task.workflow_data.get("cards", []) if task and isinstance(task.workflow_data, dict) else []
                        for card in cards:
                            card_id = card.get("id")
                            if card_id is None:
                                continue
                            try:
                                card_id_int = int(card_id)
                            except (TypeError, ValueError):
                                continue
                            custom_name = card.get("custom_name") or card.get("customName")
                            task_type = card.get("task_type")
                            labels[card_id_int] = _get_card_label(card_id_int, task_type=task_type, custom_name=custom_name)
                    except Exception:
                        pass
                    return labels

                def _get_workflow_filter_id():
                    workflow_param = param_def.get("workflow_filter_param")
                    if not workflow_param:
                        return None
                    return _normalize_workflow_value(self.current_parameters.get(workflow_param))

                def _sort_key(var_name: str) -> tuple:
                    import re
                    text = str(var_name)
                    match = re.match(r'^卡片(\d+)结果(?:[\._](.*))?$', text)
                    if match:
                        return (0, int(match.group(1)), match.group(2) or "")
                    match = re.match(r'^card_(\d+)_result(?:[\._](.*))?$', text, flags=re.IGNORECASE)
                    if match:
                        return (0, int(match.group(1)), match.group(2) or "")
                    return (1, text)

                def _is_system_var(var_name: str) -> bool:
                    return str(var_name).startswith((
                        "latest_ocr_",
                        "latest_yolo_",
                    ))

                def _get_task_type_for_card(card_id: Optional[int], workflow_task_id: Optional[int]) -> Optional[str]:
                    if card_id is None:
                        return None
                    try:
                        if workflow_task_id is None:
                            from PySide6.QtWidgets import QApplication
                            current_workflow_view = None
                            main_window = QApplication.activeWindow()
                            if main_window and hasattr(main_window, "workflow_tab_widget") and main_window.workflow_tab_widget:
                                current_task_id = main_window.workflow_tab_widget.get_current_task_id()
                                if current_task_id is not None and current_task_id in main_window.workflow_tab_widget.task_views:
                                    current_workflow_view = main_window.workflow_tab_widget.task_views[current_task_id]
                            if current_workflow_view is None and main_window and hasattr(main_window, "workflow_view"):
                                current_workflow_view = main_window.workflow_view
                            if current_workflow_view and hasattr(current_workflow_view, "cards"):
                                card = current_workflow_view.cards.get(card_id)
                                if card:
                                    return getattr(card, "task_type", None)
                        elif workflow_task_id == "global":
                            return None
                        else:
                            task_manager = None
                            try:
                                from PySide6.QtWidgets import QApplication
                                main_window = QApplication.activeWindow()
                                if main_window and hasattr(main_window, "workflow_tab_widget") and main_window.workflow_tab_widget:
                                    task_manager = main_window.workflow_tab_widget.task_manager
                                if task_manager is None and main_window and hasattr(main_window, "task_manager"):
                                    task_manager = main_window.task_manager
                            except Exception:
                                task_manager = None
                            task = task_manager.get_task(workflow_task_id) if task_manager else None
                            cards = task.workflow_data.get("cards", []) if task and isinstance(task.workflow_data, dict) else []
                            for card in cards:
                                card_id_value = card.get("id")
                                if card_id_value is None:
                                    continue
                                try:
                                    card_id_int = int(card_id_value)
                                except (TypeError, ValueError):
                                    continue
                                if card_id_int == card_id:
                                    return card.get("task_type")
                    except Exception:
                        return None
                    for _, (task_type, info_card_id) in (self.workflow_cards_info or {}).items():
                        if info_card_id == card_id:
                            return task_type
                    return None

                def _get_variable_names(card_id: Optional[int], workflow_task_id) -> List[str]:
                    try:
                        if workflow_task_id is None:
                            from task_workflow.workflow_context import get_workflow_context
                            context = get_workflow_context()
                        else:
                            from task_workflow.workflow_vars import get_context_for_task
                            context = get_context_for_task(workflow_task_id)
                        if not context:
                            return []
                        if hasattr(context, "snapshot_variable_state"):
                            state = context.snapshot_variable_state()
                            global_vars = dict((state or {}).get("global_vars", {}) or {})
                            source_map = dict((state or {}).get("var_sources", {}) or {})
                        else:
                            global_vars = getattr(context, "global_vars", {}) or {}
                            source_map = getattr(context, "var_sources", {}) or {}
                        if workflow_task_id == "global":
                            names = [str(var_name) for var_name in global_vars.keys() if not _is_system_var(var_name)]
                            return sorted(names, key=_sort_key)
                        names = []
                        allowed_task_types = param_def.get("allowed_task_types")
                        if allowed_task_types and not isinstance(allowed_task_types, (list, tuple, set)):
                            allowed_task_types = [allowed_task_types]
                        allowed_task_types = [str(item) for item in (allowed_task_types or []) if str(item)]
                        for var_name in global_vars.keys():
                            if _is_system_var(var_name):
                                continue
                            source_id = source_map.get(var_name)
                            if card_id is None:
                                if source_id is None:
                                    continue
                                if allowed_task_types:
                                    task_type = _get_task_type_for_card(source_id, workflow_task_id)
                                    if task_type not in allowed_task_types:
                                        continue
                                names.append(str(var_name))
                            else:
                                if source_id == card_id:
                                    if allowed_task_types:
                                        task_type = _get_task_type_for_card(source_id, workflow_task_id)
                                        if task_type not in allowed_task_types:
                                            continue
                                    names.append(str(var_name))
                        return sorted(names, key=_sort_key)
                    except Exception:
                        return []

                def _refresh_variable_names(card_id: Optional[int]):
                    variable_widget = self.widgets.get("simple_variable_name")
                    if not isinstance(variable_widget, QComboBox):
                        return
                    current_var = variable_widget.currentText()
                    workflow_filter_id = _get_workflow_filter_id()
                    names = _get_variable_names(card_id, workflow_filter_id)
                    variable_widget.blockSignals(True)
                    variable_widget.clear()
                    variable_widget.addItem("请选择变量", "")
                    for var_name in names:
                        variable_widget.addItem(var_name)
                    if current_var in names:
                        variable_widget.setCurrentText(current_var)
                    else:
                        variable_widget.setCurrentIndex(0)
                    variable_widget.blockSignals(False)

                def _populate_cards():
                    workflow_filter_id = _get_workflow_filter_id()
                    if workflow_filter_id is None:
                        labels = _get_cards_for_current()
                    elif workflow_filter_id == "global":
                        labels = {}
                    else:
                        labels = _get_cards_for_task(workflow_filter_id)

                    card_ids = sorted(labels.keys())
                    combo_box.blockSignals(True)
                    combo_box.clear()
                    combo_box.addItem("全部", None)
                    for card_id in card_ids:
                        combo_box.addItem(labels[card_id], card_id)

                    current_value = _normalize_card_value(self.current_parameters.get(name))
                    if current_value is None:
                        combo_box.setCurrentIndex(0)
                    else:
                        index = combo_box.findData(current_value)
                        if index >= 0:
                            combo_box.setCurrentIndex(index)
                        else:
                            combo_box.setCurrentIndex(0)
                            self.current_parameters[name] = None
                    combo_box.blockSignals(False)

                    _refresh_variable_names(current_value if current_value is not None else None)

                _populate_cards()

                workflow_filter_param = param_def.get("workflow_filter_param")
                if workflow_filter_param:
                    if not hasattr(self, "_workflow_dependent_refreshers"):
                        self._workflow_dependent_refreshers = {}
                    self._workflow_dependent_refreshers.setdefault(workflow_filter_param, []).append(_populate_cards)

                def _on_card_changed(index):
                    card_value = combo_box.itemData(index)
                    self.current_parameters[name] = card_value
                    _refresh_variable_names(_normalize_card_value(card_value))

                combo_box.currentIndexChanged.connect(_on_card_changed)

                widget = combo_box
                interactive_widget = combo_box

            elif widget_hint == 'variable_name_selector':
                combo_box = QComboBox(self)

                def _normalize_card_value(value):
                    if value in (None, "", "全部"):
                        return None
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        return None

                def _normalize_workflow_value(value):
                    if value in (None, "", "当前工作流"):
                        return None
                    if value in ("全局变量", "global"):
                        return "global"
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        return None

                def _sort_key(var_name: str) -> tuple:
                    import re
                    text = str(var_name)
                    match = re.match(r'^卡片(\d+)结果(?:[\._](.*))?$', text)
                    if match:
                        return (0, int(match.group(1)), match.group(2) or "")
                    match = re.match(r'^card_(\d+)_result(?:[\._](.*))?$', text, flags=re.IGNORECASE)
                    if match:
                        return (0, int(match.group(1)), match.group(2) or "")
                    return (1, text)

                def _is_system_var(var_name: str) -> bool:
                    return str(var_name).startswith((
                        "latest_ocr_",
                        "latest_yolo_",
                    ))

                def _get_task_type_for_card(card_id: Optional[int], workflow_task_id: Optional[int]) -> Optional[str]:
                    if card_id is None:
                        return None
                    try:
                        if workflow_task_id is None:
                            from PySide6.QtWidgets import QApplication
                            current_workflow_view = None
                            main_window = QApplication.activeWindow()
                            if main_window and hasattr(main_window, "workflow_tab_widget") and main_window.workflow_tab_widget:
                                current_task_id = main_window.workflow_tab_widget.get_current_task_id()
                                if current_task_id is not None and current_task_id in main_window.workflow_tab_widget.task_views:
                                    current_workflow_view = main_window.workflow_tab_widget.task_views[current_task_id]
                            if current_workflow_view is None and main_window and hasattr(main_window, "workflow_view"):
                                current_workflow_view = main_window.workflow_view
                            if current_workflow_view and hasattr(current_workflow_view, "cards"):
                                card = current_workflow_view.cards.get(card_id)
                                if card:
                                    return getattr(card, "task_type", None)
                        elif workflow_task_id == "global":
                            return None
                        else:
                            task_manager = _get_task_manager()
                            task = task_manager.get_task(workflow_task_id) if task_manager else None
                            cards = task.workflow_data.get("cards", []) if task and isinstance(task.workflow_data, dict) else []
                            for card in cards:
                                card_id_value = card.get("id")
                                if card_id_value is None:
                                    continue
                                try:
                                    card_id_int = int(card_id_value)
                                except (TypeError, ValueError):
                                    continue
                                if card_id_int == card_id:
                                    return card.get("task_type")
                    except Exception:
                        return None
                    for _, (task_type, info_card_id) in (self.workflow_cards_info or {}).items():
                        if info_card_id == card_id:
                            return task_type
                    return None

                def _get_variable_names(card_id: Optional[int], workflow_task_id) -> List[str]:
                    try:
                        if workflow_task_id is None:
                            from task_workflow.workflow_context import get_workflow_context
                            context = get_workflow_context()
                        else:
                            from task_workflow.workflow_vars import get_context_for_task
                            context = get_context_for_task(workflow_task_id)
                        if not context:
                            return []
                        if hasattr(context, "snapshot_variable_state"):
                            state = context.snapshot_variable_state()
                            global_vars = dict((state or {}).get("global_vars", {}) or {})
                            source_map = dict((state or {}).get("var_sources", {}) or {})
                        else:
                            global_vars = getattr(context, "global_vars", {}) or {}
                            source_map = getattr(context, "var_sources", {}) or {}
                        if workflow_task_id == "global":
                            names = [str(var_name) for var_name in global_vars.keys() if not _is_system_var(var_name)]
                            return sorted(names, key=_sort_key)
                        names = []
                        allowed_task_types = param_def.get("allowed_task_types")
                        if allowed_task_types and not isinstance(allowed_task_types, (list, tuple, set)):
                            allowed_task_types = [allowed_task_types]
                        allowed_task_types = [str(item) for item in (allowed_task_types or []) if str(item)]
                        for var_name in global_vars.keys():
                            if _is_system_var(var_name):
                                continue
                            source_id = source_map.get(var_name)
                            if card_id is None:
                                if source_id is None:
                                    continue
                                if allowed_task_types:
                                    task_type = _get_task_type_for_card(source_id, workflow_task_id)
                                    if task_type not in allowed_task_types:
                                        continue
                                names.append(str(var_name))
                            else:
                                if source_id == card_id:
                                    if allowed_task_types:
                                        task_type = _get_task_type_for_card(source_id, workflow_task_id)
                                        if task_type not in allowed_task_types:
                                            continue
                                    names.append(str(var_name))
                        return sorted(names, key=_sort_key)
                    except Exception:
                        return []

                def _populate_variable_names():
                    card_filter_param = param_def.get("card_filter_param") or "variable_card_id"
                    filter_card_id = _normalize_card_value(self.current_parameters.get(card_filter_param))
                    workflow_filter_param = param_def.get("workflow_filter_param")
                    workflow_filter_id = None
                    if workflow_filter_param:
                        workflow_filter_id = _normalize_workflow_value(self.current_parameters.get(workflow_filter_param))
                    global_only = bool(param_def.get("global_only"))
                    if global_only:
                        workflow_filter_id = "global"
                        filter_card_id = None
                        try:
                            from task_workflow.global_var_store import ensure_global_context_loaded

                            ensure_global_context_loaded()
                        except Exception:
                            pass
                    names = _get_variable_names(filter_card_id, workflow_filter_id)
                    current_value = self.current_parameters.get(name)
                    combo_box.blockSignals(True)
                    combo_box.clear()
                    placeholder_label = "请选择变量" if global_only else "当前工作流"
                    combo_box.addItem(placeholder_label, "")
                    for var_name in names:
                        combo_box.addItem(var_name)
                    if current_value in names:
                        combo_box.setCurrentText(str(current_value))
                    else:
                        combo_box.setCurrentIndex(0)
                    combo_box.blockSignals(False)

                _populate_variable_names()

                workflow_filter_param = param_def.get("workflow_filter_param")
                if workflow_filter_param:
                    if not hasattr(self, "_workflow_dependent_refreshers"):
                        self._workflow_dependent_refreshers = {}
                    self._workflow_dependent_refreshers.setdefault(workflow_filter_param, []).append(_populate_variable_names)

                widget = combo_box
                interactive_widget = combo_box

            elif widget_hint == 'variable_sources_table':
                import json as json_module
                from ui.dialogs.variable_sources_dialog import VariableSourcesDialog

                table_container = QWidget()
                table_layout = QHBoxLayout(table_container)
                table_layout.setContentsMargins(0, 0, 0, 0)
                table_layout.setSpacing(8)

                summary_label = QLabel("已配置 0 个来源")
                edit_button = QPushButton("编辑来源")

                hidden_edit = QPlainTextEdit()
                hidden_edit.setVisible(False)

                table_layout.addWidget(summary_label, 1)
                table_layout.addWidget(edit_button, 0)
                table_layout.addWidget(hidden_edit)

                def _parse_sources_text(text: str) -> list:
                    names = []
                    for part in text.replace(";", ",").replace("|", ",").split(","):
                        chunk = part.strip()
                        if not chunk:
                            continue
                        for line in chunk.splitlines():
                            name = line.strip()
                            if name:
                                names.append(name)
                    return names

                def _load_sources(value) -> list:
                    if isinstance(value, list):
                        return [str(item).strip() for item in value if str(item).strip()]
                    if isinstance(value, str) and value.strip():
                        try:
                            parsed = json_module.loads(value)
                            if isinstance(parsed, list):
                                return [str(item).strip() for item in parsed if str(item).strip()]
                        except Exception:
                            pass
                        return _parse_sources_text(value)
                    return []

                def _update_summary(count: int):
                    summary_label.setText(f"已配置 {count} 个来源")

                def _normalize_card_id(value):
                    if value in (None, "", "全部"):
                        return None
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        return None

                def _get_card_filter_id():
                    card_param = param_def.get("card_filter_param")
                    if not card_param:
                        return None
                    return _normalize_card_id(self.current_parameters.get(card_param))

                def _get_workflow_filter_id():
                    workflow_param = param_def.get("workflow_filter_param")
                    if not workflow_param:
                        return None
                    value = self.current_parameters.get(workflow_param)
                    if value in (None, "", "当前工作流"):
                        return None
                    if value in ("全局变量", "global"):
                        return "global"
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        return None

                sources_cache = _load_sources(current_value if current_value is not None else param_def.get('default', '[]'))
                hidden_edit.setPlainText(json_module.dumps(sources_cache, ensure_ascii=True))
                self.current_parameters[name] = hidden_edit.toPlainText()
                _update_summary(len(sources_cache))

                def _open_sources_dialog():
                    nonlocal sources_cache
                    card_filter_id = _get_card_filter_id()
                    workflow_filter_id = _get_workflow_filter_id()
                    dialog = VariableSourcesDialog(sources_cache, self, card_id=card_filter_id, workflow_id=workflow_filter_id)
                    if dialog.exec() == QDialog.DialogCode.Accepted:
                        sources_cache = dialog.get_sources()
                        hidden_edit.setPlainText(json_module.dumps(sources_cache, ensure_ascii=True))
                        self.current_parameters[name] = hidden_edit.toPlainText()
                        _update_summary(len(sources_cache))

                edit_button.clicked.connect(_open_sources_dialog)

                widget = table_container
                interactive_widget = table_container
                self.widgets[name] = hidden_edit

            elif widget_hint == 'conditions_table':
                import json as json_module
                from ui.dialogs.conditions_table_dialog import ConditionsTableDialog

                table_container = QWidget()
                table_layout = QHBoxLayout(table_container)
                table_layout.setContentsMargins(0, 0, 0, 0)
                table_layout.setSpacing(8)

                summary_label = QLabel("已配置 0 条条件")
                edit_button = QPushButton("编辑条件")

                hidden_edit = QPlainTextEdit()
                hidden_edit.setVisible(False)

                table_layout.addWidget(summary_label, 1)
                table_layout.addWidget(edit_button, 0)
                table_layout.addWidget(hidden_edit)

                def _load_conditions(value) -> list:
                    if isinstance(value, list):
                        return value
                    if isinstance(value, str) and value.strip():
                        try:
                            parsed = json_module.loads(value)
                            if isinstance(parsed, list):
                                return parsed
                        except Exception:
                            pass
                    return []

                def _update_summary(count: int):
                    summary_label.setText(f"已配置 {count} 条条件")

                def _normalize_card_id(value):
                    if value in (None, "", "全部"):
                        return None
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        return None

                def _get_card_filter_id():
                    card_param = param_def.get("card_filter_param")
                    if not card_param:
                        return None
                    return _normalize_card_id(self.current_parameters.get(card_param))

                def _get_workflow_filter_id():
                    workflow_param = param_def.get("workflow_filter_param")
                    if not workflow_param:
                        return None
                    value = self.current_parameters.get(workflow_param)
                    if value in (None, "", "当前工作流"):
                        return None
                    if value in ("全局变量", "global"):
                        return "global"
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        return None

                conditions_cache = _load_conditions(current_value if current_value is not None else param_def.get('default', '[]'))
                hidden_edit.setPlainText(json_module.dumps(conditions_cache, ensure_ascii=True))
                self.current_parameters[name] = hidden_edit.toPlainText()
                _update_summary(len(conditions_cache))

                def _open_conditions_dialog():
                    nonlocal conditions_cache
                    card_filter_id = _get_card_filter_id()
                    workflow_filter_id = _get_workflow_filter_id()
                    dialog = ConditionsTableDialog(conditions_cache, self, card_id=card_filter_id, workflow_id=workflow_filter_id)
                    if dialog.exec() == QDialog.DialogCode.Accepted:
                        conditions_cache = dialog.get_conditions()
                        hidden_edit.setPlainText(json_module.dumps(conditions_cache, ensure_ascii=True))
                        self.current_parameters[name] = hidden_edit.toPlainText()
                        _update_summary(len(conditions_cache))

                edit_button.clicked.connect(_open_conditions_dialog)

                widget = table_container
                interactive_widget = table_container
                self.widgets[name] = hidden_edit

            elif widget_hint == 'element_picker':
                # 元素拾取器
                picker_button = QPushButton(param_def.get('button_text', '拾取元素'))
                picker_button.setToolTip(param_def.get('tooltip', '点击后将鼠标移动到目标元素上'))
                picker_button.clicked.connect(lambda checked=False: self._start_element_picking())
                widget = picker_button
                interactive_widget = None
                # 存储按钮引用，用于更新状态
                self._element_picker_button = picker_button
                # 隐藏左侧标签
                label.hide()

            elif widget_hint == 'ocr_region_selector': # Create OCR region selector widget
                try:
                    from ui.selectors.ocr_region_selector import OCRRegionSelectorWidget
                    ocr_selector = OCRRegionSelectorWidget()

                    # 设置初始区域（如果有的话）
                    initial_x = self.current_parameters.get('region_x', 0)
                    initial_y = self.current_parameters.get('region_y', 0)
                    initial_width = self.current_parameters.get('region_width', 0)
                    initial_height = self.current_parameters.get('region_height', 0)

                    ocr_selector.set_region(initial_x, initial_y, initial_width, initial_height)

                    # 连接信号
                    ocr_selector.region_selected.connect(self._on_ocr_region_selected)
                    ocr_selector.selection_started.connect(self._on_ocr_selection_started)
                    ocr_selector.selection_finished.connect(self._on_ocr_selection_finished)

                    self._apply_bound_window_to_selector(ocr_selector)

                    widget = ocr_selector
                    interactive_widget = ocr_selector

                except Exception as e:
                    # 创建占位符按钮
                    widget = QPushButton("OCR区域选择器加载失败")
                    widget.setEnabled(False)
                    interactive_widget = widget
            elif widget_hint == 'coordinate_selector':
                # 坐标选择器
                try:
                    from ui.selectors.coordinate_selector import CoordinateSelectorWidget
                    coord_selector = CoordinateSelectorWidget()

                    # 工具 修复：初始化坐标选择器的当前坐标值
                    existing_x = self.current_parameters.get('coordinate_x', 0)
                    existing_y = self.current_parameters.get('coordinate_y', 0)
                    if existing_x is not None and existing_y is not None:
                        try:
                            coord_x = int(existing_x) if existing_x != '' else 0
                            coord_y = int(existing_y) if existing_y != '' else 0
                            coord_selector.set_coordinate(coord_x, coord_y)
                        except (ValueError, TypeError):
                            coord_selector.set_coordinate(0, 0)
                    else:
                        coord_selector.set_coordinate(0, 0)

                    # 工具 修复：确保信号连接正确，添加调试信息
                    # 工具 修复：正确的信号连接，坐标选择器发射(x, y)，我们需要传递selector_name
                    coord_selector.coordinate_selected.connect(lambda x, y, selector_name=name: self._on_coordinate_selected(selector_name, x, y))
                    coord_selector.selection_started.connect(self._on_coordinate_selection_started)
                    coord_selector.selection_finished.connect(self._on_coordinate_selection_finished)
                    self._apply_bound_window_to_selector(coord_selector)
                    widget = coord_selector
                    interactive_widget = coord_selector
                except Exception as e:
                    # 创建一个简单的按钮作为备选
                    widget = QPushButton("坐标选择器 (创建失败)")
                    interactive_widget = widget

            elif widget_hint == 'motion_region_selector':
                # 移动检测区域选择器
                try:
                    from ui.selectors.ocr_region_selector import OCRRegionSelectorWidget
                    motion_region_selector = OCRRegionSelectorWidget()

                    # 设置初始区域（如果有的话）
                    initial_x = self.current_parameters.get('minimap_x', 1150)
                    initial_y = self.current_parameters.get('minimap_y', 40)
                    initial_width = self.current_parameters.get('minimap_width', 50)
                    initial_height = self.current_parameters.get('minimap_height', 50)

                    motion_region_selector.set_region(initial_x, initial_y, initial_width, initial_height)

                    # 连接信号
                    motion_region_selector.region_selected.connect(
                        lambda x, y, w, h, selector_name=name: self._on_motion_region_selected(selector_name, x, y, w, h)
                    )
                    motion_region_selector.selection_started.connect(self._on_ocr_selection_started)
                    motion_region_selector.selection_finished.connect(self._on_ocr_selection_finished)
                    self._apply_bound_window_to_selector(motion_region_selector)

                    widget = motion_region_selector
                    interactive_widget = motion_region_selector
                except Exception as e:
                    # 创建一个简单的按钮作为备选
                    widget = QPushButton("移动检测区域选择器 (创建失败)")
                    interactive_widget = widget

            elif widget_hint == 'image_region_selector':
                # 图片识别区域选择器
                try:
                    from ui.selectors.ocr_region_selector import OCRRegionSelectorWidget
                    image_region_selector = OCRRegionSelectorWidget()

                    # 设置初始区域（如果有的话）
                    initial_x = self.current_parameters.get('recognition_region_x', 0)
                    initial_y = self.current_parameters.get('recognition_region_y', 0)
                    initial_width = self.current_parameters.get('recognition_region_width', 0)
                    initial_height = self.current_parameters.get('recognition_region_height', 0)

                    image_region_selector.set_region(initial_x, initial_y, initial_width, initial_height)

                    # 连接信号
                    image_region_selector.region_selected.connect(
                        lambda x, y, w, h, selector_name=name: self._on_image_region_selected(selector_name, x, y, w, h)
                    )
                    image_region_selector.selection_started.connect(self._on_ocr_selection_started)
                    image_region_selector.selection_finished.connect(self._on_ocr_selection_finished)

                    self._apply_bound_window_to_selector(image_region_selector)

                    # 如果已有区域数据，更新按钮文本显示
                    if initial_width > 0 and initial_height > 0:
                        button_text = f"区域: X={initial_x}, Y={initial_y}, {initial_width}x{initial_height}"
                        image_region_selector.select_button.setText(button_text)

                    widget = image_region_selector
                    interactive_widget = image_region_selector
                except Exception as e:
                    # 创建一个简单的按钮作为备选
                    widget = QPushButton("图片识别区域选择器 (创建失败)")
                    interactive_widget = widget

            elif widget_hint == 'refresh_apps': # 刷新应用列表按钮

                try:
                    button = QPushButton(param_def.get('button_text', '刷新'))

                    def on_refresh_clicked():
                        # 应用管理功能已移除
                        logger.warning("应用管理功能已移除")

                    button.clicked.connect(on_refresh_clicked)

                    widget = button
                    interactive_widget = button

                    # 添加测试按钮功能
                    def test_button():
                        # 应用管理功能已移除
                        logger.warning("应用管理功能已移除")

                    # 可以通过右键菜单或其他方式触发测试
                    button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                    button.customContextMenuRequested.connect(lambda: test_button())

                except Exception as e:
                    logger.error(f"创建刷新应用列表按钮失败: {e}")
                    # 创建占位符按钮
                    widget = QPushButton("刷新按钮加载失败")
                    widget.setEnabled(False)
                    interactive_widget = widget

            elif widget_hint == 'refresh_dynamic_options':
                # 刷新动态选项按钮（用于YOLO类别等）
                button = QPushButton(param_def.get('button_text', '刷新'))
                raw_target_params = param_def.get('target_params')
                target_params = []
                if isinstance(raw_target_params, (list, tuple, set)):
                    for item in raw_target_params:
                        text = str(item or "").strip()
                        if text:
                            target_params.append(text)
                if not target_params:
                    target_param = str(param_def.get('target_param', '') or '').strip()
                    if target_param:
                        target_params.append(target_param)
                source_param = param_def.get('source_param', '')
                options_func_name = param_def.get('options_func', '')
                source_label = str(param_def.get('source_label', '') or '').strip()
                if not source_label:
                    source_def = self.param_definitions.get(source_param, {}) if source_param else {}
                    source_label = str(source_def.get('label', '') or '').strip() or '源参数'
                raw_default_options = param_def.get('default_options')
                default_options = None
                if isinstance(raw_default_options, (list, tuple, set)):
                    default_options = [
                        str(item or "").strip()
                        for item in raw_default_options
                        if str(item or "").strip()
                    ]

                def on_refresh_dynamic_options(
                    tps=target_params,
                    sp=source_param,
                    fn=options_func_name,
                    source_label_text=source_label,
                    fallback_options=default_options,
                ):
                    # 获取源参数值
                    source_widget = self.widgets.get(sp)
                    if source_widget:
                        if isinstance(source_widget, QLineEdit):
                            source_value = source_widget.text()
                        elif hasattr(source_widget, 'findChild'):
                            line_edit = source_widget.findChild(QLineEdit)
                            source_value = line_edit.text() if line_edit else ''
                        else:
                            source_value = ''
                    else:
                        source_value = ''

                    if not source_value:
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.warning(self, "提示", f"请先设置{source_label_text}")
                        return

                    # 调用函数获取选项
                    new_options = self._get_dynamic_options(fn, source_value, fallback_options)

                    updated_count = 0
                    for tp in tps:
                        target_widget = self.widgets.get(tp)
                        if not isinstance(target_widget, QComboBox):
                            continue

                        current_selection = target_widget.currentText()
                        target_widget.clear()
                        target_widget.addItems(new_options)

                        # 恢复选择
                        index = target_widget.findText(current_selection)
                        if index != -1:
                            target_widget.setCurrentIndex(index)
                        self.current_parameters[tp] = target_widget.currentText()
                        updated_count += 1

                    if updated_count <= 0:
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.warning(self, "错误", "未找到可刷新的目标下拉框")
                        return

                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.information(self, "完成", f"已加载 {len(new_options)} 个选项，已更新 {updated_count} 个下拉框")

                button.clicked.connect(on_refresh_dynamic_options)
                widget = button
                interactive_widget = button

            elif widget_hint == 'thread_target_selector':
                combo_box = QComboBox(self)
                combo_box.addItem("当前线程", "当前线程")
                combo_box.addItem("全部线程", "全部线程")

                start_ids: List[int] = []
                for _, info in sorted((self.workflow_cards_info or {}).items(), key=lambda kv: kv[0]):
                    if not isinstance(info, (tuple, list)) or len(info) < 2:
                        continue
                    task_type = str(info[0] or "")
                    if not is_thread_start_task_type(task_type):
                        continue
                    try:
                        start_ids.append(int(info[1]))
                    except Exception:
                        continue

                for idx, start_id in enumerate(sorted(set(start_ids)), 1):
                    combo_box.addItem(f"线程起点{idx} (ID: {start_id})", str(start_id))

                desired = str(current_value or "").strip()
                if desired:
                    index = combo_box.findData(desired)
                    if index < 0:
                        index = combo_box.findText(desired)
                    if index < 0 and not desired.isdigit():
                        for i in range(combo_box.count()):
                            if combo_box.itemText(i).startswith(f"{desired} (ID:"):
                                index = i
                                break
                    if index >= 0:
                        combo_box.setCurrentIndex(index)
                selected_value = combo_box.currentData()
                if selected_value is None:
                    selected_value = combo_box.currentText()
                self.current_parameters[name] = selected_value
                combo_box.currentIndexChanged.connect(
                    lambda _index, n=name, cb=combo_box: self._on_thread_target_selection_changed(n, cb)
                )
                widget = combo_box
                interactive_widget = combo_box

            elif widget_hint == 'bound_window_selector':
                combo_box = QComboBox(self)
                combo_box.addItem("使用默认窗口", None)

                for idx, window_info in enumerate(self._get_enabled_bound_windows_for_selector(), 1):
                    window_title = str(window_info.get("title") or f"窗口{idx}").strip()
                    combo_box.addItem(f"窗口{idx}: {window_title}", idx)

                selected_index = None
                try:
                    if current_value not in (None, "", "None", "none", 0, "0"):
                        selected_index = int(current_value)
                except Exception:
                    selected_index = None
                if selected_index is not None and selected_index > 0:
                    index = combo_box.findData(selected_index)
                    if index >= 0:
                        combo_box.setCurrentIndex(index)

                widget = combo_box
                interactive_widget = combo_box

            elif widget_hint == 'workflow_card_selector':
                combo_box = QComboBox(self)
                combo_box.addItem("使用线程默认起点", None)

                target_thread_value = self.current_parameters.get("target_thread")
                for info_card_id, task_type in self._collect_filtered_workflow_cards_for_thread_target(
                    target_thread_value
                ):
                    combo_box.addItem(f"{task_type} (ID: {info_card_id})", info_card_id)

                selected_card_id = None
                if current_value is not None:
                    text_value = str(current_value).strip()
                    if text_value not in ("", "None", "none", "使用线程默认起点", "-1"):
                        try:
                            selected_card_id = int(text_value)
                        except Exception:
                            match = re.search(r"ID\s*[:：]\s*(-?\d+)", text_value)
                            if not match:
                                match = re.search(r"\(\s*ID\s*[:：]\s*(-?\d+)\s*\)", text_value)
                            if match:
                                try:
                                    selected_card_id = int(match.group(1))
                                except Exception:
                                    selected_card_id = None
                if selected_card_id is not None and selected_card_id >= 0:
                    index = combo_box.findData(selected_card_id)
                    if index >= 0:
                        combo_box.setCurrentIndex(index)
                widget = combo_box
                interactive_widget = combo_box

            elif widget_hint == 'card_selector': # Create ComboBox for jump targets
                combo_box = QComboBox(self)
                combo_box.addItem("无", None) # Default option

                # <<< ADDED: Change text for Start Node >>>
                if is_thread_start_task_type(self.task_type): # Check if editing the thread start node
                    combo_box.setItemText(0, "默认连接") # Change display text for the None item
                # <<< END ADDED >>>

                # Populate with card info
                sorted_card_ids = sorted(self.workflow_cards_info.keys())
                for card_id in sorted_card_ids:
                    if self.editing_card_id is not None and card_id == self.editing_card_id:
                        continue # Skip self
                    card_info = self.workflow_cards_info.get(card_id)
                    if card_info:
                        raw_task_type_info, seq_id = card_info
                        task_type_str = str(raw_task_type_info) # Simplified extraction for now
                        item_text = f"{task_type_str} (ID: {card_id})"
                        index = combo_box.count()
                        combo_box.addItem("", card_id) # Add with data
                        combo_box.setItemText(index, item_text) # Set display text
                # Set current value
                target_card_id = None
                if current_value is not None and str(current_value).strip() and str(current_value).lower() != 'none':
                    try: target_card_id = int(current_value)
                    except (ValueError, TypeError): target_card_id = None
                if target_card_id is not None:
                    index_to_select = combo_box.findData(target_card_id)
                    if index_to_select != -1: combo_box.setCurrentIndex(index_to_select)
                    else: combo_box.setCurrentIndex(0) # Default to "无"
                else: combo_box.setCurrentIndex(0)
                widget = combo_box
                interactive_widget = combo_box
                # Store the widget itself for enable/disable based on action
                self.jump_target_widgets[name] = widget

            # <<< Only check param_type if NO specific hint was matched >>>
            elif param_type == 'file' or name.endswith('_path'): # Handle file input
                file_widget_container = QWidget()
                file_layout = QHBoxLayout(file_widget_container)
                file_layout.setContentsMargins(0,0,0,0); file_layout.setSpacing(5)
                line_edit = QLineEdit(str(current_value) if current_value is not None else "")
                browse_button = QPushButton("浏览...")
                browse_button.clicked.connect(lambda checked=False, le=line_edit: self._browse_file(le))
                file_layout.addWidget(line_edit); file_layout.addWidget(browse_button)
                widget = file_widget_container
                interactive_widget = line_edit

            elif param_type == 'text':
                line_edit = QLineEdit(str(current_value) if current_value is not None else "")

                # 检查是否为只读
                if param_def.get('readonly', False):
                    line_edit.setReadOnly(True)
                    # 只读样式由全局主题管理器控制

                # 特殊处理：坐标显示控件设为只读
                if name == 'region_coordinates':
                    line_edit.setReadOnly(True)
                    # 检查是否有坐标数据来初始化显示
                    region_x = self.current_parameters.get('region_x', 0)
                    region_y = self.current_parameters.get('region_y', 0)
                    region_width = self.current_parameters.get('region_width', 0)
                    region_height = self.current_parameters.get('region_height', 0)

                    # 如果坐标都是0，显示未指定状态
                    if region_x == 0 and region_y == 0 and region_width == 0 and region_height == 0:
                        line_edit.setText("未指定识别区域")
                    else:
                        # 显示坐标信息
                        coord_text = f"X={region_x}, Y={region_y}, 宽度={region_width}, 高度={region_height}"
                        line_edit.setText(coord_text)

                widget = line_edit
                interactive_widget = line_edit

            elif param_type == 'int':
                min_val = param_def.get('min', -2147483648)
                max_val = param_def.get('max', 2147483647)
                step = 1
                num_widget_container = QWidget()
                num_layout = QHBoxLayout(num_widget_container)
                num_layout.setContentsMargins(0,0,0,0); num_layout.setSpacing(2)
                line_edit = QLineEdit(str(current_value) if current_value is not None else "0")
                dec_button = QPushButton("-"); inc_button = QPushButton("+")
                dec_button.setObjectName("spinButton"); inc_button.setObjectName("spinButton")
                num_layout.addWidget(line_edit); num_layout.addWidget(dec_button); num_layout.addWidget(inc_button)
                dec_button.clicked.connect(lambda checked=False, le=line_edit, s=step, mn=min_val, mx=max_val: self._decrement_value(le, s, mn, mx))
                inc_button.clicked.connect(lambda checked=False, le=line_edit, s=step, mn=min_val, mx=max_val: self._increment_value(le, s, mn, mx))
                widget = num_widget_container
                interactive_widget = line_edit

            elif param_type == 'float':
                min_val = param_def.get('min', -sys.float_info.max)
                max_val = param_def.get('max', sys.float_info.max)
                decimals = param_def.get('decimals', 2)
                step = 10 ** (-decimals) # Calculate step based on decimals

                num_widget_container = QWidget()
                num_layout = QHBoxLayout(num_widget_container)
                num_layout.setContentsMargins(0,0,0,0); num_layout.setSpacing(2)

                # Use QLineEdit for consistent +/- buttons
                formatted_value = f"{float(current_value):.{decimals}f}" if current_value is not None else f"{0.0:.{decimals}f}"
                line_edit = QLineEdit(formatted_value)
                # Optional: Add QDoubleValidator
                # line_edit.setValidator(QDoubleValidator(min_val, max_val, decimals))

                dec_button = QPushButton("-"); inc_button = QPushButton("+")
                dec_button.setObjectName("spinButton"); inc_button.setObjectName("spinButton")
                num_layout.addWidget(line_edit); num_layout.addWidget(dec_button); num_layout.addWidget(inc_button)

                # Connect buttons (pass decimals)
                dec_button.clicked.connect(lambda checked=False, le=line_edit, s=step, mn=min_val, mx=max_val, dec=decimals:
                                           self._decrement_value(le, s, mn, mx, dec))
                inc_button.clicked.connect(lambda checked=False, le=line_edit, s=step, mn=min_val, mx=max_val, dec=decimals:
                                           self._increment_value(le, s, mn, mx, dec))

                widget = num_widget_container
                interactive_widget = line_edit

            elif param_type == 'bool':
                check_box = QCheckBox()
                check_box.setChecked(bool(current_value) if current_value is not None else False)
                widget = check_box
                interactive_widget = check_box

            elif param_type == 'select' or param_type == 'combo': # Handle both 'select' and 'combo'
                combo_box = QComboBox(self)

                # 特殊处理应用选择器
                if widget_hint == 'app_selector':
                    # 应用选择器，存储引用以便后续更新
                    self.app_selector_combo = combo_box

                options = param_def.get('options', [])

                if isinstance(options, list):
                    combo_box.addItems(options)
                # 工具 修复：正确处理当前值和默认值
                param_default = param_def.get('default')
                current_text = str(current_value) if current_value is not None else str(param_default) if param_default is not None else ""
                index = combo_box.findText(current_text)
                if index != -1:
                    combo_box.setCurrentIndex(index)
                elif options: # Default to first option if current not found
                    combo_box.setCurrentIndex(0)
                widget = combo_box
                interactive_widget = combo_box
                
            elif param_type == 'radio': # Example: Radio button group
                 # Container for the radio buttons themselves
                 radio_button_container = QWidget()
                 # Use QHBoxLayout for side-by-side radio buttons
                 radio_layout_for_buttons = QHBoxLayout(radio_button_container)
                 radio_layout_for_buttons.setContentsMargins(0,0,0,0) # No extra margins

                 button_group = QButtonGroup(radio_button_container) # Parent is the container
                 button_group.setExclusive(True) # Only one can be selected

                 actual_options = param_def.get('options', {}) # e.g. {"fixed": "固定延迟", "random": "随机延迟"}
                 
                 if isinstance(actual_options, dict):
                     for i, (value_key, display_text) in enumerate(actual_options.items()):
                         radio_button = QRadioButton(display_text) # Use Chinese display text
                         radio_button.setProperty("value_key", value_key) # Store the actual value ("fixed", "random")
                         radio_layout_for_buttons.addWidget(radio_button) # Add to QHBoxLayout
                         button_group.addButton(radio_button) # Add to group
                         if str(current_value) == str(value_key): # Compare with the key
                              radio_button.setChecked(True)
                 # Fallback for list-based options if ever needed, though dict is preferred for key-value.
                 elif isinstance(actual_options, list):
                    for i, option_text_or_tuple in enumerate(actual_options):
                        display_text_val = str(option_text_or_tuple)
                        value_key_val = str(option_text_or_tuple)
                        if isinstance(option_text_or_tuple, (tuple, list)) and len(option_text_or_tuple) == 2:
                            value_key_val, display_text_val = str(option_text_or_tuple[0]), str(option_text_or_tuple[1])

                        radio_button = QRadioButton(display_text_val)
                        radio_button.setProperty("value_key", value_key_val)
                        radio_layout_for_buttons.addWidget(radio_button)
                        button_group.addButton(radio_button)
                        if str(current_value) == value_key_val:
                            radio_button.setChecked(True)


                 widget = radio_button_container # This is the QWidget holding the QHBoxLayout of radio buttons
                 interactive_widget = button_group # Store the group to get the checked button

            elif param_type == 'textarea': # Example: Multiline text
                 # 特殊处理：如果是只读的连接目标列表，创建多个独立的框
                 if param_def.get('readonly', False) and name == 'connected_targets':
                     # 创建容器来放置多个独立的卡片框
                     container = QWidget()
                     layout = QVBoxLayout(container)
                     layout.setContentsMargins(0, 0, 0, 0)
                     layout.setSpacing(8)

                     # 直接从 _random_connections 获取连接列表
                     connections = self.current_parameters.get('_random_connections', [])
                     if connections:
                         # 为每个连接创建独立的框
                         for conn in connections:
                             task_type = conn.get('task_type', '')
                             card_id = conn.get('card_id', '')

                             # 创建独立的卡片框
                             card_frame = QFrame()
                             card_frame.setObjectName("randomTargetCard")
                             card_frame.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                             card_frame.customContextMenuRequested.connect(
                                 partial(self._show_random_target_context_menu, card_id, card_frame)
                             )
                             card_layout = QHBoxLayout(card_frame)
                             card_layout.setContentsMargins(8, 6, 8, 6)

                             label = QLabel(f"{task_type} (ID: {card_id})")
                             card_layout.addWidget(label)

                             layout.addWidget(card_frame)
                     else:
                         # 未连接状态，显示提示框
                         hint_frame = QFrame()
                         hint_frame.setObjectName("randomTargetCard")
                         hint_layout = QHBoxLayout(hint_frame)
                         hint_layout.setContentsMargins(8, 6, 8, 6)

                         hint_label = QLabel("未连接任何目标卡片，请从右侧紫色端口拖拽连线")
                         hint_label.setWordWrap(True)
                         hint_layout.addWidget(hint_label)

                         layout.addWidget(hint_frame)

                     # 添加弹簧，将卡片推到顶部
                     layout.addStretch()

                     custom_height = param_def.get('height', 120)
                     container.setMinimumHeight(custom_height)
                     container.setMaximumHeight(max(custom_height, 200))

                     widget = container
                     interactive_widget = container
                 elif widget_hint == 'template_preset_editor':
                     template_widget = QWidget()
                     template_layout = QVBoxLayout(template_widget)
                     template_layout.setContentsMargins(0, 0, 0, 0)
                     template_layout.setSpacing(6)

                     text_edit = QPlainTextEdit()
                     text_edit.setPlainText(str(current_value) if current_value is not None else "")

                     if param_def.get('readonly', False):
                         text_edit.setReadOnly(True)

                     custom_height = param_def.get('height', 80)
                     text_edit.setMinimumHeight(custom_height)
                     text_edit.setMaximumHeight(max(custom_height, 200))
                     text_edit.document().documentLayout().documentSizeChanged.connect(
                         lambda size: self._adjust_text_edit_height(text_edit, size)
                     )

                     preset_combo = QComboBox(self)
                     preset_combo.setObjectName("templatePresetCombo")
                     preset_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                     preset_combo.setMinimumHeight(30)
                     presets = param_def.get("template_presets", []) or []
                     if not isinstance(presets, list):
                         presets = []
                     for item in presets:
                         label_text = ""
                         value_text = ""
                         if isinstance(item, dict):
                             label_text = str(item.get("label", "") or "").strip()
                             value_text = str(item.get("value", "") or "").strip()
                         else:
                             value_text = str(item or "").strip()
                             label_text = value_text
                         if not label_text or not value_text:
                             continue
                         preset_combo.addItem(label_text, value_text)

                     insert_button = QPushButton("插入预设")
                     insert_button.setObjectName("templatePresetInsertButton")
                     insert_button.setProperty("primary", True)
                     insert_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                     insert_button.setMinimumHeight(30)

                     def _insert_template_preset():
                         preset_value = preset_combo.currentData()
                         if preset_value is None:
                             preset_value = preset_combo.currentText()
                         snippet = str(preset_value or "").strip()
                         if not snippet:
                             return
                         if text_edit.toPlainText().strip():
                             text_edit.appendPlainText(snippet)
                         else:
                             text_edit.setPlainText(snippet)
                         text_edit.setFocus()

                     insert_button.clicked.connect(_insert_template_preset)

                     template_layout.addWidget(text_edit)
                     template_layout.addWidget(preset_combo)
                     template_layout.addWidget(insert_button)

                     widget = template_widget
                     interactive_widget = text_edit
                 else:
                     # 普通 textarea
                     text_edit = QPlainTextEdit()
                     text_edit.setPlainText(str(current_value) if current_value is not None else "")

                     # 检查是否为只读
                     if param_def.get('readonly', False):
                         text_edit.setReadOnly(True)

                     # 工具 修复：改进文本输入区域的大小设置
                     custom_height = param_def.get('height', 80)
                     text_edit.setMinimumHeight(custom_height)
                     text_edit.setMaximumHeight(max(custom_height, 200))
                     # 根据内容自动调整高度
                     text_edit.document().documentLayout().documentSizeChanged.connect(
                         lambda size: self._adjust_text_edit_height(text_edit, size)
                     )
                     widget = text_edit
                     interactive_widget = text_edit

            elif param_type == 'button': # Handle button type
                button_text = param_def.get('button_text', label_text)
                button = QPushButton(button_text)
                action_name = str(param_def.get("action", "") or "").strip()
                if action_name:
                    button.clicked.connect(
                        lambda checked=False, param_name=name, current_param_def=param_def:
                        self._invoke_task_button_action(param_name, current_param_def)
                    )

                widget = button
                interactive_widget = button

            elif param_type == 'label':
                # 静态文本标签，只读不可编辑
                info_label = QLabel(label_text)
                info_label.setWordWrap(True)
                info_label.setStyleSheet("color: #666; font-size: 11px; padding: 5px; background-color: #f5f5f5; border-radius: 3px;")
                widget = info_label
                interactive_widget = None
                # label类型不需要左侧的标签名，隐藏它
                label.hide()

            else: # Default to text if type is unknown
                line_edit = QLineEdit(str(current_value) if current_value is not None else "")
                widget = line_edit
                interactive_widget = line_edit

            # --- Add the created widget to the row layout ---
            if widget:
                row_layout.addWidget(widget)
            else:
                 # Placeholder if widget creation failed
                 row_layout.addWidget(QLabel("[Widget Error]"))

            # Store interactive widget for value retrieval
            if interactive_widget:
                # Set object name for easier debugging/styling if needed
                interactive_widget.setObjectName(f"param_{name}")
                self.widgets[name] = interactive_widget

            # Store the container widget (row_widget) for visibility control
            self.row_widgets[name] = row_widget

            # --- Add the completed row to the main parameters layout ---
            self.params_layout.addWidget(row_widget)

        # After creating all widgets, setup connections for conditional visibility etc.
        self._setup_conditional_visibility()
        self._setup_jump_target_connections()
        self._setup_condition_connections() # Ensure this is called AFTER widgets are created

    def _setup_jump_target_connections(self): # <--- ADDED this separate function for clarity
        """Setup connections for jump target dropdowns to enable/disable spin boxes."""
        on_success_combo = self.widgets.get("on_success")
        on_failure_combo = self.widgets.get("on_failure")
        success_target_widget = self.jump_target_widgets.get("success_jump_target_id")
        failure_target_widget = self.jump_target_widgets.get("failure_jump_target_id")

        if isinstance(on_success_combo, QComboBox) and success_target_widget:
            on_success_combo.currentTextChanged.connect(
                lambda text, w=success_target_widget: self._update_jump_target_state(text, w)
            )
            # Initial state
            self._update_jump_target_state(on_success_combo.currentText(), success_target_widget)
            
        if isinstance(on_failure_combo, QComboBox) and failure_target_widget:
            on_failure_combo.currentTextChanged.connect(
                lambda text, w=failure_target_widget: self._update_jump_target_state(text, w)
            )
            # Initial state
            self._update_jump_target_state(on_failure_combo.currentText(), failure_target_widget)

    def _setup_condition_connections(self): # <--- ADDED this separate function for clarity
        """Setup connections for widgets that control conditional visibility of others."""
        for controller_name, controller_widget in self.widgets.items():
            # Check if any other widget depends on this one
            # 修复：处理列表类型的condition
            has_dependents = any(
                (
                    isinstance((pdef.get('condition', pdef.get('conditions'))), dict)
                    and (pdef.get('condition', pdef.get('conditions')) or {}).get('param') == controller_name
                )
                for pdef in self.param_definitions.values()
            )
            
            # --- MODIFICATION START ---
            # Connect signals regardless of dependency for robustness, 
            # especially for checkboxes which might control visibility implicitly.
            # The handler function itself checks conditions.
            if isinstance(controller_widget, QComboBox):
                # Connect only if it controls others to avoid redundant calls if not needed?
                # Let's keep the original logic for ComboBox for now.
                if has_dependents:
                    controller_widget.currentTextChanged.connect(self._handle_conditional_visibility_check)
            elif isinstance(controller_widget, QCheckBox):
                # Always connect CheckBox toggled signal
                controller_widget.toggled.connect(self._handle_conditional_visibility_check)
            elif isinstance(controller_widget, QLineEdit):
                # Connect textChanged only if it controls others
                 if has_dependents:
                    # --- ADD Debugging for LineEdit connection ---
                    # -------------------------------------------
                    controller_widget.textChanged.connect(self._handle_conditional_visibility_check)
            elif isinstance(controller_widget, QButtonGroup): # ADDED: Handle QButtonGroup for radio buttons
                if has_dependents:
                    controller_widget.buttonClicked.connect(self._handle_conditional_visibility_check)
            # --- MODIFICATION END ---
                
            # Original Logic (commented out for comparison)
            # if has_dependents:
            #     if isinstance(controller_widget, QComboBox):
            #         controller_widget.currentTextChanged.connect(self._handle_conditional_visibility_check)
            #     elif isinstance(controller_widget, QCheckBox):
            #         controller_widget.toggled.connect(self._handle_conditional_visibility_check)
            #     elif isinstance(controller_widget, QLineEdit): # Less common, but possible
            #         controller_widget.textChanged.connect(self._handle_conditional_visibility_check)
            #     # Add other widget types (like Radio Buttons in group) if needed
            #     # Note: Radio buttons were connected individually during creation

        # Initial visibility check after all widgets and connections are set up
        self._handle_conditional_visibility_check()

        # 坐标捕获工具已删除

    def _on_ocr_region_selected(self, x: int, y: int, width: int, height: int):
        """处理OCR区域选择器的区域选择信号"""

        selector = self.sender()
        binding_params = {}
        if selector and hasattr(selector, 'get_region_binding_info'):
            try:
                binding_params = selector.get_region_binding_info() or {}
            except Exception:
                binding_params = {}

        # 更新相关的坐标参数
        coordinate_params = {
            'region_x': x,
            'region_y': y,
            'region_width': width,
            'region_height': height
        }
        for key in ('region_hwnd', 'region_window_title', 'region_window_class', 'region_client_width', 'region_client_height'):
            if key in binding_params:
                coordinate_params[key] = binding_params.get(key)

        # 初始化隐藏参数存储（如果不存在）
        if not hasattr(self, '_hidden_params'):
            self._hidden_params = {}

        # 更新对应的控件值和隐藏参数
        updated_count = 0
        for param_name, param_value in coordinate_params.items():
            # 首先检查是否是隐藏参数
            param_def = self.param_definitions.get(param_name, {})
            if param_def.get('type') == 'hidden' or param_def.get('hidden') is True:
                # 更新隐藏参数
                self._hidden_params[param_name] = param_value
                updated_count += 1
            else:
                # 尝试更新可见控件
                widget = self.widgets.get(param_name)
                if widget:
                    if hasattr(widget, 'setValue'):
                        widget.setValue(param_value)
                        updated_count += 1
                    elif hasattr(widget, 'setText'):
                        widget.setText(str(param_value))
                        updated_count += 1
                else:
                    logger.warning(f"未找到控件: {param_name}")

            # 同时更新current_parameters，确保数据一致性
            self.current_parameters[param_name] = param_value

        # 更新坐标显示文本控件
        coord_display = self.widgets.get('region_coordinates')
        if coord_display:
            coord_text = f"X={x}, Y={y}, 宽度={width}, 高度={height}"
            coord_display.setText(coord_text)
        else:
            logger.warning("未找到坐标显示控件")


        # 注意：不在这里恢复对话框显示，由 selection_finished 信号统一处理

    def _on_coordinate_selected(self, selector_name: str, x: int, y: int):
        """处理坐标选择完成事件 - 完全重写的简洁版本"""

        # 检查是否是滚动坐标选择器
        if selector_name == 'scroll_coordinate_selector':
            # 更新滚动起始位置显示参数
            position_widget = self.widgets.get('scroll_start_position')
            if position_widget and hasattr(position_widget, 'setText'):
                position_widget.setText(f"{x},{y}")

            # 更新current_parameters
            self.current_parameters['scroll_start_position'] = f"{x},{y}"
            return

        # 检查是否是拖拽坐标选择器
        if selector_name == 'drag_coordinate_selector':
            # 更新拖拽起始位置显示参数
            position_widget = self.widgets.get('drag_start_position')
            if position_widget and hasattr(position_widget, 'setText'):
                position_widget.setText(f"{x},{y}")

            # 更新current_parameters
            self.current_parameters['drag_start_position'] = f"{x},{y}"
            return

        # 检查是否是合并的坐标参数（如滚动起始位置）
        if selector_name in ['scroll_start_position']:
            # 处理合并的坐标参数
            coordinate_widget = self.widgets.get(selector_name)
            if coordinate_widget and hasattr(coordinate_widget, 'setText'):
                coordinate_widget.setText(f"{x},{y}")

            # 更新current_parameters
            self.current_parameters[selector_name] = f"{x},{y}"
            return

        # 1. 直接更新坐标输入框（原有逻辑）
        x_widget = self.widgets.get('coordinate_x')
        y_widget = self.widgets.get('coordinate_y')

        if x_widget and hasattr(x_widget, 'setText'):
            x_widget.setText(str(x))

        if y_widget and hasattr(y_widget, 'setText'):
            y_widget.setText(str(y))

        # 2. 强制设置操作模式为坐标点击
        operation_mode_widget = self.widgets.get('operation_mode')
        if operation_mode_widget and isinstance(operation_mode_widget, QComboBox):
            # 阻止信号避免递归
            operation_mode_widget.blockSignals(True)
            for i in range(operation_mode_widget.count()):
                if operation_mode_widget.itemText(i) == '坐标点击':
                    operation_mode_widget.setCurrentIndex(i)
                    break
            operation_mode_widget.blockSignals(False)

        # 3. 直接更新current_parameters
        self.current_parameters['coordinate_x'] = x
        self.current_parameters['coordinate_y'] = y
        self.current_parameters['operation_mode'] = '坐标点击'

        # 4. 设置标记表示使用了坐标工具
        self._coordinate_tool_used = True


    def _on_motion_region_selected(self, selector_name: str, x: int, y: int, width: int, height: int):
        """处理移动检测区域选择完成事件"""

        # 更新隐藏的坐标参数
        self.current_parameters['minimap_x'] = x
        self.current_parameters['minimap_y'] = y
        self.current_parameters['minimap_width'] = width
        self.current_parameters['minimap_height'] = height

        # 更新移动识别区域显示参数
        region_text = f"X={x}, Y={y}, 宽度={width}, 高度={height}"
        region_widget = self.widgets.get('motion_detection_region')
        if region_widget and hasattr(region_widget, 'setText'):
            region_widget.setText(region_text)

        # 更新current_parameters
        self.current_parameters['motion_detection_region'] = region_text


    def _on_image_region_selected(self, selector_name: str, x: int, y: int, width: int, height: int):
        """处理图片识别区域选择完成事件"""

        # 初始化隐藏参数存储（如果不存在）
        if not hasattr(self, '_hidden_params'):
            self._hidden_params = {}

        # 更新隐藏的坐标参数
        coordinate_params = {
            'recognition_region_x': x,
            'recognition_region_y': y,
            'recognition_region_width': width,
            'recognition_region_height': height
        }

        # 更新隐藏参数和current_parameters
        for param_name, param_value in coordinate_params.items():
            self._hidden_params[param_name] = param_value
            self.current_parameters[param_name] = param_value

        # 更新识别区域选择器按钮的显示文本
        region_widget = self.widgets.get('image_region_selector')
        if region_widget and hasattr(region_widget, 'select_button'):
            # 获取目标窗口信息
            target_window = self._get_bound_window_title()
            if width == 0 and height == 0:
                # 未选择区域
                if target_window:
                    button_text = f"框选区域 (目标: {target_window})"
                else:
                    button_text = "点击框选识别区域"
            else:
                # 已选择区域，显示区域信息
                button_text = f"区域: X={x}, Y={y}, {width}x{height}"

            region_widget.select_button.setText(button_text)


    def _on_coordinate_selection_started(self):
        """坐标选择开始时的处理"""

        # 停止并回收之前的恢复定时器（如果存在）
        if hasattr(self, '_restore_timer') and self._restore_timer is not None:
            try:
                if self._restore_timer.isActive():
                    self._restore_timer.stop()
            except RuntimeError:
                pass
            try:
                self._restore_timer.deleteLater()
            except RuntimeError:
                pass
            self._restore_timer = None

        # 工具 修复：不使用hide()，而是最小化对话框，避免触发关闭事件
        self.showMinimized()

        # 设置一个较短的定时器作为备用恢复机制
        from PySide6.QtCore import QTimer
        self._restore_timer = QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.timeout.connect(self._restore_dialog_visibility)
        # 5秒后自动恢复显示（缩短时间，主要依靠选择完成信号）
        self._restore_timer.start(5000)

    def _on_coordinate_selection_finished(self):
        """坐标选择结束时的处理"""

        # 停止备用恢复定时器
        if hasattr(self, '_restore_timer') and self._restore_timer.isActive():
            self._restore_timer.stop()

        # 立即恢复对话框显示
        self._restore_dialog_visibility()

    def _on_ocr_selection_started(self):
        """OCR区域选择开始时的处理"""

        # 停止并回收之前的恢复定时器（如果存在）
        if hasattr(self, '_restore_timer') and self._restore_timer is not None:
            try:
                if self._restore_timer.isActive():
                    self._restore_timer.stop()
            except RuntimeError:
                pass
            try:
                self._restore_timer.deleteLater()
            except RuntimeError:
                pass
            self._restore_timer = None

        # 临时隐藏对话框，让目标窗口完全可见
        self.hide()

        # 设置一个较短的定时器作为备用恢复机制
        from PySide6.QtCore import QTimer
        self._restore_timer = QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.timeout.connect(self._restore_dialog_visibility)
        # 5秒后自动恢复显示（缩短时间，主要依靠选择完成信号）
        self._restore_timer.start(5000)

    def _on_ocr_selection_finished(self):
        """OCR区域选择结束时的处理（无论成功还是取消）"""

        # 停止备用恢复定时器
        if hasattr(self, '_restore_timer') and self._restore_timer.isActive():
            self._restore_timer.stop()

        # 立即恢复对话框显示
        self._restore_dialog_visibility()

    def _restore_dialog_visibility(self):
        """恢复对话框显示"""
        # 工具 修复：从最小化状态恢复到正常状态
        self.showNormal()
        show_and_activate_overlay(self, log_prefix='参数对话框恢复', focus=True)

    def _get_enabled_bound_windows_for_selector(self) -> List[Dict[str, Any]]:
        try:
            current_widget = self.parent()
            level = 0
            while current_widget and level < 10:
                bound_windows = None

                if hasattr(current_widget, "bound_windows") and isinstance(current_widget.bound_windows, list):
                    bound_windows = current_widget.bound_windows
                elif hasattr(current_widget, "config"):
                    config = current_widget.config
                    if isinstance(config, dict):
                        bound_windows = get_active_bound_windows(config)
                    else:
                        active_windows = getattr(config, "active_bound_windows", None)
                        if isinstance(active_windows, list):
                            bound_windows = active_windows
                        elif hasattr(config, "bound_windows"):
                            bound_windows = config.bound_windows or []

                if isinstance(bound_windows, list):
                    enabled_windows = [
                        item for item in bound_windows
                        if isinstance(item, dict) and item.get("enabled", True)
                    ]
                    if enabled_windows:
                        return enabled_windows

                current_widget = current_widget.parent()
                level += 1
        except Exception:
            return []

        return []

    def _apply_bound_window_to_selector(self, selector) -> bool:
        try:
            bound_window = None
            for item in self._get_enabled_bound_windows_for_selector():
                if isinstance(item, dict):
                    bound_window = item
                    break

            target_hwnd = bound_window.get("hwnd") if bound_window else None
            target_title = ""
            if bound_window:
                target_title = str(bound_window.get("title") or "").strip()
            if not target_title:
                target_title = str(self._get_bound_window_title() or "").strip()

            if target_hwnd:
                if hasattr(selector, "set_target_window_hwnd"):
                    selector.set_target_window_hwnd(target_hwnd)
                    return True
                if hasattr(selector, "set_target_hwnd"):
                    selector.set_target_hwnd(target_hwnd)
                    return True
                if hasattr(selector, "target_window_hwnd"):
                    selector.target_window_hwnd = target_hwnd
                    return True

            if target_title:
                if hasattr(selector, "set_target_window"):
                    selector.set_target_window(target_title)
                    return True
                if hasattr(selector, "target_window_title"):
                    selector.target_window_title = target_title
                    return True

        except Exception:
            return False

        return False

    def _get_bound_window_title(self) -> Optional[str]:
        """获取当前绑定的窗口标题"""
        try:

            # 向上查找主窗口，直到找到有config或runner属性的窗口
            current_widget = self.parent()
            level = 0

            while current_widget and level < 10:  # 最多向上查找10层

                # 检查是否是主窗口（任务编辑器）
                if hasattr(current_widget, 'config'):
                    config = current_widget.config
                    if isinstance(config, dict):
                        target_window_title = get_active_target_window_title(config)
                    else:
                        target_window_title = getattr(config, 'active_target_window_title', None) or getattr(config, 'target_window_title', None)
                    if target_window_title:
                        return target_window_title

                # 检查是否有runner属性
                if hasattr(current_widget, 'runner'):
                    runner = current_widget.runner
                    if hasattr(runner, 'target_window_title'):
                        target_window_title = runner.target_window_title
                        if target_window_title:
                            return target_window_title

                # 检查是否有直接的target_window_title属性
                if hasattr(current_widget, 'target_window_title'):
                    target_window_title = current_widget.target_window_title
                    if target_window_title:
                        return target_window_title

                # 向上查找父窗口
                current_widget = current_widget.parent()
                level += 1

            return None

        except Exception as e:
            logger.exception(f"获取绑定窗口标题时出错: {e}")
            return None

    def _update_threshold_visibility(self, selected_method: str):
        """Updates visibility of the threshold value row."""
        show_threshold = (selected_method == "二值化")
        threshold_widget = self.row_widgets.get("threshold_value")
        if threshold_widget:
            threshold_widget.setVisible(show_threshold)
            # Optional: Adjust dialog size if visibility changes significantly
            # self.adjustSize()
            
    def _setup_conditional_visibility(self):
        """Sets up the initial state and connects signals for conditionally visible/enabled widgets."""
        # Initial visibility for pre-conditions
        self._update_pre_condition_visibility(self.current_parameters.get("pre_condition_type", "无"))
        # Initial visibility for threshold value
        self._update_threshold_visibility(self.current_parameters.get("preprocessing_method", "无"))
        
        # Initial check for all conditional visibilities
        self._handle_conditional_visibility_check()

        self.adjustSize() # Adjust dialog size after initial setup

    def _start_element_picking(self):
        """开始元素拾取 - 按F2确认"""
        try:
            from utils.element_picker import ElementPicker, ElementInfo

            if not ElementPicker.is_available():
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "错误", "UIAutomation模块不可用，无法拾取元素")
                return

            # 更新按钮状态
            if hasattr(self, '_element_picker_button') and self._element_picker_button:
                self._element_picker_button.setText("拾取中... (按F2确认, ESC取消)")
                self._element_picker_button.setEnabled(False)

            # 最小化对话框
            self.showMinimized()

            # 启动键盘监听线程
            import threading
            self._picking_active = True

            def wait_for_hotkey():
                try:
                    from utils.uiautomation_runtime import import_uiautomation, uiautomation_thread_context

                    import keyboard
                    auto = import_uiautomation()
                    with uiautomation_thread_context(auto):
                        while self._picking_active:
                            if keyboard.is_pressed('f2'):
                                self._picking_active = False
                                # 拾取元素
                                element = auto.ControlFromCursor()
                                if element:
                                    info = ElementInfo(
                                        name=element.Name or "",
                                        automation_id=element.AutomationId or "",
                                        class_name=element.ClassName or "",
                                        control_type=element.ControlTypeName or ""
                                    )
                                    from PySide6.QtCore import QMetaObject, Qt
                                    QMetaObject.invokeMethod(self, "_on_element_picked", Qt.QueuedConnection)
                                    self._picked_info = info
                                else:
                                    self._picked_info = None
                                    from PySide6.QtCore import QMetaObject, Qt
                                    QMetaObject.invokeMethod(self, "_on_element_picked", Qt.QueuedConnection)
                                break
                            elif keyboard.is_pressed('escape'):
                                self._picking_active = False
                                self._picked_info = None
                                from PySide6.QtCore import QMetaObject, Qt
                                QMetaObject.invokeMethod(self, "_on_picking_cancelled", Qt.QueuedConnection)
                                break
                            import time
                            time.sleep(0.05)
                except Exception as e:
                    logger.error(f"键盘监听失败: {e}")
                    self._picking_active = False
                    self._picked_info = None
                    from PySide6.QtCore import QMetaObject, Qt
                    QMetaObject.invokeMethod(self, "_on_element_picked", Qt.QueuedConnection)

            thread = threading.Thread(target=wait_for_hotkey, daemon=True)
            thread.start()

        except Exception as e:
            logger.error(f"启动元素拾取失败: {e}")
            if hasattr(self, '_element_picker_button') and self._element_picker_button:
                self._element_picker_button.setText("拾取元素 (按F2确认)")
                self._element_picker_button.setEnabled(True)

    def _on_picking_cancelled(self):
        """拾取被取消"""
        self.showNormal()
        show_and_activate_overlay(self, log_prefix='参数对话框恢复', focus=True)
        if hasattr(self, '_element_picker_button') and self._element_picker_button:
            self._element_picker_button.setText("拾取元素 (按F2确认)")
            self._element_picker_button.setEnabled(True)

    def _on_element_picked(self):
        """元素拾取完成的回调"""
        # 恢复对话框
        self.showNormal()
        show_and_activate_overlay(self, log_prefix='参数对话框恢复', focus=True)

        # 恢复按钮状态
        if hasattr(self, '_element_picker_button') and self._element_picker_button:
            self._element_picker_button.setText("拾取元素 (3秒后开始)")
            self._element_picker_button.setEnabled(True)

        info = getattr(self, '_picked_info', None)
        if info is None:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "拾取失败", "未能获取到元素信息，请确保鼠标在目标元素上")
            return

        # 填充元素属性到对应的输入框
        element_fields = {
            'element_name': info.name,
            'element_automation_id': info.automation_id,
            'element_class_name': info.class_name,
            'element_control_type': info.control_type
        }

        filled_count = 0
        for field_name, value in element_fields.items():
            if value and field_name in self.widgets:
                widget = self.widgets[field_name]
                if isinstance(widget, QLineEdit):
                    widget.setText(value)
                    filled_count += 1
                elif isinstance(widget, QComboBox):
                    # 控件类型是下拉框
                    index = widget.findText(value)
                    if index >= 0:
                        widget.setCurrentIndex(index)
                        filled_count += 1
                    else:
                        # 尝试添加ControlType后缀
                        if not value.endswith('Control'):
                            value_with_suffix = value + 'Control'
                            index = widget.findText(value_with_suffix)
                            if index >= 0:
                                widget.setCurrentIndex(index)
                                filled_count += 1

        # 显示结果提示
        from PySide6.QtWidgets import QMessageBox
        if filled_count > 0:
            msg = f"已填充 {filled_count} 个属性:\n"
            if info.name:
                msg += f"  Name: {info.name}\n"
            if info.automation_id:
                msg += f"  AutomationId: {info.automation_id}\n"
            if info.class_name:
                msg += f"  ClassName: {info.class_name}\n"
            if info.control_type:
                msg += f"  ControlType: {info.control_type}"
            QMessageBox.information(self, "拾取成功", msg)
        else:
            QMessageBox.warning(self, "拾取结果", "元素没有可用的属性信息")

    def _browse_color(self, line_edit_widget: QLineEdit):
        """打开汉化的Qt颜色选择对话框"""
        current_color_str = line_edit_widget.text()
        initial_color = QColor(255, 0, 0) # Default red color
        try:
            parts = [int(c.strip()) for c in current_color_str.split(',')]
            if len(parts) == 3 and all(0 <= c <= 255 for c in parts):
                initial_color = QColor(parts[0], parts[1], parts[2])
        except ValueError:
            pass # Keep default color if current string is invalid

        dialog = QColorDialog(self)
        dialog.setWindowTitle("选择目标颜色")
        dialog.setCurrentColor(initial_color)

        # 强制使用非原生对话框以确保可以修改按钮文本
        dialog.setOption(QColorDialog.DontUseNativeDialog, True)

        # 手动汉化按钮文本
        def translate_color_dialog_buttons():
            # 查找并翻译按钮
            for button in dialog.findChildren(QPushButton):
                button_text = button.text().lower()
                if 'ok' in button_text or button_text == '&ok':
                    button.setText("确定(&O)")
                elif 'cancel' in button_text or button_text == '&cancel':
                    button.setText("取消(&C)")
                elif 'pick screen color' in button_text or 'screen' in button_text:
                    button.setText("屏幕取色")
                elif 'add to custom colors' in button_text or 'custom' in button_text:
                    button.setText("添加到自定义颜色")

        # 使用定时器延迟执行翻译，确保对话框完全加载
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, translate_color_dialog_buttons)

        if dialog.exec() == QDialog.Accepted:
            color = dialog.selectedColor()
            if color.isValid():
                rgb_str = f"{color.red()},{color.green()},{color.blue()}"
                line_edit_widget.setText(rgb_str)

    def _populate_color_list(self, color_list: QListWidget, color_string: str):
        from PySide6.QtWidgets import QListWidgetItem

        color_list.clear()
        color_string = str(color_string or "").strip()
        if not color_string:
            return

        parts = color_string.split('|')
        for index, part in enumerate(parts):
            item_text = str(part or "").strip()
            if not item_text:
                continue
            try:
                values = [int(v.strip()) for v in item_text.split(',') if v.strip()]
            except Exception:
                continue

            if index == 0 and len(values) >= 3:
                r, g, b = values[:3]
                display_text = f"基准点 RGB({r},{g},{b})"
                color = QColor(r, g, b)
            elif len(values) >= 5:
                offset_x, offset_y, r, g, b = values[:5]
                display_text = f"偏移({offset_x:+d},{offset_y:+d}) RGB({r},{g},{b})"
                color = QColor(r, g, b)
            else:
                continue

            pixmap = QPixmap(16, 16)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setBrush(QBrush(color))
            painter.setPen(QColor(120, 120, 120))
            painter.drawRect(0, 0, 15, 15)
            painter.end()
            color_list.addItem(QListWidgetItem(QIcon(pixmap), display_text))

    def _create_color_coordinate_dialog(self, param_name: str):
        from ui.selectors.color_coordinate_picker import ColorCoordinatePickerWidget

        dialog = QDialog(self)
        dialog.setWindowTitle("屏幕取色")
        dialog.setMinimumSize(520, 400)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        info_label = QLabel(
            "左键可连续取色。\n"
            "第一个点为基准点，后续点自动记录相对偏移。\n"
            "完成后点“确定”保存。"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        color_picker = ColorCoordinatePickerWidget(dialog)
        target_hwnd = self._get_target_window_hwnd()
        if target_hwnd:
            color_picker.set_target_hwnd(target_hwnd)

        if param_name == "arrow_color":
            region_x = int(self.current_parameters.get("minimap_x", 0) or 0)
            region_y = int(self.current_parameters.get("minimap_y", 0) or 0)
            region_w = int(self.current_parameters.get("minimap_width", 0) or 0)
            region_h = int(self.current_parameters.get("minimap_height", 0) or 0)
            if region_w > 0 and region_h > 0:
                color_picker.set_search_region(region_x, region_y, region_w, region_h)
        elif self.current_parameters.get("search_region_enabled", False):
            region_x = int(self.current_parameters.get("search_region_x", 0) or 0)
            region_y = int(self.current_parameters.get("search_region_y", 0) or 0)
            region_w = int(self.current_parameters.get("search_region_width", 0) or 0)
            region_h = int(self.current_parameters.get("search_region_height", 0) or 0)
            if region_w > 0 and region_h > 0:
                color_picker.set_search_region(region_x, region_y, region_w, region_h)

        initial_value = str(self.current_parameters.get(param_name, "") or "").strip()
        if initial_value:
            color_picker.set_color_string(initial_value)

        layout.addWidget(color_picker)

        button_row = QHBoxLayout()
        button_row.addStretch()
        ok_button = QPushButton("确定")
        cancel_button = QPushButton("取消")
        ok_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)
        button_row.addWidget(ok_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)
        return dialog, color_picker

    def _select_color_rgb_list(self, color_list: QListWidget, param_name: str):
        try:
            from PySide6.QtCore import QEventLoop
            from PySide6.QtWidgets import QMessageBox

            dialog, color_picker = self._create_color_coordinate_dialog(param_name)
            dialog.setModal(False)
            show_and_activate_overlay(dialog, log_prefix='颜色坐标对话框', focus=True)

            loop = QEventLoop()
            dialog.finished.connect(loop.quit)
            loop.exec()

            if dialog.result() != QDialog.DialogCode.Accepted:
                return

            color_string = color_picker.get_color_string()
            if not color_string:
                QMessageBox.warning(self, "提示", "未选择任何颜色")
                return

            self._populate_color_list(color_list, color_string)
            color_list.setProperty("raw_color_data", color_string)
            item_count = color_list.count()
            color_list.setFixedHeight(min(150, max(60, item_count * 30 + 10)))
            self.current_parameters[param_name] = color_string
        except Exception as e:
            logger.error(f"颜色选择器启动失败: {e}")
            preview_label.clear()

    def _browse_file(self, line_edit_widget: QLineEdit):
        """Opens a file dialog to select a file."""
        # Consider filtering based on expected file types if available in param_def
        file_path, _ = QFileDialog.getOpenFileName(self, "选择文件")
        if file_path:
            line_edit_widget.setText(file_path)

            # 特殊处理：如果是任务模块文件选择，显示模块信息
            if hasattr(self, 'task_type') and self.task_type == "任务模块":
                self._show_module_info(file_path)

    def _get_dynamic_options(self, func_name: str, param_value: str, default_options=None) -> list:
        """根据函数名和参数值获取动态选项列表"""
        fallback_options = (
            [str(item or "").strip() for item in default_options if str(item or "").strip()]
            if isinstance(default_options, (list, tuple, set))
            else ["全部类别"]
        )
        try:
            from tasks import get_task_module
            task_module = get_task_module(self.task_type)
            if task_module and hasattr(task_module, func_name):
                func = getattr(task_module, func_name)
                options = func(param_value)
                if isinstance(options, (list, tuple, set)):
                    normalized = [str(item or "").strip() for item in options if str(item or "").strip()]
                    if normalized:
                        return normalized
            return fallback_options
        except Exception as e:
            logger.warning(f"获取动态选项失败: {e}")
            return fallback_options

    def _invoke_task_button_action(self, param_name: str, param_def: Dict[str, Any]) -> None:
        action_name = str(param_def.get("action", "") or "").strip()
        if not action_name:
            return
        try:
            from tasks import get_task_module

            task_module = get_task_module(self.task_type)
            if task_module is None or not hasattr(task_module, action_name):
                return

            current_params = self.get_parameters()
            action_func = getattr(task_module, action_name)
            action_func(
                current_params,
                target_hwnd=self._get_target_hwnd(),
                main_window=self.parent(),
                parameter_dialog=self,
                parameter_panel=self,
                param_name=param_name,
            )
        except Exception as exc:
            logger.error("参数对话框执行按钮动作失败: %s", exc, exc_info=True)

    def _show_module_info(self, file_path: str):
        """显示模块文件信息"""
        try:
            import os
            import json

            # 确定要读取的文件
            if file_path.endswith('.emodule'):
                # 加密模块，尝试读取缓存文件
                cache_file = file_path.replace('.emodule', '.cache.json')
                if os.path.exists(cache_file):
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        module_data = json.load(f)
                    info_source = "缓存"
                else:
                    # 没有缓存，尝试使用加密模块处理器
                    try:
                        import importlib
                        crypto_module = importlib.import_module('utils.module_crypto')
                        ModuleCrypto = getattr(crypto_module, 'ModuleCrypto')
                        crypto = ModuleCrypto()
                        basic_info = crypto.get_module_info_from_encrypted(file_path)
                        if basic_info:
                            self._show_basic_module_info(basic_info)
                        return
                    except (ImportError, ModuleNotFoundError, AttributeError):
                        # 加密模块处理器不可用，显示提示信息
                        self._show_encrypted_module_fallback_info(file_path)
                        return
            else:
                # 明文模块
                with open(file_path, 'r', encoding='utf-8') as f:
                    module_data = json.load(f)
                info_source = "文件"

            # 提取模块信息
            module_info = module_data.get('module_info', {})
            workflow_info = module_data.get('workflow', {})

            # 更新显示
            info_text = f"模块名称: {module_info.get('name', '未知')}\n"
            info_text += f"版本: {module_info.get('version', '未知')}\n"
            info_text += f"作者: {module_info.get('author', '未知')}\n"
            info_text += f"描述: {module_info.get('description', '无')}\n"
            info_text += f"卡片数量: {len(workflow_info.get('cards', []))}\n"
            info_text += f"数据来源: {info_source}"

            # 显示在状态栏或工具提示中
            if hasattr(self, 'setToolTip'):
                self.setToolTip(info_text)

        except Exception as e:
            logger.error(f"显示模块信息失败: {e}", exc_info=True)

    def _show_basic_module_info(self, basic_info: dict):
        """显示加密模块的基本信息"""
        info_text = f"模块名称: {basic_info.get('name', '未知')}\n"
        info_text += f"文件大小: {basic_info.get('file_size', 0)} 字节\n"
        info_text += f"状态: 加密模块（需要先导入解密）"

        if hasattr(self, 'setToolTip'):
            self.setToolTip(info_text)

    def _show_encrypted_module_fallback_info(self, file_path: str):
        """显示加密模块的回退信息（当解密器不可用时）"""
        import os
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        file_name = os.path.basename(file_path)

        info_text = f"文件名: {file_name}\n"
        info_text += f"文件大小: {file_size} 字节\n"
        info_text += f"类型: 加密模块文件\n"
        info_text += f"状态: 解密器不可用，无法读取详细信息"

        if hasattr(self, 'setToolTip'):
            self.setToolTip(info_text)

    def _update_module_info_display(self, module_info: Dict[str, Any]):
        """更新模块信息显示"""
        try:
            # 更新模块信息标签
            info_fields = {
                'module_name': module_info.get('name', '未知模块'),
                'module_version': module_info.get('version', '未知'),
                'module_description': module_info.get('description', '无描述')
            }

            for field_name, value in info_fields.items():
                if field_name in self.row_widgets:
                    row_widget = self.row_widgets[field_name]
                    # 查找标签控件并更新文本
                    for child in row_widget.findChildren(QLabel):
                        if hasattr(child, 'setText'):
                            child.setText(str(value))
                            break

        except Exception as e:
            logger.error(f"更新模块信息显示失败: {e}")

    def _add_dynamic_module_params(self, module_params: Dict[str, Dict[str, Any]]):
        """动态添加模块参数"""
        try:
            if not module_params:
                return

            # 清除之前的动态参数
            self._clear_dynamic_module_params()

            # 添加分隔符
            separator_row = self._create_separator_row("模块参数")
            self.form_layout.addRow(separator_row)
            self.dynamic_param_widgets.append(separator_row)

            # 添加每个模块参数
            for param_name, param_def in module_params.items():
                self._add_module_parameter_row(param_name, param_def)

            # 调整对话框大小
            self.adjustSize()

        except Exception as e:
            logger.error(f"添加动态模块参数失败: {e}")

    def _clear_dynamic_module_params(self):
        """清除动态模块参数"""
        if not hasattr(self, 'dynamic_param_widgets'):
            self.dynamic_param_widgets = []
            return

        # 移除所有动态参数控件
        for widget in self.dynamic_param_widgets:
            if widget:
                self.form_layout.removeRow(widget)
                widget.deleteLater()

        self.dynamic_param_widgets.clear()

    def _add_module_parameter_row(self, param_name: str, param_def: Dict[str, Any]):
        """添加单个模块参数行"""
        try:
            # 获取当前参数值
            current_value = self.parameters.get(param_name, param_def.get('default'))

            # 创建参数控件
            param_type = param_def.get('type', 'string')
            label_text = param_def.get('label', param_name)
            tooltip = param_def.get('tooltip', '')

            # 创建标签
            label = QLabel(f"{label_text}:")
            if tooltip:
                label.setToolTip(tooltip)

            # 创建输入控件
            widget, interactive_widget = self._create_parameter_widget(
                param_type, current_value, param_def
            )

            if tooltip and interactive_widget:
                interactive_widget.setToolTip(tooltip)

            # 添加到布局
            self.form_layout.addRow(label, widget)

            # 存储控件引用
            self.row_widgets[param_name] = widget
            self.interactive_widgets[param_name] = interactive_widget
            self.dynamic_param_widgets.append(widget)

        except Exception as e:
            logger.error(f"添加模块参数行失败 {param_name}: {e}")

    def _create_parameter_widget(self, param_type: str, current_value: Any,
                               param_def: Dict[str, Any]) -> Tuple[QWidget, QWidget]:
        """创建参数控件"""
        if param_type == 'string':
            widget = QLineEdit(str(current_value) if current_value is not None else "")
            return widget, widget

        elif param_type == 'int':
            widget = NoWheelSpinBox()
            widget.setRange(param_def.get('min', -999999), param_def.get('max', 999999))
            widget.setValue(int(current_value) if current_value is not None else 0)
            return widget, widget

        elif param_type == 'float':
            widget = NoWheelDoubleSpinBox()
            widget.setRange(param_def.get('min', -999999.0), param_def.get('max', 999999.0))
            widget.setDecimals(param_def.get('decimals', 2))
            widget.setValue(float(current_value) if current_value is not None else 0.0)
            return widget, widget

        elif param_type == 'bool':
            widget = QCheckBox()
            widget.setChecked(bool(current_value) if current_value is not None else False)
            return widget, widget

        elif param_type == 'select':
            widget = QComboBox(self)
            options = param_def.get('options', [])
            widget.addItems(options)
            if current_value and current_value in options:
                widget.setCurrentText(str(current_value))
            return widget, widget

        elif param_type == 'file':
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(5)

            line_edit = QLineEdit(str(current_value) if current_value is not None else "")
            browse_button = QPushButton("浏览...")

            file_filter = param_def.get('file_filter', '所有文件 (*)')
            browse_button.clicked.connect(
                lambda: self._browse_file_with_filter(line_edit, file_filter)
            )

            layout.addWidget(line_edit)
            layout.addWidget(browse_button)

            return container, line_edit

        else:
            # 默认为字符串输入
            widget = QLineEdit(str(current_value) if current_value is not None else "")
            return widget, widget

    def _browse_file_with_filter(self, line_edit_widget: QLineEdit, file_filter: str):
        """带文件过滤器的文件浏览"""
        file_path, _ = QFileDialog.getOpenFileName(self, "选择文件", "", file_filter)
        if file_path:
            line_edit_widget.setText(file_path)

    def _create_separator_row(self, title: str) -> QWidget:
        """创建分隔符行"""
        separator = QFrame()
        separator.setFrameStyle(QFrame.Shape.HLine | QFrame.Shadow.Sunken)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 10, 0, 5)

        title_label = QLabel(title)
        # 样式由全局主题管理器控制

        layout.addWidget(title_label)
        layout.addWidget(separator)

        return container

    def _update_pre_condition_visibility(self, selected_condition_type: str):
        """Updates visibility of pre-condition parameter rows within the dialog."""
        
        image_params = ["pre_image_path", "pre_confidence"]
        counter_params = ["pre_counter_name", "pre_comparison_type", "pre_target_value"]

        show_image = (selected_condition_type == "查找图片")
        show_counter = (selected_condition_type == "计数器判断")

        # Iterate through the stored row widgets
        for name, row_widget in self.row_widgets.items():
             is_image_param = name in image_params
             is_counter_param = name in counter_params

             if is_image_param:
                  row_widget.setVisible(show_image)
             elif is_counter_param:
                  row_widget.setVisible(show_counter)
                  
        # No need to adjust size here, let the caller handle it if needed
        # self.adjustSize() 

    def _update_jump_target_state(self, dropdown_text: str, target_widget: QWidget):
        """Enables/disables the jump target ID widget/container based on dropdown selection."""
        # --- MODIFIED: Expect QComboBox for jump targets ---
        is_jump = '跳转' in str(dropdown_text)
        if isinstance(target_widget, QComboBox):
             target_widget.setEnabled(is_jump)
             if not is_jump:
                 # If action is not jump, force selection to "无" (index 0)
                 target_widget.setCurrentIndex(0)
        else:
             pass
        # --- END MODIFICATION ---

        # Force style update to ensure state changes apply immediately
        target_widget.style().unpolish(target_widget)
        target_widget.style().polish(target_widget)
        target_widget.update() # Request a repaint just in case

        # Optional: Clear the value if disabled?
        # if not is_jump and isinstance(target_widget, QLineEdit):
        #     target_widget.setText("0") # Or some other default/None indicator if possible
        # elif not is_jump and isinstance(target_widget, QWidget):
             # Find the line edit inside the container
        #      lineEdit = target_widget.findChild(QLineEdit)
        #      if lineEdit:
        #          lineEdit.setText("0")

    def _get_target_hwnd(self):
        """获取目标窗口句柄"""
        try:

            parent_window = self.parent()

            # 尝试从父窗口获取当前绑定的窗口句柄
            if hasattr(parent_window, 'current_target_hwnd'):
                hwnd = parent_window.current_target_hwnd
                return hwnd

            if hasattr(parent_window, 'config') and isinstance(parent_window.config, dict):
                hwnd = get_active_bound_window_hwnd(parent_window.config)
                if hwnd:
                    return hwnd

            if hasattr(parent_window, 'bound_windows'):
                bound_windows = parent_window.bound_windows
                # 从绑定窗口列表中获取第一个启用的窗口
                for window_info in bound_windows:
                    if window_info.get('enabled', True):
                        hwnd = window_info.get('hwnd')
                        return hwnd

            if hasattr(parent_window, 'current_target_window_title'):
                # 根据窗口标题查找窗口句柄
                window_title = parent_window.current_target_window_title
                if window_title:
                    hwnd = resolve_unique_window_hwnd(window_title)
                    return hwnd

            if hasattr(parent_window, 'config') and isinstance(parent_window.config, dict):
                window_title = get_active_target_window_title(parent_window.config)
                if window_title:
                    hwnd = resolve_unique_window_hwnd(window_title)
                    return hwnd

            # 尝试其他可能的属性
            parent_attrs = [attr for attr in dir(parent_window) if 'window' in attr.lower() or 'hwnd' in attr.lower()]

            logger.warning("无法获取目标窗口句柄")
            return None

        except Exception as e:
            logger.error(f"获取目标窗口句柄时出错: {e}")
            logger.exception(f"获取目标窗口句柄时出错: {e}")
            return None

    # 样式由全局主题管理器控制，不再使用局部样式表

    def _adjust_value(self, line_edit: QLineEdit, increment: bool, step: float, 
                      min_val: float, max_val: float, decimals: Optional[int] = None):
        """Helper to increment or decrement the value in a QLineEdit."""
        current_text = line_edit.text()
        try:
            if decimals is not None: # Handling float
                current_value = float(current_text)
                new_value = current_value + step if increment else current_value - step
                # Clamp within min/max
                new_value = max(min_val, min(max_val, new_value))
                # Format back to string with correct decimals
                line_edit.setText(f"{new_value:.{decimals}f}")
            else: # Handling int
                current_value = int(current_text)
                new_value = current_value + int(step) if increment else current_value - int(step)
                # Clamp within min/max
                new_value = max(int(min_val), min(int(max_val), new_value))
                line_edit.setText(str(new_value))
        except ValueError:
            # If current text is invalid, try setting to min or 0
            reset_val = min_val if min_val > -float('inf') else 0
            if decimals is not None:
                 line_edit.setText(f"{float(reset_val):.{decimals}f}")
            else:
                 line_edit.setText(str(int(reset_val)))

    def _increment_value(self, line_edit: QLineEdit, step: float, 
                         min_val: float, max_val: float, decimals: Optional[int] = None):
        self._adjust_value(line_edit, True, step, min_val, max_val, decimals)
        
    def _decrement_value(self, line_edit: QLineEdit, step: float, 
                         min_val: float, max_val: float, decimals: Optional[int] = None):
        self._adjust_value(line_edit, False, step, min_val, max_val, decimals)
        
    def _is_controller_visible(self, controller_param: str) -> bool:
        """检查控制器参数是否可见（递归检查父级条件）"""
        # 如果控制器参数没有对应的row_widget，认为它是可见的（顶层参数）
        controller_row = self.row_widgets.get(controller_param)
        if controller_row is None:
            return True

        # 检查控制器参数本身的条件
        controller_def = self.param_definitions.get(controller_param)
        condition = controller_def.get('condition', controller_def.get('conditions')) if controller_def else None
        if not controller_def or not condition:
            return True  # 没有条件，默认可见

        # 直接检查row_widget的当前可见性状态
        return controller_row.isVisible()

    def _handle_conditional_visibility_check(self):
        """Checks all conditions and updates widget visibility."""
        # --- ADDED More Debugging ---
        sender = self.sender() # Get the object that emitted the signal
        # ---------------------------

        current_values = self._get_current_dialog_values() # Get intermediate values

        # 多轮处理：确保级联条件正确传播
        # 最多处理3轮，因为条件链不会太深
        for round_num in range(3):
            visibility_changed_this_round = False

            for name, row_widget in self.row_widgets.items():
                param_def = self.param_definitions.get(name)
                if not param_def:
                    continue

                condition = param_def.get('condition', param_def.get('conditions'))
                if not condition:
                    continue

                # 修复：处理列表类型的条件（多条件组合 - AND逻辑）
                if isinstance(condition, list):
                    # 列表类型：所有条件都必须满足（AND逻辑）
                    all_conditions_met = True
                    for single_condition in condition:
                        if not isinstance(single_condition, dict):
                            continue
                        controller_param = single_condition.get('param')
                        required_value = single_condition.get('value')

                        # 检查控制器参数是否可见
                        if not self._is_controller_visible(controller_param):
                            all_conditions_met = False
                            break

                        if controller_param not in current_values:
                            all_conditions_met = False
                            break

                        actual_value = current_values[controller_param]
                        if actual_value != required_value:
                            all_conditions_met = False
                            break

                    is_visible = all_conditions_met
                    current_visibility = row_widget.isVisible()
                    if current_visibility != is_visible:
                        visibility_changed_this_round = True
                        row_widget.setVisible(is_visible)
                        row_widget.update()
                    continue

                # 确保condition是字典类型
                if not isinstance(condition, dict):
                    continue

                controller_param = condition.get('param')
                required_value = condition.get('value')
                value_not = condition.get('value_not') # Check for 'value_not' condition
                operator = condition.get('operator') # Get operator explicitly

                # 关键修复：检查控制器参数本身是否可见
                # 如果控制器参数被隐藏，那么依赖它的参数也应该被隐藏
                if not self._is_controller_visible(controller_param):
                    current_visibility = row_widget.isVisible()
                    if current_visibility != False:
                        visibility_changed_this_round = True
                        row_widget.setVisible(False)
                        row_widget.update()
                    continue

                if controller_param not in current_values:
                    current_visibility = row_widget.isVisible()
                    if current_visibility != False:
                        visibility_changed_this_round = True
                        row_widget.setVisible(False)
                        row_widget.update()
                    continue
                actual_value = current_values[controller_param]

                # --- REVISED Logic for Clarity and value_not ---
                is_visible = False
                required_comparison_value = required_value if value_not is None else value_not

                # Determine effective operator and expected match result for visibility
                if value_not is not None:
                    effective_operator = operator if operator else '!=' # Default to != if value_not is used
                else:
                    effective_operator = operator if operator else '==' # Default to == if value is used

                match = False
                try:
                    # Handle boolean comparison specifically for CheckBox
                    if isinstance(actual_value, bool) and isinstance(required_comparison_value, bool):
                        actual_typed = actual_value
                    # Handle empty string specifically for LineEdit controlling visibility
                    elif isinstance(actual_value, str) and required_comparison_value == "":
                        actual_typed = actual_value # Compare strings directly
                    # General type conversion
                    elif required_comparison_value is not None:
                        # Try to convert actual_value to the type of required_comparison_value
                        try:
                            actual_typed = type(required_comparison_value)(actual_value)
                        except (ValueError, TypeError):
                             # If direct conversion fails, maybe it's a string comparison?
                             actual_typed = str(actual_value)
                             required_comparison_value = str(required_comparison_value)
                    else: # required_comparison_value is None
                        actual_typed = actual_value

                    if effective_operator == '==':
                        match = (actual_typed == required_comparison_value)
                    elif effective_operator == '!=':
                        match = (actual_typed != required_comparison_value)
                    elif effective_operator == 'in':
                        match = (isinstance(required_comparison_value, list) and actual_typed in required_comparison_value)
                    elif effective_operator == 'notin':
                        match = (isinstance(required_comparison_value, list) and actual_typed not in required_comparison_value)
                    else:
                        pass
                except Exception as e:
                     pass

                # Determine visibility based on match and value_not
                is_visible = match
                # ----------------------------------

                # Check if visibility will change
                current_visibility = row_widget.isVisible()
                if current_visibility != is_visible:
                    visibility_changed_this_round = True
                    row_widget.setVisible(is_visible)
                    row_widget.update()

            # 如果这一轮没有变化，就不需要继续了
            if not visibility_changed_this_round:
                break

        visibility_changed = visibility_changed_this_round or round_num > 0

        # After updating visibility of all rows, adjust the dialog size ONLY if needed
        if visibility_changed:
            # Force layout update before adjusting size
            self.params_layout.activate() # Try activating the layout
            self.params_layout.update() # <<< ADDED
            self.main_layout.activate()   # Try activating the main layout
            self.main_layout.update() # <<< ADDED
            # 工具 修复：延迟调整大小，确保布局更新完成
            QTimer.singleShot(0, self._delayed_size_adjustment)

    def _get_current_dialog_values(self) -> Dict[str, Any]: # <--- ADDED this helper
        """Gets the current values from the dialog widgets FOR INTERNAL USE (like conditions)."""
        values = {}
        for name, widget in self.widgets.items():
            param_def = self.param_definitions.get(name, {})
            param_type = param_def.get('type', 'text')
            
            try: # Wrap individual gets in try-except
                if isinstance(widget, QLineEdit):
                    values[name] = widget.text()
                elif isinstance(widget, QComboBox):
                    values[name] = widget.currentText()
                elif isinstance(widget, QCheckBox):
                    values[name] = widget.isChecked()
                elif isinstance(widget, QPlainTextEdit): # <-- ADD getting value from QPlainTextEdit
                    values[name] = widget.toPlainText()
                elif param_type == 'radio':
                    if isinstance(widget, QButtonGroup): # widget is self.widgets[name]
                        button_group = widget
                        checked_button = button_group.checkedButton()
                        if checked_button:
                            values[name] = checked_button.property("value_key") # Get the stored key
                        else:
                            # No button selected, fallback to default
                            values[name] = param_def.get('default')
                            # Minimal logging for this specific case to avoid spam if defaults are common
                            if param_def.get('default') is not None:
                                pass
                    else:
                        logger.warning(f"Widget for radio parameter '{name}' is type '{type(widget).__name__}' not QButtonGroup as expected. Fallback to default.")
                        values[name] = param_def.get('default')
                # Add other widget types if needed
            except Exception as e:
                 values[name] = None # Set to None on error
                 
        # --- ADDED: Specific debug for controller value ---
        if "condition_image_path" in values:
             pass
        # ------------------------------------------------
        return values

    def _show_random_target_context_menu(self, target_card_id: int, widget, pos):
        """显示随机跳转目标的右键菜单"""
        menu = apply_unified_menu_style(QMenu(self), frameless=True)
        delete_action = menu.addAction("删除连线")
        action = menu.exec_(widget.mapToGlobal(pos))
        if action == delete_action:
            self.request_delete_random_connection.emit(target_card_id)

    def get_parameters(self) -> dict:
        """Retrieves the updated parameters from the widgets."""
        updated_params = self.current_parameters.copy() # Start with existing values

        # Helper to parse RGB from string (copied from find_color_task for consistency)
        def _parse_rgb(color_str: str) -> Optional[Tuple[int, int, int]]:
            try:
                parts = [int(c.strip()) for c in color_str.split(',')]
                if len(parts) == 3 and all(0 <= c <= 255 for c in parts):
                    return tuple(parts)
                logger.error(f"(UI Dialog) Invalid RGB format: '{color_str}'. Expected R,G,B")
                return None
            except Exception:
                 logger.error(f"(UI Dialog) Error parsing RGB string: '{color_str}'.")
                 return None

        for name, widget in self.widgets.items():
            param_def = self.param_definitions.get(name, {})
            param_type = param_def.get('type', 'text')
            widget_hint = param_def.get('widget_hint') # <<< Get widget hint
            new_value: Any = None

            try:
                # --- Existing value retrieval logic --- 
                if isinstance(widget, QLineEdit):
                    new_value = widget.text()
                elif isinstance(widget, QSpinBox):
                    new_value = widget.value()
                elif isinstance(widget, QDoubleSpinBox):
                    new_value = widget.value()
                elif isinstance(widget, QCheckBox):
                    new_value = widget.isChecked()
                elif isinstance(widget, QComboBox):
                    # <<< MODIFIED: Handle card_selector data retrieval >>>
                    if widget_hint in ('card_selector', 'thread_target_selector', 'workflow_card_selector', 'bound_window_selector'):
                        new_value = widget.currentData() # Get card ID (or None)
                    else:
                        new_value = widget.currentText()
                elif isinstance(widget, QButtonGroup):
                    selected_button = widget.checkedButton()
                    if selected_button:
                         new_value = selected_button.property("value_key") # <--- 获取正确的 value_key
                elif isinstance(widget, QPlainTextEdit):
                      new_value = widget.toPlainText()
                elif isinstance(widget, QListWidget):
                      raw_color_data = widget.property("raw_color_data")
                      if raw_color_data is not None:
                          new_value = raw_color_data
                      else:
                          new_value = self.current_parameters.get(name)
                elif isinstance(widget, QWidget) and name == 'connected_targets':
                      # QWidget 容器是只读的，保持原值
                      new_value = self.current_parameters.get(name)
                elif widget_hint == 'ocr_region_selector':
                    # Get region from OCR region selector
                    region = widget.get_region()
                    region_binding = {}
                    if hasattr(widget, 'get_region_binding_info'):
                        try:
                            region_binding = widget.get_region_binding_info() or {}
                        except Exception:
                            region_binding = {}

                    ocr_region_binding_keys = (
                        'region_hwnd',
                        'region_window_title',
                        'region_window_class',
                        'region_client_width',
                        'region_client_height',
                    )

                    # 首先尝试从隐藏参数中获取最新的值
                    if hasattr(self, '_hidden_params'):
                        saved_x = self._hidden_params.get('region_x')
                        saved_y = self._hidden_params.get('region_y')
                        saved_width = self._hidden_params.get('region_width')
                        saved_height = self._hidden_params.get('region_height')
                        if saved_x is not None and saved_y is not None and saved_width is not None and saved_height is not None:
                            # 使用隐藏参数中保存的最新值
                            updated_params.update({
                                'region_x': saved_x,
                                'region_y': saved_y,
                                'region_width': saved_width,
                                'region_height': saved_height
                            })
                        elif region and any(region):
                            # 如果隐藏参数中没有值，使用get_region()返回的值
                            x, y, width, height = region
                            updated_params.update({
                                'region_x': x,
                                'region_y': y,
                                'region_width': width,
                                'region_height': height
                            })
                    elif region and any(region):
                        # 如果没有隐藏参数，使用get_region()返回的值
                        x, y, width, height = region
                        updated_params.update({
                            'region_x': x,
                            'region_y': y,
                            'region_width': width,
                            'region_height': height
                        })
                    for binding_key in ocr_region_binding_keys:
                        binding_value = None
                        if hasattr(self, '_hidden_params'):
                            binding_value = self._hidden_params.get(binding_key)
                        if binding_value in (None, ''):
                            binding_value = self.current_parameters.get(binding_key)
                        if binding_value in (None, '') and binding_key in region_binding:
                            binding_value = region_binding.get(binding_key)
                        if binding_value not in (None, ''):
                            updated_params[binding_key] = binding_value
                    new_value = None  # OCR区域选择器本身不存储值
                elif widget_hint == 'motion_region_selector':
                    # 处理移动检测区域选择器
                    region = widget.get_region()

                    # 首先尝试从current_parameters中获取最新的值
                    saved_x = self.current_parameters.get('minimap_x')
                    saved_y = self.current_parameters.get('minimap_y')
                    saved_width = self.current_parameters.get('minimap_width')
                    saved_height = self.current_parameters.get('minimap_height')

                    if saved_x is not None and saved_y is not None and saved_width is not None and saved_height is not None:
                        # 使用current_parameters中保存的最新值
                        updated_params.update({
                            'minimap_x': saved_x,
                            'minimap_y': saved_y,
                            'minimap_width': saved_width,
                            'minimap_height': saved_height
                        })
                    elif region and any(region):
                        # 如果current_parameters中没有值，使用get_region()返回的值
                        x, y, width, height = region
                        updated_params.update({
                            'minimap_x': x,
                            'minimap_y': y,
                            'minimap_width': width,
                            'minimap_height': height
                        })
                    new_value = None  # 移动检测区域选择器本身不存储值
                elif widget_hint == 'image_region_selector':
                    saved_x = self.current_parameters.get('recognition_region_x')
                    saved_y = self.current_parameters.get('recognition_region_y')
                    saved_width = self.current_parameters.get('recognition_region_width')
                    saved_height = self.current_parameters.get('recognition_region_height')
                    if saved_x is not None and saved_y is not None and saved_width is not None and saved_height is not None:
                        updated_params.update({
                            'recognition_region_x': saved_x,
                            'recognition_region_y': saved_y,
                            'recognition_region_width': saved_width,
                            'recognition_region_height': saved_height
                        })
                    new_value = None
                elif widget_hint == 'coordinate_selector':
                    # 从坐标选择器获取当前坐标值
                    if hasattr(widget, 'get_coordinate'):
                        coord_x, coord_y = widget.get_coordinate()
                        # 将坐标值保存到current_parameters中对应的x和y参数名
                        # 需要检查参数定义中的坐标参数名
                        updated_params['coordinate_x'] = coord_x
                        updated_params['coordinate_y'] = coord_y
                    new_value = None
                elif widget_hint == 'motion_region_selector':
                    # 移动检测区域选择器不存储值，跳过（区域信息已在选择时更新到current_parameters）
                    new_value = None
                # Add more widget types if needed

                # --- Type Conversion (Optional but recommended) ---
                if new_value is not None:
                    original_type = type(self.current_parameters.get(name)) # Get type of original value
                    if original_type is int and isinstance(new_value, str):
                        try: new_value = int(new_value)
                        except ValueError: pass # Keep as string if conversion fails
                    elif original_type is float and isinstance(new_value, str):
                         try: new_value = float(new_value)
                         except ValueError: pass # Keep as string
                    elif original_type is bool and isinstance(new_value, str):
                         new_value = new_value.lower() in ['true', '1', 'yes', 'y']

                # 工具 简化：直接设置参数，让参数处理器处理复杂逻辑
                updated_params[name] = new_value
                
            except Exception as e:
                 logger.error(f"Error retrieving value for parameter '{name}': {e}")
                 # Keep the original value if retrieval fails
                 updated_params[name] = self.current_parameters.get(name)

        # --- ADDED: Post-process for FindColorTask to calculate HSV --- 
        if self.task_type == '找色功能':
            rgb_str = updated_params.get('target_color_input')
            if isinstance(rgb_str, str):
                rgb_tuple = _parse_rgb(rgb_str)
                if rgb_tuple:
                    # Get default tolerances from definitions (since widgets are hidden)
                    try:
                        h_tol = int(self.param_definitions.get('h_tolerance', {}).get('default', 10))
                        s_tol = int(self.param_definitions.get('s_tolerance', {}).get('default', 40))
                        v_tol = int(self.param_definitions.get('v_tolerance', {}).get('default', 40))
                        
                        # Calculate HSV range
                        hsv_range_dict = self._calculate_hsv_range(rgb_tuple, h_tol, s_tol, v_tol)
                        
                        # Add calculated HSV values to the parameters
                        if hsv_range_dict:
                             updated_params.update(hsv_range_dict)
                        else:
                            logger.warning("(UI 对话框) HSV 范围计算失败，不再添加 HSV 参数。")
                            
                    except Exception as e:
                        logger.exception(f"(UI Dialog) Error getting tolerances or calculating HSV: {e}")
                else:
                    logger.warning(f"(UI Dialog) Could not parse RGB string '{rgb_str}' for HSV calculation.")
            else:
                 logger.warning("(UI 对话框) 未找到 'target_color_input' 参数，或其不是字符串。")
        # --- END ADDED ---

        # --- ADDED: Merge hidden parameters FIRST, but don't overwrite coordinate selector params ---
        if hasattr(self, '_hidden_params') and self._hidden_params:
            # 工具 修复：更智能的参数合并逻辑
            # 分离不同类型的参数，避免混乱
            coordinate_selector_params = {'coordinate_x', 'coordinate_y'}
            ocr_region_params = {
                'region_x', 'region_y', 'region_width', 'region_height',
                'region_hwnd', 'region_window_title', 'region_window_class',
                'region_client_width', 'region_client_height',
            }
            motion_detection_params = {'minimap_x', 'minimap_y', 'minimap_width', 'minimap_height'}
            protected_params = coordinate_selector_params | ocr_region_params | motion_detection_params

            for param_name, param_value in self._hidden_params.items():
                # 检查是否是受保护的参数且已经被设置
                    if param_name in protected_params and param_name in updated_params:
                        current_value = updated_params[param_name]
                        # 只有当前值为None、空或0时才使用隐藏参数的值
                        if current_value is None or current_value == '' or current_value == 0:
                            updated_params[param_name] = param_value
                        continue

                    if param_name not in protected_params or param_name not in updated_params:
                        # 非受保护参数或未设置的参数，直接使用隐藏参数值
                        updated_params[param_name] = param_value
        # --- END ADDED ---

        # 坐标选择器数据合并已删除

        # 工具 修复：参数验证和保护机制

        # 工具 完全重写：模拟鼠标操作参数的简洁处理
        if self.task_type == "模拟鼠标操作":

            # 检查是否使用了坐标选择工具
            coordinate_tool_used = hasattr(self, '_coordinate_tool_used') and self._coordinate_tool_used

            if coordinate_tool_used:
                # 如果使用了坐标工具，强制设置为坐标点击模式
                updated_params['operation_mode'] = '坐标点击'

            # 确保坐标参数是整数类型
            coord_x = updated_params.get('coordinate_x')
            coord_y = updated_params.get('coordinate_y')

            if coord_x is not None:
                try:
                    updated_params['coordinate_x'] = int(coord_x)
                except (ValueError, TypeError):
                    updated_params['coordinate_x'] = 0

            if coord_y is not None:
                try:
                    updated_params['coordinate_y'] = int(coord_y)
                except (ValueError, TypeError):
                    updated_params['coordinate_y'] = 0




        return updated_params

    def reject(self):
        """关闭对话框。"""
        super().reject()

    def _on_ok_clicked(self):
        """确定按钮点击处理"""
        self.accept()

    def _on_cancel_clicked(self):
        """取消按钮点击处理"""
        self.reject()

    def accept(self):
        """确保参数在确认时被保存。"""
        try:
            self._final_parameters = self.get_parameters()
        except Exception as e:
            logger.exception(f"保存参数失败: {e}")
        super().accept()

    # --- ADDED: Helper for HSV Calculation ---
    def _calculate_hsv_range(self, rgb_tuple: Tuple[int, int, int],
                             h_tol: int, s_tol: int, v_tol: int) -> Dict[str, int]:
        """Calculates HSV range based on RGB color and tolerances."""
        hsv_results = {}
        try:
            # Convert RGB to HSV (using BGR format for OpenCV)
            target_bgr_arr = np.uint8([[rgb_tuple[::-1]]])
            target_hsv_arr = cv2.cvtColor(target_bgr_arr, cv2.COLOR_BGR2HSV)
            h, s, v = map(int, target_hsv_arr[0][0])

            # Calculate range using standard ints
            h_min_calc = h - h_tol
            h_max_calc = h + h_tol
            s_min_calc = s - s_tol
            s_max_calc = s + s_tol
            v_min_calc = v - v_tol
            v_max_calc = v + v_tol

            # Clamp values
            h_min_final = max(0, min(h_min_calc, 179))
            h_max_final = max(0, min(h_max_calc, 179))
            s_min_final = max(0, min(s_min_calc, 255))
            s_max_final = max(0, min(s_max_calc, 255))
            v_min_final = max(0, min(v_min_calc, 255))
            v_max_final = max(0, min(v_max_calc, 255))
            
            hsv_results = {
                'h_min': h_min_final,
                'h_max': h_max_final,
                's_min': s_min_final,
                's_max': s_max_final,
                'v_min': v_min_final,
                'v_max': v_max_final
            }

        except Exception as e:
            logger.exception(f"(UI Dialog) Error calculating HSV range: {e}")
            # Return empty dict on error
            return {}
        
        return hsv_results
    # --- END ADDED Helper ---

    # --- ADDED: Slot for browsing image file --- 
    def _browse_image_file(self, line_edit_widget: QLineEdit):
        """Opens a file dialog to select an image, stores relative path if possible."""
        start_dir = self.images_dir or "." # Start in images_dir or current directory
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "选择图片文件", 
            start_dir, 
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif);;所有文件 (*)"
        )

        if file_path:
            if self.images_dir:
                try:
                    relative_path = os.path.relpath(file_path, self.images_dir)
                    # If the path starts with '..', it's outside images_dir
                    if relative_path.startswith('..') or os.path.isabs(relative_path):
                        logger.warning(f"选择的文件 '{file_path}' 不在图片目录 '{self.images_dir}' 或其子目录中，将存储绝对路径。")
                        line_edit_widget.setText(file_path)
                    else:
                        line_edit_widget.setText(relative_path) # Store relative path
                except ValueError:
                    # Happens on Windows if paths are on different drives
                    logger.warning(f"无法计算相对路径 (可能在不同驱动器上)，将存储绝对路径: '{file_path}'")
                    line_edit_widget.setText(file_path) # Store absolute path as fallback
            else:
                # images_dir not set, store absolute path
                logger.warning("图片目录未设置，将存储绝对路径。")
                line_edit_widget.setText(file_path)
    # --- END ADDED ---

    # ==================================
    # Static Method for Convenience
    @staticmethod
    def get_task_parameters(param_definitions: Dict[str, Dict[str, Any]],
                              current_parameters: Dict[str, Any],
                              title: str,
                              task_type: str, # <<< ADDED: Explicit task_type parameter
                              # --- ADDED: Receive workflow cards info ---
                              workflow_cards_info: Optional[Dict[int, tuple[str, int]]] = None, # {seq_id: (task_type, card_id)}
                              # -------------------------------------------
                              images_dir: Optional[str] = None, # <<< ADDED: Parameter for images_dir
                              editing_card_id: Optional[int] = None, # <<< ADDED: Parameter for editing_card_id
                              parent: Optional[QWidget] = None) -> Optional[Dict[str, Any]]:
        """Creates and executes the dialog, returning the new parameters if accepted."""
        dialog = ParameterDialog(
            param_definitions, 
            current_parameters, 
            title,
            task_type, # <<< ADDED: Pass task_type
            workflow_cards_info=workflow_cards_info, # Pass info
            images_dir=images_dir, # <<< ADDED: Pass images_dir to instance
            editing_card_id=editing_card_id, # <<< ADDED: Pass editing_card_id
            parent=parent
        )

        # 修复：检查是否有OCR区域选择器、坐标选择器或移动检测区域选择器，如果有则使用非模态对话框
        has_ocr_selector = any(
            param_def.get('widget_hint') == 'ocr_region_selector'
            for param_def in param_definitions.values()
        )
        has_coordinate_selector = any(
            param_def.get('widget_hint') == 'coordinate_selector'
            for param_def in param_definitions.values()
        )
        has_motion_region_selector = any(
            param_def.get('widget_hint') == 'motion_region_selector'
            for param_def in param_definitions.values()
        )
        has_image_region_selector = any(
            param_def.get('widget_hint') == 'image_region_selector'
            for param_def in param_definitions.values()
        )

        if has_ocr_selector or has_coordinate_selector or has_motion_region_selector or has_image_region_selector:
            if has_ocr_selector:
                selector_type = "OCR区域选择器"
            elif has_coordinate_selector:
                selector_type = "坐标选择器"
            elif has_motion_region_selector:
                selector_type = "移动检测区域选择器"
            else:
                selector_type = "图片识别区域选择器"
            # 强制设置为非模态对话框
            dialog.setModal(False)
            dialog.setWindowModality(Qt.WindowModality.NonModal)

            # 设置窗口标志确保不阻塞其他窗口，但不要始终置顶
            # 移除 WindowStaysOnTopHint 以允许目标窗口显示在前面
            dialog.setWindowFlags(
                dialog.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint
            )

            show_and_activate_overlay(dialog, log_prefix=f'{selector_type}参数对话框', focus=True)

            # 创建事件循环等待对话框关闭
            from PySide6.QtCore import QEventLoop
            loop = QEventLoop()
            dialog.finished.connect(loop.quit)

            loop.exec()

            result = dialog.result()
        else:
            result = dialog.exec()
        if result == QDialog.Accepted:
            # 优先使用保存的参数，如果没有则调用get_parameters
            if hasattr(dialog, '_final_parameters'):
                new_params = dialog._final_parameters
            else:
                new_params = dialog.get_parameters()
            return new_params
        return None # Indicate cancellation

    def _initial_size_adjustment(self):
        """初始化完成后调整对话框大小"""
        try:
            # 让对话框根据内容自动调整大小
            self.adjustSize()
            # 确保对话框不会太小
            current_size = self.size()
            min_width = max(500, current_size.width())
            min_height = max(300, current_size.height())
            self.resize(min_width, min_height)
        except Exception as e:
            logger.warning(f"初始大小调整失败: {e}")

    def _adjust_text_edit_height(self, text_edit: QPlainTextEdit, size):
        """根据内容自动调整文本编辑器高度"""
        try:
            # 计算内容高度
            doc_height = int(size.height())
            # 添加一些边距
            new_height = min(max(80, doc_height + 20), 200)

            # 只有当高度变化较大时才调整
            current_height = text_edit.height()
            if abs(new_height - current_height) > 10:
                text_edit.setFixedHeight(new_height)
                # 调整对话框大小
                QTimer.singleShot(0, self.adjustSize)
        except Exception as e:
            logger.warning(f"文本编辑器高度调整失败: {e}")

    def _delayed_size_adjustment(self):
        """延迟调整对话框大小"""
        try:
            # 强制更新布局
            self.updateGeometry()
            # 调整大小以适应内容
            self.adjustSize()
            # 确保最小尺寸
            current_size = self.size()
            min_width = max(500, current_size.width())
            if current_size.width() < min_width:
                self.resize(min_width, current_size.height())
        except Exception as e:
            logger.warning(f"延迟大小调整失败: {e}")
