# SPDX-License-Identifier: GPL-3.0-or-later
"""插件持久化与敏感数据加密。"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class NikkeStore:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "nikke.sqlite3"
        self.key_path = self.data_dir / "secret.key"
        self._lock = threading.RLock()
        self._cipher = Fernet(self._load_or_create_key())
        self._init_db()

    def _load_or_create_key(self) -> bytes:
        env_key = os.getenv("NIKKE_ENCRYPTION_KEY", "").strip()
        if env_key:
            return env_key.encode("ascii")
        if self.key_path.exists():
            return self.key_path.read_bytes().strip()
        key = Fernet.generate_key()
        self.key_path.write_bytes(key)
        os.chmod(self.key_path, 0o600)
        return key

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS bind_sessions (
                    token_hash TEXT PRIMARY KEY,
                    qq_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS accounts (
                    qq_id TEXT PRIMARY KEY,
                    cookie_cipher BLOB NOT NULL,
                    game_uid TEXT NOT NULL,
                    game_openid TEXT NOT NULL DEFAULT '',
                    nickname TEXT NOT NULL DEFAULT '',
                    role_name TEXT NOT NULL DEFAULT '',
                    area_id TEXT NOT NULL DEFAULT '',
                    push_enabled INTEGER NOT NULL DEFAULT 1,
                    cookie_valid INTEGER NOT NULL DEFAULT 1,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS action_runs (
                    run_key TEXT PRIMARY KEY,
                    qq_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_bind_expiry ON bind_sessions(expires_at);
                CREATE INDEX IF NOT EXISTS idx_run_created ON action_runs(created_at);
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
            if "xcommon_cipher" not in columns:
                conn.execute("ALTER TABLE accounts ADD COLUMN xcommon_cipher BLOB NOT NULL DEFAULT X''")
            if "user_agent" not in columns:
                conn.execute("ALTER TABLE accounts ADD COLUMN user_agent TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def parse_cookie(cookie: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for item in cookie.split(";"):
            if "=" not in item:
                continue
            name, value = item.strip().split("=", 1)
            if name:
                result[name] = value
        return result

    def create_bind_session(self, token: str, qq_id: str, ttl: int = 600) -> None:
        now = int(time.time())
        digest = self.token_hash(token)
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM bind_sessions WHERE expires_at < ?", (now,))
            conn.execute(
                "INSERT INTO bind_sessions(token_hash, qq_id, created_at, expires_at) VALUES(?,?,?,?)",
                (digest, str(qq_id), now, now + ttl),
            )

    def get_bind_session(self, token: str) -> dict[str, Any] | None:
        digest = self.token_hash(token)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM bind_sessions WHERE token_hash=?", (digest,)
            ).fetchone()
        return dict(row) if row else None

    def fail_bind_session(self, token: str, error: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE bind_sessions SET status='failed', error=? WHERE token_hash=?",
                (error[:240], self.token_hash(token)),
            )

    def consume_bind_session(
        self,
        token: str,
        cookie: str,
        game_uid: str,
        game_openid: str,
        nickname: str,
        role_name: str,
        area_id: str,
        x_common_params: str = "",
        user_agent: str = "",
    ) -> str:
        now = int(time.time())
        digest = self.token_hash(token)
        encrypted = self._cipher.encrypt(cookie.encode("utf-8"))
        encrypted_xcommon = self._cipher.encrypt(x_common_params.encode("utf-8")) if x_common_params else b""
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM bind_sessions WHERE token_hash=?", (digest,)
            ).fetchone()
            if not row or row["expires_at"] < now or row["used_at"] is not None:
                raise ValueError("绑定链接无效、已使用或已过期")
            qq_id = str(row["qq_id"])
            conn.execute(
                """
                INSERT INTO accounts(
                    qq_id,cookie_cipher,game_uid,game_openid,nickname,role_name,area_id,updated_at,xcommon_cipher,user_agent
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(qq_id) DO UPDATE SET
                    cookie_cipher=excluded.cookie_cipher,
                    game_uid=excluded.game_uid,
                    game_openid=excluded.game_openid,
                    nickname=excluded.nickname,
                    role_name=excluded.role_name,
                    area_id=excluded.area_id,
                    xcommon_cipher=excluded.xcommon_cipher,
                    user_agent=excluded.user_agent,
                    cookie_valid=1,
                    updated_at=excluded.updated_at
                """,
                (qq_id, encrypted, game_uid, game_openid, nickname, role_name, area_id, now, encrypted_xcommon, user_agent),
            )
            conn.execute(
                "UPDATE bind_sessions SET used_at=?, status='success', error='' WHERE token_hash=?",
                (now, digest),
            )
        return qq_id

    def get_account(self, qq_id: str, with_cookie: bool = True) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE qq_id=?", (str(qq_id),)).fetchone()
        if not row:
            return None
        account = dict(row)
        if with_cookie:
            try:
                account["cookie"] = self._cipher.decrypt(account.pop("cookie_cipher")).decode("utf-8")
                encrypted_xcommon = account.pop("xcommon_cipher", b"")
                account["x_common_params"] = (
                    self._cipher.decrypt(encrypted_xcommon).decode("utf-8") if encrypted_xcommon else ""
                )
            except InvalidToken as exc:
                raise RuntimeError("账号凭证无法解密，请重新绑定") from exc
        else:
            account.pop("cookie_cipher", None)
            account.pop("xcommon_cipher", None)
        return account

    def list_accounts(self, push_only: bool = False, with_cookie: bool = True) -> list[dict[str, Any]]:
        query = "SELECT qq_id FROM accounts"
        if push_only:
            query += " WHERE push_enabled=1"
        with self._lock, self._connect() as conn:
            ids = [r[0] for r in conn.execute(query).fetchall()]
        return [a for qq_id in ids if (a := self.get_account(qq_id, with_cookie))]

    def delete_account(self, qq_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM accounts WHERE qq_id=?", (str(qq_id),))
        return cur.rowcount > 0

    def set_push(self, qq_id: str, enabled: bool) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE accounts SET push_enabled=? WHERE qq_id=?",
                (1 if enabled else 0, str(qq_id)),
            )
        return cur.rowcount > 0

    def mark_cookie_invalid(self, qq_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE accounts SET cookie_valid=0 WHERE qq_id=?", (str(qq_id),))

    def set_setting(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, payload),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def claim_run(self, run_key: str, qq_id: str, action: str) -> bool:
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "INSERT INTO action_runs(run_key,qq_id,action,status,created_at) VALUES(?,?,?,'running',?)",
                    (run_key, str(qq_id), action, int(time.time())),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_run(self, run_key: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT run_key,qq_id,action,status,detail,created_at FROM action_runs WHERE run_key=?",
                (run_key,),
            ).fetchone()
        return dict(row) if row else None

    def retry_run(
        self,
        run_key: str,
        statuses: set[str],
        *,
        stale_after: int = 0,
    ) -> bool:
        """原子重领失败任务；也可回收超过指定秒数的运行中任务。"""
        allowed = sorted(str(status) for status in statuses)
        conditions: list[str] = []
        params: list[Any] = []
        if allowed:
            conditions.append("status IN (" + ",".join("?" for _ in allowed) + ")")
            params.extend(allowed)
        now = int(time.time())
        if stale_after > 0:
            conditions.append("(status='running' AND created_at<=?)")
            params.append(now - stale_after)
        if not conditions:
            return False
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE action_runs SET status='running',detail='',created_at=? "
                "WHERE run_key=? AND (" + " OR ".join(conditions) + ")",
                (now, run_key, *params),
            )
        return cursor.rowcount == 1

    def mark_stale_running_unknown(self, run_key: str, *, stale_after: int, detail: str) -> bool:
        """原子隔离过期写请求，不能将结果不明的任务重新领取。"""
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE action_runs SET status='unknown', detail=? "
                "WHERE run_key=? AND status='running' AND created_at<=?",
                (detail[:500], run_key, int(time.time()) - stale_after),
            )
        return cursor.rowcount == 1

    def finish_run(self, run_key: str, status: str, detail: str = "") -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE action_runs SET status=?, detail=? WHERE run_key=?",
                (status, detail[:500], run_key),
            )
