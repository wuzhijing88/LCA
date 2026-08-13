#!/usr/bin/env python3
"""Thin command-line entry point for the canonical packaging verifier."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from build_assets.packaging.verify_packaged_subprocess_workers import (
    _verify_build_modules,
    main,
)


if __name__ == "__main__":
    raise SystemExit(main())
