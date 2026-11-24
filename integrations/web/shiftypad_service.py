# SPDX-License-Identifier: GPL-3.0-or-later
"""ShiftyPad 只读导入的短时网页入口。

复用现有 aiohttp 站点与安全中间件；不建立独立站点、不使用 Cookie 登录态。
机器人私聊生成一次性短时 token，网页只能操作 token 对应的机器人用户。
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Mapping

from aiohttp import web

from ...features.shiftypad.identity import UidMappingResolver
from ...features.shiftypad.models import (
    ShiftypadPrivateError,
    ShiftypadProfile,
    ShiftypadUpstreamError,
)
from ...features.shiftypad.storage import ShiftypadReadOnlyStore

SESSIONS_KEY = "shiftypad_web_sessions_v1"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
SESSION_TTL = 600
PREVIEW_TTL = 300
MAX_SESSIONS = 200
MAX_BODY = 16 * 1024


def _json_error(code: str, message: str, status: int = 400, **extra: Any) -> web.Response:
    payload = {"ok": False, "code": code, "message": message, "error": message}
    payload.update(extra)
    return web.json_response(payload, status=status)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ShiftypadWebService:
    def __init__(
        self,
        *,
        store: Any,
        readonly: ShiftypadReadOnlyStore,
        resolver: UidMappingResolver,
        fetcher: Any,
        site_origin: str,
        clock=None,
        session_ttl: int = SESSION_TTL,
    ) -> None:
        self._store = store
        self._readonly = readonly
        self._resolver = resolver
        self._fetcher = fetcher
        self.site_origin = str(site_origin).rstrip("/")
        self._clock = clock or (lambda: time.time())
        self._session_ttl = session_ttl

    def _now(self) -> int:
        value = self._clock()
        return int(value.timestamp()) if isinstance(value, datetime) else int(value)

    def _sessions(self) -> dict[str, dict[str, Any]]:
        raw = self._store.get_setting(SESSIONS_KEY, {})
        if not isinstance(raw, dict):
            return {}
        now = self._now()
        cleaned = {
            key: value
            for key, value in raw.items()
            if isinstance(value, dict) and int(value.get("expires_at", 0)) > now
        }
        if len(cleaned) > MAX_SESSIONS:
            ordered = sorted(cleaned.items(), key=lambda item: item[1].get("created_at", 0))
            cleaned = dict(ordered[-MAX_SESSIONS:])
        return cleaned

    def _save_sessions(self, sessions: Mapping[str, Any]) -> None:
        self._store.set_setting(SESSIONS_KEY, dict(sessions))

    def create_link(self, actor_id: str) -> str:
        actor = str(actor_id or "").strip()
        if not actor:
            raise ValueError("缺少机器人用户标识")
        token = secrets.token_urlsafe(32)
        now = self._now()
        sessions = self._sessions()
        sessions[_token_hash(token)] = {
            "actor_id": actor,
            "created_at": now,
            "expires_at": now + self._session_ttl,
            "preview": None,
        }
        self._save_sessions(sessions)
        return f"{self.site_origin}/shiftypad/{token}"

    def _session(self, token: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if not TOKEN_RE.fullmatch(str(token or "")):
            return None, {}
        sessions = self._sessions()
        record = sessions.get(_token_hash(token))
        return (record, sessions) if isinstance(record, dict) else (None, sessions)

    def state(self, token: str) -> dict[str, Any]:
        record, _ = self._session(token)
        if record is None:
            return {"ok": False, "code": "EXPIRED", "status": "expired",
                    "message": "网页入口已过期，请回私聊重新发送 /妮姬 我的妮姬 导入"}
        actor = str(record.get("actor_id") or "")
        readonly = self._readonly.status(actor)
        remaining = max(0, int(record.get("expires_at", 0)) - self._now())
        return {
            "ok": True,
            "status": readonly["status"],
            "binding": readonly.get("binding"),
            "last_error": readonly.get("last_error", ""),
            "remaining_seconds": remaining,
            "uid_standalone_supported": False,
            "uid_mapping_available": self._resolver.available,
            "uid_note": (
                "数字 UID 不是 ShiftyPad OpenID；未发现受支持的公开 UID→OpenID 接口。"
                "请粘贴本人官方 ShiftyPad 公开链接，或由运营者导入可信 UID 映射。"
            ),
            "fallback_url": "https://www.blablalink.com/shiftyspad/home",
        }

    def _require_session(self, data: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any], web.Response | None]:
        token = str(data.get("token") or "")
        record, sessions = self._session(token)
        if record is None:
            return None, sessions, _json_error(
                "EXPIRED", "网页入口已过期，请回私聊重新获取", 410
            )
        return record, sessions, None

    async def preview(self, request: web.Request) -> web.Response:
        try:
            data = await request.json(loads=json.loads)
        except (ValueError, UnicodeDecodeError):
            return _json_error("INVALID_JSON", "请求格式无效")
        if not isinstance(data, Mapping):
            return _json_error("INVALID_JSON", "请求必须是对象")
        record, sessions, error = self._require_session(data)
        if error is not None:
            return error
        if data.get("confirmed_public") is not True:
            return _json_error("PUBLIC_CONFIRM_REQUIRED", "请先确认该档案已对所有人公开并获得本人授权")
        uid = str(data.get("uid") or "").strip()
        server = str(data.get("server") or "").strip()
        public_ref = str(data.get("public_ref") or "").strip()
        if len(uid) > 32 or len(server) > 32 or len(public_ref) > 512:
            return _json_error("INVALID_INPUT", "输入长度超出限制")
        resolution = self._resolver.resolve(uid, server, public_reference=public_ref)
        if resolution.status != "resolved" or resolution.identity is None:
            return _json_error(
                "UID_UNRESOLVED",
                resolution.reason or "无法解析该 UID/公开链接",
                400,
                fallback_url=resolution.fallback_url,
                uid_standalone_supported=resolution.uid_standalone,
            )
        try:
            profile = await self._fetcher.fetch(resolution.identity)
        except ShiftypadPrivateError as exc:
            return _json_error("PRIVATE", str(exc), 403)
        except ShiftypadUpstreamError as exc:
            return _json_error("UPSTREAM", str(exc), 502)
        except Exception as exc:
            return _json_error("UPSTREAM", f"读取公开档案失败（{type(exc).__name__}）", 502)
        preview_id = secrets.token_urlsafe(18)
        stored_profile = profile.to_dict(include_identity=True)
        stored_profile["identity"] = {
            "openid": profile.identity.openid,
            "uid": profile.identity.uid,
            "server": profile.identity.server,
            "area_id": profile.identity.area_id,
            "source": profile.identity.source,
            "source_url": profile.identity.source_url,
        }
        record["preview"] = {
            "id": preview_id,
            "profile": stored_profile,
            "expires_at": self._now() + PREVIEW_TTL,
        }
        sessions[_token_hash(str(data.get("token")))] = record
        self._save_sessions(sessions)
        payload = profile.to_dict(include_identity=False)
        payload["identity"] = {
            "uid": profile.identity.uid,
            "server": profile.identity.server,
            "area_id": profile.identity.area_id,
            "source": profile.identity.source,
            "source_url": profile.identity.source_url,
        }
        payload.update(
            {
                "ok": True,
                "preview_id": preview_id,
                "expires_in": PREVIEW_TTL,
                "warnings": [
                    "只读导入不会获得登录、私有账号或角色库写入权限。",
                    "需要 ShiftyPad 的持有妮姬与前哨对所有人可见；未公开会拒绝导入。",
                    "数字 UID 仅作本人标注；可查询身份来自公开链接或可信映射。",
                ],
            }
        )
        return web.json_response(payload)

    async def bind(self, request: web.Request) -> web.Response:
        try:
            data = await request.json(loads=json.loads)
        except (ValueError, UnicodeDecodeError):
            return _json_error("INVALID_JSON", "请求格式无效")
        if not isinstance(data, Mapping):
            return _json_error("INVALID_JSON", "请求必须是对象")
        record, sessions, error = self._require_session(data)
        if error is not None:
            return error
        preview = record.get("preview")
        if not isinstance(preview, Mapping) or int(preview.get("expires_at", 0)) < self._now():
            return _json_error("PREVIEW_EXPIRED", "预览已过期，请重新检查资料")
        if str(data.get("preview_id") or "") != str(preview.get("id") or ""):
            return _json_error("PREVIEW_MISMATCH", "预览标识不匹配，请重新检查")
        try:
            profile = ShiftypadProfile.from_dict(preview.get("profile") or {})
        except (TypeError, ValueError):
            return _json_error("INVALID_PREVIEW", "预览数据损坏，请重新检查")
        binding = self._readonly.bind(str(record.get("actor_id") or ""), profile)
        record["preview"] = None
        sessions[_token_hash(str(data.get("token")))] = record
        self._save_sessions(sessions)
        return web.json_response({"ok": True, "status": binding.public_dict()})

    async def sync(self, request: web.Request) -> web.Response:
        try:
            data = await request.json(loads=json.loads)
        except (ValueError, UnicodeDecodeError):
            return _json_error("INVALID_JSON", "请求格式无效")
        if not isinstance(data, Mapping):
            return _json_error("INVALID_JSON", "请求必须是对象")
        record, _, error = self._require_session(data)
        if error is not None:
            return error
        outcome = await self._readonly.sync(str(record.get("actor_id") or ""), self._fetcher)
        state = self._readonly.status(str(record.get("actor_id") or ""))
        if not outcome.ok:
            return web.json_response(
                {
                    "ok": False,
                    "code": outcome.error_code,
                    "message": outcome.message,
                    "status": state["status"],
                    "binding": state.get("binding"),
                },
                status=409 if outcome.error_code == "PRIVATE" else 502,
            )
        return web.json_response(
            {
                "ok": True,
                "changed": outcome.changed,
                "message": outcome.message,
                "status": state["status"],
                "binding": state.get("binding"),
            }
        )

    async def unbind(self, request: web.Request) -> web.Response:
        try:
            data = await request.json(loads=json.loads)
        except (ValueError, UnicodeDecodeError):
            return _json_error("INVALID_JSON", "请求格式无效")
        if not isinstance(data, Mapping):
            return _json_error("INVALID_JSON", "请求必须是对象")
        record, _, error = self._require_session(data)
        if error is not None:
            return error
        self._readonly.unbind(str(record.get("actor_id") or ""))
        return web.json_response({"ok": True, "status": "unbound"})

    async def page(self, request: web.Request) -> web.Response:
        token = str(request.match_info.get("token") or "")
        record, _ = self._session(token)
        if record is None:
            return web.Response(
                text=render_expired_page(),
                content_type="text/html",
                status=410,
            )
        return web.Response(
            text=render_page(token),
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    def mount(self, app: web.Application) -> None:
        app.router.add_get("/shiftypad/{token}", self.page)
        app.router.add_get("/api/shiftypad/state", self.state_route)
        app.router.add_post("/api/shiftypad/preview", self.preview)
        app.router.add_post("/api/shiftypad/bind", self.bind)
        app.router.add_post("/api/shiftypad/sync", self.sync)
        app.router.add_post("/api/shiftypad/unbind", self.unbind)

    async def state_route(self, request: web.Request) -> web.Response:
        return web.json_response(self.state(str(request.query.get("token") or "")))


def render_page(token: str) -> str:
    safe_token = html.escape(token, quote=True)
    token_json = json.dumps(token, ensure_ascii=True).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'">
<title>NIKKE · ShiftyPad 只读导入</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;padding:18px;background:#111318;color:#f2f3f5;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;line-height:1.55}}
main{{max-width:620px;margin:0 auto;background:#1a1e25;border:1px solid #343b46;border-top:4px solid #e9b85a;border-radius:12px;padding:22px 18px}}
h1{{font-size:22px;margin:0 0 6px}}p{{color:#b9c0cc;font-size:14px}}.badge{{display:inline-block;padding:2px 8px;border-radius:6px;background:#26303d;color:#e9b85a;font-size:12px}}
label{{display:block;margin:14px 0 4px;font-size:13px;color:#d8dde5}}input,select{{width:100%;padding:11px 12px;border-radius:8px;border:1px solid #3a4350;background:#11151c;color:#fff;font-size:15px}}
button{{margin-top:12px;padding:11px 14px;border:0;border-radius:8px;background:#e9b85a;color:#20170a;font-weight:700;font-size:15px;cursor:pointer}}button.secondary{{background:#2a3340;color:#d8dde5}}button.danger{{background:#4a2528;color:#ffd6d8}}button:disabled{{opacity:.5}}
.row{{display:flex;gap:8px;flex-wrap:wrap}}.row button{{flex:1;min-width:120px}}.note{{font-size:12px;color:#98a2b1}}.warn{{border:1px solid #6b5424;background:#2a2417;border-radius:8px;padding:10px 12px;font-size:13px;color:#f0d9a7}}
.card{{margin-top:14px;border:1px solid #343d4b;border-radius:10px;padding:12px;background:#141922}}.muted{{color:#98a2b1;font-size:13px}}.ok{{color:#8ee6a8}}.err{{color:#ff9da4}}a{{color:#f0c570}}
</style></head><body><main>
<h1>ShiftyPad 只读导入</h1>
<p><span class="badge">只读</span> 不登录、不写入游戏账号；仅导入你本人确认公开的档案。</p>
<div id="msg" class="muted">正在读取入口状态…</div>
<div id="bound" class="card" hidden></div>
<div id="form-wrap">
  <div class="warn">数字 UID 与 ShiftyPad 的长 OpenID 不是同一种 ID。仅填数字 UID 时，只有运营者已导入可信映射才能继续；否则请粘贴本人官方 ShiftyPad 公开链接。<br>本流程不验证账号所有权，只保存明确标注的公开只读快照，不授予登录或私有权限。</div>
  <label for="uid">游戏 UID（数字，仅本人标注）</label>
  <input id="uid" inputmode="numeric" autocomplete="off" placeholder="例如 123456789">
  <label for="server">区服</label>
  <select id="server"><option value="">请选择</option><option value="global">国际服</option><option value="jp">日服</option><option value="kr">韩服</option><option value="na">北美服</option><option value="sea">东南亚服</option><option value="cn">国服</option></select>
  <label for="public_ref">官方 ShiftyPad 公开链接或 OpenID（推荐）</label>
  <input id="public_ref" autocomplete="off" placeholder="https://www.blablalink.com/shiftyspad/... 或 12345-1234567890">
  <label style="display:flex;gap:8px;align-items:flex-start;margin-top:14px"><input id="confirm" type="checkbox" style="width:auto;margin-top:4px"> <span>我确认该档案已对所有人公开，且我是本人或已获本人授权进行只读导入。</span></label>
  <button id="preview">检查资料</button>
  <div id="preview-box" class="card" hidden></div>
</div>
<p class="note">入口 10 分钟内有效；过期请回私聊重新发送 <code>/妮姬 我的妮姬 导入</code>。原有账号登录/扩展绑定不受影响。</p>
</main>
<script>
const TOKEN={token_json};
const $=id=>document.getElementById(id);
const msg=(text,cls='')=>{{$('msg').textContent=text;$('msg').className='muted '+cls}};
const text=(el,value)=>{{el.textContent=value==null?'未知':String(value)}};
async function api(path,body){{
  const r=await fetch(path,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(Object.assign({{token:TOKEN}},body||{{}}))}});
  let data={{}};try{{data=await r.json()}}catch(e){{data={{ok:false,message:'响应格式错误'}}}}
  if(!r.ok||data.ok===false){{const e=new Error(data.message||('HTTP '+r.status));e.data=data;throw e}}
  return data;
}}
function showBinding(b){{
  const box=$('bound');box.hidden=false;box.textContent='';
  const title=document.createElement('div');title.className='ok';title.textContent='只读快照：'+(b.nickname||'未知');box.appendChild(title);
  const lines=[['等级',b.level],['队伍总战力',b.team_combat],['角色数',b.nikke_count],['同步器',b.synchro_level],['普通主线',b.normal_stage],['困难主线',b.hard_stage],['同步时间',b.last_sync_at]];
  lines.forEach(([k,v])=>{{const p=document.createElement('div');p.className='muted';p.textContent=k+'：'+(v==null||v===''?'未知':v);box.appendChild(p)}});
  if(b.stale){{const p=document.createElement('div');p.className='err';p.textContent='公开状态或上游异常，当前为旧快照';box.appendChild(p)}}
  const row=document.createElement('div');row.className='row';
  const sync=document.createElement('button');sync.textContent='同步最新公开资料';sync.onclick=doSync;
  const un=document.createElement('button');un.className='danger';un.textContent='解绑只读资料';un.onclick=doUnbind;
  row.append(sync,un);box.appendChild(row);
}}
async function load(){{
  try{{
    const r=await fetch('/api/shiftypad/state?token='+encodeURIComponent(TOKEN));
    const s=await r.json();
    if(!s.ok){{msg(s.message||'入口不可用','err');$('form-wrap').hidden=true;return}}
    if(s.status==='ready'||s.status==='stale'){{msg('已建立只读绑定','ok');showBinding(s.binding||{{}});$('form-wrap').hidden=true;return}}
    msg('尚未绑定。填写下方资料并检查公开档案。');
  }}catch(e){{msg('入口读取失败：'+e.message,'err')}}
}}
async function doPreview(){{
  if(!$('confirm').checked){{msg('请先勾选公开与授权确认','err');return}}
  const btn=$('preview');btn.disabled=true;msg('正在检查公开档案…');
  try{{
    const d=await api('/api/shiftypad/preview',{{uid:$('uid').value.trim(),server:$('server').value,public_ref:$('public_ref').value.trim(),confirmed_public:true}});
    const box=$('preview-box');box.hidden=false;box.textContent='';
    const title=document.createElement('div');title.className='ok';title.textContent='公开预览：'+(d.nickname||'未知');box.appendChild(title);
    [['等级',d.level],['队伍总战力',d.team_combat],['角色数',d.nikke_count],['同步器',d.synchro_level],['身份来源',d.identity&&d.identity.source]].forEach(([k,v])=>{{const p=document.createElement('div');p.className='muted';p.textContent=k+'：'+(v==null||v===''?'未知':v);box.appendChild(p)}});
    (d.warnings||[]).forEach(w=>{{const p=document.createElement('div');p.className='warn';p.textContent=w;box.appendChild(p)}});
    const b=document.createElement('button');b.textContent='确认绑定只读资料';b.onclick=()=>doBind(d.preview_id);box.appendChild(b);
    $('preview').hidden=true;msg('检查完成，请确认预览后绑定。','ok');
  }}catch(e){{msg(e.message,'err');if(e.data&&e.data.fallback_url){{const a=document.createElement('a');a.href=e.data.fallback_url;a.target='_blank';a.rel='noopener';a.textContent='打开官方 ShiftyPad';msg(e.message+' ','err');$('msg').appendChild(a)}}}}finally{{btn.disabled=false}}
}}
async function doBind(id){{
  try{{const d=await api('/api/shiftypad/bind',{{preview_id:id}});showBinding(d.status||{{}});$('form-wrap').hidden=true;msg('已建立只读绑定','ok')}}catch(e){{msg(e.message,'err')}}
}}
async function doSync(){{
  msg('正在同步公开资料…');
  try{{const d=await api('/api/shiftypad/sync');showBinding(d.binding||{{}});msg(d.message||'同步完成',d.changed?'ok':'')}}catch(e){{msg(e.message,'err');if(e.data&&e.data.binding)showBinding(e.data.binding)}}
}}
async function doUnbind(){{
  if(!confirm('确认解绑只读资料？不会影响原账号登录绑定。'))return;
  try{{await api('/api/shiftypad/unbind');$('bound').hidden=true;$('form-wrap').hidden=false;$('preview').hidden=false;$('preview-box').hidden=true;msg('已解绑只读资料')}}catch(e){{msg(e.message,'err')}}
}}
$('preview').onclick=doPreview;load();
</script></body></html>"""


def render_expired_page() -> str:
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>入口已过期</title></head><body style="background:#111318;color:#f2f3f5;font-family:sans-serif;padding:24px"><h1>入口已过期</h1><p>请回到机器人私聊，重新发送 <code>/妮姬 我的妮姬 导入</code> 获取新的短时入口。</p></body></html>"""


__all__ = ["SESSIONS_KEY", "ShiftypadWebService", "render_expired_page", "render_page"]
