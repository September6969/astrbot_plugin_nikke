# SPDX-License-Identifier: GPL-3.0-or-later
"""公告截止时间及其本地领域解析。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))

@dataclass(slots=True)
class GameDeadline:
    event_id: str
    name: str
    category: str
    end_at: datetime
    start_at: datetime | None = None
    source_content_id: str = ""
    source_url: str = ""
    deadline_version: int = 1
    start_precision: str = "EXACT"
    description: str = ""

    def is_active(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        if self.start_at and current < self.start_at:
            return False
        return current <= self.end_at

    def is_upcoming(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        return self.start_at is not None and current < self.start_at

    def is_ended(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        return current > self.end_at

    def remaining_display(self, now: datetime | None = None) -> str:
        current = now or datetime.now(timezone.utc)
        if current > self.end_at:
            return "已结束"
        diff = self.end_at - current
        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        if days > 0:
            return f"剩余 {days}天 {hours}小时"
        if hours > 0:
            return f"剩余 {hours}小时 {minutes}分钟"
        return f"剩余 {max(1, minutes)}分钟"


class DeadlineParser:
    MONTHS = {name.lower(): index for index, name in enumerate(
        ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1)}

    @classmethod
    def _normalize_english_dates(cls, body: str) -> str:
        """只转换带明确年份和时间的英文月份日期，不补猜年份。"""
        # 1. 匹配含明确年份和时刻的英文月份日期。
        pattern_time = re.compile(
            r"\b(" + "|".join(cls.MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})(?:,\s*|\s+(?:at\s+)?)(\d{1,2}):(\d{2})(?::\d{2})?",
            re.IGNORECASE,
        )
        body = pattern_time.sub(
            lambda m: f"{m.group(3)}-{cls.MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d} {int(m.group(4)):02d}:{m.group(5)}",
            body,
        )
        # 2. 维护结束只提供日期；用日期占位和标记传递精度，禁止伪造凌晨四点。
        pattern_maint = re.compile(
            r"(?:From the end of the|after(?: the)? maintenance on)\s+(" + "|".join(cls.MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})(?:\s+maintenance)?",
            re.IGNORECASE,
        )
        body = pattern_maint.sub(
            lambda m: f"{m.group(3)}-{cls.MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d} 00:00 [DATE_ONLY]",
            body,
        )
        return body

    # 匹配类似 2026.09.15 04:59 或 2026-09-15 05:00 或 2026/09/15 23:59 的时间
    DATETIME_PATTERN = re.compile(
        r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s+(\d{1,2}):(\d{2})"
    )

    @classmethod
    def _extract_timezone(cls, snippet: str, context: str = "") -> timezone:
        """从时间附近文本或上下文检测时区。默认 CST (UTC+8)。"""
        tz_pattern = re.compile(
            r"(?:\(|\b)(?:UTC|GMT)\s*([+-]\d{1,2})(?:\b|\))|"
            r"(?:\(|\b)(JST|KST)(?:\b|\))|"
            r"(?:\(|\b)(CST|SGT|HKT|BJT)(?:\b|\))|"
            r"(?:\(|\b)(UTC|GMT)(?:\b|\))|"
            r"(?:\(|\b)(PST)(?:\b|\))|"
            r"(?:\(|\b)(PDT)(?:\b|\))",
            re.IGNORECASE,
        )
        for target in (snippet, context):
            if not target:
                continue
            m = tz_pattern.search(target)
            if m:
                if m.group(1):
                    try:
                        return timezone(timedelta(hours=int(m.group(1))))
                    except ValueError:
                        pass
                name = (m.group(2) or m.group(3) or m.group(4) or m.group(5) or m.group(6) or "").upper()
                if name in ("JST", "KST"):
                    return timezone(timedelta(hours=9))
                if name in ("CST", "SGT", "HKT", "BJT"):
                    return timezone(timedelta(hours=8))
                if name in ("UTC", "GMT"):
                    return timezone.utc
                if name == "PST":
                    return timezone(timedelta(hours=-8))
                if name == "PDT":
                    return timezone(timedelta(hours=-7))
        return CST

    @classmethod
    def parse_deadlines(
        cls,
        title: str,
        body: str,
        content_id: str = "",
        category: str = "event",
    ) -> list[GameDeadline]:
        body = cls._normalize_english_dates(body)
        # 先统一时间在日期前的格式，避免全文没有标准日期时提前返回。
        body = re.sub(
            r"(\d{1,2}):(\d{2})(?::\d{2})?,?\s+(" + "|".join(cls.MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})",
            lambda m: f"{m.group(5)}-{cls.MONTHS[m.group(3).lower()]:02d}-{int(m.group(4)):02d} {int(m.group(1)):02d}:{m.group(2)}",
            body, flags=re.I,
        )
        total_matches = list(cls.DATETIME_PATTERN.finditer(body))
        if not total_matches:
            return []

        # 检查是否包含结构化多事件小节（如 "1. ", "2. ", "2.1 " 等）
        section_pattern = re.compile(r"(?m)^(?=[0-9]+(?:\.[0-9]+)*\s*[\.:、\s]+(?:[A-Za-z\u4e00-\u9fff]|\d+[- ]?(?:Day|day|日)))")
        raw_sections = section_pattern.split(body)
        if len(raw_sections) > 1:
            sections = [s.strip() for s in raw_sections if s.strip()]
        else:
            sections = [body]

        deadlines: list[GameDeadline] = []
        recovered: dict[str, GameDeadline] = {}

        story_parent = ""
        story_number = ""
        for sec_idx, sec in enumerate(sections):
            matches = list(cls.DATETIME_PATTERN.finditer(sec))
            lines = [line.strip() for line in sec.splitlines() if line.strip()]
            first_line = lines[0] if lines else title
            clean_subname = re.sub(r"^[0-9]+(?:\.[0-9]+)*\s*[\.:、\s]*", "", first_line).strip()

            if len(sections) == 1 and not section_pattern.match(sec):
                event_name = title
            else:
                is_date_or_header = bool(
                    cls.DATETIME_PATTERN.search(clean_subname)
                    or re.match(r"^(?:活动时间|时间|开放时间|Period|Time|Duration|Notice|公告|Overview)", clean_subname, re.IGNORECASE)
                )
                if clean_subname and len(clean_subname) >= 3 and not is_date_or_header:
                    event_name = clean_subname
                else:
                    event_name = f"{title} ({sec_idx + 1})"

            # 无日期的父标题也必须保留；阶段名称只能继承同一编号层级的支线活动。
            heading_number = re.match(r"^(\d+(?:\.\d+)*)", first_line)
            number = heading_number.group(1) if heading_number else ""
            from ..calendar.content_quality import classify_explicit_title
            explicit = classify_explicit_title(clean_subname)
            if explicit and explicit[0] == "story_event":
                story_parent, story_number = clean_subname, number
            elif number and story_number and not number.startswith(story_number + "."):
                story_parent, story_number = "", ""
            if story_parent and re.match(r"^(?:story\s*[12]|hard(?:\s+mode)?|困难|困難)(?:\b|\s|[:：])", clean_subname, re.I):
                event_name = f"{story_parent} · {clean_subname}"
            if not matches:
                continue

            sec_lower = (first_line + " " + sec).lower()
            inferred_cat = category
            if any(w in sec_lower for w in ["coop", "co-op", "coordinated operation", "协同"]):
                inferred_cat = "coop"
            elif any(w in sec_lower for w in ["raid", "突袭"]):
                inferred_cat = "raid"
            elif any(w in sec_lower for w in ["recruit", "pick up", "招募"]):
                inferred_cat = "recruit"

            reverse_date = re.compile(
                r"(\d{1,2}):(\d{2})(?::\d{2})?,?\s+(" + "|".join(cls.MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})", re.I
            )
            if len(matches) > 2 or reverse_date.search(sec):
                # 只提取同一行中明确相连的一对日期；不把说明段的所有日期交叉配对。
                for line in lines:
                    candidate = reverse_date.sub(
                        lambda m: f"{m.group(5)}-{cls.MONTHS[m.group(3).lower()]:02d}-{int(m.group(4)):02d} {int(m.group(1)):02d}:{m.group(2)}", line
                    )
                    if len(list(cls.DATETIME_PATTERN.finditer(candidate))) != 2:
                        continue
                    for item in cls.parse_deadlines(event_name, candidate, content_id, inferred_cat):
                        identity = f"{event_name}|{item.start_at}|{item.end_at}"
                        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
                        # 新补出的区间用独立稳定 ID，避免与既有按序编号的事件冲突。
                        item.event_id = f"{content_id or 'anonymous'}_range_{digest}"
                        item.description = sec
                        recovered[item.event_id] = item
                continue

            if len(matches) == 2:
                try:
                    m_start, m_end = matches[0], matches[1]
                    between = sec[m_start.end() : m_end.start()]
                    if len(between) > 120 or not re.search(
                        r"[~～–—]|(?<!\w)-(?!\w)|至|到|结束|\b(?:to|until|ends?|ending)\b",
                        between,
                        re.IGNORECASE,
                    ):
                        continue
                    date_only_start = sec[m_start.end():m_start.end() + 15].lstrip().startswith("[DATE_ONLY]")
                    # DATE_ONLY 以展示时区的日期存储，不代表真实的午夜开始时刻。
                    start_tz = CST if date_only_start else cls._extract_timezone(sec[m_start.end() : m_start.end() + 30], sec)
                    start_dt = datetime(
                        int(m_start.group(1)),
                        int(m_start.group(2)),
                        int(m_start.group(3)),
                        int(m_start.group(4)),
                        int(m_start.group(5)),
                        tzinfo=start_tz,
                    ).astimezone(timezone.utc)

                    end_tz = cls._extract_timezone(sec[m_end.end() : m_end.end() + 30], sec)
                    end_dt = datetime(
                        int(m_end.group(1)),
                        int(m_end.group(2)),
                        int(m_end.group(3)),
                        int(m_end.group(4)),
                        int(m_end.group(5)),
                        tzinfo=end_tz,
                    ).astimezone(timezone.utc)

                    if end_dt <= start_dt:
                        continue

                    cid_prefix = content_id or hashlib.md5(title.encode()).hexdigest()[:8]
                    deadlines.append(
                        GameDeadline(
                            event_id=f"{cid_prefix}_{len(deadlines)}",
                            name=event_name,
                            category=inferred_cat,
                            start_at=start_dt,
                            start_precision="DATE_ONLY" if date_only_start else "EXACT",
                            end_at=end_dt,
                            source_content_id=content_id,
                            description=sec,
                        )
                    )
                except (ValueError, OverflowError):
                    pass
            elif len(matches) == 1:
                m_single = matches[0]
                start_pos = max(0, m_single.start() - 30)
                end_pos = min(len(sec), m_single.end() + 30)
                surrounding = (sec[start_pos:end_pos] + " " + first_line).lower()

                is_start_marker = bool(
                    re.search(
                        r"开始|开启|上线|开放|举办|发布|启动|\b(?:starts?|starting|opens?|opening|launch(?:es|ing)?|begins?|beginning)\b",
                        surrounding,
                    )
                )
                is_deadline_marker = bool(
                    re.search(
                        r"截止|结束|至|到|前|\b(?:ends?|ending|until|deadline)\b|维护结束",
                        surrounding,
                    )
                )

                if is_start_marker and not is_deadline_marker:
                    continue
                if not is_deadline_marker:
                    continue

                try:
                    end_tz = cls._extract_timezone(sec[m_single.end() : m_single.end() + 30], sec)
                    end_dt = datetime(
                        int(m_single.group(1)),
                        int(m_single.group(2)),
                        int(m_single.group(3)),
                        int(m_single.group(4)),
                        int(m_single.group(5)),
                        tzinfo=end_tz,
                    ).astimezone(timezone.utc)

                    cid_prefix = content_id or hashlib.md5(title.encode()).hexdigest()[:8]
                    deadlines.append(
                        GameDeadline(
                            event_id=f"{cid_prefix}_{len(deadlines)}",
                            name=event_name,
                            category=inferred_cat,
                            start_at=None,
                            end_at=end_dt,
                            source_content_id=content_id,
                            description=sec,
                        )
                    )
                except (ValueError, OverflowError):
                    pass

        return deadlines + list(recovered.values())
