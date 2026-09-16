# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure data models for the NIKKE tarot subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VALID_ORIENTATIONS = {"upright", "reversed"}
VALID_POSITIONS = {"situation", "obstacle", "advice"}


@dataclass(frozen=True)
class TarotMeaning:
    keywords: tuple[str, ...]
    meaning: str
    advice: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TarotMeaning":
        keywords = payload.get("keywords") or []
        if not isinstance(keywords, list):
            raise ValueError("tarot meaning keywords must be a list")
        return cls(
            keywords=tuple(str(item).strip() for item in keywords if str(item).strip()),
            meaning=str(payload.get("meaning") or "").strip(),
            advice=str(payload.get("advice") or "").strip(),
        )


@dataclass(frozen=True)
class TarotCard:
    key: str
    arcana: str
    name_zh: str
    name_en: str
    character: str
    image: str
    upright: TarotMeaning
    reversed: TarotMeaning
    id: int | str = 0
    roman: str = ""
    suit: str = ""
    rank: str = ""
    slug: str = ""
    positions: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TarotCard":
        key = str(payload.get("key") or "").strip()
        arcana = str(payload.get("arcana") or "").strip().lower()
        if not key:
            raise ValueError("tarot card key is required")
        if arcana not in {"major", "minor"}:
            raise ValueError(f"invalid tarot arcana: {arcana!r}")
        positions = payload.get("positions") or {}
        if not isinstance(positions, dict):
            positions = {}
        return cls(
            key=key,
            arcana=arcana,
            name_zh=str(payload.get("name_zh") or "").strip(),
            name_en=str(payload.get("name_en") or "").strip(),
            character=str(payload.get("character") or "").strip(),
            image=str(payload.get("image") or "").strip(),
            upright=TarotMeaning.from_dict(payload.get("upright") or {}),
            reversed=TarotMeaning.from_dict(payload.get("reversed") or {}),
            id=payload.get("id", 0),
            roman=str(payload.get("roman") or "").strip(),
            suit=str(payload.get("suit") or "").strip().lower(),
            rank=str(payload.get("rank") or "").strip().lower(),
            slug=str(payload.get("slug") or "").strip(),
            positions=positions,
        )

    def meaning_for(self, orientation: str) -> TarotMeaning:
        if orientation == "upright":
            return self.upright
        if orientation == "reversed":
            return self.reversed
        raise ValueError(f"invalid tarot orientation: {orientation!r}")

    def position_text(self, position: str, orientation: str) -> str:
        block = self.positions.get(position)
        if not isinstance(block, dict):
            return ""
        return str(block.get(orientation) or "").strip()


@dataclass(frozen=True)
class DrawnTarotCard:
    card: TarotCard
    orientation: str
    position: str = ""

    def __post_init__(self) -> None:
        if self.orientation not in VALID_ORIENTATIONS:
            raise ValueError(f"invalid tarot orientation: {self.orientation!r}")
        if self.position and self.position not in VALID_POSITIONS:
            raise ValueError(f"invalid tarot spread position: {self.position!r}")

    @property
    def is_reversed(self) -> bool:
        return self.orientation == "reversed"

    @property
    def meaning(self) -> TarotMeaning:
        return self.card.meaning_for(self.orientation)


@dataclass(frozen=True)
class TarotReading:
    mode: str
    cards: tuple[DrawnTarotCard, ...]
    deck_size: int
    date_key: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "deck_size": self.deck_size,
            "date_key": self.date_key,
            "cards": [
                {
                    "key": draw.card.key,
                    "arcana": draw.card.arcana,
                    "name_zh": draw.card.name_zh,
                    "name_en": draw.card.name_en,
                    "character": draw.card.character,
                    "orientation": draw.orientation,
                    "position": draw.position,
                    "keywords": list(draw.meaning.keywords),
                    "meaning": draw.meaning.meaning,
                    "advice": draw.meaning.advice,
                    "image": draw.card.image,
                }
                for draw in self.cards
            ],
        }


@dataclass(frozen=True)
class TarotDeckStatus:
    total_data_cards: int
    major_data_cards: int
    minor_data_cards: int
    major_images_ready: int
    minor_images_ready: int
    active_cards: int
    minor_enabled: bool
    missing_major_images: tuple[str, ...] = ()
    missing_minor_images: tuple[str, ...] = ()

    def summary(self) -> str:
        minor_state = "已启用" if self.minor_enabled else "未启用"
        return (
            f"牌库：{self.active_cards} 张可抽取 · "
            f"大阿尔卡那图片 {self.major_images_ready}/{self.major_data_cards} · "
            f"小阿尔卡那图片 {self.minor_images_ready}/{self.minor_data_cards}（{minor_state}）"
        )
