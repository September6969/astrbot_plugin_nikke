"""在线立绘的端到端预算、共享执行和底层 worker 回收。"""

import concurrent.futures
import subprocess
import sys
import threading
import time
import asyncio
from unittest.mock import patch

import pytest
from PIL import Image

from astrbot_plugin_nikke.integrations.spine.prerenderer import SpinePreRenderer, SpineBundleFetcher, SpineRenderError
from astrbot_plugin_nikke.integrations.spine.worker_caller import SpineWorkerConfig, SpineWorkerRuntime
from astrbot_plugin_nikke.tests.test_spine_formal_backend import make_bundle


class Runtime:
    version = "4.1"

    def __init__(self, delay=0):
        self.calls = 0
        self.delay = delay
        self.started = threading.Event()

    def render(self, bundle, *, animation, skin=None, deadline=None):
        self.calls += 1
        self.started.set()
        time.sleep(self.delay)
        return Image.new("RGBA", (8, 8), "white")


class Fetcher:
    def __init__(self, bundle):
        self.bundle = bundle
        self.calls = 0

    def fetch(self, *args, **kwargs):
        self.calls += 1
        return self.bundle


def render(renderer, budget=1):
    return renderer.render_remote_portrait(asset_id="c020", source_version="a" * 40,
        urls={}, cache_key="test-key", runtime_version="4.1", budget_seconds=budget)


def test_expired_render_cannot_publish_late_cache(tmp_path):
    runtime = Runtime(.15)
    fetcher = Fetcher(make_bundle(tmp_path / "bundle"))
    renderer = SpinePreRenderer(tmp_path / "cache", runtime=runtime, fetcher=fetcher)
    start = time.monotonic()
    assert render(renderer, .02) is None
    assert time.monotonic() - start < .12
    time.sleep(.18)
    assert renderer.cached_portrait("test-key") is None
    assert not list(renderer.prerender_dir.glob("*.tmp"))
    renderer.close()


def test_singleflight_short_waiter_does_not_cancel_shared_success(tmp_path):
    runtime = Runtime(.08)
    fetcher = Fetcher(make_bundle(tmp_path / "bundle"))
    renderer = SpinePreRenderer(tmp_path / "cache", runtime=runtime, fetcher=fetcher)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        first = pool.submit(render, renderer, 1)
        assert runtime.started.wait(1)
        start = time.monotonic()
        assert render(renderer, .01) is None
        assert time.monotonic() - start < .1
        others = [pool.submit(render, renderer, 1) for _ in range(4)]
        assert first.result() is not None
        assert all(task.result() is not None for task in others)
    assert (runtime.calls, fetcher.calls) == (1, 1)
    assert render(renderer) is not None
    assert runtime.calls == 1
    renderer.close()


@pytest.mark.parametrize("phase", ["connect", "first_chunk"])
def test_http_wait_uses_remaining_not_configured_maximum(tmp_path, phase):
    import httpx
    fetcher = SpineBundleFetcher(tmp_path, timeout_seconds=5)
    class Response:
        async def __aenter__(self):
            if phase == "connect":
                await asyncio.sleep(10)
            return self
        async def __aexit__(self, *args):
            pass
        def raise_for_status(self):
            pass
        async def aiter_bytes(self):
            await asyncio.sleep(10)
            yield b""
    class Client:
        def __init__(self, **kwargs):
            assert kwargs["timeout"].connect <= .02
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def stream(self, *args):
            return Response()
    base = "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d/c020/hero"
    start = time.monotonic()
    with patch("astrbot_plugin_nikke.integrations.spine.prerenderer.httpx.AsyncClient", Client):
        with pytest.raises(SpineRenderError):
            fetcher.fetch({"skel": base + ".json", "atlas": base + ".atlas"}, "key", budget_seconds=.02)
    assert time.monotonic() - start < .1


def test_official_adapter_deadline_kills_reaps_and_cleans_real_subprocess(tmp_path):
    bundle = make_bundle(tmp_path)
    runtime = SpineWorkerRuntime(SpineWorkerConfig(tmp_path / "worker", tmp_path), version="4.1")
    actual_run = subprocess.run
    actual_popen = subprocess.Popen
    processes = []
    def popen(*args, **kwargs):
        process = actual_popen(*args, **kwargs)
        processes.append(process)
        return process
    def run(command, **kwargs):
        assert kwargs["timeout"] <= .04
        return actual_run([sys.executable, "-c", "import time; time.sleep(10)"], **kwargs)
    start = time.monotonic()
    with patch("subprocess.Popen", side_effect=popen), patch("subprocess.run", side_effect=run):
        with pytest.raises(SpineRenderError):
            runtime.render(bundle, animation="idle", deadline=time.monotonic() + .04)
    assert time.monotonic() - start < .5
    assert processes and all(process.poll() is not None for process in processes)
    assert not list(tmp_path.glob(".spine-worker-*"))
