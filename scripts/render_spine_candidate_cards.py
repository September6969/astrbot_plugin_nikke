#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""使用当前 CharacterT2IPayloadBuilder 与 character.html 生成 dry-run 白卡。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jinja2 import Environment
from PIL import Image
from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.features.character.face_anchor import framing, metadata
from astrbot_plugin_nikke.features.character.models import CostumeSelection
from astrbot_plugin_nikke.features.character.weapon_bases import card_fields
from astrbot_plugin_nikke.integrations.spine.local_resolver import LocalSpineBundleResolver
from astrbot_plugin_nikke.tests.test_character_replica import example_card
from astrbot_plugin_nikke.ui.payloads.character import CharacterT2IPayloadBuilder
from astrbot_plugin_nikke.ui.t2i_assets import T2IAssetResolver
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader
from scripts.phase3_output_guard import require_new_external_path
from scripts.spine_batch_review import create_contact_sheet


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def _load_character_rows() -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads((ROOT / "assets" / "character_master.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("无法读取 canonical character master") from exc
    rows = payload.get("characters") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("character master 结构无效")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        resource_id = row.get("resource_id")
        render_id = row.get("spine_asset_id")
        if isinstance(resource_id, int) and isinstance(render_id, str):
            if render_id in result:
                raise ValueError(f"canonical render identity 重复: {render_id}")
            result[render_id] = row
    return result


async def render_candidate_cards(
    batch: dict[str, Any],
    fetch: dict[str, Any],
    *,
    bundle_root: Path,
    portrait_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    output_root = require_new_external_path(output_dir, ROOT, label="候选白卡 evidence")
    if (
        fetch.get("source_repository") != "https://github.com/Nikke-db/Nikke-db.github.io"
        or fetch.get("source_commit") != fetch.get("upstream_snapshot_sha")
        or fetch.get("batch_id") != batch.get("batch_id")
        or fetch.get("generated_from_head") != batch.get("generated_from_head")
    ):
        raise ValueError("sparse fetch provenance 没有绑定固定 snapshot")
    batch_rows = batch.get("candidates")
    fetched_ids = fetch.get("render_ids")
    if not isinstance(batch_rows, list) or not isinstance(fetched_ids, list):
        raise ValueError("batch 或 fetch provenance 结构无效")
    bundle_meta = {
        row.get("render_id"): row
        for row in fetch.get("bundles", [])
        if isinstance(row, dict) and isinstance(row.get("render_id"), str)
    }
    fetched_files = {
        row.get("path"): row
        for row in fetch.get("files", [])
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    }
    bundle_resolver = LocalSpineBundleResolver(bundle_root)
    character_rows = _load_character_rows()
    output_root.parent.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=False)
    cards_dir = output_root / "cards"
    cards_dir.mkdir()
    manager = AssetManager(
        output_root / "local-cache",
        ROOT / "assets",
        remote=False,
        spine_manifest_path=ROOT / "assets" / "spine_manifest.json",
        spine_rendered_dir=ROOT / "assets" / "spine-rendered",
    )
    template = Environment().from_string(T2ITemplateLoader().load("character"))
    diagnostics: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page(
                    viewport={"width": 1600, "height": 2400}, device_scale_factor=1
                )
                for candidate in batch_rows:
                    if not isinstance(candidate, dict):
                        raise ValueError("batch candidate 结构无效")
                    render_id = candidate.get("render_id")
                    resource_id = candidate.get("resource_id")
                    if (
                        not isinstance(render_id, str)
                        or not re.fullmatch(r"c[0-9]+", render_id)
                        or render_id not in fetched_ids
                        or not isinstance(resource_id, str)
                        or not resource_id.isdigit()
                    ):
                        raise ValueError("白卡候选不是已 sparse-fetch 的 canonical default")
                    row = character_rows.get(render_id)
                    source_bundle = bundle_meta.get(render_id)
                    if (
                        row is None
                        or str(row.get("resource_id")) != resource_id
                        or row.get("spine_asset_id") != render_id
                        or source_bundle is None
                        or source_bundle.get("resource_id") != resource_id
                    ):
                        raise ValueError(f"canonical character master 与候选身份不一致: {render_id}")
                    resolved_bundle = bundle_resolver.resolve(render_id)
                    expected_bundle_paths = [
                        source_bundle.get("skeleton_path"),
                        source_bundle.get("atlas_path"),
                        *source_bundle.get("texture_paths", []),
                    ]
                    if (
                        resolved_bundle.runtime_version != source_bundle.get("runtime_version")
                        or resolved_bundle.skel_path.relative_to(bundle_root.resolve()).as_posix() != source_bundle.get("skeleton_path")
                        or resolved_bundle.atlas_path.relative_to(bundle_root.resolve()).as_posix() != source_bundle.get("atlas_path")
                        or [path.relative_to(bundle_root.resolve()).as_posix() for path in resolved_bundle.texture_paths]
                        != sorted(source_bundle.get("texture_paths", []))
                    ):
                        raise ValueError(f"固定 bundle 与 fetch provenance 不一致: {render_id}")
                    for relative in expected_bundle_paths:
                        if not isinstance(relative, str) or relative not in fetched_files:
                            raise ValueError(f"fetch provenance 缺少 bundle 文件: {render_id}")
                        source_root = bundle_root.resolve(strict=True)
                        source_file = (source_root / Path(*Path(relative).parts)).resolve(strict=True)
                        if not source_file.is_relative_to(source_root):
                            raise ValueError(f"fetch provenance bundle 路径越界: {render_id}")
                        file_row = fetched_files[relative]
                        if _sha256(source_file) != file_row.get("sha256") or source_file.stat().st_size != file_row.get("size"):
                            raise ValueError(f"固定 bundle 文件 hash/size 不匹配: {render_id}")
                        if _git_blob_sha(source_file) != file_row.get("git_blob_sha"):
                            raise ValueError(f"固定 bundle 文件 Git blob SHA 不匹配: {render_id}")
                    portrait_path = (portrait_root / f"{render_id}.png").resolve(strict=True)
                    if not portrait_path.is_relative_to(portrait_root.resolve(strict=True)):
                        raise ValueError(f"候选 portrait 路径越界: {render_id}")
                    with Image.open(portrait_path) as opened:
                        if opened.format != "PNG" or opened.mode != "RGBA":
                            raise ValueError(f"候选 portrait 必须是 RGBA PNG: {render_id}")
                        opened.load()
                        portrait = opened.copy()

                    card = replace(
                        example_card(),
                        name_cn=str(row.get("name_cn") or render_id),
                        name_en=str(row.get("name_en") or render_id),
                        resource_id=resource_id,
                        costume_id=0,
                        spine_asset_id=render_id,
                        costume_selection=CostumeSelection(0, "phase3a-default-preview", "default"),
                        corporation=row.get("corporation"),
                        element=row.get("element"),
                        weapon=row.get("weapon"),
                        burst=row.get("burst"),
                        **card_fields(int(resource_id)),
                    )
                    assets = await asyncio.to_thread(manager.resolve_character_assets, card)
                    assets.portrait = portrait
                    metadata.cache_clear()
                    frame = framing(
                        card,
                        portrait,
                        body_centering=False,
                        summary_count=4,
                        identity_resolver=manager.nikke_db,
                    )
                    payload = CharacterT2IPayloadBuilder(
                        T2IAssetResolver(), identity_resolver=manager.nikke_db
                    ).build(card, assets)
                    payload["art_style"] = frame["style"]
                    html = template.render(**payload)
                    if any(token in html for token in ("http://", "https://", "file://", "fetch(", "XMLHttpRequest")):
                        raise ValueError(f"候选白卡 HTML 含外部网络资源: {render_id}")
                    await page.set_content(html, wait_until="load")
                    await page.evaluate("document.fonts.ready")
                    target = cards_dir / f"{render_id}.png"
                    if target.exists():
                        raise ValueError(f"白卡 evidence 已存在；拒绝覆盖: {render_id}")
                    await page.screenshot(path=str(target), full_page=True)
                    with Image.open(target) as rendered:
                        if rendered.format != "PNG" or rendered.size != (1600, 2400):
                            raise ValueError(f"新版白卡尺寸不是 1600×2400: {render_id}")
                    card_record = {
                        "render_id": render_id,
                        "resource_id": resource_id,
                        "portrait_source": f"{batch.get('batch_id')}/bundle/l2d/{render_id}",
                        "manifest_source": "not-promoted; Phase 3A dry-run only",
                        "runtime_version": source_bundle.get("runtime_version"),
                        "portrait_sha256": _sha256(portrait_path),
                        "portrait_dimensions": list(portrait.size),
                        "face_anchor_state": "NOT_AUTHORED",
                        "core_axis_state": "UNASSESSED",
                        "framing_source": frame.get("source"),
                        "template": "templates/t2i/character.html",
                        "white_card": {
                            "path": f"cards/{render_id}.png",
                            "sha256": _sha256(target),
                            "dimensions": [1600, 2400],
                        },
                        "renderer": "CharacterT2IPayloadBuilder + current character.html + local headless Chromium",
                    }
                    diagnostics.append(card_record)
                    cards.append({"render_id": render_id, "path": target})
            finally:
                await browser.close()
    finally:
        manager.close()

    contact = create_contact_sheet(cards, output_root / "white-card-contact-sheet.png")
    evidence = {
        "schema_version": 1,
        "batch_id": batch.get("batch_id"),
        "generated_from_head": batch.get("generated_from_head"),
        "source_commit": fetch.get("source_commit"),
        "white_card_path": "white-card-contact-sheet.png",
        "white_card_sha256": contact["sha256"],
        "cards": diagnostics,
    }
    (output_root / "white-card-diagnostic.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return evidence


async def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--fetch-provenance", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--portrait-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        batch = json.loads(args.batch.read_text(encoding="utf-8"))
        fetch = json.loads(args.fetch_provenance.read_text(encoding="utf-8"))
        result = await render_candidate_cards(
            batch, fetch,
            bundle_root=args.bundle_root,
            portrait_root=args.portrait_root,
            output_dir=args.output_dir,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"新版白卡预览失败: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"card_count": len(result["cards"]), "contact_sheet_sha256": result["white_card_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
