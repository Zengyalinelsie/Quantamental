# ADR-0012：Screen 构建器的只读投影与受治理 scratch 通道

- 状态：Accepted
- 日期：2026-08-15
- 决策者：用户（2026-08-15 明确要求「按最正规最成熟的做法」）
- 相关：`docs/plans/track-00-prototype-runtime-delivery.md` PUI-02、`docs/18` §研究工作区、
  ADR-0006（研究基线与评估政策）、`AGENTS.md` 可追溯性边界

## 背景

Figma `research-universe-screen`（node `3:726`）的左栏 `screen-builder`（320 × 584）包含：

- 股票池范围选择（沪深300）；
- 行业多选（申万一级）；
- **核心维度权重配比**：Quality 40% / Valuation 30% / Improvement 30%；
- **流动性门槛**：> 5000 万 CNY（20 日日均成交额）；
- **排除硬性条件**：ST/*ST、停牌/异常波动、次新股（上市 < 1 年）；
- **「运行 Screen（计算因数重排）」按钮**。

当前后端 `ResearchWorkspaceProjectionService` 只读**已冻结、已绑定审批 scope 的
`SignalSnapshot`**。排名是版本化产物，可追溯到 `factor_version_ids`、`factor_review_ids`、
`model_version_id`、`run_id` 和 `approval_scope`。

两者存在直接冲突：原型的运行按钮意味着「用户随手改权重 → 立即得到新排名」，而该产物没有
定义版本、没有 Run 记录、没有审批用途，因此违反 `AGENTS.md`：

> 所有生产数字可追溯到数据版本、公式/模型版本、代码版本和运行记录。

同时存在一个更实质的问题：**P4 因子资格门未通过**。最新三条 `ExperimentRun` 均失败，
`FactorVersion` 保持 draft，没有合格的 factor score、IC 或 RankIC。即使实现了权重输入，
后端也没有合格因子可用于重算 —— 产出的排名将是工程占位而非研究结论。

## 决策

采用机构量化平台的标准做法：**read model 与 write model 分离**，并按阶段实施。

### 第一阶段（本 ADR 生效范围，PUI-02 当前实现）

构建器**按 Figma 布局完整存在**，但语义为**只读展示当前已冻结 Screen 的实际参数**，而非可编辑输入：

- 展示该 `SignalSnapshot` 实际使用的 `factor_version_ids` 及其 lifecycle 与审批状态；
- 展示 `universe_version_id`、`universe_size`、`decision_time`、`data_cutoff`；
- 展示 `approval_scope`、`trust_state`、`model_version_id`；
- 没有合格 Snapshot 时，构建器各分区显示真实 `empty` / `unavailable` 与 blocker，
  **不显示 Figma 的 40%/30%/30% 示例权重**，不显示「> 5000 万 CNY」等示例阈值；
- **不渲染「运行 Screen」按钮**，因为该动作在当前阶段没有合法实现。

理由：已审批快照是"排名"在本平台的唯一权威定义。先把它显示正确，再谈探索。

### 第二阶段（P4 因子资格门通过后，另行实施）

引入 scratch / governed 双通道，届时可编辑构建器成为合法功能：

| 通道 | 产物 | 可用范围 | 视觉要求 |
|---|---|---|---|
| `governed` | 已审批 `SignalSnapshot` | 组合、回测、报告、Paper | 正常呈现 |
| `scratch` | 临时探索结果 | **仅当前会话研究探索** | 必须显著标注未审批；不可导出；不可进入组合 |

第二阶段的强制要求（不得省略）：

1. 用户提交的权重、门槛与排除规则必须先落为 **`ScreenDefinition` 版本对象**（含 content hash），
   不允许匿名参数直接进入计算；
2. 每次运行必须产生 **`Run` 记录**，记录定义版本、代码版本、数据版本、执行时间与执行者；
3. scratch 产物必须携带 `approval_scope = null` 或等价的"未审批"标记，
   服务端**拒绝**将其用于组合构建、回测导出或任何 `paper`/`live` 路径；
4. scratch 与 governed 结果**不得在同一视觉层级并列呈现**，避免误读为同等可信；
5. 权重重算只能使用已通过 P4 资格门的 `FactorVersion`；未晋级因子不得参与打分；
6. 第二阶段实施前必须更新本 ADR 状态或新增 ADR，不得凭本 ADR 第二阶段描述直接开发。

### 明确禁止（两个阶段均适用）

- 不得在前端计算或重算 rank、score、rank_change 或分项贡献；
- 不得把 Figma 的 40%/30%/30%、96.3%、5000 万 CNY 等 DESIGN FIXTURE 值写入运行时；
- 不得为了让构建器"看起来完整"而填入默认权重；缺失即显示缺失；
- 不得在 P4 资格门未通过时提供任何形式的因子重算入口。

## 后果

### 正面

- 当前实现完全符合 `AGENTS.md` 可追溯性与 `docs/07` 的信任边界，无需返工；
- 页面结构与 Figma 一致，用户可获得原型表达的信息架构；
- 第二阶段的治理设计已明确留档，届时不会临时拼凑；
- 避免在没有合格因子时产出无意义的排名数字。

### 负面

- 短期内用户无法在页面上调整权重进行探索。这是**有意的**：在 P4 资格门通过前，
  可调权重只能产生不可信数字；
- Design Parity 必须记录该差异：构建器为只读，且不渲染运行按钮；
- 第二阶段需要新的领域对象（`ScreenDefinition`）、存储与计算路径，是真实工程量，
  不能视为纯前端工作。

## 备选方案与否决理由

**A. 直接实现可编辑构建器并即时重算。** 否决：产出无版本、无审批、不可追溯的数字，
违反 `AGENTS.md`；且 P4 未过，无合格因子可算。

**B. 前端本地计算权重排名。** 否决：违反"前端只消费服务端投影，不重算排名"的既有约束
（`CLAUDE.md` §3.4、§11），并会建立第二个排名真源。

**C. 构建器留空或整体隐藏。** 否决：丢失原型表达的信息架构，且无法向用户说明当前
Screen 实际使用了哪些因子与参数 —— 而这正是审计场景最需要的信息。

**D. 用 Figma 示例值占位。** 否决：DESIGN FIXTURE 进入运行时，`AGENTS.md` 与 track-00 明确禁止。

## 分项贡献列的合法来源（实现说明）

Figma 排名表包含 `质量`、`估值预期差`、`改善`、`60日预期收益区间` 四列，当前
`ScreenRankingRowProjection` 未投影这些字段。

它们**不需要新建数据**：`InvestmentView.components` 已包含
`InvestmentComponent(name, status, expected_return_contribution, evidence_ids, status_reason)`，
且 `SignalSnapshot.investment_view_id` / `investment_view_hash` 已绑定到具体已冻结 View。

因此服务端可从**已冻结 View** 投影这四列，完全可追溯，不构成新的计算或新的真源。
`status` 为 `unavailable` / `not_applicable` 的分项显示 `—`，**不填 0**。
