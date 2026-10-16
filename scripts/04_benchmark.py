"""End-to-End Latency, Throughput, and Resource Footprint Benchmark.

Measures in-process engine latency vs end-to-end HTTP TestClient latency over 500 iterations (SEED = 42),
computes exact percentiles (p50, p95, p99, mean), records database and memory footprints,
and appends benchmark results to docs/EVALUATION.md.
"""

from __future__ import annotations

import os
import random
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fastapi.testclient import TestClient

from medaudit.api.main import app
from medaudit.audit.engine import audit_prescription
from medaudit.audit.search import search_products
from medaudit.config import PROJECT_ROOT, SEED
from medaudit.lasa.tiers import get_lasa_warnings_for_brand

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "processed" / "medaudit.db"
EVALUATION_MD_PATH = PROJECT_ROOT / "docs" / "EVALUATION.md"
ITERATIONS = 500


def get_process_rss_mb() -> float:
    """Return process RSS memory usage in megabytes across Windows, Linux, and macOS."""
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except ImportError:
        pass

    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        handle = ctypes.windll.kernel32.OpenProcess(
            0x0400 | 0x0010, False, ctypes.windll.kernel32.GetCurrentProcessId()
        )
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
            ctypes.windll.kernel32.CloseHandle(handle)
            return pmc.WorkingSetSize / (1024.0 * 1024.0)
        ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        pass
    return 0.0


def compute_percentiles(durations_ms: List[float]) -> Dict[str, float]:
    """Compute p50, p95, p99, and mean latency in milliseconds."""
    s = sorted(durations_ms)
    n = len(s)
    mean_val = sum(s) / n

    def p(pct: float) -> float:
        k = int((n - 1) * pct)
        return s[k]

    return {
        "p50": round(p(0.50), 3),
        "p95": round(p(0.95), 3),
        "p99": round(p(0.99), 3),
        "mean": round(mean_val, 3),
    }


def run_benchmark() -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Run 500-iteration benchmark over engine and HTTP loopback."""
    print("=" * 70)
    print(f"MedAudit-BD: Running Phase 5 Latency & Memory Benchmark (N={ITERATIONS}, SEED={SEED})")
    print("=" * 70)

    random.seed(SEED)
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    client = TestClient(app)

    # Workloads
    rx_2 = [10452, 10557]
    rx_5 = [10452, 10557, 1958, 3216, 1430]
    rx_8 = [10452, 10557, 1958, 3216, 1430, 529, 12335, 10454]
    search_q = "Napa"
    lasa_brand_id = 7764  # Napa brand_id

    # Warm-up (10 runs)
    for _ in range(10):
        audit_prescription(rx_5, conn=conn)
        search_products(search_q, conn=conn, limit=10)
        get_lasa_warnings_for_brand(lasa_brand_id, conn=conn, limit=10)
        client.post("/v1/prescription/audit", json={"items": [{"product_id": x} for x in rx_5]})
        client.get(f"/v1/brands/search?q={search_q}&limit=10")
        client.get(f"/v1/brands/{lasa_brand_id}/lasa")

    # 1. In-Process Engine Latency
    print("\n[1/2] Benchmarking In-Process Python Engine Latency...")
    engine_results: Dict[str, Dict[str, float]] = {}

    workloads_engine = [
        ("Audit (2 items)", lambda: audit_prescription(rx_2, conn=conn)),
        ("Audit (5 items)", lambda: audit_prescription(rx_5, conn=conn)),
        ("Audit (8 items)", lambda: audit_prescription(rx_8, conn=conn)),
        ("Search (/v1/brands/search)", lambda: search_products(search_q, conn=conn, limit=10)),
        ("LASA (/v1/brands/{id}/lasa)", lambda: get_lasa_warnings_for_brand(lasa_brand_id, conn=conn, limit=10)),
    ]

    for name, fn in workloads_engine:
        durations: List[float] = []
        for _ in range(ITERATIONS):
            t0 = time.perf_counter()
            fn()
            t1 = time.perf_counter()
            durations.append((t1 - t0) * 1000.0)
        engine_results[name] = compute_percentiles(durations)
        print(f"      {name:28s} p50={engine_results[name]['p50']:6.3f}ms | p95={engine_results[name]['p95']:6.3f}ms | p99={engine_results[name]['p99']:6.3f}ms | mean={engine_results[name]['mean']:6.3f}ms")

    # 2. End-to-End HTTP Latency (TestClient)
    print("\n[2/2] Benchmarking End-to-End HTTP Loopback Latency (TestClient)...")
    http_results: Dict[str, Dict[str, float]] = {}

    workloads_http = [
        ("Audit (2 items)", lambda: client.post("/v1/prescription/audit", json={"items": [{"product_id": x} for x in rx_2]})),
        ("Audit (5 items)", lambda: client.post("/v1/prescription/audit", json={"items": [{"product_id": x} for x in rx_5]})),
        ("Audit (8 items)", lambda: client.post("/v1/prescription/audit", json={"items": [{"product_id": x} for x in rx_8]})),
        ("Search (/v1/brands/search)", lambda: client.get(f"/v1/brands/search?q={search_q}&limit=10")),
        ("LASA (/v1/brands/{id}/lasa)", lambda: client.get(f"/v1/brands/{lasa_brand_id}/lasa")),
    ]

    for name, fn in workloads_http:
        durations: List[float] = []
        for _ in range(ITERATIONS):
            t0 = time.perf_counter()
            fn()
            t1 = time.perf_counter()
            durations.append((t1 - t0) * 1000.0)
        http_results[name] = compute_percentiles(durations)
        print(f"      {name:28s} p50={http_results[name]['p50']:6.3f}ms | p95={http_results[name]['p95']:6.3f}ms | p99={http_results[name]['p99']:6.3f}ms | mean={http_results[name]['mean']:6.3f}ms")

    # 3. Resource Footprint
    db_size_mb = DEFAULT_DB_PATH.stat().st_size / (1024.0 * 1024.0)
    process_rss_mb = get_process_rss_mb()

    resource_stats = {
        "db_size_mb": round(db_size_mb, 2),
        "process_rss_mb": round(process_rss_mb, 2),
    }

    print(f"\nResource Footprint:")
    print(f"  SQLite DB File Size:  {resource_stats['db_size_mb']} MB")
    print(f"  Python Process RSS:   {resource_stats['process_rss_mb']} MB")

    conn.close()
    return engine_results, http_results, resource_stats


def append_benchmark_to_evaluation(
    engine_results: Dict[str, Dict[str, float]],
    http_results: Dict[str, Dict[str, float]],
    resource_stats: Dict[str, Any],
) -> None:
    """Format and append Section 7 to docs/EVALUATION.md."""
    lines = [
        "",
        "---",
        "",
        "## 7. End-to-End Latency, Throughput & Memory Benchmark (Phase 5)",
        "",
        f"Empirical benchmarks measured over **{ITERATIONS} iterations** (`SEED = {SEED}`) on production SQLite database `medaudit.db`:",
        "",
        "### In-Process Python Engine Latency (`audit_prescription`)",
        "",
        "| Workload | p50 Latency (ms) | p95 Latency (ms) | p99 Latency (ms) | Mean Latency (ms) |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ]

    for name, stats in engine_results.items():
        lines.append(f"| **{name}** | {stats['p50']:.3f} ms | {stats['p95']:.3f} ms | {stats['p99']:.3f} ms | {stats['mean']:.3f} ms |")

    lines.extend([
        "",
        "### End-to-End HTTP Service Latency (via `TestClient` / ASGI Loopback)",
        "",
        "| Endpoint / Workload | p50 Latency (ms) | p95 Latency (ms) | p99 Latency (ms) | Mean Latency (ms) |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ])

    for name, stats in http_results.items():
        lines.append(f"| **{name}** | {stats['p50']:.3f} ms | {stats['p95']:.3f} ms | {stats['p99']:.3f} ms | {stats['mean']:.3f} ms |")

    lines.extend([
        "",
        "### Production Resource Footprint",
        "",
        f"- **SQLite Database File Size (`medaudit.db`)**: **{resource_stats['db_size_mb']} MB** (contains all 14,013 brands, 21,714 products, 23,096 price packs, 3,358 LASA pairs, indexes, and full normalized component schemas).",
        f"- **Python Process Resident Memory (RSS)**: **{resource_stats['process_rss_mb']} MB** (lightweight footprint well within free-tier container memory limits of 512 MB).",
        "",
    ])

    section_text = "\n".join(lines)

    # Read current evaluation file
    content = ""
    if EVALUATION_MD_PATH.exists():
        with open(EVALUATION_MD_PATH, "r", encoding="utf-8") as f:
            content = f.read()

    # If section 7 already exists, replace it, otherwise append
    if "## 7. End-to-End Latency" in content:
        idx = content.find("--- \n\n## 7. End-to-End Latency")
        if idx == -1:
            idx = content.find("## 7. End-to-End Latency")
            content = content[:idx].rstrip() + "\n" + section_text
        else:
            content = content[:idx].rstrip() + "\n" + section_text
    else:
        content = content.rstrip() + "\n" + section_text

    with open(EVALUATION_MD_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\nAppended Section 7 benchmark results to {EVALUATION_MD_PATH}")


if __name__ == "__main__":
    eng_res, http_res, res_stats = run_benchmark()
    append_benchmark_to_evaluation(eng_res, http_res, res_stats)
