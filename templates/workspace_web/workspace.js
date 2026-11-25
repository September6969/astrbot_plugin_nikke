"use strict";

(() => {
  const state = {
    csrf: "",
    lastProfileText: "",
    lastSoloText: "",
    lastArenaText: "",
    lastSyncText: "",
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

  let soloContextLoaded = false;

  async function loadSoloRaidContext() {
    const banner = el("sr-season-banner");
    if (!banner) return;
    try {
      const d = await apiFetch("/workspace/api/solo-raid/context");
      soloContextLoaded = true;
      if (d.latest) {
        const b = d.latest.bosses && d.latest.bosses[0];
        const parts = [`${d.latest.name}（${d.latest.status || "核验赛季"}）`];
        if (b) {
          parts.push(`首领：${b.name} | 弱点：${b.weakness}`);
          if (b.element) parts.push(`属性：${b.element}`);
          if (b.mechanics) parts.push(b.mechanics);
          if (b.weakness_code && el("sr-boss-element") && !el("sr-boss-element").value) {
            el("sr-boss-element").value = b.weakness_code;
          }
        }
        if (d.latest.note) parts.push(d.latest.note);
        banner.textContent = parts.join(" ｜ ");
      } else {
        banner.textContent = "暂无已同步赛季，可在下方手动选择 Boss 弱点属性估算伤害。";
      }
    } catch (err) {
      banner.textContent = err.message;
    }
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
    if (tabId === "solo-raid" && !soloContextLoaded) {
      loadSoloRaidContext();
    }
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
        list.replaceChildren();
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
            boss_element: el("sr-boss-element")?.value || "",
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

    function collectCases() {
      const cases = { core_dust: {}, credits: {}, battle_data: {} };
      document.querySelectorAll(".case-inp").forEach((inp) => {
        const res = inp.dataset.res;
        const hr = inp.dataset.hr;
        if (cases[res] && hr) {
          cases[res][hr] = Number(inp.value || 0);
        }
      });
      return cases;
    }

    function renderSyncVisual(plan) {
      const visual = el("ws-sync-visual");
      const kpi = el("ws-sync-kpi");
      const cards = el("ws-sync-cards");
      if (!visual || !kpi || !cards || !plan) return;
      visual.hidden = false;

      const kpiItems = [
        {
          label: "预计达成日期",
          val: plan.eta || "无法估算",
          sub: plan.overall_days === null ? "存在零产量瓶颈" : `约需 ${plan.overall_days} 天（${plan.current} → ${plan.target}）`,
        },
        {
          label: "主要资源瓶颈",
          val: (plan.bottlenecks && plan.bottlenecks.length) ? plan.bottlenecks.join(" / ") : "无",
          sub: plan.outpost_level ? `前哨 Lv.${plan.outpost_level} · 每日歼灭 ${plan.wipeout_count ?? 1} 次` : "手动日产量模式",
        },
        {
          label: "当前库存立即升级",
          val: plan.reachable_level ? `Lv.${plan.reachable_level} (+${plan.gainable_levels})` : "-",
          sub: (plan.gainable_without_cases !== null && plan.gainable_without_cases !== plan.gainable_levels)
            ? `不含箱子 Lv.${plan.reachable_without_cases} (+${plan.gainable_without_cases})`
            : "已含背包资源箱统计",
        },
        {
          label: "再升 1 级还差",
          val: plan.next_level_missing
            ? `芯尘 ${Number(plan.next_level_missing.core_dust || 0).toLocaleString()}`
            : "—",
          sub: plan.next_level_missing
            ? `信用点 ${Number(plan.next_level_missing.credits || 0).toLocaleString()} / 数据 ${Number(plan.next_level_missing.battle_data || 0).toLocaleString()}`
            : "",
        },
      ];
      kpi.replaceChildren(...kpiItems.map((item) => {
        const box = document.createElement("div");
        box.className = "kpi-card";
        const lb = document.createElement("div");
        lb.className = "kpi-label";
        lb.textContent = item.label;
        const val = document.createElement("div");
        val.className = "kpi-val";
        val.textContent = item.val;
        const sub = document.createElement("div");
        sub.className = "kpi-sub";
        sub.textContent = item.sub;
        box.append(lb, val, sub);
        return box;
      }));

      cards.replaceChildren(...(plan.resources || []).map((r) => {
        const card = document.createElement("div");
        card.className = "res-card";
        const head = document.createElement("div");
        head.className = "res-head";
        const strong = document.createElement("strong");
        strong.textContent = r.label;
        const status = document.createElement("span");
        status.className = "tag";
        status.textContent = r.days === null ? "无法估算" : `${r.days} 天 · ${r.status}`;
        head.append(strong, status);

        const pct = r.required > 0 ? Math.min(100, Math.round((r.stock / r.required) * 100)) : 100;
        const bar = document.createElement("progress");
        bar.className = "res-progress";
        bar.max = 100;
        bar.value = pct;

        const meta = document.createElement("div");
        meta.className = "res-meta";
        const direct = plan.direct_inventory ? Number(plan.direct_inventory[r.resource] || 0) : r.stock;
        const cYield = plan.case_yields ? Number(plan.case_yields[r.resource] || 0) : 0;
        const lines = [
          `需要：${Number(r.required).toLocaleString()} (${pct}%)`,
          cYield > 0
            ? `总库存：${Number(r.stock).toLocaleString()}（直存 ${direct.toLocaleString()} + 箱子 ${cYield.toLocaleString()}）`
            : `库存：${Number(r.stock).toLocaleString()}`,
          `缺口：${Number(r.missing).toLocaleString()} ｜ 日产：${Math.round(Number(r.production || 0)).toLocaleString()}`,
        ];
        for (const text of lines) {
          const line = document.createElement("div");
          line.textContent = text;
          meta.append(line);
        }
        card.append(head, bar, meta);
        return card;
      }));
    }

    document.querySelectorAll(".sync-quick-tgt").forEach((btn) => {
      btn.addEventListener("click", () => {
        const cur = Number(el("ws-sync-cur")?.value || 200);
        const target = btn.dataset.target ? Number(btn.dataset.target) : cur + Number(btn.dataset.delta || 10);
        if (el("ws-sync-tgt")) {
          el("ws-sync-tgt").value = String(Math.max(cur + 1, target));
        }
      });
    });

    el("btn-ws-sync-autofill")?.addEventListener("click", async () => {
      const box = el("ws-sync-status");
      box.textContent = "正在读取绑定账号同步器、库存与前哨资料…";
      try {
        const d = await apiFetch("/workspace/api/sync/context", { method: "POST" });
        if (!d.bound) {
          box.textContent = d.message || "尚未绑定账号，可直接在下方手工填写参数计算。";
          return;
        }
        if (d.synchro_level) el("ws-sync-cur").value = String(d.synchro_level);
        if (d.suggested_target) el("ws-sync-tgt").value = String(d.suggested_target);
        if (d.outpost_level) el("ws-sync-outpost").value = String(d.outpost_level);
        if (d.inventory) {
          el("ws-sync-inv-dust").value = String(d.inventory.core_dust ?? 0);
          el("ws-sync-inv-cred").value = String(d.inventory.credits ?? 0);
          el("ws-sync-inv-data").value = String(d.inventory.battle_data ?? 0);
        }
        if (d.academy_boosts) {
          el("ws-sync-boost-dust").value = String(d.academy_boosts.core_dust ?? 45);
          el("ws-sync-boost-cred").value = String(d.academy_boosts.credits ?? 60);
          el("ws-sync-boost-data").value = String(d.academy_boosts.battle_data ?? 45);
        }
        const parts = [
          `已自动填充：同步器 Lv.${d.synchro_level ?? "?"}`,
          `前哨 Lv.${d.outpost_level ?? "?"}`,
          d.academy_note || "",
          d.rate_note || "",
        ].filter(Boolean);
        box.textContent = parts.join(" ｜ ");
        showToast("已填充绑定账号数据");
      } catch (err) {
        box.textContent = err.message;
      }
    });

    el("btn-ws-sync")?.addEventListener("click", async () => {
      try {
        const hrDust = el("ws-sync-hr-dust")?.value;
        const hrCred = el("ws-sync-hr-cred")?.value;
        const hrData = el("ws-sync-hr-data")?.value;
        const d = await apiFetch("/workspace/api/tools/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            current: el("ws-sync-cur").value,
            target: el("ws-sync-tgt").value,
            outpost_level: el("ws-sync-outpost").value,
            wipeout_count: el("ws-sync-wipeout").value,
            academy_boosts: {
              core_dust: el("ws-sync-boost-dust").value,
              credits: el("ws-sync-boost-cred").value,
              battle_data: el("ws-sync-boost-data").value,
            },
            hourly_override: {
              core_dust: hrDust === "" ? null : hrDust,
              credits: hrCred === "" ? null : hrCred,
              battle_data: hrData === "" ? null : hrData,
            },
            inventory: {
              core_dust: el("ws-sync-inv-dust").value,
              credits: el("ws-sync-inv-cred").value,
              battle_data: el("ws-sync-inv-data").value,
            },
            cases: collectCases(),
            extra_daily: {
              core_dust: el("ws-sync-extra-dust").value,
              credits: el("ws-sync-extra-cred").value,
              battle_data: el("ws-sync-extra-data").value,
            },
          }),
        });
        renderSyncVisual(d.plan);
        state.lastSyncText = d.text;
        el("ws-sync-output").textContent = d.text;
        el("btn-ws-sync-share").disabled = !state.shareTargetAvailable;
      } catch (err) {
        el("ws-sync-output").textContent = err.message;
      }
    });

    async function runOverloadCompare(simulateFlag) {
      el("ws-ol-output").textContent = "正在读取角色装备并分析…";
      try {
        const d = await apiFetch("/workspace/api/tools/overload", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            character_query: el("ws-ol-char").value,
            preset: el("ws-ol-preset").value,
            targets: el("ws-ol-targets").value,
            simulate: simulateFlag,
          }),
        });
        el("ws-ol-output").textContent = d.text;
      } catch (err) {
        el("ws-ol-output").textContent = err.message;
      }
    }
    el("btn-ws-overload")?.addEventListener("click", () => runOverloadCompare(false));
    el("btn-ws-overload-sim")?.addEventListener("click", () => runOverloadCompare(true));

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
    el("btn-ws-sync-share")?.addEventListener("click", () => openSharePreview("sync", state.lastSyncText));
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
