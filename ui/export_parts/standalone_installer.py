# -*- coding: utf-8 -*-
"""把独立程序 payload 目录打成 Inno Setup 安装包。"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[int, str], None]]

# 官方下载（不随 LCA 打包，避免增大体积）
INNO_SETUP_DOWNLOAD_PAGE = "https://jrsoftware.org/isdl.php"
INNO_SETUP_DOWNLOAD_EXE = (
    "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe"
)


class MissingInnoSetupError(RuntimeError):
    """本机未安装 Inno Setup 6（制作安装包的外部依赖）。"""


class MissingChineseLanguageError(RuntimeError):
    """Inno Setup 缺少简体中文语言包 ChineseSimplified.isl。"""


# 非官方翻译包说明（官方安装器默认不带中文）
INNO_CHINESE_LANG_HELP = (
    "https://jrsoftware.org/files/istrans/"
)


def _iscc_candidates() -> list[Path]:
    """收集可能的 ISCC 路径（环境变量 / 常见目录 / 各盘根目录 / 注册表）。"""
    found: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | str | None) -> None:
        if not path:
            return
        candidate = Path(os.path.expandvars(str(path))).expanduser()
        key = str(candidate).lower()
        if key in seen:
            return
        seen.add(key)
        found.append(candidate)

    env = str(os.environ.get("INNO_SETUP_ISCC") or os.environ.get("ISCC") or "").strip()
    add(env)

    for candidate in (
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        Path(r"D:\Inno Setup 6\ISCC.exe"),
        Path(r"E:\Inno Setup 6\ISCC.exe"),
    ):
        add(candidate)

    # 仅探测固定磁盘，避免 Path("A:/").exists() 在空光驱/软驱上卡住
    if os.name == "nt":
        try:
            import ctypes

            GetLogicalDrives = ctypes.windll.kernel32.GetLogicalDrives
            GetDriveTypeW = ctypes.windll.kernel32.GetDriveTypeW
            DRIVE_FIXED = 3
            mask = int(GetLogicalDrives())
            for index in range(26):
                if not (mask & (1 << index)):
                    continue
                root = f"{chr(ord('A') + index)}:\\"
                if int(GetDriveTypeW(root)) != DRIVE_FIXED:
                    continue
                add(Path(root) / "Inno Setup 6" / "ISCC.exe")
        except Exception:
            logger.debug("枚举固定磁盘查找 ISCC 失败", exc_info=True)

    which = shutil.which("ISCC") or shutil.which("ISCC.exe")
    add(which)

    if os.name == "nt":
        try:
            import winreg

            roots = (
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            )
            for hive, subkey in roots:
                try:
                    with winreg.OpenKey(hive, subkey) as key:
                        count = winreg.QueryInfoKey(key)[0]
                        for i in range(count):
                            try:
                                name = winreg.EnumKey(key, i)
                                with winreg.OpenKey(key, name) as item:
                                    display = str(winreg.QueryValueEx(item, "DisplayName")[0])
                                    if "Inno Setup 6" not in display:
                                        continue
                                    location = ""
                                    try:
                                        location = str(winreg.QueryValueEx(item, "InstallLocation")[0] or "")
                                    except OSError:
                                        location = ""
                                    if location:
                                        add(Path(location) / "ISCC.exe")
                                    try:
                                        uninstall = str(winreg.QueryValueEx(item, "UninstallString")[0] or "")
                                    except OSError:
                                        uninstall = ""
                                    if uninstall:
                                        # 形如 "D:\Inno Setup 6\unins000.exe"
                                        unins = Path(uninstall.strip().strip('"'))
                                        add(unins.parent / "ISCC.exe")
                            except OSError:
                                continue
                except OSError:
                    continue
        except Exception:
            logger.debug("查询 Inno Setup 注册表失败", exc_info=True)

    return found


def find_iscc() -> Optional[Path]:
    """仅查找本机已安装的 Inno Setup 6；不捆绑、不内嵌编译器。"""
    for candidate in _iscc_candidates():
        if candidate.is_file():
            return candidate
    return None


def require_iscc() -> Path:
    iscc = find_iscc()
    if iscc is not None:
        return iscc
    raise MissingInnoSetupError(
        "未检测到 Inno Setup 6，无法制作安装包。\n\n"
        "请先安装 Inno Setup 6，安装完成后再试。\n"
        "（Inno Setup 不随本程序打包，以免增大体积。）\n\n"
        f"下载页面：\n{INNO_SETUP_DOWNLOAD_PAGE}\n\n"
        f"安装包直链：\n{INNO_SETUP_DOWNLOAD_EXE}\n\n"
        "也可设置环境变量 INNO_SETUP_ISCC 指向 ISCC.exe。\n"
        "常见路径示例：\n"
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" + "\n"
        r"D:\Inno Setup 6\ISCC.exe"
    )


def chinese_simplified_isl_path(iscc: Path | None = None) -> Optional[Path]:
    """Inno Setup 安装目录下的简体中文语言文件。"""
    compiler = iscc or find_iscc()
    if compiler is None:
        return None
    candidate = compiler.parent / "Languages" / "ChineseSimplified.isl"
    return candidate if candidate.is_file() else None


def require_chinese_simplified_isl(iscc: Path) -> Path:
    path = chinese_simplified_isl_path(iscc)
    if path is not None:
        return path
    languages_dir = iscc.parent / "Languages"
    raise MissingChineseLanguageError(
        "本机 Inno Setup 缺少简体中文语言包，无法制作中文安装向导。\n\n"
        "请下载 ChineseSimplified.isl，放到下面目录后再试：\n"
        f"{languages_dir}\n\n"
        f"语言包下载：\n{INNO_CHINESE_LANG_HELP}\n\n"
        "（在页面中找到 Chinese Simplified，下载后把文件重命名/保存为 ChineseSimplified.isl）"
    )


def _is_missing_chinese_language_error(detail: str) -> bool:
    text = str(detail or "")
    lowered = text.lower()
    return "chinesesimplified.isl" in lowered or (
        "chinese" in lowered
        and ".isl" in lowered
        and (
            "找不到" in text
            or "couldn’t open" in lowered
            or "couldn't open" in lowered
            or "cannot open" in lowered
        )
    )


def _summarize_iscc_error(detail: str, *, max_lines: int = 8) -> str:
    """从 ISCC 冗长输出中抽出末尾关键错误行，避免整段编译日志弹窗。"""
    lines = [ln.strip() for ln in str(detail or "").splitlines() if ln.strip()]
    if not lines:
        return "（无详细输出）"
    interesting = [
        ln
        for ln in lines
        if ln.lower().startswith("error")
        or "error on line" in ln.lower()
        or "compile aborted" in ln.lower()
        or "找不到" in ln
        or "failed" in ln.lower()
    ]
    picked = interesting[-max_lines:] if interesting else lines[-max_lines:]
    return "\n".join(picked)


def _iss_escape(value: str) -> str:
    return str(value or "").replace('"', "")


def stage_setup_icon(icon_path: str, dest_dir: Path) -> str:
    """
    把图标拷到 ISS 同目录下的 setup.ico。
    安装包脚本只用相对名，避免中文/空格绝对路径导致 SetupIconFile 失效。
    """
    source = Path(str(icon_path or "").strip())
    if not source.is_file():
        return ""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / "setup.ico"
    shutil.copy2(source, target)
    return "setup.ico" if target.is_file() else ""


def build_setup_iss_text(
    *,
    display_name: str,
    safe_exe: str,
    publisher: str,
    version: str,
    output_dir: str,
    output_base: str,
    payload_dir: str,
    setup_icon_relative: str = "",
) -> str:
    app_id = "A1B2C3D4-E5F6-7890-ABCD-" + "".join(
        f"{ord(c):02X}" for c in output_base[:6]
    ).ljust(12, "0")[:12]
    # 应用与功能 / 快捷方式统一用安装目录内落地的 icon.ico，不依赖从 exe 抽图标
    uninstall_icon = "{app}\\icon.ico"
    icon_line = f"SetupIconFile={setup_icon_relative}" if setup_icon_relative else ""
    # 使用三单引号：Inno 参数里的 ""{app}""" 含 """，会截断三双引号字符串
    # 入口身份已写入 exe；--package 只帮助定位同目录数据包
    player_params = '--package ""{app}""'
    return f'''; Auto-generated standalone player installer
#define MyAppName "{_iss_escape(display_name)}"
#define MyAppExeName "{_iss_escape(safe_exe)}"
#define MyAppPublisher "{_iss_escape(publisher or 'LCA')}"
#define MyAppVersion "{_iss_escape(version or '1.0.0')}"

[Setup]
AppId={{{{{app_id}}}}}
AppName={{#MyAppName}}
AppVersion={{#MyAppVersion}}
AppVerName={{#MyAppName}} {{#MyAppVersion}}
AppPublisher={{#MyAppPublisher}}
DefaultDirName={{autopf}}\\{{#MyAppName}}
DefaultGroupName={{#MyAppName}}
DisableProgramGroupPage=yes
OutputDir={_iss_escape(str(output_dir))}
OutputBaseFilename={_iss_escape(output_base)}
Compression=lzma2
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=2
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UninstallDisplayIcon={uninstall_icon}
{icon_line}
VersionInfoVersion=1.0.0.0
VersionInfoCompany={{#MyAppPublisher}}
VersionInfoDescription={{#MyAppName}} 安装程序
VersionInfoProductName={{#MyAppName}}

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"

[Files]
Source: "{_iss_escape(str(payload_dir))}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"; Parameters: "{player_params}"; IconFilename: "{{app}}\\icon.ico"
Name: "{{group}}\\卸载 {{#MyAppName}}"; Filename: "{{uninstallexe}}"; IconFilename: "{{app}}\\icon.ico"
Name: "{{autodesktop}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"; Parameters: "{player_params}"; Tasks: desktopicon; IconFilename: "{{app}}\\icon.ico"

[Run]
; 播放器 exe 带 requireAdministrator：必须用 shellexec（ShellExecute）。
; 仅 CreateProcess 会报错误 740「请求的操作需要提升」。
; 不使用 runascurrentuser，以便沿用安装程序已提升的管理员令牌，避免二次 UAC 失败。
Filename: "{{app}}\\{{#MyAppExeName}}"; Parameters: "{player_params}"; Description: "安装完成后运行 {{#MyAppName}}"; Flags: nowait postinstall skipifsilent shellexec
'''


@dataclass
class IsccResult:
    returncode: int
    stdout: str
    stderr: str = ""


def _report_iscc_progress(progress: ProgressCallback, value: int, message: str) -> None:
    if progress is None:
        return
    try:
        progress(int(value), str(message or ""))
    except Exception:
        logger.debug("ISCC 进度回调失败", exc_info=True)


def run_iscc(
    iscc: Path,
    iss_path: Path,
    *,
    progress: ProgressCallback = None,
    poll_seconds: float = 2.0,
    extra_args: Sequence[str] | None = None,
    progress_value: int = 82,
) -> IsccResult:
    """运行 ISCC，输出写入日志文件，避免 capture_output 管道堵满假死。"""
    iss_path = Path(iss_path)
    log_path = iss_path.with_suffix(".iscc.log")
    cmd = [str(iscc)]
    if extra_args:
        cmd.extend(str(arg) for arg in extra_args)
    else:
        cmd.append(str(iss_path))

    started = time.monotonic()
    _report_iscc_progress(
        progress,
        progress_value,
        "正在压缩安装包（Inno Setup，首次可能需数分钟）…",
    )

    with open(log_path, "w", encoding="utf-8", errors="replace") as log_file:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(iss_path.parent),
        )
        while True:
            try:
                returncode = proc.wait(timeout=max(0.01, float(poll_seconds)))
                break
            except subprocess.TimeoutExpired:
                elapsed = int(time.monotonic() - started)
                _report_iscc_progress(
                    progress,
                    progress_value,
                    f"正在压缩安装包（Inno Setup，已用时 {elapsed} 秒，请耐心等待）…",
                )

    detail = ""
    try:
        detail = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        detail = ""
    try:
        log_path.unlink(missing_ok=True)
    except OSError:
        pass

    if returncode is None:
        returncode = int(proc.returncode or 0)
    return IsccResult(returncode=int(returncode), stdout=detail, stderr="")


def build_standalone_installer(
    *,
    payload_dir: Path,
    output_dir: Path,
    app_name: str,
    exe_name: str,
    icon_path: str = "",
    version: str = "1.0.0",
    publisher: str = "LCA",
    progress: ProgressCallback = None,
) -> Path:
    """
    编译安装包，返回 Setup.exe 路径。
    payload_dir: 已放好 设计名.exe / package.lcap / 依赖 DLL 的目录。
    依赖本机已安装的 Inno Setup 6，不自带编译器。
    """
    iscc = require_iscc()
    require_chinese_simplified_isl(iscc)

    payload_dir = Path(payload_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    display_name = str(app_name or "独立程序").strip() or "独立程序"
    safe_exe = str(exe_name or "").strip()
    if not safe_exe.lower().endswith(".exe"):
        safe_exe = f"{safe_exe}.exe"
    exe_path = payload_dir / safe_exe
    if not exe_path.is_file():
        raise FileNotFoundError(f"安装包源目录缺少主程序: {exe_path}")

    ico = Path(icon_path) if icon_path else None
    if ico is None or not ico.is_file():
        # 回退：工程默认图标
        from utils.app_paths import get_resource_path

        fallback = Path(get_resource_path("icon.ico"))
        ico = fallback if fallback.is_file() else None
        if icon_path and str(icon_path).strip():
            logger.warning("安装包图标不存在，回退默认图标: %s", icon_path)

    output_base = "".join(ch for ch in display_name if ch not in '<>:"/\\|?*').strip() or "独立程序"
    output_base = f"{output_base}_Setup"

    with tempfile.TemporaryDirectory(prefix="lca_standalone_iss_") as temp_dir:
        temp_root = Path(temp_dir)
        setup_icon_relative = stage_setup_icon(str(ico) if ico else "", temp_root)
        if ico and ico.is_file() and not setup_icon_relative:
            logger.warning("无法暂存安装包图标，Setup.exe 可能显示默认图标: %s", ico)
        iss_text = build_setup_iss_text(
            display_name=display_name,
            safe_exe=safe_exe,
            publisher=publisher or "LCA",
            version=version or "1.0.0",
            output_dir=str(output_dir),
            output_base=output_base,
            payload_dir=str(payload_dir),
            setup_icon_relative=setup_icon_relative,
        )
        iss_path = temp_root / "standalone.iss"
        # Inno 中文脚本建议 UTF-8 BOM
        iss_path.write_bytes(b"\xef\xbb\xbf" + iss_text.encode("utf-8"))
        if setup_icon_relative:
            logger.info("安装包图标: %s -> %s", ico, temp_root / setup_icon_relative)
        completed = run_iscc(iscc, iss_path, progress=progress)
        if completed.returncode != 0:
            detail = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
            if _is_missing_chinese_language_error(detail):
                require_chinese_simplified_isl(iscc)
            raise RuntimeError(
                "编译安装包失败。\n\n"
                "请检查 Inno Setup 是否完整安装，或查看下方简要信息。\n"
                f"{_summarize_iscc_error(detail)}"
            )

    setup_path = output_dir / f"{output_base}.exe"
    if not setup_path.is_file():
        # 偶发 OutputBaseFilename 规范化差异，回退扫描
        candidates = sorted(output_dir.glob("*_Setup.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            setup_path = candidates[0]
        else:
            raise FileNotFoundError(f"未生成安装包: {output_dir / (output_base + '.exe')}")
    logger.info("独立程序安装包已生成: %s", setup_path)
    return setup_path
