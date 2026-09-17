# SPDX-License-Identifier: GPL-3.0-or-later
"""Spine 实时加载、渲染与定位元数据读取性能基准测试。

抽样 10 个 Default 角色与 10 个 Costume 模型，测量：
- Cold load
- Warm load
- Render
- Placement metadata lookup
计算 P50 与 P95。
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import time
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from astrbot_plugin_nikke.integrations.spine.runtime import SpineBundle, SpineSkeletonParser
from astrbot_plugin_nikke.integrations.spine.renderer import SpineRenderer
from astrbot_plugin_nikke.integrations.spine.semantic_mapper import SpineSemanticMapper
from astrbot_plugin_nikke.integrations.spine.placement import compute_placement_meta

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("benchmark_spine_placement")


def run_benchmark(base_dir: Path | str) -> dict:
    base = Path(base_dir).resolve()
    mappings_dir = base / "assets" / "mappings"

    placement_file = mappings_dir / "character_placement_meta.json"
    placements_all = json.loads(placement_file.read_text(encoding="utf-8")).get("entries", {})

    # 抽样 10 个 Default 与 10 个 Costume
    default_keys = [k for k in placements_all.keys() if k.endswith(":default")][:10]
    costume_keys = [k for k in placements_all.keys() if not k.endswith(":default")][:10]
    sample_keys = default_keys + costume_keys

    # 1. Placement Lookup Benchmark
    lookup_times = []
    for _ in range(50):
        for k in sample_keys:
            t0 = time.perf_counter()
            _ = placements_all.get(k)
            lookup_times.append((time.perf_counter() - t0) * 1000.0)  # ms

    # 2. Skeleton Parsing Benchmark (Cold vs Warm)
    c470_skel = base.parent / "scratch" / "c470_bundle" / "skel.skel"
    cold_load_times = []
    warm_load_times = []
    render_times = []

    renderer = SpineRenderer()
    dummy_bundle = None
    if c470_skel.is_file():
        atlas_file = c470_skel.with_name("atlas.atlas")
        png_file = c470_skel.with_name("c470_00.png")
        dummy_bundle = SpineBundle.from_files(c470_skel, atlas_file, [png_file], spine_version="4.1")

    if dummy_bundle and dummy_bundle.skeleton:
        # Cold load
        for _ in range(10):
            t0 = time.perf_counter()
            _ = SpineSkeletonParser.parse(dummy_bundle.skeleton)
            cold_load_times.append((time.perf_counter() - t0) * 1000.0)

        # Warm load (using cache)
        for _ in range(30):
            t0 = time.perf_counter()
            _ = renderer.cache.get("c470_skel_test")
            warm_load_times.append((time.perf_counter() - t0) * 1000.0)

        # Render
        for _ in range(20):
            t0 = time.perf_counter()
            _ = renderer.render(dummy_bundle)
            render_times.append((time.perf_counter() - t0) * 1000.0)

    def calc_percentiles(data: list[float]) -> dict[str, float]:
        if not data:
            return {"p50": 0.0, "p95": 0.0, "mean": 0.0}
        s = sorted(data)
        p50 = s[int(len(s) * 0.50)]
        p95 = s[min(int(len(s) * 0.95), len(s) - 1)]
        return {"p50": round(p50, 4), "p95": round(p95, 4), "mean": round(statistics.mean(s), 4)}

    results = {
        "sample_size": len(sample_keys),
        "default_samples": len(default_keys),
        "costume_samples": len(costume_keys),
        "placement_lookup_ms": calc_percentiles(lookup_times),
        "cold_load_ms": calc_percentiles(cold_load_times),
        "warm_load_ms": calc_percentiles(warm_load_times),
        "render_ms": calc_percentiles(render_times),
    }

    print("==================================================")
    print("Spine Placement & Runtime Performance Benchmark")
    print("==================================================")
    print(f"Sample items: {results['sample_size']} ({results['default_samples']} default + {results['costume_samples']} costume)")
    print(f"Placement Metadata Lookup : P50 = {results['placement_lookup_ms']['p50']} ms, P95 = {results['placement_lookup_ms']['p95']} ms")
    if cold_load_times:
        print(f"Skeleton Cold Load (skel) : P50 = {results['cold_load_ms']['p50']} ms, P95 = {results['cold_load_ms']['p95']} ms")
        print(f"Memory Warm Load (cache)  : P50 = {results['warm_load_ms']['p50']} ms, P95 = {results['warm_load_ms']['p95']} ms")
        print(f"Runtime Render (in-memory): P50 = {results['render_ms']['p50']} ms, P95 = {results['render_ms']['p95']} ms")
    print("==================================================")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark Spine Placement")
    parser.add_argument("--base-dir", default=str(REPO_ROOT))
    args = parser.parse_args()
    run_benchmark(args.base_dir)
