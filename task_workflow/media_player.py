# -*- coding: utf-8 -*-
"""Play audio and open media files without extra dependencies."""

from __future__ import annotations

import logging
import os
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_MCI_ALIAS = "lca_media"


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

    resolved = resolve_media_path(path) or str(path or "").strip()
    if resolved and os.path.isfile(resolved):
        stop_audio()
        ext = os.path.splitext(resolved)[1].lower()
        if ext == ".wav" and not (wait and stop_checker):
            _play_wav(resolved, wait=wait)
            return resolved
        _play_mci(resolved, wait=wait, stop_checker=stop_checker)
        return resolved
    data = read_resource_bytes(path)
    if not data:
        raise FileNotFoundError(f"音频文件不存在: {path}")
    stop_audio()
    _play_wav_bytes(data, wait=wait)
    return resolved or str(path or "")


def stop_audio() -> None:
    try:
        _mci_send(f"stop {_MCI_ALIAS}")
    except Exception:
        pass
    try:
        _mci_send(f"close {_MCI_ALIAS}")
    except Exception:
        pass
    try:
        import winsound

        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        pass


def _play_wav(path: str, *, wait: bool) -> None:
    import winsound

    flags = winsound.SND_FILENAME | winsound.SND_NODEFAULT
    if not wait:
        flags |= winsound.SND_ASYNC
    winsound.PlaySound(path, flags)


def _play_wav_bytes(data: bytes, *, wait: bool) -> None:
    import winsound

    flags = winsound.SND_MEMORY | winsound.SND_NODEFAULT
    if not wait:
        flags |= winsound.SND_ASYNC
    winsound.PlaySound(data, flags)


def _mci_send(command: str) -> str:
    import ctypes

    buffer = ctypes.create_unicode_buffer(512)
    err = ctypes.windll.winmm.mciSendStringW(command, buffer, 511, 0)
    if err:
        err_buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.winmm.mciGetErrorStringW(err, err_buf, 511)
        raise RuntimeError(err_buf.value or f"MCI error {err}")
    return buffer.value


def _play_mci(
    path: str,
    *,
    wait: bool,
    stop_checker: Optional[Callable[[], bool]],
) -> None:
    safe = path.replace('"', "")
    try:
        _mci_send(f"close {_MCI_ALIAS}")
    except Exception:
        pass
    _mci_send(f'open "{safe}" alias {_MCI_ALIAS}')
    try:
        if wait:
            if stop_checker:
                _mci_send(f"play {_MCI_ALIAS}")
                while True:
                    if stop_checker():
                        try:
                            _mci_send(f"stop {_MCI_ALIAS}")
                        except Exception:
                            pass
                        break
                    mode = (_mci_send(f"status {_MCI_ALIAS} mode") or "").strip().lower()
                    if mode != "playing":
                        break
                    time.sleep(0.1)
            else:
                _mci_send(f"play {_MCI_ALIAS} wait")
        else:
            _mci_send(f"play {_MCI_ALIAS}")
            return
    finally:
        if wait:
            try:
                _mci_send(f"close {_MCI_ALIAS}")
            except Exception:
                pass
