"""候选凭证的 Cookie 作用域和属性；不把本地到期时间当作服务端续期证明。"""
from __future__ import annotations

from datetime import timezone
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from urllib.parse import urlsplit
import math
import re


LOGIN_FIELDS = {"game_openid", "game_channelid", "game_token", "game_id", "game_expire_time",
                "game_uid", "game_user_name", "game_user_region", "game_adult_status"}
REQUIRED_FIELDS = {"game_openid", "game_channelid", "game_token", "game_id", "game_expire_time", "game_uid"}
COOKIE_FIELDS = {"name", "value", "domain", "path", "secure", "httpOnly", "sameSite",
                 "expirationDate", "session", "hostOnly", "raw_attributes"}
NAME = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def cookie_header(cookies, url, now):
    host = urlsplit(url).hostname
    path = urlsplit(url).path or "/"
    selected = {}
    for item in cookies:
        domain = str(item.get("domain") or "").lower().lstrip(".")
        cpath = str(item.get("path") or "/")
        if not domain or not (host == domain or not item.get("hostOnly", True) and host.endswith("." + domain)):
            continue
        if not path.startswith(cpath) or not (cpath.endswith("/") or path == cpath or path[len(cpath):].startswith("/")):
            continue
        expiry = item.get("expirationDate")
        if expiry is not None and float(expiry) <= now:
            continue
        name, value = item.get("name"), item.get("value")
        if not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(value, str) or any(c in value for c in "\r\n;"):
            raise ValueError("Cookie 格式不完整")
        if name in selected and selected[name] != value:
            raise ValueError("Cookie 同名作用域不明确")
        selected[name] = value
    return "; ".join(f"{name}={value}" for name, value in selected.items())


def capture_material(cookies, login_payload=None):
    """绑定时只保存官方域 Cookie 属性及用户额外选择保留的白名单登录字段。"""
    result = []
    if not isinstance(cookies, list) or len(cookies) > 128:
        raise ValueError("Cookie 列表不完整")
    for item in cookies:
        if not isinstance(item, dict):
            raise ValueError("Cookie 属性不完整")
        domain = str(item.get("domain") or "").lower().lstrip(".")
        if domain != "blablalink.com" and not domain.endswith(".blablalink.com"):
            continue
        if not isinstance(item.get("name"), str) or not NAME.fullmatch(item["name"]):
            raise ValueError("Cookie 名称不合法")
        if item.get("expirationDate") is not None and (
                type(item["expirationDate"]) not in (int, float) or not math.isfinite(item["expirationDate"])):
            raise ValueError("Cookie 有效期无效")
        result.append({k: v for k, v in item.items() if k in COOKIE_FIELDS})
    payload = {}
    if login_payload is not None:
        if not isinstance(login_payload, dict) or set(login_payload) - LOGIN_FIELDS:
            raise ValueError("登录材料包含非白名单字段")
        if any(type(v) not in (str, int) or len(str(v)) > 4096 for v in login_payload.values()):
            raise ValueError("登录材料字段格式无效")
        payload = dict(login_payload)
    return {"cookies": result, "login_payload": payload, "source": "official-login-request-v1" if payload else "cookies-only"}


def renewal_payload(account, now):
    material = account.get("session_material") or {}
    payload = material.get("login_payload") or {}
    if material.get("source") != "official-login-request-v1" or not REQUIRED_FIELDS.issubset(payload):
        raise ValueError("缺少官方登录原始字段与有效期；请在新版扩展明确选择保留续期材料后重新登录并绑定")
    if set(payload) - LOGIN_FIELDS or any(payload[k] in (None, "") for k in REQUIRED_FIELDS):
        raise ValueError("续期字段不完整")
    for key in ("game_channelid", "game_expire_time"):
        if type(payload[key]) is not int or payload[key] <= 0:
            raise ValueError("续期数值字段未经确认")
    if payload["game_expire_time"] <= now:
        raise ValueError("官方登录令牌已到期，不能承诺恢复，请重新登录")
    values = dict(part.strip().split("=", 1) for part in str(account.get("cookie") or "").split(";") if "=" in part)
    for name in ("game_token", "game_openid", "game_uid"):
        if not isinstance(payload[name], str) or not payload[name] or payload[name] != values.get(name):
            raise ValueError("官方登录字段与当前会话不一致，请重新登录绑定")
    return dict(payload)


def apply_set_cookies(material, headers, now):
    """逐条读取 Set-Cookie，保留作用域、属性、会话和删除语义，不伪造期限。"""
    cookies = {(c["name"], c["domain"].lower().lstrip("."), c.get("path", "/")): dict(c)
               for c in material.get("cookies", [])}
    changed = False
    token_returned = False
    for header in headers:
        parsed = SimpleCookie()
        parsed.load(header)
        if not parsed:
            raise ValueError("续期 Cookie 响应结构变化")
        for name, value in parsed.items():
            if not NAME.fullmatch(name):
                raise ValueError("续期 Cookie 名称不合法")
            domain = value["domain"].lower().lstrip(".") or "api.blablalink.com"
            # 接口不能为无关域或其他 BlaBlaLink 子域设置 Cookie。
            if domain not in {"blablalink.com", "api.blablalink.com"}:
                raise ValueError("续期 Cookie 域不合法")
            path = value["path"] or "/api/user"
            if not path.startswith("/"):
                raise ValueError("续期 Cookie 路径不合法")
            item = {"name": name, "value": value.value, "domain": value["domain"] or "api.blablalink.com",
                    "hostOnly": not bool(value["domain"]), "path": path, "secure": bool(value["secure"]),
                    "httpOnly": bool(value["httponly"]), "sameSite": value["samesite"],
                    "session": not bool(value["max-age"] or value["expires"]), "raw_attributes": header}
            if value["max-age"]:
                item["expirationDate"] = now + int(value["max-age"])
            elif value["expires"]:
                expires = parsedate_to_datetime(value["expires"])
                item["expirationDate"] = expires.replace(tzinfo=expires.tzinfo or timezone.utc).timestamp()
            key = (name, domain, path)
            if item.get("expirationDate", now + 1) <= now or not item["value"]:
                cookies.pop(key, None)
            else:
                changed |= cookies.get(key) != item
                cookies[key] = item
                token_returned |= name == "game_token"
    if not changed or not token_returned:
        raise ValueError("未返回新的有效会话 Cookie，保留原凭证")
    return {**material, "cookies": list(cookies.values())}
