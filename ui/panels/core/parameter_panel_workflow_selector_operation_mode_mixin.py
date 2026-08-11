from ..parameter_panel_support import *


class ParameterPanelWorkflowSelectorOperationModeMixin:
    _LEGACY_OPERATION_MODE_BY_INDEX = [
        "找图功能",
        "坐标点击",
        "文字点击",
        "找色功能",
        "元素点击",
        "鼠标滚轮",
        "鼠标拖拽",
        "鼠标移动",
    ]

    _OPERATION_MODE_ALIAS = {
        "图片点击": "找图功能",
        "找图点击": "找图功能",
        "找色点击": "找色功能",
    }

    _LEGACY_IMAGE_TASK_TYPES = {"图片点击", "查找图片并点击", "找图点击", "找图功能"}

    def _normalize_operation_mode_value(self, value: Any, fallback_task_type: str = "") -> str:
        """归一化 operation_mode，兼容旧文案和旧索引值。"""
        mode = ""

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            idx = int(value)
            if 0 <= idx < len(self._LEGACY_OPERATION_MODE_BY_INDEX):
                mode = self._LEGACY_OPERATION_MODE_BY_INDEX[idx]
            else:
                mode = str(value).strip()
        else:
            mode = str(value or "").strip()
            if mode.isdigit():
                idx = int(mode)
                if 0 <= idx < len(self._LEGACY_OPERATION_MODE_BY_INDEX):
                    mode = self._LEGACY_OPERATION_MODE_BY_INDEX[idx]

        mode = self._OPERATION_MODE_ALIAS.get(mode, mode)
        if mode:
            return mode

        task_type_candidates = [
            str(fallback_task_type or "").strip(),
            str(self.current_task_type or "").strip(),
            str(self.current_parameters.get("task_type", "") or "").strip(),
        ]
        if any(task_type in self._LEGACY_IMAGE_TASK_TYPES for task_type in task_type_candidates if task_type):
            return "找图功能"
        return ""

    def _normalize_operation_mode_parameter(self, param_definitions: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        """在参数面板初始化阶段统一修正 operation_mode。"""
        definitions = param_definitions or self.param_definitions
        if "operation_mode" not in definitions:
            return

        raw_value = self.current_parameters.get("operation_mode")
        normalized = self._normalize_operation_mode_value(raw_value, fallback_task_type=self.current_task_type or "")
        if normalized:
            self.current_parameters["operation_mode"] = normalized
