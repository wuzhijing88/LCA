"""一次性参数截图 worker；仅接收固定协议，不执行用户代码。"""
import json
import hashlib
from multiprocessing import shared_memory
from pathlib import Path
import sys
import tempfile
import time


WORKER_FLAG = "--parameter-capture-worker"
PROTOCOL_VERSION = 1


def run_parameter_capture_worker(request_path, request_digest):
    source = Path(request_path)
    root = source.parent.resolve()
    if root.parent != Path(tempfile.gettempdir()).resolve() or not root.name.startswith("lca-parameter-capture-") or source.name != "request.json":
        raise ValueError("采集请求不在本次独立临时目录中")
    deadline = time.monotonic() + 10
    while not source.is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError("采集请求未就绪")
        time.sleep(0.01)
    if source.stat().st_size > 4096:
        raise ValueError("采集请求超过长度上限")
    with source.open("rb") as incoming:
        raw = incoming.read(4097)
    if not raw or len(raw) > 4096:
        raise ValueError("采集请求为空或超过长度上限")
    if hashlib.sha256(raw).hexdigest() != request_digest:
        raise ValueError("采集请求摘要不符，未开始截图")
    request = json.loads(raw.decode("utf-8"))
    required = {"version", "hwnd", "engine", "width", "height", "identity", "shared_memory", "result_path"}
    if not isinstance(request, dict) or set(request) != required or type(request["version"]) is not int or request["version"] != PROTOCOL_VERSION:
        raise ValueError("采集请求协议无效")
    destination = Path(request["result_path"])
    if destination != root / "result.json":
        raise ValueError("采集结果路径不属于本次请求")
    result = None
    try:
        from threading import Event
        import numpy as np
        from utils.dpi_awareness import enable_process_dpi_awareness
        enable_process_dpi_awareness()
        from ui.panels.parameter_tool_capture import capture_frame, describe_window

        snapshot = describe_window(request["hwnd"])
        if list(snapshot.identity()) != request["identity"] or (snapshot.width, snapshot.height) != (request["width"], request["height"]):
            raise ValueError("采集启动前窗口身份或客户区已改变")
        frame = capture_frame(snapshot.hwnd, request["engine"], Event(), lambda value: None)
        memory = shared_memory.SharedMemory(name=request["shared_memory"])
        try:
            pixels = np.ndarray((snapshot.height, snapshot.width, 3), dtype=np.uint8, buffer=frame.image.constBits(), strides=(frame.image.bytesPerLine(), 3, 1))
            target = np.ndarray((snapshot.height, snapshot.width, 3), dtype=np.uint8, buffer=memory.buf)
            try:
                np.copyto(target, pixels)
            finally:
                del target
                del pixels
        finally:
            memory.close()
        result = {"version": PROTOCOL_VERSION, "ok": True, "identity": list(frame.window.identity())}
    except Exception as error:
        message = str(error)
        if len(message) > 4096:
            message = message[:4096] + "（错误信息过长，已截断）"
        result = {"version": PROTOCOL_VERSION, "ok": False, "message": message}
    with destination.open("x", encoding="utf-8") as output:
        output.write(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    if len(sys.argv) != 6 or sys.argv[1:3] != ["--standalone", "--request"] or sys.argv[4] != "--digest":
        raise ValueError("参数采集 worker 必须使用现行独立进程入口")
    raise SystemExit(run_parameter_capture_worker(sys.argv[3], sys.argv[5]))
