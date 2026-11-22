# NIKKE Character Card 字体资产规范与开源许可说明

本目录包含 NIKKE 单角色练度卡（Character Card）渲染所需的离线字体资源。所有字体均为开源字体，按下表分别遵循 SIL Open Font License (OFL) 1.1 或 Apache License 2.0；汇总见仓库根目录 `NOTICE`。

完整的 Noto Sans S Chinese OTF（`NotoSansHans-Regular.otf`、`NotoSansHans-Medium.otf`，共 16,754,584 字节）运行时从未加载，已在 PR-6A 删除；两个离线 Spine 证据脚本改用本目录已核验的字体（`scripts/shared/evidence_fonts.py`）。如需原文件可从 Git 历史恢复（blob `923f89c8…` / `ad071a40…`，见 `docs/architecture/repository_organization_moves.json`）。

---

## 1. 字体清单与用途

| 字体文件 | 声明家族名 (`font-family`) | 字重 (`font-weight`) | 格式 | 用途说明 | 开源许可 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `NotoSansSC-ReplicaSubset-800.woff2` | `NikkeNotoSC` | 800 (ExtraBold) | WOFF2 | 角色名标题 (`--font-cn-title`)、高字重中文主信息 | OFL 1.1 (`OFL-NotoSansSC.txt`) |
| `NotoSansSC-ReplicaSubset-700.woff2` | `NikkeNotoSC` | 700 (Bold) | WOFF2 | 词条标签、总评项等粗体中文文案 (`--font-cn-body`) | OFL 1.1 (`OFL-NotoSansSC.txt`) |
| `BarlowCondensed-Bold.ttf` | `NikkeBarlowCondensed` | 700 (Bold) | TTF | 等级数值、战力大字、词条阶数等窄体数字 (`--font-num-display`) | OFL 1.1 (`OFL-BarlowCondensed.txt`) |
| `BarlowCondensed-SemiBold.ttf` | `NikkeBarlowCondensedSemiBold` | 600 (SemiBold) | TTF | 次级高密度窄体数字 | OFL 1.1 (`OFL-BarlowCondensed.txt`) |
| `Rajdhani-Bold.ttf` | `NikkeRajdhani` | 700 (Bold) | TTF | 科技感标识、前缀、槽位英文小标 (`--font-tech-label`) | OFL 1.1 (`OFL-Rajdhani.txt`) |
| `Rajdhani-SemiBold.ttf` | `NikkeRajdhaniSemiBold` | 600 (SemiBold) | TTF | 科技感次级标签与装备角标数值 | OFL 1.1 (`OFL-Rajdhani.txt`) |
| `ReplicaSans.otf` | `Replica` | 500 (Medium；`@font-face` 将 400-900 映射到这一字面) | OTF | 子集外字符的字形回退 | Apache 2.0 (`LICENSE-Apache-2.0.txt`)；修改版：由 Noto Sans S Chinese Medium 1.000 子集化（591 码位，字形轮廓未改），Copyright (c) 2014 Adobe Systems Incorporated；Noto is a trademark of Google Inc. |

---

## 2. Noto Sans SC 子集化方案 (Production Subset)

为解决完整版中文字体（约 17.7MB TTF / 23MB+ Base64 payload）导致渲染卡顿与仓库体积臃肿的问题，本项目使用 `fontTools` 将官方 `NotoSansSC[wght].ttf` 实例化并子集化为两份 WOFF2 文件：

- `NotoSansSC-ReplicaSubset-700.woff2`（约 115 KB）
- `NotoSansSC-ReplicaSubset-800.woff2`（约 115 KB）

### 2.1 字符覆盖范围
子集字符集由脚本 `scripts/assets/build_replica_font_subset.py` 自动汇集，覆盖：
1. **官方全部角色名**：来自 `assets/data/character_master.json` 中已收录的所有角色中文与英文名；
2. **固定 UI 文案**：如“词条合计”、“已知词条合计”、“阶”、“技能”、“爆裂”、“未装备”、“未获得效果”等；
3. **装备词条选项**：所有洗练词条全称与短标签（攻击、防御、装弹、蓄速、优越、暴率、暴伤、命中、蓄伤）；
4. **基础符号与标点**：数字 `0-9`、字母 `a-zA-Z`、阶数 `T1-T15`、标点符号、特殊符号（✦、★、·、—、~ 等）。

### 2.2 重新生成子集
当新增角色或修改固定词条时，可随时运行以下脚本一键刷新 WOFF2 子集：
```bash
python scripts/assets/build_replica_font_subset.py
```

### 2.3 覆盖清单与按需内联
脚本同时生成 `NotoSansSC-ReplicaSubset.codepoints.json`：记录 700/800 子集共同覆盖的码位（`codepoints`），
以及 `ReplicaSans.otf` 有而子集没有的码位（`fallback_only`）。角色卡 payload 只内联当前排版档位
（默认 `typo-set-b`）实际引用的字体：SemiBold 字重仅在 `header-font-d` 档位内联；`Replica` 只有当
中文字体栈中的文字含 `fallback_only` 字符时才作为字形回退内联，否则浏览器根本不会用到它，渲染结果逐像素一致。
重新生成子集后请一并提交该清单。

---

## 3. 字体真实渲染保证（Zero Faux-Bold）

在模板 `templates/t2i/character.html` 中严格配置：
```css
font-synthesis: none;
```
禁止浏览器通过拉伸/描边模拟伪粗体（faux bold）。所有 700 与 800 字重直接由独立的真实字重切片文件提供，确保笔画骨架清晰、抗锯齿边缘锐利。

---

## 4. 来源与上游项目

- **Noto Sans SC**: [Google Fonts - Noto Sans SC](https://fonts.google.com/specimen/Noto+Sans+SC) / [GitHub google/fonts](https://github.com/google/fonts/tree/main/ofl/notosanssc)
- **Barlow Condensed**: [Barlow Project](https://github.com/jpt/barlow)
- **Rajdhani**: [Indian Type Foundry - Rajdhani](https://github.com/itfoundry/rajdhani)
- **Noto Sans S Chinese 1.000**（`ReplicaSans.otf` 的来源，Adobe 与 Google 的 Noto Sans CJK 早期版本）：上游下载地址待确认。
