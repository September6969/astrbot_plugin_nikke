"use strict";
const $ = (id) => document.getElementById(id);
let csrf = "";

const msg = (text, cls = "") => {
  const el = $("msg");
  el.textContent = text;
  el.className = cls ? "muted " + cls : "muted";
};

async function api(path, body) {
  const options = {
    method: body === undefined ? "GET" : "POST",
    credentials: "same-origin",
    headers: {},
  };
  if (body !== undefined) {
    options.headers = {
      "Content-Type": "application/json",
      "X-Shiftypad-CSRF": csrf,
    };
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  let data = {};
  try {
    data = await response.json();
  } catch (_err) {
    data = {ok: false, message: "响应格式错误"};
  }
  if (!response.ok || data.ok === false) {
    const err = new Error(data.message || data.error || ("HTTP " + response.status));
    err.status = response.status;
    err.data = data;
    throw err;
  }
  return data;
}

function showBinding(b) {
  const box = $("bound");
  box.hidden = false;
  box.textContent = "";
  const title = document.createElement("div");
  title.className = "ok";
  title.textContent = "只读快照：" + (b.nickname || "未知");
  box.appendChild(title);
  const lines = [
    ["等级", b.level],
    ["队伍总战力", b.team_combat],
    ["角色数", b.nikke_count],
    ["同步器", b.synchro_level],
    ["普通主线", b.normal_stage],
    ["困难主线", b.hard_stage],
    ["同步时间", b.last_sync_at],
  ];
  lines.forEach(([k, v]) => {
    const p = document.createElement("div");
    p.className = "muted";
    p.textContent = k + "：" + (v == null || v === "" ? "未知" : v);
    box.appendChild(p);
  });
  if (b.stale) {
    const p = document.createElement("div");
    p.className = "err";
    p.textContent = "公开状态或上游异常，当前为旧快照，仍可点击同步重试";
    box.appendChild(p);
  }
  const row = document.createElement("div");
  row.className = "row";
  const syncBtn = document.createElement("button");
  syncBtn.type = "button";
  syncBtn.textContent = "同步最新公开资料";
  syncBtn.addEventListener("click", doSync);
  const unbindBtn = document.createElement("button");
  unbindBtn.type = "button";
  unbindBtn.className = "danger";
  unbindBtn.textContent = "解绑只读资料";
  unbindBtn.addEventListener("click", doUnbind);
  const revokeBtn = document.createElement("button");
  revokeBtn.type = "button";
  revokeBtn.className = "secondary";
  revokeBtn.textContent = "结束本次网页会话";
  revokeBtn.addEventListener("click", doRevoke);
  row.append(syncBtn, unbindBtn, revokeBtn);
  box.appendChild(row);
}

async function load() {
  try {
    const s = await api("/shiftypad/api/state");
    csrf = s.csrf || "";
    if (s.status === "ready" || s.status === "stale") {
      msg("已建立只读绑定", "ok");
      showBinding(s.binding || {});
      $("form-wrap").hidden = true;
      return;
    }
    msg("尚未绑定。填写下方资料并检查公开档案。");
  } catch (e) {
    msg("入口读取失败：" + e.message, "err");
    if (e.status === 401 || e.status === 410) {
      $("form-wrap").hidden = true;
    }
  }
}

async function doPreview() {
  if (!$("confirm").checked) {
    msg("请先勾选公开与授权确认", "err");
    return;
  }
  const btn = $("preview");
  btn.disabled = true;
  msg("正在检查公开档案…");
  try {
    const d = await api("/shiftypad/api/preview", {
      uid: $("uid").value.trim(),
      server: $("server").value,
      public_ref: $("public_ref").value.trim(),
      confirmed_public: true,
    });
    const box = $("preview-box");
    box.hidden = false;
    box.textContent = "";
    const title = document.createElement("div");
    title.className = "ok";
    title.textContent = "公开预览：" + (d.nickname || "未知");
    box.appendChild(title);
    [
      ["等级", d.level],
      ["队伍总战力", d.team_combat],
      ["角色数", d.nikke_count],
      ["同步器", d.synchro_level],
      ["身份来源", d.identity && d.identity.source],
    ].forEach(([k, v]) => {
      const p = document.createElement("div");
      p.className = "muted";
      p.textContent = k + "：" + (v == null || v === "" ? "未知" : v);
      box.appendChild(p);
    });
    (d.warnings || []).forEach((w) => {
      const p = document.createElement("div");
      p.className = "warn";
      p.textContent = w;
      box.appendChild(p);
    });
    const bindBtn = document.createElement("button");
    bindBtn.type = "button";
    bindBtn.textContent = "确认绑定只读资料";
    bindBtn.addEventListener("click", () => doBind(d.preview_id));
    box.appendChild(bindBtn);
    $("preview").hidden = true;
    msg("检查完成，请确认预览后绑定。", "ok");
  } catch (e) {
    msg(e.message, "err");
    if (e.data && e.data.fallback_url) {
      const a = document.createElement("a");
      a.href = e.data.fallback_url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = "打开官方 ShiftyPad";
      msg(e.message + " ", "err");
      $("msg").appendChild(a);
    }
  } finally {
    btn.disabled = false;
  }
}

async function doBind(id) {
  try {
    const d = await api("/shiftypad/api/bind", {preview_id: id});
    showBinding(d.status || {});
    $("form-wrap").hidden = true;
    msg("已建立只读绑定", "ok");
  } catch (e) {
    msg(e.message, "err");
  }
}

async function doSync() {
  msg("正在同步公开资料…");
  try {
    const d = await api("/shiftypad/api/sync", {});
    showBinding(d.binding || {});
    msg(d.message || "同步完成", d.changed ? "ok" : "");
  } catch (e) {
    msg(e.message, "err");
    if (e.data && e.data.binding) showBinding(e.data.binding);
  }
}

async function doUnbind() {
  if (!window.confirm("确认解绑只读资料？不会影响原账号登录绑定。")) return;
  try {
    await api("/shiftypad/api/unbind", {});
    $("bound").hidden = true;
    $("form-wrap").hidden = false;
    $("preview").hidden = false;
    $("preview-box").hidden = true;
    msg("已解绑只读资料");
  } catch (e) {
    msg(e.message, "err");
  }
}

async function doRevoke() {
  try {
    await api("/shiftypad/api/revoke", {});
    $("bound").hidden = true;
    $("form-wrap").hidden = true;
    msg("已结束本次网页会话；如需继续操作，请回私聊重新获取入口。");
  } catch (e) {
    msg(e.message, "err");
  }
}

$("preview").addEventListener("click", doPreview);
load();
