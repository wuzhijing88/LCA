# -*- coding: utf-8 -*-
"""
Template matching worker subprocess.
The worker keeps only a single cached screenshot to avoid repeatedly sending the same frame.
"""

import gc
import logging
import os
import socket
import time
from typing import Any, Dict, Optional, Tuple

import numpy as np
from services.socket_message_utils import (
    read_socket_max_message_bytes,
    recv_message as recv_socket_message,
    send_message as send_socket_message,
)


def _read_socket_max_message_bytes() -> int:
    return read_socket_max_message_bytes(
        env_name="MATCH_SOCKET_MAX_MB",
        default_mb=64,
        min_mb=8,
        max_mb=512,
    )


_MAX_SOCKET_MESSAGE_BYTES = _read_socket_max_message_bytes()


def _setup_worker_logger(process_id: str) -> logging.Logger:
    logger = logging.getLogger("MATCH_WORKER")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - [pid=%(process)d] - [match_worker:%(lineno)d] - %(message)s"
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def _send_message(sock: socket.socket, data: Dict[str, Any]) -> bool:
    return send_socket_message(sock, data)


def _recv_message(sock: socket.socket, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
    return recv_socket_message(
        sock=sock,
        timeout=timeout,
        max_message_bytes=_MAX_SOCKET_MESSAGE_BYTES,
    )


class TemplateMatchWorker:
    def __init__(self, process_id: str):
        self.process_id = process_id
        self.logger = _setup_worker_logger(process_id)
        self.running = True
        self._cached_screenshot: Optional[np.ndarray] = None
        self._cached_screenshot_id: int = 0

    def _clear_cached_screenshot(self) -> None:
        cached = self._cached_screenshot
        self._cached_screenshot = None
        self._cached_screenshot_id = 0
        if cached is not None:
            try:
                del cached
            except Exception:
                pass

    def _resolve_screenshot(self, request: Dict[str, Any]) -> Tuple[Optional[np.ndarray], str]:
        screenshot_id = int(request.get("screenshot_id") or 0)
        screenshot = request.get("screenshot")

        if screenshot is not None:
            if not isinstance(screenshot, np.ndarray):
                return None, "invalid_screenshot_payload"
            if screenshot.size <= 0:
                return None, "empty_screenshot"
            prepared = np.ascontiguousarray(screenshot)
            self._clear_cached_screenshot()
            self._cached_screenshot = prepared
            self._cached_screenshot_id = screenshot_id
            return prepared, ""

        if self._cached_screenshot is None:
            return None, "screenshot_missing"

        if screenshot_id and self._cached_screenshot_id and screenshot_id != self._cached_screenshot_id:
            return None, "screenshot_stale"

        return self._cached_screenshot, ""

    @staticmethod
    def _resolve_template(request: Dict[str, Any]) -> Tuple[Optional[np.ndarray], str]:
        template = request.get("template")
        if not isinstance(template, np.ndarray):
            return None, "invalid_template_payload"
        if template.size <= 0:
            return None, "empty_template"
        return np.ascontiguousarray(template), ""

    @staticmethod
    def _normalize_confidence(raw_value: Any) -> float:
        try:
            value = float(raw_value)
        except Exception:
            value = 0.8
        return max(0.0, min(1.0, value))

    def _match_with_smart(
        self,
        screenshot: np.ndarray,
        template: np.ndarray,
        confidence_threshold: float,
    ) -> Tuple[bool, float, Optional[Tuple[int, int, int, int]]]:
        template_h, template_w = template.shape[:2]
        from utils.resolution_aware_matcher import smart_match_template

        match_result = smart_match_template(
            haystack=screenshot,
            needle=template,
            confidence=confidence_threshold,
        )
        score = float(match_result.get("match_score", 0.0) or 0.0)
        max_loc = match_result.get("match_location_tl")
        actual_w = int(match_result.get("template_w", template_w) or template_w)
        actual_h = int(match_result.get("template_h", template_h) or template_h)

        if (
            isinstance(max_loc, (list, tuple))
            and len(max_loc) == 2
            and score >= confidence_threshold
        ):
            location = (int(max_loc[0]), int(max_loc[1]), actual_w, actual_h)
            return True, score, location
        return False, score, None

    def _handle_match_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        screenshot = None
        template = None
        try:
            screenshot, screenshot_error = self._resolve_screenshot(request)
            if screenshot is None:
                return {
                    "type": "match",
                    "success": False,
                    "error": screenshot_error or "screenshot_unavailable",
                }

            template, template_error = self._resolve_template(request)
            if template is None:
                return {
                    "type": "match",
                    "success": False,
                    "error": template_error or "template_unavailable",
                }

            screenshot_h, screenshot_w = screenshot.shape[:2]
            template_h, template_w = template.shape[:2]
            if screenshot_h < template_h or screenshot_w < template_w:
                return {
                    "type": "match",
                    "success": True,
                    "matched": False,
                    "confidence": 0.0,
                    "location": None,
                }

            confidence_threshold = self._normalize_confidence(request.get("confidence", 0.8))
            matched, confidence, location = self._match_with_smart(
                screenshot=screenshot,
                template=template,
                confidence_threshold=confidence_threshold,
            )

            return {
                "type": "match",
                "success": True,
                "matched": bool(matched),
                "confidence": float(confidence),
                "location": list(location) if location is not None else None,
            }
        except Exception as exc:
            return {
                "type": "match",
                "success": False,
                "error": str(exc),
            }
        finally:
            if template is not None:
                del template
            # screenshot may be the cached frame; do not delete it here.

    @staticmethod
    def _get_process_memory_stats() -> Dict[str, Any]:
        stats: Dict[str, Any] = {"pid": int(os.getpid())}
        try:
            import psutil

            process = psutil.Process(int(os.getpid()))
            mem = process.memory_info()
            stats["rss_mb"] = round(float(mem.rss) / 1024 / 1024, 2)

            private_bytes = None
            try:
                full_mem = process.memory_full_info()
                private_bytes = getattr(full_mem, "private", None)
                if private_bytes is None:
                    private_bytes = getattr(full_mem, "uss", None)
            except Exception:
                private_bytes = None

            if private_bytes is not None:
                stats["private_mb"] = round(float(private_bytes) / 1024 / 1024, 2)
        except Exception:
            pass
        return stats

    def _handle_clear_cache(self) -> Dict[str, Any]:
        self._clear_cached_screenshot()
        try:
            gc.collect()
        except Exception:
            pass
        return {"type": "clear_cache", "success": True}

    def _handle_stats(self) -> Dict[str, Any]:
        has_cached = self._cached_screenshot is not None
        cached_shape = None
        cached_nbytes = 0
        if has_cached:
            try:
                cached_shape = list(self._cached_screenshot.shape)
                cached_nbytes = int(self._cached_screenshot.nbytes)
            except Exception:
                cached_shape = None
                cached_nbytes = 0
        return {
            "type": "stats",
            "success": True,
            "worker": self._get_process_memory_stats(),
            "cached_screenshot": {
                "available": bool(has_cached),
                "shape": cached_shape,
                "bytes": cached_nbytes,
                "id": int(self._cached_screenshot_id or 0),
            },
        }

    def run(self, port: int) -> None:
        conn = None
        try:
            conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            conn.settimeout(10.0)
            conn.connect(("127.0.0.1", int(port)))
            conn.settimeout(None)

            if not _send_message(conn, {"type": "ready", "success": True, "process_id": self.process_id}):
                return

            while self.running:
                request = _recv_message(conn, timeout=30.0)
                if request is None:
                    break

                command = str(request.get("command") or "").strip().upper()
                if command == "MATCH_TEMPLATE":
                    response = self._handle_match_request(request)
                elif command == "CLEAR_CACHE":
                    response = self._handle_clear_cache()
                elif command == "STATS":
                    response = self._handle_stats()
                elif command == "PING":
                    response = {"type": "pong", "success": True, "ts": time.time()}
                elif command == "STOP":
                    self.running = False
                    response = {"type": "stop", "success": True}
                else:
                    response = {"type": "error", "success": False, "error": "unknown_command"}

                if not _send_message(conn, response):
                    break
        except Exception as exc:
            self.logger.error("match worker crashed: %s", exc)
        finally:
            try:
                self._clear_cached_screenshot()
                gc.collect()
            except Exception:
                pass
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


def run_match_worker_standalone(process_id: str, port: int) -> None:
    worker = TemplateMatchWorker(process_id=process_id or "match_worker")
    worker.run(port)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Template match worker")
    parser.add_argument("--match-worker-standalone", action="store_true")
    parser.add_argument("--process-id", type=str, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    run_match_worker_standalone(args.process_id, args.port)
