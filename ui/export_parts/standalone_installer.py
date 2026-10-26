# -*- coding: utf-8 -*-
"""把独立程序 payload 目录打成 Inno Setup 安装包。"""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[int, str], None]]


class ExportCancelled(RuntimeError):
    """用户取消制作独立程序。"""

# 官方下载（不随 LCA 打包，避免增大体积）
INNO_SETUP_DOWNLOAD_PAGE = "https://jrsoftware.org/isdl.php"
# 脚本使用 x64compatible，该指令自 Inno Setup 6.3 起才可用
MIN_ISCC_VERSION = (6, 3, 0, 0)


class MissingInnoSetupError(RuntimeError):
    """本机未安装 Inno Setup（制作安装包的外部依赖）。"""


class OutdatedInnoSetupError(RuntimeError):
    """本机 Inno Setup 版本过低或无法确认（需要 6.3 或更高）。"""


class MissingChineseLanguageError(RuntimeError):
    """Inno Setup 缺少简体中文语言包 ChineseSimplified.isl。"""


# 非官方翻译包说明（官方安装器默认不带中文）
INNO_CHINESE_LANG_HELP = (
    "https://jrsoftware.org/files/istrans/"
)


class _VSFixedFileInfo(ctypes.Structure):
    _fields_ = (
        ("dwSignature", wintypes.DWORD),
        ("dwStrucVersion", wintypes.DWORD),
        ("dwFileVersionMS", wintypes.DWORD),
        ("dwFileVersionLS", wintypes.DWORD),
        ("dwProductVersionMS", wintypes.DWORD),
        ("dwProductVersionLS", wintypes.DWORD),
        ("dwFileFlagsMask", wintypes.DWORD),
        ("dwFileFlags", wintypes.DWORD),
        ("dwFileOS", wintypes.DWORD),
        ("dwFileType", wintypes.DWORD),
        ("dwFileSubtype", wintypes.DWORD),
        ("dwFileDateMS", wintypes.DWORD),
        ("dwFileDateLS", wintypes.DWORD),
    )


def _is_inno_setup_display_name(display: str) -> bool:
    return "inno setup" in str(display or "").lower()


def _iscc_paths_under(root: Path) -> list[Path]:
    try:
        base = Path(root)
        if not base.is_dir():
            return []
        return list(base.glob("Inno Setup */ISCC.exe"))
    except OSError:
        return []


def _normalize_iscc_version(
    version: Optional[tuple[int, ...]],
) -> Optional[tuple[int, int, int, int]]:
    if version is None:
        return None
    try:
        parts = [int(part) for part in version]
    except (TypeError, ValueError):
        return None
    if not parts or parts[0] <= 0:
        return None
    if len(parts) < 4:
        parts.extend([0] * (4 - len(parts)))
    return (parts[0], parts[1], parts[2], parts[3])


def _parse_version_text(text: str) -> Optional[tuple[int, int, int, int]]:
    parts: list[int] = []
    current = ""
    for ch in str(text or ""):
        if ch.isdigit():
            current += ch
            continue
        if current:
            parts.append(int(current))
            current = ""
            if ch != ".":
                break
        elif parts:
            break
    if current:
        parts.append(int(current))
    return _normalize_iscc_version(tuple(parts) if parts else None)


def _parse_engine_version_output(output: str) -> Optional[tuple[int, int, int, int]]:
    for raw in str(output or "").splitlines():
        line = raw.strip()
        if line.lower().startswith("compiler engine version:"):
            return _parse_version_text(line)
    return None


def _hi_lo_version(ms: int, ls: int) -> Optional[tuple[int, int, int, int]]:
    return _normalize_iscc_version(
        (
            (int(ms) >> 16) & 0xFFFF,
            int(ms) & 0xFFFF,
            (int(ls) >> 16) & 0xFFFF,
            int(ls) & 0xFFFF,
        )
    )


def _is_usable_iscc_version(version: Optional[tuple[int, ...]]) -> bool:
    normalized = _normalize_iscc_version(version)
    return normalized is not None and normalized >= MIN_ISCC_VERSION


def _format_iscc_version(version: Optional[tuple[int, ...]]) -> str:
    normalized = _normalize_iscc_version(version)
    if normalized is None:
        return "无法确认"
    return ".".join(str(part) for part in normalized)


def _read_iscc_pe_version(path: Path) -> Optional[tuple[int, int, int, int]]:
    if os.name != "nt":
        return None
    try:
        candidate = Path(path)
        if not candidate.is_file():
            return None
    except OSError:
        return None
    try:
        version_dll = ctypes.WinDLL("version", use_last_error=True)
        get_size = version_dll.GetFileVersionInfoSizeW
        get_size.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD))
        get_size.restype = wintypes.DWORD
        get_info = version_dll.GetFileVersionInfoW
        get_info.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
        )
        get_info.restype = wintypes.BOOL
        query = version_dll.VerQueryValueW
        query.argtypes = (
            wintypes.LPCVOID,
            wintypes.LPCWSTR,
            ctypes.POINTER(wintypes.LPVOID),
            ctypes.POINTER(wintypes.UINT),
        )
        query.restype = wintypes.BOOL

        ignored = wintypes.DWORD()
        size = get_size(str(candidate), ctypes.byref(ignored))
        if not size:
            return None
        buffer = ctypes.create_string_buffer(size)
        if not get_info(str(candidate), 0, size, buffer):
            return None
        pointer = wintypes.LPVOID()
        length = wintypes.UINT()
        if not query(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return None
        if length.value < ctypes.sizeof(_VSFixedFileInfo):
            return None
        info = ctypes.cast(pointer, ctypes.POINTER(_VSFixedFileInfo)).contents
        if info.dwSignature != 0xFEEF04BD:
            return None
        file_version = _hi_lo_version(info.dwFileVersionMS, info.dwFileVersionLS)
        if file_version is not None:
            return file_version
        return _hi_lo_version(info.dwProductVersionMS, info.dwProductVersionLS)
    except (AttributeError, OSError, ValueError):
        return None


def _install_dir_of(path: Path) -> Optional[Path]:
    try:
        resolved = Path(path).resolve()
        return resolved.parent if resolved.is_file() else resolved
    except OSError:
        return None


def _same_install_dir(iscc: Path, location: str) -> bool:
    install_dir = _install_dir_of(iscc)
    other = _expand_iscc_path(location.strip().strip('"'))
    if install_dir is None or other is None:
        return False
    other_dir = _install_dir_of(other)
    if other_dir is None:
        return False
    return os.path.normcase(str(install_dir)) == os.path.normcase(str(other_dir))


def _iter_inno_uninstall_entries():
    if os.name != "nt":
        return
    try:
        import winreg
    except ImportError:
        return
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
                            try:
                                display = str(winreg.QueryValueEx(item, "DisplayName")[0])
                            except OSError:
                                continue
                            if not _is_inno_setup_display_name(display):
                                continue

                            def _value(value_name: str) -> str:
                                try:
                                    return str(winreg.QueryValueEx(item, value_name)[0] or "")
                                except OSError:
                                    return ""

                            yield {
                                "display": display,
                                "version": _value("DisplayVersion"),
                                "location": _value("InstallLocation"),
                                "uninstall": _value("UninstallString"),
                            }
                    except OSError:
                        continue
        except OSError:
            continue


def _read_iscc_registry_version(path: Path) -> Optional[tuple[int, int, int, int]]:
    try:
        candidate = Path(path)
    except TypeError:
        return None
    for entry in _iter_inno_uninstall_entries():
        location = str(entry.get("location") or "")
        uninstall = str(entry.get("uninstall") or "")
        if location and _same_install_dir(candidate, location):
            parsed = _parse_version_text(str(entry.get("version") or ""))
            if parsed is not None:
                return parsed
        if uninstall and _same_install_dir(candidate, uninstall):
            parsed = _parse_version_text(str(entry.get("version") or ""))
            if parsed is not None:
                return parsed
    return None


def _read_iscc_engine_version(path: Path) -> Optional[tuple[int, int, int, int]]:
    try:
        candidate = Path(path)
        if not candidate.is_file():
            return None
    except OSError:
        return None
    script = None
    try:
        handle, script = tempfile.mkstemp(prefix="lca_iscc_ver_", suffix=".iss")
        os.close(handle)
        Path(script).write_text("#error LCA_ISCC_PROBE\n", encoding="utf-8")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        completed = subprocess.run(
            [str(candidate), script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=flags,
        )
        output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    finally:
        if script:
            try:
                os.remove(script)
            except OSError:
                pass
    return _parse_engine_version_output(output)


def _read_iscc_file_version(path: Path) -> Optional[tuple[int, int, int, int]]:
    for reader in (
        _read_iscc_pe_version,
        _read_iscc_registry_version,
        _read_iscc_engine_version,
    ):
        version = _normalize_iscc_version(reader(path))
        if version is not None:
            return version
    return None


def _expand_iscc_path(path: Path | str | None) -> Optional[Path]:
    if not path:
        return None
    text = str(path).strip()
    if not text:
        return None
    return Path(os.path.expandvars(text)).expanduser()


def _configured_iscc_path() -> Optional[Path]:
    raw = str(os.environ.get("INNO_SETUP_ISCC") or "").strip()
    return _expand_iscc_path(raw)


def _program_files_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | str | None) -> None:
        candidate = _expand_iscc_path(path)
        if candidate is None:
            return
        key = str(candidate).lower()
        if key in seen:
            return
        seen.add(key)
        roots.append(candidate)

    add(os.environ.get("ProgramFiles"))
    add(os.environ.get("ProgramFiles(x86)"))
    add(r"C:\Program Files")
    add(r"C:\Program Files (x86)")
    return roots


def _fixed_drive_roots() -> list[Path]:
    # 仅探测固定磁盘，避免 Path("A:/").exists() 在空光驱/软驱上卡住
    if os.name != "nt":
        return []
    try:
        get_logical_drives = ctypes.windll.kernel32.GetLogicalDrives
        get_drive_type_w = ctypes.windll.kernel32.GetDriveTypeW
        drive_fixed = 3
        mask = int(get_logical_drives())
        roots: list[Path] = []
        for index in range(26):
            if not (mask & (1 << index)):
                continue
            root = f"{chr(ord('A') + index)}:\\"
            if int(get_drive_type_w(root)) != drive_fixed:
                continue
            roots.append(Path(root))
        return roots
    except Exception:
        logger.debug("枚举固定磁盘查找 ISCC 失败", exc_info=True)
        return []


def _registry_iscc_candidates() -> list[Path]:
    found: list[Path] = []
    try:
        for entry in _iter_inno_uninstall_entries():
            location = str(entry.get("location") or "")
            if location:
                found.append(Path(location) / "ISCC.exe")
            uninstall = str(entry.get("uninstall") or "")
            if uninstall:
                unins = Path(uninstall.strip().strip('"'))
                found.append(unins.parent / "ISCC.exe")
    except Exception:
        logger.debug("查询 Inno Setup 注册表失败", exc_info=True)
    return found


def _iscc_candidates() -> list[Path]:
    """收集可能的 ISCC 路径（环境变量 / 常见目录 / 各盘根目录 / 注册表）。"""
    found: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | str | None) -> None:
        candidate = _expand_iscc_path(path)
        if candidate is None:
            return
        key = str(candidate).lower()
        if key in seen:
            return
        seen.add(key)
        found.append(candidate)

    add(_configured_iscc_path())

    for root in _program_files_roots():
        for candidate in _iscc_paths_under(root):
            add(candidate)

    for root in _fixed_drive_roots():
        for candidate in _iscc_paths_under(root):
            add(candidate)

    add(shutil.which("ISCC") or shutil.which("ISCC.exe"))

    for candidate in _registry_iscc_candidates():
        add(candidate)

    return found


def _is_existing_file(path: Path) -> bool:
    try:
        return Path(path).is_file()
    except OSError:
        return False


def _missing_iscc_message() -> str:
    return (
        "未检测到 Inno Setup，无法制作安装包。\n\n"
        "请安装 Inno Setup 6.3 或更高版本后再试。\n"
        "（Inno Setup 不随本程序打包，以免增大体积。）\n\n"
        f"下载页面：\n{INNO_SETUP_DOWNLOAD_PAGE}\n\n"
        "也可设置环境变量 INNO_SETUP_ISCC 指向 ISCC.exe。\n"
        "常见路径示例：\n"
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" + "\n"
        r"C:\Program Files\Inno Setup 7\ISCC.exe"
    )


def _outdated_iscc_message(version: Optional[tuple[int, ...]]) -> str:
    current = _format_iscc_version(version)
    reason = "无法确认" if version is None else "过旧"
    return (
        f"本机 Inno Setup 版本{reason}，无法制作安装包。\n\n"
        f"当前版本：{current}\n"
        "需要 6.3 或更高版本。\n\n"
        f"下载页面：\n{INNO_SETUP_DOWNLOAD_PAGE}"
    )


def _require_specific_iscc(path: Path) -> Path:
    if not _is_existing_file(path):
        raise MissingInnoSetupError(_missing_iscc_message())
    version = _read_iscc_file_version(path)
    if not _is_usable_iscc_version(version):
        raise OutdatedInnoSetupError(_outdated_iscc_message(version))
    return path


def require_iscc() -> Path:
    configured = _configured_iscc_path()
    if configured is not None:
        return _require_specific_iscc(configured)

    existing = [candidate for candidate in _iscc_candidates() if _is_existing_file(candidate)]
    best_path: Optional[Path] = None
    best_version: Optional[tuple[int, int, int, int]] = None
    readable_old: list[tuple[int, int, int, int]] = []
    for candidate in existing:
        version = _normalize_iscc_version(_read_iscc_file_version(candidate))
        if version is None:
            continue
        if version >= MIN_ISCC_VERSION:
            if best_version is None or version > best_version:
                best_version = version
                best_path = candidate
        else:
            readable_old.append(version)
    if best_path is not None:
        return best_path
    if not existing:
        raise MissingInnoSetupError(_missing_iscc_message())
    highest_old = max(readable_old) if readable_old else None
    raise OutdatedInnoSetupError(_outdated_iscc_message(highest_old))


def find_iscc() -> Optional[Path]:
    """仅查找本机已安装且版本不低于 6.3 的 Inno Setup；不捆绑、不内嵌编译器。"""
    try:
        return require_iscc()
    except (MissingInnoSetupError, OutdatedInnoSetupError):
        return None


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
        raise FileNotFoundError(f"安装包图标不存在: {icon_path}")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / "setup.ico"
    shutil.copy2(source, target)
    return "setup.ico"


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
    app_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "lca-standalone:" + display_name)).upper()
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
    progress(int(value), str(message or ""))


def run_iscc(
    iscc: Path,
    iss_path: Path,
    *,
    progress: ProgressCallback = None,
    poll_seconds: float = 2.0,
    extra_args: Sequence[str] | None = None,
    progress_value: int = 82,
    cancel_check: Callable[[], None] | None = None,
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

    from app_core.script_process_job import ProcessJob

    try:
        if cancel_check:
            cancel_check()
        with open(log_path, "w", encoding="utf-8", errors="replace") as log_file, ProcessJob() as job:
            with subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=str(iss_path.parent),
                creationflags=subprocess.CREATE_NO_WINDOW,
            ) as proc:
                try:
                    job.assign(proc)
                    next_report = started + max(0.1, float(poll_seconds))
                    while True:
                        if cancel_check:
                            cancel_check()
                        try:
                            returncode = proc.wait(timeout=0.1)
                            break
                        except subprocess.TimeoutExpired:
                            now = time.monotonic()
                            if now >= next_report:
                                elapsed = int(now - started)
                                _report_iscc_progress(
                                    progress,
                                    progress_value,
                                    f"正在压缩安装包（Inno Setup，已用时 {elapsed} 秒，请耐心等待）…",
                                )
                                next_report = now + max(0.1, float(poll_seconds))
                finally:
                    try:
                        job.terminate_and_wait()
                    finally:
                        job.close()
                        if proc.poll() is None:
                            proc.kill()
                        proc.wait()
        detail = log_path.read_text(encoding="utf-8", errors="replace")
        return IsccResult(returncode=int(returncode), stdout=detail, stderr="")
    finally:
        log_path.unlink(missing_ok=True)


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
    cancel_check: Callable[[], None] | None = None,
) -> Path:
    """
    编译安装包，返回 Setup.exe 路径。
    payload_dir: 已放好 设计名.exe / package.lcap / 依赖 DLL 的目录。
    依赖本机已安装的 Inno Setup 6.3 或更高版本，不自带编译器。
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

    if icon_path:
        ico = Path(icon_path)
    else:
        from utils.app_paths import get_resource_path

        ico = Path(get_resource_path("icon.ico"))
    if not ico.is_file():
        raise FileNotFoundError(f"安装包图标不存在: {ico}")

    output_base = f"{Path(safe_exe).stem}_Setup"

    with tempfile.TemporaryDirectory(prefix=".lca_standalone_iss_", dir=output_dir) as temp_dir:
        temp_root = Path(temp_dir)
        setup_icon_relative = stage_setup_icon(str(ico) if ico else "", temp_root)
        iss_text = build_setup_iss_text(
            display_name=display_name,
            safe_exe=safe_exe,
            publisher=publisher or "LCA",
            version=version or "1.0.0",
            output_dir=str(temp_root),
            output_base=output_base,
            payload_dir=str(payload_dir),
            setup_icon_relative=setup_icon_relative,
        )
        iss_path = temp_root / "standalone.iss"
        # Inno 中文脚本建议 UTF-8 BOM
        iss_path.write_bytes(b"\xef\xbb\xbf" + iss_text.encode("utf-8"))
        if setup_icon_relative:
            logger.info("安装包图标: %s -> %s", ico, temp_root / setup_icon_relative)
        completed = run_iscc(iscc, iss_path, progress=progress, cancel_check=cancel_check)
        if completed.returncode != 0:
            detail = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
            if _is_missing_chinese_language_error(detail):
                require_chinese_simplified_isl(iscc)
            raise RuntimeError(
                "编译安装包失败。\n\n"
                "请检查 Inno Setup 是否完整安装，或查看下方简要信息。\n"
                f"{_summarize_iscc_error(detail)}"
            )

        staged_setup = temp_root / f"{output_base}.exe"
        if not staged_setup.is_file() or staged_setup.stat().st_size == 0:
            raise FileNotFoundError(f"未生成安装包: {output_base}.exe")
        if cancel_check:
            cancel_check()
        setup_path = output_dir / staged_setup.name
        staged_setup.replace(setup_path)
    logger.info("独立程序安装包已生成: %s", setup_path)
    return setup_path
