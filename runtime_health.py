# SPDX-License-Identifier: GPL-3.0-or-later
"""提供不暴露敏感路径的本地运行健康诊断。"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


CACHE_DIRECTORY_NAMES = ("cache", "voice_cache", "announcements")
DEFAULT_MIN_FREE_BYTES = 1024 * 1024 * 1024


@dataclass(frozen=True)
class RuntimeHealth:
    """健康诊断的只读快照，不包含账号、Cookie 或文件名。"""

    data_dir_exists: bool
    database_present: bool
    secret_key_present: bool
    cache_file_count: int
    cache_bytes: int
    temporary_file_count: int
    disk_free_bytes: int | None
    disk_total_bytes: int | None
    issues: tuple[str, ...]

    @property
    def status(self) -> str:
        return "正常" if not self.issues else "需关注"


def _is_temporary_name(name: str) -> bool:
    return name.endswith(".tmp") or name.startswith(".tmp-") or ".tmp." in name


def _measure_tree(root: Path) -> tuple[int, int, int]:
    """统计缓存文件，不跟随符号链接，避免越出插件数据目录。"""
    if not root.is_dir() or root.is_symlink():
        return 0, 0, 0

    file_count = 0
    total_bytes = 0
    temporary_count = 0
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        file_count += 1
                        total_bytes += entry.stat(follow_symlinks=False).st_size
                        if _is_temporary_name(entry.name):
                            temporary_count += 1
                    except OSError:
                        # 文件可能在诊断期间被并发替换；跳过该条目并继续汇总。
                        continue
        except OSError:
            continue
    return file_count, total_bytes, temporary_count


def _read_disk_usage(root: Path) -> tuple[int | None, int | None]:
    """读取并校验磁盘容量，拒绝负数、零总量和 free 大于 total 的异常值。"""
    try:
        usage = shutil.disk_usage(root)
    except OSError:
        return None, None

    free = usage.free
    total = usage.total
    if (
        isinstance(free, bool)
        or isinstance(total, bool)
        or not isinstance(free, int)
        or not isinstance(total, int)
        or free < 0
        or total <= 0
        or free > total
    ):
        return None, None
    return free, total


def collect_runtime_health(
    data_dir: str | Path,
    *,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
) -> RuntimeHealth:
    """收集本地目录、缓存和磁盘容量状态；此函数不写入或删除任何文件。"""
    root = Path(data_dir).expanduser()
    # 保留原始目录边界；先 resolve 会把数据目录自身的符号链接变成真实目录。
    data_dir_exists = root.is_dir() and not root.is_symlink()
    database = root / "nikke.sqlite3"
    secret_key = root / "secret.key"
    database_present = data_dir_exists and database.is_file() and not database.is_symlink()
    secret_key_present = data_dir_exists and secret_key.is_file() and not secret_key.is_symlink()

    cache_file_count = 0
    cache_bytes = 0
    temporary_file_count = 0
    if data_dir_exists:
        for directory_name in CACHE_DIRECTORY_NAMES:
            count, size, temporary = _measure_tree(root / directory_name)
            cache_file_count += count
            cache_bytes += size
            temporary_file_count += temporary

    usage_root = root if data_dir_exists else root.parent
    disk_free_bytes, disk_total_bytes = _read_disk_usage(usage_root)

    issues: list[str] = []
    if not data_dir_exists:
        issues.append("数据目录缺失")
    if not database_present:
        issues.append("数据库缺失")
    if not secret_key_present:
        issues.append("密钥缺失")
    if temporary_file_count:
        issues.append("存在未清理临时缓存")
    if disk_free_bytes is None or disk_total_bytes is None:
        issues.append("磁盘容量不可用")
    elif disk_free_bytes < max(0, min_free_bytes):
        issues.append("磁盘可用空间偏低")

    return RuntimeHealth(
        data_dir_exists=data_dir_exists,
        database_present=database_present,
        secret_key_present=secret_key_present,
        cache_file_count=cache_file_count,
        cache_bytes=cache_bytes,
        temporary_file_count=temporary_file_count,
        disk_free_bytes=disk_free_bytes,
        disk_total_bytes=disk_total_bytes,
        issues=tuple(issues),
    )


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "未知"
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return "未知"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    return f"{amount:.1f} {unit}"


def format_runtime_health(snapshot: RuntimeHealth) -> str:
    """格式化为管理员可读文本，避免输出绝对路径和敏感文件名。"""
    disk = (
        f"{_format_bytes(snapshot.disk_free_bytes)} 可用 / "
        f"{_format_bytes(snapshot.disk_total_bytes)} 总计"
    )
    result = [
        f"本地数据：{'存在' if snapshot.data_dir_exists else '缺失'}",
        f"数据库：{'存在' if snapshot.database_present else '缺失'}；密钥：{'存在' if snapshot.secret_key_present else '缺失'}",
        f"缓存：{snapshot.cache_file_count} 个文件 / {_format_bytes(snapshot.cache_bytes)}；临时文件：{snapshot.temporary_file_count} 个",
        f"磁盘：{disk}",
        f"状态：{snapshot.status}",
    ]
    if snapshot.issues:
        result.append("提示：" + "；".join(snapshot.issues))
    return "\n".join(result)
