from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Mapping, Optional, Sequence


_LAUNCHER_CS = r"""
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        try
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\', '/');
            string cfgPath = Path.Combine(baseDir, "launcher.cfg");
            if (!File.Exists(cfgPath))
            {
                MessageBox.Show("缺少 launcher.cfg，无法启动独立程序。", "启动失败",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }

            string executable = null;
            string workingDirectory = baseDir;
            var arguments = new List<string>();
            var environment = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

            foreach (string rawLine in File.ReadAllLines(cfgPath))
            {
                string line = (rawLine ?? string.Empty).Trim();
                if (line.Length == 0 || line.StartsWith("#") || line.StartsWith(";"))
                    continue;
                int sep = line.IndexOf('=');
                if (sep <= 0)
                    continue;
                string key = line.Substring(0, sep).Trim();
                string value = Expand(baseDir, line.Substring(sep + 1).Trim());
                if (key.Equals("exe", StringComparison.OrdinalIgnoreCase))
                    executable = value;
                else if (key.Equals("cwd", StringComparison.OrdinalIgnoreCase))
                    workingDirectory = string.IsNullOrWhiteSpace(value) ? baseDir : value;
                else if (key.Equals("arg", StringComparison.OrdinalIgnoreCase))
                    arguments.Add(value);
                else if (key.StartsWith("env:", StringComparison.OrdinalIgnoreCase))
                    environment[key.Substring(4)] = value;
            }

            if (string.IsNullOrWhiteSpace(executable))
            {
                MessageBox.Show("launcher.cfg 中未配置 exe。", "启动失败",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }
            if (!Path.IsPathRooted(executable))
                executable = Path.Combine(baseDir, executable);
            if (!File.Exists(executable))
            {
                MessageBox.Show("找不到运行时：\n" + executable, "启动失败",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }

            var psi = new ProcessStartInfo();
            psi.FileName = executable;
            psi.WorkingDirectory = workingDirectory;
            psi.UseShellExecute = false;
            psi.Arguments = QuoteArguments(arguments);
            foreach (var pair in environment)
                psi.EnvironmentVariables[pair.Key] = pair.Value;

            Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show(ex.Message, "启动失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static string Expand(string baseDir, string value)
    {
        if (string.IsNullOrEmpty(value))
            return value;
        return value.Replace("{BASE}", baseDir);
    }

    private static string QuoteArguments(IEnumerable<string> arguments)
    {
        var parts = new List<string>();
        foreach (string argument in arguments)
        {
            if (argument == null)
                continue;
            if (argument.Length == 0)
            {
                parts.Add("\"\"");
                continue;
            }
            bool needsQuotes = argument.IndexOfAny(new[] { ' ', '\t', '"' }) >= 0;
            if (!needsQuotes)
            {
                parts.Add(argument);
                continue;
            }
            parts.Add("\"" + argument.Replace("\"", "\\\"") + "\"");
        }
        return string.Join(" ", parts.ToArray());
    }
}
"""


def _find_csc() -> Optional[Path]:
    windir = Path(os.environ.get("WINDIR") or r"C:\Windows")
    candidates = (
        windir / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe",
        windir / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def write_launcher_cfg(
    cfg_path: Path,
    *,
    executable: str,
    arguments: Sequence[str],
    working_directory: str,
    environment: Optional[Mapping[str, str]] = None,
) -> None:
    lines = [
        f"exe={executable}",
        f"cwd={working_directory}",
    ]
    for key, value in (environment or {}).items():
        lines.append(f"env:{key}={value}")
    for argument in arguments:
        lines.append(f"arg={argument}")
    cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compile_launcher_exe(
    output_exe: Path,
    *,
    icon_path: str = "",
) -> Path:
    csc = _find_csc()
    if csc is None:
        raise RuntimeError("未找到 .NET csc.exe，无法生成独立程序启动器")

    output_exe = Path(output_exe)
    output_exe.parent.mkdir(parents=True, exist_ok=True)
    if output_exe.exists():
        output_exe.unlink()

    with tempfile.TemporaryDirectory(prefix="lca_launcher_") as temp_dir:
        source_path = Path(temp_dir) / "Launcher.cs"
        source_path.write_text(_LAUNCHER_CS, encoding="utf-8")
        command: List[str] = [
            str(csc),
            "/nologo",
            "/target:winexe",
            "/optimize+",
            f"/out:{output_exe}",
            "/r:System.Windows.Forms.dll",
            "/r:System.dll",
        ]
        if icon_path and os.path.isfile(icon_path):
            command.append(f"/win32icon:{icon_path}")
        command.append(str(source_path))
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0 or not output_exe.is_file():
            detail = (completed.stdout or "") + "\n" + (completed.stderr or "")
            raise RuntimeError(f"编译独立程序启动器失败:\n{detail.strip()}")
    return output_exe
