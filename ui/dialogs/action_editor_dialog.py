"""
录制回放步骤编辑器对话框
提供完善的步骤查看、编辑、增删改查功能
"""

import html
import json
import logging
from typing import List, Dict, Any
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QInputDialog, QSpinBox, QDoubleSpinBox, QGroupBox,
    QFormLayout, QLineEdit, QCheckBox, QSplitter, QTextEdit, QWidget,
    QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QColor
from themes import get_theme_manager
from ui.panels.recording.parameter_panel_recording_replay_thread import ParameterPanelReplayThread
from utils.window_activation_utils import (
    resolve_replay_window_offsets_from_config,
)
from ..widgets.custom_widgets import CustomDropdown as QComboBox
from utils.window_coordinate_common import get_available_geometry_for_widget, clamp_preferred_window_size

logger = logging.getLogger(__name__)


# ===== 自定义SpinBox类，禁用滚轮修改数值 =====
class NoWheelSpinBox(QSpinBox):
    """禁用滚轮事件的QSpinBox"""
    def wheelEvent(self, event):
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    """禁用滚轮事件的QDoubleSpinBox"""
    def wheelEvent(self, event):
        event.ignore()

# ===== 统一下拉框样式 =====
# ================================================


class ActionEditorDialog(QDialog):
    """步骤编辑器对话框"""

    actions_updated = Signal(list)  # 步骤更新信号

    def __init__(self, actions: List[Dict[str, Any]], recording_area: str = "全屏录制", parent=None, recording_mode: str = "绝对坐标"):
        super().__init__(parent)
        self.actions = actions.copy() if actions else []
        self.recording_area = recording_area  # 保存录制区域信息
        self.recording_mode = recording_mode  # 保存录制模式信息
        self.current_row = -1
        self.start_from_index = 0  # 回放起始索引
        self._has_custom_start_step = False
        self._replay_thread = None
        self.init_ui()
        self.load_actions()

    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("步骤编辑器")
        self.setMinimumSize(720, 480)
        available_geometry = get_available_geometry_for_widget(self.parentWidget() or self)
        initial_width, initial_height = clamp_preferred_window_size(1000, 600, available_geometry)
        self.resize(initial_width, initial_height)

        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # 顶部摘要
        stats_layout = QHBoxLayout()
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(0)
        self.stats_label = QLabel()
        self.stats_label.setObjectName("actionEditorStatsLabel")
        self.stats_label.setWordWrap(True)
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.stats_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.update_stats_label()
        stats_layout.addWidget(self.stats_label)
        main_layout.addLayout(stats_layout)

        # 创建分割器（左侧列表，右侧详情）
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("actionEditorMainSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)

        # 左侧：步骤列表和工具栏
        left_widget = QGroupBox("步骤列表")
        left_widget.setObjectName("actionEditorListGroup")
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(10, 6, 10, 10)
        left_layout.setSpacing(6)

        # 工具栏
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(6)

        # 添加步骤按钮
        add_menu_layout = QHBoxLayout()
        add_menu_layout.setContentsMargins(0, 0, 0, 0)
        add_menu_layout.setSpacing(6)
        self.add_mouse_move_btn = QPushButton("鼠标移动")
        self.add_mouse_move_btn.setToolTip("添加鼠标移动步骤")
        self.add_mouse_move_btn.clicked.connect(lambda: self.add_action('mouse_move'))
        add_menu_layout.addWidget(self.add_mouse_move_btn)

        self.add_mouse_click_btn = QPushButton("鼠标点击")
        self.add_mouse_click_btn.setToolTip("添加鼠标点击步骤")
        self.add_mouse_click_btn.clicked.connect(lambda: self.add_action('mouse_click'))
        add_menu_layout.addWidget(self.add_mouse_click_btn)

        self.add_key_press_btn = QPushButton("按键")
        self.add_key_press_btn.setToolTip("添加键盘按键步骤")
        self.add_key_press_btn.clicked.connect(lambda: self.add_action('key_press'))
        add_menu_layout.addWidget(self.add_key_press_btn)

        self.add_mouse_scroll_btn = QPushButton("滚轮")
        self.add_mouse_scroll_btn.setToolTip("添加鼠标滚轮步骤")
        self.add_mouse_scroll_btn.clicked.connect(lambda: self.add_action('mouse_scroll'))
        add_menu_layout.addWidget(self.add_mouse_scroll_btn)

        self.add_delay_btn = QPushButton("延时")
        self.add_delay_btn.setToolTip("添加延时步骤")
        self.add_delay_btn.clicked.connect(lambda: self.add_action('delay'))
        add_menu_layout.addWidget(self.add_delay_btn)

        toolbar_layout.addLayout(add_menu_layout)
        toolbar_layout.addStretch()

        # 编辑按钮
        self.edit_btn = QPushButton("编辑")
        self.edit_btn.clicked.connect(self.edit_selected_action)
        self.edit_btn.setEnabled(False)
        toolbar_layout.addWidget(self.edit_btn)

        self.delete_btn = QPushButton("删除选中")
        self.delete_btn.clicked.connect(self.delete_selected_actions)
        self.delete_btn.setEnabled(False)
        toolbar_layout.addWidget(self.delete_btn)

        # 顺序调整按钮
        self.move_up_btn = QPushButton("上移")
        self.move_up_btn.clicked.connect(self.move_action_up)
        self.move_up_btn.setEnabled(False)
        toolbar_layout.addWidget(self.move_up_btn)

        self.move_down_btn = QPushButton("下移")
        self.move_down_btn.clicked.connect(self.move_action_down)
        self.move_down_btn.setEnabled(False)
        toolbar_layout.addWidget(self.move_down_btn)

        left_layout.addLayout(toolbar_layout)

        # 步骤列表表格
        self.table = QTableWidget()
        self.table.setObjectName("actionEditorStepTable")
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["开始", "#", "时间(秒)", "类型", "详情"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        self.table.cellDoubleClicked.connect(lambda: self.edit_selected_action())

        table_header = self.table.horizontalHeader()
        table_header.setFixedHeight(32)
        table_header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        table_header.setHighlightSections(False)
        table_header.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        # 设置列宽
        self.table.setColumnWidth(0, 54)   # 开始标记
        self.table.setColumnWidth(1, 52)   # 序号
        self.table.setColumnWidth(2, 86)   # 时间
        self.table.setColumnWidth(3, 108)  # 类型

        self.table_container = QFrame()
        self.table_container.setObjectName("actionEditorStepTableFrame")
        self.table_container.setProperty("tableCard", "true")
        table_container_layout = QVBoxLayout(self.table_container)
        table_container_layout.setContentsMargins(1, 1, 1, 1)
        table_container_layout.setSpacing(0)
        table_container_layout.addWidget(self.table)

        left_layout.addWidget(self.table_container)

        # 右侧：步骤详情
        right_widget = QGroupBox("步骤详情")
        right_widget.setObjectName("actionEditorDetailGroup")
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 6, 10, 10)
        right_layout.setSpacing(8)

        self.detail_text = QTextEdit()
        self.detail_text.setObjectName("actionEditorDetailText")
        self.detail_text.setReadOnly(True)
        self.detail_text.setPlaceholderText("选择一个步骤查看详细信息...")
        self.detail_text.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_text.document().setDocumentMargin(0)
        right_layout.addWidget(self.detail_text)

        # 快速编辑区域
        quick_edit_group = QGroupBox("快速编辑")
        quick_edit_group.setObjectName("actionEditorQuickEditGroup")
        quick_edit_layout = QFormLayout(quick_edit_group)
        quick_edit_layout.setContentsMargins(10, 6, 10, 10)
        quick_edit_layout.setSpacing(6)

        self.quick_time_spin = NoWheelDoubleSpinBox()
        self.quick_time_spin.setRange(0, 10000)
        self.quick_time_spin.setDecimals(3)
        self.quick_time_spin.setSuffix(" 秒")
        quick_edit_layout.addRow("时间:", self.quick_time_spin)

        quick_edit_btn_layout = QHBoxLayout()
        self.apply_quick_edit_btn = QPushButton("应用修改")
        self.apply_quick_edit_btn.clicked.connect(self.apply_quick_edit)
        self.apply_quick_edit_btn.setEnabled(False)
        quick_edit_btn_layout.addWidget(self.apply_quick_edit_btn)
        quick_edit_btn_layout.addStretch()
        quick_edit_layout.addRow(quick_edit_btn_layout)

        self.bulk_time_offset_spin = NoWheelDoubleSpinBox()
        self.bulk_time_offset_spin.setRange(0.001, 10000)
        self.bulk_time_offset_spin.setDecimals(3)
        self.bulk_time_offset_spin.setValue(0.5)
        self.bulk_time_offset_spin.setSuffix(" 秒")
        quick_edit_layout.addRow("批量偏移:", self.bulk_time_offset_spin)

        bulk_time_btn_layout = QHBoxLayout()
        self.bulk_add_time_btn = QPushButton("增加时间")
        self.bulk_add_time_btn.setToolTip("从首个选中步骤开始，将该步骤及后续步骤整体后移")
        self.bulk_add_time_btn.clicked.connect(lambda: self.apply_bulk_time_shift(1))
        self.bulk_add_time_btn.setEnabled(False)
        bulk_time_btn_layout.addWidget(self.bulk_add_time_btn)

        self.bulk_reduce_time_btn = QPushButton("减少时间")
        self.bulk_reduce_time_btn.setToolTip("从首个选中步骤开始，将该步骤及后续步骤整体前移")
        self.bulk_reduce_time_btn.clicked.connect(lambda: self.apply_bulk_time_shift(-1))
        self.bulk_reduce_time_btn.setEnabled(False)
        bulk_time_btn_layout.addWidget(self.bulk_reduce_time_btn)
        bulk_time_btn_layout.addStretch()
        quick_edit_layout.addRow(bulk_time_btn_layout)

        self.bulk_time_hint_label = QLabel("作用范围：从首个选中步骤开始，统一平移后续时间轴。")
        self.bulk_time_hint_label.setObjectName("actionEditorBulkTimeHint")
        self.bulk_time_hint_label.setWordWrap(True)
        quick_edit_layout.addRow("", self.bulk_time_hint_label)

        right_layout.addWidget(quick_edit_group)

        # 添加到分割器
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 2)  # 左侧占2/3
        splitter.setStretchFactor(1, 1)  # 右侧占1/3

        main_layout.addWidget(splitter)

        # 底部按钮
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(6)

        # 批量操作
        self.optimize_btn = QPushButton("优化步骤")
        self.optimize_btn.setToolTip("移除冗余的鼠标移动步骤")
        self.optimize_btn.clicked.connect(self.optimize_actions)
        bottom_layout.addWidget(self.optimize_btn)

        self.clear_btn = QPushButton("清空所有")
        self.clear_btn.clicked.connect(self.clear_all_actions)
        bottom_layout.addWidget(self.clear_btn)

        # 回放测试按钮
        self.test_replay_btn = QPushButton("从选中步骤开始回放")
        self.test_replay_btn.setToolTip("从勾选的起始步骤开始测试回放（若未勾选则从头开始）")
        self.test_replay_btn.setObjectName("testReplayButton")
        self.test_replay_btn.clicked.connect(self.test_replay_from_start)
        bottom_layout.addWidget(self.test_replay_btn)

        bottom_layout.addStretch()

        # 导入导出
        self.import_btn = QPushButton("导入JSON")
        self.import_btn.clicked.connect(self.import_from_json)
        bottom_layout.addWidget(self.import_btn)

        self.export_btn = QPushButton("导出JSON")
        self.export_btn.clicked.connect(self.export_to_json)
        bottom_layout.addWidget(self.export_btn)

        # 确定/取消
        self.save_btn = QPushButton("保存")
        self.save_btn.clicked.connect(self.accept)
        self.save_btn.setObjectName("saveButton")
        bottom_layout.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        bottom_layout.addWidget(self.cancel_btn)

        main_layout.addLayout(bottom_layout)

        self._apply_theme_styles()
        self._show_detail_placeholder()

    def _apply_theme_styles(self):
        """补充步骤编辑器局部样式，使详情区与全局主题一致。"""
        try:
            theme_manager = get_theme_manager()
            is_dark = bool(theme_manager.is_dark_mode())
            text_secondary = theme_manager.get_color("text_secondary")
            text_color = theme_manager.get_color("text")
            border = theme_manager.get_color("border")
            border_light = theme_manager.get_color("border_light")
        except Exception:
            is_dark = False
            text_secondary = "#666666"
            text_color = "#1f2328"
            border = "#d0d0d0"
            border_light = "#b8b8b8"

        detail_background = "#2d2d2d" if is_dark else "#ffffff"
        button_background = "#2d2d2d" if is_dark else "#f5f5f5"
        button_hover_background = "#3a3a3a" if is_dark else "#e8e8e8"
        button_pressed_background = "#252525" if is_dark else "#d8d8d8"
        button_border = "#3e3e3e" if is_dark else "#e0e0e0"
        button_hover_border = "#4e4e4e" if is_dark else "#d0d0d0"
        button_disabled_background = "#252525" if is_dark else "#fafafa"
        button_disabled_text = "#666666" if is_dark else "#999999"
        button_disabled_border = "#2e2e2e" if is_dark else "#e8e8e8"

        self.setStyleSheet(
            f"""
            QLabel#actionEditorStatsLabel {{
                color: {text_secondary};
                padding: 0;
            }}

            QLabel#actionEditorBulkTimeHint {{
                color: {text_secondary};
                padding-top: 2px;
            }}

            QPushButton {{
                background-color: {button_background};
                color: {text_color};
                border: 1px solid {button_border};
                border-radius: 4px;
                padding: 6px 14px;
                min-height: 24px;
            }}

            QPushButton:hover {{
                background-color: {button_hover_background};
                border-color: {button_hover_border};
            }}

            QPushButton:pressed {{
                background-color: {button_pressed_background};
                border-color: {button_border};
            }}

            QPushButton:disabled {{
                background-color: {button_disabled_background};
                color: {button_disabled_text};
                border-color: {button_disabled_border};
            }}

            QTextEdit#actionEditorDetailText {{
                background-color: {detail_background};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 10px;
            }}

            QTextEdit#actionEditorDetailText:focus {{
                border-color: {border_light};
            }}

            QSplitter#actionEditorMainSplitter::handle {{
                background: transparent;
            }}

            QGroupBox#actionEditorListGroup,
            QGroupBox#actionEditorDetailGroup,
            QGroupBox#actionEditorQuickEditGroup {{
                margin-top: 8px;
                padding-top: 8px;
            }}

            QGroupBox#actionEditorListGroup::title,
            QGroupBox#actionEditorDetailGroup::title,
            QGroupBox#actionEditorQuickEditGroup::title {{
                left: 8px;
                padding: 0 6px;
            }}
            """
        )

    def _get_detail_theme_colors(self) -> Dict[str, str]:
        """获取详情区渲染所需的主题颜色。"""
        defaults = {
            "text": "#1f2328",
            "text_secondary": "#667085",
            "surface": "#f7f7f7",
            "card": "#ffffff",
            "border": "#d0d7de",
        }

        try:
            theme_manager = get_theme_manager()
            return {
                "text": theme_manager.get_color("text"),
                "text_secondary": theme_manager.get_color("text_secondary"),
                "surface": theme_manager.get_color("surface"),
                "card": theme_manager.get_color("card"),
                "border": theme_manager.get_color("border"),
            }
        except Exception:
            return defaults

    def _show_detail_placeholder(self):
        """显示默认占位内容。"""
        colors = self._get_detail_theme_colors()
        self.detail_text.setHtml(
            (
                f"<div style='color:{colors['text_secondary']}; "
                "line-height:1.7; padding:4px 2px;'>"
                "选择左侧一个步骤，即可在这里查看完整参数和原始数据。"
                "</div>"
            )
        )

    def _build_info_message_html(self, message: str) -> str:
        """构造主题感知的提示消息 HTML。"""
        colors = self._get_detail_theme_colors()
        safe_message = html.escape(str(message or "").strip())
        return (
            f"<div style='color:{colors['text_secondary']}; "
            "line-height:1.7; padding:4px 2px;'>"
            f"{safe_message}"
            "</div>"
        )

    def _build_action_detail_html(self, action: Dict[str, Any], detail_items: List[tuple[str, str]]) -> str:
        """构造主题感知的步骤详情 HTML。"""
        colors = self._get_detail_theme_colors()
        title = html.escape(self.get_type_display_name(action.get('type', '')))
        json_text = html.escape(json.dumps(action, indent=2, ensure_ascii=False))

        sections = [
            f"<div style='color:{colors['text']}; line-height:1.7;'>",
            f"<div style='font-size:15px; font-weight:600; color:{colors['text']}; margin:0 0 10px 0;'>{title}</div>",
        ]

        for label, value in detail_items:
            safe_label = html.escape(str(label))
            safe_value = html.escape(str(value))
            sections.append(
                f"<div style='margin:0 0 6px 0;'>"
                f"<span style='color:{colors['text_secondary']};'>{safe_label}：</span>"
                f"<span style='color:{colors['text']};'>{safe_value}</span>"
                f"</div>"
            )

        sections.append(
            f"<div style='margin:14px 0 8px 0; padding-top:10px; border-top:1px solid {colors['border']}; "
            f"font-weight:600; color:{colors['text_secondary']};'>原始数据</div>"
        )
        sections.append(
            f"<pre style='margin:0; padding:10px 12px; white-space:pre-wrap; word-break:break-word; "
            f"background:{colors['card']}; color:{colors['text']}; border:1px solid {colors['border']}; "
            f"border-radius:8px; font-family:Consolas, \"Courier New\", monospace;'>{json_text}</pre>"
        )
        sections.append("</div>")
        return "".join(sections)

    def load_actions(self):
        """加载步骤到表格"""
        self.table.setRowCount(0)

        for i, action in enumerate(self.actions):
            self.add_action_to_table(i, action)

        self.update_stats_label()

    def add_action_to_table(self, row: int, action: Dict[str, Any]):
        """添加步骤到表格"""
        self.table.insertRow(row)

        # 开始标记复选框 - 先添加一个空白item作为背景
        checkbox_item = QTableWidgetItem("")
        checkbox_item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # 禁用文本编辑
        self.table.setItem(row, 0, checkbox_item)

        # 在item上方放置复选框widget
        start_checkbox = QCheckBox()
        start_checkbox.setToolTip("勾选此项作为回放的起始步骤")
        checkbox_widget = QWidget()
        checkbox_layout = QHBoxLayout(checkbox_widget)
        checkbox_layout.addWidget(start_checkbox)
        checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_widget.setStyleSheet("background: transparent;")  # 透明背景
        self.table.setCellWidget(row, 0, checkbox_widget)

        # 连接复选框信号，确保只有一个被选中
        start_checkbox.stateChanged.connect(lambda state, r=row: self.on_start_checkbox_changed(r, state))
        start_checkbox.setChecked(self._has_custom_start_step and row == self.start_from_index)

        # 序号
        self.table.setItem(row, 1, QTableWidgetItem(str(row + 1)))

        # 时间
        time_str = f"{action.get('time', 0):.3f}"
        self.table.setItem(row, 2, QTableWidgetItem(time_str))

        # 类型
        action_type = action.get('type', 'unknown')
        type_display = self.get_type_display_name(action_type)
        type_item = QTableWidgetItem(type_display)

        # 根据类型设置颜色
        if action_type == 'mouse_move':
            type_item.setForeground(QColor("#0066cc"))
        elif action_type == 'mouse_move_relative':
            type_item.setForeground(QColor("#0099ff"))
        elif action_type == 'mouse_click':
            type_item.setForeground(QColor("#009900"))
        elif action_type in ['key_press', 'key_release']:
            type_item.setForeground(QColor("#cc6600"))
        elif action_type == 'mouse_scroll':
            type_item.setForeground(QColor("#9900cc"))

        self.table.setItem(row, 3, type_item)

        # 详情
        detail = self.get_action_detail(action)
        self.table.setItem(row, 4, QTableWidgetItem(detail))

    def get_type_display_name(self, action_type: str) -> str:
        """获取类型显示名称"""
        type_map = {
            'mouse_move': '鼠标移动',
            'mouse_move_relative': '相对移动',
            'mouse_click': '鼠标点击',
            'mouse_scroll': '鼠标滚轮',
            'key_press': '按键按下',
            'key_release': '按键释放',
            'delay': '延时'
        }
        return type_map.get(action_type, action_type)

    def _is_keyboard_action_type(self, action_type: str) -> bool:
        """判断是否为键盘动作类型。"""
        return action_type in ['key_press', 'key_release']

    def _is_keyboard_action_pressed(self, action: Dict[str, Any]) -> bool:
        """获取键盘动作是否为按下状态。"""
        return action.get('type', '') != 'key_release'

    def _set_keyboard_action_pressed(self, action: Dict[str, Any], pressed: bool) -> None:
        """根据按下状态回写键盘动作类型。"""
        action['type'] = 'key_press' if pressed else 'key_release'

    def get_action_detail(self, action: Dict[str, Any]) -> str:
        """获取步骤详情字符串"""
        action_type = action.get('type', '')

        if action_type == 'mouse_move':
            x, y = action.get('x', 0), action.get('y', 0)
            return f"移动到 ({x}, {y})"

        elif action_type == 'mouse_move_relative':
            dx, dy = action.get('dx', 0), action.get('dy', 0)
            return f"相对移动 (dx={dx}, dy={dy})"

        elif action_type == 'mouse_click':
            x, y = action.get('x', 0), action.get('y', 0)
            button = action.get('button', 'left')
            pressed = action.get('pressed', True)
            action_str = "按下" if pressed else "释放"
            button_map = {'left': '左键', 'right': '右键', 'middle': '中键'}
            button_str = button_map.get(button, button)
            return f"{button_str}{action_str} at ({x}, {y})"

        elif action_type == 'mouse_scroll':
            dx, dy = action.get('dx', 0), action.get('dy', 0)
            return f"滚轮 (dx={dx}, dy={dy})"

        elif self._is_keyboard_action_type(action_type):
            key = action.get('key', '')
            action_str = "按下" if self._is_keyboard_action_pressed(action) else "释放"
            return f"{action_str}: {key}"

        elif action_type == 'delay':
            duration = action.get('duration', 0)
            return f"等待 {duration} 秒"

        return str(action)

    def _get_selected_row_indices(self) -> List[int]:
        """获取当前选中的行号，按升序返回。"""
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return []
        return sorted({row.row() for row in selection_model.selectedRows()})

    def _get_action_time_value(self, row: int) -> float:
        """安全获取指定步骤的时间值。"""
        if row < 0 or row >= len(self.actions):
            return 0.0
        try:
            return max(0.0, float(self.actions[row].get('time', 0) or 0.0))
        except (TypeError, ValueError):
            return 0.0

    def on_selection_changed(self):
        """选择改变时"""
        selected_rows = self._get_selected_row_indices()

        if selected_rows:
            row = selected_rows[0]
            self.current_row = row

            # 更新按钮状态
            has_single_selection = len(selected_rows) == 1
            has_any_selection = len(selected_rows) > 0

            self.edit_btn.setEnabled(has_single_selection)
            self.delete_btn.setEnabled(has_any_selection)
            self.move_up_btn.setEnabled(has_single_selection and row > 0)
            self.move_down_btn.setEnabled(has_single_selection and row < len(self.actions) - 1)
            self.apply_quick_edit_btn.setEnabled(has_single_selection)
            self.bulk_add_time_btn.setEnabled(has_any_selection)
            self.bulk_reduce_time_btn.setEnabled(has_any_selection)

            # 显示详情（仅单选时）
            if has_single_selection:
                action = self.actions[row]
                self.show_action_detail(action)
                self.quick_time_spin.setValue(action.get('time', 0))
            else:
                self.detail_text.setHtml(
                    self._build_info_message_html(
                        f"已选中 {len(selected_rows)} 个步骤。批量调时会从第 {row + 1} 步开始作用到后续全部步骤。"
                    )
                )
        else:
            self.current_row = -1
            self.edit_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            self.move_up_btn.setEnabled(False)
            self.move_down_btn.setEnabled(False)
            self.apply_quick_edit_btn.setEnabled(False)
            self.bulk_add_time_btn.setEnabled(False)
            self.bulk_reduce_time_btn.setEnabled(False)
            self._show_detail_placeholder()

    def show_action_detail(self, action: Dict[str, Any]):
        """显示步骤详细信息"""
        detail_items = [("时间", f"{action.get('time', 0):.3f} 秒")]

        action_type = action.get('type', '')

        if action_type in ['mouse_move', 'mouse_click']:
            detail_items.append(("X坐标", str(action.get('x', 0))))
            detail_items.append(("Y坐标", str(action.get('y', 0))))

            if action_type == 'mouse_click':
                button = action.get('button', 'left')
                pressed = action.get('pressed', True)
                button_display_map = {'left': '左键', 'right': '右键', 'middle': '中键'}
                button_display = button_display_map.get(button, button)
                detail_items.append(("按钮", button_display))
                detail_items.append(("状态", '按下' if pressed else '释放'))

        elif action_type == 'mouse_move_relative':
            detail_items.append(("X位移", str(action.get('dx', 0))))
            detail_items.append(("Y位移", str(action.get('dy', 0))))

        elif action_type == 'mouse_scroll':
            detail_items.append(("水平滚动", str(action.get('dx', 0))))
            detail_items.append(("垂直滚动", str(action.get('dy', 0))))

        elif self._is_keyboard_action_type(action_type):
            detail_items.append(("按键", str(action.get('key', ''))))
            detail_items.append(("状态", '按下' if self._is_keyboard_action_pressed(action) else '释放'))

        elif action_type == 'delay':
            detail_items.append(("延时", f"{action.get('duration', 0)} 秒"))

        self.detail_text.setHtml(self._build_action_detail_html(action, detail_items))

    def add_action(self, action_type: str):
        """添加新步骤"""
        # 计算默认时间（在最后一个步骤之后）
        default_time = 0
        if self.actions:
            default_time = self.actions[-1].get('time', 0) + 0.5

        # 根据类型创建默认步骤
        new_action = {'type': action_type, 'time': default_time}

        if action_type == 'mouse_move':
            new_action.update({'x': 0, 'y': 0})
        elif action_type == 'mouse_click':
            new_action.update({'x': 0, 'y': 0, 'button': 'left', 'pressed': True})
        elif action_type == 'key_press':
            new_action.update({'key': 'a'})
        elif action_type == 'key_release':
            new_action.update({'key': 'a'})
        elif action_type == 'mouse_scroll':
            new_action.update({'dx': 0, 'dy': 1})
        elif action_type == 'delay':
            new_action.update({'duration': 1.0})

        # 打开编辑对话框
        if self.edit_action_dialog(new_action):
            self.actions.append(new_action)
            self.actions.sort(key=lambda a: a.get('time', 0))  # 按时间排序
            self.load_actions()

            # 选中新添加的步骤
            for i, action in enumerate(self.actions):
                if action is new_action:
                    self.table.selectRow(i)
                    break

    def edit_selected_action(self):
        """编辑选中的步骤"""
        if self.current_row < 0 or self.current_row >= len(self.actions):
            return

        action = self.actions[self.current_row]
        if self.edit_action_dialog(action):
            self.actions.sort(key=lambda a: a.get('time', 0))  # 重新排序
            self.load_actions()

            # 重新选中该步骤
            for i, a in enumerate(self.actions):
                if a is action:
                    self.table.selectRow(i)
                    break

    def edit_action_dialog(self, action: Dict[str, Any]) -> bool:
        """打开步骤编辑对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle("编辑步骤")
        dialog.setMinimumWidth(400)

        layout = QFormLayout(dialog)

        # 时间
        time_spin = NoWheelDoubleSpinBox()
        time_spin.setRange(0, 10000)
        time_spin.setDecimals(3)
        time_spin.setValue(action.get('time', 0))
        time_spin.setSuffix(" 秒")
        layout.addRow("时间:", time_spin)

        action_type = action.get('type', '')

        # 根据类型添加不同的编辑控件
        x_spin = y_spin = None
        button_combo = mouse_pressed_check = key_pressed_check = None
        key_edit = None
        dx_spin = dy_spin = None
        duration_spin = None

        if action_type in ['mouse_move', 'mouse_click']:
            x_spin = NoWheelSpinBox()
            x_spin.setRange(0, 10000)
            x_spin.setValue(action.get('x', 0))
            layout.addRow("X坐标:", x_spin)

            y_spin = NoWheelSpinBox()
            y_spin.setRange(0, 10000)
            y_spin.setValue(action.get('y', 0))
            layout.addRow("Y坐标:", y_spin)

            if action_type == 'mouse_click':
                button_combo = QComboBox(dialog)
                button_combo.addItems(['左键', '右键', '中键'])

                # 将内部值映射到显示文本
                button_value = action.get('button', 'left')
                button_display_map = {'left': '左键', 'right': '右键', 'middle': '中键'}
                button_combo.setCurrentText(button_display_map.get(button_value, '左键'))
                layout.addRow("按钮:", button_combo)

                mouse_pressed_check = QCheckBox("按下（取消勾选表示释放）")
                mouse_pressed_check.setChecked(action.get('pressed', True))
                layout.addRow("状态:", mouse_pressed_check)

        elif action_type == 'mouse_move_relative':
            dx_spin = NoWheelSpinBox()
            dx_spin.setRange(-10000, 10000)
            dx_spin.setValue(action.get('dx', 0))
            layout.addRow("X位移:", dx_spin)

            dy_spin = NoWheelSpinBox()
            dy_spin.setRange(-10000, 10000)
            dy_spin.setValue(action.get('dy', 0))
            layout.addRow("Y位移:", dy_spin)

        elif action_type == 'mouse_scroll':
            dx_spin = NoWheelSpinBox()
            dx_spin.setRange(-1000, 1000)
            dx_spin.setValue(action.get('dx', 0))
            layout.addRow("水平滚动:", dx_spin)

            dy_spin = NoWheelSpinBox()
            dy_spin.setRange(-1000, 1000)
            dy_spin.setValue(action.get('dy', 0))
            layout.addRow("垂直滚动:", dy_spin)

        elif self._is_keyboard_action_type(action_type):
            key_edit = QLineEdit()
            key_edit.setText(action.get('key', ''))
            layout.addRow("按键:", key_edit)

            key_pressed_check = QCheckBox("按下（取消勾选表示释放）")
            key_pressed_check.setChecked(self._is_keyboard_action_pressed(action))
            layout.addRow("状态:", key_pressed_check)

        elif action_type == 'delay':
            duration_spin = NoWheelDoubleSpinBox()
            duration_spin.setRange(0, 3600)
            duration_spin.setDecimals(2)
            duration_spin.setValue(action.get('duration', 1.0))
            duration_spin.setSuffix(" 秒")
            layout.addRow("延时:", duration_spin)

        # 按钮
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 更新步骤数据
            action['time'] = time_spin.value()

            if x_spin and y_spin:
                action['x'] = x_spin.value()
                action['y'] = y_spin.value()

            if button_combo:
                # 将显示文本转换回内部值
                button_reverse_map = {'左键': 'left', '右键': 'right', '中键': 'middle'}
                action['button'] = button_reverse_map.get(button_combo.currentText(), 'left')

            if mouse_pressed_check is not None:
                action['pressed'] = mouse_pressed_check.isChecked()

            if key_edit:
                action['key'] = key_edit.text()

            if key_pressed_check is not None:
                self._set_keyboard_action_pressed(action, key_pressed_check.isChecked())

            if dx_spin and dy_spin:
                action['dx'] = dx_spin.value()
                action['dy'] = dy_spin.value()

            if duration_spin:
                action['duration'] = duration_spin.value()

            return True

        return False

    def delete_selected_actions(self):
        """批量删除选中的步骤"""
        selected_rows = self.table.selectionModel().selectedRows()

        if not selected_rows:
            return

        # 获取选中的行号列表并排序
        row_indices = sorted([row.row() for row in selected_rows], reverse=True)

        # 确认对话框
        count = len(row_indices)
        if count == 1:
            reply = QMessageBox.question(
                self, '确认删除',
                f'确定要删除步骤 #{row_indices[0] + 1} 吗？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
        else:
            reply = QMessageBox.question(
                self, '确认删除',
                f'确定要删除选中的 {count} 个步骤吗？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

        if reply == QMessageBox.StandardButton.Yes:
            # 从后往前删除，避免索引变化
            for row_index in row_indices:
                if 0 <= row_index < len(self.actions):
                    del self.actions[row_index]

            self.load_actions()

    def move_action_up(self):
        """上移步骤"""
        if self.current_row <= 0:
            return

        # 交换时间
        current_time = self.actions[self.current_row].get('time', 0)
        prev_time = self.actions[self.current_row - 1].get('time', 0)

        self.actions[self.current_row]['time'] = prev_time
        self.actions[self.current_row - 1]['time'] = current_time

        # 重新排序
        self.actions.sort(key=lambda a: a.get('time', 0))
        self.load_actions()

        # 选中上移后的位置
        self.table.selectRow(self.current_row - 1)

    def move_action_down(self):
        """下移步骤"""
        if self.current_row < 0 or self.current_row >= len(self.actions) - 1:
            return

        # 交换时间
        current_time = self.actions[self.current_row].get('time', 0)
        next_time = self.actions[self.current_row + 1].get('time', 0)

        self.actions[self.current_row]['time'] = next_time
        self.actions[self.current_row + 1]['time'] = current_time

        # 重新排序
        self.actions.sort(key=lambda a: a.get('time', 0))
        self.load_actions()

        # 选中下移后的位置
        self.table.selectRow(self.current_row + 1)

    def apply_quick_edit(self):
        """应用快速编辑"""
        if self.current_row < 0 or self.current_row >= len(self.actions):
            return

        self.actions[self.current_row]['time'] = self.quick_time_spin.value()
        self.actions.sort(key=lambda a: a.get('time', 0))
        self.load_actions()

        # 重新选中
        for i, action in enumerate(self.actions):
            if i == self.current_row:
                self.table.selectRow(i)
                break

    def apply_bulk_time_shift(self, direction: int):
        """从首个选中步骤开始批量平移时间轴。"""
        selected_rows = self._get_selected_row_indices()
        if not selected_rows:
            QMessageBox.warning(self, "提示", "请先选择至少一个步骤")
            return

        shift_seconds = float(self.bulk_time_offset_spin.value())
        if shift_seconds <= 0:
            QMessageBox.warning(self, "提示", "偏移时间必须大于 0 秒")
            return

        anchor_row = selected_rows[0]
        applied_shift = shift_seconds if direction >= 0 else -shift_seconds

        if direction < 0:
            anchor_time = self._get_action_time_value(anchor_row)
            lower_bound = self._get_action_time_value(anchor_row - 1) if anchor_row > 0 else 0.0
            max_reducible = max(0.0, anchor_time - lower_bound)
            if max_reducible <= 0:
                QMessageBox.warning(self, "无法减少", "首个选中步骤已经贴近前一步，不能继续减少时间")
                return
            if shift_seconds > max_reducible:
                applied_shift = -max_reducible

        for row in range(anchor_row, len(self.actions)):
            base_time = self._get_action_time_value(row)
            self.actions[row]['time'] = round(max(0.0, base_time + applied_shift), 6)

        self.actions.sort(key=lambda a: a.get('time', 0))
        self.load_actions()
        self.table.selectRow(anchor_row)

        if direction < 0 and abs(abs(applied_shift) - shift_seconds) > 1e-9:
            QMessageBox.information(
                self,
                "已按边界调整",
                f"可减少的最大时间只有 {abs(applied_shift):.3f} 秒，已自动按上限处理"
            )

    def optimize_actions(self):
        """优化步骤（移除冗余的鼠标移动）"""
        if not self.actions:
            return

        # 移除连续的鼠标移动，只保留最后一个
        optimized = []
        i = 0

        while i < len(self.actions):
            action = self.actions[i]

            if action.get('type') == 'mouse_move':
                # 查找连续的鼠标移动
                j = i + 1
                while j < len(self.actions) and self.actions[j].get('type') == 'mouse_move':
                    j += 1

                # 只保留最后一个鼠标移动
                if j > i + 1:
                    optimized.append(self.actions[j - 1])
                    i = j
                else:
                    optimized.append(action)
                    i += 1
            else:
                optimized.append(action)
                i += 1

        removed_count = len(self.actions) - len(optimized)

        if removed_count > 0:
            self.actions = optimized
            self.load_actions()
            QMessageBox.information(self, "优化完成", f"已移除 {removed_count} 个冗余步骤")
        else:
            QMessageBox.information(self, "优化完成", "没有发现冗余步骤")

    def clear_all_actions(self):
        """清空所有步骤"""
        reply = QMessageBox.question(
            self, '确认清空',
            '确定要清空所有步骤吗？此操作不可撤销！',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.actions.clear()
            self.load_actions()

    def import_from_json(self):
        """从JSON导入"""
        text, ok = QInputDialog.getMultiLineText(
            self, "导入JSON",
            "粘贴JSON数据:",
            ""
        )

        if ok and text:
            try:
                imported_actions = json.loads(text)
                if isinstance(imported_actions, list):
                    self.actions = imported_actions
                    self.load_actions()
                    QMessageBox.information(self, "导入成功", f"已导入 {len(self.actions)} 个步骤")
                else:
                    QMessageBox.warning(self, "导入失败", "JSON格式错误，应该是一个数组")
            except Exception as e:
                QMessageBox.warning(self, "导入失败", f"解析JSON失败: {e}")

    def export_to_json(self):
        """导出为JSON"""
        json_str = json.dumps(self.actions, indent=2, ensure_ascii=False)

        dialog = QDialog(self)
        dialog.setWindowTitle("导出JSON")
        dialog.setMinimumSize(500, 400)

        layout = QVBoxLayout(dialog)

        text_edit = QTextEdit()
        text_edit.setPlainText(json_str)
        text_edit.selectAll()
        layout.addWidget(text_edit)

        btn_layout = QHBoxLayout()
        copy_btn = QPushButton("复制到剪贴板")
        copy_btn.clicked.connect(lambda: self.copy_to_clipboard(json_str))
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(copy_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        dialog.exec()

    def copy_to_clipboard(self, text: str):
        """复制到剪贴板"""
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        QMessageBox.information(self, "复制成功", "JSON已复制到剪贴板")

    def update_stats_label(self):
        """更新统计标签"""
        total = len(self.actions)

        # 统计各类型数量
        type_counts = {}
        for action in self.actions:
            action_type = action.get('type', 'unknown')
            type_counts[action_type] = type_counts.get(action_type, 0) + 1

        # 计算总时长
        total_duration = 0
        if self.actions:
            total_duration = self.actions[-1].get('time', 0)

        stats_parts = [
            f"录制区域: {self.recording_area}",
            f"录制模式: {self.recording_mode}",
            f"总步骤: {total}",
        ]

        if type_counts:
            type_str = ", ".join([f"{self.get_type_display_name(k)}: {v}" for k, v in type_counts.items()])
            stats_parts.append(type_str)

        stats_parts.append(f"总时长: {total_duration:.2f}秒")

        self.stats_label.setText(" | ".join(stats_parts))

    def get_actions(self) -> List[Dict[str, Any]]:
        """获取编辑后的步骤列表"""
        return self.actions

    def on_start_checkbox_changed(self, row: int, state: int):
        """处理起始步骤复选框变化，确保只有一个被选中"""
        if state == Qt.CheckState.Checked.value:
            # 取消其他所有复选框
            for i in range(self.table.rowCount()):
                if i != row:
                    widget = self.table.cellWidget(i, 0)
                    if widget:
                        checkbox = widget.findChild(QCheckBox)
                        if checkbox:
                            checkbox.blockSignals(True)
                            checkbox.setChecked(False)
                            checkbox.blockSignals(False)

            self.start_from_index = row
            self._has_custom_start_step = True
            logger.info(f"设置回放起始步骤为: {row + 1}")
        else:
            # 如果取消了当前选中的，重置为0
            if row == self.start_from_index:
                self.start_from_index = 0
                self._has_custom_start_step = False
                logger.info("取消起始步骤标记，将从头开始回放")

    def test_replay_from_start(self):
        """从选中的起始步骤开始测试回放 - 调用测试回放按钮的逻辑"""
        if not self.actions:
            QMessageBox.warning(self, "无法回放", "没有可回放的步骤")
            return

        # 获取选中的起始步骤
        start_index = self.start_from_index

        # 确认对话框
        if start_index > 0:
            reply = QMessageBox.question(
                self, '确认回放',
                f'将从第 {start_index + 1} 步开始回放，共 {len(self.actions) - start_index} 步\n是否继续？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
        else:
            reply = QMessageBox.question(
                self, '确认回放',
                f'将从头开始回放，共 {len(self.actions)} 步\n是否继续？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

        if reply == QMessageBox.StandardButton.No:
            return

        # 调用 parameter_panel 的测试回放逻辑
        try:
            # 临时保存当前的 actions 和 start_from_index
            # 将从指定步骤开始的 actions 传递给测试回放
            actions_to_replay = self.actions[start_index:]  # 只传递从起始索引开始的动作

            # 调整时间戳：从0开始
            if actions_to_replay:
                first_time = actions_to_replay[0].get('time', 0)
                adjusted_actions = []
                for action in actions_to_replay:
                    new_action = action.copy()
                    new_action['time'] = action.get('time', 0) - first_time
                    adjusted_actions.append(new_action)

                # 构造回放数据
                replay_data = {
                    'actions': adjusted_actions,
                    'recording_area': self.recording_area,
                    'recording_mode': self.recording_mode
                }

                # 模拟测试回放：使用与 parameter_panel._start_replay 相同的逻辑
                self._run_test_replay(replay_data)

        except Exception as e:
            logger.error(f"启动回放测试失败: {e}", exc_info=True)
            QMessageBox.warning(self, "回放失败", f"启动回放测试失败: {e}")

    def _run_test_replay(self, replay_data: dict):
        """执行测试回放。"""
        actions = replay_data['actions']
        recording_area = replay_data.get('recording_area', '全屏录制')
        recording_mode = replay_data.get('recording_mode', '绝对坐标')

        if not actions:
            QMessageBox.warning(self, "回放失败", "没有可回放的步骤")
            return

        thread = getattr(self, '_replay_thread', None)
        if thread and thread.isRunning():
            QMessageBox.warning(self, "回放进行中", "请等待当前测试回放结束")
            return

        window_offset_x, window_offset_y = resolve_replay_window_offsets_from_config(
            recording_area,
            log_prefix='步骤编辑器回放',
        )
        if window_offset_x is None or window_offset_y is None:
            QMessageBox.warning(self, "回放失败", "无法进行窗口回放")
            return

        self.clear_all_highlights()
        self._replay_thread = ParameterPanelReplayThread(
            actions,
            1.0,
            1,
            recording_area,
            window_offset_x,
            window_offset_y,
            recording_mode,
        )
        self._replay_thread.step_changed.connect(self.highlight_step)
        self._replay_thread.result_signal.connect(self._on_test_replay_result)
        self._replay_thread.finished.connect(self._on_replay_thread_finished)
        self._replay_thread.start()

    def _on_test_replay_result(self, success: bool, message: str):
        """处理测试回放结果。"""
        def handle_result():
            self.clear_all_highlights()
            if success:
                QMessageBox.information(self, "回放完成", "测试回放已完成")
            else:
                QMessageBox.warning(self, "回放失败", message or "回放测试失败")

        self._run_on_ui_thread(handle_result, "处理测试回放结果失败")

    def _on_replay_thread_finished(self):
        """回放线程结束清理"""
        thread = getattr(self, '_replay_thread', None)
        if not thread:
            return
        self._replay_thread = None
        try:
            thread.deleteLater()
        except RuntimeError:
            pass

    def _stop_active_replay_thread(self):
        """关闭对话框前停止测试回放线程。"""
        thread = getattr(self, '_replay_thread', None)
        if not thread or not thread.isRunning():
            return

        try:
            thread.stop()
        except Exception as exc:
            logger.error(f"停止测试回放线程失败: {exc}", exc_info=True)
            return

        if hasattr(thread, 'wait'):
            try:
                if not thread.wait(1500):
                    logger.warning("测试回放线程未在关闭前及时退出")
            except Exception as exc:
                logger.error(f"等待测试回放线程退出失败: {exc}", exc_info=True)

    def _run_on_ui_thread(self, callback, error_prefix: str):
        """确保回调在UI线程执行。"""
        if not callable(callback):
            return

        def _safe_callback():
            try:
                callback()
            except Exception as exc:
                logger.error(f"{error_prefix}: {exc}")

        if QThread.currentThread() == self.thread():
            _safe_callback()
            return

        QTimer.singleShot(0, self, _safe_callback)

    def highlight_step(self, index: int):
        """高亮显示当前执行的步骤"""
        def do_highlight():
            # 清除之前的高亮
            for i in range(self.table.rowCount()):
                for j in range(1, 6):  # 跳过复选框列
                    item = self.table.item(i, j)
                    if item:
                        item.setBackground(QColor(255, 255, 255))  # 白色背景

            # 高亮当前步骤
            if 0 <= index < self.table.rowCount():
                for j in range(1, 6):  # 跳过复选框列
                    item = self.table.item(index, j)
                    if item:
                        item.setBackground(QColor(255, 255, 0))  # 黄色高亮

                # 滚动到当前步骤
                self.table.scrollToItem(self.table.item(index, 1))

        self._run_on_ui_thread(do_highlight, "高亮步骤失败")

    def clear_all_highlights(self):
        """清除所有高亮"""
        def do_clear():
            for i in range(self.table.rowCount()):
                for j in range(1, 6):
                    item = self.table.item(i, j)
                    if item:
                        item.setBackground(QColor(255, 255, 255))

        self._run_on_ui_thread(do_clear, "清除高亮失败")

    def accept(self):
        """确定按钮"""
        self._stop_active_replay_thread()
        self.actions_updated.emit(self.actions)
        super().accept()

    def reject(self):
        """取消按钮。"""
        self._stop_active_replay_thread()
        super().reject()

    def closeEvent(self, event):
        """关闭窗口时确保回放线程退出。"""
        self._stop_active_replay_thread()
        super().closeEvent(event)
