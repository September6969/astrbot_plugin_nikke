# SPDX-License-Identifier: GPL-3.0-or-later
"""Auto theme by corporation + element + portrait color."""

from __future__ import annotations

import colorsys
from collections import Counter
from dataclasses import dataclass
from typing import Any

from PIL import Image

# 共享展示令牌：状态色只用于状态，不参与数据判断。
UI_COLORS = {
    "background": "#111318", "panel": "#1A1E25", "raised": "#222731",
    "border": "#343B46", "text": "#F2F3F5", "muted": "#A9B2C0",
    "accent": "#E9B85A", "success": "#8FBCA2", "warning": "#E9B85A",
    "error": "#E3A1A1", "unknown": "#A9B2C0",
}
UI_SPACING = (8, 16, 24, 32, 40)
UI_RADIUS = 12
UI_TYPE_SCALE = (18, 21, 24, 28, 32, 40, 54, 68)


@dataclass(frozen=True, slots=True)
class CharacterTheme:
    """Immutable color palette for a single character card."""

    primary: str = "#91C8DC"
    secondary: str = "#D2E9F0"
    accent: str = "#59AFCB"
    background: str = "#11141B"
    panel: str = "#181E28"
    text: str = "#F4F6FA"
    muted: str = "#919BAB"


CORPORATION_COLORS: dict[str, dict[str, str]] = {
    "elysion": {
        "primary": "#F2C94C",
        "secondary": "#F5DFA0",
        "accent": "#E0A82E",
    },
    "missilis": {
        "primary": "#EB5757",
        "secondary": "#F5A3A3",
        "accent": "#C93C3C",
    },
    "tetra": {
        "primary": "#6FCF97",
        "secondary": "#A8E0C0",
        "accent": "#47B074",
    },
    "pilgrim": {
        "primary": "#9B51E0",
        "secondary": "#C9A0E8",
        "accent": "#7A31C0",
    },
    "abnormal": {
        "primary": "#828282",
        "secondary": "#BDBDBD",
        "accent": "#5A5A5A",
    },
}

ELEMENT_TINTS: dict[str, str] = {
    "fire": "#FF6B35",
    "water": "#3DA5F5",
    "wind": "#5FD4A3",
    "electric": "#F5D76E",
    "electronic": "#F5D76E",
    "iron": "#A0A0A0",
}

_DEFAULT_CORP = {
    "primary": "#91C8DC",
    "secondary": "#D2E9F0",
    "accent": "#59AFCB",
}


def _clamp(value: int, lo: int = 0, hi: int = 255) -> int:
    return max(lo, min(hi, value))


def _parse(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)


def _to_hex(r: float, g: float, b: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(_clamp(round(r)), _clamp(round(g)), _clamp(round(b)))


def _mix(c1: tuple[int, int, int], c2: tuple[int, int, int], weight: float) -> tuple[int, int, int]:
    return tuple(round(a * (1 - weight) + b * weight) for a, b in zip(c1, c2))


def _lighten(hex_color: str, amount: float) -> str:
    r, g, b = _parse(hex_color)
    return _to_hex(r + (255 - r) * amount, g + (255 - g) * amount, b + (255 - b) * amount)


def _darken(hex_color: str, amount: float) -> str:
    r, g, b = _parse(hex_color)
    return _to_hex(r * (1 - amount), g * (1 - amount), b * (1 - amount))


def _saturate(hex_color: str, amount: float) -> str:
    r, g, b = (_parse(hex_color)[i] / 255 for i in range(3))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    s = min(1.0, s + amount)
    nr, ng, nb = colorsys.hls_to_rgb(h, l, s)
    return _to_hex(nr * 255, ng * 255, nb * 255)


def _relative_luminance(hex_color: str) -> float:
    r, g, b = (_parse(hex_color)[i] / 255 for i in range(3))

    def linearize(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)


def _choose_text_colors(background: str) -> tuple[str, str]:
    if _relative_luminance(background) > 0.45:
        return "#1A1D24", "#5A5F6B"
    return "#F4F6FA", "#919BAB"


def _extract_portrait_palette(portrait: Any) -> tuple[str | None, str | None, str | None, bool]:
    """从非透明像素提取主色、次色和暗色。"""
    if portrait is None:
        return None, None, None, False
    try:
        width: int = portrait.width
        height: int = portrait.height
        if width <= 4 or height <= 4:
            return None, None, None, False
        left = width // 4
        top = height // 4
        right = width * 3 // 4
        bottom = height * 3 // 4
        cropped = portrait.crop((left, top, right, bottom)).convert("RGBA")
        small = cropped.resize((8, 8), Image.Resampling.LANCZOS)
        access = small.load()
        pixels = [
            (r, g, b)
            for y in range(small.height)
            for x in range(small.width)
            for r, g, b, alpha in (access[x, y],)
            if alpha >= 32
        ]
    except Exception:
        return None, None, None, False

    quantized: list[tuple[int, int, int]] = []
    for r, g, b in pixels:
        if max(r, g, b) - min(r, g, b) < 20 and max(r, g, b) < 40:
            continue
        quantized.append((r >> 4 << 4, g >> 4 << 4, b >> 4 << 4))

    if not quantized:
        return None, None, None, False

    ranked = [item[0] for item in Counter(quantized).most_common()]
    r, g, b = ranked[0]
    dominant = _to_hex(r, g, b)
    secondary_rgb = next((color for color in ranked[1:] if sum(abs(a - b) for a, b in zip(color, ranked[0])) >= 72), ranked[min(1, len(ranked) - 1)])
    dark_rgb = min(quantized, key=lambda color: sum(color))

    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    saturated = s > 0.22
    return dominant, _to_hex(*secondary_rgb), _to_hex(*dark_rgb), saturated


def _extract_portrait_colors(portrait: Any) -> tuple[str | None, bool]:
    """兼容旧测试与扩展调用的主色提取接口。"""
    dominant, _, _, saturated = _extract_portrait_palette(portrait)
    return dominant, saturated


def _shift_toward(
    source_hex: str,
    target_hex: str,
    *,
    hue_shift: float = 0.3,
    sat_boost: float = 0.0,
    light_boost: float = 0.0,
) -> str:
    sr, sg, sb = (_parse(source_hex)[i] / 255 for i in range(3))
    tr, tg, tb = (_parse(target_hex)[i] / 255 for i in range(3))
    sh, sl, ss = colorsys.rgb_to_hls(sr, sg, sb)
    th, tl, ts = colorsys.rgb_to_hls(tr, tg, tb)

    dh = th - sh
    if dh > 0.5:
        dh -= 1.0
    elif dh < -0.5:
        dh += 1.0
    new_h = (sh + dh * hue_shift) % 1.0

    new_s = min(1.0, max(0.0, ss + (ts - ss) * 0.4 + sat_boost))
    new_l = min(0.92, max(0.12, sl + (tl - sl) * 0.25 + light_boost))

    nr, ng, nb = colorsys.hls_to_rgb(new_h, new_l, new_s)
    return _to_hex(nr * 255, ng * 255, nb * 255)


def character_theme(
    corporation: str | None,
    element: str | None,
    portrait: Image.Image | None = None,
) -> CharacterTheme:
    """Build a *CharacterTheme* from corporation, element and portrait colour.

    1. Start from the corporation base palette (fallback to cool blue).
    2. Tint the accent toward the element colour.
    3. When the portrait carries a saturated dominant hue, nudge accent and
       primary toward it so the card echoes the character illustration.
    """
    corp_key = str(corporation or "").casefold()
    elem_key = str(element or "").casefold()
    corp_colors = CORPORATION_COLORS.get(corp_key, _DEFAULT_CORP)

    base_accent = corp_colors["accent"]
    accent = base_accent

    portrait_dominant, portrait_secondary, portrait_dark, portrait_saturated = _extract_portrait_palette(portrait)
    if portrait_dominant and portrait_saturated:
        # 立绘承担主要视觉权重，企业色只做弱混合。
        accent = _shift_toward(portrait_dominant, base_accent, hue_shift=0.20)

    element_tint = ELEMENT_TINTS.get(elem_key)
    if element_tint:
        accent = _shift_toward(accent, element_tint, hue_shift=0.05, sat_boost=0.02)

    primary = _lighten(accent, 0.22)
    primary = _saturate(primary, 0.08)
    secondary = _lighten(portrait_secondary or accent, 0.35)

    background = _to_hex(*_mix(_parse(UI_COLORS["background"]), _parse(portrait_dark or accent), 0.10))
    if corp_key == "abnormal":
        background = _mix(_parse(background), _parse("#120D18"), 0.62)
        background = _to_hex(*background)
    panel = _to_hex(*_mix(_parse(UI_COLORS["panel"]), _parse(background), 0.12))
    text, muted = _choose_text_colors(background)

    return CharacterTheme(
        primary=primary,
        secondary=secondary,
        accent=accent,
        background=background,
        panel=panel,
        text=text,
        muted=UI_COLORS["muted"],
    )
