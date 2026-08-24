#!/usr/bin/env python
"""Write traceable release metadata beside the standalone distribution."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", required=True)
    args = parser.parse_args()
    dist = Path(args.dist).resolve()
    files = {}
    for relative in ("main.exe", "DirectML.dll", "onnxruntime.dll"):
        path = dist / relative
        if path.is_file():
            files[relative] = {"size": path.stat().st_size, "sha256": _sha256(path)}
    metadata = {
        "schema_version": 1,
        "edition": "离线版",
        "git_commit": _git_commit(),
        "built_at": time.time(),
        "files": files,
    }
    output = dist / "build-metadata.json"
    output.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"build_metadata={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
