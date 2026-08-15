# Step 05 Spec / Plan：P6 Core Selection Golden Path

> 状态：`dependency_blocked`（决策已冻结，等待 P5 Gate）  
> 对应：Plan P6-W01–W06/Gate、Roadmap Step 5  
> 关联 SPEC：030–035、039、048、050、059  
> D0：第一 benchmark、外部回测引擎

## Spec

### 目标与非目标

把获批 SignalSnapshot 转成受约束 TargetPortfolioSnapshot，使用同一决策代码完成现实 A 股回测、Risk R0、双引擎 reconciliation 和 core attribution。

非目标：不含主动 Timing 的非零贡献、不含事件数值增强、不含 OMS 或真实账户；不以高收益替代正确性验收。

### 领域合同

- `PortfolioPolicy`：benchmark、rebalance、AUM/currency、cash、单股/行业/turnover/participation、lot、approval scope；
- `TargetPortfolioSnapshot`：exact Snapshot/prior portfolio/policy/risk/cost versions、target weights/shares/cash、constraint diagnostics、content hash；
- `RiskModelDecisionRecord`：exposure/covariance/specific/total/component/stress/version；
- `BacktestRun` 与 `TradeLedger`：signal time、eligible session、order intent、fill/block reason、inventory、cash、corporate action、fees；
- `AttributionSnapshot`：market/industry/style/selection/cost/residual；timing/event/execution 按事实为 unavailable/not_applicable；
- 金额 Decimal + currency，权重/收益/风险有明确 scale，时间均 timezone-aware；
- 研究回测、Forecast Outcome、Paper/Live 类型不可混用。

### 现实交易规则

- 盘后信号最早下一可交易 session；
- T+1 sellable inventory、100 股 lot、停牌、涨跌停、ST/退市、分红送转配股生效；
- fee/slippage/impact/participation 参数和版本进入 hash；
- blocked/pending/cancelled 不得当成交；
- benchmark、现金和公司行动必须进入 equity closure；
- 内部与外部引擎消费同一 frozen signal/target/policy export。

### API 与前端

- `/api/portfolios/policies|targets|backtests|risk|attribution` 只读查询；执行入口由 Researcher 权限和 idempotency 拥有；
- Construction、Backtests、Risk、Scenarios、Attribution 页面不在浏览器计算权重/风险/归因；
- dual-engine diff 可逐日、逐笔钻取；
- 无 Snapshot 时失败关闭，不生成伪持仓或曲线。

### 决策

- ADR-0006 已冻结 CSI800 总体 benchmark、CSI300/CSI500 分组、RQAlpha、月度基线和 versioned next-session VWAP/cost；
- 风险/集中度上限保持配置化，Gate 前批准。

### 验收

- Top-N 等权和 ER 权重都有手算 fixture；
- T+1/lot/停牌/涨跌停/ST/退市/公司行动/费用 fixture 通过；
- 双引擎差异逐笔分类，超过容差阻断 Gate；
- risk 和 core attribution 闭合；
- 浏览器黄金路径完整；
- 不声称策略科学有效。

## Plan

### Task 1：产品政策 ADR 与合同

预计新增：

- `docs/adr/0006-research-baseline-and-evaluation-policy.md`；
- `platform/src/a_share_platform/domain/portfolio.py`；
- `platform/tests/test_portfolio_policy.py`。

先冻结可配置字段和 D0/D1，不把默认写入领域枚举。

### Task 2：组合构建纯领域核心

预计新增 `domain/portfolio_construction.py`、对应 tests。按 Top-N equal weight → ER weight → prior/cash → constraints → lot/rounding → deterministic residual cash 小步实现。

### Task 3：Risk Model R0

预计新增 `domain/risk.py`、`application/risk_models.py`、`ports/risk.py` 和 tests。先 exposure，再 shrinkage covariance，再 component closure/stress；用 NumPy/SciPy 等独立计算交叉检查。

### Task 4：内部现实回测引擎

预计新增：

- `domain/backtest.py`、`domain/execution_rules.py`；
- `application/backtests.py`、`ports/backtests.py`；
- memory/PostgreSQL/Parquet adapters；
- `tests/test_realistic_backtest_*.py`。

严格按 session → eligibility → intent → fill/block → inventory/cash → valuation 状态机 TDD。

### Task 5：外部引擎 adapter 与 reconciliation

先做 D0 spike/ADR，再新增 `adapters/rqalpha/` 或批准的 engine 目录、frozen export/import 和 diff classifier；外部依赖不进入 domain。

### Task 6：统计、capacity 和 core attribution

新增 portfolio statistics/attribution 纯函数及独立库对照；residual 超阈值失败，未参与项不填 0。

### Task 7：Repository/migration/API

预计 migration `003x_p6_portfolio_backtest.sql`，表进入 `research`，serving 只读 projection；append-only run/target/trade/risk/attribution；API schema 和 OpenAPI 生成。

### Task 8：Portfolio Workspace

新增 `frontend/src/pages/PortfolioWorkspace.tsx` 与 construction/backtest/risk/scenario/attribution features/tests；完成四视口和黄金路径。
页面信息架构、精确原型节点、六态和视觉验收按 PUI-05 执行；P6 领域/API 未完成前，运行时只能展示
真实 blocker，不能用测试或 Figma fixture 生成持仓、曲线、风险或归因。

### 验证

定向测试按新增模块执行；阶段收口执行全量命令、migration 空库/幂等、真实小样本、独立风险统计和 RQAlpha reconciliation。Evidence 新增 `docs/21-p6-implementation-evidence.md`（编号执行时按仓库最新顺延）。
