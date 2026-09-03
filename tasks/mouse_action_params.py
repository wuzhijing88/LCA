# -*- coding: utf-8 -*-
"""模拟鼠标操作任务的参数定义（面板 schema）。

只描述参数结构与默认值，不包含执行逻辑；由 tasks.mouse_action_task 作为任务契约的一部分导出。
"""

from typing import Any, Dict

from utils.input.input_timing import (
    DEFAULT_CLICK_HOLD_SECONDS,
    DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
    DEFAULT_RANDOM_CLICK_HOLD_MAX_SECONDS,
    DEFAULT_RANDOM_CLICK_HOLD_MIN_SECONDS,
)


def get_params_definition() -> Dict[str, Dict[str, Any]]:
    """获取参数定义"""
    params = {
        # 操作模式选择
        "operation_mode": {
            "label": "操作模式",
            "type": "select",
            "options": ["坐标点击", "找图功能", "文字点击", "找色功能", "元素点击", "鼠标滚轮", "鼠标拖拽", "鼠标移动"],
            "default": "坐标点击",
            "tooltip": "选择鼠标操作模式"
        },

        # 元素点击相关参数
        "---element_click_params---": {
            "type": "separator",
            "label": "元素点击参数（基于UIAutomation）",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_picker": {
            "type": "button",
            "label": "拾取元素",
            "button_text": "拾取元素 (右键确认)",
            "widget_hint": "element_picker",
            "tooltip": "点击后移动鼠标到目标元素，右键确认拾取，ESC取消",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "enable_browser_accessibility": {
            "type": "button",
            "label": "浏览器支持",
            "button_text": "启用浏览器辅助功能",
            "widget_hint": "enable_browser_accessibility",
            "tooltip": "为Chrome/Edge启用UIAutomation支持，启用后需重启浏览器",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_name": {
            "label": "元素名称",
            "type": "text",
            "default": "",
            "tooltip": "元素的名称属性，如按钮文字\"确定\"、\"取消\"等",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_automation_id": {
            "label": "自动化标识",
            "type": "text",
            "default": "",
            "tooltip": "元素的自动化标识属性，开发者定义的唯一标识",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_class_name": {
            "label": "类名",
            "type": "text",
            "default": "",
            "tooltip": "元素的类名属性",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_control_type": {
            "label": "控件类型",
            "type": "select",
            "options": ["无", "按钮", "编辑框", "文本", "复选框",
                       "单选按钮", "下拉框", "列表", "列表项",
                       "菜单", "菜单项", "树", "树节点",
                       "选项卡", "选项卡项", "超链接", "窗口",
                       "面板", "分组", "数据表格", "表格"],
            "default": "无",
            "tooltip": "控件类型，选择无表示不限制",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_found_index": {
            "label": "匹配索引",
            "type": "int",
            "default": 0,
            "min": 0,
            "max": 99,
            "tooltip": "当匹配到多个元素时，选择第几个（从0开始）",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_search_depth": {
            "label": "搜索深度",
            "type": "int",
            "default": 30,
            "min": 1,
            "max": 100,
            "tooltip": "控件树搜索深度，浏览器网页建议30以上",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_timeout": {
            "label": "超时时间(秒)",
            "type": "float",
            "default": 5.0,
            "min": 0.5,
            "max": 60.0,
            "decimals": 1,
            "tooltip": "查找元素的超时时间",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_use_invoke": {
            "label": "使用Invoke模式",
            "type": "bool",
            "default": True,
            "tooltip": "启用：使用Invoke模式点击（不移动鼠标，更可靠）；禁用：使用坐标点击",
            "condition": [
                {"param": "operation_mode", "value": "元素点击"},
                {"param": "element_enable_click", "value": True}
            ]
        },
        "element_enable_click": {
            "label": "启用点击",
            "type": "bool",
            "default": True,
            "tooltip": "关闭后仅定位元素，不执行点击",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_button": {
            "label": "鼠标按钮",
            "type": "select",
            "options": ["左键", "右键", "中键"],
            "default": "左键",
            "tooltip": "选择要点击的鼠标按钮",
            "condition": [
                {"param": "operation_mode", "value": "元素点击"},
                {"param": "element_enable_click", "value": True}
            ]
        },

        # 找图功能相关参数
        "---image_click_params---": {
            "type": "separator",
            "label": "找图功能参数",
            "condition": {"param": "operation_mode", "value": "找图功能"}
        },
        "multi_image_mode": {
            "label": "多图识别模式",
            "type": "select",
            "options": ["单图识别", "多图识别"],
            "default": "单图识别",
            "tooltip": "单图识别：只配置一张图片；多图识别：配置多张图片进行识别",
            "condition": {"param": "operation_mode", "value": "找图功能"}
        },
        "enable_parallel_recognition": {
            "label": "启用并行识别",
            "type": "checkbox",
            "default": True,
            "tooltip": "启用：多张图片并行识别，速度提升3-5倍；禁用：传统串行识别",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "image_path": {
            "label": "目标图片路径",
            "type": "file",
            "default": "",
            "file_filter": "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff);;所有文件 (*.*)",
            "tooltip": "需要查找并点击的图片文件",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "单图识别"}
            ]
        },
        "image_paths": {
            "label": "多图片路径",
            "type": "text",
            "default": "",
            "tooltip": "多张图片路径，每行一个路径。支持相对路径和绝对路径",
            "multiline": True,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "click_all_found": {
            "label": "全部点击",
            "type": "bool",
            "default": False,
            "tooltip": "启用：点击所有识别成功的图片；禁用：只点击第一张识别成功的图片",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "clear_clicked_on_next_run": {
            "label": "下次执行清除已点击记录",
            "type": "bool",
            "default": False,
            "tooltip": "启用：下次执行时清除已点击的图片记录；禁用：保持已点击记录直到全部完成",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "multi_image_delay": {
            "label": "每张图片识别延迟",
            "type": "float",
            "default": 1.0,
            "min": 0.0,
            "max": 10.0,
            "decimals": 1,
            "tooltip": "每张图片识别点击后的延迟时间（秒），防止速度过快导致图片识别失败",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        # 多图识别专用的识别区域参数
        "multi_use_recognition_region": {
            "label": "使用识别区域",
            "type": "bool",
            "default": False,
            "tooltip": "启用：仅在指定区域内识别图片；禁用：在整个窗口/屏幕范围识别",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "multi_image_region_selector": {
            "label": "识别区域",
            "type": "button",
            "widget_hint": "multi_image_region_selector",
            "button_text": "点击框选识别区域",
            "tooltip": "点击按钮在目标窗口上框选多图识别区域",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"},
                {"param": "multi_use_recognition_region", "value": True}
            ]
        },
        "multi_recognition_region_x": {
            "label": "识别区域X",
            "type": "hidden",
            "default": 0,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "multi_recognition_region_y": {
            "label": "识别区域Y",
            "type": "hidden",
            "default": 0,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "multi_recognition_region_width": {
            "label": "识别区域宽度",
            "type": "hidden",
            "default": 0,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "multi_recognition_region_height": {
            "label": "识别区域高度",
            "type": "hidden",
            "default": 0,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "confidence": {
            "label": "查找置信度",
            "type": "float",
            "default": 0.8,
            "min": 0.1,
            "max": 1.0,
            "decimals": 2,
            "tooltip": "图片匹配的相似度阈值 (0.1 到 1.0)",
            "condition": {"param": "operation_mode", "value": "找图功能"}
        },
        "test_image_recognition": {
            "label": "找图测试",
            "type": "button",
            "button_text": "测试找图并绘制结果",
            "tooltip": "测试图片识别，在绑定窗口上绘制出找到的图片区域",
            "action": "test_image_recognition",
            "condition": {"param": "operation_mode", "value": "找图功能"}
        },
        "use_recognition_region": {
            "label": "使用识别区域",
            "type": "bool",
            "default": False,
            "tooltip": "启用：仅在指定区域内识别图片；禁用：在整个窗口/屏幕范围识别",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "单图识别"}
            ]
        },
        "image_region_selector": {
            "label": "识别区域",
            "type": "button",
            "widget_hint": "image_region_selector",
            "button_text": "点击框选识别区域",
            "tooltip": "点击按钮在目标窗口上框选图片识别区域",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "单图识别"},
                {"param": "use_recognition_region", "value": True}
            ]
        },
        "recognition_region_x": {
            "label": "识别区域X",
            "type": "hidden",
            "default": 0,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "单图识别"}
            ]
        },
        "recognition_region_y": {
            "label": "识别区域Y",
            "type": "hidden",
            "default": 0,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "单图识别"}
            ]
        },
        "recognition_region_width": {
            "label": "识别区域宽度",
            "type": "hidden",
            "default": 0,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "单图识别"}
            ]
        },
        "recognition_region_height": {
            "label": "识别区域高度",
            "type": "hidden",
            "default": 0,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "单图识别"}
            ]
        },
        "image_enable_click": {
            "label": "识别后执行点击",
            "type": "bool",
            "default": True,
            "tooltip": "启用：识别成功后执行点击；禁用：仅识别不点击",
            "condition": {"param": "operation_mode", "value": "找图功能"}
        },
        "image_position_mode": {
            "label": "点击位置",
            "type": "select",
            "options": ["精准坐标", "固定偏移", "随机偏移"],
            "default": "精准坐标",
            "tooltip": "精准坐标：使用图片中心精准点击\n固定偏移：先在图片中心基础上添加固定偏移，再可选叠加随机偏移\n随机偏移：在图片中心基础上添加随机偏移",
            "condition": {"param": "operation_mode", "value": "找图功能"}
        },
        "image_offset_selector_tool": {
            "label": "偏移选择",
            "type": "button",
            "button_text": "拖拽选择偏移",
            "tooltip": "从目标点拖拽选择固定偏移距离，会自动切换为固定偏移",
            "widget_hint": "offset_selector",
            "related_params": ["image_fixed_offset_x", "image_fixed_offset_y", "image_position_mode"],
            "condition": {"param": "operation_mode", "value": "找图功能"}
        },
"image_fixed_offset_x": {
            "label": "固定X偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在图片位置上增加固定的X偏移（正数向右，负数向左）",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "image_position_mode", "value": "固定偏移"}
            ]
        },
        "image_fixed_offset_y": {
            "label": "固定Y偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在图片位置上增加固定的Y偏移（正数向下，负数向上）",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "image_position_mode", "value": "固定偏移"}
            ]
        },
        "image_random_offset_x": {
            "label": "随机X偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "X轴随机偏移范围，实际偏移在 [-X, +X] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {
                "param": "operation_mode",
                "value": "找图功能",
                "and": {"param": "image_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
            }
        },
        "image_random_offset_y": {
            "label": "随机Y偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "Y轴随机偏移范围，实际偏移在 [-Y, +Y] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {
                "param": "operation_mode",
                "value": "找图功能",
                "and": {"param": "image_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
            }
        },
        "image_click_action": {
            "label": "点击动作",
            "type": "select",
            "options": ["完整点击", "双击", "仅按下", "仅松开"],
            "default": "完整点击",
            "tooltip": "完整点击：按下并松开；双击：连续两次点击；仅按下：按下不松开；仅松开：松开按钮",
            "condition": {"param": "operation_mode", "value": "找图功能"}
        },
        "image_enable_auto_release": {
            "label": "自动释放",
            "type": "bool",
            "default": True,
            "tooltip": "启用后，按下鼠标后会自动释放。",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "image_click_action", "value": "仅按下"}
            ]
        },
        "image_hold_mode": {
            "label": "持续时间模式",
            "type": "select",
            "options": ["固定持续时间", "随机持续时间"],
            "default": "固定持续时间",
            "tooltip": "选择按键按下后持续时间的模式。",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "image_click_action", "value": "仅按下"},
                {"param": "image_enable_auto_release", "value": True}
            ]
        },
        "image_hold_duration": {
            "label": "按下持续时间(秒)",
            "type": "float",
            "default": DEFAULT_CLICK_HOLD_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "按下鼠标后保持的时间",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "image_click_action", "value": "仅按下"},
                {"param": "image_enable_auto_release", "value": True},
                {"param": "image_hold_mode", "value": "固定持续时间"}
            ]
        },
        "image_hold_duration_min": {
            "label": "持续时间最小值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MIN_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最小值。",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "image_click_action", "value": "仅按下"},
                {"param": "image_enable_auto_release", "value": True},
                {"param": "image_hold_mode", "value": "随机持续时间"}
            ]
        },
        "image_hold_duration_max": {
            "label": "持续时间最大值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MAX_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最大值。",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "image_click_action", "value": "仅按下"},
                {"param": "image_enable_auto_release", "value": True},
                {"param": "image_hold_mode", "value": "随机持续时间"}
            ]
        },

        # 文字点击相关参数
        "---text_click_params---": {
            "type": "separator",
            "label": "文字点击参数",
            "condition": {"param": "operation_mode", "value": "文字点击"}
        },
        "text_match_mode": {
            "label": "文字匹配模式",
            "type": "select",
            "options": ["包含", "完全匹配"],
            "default": "包含",
            "tooltip": "文字匹配的方式\n包含：目标文字包含在识别文字中即可\n完全匹配：识别文字必须与目标文字完全一致",
            "condition": {"param": "operation_mode", "value": "文字点击"}
        },
        "text_enable_click": {
            "label": "识别后执行点击",
            "type": "bool",
            "default": True,
            "tooltip": "启用：识别到目标文字后执行点击；禁用：仅识别不点击",
            "condition": {"param": "operation_mode", "value": "文字点击"}
        },
        "text_position_mode": {
            "label": "点击位置",
            "type": "select",
            "options": ["精准坐标", "固定偏移", "随机偏移"],
            "default": "精准坐标",
            "tooltip": "精准坐标：使用文字中心精准点击\n固定偏移：先在文字中心基础上添加固定偏移，再可选叠加随机偏移\n随机偏移：在文字中心基础上添加随机偏移",
            "condition": {"param": "operation_mode", "value": "文字点击"}
        },
        "text_offset_selector_tool": {
            "label": "偏移选择",
            "type": "button",
            "button_text": "拖拽选择偏移",
            "tooltip": "从目标点拖拽选择固定偏移距离，会自动切换为固定偏移",
            "widget_hint": "offset_selector",
            "related_params": ["text_fixed_offset_x", "text_fixed_offset_y", "text_position_mode"],
            "condition": {"param": "operation_mode", "value": "文字点击"}
        },
"text_fixed_offset_x": {
            "label": "固定X偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在文字位置上增加固定的X偏移（正数向右，负数向左）",
            "condition": [
                {"param": "operation_mode", "value": "文字点击"},
                {"param": "text_position_mode", "value": "固定偏移"}
            ]
        },
        "text_fixed_offset_y": {
            "label": "固定Y偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在文字位置上增加固定的Y偏移（正数向下，负数向上）",
            "condition": [
                {"param": "operation_mode", "value": "文字点击"},
                {"param": "text_position_mode", "value": "固定偏移"}
            ]
        },
        "text_random_offset_x": {
            "label": "随机X偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "X轴随机偏移范围，实际偏移在 [-X, +X] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {
                "param": "operation_mode",
                "value": "文字点击",
                "and": {"param": "text_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
            }
        },
        "text_random_offset_y": {
            "label": "随机Y偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "Y轴随机偏移范围，实际偏移在 [-Y, +Y] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {
                "param": "operation_mode",
                "value": "文字点击",
                "and": {"param": "text_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
            }
        },
        "text_click_action": {
            "label": "点击动作",
            "type": "select",
            "options": ["完整点击", "双击", "仅按下", "仅松开"],
            "default": "完整点击",
            "tooltip": "完整点击：按下并松开；双击：连续两次点击；仅按下：按下不松开；仅松开：松开按钮",
            "condition": {"param": "operation_mode", "value": "文字点击"}
        },
        "text_enable_auto_release": {
            "label": "自动释放",
            "type": "bool",
            "default": True,
            "tooltip": "启用后，按下鼠标后会自动释放。",
            "condition": [
                {"param": "operation_mode", "value": "文字点击"},
                {"param": "text_click_action", "value": "仅按下"}
            ]
        },
        "text_hold_mode": {
            "label": "持续时间模式",
            "type": "select",
            "options": ["固定持续时间", "随机持续时间"],
            "default": "固定持续时间",
            "tooltip": "选择按键按下后持续时间的模式。",
            "condition": [
                {"param": "operation_mode", "value": "文字点击"},
                {"param": "text_click_action", "value": "仅按下"},
                {"param": "text_enable_auto_release", "value": True}
            ]
        },
        "text_hold_duration": {
            "label": "按下持续时间(秒)",
            "type": "float",
            "default": DEFAULT_CLICK_HOLD_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "按下鼠标后保持的时间",
            "condition": [
                {"param": "operation_mode", "value": "文字点击"},
                {"param": "text_click_action", "value": "仅按下"},
                {"param": "text_enable_auto_release", "value": True},
                {"param": "text_hold_mode", "value": "固定持续时间"}
            ]
        },
        "text_hold_duration_min": {
            "label": "持续时间最小值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MIN_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最小值。",
            "condition": [
                {"param": "operation_mode", "value": "文字点击"},
                {"param": "text_click_action", "value": "仅按下"},
                {"param": "text_enable_auto_release", "value": True},
                {"param": "text_hold_mode", "value": "随机持续时间"}
            ]
        },
        "text_hold_duration_max": {
            "label": "持续时间最大值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MAX_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最大值。",
            "condition": [
                {"param": "operation_mode", "value": "文字点击"},
                {"param": "text_click_action", "value": "仅按下"},
                {"param": "text_enable_auto_release", "value": True},
                {"param": "text_hold_mode", "value": "随机持续时间"}
            ]
        },

        # 找色功能相关参数
        "---color_click_params---": {
            "type": "separator",
            "label": "找色功能参数",
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "target_color": {
            "label": "目标颜色",
            "type": "text",
            "default": "",
            "tooltip": "颜色格式：\n1. 单颜色: 255,0,0 （红色）\n2. 多颜色组合: 255,0,0;0,255,0 （用分号分隔）\n3. 多点定位: 255,0,0|10,20,0,255,0|50,0,0,0,255\n   格式：基准点R,G,B|偏移X,偏移Y,R,G,B|...\n\n使用本地截图和OpenCV HSV匹配",
            "condition": {"param": "operation_mode", "value": "找色功能"},
            "widget_hint": "colorpicker"
        },
        "search_region_enabled": {
            "label": "使用识别区域",
            "type": "checkbox",
            "default": False,
            "tooltip": "启用：仅在指定识别区域内找色；禁用：在整个窗口范围找色",
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "color_search_region_selector": {
            "label": "识别区域",
            "type": "button",
            "widget_hint": "color_region_selector",
            "button_text": "点击框选识别区域",
            "tooltip": "点击按钮在目标窗口上框选颜色识别区域",
            "condition": [
                {"param": "operation_mode", "value": "找色功能"},
                {"param": "search_region_enabled", "value": True}
            ]
        },
        "search_region_x": {
            "label": "识别区域X",
            "type": "hidden",
            "default": 0,
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "search_region_y": {
            "label": "识别区域Y",
            "type": "hidden",
            "default": 0,
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "search_region_width": {
            "label": "识别区域宽度",
            "type": "hidden",
            "default": 0,
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "search_region_height": {
            "label": "识别区域高度",
            "type": "hidden",
            "default": 0,
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "test_color_recognition": {
            "label": "找色测试",
            "type": "button",
            "button_text": "测试找色并绘制结果",
            "tooltip": "测试颜色识别，在绑定窗口上绘制出找到的颜色位置",
            "action": "test_color_recognition",
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "color_enable_click": {
            "label": "识别后执行点击",
            "type": "bool",
            "default": True,
            "tooltip": "启用：识别成功后执行点击；禁用：仅识别不点击",
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "click_position_mode": {
            "label": "点击位置",
            "type": "select",
            "options": ["精准坐标", "固定偏移", "随机偏移"],
            "default": "精准坐标",
            "tooltip": "精准坐标：使用颜色中心精准点击\n固定偏移：先在颜色中心基础上添加固定偏移，再可选叠加随机偏移\n随机偏移：在颜色中心基础上添加随机偏移",
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "color_offset_selector_tool": {
            "label": "偏移选择",
            "type": "button",
            "button_text": "拖拽选择偏移",
            "tooltip": "从目标点拖拽选择固定偏移距离，会自动切换为固定偏移",
            "widget_hint": "offset_selector",
            "related_params": ["color_fixed_offset_x", "color_fixed_offset_y", "click_position_mode"],
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
"color_fixed_offset_x": {
            "label": "固定X偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在找到的位置上增加固定的X偏移（正数向右，负数向左）",
            "condition": [
                {"param": "operation_mode", "value": "找色功能"},
                {"param": "click_position_mode", "value": "固定偏移"}
            ]
        },
        "color_fixed_offset_y": {
            "label": "固定Y偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在找到的位置上增加固定的Y偏移（正数向下，负数向上）",
            "condition": [
                {"param": "operation_mode", "value": "找色功能"},
                {"param": "click_position_mode", "value": "固定偏移"}
            ]
        },
        "color_random_offset_x": {
            "label": "随机X偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "X轴随机偏移范围，实际偏移在 [-X, +X] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {
                "param": "operation_mode",
                "value": "找色功能",
                "and": {"param": "click_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
            }
        },
        "color_random_offset_y": {
            "label": "随机Y偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "Y轴随机偏移范围，实际偏移在 [-Y, +Y] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {
                "param": "operation_mode",
                "value": "找色功能",
                "and": {"param": "click_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
            }
        },
        "color_click_button": {
            "label": "鼠标按钮",
            "type": "select",
            "options": ["左键", "右键", "中键"],
            "default": "左键",
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "color_click_clicks": {
            "label": "点击次数",
            "type": "int",
            "default": 1,
            "min": 1,
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "color_click_interval": {
            "label": "点击间隔(秒)",
            "type": "float",
            "default": DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "color_click_action": {
            "label": "点击动作",
            "type": "select",
            "options": ["完整点击", "双击", "仅按下", "仅松开"],
            "default": "完整点击",
            "tooltip": "完整点击：按下并松开；双击：连续两次点击；仅按下：按下不松开；仅松开：松开按钮",
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "color_enable_auto_release": {
            "label": "自动释放",
            "type": "bool",
            "default": True,
            "tooltip": "启用后，按下鼠标后会自动释放。",
            "condition": [
                {"param": "operation_mode", "value": "找色功能"},
                {"param": "color_click_action", "value": "仅按下"}
            ]
        },
        "color_hold_mode": {
            "label": "持续时间模式",
            "type": "select",
            "options": ["固定持续时间", "随机持续时间"],
            "default": "固定持续时间",
            "tooltip": "选择按键按下后持续时间的模式。",
            "condition": [
                {"param": "operation_mode", "value": "找色功能"},
                {"param": "color_click_action", "value": "仅按下"},
                {"param": "color_enable_auto_release", "value": True}
            ]
        },
        "color_hold_duration": {
            "label": "按下持续时间(秒)",
            "type": "float",
            "default": DEFAULT_CLICK_HOLD_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "按下鼠标后保持的时间",
            "condition": [
                {"param": "operation_mode", "value": "找色功能"},
                {"param": "color_click_action", "value": "仅按下"},
                {"param": "color_enable_auto_release", "value": True},
                {"param": "color_hold_mode", "value": "固定持续时间"}
            ]
        },
        "color_hold_duration_min": {
            "label": "持续时间最小值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MIN_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最小值。",
            "condition": [
                {"param": "operation_mode", "value": "找色功能"},
                {"param": "color_click_action", "value": "仅按下"},
                {"param": "color_enable_auto_release", "value": True},
                {"param": "color_hold_mode", "value": "随机持续时间"}
            ]
        },
        "color_hold_duration_max": {
            "label": "持续时间最大值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MAX_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最大值。",
            "condition": [
                {"param": "operation_mode", "value": "找色功能"},
                {"param": "color_click_action", "value": "仅按下"},
                {"param": "color_enable_auto_release", "value": True},
                {"param": "color_hold_mode", "value": "随机持续时间"}
            ]
        },

        # 坐标点击相关参数
        "---coordinate_click_params---": {
            "type": "separator",
            "label": "坐标点击参数",
            "condition": {"param": "operation_mode", "value": "坐标点击"}
        },
        "coordinate_source_mode": {
            "label": "坐标获取方式",
            "type": "select",
            "options": ["坐标工具获取坐标", "手动输入", "无坐标"],
            "default": "坐标工具获取坐标",
            "tooltip": "选择坐标来源：可用坐标工具拾取、手动输入固定坐标，或直接点击当前鼠标位置",
            "condition": {"param": "operation_mode", "value": "坐标点击"}
        },
        "coordinate_selector_tool": {
            "label": "坐标获取工具",
            "type": "button",
            "button_text": "点击获取坐标",
            "tooltip": "点击后可以在目标窗口中选择坐标位置",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_source_mode", "value": "坐标工具获取坐标"}
            ],
            "widget_hint": "coordinate_selector_with_display",
            "related_params": ["coordinate_x", "coordinate_y"]
        },
        "coordinate_value": {
            "label": "自定义坐标（兼容）",
            "type": "text",
            "default": "",
            "hidden": True,
            "placeholder": "示例: 100,200 或 {\"x\":100,\"y\":200}",
            "tooltip": "兼容旧工作流使用，新工作流请使用坐标工具或手动输入",
            "condition": {"param": "operation_mode", "value": "坐标点击"}
        },
        "coordinate_x": {
            "label": "X坐标",
            "type": "int",
            "default": 0,
            "min": 0,
            "tooltip": "点击位置的X坐标",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_source_mode", "value": "手动输入"}
            ]
        },
        "coordinate_y": {
            "label": "Y坐标",
            "type": "int",
            "default": 0,
            "min": 0,
            "tooltip": "点击位置的Y坐标",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_source_mode", "value": "手动输入"}
            ]
        },
        "coordinate_mode": {
            "label": "坐标模式",
            "type": "select",
            "options": ["客户区坐标", "窗口坐标", "屏幕坐标"],
            "default": "客户区坐标",
            "tooltip": "客户区坐标相对于窗口内容区域，窗口坐标相对于窗口左上角，屏幕坐标相对于整个屏幕",
            "condition": {
                "param": "operation_mode",
                "value": "坐标点击",
                "and": {
                    "param": "coordinate_source_mode",
                    "value": "无坐标",
                    "operator": "!="
                }
            }
        },
        "coordinate_enable_click": {
            "label": "执行点击",
            "type": "bool",
            "default": True,
            "tooltip": "关闭后仅解析坐标，不执行点击",
            "condition": {"param": "operation_mode", "value": "坐标点击"}
        },
        "coordinate_position_mode": {
            "label": "点击位置",
            "type": "select",
            "options": ["精准坐标", "固定偏移", "随机偏移"],
            "default": "精准坐标",
            "tooltip": "精准坐标：使用目标坐标精准点击\n固定偏移：先在目标坐标基础上添加固定偏移，再可选叠加随机偏移\n随机偏移：在目标坐标基础上添加随机偏移",
            "condition": {"param": "operation_mode", "value": "坐标点击"}
        },
        "coordinate_offset_selector_tool": {
            "label": "偏移选择",
            "type": "button",
            "button_text": "拖拽选择偏移",
            "tooltip": "从目标点拖拽选择固定偏移距离，会自动切换为固定偏移",
            "widget_hint": "offset_selector",
            "related_params": ["coordinate_fixed_offset_x", "coordinate_fixed_offset_y", "coordinate_position_mode"],
            "condition": {"param": "operation_mode", "value": "坐标点击"}
        },
"coordinate_fixed_offset_x": {
            "label": "固定X偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在指定坐标上增加固定的X偏移（正数向右，负数向左）",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_position_mode", "value": "固定偏移"}
            ]
        },
        "coordinate_fixed_offset_y": {
            "label": "固定Y偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在指定坐标上增加固定的Y偏移（正数向下，负数向上）",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_position_mode", "value": "固定偏移"}
            ]
        },
        "coordinate_random_offset_x": {
            "label": "随机X偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "X轴随机偏移范围，实际偏移在 [-X, +X] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {
                "param": "operation_mode",
                "value": "坐标点击",
                "and": {"param": "coordinate_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
            }
        },
        "coordinate_random_offset_y": {
            "label": "随机Y偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "Y轴随机偏移范围，实际偏移在 [-Y, +Y] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {
                "param": "operation_mode",
                "value": "坐标点击",
                "and": {"param": "coordinate_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
            }
        },
        "coordinate_click_action": {
            "label": "点击动作",
            "type": "select",
            "options": ["完整点击", "双击", "仅按下", "仅松开"],
            "default": "完整点击",
            "tooltip": "完整点击：按下并松开；双击：连续两次点击；仅按下：按下不松开；仅松开：松开按钮",
            "condition": {"param": "operation_mode", "value": "坐标点击"}
        },
        "coordinate_enable_auto_release": {
            "label": "自动释放",
            "type": "bool",
            "default": True,
            "tooltip": "启用后，按下鼠标后会自动释放。",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_click_action", "value": "仅按下"}
            ]
        },
        "coordinate_hold_mode": {
            "label": "持续时间模式",
            "type": "select",
            "options": ["固定持续时间", "随机持续时间"],
            "default": "固定持续时间",
            "tooltip": "选择按键按下后持续时间的模式。",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_click_action", "value": "仅按下"},
                {"param": "coordinate_enable_auto_release", "value": True}
            ]
        },
        "coordinate_hold_duration": {
            "label": "按下持续时间(秒)",
            "type": "float",
            "default": DEFAULT_CLICK_HOLD_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "按下鼠标后保持的时间",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_click_action", "value": "仅按下"},
                {"param": "coordinate_enable_auto_release", "value": True},
                {"param": "coordinate_hold_mode", "value": "固定持续时间"}
            ]
        },
        "coordinate_hold_duration_min": {
            "label": "持续时间最小值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MIN_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最小值。",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_click_action", "value": "仅按下"},
                {"param": "coordinate_enable_auto_release", "value": True},
                {"param": "coordinate_hold_mode", "value": "随机持续时间"}
            ]
        },
        "coordinate_hold_duration_max": {
            "label": "持续时间最大值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MAX_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最大值。",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_click_action", "value": "仅按下"},
                {"param": "coordinate_enable_auto_release", "value": True},
                {"param": "coordinate_hold_mode", "value": "随机持续时间"}
            ]
        },

        # 鼠标滚轮相关参数
        "---scroll_params---": {
            "type": "separator",
            "label": "鼠标滚轮参数",
            "condition": {"param": "operation_mode", "value": "鼠标滚轮"}
        },
        "scroll_direction": {
            "label": "滚动方向",
            "type": "select",
            "options": ["向上", "向下"],
            "default": "向下",
            "tooltip": "鼠标滚轮的滚动方向",
            "condition": {"param": "operation_mode", "value": "鼠标滚轮"}
        },
        "scroll_clicks": {
            "label": "滚动步数",
            "type": "int",
            "default": 3,
            "min": 1,
            "max": 999,
            "tooltip": "滚轮执行的步数",
            "condition": {"param": "operation_mode", "value": "鼠标滚轮"}
        },
        "scroll_interval": {
            "label": "滚动间隔(秒)",
            "type": "float",
            "default": 0.1,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "多次滚动之间的间隔时间",
            "condition": {"param": "operation_mode", "value": "鼠标滚轮"}
        },
        "scroll_coordinate_selector": {
            "label": "坐标获取工具",
            "type": "button",
            "button_text": "点击获取坐标",
            "tooltip": "点击选择滚轮操作的起始坐标位置",
            "widget_hint": "coordinate_selector",
            "condition": {"param": "operation_mode", "value": "鼠标滚轮"}
        },
        "scroll_start_position": {
            "label": "滚动起始位置",
            "type": "text",
            "default": "500,300",
            "tooltip": "执行滚轮操作的起始坐标位置",
            "readonly": True,
            "condition": {"param": "operation_mode", "value": "鼠标滚轮"}
        },

        # 鼠标拖拽相关参数
        "---drag_params---": {
            "type": "separator",
            "label": "鼠标拖拽参数",
            "condition": {"param": "operation_mode", "value": "鼠标拖拽"}
        },
        "drag_mode": {
            "label": "拖拽模式",
            "type": "select",
            "options": ["简单拖拽", "多点路径拖拽"],
            "default": "简单拖拽",
            "tooltip": "简单拖拽: 直线移动\n多点路径: 沿复杂路径",
            "condition": {"param": "operation_mode", "value": "鼠标拖拽"}
        },

        # ===== 简单拖拽起点参数 =====
        "---drag_start_params---": {
            "type": "separator",
            "label": "拖拽起点设置",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": {"param": "drag_mode", "value": "简单拖拽"}
            }
        },
        "drag_start_mode": {
            "label": "起点定位方式",
            "type": "select",
            "options": ["坐标", "图片"],
            "default": "坐标",
            "tooltip": "坐标: 使用固定坐标\n图片: 通过图片识别定位",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": {"param": "drag_mode", "value": "简单拖拽"}
            }
        },
        # 起点 - 坐标模式参数
        "drag_start_coordinate_selector": {
            "label": "起点坐标获取",
            "type": "button",
            "button_text": "获取起点坐标",
            "tooltip": "点击选择拖拽操作的起点坐标",
            "widget_hint": "coordinate_selector",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_start_mode", "value": "坐标"}
                ]
            }
        },
        "drag_start_position": {
            "label": "拖拽起点",
            "type": "text",
            "default": "500,300",
            "tooltip": "拖拽操作的起点坐标(x,y)",
            "readonly": True,
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_start_mode", "value": "坐标"}
                ]
            }
        },
        # 起点 - 图片模式参数
        "drag_start_image_path": {
            "label": "起点图片",
            "type": "file",
            "default": "",
            "file_filter": "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff);;所有文件 (*.*)",
            "tooltip": "拖拽起点的目标图片",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_start_mode", "value": "图片"}
                ]
            }
        },
        "drag_start_confidence": {
            "label": "起点图片置信度",
            "type": "float",
            "default": 0.8,
            "min": 0.1,
            "max": 1.0,
            "step": 0.05,
            "decimals": 2,
            "tooltip": "起点图片匹配的相似度阈值",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_start_mode", "value": "图片"}
                ]
            }
        },
        "drag_start_offset_x": {
            "label": "起点X偏移",
            "type": "int",
            "default": 0,
            "min": -500,
            "max": 500,
            "tooltip": "相对于图片中心的X偏移量",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_start_mode", "value": "图片"}
                ]
            }
        },
        "drag_start_offset_y": {
            "label": "起点Y偏移",
            "type": "int",
            "default": 0,
            "min": -500,
            "max": 500,
            "tooltip": "相对于图片中心的Y偏移量",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_start_mode", "value": "图片"}
                ]
            }
        },

        # ===== 简单拖拽终点参数 =====
        "---drag_end_params---": {
            "type": "separator",
            "label": "拖拽终点设置",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": {"param": "drag_mode", "value": "简单拖拽"}
            }
        },
        "drag_end_mode": {
            "label": "终点定位方式",
            "type": "select",
            "options": ["坐标", "图片"],
            "default": "坐标",
            "tooltip": "坐标: 使用固定坐标\n图片: 通过图片识别定位",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": {"param": "drag_mode", "value": "简单拖拽"}
            }
        },
        # 终点 - 坐标模式参数
        "drag_end_coordinate_selector": {
            "label": "终点坐标获取",
            "type": "button",
            "button_text": "获取终点坐标",
            "tooltip": "点击选择拖拽操作的终点坐标",
            "widget_hint": "coordinate_selector",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_end_mode", "value": "坐标"}
                ]
            }
        },
        "drag_end_position": {
            "label": "拖拽终点",
            "type": "text",
            "default": "700,300",
            "tooltip": "拖拽操作的终点坐标(x,y)",
            "readonly": True,
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_end_mode", "value": "坐标"}
                ]
            }
        },
        # 终点 - 图片模式参数
        "drag_end_image_path": {
            "label": "终点图片",
            "type": "file",
            "default": "",
            "file_filter": "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff);;所有文件 (*.*)",
            "tooltip": "拖拽终点的目标图片",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_end_mode", "value": "图片"}
                ]
            }
        },
        "drag_end_confidence": {
            "label": "终点图片置信度",
            "type": "float",
            "default": 0.8,
            "min": 0.1,
            "max": 1.0,
            "step": 0.05,
            "decimals": 2,
            "tooltip": "终点图片匹配的相似度阈值",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_end_mode", "value": "图片"}
                ]
            }
        },
        "drag_end_offset_x": {
            "label": "终点X偏移",
            "type": "int",
            "default": 0,
            "min": -500,
            "max": 500,
            "tooltip": "相对于图片中心的X偏移量",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_end_mode", "value": "图片"}
                ]
            }
        },
        "drag_end_offset_y": {
            "label": "终点Y偏移",
            "type": "int",
            "default": 0,
            "min": -500,
            "max": 500,
            "tooltip": "相对于图片中心的Y偏移量",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_end_mode", "value": "图片"}
                ]
            }
        },

        # ===== 拖拽控制参数 =====
        "---drag_control_params---": {
            "type": "separator",
            "label": "拖拽控制参数",
            "condition": {"param": "operation_mode", "value": "鼠标拖拽"}
        },
        "drag_button": {
            "label": "拖拽按钮",
            "type": "select",
            "options": ["左键", "右键", "中键"],
            "default": "左键",
            "tooltip": "拖拽时使用的鼠标按钮",
            "condition": {"param": "operation_mode", "value": "鼠标拖拽"}
        },
        "drag_duration": {
            "label": "拖拽持续时间(秒)",
            "type": "float",
            "default": 1.0,
            "min": 0.1,
            "max": 10.0,
            "step": 0.1,
            "decimals": 1,
            "tooltip": "完成拖拽操作的时间(实际时间不会超过此值)",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": {"param": "drag_mode", "value": "简单拖拽"}
            }
        },
        "drag_smoothness": {
            "label": "拖拽平滑度",
            "type": "int",
            "default": 100,
            "min": 5,
            "max": 100,
            "tooltip": "拖拽轨迹的平滑程度，数值越大越平滑(默认100)",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": {"param": "drag_mode", "value": "简单拖拽"}
            }
        },

        # ===== 多点路径拖拽参数 =====
        "path_points": {
            "label": "路径点坐标",
            "type": "textarea",
            "default": "100,100\n200,150\n300,200\n400,250",
            "tooltip": "每行一个坐标: x,y,time\n如: 100,100,0.5",
            "rows": 8,
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": {"param": "drag_mode", "value": "多点路径拖拽"}
            }
        },

        # 鼠标移动相关参数
        "---move_params---": {
            "type": "separator",
            "label": "鼠标移动参数",
            "condition": {"param": "operation_mode", "value": "鼠标移动"}
        },
        "move_mode": {
            "label": "移动模式",
            "type": "select",
            "options": ["绝对移动", "相对移动"],
            "default": "绝对移动",
            "tooltip": "绝对移动: 从起点移动到终点\n相对移动: 相对当前位置移动",
            "condition": {"param": "operation_mode", "value": "鼠标移动"}
        },

        # 绝对移动 - 起点参数
        "move_start_coordinate_selector": {
            "label": "起点坐标获取",
            "type": "button",
            "button_text": "获取起点坐标",
            "tooltip": "点击选择移动的起点坐标",
            "widget_hint": "coordinate_selector",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_mode", "value": "绝对移动"}
            }
        },
        "move_start_position": {
            "label": "移动起点",
            "type": "text",
            "default": "100,100",
            "tooltip": "鼠标移动的起点坐标(x,y)",
            "readonly": True,
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_mode", "value": "绝对移动"}
            }
        },

        # 绝对移动 - 终点参数
        "move_end_coordinate_selector": {
            "label": "终点坐标获取",
            "type": "button",
            "button_text": "获取终点坐标",
            "tooltip": "点击选择移动的终点坐标",
            "widget_hint": "coordinate_selector",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_mode", "value": "绝对移动"}
            }
        },
        "move_end_position": {
            "label": "移动终点",
            "type": "text",
            "default": "500,300",
            "tooltip": "鼠标移动的终点坐标(x,y)",
            "readonly": True,
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_mode", "value": "绝对移动"}
            }
        },

        # 相对移动参数
        "move_offset_mode": {
            "label": "偏移模式",
            "type": "select",
            "options": ["固定偏移", "随机偏移"],
            "default": "固定偏移",
            "tooltip": "固定偏移: 使用固定的偏移值\n随机偏移: 在范围内随机偏移",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_mode", "value": "相对移动"}
            }
        },
        "move_offset_x": {
            "label": "X偏移量",
            "type": "int",
            "default": 100,
            "min": -2000,
            "max": 2000,
            "tooltip": "相对当前鼠标位置的X偏移量\n正值: 向右移动\n负值: 向左移动",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {
                    "param": "move_mode",
                    "value": "相对移动",
                    "and": {"param": "move_offset_mode", "value": "固定偏移"}
                }
            }
        },
        "move_offset_y": {
            "label": "Y偏移量",
            "type": "int",
            "default": 100,
            "min": -2000,
            "max": 2000,
            "tooltip": "相对当前鼠标位置的Y偏移量\n正值: 向下移动\n负值: 向上移动",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {
                    "param": "move_mode",
                    "value": "相对移动",
                    "and": {"param": "move_offset_mode", "value": "固定偏移"}
                }
            }
        },
        "move_offset_x_min": {
            "label": "X偏移最小值",
            "type": "int",
            "default": -50,
            "min": -2000,
            "max": 2000,
            "tooltip": "X偏移量的最小值\n正值: 向右移动\n负值: 向左移动",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {
                    "param": "move_mode",
                    "value": "相对移动",
                    "and": {"param": "move_offset_mode", "value": "随机偏移"}
                }
            }
        },
        "move_offset_x_max": {
            "label": "X偏移最大值",
            "type": "int",
            "default": 50,
            "min": -2000,
            "max": 2000,
            "tooltip": "X偏移量的最大值\n正值: 向右移动\n负值: 向左移动",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {
                    "param": "move_mode",
                    "value": "相对移动",
                    "and": {"param": "move_offset_mode", "value": "随机偏移"}
                }
            }
        },
        "move_offset_y_min": {
            "label": "Y偏移最小值",
            "type": "int",
            "default": -50,
            "min": -2000,
            "max": 2000,
            "tooltip": "Y偏移量的最小值\n正值: 向下移动\n负值: 向上移动",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {
                    "param": "move_mode",
                    "value": "相对移动",
                    "and": {"param": "move_offset_mode", "value": "随机偏移"}
                }
            }
        },
        "move_offset_y_max": {
            "label": "Y偏移最大值",
            "type": "int",
            "default": 50,
            "min": -2000,
            "max": 2000,
            "tooltip": "Y偏移量的最大值\n正值: 向下移动\n负值: 向上移动",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {
                    "param": "move_mode",
                    "value": "相对移动",
                    "and": {"param": "move_offset_mode", "value": "随机偏移"}
                }
            }
        },
        "move_duration_mode": {
            "label": "持续时间模式",
            "type": "select",
            "options": ["固定持续时间", "随机持续时间"],
            "default": "固定持续时间",
            "tooltip": "固定持续时间: 使用固定的时间值\n随机持续时间: 在范围内随机选择时间",
            "condition": {"param": "operation_mode", "value": "鼠标移动"}
        },
        "move_duration": {
            "label": "移动持续时间(秒)",
            "type": "float",
            "default": 0.5,
            "min": 0.0,
            "max": 10.0,
            "step": 0.1,
            "decimals": 1,
            "tooltip": "完成移动操作的时间，0为瞬间移动",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_duration_mode", "value": "固定持续时间"}
            }
        },
        "move_duration_min": {
            "label": "最小持续时间(秒)",
            "type": "float",
            "default": 0.3,
            "min": 0.0,
            "max": 10.0,
            "step": 0.1,
            "decimals": 1,
            "tooltip": "随机持续时间的最小值",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_duration_mode", "value": "随机持续时间"}
            }
        },
        "move_duration_max": {
            "label": "最大持续时间(秒)",
            "type": "float",
            "default": 0.8,
            "min": 0.0,
            "max": 10.0,
            "step": 0.1,
            "decimals": 1,
            "tooltip": "随机持续时间的最大值",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_duration_mode", "value": "随机持续时间"}
            }
        },
        "move_use_bezier": {
            "label": "使用贝塞尔曲线",
            "type": "bool",
            "default": False,
            "tooltip": "启用后使用随机贝塞尔曲线轨迹，模拟人类鼠标移动",
            "condition": {"param": "operation_mode", "value": "鼠标移动"}
        },
        "move_smoothness": {
            "label": "移动平滑度",
            "type": "int",
            "default": 50,
            "min": 5,
            "max": 100,
            "tooltip": "移动轨迹的平滑程度，数值越大越平滑（仅贝塞尔曲线模式有效）",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_use_bezier", "value": True}
            }
        },

        # 鼠标移动后的点击参数
        "move_enable_click": {
            "label": "移动后启用点击",
            "type": "bool",
            "default": False,
            "tooltip": "启用后在移动到终点位置后执行点击操作",
            "condition": {"param": "operation_mode", "value": "鼠标移动"}
        },
        "move_click_button": {
            "label": "鼠标按钮",
            "type": "select",
            "options": ["左键", "右键", "中键"],
            "default": "左键",
            "tooltip": "选择要点击的鼠标按钮",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_enable_click", "value": True}
            }
        },
        "move_click_clicks": {
            "label": "点击次数",
            "type": "int",
            "default": 1,
            "min": 1,
            "tooltip": "连续点击的次数",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_enable_click", "value": True}
            }
        },
        "move_click_interval": {
            "label": "点击间隔(秒)",
            "type": "float",
            "default": DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "多次点击之间的间隔时间",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_enable_click", "value": True}
            }
        },
        "move_click_action": {
            "label": "点击动作",
            "type": "select",
            "options": ["完整点击", "双击", "仅按下", "仅松开"],
            "default": "完整点击",
            "tooltip": "完整点击：按下并松开；双击：连续两次点击；仅按下：按下不松开；仅松开：松开按钮",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_enable_click", "value": True}
            }
        },
        "move_enable_auto_release": {
            "label": "自动释放",
            "type": "bool",
            "default": True,
            "tooltip": "启用后，按下鼠标后会自动释放。",
            "condition": [
                {"param": "operation_mode", "value": "鼠标移动"},
                {"param": "move_enable_click", "value": True},
                {"param": "move_click_action", "value": "仅按下"}
            ]
        },
        "move_hold_mode": {
            "label": "持续时间模式",
            "type": "select",
            "options": ["固定持续时间", "随机持续时间"],
            "default": "固定持续时间",
            "tooltip": "选择按键按下后持续时间的模式。",
            "condition": [
                {"param": "operation_mode", "value": "鼠标移动"},
                {"param": "move_enable_click", "value": True},
                {"param": "move_click_action", "value": "仅按下"},
                {"param": "move_enable_auto_release", "value": True}
            ]
        },
        "move_hold_duration": {
            "label": "按下持续时间(秒)",
            "type": "float",
            "default": DEFAULT_CLICK_HOLD_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "按下鼠标后保持的时间",
            "condition": [
                {"param": "operation_mode", "value": "鼠标移动"},
                {"param": "move_enable_click", "value": True},
                {"param": "move_click_action", "value": "仅按下"},
                {"param": "move_enable_auto_release", "value": True},
                {"param": "move_hold_mode", "value": "固定持续时间"}
            ]
        },
        "move_hold_duration_min": {
            "label": "持续时间最小值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MIN_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最小值。",
            "condition": [
                {"param": "operation_mode", "value": "鼠标移动"},
                {"param": "move_enable_click", "value": True},
                {"param": "move_click_action", "value": "仅按下"},
                {"param": "move_enable_auto_release", "value": True},
                {"param": "move_hold_mode", "value": "随机持续时间"}
            ]
        },
        "move_hold_duration_max": {
            "label": "持续时间最大值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MAX_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最大值。",
            "condition": [
                {"param": "operation_mode", "value": "鼠标移动"},
                {"param": "move_enable_click", "value": True},
                {"param": "move_click_action", "value": "仅按下"},
                {"param": "move_enable_auto_release", "value": True},
                {"param": "move_hold_mode", "value": "随机持续时间"}
            ]
        },

        # 通用点击参数（仅点击模式显示）
        "---common_click_params---": {
            "type": "separator",
            "label": "点击参数",
            "condition": {"param": "operation_mode", "value": ["找图功能", "坐标点击", "文字点击"]}
        },
        "button": {
            "label": "鼠标按钮",
            "type": "select",
            "options": ["左键", "右键", "中键"],
            "default": "左键",
            "tooltip": "要使用的鼠标按钮",
            "condition": {"param": "operation_mode", "value": ["找图功能", "坐标点击", "文字点击"]}
        },
        "clicks": {
            "label": "点击次数",
            "type": "int",
            "default": 1,
            "min": 1,
            "tooltip": "连续点击的次数",
            "condition": {"param": "operation_mode", "value": ["找图功能", "坐标点击", "文字点击"]}
        },
        "interval": {
            "label": "点击间隔(秒)",
            "type": "float",
            "default": DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "多次点击之间的间隔时间",
            "condition": {"param": "operation_mode", "value": ["找图功能", "坐标点击", "文字点击"]}
        },

        # 重试机制（找图功能/找色功能）
        "---retry_params---": {
            "type": "separator",
            "label": "重试设置",
            "condition": {"param": "operation_mode", "value": ["找图功能", "找色功能"]}
        },
        "enable_retry": {
            "label": "启用失败重试",
            "type": "bool",
            "default": False,
            "tooltip": "如果识别失败，是否进行重试",
            "condition": {"param": "operation_mode", "value": ["找图功能", "找色功能"]}
        },
        "retry_attempts": {
            "label": "重试次数",
            "type": "int",
            "default": 3,
            "min": 1,
            "max": 10,
            "tooltip": "最大重试次数",
            "condition": [
                {"param": "operation_mode", "value": ["找图功能", "找色功能"]},
                {"param": "enable_retry", "value": True}
            ]
        },
        "retry_interval": {
            "label": "重试间隔(秒)",
            "type": "float",
            "default": 0.5,
            "min": 0.1,
            "decimals": 2,
            "tooltip": "重试之间的等待时间",
            "condition": [
                {"param": "operation_mode", "value": ["找图功能", "找色功能"]},
                {"param": "enable_retry", "value": True}
            ]
        },
        # 下一步延迟执行参数
        "---next_step_delay---": {"type": "separator", "label": "下一步延迟执行"},
        "enable_next_step_delay": {
            "label": "启用下一步延迟执行",
            "type": "bool",
            "default": False,
            "tooltip": "勾选后，执行完当前操作会等待指定时间再执行下一步"
        },
        "delay_mode": {
            "label": "延迟模式",
            "type": "select",
            "options": ["固定延迟", "随机延迟"],
            "default": "固定延迟",
            "tooltip": "选择固定延迟时间还是随机延迟时间",
            "condition": {"param": "enable_next_step_delay", "value": True}
        },
        "fixed_delay": {
            "label": "固定延迟 (秒)",
            "type": "float",
            "default": 1.0,
            "min": 0.0,
            "max": 3600.0,
            "step": 0.1,
            "decimals": 2,
            "tooltip": "设置固定的延迟时间",
            "condition": {
                "param": "delay_mode",
                "value": "固定延迟",
                "and": {"param": "enable_next_step_delay", "value": True}
            }
        },
        "min_delay": {
            "label": "最小延迟 (秒)",
            "type": "float",
            "default": 0.5,
            "min": 0.0,
            "max": 3600.0,
            "step": 0.1,
            "decimals": 2,
            "tooltip": "设置随机延迟的最小值",
            "condition": {
                "param": "delay_mode",
                "value": "随机延迟",
                "and": {"param": "enable_next_step_delay", "value": True}
            }
        },
        "max_delay": {
            "label": "最大延迟 (秒)",
            "type": "float",
            "default": 2.0,
            "min": 0.0,
            "max": 3600.0,
            "step": 0.1,
            "decimals": 2,
            "tooltip": "设置随机延迟的最大值",
            "condition": {
                "param": "delay_mode",
                "value": "随机延迟",
                "and": {"param": "enable_next_step_delay", "value": True}
            }
        },

        # 执行后操作
        "---post_execute---": {"type": "separator", "label": "执行后操作"},
        "on_success": {
            "label": "成功后操作",
            "type": "select",
            "options": ["继续执行本步骤", "执行下一步", "跳转到步骤", "停止工作流"],
            "default": "执行下一步",
            "tooltip": "点击成功后的操作"
        },
        "success_jump_target_id": {
            "label": "成功跳转目标ID",
            "type": "int",
            "default": 0,
            "min": 0,
            "widget_hint": "card_selector",
            "condition": {"param": "on_success", "value": "跳转到步骤"}
        },
        "on_failure": {
            "label": "失败后操作",
            "type": "select",
            "options": ["继续执行本步骤", "执行下一步", "跳转到步骤", "停止工作流"],
            "default": "执行下一步",
            "tooltip": "点击失败后的操作"
        },
        "failure_jump_target_id": {
            "label": "失败跳转目标ID",
            "type": "int",
            "default": 0,
            "min": 0,
            "widget_hint": "card_selector",
            "condition": {"param": "on_failure", "value": "跳转到步骤"}
        }
    }

    def _append_extra_condition(param_key: str, extra_condition: Dict[str, Any]) -> None:
        param_def = params.get(param_key)
        if not isinstance(param_def, dict):
            return
        existing_condition = param_def.get("condition")
        if existing_condition is None:
            param_def["condition"] = dict(extra_condition)
            return
        if isinstance(existing_condition, list):
            param_def["condition"] = list(existing_condition) + [dict(extra_condition)]
            return
        if isinstance(existing_condition, dict):
            and_condition = existing_condition.get("and")
            if and_condition is None:
                existing_condition["and"] = dict(extra_condition)
            elif isinstance(and_condition, list):
                existing_condition["and"] = list(and_condition) + [dict(extra_condition)]
            else:
                existing_condition["and"] = [and_condition, dict(extra_condition)]

    image_click_enabled = {"param": "image_enable_click", "value": True}
    for key in (
        "image_position_mode",
        "image_offset_selector_tool",
        "image_fixed_offset_x",
        "image_fixed_offset_y",
        "image_random_offset_x",
        "image_random_offset_y",
        "image_click_action",
        "image_enable_auto_release",
        "image_hold_mode",
        "image_hold_duration",
        "image_hold_duration_min",
        "image_hold_duration_max",
    ):
        _append_extra_condition(key, image_click_enabled)

    color_click_enabled = {"param": "color_enable_click", "value": True}
    for key in (
        "click_position_mode",
        "color_offset_selector_tool",
        "color_fixed_offset_x",
        "color_fixed_offset_y",
        "color_random_offset_x",
        "color_random_offset_y",
        "color_click_button",
        "color_click_clicks",
        "color_click_interval",
        "color_click_action",
        "color_enable_auto_release",
        "color_hold_mode",
        "color_hold_duration",
        "color_hold_duration_min",
        "color_hold_duration_max",
    ):
        _append_extra_condition(key, color_click_enabled)

    text_click_enabled = {"param": "text_enable_click", "value": True}
    for key in (
        "text_position_mode",
        "text_offset_selector_tool",
        "text_fixed_offset_x",
        "text_fixed_offset_y",
        "text_random_offset_x",
        "text_random_offset_y",
        "text_click_action",
        "text_enable_auto_release",
        "text_hold_mode",
        "text_hold_duration",
        "text_hold_duration_min",
        "text_hold_duration_max",
    ):
        _append_extra_condition(key, text_click_enabled)

    coordinate_click_enabled = {"param": "coordinate_enable_click", "value": True}
    for key in (
        "coordinate_position_mode",
        "coordinate_offset_selector_tool",
        "coordinate_fixed_offset_x",
        "coordinate_fixed_offset_y",
        "coordinate_random_offset_x",
        "coordinate_random_offset_y",
        "coordinate_click_action",
        "coordinate_enable_auto_release",
        "coordinate_hold_mode",
        "coordinate_hold_duration",
        "coordinate_hold_duration_min",
        "coordinate_hold_duration_max",
    ):
        _append_extra_condition(key, coordinate_click_enabled)

    return params
