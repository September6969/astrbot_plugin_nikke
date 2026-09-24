# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar Operations Feed T2I payload 与分页。"""

from pathlib import Path

from astrbot_plugin_nikke.ui.t2i_assets import T2IAssetResolver


class CalendarT2IPayloadBuilder:
    """Operations Feed T2I 渲染数据组装器。

    支持：
    1. 基于 Runtime Status Resolver 与起止时间精度的活动数据分类；
    2. 基于固定宽度 (1600) + 宣传图纵向长度驱动的动态画布高度 (900px ~ 2400px)；
    3. 每次 Query 共享同一背景源文件，按各页实际画布高度做高质量 Cover-Crop；
    4. 单项超页降级与标题视觉截断策略 (保留完整 full_title)；
    5. 全局状态与页面状态分离 (NO ACTIVE OPERATIONS 仅在全局无活动时出现)；
    6. 仅保留基于 EXACT 起止时间的辅助 timeline progress_pct 字段。

    高度预算与动态上限模型（Base-bounded + Source-extended）：
    - CANVAS_W = 1600px（固定宽度）
    - MIN_CANVAS_H = 900px（底线高度）
    - FALLBACK_MAX_CANVAS_H = 1600px（基础最大高度：无KV或横版KV时基础上限均允许生长至 1600px）
    - ABSOLUTE_MAX_CANVAS_H = 2400px（绝对安全上限）
    - scaled_source_h = round(1600 * source_h / source_w)
    - effective_max_canvas_h = min(max(FALLBACK_MAX_CANVAS_H, scaled_source_h), ABSOLUTE_MAX_CANVAS_H)
      即：Calendar 默认允许增长至 1600px；当 KV 提供更多纵向空间时（如竖版图），上限随 KV 延长，最高 2400px；横版图绝不会将上限压至 900px。
    - 垂直外边距: CANVAS_VERTICAL_MARGIN = 170px (上下各 85px 居中)
    - 面板固定开销: PANEL_OVERHEAD = 180px
      （包含 panel 上下 1px 边框，以及 body 的上下 padding；CSS 全部使用 border-box）
    - 动态内容净预算: effective_max_canvas_h - 170 - 180
    """

    CANVAS_W = 1600
    CANVAS_H = 900
    MIN_CANVAS_H = 900
    FALLBACK_MAX_CANVAS_H = 1600
    ABSOLUTE_MAX_CANVAS_H = 2400
    MAX_CANVAS_H = FALLBACK_MAX_CANVAS_H  # 向后兼容

    PANEL_W = 1180
    PANEL_H = 730
    MIN_PANEL_H = 730
    CANVAS_VERTICAL_MARGIN = 170  # panel_h = canvas_h - CANVAS_VERTICAL_MARGIN
    MAX_PANEL_H = ABSOLUTE_MAX_CANVAS_H - CANVAS_VERTICAL_MARGIN  # 2230

    HEADER_H = 70
    FOOTER_H = 44
    PANEL_TOP_PADDING = 28
    PANEL_BOTTOM_PADDING = 20
    BODY_TOP_PADDING = 10
    BODY_BOTTOM_PADDING = 6
    PANEL_BORDER_H = 2
    PANEL_OVERHEAD = (
        PANEL_TOP_PADDING
        + HEADER_H
        + BODY_TOP_PADDING
        + BODY_BOTTOM_PADDING
        + FOOTER_H
        + PANEL_BOTTOM_PADDING
        + PANEL_BORDER_H
    )  # 180

    MAX_CONTENT_BUDGET = FALLBACK_MAX_CANVAS_H - CANVAS_VERTICAL_MARGIN - PANEL_OVERHEAD  # 1250
    CONTENT_BUDGET = MAX_CONTENT_BUDGET

    # 以下常量必须与 calendar_schedule.html 的 border-box 几何保持一一对应。
    SECTION_HEADER_H = 32
    SECTION_HEADER_BOTTOM_GAP = 8
    NEXT_SECTION_TOP_GAP = 12
    ACTIVE_CARD_GAP = 5
    NEXT_ROW_GAP = 7
    ACTIVE_CARD_NORMAL_H = 68
    ACTIVE_CARD_LONG_H = 80
    ACTIVE_CARD_OVERSIZE_H = 92
    NEXT_ROW_NORMAL_H = 44
    NEXT_ROW_LONG_H = 58

    EMPTY_STATE_H = 60

    # 安全上限：防止异常无限增长（单页 Active + Next 总项数安全上限）
    SAFETY_MAX_ITEMS_PER_PAGE = 40

    def __init__(self, resolver: T2IAssetResolver | None = None):
        self.resolver = resolver or T2IAssetResolver()

    @classmethod
    def active_card_height(cls, item: dict) -> int:
        if item.get("is_oversize"):
            return cls.ACTIVE_CARD_OVERSIZE_H
        if item.get("is_long_title"):
            return cls.ACTIVE_CARD_LONG_H
        return cls.ACTIVE_CARD_NORMAL_H

    @classmethod
    def next_row_height(cls, item: dict) -> int:
        if item.get("is_oversize") or item.get("is_long_title"):
            return cls.NEXT_ROW_LONG_H
        return cls.NEXT_ROW_NORMAL_H

    @classmethod
    def measure_active_section(cls, items: list[dict]) -> int:
        """精确测量 Active section，不把相邻 item gap 嵌进 item 高度。"""
        if not items:
            return 0
        return (
            cls.SECTION_HEADER_H
            + cls.SECTION_HEADER_BOTTOM_GAP
            + sum(cls.active_card_height(item) for item in items)
            + max(0, len(items) - 1) * cls.ACTIVE_CARD_GAP
        )

    @classmethod
    def measure_next_section(cls, items: list[dict]) -> int:
        """精确测量 Next section，不把相邻 row gap 嵌进 item 高度。"""
        if not items:
            return 0
        return (
            cls.SECTION_HEADER_H
            + cls.SECTION_HEADER_BOTTOM_GAP
            + sum(cls.next_row_height(item) for item in items)
            + max(0, len(items) - 1) * cls.NEXT_ROW_GAP
        )

    @classmethod
    def measure_page_content(
        cls,
        active_items: list[dict],
        next_items: list[dict],
        global_has_active: bool = True,
        is_first_page: bool = False,
    ) -> int:
        content_h = 0
        if active_items:
            content_h += cls.measure_active_section(active_items)
        elif is_first_page and not global_has_active:
            content_h += cls.SECTION_HEADER_H + cls.SECTION_HEADER_BOTTOM_GAP + cls.EMPTY_STATE_H

        if (active_items or (is_first_page and not global_has_active)) and next_items:
            content_h += cls.NEXT_SECTION_TOP_GAP

        if next_items:
            content_h += cls.measure_next_section(next_items)

        return content_h

    @classmethod
    def compute_max_content_budget(cls, max_canvas_height: int) -> int:
        panel_h = max_canvas_height - cls.CANVAS_VERTICAL_MARGIN
        return panel_h - cls.PANEL_OVERHEAD

    @classmethod
    def compute_canvas_height(cls, content_h: int, max_canvas_height: int | None = None) -> int:
        max_h = max_canvas_height or cls.FALLBACK_MAX_CANVAS_H
        canvas_h_required = cls.PANEL_OVERHEAD + cls.CANVAS_VERTICAL_MARGIN + content_h
        return max(cls.MIN_CANVAS_H, min(max_h, canvas_h_required))

    @classmethod
    def compute_panel_height(cls, canvas_h: int) -> int:
        return canvas_h - cls.CANVAS_VERTICAL_MARGIN

    def _resolve_background_source(
        self, service, active_events, upcoming_events
    ) -> Path | None:
        vc = getattr(service, "visual_cache", None)
        if not vc or not hasattr(vc, "resolve_path"):
            return None

        candidate_ids = []
        # 优先级 1：进行中主活动
        main_categories = {"event", "solo_raid", "union_raid"}
        for ev in active_events:
            if ev.category in main_categories:
                candidate_ids.append(ev.event_id)
        # 优先级 2：其余进行中活动
        for ev in active_events:
            if ev.event_id not in candidate_ids:
                candidate_ids.append(ev.event_id)
        # 优先级 3：预告活动
        for ev in upcoming_events:
            if ev.event_id not in candidate_ids:
                candidate_ids.append(ev.event_id)
        # 优先级 4：本地清单内已有任意 KV
        manifest = getattr(vc, "_manifest", {})
        if isinstance(manifest, dict):
            for eid in manifest:
                if eid not in candidate_ids:
                    candidate_ids.append(str(eid))

        for eid in candidate_ids:
            path = vc.resolve_path(eid)
            if path is not None and isinstance(path, Path) and path.is_file():
                return path
        return None

    @classmethod
    def _get_background_dimensions(cls, path: Path | None) -> tuple[int, int] | None:
        if path is None:
            return None
        try:
            from PIL import Image
            with Image.open(path) as image:
                return image.size  # (width, height)
        except Exception:
            return None

    @classmethod
    def _compute_effective_max_canvas_height(
        cls, dimensions: tuple[int, int] | None
    ) -> tuple[int, int | None, int | None, int | None]:
        """计算有效最大画布高度。

        返回: (effective_max_h, source_w, source_h, scaled_source_h)
        """
        if dimensions is None:
            return cls.FALLBACK_MAX_CANVAS_H, None, None, None
        source_w, source_h = dimensions
        if source_w <= 0 or source_h <= 0:
            return cls.FALLBACK_MAX_CANVAS_H, source_w, source_h, None

        scaled_source_h = round(cls.CANVAS_W * source_h / source_w)
        effective_max_h = min(
            max(cls.FALLBACK_MAX_CANVAS_H, scaled_source_h),
            cls.ABSOLUTE_MAX_CANVAS_H,
        )
        return effective_max_h, source_w, source_h, scaled_source_h

    def _encode_background(
        self, path: Path | None, canvas_height: int = 900
    ) -> str | None:
        if path is None:
            return None
        try:
            return self.resolver.encode(
                path, size=(self.CANVAS_W, canvas_height), cover_crop=True
            )
        except Exception:
            return None

    def _resolve_background(
        self, service, active_events, upcoming_events, canvas_height: int = 900
    ) -> str | None:
        source_path = self._resolve_background_source(service, active_events, upcoming_events)
        return self._encode_background(source_path, canvas_height=canvas_height)

    def _paginate(
        self,
        active_items: list[dict],
        next_items: list[dict],
        global_has_active: bool,
        max_canvas_height: int | None = None,
    ) -> list[dict]:
        max_canvas_h = max_canvas_height or self.FALLBACK_MAX_CANVAS_H
        max_content_budget = self.compute_max_content_budget(max_canvas_h)

        pages = []
        rem_active = list(active_items)
        rem_next = list(next_items)

        if not rem_active and not rem_next:
            canvas_h = self.MIN_CANVAS_H
            panel_h = self.MIN_PANEL_H
            return [{
                "page_number": 1,
                "page_total": 1,
                "active_items": [],
                "next_items": [],
                "page_active_items": [],
                "page_next_items": [],
                "show_active_header": True,
                "show_next_header": False,
                "canvas": {"width": self.CANVAS_W, "height": canvas_h},
                "panel": {"width": self.PANEL_W, "height": panel_h},
            }]

        page_idx = 1
        while rem_active or rem_next:
            p_active = []
            p_next = []
            is_p1 = (page_idx == 1)

            # 1. 优先尝试放入 Active 任务
            while rem_active:
                if len(p_active) + len(p_next) >= self.SAFETY_MAX_ITEMS_PER_PAGE:
                    break
                candidate = rem_active[0]
                tentative = p_active + [candidate]
                tentative_h = self.measure_page_content(
                    tentative,
                    [],
                    global_has_active=global_has_active,
                    is_first_page=is_p1,
                )
                if tentative_h > max_content_budget:
                    if not p_active:
                        # 单项超页处理：独占当前页
                        candidate["is_oversize"] = True
                        p_active.append(rem_active.pop(0))
                    break
                p_active.append(rem_active.pop(0))

            # 2. 尝试放入 Next 预告任务
            while rem_next:
                if len(p_active) + len(p_next) >= self.SAFETY_MAX_ITEMS_PER_PAGE:
                    break
                candidate = rem_next[0]
                tentative = p_next + [candidate]
                tentative_h = self.measure_page_content(
                    p_active,
                    tentative,
                    global_has_active=global_has_active,
                    is_first_page=is_p1,
                )
                if tentative_h > max_content_budget:
                    if not p_active and not p_next:
                        candidate["is_oversize"] = True
                        p_next.append(rem_next.pop(0))
                    break
                p_next.append(rem_next.pop(0))

            # 紧急保底推进
            if not p_active and not p_next:
                if rem_active:
                    rem_active[0]["is_oversize"] = True
                    p_active.append(rem_active.pop(0))
                elif rem_next:
                    rem_next[0]["is_oversize"] = True
                    p_next.append(rem_next.pop(0))

            # 计算本页真实高度（以 max_canvas_h 为上限，按实际内容计算）
            actual_content_h = self.measure_page_content(
                p_active,
                p_next,
                global_has_active=global_has_active,
                is_first_page=is_p1,
            )
            page_canvas_h = self.compute_canvas_height(actual_content_h, max_canvas_height=max_canvas_h)
            page_panel_h = self.compute_panel_height(page_canvas_h)

            pages.append({
                "page_number": page_idx,
                "page_total": 0,
                "active_items": p_active,
                "next_items": p_next,
                "page_active_items": p_active,
                "page_next_items": p_next,
                "show_active_header": bool(p_active or (page_idx == 1 and not global_has_active)),
                "show_next_header": bool(p_next),
                "canvas": {"width": self.CANVAS_W, "height": page_canvas_h},
                "panel": {"width": self.PANEL_W, "height": page_panel_h},
            })
            page_idx += 1

        total_pages = len(pages)
        for p in pages:
            p["page_total"] = total_pages

        return pages

    def build(self, service, days=14, now=None, warning=""):
        from datetime import datetime, timedelta, timezone
        from astrbot_plugin_nikke.features.calendar.models import _aware_utc, TimePrecision
        from astrbot_plugin_nikke.features.calendar.canonical_models import (
            CanonicalEvent,
            resolve_event_status,
            EventStatus,
            Freshness,
            Coverage,
            resolve_next_ending,
        )
        from astrbot_plugin_nikke.features.calendar.content_quality import sort_operations_display_events
        from astrbot_plugin_nikke.features.calendar.schedule_service import CAT_LABELS, CST
        from astrbot_plugin_nikke.features.calendar.application import CalendarScheduleSnapshot

        # 1. 冻结 QueryContext
        is_snapshot = isinstance(service, CalendarScheduleSnapshot)
        if is_snapshot:
            ctx = service.context
            current = ctx.now
            events = ctx.events
            snapshot_ver = ctx.snapshot_version
            freshness = ctx.freshness
            coverage = ctx.coverage
            source_health = ctx.source_health
            days = service.horizon_days
        elif hasattr(service, "freeze_query_context"):
            ctx = service.freeze_query_context(now=now)
            current = ctx.now
            events = ctx.events
            snapshot_ver = ctx.snapshot_version
            freshness = ctx.freshness
            coverage = ctx.coverage
            source_health = ctx.source_health
        else:
            current = _aware_utc(now) if now else datetime.now(timezone.utc)
            events = [act.to_canonical() for act in getattr(service, "list_activities", lambda: [])()]
            snapshot_ver = "1.0.0"
            freshness = Freshness.FRESH
            coverage = Coverage.COMPLETE
            source_health = {}

        if not is_snapshot and hasattr(service, "normalize_horizon"):
            days = service.normalize_horizon(days)

        # 2. 运行时状态推导与地平线过滤
        active_canonical: list[CanonicalEvent] = []
        upcoming_canonical: list[CanonicalEvent] = []
        for ev in events:
            st = resolve_event_status(ev, current)
            if st == EventStatus.ACTIVE:
                active_canonical.append(ev)
            elif st == EventStatus.UPCOMING:
                if ev.start_at is None or ev.start_at <= current + timedelta(days=days):
                    upcoming_canonical.append(ev)

        # 展示排序与文本/旧查询接口共用 Operations Feed v2 契约。
        active_canonical = sort_operations_display_events(active_canonical, EventStatus.ACTIVE.value)
        upcoming_canonical = sort_operations_display_events(upcoming_canonical, EventStatus.UPCOMING.value)

        next_ending_ev = resolve_next_ending(active_canonical, now=current)
        next_ending_id = next_ending_ev.event_id if next_ending_ev else None

        # 3. 构造 Active Items
        active_items: list[dict] = []
        for ev in active_canonical:
            is_long = len(ev.title) > 26
            is_oversize = len(ev.title) > 65

            start_prec = ev.start_precision.value if hasattr(ev.start_precision, "value") else str(ev.start_precision)
            end_prec = ev.end_precision.value if hasattr(ev.end_precision, "value") else str(ev.end_precision)

            if ev.start_at and ev.end_at:
                if start_prec == "DATE_ONLY" and end_prec == "DATE_ONLY":
                    time_range = f"{ev.start_at.astimezone(CST).strftime('%m.%d')} → {ev.end_at.astimezone(CST).strftime('%m.%d')} · UTC+8"
                else:
                    s_fmt = "%m.%d %H:%M" if start_prec == "EXACT" else "%m.%d"
                    e_fmt = "%m.%d %H:%M" if end_prec == "EXACT" else "%m.%d"
                    time_range = f"{ev.start_at.astimezone(CST).strftime(s_fmt)} → {ev.end_at.astimezone(CST).strftime(e_fmt)} · UTC+8"
            elif ev.start_at:
                s_fmt = "%m.%d %H:%M" if start_prec == "EXACT" else "%m.%d"
                time_range = f"{ev.start_at.astimezone(CST).strftime(s_fmt)} 起 · UTC+8"
            elif ev.end_at:
                e_fmt = "%m.%d %H:%M" if end_prec == "EXACT" else "%m.%d"
                time_range = f"{ev.end_at.astimezone(CST).strftime(e_fmt)} 截止 · UTC+8"
            else:
                time_range = "时间未定 · UTC+8"

            remaining_str = ev.remaining_display(current)

            # 紧急度：严格限制只有 EXACT precision 参与小时级紧迫度
            urgency = "NORMAL"
            if end_prec == "EXACT" and ev.end_at and ev.end_at > current:
                diff_sec = (ev.end_at - current).total_seconds()
                if diff_sec <= 3600:
                    urgency = "CRITICAL"
                elif diff_sec <= 21600:
                    urgency = "URGENT"
                elif diff_sec <= 86400:
                    urgency = "CLOSING"
            elif end_prec != "EXACT":
                urgency = ""

            display_title = ev.title
            if is_oversize and len(display_title) > 90:
                display_title = display_title[:87] + "..."

            # 进度计算：严格条件，禁止伪造
            progress_pct: float | None = None
            if (
                ev.start_at is not None
                and ev.end_at is not None
                and start_prec == "EXACT"
                and end_prec == "EXACT"
                and ev.end_at > ev.start_at
                and ev.start_at <= current <= ev.end_at
            ):
                span = (ev.end_at - ev.start_at).total_seconds()
                elapsed = (current - ev.start_at).total_seconds()
                progress_pct = max(0.0, min(1.0, elapsed / span))

            card = {
                "event_id": ev.event_id,
                "title": display_title,
                "full_title": ev.title,
                "category": CAT_LABELS.get(ev.category, "活动"),
                "category_code": ev.category,
                "time_range": time_range,
                "start": ev.start_at.astimezone(CST).strftime("%m/%d %H:%M") if ev.start_at else "未知",
                "end": ev.end_at.astimezone(CST).strftime("%m/%d %H:%M") if ev.end_at else "未知",
                "remaining": remaining_str,
                "is_next_ending": (ev.event_id == next_ending_id),
                "urgency": urgency,
                "is_long_title": is_long,
                "is_oversize": is_oversize,
                "end_precision": end_prec,
                "progress_pct": progress_pct,          # None → 不显示进度条
            }
            active_items.append(card)


        # 4. 构造 Next Items
        next_items: list[dict] = []
        for ev in upcoming_canonical:
            is_long = len(ev.title) > 30
            is_oversize = len(ev.title) > 65
            start_prec = ev.start_precision.value if hasattr(ev.start_precision, "value") else str(ev.start_precision)

            if ev.start_at:
                s_fmt = "%m.%d %H:%M" if start_prec == "EXACT" else "%m.%d"
                start_time_display = ev.start_at.astimezone(CST).strftime(s_fmt)
                if start_prec == "EXACT":
                    diff = ev.start_at - current
                    days_diff = diff.days
                    hours_diff = diff.seconds // 3600
                    if days_diff >= 3:
                        starts_in = f"STARTS IN {days_diff}D"
                    elif days_diff > 0:
                        starts_in = f"STARTS IN {days_diff}D {hours_diff}H"
                    elif hours_diff > 0:
                        starts_in = f"STARTS IN {hours_diff}H"
                    else:
                        mins_diff = max(1, diff.seconds // 60)
                        starts_in = f"STARTS IN {mins_diff}M"
                elif start_prec == "DATE_ONLY":
                    diff_days = max(1, (ev.start_at.date() - current.date()).days)
                    starts_in = f"STARTS IN {diff_days}D"
                else:
                    starts_in = "即将开始"
            else:
                start_time_display = "时间待定"
                starts_in = "即将开始"

            display_title = ev.title
            if is_oversize and len(display_title) > 90:
                display_title = display_title[:87] + "..."

            nrow = {
                "event_id": ev.event_id,
                "title": display_title,
                "full_title": ev.title,
                "category": CAT_LABELS.get(ev.category, "活动"),
                "category_code": ev.category,
                "start_time_display": start_time_display,
                "starts_in": starts_in,
                "is_long_title": is_long,
                "is_oversize": is_oversize,
                "start": ev.start_at.astimezone(CST).strftime("%m/%d %H:%M") if ev.start_at else "未知",
                "end": ev.end_at.astimezone(CST).strftime("%m/%d %H:%M") if ev.end_at else "未知",
                "remaining": starts_in,
            }
            next_items.append(nrow)

        global_has_active = bool(active_items)
        active_count_total = len(active_items)

        # 5. 背景源探测与有效最大画布高度推导
        source_path = (
            service.background_path
            if is_snapshot
            else self._resolve_background_source(
                service, active_canonical, upcoming_canonical
            )
        )
        bg_dims = self._get_background_dimensions(source_path)
        effective_max_canvas_h, bg_w, bg_h, scaled_source_h = self._compute_effective_max_canvas_height(bg_dims)

        # 6. 分页计算（以 effective_max_canvas_h 作为最大高度预算）
        pages = self._paginate(
            active_items, next_items, global_has_active, max_canvas_height=effective_max_canvas_h
        )

        # 7. 背景图按每页实际 canvas.height 编码（所有页面共享相同背景源）
        for p in pages:
            p_canvas_h = p["canvas"]["height"]
            p["background_data_uri"] = self._encode_background(
                source_path, canvas_height=p_canvas_h
            )

        top_canvas = pages[0]["canvas"] if pages else {"width": self.CANVAS_W, "height": self.MIN_CANVAS_H}
        top_panel = pages[0]["panel"] if pages else {"width": self.PANEL_W, "height": self.MIN_PANEL_H}
        top_bg = pages[0]["background_data_uri"] if pages else None

        if scaled_source_h is None or scaled_source_h <= self.FALLBACK_MAX_CANVAS_H:
            height_policy = "base"
        elif scaled_source_h < self.ABSOLUTE_MAX_CANVAS_H:
            height_policy = "source_extended"
        else:
            height_policy = "absolute_capped"

        layout_limits = {
            "min_canvas_height": self.MIN_CANVAS_H,
            "effective_max_canvas_height": effective_max_canvas_h,
            "absolute_max_canvas_height": self.ABSOLUTE_MAX_CANVAS_H,
            "fallback_max_canvas_height": self.FALLBACK_MAX_CANVAS_H,
            "background_source_width": bg_w,
            "background_source_height": bg_h,
            "background_scaled_height": scaled_source_h,
            "height_policy": height_policy,
            "background_limited": bool(source_path and effective_max_canvas_h < self.ABSOLUTE_MAX_CANVAS_H),
        }

        # 8. 元数据准备
        updated_str = "Unknown"
        last_updated_at = (
            service.last_updated_at
            if is_snapshot
            else getattr(service, "last_updated_at", None)
        )
        if last_updated_at:
            try:
                updated_str = _aware_utc(last_updated_at).astimezone(CST).strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                pass

        fresh_str = freshness.value if hasattr(freshness, "value") else str(freshness)
        cov_str = coverage.value if hasattr(coverage, "value") else str(coverage)

        sync_warning = warning or (
            service.sync_warning
            if is_snapshot
            else getattr(service, "last_sync_error", "")
        )
        is_stale = (fresh_str == "STALE") or bool(sync_warning)

        # 直接消费 QueryContext 冻结的健康与来源展示
        if is_snapshot or hasattr(service, "freeze_query_context"):
            health_display = ctx.health_display
            source_display = ctx.source_display
            if not source_display or source_display == "UNKNOWN":
                source_display = "LOCAL SNAPSHOT"
        else:
            from astrbot_plugin_nikke.features.calendar.canonical_models import compute_health_badge
            health_display = compute_health_badge(fresh_str, cov_str)
            sources_present = set()
            if source_health:
                for s_name in source_health:
                    sources_present.add(s_name.upper())
            if not sources_present:
                source_display = "LOCAL SNAPSHOT"
            else:
                ordered = [s for s in ("GAMEKEE", "OFFICIAL", "MANUAL_OVERRIDE") if s in sources_present]
                for s in sorted(sources_present):
                    if s not in ordered:
                        ordered.append(s)
                source_display = " + ".join(ordered)

        fallback_text = (
            service.fallback_text
            if is_snapshot
            else service.format_schedule_text(days, current, warning)
            if hasattr(service, "format_schedule_text")
            else ""
        )

        bundle = {
            "snapshot_version": snapshot_ver,
            "query_now": current.isoformat(),
            "canvas": top_canvas,
            "panel": top_panel,
            "layout_limits": layout_limits,
            "background_data_uri": top_bg,
            "freshness": fresh_str,
            "coverage": cov_str,
            "health_display": health_display,
            "source_display": source_display,
            "timezone_display": "UTC+8",
            "updated_at_display": updated_str,
            "horizon_days": days,
            "is_stale": is_stale,
            "sync_warning": sync_warning,
            "available": (
                service.has_snapshot
                if is_snapshot
                else service.has_snapshot()
                if hasattr(service, "has_snapshot")
                else bool(events)
            ),
            "fallback_text": fallback_text,
            "global_has_active": global_has_active,
            "active_count_total": active_count_total,
            "pages": pages,
            # Top-level direct access (Page 1)
            "page_number": pages[0]["page_number"] if pages else 1,
            "page_total": len(pages),
            "active_items": pages[0]["active_items"] if pages else [],
            "next_items": pages[0]["next_items"] if pages else [],
            "page_active_items": pages[0]["active_items"] if pages else [],
            "page_next_items": pages[0]["next_items"] if pages else [],
            "show_active_header": pages[0]["show_active_header"] if pages else True,
            "show_next_header": pages[0]["show_next_header"] if pages else False,
        }
        return bundle
