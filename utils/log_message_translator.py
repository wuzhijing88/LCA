# -*- coding: utf-8 -*-
import ctypes
import logging
import os
import re
from functools import lru_cache
from typing import List, Tuple


_LEVEL_MAP = {
    "DEBUG": "调试",
    "INFO": "信息",
    "WARNING": "警告",
    "ERROR": "错误",
    "CRITICAL": "严重",
}

_PHRASE_REPLACEMENTS: List[Tuple[str, str]] = [
    (r"failed to get function address for", "获取函数地址失败："),
    (r"read parent workflow context failed:", "读取父工作流上下文失败："),
    (r"onnx runtime not available for class names:", "ONNX Runtime 不可用，无法读取类别名："),
    (r"failed to show missing classes\.txt prompt:", "显示缺少 classes.txt 提示失败："),
    (r"failed to read class names from onnx metadata:", "从 ONNX 元数据读取类别名失败："),
    (r"failed to read classes\.txt:", "读取 classes.txt 失败："),
    (r"no class names found in onnx metadata or classes\.txt; using class_id labels", "未在 ONNX 元数据或 classes.txt 中找到类别名，将使用 class_id 标签"),
    (r"no class names found in onnx metadata or classes\.txt", "未在 ONNX 元数据或 classes.txt 中找到类别名"),
    (r"failed to show yolo warning dialog:", "显示 YOLO 警告弹窗失败："),
    (r"failed to request workflow stop for yolo:", "请求停止工作流失败（YOLO）："),
    (r"yolo forbids background capture engines; current_engine=", "YOLO 截图引擎不受支持，当前引擎="),
    (r"YOLO capture only supports dxgi/gdi; current_engine=", "YOLO 截图引擎不受支持，当前引擎="),
    (r"yolo requires gdi but gdi is unavailable", "YOLO 需要 GDI，但当前 GDI 不可用"),
    (r"failed to check screenshot engine for yolo:", "检查 YOLO 截图引擎失败："),
    (r"overlay draw loop failed:", "悬浮绘制循环失败："),
    (r"gdi\+ init failed:", "GDI+ 初始化失败："),
    (r"winapi init failed:", "WinAPI 初始化失败："),
    (r"overlay class registration failed:", "悬浮窗类注册失败："),
    (r"gdi fallback draw failed:", "GDI 回退绘制失败："),
    (r"overlay render failed:", "悬浮层渲染失败："),
    (r"qt overlay position failed:", "Qt 悬浮层定位失败："),
    (r"qt overlay invoker failed:", "Qt 悬浮层调用器执行失败："),
    (r"overlay update emit failed:", "悬浮层更新信号发送失败："),
    (r"tracking state update failed:", "跟踪状态更新失败："),
    (r"tracking capture failed:", "跟踪截图失败："),
    (r"overlay runtime shutdown timed out", "悬浮层运行时关闭超时"),
    (r"setwindowsize failed:", "设置窗口大小失败："),
    (r"setclientsize failed:", "设置客户区大小失败："),
    (r"\[replay\] win32api unavailable for relative move", "[回放] Win32API 不可用，无法执行相对移动"),
    (r"\[replay\] relative move failed:", "[回放] 相对移动失败："),
    (r"dxgi enumadapters1 failed:", "DXGI EnumAdapters1 调用失败："),
    (r"dxgi getdesc1 failed:", "DXGI GetDesc1 调用失败："),
    (r"black border fix failed:", "黑边修复失败："),
    (r"foreground driver init failed:", "前台驱动初始化失败："),
    (r"foreground driver unavailable", "前台驱动不可用"),
    (r"virtual screen bounds unavailable:", "虚拟屏幕边界不可用："),
    (r"failed to delete connection:", "删除连线失败："),
    (r"failed to create jump connection", "创建跳转连线失败"),
    (r"failed to create random connection", "创建随机连线失败"),
    (r"failed to create sequential connection", "创建顺序连线失败"),
    (r"startup hook failed:", "启动钩子执行失败："),
    (r"subprocess entry failed:", "子进程入口执行失败："),
    (r"yolo capture failed:", "YOLO 截图失败："),
    (r"deferred remove retry failed:", "延迟移除重试失败："),
    (r"remove task failed:", "移除任务失败："),
    (r"stop before remove failed:", "移除前停止任务失败："),
    (r"force cleanup before remove failed:", "移除前强制清理失败："),
    (r"set recording panel position failed:", "设置录制面板位置失败："),
    (r"failed to set overlay geometry:", "设置悬浮层几何信息失败："),
    (r"license validation worker failed:", "许可证校验工作线程失败："),
    (r"license dialog validation failed:", "许可证弹窗校验失败："),
    (r"failed to persist license key:", "持久化许可证密钥失败："),
    (r"failed to show license dialog:", "显示许可证弹窗失败："),
    (r"auto-save before hide failed:", "隐藏前自动保存失败："),
    (r"workflow context cleanup failed:", "工作流上下文清理失败："),
    (r"failed to read parameter", "读取参数失败"),
    (r"failed to collect parameter", "收集参数失败"),
    (r"failed to reset widget", "重置控件失败"),
    (r"bound window selector source failed:", "绑定窗口选择器来源失败："),
    (r"task_state_manager\.request_start failed:", "task_state_manager.request_start 失败："),
    (r"task_state_manager rejected this start request", "task_state_manager 拒绝了本次启动请求"),
    (r"safe start flow failed:", "安全启动流程失败："),
    (r"stop window failed:", "停止窗口失败："),
    (r"runner cleanup failed:", "运行器清理失败："),
    (r"ocr cleanup check failed:", "OCR 清理检查失败："),
    (r"batch workflow execute failed:", "批量工作流执行失败："),
    (r"workflow task not found:", "未找到工作流任务："),
    (r"failed to apply motion region selection:", "应用运动区域选择失败："),
    (r"failed to apply image region selection:", "应用图片区域选择失败："),
    (r"failed to apply multi-image region selection:", "应用多图区域选择失败："),
    (r"failed to apply color search region selection:", "应用找色区域选择失败："),
    (r"failed to start yolo realtime preview:", "启动 YOLO 实时预览失败："),
    (r"no window hwnd found; fallback to window title", "未找到窗口句柄，回退到窗口标题"),
    (r"window position verification failed:", "窗口位置校验失败："),
    (r"ocr coordinate conversion failed:", "OCR 坐标转换失败："),
    (r"ocr rect conversion failed:", "OCR 区域转换失败："),
    (r"traceback:", "堆栈："),
    (r"read timed out", "读取超时"),
    (r"max retries exceeded", "已超过最大重试次数"),
]

_REPLACEMENTS: List[Tuple[str, str]] = [
    # 状态标签
    (r"\[OK\]", "[成功]"),
    (r"\[ERROR\]", "[错误]"),
    (r"\[WARN\]", "[警告]"),
    (r"\[INFO\]", "[信息]"),
    (r"\[DEBUG\]", "[调试]"),
    # 悬浮窗
    (r"\bFloatingWindow\b", "悬浮窗"),
    (r"\bon_step_log\b", "悬浮窗日志"),
    # 卡片相关
    (r"\bcard_id\b", "卡片ID"),
    (r"\btask_type\b", "任务类型"),
    (r"\bcustom_name\b", "自定义名称"),
    (r"\bis_executing\b", "执行中"),
    (r"\bnext_id\b", "下一步ID"),
    (r"\brequest_id\b", "请求ID"),
    (r"\bprocess_id\b", "进程ID"),
    # 窗口相关
    (r"\bwindow_title\b", "窗口标题"),
    (r"\bwindow_hwnd\b", "窗口句柄"),
    (r"\bhwnd\b", "句柄"),
    (r"\bwindow_name\b", "窗口名"),
    (r"\btarget_window\b", "目标窗口"),
    # 执行模式
    (r"\bstate\b", "状态"),
    (r"\bforeground_driver\b", "前台驱动"),
    (r"\bbackground_driver\b", "后台驱动"),
    (r"\bforeground\b", "前台"),
    (r"\bbackground\b", "后台"),
    # 执行状态
    (r"\bexecuting\b", "执行中"),
    (r"\bexecuted\b", "已执行"),
    (r"\bexecute\b", "执行"),
    (r"\bfailed\b", "失败"),
    (r"\bfailure\b", "失败"),
    (r"\bsuccess\b", "成功"),
    (r"\bsucceeded\b", "成功"),
    (r"\bcompleted\b", "完成"),
    (r"\bfinished\b", "完成"),
    (r"\bstarted\b", "已开始"),
    (r"\bstopped\b", "已停止"),
    (r"\bpaused\b", "已暂停"),
    (r"\bresumed\b", "已恢复"),
    (r"\brunning\b", "运行中"),
    (r"\bwaiting\b", "等待中"),
    (r"\bpending\b", "待处理"),
    # 参数相关
    (r"\bregion_x\b", "区域X"),
    (r"\bregion_y\b", "区域Y"),
    (r"\bregion_width\b", "区域宽"),
    (r"\bregion_height\b", "区域高"),
    (r"\bregion_mode\b", "区域模式"),
    (r"\bregion_coordinates\b", "区域坐标"),
    (r"\bcompare_mode\b", "比对模式"),
    (r"\bdelay_mode\b", "延迟模式"),
    (r"\bmatch_mode\b", "匹配模式"),
    (r"\btext_recognition_mode\b", "识别模式"),
    (r"\brecognition_type\b", "识别类型"),
    (r"\btarget_text\b", "目标文字"),
    (r"\btarget_number\b", "目标数字"),
    (r"\bconfidence_threshold\b", "置信度阈值"),
    (r"\bconfidence\b", "置信度"),
    (r"\bsimilarity_threshold\b", "相似度阈值"),
    (r"\bsimilarity\b", "相似度"),
    (r"\benable_binarization\b", "启用二值化"),
    (r"\benable_compare\b", "启用比对"),
    (r"\benable_next_step_delay\b", "启用延迟"),
    (r"\bfixed_delay\b", "固定延迟"),
    (r"\bmin_delay\b", "最小延迟"),
    (r"\bmax_delay\b", "最大延迟"),
    (r"\bon_success\b", "成功时"),
    (r"\bon_failure\b", "失败时"),
    # 布尔值
    (r"\bTrue\b", "是"),
    (r"\bFalse\b", "否"),
    (r"\bNone\b", "无"),
    # 其他
    (r"\btimeout\b", "超时"),
    (r"\bretry\b", "重试"),
    (r"\binterval\b", "间隔"),
    (r"\boffset\b", "偏移"),
    (r"\bclick\b", "点击"),
    (r"\bscroll\b", "滚动"),
    (r"\bdrag\b", "拖拽"),
    (r"\binput\b", "输入"),
    (r"\boutput\b", "输出"),
    (r"\bunknown\b", "未知"),
    (r"\binvalid\b", "无效"),
    (r"\bmissing\b", "缺少"),
    (r"\bunexpected\b", "未预期"),
    (r"\brequest\b", "请求"),
    (r"\bresponse\b", "响应"),
    (r"\bconnection\b", "连接"),
    (r"\blicense\b", "许可证"),
    (r"\bvalidation\b", "校验"),
    (r"\bauthenticate\b", "认证"),
    (r"\bauthorization\b", "授权"),
    (r"\brejected\b", "被拒绝"),
    (r"\binitiate\b", "初始化"),
    (r"\bbind\b", "绑定"),
    (r"\bfetch\b", "获取"),
    (r"\bfallback\b", "回退"),
    (r"\bfailed to\b", "未能"),
]

_SHORT_PATH_PATTERN = re.compile(
    r"(?i)\b[a-z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*[^\\/:*?\"<>|\r\n]*~\d[^\\/:*?\"<>|\r\n]*(?:\\[^\\/:*?\"<>|\r\n]+)*"
)


def _build_long_path_getter():
    if os.name != "nt":
        return None
    try:
        get_long = ctypes.windll.kernel32.GetLongPathNameW
        get_long.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        get_long.restype = ctypes.c_uint
        return get_long
    except Exception:
        return None


_GET_LONG_PATH_NAME_W = _build_long_path_getter()


@lru_cache(maxsize=4096)
def _to_long_path_if_possible(path: str) -> str:
    if not path or "~" not in path:
        return path
    if _GET_LONG_PATH_NAME_W is None:
        return path
    try:
        required = _GET_LONG_PATH_NAME_W(path, None, 0)
        if required != 0:
            buffer = ctypes.create_unicode_buffer(required)
            result = _GET_LONG_PATH_NAME_W(path, buffer, required)
            if result != 0:
                long_path = buffer.value
                if long_path:
                    return long_path

        # 完整路径不存在时，尝试转换最长存在前缀，再拼接剩余后缀
        parts = path.split("\\")
        if len(parts) < 2:
            return path

        prefix = parts[0] + "\\"
        consumed = 1
        best_prefix = prefix if os.path.exists(prefix) else ""
        best_index = consumed

        for idx in range(1, len(parts)):
            if not parts[idx]:
                continue
            if prefix.endswith("\\"):
                prefix = prefix + parts[idx]
            else:
                prefix = prefix + "\\" + parts[idx]
            if os.path.exists(prefix):
                best_prefix = prefix
                best_index = idx + 1
            consumed = idx + 1

        if not best_prefix:
            return path

        need = _GET_LONG_PATH_NAME_W(best_prefix, None, 0)
        if need == 0:
            return path
        out = ctypes.create_unicode_buffer(need)
        got = _GET_LONG_PATH_NAME_W(best_prefix, out, need)
        if got == 0:
            return path

        long_prefix = out.value
        if not long_prefix:
            return path

        tail_parts = [p for p in parts[best_index:] if p]
        if not tail_parts:
            return long_prefix
        sep = "" if long_prefix.endswith("\\") else "\\"
        return long_prefix + sep + "\\".join(tail_parts)
    except Exception:
        return path


def _normalize_short_paths_in_text(message: str) -> str:
    if not message or "~" not in message or ":" not in message:
        return message

    def _replace(match: re.Match) -> str:
        return _to_long_path_if_possible(match.group(0))

    try:
        return _SHORT_PATH_PATTERN.sub(_replace, message)
    except Exception:
        return message


def _translate_message(message: str) -> str:
    if not message:
        return message
    text = _normalize_short_paths_in_text(message)
    for pattern, replacement in _PHRASE_REPLACEMENTS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    for pattern, replacement in _REPLACEMENTS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def translate_log_message(message: str) -> str:
    return _translate_message(str(message or ""))


class LogMessageTranslator(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            translated = _translate_message(message)
            record.msg = translated
            record.args = ()
            record.levelname = _LEVEL_MAP.get(record.levelname, record.levelname)
        except Exception:
            pass
        return True


def _has_translator(filterer: logging.Filterer) -> bool:
    for existing in getattr(filterer, "filters", []):
        if isinstance(existing, LogMessageTranslator):
            return True
    return False


def install_log_message_translator(logger: logging.Logger = None) -> LogMessageTranslator:
    target_logger = logger or logging.getLogger()
    translator = None

    for existing in target_logger.filters:
        if isinstance(existing, LogMessageTranslator):
            translator = existing
            break

    if translator is None:
        translator = LogMessageTranslator()
        target_logger.addFilter(translator)

    for handler in target_logger.handlers:
        if not _has_translator(handler):
            handler.addFilter(translator)

    return translator
