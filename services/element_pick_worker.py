"""元素读取独立进程；UIAutomation 阻塞时由宿主完整终止进程组。"""
from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

WORKER_FLAG = "--element-pick-worker"
PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 16384


@dataclass(frozen=True)
class ElementInfo:
    name: str
    automation_id: str
    class_name: str
    control_type: str
    bounding_rect: tuple


def decode_message(data):
    if not data or len(data) > MAX_MESSAGE_BYTES:
        raise ValueError("元素拾取消息为空或超过长度上限")
    message = json.loads(data.decode("utf-8"))
    if not isinstance(message, dict) or type(message.get("version")) is not int or message["version"] != PROTOCOL_VERSION:
        raise ValueError("元素拾取消息协议无效")
    return message


def write_message(message):
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("元素拾取消息超过长度上限")
    sys.stdout.buffer.write(payload + b"\n")
    sys.stdout.buffer.flush()


def run_element_pick_worker(request_path, request_digest):
    request = Path(request_path)
    directory = request.parent.resolve()
    if directory.parent != Path(tempfile.gettempdir()).resolve() or not directory.name.startswith("lca-element-pick-") or request.name != "request.json":
        raise ValueError("元素拾取请求不在本次独立临时目录中")
    raw = request.read_bytes()
    if len(raw) > MAX_MESSAGE_BYTES or hashlib.sha256(raw).hexdigest() != request_digest:
        raise ValueError("元素拾取请求摘要无效")
    message = decode_message(raw)
    if set(message) != {"version"}:
        raise ValueError("元素拾取请求字段无效")
    try:
        # UIAutomation 在独立的 MTA 进程中运行，界面线程不执行原生元素读取。
        sys.coinit_flags = 0
        from utils.dpi_awareness import enable_process_dpi_awareness
        enable_process_dpi_awareness()
        from utils.input.uiautomation_runtime import import_uiautomation
        auto = import_uiautomation()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        sequence = 0
        with auto.UIAutomationInitializerInThread():
            while True:
                if user32.GetAsyncKeyState(0x1B) & 0x8000:
                    write_message({"version": PROTOCOL_VERSION, "kind": "cancelled"})
                    return 0
                point = wintypes.POINT()
                if not user32.GetCursorPos(ctypes.byref(point)):
                    raise ctypes.WinError(ctypes.get_last_error())
                element = auto.ControlFromPoint(point.x, point.y)
                info = None
                if element is not None:
                    rect = element.BoundingRectangle
                    if rect is not None and rect.width() > 0 and rect.height() > 0:
                        info = {"name": element.Name, "automation_id": element.AutomationId,
                                "class_name": element.ClassName, "control_type": element.ControlTypeName,
                                "bounding_rect": [rect.left, rect.top, rect.width(), rect.height()]}
                sequence += 1
                confirmed = (directory / "confirm").exists() or bool(user32.GetAsyncKeyState(0x02) & 0x8000)
                if confirmed and info is not None:
                    write_message({"version": PROTOCOL_VERSION, "kind": "selected", "info": info})
                    return 0
                write_message({"version": PROTOCOL_VERSION, "kind": "progress", "sequence": sequence, "info": info})
                time.sleep(0.04)
    except Exception as error:
        write_message({"version": PROTOCOL_VERSION, "kind": "failed", "message": str(error)[:2048]})
        return 1


if __name__ == "__main__":
    if len(sys.argv) != 6 or sys.argv[1:3] != ["--standalone", "--request"] or sys.argv[4] != "--digest":
        raise ValueError("元素拾取进程必须使用现行独立入口")
    raise SystemExit(run_element_pick_worker(sys.argv[3], sys.argv[5]))
