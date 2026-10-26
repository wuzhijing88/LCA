"""从输入类型派生原生控件，不接受独立的插件表单语言。"""
from __future__ import annotations

from app_core.card_plugins import CardPluginError

_DEFAULT_CONTROLS = {
    "text": "文本框", "int": "整数输入", "float": "小数输入",
    "bool": "复选框", "choice": "下拉框", "file": "文件选择",
}


def parameter_presentation(definition):
    if any(field in definition for field in ("ui", "compute", "option_rules", "range_rules", "visible_when", "enabled_when", "required_when")):
        raise CardPluginError("参数包含已移除的界面或联动声明")
    control = "多行文本" if definition.get("multiline") else _DEFAULT_CONTROLS[definition["type"]]
    presentation = {"控件": control, "分组": "", "页签": "", "列数": 1, "顺序": 0}
    if definition.get("resource_kind") == "image":
        presentation["预览"] = True
    if "tool" in definition:
        presentation["工具"] = definition["tool"]
    return presentation


def validate_presentations(definitions):
    from app_core.card_plugin_tools import validate_tools

    for definition in definitions.values():
        parameter_presentation(definition)
    validate_tools(definitions)


def describe_presentation(definition):
    parts = ["控件：" + parameter_presentation(definition)["控件"]]
    if "tool" in definition:
        parts.append("原生工具：" + definition["tool"]["类型"])
    return "，".join(parts)
