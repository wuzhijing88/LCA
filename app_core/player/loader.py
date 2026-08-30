from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from app_core.player.entry_stamp import (
    ENTRY_EDITOR,
    ENTRY_PLAYER,
    read_own_entry_stamp,
)
from app_core.player.package import (
    PlayerPackage,
    normalize_player_manifest,
    normalize_player_ui,
)
from app_core.player.runtime_config import load_packaged_runtime_config
from app_core.player.secure_package import (
    cleanup_extracted_package,
    find_sealed_package,
    load_sealed_package_memory,
)
from app_core.player.memory_store import get_player_memory_json, list_player_memory_files
from task_workflow.workflow_payload import load_workflow_json
from utils.app_paths import get_app_root, is_packaged_runtime, resolve_running_executable

logger = logging.getLogger(__name__)

PLAYER_FLAG = "--player"
PACKAGE_FLAG = "--package"
WORKER_FLAGS = ("--ocr-worker", "--match-worker", "--workflow-worker")

# 产品角色：离线双身份（与 PE 印记一致）
ROLE_PLAYER = ENTRY_PLAYER
ROLE_EDITOR = ENTRY_EDITOR
ROLE_WORKER = "worker"


def _argv_has_flag(argv: Sequence[str], flag: str) -> bool:
    return any(str(item) == flag for item in argv)


def _argv_value(argv: Sequence[str], flag: str) -> str:
    matches = [index for index, item in enumerate(argv) if str(item) == flag]
    if not matches:
        return ""
    if len(matches) > 1:
        raise ValueError(f"命令行参数重复: {flag}")
    index = matches[0]
    if index + 1 >= len(argv):
        raise ValueError(f"{flag} 缺少路径")
    return str(argv[index + 1]).strip()


def is_worker_argv(argv: Optional[Sequence[str]] = None) -> bool:
    args = [str(item) for item in (argv if argv is not None else ())]
    return any(flag in args for flag in WORKER_FLAGS)


def resolve_product_role(argv: Optional[Sequence[str]] = None) -> str:
    """
    解析当前进程产品角色（离线主流：显式双身份）。

    - worker 子进程：ROLE_WORKER
    - 打包后：只认 exe PE 印记（player / editor）；无印记时兼容旧包 → editor
    - 源码：默认 editor；``--player`` / ``--package`` 便于本地调试播放器
    """
    args = [str(item) for item in (argv if argv is not None else ())]
    if is_worker_argv(args):
        return ROLE_WORKER
    if is_packaged_runtime():
        stamp = read_own_entry_stamp()
        if stamp == ENTRY_PLAYER:
            return ROLE_PLAYER
        if stamp == ENTRY_EDITOR:
            return ROLE_EDITOR
        # 未盖印的旧安装包：按编辑器运行，避免误伤已发布 LCA
        return ROLE_EDITOR
    if _argv_has_flag(args, PLAYER_FLAG) or _argv_has_flag(args, PACKAGE_FLAG):
        return ROLE_PLAYER
    return ROLE_EDITOR


def is_player_only_executable() -> bool:
    """打包后的播放器身份：禁止回退编辑器。"""
    if not is_packaged_runtime():
        return False
    return read_own_entry_stamp() == ENTRY_PLAYER


def is_player_mode_requested(argv: Optional[Sequence[str]] = None) -> bool:
    return resolve_product_role(argv) == ROLE_PLAYER


def _plain_package_dir(candidate: Path) -> Optional[Path]:
    if not candidate:
        return None
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate
    manifest = resolved / "manifest.json"
    if manifest.is_file():
        return resolved
    nested = resolved / "package" / "manifest.json"
    if nested.is_file():
        return nested.parent
    return None


def _export_root_from_candidate(candidate: Path) -> Optional[Path]:
    if not candidate:
        return None
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate
    if not resolved.exists():
        return None
    if find_sealed_package(resolved) is not None:
        return resolved
    if _plain_package_dir(resolved) is not None:
        plain = _plain_package_dir(resolved)
        if plain is not None and plain.name == "package":
            return plain.parent
        return resolved
    return None


def _candidate_export_roots() -> list[Path]:
    """按优先级收集可能放置 package.lcap 的目录（只找数据包，不决定入口）。"""
    roots: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | str | None) -> None:
        if not path:
            return
        candidate = Path(path)
        try:
            key = str(candidate.resolve()).lower()
        except OSError:
            key = str(candidate).lower()
        if key in seen:
            return
        seen.add(key)
        roots.append(candidate)

    exe = resolve_running_executable()
    if exe:
        add(Path(exe).parent)
    add(Path(get_app_root()))
    argv0 = str(os.environ.get("LCA_EXPORT_ROOT") or "").strip()
    if argv0:
        add(Path(os.path.expandvars(argv0)).expanduser())
    if roots:
        add(roots[0].parent)
        add(roots[0] / "package")
    return roots


def discover_export_root(argv: Optional[Sequence[str]] = None) -> Optional[Path]:
    args = [str(item) for item in (argv if argv is not None else ())]
    if is_worker_argv(args):
        return None

    explicit = _argv_value(args, PACKAGE_FLAG)
    if explicit:
        path = Path(os.path.expandvars(explicit)).expanduser()
        found = _export_root_from_candidate(path)
        if found is None:
            plain = _plain_package_dir(path)
            if plain is not None:
                return plain.parent if plain.name == "package" else plain
            raise FileNotFoundError(f"未找到独立程序包: {explicit}")
        return found

    env_root = str(os.environ.get("LCA_EXPORT_ROOT") or "").strip()
    if env_root:
        found = _export_root_from_candidate(Path(os.path.expandvars(env_root)).expanduser())
        if found is not None:
            return found

    for candidate in _candidate_export_roots():
        found = _export_root_from_candidate(candidate)
        if found is not None:
            return found
    return None


def discover_package_dir(argv: Optional[Sequence[str]] = None) -> Optional[Path]:
    export_root = discover_export_root(argv)
    if export_root is None:
        return None
    if find_sealed_package(export_root) is not None:
        return export_root
    return open_package_dir(export_root)


def open_package_dir(export_root: Path | str) -> Path:
    root = Path(export_root)
    if find_sealed_package(root) is not None:
        return root
    plain = _plain_package_dir(root)
    if plain is not None:
        return plain
    nested_plain = _plain_package_dir(root / "package")
    if nested_plain is not None:
        return nested_plain
    raise FileNotFoundError(f"未找到独立程序包: {root}")


def apply_player_isolation(argv: Optional[Sequence[str]] = None) -> Optional[Path]:
    args = [str(item) for item in (argv if argv is not None else ())]
    if is_worker_argv(args):
        return None

    force_player = is_player_mode_requested(args)
    try:
        export_root = discover_export_root(args)
    except ValueError:
        raise
    except FileNotFoundError:
        if force_player:
            raise
        return None
    if export_root is None:
        if force_player:
            exe = resolve_running_executable() or ""
            exe_dir = str(Path(exe).parent) if exe else "(未知)"
            raise FileNotFoundError(
                "独立播放器未找到 package.lcap，无法启动。\n"
                f"程序目录：{exe_dir}\n"
                "请重新安装独立程序，并确认未删除 package.lcap。\n"
                "（本程序为播放器身份，不会打开编辑器。）"
            )
        return None

    if force_player and find_sealed_package(export_root) is None:
        exe = resolve_running_executable() or ""
        exe_dir = str(Path(exe).parent) if exe else "(未知)"
        raise FileNotFoundError(
            "独立播放器未找到 package.lcap，无法启动。\n"
            f"程序目录：{exe_dir}\n"
            "请重新安装独立程序，并确认未删除 package.lcap。\n"
            "（本程序为播放器身份，不会打开编辑器。）"
        )

    # 非播放器入口：即使旁边有 package.lcap 也不进播放器（编辑器安装包勿被数据包带偏）
    if not force_player:
        return None

    userdata_dir = export_root / "userdata"
    userdata_dir.mkdir(parents=True, exist_ok=True)
    os.environ["LCA_EXPORT_ROOT"] = str(export_root)
    os.environ["LCA_USER_DATA_DIR"] = str(userdata_dir)
    os.environ.pop("LCA_PORTABLE", None)
    cleanup_extracted_package(export_root)
    return open_package_dir(export_root)


def _try_load_script_payload(relpath: str, package_dir: str = "") -> Optional[Dict[str, Any]]:
    rel = str(relpath or "").replace("\\", "/").lstrip("/")
    if not rel:
        return None
    data = get_player_memory_json(rel)
    if isinstance(data, dict):
        return data
    if package_dir:
        path = Path(package_dir) / rel
        if path.is_file():
            try:
                payload = load_workflow_json(str(path))
            except Exception:
                logger.debug("读取脚本失败: %s", path, exc_info=True)
                return None
            return payload if isinstance(payload, dict) else None
    return None


def load_package_scripts(
    manifest: Mapping[str, Any],
    *,
    workflow_data: Mapping[str, Any],
    ui: Optional[Mapping[str, Any]] = None,
    package_dir: str = "",
) -> Dict[str, Dict[str, Any]]:
    """从 manifest / 界面列表 / 包内文件收集可切换脚本。"""
    scripts: Dict[str, Dict[str, Any]] = {}
    metas: list[dict] = []
    seen: set[str] = set()

    def _add_meta(item: Mapping[str, Any]) -> None:
        sid = str(item.get("id") or "").strip()
        if not sid or sid in seen:
            return
        seen.add(sid)
        path = str(item.get("path") or item.get("source") or f"workflows/scripts/{sid}.json")
        metas.append(
            {
                "id": sid,
                "title": str(item.get("title") or sid).strip() or sid,
                "path": path.replace("\\", "/"),
            }
        )

    for item in manifest.get("scripts") or []:
        if isinstance(item, Mapping):
            _add_meta(item)
    if isinstance(ui, Mapping):
        for widget in ui.get("widgets") or []:
            if not isinstance(widget, Mapping) or str(widget.get("type") or "") != "script_list":
                continue
            for item in widget.get("items") or []:
                if isinstance(item, Mapping):
                    _add_meta(item)

    for meta in metas:
        sid = meta["id"]
        data = _try_load_script_payload(meta["path"], package_dir)
        if data is None:
            data = _try_load_script_payload(f"workflows/scripts/{sid}.json", package_dir)
        if isinstance(data, dict):
            scripts[sid] = data

    if not scripts:
        for key in list_player_memory_files():
            text = str(key or "").replace("\\", "/")
            if not (text.startswith("workflows/scripts/") and text.endswith(".json")):
                continue
            sid = Path(text).stem
            data = get_player_memory_json(text)
            if isinstance(data, dict):
                scripts[sid] = data
        folder = Path(package_dir) / "workflows" / "scripts" if package_dir else None
        if folder is not None and folder.is_dir():
            for path in folder.glob("*.json"):
                sid = path.stem
                if sid in scripts:
                    continue
                try:
                    payload = load_workflow_json(str(path))
                except Exception:
                    continue
                if isinstance(payload, dict):
                    scripts[sid] = payload

    entry_id = str(manifest.get("entry_script_id") or "").strip()
    if not entry_id:
        entry_rel = str(manifest.get("entry_workflow") or "workflows/main.json").replace("\\", "/")
        for meta in metas:
            if str(meta.get("path") or "").replace("\\", "/") == entry_rel:
                entry_id = meta["id"]
                break
    if entry_id and entry_id not in scripts and isinstance(workflow_data, Mapping) and workflow_data:
        scripts[entry_id] = copy.deepcopy(dict(workflow_data))
    return scripts


def load_player_package(package_dir: Path | str) -> PlayerPackage:
    root = Path(package_dir)
    export_root = Path(os.environ.get("LCA_EXPORT_ROOT") or "")
    if find_sealed_package(root) is not None:
        export_root = root
        manifest_raw, ui_raw, workflow_data, entry_uri = load_sealed_package_memory(root)
        try:
            from app_core.player.package_integrity import verify_player_memory_package

            # 有摘要则强制校验；旧包无摘要则跳过以保持兼容
            verify_player_memory_package(require=False)
        except ValueError as exc:
            from app_core.player.secure_package import SecurePackageError

            raise SecurePackageError(str(exc)) from exc
        manifest = normalize_player_manifest(manifest_raw)
        ui = normalize_player_ui(ui_raw, app_name=manifest["app_name"])
        userdata_dir = Path(os.environ.get("LCA_USER_DATA_DIR") or (export_root / "userdata"))
        userdata_dir.mkdir(parents=True, exist_ok=True)
        return PlayerPackage(
            package_dir=str(export_root),
            export_root=str(export_root),
            userdata_dir=str(userdata_dir),
            assets_images_dir="",
            assets_sounds_dir="",
            entry_workflow_path=entry_uri,
            manifest=manifest,
            ui=ui,
            workflow_data=workflow_data,
            scripts=load_package_scripts(
                manifest, workflow_data=workflow_data, ui=ui, package_dir=""
            ),
            runtime_config=load_packaged_runtime_config(),
        )

    if is_player_only_executable() or is_player_mode_requested():
        from app_core.player.secure_package import SecurePackageError

        raise SecurePackageError("独立程序只接受加密程序包")

    if not root.is_dir():
        raise FileNotFoundError(f"独立程序包目录不存在: {root}")

    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"缺少 {manifest_path}")
    manifest = normalize_player_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))

    ui_path = root / "ui.json"
    ui_payload = {}
    if ui_path.is_file():
        ui_payload = json.loads(ui_path.read_text(encoding="utf-8"))
    ui = normalize_player_ui(ui_payload, app_name=manifest["app_name"])

    entry_rel = Path(manifest["entry_workflow"])
    entry_path = entry_rel if entry_rel.is_absolute() else (root / entry_rel)
    entry_path = entry_path.resolve()
    try:
        entry_path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("入口工作流必须位于 package 目录内") from exc
    workflow_data = load_workflow_json(str(entry_path))

    assets_root = root / "assets"
    images_dir = assets_root / "images"
    sounds_dir = assets_root / "sounds"
    images_dir.mkdir(parents=True, exist_ok=True)
    sounds_dir.mkdir(parents=True, exist_ok=True)

    if not export_root:
        export_root = root.parent if root.name == "package" else root
    userdata_dir = Path(os.environ.get("LCA_USER_DATA_DIR") or (export_root / "userdata"))
    userdata_dir.mkdir(parents=True, exist_ok=True)

    return PlayerPackage(
        package_dir=str(root),
        export_root=str(export_root),
        userdata_dir=str(userdata_dir),
        assets_images_dir=str(images_dir),
        assets_sounds_dir=str(sounds_dir),
        entry_workflow_path=str(entry_path),
        manifest=manifest,
        ui=ui,
        workflow_data=workflow_data,
        scripts=load_package_scripts(
            manifest, workflow_data=workflow_data, ui=ui, package_dir=str(root)
        ),
        runtime_config=load_packaged_runtime_config(package_dir=str(root)),
    )


def prepare_player_search_paths(package: PlayerPackage) -> None:
    from app_core.player.runtime_images import materialize_player_maps, materialize_player_sounds

    # 密封包没有磁盘 assets 目录，音效和地图仍要从 memory 落到 userdata。
    materialize_player_sounds(package.userdata_dir)
    materialize_player_maps(package.userdata_dir)
    if package.assets_images_dir:
        from utils.image_paths import get_image_path_resolver

        resolver = get_image_path_resolver()
        resolver.add_search_path(package.assets_images_dir, priority=0)
    sounds_dir = package.assets_sounds_dir
    if sounds_dir and os.path.isdir(sounds_dir):
        userdata_sounds = os.path.join(package.userdata_dir, "sounds")
        os.makedirs(userdata_sounds, exist_ok=True)
        for name in os.listdir(sounds_dir):
            source = os.path.join(sounds_dir, name)
            if not os.path.isfile(source):
                continue
            destination = os.path.join(userdata_sounds, name)
            if os.path.isfile(destination):
                continue
            try:
                os.link(source, destination)
            except OSError:
                import shutil

                shutil.copy2(source, destination)
