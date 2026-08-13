#!/usr/bin/env python3
"""Benchmark the LCA RapidOCR runtime and its multi-window process pool."""

from __future__ import annotations

import argparse
import gc
import json
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import cv2
import numpy as np
import psutil


@dataclass(frozen=True)
class Sample:
    path: Path
    expected: str
    image: np.ndarray


class ProcessTreeSampler:
    def __init__(self, interval_seconds: float = 0.02) -> None:
        self._root = psutil.Process(os.getpid())
        self._interval_seconds = max(0.01, float(interval_seconds))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._baseline_cpu: Dict[int, float] = {}
        self._max_cpu: Dict[int, float] = {}
        self.peak_total_rss_mb = 0.0
        self.peak_child_rss_mb = 0.0
        self.peak_child_count = 0

    @staticmethod
    def _cpu_seconds(process: psutil.Process) -> float:
        cpu_times = process.cpu_times()
        return float(cpu_times.user + cpu_times.system)

    def _snapshot(self) -> None:
        try:
            children = self._root.children(recursive=True)
        except (psutil.Error, OSError):
            children = []

        processes = [self._root, *children]
        total_rss = 0
        child_rss = 0
        live_children = 0
        for process in processes:
            try:
                rss = int(process.memory_info().rss)
                cpu_seconds = self._cpu_seconds(process)
            except (psutil.Error, OSError):
                continue
            total_rss += rss
            if process.pid != self._root.pid:
                child_rss += rss
                live_children += 1
            self._baseline_cpu.setdefault(process.pid, cpu_seconds)
            self._max_cpu[process.pid] = max(
                self._max_cpu.get(process.pid, cpu_seconds),
                cpu_seconds,
            )

        self.peak_total_rss_mb = max(self.peak_total_rss_mb, total_rss / 1048576)
        self.peak_child_rss_mb = max(self.peak_child_rss_mb, child_rss / 1048576)
        self.peak_child_count = max(self.peak_child_count, live_children)

    def start(self) -> None:
        self._snapshot()

        def run() -> None:
            while not self._stop_event.wait(self._interval_seconds):
                self._snapshot()

        self._thread = threading.Thread(target=run, daemon=True, name="OCRBenchSampler")
        self._thread.start()

    def reset_cpu_baseline(self) -> None:
        """Start a new CPU accounting interval without resetting RSS peaks."""
        self._baseline_cpu.clear()
        self._max_cpu.clear()
        self._snapshot()

    def stop(self) -> Dict[str, Any]:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._snapshot()
        cpu_seconds = 0.0
        for pid, maximum in self._max_cpu.items():
            cpu_seconds += max(0.0, maximum - self._baseline_cpu.get(pid, maximum))
        return {
            "peak_total_rss_mb": round(self.peak_total_rss_mb, 2),
            "peak_child_rss_mb": round(self.peak_child_rss_mb, 2),
            "peak_child_count": int(self.peak_child_count),
            "cpu_seconds": round(cpu_seconds, 4),
        }


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _latency_summary(values: Sequence[float]) -> Dict[str, float]:
    if not values:
        return {"mean_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    milliseconds = [float(value) * 1000.0 for value in values]
    return {
        "mean_ms": round(statistics.fmean(milliseconds), 3),
        "p50_ms": round(_percentile(milliseconds, 0.50), 3),
        "p95_ms": round(_percentile(milliseconds, 0.95), 3),
        "max_ms": round(max(milliseconds), 3),
    }


def _load_manifest(path: Path, images_root: Path) -> List[Sample]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_items = payload.get("samples", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("OCR benchmark manifest has no samples")

    samples: List[Sample] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        relative_path = str(raw_item.get("file", "")).strip()
        expected = str(raw_item.get("expected", "")).strip()
        image_path = (images_root / relative_path).resolve(strict=False)
        if not image_path.is_file():
            raise FileNotFoundError(f"Benchmark image not found: {image_path}")
        encoded = np.fromfile(image_path, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError(f"Cannot decode benchmark image: {image_path}")
        samples.append(Sample(path=image_path, expected=expected, image=image))
    if not samples:
        raise ValueError("OCR benchmark manifest has no valid samples")
    return samples


def _result_texts(results: Iterable[Dict[str, Any]]) -> List[str]:
    return [str(item.get("text", "")) for item in results if isinstance(item, dict)]


def _is_correct(sample: Sample, results: Iterable[Dict[str, Any]]) -> bool:
    if not sample.expected:
        return bool(list(results))
    normalized_expected = "".join(sample.expected.split()).lower()
    for text in _result_texts(results):
        normalized_text = "".join(text.split()).lower()
        if normalized_expected in normalized_text:
            return True
    return False


def _configure_project(project_root: Path) -> None:
    resolved = str(project_root.resolve())
    os.chdir(resolved)
    sys.path.insert(0, resolved)


def _create_service():
    from services.rapidocr_ocr_service import RapidOCROCRService

    return RapidOCROCRService()


def benchmark_service(
    samples: Sequence[Sample],
    steady_iterations: int,
) -> Dict[str, Any]:
    process = psutil.Process(os.getpid())
    rss_before_mb = process.memory_info().rss / 1048576
    sampler = ProcessTreeSampler()
    sampler.start()
    service = _create_service()
    init_started = time.perf_counter()
    initialized = bool(service.initialize())
    init_seconds = time.perf_counter() - init_started
    rss_after_init_mb = process.memory_info().rss / 1048576

    latencies: List[float] = []
    successful = 0
    correct = 0
    per_sample: Dict[str, Dict[str, Any]] = {}
    sampler.reset_cpu_baseline()
    started = time.perf_counter()
    if initialized:
        for index in range(max(1, int(steady_iterations))):
            sample = samples[index % len(samples)]
            request_started = time.perf_counter()
            results = service.recognize_text(sample.image, 0.1)
            elapsed = time.perf_counter() - request_started
            latencies.append(elapsed)
            if results:
                successful += 1
            if _is_correct(sample, results):
                correct += 1
            key = sample.path.name
            if key not in per_sample:
                per_sample[key] = {
                    "expected": sample.expected,
                    "texts": _result_texts(results),
                    "correct": _is_correct(sample, results),
                }
    inference_seconds = time.perf_counter() - started
    rss_after_inference_mb = process.memory_info().rss / 1048576
    resource_stats = sampler.stop()

    shutdown_started = time.perf_counter()
    service.shutdown(deep_cleanup=True)
    gc.collect()
    shutdown_seconds = time.perf_counter() - shutdown_started
    rss_after_shutdown_mb = process.memory_info().rss / 1048576
    request_count = len(latencies)
    resource_stats["average_cpu_cores"] = round(
        resource_stats["cpu_seconds"] / inference_seconds if inference_seconds > 0 else 0.0,
        3,
    )

    return {
        "kind": "service",
        "engine": "rapidocr",
        "initialized": initialized,
        "init_error": getattr(service, "init_error", None),
        "init_seconds": round(init_seconds, 4),
        "shutdown_seconds": round(shutdown_seconds, 4),
        "request_count": request_count,
        "successful_requests": successful,
        "correct_requests": correct,
        "success_rate": round(successful / request_count, 4) if request_count else 0.0,
        "correct_rate": round(correct / request_count, 4) if request_count else 0.0,
        "inference_seconds": round(inference_seconds, 4),
        "throughput_rps": round(request_count / inference_seconds, 3) if inference_seconds else 0.0,
        "latency": _latency_summary(latencies),
        "rss_before_mb": round(rss_before_mb, 2),
        "rss_after_init_mb": round(rss_after_init_mb, 2),
        "rss_after_inference_mb": round(rss_after_inference_mb, 2),
        "rss_after_shutdown_mb": round(rss_after_shutdown_mb, 2),
        "resource": resource_stats,
        "per_sample": per_sample,
    }


def _run_concurrent_batch(pool, samples: Sequence[Sample], concurrency: int, round_index: int):
    barrier = threading.Barrier(concurrency)

    def recognize(index: int) -> Dict[str, Any]:
        sample = samples[index % len(samples)]
        barrier.wait(timeout=10.0)
        started = time.perf_counter()
        results = pool.recognize_text(
            window_title=f"OCRBench-{index}",
            window_hwnd=10000 + index,
            image=sample.image,
            confidence=0.1,
            timeout=60.0,
            resource_key=f"bench-window-{index}",
        )
        return {
            "index": index,
            "round": round_index,
            "elapsed": time.perf_counter() - started,
            "success": bool(results),
            "correct": _is_correct(sample, results),
            "texts": _result_texts(results),
            "file": sample.path.name,
            "expected": sample.expected,
        }

    batch_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(recognize, index) for index in range(concurrency)]
        results = [future.result() for future in as_completed(futures)]
    return time.perf_counter() - batch_started, results


def benchmark_pool_level(
    samples: Sequence[Sample],
    concurrency: int,
    warm_rounds: int,
) -> Dict[str, Any]:
    from services.multiprocess_ocr_pool import MultiProcessOCRPool

    pool = MultiProcessOCRPool()
    sampler = ProcessTreeSampler()
    sampler.start()
    all_results: List[Dict[str, Any]] = []
    batch_wall_times: List[float] = []
    started = time.perf_counter()

    for round_index in range(max(1, warm_rounds + 1)):
        wall_time, results = _run_concurrent_batch(
            pool,
            samples,
            concurrency,
            round_index,
        )
        batch_wall_times.append(wall_time)
        all_results.extend(results)

    workload_seconds = time.perf_counter() - started
    try:
        pool_stats_before_cleanup = pool.get_stats()
    except Exception:
        pool_stats_before_cleanup = {}
    child_count_before_cleanup = len(psutil.Process(os.getpid()).children(recursive=True))
    resource_stats = sampler.stop()

    cleanup_started = time.perf_counter()
    pool.cleanup_all_processes()
    cleanup_seconds = time.perf_counter() - cleanup_started
    time.sleep(0.2)
    child_count_after_cleanup = len(psutil.Process(os.getpid()).children(recursive=True))
    request_count = len(all_results)
    latencies = [float(item["elapsed"]) for item in all_results]
    resource_stats["average_cpu_cores"] = round(
        resource_stats["cpu_seconds"] / workload_seconds if workload_seconds > 0 else 0.0,
        3,
    )

    return {
        "concurrency": concurrency,
        "rounds": max(1, warm_rounds + 1),
        "request_count": request_count,
        "successful_requests": sum(1 for item in all_results if item["success"]),
        "correct_requests": sum(1 for item in all_results if item["correct"]),
        "success_rate": round(
            sum(1 for item in all_results if item["success"]) / request_count,
            4,
        ) if request_count else 0.0,
        "correct_rate": round(
            sum(1 for item in all_results if item["correct"]) / request_count,
            4,
        ) if request_count else 0.0,
        "workload_seconds": round(workload_seconds, 4),
        "throughput_rps": round(request_count / workload_seconds, 3) if workload_seconds else 0.0,
        "batch_wall_seconds": [round(value, 4) for value in batch_wall_times],
        "latency": _latency_summary(latencies),
        "resource": resource_stats,
        "pool_stats_before_cleanup": pool_stats_before_cleanup,
        "child_count_before_cleanup": child_count_before_cleanup,
        "cleanup_seconds": round(cleanup_seconds, 4),
        "child_count_after_cleanup": child_count_after_cleanup,
        "requests": sorted(all_results, key=lambda item: (item["round"], item["index"])),
    }


def benchmark_pool(
    samples: Sequence[Sample],
    concurrency_levels: Sequence[int],
    warm_rounds: int,
) -> Dict[str, Any]:
    levels = []
    for concurrency in concurrency_levels:
        levels.append(benchmark_pool_level(samples, concurrency, warm_rounds))
    return {
        "kind": "pool",
        "engine": "rapidocr",
        "levels": levels,
    }


def _parse_concurrency(value: str) -> List[int]:
    result = []
    for item in str(value or "").split(","):
        item = item.strip()
        if not item:
            continue
        result.append(max(1, int(item)))
    return result or [1, 3, 5, 10]


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark LCA OCR runtime")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--images-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--mode", choices=("service", "pool"), required=True)
    parser.add_argument("--steady-iterations", type=int, default=200)
    parser.add_argument("--concurrency", default="1,3,5,10")
    parser.add_argument("--warm-rounds", type=int, default=2)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    images_root = Path(args.images_root).resolve()
    manifest_path = Path(args.manifest).resolve()
    output_path = Path(args.output).resolve()
    _configure_project(project_root)
    samples = _load_manifest(manifest_path, images_root)

    if args.mode == "service":
        result = benchmark_service(samples, args.steady_iterations)
    else:
        result = benchmark_pool(
            samples,
            _parse_concurrency(args.concurrency),
            args.warm_rounds,
        )

    result["project_root"] = str(project_root)
    result["images_root"] = str(images_root)
    result["sample_count"] = len(samples)
    result["logical_cpu_count"] = os.cpu_count()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
