# -*- coding: utf-8 -*-
"""给已有 exe 改名并写入 .ico 图标（导出独立程序用）。"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def apply_exe_icon(exe_path: Path, ico_path: Path) -> None:
    """
    把 ico 写入 exe 的主图标资源。
    在临时副本上修改再替换，避免资源更新会话被批量删除搞坏，
    并降低资源管理器占用文件时的偶发失败。
    """
    from app_core.player.branding import inject_exe_icon

    exe_path = Path(exe_path)
    ico_path = Path(ico_path)
    if not exe_path.is_file():
        raise FileNotFoundError(exe_path)
    if not ico_path.is_file():
        raise FileNotFoundError(ico_path)

    temp_exe = exe_path.with_name(exe_path.name + ".icon_tmp")
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            if temp_exe.exists():
                temp_exe.unlink()
            shutil.copy2(exe_path, temp_exe)
            inject_exe_icon(temp_exe, ico_path)
            # 用替换避免目标文件被短暂锁定时直接写失败
            temp_exe.replace(exe_path)
            return
        except Exception as exc:
            last_error = exc
            logger.debug("写入图标第 %s 次失败: %s", attempt, exc)
            try:
                if temp_exe.exists():
                    temp_exe.unlink()
            except OSError:
                pass
            time.sleep(0.15 * attempt)
    raise OSError(f"写入程序图标失败: {last_error}")


def brand_runtime_exe(
    source_exe: Path,
    target_exe: Path,
    *,
    icon_path: str = "",
    entry_mode: str = "player",
    bind_id: bytes | bytearray | memoryview | None = None,
) -> Path:
    """复制引擎 exe → 产品 exe：图标 + 入口印记（播放器可带 package 绑定）。"""
    from app_core.player.entry_stamp import apply_entry_stamp

    source_exe = Path(source_exe)
    target_exe = Path(target_exe)
    target_exe.parent.mkdir(parents=True, exist_ok=True)
    if target_exe.exists():
        target_exe.unlink()
    shutil.copy2(source_exe, target_exe)
    ico = str(icon_path or "").strip()
    if ico:
        ico_file = Path(ico)
        if not ico_file.is_file():
            raise RuntimeError(f"写入程序图标失败: 找不到图标文件 {ico}")
        try:
            apply_exe_icon(target_exe, ico_file)
        except Exception as exc:
            raise RuntimeError(f"写入程序图标失败: {exc}") from exc
    apply_entry_stamp(target_exe, entry_mode, bind_id=bind_id)
    return target_exe
