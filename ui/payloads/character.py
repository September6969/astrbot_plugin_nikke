# SPDX-License-Identifier: GPL-3.0-or-later
"""妮姬角色卡的独立 T2I payload 投影。"""

from ..t2i_assets import T2IAssetResolver


def _normalize_equipment_icon(source):
    """裁去装备图标透明边缘，并放入固定尺寸的透明安全框。"""
    from PIL import Image, ImageOps

    if not isinstance(source, Image.Image):
        return source
    prepared = source.convert("RGBA")
    bbox = prepared.getchannel("A").getbbox()
    canvas = Image.new("RGBA", (180, 180), (0, 0, 0, 0))
    if bbox is None:
        return canvas
    trimmed = prepared.crop(bbox)
    fitted = ImageOps.contain(trimmed, (172, 172), Image.Resampling.LANCZOS)
    x = (180 - fitted.width) // 2
    y = (180 - fitted.height) // 2
    canvas.alpha_composite(fitted, (x, y))
    return canvas


def display_number(value):
    return "Unknown" if value is None else f"{value:,}"


class CharacterT2IPayloadBuilder:
    """只把角色卡 DTO 和已经解析的资产投影为模板数据。"""

    def __init__(self, resolver: T2IAssetResolver):
        self.resolver = resolver

    def build(self, data, card_assets):
        from dataclasses import asdict

        from ...features.character.models import EquipmentData, EquipmentOption
        from ...features.character.registries.static import StaticDataRegistry
        from ...features.character.replica import (
            SHORT_NAMES,
            VERSION,
            art_style,
            barlow_font,
            barlow_semibold_font,
            build_summary,
            cache_identity,
            noto_font,
            noto_font_700,
            noto_font_800,
            rajdhani_font,
            rajdhani_semibold_font,
            replica_font,
        )
        from ...features.character.layout import summary_layout
        from ...ui.renderers.character import CharacterCardRenderer
        from ...ui.theme import (
            _extract_portrait_palette,
            _parse,
            character_theme,
        )

        portrait = card_assets.portrait
        theme = character_theme(data.corporation, data.element, portrait)
        dominant, secondary, _, saturation = _extract_portrait_palette(portrait)
        if dominant and saturation:
            red, green, blue = _parse(dominant)
            secondary_rgb = _parse(secondary) if secondary else _parse(theme.accent)
            sr, sg, sb = secondary_rgb
            background = (
                f"radial-gradient(1100px 750px at 24% 42%, "
                f"rgba({red},{green},{blue},0.18) 0%, "
                f"rgba({sr},{sg},{sb},0.07) 45%, transparent 80%), "
                f"linear-gradient(135deg, rgba({red},{green},{blue},0.08) 0%, "
                f"{theme.background} 100%)"
            )
        else:
            red, green, blue = _parse(theme.accent)
            background = (
                f"radial-gradient(1100px 750px at 24% 42%, "
                f"rgba({red},{green},{blue},0.14) 0%, transparent 75%), "
                f"linear-gradient(135deg, rgba({red},{green},{blue},0.06) 0%, "
                f"{theme.background} 100%)"
            )

        equipment = []
        for slot, label in CharacterCardRenderer.SLOT_NAMES.items():
            item = data.equipment.get(slot, EquipmentData(slot))
            options = item.options if item.equipped else []
            rows = []
            for index in range(3):
                option = (
                    options[index]
                    if index < len(options)
                    else EquipmentOption("empty", "空槽", 0, "empty")
                )
                tier = option.tier if type(option.tier) is int and 1 <= option.tier <= 15 else None
                rows.append(
                    {
                        "name": option.display_name,
                        "value": CharacterCardRenderer._option_value(option),
                        "tier": f"T{tier}" if tier is not None else "—",
                        "replica_tier": f"{tier}阶" if tier is not None else "—",
                        "semantic": (
                            "max"
                            if tier == 15
                            else "high"
                            if tier is not None and tier >= 12
                            else "neutral"
                        ),
                        "state": (
                            "EMPTY"
                            if option.unit == "empty"
                            else "UNKNOWN"
                            if option.unit not in ("flat", "percent")
                            else "KNOWN"
                        ),
                    }
                )
            equipment.append(
                {
                    "label": label,
                    "status": (
                        f"LV.{item.level}"
                        if item.equipped and item.level is not None
                        else "已装备"
                        if item.equipped
                        else "未装备"
                    ),
                    "icon": self.resolver.encode(
                        _normalize_equipment_icon(card_assets.equipment.get(slot)),
                        (180, 180),
                    ),
                    "options": rows,
                }
            )

        identities = []
        for key, value in (
            ("corporation", data.corporation),
            ("element", data.element),
            ("weapon", data.weapon),
            ("burst", data.burst),
        ):
            identities.append(
                {
                    "label": str(value) if value is not None else "Unknown",
                    "icon": self.resolver.encode(getattr(card_assets, key), (120, 120)),
                }
            )

        def item_payload(item, image, kind=None):
            fallback_unworn = (
                "未佩戴魔方"
                if kind == "cube"
                else "未装配珍藏品/收藏品"
                if kind in ("favorite", "favorite_item")
                else "EMPTY / 未装备"
            )
            if not item or not getattr(item, "tid", None) or item.tid in (0, "0"):
                return {
                    "name": fallback_unworn,
                    "level": "—",
                    "icon": self.resolver.encode(image, (100, 100)),
                }
            name = getattr(item, "display_name", None)
            if not name and kind:
                name = StaticDataRegistry.resolve_display_name(kind, item.tid)
            return {
                "name": name or "已装备 · 名称 Unknown",
                "level": "LV." + display_number(item.level),
                "icon": self.resolver.encode(image, (100, 100)),
            }

        corporation_asset = getattr(card_assets, "corporation", None)
        watermark = (
            self.resolver.encode(corporation_asset, (260, 260))
            if corporation_asset
            else None
        )
        for gear in equipment:
            for row in gear["options"]:
                row["short_name"] = SHORT_NAMES.get(
                    row["name"].strip("【】"), row["name"]
                )
        replica = build_summary(data)
        layout = summary_layout(len(replica["rows"]))
        summary_panel_style = (
            f"top:{layout.local_top:.3f}px;height:{layout.height:.3f}px"
            if layout.visible
            else ""
        )
        character_layout = {
            "summary_count": layout.count,
            "summary_height": layout.height,
            "summary_top": layout.card_top,
            "summary_bottom": layout.card_bottom,
            "gear_top": layout.gear_top,
            "safe_top": layout.safe_top,
            "safe_bottom": layout.safe_bottom,
        }
        skills_assets = getattr(card_assets, "skills", {}) or {}
        return {
            "replica_summary": replica,
            "template_version": VERSION,
            "cache_identity": cache_identity(data),
            "grade": data.grade,
            "core": data.core,
            "skill_items": [
                {
                    "label": label,
                    "level": level,
                    "icon": self.resolver.encode(skills_assets.get(key), (110, 110)),
                }
                for key, label, level in (
                    ("skill1", "技能1", data.skill1_level),
                    ("skill2", "技能2", data.skill2_level),
                    ("burst", "爆裂", data.burst_skill_level),
                )
            ],
            "replica_font": replica_font(),
            "font_noto": noto_font(),
            "font_noto_700": noto_font_700(),
            "font_noto_800": noto_font_800(),
            "font_barlow": barlow_font(),
            "font_barlow_sb": barlow_semibold_font(),
            "font_rajdhani": rajdhani_font(),
            "font_rajdhani_sb": rajdhani_semibold_font(),
            "art_style": art_style(data, portrait, summary_count=layout.count),
            "summary_panel_style": summary_panel_style,
            "character_layout": character_layout,
            "name": data.name_cn,
            "english": data.name_en,
            "long_name": len(data.name_cn) > 11,
            "combat": display_number(data.combat),
            "level": str(data.level),
            "rarity": data.rarity or "Unknown",
            "character_art_data_uri": self.resolver.encode(portrait, (1600, 2400)),
            "theme": asdict(theme),
            "identities": identities,
            "corporation_watermark": watermark,
            "bg_gradient": background,
            "summary": [
                {
                    "label": item.display_name,
                    "value": CharacterCardRenderer._option_value(item),
                    "tier": "—",
                }
                for item in data.option_totals
            ],
            "equipment": equipment,
            "skills": f"{data.skill1_level} / {data.skill2_level} / {data.burst_skill_level}",
            "favorite": item_payload(
                data.favorite_item, card_assets.favorite_item, kind="favorite"
            ),
            "cube": item_payload(data.cube, card_assets.cube, kind="cube"),
            "stats": [
                {"label": label, "value": display_number(value), "source": source}
                for label, value, source in (
                    ("HP", data.hp, data.hp_source),
                    ("ATK", data.attack, data.attack_source),
                    ("DEF", data.defense, data.defense_source),
                )
            ],
            "growth": f"突破 {data.grade} 星 · 核心 +{data.core} 阶 · 好感 {display_number(data.bond_level)}",
            "commander": data.commander_name,
            "updated": data.fetched_at,
            "version": data.plugin_version,
        }
