from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT_FOR_IMPORTS = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT_FOR_IMPORTS) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_IMPORTS))

from app_core.ocr_runtime_contract import (
    OCR_MODEL_DIRECTORY,
    OCR_MODEL_FILES,
    OCR_REQUIRED_REQUIREMENTS,
)


INCLUDE_PACKAGES = (
    "tasks",
    "uiautomation",
    "winrt",
    "dxcam",
    "rapidocr",
    "app_core",
)

INCLUDE_PACKAGE_DATA = (
    "rapidocr",
)

INCLUDE_MODULES = (
    "services.multiprocess_ocr_pool",
    "services.multiprocess_ocr_worker",
    "services.rapidocr_ocr_service",
    "services.screenshot_pool",
    "utils.dxgi_capture",
    "services.multiprocess_match_worker",
    "task_workflow.process_worker",
    "win32gui",
    "win32ui",
    "win32con",
    "winrt.windows.graphics.capture",
    "winrt.windows.graphics.capture.interop",
    "winrt.windows.graphics.directx",
    "winrt.windows.graphics.directx.direct3d11",
    "winrt.windows.graphics.imaging",
    "winrt.windows.ai.machinelearning",
    "comtypes",
    "comtypes.client",
    "comtypes.stream",
    "comtypes.server",
    "comtypes.automation",
    "comtypes.typeinfo",
    "comtypes.hresult",
    "comtypes._comobject",
    "comtypes.patcher",
    "app_core.app_config",
    "themes.theme_manager",
    "ui.widgets.custom_title_bar",
)

NOFOLLOW_IMPORTS = (
    "comtypes.test",
    "mouseinfo",
    "MNN",
    "openvino",
    "paddle",
    "tensorrt",
    "torch",
    "zstandard",
)

DATA_DIR_SPECS = (
    ("models/rapidocr", "models/rapidocr"),
    ("config", "config"),
    ("themes", "themes"),
    ("Interception", "Interception"),
)

DATA_FILE_SPECS = (
    ("tools/ibinputsimulator/ib_worker_core.ahk", "tools/ibinputsimulator/ib_worker_core.ahk"),
    (
        "tools/ibinputsimulator/Binding.AHK2/IbInputSimulator.ahk",
        "tools/ibinputsimulator/Binding.AHK2/IbInputSimulator.ahk",
    ),
    (
        "tools/ibinputsimulator/Binding.AHK2/IbInputSimulator.dll",
        "tools/ibinputsimulator/Binding.AHK2/IbInputSimulator.dll",
    ),
    ("AutoHotkey/AutoHotkey64.exe", "AutoHotkey/AutoHotkey64.exe"),
    ("resources/icon.ico", "resources/icon.ico"),
)

ONNXRUNTIME_GPU_DLL_PATTERNS = (
    "onnxruntime/capi/onnxruntime_providers_cuda.dll",
    "onnxruntime/capi/onnxruntime_providers_tensorrt.dll",
    "onnxruntime_providers_cuda.dll",
    "onnxruntime_providers_tensorrt.dll",
    "cublas*.dll",
    "cufft*.dll",
    "cudart*.dll",
    "cudnn*.dll",
    "zlibwapi.dll",
)

OPTIONAL_RUNTIME_DLL_PATTERNS = (
    "cv2/opencv_videoio_ffmpeg*.dll",
    "opencv_videoio_ffmpeg*.dll",
)

RUNTIME_DLL_REMOVE_PATTERNS = (
    *ONNXRUNTIME_GPU_DLL_PATTERNS,
    *OPTIONAL_RUNTIME_DLL_PATTERNS,
)

NOINCLUDE_DLLS = RUNTIME_DLL_REMOVE_PATTERNS

CCACHE_OWNER_PATTERN = re.compile(r"^ccache-(\d+)\.txt$", re.IGNORECASE)
DELETE_RETRY_COUNT = 5
DELETE_RETRY_DELAY_SECONDS = 1.0
PROCESS_EXIT_GRACE_SECONDS = 2.0
RESULT_EXE_NAME = "main.exe"
RESULT_EXE_RELATIVE_PATH = Path("main.dist") / RESULT_EXE_NAME
BUILD_ARTIFACT_WAIT_TIMEOUT_SECONDS = 30.0
BUILD_ARTIFACT_POLL_INTERVAL_SECONDS = 0.25
WINDOWS_PROCESS_QUERY = (
    "Get-CimInstance Win32_Process | "
    "Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine | "
    "ConvertTo-Json -Compress"
)


@dataclass(frozen=True)
class ProcessInfo:
    process_id: int
    parent_process_id: int
    name: str
    executable_path: str
    command_line: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the main Nuitka build with stable argument handling.")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_pinned_requirements(requirements_path: Path) -> dict[str, str]:
    pinned: dict[str, str] = {}
    for raw_line in requirements_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if "==" not in line:
            continue
        name, version = line.split("==", 1)
        pinned[name.strip().lower()] = version.strip()
    return pinned


def _validate_ocr_build_inputs(project_root: Path) -> None:
    model_dir = project_root / OCR_MODEL_DIRECTORY
    expected_names = {filename for filename, _expected_hash in OCR_MODEL_FILES.values()}
    actual_names = {path.name for path in model_dir.glob("*.onnx") if path.is_file()}
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        unexpected = sorted(actual_names - expected_names)
        raise RuntimeError(
            "OCR模型目录与PP-OCRv4打包清单不一致: "
            f"missing={missing}, unexpected={unexpected}"
        )

    for filename, expected_hash in OCR_MODEL_FILES.values():
        model_path = model_dir / filename
        actual_hash = _sha256(model_path)
        if actual_hash.lower() != expected_hash.lower():
            raise RuntimeError(f"OCR模型哈希校验失败: {model_path}")

    requirements_path = project_root / "requirements.txt"
    pinned = _load_pinned_requirements(requirements_path)
    mismatches = {
        name: {"expected": expected, "actual": pinned.get(name)}
        for name, expected in OCR_REQUIRED_REQUIREMENTS.items()
        if pinned.get(name) != expected
    }
    if mismatches:
        raise RuntimeError(f"OCR运行依赖版本不符合打包清单: {mismatches}")


def _validate_paths(project_root: Path) -> None:
    missing_paths: list[str] = []

    for source, _target in DATA_DIR_SPECS:
        if not (project_root / source).exists():
            missing_paths.append(source)

    for source, _target in DATA_FILE_SPECS:
        if not (project_root / source).is_file():
            missing_paths.append(source)

    main_py = project_root / "main.py"
    if not main_py.is_file():
        missing_paths.append("main.py")

    if missing_paths:
        joined = "\n".join(f"  - {path}" for path in missing_paths)
        raise FileNotFoundError(f"Missing required Nuitka build inputs:\n{joined}")

    _validate_ocr_build_inputs(project_root)


def _build_command(output_dir: str) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--mode=standalone",
        "--windows-console-mode=disable",
        "--windows-icon-from-ico=resources/icon.ico",
        "--windows-uac-admin",
        "--enable-plugins=pyside6",
    ]

    command.extend(f"--include-package={package_name}" for package_name in INCLUDE_PACKAGES)
    command.extend(f"--include-package-data={package_name}" for package_name in INCLUDE_PACKAGE_DATA)
    command.extend(f"--include-module={module_name}" for module_name in INCLUDE_MODULES)
    command.extend(f"--nofollow-import-to={module_name}" for module_name in NOFOLLOW_IMPORTS)
    command.extend(f"--include-data-dir={source}={target}" for source, target in DATA_DIR_SPECS)
    command.extend(f"--include-data-files={source}={target}" for source, target in DATA_FILE_SPECS)
    command.extend(f"--noinclude-dlls={pattern}" for pattern in NOINCLUDE_DLLS)
    command.append(f"--output-dir={Path(output_dir).as_posix()}")
    command.append("main.py")
    return command


def _resolve_output_dir(project_root: Path, output_dir: str) -> Path:
    resolved_output_dir = Path(output_dir)
    if not resolved_output_dir.is_absolute():
        resolved_output_dir = project_root / resolved_output_dir
    return resolved_output_dir.resolve()


def _resolve_result_exe(output_dir: Path) -> Path:
    return (output_dir / RESULT_EXE_RELATIVE_PATH).resolve()


def _wait_for_build_artifact(
    exe_path: Path,
    timeout_seconds: float = BUILD_ARTIFACT_WAIT_TIMEOUT_SECONDS,
    poll_interval_seconds: float = BUILD_ARTIFACT_POLL_INTERVAL_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: OSError | None = None

    while True:
        try:
            if exe_path.is_file():
                with exe_path.open("rb"):
                    return
        except OSError as exc:
            last_error = exc

        if time.monotonic() >= deadline:
            break
        time.sleep(poll_interval_seconds)

    if last_error is not None:
        raise RuntimeError(f"Nuitka 已返回成功，但产物仍不可访问: {exe_path}\n{last_error}") from last_error
    raise FileNotFoundError(f"Nuitka 已返回成功，但未找到产物: {exe_path}")


def _matches_dll_exclude_pattern(relative_path: Path, patterns: tuple[str, ...]) -> bool:
    normalized_path = relative_path.as_posix().lower()
    normalized_name = relative_path.name.lower()
    for pattern in patterns:
        normalized_pattern = str(pattern).replace("\\", "/").lower()
        if fnmatch.fnmatch(normalized_path, normalized_pattern):
            return True
        if fnmatch.fnmatch(normalized_name, normalized_pattern):
            return True
    return False


def _remove_excluded_runtime_dlls(dist_dir: Path) -> list[tuple[Path, int]]:
    if not dist_dir.is_dir():
        return []

    removed: list[tuple[Path, int]] = []
    for file_path in sorted(path for path in dist_dir.rglob("*") if path.is_file()):
        relative_path = file_path.relative_to(dist_dir)
        if not _matches_dll_exclude_pattern(relative_path, RUNTIME_DLL_REMOVE_PATTERNS):
            continue
        file_size = int(file_path.stat().st_size)
        file_path.unlink()
        removed.append((relative_path, file_size))
    return removed


def _normalize_windows_text(value: str) -> str:
    return value.replace("/", "\\").strip().lower()


def _make_writable_and_retry(func, path, exc_info) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        raise exc_info[1]


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return

    last_error: OSError | None = None
    for attempt in range(DELETE_RETRY_COUNT):
        try:
            shutil.rmtree(path, onerror=_make_writable_and_retry)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last_error = exc
            if attempt + 1 >= DELETE_RETRY_COUNT:
                break
            time.sleep(DELETE_RETRY_DELAY_SECONDS)

    assert last_error is not None
    raise RuntimeError(f"清理目录失败: {path}\n{last_error}") from last_error


def _load_windows_processes() -> list[ProcessInfo]:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", WINDOWS_PROCESS_QUERY],
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "未知错误"
        raise RuntimeError(f"读取进程列表失败: {detail}")

    payload = result.stdout.strip()
    if not payload:
        return []

    raw_items = json.loads(payload)
    if isinstance(raw_items, dict):
        raw_items = [raw_items]

    processes: list[ProcessInfo] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        processes.append(
            ProcessInfo(
                process_id=int(raw_item.get("ProcessId") or 0),
                parent_process_id=int(raw_item.get("ParentProcessId") or 0),
                name=str(raw_item.get("Name") or ""),
                executable_path=str(raw_item.get("ExecutablePath") or ""),
                command_line=str(raw_item.get("CommandLine") or ""),
            )
        )
    return processes


def _is_project_nuitka_process(process: ProcessInfo, project_root: Path) -> bool:
    if process.process_id <= 0 or process.process_id == os.getpid():
        return False
    if process.name.lower() != "python.exe":
        return False

    command_line = _normalize_windows_text(process.command_line)
    project_token = _normalize_windows_text(str(project_root))
    if project_token not in command_line:
        return False

    return (
        "run_nuitka_main_build.py" in command_line
        or ("scons.py" in command_line and "nuitka" in command_line)
        or " -m nuitka" in command_line
    )


def _extract_ccache_owner_pids(build_dir: Path) -> set[int]:
    if not build_dir.is_dir():
        return set()

    owner_pids: set[int] = set()
    for child in build_dir.iterdir():
        if not child.is_file():
            continue
        matched = CCACHE_OWNER_PATTERN.fullmatch(child.name)
        if matched:
            owner_pids.add(int(matched.group(1)))
    return owner_pids


def _find_process_tree_root(
    processes_by_pid: dict[int, ProcessInfo],
    process_id: int,
    project_root: Path,
) -> int | None:
    process = processes_by_pid.get(process_id)
    if process is None or not _is_project_nuitka_process(process, project_root):
        return None

    root_pid = process.process_id
    visited = {root_pid}
    current = process
    while current.parent_process_id and current.parent_process_id not in visited:
        parent = processes_by_pid.get(current.parent_process_id)
        if parent is None or not _is_project_nuitka_process(parent, project_root):
            break
        root_pid = parent.process_id
        current = parent
        visited.add(root_pid)

    return root_pid


def _terminate_process_tree(root_pid: int) -> None:
    result = subprocess.run(
        ["taskkill", "/PID", str(root_pid), "/T", "/F"],
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    if result.returncode != 0:
        detail = result.stdout.strip() or result.stderr.strip() or "未知错误"
        raise RuntimeError(f"结束残留构建进程失败(PID {root_pid}): {detail}")


def _terminate_stale_build_processes(build_dir: Path, project_root: Path) -> list[int]:
    owner_pids = _extract_ccache_owner_pids(build_dir)
    if not owner_pids:
        return []

    processes = _load_windows_processes()
    processes_by_pid = {process.process_id: process for process in processes if process.process_id > 0}

    root_pids: set[int] = set()
    for owner_pid in owner_pids:
        root_pid = _find_process_tree_root(processes_by_pid, owner_pid, project_root)
        if root_pid is not None:
            root_pids.add(root_pid)

    for root_pid in sorted(root_pids):
        _terminate_process_tree(root_pid)

    return sorted(root_pids)


def _prepare_output_dirs(project_root: Path, output_dir: Path) -> None:
    try:
        _remove_tree(output_dir)
    except RuntimeError as exc:
        stale_roots = _terminate_stale_build_processes(output_dir / "main.build", project_root)
        if not stale_roots:
            raise RuntimeError(
                f"{exc}\n未识别到可安全结束的残留 Nuitka 构建进程，请先检查是否有其他构建仍在运行。"
            ) from exc

        print(
            "检测到残留 Nuitka 构建进程，正在清理:"
            f" {', '.join(str(root_pid) for root_pid in stale_roots)}"
        )
        time.sleep(PROCESS_EXIT_GRACE_SECONDS)
        _remove_tree(output_dir)

    _remove_tree(project_root / "nuitka_dist")


def main() -> int:
    args = _parse_args()
    project_root = Path(args.project_root).resolve()
    output_dir = _resolve_output_dir(project_root, args.output_dir)
    result_exe = _resolve_result_exe(output_dir)

    try:
        _validate_paths(project_root)
        _prepare_output_dirs(project_root, output_dir)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        result = subprocess.run(
            _build_command(str(output_dir)),
            cwd=project_root,
            check=False,
        )
    except OSError as exc:
        print(f"Failed to start Nuitka build: {exc}", file=sys.stderr)
        return 1

    if result.returncode != 0:
        return result.returncode

    try:
        _wait_for_build_artifact(result_exe)
    except (FileNotFoundError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    removed_excluded_dlls = _remove_excluded_runtime_dlls(result_exe.parent)
    if removed_excluded_dlls:
        removed_size = sum(file_size for _relative_path, file_size in removed_excluded_dlls)
        print(
            "removed_excluded_runtime_dlls="
            f"{len(removed_excluded_dlls)} files, {removed_size / 1024 / 1024:.2f} MB"
        )
        for relative_path, _file_size in removed_excluded_dlls:
            print(f"  - {relative_path.as_posix()}")

    print(f"result_exe={result_exe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
