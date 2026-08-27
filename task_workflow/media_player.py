# -*- coding: utf-8 -*-
"""Play audio and open media files without extra dependencies."""

from __future__ import annotations

import logging
import os
import time
from typing import Callable, Optional

from utils.app_paths import get_app_root, get_images_dir, get_sounds_dir

logger = logging.getLogger(__name__)

_MCI_ALIAS = "lca_media"


def resolve_media_path(raw_path: str) -> Optional[str]:
    text = str(raw_path or "").strip()
    if not text or text.startswith("memory://"):
        return None

    candidates = []
    if os.path.isabs(text):
        candidates.append(text)
    else:
        normalized = text.replace("\\", "/")
        basename = os.path.basename(normalized)
        candidates.append(os.path.abspath(text))
        candidates.append(os.path.join(get_app_root(), text))
        if normalized.lower().startswith("sounds/"):
            suffix = normalized[7:].lstrip("/")
            if suffix:
                candidates.append(os.path.join(get_sounds_dir(), suffix))
                candidates.append(os.path.join(get_app_root(), "sounds", suffix))
        if normalized.lower().startswith("images/"):
            suffix = normalized[7:].lstrip("/")
            if suffix:
                candidates.append(os.path.join(get_images_dir(), suffix))
        if basename:
            candidates.append(os.path.join(get_images_dir(), basename))
            candidates.append(os.path.join(get_sounds_dir(), basename))
            candidates.append(os.path.join(get_app_root(), "sounds", basename))

    seen = set()
    for item in candidates:
        normalized = os.path.normpath(item) if item else ""
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if os.path.exists(normalized):
            return normalized
    return None


def play_audio(
    path: str,
    *,
    wait: bool = True,
    stop_checker: Optional[Callable[[], bool]] = None,
) -> str:
    resolved = resolve_media_path(path) or str(path or "").strip()
    if not resolved or not os.path.exists(resolved):
        raise FileNotFoundError(f"音频文件不存在: {path}")
    stop_audio()
    ext = os.path.splitext(resolved)[1].lower()
    if ext == ".wav" and not (wait and stop_checker):
        _play_wav(resolved, wait=wait)
        return resolved
    _play_mci(resolved, wait=wait, stop_checker=stop_checker)
    return resolved


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
