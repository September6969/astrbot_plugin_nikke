# SPDX-License-Identifier: GPL-3.0-or-later
"""战役关卡名称到内部 stage_id 的静态解析器。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CampaignStage:
    mode: str
    chapter: int
    name: str
    stage_id: int


class CampaignStageResolver:
    MODE_ALIASES = {
        "normal": "NORMAL",
        "n": "NORMAL",
        "普通": "NORMAL",
        "常态": "NORMAL",
        "hard": "HARD",
        "h": "HARD",
        "困难": "HARD",
        "硬": "HARD",
    }

    def __init__(self, mapping: dict[str, dict[str, dict[str, int]]]):
        self.mapping = mapping

    @classmethod
    def from_file(cls, path: str | Path) -> CampaignStageResolver:
        p = Path(path)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        return cls(data)

    @classmethod
    def normalize_mode(cls, mode: str) -> str:
        s = str(mode or "").strip().lower()
        return cls.MODE_ALIASES.get(s, "NORMAL")

    @classmethod
    def parse_query(cls, query: str) -> tuple[str, str]:
        """从用户查询文本解析出 (mode, stage_name)。
        例如:
        '46-40' -> ('NORMAL', '46-40')
        '困难 35-36' -> ('HARD', '35-36')
        'H35-36' -> ('HARD', '35-36')
        '普通 46-14A-1' -> ('NORMAL', '46-14A-1')
        """
        raw = str(query or "").strip()
        tokens = raw.split()
        if len(tokens) >= 2:
            mode_cand = tokens[0].lower()
            if mode_cand in cls.MODE_ALIASES:
                return cls.MODE_ALIASES[mode_cand], tokens[1].upper()

        # 检查前缀如 H35-36 或 N46-40
        m = re.match(r"^([hHnN])(\d+.*)$", raw)
        if m:
            prefix = "HARD" if m.group(1).upper() == "H" else "NORMAL"
            return prefix, m.group(2).upper()

        return "NORMAL", raw.upper()

    def resolve(self, mode: str, stage_name: str) -> CampaignStage | None:
        normalized_mode = self.normalize_mode(mode)
        cleaned_name = str(stage_name or "").strip().upper()

        chapter_text = cleaned_name.split("-", 1)[0]
        try:
            chapter = int(chapter_text)
        except ValueError:
            return None

        stage_id = (
            self.mapping
            .get(normalized_mode, {})
            .get(str(chapter), {})
            .get(cleaned_name)
        )

        if stage_id is None:
            return None

        return CampaignStage(
            mode=normalized_mode,
            chapter=chapter,
            name=cleaned_name,
            stage_id=int(stage_id),
        )

    def resolve_query(self, query: str) -> CampaignStage | None:
        mode, stage_name = self.parse_query(query)
        return self.resolve(mode, stage_name)

