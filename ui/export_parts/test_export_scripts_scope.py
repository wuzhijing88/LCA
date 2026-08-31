import json
from types import SimpleNamespace

from ui.export_parts.collector import collect_workflow_package
from ui.export_parts.export_scripts import (
    apply_catalog_to_ui_exclusive,
    assert_script_lists_exclusive,
    collect_multi_script_package,
    default_entry_script_id,
    list_workspace_export_scripts,
    script_list_checked_ids,
    select_scripts_for_export,
    sync_script_list_items,
    unassigned_catalog_items,
    workspace_dirs_from_main,
)


def _write_workflow(path, *, name: str, cards=None):
    path.write_text(
        json.dumps(
            {
                "name": name,
                "cards": cards if cards is not None else [{"id": 1, "task_type": "延时"}],
                "connections": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_workspace_dirs_from_main_reads_parameter_panel():
    panel = SimpleNamespace(_favorite_workspaces=[r"D:\ws1", r"D:\ws2"])
    main = SimpleNamespace(parameter_panel=panel)
    assert workspace_dirs_from_main(main) == [r"D:\ws1", r"D:\ws2"]


def test_list_workspace_export_scripts_reads_disk_not_open_tabs(tmp_path):
    _write_workflow(tmp_path / "alpha.json", name="Alpha")
    _write_workflow(tmp_path / "beta.json", name="Beta")
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"name": "Empty", "cards": [], "connections": []}), encoding="utf-8")
    panel = SimpleNamespace(_favorite_workspaces=[str(tmp_path)])
    main = SimpleNamespace(parameter_panel=panel, task_manager=None, workflow_tab_widget=None)
    catalog = list_workspace_export_scripts(main)
    ids = {item["id"] for item in catalog}
    assert ids == {"alpha", "beta"}
    by_id = {item["id"]: item for item in catalog}
    assert by_id["alpha"]["title"] == "Alpha"
    assert by_id["alpha"]["workflow_data"].get("cards")
    assert all(item.get("filepath") for item in catalog)


def test_list_workspace_export_scripts_empty_without_workspace():
    main = SimpleNamespace(parameter_panel=SimpleNamespace(_favorite_workspaces=[]))
    assert list_workspace_export_scripts(main) == []


def test_empty_sub_workflow_error_includes_card_id():
    workflow = {
        "cards": [
            {
                "id": 42,
                "task_type": "子工作流",
                "parameters": {"workflow_file": ""},
            }
        ],
        "connections": [],
    }
    result = collect_workflow_package(workflow)
    assert any("卡片 #42" in err and "未填写工作流文件" in err for err in result.errors)


def test_select_scripts_defaults_to_full_catalog_when_no_script_list_items():
    catalog = [
        {"id": "a", "title": "A", "workflow_data": {"cards": [{"id": 1}]}},
        {"id": "b", "title": "B", "workflow_data": {"cards": [{"id": 2}]}},
    ]
    selected = select_scripts_for_export(catalog, entry_id="b", ui={"widgets": []})
    assert [item["id"] for item in selected] == ["a", "b"]
    assert script_list_checked_ids({"widgets": []}) is None


def test_select_scripts_unions_all_list_items_not_just_checked():
    catalog = [
        {"id": "a", "title": "A", "workflow_data": {"cards": [{"id": 1}]}},
        {"id": "b", "title": "B", "workflow_data": {"cards": [{"id": 2}]}},
        {"id": "c", "title": "C", "workflow_data": {"cards": [{"id": 3}]}},
    ]
    ui = {
        "widgets": [
            {
                "id": "L1",
                "type": "script_list",
                "items": [
                    {"id": "a", "title": "A", "checked": True},
                    {"id": "b", "title": "B", "checked": False},
                ],
            }
        ],
        "list_order": ["L1"],
    }
    selected = select_scripts_for_export(catalog, entry_id="a", ui=ui)
    assert [item["id"] for item in selected] == ["a", "b"]


def test_apply_catalog_appends_new_only_to_first_list():
    ui = {
        "widgets": [
            {
                "id": "L1",
                "type": "script_list",
                "title": "列表1",
                "items": [{"id": "a", "title": "A", "checked": True, "loops": 1}],
            },
            {
                "id": "L2",
                "type": "script_list",
                "title": "列表2",
                "items": [{"id": "b", "title": "B", "checked": True, "loops": 1}],
            },
        ],
        "list_order": ["L1", "L2"],
    }
    catalog = [
        {"id": "a", "title": "A"},
        {"id": "b", "title": "B"},
        {"id": "c", "title": "C"},
    ]
    out = apply_catalog_to_ui_exclusive(ui, catalog)
    lists = [w for w in out["widgets"] if w.get("type") == "script_list"]
    ids1 = {i["id"] for i in lists[0]["items"]}
    ids2 = {i["id"] for i in lists[1]["items"]}
    assert "c" in ids1 and "c" not in ids2
    assert ids1.isdisjoint(ids2)
    assert assert_script_lists_exclusive(out) is None
    assert default_entry_script_id(out, catalog) == "a"
    assert [x["id"] for x in unassigned_catalog_items(catalog, out)] == []


def test_assert_script_lists_exclusive_detects_duplicate():
    ui = {
        "widgets": [
            {"id": "L1", "type": "script_list", "title": "一", "items": [{"id": "a"}]},
            {"id": "L2", "type": "script_list", "title": "二", "items": [{"id": "a"}]},
        ]
    }
    msg = assert_script_lists_exclusive(ui)
    assert msg and "a" in msg


def test_collect_multi_prefixes_script_title_on_errors():
    catalog = [
        {
            "id": "main",
            "title": "主流程",
            "filepath": "",
            "workflow_data": {
                "cards": [
                    {
                        "id": 7,
                        "task_type": "子工作流",
                        "parameters": {},
                    }
                ],
                "connections": [],
            },
        }
    ]
    result, meta = collect_multi_script_package(catalog, entry_id="main")
    assert meta and meta[0]["id"] == "main"
    assert any(err.startswith("[主流程]") and "#7" in err for err in result.errors)


def test_sync_script_list_items_preserves_loops():
    catalog = [
        {"id": "a", "title": "日常"},
        {"id": "b", "title": "刷图"},
    ]
    items = sync_script_list_items(
        [{"id": "a", "title": "日常", "checked": True, "loops": 4}],
        catalog,
    )
    by_id = {item["id"]: item for item in items}
    assert by_id["a"]["loops"] == 4
    assert by_id["b"]["loops"] == 1
