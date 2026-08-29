from __future__ import annotations

import json

import pytest

from app_core.lca_format import (
    LcaFormatError,
    is_lca_path,
    load_lca_project,
    save_lca_project,
    unseal_lca_bytes,
)


def test_save_load_rewrites_image_into_package(tmp_path):
    image_path = tmp_path / "shot.bmp"
    image_path.write_bytes(b"BMFAKE")
    workflow = {
        "cards": [
            {
                "id": 1,
                "task_type": "图像匹配点击",
                "parameters": {
                    "image_path": str(image_path),
                    "save_result_variable_name": "removed-on-save",
                },
            }
        ],
        "connections": [],
    }

    output_path = tmp_path / "demo.lca"
    saved_path = save_lca_project(output_path, workflow, display_name="demo")
    loaded, session = load_lca_project(saved_path)

    rewritten = loaded["cards"][0]["parameters"]["image_path"]
    assert rewritten.startswith("assets/images/")
    assert session.get_bytes(rewritten) == b"BMFAKE"
    assert "save_result_variable_name" not in loaded["cards"][0]["parameters"]

    manifest = json.loads(unseal_lca_bytes(saved_path.read_bytes())["manifest.json"])
    assert manifest["format"] == "lca_editor"
    assert manifest["entry_workflow"] == "workflows/main.json"
    assert manifest["name"] == "demo"


def test_save_rejects_missing_resource_and_lists_path(tmp_path):
    missing = tmp_path / "missing.bmp"
    workflow = {
        "cards": [
            {
                "id": 1,
                "task_type": "图像匹配点击",
                "parameters": {"image_path": str(missing)},
            }
        ],
        "connections": [],
    }

    with pytest.raises(LcaFormatError, match="missing[.]bmp"):
        save_lca_project(tmp_path / "bad.lca", workflow)


def test_save_resolves_relative_image_from_custom_gallery(tmp_path, monkeypatch):
    gallery = tmp_path / "custom_gallery"
    gallery.mkdir()
    image_path = gallery / "gallery-only.bmp"
    image_path.write_bytes(b"BM-GALLERY")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    workflow = {
        "metadata": {"custom_gallery_path": "custom_gallery"},
        "cards": [
            {
                "id": 1,
                "task_type": "图像匹配点击",
                "parameters": {"image_path": "images/gallery-only.bmp"},
            }
        ],
        "connections": [],
    }

    saved = save_lca_project(output_dir / "gallery.lca", workflow)
    loaded, session = load_lca_project(saved)

    packed_path = loaded["cards"][0]["parameters"]["image_path"]
    assert packed_path == "assets/images/gallery-only.bmp"
    assert session.get_bytes(packed_path) == b"BM-GALLERY"


def test_save_rejects_missing_drag_gif_resource(tmp_path):
    workflow = {
        "cards": [
            {
                "id": 1,
                "task_type": "模拟鼠标操作",
                "parameters": {"drag_start_image_path": "missing-start.gif"},
            }
        ],
        "connections": [],
    }

    with pytest.raises(LcaFormatError, match="missing-start[.]gif"):
        save_lca_project(tmp_path / "bad-drag.lca", workflow)


def test_save_packs_present_drag_gif_resource(tmp_path):
    image_path = tmp_path / "drag-start.gif"
    image_path.write_bytes(b"GIF89a-FAKE")
    workflow = {
        "cards": [
            {
                "id": 1,
                "task_type": "模拟鼠标操作",
                "parameters": {"drag_start_image_path": str(image_path)},
            }
        ],
        "connections": [],
    }

    saved = save_lca_project(tmp_path / "drag.lca", workflow)
    loaded, session = load_lca_project(saved)

    packed_path = loaded["cards"][0]["parameters"]["drag_start_image_path"]
    assert packed_path == "assets/images/drag-start.gif"
    assert session.get_bytes(packed_path) == b"GIF89a-FAKE"


def test_save_recursively_collects_json_sub_workflow(tmp_path):
    child_image = tmp_path / "child.bmp"
    child_image.write_bytes(b"BMCHILD")
    child_path = tmp_path / "child.json"
    child_path.write_text(
        json.dumps(
            {
                "cards": [
                    {
                        "id": 2,
                        "task_type": "图像匹配点击",
                        "parameters": {"image_path": str(child_image)},
                    }
                ],
                "connections": [],
            }
        ),
        encoding="utf-8",
    )
    workflow = {
        "cards": [
            {
                "id": 1,
                "task_type": "子工作流",
                "parameters": {"workflow_file": str(child_path)},
            }
        ],
        "connections": [],
    }

    saved = save_lca_project(tmp_path / "nested.lca", workflow)
    loaded, session = load_lca_project(saved)

    child_ref = loaded["cards"][0]["parameters"]["workflow_file"]
    assert child_ref.startswith("workflows/subs/")
    child = json.loads(session.get_bytes(child_ref))
    child_ref_image = child["cards"][0]["parameters"]["image_path"]
    assert session.get_bytes(child_ref_image) == b"BMCHILD"


def test_export_collector_reads_asset_from_lca_file(tmp_path):
    from ui.export_parts.collector import (
        collect_workflow_package,
        collection_to_memory_files,
    )

    image_path = tmp_path / "packed-only.bmp"
    image_path.write_bytes(b"BM-PACKED-ONLY")
    workflow = {
        "cards": [
            {
                "id": 1,
                "task_type": "图像匹配点击",
                "parameters": {"image_path": str(image_path)},
            }
        ],
        "connections": [],
    }

    saved = save_lca_project(tmp_path / "export-source.lca", workflow)
    loaded, _session = load_lca_project(saved)
    image_path.unlink()

    result = collect_workflow_package(
        loaded,
        parent_workflow_file=str(saved),
        images_dir=str(tmp_path / "empty-images"),
    )
    files = collection_to_memory_files(result)

    assert not result.errors
    assert files["assets/images/packed-only.bmp"] == b"BM-PACKED-ONLY"
    assert (
        result.workflow_data["cards"][0]["parameters"]["image_path"]
        == "memory://images/packed-only.bmp"
    )


def test_active_session_resolves_package_assets_to_readable_files():
    from pathlib import Path

    from app_core.lca_format.session import LcaPackageSession
    from task_workflow.sub_workflow_path import resolve_sub_workflow_path
    from utils.image_paths import ImagePathResolver

    ImagePathResolver.reset_instance()
    first = LcaPackageSession(
        {
            "assets/images/shared.bmp": b"FIRST",
            "workflows/subs/child.json": b'{"cards":[],"connections":[]}',
        }
    ).activate()
    resolver = ImagePathResolver()

    first_path = resolver.resolve("assets/images/shared.bmp")
    assert first_path is not None
    assert Path(first_path).read_bytes() == b"FIRST"
    assert resolver.resolve("memory://assets/images/shared.bmp") == first_path
    assert (
        resolve_sub_workflow_path("workflows/subs/child.json", "project.lca")
        == "memory://workflows/subs/child.json"
    )

    LcaPackageSession({"assets/images/shared.bmp": b"SECOND"}).activate()
    second_path = resolver.resolve("assets/images/shared.bmp")
    assert second_path is not None
    assert Path(second_path).read_bytes() == b"SECOND"
    assert second_path != first_path


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("demo.lca", True),
        ("DEMO.LCA", True),
        ("demo.json", False),
        ("", False),
    ],
)
def test_is_lca_path(path, expected):
    assert is_lca_path(path) is expected
