# SPDX-License-Identifier: GPL-3.0-or-later
"""Spine 静态 manifest 的读取、身份校验与安全文件解析。"""

from __future__ import annotations

import json
import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from PIL import Image

from .image_codec import AssetImageCodec

logger = logging.getLogger("nikke.asset_manager")


class SpineManifestStore:
    def __init__(
        self,
        asset_dir: str | Path,
        cache_dir: str | Path,
        *,
        manifest_path: str | Path | None = None,
        rendered_dir: str | Path | None = None,
    ) -> None:
        self.asset_dir = Path(asset_dir)
        self.cache_dir = Path(cache_dir)
        self.manifest_path = Path(manifest_path) if manifest_path is not None else None
        self.rendered_dir = Path(rendered_dir) if rendered_dir is not None else None
        self.manifest: dict[str, Any] = {}
        self.entries: dict[str, dict[str, Any]] = {}
        self.declared_ids: set[str] = set()
        self.source: Path | None = None
        self.schema: int | None = None
        self.refresh()

    def refresh(self) -> None:
        candidates: list[Path] = []
        if self.manifest_path is not None:
            candidates.append(self.manifest_path)
        candidates.extend(
            [
                self.asset_dir / "data" / "spine_manifest.json",
                self.asset_dir / "spine_manifest.json",
                self.cache_dir / "spine-manifest.json",
                self.cache_dir / "spine_manifest.json",
            ]
        )
        self.manifest = {}
        self.entries = {}
        self.declared_ids = set()
        self.source = None
        self.schema = None
        for candidate in candidates:
            try:
                if not candidate.is_file():
                    continue
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            schema = payload.get("schema_version")
            entries = payload.get("assets", payload.get("characters")) if schema == 2 else payload.get("characters") if schema == 1 else None
            if not isinstance(entries, dict):
                continue
            declared_ids = {
                str(key).strip().lower()
                for key in entries
                if re.fullmatch(r"c[0-9]+(?:_[0-9]+)?", str(key).strip().lower())
            }
            valid_entries = {
                str(key).strip().lower(): value
                for key, value in entries.items()
                if re.fullmatch(r"c[0-9]+(?:_[0-9]+)?(?:@[a-z0-9][a-z0-9_-]*)?", str(key).strip().lower())
                and isinstance(value, dict)
            }
            if schema == 2 and "characters" in payload:
                identities: dict[tuple[str, str], dict[str, Any]] = {}
                for key, entry in entries.items():
                    if not isinstance(entry, dict):
                        continue
                    identity = (str(entry.get("character_resource_id")), str(entry.get("costume_id")))
                    if identity in identities:
                        entry["_conflict"] = identities[identity]["_conflict"] = True
                    identities[identity] = entry
                    if entry.get("spine_asset_id", key) != key:
                        entry["_conflict"] = True
            self.manifest = payload
            self.entries = valid_entries
            self.declared_ids = declared_ids
            self.source = candidate
            self.schema = schema if isinstance(schema, int) else None
            return

    def is_declared(self, char_id: str) -> bool:
        return str(char_id).strip().lower() in self.declared_ids

    def resolve_png(self, char_id: str) -> tuple[Path | None, bool]:
        char_id = str(char_id).strip().lower()
        if char_id not in self.declared_ids:
            return None, False
        entry = self.entries.get(char_id)
        if entry is None:
            return None, True
        if entry.get("_conflict"):
            logger.warning("SPINE_ASSET_CONFLICT_REJECTED: %s", char_id)
            return None, True
        if self.schema == 2 and "characters" in self.manifest:
            relative = entry.get("local_relpath", f"assets/spine-rendered/{char_id}.png")
            try:
                target = (self.asset_dir.parent / relative).resolve()
                if not target.is_relative_to(self.asset_dir.resolve()):
                    return None, True
                if not target.is_file():
                    logger.warning("SPINE_ASSET_FILE_MISSING: %s", char_id)
                    return None, True
                return target, True
            except (OSError, RuntimeError, ValueError, TypeError):
                return None, True
        relative = entry.get("rendered_png") if self.schema == 2 else entry.get("png_file")
        if not isinstance(relative, str) or not relative.strip():
            return None, True
        base = self.rendered_dir
        if base is None:
            base = self.source.parent / "spine-rendered" if self.source else self.asset_dir
        try:
            base_resolved = base.expanduser().resolve()
            target = (base_resolved / relative).resolve()
            if not target.is_relative_to(base_resolved):
                return None, True
            if not target.is_file():
                logger.warning("SPINE_ASSET_FILE_MISSING: %s", char_id)
                return None, True
            return target, True
        except (OSError, RuntimeError, ValueError, TypeError):
            return None, True

    def load_png(self, char_id: str) -> Image.Image | None:
        path, declared = self.resolve_png(char_id)
        if not declared or path is None:
            return None
        entry = self.entries.get(str(char_id).strip().lower())
        if entry is None or not isinstance(entry.get("sha256"), str):
            logger.warning("SPINE_MANIFEST_MISSING_HASH: %s", char_id)
            return None
        expected = entry["sha256"].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            logger.warning("SPINE_HASH_MISMATCH: %s", char_id)
            return None
        try:
            if path.stat().st_size > AssetImageCodec.MAX_BYTES:
                logger.warning("SPINE_ASSET_CORRUPT: oversize file %s", char_id)
                return None
            digest_builder = hashlib.sha256()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest_builder.update(chunk)
            digest = digest_builder.hexdigest()
        except OSError:
            logger.warning("SPINE_ASSET_FILE_MISSING: %s", char_id)
            return None
        if digest != expected:
            logger.warning("SPINE_HASH_MISMATCH: %s", char_id)
            return None
        try:
            with path.open("rb") as source:
                valid_png = source.read(8) == b"\x89PNG\r\n\x1a\n"
        except OSError:
            valid_png = False
        if not valid_png:
            logger.warning("SPINE_ASSET_CORRUPT: %s", char_id)
            return None
        image = AssetImageCodec.load_file(path, strict_png=True)
        if image is not None and any(
            entry.get(key) is not None and entry[key] != value
            for key, value in (("width", image.width), ("height", image.height))
        ):
            logger.warning("SPINE_ASSET_CORRUPT: dimensions")
            return None
        if image is None:
            logger.warning("STATIC_SPINE_ASSET_INVALID: %s", char_id)
        return image
