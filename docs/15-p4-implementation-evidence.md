# P4 实现与验证证据

日期：2026-08-11

范围：`docs/08-detailed-implementation-plan.md` 的 P4 前置数据资格门和 P4-W01 至 W06 工程
能力，以及使用真实开发库执行的三因子资格审计。本文只记录已经提交并完成验证的内容；工程
能力完成与真实 PIT 数据 Gate 分开判断。

P4 建立行业模板、可复用特征层、正式 Factor Lab、统计验证、最小审批和浏览器工作区。
Capability 测试通过不等于特征、因子或投资模型科学有效，不代表有超额收益，也不授权
真实交易、下单、撤单或账户连接。

## P4-W00：严格 PIT 数据资格门

提交：`6cde9ef feat: add P4 data readiness gate`

已实现：

- `FactorStudySpec` 冻结研究窗口、Universe、benchmark、decision-time policy 和各数据域覆盖
  阈值来源；
- 前置数据角色显式包含财务事实、历史 Universe、行业分类、raw 日线、股本、公司行动、
  benchmark 日线和 forward-return label；
- 历史因子证据只接受 `strict_historical + research`；特征输入要求 decision-time cutoff，
  forward label 使用独立 outcome policy；
- 每个绑定必须显式保存 DatasetVersion、`pit_verified`、质量状态、覆盖率、起止范围、
  availability enforcement、完整 lineage 和 warning；
- current 数据、缺失域、覆盖不足、质量失败、研究窗口不完整、时间门未执行或 lineage 不完整
  均失败关闭。

该门只证明系统能够拒绝不合格研究输入。它没有把 P2/P3.5 的 current 数据晋升为 PIT，
也不表示数据库中已经存在满足 P4 Gate 的全量绑定。

定向 TDD：7 tests。红灯从 `a_share_platform.domain.factor_readiness` 不存在开始；实现后
current 冒充历史、缺域、低覆盖、错误 availability policy 和不完整 lineage 等测试转绿。

## P4-W01：FeatureDefinition 与 Snapshot 首批合同

提交：`6948073`、`98d1990`、`40b73bc`

已实现：

- provider/framework-neutral 的 `FeatureDefinition` 和只由有序 typed inputs 驱动的
  `FeatureFormula`；
- 输入与输出的 unit、ISO currency 和经济 period 兼容检查；
- `unavailable/reject` missing policy，缺失值不以 0 参与公式；
- winsorization、standardization、industry/size neutralization 的方法、参数和版本合同；
- 不可变 `FeatureSnapshot`，其确定性 SHA-256 绑定公式、输入内容、DatasetVersion 和变换版本；
- `LabelSchema/LabelValue` 与生产 feature 使用不同类型和 storage namespace，避免 future label
  混入生产特征合同；
- 确定性 Decimal 横截面执行器实现显式版本的 quantile winsorization、z-score standardization
  和 industry/size OLS residual neutralization；外部 Decimal context、输入顺序不会改变结果；
- 缺失行保持 `unavailable`，小样本、常数截面和奇异回归失败关闭；
- `feature_snapshots` 与 `research_labels` 使用独立 append-only PostgreSQL 表、port 和 repository，
  label repository 不能被注入 feature reader，生产 feature repository 不暴露 label 方法。

W01 工程能力已完成。定向复核中 feature transform 为 17/17 tests；FeatureSnapshot/Label
repository、migration 和类型隔离另有独立测试。Ruff、mypy、compileall 和 diff-check 通过。
这些测试不表示已有合格 PIT 截面数据或变换方法具有科学最优性。

## P4-W02：行业模板与 partial Quality baseline

提交：`af126be`、`00858d0`、`4e48462`

- 非金融、银行、制造/消费三套模板已定义通用层、行业层、不可比字段和公司例外流程；
- 阈值无内置默认数值，必须绑定来源、版本、hash、有效期和审批；
- 非金融/制造使用经营应计、非金融 ROE 和四期净利率稳定性；银行使用贷款损失准备应计、
  银行 ROE 和四期净息差稳定性，跨行业字段显式不可比；
- Quality V0 已做 4 家手算，缺失组件使结果 `unavailable` 且不填零；Size/行业/Beta 只作为
  exposure；
- 稀释、审计/监管、退市和财务异常仍是 coverage gap，因此 Quality 明确保持
  `coverage_status=partial`、`scientific_status=not_evaluated`。

定向 TDD：行业模板与 Quality 最新回归 16/16 通过；Ruff、mypy、compileall 和 diff-check
通过。这证明模板和 baseline 合同按预期工作，不代表 Quality 因子已完成 PIT 截面验证。

## P4-W03：三类因子的 company-level baseline

提交：`1d5cd70`

- provider-neutral 纯函数分别输出营收、利润、利润率和现金流的带单位 level、trend、
  acceleration；不同单位不伪合成单一总分；
- 显式区分 YOY/QOQ、TTM/单季度及比较期间；季节性未控制、基数效应未调整或一次性项目
  未剔除时，对应 component 为 `unavailable`；部分组件可用时为 `partial`，不填零；
- breadth 是可用组件中正 acceleration 的比例；confidence 是组件可比覆盖率，不是预测概率；
- current 结果 `historical_eligible=false`；strict 结果要求 input 为 `strict_historical +
  pit_verified`，并强制验证 `latest_source_available_at <= decision_time`；
- DatasetVersion、source/mapping/metric definition、fact id 和内容 hash 进入 provenance；
- Size/行业/Beta 只随结果携带，不进入公司级公式；scientific status 固定为 `not_evaluated`。

定向 TDD：4 个手算场景与 4 个合同测试，8/8 通过；Ruff、mypy、compileall 和 diff-check
通过。该 baseline 尚未实现财报修订触发的 Snapshot repository、PIT 截面计算或科学验证。

提交：`7abcfe3`

- Valuation Expectation Gap V0 使用区间而不是伪精确点值表达 relative valuation、fundamental
  anchor 和 expectation gap；
- 银行行业的 FCF yield、EV/EBIT 明确为 `not_applicable`，不填零、不跨行业硬比较；
- 4 家手算覆盖行业模板、missing expectation、unit/period/currency、假设和失效条件；
- current 输入不能被重标为 strict，strict 路径逐项检查 source `available_at <= decision_time`。

P4-W03 的三个公司级 baseline 都已实现，但 Plan 中三个因子项仍不勾选，因为每项还要求真实
PIT 截面计算。公司级手算、类型合同和测试通过不等于因子已经完成或有效。

## P4-W04：统计引擎与独立库交叉验证

提交：`cf70147`、`117d4ae`、`a298335`、`7d939dd`、`d962344`

已实现：

- Pearson IC、带 ties average-rank 的 Rank IC、HAC Newey-West、可复现 circular block
  bootstrap CI；
- quantile/monotonicity、decay、turnover、coverage；
- Fama–MacBeth 逐期 OLS 和系数聚合、regime/subperiod 稳健性；
- Benjamini–Hochberg/FDR family、walk-forward、purge/embargo；
- 所有 strict 统计输入检查 `pit_verified` 与 decision-time，current 只能产生带 warning 的研究
  结果，不能冒充历史检验；缺失、小样本、常数截面和秩亏显式 `unavailable`；
- 独立适配器使用 SciPy 检查 Pearson/Spearman IC，使用 statsmodels 检查 HAC 和
  Fama–MacBeth；报告绑定输入 SHA-256、主公式版本、adapter/库版本、绝对/相对容差和逐组件
  误差；缺依赖为 `unavailable`，超容差为 `mismatch`。

独立库交叉验证的 `scientific_status` 固定为 `not_evaluated`。数值一致只能支持实现正确性，
不能证明样本、经济机制、稳定性、成本后收益或可投资性。

## P4-W05：Experiment、Reviewer 与 Qlib exchange

提交：`f754957`、`5972b0a`、`ddfe54a`、`21aa1e1`、`5ce6e71`

- `ExperimentSpec/Run` 冻结数据、代码、环境、feature/label、参数、metrics 和 artifacts；失败
  run 与成功 run 一样 append-only 保存；
- `ValidationReport`、waiver、PromotionApproval、FactorVersion lifecycle 和
  `research_backtest/shadow/paper/limited_live` scope 均为显式合同；
- `0027_factor_promotion_reviews.sql`、PostgreSQL repository 和 API 提供最小 Reviewer 服务端
  路径；只接受服务端认证 principal 的 Reviewer/Administrator，角色 header 不能冒充身份；
- approval 不能覆盖失败科学门，不授予账户或下单权限；immutable review id 不能重绑证据；
- Qlib export 冻结可复现合同和验证血缘；Recorder import 只读取显式、版本化 schema，并验证
  metric/artifact/failure 字段、内容 hash 和 run binding；缺少 Qlib SDK 时显式 `unavailable`。

这些 adapter 不把 Qlib 当数据真源，也没有连接交易账户或任何下单接口。

## P4-W06：真实 Experiment API 与 Factor Workspace

提交：`7838aa4`、`57a894b`、`5d36a28`

- Catalog、Experiments、Alpha Model、Timing Lab、Correlation Monitor、Production 六个页签；
- Workspace 直接读取 `/api/experiments/runs`，保留 append-only failed runs；没有运行时假实验；
- Rank IC、CI、turnover、coverage 显式显示；只有绑定真实 validation series 时才画 quantile/
  decay 图，不从 artifact hash 或缺失值生成图形；
- multiple-testing family 和样本外标识未绑定时显示“未绑定”，不伪造默认值；
- `FactorStudyNotReady` 默认显示“PIT 输入资格未通过”、阻断数和阶段，完整原始原因可展开，
  没有为了视觉整洁删除失败证据；
- Gate 文案明确审批和独立统计能力已就绪，当前阻断是冻结窗口 `pit_verified` 输入。

`5d36a28` 同时重新生成 Reviewer 路径对应的 OpenAPI 前端合同。

## 真实三因子资格审计与失败产物

提交：`1b1f279`、`8d9884d`；migration：`0028_factor_qualification_audits.sql`。

对 2018–2025 冻结窗口的 Quality、Valuation Expectation Gap、Fundamental Improvement 执行
同一套真实 PostgreSQL 资格查询。结果为：

- 最新三条 ExperimentRun 全部 `failed`，metrics 为空；三份 ValidationReport 都不可晋级；
- 36 个 validation checks 中 PASS=0；三个 FactorVersion 均保持 `draft`；
- 首次 execute 持久化不可变 audit、role DatasetVersion、run、report 和 artifact，重复 execute
  `writes_performed=false`；
- 浏览器中旧三条和最新三条失败 run 共 6 条，按 append-only 保留；
- 没有计算因子 score、IC、RankIC、分层收益或晋级结果。

资格查询观察到的真实输入范围：

- 冻结窗口 PIT 财务 6 条、1 家；raw bars 4,860 条、20 家；股本 23,934 条、799 家；
- 公司行动 7,094 条，覆盖 800/800，但 trust ceiling 为 `normalized_current`；
- PIT-qualified 行业为 0；另有 current-only 1,258 条，仅覆盖 2026-08-10 至 2026-08-11；
- forward labels 为 0；CSI800 benchmark 为 0；
- 历史 Universe 不是一个覆盖整个窗口且 `pit_verified` 的 CSI800 UniverseVersion。

因此本工作包产出的是真实“失败/不晋级”产物，不是用户要求的三个真实 PIT 截面成功结果。
这是数据缺口的证据，不应被改写成工程失败或科学失败。

## 验证证据

最终共享分支验证结果：

- Python：`636 tests passed`；
- 前端：`32 tests passed`；
- Python compileall、Ruff、mypy 通过；
- 前端 ESLint、TypeScript/Vite build 通过；
- `git diff --check` 通过。

对应命令：

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/ruff check src tests
PYTHONPATH=src .venv/bin/mypy src
npm --prefix frontend run lint
npm --prefix frontend test -- --run
npm --prefix frontend run build
git diff --check
```

统计交叉验证定向复核为 20/20；Factor Workspace 定向复核为 6/6。测试计数包含此前已经
提交的 P0–P3 和 P3.5 测试，不能全部归因于 P4。

## 当前数据阻断与浏览器里程碑

P4 工程工作包已经收口，但以下数据缺口阻断真实广覆盖历史因子结论和 P4 Gate：

- P2 按用户要求暂停；尚无覆盖 2018–2025 的完整 CSI300/CSI500 历史 Universe 和 CSI800
  benchmark/forward label，XBSE 链路也未完成；
- P3.5 已完成 CSI500 当前 500 家、2018–2025 年末三表的 35,505 条 observation 和 12,000
  份 checkpoint/receipt，但它们是 `normalized_current + current_research`，不是 PIT；
- P4 的真实历史输入仍需满足 W00 的 `pit_verified`、decision-time、覆盖、质量和 lineage 门。

2026-08-11 在 `http://127.0.0.1:5173/factors?tab=experiments` 对真实 API 完成浏览器验收：六个
页签均可切换；Experiments 显示 6 条真实失败 run，摘要为 33/34 项 PIT 阻断并可展开完整
证据；Catalog 显示三个 `not_evaluated` baseline；Alpha/Timing/Correlation/Production 都是
honest blocked/empty state。最终刷新后的控制台只有 Vite debug 和 React DevTools info，没有
error。浏览器验收证明页面接线和失败态可见，不证明 P4 Gate 或模型有效。

## Gate 结论

截至 2026-08-11，P4 W00–W06 的工程能力已经完成，但 P4 Capability Gate **未通过**。
独立统计交叉验证、失败生命周期、Reviewer/Approval、Qlib exchange 和浏览器工作区均已完成；
真正未完成的是三个因子的真实合格 PIT 截面及其统计结果。现有真实资格审计已正确失败关闭，
不能拿 current 数据、测试 fixture 或空图表替代。

测试通过只证明已实现合同按预期工作，不证明任何特征、因子、模型或策略科学有效。
