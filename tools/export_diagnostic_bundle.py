#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_core.diagnostics import export_diagnostic_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a redacted LCA diagnostic bundle")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    print(export_diagnostic_bundle(args.output or None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
