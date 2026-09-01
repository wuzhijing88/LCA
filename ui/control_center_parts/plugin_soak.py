from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from utils.capture.engine_ids import is_plugin_screenshot_engine
from utils.plugin.capture import capture_window_plugin, is_plugin_capture_available
from utils.plugin.runtime import find_plugin_dir, is_plugin_runtime_available

logger = logging.getLogger("plugin_soak")

PLUGIN_ENGINES = ("gdi2", "normal")


class _Target(QWidget):
    def __init__(self, index: int):
        super().__init__()
        self.setWindowTitle(f"LCA插件实测窗 {index + 1}")
        self.resize(420, 260)
        self.move(80 + index * 48, 80 + index * 48)
        layout = QVBoxLayout(self)
        banner = QLabel(f"插件实测 {index + 1}\nPLUGIN SAMPLE 测试 123")
        banner.setStyleSheet("font-size: 20px; background: #3d1f4e; color: #f4f7fb; padding: 16px;")
        layout.addWidget(banner)


def _ensure_plugin_dir() -> str:
    found = find_plugin_dir()
    if found is not None:
        os.environ["LCA_PLUGIN_DIR"] = str(found)
        return str(found)
    for candidate in (
        Path(os.environ.get("LCA_PLUGIN_DIR") or ""),
        Path(__file__).resolve().parents[2] / "tools" / "plugin",
    ):
        if candidate.is_dir():
            os.environ["LCA_PLUGIN_DIR"] = str(candidate)
            return str(candidate)
    return ""


def _capture_matrix(hwnds: List[int]) -> Dict[str, Any]:
    result: Dict[str, Any] = {"engines": {}, "overlap_ok": True}
    for engine in PLUGIN_ENGINES:
        frames = []
        for hwnd in hwnds:
            frame = capture_window_plugin(hwnd, engine, client_area_only=True, timeout=6.0)
            shape = None if frame is None else tuple(int(x) for x in frame.shape)
            frames.append({"hwnd": hwnd, "shape": shape, "ok": frame is not None and frame.size > 0})
        result["engines"][engine] = frames
    return result


def _run_control_center_plugin_runtime(hwnds: List[int], titles: List[str]) -> Dict[str, Any]:
    from app_core.runtime.execution_coordinator import (
        ExecutionSource,
        create_coordinated_workflow_runtime,
    )
    from task_workflow.thread_start import THREAD_START_TASK_TYPE
    from ui.control_center_parts.control_center_policy import resolve_control_center_screenshot_engine

    class _Parent:
        config = {"screenshot_engine": "gdi2", "execution_mode": "background_sendmessage"}

    class _Runner:
        _runtime_config = {}
        parent_window = _Parent()

        def _get_parent_config(self):
            return self.parent_window.config

    engine = resolve_control_center_screenshot_engine(_Runner())
    cards = {
        1: {"id": 1, "task_type": THREAD_START_TASK_TYPE, "parameters": {}, "custom_name": "起点"},
        2: {
            "id": 2,
            "task_type": "OCR文字识别",
            "parameters": {
                "region_mode": "指定区域",
                "region_x": 0,
                "region_y": 0,
                "region_width": 360,
                "region_height": 180,
                "on_success": "执行下一步",
                "on_failure": "执行下一步",
            },
            "custom_name": "插件OCR",
        },
        3: {
            "id": 3,
            "task_type": "延迟",
            "parameters": {"delay_mode": "固定延迟", "delay_seconds": 0.2, "on_success": "执行下一步"},
            "custom_name": "延迟",
        },
    }
    connections = [
        {"start_card_id": 1, "end_card_id": 2, "type": "sequential"},
        {"start_card_id": 2, "end_card_id": 3, "type": "sequential"},
        {"start_card_id": 3, "end_card_id": 2, "type": "sequential"},
    ]
    finished: List[Dict[str, Any]] = []
    cards_executed = 0

    def _on_card(_card_id):
        nonlocal cards_executed
        cards_executed += 1

    def _on_finished(success, message):
        finished.append({"success": bool(success), "message": str(message or "")})

    runtimes = []
    for index, hwnd in enumerate(hwnds):
        executor, _thread = create_coordinated_workflow_runtime(
            source=ExecutionSource.CONTROL_CENTER,
            cards_data=cards,
            connections_data=connections,
            execution_mode="background_sendmessage",
            screenshot_engine=engine,
            images_dir=None,
            workflow_id=f"plugin_soak_{index + 1}",
            start_card_ids=[1],
            target_window_title=titles[index],
            target_hwnd=hwnd,
            bound_windows=[
                {"hwnd": item, "title": titles[i], "bind_id": f"plugin-{i + 1}", "enabled": True}
                for i, item in enumerate(hwnds)
            ],
        )
        if hasattr(executor, "card_executing"):
            executor.card_executing.connect(_on_card)
        if hasattr(executor, "execution_finished"):
            executor.execution_finished.connect(_on_finished)
        executor.run()
        runtimes.append(executor)

    deadline = time.time() + 12
    app = QApplication.instance()
    while time.time() < deadline and len(finished) < len(hwnds):
        if app is not None:
            app.processEvents()
        time.sleep(0.05)
    for executor in runtimes:
        try:
            executor.request_stop(force=True)
        except Exception:
            pass
    stop_deadline = time.time() + 8
    while time.time() < stop_deadline and len(finished) < len(hwnds):
        if app is not None:
            app.processEvents()
        time.sleep(0.05)
    return {
        "engine": engine,
        "plugin_engine": is_plugin_screenshot_engine(engine),
        "cards_executed": cards_executed,
        "finished": finished,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    plugin_dir = _ensure_plugin_dir()
    print(f"PLUGIN_DIR={plugin_dir or 'missing'}")
    print(f"PLUGIN_AVAILABLE={is_plugin_runtime_available()} CAPTURE={is_plugin_capture_available()}")
    if not is_plugin_capture_available():
        print("PLUGIN_SOAK=skipped_no_runtime")
        return 3

    app = QApplication.instance() or QApplication(sys.argv)
    widgets = [_Target(index) for index in range(3)]
    for widget in widgets:
        widget.show()
    app.processEvents()
    hwnds = [int(widget.winId()) for widget in widgets]
    titles = [widget.windowTitle() for widget in widgets]
    print(f"HWNDS={hwnds}")

    captures = _capture_matrix(hwnds)
    for engine, frames in captures["engines"].items():
        ok = sum(1 for item in frames if item["ok"])
        print(f"CAPTURE {engine}: {ok}/{len(frames)} {frames}")

    runtime = _run_control_center_plugin_runtime(hwnds, titles)
    print(
        f"RUNTIME engine={runtime['engine']} plugin={runtime['plugin_engine']} "
        f"cards={runtime['cards_executed']} finished={len(runtime['finished'])}"
    )
    for item in runtime["finished"]:
        print(f"  finish success={item['success']} {item['message']}")

    for widget in widgets:
        widget.close()

    capture_ok = any(item["ok"] for frames in captures["engines"].values() for item in frames)
    runtime_ok = runtime["plugin_engine"] and runtime["cards_executed"] > 0
    if capture_ok and runtime_ok:
        print("PLUGIN_SOAK=ok")
        return 0
    print("PLUGIN_SOAK=failed")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
