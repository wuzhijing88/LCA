from pathlib import Path

from utils.plugin.runtime import launch_host_command


def test_csproj_is_net472_x86():
    text = Path("build_assets/plugin_host/PluginHost.csproj").read_text(encoding="utf-8")
    assert "net472" in text
    assert "x86" in text
    assert "PluginHost" in text


def test_launch_args_are_pipe_only():
    cmd = launch_host_command(Path("PluginHost.exe"), "lca-plugin-1")
    assert cmd == ["PluginHost.exe", "--pipe", "lca-plugin-1"]
