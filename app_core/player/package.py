from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from app_core.config_sections import DEFAULT_HOTKEYS


PLAYER_PACKAGE_SCHEMA_VERSION = 1
PLAYER_LAYOUTS = ("mini", "floating", "tray")
PLAYER_THEMES = ("auto", "light", "dark")
PLAYER_LAYOUT_CHOICES = (
    ("mini", "普通窗口"),
    ("floating", "始终置顶"),
    ("tray", "最小化到托盘"),
)
PLAYER_THEME_CHOICES = (
    ("auto", "跟随系统"),
    ("light", "浅色"),
    ("dark", "深色"),
)
PLAYER_WIDGET_TYPES = (
    "button",
    "label",
    "link",
    "log",
    "status",
    "image",
    "rich_text",
    "tabs",
    "script_list",
    "progress",
    "schedule",
)
PLAYER_BUTTON_ACTIONS = ("start", "pause", "stop", "bind", "settings")
PLAYER_TEXT_ALIGNS = ("left", "center", "right")
UI_ASSETS_DIRNAME = "ui_assets"


def _text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text if text else default


def _int(value: Any, default: int, *, minimum: int = 0, maximum: int = 10000) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def normalize_script_loop_count(value: Any, default: int = 1) -> int:
    """单个工作流循环次数：至少 1，最多 9999。"""
    return _int(value, default, minimum=1, maximum=9999)


def normalize_schedule_alarms(raw: Any, *, slots: int = 4) -> List[Dict[str, Any]]:
    """定时闹钟：最多 slots 组，每组 enabled + hour + minute。"""
    count = max(1, min(8, int(slots or 4)))
    alarms: List[Dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            alarms.append(
                {
                    "enabled": _bool(item.get("enabled"), False),
                    "hour": _int(item.get("hour"), 8, minimum=0, maximum=23),
                    "minute": _int(item.get("minute"), 0, minimum=0, maximum=59),
                }
            )
            if len(alarms) >= count:
                break
    while len(alarms) < count:
        alarms.append({"enabled": False, "hour": 8 + len(alarms), "minute": 0})
    return alarms[:count]


def expand_script_run_queue(
    selected: List[tuple],
    *,
    loops_by_id: Optional[Mapping[str, int]] = None,
    group_loops: int = 1,
) -> List[tuple]:
    """按「每项循环 × 整组循环」展开执行队列。

    每项为 ``(script_id, workflow_data, loop_index, loop_total)``，
    ``loop_index`` / ``loop_total`` 是该脚本自己的第几次/总次数。
    """
    counts = loops_by_id or {}
    rounds = normalize_script_loop_count(group_loops, 1)
    queue: List[tuple] = []
    for _ in range(rounds):
        for item in selected or []:
            if not item:
                continue
            sid = str(item[0] or "").strip()
            data = item[1] if len(item) > 1 else {}
            if not sid:
                continue
            total = normalize_script_loop_count(counts.get(sid, 1), 1)
            for index in range(1, total + 1):
                queue.append((sid, data, index, total))
    return queue


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return bool(value)


def _normalize_bg_color(raw: Any) -> str:
    """空 = 跟随主题；仅接受 #RGB / #RRGGBB。"""
    bg_color = _text(raw)
    if bg_color.startswith("#") and len(bg_color) in (4, 7):
        return bg_color
    return ""


def _new_widget_id() -> str:
    return "w_" + uuid.uuid4().hex[:10]


def default_window_size() -> Dict[str, int]:
    # Wide enough for script_list + log toolbar ("运行日志/清空/复制/目录") side by side.
    return {"width": 480, "height": 360}


def _theme_default(key: str) -> str:
    """从主题色板取默认色，避免业务代码写死 hex。"""
    try:
        from themes import theme_color

        return theme_color(key)
    except Exception:
        from themes.theme_manager import ThemeManager

        return ThemeManager.THEME_COLORS["light"].get(key, ThemeManager.THEME_COLORS["light"]["text"])


def default_background() -> Dict[str, Any]:
    # w/h 为 0 表示铺满窗口，兼容旧包
    return {"mode": "color", "color": _theme_default("canvas"), "image": "", "x": 0, "y": 0, "w": 0, "h": 0}


def default_player_widgets(app_name: str = "") -> List[Dict[str, Any]]:
    """接近旧版固定布局的默认控件集，供设计器与一键导出使用。"""
    title = _text(app_name) or "独立程序"
    return [
        {
            "id": "label_title",
            "type": "label",
            "text": title,
            "x": 20,
            "y": 16,
            "w": 440,
            "h": 28,
            "font_size": 14,
            "color": _theme_default("text"),
            "z": 10,
            "visible": True,
        },
        {
            "id": "status_main",
            "type": "status",
            "x": 20,
            "y": 52,
            "w": 440,
            "h": 24,
            "font_size": 12,
            "color": _theme_default("text"),
            "z": 11,
            "visible": True,
        },
        {
            "id": "btn_start",
            "type": "button",
            "action": "start",
            "text": "开始",
            "x": 20,
            "y": 90,
            "w": 100,
            "h": 36,
            "z": 20,
            "visible": True,
        },
        {
            "id": "btn_pause",
            "type": "button",
            "action": "pause",
            "text": "暂停",
            "x": 130,
            "y": 90,
            "w": 100,
            "h": 36,
            "z": 21,
            "visible": True,
        },
        {
            "id": "btn_stop",
            "type": "button",
            "action": "stop",
            "text": "停止",
            "x": 240,
            "y": 90,
            "w": 100,
            "h": 36,
            "z": 22,
            "visible": True,
        },
        {
            "id": "btn_bind",
            "type": "button",
            "action": "bind",
            "text": "绑定窗口",
            "x": 350,
            "y": 90,
            "w": 90,
            "h": 36,
            "z": 23,
            "visible": True,
        },
        {
            "id": "scripts_main",
            "type": "script_list",
            "title": "脚本",
            "x": 20,
            "y": 136,
            "w": 200,
            "h": 188,
            "items": [],
            "group_loops": 1,
            "z": 16,
            "visible": True,
        },
        {
            "id": "log_main",
            "type": "log",
            "x": 230,
            "y": 136,
            "w": 230,
            "h": 188,
            "z": 15,
            "visible": True,
        },
    ]


def default_player_ui(app_name: str = "", *, with_widgets: bool = True) -> Dict[str, Any]:
    title = _text(app_name) or "独立程序"
    payload: Dict[str, Any] = {
        "title": title,
        "layout": "mini",
        "theme": "auto",
        "auto_start": False,
        "exit_on_finish": False,
        "notify_on_finish": True,
        "show_log": True,
        "start_hotkey": DEFAULT_HOTKEYS["start_task_hotkey"],
        "stop_hotkey": DEFAULT_HOTKEYS["stop_task_hotkey"],
        "pause_hotkey": DEFAULT_HOTKEYS["pause_workflow_hotkey"],
        "skin_image": "",
        "about": "",
        "window": default_window_size(),
        "background": default_background(),
    }
    if with_widgets:
        payload["widgets"] = default_player_widgets(title)
    return payload


def _normalize_window(raw: Any) -> Dict[str, int]:
    base = default_window_size()
    if not isinstance(raw, Mapping):
        return base
    return {
        "width": _int(raw.get("width"), base["width"], minimum=240, maximum=1920),
        "height": _int(raw.get("height"), base["height"], minimum=160, maximum=1200),
    }


def _normalize_background(raw: Any) -> Dict[str, Any]:
    base = default_background()
    if not isinstance(raw, Mapping):
        return base
    mode = _text(raw.get("mode"), base["mode"]).lower()
    if mode not in ("color", "image"):
        mode = "color"
    image = _text(raw.get("image")).replace("\\", "/")
    color = _text(raw.get("color"), base["color"])
    if not color.startswith("#"):
        color = base["color"]
    return {
        "mode": mode,
        "color": color,
        "image": image,
        "x": _int(raw.get("x"), 0, minimum=-4000, maximum=4000),
        "y": _int(raw.get("y"), 0, minimum=-4000, maximum=4000),
        "w": _int(raw.get("w"), 0, minimum=0, maximum=4000),
        "h": _int(raw.get("h"), 0, minimum=0, maximum=4000),
    }


def _normalize_hex_color(value: Any, default: str) -> str:
    color = _text(value, default)
    if color.startswith("#") and len(color) in (4, 7):
        return color
    return default


def _normalize_tab_pages(raw: Any) -> List[Dict[str, str]]:
    pages: List[Dict[str, str]] = []
    seen = set()
    if isinstance(raw, list):
        for index, item in enumerate(raw):
            if not isinstance(item, Mapping):
                continue
            page_id = _text(item.get("id")) or f"page_{index + 1}"
            if page_id in seen:
                continue
            seen.add(page_id)
            title = _text(item.get("title"), f"页{index + 1}")
            pages.append({"id": page_id, "title": title})
    if not pages:
        pages = [
            {"id": "page_1", "title": "页面1"},
            {"id": "page_2", "title": "页面2"},
        ]
    return pages


def _normalize_script_items(raw: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    seen = set()
    if isinstance(raw, list):
        for index, item in enumerate(raw):
            if not isinstance(item, Mapping):
                continue
            item_id = _text(item.get("id")) or f"script_{index + 1}"
            if item_id in seen:
                continue
            seen.add(item_id)
            source = _text(item.get("source")).replace("\\", "/")
            entry = {
                "id": item_id,
                "title": _text(item.get("title"), f"脚本{index + 1}"),
                "checked": _bool(item.get("checked"), True),
                "loops": normalize_script_loop_count(item.get("loops"), 1),
            }
            if source:
                entry["source"] = source
            items.append(entry)
    # 仅在完全未提供 items 时给占位；空列表表示「尚未同步到导出脚本」
    if not items and raw is None:
        items = [
            {"id": "script_1", "title": "脚本1", "checked": True, "loops": 1},
            {"id": "script_2", "title": "脚本2", "checked": False, "loops": 1},
        ]
    return items


def _normalize_widget(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, Mapping):
        return None
    kind = _text(raw.get("type")).lower()
    if kind not in PLAYER_WIDGET_TYPES:
        return None
    default_h = (
        280
        if kind == "tabs"
        else (
            120
            if kind == "schedule"
            else (
                80
                if kind in ("rich_text", "script_list")
                else (36 if kind == "progress" else 28)
            )
        )
    )
    default_w = 420 if kind == "tabs" else (220 if kind in ("rich_text", "script_list", "progress", "schedule") else 100)
    widget: Dict[str, Any] = {
        "id": _text(raw.get("id")) or _new_widget_id(),
        "type": kind,
        "x": _int(raw.get("x"), 0, maximum=4000),
        "y": _int(raw.get("y"), 0, maximum=4000),
        "w": _int(raw.get("w"), default_w, minimum=8, maximum=4000),
        "h": _int(raw.get("h"), default_h, minimum=8, maximum=4000),
        "z": _int(raw.get("z"), 0 if kind == "image" else 10, minimum=-10000, maximum=10000),
        "visible": _bool(raw.get("visible"), True),
        # 空 = 所有标签页都显示；有值则仅对应 page 显示
        "page": _text(raw.get("page")),
    }
    if kind == "button":
        action = _text(raw.get("action"), "start").lower()
        if action not in PLAYER_BUTTON_ACTIONS:
            action = "start"
        widget["action"] = action
        defaults = {
            "start": "开始",
            "pause": "暂停",
            "stop": "停止",
            "bind": "绑定窗口",
            "settings": "设置",
        }
        widget["text"] = _text(raw.get("text"), defaults[action])
        widget["bg_color"] = _normalize_bg_color(raw.get("bg_color"))
    elif kind == "label":
        widget["text"] = _text(raw.get("text"), "文本")
        widget["font_size"] = _int(raw.get("font_size"), 12, minimum=8, maximum=72)
        widget["color"] = _text(raw.get("color"), _theme_default("text"))
    elif kind == "rich_text":
        widget["text"] = _text(raw.get("text"), "说明文字")
        widget["font_size"] = _int(raw.get("font_size"), 12, minimum=8, maximum=72)
        widget["color"] = _text(raw.get("color"), _theme_default("text"))
        align = _text(raw.get("align"), "left").lower()
        widget["align"] = align if align in PLAYER_TEXT_ALIGNS else "left"
    elif kind == "tabs":
        widget["pages"] = _normalize_tab_pages(raw.get("pages"))
        # 标签条本身始终显示
        widget["page"] = ""
        widget["bg_color"] = _normalize_bg_color(raw.get("bg_color"))
        widget["font_size"] = _int(raw.get("font_size"), 12, minimum=8, maximum=72)
        widget["color"] = _text(raw.get("color"), _theme_default("text"))
    elif kind == "script_list":
        widget["title"] = _text(raw.get("title"), "脚本")
        widget["items"] = _normalize_script_items(raw.get("items"))
        widget["group_loops"] = normalize_script_loop_count(raw.get("group_loops"), 1)
        order_mode = _text(raw.get("order_mode"), "fixed").lower()
        widget["order_mode"] = order_mode if order_mode in ("fixed", "random") else "fixed"
        widget["bg_color"] = _normalize_bg_color(raw.get("bg_color"))
        widget["font_size"] = _int(raw.get("font_size"), 12, minimum=8, maximum=72)
        widget["color"] = _text(raw.get("color"), _theme_default("text"))
    elif kind == "progress":
        widget["title"] = _text(raw.get("title"), "进度")
        widget["bg_color"] = _normalize_bg_color(raw.get("bg_color"))
        widget["font_size"] = _int(raw.get("font_size"), 12, minimum=8, maximum=72)
        widget["color"] = _text(raw.get("color"), _theme_default("text"))
    elif kind == "schedule":
        widget["title"] = _text(raw.get("title"), "定时")
        widget["alarms"] = normalize_schedule_alarms(raw.get("alarms"))
        widget["bg_color"] = _normalize_bg_color(raw.get("bg_color"))
        widget["font_size"] = _int(raw.get("font_size"), 12, minimum=8, maximum=72)
        widget["color"] = _text(raw.get("color"), _theme_default("text"))
    elif kind == "link":
        widget["text"] = _text(raw.get("text"), "链接")
        widget["url"] = _text(raw.get("url"))
        widget["font_size"] = _int(raw.get("font_size"), 12, minimum=8, maximum=72)
        widget["color"] = _text(raw.get("color"), _theme_default("accent"))
    elif kind == "image":
        widget["path"] = _text(raw.get("path")).replace("\\", "/")
    elif kind == "log":
        widget["bg_color"] = _normalize_bg_color(raw.get("bg_color"))
        widget["font_size"] = _int(raw.get("font_size"), 12, minimum=8, maximum=72)
        widget["color"] = _text(raw.get("color"), _theme_default("text"))
    elif kind == "status":
        widget["font_size"] = _int(raw.get("font_size"), 12, minimum=8, maximum=72)
        widget["color"] = _text(raw.get("color"), _theme_default("text"))
    return widget


def _fold_loop_settings_into_script_list(raw: Any) -> List[Any]:
    """把旧版独立「循环设置」并进脚本列表后丢弃。"""
    if not isinstance(raw, list):
        return []
    loop_src: Optional[Dict[str, Any]] = None
    others: List[Any] = []
    for item in raw:
        if isinstance(item, Mapping) and str(item.get("type") or "").lower() == "loop_settings":
            if loop_src is None:
                loop_src = dict(item)
            continue
        others.append(item)
    if loop_src is None:
        return others
    loops_by_id: Dict[str, Any] = {}
    for entry in loop_src.get("items") or []:
        if not isinstance(entry, Mapping):
            continue
        sid = str(entry.get("id") or "").strip()
        if sid:
            loops_by_id[sid] = entry.get("loops", 1)
    group = loop_src.get("group_loops", 1)
    merged = False
    result: List[Any] = []
    for item in others:
        if (
            not merged
            and isinstance(item, Mapping)
            and str(item.get("type") or "").lower() == "script_list"
        ):
            item = dict(item)
            item["group_loops"] = group
            items: List[Any] = []
            seen: set[str] = set()
            for entry in item.get("items") or []:
                if not isinstance(entry, Mapping):
                    continue
                entry = dict(entry)
                sid = str(entry.get("id") or "").strip()
                if sid and sid in loops_by_id:
                    entry["loops"] = loops_by_id[sid]
                if sid:
                    seen.add(sid)
                items.append(entry)
            for entry in loop_src.get("items") or []:
                if not isinstance(entry, Mapping):
                    continue
                sid = str(entry.get("id") or "").strip()
                if not sid or sid in seen:
                    continue
                seen.add(sid)
                items.append(dict(entry))
            item["items"] = items
            result.append(item)
            merged = True
        else:
            result.append(item)
    if not merged:
        converted = dict(loop_src)
        converted["type"] = "script_list"
        title = _text(converted.get("title"), "脚本")
        converted["title"] = "脚本" if title in ("", "循环") else title
        converted["group_loops"] = group
        result.insert(0, converted)
    return result


def normalize_player_widgets(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    widgets: List[Dict[str, Any]] = []
    seen_actions = set()
    seen_tabs = False
    seen_schedule = False
    for item in _fold_loop_settings_into_script_list(raw):
        widget = _normalize_widget(item)
        if widget is None:
            continue
        if widget["type"] == "button":
            action = widget["action"]
            if action in seen_actions:
                continue
            seen_actions.add(action)
        elif widget["type"] == "tabs":
            if seen_tabs:
                continue
            seen_tabs = True
        elif widget["type"] == "schedule":
            if seen_schedule:
                continue
            seen_schedule = True
        widgets.append(widget)
    # 页归属：无 tabs 时清空；有 tabs 时丢弃未知 page（空 = 全局）
    page_ids = set()
    for widget in widgets:
        if widget.get("type") == "tabs":
            for page in widget.get("pages") or []:
                page_ids.add(str(page.get("id") or ""))
    page_ids.discard("")
    for widget in widgets:
        if widget.get("type") == "tabs":
            widget["page"] = ""
            continue
        page = str(widget.get("page") or "")
        # 无标签页、或归属了不存在的页 → 视为全局（始终显示）
        if not page_ids or (page and page not in page_ids):
            widget["page"] = ""
    widgets.sort(key=lambda item: (int(item.get("z") or 0), str(item.get("id") or "")))
    return widgets


def resolve_player_layout(ui: Mapping[str, Any] | None) -> str:
    raw = ui.get("layout") if isinstance(ui, Mapping) else ""
    layout = _text(raw, "mini").lower()
    return layout if layout in PLAYER_LAYOUTS else "mini"


def resolve_player_theme(ui: Mapping[str, Any] | None) -> str:
    raw = ui.get("theme") if isinstance(ui, Mapping) else ""
    theme = _text(raw, "auto").lower()
    return theme if theme in PLAYER_THEMES else "auto"


def player_should_stay_on_top(layout: str) -> bool:
    return str(layout or "") == "floating"


def player_should_start_hidden(layout: str, *, tray_available: bool) -> bool:
    return str(layout or "") == "tray" and bool(tray_available)


def player_close_hides_to_tray(layout: str, *, quit_on_close: bool) -> bool:
    return str(layout or "") == "tray" and bool(quit_on_close)


def has_custom_widgets(ui: Mapping[str, Any] | None) -> bool:
    if not isinstance(ui, Mapping):
        return False
    widgets = ui.get("widgets")
    return isinstance(widgets, list) and len(widgets) > 0


def normalize_player_ui(raw: Any, app_name: str = "") -> Dict[str, Any]:
    """
    归一化 ui.json。
    - 若含 widgets：按画布协议解析（设计器导出）。
    - 若无 widgets：保留旧字段，不注入默认 widgets，保证旧包走固定布局回退。
    """
    normalized = default_player_ui(app_name, with_widgets=False)
    if not isinstance(raw, Mapping):
        return normalized

    normalized["title"] = _text(raw.get("title"), normalized["title"])
    layout = _text(raw.get("layout"), "mini").lower()
    normalized["layout"] = layout if layout in PLAYER_LAYOUTS else "mini"
    theme = _text(raw.get("theme"), "auto").lower()
    normalized["theme"] = theme if theme in PLAYER_THEMES else "auto"
    normalized["auto_start"] = bool(raw.get("auto_start"))
    normalized["exit_on_finish"] = bool(raw.get("exit_on_finish"))
    if "notify_on_finish" in raw:
        normalized["notify_on_finish"] = bool(raw.get("notify_on_finish"))
    else:
        normalized["notify_on_finish"] = True
    normalized["show_log"] = True if raw.get("show_log") is None else bool(raw.get("show_log"))
    normalized["start_hotkey"] = _text(raw.get("start_hotkey"), normalized["start_hotkey"]).upper()
    normalized["stop_hotkey"] = _text(raw.get("stop_hotkey"), normalized["stop_hotkey"]).upper()
    normalized["pause_hotkey"] = _text(raw.get("pause_hotkey"), normalized["pause_hotkey"]).upper()
    normalized["skin_image"] = _text(raw.get("skin_image")).replace("\\", "/")
    normalized["about"] = _text(raw.get("about"))
    normalized["window"] = _normalize_window(raw.get("window"))
    normalized["background"] = _normalize_background(raw.get("background"))

    # 兼容旧 skin_image → background.image
    if normalized["skin_image"] and not normalized["background"].get("image"):
        normalized["background"]["mode"] = "image"
        normalized["background"]["image"] = normalized["skin_image"]

    if "widgets" in raw:
        widgets = normalize_player_widgets(raw.get("widgets"))
        normalized["widgets"] = widgets
        # 有日志控件时同步 show_log
        log_visible = any(w.get("type") == "log" and w.get("visible", True) for w in widgets)
        if any(w.get("type") == "log" for w in widgets):
            normalized["show_log"] = log_visible
        list_ids = [str(w.get("id") or "") for w in widgets if w.get("type") == "script_list" and w.get("id")]
        order_raw = raw.get("list_order")
        list_order: list[str] = []
        if isinstance(order_raw, list):
            for item in order_raw:
                sid = _text(item)
                if sid and sid in list_ids and sid not in list_order:
                    list_order.append(sid)
        for sid in list_ids:
            if sid not in list_order:
                list_order.append(sid)
        normalized["list_order"] = list_order
        lom = _text(raw.get("list_order_mode"), "fixed").lower()
        normalized["list_order_mode"] = lom if lom in ("fixed", "random") else "fixed"
    return normalized


def ensure_designer_ui(raw: Any = None, app_name: str = "") -> Dict[str, Any]:
    """设计器/一键导出用：保证带默认 widgets。"""
    if isinstance(raw, Mapping) and has_custom_widgets(raw):
        return normalize_player_ui(raw, app_name=app_name)
    base = default_player_ui(app_name, with_widgets=True)
    if isinstance(raw, Mapping):
        merged = dict(base)
        merged.update({k: v for k, v in raw.items() if k != "widgets"})
        if has_custom_widgets(raw):
            merged["widgets"] = raw["widgets"]
        return normalize_player_ui(merged, app_name=app_name)
    return normalize_player_ui(base, app_name=app_name)


def collect_ui_asset_refs(ui: Mapping[str, Any]) -> List[str]:
    """收集 ui 中引用的相对资源路径（ui_assets/...）。"""
    refs: List[str] = []
    bg = ui.get("background") if isinstance(ui.get("background"), Mapping) else {}
    image = _text(bg.get("image") if isinstance(bg, Mapping) else "").replace("\\", "/")
    if image:
        refs.append(image)
    for widget in ui.get("widgets") or []:
        if not isinstance(widget, Mapping):
            continue
        if widget.get("type") == "image":
            path = _text(widget.get("path")).replace("\\", "/")
            if path:
                refs.append(path)
    # 去重保序
    seen = set()
    unique: List[str] = []
    for item in refs:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def normalize_player_manifest(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("package/manifest.json 必须是对象")
    schema_version = raw.get("schema_version", PLAYER_PACKAGE_SCHEMA_VERSION)
    try:
        schema_version = int(schema_version)
    except (TypeError, ValueError) as exc:
        raise ValueError("manifest.schema_version 必须是整数") from exc
    if schema_version != PLAYER_PACKAGE_SCHEMA_VERSION:
        raise ValueError(f"不支持的独立程序包版本: {schema_version}")
    app_name = _text(raw.get("app_name"), "独立程序")
    entry_workflow = _text(raw.get("entry_workflow"), "workflows/main.json").replace("\\", "/")
    if not entry_workflow:
        raise ValueError("manifest.entry_workflow 不能为空")
    required_width = _int(raw.get("required_client_width"), 0, maximum=10000)
    required_height = _int(raw.get("required_client_height"), 0, maximum=10000)
    if required_width <= 0 or required_height <= 0:
        required_width = 0
        required_height = 0
    scripts_meta: List[Dict[str, str]] = []
    raw_scripts = raw.get("scripts")
    if isinstance(raw_scripts, list):
        for item in raw_scripts:
            if not isinstance(item, Mapping):
                continue
            sid = _text(item.get("id"))
            if not sid:
                continue
            scripts_meta.append(
                {
                    "id": sid,
                    "title": _text(item.get("title"), sid),
                    "path": _text(item.get("path"), f"workflows/scripts/{sid}.json").replace(
                        "\\", "/"
                    ),
                }
            )
    content_sha256 = _text(raw.get("content_sha256")).lower()
    result = {
        "schema_version": schema_version,
        "app_name": app_name,
        "description": _text(raw.get("description")),
        "entry_workflow": entry_workflow,
        "entry_script_id": _text(raw.get("entry_script_id")),
        "company": _text(raw.get("company")),
        "version": _text(raw.get("version")),
        "required_client_width": required_width,
        "required_client_height": required_height,
        "scripts": scripts_meta,
    }
    if content_sha256:
        result["content_sha256"] = content_sha256
    return result


@dataclass(frozen=True)
class PlayerPackage:
    package_dir: str
    export_root: str
    userdata_dir: str
    assets_images_dir: str
    assets_sounds_dir: str
    entry_workflow_path: str
    manifest: Dict[str, Any]
    ui: Dict[str, Any]
    workflow_data: Dict[str, Any] = field(repr=False)
    # id -> workflow_data；供脚本列表勾选后切换执行
    scripts: Dict[str, Dict[str, Any]] = field(default_factory=dict, repr=False)
    runtime_config: Dict[str, Any] = field(default_factory=dict)


def resolve_ui_asset_bytes(package: Optional[PlayerPackage], relative_or_abs: str) -> Optional[bytes]:
    """从内存包或磁盘解析 UI 资源。"""
    text = _text(relative_or_abs).replace("\\", "/")
    if not text:
        return None
    from app_core.player.memory_store import get_player_memory_file

    candidates = [text.lstrip("/")]
    if not text.startswith(UI_ASSETS_DIRNAME + "/") and "/" not in text and "\\" not in relative_or_abs:
        candidates.append(f"{UI_ASSETS_DIRNAME}/{text}")
    for key in candidates:
        data = get_player_memory_file(key)
        if data:
            return data
    # 绝对路径（设计器本地预览）
    from pathlib import Path

    abs_path = Path(relative_or_abs)
    if abs_path.is_file():
        try:
            return abs_path.read_bytes()
        except OSError:
            return None
    if package is not None:
        for key in candidates:
            disk = Path(package.package_dir) / key
            if disk.is_file():
                try:
                    return disk.read_bytes()
                except OSError:
                    return None
            # 明文 package 子目录
            alt = Path(package.package_dir) / "package" / key
            if alt.is_file():
                try:
                    return alt.read_bytes()
                except OSError:
                    return None
    return None
