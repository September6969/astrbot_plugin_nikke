# SPDX-License-Identifier: GPL-3.0-or-later
"""创建可离线恢复的 NIKKE 数据目录备份。

工具只读取源目录中的 SQLite 数据库和密钥文件，不连接网络、不访问账号，
并拒绝把备份写回源目录或覆盖已有备份。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class BackupError(RuntimeError):
    """备份前置条件或完整性检查失败。"""


_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _backup_label(label: str | None) -> str:
    if label is not None:
        if not _LABEL_RE.fullmatch(label):
            raise BackupError("备份名称只能包含字母、数字、点、下划线和短横线")
        return label
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"nikke-{timestamp}-{secrets.token_hex(4)}"


def _copy_database(source: Path, target: Path) -> None:
    source_connection = sqlite3.connect(source)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
        target_connection.commit()
    except sqlite3.Error as exc:
        raise BackupError("SQLite 备份失败") from exc
    finally:
        target_connection.close()
        source_connection.close()


def _verify_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        raise BackupError("备份数据库完整性检查失败") from exc
    finally:
        connection.close()
    if not row or row[0] != "ok":
        raise BackupError("备份数据库完整性检查未通过")


def create_backup(
    data_dir: str | Path,
    destination_dir: str | Path,
    *,
    label: str | None = None,
) -> Path:
    """创建数据库与密钥的不可覆盖备份，并返回备份目录。"""
    source_dir = Path(data_dir).resolve()
    destination_root = Path(destination_dir).resolve()
    if not source_dir.is_dir():
        raise BackupError("源数据目录不存在")
    if destination_root == source_dir or destination_root.is_relative_to(source_dir):
        raise BackupError("备份目录不能位于源数据目录内")

    database = source_dir / "nikke.sqlite3"
    secret_key = source_dir / "secret.key"
    if not database.is_file() or not secret_key.is_file():
        raise BackupError("源目录必须同时包含 nikke.sqlite3 和 secret.key")

    backup_name = _backup_label(label)
    destination_root.mkdir(parents=True, exist_ok=True)
    final_dir = destination_root / backup_name
    if final_dir.exists():
        raise BackupError("目标备份已存在，不会覆盖")

    staging_dir = Path(tempfile.mkdtemp(prefix=f".{backup_name}-", dir=destination_root))
    try:
        backup_database = staging_dir / "nikke.sqlite3"
        _copy_database(database, backup_database)
        _verify_database(backup_database)
        shutil.copyfile(secret_key, staging_dir / "secret.key")

        manifest = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": ["nikke.sqlite3", "secret.key"],
            "sha256": {
                "nikke.sqlite3": _sha256(backup_database),
                "secret.key": _sha256(staging_dir / "secret.key"),
            },
        }
        (staging_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        staging_dir.replace(final_dir)
        return final_dir
    except OSError as exc:
        raise BackupError("写入备份失败") from exc
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="备份 NIKKE SQLite 数据库与 secret.key")
    parser.add_argument("--data-dir", required=True, type=Path, help="包含 nikke.sqlite3 和 secret.key 的目录")
    parser.add_argument("--destination", required=True, type=Path, help="备份输出目录")
    parser.add_argument("--label", help="备份目录名，不填则自动生成")
    args = parser.parse_args(argv)
    try:
        print(create_backup(args.data_dir, args.destination, label=args.label))
    except BackupError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
