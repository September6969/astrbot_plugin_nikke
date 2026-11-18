"""有界内存会话，重启后安全失效。"""

import asyncio
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class ArenaSession:
    actor_id: str
    created: float
    accessed: float
    csrf: str
    mode: str
    draft: dict = field(default_factory=dict)
    revision: int = 0
    result: Any = None
    submissions: dict = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    requests: list[float] = field(default_factory=list)


class ArenaSessionStore:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic, capacity: int = 128):
        self.clock = clock
        self.capacity = capacity
        self.links: dict[str, tuple[str, float, str]] = {}
        self.sessions: dict[str, ArenaSession] = {}
        self.results: dict[str, tuple[float, Any]] = {}

    def clean(self) -> None:
        now = self.clock()
        self.links = {key: value for key, value in self.links.items() if now < value[1]}
        self.sessions = {key: value for key, value in self.sessions.items()
                         if now - value.created < 3600 and now - value.accessed < 1800}
        self.results = {key: value for key, value in self.results.items() if now - value[0] < 7200}

    def create_link(self, actor_id: str, mode: str = "single") -> str:
        self.clean()
        if mode not in {"single", "three"} or not actor_id:
            raise ValueError("编辑会话参数无效。")
        # 同一用户重新申请时撤销尚未兑换的旧链接。
        self.links = {key: value for key, value in self.links.items() if value[0] != actor_id}
        if len(self.links) >= self.capacity:
            raise ValueError("编辑链接已满，请稍后重试。")
        token = secrets.token_urlsafe(32)
        self.links[digest(token)] = (actor_id, self.clock() + 900, mode)
        return token

    def claim(self, token: str) -> str:
        self.clean()
        link = self.links.get(digest(token))
        if link is None:
            raise ValueError("链接已过期或已兑换，请回 QQ 获取新链接。")
        if len(self.sessions) >= self.capacity:
            raise ValueError("编辑会话已满，请稍后重试。")
        del self.links[digest(token)]
        cookie = secrets.token_urlsafe(32)
        now = self.clock()
        self.sessions[digest(cookie)] = ArenaSession(link[0], now, now, secrets.token_urlsafe(32), link[2])
        return cookie

    def get(self, cookie: str, *, touch: bool = True) -> ArenaSession:
        self.clean()
        session = self.sessions.get(digest(cookie))
        if session is None:
            raise ValueError("编辑会话已过期，请回 QQ 获取新链接。")
        if touch:
            session.accessed = self.clock()
        return session

    def save_result(self, session: ArenaSession, result: Any) -> None:
        self.clean()
        session.result = result
        if session.actor_id not in self.results and len(self.results) >= self.capacity:
            oldest = min(self.results, key=lambda actor: self.results[actor][0])
            del self.results[oldest]
        self.results[session.actor_id] = (self.clock(), result)

    def latest(self, actor_id: str):
        self.clean()
        entry = self.results.get(actor_id)
        return entry[1] if entry else None

    def revoke(self, cookie: str) -> None:
        self.sessions.pop(digest(cookie), None)

    def clear(self) -> None:
        self.links.clear()
        self.sessions.clear()
        self.results.clear()
