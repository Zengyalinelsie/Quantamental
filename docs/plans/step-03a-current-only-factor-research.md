# Step 03A Spec / Plan：current-only 因子研究轨道

> 状态：`ready_for_implementation`
>
> 建立日期：2026-08-15
>
> 用户决策（2026-08-15）：先走「路 A」——用已入库的 current-only 数据把因子与估值研究跑通，
> 暂不等待 strict-PIT 数据源许可。
>
> 关联：`docs/plans/step-03-p4-real-qualification-gate.md`（strict 轨道，**本文件不替代它**）、
> ADR-0006（研究基线与评估政策）、ADR-0011（估值模型工程默认值）
>
> 性质：实现级 Spec/Plan。不修改 `AGENTS.md`、`docs/07`、已接受 ADR 或任何 Gate 定义。

## 0. 为什么单独开一条轨道

`step-03` 的 Spec 是为 **strict-PIT** 因子资格 Gate 写的，其不变量要求 `pit_verified` 截面与
forward-return labels。该轨道当前 `gate_blocked`，根因是 Step 02 的 D0 数据源资格未通过
（Wind 无许可、Factor Service 无实时凭据、iFinD 401）。

同时，仓库已有一批**真实但 current-only** 的数据：

- CSI500 全部 500 家 × 2018–2025 年末三表，35,505 条 observation；
- 11,922/12,000 UoW 完整，78 个合法空期保持为空（未填零）；
- `data_mode=current_research`、`trust_state=normalized_current`、`pit_verified=false`。

且经代码审计确认：**质量、改善、相对估值、基本面锚定、隐含预期、IC/RankIC、Fama-MacBeth
的数学全部已实现，且在 `current_research` 模式下无门禁**。仅分析师修正因缺
`AnalystSourceAttestation` 而不可用。

因此存在一条不与 strict 轨道冲突的可执行路径：用 current-only 数据跑通编排层，产出真实
（但**明确非 PIT**）的因子分数与 IC。本文件定义该轨道。

**本轨道不改变 strict 轨道的任何要求。** Step 03 保持 `gate_blocked`，其 Gate 条件不因本轨道
的任何产物而放松。

## Spec

### 目标

在 `data_mode=current_research` 下，把已入库的 CSI500 财务事实经由已有领域数学，编排为：

1. 版本化的远期收益标签；
2. 质量 / 估值预期差 / 改善三个维度的真实特征与分项值；
3. 截面因子分数与排名；
4. 真实 IC / RankIC，并与独立库交叉验证；
5. 记入 `ExperimentRun` 账本的可追溯运行记录。

### 非目标（每一条都是硬约束）

- **不声称任何因子科学有效。** current-only 数据无法证明历史可用性，因此本轨道的 IC 只是
  「在当前可得数据上的相关性观测」，不是样本外证据；
- **不把 current-only 产物用于 strict 回测。** 不生成 `strict_historical` 模式的任何产物；
- **不晋级 FactorVersion。** 本轨道产出的 `FactorVersion` 保持 `draft`，不申请 promotion，
  不进入 `research_backtest` 以上的任何 approval scope；
- **不为得到好看的 IC 而调整窗口、样本、阈值或过滤规则**；
- **不把 current 数据重新标注为 `pit_verified`**。ADR-0006 已明确：
  「strict 回测仍只消费 `pit_verified`；current 数据不能因采用本口径而获得严格资格」；
- **不填零**。缺失、停牌、退市、不可比一律显式表达；
- 不实现分析师修正维度（缺 `AnalystSourceAttestation`，属付费数据）。

### 不变量

- 每个产物绑定 exact `DatasetVersion` / `UniverseVersion` / `FeatureDefinition` 版本 /
  `LabelDefinition` 版本 / code version / 参数 / seed；
- 标签与特征在时间上隔离：标签的观测窗口不得早于特征的决策时点；
- 所有 `RunContext` 固定为 `(current_research, research)`；任何试图构造
  `strict_historical` 的调用必须失败关闭；
- 权重来自版本化定义对象，**不得硬编码在编排代码里**；
- 独立库交叉验证的输入与主统计器完全一致（同一份 observation 序列）；
- 失败运行不可删除或改写为成功；
- 编排层不重新实现任何数学 —— 只调用已有 `domain/` 纯函数。

### 数据与信任边界

| 项 | 本轨道状态 |
|---|---|
| `data_mode` | `current_research`（唯一允许值） |
| `deployment_stage` | `research`（唯一允许值） |
| `trust_state` | `normalized_current` |
| 可否用于 strict 回测 | **否** |
| 可否申请 promotion | **否** |
| 可否进入 Paper/Live | **否** |
| 可否声称科学有效 | **否** |

### 产物

- `LabelDefinition` + 远期收益标签数据集（版本化）；
- `FeatureSnapshot`：质量/估值/改善三维度的真实特征值与状态；
- 截面因子分数与排名（含每个维度的分项贡献）；
- 真实 IC / RankIC / Fama-MacBeth 统计量 + 独立库对照报告；
- `ExperimentRun` 记录（含 spec、绑定、指标、失败原因）；
- Evidence 文档，记录真实数值、限制与**明确的否认声明**。

### 验收

- 三个维度各至少在一个真实截面上产出非空分项值，或给出明确的 unavailable 原因；
- IC / RankIC 为真实计算结果，主统计器与独立库在既定容差内一致；
- 负结果（IC 接近零或为负）**完整保存**，不重跑至好看为止；
- Evidence 明确声明：本轨道不构成科学有效性证据，不满足任何 Gate；
- 全量验证通过。

## Plan

### 依赖：行情数据（用户执行）

标签生成需要 CSI500 2018–2025 日线。当前仓库只验证过 21 天窗口。

用户已确认自行下载。所需命令与前置条件（PostgreSQL、migration、ack flag）见本轮交接说明。
复用**已有** `platform/src/a_share_platform/workers/backfill.py`（支持
`--domains raw_daily_bar`、`--benchmarks 000905`），**不新建下载器**。

数据未到位时，Task A2–A4 用测试 fixture 完成并验证；A5 需要真实数据。

### Task A2：远期收益标签生成器

新增 `domain/labels.py`：版本化 `LabelDefinition` 与纯函数标签计算。

TDD 切片：

1. 红测：`ForwardReturnLabelDefinition` 不存在；
2. 从日线序列计算 20 / 60 / 120 交易日远期收益；
3. 停牌、退市、数据缺口 → 显式 `unavailable` 与原因，**不插值、不填零**；
4. 窗口不足（末端不满 N 日）→ `unavailable`，不截短窗口；
5. 复权语义显式：当前只有未复权价，因此标签必须声明
   `adjustment=unadjusted` 并在缺公司行动时标注该限制；
6. `content_hash` 覆盖定义与参数，保证同参数同结果。

预计文件：`domain/labels.py`、`tests/test_labels.py`。

### Task A3：特征计算编排层

新增 `application/factor_features.py`：把已入库财务事实转为三个模型的输入。

TDD 切片：

1. 红测：编排服务不存在；
2. 财务事实 → `QualityComponentInput`（复用 `domain/quality_factor.py`）；
3. 财务事实 → `ImprovementComponentInput`（复用 `domain/fundamental_improvement.py`，
   `data_mode=CURRENT_RESEARCH`）；
4. 财务事实 + 价格 → 估值分项（复用 `domain/valuation_expectation_gap.py`）；
5. 任一输入缺失 → 该分项 `unavailable` 且携带原因，其余分项继续；
6. 显式拒绝 `strict_historical`：构造该模式时抛错（fail closed）；
7. 不重新实现任何数学 —— 测试断言编排层只做数据搬运与状态传递。

预计文件：`application/factor_features.py`、`tests/test_factor_features.py`。

### Task A4：因子分数与截面排名

新增 `application/factor_scoring.py`。

TDD 切片：

1. 红测：打分服务不存在；
2. 三维度分项 → 综合分数，权重来自版本化 `FactorScoreDefinition`，**不硬编码**；
3. 截面标准化与排名（复用 `domain/feature_transforms.py`）；
4. 某维度 unavailable 时的处理策略必须显式声明（重新归一化 or 整体 unavailable），
   并由测试固定该语义；
5. 排名稳定、可复现、`content_hash` 覆盖全部输入。

预计文件：`application/factor_scoring.py`、`domain/factor_scoring.py`（定义对象）、对应测试。

### Task A5：IC / RankIC 实跑与 Experiment 接线

新增 `workers/factor_research.py`（dry-run 优先）。

TDD 切片：

1. 分数 × 标签 → `CrossSectionObservation`（复用 `domain/factor_statistics.py`）；
2. 真实 IC / RankIC / Fama-MacBeth；
3. 独立库交叉验证（scipy / statsmodels，已安装），输入与主统计器完全一致；
4. 结果写入 `ExperimentRun`，含 spec 绑定与真实指标；
5. **IC 为负或接近零时照实记录**，不重跑、不改窗口；
6. worker 默认 dry-run，真实写入需显式 ack。

预计文件：`workers/factor_research.py`、`tests/test_factor_research_worker.py`。

### Task A6：Evidence 与全量验证

记录真实红绿测、真实 IC 数值、环境限制、未完成项，以及**明确的否认声明**。
运行后端 unittest、compileall、ruff、mypy、前端 Vitest、lint、build、`git diff --check`。

## 与 strict 轨道的关系

| 项 | 本轨道（03A） | strict 轨道（03） |
|---|---|---|
| 数据 | `normalized_current` | `pit_verified` |
| 模式 | `current_research` | `strict_historical` |
| 产物可否 promotion | 否 | 是（通过科学门后） |
| 可否声称有效 | **否** | 需样本外+成本后+统计不确定性 |
| 当前状态 | `ready_for_implementation` | `gate_blocked`（等 Step 02 D0） |

本轨道的编排层（标签生成、特征编排、打分、IC 计算）**在 strict 数据到位后可直接复用** ——
只需切换数据来源与 `RunContext`，不需重写。这是先走路 A 的主要工程理由。

反之，本轨道的**任何产物、任何数值、任何结论都不能迁移到 strict 轨道**作为证据。
