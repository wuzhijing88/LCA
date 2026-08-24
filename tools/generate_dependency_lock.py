#!/usr/bin/env python
"""Snapshot the validated Windows Python environment as exact package pins."""

from __future__ import annotations

import argparse
from importlib import metadata
from pathlib import Path


EXCLUDED = {"pip", "setuptools", "wheel"}


def installed_pins() -> list[str]:
    pins: dict[str, str] = {}
    for distribution in metadata.distributions():
        name = str(distribution.metadata.get("Name") or "").strip()
        version = str(distribution.version or "").strip()
        if not name or not version or name.lower() in EXCLUDED:
            continue
        pins[name.lower()] = f"{name}=={version}"
    return [pins[key] for key in sorted(pins)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="requirements-lock.txt")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.write_text(
        "# Generated from the validated Windows Python 3.10 environment.\n"
        "# Regenerate with tools/generate_dependency_lock.py after dependency changes.\n"
        + "\n".join(installed_pins())
        + "\n",
        encoding="utf-8",
    )
    print(f"dependency_lock={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
