# 本地预渲染 Spine 资产审计与 Manifest 迁移报告

**审计日期**: 2026-09-13  
**状态**: 审计通过 (100% 物理校验合规，0 冲突，0 损坏，0 缺失)  
**资产目录**: `assets/spine-rendered/`  
**Manifest 路径**: `assets/spine_manifest.json`  

---

## 1. 背景与问题定位

Astra 在完成 Character T2I 渲染页面与自动化测试后，接入真实环境预览时发现：
仓库随附的旧版 Spine manifest (`schema_version: 1`) 缺少当前资产安全契约（`AssetManager` 与安全 loader）所必需的 `sha256` 校验和与身份关联字段。安全加载器在加载这些旧资产时执行 fail-closed 策略，正确地拒绝加载未带有效 SHA-256 校验的资产，导致页面回退为占位图。

这是一次**资产元数据（Manifest）安全升级与迁移任务**，而非 Character 前端页面或业务 DTO 问题。

---

## 2. Schema 对比与缺失字段分析

### 2.1 旧版 Manifest Schema (`schema_version: 1`)
旧版 manifest 记录结构如下：
```json
{
  "schema_version": 1,
  "characters": {
    "c010": {
      "canonical_asset_id": "c010",
      "runtime_version": "4.0",
      "png_file": "c010.png",
      "width": 425,
      "height": 891,
      "alpha_bbox": [316, 83, 709, 942],
      "file_size": 313219,
      "updated_at": "2026-09-11T17:55:33.564728+00:00"
    }
  },
  "total_characters": 8
}
```

### 2.2 当前安全加载器所需 Schema (`schema_version: 2`)
当前安全加载器要求的标准化条目结构如下：
```json
{
  "schema_version": 2,
  "generated_at": "2026-09-13T14:44:01.337134+00:00",
  "total_characters": 8,
  "verified_count": 8,
  "failed_count": 0,
  "characters": {
    "c010": {
      "spine_asset_id": "c010",
      "character_resource_id": "10",
      "character_name": "拉毗",
      "character_name_en": "Rapi",
      "costume_id": null,
      "costume_name": null,
      "is_costume": false,
      "local_relpath": "assets/spine-rendered/c010.png",
      "sha256": "fb05dccee549af72da59b33d6181d2f47d19302caf98ed364e3d216e2c21a0c3",
      "width": 425,
      "height": 891,
      "format": "png",
      "file_size": 313219,
      "alpha_bbox": [316, 83, 709, 942],
      "runtime_version": "4.0",
      "verification": "local_revalidated"
    }
  }
}
```

### 2.3 字段缺失与生成可行性判定

| 字段 | 旧版状态 | 当前状态 | 确定性生成方式 |
| :--- | :--- | :--- | :--- |
| `sha256` | **缺失** | 必须 | 直接对本地物理 PNG 文件计算 `hashlib.sha256(path.read_bytes()).hexdigest()` |
| `spine_asset_id` | `canonical_asset_id` | 必须 | 规范化为 `spine_asset_id` |
| `character_resource_id`| **缺失** | 必须 | 通过官方 `CharacterMasterResolver` 与 `CostumeRegistry` 精确解析（如 `c010` -> `10`） |
| `character_name` | **缺失** | 建议 | 关联官方 `CharacterMaster` 获取权威角色中英文名称 |
| `costume_id` | **缺失** | 必须 | `CostumeRegistry` 严格解析；原皮为 `null`，服装为官方 ID（如 `10005`, `20001`） |
| `costume_name` | **缺失** | 建议 | `CostumeRegistry` 官方登记服装名称（如 `White Promise`） |
| `is_costume` | **缺失** | 必须 | 布尔标识，指示是否为服装立绘 |
| `local_relpath` | 仅文件名 | 必须 | 相对于仓库根目录的标准路径（防路径穿越） |
| `format` | **缺失** | 必须 | 固定为 `"png"`，经 Pillow/魔数核验 |
| `verification` | **缺失** | 必须 | `"local_revalidated"` 标明经全量重新审计验证 |
| `alpha_bbox` | 存在 | 保留 | 继承原始渲染画布或 Pillow `getbbox()` 边界 |
| `runtime_version` | 存在 | 保留 | 保留 4.0 / 4.1 原始 Spine 骨骼运行时版本 |

---

## 3. 物理文件审计与真实 SHA-256 汇总

所有 8 个预渲染 PNG 均位于 `assets/spine-rendered/`。经独立脚本直接读取实际二进制字节，校验 PNG 魔数（`\x89PNG\r\n\x1a\n`）与 Pillow 解码验证，计算得出真实 SHA-256：

| 资产 ID | 物理文件名 | 尺寸 | 文件大小 | 完整 SHA-256 哈希 | 权威身份 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `c010` | `c010.png` | 425x891 | 313,219 B | `fb05dccee549af72da59b33d6181d2f47d19302caf98ed364e3d216e2c21a0c3` | 拉毗 (Rapi, resource_id=10, 默认) |
| `c010_02`| `c010_02.png`| 426x892 | 357,301 B | `623ec249fce5441f19f4b181556410ce6c0f3f6c1b738730f4319e2eb7571258` | 拉毗 (Rapi, resource_id=10, 服装: White Promise, ID: 20001) |
| `c010_03`| `c010_03.png`| 467x892 | 282,682 B | `0ef8d58e0484b687f72c6e19f3cf91e470bac08f735cc1bc1ef78f0117f7dbeb` | 拉毗 (Rapi, resource_id=10, 服装: Classic Vacation, ID: 10005) |
| `c017` | `c017.png` | 348x891 | 282,276 B | `0f031045cf1268526ecc5ae6b59bb5236489e1325e5999d4f6d220009eda6886` | 阿妮斯：超级巨星 (Anis: Star, resource_id=17, 默认) |
| `c234` | `c234.png` | 602x891 | 618,240 B | `ddf9e9f84fff65f0e16f1559808c2e414ee1ff5d37169dbc58a18f0338b6e3b4` | 桃乐丝：机缘巧遇 (Dorothy: Serendipity, resource_id=234, 默认) |
| `c330` | `c330.png` | 794x885 | 594,100 B | `3b42e870819fb81278caad9401b42b1b699558a2f51f566b4d31e85ae1609dbe` | 皇冠 (Crown, resource_id=330, 默认) |
| `c352` | `c352.png` | 657x892 | 569,464 B | `0a817a46efbd864c456afbe6f34d6fbe4ce2cd022e2a517ebbc1f1dd15804b0f` | 海伦 (Helm, resource_id=352, 默认) |
| `c471` | `c471.png` | 618x887 | 479,770 B | `63bc619f215fc84544c9e185e4a005ecab8f5c1dac5eb06d9f47d2f959a6f5aa` | 白雪公主：重型武装 (Snow White: Heavy Arms, resource_id=471, 默认) |

---

## 4. 身份映射与冲突审查

1. **零文件后缀猜测**:
   严禁根据文件名 `cXXX_YY` 猜测角色或皮肤关系。所有的映射全部经由官方 `assets/character_master.json` 与 `assets/costumes.json` 的权威登记条目进行双向闭包验证。
   - `c010_02`: 在 `costumes.json` 中明确登记为 `costume_id: "20001"`, `character_resource_id: "10"`, `costume_name: "White Promise"`。
   - `c010_03`: 在 `costumes.json` 中明确登记为 `costume_id: "10005"`, `character_resource_id: "10"`, `costume_name: "Classic Vacation"`。
2. **零身份冲突 (Conflict Count = 0)**:
   没有两个不同的 Spine 文件声明相同的 `(character_resource_id, costume_id)`。
3. **零损坏文件 (Corrupt Count = 0)**:
   全部 8 个文件均具备标准 PNG 文件头，未受任何截断或损坏。
4. **零缺失文件 (Missing Count = 0)**:
   Manifest 中声明的 8 个条目在磁盘上均真实存在。

---

## 5. 覆盖率统计

- **默认角色预渲染覆盖率**: 6 / 200 (3.0%)
- **服装预渲染覆盖率**: 2 / 40 (5.0%)
- **当前预渲染总数**: 8 张
- **已核验证明总数**: 8 张 (100%)
- **哈希匹配率**: 100%

未预渲染的 194 位角色及 38 款服装在热路径中受 `AssetManager` 保护，返回标准化占位素材，严禁在线发起动态 Spine 渲染或网络请求。

---

## 6. 维护工具与原子写入保证

为防止后续人工维护或自动化同步引入格式错漏，已建立专用维护脚本：
`scripts/rebuild_spine_render_manifest.py`

- `python scripts/rebuild_spine_render_manifest.py --audit-only`：只读审查，输出诊断，返回码反应是否存在损坏/缺失。
- `python scripts/rebuild_spine_render_manifest.py --write`：使用临时文件写入、校验无误后通过 `os.replace` 原子替换原文件，杜绝写入中断导致 manifest 损坏。
- `python scripts/rebuild_spine_render_manifest.py --verify`：全量回读校验磁盘上的 manifest 与物理文件的一致性。
