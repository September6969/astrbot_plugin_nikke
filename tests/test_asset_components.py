from __future__ import annotations

import hashlib
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from PIL import Image

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.core.assets.downloader import AssetDownloader
from astrbot_plugin_nikke.core.assets.fallback_provider import FallbackAssetProvider
from astrbot_plugin_nikke.core.assets.image_cache import AssetImageCache
from astrbot_plugin_nikke.core.assets.spine_manifest import SpineManifestStore
from astrbot_plugin_nikke.features.character.models import CharacterCardAssets
from astrbot_plugin_nikke.ui.renderers.campaign import CampaignHistoryRenderer
from astrbot_plugin_nikke.ui.renderers.character import CharacterCardRenderer


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def response_context(response):
    yield response


def test_asset_manager_remains_a_small_composition_facade() -> None:
    lines = (ROOT / "core" / "asset_manager.py").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 300


def test_image_cache_rejects_traversal_and_round_trips_valid_image() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        cache = AssetImageCache(root / "cache", root / "assets")
        source = Image.new("RGBA", (9, 7), "purple")
        assert cache.save("icons/sample.png", source)
        loaded = cache.load("icons/sample.png")
        assert loaded is not None and loaded.size == (9, 7)
        assert cache.load("../outside.png") is None
        assert not cache.save("../outside.png", source)
        assert not (root / "outside.png").exists()
        corrupt = root / "cache" / "icons" / "corrupt.png"
        corrupt.parent.mkdir(parents=True, exist_ok=True)
        corrupt.write_bytes(b"not-image")
        assert cache.load("icons/corrupt.png") is None


def test_downloader_retries_transient_failure_and_caches_success() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        cache = AssetImageCache(root / "cache", root / "assets")
        downloader = AssetDownloader(cache, remote_enabled=True)
        payload_file = root / "source.png"
        Image.new("RGBA", (11, 13), "teal").save(payload_file, format="PNG")
        payload = payload_file.read_bytes()
        response = httpx.Response(
            200,
            content=payload,
            request=httpx.Request("GET", "https://cdn.example/second.png"),
        )
        calls = []

        def stream_side_effect(*args, **_kwargs):
            calls.append(args[1])
            if stream.call_count == 1:
                raise httpx.ConnectError("offline")
            return response_context(response)

        stream = Mock(side_effect=stream_side_effect)
        downloader.stream = stream

        image = downloader.load(
            "icons/retry.png",
            ["https://cdn.example/second.png"],
        )

        assert image is not None and image.size == (11, 13)
        assert stream.call_count == 2
        assert calls == ["https://cdn.example/second.png"] * 2
        assert cache.load("icons/retry.png") is not None


def test_downloader_falls_through_to_next_candidate_after_retry_budget() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        cache = AssetImageCache(root / "cache", root / "assets")
        downloader = AssetDownloader(cache, remote_enabled=True)
        payload_file = root / "source.png"
        Image.new("RGBA", (8, 12), "teal").save(payload_file, format="PNG")
        payload = payload_file.read_bytes()
        response = httpx.Response(
            200,
            content=payload,
            request=httpx.Request("GET", "https://cdn.example/second.png"),
        )
        calls = []

        def stream_side_effect(_method, url, **_kwargs):
            calls.append(url)
            if url.endswith("first.png"):
                raise httpx.ConnectError("offline")
            return response_context(response)

        downloader.stream = Mock(side_effect=stream_side_effect)
        image = downloader.load(
            "icons/fallback.png",
            ["https://cdn.example/first.png", "https://cdn.example/second.png"],
        )
        assert image is not None and image.size == (8, 12)
        assert calls == [
            "https://cdn.example/first.png",
            "https://cdn.example/first.png",
            "https://cdn.example/second.png",
        ]


def test_downloader_rejects_non_https_and_corrupt_images_without_caching() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        cache = AssetImageCache(root / "cache", root / "assets")
        downloader = AssetDownloader(cache, remote_enabled=True)
        stream = Mock()
        downloader.stream = stream

        assert downloader.load("icons/bad.png", ["http://cdn.example/bad.png"]) is None
        assert stream.call_count == 0

        response = httpx.Response(
            200,
            content=b"<html>not an image</html>",
            request=httpx.Request("GET", "https://cdn.example/bad.png"),
        )
        stream.side_effect = lambda *_args, **_kwargs: response_context(response)
        assert downloader.load("icons/bad.png", ["https://cdn.example/bad.png"]) is None
        assert cache.load("icons/bad.png") is None


def test_spine_manifest_store_fails_closed_on_hash_mismatch() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        asset_dir = root / "assets"
        rendered = asset_dir / "spine-rendered"
        rendered.mkdir(parents=True)
        image_path = rendered / "c010.png"
        Image.new("RGBA", (10, 20), "orange").save(image_path)
        manifest = asset_dir / "spine_manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "characters": {
                        "c010": {
                            "png_file": "c010.png",
                            "sha256": "0" * 64,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        store = SpineManifestStore(asset_dir, root / "cache")

        assert store.is_declared("c010")
        assert store.load_png("c010") is None
        assert hashlib.sha256(image_path.read_bytes()).hexdigest() != "0" * 64


def test_fallback_provider_is_non_owning_and_returns_complete_card_assets() -> None:
    class Card:
        resource_id = "c010"
        name_code = "c010"
        costume_id = None
        equipment = {}
        favorite_item = None
        cube = None
        element = "fire"
        corporation = "tetra"
        weapon = "ar"
        burst = "step1"

    assets = FallbackAssetProvider()
    result = assets.resolve_character_assets(Card())
    assert isinstance(result, CharacterCardAssets)
    assert result.portrait.size[0] > 0
    assert set(result.equipment) == {"head", "torso", "arm", "leg"}


def test_character_renderer_does_not_own_asset_resolution() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        fonts = ROOT / "fonts"
        character = CharacterCardRenderer(root / "character", fonts)
        assert not hasattr(character, "assets")
        source = (ROOT / "ui" / "renderers" / "character.py").read_text(encoding="utf-8")
        for forbidden in (
            "resolve_character_assets",
            "get_character_portrait",
            "get_equipment_icon",
            "get_favorite_item_icon",
            "get_cube_icon",
        ):
            assert forbidden not in source


def test_character_renderer_requires_explicitly_prepared_assets() -> None:
    import inspect

    assert "card_assets" in inspect.signature(CharacterCardRenderer.render_character).parameters
    assert inspect.signature(CharacterCardRenderer.render_character).parameters["card_assets"].default is inspect.Parameter.empty


def test_prefetch_lifecycle_close_is_idempotent_and_prevents_new_tasks() -> None:
    with tempfile.TemporaryDirectory() as directory:
        manager = AssetManager(Path(directory) / "cache", ROOT / "assets")
        executor = manager._executor
        shutdown = Mock(wraps=executor.shutdown)
        executor.shutdown = shutdown
        manager.close()
        manager.close()
        assert shutdown.call_count == 1
        assert manager._submit_prefetch(lambda: None) is None


def test_spine_cache_identity_covers_costume_runtime_and_animation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        manager = AssetManager(Path(directory) / "cache", ROOT / "assets")
        try:
            keys = {
                manager._spine_cache_key("c010", None, "4.0", "idle"),
                manager._spine_cache_key("c010", "10005", "4.0", "idle"),
                manager._spine_cache_key("c010", "10005", "4.1", "idle"),
                manager._spine_cache_key("c010", "10005", "4.1", "attack"),
            }
            assert len(keys) == 4
        finally:
            manager.close()
