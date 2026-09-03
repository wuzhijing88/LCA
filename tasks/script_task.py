# -*- coding: utf-8 -*-
"""自定义脚本：用中文命令调用现有找图、点击、按键等能力。"""

from __future__ import annotations

import html
import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

TASK_TYPE = "自定义脚本"
TASK_NAME = "自定义脚本"
REQUIRES_INPUT_LOCK = True
SUPPORTED_CONNECTION_TYPES = frozenset({"sequential", "success", "failure"})

DEFAULT_SCRIPT_SOURCE = (
    "图 = 等图(\"确定.png\", 超时=8)\n"
    "如果 图:\n"
    "    延时(0.3)\n"
    "    点击(图)\n"
    "否则:\n"
    "    失败(\"没找到确定\")\n"
)
SCRIPT_PLACEHOLDER = (
    "图 = 等图(\"确定.png\", 超时=8)\n"
    "如果 图:\n"
    "    延时(0.3)\n"
    "    点击(图)\n"
    "否则:\n"
    "    失败(\"没找到确定\")"
)
SCRIPT_INSERT_GROUPS = (
    {
        "title": "动作",
        "items": (
            {
                "name": "找图",
                "signature": (
                    "找图(图片, 阈值=0.8, 点击=假, 双击=假, 偏移x=0, 偏移y=0, 随机=0)\n"
                    "找图(图片1, 图片2, 阈值=0.8)\n"
                    "找图(图片, 区域=(x, y, 宽, 高))"
                ),
                "params": (
                    ("图片", "阈值=0.8", "点击=假", "双击=假", "偏移x=0", "偏移y=0", "随机=0"),
                    ("图片", "图片2", "阈值=0.8", "点击=假", "双击=假", "偏移x=0", "偏移y=0", "随机=0"),
                    ("图片", "阈值=0.8", "点击=假", "区域=(x, y, 宽, 高)", "双击=假", "偏移x=0", "偏移y=0", "随机=0"),
                ),
                "note": "当前窗口找图。可写多张图，找到第一张即成功。工具栏「截图」每次存新文件，在找图行上再截会追加。点击=真 时找到后立刻点。",
                "kind": "expr",
                "snippet": "找图(图片, 阈值=0.8, 点击=假, 双击=假, 偏移x=0, 偏移y=0, 随机=0)",
            },
            {
                "name": "点击",
                "signature": (
                    "点击()\n"
                    "点击(目标, 双击=假, 偏移x=0, 偏移y=0, 随机=0)\n"
                    "点击(x, y, 双击=假, 偏移x=0, 偏移y=0, 随机=0)"
                ),
                "params": (
                    (),
                    ("目标", "双击=假", "偏移x=0", "偏移y=0", "随机=0"),
                    ("x", "y"),
                    ("x", "y", '键="右键"'),
                    ("x", "y", "双击=假", "偏移x=0", "偏移y=0", "随机=0"),
                    ("x", "y", '键="右键"', "双击=假", "偏移x=0", "偏移y=0", "随机=0"),
                ),
                "note": "可点找图或检测结果：点击(图)、点击(结果, 键=\"右键\")。框内比例点用 框内点(结果, 0.5, 0.85) 或 结果.点(0.5, 0.85)。偏移是固定像素，再写随机= 就是固定偏移后再抖。文字请用 点文字()。不写参数时点上次成功位置。",
                "kind": "expr",
                "snippet": "点击(目标, 双击=假, 偏移x=0, 偏移y=0, 随机=0)",
            },
            {
                "name": "移动",
                "signature": "移动(目标)  /  移动(x, y)",
                "params": (("目标",), ("x", "y")),
                "note": "把鼠标移到检测/找图结果或坐标，不点击。",
                "snippet": "移动(x, y)",
            },
            {
                "name": "按键",
                "signature": '按键("Ctrl+C")  /  按键("W", 秒=0.4)  /  按键("W", 动作="按下")',
                "params": (("按键",), ("按键", "秒=0.4"), ("按键", '动作="按下"'), ("按键", '动作="松开"'), ("按键", "秒=(0.2, 0.6)")),
                "note": "点按一下。秒= 是按住多久再松开，写 (0.2, 0.6) 或 随机(0.2, 0.6) 就是随机时长。动作=按下/松开 只做一半，和鼠标同一套。",
                "snippet": "按键(按键)",
            },
            {
                "name": "输入",
                "signature": '输入("文本")  /  输入("文本", 方式="粘贴")',
                "params": (("文本",), ("文本", '方式="粘贴"')),
                "note": "往当前焦点输入文字。方式=粘贴 走剪贴板 Ctrl+V，适合长文本；默认仿真逐字输入。",
                "snippet": "输入(文本)",
            },
            {
                "name": "延时",
                "signature": "延时(秒)",
                "params": ("秒",),
                "note": "等待秒数，可被停止打断。",
                "snippet": "延时(秒)",
            },
            {
                "name": "找字",
                "signature": '找字()  /  找字(目标="金币")  /  找字(目标="金币", 区域=(x, y, 宽, 高))',
                "params": ((), ('目标="金币"',), ('目标="金币"', "区域=(x, y, 宽, 高)")),
                "note": "默认识别整个窗口。写了目标就按是否包含该文字判成功。",
                "kind": "expr",
                "snippet": "找字(目标)",
            },
            {
                "name": "找字库",
                "signature": '找字库(字库="ui.txt")  /  找字库(目标="确定", 字库="ui.txt", 颜色="ffffff-101010", 相似度=0.9)',
                "params": (
                    ('字库="ui.txt"',),
                    ('目标="确定"', '字库="ui.txt"', '颜色="ffffff-101010"', "相似度=0.9"),
                    ('目标="确定"', '字库="ui.txt"', "区域=(x, y, 宽, 高)"),
                ),
                "note": "用点阵字库识别，兼容大漠字库格式。留空目标则识别全部；颜色按大漠 RRGGBB-偏色，留空则自动二值化。",
                "kind": "expr",
                "snippet": '找字库(目标="确定", 字库="ui.txt")',
            },
            {
                "name": "点字库",
                "signature": '点字库(目标, 字库="ui.txt")  /  点字库(目标, 字库="ui.txt", 颜色="ffffff-101010")',
                "params": (
                    ("目标", '字库="ui.txt"'),
                    ("目标", '字库="ui.txt"', '颜色="ffffff-101010"', "相似度=0.9"),
                ),
                "note": "先用字库找字再点击。",
                "kind": "expr",
                "snippet": '点字库(目标, 字库="ui.txt")',
            },
            {
                "name": "等字库",
                "signature": '等字库(目标="确定", 字库="ui.txt", 超时=8)',
                "params": (('目标="确定"', '字库="ui.txt"', "超时=8"),),
                "note": "超时秒内反复用字库找字。",
                "kind": "expr",
                "snippet": '等字库(目标="确定", 字库="ui.txt")',
            },
            {
                "name": "等字库消失",
                "signature": '等字库消失(目标="确定", 字库="ui.txt", 超时=8)',
                "params": (('目标="确定"', '字库="ui.txt"', "超时=8"),),
                "note": "等到字库认不到这段字。",
                "kind": "expr",
                "snippet": '等字库消失(目标="确定", 字库="ui.txt")',
            },
            {
                "name": "检测",
                "signature": '检测(模型)  /  检测(模型, 类别="敌人", 阈值=0.5, 策略="最近")  /  检测(模型, 类别="敌人", 区域=(x, y, 宽, 高))',
                "params": (
                    ("模型",),
                    ("模型", '类别="敌人"', "阈值=0.5", '策略="最近"'),
                    ("模型", '类别="敌人"', "阈值=0.5", '策略="最近"', "区域=(x, y, 宽, 高)"),
                ),
                "note": "跟画布 YOLO 卡的「原生/插件」。模型和类别跟卡片一样，也可写成 检测(\"yolo/xxx.onnx\", 类别=\"敌人\")。只识别，不点；要点写 点击(结果)。",
                "kind": "expr",
                "snippet": "检测(模型)",
            },
            {
                "name": "框内点",
                "signature": "框内点(目标, 横向=0.5, 纵向=0.5)  /  目标.点(横向, 纵向)",
                "params": (("目标", "横向=0.5", "纵向=0.5"),),
                "note": "按框算比例点，可不用。复杂落点请自己写：目标.左 + 目标.宽 * 小数，再用 整数、限制、开方、角度。",
                "kind": "expr",
                "snippet": "框内点(目标, 横向=0.5, 纵向=0.5)",
            },
            {
                "name": "随机点",
                "signature": "随机点(目标, 边距=2)  /  目标.随机点(边距)",
                "params": (("目标", "边距=2"),),
                "note": "在检测框内随机取一点，边距是离边多少像素。",
                "kind": "expr",
                "snippet": "随机点(目标, 边距=2)",
            },
            {
                "name": "找色",
                "signature": '找色(颜色, 点击=假)  /  找色(颜色, 区域=(x, y, 宽, 高), 双击=假, 偏移x=0, 偏移y=0, 随机=0)',
                "params": (
                    ("颜色", "点击=假", "双击=假", "偏移x=0", "偏移y=0", "随机=0"),
                    ("颜色", "点击=假", "区域=(x, y, 宽, 高)", "双击=假", "偏移x=0", "偏移y=0", "随机=0"),
                ),
                "note": "在当前窗口找颜色。单点写 红,绿,蓝；多点写 红,绿,蓝|偏移X,偏移Y,红,绿,蓝。工具栏「取色」可连点再完成。点击=真 时找到后立刻点。",
                "kind": "expr",
                "snippet": "找色(颜色, 点击=假)",
            },
            {
                "name": "拖拽",
                "signature": "拖拽(起点, 终点)  /  拖拽(x1, y1, x2, y2)",
                "params": (("起点", "终点"), ("x1", "y1", "x2", "y2")),
                "note": "从起点拖到终点。可传检测结果或 框内点：拖拽(结果, 框内点(结果, 0.1, 0.5))。",
                "snippet": "拖拽(x1, y1, x2, y2)",
            },
            {
                "name": "滚轮",
                "signature": '滚轮(方向="向下", 步数=3)  /  滚轮(目标, 方向="向下")  /  滚轮(步数, x, y)',
                "params": (('方向="向下"', "步数=3"), ("目标", '方向="向下"', "步数=3"), ("步数", "x", "y")),
                "note": "滚动鼠标滚轮。可先移到检测结果再滚：滚轮(结果, 方向=\"向下\")。正数或向下为往下，负数或向上为往上。",
                "kind": "stmt",
                "snippet": '滚轮(方向="向下", 步数=3)',
            },
            {
                "name": "点文字",
                "signature": '点文字(目标, 点击=真, 键="左键")  /  点文字(目标, 双击=假, 偏移x=0, 偏移y=0, 随机=0)',
                "params": (
                    ("目标", "点击=真", '键="左键"', "双击=假", "偏移x=0", "偏移y=0", "随机=0"),
                    ("目标", "点击=真", "区域=(x, y, 宽, 高)", "双击=假", "偏移x=0", "偏移y=0", "随机=0"),
                ),
                "note": "先找字再点找到的文字。偏移和随机与点击相同。",
                "kind": "expr",
                "snippet": "点文字(目标)",
            },
            {
                "name": "点元素",
                "signature": "点元素(名称, 点击=真)",
                "params": (("名称", "点击=真"),),
                "note": "按控件名称点击界面元素。",
                "kind": "expr",
                "snippet": "点元素(名称)",
            },
            {
                "name": "等图",
                "signature": "等图(图片, 超时=8, 间隔=0.3)",
                "params": (("图片", "超时=8", "间隔=0.3"),),
                "note": "超时秒内反复找图，找到就返回。间隔是每次查找之间的等待。",
                "kind": "expr",
                "snippet": "等图(图片, 超时=8, 间隔=0.3)",
            },
            {
                "name": "等色",
                "signature": "等色(颜色, 超时=8, 间隔=0.3)",
                "params": (("颜色", "超时=8", "间隔=0.3"),),
                "note": "超时秒内反复找色。",
                "kind": "expr",
                "snippet": "等色(颜色, 超时=8, 间隔=0.3)",
            },
            {
                "name": "等文字",
                "signature": '等文字(目标="金币", 超时=8)',
                "params": (('目标="金币"', "超时=8", "间隔=0.3"),),
                "note": "超时秒内反复找字。",
                "kind": "expr",
                "snippet": "等文字(目标, 超时=8)",
            },
            {
                "name": "等图消失",
                "signature": "等图消失(图片, 超时=8, 间隔=0.3)",
                "params": (("图片", "超时=8", "间隔=0.3"),),
                "note": "等到这张图找不到。弹窗关掉、进度条走完用这个。",
                "kind": "expr",
                "snippet": "等图消失(图片, 超时=8, 间隔=0.3)",
            },
            {
                "name": "等色消失",
                "signature": "等色消失(颜色, 超时=8, 间隔=0.3)",
                "params": (("颜色", "超时=8", "间隔=0.3"),),
                "note": "等到这个颜色找不到。",
                "kind": "expr",
                "snippet": "等色消失(颜色, 超时=8, 间隔=0.3)",
            },
            {
                "name": "等文字消失",
                "signature": "等文字消失(目标, 超时=8)",
                "params": (("目标", "超时=8", "间隔=0.3"),),
                "note": "等到这段字认不到。",
                "kind": "expr",
                "snippet": "等文字消失(目标, 超时=8)",
            },
            {
                "name": "等检测",
                "signature": '等检测(模型, 超时=8)  /  等检测(模型, 类别="敌人", 超时=8, 间隔=0.3)',
                "params": (("模型", "超时=8", "间隔=0.3"), ("模型", '类别="敌人"', "超时=8", "间隔=0.3")),
                "note": "超时秒内反复检测，出现就返回结果。可再写 阈值、策略、区域。",
                "kind": "expr",
                "snippet": "等检测(模型, 超时=8, 间隔=0.3)",
            },
            {
                "name": "等检测消失",
                "signature": '等检测消失(模型, 超时=8)  /  等检测消失(模型, 类别="敌人", 超时=8, 间隔=0.3)',
                "params": (("模型", "超时=8", "间隔=0.3"), ("模型", '类别="敌人"', "超时=8", "间隔=0.3")),
                "note": "等到这个类别检测不到。",
                "kind": "expr",
                "snippet": "等检测消失(模型, 超时=8, 间隔=0.3)",
            },
            {
                "name": "持续检测",
                "signature": '持续检测(模型, 间隔=0.3)  /  持续检测(模型, 类别="敌人", 间隔=0.3, 阈值=0.5)',
                "params": (("模型", "间隔=0.3"), ("模型", '类别="敌人"', "间隔=0.3", "阈值=0.5")),
                "note": "必须写模型，路径和画布 YOLO 卡一样，例如 \"yolo/xxx.onnx\"。后台持续识别，结果写进 检测。主流程或子程序里读 检测、检测.列表，不要再写 检测()。不会自动点。停止检测() 或脚本结束会停。",
                "example": (
                    '持续检测("yolo/xxx.onnx", 间隔=0.2)\n'
                    "当 真:\n"
                    "    循环 目标 在 检测.列表:\n"
                    '        如果 目标.类别 是 "怪物":\n'
                    "            点击(目标.x, 目标.y)\n"
                    "            中断\n"
                    "    延时(0.05)"
                ),
                "kind": "expr",
                "snippet": "持续检测(模型, 间隔=0.3)",
            },
            {
                "name": "停止检测",
                "signature": "停止检测()",
                "note": "停掉后台检测。脚本结束也会自动停。",
                "snippet": "停止检测()",
            },
            {
                "name": "持续找图",
                "signature": "持续找图(图片, 间隔=0.3)",
                "params": (("图片", "间隔=0.3"),),
                "note": "后台反复找图，主脚本读 找图 就是最新一次。找到后不会自动点。",
                "kind": "expr",
                "snippet": "持续找图(图片, 间隔=0.3)",
            },
            {
                "name": "停止找图",
                "signature": "停止找图()",
                "note": "停掉后台找图。",
                "snippet": "停止找图()",
            },
            {
                "name": "多线程",
                "signature": "多线程(按W)",
                "params": (("按W",),),
                "note": (
                    "按W 是你自己起的子程序名，不是内置命令。先写 子程序 按W():，再 多线程(按W)，不要写成 多线程(按W())。"
                    "YOLO 不走多线程。一直认用 持续检测，结果在 检测 里，主流程和子程序都能读。"
                    "关一条写 关闭线程(按W)，全关写 关闭线程()。"
                ),
                "example": (
                    "子程序 按W():\n"
                    "    当 真:\n"
                    "        按键(\"W\", 秒=0.2)\n"
                    "        延时(0.05)\n"
                    "多线程(按W)\n"
                    '持续检测("yolo/xxx.onnx", 间隔=0.2)\n'
                    "当 真:\n"
                    "    循环 目标 在 检测.列表:\n"
                    '        如果 目标.类别 是 "怪物":\n'
                    "            点击(目标)\n"
                    "            中断\n"
                    "    延时(0.05)"
                ),
                "snippet": (
                    "子程序 按W():\n"
                    "    当 真:\n"
                    "        按键(\"W\", 秒=0.2)\n"
                    "        延时(0.05)\n"
                    "多线程(按W)"
                ),
            },
            {
                "name": "关闭线程",
                "signature": "关闭线程()  /  关闭线程(按W)",
                "params": ((), ("按W",)),
                "note": "关闭线程() 关掉本脚本开出的全部线程。关闭线程(按W) 只关这一条。按W 是你自己的子程序名，不要加括号。",
                "example": "关闭线程(按W)\n关闭线程()",
                "snippet": "关闭线程()",
            },
            {
                "name": "找所有图",
                "signature": "找所有图(图片, 阈值=0.8, 最多=20)",
                "params": (("图片", "阈值=0.8", "最多=20"),),
                "note": "一次找出当前窗口里所有匹配，第一个点和找图同一条链路。可写 图[0]、图.列表。",
                "kind": "expr",
                "snippet": "找所有图(图片, 阈值=0.8, 最多=20)",
            },
            {
                "name": "取色",
                "signature": "取色(x, y)",
                "params": (("x", "y"),),
                "note": "读当前窗口客户区这一点的颜色，返回 红,绿,蓝。可写 色.红。",
                "kind": "expr",
                "snippet": "取色(x, y)",
            },
            {
                "name": "比色",
                "signature": "比色(x, y, 颜色, 偏色=20)  /  比色(颜色, 偏色=20)",
                "params": (("x", "y", "颜色", "偏色=20"), ("颜色", "偏色=20")),
                "note": "和当前点或指定坐标比颜色。偏色是每个通道允许差多少。",
                "kind": "expr",
                "snippet": "比色(x, y, 颜色, 偏色=20)",
            },
            {
                "name": "按下",
                "signature": '按下(目标)  /  按下(x, y)  /  按下("W")',
                "params": (("目标",), ("x", "y"), ("按键",)),
                "note": "只按下不松开。键盘写 按下(\"W\")，鼠标写 按下(目标) 或 按下(x, y)。和 松开 成对用。",
                "kind": "expr",
                "snippet": "按下(目标)",
            },
            {
                "name": "松开",
                "signature": '松开(目标)  /  松开(x, y)  /  松开("W")',
                "params": (("目标",), ("x", "y"), ("按键",)),
                "note": "弹起。键盘写 松开(\"W\")，鼠标写 松开(目标)。",
                "kind": "expr",
                "snippet": "松开(目标)",
            },
            {
                "name": "按住",
                "signature": "按住(目标, 秒=0.5)  /  按住(\"W\", 秒=0.5)  /  按住(\"W\", 秒=(0.2, 0.6))",
                "params": (("目标", "秒=0.5"), ("按键", "秒=0.5"), ("按键", "秒=(0.2, 0.6)")),
                "note": "按下、等一段时间、再松开。秒写数字是固定时长，写 (最短, 最长) 或 随机(0.2, 0.6) 是随机时长。键盘鼠标都能用。",
                "kind": "expr",
                "snippet": "按住(目标, 秒=0.5)",
            },
            {
                "name": "连点",
                "signature": "连点(目标, 次数=3, 间隔=0.08)",
                "params": (("目标", "次数=3", "间隔=0.08"),),
                "note": "连续点击。间隔是每次之间的秒数。",
                "kind": "expr",
                "snippet": "连点(目标, 次数=3, 间隔=0.08)",
            },
            {
                "name": "等毫秒",
                "signature": "等毫秒(50)",
                "params": ("毫秒",),
                "note": "按毫秒等待。等毫秒(50) 就是等 50 毫秒。秒请用 延时(0.05)。",
                "snippet": "等毫秒(50)",
            },
            {
                "name": "鼠标位置",
                "signature": "鼠标位置()",
                "note": "当前鼠标在窗口客户区的坐标。",
                "kind": "expr",
                "snippet": "鼠标位置()",
            },
            {
                "name": "相对移动",
                "signature": "相对移动(偏移x, 偏移y)",
                "params": (("偏移x", "偏移y"),),
                "note": "从当前鼠标位置挪一段。正数向右、向下。",
                "snippet": "相对移动(偏移x, 偏移y)",
            },
            {
                "name": "激活",
                "signature": "激活()",
                "note": "把全局设置里绑定的当前窗口提到前面。前后台模式也看全局设置。",
                "snippet": "激活()",
            },
            {
                "name": "窗口.设置分辨率",
                "signature": (
                    "窗口.设置分辨率(宽, 高)\n"
                    "窗口.设置分辨率(宽, 高, 目标)\n"
                    "窗口.设置分辨率(目标)\n"
                    "窗口.设置分辨率(宽, 高, 报错=假)"
                ),
                "params": (
                    ("宽", "高"),
                    ("宽", "高", "目标"),
                    ("目标",),
                    ("宽", "高", "报错=假"),
                ),
                "note": "改绑定窗口客户区尺寸。不写宽高就用全局自定义分辨率。目标可省略（当前）、写「当前」「全部」、标题、序号（从 1 起）或列表。单独一个数字不行。默认失败会打断脚本，报错=假 时只返回假。",
                "snippet": "窗口.设置分辨率(1280, 720)",
            },
            {
                "name": "播放",
                "signature": '播放(文件)  /  播放(文件, 等待=真)',
                "params": (("文件",), ("文件", "等待=真")),
                "note": "播音频。wav、mp3 都可以。等待=真 是播完再往下；等待=假 是接着跑。点停止会打断正在播的。文件用资源栏导入，或写成 \"提示.wav\"、\"sounds/提示.mp3\"。",
                "snippet": "播放(文件, 等待=真)",
            },
            {
                "name": "停止播放",
                "signature": "停止播放()",
                "note": "停掉当前正在播的音频。",
                "snippet": "停止播放()",
            },
            {
                "name": "回放",
                "signature": '回放("replays/过图.replay.json")  /  回放(文件, 速度=1, 次数=1)',
                "params": (("文件",), ("文件", "速度=1", "次数=1")),
                "note": "回放录制轨迹。文件用 .replay.json，放在 replays/ 或资源栏导入。只回放，不在脚本里开录制。",
                "snippet": '回放("replays/过图.replay.json", 速度=1, 次数=1)',
            },
            {
                "name": "截图",
                "signature": "截图()  /  截图(\"shot.png\")",
                "params": ((), ("文件",)),
                "note": "把当前绑定窗口存成项目图片。不写文件名就自动起名。返回路径，可接着 找图(图.路径)。",
                "kind": "expr",
                "snippet": '截图("shot.png")',
            },
            {
                "name": "等按键",
                "signature": '等按键("F1", 超时=8)  /  等按键("Ctrl+C", 超时=8)',
                "params": (("按键", "超时=8"),),
                "note": "等到这些键都按下。超时没按到就返回假，不会抛错。可写 空格、回车、F1 或组合键。",
                "kind": "expr",
                "snippet": '等按键("F1", 超时=8)',
            },
        ),
    },
    {
        "title": "跳转",
        "items": (
            {
                "name": "记录",
                "signature": "记录(内容)",
                "params": ("内容",),
                "note": "写到运行日志，不影响成功失败。",
                "snippet": "记录(内容)",
            },
            {
                "name": "成功",
                "signature": "成功()  /  成功(说明)",
                "params": ((), ("说明",)),
                "note": "立刻结束脚本并走成功线。后面的命令不会执行。",
                "snippet": "成功()",
            },
            {
                "name": "失败",
                "signature": "失败(说明)",
                "params": ("说明",),
                "note": "立刻结束脚本并走失败线。后面的命令不会执行。",
                "snippet": "失败(说明)",
            },
        ),
    },
    {
        "title": "变量",
        "items": (
            {
                "name": "变量.获取",
                "signature": "变量.获取(名字, 默认值)",
                "params": ("名字", "默认值"),
                "note": "没有这个名字时返回后面的默认值。",
                "kind": "expr",
                "snippet": "变量.获取(名字, 默认值)",
            },
            {
                "name": "变量.设置",
                "signature": "变量.设置(名字, 值)",
                "params": ("名字", "值"),
                "note": "写入或覆盖。",
                "snippet": "变量.设置(名字, 值)",
            },
            {
                "name": "变量.增加",
                "signature": "变量.增加(名字, 步长=1)",
                "params": ("名字", "步长=1"),
                "note": "按步长累加，默认加 1。",
                "snippet": "变量.增加(名字)",
            },
            {
                "name": "剪贴板.获取",
                "signature": "剪贴板.获取()",
                "note": "读当前剪贴板文字。",
                "kind": "expr",
                "snippet": "剪贴板.获取()",
            },
            {
                "name": "剪贴板.设置",
                "signature": "剪贴板.设置(文本)",
                "params": ("文本",),
                "note": "写入剪贴板。",
                "snippet": "剪贴板.设置(文本)",
            },
        ),
    },
    {
        "title": "结果",
        "items": (
            {
                "name": "上次",
                "signature": "上次.通过  上次.成功  上次.分数  上次.阈值  上次.x  上次.y",
                "note": "最近一次动作的结果，不区分种类。",
                "kind": "expr",
                "snippet": "上次",
            },
            {
                "name": "文字",
                "signature": "文字.内容  文字.通过",
                "note": "最近一次找字或字库识别。",
                "kind": "expr",
                "snippet": "文字",
            },
            {
                "name": "卡片",
                "signature": "卡片[编号].内容  卡片[编号].分数  卡片[编号].通过",
                "note": "读画布上某张卡上次跑完的结果，编号是卡片编号。",
                "kind": "expr",
                "snippet": "卡片[编号]",
            },
            {
                "name": "窗口.宽",
                "signature": "窗口.宽",
                "note": "当前绑定窗口客户区宽度。",
                "kind": "expr",
                "snippet": "窗口.宽",
            },
            {
                "name": "窗口.高",
                "signature": "窗口.高",
                "note": "当前绑定窗口客户区高度。",
                "kind": "expr",
                "snippet": "窗口.高",
            },
        ),
    },
    {
        "title": "语法",
        "items": (
            {
                "name": "如果",
                "signature": "如果 条件:",
                "params": ("条件",),
                "note": "条件成立时执行缩进里的命令。回车后在下一行写动作。",
                "snippet": "如果 条件:",
            },
            {
                "name": "循环",
                "signature": "循环 i 在 范围(次数):",
                "params": ("次数",),
                "note": "按次数重复。",
                "snippet": "循环 i 在 范围(次数):",
            },
            {
                "name": "当",
                "signature": "当 条件:",
                "params": ("条件",),
                "note": "条件成立就继续。",
                "snippet": "当 条件:",
            },
            {
                "name": "否则如果",
                "signature": "否则如果 条件:",
                "params": ("条件",),
                "note": "上一个条件不成立时再判断。",
                "snippet": "否则如果 条件:",
            },
            {
                "name": "否则",
                "signature": "否则:",
                "note": "前面的条件都不成立时执行。与 如果 对齐。",
                "snippet": "否则:",
            },
            {
                "name": "中断",
                "signature": "中断",
                "note": "立刻跳出当前循环。",
                "snippet": "中断",
            },
            {
                "name": "继续",
                "signature": "继续",
                "note": "跳过本轮，进入下一轮循环。",
                "snippet": "继续",
            },
            {
                "name": "子程序",
                "signature": "子程序 点确定():",
                "note": "可复用的一段命令。里面可以用 返回 值。可以再写子程序。",
                "snippet": "子程序 点确定():",
            },
        ),
    },
    {
        "title": "计算",
        "items": (
            {
                "name": "长度",
                "signature": "长度(对象)",
                "params": ("对象",),
                "note": "文字或列表有多少项。",
                "kind": "expr",
                "snippet": "长度(对象)",
            },
            {
                "name": "整数",
                "signature": "整数(值)",
                "params": ("值",),
                "note": "转成整数。",
                "kind": "expr",
                "snippet": "整数(值)",
            },
            {
                "name": "小数",
                "signature": "小数(值)",
                "params": ("值",),
                "note": "转成小数。",
                "kind": "expr",
                "snippet": "小数(值)",
            },
            {
                "name": "到文本",
                "signature": "到文本(值)",
                "params": ("值",),
                "note": "转成文字。",
                "kind": "expr",
                "snippet": "到文本(值)",
            },
            {
                "name": "真假",
                "signature": "真假(值)",
                "params": ("值",),
                "note": "转成真或假。",
                "kind": "expr",
                "snippet": "真假(值)",
            },
            {
                "name": "最小",
                "signature": "最小(值1, 值2)",
                "params": ("值1", "值2"),
                "note": "取较小的那个。",
                "kind": "expr",
                "snippet": "最小(值1, 值2)",
            },
            {
                "name": "最大",
                "signature": "最大(值1, 值2)",
                "params": ("值1", "值2"),
                "note": "取较大的那个。",
                "kind": "expr",
                "snippet": "最大(值1, 值2)",
            },
            {
                "name": "绝对值",
                "signature": "绝对值(值)",
                "params": ("值",),
                "note": "去掉正负号。",
                "kind": "expr",
                "snippet": "绝对值(值)",
            },
            {
                "name": "开方",
                "signature": "开方(值)  /  平方根(值)",
                "params": ("值",),
                "note": "平方根，不是「开放」。开方(9) 是 3。算距离用 开方(差x * 差x + 差y * 差y)。",
                "kind": "expr",
                "snippet": "开方(值)",
            },
            {
                "name": "限制",
                "signature": "限制(值, 下限, 上限)",
                "params": ("值", "下限", "上限"),
                "note": "把数夹在两头之间，防止点出窗口或区域。",
                "kind": "expr",
                "snippet": "限制(值, 下限, 上限)",
            },
            {
                "name": "距离",
                "signature": "距离(点1, 点2)  /  距离(x1, y1, x2, y2)",
                "params": (("点1", "点2"), ("x1", "y1", "x2", "y2")),
                "note": "用两点的 x、y 算像素距离。也可以自己用 开方 算。",
                "kind": "expr",
                "snippet": "距离(点1, 点2)",
            },
            {
                "name": "角度",
                "signature": "角度(点1, 点2)  /  角度(x1, y1, x2, y2)",
                "params": (("点1", "点2"), ("x1", "y1", "x2", "y2")),
                "note": "从点1指向点2的方向角，单位是度。用两点的 x、y。屏幕坐标：0 正右，90 正下，-90 正上，180 正左。",
                "kind": "expr",
                "snippet": "角度(点1, 点2)",
            },
            {
                "name": "正弦",
                "signature": "正弦(角度)",
                "params": ("角度",),
                "note": "参数是度，不是弧度。和 余弦 一起把角度还原成方向。",
                "kind": "expr",
                "snippet": "正弦(角度)",
            },
            {
                "name": "余弦",
                "signature": "余弦(角度)",
                "params": ("角度",),
                "note": "参数是度，不是弧度。走x = 自己.x + 余弦(角) * 像素。",
                "kind": "expr",
                "snippet": "余弦(角度)",
            },
            {
                "name": "范围",
                "signature": "范围(次数)  /  范围(起点, 终点)  /  范围(起点, 终点, 步长)",
                "params": (("次数",), ("起点", "终点"), ("起点", "终点", "步长")),
                "note": "给循环生成一串数字。",
                "kind": "expr",
                "snippet": "范围(次数)",
            },
            {
                "name": "随机",
                "signature": "随机()  /  随机(10)  /  随机(1, 10)",
                "params": ((), ("次数",), ("起点", "终点")),
                "note": "不写参数是 0 到 1 的小数。写一个整数是 0 到 这个数减 1。写两个整数是闭区间整数。写两个小数是这段里随机小数，给按住时长用。",
                "kind": "expr",
                "snippet": "随机(1, 10)",
            },
            {
                "name": "包含",
                "signature": "包含(文本, 片段)",
                "params": ("文本", "片段"),
                "note": "文本里有没有这段字。",
                "kind": "expr",
                "snippet": "包含(文本, 片段)",
            },
            {
                "name": "截取",
                "signature": "截取(文本, 起点, 字数)",
                "params": ("文本", "起点", "字数"),
                "note": "起点从 1 开始。不写字数就截到末尾。",
                "kind": "expr",
                "snippet": "截取(文本, 1, 2)",
            },
            {
                "name": "替换",
                "signature": "替换(文本, 旧, 新)",
                "params": ("文本", "旧", "新"),
                "note": "把旧字换成新字。",
                "kind": "expr",
                "snippet": "替换(文本, 旧, 新)",
            },
            {
                "name": "分割",
                "signature": '分割(文本, ",")',
                "params": ("文本", "分隔符"),
                "note": "拆成列表。不写分隔符就按空白拆。",
                "kind": "expr",
                "snippet": "分割(文本, 分隔符)",
            },
            {
                "name": "时间",
                "signature": "时间()",
                "note": "当前毫秒。用来自己算超时：起 = 时间()。",
                "kind": "expr",
                "snippet": "时间()",
            },
            {
                "name": "去空格",
                "signature": "去空格(文本)",
                "params": ("文本",),
                "note": "去掉头尾空白。",
                "kind": "expr",
                "snippet": "去空格(文本)",
            },
            {
                "name": "查找",
                "signature": "查找(文本, 片段)",
                "params": ("文本", "片段"),
                "note": "片段在文本里的位置，从 1 起。找不到是 0。",
                "kind": "expr",
                "snippet": "查找(文本, 片段)",
            },
            {
                "name": "提取数字",
                "signature": "提取数字(文本)",
                "params": ("文本",),
                "note": "从文字里抽出第一个数字。没有就返回 0。",
                "kind": "expr",
                "snippet": "提取数字(文本)",
            },
        ),
    },
)


def iter_script_insert_items() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for group in SCRIPT_INSERT_GROUPS:
        for item in group.get("items") or ():
            if isinstance(item, dict) and str(item.get("snippet") or "").strip():
                items.append(item)
    return items


def script_completion_names() -> List[str]:
    names = [str(item.get("name") or "") for item in iter_script_insert_items()]
    names.extend(
        (
            "变量.获取",
            "变量.设置",
            "变量.增加",
            "上次.分数",
            "上次.x",
            "上次.y",
            "上次.通过",
            "文字.内容",
            "文字.通过",
            "找图.分数",
            "找图.路径",
            "找图.x",
            "找图.y",
            "找图.通过",
            "检测.类别",
            "检测.分数",
            "检测.列表",
            "检测.x",
            "检测.y",
            "检测.宽",
            "检测.高",
            "检测.通过",
            "卡片",
            "否则如果",
            "否则",
            "中断",
            "继续",
            "并且",
            "或者",
            "不是",
            "真",
            "假",
            "空",
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
            "角度",
            "正弦",
            "余弦",
            "限制",
            "距离",
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
            "窗口.宽",
            "窗口.高",
            "窗口.设置分辨率",
            "剪贴板.获取",
            "剪贴板.设置",
        )
    )
    return sorted({name for name in names if name})


_PLACEHOLDER_TOKENS = (
    "区域=(x, y, 宽, 高)",
    "区域=(x, y, 宽, 高)",
    '目标="金币"',
    '类别="敌人"',
    '键="右键"',
    '键="左键"',
    '方向="向下"',
    '方向="向上"',
    "阈值=0.8",
    "阈值=0.5",
    '策略="最近"',
    '策略="最大"',
    '策略="置信度最高"',
    "横向=0.5",
    "纵向=0.85",
    "纵向=0.5",
    "边距=2",
    "点击=假",
    "点击=真",
    "点击=False",
    "点击=True",
    "报错=假",
    "报错=真",
    "双击=假",
    "双击=真",
    "偏移x=0",
    "偏移y=0",
    "随机=0",
    "步数=3",
    "步长=1",
    "超时=8",
    "间隔=0.3",
    "间隔=0.08",
    "偏色=20",
    "最多=20",
    "秒=0.5",
    "秒=(0.2, 0.6)",
    '动作="按下"',
    '动作="松开"',
    "次数=3",
    "默认值",
    "起点横坐标",
    "起点纵坐标",
    "终点横坐标",
    "终点纵坐标",
    "横坐标",
    "纵坐标",
    "条件",
    "次数",
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
    "对象",
    "值1",
    "值2",
    "点1",
    "点2",
    "下限",
    "上限",
    "起点",
    "终点",
    "值",
    "秒",
    "按键",
    "步数",
    "横向",
    "纵向",
    "边距",
    "自己",
    "策略",
    "类别",
    "宽",
    "高",
    "x1",
    "y1",
    "x2",
    "y2",
    "x",
    "y",
)


def iter_placeholder_spans(text: str) -> List[Tuple[int, int]]:
    source = str(text or "")
    used = [False] * len(source)
    spans: List[Tuple[int, int]] = []
    for token in _PLACEHOLDER_TOKENS:
        start = 0
        while True:
            index = _find_token(source[start:], token)
            if index < 0:
                break
            index += start
            end = index + len(token)
            if not any(used[index:end]):
                spans.append((index, end))
                for pos in range(index, end):
                    used[pos] = True
            start = index + 1
    spans.sort()
    return spans


def first_placeholder_span(text: str) -> Optional[Tuple[int, int]]:
    source = str(text or "")
    empty_quotes = source.find('""')
    if empty_quotes >= 0:
        return empty_quotes, empty_quotes + 2
    empty_single = source.find("''")
    if empty_single >= 0:
        return empty_single, empty_single + 2
    spans = iter_placeholder_spans(source)
    if spans:
        return spans[0]
    empty_call = source.find("()")
    if empty_call >= 0:
        return empty_call + 1, empty_call + 1
    for quote in ('"', "'"):
        start = source.find(quote)
        if start < 0:
            continue
        end = source.find(quote, start + 1)
        if end > start:
            return start, end + 1
    return None


def next_placeholder_span(text: str, column: int, backward: bool = False) -> Optional[Tuple[int, int]]:
    spans = iter_placeholder_spans(text)
    if not spans:
        return None
    cursor = max(0, int(column))
    if backward:
        for start, end in reversed(spans):
            if end <= cursor:
                return start, end
        return None
    for start, end in spans:
        if start >= cursor:
            return start, end
    return None


def _find_token(text: str, token: str) -> int:
    start = 0
    while True:
        index = text.find(token, start)
        if index < 0:
            return -1
        before = text[index - 1] if index > 0 else ""
        after = text[index + len(token)] if index + len(token) < len(text) else ""
        if not _is_ident_char(before) and not _is_ident_char(after):
            return index
        start = index + 1


def _is_ident_char(char: str) -> bool:
    if not char:
        return False
    return char.isalnum() or char == "_" or "\u4e00" <= char <= "\u9fff"


def leading_whitespace(text: str) -> str:
    index = 0
    while index < len(text) and text[index] in {" ", "\t"}:
        index += 1
    return text[:index].replace("\t", "    ")


def indent_snippet(snippet: str, indent: str) -> str:
    lines = str(snippet or "").splitlines() or [""]
    return "\n".join(indent + line for line in lines)


def _block_body_end(lines: List[str], header_index: int) -> int:
    header_indent = leading_whitespace(lines[header_index])
    end = header_index + 1
    while end < len(lines):
        line = lines[end]
        if not line.strip():
            break
        if len(leading_whitespace(line)) <= len(header_indent):
            break
        end += 1
    return end - 1


def _indent_from_above(lines: List[str], line_index: int) -> str:
    for previous in reversed(lines[:line_index]):
        if not previous.strip():
            continue
        indent = leading_whitespace(previous)
        if previous.rstrip().endswith(":"):
            return indent + "    "
        return indent
    return ""


def command_matches_query(item: Dict[str, Any], query: str) -> bool:
    needle = str(query or "").strip().lower()
    if not needle:
        return True
    haystack = " ".join(
        (
            str((item or {}).get("name") or ""),
            str((item or {}).get("signature") or ""),
            str((item or {}).get("note") or ""),
            str((item or {}).get("snippet") or ""),
            command_example_text(item or {}),
        )
    ).lower()
    return needle in haystack


def _is_command_name_char(char: str) -> bool:
    return _is_ident_char(char) or char == "."


def command_name_from_snippet(snippet: str) -> str:
    text = str(snippet or "").strip()
    index = 0
    while index < len(text) and _is_command_name_char(text[index]):
        index += 1
    return text[:index]


def call_name_before(text: str, open_index: int) -> str:
    source = str(text or "")
    index = max(0, min(int(open_index), len(source)))
    while index > 0 and source[index - 1].isspace():
        index -= 1
    end = index
    while index > 0 and _is_command_name_char(source[index - 1]):
        index -= 1
    return source[index:end]


def ident_span(line: str, column: int) -> Tuple[int, int]:
    text = str(line or "")
    position = max(0, min(int(column), len(text)))
    start = position
    while start > 0 and _is_command_name_char(text[start - 1]):
        start -= 1
    end = position
    while end < len(text) and _is_command_name_char(text[end]):
        end += 1
    return start, end


def _is_block_header(line: str) -> bool:
    return bool(str(line or "").rstrip().endswith(":"))


def _is_outdent_keyword(name: str) -> bool:
    return str(name or "") in {"else", "elif", "否则", "否则如果"}


def _outer_indent(lines: List[str], index: int) -> str:
    current = lines[index] if 0 <= index < len(lines) else ""
    current_indent = leading_whitespace(current) if current.strip() else (_indent_from_above(lines, index) or "")
    for previous in reversed(lines[: max(0, index)]):
        if not previous.strip():
            continue
        indent = leading_whitespace(previous)
        if _is_block_header(previous) and len(indent) <= len(current_indent):
            return indent
        if len(indent) < len(current_indent):
            return indent
    return ""


def _should_complete_token(token: str, name: str, line: str) -> bool:
    command = str(name or "").strip()
    piece = str(token or "").strip()
    if not piece or not command:
        return False
    if piece == command:
        return str(line or "").strip() == piece
    if command.startswith(piece):
        return True
    tail = command.split(".")[-1]
    return bool(tail) and tail.startswith(piece)


_STMT_COMMANDS = frozenset(
    {
        "移动",
        "拖拽",
        "滚轮",
        "按键",
        "输入",
        "延时",
        "等毫秒",
        "相对移动",
        "按下",
        "松开",
        "按住",
        "连点",
        "激活",
        "窗口.设置分辨率",
        "播放",
        "停止播放",
        "回放",
        "剪贴板.设置",
        "记录",
        "成功",
        "失败",
        "变量.设置",
        "如果",
        "循环",
        "当",
        "否则如果",
        "否则",
        "中断",
        "继续",
        "if",
        "for",
        "while",
        "elif",
        "else",
    }
)
_RESULT_ASSIGN_PREFIXES = (
    "找图(",
    "等图(",
    "找所有图(",
    "检测(",
    "等检测(",
    "等检测消失(",
    "框内点(",
    "随机点(",
    "找字(",
    "找字库(",
    "等字库(",
    "等字库消失(",
    "点字库(",
    "等文字(",
    "等图消失(",
    "等色消失(",
    "等文字消失(",
    "鼠标位置(",
    "找色(",
    "等色(",
    "取色(",
    "比色(",
    "点文字(",
    "点元素(",
    "截图(",
    "等按键(",
)
_HEADER_PREFIXES = (
    ("否则如果 ", "条件"),
    ("如果 ", "条件"),
    ("当 ", "条件"),
    ("elif ", "条件"),
    ("if ", "条件"),
    ("while ", "条件"),
)
_CARD_INDEX_RE = re.compile(r"卡片\[([^\]]*)\]")
_LOOP_RANGE_TOKENS = ("范围(", "range(")
_PARAM_CHOICES = {
    "点击": ("假", "真"),
    "双击": ("假", "真"),
    "等待": ("真", "假"),
    "键": ('"左键"', '"右键"'),
    "方向": ('"向下"', '"向上"'),
    "动作": ('"按下"', '"松开"'),
    "方式": ('"粘贴"', '"仿真"'),
    "策略": ('"最近"', '"最大"', '"置信度最高"'),
}


def insert_item_catalog() -> Dict[str, Dict[str, Any]]:
    return {str(item.get("name") or ""): item for item in iter_script_insert_items() if item.get("name")}


def catalog_snippet(name: str) -> str:
    item = insert_item_catalog().get(str(name or ""))
    return str((item or {}).get("snippet") or "").rstrip()


def command_kind(name: str, item: Optional[Dict[str, Any]] = None) -> str:
    if item and item.get("kind"):
        return str(item.get("kind") or "stmt")
    catalog = insert_item_catalog().get(str(name or "")) or {}
    if catalog.get("kind"):
        return str(catalog.get("kind") or "stmt")
    return "stmt" if str(name or "") in _STMT_COMMANDS else "expr"


def command_returns_label(name: str) -> str:
    return "结果" if command_kind(name) == "expr" else "无"


def _is_concrete_snippet(snippet: str) -> bool:
    text = str(snippet or "")
    if '"' in text or "'" in text:
        return True
    stripped = text
    for token in _PLACEHOLDER_TOKENS:
        stripped = stripped.replace(token, "")
    return any(char.isdigit() for char in stripped)


def is_placeholder_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    for token in _PLACEHOLDER_TOKENS:
        if value == token:
            return True
    key = value.split("=", 1)[0].strip()
    return key in {
        "条件",
        "次数",
        "图片",
        "颜色",
        "目标",
        "文本",
        "内容",
        "说明",
        "名字",
        "名称",
        "编号",
        "按键",
        "秒",
        "动作",
        "值",
        "默认值",
        "步数",
        "步长",
        "类别",
        "阈值",
        "策略",
        "文件",
        "等待",
        "横向",
        "纵向",
        "边距",
        "自己",
        "点击",
        "双击",
        "偏移x",
        "偏移y",
        "随机",
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
        "键",
        "方向",
        "区域",
        "对象",
        "值1",
        "值2",
        "点1",
        "点2",
        "角度",
        "下限",
        "上限",
        "起点",
        "终点",
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


def wrap_first_arg(snippet: str, value: str) -> str:
    text = str(snippet or "").rstrip()
    filled = str(value or "").strip()
    if not filled:
        return text
    span = first_placeholder_span(text)
    if span:
        return text[: span[0]] + filled + text[span[1] :]
    empty = text.find("()")
    if empty >= 0:
        return f"{text[: empty + 1]}{filled}{text[empty + 1 :]}"
    return text


def _nearest_result_var(lines: List[str], index: int) -> Optional[str]:
    for line in reversed(lines[: index + 1]):
        stripped = str(line or "").strip()
        if not stripped or stripped.startswith(
            ("如果 ", "否则如果 ", "当 ", "循环 ", "if ", "elif ", "while ", "for ", "否则:", "else:")
        ):
            continue
        if "=" not in stripped:
            continue
        left, right = stripped.split("=", 1)
        name = left.strip()
        right = right.lstrip()
        if name and any(right.startswith(prefix) for prefix in _RESULT_ASSIGN_PREFIXES):
            return name
    return None


def statement_for_insert(name: str, snippet: str, result_var: Optional[str] = None, header: str = "") -> str:
    command = str(name or "").strip()
    text = str(snippet or "").rstrip()
    if not _is_concrete_snippet(text):
        text = catalog_snippet(command) or text
    if command == "点击":
        if result_var:
            return f"点击({result_var}, 双击=假, 偏移x=0, 偏移y=0, 随机=0)"
        if any(token in str(header or "") for token in ("找图", "检测", "找字", "找字库", "找色", "点文字", "点字库", "点元素")):
            return "点击()"
        return text or "点击(目标, 双击=假, 偏移x=0, 偏移y=0, 随机=0)"
    if command == "移动" and result_var:
        return f"移动({result_var})"
    if command == "拖拽" and result_var:
        return f"拖拽({result_var}, 终点)"
    if command == "滚轮" and result_var:
        return f'滚轮({result_var}, 方向="向下")'
    if command == "框内点" and result_var:
        return f"框内点({result_var}, 横向=0.5, 纵向=0.5)"
    if command == "随机点" and result_var:
        return f"随机点({result_var}, 边距=2)"
    if command in {"如果", "if"} and result_var:
        return f"{command} {result_var}:"
    if command in {"当", "while"} and result_var:
        return f"{command} {result_var}:"
    return text


def _placeholder_span_at(
    line: str,
    column: int,
    select_start: Optional[int] = None,
    select_end: Optional[int] = None,
) -> Optional[Tuple[int, int]]:
    spans = iter_placeholder_spans(line)
    if select_start is not None and select_end is not None and select_end > select_start:
        for start, end in spans:
            if start <= select_start and select_end <= end:
                return start, end
            if select_start <= start and end <= select_end:
                return start, end
    for start, end in spans:
        if start <= column <= end:
            return start, end
    return None


def _empty_call_span_at(line: str, open_index: int) -> Optional[Tuple[int, int, str]]:
    text = str(line or "")
    if open_index < 0 or open_index >= len(text) or text[open_index] != "(":
        return None
    close_index = text.find(")", open_index + 1)
    if close_index < 0 or text[open_index + 1 : close_index].strip():
        return None
    name = command_name_from_snippet(text[:open_index])
    name = name.split()[-1] if name else ""
    if not name:
        return None
    return open_index + 1, close_index, name


def _empty_call_at_cursor(line: str, column: int) -> Optional[Tuple[int, int]]:
    text = str(line or "")
    position = max(0, min(int(column), len(text)))
    open_index = text.rfind("(", 0, position + 1)
    found = _empty_call_span_at(text, open_index)
    if found and found[0] <= position <= found[1]:
        return found[0], found[1]
    return None


def _nest_target(
    line: str,
    column: int,
    select_start: Optional[int] = None,
    select_end: Optional[int] = None,
) -> Optional[Tuple[int, int]]:
    if select_start is not None and select_end is not None and select_end > select_start:
        return select_start, select_end
    placeholder = _placeholder_span_at(line, column, select_start, select_end)
    if placeholder:
        return placeholder
    empty = _empty_call_at_cursor(line, column)
    if empty:
        return empty
    return None


def _match_paren(text: str, open_index: int) -> Optional[int]:
    depth = 0
    quote = None
    escape = False
    for index in range(open_index, len(text)):
        char = text[index]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
            continue
        if char == "(":
            depth += 1
            continue
        if char == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _split_args_spans(text: str, start: int, end: int) -> List[Tuple[int, int, str]]:
    args: List[Tuple[int, int, str]] = []
    buf_start = start
    depth = 0
    quote = None
    for index in range(start, end):
        char = text[index]
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
            continue
        if char in "([{":
            depth += 1
            continue
        if char in ")]}":
            depth = max(0, depth - 1)
            continue
        if char == "," and depth == 0:
            token = text[buf_start:index].strip()
            if token:
                lead = 0
                while buf_start + lead < index and text[buf_start + lead] in {" ", "\t"}:
                    lead += 1
                args.append((buf_start + lead, buf_start + lead + len(token), token))
            buf_start = index + 1
    token = text[buf_start:end].strip()
    if token:
        lead = 0
        while buf_start + lead < end and text[buf_start + lead] in {" ", "\t"}:
            lead += 1
        args.append((buf_start + lead, buf_start + lead + len(token), token))
    return args


def _normalize_overloads(params: Any) -> List[Tuple[str, ...]]:
    if not params:
        return []
    first = params[0]
    if isinstance(first, (tuple, list)):
        return [tuple(str(part) for part in item) for item in params if item]
    return [tuple(str(part) for part in params)]


def _looks_like_xy_token(raw: str) -> bool:
    text = str(raw or "").strip()
    if not text:
        return False
    if _field_label(text) in {"横坐标", "纵坐标", "x", "y"}:
        return True
    if text.startswith(("+", "-")):
        text = text[1:]
    return bool(text) and text.isdigit()


def _arg_raw(arg: Any) -> str:
    if isinstance(arg, (tuple, list)) and len(arg) >= 3:
        return str(arg[2] or "").strip()
    return str(arg or "").strip()


def _arg_keyword(raw: str) -> str:
    text = str(raw or "").strip()
    if "=" not in text or text.startswith(("'", '"', "(")):
        return ""
    return text.split("=", 1)[0].strip()


def _looks_like_number_token(raw: str) -> bool:
    text = str(raw or "").strip()
    if not text or text.startswith(("'", '"', "(")):
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


def _bind_call_args(
    specs: Sequence[str],
    args: List,
) -> Tuple[List[Tuple[str, Any]], List, Dict[str, Any]]:
    positionals: List = []
    keywords: Dict[str, Any] = {}
    for arg in args:
        key = _arg_keyword(_arg_raw(arg))
        if key:
            keywords[key] = arg
        else:
            positionals.append(arg)
    bound: List[Tuple[str, Any]] = []
    pos_index = 0
    used_keywords = set()
    for spec in specs:
        label = _field_label(spec)
        if label in keywords:
            bound.append((spec, keywords[label]))
            used_keywords.add(label)
        elif "=" not in spec and pos_index < len(positionals):
            bound.append((spec, positionals[pos_index]))
            pos_index += 1
        else:
            bound.append((spec, None))
    leftover_pos = positionals[pos_index:]
    if leftover_pos and _looks_like_number_token(_arg_raw(leftover_pos[0])):
        for index, (spec, arg) in enumerate(bound):
            if arg is None and _field_label(spec) == "阈值":
                bound[index] = (spec, leftover_pos.pop(0))
                break
    leftover_kw = {key: arg for key, arg in keywords.items() if key not in used_keywords}
    return bound, leftover_pos, leftover_kw


def _overload_score(specs: Sequence[str], args: List) -> Optional[Tuple[int, ...]]:
    _bound, leftover_pos, leftover_kw = _bind_call_args(specs, args)
    if leftover_kw:
        return None
    unused_required = 0
    unused_optional = 0
    for spec, arg in _bound:
        if arg is not None:
            continue
        if "=" in spec:
            unused_optional += 1
        else:
            unused_required += 1
    return (len(leftover_pos), unused_required, unused_optional, len(specs))


def _first_positional_raw(args: List) -> str:
    for arg in args:
        if not _arg_keyword(_arg_raw(arg)):
            return _arg_raw(arg)
    return ""


def _preferred_overloads(items: List[Tuple[str, ...]], args: List) -> List[Tuple[str, ...]]:
    first = _first_positional_raw(args)
    if _looks_like_xy_token(first):
        group = [item for item in items if item and _field_label(item[0]) in {"横坐标", "x"}]
        if group:
            return group
    elif first:
        group = [item for item in items if item and _field_label(item[0]) == "目标"]
        if group:
            return group
    return items


def _pick_call_overload(overloads: List[Tuple[str, ...]], args: List) -> Tuple[str, ...]:
    items = [tuple(item) for item in (overloads or []) if item]
    if not items:
        return ()
    if not args:
        targets = [item for item in items if item and _field_label(item[0]) == "目标"]
        if targets:
            return max(targets, key=len)
        return items[0]
    pool = _preferred_overloads(items, args)
    scored = []
    for candidate in (pool, items):
        scored = [
            (score, item)
            for item in candidate
            if (score := _overload_score(item, args)) is not None
        ]
        if scored:
            scored.sort(key=lambda item: item[0])
            return scored[0][1]
    return pool[0] if pool else items[0]


def _is_image_label(label: str) -> bool:
    text = str(label or "")
    return text == "图片" or text.startswith("图片")


def _next_image_spec(used: set) -> str:
    index = 2
    while f"图片{index}" in used or (index == 1 and "图片" in used):
        index += 1
    return f"图片{index}"


def _make_call_field(index: int, spec: str, arg: Any, close_index: int, position: int) -> Dict[str, Any]:
    raw = _arg_raw(arg) if arg is not None else ""
    start, end = (int(arg[0]), int(arg[1])) if arg is not None else (close_index, close_index)
    return {
        "index": index,
        "label": _field_label(spec),
        "spec": spec,
        "raw": raw,
        "value": _field_display_value(spec, raw),
        "start": start,
        "end": end,
        "choices": _PARAM_CHOICES.get(_field_label(spec), ()),
        "active": bool(arg is not None and int(arg[0]) <= position <= int(arg[1])),
    }


def _call_fields(specs: Sequence[str], args: List, close_index: int, position: int) -> List[Dict[str, Any]]:
    bound, leftover_pos, leftover_kw = _bind_call_args(specs, args)
    fields = [_make_call_field(index, spec, arg, close_index, position) for index, (spec, arg) in enumerate(bound)]
    insert_at = 0
    used = set()
    for index, field in enumerate(fields):
        label = str(field.get("label") or "")
        used.add(label)
        if _is_image_label(label):
            insert_at = index + 1
    extras = []
    for arg in leftover_pos:
        spec = _next_image_spec(used)
        extras.append(_make_call_field(0, spec, arg, close_index, position))
        used.add(spec)
    if extras:
        fields[insert_at:insert_at] = extras
    for key, arg in leftover_kw.items():
        raw = _arg_raw(arg)
        spec = raw if "=" in raw else key
        fields.append(_make_call_field(len(fields), spec, arg, close_index, position))
    for index, field in enumerate(fields):
        field["index"] = index
    return fields


def _field_label(spec: str) -> str:
    return str(spec or "").split("=", 1)[0].strip()


def _field_default(spec: str) -> str:
    text = str(spec or "")
    if "=" not in text:
        return ""
    return text.split("=", 1)[1].strip()


def _field_display_value(spec: str, raw: str) -> str:
    text = str(raw or "").strip()
    key = _field_label(spec)
    prefix = f"{key}="
    if text.startswith(prefix):
        return text[len(prefix) :]
    if text:
        return text
    return _field_default(spec)


def format_param_value(spec: str, value: str) -> str:
    raw = str(value or "").strip()
    key = _field_label(spec)
    if "=" in str(spec or "") and raw and not raw.startswith(f"{key}="):
        return f"{key}={raw}"
    return raw


def parse_param_fields(line: str, column: int = 0) -> Optional[Dict[str, Any]]:
    text = str(line or "")
    position = max(0, min(int(column), len(text)))
    open_index = text.rfind("(", 0, position + 1)
    close_index = _match_paren(text, open_index) if open_index >= 0 else None
    if open_index >= 0 and close_index is not None and open_index < position <= close_index:
        name = call_name_before(text, open_index)
        item = insert_item_catalog().get(name) or {}
        overloads = _normalize_overloads(item.get("params"))
        args = _split_args_spans(text, open_index + 1, close_index)
        labels = _pick_call_overload(overloads, args)
        fields = _call_fields(labels, args, close_index, position)
        if not fields and name:
            fields.append(
                {
                    "index": 0,
                    "label": "",
                    "spec": "",
                    "raw": "",
                    "value": "",
                    "start": open_index + 1,
                    "end": close_index,
                    "choices": (),
                    "active": True,
                }
            )
        active = 0
        for index, field in enumerate(fields):
            if field.get("active"):
                active = index
                break
        return {
            "kind": "call",
            "name": name,
            "open": open_index,
            "close": close_index,
            "fields": fields,
            "active": active,
        }

    loop_fields = _parse_loop_header(text, position)
    if loop_fields:
        return loop_fields
    card_fields = _parse_card_index(text, position)
    if card_fields:
        return card_fields

    stripped = text.lstrip()
    for prefix, label in _HEADER_PREFIXES:
        if stripped.startswith(prefix) and stripped.endswith(":"):
            value = stripped[len(prefix) : -1]
            start = len(text) - len(stripped) + len(prefix)
            while start < len(text) and text[start] in {" ", "\t"}:
                start += 1
            end = len(text.rstrip()) - 1 if text.rstrip().endswith(":") else len(text)
            while end > start and text[end - 1] in {" ", "\t"}:
                end -= 1
            return {
                "kind": "header",
                "name": prefix.strip(),
                "fields": [
                    {
                        "index": 0,
                        "label": label,
                        "spec": label,
                        "raw": value.strip(),
                        "value": value.strip(),
                        "start": start,
                        "end": end,
                        "choices": (),
                        "active": True,
                    }
                ],
                "active": 0,
            }
    return None


def _parse_loop_header(line: str, column: int = 0) -> Optional[Dict[str, Any]]:
    text = str(line or "")
    stripped = text.lstrip()
    if not (stripped.startswith("循环 ") or stripped.startswith("for ")):
        return None
    for token in _LOOP_RANGE_TOKENS:
        index = text.find(token)
        if index < 0:
            continue
        open_index = index + len(token) - 1
        close_index = _match_paren(text, open_index)
        if close_index is None:
            continue
        parsed = parse_param_fields(text, open_index + 1)
        if parsed and parsed.get("kind") == "call":
            parsed["name"] = "循环" if stripped.startswith("循环 ") else "for"
            return parsed
    return None


def _parse_card_index(line: str, column: int = 0) -> Optional[Dict[str, Any]]:
    text = str(line or "")
    position = max(0, min(int(column), len(text)))
    match = _CARD_INDEX_RE.search(text)
    if match is None or not (match.start() <= position <= match.end()):
        return None
    return {
        "kind": "header",
        "name": "卡片",
        "fields": [
            {
                "index": 0,
                "label": "编号",
                "spec": "编号",
                "raw": match.group(1),
                "value": match.group(1),
                "start": match.start(1),
                "end": match.end(1),
                "choices": (),
                "active": True,
            }
        ],
        "active": 0,
    }


def apply_param_value(line: str, column: int, arg_index: int, value: str) -> str:
    parsed = parse_param_fields(line, column)
    if not parsed:
        return line
    fields = list(parsed.get("fields") or [])
    if not fields:
        return line
    index = max(0, min(int(arg_index), len(fields) - 1))
    field = fields[index]
    written = format_param_value(str(field.get("spec") or field.get("label") or ""), value)
    start = int(field.get("start") or 0)
    end = int(field.get("end") or start)
    if parsed.get("kind") == "call" and not str(field.get("raw") or "") and start == parsed.get("close"):
        open_index = int(parsed.get("open") or 0)
        close_index = int(parsed.get("close") or 0)
        inside = line[open_index + 1 : close_index]
        existing = [span[2] for span in _split_args_spans(line, open_index + 1, close_index)]
        while len(existing) < index:
            missing = fields[len(existing)]
            filler = str(missing.get("spec") or missing.get("label") or "").strip() or "值"
            existing.append(filler)
        existing.append(written)
        return f"{line[: open_index + 1]}{', '.join(existing)}{line[close_index:]}"
    return line[:start] + written + line[end:]


def align_block_keyword_line(line: str, source: str, line_index: int) -> Optional[str]:
    stripped = str(line or "").strip()
    if not stripped.endswith(":"):
        return None
    name = command_name_from_snippet(stripped)
    if not _is_outdent_keyword(name):
        return None
    lines = str(source or "").splitlines() or [""]
    safe_index = max(0, min(int(line_index), len(lines) - 1))
    aligned = indent_snippet(stripped, _outer_indent(lines, safe_index))
    return aligned if aligned != line else None


def plan_command_insert(
    item: Dict[str, Any],
    source: str,
    line_index: int = 0,
    column: Optional[int] = None,
    select_start: Optional[int] = None,
    select_end: Optional[int] = None,
) -> Dict[str, Any]:
    snippet = str((item or {}).get("snippet") or "").rstrip()
    name = str((item or {}).get("name") or command_name_from_snippet(snippet)).strip()
    return plan_snippet_insert(snippet, source, line_index, column, select_start, select_end, name=name)


def _replace_span(line: str, start: int, end: int, snippet: str, line_index: int) -> Dict[str, Any]:
    return {
        "mode": "replace",
        "line": line_index,
        "text": line[:start] + snippet + line[end:],
    }


def plan_snippet_insert(
    snippet: str,
    source: str,
    line_index: int = 0,
    column: Optional[int] = None,
    select_start: Optional[int] = None,
    select_end: Optional[int] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """易语言式插入：有返回值就填进当前参数；选中已有值则包成第一个参数；否则另起一行。"""
    snippet = str(snippet or "").rstrip()
    lines = str(source or "").splitlines() or [""]
    safe_index = max(0, min(int(line_index), len(lines) - 1))
    current = lines[safe_index]
    command = str(name or command_name_from_snippet(snippet)).strip()
    if not _is_concrete_snippet(snippet):
        snippet = catalog_snippet(command) or snippet
    result_var = _nearest_result_var(lines, safe_index)
    cursor_column = len(current) if column is None else max(0, min(int(column), len(current)))
    start, end = ident_span(current, cursor_column)
    token = current[start:end]
    statement = statement_for_insert(command, snippet, result_var, current)

    if _should_complete_token(token, command, current):
        return _replace_span(current, start, end, statement, safe_index)

    can_nest = command_kind(command) == "expr"
    target = _nest_target(current, cursor_column, select_start, select_end) if can_nest else None
    if target:
        selected = current[target[0] : target[1]].strip()
        fill = wrap_first_arg(snippet, selected) if selected and not is_placeholder_text(selected) else snippet
        return _replace_span(current, target[0], target[1], fill, safe_index)

    if not current.strip():
        indent = _indent_from_above(lines, safe_index) or leading_whitespace(current)
        if _is_outdent_keyword(command):
            indent = _outer_indent(lines, safe_index)
        return {
            "mode": "replace",
            "line": safe_index,
            "text": indent_snippet(statement, indent),
        }
    if _is_block_header(current):
        indent = leading_whitespace(current)
        if not _is_outdent_keyword(command):
            indent += "    "
        return {
            "mode": "after",
            "line": _block_body_end(lines, safe_index),
            "text": "\n" + indent_snippet(statement, indent),
        }
    indent = leading_whitespace(current)
    if _is_outdent_keyword(command):
        indent = _outer_indent(lines, safe_index)
    return {
        "mode": "after",
        "line": safe_index,
        "text": "\n" + indent_snippet(statement, indent),
    }

_COMMAND_EXAMPLES = {
    "找图": (
        '图 = 找图("确定.png", 阈值=0.8)\n'
        "如果 图:\n"
        "    记录(图.分数)\n"
        "    点击(图)\n"
        "否则:\n"
        '    失败("没找到确定")\n'
        "\n"
        '图 = 找图("确定.png", "确定亮.png", 阈值=0.8)\n'
        '图 = 找图("确定.png", 区域=(10, 20, 200, 80))'
    ),
    "点击": (
        '图 = 找图("确定.png")\n'
        "如果 图:\n"
        "    点击(图)\n"
        '    点击(图, 键="右键")\n'
        "点击(120, 80)\n"
        "点击()"
    ),
    "移动": (
        '图 = 找图("确定.png")\n'
        "如果 图:\n"
        "    移动(图)\n"
        "移动(120, 80)"
    ),
    "按键": (
        '按键("Enter")\n'
        '按键("W", 秒=0.4)\n'
        '按键("W", 秒=(0.2, 0.6))\n'
        '按键("Ctrl+C")'
    ),
    "输入": '输入("你好")',
    "延时": "延时(0.3)",
    "找字": (
        '字 = 找字(目标="金币")\n'
        "如果 字:\n"
        "    记录(字.内容)\n"
        "    点文字(\"金币\")"
    ),
    "找字库": (
        '字 = 找字库(目标="确定", 字库="ui.txt")\n'
        "如果 字:\n"
        "    记录(字.内容)\n"
        "    点字库(\"确定\", 字库=\"ui.txt\")"
    ),
    "点字库": '点字库("确定", 字库="ui.txt")',
    "等字库": '字 = 等字库(目标="确定", 字库="ui.txt", 超时=8)',
    "等字库消失": '等字库消失(目标="确定", 字库="ui.txt", 超时=8)',
    "检测": (
        '结果 = 检测("yolo/xxx.onnx", 类别="敌人")\n'
        "如果 结果:\n"
        "    记录(结果.类别)\n"
        "    记录(结果.分数)\n"
        "    点击(结果)\n"
        "\n"
        "循环 目标 在 结果.列表:\n"
        '    如果 目标.类别 是 "敌人":\n'
        "        点击(目标)\n"
        "        中断"
    ),
    "框内点": (
        '结果 = 检测("yolo/xxx.onnx", 类别="敌人")\n'
        "如果 结果:\n"
        "    点 = 框内点(结果, 0.5, 0.85)\n"
        "    点击(点)"
    ),
    "随机点": (
        '结果 = 检测("yolo/xxx.onnx", 类别="敌人")\n'
        "如果 结果:\n"
        "    点击(随机点(结果))"
    ),
    "找色": (
        '色 = 找色("255,0,0")\n'
        "如果 色:\n"
        "    点击(色)"
    ),
    "拖拽": (
        "拖拽(10, 20, 200, 80)\n"
        '结果 = 检测("yolo/xxx.onnx", 类别="敌人")\n'
        "如果 结果:\n"
        "    拖拽(结果, 框内点(结果, 0.1, 0.5))"
    ),
    "滚轮": (
        '滚轮(方向="向下", 步数=3)\n'
        '结果 = 检测("yolo/xxx.onnx")\n'
        "如果 结果:\n"
        '    滚轮(结果, 方向="向下", 步数=3)'
    ),
    "点文字": (
        '点文字("确定")\n'
        '点文字("确定", 区域=(10, 20, 200, 40))'
    ),
    "点元素": '点元素("确定")',
    "等图": (
        '图 = 等图("确定.png", 超时=8)\n'
        "如果 图:\n"
        "    点击(图)"
    ),
    "等色": (
        '色 = 等色("255,0,0", 超时=8)\n'
        "如果 色:\n"
        "    点击(色)"
    ),
    "等文字": (
        '字 = 等文字("金币", 超时=8)\n'
        "如果 字:\n"
        '    点文字("金币")'
    ),
    "等图消失": '等图消失("加载中.png", 超时=8)',
    "等色消失": '等色消失("255,0,0", 超时=8)',
    "等文字消失": '等文字消失("请稍候", 超时=8)',
    "等检测": (
        '结果 = 等检测("yolo/xxx.onnx", 类别="敌人", 超时=8)\n'
        "如果 结果:\n"
        "    点击(结果)"
    ),
    "等检测消失": '等检测消失("yolo/xxx.onnx", 类别="敌人", 超时=8)',
    "持续找图": (
        '持续找图("确定.png", 间隔=0.3)\n'
        "当 真:\n"
        "    如果 找图:\n"
        "        点击(找图)\n"
        "        中断\n"
        "    延时(0.05)"
    ),
    "停止找图": "停止找图()",
    "停止检测": "停止检测()",
    "找所有图": (
        '图 = 找所有图("怪.png", 阈值=0.8, 最多=20)\n'
        "循环 一项 在 图.列表:\n"
        "    记录(一项.x)\n"
        "    点击(一项)"
    ),
    "取色": (
        "色 = 取色(120, 80)\n"
        "记录(色.红)\n"
        "记录(色.绿)\n"
        "记录(色.蓝)"
    ),
    "比色": (
        '如果 比色(120, 80, "255,0,0", 偏色=20):\n'
        '    记录("颜色对上了")'
    ),
    "按下": (
        '按下("W")\n'
        "延时(0.4)\n"
        '松开("W")'
    ),
    "松开": '松开("W")',
    "按住": (
        '按住("W", 秒=0.4)\n'
        "按住(目标, 秒=(0.2, 0.6))"
    ),
    "连点": (
        '图 = 找图("确定.png")\n'
        "如果 图:\n"
        "    连点(图, 次数=3, 间隔=0.08)"
    ),
    "等毫秒": "等毫秒(50)",
    "鼠标位置": (
        "位置 = 鼠标位置()\n"
        "记录(位置.x)\n"
        "记录(位置.y)"
    ),
    "相对移动": "相对移动(10, 0)",
    "激活": "激活()",
    "窗口.设置分辨率": (
        "窗口.设置分辨率(1280, 720)\n"
        '窗口.设置分辨率(1280, 720, "全部")\n'
        '窗口.设置分辨率("阴阳师", 报错=假)'
    ),
    "播放": (
        '播放("提示.wav")\n'
        '播放("提示.mp3", 等待=假)\n'
        "延时(0.5)\n"
        "停止播放()"
    ),
    "停止播放": "停止播放()",
    "回放": '回放("replays/过图.replay.json", 速度=1)',
    "截图": (
        '图 = 截图("shot.png")\n'
        "记录(图.路径)"
    ),
    "等按键": (
        '如果 等按键("F1", 超时=8):\n'
        "    点击()"
    ),
    "记录": '记录("已点确定")',
    "成功": "成功()",
    "失败": '失败("没找到确定")',
    "变量.获取": (
        '次数 = 变量.获取("次数", 0)\n'
        "如果 次数 >= 3:\n"
        '    失败("重试过多")'
    ),
    "变量.设置": '变量.设置("次数", 0)',
    "变量.增加": (
        '变量.设置("次数", 0)\n'
        '变量.增加("次数")\n'
        '记录(变量.获取("次数", 0))'
    ),
    "剪贴板.获取": (
        "文本 = 剪贴板.获取()\n"
        "记录(文本)"
    ),
    "剪贴板.设置": '剪贴板.设置("已复制")',
    "上次": (
        '找图("确定.png")\n'
        "如果 上次:\n"
        "    记录(上次.分数)\n"
        "    点击(上次.x, 上次.y)"
    ),
    "文字": (
        '找字(目标="金币")\n'
        "如果 文字:\n"
        "    记录(文字.内容)"
    ),
    "卡片": (
        "如果 卡片[3].通过:\n"
        "    记录(卡片[3].内容)"
    ),
    "窗口.宽": "记录(窗口.宽)",
    "窗口.高": "记录(窗口.高)",
    "如果": (
        '图 = 找图("确定.png")\n'
        "如果 图:\n"
        "    点击(图)\n"
        "否则:\n"
        '    失败("没找到确定")'
    ),
    "否则如果": (
        '字 = 找字(目标="金币")\n'
        '如果 字.内容 是 "金币":\n'
        '    点文字("金币")\n'
        '否则如果 字.内容 是 "银币":\n'
        '    点文字("银币")\n'
        "否则:\n"
        '    记录("都不是")'
    ),
    "否则": (
        '图 = 找图("确定.png")\n'
        "如果 图:\n"
        "    点击(图)\n"
        "否则:\n"
        '    失败("没找到确定")'
    ),
    "循环": (
        "循环 i 在 范围(3):\n"
        '    图 = 找图("确定.png")\n'
        "    如果 图:\n"
        "        点击(图)\n"
        "        中断"
    ),
    "当": (
        "当 找图:\n"
        "    点击(找图)\n"
        "    延时(0.3)"
    ),
    "中断": (
        "循环 i 在 范围(10):\n"
        '    如果 找图("确定.png"):\n'
        "        中断"
    ),
    "继续": (
        "循环 i 在 范围(10):\n"
        "    如果 i 是 0:\n"
        "        继续\n"
        "    记录(i)"
    ),
    "子程序": (
        "子程序 点确定():\n"
        '    图 = 找图("确定.png")\n'
        "    如果 图:\n"
        "        点击(图)\n"
        "        返回 真\n"
        "    返回 假\n"
        "\n"
        "如果 点确定():\n"
        "    成功()"
    ),
    "长度": '记录(长度(检测.列表))',
    "整数": "记录(整数(3.9))",
    "小数": "记录(小数(\"3.14\"))",
    "到文本": "记录(到文本(12))",
    "真假": "如果 真假(图):\n    点击(图)",
    "最小": "记录(最小(3, 8))",
    "最大": "记录(最大(3, 8))",
    "绝对值": "记录(绝对值(-4))",
    "开方": (
        "差x = 目标.x - 自己.x\n"
        "差y = 目标.y - 自己.y\n"
        "记录(开方(差x * 差x + 差y * 差y))"
    ),
    "限制": "x = 限制(目标.x, 0, 窗口.宽)",
    "距离": (
        '自己 = 检测("yolo/xxx.onnx", 类别="自己")\n'
        '目标 = 检测("yolo/xxx.onnx", 类别="敌人")\n'
        "如果 自己 并且 目标:\n"
        "    记录(距离(自己, 目标))"
    ),
    "角度": (
        '自己 = 检测("yolo/xxx.onnx", 类别="自己")\n'
        '目标 = 检测("yolo/xxx.onnx", 类别="敌人")\n'
        "如果 自己 并且 目标:\n"
        "    记录(角度(自己, 目标))"
    ),
    "正弦": "走y = 自己.y + 正弦(角) * 80",
    "余弦": "走x = 自己.x + 余弦(角) * 80",
    "范围": (
        "循环 i 在 范围(3):\n"
        "    记录(i)\n"
        "循环 n 在 范围(1, 5):\n"
        "    记录(n)"
    ),
    "随机": (
        "记录(随机())\n"
        "记录(随机(10))\n"
        "记录(随机(1, 10))\n"
        '按住("W", 秒=随机(0.2, 0.6))'
    ),
    "包含": (
        '如果 包含(文字.内容, "金币"):\n'
        '    点文字("金币")'
    ),
    "截取": '记录(截取(文字.内容, 1, 2))',
    "替换": '记录(替换(文字.内容, "旧", "新"))',
    "分割": (
        '项 = 分割("1,2,3", ",")\n'
        "记录(项[0])"
    ),
    "时间": (
        "起 = 时间()\n"
        "延时(0.3)\n"
        "记录(时间() - 起)"
    ),
    "去空格": '记录(去空格("  金币  "))',
    "查找": (
        '位置 = 查找(文字.内容, "金币")\n'
        "如果 位置 > 0:\n"
        "    记录(位置)"
    ),
    "提取数字": (
        '数量 = 提取数字(文字.内容)\n'
        "记录(数量)"
    ),
}
_COMMAND_RETURNS = {
    "找图": "赋给变量后，如果 图: 表示找到了。可读 图.分数  图.路径  图.x  图.y  图.通过",
    "等图": "找到就返回。超时则失败。可读 图.分数  图.路径  图.x  图.y",
    "等图消失": "图消失了为真。超时则失败。",
    "持续找图": "后台更新 找图。后面读 找图、找图.分数、找图.x，不要再写 找图()",
    "停止找图": "无",
    "找所有图": "图.列表 是全部匹配，图[0] 是第一个。也可读 图.x  图.y  图.通过",
    "找字": "如果 字: 表示认出了。可读 字.内容  字.x  字.y  字.通过",
    "找字库": "如果 字: 表示字库认出了。可读 字.内容  字.x  字.y  字.通过",
    "等字库": "找到就返回。可读 字.内容  字.x  字.y",
    "等字库消失": "这段字认不到了为真。",
    "点字库": "先用字库找再点。可读 结果.内容  结果.x  结果.y  结果.通过",
    "等文字": "找到就返回。可读 字.内容  字.x  字.y",
    "等文字消失": "这段字认不到了为真。",
    "点文字": "先找再点。可读 结果.内容  结果.x  结果.y  结果.通过",
    "点元素": "可读 结果.通过",
    "找色": "如果 色: 表示找到了。可读 色.颜色  色.红  色.绿  色.蓝  色.x  色.y",
    "等色": "找到就返回。可读 色.颜色  色.x  色.y",
    "等色消失": "这个颜色找不到了为真。",
    "取色": "色.红  色.绿  色.蓝  色.颜色",
    "比色": "颜色对上了为真。",
    "检测": "只认这一帧，默认不点。可读 结果.类别  结果.分数  结果.列表  结果.x  结果.y  结果.宽  结果.高",
    "等检测": "出现就返回。可读 结果.类别  结果.列表  结果.x  结果.y",
    "等检测消失": "这个类别检测不到了为真。",
    "持续检测": "结果写进 检测。读 检测、检测.列表，不要再写 检测()",
    "停止检测": "无",
    "点击": "可读 结果.x  结果.y。不写参数时点上次成功位置",
    "移动": "无",
    "框内点": "返回一个点，给 点击、移动、拖拽 用",
    "随机点": "返回框内随机一点",
    "拖拽": "无",
    "滚轮": "无",
    "按键": "无",
    "输入": "无",
    "延时": "无",
    "等毫秒": "无",
    "按下": "无",
    "松开": "无",
    "按住": "无",
    "连点": "无",
    "鼠标位置": "位置.x  位置.y",
    "相对移动": "无",
    "激活": "无",
    "播放": "无。等待=真 时播完才返回",
    "停止播放": "无",
    "记录": "无",
    "成功": "结束脚本，走成功线",
    "失败": "结束脚本，走失败线",
    "上次": "上次.通过  上次.成功  上次.类型  上次.分数  上次.阈值  上次.x  上次.y",
    "文字": "文字.内容  文字.通过",
    "卡片": "卡片[编号].内容  卡片[编号].分数  卡片[编号].通过",
    "窗口.宽": "当前绑定窗口客户区宽度",
    "窗口.高": "当前绑定窗口客户区高度",
    "窗口.设置分辨率": "可读 结果.宽  结果.高  结果.通过。报错=假 时失败返回假",
    "回放": "无。按录制轨迹前台回放",
    "截图": "可读 图.路径  图.通过",
    "等按键": "按时为真。超时为假",
    "变量.获取": "返回这个名字的值",
    "变量.设置": "无",
    "变量.增加": "返回增加后的值",
    "剪贴板.获取": "返回当前剪贴板文字",
    "剪贴板.设置": "无",
    "多线程": "无。子程序自己在旁边跑",
    "关闭线程": "无",
    "如果": "无。条件成立才跑缩进里的命令",
    "否则如果": "无",
    "否则": "无",
    "循环": "无",
    "当": "无",
    "中断": "无",
    "继续": "无",
    "子程序": "子程序里 返回 值 会带回给调用的地方",
    "长度": "返回个数",
    "整数": "返回整数",
    "小数": "返回小数",
    "到文本": "返回文字",
    "真假": "返回 真 或 假",
    "最小": "返回较小的那个",
    "最大": "返回较大的那个",
    "绝对值": "返回去掉正负号后的数",
    "开方": "返回平方根",
    "限制": "返回夹在两头之间的数",
    "距离": "返回像素距离",
    "角度": "返回度数",
    "正弦": "返回正弦值",
    "余弦": "返回余弦值",
    "范围": "返回一串数字，给 循环 用",
    "随机": "返回随机数",
    "包含": "有这段字为真",
    "截取": "返回截出来的文字",
    "替换": "返回换过的文字",
    "分割": "返回列表",
    "时间": "返回当前毫秒",
    "去空格": "返回去掉头尾空白的文字",
    "查找": "找到返回位置（从 1 起），找不到是 0",
    "提取数字": "返回抽出的第一个数字，没有是 0",
}
_EXTRA_PARAM_HELP = {
    "文件": "用资源栏导入，或写成 \"提示.wav\"",
    "等待": "写成 真 或 假。真是播完再往下，假是接着跑",
    "点击": "写成 真 或 假。真表示找到后立刻点",
    "区域": "用工具栏「框选区域」，或写成 (x, y, 宽, 高)",
    "图片2": "第二张备选图。多张图找到其中一张即成功，阈值仍写 阈值=",
    "最多": "最多返回多少个匹配",
    "超时": "最多等多少秒",
    "间隔": "两次查找之间等多少秒",
    "偏色": "每个颜色通道允许差多少",
    "步长": "每次加多少，默认 1",
    "毫秒": "等待的毫秒数",
    "按W": "你自己的子程序名，不要加括号",
    "默认值": "没有这个名字时用这个值",
    "值": "要写入或转换的值",
    "步数": "滚轮滚几格",
    "次数": "重复多少次",
}


def split_command_signatures(signature: str) -> List[str]:
    text = str(signature or "").strip()
    if not text:
        return []
    parts = [part.strip() for part in text.replace("\n", " / ").split(" / ") if part.strip()]
    return parts or [text]


def _param_help_map() -> Dict[str, str]:
    hints = dict(_EXTRA_PARAM_HELP)
    try:
        from task_workflow.script_sandbox import _PLACEHOLDER_HINTS

        merged = dict(_PLACEHOLDER_HINTS)
        merged.update(hints)
        return merged
    except Exception:
        return hints


def _command_param_lines(item: Dict[str, Any]) -> List[str]:
    hints = _param_help_map()
    lines = []
    seen = set()
    for overload in _normalize_overloads((item or {}).get("params")):
        for spec in overload:
            label = _field_label(spec)
            if not label or label in seen:
                continue
            seen.add(label)
            hint = str(hints.get(label) or "").strip()
            default = _field_default(spec)
            if hint and default:
                lines.append(f"{label}  {hint}。默认 {default}")
            elif hint:
                lines.append(f"{label}  {hint}")
            elif default:
                lines.append(f"{label}  默认 {default}")
            else:
                lines.append(label)
    return lines


def command_example_text(item: Dict[str, Any]) -> str:
    example = str((item or {}).get("example") or "").rstrip()
    if example:
        return example
    name = str((item or {}).get("name") or "")
    example = str(_COMMAND_EXAMPLES.get(name) or "").rstrip()
    if example:
        return example
    return str((item or {}).get("snippet") or "").rstrip()


def command_help_text(item: Optional[Dict[str, Any]] = None) -> str:
    if not item:
        return "点列表里的命令，这里只显示这一条的写法和例子。"
    name = str(item.get("name") or "").strip()
    blocks = []
    signatures = split_command_signatures(str(item.get("signature") or ""))
    if not signatures and name:
        signatures = [name]
    if signatures:
        blocks.append("写法\n" + "\n".join(signatures))
    note = str(item.get("note") or "").strip()
    if note:
        blocks.append("说明\n" + note)
    params = _command_param_lines(item)
    if params:
        blocks.append("参数\n" + "\n".join(params))
    example = command_example_text(item)
    if example:
        blocks.append("例\n" + example)
    returns = str(_COMMAND_RETURNS.get(name) or "").strip()
    if not returns:
        returns = command_returns_label(name)
    blocks.append("返回\n" + returns)
    blocks.append("双击或回车插入。插入后不会选中参数。要填进某个参数，先点到那个格子再插入。")
    return "\n\n".join(block for block in blocks if block)


def get_params_definition() -> Dict[str, Dict[str, Any]]:
    return {
        "script_source": {
            "label": "命令",
            "type": "text",
            "multiline": True,
            "default": DEFAULT_SCRIPT_SOURCE,
            "placeholder": SCRIPT_PLACEHOLDER,
            "tooltip": "用中文命令调用找图、点击、按键等现有能力。",
        },
    }


def validate_script_source(source: Any) -> None:
    from task_workflow.script_sandbox import ScriptError, unfilled_placeholder_error, validate_script

    text = str(source or "")
    validate_script(text)
    placeholder = unfilled_placeholder_error(text)
    if placeholder:
        raise ScriptError(placeholder)


def execute_task(
    params: Dict[str, Any],
    counters: Dict[str, int],
    execution_mode: str = "foreground",
    target_hwnd: Optional[int] = None,
    window_region=None,
    card_id: Optional[int] = None,
    **kwargs,
) -> Tuple[Any, ...]:
    source = str((params or {}).get("script_source") or "").strip()
    if not source:
        logger.error("[自定义脚本] 内容为空")
        return False, "执行下一步", None, "内容为空"

    try:
        from task_workflow.script_sandbox import ScriptError, run_script
        from task_workflow.workflow_context import get_runtime_store

        store = get_runtime_store()
        store.bind_counters(counters if isinstance(counters, dict) else {})
        store.set_current_card_id(card_id)
        executor = kwargs.get("executor")
        context = {
            "counters": counters if isinstance(counters, dict) else {},
            "execution_mode": execution_mode,
            "target_hwnd": target_hwnd,
            "bound_windows": kwargs.get("bound_windows")
            if kwargs.get("bound_windows") is not None
            else getattr(executor, "bound_windows", None),
            "custom_width": kwargs.get("custom_width")
            if kwargs.get("custom_width") is not None
            else getattr(executor, "custom_width", 0),
            "custom_height": kwargs.get("custom_height")
            if kwargs.get("custom_height") is not None
            else getattr(executor, "custom_height", 0),
            "adjust_window_resolution": kwargs.get("adjust_window_resolution")
            or getattr(executor, "adjust_window_resolution", None),
            "window_region": window_region,
            "card_id": card_id,
            "get_image_data": kwargs.get("get_image_data"),
            "stop_checker": kwargs.get("stop_checker"),
            "pause_checker": kwargs.get("pause_checker"),
            "executor": kwargs.get("executor"),
            "images_dir": kwargs.get("images_dir")
            if kwargs.get("images_dir") is not None
            else getattr(executor, "images_dir", None),
            "sounds_dir": kwargs.get("sounds_dir")
            if kwargs.get("sounds_dir") is not None
            else getattr(executor, "sounds_dir", None),
        }
        success, detail = run_script(source, store, logger, context=context)
        if success:
            logger.info("[自定义脚本] 执行成功%s", f": {detail}" if detail else "")
            return True, "执行下一步", None
        logger.info("[自定义脚本] 执行失败: %s", detail or "判断失败")
        return False, "执行下一步", None, detail or "判断失败"
    except ScriptError as exc:
        logger.error("[自定义脚本] %s", exc)
        return False, "执行下一步", None, str(exc)
    except Exception as exc:
        logger.exception("[自定义脚本] 未预期错误: %s", exc)
        return False, "执行下一步", None, str(exc)
