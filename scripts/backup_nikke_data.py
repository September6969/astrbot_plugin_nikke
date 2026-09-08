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

from cryptography.fernet import Fernet, InvalidToken


class BackupError(RuntimeError):
    """备份前置条件或完整性检查失败。"""


_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _contains_symlink_component(path: Path) -> bool:
    """检查输入路径的每个已存在部分，避免通过父级链接越界。"""
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
    return False


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
    source_connection = None
    target_connection = None
    try:
        source_connection = sqlite3.connect(source)
        target_connection = sqlite3.connect(target)
        source_connection.backup(target_connection)
        target_connection.commit()
    except (OSError, sqlite3.Error) as exc:
        raise BackupError("SQLite 备份失败") from exc
    finally:
        if target_connection is not None:
            target_connection.close()
        if source_connection is not None:
            source_connection.close()


def _verify_database(path: Path) -> None:
    connection = None
    try:
        connection = sqlite3.connect(path)
        row = connection.execute("PRAGMA integrity_check").fetchone()
    except (OSError, sqlite3.Error) as exc:
        raise BackupError("备份数据库完整性检查失败") from exc
    finally:
        if connection is not None:
            connection.close()
    if not row or row[0] != "ok":
        raise BackupError("备份数据库完整性检查未通过")


def _read_fernet_key(path: Path) -> tuple[bytes, Fernet]:
    """只读解析 Fernet 密钥，不创建或迁移任何本地状态。"""
    try:
        raw = path.read_bytes().strip()
        return raw, Fernet(raw)
    except (OSError, ValueError) as exc:
        raise BackupError("secret.key 格式无效") from exc


def _validate_encrypted_fields(database: Path, cipher: Fernet) -> dict[str, int | str]:
    """只读验证现有加密列；没有样本时明确记录而不是声称已验证。"""
    connection = None
    checked = 0
    try:
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'"
            )
        }
        if "accounts" not in tables:
            return {"status": "no_encrypted_sample", "checked_fields": 0}
        columns = {row[1] for row in connection.execute("PRAGMA table_info(accounts)")}
        encrypted_columns = sorted({"cookie_cipher", "xcommon_cipher"} & columns)
        for column in encrypted_columns:
            for (value,) in connection.execute(
                f"SELECT {column} FROM accounts WHERE {column} IS NOT NULL AND length({column}) > 0"
            ):
                if not isinstance(value, (bytes, bytearray)):
                    raise BackupError(f"加密字段格式异常：{column}")
                try:
                    cipher.decrypt(bytes(value))
                except InvalidToken as exc:
                    raise BackupError(f"加密字段无法使用 secret.key 解密：{column}") from exc
                checked += 1
    except BackupError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise BackupError("加密字段验证失败") from exc
    finally:
        if connection is not None:
            connection.close()
    return {
        "status": "all_encrypted_fields" if checked else "no_encrypted_sample",
        "checked_fields": checked,
    }


def _validate_manifest(backup_dir: Path) -> dict:
    manifest_path = backup_dir / "manifest.json"
    database = backup_dir / "nikke.sqlite3"
    secret_key = backup_dir / "secret.key"
    if any(path.is_symlink() for path in (manifest_path, database, secret_key)):
        raise BackupError("备份文件不能是符号链接")
    if not all(path.is_file() for path in (manifest_path, database, secret_key)):
        raise BackupError("备份缺少 manifest.json、nikke.sqlite3 或 secret.key")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError("备份 manifest 无法读取") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise BackupError("备份 manifest 版本不受支持")
    expected_hashes = manifest.get("sha256")
    if not isinstance(expected_hashes, dict):
        raise BackupError("备份 manifest 缺少哈希合同")
    for name, path in (("nikke.sqlite3", database), ("secret.key", secret_key)):
        if expected_hashes.get(name) != _sha256(path):
            raise BackupError(f"备份文件哈希校验失败：{name}")
    _verify_database(database)
    _, cipher = _read_fernet_key(secret_key)
    _validate_encrypted_fields(database, cipher)
    return manifest


def create_backup(
    data_dir: str | Path,
    destination_dir: str | Path,
    *,
    label: str | None = None,
) -> Path:
    """创建数据库与密钥的不可覆盖备份，并返回备份目录。"""
    source_input = Path(data_dir).expanduser()
    destination_input = Path(destination_dir).expanduser()
    if _contains_symlink_component(source_input):
        raise BackupError("源数据目录不能是符号链接")
    if _contains_symlink_component(destination_input):
        raise BackupError("备份输出目录不能是符号链接")

    source_dir = source_input.resolve()
    destination_root = destination_input.resolve()
    if not source_dir.is_dir():
        raise BackupError("源数据目录不存在")
    if destination_root == source_dir or destination_root.is_relative_to(source_dir):
        raise BackupError("备份目录不能位于源数据目录内")

    database = source_dir / "nikke.sqlite3"
    secret_key = source_dir / "secret.key"
    if database.is_symlink() or secret_key.is_symlink():
        raise BackupError("源目录文件不能是符号链接")
    if not database.is_file() or not secret_key.is_file():
        raise BackupError("源目录必须同时包含 nikke.sqlite3 和 secret.key")

    _, cipher = _read_fernet_key(secret_key)

    backup_name = _backup_label(label)
    try:
        destination_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError("备份输出目录不可用") from exc
    if not destination_root.is_dir():
        raise BackupError("备份输出目录不可用")
    final_dir = destination_root / backup_name
    if final_dir.exists() or final_dir.is_symlink():
        raise BackupError("目标备份已存在，不会覆盖")

    staging_dir = Path(tempfile.mkdtemp(prefix=f".{backup_name}-", dir=destination_root))
    try:
        backup_database = staging_dir / "nikke.sqlite3"
        _copy_database(database, backup_database)
        _verify_database(backup_database)
        encryption_validation = _validate_encrypted_fields(backup_database, cipher)
        backup_key = staging_dir / "secret.key"
        shutil.copyfile(secret_key, backup_key)
        backup_key.chmod(0o600)

        manifest = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": ["nikke.sqlite3", "secret.key"],
            "key_validation": encryption_validation,
            "sha256": {
                "nikke.sqlite3": _sha256(backup_database),
                "secret.key": _sha256(staging_dir / "secret.key"),
            },
        }
        (staging_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if final_dir.exists() or final_dir.is_symlink():
            raise BackupError("目标备份已存在，不会覆盖")
        staging_dir.replace(final_dir)
        return final_dir
    except OSError as exc:
            raise BackupError("写入备份失败") from exc
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def restore_backup(
    backup_dir: str | Path,
    destination_dir: str | Path,
    *,
    key_path: str | Path | None = None,
) -> Path:
    """将备份恢复到全新的目录，默认不覆盖且不初始化 NikkeStore。"""
    source_input = Path(backup_dir).expanduser()
    destination_input = Path(destination_dir).expanduser()
    if _contains_symlink_component(source_input):
        raise BackupError("备份目录不能是符号链接")
    if _contains_symlink_component(destination_input):
        raise BackupError("恢复输出目录不能是符号链接")
    source_dir = source_input.resolve()
    destination = destination_input.resolve()
    if not source_dir.is_dir():
        raise BackupError("备份目录不存在")
    if destination == source_dir or destination.is_relative_to(source_dir):
        raise BackupError("恢复目录不能位于备份目录内")
    if destination.exists() or destination.is_symlink():
        raise BackupError("恢复目标已存在，不会覆盖")
    _validate_manifest(source_dir)

    selected_key = Path(key_path).expanduser() if key_path is not None else source_dir / "secret.key"
    if _contains_symlink_component(selected_key) or selected_key.is_symlink() or not selected_key.is_file():
        raise BackupError("指定密钥文件不可用")
    _, cipher = _read_fernet_key(selected_key)
    parent = destination.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError("恢复输出目录不可用") from exc
    if _contains_symlink_component(parent):
        raise BackupError("恢复输出目录不能是符号链接")

    staging_dir = Path(tempfile.mkdtemp(prefix=".nikke-restore-", dir=parent))
    try:
        restored_database = staging_dir / "nikke.sqlite3"
        _copy_database(source_dir / "nikke.sqlite3", restored_database)
        _verify_database(restored_database)
        encryption_validation = _validate_encrypted_fields(restored_database, cipher)
        restored_key = staging_dir / "secret.key"
        shutil.copyfile(selected_key, restored_key)
        restored_key.chmod(0o600)
        manifest = {
            "schema_version": 1,
            "restored_at": datetime.now(timezone.utc).isoformat(),
            "files": ["nikke.sqlite3", "secret.key"],
            "key_validation": encryption_validation,
            "sha256": {
                "nikke.sqlite3": _sha256(restored_database),
                "secret.key": _sha256(restored_key),
            },
        }
        (staging_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if destination.exists() or destination.is_symlink():
            raise BackupError("恢复目标已存在，不会覆盖")
        staging_dir.replace(destination)
        return destination
    except BackupError:
        raise
    except OSError as exc:
        raise BackupError("写入恢复目录失败") from exc
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="备份 NIKKE SQLite 数据库与 secret.key")
    parser.add_argument("--data-dir", type=Path, help="包含 nikke.sqlite3 和 secret.key 的目录")
    parser.add_argument("--destination", type=Path, help="备份输出目录")
    parser.add_argument("--label", help="备份目录名，不填则自动生成")
    parser.add_argument("--restore-from", type=Path, help="待恢复的备份目录")
    parser.add_argument("--restore-destination", type=Path, help="全新的恢复输出目录")
    parser.add_argument("--key-path", type=Path, help="可选的显式 Fernet 密钥来源")
    args = parser.parse_args(argv)
    try:
        if args.restore_from is not None:
            if args.restore_destination is None or args.data_dir is not None or args.destination is not None:
                parser.error("恢复模式需要 --restore-destination，且不能同时使用备份参数")
            print(restore_backup(args.restore_from, args.restore_destination, key_path=args.key_path))
        else:
            if args.data_dir is None or args.destination is None or args.restore_destination is not None or args.key_path is not None:
                parser.error("备份模式需要 --data-dir/--destination，且不能同时使用恢复参数")
            print(create_backup(args.data_dir, args.destination, label=args.label))
    except BackupError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
