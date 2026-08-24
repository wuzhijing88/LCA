#!/usr/bin/env python
"""End-to-end smoke test for authenticated safe workflow IPC."""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.socket_message_utils import recv_message, send_message


def main() -> int:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(10.0)
    token = secrets.token_hex(32)
    env = os.environ.copy()
    env["LCA_WORKFLOW_AUTH_TOKEN"] = token
    command = [
        sys.executable,
        "-m",
        "task_workflow.process_worker",
        "--workflow-worker-standalone",
        "--port",
        str(server.getsockname()[1]),
    ]
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    connection = None
    try:
        connection, _ = server.accept()
        ready = recv_message(connection, timeout=10.0)
        if not isinstance(ready, dict) or ready.get("type") != "ready":
            raise RuntimeError(f"invalid ready message: {ready}")
        if not secrets.compare_digest(str(ready.get("auth_token") or ""), token):
            raise RuntimeError("workflow worker authentication failed")
        payload = {
            "payload_version": 2,
            "cards_data": {},
            "connections_data": [],
            "session_mode": "single",
            "execution_mode": "foreground",
            "screenshot_engine": "wgc",
            "workflow_id": "source-smoke",
            "start_card_id": None,
        }
        if not send_message(connection, {"command": "init", "payload": payload}):
            raise RuntimeError("failed to send init")
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            message = recv_message(connection, timeout=1.0)
            if not isinstance(message, dict):
                continue
            if message.get("type") == "signal" and message.get("name") == "execution_finished":
                print("source workflow worker safe IPC verified")
                return 0
        raise TimeoutError("workflow worker did not emit execution_finished")
    finally:
        if connection is not None:
            connection.close()
        server.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
