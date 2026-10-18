# -*- coding: utf-8 -*-
"""自定义脚本编辑器语法高亮，不依赖 Web 控件。"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from themes import get_theme_manager

from task_workflow.script_sandbox import COMMAND_NAMES, _EXCEPTION_NAMES
from task_workflow.script_image import IMAGE_METHODS

_KEYWORDS = (
    "导入", "从", "作为", "尝试", "捕获", "最终", "抛出", "匿名", "使用", "就是",
    "import", "from", "as", "try", "except", "finally", "raise", "lambda", "with",
    "否则如果",
    "如果",
    "否则",
    "循环",
    "当",
    "中断",
    "继续",
    "并且",
    "或者",
    "不是",
    "在",
    "是",
    "略过",
    "返回",
    "子程序",
    "函数",
    "if",
    "elif",
    "else",
    "for",
    "while",
    "break",
    "continue",
    "pass",
    "return",
    "and",
    "or",
    "not",
    "in",
    "is",
)
_CONSTANTS = ("真", "假", "空", "True", "False", "None")
_RUNTIME = ("变量", "上次", "文字", "找图", "检测", "卡片", "结果", "色", "数据", "剪贴板", "窗口", "组件", "区域", "图像")


def script_action_names():
    return (*COMMAND_NAMES, *(f"图像.{name}" for name in IMAGE_METHODS), "组件.加载", "组件.调用", "组件.读取", "组件.写入", "组件.运行", "组件.关闭",
            "变量.获取", "变量.设置", "变量.增加", "变量.存在", "变量.删除",
            "变量.全局获取", "变量.全局设置", "变量.全局增加", "变量.全局存在", "变量.全局删除",
            "数据.读取", "数据.写入", "数据.JSON读取", "数据.JSON写入", "数据.存在", "数据.删除",
            "区域.设置", "区域.获取", "区域.存在", "区域.删除", "区域.列表")


_ACTION_METHODS = (
    "获取",
    "设置",
    "增加",
    "存在",
    "删除",
    "全局获取",
    "全局设置",
    "全局增加",
    "全局存在",
    "全局删除",
    "列表",
    "设置分辨率",
    "加载",
    "调用",
    "读取",
    "写入",
    "运行",
    "关闭",
)
_BUILTINS = (
    "列表清空", "求和", "就近取整", "异常", "值错误", "类型错误", "运行错误",
    "随机",
    "开方",
    "平方根",
    "正弦",
    "余弦",
    "限制",
    "包含",
    "截取",
    "替换",
    "分割",
    "去空格",
    "查找",
    "提取数字",
    "时间",
    "绝对值",
    "到文本",
    "整数",
    "小数",
    "真假",
    "最小",
    "最大",
    "长度",
    "范围",
    "len",
    "int",
    "float",
    "str",
    "bool",
    "min",
    "max",
    "abs",
    "range",
    "enumerate",
    "zip",
    "sorted",
    "round",
    "all",
    "any",
    "list",
    "tuple",
    "dict",
    "set",
    "sum",
    "reversed",
    "枚举",
    "配对",
    "排序",
    "四舍五入",
    "全部",
    "任一",
    "JSON解析",
    "JSON生成",
    "字典获取",
    "字典设置",
    "列表追加",
    "列表弹出",
    "列表合并",
    "字典键",
    "字典值",
    "类型",
    "断言",
    "开头是",
    "结尾是",
)
_FIELDS = ("分数", "内容", "通过", "成功", "阈值", "类别", "路径", "列表", "类型", "句柄", "返回值", "退出码", "标准输出", "标准错误", "进程号", "x", "y", "横坐标", "纵坐标", "宽", "高", "宽度", "高度", "左", "上", "右", "下", "颜色", "红", "绿", "蓝")

_STATE_NONE = 0
_STATE_TRIPLE_DOUBLE = 1
_STATE_TRIPLE_SINGLE = 2

_COLOR_ROLES = ("keyword", "constant", "runtime", "action", "builtin", "string", "number", "comment")


def script_highlight_colors(dark: bool) -> Dict[str, str]:
    theme = "dark" if dark else "light"
    colors = get_theme_manager().THEME_COLORS[theme]
    return {role: colors[f"script_syntax_{role}"] for role in _COLOR_ROLES}


def is_dark_theme() -> bool:
    return get_theme_manager().is_dark_mode()


def _word_pattern(words: Tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)(?:%s)(?!\w)" % "|".join(re.escape(word) for word in words))


def _call_pattern(words: Tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(
        r"(?<!\w)(?:%s)(?=\s*[(\uff08])" % "|".join(re.escape(word) for word in words)
    )


class ScriptSyntaxHighlighter(QSyntaxHighlighter):
    """高亮自定义脚本允许的关键字、命令、运行时对象、字符串和注释。"""

    def __init__(self, document, dark=None) -> None:
        super().__init__(document)
        self._dark = is_dark_theme() if dark is None else bool(dark)
        self._formats = self._build_formats()
        self._keyword_re = _word_pattern(_KEYWORDS)
        self._constant_re = _word_pattern(_CONSTANTS)
        action_names = "|".join(re.escape(word) for word in script_action_names())
        method_names = "|".join(re.escape(word) for word in _ACTION_METHODS)
        runtime_names = "|".join(re.escape(word) for word in _RUNTIME)
        field_names = "|".join(re.escape(word) for word in _FIELDS)
        self._action_re = re.compile(
            r"(?<!\w)(?:(?:变量|组件|数据|区域)\.(?:%s)|%s)(?=\s*[(\uff08])" % (method_names, action_names)
        )
        self._runtime_re = re.compile(
            r"(?<!\w)(?:%s)(?:\.(?:\w+|%s))+|(?<!\w)(?:%s)(?=\s*\[)"
            % (runtime_names, field_names, runtime_names)
        )
        self._builtin_re = _call_pattern(_BUILTINS)
        self._exception_re = _word_pattern(_EXCEPTION_NAMES)
        self._number_re = re.compile(r"(?<!\w)\d+(?:\.\d+)?(?!\w)")

    def set_dark(self, dark: bool) -> None:
        if bool(dark) == self._dark:
            return
        self._dark = bool(dark)
        self._formats = self._build_formats()
        self.rehighlight()

    def _build_formats(self) -> Dict[str, QTextCharFormat]:
        colors = script_highlight_colors(self._dark)
        formats: Dict[str, QTextCharFormat] = {}
        for name, color in colors.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if name in {"keyword", "constant"}:
                fmt.setFontWeight(QFont.Weight.Bold)
            formats[name] = fmt
        return formats

    def highlightBlock(self, text: str) -> None:
        occupied = self._highlight_literals(text)
        self._highlight_tokens(text, occupied)

    def _highlight_literals(self, text: str) -> List[Tuple[int, int]]:
        occupied: List[Tuple[int, int]] = []
        previous = self.previousBlockState()
        self.setCurrentBlockState(_STATE_NONE)
        index = 0
        length = len(text)

        if previous == _STATE_TRIPLE_DOUBLE:
            index = self._close_triple(text, 0, '"""', _STATE_TRIPLE_DOUBLE, occupied)
        elif previous == _STATE_TRIPLE_SINGLE:
            index = self._close_triple(text, 0, "'''", _STATE_TRIPLE_SINGLE, occupied)

        while 0 <= index < length:
            if text.startswith('"""', index):
                index = self._open_triple(text, index, '"""', _STATE_TRIPLE_DOUBLE, occupied)
                continue
            if text.startswith("'''", index):
                index = self._open_triple(text, index, "'''", _STATE_TRIPLE_SINGLE, occupied)
                continue
            char = text[index]
            if char in {'"', "'"}:
                end = self._scan_quoted(text, index)
                self.setFormat(index, end - index, self._formats["string"])
                occupied.append((index, end))
                index = end
                continue
            if char == "#":
                self.setFormat(index, length - index, self._formats["comment"])
                occupied.append((index, length))
                break
            index += 1
        return occupied

    def _close_triple(
        self,
        text: str,
        start: int,
        quote: str,
        state: int,
        occupied: List[Tuple[int, int]],
    ) -> int:
        end = text.find(quote, start)
        if end < 0:
            self.setFormat(start, len(text) - start, self._formats["string"])
            occupied.append((start, len(text)))
            self.setCurrentBlockState(state)
            return len(text)
        end += len(quote)
        self.setFormat(start, end - start, self._formats["string"])
        occupied.append((start, end))
        return end

    def _open_triple(
        self,
        text: str,
        start: int,
        quote: str,
        state: int,
        occupied: List[Tuple[int, int]],
    ) -> int:
        end = text.find(quote, start + len(quote))
        if end < 0:
            self.setFormat(start, len(text) - start, self._formats["string"])
            occupied.append((start, len(text)))
            self.setCurrentBlockState(state)
            return len(text)
        end += len(quote)
        self.setFormat(start, end - start, self._formats["string"])
        occupied.append((start, end))
        return end

    def _scan_quoted(self, text: str, start: int) -> int:
        quote = text[start]
        index = start + 1
        while index < len(text):
            char = text[index]
            if char == "\\":
                index += 2
                continue
            if char == quote:
                return index + 1
            index += 1
        return len(text)

    def _highlight_tokens(self, text: str, occupied: List[Tuple[int, int]]) -> None:
        rules = (
            (self._keyword_re, "keyword"),
            (self._constant_re, "constant"),
            (self._runtime_re, "runtime"),
            (self._action_re, "action"),
            (self._builtin_re, "builtin"),
            (self._exception_re, "builtin"),
            (self._number_re, "number"),
        )
        for pattern, name in rules:
            for match in pattern.finditer(text):
                start, end = match.span()
                if self._overlaps(start, end, occupied):
                    continue
                self.setFormat(start, end - start, self._formats[name])

    @staticmethod
    def _overlaps(start: int, end: int, occupied: List[Tuple[int, int]]) -> bool:
        for left, right in occupied:
            if start < right and end > left:
                return True
        return False
