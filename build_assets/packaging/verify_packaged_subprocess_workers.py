#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import cv2
import json
import numpy as np
import socket
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from build_assets.packaging.verify_worker_socket_utils import (
        recv_verify_message as _recv_message,
        send_verify_message as _send_message,
    )
except Exception:
    from verify_worker_socket_utils import (
        recv_verify_message as _recv_message,
        send_verify_message as _send_message,
    )


def _validate_ping_response(worker_name: str, response: dict) -> tuple[bool, str]:
    msg_type = str(response.get("type") or "").strip().lower()
    success = bool(response.get("success", True))

    if worker_name in {"ocr", "match"}:
        if msg_type != "pong":
            return False, f"invalid_ping_response:{response}"
        if worker_name == "match" and not success:
            return False, f"invalid_ping_response:{response}"
        return True, ""

    return False, f"unknown_worker:{worker_name}"


def _build_ocr_inference_smoke_request(request_id: str, window_hwnd: int) -> dict:
    image = np.full((96, 320, 3), 255, dtype=np.uint8)
    cv2.putText(
        image,
        "OCR 123",
        (20, 68),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.8,
        (0, 0, 0),
        3,
        cv2.LINE_AA,
    )
    return {
        "request_id": request_id,
        "window_hwnd": window_hwnd,
        "window_title": "packaged-ocr-smoke",
        "use_shared_memory": False,
        "image": image.tobytes(),
        "image_shape": image.shape,
        "image_dtype": str(image.dtype),
        "confidence": 0.1,
        "timestamp": time.time(),
    }


def _validate_ocr_inference_response(
    response: dict,
    request_id: str,
    window_hwnd: int,
) -> tuple[bool, str]:
    if not isinstance(response, dict):
        return False, f"invalid_ocr_response:{response}"
    if response.get("request_id") != request_id:
        return False, f"mismatch_ocr_request_id:{response}"
    if int(response.get("window_hwnd") or 0) != int(window_hwnd):
        return False, f"mismatch_ocr_window:{response}"
    if not bool(response.get("success", False)):
        return False, f"ocr_inference_failed:{response}"
    results = response.get("results")
    if not isinstance(results, list) or not results:
        return False, f"ocr_inference_empty:{response}"
    if not any(str(item.get("text") or "").strip() for item in results if isinstance(item, dict)):
        return False, f"ocr_inference_has_no_text:{response}"
    return True, ""


def _recv_message_with_timeout(conn: socket.socket, timeout_sec: float) -> dict:
    return _recv_message(conn, float(timeout_sec))


def _run_worker_smoke(exe_path: Path, worker_name: str, flag: str, timeout_sec: float) -> tuple[bool, str, bool]:
    server = None
    conn = None
    proc = None
    process_id = f"smoke_{worker_name}_{int(time.time())}"
    uac_blocked = False

    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = int(server.getsockname()[1])

        cmd = [
            str(exe_path),
            flag,
            "--process-id",
            process_id,
            "--port",
            str(port),
        ]

        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
        except OSError as exc:
            if int(getattr(exc, "winerror", 0) or 0) == 740:
                return False, "uac_elevation_required", True
            raise

        server.settimeout(timeout_sec)
        conn, _ = server.accept()

        ready = _recv_message_with_timeout(conn, timeout_sec)
        ready_type = str(ready.get("type") or "").strip().lower()
        if ready_type == "error":
            return False, f"worker_init_error:{ready}", False
        if ready_type != "ready":
            return False, f"invalid_ready:{ready}", False

        ready_pid = str(ready.get("process_id") or "")
        if ready_pid and ready_pid != process_id:
            return False, f"mismatch_process_id:{ready}", False

        _send_message(conn, {"command": "PING"})
        pong = _recv_message_with_timeout(conn, timeout_sec)
        ok, reason = _validate_ping_response(worker_name, pong)
        if not ok:
            return False, reason, False

        if worker_name == "ocr":
            inference_request_id = f"{process_id}_inference"
            inference_hwnd = 987654
            _send_message(
                conn,
                _build_ocr_inference_smoke_request(inference_request_id, inference_hwnd),
            )
            inference_response = _recv_message_with_timeout(conn, timeout_sec)
            ok, reason = _validate_ocr_inference_response(
                inference_response,
                inference_request_id,
                inference_hwnd,
            )
            if not ok:
                return False, reason, False

        try:
            _send_message(conn, {"command": "STOP"})
            _recv_message_with_timeout(conn, 2.0)
        except Exception:
            pass

        return True, "", False
    except Exception as exc:
        return False, f"{type(exc).__name__}:{exc}", uac_blocked
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if server is not None:
            try:
                server.close()
            except Exception:
                pass
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


def _build_workflow_smoke_payload() -> dict:
    return {
        "cards_data": {},
        "connections_data": [],
        "execution_mode": "foreground",
        "images_dir": None,
        "workflow_id": "packaged_smoke_workflow",
        "workflow_filepath": None,
        "session_mode": "single",
        "target_window_title": None,
        "target_hwnd": None,
        "start_card_id": None,
    }


def _run_workflow_worker_smoke(exe_path: Path, timeout_sec: float) -> tuple[bool, str, bool]:
    server = None
    conn = None
    proc = None

    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = int(server.getsockname()[1])

        cmd = [
            str(exe_path),
            "--workflow-worker",
            "--port",
            str(port),
        ]

        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
        except OSError as exc:
            if int(getattr(exc, "winerror", 0) or 0) == 740:
                return False, "uac_elevation_required", True
            raise

        server.settimeout(timeout_sec)
        conn, _ = server.accept()

        ready = _recv_message_with_timeout(conn, timeout_sec)
        ready_type = str((ready or {}).get("type") or "").strip().lower()
        if ready_type == "error":
            return False, f"worker_init_error:{ready}", False
        if ready_type != "ready":
            return False, f"invalid_ready:{ready}", False

        _send_message(
            conn,
            {
                "command": "init",
                "payload": _build_workflow_smoke_payload(),
            },
        )
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            response = _recv_message_with_timeout(conn, max(0.1, deadline - time.monotonic()))
            if not isinstance(response, dict):
                return False, f"invalid_response:{response}", False

            response_type = str(response.get("type") or "").strip().lower()
            if response_type == "runtime_variables":
                continue
            if response_type != "signal":
                return False, f"invalid_response:{response}", False

            signal_name = str(response.get("name") or "").strip().lower()
            if signal_name != "execution_finished":
                continue

            args = response.get("args") or []
            if not isinstance(args, list) or len(args) < 2:
                return False, f"invalid_execution_finished:{response}", False
            return True, "", False

        return False, "missing_execution_finished", False
    except Exception as exc:
        return False, f"{type(exc).__name__}:{exc}", False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if server is not None:
            try:
                server.close()
            except Exception:
                pass
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


def _verify_build_modules(build_dir: Path) -> tuple[bool, list[str]]:
    required = [
        "module.services.multiprocess_ocr_pool.c",
        "module.services.multiprocess_ocr_worker.c",
        "module.services.rapidocr_ocr_service.c",
        "module.services.multiprocess_match_worker.c",
        "module.services.screenshot_pool.c",
        "module.task_workflow.process_worker.c",
        "module.utils.dxgi_capture.c",
        "module.dxcam.c",
    ]
    missing = [name for name in required if not (build_dir / name).exists()]
    return (len(missing) == 0), missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify packaged subprocess workers")
    parser.add_argument("--exe", required=True, help="Path to packaged main.exe")
    parser.add_argument("--build-dir", default="", help="Optional Nuitka main.build path")
    parser.add_argument("--timeout", type=float, default=18.0)
    args = parser.parse_args()

    exe_path = Path(args.exe).resolve()
    if not exe_path.exists():
        print(f"ERROR: exe_not_found: {exe_path}")
        return 2

    had_uac_block = False
    failures = []
    workers = [
        ("ocr", lambda: _run_worker_smoke(exe_path, "ocr", "--ocr-worker", timeout_sec=float(args.timeout))),
        ("match", lambda: _run_worker_smoke(exe_path, "match", "--match-worker", timeout_sec=float(args.timeout))),
        ("workflow", lambda: _run_workflow_worker_smoke(exe_path, timeout_sec=float(args.timeout))),
    ]

    for name, runner in workers:
        ok, reason, uac_blocked = runner()
        if uac_blocked:
            had_uac_block = True
            print(f"WARN: {name}: uac_elevation_required")
            continue
        if ok:
            print(f"OK: {name}: smoke_passed")
        else:
            failures.append((name, reason))
            print(f"ERROR: {name}: {reason}")

    if failures:
        return 1

    if had_uac_block:
        build_dir = Path(args.build_dir).resolve() if args.build_dir else None
        if build_dir is None or not build_dir.exists():
            print("ERROR: uac_blocked_and_missing_build_dir")
            return 3
        ok, missing = _verify_build_modules(build_dir)
        if not ok:
            print(f"ERROR: build_module_check_failed: missing={missing}")
            return 4
        print("WARN: uac_blocked_smoke, build_module_check_passed")
        return 0

    print("OK: ocr_match_workflow_subprocess_workers_smoke_passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
