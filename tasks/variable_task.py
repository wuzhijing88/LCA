# -*- coding: utf-8 -*-

"""
变量提取卡片 - 从变量文本中自定义格式提取数据
"""

import json
import re
import logging
from typing import Dict, Any, Optional, Tuple, List

logger = logging.getLogger(__name__)

TASK_NAME = '变量提取'
_NUM_CAPTURE_PATTERN = r'([+-]?\d+(?:\.\d+)?)'


def get_params_definition() -> Dict[str, Any]:
    """返回变量提取卡片的参数定义"""
    return {
        "source_workflow_id": {
            "label": "来源工作流",
            "type": "select",
            "default": None,
            "widget_hint": "workflow_selector",
            "tooltip": "选择变量来源的工作流（只读）"
        },
        "source_card_id": {
            "label": "卡片ID",
            "type": "select",
            "default": None,
            "widget_hint": "variable_card_selector",
            "workflow_filter_param": "source_workflow_id",
            "tooltip": "选择变量来源的工作流（只读）"
        },
        "ocr_variable_names": {
            "label": "目标来源",
            "type": "text",
            "default": "[]",
            "widget_hint": "variable_sources_table",
            "workflow_filter_param": "source_workflow_id",
            "card_filter_param": "source_card_id",
            "placeholder": "卡片12结果.全部文字, 卡片15结果.目标文字",
            "tooltip": "支持变量名列表；可用 全局:变量名 或 global:变量名 强制读取全局变量"
        },
        "format_template": {
            "label": "提取格式模板",
            "type": "textarea",
            "widget_hint": "template_preset_editor",
            "default": "HH:MM:SS",
            "template_presets": [
                {"label": "时间 HH:MM:SS", "value": "HH:MM:SS"},
                {"label": "坐标 #,#", "value": "#,#"},
                {"label": "坐标 (#,#)", "value": "(#,#)"},
                {"label": "血量 HP #/#", "value": "HP #/#"},
                {"label": "百分比 #%", "value": "#%"},
                {"label": "日期 YYYY-MM-DD", "value": "YYYY-MM-DD"},
            ],
            "tooltip": "支持 {} / {name} / # 占位符；多模板可用换行或 || 分隔",
        },
        "allow_overwrite": {
            "label": "允许覆盖变量",
            "type": "bool",
            "default": True,
            "tooltip": "开启后覆盖不提示；关闭后如变量已存在将弹窗确认",
            "hidden": True
        },
    }


def _confirm_overwrite(
    name: str,
    old_value: Any,
    new_value: Any,
    allow_overwrite: bool,
    parent=None,
    executor=None,
) -> bool:
    if allow_overwrite or old_value is None or old_value == new_value:
        return True
    logger.debug("变量已存在且不允许覆盖，跳过写入: %s", name)
    return False


def _normalize_allow_overwrite(value: Any) -> bool:
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("false", "0", "no", "off"):
            return False
        if text in ("true", "1", "yes", "on"):
            return True
    return bool(value)

def _normalize_card_id(value: Any) -> Optional[int]:
    if value in (None, "", "全部"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None



def _split_variable_names_from_text(text: str) -> List[str]:
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


def _split_variable_names(raw_value: Any) -> List[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except Exception:
                pass
        return _split_variable_names_from_text(text)
    return _split_variable_names_from_text(str(raw_value))


def _extract_text_candidates(value: Any) -> List[str]:
    texts: List[str] = []

    def _add(candidate: Any) -> None:
        if candidate is None:
            return
        text = str(candidate).strip()
        if text:
            texts.append(text)

    def _from_dict(data: dict) -> None:
        for key in ("文字", "text"):
            if key in data:
                _add(data.get(key))

    if value is None:
        return texts
    if isinstance(value, dict):
        _from_dict(value)
    elif isinstance(value, (list, tuple)):
        for item in value:
            texts.extend(_extract_text_candidates(item))
    else:
        _add(value)

    return texts


def _build_regex_pattern(format_template: str) -> Tuple[str, List[str]]:
    """
    将格式模板转换为正则表达式

    Args:
        format_template: 用户定义的格式模板
        支持两种占位符：
        1. 显式占位符: {} 或 {name}  - 明确表示要提取的数字
        2. 隐式占位符: 重复字母如 HH, MM, SS 等 - 自动识别为数字占位符

        分隔符灵活匹配：
        - 空格会自动匹配1个或多个空白符(空格、制表符等)
        - 逗号、冒号、分号、斜杠、中划线会自动匹配前后可选空白符
        - 括号会自动匹配前后可选空白符
        - 百分号会自动匹配前面可选空白符

        示例:
        - "HH:MM:SS" -> 可匹配 "12:34:56" 或 "12 : 34 : 56"
        - "HP {}/{}" -> 可匹配 "HP 100/200" 或 "HP 100 / 200"
        - "({x},{y})" -> 可匹配 "(123,456)" 或 "( 123 , 456 )"
        - "{} {}" -> 可匹配 "123 456" 或 "123  456"
        - "{percent}%" -> 可匹配 "50%" 或 "50 %"

    Returns:
        (regex_pattern, field_names): 正则表达式和字段名列表
    """
    format_template = str(format_template or "")
    # 简写支持：# / ＃ 等价于 {}，便于非编程用户快速录入
    if "#" in format_template or "＃" in format_template:
        format_template = format_template.replace("＃", "#").replace("#", "{}")

    # 第一步：识别所有占位符位置
    # 先找显式占位符 {name} 或 {}
    explicit_placeholders = list(re.finditer(r'\{([^}]*)\}', format_template))
    explicit_fields = [m.group(1) for m in explicit_placeholders]

    # 再找隐式占位符 - 重复字母 (HH, MM, SS, DD 等)
    implicit_pattern = r'([A-Z])\1(?![A-Z])'
    implicit_placeholders = list(re.finditer(implicit_pattern, format_template))
    implicit_fields = [m.group(0) for m in implicit_placeholders]

    # 第二步：检查冲突 - 不能同时使用两种占位符
    if explicit_fields and implicit_fields:
        logger.warning("格式模板既包含显式占位符 {} 又包含隐式占位符如 HH，建议使用统一的方式")

    # 第三步：确定字段列表
    if explicit_fields:
        fields = explicit_fields
        # 使用显式占位符构建正则
        regex = format_template
        result = ""
        i = 0
        while i < len(regex):
            if regex[i] == '{':
                end = regex.find('}', i)
                if end != -1:
                    result += '(!)'  # 临时占位符
                    i = end + 1
                    continue

            # 空格转换为\s+（1个或多个空白符）
            if regex[i] == ' ':
                result += r'\s+'
                i += 1
            # 标点符号前后加可选空白符
            elif regex[i] in ',;:/-':
                result += r'\s*' + re.escape(regex[i]) + r'\s*'
                i += 1
            # 括号前后加可选空白符
            elif regex[i] in '()':
                result += r'\s*' + '\\' + regex[i] + r'\s*'
                i += 1
            # 百分号前加可选空白符
            elif regex[i] == '%':
                result += r'\s*' + re.escape(regex[i])
                i += 1
            elif regex[i] in r'.^$*+?[]|\\':
                result += '\\' + regex[i]
                i += 1
            else:
                result += regex[i]
                i += 1
        regex = result.replace('(!)', _NUM_CAPTURE_PATTERN)
    else:
        fields = implicit_fields
        # 使用隐式占位符构建正则
        result = ""
        i = 0
        while i < len(format_template):
            # 检查是否是重复字母（隐式占位符）
            if i < len(format_template) - 1 and format_template[i].isupper() and format_template[i] == format_template[i+1]:
                result += _NUM_CAPTURE_PATTERN
                i += 2
            # 空格转换为\s+
            elif format_template[i] == ' ':
                result += r'\s+'
                i += 1
            # 标点符号前后加可选空白符
            elif format_template[i] in ',;:/-':
                result += r'\s*' + re.escape(format_template[i]) + r'\s*'
                i += 1
            # 括号前后加可选空白符
            elif format_template[i] in '()':
                result += r'\s*' + '\\' + format_template[i] + r'\s*'
                i += 1
            # 百分号前加可选空白符
            elif format_template[i] == '%':
                result += r'\s*' + re.escape(format_template[i])
                i += 1
            elif format_template[i] in r'.^$*+?[]|\\':
                result += '\\' + format_template[i]
                i += 1
            else:
                result += format_template[i]
                i += 1
        regex = result

    logger.debug(f"格式模板: {format_template} -> 正则: {regex} -> 字段: {fields}")

    return regex, fields


def _parse_numeric_capture(value: str) -> Any:
    text = str(value or "").strip()
    if not text:
        raise ValueError("空值无法转换为数字")
    if re.fullmatch(r"[+-]?\d+", text):
        return int(text)
    return float(text)


def _extract_from_text(format_template: str, text: str) -> Optional[Any]:
    """
    从目标文本中按格式提取数据

    Args:
        format_template: 用户定义的格式
        text: 待匹配的文本

    Returns:
        提取的数据（数组或对象），如果匹配失败返回None
    """
    regex, field_names = _build_regex_pattern(format_template)

    try:
        # 使用原始正则表达式（包含转义）
        match = re.search(regex, text)
        if not match:
            logger.debug(f"格式 '{format_template}' 在文本 '{text}' 中未匹配")
            return None

        # 获取所有捕获组
        try:
            captured_values = [_parse_numeric_capture(v) for v in match.groups()]
        except ValueError as ve:
            logger.warning(f"捕获的值无法转换为数字: {match.groups()}, 错误: {ve}")
            return None

        # 判断是否有命名字段（非空字段名或隐式字段）
        has_named_fields = any(name for name in field_names)

        if has_named_fields:
            # 有命名字段 -> 返回对象 {"HH": 0, "MM": 56, "SS": 15} 或 {"x": 42, "y": 89}
            result = {}
            for i, name in enumerate(field_names):
                if i < len(captured_values):
                    # 使用字段名作为键（隐式占位符 HH, MM, SS 等也能作为有意义的键）
                    result[name] = captured_values[i]

            return result if result else None
        else:
            # 未命名字段 -> 返回数组或单个值
            if len(captured_values) == 0:
                return None
            elif len(captured_values) == 1:
                return captured_values[0]  # 单个值
            else:
                return captured_values  # 数组

    except Exception as e:
        logger.error(f"格式提取失败 - 格式: {format_template}, 文本: {text}, 错误: {e}")
        return None


def execute_task(params: Dict[str, Any], counters: Dict[str, int],
                execution_mode='foreground', **kwargs) -> Tuple[bool, str, Optional[int]]:
    """
    执行变量提取任务
    """
    try:
        logger.info("开始执行变量提取任务")
        parent = kwargs.get('parameter_panel') or kwargs.get('main_window')
        executor = kwargs.get('executor')
        card_id = kwargs.get('card_id')

        # 获取工作流上下文
        try:
            from task_workflow.workflow_context import get_workflow_context
            from task_workflow.workflow_vars import get_context_for_task, normalize_workflow_task_id
            from task_workflow.variable_resolver import lookup_variable_entry, normalize_variable_name
        except ImportError:
            logger.error("无法导入工作流上下文模块")
            return False, '执行下一步', None

        # 获取参数
        source_card_id = _normalize_card_id(params.get('source_card_id'))
        source_workflow_id = normalize_workflow_task_id(params.get('source_workflow_id'))
        result_prefix = str(params.get('save_result_variable_name', '') or '').strip()
        if not result_prefix and card_id is not None:
            result_prefix = f"卡片{card_id}结果"
        variable_name = result_prefix or "变量提取结果"

        # 变量来源：仅使用变量来源
        source_variable_raw = params.get('ocr_variable_names', '')
        source_variable_names = _split_variable_names(source_variable_raw)
        texts_to_check = []

        if not source_variable_names:
            logger.warning("未配置目标来源变量或所选卡片无可用变量，无法提取变量")
            return False, '执行下一步', None

        context = get_workflow_context()
        source_context = context
        if source_workflow_id is not None:
            source_context = get_context_for_task(source_workflow_id) or context

        source_specs = []
        for raw_name in source_variable_names:
            normalized_name, force_global = normalize_variable_name(raw_name)
            if not normalized_name:
                continue
            source_specs.append({
                "raw": str(raw_name).strip(),
                "normalized": normalized_name,
                "force_global": bool(force_global),
            })

        if source_card_id is not None:
            source_map = getattr(source_context, "var_sources", {}) or {}
            filtered_specs = [
                spec for spec in source_specs
                if spec["force_global"] or source_map.get(spec["normalized"]) == source_card_id
            ]
            if source_specs and not filtered_specs:
                logger.warning(f"目标来源变量不属于选择的卡片ID: {source_card_id}")
                return False, '执行下一步', None
            source_specs = filtered_specs

        for spec in source_specs:
            raw_name = spec["raw"]
            normalized_name = spec["normalized"]

            found, value = lookup_variable_entry(raw_name, context=source_context)
            if (not found) and isinstance(counters, dict):
                if raw_name in counters:
                    value = counters.get(raw_name)
                    found = True
                elif normalized_name in counters:
                    value = counters.get(normalized_name)
                    found = True
            if not found:
                logger.warning(f"未找到目标来源变量: '{raw_name}'")
                continue
            texts_to_check.extend(_extract_text_candidates(value))

        if not texts_to_check:
                logger.warning("未找到可用于提取的目标文本")
                return False, '执行下一步', None

        # 获取参数
        format_template_raw = params.get('format_template', '').strip()

        if not format_template_raw:
            logger.error("格式模板为空")
            return False, '执行下一步', None

        # 解析多格式（支持换行或双竖线分隔）
        # 先尝试按换行分割，如果只有一行则按分号分割
        if '\n' in format_template_raw:
            format_templates = [line.strip() for line in format_template_raw.split('\n') if line.strip()]
        elif '||' in format_template_raw:
            # 使用双竖线分隔多个格式
            format_templates = [fmt.strip() for fmt in format_template_raw.split('||') if fmt.strip()]
        else:
            format_templates = [format_template_raw.strip()]

        if not format_templates:
            logger.error("格式模板为空")
            return False, '执行下一步', None

        logger.info(f"格式模板数量: {len(format_templates)}")
        logger.info(f"变量名: {variable_name}")
        logger.info(f"目标文本数量: {len(texts_to_check)}")

        # 打印所有文本和格式模板，方便调试
        logger.info(f"格式模板列表: {format_templates}")

        # 开始提取
        extracted_data = None
        matched_text = None
        matched_format = None


        # 尝试从文本中提取数据
        if extracted_data is None:
            for text in texts_to_check:
                text = str(text).strip()
                if not text:
                    continue
    
                logger.info(f"尝试匹配文本: '{text}'")
    
                # 依次尝试每个格式模板
                for format_template in format_templates:
                    data = _extract_from_text(format_template, text)
                    if data is not None:
                        extracted_data = data
                        matched_text = text
                        matched_format = format_template
                        logger.info(f"成功提取 - 格式: '{format_template}' 源文本: '{text}' -> 提取数据: {data}")
                        break
                    else:
                        logger.info(f"  格式 '{format_template}' 无法匹配文本 '{text}'")
    
                if extracted_data is not None:
                    break
    
        if extracted_data is None:
            logger.warning("所有格式模板均无法从任何目标文本中提取数据")
            logger.warning(f"  格式模板: {format_templates}")
            logger.warning(f"  目标文本: {texts_to_check}")
            return False, '执行下一步', None

        # 存储提取的数据
        context = get_workflow_context()
        allow_overwrite = _normalize_allow_overwrite(params.get('allow_overwrite', True))
        if not _confirm_overwrite(
            variable_name,
            context.get_global_var(variable_name),
            extracted_data,
            allow_overwrite,
            parent,
            executor=executor,
        ):
            logger.warning(f"变量提取取消覆盖: '{variable_name}'")
            return True, '执行下一步', None
        context.set_global_var(variable_name, extracted_data, card_id=card_id)

        # 同时存储到counters供其他卡片使用
        counters[variable_name] = extracted_data

        # 如果提取结果是字典，将每个字段也保存为独立的全局变量
        if isinstance(extracted_data, dict):
            for field_name, field_value in extracted_data.items():
                if not _confirm_overwrite(
                    field_name,
                    context.get_global_var(field_name),
                    field_value,
                    allow_overwrite,
                    parent,
                    executor=executor,
                ):
                    logger.warning(f"字段变量保留原值: '{field_name}'")
                    continue
                context.set_global_var(field_name, field_value, card_id=card_id)
                counters[field_name] = field_value
                logger.info(f"保存字段变量: {field_name} = {field_value}")

        # 记录元数据
        context.set_global_var(f"{variable_name}.来源", matched_text, card_id=card_id)
        context.set_global_var(f"{variable_name}.格式", matched_format, card_id=card_id)

        logger.info(f"变量 '{variable_name}' 已存储: {extracted_data}")

        return True, '执行下一步', None

    except Exception as e:
        logger.error(f"变量提取任务执行失败: {e}", exc_info=True)
        return False, '执行下一步', None
