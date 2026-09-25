# SPDX-License-Identifier: GPL-3.0-or-later
"""用仓库锁定的官方 Spine worker 验证运行时角色立绘与白卡链路。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from jinja2 import Environment
from PIL import Image

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.core.assets.fallback_provider import FallbackAssetProvider
from astrbot_plugin_nikke.integrations.spine.prerenderer import SpinePreRenderer
from astrbot_plugin_nikke.integrations.spine.runtime import detect_spine_version
from astrbot_plugin_nikke.integrations.spine.worker_caller import SpineWorkerConfig, SpineWorkerRuntime
from astrbot_plugin_nikke.tests.test_character_replica import example_card
from astrbot_plugin_nikke.ui.payloads.character import CharacterT2IPayloadBuilder
from astrbot_plugin_nikke.ui.t2i_assets import T2IAssetResolver
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader


ROOT = Path(__file__).resolve().parents[1]
WORKER_IMAGES = {
    "4.0": os.environ.get("NIKKE_SPINE_E2E_WORKER_40_IMAGE", ""),
    "4.1": os.environ.get("NIKKE_SPINE_E2E_WORKER_41_IMAGE", ""),
}
OFFICIAL_WORKER_E2E_ENABLED = all(WORKER_IMAGES.values())


class _CountingOfficialWorker(SpineWorkerRuntime):
    """统计真实 worker 调用；渲染仍由 SpineWorkerRuntime 执行 Docker worker。"""

    def __init__(self, config: SpineWorkerConfig, *, version: str) -> None:
        super().__init__(config, version=version)
        self.calls = 0

    def render(self, bundle, *, animation: str, skin: str | None = None) -> Image.Image:
        self.calls += 1
        return super().render(bundle, animation=animation, skin=skin)


class OfficialRuntimeCharacterPortraitTests(unittest.TestCase):
    @unittest.skipUnless(
        OFFICIAL_WORKER_E2E_ENABLED,
        "需在官方 Spine worker CI job 中运行",
    )
    def test_bundled_and_runtime_portraits_render_current_white_card(self) -> None:
        cache_root = Path(os.environ["NIKKE_SPINE_E2E_CACHE_ROOT"])
        evidence_root = Path(os.environ["NIKKE_SPINE_E2E_EVIDENCE_DIR"])
        evidence_root.mkdir(parents=True, exist_ok=True)
        cache_root.mkdir(parents=True, exist_ok=True)
        bundle_root = cache_root / "spine-bundles"
        bundle_root.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="spine-worker-bridge-") as bridge_dir:
            bridge_root = Path(bridge_dir)
            worker_runtimes: dict[str, _CountingOfficialWorker] = {}
            for version, image in WORKER_IMAGES.items():
                executable = bridge_root / f"official-spine-worker-{version.replace('.', '-')}.py"
                executable.write_text(
                    "#!/usr/bin/env python3\n"
                    "import subprocess, sys\n"
                    "from pathlib import Path\n"
                    f"sys.path.insert(0, {str(ROOT.parent)!r})\n"
                    "from astrbot_plugin_nikke.scripts.spine_worker_docker_bridge import build_docker_command\n"
                    f"command = build_docker_command({image!r}, Path.cwd(), sys.argv[1:])\n"
                    "raise SystemExit(subprocess.run(command, check=False, timeout=90).returncode)\n",
                    encoding="utf-8",
                )
                executable.chmod(0o755)
                worker_runtimes[version] = _CountingOfficialWorker(
                    SpineWorkerConfig(
                        executable=executable,
                        bundle_root=bundle_root,
                        timeout_seconds=5.0,
                    ),
                    version=version,
                )

            renderer = SpinePreRenderer(cache_root, runtime=worker_runtimes)
            manager = AssetManager(
                cache_root,
                ROOT / "assets",
                remote=True,
                spine_renderer=renderer,
                spine_budget_seconds=30.0,
            )
            fetcher = renderer.fetcher
            original_fetch = fetcher.fetch
            fetched_bundles: list[Any] = []
            fetch_calls = 0

            def counted_fetch(*args, **kwargs):
                nonlocal fetch_calls
                fetch_calls += 1
                bundle = original_fetch(*args, **kwargs)
                fetched_bundles.append(bundle)
                return bundle

            fetcher.fetch = counted_fetch
            evidence: dict[str, Any] = {"schema_version": 1, "cards": []}
            try:
                self.assertTrue(manager.spine_manifest.is_declared("c018"))
                with patch.object(
                    manager.nikke_db,
                    "resolve_spine_bundle_source",
                    side_effect=AssertionError("c018 必须直接使用 bundled portrait"),
                ):
                    bundled = manager.get_character_portrait("c018", "18", 0)
                self.assertEqual((fetch_calls, sum(worker.calls for worker in worker_runtimes.values())), (0, 0))
                card_evidence = self._render_white_card(
                    render_id="c018",
                    resource_id="18",
                    portrait=bundled,
                    manager=manager,
                    evidence_root=evidence_root,
                )
                evidence["cards"].append(
                    {
                        "render_id": "c018",
                        "resource_id": "18",
                        "first_request": "bundled_verified_portrait",
                        "second_request": "not_needed",
                        "worker_invocations": 0,
                        "portrait_source": "assets/spine_manifest.json",
                        "portrait_rgba_sha256": hashlib.sha256(bundled.tobytes()).hexdigest(),
                        "white_card": card_evidence,
                    }
                )
                self._write_evidence(evidence_root, evidence)

                for render_id, resource_id in (("c014", "14"), ("c020", "20")):
                    with self.subTest(render_id=render_id):
                        self.assertEqual(manager.nikke_db.resolve_render_id(resource_id), render_id)
                        source = manager.nikke_db.resolve_spine_bundle_source(render_id, allow_remote=True)
                        self.assertIsNotNone(source, f"{render_id} 应有完整上游 Spine bundle")
                        self.assertTrue(source.commit_sha)
                        before_fetch = fetch_calls
                        before_calls = {version: worker.calls for version, worker in worker_runtimes.items()}
                        before_cache = len(list(renderer.prerender_dir.glob("*.png")))

                        first = manager.get_character_portrait(render_id, resource_id, 0)
                        self.assertEqual(fetch_calls, before_fetch + 1, "首次请求应实际获取上游 bundle")
                        self.assertEqual(len(fetched_bundles), fetch_calls)
                        self.assertEqual(len(fetched_bundles), before_fetch + 1)
                        self.assertEqual(sum(worker.calls for worker in worker_runtimes.values()), sum(before_calls.values()) + 1)
                        self.assertNotEqual(first.size, (600, 900), "首次请求不得返回中性占位图")
                        self.assertIsNotNone(first.getchannel("A").getbbox(), "Spine 渲染应含可见人物像素")
                        self.assertEqual(len(list(renderer.prerender_dir.glob("*.png"))), before_cache + 1)

                        bundle = fetched_bundles[-1]
                        spine_version = detect_spine_version(bundle.skeleton)
                        self.assertIn(spine_version, worker_runtimes)
                        self.assertEqual(
                            worker_runtimes[spine_version].calls,
                            before_calls[spine_version] + 1,
                            "应调用与 skeleton 版本匹配的官方 worker",
                        )
                        for version, worker in worker_runtimes.items():
                            self.assertEqual(worker.calls, before_calls[version] + (version == spine_version))

                        after_first_fetch = fetch_calls
                        after_first_calls = {version: worker.calls for version, worker in worker_runtimes.items()}
                        after_first_cache = len(list(renderer.prerender_dir.glob("*.png")))
                        second = manager.get_character_portrait(render_id, resource_id, 0)
                        self.assertEqual(fetch_calls, after_first_fetch, "缓存命中不应重新获取 bundle")
                        self.assertEqual(
                            {version: worker.calls for version, worker in worker_runtimes.items()},
                            after_first_calls,
                            "第二次请求不得再次调用官方 worker",
                        )
                        self.assertEqual(len(list(renderer.prerender_dir.glob("*.png"))), after_first_cache)
                        self.assertEqual(first.size, second.size)
                        self.assertEqual(first.tobytes(), second.tobytes())

                        card_evidence = self._render_white_card(
                            render_id=render_id,
                            resource_id=resource_id,
                            portrait=second,
                            manager=manager,
                            evidence_root=evidence_root,
                        )
                        evidence["cards"].append(
                            {
                                "render_id": render_id,
                                "resource_id": resource_id,
                                "upstream_commit": source.commit_sha,
                                "runtime_version": spine_version,
                                "first_request": "upstream_bundle_fetched_and_official_worker_rendered",
                                "second_request": "runtime_cache_hit_without_worker_invocation",
                                "worker_invocations": worker_runtimes[spine_version].calls - before_calls[spine_version],
                                "portrait_dimensions": list(first.size),
                                "portrait_alpha_bbox": list(first.getchannel("A").getbbox() or ()),
                                "portrait_rgba_sha256": hashlib.sha256(first.tobytes()).hexdigest(),
                                "white_card": card_evidence,
                            }
                        )
                        self._write_evidence(evidence_root, evidence)
            finally:
                manager.close()

    @staticmethod
    def _render_white_card(
        *,
        render_id: str,
        resource_id: str,
        portrait: Image.Image,
        manager: AssetManager,
        evidence_root: Path,
    ) -> dict[str, Any]:
        card = replace(example_card(), resource_id=resource_id, spine_asset_id=render_id)
        assets = FallbackAssetProvider().resolve_character_assets(card)
        assets.portrait = portrait
        payload = CharacterT2IPayloadBuilder(
            T2IAssetResolver(), identity_resolver=manager.nikke_db
        ).build(card, assets)
        html = Environment().from_string(T2ITemplateLoader().load("character")).render(**payload)
        output = evidence_root / f"{render_id}-character-card.png"

        async def capture() -> None:
            from playwright.async_api import async_playwright

            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                try:
                    page = await browser.new_page(viewport={"width": 1600, "height": 2400})
                    await page.set_content(html, wait_until="load")
                    await page.evaluate("document.fonts.ready")
                    art = page.locator("img.art")
                    await art.wait_for(state="visible")
                    loaded = await art.evaluate("image => image.complete && image.naturalWidth > 0")
                    if not loaded:
                        raise AssertionError("白卡角色立绘没有加载")
                    await page.screenshot(path=str(output), full_page=True)
                finally:
                    await browser.close()

        asyncio.run(capture())
        with Image.open(output) as rendered:
            if rendered.size != (1600, 2400):
                raise AssertionError(f"新版白卡尺寸错误: {rendered.size}")
        return {
            "path": output.name,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "dimensions": [1600, 2400],
        }

    @staticmethod
    def _write_evidence(evidence_root: Path, evidence: dict[str, Any]) -> None:
        (evidence_root / "runtime-portrait-diagnostics.json").write_text(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
