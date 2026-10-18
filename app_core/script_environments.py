"""Private Python runtime and the installation's shared script_venv."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from contextlib import ExitStack, contextmanager
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from app_core.runtime.process_tree import terminate_process_tree
from app_core.script_process_job import ProcessJob
from services.worker_process_cleanup import (
    register_worker_process,
    unregister_worker_process,
)

RUNTIME_ID = "cpython-3.12.12-20251014-windows-x64"
RUNTIME_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/20251014/"
    "cpython-3.12.12%2B20251014-x86_64-pc-windows-msvc-install_only.tar.gz"
)
RUNTIME_SHA256 = "2d670beb3b930d30e3a13cc909923a001dbdfcb5537692d5da40b6b41643ce1c"
DEFAULT_INDEX = "https://mirrors.aliyun.com/pypi/simple"
WORKER_FLAG = "--script-environment-worker"


class EnvironmentError(RuntimeError):
    pass


class _WindowsFileLock:
    def __init__(self, stream, shared):
        import ctypes
        import msvcrt
        from ctypes import wintypes

        class Overlapped(ctypes.Structure):
            _fields_ = [
                ("Internal", ctypes.c_size_t),
                ("InternalHigh", ctypes.c_size_t),
                ("Offset", wintypes.DWORD),
                ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE),
            ]

        self.ctypes = ctypes
        self.overlapped = Overlapped()
        self.handle = wintypes.HANDLE(msvcrt.get_osfhandle(stream.fileno()))
        self.flags = 1 | (0 if shared else 2)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.acquire = kernel.LockFileEx
        self.acquire.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(Overlapped),
        ]
        self.acquire.restype = wintypes.BOOL
        self.release = kernel.UnlockFileEx
        self.release.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(Overlapped),
        ]
        self.release.restype = wintypes.BOOL

    def lock(self):
        if not self.acquire(
            self.handle, self.flags, 0, 1, 0, self.ctypes.byref(self.overlapped)
        ):
            raise self.ctypes.WinError(self.ctypes.get_last_error())

    def unlock(self):
        if not self.release(self.handle, 0, 1, 0, self.ctypes.byref(self.overlapped)):
            raise self.ctypes.WinError(self.ctypes.get_last_error())


def normalize_environment(value=None):
    if value is None:
        value = {"mode": "builtin"}
    if not isinstance(value, dict):
        raise EnvironmentError("脚本运行环境必须是对象")
    unknown = set(value) - {"mode", "interpreter", "requirements", "index_url"}
    if unknown:
        raise EnvironmentError(
            "脚本运行环境包含未知设置：" + "、".join(sorted(unknown))
        )
    mode = value.get("mode")
    if not isinstance(mode, str) or mode not in {"builtin", "isolated"}:
        raise EnvironmentError("脚本运行环境只能选择内置或独立环境")
    interpreter = value.get("interpreter", "")
    requirements = value.get("requirements", [])
    index = value.get("index_url", DEFAULT_INDEX)
    if not isinstance(interpreter, str) or not isinstance(index, str):
        raise EnvironmentError("Python 路径和软件源必须是文本")
    from urllib.parse import urlsplit

    parsed = urlsplit(index)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise EnvironmentError("软件源必须是无账号密码的 HTTPS 地址")
    if not isinstance(requirements, list) or any(
        not isinstance(item, str) for item in requirements
    ):
        raise EnvironmentError("依赖列表必须是包名文本列表")
    normalized = []
    seen = set()
    for item in requirements:
        try:
            requirement = Requirement(item)
        except InvalidRequirement as exc:
            raise EnvironmentError(f"依赖格式不正确：{item}") from exc
        if requirement.url is not None or "\n" in item or "\r" in item:
            raise EnvironmentError(
                "依赖请填写软件源中的包名和版本，不能填写网址或安装选项"
            )
        name = canonicalize_name(requirement.name)
        if name in seen:
            raise EnvironmentError(f"依赖重复：{requirement.name}")
        seen.add(name)
        normalized.append(str(requirement))
    return {
        "mode": mode,
        "interpreter": interpreter.strip(),
        "requirements": sorted(normalized),
        "index_url": index.rstrip("/"),
    }


def clean_python_env(executable=None):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("PYTHON", "PIP_"))
        and key.upper() not in {"VIRTUAL_ENV", "__PYVENV_LAUNCHER__"}
    }
    env.update(
        PYTHONIOENCODING="utf-8",
        PYTHONUTF8="1",
        PIP_CONFIG_FILE=os.devnull,
        PYTHONUNBUFFERED="1",
        PIP_DISABLE_PIP_VERSION_CHECK="1",
        PIP_NO_INPUT="1",
    )
    if executable is not None:
        directory = Path(executable).resolve().parent
        env["PATH"] = str(directory) + os.pathsep + env.get("PATH", "")
        if (directory.parent / "pyvenv.cfg").is_file():
            env["VIRTUAL_ENV"] = str(directory.parent)
    return env


class EnvironmentManager:
    def __init__(self, root=None, *, stop_checker=None, progress=None):
        if root is None:
            from utils.app_paths import get_app_root

            root = get_app_root()
        self.root = Path(root).resolve()
        self.directory = self.root / "script_venv"
        self.storage = self.root / "script_environments"
        self.executable = self.directory / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        self.stop_checker = stop_checker
        self.progress = progress or (lambda message: None)

    def check_stop(self):
        if self.stop_checker is not None and self.stop_checker():
            raise EnvironmentError("已停止")

    @contextmanager
    def _lock(self, key, *, shared=False):
        self.check_stop()
        directory = self.storage / "locks"
        directory.mkdir(parents=True, exist_ok=True)
        stream = (directory / (key + ".lock")).open("a+b")
        locked = False
        windows_lock = None
        try:
            if os.name == "nt":
                windows_lock = _WindowsFileLock(stream, shared)
            stream.seek(0, os.SEEK_END)
            if not stream.tell():
                stream.write(b"0")
                stream.flush()
            reported = False
            while not locked:
                self.check_stop()
                stream.seek(0)
                try:
                    if windows_lock is not None:
                        windows_lock.lock()
                    else:
                        import fcntl

                        fcntl.flock(
                            stream.fileno(),
                            (fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
                            | fcntl.LOCK_NB,
                        )
                    locked = True
                except OSError as exc:
                    if exc.errno not in (11, 13, 35, 36) and getattr(
                        exc, "winerror", None
                    ) not in (32, 33):
                        raise
                    if not reported:
                        self.progress("正在等待同一环境的任务结束")
                        reported = True
                    time.sleep(0.1)
            yield
        finally:
            try:
                if locked:
                    stream.seek(0)
                    if windows_lock is not None:
                        windows_lock.unlock()
                    else:
                        import fcntl

                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            finally:
                stream.close()

    def _run(self, command, *, timeout=900, cwd=None, capture_limit=16000):
        self.check_stop()
        command = [command[0], "-X", "utf8", *command[1:]]
        with tempfile.TemporaryDirectory(prefix="lca-environment-") as temporary:
            path = Path(temporary) / "output.log"
            try:
                with path.open("wb") as output, path.open("rb") as reader:
                    return self._run_logged(
                        command,
                        output,
                        reader,
                        timeout=timeout,
                        cwd=cwd,
                        capture_limit=capture_limit,
                    )
            except OSError as exc:
                raise self._tool_failure(str(exc)) from exc

    def _run_logged(self, command, output, reader, *, timeout, cwd, capture_limit):
        with ProcessJob() as job:
            return self._run_owned(
                command,
                output,
                reader,
                job,
                timeout=timeout,
                cwd=cwd,
                capture_limit=capture_limit,
            )

    def _run_owned(self, command, output, reader, job, *, timeout, cwd, capture_limit):
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            env=clean_python_env(command[0]),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        registered = False
        try:
            job.assign(process)
            if process.poll() is None:
                register_worker_process(process, WORKER_FLAG)
                registered = True
            deadline = time.monotonic() + timeout
            tail = ""
            while True:
                self.check_stop()
                if time.monotonic() > deadline:
                    raise EnvironmentError("准备脚本环境超时")
                chunk = reader.read(8192)
                text = chunk.decode("utf-8", errors="replace").replace("\r", "")
                tail = (tail + text)[-capture_limit:]
                if process.poll() is not None and not chunk:
                    break
                time.sleep(0.05)
            if process.returncode:
                raise self._tool_failure(tail, process.returncode)
            return tail
        finally:
            try:
                if process.poll() is None:
                    terminate_process_tree(process, wait_timeout=3, force=True)
            finally:
                if registered and process.poll() is not None:
                    unregister_worker_process(process)

    def _tool_failure(self, output, exit_code=None):
        text = output.lower()
        reasons = (
            (("certificate_verify_failed", "certificate verify failed"), "HTTPS 证书校验失败"),
            (("proxyerror", "cannot connect to proxy"), "代理连接失败"),
            (("timed out", "timeouterror"), "连接或下载超时"),
            (("getaddrinfo failed", "name resolution", "connection refused", "connection aborted",
              "network is unreachable", "could not fetch url"), "无法连接软件源或下载服务"),
            (("no space left on device", "disk full", "winerror 112"), "磁盘空间不足"),
            (("permission denied", "access is denied", "winerror 5", "winerror 32"), "目录或文件访问被拒绝"),
            (("requires a different python", "not a supported wheel", "requires-python"),
             "依赖不支持当前 Python 版本或系统架构"),
            (("no matching distribution found", "could not find a version that satisfies"),
             "软件源中没有符合要求的安装包或版本"),
            (("resolutionimpossible", "conflicting dependencies", "has requirement"), "依赖版本冲突"),
            (("which is not installed", "no module named"), "缺少所需的依赖模块"),
            (("failed building wheel", "failed to build", "subprocess-exited-with-error"), "依赖构建失败"),
            (("assertionerror",), "指定的基础 Python 不符合环境要求"),
        )
        reason = next((message for terms, message in reasons if any(term in text for term in terms)),
                      "环境工具执行失败，具体原因未知")
        # Keep one bounded diagnostic file; tool output is never user-facing status text.
        diagnostic = self.storage / "diagnostics" / "last-error.log"
        operation = f"准备脚本环境失败（退出码 {exit_code}）" if exit_code is not None else "脚本环境操作失败"
        prefix = operation + "：" + reason
        try:
            diagnostic.parent.mkdir(parents=True, exist_ok=True)
            diagnostic.write_text(prefix + "\n\n" + output[-65536:], "utf-8")
        except OSError as exc:
            raise EnvironmentError(prefix + "；无法保存诊断文件：" + str(diagnostic)) from exc
        return EnvironmentError(prefix + "；诊断文件：" + str(diagnostic))

    def _managed_python(self):
        if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
            raise EnvironmentError(
                "自动下载 Python 仅支持 Windows x64，请指定完整 Python 解释器"
            )
        with self._lock("runtime-" + RUNTIME_ID):
            target = self.storage / "runtimes" / RUNTIME_ID
            python = target / "python" / "python.exe"
            marker = target / "ready.json"
            if target.exists():
                if not marker.is_file() or json.loads(marker.read_text("utf-8")) != {
                    "sha256": RUNTIME_SHA256
                }:
                    raise EnvironmentError(
                        "独立 Python 运行时损坏，请在环境目录删除该运行时后重新准备"
                    )
                if not python.is_file():
                    raise EnvironmentError("独立 Python 运行时缺少解释器")
                return python
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="download-", dir=target.parent
            ) as temporary:
                stage = Path(temporary)
                archive = stage / "python.tar.gz"
                self.progress("正在下载独立 Python 3.12.12（约 43 MB）")
                digest = hashlib.sha256()
                started = time.monotonic()
                size = 0
                last_report = -1
                with (
                    urllib.request.urlopen(RUNTIME_URL, timeout=5) as response,
                    archive.open("wb") as output,
                ):
                    while True:
                        self.check_stop()
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > 128 * 1024 * 1024 or time.monotonic() - started > 600:
                            raise EnvironmentError("独立 Python 下载超出大小或时间限制")
                        digest.update(chunk)
                        output.write(chunk)
                        megabytes = size // (4 * 1024 * 1024)
                        if megabytes != last_report:
                            self.progress(f"Python 已下载 {size // (1024 * 1024)} MB")
                            last_report = megabytes
                if digest.hexdigest() != RUNTIME_SHA256:
                    raise EnvironmentError("独立 Python 下载校验失败")
                self.progress("正在解压并校验独立 Python")
                unpacked = stage / "unpacked"
                unpacked.mkdir()
                with tarfile.open(archive, "r:gz") as bundle:
                    expanded = 0
                    for member in bundle:
                        self.check_stop()
                        destination = (unpacked / member.name).resolve()
                        if not destination.is_relative_to(unpacked) or not (
                            member.isfile() or member.isdir()
                        ):
                            raise EnvironmentError(
                                "独立 Python 压缩包包含不允许的路径或文件类型"
                            )
                        expanded += member.size
                        if expanded > 1024 * 1024 * 1024:
                            raise EnvironmentError("独立 Python 解压大小超出限制")
                        bundle.extract(member, unpacked)
                executable = unpacked / "python" / "python.exe"
                self._run(
                    [
                        str(executable),
                        "-I",
                        "-c",
                        "import venv, ensurepip, ssl; print('Python 运行时就绪')",
                    ],
                    timeout=60,
                )
                self.progress("Python 运行时就绪")
                (unpacked / "ready.json").write_text(
                    json.dumps({"sha256": RUNTIME_SHA256}), "utf-8"
                )
                unpacked.rename(target)
            return python

    @contextmanager
    def prepare(self, settings):
        settings = normalize_environment(settings)
        if settings["mode"] != "isolated":
            raise EnvironmentError("当前脚本未选择独立环境")
        with ExitStack() as lease:
            try:
                with self._lock("prepare"):
                    self._prepare_locked(settings)
                    lease.enter_context(self._lock("use", shared=True))
            except (OSError, ValueError, tarfile.TarError) as exc:
                raise self._tool_failure(str(exc)) from exc
            self.progress("脚本环境就绪：" + str(self.executable))
            yield self.executable

    def _record(self):
        marker = self.directory / "ready.json"
        lock = self.directory / "requirements.lock"
        if not marker.is_file() or not self.executable.is_file():
            raise EnvironmentError("脚本环境未完成或已损坏，请删除后重新准备：" + str(self.directory))
        try:
            record = json.loads(marker.read_text("utf-8"))
            if (set(record) != {"interpreter", "python", "packages", "requirements"}
                    or not all(isinstance(record[k], str) for k in ("interpreter", "python", "packages"))):
                raise ValueError("无效的环境记录")
            normalize_environment({"mode": "isolated", "requirements": record["requirements"]})
        except (ValueError, TypeError, EnvironmentError) as exc:
            raise EnvironmentError("脚本环境记录损坏，请删除后重新准备：" + str(self.directory)) from exc
        if not lock.is_file() or lock.read_text("utf-8") != record["packages"]:
            raise EnvironmentError("依赖锁定清单损坏：" + str(self.directory))
        return record

    def _snapshot(self):
        output = self._run(
            [str(self.executable), "-I", "-c", (
                "import importlib.metadata as m,json,sys,struct; "
                "from pip._vendor.packaging.markers import default_environment; "
                "print(json.dumps({'executable':sys.executable,'exists':True,"
                "'identity':json.dumps([sys.version,struct.calcsize('P')*8,sys.base_prefix]),"
                "'markers':default_environment(),"
                "'packages':sorted([[d.metadata['Name'],d.version] for d in m.distributions()],"
                "key=lambda d:d[0].lower())}))"
            )], timeout=60, capture_limit=1024 * 1024,
        )
        if len(output) >= 1024 * 1024:
            raise EnvironmentError("已安装库列表超过大小限制")
        try:
            return json.loads(output)
        except ValueError as exc:
            raise EnvironmentError("读取已安装库列表失败") from exc

    def inspect(self):
        """Read the actual environment without creating it or downloading packages."""
        empty = {"exists": False, "executable": str(self.executable), "packages": []}
        if not self.directory.exists():
            return empty
        try:
            with self._lock("prepare"), self._lock("use", shared=True):
                if not self.directory.exists():
                    return empty
                record = self._record()
                snapshot = self._snapshot()
                if snapshot["identity"] != record["python"]:
                    raise EnvironmentError("脚本环境 Python 校验失败，请删除后重新准备")
                return snapshot
        except OSError as exc:
            raise self._tool_failure(str(exc)) from exc

    @staticmethod
    def _satisfied(requirements, snapshot):
        installed = {canonicalize_name(name): version for name, version in snapshot["packages"]}
        for text in requirements:
            req = Requirement(text)
            if req.marker is not None and not req.marker.evaluate(snapshot["markers"]):
                continue
            version = installed.get(canonicalize_name(req.name))
            if version is None or not req.specifier.contains(version, prereleases=True):
                return False
        return True

    def _save_record(self, interpreter, identity, requirements):
        freeze = self._run(
            [str(self.executable), "-I", "-m", "pip", "freeze", "--all"],
            timeout=60, capture_limit=1024 * 1024,
        )
        if len(freeze) >= 1024 * 1024:
            raise EnvironmentError("依赖锁定清单超过大小限制")
        (self.directory / "requirements.lock").write_text(freeze, "utf-8")
        (self.directory / "ready.json").write_text(json.dumps({
            "interpreter": interpreter, "python": identity, "packages": freeze,
            "requirements": requirements,
        }, ensure_ascii=False, indent=2), "utf-8")

    def _prepare_locked(self, settings):
        marker = self.directory / "ready.json"
        if self.directory.exists():
            record = self._record()
            if os.path.normcase(record["interpreter"]) != os.path.normcase(settings["interpreter"]):
                raise EnvironmentError("基础 Python 已变更，请先删除 script_venv 再准备环境")
            with self._lock("use", shared=True):
                snapshot = self._snapshot()
                if snapshot["identity"] != record["python"]:
                    raise EnvironmentError("脚本环境 Python 校验失败，请删除后重新准备")
                locked = record["packages"].splitlines()
                repair = not self._satisfied(locked, snapshot)
                install = not self._satisfied(settings["requirements"], snapshot) or any(
                    Requirement(req).extras and req not in record["requirements"]
                    for req in settings["requirements"]
                )
                if not repair and not install:
                    self._check_dependencies(self.executable)
                    return
            with self._lock("use"):
                # Interrupted package mutations must never be advertised as ready.
                marker.unlink()
                if repair:
                    self._install(self.executable, {**settings, "requirements": locked},
                                  constraint=self.directory / "requirements.lock")
                    snapshot = self._snapshot()
                    install = not self._satisfied(settings["requirements"], snapshot) or any(
                        Requirement(req).extras and req not in record["requirements"]
                        for req in settings["requirements"]
                    )
                if install:
                    self._install(self.executable, settings)
                snapshot = self._snapshot()
                if not self._satisfied(settings["requirements"], snapshot):
                    raise EnvironmentError("依赖安装后仍未满足要求，请删除环境后重新准备")
                if install:
                    self._save_record(record["interpreter"], record["python"], settings["requirements"])
                else:
                    # A repair restores the exact recorded versions.
                    marker.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
            return
        python = Path(settings["interpreter"]) if settings["interpreter"] else self._managed_python()
        if not python.is_absolute() or not python.is_file():
            raise EnvironmentError("指定的 Python 解释器不存在或不是绝对路径")
        identity = self._run([
            str(python), "-I", "-c", (
                "import sys,struct,json,venv,ensurepip; "
                "assert sys.implementation.name=='cpython' and (3,10)<=sys.version_info[:2]<=(3,14); "
                "print(json.dumps([sys.version,struct.calcsize('P')*8,sys.base_prefix]))"
            )], timeout=60,
        ).strip()
        self.progress("正在创建脚本专用环境 script_venv")
        with self._lock("use"):
            try:
                self._run([str(python), "-I", "-m", "venv", str(self.directory)], timeout=120)
                self._install(self.executable, settings)
                self._save_record(settings["interpreter"], identity, settings["requirements"])
            except BaseException:
                if self.directory.exists():
                    shutil.rmtree(self.directory)
                raise

    def _install(self, executable, settings, *, constraint=None):
        if settings["requirements"]:
            self.progress("正在使用软件源：" + settings["index_url"])
            self.progress("正在检查并安装依赖：" + "、".join(settings["requirements"]))
            self._run(
                [
                    str(executable),
                    "-I",
                    "-m",
                    "pip",
                    "install",
                    "--no-input",
                    "--disable-pip-version-check",
                    "--progress-bar",
                    "off",
                    "--retries",
                    "0",
                    "--timeout",
                    "15",
                    "--index-url",
                    settings["index_url"],
                    *([] if constraint is None else ["--constraint", str(constraint)]),
                    *settings["requirements"],
                ]
            )
            self.progress("依赖安装完成")
        self._check_dependencies(executable)

    def _check_dependencies(self, executable):
        self.progress("正在检查依赖完整性")
        self._run([str(executable), "-I", "-m", "pip", "check"], timeout=60)
        self.progress("依赖检查通过")

    def delete(self):
        try:
            with self._lock("prepare"), self._lock("use"):
                if self.directory.exists():
                    shutil.rmtree(self.directory)
                self.progress("脚本专用环境已删除")
        except OSError as exc:
            raise self._tool_failure(str(exc)) from exc
