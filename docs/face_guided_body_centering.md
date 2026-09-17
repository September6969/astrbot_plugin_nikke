# Character Card：Face-Guided Whole-Character Centering v5

> 状态：**生产预览接入（Opt-in Preview） / 接入 `face_anchor.framing(..., body_centering=...)` / 默认严格 OFF**  
> 第一阶段：**X-only，`vertical_gain=0`**  
> 核心原则：**Face Anchor 是硬约束；Body Axis 只能提供保守的二次平移建议。**

## 1. 主链路

```text
Spine eye/head anchor
→ offline face_anchors.json
→ existing face-first scale + left/top
→ v5 face-local bootstrap
→ alpha body-axis tracking
→ confidence gate
→ face-safety clamp
→ bounded X-only translate
```

不修改 scale，不运行时解析 Spine，不重新做人脸识别。

## 2. v5 新增不变量

**一个从 face/neck 区域开始的中等单侧连接附件，不能仅因为总宽度稳定且未超过极端 full/core 比例，就成为可信主体尺度。**

v4 的：

```text
full_width > core_width * 2.25
```

只适合识别明显超宽附件。

v5 增加左右半宽证据，而不是直接降低 `2.25`。

## 3. Half-width balance

对包含 `face_x` 的 run：

```text
left_radius  = face_x - run.left
right_radius = run.right - face_x

half_balance = min(left_radius, right_radius)
               / max(left_radius, right_radius)
```

默认：

```python
bootstrap_min_half_balance = 0.48
```

如果：

```text
half_balance < bootstrap_min_half_balance
```

该行被标记为 bootstrap contamination。

但这里的语义不是“检测到了武器”，而是：

> alpha 证据不足以把完整宽度当成可信人体尺度。

因此只保留：

```text
effective_width = 2 * min(left_radius, right_radius)
```

作为 tentative scale。

## 4. Clean evidence

Bootstrap reliable 不再仅由 width cluster 决定。

至少需要：

```text
clean rows >= bootstrap_min_clean_rows
clean rows / local rows >= bootstrap_min_clean_fraction
clean seed width cluster stable
```

默认：

```python
bootstrap_min_clean_rows = 3
bootstrap_min_clean_fraction = 0.20
bootstrap_max_cluster_ratio = 1.85
```

如果缺少 clean evidence：

```text
bootstrap_reliable = false
```

分析仍返回诊断，但 confidence 强制衰减，默认配置 no-op。

## 5. 为什么不要求最近 face rows 必须对称

Eye/head anchor 不保证位于 alpha face silhouette 的几何中央。

普通侧脸或偏头可能出现：

```text
face_x != local_run_midpoint
```

因此 v5 会扫描整个**小型 face/neck bootstrap band**寻找 balanced rows，再取距离 face 最近的 clean rows 建 seed。

这让几行不对称的头部轮廓可以被容忍，只要稍低处存在独立、稳定的 neck/torso 证据。

## 6. Fail-closed 边界

如果附件在 clean face/neck evidence 之前已经接入：

```text
没有 clean scale evidence
→ bootstrap_reliable=false
→ low confidence
→ preserve face-anchor-only composition
```

如果 clean seed 已先建立，而附件稍后接入：

```text
bootstrap reliable
→ v3/v4 tracker width-growth + untrusted-span protections
→ connected accessory cannot accumulate drift
```

## 7. 已知不可辨识区

仅从 RGBA alpha + 一个 face point，某些几何本身不可唯一解释：

```text
轻微单侧附件
vs
face anchor 在侧脸/偏头时天然偏离 silhouette 中轴
```

因此 v5 不宣称对所有轻微单侧扩张都能分类正确。

当前合成 sweep 中：

```text
half_balance >= ~0.48
```

的边界案例仍可能获得小幅修正；回归限制其最终卡面位移 `<20px`。

这个区间必须由真实 NIKKE 立绘决定是否继续收紧。

## 8. 后续 tracker 不变量

继续保留：

- raw geometry continuity；
- connected wide-run freeze；
- untrusted span termination；
- long transparent vertical gap termination；
- symmetric split-leg midline；
- transparent padding invariance；
- Face Safety；
- `scale` 永远不变；
- 默认 `vertical_gain=0`。

## 9. 默认关键参数

| 参数 | 默认值 |
|---|---:|
| `body_target_x` | 800 |
| `alpha_threshold` | 24 |
| `bootstrap_band_ratio` | 0.18 |
| `bootstrap_seed_rows` | 7 |
| `bootstrap_core_expansion` | 2.25 |
| `bootstrap_min_half_balance` | **0.48** |
| `bootstrap_min_clean_rows` | **3** |
| `bootstrap_min_clean_fraction` | **0.20** |
| `bootstrap_max_cluster_ratio` | 1.85 |
| `max_width_growth_ratio` | 1.75 |
| `max_untrusted_span_ratio` | 2.75 |
| `horizontal_gain` | 0.72 |
| `vertical_gain` | **0.0** |
| `min_confidence_for_shift` | **0.45** |
| `max_shift_x` | 140px |

这些值仍是候选值，不是生产最优值。

## 10. 生产接入前门槛

真实资产 A/B 必须至少输出：

```text
before / after / overlay
body_axis_x
bootstrap_width
bootstrap_reliable
bootstrap_clean_rows
bootstrap_clean_fraction
bootstrap_half_balance
bootstrap_contaminated_rows
confidence
path_coverage
path_continuity
width_reliability
terminated_early
applied_shift_x
```

重点覆盖：普通直立、真实侧脸、偏头、斜姿态、肩部相连枪械、短附件、长附件、长发、披风、宽裙摆、分腿、透明空间较大的皮肤，以及 `拉毗：小红帽` Golden Sample。
