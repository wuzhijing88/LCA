from pathlib import Path

from utils.plugin.runtime import launch_host_command

_HOST_CS = Path("build_assets/plugin_host/Program.cs")
_SPLIT_BIND_ERROR = "无法分离绑定: 大漠 BindWindowEx 不支持独立 input_hwnd"


def _csharp_method(text: str, signature: str) -> str:
    start = text.index(signature)
    brace = text.index("{", start)
    depth = 0
    for index, char in enumerate(text[brace:], brace):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError("unclosed method: " + signature)


def test_csproj_is_net472_x86():
    text = Path("build_assets/plugin_host/PluginHost.csproj").read_text(encoding="utf-8")
    assert "net472" in text
    assert "x86" in text
    assert "PluginHost" in text


def test_launch_args_are_pipe_only():
    cmd = launch_host_command(Path("PluginHost.exe"), "lca-plugin-1")
    assert cmd == ["PluginHost.exe", "--pipe", "lca-plugin-1"]


def test_split_hwnd_bind_fails_without_calling_bindwindowex():
    text = _HOST_CS.read_text(encoding="utf-8")
    dobind = _csharp_method(text, "static bool DoBind")
    assert _SPLIT_BIND_ERROR in dobind
    assert 'Invoke(dm, "BindWindowEx"' not in dobind
    assert "inputHwnd > 0" in dobind
    assert "inputHwnd != displayHwnd" in dobind or "displayHwnd != inputHwnd" in dobind


def test_get_screen_data_bmp_com_out_uses_null_and_requires_success():
    body = _csharp_method(_HOST_CS.read_text(encoding="utf-8"), "static byte[] GetScreenDataBmp")
    assert "x1, y1, x2, y2, null" in body
    assert "{ x1, y1, x2, y2, 0, 0 }" not in body
    assert body.index("IsSuccessInt") < body.index("CopyOutBytes")


def test_plugin_host_gitignore_ignores_bin_obj():
    text = Path("build_assets/plugin_host/.gitignore").read_text(encoding="utf-8")
    assert "bin/" in text
    assert "obj/" in text
