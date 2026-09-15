# SPDX-License-Identifier: GPL-3.0-or-later
"""Union Raid Boss / Monster 本地资产解析器。

为突袭卡片与各类怪物总览提供纯本地、零网络、确定性的资产解析与多级兜底策略。
向下游 T2I (Astra) 与渲染器提供标准化 BossAssetResolution 结果。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("nikke.boss_resolver")


@dataclass(slots=True)
class BossAssetResolution:
    """Boss 资产解析结果契约。"""

    local_path: Path
    relative_uri: str
    is_fallback: bool
    fallback_reason: str | None
    boss_id: str | int | None
    icon_id: str | None
    monster_model_id: str | None
    boss_name: str
    dimensions: tuple[int, int] = (256, 256)


class BossAssetResolver:
    """本地 Boss / Monster 资产解析器，严格只读本地文件系统，不发起任何网络请求。"""

    def __init__(
        self,
        base_dir: str | Path | None = None,
        asset_dir: str | Path | None = None,
        manifest_path: str | Path | None = None,
    ):
        if base_dir is None:
            self.base_dir = Path("data/nikke/blabla-assets")
        else:
            self.base_dir = Path(base_dir)

        if asset_dir is None:
            self.asset_dir = Path("assets")
        else:
            self.asset_dir = Path(asset_dir)

        self.search_roots = [
            self.base_dir,
            self.asset_dir,
            Path("/AstrBot/data/nikke/blabla-assets"),
            Path("/opt/nikke-bot/data/nikke/blabla-assets"),
        ]

        self.custom_manifest_path = Path(manifest_path) if manifest_path else None
        self.fallback_file = self._find_fallback_file()
        self.manifest_records: list[dict[str, Any]] = []
        self.by_boss_id: dict[str, dict[str, Any]] = {}
        self.by_icon_id: dict[str, dict[str, Any]] = {}
        self.by_model_id: dict[str, dict[str, Any]] = {}
        self._load_manifest()

    def _find_fallback_file(self) -> Path:
        for r in self.search_roots:
            for cand in [
                r / "icon" / "default_boss.webp",
                r / "icon" / "default_boss.png",
                r / "default_boss.webp",
                r / "default_boss.png",
            ]:
                if cand.is_file():
                    return cand
        return self.base_dir / "icon" / "default_boss.webp"

    def _load_manifest(self) -> None:
        """加载已验证的 Boss 机器可读 manifest。"""
        manifest_file = None
        if self.custom_manifest_path and self.custom_manifest_path.is_file():
            manifest_file = self.custom_manifest_path
        else:
            candidates = [
                self.base_dir.parent / "blabla-manifests" / "boss_identity_manifest.json",
                Path("data/nikke/blabla-manifests/boss_identity_manifest.json"),
                Path("docs/evidence/blabla_static_assets/boss_identity_manifest.json"),
            ]
            for root in self.search_roots:
                candidates.extend([
                    root / "boss_identity_manifest.json",
                    root / "manifests" / "boss_identity_manifest.json",
                ])
            for cand in candidates:
                if cand.is_file():
                    manifest_file = cand
                    break

        if not manifest_file:
            logger.debug("Boss identity manifest not found; operating in purely filename-based mode.")
            return

        try:
            raw_data = json.loads(manifest_file.read_text(encoding="utf-8"))
            records = raw_data.get("records", []) if isinstance(raw_data, dict) else raw_data
            self.manifest_records = records
            for rec in records:
                bid = str(rec.get("boss_id") or "").strip()
                if bid:
                    self.by_boss_id[bid] = rec
                for alt_bid in rec.get("all_boss_ids", []):
                    str_alt = str(alt_bid).strip()
                    if str_alt:
                        self.by_boss_id[str_alt] = rec

                iid = str(rec.get("icon_id") or "").strip()
                if iid:
                    self.by_icon_id[iid] = rec

                mid = str(rec.get("monster_model_id") or "").strip()
                if mid:
                    self.by_model_id[mid] = rec
            logger.debug("Loaded %d boss identity records from %s", len(records), manifest_file)
        except Exception as e:
            logger.warning("Failed to load boss identity manifest %s: %s", manifest_file, e)

    def _locate_file(self, filename: str) -> Path | None:
        for root in self.search_roots:
            for sub in [
                root / "boss" / filename,
                root / "icon" / "monster_full" / filename,
                root / "icon" / filename,
                root / filename,
            ]:
                if sub.is_file():
                    return sub
        return None

    def resolve(
        self,
        boss_id: int | str | None = None,
        icon_id: str | None = None,
        monster_model_id: str | None = None,
        boss_name: str | None = None,
    ) -> BossAssetResolution:
        """解析指定 Boss 的本地立绘/图标。严格零网络。"""
        raw_bid = str(boss_id).strip() if boss_id is not None else None
        raw_iid = str(icon_id).strip() if icon_id is not None else None
        raw_mid = str(monster_model_id).strip() if monster_model_id is not None else None

        # 1. 检测入参冲突: 若同时提供 boss_id 与 icon_id，且在 manifest 中存在已知映射但不一致
        if raw_bid and raw_iid and raw_bid in self.by_boss_id:
            expected_icon = self.by_boss_id[raw_bid].get("icon_id")
            if expected_icon and expected_icon != raw_iid:
                logger.warning("Conflicting boss_id %s (expected %s) and icon_id %s", raw_bid, expected_icon, raw_iid)
                resolved_name = (boss_name or "").strip() or f"Boss {raw_bid}"
                return BossAssetResolution(
                    local_path=self.fallback_file,
                    relative_uri="/icon/default_boss.webp",
                    is_fallback=True,
                    fallback_reason="CONFLICTING_IDENTIFIERS",
                    boss_id=boss_id,
                    icon_id=icon_id,
                    monster_model_id=monster_model_id,
                    boss_name=resolved_name,
                    dimensions=(256, 256),
                )

        # 2. 从 manifest 索引中补全已知身份
        matched_record = None
        if raw_bid and raw_bid in self.by_boss_id:
            matched_record = self.by_boss_id[raw_bid]
        elif raw_iid and raw_iid in self.by_icon_id:
            matched_record = self.by_icon_id[raw_iid]
        elif raw_mid and raw_mid in self.by_model_id:
            matched_record = self.by_model_id[raw_mid]

        resolved_name = (boss_name or "").strip()
        if matched_record:
            if not raw_iid:
                raw_iid = matched_record.get("icon_id")
            if not raw_mid:
                raw_mid = matched_record.get("monster_model_id")
            if not raw_bid:
                raw_bid = str(matched_record.get("boss_id"))
            if not resolved_name:
                resolved_name = matched_record.get("display_name", "")

        if not resolved_name:
            resolved_name = f"Boss {raw_bid or raw_iid or '?'}"

        # 3. 构建本地候选文件名
        candidates: list[tuple[str, str]] = []
        if raw_iid:
            candidates.append((f"full_{raw_iid}.webp", f"/icon/monster_full/full_{raw_iid}.webp"))
            candidates.append((f"full_{raw_iid}.png", f"/icon/monster_full/full_{raw_iid}.png"))
            candidates.append((f"{raw_iid}.webp", f"/icon/monster_full/{raw_iid}.webp"))
            candidates.append((f"{raw_iid}.png", f"/icon/monster_full/{raw_iid}.png"))

        if raw_mid:
            candidates.append((f"full_{raw_mid}.webp", f"/icon/monster_full/full_{raw_mid}.webp"))
            candidates.append((f"full_{raw_mid}.png", f"/icon/monster_full/full_{raw_mid}.png"))
            candidates.append((f"{raw_mid}.webp", f"/icon/monster_full/{raw_mid}.webp"))
            candidates.append((f"{raw_mid}.png", f"/icon/monster_full/{raw_mid}.png"))

        if raw_bid:
            candidates.append((f"full_{raw_bid}.webp", f"/icon/monster_full/full_{raw_bid}.webp"))
            candidates.append((f"full_{raw_bid}.png", f"/icon/monster_full/full_{raw_bid}.png"))

        # 4. 尝试命中本地镜像文件
        for fn, rel_uri in candidates:
            found = self._locate_file(fn)
            if found:
                dims = (1024, 1024)
                if matched_record and matched_record.get("width") and matched_record.get("height"):
                    dims = (int(matched_record["width"]), int(matched_record["height"]))
                return BossAssetResolution(
                    local_path=found,
                    relative_uri=rel_uri,
                    is_fallback=False,
                    fallback_reason=None,
                    boss_id=raw_bid or boss_id,
                    icon_id=raw_iid or icon_id,
                    monster_model_id=raw_mid or monster_model_id,
                    boss_name=resolved_name,
                    dimensions=dims,
                )

        # 5. 未命中本地镜像，降级处理
        if matched_record is not None:
            # 真实 metadata 已识别该 Boss，但本地文件缺失
            fallback_reason = "BOSS_IMAGE_MISSING"
        elif raw_bid or raw_iid or raw_mid:
            fallback_reason = "UNKNOWN_BOSS"
        else:
            fallback_reason = "NO_BOSS_IDENTIFIER"

        return BossAssetResolution(
            local_path=self.fallback_file,
            relative_uri="/icon/default_boss.webp",
            is_fallback=True,
            fallback_reason=fallback_reason,
            boss_id=raw_bid or boss_id,
            icon_id=raw_iid or icon_id,
            monster_model_id=raw_mid or monster_model_id,
            boss_name=resolved_name,
            dimensions=(256, 256),
        )
