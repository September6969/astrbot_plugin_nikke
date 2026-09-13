# SPDX-License-Identifier: GPL-3.0-or-later
"""NIKKE 阵容小头像（Compact Portrait）本地解析器。

针对 128x128 紧凑圆形/方形小头像 (si 家族) 提供纯本地、零网络、确定性的解析与多级兜底策略。
向下游 T2I (Astra) 与渲染器提供标准化 LineupPortraitResolution 结果。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("nikke.lineup_resolver")


@dataclass(slots=True)
class LineupPortraitResolution:
    """阵容小头像解析结果契约。"""

    local_path: Path
    relative_uri: str
    is_fallback: bool
    fallback_reason: str | None
    character_id: int | None
    resource_id: int | None
    costume_index: int
    character_name: str
    dimensions: tuple[int, int] = (128, 128)


class LineupPortraitResolver:
    """本地紧凑头像解析器，严格只读本地文件系统，不发起任何网络请求。"""

    def __init__(
        self,
        base_dir: str | Path | None = None,
        asset_dir: str | Path | None = None,
    ):
        if base_dir is None:
            self.base_dir = Path("data/nikke/blabla-assets")
        else:
            self.base_dir = Path(base_dir)

        if asset_dir is None:
            self.asset_dir = Path("assets")
        else:
            self.asset_dir = Path(asset_dir)

        # 候选查找根目录（优先 local mirror，再检查 assets）
        self.search_roots = [
            self.base_dir,
            self.asset_dir,
            Path("/AstrBot/data/nikke/blabla-assets"),
            Path("/opt/nikke-bot/data/nikke/blabla-assets"),
        ]

        # 默认占位图
        self.fallback_file = self._find_fallback_file()

        # 内存索引映射
        self._tid_to_char: dict[int, dict[str, Any]] = {}
        self._res_to_char: dict[int, dict[str, Any]] = {}
        self._name_to_char: dict[str, dict[str, Any]] = {}
        self._costume_map: dict[str, dict[str, Any]] = {}  # costume_id -> {resource_id, costume_index, name}
        self._avatar_map: dict[int, dict[str, Any]] = {}   # avatar_id -> {resource_id, costume_index}

        self._load_indexes()

    def _find_fallback_file(self) -> Path:
        for r in self.search_roots:
            p = r / "character" / "si" / "default_avatar.webp"
            if p.is_file():
                return p
            p_png = r / "character" / "si" / "default_avatar.png"
            if p_png.is_file():
                return p_png
        # 若均不存在，返回相对缺省路径
        return self.base_dir / "character" / "si" / "default_avatar.png"

    def _load_indexes(self) -> None:
        """从本地快照或 assets 加载权威清单索引。"""
        # 1. 尝试加载 nikke_list_zh-TW_v2 快照或 assets/character_master.json
        manifest_paths = [
            self.base_dir.parent / "blabla-manifests" / "character_zh-tw_nikke_list_zh-TW_v2.json",
            Path("docs/evidence/blabla_static_assets/blabla_manifest_snapshots/character_zh-tw_nikke_list_zh-TW_v2.json"),
            self.asset_dir / "character_master.json",
        ]

        for mp in manifest_paths:
            if mp.is_file():
                try:
                    data = json.loads(mp.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        # 官方 nikke_list 结构
                        for c in data:
                            res_id = c.get("resource_id")
                            c_id = c.get("id")
                            # name_localkey: {'name': '...'} or direct 'name'
                            name = ""
                            nlk = c.get("name_localkey")
                            if isinstance(nlk, dict):
                                name = nlk.get("name", "")
                            if not name:
                                name = c.get("name", "Unknown")

                            if res_id is not None:
                                entry = {
                                    "resource_id": int(res_id),
                                    "character_id": int(c_id) if c_id else None,
                                    "name": name,
                                }
                                self._res_to_char[int(res_id)] = entry
                                if c_id:
                                    self._tid_to_char[int(c_id)] = entry
                                if name and name != "Unknown":
                                    self._name_to_char[name.lower()] = entry
                                # 索引皮肤
                                for costume in c.get("costumes", []):
                                    cid = str(costume.get("id", ""))
                                    cidx = costume.get("costume_index", 0)
                                    cname = ""
                                    c_nlk = costume.get("name_localkey")
                                    if isinstance(c_nlk, dict):
                                        cname = c_nlk.get("name", "")
                                    if not cname:
                                        cname = costume.get("name", "Costume")
                                    if cid:
                                        self._costume_map[cid] = {
                                            "resource_id": int(res_id),
                                            "costume_index": int(cidx),
                                            "costume_name": cname,
                                        }
                        break
                    elif isinstance(data, dict) and "characters" in data:
                        # 本地 character_master.json 结构
                        for c in data["characters"]:
                            res_id = c.get("resource_id")
                            c_id = c.get("id")
                            name = c.get("name_zh_tw") or c.get("name_en") or "Unknown"
                            if res_id is not None:
                                entry = {
                                    "resource_id": int(res_id),
                                    "character_id": int(c_id) if c_id else None,
                                    "name": name,
                                }
                                self._res_to_char[int(res_id)] = entry
                                if c_id:
                                    self._tid_to_char[int(c_id)] = entry
                                self._name_to_char[name.lower()] = entry
                        break
                except Exception as e:
                    logger.warning("Failed to load character manifest from %s: %s", mp, e)

        # 2. 尝试加载 character_avatar_map
        avatar_paths = [
            self.base_dir.parent / "blabla-manifests" / "character_character_avatar_map.json",
            Path("docs/evidence/blabla_static_assets/blabla_manifest_snapshots/character_character_avatar_map.json"),
        ]
        for ap in avatar_paths:
            if ap.is_file():
                try:
                    data = json.loads(ap.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        for a in data:
                            aid = a.get("id")
                            if aid:
                                self._avatar_map[int(aid)] = {
                                    "resource_id": a.get("resource_id"),
                                    "costume_index": a.get("costume_index", 0),
                                }
                        break
                except Exception as e:
                    logger.warning("Failed to load avatar map: %s", e)

        # 3. 补充 assets/costumes.json
        costumes_json = self.asset_dir / "costumes.json"
        if costumes_json.is_file():
            try:
                c_data = json.loads(costumes_json.read_text(encoding="utf-8"))
                for row in c_data.get("entries", []):
                    cid = str(row.get("costume_id", ""))
                    if cid and cid not in self._costume_map:
                        res_id = row.get("character_resource_id")
                        spine_id = row.get("spine_asset_id", "")
                        # e.g. c082_01 -> costume_index 1
                        cidx = 1
                        if "_" in spine_id:
                            try:
                                cidx = int(spine_id.split("_")[1])
                            except ValueError:
                                pass
                        if res_id:
                            self._costume_map[cid] = {
                                "resource_id": int(res_id),
                                "costume_index": cidx,
                                "costume_name": row.get("costume_name", ""),
                            }
            except Exception as e:
                logger.warning("Failed to load fallback costumes.json: %s", e)

    def _locate_file(self, filename: str) -> Path | None:
        """在所有 search_roots 下查找文件。"""
        for root in self.search_roots:
            p = root / "character" / "si" / filename
            if p.is_file():
                return p
            # 直接在 si 目录或者根目录下查找
            p2 = root / filename
            if p2.is_file():
                return p2
        return None

    def resolve(
        self,
        tid: int | str | None = None,
        costume_id: int | str | None = None,
        character_id: int | str | None = None,
        avatar_id: int | str | None = None,
    ) -> LineupPortraitResolution:
        """按优先级解析阵容小头像，保证零崩溃与清晰 Fallback。"""
        res_id: int | None = None
        char_id_val: int | None = None
        costume_idx = 0
        char_name = "Unknown"
        is_fallback = False
        fallback_reason: str | None = None

        # 1. 优先通过 avatar_id 直接解析（BlaBla 用户资料与头像场景）
        if avatar_id is not None:
            try:
                aid_int = int(avatar_id)
                if aid_int in self._avatar_map:
                    av = self._avatar_map[aid_int]
                    res_id = av["resource_id"]
                    costume_idx = av["costume_index"]
            except ValueError:
                pass

        # 2. 通过 costume_id 解析
        if costume_id is not None:
            c_str = str(costume_id).strip()
            if c_str in self._costume_map:
                c_info = self._costume_map[c_str]
                if res_id is None:
                    res_id = c_info["resource_id"]
                costume_idx = c_info["costume_index"]
            else:
                # 记录皮肤未找到，后续将尝试降级回原皮
                fallback_reason = f"COSTUME_ID_{c_str}_NOT_FOUND"

        # 3. 通过 character_id / tid 解析角色主体
        lookup_id = character_id if character_id is not None else tid
        if lookup_id is not None and res_id is None:
            try:
                id_int = int(lookup_id)
                char_id_val = id_int
                # 检查是否直接是 tid
                if id_int in self._tid_to_char:
                    entry = self._tid_to_char[id_int]
                    res_id = entry["resource_id"]
                    char_name = entry["name"]
                elif id_int in self._res_to_char:
                    # 传入的直接就是 resource_id
                    entry = self._res_to_char[id_int]
                    res_id = entry["resource_id"]
                    char_name = entry["name"]
                else:
                    # 尝试战斗 TID 前缀推算: e.g. 101801 -> 18, 108201 -> 82
                    prefix = id_int // 100
                    if prefix > 1000:
                        cand_res = prefix - 1000
                        if cand_res in self._res_to_char:
                            entry = self._res_to_char[cand_res]
                            res_id = entry["resource_id"]
                            char_name = entry["name"]
            except ValueError:
                # 传入的是名称或别名
                name_str = str(lookup_id).lower().strip()
                if name_str in self._name_to_char:
                    entry = self._name_to_char[name_str]
                    res_id = entry["resource_id"]
                    char_name = entry["name"]

        # 4. 若匹配到角色，定位对应头像文件
        if res_id is not None:
            if char_name == "Unknown" and res_id in self._res_to_char:
                char_name = self._res_to_char[res_id]["name"]

            # 首选目标：对应皮肤的 si 头像
            target_fn = f"si_c{res_id:03d}_{costume_idx:02d}_s.webp"
            found_path = self._locate_file(target_fn)
            if not found_path:
                # 尝试 png 扩展名
                found_path = self._locate_file(f"si_c{res_id:03d}_{costume_idx:02d}_s.png")

            if found_path:
                rel_uri = f"/character/si/{found_path.name}"
                return LineupPortraitResolution(
                    local_path=found_path,
                    relative_uri=rel_uri,
                    is_fallback=is_fallback or (fallback_reason is not None),
                    fallback_reason=fallback_reason,
                    character_id=char_id_val,
                    resource_id=res_id,
                    costume_index=costume_idx,
                    character_name=char_name,
                )

            # 皮肤头像未命中，多级降级：尝试原皮 (00)
            if costume_idx != 0:
                default_fn = f"si_c{res_id:03d}_00_s.webp"
                default_path = self._locate_file(default_fn)
                if not default_path:
                    default_path = self._locate_file(f"si_c{res_id:03d}_00_s.png")

                if default_path:
                    logger.debug("Costume %d missing, fell back to default for res %d", costume_idx, res_id)
                    return LineupPortraitResolution(
                        local_path=default_path,
                        relative_uri=f"/character/si/{default_path.name}",
                        is_fallback=True,
                        fallback_reason=f"COSTUME_{costume_idx}_PORTRAIT_MISSING_FALLBACK_DEFAULT",
                        character_id=char_id_val,
                        resource_id=res_id,
                        costume_index=0,
                        character_name=char_name,
                    )

            # 原皮也不存在，降级到默认占位图
            logger.warning("Portrait asset missing for res %d, using default avatar", res_id)
            return LineupPortraitResolution(
                local_path=self.fallback_file,
                relative_uri="/character/si/default_avatar.webp",
                is_fallback=True,
                fallback_reason="PORTRAIT_FILE_NOT_FOUND_ON_DISK",
                character_id=char_id_val,
                resource_id=res_id,
                costume_index=costume_idx,
                character_name=char_name,
            )

        # 5. 完全无法识别角色 ID，返回通用占位图
        return LineupPortraitResolution(
            local_path=self.fallback_file,
            relative_uri="/character/si/default_avatar.webp",
            is_fallback=True,
            fallback_reason="UNRECOGNIZED_CHARACTER_ID",
            character_id=char_id_val,
            resource_id=None,
            costume_index=0,
            character_name="Unknown",
        )
