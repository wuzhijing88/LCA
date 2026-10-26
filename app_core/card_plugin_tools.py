"""原生参数工具的显式结果绑定，不提供窗口或外观配置语言。"""
from app_core.card_plugins import CardPluginError

TOOL_ROLES = {
    "取坐标": {"横坐标": "int", "纵坐标": "int"},
    "框选区域": {"横坐标": "int", "纵坐标": "int", "宽度": "int", "高度": "int"},
    "取色": {"颜色": "text"},
    "取偏移": {"横偏移": "int", "纵偏移": "int"},
    "截图": {"图片": "file"},
}


def validate_tools(definitions):
    for name, definition in definitions.items():
        if "tool" not in definition:
            continue
        tool = definition["tool"]
        if not isinstance(tool, dict) or set(tool) != {"类型", "写入"}:
            raise CardPluginError(f"参数 {name} 的工具只能声明类型和写入")
        kind = tool["类型"]
        if not isinstance(kind, str) or kind not in TOOL_ROLES:
            raise CardPluginError(f"参数 {name} 的原生工具类型不支持")
        targets = tool["写入"]
        if not isinstance(targets, dict) or set(targets) != set(TOOL_ROLES[kind]):
            raise CardPluginError(f"参数 {name} 的原生工具写入字段不完整或包含未知字段")
        for role, target in targets.items():
            if not isinstance(target, str) or target not in definitions or definitions[target]["type"] != TOOL_ROLES[kind][role]:
                raise CardPluginError(f"参数 {name} 的工具必须绑定已声明且类型匹配的输入")
            if role == "图片" and definitions[target].get("resource_kind") != "image":
                raise CardPluginError("截图工具只能写入图片文件参数")
        if len(set(targets.values())) != len(targets) or name not in targets.values():
            raise CardPluginError(f"参数 {name} 的工具必须包含自身，且不能重复写入")


def tool_result_updates(tool, result):
    roles = TOOL_ROLES[tool["类型"]]
    if not isinstance(result, dict) or set(result) != set(roles):
        raise CardPluginError("原生工具返回字段不完整或包含未知字段，未写入参数")
    for role, kind in roles.items():
        value = result[role]
        if kind == "int" and type(value) is not int:
            raise CardPluginError(f"工具结果 {role} 必须是整数")
        if kind in {"text", "file"} and (not isinstance(value, str) or not value):
            raise CardPluginError(f"工具结果 {role} 必须是非空文本")
        if role in {"横坐标", "纵坐标"} and value < 0:
            raise CardPluginError(f"工具结果 {role} 不能小于零")
        if role in {"宽度", "高度"} and value <= 0:
            raise CardPluginError(f"工具结果 {role} 必须大于零")
    return {target: result[role] for role, target in tool["写入"].items()}
