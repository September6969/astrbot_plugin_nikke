# SPDX-License-Identifier: GPL-3.0-or-later
"""独立基准测试脚本：统计真实微基准指标（中位数、P95、样本数）。"""

import asyncio
import hashlib
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent
PROJECTS_DIR = REPO_ROOT.parent

for p in (PROJECTS_DIR, REPO_ROOT, CURRENT_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from cryptography.fernet import Fernet
from astrbot_plugin_nikke.character_identity import CharacterDirectoryResolver
from astrbot_plugin_nikke.storage import NikkeStore
from astrbot_plugin_nikke.voice_audio import VoiceAudioCache
from astrbot_plugin_nikke.voice_resource_provider import VoiceResourceProvider


def percentile(data, p):
    data_sorted = sorted(data)
    idx = int(len(data_sorted) * p)
    return data_sorted[min(idx, len(data_sorted) - 1)]


async def benchmark_voice_registry():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        voices = root / "voices"
        voices.mkdir()
        reg_file = voices / "registry.json"
        sample_rows = [
            {"character": f"char_{i}", "license": "official", "source": "test", "file": f"c{i}.wav"}
            for i in range(50)
        ]
        reg_file.write_text(json.dumps(sample_rows), encoding="utf-8")

        cache = VoiceAudioCache(voices, root / "cache")
        # 预热一次
        await cache._load_registry()

        # Before (每次读盘与反序列化)
        samples_before = []
        for _ in range(1000):
            t0 = time.perf_counter_ns()
            _ = json.loads(reg_file.read_text(encoding="utf-8"))
            t1 = time.perf_counter_ns()
            samples_before.append((t1 - t0) / 1000.0)  # 微秒

        # After (mtime 内存缓存)
        samples_after = []
        for _ in range(1000):
            t0 = time.perf_counter_ns()
            _ = await cache._load_registry()
            t1 = time.perf_counter_ns()
            samples_after.append((t1 - t0) / 1000.0)

        print(json.dumps({
            "name": "voice_registry_json_load",
            "samples": 1000,
            "unit": "us",
            "before_median": statistics.median(samples_before),
            "before_p95": percentile(samples_before, 0.95),
            "after_median": statistics.median(samples_after),
            "after_p95": percentile(samples_after, 0.95),
        }))


async def benchmark_cached_source():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        provider = VoiceResourceProvider(root)
        source_dir = root / "source"
        source_dir.mkdir()

        audio_bytes = b"ID3" + b"\x00" * (100 * 1024)  # 100 KB
        sha = hashlib.sha256(audio_bytes).hexdigest()
        target = source_dir / "test.mp3"
        manifest = source_dir / "test.json"
        target.write_bytes(audio_bytes)
        manifest.write_text(json.dumps({
            "sha256": sha,
            "source_path": "/voice/ja/line_1.mp3",
            "map_key": "map_test",
        }), encoding="utf-8")

        # Baseline _cached_source implementation (full execution: symlink check, stat, read_bytes, json decode, sha256)
        def cached_source_baseline(p, tgt, mnf, mk, sid, loc):
            try:
                if not p._cache_path_is_safe() or tgt.is_symlink() or mnf.is_symlink():
                    return None
                age = time.time() - mnf.stat().st_mtime
                if not tgt.is_file() or not mnf.is_file() or not 0 <= age < 86400 or tgt.stat().st_size > p.MAX_BYTES:
                    return None
                raw = tgt.read_bytes()
                saved = json.loads(mnf.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError):
                return None
            expected_source_path = f"/voice/{loc}/{sid}.mp3"
            if (
                not isinstance(saved, dict)
                or saved.get("sha256") != hashlib.sha256(raw).hexdigest()
                or saved.get("source_path") != expected_source_path
                or saved.get("map_key") != mk
                or not p.is_mp3(raw)
            ):
                return None
            return tgt

        # Warm up both
        assert cached_source_baseline(provider, target, manifest, "map_test", "line_1", "ja") is not None
        assert provider._cached_source(target, manifest, "map_test", "line_1", "ja") is not None

        # Before (baseline: disk reads + sha256 hashing on every access)
        samples_before = []
        for _ in range(1000):
            t0 = time.perf_counter_ns()
            res = cached_source_baseline(provider, target, manifest, "map_test", "line_1", "ja")
            t1 = time.perf_counter_ns()
            samples_before.append((t1 - t0) / 1000.0)
            assert res is not None

        # After (optimized: fast metadata/stat check + verified cache hit)
        samples_after = []
        for _ in range(1000):
            t0 = time.perf_counter_ns()
            res = provider._cached_source(target, manifest, "map_test", "line_1", "ja")
            t1 = time.perf_counter_ns()
            samples_after.append((t1 - t0) / 1000.0)
            assert res is not None

        print(json.dumps({
            "name": "voice_cached_source_validation_100kb",
            "samples": 1000,
            "unit": "us",
            "before_median": statistics.median(samples_before),
            "before_p95": percentile(samples_before, 0.95),
            "after_median": statistics.median(samples_after),
            "after_p95": percentile(samples_after, 0.95),
        }))


def benchmark_list_accounts():
    with tempfile.TemporaryDirectory() as td:
        store = NikkeStore(td)
        n_accounts = 10
        for i in range(n_accounts):
            token = f"tok_{i}_" + "x" * 20
            store.create_bind_session(token, f"qq_{i}")
            store.consume_bind_session(token, f"game_token=abc_{i}; uid={i}", str(i), f"open_{i}", f"nick_{i}", f"role_{i}", "global")

        # Before: 模拟原有的 N+1 次 SQL 连接与查询
        samples_before = []
        for _ in range(100):
            t0 = time.perf_counter_ns()
            with store._lock, store._connect() as conn:
                ids = [r[0] for r in conn.execute("SELECT qq_id FROM accounts").fetchall()]
            _ = [store.get_account(qq_id, with_cookie=True) for qq_id in ids]
            t1 = time.perf_counter_ns()
            samples_before.append((t1 - t0) / 1_000_000.0)  # 毫秒

        # After: 单次 SQL SELECT * 并在内存循环中解密
        samples_after = []
        for _ in range(100):
            t0 = time.perf_counter_ns()
            _ = store.list_accounts(with_cookie=True)
            t1 = time.perf_counter_ns()
            samples_after.append((t1 - t0) / 1_000_000.0)

        print(json.dumps({
            "name": f"list_accounts_{n_accounts}_accounts",
            "samples": 100,
            "unit": "ms",
            "before_median": statistics.median(samples_before),
            "before_p95": percentile(samples_before, 0.95),
            "after_median": statistics.median(samples_after),
            "after_p95": percentile(samples_after, 0.95),
        }))


def benchmark_name_map():
    resolver = CharacterDirectoryResolver()
    sample_dir = [
        {"name_code": i, "name_cn": f"角色_{i}", "name_en": f"Char_{i}", "name_zh_tw": f"角色_{i}"}
        for i in range(200)
    ]

    # Before: 每次遍历 200 个 dict 并调用 enrich / display_name
    samples_before = []
    for _ in range(1000):
        t0 = time.perf_counter_ns()
        _ = {str(item["name_code"]): resolver.display_name(resolver.enrich(item)) for item in sample_dir}
        t1 = time.perf_counter_ns()
        samples_before.append((t1 - t0) / 1000.0)

    # After: 计算指纹并直接命中内存缓存
    fingerprint = hashlib.sha256("".join(f"{item['name_code']}:{item['name_cn']}:{item['name_en']}:{item['name_zh_tw']};" for item in sample_dir).encode("utf-8")).hexdigest()
    precomputed = {str(item["name_code"]): resolver.display_name(resolver.enrich(item)) for item in sample_dir}
    cache = (fingerprint, precomputed)

    samples_after = []
    for _ in range(1000):
        t0 = time.perf_counter_ns()
        fp = hashlib.sha256("".join(f"{item['name_code']}:{item['name_cn']}:{item['name_en']}:{item['name_zh_tw']};" for item in sample_dir).encode("utf-8")).hexdigest()
        if cache[0] == fp:
            _ = cache[1]
        t1 = time.perf_counter_ns()
        samples_after.append((t1 - t0) / 1000.0)

    print(json.dumps({
        "name": "name_map_200_chars",
        "samples": 1000,
        "unit": "us",
        "before_median": statistics.median(samples_before),
        "before_p95": percentile(samples_before, 0.95),
        "after_median": statistics.median(samples_after),
        "after_p95": percentile(samples_after, 0.95),
    }))


async def main():
    await benchmark_voice_registry()
    await benchmark_cached_source()
    benchmark_list_accounts()
    benchmark_name_map()


if __name__ == "__main__":
    asyncio.run(main())
