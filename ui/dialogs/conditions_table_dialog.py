# -*- coding: utf-8 -*-
import json
import re
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QDialogButtonBox, QMessageBox, QLabel, QPlainTextEdit, QPushButton
)
from themes import get_theme_manager
from ..widgets.custom_widgets import CustomDropdown


class NoWheelComboBox(CustomDropdown):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaxVisibleItems(8)


class ConditionsTableDialog(QDialog):
    def __init__(
        self,
        conditions: Optional[List[Dict[str, Any]]] = None,
        parent=None,
        card_id: Optional[int] = None,
        workflow_id: Optional[object] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("\u6761\u4ef6\u7f16\u8f91")
        self.setMinimumSize(660, 360)
        self.resize(720, 420)
        self._card_id = self._normalize_card_id(card_id)
        self._workflow_id = self._normalize_workflow_id(workflow_id)

        self._count_label = QLabel()
        self._count_label.setObjectName("conditions_count")

        self._text_edit = QPlainTextEdit()
        self._text_edit.setObjectName("conditions_text")
        self._text_edit.textChanged.connect(self._refresh_count)
        self._preset_combo = NoWheelComboBox()
        self._preset_insert_button = QPushButton("插入预设")

        self._build_ui()
        self._apply_styles()
        self._load_initial_rows(conditions or [])

    def _build_ui(self) -> None:
        self._text_edit.setPlaceholderText("每行一条条件")

        actions_layout = QHBoxLayout()
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        actions_layout.addWidget(self._count_label)
        actions_layout.addStretch()

        preset_layout = QHBoxLayout()
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.setSpacing(8)
        self._preset_combo.addItem("模板：变量A 等于 \"目标值\"", "变量A 等于 \"目标值\"")
        self._preset_combo.addItem("模板：变量A 大于 0", "变量A 大于 0")
        self._preset_combo.addItem("模板：变量A 包含 \"关键词\"", "变量A 包含 \"关键词\"")
        self._preset_combo.addItem("模板：变量A 大于 @变量B", "变量A 大于 @变量B")
        self._preset_combo.addItem("模板：变量A 存在", "变量A 存在")
        self._preset_insert_button.setProperty("primary", True)
        self._preset_insert_button.clicked.connect(self._insert_selected_preset)
        preset_layout.addWidget(self._preset_combo, 1)
        preset_layout.addWidget(self._preset_insert_button, 0)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_button:
            ok_button.setText("\u786e\u5b9a")
            ok_button.setProperty("primary", True)
        if cancel_button:
            cancel_button.setText("\u53d6\u6d88")

        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(actions_layout)
        layout.addLayout(preset_layout)
        layout.addWidget(self._text_edit)
        layout.addWidget(button_box)

        self._refresh_count()

    def _insert_selected_preset(self) -> None:
        preset_line = str(self._preset_combo.currentData() or self._preset_combo.currentText()).strip()
        if not preset_line:
            return
        if self._text_edit.toPlainText().strip():
            self._text_edit.appendPlainText(preset_line)
        else:
            self._text_edit.setPlainText(preset_line)
        self._text_edit.setFocus()

    def _apply_styles(self) -> None:
        theme_manager = get_theme_manager()
        background = theme_manager.get_color("background")
        surface = theme_manager.get_color("surface")
        border = theme_manager.get_color("border")
        border_light = theme_manager.get_color("border_light")
        text = theme_manager.get_color("text")
        text_secondary = theme_manager.get_color("text_secondary")

        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {background};
                color: {text};
            }}

            #conditions_count {{
                color: {text_secondary};
            }}

            #conditions_text {{
                background-color: {surface};
                border: 1px solid {border};
                border-radius: 10px;
                padding: 8px;
            }}

            #conditions_text:focus {{
                border-color: {border_light};
            }}

            QDialogButtonBox QPushButton {{
                min-width: 96px;
            }}
            """
        )

    def _load_initial_rows(self, conditions: List[Dict[str, Any]]) -> None:
        text_value = self._conditions_to_text(conditions)
        self._text_edit.setPlainText(text_value)
        self._refresh_count()

    def _get_condition_lines(self) -> List[str]:
        text = self._text_edit.toPlainText()
        lines: List[str] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                continue
            lines.append(line)
        return lines

    @staticmethod
    def _normalize_expression_line(line: str) -> str:
        text = line.strip()
        lower = text.lower()
        if lower.startswith("expr:"):
            return text.split(":", 1)[1].strip()
        if lower.startswith("expression:"):
            return text.split(":", 1)[1].strip()
        if lower.startswith("expr\uff1a"):
            return text.split("\uff1a", 1)[1].strip()
        if lower.startswith("expression\uff1a"):
            return text.split("\uff1a", 1)[1].strip()
        if text.startswith("\u8868\u8fbe\u5f0f:"):
            return text.split(":", 1)[1].strip()
        if text.startswith("\u8868\u8fbe\u5f0f\uff1a"):
            return text.split("\uff1a", 1)[1].strip()
        return text

    @staticmethod
    def _strip_wrapped_var_name(text: str) -> str:
        raw = str(text or "").strip()
        if raw.startswith("@"):
            raw = raw[1:].strip()
        if raw.startswith("${") and raw.endswith("}"):
            return raw[2:-1].strip()
        if raw.startswith("{{") and raw.endswith("}}"):
            return raw[2:-2].strip()
        return raw

    @staticmethod
    def _is_function_like_expression(text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        return bool(
            re.fullmatch(
                r"[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*\s*\(.*\)",
                raw,
            )
        )

    @classmethod
    def _build_human_operand(cls, token: str, side: str) -> str:
        raw = str(token or "").strip()
        if not raw:
            return "\"\""

        if raw.startswith("@"):
            var_name = cls._strip_wrapped_var_name(raw)
            return f"var({json.dumps(var_name, ensure_ascii=False)})" if var_name else "\"\""

        if raw.startswith("${") and raw.endswith("}"):
            return raw
        if raw.startswith("{{") and raw.endswith("}}"):
            return raw
        if raw in ("self", "this"):
            return raw
        if cls._is_number(raw):
            return raw

        lower = raw.lower()
        if lower in ("true", "false"):
            return "True" if lower == "true" else "False"
        if lower in ("none", "null"):
            return "None"

        if (raw.startswith("\"") and raw.endswith("\"")) or (raw.startswith("'") and raw.endswith("'")):
            return raw
        if cls._is_function_like_expression(raw):
            return raw

        if side == "left":
            return f"var({json.dumps(raw, ensure_ascii=False)})"
        return json.dumps(raw, ensure_ascii=False)

    @classmethod
    def _rewrite_human_friendly_expression(cls, expr: str) -> str:
        text = str(expr or "").strip()
        if not text:
            return ""

        text_op_match = re.match(
            r"^\s*(.+?)\s*(包含|不包含|开头是|结尾是|匹配正则)\s*(.+?)\s*$",
            text,
        )
        if text_op_match:
            left_raw = text_op_match.group(1)
            op = text_op_match.group(2)
            right_raw = text_op_match.group(3)
            left_expr = cls._build_human_operand(left_raw, side="left")
            right_expr = cls._build_human_operand(right_raw, side="right")
            if op == "不包含":
                return f"not contains({left_expr}, {right_expr})"
            func_map = {
                "包含": "contains",
                "开头是": "startswith",
                "结尾是": "endswith",
                "匹配正则": "regex",
            }
            func_name = func_map.get(op)
            if func_name:
                return f"{func_name}({left_expr}, {right_expr})"

        cmp_match = re.match(
            r"^\s*(.+?)\s*(大于等于|小于等于|不等于|等于|大于|小于)\s*(.+?)\s*$",
            text,
        )
        if cmp_match:
            left_raw = cmp_match.group(1)
            op = cmp_match.group(2)
            right_raw = cmp_match.group(3)
            left_expr = cls._build_human_operand(left_raw, side="left")
            right_expr = cls._build_human_operand(right_raw, side="right")
            symbol_map = {
                "等于": "==",
                "不等于": "!=",
                "大于": ">",
                "小于": "<",
                "大于等于": ">=",
                "小于等于": "<=",
            }
            symbol = symbol_map.get(op)
            if symbol:
                return f"{left_expr} {symbol} {right_expr}"

        exists_match = re.match(r"^\s*(.+?)\s*(存在|不存在)\s*$", text)
        if exists_match:
            var_name = cls._strip_wrapped_var_name(exists_match.group(1))
            if var_name:
                exists_expr = f"存在({json.dumps(var_name, ensure_ascii=False)})"
                if exists_match.group(2) == "不存在":
                    return f"not {exists_expr}"
                return exists_expr

        return text

    @staticmethod
    def _is_identifier(text: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text))

    def _format_var_reference(self, name: str) -> str:
        raw = str(name or "").strip()
        if not raw:
            return ""
        if raw.startswith("${") and raw.endswith("}"):
            return raw
        if raw.startswith("{{") and raw.endswith("}}"):
            return raw
        if self._is_identifier(raw):
            return raw
        return f"${{{raw}}}"

    @staticmethod
    def _operator_to_symbol(op: str) -> str:
        mapping = {
            "\u7b49\u4e8e": "==",
            "\u4e0d\u7b49\u4e8e": "!=",
            "\u5927\u4e8e": ">",
            "\u5c0f\u4e8e": "<",
            "\u5927\u4e8e\u7b49\u4e8e": ">=",
            "\u5c0f\u4e8e\u7b49\u4e8e": "<=",
            "==": "==",
            "=": "==",
            "!=": "!=",
            ">": ">",
            "<": "<",
            ">=": ">=",
            "<=": "<=",
        }
        return mapping.get(str(op).strip(), str(op).strip())

    @staticmethod
    def _is_number(text: str) -> bool:
        return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text))

    def _format_literal(self, value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        if self._is_number(raw):
            return raw
        if raw in ("True", "False", "true", "false"):
            return raw
        if (raw.startswith("\"") and raw.endswith("\"")) or (raw.startswith("'") and raw.endswith("'")):
            return raw
        return json.dumps(raw, ensure_ascii=False)

    def _replace_self_reference(self, expr: str, left_value: str) -> str:
        if not expr or not left_value:
            return expr
        target = self._format_var_reference(left_value)
        if not target:
            return expr
        return re.sub(r"\b(self|this)\b", target, expr)

    def _conditions_to_text(self, conditions: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for row in conditions:
            if not isinstance(row, dict):
                continue
            operator = str(row.get("operator", "")).strip()
            left_value = str(row.get("left_value", "")).strip()
            right_source = str(row.get("right_source", "")).strip()
            right_value = str(row.get("right_value", "")).strip()

            if operator in ("\u8868\u8fbe\u5f0f", "expr", "expression"):
                if right_value:
                    lines.append(self._replace_self_reference(right_value, left_value))
                continue

            left_text = self._format_var_reference(left_value)
            op_symbol = self._operator_to_symbol(operator)
            if right_source in ("\u53d8\u91cf", "\u53d8\u91cf\u540d"):
                right_text = self._format_var_reference(right_value)
            else:
                right_text = self._format_literal(right_value)

            if left_text and op_symbol and right_text:
                lines.append(f"{left_text} {op_symbol} {right_text}")
            elif right_value:
                lines.append(right_value)
        return "\n".join(lines)

    @staticmethod
    def _normalize_workflow_id(value: Optional[object]) -> Optional[object]:
        if value in (None, "", "\u5f53\u524d\u5de5\u4f5c\u6d41"):
            return None
        if value in ("\u5168\u5c40\u53d8\u91cf", "global"):
            return "global"
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_card_id(value: Optional[int]) -> Optional[int]:
        if value in (None, "", "\u5168\u90e8"):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _refresh_count(self) -> None:
        self._count_label.setText(f"\u6761\u4ef6\u6570: {len(self._get_condition_lines())}")

    def get_conditions(self) -> List[Dict[str, Any]]:
        conditions: List[Dict[str, Any]] = []
        for raw_line in self._get_condition_lines():
            expr = self._normalize_expression_line(raw_line)
            expr = self._rewrite_human_friendly_expression(expr)
            if not expr:
                continue
            conditions.append(
                {
                    "left_source": "\u53d8\u91cf",
                    "left_value": "",
                    "operator": "\u8868\u8fbe\u5f0f",
                    "right_source": "\u8868\u8fbe\u5f0f",
                    "right_value": expr,
                }
            )
        return conditions

    def _validate_conditions(self, conditions: List[Dict[str, Any]]) -> Optional[str]:
        if not conditions:
            return "\u8bf7\u81f3\u5c11\u6dfb\u52a0 1 \u6761\u6761\u4ef6"

        for index, row in enumerate(conditions, start=1):
            expr = str(row.get("right_value", "")).strip()
            if not expr:
                return f"\u6761\u4ef6 {index} \u8868\u8fbe\u5f0f\u4e3a\u7a7a"

        return None

    def _on_accept(self) -> None:
        conditions = self.get_conditions()
        error = self._validate_conditions(conditions)
        if error:
            QMessageBox.warning(self, "\u6761\u4ef6\u9519\u8bef", error)
            return
        self.accept()
