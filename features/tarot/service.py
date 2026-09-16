# SPDX-License-Identifier: GPL-3.0-or-later
"""NIKKE tarot draw, persistence, formatting and image resolution.

The service deliberately keeps card selection deterministic/algorithmic and never asks
an LLM to choose a card.  Minor Arcana is activated atomically only when all 56 minor
card images exist, so a partially generated art set never biases the live deck.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from PIL import Image as PILImage

from .models import (
    DrawnTarotCard,
    TarotCard,
    TarotDeckStatus,
    TarotReading,
)

CHINA_TZ = timezone(timedelta(hours=8))
DEFAULT_SPREAD = ("situation", "obstacle", "advice")
DEFAULT_SPREAD_LABELS = {
    "situation": "现状",
    "obstacle": "阻碍",
    "advice": "建议",
}
ORIENTATION_LABELS = {
    "upright": "正位",
    "reversed": "逆位",
}


class TarotDataError(RuntimeError):
    """Raised when the tarot data files are malformed or unusable."""


class TarotDeckRepository:
    """Load card metadata and resolve static card assets.

    `deck_mode`:
      - auto: always use Major Arcana, enable Minor only when all 56 images exist.
      - major: Major Arcana only.
      - full: all data cards, even if an image is missing (text fallback remains usable).
    """

    def __init__(
        self,
        plugin_dir: Path,
        data_file: Path | None = None,
        *,
        deck_mode: str = "auto",
    ) -> None:
        self.plugin_dir = Path(plugin_dir).resolve()
        self.data_file = Path(data_file or self.plugin_dir / "assets" / "tarot" / "tarot_cards.json")
        self.deck_mode = str(deck_mode or "auto").strip().lower()
        if self.deck_mode not in {"auto", "major", "full"}:
            raise ValueError("tarot deck_mode must be auto, major, or full")
        self._cards: tuple[TarotCard, ...] = ()
        self._card_map: dict[str, TarotCard] = {}
        self._spread_labels = dict(DEFAULT_SPREAD_LABELS)
        self.reload()

    @property
    def cards(self) -> tuple[TarotCard, ...]:
        return self._cards

    @property
    def spread_labels(self) -> dict[str, str]:
        return dict(self._spread_labels)

    def reload(self) -> None:
        try:
            payload = json.loads(self.data_file.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise TarotDataError(f"塔罗数据文件不存在：{self.data_file}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise TarotDataError(f"塔罗数据读取失败：{type(exc).__name__}") from exc

        raw_cards = payload.get("cards") if isinstance(payload, dict) else None
        if not isinstance(raw_cards, list):
            raise TarotDataError("塔罗数据缺少 cards 数组")

        cards: list[TarotCard] = []
        seen: set[str] = set()
        for raw in raw_cards:
            if not isinstance(raw, dict):
                raise TarotDataError("塔罗 cards 中存在非对象条目")
            try:
                card = TarotCard.from_dict(raw)
            except (TypeError, ValueError) as exc:
                raise TarotDataError(f"塔罗卡数据非法：{exc}") from exc
            if card.key in seen:
                raise TarotDataError(f"塔罗卡 key 重复：{card.key}")
            seen.add(card.key)
            cards.append(card)

        major_count = sum(card.arcana == "major" for card in cards)
        minor_count = sum(card.arcana == "minor" for card in cards)
        if major_count != 22:
            raise TarotDataError(f"大阿尔卡那应为 22 张，当前为 {major_count} 张")
        if minor_count not in {0, 56}:
            raise TarotDataError(f"小阿尔卡那应为 0 或 56 张，当前为 {minor_count} 张")

        labels = payload.get("spread_labels") if isinstance(payload, dict) else None
        if isinstance(labels, dict):
            for key in DEFAULT_SPREAD_LABELS:
                value = str(labels.get(key) or "").strip()
                if value:
                    self._spread_labels[key] = value

        self._cards = tuple(cards)
        self._card_map = {card.key: card for card in cards}

    def card_by_key(self, key: str) -> TarotCard | None:
        return self._card_map.get(str(key))

    def resolve_image(self, card: TarotCard) -> Path | None:
        """Resolve a configured image safely inside the plugin directory."""
        relative = str(card.image or "").strip().replace("\\", "/")
        if not relative:
            return None
        candidate = (self.plugin_dir / relative).resolve()
        try:
            candidate.relative_to(self.plugin_dir)
        except ValueError:
            return None
        if candidate.is_file():
            return candidate

        # Compatibility fallback: a final card may have been copied under tarot/
        # while preserving only its basename.  Keep this bounded to assets/tarot.
        tarot_root = (self.plugin_dir / "assets" / "tarot").resolve()
        if tarot_root.is_dir():
            matches = list(tarot_root.rglob(Path(relative).name))
            if len(matches) == 1 and matches[0].is_file():
                return matches[0].resolve()
        return None

    def status(self) -> TarotDeckStatus:
        major = [card for card in self._cards if card.arcana == "major"]
        minor = [card for card in self._cards if card.arcana == "minor"]
        missing_major = tuple(card.key for card in major if self.resolve_image(card) is None)
        missing_minor = tuple(card.key for card in minor if self.resolve_image(card) is None)
        minor_ready = bool(minor) and not missing_minor and len(minor) == 56
        if self.deck_mode == "major":
            active = len(major)
            enabled = False
        elif self.deck_mode == "full":
            active = len(major) + len(minor)
            enabled = bool(minor)
        else:
            enabled = minor_ready
            active = len(major) + (len(minor) if enabled else 0)
        return TarotDeckStatus(
            total_data_cards=len(self._cards),
            major_data_cards=len(major),
            minor_data_cards=len(minor),
            major_images_ready=len(major) - len(missing_major),
            minor_images_ready=len(minor) - len(missing_minor),
            active_cards=active,
            minor_enabled=enabled,
            missing_major_images=missing_major,
            missing_minor_images=missing_minor,
        )

    def active_cards(self) -> tuple[TarotCard, ...]:
        major = tuple(card for card in self._cards if card.arcana == "major")
        minor = tuple(card for card in self._cards if card.arcana == "minor")
        if self.deck_mode == "major":
            return major
        if self.deck_mode == "full":
            return major + minor
        # Atomic activation: partial Minor Arcana must not bias probabilities.
        if minor and len(minor) == 56 and all(self.resolve_image(card) for card in minor):
            return major + minor
        return major


class TarotDailyStore:
    """Tiny privacy-preserving persistence for same-user/same-day daily draws."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @staticmethod
    def _subject_key(user_key: str) -> str:
        return hashlib.sha256(str(user_key).encode("utf-8")).hexdigest()[:32]

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def get(self, date_key: str, user_key: str) -> dict[str, str] | None:
        subject = self._subject_key(user_key)
        with self._lock:
            data = self._read()
            daily = data.get(date_key)
            if not isinstance(daily, dict):
                return None
            item = daily.get(subject)
            if not isinstance(item, dict):
                return None
            card_key = str(item.get("card_key") or "")
            orientation = str(item.get("orientation") or "")
            if not card_key or orientation not in {"upright", "reversed"}:
                return None
            return {"card_key": card_key, "orientation": orientation}

    def put(self, date_key: str, user_key: str, card_key: str, orientation: str) -> None:
        subject = self._subject_key(user_key)
        with self._lock:
            data = self._read()
            # Keep only today plus one prior date to prevent unbounded growth.
            keys = sorted(key for key, value in data.items() if isinstance(value, dict))
            for old in keys[:-1]:
                if old != date_key:
                    data.pop(old, None)
            daily = data.setdefault(date_key, {})
            if not isinstance(daily, dict):
                daily = {}
                data[date_key] = daily
            daily[subject] = {
                "card_key": str(card_key),
                "orientation": str(orientation),
            }
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)


class TarotImageProvider:
    """Resolve final card images and cache physically reversed variants."""

    def __init__(
        self,
        deck: TarotDeckRepository,
        cache_dir: Path,
        *,
        rotate_reversed: bool = True,
    ) -> None:
        self.deck = deck
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.rotate_reversed = bool(rotate_reversed)

    def image_for(self, draw: DrawnTarotCard) -> Path | None:
        source = self.deck.resolve_image(draw.card)
        if source is None or not draw.is_reversed or not self.rotate_reversed:
            return source
        try:
            stat = source.stat()
        except OSError:
            return None
        fingerprint = hashlib.sha256(
            f"{source}:{stat.st_mtime_ns}:{stat.st_size}".encode("utf-8")
        ).hexdigest()[:12]
        safe_key = draw.card.key.replace(":", "_").replace("/", "_")
        output = self.cache_dir / f"{safe_key}_reversed_{fingerprint}.png"
        if output.is_file():
            return output
        try:
            with PILImage.open(source) as image:
                rotated = image.convert("RGBA").rotate(180, expand=False)
                tmp = output.with_suffix(".tmp.png")
                rotated.save(tmp, format="PNG", optimize=True)
                os.replace(tmp, output)
        except (OSError, ValueError):
            return source
        return output


class TarotService:
    """Facade used by AstrBot handlers."""

    def __init__(
        self,
        plugin_dir: Path,
        data_dir: Path,
        *,
        deck_mode: str = "auto",
        rotate_reversed: bool = True,
    ) -> None:
        self.plugin_dir = Path(plugin_dir)
        self.runtime_dir = Path(data_dir)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.deck = TarotDeckRepository(self.plugin_dir, deck_mode=deck_mode)
        self.daily_store = TarotDailyStore(self.runtime_dir / "daily_draws.json")
        self.images = TarotImageProvider(
            self.deck,
            self.runtime_dir / "reversed_cache",
            rotate_reversed=rotate_reversed,
        )
        self._random = secrets.SystemRandom()

    @staticmethod
    def _draw_orientation(rng: random.Random | secrets.SystemRandom) -> str:
        return "reversed" if rng.randrange(2) else "upright"

    def _active(self) -> tuple[TarotCard, ...]:
        cards = self.deck.active_cards()
        if not cards:
            raise TarotDataError("当前没有可用塔罗牌")
        return cards

    def draw_single(self) -> TarotReading:
        cards = self._active()
        card = self._random.choice(cards)
        draw = DrawnTarotCard(card, self._draw_orientation(self._random))
        return TarotReading("single", (draw,), len(cards))

    def draw_three(self) -> TarotReading:
        cards = self._active()
        if len(cards) < 3:
            raise TarotDataError("当前牌库不足 3 张")
        chosen = self._random.sample(cards, 3)
        draws = tuple(
            DrawnTarotCard(card, self._draw_orientation(self._random), position)
            for card, position in zip(chosen, DEFAULT_SPREAD)
        )
        return TarotReading("three", draws, len(cards))

    def draw_daily(
        self,
        user_key: str,
        *,
        now: datetime | None = None,
    ) -> TarotReading:
        current = now.astimezone(CHINA_TZ) if now else datetime.now(CHINA_TZ)
        date_key = current.strftime("%Y-%m-%d")
        cards = self._active()
        saved = self.daily_store.get(date_key, user_key)
        if saved:
            saved_card = self.deck.card_by_key(saved["card_key"])
            if saved_card and saved_card in cards:
                draw = DrawnTarotCard(saved_card, saved["orientation"])
                return TarotReading("daily", (draw,), len(cards), date_key=date_key)

        # Stable seed avoids relying on Python's randomized hash(). Persistence above
        # additionally guarantees the draw survives deck expansion/restarts that day.
        seed_bytes = hashlib.sha256(
            f"NIKKE_TAROT_DAILY_V1|{user_key}|{date_key}".encode("utf-8")
        ).digest()
        rng = random.Random(int.from_bytes(seed_bytes, "big"))
        card = cards[rng.randrange(len(cards))]
        orientation = self._draw_orientation(rng)
        self.daily_store.put(date_key, user_key, card.key, orientation)
        draw = DrawnTarotCard(card, orientation)
        return TarotReading("daily", (draw,), len(cards), date_key=date_key)

    def image_paths(self, reading: TarotReading) -> list[Path | None]:
        return [self.images.image_for(draw) for draw in reading.cards]

    def deck_status(self) -> TarotDeckStatus:
        return self.deck.status()

    def format_help(self) -> str:
        status = self.deck.status()
        return (
            "【NIKKE 塔罗】\n"
            "/妮姬 塔罗 单抽 — 随机抽取 1 张牌\n"
            "/妮姬 塔罗 三张 — 现状 / 阻碍 / 建议\n"
            "/妮姬 塔罗 今日 — 同一用户当天固定 1 张\n"
            "/妮姬 塔罗 状态 — 查看牌库资源状态\n\n"
            f"{status.summary()}\n"
            "正逆位各 50%；今日塔罗按 UTC+8 日期计算。\n"
            "塔罗内容仅供娱乐与自我反思。"
        )

    def format_status(self) -> str:
        status = self.deck.status()
        lines = ["【塔罗牌库状态】", status.summary()]
        if status.missing_major_images:
            preview = "、".join(status.missing_major_images[:5])
            suffix = "…" if len(status.missing_major_images) > 5 else ""
            lines.append(f"缺失大阿尔卡那图片：{preview}{suffix}")
        if status.minor_data_cards and not status.minor_enabled:
            lines.append("小阿尔卡那采用原子启用：56 张图片全部就绪后才会进入抽牌池。")
        return "\n".join(lines)

    def format_reading(self, reading: TarotReading) -> str:
        if reading.mode == "three":
            return self._format_three(reading)
        draw = reading.cards[0]
        prefix = "【今日塔罗】" if reading.mode == "daily" else "【塔罗单抽】"
        date_line = f"\n日期：{reading.date_key}" if reading.date_key else ""
        return prefix + date_line + "\n\n" + self._format_one(draw, include_character=True) + self._footer(reading)

    def _format_three(self, reading: TarotReading) -> str:
        blocks = ["【三张牌阵｜现状 · 阻碍 · 建议】"]
        for index, draw in enumerate(reading.cards, 1):
            label = self.deck.spread_labels.get(draw.position, draw.position)
            orientation = ORIENTATION_LABELS[draw.orientation]
            meaning = draw.meaning
            contextual = draw.card.position_text(draw.position, draw.orientation)
            lines = [
                f"{index}. {label}｜{draw.card.name_zh} · {orientation}",
                f"关键词：{' · '.join(meaning.keywords)}",
            ]
            if contextual:
                lines.append(f"位置解读：{contextual}")
            else:
                lines.append(f"解读：{meaning.meaning}")
            if draw.position == "advice":
                lines.append(f"建议：{meaning.advice}")
            blocks.append("\n".join(lines))
        blocks.append(self._footer(reading).lstrip("\n"))
        return "\n\n".join(blocks)

    @staticmethod
    def _format_one(draw: DrawnTarotCard, *, include_character: bool) -> str:
        meaning = draw.meaning
        orientation = ORIENTATION_LABELS[draw.orientation]
        title = f"{draw.card.roman + ' · ' if draw.card.roman else ''}{draw.card.name_zh} · {orientation}"
        lines = [title]
        if include_character and draw.card.character:
            lines.append(f"角色：{draw.card.character}")
        lines.extend([
            f"关键词：{' · '.join(meaning.keywords)}",
            f"解读：{meaning.meaning}",
            f"建议：{meaning.advice}",
        ])
        return "\n".join(lines)

    @staticmethod
    def _footer(reading: TarotReading) -> str:
        return f"\n\n牌池：{reading.deck_size} 张 · 仅供娱乐与自我反思"
