# Card-space Correction Policy 离线评估与证据库说明

本文档基于现有 36 个跨 8 类视觉特征的原型立绘样本（真实 Spine 离线渲染与权威面部锚点），记录 **Card-space Correction Policy** 的离线评估结果、对比图谱、评估指标及人工复核协议。

> [!IMPORTANT]
> **生产状态严格声明**：
> 1. 本评估为**纯离线实验**，禁止将任何候选参数接入生产。
> 2. `face_guided_centering.py`、`DEFAULT_CENTERING_CONFIG` 及 Face Safety 生产配置保持完全不变。
> 3. Body Centering 在生产环境中继续保持严格默认 **OFF**。

---

## 一、核心术语与语义修正 (Terminology Clarification)

在证据链与文档中：
* **`confidence` / `tracking_confidence`**：
  * **真实语义**：表示 **Alpha Path 轮廓追踪过程中的内部几何稳定性**（包含头部/颈部 bootstrap 纯净度、路径垂直连通性、轮廓对称度与宽度平滑度）。
  * **严正声明**：**它绝对不表示最终卡面构图的“美学正确概率”或“构图合理性概率”**。
  * **背景说明**：当角色拥有密实、大面积且与躯干无断裂连通的单侧外挂物（如小红帽的披风、重装白雪的反器材主炮、皇冠的浮游翼披风）时，Tracker 会“高置信度”地把外挂物连同身体一并识别为平滑连通的整体，从而给出高达 >0.95 的 `tracking_confidence`，但却导致卡面发生高达 70~130px 的过度偏移。
  * **代码兼容性**：保留内部数据与 API 字段名 `confidence` 以确保测试与调用兼容，但在展示与评审时统一解释为 `tracking_confidence`。

---

## 二、候选策略定义 (Candidates A - E)

针对卡面空间（Card Space）的位移修正策略设计了 5 套对比方案：

1. **`Policy A` (Baseline)**:
   * 纯 Face Anchor 基线，位移量 $\Delta x = 0.0\text{ px}$。
2. **`Policy B` (Raw v5)**:
   * 当前 v5 算法输出的原始卡面未截断位移（$\Delta x = \text{applied\_shift\_x}$）。
3. **`Policy C` (Soft-Cap 20 / 40)**:
   * 连续光滑软截断：Knee = 20px, Cap = 40px。
4. **`Policy D` (Soft-Cap 16 / 32)**:
   * 连续光滑软截断：Knee = 16px, Cap = 32px。
5. **`Policy E` (Soft-Cap 24 / 48)**:
   * 连续光滑软截断：Knee = 24px, Cap = 48px。

### Soft-Cap 连续映射函数
$$\text{SoftCap}(\Delta x) = \begin{cases}
\Delta x, & \text{if } |\Delta x| \le \text{knee} \\
\operatorname{sgn}(\Delta x) \cdot \left[ \text{knee} + (\text{cap} - \text{knee}) \cdot \tanh\left( \frac{|\Delta x| - \text{knee}}{\text{cap} - \text{knee}} \right) \right], & \text{if } |\Delta x| > \text{knee}
\end{cases}$$
* 该函数在转折点 $\Delta x = \pm\text{knee}$ 处满足 $C^0$ 连续且导数一阶连续（$C^1$ 光滑，左右导数均为 $1.0$），随输入趋近无穷渐近收敛于 $\pm\text{cap}$，避免了硬截断带来的突兀视觉折线。

---

## 三、生成制品与目录结构

本目录下包含以下离线评估制品：

1. **`{render_id}_policy_compare.png` (共 36 份)**:
   * 采用 5 列并排高清看板：`Baseline (A) | Raw v5 (B) | Policy C | Policy D | Policy E`。
   * 每张卡片均使用 1600×2400 原生立绘与同一 Face Anchor，顶部清晰展示样本身份、分类、`tracking_confidence` 语义提示及各列精确位移量。
   * 图像包含绿色基准中线（Baseline Reference）与品红色实际位置指示线（Candidate Shifted Line）。
2. **`policy_metrics.csv` / `policy_metrics.json`**:
   * 记录全部 36 样本 × 5 策略（共 180 条记录）的指标数据：
     - `render_id`, `canonical_name`, `category`, `policy`
     - `original_v5_shift`, `candidate_shift`, `difference_from_v5`
     - `face_x_after`, `face_safe`
     - `new_edge_clipping`, `has_new_edge_clipping`
     - `tracking_confidence`
3. **`policy_review.csv`**:
   * 人工复核表格，严格包含字段：
     `render_id,canonical_name,category,baseline_vs_raw,baseline_vs_C,baseline_vs_D,baseline_vs_E,reviewer_note`
   * 评价值仅允许：`better`、`same`、`worse`、`unreviewed`。
   * **初始状态全量设为 `unreviewed`**，禁止脚本预填或假定优劣。
4. **`policy_statistics.json`**:
   * 汇总 5 套策略的纯几何统计分布（中位数、P75、P90、最大值、各分桶占比）。

---

## 四、各 Candidate 几何位移统计

> 注：在人工 / Astra 审美复核完成前，仅客观展示几何指标，**绝不根据几何数值单方面决定策略胜出者**。

| 策略代码 | 策略配置 | 中位数绝对位移 | P75 | P90 | 最大位移 | $>20\text{px}$ 样本数 | $>40\text{px}$ 样本数 | $>80\text{px}$ 样本数 |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **A** | Baseline (No Centering) | 0.00 px | 0.00 px | 0.00 px | 0.00 px | 0 / 36 | 0 / 36 | 0 / 36 |
| **B** | Raw v5 (Uncapped) | 41.22 px | 85.77 px | 109.06 px | 130.62 px | 25 / 36 | 18 / 36 | 12 / 36 |
| **C** | Soft-Cap (20 / 40) | 35.70 px | 39.94 px | 39.99 px | 40.00 px | 25 / 36 | 0 / 36 | 0 / 36 |
| **D** | Soft-Cap (16 / 32) | 30.67 px | 31.99 px | 32.00 px | 32.00 px | 25 / 36 | 0 / 36 | 0 / 36 |
| **E** | Soft-Cap (24 / 48) | 38.75 px | 47.72 px | 47.96 px | 47.99 px | 25 / 36 | 17 / 36 | 0 / 36 |

---

## 五、复核与后续决策流程

1. **由美术/产品/Astra 评审人** 审阅 36 份 `{rid}_policy_compare.png`。
2. 填写 `policy_review.csv`，对各策略相对于 Baseline 的视觉观感标注 `better` / `same` / `worse`，并记录备注。
3. 结合人工复核结果与边缘裁切风险，再行决定是否将最佳 Policy 的阻尼参数收敛至生产逻辑中。
