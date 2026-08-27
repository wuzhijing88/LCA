# -*- coding: utf-8 -*-
"""受控自定义脚本：中文命令调用现有能力，禁止 import 和直接读写文件。"""

from __future__ import annotations

import ast
import logging
import math
import random
import time
from typing import Any, Dict, Optional

from task_workflow.runtime_store import RuntimeStore
from task_workflow.script_commands import RESULT_FIELD_ALIASES, CommandHost, ScriptResult

logger = logging.getLogger(__name__)

MAX_LOOP = 2000
MAX_OPS = 10000
MAX_SECONDS = 120.0
MAX_SOURCE_CHARS = 20000

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
    "激活",
    "播放",
    "停止播放",
    "记录",
    "成功",
    "失败",
)
_BUILTIN_CALLS = (
    "len",
    "int",
    "float",
    "str",
    "bool",
    "min",
    "max",
    "abs",
    "range",
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
)

_RESULT_METHODS = frozenset({"点", "随机点"})
_EXCEPTION_NAMES = (
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
)

ALLOWED_CALLS = {
    "变量.获取",
    "变量.设置",
    "变量.增加",
    "剪贴板.获取",
    "剪贴板.设置",
    *COMMAND_NAMES,
    *_BUILTIN_CALLS,
    *_EXCEPTION_NAMES,
}

ALLOWED_CALL_ROOTS = frozenset({*COMMAND_NAMES, *_BUILTIN_CALLS, *_EXCEPTION_NAMES})

_CN_IDENT_MAP = {
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

_FORBIDDEN_NODE_CN = {
    "Import": "导入",
    "ImportFrom": "导入",
    "AsyncFunctionDef": "异步函数",
    "ClassDef": "类定义",
    "With": "with 语句",
    "AsyncWith": "异步 with",
    "Try": "try 语句",
    "Raise": "抛出异常",
    "Lambda": "匿名函数",
    "Await": "await",
    "Yield": "yield",
    "YieldFrom": "yield from",
    "Global": "global",
    "Nonlocal": "nonlocal",
    "Delete": "删除",
    "AnnAssign": "类型注解",
    "NamedExpr": "海象运算符",
    "Attribute": "属性访问",
    "Return": "返回，请改用 成功() 或 失败()",
}

_SYNTAX_CN = (
    ("'break' outside loop", "中断 只能写在循环里"),
    ("'continue' not properly in loop", "继续 只能写在循环里"),
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

ALLOWED_NODES = (
    ast.Module,
    ast.Expr,
    ast.Assign,
    ast.AugAssign,
    ast.If,
    ast.For,
    ast.While,
    ast.Break,
    ast.Continue,
    ast.Pass,
    ast.FunctionDef,
    ast.arguments,
    ast.arg,
    ast.Return,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Del,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Set,
    ast.Subscript,
    ast.Slice,
    ast.Attribute,
    ast.Call,
    ast.keyword,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
    ast.Try,
    ast.ExceptHandler,
    ast.Raise,
    ast.JoinedStr,
    ast.FormattedValue,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.comprehension,
    ast.IfExp,
)


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
        max_ops: int = MAX_OPS,
        timeout: float = MAX_SECONDS,
        stop_checker=None,
        pause_checker=None,
        max_loop: int = MAX_LOOP,
        hang: bool = False,
    ) -> None:
        self.ops = 0
        self.loops = 0
        self.max_ops = max_ops
        self.max_loop = max_loop
        self.hang = True
        self.deadline = None
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
            if self.deadline is not None:
                self.deadline += 0.05


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


def cursor_in_string_or_comment(line: str, column: int) -> bool:
    text = str(line or "")
    limit = max(0, min(int(column), len(text)))
    quote = None
    escape = False
    index = 0
    while index < limit:
        char = text[index]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char == "#":
            return True
        if char in {'"', "'"}:
            quote = char
        index += 1
    return quote is not None


def normalize_script_punctuation(source: str) -> str:
    """把输入里的中文/全角标点一律换成代码用的英文标点。"""
    return "".join(map_script_punct_char(char) for char in str(source or ""))


def translate_cn_script(source: str) -> str:
    """把中文关键字/内置名译成 Python，字符串和注释里不改。旧英文写法原样保留。"""
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
            if ident == "是":
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
        "偏移横坐标",
        "偏移纵坐标",
        "偏移x",
        "偏移y",
        "随机",
        "随机横坐标",
        "随机纵坐标",
        "随机x",
        "随机y",
        "区域",
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
        "横坐标",
        "纵坐标",
        "起点横坐标",
        "起点纵坐标",
        "终点横坐标",
        "终点纵坐标",
        "x",
        "y",
        "x1",
        "y1",
        "x2",
        "y2",
    }
)
_PLACEHOLDER_HINTS = {
    "文件": "用资源栏导入，或写成 \"提示.wav\"",
    "等待": "写成 真 或 假。真是播完再往下，假是接着跑",
    "图片": "用工具栏「截图」选图，或写成 \"确定.png\"",
    "图片2": "第二张备选图。多张图找到其中一张即成功，阈值仍写 阈值=",
    "模型": "写成 onnx 路径，例如 \"yolo/xxx.onnx\"",
    "颜色": "用「取色」，或写成 \"255,0,0\"",
    "目标": "写成 图，或 \"确定\"",
    "条件": "插入找图/检测，或写成 图",
    "文本": "写成要输入的文字，例如 \"你好\"",
    "内容": "写成要记录的内容",
    "说明": "写成失败原因，例如 \"没找到\"",
    "名称": "写成控件名，或用「拾取元素」",
    "秒": "写成等待秒数，例如 0.3；随机时长写成 (0.2, 0.6)",
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
    "偏移横坐标": "写成像素，正数向右",
    "偏移纵坐标": "写成像素，正数向下",
    "偏移x": "写成像素，正数向右",
    "偏移y": "写成像素，正数向下",
    "随机": "写成随机半径，例如 5。和偏移一起写时先固定偏移再抖",
    "区域": "用工具栏「框选区域」，或写成 (横坐标, 纵坐标, 宽, 高)",
    "键": "写成 \"左键\" 或 \"右键\"",
    "阈值": "写成 0 到 1 的小数，例如 0.8",
    "方向": "写成 \"向下\" 或 \"向上\"",
    "随机横坐标": "写成 X 随机范围，例如 5",
    "随机纵坐标": "写成 Y 随机范围，例如 5",
    "横坐标": "用「取坐标」，或写成数字",
    "纵坐标": "用「取坐标」，或写成数字",
    "起点横坐标": "用「取坐标」，或写成数字",
    "起点纵坐标": "用「取坐标」，或写成数字",
    "终点横坐标": "用「取坐标」，或写成数字",
    "终点纵坐标": "用「取坐标」，或写成数字",
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
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            call_funcs.add(id(node.func))
    found = []
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        if id(node) in call_funcs:
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
                scan(stmt.body)
                scan(stmt.orelse)

    scan(tree.body)
    return found


class _GuardInsert(ast.NodeTransformer):
    def visit(self, node):
        node = super().visit(node)
        if isinstance(node, ast.stmt) and not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            guard_call = ast.Expr(
                value=ast.Call(func=ast.Name(id="__guard", ctx=ast.Load()), args=[], keywords=[])
            )
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
                    value=ast.Name(id="__guard", ctx=ast.Load()),
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


class _VarsApi:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    def 获取(self, name: Any, default: Any = None) -> Any:
        return self._store.get_var(name, default)

    def 设置(self, name: Any, value: Any) -> Any:
        return self._store.set_var(name, value)

    def 增加(self, name: Any, step: Any = 1) -> Any:
        return self._store.inc_var(name, step)


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
            return _wrap(self._payload[key])
        raise ScriptError(f"没有字段: {name}")

    def __getitem__(self, key: Any) -> Any:
        if isinstance(self._payload, dict):
            return _wrap(self._payload[key])
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
    def __setitem__(self, key, value):
        current = dict.get(self, key)
        if isinstance(current, _CommandSlot):
            current.bind(value)
            return
        dict.__setitem__(self, key, value)

    def install_command(self, name: str, callback: Any) -> None:
        dict.__setitem__(self, name, callback if isinstance(callback, _CommandSlot) else _CommandSlot(callback))


def validate_script(source: str) -> None:
    text = str(source or "")
    if len(text) > MAX_SOURCE_CHARS:
        raise ScriptError("内容过长")
    try:
        tree = parse_script(text)
    except SyntaxError as exc:
        raise ScriptError(f"语法错误: {_syntax_error_text(exc)}", lineno=getattr(exc, "lineno", None)) from exc
    user_funcs = set()
    returns_in_func = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            user_funcs.add(node.name)
            if node.name in _PROTECTED_FUNC_NAMES:
                raise ScriptError(f"不能用命令名定义子程序：{node.name}", lineno=getattr(node, "lineno", None))
            for child in ast.walk(node):
                if isinstance(child, ast.Return):
                    returns_in_func.add(id(child))
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            name = type(node).__name__
            raise ScriptError(f"不允许使用 {_FORBIDDEN_NODE_CN.get(name, name)}", lineno=getattr(node, "lineno", None))
        if isinstance(node, ast.Return) and id(node) not in returns_in_func:
            raise ScriptError("不能单独写返回，请用 成功() 或 失败()", lineno=getattr(node, "lineno", None))
        if isinstance(node, ast.Name) and "__" in node.id:
            raise ScriptError("禁止使用双下划线名称", lineno=getattr(node, "lineno", None))
        if isinstance(node, ast.Attribute):
            if "__" in node.attr:
                raise ScriptError("禁止访问双下划线属性", lineno=getattr(node, "lineno", None))
        if isinstance(node, ast.Call):
            path = _call_path(node.func)
            method = path.split(".")[-1] if path else ""
            if (
                path not in ALLOWED_CALLS
                and path.split(".")[0] not in ALLOWED_CALL_ROOTS
                and path not in user_funcs
                and method not in _RESULT_METHODS
            ):
                raise ScriptError(f"不允许调用: {path or type(node.func).__name__}", lineno=getattr(node, "lineno", None))
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for name in _assigned_names(target):
                    if name in _PROTECTED_ASSIGN_NAMES:
                        raise ScriptError(f"不能给命令名赋值：{name}", lineno=getattr(node, "lineno", None))
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            if node.target.id in _PROTECTED_ASSIGN_NAMES:
                raise ScriptError(f"不能给命令名赋值：{node.target.id}", lineno=getattr(node, "lineno", None))


_PROTECTED_ASSIGN_NAMES = frozenset(
    {
        *_BUILTIN_CALLS,
        "range",
        "len",
        "int",
        "float",
        "str",
        "bool",
        "min",
        "max",
        "abs",
        "True",
        "False",
        "None",
    }
)
_PROTECTED_FUNC_NAMES = frozenset({*COMMAND_NAMES, *_PROTECTED_ASSIGN_NAMES})


def _assigned_names(target: ast.AST) -> list:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names = []
        for item in target.elts:
            names.extend(_assigned_names(item))
        return names
    return []


def _attr_path(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attr_path(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _call_path(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _attr_path(node)
    return ""


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


def _is_int_range_bound(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return value.is_integer()
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("+", "-")):
            text = text[1:]
        return bool(text) and text.isdigit()
    return False


def script_random(*args: Any) -> Any:
    if not args:
        return random.random()
    if len(args) == 1:
        return random.randint(0, max(0, int(args[0]) - 1)) if int(args[0]) > 0 else 0
    low, high = args[0], args[1]
    if _is_int_range_bound(low) and _is_int_range_bound(high):
        start, end = int(low), int(high)
        if end < start:
            start, end = end, start
        return random.randint(start, end)
    start, end = float(low), float(high)
    if end < start:
        start, end = end, start
    return random.uniform(start, end)


def script_sqrt(value: Any) -> float:
    number = float(value)
    if number < 0:
        raise ValueError("开方不能是负数")
    return number ** 0.5


def script_sin(degrees: Any) -> float:
    return math.sin(math.radians(float(degrees)))


def script_cos(degrees: Any) -> float:
    return math.cos(math.radians(float(degrees)))


def script_clamp(value: Any, 下限: Any, 上限: Any) -> float:
    number = float(value)
    low = float(下限)
    high = float(上限)
    if low > high:
        low, high = high, low
    return min(high, max(low, number))


def script_contains(text: Any, part: Any) -> bool:
    return str(part or "") in str(text or "")


def script_slice(text: Any, start: Any, length: Any = None) -> str:
    source = str(text or "")
    begin = max(0, int(start or 1) - 1)
    if length is None or length == "":
        return source[begin:]
    return source[begin : begin + max(0, int(length))]


def script_replace(text: Any, old: Any, new: Any, 次数: Any = None) -> str:
    source = str(text or "")
    if 次数 is None or 次数 == "":
        return source.replace(str(old or ""), str(new or ""))
    return source.replace(str(old or ""), str(new or ""), int(次数))


def script_strip(text: Any) -> str:
    return str(text or "").strip()


def script_find(text: Any, part: Any) -> int:
    index = str(text or "").find(str(part or ""))
    return 0 if index < 0 else index + 1


def script_extract_number(text: Any) -> Any:
    import re

    match = re.search(r"-?\d+(?:\.\d+)?", str(text or ""))
    if not match:
        return 0
    raw = match.group(0)
    return float(raw) if "." in raw else int(raw)


def script_split(text: Any, 分隔符: Any = None) -> list:
    source = str(text or "")
    if 分隔符 is None or 分隔符 == "":
        return source.split()
    return source.split(str(分隔符))


def script_now_ms() -> int:
    return int(time.monotonic() * 1000)


def clipboard_get() -> str:
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            return str(app.clipboard().text() or "")
    except Exception:
        pass
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                return str(win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT) or "")
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return ""
    return ""


def clipboard_set(text: Any) -> str:
    value = str(text or "")
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.clipboard().setText(value)
            return value
    except Exception:
        pass
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(value)
        finally:
            win32clipboard.CloseClipboard()
    except Exception as exc:
        raise ScriptError(f"剪贴板写入失败: {exc}") from exc
    return value


class _WindowView:
    def __init__(self, host) -> None:
        self._host = host

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise ScriptError("禁止访问该属性")
        width, height = self._host.客户区尺寸()
        if name in {"宽", "宽度"}:
            return width
        if name in {"高", "高度"}:
            return height
        raise ScriptError(f"没有字段: {name}")


class _ClipboardApi:
    def 获取(self) -> str:
        return clipboard_get()

    def 设置(self, text: Any) -> str:
        return clipboard_set(text)


def run_script(
    source: str,
    store: RuntimeStore,
    logger_obj: Optional[logging.Logger] = None,
    context: Optional[Dict[str, Any]] = None,
    modules: Optional[Dict[str, Any]] = None,
    invoke=None,
) -> tuple[bool, str]:
    validate_script(source)
    placeholder = unfilled_placeholder_error(source)
    if placeholder:
        raise ScriptError(placeholder)
    tree = parse_script(source)
    tree = _GuardInsert().visit(tree)
    ast.fix_missing_locations(tree)
    runtime_logger = logger_obj or logger
    runtime_context = dict(context or {})
    host = CommandHost(store, runtime_context, runtime_logger, modules=modules, invoke=invoke)

    def _script_stop() -> bool:
        return host.should_stop()

    runtime_context["stop_checker"] = _script_stop
    host.context["stop_checker"] = _script_stop
    hang = callable(host._outer_stop)
    guard = _Guard(
        stop_checker=_script_stop,
        pause_checker=runtime_context.get("pause_checker"),
        hang=hang,
    )
    host.context["_guard"] = guard
    host.context["_script_deadline"] = guard.deadline

    def _log(message: Any) -> None:
        runtime_logger.info("[自定义脚本] %s", message)

    def _ok(detail: Any = "") -> None:
        raise ScriptOutcome(True, str(detail or ""))

    def _fail(detail: Any = "") -> None:
        raise ScriptOutcome(False, str(detail or "判断失败"))

    def _start_thread(目标: Any, 名字: Any = None) -> Any:
        func = 目标
        label = 名字
        if isinstance(目标, str):
            func = namespace.get(目标)
            if not callable(func):
                raise ScriptError(f"没有这个子程序：{目标}")
            label = 名字 or 目标
        if not callable(func):
            raise ScriptError("多线程请传入子程序，例如 多线程(按W)")
        return host.多线程(func, label)

    namespace = _ScriptNamespace({
        "__builtins__": {},
        "__guard": guard,
        "变量": _VarsApi(store),
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
        "卡片": _CardView(store),
        "窗口": _WindowView(host),
        "剪贴板": _ClipboardApi(),
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
        "激活": host.激活,
        "播放": host.播放,
        "停止播放": host.停止播放,
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
        "随机": script_random,
        "包含": script_contains,
        "截取": script_slice,
        "替换": script_replace,
        "分割": script_split,
        "时间": script_now_ms,
        "去空格": script_strip,
        "查找": script_find,
        "提取数字": script_extract_number,
        "Exception": Exception,
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
    })
    for name in COMMAND_NAMES:
        value = dict.get(namespace, name)
        if value is not None:
            namespace.install_command(name, value)
    try:
        try:
            exec(compile(tree, "<script>", "exec"), namespace, namespace)  # noqa: S102
        except ScriptOutcome as outcome:
            return outcome.success, outcome.detail
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
            if message.startswith(("不允许", "未找到", "能力不可", "已停止", "执行超时", "点击缺少", "移动缺少", "拖拽缺少", "取色缺少", "框内点缺少", "随机点缺少", "距离缺少", "角度缺少", "开方", "多线程", "检测", "持续检测", "持续找图", "没有框", "停止检查", "暂停检查", "文字请用", "区域请写成")):
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
        return True, ""
    finally:
        host.close()
