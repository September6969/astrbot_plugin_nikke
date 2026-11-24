# SPDX-License-Identifier: GPL-3.0-or-later
"""妮姬角色卡的独立 T2I payload 投影。"""

from typing import Any

from ..t2i_assets import T2IAssetResolver
from ...features.character.ports import CharacterRenderIdentity
from .common import display_number, text_units

CHARACTER_CANVAS = {"width": 1600, "height": 2400}
DEFAULT_TYPO_SET = "typo-set-b"
# 各排版档位实际引用的 @font-face（与 character.html 的 .character.* 字体变量同步）。
# 只内联当前档位用到的字体；未引用的字重与重复的 font_noto 不再进入 payload（AUD-021）。
TYPOGRAPHY_FONTS: dict[str, tuple[str, ...]] = {
    "typo-set-b": ("noto", "replica", "barlow", "rajdhani"),
    "header-font-b": ("noto", "replica", "barlow", "rajdhani"),
    "typo-current": ("replica", "barlow", "rajdhani"),
    "header-font-a": ("replica", "barlow", "rajdhani"),
    "typo-set-c": ("noto", "replica", "rajdhani"),
    "header-font-c": ("noto", "replica", "rajdhani"),
    "header-font-d": ("noto", "replica", "barlow", "barlow_sb", "rajdhani", "rajdhani_sb"),
}
# 模板中固定渲染且走中文字体栈（--font-cn-* / --font-ui）的文案。
TEMPLATE_TEXT = "词条合计已知词条合计阶✦未装备未获得效果【】"
# 名称槽 630px；字号 67/56/41px，字距 -1.5px；4% 余量吸收字形差异。
NAME_SLOT_PX = 630
NAME_FIT_RATIO = 0.96


def _name_fit(name: str) -> str:
    """名称单行放得下用标准字号，略长改用中号单行，再长才两行（模板以省略号兜底）。"""
    width = text_units(name)
    budget = NAME_SLOT_PX * NAME_FIT_RATIO
    if width * (67 - 1.5) <= budget:
        return ""
    if width * (56 - 1.5) <= budget:
        return "mid"
    return "long"


def _combat_fit(text: str) -> str:
    """战力槽 195px 宽：七位及以上逐级缩小字号，避免压到右侧星级（AUD-017）。"""
    digits = text.replace(",", "")
    if not digits.isdigit():
        return "text"
    return {7: "d7", 8: "d8"}.get(len(digits), "d9" if len(digits) >= 9 else "")


def _cn_stack_texts(payload: dict[str, Any]) -> list[str]:
    """收集模板中以中文字体栈渲染的文字；数字/科技字体元素不会回退到 Replica。"""
    texts = [TEMPLATE_TEXT, payload["name"]]
    if not payload.get("character_art_data_uri"):
        texts.append("立绘暂不可用")
    texts.extend(item["label"] for item in payload["identities"] if not item["icon"])
    texts.extend(item["label"] for item in payload["skill_items"] if not item["icon"])
    for row in payload["replica_summary"]["rows"]:
        texts.extend((row["label"], row["note"]))
    for gear in payload["equipment"]:
        if not gear["icon"]:
            texts.append(gear["label"])
        texts.extend(row["short_name"] for row in gear["options"] if row["state"] != "EMPTY")
    return texts


def _needs_replica_fallback(texts) -> bool:
    """中文字体栈为 NikkeNotoSC → Replica → 系统字体：只有子集缺字且 Replica 有该字时才会用到 Replica。

    清单不可用时保守地内联 Replica，保证与历史渲染一致。
    """
    from ...features.character.replica import replica_fallback_codepoints

    fallback_only = replica_fallback_codepoints()
    if fallback_only is None:
        return True
    return any(ord(char) in fallback_only for text in texts for char in str(text))


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


class CharacterT2IPayloadBuilder:
    """只把角色卡 DTO 和已经解析的资产投影为模板数据。"""

    def __init__(
        self,
        resolver: T2IAssetResolver,
        identity_resolver: CharacterRenderIdentity | None = None,
    ):
        self.resolver = resolver
        self.identity_resolver = identity_resolver

    def build(self, data, card_assets, typo_set: str = DEFAULT_TYPO_SET):
        from ...features.character.models import EquipmentData, EquipmentOption
        from ...features.character.registries.static import StaticDataRegistry
        from ...features.character.replica import (
            SHORT_NAMES,
            VERSION,
            art_style,
            build_summary,
            cache_identity,
        )
        from ...features.character.layout import summary_layout
        from .character_labels import (
            CHARACTER_EQUIPMENT_SLOT_LABELS,
            format_equipment_option_value,
        )

        if typo_set not in TYPOGRAPHY_FONTS:
            raise ValueError("未知的角色卡排版档位")
        portrait = card_assets.portrait

        equipment: list[dict[str, Any]] = []
        for slot, label in CHARACTER_EQUIPMENT_SLOT_LABELS.items():
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
                        "value": format_equipment_option_value(option),
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

        for gear in equipment:
            for row in gear["options"]:
                row["short_name"] = SHORT_NAMES.get(
                    row["name"].strip("【】"), row["name"]
                )
        replica = build_summary(data)
        layout = summary_layout(len(replica["rows"]))
        # 外层毛玻璃与实际内容一起收缩，装备和技能仍保持原卡面坐标。
        equipment_top = (layout.card_top if layout.visible else layout.gear_top) - 50.0
        equipment_height = 2340.0 - equipment_top
        gear_local_top = layout.gear_top - equipment_top
        summary_panel_style = (
            f"top:{layout.card_top - equipment_top:.3f}px;height:{layout.height:.3f}px"
            if layout.visible
            else ""
        )
        character_layout = {
            "equipment_top": equipment_top,
            "equipment_height": equipment_height,
            "gear_local_top": gear_local_top,
            "summary_count": layout.count,
            "summary_height": layout.height,
            "summary_top": layout.card_top,
            "summary_bottom": layout.card_bottom,
            "gear_top": layout.gear_top,
            "safe_top": layout.safe_top,
            "safe_bottom": layout.safe_bottom,
        }
        skills_assets = getattr(card_assets, "skills", {}) or {}
        skill_items = [
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
        ]
        combat = display_number(data.combat)
        name_fit = _name_fit(data.name_cn)
        # 只保留模板实际渲染的字段；英文名、稀有度、主题色、水印、旧摘要、
        # 属性/成长文案、页脚元数据等未渲染字段不再随每张卡传输（AUD-021）。
        payload = {
            "canvas": dict(CHARACTER_CANVAS),
            "typo_set": typo_set,
            "replica_summary": replica,
            "template_version": VERSION,
            "cache_identity": cache_identity(data),
            "grade": data.grade,
            "core": data.core,
            "skill_items": skill_items,
            "art_style": art_style(
                data,
                portrait,
                summary_count=layout.count,
                identity_resolver=self.identity_resolver,
            ),
            "summary_panel_style": summary_panel_style,
            "character_layout": character_layout,
            "name": data.name_cn,
            "name_fit": name_fit,
            "long_name": name_fit == "long",
            "combat": combat,
            "combat_fit": _combat_fit(combat),
            "level": str(data.level),
            "character_art_data_uri": self.resolver.encode(portrait, (1600, 2400)),
            "identities": identities,
            "equipment": equipment,
            "favorite": item_payload(
                data.favorite_item, card_assets.favorite_item, kind="favorite"
            ),
            "cube": item_payload(data.cube, card_assets.cube, kind="cube"),
        }
        payload.update(self._fonts(typo_set, payload))
        return payload

    @staticmethod
    def _fonts(typo_set: str, payload: dict[str, Any]) -> dict[str, str]:
        """按排版档位与实际文字内联字体：Replica 仅在子集缺字时作为回退嵌入。"""
        from ...features.character.replica import (
            barlow_font,
            barlow_semibold_font,
            noto_font_700,
            noto_font_800,
            rajdhani_font,
            rajdhani_semibold_font,
            replica_font,
        )

        families = TYPOGRAPHY_FONTS[typo_set]
        fonts: dict[str, Any] = {}
        if "noto" in families:
            fonts["font_noto_700"] = noto_font_700()
            fonts["font_noto_800"] = noto_font_800()
        if "replica" in families:
            primary = "noto" not in families or not (fonts["font_noto_700"] or fonts["font_noto_800"])
            texts = _cn_stack_texts(payload)
            if primary or _needs_replica_fallback(texts):
                fonts["replica_font"] = replica_font()
        loaders = {
            "barlow": ("font_barlow", barlow_font),
            "barlow_sb": ("font_barlow_sb", barlow_semibold_font),
            "rajdhani": ("font_rajdhani", rajdhani_font),
            "rajdhani_sb": ("font_rajdhani_sb", rajdhani_semibold_font),
        }
        for family, (key, loader) in loaders.items():
            if family in families:
                fonts[key] = loader()
        return {key: value for key, value in fonts.items() if value}
