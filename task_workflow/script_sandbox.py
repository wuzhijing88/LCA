# -*- coding: utf-8 -*-
"""自定义脚本执行器：提供中文命令，并执行完整 Python 代码。"""

from __future__ import annotations

import ast
import logging
import math
import threading
import time
import json
import os
import platform
import sys
from typing import Any, Dict, Optional, Tuple

from task_workflow.runtime_store import RuntimeStore, normalize_var_value, normalize_var_name
from task_workflow.script_commands import RESULT_FIELD_ALIASES, CommandHost, ScriptResult, finite_seconds, integer_parameter
from task_workflow.script_parameters import (
    add_numeric_values,
    boolean_parameter as _as_bool,
    text_parameter as _text,
)
from task_workflow.script_image import IMAGE_METHODS, ImageApi
from task_workflow.card_plugin_runtime import PluginParameterView, PluginOutputView

from task_workflow.script_pure import (
    script_for_iterable,
    script_random,
    script_sqrt,
    script_sin,
    script_cos,
    script_clamp,
    script_contains,
    script_slice,
    script_replace,
    script_strip,
    script_find,
    script_extract_number,
    script_split,
    script_now_ms,
    script_json_parse,
    script_json_dump,
    script_dict_get,
    script_dict_set,
    script_list_append,
    script_list_pop,
    script_type,
    script_assert,
    script_dict_keys,
    script_dict_values,
    script_list_extend,
    script_startswith,
    script_endswith,
    script_sort,
    script_round,
    script_list_clear,
    script_sum,
    script_nearest_int,
)

logger = logging.getLogger(__name__)


COMMAND_NAMES = (
    "找图",
    "找色",
    "找所有图",
    "等图",
    "等色",
    "等文字",
    "等图消失",
    "等色消失",
    "等文字消失",
    "等检测",
    "等检测消失",
    "持续检测",
    "停止检测",
    "持续找图",
    "停止找图",
    "多线程",
    "关闭线程",
    "线程状态",
    "等待线程",
    "线程结果",
    "框内点",
    "随机点",
    "距离",
    "角度",
    "取色",
    "比色",
    "点击",
    "按下",
    "松开",
    "按住",
    "连点",
    "移动",
    "相对移动",
    "鼠标位置",
    "拖拽",
    "滚轮",
    "按键",
    "输入",
    "延时",
    "等毫秒",
    "找字",
    "找字库",
    "等字库",
    "等字库消失",
    "点字库",
    "点文字",
    "点元素",
    "检测",
    "播放",
    "停止播放",
    "回放",
    "暂停回放",
    "继续回放",
    "停止回放",
    "截图",
    "等按键",
    "记录",
    "成功",
    "失败",
)
_BUILTIN_CALLS = (
    "长度",
    "整数",
    "小数",
    "到文本",
    "真假",
    "最小",
    "最大",
    "绝对值",
    "开方",
    "平方根",
    "正弦",
    "余弦",
    "限制",
    "范围",
    "随机",
    "包含",
    "截取",
    "替换",
    "分割",
    "去空格",
    "查找",
    "提取数字",
    "时间",
    "枚举",
    "配对",
    "排序",
    "四舍五入",
    "全部",
    "任一",
    "字典获取",
    "字典设置",
    "列表追加",
    "列表弹出",
    "类型",
    "断言",
    "字典键",
    "字典值",
    "列表合并",
    "列表清空",
    "求和",
    "就近取整",
    "开头是",
    "结尾是",
    "JSON解析",
    "JSON生成",
)

# These names are used only as the internal targets of Chinese-name
# translation. They are not accepted as script source identifiers.
_TRANSLATED_BUILTIN_CALLS = (
    "len",
    "int",
    "float",
    "str",
    "bool",
    "min",
    "max",
    "abs",
    "range",
)
_RESULT_METHODS = frozenset({"点", "随机点"})
_EXCEPTION_NAMES = (
    "异常",
    "值错误",
    "类型错误",
    "运行错误",
    "Exception",
    "BaseException",
    "ValueError",
    "TypeError",
    "RuntimeError",
    "KeyError",
    "IndexError",
    "AttributeError",
    "ZeroDivisionError",
    "StopIteration",
    "NameError",
    "ArithmeticError",
    "AssertionError",
)

ALLOWED_CALLS = {
    *(f"图像.{name}" for name in IMAGE_METHODS),
    "大漠内存.模块基址", "大漠内存.模块大小",
    "大漠内存.读取整数", "大漠内存.读取单精度", "大漠内存.读取双精度",
    "大漠内存.读取文本", "大漠内存.读取数据",
    "大漠内存.写入整数", "大漠内存.写入单精度", "大漠内存.写入双精度",
    "大漠内存.写入文本", "大漠内存.写入数据",
    "大漠内存.搜索整数", "大漠内存.搜索单精度", "大漠内存.搜索双精度",
    "大漠内存.搜索文本", "大漠内存.搜索数据",
    "大漠内存.申请", "大漠内存.释放", "大漠内存.清理",
    "大漠汇编.添加", "大漠汇编.清空", "大漠汇编.调用",
    "大漠汇编.基址调用", "大漠汇编.超时",
    "变量.获取",
    "变量.设置",
    "变量.增加",
    "变量.存在",
    "变量.删除",
    "变量.全局获取",
    "变量.全局设置",
    "变量.全局增加",
    "变量.全局存在",
    "变量.全局删除",
    "区域.设置",
    "区域.获取",
    "区域.存在",
    "区域.删除",
    "区域.列表",
    "剪贴板.获取",
    "剪贴板.设置",
    "窗口.设置分辨率",
    "窗口.枚举",
    "窗口.查找",
    "窗口.信息",
    "窗口.激活",
    "窗口.查找元素",
    "窗口.元素文本",
    "窗口.设置元素值",
    "窗口.元素属性",
    "窗口.元素聚焦",
    "窗口.元素切换",
    "窗口.元素选择",
    "窗口.元素展开",
    "窗口.元素折叠",
    "窗口.坐标转换",
    "窗口.兼容性",
    "输入设备.枚举",
    "输入设备.能力",
    "输入设备.状态",
    "输入设备.等待按钮",
    "输入设备.HID枚举",
    "输入设备.HID读取",
    "输入设备.HID写入",
    "窗口.子窗口",
    "窗口.消息",
    "窗口.Z序",
    "窗口.DPI",
    "网络.请求",
    "事件.等待窗口",
    "事件.等待进程",
    "事件.等待窗口关闭",
    "事件.等待进程退出",
    "事件.等待文件",
    "窗口.关闭",
    "窗口.显示",
    "窗口.隐藏",
    "窗口.最小化",
    "窗口.还原",
    "窗口.移动",
    "窗口.大小",
    "进程.查找",
    "进程.信息",
    "进程.是否运行",
    "进程.启动",
    "进程.关闭",
    "热键.注册",
    "热键.注销",
    "热键.全部注销",
    "定时器.启动",
    "定时器.停止",
    "组件.加载",
    "组件.调用",
    "组件.读取",
    "组件.写入",
    "组件.运行",
    "组件.关闭",
    "数据.读取",
    "数据.写入",
    "数据.JSON读取",
    "数据.JSON写入",
    "数据.INI读取",
    "数据.INI写入",
    "数据.CSV读取",
    "数据.SQLite查询",
    "性能.快照",
    "数据.存在",
    "数据.删除",
    *COMMAND_NAMES,
    *_BUILTIN_CALLS,
    *_TRANSLATED_BUILTIN_CALLS,
    *_EXCEPTION_NAMES,
}

ALLOWED_CALL_ROOTS = frozenset({"参数", "输出", *COMMAND_NAMES, *_BUILTIN_CALLS, *_TRANSLATED_BUILTIN_CALLS, *_EXCEPTION_NAMES})

_CN_IDENT_MAP = {
    "导入": "import",
    "从": "from",
    "作为": "as",
    "尝试": "try",
    "捕获": "except",
    "最终": "finally",
    "抛出": "raise",
    "匿名": "lambda",
    "使用": "with",
    "就是": "is",
    "否则如果": "elif",
    "如果": "if",
    "否则": "else",
    "循环": "for",
    "当": "while",
    "范围": "range",
    "中断": "break",
    "继续": "continue",
    "并且": "and",
    "或者": "or",
    "在": "in",
    "真": "True",
    "假": "False",
    "空": "None",
    "略过": "pass",
    "返回": "return",
    "子程序": "def",
    "函数": "def",
    "长度": "len",
    "整数": "int",
    "小数": "float",
    "到文本": "str",
    "真假": "bool",
    "最小": "min",
    "最大": "max",
    "绝对值": "abs",
}

_SYNTAX_CN = (
    ("'break' outside loop", "中断 只能写在循环里"),
    ("'continue' not properly in loop", "继续 只能写在循环里"),
    ("expected 'except' or 'finally' block", "尝试 后需要 捕获 或 最终 代码块"),
    ("expected ':'", "这里少了冒号"),
    ("invalid syntax", "写法不对"),
    ("unexpected EOF while parsing", "代码没写完"),
    ("unexpected EOF", "代码没写完"),
    ("unmatched ')'", "括号不配对"),
    ("unmatched ']'", "括号不配对"),
    ("unmatched '}'", "括号不配对"),
    ("EOL while scanning string literal", "字符串没写完"),
    ("unterminated string literal", "字符串没写完"),
    ("cannot assign to", "这个名字不能当变量用"),
    ("'return' outside function", "不能单独写返回，请用 成功() 或 失败()"),
)
FIELD_ALIASES = RESULT_FIELD_ALIASES


class ScriptError(ValueError):
    """脚本语法或运行错误。"""

    def __init__(self, message: str, lineno: Optional[int] = None):
        text = str(message or "")
        line = int(lineno) if lineno else None
        if line and "第" not in text[:8]:
            text = f"第{line}行：{text}"
        super().__init__(text)
        self.lineno = line


class ScriptOutcome(Exception):
    def __init__(self, success: bool, detail: str = ""):
        self.success = bool(success)
        self.detail = str(detail or "")
        super().__init__(self.detail)


class _Guard:
    def __init__(
        self,
        stop_checker=None,
        pause_checker=None,
    ) -> None:
        self.stop_checker = stop_checker
        self.pause_checker = pause_checker

    def __call__(self) -> None:
        self._check_stop()
        self._wait_pause()

    def loop(self) -> None:
        self()

    def _check_stop(self) -> None:
        if not callable(self.stop_checker):
            return
        try:
            stopped = bool(self.stop_checker())
        except ScriptError:
            raise
        except Exception as exc:
            raise ScriptError(f"停止检查失败: {exc}") from exc
        if stopped:
            raise ScriptError("已停止")

    def _wait_pause(self) -> None:
        if not callable(self.pause_checker):
            return
        while True:
            try:
                paused = bool(self.pause_checker())
            except ScriptError:
                raise
            except Exception as exc:
                raise ScriptError(f"暂停检查失败: {exc}") from exc
            if not paused:
                return
            self._check_stop()
            time.sleep(0.05)


def _is_outcome_call(stmt: ast.AST) -> str:
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
        return ""
    func = stmt.value.func
    if isinstance(func, ast.Name) and func.id in {"成功", "失败"}:
        return func.id
    return ""


def _is_exit_stmt(stmt: ast.AST) -> str:
    name = _is_outcome_call(stmt)
    if name:
        return f"{name}()"
    if isinstance(stmt, ast.Return):
        return "返回"
    return ""


def _is_ident_char(char: str) -> bool:
    return bool(char) and (char.isalnum() or char == "_" or "\u4e00" <= char <= "\u9fff")


def _peek_ident(text: str, index: int) -> str:
    cursor = index
    length = len(text)
    while cursor < length and text[cursor] in {" ", "\t"}:
        cursor += 1
    if cursor >= length or not _is_ident_char(text[cursor]):
        return ""
    end = cursor + 1
    while end < length and _is_ident_char(text[end]):
        end += 1
    return text[cursor:end]


_CN_PUNCT_MAP = {
    "（": "(",
    "）": ")",
    "【": "[",
    "】": "]",
    "［": "[",
    "］": "]",
    "｛": "{",
    "｝": "}",
    "，": ",",
    "、": ",",
    "：": ":",
    "；": ";",
    "。": ".",
    "！": "!",
    "？": "?",
    "＝": "=",
    "＋": "+",
    "－": "-",
    "×": "*",
    "÷": "/",
    "／": "/",
    "＊": "*",
    "＜": "<",
    "＞": ">",
    "％": "%",
    "＆": "&",
    "｜": "|",
    "～": "~",
    "＠": "@",
    "＃": "#",
    "＾": "^",
    "｀": "`",
    "＄": "$",
    "　": " ",
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "〝": '"',
    "〞": '"',
    "「": '"',
    "」": '"',
    "『": '"',
    "』": '"',
    "＂": '"',
    "‘": "'",
    "’": "'",
    "‛": "'",
    "＇": "'",
}


def map_script_punct_char(char: str) -> str:
    return _CN_PUNCT_MAP.get(char, char)


def string_open_quote(line: str, column: int) -> Optional[str]:
    """返回光标处所在字符串的开引号（半角 ``"`` 或 ``'``），注释里返回 ``"#"``，
    不在字符串/注释里返回 ``None``。

    与 ``normalize_script_punctuation`` 对齐：全角引号按其映射的半角引号开/闭
    字符串（例如 ``“`` 开、``”`` 闭），这样编辑器判断“光标是否在字符串里”与
    半角化逻辑保持一致。
    """
    text = str(line or "")
    limit = max(0, min(int(column), len(text)))
    quote: Optional[str] = None  # 已开字符串的半角引号
    escape = False
    index = 0
    while index < limit:
        char = text[index]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif map_script_punct_char(char) == quote:
                quote = None
            index += 1
            continue
        if char == "#":
            return "#"
        mapped = map_script_punct_char(char)
        if mapped in {'"', "'"}:
            quote = mapped
        index += 1
    return quote


def cursor_in_string_or_comment(line: str, column: int) -> bool:
    return string_open_quote(line, column) is not None


_QUOTE_CHARS = frozenset(char for char, mapped in _CN_PUNCT_MAP.items() if mapped in {'"', "'"}) | {'"', "'"}


def normalize_script_punctuation(source: str) -> str:
    """把代码里的中文/全角标点换成英文标点；字符串和注释里的内容原样保留。

    用户要输入/记录的文本（"你好，世界。"）不能被改成半角，否则打进游戏里的字都变了。
    中文引号“ ”「 」可以用来开闭字符串，配对的那个也会被换成英文引号。
    """
    text = str(source or "")
    out: list[str] = []
    quote: Optional[str] = None
    escape = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if quote is not None:
            if escape:
                escape = False
                out.append(char)
            elif char == "\\":
                escape = True
                out.append(char)
            elif quote == '"""' or quote == "'''":
                if text.startswith(quote, index):
                    out.append(quote)
                    index += 3
                    quote = None
                    continue
                out.append(char)
            elif char in _QUOTE_CHARS and map_script_punct_char(char) == quote:
                out.append(quote)
                quote = None
            else:
                out.append(char)
            index += 1
            continue
        if char == "#":
            newline = text.find("\n", index)
            if newline < 0:
                out.append(text[index:])
                break
            out.append(text[index:newline])
            index = newline
            continue
        if text.startswith('"""', index) or text.startswith("'''", index):
            quote = text[index : index + 3]
            out.append(quote)
            index += 3
            continue
        mapped = map_script_punct_char(char)
        if mapped in {'"', "'"}:
            quote = mapped
        out.append(mapped)
        index += 1
    return "".join(out)


def translate_cn_script(source: str) -> str:
    """把中文关键字/内置名译成 Python，字符串和注释里不改。"""
    text = normalize_script_punctuation(str(source or ""))
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if text.startswith('"""', index) or text.startswith("'''", index):
            quote = text[index : index + 3]
            cursor = index + 3
            while cursor < length:
                if text.startswith(quote, cursor):
                    cursor += 3
                    break
                if text[cursor] == "\\" and cursor + 1 < length:
                    cursor += 2
                    continue
                cursor += 1
            out.append(text[index:cursor])
            index = cursor
            continue
        if char in {'"', "'"}:
            cursor = index + 1
            while cursor < length:
                if text[cursor] == "\\":
                    cursor += 2
                    continue
                if text[cursor] == char:
                    cursor += 1
                    break
                cursor += 1
            out.append(text[index:cursor])
            index = cursor
            continue
        if char == "#":
            newline = text.find("\n", index)
            if newline < 0:
                out.append(text[index:])
                break
            out.append(text[index:newline])
            index = newline
            continue
        if _is_ident_char(char):
            cursor = index + 1
            while cursor < length and _is_ident_char(text[cursor]):
                cursor += 1
            ident = text[index:cursor]
            nxt = _peek_ident(text, cursor)
            if ident in {"导入", "从", "作为", "尝试", "捕获", "最终", "抛出", "匿名", "使用", "就是"}:
                following = text[cursor:].lstrip()
                previous = text[:index].rstrip()
                is_field = previous.endswith(".") or (following.startswith("=") and not following.startswith("=="))
                out.append(ident if is_field else _CN_IDENT_MAP[ident])
            elif ident in _BUILTIN_CALLS:
                # 内置名也可能是命令的关键字参数或结果字段（例如 长度=64）。
                # 只翻译独立的函数调用，不能改写这些参数名和属性名。
                following = text[cursor:].lstrip()
                previous = text[:index].rstrip()
                is_call = following.startswith("(") and not previous.endswith(".")
                out.append(_CN_IDENT_MAP.get(ident, ident) if is_call else ident)
            elif ident == "是":
                out.append("is" if nxt in {"空", "None"} else "==")
            elif ident == "不是":
                out.append("is not" if nxt in {"空", "None"} else "not")
            else:
                out.append(_CN_IDENT_MAP.get(ident, ident))
            index = cursor
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _syntax_error_text(exc: SyntaxError) -> str:
    message = str(exc.msg or "写法不对")
    for english, chinese in _SYNTAX_CN:
        if english in message:
            return chinese
    return message


def parse_script(source: str) -> ast.AST:
    return ast.parse(translate_cn_script(str(source or "")))


_PLACEHOLDER_NAMES = frozenset(
    {
        "条件",
        "次数",
        "图片",
        "模型",
        "文件",
        "等待",
        "颜色",
        "文本",
        "目标",
        "名称",
        "说明",
        "内容",
        "编号",
        "进程号",
        "程序",
        "标题",
        "类名",
        "宽",
        "高",
        "x",
        "y",
        "自动化ID",
        "名字",
        "值",
        "默认值",
        "秒",
        "动作",
        "按键",
        "步数",
        "步长",
        "类别",
        "横向",
        "纵向",
        "边距",
        "自己",
        "点1",
        "点2",
        "名字",
        "角度",
        "下限",
        "上限",
        "对象",
        "值1",
        "值2",
        "起点",
        "终点",
        "宽",
        "高",
        "双击",
        "偏移x",
        "偏移y",
        "随机",
        "随机横坐标",
        "随机纵坐标",
        "区域",
        "大漠内存",
        "大漠汇编",
        "键",
        "阈值",
        "策略",
        "方向",
        "超时",
        "间隔",
        "偏色",
        "最多",
        "毫秒",
        "片段",
        "旧",
        "新",
        "分隔符",
        "字数",
        "x",
        "y",
        "x1",
        "y1",
        "x2",
        "y2",
    }
)
_PLACEHOLDER_HINTS = {
    "文件": "用资源栏导入，或填写当前工程内该命令所需的文件路径",
    "等待": "写成 真 或 假。真表示执行完成后再往下，假表示启动后继续",
    "图片": "用工具栏「截图」选图，或写成 \"确定.png\"",
    "图片2": "第二张图。多张图并行识别，按顺序取第一张命中，阈值仍写 阈值=",
    "模型": "写成 onnx 路径，例如 \"yolo/xxx.onnx\"",
    "颜色": "用「取色」，或写成 \"255,0,0\"",
    "目标": "写成 图，或 \"确定\"",
    "条件": "插入找图/检测，或写成 图",
    "文本": "写成要输入的文字，例如 \"你好\"",
    "内容": "写成要记录的内容",
    "说明": "写成失败原因，例如 \"没找到\"",
    "名称": "写成控件名，或用「拾取元素」",
    "秒": "写成等待秒数，例如 0.3；随机时长写成 (0.2, 0.6)",
    "连发": "写成 真 或 假。真是按住时继续出字，假是只按住不连发",
    "动作": "写成 \"按下\" 或 \"松开\"",
    "按键": "写成 \"Ctrl+C\" 或 \"Enter\"",
    "次数": "写成数字，或 变量.获取(\"次数\", 3)",
    "名字": "写成变量名，例如 \"次数\"",
    "编号": "写成卡片 ID，例如 3",
    "类别": "写成这个模型里的类别名，例如 \"敌人\"。不写就认全部类",
    "横向": "写成 0 到 1，0 是左边、1 是右边",
    "纵向": "写成 0 到 1，0 是顶、1 是底。脚下常用 0.85",
    "边距": "写成离边多少像素，例如 2",
    "自己": "写成你赋过值的检测结果，例如 自己",
    "点1": "写成一个检测结果，或四个数字 距离(x1, y1, x2, y2) / 角度(x1, y1, x2, y2)",
    "点2": "写成另一个检测结果或坐标点",
    "角度": "写成度数，例如 角度(自己, 目标)",
    "下限": "写成最小允许值",
    "上限": "写成最大允许值",
    "策略": "写成 \"最近\"、\"最大\" 或 \"置信度最高\"",
    "对象": "写成要测量的值，例如 文字.内容",
    "值1": "写成数字或变量",
    "值2": "写成数字或变量",
    "起点": "写成起始数字",
    "终点": "写成结束数字",
    "宽": "写成宽度数字",
    "高": "写成高度数字",
    "双击": "写成 真 或 假",
    "偏移x": "写成像素，正数向右",
    "偏移y": "写成像素，正数向下",
    "随机": "写成随机半径，例如 5。和偏移一起写时先固定偏移再抖",
    "区域": "用工具栏「框选区域」写入 区域.设置，或写成 (横坐标, 纵坐标, 宽, 高) / 区域名",
    "键": "写成 \"左键\" 或 \"右键\"",
    "阈值": "写成 0 到 1 的小数，例如 0.8",
    "方向": "写成 \"向下\" 或 \"向上\"",
    "随机横坐标": "写成 X 随机范围，例如 5",
    "随机纵坐标": "写成 Y 随机范围，例如 5",
    "x": "用「取坐标」，或写成数字",
    "y": "用「取坐标」，或写成数字",
    "x1": "用「取坐标」，或写成数字",
    "y1": "用「取坐标」，或写成数字",
    "x2": "用「取坐标」，或写成数字",
    "y2": "用「取坐标」，或写成数字",
}


def unfilled_placeholder_names(source: str) -> list:
    try:
        tree = parse_script(source)
    except SyntaxError:
        return []
    assigned = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            assigned.add(node.id)
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            assigned.add(node.target.id)
        if isinstance(node, ast.FunctionDef):
            assigned.add(node.name)
            for arg in list(node.args.args) + list(getattr(node.args, "posonlyargs", []) or []) + list(node.args.kwonlyargs):
                assigned.add(arg.arg)
    call_funcs = set()
    attr_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            call_funcs.add(id(node.func))
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            attr_roots.add(id(node.value))
    found = []
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        if id(node) in call_funcs or id(node) in attr_roots:
            continue
        if node.id in assigned or node.id not in _PLACEHOLDER_NAMES or node.id in seen:
            continue
        seen.add(node.id)
        found.append(node.id)
    return found


def unfilled_placeholder_error(source: str) -> str:
    names = unfilled_placeholder_names(source)
    if not names:
        return ""
    name = names[0]
    hint = _PLACEHOLDER_HINTS.get(name, "把占位名改成实际值")
    extra = f"；还有 {'、'.join(names[1:])}" if len(names) > 1 else ""
    return f"还没填写参数：{name}{extra}。{hint}"


_RESERVED_VAR_NAMES = ("当", "在", "是", "真", "假", "空", "子程序", "函数")


def _reserved_name_warnings(source: str) -> list:
    import re

    found = []
    text = str(source or "")
    for name in _RESERVED_VAR_NAMES:
        if re.search(rf"(?<![\w\u4e00-\u9fff]){re.escape(name)}\s*=", text):
            found.append(f"不要用「{name}」当变量名")
    return found


def script_warnings(source: str) -> list:
    found: list = list(_reserved_name_warnings(source))
    try:
        tree = parse_script(source)
    except SyntaxError:
        return found
    placeholder = unfilled_placeholder_error(source)
    if placeholder:
        found.append(placeholder)

    def scan(body: list) -> None:
        for index, stmt in enumerate(body):
            name = _is_exit_stmt(stmt)
            if name:
                rest = [item for item in body[index + 1 :] if not isinstance(item, ast.Pass)]
                if rest:
                    found.append(f"第{stmt.lineno}行：{name} 后面的命令不会执行")
            if isinstance(stmt, ast.FunctionDef):
                scan(stmt.body)
                continue
            if isinstance(stmt, ast.Try):
                scan(stmt.body)
                scan(stmt.orelse)
                scan(stmt.finalbody)
                for handler in stmt.handlers:
                    scan(handler.body)
                continue
            if isinstance(stmt, (ast.If, ast.For, ast.While)):
                if isinstance(stmt, (ast.For, ast.While)):
                    _warn_loop_outcomes(stmt.body, found)
                scan(stmt.body)
                scan(stmt.orelse)

    scan(tree.body)
    return found


def _warn_loop_outcomes(body: list, found: list) -> None:
    for stmt in body:
        name = _is_outcome_call(stmt)
        if name:
            found.append(f"第{stmt.lineno}行：{name}() 写在循环里会立刻结束整段脚本，剩下的轮次不会跑")
            continue
        if isinstance(stmt, ast.If):
            _warn_loop_outcomes(stmt.body, found)
            _warn_loop_outcomes(stmt.orelse, found)


class _ForCountWrap(ast.NodeTransformer):
    """`循环 i 在 6:` 这种次数写法译成 `for i in 6` 后补成可迭代的次数。"""

    def visit_For(self, node):
        self.generic_visit(node)
        node.iter = ast.Call(
            func=ast.Name(id="__iter_count", ctx=ast.Load()),
            args=[node.iter],
            keywords=[],
        )
        ast.copy_location(node.iter, node)
        ast.fix_missing_locations(node.iter)
        return node


class _GuardInsert(ast.NodeTransformer):
    @staticmethod
    def _guard_ref() -> ast.Subscript:
        return ast.Name(id="_lca_guard", ctx=ast.Load())

    @classmethod
    def _guard_call(cls) -> ast.Call:
        return ast.Call(
            func=cls._guard_ref(),
            args=[],
            keywords=[],
        )

    def visit(self, node):
        node = super().visit(node)
        if isinstance(node, ast.stmt) and not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            guard_call = ast.Expr(value=self._guard_call())
            ast.copy_location(guard_call, node)
            return [guard_call, node]
        return node

    def visit_For(self, node):
        self.generic_visit(node)
        node.body = [self._loop_guard(node), *(node.body or [ast.Pass()])]
        return node

    def visit_While(self, node):
        self.generic_visit(node)
        node.body = [self._loop_guard(node), *(node.body or [ast.Pass()])]
        return node

    def _loop_guard(self, node):
        stmt = ast.Expr(
            value=ast.Call(
                func=ast.Attribute(
                    value=self._guard_ref(),
                    attr="loop",
                    ctx=ast.Load(),
                ),
                args=[],
                keywords=[],
            )
        )
        ast.copy_location(stmt, node)
        ast.fix_missing_locations(stmt)
        return stmt


def _region_payload(name: str, rect: Tuple[int, int, int, int], ok: bool = True) -> Dict[str, Any]:
    left, top, width, height = rect
    return {
        "ok": ok,
        "kind": "region",
        "name": name,
        "x": left,
        "y": top,
        "width": width,
        "height": height,
        "x1": left,
        "y1": top,
        "x2": left + width,
        "y2": top + height,
    }


class _RegionApi:
    def __init__(self, host: CommandHost) -> None:
        self._host = host

    def 设置(self, 名字: Any, x: Any = None, y: Any = None, 宽: Any = None, 高: Any = None) -> ScriptResult:
        from task_workflow.script_commands import _as_region

        name = str(名字 if 名字 is not None else "").strip()
        if not name:
            raise ValueError("区域名不能为空")
        if isinstance(x, (tuple, list)) and y is None and 宽 is None and 高 is None:
            rect = _as_region(x)
        else:
            rect = _as_region((x, y, 宽, 高))
        if rect is None:
            raise ValueError("区域.设置要写名字和 (x, y, 宽, 高)")
        with self._host._regions_lock:
            self._host._regions[name] = rect
        return ScriptResult(_region_payload(name, rect))

    def 获取(self, 名字: Any) -> ScriptResult:
        name = str(名字 if 名字 is not None else "").strip()
        with self._host._regions_lock:
            rect = self._host._regions.get(name) if name else None
        if rect is None:
            return ScriptResult({"ok": False, "kind": "region", "name": name})
        return ScriptResult(_region_payload(name, rect))

    def 存在(self, 名字: Any) -> bool:
        name = str(名字 if 名字 is not None else "").strip()
        if not name:
            return False
        with self._host._regions_lock:
            return name in self._host._regions

    def 删除(self, 名字: Any) -> bool:
        name = str(名字 if 名字 is not None else "").strip()
        if not name:
            return False
        with self._host._regions_lock:
            return self._host._regions.pop(name, None) is not None

    def 列表(self) -> ScriptResult:
        with self._host._regions_lock:
            items = [_region_payload(name, rect) for name, rect in self._host._regions.items()]
        return ScriptResult({"ok": True, "kind": "region", "items": items})


class _VarsApi:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store
        self._vars: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def 获取(self, 名字: Any, 默认值: Any = None) -> Any:
        key = normalize_var_name(名字)
        with self._lock:
            return self._vars.get(key, 默认值)

    def 设置(self, 名字: Any, 值: Any) -> Any:
        key = normalize_var_name(名字)
        stored = normalize_var_value(值)
        with self._lock:
            self._vars[key] = stored
        return stored

    def 增加(self, 名字: Any, 步长: Any = 1) -> Any:
        key = normalize_var_name(名字)
        with self._lock:
            current = self._vars.get(key, 0)
            next_value = add_numeric_values(current, 步长)
            self._vars[key] = next_value
            return next_value

    def 存在(self, 名字: Any) -> bool:
        key = normalize_var_name(名字)
        with self._lock:
            return key in self._vars

    def 删除(self, 名字: Any) -> bool:
        key = normalize_var_name(名字)
        missing = object()
        with self._lock:
            return self._vars.pop(key, missing) is not missing

    def 全局获取(self, 名字: Any, 默认值: Any = None) -> Any:
        return self._store.get_var(名字, 默认值)

    def 全局设置(self, 名字: Any, 值: Any) -> Any:
        return self._store.set_var(名字, 值)

    def 全局增加(self, 名字: Any, 步长: Any = 1) -> Any:
        return self._store.inc_var(名字, 步长)

    def 全局存在(self, 名字: Any) -> bool:
        return self._store.has_var(名字)

    def 全局删除(self, 名字: Any) -> bool:
        return self._store.delete_var(名字)


class _StoreView:
    def __init__(self, store: RuntimeStore, kind: Optional[str] = None) -> None:
        self._store = store
        self._kind = kind

    def __bool__(self) -> bool:
        return bool(self._store.last(self._kind).get("ok"))

    def __getattr__(self, name: str) -> Any:
        return _AttrView(self._store.last(self._kind)).__getattr__(name)

    def __getitem__(self, key: Any) -> Any:
        return _AttrView(self._store.last(self._kind)).__getitem__(key)


class _AttrView:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise ScriptError("禁止访问该属性")
        key = FIELD_ALIASES.get(name, name)
        if isinstance(self._payload, dict) and key in self._payload:
            value = self._payload[key]
            return value if key == "outputs" else _wrap(value)
        raise ScriptError(f"没有字段: {name}")

    def __getitem__(self, key: Any) -> Any:
        if isinstance(self._payload, dict):
            value = self._payload[key]
            return value if key == "outputs" else _wrap(value)
        if isinstance(self._payload, list):
            return _wrap(self._payload[int(key)])
        raise ScriptError("该值不支持下标")


class _CardView:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    def __getitem__(self, card_id: Any) -> _AttrView:
        return _AttrView(self._store.card_result(card_id))


class _CallableLast:
    def __init__(self, callback, store: RuntimeStore, kind: str, host: Any = None) -> None:
        self._callback = callback
        self._store = store
        self._kind = kind
        self._host = host

    def __call__(self, *args, **kwargs):
        return self._callback(*args, **kwargs)

    def _payload(self) -> Dict[str, Any]:
        if self._host is not None:
            latest = self._host.latest(self._kind)
            if latest is not None:
                return latest
        return self._store.last(self._kind)

    def _result(self) -> ScriptResult:
        return ScriptResult(self._payload())

    def __bool__(self) -> bool:
        return bool(self._payload().get("ok"))

    def __len__(self) -> int:
        return len(self._result())

    def __iter__(self):
        return iter(self._result())

    def __getitem__(self, key: Any) -> Any:
        return self._result()[key]

    def __getattr__(self, name: str) -> Any:
        if name in _RESULT_METHODS:
            return getattr(self._result(), name)
        return _AttrView(self._payload()).__getattr__(name)


def _wrap(value: Any) -> Any:
    if isinstance(value, dict):
        return ScriptResult(value)
    return value


class _CommandSlot:
    """命令可调用；同名赋值只记住结果，不把命令冲掉。"""

    def __init__(self, callback: Any) -> None:
        self._callback = callback
        self._bound = None

    def bind(self, value: Any) -> None:
        self._bound = value

    def __call__(self, *args, **kwargs):
        result = self._callback(*args, **kwargs)
        self._bound = result
        return result

    def __bool__(self) -> bool:
        if self._bound is not None:
            return bool(self._bound)
        callback = self._callback
        try:
            return bool(callback)
        except Exception:
            return True

    def _value_for_container(self) -> Any:
        if self._bound is None:
            raise ScriptError("请先调用命令并保存结果，再读取长度、项目或字段")
        return self._bound

    def __len__(self) -> int:
        return len(self._value_for_container())

    def __iter__(self):
        return iter(self._value_for_container())

    def __getitem__(self, key: Any) -> Any:
        return self._value_for_container()[key]

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if self._bound is not None:
            return getattr(self._bound, name)
        callback = self._callback
        try:
            return getattr(callback, name)
        except AttributeError:
            raise ScriptError(f"没有字段: {name}") from None


class _ScriptNamespace(dict):
    pass

    def install_command(self, name: str, callback: Any) -> None:
        dict.__setitem__(self, name, callback if isinstance(callback, _CommandSlot) else _CommandSlot(callback))


def validate_script(source: str) -> None:
    text = str(source or "")
    try:
        parse_script(text)
    except SyntaxError as exc:
        raise ScriptError(f"语法错误: {_syntax_error_text(exc)}", lineno=getattr(exc, "lineno", None)) from exc


def _script_lineno(exc: BaseException) -> Optional[int]:
    line = getattr(exc, "lineno", None)
    try:
        if line:
            return int(line)
    except Exception:
        line = None
    tb = getattr(exc, "__traceback__", None)
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == "<script>":
            line = tb.tb_lineno
        tb = tb.tb_next
    return int(line) if line else None


def _raise_script_error(message: str, exc: Optional[BaseException] = None) -> None:
    raise ScriptError(message, lineno=_script_lineno(exc) if exc is not None else None) from exc




def clipboard_get() -> str:
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                return str(win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT) or "")
        finally:
            win32clipboard.CloseClipboard()
    except Exception as exc:
        raise ScriptError(f"剪贴板读取失败: {exc}") from exc
    return ""


def clipboard_set(text: Any) -> str:
    value = "" if text is None else str(text)
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(value, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    except Exception as exc:
        raise ScriptError(f"剪贴板写入失败: {exc}") from exc
    return value


class _DmMemoryView:
    def __init__(self, host: CommandHost) -> None: self._host = host
    def 模块基址(self, 模块): return self._host.大漠内存_模块基址(模块)
    def 模块大小(self, 模块): return self._host.大漠内存_模块大小(模块)
    def 读取整数(self, 地址, 类型=0): return self._host.大漠内存_读取整数(地址, 类型)
    def 读取单精度(self, 地址): return self._host.大漠内存_读取单精度(地址)
    def 读取双精度(self, 地址): return self._host.大漠内存_读取双精度(地址)
    def 读取文本(self, 地址, 类型, 长度): return self._host.大漠内存_读取文本(地址, 类型, 长度)
    def 读取数据(self, 地址, 长度): return self._host.大漠内存_读取数据(地址, 长度)
    def 写入整数(self, 地址, 类型, 值): return self._host.大漠内存_写入整数(地址, 类型, 值)
    def 写入单精度(self, 地址, 值): return self._host.大漠内存_写入单精度(地址, 值)
    def 写入双精度(self, 地址, 值): return self._host.大漠内存_写入双精度(地址, 值)
    def 写入文本(self, 地址, 类型, 值): return self._host.大漠内存_写入文本(地址, 类型, 值)
    def 写入数据(self, 地址, 数据): return self._host.大漠内存_写入数据(地址, 数据)
    def 搜索整数(self, 范围, 最小值, 最大值, 类型=0): return self._host.大漠内存_搜索整数(范围, 最小值, 最大值, 类型)
    def 搜索单精度(self, 范围, 最小值, 最大值): return self._host.大漠内存_搜索单精度(范围, 最小值, 最大值)
    def 搜索双精度(self, 范围, 最小值, 最大值): return self._host.大漠内存_搜索双精度(范围, 最小值, 最大值)
    def 搜索文本(self, 范围, 文本, 类型): return self._host.大漠内存_搜索文本(范围, 文本, 类型)
    def 搜索数据(self, 范围, 数据): return self._host.大漠内存_搜索数据(范围, 数据)
    def 申请(self, 地址, 大小, 类型): return self._host.大漠内存_申请(地址, 大小, 类型)
    def 释放(self, 地址): return self._host.大漠内存_释放(地址)
    def 清理(self): return self._host.大漠内存_清理()


class _DmAsmView:
    def __init__(self, host: CommandHost) -> None: self._host = host
    def 添加(self, 指令): return self._host.大漠汇编_添加(指令)
    def 清空(self): return self._host.大漠汇编_清空()
    def 调用(self, 模式): return self._host.大漠汇编_调用(模式)
    def 基址调用(self, 模式, 基址): return self._host.大漠汇编_基址调用(模式, 基址)
    def 超时(self, 毫秒, 参数): return self._host.大漠汇编_超时(毫秒, 参数)


class _PerformanceView:
    """Read-only process/runtime metrics for long-running scripts."""

    def __init__(self, host) -> None:
        self._host = host

    def 快照(self) -> ScriptResult:
        payload: Dict[str, Any] = {
            "ok": True,
            "kind": "performance",
            "platform": os.name,
            "python": platform.python_version(),
        }
        try:
            import psutil

            process = psutil.Process(os.getpid())
            memory = process.memory_info()
            payload.update(
                {
                    "available": True,
                    "pid": int(process.pid),
                    "rss_bytes": int(memory.rss),
                    "rss_mb": round(float(memory.rss) / (1024 * 1024), 3),
                    "cpu_percent": float(process.cpu_percent(interval=0.0)),
                    "threads": int(process.num_threads()),
                }
            )
        except Exception as exc:
            payload.update({"ok": False, "available": False, "error": str(exc)})
        try:
            user_threads = getattr(self._host, "_user_threads", {}) or {}
            watch_threads = getattr(self._host, "_watch_threads", {}) or {}
            payload["script_threads"] = sum(1 for thread in user_threads.values() if thread and thread.is_alive())
            payload["watch_threads"] = sum(1 for thread in watch_threads.values() if thread and thread.is_alive())
        except Exception:
            payload["script_threads"] = 0
            payload["watch_threads"] = 0
        try:
            from services.screenshot_pool import get_screenshot_stats, get_screenshot_worker_limit

            payload["screenshot_workers"] = get_screenshot_stats()
            payload["screenshot_worker_limit"] = int(get_screenshot_worker_limit())
        except Exception as exc:
            payload["screenshot_workers"] = {"available": False, "error": str(exc)}
        return ScriptResult(payload)


class _DataApi:
    """脚本数据接口，直接使用调用方提供的文件路径。"""

    @classmethod
    def _row_limit(cls, value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("最多必须是大于 0 的整数")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("最多必须是大于 0 的整数") from exc
        if not math.isfinite(number) or not number.is_integer():
            raise ValueError("最多必须是大于 0 的整数")
        limit = int(number)
        if limit < 1:
            raise ValueError("最多必须是大于 0 的整数")
        return limit

    def _path(self, name: Any) -> str:
        raw = str(name or "").replace("\\", "/").strip()
        if not raw:
            raise ValueError("数据文件路径不能为空")
        return os.path.abspath(os.path.expanduser(raw))

    def 读取(self, 文件名: Any, 默认值: Any = "") -> str:
        path = self._path(文件名)
        try:
            with open(path, "rb") as handle:
                content = handle.read()
            return content.decode("utf-8")
        except FileNotFoundError:
            return _text(默认值)

    def 写入(self, 文件名: Any, 内容: Any) -> str:
        path = self._path(文件名)
        text = str(内容 if 内容 is not None else "")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        import tempfile

        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(path), delete=False) as handle:
                temporary = handle.name
                handle.write(text)
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.remove(temporary)
        return text

    def JSON读取(self, 文件名: Any, 默认值: Any = None) -> Any:
        path = self._path(文件名)
        try:
            with open(path, "rb") as handle:
                text = handle.read().decode("utf-8")
        except FileNotFoundError:
            return 默认值
        return script_json_parse(text)

    def JSON写入(self, 文件名: Any, 对象: Any) -> str:
        return self.写入(文件名, script_json_dump(对象))

    def INI读取(self, 文件名: Any, 节: Any, 键: Any, 默认值: Any = "") -> str:
        import configparser
        parser = configparser.ConfigParser()
        path = self._path(文件名)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                parser.read_file(handle)
        except FileNotFoundError:
            return _text(默认值)
        return parser.get(str(节), str(键), fallback=_text(默认值))

    def INI写入(self, 文件名: Any, 节: Any, 键: Any, 值: Any) -> str:
        import configparser
        parser = configparser.ConfigParser()
        path = self._path(文件名)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as handle:
                parser.read_file(handle)
        section, key = str(节).strip(), str(键).strip()
        if not section or not key:
            raise ValueError("INI 节和键不能为空")
        if not parser.has_section(section):
            parser.add_section(section)
        parser.set(section, key, str(值 if 值 is not None else ""))
        from io import StringIO
        output = StringIO()
        parser.write(output)
        return self.写入(文件名, output.getvalue())

    def CSV读取(self, 文件名: Any, 标题行: Any = True, 最多: Any = None) -> list:
        import csv
        path = self._path(文件名)
        limit = self._row_limit(最多)
        field_limit = csv.field_size_limit()
        csv.field_size_limit((1 << 31) - 1)
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as handle:
                if _as_bool(标题行):
                    reader = csv.DictReader(handle)
                    rows = []
                    for row in reader:
                        if limit is not None and len(rows) >= limit:
                            raise ValueError(f"CSV 结果行数超过最多 {limit} 行")
                        rows.append(row)
                else:
                    reader = csv.reader(handle)
                    rows = []
                    for row in reader:
                        if limit is not None and len(rows) >= limit:
                            raise ValueError(f"CSV 结果行数超过最多 {limit} 行")
                        rows.append(row)
        except FileNotFoundError:
            return []
        finally:
            csv.field_size_limit(field_limit)
        return rows

    def SQLite查询(self, 文件名: Any, SQL: Any, 参数: Any = (), 最多: Any = None) -> list:
        import sqlite3
        statement = str(SQL or "").strip()
        if not statement:
            raise ValueError("SQLite 语句不能为空")
        keyword = statement.split(None, 1)[0].upper()
        if keyword not in {"SELECT", "PRAGMA", "WITH"}:
            raise ValueError("SQLite 只允许 SELECT、PRAGMA 或 WITH 查询")
        limit = self._row_limit(最多)
        values = tuple(参数) if isinstance(参数, (list, tuple)) else (() if 参数 is None else (参数,))
        path = self._path(文件名)
        try:
            from pathlib import Path
            uri = Path(path).as_uri() + "?mode=ro"
            from contextlib import closing
            with closing(sqlite3.connect(uri, uri=True)) as conn:
                with closing(conn.execute(statement, values)) as cursor:
                    columns = [item[0] for item in cursor.description or ()]
                    rows = []
                    if columns:
                        for row in cursor:
                            if limit is not None and len(rows) >= limit:
                                raise ValueError(f"SQLite 结果行数超过最多 {limit} 行")
                            rows.append(dict(zip(columns, row)))
        except sqlite3.Error as exc:
            raise ValueError(f"SQLite 查询失败: {exc}") from exc
        return rows

    def 存在(self, 文件名: Any) -> bool:
        return os.path.isfile(self._path(文件名))

    def 删除(self, 文件名: Any) -> bool:
        try:
            os.remove(self._path(文件名))
            return True
        except FileNotFoundError:
            return False


class _InputDeviceView:
    """受控只读游戏杆状态接口（WinMM）；无设备或非 Windows 返回空结果。"""

    _JOY_RETURNALL = 0xFF
    _JOYERR_NOERROR = 0

    def __init__(self, host=None):
        self._host = host

    def _winmm(self):
        import ctypes
        if os.name != "nt":
            return None
        try:
            dll = ctypes.windll.winmm
            dll.joyGetNumDevs.restype = ctypes.c_uint
            try:
                dll.joyGetPosEx.argtypes = [ctypes.c_uint, ctypes.c_void_p]
                dll.joyGetPosEx.restype = ctypes.c_uint
            except Exception:
                pass
            return dll
        except Exception:
            return None

    @staticmethod
    def _joy_info_type():
        import ctypes
        class JoyInfoEx(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32),
                ("dwXpos", ctypes.c_uint32), ("dwYpos", ctypes.c_uint32), ("dwZpos", ctypes.c_uint32),
                ("dwRpos", ctypes.c_uint32), ("dwUpos", ctypes.c_uint32), ("dwVpos", ctypes.c_uint32),
                ("dwButtons", ctypes.c_uint32), ("dwButtonNumber", ctypes.c_uint32),
                ("dwPOV", ctypes.c_uint32), ("dwReserved1", ctypes.c_uint32), ("dwReserved2", ctypes.c_uint32),
            ]
        return JoyInfoEx

    def _read(self, dll, index: int):
        import ctypes
        info = self._joy_info_type()()
        info.dwSize = ctypes.sizeof(info)
        info.dwFlags = self._JOY_RETURNALL
        try:
            code = int(dll.joyGetPosEx(index, ctypes.byref(info)))
        except Exception as exc:
            return None, str(exc)
        return (info if code == self._JOYERR_NOERROR else None), ("" if code == self._JOYERR_NOERROR else f"winmm:{code}")

    @staticmethod
    def _index(value: Any) -> int:
        if isinstance(value, bool):
            raise ValueError("输入设备编号必须是整数")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("输入设备编号必须是整数") from exc
        if not number.is_integer():
            raise ValueError("输入设备编号必须是整数")
        index = int(number)
        if index < 0 or index >= 16:
            raise ValueError("输入设备编号必须在 0 到 15 之间")
        return index

    def 枚举(self) -> list:
        dll = self._winmm()
        if dll is None:
            return []
        result = []
        for index in range(min(16, int(dll.joyGetNumDevs() or 0))):
            info, _ = self._read(dll, index)
            if info is not None:
                result.append({"id": index, "name": f"joystick{index}", "buttons": int(info.dwButtons), "pov": int(info.dwPOV), "x": int(info.dwXpos), "y": int(info.dwYpos), "z": int(info.dwZpos), "connected": True})
        return result

    def 能力(self) -> ScriptResult:
        """Report installed device protocols without probing or injecting input."""
        winmm_available = self._winmm() is not None
        hid_available = self._hid() is not None
        try:
            import vgamepad  # type: ignore
            virtual_gamepad_available = True
        except Exception:
            virtual_gamepad_available = False
        return ScriptResult({
            "ok": True,
            "kind": "input_device_capabilities",
            "winmm": bool(winmm_available),
            "hidapi": bool(hid_available),
            "virtual_gamepad": bool(virtual_gamepad_available),
            "can_read_joystick": bool(winmm_available),
            "can_read_hid": bool(hid_available),
            "can_inject": False,
        })

    @staticmethod
    def _hid():
        try:
            import hid
            return hid
        except Exception:
            return None

    def HID枚举(self) -> ScriptResult:
        hid = self._hid()
        if hid is None:
            return ScriptResult({"ok": False, "kind": "hid", "available": False, "devices": [], "error": "hidapi 未安装"})
        try:
            raw = hid.enumerate()
        except Exception as exc:
            return ScriptResult({"ok": False, "kind": "hid", "available": True, "devices": [], "error": str(exc)})
        devices = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            devices.append({key: item.get(key) for key in ("path", "vendor_id", "product_id", "serial_number", "manufacturer_string", "product_string", "usage_page", "usage")})
        return ScriptResult({"ok": True, "kind": "hid", "available": True, "devices": devices})

    def HID读取(self, 路径: Any, 长度: Any = 64, 超时: Any = 1000) -> ScriptResult:
        length = integer_parameter(长度, "HID 长度", minimum=1, maximum=4096)
        timeout = integer_parameter(超时, "HID 超时（毫秒）", minimum=0, maximum=60000)
        if not 路径:
            raise ValueError("HID 路径不能为空")
        hid = self._hid()
        if hid is None:
            return ScriptResult({"ok": False, "kind": "hid_read", "available": False, "data": [], "error": "hidapi 未安装"})
        path = 路径
        device = None
        try:
            device = hid.device()
            device.open_path(path)
            if timeout == 0:
                device.set_nonblocking(True)
            data = list(device.read(length, timeout))
            return ScriptResult({"ok": bool(data), "kind": "hid_read", "available": True, "data": data, "bytes": len(data)})
        except Exception as exc:
            return ScriptResult({"ok": False, "kind": "hid_read", "available": True, "data": [], "error": str(exc)})
        finally:
            if device is not None:
                try:
                    device.close()
                except Exception as exc:
                    raise RuntimeError(f"HID 设备关闭失败，释放状态未知: {exc}") from exc

    def HID写入(self, 路径: Any, 数据: Any) -> ScriptResult:
        path = 路径
        if not path:
            raise ValueError("HID 路径不能为空")
        if isinstance(数据, (bytes, bytearray)):
            payload = bytes(数据)
        elif isinstance(数据, (list, tuple)):
            try:
                values = []
                for item in 数据:
                    values.append(integer_parameter(item, "HID 数据字节"))
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("HID 数据必须是字节列表") from exc
            if any(value < 0 or value > 255 for value in values):
                raise ValueError("HID 数据字节必须在 0 到 255 之间")
            payload = bytes(values)
        else:
            raise TypeError("HID 数据必须是字节列表")
        if not payload or len(payload) > 4096:
            raise ValueError("HID 数据长度必须在 1 到 4096 字节之间")
        hid = self._hid()
        if hid is None:
            return ScriptResult({"ok": False, "kind": "hid_write", "available": False, "bytes": 0, "error": "hidapi 未安装"})
        device = None
        try:
            device = hid.device(); device.open_path(path)
            written = int(device.write(payload))
            return ScriptResult({"ok": written == len(payload), "kind": "hid_write", "available": True, "bytes": written})
        except Exception as exc:
            return ScriptResult({"ok": False, "kind": "hid_write", "available": True, "bytes": 0, "error": str(exc)})
        finally:
            if device is not None:
                try:
                    device.close()
                except Exception as exc:
                    raise RuntimeError(f"HID 设备关闭失败，释放状态未知: {exc}") from exc

    def 状态(self, 设备: Any = 0) -> ScriptResult:
        dll = self._winmm()
        index = self._index(设备)
        if dll is None:
            return ScriptResult({"ok": False, "kind": "joystick", "id": index, "connected": False})
        info, error = self._read(dll, index)
        if info is None:
            return ScriptResult({"ok": False, "kind": "joystick", "id": index, "connected": False, "error": error})
        return ScriptResult({"ok": True, "kind": "joystick", "id": index, "connected": True, "x": int(info.dwXpos), "y": int(info.dwYpos), "z": int(info.dwZpos), "buttons": int(info.dwButtons), "pov": int(info.dwPOV)})

    def 等待按钮(self, 按钮: Any, 设备: Any = 0, 按下: Any = True, 超时: Any = 30, 间隔: Any = 0.05) -> ScriptResult:
        button = integer_parameter(按钮, "手柄按钮编号", minimum=1, maximum=32)
        timeout = finite_seconds(超时, "手柄超时")
        pause = finite_seconds(间隔, "手柄间隔", positive=True)
        device_index = self._index(设备)
        deadline = time.monotonic() + timeout
        mask = 1 << (button - 1)
        desired = _as_bool(按下)
        while True:
            if self._host is not None:
                if self._host.should_stop():
                    raise ScriptError("手柄按钮等待已停止")
                self._host._wait_if_paused()
            if self._winmm() is None:
                return ScriptResult({"ok": False, "kind": "joystick_button", "id": device_index, "button": button, "pressed": False, "connected": False})
            state = self.状态(device_index)
            if not state or not bool(getattr(state, "connected", False)):
                return ScriptResult({
                    "ok": False,
                    "kind": "joystick_button",
                    "id": device_index,
                    "button": button,
                    "pressed": False,
                    "connected": False,
                    "error": "输入设备未连接",
                })
            pressed = bool(int(getattr(state, "buttons", 0) or 0) & mask)
            if pressed == desired:
                return ScriptResult({"ok": True, "kind": "joystick_button", "id": device_index, "button": button, "pressed": pressed, "connected": bool(getattr(state, "connected", False))})
            if self._host is not None and self._host.should_stop():
                raise ScriptError("手柄按钮等待已停止")
            if time.monotonic() >= deadline:
                return ScriptResult({"ok": False, "kind": "joystick_button", "id": device_index, "button": button, "pressed": pressed, "connected": bool(getattr(state, "connected", False))})
            remaining = max(0.0, deadline - time.monotonic())
            if self._host is not None:
                self._host._sleep_interruptible(min(pause, remaining))
            else:
                time.sleep(min(pause, remaining))


class _WindowNotFound(ValueError):
    """查询确定窗口不存在；参数错误和查询失败不使用此类型。"""


class _WindowView:
    def __init__(self, host) -> None:
        self._host = host

    def 设置分辨率(self, *args, 报错=True):
        return self._host.设置分辨率(*args, 报错=报错)

    @staticmethod
    def _win32():
        try:
            import win32con
            import win32gui
            import win32process
        except Exception as exc:
            raise ScriptError(f"窗口 API 不可用: {exc}") from exc
        return win32con, win32gui, win32process

    def _resolve_hwnd(self, target: Any = None) -> int:
        """Resolve a script window argument without allowing arbitrary handles by accident."""
        _, win32gui, _ = self._win32()
        if target is None or str(target).strip() in {"", "当前", "绑定"}:
            target = self._host.context.get("target_hwnd")
        if isinstance(target, ScriptResult):
            target = target._payload.get("hwnd")
        elif isinstance(target, dict):
            target = target.get("hwnd")
        if isinstance(target, str) and not target.strip().isdigit():
            matches = []
            title = target.strip()
            def callback(hwnd, items):
                if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == title:
                    items.append(hwnd)
                return True

            win32gui.EnumWindows(callback, matches)
            if len(matches) != 1:
                if not matches:
                    raise _WindowNotFound(f"未找到窗口: {title}")
                raise ValueError(f"窗口标题不唯一: {title}")
            target = matches[0]
        try:
            hwnd = integer_parameter(target, "窗口句柄", minimum=1)
        except (TypeError, ValueError) as exc:
            raise ValueError("窗口目标必须是 HWND、窗口标题或窗口信息") from exc
        if not win32gui.IsWindow(hwnd):
            raise _WindowNotFound(f"窗口句柄无效: {hwnd}")
        return hwnd

    @staticmethod
    def _target_process_elevation(pid: Any) -> Optional[bool]:
        """Read a target process token elevation without requiring admin rights.

        ``None`` means the platform/API could not provide a reliable answer; it
        is deliberately kept distinct from ``False`` (known unelevated).
        """
        if os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            process = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if not process:
                return None
            token = wintypes.HANDLE()
            try:
                if not ctypes.windll.advapi32.OpenProcessToken(process, 0x0008, ctypes.byref(token)):
                    return None
                class _TokenElevation(ctypes.Structure):
                    _fields_ = [("TokenIsElevated", wintypes.DWORD)]

                elevation = _TokenElevation()
                size = wintypes.DWORD()
                if not ctypes.windll.advapi32.GetTokenInformation(
                    token, 20, ctypes.byref(elevation), ctypes.sizeof(elevation), ctypes.byref(size)
                ):
                    return None
                return bool(elevation.TokenIsElevated)
            finally:
                if token.value:
                    ctypes.windll.kernel32.CloseHandle(token)
                ctypes.windll.kernel32.CloseHandle(process)
        except Exception:
            return None

    def 信息(self, 目标: Any = None) -> dict:
        """Return stable metadata for a top-level or child window."""
        _, win32gui, win32process = self._win32()
        hwnd = self._resolve_hwnd(目标)
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        info = {
            "hwnd": int(hwnd),
            "title": str(win32gui.GetWindowText(hwnd) or ""),
            "class_name": str(win32gui.GetClassName(hwnd) or ""),
            "pid": int(pid or 0),
            "visible": bool(win32gui.IsWindowVisible(hwnd)),
            "minimized": bool(win32gui.IsIconic(hwnd)),
            "x": int(left),
            "y": int(top),
            "width": max(0, int(right - left)),
            "height": max(0, int(bottom - top)),
            "client_width": max(0, int(client_right - client_left)),
            "client_height": max(0, int(client_bottom - client_top)),
        }
        info.update(
            {
                "句柄": info["hwnd"],
                "标题": info["title"],
                "类名": info["class_name"],
                "进程号": info["pid"],
                "可见": info["visible"],
                "最小化": info["minimized"],
                "宽": info["width"],
                "高": info["height"],
            }
        )
        return info

    def 枚举(self, 标题: Any = None, 类名: Any = None, 可见: Any = True) -> list:
        _, win32gui, win32process = self._win32()
        title_filter = str(标题 or "").strip()
        class_filter = str(类名 or "").strip()
        visible_only = _as_bool(可见)
        result = []

        def callback(hwnd, _):
            try:
                if visible_only and not win32gui.IsWindowVisible(hwnd):
                    return True
                title = str(win32gui.GetWindowText(hwnd) or "")
                class_name = str(win32gui.GetClassName(hwnd) or "")
                if title_filter and title_filter not in title:
                    return True
                if class_filter and class_filter not in class_name:
                    return True
                if not title and not class_name:
                    return True
                result.append(self.信息(hwnd))
            except Exception:
                return True
            return True

        win32gui.EnumWindows(callback, None)
        return result

    def 查找(self, 标题: Any, 完全匹配: Any = False, 可见: Any = True) -> list:
        text = str(标题 or "").strip()
        if not text:
            raise ValueError("窗口标题不能为空")
        rows = self.枚举(可见=可见)
        if _as_bool(完全匹配):
            return [row for row in rows if row.get("title") == text]
        return [row for row in rows if text in str(row.get("title") or "")]

    def 子窗口(self, 目标: Any = None, 搜索深度: Any = 10, 可见: Any = False) -> list:
        """Return descendants in parent-first order with an explicit depth."""
        _, win32gui, _ = self._win32()
        parent = self._resolve_hwnd(目标)
        max_depth = max(1, int(搜索深度))
        visible_only = _as_bool(可见)
        rows = []

        def walk(hwnd: int, depth: int) -> None:
            if depth > max_depth:
                return
            child = win32gui.GetWindow(hwnd, 5)  # GW_CHILD
            while child:
                current = child
                try:
                    if not visible_only or win32gui.IsWindowVisible(current):
                        row = self.信息(current)
                        row["parent_hwnd"] = int(hwnd)
                        row["depth"] = depth
                        rows.append(row)
                    walk(current, depth + 1)
                except Exception:
                    # 单个失效/拒绝访问的子窗口不能截断同级窗口遍历。
                    pass
                try:
                    child = win32gui.GetWindow(current, 2)  # GW_HWNDNEXT
                except Exception:
                    break

        walk(parent, 1)
        return rows

    def Z序(self, 可见: Any = True) -> list:
        """Enumerate top-level windows in the OS Z-order."""
        _, win32gui, _ = self._win32()
        visible_only = _as_bool(可见)
        rows = []

        def callback(hwnd, _):
            try:
                if visible_only and not win32gui.IsWindowVisible(hwnd):
                    return True
                title = str(win32gui.GetWindowText(hwnd) or "")
                class_name = str(win32gui.GetClassName(hwnd) or "")
                if title or class_name:
                    row = self.信息(hwnd)
                    row["z_index"] = len(rows)
                    rows.append(row)
            except Exception:
                pass
            return True

        win32gui.EnumWindows(callback, None)
        return rows

    def DPI(self, 目标: Any = None) -> ScriptResult:
        _, win32gui, _ = self._win32()
        hwnd = self._resolve_hwnd(目标)
        getter = getattr(win32gui, "GetDpiForWindow", None)
        if not callable(getter):
            try:
                import ctypes
                getter = getattr(ctypes.windll.user32, "GetDpiForWindow", None)
            except Exception:
                getter = None
        if not callable(getter):
            return ScriptResult({
                "ok": False,
                "kind": "window",
                "hwnd": hwnd,
                "dpi": None,
                "scale": None,
                "error": "系统不支持 GetDpiForWindow",
            })
        try:
            dpi = int(getter(hwnd))
        except Exception as exc:
            return ScriptResult({"ok": False, "kind": "window", "hwnd": hwnd, "dpi": None, "scale": None, "error": str(exc)})
        return ScriptResult({"ok": dpi > 0, "kind": "window", "hwnd": hwnd, "dpi": dpi if dpi > 0 else None, "scale": dpi / 96.0 if dpi > 0 else None})

    def 坐标转换(self, x: Any, y: Any, 方向: Any = "屏幕到客户区", 目标: Any = None) -> ScriptResult:
        """在屏幕坐标与目标窗口客户区坐标之间转换，保留负坐标以支持多显示器。"""
        _, win32gui, _ = self._win32()
        hwnd = self._resolve_hwnd(目标)
        try:
            px, py = int(x), int(y)
        except (TypeError, ValueError) as exc:
            raise ValueError("坐标必须是整数") from exc
        direction = str(方向 or "屏幕到客户区").strip().casefold()
        screen_to_client = direction in {"屏幕到客户区", "屏幕转客户区", "screen_to_client", "screen2client"}
        client_to_screen = direction in {"客户区到屏幕", "客户区转屏幕", "client_to_screen", "client2screen"}
        if not (screen_to_client or client_to_screen):
            raise ValueError("坐标转换方向只能是 屏幕到客户区 或 客户区到屏幕")
        try:
            result = win32gui.ScreenToClient(hwnd, (px, py)) if screen_to_client else win32gui.ClientToScreen(hwnd, (px, py))
        except Exception as exc:
            raise ValueError(f"坐标转换失败: {exc}") from exc
        return ScriptResult({"ok": True, "kind": "coordinate", "x": int(result[0]), "y": int(result[1]), "hwnd": hwnd, "direction": "screen_to_client" if screen_to_client else "client_to_screen"})

    def 兼容性(self, 目标: Any = None) -> ScriptResult:
        """诊断当前脚本运行环境，供执行前判断 DPI/截图/UAC 能力。"""
        payload = {"ok": True, "kind": "compatibility", "platform": os.name}
        try:
            from utils.dpi_awareness import get_process_dpi_awareness
            awareness = get_process_dpi_awareness()
            payload["dpi_awareness"] = int(awareness)
            payload["dpi_aware"] = int(awareness) >= 1
        except Exception as exc:
            payload.update({"dpi_awareness": None, "dpi_aware": False, "dpi_error": str(exc)})
        try:
            # 直接读取统一截图引擎能力表，包含原生、DirectX/D3D 与 OpenGL 插件项。
            from utils.capture.screenshot_helper import get_screenshot_diagnostics
            screenshot_diag = dict(get_screenshot_diagnostics() or {})
            payload["screenshot"] = dict(screenshot_diag.get("capabilities") or {})
            payload["screenshot_diagnostics"] = screenshot_diag
            caps = payload["screenshot"]
            payload["directx"] = bool(
                caps.get("dxgi")
                or caps.get("dx")
                or caps.get("dx2")
                or caps.get("dx3")
                or caps.get("dx.graphic.2d")
                or caps.get("dx.graphic.2d.2")
                or caps.get("dx.graphic.3d")
                or caps.get("dx.graphic.3d.8")
                or caps.get("dx.graphic.3d.10plus")
            )
            payload["opengl"] = bool(
                caps.get("dx.graphic.opengl") or caps.get("dx.graphic.opengl.esv2")
            )
        except Exception as exc:
            payload.update({"screenshot": {}, "screenshot_diagnostics": {}, "directx": False, "opengl": False, "screenshot_error": str(exc)})
        try:
            import ctypes
            payload["admin"] = bool(ctypes.windll.shell32.IsUserAnAdmin()) if os.name == "nt" else False
        except Exception:
            payload["admin"] = False
        try:
            user_threads = getattr(self._host, "_user_threads", {}) or {}
            watch_threads = getattr(self._host, "_watch_threads", {}) or {}
            active_user = sum(1 for thread in user_threads.values() if thread is not None and thread.is_alive())
            active_watch = sum(1 for thread in watch_threads.values() if thread is not None and thread.is_alive())
            from services.screenshot_pool import get_screenshot_worker_limit

            payload["runtime"] = {
                "python": platform.python_version(),
                "user_threads": active_user,
                "watch_threads": active_watch,
                "screenshot_worker_limit": int(get_screenshot_worker_limit()),
            }
        except Exception as exc:
            payload["runtime"] = {"python": platform.python_version(), "error": str(exc)}
        if 目标 is not None or self._host.context.get("target_hwnd"):
            try:
                hwnd = self._resolve_hwnd(目标)
                payload["hwnd"] = hwnd
                payload["window_dpi"] = self.DPI(hwnd).dpi
                try:
                    _, _, win32process = self._win32()
                    _thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
                    payload["window_pid"] = int(pid)
                    elevated = self._target_process_elevation(pid)
                    payload["window_admin"] = elevated
                    payload["window_integrity"] = (
                        "高" if elevated is True else "中/低" if elevated is False else "未知"
                    )
                except Exception as exc:
                    payload.update({"window_admin": None, "window_integrity": "未知", "window_admin_error": str(exc)})
            except Exception as exc:
                payload["window_error"] = str(exc)
        return ScriptResult(payload)

    def 消息(self, 目标: Any, 消息: Any, wParam: Any = 0, lParam: Any = 0, 投递: Any = True) -> ScriptResult:
        win32con, win32gui, _ = self._win32()
        hwnd = self._resolve_hwnd(目标)
        names = {
            "关闭": win32con.WM_CLOSE, "激活": win32con.WM_ACTIVATE,
            "显示": win32con.WM_SHOWWINDOW, "隐藏": win32con.WM_SHOWWINDOW,
            "左键按下": win32con.WM_LBUTTONDOWN, "左键松开": win32con.WM_LBUTTONUP,
            "右键按下": win32con.WM_RBUTTONDOWN, "右键松开": win32con.WM_RBUTTONUP,
            "中键按下": win32con.WM_MBUTTONDOWN, "中键松开": win32con.WM_MBUTTONUP,
            "回车": win32con.WM_KEYDOWN, "复制": win32con.WM_COPY, "粘贴": win32con.WM_PASTE,
        }
        message_name = str(消息).strip() if isinstance(消息, str) else ""
        if message_name in names:
            code = names[message_name]
            # WM_SHOWWINDOW 的 wParam 明确表示显示(1)/隐藏(0)。
            if message_name == "显示" and wParam == 0:
                wParam = 1
            elif message_name == "隐藏" and wParam == 0:
                wParam = 0
        else:
            try:
                code = int(消息)
            except (TypeError, ValueError) as exc:
                raise ValueError("窗口消息必须是受支持的名称或整数消息号") from exc
        if code < 0 or code > 0xFFFF:
            raise ValueError("窗口消息号必须在 0 到 65535 之间")
        try:
            wParam = int(wParam or 0)
            lParam = int(lParam or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("窗口消息参数必须是整数") from exc
        if not -(2**31) <= wParam <= 0xFFFFFFFF or not -(2**31) <= lParam <= 0xFFFFFFFF:
            raise ValueError("窗口消息参数超出 32 位范围")
        posted = _as_bool(投递)
        sender = win32gui.PostMessage if posted else win32gui.SendMessage
        result = sender(hwnd, code, wParam, lParam)
        # pywin32 的 PostMessage 成功时返回 None，失败会抛异常。
        # SendMessage 的 0 则可能是消息本身的合法返回值。
        ok = not (posted and result is False)
        return ScriptResult({"ok": ok, "kind": "window_message", "hwnd": hwnd, "message": code, "result": result, "posted": posted})

    def 激活(self, 目标: Any = None) -> bool:
        from utils.window.window_activation_utils import activate_window

        return bool(activate_window(self._resolve_hwnd(目标), log_prefix="自定义脚本"))

    def _element_simulator(self, 目标: Any = None):
        hwnd = self._resolve_hwnd(目标)
        try:
            from utils.input_simulation import InputSimulatorFactory, SimulatorBackend
            simulator = InputSimulatorFactory.create_simulator(
                hwnd=hwnd,
                operation_mode="auto",
                execution_mode=self._host.context.get("execution_mode", "foreground"),
                backend=SimulatorBackend.NATIVE,
            )
            if simulator is None:
                raise ScriptError("窗口元素 API 不可用: 无法创建 UIAutomation 模拟器")
            return simulator
        except Exception as exc:
            raise ScriptError(f"窗口元素 API 不可用: {exc}") from exc

    @staticmethod
    def _element_kwargs(名称=None, 自动化ID=None, 类名=None, 控件类型=None, 搜索深度=30, 超时=5.0):
        control_type_map = {
            "按钮": "ButtonControl", "编辑框": "EditControl", "文本": "TextControl",
            "复选框": "CheckBoxControl", "单选按钮": "RadioButtonControl", "下拉框": "ComboBoxControl",
            "列表": "ListControl", "列表项": "ListItemControl", "菜单": "MenuControl",
            "菜单项": "MenuItemControl", "树": "TreeControl", "树节点": "TreeItemControl",
            "选项卡": "TabControl", "选项卡项": "TabItemControl", "超链接": "HyperlinkControl",
            "窗口": "WindowControl", "面板": "PaneControl", "分组": "GroupControl",
            "数据表格": "DataGridControl", "表格": "TableControl", "无": None,
        }
        value = str(控件类型 or "").strip() or None
        return {
            "name": str(名称 or "").strip() or None,
            "automation_id": str(自动化ID or "").strip() or None,
            "class_name": str(类名 or "").strip() or None,
            "control_type": control_type_map.get(value, value),
            "search_depth": integer_parameter(搜索深度, "搜索深度", minimum=1),
            "timeout": finite_seconds(超时, "超时"),
        }

    def 查找元素(self, 名称=None, 自动化ID=None, 类名=None, 控件类型=None, 序号=0, 搜索深度=30, 超时=5.0, 目标=None):
        start = integer_parameter(序号, "序号", minimum=0)
        kwargs = self._element_kwargs(名称, 自动化ID, 类名, 控件类型, 搜索深度, 超时)
        simulator = self._element_simulator(目标)
        elements = simulator.find_all_elements(**kwargs)
        rows = []
        for element in elements[start:]:
            row = {}
            for key, attr in (("name", "Name"), ("automation_id", "AutomationId"), ("class_name", "ClassName"), ("control_type", "ControlTypeName")):
                try:
                    row[key] = getattr(element, attr, "") or ""
                except Exception:
                    row[key] = ""
            try:
                rect = element.BoundingRectangle
                row.update({"x": rect.left, "y": rect.top, "width": rect.width(), "height": rect.height()})
            except Exception:
                pass
            rows.append(row)
        return ScriptResult({"ok": bool(rows), "kind": "elements", "items": rows})

    def 元素文本(self, 名称=None, 自动化ID=None, 类名=None, 控件类型=None, 序号=0, 搜索深度=30, 超时=5.0, 目标=None):
        index = integer_parameter(序号, "序号", minimum=0)
        kwargs = self._element_kwargs(名称, 自动化ID, 类名, 控件类型, 搜索深度, 超时)
        simulator = self._element_simulator(目标)
        elements = simulator.find_all_elements(**kwargs)
        element = elements[index] if index < len(elements) else None
        if element is None:
            return ScriptResult({"ok": False, "kind": "element"})
        text = None
        pattern_errors = []
        try:
            value_pattern = element.GetValuePattern()
            if value_pattern:
                text = value_pattern.Value
        except Exception as exc:
            pattern_errors.append(str(exc))
        if text is None:
            try:
                text_pattern = element.GetTextPattern()
                if text_pattern:
                    text = text_pattern.DocumentRange.GetText(-1)
            except Exception as exc:
                pattern_errors.append(str(exc))
        if text is None:
            return ScriptResult({
                "ok": False,
                "kind": "element",
                "text": "",
                "error": "元素不支持读取文本" if not pattern_errors else "；".join(pattern_errors),
            })
        return ScriptResult({"ok": True, "kind": "element", "text": text or ""})

    def 设置元素值(self, 值, 名称=None, 自动化ID=None, 类名=None, 控件类型=None, 序号=0, 搜索深度=30, 超时=5.0, 目标=None):
        index = integer_parameter(序号, "序号", minimum=0)
        kwargs = self._element_kwargs(名称, 自动化ID, 类名, 控件类型, 搜索深度, 超时)
        simulator = self._element_simulator(目标)
        elements = simulator.find_all_elements(**kwargs)
        element = elements[index] if index < len(elements) else None
        if element is None:
            return ScriptResult({"ok": False, "kind": "element"})
        try:
            pattern = element.GetValuePattern()
            if not pattern:
                raise RuntimeError("元素不支持设置值")
            pattern.SetValue(str(值))
            return ScriptResult({"ok": True, "kind": "element", "value": str(值)})
        except Exception as exc:
            # UI Automation pattern 不可用时必须显式失败；不转换为点击、
            # 坐标输入或其他隐式动作，避免误操作目标窗口。
            return ScriptResult({"ok": False, "kind": "element", "value": str(值), "error": str(exc)})

    def _find_element_object(self, 名称=None, 自动化ID=None, 类名=None, 控件类型=None,
                             序号=0, 搜索深度=30, 超时=5.0, 目标=None):
        index = integer_parameter(序号, "序号", minimum=0)
        kwargs = self._element_kwargs(名称, 自动化ID, 类名, 控件类型, 搜索深度, 超时)
        simulator = self._element_simulator(目标)
        elements = simulator.find_all_elements(**kwargs)
        return (elements[index] if index < len(elements) else None), simulator

    @staticmethod
    def _element_info(element: Any) -> dict:
        """读取常用 UIA 属性；单个属性读取失败不会影响其他属性。"""
        values = {}
        attrs = {
            "name": "Name", "automation_id": "AutomationId", "class_name": "ClassName",
            "control_type": "ControlTypeName", "enabled": "IsEnabled", "offscreen": "IsOffscreen",
            "focused": "HasKeyboardFocus",
        }
        for key, attr in attrs.items():
            try:
                values[key] = getattr(element, attr)
            except Exception:
                values[key] = "" if key in {"name", "automation_id", "class_name", "control_type"} else False
        try:
            rect = element.BoundingRectangle
            values.update({"x": int(rect.left), "y": int(rect.top), "width": int(rect.width()), "height": int(rect.height())})
        except Exception:
            pass
        values.update({"名称": values.get("name", ""), "自动化ID": values.get("automation_id", ""),
                       "类名": values.get("class_name", ""), "控件类型": values.get("control_type", "")})
        return values

    def 元素属性(self, 名称=None, 自动化ID=None, 类名=None, 控件类型=None, 序号=0,
                 搜索深度=30, 超时=5.0, 目标=None):
        element, _ = self._find_element_object(名称, 自动化ID, 类名, 控件类型, 序号, 搜索深度, 超时, 目标)
        if element is None:
            return ScriptResult({"ok": False, "kind": "element"})
        return ScriptResult({"ok": True, "kind": "element", **self._element_info(element)})

    def 元素聚焦(self, 名称=None, 自动化ID=None, 类名=None, 控件类型=None, 序号=0,
                 搜索深度=30, 超时=5.0, 目标=None):
        element, _ = self._find_element_object(名称, 自动化ID, 类名, 控件类型, 序号, 搜索深度, 超时, 目标)
        if element is None:
            return ScriptResult({"ok": False, "kind": "element"})
        try:
            element.SetFocus()
            return ScriptResult({"ok": True, "kind": "element", "action": "focus"})
        except Exception as exc:
            return ScriptResult({"ok": False, "kind": "element", "action": "focus", "error": str(exc)})

    def 元素切换(self, 名称=None, 自动化ID=None, 类名=None, 控件类型=None, 序号=0,
                 搜索深度=30, 超时=5.0, 目标=None, 状态=None):
        element, _ = self._find_element_object(名称, 自动化ID, 类名, 控件类型, 序号, 搜索深度, 超时, 目标)
        if element is None:
            return ScriptResult({"ok": False, "kind": "element"})
        try:
            pattern = element.GetTogglePattern()
            if not pattern:
                raise RuntimeError("元素不支持勾选状态")
            desired = None if 状态 is None else _as_bool(状态)
            current = int(getattr(pattern, "ToggleState", 0))
            if desired is None or (desired and current == 0) or ((not desired) and current != 0):
                pattern.Toggle()
            state = int(getattr(pattern, "ToggleState", current))
            return ScriptResult({"ok": True, "kind": "element", "checked": state != 0, "state": state})
        except Exception as exc:
            return ScriptResult({"ok": False, "kind": "element", "error": str(exc)})

    def 元素选择(self, 值=None, 名称=None, 自动化ID=None, 类名=None, 控件类型=None, 序号=0,
                 搜索深度=30, 超时=5.0, 目标=None):
        element, simulator = self._find_element_object(名称, 自动化ID, 类名, 控件类型, 序号, 搜索深度, 超时, 目标)
        if element is None:
            return ScriptResult({"ok": False, "kind": "element"})
        try:
            target = element
            if 值 is not None:
                # ComboBox/List 选择项：优先在控件子树按名称精确找 ListItem。
                candidates = simulator.find_all_elements(name=str(值), control_type="ListItemControl", search_depth=搜索深度, timeout=超时)
                if candidates:
                    target = candidates[0]
            pattern = target.GetSelectionItemPattern()
            if not pattern:
                raise RuntimeError("元素不支持选择")
            pattern.Select()
            return ScriptResult({"ok": True, "kind": "element", "value": "" if 值 is None else str(值)})
        except Exception as exc:
            return ScriptResult({"ok": False, "kind": "element", "error": str(exc)})

    def _元素展开折叠(self, expand: bool, **kwargs):
        element, _ = self._find_element_object(**kwargs)
        if element is None:
            return ScriptResult({"ok": False, "kind": "element"})
        try:
            pattern = element.GetExpandCollapsePattern()
            if not pattern:
                raise RuntimeError("元素不支持展开折叠")
            (pattern.Expand if expand else pattern.Collapse)()
            return ScriptResult({"ok": True, "kind": "element", "expanded": bool(expand)})
        except Exception as exc:
            return ScriptResult({"ok": False, "kind": "element", "error": str(exc)})

    def 元素展开(self, **kwargs):
        return self._元素展开折叠(True, **kwargs)

    def 元素折叠(self, **kwargs):
        return self._元素展开折叠(False, **kwargs)

    def 关闭(self, 目标: Any = None) -> bool:
        _, win32gui, win32process = self._win32()
        _ = win32process
        hwnd = self._resolve_hwnd(目标)
        import win32con

        return win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0) is not False

    def 显示(self, 目标: Any = None) -> bool:
        _, win32gui, win32process = self._win32()
        _ = win32process
        hwnd = self._resolve_hwnd(目标)
        import win32con

        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        return True

    def 隐藏(self, 目标: Any = None) -> bool:
        _, win32gui, win32process = self._win32()
        _ = win32process
        hwnd = self._resolve_hwnd(目标)
        import win32con

        win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
        return True

    def 最小化(self, 目标: Any = None) -> bool:
        _, win32gui, win32process = self._win32()
        _ = win32process
        hwnd = self._resolve_hwnd(目标)
        import win32con

        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        return True

    def 还原(self, 目标: Any = None) -> bool:
        _, win32gui, win32process = self._win32()
        _ = win32process
        hwnd = self._resolve_hwnd(目标)
        import win32con

        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        return True

    def 移动(self, x: Any, y: Any, 目标: Any = None) -> bool:
        _, win32gui, win32process = self._win32()
        _ = win32process
        hwnd = self._resolve_hwnd(目标)
        import win32con

        win32gui.SetWindowPos(hwnd, 0, int(x), int(y), 0, 0, win32con.SWP_NOSIZE | win32con.SWP_NOZORDER)
        return True

    def 大小(self, 宽: Any, 高: Any, 目标: Any = None) -> bool:
        _, win32gui, win32process = self._win32()
        _ = win32process
        hwnd = self._resolve_hwnd(目标)
        import win32con

        win32gui.SetWindowPos(hwnd, 0, 0, 0, int(宽), int(高), win32con.SWP_NOMOVE | win32con.SWP_NOZORDER)
        return True

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise ScriptError("禁止访问该属性")
        if name in {"宽", "宽度"}:
            width, _ = self._client_size_or_error()
            return width
        if name in {"高", "高度"}:
            _, height = self._client_size_or_error()
            return height
        raise ScriptError(f"没有字段: {name}")

    def _client_size_or_error(self) -> Tuple[int, int]:
        hwnd = int(self._host.context.get("target_hwnd") or 0)
        if hwnd <= 0:
            raise ValueError("窗口宽高缺少当前目标窗口")
        try:
            import win32gui

            left, top, right, bottom = win32gui.GetClientRect(hwnd)
        except Exception as exc:
            raise ValueError(f"读取窗口客户区尺寸失败: {exc}") from exc
        width, height = int(right - left), int(bottom - top)
        if width < 0 or height < 0:
            raise ValueError("读取窗口客户区尺寸失败: 尺寸未知")
        return width, height


class _ClipboardApi:
    def 获取(self) -> str:
        return clipboard_get()

    def 设置(self, 文本: Any) -> str:
        return clipboard_set(文本)


class _ElevationLaunchError(OSError):
    """Raised when ShellExecuteExW cannot start an elevated process."""

    def __init__(self, error_code: int, message: str) -> None:
        super().__init__(int(error_code), message)
        self.winerror = int(error_code)


class _ElevatedProcess:
    """Small Popen-compatible wrapper around a ShellExecuteEx process handle."""

    def __init__(self, pid: int, handle: Any, api: Dict[str, Any], command: list[str]) -> None:
        self.pid = int(pid)
        self._handle = handle
        self._api = api
        self._command = command
        self._lca_program_path = command[0]
        self._returncode = None
        self._closed = False
        self.stdin = None
        self.stdout = None
        self.stderr = None

    @property
    def returncode(self):
        return self._returncode

    def _exit_code(self) -> int:
        import ctypes
        from ctypes import wintypes

        value = wintypes.DWORD()
        if not self._api["get_exit_code"](self._handle, ctypes.byref(value)):
            raise OSError(int(ctypes.get_last_error() or 1), "读取提权进程退出码失败")
        return int(value.value)

    def poll(self):
        if self._returncode is not None:
            return self._returncode
        result = int(self._api["wait"](self._handle, 0))
        if result == 0x00000102:  # WAIT_TIMEOUT
            return None
        if result != 0x00000000:  # WAIT_OBJECT_0
            raise OSError("查询提权进程状态失败")
        self._returncode = self._exit_code()
        return self._returncode

    def wait(self, timeout=None):
        import subprocess

        if self._returncode is not None:
            return self._returncode
        if timeout is None:
            milliseconds = 0xFFFFFFFF
        else:
            milliseconds = max(0, int(float(timeout) * 1000))
        result = int(self._api["wait"](self._handle, milliseconds))
        if result == 0x00000102:  # WAIT_TIMEOUT
            raise subprocess.TimeoutExpired(self._command, timeout)
        if result != 0x00000000:
            raise OSError("等待提权进程失败")
        self._returncode = self._exit_code()
        return self._returncode

    def terminate(self) -> None:
        if self.poll() is not None:
            return
        if not self._api["terminate"](self._handle, 1):
            import ctypes

            error_code = int(ctypes.get_last_error() or 1)
            raise OSError(error_code, "终止提权进程失败")

    def kill(self) -> None:
        self.terminate()

    def communicate(self, input=None, timeout=None):
        if input not in (None, b"", ""):
            raise ValueError("提权启动不支持标准输入")
        self.wait(timeout=timeout)
        return "", ""

    def close(self) -> None:
        if self._closed:
            return
        if self._handle:
            self._api["close"](self._handle)
        self._closed = True
        self._handle = None


def _close_process_resources(process: Any) -> None:
    errors = []
    for name in ("stdin", "stdout", "stderr"):
        stream = getattr(process, name, None)
        if stream is not None:
            try:
                stream.close()
            except Exception as exc:
                errors.append(f"{name}: {exc}")
    close = getattr(process, "close", None)
    if callable(close):
        try:
            close()
        except Exception as exc:
            errors.append(str(exc))
    if errors:
        raise ValueError("；".join(errors))


def _launch_elevated_process(executable: str, args: list[str], working_directory: Optional[str]):
    """Start a program with UAC only after CreateProcess reports ERROR_ELEVATION_REQUIRED."""
    if os.name != "nt":
        raise OSError(740, "Windows 管理员提权仅适用于 Windows")

    import ctypes
    import subprocess
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = (
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", wintypes.LPVOID),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        )

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    execute = shell32.ShellExecuteExW
    execute.argtypes = (ctypes.POINTER(ShellExecuteInfo),)
    execute.restype = wintypes.BOOL
    get_process_id = kernel32.GetProcessId
    get_process_id.argtypes = (wintypes.HANDLE,)
    get_process_id.restype = wintypes.DWORD
    wait_for_process = kernel32.WaitForSingleObject
    wait_for_process.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    wait_for_process.restype = wintypes.DWORD
    get_exit_code = kernel32.GetExitCodeProcess
    get_exit_code.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    get_exit_code.restype = wintypes.BOOL
    terminate_process = kernel32.TerminateProcess
    terminate_process.argtypes = (wintypes.HANDLE, wintypes.UINT)
    terminate_process.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    execute_info = ShellExecuteInfo()
    execute_info.cbSize = ctypes.sizeof(execute_info)
    execute_info.fMask = 0x00000040 | 0x00000100  # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    execute_info.lpVerb = "runas"
    execute_info.lpFile = executable
    execute_info.lpParameters = subprocess.list2cmdline(args)
    execute_info.lpDirectory = working_directory or None
    execute_info.nShow = 1  # SW_SHOWNORMAL
    if not execute(ctypes.byref(execute_info)):
        error_code = int(ctypes.get_last_error() or 1)
        if error_code == 1223:  # ERROR_CANCELLED
            raise _ElevationLaunchError(error_code, "用户取消了管理员授权")
        raise _ElevationLaunchError(error_code, "ShellExecuteExW 启动提权程序失败")
    if not execute_info.hProcess:
        raise _ElevationLaunchError(1, "提权程序未返回进程句柄")

    shell_handle = execute_info.hProcess
    pid = int(get_process_id(shell_handle) or 0)
    if pid <= 0:
        close_handle(shell_handle)
        error_code = int(ctypes.get_last_error() or 1)
        raise _ElevationLaunchError(error_code, "无法读取提权进程号")
    return _ElevatedProcess(
        pid,
        shell_handle,
        {
            "wait": wait_for_process,
            "get_exit_code": get_exit_code,
            "terminate": terminate_process,
            "close": close_handle,
        },
        [executable, *args],
    )


class _ProcessView:
    """Process inspection and control for custom scripts."""

    def __init__(self, host) -> None:
        self._host = host

    @staticmethod
    def _psutil():
        try:
            import psutil
        except Exception as exc:
            raise ScriptError(f"进程 API 不可用: {exc}") from exc
        return psutil

    @staticmethod
    def _pid(value: Any) -> int:
        try:
            return integer_parameter(value, "进程号", minimum=1)
        except ValueError as exc:
            raise ValueError("进程号必须是正整数") from exc

    def _resolve_program_path(self, value: Any, *, require_file: bool = False) -> str:
        from task_workflow.script_resources import resolve_script_program_path

        return resolve_script_program_path(
            str(value or ""),
            require_file=require_file,
            **self._host._resource_dirs(),
        )

    def 查找(self, 名称: Any = None) -> list:
        psutil = self._psutil()
        raw_needle = str(名称 or "").strip()
        path_needle = ""
        if raw_needle and (os.path.isabs(raw_needle) or "/" in raw_needle or "\\" in raw_needle):
            path_needle = os.path.normcase(
                os.path.abspath(self._resolve_program_path(raw_needle, require_file=False))
            )
        needle = raw_needle.casefold()
        rows = []
        for proc in psutil.process_iter(["pid", "name", "exe", "status"]):
            try:
                info = proc.info
                name = str(info.get("name") or "")
                exe = str(info.get("exe") or "")
                if path_needle:
                    if not exe or os.path.normcase(os.path.abspath(exe)) != path_needle:
                        continue
                elif needle and needle not in name.casefold() and needle not in exe.casefold():
                    continue
                rows.append(
                    ScriptResult(
                        {
                            "pid": int(info.get("pid") or 0),
                            "name": name,
                            "path": exe,
                            "status": str(info.get("status") or ""),
                        },
                        ok=True,
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return rows

    def 信息(self, 进程号: Any) -> dict:
        psutil = self._psutil()
        try:
            proc = psutil.Process(self._pid(进程号))
            with proc.oneshot():
                return ScriptResult(
                    {
                        "pid": int(proc.pid),
                        "name": str(proc.name() or ""),
                        "path": str(proc.exe() or ""),
                        "status": str(proc.status() or ""),
                        "create_time": float(proc.create_time() or 0),
                    },
                    ok=True,
                )
        except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            raise ValueError(f"无法读取进程: {进程号}") from exc

    def 是否运行(self, 目标: Any) -> bool:
        psutil = self._psutil()
        if isinstance(目标, (int, float)) and not isinstance(目标, bool):
            pid = self._pid(目标)
            try:
                return bool(psutil.pid_exists(pid))
            except Exception as exc:
                raise ValueError(f"查询进程状态失败，状态未知: {pid}: {exc}") from exc
        return bool(self.查找(目标))

    def 启动(self, 程序: Any, 参数: Any = None, 等待: Any = False, 超时: Any = 30) -> dict:
        import subprocess

        wait_for_exit = _as_bool(等待, "进程等待")
        timeout = finite_seconds(超时, "进程超时")
        raw_program = os.path.expandvars(os.path.expanduser(str(程序 or "").strip()))
        path_argument = os.path.isabs(raw_program) or "/" in raw_program or "\\" in raw_program
        executable = self._resolve_program_path(程序, require_file=path_argument)
        if 参数 is None:
            args = []
        elif isinstance(参数, (list, tuple)):
            args = [str(item) for item in 参数]
        else:
            args = [str(参数)]
        working_directory = os.path.dirname(executable) if os.path.isabs(executable) else None
        try:
            proc = subprocess.Popen(
                [executable, *args],
                shell=False,
                cwd=working_directory,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if wait_for_exit else subprocess.DEVNULL,
                stderr=subprocess.PIPE if wait_for_exit else subprocess.DEVNULL,
                text=True,
            )
        except OSError as exc:
            if int(getattr(exc, "winerror", 0) or 0) != 740:
                raise ValueError(f"启动程序失败: {executable}: {exc}") from exc
            try:
                proc = _launch_elevated_process(executable, args, working_directory)
            except _ElevationLaunchError as elevation_error:
                if elevation_error.winerror == 1223:
                    raise ValueError(f"启动程序失败: 用户取消了管理员授权: {executable}") from elevation_error
                raise ValueError(
                    f"启动程序失败: {executable}: 管理员提权启动失败: {elevation_error}"
                ) from elevation_error
            except OSError as elevation_error:
                raise ValueError(
                    f"启动程序失败: {executable}: 管理员提权启动失败: {elevation_error}"
                ) from elevation_error
        # 非等待启动是明确的脱离脚本启动：工作流结束后程序继续运行，
        # 通过进程号或程序路径调用 进程.关闭 负责结束它。宿主仍登记对象，
        # 以便立即关闭本地管道/句柄，但收尾时不终止脱离进程。
        self._host._register_process(proc)
        try:
            proc._lca_program_path = executable
            proc._lca_detached = not wait_for_exit
        except AttributeError:
            pass
        result = {
            "pid": int(proc.pid),
            "path": executable,
            "running": proc.poll() is None,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "started": True,
            "completed": False,
            "timed_out": False,
            "status": "running",
        }
        if isinstance(proc, _ElevatedProcess):
            result["output_captured"] = False
            result["output_note"] = "管理员提权启动不支持捕获标准输出和错误输出"
        result["detached"] = not wait_for_exit
        self._host.logger.info(
            "[自定义脚本] 进程已启动: pid=%s, path=%s, detached=%s",
            result["pid"],
            executable,
            result["detached"],
        )
        if wait_for_exit:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                result["running"] = True
                result["stdout"] = ""
                result["stderr"] = ""
                result["timed_out"] = True
                result["status"] = "timeout"
            else:
                result.update(
                    {
                        "running": False,
                        "exit_code": proc.returncode,
                        "stdout": stdout or "",
                        "stderr": stderr or "",
                        "completed": True,
                        "status": "exited",
                    }
                )
                _close_process_resources(proc)
                self._host._forget_process(proc)
        ok = not wait_for_exit or (result["completed"] and result["exit_code"] == 0)
        return ScriptResult(result, ok=ok)

    def 关闭(self, 进程号: Any, 强制: Any = False) -> bool:
        import subprocess

        psutil = self._psutil()
        target = 进程号
        if isinstance(target, ScriptResult):
            target = target.pid
        elif isinstance(target, dict):
            target = target.get("pid")
        if target is None:
            raise ValueError("关闭目标必须是进程号或程序路径")
        try:
            try:
                pid = self._pid(target)
            except (TypeError, ValueError):
                if isinstance(target, (int, float)):
                    raise
                try:
                    float(str(target).strip())
                except (TypeError, ValueError):
                    pid = None
                else:
                    raise

            with self._host._process_lock:
                owned_by_pid = dict(self._host._owned_processes)

            if pid is None:
                path = self._resolve_program_path(target, require_file=True)
                path_key = os.path.normcase(os.path.abspath(os.path.normpath(path)))
                owned_matches = [
                    process
                    for process in owned_by_pid.values()
                    if os.path.normcase(
                        os.path.abspath(str(getattr(process, "_lca_program_path", "")))
                    ) == path_key
                ]
                if owned_matches:
                    processes = [(process, process) for process in owned_matches]
                else:
                    matches = []
                    for candidate_pid in psutil.pids():
                        candidate = psutil.Process(candidate_pid)
                        try:
                            candidate_path = str(candidate.exe() or "")
                            if candidate_path and os.path.normcase(
                                os.path.abspath(os.path.normpath(candidate_path))
                            ) == path_key:
                                matches.append(candidate)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                    matches = [item for item in matches if int(item.pid) not in owned_by_pid]
                    if len(matches) > 1:
                        raise ValueError("指定路径匹配到多个进程，请传入进程号")
                    if not matches:
                        raise ValueError(f"未找到指定程序对应的运行进程: {path}")
                    processes = [(item, None) for item in matches]
            else:
                owned = owned_by_pid.get(pid)
                processes = [(None, owned)] if owned is not None else [(psutil.Process(pid), None)]

            for proc, owned in processes:
                if owned is not None:
                    current_pid = int(owned.pid)
                    try:
                        owned.kill() if _as_bool(强制) else owned.terminate()
                        owned.wait(timeout=5.0)
                    except subprocess.TimeoutExpired as exc:
                        raise ValueError(f"进程未在 5 秒内退出: {current_pid}") from exc
                    try:
                        _close_process_resources(owned)
                    except Exception as exc:
                        raise ValueError(f"关闭进程资源失败: {current_pid}: {exc}") from exc
                    self._host._forget_process(owned)
                    continue
                current_pid = int(proc.pid)
                try:
                    proc.kill() if _as_bool(强制) else proc.terminate()
                    proc.wait(timeout=5.0)
                except psutil.NoSuchProcess:
                    pass
                except psutil.TimeoutExpired as exc:
                    raise ValueError(f"进程未在 5 秒内退出: {current_pid}") from exc
            return True
        except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith(("指定路径匹配到多个进程", "未找到指定程序", "进程未在")):
                raise
            raise ValueError(f"无法关闭进程或程序: {进程号}: {exc}") from exc


class _NetworkView:
    """HTTP client exposed to custom scripts."""

    def __init__(self, host) -> None:
        self._host = host

    def 请求(self, 地址: Any, 方法: Any = "GET", 数据: Any = None, 头: Any = None, 超时: Any = 15, 最大字节: Any = None) -> ScriptResult:
        from urllib.parse import urlparse
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen

        url = str(地址 or "").strip()
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise ValueError("网络地址只支持 HTTP 或 HTTPS")
        method = str(方法 or "GET").strip().upper()
        headers = {}
        if 头 is not None:
            if not isinstance(头, dict):
                raise TypeError("网络请求头必须是字典")
            headers = {str(key): str(value) for key, value in 头.items()}
        body = None
        if 数据 is not None:
            if isinstance(数据, (dict, list, tuple)):
                body = json.dumps(数据, ensure_ascii=False).encode("utf-8")
                headers.setdefault("Content-Type", "application/json; charset=utf-8")
            else:
                body = str(数据).encode("utf-8")
        timeout = finite_seconds(超时, "网络超时", positive=True)
        max_bytes = None
        if 最大字节 is not None:
            if isinstance(最大字节, bool):
                raise ValueError("最大字节必须是大于 0 的整数")
            try:
                max_bytes_float = float(最大字节)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("最大字节必须是大于 0 的整数") from exc
            if not math.isfinite(max_bytes_float) or not max_bytes_float.is_integer() or max_bytes_float < 1:
                raise ValueError("最大字节必须是大于 0 的整数")
            max_bytes = int(max_bytes_float)
        try:
            request = Request(url, data=body, headers=headers, method=method)
            try:
                response = urlopen(request, timeout=timeout)
            except HTTPError as error:
                response = error
            with response:
                if self._host.should_stop():
                    raise ScriptError("网络请求已停止")
                self._host._wait_if_paused()
                raw = response.read() if max_bytes is None else response.read(max_bytes + 1)
                truncated = max_bytes is not None and len(raw) > max_bytes
                if truncated:
                    raw = raw[:max_bytes]
                charset = response.headers.get_content_charset() or "utf-8"
                text = raw.decode(charset, errors="replace")
                return ScriptResult({"ok": 200 <= int(response.status) < 400, "kind": "http", "status": int(response.status), "headers": dict(response.headers.items()), "text": text, "bytes": len(raw), "url": url, "truncated": truncated})
        except Exception as exc:
            raise ValueError(f"网络请求失败: {exc}") from exc


class _EventView:
    def __init__(self, host) -> None:
        self._host = host

    def _wait(self, check, 超时: Any, 间隔: Any, kind: str) -> ScriptResult:
        timeout = finite_seconds(超时, "事件超时")
        pause = finite_seconds(间隔, "事件间隔", positive=True)
        deadline = time.monotonic() + timeout
        while True:
            if self._host.should_stop():
                raise ScriptError("事件等待已停止")
            self._host._wait_if_paused()
            value = check()
            if value:
                if isinstance(value, ScriptResult):
                    return value
                return ScriptResult({"ok": True, "kind": kind, "value": value})
            if time.monotonic() >= deadline:
                return ScriptResult({"ok": False, "kind": kind})
            self._host._sleep_interruptible(min(pause, max(0.0, deadline - time.monotonic())))

    def 等待窗口(self, 标题: Any, 完全匹配: Any = False, 超时: Any = 30, 间隔: Any = 0.3) -> ScriptResult:
        view = _WindowView(self._host)
        text = str(标题 or "").strip()
        if not text:
            raise ValueError("事件窗口标题不能为空")
        return self._wait(lambda: (view.查找(text, 完全匹配=完全匹配) or [None])[0], 超时, 间隔, "window_event")

    def 等待进程(self, 目标: Any, 超时: Any = 30, 间隔: Any = 0.5) -> ScriptResult:
        view = _ProcessView(self._host)
        def check():
            if isinstance(目标, (int, float)) and not isinstance(目标, bool):
                return ScriptResult({"ok": view.是否运行(目标), "kind": "process_event", "pid": int(目标)}) if view.是否运行(目标) else None
            rows = view.查找(目标)
            return rows[0] if rows else None
        return self._wait(check, 超时, 间隔, "process_event")

    def 等待窗口关闭(self, 目标: Any, 超时: Any = 30, 间隔: Any = 0.3) -> ScriptResult:
        view = _WindowView(self._host)
        target = 目标
        def check():
            try:
                hwnd = view._resolve_hwnd(target)
                return None if hwnd else True
            except _WindowNotFound:
                return True
        return self._wait(check, 超时, 间隔, "window_closed_event")

    def 等待进程退出(self, 目标: Any, 超时: Any = 30, 间隔: Any = 0.5) -> ScriptResult:
        view = _ProcessView(self._host)
        def check():
            if isinstance(目标, (int, float)) and not isinstance(目标, bool):
                return not view.是否运行(目标)
            return not bool(view.查找(目标))
        return self._wait(check, 超时, 间隔, "process_exit_event")

    def 等待文件(self, 文件: Any, 存在: Any = True, 超时: Any = 30, 间隔: Any = 0.5) -> ScriptResult:
        path = str(文件 or "").strip()
        if not path:
            raise ValueError("事件文件路径不能为空")
        if not os.path.isabs(path):
            raise ValueError("事件文件路径必须是绝对路径")
        want_exists = _as_bool(存在)
        def check():
            return os.path.isfile(path) == want_exists
        return self._wait(check, 超时, 间隔, "file_event")


class _HotkeyView:
    def __init__(self, host, callback_resolver) -> None:
        self._host = host
        self._callback_resolver = callback_resolver

    def 注册(self, 按键: Any, 回调: Any, 名字: Any = None) -> ScriptResult:
        callback = self._callback_resolver(回调)
        label = str(名字 or 按键 or "热键").strip() or "热键"
        return self._host.注册热键(按键, callback, label)

    def 注销(self, 名字: Any) -> bool:
        return self._host.注销热键(名字)

    def 全部注销(self) -> int:
        return self._host.全部注销热键()


class _TimerView:
    def __init__(self, host, callback_resolver) -> None:
        self._host = host
        self._callback_resolver = callback_resolver

    def 启动(self, 名字: Any, 间隔: Any, 回调: Any, 次数: Any = 0) -> ScriptResult:
        callback = self._callback_resolver(回调)
        return self._host.启动定时器(名字, 间隔, callback, 次数=次数)

    def 停止(self, 名字: Any) -> ScriptResult:
        return self._host.停止定时器(名字)


class _ExternalComponentApi:
    def __init__(self, host: CommandHost) -> None:
        self._host = host

    def 加载(self, 类型: Any, 入口: Any, 调用约定: Any = None, 超时: Any = 10) -> ScriptResult:
        return self._host.组件加载(类型, 入口, 调用约定=调用约定, 超时=超时)

    def 调用(self, 句柄: Any, 方法: Any = "", *参数: Any, **选项: Any) -> ScriptResult:
        return self._host.组件调用(句柄, 方法, *参数, **选项)

    def 读取(self, 句柄: Any, 属性: Any, 超时: Any = 30) -> ScriptResult:
        return self._host.组件读取(句柄, 属性, 超时=超时)

    def 写入(self, 句柄: Any, 属性: Any, 值: Any, 超时: Any = 30) -> ScriptResult:
        return self._host.组件写入(句柄, 属性, 值, 超时=超时)

    def 运行(self, 程序: Any, *参数: Any, **选项: Any) -> ScriptResult:
        return self._host.组件运行(程序, *参数, **选项)

    def 关闭(self, 句柄: Any = None, 超时: Any = 5) -> ScriptResult:
        return self._host.组件关闭(句柄, 超时=超时)


def run_script(
    source: str,
    store: RuntimeStore,
    logger_obj: Optional[logging.Logger] = None,
    context: Optional[Dict[str, Any]] = None,
    modules: Optional[Dict[str, Any]] = None,
    invoke=None,
) -> tuple[bool, str]:
    validate_script(source)
    if context is None or context.get("plugin_invocation") is None:
        from app_core.card_plugins import plugin_command_paths
        commands = plugin_command_paths(source)
        if commands:
            raise ScriptError("插件命令只能在插件模式的脚本卡片中执行：" + "、".join(commands))
    placeholder = unfilled_placeholder_error(source)
    if placeholder:
        raise ScriptError(placeholder)
    tree = parse_script(source)
    user_funcs = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    debug_variable_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            debug_variable_names.add(node.id)
        elif isinstance(node, ast.FunctionDef):
            debug_variable_names.add(node.name)
            debug_variable_names.update(arg.arg for arg in node.args.args)
            debug_variable_names.update(arg.arg for arg in node.args.posonlyargs)
            debug_variable_names.update(arg.arg for arg in node.args.kwonlyargs)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            debug_variable_names.add(str(node.name))
    tree = _ForCountWrap().visit(tree)
    plugin_invocation = (context or {}).get("plugin_invocation")
    tree = _GuardInsert().visit(tree)
    ast.fix_missing_locations(tree)
    runtime_logger = logger_obj or logger
    runtime_context = dict(context or {})
    host = CommandHost(store, runtime_context, runtime_logger, modules=modules, invoke=invoke)
    external_process = None

    def _read_image_resource(path):
        from task_workflow.script_resources import read_resource_bytes

        if plugin_invocation is not None:
            plugin_invocation.require_resource("image", path)
        data = read_resource_bytes(path, **host._resource_dirs())
        if data is None:
            raise ValueError("资源不存在：" + str(path))
        return data

    def _capture_image():
        from utils.capture.screenshot_helper import capture_window_frame

        hwnd = host.context.get("target_hwnd")
        if not hwnd:
            raise ValueError("截帧需要先绑定窗口")
        frame = capture_window_frame(hwnd)
        if frame is None:
            raise ValueError("窗口截图失败")
        return frame

    image_api = ImageApi(_read_image_resource, _capture_image)

    def _script_stop() -> bool:
        return host.should_stop()

    runtime_context["stop_checker"] = _script_stop
    host.context["stop_checker"] = _script_stop
    guard = _Guard(
        stop_checker=_script_stop,
        pause_checker=runtime_context.get("pause_checker"),
    )

    def _log(message: Any) -> None:
        execution_owner = runtime_context.get("executor")
        extra = {"lca_execution_log": True}
        if execution_owner is not None:
            extra["lca_execution_owner_id"] = id(execution_owner)
        runtime_logger.info(
            "[自定义脚本] %s",
            message,
            extra=extra,
        )

    def _ok(detail: Any = "") -> None:
        raise ScriptOutcome(True, str(detail or ""))

    def _fail(detail: Any = "") -> None:
        raise ScriptOutcome(False, str(detail or "判断失败"))

    def _is_user_func(func: Any) -> bool:
        if external_process is not None:
            return external_process.is_user_callback(func, user_funcs)
        name = str(getattr(func, "__name__", "") or "")
        return name in user_funcs and namespace.get(name) is func

    def _resolve_user_callback(target: Any) -> Any:
        callback = target
        if isinstance(target, str):
            if target not in user_funcs:
                raise ScriptError(f"回调请传入子程序，例如 回调={target}")
            callback = external_process.callback(target) if external_process is not None else namespace.get(target)
        if not callable(callback) or not _is_user_func(callback):
            raise ScriptError("回调请传入脚本中的子程序")
        return callback

    def _start_thread(目标: Any, 名字: Any = None) -> Any:
        func = 目标
        label = 名字
        if isinstance(目标, str):
            if 目标 not in user_funcs:
                raise ScriptError("多线程请传入子程序，例如 多线程(按W)")
            func = external_process.callback(目标) if external_process is not None else namespace.get(目标)
            if not callable(func):
                raise ScriptError(f"没有这个子程序：{目标}")
            label = 名字 or 目标
        if not callable(func) or not _is_user_func(func):
            raise ScriptError("多线程请传入子程序，例如 多线程(按W)")
        return host.多线程(func, label)

    namespace = _ScriptNamespace({
        "__builtins__": __builtins__,
        "__guard": guard,
        "_lca_guard": guard,
        "__iter_count": script_for_iterable,
        "变量": _VarsApi(store),
        "图像": image_api,
        "参数": PluginParameterView(runtime_context.get("plugin_invocation")),
        "输出": PluginOutputView(runtime_context.get("plugin_invocation")),
        "区域": _RegionApi(host),
        "上次": _StoreView(store),
        "文字": _StoreView(store, "ocr"),
        "找图": _CallableLast(host.找图, store, "image", host),
        "等图": _CallableLast(host.等图, store, "image", host),
        "找所有图": _CallableLast(host.找所有图, store, "image", host),
        "检测": _CallableLast(host.检测, store, "yolo", host),
        "框内点": host.框内点,
        "随机点": host.随机点,
        "距离": host.距离,
        "角度": host.角度,
        "等检测": _CallableLast(host.等检测, store, "yolo", host),
        "等检测消失": host.等检测消失,
        "持续检测": host.持续检测,
        "停止检测": host.停止检测,
        "持续找图": host.持续找图,
        "停止找图": host.停止找图,
        "多线程": _start_thread,
        "关闭线程": host.关闭线程,
        "线程状态": host.线程状态,
        "等待线程": host.等待线程,
        "线程结果": host.线程结果,
        "卡片": _CardView(store),
        "窗口": _WindowView(host),
        "输入设备": _InputDeviceView(host),
        "进程": _ProcessView(host),
        "网络": _NetworkView(host),
        "事件": _EventView(host),
        "热键": _HotkeyView(host, _resolve_user_callback),
        "定时器": _TimerView(host, _resolve_user_callback),
        "剪贴板": _ClipboardApi(),
        "组件": _ExternalComponentApi(host),
        "数据": _DataApi(),
        "性能": _PerformanceView(host),
        "大漠内存": _DmMemoryView(host),
        "大漠汇编": _DmAsmView(host),
        "点击": host.点击,
        "按下": host.按下,
        "松开": host.松开,
        "按住": host.按住,
        "连点": host.连点,
        "找色": host.找色,
        "移动": host.移动,
        "相对移动": host.相对移动,
        "鼠标位置": host.鼠标位置,
        "拖拽": host.拖拽,
        "滚轮": host.滚轮,
        "按键": host.按键,
        "输入": host.输入,
        "延时": host.延时,
        "等毫秒": host.等毫秒,
        "播放": host.播放,
        "停止播放": host.停止播放,
        "回放": host.回放,
        "暂停回放": host.暂停回放,
        "继续回放": host.继续回放,
        "停止回放": host.停止回放,
        "截图": _CallableLast(host.截图, store, "image", host),
        "等按键": host.等按键,
        "找字": host.找字,
        "找字库": host.找字库,
        "等字库": host.等字库,
        "等字库消失": host.等字库消失,
        "点字库": host.点字库,
        "等色": host.等色,
        "等文字": host.等文字,
        "等图消失": host.等图消失,
        "等色消失": host.等色消失,
        "等文字消失": host.等文字消失,
        "取色": host.取色,
        "比色": host.比色,
        "点文字": host.点文字,
        "点元素": host.点元素,
        "记录": _log,
        "成功": _ok,
        "失败": _fail,
        # 脚本帮助中的“模式=无”表示沿用线程执行模式。
        "无": None,
        # These Python names are internal targets of the Chinese aliases
        # above, not public script commands.
        "len": len,
        "int": int,
        "float": float,
        "str": str,
        "bool": bool,
        "min": min,
        "max": max,
        "abs": abs,
        "range": range,
        "长度": len,
        "整数": int,
        "小数": float,
        "到文本": str,
        "真假": bool,
        "最小": min,
        "最大": max,
        "绝对值": abs,
        "开方": script_sqrt,
        "平方根": script_sqrt,
        "正弦": script_sin,
        "余弦": script_cos,
        "限制": script_clamp,
        "范围": range,
        "枚举": enumerate,
        "配对": zip,
        "排序": script_sort,
        "四舍五入": script_round,
        "就近取整": script_nearest_int,
        "求和": script_sum,
        "全部": all,
        "任一": any,
        "随机": script_random,
        "包含": script_contains,
        "截取": script_slice,
        "替换": script_replace,
        "分割": script_split,
        "时间": script_now_ms,
        "JSON解析": script_json_parse,
        "JSON生成": script_json_dump,
        "字典获取": script_dict_get,
        "字典设置": script_dict_set,
        "列表追加": script_list_append,
        "列表弹出": script_list_pop,
        "类型": script_type,
        "断言": script_assert,
        "字典键": script_dict_keys,
        "字典值": script_dict_values,
        "列表合并": script_list_extend,
        "列表清空": script_list_clear,
        "开头是": script_startswith,
        "结尾是": script_endswith,
        "去空格": script_strip,
        "查找": script_find,
        "提取数字": script_extract_number,
        "Exception": Exception,
        "异常": Exception,
        "值错误": ValueError,
        "类型错误": TypeError,
        "运行错误": RuntimeError,
        "BaseException": BaseException,
        "ValueError": ValueError,
        "TypeError": TypeError,
        "RuntimeError": RuntimeError,
        "KeyError": KeyError,
        "IndexError": IndexError,
        "AttributeError": AttributeError,
        "ZeroDivisionError": ZeroDivisionError,
        "StopIteration": StopIteration,
        "NameError": NameError,
        "ArithmeticError": ArithmeticError,
        "AssertionError": AssertionError,
    })
    if plugin_invocation is not None:
        from task_workflow.card_plugin_runtime import guard_resource_command
        from app_core.card_plugins import RESOURCE_COMMAND_ARGUMENTS
        for name, (kind, parameter, _position, multiple) in RESOURCE_COMMAND_ARGUMENTS.items():
            if "." in name:
                continue
            command = dict.__getitem__(namespace, name)
            if isinstance(command, _CallableLast):
                command._callback = guard_resource_command(command._callback, plugin_invocation, kind, parameter, more_parameter="更多图片" if multiple else None)
            else:
                namespace[name] = guard_resource_command(command, plugin_invocation, kind, parameter, more_parameter="更多图片" if multiple else None)
        components = dict.__getitem__(namespace, "组件")
        components.加载 = guard_resource_command(components.加载, plugin_invocation, "component", "入口", component=True)
        components.运行 = guard_resource_command(components.运行, plugin_invocation, "component", "程序")
    for name in COMMAND_NAMES:
        value = dict.get(namespace, name)
        if value is not None:
            namespace.install_command(name, value)
    result = None
    previous_trace = None
    debugger = runtime_context.get("debugger")
    if debugger is not None and callable(getattr(debugger, "set_variable_names", None)):
        # 执行命名空间包含中文命令和完整 Python 运行时；只把脚本实际定义的
        # 变量交给调试器，避免变量面板被内部对象淹没。
        try:
            debugger.set_variable_names(debug_variable_names)
        except Exception:
            runtime_logger.debug("设置脚本调试变量白名单失败", exc_info=True)
    try:
        try:
            from app_core.script_environments import normalize_environment

            environment = normalize_environment(runtime_context.get("script_environment"))
            if environment["mode"] == "isolated":
                from task_workflow.script_process import ScriptProcess

                host.context["script_environment"] = environment
                external_process = ScriptProcess(namespace, host, guard, tree, debug_variable_names, _log)
            # 调试器仅在本次脚本执行期间安装逐行追踪，结束后恢复宿主线程原有设置。
            trace = getattr(debugger, "trace", None) if debugger is not None else None
            if callable(trace):
                previous_trace = sys.gettrace()
                if external_process is None:
                    def _script_trace(frame, event, arg):
                        if frame.f_code.co_filename != "<script>":
                            return None
                        return trace(frame, event, arg)
                    sys.settrace(_script_trace)
            if external_process is not None:
                result = external_process.run()
            else:
                exec(compile(tree, "<script>", "exec"), namespace, namespace)  # noqa: S102
                result = (True, "")
        except ScriptOutcome as outcome:
            result = (outcome.success, outcome.detail)
        except ScriptError:
            raise
        except AttributeError as exc:
            message = str(exc)
            name = getattr(exc, "name", "") or ""
            if "没有字段" in message:
                _raise_script_error(message, exc)
            _raise_script_error(f"没有字段: {name or message}", exc)
        except ZeroDivisionError as exc:
            _raise_script_error("除数不能为 0", exc)
        except TypeError as exc:
            message = str(exc)
            if "int" in message and ("literal" in message or "argument" in message):
                _raise_script_error("坐标必须是数字，文字请用 点文字()", exc)
            _raise_script_error(f"参数不对: {message}", exc)
        except ValueError as exc:
            message = str(exc)
            if message.startswith(("不允许", "未找到", "能力不可", "已停止", "点击缺少", "移动缺少", "拖拽缺少", "取色缺少", "框内点缺少", "随机点缺少", "距离缺少", "角度缺少", "开方", "多线程", "检测", "持续检测", "持续找图", "没有框", "停止检查", "暂停检查", "文字请用", "区域请写成", "没有这个区域", "宽和高", "策略只能", "区域名", "区域.设置", "单独一个", "宽高", "窗口", "没有当前", "没有可调整", "当前窗口", "脚本不能", "缺少资源", "回放", "不认识", "截图", "等按键", "外部组件", "变量名", "步长", "循环次数")):
                _raise_script_error(message, exc)
            _raise_script_error(f"运行失败: {message}", exc)
        except NameError as exc:
            name = getattr(exc, "name", None) or ""
            if name in _PLACEHOLDER_NAMES:
                _raise_script_error(unfilled_placeholder_error(source) or f"还没填写参数：{name}", exc)
            message = str(exc)
            for placeholder in _PLACEHOLDER_NAMES:
                if f"'{placeholder}'" in message:
                    _raise_script_error(unfilled_placeholder_error(source) or f"还没填写参数：{placeholder}", exc)
            if name:
                _raise_script_error(f"没有这个名字：{name}", exc)
            _raise_script_error(f"运行失败: {exc}", exc)
        except Exception as exc:
            message = str(exc)
            if "outside function" in message and "return" in message:
                _raise_script_error("不能单独写返回，请用 成功() 或 失败()", exc)
            _raise_script_error(f"运行失败: {exc}", exc)
    finally:
        pending = sys.exc_info()[1]
        cleanup_error = None
        try:
            host.close()
        except Exception as exc:
            cleanup_error = ScriptError(f"{pending}；{exc}" if pending is not None else str(exc))
        if external_process is not None:
            try:
                external_process.close()
            except Exception as exc:
                cleanup_error = ScriptError(f"{cleanup_error or pending}；{exc}" if cleanup_error or pending else str(exc))
        image_api.close()
        failure = host.thread_failure()
        if failure and cleanup_error is None:
            cleanup_error = ScriptError(f"线程失败: {failure}")
        if debugger is not None and callable(getattr(debugger, "finish", None)):
            try:
                if cleanup_error is not None or pending is not None:
                    # 有异常正在向外传播：以失败和异常文本收尾，避免用陈旧的 result
                    # 误报成功；同时保证异常路径上 finish 只在这里发生一次。
                    debugger.finish(False, str(cleanup_error or pending))
                else:
                    success = result[0] if isinstance(result, tuple) and result else None
                    detail = result[1] if isinstance(result, tuple) and len(result) > 1 else ""
                    debugger.finish(success, detail)
            except Exception:
                logger.debug("结束脚本调试器失败", exc_info=True)
        if callable(getattr(debugger, "trace", None)):
            try:
                sys.settrace(previous_trace)
            except Exception:
                sys.settrace(None)
        if cleanup_error is not None:
            raise cleanup_error
    return result if result is not None else (True, "")
