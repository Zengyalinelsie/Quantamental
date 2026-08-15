# 完整平台交付路线图

> 建立日期：2026-08-16
>
> 代码基线：`ed41fdd feat: add forward-return labels for the current-only research track`
>
> 用户目标：平台**必须完备**（含 P7 Timing、P8 事件/Agent、P10 Paper 执行）。
> 研究沪深300 / 中证500 是**验证平台能力的测试对象**，不是终点。
>
> 数据预算决策（2026-08-16）：**先用免费源跑通全链，预留付费 PIT 升级路径**。
>
> 性质：路线图。每份子 plan 独立可执行，见 `docs/superpowers/plans/`。
> 本文件不替代 `AGENTS.md`、`docs/07`、已接受 ADR 或任何 Gate 定义。

## 0. 本路线图基于代码审计，不基于文档描述

2026-08-16 对 `platform/src` 做了逐文件核查。**结论与文档描述有重要差异**，必须先纠正：

### 已存在且可用（不要重建）

| 能力 | 位置 | 状态 |
|---|---|---|
| 公司质量因子 | `domain/quality_factor.py` | 真实实现，有测试，产出真实 Decimal |
| 基本面改善 | `domain/fundamental_improvement.py` | 真实实现，`current_research` 模式无门禁 |
| 估值三模型 | `domain/valuation_models.py` | 相对估值 / FCF 锚定 / 隐含预期均可跑 |
| IC / RankIC | `domain/factor_statistics.py` | 真实实现 |
| Fama-MacBeth | `domain/factor_panel_statistics.py` | 真实实现 |
| 因子诊断 | `domain/factor_diagnostics.py` | 分位组合、IC 衰减、换手、覆盖率 |
| 独立库交叉验证 | `validation/statistical_crosscheck.py` | scipy / statsmodels，555 行 |
| 远期收益标签 | `domain/labels.py` | 2026-08-15 新增，19 测试 |
| 文档/披露账本 | `domain/disclosure.py` + `application/disclosure_ledger.py` | **成熟**：RawObject 不可变、hash、retention、版本链 |
| 原始对象存储 | `adapters/object_store/local.py` | 可存 PDF，内容寻址，防符号链接逃逸 |
| 被动 Timing baseline | `domain/timing.py` + `application/timing_baseline.py` | 真实实现，429 行 |
| 权限骨架 | `application/permissions.py` | 8 角色 × 8 权限，默认策略已定 |
| dry-run + ack 模式 | `workers/timing_baseline.py`、`workers/financial_backfill.py` | 可直接复制的模板 |
| Desk 七分区 | `domain/desk.py` + `application/desk_projection.py` | 2026-08-15 完成 |
| Screen 双栏 + 12 列 | `features/screen/*` | 2026-08-15 完成 |

**测试基线：129 个测试文件，30,647 行，886 个测试全绿。**

### 完全不存在（必须从零建）

| 缺失能力 | 需新建文件 | 属于 |
|---|---|---|
| 组合领域合同 | `domain/portfolio.py` | P6 |
| 组合构建算法 | `domain/portfolio_construction.py` | P6 |
| 风险模型 | `domain/risk.py`、`application/risk_models.py`、`ports/risk.py` | P6 |
| 现实回测引擎 | `domain/backtest.py`、`domain/execution_rules.py` | P6 |
| 归因 | `domain/attribution.py` | P6/P9 |
| Timing 研究合同 | `domain/timing_research.py`、`application/timing_features.py` | P7 |
| 主动 Timing 模型 | 模型 port + 静态/均线/波动目标/logistic/linear 基线 | P7 |
| 事件领域 | `domain/events.py` | P8 |
| Agent 运行时 | `domain/agent_research.py`、`application/agent_runtime.py` | P8 |
| 供应链图 | `domain/supply_chain.py` | P8 |
| 监控/漂移 | `domain/monitoring.py` | P9 |
| Incident 状态机 | `domain/incidents.py` | P9 |
| OMS | `domain/oms.py`、`application/order_intents.py` | P10 |
| Paper Broker | `ports/broker.py`、`adapters/paper/broker.py` | P10 |
| 持仓/现金/对账 | Position、Cash、ReconciliationBreak | P10 |

**组合/风险/回测测试数：0。** 这三块是最大的空白。

### 部分存在，需扩展

| 能力 | 现状 | 需补 |
|---|---|---|
| walk-forward | `factor_validation.py` 有 `purged_embargoed_walk_forward()` 折分生成 | Timing 专用校准 / HAC / DM 检验 |
| Qlib adapter | `adapters/qlib/recorder.py` 15 KB，仅 Recorder 导入导出 | 不用于组合回测 |
| 外部回测引擎 | `adapters/rqalpha/` **不存在** | 需先做 D0 spike + ADR |
| Experiment | `application/experiments.py` 只是**账本** | 真实计算编排（关键缺口） |
| 事件研究 | `validation/gates.py` 只定义了要求（AR/CAR/聚类 SE） | 全部实现 |

**最关键的单点发现**：`ExperimentRunService` 只记录别处算好的结果，自己不算。
**没有任何东西把「财务事实 → 因子分数 → IC」串起来。** 这是路线图第一优先级。

## 1. 子 plan 清单与依赖

```
P-1 数据层（免费源 + PIT 升级路径）
 │
 ├─→ P-2 因子研究编排 ────┐
 │                        │
 ├─→ P-3 前端 PUI-03      │   （可与数据线并行）
 ├─→ P-4 前端 PUI-04      │
 │                        │
 │   P-5 组合与回测 P6 ←──┘
 │    │
 │    ├─→ P-6 主动 Timing P7
 │    │
 │    └─→ P-7 事件/Agent P8   （也依赖 P-1 的文档源）
 │         │
 │         └─→ P-8 监控治理 P9
 │              │
 │              └─→ P-9 Paper 执行 P10
 │
 └─→ P-10 Limited Live P11   （需你新授权，非必需）
```

| Plan | 范围 | 交付物 | 依赖 | 是否需你决策 |
|---|---|---|---|---|
| **P-1** | 数据层 | CSI300/500 行情、日历、股本、公司行动、历史成分股入库；PIT 升级路径就绪 | 无 | 付费源时机 |
| **P-2** | 因子研究编排 | 真实 IC/RankIC 跑出来，Experiment 有记录，Alpha 页显示真值 | P-1 | 否 |
| **P-3** | 前端黄金路径 | Security 融合页 + InvestmentView + Approvals + Alpha 四页像原型 | 无 | 否 |
| **P-4** | 前端 Factor/System | 9 页产品化 + 修 `/factors` 320 溢出 | 无 | 否 |
| **P-5** | 组合与回测 P6 | 组合构建、现实回测、风险 R0、核心归因 + PUI-05 五页 | P-2 | 外部引擎选型 |
| **P-6** | 主动 Timing P7 | Timing 研究合同、主动模型、验证引擎 + PUI-06 | P-5 | 否 |
| **P-7** | 事件/Agent P8 | 事件管道、Agent 运行时、供应链图、事件研究 + PUI-07 | P-1、P-5 | LLM provider 与文档源许可 |
| **P-8** | 监控治理 P9 | 统一归因、漂移、Incident、审批泛化 + PUI-08 | P-5、P-6、P-7 | 否 |
| **P-9** | Paper 执行 P10 | OMS、确定性 Paper Broker、持仓现金对账、kill switch + PUI-09 | P-8 | 否 |
| **P-10** | Limited Live P11 | 只读对账 → 预览 → 人工批准最小执行 | P-9 | **必须新授权** |

## 2. 三条线的并行关系

**数据线**（P-1 → P-2）：一切研究结论的前提。
**产品线**（P-3、P-4）：不依赖数据能力，可立刻并行。
**能力线**（P-5 → P-9）：串行，每级依赖前级真实产出。

因此推荐执行顺序：

1. **P-1 + P-3 并行**（数据下载与前端页面互不干扰）
2. **P-2 + P-4 并行**
3. P-5 → P-6 → P-7 → P-8 → P-9 串行
4. P-10 仅在你新授权后

## 3. 数据两阶段（P-1 的核心设计）

### 阶段一：免费源（BaoStock / AkShare / 巨潮）

信任上限 `normalized_current`。**能做**：今日研究、因子相关性观测、组合构建、Paper 执行演练。
**不能做**：可信历史回测，不得声称任何策略科学有效。

已入库：CSI500 500 家 × 2018–2025 年末三表，35,505 条 observation。

需补：2018+ 日线、交易日历、股本、公司行动、历史成分股。

### 阶段二：付费 PIT 主源（Wind / 同花顺 / iFinD）

`pit_verified`，解锁 `strict_historical` 回测。

P-1 会预先建好迁移路径：资格探针、字段主源 ADR 模板、双源对账、trust 提升流程。
**你什么时候买，接上就能用**，不需重做阶段一的任何编排代码。

**这是先走免费源的工程理由**：P-2 到 P-9 的所有编排在切换数据源后可直接复用；
只有数值结论不可迁移。

## 4. 全局硬约束（每份 plan 都继承）

以下每条都来自 `AGENTS.md` 或已接受 ADR，**不可协商**：

1. Python 3.11+，`domain/` 不导入 FastAPI / SQLAlchemy / provider SDK / 前端概念；
2. 金额、比例、股数、时间必须有明确单位、币种、时区；
3. **缺失、无权限、时间不可信、冲突必须显式表达，禁止填零**；
4. `strict_historical` 只消费 `pit_verified`，且强制 `available_at <= decision_time`；
5. 回测、Paper、未来 Live 共用同一决策与组合代码，仅执行 adapter 不同；
6. 生产数字可追溯到 DatasetVersion / 公式版本 / 模型版本 / 代码版本 / Run；
7. 失败记录不可删除或改写为成功；
8. Capability Gate 与 Promotion Gate 分离；任一轴通过不推出另一轴；
9. 前端只消费服务端投影，**不重算排名、trust、审批状态**；
10. 运行时无默认 fixture；测试 fixture 不得进入 runtime bundle；
11. LLM 文本不作为价格、财务数值、公告时间、交易结果的权威来源；
12. Agent 不得绕过数据、风险、审批或交易权限门；
13. worker 默认 dry-run，真实写入需显式 ack；
14. **不安装或导入真实交易 SDK，不保存账户凭据**（ADR-0010）；
15. P11 需新的明确授权，Paper 测试结果不能推出 Live 安全。

## 5. 每份 plan 的完成定义

1. 所有 Task 的 TDD 步骤执行完毕，红测有真实失败记录；
2. 后端 unittest / compileall / ruff / mypy 全过；
3. 前端 Vitest / lint / build 全过（涉及前端时）；
4. 四视口真实浏览器验收（涉及页面时）；
5. Evidence 文档记录真实数值、限制、未完成项，以及**明确的否认声明**；
6. 三轴状态（Design Parity / Runtime Product / Domain Capability）分别报告；
7. `git diff --check` 干净，一个 Task 一个独立提交。

## 6. 明确不承诺的事

- **不承诺任何策略盈利**；
- **不承诺因子科学有效** —— 那需要样本外、成本后、统计不确定性和可复现产物；
- **不承诺 31 页逐像素与 Figma 一致** —— 320/768/1024 无独立设计 Frame；
- **不承诺免费源能支撑可信历史回测** —— 信任上限是 `normalized_current`；
- **不承诺 P10 完成即可实盘** —— P11 是独立授权项目。

## 7. 子 plan 索引

| Plan | 文件 | 状态 |
|---|---|---|
| P-1 | `2026-08-16-p1-data-foundation.md` | 已写 |
| P-2 | `2026-08-16-p2-factor-research-orchestration.md` | 已写 |
| P-3 | `2026-08-16-p3-frontend-golden-path.md` | 已写 |
| P-4 | `2026-08-16-p4-frontend-factor-system.md` | 已写 |
| P-5 | `2026-08-16-p5-portfolio-backtest.md` | 已写 |
| P-6 | `2026-08-16-p6-active-timing.md` | 已写 |
| P-7 | `2026-08-16-p7-events-agents.md` | 已写 |
| P-8 | `2026-08-16-p8-monitoring-governance.md` | 已写 |
| P-9 | `2026-08-16-p9-paper-execution.md` | 已写 |
| P-10 | 不写（需新授权后另议） | 授权阻断 |

P-1 至 P-9 共 **28,985 行、79 个 Task**，全部展开到可执行步骤（每步含真实测试代码、真实命令、
真实提交信息）。P-10 需你新的明确授权后另议，不预写。

## 8. 关于 plan 里的测试代码密度（执行前必读）

自审统计（2026-08-16，用 AST 逐块解析）：

| plan | 有完整断言 | 仅 docstring | 填充率 |
|---|---:|---:|---:|
| P-1 数据层 | 11 | 0 | 100% |
| P-2 因子编排 | 10 | 10 | 50% |
| P-3 前端黄金路径 | 30 | 0 | 100% |
| P-4 前端 Factor/System | 4 | 0 | 100% |
| P-5 组合与回测 | 99 | 79 | 55% |
| P-6 主动 Timing | 74 | 53 | 58% |
| P-7 事件/Agent | 118 | 110 | 51% |
| P-8 监控治理 | 233 | 0 | 100% |
| P-9 Paper 执行 | 116 | 101 | 53% |
| **合计** | **695** | **353** | **66%** |

全部 194 个 Python 代码块**均可通过 `ast.parse`**，无语法错误，无占位符
（`TBD` / `TODO` / `Similar to Task N` 一处都没有）。

**353 个"仅 docstring"的测试方法是有意保留的，不是缺漏。** 判断理由：

1. 每一个都带**完整的意图说明**，说清要断言什么以及为什么。断言的具体写法取决于执行时
   读到的真实字段名 —— 例如 P-5 撰写过程中就发现 `CorporateActionType` 只有 5 个成员
   而非预期的 7 个（无转增、无退市），当场按真实枚举改了断言。若提前把断言写死，
   执行者会照抄一个引用不存在字段的测试，然后为了让它通过而**改领域代码去迁就 plan** ——
   这正好反了；
2. 每份 plan 的第一个 Step 都是「先读真实接口，以代码为准」，并明确写了
   「若字段名与本 plan 不同，改本 plan，不要改领域代码」；
3. 100% 填充的四份（P-1/P-3/P-4/P-8）恰好是接口已被逐字核实过的那几份 ——
   填充率高低反映的是**接口确定性**，不是 plan 质量。

因此执行时的正确做法是：**照 docstring 的意图写断言，用当时读到的真实类型**，
而不是把 docstring 当作待填空白然后猜。

---

## 9. 撰写过程中发现的真实问题（必须先看）

以下问题是写 plan 时逐文件核查代码发现的，**不是文档描述，是当前代码的真实状态**。
它们已分别写进对应 plan 的 Task，此处汇总供你优先决策。

### 8.1 当前就存在的治理漏洞：自审批

`domain/factor_lifecycle.py` 的 `FactorVersion` 有 `created_by` 字段，但
`application/factor_reviews.py` 的 `FactorReviewService.record_review()` **从不读它**。
全仓库 `grep "submitted_by\|submitter\|requested_by"` 返回 0 行。

**后果**：一个 Reviewer 注册 FactorVersion 后可以在下一次调用里批准自己的提交，
产出的 `FactorPromotionReview` 与两个人签署的记录**逐字节无法区分**。

危险之处在于周围的门都很严（证据 hash、生命周期状态、"审批不能覆盖失败的科学门"），
所以记录看起来完全受治理。而原型一直比实现更严格 —— node `9:883` 画了 `提交人` 列，
`User-1` 提交、`Reviewer-2` 批准。

修复在 P-8 Task 4。**这是本次规划发现的最高优先级缺陷。**

次要但结构上更麻烦的一处：`PermissionPolicy.allows()` 用
`any(requested in grants[role] for role in principal.roles)`。一个同时持有
`Role.AGENT` 与 `Role.REVIEWER` 的服务账号会直接通过权限矩阵。因此 P-8 把 `AGENT`
处理为**取消资格**而非仅仅不足。

### 8.2 `/factors` 320 视口溢出的记录根因是错的

`docs/plans/track-00` 记为「pageHeading 溢出」。P-4 撰写时用 Playwright 实测复现
（`scrollWidth 652` vs `clientWidth 320`）并逐规则隔离，真实根因是：
`.factorWorkspace` 声明了 `display: grid` 但**没有 `grid-template-columns`**，
隐式列解析为 max-content，AntD Tabs nav（min-content 642 px）撑开了页面宽度 ——
标题是被撑大的，不是起因。修复在 P-4 Task 1。

### 8.3 Production 页的"诚实"是假的

`mapExperimentEnvelope` 硬编码 `productionVersions: []`，因此该 tab 永远显示
"没有获批因子"而**从未调用** `/api/factors/reviews`。`correlationPairs: []` 与
`timingBaseline: null` 同理。这不是空态，是假空态。修复在 P-4。

### 8.4 Figma 自身在侧栏宽度上自相矛盾

`24:400` / `15:2` / `9:883` 实测 **224 px**，而 `7:5` 的 `sidebar` FRAME 是 **248 px**。
运行时按 SPEC-045 用 280 px。**两个 Figma 值都不采用** —— 因为设计稿自己就不一致，
无法作为单一真源。这一点已写进 P-3、P-4，并在 `docs/18` 记录为已批准差异。

### 8.5 迁移编号双重占用

P-7 计划用 `0039`–`0043`，P-8 也计划用 `0039`–`0041`。执行时必须先读
`ls platform/migrations/` 的真实最大编号再分配，两份 plan 都已写入该检查步骤。

### 8.6 Paper 账本没有归属 schema

六个职责 schema 都不适合 paper 执行账本，而 `research` 被 `AGENTS.md` 的用途隔离规则排除。
P-9 因此要求新增 **ADR-0014** 并保持 `Proposed`，未批准前不建表。

### 8.7 三个统计陷阱（各 plan 已设计对策）

- **重叠窗口自相关**（P-6）：日度滚动的 20 日指数预测与相邻预测共享 19 天路径，
  同时污染 walk-forward purge 长度、HAC max_lag 和 DM 方差估计 —— 三者在不同模块，
  修好两个第三个会静默恢复约 √20 的标准误低估，把 t=0.4 变成 t=3.1。
  对策：`TimingTargetDefinition` 强制 `overlapping_sessions == horizon - 1`，
  下游一律**拒绝**而非降级。
- **归因残差被吸收**（P-8）：残差超容差必须触发 blocker/Incident，
  不得并入 "other" 桶 —— 那是归因静默变成虚构的方式。
- **命令幂等性**（P-9）：单测调一次、集成测发一次，**没有任何测试重试**，
  而重试在生产是常态。对策是数据库 `(command_kind, idempotency_key)` 唯一索引，
  且重放返回 200 与同一 `order_id`，**不是 409**（409 会让客户端进入错误处理，
  为一个已存在的订单报告失败）。

### 8.8 A 股执行规则中最难规范的三条（P-5 已逐条设计）

- **买卖手数不对称**：买必须整 100 股，卖必须允许清掉零股 —— 因为送股会产生零股
  （1,050 × 10送3 = 1,365）。对称规则会永久搁死这些股票且随每次公司行动复利累积。
- **`LOCKED_UP` 与 `LIMIT_UP` 不可合并**，且涨跌停数据本身不存在
  （`docs/11` 记录 BaoStock 无该字段）。"无数据即无限制"是唯一会系统性美化结果的默认值，
  因此 P-5 默认严格阻断，放宽须显式哈希配置。
- **T+1 是两条各自可能正确而组合错误的规则**：单 session 判定在 `execution_rules.py`，
  跨 session 推进在 `backtest.py`，故意分两个文件测。且卖出**现金当日可用**而股份 T+1 交收 ——
  钱的规则和股的规则不是同一条。
