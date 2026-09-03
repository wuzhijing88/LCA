"""多脚本列表：列表顺序 / 项顺序 / 随机。"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence


def _norm_mode(raw: Any) -> str:
    mode = str(raw or "fixed").strip().lower()
    return mode if mode in ("fixed", "random") else "fixed"


def resolve_list_order(ui: Optional[Mapping[str, Any]], state: Optional[Mapping[str, Any]] = None) -> List[str]:
    """返回 script_list widget id 顺序。"""
    ui = ui if isinstance(ui, Mapping) else {}
    state = state if isinstance(state, Mapping) else {}
    widgets = [
        w
        for w in (ui.get("widgets") or [])
        if isinstance(w, Mapping) and str(w.get("type") or "") == "script_list"
    ]
    by_id = {str(w.get("id") or "").strip(): w for w in widgets if str(w.get("id") or "").strip()}
    order: List[str] = []
    state_order = state.get("list_order")
    if isinstance(state_order, list) and state_order:
        source = state_order
    else:
        source = ui.get("list_order") if isinstance(ui.get("list_order"), list) else []
    for raw in source or []:
        sid = str(raw or "").strip()
        if sid and sid in by_id and sid not in order:
            order.append(sid)
    for sid in by_id:
        if sid not in order:
            order.append(sid)
    # 无 id 的列表用稳定占位
    for index, widget in enumerate(widgets):
        sid = str(widget.get("id") or "").strip()
        if not sid:
            order.append(f"__anon_{index}")
    return order


def resolve_list_order_mode(ui: Optional[Mapping[str, Any]], state: Optional[Mapping[str, Any]] = None) -> str:
    state = state if isinstance(state, Mapping) else {}
    if state.get("list_order_mode"):
        return _norm_mode(state.get("list_order_mode"))
    ui = ui if isinstance(ui, Mapping) else {}
    return _norm_mode(ui.get("list_order_mode"))


def resolve_item_order_mode(
    list_id: str,
    widget: Optional[Mapping[str, Any]],
    state: Optional[Mapping[str, Any]] = None,
) -> str:
    state = state if isinstance(state, Mapping) else {}
    modes = state.get("list_order_modes")
    if isinstance(modes, Mapping) and list_id in modes:
        return _norm_mode(modes.get(list_id))
    widget = widget if isinstance(widget, Mapping) else {}
    return _norm_mode(widget.get("order_mode"))


def ordered_ids(
    ids: Sequence[str],
    *,
    mode: str = "fixed",
    preferred: Optional[Sequence[str]] = None,
    rng: Optional[random.Random] = None,
) -> List[str]:
    """按固定顺序或随机排列 id；preferred 可覆盖默认顺序（仍只保留 ids 内成员）。"""
    base = [str(x).strip() for x in ids if str(x).strip()]
    if not base:
        return []
    if preferred:
        ordered: List[str] = []
        seen = set()
        for sid in preferred:
            s = str(sid or "").strip()
            if s in base and s not in seen:
                ordered.append(s)
                seen.add(s)
        for s in base:
            if s not in seen:
                ordered.append(s)
        base = ordered
    if _norm_mode(mode) == "random":
        out = list(base)
        (rng or random.Random()).shuffle(out)
        return out
    return list(base)


def build_run_queue_parts(
    ui: Optional[Mapping[str, Any]],
    *,
    selected_by_list: Mapping[str, Sequence[str]],
    scripts: Mapping[str, Any],
    state: Optional[Mapping[str, Any]] = None,
    loops_by_id: Optional[Mapping[str, int]] = None,
    group_loops_by_list: Optional[Mapping[str, int]] = None,
    rng: Optional[random.Random] = None,
) -> List[tuple]:
    """按列表顺序展开多段队列。

    selected_by_list: list_id -> checked script ids（当前 UI 顺序）。
    返回 expand 后的 (script_id, workflow_data, loop_index, loop_total) 列表。
    """
    from app_core.player.package import expand_script_run_queue, normalize_script_loop_count

    ui = ui if isinstance(ui, Mapping) else {}
    state = state if isinstance(state, Mapping) else {}
    widgets = {
        str(w.get("id") or "").strip(): w
        for w in (ui.get("widgets") or [])
        if isinstance(w, Mapping) and str(w.get("type") or "") == "script_list"
    }
    list_ids = resolve_list_order(ui, state)
    list_mode = resolve_list_order_mode(ui, state)
    list_ids = ordered_ids(list_ids, mode=list_mode, rng=rng)

    item_orders = state.get("list_item_order") if isinstance(state.get("list_item_order"), Mapping) else {}
    queue: List[tuple] = []
    for list_id in list_ids:
        widget = widgets.get(list_id) or {}
        selected = [str(x).strip() for x in (selected_by_list.get(list_id) or []) if str(x).strip()]
        if not selected:
            continue
        preferred = item_orders.get(list_id) if isinstance(item_orders, Mapping) else None
        mode = resolve_item_order_mode(list_id, widget, state)
        ids = ordered_ids(selected, mode=mode, preferred=preferred, rng=rng)
        pairs = []
        for sid in ids:
            data = scripts.get(sid)
            if isinstance(data, dict) and data:
                pairs.append((sid, data))
        if not pairs:
            continue
        # The standalone player lets users change loop counts at runtime.  Those
        # values live in the widgets, not in the immutable exported UI payload;
        # callers pass them explicitly so a run uses the current controls.
        runtime_group_loops = None
        if isinstance(group_loops_by_list, Mapping):
            if list_id in group_loops_by_list:
                runtime_group_loops = group_loops_by_list.get(list_id)
            elif "__main__" in group_loops_by_list and len(list_ids) == 1:
                runtime_group_loops = group_loops_by_list.get("__main__")
        group_loops = normalize_script_loop_count(
            runtime_group_loops if runtime_group_loops is not None else widget.get("group_loops"),
            1,
        )
        queue.extend(
            expand_script_run_queue(
                pairs,
                loops_by_id=loops_by_id or {},
                group_loops=group_loops,
            )
        )
    return queue
