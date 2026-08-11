from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "LCA 版本备份中心"
REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?(?:[-+][0-9A-Za-z.-]+)?$")
LARGE_FILE_LIMIT_MB = 50
LARGE_FILE_LIMIT = LARGE_FILE_LIMIT_MB * 1024 * 1024
DANGEROUS_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(^|/)venv/", "虚拟环境"),
    (r"(^|/)\.venv/", "虚拟环境"),
    (r"(^|/)env/", "虚拟环境"),
    (r"(^|/)__pycache__/", "Python 缓存"),
    (r"\.pyc$", "Python 缓存"),
    (r"(^|/)\.codex_tmp/", "临时目录"),
    (r"(^|/)logs?/", "日志目录"),
    (r"\.log$", "日志文件"),
    (r"^build_assets/packaging/(build_output|release_output)/", "打包产物"),
    (r"(^|/)备份/", "本地备份目录"),
    (r"^certs/", "证书目录"),
    (r"^lcaa\.top_cert/", "证书目录"),
    (r"^config/credentials\.json$", "本机密钥/凭据"),
    (r"^runtime/state/", "运行状态"),
    (r"^tools/17173_rocom_shijie_export/", "生成的地图导出"),
    (r"^tools/17173_map_probe/", "生成的探测输出"),
    (r"\.(zip|7z|rar|tar|tgz|gz)$", "压缩包"),
    (r"\.(pem|key|crt|cer|pfx|p12)$", "证书/私钥"),
    (r"\.(db|db-shm|db-wal|sqlite|sqlite3)$", "数据库"),
    (r"\.(onnx|pdmodel|pdiparams|pdparams|lcares)$", "模型/大资源包"),
)


class GitError(RuntimeError):
    def __init__(self, command: str, output: str = "") -> None:
        super().__init__(command)
        self.output = output


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str


@dataclass(frozen=True)
class StatusEntry:
    index: str
    worktree: str
    path: str
    raw: str

    @property
    def staged(self) -> bool:
        return self.index not in (" ", "?")

    @property
    def unstaged(self) -> bool:
        return self.worktree not in (" ", "") or self.index == "?"

    @property
    def state_label(self) -> str:
        if self.index == "?":
            return "未跟踪"
        if self.staged and self.unstaged:
            return "已暂存+又修改"
        if self.staged:
            return "已暂存"
        return "未暂存"


@dataclass(frozen=True)
class TagEntry:
    name: str
    date: str
    commit: str
    subject: str


@dataclass(frozen=True)
class CommitEntry:
    commit: str
    date: str
    subject: str


@dataclass(frozen=True)
class BundleEntry:
    path: Path
    size_bytes: int
    modified: str

    @property
    def size_text(self) -> str:
        return human_size(self.size_bytes)


@dataclass(frozen=True)
class PreflightReport:
    ok: bool
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def run_command(cmd: list[str], check: bool = True) -> CommandResult:
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if check and proc.returncode != 0:
        raise GitError(" ".join(cmd), output)
    return CommandResult(proc.returncode, output)


def run_git(*args: str, check: bool = True) -> str:
    return run_command(["git", *args], check=check).output


def git_exit_code(*args: str) -> int:
    return run_command(["git", *args], check=False).returncode


def default_backup_dir() -> Path:
    for drive in "DEFGHIJKLMNOPQRSTUVWXYZ":
        root = Path(f"{drive}:/")
        try:
            if root.exists():
                return root / "LCA-git-backups"
        except OSError:
            continue
    return Path("C:/LCA-git-backups")


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", value.strip())
    return cleaned.strip(".-") or "version"


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def folder_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def parse_status(output: str) -> list[StatusEntry]:
    entries: list[StatusEntry] = []
    for raw in output.splitlines():
        if len(raw) < 4:
            continue
        path = raw[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        entries.append(StatusEntry(raw[0], raw[1], path, raw))
    return entries


def parse_tags(output: str) -> list[TagEntry]:
    tags: list[TagEntry] = []
    for raw in output.splitlines():
        parts = raw.split("\t", 3)
        if len(parts) >= 4:
            tags.append(TagEntry(parts[0], parts[1], parts[2], parts[3]))
    return tags


def parse_commits(output: str) -> list[CommitEntry]:
    commits: list[CommitEntry] = []
    for raw in output.splitlines():
        parts = raw.split("\t", 2)
        if len(parts) >= 3:
            commits.append(CommitEntry(parts[0], parts[1], parts[2]))
    return commits


def normalize_tag(tag: str) -> str:
    value = tag.strip()
    if not VERSION_RE.match(value):
        raise ValueError("版本号格式应类似 v1.2.6.4 或 1.2.6.4")
    return value if value.startswith("v") else "v" + value


def version_tuple(tag: str) -> tuple[int, int, int, int] | None:
    match = VERSION_RE.match(tag.strip())
    if not match:
        return None
    major, minor, patch, build = match.groups()
    return int(major), int(minor), int(patch), int(build or 0)


def suggest_next_tag(tags: Iterable[TagEntry]) -> str:
    versions = [version for tag in tags if (version := version_tuple(tag.name))]
    if not versions:
        return "v1.0.0.1"
    major, minor, patch, build = max(versions)
    return f"v{major}.{minor}.{patch}.{build + 1}"


def risk_reason(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    for pattern, reason in DANGEROUS_PATTERNS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return reason
    try:
        full = REPO_ROOT / path
        if full.is_file() and full.stat().st_size > LARGE_FILE_LIMIT:
            return f"超过 {LARGE_FILE_LIMIT_MB} MB"
    except OSError:
        pass
    return None
class VersionBackupCenter(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1360x860")
        self.minsize(1120, 740)

        self.branch_var = tk.StringVar(value="-")
        self.latest_commit_var = tk.StringVar(value="-")
        self.latest_tag_var = tk.StringVar(value="-")
        self.worktree_var = tk.StringVar(value="-")
        self.hook_var = tk.StringVar(value="-")
        self.git_size_var = tk.StringVar(value="-")
        self.disk_var = tk.StringVar(value="-")
        self.footer_var = tk.StringVar(value="就绪")
        self.tag_var = tk.StringVar(value="")
        self.commit_message_var = tk.StringVar(value="")
        self.backup_dir_var = tk.StringVar(value=str(default_backup_dir()))
        self.include_changes_var = tk.BooleanVar(value=True)
        self.export_bundle_var = tk.BooleanVar(value=True)
        self.verify_bundle_var = tk.BooleanVar(value=True)
        self.restore_tag_var = tk.StringVar(value="")
        self.compare_from_var = tk.StringVar(value="")
        self.compare_to_var = tk.StringVar(value="")

        self.status_entries: list[StatusEntry] = []
        self.tag_entries: list[TagEntry] = []
        self.commit_entries: list[CommitEntry] = []
        self.bundle_entries: list[BundleEntry] = []

        self._build_ui()
        self.refresh_async()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        header = ttk.Frame(self, padding=(14, 12, 14, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="LCA 版本备份中心", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="刷新", command=self.refresh_async).grid(row=0, column=1, padx=(8, 0))

        summary = ttk.Frame(self, padding=(14, 0, 14, 10))
        summary.grid(row=1, column=0, sticky="ew")
        for col in range(7):
            summary.columnconfigure(col, weight=1)
        self._summary_item(summary, "当前分支", self.branch_var, 0)
        self._summary_item(summary, "最新提交", self.latest_commit_var, 1)
        self._summary_item(summary, "最新版本", self.latest_tag_var, 2)
        self._summary_item(summary, "工作区", self.worktree_var, 3)
        self._summary_item(summary, "安全保护", self.hook_var, 4)
        self._summary_item(summary, ".git 大小", self.git_size_var, 5)
        self._summary_item(summary, "备份盘空间", self.disk_var, 6)

        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 10))
        self._build_backup_center_tab()
        self._build_changes_tab()
        self._build_versions_tab()
        self._build_bundles_tab()
        self._build_logs_tab()

        footer = ttk.Frame(self, padding=(14, 0, 14, 12))
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.footer_var).grid(row=0, column=0, sticky="w")

    def _summary_item(self, parent: ttk.Frame, title: str, variable: tk.StringVar, col: int) -> None:
        frame = ttk.Frame(parent, padding=(0, 0, 12, 0))
        frame.grid(row=0, column=col, sticky="ew")
        ttk.Label(frame, text=title, foreground="#666").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, textvariable=variable, font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky="w")

    def _build_backup_center_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(1, weight=1)
        self.notebook.add(tab, text="备份中心")
        wizard = ttk.LabelFrame(tab, text="版本备份向导")
        wizard.grid(row=0, column=0, columnspan=2, sticky="ew")
        wizard.columnconfigure(1, weight=1)
        wizard.columnconfigure(4, weight=1)
        ttk.Label(wizard, text="版本号").grid(row=0, column=0, padx=10, pady=(10, 6), sticky="w")
        ttk.Entry(wizard, textvariable=self.tag_var).grid(row=0, column=1, padx=(0, 8), pady=(10, 6), sticky="ew")
        ttk.Button(wizard, text="建议下一个", command=self.suggest_next_version).grid(row=0, column=2, padx=(0, 12), pady=(10, 6))
        ttk.Label(wizard, text="提交说明").grid(row=0, column=3, padx=(0, 6), pady=(10, 6), sticky="w")
        ttk.Entry(wizard, textvariable=self.commit_message_var).grid(row=0, column=4, padx=(0, 10), pady=(10, 6), sticky="ew")
        ttk.Label(wizard, text="备份目录").grid(row=1, column=0, padx=10, pady=6, sticky="w")
        ttk.Entry(wizard, textvariable=self.backup_dir_var).grid(row=1, column=1, columnspan=3, padx=(0, 8), pady=6, sticky="ew")
        ttk.Button(wizard, text="选择", command=self.choose_backup_dir).grid(row=1, column=4, padx=(0, 10), pady=6, sticky="ew")
        options = ttk.Frame(wizard)
        options.grid(row=2, column=0, columnspan=5, sticky="ew", padx=10, pady=(4, 10))
        ttk.Checkbutton(options, text="把当前改动纳入本次备份", variable=self.include_changes_var).grid(row=0, column=0, padx=(0, 18), sticky="w")
        ttk.Checkbutton(options, text="导出 .bundle 备份包", variable=self.export_bundle_var).grid(row=0, column=1, padx=(0, 18), sticky="w")
        ttk.Checkbutton(options, text="导出后校验备份包", variable=self.verify_bundle_var).grid(row=0, column=2, sticky="w")
        actions = ttk.Frame(wizard)
        actions.grid(row=3, column=0, columnspan=5, sticky="ew", padx=10, pady=(0, 10))
        ttk.Button(actions, text="预检查", command=self.preflight_async).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="一键版本备份", command=self.run_version_backup_async).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(actions, text="打开备份目录", command=self.open_backup_folder).grid(row=0, column=2, padx=(0, 8))
        self.preflight_text = self._text_box(tab, height=15)
        self.preflight_text.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(10, 0))
        self.timeline_text = self._text_box(tab, height=15)
        self.timeline_text.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(10, 0))

    def _build_changes_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        self.notebook.add(tab, text="改动与提交")
        buttons = ttk.Frame(tab)
        buttons.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(buttons, text="暂存选中", command=self.stage_selected_async).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(buttons, text="取消暂存选中", command=self.unstage_selected_async).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(buttons, text="查看选中差异", command=self.diff_selected_async).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(buttons, text="暂存全部", command=self.stage_all_async).grid(row=0, column=3, padx=(0, 6))
        panes = ttk.PanedWindow(tab, orient=tk.HORIZONTAL)
        panes.grid(row=1, column=0, sticky="nsew")
        left = ttk.Frame(panes)
        right = ttk.Frame(panes)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        panes.add(left, weight=2)
        panes.add(right, weight=3)
        status_frame, self.status_tree = self._tree_frame(left, ("state", "path"), ("状态", "文件"), (120, 580))
        status_frame.grid(row=0, column=0, sticky="nsew")
        self.status_tree.bind("<<TreeviewSelect>>", self.on_status_selected)
        self.diff_text = self._text_box(right, height=20)
        self.diff_text.grid(row=0, column=0, sticky="nsew")
        commit_box = ttk.LabelFrame(tab, text="提交")
        commit_box.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        commit_box.columnconfigure(1, weight=1)
        ttk.Label(commit_box, text="提交说明").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        ttk.Entry(commit_box, textvariable=self.commit_message_var).grid(row=0, column=1, padx=(0, 10), pady=10, sticky="ew")
        ttk.Button(commit_box, text="提交已暂存", command=self.commit_staged_async).grid(row=0, column=2, padx=(0, 10), pady=10)
    def _build_versions_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        self.notebook.add(tab, text="版本历史")
        top = ttk.Frame(tab)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(top, text="只创建版本标签", command=self.create_tag_async).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(top, text="提交已暂存并打版本", command=self.commit_staged_and_tag_async).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(top, text="比较两个版本", command=self.compare_versions_async).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(top, text="查看这个版本", command=self.restore_branch_async).grid(row=0, column=3, padx=(0, 6))
        panes = ttk.PanedWindow(tab, orient=tk.HORIZONTAL)
        panes.grid(row=1, column=0, sticky="nsew")
        versions = ttk.Frame(panes)
        history = ttk.Frame(panes)
        versions.columnconfigure(0, weight=1)
        versions.rowconfigure(1, weight=1)
        history.columnconfigure(0, weight=1)
        history.rowconfigure(1, weight=1)
        panes.add(versions, weight=1)
        panes.add(history, weight=1)
        version_form = ttk.LabelFrame(versions, text="版本操作")
        version_form.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        version_form.columnconfigure(1, weight=1)
        ttk.Label(version_form, text="版本号").grid(row=0, column=0, padx=8, pady=8)
        ttk.Entry(version_form, textvariable=self.tag_var).grid(row=0, column=1, sticky="ew", pady=8)
        ttk.Button(version_form, text="建议", command=self.suggest_next_version).grid(row=0, column=2, padx=8, pady=8)
        ttk.Label(version_form, text="从").grid(row=1, column=0, padx=8, pady=8)
        ttk.Entry(version_form, textvariable=self.compare_from_var).grid(row=1, column=1, sticky="ew", pady=8)
        ttk.Label(version_form, text="到").grid(row=1, column=2, padx=8, pady=8)
        ttk.Entry(version_form, textvariable=self.compare_to_var, width=18).grid(row=1, column=3, sticky="ew", padx=(0, 8), pady=8)
        tag_frame, self.tag_tree = self._tree_frame(versions, ("tag", "date", "commit", "subject"), ("版本", "日期", "提交", "说明"), (140, 100, 90, 360))
        tag_frame.grid(row=1, column=0, sticky="nsew")
        self.tag_tree.bind("<<TreeviewSelect>>", self.on_tag_selected)
        history_buttons = ttk.Frame(history)
        history_buttons.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(history_buttons, text="查看提交详情", command=self.show_commit_async).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(history_buttons, text="复制提交号", command=self.copy_commit_hash).grid(row=0, column=1, padx=(0, 6))
        history_frame, self.history_tree = self._tree_frame(history, ("commit", "date", "subject"), ("提交", "日期", "说明"), (100, 110, 520))
        history_frame.grid(row=1, column=0, sticky="nsew")

    def _build_bundles_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        self.notebook.add(tab, text="备份包")
        top = ttk.LabelFrame(tab, text="备份目录")
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        ttk.Entry(top, textvariable=self.backup_dir_var).grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        ttk.Button(top, text="选择", command=self.choose_backup_dir).grid(row=0, column=1, padx=(0, 8), pady=10)
        ttk.Button(top, text="打开", command=self.open_backup_folder).grid(row=0, column=2, padx=(0, 10), pady=10)
        actions = ttk.Frame(tab)
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        ttk.Button(actions, text="导出完整 .bundle", command=self.export_bundle_async).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(actions, text="校验选中备份包", command=self.verify_bundle_async).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(actions, text="从备份包恢复到新目录", command=self.clone_bundle_async).grid(row=0, column=2, padx=(0, 6))
        bundle_frame, self.bundle_tree = self._tree_frame(tab, ("file", "size", "modified"), ("文件", "大小", "修改时间"), (760, 120, 180))
        bundle_frame.grid(row=2, column=0, sticky="nsew")

    def _build_logs_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        self.notebook.add(tab, text="日志")
        self.log_text = self._text_box(tab, height=24)
        self.log_text.grid(row=0, column=0, sticky="nsew")

    def _text_box(self, parent: ttk.Frame, height: int) -> ttk.Frame:
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        text = tk.Text(frame, height=height, wrap="none", font=("Consolas", 10), undo=False)
        ybar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        text.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        frame.text_widget = text  # type: ignore[attr-defined]
        return frame

    def _tree_frame(self, parent: ttk.Frame, columns: tuple[str, ...], headings: tuple[str, ...], widths: tuple[int, ...]) -> tuple[ttk.Frame, ttk.Treeview]:
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended")
        for column, heading, width in zip(columns, headings, widths):
            tree.heading(column, text=heading)
            tree.column(column, width=width, anchor="w", stretch=True)
        ybar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        return frame, tree

    def set_text(self, container: ttk.Frame, value: str) -> None:
        text: tk.Text = container.text_widget  # type: ignore[attr-defined]
        text.configure(state="normal")
        text.delete("1.0", tk.END)
        text.insert(tk.END, value)
        text.configure(state="disabled")

    def append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        text: tk.Text = self.log_text.text_widget  # type: ignore[attr-defined]
        text.configure(state="normal")
        text.insert(tk.END, f"[{timestamp}] {message}\n")
        text.see(tk.END)
        text.configure(state="disabled")

    def run_async(self, label: str, func: Callable[[], str], refresh_after: bool = True) -> None:
        self.footer_var.set(label)
        self.append_log(label)
        thread = threading.Thread(target=self._worker, args=(func, refresh_after), daemon=True)
        thread.start()

    def _worker(self, func: Callable[[], str], refresh_after: bool) -> None:
        try:
            message = func()
            self.after(0, lambda: self.operation_done(message, refresh_after))
        except GitError as exc:
            self.after(0, lambda: self.operation_failed(exc.output or str(exc), refresh_after))
        except Exception as exc:  # noqa: BLE001 - GUI boundary
            self.after(0, lambda: self.operation_failed(str(exc), refresh_after))

    def operation_done(self, message: str, refresh_after: bool) -> None:
        self.footer_var.set(message)
        self.append_log(message)
        if refresh_after:
            self.refresh_async(silent=True)

    def operation_failed(self, message: str, refresh_after: bool) -> None:
        self.footer_var.set("失败")
        self.append_log("失败: " + (message or "操作失败"))
        messagebox.showerror(APP_TITLE, message or "操作失败")
        if refresh_after:
            self.refresh_async(silent=True)
    def refresh_async(self, silent: bool = False) -> None:
        def work() -> str:
            branch = run_git("branch", "--show-current", check=False) or "(detached)"
            latest = run_git("log", "--oneline", "-1", check=False) or "No commits"
            status_output = run_git("-c", "core.quotepath=false", "status", "--short", check=False)
            tag_output = run_git(
                "-c", "core.quotepath=false", "for-each-ref", "--sort=-creatordate",
                "--format=%(refname:short)%09%(creatordate:short)%09%(objectname:short)%09%(subject)",
                "refs/tags", check=False,
            )
            commit_output = run_git(
                "-c", "core.quotepath=false", "log", "--date=short",
                "--pretty=format:%h%x09%ad%x09%s", "-100", check=False,
            )
            hook_path = run_git("config", "--get", "core.hooksPath", check=False)
            entries = parse_status(status_output)
            tags = parse_tags(tag_output)
            commits = parse_commits(commit_output)
            bundles = self.load_bundles()
            git_size = folder_size(REPO_ROOT / ".git")
            disk_text = self.backup_disk_text()
            hook_ok = hook_path.strip() == ".githooks" and (REPO_ROOT / ".githooks" / "pre-commit.ps1").exists()
            self.after(0, lambda: self.apply_refresh(branch, latest, entries, tags, commits, bundles, git_size, disk_text, hook_ok))
            return "就绪" if silent else "已刷新"
        self.run_async("正在刷新...", work, refresh_after=False)

    def apply_refresh(
        self,
        branch: str,
        latest: str,
        entries: list[StatusEntry],
        tags: list[TagEntry],
        commits: list[CommitEntry],
        bundles: list[BundleEntry],
        git_size: int,
        disk_text: str,
        hook_ok: bool,
    ) -> None:
        self.status_entries = entries
        self.tag_entries = tags
        self.commit_entries = commits
        self.bundle_entries = bundles
        latest_tag = tags[0].name if tags else "无"
        self.branch_var.set(branch)
        self.latest_commit_var.set(latest[:90])
        self.latest_tag_var.set(latest_tag)
        self.worktree_var.set("干净" if not entries else f"{len(entries)} 个改动")
        self.hook_var.set("已启用" if hook_ok else "未启用")
        self.git_size_var.set(human_size(git_size))
        self.disk_var.set(disk_text)
        if not self.tag_var.get().strip():
            self.tag_var.set(suggest_next_tag(tags))
        self.fill_status_tree(entries)
        self.fill_tag_tree(tags)
        self.fill_history_tree(commits)
        self.fill_bundle_tree(bundles)
        self.set_text(self.preflight_text, self.build_preflight_report(mutate=False).text)
        self.set_text(self.timeline_text, self.build_timeline_text(latest_tag, bundles))

    def build_timeline_text(self, latest_tag: str, bundles: list[BundleEntry]) -> str:
        lines = ["备份状态", "========", f"最新版本: {latest_tag}", f"备份包数量: {len(bundles)}"]
        if bundles:
            lines.append(f"最新备份包: {bundles[0].path.name}")
            lines.append(f"最新备份包大小: {bundles[0].size_text}")
            lines.append(f"最新备份时间: {bundles[0].modified}")
        lines.extend([
            "", "推荐流程", "========",
            "1. 预检查确认没有敏感/超大文件。",
            "2. 输入版本号和提交说明。",
            "3. 点击“一键版本备份”。",
            "4. 工具会提交、打版本标签、导出并校验 .bundle。",
        ])
        return "\n".join(lines)

    def fill_status_tree(self, entries: list[StatusEntry]) -> None:
        self.status_tree.delete(*self.status_tree.get_children())
        if not entries:
            self.status_tree.insert("", tk.END, values=("干净", "没有未提交改动"))
            return
        for entry in entries:
            self.status_tree.insert("", tk.END, values=(entry.state_label, entry.path))

    def fill_tag_tree(self, tags: list[TagEntry]) -> None:
        self.tag_tree.delete(*self.tag_tree.get_children())
        for tag in tags:
            self.tag_tree.insert("", tk.END, values=(tag.name, tag.date, tag.commit, tag.subject))

    def fill_history_tree(self, commits: list[CommitEntry]) -> None:
        self.history_tree.delete(*self.history_tree.get_children())
        for commit in commits:
            self.history_tree.insert("", tk.END, values=(commit.commit, commit.date, commit.subject))

    def fill_bundle_tree(self, bundles: list[BundleEntry]) -> None:
        self.bundle_tree.delete(*self.bundle_tree.get_children())
        for bundle in bundles:
            self.bundle_tree.insert("", tk.END, values=(bundle.path.name, bundle.size_text, bundle.modified))

    def load_bundles(self) -> list[BundleEntry]:
        folder = Path(self.backup_dir_var.get()).expanduser()
        if not folder.exists():
            return []
        bundles: list[BundleEntry] = []
        for item in sorted(folder.glob("*.bundle"), key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True):
            try:
                stat = item.stat()
            except OSError:
                continue
            bundles.append(BundleEntry(item, stat.st_size, datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")))
        return bundles

    def backup_disk_text(self) -> str:
        folder = Path(self.backup_dir_var.get()).expanduser()
        probe = folder if folder.exists() else folder.parent
        try:
            usage = shutil.disk_usage(probe)
            return f"可用 {human_size(usage.free)}"
        except OSError:
            return "未知"

    def build_preflight_report(self, mutate: bool) -> PreflightReport:
        lines: list[str] = ["预检查", "======"]
        ok = True
        try:
            tag = normalize_tag(self.tag_var.get())
            existing = run_git("tag", "--list", tag, check=False)
            if existing.strip() == tag:
                lines.append(f"[阻止] 版本标签已存在: {tag}")
                ok = False
            else:
                lines.append(f"[通过] 版本号可用: {tag}")
        except ValueError as exc:
            lines.append(f"[阻止] {exc}")
            ok = False
        message = self.commit_message_var.get().strip()
        lines.append(f"[通过] 提交说明: {message}" if message else "[提示] 未填写提交说明，将使用 Release <版本号>。")
        entries = self.status_entries if not mutate else parse_status(run_git("-c", "core.quotepath=false", "status", "--short", check=False))
        staged = [entry for entry in entries if entry.staged]
        unstaged = [entry for entry in entries if entry.unstaged]
        if entries:
            lines.append(f"[信息] 当前有 {len(entries)} 个改动，已暂存 {len(staged)} 个，未暂存/未跟踪 {len(unstaged)} 个。")
        else:
            lines.append("[信息] 工作区干净，将只给当前提交打版本或导出备份。")
        if entries and not self.include_changes_var.get() and not staged:
            lines.append("[阻止] 未勾选纳入当前改动，且没有已暂存文件可提交。")
            ok = False
        risky = [(entry.path, reason) for entry in entries if (reason := risk_reason(entry.path))]
        if risky:
            ok = False
            lines.append("[阻止] 发现可能导致仓库膨胀或泄密的文件：")
            for path, reason in risky[:20]:
                lines.append(f"  - {path}  ({reason})")
            if len(risky) > 20:
                lines.append(f"  - 另外还有 {len(risky) - 20} 个风险文件")
        else:
            lines.append("[通过] 未发现敏感/超大文件风险。")
        backup_dir = Path(self.backup_dir_var.get()).expanduser()
        probe = backup_dir if backup_dir.exists() else backup_dir.parent
        try:
            usage = shutil.disk_usage(probe)
            lines.append(f"[通过] 备份盘剩余空间: {human_size(usage.free)}")
        except OSError:
            lines.append("[提醒] 无法读取备份盘剩余空间。")
        hook_path = run_git("config", "--get", "core.hooksPath", check=False).strip()
        if hook_path == ".githooks" and (REPO_ROOT / ".githooks" / "pre-commit.ps1").exists():
            lines.append("[通过] Git 提交安全钩子已启用。")
        else:
            ok = False
            lines.append("[阻止] Git 提交安全钩子未启用。")
        lines.append("")
        lines.append("结论: " + ("可以执行版本备份。" if ok else "请先处理阻止项。"))
        return PreflightReport(ok, lines)

    def preflight_async(self) -> None:
        def work() -> str:
            report = self.build_preflight_report(mutate=True)
            self.after(0, lambda: self.set_text(self.preflight_text, report.text))
            return "预检查通过" if report.ok else "预检查发现阻止项"
        self.run_async("正在预检查...", work, refresh_after=False)
    def run_version_backup_async(self) -> None:
        report = self.build_preflight_report(mutate=True)
        self.set_text(self.preflight_text, report.text)
        if not report.ok:
            messagebox.showwarning(APP_TITLE, "预检查没有通过，请先处理阻止项。")
            return
        tag = normalize_tag(self.tag_var.get())
        message = self.commit_message_var.get().strip() or f"Release {tag}"
        confirm = (
            f"准备执行版本备份：\n\n版本号: {tag}\n提交说明: {message}\n"
            f"纳入当前改动: {'是' if self.include_changes_var.get() else '否'}\n"
            f"导出 .bundle: {'是' if self.export_bundle_var.get() else '否'}\n"
        )
        if not messagebox.askyesno(APP_TITLE, confirm):
            return

        def work() -> str:
            steps: list[str] = []
            self.ensure_tag_available(tag)
            if self.include_changes_var.get():
                run_git("add", "-A")
                steps.append("已暂存当前非忽略改动")
            has_staged = git_exit_code("diff", "--cached", "--quiet") != 0
            if has_staged:
                run_git("commit", "-m", message)
                steps.append("已创建提交")
            else:
                steps.append("没有已暂存改动，版本标签将指向当前提交")
            self.create_tag(tag)
            steps.append(f"已创建版本标签 {tag}")
            if self.export_bundle_var.get():
                bundle = self.create_bundle(tag)
                steps.append(f"已导出备份包 {bundle.name}")
                if self.verify_bundle_var.get():
                    verify = run_git("bundle", "verify", str(bundle), check=False)
                    steps.append("备份包校验完成")
                    if verify:
                        steps.append(verify)
            self.after(0, lambda: self.set_text(self.timeline_text, "\n".join(steps)))
            return f"版本备份完成: {tag}"
        self.run_async("正在执行版本备份...", work)

    def selected_status_paths(self) -> list[str]:
        paths: list[str] = []
        for item in self.status_tree.selection():
            values = self.status_tree.item(item, "values")
            if len(values) >= 2 and values[1] != "没有未提交改动":
                paths.append(str(values[1]))
        return paths

    def selected_tag(self) -> str | None:
        selection = self.tag_tree.selection()
        if not selection:
            return None
        values = self.tag_tree.item(selection[0], "values")
        return str(values[0]) if values else None

    def selected_commit(self) -> str | None:
        selection = self.history_tree.selection()
        if not selection:
            return None
        values = self.history_tree.item(selection[0], "values")
        return str(values[0]) if values else None

    def selected_bundle(self) -> Path | None:
        selection = self.bundle_tree.selection()
        if not selection:
            return None
        values = self.bundle_tree.item(selection[0], "values")
        if not values:
            return None
        return Path(self.backup_dir_var.get()).expanduser() / str(values[0])

    def on_status_selected(self, _event: object) -> None:
        paths = self.selected_status_paths()
        if paths:
            self.show_diff_for_paths(paths[:1])

    def on_tag_selected(self, _event: object) -> None:
        tag = self.selected_tag()
        if not tag:
            return
        self.tag_var.set(tag)
        self.restore_tag_var.set(tag)
        if not self.compare_from_var.get().strip():
            self.compare_from_var.set(tag)
        else:
            self.compare_to_var.set(tag)

    def show_diff_for_paths(self, paths: list[str]) -> None:
        chunks: list[str] = []
        for path in paths:
            unstaged = run_git("-c", "core.quotepath=false", "diff", "--", path, check=False)
            staged = run_git("-c", "core.quotepath=false", "diff", "--cached", "--", path, check=False)
            chunks.append(f"===== {path} =====\n{unstaged or staged or '没有文本差异，可能是二进制文件或仅状态变化'}")
        self.set_text(self.diff_text, "\n\n".join(chunks))

    def stage_selected_async(self) -> None:
        paths = self.selected_status_paths()
        if not paths:
            messagebox.showinfo(APP_TITLE, "请先选择要暂存的文件。")
            return
        self.run_async("正在暂存选中文件...", lambda: self.git_paths(["add", "--"], paths, "已暂存选中文件"))

    def unstage_selected_async(self) -> None:
        paths = self.selected_status_paths()
        if not paths:
            messagebox.showinfo(APP_TITLE, "请先选择要取消暂存的文件。")
            return
        self.run_async("正在取消暂存...", lambda: self.git_paths(["restore", "--staged", "--"], paths, "已取消暂存选中文件"))

    def diff_selected_async(self) -> None:
        paths = self.selected_status_paths()
        if not paths:
            messagebox.showinfo(APP_TITLE, "请先选择要查看差异的文件。")
            return
        self.show_diff_for_paths(paths[:8])
        self.notebook.select(1)

    def git_paths(self, prefix: list[str], paths: list[str], message: str) -> str:
        run_git(*(prefix + paths))
        return message

    def stage_all_async(self) -> None:
        if not messagebox.askyesno(APP_TITLE, "暂存所有未忽略的改动？\n\n提交保护仍会拦截大文件和敏感文件。"):
            return
        self.run_async("正在暂存全部...", lambda: run_git("add", "-A") or "已暂存全部改动")

    def commit_staged_async(self) -> None:
        message = self.commit_message_var.get().strip()
        if not message:
            messagebox.showwarning(APP_TITLE, "请输入提交说明。")
            return
        self.run_async("正在提交...", lambda: run_git("commit", "-m", message) or "已提交")

    def suggest_next_version(self) -> None:
        self.tag_var.set(suggest_next_tag(self.tag_entries))

    def create_tag_async(self) -> None:
        try:
            tag = normalize_tag(self.tag_var.get())
        except ValueError as exc:
            messagebox.showwarning(APP_TITLE, str(exc))
            return
        self.run_async("正在创建版本标签...", lambda: self.create_tag(tag))

    def commit_staged_and_tag_async(self) -> None:
        try:
            tag = normalize_tag(self.tag_var.get())
        except ValueError as exc:
            messagebox.showwarning(APP_TITLE, str(exc))
            return
        message = self.commit_message_var.get().strip() or f"Release {tag}"
        if not messagebox.askyesno(APP_TITLE, f"提交当前已暂存内容，并创建版本标签 {tag}？\n\n不会自动暂存未暂存文件。"):
            return
        def work() -> str:
            self.ensure_tag_available(tag)
            run_git("commit", "-m", message)
            self.create_tag(tag)
            return f"已提交并创建版本标签 {tag}"
        self.run_async("正在提交并打版本...", work)
    def compare_versions_async(self) -> None:
        left = self.compare_from_var.get().strip()
        right = self.compare_to_var.get().strip()
        if not left or not right:
            messagebox.showinfo(APP_TITLE, "请选择或输入两个版本标签。")
            return
        def work() -> str:
            stat = run_git("-c", "core.quotepath=false", "diff", "--stat", f"{left}..{right}", check=False)
            names = run_git("-c", "core.quotepath=false", "diff", "--name-status", f"{left}..{right}", check=False)
            text = f"版本比较: {left}..{right}\n\n{stat}\n\n{names}"
            self.after(0, lambda: self.set_text(self.diff_text, text))
            self.after(0, lambda: self.notebook.select(1))
            return "版本比较已显示在改动页"
        self.run_async("正在比较版本...", work, refresh_after=False)

    def show_commit_async(self) -> None:
        commit = self.selected_commit()
        if not commit:
            messagebox.showinfo(APP_TITLE, "请先选择一个提交。")
            return
        def work() -> str:
            detail = run_git("-c", "core.quotepath=false", "show", "--stat", "--name-status", "--decorate", "--oneline", commit, check=False)
            self.after(0, lambda: self.set_text(self.diff_text, detail or "没有提交详情"))
            self.after(0, lambda: self.notebook.select(1))
            return "提交详情已显示在改动页"
        self.run_async("正在读取提交详情...", work, refresh_after=False)

    def copy_commit_hash(self) -> None:
        commit = self.selected_commit()
        if not commit:
            messagebox.showinfo(APP_TITLE, "请先选择一个提交。")
            return
        self.clipboard_clear()
        self.clipboard_append(commit)
        self.footer_var.set(f"已复制提交号 {commit}")
        self.append_log(f"已复制提交号 {commit}")

    def restore_branch_async(self) -> None:
        tag = self.restore_tag_var.get().strip() or self.selected_tag() or self.tag_var.get().strip()
        if not tag:
            messagebox.showwarning(APP_TITLE, "请输入或选择版本标签。")
            return
        branch = "view-" + sanitize_filename(tag)
        if not messagebox.askyesno(APP_TITLE, f"从 {tag} 创建并切换到分支 {branch}？\n\n这个操作用于查看旧版本，Git 会保护未提交改动。"):
            return
        self.run_async("正在创建查看分支...", lambda: run_git("switch", "-c", branch, tag) or f"已切换到 {branch}")

    def export_bundle_async(self) -> None:
        tag = self.tag_var.get().strip() or datetime.now().strftime("%Y%m%d-%H%M%S")
        self.run_async("正在导出完整备份包...", lambda: f"已导出备份包: {self.create_bundle(tag)}")

    def verify_bundle_async(self) -> None:
        bundle = self.selected_bundle()
        if not bundle:
            messagebox.showinfo(APP_TITLE, "请先选择一个 .bundle 备份包。")
            return
        self.run_async("正在校验备份包...", lambda: self.verify_bundle(bundle), refresh_after=False)

    def clone_bundle_async(self) -> None:
        bundle = self.selected_bundle()
        if not bundle:
            messagebox.showinfo(APP_TITLE, "请先选择一个 .bundle 备份包。")
            return
        target = filedialog.askdirectory(title="选择恢复到哪个空目录的上级目录")
        if not target:
            return
        restore_dir = Path(target) / f"LCA-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        if not messagebox.askyesno(APP_TITLE, f"将从备份包恢复到新目录：\n{restore_dir}\n\n不会覆盖当前项目。"):
            return
        def work() -> str:
            run_command(["git", "clone", str(bundle), str(restore_dir)])
            return f"已恢复到新目录: {restore_dir}"
        self.run_async("正在从备份包恢复...", work, refresh_after=False)

    def choose_backup_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.backup_dir_var.get() or str(REPO_ROOT))
        if selected:
            self.backup_dir_var.set(selected)
            self.refresh_async()

    def open_backup_folder(self) -> None:
        folder = Path(self.backup_dir_var.get()).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)  # type: ignore[attr-defined]

    def ensure_tag_available(self, tag: str) -> None:
        existing = run_git("tag", "--list", tag, check=False)
        if existing.strip() == tag:
            raise GitError("tag exists", f"版本标签已存在: {tag}")

    def create_tag(self, tag: str) -> str:
        tag = normalize_tag(tag)
        self.ensure_tag_available(tag)
        run_git("tag", "-a", tag, "-m", f"LCA {tag}")
        return f"已创建版本标签 {tag}"

    def create_bundle(self, tag: str) -> Path:
        suffix = sanitize_filename(tag)
        backup_dir = Path(self.backup_dir_var.get()).expanduser()
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"LCA-{suffix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.bundle"
        run_git("bundle", "create", str(target), "--all")
        if self.verify_bundle_var.get():
            run_git("bundle", "verify", str(target), check=False)
        return target

    def verify_bundle(self, bundle: Path) -> str:
        output = run_git("bundle", "verify", str(bundle), check=False)
        self.after(0, lambda: self.set_text(self.timeline_text, output or "校验完成"))
        return "备份包校验完成"


if __name__ == "__main__":
    VersionBackupCenter().mainloop()
