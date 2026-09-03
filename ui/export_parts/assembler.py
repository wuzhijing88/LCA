from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from app_core.player.exe_branding import brand_runtime_exe
from app_core.player.package import (
    PLAYER_PACKAGE_SCHEMA_VERSION,
    ensure_designer_ui,
)
from app_core.player.runtime_config import (
    RUNTIME_CONFIG_FILENAME,
    apply_player_ui_hotkeys,
    snapshot_export_runtime_config,
)
from app_core.player.secure_package import seal_package_files, secure_remove_path
from ui.export_parts.collector import CollectionResult, collection_to_memory_files
from ui.export_parts.standalone_installer import build_standalone_installer
from utils.app_paths import get_app_root, get_resource_path, is_packaged_runtime, resolve_running_executable

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[int, str], None]]

RUNTIME_DIRNAME = "runtime"
# 根目录应保持干净；这些文件默认设为隐藏
_HIDDEN_ROOT_FILES = (
    "package.lcap",
    "package.key",
    "launcher.cfg",
)

EXCLUDE_DIR_NAMES = {
    ".git",
    "__pycache__",
    "backups",
    "diagnostics",
    "logs",
    "package",
    "userdata",
    "runtime",
    "build_output",
    "release_output",
}
EXCLUDE_FILE_NAMES = {
    "slot-1.lock",
    "package.lcap",
    "package.key",
    "launcher.cfg",
}


def safe_export_name(app_name: str) -> str:
    cleaned = "".join(ch for ch in str(app_name or "").strip() if ch not in '<>:"/\\|?*')
    cleaned = cleaned.strip(" .")
    return cleaned or "独立程序"


def build_manifest_and_ui_files(
    *,
    app_name: str,
    description: str,
    ui: dict,
    company: str = "",
    version: str = "",
    required_client_width: int = 0,
    required_client_height: int = 0,
    scripts: list | None = None,
    entry_script_id: str = "",
    runtime_config: dict | None = None,
) -> Dict[str, bytes]:
    try:
        req_w = int(required_client_width or 0)
        req_h = int(required_client_height or 0)
    except (TypeError, ValueError):
        req_w = req_h = 0
    if req_w <= 0 or req_h <= 0:
        req_w = req_h = 0
    manifest = {
        "schema_version": PLAYER_PACKAGE_SCHEMA_VERSION,
        "app_name": app_name,
        "description": description,
        "entry_workflow": "workflows/main.json",
        "entry_script_id": str(entry_script_id or "").strip(),
        "company": company,
        "version": version,
        "required_client_width": req_w,
        "required_client_height": req_h,
        "scripts": list(scripts or []),
    }
    snapshot = snapshot_export_runtime_config(runtime_config)
    ui_payload = apply_player_ui_hotkeys(ensure_designer_ui(ui, app_name=app_name), snapshot)
    files = {
        "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        "ui.json": json.dumps(ui_payload, ensure_ascii=False, indent=2).encode("utf-8"),
    }
    if snapshot:
        files[RUNTIME_CONFIG_FILENAME] = json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8")
    return files


def write_manifest_and_ui(
    package_dir: Path,
    *,
    app_name: str,
    description: str,
    ui: dict,
    company: str = "",
    version: str = "",
    required_client_width: int = 0,
    required_client_height: int = 0,
    scripts: list | None = None,
    entry_script_id: str = "",
    runtime_config: dict | None = None,
) -> None:
    package_dir.mkdir(parents=True, exist_ok=True)
    files = build_manifest_and_ui_files(
        app_name=app_name,
        description=description,
        ui=ui,
        company=company,
        version=version,
        required_client_width=required_client_width,
        required_client_height=required_client_height,
        scripts=scripts,
        entry_script_id=entry_script_id,
        runtime_config=runtime_config,
    )
    for name, data in files.items():
        (package_dir / name).write_bytes(data)


def collect_ui_asset_files(asset_map: dict | None) -> Dict[str, bytes]:
    files: Dict[str, bytes] = {}
    if not asset_map:
        return files
    for rel, source in asset_map.items():
        rel_text = str(rel or "").replace("\\", "/").lstrip("/")
        src = Path(str(source or ""))
        if not rel_text or not src.is_file():
            continue
        files[rel_text] = src.read_bytes()
    return files


def write_ui_assets(package_dir: Path, asset_map: dict | None) -> None:
    """把设计器资源复制进 package/ui_assets/..."""
    for rel_text, data in collect_ui_asset_files(asset_map).items():
        dest = package_dir / rel_text
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)


def _should_skip(path: Path, root: Path) -> bool:
    relative_parts = path.relative_to(root).parts
    if any(part in EXCLUDE_DIR_NAMES for part in relative_parts[:-1]):
        return True
    if path.name in EXCLUDE_FILE_NAMES or path.name in EXCLUDE_DIR_NAMES:
        return True
    if path.suffix.lower() == ".pyc":
        return True
    return False


def _copy_or_link_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return
    try:
        os.link(source, destination)
        return
    except OSError:
        pass
    shutil.copy2(source, destination)


def _report_progress(progress: ProgressCallback, value: int, message: str) -> None:
    if progress is None:
        return
    try:
        progress(max(0, min(100, int(value))), str(message or ""))
    except Exception:
        logger.debug("进度回调失败", exc_info=True)


def copy_runtime_tree(
    source_root: Path,
    destination_root: Path,
    *,
    progress: ProgressCallback = None,
    progress_start: int = 20,
    progress_end: int = 70,
) -> None:
    destination_root.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for current, dirnames, filenames in os.walk(source_root):
        current_path = Path(current)
        dirnames[:] = [name for name in dirnames if name not in EXCLUDE_DIR_NAMES]
        for filename in filenames:
            source = current_path / filename
            if _should_skip(source, source_root):
                continue
            files.append(source)

    total = max(1, len(files))
    _report_progress(progress, progress_start, f"正在复制运行时（0/{total}）…")
    for index, source in enumerate(files, start=1):
        relative = source.relative_to(source_root)
        _copy_or_link_file(source, destination_root / relative)
        if index == 1 or index == total or index % 25 == 0:
            ratio = index / total
            value = progress_start + int((progress_end - progress_start) * ratio)
            _report_progress(
                progress,
                value,
                f"正在复制运行时（{index}/{total}）…",
            )


def _runtime_has_main_engine(root: Path) -> bool:
    return (root / "main.exe").is_file()


def resolve_bundled_runtime_root() -> Path:
    """定位同一主程序运行时（main.dist）。独立程序与编辑器共用二进制，靠 exe 内嵌入口印记分流。"""
    for env_name in ("LCA_RUNTIME", "LCA_PLAYER_RUNTIME"):
        env = str(os.environ.get(env_name) or "").strip()
        if not env:
            continue
        candidate = Path(os.path.expandvars(env)).expanduser()
        if _runtime_has_main_engine(candidate):
            return candidate.resolve()
        raise FileNotFoundError(
            f"环境变量 {env_name} 无效，未找到 main.exe: {candidate}"
        )

    project_root = Path(get_app_root())
    candidates: list[Path] = []
    if is_packaged_runtime():
        # 从已安装/已打包的编辑器导出时，运行时就在自身目录
        candidates.append(project_root)
        candidates.append(project_root.parent / "main.dist")
    candidates.extend(
        [
            project_root / "build_assets" / "packaging" / "build_output" / "main.dist",
            project_root / "build_assets" / "packaging" / "main.dist",
        ]
    )
    for candidate in candidates:
        if _runtime_has_main_engine(candidate):
            return candidate.resolve()

    raise FileNotFoundError(
        "未找到运行时（main.dist/main.exe）。\n"
        "请先执行 build_assets\\packaging\\build_release.bat，\n"
        "或设置环境变量 LCA_RUNTIME 指向含 main.exe 的目录。"
    )


def resolve_runtime_main_exe(runtime_root: Path) -> Path:
    """导出独立程序使用同一主程序 main.exe（导出时再写入播放器入口印记）。"""
    runtime_root = Path(runtime_root)
    main_exe = runtime_root / "main.exe"
    if main_exe.is_file():
        return main_exe
    raise FileNotFoundError(f"运行时目录中未找到 main.exe: {runtime_root}")


def resolve_export_engine() -> Tuple[str, Optional[Path]]:
    """bundled=main.dist；导出时 brand 写入播放器 PE 入口印记。"""
    runtime_root = resolve_bundled_runtime_root()
    if resolve_runtime_main_exe(runtime_root).is_file():
        return "bundled", runtime_root
    raise FileNotFoundError(
        "未找到可用运行时（main.dist/main.exe）。\n"
        "请先执行 build_assets\\packaging\\build_release.bat。"
    )


def _hide_path(path: Path) -> None:
    if os.name != "nt" or not path.exists():
        return
    try:
        import ctypes

        # FILE_ATTRIBUTE_HIDDEN
        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x2)
    except Exception:
        pass


def _default_export_icon(icon_path: str = "") -> str:
    text = str(icon_path or "").strip()
    if text and os.path.isfile(text):
        return text
    fallback = Path(get_resource_path("icon.ico"))
    return str(fallback) if fallback.is_file() else ""


def _prepare_payload_dir(
    payload_dir: Path,
    *,
    app_name: str,
    icon_path: str,
    runtime_root: Path,
    sealed_lcap: Path,
    bind_id: bytes | None = None,
    progress: ProgressCallback = None,
) -> Path:
    """
    安装包 payload：
      设计名.exe     ← 复制自 main.exe + 图标 + PE 播放器入口印记
      *.dll / 依赖
      package.lcap   ← 数据包（不决定入口）
      userdata\\
    安装目录内不得残留 main.exe；入口只认 exe 内嵌印记。
    """
    if payload_dir.exists():
        shutil.rmtree(payload_dir, ignore_errors=True)
    payload_dir.mkdir(parents=True, exist_ok=True)

    copy_runtime_tree(
        runtime_root,
        payload_dir,
        progress=progress,
        progress_start=25,
        progress_end=72,
    )
    _report_progress(progress, 74, "正在写入程序名称、图标与入口印记…")
    source_exe = resolve_runtime_main_exe(runtime_root)
    flat_main = payload_dir / "main.exe"
    exe_name = f"{safe_export_name(app_name)}.exe"
    target_exe = payload_dir / exe_name
    brand_source = flat_main if flat_main.is_file() else source_exe
    brand_runtime_exe(
        brand_source,
        target_exe,
        icon_path=icon_path,
        entry_mode="player",
        bind_id=bind_id,
    )
    # 安装目录落地 icon.ico，供卸载项 / 快捷方式 /「应用和功能」显示自定义图标
    ico_text = str(icon_path or "").strip()
    if ico_text and os.path.isfile(ico_text):
        try:
            shutil.copy2(ico_text, payload_dir / "icon.ico")
        except OSError:
            logger.warning("复制安装目录图标失败: %s", ico_text, exc_info=True)
    from app_core.player.entry_stamp import (
        ENTRY_PLAYER,
        read_entry_stamp_info_from_exe,
    )

    stamp_info = read_entry_stamp_info_from_exe(target_exe)
    if stamp_info is None or stamp_info.entry != ENTRY_PLAYER:
        raise RuntimeError(
            f"导出失败：未能将播放器入口印记写入 {target_exe.name}。"
            "请确认杀毒软件未拦截资源更新后重试。"
        )
    if bind_id and stamp_info.bind_id != bytes(bind_id):
        raise RuntimeError(
            f"导出失败：程序与数据包绑定写入不一致（{target_exe.name}）。"
        )

    # 去掉仍带编辑器身份的 main.exe，只保留已盖播放器印记的设计名.exe
    if flat_main.is_file():
        try:
            if flat_main.resolve() != target_exe.resolve():
                flat_main.unlink()
        except OSError:
            try:
                flat_main.unlink()
            except OSError:
                pass
    flat_player = payload_dir / "player.exe"
    if flat_player.is_file():
        try:
            if flat_player.resolve() != target_exe.resolve():
                flat_player.unlink()
        except OSError:
            pass

    shutil.copy2(sealed_lcap, payload_dir / "package.lcap")
    # 清理旧版旁路入口标记（入口已写入 exe PE 资源）
    for stale_marker in ("player.mode", "launcher.cfg", "package.key"):
        stale_path = payload_dir / stale_marker
        if stale_path.exists():
            try:
                stale_path.unlink()
            except OSError:
                pass
    (payload_dir / "userdata").mkdir(parents=True, exist_ok=True)

    if not (payload_dir / "package.lcap").is_file():
        raise RuntimeError("导出失败：payload 中缺少 package.lcap")
    if not target_exe.is_file():
        raise RuntimeError(f"导出失败：未生成主程序 {target_exe.name}")
    return target_exe


def assemble_standalone_export(
    *,
    output_dir: Path,
    app_name: str,
    description: str,
    collection: CollectionResult,
    ui: dict,
    icon_path: str = "",
    company: str = "",
    version: str = "",
    ui_asset_map: dict | None = None,
    required_client_width: int = 0,
    required_client_height: int = 0,
    scripts: list | None = None,
    entry_script_id: str = "",
    runtime_config: dict | None = None,
    progress: ProgressCallback = None,
) -> Path:
    """
    制作独立程序安装包。
    返回 Setup.exe 路径；中间 payload 在输出目录下临时生成后删除。
    """
    if collection.errors:
        raise ValueError("独立程序包仍有未解决的错误，拒绝导出")

    _report_progress(progress, 2, "正在检查运行时…")
    engine_mode, runtime_root = resolve_export_engine()
    if engine_mode != "bundled" or runtime_root is None:
        raise RuntimeError(
            "制作安装包需要正式运行时（main.dist / main.exe）。\n"
            "请先执行 build_assets\\packaging\\build_release.bat 生成运行时，\n"
            "或设置环境变量 LCA_RUNTIME。"
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    icon_path = _default_export_icon(icon_path)
    display_name = str(app_name or "").strip() or "独立程序"
    safe_name = safe_export_name(display_name)

    work_dir = output_dir / f".{safe_name}_build"
    leftover_package = work_dir / "package"
    if leftover_package.exists():
        secure_remove_path(leftover_package)
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        _report_progress(progress, 8, "正在打包工作流与界面…")
        package_files = collection_to_memory_files(collection)
        package_files.update(
            build_manifest_and_ui_files(
                app_name=display_name,
                description=description,
                ui=ui,
                company=company,
                version=version,
                required_client_width=required_client_width,
                required_client_height=required_client_height,
                scripts=scripts,
                entry_script_id=entry_script_id,
                runtime_config=runtime_config,
            )
        )
        package_files.update(collect_ui_asset_files(ui_asset_map))
        if icon_path and os.path.isfile(icon_path):
            package_files["icon.ico"] = Path(icon_path).read_bytes()

        import secrets

        from app_core.player.package_integrity import stamp_package_files
        from app_core.player.secure_package import cleanup_extracted_package

        # 同一随机 bind_id 写入 package.lcap 与播放器 exe 印记，防挪包混用
        package_bind_id = secrets.token_bytes(16)
        package_files = stamp_package_files(package_files)

        _report_progress(progress, 16, "正在加密程序包…")
        cleanup_extracted_package(work_dir)
        lcap_path = seal_package_files(package_files, work_dir, bind_id=package_bind_id)

        payload_dir = work_dir / "payload"
        branded_exe = _prepare_payload_dir(
            payload_dir,
            app_name=display_name,
            icon_path=icon_path,
            runtime_root=runtime_root,
            sealed_lcap=lcap_path,
            bind_id=package_bind_id,
            progress=progress,
        )

        _report_progress(progress, 82, "正在压缩安装包（Inno Setup，首次可能需数分钟）…")
        setup_path = build_standalone_installer(
            payload_dir=payload_dir,
            output_dir=output_dir,
            app_name=display_name,
            exe_name=branded_exe.name,
            icon_path=icon_path,
            version=version or "1.0.0",
            publisher=(company or "LCA"),
            progress=progress,
        )
    finally:
        _report_progress(progress, 94, "正在清理临时文件…")
        shutil.rmtree(work_dir, ignore_errors=True)

    # 清掉输出目录里旧的绿色版残留，只保留安装包
    keep = {setup_path.name}
    for child in list(output_dir.iterdir()):
        if child.name in keep:
            continue
        if child.name.startswith("."):
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        # 旧导出：runtime / launcher / lcap / 旧 exe 等
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            elif child.suffix.lower() == ".exe" and child.name != setup_path.name:
                child.unlink(missing_ok=True)
            elif child.name in {"package.lcap", "package.key", "launcher.cfg"}:
                child.unlink(missing_ok=True)
        except OSError:
            pass

    _report_progress(progress, 100, "制作完成")
    return setup_path
