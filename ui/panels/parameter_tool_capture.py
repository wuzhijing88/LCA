"""声明式参数工具的窗口快照；严格使用指定句柄和当前截图引擎。"""
from dataclasses import dataclass
import hashlib
import json
from multiprocessing import shared_memory
import os
from pathlib import Path
import subprocess
import tempfile
import time

import psutil
from PySide6.QtGui import QImage
from services.parameter_capture_worker import PROTOCOL_VERSION, WORKER_FLAG


MAX_CAPTURE_PIXELS = 16_000_000
CAPTURE_TIMEOUT = 12.0
CREATE_SUSPENDED = 0x00000004


@dataclass(frozen=True)
class WindowSnapshot:
    hwnd: int
    process_id: int
    thread_id: int
    class_name: str
    title: str
    width: int
    height: int

    def identity(self):
        return self.hwnd, self.process_id, self.thread_id, self.class_name, self.width, self.height


@dataclass(frozen=True)
class CaptureSnapshot:
    window: WindowSnapshot
    image: QImage


def describe_window(hwnd):
    import win32gui
    import win32process

    if isinstance(hwnd, bool) or not isinstance(hwnd, int) or hwnd <= 0 or not win32gui.IsWindow(hwnd):
        raise ValueError("目标窗口句柄无效，请重新选择窗口")
    class_name = win32gui.GetClassName(hwnd)
    if class_name.lower() in {"progman", "workerw", "#32769"}:
        raise ValueError("参数采集只支持明确的应用窗口，不支持桌面")
    if win32gui.IsIconic(hwnd):
        raise ValueError("目标窗口已最小化，请还原后重新采集")
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0 or width * height > MAX_CAPTURE_PIXELS:
        raise ValueError("目标客户区为空或超过 1600 万像素采集上限")
    thread_id, process_id = win32process.GetWindowThreadProcessId(hwnd)
    if not process_id or not thread_id:
        raise ValueError("无法确定目标窗口的进程和线程")
    return WindowSnapshot(hwnd, process_id, thread_id, class_name, win32gui.GetWindowText(hwnd), width, height)


def list_windows(cancelled, progress):
    import win32gui

    windows = []

    def visit(hwnd, _context):
        if cancelled.is_set() or not win32gui.IsWindowVisible(hwnd):
            return
        if len(windows) >= 512:
            raise RuntimeError("可见窗口超过 512 个，请先关闭不需要的窗口")
        try:
            window = describe_window(hwnd)
        except Exception as error:
            windows.append({"hwnd": hwnd, "window": None, "error": f"窗口不可用：{error}"})
        else:
            if window.process_id != os.getpid():
                windows.append({"hwnd": hwnd, "window": window, "error": ""})

    win32gui.EnumWindows(visit, None)
    return windows


def capture_frame(hwnd, engine, cancelled, progress):
    import numpy as np
    from utils.capture import screenshot_helper as screenshots

    window = describe_window(hwnd)
    if cancelled.is_set():
        return None
    if screenshots.is_plugin_screenshot_engine(engine):
        raise RuntimeError("当前插件截图引擎没有独立采集会话接口，工具未启动；不会复用主进程绑定或更换引擎")
    readers = {
        "wgc": screenshots.capture_window_wgc,
        "printwindow": screenshots.capture_window_printwindow,
        "gdi": screenshots.capture_window_gdi,
        "dxgi": screenshots.capture_window_dxgi,
    }
    if engine in readers:
        reader = readers[engine]
    else:
        raise ValueError(f"不支持的截图引擎：{engine}")
    try:
        frame = reader(hwnd, client_area_only=True, timeout=4.0)
        if cancelled.is_set():
            return None
        if frame is None:
            raise RuntimeError(f"当前截图引擎 {engine} 未取得窗口画面，不切换引擎或改抓桌面")
        if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] not in (3, 4):
            raise ValueError("截图没有返回有效的 BGR 客户区图像")
        if frame.shape[:2] != (window.height, window.width):
            raise ValueError("截图尺寸与客户区物理像素不一致，未进行缩放或坐标推测")
        if describe_window(hwnd).identity() != window.identity():
            raise ValueError("采集期间窗口身份或客户区尺寸已改变，请重新采集")
        pixels = np.ascontiguousarray(frame[:, :, :3])
        image = QImage(pixels.data, window.width, window.height, pixels.strides[0], QImage.Format.Format_BGR888).copy()
        if image.isNull():
            raise RuntimeError("无法创建客户区采集图像")
        return CaptureSnapshot(window, image)
    finally:
        screenshots.cleanup_screenshot_engine_runtime(engine=engine, hwnd=hwnd)


def _worker_command(request_path, request_digest):
    from app_core.runtime.worker_entry import build_worker_launch_command
    return build_worker_launch_command(WORKER_FLAG, "services.parameter_capture_worker", "--standalone", ["--request", str(request_path), "--digest", request_digest])


def _resume_worker(process):
    try:
        psutil.Process(process.pid).resume()
    except Exception as error:
        raise RuntimeError(f"参数采集进程无法开始执行：{error}") from error


def _stop_worker(process, job, assigned):
    from services.worker_process_cleanup import unregister_worker_process

    try:
        if assigned:
            job.terminate_and_wait(timeout=3)
        elif process.poll() is None:
            process.terminate()
    finally:
        try:
            job.close()
        finally:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=3)
            finally:
                if process.poll() is not None:
                    unregister_worker_process(process)
                if process.stdin is not None and not process.stdin.closed:
                    process.stdin.close()
                if process.poll() is not None:
                    process._handle.Close()


def capture_client(hwnd, cancelled, progress):
    from app_core.runtime.worker_entry import build_worker_process_env
    from app_core.script_process_job import ProcessJob
    from services.worker_process_cleanup import register_worker_process
    from utils.capture.screenshot_helper import get_screenshot_engine, is_plugin_screenshot_engine

    snapshot = describe_window(hwnd)
    if cancelled.is_set():
        return None
    engine = get_screenshot_engine()
    if is_plugin_screenshot_engine(engine):
        raise RuntimeError("当前插件截图引擎没有独立采集会话接口，工具未启动；不会共享主进程绑定或更换引擎")
    memory = shared_memory.SharedMemory(create=True, size=snapshot.width * snapshot.height * 3)
    try:
        with tempfile.TemporaryDirectory(prefix="lca-parameter-capture-") as directory:
            destination = Path(directory) / "result.json"
            source = Path(directory) / "request.json"
            request = {"version": PROTOCOL_VERSION, "hwnd": hwnd, "engine": engine, "width": snapshot.width, "height": snapshot.height,
                       "identity": list(snapshot.identity()), "shared_memory": memory.name, "result_path": str(destination)}
            payload = json.dumps(request, ensure_ascii=False).encode("utf-8")
            if len(payload) > 4096:
                raise ValueError("采集请求超过长度上限")
            job = ProcessJob()
            process = None
            assigned = False
            try:
                process = subprocess.Popen(_worker_command(source, hashlib.sha256(payload).hexdigest()), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           env=build_worker_process_env(include_plugin_attach=False), creationflags=subprocess.CREATE_NO_WINDOW | CREATE_SUSPENDED)
                if process.poll() is not None:
                    raise RuntimeError("参数采集进程未能启动")
                job.assign(process)
                assigned = True
                register_worker_process(process, WORKER_FLAG)
                pending = Path(directory) / "pending.json"
                pending.write_bytes(payload)
                pending.replace(source)
                _resume_worker(process)
                deadline = time.monotonic() + CAPTURE_TIMEOUT
                while process.poll() is None:
                    if cancelled.wait(0.02):
                        return None
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"客户区截图超过 {CAPTURE_TIMEOUT:g} 秒，采集进程将完整关闭；未切换截图引擎")
                if cancelled.is_set():
                    return None
                if not destination.is_file() or destination.stat().st_size > 32768:
                    raise RuntimeError("采集进程未返回有效结果，失败原因未知")
                with destination.open("rb") as incoming:
                    reply = incoming.read(32769)
                if len(reply) > 32768:
                    raise ValueError("采集进程结果超过长度上限")
                result = json.loads(reply.decode("utf-8"))
                if not isinstance(result, dict) or type(result.get("version")) is not int or result["version"] != PROTOCOL_VERSION or type(result.get("ok")) is not bool:
                    raise ValueError("采集进程返回了非法协议")
                if not result["ok"]:
                    if set(result) != {"version", "ok", "message"} or not isinstance(result["message"], str):
                        raise ValueError("采集进程错误结果无效")
                    raise RuntimeError("窗口采集失败：" + result["message"])
                if set(result) != {"version", "ok", "identity"} or result["identity"] != list(snapshot.identity()) or process.returncode != 0:
                    raise ValueError("采集结果身份或进程状态无效")
                if describe_window(hwnd).identity() != snapshot.identity():
                    raise ValueError("采集期间窗口身份或客户区已改变")
                image = QImage(memory.buf, snapshot.width, snapshot.height, snapshot.width * 3, QImage.Format.Format_BGR888).copy()
                if image.isNull():
                    raise RuntimeError("无法创建采集图像")
                return CaptureSnapshot(snapshot, image)
            finally:
                if process is None:
                    job.close()
                else:
                    _stop_worker(process, job, assigned)
    finally:
        memory.close()
        memory.unlink()
