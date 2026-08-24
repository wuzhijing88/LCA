#!/usr/bin/env python
"""Generate the deterministic synthetic OCR benchmark sample."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="benchmarks/ocr/samples")
    parser.add_argument("--manifest", default="benchmarks/ocr/manifest.json")
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / "ocr_123.png"
    image = np.full((120, 420, 3), 255, dtype=np.uint8)
    cv2.putText(
        image,
        "OCR 123",
        (24, 82),
        cv2.FONT_HERSHEY_SIMPLEX,
        2.0,
        (0, 0, 0),
        4,
        cv2.LINE_AA,
    )
    if not cv2.imwrite(str(image_path), image):
        raise RuntimeError(f"failed to write sample: {image_path}")
    manifest = Path(args.manifest).resolve()
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            [{"file": image_path.name, "expected": "OCR"}],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"sample={image_path}")
    print(f"manifest={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
