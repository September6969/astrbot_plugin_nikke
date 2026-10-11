"""冻结快照的分页投影，图片与文本共用同一份日期语义。"""
from .content_quality import sort_operations_display_events
from .query import format_event_time
from .models import _aware_utc
from .canonical_models import CST
from .time_rules import CalendarTimeRules, resolve_event_status


def schedule_pages(snapshot):
    context = snapshot.context
    groups = CalendarTimeRules.classify_events(context.events, context.now, snapshot.horizon_days)
    unconfirmed = sum(not event.is_valid_interval or resolve_event_status(event, context.now) == "UNKNOWN" for event in context.events)
    ordered = []
    for label, events, status in (
        ("24 小时内结束", groups.ending_soon, "ACTIVE"),
        ("进行中", groups.active, "ACTIVE"),
        ("即将开始", groups.upcoming, "UPCOMING"),
    ):
        for event in sort_operations_display_events(events, status):
            ordered.append({"id": event.id, "title": event.title[:120] + ("…" if len(event.title) > 120 else ""), "full_title": event.title, "group": label,
                            "start": format_event_time(event.start_at, event.start_precision),
                            "end": format_event_time(event.end_at, event.end_precision),
                            "remaining": ("结束时间待公布" if event.end_at is None or event.end_precision == "UNKNOWN" else event.remaining_display(context.now)),
                            "stale": bool(event.metadata.get("source_stale"))})
    # 长标题增加行高，按高度预算提前换页，不靠缩小字体装满八项。
    chunks, current, height = [], [], 0
    for item in ordered:
        width = sum(2 if ord(char) > 127 else 1 for char in item["title"])
        cost = 210 + max(0, (width + 57) // 58 - 1) * 45
        if current and (len(current) >= 8 or height + cost > 1800):
            chunks.append(current)
            current, height = [], 0
        current.append(item)
        height += cost
    if current or not chunks:
        chunks.append(current)
    total = len(chunks)
    summary = {"active": len(groups.active_including_soon), "ending": len(groups.ending_soon),
               "upcoming": len(groups.upcoming)}
    fresh = {"FRESH": "近期已确认", "STALE": "数据较旧", "EXPIRED": "数据已过期"}.get(context.freshness, "更新时间未知")
    coverage = {"COMPLETE": "主来源范围完整", "PARTIAL": "部分数据", "UNAVAILABLE": "覆盖范围未知"}.get(context.coverage, "覆盖范围未知")
    updated = "尚无内容更新时间"
    if snapshot.last_updated_at:
        try:
            updated = _aware_utc(snapshot.last_updated_at).astimezone(CST).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            pass
    sources = []
    for name, health in sorted(context.source_health.items()):
        if name == "manual":
            continue
        label = {"official": "官方公告", "gamekee": "GameKee"}.get(name, name)
        confirmed = health.last_success_at
        sources.append(f"{label}：" + (confirmed.astimezone(CST).strftime("%m/%d %H:%M") if confirmed else "未确认") + (" · 同步异常" if health.consecutive_failures else ""))
    empty_label = "此范围暂无已记录活动。" if context.coverage == "COMPLETE" else "当前可用数据未记录此范围的活动，无法确认是否为空。"
    pages = []
    for index in range(total):
        items = chunks[index]
        next_command = f"/妮姬 日程 {snapshot.horizon_days} {index + 2}" if index + 1 < total else "/妮姬 日程 刷新"
        state = f"{fresh} · {coverage}"
        lines = [f"【妮姬日程 · 未来 {snapshot.horizon_days} 天 · {index+1}/{total} 页】", state]
        if index == 0:
            lines.append(f"当前快照：进行中 {summary['active']} · 24 小时内结束 {summary['ending']} · 即将开始 {summary['upcoming']}")
        if unconfirmed:
            lines.append(f"另有 {unconfirmed} 项时间待确认，未计入上述范围数量。")
        if snapshot.sync_warning:
            lines.append("部分来源同步异常，以下包含本地缓存。")
        for item in items:
            lines.append(f"[{item['group']}] {item['full_title']}\n{item['start']} → {item['end']} · {item['remaining']}" + (" · 未重新确认" if item['stale'] else ""))
        if not items:
            lines.append(empty_label)
        lines.extend(sources)
        lines.append(f"内容更新：{updated} · 北京时间")
        lines.append(next_command)
        pages.append({"experience": True, "canvas": {"width": 1080, "height": 600},
                      "page_number": index+1, "page_total": total, "total_items": len(ordered),
                      "items": items, "summary": summary, "unconfirmed_count": unconfirmed, "state_label": state,
                      "horizon_days": snapshot.horizon_days, "next_command": next_command,
                      "updated_at_display": updated, "source_status": sources,
                      "sync_warning": snapshot.sync_warning, "empty_label": empty_label, "fallback_text": "\n".join(lines)})
    return pages
