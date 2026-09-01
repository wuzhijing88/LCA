from pathlib import Path

from build_assets.packaging.run_nuitka_main_build import (
    LOCAL_INCLUDE_PACKAGES,
    _build_command,
)


def _stub_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    for package_name in LOCAL_INCLUDE_PACKAGES:
        package_root = project.joinpath(*package_name.split("."))
        package_root.mkdir(parents=True)
        (package_root / "__init__.py").write_text("", encoding="utf-8")
    return project


def test_build_command_includes_plugin_dir_from_project_root(tmp_path, monkeypatch):
    project = _stub_project(tmp_path)
    (project / "tools" / "plugin").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    command = _build_command(project, str(tmp_path / "out"))
    assert "--include-data-dir=tools/plugin=tools/plugin" in command


def test_build_command_skips_missing_plugin_dir(tmp_path, monkeypatch):
    project = _stub_project(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    command = _build_command(project, str(tmp_path / "out"))
    assert not any("tools/plugin" in part for part in command)
