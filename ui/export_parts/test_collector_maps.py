import numpy as np

from app_core.maps.record import create_map, format_map_option, save_map
from ui.export_parts.collector import collect_workflow_package


def test_collect_includes_map_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("LCA_USER_DATA_DIR", str(tmp_path))
    maps = tmp_path / "maps"
    record = create_map("包", np.zeros((8, 8, 3), dtype=np.uint8), goal=(2, 2), root=maps)
    save_map(record, root=maps)
    workflow = {
        "cards": [
            {
                "id": 1,
                "task_type": "A*寻路",
                "parameters": {
                    "map_option": format_map_option(record.map_id, "包"),
                    "death_image_paths": "",
                    "arrow_template_path": "",
                },
            }
        ],
        "connections": [],
    }
    result = collect_workflow_package(workflow)
    rels = [asset.package_relpath.replace("\\", "/") for asset in result.assets]
    assert any(path.startswith(f"assets/maps/{record.map_id}/") and path.endswith("manifest.json") for path in rels)


def test_collect_errors_when_map_directory_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("LCA_USER_DATA_DIR", str(tmp_path))
    workflow = {
        "cards": [
            {
                "id": 1,
                "task_type": "A*寻路",
                "parameters": {
                    "map_option": "缺 — missingid",
                    "death_image_paths": "",
                    "arrow_template_path": "",
                },
            }
        ],
        "connections": [],
    }
    result = collect_workflow_package(workflow)
    assert result.errors
    assert any("地图" in err for err in result.errors)
