#!/usr/bin/env python
"""Fail when OCR latency/throughput/correctness regress beyond policy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _service_metrics(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    if payload.get("kind") == "service":
        return [("service", payload)]
    if payload.get("kind") == "pool":
        return [
            (f"pool:{int(level.get('concurrency') or 0)}", level)
            for level in payload.get("levels", [])
        ]
    raise ValueError(f"unsupported benchmark kind: {payload.get('kind')!r}")


def compare(
    baseline: dict[str, Any],
    result: dict[str, Any],
    *,
    tolerance: float,
) -> list[str]:
    baseline_levels = dict(_service_metrics(baseline))
    result_levels = dict(_service_metrics(result))
    errors: list[str] = []
    for name, expected in baseline_levels.items():
        actual = result_levels.get(name)
        if actual is None:
            errors.append(f"missing benchmark level: {name}")
            continue
        expected_correct = float(expected.get("correct_rate") or 0.0)
        actual_correct = float(actual.get("correct_rate") or 0.0)
        if actual_correct < expected_correct:
            errors.append(f"{name} correct_rate regressed: {actual_correct} < {expected_correct}")

        expected_p95 = float((expected.get("latency") or {}).get("p95_ms") or 0.0)
        actual_p95 = float((actual.get("latency") or {}).get("p95_ms") or 0.0)
        if expected_p95 > 0 and actual_p95 > expected_p95 * (1.0 + tolerance):
            errors.append(
                f"{name} p95 regressed: {actual_p95:.3f}ms > "
                f"{expected_p95 * (1.0 + tolerance):.3f}ms"
            )

        expected_throughput = float(expected.get("throughput_rps") or 0.0)
        actual_throughput = float(actual.get("throughput_rps") or 0.0)
        if expected_throughput > 0 and actual_throughput < expected_throughput * (1.0 - tolerance):
            errors.append(
                f"{name} throughput regressed: {actual_throughput:.3f} < "
                f"{expected_throughput * (1.0 - tolerance):.3f}"
            )
        if int(actual.get("child_count_after_cleanup") or 0) > 0:
            errors.append(f"{name} leaked child processes after cleanup")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--tolerance-percent", type=float, default=10.0)
    args = parser.parse_args()
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    errors = compare(
        baseline,
        result,
        tolerance=max(0.0, float(args.tolerance_percent)) / 100.0,
    )
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print("benchmark gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
