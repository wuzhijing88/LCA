#!/usr/bin/env python
"""Generate a reproducible inventory for bundled third-party components."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "build_assets" / "third_party" / "manifest.json"

COMPONENTS = (
    {
        "name": "AutoHotkey",
        "version": "2.x",
        "path": "AutoHotkey/AutoHotkey64.exe",
        "license": "GPL-2.0-only",
        "source_url": "https://www.autohotkey.com/",
    },
    {
        "name": "Interception",
        "version": "1.x",
        "path": "Interception/library/x64/interception.dll",
        "license": "LGPL-3.0-only",
        "source_url": "https://github.com/oblitum/Interception",
    },
    {
        "name": "Interception-x86",
        "version": "1.x",
        "path": "Interception/library/x86/interception.dll",
        "license": "LGPL-3.0-only",
        "source_url": "https://github.com/oblitum/Interception",
    },
    {
        "name": "IbInputSimulator",
        "version": "local-pinned",
        "path": "tools/ibinputsimulator/Binding.AHK2/IbInputSimulator.dll",
        "license": "LicenseRef-Upstream",
        "source_url": "https://github.com/Chaoses-Ib/IbInputSimulator",
    },
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _python_dependencies() -> list[dict[str, str]]:
    dependencies = []
    requirements = PROJECT_ROOT / "requirements-runtime.txt"
    for raw_line in requirements.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name, version = line.split("==", 1)
        dependencies.append({"name": name, "version": version})
    return dependencies


def build_manifest() -> dict[str, object]:
    components = []
    for component in COMPONENTS:
        source = PROJECT_ROOT / component["path"]
        components.append(
            {
                **component,
                "present": source.is_file(),
                "sha256": _sha256(source) if source.is_file() else "",
            }
        )
    return {
        "schema_version": 1,
        "components": components,
        "python_dependencies": _python_dependencies(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_manifest(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"third_party_manifest={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
