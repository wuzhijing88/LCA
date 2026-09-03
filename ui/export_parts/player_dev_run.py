from __future__ import annotations

import copy
import os
from typing import Any, Mapping, Optional

from app_core.player.package import (
    PLAYER_PACKAGE_SCHEMA_VERSION,
    PlayerPackage,
    normalize_player_manifest,
    normalize_player_ui,
    resolve_player_theme,
)
from utils.app_paths import get_app_root, get_images_dir, get_sounds_dir, get_user_data_dir


def rewrite_ui_assets_to_local(ui: Mapping[str, Any], asset_map: Mapping[str, str]) -> dict:
    """把设计器相对资源改成本地绝对路径，供开发态运行窗直接读盘。"""
    payload = copy.deepcopy(dict(ui or {}))
    mapping = {
        str(key).replace("\\", "/"): str(value)
        for key, value in dict(asset_map or {}).items()
        if str(key).strip() and str(value).strip()
    }

    def _abs(rel: str) -> str:
        text = str(rel or "").replace("\\", "/").strip()
        if not text:
            return ""
        local = mapping.get(text) or mapping.get(text.lstrip("/"))
        if local and os.path.isfile(local):
            return os.path.abspath(local)
        if os.path.isfile(text):
            return os.path.abspath(text)
        return text

    background = payload.get("background")
    if isinstance(background, dict) and background.get("image"):
        background = dict(background)
        background["image"] = _abs(str(background.get("image") or ""))
        payload["background"] = background

    widgets = []
    for widget in payload.get("widgets") or []:
        if not isinstance(widget, dict):
            continue
        item = dict(widget)
        if item.get("type") == "image" and item.get("path"):
            item["path"] = _abs(str(item.get("path") or ""))
        widgets.append(item)
    if "widgets" in payload:
        payload["widgets"] = widgets
    return payload


def build_dev_player_package(
    *,
    app_name: str,
    ui: Mapping[str, Any],
    asset_map: Mapping[str, str],
    workflow_data: Mapping[str, Any],
    images_dir: str = "",
    sounds_dir: str = "",
    parent_workflow_file: str = "",
    required_client_width: int = 0,
    required_client_height: int = 0,
    scripts: Optional[Mapping[str, Mapping[str, Any]]] = None,
    scripts_meta: Optional[list] = None,
    entry_script_id: str = "",
) -> PlayerPackage:
    name = str(app_name or "").strip() or "独立程序"
    local_ui = normalize_player_ui(rewrite_ui_assets_to_local(ui, asset_map), app_name=name)
    payload_scripts = []
    for item in scripts_meta or []:
        if not isinstance(item, Mapping):
            continue
        sid = str(item.get("id") or "").strip()
        if not sid:
            continue
        payload_scripts.append(
            {
                "id": sid,
                "title": str(item.get("title") or sid).strip() or sid,
                "path": str(item.get("path") or f"workflows/scripts/{sid}.json").replace("\\", "/"),
            }
        )
    if not payload_scripts and scripts:
        for sid in scripts:
            text = str(sid or "").strip()
            if text:
                payload_scripts.append(
                    {"id": text, "title": text, "path": f"workflows/scripts/{text}.json"}
                )
    manifest = normalize_player_manifest(
        {
            "schema_version": PLAYER_PACKAGE_SCHEMA_VERSION,
            "app_name": name,
            "description": "开发环境调试运行",
            "entry_workflow": "workflows/main.json",
            "required_client_width": required_client_width,
            "required_client_height": required_client_height,
            "scripts": payload_scripts,
            "entry_script_id": str(entry_script_id or "").strip(),
        }
    )
    images = str(images_dir or "").strip() or get_images_dir("LCA")
    sounds = str(sounds_dir or "").strip() or get_sounds_dir("LCA")
    entry = str(parent_workflow_file or "").strip() or "dev://current-workflow"
    export_root = get_app_root()
    scripts_payload: dict[str, dict] = {}
    for sid, data in dict(scripts or {}).items():
        key = str(sid or "").strip()
        if key and isinstance(data, Mapping):
            scripts_payload[key] = copy.deepcopy(dict(data))
    return PlayerPackage(
        package_dir=str(export_root),
        export_root=str(export_root),
        userdata_dir=str(get_user_data_dir("LCA")),
        assets_images_dir=images,
        assets_sounds_dir=sounds,
        entry_workflow_path=entry,
        manifest=manifest,
        ui=local_ui,
        workflow_data=copy.deepcopy(dict(workflow_data or {})),
        scripts=scripts_payload,
    )


def runtime_config_from_main(main) -> dict:
    config = dict(getattr(main, "config", None) or {})
    bound = getattr(main, "bound_windows", None)
    if isinstance(bound, list):
        config["bound_windows"] = [dict(item) for item in bound if isinstance(item, dict)]
    mode = getattr(main, "current_execution_mode", None)
    if mode:
        config["execution_mode"] = str(mode)
    config.setdefault("execution_mode", "background_sendmessage")
    config.setdefault("screenshot_engine", str(config.get("screenshot_engine") or "wgc"))
    return config


def cancel_dev_player_theme_restore(window) -> None:
    """关闭并重建调试窗前取消旧窗的主题还原，避免把宿主主题打回切换前状态。"""
    cancel = getattr(window, "_cancel_dev_theme_restore", None)
    if callable(cancel):
        cancel()


def launch_dev_player_window(
    package: PlayerPackage,
    config: dict,
    *,
    parent=None,
    initial_page: str = "",
):
    """打开真实 PlayerWindow，但不退出宿主编辑器、不写回绑定配置。"""
    from PySide6.QtCore import Qt
    from themes import get_theme_manager
    from themes.theme_manager import detect_system_theme
    from ui.player.player_app import _player_overlay_qss
    from ui.player.player_chrome import apply_player_rounded_window
    from ui.player.player_window import PlayerWindow

    manager = get_theme_manager()
    theme_mode = resolve_player_theme(package.ui)
    if theme_mode in ("light", "dark"):
        effective = theme_mode
    else:
        # 调试窗 auto：跟当前宿主主题，避免又探一次系统主题导致和编辑器不一致
        host_theme = str(getattr(manager, "current_theme", "") or "").strip().lower()
        effective = host_theme if host_theme in ("light", "dark") else detect_system_theme()

    old_mode = getattr(manager, "theme_mode", None)
    old_current = getattr(manager, "current_theme", None)
    restored = {"done": False}

    def _restore_host_theme(*_args):
        if restored["done"]:
            return
        restored["done"] = True
        if old_mode is not None:
            manager.theme_mode = old_mode
        if old_current is not None:
            manager.current_theme = old_current

    def _cancel_restore():
        restored["done"] = True

    # 仅在构建期切到包主题以烘焙控件色，构建完立刻还原宿主，避免和编辑器主题抢全局状态。
    manager.theme_mode = theme_mode
    manager.current_theme = effective
    try:
        window = PlayerWindow(
            package,
            dict(config or {}),
            parent,
            quit_on_close=False,
            persist_binding=False,
            initial_page=str(initial_page or ""),
        )
        extra = _player_overlay_qss(effective == "dark")
        # 不要把整份主题 QSS 套到运行窗上：QMainWindow/QWidget 直角底会盖住圆角。
        apply_player_rounded_window(window)
        current = window.styleSheet() or ""
        if extra and extra not in current:
            window.setStyleSheet((current + "\n" + extra).strip() if current else extra)
        apply_player_rounded_window(window)
    except Exception:
        _restore_host_theme()
        raise
    else:
        _restore_host_theme()

    window._cancel_dev_theme_restore = _cancel_restore
    title = str(window.windowTitle() or "独立程序").strip()
    if "调试" not in title:
        window.setWindowTitle(f"{title}（调试）")
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    window.show()
    window.raise_()
    window.activateWindow()
    return window
