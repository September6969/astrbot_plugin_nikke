# 六项 Guide / Help 素材验收

状态：`READY_OFFLINE`（2026-09-08）。用户已明确授权公开仓库收录及机器人发送；本 PR 没有实际发送 QQ 消息或部署。

## 路由与输出

- `progression`：养成一图流，6 段。
- `red_orbs`：仅输出 `https://nikkeoutpost.netlify.app/`，不抓取或复制站点内容。
- `favorite`：珍藏品养成，1 张。
- `arena_charge`：充能表，3 段。
- `overload`：洗词条教学，5 段。
- `pvp`：PVP 配队，1 张。

支持中英文及常见中文别名。输出顺序固定为分页信息 → 标题/版本/来源/作者/授权 → 图片分段或链接。

## 完整性与安全

- 原件保留在 `E:\walkthrough`；仓库只提交处理副本。
- `scripts/import_walkthrough_assets.py` 在处理前核对五张图片的固定 SHA-256，使用 120 像素纵向重叠，并拒绝任何超过 12 MiB 的输出。
- `assets/guides/source_manifest.json` 记录每个源文件的 SHA-256、字节数、分段裁切范围、输出 SHA-256、署名、登记日期与授权。
- `GuideRegistry` 要求每条记录至少有图片或链接。链接只允许 HTTPS、无嵌入凭据且 hostname 严格为 `nikkeoutpost.netlify.app`；图片仍防目录逃逸、扩展名伪装和超大文件。
- 保留原图可见署名。养成图登记为“屑芙蒂（原图可见署名）”，充能/PVP/珍藏品登记为“迪恩deen33（原图可见署名）”；洗词条标记“用户授权提供，原图未署名”。

## 视觉检查

已逐张查看全部 16 个输出：文字可读、首尾完整、分段顺序稳定，相邻段均有 120 像素重叠；可见署名未裁掉。没有把外部站点内容复制进仓库。

`NEEDS_LIVE_EVIDENCE`：实际 QQ 平台逐图大小限制、客户端压缩后的可读性和发送顺序。最小现场动作是获准后在测试会话手动请求六类各一次并核对送达；本 PR 未执行。
