"""导出脚本目录：工作区工作流 → 脚本列表 / 打包 / 运行勾选。"""

from __future__ import annotations

import copy
import os
import re
from typing import Any, Dict, List, Mapping, Optional


def _safe_script_id(raw: str, fallback: str) -> str:
    text = str(raw or "").strip()
    text = os.path.splitext(os.path.basename(text))[0] if text else ""
    text = re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE).strip("_")
    return text or fallback


def script_id_for_task(task: Any) -> str:
    filepath = str(getattr(task, "filepath", "") or "").strip()
    task_id = getattr(task, "task_id", None)
    fallback = f"task_{task_id}" if task_id is not None else "script"
    if filepath:
        return _safe_script_id(filepath, fallback)
    name = str(getattr(task, "name", "") or "").strip()
    return _safe_script_id(name, fallback)


def workspace_dirs_from_main(main: Any) -> List[str]:
    """侧栏已配置的工作区根目录（导出扫描范围）。"""
    from task_workflow.workspace import normalize_workspace_dir

    panel = getattr(main, "parameter_panel", None) if main is not None else None
    raw = None
    if panel is not None:
        raw = getattr(panel, "_favorite_workspaces", None)
    if raw is None and main is not None:
        raw = getattr(main, "_favorite_workspaces", None)
    if not isinstance(raw, (list, tuple)):
        return []
    out: List[str] = []
    seen: set[str] = set()
    for item in raw:
        root = normalize_workspace_dir(item)
        if not root:
            continue
        key = os.path.normcase(root)
        if key in seen:
            continue
        seen.add(key)
        out.append(root)
    return out


def list_workspace_export_scripts(main: Any) -> List[Dict[str, Any]]:
    """当前工作区目录下已落盘且含卡片的工作流，各作为一项可导出脚本。"""
    from task_workflow.workspace import (
        extract_workflow_metadata,
        get_workflow_body,
        iter_workspace_workflow_files,
        load_workspace_workflow,
    )

    result: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for root in workspace_dirs_from_main(main):
        for filepath in iter_workspace_workflow_files(root):
            workflow_data = load_workspace_workflow(filepath)
            if not isinstance(workflow_data, dict):
                continue
            body = get_workflow_body(workflow_data)
            cards = body.get("cards") if isinstance(body, dict) else None
            if not cards:
                continue
            script_id = _safe_script_id(filepath, "script")
            if script_id in seen:
                base = script_id
                index = 2
                while script_id in seen:
                    script_id = f"{base}_{index}"
                    index += 1
            seen.add(script_id)
            meta = extract_workflow_metadata(workflow_data)
            title = str(meta.get("name") or body.get("name") or "").strip()
            if not title:
                title = os.path.splitext(os.path.basename(filepath))[0]
            if title.lower().endswith(".json") or title.lower().endswith(".lca"):
                title = os.path.splitext(title)[0]
            result.append(
                {
                    "id": script_id,
                    "title": title or script_id,
                    "filepath": str(filepath),
                    "workflow_data": copy.deepcopy(body if isinstance(body, dict) else workflow_data),
                }
            )
    return result


def list_open_export_scripts(main: Any) -> List[Dict[str, Any]]:
    """当前编辑器里已打开且含卡片的工作流，各作为一项可导出脚本。"""
    task_manager = getattr(main, "task_manager", None)
    tab_widget = getattr(main, "workflow_tab_widget", None)
    if task_manager is None:
        return []
    tasks: List[Any] = []
    if tab_widget is not None:
        tab_to_task = getattr(tab_widget, "tab_to_task", None) or {}
        count = int(tab_widget.count()) if callable(getattr(tab_widget, "count", None)) else 0
        for index in range(count):
            task_id = tab_to_task.get(index)
            if task_id is None:
                continue
            get_task = getattr(task_manager, "get_task", None)
            task = get_task(task_id) if callable(get_task) else None
            if task is not None:
                tasks.append(task)
    if not tasks:
        getter = getattr(task_manager, "get_all_tasks", None)
        tasks = list(getter() or []) if callable(getter) else []
    result: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for task in tasks:
        script_id = script_id_for_task(task)
        if script_id in seen:
            # 同名文件打开多次时加后缀
            base = script_id
            index = 2
            while script_id in seen:
                script_id = f"{base}_{index}"
                index += 1
        seen.add(script_id)

        workflow_data = None
        task_id = getattr(task, "task_id", None)
        if tab_widget is not None and task_id is not None:
            views = getattr(tab_widget, "task_views", None) or {}
            view = views.get(task_id)
            serialize = getattr(view, "serialize_workflow", None) if view is not None else None
            if callable(serialize):
                try:
                    workflow_data = serialize()
                except Exception:
                    workflow_data = None
        if not isinstance(workflow_data, dict):
            workflow_data = copy.deepcopy(getattr(task, "workflow_data", None) or {})
        if not (workflow_data.get("cards") if isinstance(workflow_data, dict) else None):
            continue

        name = str(getattr(task, "name", "") or "").strip()
        if name.lower().endswith(".json"):
            name = os.path.splitext(name)[0]
        if not name:
            name = script_id
        result.append(
            {
                "id": script_id,
                "title": name,
                "filepath": str(getattr(task, "filepath", "") or ""),
                "workflow_data": workflow_data,
            }
        )
    return result


def sync_script_list_items(
    existing: Optional[List[Any]],
    catalog: List[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """用导出目录刷新脚本列表项。

    - 保留已有项的**自定义顺序**、显示名与勾选
    - 目录中新增的脚本追加到末尾
    - 目录里已消失的脚本从列表移除
    """
    catalog_by_id: Dict[str, Mapping[str, Any]] = {}
    catalog_order: List[str] = []
    for entry in catalog or []:
        if not isinstance(entry, Mapping):
            continue
        item_id = str(entry.get("id") or "").strip()
        if not item_id or item_id in catalog_by_id:
            continue
        catalog_by_id[item_id] = entry
        catalog_order.append(item_id)

    def _build(item_id: str, prev: Mapping[str, Any], entry: Mapping[str, Any]) -> Dict[str, Any]:
        from app_core.player.package import normalize_script_loop_count

        title = str(prev.get("title") or entry.get("title") or item_id).strip() or item_id
        if "checked" in prev:
            checked = bool(prev.get("checked"))
        else:
            checked = True
        loops = normalize_script_loop_count(
            prev.get("loops") if "loops" in prev else 1,
            1,
        )
        return {
            "id": item_id,
            "title": title,
            "checked": checked,
            "loops": loops,
            "source": f"workflows/scripts/{item_id}.json",
        }

    items: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in existing or []:
        if not isinstance(item, Mapping):
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id or item_id in seen or item_id not in catalog_by_id:
            continue
        seen.add(item_id)
        items.append(_build(item_id, item, catalog_by_id[item_id]))
    for item_id in catalog_order:
        if item_id in seen:
            continue
        seen.add(item_id)
        items.append(_build(item_id, {}, catalog_by_id[item_id]))
    return items


def scripts_dict_from_catalog(catalog: List[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """id -> workflow_data，供开发态运行窗切换脚本。"""
    scripts: Dict[str, Dict[str, Any]] = {}
    for entry in catalog or []:
        if not isinstance(entry, Mapping):
            continue
        sid = str(entry.get("id") or "").strip()
        data = entry.get("workflow_data")
        if not sid or not isinstance(data, Mapping):
            continue
        scripts[sid] = copy.deepcopy(dict(data))
    return scripts


def scripts_meta_from_catalog(catalog: List[Mapping[str, Any]]) -> List[Dict[str, str]]:
    meta: List[Dict[str, str]] = []
    for entry in catalog or []:
        if not isinstance(entry, Mapping):
            continue
        sid = str(entry.get("id") or "").strip()
        if not sid:
            continue
        title = str(entry.get("title") or sid).strip() or sid
        meta.append({"id": sid, "title": title, "path": f"workflows/scripts/{sid}.json"})
    return meta


def script_list_widgets(ui: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """按 list_order（若有）返回脚本列表控件副本。"""
    if not isinstance(ui, Mapping):
        return []
    widgets = [dict(w) for w in (ui.get("widgets") or []) if isinstance(w, Mapping)]
    lists = [w for w in widgets if str(w.get("type") or "") == "script_list"]
    if not lists:
        return []
    by_id = {str(w.get("id") or ""): w for w in lists if str(w.get("id") or "").strip()}
    order_raw = ui.get("list_order")
    ordered_ids: List[str] = []
    if isinstance(order_raw, list):
        for raw_id in order_raw:
            sid = str(raw_id or "").strip()
            if sid and sid in by_id and sid not in ordered_ids:
                ordered_ids.append(sid)
    for wid in by_id:
        if wid not in ordered_ids:
            ordered_ids.append(wid)
    # 无 id 的列表跟在后面
    result = [by_id[i] for i in ordered_ids if i in by_id]
    for widget in lists:
        wid = str(widget.get("id") or "").strip()
        if not wid:
            result.append(widget)
    return result


def assigned_script_ids(ui: Optional[Mapping[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for widget in script_list_widgets(ui):
        for item in widget.get("items") or []:
            if not isinstance(item, Mapping):
                continue
            sid = str(item.get("id") or "").strip()
            if sid:
                ids.add(sid)
    return ids


def unassigned_catalog_items(
    catalog: List[Mapping[str, Any]],
    ui: Optional[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    taken = assigned_script_ids(ui)
    out: List[Dict[str, Any]] = []
    for entry in catalog or []:
        if not isinstance(entry, Mapping):
            continue
        sid = str(entry.get("id") or "").strip()
        if not sid or sid in taken:
            continue
        out.append(dict(entry))
    return out


def script_list_all_item_ids(ui: Optional[Mapping[str, Any]]) -> Optional[List[str]]:
    """所有脚本列表 items 的 id（保序、去重）。无列表或全无 items 时返回 None。"""
    if not isinstance(ui, Mapping):
        return None
    found = False
    ordered: List[str] = []
    seen: set[str] = set()
    for widget in script_list_widgets(ui):
        items = widget.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            found = True
            sid = str(item.get("id") or "").strip()
            if not sid or sid in seen:
                continue
            seen.add(sid)
            ordered.append(sid)
    if not found:
        return None
    return ordered


def assert_script_lists_exclusive(ui: Optional[Mapping[str, Any]]) -> Optional[str]:
    """若多列表存在重复 id，返回中文错误信息。"""
    seen: dict[str, str] = {}
    for widget in script_list_widgets(ui):
        title = str(widget.get("title") or widget.get("id") or "脚本列表").strip()
        for item in widget.get("items") or []:
            if not isinstance(item, Mapping):
                continue
            sid = str(item.get("id") or "").strip()
            if not sid:
                continue
            if sid in seen:
                return f"工作流「{sid}」同时出现在「{seen[sid]}」与「{title}」，每个工作流只能放进一个脚本列表。"
            seen[sid] = title
    return None


def ensure_list_order(ui: Mapping[str, Any] | dict) -> dict:
    payload = dict(ui)
    lists = script_list_widgets(payload)
    ids = [str(w.get("id") or "").strip() for w in lists if str(w.get("id") or "").strip()]
    payload["list_order"] = ids
    mode = str(payload.get("list_order_mode") or "fixed").strip().lower()
    payload["list_order_mode"] = mode if mode in ("fixed", "random") else "fixed"
    return payload


def apply_catalog_to_ui(ui: Mapping[str, Any], catalog: List[Mapping[str, Any]]) -> dict:
    """旧行为：把目录同步进每一个脚本列表（会重复）。请优先用 apply_catalog_to_ui_exclusive。"""
    payload = copy.deepcopy(dict(ui or {}))
    widgets = []
    for widget in payload.get("widgets") or []:
        if not isinstance(widget, dict):
            continue
        item = dict(widget)
        if str(item.get("type") or "") == "script_list":
            item["items"] = sync_script_list_items(item.get("items"), catalog)
        widgets.append(item)
    if "widgets" in payload:
        payload["widgets"] = widgets
    return payload


def apply_catalog_to_ui_exclusive(ui: Mapping[str, Any], catalog: List[Mapping[str, Any]]) -> dict:
    """互斥同步：剔除不在 catalog 的项；新项只追加到第一个脚本列表。"""
    payload = copy.deepcopy(dict(ui or {}))
    catalog_ids = {
        str(entry.get("id") or "").strip()
        for entry in (catalog or [])
        if isinstance(entry, Mapping) and str(entry.get("id") or "").strip()
    }
    catalog_by_id = {
        str(entry.get("id") or "").strip(): entry
        for entry in (catalog or [])
        if isinstance(entry, Mapping) and str(entry.get("id") or "").strip()
    }
    widgets = []
    list_indices: List[int] = []
    claimed: set[str] = set()
    for widget in payload.get("widgets") or []:
        if not isinstance(widget, dict):
            continue
        item = dict(widget)
        if str(item.get("type") or "") == "script_list":
            list_indices.append(len(widgets))
            kept: List[Dict[str, Any]] = []
            for entry in item.get("items") or []:
                if not isinstance(entry, Mapping):
                    continue
                sid = str(entry.get("id") or "").strip()
                if not sid or sid not in catalog_ids or sid in claimed:
                    continue
                claimed.add(sid)
                # 用 catalog 刷新 title/source，保留 checked/loops
                cat = catalog_by_id.get(sid) or {}
                row = dict(entry)
                if cat.get("title"):
                    row.setdefault("title", cat.get("title"))
                kept.append(row)
            item["items"] = kept
            mode = str(item.get("order_mode") or "fixed").strip().lower()
            item["order_mode"] = mode if mode in ("fixed", "random") else "fixed"
        widgets.append(item)
    payload["widgets"] = widgets
    # 新项进第一个列表
    missing = [sid for sid in catalog_by_id if sid not in claimed]
    if missing:
        if not list_indices:
            # 无脚本列表：不自动造控件（由设计器添加）；打包回退用全 catalog
            pass
        else:
            first = widgets[list_indices[0]]
            items = list(first.get("items") or [])
            stub_catalog = [catalog_by_id[sid] for sid in missing]
            items.extend(sync_script_list_items([], stub_catalog))
            first["items"] = items
            widgets[list_indices[0]] = first
            payload["widgets"] = widgets
    return ensure_list_order(payload)


def default_entry_script_id(
    ui: Optional[Mapping[str, Any]],
    catalog: List[Mapping[str, Any]],
) -> str:
    for widget in script_list_widgets(ui):
        for item in widget.get("items") or []:
            if not isinstance(item, Mapping):
                continue
            sid = str(item.get("id") or "").strip()
            if sid:
                return sid
    for entry in catalog or []:
        if isinstance(entry, Mapping):
            sid = str(entry.get("id") or "").strip()
            if sid:
                return sid
    return ""


def script_list_checked_ids(ui: Optional[Mapping[str, Any]]) -> Optional[List[str]]:
    """从设计器 UI 读取脚本列表勾选（运行时默认勾选）。

    返回 None 表示界面里还没有脚本列表项。
    """
    if not isinstance(ui, Mapping):
        return None
    found_list = False
    checked: List[str] = []
    seen: set[str] = set()
    for widget in script_list_widgets(ui):
        items = widget.get("items")
        if not isinstance(items, list) or not items:
            continue
        found_list = True
        for item in items:
            if not isinstance(item, Mapping):
                continue
            item_id = str(item.get("id") or "").strip()
            if not item_id or item_id in seen:
                continue
            if not bool(item.get("checked", True)):
                continue
            seen.add(item_id)
            checked.append(item_id)
    if not found_list:
        return None
    return checked


def select_scripts_for_export(
    catalog: List[Mapping[str, Any]],
    *,
    entry_id: str = "",
    ui: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """决定实际打包哪些脚本：所有脚本列表 items 并集；无列表则打全目录。"""
    ordered: List[Dict[str, Any]] = []
    by_id: Dict[str, Mapping[str, Any]] = {}
    for entry in catalog or []:
        if not isinstance(entry, Mapping):
            continue
        sid = str(entry.get("id") or "").strip()
        if not sid or sid in by_id:
            continue
        by_id[sid] = entry
        ordered.append(dict(entry))
    if not ordered:
        return []

    entry_id = str(entry_id or "").strip() or default_entry_script_id(ui, ordered)
    item_ids = script_list_all_item_ids(ui)
    if item_ids is None:
        # 无脚本列表项：打包剔除后的全部目录
        wanted = {str(s.get("id") or "") for s in ordered}
    else:
        wanted = set(item_ids)
        if entry_id:
            wanted.add(entry_id)

    selected = [script for script in ordered if str(script.get("id") or "") in wanted]
    if not selected:
        fallback = by_id.get(entry_id) or ordered[0]
        selected = [dict(fallback)]
    return selected


def _prefix_messages(messages: List[str], script_title: str) -> List[str]:
    title = str(script_title or "").strip() or "脚本"
    return [f"[{title}] {msg}" for msg in messages if str(msg or "").strip()]


def collect_multi_script_package(
    catalog: List[Mapping[str, Any]],
    *,
    entry_id: str = "",
    images_dir: str = "",
    sounds_dir: str = "",
):
    """打包目录中的脚本；返回 (CollectionResult, scripts_meta)。"""
    from ui.export_parts.collector import CollectedAsset, collect_workflow_package

    if not catalog:
        raise RuntimeError("没有可导出的脚本")
    entry_id = str(entry_id or "").strip() or str(catalog[0].get("id") or "")
    entry = next((s for s in catalog if str(s.get("id") or "") == entry_id), catalog[0])
    entry_id = str(entry.get("id") or entry_id)
    entry_title = str(entry.get("title") or entry_id).strip() or entry_id

    main = collect_workflow_package(
        entry.get("workflow_data") or {},
        parent_workflow_file=str(entry.get("filepath") or ""),
        images_dir=images_dir,
        sounds_dir=sounds_dir,
    )
    main.errors[:] = _prefix_messages(list(main.errors or []), entry_title)
    main.warnings[:] = _prefix_messages(list(main.warnings or []), entry_title)
    used = {asset.package_relpath for asset in main.assets}
    script_meta: List[Dict[str, str]] = []

    for script in catalog:
        sid = str(script.get("id") or "").strip()
        if not sid:
            continue
        title = str(script.get("title") or sid).strip() or sid
        rel = f"workflows/scripts/{sid}.json"
        if sid == entry_id:
            workflow_data = main.workflow_data
        else:
            part = collect_workflow_package(
                script.get("workflow_data") or {},
                parent_workflow_file=str(script.get("filepath") or ""),
                images_dir=images_dir,
                sounds_dir=sounds_dir,
            )
            main.errors.extend(_prefix_messages(list(part.errors or []), title))
            main.warnings.extend(_prefix_messages(list(part.warnings or []), title))
            main.has_yolo = bool(main.has_yolo or part.has_yolo)
            for asset in part.assets:
                if asset.package_relpath in used:
                    continue
                used.add(asset.package_relpath)
                main.assets.append(asset)
            workflow_data = part.workflow_data
        if rel not in used:
            used.add(rel)
            main.assets.append(
                CollectedAsset(
                    kind="workflow",
                    source=str(script.get("filepath") or f"script://{sid}"),
                    package_relpath=rel,
                    workflow_data=copy.deepcopy(workflow_data),
                )
            )
        script_meta.append({"id": sid, "title": title, "path": rel})
    return main, script_meta
