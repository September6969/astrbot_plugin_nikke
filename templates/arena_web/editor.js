"use strict";
// 浏览器仅编辑输入，所有计算均交给服务端。
const $ = (id) => document.getElementById(id);
let characters = [];
let byKey = new Map();
let draft;
let csrf = "";
let revision = 0;
let history = [];
let activeSlot = [0, 0];
let visibleTeam = 0;
let swapMode = false;
let burstFilter = "all";
const PAGE_SIZE = 30;
let saveQueue = null;
let pendingDraft = null;
let savingDraft = null;
let pendingAnalysis = null;
let busy = false;
let ending = false;
let ended = false;
let saveError = false;
let revisionConflict = false;
let validDraft = false;
let choiceLimit = PAGE_SIZE;
const emptyTeam = () => ["", "", "", "", ""];
const clone = (value) => JSON.parse(JSON.stringify(value));
const normalize = (value) => value.normalize("NFKC").toLocaleLowerCase().replace(/[\s:：]/g, "");
async function api(path, body) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 25000);
  const options = {credentials: "same-origin", headers: {}, signal: controller.signal};
  if (body !== undefined) {
    options.method = "POST";
    options.headers = {"Content-Type": "application/json", "X-Arena-CSRF": csrf};
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch("/arena/api/" + path, options);
    const result = await response.json();
    if (response.ok) return result;
    const error = new Error(result.error || "请求失败，请稍后再试。");
    error.status = response.status;
    throw error;
  } catch (error) {
    if (controller.signal.aborted) throw new Error("请求等待超时，请重试。");
    if (error.status) throw error;
    if (!response) throw new Error("网络连接中断，请重新连接后重试。");
    const incomplete = new Error("未收到完整响应，请稍后重试。");
    incomplete.status = response.status;
    throw incomplete;
  } finally {
    clearTimeout(timeout);
  }
}
function setTone(element, tone) {
  if (!element) return;
  if (tone) element.dataset.tone = tone;
  else delete element.dataset.tone;
}
function report(error) {
  if (error.status === 401) {
    ended = true;
    $("end-session").open = false;
    renderAnalysisButton();
  }
  const target = $(draft ? "status" : "loading");
  setTone(target, "error");
  target.textContent = ended
    ? "编辑会话已失效。请回 QQ 私聊发送 /妮姬 竞技场 三队 或 编辑，获取新链接。"
    : error.message;
}
function queueSave() {
  pendingAnalysis = null;
  pendingDraft = clone(draft);
  if (!saveError) flushDraft();
}
function flushDraft() {
  if (saveQueue || revisionConflict || ended) return;
  saveError = false;
  $("retry-save").hidden = true;
  setTone($("status"), "");
  $("status").textContent = "正在保存草稿…";
  saveQueue = (async () => {
    while (savingDraft || pendingDraft) {
      if (!savingDraft) {
        savingDraft = pendingDraft;
        pendingDraft = null;
      }
      const result = await api("draft", {draft: savingDraft, revision});
      revision = result.revision;
      savingDraft = null;
    }
    setTone($("status"), "ok");
    $("status").textContent = "草稿已保存";
  })().catch((error) => {
    saveError = true;
    revisionConflict = error.status === 409 || error.status === 401;
    report(error);
  }).finally(() => {
    saveQueue = null;
    renderAnalysisButton();
  });
}
$("retry-save").onclick = flushDraft;
function change(callback) {
  $("result").hidden = true;
  history.push(clone(draft));
  if (history.length > 20) history.shift();
  swapMode = false;
  const count = draft.teams.length;
  callback();
  if (draft.teams.length === 1) delete draft.manual_candidates;
  render();
  if (count !== draft.teams.length) showManualCandidates();
  queueSave();
}
function render() {
  $("mode").value = draft.teams.length === 3 ? "three" : "single";
  $("roster-mode").value = draft.roster_mode;
  $("objective").value = draft.objective;
  $("objective-field").hidden = draft.teams.length !== 3;
  $("candidate-editor").hidden = draft.teams.length !== 3;
  $("manual").hidden = draft.roster_mode !== "manual";
  $("undo").disabled = !history.length || busy;
  if (!draft.teams[activeSlot[0]]) activeSlot = [0, 0];
  renderTeams();
  renderChoices();
  const bases = draft.teams.flat().filter(Boolean).map((key) => byKey.get(key)?.base_key || key);
  const filled = bases.length;
  const repeated = new Set(bases).size !== bases.length;
  const complete = filled === draft.teams.length * 5;
  const issue = repeated ? "跨队存在重复角色，请更换。" : complete ? "阵容已填满。" : "请补齐空位。";
  setTone($("validation"), repeated ? "error" : complete ? "ok" : "warn");
  $("validation").textContent = "已选 " + filled + "/" + (draft.teams.length * 5) + " · " + issue;
  validDraft = complete && !repeated;
  renderAnalysisButton();
  if (draft.roster_mode === "manual") renderOwned();
}
function positionName(teamIndex, position) {
  return (draft.teams.length === 3 ? `第 ${teamIndex + 1} 队 · ` : "") + `P${position + 1}`;
}
function addPortrait(button, char) {
  if (!char.portrait) return;
  const avatar = document.createElement("img");
  avatar.src = char.portrait;
  avatar.alt = "";
  avatar.loading = "lazy";
  avatar.onerror = () => avatar.remove();
  button.append(avatar);
}
function chooseSlot(teamIndex, position) {
  const [previousTeam, previousPosition] = activeSlot;
  if (swapMode && (previousTeam !== teamIndex || previousPosition !== position)) {
    change(() => {
      const from = draft.teams[previousTeam], to = draft.teams[teamIndex];
      [from[previousPosition], to[position]] = [to[position], from[previousPosition]];
      activeSlot = [teamIndex, position];
    });
  } else {
    swapMode = swapMode && (previousTeam !== teamIndex || previousPosition !== position);
    activeSlot = [teamIndex, position];
    renderTeams();
    renderChoices();
  }
  $("teams").querySelector('[aria-pressed="true"]').focus({preventScroll: true});
}
function renderTeams() {
  $("teams").replaceChildren();
  $("team-tabs").replaceChildren();
  const [activeTeam, activePosition] = activeSlot;
  if (!swapMode) visibleTeam = activeTeam;
  $("team-tabs").hidden = draft.teams.length < 3;
  draft.teams.forEach((team, teamIndex) => {
    const filled = team.filter(Boolean).length;
    const tab = document.createElement("button");
    tab.type = "button";
    tab.textContent = `队伍 ${teamIndex + 1} · ${filled}/5`;
    tab.setAttribute("aria-pressed", String(teamIndex === visibleTeam));
    tab.onclick = () => {
      if (swapMode) {
        visibleTeam = teamIndex;
      } else if (teamIndex !== activeTeam) {
        activeSlot = [teamIndex, Math.max(0, team.indexOf(""))];
      }
      renderTeams();
      renderChoices();
      $("team-tabs").children[teamIndex].focus({preventScroll: true});
    };
    $("team-tabs").append(tab);
    const section = document.createElement("section");
    section.className = "team";
    section.dataset.visible = String(teamIndex === visibleTeam);
    const title = document.createElement("h2");
    title.textContent = draft.teams.length === 3 ? `队伍 ${teamIndex + 1}` : "站位";
    const count = document.createElement("span");
    count.textContent = `${filled}/5`;
    title.append(count);
    const slots = document.createElement("div");
    slots.className = "slots";
    team.forEach((key, position) => {
      const button = document.createElement("button");
      button.type = "button";
      const isActive = teamIndex === activeTeam && position === activePosition;
      button.className = (key ? "seat" : "seat empty") + (swapMode && isActive ? " swap-source" : "");
      button.setAttribute("aria-pressed", String(isActive));
      const char = byKey.get(key);
      const label = document.createElement("span");
      label.className = "seat-label";
      label.textContent = `P${position + 1}`;
      button.append(label);
      if (char) {
        addPortrait(button, char);
        const name = document.createElement("span");
        name.className = "portrait-name";
        name.textContent = char.name;
        button.append(name);
        button.title = char.name;
      }
      button.setAttribute("aria-label", `${positionName(teamIndex, position)} ${char?.name || "空位"}`);
      button.onclick = () => chooseSlot(teamIndex, position);
      slots.append(button);
    });
    section.append(title, slots);
    $("teams").append(section);
  });
  const hasCharacter = Boolean(draft.teams[activeTeam][activePosition]);
  $("swap").disabled = !hasCharacter;
  $("swap").setAttribute("aria-pressed", String(swapMode));
  $("swap").textContent = swapMode ? "取消换位" : "换位";
  $("remove-character").disabled = !hasCharacter;
  $("clear-team").hidden = draft.teams.length < 3;
  $("picker-title").textContent = swapMode
    ? `${positionName(activeTeam, activePosition)} · 选择换位目标`
    : `${positionName(activeTeam, activePosition)} · 选择角色`;
}
function renderAnalysisButton() {
  const inactive = busy || ending || ended;
  $("editor").disabled = !draft || inactive;
  $("analyze").disabled = inactive || saveError || revisionConflict || !validDraft;
  $("analyze").textContent = busy ? "正在分析…" : pendingAnalysis && !revisionConflict && !ended ? "重试分析" : "分析阵容";
  $("retry-save").hidden = inactive || !saveError || revisionConflict;
  $("revoke").disabled = !draft || inactive;
  $("end-session").hidden = ended;
}
function matches(char, query) {
  return normalize(char.name + " " + char.key + " " + (char.aliases || []).join(" ")).includes(normalize(query));
}
function renderChoices() {
  const [teamIndex, position] = activeSlot;
  $("search-clear").hidden = !$("search").value;
  const takenAt = new Map();
  draft.teams.forEach((team, index) => {
    team.forEach((key, slot) => {
      if (!key || (index === teamIndex && slot === position)) return;
      const base = byKey.get(key)?.base_key || key;
      takenAt.set(base, draft.teams.length === 3 ? `${index + 1}·P${slot + 1}` : `P${slot + 1}`);
    });
  });
  const matchesQuery = characters.filter((char) =>
    (burstFilter === "all" || !char.burst || String(char.burst) === burstFilter) && matches(char, $("search").value));
  $("choices").replaceChildren();
  $("choice-count").textContent = `${matchesQuery.length} 人`;
  for (const filter of $("burst-filters").querySelectorAll("button")) {
    filter.setAttribute("aria-pressed", String(filter.dataset.burst === burstFilter));
  }
  for (const char of matchesQuery.slice(0, choiceLimit)) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "portrait";
    const seatTag = takenAt.get(char.base_key);
    const taken = Boolean(seatTag);
    const burst = document.createElement("span");
    burst.className = "portrait-stage";
    burst.textContent = char.burst ? "B" + char.burst : "全阶段";
    const name = document.createElement("span");
    name.className = "portrait-name";
    name.textContent = char.name;
    button.append(burst);
    if (seatTag) {
      const used = document.createElement("span");
      used.className = "portrait-used";
      used.textContent = seatTag;
      button.append(used);
    }
    addPortrait(button, char);
    button.append(name);
    button.title = char.name + (taken ? ` · 已在 ${seatTag}` : "");
    button.setAttribute("aria-label", `${char.name}${taken ? " · 已在阵容中" : ""} · ${burst.textContent}`);
    button.disabled = taken || swapMode;
    button.onclick = (event) => {
      change(() => {
        draft.teams[teamIndex][position] = char.key;
        const seats = draft.teams.flat();
        const current = teamIndex * 5 + position;
        const next = seats.findIndex((key, index) => !key && index > current);
        const empty = next < 0 ? seats.indexOf("") : next;
        if (empty >= 0) activeSlot = [Math.floor(empty / 5), empty % 5];
        $("search").value = "";
        choiceLimit = PAGE_SIZE;
      });
      if (event.detail === 0) $("search").focus({preventScroll: true});
    };
    $("choices").append(button);
  }
  $("more-choices").hidden = matchesQuery.length <= choiceLimit;
  if (!$("choices").children.length) $("choices").textContent = "未找到角色，请尝试完整姓名或角色键。";
}
function filteredOwnedCharacters() {
  return characters.filter((char) => matches(char, $("owned-search").value));
}
function renderOwned() {
  $("owned-count").textContent = "已手动选择 " + draft.manual_owned.length + " 人";
  $("owned-list").replaceChildren();
  for (const char of filteredOwnedCharacters()) {
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = draft.manual_owned.includes(char.key);
    checkbox.onchange = () => change(() => {
      const selected = new Set(draft.manual_owned);
      if (checkbox.checked) selected.add(char.key); else selected.delete(char.key);
      draft.manual_owned = [...selected];
    });
    label.append(checkbox, document.createTextNode(char.name));
    $("owned-list").append(label);
  }
}
$("search").oninput = () => {
  choiceLimit = PAGE_SIZE;
  renderChoices();
};
$("search").addEventListener("keydown", (event) => {
  if (event.key === "Escape" && $("search").value) {
    event.preventDefault();
    $("search").value = "";
    choiceLimit = PAGE_SIZE;
    renderChoices();
  } else if (event.key === "Enter") {
    const first = $("choices").querySelector("button:not(:disabled)");
    if (first) {
      event.preventDefault();
      first.click();
    }
  }
});
$("search-clear").onclick = () => {
  $("search").value = "";
  choiceLimit = PAGE_SIZE;
  renderChoices();
  $("search").focus({preventScroll: true});
};
$("clear-team").onclick = () => change(() => {
  draft.teams[visibleTeam] = emptyTeam();
  activeSlot = [visibleTeam, 0];
});
$("owned-select-visible").onclick = () => change(() => {
  const selected = new Set(draft.manual_owned);
  for (const char of filteredOwnedCharacters()) selected.add(char.key);
  draft.manual_owned = [...selected];
});
$("owned-clear-visible").onclick = () => change(() => {
  const hiddenKeys = new Set(filteredOwnedCharacters().map((char) => char.key));
  draft.manual_owned = draft.manual_owned.filter((key) => !hiddenKeys.has(key));
});
$("burst-filters").onclick = (event) => {
  if (!event.target.dataset.burst) return;
  burstFilter = event.target.dataset.burst;
  choiceLimit = PAGE_SIZE;
  renderChoices();
};
$("more-choices").onclick = () => {
  choiceLimit += PAGE_SIZE;
  renderChoices();
};
$("swap").onclick = () => {
  swapMode = !swapMode;
  renderTeams();
  renderChoices();
};
$("remove-character").onclick = () => {
  const [teamIndex, position] = activeSlot;
  change(() => {draft.teams[teamIndex][position] = "";});
};
$("owned-search").oninput = renderOwned;
$("mode").onchange = () => change(() => {
  if ($("mode").value === "three") {
    draft.teams = [draft.teams[0], emptyTeam(), emptyTeam()];
  } else draft.teams = [draft.teams[0]];
});
$("roster-mode").onchange = () => change(() => {draft.roster_mode = $("roster-mode").value;});
$("objective").onchange = () => change(() => {draft.objective = $("objective").value;});
$("clear").onclick = () => change(() => {draft.teams = draft.teams.map(emptyTeam);});
$("undo").onclick = () => {
  if (!history.length) return;
  draft = history.pop();
  swapMode = false;
  render();
  showManualCandidates();
  queueSave();
};
const splitNames = (line) => line.split(/[/、,，]/).map((text) => text.trim());
function parseTeam(tokens) {
  if (tokens.length !== 5 || tokens.some((text) => !text)) throw new Error("每队需要五人，以 / 分隔。");
  return tokens.map((text) => {
    const found = characters.filter((char) => normalize(char.name) === normalize(text) || char.key === text
      || (char.aliases || []).some((name) => normalize(name) === normalize(text)));
    if (found.length !== 1) throw new Error("角色需要确认，请在名册搜索 " + text);
    return found[0].key;
  });
}
function showManualCandidates() {
  const candidates = draft.manual_candidates || [];
  $("candidate-teams").querySelectorAll("input").forEach((input, index) => {
    input.value = (candidates[index] || []).map((key) => byKey.get(key)?.name || key).join("/");
  });
  $("candidate-feedback").textContent = "";
}
$("apply-candidates").onclick = () => {
  try {
    const candidates = Array.from($("candidate-teams").querySelectorAll("input"), (input, index) => {
      try {
        if (!input.value.trim()) return null;
        const keys = parseTeam(splitNames(input.value.normalize("NFKC")));
        if (new Set(keys.map((key) => byKey.get(key).base_key)).size !== 5) {
          throw new Error("同队不能包含重复角色或珍藏变体。");
        }
        return keys;
      } catch (error) {
        throw new Error(`第 ${index + 1} 场：${error.message}`);
      }
    });
    change(() => {
      if (candidates.some(Boolean)) draft.manual_candidates = candidates;
      else delete draft.manual_candidates;
    });
    setTone($("candidate-feedback"), "ok");
    $("candidate-feedback").textContent = candidates.some(Boolean) ? "已加入候选范围。" : "已清除手动候选。";
  } catch (error) {
    setTone($("candidate-feedback"), "error");
    $("candidate-feedback").textContent = error.message;
  }
};
$("import").onclick = () => {
  try {
    const lines = $("paste").value.trim().normalize("NFKC").split(/\r?\n+/);
    const flat = lines.length === 1 ? splitNames(lines[0]) : [];
    const groups = flat.length === 15
      ? [flat.slice(0, 5), flat.slice(5, 10), flat.slice(10)]
      : lines.map(splitNames);
    if (![1, 3].includes(groups.length)) throw new Error("请输入五人、三行五人或一行十五人。");
    const teams = groups.map(parseTeam);
    change(() => {draft.teams = teams;});
    setTone($("import-feedback"), "ok");
    $("import-feedback").textContent = `已导入 ${teams.length} 队（${teams.length * 5} 人）。`;
  } catch (error) {
    setTone($("import-feedback"), "error");
    $("import-feedback").textContent = error.message;
    report(error);
  }
};
$("copy-result").onclick = async () => {
  const text = $("result-text").textContent || "";
  if (!text) return;
  let copied = false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      copied = true;
    }
  } catch (_) {
    copied = false;
  }
  $("copy-result-feedback").textContent = copied ? "已复制结果" : "请长按或手动选中复制";
};
document.addEventListener("keydown", (event) => {
  const tag = document.activeElement?.tagName;
  if ((event.ctrlKey || event.metaKey) && !event.shiftKey && event.key.toLowerCase() === "z"
      && !["INPUT", "TEXTAREA", "SELECT"].includes(tag || "")) {
    if (!$("undo").disabled) {
      event.preventDefault();
      $("undo").click();
    }
  }
});
$("analyze").onclick = async () => {
  busy = true; render(); $("status").textContent = "正在分析…";
  try {
    await saveQueue;
    if (saveError) return;
    $("status").textContent = "正在分析…";
    if (!pendingAnalysis) {
      const bytes = crypto.getRandomValues(new Uint8Array(24));
      const idempotency_key = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
      pendingAnalysis = {draft: clone(draft), idempotency_key, revision};
    }
    const result = await api("analyze", pendingAnalysis);
    pendingAnalysis = null;
    revision = result.revision;
    $("result-text").textContent = result.text;
    $("result").hidden = false;
    setTone($("status"), "ok");
    $("status").textContent = "结果已保存，可回 QQ 查看。";
    $("result").scrollIntoView({behavior: "smooth", block: "start"});
  } catch (error) {
    if (error.status === 401 || error.status === 409) revisionConflict = true;
    report(error);
  }
  finally {busy = false; render();}
};
$("revoke").onclick = async () => {
  ending = true;
  renderAnalysisButton();
  try {
    await saveQueue;
    if (ended) return;
    await api("revoke", {});
    ended = true;
    $("end-session").open = false;
    setTone($("status"), "warn");
    $("status").textContent = "编辑会话已结束。请回 QQ 获取新链接。";
  } catch (error) {report(error);}
  finally {ending = false; renderAnalysisButton();}
};
async function start() {
  try {
    const data = await api("roster");
    characters = data.characters;
    $("choice-count").title = data.catalogue_basis || "";
    byKey = new Map(characters.map((char) => [char.key, char]));
    csrf = data.csrf; revision = data.revision;
    const ownedAvailable = ["available", "partial"].includes(data.roster_status);
    $("roster-mode").options[0].disabled = !ownedAvailable;
    draft = Object.keys(data.draft).length ? data.draft : {
      teams: data.mode === "three" ? [emptyTeam(), emptyTeam(), emptyTeam()] : [emptyTeam()],
      roster_mode: ownedAvailable ? "owned" : "sandbox", manual_owned: [], objective: "two",
    };
    $("loading").hidden = true;
    setTone($("status"), ownedAvailable ? "ok" : "warn");
    $("status").textContent = ownedAvailable ? "角色库已读取。" : "角色库未验证，当前使用全角色沙盒。";
    render();
    showManualCandidates();
    const result = await api("result");
    if (result.saved) {$("result-text").textContent = result.text; $("result").hidden = false;}
  } catch (error) {report(error);}
}
start();
