"""日常任务图片与文本展示共用的状态标签。"""

from .models import DailyTaskResult, DailyTaskStatus


DAILY_STATUS_PRESENTATION = {
    DailyTaskStatus.SUCCESS: ("成功", "success"),
    DailyTaskStatus.ALREADY_DONE: ("已完成", "success"),
    DailyTaskStatus.PENDING: ("待执行", "warning"),
    DailyTaskStatus.FAILED: ("失败", "danger"),
    DailyTaskStatus.RATE_LIMITED: ("请求限流", "warning"),
    DailyTaskStatus.COOKIE_EXPIRED: ("登录失效", "danger"),
    DailyTaskStatus.UNKNOWN_AFTER_ACTION: ("结果待确认", "warning"),
    DailyTaskStatus.UNAVAILABLE: ("暂不可用", "muted"),
}

DAILY_REWARD_STATUS_LABELS = {
    "success": "领取成功",
    "already_done": "已领取",
    "pending": "尚未达成",
    "failed": "领取失败",
    "rate_limited": "请求限流",
    "cookie_expired": "登录失效",
    "unknown_after_action": "结果待确认",
    "unknown": "状态未验证",
    "unavailable": "暂不可用",
}


def daily_status_presentation(status):
    """将结构化状态码投影为本地化标签和样式语义。"""
    try:
        normalized = DailyTaskStatus(status)
    except (TypeError, ValueError):
        normalized = DailyTaskStatus.UNAVAILABLE
    return normalized, DAILY_STATUS_PRESENTATION[normalized]


def _split_record_fields(fields, chunk_size):
    chunks = []
    current = ""
    for index, field in enumerate(fields):
        token = field if index == 0 else f"\n{field}"
        if len(token) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(
                token[offset : offset + chunk_size]
                for offset in range(0, len(token), chunk_size)
            )
        elif len(current) + len(token) <= chunk_size:
            current += token
        else:
            chunks.append(current)
            current = token
    if current:
        chunks.append(current)
    return chunks


def _record_units(fields, index, budget):
    block = "\n".join(fields)
    if len(block) <= budget:
        return [(index, block)]
    size = max(1, budget - 48)
    while size > 0:
        chunks = _split_record_fields(fields, size)
        marker_lengths = [
            len(f"【第 {index} 条账号结果续页 {part}/{len(chunks)}】\n")
            for part in range(1, len(chunks) + 1)
        ]
        if all(marker_lengths[part - 1] + len(chunk) <= budget for part, chunk in enumerate(chunks, 1)):
            break
        size -= 1
    if size < 1:
        raise ValueError("日常汇总文本预算无法容纳续页标记")
    chunks = _split_record_fields(fields, size)
    return [
        (
            index,
            f"【第 {index} 条账号结果续页 {part}/{len(chunks)}】\n{chunk}",
        )
        for part, chunk in enumerate(chunks, 1)
    ]


def format_daily_summary_text(
    results, *, scope="日常任务执行摘要", page_size=10, max_chars=3500
):
    """按完整账号结果和字符预算生成有序文本块，超长单条明确续页。"""
    materialized = tuple(results)
    total = len(materialized)
    if not materialized:
        return (f"{scope}（暂无结果 / 共 0 条）",)

    body_budget = max_chars - len(scope) - 80
    if body_budget < 1:
        raise ValueError("日常汇总文本预算不足以包含范围标题")

    units = []
    for index, result in enumerate(materialized, start=1):
        _, (label, _) = daily_status_presentation(result.status)
        lines = [
            f"{result.account_name}｜{label}",
            f"  详情：{result.detail}",
        ]
        for item in result.items:
            if not isinstance(item, dict):
                continue
            raw_status = str(item.get("status") or item.get("state") or "unknown")
            reward_label = DAILY_REWARD_STATUS_LABELS.get(raw_status, "状态未验证")
            lines.append(
                f"  {item.get('name') or '日常项目'}：{reward_label}；{item.get('detail') or '状态未验证'}"
            )
        units.extend(_record_units(lines, index, body_budget))

    messages = []
    current = []
    current_chars = 0
    current_indices = set()
    for index, unit in units:
        added_chars = len(unit) + (1 if current else 0)
        new_account = index not in current_indices
        if current and (
            current_chars + added_chars > body_budget
            or (new_account and len(current_indices) >= page_size)
        ):
            messages.append((current, current_indices))
            current = []
            current_chars = 0
            current_indices = set()
            added_chars = len(unit)
        current.append((index, unit))
        current_chars += added_chars
        current_indices.add(index)
    if current:
        messages.append((current, current_indices))

    total_pages = len(messages)
    rendered = []
    for page_number, (message, indices) in enumerate(messages, start=1):
        start, end = min(indices), max(indices)
        header = (
            f"{scope}（第 {page_number}/{total_pages} 段；"
            f"账号结果 {start}–{end} / 共 {total} 条）"
        )
        text = f"{header}\n" + "\n".join(unit for _, unit in message)
        if len(text) > max_chars:
            raise ValueError("日常汇总文本块超过字符预算")
        rendered.append(text)
    return tuple(rendered)
