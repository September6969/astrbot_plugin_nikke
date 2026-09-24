# SPDX-License-Identifier: GPL-3.0-or-later
"""公告同步状态的脱敏只读诊断。"""

from __future__ import annotations

from collections import Counter

from .repository import AnnouncementRepository


class AnnouncementDiagnostics:
    """只呈现仓储摘要，不读取来源、不包含正文或投递目标。"""

    CACHE_RETENTION_DAYS = AnnouncementRepository.CACHE_RETENTION_DAYS
    REVISION_HISTORY_LIMIT = AnnouncementRepository.REVISION_HISTORY_LIMIT

    def __init__(self, repository: AnnouncementRepository):
        self.repository = repository

    def format_diagnostic_text(self) -> str:
        """返回不含正文、订阅 target 或凭据的本地只读诊断。"""
        locale_counts = Counter(record.locale for record in self.repository._records.values())
        category_counts = Counter(record.category for record in self.repository._records.values())
        lines = ["【公告诊断（公开只读）】", f"缓存公告: {len(self.repository._records)} 条"]
        if self.repository.last_updated_at:
            lines.append(f"最近同步: {self.repository.last_updated_at}")
        if self.repository.last_sync_report:
            report = self.repository.last_sync_report
            if report.get("success") is False:
                scope = "深度重扫" if report.get("deep") else "常规同步"
                lines.append(
                    f"最近同步: {scope}失败 · locale={report.get('locale', 'unknown')} · "
                    f"错误类型={report.get('error_type', 'UnknownError')}"
                )
            else:
                scope = "深度重扫" if report.get("deep") else "常规同步"
                lines.append(
                    f"最近范围: {scope} · locale={report.get('locale', 'unknown')} · "
                    f"收到 {report.get('received', 0)} / 新增 {report.get('new', 0)} / "
                    f"更新 {report.get('updated', 0)} / 乱序回放忽略 {report.get('stale', 0)}"
                )
            lines.append(f"来源顺序: {report.get('source_order', 'unknown')}（未宣称官方修改时序）")
        else:
            lines.append("最近范围: 尚未同步")
        locales = ", ".join(f"{name}: {count}" for name, count in sorted(locale_counts.items())) or "无"
        categories = ", ".join(f"{name}: {count}" for name, count in sorted(category_counts.items())) or "无"
        lines.append(f"locale: {locales}")
        lines.append(f"category: {categories}")
        lines.append(
            f"缓存保留: {self.CACHE_RETENTION_DAYS} 天；已见内容指纹最多 {self.REVISION_HISTORY_LIMIT} 个/公告。"
        )
        lines.append("本诊断不发起网络请求、不发送消息，也不输出订阅目标或凭据。")
        return "\n".join(lines)
