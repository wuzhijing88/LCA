import json

from app_core.user_data_migration import ensure_user_data_migrated


def test_user_data_migration_is_non_destructive_and_idempotent(tmp_path):
    app_root = tmp_path / "app"
    user_root = tmp_path / "user"
    app_root.mkdir()
    (app_root / "config.json").write_text('{"legacy": true}', encoding="utf-8")
    (app_root / "images").mkdir()
    (app_root / "images" / "one.png").write_bytes(b"image")

    first = ensure_user_data_migrated(app_root=app_root, user_data_root=user_root)
    second = ensure_user_data_migrated(app_root=app_root, user_data_root=user_root)

    assert "config.json" in first.copied
    assert (user_root / "config.json").read_text(encoding="utf-8") == '{"legacy": true}'
    assert (user_root / "images" / "one.png").read_bytes() == b"image"
    assert (app_root / "config.json").exists()
    assert second == first
    assert json.loads((user_root / ".migration.json").read_text(encoding="utf-8"))["version"] == 1


def test_migration_does_not_overwrite_newer_user_config(tmp_path):
    app_root = tmp_path / "app"
    user_root = tmp_path / "user"
    app_root.mkdir()
    user_root.mkdir()
    (app_root / "config.json").write_text('{"source": "legacy"}', encoding="utf-8")
    (user_root / "config.json").write_text('{"source": "current"}', encoding="utf-8")

    ensure_user_data_migrated(app_root=app_root, user_data_root=user_root)

    assert json.loads((user_root / "config.json").read_text(encoding="utf-8"))["source"] == "current"
