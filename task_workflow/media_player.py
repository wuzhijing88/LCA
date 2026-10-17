# -*- coding: utf-8 -*-
"""音频播放与所属脚本的关闭管理。"""

from __future__ import annotations

import itertools
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Optional

_OWNER = ContextVar("lca_audio_owner", default=None)
_LOCK = threading.RLock()
_ALIASES = itertools.count(1)
_active = None


@contextmanager
def audio_owner(owner):
    token = _OWNER.set(owner)
    try:
        yield
    finally:
        _OWNER.reset(token)


def resolve_media_path(raw_path: str) -> Optional[str]:
    from task_workflow.resource_path import unwrap_resource_path
    from task_workflow.script_resources import resolve_resource_path

    text = unwrap_resource_path(raw_path) or ""
    if not text:
        return None
    located = resolve_resource_path(text, enforce_jail=False)
    if located and str(located).startswith("memory://"):
        return located
    if located and os.path.isfile(located):
        return located
    return None


def play_audio(
    path: str,
    *,
    wait: bool = True,
    stop_checker: Optional[Callable[[], bool]] = None,
) -> str:
    from task_workflow.script_resources import read_resource_bytes

    resolved = resolve_media_path(path)
    if not resolved:
        raise FileNotFoundError(f"音频文件不存在: {path}")
    temporary = ""
    actual = resolved
    if resolved.startswith("memory://"):
        data = read_resource_bytes(resolved)
        if not data:
            raise FileNotFoundError(f"音频文件不存在: {path}")
        suffix = os.path.splitext(resolved)[1]
        with tempfile.NamedTemporaryFile(prefix="lca_audio_", suffix=suffix, delete=False) as stream:
            temporary = stream.name
            try:
                stream.write(data)
            except Exception:
                stream.close()
                os.unlink(temporary)
                raise
        actual = temporary
    try:
        _play_mci(actual, wait=wait, stop_checker=stop_checker, temporary=temporary)
    except Exception:
        with _LOCK:
            owned = _active is not None and _active["temporary"] == temporary and bool(temporary)
        if temporary and not owned and os.path.exists(temporary):
            os.unlink(temporary)
        raise
    return resolved


def stop_audio() -> None:
    global _active
    with _LOCK:
        playback = _active
        if playback is None:
            return
        errors = []
        if not playback["closed"]:
            try:
                _mci_send(f"stop {playback['alias']}")
            except Exception as exc:
                errors.append(str(exc))
            try:
                _mci_send(f"close {playback['alias']}")
                playback["closed"] = True
            except Exception as exc:
                errors.append(str(exc))
        if playback["closed"]:
            try:
                if playback["temporary"]:
                    os.unlink(playback["temporary"])
                    playback["temporary"] = ""
            except Exception as exc:
                errors.append(str(exc))
            if not playback["temporary"]:
                _active = None
        if errors:
            raise ValueError("停止音频失败：" + "；".join(errors))


def stop_owned_audio(owner) -> None:
    with _LOCK:
        if _active is not None and _active["owner"] is owner:
            stop_audio()


def _mci_send(command: str) -> str:
    import ctypes

    buffer = ctypes.create_unicode_buffer(512)
    err = ctypes.windll.winmm.mciSendStringW(command, buffer, 511, 0)
    if err:
        err_buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.winmm.mciGetErrorStringW(err, err_buf, 511)
        raise RuntimeError(err_buf.value or f"音频接口错误 {err}")
    return buffer.value


def _play_mci(path: str, *, wait: bool, stop_checker, temporary: str = "") -> None:
    global _active
    if '"' in path:
        raise ValueError("音频路径不能含双引号")
    playback = {"alias": f"lca_media_{next(_ALIASES)}", "owner": _OWNER.get(),
                "temporary": temporary, "closed": False}
    with _LOCK:
        stop_audio()
        _mci_send(f'open "{path}" alias {playback["alias"]}')
        _active = playback
        try:
            _mci_send(f"play {playback['alias']}")
        except Exception:
            stop_audio()
            raise
    if not wait:
        return
    try:
        while True:
            if stop_checker and stop_checker():
                break
            with _LOCK:
                if _active is not playback:
                    break
                mode = _mci_send(f"status {playback['alias']} mode").strip().lower()
            if mode != "playing":
                break
            time.sleep(0.05)
    finally:
        with _LOCK:
            if _active is playback:
                stop_audio()
