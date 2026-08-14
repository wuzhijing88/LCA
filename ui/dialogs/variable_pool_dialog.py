# -*- coding: utf-8 -*-

import json
import logging
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QCheckBox,
    QMenu,
    QPushButton,
    QFrame,
    QHeaderView,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QWidget,
    QVBoxLayout,
)

from task_workflow.global_var_store import ensure_global_context_loaded
from task_workflow.workflow_context import get_workflow_context
from task_workflow.workflow_vars import get_context_for_task, update_context_from_variables
from ui.system_parts.message_box_translator import show_information_box, show_question_box
from themes import get_theme_manager
from ..widgets.custom_widgets import CustomDropdown as QComboBox
from ..system_parts.menu_style import apply_unified_menu_style

logger = logging.getLogger(__name__)

SYSTEM_VAR_PREFIXES = ("latest_ocr_", "latest_yolo_")

_TYPE_LABELS = {
    bool: "布尔",
    int: "整数",
    float: "浮点",
    str: "字符串",
    list: "列表",
    tuple: "元组",
    dict: "字典",
    type(None): "空",
}

_EDIT_TYPE_OPTIONS = [
    ("字符串", "string"),
    ("整数", "int"),
    ("浮点", "float"),
    ("布尔", "bool"),
    ("随机数", "random"),
    ("表达式", "expression"),
    ("列表(JSON)", "list"),
    ("字典(JSON)", "dict"),
    ("空", "null"),
]

_RANDOM_DEFAULTS = {
    "mode": "int",
    "min": 0,
    "max": 100,
    "precision": 2,
    "refresh": "per_run",
}
_EXPR_DEFAULTS = {
    "expr": "",
    "refresh": "manual",
}

_GLOBAL_VARIABLE_PRESETS = {
    "string": [
        {"label": "状态：成功", "value": "成功"},
        {"label": "状态：失败", "value": "失败"},
        {"label": "账号标识", "value": "account_001"},
        {"label": "提示消息", "value": "操作完成"},
        {"label": "本地文件", "value": "C:\\LCA\\data\\example.json"},
    ],
    "int": [
        {"label": "计数：0", "value": "0"},
        {"label": "计数：1", "value": "1"},
        {"label": "重试次数：3", "value": "3"},
        {"label": "最大重试：5", "value": "5"},
    ],
    "float": [
        {"label": "比例：0.5", "value": "0.5"},
        {"label": "比例：1.0", "value": "1.0"},
        {"label": "阈值：0.75", "value": "0.75"},
        {"label": "精度：0.01", "value": "0.01"},
    ],
    "bool": [
        {"label": "布尔：真", "value": "true"},
        {"label": "布尔：假", "value": "false"},
    ],
    "list": [
        {"label": "空列表", "value": "[]"},
        {"label": "账号列表", "value": "[\"账号1\", \"账号2\"]"},
        {"label": "数字列表", "value": "[1, 2, 3]"},
        {"label": "坐标点列表", "value": "[{\"x\": 100, \"y\": 200}, {\"x\": 120, \"y\": 260}]"},
    ],
    "dict": [
        {"label": "空字典", "value": "{}"},
        {"label": "账号对象", "value": "{\"username\": \"账号\", \"password\": \"密码\"}"},
        {"label": "状态对象", "value": "{\"ok\": true, \"message\": \"成功\"}"},
        {"label": "重试配置", "value": "{\"retry\": 0, \"max_retry\": 3, \"delay\": 1.5}"},
        {"label": "坐标对象", "value": "{\"x\": 100, \"y\": 200}"},
    ],
    "expression": [
        {"label": "自增计数", "value": "转数字(self) + 1"},
        {"label": "读取全局计数并自增", "value": "转数字(取值(\"全局:计数\")) + 1"},
        {"label": "判断是否包含成功", "value": "包含(取值(\"登录.消息\"), \"成功\")"},
        {"label": "获取列表长度", "value": "长度(取值(\"任务.列表\"))"},
        {"label": "字符串去空格", "value": "去空格(取值(\"账号.用户名\"))"},
        {"label": "存在性判断", "value": "存在(\"全局:令牌\")"},
    ],
    "random": [
        {
            "label": "整数 1~100（每次执行）",
            "config": {"mode": "int", "min": 1, "max": 100, "precision": 0, "refresh": "per_run"},
        },
        {
            "label": "整数 0~9（每次读取）",
            "config": {"mode": "int", "min": 0, "max": 9, "precision": 0, "refresh": "on_read"},
        },
        {
            "label": "浮点 0~1（3位小数）",
            "config": {"mode": "float", "min": 0, "max": 1, "precision": 3, "refresh": "on_read"},
        },
        {
            "label": "浮点 -1~1（4位小数）",
            "config": {"mode": "float", "min": -1, "max": 1, "precision": 4, "refresh": "per_run"},
        },
    ],
}

_IMPORT_FIELD_ALIASES = {
    "name": "name",
    "label": "name",
    "title": "name",
    "名称": "name",
    "名字": "name",
    "用户名": "username",
    "账号": "username",
    "账户": "username",
    "user": "username",
    "username": "username",
    "password": "password",
    "pwd": "password",
    "pass": "password",
    "密码": "password",
    "标签": "tag",
    "备注": "tag",
    "说明": "tag",
    "tag": "tag",
    "note": "tag",
    "remark": "tag",
    "忽略": "ignore",
    "跳过": "ignore",
    "ignore": "ignore",
    "skip": "ignore",
    "value": "value",
    "值": "value",
    "内容": "value",
}

_ROUTE_NUM_PATTERN = re.compile(r"[-+]?\d*\.?\d+")
_DISPLAY_PREVIEW_MAX_DEPTH = 3
_DISPLAY_PREVIEW_MAX_ITEMS = 20
_DISPLAY_PREVIEW_MAX_STR_LEN = 160


def _truncate_display_text(text: str, max_len: int = _DISPLAY_PREVIEW_MAX_STR_LEN) -> str:
    content = str(text)
    if len(content) <= max_len:
        return content
    return f"{content[:max_len]}...(共{len(content)}字符)"


def _container_summary(value: Any) -> str:
    try:
        size = len(value)  # type: ignore[arg-type]
    except Exception:
        size = "?"
    if isinstance(value, dict):
        return f"<字典 {size}项>"
    if isinstance(value, tuple):
        return f"<元组 {size}项>"
    if isinstance(value, set):
        return f"<集合 {size}项>"
    return f"<列表 {size}项>"


def _is_status_variable(name: Any) -> bool:
    if not name:
        return False
    text = str(name)
    return text == "\u72b6\u6001" or text.endswith(".\u72b6\u6001")


def _normalize_value_for_display(
    value: Any,
    status_label: bool = False,
    *,
    _depth: int = 0,
    _seen: Optional[set] = None,
) -> Any:
    _ = status_label  # 预留参数，保持兼容调用方
    if _seen is None:
        _seen = set()
    if isinstance(value, bool):
        return "\u6210\u529f" if value else "\u5931\u8d25"
    if value is None:
        return "\u7a7a"
    if isinstance(value, str):
        return _truncate_display_text(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (dict, list, tuple, set)):
        identity = id(value)
        if identity in _seen:
            return "<循环引用>"
        if _depth >= _DISPLAY_PREVIEW_MAX_DEPTH:
            return _container_summary(value)

        _seen.add(identity)
        try:
            if isinstance(value, dict):
                normalized: Dict[str, Any] = {}
                for idx, (k, v) in enumerate(value.items()):
                    if idx >= _DISPLAY_PREVIEW_MAX_ITEMS:
                        break
                    normalized[str(k)] = _normalize_value_for_display(
                        v, _depth=_depth + 1, _seen=_seen
                    )
                remaining = len(value) - len(normalized)
                if remaining > 0:
                    normalized["__more__"] = f"...其余{remaining}项"
                return normalized

            seq = list(value) if isinstance(value, set) else value
            normalized_list = []
            for idx, item in enumerate(seq):
                if idx >= _DISPLAY_PREVIEW_MAX_ITEMS:
                    break
                normalized_list.append(
                    _normalize_value_for_display(item, _depth=_depth + 1, _seen=_seen)
                )
            remaining = len(seq) - len(normalized_list)
            if remaining > 0:
                normalized_list.append(f"...其余{remaining}项")
            return normalized_list
        finally:
            _seen.discard(identity)
    return value





def _format_type(value: Any) -> str:
    if isinstance(value, bool):
        return _TYPE_LABELS[bool]
    if value is None:
        return _TYPE_LABELS[type(None)]
    for py_type, label in _TYPE_LABELS.items():
        if py_type in (bool, type(None)):
            continue
        if isinstance(value, py_type):
            return label
    return type(value).__name__


def _format_value(value: Any, max_len: int = 300, var_name: Any = None) -> str:
    try:
        value = _normalize_value_for_display(value, status_label=_is_status_variable(var_name))
        if isinstance(value, (dict, list, tuple)):
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        elif isinstance(value, (int, float, str)) or value is None:
            text = str(value)
        else:
            text = f"<{type(value).__name__}>"
    except Exception as exc:
        logger.debug("变量值格式化失败: %s", exc)
        text = f"<{type(value).__name__}>"

    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _resolve_delimiter(text: str) -> str:
    raw = (text or "").strip()
    if raw in ("\\t", "tab", "TAB"):
        return "\t"
    return raw


def _coerce_route_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _parse_route_point(value: Any) -> Optional[Tuple[int, int]]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        x_val = _coerce_route_number(value[0])
        y_val = _coerce_route_number(value[1])
        if x_val is None or y_val is None:
            return None
        return int(round(x_val)), int(round(y_val))
    if isinstance(value, dict):
        for x_key, y_key in (
            ("x", "y"),
            ("X", "Y"),
            ("坐标X", "坐标Y"),
        ):
            if x_key in value and y_key in value:
                x_val = _coerce_route_number(value.get(x_key))
                y_val = _coerce_route_number(value.get(y_key))
                if x_val is None or y_val is None:
                    return None
                return int(round(x_val)), int(round(y_val))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        nums = _ROUTE_NUM_PATTERN.findall(text)
        if len(nums) >= 2:
            try:
                return int(round(float(nums[0]))), int(round(float(nums[1])))
            except ValueError:
                return None
    return None


def _parse_route_points(data: Any) -> List[List[int]]:
    if data is None:
        return []
    if isinstance(data, str):
        return _parse_route_text(data)
    if isinstance(data, dict):
        for key in ("points", "route", "path", "coords", "coordinates", "data"):
            if key in data:
                return _parse_route_points(data.get(key))
        point = _parse_route_point(data)
        return [list(point)] if point else []
    if isinstance(data, (list, tuple)):
        points: List[List[int]] = []
        for item in data:
            point = _parse_route_point(item)
            if point:
                points.append(list(point))
        return points
    return []


def _parse_route_text(content: str) -> List[List[int]]:
    text = (content or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        return _parse_route_points(data)
    except Exception:
        pass

    points: List[List[int]] = []
    for raw_line in re.split(r"[\r\n]+", text):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for part in re.split(r"[;；]+", line):
            part = part.strip()
            if not part or part.startswith("#"):
                continue
            point = _parse_route_point(part)
            if point:
                points.append(list(point))
    return points


def _normalize_mapping_tokens(text: str) -> List[str]:
    raw = (text or "").strip()
    if not raw or raw in ("自动", "auto", "AUTO"):
        return []
    tokens = [part.strip() for part in re.split(r"[,\uFF0C]", raw) if part.strip()]
    normalized = []
    for token in tokens:
        key = _IMPORT_FIELD_ALIASES.get(token, _IMPORT_FIELD_ALIASES.get(token.lower()))
        if key:
            normalized.append(key)
        else:
            normalized.append(token)
    return normalized


def _auto_mapping(column_count: int) -> List[str]:
    if column_count <= 1:
        return ["value"]
    if column_count == 2:
        return ["username", "password"]
    if column_count == 3:
        return ["name", "username", "password"]
    base = ["name", "username", "password", "tag"]
    return base + ["ignore"] * max(0, column_count - len(base))


def _format_field_label(token: str) -> str:
    if token == "username":
        return "账号"
    if token == "password":
        return "密码"
    if token == "tag":
        return "标签"
    if token == "value":
        return "值"
    return token


def _sanitize_label(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _read_text_file(path: Path, encoding: str) -> str:
    if encoding == "自动":
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                return path.read_text(encoding=enc)
            except Exception:
                continue
        return path.read_text(encoding="utf-8", errors="ignore")
    return path.read_text(encoding=encoding)


class GlobalVarImportDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("导入全局变量")
        self.setMinimumSize(520, 320)
        self.resize(580, 360)

        self._path_edit = QLineEdit()
        browse_button = QPushButton("选择文件")
        browse_button.clicked.connect(self._on_browse)
        file_layout = QHBoxLayout()
        file_layout.addWidget(self._path_edit, 1)
        file_layout.addWidget(browse_button)

        self._encoding_combo = QComboBox()
        self._encoding_combo.addItems(["自动", "UTF-8", "UTF-8-SIG", "GBK"])

        self._delimiter_edit = QLineEdit("|")
        self._prefix_edit = QLineEdit("账号")
        self._mapping_edit = QLineEdit("")
        self._mapping_edit.setPlaceholderText("留空自动（如：name,username,password,tag）")

        self._skip_header_check = QCheckBox("跳过首行（表头）")
        self._encrypt_check = QCheckBox("加密密码字段")
        self._passphrase_edit = QLineEdit()
        self._passphrase_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._passphrase_edit.setEnabled(False)
        self._encrypt_check.toggled.connect(self._passphrase_edit.setEnabled)


        form_layout = QFormLayout()
        form_layout.addRow("文件", file_layout)
        form_layout.addRow("编码", self._encoding_combo)
        form_layout.addRow("分隔符", self._delimiter_edit)
        form_layout.addRow("前缀", self._prefix_edit)
        form_layout.addRow("字段顺序", self._mapping_edit)
        form_layout.addRow("", self._skip_header_check)
        form_layout.addRow("", self._encrypt_check)
        form_layout.addRow("加密密码", self._passphrase_edit)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_button:
            ok_button.setText("确定")
            ok_button.setProperty("primary", True)
        if cancel_button:
            cancel_button.setText("取消")
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(form_layout)
        layout.addWidget(button_box)

        self._options: Dict[str, Any] = {}

    def _on_browse(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "选择TXT文件", "", "Text Files (*.txt);;All Files (*)")
        if file_path:
            self._path_edit.setText(file_path)

    def _on_accept(self) -> None:
        path_text = self._path_edit.text().strip()
        if not path_text or not Path(path_text).exists():
            QMessageBox.warning(self, "导入失败", "请选择有效的TXT文件")
            return
        delimiter = _resolve_delimiter(self._delimiter_edit.text())
        if not delimiter:
            QMessageBox.warning(self, "导入失败", "分隔符不能为空")
            return
        encrypt = self._encrypt_check.isChecked()
        passphrase = self._passphrase_edit.text()
        if encrypt and not passphrase:
            QMessageBox.warning(self, "导入失败", "已启用加密，请输入加密密码")
            return
        self._options = {
            "path": path_text,
            "encoding": self._encoding_combo.currentText(),
            "delimiter": delimiter,
            "prefix": self._prefix_edit.text().strip(),
            "mapping": self._mapping_edit.text().strip(),
            "skip_header": self._skip_header_check.isChecked(),
            "encrypt": encrypt,
            "passphrase": passphrase,
        }
        self.accept()

    def get_options(self) -> Dict[str, Any]:
        return dict(self._options)


class RouteImportDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("导入坐标路线")
        self.setMinimumSize(520, 360)
        self.resize(600, 400)

        self._path_edit = QLineEdit()
        browse_button = QPushButton("选择文件")
        browse_button.clicked.connect(self._on_browse)
        file_layout = QHBoxLayout()
        file_layout.addWidget(self._path_edit, 1)
        file_layout.addWidget(browse_button)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("变量名（默认使用文件名）")

        self._encoding_combo = QComboBox()
        self._encoding_combo.addItems(["自动", "UTF-8", "UTF-8-SIG", "GBK"])

        form_layout = QFormLayout()
        form_layout.addRow("文件", file_layout)
        form_layout.addRow("编码", self._encoding_combo)
        form_layout.addRow("变量名", self._name_edit)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_button:
            ok_button.setText("确定")
            ok_button.setProperty("primary", True)
        if cancel_button:
            cancel_button.setText("取消")
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(form_layout)
        layout.addWidget(button_box)

        self._options: Dict[str, Any] = {}

    def _on_browse(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择路线文件",
            "",
            "Text/JSON Files (*.txt *.json);;All Files (*)",
        )
        if file_path:
            self._path_edit.setText(file_path)
            if not self._name_edit.text().strip():
                self._name_edit.setText(Path(file_path).stem)

    def _on_accept(self) -> None:
        path_text = self._path_edit.text().strip()
        if not path_text or not Path(path_text).exists():
            QMessageBox.warning(self, "导入失败", "请选择有效的路线文件")
            return
        name = self._name_edit.text().strip() or Path(path_text).stem
        if not name:
            QMessageBox.warning(self, "导入失败", "变量名不能为空")
            return
        encoding = self._encoding_combo.currentText()
        try:
            content = _read_text_file(Path(path_text), encoding)
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", f"读取文件失败：{exc}")
            return
        points = _parse_route_text(content)
        if not points:
            QMessageBox.warning(self, "导入失败", "未识别到有效坐标点")
            return
        self._options = {
            "name": name,
            "points": points,
        }
        self.accept()

    def get_options(self) -> Dict[str, Any]:
        return dict(self._options)


class GlobalVariableEditDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        title: str = "新增变量",
        name: str = "",
        value: Any = None,
        type_key: Optional[str] = None,
        random_config: Optional[Dict[str, Any]] = None,
        expr_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(460, 460)
        self.resize(600, 560)

        self._name_edit = QLineEdit()
        self._type_combo = QComboBox()
        self._value_edit = QPlainTextEdit()
        self._value_edit.setMinimumHeight(120)
        self._expr_container = QWidget()
        self._expr_edit = QPlainTextEdit()
        self._expr_edit.setMinimumHeight(80)
        self._expr_refresh_combo = QComboBox()
        self._expr_initial_edit = QLineEdit()
        self._random_container = QWidget()
        self._random_min_edit = QLineEdit()
        self._random_max_edit = QLineEdit()
        self._random_mode_combo = QComboBox()
        self._random_precision_edit = QLineEdit()
        self._random_refresh_combo = QComboBox()
        self._random_preview_label = QLabel("")
        self._random_generate_btn = QPushButton("生成预览")
        self._preset_widget = QWidget()
        self._preset_combo = QComboBox()
        self._preset_insert_btn = QPushButton("插入预设")
        combo_and_btn_widgets = (
            self._type_combo,
            self._random_mode_combo,
            self._random_refresh_combo,
            self._expr_refresh_combo,
            self._random_generate_btn,
            self._preset_combo,
            self._preset_insert_btn,
        )
        for widget in combo_and_btn_widgets:
            widget.setMinimumHeight(34)

        for label, key in _EDIT_TYPE_OPTIONS:
            self._type_combo.addItem(label, key)

        self._random_mode_combo.addItem("整数", "int")
        self._random_mode_combo.addItem("浮点", "float")
        self._random_refresh_combo.addItem("手动", "manual")
        self._random_refresh_combo.addItem("每次读取", "on_read")
        self._random_refresh_combo.addItem("每次执行", "per_run")
        self._random_preview_label.setObjectName("random_preview_label")
        self._random_preview_label.setWordWrap(True)
        self._random_generate_btn.clicked.connect(self._refresh_random_preview)
        self._preset_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._preset_insert_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._preset_insert_btn.setFixedWidth(96)
        self._preset_insert_btn.setProperty("primary", True)
        self._preset_insert_btn.clicked.connect(self._on_insert_preset)

        self._value_label = QLabel("值")
        self._expr_label = QLabel("表达式配置")
        self._random_label = QLabel("随机配置")

        self._expr_refresh_combo.addItem("手动", "manual")
        self._expr_refresh_combo.addItem("每次读取", "on_read")
        self._expr_refresh_combo.addItem("每次执行", "per_run")

        random_form = QFormLayout()
        random_form.setContentsMargins(0, 0, 0, 0)
        random_form.addRow("最小值", self._random_min_edit)
        random_form.addRow("最大值", self._random_max_edit)
        random_form.addRow("随机类型", self._random_mode_combo)
        random_form.addRow("精度(小数位)", self._random_precision_edit)
        random_form.addRow("刷新策略", self._random_refresh_combo)
        random_form.addRow("当前预览", self._random_preview_label)
        random_form.addRow("", self._random_generate_btn)
        self._random_container.setLayout(random_form)

        expr_form = QFormLayout()
        expr_form.setContentsMargins(0, 0, 0, 0)
        expr_form.addRow("表达式", self._expr_edit)
        expr_form.addRow("初始值", self._expr_initial_edit)
        expr_form.addRow("刷新策略", self._expr_refresh_combo)
        self._expr_container.setLayout(expr_form)

        preset_layout = QHBoxLayout()
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.setSpacing(8)
        preset_layout.addWidget(self._preset_combo, 1)
        preset_layout.addWidget(self._preset_insert_btn, 0)
        self._preset_widget.setLayout(preset_layout)

        form_layout = QFormLayout()
        form_layout.setVerticalSpacing(10)
        form_layout.addRow("变量名", self._name_edit)
        form_layout.addRow("类型", self._type_combo)
        form_layout.addRow("预设", self._preset_widget)
        form_layout.addRow(self._value_label, self._value_edit)
        form_layout.addRow(self._expr_label, self._expr_container)
        form_layout.addRow(self._random_label, self._random_container)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        for btn in button_box.buttons():
            btn.setMinimumHeight(34)

        form_container = QWidget()
        form_container.setLayout(form_layout)
        self._form_layout = form_layout
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setFrameShape(QFrame.Shape.NoFrame)
        form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        form_scroll.setWidget(form_container)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(form_scroll, 1)
        layout.addWidget(button_box)

        self._result_name = ""
        self._result_type = ""
        self._result_value = None

        self._name_edit.setText(str(name or ""))
        self._apply_initial_value(value, type_key, random_config, expr_config)

        self._expr_label.setVisible(False)
        self._expr_container.setVisible(False)
        self._random_label.setVisible(False)
        self._random_container.setVisible(False)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        self._on_type_changed(self._type_combo.currentIndex())

    def _normalize_type_key(self, raw: Any) -> Optional[str]:
        if not raw:
            return None
        text = str(raw).strip().lower()
        mapping = {
            "text": "string",
            "str": "string",
            "string": "string",
            "int": "int",
            "integer": "int",
            "float": "float",
            "double": "float",
            "bool": "bool",
            "boolean": "bool",
            "list": "list",
            "array": "list",
            "dict": "dict",
            "object": "dict",
            "map": "dict",
            "random": "random",
            "expression": "expression",
            "expr": "expression",
            "formula": "expression",
            "null": "null",
            "none": "null",
        }
        return mapping.get(text)

    def _infer_type_key(self, value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int) and not isinstance(value, bool):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, list):
            return "list"
        if isinstance(value, dict):
            return "dict"
        return "string"

    def _format_value_for_edit(self, value: Any, type_key: str) -> str:
        if type_key == "null":
            return ""
        if type_key in ("list", "dict"):
            try:
                return json.dumps(value, ensure_ascii=False, indent=2)
            except Exception:
                return ""
        if type_key == "bool":
            return "true" if bool(value) else "false"
        if value is None:
            return ""
        return str(value)

    def _normalize_random_config(self, config: Any) -> Dict[str, Any]:
        if not isinstance(config, dict):
            config = {}
        mode = str(config.get("mode", _RANDOM_DEFAULTS["mode"])).lower()
        if mode not in ("int", "float"):
            mode = _RANDOM_DEFAULTS["mode"]
        refresh = str(config.get("refresh", _RANDOM_DEFAULTS["refresh"])).lower()
        if refresh not in ("manual", "on_read", "per_run"):
            refresh = _RANDOM_DEFAULTS["refresh"]
        try:
            min_value = float(config.get("min", _RANDOM_DEFAULTS["min"]))
        except (TypeError, ValueError):
            min_value = float(_RANDOM_DEFAULTS["min"])
        try:
            max_value = float(config.get("max", _RANDOM_DEFAULTS["max"]))
        except (TypeError, ValueError):
            max_value = float(_RANDOM_DEFAULTS["max"])
        if max_value < min_value:
            min_value, max_value = max_value, min_value
        try:
            precision = int(config.get("precision", _RANDOM_DEFAULTS["precision"]))
        except (TypeError, ValueError):
            precision = _RANDOM_DEFAULTS["precision"]
        precision = max(0, min(6, precision))
        return {
            "mode": mode,
            "min": min_value,
            "max": max_value,
            "precision": precision,
            "refresh": refresh,
        }

    def _normalize_expr_config(self, config: Any) -> Dict[str, Any]:
        if not isinstance(config, dict):
            config = {"expr": str(config) if config is not None else ""}
        expr = str(config.get("expr", _EXPR_DEFAULTS["expr"])).strip()
        refresh = str(config.get("refresh", _EXPR_DEFAULTS["refresh"])).lower()
        if refresh not in ("manual", "on_read", "per_run"):
            refresh = _EXPR_DEFAULTS["refresh"]
        normalized = {"expr": expr, "refresh": refresh}
        if "initial" in config:
            normalized["initial"] = config.get("initial")
        return normalized

    def _apply_random_config(self, config: Optional[Dict[str, Any]], preview_value: Any) -> None:
        normalized = self._normalize_random_config(config or {})
        self._random_min_edit.setText(str(normalized["min"]))
        self._random_max_edit.setText(str(normalized["max"]))
        mode_index = self._random_mode_combo.findData(normalized["mode"])
        if mode_index >= 0:
            self._random_mode_combo.setCurrentIndex(mode_index)
        refresh_index = self._random_refresh_combo.findData(normalized["refresh"])
        if refresh_index >= 0:
            self._random_refresh_combo.setCurrentIndex(refresh_index)
        self._random_precision_edit.setText(str(normalized["precision"]))
        if preview_value is not None:
            self._random_preview_label.setText(str(preview_value))
        else:
            self._refresh_random_preview()

    def _apply_expr_config(self, config: Optional[Dict[str, Any]], initial_value: Any) -> None:
        normalized = self._normalize_expr_config(config or {})
        self._expr_edit.setPlainText(normalized["expr"])
        refresh_index = self._expr_refresh_combo.findData(normalized["refresh"])
        if refresh_index >= 0:
            self._expr_refresh_combo.setCurrentIndex(refresh_index)
        if initial_value is None and "initial" in normalized:
            initial_value = normalized.get("initial")
        initial_text = self._format_value_for_edit(initial_value, self._infer_type_key(initial_value))
        self._expr_initial_edit.setText(initial_text)

    def _apply_initial_value(
        self,
        value: Any,
        type_key: Optional[str],
        random_config: Optional[Dict[str, Any]],
        expr_config: Optional[Dict[str, Any]],
    ) -> None:
        normalized = self._normalize_type_key(type_key)
        if normalized is None:
            normalized = self._infer_type_key(value)
        index = self._type_combo.findData(normalized)
        if index >= 0:
            self._type_combo.setCurrentIndex(index)
        if normalized == "random":
            self._apply_random_config(random_config, value)
        elif normalized == "expression":
            self._apply_expr_config(expr_config, value)
        else:
            self._value_edit.setPlainText(self._format_value_for_edit(value, normalized))

    def _refresh_presets(self, type_key: Any) -> None:
        key = str(type_key or "")
        presets = _GLOBAL_VARIABLE_PRESETS.get(key, [])
        self._preset_combo.clear()
        for item in presets:
            if isinstance(item, dict):
                label_text = str(item.get("label") or "").strip()
                if not label_text:
                    continue
                self._preset_combo.addItem(label_text, item)
                continue
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                label_text = str(item[0] or "").strip()
                value_text = str(item[1] or "").strip()
                if not label_text or not value_text:
                    continue
                self._preset_combo.addItem(label_text, {"label": label_text, "value": value_text})
        enabled = self._preset_combo.count() > 0
        if hasattr(self, "_form_layout") and hasattr(self._form_layout, "setRowVisible"):
            try:
                self._form_layout.setRowVisible(self._preset_widget, enabled)
            except Exception:
                self._preset_widget.setVisible(enabled)
        else:
            self._preset_widget.setVisible(enabled)
            if hasattr(self, "_form_layout"):
                try:
                    row_label = self._form_layout.labelForField(self._preset_widget)
                    if row_label:
                        row_label.setVisible(enabled)
                except Exception:
                    pass
        self._preset_combo.setEnabled(enabled)
        self._preset_insert_btn.setEnabled(enabled)

    def _on_insert_preset(self) -> None:
        type_key = self._type_combo.currentData()
        preset_data = self._preset_combo.currentData()
        if not isinstance(preset_data, dict):
            preset_data = {}

        if type_key == "random":
            config = preset_data.get("config")
            if isinstance(config, dict):
                self._apply_random_config(config, None)
            return

        snippet = str(preset_data.get("value") or "")
        if not snippet.strip():
            snippet = str(self._preset_combo.currentText() or "")
        if not snippet.strip():
            return

        target_editor = self._expr_edit if type_key == "expression" else self._value_edit
        target_editor.setPlainText(snippet)
        target_editor.setFocus()

    def _on_type_changed(self, index: int) -> None:
        type_key = self._type_combo.itemData(index)
        self._refresh_presets(type_key)
        if type_key == "null":
            self._value_edit.setVisible(True)
            self._value_edit.setReadOnly(True)
            self._value_edit.setPlainText("")
            self._value_label.setVisible(True)
            self._expr_container.setVisible(False)
            self._expr_label.setVisible(False)
            self._random_container.setVisible(False)
            self._random_label.setVisible(False)
            return
        if type_key == "expression":
            self._value_edit.setReadOnly(True)
            self._value_edit.setPlainText("")
            self._value_edit.setVisible(False)
            self._expr_container.setVisible(True)
            self._expr_label.setVisible(True)
            self._random_container.setVisible(False)
            self._random_label.setVisible(False)
            self._value_label.setVisible(False)
            return
        if type_key == "random":
            self._value_edit.setReadOnly(True)
            self._value_edit.setPlainText("")
            self._value_edit.setVisible(False)
            self._expr_container.setVisible(False)
            self._expr_label.setVisible(False)
            self._random_container.setVisible(True)
            self._random_label.setVisible(True)
            self._value_label.setVisible(False)
            self._refresh_random_preview()
            return
        self._value_edit.setVisible(True)
        self._value_label.setVisible(True)
        self._expr_container.setVisible(False)
        self._expr_label.setVisible(False)
        self._random_container.setVisible(False)
        self._random_label.setVisible(False)
        self._value_edit.setReadOnly(False)

    def _parse_bool(self, text: str) -> Optional[bool]:
        raw = text.strip().lower()
        if raw in ("true", "1", "yes", "y", "on", "是", "真"):
            return True
        if raw in ("false", "0", "no", "n", "off", "否", "假"):
            return False
        return None

    def _parse_value(self, type_key: str, raw_text: str) -> Any:
        if type_key == "null":
            return None
        if type_key == "string":
            return raw_text
        if type_key == "int":
            if not raw_text:
                raise ValueError("整数类型不能为空")
            return int(float(raw_text))
        if type_key == "float":
            if not raw_text:
                raise ValueError("浮点类型不能为空")
            return float(raw_text)
        if type_key == "bool":
            parsed = self._parse_bool(raw_text)
            if parsed is None:
                raise ValueError("布尔类型格式不正确")
            return parsed
        if type_key == "list":
            if not raw_text:
                return []
            parsed = json.loads(raw_text)
            if not isinstance(parsed, list):
                raise ValueError("列表类型需要 JSON 数组")
            return parsed
        if type_key == "dict":
            if not raw_text:
                return {}
            parsed = json.loads(raw_text)
            if not isinstance(parsed, dict):
                raise ValueError("字典类型需要 JSON 对象")
            return parsed
        return raw_text

    def _parse_expr_initial(self) -> Any:
        raw = self._expr_initial_edit.text().strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return raw

    def _parse_expr_config(self) -> Dict[str, Any]:
        expr = self._expr_edit.toPlainText().strip()
        if not expr:
            raise ValueError("表达式不能为空")
        refresh = self._expr_refresh_combo.currentData()
        initial = self._parse_expr_initial()
        return {
            "expr": expr,
            "refresh": refresh,
            "initial": initial,
        }

    def _parse_random_config(self) -> Dict[str, Any]:
        mode = self._random_mode_combo.currentData()
        refresh = self._random_refresh_combo.currentData()
        try:
            min_value = float(self._random_min_edit.text().strip())
        except (TypeError, ValueError):
            raise ValueError("随机数最小值格式不正确")
        try:
            max_value = float(self._random_max_edit.text().strip())
        except (TypeError, ValueError):
            raise ValueError("随机数最大值格式不正确")
        if max_value < min_value:
            raise ValueError("随机数最大值不能小于最小值")
        try:
            precision = int(self._random_precision_edit.text().strip() or _RANDOM_DEFAULTS["precision"])
        except (TypeError, ValueError):
            raise ValueError("精度格式不正确")
        precision = max(0, min(6, precision))
        return {
            "mode": mode,
            "min": min_value,
            "max": max_value,
            "precision": precision,
            "refresh": refresh,
        }

    def _refresh_random_preview(self) -> None:
        try:
            config = self._parse_random_config()
        except Exception:
            return
        min_value = config["min"]
        max_value = config["max"]
        if config["mode"] == "int":
            value = random.randint(int(min_value), int(max_value))
        else:
            value = round(random.uniform(min_value, max_value), config["precision"])
        self._random_preview_label.setText(str(value))

    def accept(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.information(self, "提示", "变量名不能为空")
            return
        type_key = self._type_combo.currentData()
        if type_key == "expression":
            try:
                value = self._parse_expr_config()
            except Exception as exc:
                QMessageBox.information(self, "提示", str(exc))
                return
        elif type_key == "random":
            try:
                value = self._parse_random_config()
            except Exception as exc:
                QMessageBox.information(self, "提示", str(exc))
                return
        else:
            try:
                value = self._parse_value(type_key, self._value_edit.toPlainText().strip())
            except Exception as exc:
                QMessageBox.information(self, "提示", str(exc))
                return
        self._result_name = name
        self._result_type = type_key
        self._result_value = value
        super().accept()

    def get_result(self) -> Tuple[str, str, Any]:
        return self._result_name, self._result_type, self._result_value


class VariablePoolDialog(QDialog):
    def __init__(self, parent=None, parameter_panel=None, workflow_task_id: Optional[int] = None):
        super().__init__(parent)
        self.setWindowTitle("变量池管理")
        self.setMinimumSize(900, 480)
        self.resize(960, 520)

        self._workflow_task_id = workflow_task_id
        self._context = get_workflow_context()
        self._parameter_panel = parameter_panel
        self._scope_mode = "workflow"
        self._global_store = None
        self._global_entries: Dict[str, Any] = {}
        self._scope_combo = None
        self._global_status_label = None
        self._import_btn = None
        self._import_route_btn = None
        self._lock_btn = None
        self._remember_unlock_checkbox = None
        self._add_btn = None
        self._edit_btn = None
        self._current_group_key = "__all__"
        self._all_vars = {}
        self._group_map = {}
        self._allow_overwrite_checkbox = None
        self._workflow_runtime_task_key = ""
        self._table_render_ticket = 0
        self._table_render_batch_size = 180

        self._build_ui()
        self._apply_styles()

        self._refresh_btn.clicked.connect(self._refresh_table)
        self._delete_btn.clicked.connect(self._delete_selected)
        self._clear_btn.clicked.connect(self._clear_all)
        self._close_btn.clicked.connect(self.accept)
        if self._add_btn:
            self._add_btn.clicked.connect(self._on_add_variable)
        if self._edit_btn:
            self._edit_btn.clicked.connect(self._on_edit_variable)
        if self._import_btn:
            self._import_btn.clicked.connect(self._on_import_global_txt)
        if self._import_route_btn:
            self._import_route_btn.clicked.connect(self._on_import_route)
        if self._lock_btn:
            self._lock_btn.clicked.connect(self._on_toggle_global_lock)
        if self._remember_unlock_checkbox:
            self._remember_unlock_checkbox.toggled.connect(self._on_remember_unlock_changed)

        self._update_scope_ui()
        self._sync_workflow_context()
        self._refresh_table()

    def _get_active_workflow_task_id(self) -> Optional[int]:
        main_window = self._get_main_window()
        candidates: List[int] = []
        visited_ids = set()

        def _append_candidate(task_id: Optional[int]) -> None:
            if task_id is None:
                return
            try:
                task_id = int(task_id)
            except (TypeError, ValueError):
                return
            if task_id in visited_ids:
                return
            visited_ids.add(task_id)
            candidates.append(task_id)

        def _has_context_vars(task_id: int) -> bool:
            context = get_context_for_task(task_id)
            if not context:
                return False
            try:
                lock = getattr(context, "global_vars_lock", None)
                if lock and callable(getattr(lock, "acquire", None)) and callable(getattr(lock, "release", None)):
                    with lock:
                        if bool(getattr(context, "global_vars", {}) or {}):
                            return True
                        manifest = getattr(context, "runtime_vars_manifest", None)
                else:
                    if bool(getattr(context, "global_vars", {}) or {}):
                        return True
                    manifest = getattr(context, "runtime_vars_manifest", None)

                if isinstance(manifest, dict):
                    try:
                        return int(manifest.get("count") or 0) > 0
                    except Exception:
                        return True
                return False
            except Exception:
                try:
                    state = context.snapshot_variable_state()
                except Exception:
                    return False
                global_vars = (state or {}).get("global_vars")
                if isinstance(global_vars, dict) and global_vars:
                    return True
                manifest = (state or {}).get("runtime_vars_manifest")
                if isinstance(manifest, dict):
                    try:
                        return int(manifest.get("count") or 0) > 0
                    except Exception:
                        return True
                return False

        if main_window:
            _append_candidate(getattr(main_window, "_active_execution_task_id", None))
            _append_candidate(getattr(main_window, "_last_finished_task_id", None))
        _append_candidate(self._workflow_task_id)

        if main_window and hasattr(main_window, "workflow_tab_widget") and main_window.workflow_tab_widget:
            try:
                _append_candidate(main_window.workflow_tab_widget.get_current_task_id())
            except Exception:
                pass

            try:
                current_view = main_window.workflow_tab_widget.get_current_workflow_view()
                if current_view is not None:
                    for mapped_task_id, view in main_window.workflow_tab_widget.task_views.items():
                        if view == current_view:
                            _append_candidate(mapped_task_id)
                            break
            except Exception:
                pass

        for task_id in candidates:
            if _has_context_vars(task_id):
                return task_id
        if candidates:
            return candidates[0]

        if main_window and hasattr(main_window, "task_manager") and main_window.task_manager:
            try:
                tasks = main_window.task_manager.get_all_tasks()
            except Exception:
                tasks = []
            for task in tasks:
                task_id = getattr(task, "task_id", None)
                if task_id is None:
                    continue
                context = get_context_for_task(task_id)
                if not context:
                    continue
                if _has_context_vars(task_id):
                    return task_id
        return None

    def _sync_workflow_context(self) -> None:
        if self._is_global_mode():
            return
        task_id = self._get_active_workflow_task_id()
        if task_id is None:
            self._context = get_workflow_context()
            return
        context = get_context_for_task(task_id)
        if context:
            try:
                lock = getattr(context, "global_vars_lock", None)
                if lock and callable(getattr(lock, "acquire", None)) and callable(getattr(lock, "release", None)):
                    with lock:
                        has_vars = bool(getattr(context, "global_vars", {}) or {})
                        manifest = getattr(context, "runtime_vars_manifest", None)
                else:
                    has_vars = bool(getattr(context, "global_vars", {}) or {})
                    manifest = getattr(context, "runtime_vars_manifest", None)
                if not has_vars and isinstance(manifest, dict):
                    try:
                        has_vars = int(manifest.get("count") or 0) > 0
                    except Exception:
                        has_vars = True
            except Exception:
                has_vars = False

            if not has_vars:
                main_window = self._get_main_window()
                task_manager = getattr(main_window, "task_manager", None) if main_window else None
                if task_manager:
                    try:
                        task = task_manager.get_task(task_id)
                    except Exception:
                        task = None
                    if task and isinstance(getattr(task, "workflow_data", None), dict):
                        variables_data = task.workflow_data.get("variables")
                        if isinstance(variables_data, dict):
                            try:
                                update_context_from_variables(task_id, variables_data)
                                context = get_context_for_task(task_id) or context
                            except Exception:
                                pass
        if context:
            self._context = context

    def _build_ui(self) -> None:
        title = QLabel("")
        title.setObjectName("variable_pool_title")
        title.setVisible(False)
        title_layout = QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        title_layout.addWidget(title)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addLayout(title_layout)
        header_layout.addStretch()

        scope_layout = QHBoxLayout()
        scope_layout.setContentsMargins(0, 0, 0, 0)
        scope_layout.setSpacing(8)
        scope_label = QLabel("变量范围")
        self._scope_combo = QComboBox()
        self._scope_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._scope_combo.setMinimumContentsLength(8)
        self._scope_combo.setMinimumWidth(140)
        self._scope_combo.setMaximumWidth(180)
        self._scope_combo.addItem("工作流变量", "workflow")
        self._scope_combo.addItem("全局变量", "global")
        self._scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        self._global_status_label = QLabel("")
        self._global_status_label.setObjectName("variable_pool_global_status")
        scope_layout.addWidget(scope_label)
        scope_layout.addWidget(self._scope_combo)
        scope_layout.addStretch()
        scope_layout.addWidget(self._global_status_label)

        self._table = QTableWidget(0, 3)
        self._table.setObjectName("variable_pool_table")
        self._table.setHorizontalHeaderLabels(["变量名", "类型", "值"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setFrameShape(QFrame.Shape.NoFrame)
        header = self._table.horizontalHeader()
        header.setFixedHeight(32)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setHighlightSections(False)
        header.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 260)
        self._table.setColumnWidth(1, 100)
        header.setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(34)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setWordWrap(False)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_table_context_menu)

        table_layout = QVBoxLayout()
        table_layout.setContentsMargins(1, 1, 1, 1)
        table_layout.setSpacing(0)
        table_layout.addWidget(self._table)

        self._table_frame = QFrame()
        self._table_frame.setObjectName("variable_pool_frame")
        self._table_frame.setProperty("tableCard", "true")
        self._table_frame.setLayout(table_layout)

        self._group_list = QListWidget()
        self._group_list.setObjectName("variable_pool_groups")
        self._group_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._group_list.setMinimumWidth(160)
        self._group_list.currentItemChanged.connect(self._on_group_changed)

        group_layout = QVBoxLayout()
        group_layout.setContentsMargins(8, 8, 8, 8)
        group_layout.addWidget(self._group_list)

        self._group_frame = QFrame()
        self._group_frame.setObjectName("variable_pool_group_frame")
        self._group_frame.setLayout(group_layout)

        buttons_layout = QHBoxLayout()
        self._init_allow_overwrite_checkbox()
        if self._allow_overwrite_checkbox:
            buttons_layout.addWidget(self._allow_overwrite_checkbox)

        self._import_btn = QPushButton("导入TXT")
        self._import_route_btn = QPushButton("导入路线")
        self._lock_btn = QPushButton("解锁")
        self._remember_unlock_checkbox = QCheckBox("记住解锁状态")
        self._remember_unlock_checkbox.setToolTip("启用后会保存解锁口令，下次自动解锁")

        self._add_btn = QPushButton("新增变量")
        self._edit_btn = QPushButton("编辑变量")
        self._refresh_btn = QPushButton("刷新")
        self._delete_btn = QPushButton("删除选中")
        self._clear_btn = QPushButton("清空全部")
        self._close_btn = QPushButton("关闭")
        self._close_btn.setProperty("primary", True)

        buttons_layout.addWidget(self._import_btn)
        buttons_layout.addWidget(self._import_route_btn)
        buttons_layout.addWidget(self._lock_btn)
        buttons_layout.addWidget(self._remember_unlock_checkbox)
        buttons_layout.addWidget(self._add_btn)
        buttons_layout.addWidget(self._edit_btn)
        buttons_layout.addWidget(self._refresh_btn)
        buttons_layout.addWidget(self._delete_btn)
        buttons_layout.addWidget(self._clear_btn)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self._close_btn)

        self._count_label = QLabel("")
        self._count_label.setObjectName("variable_pool_count")

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        content_layout.addWidget(self._group_frame)
        content_layout.addWidget(self._table_frame, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(header_layout)
        layout.addLayout(scope_layout)
        layout.addWidget(self._count_label)
        layout.addLayout(content_layout)
        layout.addLayout(buttons_layout)

    def _apply_styles(self) -> None:
        theme_manager = get_theme_manager()
        background = theme_manager.get_color("background")
        card = theme_manager.get_color("card")
        border = theme_manager.get_color("border")
        text = theme_manager.get_color("text")
        text_secondary = theme_manager.get_color("text_secondary")
        selected = theme_manager.get_color("selected")

        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {background};
                color: {text};
            }}

            #variable_pool_title {{
                font-size: 14px;
                font-weight: 600;
            }}

            #variable_pool_subtitle,
            #variable_pool_count,
            #variable_pool_global_status {{
                color: {text_secondary};
            }}

            #variable_pool_group_frame {{
                background-color: {card};
                border: 1px solid {border};
                border-radius: 12px;
            }}

            #variable_pool_groups {{
                background-color: {card};
                border: none;
            }}

            #variable_pool_groups::item {{
                padding: 6px 8px;
                border-radius: 6px;
            }}

            #variable_pool_groups::item:selected {{
                background-color: {selected};
                color: #ffffff;
            }}

            QPushButton {{
                min-height: 28px;
            }}

            QDialog QPushButton[primary="true"]:hover {{
                background-color: {selected};
                color: #ffffff;
            }}
            """
        )

    def _is_global_mode(self) -> bool:
        return self._scope_mode == "global"

    def _ensure_global_store(self):
        if self._global_store:
            return self._global_store
        try:
            store = ensure_global_context_loaded()
            self._global_store = store
            return store
        except Exception as exc:
            logger.debug("读取全局变量失败: %s", exc)
            return None

    def _read_global_variables_snapshot(self, store=None) -> Dict[str, Any]:
        store_obj = store or self._ensure_global_store()
        if not store_obj:
            return {}
        try:
            lock = getattr(store_obj, "_lock", None)
            if lock and callable(getattr(lock, "acquire", None)) and callable(getattr(lock, "release", None)):
                with lock:
                    raw = store_obj.data.get("variables", {})
                    return dict(raw) if isinstance(raw, dict) else {}
            raw = getattr(store_obj, "data", {}).get("variables", {})
            return dict(raw) if isinstance(raw, dict) else {}
        except Exception as exc:
            logger.debug("读取全局变量快照失败: %s", exc)
            return {}

    def _apply_global_store(self) -> None:
        store = self._ensure_global_store()
        if not store:
            return
        try:
            context = get_workflow_context("global")
            store.apply_to_context(context)
        except Exception as exc:
            logger.debug("更新全局上下文失败: %s", exc)

    def _refresh_after_global_store_mutation(self) -> None:
        self._apply_global_store()
        self._refresh_table_internal(sync_global_store=False)

    def _refresh_global_status(self) -> None:
        if not self._global_status_label or not self._lock_btn:
            return
        store = self._ensure_global_store()
        if not store:
            self._global_status_label.setText("全局变量不可用")
            self._lock_btn.setEnabled(False)
            self._lock_btn.setText("解锁")
            if self._remember_unlock_checkbox:
                self._remember_unlock_checkbox.blockSignals(True)
                self._remember_unlock_checkbox.setChecked(False)
                self._remember_unlock_checkbox.setEnabled(False)
                self._remember_unlock_checkbox.blockSignals(False)
            return
        if not store.has_encrypted():
            self._global_status_label.setText("未启用加密")
            self._lock_btn.setEnabled(False)
            self._lock_btn.setText("解锁")
            if self._remember_unlock_checkbox:
                self._remember_unlock_checkbox.blockSignals(True)
                self._remember_unlock_checkbox.setChecked(False)
                self._remember_unlock_checkbox.setEnabled(False)
                self._remember_unlock_checkbox.blockSignals(False)
            return
        locked = store.is_locked()
        self._global_status_label.setText("已锁定" if locked else "已解锁")
        self._lock_btn.setEnabled(True)
        self._lock_btn.setText("解锁" if locked else "锁定")
        if self._remember_unlock_checkbox:
            remember = store.remember_unlock_enabled()
            self._remember_unlock_checkbox.blockSignals(True)
            self._remember_unlock_checkbox.setChecked(remember)
            self._remember_unlock_checkbox.setEnabled(True)
            self._remember_unlock_checkbox.blockSignals(False)

    def _update_scope_ui(self) -> None:
        is_global = self._is_global_mode()
        if self._allow_overwrite_checkbox:
            self._allow_overwrite_checkbox.setVisible(not is_global)
        if self._import_btn:
            self._import_btn.setVisible(is_global)
        if self._import_route_btn:
            self._import_route_btn.setVisible(is_global)
        if self._lock_btn:
            self._lock_btn.setVisible(is_global)
        if self._remember_unlock_checkbox:
            self._remember_unlock_checkbox.setVisible(is_global)
        if self._add_btn:
            self._add_btn.setVisible(is_global)
        if self._edit_btn:
            self._edit_btn.setVisible(is_global)
        if self._global_status_label:
            self._global_status_label.setVisible(is_global)
        if self._group_frame:
            self._group_frame.setVisible(not is_global)
        if is_global:
            self._refresh_global_status()

    def _on_scope_changed(self, index: int) -> None:
        if not self._scope_combo:
            return
        self._scope_mode = self._scope_combo.itemData(index) or "workflow"
        if self._is_global_mode():
            self._ensure_global_store()
        self._update_scope_ui()
        self._refresh_table()

    def _init_allow_overwrite_checkbox(self) -> None:
        if not self._parameter_panel:
            return

        param_def = self._parameter_panel.param_definitions.get("allow_overwrite", {})
        default_value = param_def.get("default", True)
        current_value = None
        if hasattr(self._parameter_panel, "_get_real_time_card_parameters"):
            try:
                real_params = self._parameter_panel._get_real_time_card_parameters()
                current_value = real_params.get("allow_overwrite", None)
            except Exception as exc:
                logger.debug("读取实时参数失败: %s", exc)
        if current_value is None:
            current_value = self._parameter_panel.current_parameters.get("allow_overwrite", default_value)

        checkbox = QCheckBox("允许覆盖变量")
        checkbox.setChecked(bool(current_value))
        try:
            self._context.allow_overwrite = bool(current_value)
        except Exception:
            pass
        tooltip = param_def.get("tooltip", "")
        if tooltip:
            checkbox.setToolTip(tooltip)
            checkbox.setToolTipDuration(10000)
        checkbox.toggled.connect(self._on_allow_overwrite_changed)
        self._allow_overwrite_checkbox = checkbox

    def _on_allow_overwrite_changed(self, checked: bool) -> None:
        if not self._parameter_panel:
            return
        self._parameter_panel.current_parameters["allow_overwrite"] = bool(checked)
        try:
            self._context.allow_overwrite = bool(checked)
        except Exception:
            pass
        widget = self._parameter_panel.widgets.get("allow_overwrite")
        if isinstance(widget, QCheckBox):
            widget.blockSignals(True)
            widget.setChecked(bool(checked))
            widget.blockSignals(False)
        if self._parameter_panel.current_card_id is not None:
            try:
                self._parameter_panel.parameters_changed.emit(
                    self._parameter_panel.current_card_id,
                    {"allow_overwrite": bool(checked)},
                )
            except Exception as exc:
                logger.debug("同步允许覆盖变量失败: %s", exc)

    def _is_system_var(self, name: str) -> bool:
        if not name:
            return False
        for prefix in SYSTEM_VAR_PREFIXES:
            if name.startswith(prefix):
                return True
        return False

    @staticmethod
    def _is_runtime_unloaded_value(value: Any) -> bool:
        # WorkflowContext 使用 object() 作为运行变量未加载占位符。
        return value is not None and value.__class__ is object

    def _load_workflow_values_batch(self, names: List[str]) -> None:
        task_key = str(self._workflow_runtime_task_key or "").strip()
        if not task_key or not names:
            return

        pending: List[str] = []
        name_map: Dict[str, Any] = {}
        for name in names:
            value = self._all_vars.get(name)
            if self._is_runtime_unloaded_value(value):
                name_text = str(name)
                pending.append(name_text)
                name_map[name_text] = name
        if not pending:
            return

        try:
            from task_workflow.runtime_var_store import get_runtime_vars

            loaded_pairs = get_runtime_vars(task_key, pending)
        except Exception as exc:
            logger.debug("批量加载运行变量失败: %s", exc)
            return
        if not isinstance(loaded_pairs, dict):
            return
        for name, pair in (loaded_pairs or {}).items():
            if not isinstance(pair, tuple) or len(pair) < 1:
                continue
            key = name_map.get(str(name), name)
            self._all_vars[key] = pair[0]

    def _build_group_map(self) -> None:
        if self._is_global_mode():
            self._build_global_map()
            return
        try:
            lock = getattr(self._context, "global_vars_lock", None)
            if lock and callable(getattr(lock, "acquire", None)) and callable(getattr(lock, "release", None)):
                with lock:
                    raw_vars = dict(getattr(self._context, "global_vars", {}) or {})
                    source_map = dict(getattr(self._context, "var_sources", {}) or {})
                    runtime_task_key = str(getattr(self._context, "runtime_vars_task_key", "") or "").strip()
            else:
                raw_vars = dict(getattr(self._context, "global_vars", {}) or {})
                source_map = dict(getattr(self._context, "var_sources", {}) or {})
                runtime_task_key = str(getattr(self._context, "runtime_vars_task_key", "") or "").strip()
        except Exception as exc:
            logger.debug("读取变量池失败: %s", exc)
            raw_vars = {}
            source_map = {}
            runtime_task_key = ""
        if runtime_task_key:
            try:
                from task_workflow.runtime_var_store import list_runtime_var_sources

                db_sources = list_runtime_var_sources(runtime_task_key) or {}
                for raw_name, source in db_sources.items():
                    name = str(raw_name or "").strip()
                    if not name:
                        continue
                    if name not in raw_vars:
                        raw_vars[name] = object()
                    if name not in source_map and source is not None:
                        source_map[name] = source
            except Exception as exc:
                logger.debug("合并 SQLite 变量索引失败: %s", exc)
        group_map: dict = {}

        display_names = [name for name in raw_vars.keys() if not self._is_system_var(name)]

        for name in list(display_names):
            if name not in source_map:
                group_map.setdefault(None, []).append(name)
                continue

            card_id = source_map.get(name)
            if isinstance(card_id, int) and not isinstance(card_id, bool):
                group_map.setdefault(card_id, []).append(name)
                continue

            try:
                parsed_card_id = int(card_id)
                group_map.setdefault(parsed_card_id, []).append(name)
            except (TypeError, ValueError):
                group_map.setdefault(None, []).append(name)

        for names in group_map.values():
            names.sort(key=lambda value: str(value))

        self._workflow_runtime_task_key = runtime_task_key
        display_vars = {name: raw_vars.get(name) for name in display_names}
        self._all_vars = display_vars
        self._group_map = group_map

    def _build_global_map(self) -> None:
        store = self._ensure_global_store()
        entries: Dict[str, Any] = {}
        display_vars: Dict[str, Any] = {}
        if store:
            variables = self._read_global_variables_snapshot(store)
            for name, entry in variables.items():
                if not isinstance(entry, dict):
                    continue
                name_text = str(name)
                entries[name_text] = entry
                display_vars[name_text] = self._get_global_value(name_text, entry)
        self._global_entries = entries
        self._all_vars = display_vars
        self._group_map = {}

    def _get_global_value(self, name: str, entry: Optional[Dict[str, Any]] = None) -> Any:
        store = self._global_store
        if not store:
            return None
        if entry is None:
            entry = self._global_entries.get(name)
        if not isinstance(entry, dict):
            return None
        if "enc" in entry:
            if store.is_locked():
                return None
            return store.get_value(name)
        return entry.get("value")

    def _format_global_type(self, entry: Dict[str, Any], value: Any) -> str:
        if "enc" in entry and self._global_store and self._global_store.is_locked():
            return "加密"
        if entry.get("type") == "secret" or entry.get("secret"):
            return "字符串"
        if entry.get("type") == "random":
            return "随机数"
        if entry.get("type") == "expression":
            return "表达式"
        if value is None:
            return _TYPE_LABELS[type(None)]
        return _format_type(value)

    def _format_global_value(self, name: str, entry: Dict[str, Any], value: Any) -> str:
        if "enc" in entry and self._global_store and self._global_store.is_locked():
            return "已加密"
        return _format_value(value, var_name=name)

    def _add_group_item(self, label: str, key: object, count: int) -> None:
        item = QListWidgetItem(f"{label} ({count})")
        item.setData(Qt.ItemDataRole.UserRole, key)
        self._group_list.addItem(item)

    def _get_main_window(self):
        if self._parameter_panel:
            main_window = getattr(self._parameter_panel, "main_window", None)
            if main_window:
                return main_window
        parent = self.parent()
        while parent:
            if hasattr(parent, "workflow_tab_widget") or hasattr(parent, "workflow_view"):
                return parent
            parent = parent.parent()
        return None

    def _get_card_display_name(self, card_id: int) -> str:
        if card_id is None:
            return ""
        try:
            main_window = self._get_main_window()
            workflow_view = None
            if main_window and hasattr(main_window, "workflow_tab_widget") and main_window.workflow_tab_widget:
                current_task_id = main_window.workflow_tab_widget.get_current_task_id()
                if current_task_id is not None and current_task_id in main_window.workflow_tab_widget.task_views:
                    workflow_view = main_window.workflow_tab_widget.task_views[current_task_id]
                if workflow_view is None:
                    for view in main_window.workflow_tab_widget.task_views.values():
                        if hasattr(view, "cards") and card_id in view.cards:
                            workflow_view = view
                            break
            if workflow_view is None and main_window and hasattr(main_window, "workflow_view"):
                workflow_view = main_window.workflow_view
            if workflow_view and hasattr(workflow_view, "cards"):
                card = workflow_view.cards.get(card_id)
                if card:
                    custom_name = getattr(card, "custom_name", None)
                    if custom_name:
                        return str(custom_name)
                    task_type = getattr(card, "task_type", None)
                    if task_type:
                        return str(task_type)
        except Exception:
            pass

        if self._parameter_panel:
            info = getattr(self._parameter_panel, "workflow_cards_info", {}) or {}
            for _, (task_type, info_card_id) in info.items():
                if info_card_id == card_id and task_type:
                    return str(task_type)
        return ""

    def _refresh_group_list(self) -> object:
        total = len(self._all_vars)
        self._group_list.blockSignals(True)
        try:
            self._group_list.clear()

            self._add_group_item("全部", "__all__", total)

            target_group_key = "__all__" if self._is_global_mode() else (self._current_group_key or "__all__")

            if not self._is_global_mode():
                for card_id in sorted(k for k in self._group_map.keys() if isinstance(k, int)):
                    card_name = self._get_card_display_name(card_id)
                    if card_name:
                        label = f"卡片 {card_id} {card_name}"
                    else:
                        label = f"卡片 {card_id}"
                    self._add_group_item(label, card_id, len(self._group_map[card_id]))

            return self._select_group(target_group_key)
        finally:
            self._group_list.blockSignals(False)

    def _select_group(self, key: object) -> object:
        for index in range(self._group_list.count()):
            item = self._group_list.item(index)
            if item and item.data(Qt.ItemDataRole.UserRole) == key:
                self._group_list.setCurrentRow(index)
                return key
        if self._group_list.count() > 0:
            self._group_list.setCurrentRow(0)
            item = self._group_list.item(0)
            if item:
                return item.data(Qt.ItemDataRole.UserRole)
        return None

    def _cancel_table_render(self) -> None:
        self._table_render_ticket += 1

    def _is_table_available(self) -> bool:
        table = getattr(self, "_table", None)
        if table is None:
            return False
        try:
            table.rowCount()
        except RuntimeError:
            return False
        return True

    def _prepare_table_render(self, label_text: str, row_count: int) -> int:
        self._cancel_table_render()
        ticket = self._table_render_ticket
        self._count_label.setText(label_text)
        if not self._is_table_available():
            return ticket
        self._table.clearContents()
        self._table.setRowCount(max(0, int(row_count)))
        return ticket

    def _set_table_row_items(self, row: int, name: str, type_text: str, value_text: str) -> bool:
        if not self._is_table_available():
            self._cancel_table_render()
            return False

        name_item = QTableWidgetItem(str(name))
        type_item = QTableWidgetItem(type_text)
        value_item = QTableWidgetItem(value_text)

        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        try:
            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, type_item)
            self._table.setItem(row, 2, value_item)
        except RuntimeError:
            self._cancel_table_render()
            return False
        return True

    def _render_global_rows_chunk(self, ticket: int, names: List[str], start: int) -> None:
        if ticket != self._table_render_ticket or not self._is_table_available():
            return
        end = min(start + self._table_render_batch_size, len(names))
        for row in range(start, end):
            name = names[row]
            entry = self._global_entries.get(name, {})
            if not isinstance(entry, dict):
                entry = {}
            value = self._get_global_value(name, entry)
            type_text = self._format_global_type(entry, value)
            value_text = self._format_global_value(name, entry, value)
            if not self._set_table_row_items(row, str(name), type_text, value_text):
                return

        if end < len(names) and ticket == self._table_render_ticket and self._is_table_available():
            QTimer.singleShot(
                0,
                lambda t=ticket, n=names, s=end: self._render_global_rows_chunk(t, n, s),
            )

    def _render_workflow_rows_chunk(self, ticket: int, names: List[str], start: int) -> None:
        if ticket != self._table_render_ticket or not self._is_table_available():
            return
        end = min(start + self._table_render_batch_size, len(names))
        batch_names = names[start:end]
        self._load_workflow_values_batch(batch_names)
        for row, name in enumerate(batch_names, start):
            value = self._all_vars.get(name)
            if not self._set_table_row_items(
                row,
                str(name),
                _format_type(value),
                _format_value(value, var_name=name),
            ):
                return

        if end < len(names) and ticket == self._table_render_ticket and self._is_table_available():
            QTimer.singleShot(
                0,
                lambda t=ticket, n=names, s=end: self._render_workflow_rows_chunk(t, n, s),
            )

    def _render_table_for_group(self, group_key: object) -> None:
        if self._is_global_mode():
            names = sorted(self._all_vars.keys(), key=lambda value: str(value))
            label_text = f"共 {len(names)} 个全局变量"
            ticket = self._prepare_table_render(label_text, len(names))
            self._render_global_rows_chunk(ticket, names, 0)
            return

        if group_key == "__all__":
            names = sorted(self._all_vars.keys(), key=lambda value: str(value))
            label_text = f"共 {len(names)} 个变量"
        elif group_key is None:
            names = self._group_map.get(None, [])
            label_text = f"未归属 {len(names)} 个变量"
        else:
            names = self._group_map.get(group_key, [])
            card_name = self._get_card_display_name(group_key)
            if card_name:
                label_text = f"卡片 {group_key} {card_name}：{len(names)} 个变量"
            else:
                label_text = f"卡片 {group_key}：{len(names)} 个变量"

        ticket = self._prepare_table_render(label_text, len(names))
        self._render_workflow_rows_chunk(ticket, names, 0)

    def _refresh_table(self):
        self._refresh_table_internal(sync_global_store=True)

    def handle_runtime_variables_persisted(self, task_id: Optional[int]) -> None:
        if self._is_global_mode():
            return
        try:
            normalized_task_id = int(task_id)
        except (TypeError, ValueError):
            return
        self._workflow_task_id = normalized_task_id
        self._refresh_table_internal(sync_global_store=False)

    def done(self, result: int) -> None:
        self._cancel_table_render()
        super().done(result)

    def closeEvent(self, event) -> None:
        self._cancel_table_render()
        super().closeEvent(event)

    def _refresh_table_internal(self, *, sync_global_store: bool) -> None:
        self._cancel_table_render()
        self._sync_workflow_context()
        if self._is_global_mode():
            store = self._ensure_global_store()
            if store and sync_global_store:
                try:
                    store.load()
                except Exception:
                    pass
                self._apply_global_store()
            self._refresh_global_status()
        self._build_group_map()
        selected_group_key = self._refresh_group_list()
        render_group_key = "__all__" if selected_group_key is None else selected_group_key
        self._current_group_key = render_group_key
        self._render_table_for_group(render_group_key)

    def _on_group_changed(self, current: QListWidgetItem, previous: QListWidgetItem) -> None:
        if not current:
            return
        self._current_group_key = current.data(Qt.ItemDataRole.UserRole)
        self._render_table_for_group(self._current_group_key)

    def _on_table_context_menu(self, pos) -> None:
        item = self._table.itemAt(pos)
        if not item:
            return

        row = item.row()
        name_item = self._table.item(row, 0)
        type_item = self._table.item(row, 1)
        value_item = self._table.item(row, 2)

        var_name = name_item.text().strip() if name_item else ""
        var_type = type_item.text().strip() if type_item else ""
        var_value = value_item.text().strip() if value_item else ""
        value_for_copy: Optional[str] = var_value
        locked_value = False

        if self._is_global_mode() and var_name:
            entry = self._global_entries.get(var_name, {})
            if isinstance(entry, dict) and "enc" in entry:
                if self._global_store and self._global_store.is_locked():
                    locked_value = True
                value_for_copy = None if locked_value else self._get_global_value(var_name, entry)
            else:
                value_for_copy = self._get_global_value(var_name, entry)

        menu = apply_unified_menu_style(QMenu(self), frameless=True)
        copy_name = menu.addAction("复制变量名")
        copy_type = menu.addAction("复制类型")
        copy_value = menu.addAction("复制值")
        copy_name.setEnabled(bool(var_name))
        copy_type.setEnabled(bool(var_type))
        copy_value.setEnabled(value_for_copy is not None and not locked_value)
        chosen = menu.exec_(self._table.viewport().mapToGlobal(pos))
        if chosen == copy_name:
            QApplication.clipboard().setText(var_name)
        elif chosen == copy_type:
            QApplication.clipboard().setText(var_type)
        elif chosen == copy_value:
            if locked_value:
                show_information_box(self, "提示", "请先解锁全局变量")
                return
            if value_for_copy is None:
                return
            QApplication.clipboard().setText(str(value_for_copy))

    def _validate_global_name(self, name: str) -> bool:
        if not name:
            show_information_box(self, "提示", "变量名不能为空")
            return False
        if self._is_system_var(name):
            show_information_box(self, "提示", "系统变量不支持修改")
            return False
        return True

    def _save_global_entry(
        self,
        name: str,
        type_key: str,
        value: Any,
        *,
        old_name: Optional[str] = None,
        secret: bool = False,
    ) -> bool:
        store = self._ensure_global_store()
        if not store:
            show_information_box(self, "提示", "全局变量不可用")
            return False
        ok = store.set_value(name, value, var_type=type_key, secret=bool(secret))
        if not ok:
            show_information_box(self, "提示", "保存全局变量失败")
            return False
        if old_name and old_name != name:
            store.delete(old_name)
        try:
            store.save()
        except Exception as exc:
            show_information_box(self, "提示", f"写入全局变量失败: {exc}")
            return False
        self._refresh_after_global_store_mutation()
        return True

    def _on_add_variable(self) -> None:
        if not self._is_global_mode():
            return
        store = self._ensure_global_store()
        if not store:
            show_information_box(self, "提示", "全局变量不可用")
            return
        dialog = GlobalVariableEditDialog(self, title="新增全局变量")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, type_key, value = dialog.get_result()
        if not self._validate_global_name(name):
            return
        variables = self._read_global_variables_snapshot(store)
        if name in variables:
            reply = show_question_box(self, "覆盖确认", f"变量 '{name}' 已存在，是否覆盖？")
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._save_global_entry(name, type_key, value)

    def _on_edit_variable(self) -> None:
        if not self._is_global_mode():
            return
        names = self._selected_variable_names()
        if len(names) != 1:
            show_information_box(self, "提示", "请选择一个变量进行编辑")
            return
        name = names[0]
        entry = self._global_entries.get(name, {})
        if not isinstance(entry, dict):
            entry = {}
        if "enc" in entry:
            if self._global_store and self._global_store.is_locked():
                show_information_box(self, "提示", "请先解锁全局变量")
                return
            show_information_box(self, "提示", "加密变量暂不支持编辑")
            return
        value = self._get_global_value(name, entry)
        dialog = GlobalVariableEditDialog(
            self,
            title="编辑全局变量",
            name=name,
            value=value,
            type_key=entry.get("type"),
            random_config=entry.get("config"),
            expr_config=entry.get("config"),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_name, type_key, new_value = dialog.get_result()
        if not self._validate_global_name(new_name):
            return
        store = self._ensure_global_store()
        if not store:
            show_information_box(self, "提示", "全局变量不可用")
            return
        variables = self._read_global_variables_snapshot(store)
        if new_name != name and new_name in variables:
            reply = show_question_box(self, "覆盖确认", f"变量 '{new_name}' 已存在，是否覆盖？")
            if reply != QMessageBox.StandardButton.Yes:
                return
        secret = bool(entry.get("secret") or entry.get("type") == "secret")
        self._save_global_entry(new_name, type_key, new_value, old_name=name, secret=secret)

    def _selected_variable_names(self) -> List[str]:
        selection = self._table.selectionModel()
        if not selection:
            return []
        rows = {index.row() for index in selection.selectedRows()}
        names = []
        for row in sorted(rows):
            item = self._table.item(row, 0)
            if item:
                names.append(item.text())
        return names

    def _delete_selected(self):
        names = self._selected_variable_names()
        if not names:
            show_information_box(self, "提示", "请先选择要删除的变量")
            return

        if self._is_global_mode():
            store = self._ensure_global_store()
            if not store:
                show_information_box(self, "提示", "全局变量不可用")
                return
            reply = show_question_box(
                self,
                "删除确认",
                f"确定删除选中的 {len(names)} 个全局变量吗？",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            for name in names:
                store.delete(name)
            store.save()
            self._refresh_after_global_store_mutation()
            return

        reply = show_question_box(
            self,
            "删除确认",
            f"确定删除选中的 {len(names)} 个变量吗？",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        for name in names:
            self._context.remove_global_var(name)
        self._refresh_table()

    def _clear_all(self):
        if self._is_global_mode():
            store = self._ensure_global_store()
            if not store:
                show_information_box(self, "提示", "全局变量不可用")
                return
            if not self._read_global_variables_snapshot(store):
                show_information_box(self, "提示", "当前没有可清空的全局变量")
                return
            reply = show_question_box(self, "清空确认", "确定清空所有全局变量吗？")
            if reply != QMessageBox.StandardButton.Yes:
                return
            store.clear()
            store.save()
            self._refresh_after_global_store_mutation()
            return

        has_vars = False
        if hasattr(self._context, "snapshot_variable_state"):
            state = self._context.snapshot_variable_state()
            has_vars = bool((state or {}).get("global_vars", {}) or {})
        else:
            has_vars = bool(self._context.global_vars)
        if not has_vars:
            show_information_box(self, "提示", "当前没有可清空的变量")
            return

        reply = show_question_box(self, "清空确认", "确定清空所有全局变量吗？")
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._context.clear_global_vars()
        self._refresh_table()

    def _on_toggle_global_lock(self) -> None:
        if not self._is_global_mode():
            return
        store = self._ensure_global_store()
        if not store:
            show_information_box(self, "提示", "全局变量不可用")
            return
        if not store.has_encrypted():
            show_information_box(self, "提示", "当前没有加密变量")
            return
        if store.is_locked():
            passphrase, ok = QInputDialog.getText(self, "解锁全局变量", "请输入加密密码", QLineEdit.EchoMode.Password)
            if not ok:
                return
            if not passphrase:
                show_information_box(self, "提示", "密码不能为空")
                return
            if not store.unlock(passphrase):
                show_information_box(self, "解锁失败", "密码错误或无法解密")
                return
        else:
            store.lock()
        self._refresh_after_global_store_mutation()

    def _on_remember_unlock_changed(self, checked: bool) -> None:
        if not self._is_global_mode():
            return
        store = self._ensure_global_store()
        if not store:
            show_information_box(self, "提示", "全局变量不可用")
            return
        if not store.has_encrypted():
            show_information_box(self, "提示", "当前没有加密变量")
            return
        if not checked:
            store.set_remember_unlock(False)
            store.save()
            return
        passphrase = store.get_cached_passphrase() or store.get_remembered_passphrase()
        if store.is_locked() or not passphrase:
            passphrase, ok = QInputDialog.getText(self, "记住解锁状态", "请输入解锁密码", QLineEdit.EchoMode.Password)
            if not ok:
                if self._remember_unlock_checkbox:
                    self._remember_unlock_checkbox.blockSignals(True)
                    self._remember_unlock_checkbox.setChecked(False)
                    self._remember_unlock_checkbox.blockSignals(False)
                return
            if not passphrase:
                show_information_box(self, "提示", "密码不能为空")
                if self._remember_unlock_checkbox:
                    self._remember_unlock_checkbox.blockSignals(True)
                    self._remember_unlock_checkbox.setChecked(False)
                    self._remember_unlock_checkbox.blockSignals(False)
                return
            if store.is_locked() and not store.unlock(passphrase):
                show_information_box(self, "解锁失败", "密码错误或无法解密")
                if self._remember_unlock_checkbox:
                    self._remember_unlock_checkbox.blockSignals(True)
                    self._remember_unlock_checkbox.setChecked(False)
                    self._remember_unlock_checkbox.blockSignals(False)
                return
        if not store.set_remember_unlock(True, passphrase):
            show_information_box(self, "提示", "保存解锁状态失败")
            if self._remember_unlock_checkbox:
                self._remember_unlock_checkbox.blockSignals(True)
                self._remember_unlock_checkbox.setChecked(False)
                self._remember_unlock_checkbox.blockSignals(False)
            return
        store.save()
        self._refresh_after_global_store_mutation()

    def _on_import_global_txt(self) -> None:
        if not self._is_global_mode() and self._scope_combo:
            index = self._scope_combo.findData("global")
            if index >= 0:
                self._scope_combo.setCurrentIndex(index)
        dialog = GlobalVarImportDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        options = dialog.get_options()
        store = self._ensure_global_store()
        if not store:
            show_information_box(self, "提示", "全局变量不可用")
            return

        encrypt = bool(options.get("encrypt"))
        passphrase = options.get("passphrase") or ""
        if encrypt:
            try:
                from task_workflow.global_var_store import _crypto_available
            except Exception:
                _crypto_available = None
            if _crypto_available and not _crypto_available():
                show_information_box(self, "导入失败", "未安装加密依赖 cryptography")
                return
            if store.has_encrypted():
                if not store.unlock(passphrase):
                    show_information_box(self, "导入失败", "加密密码错误，无法解锁全局变量")
                    return

        path = Path(options["path"])
        try:
            content = _read_text_file(path, options.get("encoding", "自动"))
        except Exception as exc:
            show_information_box(self, "导入失败", f"读取文件失败：{exc}")
            return

        delimiter = options.get("delimiter") or "|"
        prefix = options.get("prefix") or ""
        mapping_tokens = _normalize_mapping_tokens(options.get("mapping", ""))
        skip_header = bool(options.get("skip_header"))

        entries: List[Tuple[str, Any, str, bool]] = []
        used_names: set = set()
        row_counter = 0

        def _unique_name(base_name: str) -> str:
            if base_name not in used_names:
                used_names.add(base_name)
                return base_name
            index = 2
            while f"{base_name}_{index}" in used_names:
                index += 1
            unique = f"{base_name}_{index}"
            used_names.add(unique)
            return unique

        lines = content.splitlines()
        for line_index, line in enumerate(lines):
            if skip_header and line_index == 0:
                continue
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            parts = [part.strip() for part in raw.split(delimiter)]
            if not any(parts):
                continue
            mapping = mapping_tokens or _auto_mapping(len(parts))
            if mapping_tokens and len(parts) <= 2:
                if mapping_tokens[:3] == ["name", "username", "password"]:
                    mapping = _auto_mapping(len(parts))
            if len(mapping) < len(parts):
                mapping = mapping + ["ignore"] * (len(parts) - len(mapping))

            fields: Dict[str, str] = {}
            custom_fields: Dict[str, str] = {}
            for idx, token in enumerate(mapping):
                if idx >= len(parts):
                    break
                if token == "ignore":
                    continue
                if parts[idx] == "":
                    continue
                if token in ("name", "username", "password", "tag", "value"):
                    fields[token] = parts[idx]
                else:
                    custom_fields[token] = parts[idx]

            if not fields:
                continue

            row_counter += 1
            has_name = bool(fields.get("name"))
            base_prefix = prefix.strip()

            def _indexed_name(label_text: str) -> str:
                label_clean = _sanitize_label(label_text)
                if base_prefix:
                    if base_prefix == label_clean:
                        return f"{base_prefix}{row_counter}"
                    return f"{base_prefix}.{label_clean}{row_counter}"
                return f"{label_clean}{row_counter}"

            if not has_name:
                for token in list(fields.keys()) + list(custom_fields.keys()):
                    if token == "name":
                        continue
                    value = fields.get(token)
                    if value is None:
                        value = custom_fields.get(token)
                    if value is None:
                        continue
                    field_label = _format_field_label(token)
                    name = _unique_name(_indexed_name(field_label))
                    secret = token == "password" or (encrypt and token == "username")
                    var_type = "secret" if secret else "text"
                    entries.append((name, value, var_type, secret))
                continue

            label = _sanitize_label(fields.get("name"))
            if not label:
                label = f"项{row_counter}"
            base_name = ".".join([text for text in [prefix, label] if text])
            if not base_name:
                continue

            if "value" in fields and fields.get("value") != "":
                name = _unique_name(base_name)
                entries.append((name, fields["value"], "text", False))

            for token, value in fields.items():
                if token in ("name", "value"):
                    continue
                if value == "":
                    continue
                field_label = _format_field_label(token)
                name = _unique_name(f"{base_name}.{field_label}")
                secret = token == "password" or (encrypt and token == "username")
                var_type = "secret" if secret else "text"
                entries.append((name, value, var_type, secret))

            for token, value in custom_fields.items():
                if value == "":
                    continue
                field_label = _format_field_label(token)
                name = _unique_name(f"{base_name}.{field_label}")
                entries.append((name, value, "text", False))

        if not entries:
            show_information_box(self, "导入失败", "没有可导入的有效内容")
            return

        existing = set()
        variables = self._read_global_variables_snapshot(store)
        existing = {str(name) for name in variables.keys()}

        skipped = 0
        duplicates = [name for name, _, _, _ in entries if name in existing]
        if duplicates:
            reply = show_question_box(
                self,
                "覆盖确认",
                f"检测到 {len(duplicates)} 个变量已存在，是否覆盖？",
            )
            if reply != QMessageBox.StandardButton.Yes:
                skipped = len(duplicates)
                entries = [entry for entry in entries if entry[0] not in existing]

        if not entries:
            show_information_box(self, "提示", "已取消覆盖，未导入任何变量")
            return

        added = 0
        failed = 0
        for name, value, var_type, secret in entries:
            ok = store.set_value(
                name,
                value,
                var_type=var_type,
                secret=secret,
                encrypt=encrypt and secret,
                passphrase=passphrase if encrypt and secret else None,
            )
            if ok:
                added += 1
            else:
                failed += 1

        if added > 0:
            if encrypt and self._remember_unlock_checkbox and self._remember_unlock_checkbox.isChecked():
                store.set_remember_unlock(True, passphrase)
            store.save()
            self._refresh_after_global_store_mutation()

        show_information_box(
            self,
            "导入完成",
            f"新增 {added} 个变量，失败 {failed}，跳过 {skipped}",
        )

    def _on_import_route(self) -> None:
        if not self._is_global_mode() and self._scope_combo:
            index = self._scope_combo.findData("global")
            if index >= 0:
                self._scope_combo.setCurrentIndex(index)
        dialog = RouteImportDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        options = dialog.get_options()
        name = str(options.get("name") or "").strip()
        points = options.get("points") or []
        if not name:
            show_information_box(self, "提示", "变量名不能为空")
            return
        if not points:
            show_information_box(self, "提示", "未识别到有效坐标点")
            return
        store = self._ensure_global_store()
        if not store:
            show_information_box(self, "提示", "全局变量不可用")
            return
        variables = self._read_global_variables_snapshot(store)
        if name in variables:
            reply = show_question_box(self, "覆盖确认", f"变量 '{name}' 已存在，是否覆盖？")
            if reply != QMessageBox.StandardButton.Yes:
                return
        ok = self._save_global_entry(name, "list", points)
        if ok:
            show_information_box(self, "导入完成", f"已导入路线点 {len(points)} 个")
