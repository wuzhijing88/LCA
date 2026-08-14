#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""LCA 发布构建脚本：Nuitka standalone 构建 + 本地运行文件装配 + Inno Setup 安装包。

用法（在项目根目录，使用项目 venv 的 Python）：
    .\\venv\\Scripts\\python.exe build_assets\\packaging\\build_release.py [选项]

常用选项：
    --skip-nuitka     跳过 Nuitka 编译，复用已有 build_output/main.dist（只重新装配发布目录/安装包）
    --skip-installer  不调用 Inno Setup
    --clean           构建前清空 build_output 与 release_output
    --jobs N          传给 Nuitka 的并行编译任务数

产物：
    build_output/main.build   Nuitka 编译中间产物（供打包校验脚本使用）
    build_output/main.dist    Nuitka standalone 输出
    release_output/LCA        最终发布目录（dist + 模型/驱动等本地运行文件）
    release_output/LCA-Setup-<版本>.exe   安装包（本机装有 Inno Setup 6 时）
"""

from __future__ import annotations

import argparse
import atexit
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

PACKAGING_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGING_DIR.parents[1]
BUILD_OUTPUT_DIR = PACKAGING_DIR / "build_output"
BUILD_LOCK_FILE = BUILD_OUTPUT_DIR / ".build.lock"
RELEASE_OUTPUT_DIR = PACKAGING_DIR / "release_output"
RELEASE_APP_DIR = RELEASE_OUTPUT_DIR / "LCA"
VENV_PYTHON = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
SITE_PACKAGES = PROJECT_ROOT / "venv" / "Lib" / "site-packages"

# 主 exe 同时充当子进程 worker（--ocr-worker / --match-worker / --workflow-worker），
# 这些包在运行时经 importlib 按字符串导入，Nuitka 静态分析发现不了，必须显式包含。
INCLUDE_PACKAGES = (
    "app_core",
    "tasks",
    "services",
    "task_workflow",
    "utils",
    "ui",
    "themes",
    # rapidocr 内部经 importlib 懒加载推理引擎；uiautomation 由 utils.uiautomation_runtime
    # 动态导入；comtypes.gen 运行时在程序目录下动态生成/加载。
    "rapidocr",
    "onnxruntime",
    "comtypes",
    "uiautomation",
    # WGC（Windows Graphics Capture）依赖 winrt 扩展模块；其中
    # _winrt_windows_foundation.pyd 由捕获模块在运行时导入，静态分析发现不了。
    "winrt",
)

# winrt 捕获扩展在 C 层才导入这些模块，仅 --include-package 仍可能漏掉
INCLUDE_MODULES = (
    "winrt._winrt_windows_foundation",
    "winrt._winrt_windows_graphics_directx",
)

NOFOLLOW_IMPORTS = (
    "onnxruntime.transformers",
    "onnxruntime.quantization",
    "onnxruntime.tools",
    "onnxruntime.backend",  # 兼容层，会 import unittest，OCR/YOLO 推理用不到
    "comtypes.test",
)

# app_core/ocr_runtime_contract.py 要求的 DirectML 推理运行库
OCR_REQUIRED_RUNTIME_DLLS = (
    "DirectML.dll",
    "onnxruntime.dll",
    "onnxruntime_providers_shared.dll",
)

OCR_MODEL_FILES = (
    "ch_PP-OCRv4_det_mobile.onnx",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "ch_PP-OCRv4_rec_mobile.onnx",
)

# RapidOCR 3.9 包内默认模型是 v6，LCA 只使用上面的本地 v4。打包时剔除，避免随包装进发布目录。
UNUSED_RAPIDOCR_BUNDLE_MODEL_GLOB = "PP-OCRv6*.onnx"

# 便携发布需要随包装的 VC++ 2015-2022 运行库（Nuitka 只从 VS 安装目录取，本机未装 VS 时会漏）
VC_REDIST_DLLS = (
    "msvcp140.dll",
    "msvcp140_1.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
)


def _log(message: str) -> None:
    print(f"[build] {message}", flush=True)


def _warn(message: str) -> None:
    print(f"[build][警告] {message}", flush=True)


def _fail(message: str) -> None:
    print(f"[build][错误] {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def _pid_alive(pid: int) -> bool:
    try:
        import psutil

        return psutil.pid_exists(pid)
    except Exception:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
        )
        return str(pid) in (result.stdout or "")


def _acquire_build_lock() -> None:
    """防止两个构建同时使用 build_output（并发会互删中间产物导致离奇编译错误）。"""
    BUILD_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if BUILD_LOCK_FILE.exists():
        try:
            stale_pid = int(BUILD_LOCK_FILE.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            stale_pid = None
        if stale_pid is not None and stale_pid != os.getpid() and _pid_alive(stale_pid):
            _fail(
                f"检测到另一个构建正在运行（PID {stale_pid}）。"
                f"请等待其结束，或确认其已退出后删除锁文件: {BUILD_LOCK_FILE}"
            )
        _warn("发现上次构建遗留的锁文件，已自动清理")
        BUILD_LOCK_FILE.unlink(missing_ok=True)

    BUILD_LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")

    def _release_lock() -> None:
        try:
            if BUILD_LOCK_FILE.is_file() and BUILD_LOCK_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
                BUILD_LOCK_FILE.unlink()
        except OSError:
            pass

    atexit.register(_release_lock)


def _default_jobs() -> int:
    """按可用内存限制并行度：每个 gcc 任务按约 2GB 估算，避免内存耗尽导致编译中断。"""
    cores = os.cpu_count() or 4
    try:
        import psutil

        available_gb = psutil.virtual_memory().available / (1024 ** 3)
        return max(2, min(cores, int(available_gb // 2)))
    except Exception:
        return max(2, min(cores, 8))


def _read_app_version() -> str:
    config_path = PROJECT_ROOT / "app_core" / "app_config.py"
    match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', config_path.read_text(encoding="utf-8"))
    if not match:
        _fail(f"无法从 {config_path} 解析 APP_VERSION")
    return match.group(1)


def _preflight() -> None:
    if not VENV_PYTHON.is_file():
        _fail(f"未找到项目虚拟环境 Python: {VENV_PYTHON}")

    required = {
        "程序入口": PROJECT_ROOT / "main.py",
        "程序图标": PROJECT_ROOT / "resources" / "icon.ico",
        "浅色主题": PROJECT_ROOT / "themes" / "light.qss",
        "深色主题": PROJECT_ROOT / "themes" / "dark.qss",
    }
    for label, path in required.items():
        if not path.exists():
            _fail(f"缺少必需文件（{label}）: {path}")

    # 以下内容由本地环境提供（见 README），缺失时仅告警，发布目录会缺对应功能
    local_runtime = {
        "AutoHotkey 运行时": PROJECT_ROOT / "AutoHotkey" / "AutoHotkey64.exe",
        "Interception 驱动库": PROJECT_ROOT / "Interception" / "library" / "x64" / "interception.dll",
        "IbInputSimulator 绑定": PROJECT_ROOT / "tools" / "ibinputsimulator" / "Binding.AHK2" / "IbInputSimulator.ahk",
        "IbInputSimulator DLL": PROJECT_ROOT / "tools" / "ibinputsimulator" / "Binding.AHK2" / "IbInputSimulator.dll",
        "IbInputSimulator worker": PROJECT_ROOT / "tools" / "ibinputsimulator" / "ib_worker_core.ahk",
    }
    for name in OCR_MODEL_FILES:
        local_runtime[f"OCR 模型 {name}"] = PROJECT_ROOT / "models" / "rapidocr" / name

    for label, path in local_runtime.items():
        if not path.exists():
            _warn(f"本地运行文件缺失（{label}）: {path}")


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_NUITKA_PREFIX_RE = re.compile(
    r"^(?P<channel>Nuitka(?:-[A-Za-z]+)?)(?P<warning>:WARNING)?:[ \t]*(?P<body>.*)$"
)
_FATAL_RE = re.compile(r"^FATAL:[ \t]*(?P<body>.*)$")


def _build_tag(level: str) -> str:
    return {
        "info": "[build]",
        "hint": "[build][提示]",
        "warn": "[build][警告]",
        "error": "[build][错误]",
        "compile": "[build][编译]",
    }[level]


def _translate_data_reason(reason: str) -> str:
    specified_file = re.match(r"^specified data file '(.+)' on command line$", reason)
    if specified_file:
        return f"命令行指定数据文件 {specified_file.group(1)}"
    specified_dir = re.match(r"^specified data dir '(.+)' on command line$", reason)
    if specified_dir:
        return f"命令行指定数据目录 {specified_dir.group(1)}"
    package_data = re.match(r"^package '(.+)' package data$", reason)
    if package_data:
        return f"{package_data.group(1)} 包内数据"
    package_for = re.match(r"^package data for '(.+)'$", reason)
    if package_for:
        return f"{package_for.group(1)} 包内数据"
    if reason == "Tk needed for tkinter usage":
        return "tkinter 需要 Tk"
    if reason == "Tcl needed for tkinter usage":
        return "tkinter 需要 Tcl"
    return reason


class _NuitkaLogTranslator:
    """将 Nuitka / gcc 的英文日志转成中文后输出。"""

    def __init__(self) -> None:
        self._skip_option_lines = False
        self._constants_h_explained = False

    def feed(self, raw_line: str) -> Optional[str]:
        line = _ANSI_RE.sub("", raw_line).replace("\r", "").rstrip()
        if not line.strip():
            return None

        fatal = _FATAL_RE.match(line)
        if fatal:
            rendered = self._translate_nuitka_body(fatal.group("body"), is_warning=True)
            if rendered is None:
                return f"{_build_tag('error')} {fatal.group('body').strip()}"
            return f"{_build_tag('error')} {rendered[1]}"

        prefixed = _NUITKA_PREFIX_RE.match(line)
        if prefixed:
            body = prefixed.group("body")
            if self._skip_option_lines:
                stripped = body.strip()
                if stripped.startswith("--") or stripped.startswith("~"):
                    return None
                self._skip_option_lines = False
            rendered = self._translate_nuitka_body(body, is_warning=bool(prefixed.group("warning")))
            if rendered is None:
                return None
            return f"{_build_tag(rendered[0])} {rendered[1]}"

        rendered = self._translate_compiler_line(line)
        if rendered is None:
            return None
        return f"{_build_tag(rendered[0])} {rendered[1]}"

    def _translate_nuitka_body(self, body: str, is_warning: bool) -> Optional[Tuple[str, str]]:
        text = body.strip()
        if not text:
            return None

        if text == "Used command line options:":
            self._skip_option_lines = True
            return None

        if text == "Starting Python compilation with:":
            return ("info", "开始 Python 层编译")

        version_match = re.match(
            r"^Version '([^']+)' on Python (\S+) \(flavor '([^']+)'( no GIL)?\) "
            r"commercial grade '([^']+)'\.$",
            text,
        )
        if version_match:
            flavor = version_match.group(3)
            if flavor == "CPython Official":
                flavor = "CPython 官方版"
            commercial = version_match.group(5)
            if commercial == "not installed":
                commercial = "未安装"
            gil = "，无 GIL" if version_match.group(4) else ""
            return (
                "info",
                f"Nuitka {version_match.group(1)}，Python {version_match.group(2)}"
                f"（{flavor}{gil}，商业版：{commercial}）",
            )

        include_match = re.match(
            r"^Not allowed to include module '([^']+)' due to '(.*)'\.$",
            text,
        )
        if include_match:
            module_name, reason = include_match.group(1), include_match.group(2)
            if "not follow" in reason or "exact match" in reason:
                return ("hint", f"已按配置排除模块 {module_name}（不参与打包，属预期行为）")
            return ("warn", f"不允许包含模块 {module_name}：{reason}")

        bloat_match = re.match(
            r"^anti-bloat: Undesirable import of '([^']+)'"
            r"(?: \(intending to avoid '[^']+'\))? in '([^']+)' \(at '([^']+)'\) "
            r"encountered\. It may slow down compilation\.$",
            text,
        )
        if bloat_match:
            return (
                "warn",
                f"模块 {bloat_match.group(2)} 引入了 {bloat_match.group(1)}，"
                f"可能拖慢编译（位置：{bloat_match.group(3)}）",
            )

        pyside_match = re.match(
            r"^pyside6: Unwanted import of '([^']+)' that is redundant with '([^']+)' encountered\.",
            text,
        )
        if pyside_match:
            unwanted, binding = pyside_match.group(1), pyside_match.group(2)
            if unwanted == "tkinter":
                return (
                    "hint",
                    f"检测到 {unwanted} 与 {binding} 同时存在。"
                    "本项目因 pyautogui 需要 tkinter，已启用 tk-inter 插件，可忽略。",
                )
            return ("warn", f"检测到不需要的导入 {unwanted}，与 {binding} 功能重复")

        if "More information can be found at" in text or text.startswith("Complex topic!"):
            return None

        exact_info = {
            "Completed Python level compilation and optimization.": (
                "info",
                "Python 层编译与优化已完成",
            ),
            "Generating source code for C backend compiler.": (
                "info",
                "正在生成 C 后端源代码",
            ),
            "Running data composer tool for optimal constant value handling.": (
                "info",
                "正在整理常量数据",
            ),
            "Running C compilation via Scons.": (
                "info",
                "开始 C 编译（最耗时，请耐心等待）",
            ),
            "Failed unexpectedly in Scons C backend compilation.": (
                "error",
                "C 后端编译意外失败",
            ),
            "User interrupted scons build.": ("error", "用户中断了 C 编译"),
            "Fatal error in scons build.": ("error", "C 编译过程发生致命错误"),
            "No usable C compiler, attempt fallback to winlibs gcc or clang.": (
                "info",
                "未找到可用的系统 C 编译器，改用 Nuitka 自带的 gcc/clang",
            ),
            "Error, cannot locate suitable C compiler.": (
                "error",
                "找不到合适的 C 编译器",
            ),
        }
        if text in exact_info:
            return exact_info[text]

        gcc_ignore = re.match(
            r"^Non downloaded winlibs-gcc '(.+)' is being ignored, "
            r"Nuitka is very dependent on the precise one\.$",
            text,
        )
        if gcc_ignore:
            return ("hint", f"已忽略系统中的 gcc（{gcc_ignore.group(1)}），将使用 Nuitka 指定的编译器")

        compiler_match = re.match(r"^(.+) C compiler: (.+) \((.+)\)\.$", text)
        if compiler_match:
            context = compiler_match.group(1)
            if context == "Backend":
                context = "后端"
            return (
                "info",
                f"{context} C 编译器：{compiler_match.group(2)}（{compiler_match.group(3)}）",
            )

        crash_match = re.match(r"^Compilation crash report written to file '(.+)'\.$", text)
        if crash_match:
            return ("error", f"编译崩溃报告已写入 {crash_match.group(1)}")

        created_match = re.match(r"^Successfully created '(.+)'\.$", text)
        if created_match:
            return ("info", f"已生成 {created_match.group(1)}")

        keep_match = re.match(r"^Keeping build directory '(.+)'\.$", text)
        if keep_match:
            return ("info", f"保留编译目录 {keep_match.group(1)}")

        download_match = re.match(r"^Downloading '(.+)'\.$", text)
        if download_match:
            return ("info", f"正在下载 {download_match.group(1)}")

        extract_match = re.match(r"^Extracting to '(.+)'\.$", text)
        if extract_match:
            return ("info", f"正在解压到 {extract_match.group(1)}")

        slow_cc = re.match(
            r"^Slow C compilation detected, used ([\d.]+)s so far, scalability problem\.$",
            text,
        )
        if slow_cc:
            return ("warn", f"C 编译较慢，已耗时 {slow_cc.group(1)} 秒")

        slow_link = re.match(r"^Slow C linking detected, used ([\d.]+)s so far,", text)
        if slow_link:
            return ("warn", f"C 链接较慢，已耗时 {slow_link.group(1)} 秒。若要加快可加 --lto=no")

        linking = re.match(
            r"^(.+) C linking with (\d+) files \(no progress information available for this stage\)\.$",
            text,
        )
        if linking:
            stage = "后端" if linking.group(1) == "Backend" else linking.group(1)
            return ("info", f"开始{stage}链接（共 {linking.group(2)} 个文件，此阶段无进度显示）")

        linking_simple = re.match(r"^(.+) C linking\.$", text)
        if linking_simple:
            stage = "后端" if linking_simple.group(1) == "Backend" else linking_simple.group(1)
            return ("info", f"开始{stage}链接")

        failed_include = re.match(r"^Failed to include module from '(.+)'\.$", text)
        if failed_include:
            return ("warn", f"未能包含模块：{failed_include.group(1)}")

        ccache_compiled = re.match(r"^Compiled (\d+) C files using ccache\.$", text)
        if ccache_compiled:
            return ("info", f"已用编译缓存处理 {ccache_compiled.group(1)} 个 C 文件")

        ccache_result = re.match(
            r"^Cached C files \(using ccache\) with result '([^']+)': (\d+)$",
            text,
        )
        if ccache_result:
            kind = {
                "cache hit": "命中缓存（直接复用，不必重编译）",
                "cache miss": "未命中缓存（已重新编译）",
            }.get(ccache_result.group(1), ccache_result.group(1))
            return ("info", f"编译缓存：{kind} {ccache_result.group(2)} 个")

        clcache = re.match(
            r"^Compiled (\d+) C files using clcache with (\d+) cache hits and (\d+) cache misses\.$",
            text,
        )
        if clcache:
            return (
                "info",
                f"已用 clcache 处理 {clcache.group(1)} 个 C 文件"
                f"（命中 {clcache.group(2)}，重编译 {clcache.group(3)}）",
            )

        icons = re.match(r"^Adding (\d+) icon\(s\) from icon file '(.+)'\.$", text)
        if icons:
            return ("info", f"已写入 {icons.group(1)} 个程序图标：{icons.group(2)}")

        qt_plugins = re.match(
            r"^Including Qt plugins '([^']+)' below '([^']+)'\.$",
            text,
        )
        if qt_plugins:
            return (
                "info",
                f"已包含 Qt 插件 {qt_plugins.group(1)}，输出到 {qt_plugins.group(2)}",
            )

        dll_found = re.match(
            r"^Found (\d+) files? DLLs from (.+) installation\.$",
            text,
        )
        if dll_found:
            return ("info", f"已从 {dll_found.group(2)} 收集 {dll_found.group(1)} 个 DLL")

        vc_redist = re.match(
            r"^The following Visual C\+\+ Redistributable DLLs were not found: ([^.]+)\.",
            text,
        )
        if vc_redist:
            return (
                "warn",
                f"Nuitka 未打入 Visual C++ 运行库：{vc_redist.group(1)}。"
                "本机一般已安装所以能运行；未装「VC++ 2015-2022 可再发行组件」的电脑可能无法启动。"
                "发布阶段会从系统目录补进这些 DLL。",
            )

        data_file = re.match(r"^Included data file '(.+)' due to (.+)\.$", text)
        if data_file:
            return ("info", f"已包含数据文件 {data_file.group(1)}（{_translate_data_reason(data_file.group(2))}）")

        data_files = re.match(r"^Included (\d+) data files due to (.+)\.$", text)
        if data_files:
            return (
                "info",
                f"已包含 {data_files.group(1)} 个数据文件（{_translate_data_reason(data_files.group(2))}）",
            )

        if is_warning:
            return ("warn", f"Nuitka 提示：{text}")
        return ("info", text)

    def _translate_compiler_line(self, line: str) -> Optional[Tuple[str, str]]:
        stripped = line.strip()
        if stripped.startswith("In file included from") or stripped.startswith("from "):
            return None
        if stripped == "compilation terminated.":
            return None
        if re.match(r"^\d+\s+\|", stripped) or re.match(r"^\|\s+\^", stripped):
            return None
        if "__constants.h" in line and "fatal error" in line:
            if self._constants_h_explained:
                return None
            self._constants_h_explained = True
            return (
                "error",
                "找不到中间文件 __constants.h。常见原因：上次构建被中断，或同时运行了两个构建。"
                "请停止全部构建后使用 --clean 重试。",
            )
        scons_error = re.match(r"^scons: \*\*\* \[(.+)\] Error (\d+)$", stripped)
        if scons_error:
            if self._constants_h_explained:
                return None
            return ("error", f"编译 {scons_error.group(1)} 失败（退出码 {scons_error.group(2)}）")
        fatal_error = re.search(r"fatal error:\s*(.+)$", line)
        if fatal_error:
            detail = fatal_error.group(1).strip()
            if detail.endswith("No such file or directory"):
                missing = detail.replace(": No such file or directory", "").strip()
                return ("error", f"编译致命错误：找不到文件 {missing}")
            return ("error", f"编译致命错误：{detail}")
        return ("compile", line)


def _run_nuitka(version: str, jobs: Optional[int]) -> None:
    cmd: List[str] = [
        str(VENV_PYTHON),
        "-m",
        "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        "--enable-plugin=pyside6",
        # pyautogui -> pymsgbox 依赖 tkinter
        "--enable-plugin=tk-inter",
        "--windows-console-mode=disable",
        "--windows-uac-admin",
        f"--windows-icon-from-ico={PROJECT_ROOT / 'resources' / 'icon.ico'}",
        "--company-name=LCA",
        "--product-name=LCA",
        f"--file-version={version}",
        f"--product-version={version}",
        "--file-description=LCA 自动化工作流",
        "--copyright=LCA (AGPL-3.0)",
        f"--output-dir={BUILD_OUTPUT_DIR}",
        "--output-filename=LCA.exe",
    ]
    for package in INCLUDE_PACKAGES:
        cmd.append(f"--include-package={package}")
    for module in INCLUDE_MODULES:
        cmd.append(f"--include-module={module}")
    for module in NOFOLLOW_IMPORTS:
        cmd.append(f"--nofollow-import-to={module}")
    # rapidocr 需要包内 config.yaml / default_models.yaml；不要带上未使用的 v6 默认模型
    cmd.append("--include-package-data=rapidocr")
    cmd.append(f"--noinclude-data-files=rapidocr/models/{UNUSED_RAPIDOCR_BUNDLE_MODEL_GLOB}")
    # 主题 QSS 与图标按 get_app_root()/themes 相对路径读取；resources 存放程序图标与声明
    cmd.append("--include-data-files=themes/*.qss=themes/")
    cmd.append("--include-data-dir=themes/icons=themes/icons")
    cmd.append("--include-data-dir=resources=resources")
    if jobs:
        cmd.append(f"--jobs={jobs}")
    cmd.append(str(PROJECT_ROOT / "main.py"))

    _log("开始 Nuitka 编译（首次编译可能需要较长时间）...")
    _log("命令: " + subprocess.list2cmdline(cmd))
    started = time.monotonic()
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    translator = _NuitkaLogTranslator()
    process = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    assert process.stdout is not None
    try:
        for raw in process.stdout:
            rendered = translator.feed(raw)
            if rendered:
                print(rendered, flush=True)
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
        raise
    returncode = process.wait()
    if returncode != 0:
        _fail(f"Nuitka 编译失败，退出码 {returncode}")
    _log(f"Nuitka 编译完成，耗时 {time.monotonic() - started:.0f} 秒")


def _run_packaging_checks() -> None:
    build_dir = BUILD_OUTPUT_DIR / "main.build"
    checks = (
        ("任务模块", PROJECT_ROOT / "tools" / "verify_packaged_task_modules.py"),
        ("子进程 worker", PROJECT_ROOT / "tools" / "verify_packaged_subprocess_workers.py"),
    )
    for label, script in checks:
        _log(f"打包校验：{label} ...")
        result = subprocess.run(
            [str(VENV_PYTHON), str(script), "--build-dir", str(build_dir)],
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode != 0:
            _fail(f"打包校验未通过（{label}），请检查 Nuitka include 配置")


def _copy_tree(source: Path, target: Path, label: str) -> None:
    if not source.exists():
        _warn(f"跳过复制（目录不存在）：{label} -> {source}")
        return
    _log(f"复制 {label}: {source.name}/")
    shutil.copytree(source, target, dirs_exist_ok=True)


def _bundle_vc_redist_dlls(target_dir: Path) -> None:
    """把 VC++ 运行库拷到程序目录，避免未装可再发行组件的电脑无法启动。"""
    system_dir = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    existing = {path.name.lower() for path in target_dir.glob("*.dll")}
    copied: List[str] = []
    missing: List[str] = []
    for dll_name in VC_REDIST_DLLS:
        if dll_name.lower() in existing:
            continue
        source = system_dir / dll_name
        if source.is_file():
            shutil.copy2(source, target_dir / dll_name)
            copied.append(dll_name)
        else:
            missing.append(dll_name)
    if copied:
        _log(f"已从系统目录补入 Visual C++ 运行库：{', '.join(copied)}")
    if missing:
        _warn(
            f"系统中也找不到 {', '.join(missing)}。"
            "未安装「Microsoft Visual C++ 2015-2022 可再发行组件包（x64）」的电脑可能无法启动。"
        )


def _bundle_winrt_extensions(target_dir: Path) -> None:
    """补齐 WGC 所需的 winrt 原生扩展（Nuitka 可能漏掉运行时才导入的 foundation）。"""
    source_dir = SITE_PACKAGES / "winrt"
    dest_dir = target_dir / "winrt"
    if not source_dir.is_dir():
        _warn(f"未找到 winrt 包，WGC 截屏将不可用: {source_dir}")
        return
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied: List[str] = []
    for source in source_dir.glob("_winrt*.pyd"):
        if ".cp" in source.name:
            dest_name = source.name.split(".cp")[0] + ".pyd"
        else:
            dest_name = source.name
        destination = dest_dir / dest_name
        if destination.is_file():
            continue
        shutil.copy2(source, destination)
        copied.append(dest_name)
    if copied:
        _log(f"已补入 winrt 扩展模块：{', '.join(copied)}")


def _strip_unused_rapidocr_bundle_models(root: Path) -> None:
    """删除 RapidOCR 自带、LCA 不会加载的 PP-OCRv6 ONNX。不影响 models/rapidocr 下的 v4。"""
    models_dir = root / "rapidocr" / "models"
    if not models_dir.is_dir():
        return
    removed: List[str] = []
    for path in models_dir.glob(UNUSED_RAPIDOCR_BUNDLE_MODEL_GLOB):
        if not path.is_file():
            continue
        path.unlink()
        removed.append(path.name)
    if removed:
        _log(f"已移除未使用的 RapidOCR v6 模型: {', '.join(sorted(removed))}")


def _assemble_release() -> None:
    dist_dir = BUILD_OUTPUT_DIR / "main.dist"
    if not (dist_dir / "LCA.exe").is_file():
        _fail(f"未找到 Nuitka 输出 {dist_dir / 'LCA.exe'}，请先完成编译")

    if RELEASE_APP_DIR.exists():
        _log("清理旧的发布目录 ...")
        shutil.rmtree(RELEASE_APP_DIR)
    RELEASE_APP_DIR.parent.mkdir(parents=True, exist_ok=True)

    _log("复制 Nuitka standalone 输出 ...")
    shutil.copytree(dist_dir, RELEASE_APP_DIR)
    _strip_unused_rapidocr_bundle_models(RELEASE_APP_DIR)

    # 本地环境提供的运行文件（README：模型、Interception、AutoHotkey、IbInputSimulator）
    _copy_tree(PROJECT_ROOT / "models", RELEASE_APP_DIR / "models", "OCR/YOLO 模型")
    _copy_tree(PROJECT_ROOT / "AutoHotkey", RELEASE_APP_DIR / "AutoHotkey", "AutoHotkey 运行时")
    _copy_tree(PROJECT_ROOT / "Interception", RELEASE_APP_DIR / "Interception", "Interception 驱动")

    ib_source = PROJECT_ROOT / "tools" / "ibinputsimulator"
    ib_target = RELEASE_APP_DIR / "tools" / "ibinputsimulator"
    if ib_source.is_dir():
        _log("复制 IbInputSimulator 运行文件 ...")
        (ib_target / "Binding.AHK2").mkdir(parents=True, exist_ok=True)
        for name in ("IbInputSimulator.ahk", "IbInputSimulator.dll"):
            source_file = ib_source / "Binding.AHK2" / name
            if source_file.is_file():
                shutil.copy2(source_file, ib_target / "Binding.AHK2" / name)
            else:
                _warn(f"IbInputSimulator 文件缺失: {source_file}")
        worker_core = ib_source / "ib_worker_core.ahk"
        if worker_core.is_file():
            shutil.copy2(worker_core, ib_target / "ib_worker_core.ahk")
        else:
            _warn(f"IbInputSimulator 文件缺失: {worker_core}")
    else:
        _warn(f"跳过 IbInputSimulator（目录不存在）: {ib_source}")

    # utils.uiautomation_runtime 在打包环境下于程序根目录查找 comtypes/gen 与 uiautomation/bin
    comtypes_gen = SITE_PACKAGES / "comtypes" / "gen"
    target_gen = RELEASE_APP_DIR / "comtypes" / "gen"
    target_gen.mkdir(parents=True, exist_ok=True)
    if comtypes_gen.is_dir():
        copied = 0
        for module_file in comtypes_gen.iterdir():
            if module_file.is_file() and module_file.suffix.lower() in (".py", ".pyc"):
                shutil.copy2(module_file, target_gen / module_file.name)
                copied += 1
        _log(f"复制 comtypes/gen 预生成模块：{copied} 个文件")
    if not (target_gen / "__init__.py").is_file():
        (target_gen / "__init__.py").write_text(
            "# comtypes.gen 运行时生成目录\n", encoding="utf-8"
        )

    uia_bin = SITE_PACKAGES / "uiautomation" / "bin"
    if uia_bin.is_dir():
        _copy_tree(uia_bin, RELEASE_APP_DIR / "uiautomation" / "bin", "UIAutomation DLL")
    else:
        _warn(f"未找到 uiautomation/bin: {uia_bin}")

    license_file = PROJECT_ROOT / "LICENSE"
    if license_file.is_file():
        shutil.copy2(license_file, RELEASE_APP_DIR / "LICENSE")

    _bundle_winrt_extensions(RELEASE_APP_DIR)


def _check_release() -> None:
    _log("发布目录完整性检查 ...")
    problems: List[str] = []

    if not (RELEASE_APP_DIR / "LCA.exe").is_file():
        problems.append("缺少 LCA.exe")
    for relative in ("themes/light.qss", "themes/dark.qss", "themes/icons/check-white.svg", "resources/icon.ico"):
        if not (RELEASE_APP_DIR / relative).is_file():
            problems.append(f"缺少 {relative}")

    # OCR DirectML 运行库：Nuitka 未带出时从 venv 补拷
    existing_dlls = {path.name.lower() for path in RELEASE_APP_DIR.rglob("*.dll")}
    capi_dir = SITE_PACKAGES / "onnxruntime" / "capi"
    for dll_name in OCR_REQUIRED_RUNTIME_DLLS:
        if dll_name.lower() in existing_dlls:
            continue
        fallback = capi_dir / dll_name
        if fallback.is_file():
            target_dir = RELEASE_APP_DIR / "onnxruntime" / "capi"
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fallback, target_dir / dll_name)
            _warn(f"Nuitka 输出缺少 {dll_name}，已从 venv 补拷到 onnxruntime/capi/")
        else:
            problems.append(f"缺少 OCR 运行库 {dll_name}")

    for name in OCR_MODEL_FILES:
        if not (RELEASE_APP_DIR / "models" / "rapidocr" / name).is_file():
            _warn(f"发布目录缺少 OCR 模型 {name}（OCR 功能将不可用）")

    leftover_v6 = sorted(
        path.name
        for path in (RELEASE_APP_DIR / "rapidocr" / "models").glob(UNUSED_RAPIDOCR_BUNDLE_MODEL_GLOB)
        if path.is_file()
    ) if (RELEASE_APP_DIR / "rapidocr" / "models").is_dir() else []
    if leftover_v6:
        problems.append("发布目录仍包含未使用的 RapidOCR v6 模型: " + ", ".join(leftover_v6))

    _bundle_vc_redist_dlls(RELEASE_APP_DIR)

    if problems:
        for problem in problems:
            _fail(f"发布目录检查未通过: {problem}")
    _log("发布目录检查通过")


def _find_iscc() -> Optional[Path]:
    env_path = os.environ.get("LCA_ISCC")
    candidates = [Path(env_path)] if env_path else []
    for base in (
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("ProgramFiles", r"C:\Program Files"),
    ):
        candidates.append(Path(base) / "Inno Setup 6" / "ISCC.exe")
    located = shutil.which("iscc")
    if located:
        candidates.append(Path(located))
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    return None


def _translate_inno_line(raw_line: str) -> Optional[str]:
    line = raw_line.rstrip("\r\n")
    if not line.strip():
        return None

    exact = {
        "Inno Setup 6 Command-Line Compiler": "Inno Setup 6 命令行编译器",
        "Non-commercial use only": "仅限非商业使用",
        "Preprocessing": "正在预处理",
        "Preparing Setup program executable": "正在准备安装程序",
        "Verification successful": "校验通过",
        "Determining language code pages": "正在确定语言代码页",
        "Messages in script file": "正在读取脚本中的界面文本",
        "Reading default messages from Default.isl": "正在读取默认英文界面文本",
        "Reading [Code] section": "正在读取脚本代码段",
        "Creating setup files": "正在生成安装包文件",
        "Successful compile": "安装包编译成功",
    }
    stripped = line.strip()
    if stripped in exact:
        return f"[build] {exact[stripped]}"
    if stripped.startswith("Copyright (C)") or stripped.startswith("Portions Copyright"):
        return None
    if stripped == "https://www.innosetup.com":
        return None

    compiler_ver = re.match(r"^Compiler engine version: Inno Setup (.+)$", stripped)
    if compiler_ver:
        return f"[build] 编译器版本：Inno Setup {compiler_ver.group(1)}"

    reading = re.match(r"^Reading file(?: \((.+)\))?: (.+)$", stripped)
    if reading:
        kind = f"（{reading.group(1)}）" if reading.group(1) else ""
        return f"[build] 正在读取文件{kind}：{reading.group(2)}"

    parsing = re.match(r"^Parsing (.+) section, line (\d+)$", stripped)
    if parsing:
        return f"[build] 正在解析 {parsing.group(1)} 段，第 {parsing.group(2)} 行"

    parsing_multi = re.match(r"^Parsing (.+) sections$", stripped)
    if parsing_multi:
        return f"[build] 正在解析 {parsing_multi.group(1)} 段"

    updating = re.match(r"^Updating (.+) \((.+)\)$", stripped)
    if updating:
        kind = {"icons": "图标", "version info": "版本信息"}.get(updating.group(1), updating.group(1))
        return f"[build] 正在更新{kind}（{updating.group(2)}）"

    compressing = re.match(r"^Compressing: (.+)$", stripped)
    if compressing:
        return f"[build] 正在压缩：{compressing.group(1)}"

    successful = re.match(r"^Successful compile \((.+)\)\. Resulting Setup program filename is:$", stripped)
    if successful:
        return f"[build] 安装包编译成功，耗时 {successful.group(1)}。输出文件："

    if stripped.startswith("Error") or stripped.startswith("Fatal"):
        return f"[build][错误] {stripped}"

    return f"[build] {line}"


def _run_inno_setup(version: str) -> None:
    iscc = _find_iscc()
    if iscc is None:
        _warn("未检测到 Inno Setup 6（ISCC.exe），跳过安装包生成。可安装后重跑，或设置环境变量 LCA_ISCC")
        return

    script = PACKAGING_DIR / "installer.iss"
    _log(f"使用 Inno Setup 生成安装包: {iscc}")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen(
        [
            str(iscc),
            f"/DAppVersion={version}",
            f"/DReleaseDir={RELEASE_APP_DIR}",
            f"/O{RELEASE_OUTPUT_DIR}",
            str(script),
        ],
        cwd=str(PACKAGING_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    assert process.stdout is not None
    for raw in process.stdout:
        rendered = _translate_inno_line(raw)
        if rendered:
            print(rendered, flush=True)
    if process.wait() != 0:
        _fail(f"Inno Setup 编译失败，退出码 {process.returncode}")
    _log(f"安装包已生成: {RELEASE_OUTPUT_DIR / f'LCA-Setup-{version}.exe'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="LCA Nuitka + Inno Setup 发布构建")
    parser.add_argument("--skip-nuitka", action="store_true", help="跳过 Nuitka 编译，复用已有 main.dist")
    parser.add_argument("--skip-installer", action="store_true", help="不生成 Inno Setup 安装包")
    parser.add_argument("--clean", action="store_true", help="构建前清空 build_output 与 release_output")
    parser.add_argument("--jobs", type=int, default=None, help="Nuitka 并行编译任务数")
    args = parser.parse_args()

    version = _read_app_version()
    _log(f"项目根目录: {PROJECT_ROOT}")
    _log(f"应用版本: {version}")

    _acquire_build_lock()

    if args.clean:
        for directory in (BUILD_OUTPUT_DIR / "main.build", BUILD_OUTPUT_DIR / "main.dist", RELEASE_OUTPUT_DIR):
            if directory.exists():
                _log(f"清理 {directory} ...")
                shutil.rmtree(directory)

    _preflight()

    if args.skip_nuitka:
        _log("已跳过 Nuitka 编译（--skip-nuitka）")
    else:
        jobs = args.jobs or _default_jobs()
        if not args.jobs:
            _log(f"并行编译任务数按可用内存自动限制为 {jobs}（可用 --jobs 覆盖）")
        _run_nuitka(version, jobs)

    _run_packaging_checks()
    _assemble_release()
    _check_release()

    if args.skip_installer:
        _log("已跳过安装包生成（--skip-installer）")
    else:
        _run_inno_setup(version)

    _log(f"完成。发布目录: {RELEASE_APP_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
