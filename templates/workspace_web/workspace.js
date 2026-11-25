"use strict";

(() => {
  const state = {
    csrf: "",
    lastProfileText: "",
    lastSoloText: "",
    lastArenaText: "",
    shareTargetAvailable: false,
    confirmToken: "",
    bindToken: "",
  };

  function el(id) {
    return document.getElementById(id);
  }

  function showToast(msg) {
    const toast = el("toast");
    toast.textContent = msg;
    toast.hidden = false;
    setTimeout(() => { toast.hidden = true; }, 2200);
  }

  function newKey(prefix) {
    return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
  }

  async function apiFetch(url, options = {}) {
    const headers = Object.assign({ "Accept": "application/json" }, options.headers || {});
    if (options.method && options.method !== "GET" && state.csrf) {
      headers["X-Workspace-CSRF"] = state.csrf;
    }
    const resp = await fetch(url, Object.assign({ credentials: "same-origin" }, options, { headers }));
    const data = await resp.json().catch(() => ({ ok: false, error: "响应解析失败" }));
    if (!resp.ok) {
      throw new Error(data.message || data.error || `请求失败 (${resp.status})`);
    }
    return data;
  }

  function switchTab(tabId) {
    document.querySelectorAll(".tab").forEach((b) => {
      const active = b.dataset.tab === tabId;
      b.classList.toggle("active", active);
      b.setAttribute("aria-selected", active ? "true" : "false");
    });
    document.querySelectorAll(".tab-panel").forEach((p) => {
      p.classList.toggle("active", p.id === `tab-${tabId}`);
    });
  }

  function renderBindSummary(b) {
    const box = el("bind-summary");
    if (!b || !b.bound) {
      box.textContent = "当前尚未绑定 BlaBlaLink 账号。点击右上角「生成 / 刷新绑定链接」按向导自助绑定。";
      return;
    }
    box.textContent = `已绑定：${b.nickname} | 服务器 ${b.area_id || "?"} | 尾号 ${b.masked_uid || "***"} | 凭据状态：${b.cookie_valid ? "有效" : "已过期需重绑"} | 每日汇总：${b.push_enabled ? "开启" : "关闭"}`;
  }

  async function openSharePreview(kind, text) {
    if (!text) return;
    try {
      const data = await apiFetch("/workspace/api/share/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, text }),
      });
      state.confirmToken = data.confirm_token;
      el("share-target-line").textContent = `发送目标：${data.target_label}`;
      el("share-redaction-line").textContent = data.redaction_notes?.length
        ? `自动脱敏：${data.redaction_notes.join("、")}`
        : "未检测到敏感凭据或长数字 UID。";
      el("share-preview-box").textContent = data.preview_text;
      el("share-confirm-status").textContent = "";
      el("share-dialog").showModal();
    } catch (err) {
      showToast(err.message);
    }
  }

  async function init() {
    const data = await apiFetch("/workspace/api/bootstrap");
    state.csrf = data.csrf || "";
    state.shareTargetAvailable = Boolean(data.share_target?.available);
    el("session-meta").textContent = `指挥官 ${data.actor_label} ｜ QQ 分享目标：${data.share_target?.label || "无"}`;
    renderBindSummary(data.binding);
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".tab").forEach((b) => {
      b.addEventListener("click", () => switchTab(b.dataset.tab));
    });

    el("btn-revoke")?.addEventListener("click", async () => {
      await apiFetch("/workspace/api/revoke", { method: "POST" });
      window.location.replace("/hall");
    });

    el("btn-start-bind")?.addEventListener("click", async () => {
      const d = await apiFetch("/workspace/api/bind/start", { method: "POST" });
      state.bindToken = d.token;
      el("bind-link").href = d.bind_url;
      el("bind-ext").href = d.download_url;
      el("bind-flow").hidden = false;
      el("bind-poll-status").textContent = "绑定链接已生成（10 分钟有效），请在上方打开并完成扩展提交。";
    });

    el("btn-load-profile")?.addEventListener("click", async () => {
      el("profile-output").textContent = "正在拉取个人进度…";
      try {
        const d = await apiFetch("/workspace/api/profile/load", { method: "POST" });
        const p = d.profile;
        const lines = [
          `指挥官：${p.commander_name} (Lv.${p.commander_level ?? "?"})`,
          `队伍总战力：${p.team_combat ?? "?"} ｜ 同步器：Lv.${p.synchro_level ?? "?"} ｜ 前哨基地：Lv.${p.outpost_battle_level ?? "?"}`,
          `主线：普通 ${p.normal_campaign || "?"} / 困难 ${p.hard_campaign || "?"}`,
          `无限塔：${p.progress_tribe_tower || "?"} ｜ 已收录角色：${p.character_count ?? "?"}`,
          `拉取时间：${p.fetched_at}`,
        ];
        if (p.growth_diff) lines.push("", p.growth_diff);
        state.lastProfileText = lines.join("\n");
        el("profile-output").textContent = state.lastProfileText;
        el("btn-share-profile").disabled = !state.shareTargetAvailable;
      } catch (err) {
        el("profile-output").textContent = err.message;
      }
    });

    el("btn-load-roster")?.addEventListener("click", async () => {
      const list = el("roster-list");
      list.textContent = "正在加载已持有角色…";
      try {
        const d = await apiFetch("/workspace/api/roster/load", { method: "POST" });
        el("roster-count").textContent = `共 ${d.count} 名角色`;
        list.innerHTML = "";
        for (const c of d.characters.slice(0, 60)) {
          const row = document.createElement("div");
          row.className = "list-row";
          row.textContent = `${c.name} | ${c.burst || "?"} | ${c.element || "?"} | 战力 ${c.combat} | LB${c.grade}`;
          list.append(row);
        }
      } catch (err) {
        list.textContent = err.message;
      }
    });

    el("btn-load-card")?.addEventListener("click", async () => {
      el("card-output").textContent = "查询单卡中…";
      try {
        const d = await apiFetch("/workspace/api/character/load", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: el("char-card-q").value }),
        });
        const ch = d.character;
        el("card-output").textContent = [
          `${ch.name} (Lv.${ch.level ?? "?"}) | 战力 ${ch.combat ?? "?"}`,
          ch.skills || "",
          ...(ch.overload_lines || []),
        ].join("\n");
      } catch (err) {
        el("card-output").textContent = err.message;
      }
    });

    async function buildSoloRaid(source) {
      el("sr-output").textContent = "正在编组与调用固定估伤引擎…";
      try {
        const d = await apiFetch("/workspace/api/solo-raid/build", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source,
            members: el("sr-manual-pool").value,
            save: el("sr-save-plan").checked,
          }),
        });
        el("sr-trust-badge").textContent = `引擎校验：${d.version_trust} (verified=${d.version_ok})`;
        state.lastSoloText = d.text;
        el("sr-output").textContent = d.text;
        el("btn-sr-share").disabled = !state.shareTargetAvailable;
      } catch (err) {
        el("sr-output").textContent = err.message;
      }
    }
    el("btn-sr-account")?.addEventListener("click", () => buildSoloRaid("account"));
    el("btn-sr-manual")?.addEventListener("click", () => buildSoloRaid("manual"));

    async function openArenaMode(mode) {
      try {
        const d = await apiFetch("/workspace/api/arena/open", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode }),
        });
        const linkBox = el("arena-web-link");
        linkBox.textContent = "已签发一次性编辑器链接（15 分钟有效）：";
        const link = document.createElement("a");
        link.href = d.url;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = d.url;
        linkBox.append(link);
      } catch (err) {
        el("arena-web-link").textContent = err.message;
      }
    }
    el("btn-arena-single-web")?.addEventListener("click", () => openArenaMode("single"));
    el("btn-arena-three-web")?.addEventListener("click", () => openArenaMode("three"));

    el("btn-arena-analyze")?.addEventListener("click", async () => {
      try {
        const d = await apiFetch("/workspace/api/arena/analyze", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lineup: el("arena-lineup").value, owned: true }),
        });
        state.lastArenaText = d.text;
        el("arena-output").textContent = d.text;
        el("btn-arena-share").disabled = !state.shareTargetAvailable;
      } catch (err) {
        el("arena-output").textContent = err.message;
      }
    });

    el("btn-ws-wishlist")?.addEventListener("click", async () => {
      try {
        const d = await apiFetch("/workspace/api/tools/wishlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            strategy: el("ws-wl-strategy").value,
            owned: el("ws-wl-owned").value,
          }),
        });
        el("ws-wl-output").textContent = d.text;
      } catch (err) {
        el("ws-wl-output").textContent = err.message;
      }
    });

    el("btn-ws-sync")?.addEventListener("click", async () => {
      try {
        const d = await apiFetch("/workspace/api/tools/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            use_account: true,
            target: el("ws-sync-tgt").value,
            production: {
              core_dust: el("ws-sync-dust").value,
              credits: el("ws-sync-cred").value,
              battle_data: el("ws-sync-data").value,
            },
          }),
        });
        el("ws-sync-output").textContent = d.text;
      } catch (err) {
        el("ws-sync-output").textContent = err.message;
      }
    });

    el("btn-toggle-push-on")?.addEventListener("click", async () => {
      const d = await apiFetch("/workspace/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "toggle_push", enabled: true }),
      });
      el("settings-output").textContent = `每日汇总已开启 (${d.updated})`;
    });
    el("btn-toggle-push-off")?.addEventListener("click", async () => {
      const d = await apiFetch("/workspace/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "toggle_push", enabled: false }),
      });
      el("settings-output").textContent = `每日汇总已关闭 (${d.updated})`;
    });
    el("btn-clear-growth")?.addEventListener("click", async () => {
      const d = await apiFetch("/workspace/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "clear_growth" }),
      });
      el("settings-output").textContent = d.message;
    });

    el("btn-share-profile")?.addEventListener("click", () => openSharePreview("profile", state.lastProfileText));
    el("btn-sr-share")?.addEventListener("click", () => openSharePreview("solo_raid", state.lastSoloText));
    el("btn-arena-share")?.addEventListener("click", () => openSharePreview("arena", state.lastArenaText));
    el("btn-share-cancel")?.addEventListener("click", () => el("share-dialog").close());
    el("btn-share-confirm")?.addEventListener("click", async () => {
      const status = el("share-confirm-status");
      status.textContent = "正在发送…";
      try {
        const d = await apiFetch("/workspace/api/share/confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            confirm_token: state.confirmToken,
            idempotency_key: newKey("share"),
          }),
        });
        status.textContent = `发送成功：${d.target_label}`;
        showToast("已发送到 QQ 会话");
        setTimeout(() => el("share-dialog").close(), 900);
      } catch (err) {
        status.textContent = err.message;
      }
    });

    init().catch((err) => {
      el("session-meta").textContent = err.message;
    });
  });
})();
