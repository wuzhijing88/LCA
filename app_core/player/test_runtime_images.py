from pathlib import Path

from app_core.player import runtime_images
from app_core.player.memory_store import (
    clear_player_memory_store,
    get_player_memory_file,
    load_files_into_memory,
    put_player_memory_file,
)
from app_core.player.runtime_images import (
    ensure_player_image_memory,
    materialize_player_sounds,
    resolve_get_image_data,
)
from task_workflow.media_player import resolve_media_path


def setup_function():
    clear_player_memory_store()


def teardown_function():
    clear_player_memory_store()


def test_resolve_get_image_data_none_without_store():
    assert resolve_get_image_data({}) is None


def test_resolve_get_image_data_uses_memory_store():
    put_player_memory_file("images/离线版测试_12.bmp", b"bmp-bytes")
    loader = resolve_get_image_data({})
    assert loader is not None
    assert loader("memory://images/离线版测试_12.bmp") == b"bmp-bytes"
    assert get_player_memory_file("images/离线版测试_12.bmp") == b"bmp-bytes"


def test_resolve_get_image_data_keeps_explicit_callback():
    put_player_memory_file("images/a.bmp", b"stored")

    def custom(_uri):
        return b"custom"

    assert resolve_get_image_data({"get_image_data": custom}) is custom


def test_ensure_player_image_memory_installs_existing_store():
    put_player_memory_file("images/x.bmp", b"x")
    assert ensure_player_image_memory() is True
    from utils.match.template_preloader import get_memory_image_provider

    provider = get_memory_image_provider()
    assert callable(provider)
    assert provider("memory://images/x.bmp") == b"x"


def test_materialize_player_sounds_makes_basename_playable(tmp_path, monkeypatch):
    put_player_memory_file("assets/sounds/提示音.wav", b"RIFF....WAVE")
    userdata = tmp_path / "userdata"
    count = materialize_player_sounds(str(userdata))
    assert count == 1
    target = userdata / "sounds" / "提示音.wav"
    assert target.is_file()
    assert target.read_bytes() == b"RIFF....WAVE"
    monkeypatch.setenv("LCA_USER_DATA_DIR", str(userdata))
    resolved = resolve_media_path("提示音.wav")
    assert resolved
    assert Path(resolved).read_bytes() == b"RIFF....WAVE"


def test_materialize_player_maps_preserves_map_directory(tmp_path):
    load_files_into_memory(
        {
            "assets/maps/ab/manifest.json": b'{"map_id":"ab"}',
            "assets/maps/ab/map.png": b"png-bytes",
        }
    )
    assert get_player_memory_file("maps/ab/map.png") == b"png-bytes"
    userdata = tmp_path / "userdata"

    count = runtime_images.materialize_player_maps(str(userdata))

    assert count == 2
    assert (userdata / "maps" / "ab" / "map.png").read_bytes() == b"png-bytes"


def test_materialize_player_maps_rejects_parent_path(tmp_path):
    put_player_memory_file("assets/maps/../outside.txt", b"outside")
    userdata = tmp_path / "userdata"

    assert runtime_images.materialize_player_maps(str(userdata)) == 0
    assert not (userdata / "outside.txt").exists()
