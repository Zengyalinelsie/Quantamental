# P-5 组合构建与现实回测实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把获批 `SignalSnapshot` 转成受约束 `TargetPortfolioSnapshot`，实现 Risk Model R0、A 股现实回测状态机与 core attribution，并按 PUI-05 交付 Construction / Backtests / Risk / Scenarios / Attribution 五页产品面。

**Architecture:** 本 plan 与 P-1/P-2 相反 —— **绝大部分是从零新建**。2026-08-16 逐文件核实：`domain/portfolio.py`、`domain/portfolio_construction.py`、`domain/risk.py`、`domain/backtest.py`、`domain/execution_rules.py`、`domain/attribution.py` **全部不存在**；`ports/risk.py`、`ports/backtests.py` **不存在**；133 个测试文件中**没有任何** portfolio / risk / backtest / attribution 测试。因此本 plan 的纪律不是"复用已有数学"，而是**严格分层地新建数学**：纯领域数学（无 I/O）→ ports → adapters → API → UI。已存在的 `domain/market_data.py`（`DailyBar` / `DailyMarketState` / `PriceLimit` / `CorporateAction` / `ShareCapital` / `ExchangeCalendar`）、`domain/signals.py`（`SignalSnapshot`）、`validation/statistical_crosscheck.py`、`domain/run_context.py` 是**输入合同**，一律消费不改写。

**Tech Stack:** Python 3.11+（本机 3.12.12）、Decimal 全程（金额/权重/股数）、NumPy 2.5.2 + SciPy 1.18.0（独立交叉验证）、PostgreSQL 17（端口 55432）、Parquet/DuckDB、React 19 + TypeScript 5.8 + Vite 7 + AntD 6、Vitest 3、Playwright（Chrome channel）

## Global Constraints

继承 `AGENTS.md`、`docs/07-detailed-system-spec.md`（SPEC-030–035、039、048、050、059）、
`docs/plans/step-05-p6-core-selection.md` 的冻结 Spec 与 **ADR-0006（Accepted）**，**每个 Task 都适用**：

- `domain/` 不导入 FastAPI / SQLAlchemy / psycopg / provider SDK / qlib / rqalpha / 前端概念
  （`tests/test_architecture_contract.py` 的 `forbidden_roots` 已强制，新增外部引擎依赖时**必须**把它加进该集合）
- **组合数学必须是纯函数**：不读数据库、不读文件、不看时钟。所有输入显式传入，所有输出可复现
- 金额一律 `Decimal` + ISO 4217 currency；股数一律 `int`（A 股无碎股）；权重/收益/风险有明确 scale
- **缺失、不可比、不可用、被阻断必须显式表达，禁止填零**（SPEC-039：未参与分项标 `not_applicable`，未实现标 `unavailable`，只有"策略确实无该暴露"才可记 0）
- benchmark、AUM、持仓数、单股/行业上限、现金、TE、换手、参与率、整手、再平衡频率、审批层级
  **全部是 `PortfolioPolicy` 配置，不得写成领域枚举默认值或平台常量**（SPEC-031）
- `RunContext` 在本 plan 固定为 `(current_research, research)`；`strict_historical` 组合必须
  **失败关闭**，因为它要求 `pit_verified` 输入而当前不存在
- **blocked / pending / cancelled 订单不得当成交**，且不得静默消失（SPEC-034）
- **盘后信号最早在下一可交易 session 成交**；任何按当日收盘成交的实现都是缺陷
- 风险分项闭合、归因闭合的**残差超阈值必须 fail，不得吸收进 "other"**
- 费用/滑点/冲击/参与率/价格口径/日历版本**全部进入 Run/Artifact hash**（ADR-0006 决策 6）
- `BacktestRun` 类型必须显式命名（SPEC-033）：本 plan 只产出 `stock_selection_backtest` 与
  `execution_simulation`，**不得统一叫"回测"**
- 外部引擎 adapter **必须先有 D0 spike + ADR**，不得假定 rqalpha 已选定（见 Task 6）
- 前端只消费服务端投影，**不在浏览器计算权重、风险、归因或闭合**
- **runtime 无默认 fixture**；Figma 示例值（`+78.2%`、`贵州茅台`、`RUN-ATTR-20241206-889` 等）零泄漏
- worker 默认 dry-run，真实写入需显式 ack（复用 `--private-local-research-ack --execute`）
- append-only：`BacktestRun` / `TradeLedger` / `RiskModelDecisionRecord` / `AttributionSnapshot`
  重复写幂等，same ID / different semantics 冲突关闭，失败 run 不可改写为成功
- 未经用户明确授权不 commit、不 push

## 前置条件

### P-2 必须完成 —— 这是硬依赖

组合的输入是**真实因子分数**。没有 P-2 的 `FactorScoreDefinition` → `CrossSectionObservation` →
真实 IC 链路，Construction 就只能拿到空 Snapshot 集合，回测就只能在零持仓上跑。

用 P-2 Task 4/5 的产出校验：

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m unittest tests.test_data_readiness_gate -v
.venv/bin/python - <<'PY'
import os, psycopg
with psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True) as c:
    for t in ("research.signal_snapshots", "research.investment_views",
              "research.experiment_runs", "observation.market_data_partitions",
              "canonical.universe_versions"):
        print(t, c.execute(f"select count(*) from {t}").fetchone()[0])
PY
```

**关键判断**：如果 `research.signal_snapshots` 为 0，本 plan 的 Task 1–7 仍然**全部可做**
（它们是纯数学与工程合同，用测试 fixture 驱动），但 Task 8 的真实小样本回测只能产出
"引擎正确、结论为空"的结果，Task 9–13 的页面只能显示真实 blocker。**这是允许且正确的结果。**

### 科学性的前置声明（必须先读，否则后面每一步都会被误读）

本 plan 的所有输入是 `normalized_current`。因此：

> **回测引擎正确 ≠ 回测结论有效。** 本 plan 产出的 equity curve、Sharpe、TE、归因分解全部是
> **工程正确性证据**，不是策略有效性证据。理由：输入未经 PIT 验证、无法证明历史可用时间、
> 无样本外、无多重检验校正、无容量验证。任何人不得用本 plan 的曲线声称策略可盈利。

这不是免责套话 —— 它决定了 Task 8 与 Task 14 的验收标准：**引擎跑通就算过，数字好坏不算过也不算不过**。

## 现状事实（2026-08-16 逐文件核实）

### 确认不存在（本 plan 全部新建）

| 目标文件 | 状态 | 本 plan 的 Task |
|---|---|---|
| `domain/portfolio.py` | **不存在** | Task 2 |
| `domain/portfolio_construction.py` | **不存在** | Task 3 |
| `domain/risk.py` | **不存在** | Task 4 |
| `domain/execution_rules.py` | **不存在** | Task 5 |
| `domain/backtest.py` | **不存在** | Task 5 |
| `domain/attribution.py` | **不存在** | Task 7 |
| `ports/risk.py` | **不存在** | Task 4 |
| `ports/backtests.py` | **不存在** | Task 5 |
| `application/risk_models.py` / `application/backtests.py` | **不存在** | Task 4 / Task 5 |
| portfolio / risk / backtest / attribution 测试 | **0 个**（133 个测试文件中无一个） | 全部 Task |
| `docs/adr/0006-...` | **已存在且 Accepted** | Task 1 只消费不重写 |
| `pages/PortfolioWorkspace.tsx` | **不存在**；`/portfolios` 当前是 `RouteWorkspace` 通用壳 | Task 10–13 |
| rqalpha | **未安装**（`ModuleNotFoundError`） | Task 6 的 D0 spike |

`/portfolios` 当前的运行时是 `AppShell.tsx` 第 185 行：

```tsx
<Route path="/portfolios" element={<RouteWorkspace definition={workspaceDefinitions.portfolios} />} />
```

即 `routes.tsx` 第 37–41 行的通用 `WorkspacePage`，五个 tab 名已登记
（`['Construction', 'Backtests', 'Risk', 'Scenarios', 'Attribution']`）但无任何实现。
`docs/22-prototype-runtime-gap-audit.md` §5 第 12–16 行把五页全部记为 `placeholder`。

### 必须复用的真实签名（逐字段核实，不得凭记忆改写）

**`domain/signals.py` 的 `SignalSnapshot` —— 组合的唯一输入**（26 个 init 字段 + 2 个 `init=False`）：

```python
@dataclass(frozen=True)
class SignalSnapshot:
    snapshot_id: str
    security_id: str
    decision_time: datetime          # timezone-aware
    horizon_trading_days: int        # 只允许 20 / 60 / 120
    universe_version_id: str
    universe_size: int               # > 0
    rank: int                        # 1 <= rank <= universe_size
    previous_rank: int | None
    score: Decimal
    expected_return: Decimal         # 组合 ER 权重的来源
    confidence: Decimal              # [0, 1]
    investment_view_id: str
    investment_view_hash: str
    factor_version_ids: tuple[str, ...]
    factor_version_hashes: tuple[str, ...]     # 与 ids 长度必须一致
    factor_review_ids: tuple[str, ...]
    factor_review_hashes: tuple[str, ...]      # 与 ids 长度必须一致
    dataset_version_ids: tuple[str, ...]
    feature_version_ids: tuple[str, ...]
    model_version_id: str
    run_id: str
    approval_scope: ApprovalScope    # 必须匹配 run_context.deployment_stage
    run_context: RunContext
    trust_state: DataTrustState      # RAW 被拒；strict_historical 必须 PIT_VERIFIED
    data_cutoff: datetime            # <= decision_time
    created_at: datetime             # >= decision_time
    rank_change: int | None = field(init=False)   # previous_rank - rank
    content_hash: str = field(init=False)         # 64 位十六进制
```

注意三条已被 `__post_init__` 强制的不变量，组合层**不要重复校验，也不要绕过**：
`data_cutoff <= decision_time`、`approval_scope` 与 `deployment_stage` 一一对应
（`_SCOPE_BY_STAGE`）、`raw` 输入直接 `ValueError`。

**`domain/factor_diagnostics.py` —— 这里的"portfolio"是因子诊断，不是组合构建**：

```text
QuantilePortfolioSpec(quantile_count, minimum_sample_size, formula_version, tie_break_version)
quantile_portfolios(observations: Sequence[CrossSectionObservation], *, spec, data_mode)
    -> QuantilePortfolioResult   # quantiles / monotonic / top_minus_bottom / sample_size ...

TurnoverObservation(period_id, entity_id, weight, portfolio_version_id, data_mode,
                    trust_state, decision_time, available_at, missing_reason=None)
TurnoverSpec(minimum_positions_per_period, weight_sum_tolerance, formula_version)
portfolio_turnover(observations, *, spec, data_mode) -> TurnoverResult
```

**必须明确：这两个函数不是组合构建。** `quantile_portfolios()` 把截面按分数切成 N 组算平均
forward return，用于判断因子单调性；它不知道 AUM、现金、整手、单股上限、prior portfolio 或 T+1。
`portfolio_turnover()` 只接受**恰好两期**（`if len(period_ids) != 2: raise`）的权重观测算换手率，
用于因子诊断，不是多期回测的换手账本。

**Task 3 不得调用 `quantile_portfolios()` 生成目标权重；Task 5 不得用 `portfolio_turnover()`
充当回测换手统计。** 混用会让"因子诊断口径"与"组合政策口径"共享一个数字而语义不同 ——
这正是 `CLAUDE.md` §11 列的错误之一（把因子级结果当组合级结果）。
真实组合换手必须由 Task 7 的组合统计纯函数按 `PortfolioPolicy.turnover_limit` 的口径独立计算。

**`domain/market_data.py` —— 回测的市场输入，全部已存在**：

```text
class PriceAdjustment(str, Enum):     UNADJUSTED  # 目前只有这一个值
class PriceLimitStatus(str, Enum):    NOT_AT_LIMIT / LIMIT_UP / LIMIT_DOWN / LOCKED_UP / LOCKED_DOWN
class CorporateActionType(str, Enum): CASH_DIVIDEND / BONUS_SHARE / SPLIT / REVERSE_SPLIT / RIGHTS_ISSUE

DailyBar(listing_id, exchange, session_date, currency, open, high, low, close,
         previous_close, volume_shares, amount, adjustment, source_id,
         dataset_version_id, trust_state)
    # high >= max(open, low, close)；low <= min(open, high, close)；
    # volume_shares 非负 int；adjustment 必须 UNADJUSTED（"DailyBar stores only raw unadjusted prices"）

DailyMarketState(listing_id, session_date, is_trading, is_suspended, source_id,
                 dataset_version_id, trust_state, listing_state, special_treatment)
    # is_trading 与 is_suspended 不可同真；TERMINATED 不可 is_trading

PriceLimit(listing_id, session_date, lower, upper, source_id)
    def status_for(self, bar: DailyBar) -> PriceLimitStatus
    # close == upper 且 low == high == upper → LOCKED_UP；否则 LIMIT_UP

ShareCapital(listing_id, effective_from, effective_to, total_shares,
             circulating_shares, free_float_shares, source_id, dataset_version_id)
    # free_float <= circulating <= total，且 free_float 要求 circulating 非 None

CorporateAction(action_id, listing_id, action_type, ex_date, record_date,
                cash_per_share, share_ratio, subscription_price, currency, source_id)
    # record_date <= ex_date；CASH_DIVIDEND 必须有 cash_per_share；
    # BONUS_SHARE/SPLIT/REVERSE_SPLIT 必须有 share_ratio；
    # RIGHTS_ISSUE 必须同时有 share_ratio 与 subscription_price

CalendarDay(exchange, calendar_date, is_open, closure_reason, source_id)
    # 关闭日必须有 closure_reason
ExchangeCalendar(exchange, days)
    def is_session(self, calendar_date: date) -> bool   # 无观测 → MarketDataUnavailable
    def next_session(self, after: date) -> date         # 无已知后继 → MarketDataUnavailable
```

`ExchangeCalendar.next_session()` 是"盘后信号最早下一 session"的**唯一**实现来源。
Task 5 不得自己写 `+1 day` 或 `while weekday < 5` —— 那会静默跳过节假日与临时休市。

**`validation/statistical_crosscheck.py` —— 独立库交叉验证的既有合同**：

```text
class CrossCheckStatus(str, Enum):  MATCHED / MISMATCH / UNAVAILABLE
CrossCheckSpec(absolute_tolerance, relative_tolerance, adapter_version)
    # 两个容差不可同时为 0
CrossCheckComponent(name, primary_value, reference_value, absolute_error,
                    allowed_error, within_tolerance)
StatisticalCrossCheckReport(report_id, statistic_id, status, components,
    absolute_tolerance, relative_tolerance, adapter_version,
    primary_formula_versions, reference_libraries, reference_method,
    input_digest, unavailable_reason, warnings, scientific_status)
    def component(self, name: str) -> CrossCheckComponent

cross_check_information_coefficient(...)   # scipy
cross_check_newey_west_mean(...)           # statsmodels
cross_check_fama_macbeth(...)              # statsmodels
```

Task 4 与 Task 7 **复用这三个数据类与 `_comparison_report` 的语义**（尤其
`status=UNAVAILABLE` + `unavailable_reason` 表示"库缺失"而非"一致"），新增
`cross_check_shrinkage_covariance(...)` 与 `cross_check_attribution_closure(...)`
两个函数，**不新建第二套交叉验证报告结构**。

**`domain/run_context.py`**：

```python
DataMode:        CURRENT_RESEARCH / STRICT_HISTORICAL
DeploymentStage: RESEARCH / SHADOW / PAPER / LIMITED_LIVE
RunContext(data_mode, deployment_stage)
# _ALLOWED_STAGES_BY_DATA_MODE: STRICT_HISTORICAL 只允许 RESEARCH
```

### ADR-0006 的绑定内容（Accepted 2026-08-14，逐条引用）

本 plan 不重新决策以下任何一条，也不得"因为结果不好"而改动：

1. **"首个总体研究 benchmark 使用 CSI800；同时分别报告 CSI300 和 CSI500 分组结果。
   benchmark 是 `PortfolioPolicy`/`UniverseVersion` 配置，不写死在领域核心。"**
   → Task 2 的 `PortfolioPolicy.benchmark_universe_version_id` 是必填字段，
   `domain/portfolio.py` 里**不得出现** `CSI800` 这个字面量。
2. **"第一再平衡频率为月度；周度只作为预先登记的敏感度分析。"**
   → `RebalanceFrequency` 枚举可含 `MONTHLY` / `WEEKLY`，但默认基线是月度，
   周度运行必须在 Run 里标记为 `pre_registered_sensitivity`。
3. **"第一外部回测对照引擎选择 RQAlpha，通过 adapter 隔离；若资格 spike 证明不可用，
   再以新 ADR 选择 LEAN，不修改内部领域合同。"**
   → 注意措辞是"选择 RQAlpha"**并附带资格 spike 条件**。rqalpha 当前**未安装**，
   Task 6 必须先跑 spike；spike 失败则写新 ADR 选 LEAN 或声明双引擎 reconciliation 不可用。
   **两种结果都不允许修改 Task 5 的内部领域合同。**
4. **"盘后决策的 Outcome/回测默认在下一可交易 session 使用可配置 VWAP 作为入场参考，
   在第 N 个可交易 session 使用相同口径退出。"**
   → Task 5 的 `ExecutionPricePolicy` 必须版本化 VWAP 口径；VWAP source 不可用时
   **回测 fail closed 或退化为显式声明的替代口径**，不得静默用 close 替代。
5. **"分红、送转、拆股、配股和退市现金流通过 total-return 公司行动账本处理；
   不得用无记录的前复权价格替代公司行动。"**
   → Task 5 的除权处理必须走 `CorporateAction` 账本产生现金流与股数变化，
   **不得**读取 provider 的前复权价格然后声称已处理公司行动。
6. **"费用、滑点、冲击、参与率、价格口径和日历版本进入 Run/Artifact hash。"**
   → Task 2 的 `CostModelVersion` 与 Task 5 的 `BacktestRunSpec` 的 `content_hash`
   必须覆盖这六项，Task 8 有专门测试断言"改任一项则 hash 改变"。
7. **"P7 Timing 的 benchmark 与 P6 对齐；若 benchmark 不可交易，必须显式绑定可交易 proxy。
   Shadow 阶段对组合影响固定为 0。"**
   → Task 3 的目标权重**不得**读取任何 Shadow `TimingForecast`。SPEC-030 同样要求：
   "若主动 Timing 尚在 Shadow，组合 MUST 使用获批静态/被动仓位基线"。

边界条款同样绑定：**"strict 回测仍只消费 `pit_verified`；current 数据不能因采用本口径而获得严格资格"**、
**"实际 VWAP source 必须单独通过数据、许可、coverage 和 availability 资格；不可用时 Outcome 保持 pending/unavailable"**、
**"敏感度分析必须预先登记，不得选择性只展示有利结果"**、**"本 ADR 不授权 Paper 或 Live 交易"**。

### `docs/plans/step-05-p6-core-selection.md` 的 8 个 Task（逐字引用，本 plan 展开其 Plan 半部）

冻结 Spec 的 Plan 部分原文如下，本 plan 的 Task 编号与它一一对应但更细：

- **Task 1：产品政策 ADR 与合同** —— "先冻结可配置字段和 D0/D1，不把默认写入领域枚举。"
- **Task 2：组合构建纯领域核心** —— "按 Top-N equal weight → ER weight → prior/cash → constraints
  → lot/rounding → deterministic residual cash 小步实现。"
- **Task 3：Risk Model R0** —— "先 exposure，再 shrinkage covariance，再 component closure/stress；
  用 NumPy/SciPy 等独立计算交叉检查。"
- **Task 4：内部现实回测引擎** —— "严格按 session → eligibility → intent → fill/block →
  inventory/cash → valuation 状态机 TDD。"
- **Task 5：外部引擎 adapter 与 reconciliation** —— "先做 D0 spike/ADR，再新增 `adapters/rqalpha/`
  或批准的 engine 目录、frozen export/import 和 diff classifier；外部依赖不进入 domain。"
- **Task 6：统计、capacity 和 core attribution** —— "新增 portfolio statistics/attribution 纯函数
  及独立库对照；residual 超阈值失败，未参与项不填 0。"
- **Task 7：Repository/migration/API** —— "预计 migration `003x_p6_portfolio_backtest.sql`，
  表进入 `research`，serving 只读 projection；append-only run/target/trade/risk/attribution；
  API schema 和 OpenAPI 生成。"
- **Task 8：Portfolio Workspace** —— "新增 `frontend/src/pages/PortfolioWorkspace.tsx` 与
  construction/backtest/risk/scenario/attribution features/tests；完成四视口和黄金路径。
  ……P6 领域/API 未完成前，运行时只能展示真实 blocker，不能用测试或 Figma fixture 生成持仓、
  曲线、风险或归因。"

**本 plan 的映射与展开理由**：冻结 Plan 的 Task 4 把整个回测状态机压成一句话。
状态机有六个转移，每个转移都有独立的 A 股规则和独立的失败模式，压在一个 commit 里
无法做到"一个 task 一个可验证行为"。因此本 plan 把它拆成 Task 5（execution_rules 纯规则）
与 Task 6 后的多个状态机切片；同理把冻结 Task 8 的五页拆成 Task 10–13。
**冻结 Spec 的内容一字不改，只把 Plan 的粒度做细。**

### 原型节点事实（`docs/assets/prototype/figma-node-summary.json` 实际解析）

四个节点均**存在**，尺寸与 `docs/assets/prototype/README.md` 第 55–58 行一致：

| node | 名称 | 尺寸 | 顶层结构 |
|---|---|---|---|
| `7:303` | `portfolios-construction` | **1440 × 1200** | `viewport-wrap` → `sidebar` 248 + `main-content` 1192 |
| `7:712` | `portfolios-realistic-backtest` | **1440 × 1367** | `sidebar` 248 + `main-content` 1192 |
| `7:1060` | `portfolios-risk-scenarios` | **1440 × 1271** | `sidebar` 248 + `main-content` 1192 |
| `7:1348` | `portfolios-attribution` | **1440 × 1300** | `sidebar` 248 + `main-content` 1192 |

注意 `7:303` 多一层 `viewport-wrap`，另外三个没有 —— 这是原型自身的不一致，
**不要**在实现里复制这个额外容器。

**summary JSON 的深度限制**：`children` 在约第 4 层被替换成 `children_count`
（例：`{"name": "left-col", "w": 724.0, "h": 934.0, "children_count": 2}`），
且**没有 `layoutMode` / `itemSpacing` 字段**（只有 `layout` / `gap`，且深层节点没有）。
因此区块名与文案必须从 SVG 提取：

```bash
cd docs/assets/prototype && python3 - <<'PY'
import re, html
for f in ("portfolios-construction.svg", "portfolios-realistic-backtest.svg",
          "portfolios-risk-scenarios.svg", "portfolios-attribution.svg"):
    s = open(f, encoding="utf-8").read()
    texts = [html.unescape(re.sub("<[^>]+>", "", m))
             for m in re.findall(r"<text[^>]*>(.*?)</text>", s, re.S)]
    texts = [t.strip() for t in texts if t.strip()]
    print("=====", f, len(texts))
    for t in texts:
        print(" |", t)
PY
```

2026-08-16 实测提取数量：construction **217** 条、backtest **200** 条、
risk-scenarios **165** 条、attribution **200** 条。

**四页的真实区块（从 summary 的可见层级 + SVG 文案交叉确认）**：

`7:303` construction，`workspace` 1192 × 945，`gap` 20：
- `strategy-config-card` 1144 × 171 —— 文案「策略设置 / Strategy Configuration」，
  六个配置位：Benchmark（`CSI500 (中证500) ▾`）、持仓数（`Top-50`）、权重方式（`Expected Return`）、
  AUM（`¥500,000,000`）、现金比例（`2.0%`）；下方「硬性约束边界:」`单股≤3%` `行业偏离≤5%`
  `月换手≤20%` `参与率≤15%`
- `columns-wrapper` 1144 × 630 —— 左「目标持仓 / Target Holdings」10 列表
  （代码｜公司｜行业｜当前权重｜目标权重｜变化｜预期收益｜风险贡献｜流动性｜阻断状态），
  15 行全部 `0.00%` / `—` / `BLOCKED`；右「约束诊断 / Constraint Diagnostics」
  `PORTFOLIO READINESS BLOCKED`，六项 checklist（`单股上限 3%` `行业偏离 5%` `月换手 20%`
  `参与率 15%` `现金 2%` `T+1 约束`）
- `bottom-action-bar` 1144 × 56 —— `运行构建 / 冻结研究目标 (Blocked)`

原型自己就画的是空态：`Pre-trade Readiness: BLOCKED — 真实合格 Snapshot 为 0，无法构建有效目标组合`。
**这对本 plan 极其有利** —— 设计已经预期了 blocked 运行时，不需要为了"像原型"而伪造持仓。

`7:712` backtest，`workspace` 1192 × 1173：
- `config-card` 1144 × 171 —— 「信号与执行规则 / Signal & Execution Rules」：
  信号时点 `T日收盘 (T Close)`、最早执行 `T+1日开盘 (T+1 Open)`、
  执行价格 `下一日开盘价 / Next Open (VWAP)`；`rules-row` 十个 chip：
  `T+1 可卖库存` `100股 lot size` `佣金 0.08%` `印花税 0.1%` `滑点 0.05%` `参与率≤15%`
  `停牌处理` `涨跌停处理` `ST排除` `退市清算` `公司行动调整` `现金管理`
- `layout-columns` 1144 × 934 = `left-col` **724** + `right-col` **400**（gap 20）
  - 左：「Equity Curve / 权益曲线」+ 业绩表（1M/3M/6M/1Y/累计 × 策略/基准）
    + 「Trade & Blocked Order Ledger / 交易与阻断订单台账」9 列
    （日期｜代码｜方向｜计划数量｜实际数量｜价格｜滑点｜状态｜阻断原因）
  - 右：「Internal vs RQAlpha Reconciliation」（逐日差异 / 逐笔差异）
    + 「PIT 资格检查 / PIT Eligibility」`BLOCKED` `原因: PIT Snapshot 缺失`
    `• 结构已就绪但科学结果不可用` `• 盘后信号不能当日收盘成交`
    + 「数据与策略生成流转 / Flow Pipeline」五段
    （`1. INPUT Signal + Rules` → `2. PROCESS Simulation Engine` → `3. OUTPUT Results Portfolio`
    → `4. ACTION 分析 / Investment Analysis` → `5. GATE PIT缺失时结果仅供结构验证`）

台账示例行含三种真实状态：`成交` / `阻断`（原因 `停牌`、`涨停阻断`）/ `部分`（原因 `参与率超限`）。
**这三种状态 + 原因是 Task 5 状态机的产品级验收清单。**

`7:1060` risk-scenarios，`workspace` 1192 × 1077：
- `top-metrics-row` 1144 × 114 —— 四张 `kpi-card` 各 **274 × 113/114**（gap 16）：
  预测年化波动 `18.2%`（`基于 Ledoit-Wolf 收缩估计`）、Tracking Error `5.6%`、
  最大行业偏离 `3.8%`、模型状态 `DRAFT` `Risk Model R0 - v0.3`
- `layout-columns` 1144 × 895 = `left-col` **624** + `right-col` **500**
  - 左：「Exposures Analysis / 因子暴露与主动偏离分析」5 列
    （因子｜暴露值 Beta｜风险贡献 %｜基准 Bench｜主动偏离 Active），
    分「行业暴露 / Industry Group (Top 6)」与「风格暴露 / Style Factors」
    （市值 Size｜贝塔 Beta｜动量 Momentum｜估值 Value｜质量 Quality）
    + 「Covariance & Risk Decomposition / 协方差风险归因」`Method: Ledoit-Wolf`，
    特异性风险 / 系统风险 / Top 5 MCTR
    + `✓ 风险分项和闭合校验: factor + specific = 100%`
  - 右：「情景分析 / Stress Scenarios」5 行，**其中一行 `行业轮动极端 (Rotational)` 是 `—` + `unavailable`**
    + 「决策记录依据 / Risk Model Record」`DRAFT`（Model Version / Data Reference Version / Run ID）
    + 「Evidence Chain Link / 穿透存证证据链」`已折叠 (Collapsed)`

原型自己在情景表里画了一行 `unavailable` —— **设计已经承认未映射暴露不可填 0**，与
`docs/18` 第 91 行「未映射暴露 `unavailable`，不得填 0」一致。

`7:1348` attribution，`workspace` 1192 × 1106：
- `top-metrics-row` 1144 × 106 —— 四张 `kpi-card` 各 **274 × 105/106**（gap 8 内部）：
  组合收益 `+2.84%`、基准收益 `+2.11%`、主动收益 `+0.73%`、
  闭合残差 `0.00%` `✓ 残差完全闭合归零校验`
- `layout-columns` 1144 × 932 = `left-col` **624** + `right-col` **500**
  - 左：「Performance Attribution Waterfall / 主动收益贡献瀑布图」九段
    （Market `+1.82%`｜Industry `+0.31%`｜Style `-0.12%`｜Selection `+0.48%`｜Cost `-0.18%`｜
    **Timing `+0.15%`**｜**Events `N/A`**｜**Execution `+0.09%`**｜Residual `0.00%`｜Total Acti `+0.73%`）
    + 「Selection Detail by Industry」7 列 8 行
    + 「Transaction Cost Decomposition」（券商佣金 `1.5 bps`｜印花税 `5.0 bps`｜
    市场滑点 `1.2 bps`｜冲击成本 `1.8 bps`｜合计 `9.5 bps`）
  - 右：「Style Factor Attribution」+「Beta Timing Performance」+
    「Macro Events Attribution」`UNAVAILABLE` +「Algorithm Execution Quality」
    + 「Attribution Evidence & Model」（`ATTR-v1.0` / `20241101_20241206` / `RUN-ATTR-20241206-889`）

**这里有一个必须偏离原型的地方**：原型给 Timing 画了 `+0.15%`、给 Execution 画了 `+0.09%`。
按 SPEC-039 与 ADR-0006 决策 7，P6 阶段 **Timing 处于 Shadow，对组合影响固定为 0，
应标 `not_applicable`；Execution 归因需要真实执行，P6 无 OMS，应标 `unavailable`**。
原型的两个正数是设计示意，**运行时不得出现**。Task 13 会把这条差异写进 Evidence。

### PUI-01 的可复用分区合同（PUI-05 必须复用，不建第二套）

`platform/frontend/src/features/desk/DeskSection.tsx`（59 行）与
`deskState.ts`（86 行）已经解决了六态渲染：

```tsx
interface DeskSectionProps {
  section: DeskSectionData
  loading?: boolean      // "Request in flight.  Owned by the client, never by the server."
  error?: string         // "Request failed.  Owned by the client, never by the server."
  subtitle?: string
  extra?: ReactNode
  children?: ReactNode
}
```

```ts
export function resolveSectionState(
  section: DeskSectionData | undefined,
  { loading, error }: { loading?: boolean; error?: string },
): WorkspaceStateKind
// loading → 'loading'；error → 'error'；否则 section?.status ?? 'unavailable'
// 注释原文："the browser must not upgrade, downgrade or infer a status"

export function noticeReason(section, error?): string
// 服务端 blocker 优先；partial 回落到 coverage 文案
export function metricsFromPayload(payload: unknown, fields: ReadonlyArray<MetricField>): DeskMetric[]
// "A missing or malformed value yields no metric rather than a zero"
export function coverageMetrics(section: DeskSectionData): DeskMetric[]
```

`DeskSection` 的行为已被 `DeskSection.test.tsx`（109 行、9 个测试）锁定，包括
`renders every unavailable blocker code and reason` 与
`conveys status by text, not by colour alone`。**PUI-05 五页直接复用这个组件**，
只新增 payload 渲染子组件。后端侧同理复用 `domain/desk.py` 的
`DeskBlocker(code, reason, affected_binding, evidence_ids)` 形状 ——
`DeskBlocker` 的 docstring 明确说这是为了"the frontend renders both with one component"。

`domain/desk.py` 的 `DeskSection.__post_init__` 已有三条不变量，Portfolio 分区必须沿用：
`partial` 必须带 coverage 或 blocker、`unavailable` 必须带 blocker、
`ready`/`partial` 必须有 payload 而其他状态**必须没有** payload。

`application/desk_projection.py` 第 352–361 行当前的 Portfolio 分区是：

```python
def _portfolio_tracking(self) -> DeskSection:
    return _unavailable(
        DeskSectionKey.PORTFOLIO_TRACKING,
        _blocker(
            "P6_PORTFOLIO_TRACKING_NOT_IMPLEMENTED",
            "组合构建、偏离与风险能力属 P6，尚未实现；不展示模拟持仓或风险数字。",
            "portfolio.tracking",
        ),
    )
```

Task 14 会在真实 Target/Risk 可用后更新它 —— **在此之前不得改动**，
因为改了就是在页面上宣称一个不存在的能力。

---

## Task 排序的理由（严格 TDD 可行性）

本 plan 的 Task 顺序不是"按页面从上到下"，而是**按可测试性**：

```text
Task 1  政策与决策冻结（文档 + D0/D1 登记）        ← 无代码，先消除后续歧义
Task 2  domain/portfolio.py     纯值对象与政策     ← 无 I/O，可 100% 单元测试
Task 3  domain/portfolio_construction.py 纯数学   ← 无 I/O
Task 4  domain/risk.py          纯数学 + NumPy 对照 ← 无 I/O
Task 5  domain/execution_rules.py 纯规则判定       ← 无 I/O，A 股规则全部在这里
Task 6  外部引擎 D0 spike + ADR                   ← 决策门，必须在 adapters 之前
Task 7  domain/backtest.py      状态机 + domain/attribution.py ← 无 I/O
Task 8  ports/ + adapters/ + application/         ← 第一次出现 I/O
Task 9  migration + repository + API              ← 第一次出现数据库
Task 10 PortfolioWorkspace 壳 + Construction 页
Task 11 Backtests 页
Task 12 Risk + Scenarios 页
Task 13 Attribution 页
Task 14 Desk 分区更新 + Evidence + 明确否认
```

**为什么纯数学必须排在最前**：回测状态机有六个转移，每个转移的正确性只有在
"输入完全由测试构造、无外部依赖"时才能红/绿分明。如果先建 repository，
第一个红测的失败原因会是"数据库没连上"而不是"T+1 规则错了" ——
那就失去了 TDD 的诊断价值。`domain/` 的架构守卫（`test_architecture_contract.py`）
本身也强制这个方向。

**为什么 Task 6 的 D0 必须在 Task 8 之前**：冻结 Plan 的 Task 5 原文是
"先做 D0 spike/ADR，再新增 `adapters/rqalpha/` 或批准的 engine 目录"。
rqalpha 当前未安装；它对 Python 版本、pandas 版本、数据 bundle 格式都有强约束。
先建目录再发现不可用，会留下一个空 adapter 和一条已发生的依赖污染。

**为什么 UI 排在最后且分四个 Task**：五页各有独立的服务端投影与独立的六态语义。
一个 Task 一页（Risk 与 Scenarios 合并，因为它们共用 node `7:1060`），
每页都能独立跑四视口验收。

---

### Task 1: 冻结产品政策、D0/D1 登记与 ADR 消费

冻结 Plan 的 Task 1 说"先冻结可配置字段和 D0/D1，**不把默认写入领域枚举**"。
本 Task 不写代码，只把决策写清楚 —— 因为 Task 2 的第一个测试就要断言
"政策字段是必填的、没有隐含默认值"，而这个断言的清单必须先存在。

**Files:**
- Modify: `docs/plans/step-05-p6-core-selection.md`（Task 状态：`dependency_blocked` → `in_progress`）
- Create: `docs/27-p6-implementation-evidence.md`（编号按仓库现状顺延：现有最大为 `26`，
  但 P-3/P-4 两份 plan 都声明创建 `docs/26-*`；**执行时先 `ls docs/*.md` 确认真实最大编号再顺延**）
- Modify: `docs/14-data-source-catalog-and-agent-routing.md`（VWAP source 资格状态）

**Interfaces:** 无代码产出。产出是一份**可被测试引用的字段清单**。

- [ ] **Step 1: 重读 ADR-0006 并逐条抄进 Evidence**

```bash
cd /Users/casiezhou/personal/Quantamental
cat docs/adr/0006-research-baseline-and-evaluation-policy.md
```

把七条决策与四条边界**逐字**抄进 `docs/27-p6-implementation-evidence.md` 的
「绑定决策」一节。抄录而非概括，是因为后面每个 Task 的验收都要回来对照原文；
概括会在传递中丢掉"若资格 spike 证明不可用"这类关键条件。

- [ ] **Step 2: 登记 D0 决策与当前状态**

`docs/plans/step-05-p6-core-selection.md` 头部写的是「D0：第一 benchmark、外部回测引擎」。
第一 benchmark 已由 ADR-0006 决策 1 解决（CSI800 + CSI300/CSI500 分组）；
外部引擎**只是有条件地**选定了 RQAlpha。在 Evidence 里登记：

```text
P6-D0-01  第一研究 benchmark        → 已由 ADR-0006 决策 1 冻结（CSI800，配置化）
P6-D0-02  外部回测对照引擎          → ADR-0006 决策 3 条件选定 RQAlpha，
                                      资格 spike 未做，rqalpha 未安装 → 状态 pending_spike
P6-D1-01  执行价格 VWAP source      → ADR-0006 决策 4 定口径，真实 source 未资格化
                                      → 状态 not_qualified（与 P5-D1-01 同一阻断）
P6-D1-02  风险/集中度上限具体数值    → Spec 要求「保持配置化，Gate 前批准」→ 待用户批准
```

**`P6-D1-02` 必须保持 pending。** 原型画的 `单股≤3%` `行业偏离≤5%` `月换手≤20%` `参与率≤15%`
是设计示意值，不是已批准限额。Task 2 会让这些成为必填配置参数，
测试里用它们做 fixture 是合法的，但**运行时默认值不存在**。

- [ ] **Step 3: 列出 `PortfolioPolicy` 的完整可配置字段清单**

按 SPEC-031 逐字段列出，每个字段写明"为什么它不能是常量"。至少：

```text
benchmark_universe_version_id  ADR-0006 决策 1：benchmark 是配置，不写死在领域核心
aum_amount / aum_currency      不同 AUM 下同一信号的整手可行性完全不同
target_position_count          Top-N 是策略参数，不是平台事实
weighting_scheme               equal_weight / expected_return（ER 权重来自 SignalSnapshot.expected_return）
cash_target_ratio              现金比例影响权重归一化的分母
single_name_weight_limit       集中度限额需 Gate 前批准（P6-D1-02）
industry_active_weight_limit   行业偏离限额同上
turnover_limit / turnover_window  换手口径必须与 rebalance 频率绑定才有意义
participation_limit            与 capacity 分析同源
lot_size                       A 股 100 股，但 lot 是交易所规则版本，不是数学常量
rebalance_frequency            ADR-0006 决策 2：月度基线，周度为预登记敏感度
approval_scope                 SPEC-030：用途不互相隐含
risk_model_version_id          必须绑定具体 R0 版本
cost_model_version_id          ADR-0006 决策 6：进入 hash
execution_price_policy_id      ADR-0006 决策 4：VWAP 口径版本化
calendar_version_id            ADR-0006 决策 6：日历版本进入 hash
```

- [ ] **Step 4: 记录 VWAP source 的资格缺口**

在 `docs/14-data-source-catalog-and-agent-routing.md` 追加一行：
执行价格所需的 VWAP source 当前**无合格来源**。ADR-0006 边界原文：
"实际 VWAP source 必须单独通过数据、许可、coverage 和 availability 资格；
不可用时 Outcome 保持 pending/unavailable"。

**这意味着 Task 5 的 `ExecutionPricePolicy` 必须支持一个显式的
`next_session_open` 退化口径，并在 Run 里标记"非 VWAP"** ——
不是静默用 open 冒充 VWAP。

- [ ] **Step 5: 提交**

```bash
cd /Users/casiezhou/personal/Quantamental
git add docs/27-p6-implementation-evidence.md \
  docs/plans/step-05-p6-core-selection.md \
  docs/14-data-source-catalog-and-agent-routing.md
git commit -m "docs: freeze the P6 configurable policy surface before writing any portfolio code

Every number the prototype draws — 3% single name, 5% industry deviation, 20%
monthly turnover, 15% participation — is a design illustration, not an approved
limit.  Writing any of them as a domain default would turn an unapproved
parameter into a platform fact, and the next reader could not tell which numbers
you chose and which the user approved.  So the field list is frozen first and
every field is required, with no default at all.

The external engine decision is recorded as conditionally selected rather than
selected: ADR-0006 picks RQAlpha but only if a qualification spike proves it
usable, and rqalpha is not even installed on this machine.  Recording it as
'decided' would let someone create adapters/rqalpha/ before the spike that is
supposed to gate it.

The VWAP source stays not_qualified, which is the same blocker P5 already carries
for outcome pricing.  The consequence is written down now so it is not
rediscovered later: the execution price policy needs an explicit degraded mode
that is labelled as not-VWAP, rather than quietly using the open price and
calling it VWAP."
```

---

### Task 2: `domain/portfolio.py` —— 政策与目标组合值对象

第一段代码。全部是值对象与校验，**没有一行求解逻辑** —— 权重怎么算属 Task 3。
先建合同再建数学，是因为 Task 3 的每个测试都要构造 `PortfolioPolicy`，
如果政策合同还在变，Task 3 的测试会反复重写。

**Files:**
- Create: `platform/src/a_share_platform/domain/portfolio.py`
- Test: `platform/tests/test_portfolio_policy.py`

**Interfaces:**
- Consumes: `domain/run_context.py`（`RunContext`、`DataMode`）、
  `domain/factor_lifecycle.py`（`ApprovalScope`）、`domain/pit.py`（`DataTrustState`）
- Produces:
  ```python
  class WeightingScheme(StrEnum):
      EQUAL_WEIGHT = "equal_weight"
      EXPECTED_RETURN = "expected_return"

  class RebalanceFrequency(StrEnum):
      MONTHLY = "monthly"
      WEEKLY = "weekly"          # ADR-0006 决策 2：仅预登记敏感度

  class ConstraintStatus(StrEnum):
      SATISFIED = "satisfied"
      BINDING = "binding"        # 恰好触及上限
      VIOLATED = "violated"      # 求解后仍越界 → 目标不可用
      UNAVAILABLE = "unavailable"  # 缺输入无法判定，禁止当作 satisfied

  @dataclass(frozen=True)
  class PortfolioPolicy:
      policy_id: str
      version: str
      benchmark_universe_version_id: str
      aum_amount: Decimal
      aum_currency: str
      target_position_count: int
      weighting_scheme: WeightingScheme
      cash_target_ratio: Decimal
      single_name_weight_limit: Decimal
      industry_active_weight_limit: Decimal
      turnover_limit: Decimal
      participation_limit: Decimal
      lot_size: int
      rebalance_frequency: RebalanceFrequency
      approval_scope: ApprovalScope
      risk_model_version_id: str
      cost_model_version_id: str
      execution_price_policy_id: str
      calendar_version_id: str
      content_hash: str = field(init=False)

  @dataclass(frozen=True)
  class ConstraintDiagnostic:
      constraint_id: str
      status: ConstraintStatus
      limit: Decimal | None
      observed: Decimal | None
      reason: str | None          # UNAVAILABLE / VIOLATED 必填

  @dataclass(frozen=True)
  class TargetPosition:
      security_id: str
      listing_id: str
      target_weight: Decimal
      target_shares: int
      prior_weight: Decimal
      weight_change: Decimal
      reference_price: Decimal
      expected_return: Decimal | None
      unavailable_reason: str | None

  @dataclass(frozen=True)
  class TargetPortfolioSnapshot:
      WEIGHT_CLOSURE_TOLERANCE: ClassVar[Decimal] = Decimal("0.000001")  # 显式声明，非浮点巧合
      target_id: str
      policy_id: str
      policy_hash: str
      decision_time: datetime
      eligible_session: date
      signal_snapshot_ids: tuple[str, ...]
      signal_snapshot_hashes: tuple[str, ...]
      prior_target_id: str | None
      positions: tuple[TargetPosition, ...]
      cash_weight: Decimal
      residual_cash_amount: Decimal
      constraints: tuple[ConstraintDiagnostic, ...]
      risk_model_version_id: str
      cost_model_version_id: str
      run_context: RunContext
      trust_state: DataTrustState
      run_id: str
      created_at: datetime
      content_hash: str = field(init=False)
  ```

- [ ] **Step 1: 先读三个被消费的合同的真实字段**

```bash
cd platform
grep -n "class ApprovalScope" -A6 src/a_share_platform/domain/factor_lifecycle.py
grep -n "class DataTrustState" -A5 src/a_share_platform/domain/pit.py
sed -n 1,56p src/a_share_platform/domain/run_context.py
grep -n "_canonical_hash\|_decimal_text\|_canonical_time" -A8 src/a_share_platform/domain/signals.py | head -40
```

**hash 工具函数要照抄 `signals.py` 的实现方式**（`_canonical_hash` / `_decimal_text` /
`_canonical_time`），不要新发明一套规范化。两套 hash 规范化会让"同一语义不同 hash"
变成可能，而那正是 same-ID-different-semantics 冲突检测要防的。

- [ ] **Step 2: 写失败测试 —— 政策没有默认值**

```python
# platform/tests/test_portfolio_policy.py
"""PortfolioPolicy: every product parameter is required configuration.

SPEC-031 lists benchmark, AUM, position count, single-name and industry limits,
cash, tracking error, turnover, participation, lot, rebalance and approval tier
as configuration rather than platform constants.  ADR-0006 adds that the
benchmark in particular "是 PortfolioPolicy/UniverseVersion 配置，不写死在领域核心".

So the dataclass has no defaults at all.  The prototype draws 3% / 5% / 20% / 15%
and the user has approved none of them (P6-D1-02 is pending); a default would
silently promote a design illustration into a platform fact.
"""

from __future__ import annotations

import unittest
from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal

from a_share_platform.domain.factor_lifecycle import ApprovalScope
from a_share_platform.domain.portfolio import (
    PortfolioPolicy,
    RebalanceFrequency,
    WeightingScheme,
)


def policy(**overrides: object) -> PortfolioPolicy:
    base: dict[str, object] = {
        "policy_id": "portfolio-policy:core-selection",
        "version": "v0",
        "benchmark_universe_version_id": "universe-version:csi800:2025-12-31",
        "aum_amount": Decimal("500000000"),
        "aum_currency": "CNY",
        "target_position_count": 50,
        "weighting_scheme": WeightingScheme.EQUAL_WEIGHT,
        "cash_target_ratio": Decimal("0.02"),
        "single_name_weight_limit": Decimal("0.03"),
        "industry_active_weight_limit": Decimal("0.05"),
        "turnover_limit": Decimal("0.20"),
        "participation_limit": Decimal("0.15"),
        "lot_size": 100,
        "rebalance_frequency": RebalanceFrequency.MONTHLY,
        "approval_scope": ApprovalScope.RESEARCH_BACKTEST,
        "risk_model_version_id": "risk-model:r0:v0",
        "cost_model_version_id": "cost-model:a-share:v0",
        "execution_price_policy_id": "execution-price:next-session-open:v0",
        "calendar_version_id": "calendar:XSHG:v0",
    }
    base.update(overrides)
    return PortfolioPolicy(**base)  # type: ignore[arg-type]


class PolicyHasNoDefaultsTest(unittest.TestCase):
    def test_no_policy_field_carries_a_default(self) -> None:
        """A default here would be an unapproved limit masquerading as a fact."""
        import dataclasses

        for field in fields(PortfolioPolicy):
            if field.name == "content_hash":
                continue  # init=False, derived
            self.assertIs(
                field.default,
                dataclasses.MISSING,
                f"{field.name} must not carry a default",
            )
            self.assertIs(
                field.default_factory,  # type: ignore[misc]
                dataclasses.MISSING,
                f"{field.name} must not carry a default_factory",
            )

    def test_no_benchmark_literal_appears_in_the_module(self) -> None:
        """ADR-0006: the benchmark is configuration, not a domain literal."""
        from pathlib import Path

        import a_share_platform.domain.portfolio as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        for literal in ("CSI800", "CSI300", "CSI500", "000300", "000905", "000906"):
            self.assertNotIn(literal, source, f"{literal} must not be hard-coded")


class PolicyValidationTest(unittest.TestCase):
    def test_policy_is_content_addressed(self) -> None:
        self.assertEqual(policy().content_hash, policy().content_hash)
        self.assertEqual(len(policy().content_hash), 64)

    def test_changing_any_costed_input_changes_the_hash(self) -> None:
        """ADR-0006 decision 6: fees, slippage, participation, price convention
        and calendar version all enter the run hash."""
        baseline = policy().content_hash
        for overrides in (
            {"cost_model_version_id": "cost-model:a-share:v1"},
            {"participation_limit": Decimal("0.10")},
            {"execution_price_policy_id": "execution-price:next-session-vwap:v0"},
            {"calendar_version_id": "calendar:XSHG:v1"},
        ):
            self.assertNotEqual(baseline, policy(**overrides).content_hash, str(overrides))

    def test_lot_size_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            policy(lot_size=0)

    def test_cash_ratio_outside_unit_interval_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            policy(cash_target_ratio=Decimal("1.5"))
        with self.assertRaises(ValueError):
            policy(cash_target_ratio=Decimal("-0.01"))

    def test_single_name_limit_must_admit_the_requested_position_count(self) -> None:
        """50 names cannot fit under a 1% single-name cap with 2% cash."""
        with self.assertRaises(ValueError):
            policy(target_position_count=50, single_name_weight_limit=Decimal("0.01"))

    def test_aum_currency_must_be_an_iso_code(self) -> None:
        with self.assertRaises(ValueError):
            policy(aum_currency="RMB¥")

    def test_weekly_rebalance_is_allowed_but_not_the_baseline(self) -> None:
        """ADR-0006 decision 2 keeps monthly as the baseline and weekly as a
        pre-registered sensitivity, so both must be constructible and
        distinguishable by hash."""
        monthly = policy(rebalance_frequency=RebalanceFrequency.MONTHLY)
        weekly = policy(rebalance_frequency=RebalanceFrequency.WEEKLY)
        self.assertNotEqual(monthly.content_hash, weekly.content_hash)
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_portfolio_policy -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'a_share_platform.domain.portfolio'`。
把真实错误文本抄进 Evidence。

- [ ] **Step 4: 最小实现 `PortfolioPolicy`**

只实现 `PortfolioPolicy` 与它的校验 + `content_hash`。
`TargetPortfolioSnapshot` 留到 Step 6。

`test_single_name_limit_must_admit_the_requested_position_count` 的校验逻辑：
`target_position_count * single_name_weight_limit >= 1 - cash_target_ratio`。
不满足则政策自相矛盾 —— 求解器永远无法同时满足持仓数与集中度。
**在政策构造时就拒绝，比让 Task 3 的求解器返回 VIOLATED 更早、更清楚。**

- [ ] **Step 5: 转绿**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_portfolio_policy -v`
Expected: PASS

- [ ] **Step 6: 写 `TargetPortfolioSnapshot` 的红测再实现**

```python
from datetime import date

from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.portfolio import (
    ConstraintDiagnostic,
    ConstraintStatus,
    TargetPortfolioSnapshot,
    TargetPosition,
)
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext

DECISION = datetime(2025, 12, 1, 15, 30, tzinfo=UTC)
RESEARCH = RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.RESEARCH)


def position(index: int, *, weight: str, shares: int, **overrides: object) -> TargetPosition:
    base: dict[str, object] = {
        "security_id": f"security:CN:{600000 + index}:XSHG",
        "listing_id": f"listing:CN:{600000 + index}:XSHG",
        "target_weight": Decimal(weight),
        "target_shares": shares,
        "prior_weight": Decimal("0"),
        "weight_change": Decimal(weight),
        "reference_price": Decimal("10.00"),
        "expected_return": Decimal("0.10"),
        "unavailable_reason": None,
    }
    base.update(overrides)
    return TargetPosition(**base)  # type: ignore[arg-type]


def satisfied(constraint_id: str = "single_name_weight_limit") -> ConstraintDiagnostic:
    return ConstraintDiagnostic(
        constraint_id=constraint_id,
        status=ConstraintStatus.SATISFIED,
        limit=Decimal("0.30"),
        observed=Decimal("0.25"),
        reason=None,
    )


def target(**overrides: object) -> TargetPortfolioSnapshot:
    base: dict[str, object] = {
        "target_id": "target-portfolio:core-selection:2025-12-02",
        "policy_id": "portfolio-policy:core-selection",
        "policy_hash": policy().content_hash,
        "decision_time": DECISION,
        "eligible_session": date(2025, 12, 2),
        "signal_snapshot_ids": ("signal-snapshot:security:CN:600000:XSHG:2025-12-01",),
        "signal_snapshot_hashes": ("d" * 64,),
        "prior_target_id": None,
        "positions": (position(0, weight="0.25", shares=25_000),),
        "cash_weight": Decimal("0.75"),
        "residual_cash_amount": Decimal("375000000.00"),
        "constraints": (satisfied(),),
        "risk_model_version_id": "risk-model:r0:v0",
        "cost_model_version_id": "cost-model:a-share:v0",
        "run_context": RESEARCH,
        "trust_state": DataTrustState.NORMALIZED_CURRENT,
        "run_id": "run:portfolio-construction:2025-12-01",
        "created_at": DECISION,
    }
    base.update(overrides)
    return TargetPortfolioSnapshot(**base)  # type: ignore[arg-type]


class TargetPortfolioSnapshotTest(unittest.TestCase):
    def test_weights_plus_cash_must_close_to_one(self) -> None:
        """SPEC-030 acceptance: target weights, cash, constraints and versions close."""
        # 断言：positions 权重和 + cash_weight != 1 → ValueError，
        # 且误差容忍必须显式声明（不是浮点巧合）
        self.assertEqual(
            sum((p.target_weight for p in target().positions), Decimal("0"))
            + target().cash_weight,
            Decimal("1"),
        )
        with self.assertRaises(ValueError):
            target(cash_weight=Decimal("0.70"))  # 0.25 + 0.70 = 0.95
        with self.assertRaises(ValueError):
            target(
                positions=(position(0, weight="0.25", shares=25_000),
                           position(1, weight="0.25", shares=25_000)),
            )  # 0.50 + 0.75 = 1.25
        # 容差是声明出来的常量，不是浮点巧合：Decimal 精确到分位即闭合
        self.assertEqual(TargetPortfolioSnapshot.WEIGHT_CLOSURE_TOLERANCE, Decimal("0.000001"))
        inside = target(
            positions=(position(0, weight="0.2500005", shares=25_000),),
            cash_weight=Decimal("0.75"),
        )
        self.assertIsNotNone(inside.content_hash)

    def test_eligible_session_cannot_precede_the_decision_date(self) -> None:
        """An after-close signal cannot trade on the day it was formed."""
        # 断言：eligible_session <= decision_time.date() → ValueError
        with self.assertRaises(ValueError):
            target(eligible_session=date(2025, 12, 1))
        with self.assertRaises(ValueError):
            target(eligible_session=date(2025, 11, 28))
        self.assertEqual(target(eligible_session=date(2025, 12, 2)).eligible_session,
                         date(2025, 12, 2))

    def test_unavailable_position_carries_a_reason_and_no_target(self) -> None:
        """A zero target weight and an unavailable target are different facts."""
        # 断言：unavailable_reason 非空时 target_weight 必须为 0 且 target_shares 为 0；
        # 反之 unavailable_reason 为 None 时不得出现 "为什么是 0" 的歧义
        with self.assertRaises(ValueError):
            position(1, weight="0.10", shares=10_000, unavailable_reason="suspended")
        with self.assertRaises(ValueError):
            position(1, weight="0.00", shares=10_000, unavailable_reason="suspended")
        blocked = position(1, weight="0.00", shares=0, unavailable_reason="suspended")
        self.assertEqual(blocked.target_weight, Decimal("0"))
        self.assertEqual(blocked.target_shares, 0)
        # expected_return 缺失时必须是 None，不得填 0：0 是一个预测，None 是没有预测
        self.assertIsNone(
            position(1, weight="0.00", shares=0, unavailable_reason="suspended",
                     expected_return=None).expected_return,
        )
        # 反向：没有 reason 的零权重零股是歧义，禁止构造
        with self.assertRaises(ValueError):
            position(1, weight="0.00", shares=0)

    def test_violated_constraint_makes_the_snapshot_refuse_construction(self) -> None:
        """A target that breaks an approved limit is not a target."""
        # 断言：任一 ConstraintDiagnostic.status is VIOLATED → ValueError
        violated = ConstraintDiagnostic(
            constraint_id="single_name_weight_limit",
            status=ConstraintStatus.VIOLATED,
            limit=Decimal("0.30"),
            observed=Decimal("0.34"),
            reason="single name 0.34 exceeds the 0.30 limit",
        )
        with self.assertRaises(ValueError):
            target(constraints=(satisfied(), violated))
        # BINDING 恰好触及上限，是可发布的事实，不是违规
        binding = ConstraintDiagnostic(
            constraint_id="single_name_weight_limit",
            status=ConstraintStatus.BINDING,
            limit=Decimal("0.30"),
            observed=Decimal("0.30"),
            reason=None,
        )
        self.assertEqual(len(target(constraints=(binding,)).constraints), 1)

    def test_unavailable_constraint_is_not_treated_as_satisfied(self) -> None:
        """Missing industry data cannot silently pass the industry limit."""
        # 断言：status is UNAVAILABLE 且 reason 为空 → ValueError；
        # 且 UNAVAILABLE 不得被 Snapshot 当作可发布
        with self.assertRaises(ValueError):
            ConstraintDiagnostic(
                constraint_id="industry_active_weight_limit",
                status=ConstraintStatus.UNAVAILABLE,
                limit=Decimal("0.05"),
                observed=None,
                reason=None,
            )
        unavailable = ConstraintDiagnostic(
            constraint_id="industry_active_weight_limit",
            status=ConstraintStatus.UNAVAILABLE,
            limit=Decimal("0.05"),
            observed=None,
            reason="benchmark industry weights are missing for 2025-12-01",
        )
        self.assertIsNone(unavailable.observed)
        with self.assertRaises(ValueError):
            target(constraints=(satisfied(), unavailable))

    def test_snapshot_hash_covers_the_policy_hash_not_just_the_policy_id(self) -> None:
        """Two runs under the same policy id but different weights must differ."""
        baseline = target()
        self.assertEqual(len(baseline.content_hash), 64)
        self.assertEqual(baseline.content_hash, target().content_hash)
        # 同 policy_id、不同 policy_hash → 不同 snapshot hash
        rehashed = target(policy_hash=policy(turnover_limit=Decimal("0.10")).content_hash)
        self.assertEqual(rehashed.policy_id, baseline.policy_id)
        self.assertNotEqual(rehashed.content_hash, baseline.content_hash)
        # 同 policy_hash、不同权重 → 不同 snapshot hash
        reweighted = target(
            positions=(position(0, weight="0.20", shares=20_000),),
            cash_weight=Decimal("0.80"),
        )
        self.assertEqual(reweighted.policy_hash, baseline.policy_hash)
        self.assertNotEqual(reweighted.content_hash, baseline.content_hash)

    def test_signal_ids_and_hashes_must_align(self) -> None:
        # 与 SignalSnapshot 的 factor_version_ids/hashes 对齐检查同构
        with self.assertRaises(ValueError):
            target(signal_snapshot_hashes=("d" * 64, "e" * 64))
        with self.assertRaises(ValueError):
            target(signal_snapshot_hashes=())
        with self.assertRaises(ValueError):
            target(signal_snapshot_ids=())
        aligned = target(
            signal_snapshot_ids=(
                "signal-snapshot:security:CN:600000:XSHG:2025-12-01",
                "signal-snapshot:security:CN:600001:XSHG:2025-12-01",
            ),
            signal_snapshot_hashes=("d" * 64, "e" * 64),
        )
        self.assertEqual(len(aligned.signal_snapshot_ids), len(aligned.signal_snapshot_hashes))

    def test_strict_historical_target_requires_pit_verified(self) -> None:
        """Mirrors SignalSnapshot: strict mode has no PIT inputs today, so it
        must fail closed rather than produce an unusable-but-plausible target."""
        # 断言：RunContext(STRICT_HISTORICAL, RESEARCH) + NORMALIZED_CURRENT → ValueError
        strict = RunContext(DataMode.STRICT_HISTORICAL, DeploymentStage.RESEARCH)
        with self.assertRaises(ValueError):
            target(run_context=strict, trust_state=DataTrustState.NORMALIZED_CURRENT)
        with self.assertRaises(ValueError):
            target(run_context=strict, trust_state=DataTrustState.RAW)
        with self.assertRaises(ValueError):
            target(run_context=RESEARCH, trust_state=DataTrustState.RAW)
```

补全断言时用真实字段名，**不要**为了让测试好写而改字段名。

- [ ] **Step 7: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/domain/portfolio.py \
  platform/tests/test_portfolio_policy.py
git commit -m "feat: add the portfolio policy and target snapshot contracts

PortfolioPolicy has no default on any field.  The prototype draws a 3% single
name cap, 5% industry deviation, 20% monthly turnover and 15% participation, and
the user has approved none of them — P6-D1-02 is still pending.  A dataclass
default would turn those illustrations into platform facts that nobody chose, so
every one of the nineteen fields must be supplied at the call site.  A test also
asserts no benchmark literal appears anywhere in the module, because ADR-0006
makes the benchmark configuration rather than domain code.

A policy is refused if it contradicts itself: fifty names cannot fit under a one
percent single-name cap once cash is reserved.  Catching that when the policy is
built says 'this policy is impossible', whereas catching it in the solver says
'this target is violated' — the first is true and the second is misleading.

The target snapshot separates a zero weight from an unavailable one, and refuses
to exist at all when a constraint is violated or when a constraint could not be
evaluated.  Treating an unevaluated industry limit as satisfied is how a
concentration breach reaches a report unnoticed."
```

---

### Task 3: `domain/portfolio_construction.py` —— 纯权重求解

冻结 Plan 的 Task 2 规定顺序：
「Top-N equal weight → ER weight → prior/cash → constraints → lot/rounding →
deterministic residual cash 小步实现」。**照这个顺序，每一小步一个红测。**

**Files:**
- Create: `platform/src/a_share_platform/domain/portfolio_construction.py`
- Test: `platform/tests/test_portfolio_construction.py`

**Interfaces:**
- Consumes: Task 2 的 `PortfolioPolicy` / `TargetPosition` / `ConstraintDiagnostic`、
  `domain/signals.py` 的 `SignalSnapshot`
- Produces:
  ```python
  @dataclass(frozen=True)
  class ConstructionInput:
      security_id: str
      listing_id: str
      signal: SignalSnapshot
      reference_price: Decimal          # 参考价，来自 ExecutionPricePolicy
      industry_code: str | None         # None → 行业约束 UNAVAILABLE，不是 satisfied
      prior_shares: int
      tradable: bool
      unavailable_reason: str | None

  @dataclass(frozen=True)
  class ConstructionResult:
      positions: tuple[TargetPosition, ...]
      cash_weight: Decimal
      residual_cash_amount: Decimal
      constraints: tuple[ConstraintDiagnostic, ...]
      excluded: tuple[tuple[str, str], ...]   # (security_id, reason)
      formula_version: str

  def construct_target_portfolio(
      inputs: Sequence[ConstructionInput], *, policy: PortfolioPolicy,
      prior_total_value: Decimal,
  ) -> ConstructionResult
  ```

- [ ] **Step 1: 写失败测试 —— Top-N 等权 + 手算 fixture**

Spec 验收原文：「Top-N 等权和 ER 权重都有**手算 fixture**」。
手算意味着期望值写在测试里、可由人验算，不是"跑一遍把输出粘回来"。

```python
# platform/tests/test_portfolio_construction.py
"""Pure target-portfolio construction.

No I/O: every price, prior holding, industry code and policy value is passed in.
That is what makes each red test diagnose the maths rather than the environment.

The expected numbers below are hand-computed and written out, not captured from a
run.  A captured expectation cannot fail when the maths changes meaning.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal

from a_share_platform.domain.factor_lifecycle import ApprovalScope
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.portfolio import (
    ConstraintStatus,
    PortfolioPolicy,
    RebalanceFrequency,
    WeightingScheme,
)
from a_share_platform.domain.portfolio_construction import (
    ConstructionInput,
    construct_target_portfolio,
)
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.domain.signals import SignalSnapshot

DECISION = datetime(2025, 12, 1, 8, 0, tzinfo=UTC)
CONTEXT = RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.RESEARCH)


def signal(rank: int, *, expected_return: str, security: str) -> SignalSnapshot:
    return SignalSnapshot(
        snapshot_id=f"signal-snapshot:{security}:2025-12-01",
        security_id=security,
        decision_time=DECISION,
        horizon_trading_days=20,
        universe_version_id="universe-version:csi500:2025-11-28",
        universe_size=500,
        rank=rank,
        previous_rank=None,
        score=Decimal("1.0"),
        expected_return=Decimal(expected_return),
        confidence=Decimal("0.5"),
        investment_view_id=f"investment-view:{security}:2025-12-01",
        investment_view_hash="a" * 64,
        factor_version_ids=("factor-version:quality:v0",),
        factor_version_hashes=("b" * 64,),
        factor_review_ids=("factor-review:quality:v0",),
        factor_review_hashes=("c" * 64,),
        dataset_version_ids=("dataset-version:csi500:2025-11-28",),
        feature_version_ids=("feature-version:quality:v0",),
        model_version_id="model-version:composite:v0",
        run_id="run:factor-research:2025-12-01",
        approval_scope=ApprovalScope.RESEARCH_BACKTEST,
        run_context=CONTEXT,
        trust_state=DataTrustState.NORMALIZED_CURRENT,
        data_cutoff=DECISION,
        created_at=DECISION,
    )


def candidate(
    index: int, *, expected_return: str = "0.10", price: str = "10.00",
    industry: str | None = "食品饮料", prior_shares: int = 0, tradable: bool = True,
) -> ConstructionInput:
    security = f"security:CN:{600000 + index}:XSHG"
    return ConstructionInput(
        security_id=security,
        listing_id=f"listing:CN:{600000 + index}:XSHG",
        signal=signal(index + 1, expected_return=expected_return, security=security),
        reference_price=Decimal(price),
        industry_code=industry,
        prior_shares=prior_shares,
        tradable=tradable,
        unavailable_reason=None,
    )


def policy(**overrides: object) -> PortfolioPolicy:
    base: dict[str, object] = {
        "policy_id": "portfolio-policy:core-selection",
        "version": "v0",
        "benchmark_universe_version_id": "universe-version:csi800:2025-11-28",
        "aum_amount": Decimal("10000000"),
        "aum_currency": "CNY",
        "target_position_count": 4,
        "weighting_scheme": WeightingScheme.EQUAL_WEIGHT,
        "cash_target_ratio": Decimal("0.00"),
        "single_name_weight_limit": Decimal("0.30"),
        "industry_active_weight_limit": Decimal("1.00"),
        "turnover_limit": Decimal("1.00"),
        "participation_limit": Decimal("1.00"),
        "lot_size": 100,
        "rebalance_frequency": RebalanceFrequency.MONTHLY,
        "approval_scope": ApprovalScope.RESEARCH_BACKTEST,
        "risk_model_version_id": "risk-model:r0:v0",
        "cost_model_version_id": "cost-model:a-share:v0",
        "execution_price_policy_id": "execution-price:next-session-open:v0",
        "calendar_version_id": "calendar:XSHG:v0",
    }
    base.update(overrides)
    return PortfolioPolicy(**base)  # type: ignore[arg-type]


class TopNEqualWeightTest(unittest.TestCase):
    def test_four_names_equal_weight_no_cash(self) -> None:
        """Hand computation: 4 names, 0% cash, so each target weight is 0.25.
        AUM 10,000,000 × 0.25 = 2,500,000 per name at price 10.00 = 250,000
        shares, which is already a whole number of 100-share lots."""
        result = construct_target_portfolio(
            [candidate(i) for i in range(4)],
            policy=policy(),
            prior_total_value=Decimal("10000000"),
        )
        self.assertEqual(len(result.positions), 4)
        for position in result.positions:
            self.assertEqual(position.target_weight, Decimal("0.25"))
            self.assertEqual(position.target_shares, 250_000)
        self.assertEqual(result.cash_weight, Decimal("0"))
        self.assertEqual(result.residual_cash_amount, Decimal("0"))

    def test_only_top_n_by_rank_are_selected(self) -> None:
        """Six candidates, target_position_count 4: ranks 1-4 in, 5-6 excluded
        with an explicit reason rather than a zero-weight row."""
        result = construct_target_portfolio(
            [candidate(i) for i in range(6)],
            policy=policy(target_position_count=4),
            prior_total_value=Decimal("10000000"),
        )
        self.assertEqual(len(result.positions), 4)
        self.assertEqual(len(result.excluded), 2)
        for _security_id, reason in result.excluded:
            self.assertIn("rank", reason.lower())

    def test_cash_target_reduces_the_invested_weight(self) -> None:
        """2% cash, 4 names: each weight is 0.98 / 4 = 0.245 exactly."""
        result = construct_target_portfolio(
            [candidate(i) for i in range(4)],
            policy=policy(cash_target_ratio=Decimal("0.02")),
            prior_total_value=Decimal("10000000"),
        )
        for position in result.positions:
            self.assertEqual(position.target_weight, Decimal("0.245"))
        self.assertEqual(result.cash_weight, Decimal("0.02"))

    def test_fewer_candidates_than_target_count_is_reported_not_padded(self) -> None:
        """Two candidates for a Top-4 policy: weights are 0.50 each and the
        shortfall is a declared coverage fact, not a silent 4-name claim."""
        result = construct_target_portfolio(
            [candidate(i) for i in range(2)],
            policy=policy(target_position_count=4),
            prior_total_value=Decimal("10000000"),
        )
        self.assertEqual(len(result.positions), 2)
        shortfall = [c for c in result.constraints if c.constraint_id == "position_count"]
        self.assertEqual(len(shortfall), 1)
        self.assertEqual(shortfall[0].status, ConstraintStatus.BINDING)

    def test_empty_candidate_set_yields_no_positions_and_full_cash(self) -> None:
        """This is today's real runtime: zero qualified snapshots.  It must be an
        empty target with an explicit reason, never an error and never a
        fabricated holding."""
        result = construct_target_portfolio(
            [], policy=policy(), prior_total_value=Decimal("10000000"),
        )
        self.assertEqual(result.positions, ())
        self.assertEqual(result.cash_weight, Decimal("1"))
```

- [ ] **Step 2: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_portfolio_construction -v`
Expected: FAIL —— 模块不存在。抄真实错误。

- [ ] **Step 3: 实现等权 → 转绿**

只实现等权 + Top-N 选择 + cash。ER 权重、约束、整手留到后续 Step。

- [ ] **Step 4: ER 权重（红测先行）**

```python
class ExpectedReturnWeightTest(unittest.TestCase):
    def test_er_weights_are_proportional_to_expected_return(self) -> None:
        """Hand computation: ER 0.20 / 0.10 / 0.10 / 0.05, sum 0.45.
        Weights 0.20/0.45 = 0.444444, 0.10/0.45 = 0.222222 (×2),
        0.05/0.45 = 0.111111.  The scale must be declared, not left to float
        accident, so the assertion uses quantized Decimal."""
        result = construct_target_portfolio(
            [
                candidate(0, expected_return="0.20"),
                candidate(1, expected_return="0.10"),
                candidate(2, expected_return="0.10"),
                candidate(3, expected_return="0.05"),
            ],
            policy=policy(
                weighting_scheme=WeightingScheme.EXPECTED_RETURN,
                single_name_weight_limit=Decimal("0.50"),
            ),
            prior_total_value=Decimal("10000000"),
        )
        weights = [p.target_weight for p in result.positions]
        self.assertEqual(weights[0], Decimal("0.444444"))
        self.assertEqual(weights[1], Decimal("0.222222"))
        self.assertEqual(weights[3], Decimal("0.111111"))
        # The rounding remainder is explicit, not absorbed into the largest name.
        self.assertEqual(sum(weights) + result.cash_weight, Decimal("1"))

    def test_negative_expected_return_is_excluded_not_shorted(self) -> None:
        """This is a long-only product; a negative ER cannot become a negative
        weight, and it cannot be clipped to zero without saying so."""

    def test_all_expected_returns_zero_falls_back_with_an_explicit_reason(self) -> None:
        """Dividing by a zero sum would raise; equalising silently would hide
        that ER carried no information at all in this cross-section."""
```

**ER 权重的舍入余量必须显式处理。** 六位小数下 `0.444444 + 0.222222×2 + 0.111111 = 0.999999`，
差 `0.000001`。把它塞进最大持仓是最常见的做法，也是最难追查的 ——
必须明确规则并在 `ConstructionResult` 记录余量归属。

- [ ] **Step 5: prior portfolio 与换手（红测先行）**

```python
class PriorPortfolioTest(unittest.TestCase):
    def test_prior_weight_and_change_are_reported_per_position(self) -> None:
        """Construction draws 当前权重 / 目标权重 / 变化 as three columns; the
        change is computed once here, not recomputed in the browser."""

    def test_turnover_above_the_policy_limit_marks_the_constraint_violated(self) -> None:
        """A 100% rebuild against a 20% monthly turnover limit is not a target."""

    def test_turnover_uses_the_policy_window_not_the_factor_diagnostic_formula(self) -> None:
        """domain/factor_diagnostics.portfolio_turnover accepts exactly two
        periods and answers a factor question.  Reusing it here would publish a
        factor-level number under a portfolio-level name."""
        import a_share_platform.domain.portfolio_construction as module
        from pathlib import Path

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("factor_diagnostics", source)
        self.assertNotIn("portfolio_turnover", source)
```

- [ ] **Step 6: 约束诊断（红测先行，逐约束）**

四个约束各一个测试，且每个都要覆盖 `UNAVAILABLE` 分支：

```python
class ConstraintDiagnosticsTest(unittest.TestCase):
    def test_single_name_limit_binds_and_redistributes(self) -> None:
        """One name would take 0.40 under ER weighting but the cap is 0.30, so it
        is trimmed to exactly 0.30 (status BINDING) and the freed 0.10 goes to the
        remaining names by the same rule — not to cash and not to the next name
        alone."""

    def test_missing_industry_code_makes_the_industry_constraint_unavailable(self) -> None:
        """A candidate with industry_code None cannot be checked against the
        industry deviation limit.  Reporting satisfied would be a false clearance
        on a concentration limit."""
        result = construct_target_portfolio(
            [candidate(i, industry=None) for i in range(4)],
            policy=policy(industry_active_weight_limit=Decimal("0.05")),
            prior_total_value=Decimal("10000000"),
        )
        industry = next(c for c in result.constraints if c.constraint_id == "industry_active_weight")
        self.assertEqual(industry.status, ConstraintStatus.UNAVAILABLE)
        self.assertIsNotNone(industry.reason)
        self.assertIsNone(industry.observed)   # not 0

    def test_industry_deviation_needs_benchmark_weights_to_be_evaluable(self) -> None:
        """Active deviation is portfolio minus benchmark.  Without benchmark
        industry weights the answer is unknown, not zero."""

    def test_participation_limit_is_unavailable_without_volume_input(self) -> None:
        """The prototype's 参与率 15% chip cannot be evaluated at construction
        time without an ADV input; it is evaluated in the backtest.  Here it must
        read unavailable rather than satisfied."""

    def test_untradable_candidate_is_excluded_with_its_reason(self) -> None:
        """tradable False → excluded, and the reason survives into the result so
        the Construction page can show 阻断状态 per row."""
```

- [ ] **Step 7: 整手与确定性残余现金（红测先行）**

这是最容易出隐蔽 bug 的一步。

```python
class LotRoundingTest(unittest.TestCase):
    def test_shares_round_down_to_whole_lots(self) -> None:
        """Hand computation: weight 0.25 of AUM 10,000,000 = 2,500,000 at price
        33.33 = 75,007.5 shares → 750 lots = 75,000 shares, costing 2,499,750.
        The 250 difference is residual cash, stated explicitly."""
        result = construct_target_portfolio(
            [candidate(i, price="33.33") for i in range(4)],
            policy=policy(),
            prior_total_value=Decimal("10000000"),
        )
        for position in result.positions:
            self.assertEqual(position.target_shares, 75_000)
            self.assertEqual(position.target_shares % 100, 0)
        self.assertEqual(result.residual_cash_amount, Decimal("1000.00"))  # 250 × 4

    def test_rounding_is_always_down_never_up(self) -> None:
        """Rounding up would require cash the portfolio does not have, which in a
        backtest shows up as a negative cash balance several sessions later —
        far from its cause."""

    def test_a_name_too_expensive_for_one_lot_is_excluded_with_a_reason(self) -> None:
        """Target value 2,500,000 cannot buy one 100-share lot at 30,000 per
        share.  A zero-share position with a non-zero target weight would break
        weight closure silently."""
        result = construct_target_portfolio(
            [candidate(0, price="30000.00")] + [candidate(i) for i in range(1, 4)],
            policy=policy(),
            prior_total_value=Decimal("10000000"),
        )
        excluded_ids = [security for security, _reason in result.excluded]
        self.assertIn("security:CN:600000:XSHG", excluded_ids)

    def test_rounding_is_deterministic_across_runs(self) -> None:
        """Same inputs, same lots, same residual — twice."""
        args = ([candidate(i, price="33.33") for i in range(4)],)
        first = construct_target_portfolio(*args, policy=policy(),
                                          prior_total_value=Decimal("10000000"))
        second = construct_target_portfolio(*args, policy=policy(),
                                            prior_total_value=Decimal("10000000"))
        self.assertEqual(
            [p.target_shares for p in first.positions],
            [p.target_shares for p in second.positions],
        )
        self.assertEqual(first.residual_cash_amount, second.residual_cash_amount)

    def test_residual_cash_plus_position_value_equals_aum(self) -> None:
        """Closure after rounding, asserted in money rather than in weights: a
        weight-only assertion can pass while the cash is wrong."""
```

- [ ] **Step 8: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/domain/portfolio_construction.py \
  platform/tests/test_portfolio_construction.py
git commit -m "feat: construct target portfolios as a pure function with hand-checked fixtures

Every expected number in the tests is computed by hand and written out: four
names at zero cash weigh 0.25 each, 2,500,000 of AUM at 33.33 buys 750 lots not
75,007 shares, and the 250 left over is residual cash.  An expectation captured
from a run cannot fail when the maths changes meaning, which is the only failure
this file exists to catch.

Lots always round down.  Rounding up asks for cash the portfolio does not have,
and in a multi-period backtest that shows up as a negative balance several
sessions after its cause — the hardest kind of bug to trace back.  A name whose
target value cannot buy a single lot is excluded with a reason instead of
becoming a zero-share position with a non-zero weight, which would break weight
closure without breaking any assertion.

A missing industry code makes the industry constraint unavailable rather than
satisfied.  Reporting satisfied would be a false clearance on a concentration
limit, and the diagnostic carries no observed value at all rather than a zero,
because zero deviation and unknown deviation are different facts.

Turnover is computed here under the policy window rather than by reusing
factor_diagnostics.portfolio_turnover, which accepts exactly two periods and
answers a factor-diagnostic question.  A test asserts that module is not
imported: publishing a factor-level number under a portfolio-level name is the
kind of reuse that looks efficient and reads as a lie."
```

---

### Task 4: Risk Model R0 —— exposure → 收缩协方差 → 分项闭合

冻结 Plan 的 Task 3：「先 exposure，再 shrinkage covariance，再 component closure/stress；
用 NumPy/SciPy 等独立计算交叉检查。」SPEC-032 定义 R0 范围：
「行业、Size、Beta、收缩协方差和基本约束」。

原型 `7:1060` 画的是 `Method: Ledoit-Wolf`、`✓ 风险分项和闭合校验: factor + specific = 100%`，
以及一行 `行业轮动极端 (Rotational)` = `—` `unavailable`。三者都要在实现里成真。

**Files:**
- Create: `platform/src/a_share_platform/domain/risk.py`
- Create: `platform/src/a_share_platform/ports/risk.py`
- Create: `platform/src/a_share_platform/application/risk_models.py`
- Modify: `platform/src/a_share_platform/validation/statistical_crosscheck.py`
  （新增 `cross_check_shrinkage_covariance`）
- Test: `platform/tests/test_risk_model_r0.py`
- Test: `platform/tests/test_risk_crosscheck.py`

**Interfaces:**
- Consumes: Task 2 的 `TargetPortfolioSnapshot`、`validation/statistical_crosscheck.py` 的
  `CrossCheckSpec` / `CrossCheckStatus` / `StatisticalCrossCheckReport`
- Produces:
  ```python
  class RiskFactorKind(StrEnum):
      INDUSTRY = "industry"
      SIZE = "size"
      BETA = "beta"

  @dataclass(frozen=True)
  class RiskFactorExposure:
      factor_id: str
      kind: RiskFactorKind
      portfolio_exposure: Decimal | None
      benchmark_exposure: Decimal | None
      active_exposure: Decimal | None
      unavailable_reason: str | None

  @dataclass(frozen=True)
  class ShrinkageCovarianceSpec:
      method_id: str                  # "ledoit_wolf"
      formula_version: str
      minimum_observations: int
      shrinkage_target: str           # "constant_correlation" | "identity"

  @dataclass(frozen=True)
  class RiskDecomposition:
      total_risk: Decimal | None
      systematic_risk: Decimal | None
      specific_risk: Decimal | None
      factor_contributions: tuple[tuple[str, Decimal], ...]
      marginal_contributions: tuple[tuple[str, Decimal], ...]
      closure_residual: Decimal | None
      closure_tolerance: Decimal
      status: RiskStatus              # QUANTIFIED | UNAVAILABLE | CLOSURE_FAILED
      unavailable_reason: str | None

  @dataclass(frozen=True)
  class RiskModelDecisionRecord:
      record_id: str
      risk_model_version_id: str
      target_id: str
      target_hash: str
      exposures: tuple[RiskFactorExposure, ...]
      covariance_spec: ShrinkageCovarianceSpec
      decomposition: RiskDecomposition
      scenarios: tuple[ScenarioResult, ...]
      tracking_error: Decimal | None
      data_reference_version_id: str
      run_context: RunContext
      run_id: str
      created_at: datetime
      content_hash: str = field(init=False)
  ```

- [ ] **Step 1: 写失败测试 —— exposure 先行**

```python
# platform/tests/test_risk_model_r0.py
"""Risk Model R0: industry, Size, Beta, shrinkage covariance, closure.

SPEC-032 sets R0's scope and its acceptance: "每个目标组合显示 absolute 和
benchmark-relative 暴露、风险贡献和压力情景".  So absolute and active exposure are
separate fields, and an exposure that cannot be computed is unavailable rather
than zero — a zero active exposure means the portfolio matches the benchmark,
which is a strong claim to make by accident.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from a_share_platform.domain.market_data import ShareCapital
from a_share_platform.domain.risk import (
    RiskFactorKind,
    RiskStatus,
    ShrinkageCovarianceSpec,
    compute_factor_exposures,
    decompose_risk,
)

FOOD, BANK, ELEC = "食品饮料", "银行", "电子"
MOUTAI = "security:CN:600519:XSHG"
WULIANG = "security:CN:000858:XSHE"
ICBC = "security:CN:601398:XSHG"
BOE = "security:CN:000725:XSHE"

PORTFOLIO_WEIGHTS = {
    MOUTAI: Decimal("0.25"), WULIANG: Decimal("0.25"),
    ICBC: Decimal("0.25"), BOE: Decimal("0.25"),
}
BENCHMARK_WEIGHTS = {
    MOUTAI: Decimal("0.06"), WULIANG: Decimal("0.04"),
    ICBC: Decimal("0.30"), BOE: Decimal("0.20"),
}
INDUSTRY = {MOUTAI: FOOD, WULIANG: FOOD, ICBC: BANK, BOE: ELEC}


def exposure_of(exposures: tuple[object, ...], factor_id: str) -> object:
    matches = [
        item for item in exposures
        if item.factor_id == factor_id  # type: ignore[attr-defined]
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {factor_id}, got {len(matches)}")
    return matches[0]


def share_capital(*, total: str, free_float: str | None) -> ShareCapital:
    return ShareCapital(
        listing_id="listing:CN:600519:XSHG",
        effective_from=date(2025, 1, 1),
        effective_to=None,
        total_shares=Decimal(total),
        circulating_shares=Decimal(total),
        free_float_shares=None if free_float is None else Decimal(free_float),
        source_id="source:baostock",
        dataset_version_id="dataset-version:share-capital:2025-12-01",
    )


class ExposureTest(unittest.TestCase):
    def test_industry_exposure_is_the_summed_weight_of_its_members(self) -> None:
        """Hand computation: 0.25 + 0.25 in 食品饮料, 0.25 in 银行, 0.25 in 电子.
        Benchmark 0.10 / 0.30 / 0.20 → active +0.40 / -0.05 / +0.05."""
        exposures = compute_factor_exposures(
            portfolio_weights=PORTFOLIO_WEIGHTS,
            benchmark_weights=BENCHMARK_WEIGHTS,
            industry_by_security=INDUSTRY,
        )
        food = exposure_of(exposures, f"industry:{FOOD}")
        self.assertIs(food.kind, RiskFactorKind.INDUSTRY)
        self.assertEqual(food.portfolio_exposure, Decimal("0.50"))
        self.assertEqual(food.benchmark_exposure, Decimal("0.10"))
        self.assertEqual(food.active_exposure, Decimal("0.40"))
        self.assertIsNone(food.unavailable_reason)

        bank = exposure_of(exposures, f"industry:{BANK}")
        self.assertEqual(bank.portfolio_exposure, Decimal("0.25"))
        self.assertEqual(bank.benchmark_exposure, Decimal("0.30"))
        self.assertEqual(bank.active_exposure, Decimal("-0.05"))

        elec = exposure_of(exposures, f"industry:{ELEC}")
        self.assertEqual(elec.portfolio_exposure, Decimal("0.25"))
        self.assertEqual(elec.benchmark_exposure, Decimal("0.20"))
        self.assertEqual(elec.active_exposure, Decimal("0.05"))

    def test_active_exposure_needs_both_sides_or_reads_unavailable(self) -> None:
        """A benchmark industry weight that is missing makes active exposure
        unknown.  Reporting +0.50 against an assumed benchmark of zero would be
        an invented number."""
        exposures = compute_factor_exposures(
            portfolio_weights=PORTFOLIO_WEIGHTS,
            benchmark_weights={ICBC: Decimal("0.30"), BOE: Decimal("0.20")},
            industry_by_security=INDUSTRY,
        )
        food = exposure_of(exposures, f"industry:{FOOD}")
        self.assertEqual(food.portfolio_exposure, Decimal("0.50"))
        self.assertIsNone(food.benchmark_exposure)
        self.assertIsNone(food.active_exposure)
        self.assertIsNotNone(food.unavailable_reason)
        # 具体错在哪个 industry 必须写在 reason 里，否则下一个人只知道"有东西缺了"
        self.assertIn(FOOD, food.unavailable_reason)
        # 另一侧不受污染：银行两边都有，仍然是 QUANTIFIED 的差
        self.assertEqual(exposure_of(exposures, f"industry:{BANK}").active_exposure,
                         Decimal("-0.05"))

    def test_size_exposure_requires_share_capital_and_price(self) -> None:
        """ShareCapital already exists in domain/market_data.py with total,
        circulating and free-float shares.  Missing free float makes the free
        float variant unavailable while total-share Size stays available."""
        exposures = compute_factor_exposures(
            portfolio_weights={MOUTAI: Decimal("1.00")},
            benchmark_weights={MOUTAI: Decimal("1.00")},
            industry_by_security={MOUTAI: FOOD},
            share_capital_by_security={MOUTAI: share_capital(total="1000000", free_float=None)},
            price_by_security={MOUTAI: Decimal("10.00")},
        )
        total_size = exposure_of(exposures, "size:total_shares")
        self.assertIs(total_size.kind, RiskFactorKind.SIZE)
        self.assertIsNotNone(total_size.portfolio_exposure)
        self.assertIsNone(total_size.unavailable_reason)

        free_float_size = exposure_of(exposures, "size:free_float")
        self.assertIsNone(free_float_size.portfolio_exposure)
        self.assertIsNone(free_float_size.benchmark_exposure)
        self.assertIsNone(free_float_size.active_exposure)
        self.assertIsNotNone(free_float_size.unavailable_reason)

        # 缺价格时两个变体都不可得 —— market cap 需要 shares × price
        priceless = compute_factor_exposures(
            portfolio_weights={MOUTAI: Decimal("1.00")},
            benchmark_weights={MOUTAI: Decimal("1.00")},
            industry_by_security={MOUTAI: FOOD},
            share_capital_by_security={MOUTAI: share_capital(total="1000000",
                                                             free_float="400000")},
            price_by_security={},
        )
        for factor_id in ("size:total_shares", "size:free_float"):
            self.assertIsNone(exposure_of(priceless, factor_id).portfolio_exposure)
            self.assertIsNotNone(exposure_of(priceless, factor_id).unavailable_reason)

    def test_beta_exposure_below_minimum_observations_is_unavailable(self) -> None:
        """A beta from eight overlapping sessions is a number, not an estimate."""
        eight = tuple(
            (Decimal(f"0.0{index + 1}"), Decimal(f"0.00{index + 1}")) for index in range(8)
        )
        exposures = compute_factor_exposures(
            portfolio_weights={MOUTAI: Decimal("1.00")},
            benchmark_weights={MOUTAI: Decimal("1.00")},
            industry_by_security={MOUTAI: FOOD},
            beta_return_pairs=eight,
            minimum_beta_observations=60,
        )
        beta = exposure_of(exposures, "beta:benchmark")
        self.assertIs(beta.kind, RiskFactorKind.BETA)
        self.assertIsNone(beta.portfolio_exposure)
        self.assertIsNotNone(beta.unavailable_reason)
        # reason 必须同时说出实得与所需，否则无法判断差多少
        self.assertIn("8", beta.unavailable_reason)
        self.assertIn("60", beta.unavailable_reason)
        # 恰好达到门槛时可得：边界是 >=，不是 >
        exactly = compute_factor_exposures(
            portfolio_weights={MOUTAI: Decimal("1.00")},
            benchmark_weights={MOUTAI: Decimal("1.00")},
            industry_by_security={MOUTAI: FOOD},
            beta_return_pairs=eight,
            minimum_beta_observations=8,
        )
        self.assertIsNotNone(exposure_of(exactly, "beta:benchmark").portfolio_exposure)

    def test_an_unavailable_exposure_never_reports_a_value(self) -> None:
        # 断言：unavailable_reason 非空 → portfolio/benchmark/active 三者皆 None
        exposures = compute_factor_exposures(
            portfolio_weights=PORTFOLIO_WEIGHTS,
            benchmark_weights={},
            industry_by_security=INDUSTRY,
        )
        unavailable = [item for item in exposures if item.unavailable_reason is not None]
        self.assertNotEqual(unavailable, [], "this fixture must produce unavailable exposures")
        for item in unavailable:
            with self.subTest(factor_id=item.factor_id):
                self.assertIsNone(item.benchmark_exposure)
                self.assertIsNone(item.active_exposure)
        # 反向：任何带值的 exposure 都不得同时带 reason
        for item in exposures:
            if item.active_exposure is not None:
                self.assertIsNone(item.unavailable_reason, item.factor_id)
```

- [ ] **Step 2: 运行确认红测 → 实现 exposure → 转绿**

- [ ] **Step 3: 收缩协方差（红测先行）**

```python
class ShrinkageCovarianceTest(unittest.TestCase):
    def test_shrinkage_intensity_is_between_zero_and_one(self) -> None:
        """A shrinkage weight outside [0, 1] is not a convex combination and the
        result is not a covariance estimate."""

    def test_estimate_is_positive_semidefinite(self) -> None:
        """A non-PSD covariance yields negative portfolio variance downstream,
        which surfaces as a NaN standard deviation rather than as an error."""

    def test_fewer_observations_than_assets_still_yields_a_usable_estimate(self) -> None:
        """This is exactly why shrinkage is used: the sample covariance is
        singular when T < N, and a singular matrix produces meaningless risk
        contributions rather than an obvious failure."""

    def test_below_minimum_observations_refuses_rather_than_shrinking_harder(self) -> None:
        """Shrinking a five-observation sample all the way to the target returns
        the target, not an estimate of this portfolio's risk."""

    def test_spec_and_result_are_content_addressed_together(self) -> None:
        """Two runs with different shrinkage targets must not share an id."""
```

**实现要点**：Ledoit-Wolf 的收缩强度必须由公式算出并**记录在结果里**，
不得作为可调参数暗中调整。`shrinkage_target` 是版本化选择（`constant_correlation`
或 `identity`），不同选择产生不同 `content_hash`。

- [ ] **Step 4: 分项闭合（红测先行）—— 残差超阈值必须 FAIL**

这是本 Task 最重要的一组断言。

```python
class ClosureTest(unittest.TestCase):
    def test_factor_plus_specific_equals_total_within_tolerance(self) -> None:
        """The prototype prints "✓ 风险分项和闭合校验: factor + specific = 100%".
        That tick is only honest if the check can fail."""
        decomposition = decompose_risk(...)
        self.assertEqual(decomposition.status, RiskStatus.QUANTIFIED)
        self.assertLessEqual(abs(decomposition.closure_residual), decomposition.closure_tolerance)

    def test_residual_over_tolerance_fails_and_is_not_absorbed(self) -> None:
        """The failure mode this guards: a mismatch quietly renamed 'other' and
        printed as a component.  Once it has a label nobody looks for the bug."""
        decomposition = decompose_risk(...)  # inputs engineered to break closure
        self.assertEqual(decomposition.status, RiskStatus.CLOSURE_FAILED)
        self.assertIsNotNone(decomposition.unavailable_reason)
        names = [name for name, _value in decomposition.factor_contributions]
        for forbidden in ("other", "others", "residual", "unexplained", "其他"):
            self.assertNotIn(forbidden, [n.lower() for n in names])

    def test_closure_tolerance_is_declared_not_implicit(self) -> None:
        """A tolerance chosen inside the function can be widened to make a
        failing check pass, with no diff that looks like a behaviour change."""
        # 断言：tolerance 是必填输入且出现在 content_hash 里

    def test_marginal_contributions_sum_to_total_risk(self) -> None:
        """MCTR is Euler-decomposable; if the sum does not recover total risk the
        Top-5 table on the Risk page is ranking the wrong quantity."""

    def test_unavailable_exposure_excludes_the_factor_from_closure(self) -> None:
        """An unavailable factor cannot contribute 0 to the decomposition and
        still let it close — that would silently reallocate its risk to the
        others.  The decomposition itself becomes unavailable."""
```

- [ ] **Step 5: 情景分析（红测先行）—— 未映射暴露不填 0**

```python
class ScenarioTest(unittest.TestCase):
    def test_mapped_scenario_shock_propagates_through_exposures(self) -> None:
        """Hand computation: a -10% shock on 食品饮料 with 0.50 exposure is
        -5.00% at the portfolio level."""

    def test_unmapped_scenario_reads_unavailable_not_zero(self) -> None:
        """The prototype itself draws 行业轮动极端 (Rotational) as — / unavailable.
        docs/18 requires it: 未映射暴露 unavailable，不得填 0.  A zero would read
        as 'this scenario cannot hurt us'."""

    def test_partially_mapped_scenario_reports_its_coverage(self) -> None:
        """Three of five shocked factors mapped: the result states 3/5 rather
        than presenting a full-looking number built from part of the shock."""
```

- [ ] **Step 6: 独立库交叉验证（红测先行）**

```python
# platform/tests/test_risk_crosscheck.py
"""Cross-check the shrinkage covariance against NumPy/SciPy directly.

The existing validation/statistical_crosscheck.py contract is reused rather than
duplicated: CrossCheckSpec, CrossCheckStatus and StatisticalCrossCheckReport
already encode the two rules that matter — a tolerance must be declared, and an
absent reference library reports UNAVAILABLE rather than agreement.
"""

from __future__ import annotations

import unittest

from a_share_platform.validation.statistical_crosscheck import (
    CrossCheckSpec,
    CrossCheckStatus,
    cross_check_shrinkage_covariance,
)


class ShrinkageCrossCheckTest(unittest.TestCase):
    def test_reference_receives_the_identical_return_matrix(self) -> None:
        """A cross-check on different inputs proves nothing.  The input digest
        must be computed from the same matrix both engines saw."""

    def test_disagreement_beyond_tolerance_reports_mismatch(self) -> None:
        report = cross_check_shrinkage_covariance(...)
        self.assertEqual(report.status, CrossCheckStatus.MISMATCH)
        self.assertFalse(report.component("shrinkage_intensity").within_tolerance)

    def test_absent_numpy_reports_unavailable_not_matched(self) -> None:
        """Absence of the library must not read as agreement."""
        report = cross_check_shrinkage_covariance(...)  # with the import blocked
        self.assertEqual(report.status, CrossCheckStatus.UNAVAILABLE)
        self.assertIsNotNone(report.unavailable_reason)

    def test_component_names_cover_intensity_and_each_matrix_entry(self) -> None:
        """Comparing only the total variance would pass while individual
        covariances are wrong, and the risk contributions come from the entries."""
```

**注意**：`domain/risk.py` **不得** `import numpy`。交叉验证住在
`validation/`，那里可以导入 NumPy —— 这也是既有 `statistical_crosscheck.py` 的位置。
主实现用纯 Python + Decimal，参照实现用 NumPy float。
两者容差差异必须显式声明（Decimal 与 float64 本来不该逐位相等）。

- [ ] **Step 7: `ports/risk.py` 与 `application/risk_models.py`**

port 照抄 `ports/experiments.py` 的极简 Protocol 风格：

```python
class RiskModelStoreUnavailable(RuntimeError): ...

class RiskModelDecisionRepository(Protocol):
    def append_record(self, value: RiskModelDecisionRecord) -> RiskModelDecisionRecord: ...
    def get_record(self, record_id: str) -> RiskModelDecisionRecord | None: ...
    def list_records(self) -> tuple[RiskModelDecisionRecord, ...]: ...
```

application 层只编排：取 target → 取收益矩阵 → 调纯函数 → 调交叉验证 → 组装 record。
**不含任何数学。**

- [ ] **Step 8: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/domain/risk.py \
  platform/src/a_share_platform/ports/risk.py \
  platform/src/a_share_platform/application/risk_models.py \
  platform/src/a_share_platform/validation/statistical_crosscheck.py \
  platform/tests/test_risk_model_r0.py platform/tests/test_risk_crosscheck.py
git commit -m "feat: add Risk Model R0 with a closure check that can actually fail

The prototype prints a tick beside 'factor + specific = 100%'.  That tick is only
honest if the check can fail, so the residual is compared against a tolerance
that must be supplied by the caller and that enters the content hash.  A
tolerance chosen inside the function can be widened later to make a failing
portfolio pass, and the diff would not look like a behaviour change.

When closure breaks the decomposition reports CLOSURE_FAILED.  It does not open a
component called 'other' and put the difference there: once a mismatch has a
label it stops being a bug and starts being a row in a table, and nobody looks
for it again.  A test asserts no contribution is ever named other, residual or
unexplained.

An exposure that cannot be computed is unavailable with no value at all, and it
removes the whole decomposition from QUANTIFIED rather than contributing zero.
Contributing zero would let the remaining factors absorb its risk and still
close, which is closure by construction rather than by measurement.  The scenario
table follows the same rule and keeps the prototype's own unavailable row: a zero
shock reads as 'this scenario cannot hurt us'.

The covariance is cross-checked against NumPy on the identical return matrix, and
a missing NumPy reports unavailable rather than agreement.  domain/risk.py itself
imports no NumPy: the maths is Decimal in the domain and float64 in the
reference, so the tolerance between them is declared rather than assumed."
```

---

### Task 5: `domain/execution_rules.py` —— A 股规则判定（本 plan 最难的一步）

SPEC-034 的 MUST 清单原文：「次交易日成交、T+1 可卖库存、整手、佣金、最低佣金、印花税、
过户费、滑点、参与率/冲击、停牌、涨跌停、ST、分红送转、配股、退市、现金和 benchmark」。

本 Task 只做**纯规则判定**：给定一个订单意图与一个 session 的市场状态，
回答"能不能成、能成多少、被什么阻断"。**状态机的推进属 Task 7。**
拆开的理由：规则判定是无状态纯函数，可以用单个 session 的 fixture 穷举；
状态机是有状态的，它的测试要跨多个 session。混在一起时，
一个 T+1 的失败测试无法区分是"规则错"还是"库存推进错"。

**Files:**
- Create: `platform/src/a_share_platform/domain/execution_rules.py`
- Test: `platform/tests/test_execution_rules.py`

**Interfaces:**
- Consumes: `domain/market_data.py` 的 `DailyBar` / `DailyMarketState` / `PriceLimit` /
  `PriceLimitStatus` / `CorporateAction` / `ExchangeCalendar`、
  `domain/security_master.py` 的 `ListingState` / `SpecialTreatment`
- Produces:
  ```python
  class OrderSide(StrEnum):
      BUY = "buy"
      SELL = "sell"

  class BlockReason(StrEnum):
      SUSPENDED = "suspended"
      NOT_A_SESSION = "not_a_session"
      LIMIT_UP_LOCKED = "limit_up_locked"
      LIMIT_DOWN_LOCKED = "limit_down_locked"
      SPECIAL_TREATMENT_EXCLUDED = "special_treatment_excluded"
      DELISTED = "delisted"
      T1_INVENTORY = "t1_inventory"
      BELOW_ONE_LOT = "below_one_lot"
      PARTICIPATION_CAP = "participation_cap"
      MARKET_DATA_UNAVAILABLE = "market_data_unavailable"
      PRICE_POLICY_UNAVAILABLE = "price_policy_unavailable"

  class FillStatus(StrEnum):
      FILLED = "filled"
      PARTIAL = "partial"
      BLOCKED = "blocked"

  @dataclass(frozen=True)
  class EligibilityDecision:
      eligible: bool
      block_reasons: tuple[BlockReason, ...]
      detail: tuple[str, ...]

  @dataclass(frozen=True)
  class SellableInventory:
      settled_shares: int          # 可卖
      unsettled_shares: int        # 今日买入，T+1 才可卖
      as_of_session: date

  @dataclass(frozen=True)
  class ExecutionRuleSet:
      rule_set_id: str
      version: str
      lot_size: int
      participation_limit: Decimal
      exclude_special_treatment: bool
      allow_limit_locked_fills: bool     # 必须为 False；字段存在是为了让它进 hash
      settlement_days: int               # A 股 = 1
      content_hash: str = field(init=False)

  @dataclass(frozen=True)
  class CostModel:
      cost_model_version_id: str
      commission_rate: Decimal
      commission_minimum: Decimal
      stamp_duty_rate_sell: Decimal      # A 股印花税只在卖出侧
      transfer_fee_rate: Decimal
      slippage_rate: Decimal
      impact_coefficient: Decimal
      currency: str
      content_hash: str = field(init=False)

  def evaluate_eligibility(*, side: OrderSide, session: date,
      calendar: ExchangeCalendar, state: DailyMarketState | None,
      bar: DailyBar | None, price_limit: PriceLimit | None,
      inventory: SellableInventory, requested_shares: int,
      rules: ExecutionRuleSet) -> EligibilityDecision

  def cap_by_participation(*, requested_shares: int, session_volume_shares: int,
      rules: ExecutionRuleSet) -> tuple[int, tuple[str, ...]]

  def compute_costs(*, side: OrderSide, filled_shares: int, price: Decimal,
      model: CostModel) -> ExecutionCosts
  ```

- [ ] **Step 1: 先读被消费合同的真实语义（不要凭记忆）**

```bash
cd platform
sed -n 137,200p src/a_share_platform/domain/market_data.py     # DailyMarketState + PriceLimit
sed -n 294,323p src/a_share_platform/domain/market_data.py     # ExchangeCalendar
grep -n "class ListingState" -A6 src/a_share_platform/domain/security_master.py
grep -n "class SpecialTreatment" -A5 src/a_share_platform/domain/security_master.py
```

三条已被现有代码强制的事实，规则层要利用而不是重复实现：
`DailyMarketState` 拒绝 `is_trading and is_suspended` 同真；
`TERMINATED` 拒绝 `is_trading`；`PriceLimit.status_for(bar)` 已区分
`LIMIT_UP` 与 `LOCKED_UP`（后者是 `low == high == upper`，即全天封板）。

**`LOCKED_UP` 与 `LIMIT_UP` 的区别是本 Task 最重要的语义判断**：
封板（`LOCKED_UP`）意味着全天没有低于涨停的成交，买单基本不可能成交；
只是收于涨停（`LIMIT_UP`）意味着盘中有过低价成交，买单可能成交。
把两者合并处理会系统性高估或低估成交率。

- [ ] **Step 2: 写失败测试 —— T+1 结算（第一条，也是最容易写错的一条）**

```python
# platform/tests/test_execution_rules.py
"""A-share execution rules as stateless predicates.

Each rule answers one question about one session, so a failing test names the
rule rather than the simulation.  The state machine that advances inventory and
cash across sessions is separate (domain/backtest.py) for exactly that reason.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from a_share_platform.domain.execution_rules import (
    BlockReason,
    ExecutionRuleSet,
    OrderSide,
    SellableInventory,
    evaluate_eligibility,
)
from a_share_platform.domain.market_data import (
    CalendarDay,
    DailyBar,
    DailyMarketState,
    ExchangeCalendar,
    MarketDataUnavailable,
    PriceAdjustment,
    PriceLimit,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.security_master import (
    Exchange,
    ListingState,
    SpecialTreatment,
)

LISTING = "listing:CN:600519:XSHG"
SESSION = date(2025, 12, 2)


def rules(**overrides: object) -> ExecutionRuleSet:
    base: dict[str, object] = {
        "rule_set_id": "execution-rules:a-share",
        "version": "v0",
        "lot_size": 100,
        "participation_limit": Decimal("0.15"),
        "exclude_special_treatment": True,
        "allow_limit_locked_fills": False,
        "settlement_days": 1,
    }
    base.update(overrides)
    return ExecutionRuleSet(**base)  # type: ignore[arg-type]


def calendar(*sessions: date) -> ExchangeCalendar:
    return ExchangeCalendar(
        exchange=Exchange.XSHG,
        days=tuple(
            CalendarDay(
                exchange=Exchange.XSHG,
                calendar_date=day,
                is_open=True,
                closure_reason=None,
                source_id="source:calendar",
            )
            for day in sessions
        ),
    )


def bar(session: date = SESSION, *, close: str = "10.00", high: str = "10.50",
        low: str = "9.50", volume: int = 1_000_000) -> DailyBar:
    return DailyBar(
        listing_id=LISTING,
        exchange=Exchange.XSHG,
        session_date=session,
        currency="CNY",
        open=Decimal("10.00"),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        previous_close=Decimal("10.00"),
        volume_shares=volume,
        amount=Decimal("10000000"),
        adjustment=PriceAdjustment.UNADJUSTED,
        source_id="source:baostock",
        dataset_version_id="dataset-version:bars:2025",
        trust_state=DataTrustState.NORMALIZED_CURRENT,
    )


def state(session: date = SESSION, *, trading: bool = True, suspended: bool = False,
          listing_state: ListingState = ListingState.ACTIVE,
          treatment: SpecialTreatment = SpecialTreatment.NONE) -> DailyMarketState:
    return DailyMarketState(
        listing_id=LISTING,
        session_date=session,
        is_trading=trading,
        is_suspended=suspended,
        source_id="source:baostock",
        dataset_version_id="dataset-version:states:2025",
        trust_state=DataTrustState.NORMALIZED_CURRENT,
        listing_state=listing_state,
        special_treatment=treatment,
    )


class T1SettlementTest(unittest.TestCase):
    def test_shares_bought_today_cannot_be_sold_today(self) -> None:
        """A-share settlement is T+1: today's purchase is unsettled inventory.
        Selling it in the same session is the single most profitable bug a
        backtest can have, because it converts intraday volatility into free
        return."""
        decision = evaluate_eligibility(
            side=OrderSide.SELL,
            session=SESSION,
            calendar=calendar(SESSION),
            state=state(),
            bar=bar(),
            price_limit=None,
            inventory=SellableInventory(
                settled_shares=0, unsettled_shares=10_000, as_of_session=SESSION,
            ),
            requested_shares=10_000,
            rules=rules(),
        )
        self.assertFalse(decision.eligible)
        self.assertIn(BlockReason.T1_INVENTORY, decision.block_reasons)

    def test_settled_shares_are_sellable(self) -> None:
        decision = evaluate_eligibility(
            side=OrderSide.SELL,
            session=SESSION,
            calendar=calendar(SESSION),
            state=state(),
            bar=bar(),
            price_limit=None,
            inventory=SellableInventory(
                settled_shares=10_000, unsettled_shares=0, as_of_session=SESSION,
            ),
            requested_shares=10_000,
            rules=rules(),
        )
        self.assertTrue(decision.eligible)

    def test_partial_settlement_sells_only_the_settled_part(self) -> None:
        """5,000 settled and 5,000 unsettled against a 10,000 sell: the eligible
        quantity is 5,000 and the shortfall carries the T+1 reason.  Rejecting
        the whole order would understate turnover; filling it whole would invent
        return."""
        decision = evaluate_eligibility(
            side=OrderSide.SELL,
            session=SESSION,
            calendar=calendar(SESSION),
            state=state(),
            bar=bar(),
            price_limit=None,
            inventory=SellableInventory(
                settled_shares=5_000, unsettled_shares=5_000, as_of_session=SESSION,
            ),
            requested_shares=10_000,
            rules=rules(),
        )
        self.assertTrue(decision.eligible)
        self.assertIn(BlockReason.T1_INVENTORY, decision.block_reasons)
        self.assertTrue(any("5000" in text for text in decision.detail))

    def test_inventory_from_a_stale_session_is_refused(self) -> None:
        """An inventory snapshot dated before the session under evaluation cannot
        be trusted to reflect the settlement that happened in between."""
        with self.assertRaises(ValueError):
            evaluate_eligibility(
                side=OrderSide.SELL,
                session=SESSION,
                calendar=calendar(SESSION),
                state=state(),
                bar=bar(),
                price_limit=None,
                inventory=SellableInventory(
                    settled_shares=1_000, unsettled_shares=0,
                    as_of_session=date(2025, 11, 28),
                ),
                requested_shares=100,
                rules=rules(),
            )

    def test_settlement_days_is_configuration_not_a_literal(self) -> None:
        """T+1 is an exchange rule with a version, not a mathematical constant.
        A T+0 rule set must be constructible so the rule can be tested rather
        than assumed — and it must change the rule-set hash."""
        self.assertNotEqual(
            rules(settlement_days=1).content_hash,
            rules(settlement_days=0).content_hash,
        )
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_execution_rules -v`
Expected: FAIL —— `domain.execution_rules` 不存在。

- [ ] **Step 4: 实现 T+1 → 转绿**

只实现 T+1 与 `SellableInventory` 的校验。其余规则逐条补。

- [ ] **Step 5: 100 股整手（红测先行）**

```python
class LotRoundingTest(unittest.TestCase):
    def test_buy_quantity_rounds_down_to_whole_lots(self) -> None:
        """A 1,050-share buy becomes 1,000.  A-share buys must be whole lots."""

    def test_a_sub_lot_buy_is_blocked_with_below_one_lot(self) -> None:
        """50 shares is not a tradable buy quantity; it is not a 50-share fill
        and it is not a zero-cost no-op — it is a blocked order with a reason."""
        # 断言 BlockReason.BELOW_ONE_LOT

    def test_an_odd_lot_sell_is_allowed(self) -> None:
        """Asymmetric on purpose: A-share sells may clear an odd lot created by a
        bonus issue, while buys may not.  Applying the buy rule to sells would
        strand shares in the portfolio forever, and the stranded amount grows
        with every corporate action."""
        decision = evaluate_eligibility(
            side=OrderSide.SELL,
            session=SESSION,
            calendar=calendar(SESSION),
            state=state(),
            bar=bar(),
            price_limit=None,
            inventory=SellableInventory(
                settled_shares=1_050, unsettled_shares=0, as_of_session=SESSION,
            ),
            requested_shares=1_050,
            rules=rules(),
        )
        self.assertTrue(decision.eligible)
        self.assertNotIn(BlockReason.BELOW_ONE_LOT, decision.block_reasons)

    def test_lot_size_comes_from_the_rule_set(self) -> None:
        """STAR board and some funds do not use 100; a literal 100 in the code
        would silently misprice those."""
```

**这条不对称性是 A 股规则里最容易漏的一条。** 送股产生的碎股（例如 10 送 3 后
1,000 股变 1,300 股，若基数不是整百则出现非整百余数）必须能卖出，
否则回测里会永久留下不可处置的股票，并在长周期里累积成显著的估值偏差。

- [ ] **Step 6: 涨跌停阻断（红测先行）**

```python
class PriceLimitTest(unittest.TestCase):
    def test_locked_limit_up_blocks_a_buy(self) -> None:
        """PriceLimit.status_for already distinguishes LOCKED_UP (low == high ==
        upper, no trade below the cap all day) from LIMIT_UP (closed at the cap
        after trading lower).  A buy into a locked board cannot fill."""
        limit = PriceLimit(
            listing_id=LISTING, session_date=SESSION,
            lower=Decimal("9.00"), upper=Decimal("11.00"),
            source_id="source:rules",
        )
        locked = bar(close="11.00", high="11.00", low="11.00")
        decision = evaluate_eligibility(
            side=OrderSide.BUY, session=SESSION, calendar=calendar(SESSION),
            state=state(), bar=locked, price_limit=limit,
            inventory=SellableInventory(0, 0, SESSION),
            requested_shares=1_000, rules=rules(),
        )
        self.assertFalse(decision.eligible)
        self.assertIn(BlockReason.LIMIT_UP_LOCKED, decision.block_reasons)

    def test_unlocked_limit_up_does_not_block_a_buy(self) -> None:
        """Closing at the cap after trading down to 10.20 means a buy could have
        filled.  Blocking it would understate achievable turnover, and the
        understatement is not symmetric across strategies."""
        limit = PriceLimit(
            listing_id=LISTING, session_date=SESSION,
            lower=Decimal("9.00"), upper=Decimal("11.00"),
            source_id="source:rules",
        )
        decision = evaluate_eligibility(
            side=OrderSide.BUY, session=SESSION, calendar=calendar(SESSION),
            state=state(), bar=bar(close="11.00", high="11.00", low="10.20"),
            price_limit=limit, inventory=SellableInventory(0, 0, SESSION),
            requested_shares=1_000, rules=rules(),
        )
        self.assertTrue(decision.eligible)

    def test_locked_limit_down_blocks_a_sell(self) -> None:
        """Symmetric: a locked down board traps a seller."""

    def test_locked_limit_up_does_not_block_a_sell(self) -> None:
        """A seller into a locked-up board is exactly who can trade."""

    def test_absent_price_limit_reads_unavailable_not_no_limit(self) -> None:
        """docs/11-p2-data-source-coverage-matrix.md line 32 records that
        BaoStock has 无独立上下限字段 for price limits, so absence is the normal
        case today.  Treating absence as 'no limit exists' would let every order
        fill through a board that really was locked, which flatters the result.
        The order is blocked with MARKET_DATA_UNAVAILABLE instead."""
        decision = evaluate_eligibility(
            side=OrderSide.BUY, session=SESSION, calendar=calendar(SESSION),
            state=state(), bar=bar(), price_limit=None,
            inventory=SellableInventory(0, 0, SESSION),
            requested_shares=1_000, rules=rules(strict_price_limits=True),
        )
        self.assertFalse(decision.eligible)
        self.assertIn(BlockReason.MARKET_DATA_UNAVAILABLE, decision.block_reasons)

    def test_allow_limit_locked_fills_must_be_false_in_any_shipped_rule_set(self) -> None:
        """The field exists so the choice enters the hash, not so it can be
        turned on.  A rule set with it True is refused."""
        with self.assertRaises(ValueError):
            rules(allow_limit_locked_fills=True)
```

**注意 `strict_price_limits` 这个额外字段**：`PriceLimit` 数据当前不存在
（`docs/11` 第 32 行确认 BaoStock 无独立字段，需按规则版本计算）。
两种处理都可辩护 —— 严格阻断（保守，低估成交）或按规则推算上下限。
本 plan 要求：**必须是显式配置且进入 hash**，并在 Run 里记录哪一种口径。
不允许默认"无数据即无限制"，那是唯一会系统性美化结果的选项。

- [ ] **Step 7: 停牌、ST、退市（红测先行）**

```python
def closed_calendar(day: date, *, reason: str = "public holiday") -> ExchangeCalendar:
    return ExchangeCalendar(
        exchange=Exchange.XSHG,
        days=(
            CalendarDay(
                exchange=Exchange.XSHG,
                calendar_date=day,
                is_open=False,
                closure_reason=reason,
                source_id="source:calendar",
            ),
        ),
    )


class TradingStateTest(unittest.TestCase):
    def test_suspended_session_blocks_both_sides(self) -> None:
        # DailyMarketState(is_trading=False, is_suspended=True) → SUSPENDED
        for side, inventory in (
            (OrderSide.BUY, SellableInventory(0, 0, SESSION)),
            (OrderSide.SELL, SellableInventory(1_000, 0, SESSION)),
        ):
            with self.subTest(side=side):
                decision = evaluate_eligibility(
                    side=side, session=SESSION, calendar=calendar(SESSION),
                    state=state(trading=False, suspended=True), bar=bar(),
                    price_limit=None, inventory=inventory,
                    requested_shares=1_000, rules=rules(),
                )
                self.assertFalse(decision.eligible)
                self.assertIn(BlockReason.SUSPENDED, decision.block_reasons)

    def test_non_session_date_blocks_before_any_other_check(self) -> None:
        """A date the calendar says is closed must be rejected as NOT_A_SESSION
        rather than falling through to a missing-bar error, which would read as a
        data gap and send the next person to the wrong place."""
        decision = evaluate_eligibility(
            side=OrderSide.BUY, session=SESSION, calendar=closed_calendar(SESSION),
            state=None, bar=None, price_limit=None,
            inventory=SellableInventory(0, 0, SESSION),
            requested_shares=1_000, rules=rules(),
        )
        self.assertFalse(decision.eligible)
        # "before any other check"：即使 state 与 bar 双缺，唯一原因也必须是 NOT_A_SESSION
        self.assertEqual(decision.block_reasons, (BlockReason.NOT_A_SESSION,))
        self.assertNotIn(BlockReason.MARKET_DATA_UNAVAILABLE, decision.block_reasons)

    def test_calendar_with_no_observation_for_the_date_fails_closed(self) -> None:
        """ExchangeCalendar.is_session raises MarketDataUnavailable for an
        unobserved date.  That exception must not be swallowed into 'closed'."""
        unobserved = calendar(date(2025, 12, 3))  # SESSION 本身没有观测
        decision = evaluate_eligibility(
            side=OrderSide.BUY, session=SESSION, calendar=unobserved,
            state=state(), bar=bar(), price_limit=None,
            inventory=SellableInventory(0, 0, SESSION),
            requested_shares=1_000, rules=rules(),
        )
        self.assertFalse(decision.eligible)
        # 未观测 ≠ 休市：前者是数据缺口，后者是市场事实，两者的下一步动作不同
        self.assertIn(BlockReason.MARKET_DATA_UNAVAILABLE, decision.block_reasons)
        self.assertNotIn(BlockReason.NOT_A_SESSION, decision.block_reasons)
        self.assertTrue(any("calendar" in text for text in decision.detail))
        # 底层异常本身仍必须可抛，规则层只在自己的边界上转译它
        with self.assertRaises(MarketDataUnavailable):
            unobserved.is_session(SESSION)

    def test_special_treatment_is_excluded_when_the_rule_set_says_so(self) -> None:
        """The prototype draws an ST排除 chip.  Exclusion is a policy choice, so
        it lives in the rule set: SpecialTreatment.ST and STAR_ST both exclude
        when exclude_special_treatment is True."""
        for treatment in (SpecialTreatment.ST, SpecialTreatment.STAR_ST):
            decision = evaluate_eligibility(
                side=OrderSide.BUY, session=SESSION, calendar=calendar(SESSION),
                state=state(treatment=treatment), bar=bar(), price_limit=None,
                inventory=SellableInventory(0, 0, SESSION),
                requested_shares=1_000, rules=rules(exclude_special_treatment=True),
            )
            self.assertIn(BlockReason.SPECIAL_TREATMENT_EXCLUDED, decision.block_reasons)

    def test_st_exclusion_blocks_buys_but_never_traps_an_existing_holding(self) -> None:
        """A name that becomes ST while held must still be sellable.  Excluding
        both sides would freeze the position until delisting, and the frozen
        value would quietly become a permanent part of the equity curve."""
        decision = evaluate_eligibility(
            side=OrderSide.SELL, session=SESSION, calendar=calendar(SESSION),
            state=state(treatment=SpecialTreatment.ST), bar=bar(), price_limit=None,
            inventory=SellableInventory(1_000, 0, SESSION),
            requested_shares=1_000, rules=rules(exclude_special_treatment=True),
        )
        self.assertTrue(decision.eligible)

    def test_terminated_listing_blocks_buys_and_routes_sells_to_liquidation(self) -> None:
        """ListingState.TERMINATED already forbids is_trading in the domain, so
        there is no session to trade in.  A held position becomes a delisting
        cash flow rather than a sell order, and DELISTED says which."""
        terminated = state(trading=False, listing_state=ListingState.TERMINATED)
        buy = evaluate_eligibility(
            side=OrderSide.BUY, session=SESSION, calendar=calendar(SESSION),
            state=terminated, bar=bar(), price_limit=None,
            inventory=SellableInventory(0, 0, SESSION),
            requested_shares=1_000, rules=rules(),
        )
        self.assertFalse(buy.eligible)
        self.assertIn(BlockReason.DELISTED, buy.block_reasons)

        sell = evaluate_eligibility(
            side=OrderSide.SELL, session=SESSION, calendar=calendar(SESSION),
            state=terminated, bar=bar(), price_limit=None,
            inventory=SellableInventory(1_000, 0, SESSION),
            requested_shares=1_000, rules=rules(),
        )
        # 卖出同样不可成交，但原因必须是 DELISTED 而不是 SUSPENDED：
        # 前者路由到退市现金流，后者只是等复牌
        self.assertFalse(sell.eligible)
        self.assertIn(BlockReason.DELISTED, sell.block_reasons)
        self.assertNotIn(BlockReason.SUSPENDED, sell.block_reasons)

    def test_missing_market_state_is_not_treated_as_tradable(self) -> None:
        """state=None means we do not know whether it traded.  Assuming it did is
        how a suspended session becomes a fill."""
        for side, inventory in (
            (OrderSide.BUY, SellableInventory(0, 0, SESSION)),
            (OrderSide.SELL, SellableInventory(1_000, 0, SESSION)),
        ):
            with self.subTest(side=side):
                decision = evaluate_eligibility(
                    side=side, session=SESSION, calendar=calendar(SESSION),
                    state=None, bar=bar(), price_limit=None, inventory=inventory,
                    requested_shares=1_000, rules=rules(),
                )
                self.assertFalse(decision.eligible)
                self.assertIn(BlockReason.MARKET_DATA_UNAVAILABLE, decision.block_reasons)
                self.assertNotIn(BlockReason.SUSPENDED, decision.block_reasons)

    def test_missing_bar_is_not_treated_as_tradable_either(self) -> None:
        """A session with a market state but no bar has no price to trade at, so
        there is nothing for the price policy to reference."""
        decision = evaluate_eligibility(
            side=OrderSide.BUY, session=SESSION, calendar=calendar(SESSION),
            state=state(), bar=None, price_limit=None,
            inventory=SellableInventory(0, 0, SESSION),
            requested_shares=1_000, rules=rules(),
        )
        self.assertFalse(decision.eligible)
        self.assertIn(BlockReason.MARKET_DATA_UNAVAILABLE, decision.block_reasons)
```

- [ ] **Step 8: 参与率与部分成交（红测先行）**

```python
class ParticipationTest(unittest.TestCase):
    def test_order_above_the_participation_cap_is_capped_not_rejected(self) -> None:
        """Hand computation: 1,000,000-share session volume at a 15% cap allows
        150,000 shares.  A 300,000-share order fills 150,000 as PARTIAL with the
        PARTICIPATION_CAP reason — the prototype's 参与率超限 row."""
        capped, detail = cap_by_participation(
            requested_shares=300_000, session_volume_shares=1_000_000, rules=rules(),
        )
        self.assertEqual(capped, 150_000)
        self.assertTrue(detail)

    def test_the_cap_is_rounded_down_to_whole_lots(self) -> None:
        """15% of 1,000,050 is 150,007.5; the fill is 150,000, not 150,007."""

    def test_zero_session_volume_blocks_rather_than_dividing(self) -> None:
        """A session with no volume is not a session with an infinite cap."""

    def test_missing_volume_is_unavailable_not_unlimited(self) -> None:
        """Absent volume must block, because an uncapped fill in an illiquid name
        is the single largest source of unachievable backtest return."""
```

- [ ] **Step 9: 费用模型（红测先行）**

```python
class CostModelTest(unittest.TestCase):
    def test_stamp_duty_applies_to_sells_only(self) -> None:
        """A-share stamp duty is one-sided.  Charging it on buys doubles the
        modelled cost and makes every strategy look worse by a constant, which is
        harder to notice than an obvious error."""

    def test_commission_minimum_dominates_a_small_order(self) -> None:
        """Hand computation: 100 shares at 10.00 is 1,000 notional; at 0.0008 the
        commission is 0.80, below a 5.00 minimum, so 5.00 is charged.  Without
        the minimum, a strategy that trades in tiny clips looks costless."""

    def test_every_cost_component_is_reported_separately(self) -> None:
        """The Attribution page decomposes commission, stamp duty, slippage and
        impact as four rows.  A single total cannot be decomposed later."""

    def test_changing_any_rate_changes_the_cost_model_hash(self) -> None:
        """ADR-0006 decision 6: fees, slippage, impact, participation, price
        convention and calendar version all enter the run hash."""

    def test_costs_are_never_negative(self) -> None:
        """A negative cost is a rebate, and no rebate is modelled here."""
```

- [ ] **Step 10: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest tests.test_execution_rules -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/domain/execution_rules.py \
  platform/tests/test_execution_rules.py
git commit -m "feat: add A-share execution rules as stateless per-session predicates

Rules and state are separated deliberately.  Each predicate answers one question
about one session, so a failing T+1 test names the settlement rule rather than
the simulation loop; when the two live together a red test cannot tell you which
of them is wrong.

Three rules are asymmetric and the asymmetry is the point.  Buys must be whole
lots and sells may clear an odd lot, because a bonus issue creates one and a
symmetric rule would strand those shares in the portfolio forever — an error that
compounds with every corporate action.  A locked limit-up board blocks a buy and
not a sell, and a locked limit-down board the reverse, since the trapped side is
the one that cannot find a counterparty.  An ST name cannot be bought but must
still be sellable, otherwise a position that turns ST while held is frozen until
delisting and its stale value quietly becomes part of the equity curve.

Absent data blocks rather than permits.  A missing price limit does not mean no
limit exists — docs/11 records that BaoStock has no such field, so absence is the
normal case — and a missing session volume does not mean an unlimited fill.  Both
of those defaults would only ever flatter the result, which is why the
conservative choice is the default and the alternative has to be configured and
hashed.

PriceLimit.status_for's existing distinction between LOCKED_UP and LIMIT_UP is
used rather than collapsed: closing at the cap after trading lower means a buy
could have filled, while a board locked all day means it could not.  Merging them
biases fill rates in a direction that differs by strategy, so it cannot be
corrected afterwards."
```

---

### Task 6: 外部引擎 D0 spike 与 ADR（决策门，必须在任何 adapter 之前）

冻结 Plan 的 Task 5 原文：「**先做 D0 spike/ADR**，再新增 `adapters/rqalpha/` 或
批准的 engine 目录、frozen export/import 和 diff classifier；外部依赖不进入 domain。」

ADR-0006 决策 3 的措辞是**条件性**的：「第一外部回测对照引擎选择 RQAlpha，通过 adapter 隔离；
**若资格 spike 证明不可用**，再以新 ADR 选择 LEAN，不修改内部领域合同。」

2026-08-16 实测：`import rqalpha` → `ModuleNotFoundError`。**它没有被选定，它被条件性提名了。**

**Files:**
- Create: `platform/scripts/spike_external_backtest_engine.py`
- Create: `docs/adr/0013-external-backtest-engine-qualification.md`（状态取决于 spike 结果）
- Modify: `docs/27-p6-implementation-evidence.md`
- Modify: `platform/tests/test_architecture_contract.py`（若引入引擎依赖，把它加进 `forbidden_roots`）

**Interfaces:** 本 Task **不新增 adapter 代码**。产出是一份可复现的资格结论。

- [ ] **Step 1: 定义 spike 必须回答的问题（先写清单，再动手）**

至少：

```text
1. 安装可行性：目标 Python（本机 3.12.12）能否安装？依赖是否与已装 numpy 2.5.2 /
   scipy 1.18.0 / pandas 冲突？冲突是否会降级本平台已验证的依赖？
2. 数据 bundle：引擎需要什么格式的历史数据？能否从本平台的 Parquet
   （adapters/parquet/market_data.py 的分区布局）导出而不重新下载？
3. A 股规则覆盖：引擎自己实现哪些规则（T+1 / 涨跌停 / 整手 / 停牌 / ST /
   公司行动）？它的实现口径与 Task 5 的规则集是否一致？不一致的项如何在 diff
   classifier 中归类为"引擎口径差异"而非"实现缺陷"？
4. 确定性：同一输入两次运行是否逐笔一致？是否有随机种子、时钟依赖或并发顺序依赖？
5. 许可证：许可是否允许本地私人研究使用？是否有再分发或商业限制？
6. 隔离性：引擎是否要求全局状态、写文件系统、起子进程或联网？
7. 逐笔可比性：引擎输出是否包含足以做逐笔 reconciliation 的字段
   （session、代码、方向、计划数量、实际数量、价格、费用、阻断原因）？
8. 阻断可见性：引擎是否**报告**被阻断的订单，还是静默丢弃？静默丢弃会让
   reconciliation 出现"内部有阻断记录、外部无记录"的系统性差异。
9. 失败语义：数据缺失、代码不存在、日历缺日时引擎的行为（异常 / 静默跳过 / 填零）。
10. 版本可钉：能否钉住一个具体版本以进入 Run hash？
```

**第 8 项是最可能导致否决的一项。** 一个不报告阻断订单的引擎无法用于本平台的
reconciliation，因为 SPEC-034 的验收是「被阻塞订单有原因且不会静默消失」。

- [ ] **Step 2: 在隔离环境跑安装 spike（不污染主 venv）**

```bash
cd platform
python3 -m venv /tmp/asp_engine_spike
/tmp/asp_engine_spike/bin/python -m pip install --upgrade pip
/tmp/asp_engine_spike/bin/python -m pip install rqalpha 2>&1 | tail -40
/tmp/asp_engine_spike/bin/python -c "import rqalpha, sys; print(rqalpha.__version__, sys.version)" \
  || echo "SPIKE RESULT: rqalpha not installable on this interpreter"
```

**必须用独立 venv。** 直接装进 `platform/.venv` 会污染已通过 817 项测试的环境，
且如果 spike 失败，卸载不一定能完全恢复依赖版本。

- [ ] **Step 3: 写 spike 脚本并记录结构化结果**

```python
# platform/scripts/spike_external_backtest_engine.py
"""D0 qualification spike for the external comparison backtest engine.

Not a test and not an adapter.  ADR-0006 names RQAlpha but conditions it on a
qualification spike, and this script is that spike: it answers the ten questions
in docs/27 with reproducible evidence and writes a structured verdict.

It must be safe to run when the engine is absent.  A spike that cannot reach the
engine reports cannot_evaluate, never qualified — the same rule the PIT source
probe follows, and for the same reason: absence of evidence is not evidence that
there is no problem.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from enum import StrEnum


class SpikeVerdict(StrEnum):
    QUALIFIED = "qualified"
    QUALIFIED_WITH_KNOWN_DEVIATIONS = "qualified_with_known_deviations"
    NOT_QUALIFIED = "not_qualified"
    CANNOT_EVALUATE = "cannot_evaluate"


@dataclass(frozen=True)
class SpikeFinding:
    question_id: str
    question: str
    observed: str
    blocking: bool


def run(engine_id: str) -> int:
    findings: list[SpikeFinding] = []
    # Every finding records what was actually observed on this machine, including
    # the import error text verbatim when the engine is absent.
    ...
    verdict = ...
    print(json.dumps({
        "engine_id": engine_id,
        "verdict": verdict,
        "findings": [asdict(item) for item in findings],
    }, ensure_ascii=False, indent=2))
    return 0 if verdict is not SpikeVerdict.CANNOT_EVALUATE else 2


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1] if len(sys.argv) > 1 else "rqalpha"))
```

- [ ] **Step 4: 写 ADR-0013，状态由结果决定**

三种合法结果，**每一种都要写进 ADR 并给出后果**：

```text
verdict = qualified                     → ADR-0013 Accepted，选定引擎，Task 8 可建 adapter
verdict = qualified_with_known_deviations → ADR-0013 Accepted，但必须逐项列出口径差异
                                           及其在 diff classifier 中的分类
verdict = not_qualified                 → ADR-0013 Accepted（决定"不用它"也是决定），
                                           并按 ADR-0006 决策 3 提名 LEAN 做第二次 spike
verdict = cannot_evaluate               → ADR-0013 保持 Proposed，
                                           双引擎 reconciliation 记为 unavailable
```

**关键约束**：无论哪种结果，**Task 5 与 Task 7 的内部领域合同不得修改**
（ADR-0006 决策 3 原文：「不修改内部领域合同」）。
如果 spike 显示引擎的 T+1 口径与本平台不同，正确做法是在 diff classifier 里
分类为口径差异，而不是改本平台的 T+1 让两边一致。

- [ ] **Step 5: 若结果不是 qualified，明确记录 reconciliation 不可用**

SPEC-034 说「同信号 **SHOULD** 在内部引擎和 RQAlpha/LEAN 之一运行」——
是 SHOULD 不是 MUST。因此 `not_qualified` / `cannot_evaluate` **不阻断 P6 其余部分**，
但必须：

- Backtests 页的「Internal vs RQAlpha Reconciliation」分区显示真实 `unavailable` + 原因；
- Evidence 明确写「双引擎 reconciliation 未完成，因此 SPEC-034 的 SHOULD 项未满足」；
- **不得**用内部引擎跑两次然后声称"双引擎一致"。

- [ ] **Step 6: 提交**

```bash
cd /Users/casiezhou/personal/Quantamental
git add platform/scripts/spike_external_backtest_engine.py \
  docs/adr/0013-external-backtest-engine-qualification.md \
  docs/27-p6-implementation-evidence.md
git commit -m "feat: add the external engine qualification spike before any engine adapter

ADR-0006 names RQAlpha but conditions it on a qualification spike, and rqalpha is
not installed on this machine at all.  Creating adapters/rqalpha/ first would
turn a conditional nomination into a decision and leave a dependency in the tree
that the gate was supposed to authorise.

The spike installs into a throwaway venv rather than platform/.venv.  Installing
into the verified environment risks silently downgrading numpy or pandas
underneath 817 passing tests, and an uninstall does not reliably restore the
versions that were there before.

The question most likely to disqualify an engine is whether it reports blocked
orders or discards them silently.  SPEC-034 requires blocked orders to carry a
reason and never disappear; an engine that drops them produces a reconciliation
where every internal block looks like a discrepancy, which is worse than no
reconciliation because it looks like evidence.

All four verdicts are written out with their consequences, including that a
not-qualified engine does not block P6: SPEC-034 makes dual-engine comparison a
SHOULD.  What it does block is the claim — the reconciliation panel reports
unavailable, and running the internal engine twice does not count as two engines."
```

---

### Task 7: `domain/backtest.py` 状态机 + `domain/attribution.py` 闭合归因

冻结 Plan 的 Task 4 要求「严格按 session → eligibility → intent → fill/block →
inventory/cash → valuation 状态机 TDD」，Task 6 要求「residual 超阈值失败，未参与项不填 0」。

**六个转移各自一个红测。** 一次实现整条链会让第一个失败的转移掩盖后面五个。

**Files:**
- Create: `platform/src/a_share_platform/domain/backtest.py`
- Create: `platform/src/a_share_platform/domain/attribution.py`
- Test: `platform/tests/test_realistic_backtest_state_machine.py`
- Test: `platform/tests/test_realistic_backtest_corporate_actions.py`
- Test: `platform/tests/test_portfolio_statistics.py`
- Test: `platform/tests/test_core_attribution.py`

**Interfaces:**
- Consumes: Task 2 / 3 / 5 的全部纯函数、`domain/market_data.py`
- Produces:
  ```python
  class BacktestKind(StrEnum):
      """SPEC-033: types are named, never merged into a generic 'backtest'."""
      STOCK_SELECTION_BACKTEST = "stock_selection_backtest"
      EXECUTION_SIMULATION = "execution_simulation"

  class BacktestStage(StrEnum):
      SESSION = "session"
      ELIGIBILITY = "eligibility"
      INTENT = "intent"
      SETTLEMENT = "settlement"      # fill / block
      INVENTORY = "inventory"
      VALUATION = "valuation"

  @dataclass(frozen=True)
  class OrderIntent:
      intent_id: str
      security_id: str
      listing_id: str
      side: OrderSide
      requested_shares: int
      reference_price: Decimal
      target_id: str
      session: date

  @dataclass(frozen=True)
  class TradeRecord:
      trade_id: str
      intent_id: str
      session: date
      side: OrderSide
      requested_shares: int
      filled_shares: int          # BLOCKED 时为 0，且必须保留该行
      fill_price: Decimal | None
      status: FillStatus
      block_reasons: tuple[BlockReason, ...]
      costs: ExecutionCosts | None

  @dataclass(frozen=True)
  class InventoryState:
      session: date
      settled: Mapping[str, int]
      unsettled: Mapping[str, int]
      cash_amount: Decimal
      currency: str

  @dataclass(frozen=True)
  class SessionValuation:
      session: date
      position_value: Decimal
      cash_amount: Decimal
      total_equity: Decimal
      benchmark_level: Decimal | None
      corporate_action_cash: Decimal
      unavailable_listings: tuple[tuple[str, str], ...]

  class RightsIssueChoice(StrEnum):
      """ADR-0006 决策 5：配股不得隐式处理，政策必须显式声明并入账。"""
      SUBSCRIBE_IN_FULL = "subscribe_in_full"
      DECLINE = "decline"

  @dataclass(frozen=True)
  class CorporateActionEffect:
      action_id: str
      listing_id: str
      ex_date: date
      action_type: CorporateActionType
      share_delta: int              # 送转/拆股/配股的股数变化；分红为 0
      cash_delta: Decimal           # 分红为正、配股认购为负
      reference_price_multiplier: Decimal | None   # 拆并股缩放；分红为 None
      rights_issue_choice: RightsIssueChoice | None
      removes_holding: bool         # 仅退市现金流为 True

  @dataclass(frozen=True)
  class DelistingCashFlow:
      """退市不是 CorporateActionType 的成员（现有五个成员没有它），
      它由 ListingState.TERMINATED 驱动，因此是独立入口与独立返回类型。"""
      listing_id: str
      session: date
      share_delta: int              # 必然为 -held_shares
      cash_delta: Decimal | None    # 清算价未知时为 None，不得填 0
      removes_holding: bool         # 恒为 True
      unavailable_reason: str | None

  def apply_corporate_action(*, action: CorporateAction, held_shares: int,
      session: date, rights_issue_choice: RightsIssueChoice | None = None,
      available_cash: Decimal | None = None) -> CorporateActionEffect

  def resolve_delisting_cash_flow(*, listing_id: str, session: date,
      held_shares: int, listing_state: ListingState,
      final_cash_per_share: Decimal | None) -> DelistingCashFlow

  @dataclass(frozen=True)
  class StatisticsSpec:
      """SPEC-035 的每个口径都是版本化输入，不是埋在函数里的选择。"""
      spec_id: str
      annualization_sessions: int          # 252 / 244 / 250 都是约定，不是事实
      minimum_sample_sessions: int
      risk_free_annual_rate: Decimal
      bootstrap_resamples: int             # >= 100
      bootstrap_seed: int
      bootstrap_confidence_level: Decimal
      trial_count: int | None              # PSR/DSR 必需；None 时两者 UNAVAILABLE
      preregistered_subperiods: tuple[tuple[date, date], ...]
      formula_version: str
      content_hash: str = field(init=False)

  @dataclass(frozen=True)
  class StatisticValue:
      """QUANTIFIED 必须有 value；UNAVAILABLE 必须有 reason 且 value 为 None。"""
      statistic_id: str
      status: StatisticStatus              # 复用 domain/factor_statistics.py
      value: Decimal | None
      unavailable_reason: str | None

  @dataclass(frozen=True)
  class PortfolioStatistics:
      spec: StatisticsSpec
      gross_of_cost: tuple[StatisticValue, ...]
      net_of_cost: tuple[StatisticValue, ...]
      benchmark: tuple[StatisticValue, ...]
      subperiods: tuple[tuple[tuple[date, date], tuple[StatisticValue, ...]], ...]

      def statistic(self, statistic_id: str, *, basis: str = "net") -> StatisticValue: ...

  def compute_portfolio_statistics(*, equity_series: Sequence[tuple[date, Decimal]],
      cost_series: Sequence[tuple[date, Decimal]],
      benchmark_series: Sequence[tuple[date, Decimal]] | None,
      spec: StatisticsSpec) -> PortfolioStatistics

  @dataclass(frozen=True)
  class BacktestRunSpec:
      run_id: str
      kind: BacktestKind
      policy: PortfolioPolicy
      rules: ExecutionRuleSet
      cost_model: CostModel
      calendar_version_id: str
      execution_price_policy_id: str
      start_session: date
      end_session: date
      run_context: RunContext
      content_hash: str = field(init=False)

  def advance_session(state: InventoryState, *, session: date,
      intents: Sequence[OrderIntent], market: SessionMarketData,
      rules: ExecutionRuleSet, cost_model: CostModel,
  ) -> tuple[InventoryState, tuple[TradeRecord, ...], SessionValuation]
  ```

- [ ] **Step 1: 转移 1 —— session（红测先行）**

```python
# platform/tests/test_realistic_backtest_state_machine.py
"""The backtest as an explicit state machine.

session → eligibility → intent → fill/block → inventory/cash → valuation.
Each transition has its own red test, because a single end-to-end test that fails
tells you the simulation is wrong without telling you where, and the six
transitions fail for entirely different reasons.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from decimal import Decimal

from a_share_platform.domain.backtest import (
    BacktestKind,
    BacktestStage,
    InventoryState,
    OrderIntent,
    advance_session,
    resolve_eligible_session,
)
from a_share_platform.domain.execution_rules import BlockReason, FillStatus, OrderSide
from a_share_platform.domain.market_data import MarketDataUnavailable


class SessionTransitionTest(unittest.TestCase):
    def test_after_close_signal_trades_on_the_next_session(self) -> None:
        """SPEC-034 acceptance, verbatim: 不存在用盘后才生成的信号按当日收盘成交.
        A decision formed at 2025-12-01 15:30 CST trades on 12-02, not 12-01."""
        eligible = resolve_eligible_session(
            decision_time=datetime(2025, 12, 1, 7, 30, tzinfo=UTC),  # 15:30 CST
            calendar=calendar(date(2025, 12, 1), date(2025, 12, 2)),
        )
        self.assertEqual(eligible, date(2025, 12, 2))

    def test_the_next_session_skips_a_holiday(self) -> None:
        """ExchangeCalendar.next_session already handles this.  Computing
        session + 1 day here would trade on a closed exchange, and a naive
        weekday check would trade through 国庆 and 春节 — the two longest closures
        of the year, which is where the largest gaps happen."""
        eligible = resolve_eligible_session(
            decision_time=datetime(2025, 9, 30, 7, 30, tzinfo=UTC),
            calendar=calendar_with_closure(
                open_days=(date(2025, 9, 30), date(2025, 10, 9)),
                closed_days=tuple(date(2025, 10, day) for day in range(1, 9)),
            ),
        )
        self.assertEqual(eligible, date(2025, 10, 9))

    def test_an_unknown_calendar_horizon_fails_closed(self) -> None:
        """ExchangeCalendar.next_session raises MarketDataUnavailable when no
        later session is known.  Extrapolating a session would invent a trading
        day, and every fill after it would be fiction."""
        with self.assertRaises(MarketDataUnavailable):
            resolve_eligible_session(
                decision_time=datetime(2025, 12, 31, 7, 30, tzinfo=UTC),
                calendar=calendar(date(2025, 12, 31)),
            )

    def test_a_pre_open_decision_still_waits_for_the_next_session(self) -> None:
        """ADR-0006 decision 4 says the entry reference is the next tradable
        session, without an intraday carve-out.  Letting a 09:00 decision trade
        the same morning would create two different rules for the same
        InvestmentView depending on the minute it was compiled."""
```

- [ ] **Step 2: 运行确认红测 → 实现 → 转绿**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_realistic_backtest_state_machine -v`
Expected: FAIL —— `domain.backtest` 不存在。

- [ ] **Step 3: 转移 2/3 —— eligibility 与 intent（红测先行）**

```python
class IntentTransitionTest(unittest.TestCase):
    def test_intent_quantity_is_the_difference_from_current_holding(self) -> None:
        """Target 250,000 shares against 100,000 held is a 150,000 buy, not a
        250,000 buy.  Rebuilding the whole position every rebalance would multiply
        turnover and cost by the holding period."""

    def test_no_intent_is_emitted_when_the_target_already_matches(self) -> None:
        """A zero-share intent is not an order; emitting one would put a row in
        the ledger that can never fill and can never be explained."""

    def test_a_target_with_a_violated_constraint_emits_no_intent(self) -> None:
        """Task 2 already refuses to build such a snapshot.  This asserts the
        engine does not accept one from another path."""

    def test_intents_are_ordered_deterministically(self) -> None:
        """Sells before buys within a session, then by security_id.  Order
        matters because cash from a sell funds a buy, and a dict-iteration order
        would make the same inputs produce different fills."""

    def test_sell_proceeds_are_not_available_to_buy_in_the_same_session(self) -> None:
        """A-share cash from a sale is usable for a same-day purchase but the
        share settlement is T+1; the money rule and the share rule are different
        and must be tested separately.  Whichever convention the rule set picks,
        it is explicit and hashed rather than emergent from the loop order."""
```

- [ ] **Step 4: 转移 4 —— fill / block（红测先行）**

```python
class SettlementTransitionTest(unittest.TestCase):
    def test_a_blocked_order_stays_in_the_ledger_with_zero_fill(self) -> None:
        """SPEC-034 acceptance: 被阻塞订单有原因且不会静默消失.  The prototype's
        ledger draws 计划数量 50,000 / 实际数量 0 / 状态 阻断 / 原因 停牌 — the row
        exists precisely because nothing filled."""
        _state, trades, _valuation = advance_session(...)
        blocked = [t for t in trades if t.status is FillStatus.BLOCKED]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].filled_shares, 0)
        self.assertEqual(blocked[0].block_reasons, (BlockReason.SUSPENDED,))
        self.assertIsNone(blocked[0].costs)

    def test_a_partial_fill_records_both_quantities_and_its_reason(self) -> None:
        """计划数量 30,000 / 实际数量 15,000 / 原因 参与率超限."""

    def test_a_blocked_order_never_moves_cash_or_inventory(self) -> None:
        """This is the assertion that catches the most damaging class of bug: a
        block that is reported in the ledger but still applied to the books, so
        the page shows an honest blocked row while the equity curve reflects a
        fill that never happened."""

    def test_costs_are_charged_on_the_filled_quantity_only(self) -> None:
        """A partial fill pays commission on 15,000 shares, not 30,000."""

    def test_multiple_block_reasons_are_all_retained(self) -> None:
        """A suspended, ST, sub-lot order has three reasons.  Keeping only the
        first makes the remaining two invisible for as long as the first persists."""
```

- [ ] **Step 5: 转移 5 —— inventory / cash（红测先行，含 T+1 跨 session）**

```python
class InventoryTransitionTest(unittest.TestCase):
    def test_todays_buy_settles_before_the_next_session(self) -> None:
        """The T+1 rule tested in Task 5 was a single-session predicate; this is
        the multi-session half: shares bought on 12-02 are unsettled that day and
        settled on 12-03.  Both halves can be individually right and jointly
        wrong, which is why they are two tests in two files."""
        after_first, _trades, _valuation = advance_session(..., session=date(2025, 12, 2))
        self.assertEqual(after_first.unsettled["security:CN:600519:XSHG"], 10_000)
        self.assertEqual(after_first.settled.get("security:CN:600519:XSHG", 0), 0)
        after_second, _t, _v = advance_session(after_first, session=date(2025, 12, 3), intents=())
        self.assertEqual(after_second.settled["security:CN:600519:XSHG"], 10_000)
        self.assertEqual(after_second.unsettled.get("security:CN:600519:XSHG", 0), 0)

    def test_settlement_advances_by_sessions_not_by_calendar_days(self) -> None:
        """A Friday purchase settles on Monday, not on Saturday.  Counting
        calendar days makes every weekend and every holiday produce a phantom
        settlement, and the phantom is sellable."""

    def test_cash_never_goes_negative(self) -> None:
        """A negative balance means an order filled without funding.  The engine
        must block the unfunded order at settlement rather than let the balance
        go negative and 'fix itself' when the next sale lands."""

    def test_inventory_is_never_negative(self) -> None:
        """A negative holding is a short position, and this is a long-only
        product with no borrow model."""

    def test_state_transitions_are_recorded_with_their_stage(self) -> None:
        """Each transition names its BacktestStage so a diff against an external
        engine can say which stage disagreed rather than only that the equity
        differs."""
```

- [ ] **Step 6: 转移 6 —— valuation（红测先行）**

```python
class ValuationTransitionTest(unittest.TestCase):
    def test_equity_is_position_value_plus_cash(self) -> None:
        """SPEC-034: benchmark、现金和公司行动必须进入 equity closure."""

    def test_a_missing_close_makes_the_valuation_unavailable_not_stale(self) -> None:
        """Carrying yesterday's close forward through a data gap produces a flat
        segment in the curve that looks like a calm market instead of a hole in
        the data.  The session reports the listing as unavailable with a reason."""

    def test_a_suspended_holding_is_valued_at_its_last_traded_close_with_a_flag(self) -> None:
        """Different from a data gap on purpose: a suspension is a real market
        fact and the holding really is worth its last print, but the valuation
        must say so, because a long suspension pins a growing share of equity to
        a stale price."""

    def test_benchmark_level_absent_marks_relative_metrics_unavailable(self) -> None:
        """Without a benchmark there is no active return and no tracking error.
        Reporting the absolute return as active return is the error this blocks."""
```

- [ ] **Step 7: 公司行动（独立测试文件，红测先行）**

ADR-0006 决策 5 原文：「分红、送转、拆股、配股和退市现金流通过 total-return
公司行动账本处理；**不得用无记录的前复权价格替代公司行动**。」

```python
# platform/tests/test_realistic_backtest_corporate_actions.py
"""Corporate actions as ledger events, not as adjusted prices.

ADR-0006 decision 5 forbids substituting an unrecorded forward-adjusted price for
a corporate action.  The reason is auditability: an adjusted price makes the cash
and the share change invisible, so the equity curve is right and nothing explains
why.  Here every action produces an explicit share change, an explicit cash flow,
or both.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from a_share_platform.domain.backtest import (
    RightsIssueChoice,
    apply_corporate_action,
    resolve_delisting_cash_flow,
)
from a_share_platform.domain.market_data import CorporateAction, CorporateActionType
from a_share_platform.domain.security_master import ListingState

LISTING = "listing:CN:600519:XSHG"
EX_DATE = date(2025, 12, 2)


def action(action_type: CorporateActionType, **overrides: object) -> CorporateAction:
    base: dict[str, object] = {
        "action_id": f"corporate-action:{LISTING}:2025-12-02",
        "listing_id": LISTING,
        "action_type": action_type,
        "ex_date": EX_DATE,
        "record_date": date(2025, 12, 1),
        "cash_per_share": None,
        "share_ratio": None,
        "subscription_price": None,
        "currency": "CNY",
        "source_id": "source:baostock",
    }
    base.update(overrides)
    return CorporateAction(**base)  # type: ignore[arg-type]


class ExRightsDateTest(unittest.TestCase):
    def test_cash_dividend_credits_cash_on_the_ex_date_not_the_record_date(self) -> None:
        """CorporateAction already enforces record_date <= ex_date.  A holder on
        the ex date receives the dividend; applying it on the record date shifts
        the cash by one or more sessions and the shift lands inside the return
        window whenever a rebalance is nearby."""
        # Hand computation: 10,000 shares × 0.50 per share = 5,000.00 cash.
        dividend = action(CorporateActionType.CASH_DIVIDEND, cash_per_share=Decimal("0.50"))
        effect = apply_corporate_action(
            action=dividend, held_shares=10_000, session=EX_DATE,
        )
        self.assertEqual(effect.cash_delta, Decimal("5000.00"))
        self.assertEqual(effect.share_delta, 0)
        self.assertIsNone(effect.reference_price_multiplier)
        self.assertFalse(effect.removes_holding)
        # record_date 那天什么都不发生 —— 现金不能提前一个 session 落账
        on_record = apply_corporate_action(
            action=dividend, held_shares=10_000, session=date(2025, 12, 1),
        )
        self.assertEqual(on_record.cash_delta, Decimal("0"))
        self.assertEqual(on_record.share_delta, 0)

    def test_the_price_drop_on_the_ex_date_is_not_a_loss(self) -> None:
        """Close 10.00 → 9.50 across a 0.50 dividend with 10,000 shares: position
        value falls 5,000 and cash rises 5,000, so equity is unchanged.  Without
        the ledger entry this reads as a 5% single-session loss."""
        shares = 10_000
        before_equity = Decimal("10.00") * shares          # 100,000.00
        effect = apply_corporate_action(
            action=action(CorporateActionType.CASH_DIVIDEND, cash_per_share=Decimal("0.50")),
            held_shares=shares, session=EX_DATE,
        )
        after_equity = Decimal("9.50") * (shares + effect.share_delta) + effect.cash_delta
        self.assertEqual(after_equity, before_equity)
        # 反证：不记账簿分录时，同一 session 会显示 -5%
        self.assertEqual(Decimal("9.50") * shares - before_equity, Decimal("-5000.00"))

    def test_bonus_shares_increase_the_count_without_cash(self) -> None:
        """10 送 3 on 10,000 shares is 13,000 shares and no cash.  The resulting
        odd lot must remain sellable — this is why Task 5's sell rule permits an
        odd lot."""
        effect = apply_corporate_action(
            action=action(CorporateActionType.BONUS_SHARE, share_ratio=Decimal("0.3")),
            held_shares=10_000, session=EX_DATE,
        )
        self.assertEqual(effect.share_delta, 3_000)
        self.assertEqual(effect.cash_delta, Decimal("0"))
        self.assertIsNone(effect.rights_issue_choice)

    def test_a_bonus_issue_can_create_a_non_round_lot(self) -> None:
        """1,050 shares with a 3-for-10 bonus is 1,365 shares.  Rounding it to
        1,300 silently confiscates 65 shares; rounding to 1,400 invents 35."""
        effect = apply_corporate_action(
            action=action(CorporateActionType.BONUS_SHARE, share_ratio=Decimal("0.3")),
            held_shares=1_050, session=EX_DATE,
        )
        self.assertEqual(effect.share_delta, 315)
        self.assertEqual(1_050 + effect.share_delta, 1_365)
        # 不得向整手取整 —— 两个方向都是编造
        self.assertNotEqual(1_050 + effect.share_delta, 1_300)
        self.assertNotEqual(1_050 + effect.share_delta, 1_400)

    def test_split_and_reverse_split_scale_shares_and_the_reference_price(self) -> None:
        """A 2-for-1 split doubles shares and halves the reference price, so the
        product is invariant.  Scaling only one side moves equity by the ratio,
        which is the largest single-session error a corporate action can cause."""
        split = apply_corporate_action(
            action=action(CorporateActionType.SPLIT, share_ratio=Decimal("2")),
            held_shares=1_000, session=EX_DATE,
        )
        self.assertEqual(split.share_delta, 1_000)
        self.assertEqual(split.reference_price_multiplier, Decimal("0.5"))
        self.assertEqual(split.cash_delta, Decimal("0"))
        self.assertEqual(
            (1_000 + split.share_delta) * Decimal("10.00") * split.reference_price_multiplier,
            1_000 * Decimal("10.00"),
        )
        reverse = apply_corporate_action(
            action=action(CorporateActionType.REVERSE_SPLIT, share_ratio=Decimal("2")),
            held_shares=1_000, session=EX_DATE,
        )
        self.assertEqual(reverse.share_delta, -500)
        self.assertEqual(reverse.reference_price_multiplier, Decimal("2"))
        self.assertEqual(
            (1_000 + reverse.share_delta) * Decimal("10.00")
            * reverse.reference_price_multiplier,
            1_000 * Decimal("10.00"),
        )

    def test_rights_issue_requires_a_funding_decision_and_is_not_auto_subscribed(self) -> None:
        """CorporateAction requires both share_ratio and subscription_price for a
        rights issue.  Auto-subscribing spends cash the policy never allocated;
        auto-declining forfeits value.  Neither may be implicit, so the policy
        must state it and the ledger must record which happened."""
        rights = action(
            CorporateActionType.RIGHTS_ISSUE,
            share_ratio=Decimal("0.3"), subscription_price=Decimal("8.00"),
        )
        # 未声明选择 → 拒绝，而不是默认认购或默认放弃
        with self.assertRaises(ValueError):
            apply_corporate_action(action=rights, held_shares=10_000, session=EX_DATE)

        subscribed = apply_corporate_action(
            action=rights, held_shares=10_000, session=EX_DATE,
            rights_issue_choice=RightsIssueChoice.SUBSCRIBE_IN_FULL,
            available_cash=Decimal("100000.00"),
        )
        self.assertEqual(subscribed.share_delta, 3_000)
        self.assertEqual(subscribed.cash_delta, Decimal("-24000.00"))  # 3,000 × 8.00
        self.assertIs(subscribed.rights_issue_choice, RightsIssueChoice.SUBSCRIBE_IN_FULL)

        declined = apply_corporate_action(
            action=rights, held_shares=10_000, session=EX_DATE,
            rights_issue_choice=RightsIssueChoice.DECLINE,
        )
        self.assertEqual(declined.share_delta, 0)
        self.assertEqual(declined.cash_delta, Decimal("0"))
        self.assertIs(declined.rights_issue_choice, RightsIssueChoice.DECLINE)

        # 现金不足时不得透支成交 —— 组合层没有融资模型
        with self.assertRaises(ValueError):
            apply_corporate_action(
                action=rights, held_shares=10_000, session=EX_DATE,
                rights_issue_choice=RightsIssueChoice.SUBSCRIBE_IN_FULL,
                available_cash=Decimal("1000.00"),
            )

    def test_bonus_shares_and_capitalisation_issues_stay_separate(self) -> None:
        """docs/14 requires them stored separately.  Merging them loses the tax
        and accounting distinction, which cannot be recovered afterwards."""
        # 现状（2026-08-16 核实）：CorporateActionType 只有五个成员，没有转增。
        # 本 Task **不改 domain/market_data.py**，因此这里断言的是"不得合并"，
        # 而不是"转增已支持"：转增到达时必须新增独立成员 + 独立 effect 分支，
        # 而不是复用 BONUS_SHARE。缺失的成员是 P2 数据层前置，不是本 Task 的产物。
        self.assertEqual(
            {member.value for member in CorporateActionType},
            {"cash_dividend", "bonus_share", "split", "reverse_split", "rights_issue"},
        )
        # effect 逐字携带来源 action_type，不做任何归并
        for action_type, kwargs in (
            (CorporateActionType.BONUS_SHARE, {"share_ratio": Decimal("0.3")}),
            (CorporateActionType.SPLIT, {"share_ratio": Decimal("2")}),
        ):
            effect = apply_corporate_action(
                action=action(action_type, **kwargs),  # type: ignore[arg-type]
                held_shares=10_000, session=EX_DATE,
            )
            self.assertIs(effect.action_type, action_type)
        # 未知/未映射的类型必须失败关闭，不得回落到 BONUS_SHARE 的分支
        with self.assertRaises(ValueError):
            apply_corporate_action(
                action=action(CorporateActionType.BONUS_SHARE, share_ratio=Decimal("0.3")),
                held_shares=10_000, session=EX_DATE,
                rights_issue_choice=RightsIssueChoice.SUBSCRIBE_IN_FULL,
            )  # 非配股却带配股选择 → 语义混用，拒绝

    def test_delisting_produces_a_cash_flow_and_removes_the_holding(self) -> None:
        """ListingState.TERMINATED forbids is_trading, so there is no session in
        which to sell.  Leaving the position in the book at its last price
        overstates equity for the rest of the run."""
        # 退市不是 CorporateActionType 的成员（五个成员里没有它），
        # 它由 ListingState.TERMINATED 驱动，所以走独立入口。
        flow = resolve_delisting_cash_flow(
            listing_id=LISTING, session=EX_DATE, held_shares=10_000,
            listing_state=ListingState.TERMINATED,
            final_cash_per_share=Decimal("3.20"),
        )
        self.assertEqual(flow.cash_delta, Decimal("32000.00"))
        self.assertEqual(flow.share_delta, -10_000)
        self.assertTrue(flow.removes_holding)

        # ACTIVE 的持仓不得被当作退市清算 —— 那会提前把持仓换成现金
        with self.assertRaises(ValueError):
            resolve_delisting_cash_flow(
                listing_id=LISTING, session=EX_DATE, held_shares=10_000,
                listing_state=ListingState.ACTIVE,
                final_cash_per_share=Decimal("3.20"),
            )

        # 清算价未知时：既不能按最后收盘价估值，也不能记为 0
        unknown = resolve_delisting_cash_flow(
            listing_id=LISTING, session=EX_DATE, held_shares=10_000,
            listing_state=ListingState.TERMINATED, final_cash_per_share=None,
        )
        self.assertIsNone(unknown.cash_delta)
        self.assertEqual(unknown.share_delta, -10_000)
        self.assertTrue(unknown.removes_holding)
        self.assertIsNotNone(unknown.unavailable_reason)

    def test_an_action_with_a_missing_ratio_or_price_fails_the_session(self) -> None:
        """An incomplete action cannot be applied and cannot be skipped: skipping
        it makes the next valuation wrong with no record of why."""
        # 一半的守卫已经在 CorporateAction.__post_init__ 里，构造期就拒绝
        with self.assertRaises(ValueError):
            action(CorporateActionType.CASH_DIVIDEND)                 # 缺 cash_per_share
        with self.assertRaises(ValueError):
            action(CorporateActionType.BONUS_SHARE)                   # 缺 share_ratio
        with self.assertRaises(ValueError):
            action(CorporateActionType.RIGHTS_ISSUE, share_ratio=Decimal("0.3"))
        # 另一半在应用期：负持仓或非整数持仓不是可入账的状态
        with self.assertRaises(ValueError):
            apply_corporate_action(
                action=action(CorporateActionType.BONUS_SHARE, share_ratio=Decimal("0.3")),
                held_shares=-100, session=EX_DATE,
            )

    def test_no_forward_adjusted_price_path_exists_in_the_engine(self) -> None:
        """ADR-0006 decision 5, asserted structurally.  PriceAdjustment only has
        UNADJUSTED today and DailyBar refuses anything else, so an adjusted price
        could only enter through a bespoke code path."""
        from pathlib import Path

        import a_share_platform.domain.backtest as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        for forbidden in ("forward_adjust", "pre_adjust", "adjustflag", "qfq"):
            self.assertNotIn(forbidden, source)
```

- [ ] **Step 8: 组合统计（红测先行）**

SPEC-035 清单：「累计/年化收益、Alpha/Beta、Sharpe/Sortino/Calmar、最大回撤、
TE/IR、换手、成本、容量、风险贡献、压力、bootstrap CI、PSR/DSR 和子期间」。

```python
# platform/tests/test_portfolio_statistics.py
"""Portfolio statistics with declared conventions.

Every one of these has more than one defensible definition — annualisation basis,
risk-free treatment, drawdown on total or on active return — so the convention is
a versioned input rather than a choice buried in the function.  Two runs that used
different conventions must not be comparable by accident.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from decimal import Decimal

from a_share_platform.domain.backtest import (
    StatisticsSpec,
    compute_portfolio_statistics,
)
from a_share_platform.domain.factor_statistics import StatisticStatus

START = date(2025, 1, 2)


def sessions(count: int) -> tuple[date, ...]:
    return tuple(START + timedelta(days=index) for index in range(count))


def equity(*values: str) -> tuple[tuple[date, Decimal], ...]:
    return tuple(zip(sessions(len(values)), (Decimal(v) for v in values), strict=True))


def zero_costs(length: int) -> tuple[tuple[date, Decimal], ...]:
    return tuple((day, Decimal("0")) for day in sessions(length))


def spec(**overrides: object) -> StatisticsSpec:
    base: dict[str, object] = {
        "spec_id": "portfolio-statistics:core",
        "annualization_sessions": 252,
        "minimum_sample_sessions": 60,
        "risk_free_annual_rate": Decimal("0.0150"),
        "bootstrap_resamples": 1_000,
        "bootstrap_seed": 20251202,
        "bootstrap_confidence_level": Decimal("0.95"),
        "trial_count": None,
        "preregistered_subperiods": (),
        "formula_version": "portfolio-statistics-v1",
    }
    base.update(overrides)
    return StatisticsSpec(**base)  # type: ignore[arg-type]


def long_equity(length: int = 120) -> tuple[tuple[date, Decimal], ...]:
    """A deterministic series that both rises and falls, so volatility and
    drawdown are non-zero without depending on a random generator."""
    values: list[Decimal] = [Decimal("1.00")]
    for index in range(1, length):
        step = Decimal("0.010") if index % 3 else Decimal("-0.008")
        values.append(values[-1] * (Decimal("1") + step))
    return tuple(zip(sessions(length), values, strict=True))


class ReturnStatisticsTest(unittest.TestCase):
    def test_cumulative_return_is_computed_from_the_equity_series(self) -> None:
        """Hand computation: 1.00 → 1.10 → 1.045 is +4.5% cumulative, which is
        not 10% - 5%.  Summing period returns instead of compounding them is the
        classic error and it is largest exactly when volatility is largest."""
        series = equity("1.00", "1.10", "1.045")
        statistics = compute_portfolio_statistics(
            equity_series=series, cost_series=zero_costs(3),
            benchmark_series=None, spec=spec(minimum_sample_sessions=2),
        )
        cumulative = statistics.statistic("cumulative_return")
        self.assertIs(cumulative.status, StatisticStatus.QUANTIFIED)
        self.assertEqual(cumulative.value, Decimal("0.045"))
        # 期间收益是 +10% 与 -5%，相加是 +5% —— 复利结果与它不同
        self.assertNotEqual(cumulative.value, Decimal("0.05"))

    def test_annualisation_basis_is_a_declared_input(self) -> None:
        """252 sessions is a convention, not a fact; a run using 250 must produce
        a different formula version and a different hash."""
        self.assertNotEqual(
            spec(annualization_sessions=252).content_hash,
            spec(annualization_sessions=250).content_hash,
        )
        series = long_equity()
        costs = zero_costs(len(series))
        under_252 = compute_portfolio_statistics(
            equity_series=series, cost_series=costs, benchmark_series=None,
            spec=spec(annualization_sessions=252),
        ).statistic("annualized_return")
        under_250 = compute_portfolio_statistics(
            equity_series=series, cost_series=costs, benchmark_series=None,
            spec=spec(annualization_sessions=250),
        ).statistic("annualized_return")
        self.assertIs(under_252.status, StatisticStatus.QUANTIFIED)
        self.assertIs(under_250.status, StatisticStatus.QUANTIFIED)
        self.assertNotEqual(under_252.value, under_250.value)
        # 没有声明基数的 spec 不可构造 —— 默认 252 就是把约定伪装成事实
        with self.assertRaises(ValueError):
            spec(annualization_sessions=0)

    def test_sharpe_reports_unavailable_below_the_minimum_sample(self) -> None:
        """A Sharpe from eleven sessions is a number and not an estimate."""
        short = long_equity(11)
        sharpe = compute_portfolio_statistics(
            equity_series=short, cost_series=zero_costs(11),
            benchmark_series=None, spec=spec(minimum_sample_sessions=60),
        ).statistic("sharpe_ratio")
        self.assertIs(sharpe.status, StatisticStatus.UNAVAILABLE)
        self.assertIsNone(sharpe.value)
        self.assertIsNotNone(sharpe.unavailable_reason)
        self.assertIn("60", sharpe.unavailable_reason)
        # 恰好达到门槛可得：边界是 >=
        enough = long_equity(61)
        self.assertIs(
            compute_portfolio_statistics(
                equity_series=enough, cost_series=zero_costs(61),
                benchmark_series=None, spec=spec(minimum_sample_sessions=60),
            ).statistic("sharpe_ratio").status,
            StatisticStatus.QUANTIFIED,
        )

    def test_sortino_uses_downside_deviation_not_total_deviation(self) -> None:
        """Upside volatility is not risk under this definition, so a series with
        large gains and small losses must rank higher on Sortino than on Sharpe.
        Reusing the total standard deviation makes Sortino a rescaled Sharpe and
        the whole distinction disappears."""
        series = long_equity()
        statistics = compute_portfolio_statistics(
            equity_series=series, cost_series=zero_costs(len(series)),
            benchmark_series=None, spec=spec(),
        )
        sharpe = statistics.statistic("sharpe_ratio")
        sortino = statistics.statistic("sortino_ratio")
        self.assertIs(sortino.status, StatisticStatus.QUANTIFIED)
        self.assertNotEqual(sortino.value, sharpe.value)
        # 该 fixture 的涨幅次数多于跌幅，下行离差小于总离差 → Sortino 更高
        self.assertGreater(sortino.value, sharpe.value)
        # 全程无下行时下行离差为 0，Sortino 无定义而不是无穷大
        monotonic = equity(*[f"{1 + index * 0.01:.4f}" for index in range(80)])
        no_downside = compute_portfolio_statistics(
            equity_series=monotonic, cost_series=zero_costs(80),
            benchmark_series=None, spec=spec(),
        ).statistic("sortino_ratio")
        self.assertIs(no_downside.status, StatisticStatus.UNAVAILABLE)
        self.assertIsNone(no_downside.value)

    def test_calmar_with_zero_drawdown_is_unavailable_not_infinite(self) -> None:
        """A strategy with no drawdown in-sample has an undefined Calmar, and
        printing infinity or a large number would rank it first."""
        monotonic = equity(*[f"{1 + index * 0.01:.4f}" for index in range(80)])
        calmar = compute_portfolio_statistics(
            equity_series=monotonic, cost_series=zero_costs(80),
            benchmark_series=None, spec=spec(),
        ).statistic("calmar_ratio")
        self.assertIs(calmar.status, StatisticStatus.UNAVAILABLE)
        self.assertIsNone(calmar.value)
        self.assertIsNotNone(calmar.unavailable_reason)

    def test_max_drawdown_is_measured_peak_to_trough_on_equity(self) -> None:
        """Hand computation: 100 → 120 → 90 → 130 is a 25% drawdown, from the 120
        peak, not 10% from the start."""
        series = equity("100", "120", "90", "130")
        drawdown = compute_portfolio_statistics(
            equity_series=series, cost_series=zero_costs(4),
            benchmark_series=None, spec=spec(minimum_sample_sessions=3),
        ).statistic("max_drawdown")
        self.assertIs(drawdown.status, StatisticStatus.QUANTIFIED)
        self.assertEqual(drawdown.value, Decimal("0.25"))
        self.assertNotEqual(drawdown.value, Decimal("0.10"))

    def test_tracking_error_and_information_ratio_need_the_benchmark(self) -> None:
        """Both unavailable without a benchmark series, rather than falling back
        to absolute volatility and absolute return under active names."""
        series = long_equity()
        without = compute_portfolio_statistics(
            equity_series=series, cost_series=zero_costs(len(series)),
            benchmark_series=None, spec=spec(),
        )
        for statistic_id in ("tracking_error", "information_ratio", "alpha", "beta"):
            with self.subTest(statistic_id=statistic_id):
                item = without.statistic(statistic_id)
                self.assertIs(item.status, StatisticStatus.UNAVAILABLE)
                self.assertIsNone(item.value)
                self.assertIsNotNone(item.unavailable_reason)
        # 绝对口径仍然可得 —— 缺基准不污染绝对统计
        self.assertIs(without.statistic("volatility").status, StatisticStatus.QUANTIFIED)
        # 且绝对波动率不得被当作 TE 复用
        self.assertIsNone(without.statistic("tracking_error").value)

        with_benchmark = compute_portfolio_statistics(
            equity_series=series, cost_series=zero_costs(len(series)),
            benchmark_series=long_equity(len(series)), spec=spec(),
        )
        self.assertIs(
            with_benchmark.statistic("tracking_error").status, StatisticStatus.QUANTIFIED,
        )

    def test_costs_are_reported_before_and_after(self) -> None:
        """SPEC-035 acceptance: 同时展示成本前/后与基准.  A single net number
        cannot answer whether the edge or the cost model dominates."""
        series = long_equity()
        costs = tuple((day, Decimal("0.0002")) for day, _ in series)
        statistics = compute_portfolio_statistics(
            equity_series=series, cost_series=costs,
            benchmark_series=long_equity(len(series)), spec=spec(),
        )
        gross = statistics.statistic("cumulative_return", basis="gross")
        net = statistics.statistic("cumulative_return", basis="net")
        self.assertIs(gross.status, StatisticStatus.QUANTIFIED)
        self.assertIs(net.status, StatisticStatus.QUANTIFIED)
        self.assertGreater(gross.value, net.value)
        # 三套口径同时存在，不允许只留一个 net 数字
        self.assertNotEqual(statistics.gross_of_cost, ())
        self.assertNotEqual(statistics.net_of_cost, ())
        self.assertNotEqual(statistics.benchmark, ())

    def test_bootstrap_confidence_interval_declares_its_resample_count_and_seed(self) -> None:
        """A CI that changes between runs is not a CI.  Both the count and the
        seed enter the formula version."""
        series = long_equity()
        costs = zero_costs(len(series))

        def ci(**overrides: object) -> tuple[Decimal | None, Decimal | None]:
            statistics = compute_portfolio_statistics(
                equity_series=series, cost_series=costs,
                benchmark_series=None, spec=spec(**overrides),
            )
            return (
                statistics.statistic("mean_return_ci_lower").value,
                statistics.statistic("mean_return_ci_upper").value,
            )

        self.assertEqual(ci(), ci())                       # 同 seed 逐位可复现
        self.assertNotEqual(ci(), ci(bootstrap_seed=1))    # 换 seed 必须换结果
        self.assertNotEqual(
            spec(bootstrap_resamples=1_000).content_hash,
            spec(bootstrap_resamples=2_000).content_hash,
        )
        self.assertNotEqual(
            spec(bootstrap_seed=20251202).content_hash, spec(bootstrap_seed=1).content_hash,
        )
        # resamples 低于下限时不得静默降级
        with self.assertRaises(ValueError):
            spec(bootstrap_resamples=99)

    def test_psr_and_dsr_require_the_trial_count(self) -> None:
        """A deflated Sharpe without the number of strategies tried is just a
        Sharpe wearing a different name — and the deflation is the entire point."""
        series = long_equity()
        costs = zero_costs(len(series))
        without = compute_portfolio_statistics(
            equity_series=series, cost_series=costs, benchmark_series=None,
            spec=spec(trial_count=None),
        )
        for statistic_id in ("probabilistic_sharpe_ratio", "deflated_sharpe_ratio"):
            with self.subTest(statistic_id=statistic_id):
                item = without.statistic(statistic_id)
                self.assertIs(item.status, StatisticStatus.UNAVAILABLE)
                self.assertIsNone(item.value)
                self.assertIsNotNone(item.unavailable_reason)

        with_trials = compute_portfolio_statistics(
            equity_series=series, cost_series=costs, benchmark_series=None,
            spec=spec(trial_count=37),
        )
        dsr = with_trials.statistic("deflated_sharpe_ratio")
        self.assertIs(dsr.status, StatisticStatus.QUANTIFIED)
        # 试验次数越多，deflation 越强 → DSR 必须严格下降
        more_trials = compute_portfolio_statistics(
            equity_series=series, cost_series=costs, benchmark_series=None,
            spec=spec(trial_count=370),
        ).statistic("deflated_sharpe_ratio")
        self.assertLess(more_trials.value, dsr.value)

    def test_subperiod_statistics_do_not_recompute_the_whole_period(self) -> None:
        """Pre-registered subperiods only.  Choosing them after seeing results is
        the selection bias PSR/DSR exist to correct."""
        series = long_equity()
        costs = zero_costs(len(series))
        days = tuple(day for day, _ in series)
        first, second = (days[0], days[59]), (days[60], days[-1])

        without = compute_portfolio_statistics(
            equity_series=series, cost_series=costs, benchmark_series=None,
            spec=spec(preregistered_subperiods=()),
        )
        self.assertEqual(without.subperiods, ())

        with_subperiods = compute_portfolio_statistics(
            equity_series=series, cost_series=costs, benchmark_series=None,
            spec=spec(preregistered_subperiods=(first, second),
                      minimum_sample_sessions=30),
        )
        self.assertEqual(
            tuple(window for window, _ in with_subperiods.subperiods), (first, second),
        )
        # 子期间进入 hash：事后追加一个窗口不能与预登记的运行同 hash
        self.assertNotEqual(
            spec(preregistered_subperiods=(first,)).content_hash,
            spec(preregistered_subperiods=(first, second)).content_hash,
        )
        # 未预登记的窗口无法查询 —— 没有事后挑窗口的入口
        with self.assertRaises(KeyError):
            next(
                values for window, values in with_subperiods.subperiods
                if window == (days[10], days[20])
            )
```

- [ ] **Step 9: core attribution（红测先行）—— 日度先行，再累计，再残差**

SPEC-039 原文的三条规则必须逐条成为测试：
「归因 schema 从第一版保留全部分项，但允许尚未参与某次策略的分项标记为 `not_applicable`；
只有策略明确没有该暴露时才可记为 0。模块尚未实现或证据缺失时应标记 `unavailable`，
不能用 0 掩盖。」以及「无法闭合时标记 failed，不发布"解释性"图表冒充闭合归因」。

```python
# platform/tests/test_core_attribution.py
"""Core attribution: daily first, then cumulative, then the residual gate.

Daily comes first because a cumulative decomposition that closes can still be
built from daily components that individually do not — the errors cancel.  A
cumulative-only test would pass on a wrong implementation.

SPEC-039 keeps every component in the schema from the first version and separates
three reasons a component can be non-numeric: not_applicable (the strategy did
not use it), unavailable (the module or the evidence is missing) and zero (the
strategy provably had no exposure).  Collapsing them loses the only information
that says whether a gap is a design decision or a defect.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from a_share_platform.domain.attribution import (
    AttributionComponent,
    AttributionComponentStatus,
    AttributionSnapshot,
    ClosureStatus,
    accumulate_attribution,
    attribute_session,
)


class DailyAttributionTest(unittest.TestCase):
    def test_daily_components_sum_to_the_daily_active_return(self) -> None:
        """Hand computation: market +0.0182, industry +0.0031, style -0.0012,
        selection +0.0048, cost -0.0018 sums to +0.0231 against a measured active
        return of +0.0231, leaving a zero residual."""

    def test_a_daily_residual_over_tolerance_fails_that_session(self) -> None:
        """SPEC-039 acceptance: 无法闭合时标记 failed，不发布"解释性"图表冒充闭合归因."""
        result = attribute_session(...)
        self.assertEqual(result.closure_status, ClosureStatus.FAILED)

    def test_the_failed_session_is_named_in_the_cumulative_result(self) -> None:
        """A single failing session must not be averaged away by 20 good ones."""

    def test_a_non_participant_is_not_zero_filled(self) -> None:
        """Timing is in Shadow, so ADR-0006 decision 7 fixes its portfolio impact
        at zero — but the component status is NOT_APPLICABLE, and the prototype's
        +0.15% Timing bar must never reach the runtime.  Zero and not-applicable
        both display as no contribution and mean different things: zero asserts
        the model ran and contributed nothing."""
        result = attribute_session(...)
        timing = result.component("timing")
        self.assertEqual(timing.status, AttributionComponentStatus.NOT_APPLICABLE)
        self.assertIsNone(timing.contribution)
        self.assertIsNotNone(timing.status_reason)

    def test_an_unimplemented_component_reads_unavailable(self) -> None:
        """Events attribution belongs to P8 and execution attribution needs a
        real OMS from P10.  The prototype draws Events as UNAVAILABLE already and
        Execution as +0.09%; the second one is a design illustration and the
        runtime must report unavailable."""
        result = attribute_session(...)
        for name in ("events", "execution"):
            self.assertEqual(
                result.component(name).status, AttributionComponentStatus.UNAVAILABLE,
            )

    def test_a_provable_zero_exposure_is_allowed_to_be_zero(self) -> None:
        """SPEC-039 permits zero only when 策略明确没有该暴露.  A long-only
        portfolio with no FX position has a provable zero FX contribution, and it
        carries the proof."""

    def test_every_schema_component_is_present_in_every_snapshot(self) -> None:
        """SPEC-039: 归因 schema 从第一版保留全部分项.  A component that
        disappears when it has nothing to say makes its absence indistinguishable
        from a bug in the projection."""
        result = attribute_session(...)
        for name in ("market", "industry", "style", "selection", "cost",
                     "timing", "events", "execution"):
            self.assertIsNotNone(result.component(name))


class CumulativeAttributionTest(unittest.TestCase):
    def test_cumulative_components_compound_rather_than_sum(self) -> None:
        """Daily contributions do not add across periods any more than returns
        do; the cross-product terms have to go somewhere and the interaction term
        must be named, not swept into selection."""

    def test_the_interaction_term_is_explicit(self) -> None:
        """An unnamed interaction term is the residual under another name, and
        naming it 'selection' credits the stock picker for arithmetic."""

    def test_cumulative_closure_is_checked_independently_of_daily_closure(self) -> None:
        """Daily sessions can each close while the cumulative does not, if the
        linking method is wrong.  Both gates are needed."""

    def test_core_only_scope_is_stated_on_the_snapshot(self) -> None:
        """SPEC-039: P6 的选股回测只能完成 core attribution；包含 Timing、事件和
        真实执行后的 unified attribution 才满足本 Spec 的完整验收.  The snapshot
        says core_only so no reader mistakes it for the full decomposition."""
        result = accumulate_attribution(...)
        self.assertEqual(result.scope, "core_only")
```

- [ ] **Step 10: 归因交叉验证（复用既有合同）**

新增 `cross_check_attribution_closure(...)` 到
`validation/statistical_crosscheck.py`，用 NumPy 独立重算分项和与残差。
**报告结构复用 `StatisticalCrossCheckReport`。**

- [ ] **Step 11: 全量验证并提交（分两个 commit）**

状态机与归因是两个独立可验证行为，分开提交。

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src

cd .. && git add platform/src/a_share_platform/domain/backtest.py \
  platform/tests/test_realistic_backtest_state_machine.py \
  platform/tests/test_realistic_backtest_corporate_actions.py
git commit -m "feat: add the realistic A-share backtest as an explicit six-stage state machine

session, eligibility, intent, fill/block, inventory/cash, valuation — each with
its own red test.  One end-to-end test that fails tells you the simulation is
wrong without telling you where, and these six stages fail for unrelated reasons:
a calendar gap, a settlement off-by-one and a corporate action all show up as 'the
equity curve is wrong'.

The T+1 rule is tested twice on purpose.  Task 5 asserted the single-session
predicate: today's purchase cannot be sold today.  Here the multi-session half is
asserted: it becomes settled on the next session, counted in sessions rather than
calendar days.  A Friday buy settling on Saturday produces a phantom holding that
is sellable on a day the exchange is closed, and both halves can be individually
correct while the pair is wrong.

A blocked order keeps its ledger row with a zero fill and moves neither cash nor
inventory.  A separate test asserts the second half, because the damaging version
of this bug reports the block honestly on the page while still applying the fill
to the books — the ledger and the curve then disagree, and the curve is the one
people quote.

Corporate actions are ledger events rather than adjusted prices, as ADR-0006
decision 5 requires.  A 0.50 dividend on 10,000 shares moves 5,000 from position
value into cash and leaves equity unchanged; without the entry the same event
reads as a 5% single-session loss.  A test asserts no forward-adjustment code path
exists at all, since an adjusted price would make both the cash and the share
change invisible and leave the curve right for unexplainable reasons."

git add platform/src/a_share_platform/domain/attribution.py \
  platform/src/a_share_platform/validation/statistical_crosscheck.py \
  platform/tests/test_core_attribution.py \
  platform/tests/test_portfolio_statistics.py
git commit -m "feat: add core attribution with daily closure before cumulative closure

Daily closure is checked first because a cumulative decomposition can close while
the daily components that built it do not — the errors cancel over twenty
sessions.  A cumulative-only test therefore passes on a wrong implementation, and
this is the ordering the whole file exists to enforce.

Three ways of having no contribution are kept distinct, as SPEC-039 requires.
Timing is not_applicable because it sits in Shadow and ADR-0006 fixes its
portfolio impact at zero; events and execution are unavailable because P8 and P10
have not been built.  A provable zero is allowed only with its proof.  All three
render as no contribution and mean different things, and zero is the one that
claims the model ran.

The prototype draws Timing at +0.15% and Execution at +0.09%.  Both are design
illustrations and neither may reach the runtime, so the tests assert the statuses
rather than the numbers.

The cumulative link names its interaction term.  Daily contributions do not add
across periods any more than returns do, and an unnamed cross-product is the
residual under a different label — usually folded into selection, which credits
the stock picker for arithmetic.

Statistics conventions are versioned inputs rather than buried choices: the
annualisation basis, the bootstrap resample count and seed, and the trial count
that makes a deflated Sharpe deflated.  Two runs under different conventions must
not be silently comparable."
```

---

### Task 8: ports、memory adapter、application 编排与 worker

第一次出现 I/O。前七个 Task 的数学全部可测且已绿，因此这里的失败一定是编排问题 ——
这正是分层的收益。

**Files:**
- Create: `platform/src/a_share_platform/ports/backtests.py`
- Create: `platform/src/a_share_platform/adapters/memory/portfolios.py`
- Create: `platform/src/a_share_platform/application/portfolio_construction.py`
- Create: `platform/src/a_share_platform/application/backtests.py`
- Create: `platform/src/a_share_platform/workers/portfolio_backtest.py`
- Create: `platform/src/a_share_platform/adapters/<engine>/` **仅当 Task 6 的 verdict 允许**
- Create: `platform/tests/_builders.py`
  （把 Task 2 / 3 / 7 测试里已绿的 `policy()` / `signal()` / `target()` / `run()`
  builder 抽到一处共享；**只搬运，不改语义**，也不新增默认值）
- Test: `platform/tests/test_portfolio_application.py`
- Test: `platform/tests/test_portfolio_backtest_worker.py`
- Test: `platform/tests/test_dual_engine_reconciliation.py` **仅当引擎已资格化**

**Interfaces:**
- Consumes: Task 2–7 全部、`ports/signals.py` 的 `SignalSnapshotRepository`、
  `adapters/parquet/market_data.py` 的 `ParquetMarketDataStore`
- Produces:
  ```python
  class BacktestStoreUnavailable(RuntimeError): ...
  class PortfolioLedgerConflict(RuntimeError): ...

  class BacktestRunStatus(StrEnum):
      SUCCEEDED = "succeeded"
      FAILED = "failed"

  @dataclass(frozen=True)
  class BacktestRun:
      run_id: str
      spec: BacktestRunSpec
      status: BacktestRunStatus
      statistics: PortfolioStatistics | None    # FAILED 时为 None，不得填零统计
      failure_reason: str | None                # FAILED 时必填
      created_at: datetime
      content_hash: str = field(init=False)

  class BacktestRunRepository(Protocol):
      def append_run(self, value: BacktestRun) -> BacktestRun: ...
      def get_run(self, run_id: str) -> BacktestRun | None: ...
      def list_runs(self) -> tuple[BacktestRun, ...]: ...

  class TradeLedgerRepository(Protocol):
      def append_trades(self, run_id: str, values: Sequence[TradeRecord]) -> int: ...
      def list_trades(self, run_id: str) -> tuple[TradeRecord, ...]: ...

  class TargetPortfolioRepository(Protocol):
      def append_target(self, value: TargetPortfolioSnapshot) -> TargetPortfolioSnapshot: ...
      def get_target(self, target_id: str) -> TargetPortfolioSnapshot | None: ...
      def list_targets(self) -> tuple[TargetPortfolioSnapshot, ...]: ...

  # application/portfolio_construction.py
  def build_target_portfolio(*, signals: Sequence[SignalSnapshot],
      policy: PortfolioPolicy, requested_scope: ApprovalScope,
      run_context: RunContext, ...) -> TargetPortfolioSnapshot
  ```

- [ ] **Step 1: 读既有 port / memory adapter / worker 的真实模式**

```bash
cd platform
sed -n 1,25p src/a_share_platform/ports/experiments.py
sed -n 1,60p src/a_share_platform/adapters/memory/signals.py
grep -n "add_argument\|--execute\|--private-local-research-ack\|blockers\|return 2" \
  src/a_share_platform/workers/timing_baseline.py | head -30
```

**照抄这三个模式，不要自创。** `adapters/memory/signals.py` 的
`InMemorySignalSnapshotRepository` 有一句关键注释：
"Append-only adapter intended for contract tests, never runtime fixtures" ——
新 adapter 必须继承同样的意图，并用同样的 `_natural_key` 幂等/冲突模式。

- [ ] **Step 2: 写失败测试 —— append-only 与幂等**

```python
# platform/tests/test_portfolio_application.py
"""Application orchestration for targets, risk and backtest runs.

The maths is already green under tests/test_portfolio_*.py, so a failure here is
an orchestration failure: a missing binding, a repeated write, or a target built
from a signal whose approval scope does not match.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal

from a_share_platform.adapters.memory.portfolios import (
    InMemoryBacktestRunRepository,
    InMemoryTargetPortfolioRepository,
    UnavailableBacktestRunRepository,
)
from a_share_platform.application.portfolio_construction import build_target_portfolio
from a_share_platform.domain.backtest import BacktestRunStatus
from a_share_platform.domain.factor_lifecycle import ApprovalScope
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.ports.backtests import (
    BacktestStoreUnavailable,
    PortfolioLedgerConflict,
)

# target() / policy() / signal() / run() 复用 tests/test_portfolio_policy.py 与
# tests/test_portfolio_construction.py 里已绿的同名 builder，经 tests/_builders.py 共享。
from tests._builders import policy, run, signal, target


class AppendOnlyTest(unittest.TestCase):
    def test_rewriting_the_same_target_id_with_different_content_conflicts(self) -> None:
        """same ID / different semantics must fail closed, exactly as
        InMemorySignalSnapshotRepository already does for snapshots."""
        repository = InMemoryTargetPortfolioRepository()
        first = target()
        repository.append_target(first)
        mutated = target(cash_weight=Decimal("0.80"), positions=(
            replace(first.positions[0], target_weight=Decimal("0.20"),
                    weight_change=Decimal("0.20")),
        ))
        self.assertEqual(mutated.target_id, first.target_id)
        self.assertNotEqual(mutated.content_hash, first.content_hash)
        with self.assertRaises(PortfolioLedgerConflict):
            repository.append_target(mutated)
        # 冲突不得留下半写状态：原记录逐位不变
        self.assertEqual(repository.get_target(first.target_id).content_hash,
                         first.content_hash)
        self.assertEqual(len(repository.list_targets()), 1)

    def test_rewriting_the_identical_target_is_idempotent(self) -> None:
        """A retried write of the same content is a retry, not a second target.
        Raising here would make every worker restart a failure."""
        repository = InMemoryTargetPortfolioRepository()
        stored = repository.append_target(target())
        again = repository.append_target(target())
        self.assertEqual(again.content_hash, stored.content_hash)
        self.assertEqual(len(repository.list_targets()), 1)
        # natural key（policy_hash + eligible_session + signal ids）相同但 target_id
        # 不同，仍然是冲突：换一个 id 不能绕过不可变性
        with self.assertRaises(PortfolioLedgerConflict):
            repository.append_target(target(target_id="target-portfolio:core:retry"))

    def test_a_failed_backtest_run_cannot_be_rewritten_as_successful(self) -> None:
        """A failed run is evidence.  Overwriting it removes the only record that
        the configuration produced a failure, and the next run looks like a first
        attempt."""
        repository = InMemoryBacktestRunRepository()
        failed = run(status=BacktestRunStatus.FAILED,
                     statistics=None,
                     failure_reason="no qualified signal snapshot for 2025-12-01")
        repository.append_run(failed)
        with self.assertRaises(PortfolioLedgerConflict):
            repository.append_run(run(status=BacktestRunStatus.SUCCEEDED))
        stored = repository.get_run(failed.run_id)
        self.assertIs(stored.status, BacktestRunStatus.FAILED)
        self.assertIsNotNone(stored.failure_reason)
        # 失败的 run 不得携带统计 —— 零统计会被读成"跑完了但很差"
        self.assertIsNone(stored.statistics)
        self.assertEqual(len(repository.list_runs()), 1)

    def test_unavailable_repository_raises_rather_than_returning_empty(self) -> None:
        """An empty list from a missing store reads as 'no runs yet', which is a
        different fact from 'the store is not configured'."""
        with self.assertRaises(BacktestStoreUnavailable):
            UnavailableBacktestRunRepository().list_runs()


class ApprovalScopeTest(unittest.TestCase):
    def test_a_signal_approved_only_for_research_cannot_build_a_paper_target(self) -> None:
        """SPEC-030: purposes do not imply one another.  This is the single check
        that keeps a research artefact out of an execution path."""
        research_signal = signal(approval_scope=ApprovalScope.RESEARCH_BACKTEST)
        for requested in (ApprovalScope.PAPER, ApprovalScope.LIMITED_LIVE,
                          ApprovalScope.SHADOW):
            with self.subTest(requested=requested), self.assertRaises(ValueError):
                build_target_portfolio(
                    signals=(research_signal,),
                    policy=policy(approval_scope=requested),
                    requested_scope=requested,
                    run_context=RunContext(DataMode.CURRENT_RESEARCH,
                                           DeploymentStage.RESEARCH),
                )
        # 同 scope 才允许
        built = build_target_portfolio(
            signals=(research_signal,),
            policy=policy(approval_scope=ApprovalScope.RESEARCH_BACKTEST),
            requested_scope=ApprovalScope.RESEARCH_BACKTEST,
            run_context=RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.RESEARCH),
        )
        self.assertEqual(built.signal_snapshot_ids, (research_signal.snapshot_id,))

    def test_a_shadow_timing_forecast_never_enters_target_weights(self) -> None:
        """SPEC-030 and ADR-0006 decision 7: Shadow impact is fixed at zero.
        Asserted structurally as well — the construction module does not import
        the timing domain at all."""
        from pathlib import Path

        import a_share_platform.application.portfolio_construction as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("timing", source.lower())

    def test_strict_historical_construction_is_refused(self) -> None:
        """There are no pit_verified inputs today, so a strict target would be
        plausible and wrong."""
        strict = RunContext(DataMode.STRICT_HISTORICAL, DeploymentStage.RESEARCH)
        with self.assertRaises(ValueError) as raised:
            build_target_portfolio(
                signals=(signal(),),
                policy=policy(),
                requested_scope=ApprovalScope.RESEARCH_BACKTEST,
                run_context=strict,
            )
        # 原因必须指向 PIT 输入缺失，而不是一句泛化的 invalid input
        self.assertIn("pit_verified", str(raised.exception))
```

- [ ] **Step 3: 运行确认红测 → 实现 → 转绿**

- [ ] **Step 4: application 编排（无数学）**

`application/portfolio_construction.py` 的职责边界，逐条：

```text
读 SignalSnapshotRepository → 过滤 approval_scope 与 universe_version
读 ParquetMarketDataStore   → 取参考价与前一 session 状态
读 SecurityMaster           → 取行业归属（缺失则传 None，让约束报 UNAVAILABLE）
调 construct_target_portfolio()  ← 唯一的数学调用
调 risk_models 的编排           ← 产出 RiskModelDecisionRecord
写 TargetPortfolioRepository（append-only）
```

**这个文件里不得出现任何算术运算。** 一旦出现，就有了第二个权重真源。

- [ ] **Step 5: worker（红测先行）**

```python
# platform/tests/test_portfolio_backtest_worker.py
"""The portfolio backtest worker: dry-run by default, ack-gated writes.

Copied from the timing_baseline worker's contract rather than reinvented, so an
operator who knows one knows both.
"""

class DryRunDefaultTest(unittest.TestCase):
    def test_without_execute_nothing_is_written(self) -> None:
        code = portfolio_backtest.main([
            "--policy", "portfolio-policy:core-selection",
            "--start", "2024-01-01", "--end", "2024-12-31",
        ])
        self.assertEqual(code, 0)

    def test_execute_without_ack_is_blocked_with_a_reason(self) -> None:
        code = portfolio_backtest.main([
            "--policy", "portfolio-policy:core-selection",
            "--start", "2024-01-01", "--end", "2024-12-31", "--execute",
        ])
        self.assertEqual(code, 2)

    def test_the_dry_run_plan_states_the_backtest_kind(self) -> None:
        """SPEC-033: 页面和 API 不允许统一叫"回测"而不显示类型.  The plan says
        stock_selection_backtest, so the operator knows what is about to run."""

    def test_zero_qualified_signals_reports_a_blocker_and_exits_zero(self) -> None:
        """Today's real state.  An empty universe is not an error; producing an
        empty run with a stated reason is the correct output."""

    def test_a_negative_result_is_recorded_not_retried(self) -> None:
        """The failure mode this guards is re-running with a different window
        until the curve looks better."""

    def test_the_run_hash_covers_every_costed_input(self) -> None:
        """ADR-0006 decision 6, at the worker boundary: two runs differing only in
        the slippage rate must produce different run ids."""
```

- [ ] **Step 6: 双引擎 reconciliation（**仅当 Task 6 verdict 允许**）**

若 Task 6 的 verdict 是 `qualified` 或 `qualified_with_known_deviations`：

```python
# platform/tests/test_dual_engine_reconciliation.py
"""Compare the internal engine against the qualified external engine.

Both consume the identical frozen signal/target/policy export.  A comparison of
two engines fed different inputs measures the export, not the engines.
"""

class ReconciliationTest(unittest.TestCase):
    def test_both_engines_consume_the_same_frozen_export(self) -> None:
        """Asserted by hashing the export and requiring both runs to record it."""

    def test_each_trade_difference_is_classified(self) -> None:
        """Spec acceptance: 双引擎差异逐笔分类.  Categories at minimum:
        rule_convention (the engines model a rule differently — recorded in
        ADR-0013), data_difference, rounding, and unexplained."""

    def test_an_unexplained_difference_beyond_tolerance_blocks_the_gate(self) -> None:
        """Spec: 超过容差阻断 Gate.  Unexplained is the only category that blocks;
        a documented convention difference does not, because it was qualified."""

    def test_a_block_reported_internally_and_absent_externally_is_a_difference(self) -> None:
        """An engine that silently drops blocked orders would otherwise look like
        perfect agreement on the orders it did report."""

    def test_the_internal_engine_is_never_compared_against_itself(self) -> None:
        """Two runs of one engine agreeing is not a reconciliation, and it is the
        easiest way to produce a green panel that means nothing."""
```

若 verdict 是 `not_qualified` / `cannot_evaluate`：**跳过本 Step**，
并在 Evidence 明确记录 SPEC-034 的 SHOULD 项未满足。

- [ ] **Step 7: 真实小样本运行（需 P-2 完成）**

```bash
cd platform && source /tmp/asp_env.sh
# dry-run first: the plan must state the kind, the window, the policy hash and
# the number of qualified snapshots it found.
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.portfolio_backtest \
  --policy portfolio-policy:core-selection \
  --start 2024-01-01 --end 2024-12-31 \
  --universe-version <真实 id>
```

然后真实执行：

```bash
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.portfolio_backtest \
  --policy portfolio-policy:core-selection \
  --start 2024-01-01 --end 2024-12-31 \
  --universe-version <真实 id> \
  --private-local-research-ack --execute
```

**把真实输出原样记进 Evidence，无论结果如何。** 包括：
成交笔数、阻断笔数与各阻断原因计数、公司行动事件数、
真实 equity curve 起止值、最大回撤、换手、成本、闭合残差。
**曲线难看不是失败；闭合失败或阻断丢失才是失败。**

- [ ] **Step 8: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/ports/backtests.py \
  platform/src/a_share_platform/adapters/memory/portfolios.py \
  platform/src/a_share_platform/application/portfolio_construction.py \
  platform/src/a_share_platform/application/backtests.py \
  platform/src/a_share_platform/workers/portfolio_backtest.py \
  platform/tests/test_portfolio_application.py \
  platform/tests/test_portfolio_backtest_worker.py
git commit -m "feat: orchestrate portfolio construction and backtest runs behind ports

The maths went green in the previous tasks with no I/O at all, so a red test here
can only be an orchestration fault: a missing binding, a repeated write, or a
signal used outside its approval scope.  That separation is the whole reason the
domain came first.

application/portfolio_construction.py contains no arithmetic.  A single weight
computed here would be a second source of truth for a governed number, and a test
asserts the module does not import the timing domain either — SPEC-030 and
ADR-0006 decision 7 fix Shadow timing's portfolio impact at zero, and the
cheapest way to guarantee that is to make the dependency impossible.

An unavailable repository raises instead of returning an empty tuple.  'No runs
yet' and 'the store is not configured' would otherwise render identically on the
page, and only one of them is a reason to go configure something.

A failed run cannot be rewritten as successful.  The failure is the evidence that
this configuration produced one, and without it the next attempt looks like a
first attempt."
```

---

### Task 9: migration、PostgreSQL repository 与只读 API

冻结 Plan 的 Task 7：「预计 migration `003x_p6_portfolio_backtest.sql`，表进入 `research`，
serving 只读 projection；append-only run/target/trade/risk/attribution；API schema 和 OpenAPI 生成。」

**Files:**
- Create: `platform/migrations/0037_p6_portfolio_backtest.sql`
  （**执行前先 `ls platform/migrations/` 确认真实最大编号**；当前最大是 `0036`）
- Create: `platform/src/a_share_platform/adapters/postgres/portfolios.py`
- Modify: `platform/src/a_share_platform/api/app.py`
- Modify: `platform/src/a_share_platform/api/schemas.py`
- Modify: `platform/tests/test_migrations.py`（迁移清单 + 新的约束断言）
- Test: `platform/tests/test_postgres_portfolios.py`
- Test: `platform/tests/test_portfolio_api.py`

**Interfaces:**
- Produces: `GET /api/portfolios/policies|targets|backtests|risk|attribution`（只读）
  + `GET /api/portfolios/backtests/{run_id}/trades`（逐笔钻取）

- [ ] **Step 1: 读现有分层与 append-only 的真实约束写法**

```bash
cd platform
sed -n 1,60p migrations/0030_p5_investment_signal_ledgers.sql
sed -n 1,30p migrations/0035_outcome_source_policy.sql
grep -n "def test_p5_ledgers_are_layered_append_only_and_api_isolated" -A24 tests/test_migrations.py
grep -n "def test_platform_migrations_are_versioned_in_order" -A45 tests/test_migrations.py | tail -12
```

`0030` 已经示范了本 Task 要复制的三种约束：
`content_hash ~ '^[0-9a-f]{64}$'`、
`CHECK (data_mode <> 'strict_historical' OR trust_state = 'pit_verified')`、
`CHECK (data_cutoff <= decision_time)`。**照抄这套写法。**

- [ ] **Step 2: 写迁移测试（红测先行）**

```python
# 追加到 platform/tests/test_migrations.py
def test_p6_portfolio_tables_are_append_only_and_close_their_weights(self) -> None:
    """The database enforces what the domain enforces, because a repository bug
    must not be able to persist an object the domain would have refused."""
    sql = (PLATFORM_ROOT / "migrations" / "0037_p6_portfolio_backtest.sql").read_text(
        encoding="utf-8",
    )
    # Layering: research, never serving and never public.
    self.assertIn("CREATE TABLE research.target_portfolio_snapshots", sql)
    self.assertIn("CREATE TABLE research.backtest_runs", sql)
    self.assertIn("CREATE TABLE research.backtest_trades", sql)
    self.assertIn("CREATE TABLE research.risk_model_decisions", sql)
    self.assertIn("CREATE TABLE research.attribution_snapshots", sql)
    self.assertNotIn("CREATE TABLE serving.", sql)
    self.assertNotIn("CREATE TABLE public.", sql)
    # The backtest kind is never a free-text 'backtest' (SPEC-033).
    self.assertIn("stock_selection_backtest", sql)
    self.assertIn("execution_simulation", sql)
    # A blocked trade keeps its row: zero fill requires a reason.
    self.assertIn("filled_shares = 0", sql)
    self.assertIn("block_reasons", sql)
    # Hash discipline, copied from 0030.
    self.assertIn("content_hash ~ '^[0-9a-f]{64}$'", sql)
    # Strict mode cannot be persisted with current-only trust.
    self.assertIn("data_mode <> 'strict_historical' OR trust_state = 'pit_verified'", sql)

def test_p6_attribution_closure_status_is_constrained(self) -> None:
    """A residual over tolerance must be storable only as failed.  If the column
    accepted any status the domain gate could be bypassed by a repository that
    writes the wrong one."""

def test_p6_trade_ledger_forbids_a_fill_without_a_price(self) -> None:
    """A filled trade with a null price would produce a null-valued position
    that silently drops out of the equity sum."""

def test_p6_migration_does_not_alter_any_p5_table(self) -> None:
    """P5 ledgers are frozen evidence; a P6 migration that touches them would
    rewrite history to fit a later design."""
    sql = ...
    for frozen in ("research.investment_views", "research.signal_snapshots",
                   "research.investment_view_outcomes"):
        self.assertNotIn(f"ALTER TABLE {frozen}", sql)
```

同时更新 `test_platform_migrations_are_versioned_in_order` 的元组，
**追加**（不改动既有 36 项）。

- [ ] **Step 3: 运行确认红测 → 写 migration → 转绿**

- [ ] **Step 4: 空库与幂等 smoke（真实库）**

```bash
cd platform
source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m a_share_platform.adapters.postgres.cli
# 再跑一次，确认幂等
PYTHONPATH=src .venv/bin/python -m a_share_platform.adapters.postgres.cli
.venv/bin/python - <<'PY'
import os, psycopg
with psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True) as c:
    rows = c.execute("""
        select table_schema, table_name from information_schema.tables
        where table_name like '%portfolio%' or table_name like '%backtest%'
           or table_name like '%attribution%' or table_name like '%risk_model%'
        order by 1, 2
    """).fetchall()
    for row in rows:
        print(row)
PY
```

Expected: 五张表全部在 `research`；第二次 migration 无错误、无重复。

- [ ] **Step 5: PostgreSQL repository（红测先行）**

照 `adapters/postgres/signals.py` 的模式。至少覆盖：
往返保真（Decimal 不退化为 float）、幂等重写、冲突关闭、
`unavailable` 分项往返后仍是 `None` 而非 `0`。

```python
# platform/tests/test_postgres_portfolios.py
class RoundTripTest(unittest.TestCase):
    def test_decimal_weights_survive_the_round_trip_exactly(self) -> None:
        """A weight that comes back as 0.24999999999999998 breaks closure by an
        amount that grows with the position count."""

    def test_an_unavailable_component_returns_none_not_zero(self) -> None:
        """The single most important round-trip property in this plan: the
        database is where an explicit unknown most easily becomes a zero."""

    def test_block_reasons_survive_as_an_ordered_tuple(self) -> None:
        """Three reasons stored and three read back, in the same order."""
```

- [ ] **Step 6: 只读 API（红测先行）**

照 `api/app.py` 已有的 `envelope(...)` + `fixed_read_context` 模式：

```python
# platform/tests/test_portfolio_api.py
"""Read-only portfolio endpoints.

SPEC-048 requires each tab to have all six states, and the API is where four of
them originate: ready, partial, empty and unavailable.  loading and error belong
to the client.
"""

class PortfolioEndpointTest(unittest.TestCase):
    def test_targets_endpoint_returns_an_empty_list_when_none_exist(self) -> None:
        """Empty is 200 with an empty collection, not 404: the capability exists."""

    def test_targets_endpoint_returns_503_when_the_store_is_unconfigured(self) -> None:
        """Unavailable is a different HTTP outcome from empty, because they are
        different facts and the page renders them differently."""

    def test_backtest_response_states_its_kind(self) -> None:
        """SPEC-033: the API may not return a generic 'backtest'."""

    def test_trades_endpoint_includes_blocked_orders(self) -> None:
        """A trades endpoint that filters to fills makes the blocked rows
        unreachable from the page that is supposed to show them."""

    def test_no_write_endpoint_is_registered_for_portfolios(self) -> None:
        """Construction runs belong to a worker with an ack.  A POST here would
        be an execution path reachable from a browser."""
        routes = [(r.path, tuple(r.methods)) for r in app.routes]
        for path, methods in routes:
            if path.startswith("/api/portfolios"):
                self.assertEqual(set(methods) - {"HEAD", "OPTIONS"}, {"GET"})

    def test_envelope_carries_the_run_context_and_dataset_versions(self) -> None:
        """SPEC-050: trust, versions and evidence travel with the number."""
```

- [ ] **Step 7: 生成 OpenAPI 与前端类型**

```bash
cd platform
.venv/bin/python scripts/export_openapi.py
cd frontend && PYTHON_BIN=../.venv/bin/python npm run generate:api
git diff --stat src/api/openapi.json src/api/schema.d.ts
```

- [ ] **Step 8: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
npm --prefix frontend run lint && npm --prefix frontend run build
cd .. && git add platform/migrations/0037_p6_portfolio_backtest.sql \
  platform/src/a_share_platform/adapters/postgres/portfolios.py \
  platform/src/a_share_platform/api/app.py \
  platform/src/a_share_platform/api/schemas.py \
  platform/tests/test_migrations.py \
  platform/tests/test_postgres_portfolios.py \
  platform/tests/test_portfolio_api.py \
  platform/frontend/src/api/openapi.json platform/frontend/src/api/schema.d.ts
git commit -m "feat: persist and expose P6 portfolio artefacts as append-only research tables

The database re-states what the domain already enforces, because a repository bug
must not be able to persist an object the domain would have refused: a blocked
trade with a non-zero fill, a filled trade with a null price, an attribution
snapshot whose residual exceeds tolerance but whose status says closed.

The round-trip test that matters most asserts an unavailable component comes back
as null rather than zero.  A database column is the easiest place in the whole
stack for an explicit unknown to become a number, and once it is a number nothing
downstream can tell it was ever unknown.

Every portfolio endpoint is GET.  A construction run is a worker with an
acknowledgement flag, and a POST here would put an execution path one fetch away
from a browser.  Empty returns 200 with an empty collection while an unconfigured
store returns 503, because 'nothing has been built yet' and 'this capability is
not wired up' lead to different actions.

The migration touches no P5 table.  Those ledgers are frozen evidence, and
altering them from a later phase would be rewriting history to fit a newer
design."
```

---

### Task 10: `PortfolioWorkspace` 壳与 Construction 页（node `7:303`）

PUI-05 的第一页。**复用 `DeskSection`，不建第二套分区组件。**

**Files:**
- Create: `platform/frontend/src/pages/PortfolioWorkspace.tsx`
- Create: `platform/frontend/src/pages/PortfolioWorkspace.test.tsx`
- Create: `platform/frontend/src/features/portfolio/portfolioProjection.ts`
- Create: `platform/frontend/src/features/portfolio/ConstructionPanel.tsx`
- Create: `platform/frontend/src/features/portfolio/ConstructionPanel.test.tsx`
- Create: `platform/frontend/src/features/portfolio/portfolio.less`
- Modify: `platform/frontend/src/app/AppShell.tsx`（第 185 行路由）
- Modify: `platform/frontend/src/app/shell.less`（网格容器，见下）
- Create: `platform/scripts/verify_portfolio_browser.py`

**Interfaces:**
- Consumes: Task 9 的 `GET /api/portfolios/policies|targets`、
  `features/desk/DeskSection.tsx`、`features/desk/deskState.ts`、`components/NumericCell.tsx`
- Produces: `/portfolios?tab=construction` 显示真实政策与真实 blocker

- [ ] **Step 1: 提取 node `7:303` 的真实结构与文案**

```bash
cd docs/assets/prototype && python3 - <<'PY'
import json, re, html
d = json.load(open("figma-node-summary.json"))
frame = d["frames"]["7:303"]
print(frame["name"], frame["summary"]["w"], frame["summary"]["h"])

def walk(node, depth=0):
    if node.get("type") == "TEXT":
        return
    print("  " * depth, node.get("name"), node.get("w"), node.get("h"),
          node.get("layout"), node.get("gap"), node.get("children_count", ""))
    for child in node.get("children", []):
        walk(child, depth + 1)
walk(frame["summary"])

s = open("portfolios-construction.svg", encoding="utf-8").read()
texts = [html.unescape(re.sub("<[^>]+>", "", m))
         for m in re.findall(r"<text[^>]*>(.*?)</text>", s, re.S)]
for t in (t.strip() for t in texts):
    if t:
        print("|", t)
PY
```

Expected（2026-08-16 实测）：1440 × 1200；`viewport-wrap` → `sidebar` 248 + `main-content` 1192；
`workspace` 1192 × 945 gap 20，含 `strategy-config-card` 1144 × 171、
`columns-wrapper` 1144 × 630、`bottom-action-bar` 1144 × 56；217 条文案。

**summary 在第 4 层截断为 `children_count`，且没有 `layoutMode`/`itemSpacing`** ——
列宽与列名只能从 SVG 文案与坐标推断，这一点必须写进 Evidence 的设计假设，
不能声称"逐节点 parity"。

- [ ] **Step 2: 先修网格容器（避免带着已知溢出做验收）**

P-4 plan Task 1 已经诊断出 `shell.less` 的隐式网格列问题：
`display: grid` 而不声明 `grid-template-columns` 时隐式列是 max-content，
被 AntD Tabs 的 min-content 撑开。`.deskGrid` 用 `minmax(0, …fr)` 所以不受影响。

新增的 `.portfolioWorkspace` **必须一开始就声明 `minmax(0, 1fr)`**，
并加进 P-4 建立的 `layoutGrid.test.ts` 不变量清单：

```ts
// 追加到 platform/frontend/src/app/layoutGrid.test.ts 的 it.each 列表
'.portfolioWorkspace,',
```

若 P-4 尚未执行，则在本 Task 内新建该测试文件（同样的实现），
并在 Evidence 记录"该不变量由本 plan 首次建立"。

- [ ] **Step 3: 写投影解析的失败测试**

```ts
// platform/frontend/src/features/portfolio/portfolioProjection.test.ts
/**
 * Parse the portfolio projection without inventing anything.
 *
 * The browser must not compute a weight, a change, a risk contribution or a
 * readiness status — SPEC-030's construction page acceptance is that the page
 * does not calculate weights.  So these helpers only read and format; a missing
 * field yields no row rather than a zero.
 */
import { describe, expect, it } from 'vitest'

import { targetRows, policyFields, readinessOf } from './portfolioProjection'

describe('portfolioProjection', () => {
  it('returns no rows for a null payload rather than an empty placeholder row', () => {
    expect(targetRows(null)).toEqual([])
  })

  it('keeps an unavailable expected return as null so NumericCell renders a dash', () => {
    const rows = targetRows({
      positions: [{
        security_id: 'security:CN:600519:XSHG',
        target_weight: '0.25',
        prior_weight: '0.00',
        weight_change: '0.25',
        expected_return: null,
        unavailable_reason: null,
      }],
    })
    expect(rows[0].expected_return).toBeNull()
  })

  it('does not recompute weight_change from the two weights', () => {
    // The server sent 0.20 even though 0.25 - 0.00 is 0.25.  The page shows what
    // the server said: a disagreement is a server bug to find, not a number for
    // the browser to silently correct.
    const rows = targetRows({
      positions: [{
        security_id: 'security:CN:600519:XSHG',
        target_weight: '0.25',
        prior_weight: '0.00',
        weight_change: '0.20',
        expected_return: '0.10',
        unavailable_reason: null,
      }],
    })
    expect(rows[0].weight_change).toBe('0.20')
  })

  it('reads readiness from the server status and never infers it from row count', () => {
    expect(readinessOf({ status: 'unavailable', blockers: [{ code: 'X', reason: 'y' }] }))
      .toBe('unavailable')
    // Zero rows with a ready status stays ready-but-empty; inferring 'blocked'
    // from an empty table would contradict the server.
    expect(readinessOf({ status: 'empty', blockers: [] })).toBe('empty')
  })

  it('exposes every policy field the server sent, including ones it cannot format', () => {
    // A policy field dropped because the client has no formatter for it would
    // make an approved limit invisible on the page that shows the limits.
  })
})
```

- [ ] **Step 4: 运行确认红测 → 实现 → 转绿**

Run: `cd platform && npm --prefix frontend test -- --run src/features/portfolio/portfolioProjection.test.ts`

- [ ] **Step 5: `ConstructionPanel` 组件测试（红测先行）**

```tsx
// platform/frontend/src/features/portfolio/ConstructionPanel.test.tsx
/**
 * Construction page contract: six states, and no fabricated holding in any of them.
 *
 * The prototype (node 7:303) already draws its own blocked state —
 * "Pre-trade Readiness: BLOCKED — 真实合格 Snapshot 为 0" with fifteen 0.00% /
 * — / BLOCKED rows.  That is the design's own answer to today's runtime, so the
 * page does not need a fixture to look finished.
 */
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ConstructionPanel } from './ConstructionPanel'

describe('ConstructionPanel', () => {
  afterEach(cleanup)

  it('shows the server blocker when no qualified snapshot exists', () => {
    render(<ConstructionPanel section={{
      key: 'construction', status: 'unavailable', title: '目标持仓',
      blockers: [{
        code: 'P6_NO_QUALIFIED_SIGNAL_SNAPSHOT',
        reason: '真实合格 SignalSnapshot 数量为 0，无法构建目标组合。',
        affected_binding: 'portfolio.target', evidence_ids: [],
      }],
      coverage: {}, payload: null,
    }} />)
    expect(screen.getByText('P6_NO_QUALIFIED_SIGNAL_SNAPSHOT')).toBeInTheDocument()
    expect(screen.getByText(/真实合格 SignalSnapshot 数量为 0/)).toBeInTheDocument()
  })

  it('renders no holdings table at all when the section is unavailable', () => {
    // Not an empty table: an empty table with the ten prototype column headers
    // reads as "we looked and found nothing", which is a stronger claim than
    // "we cannot look".
    render(<ConstructionPanel section={{ /* unavailable */ } as never} />)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('renders an unavailable constraint as a dash with its reason, never as satisfied', () => {
    render(<ConstructionPanel section={{
      key: 'construction', status: 'partial', title: '目标持仓',
      blockers: [{
        code: 'P6_INDUSTRY_CLASSIFICATION_MISSING',
        reason: '行业分类缺失，行业偏离约束无法判定。',
        affected_binding: 'portfolio.constraint.industry_active_weight',
        evidence_ids: [],
      }],
      coverage: { constraints_evaluated: 4, constraints_total: 5 },
      payload: {
        constraints: [
          { constraint_id: 'single_name_weight', status: 'satisfied',
            limit: '0.03', observed: '0.025', reason: null },
          { constraint_id: 'industry_active_weight', status: 'unavailable',
            limit: '0.05', observed: null, reason: '行业分类缺失' },
        ],
      },
    }} />)
    expect(screen.getByText(/行业分类缺失/)).toBeInTheDocument()
    // The observed cell is a dash, and there is no tick anywhere near it.
    expect(screen.queryByText('✓ 满足')).not.toBeInTheDocument()
  })

  it('never renders a prototype sample value', () => {
    render(<ConstructionPanel section={{ /* unavailable */ } as never} />)
    for (const fixture of ['贵州茅台', '600519.SH', '¥500,000,000', 'Top-50',
                           'A-级高流动', '2024-12-06 09:35']) {
      expect(screen.queryByText(fixture)).not.toBeInTheDocument()
    }
  })

  it('disables the construction action and states why', () => {
    // The prototype draws 运行构建 / 冻结研究目标 (Blocked).  Disabled is not
    // enough on its own: a disabled button with no reason reads as a bug.
    render(<ConstructionPanel section={{ /* unavailable */ } as never} />)
    const action = screen.getByRole('button', { name: /运行构建/ })
    expect(action).toBeDisabled()
    expect(action).toHaveAccessibleDescription(/Snapshot/)
  })

  it('shows the policy card even when no target exists', () => {
    // The policy is a real, readable artefact independent of whether a target
    // was built, and it is the page's only honest content today.
  })
})
```

- [ ] **Step 6: 实现 → 转绿 → 接路由**

`AppShell.tsx` 第 185 行改为 `<PortfolioWorkspace />`，lazy 导入方式照
`FactorWorkspace` 现有写法。

- [ ] **Step 7: 四视口真实浏览器验收**

新建 `platform/scripts/verify_portfolio_browser.py`，照
`scripts/verify_desk_browser.py` 的结构（它已经声明"Component tests and curl cannot
replace it: page-level overflow, right-edge clipping and console errors only appear
in a real browser"）。本 Task 只验 construction tab，后续 Task 逐 tab 追加。

```bash
cd platform
docker compose up -d postgres
ASP_DATABASE_URL=postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_layered_dev \
PYTHONPATH=src .venv/bin/python -m uvicorn a_share_platform.api.app:app \
  --host 127.0.0.1 --port 8010 --reload &
cd frontend && npm run dev &
sleep 6
cd .. && .venv/bin/python scripts/verify_portfolio_browser.py --tab construction
```

每个视口必须：`document.documentElement.scrollWidth === clientWidth`、
无右侧裁切、控制台无 error/warning、正常重载无非预期 4xx/5xx、
**无任何原型示例值**。

- [ ] **Step 8: 提交**

```bash
cd platform
npm --prefix frontend test -- --run && npm --prefix frontend run lint \
  && npm --prefix frontend run build
cd .. && git add platform/frontend/src/pages/PortfolioWorkspace.tsx \
  platform/frontend/src/pages/PortfolioWorkspace.test.tsx \
  platform/frontend/src/features/portfolio/ \
  platform/frontend/src/app/AppShell.tsx \
  platform/frontend/src/app/shell.less \
  platform/frontend/src/app/layoutGrid.test.ts \
  platform/scripts/verify_portfolio_browser.py
git commit -m "feat: build the portfolio workspace shell and the construction page

The prototype at node 7:303 draws its own blocked state: fifteen rows of 0.00% and
BLOCKED under the line 'Pre-trade Readiness: BLOCKED — 真实合格 Snapshot 为 0'.
The design already answered the question this page faces today, so nothing has to
be invented to make it look finished.

An unavailable section renders no holdings table at all rather than an empty one.
An empty table under the ten prototype column headers says 'we looked and found
nothing', which is a stronger claim than 'we cannot look' — and only the second one
is true while there are no qualified snapshots.

An unevaluable constraint shows a dash with its reason and no tick.  The
prototype's checklist draws ✓ 满足 beside five constraints; rendering that tick for
a constraint whose input is missing is a false clearance on a concentration limit,
which is the one class of error a risk page must never make.

The page does not recompute weight_change from the two weights it was given.  If
the server's change disagrees with its own weights that is a server bug worth
finding, and a browser that quietly corrects it removes the only symptom.

The workspace grid declares minmax(0, 1fr) from the start, and the invariant is
added to the layout test.  An implicit grid column is max-content, so an AntD Tabs
nav sets the page width — the root cause of the /factors 320 overflow, and there
is no reason to reproduce it here first and fix it later."
```

---

### Task 11: Backtests 页（node `7:712`）

**Files:**
- Create: `platform/frontend/src/features/portfolio/BacktestPanel.tsx`
- Create: `platform/frontend/src/features/portfolio/BacktestPanel.test.tsx`
- Create: `platform/frontend/src/features/portfolio/TradeLedgerTable.tsx`
- Create: `platform/frontend/src/features/portfolio/TradeLedgerTable.test.tsx`
- Modify: `platform/frontend/src/pages/PortfolioWorkspace.tsx`
- Modify: `platform/scripts/verify_portfolio_browser.py`

**Interfaces:**
- Consumes: `GET /api/portfolios/backtests`、`GET /api/portfolios/backtests/{run_id}/trades`

- [ ] **Step 1: 提取 node `7:712` 结构**

已实测：`workspace` 1192 × 1173；`config-card` 1144 × 171
（`title` 287 × 17、`config-grid` 1104 × 45、`Line` 1104、`rules-row` 1104 × 21）；
`layout-columns` 1144 × 934 = `left-col` **724** + `right-col` **400**，gap 20。
另有 `company-header-band` 1192 × 89（`header-meta-row` + `sub-navigation`）与 `footer` 1192 × 41。

`sub-navigation` 的六项：`概览` `分仓明细` `交易对账` `归因分析` `极端压力测试` `InvestmentView`。
**注意这与 SPEC-048 的五个 tab（Construction/Backtests/Risk/Scenarios/Attribution）不一致** ——
原型的 sub-navigation 是页内子导航，不是一级 tab。这条差异要写进 Evidence，
**运行时以 SPEC-048 为准**（Spec 优先于原型）。

- [ ] **Step 2: 写台账测试（红测先行）—— 阻断行必须可见**

```tsx
// platform/frontend/src/features/portfolio/TradeLedgerTable.test.tsx
/**
 * The trade ledger's whole purpose is the rows that did not fill.
 *
 * SPEC-034's acceptance is 被阻塞订单有原因且不会静默消失, and the prototype's
 * ledger draws three statuses — 成交 / 阻断 / 部分 — with 计划数量 and 实际数量 as
 * separate columns precisely so a block is visible as 50,000 planned against 0
 * filled.
 */
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { TradeLedgerTable } from './TradeLedgerTable'

const rows = [
  { trade_id: 't1', session: '2024-12-06', security_id: 'security:CN:600519:XSHG',
    side: 'buy', requested_shares: 10_000, filled_shares: 10_000,
    fill_price: '1856.20', status: 'filled', block_reasons: [] },
  { trade_id: 't2', session: '2024-12-06', security_id: 'security:CN:000001:XSHE',
    side: 'buy', requested_shares: 50_000, filled_shares: 0,
    fill_price: null, status: 'blocked', block_reasons: ['suspended'] },
  { trade_id: 't3', session: '2024-12-06', security_id: 'security:CN:601398:XSHG',
    side: 'sell', requested_shares: 30_000, filled_shares: 15_000,
    fill_price: '5.60', status: 'partial', block_reasons: ['participation_cap'] },
]

describe('TradeLedgerTable', () => {
  afterEach(cleanup)

  it('renders blocked rows alongside fills', () => {
    render(<TradeLedgerTable rows={rows} />)
    expect(screen.getAllByRole('row')).toHaveLength(rows.length + 1)
  })

  it('shows planned and filled quantities as separate values for a partial', () => {
    render(<TradeLedgerTable rows={rows} />)
    expect(screen.getByText('30,000')).toBeInTheDocument()
    expect(screen.getByText('15,000')).toBeInTheDocument()
  })

  it('shows every block reason, not only the first', () => {
    render(<TradeLedgerTable rows={[{
      ...rows[1], block_reasons: ['suspended', 'special_treatment_excluded', 'below_one_lot'],
    }]} />)
    for (const reason of ['停牌', 'ST', '不足一手']) {
      expect(screen.getByText(new RegExp(reason))).toBeInTheDocument()
    }
  })

  it('renders a blocked row price as a dash, never as zero', () => {
    // A zero price in a ledger sorted by price puts blocked orders first and
    // reads as a free trade.
    render(<TradeLedgerTable rows={[rows[1]]} />)
    expect(screen.queryByText('0.00')).not.toBeInTheDocument()
  })

  it('does not offer a filter that hides blocked rows by default', () => {
    // A default filter to fills makes the blocked rows unreachable in practice
    // while satisfying every assertion above.
  })

  it('paginates without dropping the blocked rows off the reachable pages', () => {
    // Same discipline as PUI-04's failed-experiment pagination.
  })
})
```

- [ ] **Step 3: 权益曲线与双引擎面板测试（红测先行）**

```tsx
// platform/frontend/src/features/portfolio/BacktestPanel.test.tsx
describe('BacktestPanel', () => {
  it('states the backtest kind rather than the word 回测 alone', () => {
    // SPEC-048 acceptance: Backtests 必须标注具体回测类型.
    expect(screen.getByText(/选股回测|stock_selection_backtest/)).toBeInTheDocument()
  })

  it('renders no equity curve when no run exists', () => {
    // Not a flat line at 100: a flat line is a result.
    expect(screen.queryByRole('img', { name: /权益曲线/ })).not.toBeInTheDocument()
  })

  it('shows the execution rule chips from the server run spec, not from constants', () => {
    // The prototype draws 佣金 0.08% / 印花税 0.1% / 滑点 0.05% / 参与率≤15%.
    // Those are CostModel values on the run; hard-coding them would display a
    // cost model the run never used.
  })

  it('reports the dual-engine panel as unavailable with its reason when no engine is qualified', () => {
    // Task 6's verdict decides this.  The prototype draws 可接受 and 需调查
    // badges; neither may appear without a real second engine.
    expect(screen.getByText(/外部对照引擎未资格化/)).toBeInTheDocument()
    expect(screen.queryByText('可接受')).not.toBeInTheDocument()
  })

  it('shows the PIT eligibility blocker verbatim from the server', () => {
    // The prototype's own text: BLOCKED / 原因: PIT Snapshot 缺失 /
    // • 结构已就绪但科学结果不可用 / • 盘后信号不能当日收盘成交.
  })

  it('never renders a prototype performance number', () => {
    for (const fixture of ['+78.2%', '+28.5%', '+12.4%', '1,856.20', '98.3%']) {
      expect(screen.queryByText(fixture)).not.toBeInTheDocument()
    }
  })
})
```

- [ ] **Step 4: 实现 → 转绿 → 四视口验收**

`left-col` 724 / `right-col` 400 在 1440 下按比例实现；1024 及以下折叠为单列。
**折叠顺序必须让阻断台账与 PIT blocker 优先可见**，不能把它们推到最底。

- [ ] **Step 5: 提交**

```bash
git commit -m "feat: add the backtests page with blocked orders as first-class rows

The ledger exists for the rows that did not fill.  The prototype draws three
statuses and keeps 计划数量 and 实际数量 as separate columns so a block appears as
50,000 planned against 0 filled, and SPEC-034 makes that visibility an acceptance
criterion rather than a nicety.  So the tests assert the blocked rows are present,
that every reason is shown rather than only the first, and that no default filter
quietly reduces the table to fills — a filter would satisfy every other assertion
while making the rows unreachable.

A blocked row's price is a dash.  Rendering zero puts blocked orders at the top of
a price sort and reads as a free trade.

No run means no curve, not a flat line at 100.  A flat line is a result, and it is
the result that says the strategy did nothing rather than that nothing ran.

The execution rule chips come from the run's own cost model instead of constants.
The prototype's 0.08% commission and 0.1% stamp duty are design values; printing
them beside a run that used different rates would describe a run that never
happened.

The dual-engine panel reports unavailable with its reason until Task 6 qualifies an
engine.  The prototype's 可接受 and 需调查 badges are the two things that must not
appear without a real second engine, because a reconciliation badge is read as
independent confirmation."
```

---

### Task 12: Risk 与 Scenarios 页（共用 node `7:1060`）

两页共用一个 Frame，因此合并为一个 Task。但**运行时是两个 tab**（SPEC-048），
各自独立的六态。

**Files:**
- Create: `platform/frontend/src/features/portfolio/RiskPanel.tsx`
- Create: `platform/frontend/src/features/portfolio/RiskPanel.test.tsx`
- Create: `platform/frontend/src/features/portfolio/ScenarioPanel.tsx`
- Create: `platform/frontend/src/features/portfolio/ScenarioPanel.test.tsx`
- Modify: `platform/frontend/src/pages/PortfolioWorkspace.tsx`
- Modify: `platform/scripts/verify_portfolio_browser.py`

- [ ] **Step 1: 提取 node `7:1060` 结构**

已实测：`workspace` 1192 × 1077；`top-metrics-row` 1144 × 114 含四张
`kpi-card` **274 × 113/114** gap 16；`layout-columns` 1144 × 895 =
`left-col` **624** + `right-col` **500**。

- [ ] **Step 2: 风险面板测试（红测先行）—— 闭合的勾必须能不出现**

```tsx
// platform/frontend/src/features/portfolio/RiskPanel.test.tsx
/**
 * Risk page: exposures, decomposition and the closure tick.
 *
 * The prototype prints "✓ 风险分项和闭合校验: factor + specific = 100%".  The tick
 * is a claim, so the test that matters is the one where it must be absent.
 */
describe('RiskPanel', () => {
  it('shows the closure tick only when the server says closure passed', () => {
    render(<RiskPanel section={sectionWith({
      decomposition: { closure_residual: '0.0001', closure_tolerance: '0.001',
                       status: 'quantified' },
    })} />)
    expect(screen.getByText(/闭合/)).toBeInTheDocument()
  })

  it('shows a closure failure as a failure, not as a missing tick', () => {
    render(<RiskPanel section={sectionWith({
      decomposition: { closure_residual: '0.043', closure_tolerance: '0.001',
                       status: 'closure_failed',
                       unavailable_reason: '分项和与总风险差异 4.3%，超过容差 0.1%' },
    })} />)
    expect(screen.getByText(/超过容差/)).toBeInTheDocument()
    expect(screen.queryByText('✓')).not.toBeInTheDocument()
  })

  it('renders an unavailable exposure as a dash with a reason and no active value', () => {
    // A zero active exposure claims the portfolio matches the benchmark.
    render(<RiskPanel section={sectionWith({
      exposures: [{ factor_id: '食品饮料', kind: 'industry',
                    portfolio_exposure: '0.145', benchmark_exposure: null,
                    active_exposure: null,
                    unavailable_reason: '基准行业权重缺失' }],
    })} />)
    expect(screen.getByText(/基准行业权重缺失/)).toBeInTheDocument()
    expect(screen.queryByText('0.00')).not.toBeInTheDocument()
  })

  it('labels the risk model lifecycle from the server', () => {
    // The prototype draws DRAFT twice and 'Risk Model R0 - v0.3'.  DRAFT is a
    // governance fact and must come from the record, not from a constant that
    // happens to say DRAFT today and would keep saying it after promotion.
  })

  it('never renders a prototype risk number', () => {
    for (const fixture of ['18.2%', '5.6%', '3.8%', 'R0-v0.3', 'RUN-20241206-001',
                           '贵州茅台', '0.24']) {
      expect(screen.queryByText(fixture)).not.toBeInTheDocument()
    }
  })

  it('states that the covariance method is Ledoit-Wolf only when the spec says so', () => {
    // The method is a versioned input; a hard-coded label would misdescribe a run
    // that used the identity target.
  })
})
```

- [ ] **Step 3: 情景面板测试（红测先行）—— 未映射不填 0**

```tsx
// platform/frontend/src/features/portfolio/ScenarioPanel.test.tsx
describe('ScenarioPanel', () => {
  it('renders an unmapped scenario as a dash and the word unavailable', () => {
    // The prototype itself draws 行业轮动极端 (Rotational) as — / unavailable, and
    // docs/18 line 91 requires it: 未映射暴露 unavailable，不得填 0.  A zero shock
    // reads as "this scenario cannot hurt us".
    render(<ScenarioPanel section={sectionWith({
      scenarios: [{ scenario_id: 'rotational', shock: null,
                    confidence: null, status: 'unavailable',
                    reason: '行业轮动暴露未映射' }],
    })} />)
    expect(screen.getByText(/未映射/)).toBeInTheDocument()
    expect(screen.queryByText('0.0%')).not.toBeInTheDocument()
  })

  it('shows partial coverage as a fraction rather than a full-looking number', () => {
    // Three of five shocked factors mapped: the cell says 3/5.
  })

  it('separates a triggered invalidator from a hypothetical shock', () => {
    // The prototype draws 公司 Invalidator 触发 with status Triggered next to
    // hypothetical macro scenarios.  A real trigger and a what-if are different
    // kinds of statement and cannot share a confidence label.
  })

  it('renders the scenarios tab independently of the risk tab state', () => {
    // SPEC-048 gives each tab its own six states even though they share a frame.
  })
})
```

- [ ] **Step 4: 实现 → 转绿 → 四视口验收（两个 tab 各验一遍）**

- [ ] **Step 5: 提交**

```bash
git commit -m "feat: add the risk and scenarios pages with a closure tick that can be absent

The prototype prints a tick beside 'factor + specific = 100%', so the test that
carries the weight is the one where the tick must not appear: a closure failure
renders as an explicit failure with the residual and the tolerance, not as a
quietly missing checkmark that looks like a rendering gap.

An unavailable exposure shows a dash and its reason and no active value at all.  A
zero active exposure is not a neutral placeholder — it claims the portfolio matches
the benchmark on that factor, which is a stronger statement than anything the page
actually knows.

The scenarios table keeps the prototype's own unavailable row.  docs/18 requires
未映射暴露 unavailable，不得填 0, and the reason is that a zero shock reads as
'this scenario cannot hurt us', which is exactly backwards from 'we cannot tell'.

Risk lifecycle and covariance method both come from the record rather than from
labels.  A constant that reads DRAFT is correct today and becomes a lie the day a
model is promoted, and a hard-coded Ledoit-Wolf label misdescribes any run that
used a different shrinkage target.

Risk and Scenarios share Figma node 7:1060 but remain two tabs with independent
six-state contracts, because SPEC-048 scopes the states per tab and one shared
frame is a design fact rather than a runtime one."
```

---

### Task 13: Attribution 页（node `7:1348`）

**Files:**
- Create: `platform/frontend/src/features/portfolio/AttributionPanel.tsx`
- Create: `platform/frontend/src/features/portfolio/AttributionPanel.test.tsx`
- Modify: `platform/frontend/src/pages/PortfolioWorkspace.tsx`
- Modify: `platform/scripts/verify_portfolio_browser.py`

- [ ] **Step 1: 提取 node `7:1348` 结构**

已实测：`workspace` 1192 × 1106；`top-metrics-row` 1144 × 106 含四张
`kpi-card` **274 × 105/106**；`layout-columns` 1144 × 932 =
`left-col` **624** + `right-col` **500**。

瀑布九段的原型值：Market `+1.82%`、Industry `+0.31%`、Style `-0.12%`、
Selection `+0.48%`、Cost `-0.18%`、**Timing `+0.15%`**、**Events `N/A`**、
**Execution `+0.09%`**、Residual `0.00%`、Total `+0.73%`。

- [ ] **Step 2: 写测试（红测先行）—— 三种"无贡献"必须可区分**

```tsx
// platform/frontend/src/features/portfolio/AttributionPanel.test.tsx
/**
 * Attribution page: core-only, with three distinguishable kinds of no-contribution.
 *
 * SPEC-039 keeps every component in the schema and separates not_applicable
 * (the strategy did not use it), unavailable (the module or evidence is missing)
 * and a provable zero.  All three render as "no contribution" to a casual reader,
 * so the page has to say which one it is — and the prototype does not, because it
 * draws Timing at +0.15% and Execution at +0.09%.
 */
describe('AttributionPanel', () => {
  it('renders timing as not applicable with its reason, never as a number', () => {
    // ADR-0006 decision 7 fixes Shadow timing's portfolio impact at zero, and
    // SPEC-030 forbids a Shadow forecast from entering target weights.  The
    // prototype's +0.15% is a design illustration.
    render(<AttributionPanel section={sectionWith({
      components: [{ name: 'timing', status: 'not_applicable', contribution: null,
                     status_reason: 'Timing 处于 Shadow，对组合影响固定为 0' }],
    })} />)
    expect(screen.getByText(/Shadow/)).toBeInTheDocument()
    expect(screen.queryByText('+0.15%')).not.toBeInTheDocument()
  })

  it('renders events and execution as unavailable with their phase reasons', () => {
    // Events attribution is P8; execution attribution needs a real OMS from P10.
    render(<AttributionPanel section={sectionWith({
      components: [
        { name: 'events', status: 'unavailable', contribution: null,
          status_reason: '事件归因属 P8，尚未实现' },
        { name: 'execution', status: 'unavailable', contribution: null,
          status_reason: '执行归因需要真实 OMS，属 P10' },
      ],
    })} />)
    expect(screen.getByText(/属 P8/)).toBeInTheDocument()
    expect(screen.getByText(/属 P10/)).toBeInTheDocument()
    expect(screen.queryByText('+0.09%')).not.toBeInTheDocument()
  })

  it('distinguishes not_applicable from unavailable in the rendered text', () => {
    // The failure this catches: one shared "—" for both, which merges a design
    // decision with a missing module.
    render(<AttributionPanel section={sectionWith({
      components: [
        { name: 'timing', status: 'not_applicable', contribution: null,
          status_reason: 'Shadow 阶段影响为 0' },
        { name: 'events', status: 'unavailable', contribution: null,
          status_reason: '属 P8' },
      ],
    })} />)
    const timing = screen.getByRole('row', { name: /Timing/ })
    const events = screen.getByRole('row', { name: /Events/ })
    expect(timing.textContent).not.toBe(events.textContent)
  })

  it('shows every schema component even when it has nothing to report', () => {
    // SPEC-039: 归因 schema 从第一版保留全部分项.  A component that disappears
    // makes its absence indistinguishable from a projection bug.
    render(<AttributionPanel section={sectionWith({ components: [] })} />)
    for (const name of ['Market', 'Industry', 'Style', 'Selection', 'Cost',
                        'Timing', 'Events', 'Execution', 'Residual']) {
      expect(screen.getByText(name)).toBeInTheDocument()
    }
  })

  it('labels the snapshot core_only so it is not read as unified attribution', () => {
    // SPEC-039: P6 的选股回测只能完成 core attribution.
    expect(screen.getByText(/core attribution|核心归因/)).toBeInTheDocument()
  })

  it('renders a closure failure instead of a waterfall', () => {
    // SPEC-039 acceptance: 无法闭合时标记 failed，不发布"解释性"图表冒充闭合归因.
    // A waterfall whose bars do not sum to the total is the "explanatory chart"
    // that acceptance criterion names.
    render(<AttributionPanel section={sectionWith({
      closure_status: 'failed', residual: '0.0043', tolerance: '0.0005',
    })} />)
    expect(screen.queryByRole('img', { name: /瀑布/ })).not.toBeInTheDocument()
    expect(screen.getByText(/未闭合/)).toBeInTheDocument()
  })

  it('never renders a prototype attribution number', () => {
    for (const fixture of ['+2.84%', '+2.11%', '+0.73%', '+1.82%', 'ATTR-v1.0',
                           'RUN-ATTR-20241206-889', '9.5 bps', '￥286,330']) {
      expect(screen.queryByText(fixture)).not.toBeInTheDocument()
    }
  })
})
```

- [ ] **Step 3: 实现 → 转绿 → 四视口验收**

- [ ] **Step 4: 提交**

```bash
git commit -m "feat: add the attribution page keeping three kinds of no-contribution distinct

SPEC-039 separates not_applicable, unavailable and a provable zero, and all three
look identical to a casual reader.  So the page renders different text for each and
a test asserts the timing row and the events row do not share a rendering: timing
is not applicable because ADR-0006 fixes Shadow impact at zero, while events are
unavailable because P8 does not exist.  One shared dash would merge a design
decision with a missing module, and only the second one is something to go build.

The prototype draws Timing at +0.15% and Execution at +0.09%.  Both are design
illustrations that contradict the governance rules — a Shadow forecast may not
enter portfolio weights, and execution attribution needs an OMS that P10 has not
built — so the tests assert those two numbers never appear.

A closure failure renders as a failure rather than as a waterfall with a residual
bar.  SPEC-039's acceptance names exactly this: 不发布"解释性"图表冒充闭合归因.
Bars that do not sum to the total are that explanatory chart, and a reader
interprets a waterfall as an accounting identity whether or not it closes.

Every schema component is rendered even when it has nothing to say, because a row
that disappears makes its absence indistinguishable from a projection bug — and the
whole point of keeping the schema fixed from the first version is that a gap stays
visible."
```

---

### Task 14: Desk 分区更新、Evidence 与明确否认

**Files:**
- Modify: `platform/src/a_share_platform/application/desk_projection.py`（`_portfolio_tracking`）
- Modify: `platform/tests/test_desk_projection.py`
- Modify: `platform/frontend/src/features/desk/DeskSection.test.tsx`
  （**仅当 blocker code 变化**；若 P6 仍不可用则**一字不改**）
- Modify: `docs/27-p6-implementation-evidence.md`
- Modify: `docs/plans/step-05-p6-core-selection.md`（八个 Task 的真实状态）
- Modify: `docs/plans/track-00-prototype-runtime-delivery.md`（PUI-05 三轴结论）
- Modify: `docs/22-prototype-runtime-gap-audit.md`（**追加增量节，不改写原 §5 矩阵**）

- [ ] **Step 1: 判断 Desk 分区能否从 unavailable 转出**

`application/desk_projection.py` 第 352–361 行当前报
`P6_PORTFOLIO_TRACKING_NOT_IMPLEMENTED`。转出的条件是**真实存在**
`TargetPortfolioSnapshot` 或 `RiskModelDecisionRecord`：

```bash
cd platform && source /tmp/asp_env.sh
.venv/bin/python - <<'PY'
import os, psycopg
with psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True) as c:
    for t in ("research.target_portfolio_snapshots", "research.risk_model_decisions",
              "research.backtest_runs", "research.attribution_snapshots"):
        print(t, c.execute(f"select count(*) from {t}").fetchone()[0])
PY
```

**判断规则**：
- 四表全为 0 → **不改 `_portfolio_tracking`**，只把 blocker reason 从
  "尚未实现"更新为"能力已实现，但无合格输入"（这是两个不同的事实）；
- 有真实记录 → 改为 `partial` 并声明 coverage；`DeskSection` 的
  `partial` 必须带 coverage 或 blocker（`domain/desk.py` 已强制）。

**不得**因为代码写完了就把分区改成 `ready` —— Desk 的 Portfolio 分区
展示的是真实持仓与偏离，没有真实目标就没有可展示的内容。

- [ ] **Step 2: 记录真实红绿测**

每个 Task 的**真实**失败文本与转绿结果，原样抄录。至少包含：

- Task 2 的 `ModuleNotFoundError: No module named 'a_share_platform.domain.portfolio'`；
- Task 5 的 T+1 首个红测失败文本；
- Task 6 的 spike 真实输出（含 `rqalpha` 的真实安装错误或版本号）；
- Task 9 的 migration 空库 + 幂等两次运行输出；
- 后端 `unittest discover` 的真实通过数（当前基线 817；本 plan 新增数量照实记录）；
- 前端 Vitest 真实通过数（当前基线 73）。

**不编造命令输出。**

- [ ] **Step 3: 记录真实回测数值（无论好坏）**

Task 8 Step 7 的真实运行输出，逐项：

```text
运行窗口、policy hash、run hash、qualified snapshot 数
成交笔数 / 部分成交笔数 / 阻断笔数
每种 BlockReason 的计数（这是 A 股规则是否真的生效的唯一证据）
公司行动事件数与类型分布
equity 起止值、累计收益、最大回撤、换手、成本前/后
风险分项闭合残差、归因日度闭合失败 session 数
双引擎 diff（若引擎已资格化）或 unavailable 原因
```

**如果阻断笔数为 0，必须查明原因并记录。** 一个 2018–2025 的 A 股回测
完全没有停牌、涨跌停或参与率阻断，几乎必然意味着规则没有真正接上数据。

- [ ] **Step 4: 逐页登记三轴状态**

```text
                    design_status                          runtime_status  capability_status
Construction        parity_verified_with_known_deviation   verified        <按实际>
                    （node 7:303，1440 逐区对照）
Backtests           parity_verified_with_known_deviation   verified        <按实际>
                    （node 7:712）
Risk                parity_verified_with_known_deviation   verified        <按实际>
                    （node 7:1060）
Scenarios           parity_verified_with_known_deviation   verified        <按实际>
                    （共用 node 7:1060，弱于 Risk）
Attribution         parity_verified_with_known_deviation   verified        <按实际>
                    （node 7:1348）
```

**五页都有精确 Frame，这是 PUI-05 与 PUI-04 的关键区别**
（PUI-04 十页中七页无 Frame）。但 `design_status` 仍**不得**写成 `ready`：
summary JSON 在第 4 层截断为 `children_count` 且无 `layoutMode`/`itemSpacing`，
列宽只能从 SVG 坐标推断，因此只能是 `parity_verified_with_known_deviation`。

- [ ] **Step 5: 逐条记录与原型的已知差异**

至少七条：

```text
1. 侧栏 280 px（运行时，SPEC-045）vs 248 px（Figma）→ 内容区 1160 vs 1192，
   已批准差异（P-4 plan 已登记，不得改回）
2. node 7:303 多一层 viewport-wrap，另三页没有 → 实现不复制该容器
3. 原型 sub-navigation 六项（概览/分仓明细/交易对账/归因分析/极端压力测试/InvestmentView）
   与 SPEC-048 的五 tab 不一致 → 运行时以 Spec 为准
4. Attribution 瀑布的 Timing +0.15% 与 Execution +0.09% 违反 SPEC-039 与
   ADR-0006 决策 7 → 运行时分别为 not_applicable 与 unavailable
5. Backtest 的 Internal vs RQAlpha 面板的「可接受」「需调查」徽章需要真实第二引擎
   → Task 6 未资格化时显示 unavailable
6. Risk 的 Ledoit-Wolf 标签与 R0-v0.3 版本号来自记录而非常量
7. Construction 的六项 checklist ✓ 满足 在输入缺失时不得渲染
```

- [ ] **Step 6: 写明确否认声明（必须逐字包含）**

> 本 plan 交付**组合构建、Risk R0、A 股现实回测引擎、core attribution 的工程实现**
> 与**五个 Portfolio 产品页**。它**不代表**：
>
> - P2、P4、P5 或 P6 Gate 通过 —— 四者的数据与科学阻断完全未变；
> - 任何策略或因子科学有效 —— 输入全部为 `normalized_current`，
>   未经 PIT 验证、无样本外、无多重检验校正、无容量验证；
> - 回测结论可信 —— **引擎正确性与结论有效性是两件事**。本 plan 证明的是
>   T+1、整手、涨跌停、停牌、ST、公司行动、费用、参与率被正确实现，
>   **不是**这些规则下产生的收益可复现或可实现；
> - SPEC-034 的 SHOULD 项（双引擎 reconciliation）完成 —— 取决于 Task 6 的 verdict；
>   未资格化时该项**未满足**，且内部引擎跑两次**不算**双引擎；
> - SPEC-039 的完整验收通过 —— P6 只完成 core attribution；
>   含 Timing、事件与真实执行的 unified attribution 属 P9；
> - 平台具备 Paper-ready 或实盘能力 —— OMS 属 P10，真实账户属 P11 且需新授权。
>
> 本 plan 产出的 `TargetPortfolioSnapshot` 只在 `research_backtest` scope 内有效，
> 不得进入 `shadow` / `paper` / `limited_live`。

- [ ] **Step 7: 更新冻结 Plan 与 Track 的真实状态**

`docs/plans/step-05-p6-core-selection.md`：状态从 `dependency_blocked` 改为
**按实际** `in_progress` 或 `capability_complete_gate_blocked`。
**不得改为 Gate 通过** —— Spec 验收要求"双引擎差异逐笔分类"与
"浏览器黄金路径完整"，后者在无合格 Snapshot 时不可能完成。

`docs/plans/track-00-prototype-runtime-delivery.md`：PUI-05 状态与三轴结论表。

`docs/22-prototype-runtime-gap-audit.md`：**追加**「2026-08-16 PUI-05 完成后的增量更新」，
原 §5 矩阵（第 12–16 行的五个 `placeholder`）**保留不改** —— 它记录审计时点事实。

- [ ] **Step 8: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
npm --prefix frontend test -- --run
npm --prefix frontend run lint
npm --prefix frontend run build
.venv/bin/python scripts/verify_portfolio_browser.py
git diff --check
cd .. && git add platform/src/a_share_platform/application/desk_projection.py \
  platform/tests/test_desk_projection.py \
  docs/27-p6-implementation-evidence.md \
  docs/plans/step-05-p6-core-selection.md \
  docs/plans/track-00-prototype-runtime-delivery.md \
  docs/22-prototype-runtime-gap-audit.md
git commit -m "docs: record P6 evidence separating engine correctness from result validity

The blocked-order counts by reason are the most important numbers in this
document, and not because they are interesting.  A 2018-2025 A-share backtest with
zero suspension, zero locked-limit and zero participation blocks almost certainly
means the rules were never wired to the data, so a clean ledger is a red flag
rather than a clean bill of health.  The counts are recorded per reason for exactly
that reason.

The desk portfolio section keeps reporting unavailable while the four research
tables are empty, but its blocker reason changes from 'not implemented' to
'implemented, no qualified input'.  Those are different facts and they point at
different work.

All five pages have a dedicated high-fidelity frame, which is what separates PUI-05
from PUI-04's seven frameless pages.  Even so design_status stops at
parity_verified_with_known_deviation rather than ready: the node summary truncates
below the fourth level into children_count and carries no layoutMode or
itemSpacing, so column widths are inferred from SVG coordinates.  Inference is not
parity.

Seven deviations from the prototype are listed, and two of them are cases where the
design contradicts the governance rules.  The attribution waterfall draws Timing at
+0.15% and Execution at +0.09%; a Shadow timing forecast may not enter portfolio
weights and execution attribution needs an OMS from P10, so the runtime reports
not_applicable and unavailable instead.

The denial section states plainly that a correct engine is not a valid conclusion.
This plan proves T+1, lots, limits, suspensions, ST, corporate actions, fees and
participation are implemented as specified.  It proves nothing whatsoever about
whether the returns produced under those rules are repeatable, and no gate moves."
```

---

## 完成定义

1. `PortfolioPolicy` 十九个字段全部必填、无默认、无 benchmark 字面量，且成本相关字段进入 hash（Task 2）；
2. Top-N 等权与 ER 权重均有**手算 fixture**；整手向下取整；残余现金确定且闭合到 AUM（Task 3）；
3. Risk R0 的 exposure / 收缩协方差 / 分项闭合 / 情景全部实现；
   **闭合残差超阈值报 `CLOSURE_FAILED`**，无 "other" 分项；NumPy 交叉验证输入一致（Task 4）；
4. A 股规则逐条有测试：T+1（含部分结算）、买入整手/卖出允许碎股、
   `LOCKED_UP` 与 `LIMIT_UP` 区分、停牌、ST（买阻断卖不阻断）、退市、
   参与率上限、费用（印花税单边 + 最低佣金）（Task 5）；
5. 外部引擎 D0 spike 有可复现结论与 ADR-0013；**未资格化时 adapter 不存在**（Task 6）；
6. 回测状态机六个转移各有独立测试；公司行动走账本不走复权价；
   `test_no_forward_adjusted_price_path_exists_in_the_engine` 通过（Task 7）；
7. core attribution **日度闭合先于累计闭合**；三种"无贡献"可区分；
   `scope == "core_only"`（Task 7）；
8. ports / memory adapter / application / worker 完成；
   worker dry-run 默认、ack 门控；application 层无任何算术（Task 8）；
9. migration `0037` 五张表在 `research`、append-only、约束覆盖领域不变量；
   空库 + 幂等 smoke 通过；只读 API 全部为 GET（Task 9）；
10. 五页复用 `DeskSection` 六态合同，各自四视口验收无页面级溢出、
    无原型示例值泄漏、控制台无 error/warning（Task 10–13）；
11. Desk Portfolio 分区状态按真实数据判定，未改为 `ready`（Task 14）；
12. Evidence 含真实红绿测、真实回测数值（含逐 BlockReason 计数）、
    七条原型差异与明确否认（Task 14）；
13. 后端 unittest / compileall / ruff / mypy 全过；前端 Vitest / lint / build 全过；
    `verify_portfolio_browser.py` 20 个检查点（5 页 × 4 视口）全过；
14. `git diff --check` 干净，一个 Task 一个独立提交（Task 7 与 Task 12 各两个 commit）。

## 明确不在本 plan 范围

- **OMS、订单、成交、持仓现金对账、kill switch** —— 属 P10 / SPEC-036–038；
  本 plan 的 `TradeRecord` 是模拟成交记录，不是 broker 订单；
- **主动 Timing 的非零组合贡献** —— 属 P7；ADR-0006 决策 7 与 SPEC-030 固定
  Shadow 影响为 0，归因中标 `not_applicable`；
- **事件数值增强与事件归因** —— 属 P8；归因中标 `unavailable`；
- **执行归因（implementation shortfall、滑点模型误差、成交率）** —— 需真实执行，属 P10；
- **unified attribution** —— 属 P9；本 plan 只做 core attribution；
- **Risk R1（自建 A 股风险模型）与 R2（商业模型对照）** —— SPEC-032 分级，本 plan 只做 R0；
- **`strict_historical` 回测** —— 需 `pit_verified` 数据，属付费源；
- **真实 VWAP 执行价** —— VWAP source 未资格化（P6-D1-01），
  本 plan 用显式声明的 `next_session_open` 退化口径；
- **风险与集中度限额的批准值** —— P6-D1-02 待用户批准，测试 fixture 不构成批准；
- **周度再平衡基线** —— ADR-0006 决策 2 只允许作为预登记敏感度；
- **双引擎 reconciliation 的实现** —— 取决于 Task 6 verdict；未资格化时不做；
- **截图 diff 工具** —— 需用户先批准基线与容差（`docs/plans/track-00` PUI-00 已记录）；
- **任何写接口** —— 组合构建只经 worker + ack。

## 本 plan 完成后仍然成立的限制

- **所有输入为 `normalized_current`**，因此所有回测结论**不是样本外证据**，
  不得据此声称任何策略或因子有效；
- **P2、P4、P5、P6 Gate 全部未通过** —— 本 plan 不改变任何一条；
- 若 `research.signal_snapshots` 仍为 0，则五页运行时全部显示真实 blocker，
  真实回测为空运行 —— **这是被验收的状态，不是缺陷**；
- 双引擎 reconciliation 可能**永久不可用**（若引擎资格化失败且 LEAN 也不可用），
  此时 SPEC-034 的 SHOULD 项未满足，且不得用内部引擎自比冒充；
- 涨跌停数据当前不存在（`docs/11` 第 32 行：BaoStock 无独立上下限字段），
  因此 `strict_price_limits` 配置下大量订单会被 `MARKET_DATA_UNAVAILABLE` 阻断 ——
  **这是诚实的，不得为了让回测跑通而默认"无数据即无限制"**；
- 五页 `design_status` 为 `parity_verified_with_known_deviation`，**不是 `ready`**；
  31 页完全逐像素 parity 计数**仍为 0/31**；
- 侧栏 280 px 使 1440 内容区为 1160 px 而非 Figma 的 1192 px，属已批准差异；
- Vite 的 AntD large-chunk warning 仍然存在，**不得隐藏也不得写成已修复**；
- `TargetPortfolioSnapshot` 只在 `research_backtest` scope 内有效，
  **不得进入 `shadow` / `paper` / `limited_live`**；
- 本 plan **不授权**任何真实账户操作。P11 需用户新的明确授权。
