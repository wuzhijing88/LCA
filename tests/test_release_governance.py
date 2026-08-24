import json
from pathlib import Path

from build_assets.packaging.generate_sbom import build_sbom
from build_assets.packaging.verify_third_party_manifest import verify
from tools.compare_benchmark_result import compare


ROOT = Path(__file__).resolve().parents[1]


def test_third_party_manifest_schema_and_present_hashes_are_valid():
    errors = verify(
        ROOT / "build_assets" / "third_party" / "manifest.json",
        require_all=True,
    )

    assert errors == []


def test_benchmark_gate_rejects_latency_and_throughput_regression():
    baseline = {
        "kind": "service",
        "correct_rate": 1.0,
        "throughput_rps": 10.0,
        "latency": {"p95_ms": 100.0},
    }
    result = {
        "kind": "service",
        "correct_rate": 1.0,
        "throughput_rps": 8.0,
        "latency": {"p95_ms": 130.0},
    }

    errors = compare(baseline, result, tolerance=0.1)

    assert any("p95 regressed" in error for error in errors)
    assert any("throughput regressed" in error for error in errors)


def test_approved_ocr_baseline_is_measured_and_correct():
    baseline = json.loads((ROOT / "benchmarks" / "ocr" / "baseline.json").read_text(encoding="utf-8"))

    assert baseline["request_count"] >= 10
    assert baseline["correct_rate"] == 1.0
    assert baseline["latency"]["p95_ms"] > 0


def test_sbom_contains_binary_and_python_components():
    manifest = json.loads(
        (ROOT / "build_assets" / "third_party" / "manifest.json").read_text(encoding="utf-8")
    )

    sbom = build_sbom(manifest)

    assert sbom["bomFormat"] == "CycloneDX"
    assert any(component["type"] == "file" for component in sbom["components"])
    assert any(component["type"] == "library" for component in sbom["components"])
