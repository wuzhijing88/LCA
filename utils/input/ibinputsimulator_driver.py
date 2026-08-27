#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import atexit
import base64
import ctypes
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from ctypes import wintypes
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

from utils.app_paths import get_app_root
from utils.input_simulation.mode_utils import normalize_ib_driver_name
from utils.input.input_timing import DEFAULT_CLICK_HOLD_SECONDS, DEFAULT_KEY_HOLD_SECONDS
from utils.input.logitech_runtime import detect_logitech_runtime
from utils.precise_sleep import precise_sleep as _shared_precise_sleep


logger = logging.getLogger(__name__)

_DEFAULT_KEY_HOLD_SECONDS = DEFAULT_KEY_HOLD_SECONDS
_DEFAULT_CLICK_HOLD_SECONDS = DEFAULT_CLICK_HOLD_SECONDS


_AHK_OFFLINE_ZIP_NAMES = (
    "ahk-v2.zip",
    "AutoHotkey-v2.zip",
    "AutoHotkey.zip",
)

_IB_OFFLINE_ZIP_NAMES = (
    "Binding.AHK2.zip",
    "ibinputsimulator.zip",
    "IbInputSimulator.zip",
)

_IB_RUNTIME_DEPENDENCY_DLLS = (
    "concrt140.dll",
    "msvcp140.dll",
    "vcomp140.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
)


def _is_workflow_worker_relative_trace_enabled() -> bool:
    value = str(os.environ.get("LCA_WORKFLOW_WORKER", "") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


class RequestAbortedError(RuntimeError):
    """请求被主动中断。"""


class IbInputSimulatorDriver:
    """IbInputSimulator AHK2 桥接驱动。"""

    _SPECIAL_KEYS = {
        "enter": "Enter",
        "return": "Enter",
        "tab": "Tab",
        "space": "Space",
        "spacebar": "Space",
        "esc": "Esc",
        "escape": "Esc",
        "backspace": "Backspace",
        "delete": "Delete",
        "ins": "Insert",
        "insert": "Insert",
        "home": "Home",
        "end": "End",
        "pageup": "PgUp",
        "page_up": "PgUp",
        "pagedown": "PgDn",
        "page_down": "PgDn",
        "pgup": "PgUp",
        "pgdn": "PgDn",
        "printscreen": "PrintScreen",
        "print_screen": "PrintScreen",
        "capslock": "CapsLock",
        "caps_lock": "CapsLock",
        "numlock": "NumLock",
        "num_lock": "NumLock",
        "scrolllock": "ScrollLock",
        "scroll_lock": "ScrollLock",
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
        "ctrl": "Ctrl",
        "control": "Ctrl",
        "lctrl": "LCtrl",
        "left_ctrl": "LCtrl",
        "rctrl": "RCtrl",
        "right_ctrl": "RCtrl",
        "shift": "Shift",
        "lshift": "LShift",
        "left_shift": "LShift",
        "rshift": "RShift",
        "right_shift": "RShift",
        "alt": "Alt",
        "lalt": "LAlt",
        "left_alt": "LAlt",
        "ralt": "RAlt",
        "right_alt": "RAlt",
        "win": "LWin",
        "windows": "LWin",
        "lwin": "LWin",
        "left_win": "LWin",
        "rwin": "RWin",
        "right_win": "RWin",
        "numpad0": "Numpad0",
        "numpad1": "Numpad1",
        "numpad2": "Numpad2",
        "numpad3": "Numpad3",
        "numpad4": "Numpad4",
        "numpad5": "Numpad5",
        "numpad6": "Numpad6",
        "numpad7": "Numpad7",
        "numpad8": "Numpad8",
        "numpad9": "Numpad9",
        "numpad+": "NumpadAdd",
        "numpadadd": "NumpadAdd",
        "numpad-": "NumpadSub",
        "numpadsub": "NumpadSub",
        "numpad*": "NumpadMult",
        "numpadmult": "NumpadMult",
        "numpad/": "NumpadDiv",
        "numpaddiv": "NumpadDiv",
        "numpad.": "NumpadDot",
        "numpaddot": "NumpadDot",
    }

    def __init__(self, driver: str = "Logitech", driver_arg: str = ""):
        normalized_driver = normalize_ib_driver_name(driver)

        self._driver_name = normalized_driver
        self._runtime_driver_name = normalized_driver
        self._driver_arg = str(driver_arg or "").strip()

        self._process: Optional[subprocess.Popen[str]] = None
        self._wrapper_script_path: Optional[str] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._response_queue: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.RLock()
        self._mouse_lock = threading.RLock()
        self._key_lock = threading.RLock()
        self._abort_request_event = threading.Event()
        # 追踪按下未释放输入，停止/退出时统一回收。
        self._pressed_keys = set()
        self._pressed_mouse_buttons = set()
        self._sendinput_pressed_keys = set()
        self._request_id = 0
        self._ready = False
        self._recent_stderr: List[str] = []
        self._last_error_message = ""
        self._worker_core_source_path: Optional[Path] = None
        self._worker_core_source_mtime_ns: int = 0
        self._runtime_base_dir: Optional[Path] = None
        self._runtime_session_dir: Optional[Path] = None

        self._startup_timeout = 8.0
        self._request_timeout = 8.0
        self._mouse_request_timeout = 20.0
        self._response_poll_interval = 0.05
        self._alignment_fast_retry_count = 1
        self._alignment_fast_retry_sleep = 0.004
        self._alignment_recovery_budget_seconds = 0.12
        self._alignment_rebuild_cooldown = 0.35
        self._alignment_rebuild_failure_threshold = 2
        self._alignment_consecutive_failures = 0
        self._last_alignment_rebuild_ts = 0.0
        try:
            if getattr(sys, "frozen", False):
                self._startup_timeout = 15.0
        except Exception:
            pass

        atexit.register(self.close)

    def _get_file_mtime_ns(self, path: Optional[Path]) -> int:
        try:
            if not path:
                return 0
            return int(path.stat().st_mtime_ns)
        except Exception:
            return 0

    def _iter_root_candidates(self) -> List[Path]:
        return [Path(get_app_root()).resolve()]

    def _get_writable_storage_root(self) -> Path:
        root = Path(get_app_root()).resolve()
        (root / "tools" / "ibinputsimulator").mkdir(parents=True, exist_ok=True)
        return root

    def initialize(self) -> bool:
        with self._lock:
            self._abort_request_event.clear()
            if str(self._driver_name or "").strip().lower() == "logitech":
                runtime_result = detect_logitech_runtime()
                if not runtime_result.compatible:
                    self.close()
                    self._abort_request_event.clear()
                    self._last_error_message = runtime_result.driver_error()
                    logger.error(runtime_result.user_message().replace("\n", " "))
                    return False
                self._runtime_driver_name = runtime_result.send_type
                logger.info(
                    "Logitech 输入运行时已选择: "
                    f"driver={self._runtime_driver_name}, "
                    f"product={runtime_result.detected_name} {runtime_result.detected_version}, "
                    f"source={runtime_result.source}"
                )
            else:
                self._runtime_driver_name = self._driver_name
            if self._ready and self._is_alive():
                return True

            self.close()
            self._abort_request_event.clear()

            try:
                ahk_exe = self._find_ahk_exe()
                include_file = self._find_ib_include_file()
                core_script = self._find_worker_core_script()
                source_core_script = core_script
                source_core_mtime_ns = self._get_file_mtime_ns(source_core_script)
                include_file, core_script, runtime_base, runtime_dir = self._prepare_worker_runtime_files(
                    include_file=include_file,
                    core_script=core_script,
                )
                self._runtime_base_dir = runtime_base
                self._runtime_session_dir = runtime_dir
                wrapper_content = self._build_wrapper_script(include_file, core_script)
                self._wrapper_script_path = self._write_temp_script(
                    content=wrapper_content,
                    preferred_dir=include_file.parent,
                )

                creation_flags = 0
                if os.name == "nt":
                    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                runtime_env = self._build_subprocess_env(include_file=include_file, ahk_exe=ahk_exe)

                self._process = subprocess.Popen(
                    [ahk_exe, "/ErrorStdOut=UTF-8", self._wrapper_script_path],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    cwd=str(include_file.parent),
                    env=runtime_env,
                    creationflags=creation_flags,
                )

                self._response_queue = queue.Queue()
                self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
                self._reader_thread.start()

                self._wait_ready(self._startup_timeout)
                self._ready = True
                self._last_error_message = ""
                self._worker_core_source_path = source_core_script
                self._worker_core_source_mtime_ns = source_core_mtime_ns
                logger.info(
                    "IbInputSimulator 驱动初始化成功: "
                    f"configured={self._driver_name}, runtime={self._runtime_driver_name}"
                )
                return True
            except Exception as exc:
                detail = self._collect_stderr()
                self._log_debug_context(ahk_exe if 'ahk_exe' in locals() else "", include_file if 'include_file' in locals() else None, core_script if 'core_script' in locals() else None)
                message = str(exc or "").strip() or exc.__class__.__name__
                self._last_error_message = f"{message} | {detail}" if detail else message
                if detail:
                    logger.error(f"IbInputSimulator 驱动初始化失败: {message} | {detail}")
                else:
                    logger.error(f"IbInputSimulator 驱动初始化失败: {message}")
                self.close()
                return False

    def get_last_error(self) -> str:
        return str(self._last_error_message or "")

    def _log_debug_context(self, ahk_exe: str, include_file: Optional[Path], core_script: Optional[Path]) -> None:
        try:
            include_path = str(include_file) if include_file else ""
            core_path = str(core_script) if core_script else ""
            include_dll = ""
            if include_file:
                include_dll = str(include_file.parent / "IbInputSimulator.dll")
            logger.error(
                "IbInputSimulator init context: "
                f"driver={self._driver_name}, runtime_driver={self._runtime_driver_name}, "
                f"ahk_exe={ahk_exe}, ahk_exists={bool(ahk_exe and os.path.isfile(ahk_exe))}, "
                f"include={include_path}, include_exists={bool(include_path and os.path.isfile(include_path))}, "
                f"dll={include_dll}, dll_exists={bool(include_dll and os.path.isfile(include_dll))}, "
                f"worker={core_path}, worker_exists={bool(core_path and os.path.isfile(core_path))}"
            )
        except Exception:
            return

    def _is_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _reader_loop(self) -> None:
        process = self._process
        if not process:
            self._response_queue.put("__EOF__")
            return

        stdout = process.stdout
        stderr = process.stderr

        def read_stderr() -> None:
            if stderr is None:
                return
            try:
                for line in stderr:
                    msg = line.rstrip("\r\n")
                    if msg:
                        if len(self._recent_stderr) >= 20:
                            self._recent_stderr = self._recent_stderr[-19:]
                        self._recent_stderr.append(msg)
            except Exception:
                return

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()

        if stdout is None:
            self._response_queue.put("__EOF__")
            try:
                if stderr_thread.is_alive():
                    stderr_thread.join(timeout=0.2)
            except Exception:
                pass
            return

        try:
            for line in stdout:
                self._response_queue.put(line.rstrip("\r\n"))
        except Exception as exc:
            if len(self._recent_stderr) >= 20:
                self._recent_stderr = self._recent_stderr[-19:]
            self._recent_stderr.append(f"stdout reader error: {exc}")
        finally:
            self._response_queue.put("__EOF__")
            try:
                if stderr_thread.is_alive():
                    stderr_thread.join(timeout=0.2)
            except Exception:
                pass

    def _wait_ready(self, timeout: float) -> None:
        deadline = time.monotonic() + max(0.5, float(timeout))
        while time.monotonic() < deadline:
            if self._abort_request_event.is_set():
                raise RequestAbortedError("worker ready wait aborted")
            if not self._is_alive():
                raise RuntimeError(self._collect_stderr() or "worker exited")

            try:
                line = self._response_queue.get(timeout=self._response_poll_interval)
            except queue.Empty:
                continue

            if line == "READY":
                return
            if line == "__EOF__":
                raise RuntimeError(self._collect_stderr() or "worker exited")
            if line.startswith("ERR\t0\t"):
                parts = line.split("\t", 2)
                detail = self._decode_token(parts[2]) if len(parts) >= 3 else "worker init failed"
                detail_text = str(detail or "").strip()
                if not detail_text:
                    detail_text = self._collect_stderr() or "worker init failed"
                raise RuntimeError(detail_text)

        raise TimeoutError("worker ready timeout")

    def _collect_stderr(self) -> str:
        if not self._recent_stderr:
            return ""
        return " | ".join(self._recent_stderr[-3:])

    def _is_ahk_v2_script(self, script_path: Path) -> bool:
        try:
            text = script_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return False

        lower_text = text.lower()
        if "#requires autohotkey v2" in lower_text:
            return True

        if "setworkingdir," in lower_text and "%a_scriptdir%" in lower_text:
            return False

        if "setworkingdir(" in lower_text:
            return True

        return False

    def _escape_ahk_string(self, text: str) -> str:
        value = str(text or "")
        value = value.replace("`", "``")
        value = value.replace('"', '""')
        return value

    def _build_wrapper_script(self, include_file: Path, core_script: Path) -> str:
        include_path = self._escape_ahk_string(str(include_file))
        core_path = self._escape_ahk_string(str(core_script))
        driver_name = self._escape_ahk_string(self._runtime_driver_name)
        driver_arg = self._escape_ahk_string(self._driver_arg)

        return (
            "#Requires AutoHotkey v2.0\n"
            "#SingleInstance Force\n"
            "#NoTrayIcon\n"
            f"#Include \"{include_path}\"\n"
            f"#Include \"{core_path}\"\n"
            f"IbWorkerMain(\"{driver_name}\", \"{driver_arg}\")\n"
        )

    def _write_temp_script(self, content: str, preferred_dir: Optional[Path] = None) -> str:
        target_dir = None
        try:
            if preferred_dir:
                preferred_dir.mkdir(parents=True, exist_ok=True)
                target_dir = str(preferred_dir)
        except Exception:
            target_dir = None

        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".ahk",
            prefix="ibworker_",
            encoding="utf-8",
            newline="\n",
            delete=False,
            dir=target_dir,
        )
        try:
            tmp.write(content)
            return tmp.name
        finally:
            tmp.close()

    def _is_directory_writable(self, directory: Path) -> bool:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / f".lca_ib_probe_{os.getpid()}_{int(time.time() * 1000)}.tmp"
            with open(probe, "w", encoding="utf-8") as probe_file:
                probe_file.write("ok")
            try:
                probe.unlink()
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _get_runtime_base_dir(self) -> Path:
        storage_root = self._get_writable_storage_root()
        runtime_base = storage_root / "runtime" / "ibinputsimulator" / "Binding.AHK2"
        runtime_base.mkdir(parents=True, exist_ok=True)
        return runtime_base

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except Exception:
            return False

    def _cleanup_stale_runtime_sessions(self, runtime_base: Optional[Path], keep_dir: Optional[Path] = None) -> None:
        if runtime_base is None:
            return
        try:
            session_dirs = list(runtime_base.glob("session_*"))
        except Exception:
            return
        keep_key = str(keep_dir.resolve()).lower() if keep_dir else ""
        now_ts = time.time()
        for session_dir in session_dirs:
            try:
                if not session_dir.is_dir():
                    continue
                session_key = str(session_dir.resolve()).lower()
                if keep_key and session_key == keep_key:
                    continue
            except Exception:
                continue

            dir_name = session_dir.name
            pid_match = re.match(r"^session_(\d+)_", dir_name)
            if pid_match:
                try:
                    owner_pid = int(pid_match.group(1))
                except Exception:
                    owner_pid = 0
                if owner_pid > 0 and self._is_pid_alive(owner_pid):
                    continue
            else:
                try:
                    age_seconds = now_ts - session_dir.stat().st_mtime
                    if age_seconds < 300:
                        continue
                except Exception:
                    continue

            try:
                shutil.rmtree(session_dir)
            except Exception:
                continue

    def _prepare_worker_runtime_files(self, include_file: Path, core_script: Path) -> Tuple[Path, Path, Path, Path]:
        include_dir = include_file.parent
        dll_file = include_dir / "IbInputSimulator.dll"
        runtime_base = self._get_runtime_base_dir()
        self._cleanup_stale_runtime_sessions(runtime_base=runtime_base, keep_dir=self._runtime_session_dir)
        runtime_dir = Path(
            tempfile.mkdtemp(
                prefix=f"session_{os.getpid()}_",
                dir=str(runtime_base),
            )
        )

        runtime_include = runtime_dir / "IbInputSimulator.ahk"
        runtime_dll = runtime_dir / "IbInputSimulator.dll"
        runtime_core = runtime_dir / "ib_worker_core.ahk"

        if not dll_file.is_file():
            raise FileNotFoundError("missing IbInputSimulator.dll")

        shutil.copy2(include_file, runtime_include)
        shutil.copy2(dll_file, runtime_dll)
        shutil.copy2(core_script, runtime_core)
        self._patch_runtime_include_dll_load(runtime_include=runtime_include, runtime_dll=runtime_dll)
        self._copy_runtime_dependency_dlls(target_dir=runtime_dir, include_dir=include_dir)

        return runtime_include, runtime_core, runtime_base, runtime_dir

    def _patch_runtime_include_dll_load(self, runtime_include: Path, runtime_dll: Path) -> None:
        try:
            content = runtime_include.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return

        dll_path = str(runtime_dll).replace("\\", "/").replace('"', '""')
        patched_line = f'#DllLoad "*i {dll_path}"'
        pattern = re.compile(r"^\s*#DllLoad\b.*$", re.MULTILINE)

        if pattern.search(content):
            content = pattern.sub(patched_line, content, count=1)
        else:
            content = f'{patched_line}\n{content}'

        try:
            runtime_include.write_text(content, encoding="utf-8", newline="\n")
        except Exception:
            return

    def _copy_runtime_dependency_dlls(self, target_dir: Path, include_dir: Path) -> None:
        search_dirs: List[Path] = []
        seen = set()

        def add_dir(path_value: Any) -> None:
            try:
                path_obj = Path(path_value).resolve()
            except Exception:
                return
            key = str(path_obj).lower()
            if key in seen or not path_obj.is_dir():
                return
            seen.add(key)
            search_dirs.append(path_obj)

        add_dir(include_dir)

        try:
            current = include_dir
            for _ in range(6):
                current = current.parent
                add_dir(current)
        except Exception:
            pass

        for root in self._iter_root_candidates():
            add_dir(root)
            add_dir(root / "AutoHotkey")
            add_dir(root / "tools" / "ibinputsimulator" / "Binding.AHK2")

        win_dir = os.environ.get("WINDIR", r"C:\Windows")
        add_dir(Path(win_dir) / "System32")

        for dll_name in _IB_RUNTIME_DEPENDENCY_DLLS:
            destination = target_dir / dll_name
            if destination.is_file():
                continue
            for source_dir in search_dirs:
                source = source_dir / dll_name
                if source.is_file():
                    try:
                        shutil.copy2(source, destination)
                    except Exception:
                        pass
                    break

    def _build_subprocess_env(self, include_file: Path, ahk_exe: str) -> dict:
        env = os.environ.copy()
        search_dirs: List[str] = []
        seen = set()

        def add_path(path_value: Any) -> None:
            try:
                path_obj = Path(path_value).resolve()
            except Exception:
                return
            if not path_obj.exists():
                return
            key = str(path_obj).lower()
            if key in seen:
                return
            seen.add(key)
            search_dirs.append(str(path_obj))

        add_path(include_file.parent)
        try:
            current = include_file.parent
            for _ in range(6):
                current = current.parent
                add_path(current)
        except Exception:
            pass

        try:
            add_path(Path(ahk_exe).resolve().parent)
        except Exception:
            pass

        for root in self._iter_root_candidates():
            add_path(root)
            add_path(root / "AutoHotkey")
            add_path(root / "tools" / "ibinputsimulator" / "Binding.AHK2")

        win_dir = os.environ.get("WINDIR", r"C:\Windows")
        add_path(Path(win_dir) / "System32")

        current_path = str(env.get("PATH", "") or "")
        env["PATH"] = os.pathsep.join(search_dirs + ([current_path] if current_path else []))
        return env

    def _find_ahk_exe(self) -> str:
        candidates: List[Path] = []

        for root in self._iter_root_candidates():
            candidates.extend(
                [
                    root / "AutoHotkey" / "AutoHotkey64.exe",
                    root / "AutoHotkey" / "v2" / "AutoHotkey64.exe",
                    root / "AutoHotkey" / "AutoHotkey.exe",
                    root / "AutoHotkey" / "v2" / "AutoHotkey.exe",
                ]
            )

        env_ahk = str(os.environ.get("AUTOHOTKEY_EXE", "") or "").strip()
        if env_ahk:
            candidates.insert(0, Path(env_ahk))

        for exe_name in ("AutoHotkey64.exe", "AutoHotkey.exe"):
            found = shutil.which(exe_name)
            if found:
                candidates.append(Path(found))

        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        candidates.extend(
            [
                Path(pf) / "AutoHotkey" / "v2" / "AutoHotkey64.exe",
                Path(pf) / "AutoHotkey" / "v2" / "AutoHotkey.exe",
                Path(pf) / "AutoHotkey" / "AutoHotkey64.exe",
                Path(pf) / "AutoHotkey" / "AutoHotkey.exe",
            ]
        )

        seen = set()
        for item in candidates:
            key = str(item).lower()
            if key in seen:
                continue
            seen.add(key)
            if item.is_file():
                return str(item)

        installed = self._install_ahk_from_local_package()
        if installed and installed.is_file():
            return str(installed)

        raise FileNotFoundError("未找到 AutoHotkey v2 可执行文件")

    def _install_ahk_from_local_package(self) -> Optional[Path]:
        """解压本机已有的 AutoHotkey v2 安装包。"""
        project_root = self._get_writable_storage_root()
        ahk_root = project_root / "AutoHotkey"
        ahk_root.mkdir(parents=True, exist_ok=True)

        direct_candidates = [
            ahk_root / "AutoHotkey64.exe",
            ahk_root / "AutoHotkey.exe",
            ahk_root / "v2" / "AutoHotkey64.exe",
            ahk_root / "v2" / "AutoHotkey.exe",
            ahk_root / "AutoHotkeyUX.exe",
        ]
        for item in direct_candidates:
            if item.is_file():
                return item

        package_sources = [project_root, ahk_root, project_root / "offline", Path.cwd()]
        package_path = next(
            (
                source_dir / package_name
                for source_dir in package_sources
                for package_name in _AHK_OFFLINE_ZIP_NAMES
                if (source_dir / package_name).is_file()
            ),
            None,
        )
        if package_path is None:
            return None

        try:
            with zipfile.ZipFile(package_path, "r") as archive:
                archive.extractall(ahk_root)
        except Exception as exc:
            logger.error(f"解压本地 AutoHotkey 安装包失败: {exc}")
            return None

        post_candidates = [
            ahk_root / "AutoHotkey64.exe",
            ahk_root / "AutoHotkey.exe",
            ahk_root / "v2" / "AutoHotkey64.exe",
            ahk_root / "v2" / "AutoHotkey.exe",
            ahk_root / "AutoHotkeyUX.exe",
            ahk_root / "AutoHotkey32.exe",
        ]
        for item in post_candidates:
            if item.is_file():
                return item

        nested_candidates = list(ahk_root.rglob("AutoHotkey64.exe")) + list(ahk_root.rglob("AutoHotkey.exe"))
        for item in nested_candidates:
            if item.is_file():
                return item

        logger.error("本地 AutoHotkey 安装包中未找到可执行文件")
        return None

    def _find_ib_include_file(self) -> Path:
        explicit_file = str(os.environ.get("IBINPUTSIMULATOR_AHK", "") or "").strip()
        if explicit_file:
            candidate = Path(explicit_file)
            if candidate.is_file() and candidate.name.lower() == "ibinputsimulator.ahk":
                if self._is_ahk_v2_script(candidate):
                    return candidate
                raise FileNotFoundError("指定的 IbInputSimulator.ahk 不是 AHK2 版本")

        roots: List[Path] = []
        explicit_dir = str(os.environ.get("IBINPUTSIMULATOR_DIR", "") or "").strip()
        if explicit_dir:
            roots.append(Path(explicit_dir))

        root_candidates = self._iter_root_candidates()
        for root in root_candidates:
            roots.append(root / "tools" / "ibinputsimulator" / "Binding.AHK2")
            roots.append(root / "tools" / "ibinputsimulator")

        seen = set()
        for root in roots:
            key = str(root).lower()
            if key in seen:
                continue
            seen.add(key)

            include_path = root / "IbInputSimulator.ahk"
            if include_path.is_file():
                dll_path = root / "IbInputSimulator.dll"
                if self._is_ahk_v2_script(include_path) and dll_path.is_file():
                    return include_path

        search_roots = [root / "tools" / "ibinputsimulator" for root in root_candidates]
        for search_root in search_roots:
            if not search_root.exists():
                continue
            try:
                nested = list(search_root.rglob("IbInputSimulator.ahk"))
            except Exception:
                nested = []
            for candidate in nested:
                if self._is_ahk_v2_script(candidate):
                    candidate_dir = candidate.parent
                    candidate_dll = candidate_dir / "IbInputSimulator.dll"
                    if not candidate_dll.is_file():
                        continue
                    storage_root = self._get_writable_storage_root()
                    target_dir = storage_root / "tools" / "ibinputsimulator" / "Binding.AHK2"
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target_path = target_dir / "IbInputSimulator.ahk"
                    target_dll = target_dir / "IbInputSimulator.dll"
                    if candidate.resolve() != target_path.resolve():
                        try:
                            shutil.copy2(candidate, target_path)
                            shutil.copy2(candidate_dll, target_dll)
                        except Exception:
                            return candidate
                    return target_path

        installed = self._install_ib_library_from_local_package()
        if installed and installed.is_file() and self._is_ahk_v2_script(installed):
            if (installed.parent / "IbInputSimulator.dll").is_file():
                return installed

        raise FileNotFoundError("未找到 IbInputSimulator.ahk 或 IbInputSimulator.dll")

    def _install_ib_library_from_local_package(self) -> Optional[Path]:
        """解压本机已有的 IbInputSimulator 安装包。"""
        project_root = self._get_writable_storage_root()
        ib_root = project_root / "tools" / "ibinputsimulator"
        binding_dir = ib_root / "Binding.AHK2"
        binding_dir.mkdir(parents=True, exist_ok=True)

        direct_target = binding_dir / "IbInputSimulator.ahk"
        direct_dll = binding_dir / "IbInputSimulator.dll"
        if direct_target.is_file() and direct_dll.is_file() and self._is_ahk_v2_script(direct_target):
            return direct_target

        offline_sources = [
            project_root,
            project_root / "tools" / "ibinputsimulator",
            project_root / "tools" / "ibinputsimulator" / "offline",
            Path.cwd(),
        ]
        for source_dir in offline_sources:
            for zip_name in _IB_OFFLINE_ZIP_NAMES:
                offline_zip = source_dir / zip_name
                if offline_zip.is_file():
                    try:
                        shutil.copy2(offline_zip, ib_root / "ibinputsimulator.zip")
                        with zipfile.ZipFile(ib_root / "ibinputsimulator.zip", "r") as archive:
                            archive.extractall(ib_root)
                    except Exception as exc:
                        logger.error(f"离线包解压失败: {exc}")
                    finally:
                        try:
                            temp_zip = ib_root / "ibinputsimulator.zip"
                            if temp_zip.exists():
                                temp_zip.unlink()
                        except Exception:
                            pass

                    expected_offline = binding_dir / "IbInputSimulator.ahk"
                    expected_offline_dll = binding_dir / "IbInputSimulator.dll"
                    if expected_offline.is_file() and expected_offline_dll.is_file() and self._is_ahk_v2_script(expected_offline):
                        return expected_offline

        expected = binding_dir / "IbInputSimulator.ahk"
        expected_dll = binding_dir / "IbInputSimulator.dll"
        if expected.is_file() and expected_dll.is_file() and self._is_ahk_v2_script(expected):
            return expected

        nested = list(ib_root.rglob("IbInputSimulator.ahk"))
        if not nested:
            logger.error("本地 IbInputSimulator 安装包中未找到 IbInputSimulator.ahk")
            return None

        v2_candidates = [path for path in nested if self._is_ahk_v2_script(path)]
        if not v2_candidates:
            logger.error("本地 IbInputSimulator 安装包中未找到 AHK2 版本脚本")
            return None

        v2_candidates.sort(key=lambda path: ("binding.ahk2" not in str(path).lower(), len(str(path))))
        source = v2_candidates[0]
        try:
            source_dll = source.parent / "IbInputSimulator.dll"
            if not source_dll.is_file():
                logger.error("IbInputSimulator AHK2 脚本存在但缺少 IbInputSimulator.dll")
                return None
            binding_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, expected)
            shutil.copy2(source_dll, expected_dll)
            return expected if expected.is_file() else source
        except Exception:
            return source

    def _find_worker_core_script(self) -> Path:
        candidates: List[Path] = []
        for root in self._iter_root_candidates():
            candidates.append(root / "tools" / "ibinputsimulator" / "ib_worker_core.ahk")

        for item in candidates:
            if item.is_file():
                return item

        raise FileNotFoundError("未找到 AHK worker 脚本")

    def _encode_token(self, value: Any) -> str:
        if value is None:
            return "~"
        if isinstance(value, bool):
            return "b:1" if value else "b:0"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f"n:{value}"

        text = str(value)
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        return f"s:{payload}"

    def _decode_token(self, token: str) -> Any:
        if token == "~":
            return None
        if token.startswith("b:"):
            return token[2:] == "1"
        if token.startswith("n:"):
            number_text = token[2:]
            try:
                if any(ch in number_text for ch in (".", "e", "E")):
                    return float(number_text)
                return int(number_text)
            except Exception:
                return 0
        if token.startswith("s:"):
            payload = token[2:]
            try:
                return base64.b64decode(payload).decode("utf-8")
            except Exception:
                return ""
        return token

    def _ensure_ready(self) -> None:
        if self._ready and self._is_alive():
            if self._worker_core_source_path and self._worker_core_source_mtime_ns > 0:
                current_mtime_ns = self._get_file_mtime_ns(self._worker_core_source_path)
                if current_mtime_ns > 0 and current_mtime_ns != self._worker_core_source_mtime_ns:
                    self.close()
                else:
                    return
            else:
                return
        if not self.initialize():
            raise RuntimeError("IbInputSimulator 驱动未就绪")

    def _request(self, method: str, *args: Any, timeout: Optional[float] = None) -> List[Any]:
        with self._lock:
            if self._abort_request_event.is_set():
                raise RequestAbortedError("worker request aborted")
            self._ensure_ready()

            process = self._process
            if process is None or process.stdin is None:
                raise RuntimeError("工作线程标准输入不可用")

            self._request_id += 1
            req_id = str(self._request_id)
            tokens = [req_id, method] + [self._encode_token(arg) for arg in args]
            line = "\t".join(tokens) + "\n"
            trace_relative_move = (
                method == "move_mouse"
                and len(args) >= 3
                and not bool(args[2])
                and _is_workflow_worker_relative_trace_enabled()
            )
            if trace_relative_move:
                try:
                    trace_dx = int(args[0])
                except Exception:
                    trace_dx = args[0]
                try:
                    trace_dy = int(args[1])
                except Exception:
                    trace_dy = args[1]
                logger.info(f"[IbInputSimulator][relative] req={req_id} driver={self._driver_name} dx={trace_dx} dy={trace_dy}")

            try:
                process.stdin.write(line)
                process.stdin.flush()
            except Exception as exc:
                self._ready = False
                if trace_relative_move:
                    logger.error(f"[IbInputSimulator][relative] 写入失败 req={req_id} driver={self._driver_name} error={exc}")
                raise RuntimeError(f"工作线程写入失败：{exc}") from exc

            deadline = time.monotonic() + max(0.5, float(timeout or self._request_timeout))
            while time.monotonic() < deadline:
                if self._abort_request_event.is_set():
                    raise RequestAbortedError("worker request aborted")
                try:
                    response = self._response_queue.get(timeout=self._response_poll_interval)
                except queue.Empty:
                    if not self._is_alive():
                        self._ready = False
                        detail = self._collect_stderr() or "worker exited"
                        if trace_relative_move:
                            logger.error(f"[IbInputSimulator][relative] worker_exited req={req_id} driver={self._driver_name} detail={detail}")
                        raise RuntimeError(detail)
                    continue

                if response in ("", "READY"):
                    continue
                if response == "__EOF__":
                    self._ready = False
                    detail = self._collect_stderr() or "worker exited"
                    if trace_relative_move:
                        logger.error(f"[IbInputSimulator][relative] eof req={req_id} driver={self._driver_name} detail={detail}")
                    raise RuntimeError(detail)

                parts = response.split("\t")
                if len(parts) < 2:
                    continue
                if parts[1] != req_id:
                    continue

                payload = [self._decode_token(p) for p in parts[2:]]
                if parts[0] == "OK":
                    if trace_relative_move:
                        logger.info(f"[IbInputSimulator][relative] ok req={req_id} driver={self._driver_name}")
                    return payload
                if parts[0] == "ERR":
                    detail = str(payload[0]) if payload else ""
                    if not detail:
                        detail = self._collect_stderr() or f"{method} failed"
                    if trace_relative_move:
                        logger.error(f"[IbInputSimulator][relative] err req={req_id} driver={self._driver_name} detail={detail}")
                    raise RuntimeError(detail)

            if self._abort_request_event.is_set():
                raise RequestAbortedError("worker request aborted")
            if trace_relative_move:
                logger.error(f"[IbInputSimulator][relative] timeout req={req_id} driver={self._driver_name}")
            raise TimeoutError("worker response timeout")

    def _is_retryable_mouse_alignment_error(self, error: Exception) -> bool:
        text = str(error or "").strip().lower().replace(" ", "")
        if not text:
            return False
        keywords = (
            "targetverifyfailed",
            "drivermovefailed",
            "setcursorposfailed",
            "mousemovefailed",
        )
        return any(keyword in text for keyword in keywords)

    def _request_with_mouse_alignment_recovery(self, method: str, *args: Any, timeout: Optional[float] = None) -> bool:
        recovery_start_ts = time.monotonic()

        def _invoke_request() -> Tuple[bool, Optional[Exception]]:
            try:
                self._request(method, *args, timeout=timeout)
                return True, None
            except Exception as req_error:
                return False, req_error

        def _budget_exceeded() -> bool:
            try:
                budget = max(0.0, float(self._alignment_recovery_budget_seconds))
            except Exception:
                budget = 0.0
            if budget <= 0:
                return False
            return (time.monotonic() - recovery_start_ts) > budget

        ok, first_error = _invoke_request()
        if ok:
            self._alignment_consecutive_failures = 0
            return True

        if first_error is None:
            return False

        self._last_error_message = str(first_error or "").strip()
        if isinstance(first_error, RequestAbortedError):
            return False
        if not self._is_retryable_mouse_alignment_error(first_error):
            self._alignment_consecutive_failures = 0
            return False

        retry_count = max(0, int(self._alignment_fast_retry_count))
        fast_retry_error: Exception = first_error
        for _ in range(retry_count):
            if _budget_exceeded():
                break
            if self._alignment_fast_retry_sleep > 0:
                _shared_precise_sleep(self._alignment_fast_retry_sleep)
            retry_ok, retry_error = _invoke_request()
            if retry_ok:
                self._alignment_consecutive_failures = 0
                return True
            if retry_error is None:
                return False
            self._last_error_message = str(retry_error or "").strip()
            if isinstance(retry_error, RequestAbortedError):
                return False
            fast_retry_error = retry_error
            if not self._is_retryable_mouse_alignment_error(retry_error):
                self._alignment_consecutive_failures = 0
                return False

        self._alignment_consecutive_failures = min(
            1000,
            int(self._alignment_consecutive_failures) + 1,
        )

        if self._abort_request_event.is_set():
            return False

        if _budget_exceeded():
            return False

        if self._alignment_consecutive_failures < int(self._alignment_rebuild_failure_threshold):
            return False

        now_ts = time.monotonic()
        if (now_ts - self._last_alignment_rebuild_ts) < self._alignment_rebuild_cooldown:
            return False

        try:
            self.close()
        except Exception:
            return False

        try:
            if not self.initialize():
                return False
            self._last_alignment_rebuild_ts = time.monotonic()
            self._request(method, *args, timeout=timeout)
            self._last_error_message = ""
            self._alignment_consecutive_failures = 0
            return True
        except Exception as rebuild_error:
            if rebuild_error is not None:
                self._last_error_message = str(rebuild_error or "").strip()
            elif fast_retry_error is not None:
                self._last_error_message = str(fast_retry_error or "").strip()
            return False

    def _normalize_button(self, button: str) -> str:
        key = str(button or "left").strip().lower()
        if key in {"right", "r", "rbutton", "右键"}:
            return "right"
        if key in {"middle", "m", "mbutton", "中键"}:
            return "middle"
        return "left"

    def _normalize_key(self, key: str) -> str:
        text = str(key or "").strip()
        if not text:
            raise ValueError("按键不能为空")
        lower_text = text.lower()
        if lower_text in self._SPECIAL_KEYS:
            return self._SPECIAL_KEYS[lower_text]
        if lower_text.startswith("f") and lower_text[1:].isdigit():
            return f"F{lower_text[1:]}"
        return text

    @staticmethod
    def _is_modifier_key_name(key: Any) -> bool:
        return str(key or "").strip().lower() in {
            "ctrl",
            "control",
            "lctrl",
            "rctrl",
            "shift",
            "lshift",
            "rshift",
            "alt",
            "lalt",
            "ralt",
            "win",
            "lwin",
            "rwin",
        }

    @staticmethod
    def _sendinput_vk_for_key(key: Any) -> Optional[int]:
        text = str(key or "").strip()
        if not text:
            return None
        lower_text = text.lower()
        vk_map = {
            "ctrl": 0x11,
            "control": 0x11,
            "lctrl": 0xA2,
            "rctrl": 0xA3,
            "shift": 0x10,
            "lshift": 0xA0,
            "rshift": 0xA1,
            "alt": 0x12,
            "lalt": 0xA4,
            "ralt": 0xA5,
            "win": 0x5B,
            "lwin": 0x5B,
            "rwin": 0x5C,
            "enter": 0x0D,
            "return": 0x0D,
            "tab": 0x09,
            "space": 0x20,
            "esc": 0x1B,
            "escape": 0x1B,
            "backspace": 0x08,
            "delete": 0x2E,
            "insert": 0x2D,
            "home": 0x24,
            "end": 0x23,
            "pgup": 0x21,
            "pageup": 0x21,
            "pgdn": 0x22,
            "pagedown": 0x22,
            "up": 0x26,
            "down": 0x28,
            "left": 0x25,
            "right": 0x27,
        }
        if lower_text in vk_map:
            return vk_map[lower_text]
        if lower_text.startswith("f") and lower_text[1:].isdigit():
            f_index = int(lower_text[1:])
            if 1 <= f_index <= 24:
                return 0x70 + f_index - 1
        if len(text) == 1:
            vk = ctypes.windll.user32.VkKeyScanW(ord(text))
            if vk != -1:
                return int(vk) & 0xFF
        return None

    @classmethod
    def _sendinput_key_event(cls, key: Any, key_down: bool) -> bool:
        vk_code = cls._sendinput_vk_for_key(key)
        if vk_code is None:
            return False

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p),
            ]

        class INPUT_UNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]

        flags = 0 if key_down else 0x0002
        input_item = INPUT(type=1, union=INPUT_UNION(ki=KEYBDINPUT(vk_code, 0, flags, 0, None)))
        sent = ctypes.windll.user32.SendInput(1, ctypes.byref(input_item), ctypes.sizeof(INPUT))
        return int(sent or 0) == 1

    def _should_use_sendinput_modifier_support(self) -> bool:
        return str(self._driver_name or "").strip().lower() == "logitech"

    def _sendinput_set_key_state(self, key: Any, key_down: bool) -> bool:
        if not self._should_use_sendinput_modifier_support():
            return True
        normalized_key = str(key or "").strip()
        if not self._is_modifier_key_name(normalized_key):
            return True
        ok = self._sendinput_key_event(normalized_key, key_down)
        if ok:
            if key_down:
                self._sendinput_pressed_keys.add(normalized_key)
            else:
                self._sendinput_pressed_keys.discard(normalized_key)
        return ok

    def _sendinput_modified_key_press(
        self,
        key: Any,
        held_keys: Sequence[Any],
        duration: float,
    ) -> bool:
        if not self._should_use_sendinput_modifier_support():
            return False

        clean_held_keys = [str(item or "").strip() for item in held_keys or [] if str(item or "").strip()]
        if not clean_held_keys or not all(self._is_modifier_key_name(item) for item in clean_held_keys):
            return False

        pressed_now: List[str] = []
        try:
            for held_key in clean_held_keys:
                if held_key not in self._sendinput_pressed_keys:
                    if not self._sendinput_key_event(held_key, True):
                        return False
                    self._sendinput_pressed_keys.add(held_key)
                    pressed_now.append(held_key)

            if not self._sendinput_key_event(key, True):
                return False
            if duration > 0:
                _shared_precise_sleep(float(duration))
            if not self._sendinput_key_event(key, False):
                return False
            return True
        except Exception:
            return False

    def _serialize_points(self, points: Sequence[Sequence[Any]]) -> str:
        serialized: List[str] = []
        for item in points:
            if not item or len(item) < 2:
                continue
            serialized.append(f"{int(item[0])},{int(item[1])}")
        return ";".join(serialized)

    def _dispatch_mouse_button_event(
        self,
        method_name: str,
        normalized_button: str,
        target_x: Optional[int],
        target_y: Optional[int],
    ) -> bool:
        """统一发鼠标按键事件入口。"""
        try:
            if target_x is not None and target_y is not None:
                tx = int(target_x)
                ty = int(target_y)
                return self._request_with_mouse_alignment_recovery(
                    method_name,
                    tx,
                    ty,
                    normalized_button,
                    timeout=self._mouse_request_timeout,
                )

            return False
        except Exception:
            return False

    def _serialize_timestamps(self, timestamps: Optional[Sequence[Any]]) -> str:
        if not timestamps:
            return ""
        values: List[str] = []
        for item in timestamps:
            try:
                values.append(f"{float(item):.6f}")
            except Exception:
                values.append("0")
        return ";".join(values)

    def get_screen_size(self) -> Tuple[int, int]:
        payload = self._request("get_screen_size")
        if len(payload) >= 2:
            return int(payload[0]), int(payload[1])
        from utils.window.multi_monitor_manager import get_primary_screen_size
        return get_primary_screen_size()

    def get_mouse_position(self) -> Tuple[int, int]:
        payload = self._request("get_mouse_position")
        if len(payload) >= 2:
            return int(payload[0]), int(payload[1])
        point = wintypes.POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            return int(point.x), int(point.y)
        return 0, 0

    def move_mouse(self, x: int, y: int, absolute: bool = True) -> bool:
        with self._mouse_lock:
            self._request("move_mouse", int(x), int(y), bool(absolute))
        return True

    def click_mouse(self, x=None, y=None, button='left', clicks=1, interval=0.0, duration=0.0, **_kwargs) -> bool:
        if x is None or y is None:
            return False

        try:
            safe_clicks = max(1, int(clicks))
        except Exception:
            safe_clicks = 1
        try:
            safe_interval = max(0.0, float(interval))
        except Exception:
            safe_interval = 0.0
        try:
            safe_duration = max(0.0, float(duration))
        except Exception:
            safe_duration = _DEFAULT_CLICK_HOLD_SECONDS
        if safe_duration <= 0:
            safe_duration = _DEFAULT_CLICK_HOLD_SECONDS

        target_x = int(x)
        target_y = int(y)
        normalized_button = self._normalize_button(button)

        with self._mouse_lock:
            try:
                for i in range(safe_clicks):
                    if i > 0 and safe_interval > 0:
                        _shared_precise_sleep(safe_interval)
                    if not self._request_with_mouse_alignment_recovery(
                        "move_mouse",
                        target_x,
                        target_y,
                        True,
                        timeout=self._mouse_request_timeout,
                    ):
                        return False
                    if not self._dispatch_mouse_button_event("mouse_down", normalized_button, target_x, target_y):
                        return False
                    if safe_duration > 0:
                        _shared_precise_sleep(safe_duration)
                    if not self._dispatch_mouse_button_event("mouse_up", normalized_button, target_x, target_y):
                        return False
            except Exception:
                return False

        return True

    def mouse_down(self, x=None, y=None, button='left') -> bool:
        if x is None or y is None:
            return False
        target_x = int(x)
        target_y = int(y)
        normalized_button = self._normalize_button(button)
        with self._mouse_lock:
            if not self._request_with_mouse_alignment_recovery(
                "move_mouse",
                target_x,
                target_y,
                True,
                timeout=self._mouse_request_timeout,
            ):
                return False
            if not self._dispatch_mouse_button_event("mouse_down", normalized_button, target_x, target_y):
                return False
            self._pressed_mouse_buttons.add(normalized_button)
        return True

    def mouse_up(self, x=None, y=None, button='left') -> bool:
        if x is None or y is None:
            return False
        target_x = int(x)
        target_y = int(y)
        normalized_button = self._normalize_button(button)
        with self._mouse_lock:
            if not self._request_with_mouse_alignment_recovery(
                "move_mouse",
                target_x,
                target_y,
                True,
                timeout=self._mouse_request_timeout,
            ):
                return False
            if not self._dispatch_mouse_button_event("mouse_up", normalized_button, target_x, target_y):
                return False
            self._pressed_mouse_buttons.discard(normalized_button)
        return True

    def drag_mouse(self, start_x, start_y, end_x, end_y, button='left', duration=1.0) -> bool:
        with self._mouse_lock:
            self._request(
                "drag_mouse",
                int(start_x),
                int(start_y),
                int(end_x),
                int(end_y),
                self._normalize_button(button),
                max(0.0, float(duration)),
            )
        return True

    def drag_path(self, points, duration=1.0, button='left', timestamps=None) -> bool:
        if not points or len(points) < 2:
            raise ValueError("drag_path 至少需要两个点")
        points_text = self._serialize_points(points)
        if not points_text:
            raise ValueError("drag_path 参数无效")
        with self._mouse_lock:
            self._request(
                "drag_path",
                points_text,
                max(0.0, float(duration)),
                self._normalize_button(button),
                self._serialize_timestamps(timestamps),
            )
        return True

    def scroll_mouse(self, direction, clicks=1, x=None, y=None) -> bool:
        normalized = "up" if str(direction or "").strip().lower() == "up" else "down"
        with self._mouse_lock:
            self._request(
                "scroll_mouse",
                normalized,
                max(1, int(abs(int(clicks)))),
                None if x is None else int(x),
                None if y is None else int(y),
            )
        return True

    def key_down(self, key: str) -> bool:
        normalized_key = self._normalize_key(key)
        if not normalized_key:
            return False
        with self._key_lock:
            self._sendinput_set_key_state(normalized_key, True)
            self._request("key_down", normalized_key)
            self._pressed_keys.add(normalized_key)
        return True

    def key_up(self, key: str) -> bool:
        normalized_key = self._normalize_key(key)
        if not normalized_key:
            return False
        with self._key_lock:
            self._request("key_up", normalized_key)
            self._pressed_keys.discard(normalized_key)
            self._sendinput_set_key_state(normalized_key, False)
        return True

    def press_key(self, key: str, duration: float = _DEFAULT_KEY_HOLD_SECONDS) -> bool:
        normalized_key = self._normalize_key(key)
        try:
            hold_duration = max(0.0, float(duration))
        except Exception:
            hold_duration = _DEFAULT_KEY_HOLD_SECONDS

        with self._key_lock:
            try:
                # 由 worker 内部原子执行 down->hold->up，减少 IPC 往返抖动对按压时长的影响。
                self._request("press_key", normalized_key, hold_duration)
                self._pressed_keys.discard(normalized_key)
                return True
            except Exception:
                return False

    def modified_key_press(
        self,
        key: str,
        held_keys: Optional[Sequence[Any]] = None,
        duration: float = _DEFAULT_KEY_HOLD_SECONDS,
    ) -> bool:
        normalized_key = self._normalize_key(key)
        if not normalized_key:
            return False
        try:
            hold_duration = max(0.0, float(duration))
        except Exception:
            hold_duration = _DEFAULT_KEY_HOLD_SECONDS

        normalized_held_keys: List[str] = []
        for item in held_keys or []:
            held_key = self._normalize_key(str(item))
            if held_key and held_key != normalized_key:
                normalized_held_keys.append(held_key)

        if not normalized_held_keys:
            return self.press_key(normalized_key, hold_duration)

        with self._key_lock:
            try:
                if self._sendinput_modified_key_press(normalized_key, normalized_held_keys, hold_duration):
                    logger.info(
                        "[IbInputSimulator][Logitech] 使用 SendInput 组合键兜底: held=%s key=%s",
                        normalized_held_keys,
                        normalized_key,
                    )
                    for held_key in normalized_held_keys:
                        self._pressed_keys.add(held_key)
                    self._pressed_keys.discard(normalized_key)
                    return True

                self._request(
                    "modified_key_press",
                    normalized_key,
                    hold_duration,
                    *normalized_held_keys,
                )
                for held_key in normalized_held_keys:
                    self._pressed_keys.add(held_key)
                self._pressed_keys.discard(normalized_key)
                return True
            except Exception:
                return False

    def hotkey(self, *keys) -> bool:
        key_list = [self._normalize_key(str(item)) for item in keys if str(item).strip()]
        if not key_list:
            raise ValueError("组合键不能为空")
        with self._key_lock:
            self._request("hotkey", *key_list)
            for key_name in key_list:
                self._pressed_keys.discard(key_name)
        return True

    def type_text(self, text: str, **_kwargs) -> bool:
        content = str(text or "")
        if content == "":
            return True
        self._request("type_text", content)
        return True

    def release_all_inputs(self) -> bool:
        """释放当前驱动记录的全部按下输入。"""
        pending_keys = list(self._pressed_keys)
        pending_buttons = list(self._pressed_mouse_buttons)
        pending_sendinput_keys = list(self._sendinput_pressed_keys)

        if not pending_keys and not pending_buttons and not pending_sendinput_keys:
            return True

        try:
            if self._abort_request_event.is_set():
                for key_name in reversed(pending_sendinput_keys):
                    self._sendinput_key_event(key_name, False)
                self._sendinput_pressed_keys.clear()
                self._pressed_keys.clear()
                self._pressed_mouse_buttons.clear()
                return False

            self._request(
                "release_all_inputs",
                timeout=min(2.0, max(0.5, float(self._request_timeout))),
            )
            for key_name in reversed(pending_sendinput_keys):
                self._sendinput_key_event(key_name, False)
            self._sendinput_pressed_keys.clear()
            self._pressed_keys.clear()
            self._pressed_mouse_buttons.clear()
            return True
        except Exception:
            release_ok = True
            for key_name in pending_keys:
                try:
                    self._request(
                        "key_up",
                        key_name,
                        timeout=min(1.0, max(0.5, float(self._request_timeout))),
                    )
                except Exception:
                    release_ok = False
            for key_name in reversed(pending_sendinput_keys):
                try:
                    if not self._sendinput_key_event(key_name, False):
                        release_ok = False
                except Exception:
                    release_ok = False
            self._sendinput_pressed_keys.clear()
            self._pressed_keys.clear()
            self._pressed_mouse_buttons.clear()
            return release_ok

    def close(self) -> None:
        try:
            self.release_all_inputs()
        except Exception:
            pass
        self._abort_request_event.set()
        with self._lock:
            process = self._process
            reader_thread = self._reader_thread
            runtime_session_dir = self._runtime_session_dir
            runtime_base_dir = self._runtime_base_dir
            if process and process.poll() is None:
                try:
                    if process.stdin:
                        self._request_id += 1
                        process.stdin.write(f"{self._request_id}\texit\n")
                        process.stdin.flush()
                except Exception:
                    pass

            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=2.0)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass

            if process:
                try:
                    if process.stdin:
                        process.stdin.close()
                except Exception:
                    pass
                try:
                    if process.stdout:
                        process.stdout.close()
                except Exception:
                    pass
                try:
                    if process.stderr:
                        process.stderr.close()
                except Exception:
                    pass

            if (
                reader_thread is not None
                and reader_thread is not threading.current_thread()
                and reader_thread.is_alive()
            ):
                try:
                    reader_thread.join(timeout=1.0)
                except Exception:
                    pass

            if self._wrapper_script_path:
                try:
                    os.remove(self._wrapper_script_path)
                except Exception:
                    pass

            if runtime_session_dir:
                try:
                    shutil.rmtree(runtime_session_dir)
                except Exception:
                    pass

            self._cleanup_stale_runtime_sessions(runtime_base=runtime_base_dir, keep_dir=None)

            self._process = None
            self._wrapper_script_path = None
            self._reader_thread = None
            self._response_queue = queue.Queue()
            self._ready = False
            self._request_id = 0
            self._recent_stderr = []
            self._worker_core_source_path = None
            self._worker_core_source_mtime_ns = 0
            self._alignment_consecutive_failures = 0
            self._runtime_base_dir = None
            self._runtime_session_dir = None
            self._pressed_keys.clear()
            self._pressed_mouse_buttons.clear()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
