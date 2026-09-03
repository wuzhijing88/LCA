"""One-way, non-destructive migration from portable to per-user storage."""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


MIGRATION_VERSION = 1
_FILE_NAMES = ("config.json", "workflow_favorites.json", "universal_system_config.json")
_DIRECTORY_NAMES = ("images", "workflows", "logs", "runtime", "runtime_data")


@dataclass(frozen=True)
class UserDataMigrationReport:
    """一次 ensure_user_data_migrated() 调用的结果。

    ``copied`` / ``skipped`` 只描述本次调用实际做了什么；已经迁移过再调用时两者都为空，
    ``performed`` 为 False，历史迁移时间保留在 ``completed_at``。
    """

    version: int
    source: str
    destination: str
    copied: tuple[str, ...]
    skipped: tuple[str, ...]
    completed_at: float
    performed: bool = True


def _copy_file_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.migrating.{os.getpid()}")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def _legacy_files(root: Path) -> Iterable[Path]:
    for name in _FILE_NAMES:
        yield root / name
    yield from sorted(root.glob("config.instance-*.json"))


def ensure_user_data_migrated(
    *,
    app_root: str | Path,
    user_data_root: str | Path,
) -> UserDataMigrationReport:
    source_root = Path(app_root).resolve()
    destination_root = Path(user_data_root).resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    marker = destination_root / ".migration.json"

    if marker.is_file():
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            if int(payload.get("version", 0)) >= MIGRATION_VERSION:
                # 已迁移过：本次什么都不做，不要把历史 copied 清单当成本次结果返回。
                return UserDataMigrationReport(
                    version=int(payload["version"]),
                    source=str(payload.get("source", source_root)),
                    destination=str(payload.get("destination", destination_root)),
                    copied=(),
                    skipped=(),
                    completed_at=float(payload.get("completed_at", 0.0)),
                    performed=False,
                )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

    copied: list[str] = []
    skipped: list[str] = []
    if source_root != destination_root:
        for source in _legacy_files(source_root):
            relative = source.name
            destination = destination_root / relative
            if not source.is_file() or destination.exists():
                skipped.append(relative)
                continue
            _copy_file_atomic(source, destination)
            copied.append(relative)

        for name in _DIRECTORY_NAMES:
            source = source_root / name
            destination = destination_root / name
            if not source.is_dir():
                skipped.append(name)
                continue
            shutil.copytree(source, destination, dirs_exist_ok=True)
            copied.append(name)

    report = UserDataMigrationReport(
        version=MIGRATION_VERSION,
        source=str(source_root),
        destination=str(destination_root),
        copied=tuple(copied),
        skipped=tuple(skipped),
        completed_at=time.time(),
    )
    temporary_marker = marker.with_name(f".{marker.name}.tmp.{os.getpid()}")
    temporary_marker.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary_marker, marker)
    return report


def migrate_default_user_data(app_name: str = "LCA") -> UserDataMigrationReport:
    from utils.app_paths import get_app_root, get_user_data_dir

    return ensure_user_data_migrated(
        app_root=get_app_root(),
        user_data_root=get_user_data_dir(app_name),
    )


__all__ = [
    "MIGRATION_VERSION",
    "UserDataMigrationReport",
    "ensure_user_data_migrated",
    "migrate_default_user_data",
]
