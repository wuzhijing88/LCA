#!/usr/bin/env python
"""Verify third-party component hashes before packaging."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = PROJECT_ROOT / "build_assets" / "third_party" / "manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(manifest_path: Path, *, require_all: bool) -> list[str]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("unsupported third-party manifest schema")
    for component in payload.get("components", []):
        name = str(component.get("name") or "unknown")
        relative_path = str(component.get("path") or "")
        source = PROJECT_ROOT / relative_path
        expected = str(component.get("sha256") or "").lower()
        if not source.is_file():
            if require_all:
                errors.append(f"missing component: {name}: {relative_path}")
            continue
        if not expected:
            errors.append(f"missing sha256: {name}")
            continue
        actual = _sha256(source)
        if actual != expected:
            errors.append(f"sha256 mismatch: {name}: {actual} != {expected}")
        if not str(component.get("license") or "").strip():
            errors.append(f"missing license: {name}")
        if not str(component.get("source_url") or "").strip():
            errors.append(f"missing source_url: {name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()
    errors = verify(Path(args.manifest).resolve(), require_all=args.require_all)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print("third-party manifest verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
