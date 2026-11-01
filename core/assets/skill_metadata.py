"""从官网公开资料同步角色技能图标标识，保留最后一次有效缓存。"""
from __future__ import annotations
import json
import logging
import re
import threading
import time
from pathlib import Path
import httpx
from .resource_url import game_resource_url

log = logging.getLogger("nikke.asset_manager")

class SkillMetadata:
    TTL = 86400
    RETRY = 120

    def __init__(self, cache_dir, *, fetch=None, clock=time.time):
        self.root = Path(cache_dir) / "character-skills"
        self.fetch = fetch or self._fetch
        self.clock = clock
        self.lock = threading.Lock()
        self.next_attempt = {}

    @staticmethod
    def _fetch(url):
        # 只访问公开 CDN，不携带账号或 Cookie。
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=True) as client:
            response = client.get(url)
            response.raise_for_status()
            if len(response.content) > 2 * 1024 * 1024:
                raise ValueError("角色资料超过大小上限")
            return response.json()

    @staticmethod
    def parse(data, rid):
        if not isinstance(data, dict) or str(data.get("resource_id")) != rid:
            raise ValueError("角色资料身份不匹配")
        skills = {}
        for slot, field in (("skill1", "skill1_detail"), ("skill2", "skill2_detail"), ("burst", "ulti_skill_detail")):
            detail = data.get(field)
            name = detail.get("icon") if isinstance(detail, dict) else None
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,128}", name):
                raise ValueError("技能图标字段不完整")
            skills[slot] = name
        return skills

    def resolve(self, resource_id, fallback, *, remote=True):
        rid = str(resource_id)
        if not re.fullmatch(r"[0-9]{1,10}", rid):
            return fallback
        with self.lock:
            path = self.root / (rid + ".json")
            cached, stamp = fallback, 0
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                cached = self.parse(saved["data"], rid)
                stamp = float(saved["fetched_at"])
            except (OSError, ValueError, TypeError, KeyError):
                pass
            now = self.clock()
            if not remote or 0 <= now-stamp < self.TTL or now < self.next_attempt.get(rid, 0):
                return cached
            self.next_attempt[rid] = now + self.RETRY
            try:
                url = game_resource_url(f"roledata/{rid}-v2-en.json")
                data = self.fetch(url)
                skills = self.parse(data, rid)
                self.root.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps({"fetched_at": now, "source_url": url, "data": data}, ensure_ascii=False), encoding="utf-8")
                temporary.replace(path)
                return skills
            except (httpx.HTTPError, OSError, ValueError, TypeError):
                log.warning("角色技能资料同步失败 resource_id=%s，保留已有数据", rid)
                return cached
