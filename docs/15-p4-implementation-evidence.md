# P4 实现与验证证据

日期：2026-08-11

范围：`docs/08-detailed-implementation-plan.md` 的 P4 前置数据资格门、P4-W01 首批领域
合同、P4-W02 行业模板和 P4-W03 的两个 company-level baseline。本文只记录已经提交并完成
验证的内容，不把共享工作树中并发但未提交的后续工作包算作 P4 完成。

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

提交：`6948073 feat: define P4 feature contracts`

已实现：

- provider/framework-neutral 的 `FeatureDefinition` 和只由有序 typed inputs 驱动的
  `FeatureFormula`；
- 输入与输出的 unit、ISO currency 和经济 period 兼容检查；
- `unavailable/reject` missing policy，缺失值不以 0 参与公式；
- winsorization、standardization、industry/size neutralization 的方法、参数和版本合同；
- 不可变 `FeatureSnapshot`，其确定性 SHA-256 绑定公式、输入内容、DatasetVersion 和变换版本；
- `LabelSchema/LabelValue` 与生产 feature 使用不同类型和 storage namespace，避免 future label
  混入生产特征合同。

尚未完成：

- winsorization、standardization 和 industry/size neutralization 的横截面统计执行；
- 变换后 snapshot 的 repository、migration、DatasetVersion/lineage 落库；
- label 与生产 feature 的真实物理表、repository 和 API 隔离；
- P4-W02 至 W06 的行业模板、三类因子、统计引擎、Experiment/Approval 和浏览器工作区。

因此 Plan 只勾选已完成的合同项；P4-W01 和 P4 Gate 均未整体通过。

定向 TDD：10 tests。红灯从 `a_share_platform.domain.features` 不存在开始；实现后覆盖纯公式、
单位/币种/期间冲突、missing 不填零、确定性 hash、不可变 snapshot 和 label namespace 隔离。

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

## P4-W03：Fundamental Improvement V0 company-level baseline

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

## 验证证据

两个提交完成后的共享分支验证结果：

- Python：`340 tests passed`；
- 前端：`26 tests passed`；
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

测试计数包含此前已经提交的 P0–P3 和 P3.5 测试，不能全部归因于 P4；本文也不把并发未提交
文件计入完成范围。

## 当前数据阻断与浏览器里程碑

P4 工程可以继续实现合同、统计器和 honest empty state，但以下数据缺口阻断真实广覆盖
历史因子结论和 P4 Gate：

- P2 尚无完整 CSI300/CSI500 历史 Universe，XBSE、2018+ 股本和公司行动链路未完成；
- P3.5 已完成 AkShare current-only 的 5 家 pilot 和 30 家、2018–2025、三表批次，但
  700–800 家结构化主源资格、官方对账和批量覆盖尚未完成；已入库数据只能是
  `normalized_current`，不能作为严格历史证据；
- P4 的真实历史输入仍需满足 W00 的 `pit_verified`、decision-time、覆盖、质量和 lineage 门。

浏览器中的完整 Factor Workspace 到 P4-W06 才验收，包括 Catalog、Experiments、Alpha
Model honest empty state、Timing Lab、Correlation Monitor、Production、统计图和失败实验。
在 W06 前出现页面骨架或 Catalog，不代表完整工作区，更不代表 P4 Gate 通过。

## Gate 结论

截至 2026-08-11，P4 Capability Gate **未通过**。当前完成 W00 数据资格合同、W01 的部分
领域合同、W02 三套行业模板，以及 Quality/Fundamental Improvement 的 company-level baseline；
没有三个因子的真实 PIT 截面计算、独立统计库交叉验证、失败因子生命周期、最小
Reviewer/Approval 或完整浏览器工作区。

测试通过只证明已实现合同按预期工作，不证明任何特征、因子、模型或策略科学有效。
