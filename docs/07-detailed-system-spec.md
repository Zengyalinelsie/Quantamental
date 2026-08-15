# A 股基本面量化平台详细 Spec

> 文档状态：Draft for User Review
>
> 版本：0.9.2
>
> 日期：2026-08-15
>
> 产品范围：A 股优先、多头选股、主动市场择时、事件研究、现实回测、未来模拟盘与实盘
>
> 前端产品/交互真源：`docs/18-product-blueprint-and-prototype.md` 与目标页面精确 Figma node
>
> 前端 token/组件 provenance：用户原项目最新本地工作树中的机构研究工作台风格
>
> 本文是需求与验收真源；实现顺序见 `08-detailed-implementation-plan.md`

## 0. 阅读方法

本文中的 `SPEC-xxx` 是可追踪需求。每项需求都有验收标准；没有满足验收标准的代码或页面不能标记为完成。

文档使用以下词义：

- `MUST`：缺失即不能通过阶段 Gate；
- `SHOULD`：默认实现，只有记录 ADR 才能偏离；
- `MAY`：可选增强，不阻塞当前阶段；
- “Production 版本”：通过某一用途审批、可被正式流程复用的不可变版本；是否影响账户仍由 `deployment_stage` 和 Approval scope 决定；
- “严格回测”：只使用历史当时可知并通过 PIT 验证的数据。

本文把两类 Gate 分开：

- `Capability Gate`：证明平台能正确运行、能诚实保存失败结果；
- `Promotion Gate`：证明某个数据集、因子、模型或策略有资格进入指定用途。

完成 Capability Gate 不代表模型有效或获准实盘。科学结果可以失败，平台阶段仍可完成；失败对象不得晋级。

## 1. 已确定的产品决策

| 决策 | 结果 |
|---|---|
| 首个市场 | A 股 |
| 主要投资方向 | 多头选股 |
| 市场择时 | 必须研究主动预测，不只做被动风险控仓 |
| 实盘目标 | 平台必须为未来实盘设计，但按 Shadow → Paper → Limited Live 晋级 |
| 本金 | 不是平台常量，由 Portfolio/Account Policy 配置 |
| 前端风格 | 使用 `docs/18` 与精确 Figma node 的产品结构，复用用户原项目机构级 token/组件 provenance |
| DSA 的角色 | 产品体验、Agent、报告、新闻与通知供体；不是数据权威 |
| Legacy 的角色 | PIT、版本、因子、信号、组合和现实回测合同供体 |
| 架构 | 独立模块化单体；不直接合并两个来源运行时 |
| Agent 权限 | 无直接交易权限，无权提升数据可信状态 |
| 回测引擎 | 内部 A 股规则引擎为领域真源，成熟外部引擎用于对照 |
| Qlib | 研究执行适配器，不是权威数据仓库 |

## 2. 产品目标与边界

### SPEC-001：六个投资问题

平台 MUST 形成以下六个可审计输出，而不只是六个页面：

1. 哪些公司值得投资：行业化公司质量；
2. 当前价格是否有吸引力：估值、隐含预期和预期差；
3. 公司是否改善或恶化：财务、经营数据和分析师预测修正；
4. 新事件改变了什么：新闻、公告、研报和供应链影响；
5. 当前整体股票仓位应是多少：主动市场择时与被动风险基线；
6. 结论能否真实执行：组合、风险、成本、订单、成交和对账。

验收：每个问题都有版本化领域对象、API、前端入口、`data_mode`/`deployment_stage` 说明和不可用原因。

### SPEC-002：四个内部支撑问题

平台 MUST 额外回答：

- 当时究竟知道什么；
- 前四问如何合成为统一投资判断；
- 结果为何与预期不同；
- 数据、模型或执行是否正在失效。

验收：存在 PIT 查询、`InvestmentView`、归因报告和漂移/失效监控。

### SPEC-003：非目标

第一版 MUST NOT：

- 承诺盈利或输出“必涨”结论；
- 让 LLM 生成权威财务数值或直接下单；
- 用当前股票池代替历史股票池；
- 用当前财务字段回填历史回测；
- 一开始构建完整商业 Barra、微服务或高频撮合器；
- 把报告命中评估叫作组合回测；
- 为了页面完整展示演示数据；
- 把 AUM、股价上限、持仓数写成全局常量。

### SPEC-004：用户与权限角色

平台定义以下角色：

| 角色 | 权限 |
|---|---|
| Viewer | 读取已发布研究和运行状态 |
| Researcher | 建实验、运行研究、提交晋级申请 |
| Data Operator | 数据摄取、回填、质量处理，不改投资审批 |
| Reviewer | 审核因子、模型、研究结论和数据例外 |
| Portfolio Manager | 冻结组合政策、批准目标组合 |
| Trader/Execution Operator | 审核并发送订单意图、处理异常 |
| Administrator | 用户、权限、配置和系统治理 |
| Agent | 受限工具调用主体，不是人类角色，不持有交易权限 |

验收：权限由服务端执行；前端隐藏按钮不能替代权限校验；关键动作有审计记录。

## 3. 运行模式、时间和决策周期

### SPEC-005：数据模式与部署阶段是两个正交轴

不能把“数据是否 PIT 合格”和“结论是否影响账户”塞进同一个 mode。平台 MUST 分别保存：

| 轴 | 值 | 含义 |
|---|---|---|
| `data_mode` | `current_research` | 可使用 `normalized_current` 或 `pit_verified`，显式显示可信状态 |
| `data_mode` | `strict_historical` | 仅使用 `pit_verified`，用于严格历史研究和回测 |
| `deployment_stage` | `research` | 探索结果，不作为正式前瞻输出 |
| `deployment_stage` | `shadow` | 按真实时钟生成并冻结，但不影响账户 |
| `deployment_stage` | `paper` | 仅获批冻结版本，可影响模拟账户 |
| `deployment_stage` | `limited_live` | 仅获批冻结版本，可在受限政策和人工授权下影响真实账户 |

有效组合由服务端 use case 决定。例如，严格回测通常是 `strict_historical + research`；每日前瞻预测通常是 `current_research + shadow`。历史回放不能伪装成 Shadow，Current 数据不能用于 Strict。

验收：API、运行账本和前端分别显示两个轴；非法组合 fail closed；不能通过前端参数提升数据资格或部署阶段。

### SPEC-006：三类时间

所有历史相关事实 MUST 区分：

- 经济时间：事实描述哪个报告期或事件期；
- 市场可用时间：`available_at`，最早可进入决策的时点；
- 系统知识时间：`known_from/known_to`，仓库何时保存某版本。

所有 datetime MUST 带时区。交易日、盘前、盘中、盘后必须按交易所日历解析。

验收：修订日前查询返回旧版本；修订可用后返回新版本；系统回填不会修改历史市场可用时间。

### SPEC-007：决策期限

第一版标准期限：

| 对象 | 标准期限 |
|---|---|
| 基本面选股 | 20、60、120 个交易日 |
| 主动择时 | 1、5、20、60 个交易日 |
| 事件 | 1、3、5、20、60 个交易日，按事件类型选择 |
| 组合再平衡 | 月度基线 + 事件触发；最终由 Portfolio Policy 配置 |
| 风险监控 | 日频；实盘执行风险为事件驱动/近实时 |

验收：收益、风险、成本、预测和归因必须标明同一或可换算期限，不允许混用年化和区间值而不注明。

## 4. 系统总体架构

### SPEC-008：模块化单体与依赖方向

第一版 MUST 使用模块化单体：

```text
Frontend / API / Scheduler
        ↓
Application Use Cases
        ↓
Domain: Data → Research → Decision → Portfolio → Execution
        ↑
Adapters: Provider / Storage / Broker / LLM / External Engines
```

领域层不能 import FastAPI、SQLAlchemy、供应商 SDK、LLM SDK 或来源仓库代码。

验收：依赖守卫测试通过；来源仓库保持只读；所有外部能力通过 port/adapter。

### SPEC-009：存储职责

- PostgreSQL：身份、PIT 事实、元数据、版本、运行、审批、组合、OMS；
- Parquet：价格面板、特征、标签、风险与回测明细；
- DuckDB/Polars：本地研究计算；
- S3/MinIO 兼容对象存储：原始响应、公告、研报、模型和实验 Artifact；
- Redis MAY 用于短缓存/队列，但不得成为权威账本。

验收：任意生产数字能追到原始对象、DatasetVersion、公式/模型、代码和运行 Artifact。

## 5. 数据与证据规格

### SPEC-010：公司、证券和挂牌分离

核心身份：

- `Company`：经济实体；
- `Security`：股权证券；
- `Listing`：证券在某交易所的挂牌代码；
- `IdentifierHistory`：代码、名称和标识变化；
- `CorporateRelationship`：母子公司、合并、分拆等关系。

验收：代码变化不产生新公司；一家公司多地挂牌不合并价格；跨期查询返回当时有效身份。

### SPEC-011：历史股票池

`UniverseVersion` MUST 保存：

- 规则版本和基准；
- 成员有效区间；
- 纳入/排除原因；
- 上市、退市、ST、停牌和可交易条件；
- 历史行业分类；
- 生成所用 DatasetVersion。

验收：退市股票不会从历史样本消失；任意历史日可重建研究池和可交易池，两者允许不同。

### SPEC-012：行情与公司行动

MUST 保存：

- 原始不复权 OHLCV、成交额；
- 复权因子独立表；
- 涨跌停价和状态；
- 停牌、ST、上市/退市状态；
- 分红、送转、拆合股、配股；
- 总股本、流通股本、自由流通股本；
- 交易日历和临时休市。

验收：历史市值使用当时股本；原始价格和复权序列可重建；公司行动不会制造虚假收益。

### SPEC-013：PIT 财务事实

`FactObservation` MUST 至少包含：

- company/security、metric code、value、unit、currency；
- report period、period type、statement type；
- announced_at、available_at；
- revision_sequence；
- known_from、known_to；
- provider、source field、raw object hash；
- trust state、quality state、mapping version。

`ProviderFieldMapping` 的用途资格 MUST 独立、显式且可持久化，至少区分
`current_research`、`strict_historical` 和 `production`。调用方必须声明目标用途；未声明、
未获批或未知用途一律 fail closed。`production` 资格不能替代 `current_research` 资格，反之亦然；
模糊映射不得获得 `production` 资格。仅获批 current 研究的免费源映射（包括 AkShare）不得被
提升为 strict historical 或 production。Mapping 的 `production` scope 只表示该字段转换合同
具备正式流程资格，不授予数据 PIT 可信、模型晋级、部署阶段、账户或交易权限。

同一事实的多个供应商观察并存；权威选值规则版本化。缺失、无权限、冲突不能显示为 0。

验收：严格历史查询只返回 `available_at <= decision_time`、系统时点可见且 `pit_verified` 的最高公开修订。

### SPEC-014：数据可信与质量

可信状态只有：`raw`、`normalized_current`、`pit_verified`。提升可信状态需要治理运行，不允许人工直接改标签。

质量检查包括：schema、单位、币种、范围、平衡关系、跨表关系、时间顺序、重复、缺失、异常、来源覆盖、修订连续性和抽样对账。

验收：质量结果版本化；严重错误阻断下游；警告传播到 InvestmentView 和页面。

### SPEC-015：数据来源与许可

每个数据域 MUST 定义主来源、备用来源、许可、字段级权限、速率限制和保存期限。Fallback 只能生成新的来源观察，不能静默覆盖权威值。

第一阶段来源选择仍为待决策项，必须通过 Data Source ADR；免费源可用于原型，未来实盘必须评估稳定性、PIT 完整性和使用许可。

验收：Provider Registry 可回答每个字段来自哪里、能否存储、能否回测、能否对外展示；
Mapping Registry 可回答每个 provider 字段映射获准用于 current、strict 或 production 中的
哪些用途，且数据库和应用服务执行相同的 fail-closed 范围约束。

## 6. 基本面研究规格

### SPEC-016：公司好坏的三层标准

公司质量由三层组成：

1. 全市场底线：财务真实性、治理、偿债、现金流、资本回报；
2. 行业模板：行业专属指标和阈值；
3. 公司例外：生命周期、商业模式、会计口径和重大事件调整。

排名 SHOULD 先在行业内标准化，再由组合控制行业暴露。跨行业统一分数只作为合成展示，不代替行业语义。

验收：银行和制造业不能使用完全相同的质量公式；每个特征能显示通用/行业/特例来源。

### SPEC-017：第一批基本面特征

第一批 MUST 覆盖：

- 质量：ROIC/ROE、经营现金流/利润、应计、毛利率/净利率稳定性、杠杆；
- 估值：E/P、B/P、FCF yield、EV/EBIT 或行业适用口径；
- 改善：营收、利润、利润率、现金流的趋势和加速度；
- 安全：偿债、稀释、审计/监管、退市与财务异常；
- Size/流动性/Beta：作为风险暴露，不直接等同公司质量。

验收：所有公式为纯函数，输入、单位、缺失处理、winsorize、标准化和 neutralization 版本化。

### SPEC-018：估值与市场预期

估值模块 MUST 同时提供：

- 历史/行业/同业相对估值；
- 至少一种绝对或基本面锚定估值；
- 当前价格隐含的增长、利润率或资本回报预期；
- 分析师一致预期及其修正（数据可用时）；
- 情景和敏感度，不输出伪精确单点目标价。

验收：估值结果包含区间、关键假设、可比公司版本、币种和失效条件。

### SPEC-019：改善与恶化

模块 MUST 区分：同比、环比、TTM、单季度、季节性、基数效应和一次性项目；输出 level、trend、acceleration、breadth 和 confidence。

验收：不能把季度季节性误当同比改善；财报修订会重算受影响 FeatureSnapshot，而不篡改旧版本。

## 7. 因子、模型与科学验证

### SPEC-020：实验可复现

`ExperimentSpec/Run` MUST 冻结：研究问题、数据/股票池/特征/标签版本、时间切分、代码 SHA、参数、随机种子、环境、指标、Artifact 和状态。失败实验同样登记。

验收：相同输入可重放相同确定性结果；无法重放的运行不得晋级。

### SPEC-021：因子验证门

单因子至少需要：

- IC/Rank IC；
- HAC t 或 block-bootstrap CI；
- 分层收益和单调性；
- 衰减、换手、覆盖；
- 行业/Size 中性；
- Fama–MacBeth；
- 子期间、市场状态和参数稳定性；
- 多重检验/FDR；
- Walk-forward 真正样本外；
- 成本和容量解释。

验收：ValidationReport 逐项 pass/fail/waived；waive 必须有人类理由且不能绕过 PIT 和样本外硬门。

### SPEC-022：选股与 Alpha 模型验证门

多因子/机器学习模型 MUST 与等权、随机、简单价值、单因子和简单线性模型比较；时间重叠时使用 purged/embargo；报告 bootstrap CI、参数敏感度、regime、成本和容量。

验收：复杂模型没有样本外增量时不得因为样本内收益更高而晋级。

### SPEC-023：模型生命周期

生命周期：`draft → research → shadow → candidate → production → suspended → retired`。

晋级绑定数据、代码、模型、验证和审批版本。Production 版本不可原地修改，只能产生新版本或回滚。

Approval MUST 带用途范围，至少区分 `research_backtest`、`shadow`、`paper` 和 `limited_live`。获准研究回测不等于获准模拟盘或实盘。

验收：生产 API 只读取获批 production 版本；rollback 有审计和可重放 Artifact。

## 8. 统一投资判断与主动择时

### SPEC-024：InvestmentView

`InvestmentView` 是前四个公司问题进入组合的唯一桥梁，包含：

- security、decision_time、horizon；
- expected return point/p10/p50/p90；
- downside/tail risk；
- quality、valuation expectation gap、fundamental revision、event adjustment 分项；
- confidence、catalysts、invalidators；
- evidence、dataset、feature、model 和 run versions。

每个分项 MUST 具有 `status = quantified | constrained | unavailable | not_applicable`。只有 `quantified` 分项进入数值闭合；`constrained` 只影响约束或置信度；`unavailable` 不能被解释为“影响为零”；`not_applicable` 必须有理由。分项贡献与显式 residual MUST 和点估计闭合。无法量化的判断可作为 evidence/constraint，不得硬编伪数字。

验收：组合层不直接读取 LLM 文本、新闻情绪或未版本化页面字段。

### SPEC-025：Expected Return Compiler

第一版使用可解释线性/分层合成作为基线，复杂模型必须证明增量。Compiler MUST 统一期限，防止把长期质量分和单日事件分直接相加。

验收：每个贡献可解释，残差显式列出，预测校准和 realized outcome 可追踪。

### SPEC-026：主动 Timing Forecast

`TimingForecast` MUST 包含：

- benchmark/universe；
- 1/5/20/60 日上涨概率和收益分布；
- 波动、回撤或尾部风险预测；
- 静态仓位、被动波动率仓位基线；
- 主动调整建议及置信区间；
- model/run/version、模型生命周期、`deployment_stage` 和 Approval scope。

验证包括 AUC/平衡准确率、Brier、log loss、概率校准、HAC、适用时 Diebold–Mariano、成本后效用和相对静态/被动基线增量。

验收：主动预测必须做；在通过生产门前只记录 Shadow，不影响实际目标仓位。

## 9. 新闻、事件、研报与供应链

### SPEC-027：Document 与 Event Ledger

文档保存原文/合法快照、URL、来源、published_at、fetched_at、available_at、hash、语言和版本。Event 是跨来源去重后的事实对象，不等同一篇新闻。

验收：可以重建某历史时点已知事件；文章更正/撤回不会覆盖旧版本。

### SPEC-028：Agent 事件处理

Agent MAY：提取实体、事件、事实主张、影响路径、上下游传播、期限、置信度、反证和待核验项。

Agent MUST NOT：

- 自己认定财务数值为真；
- 修改 published/available time；
- 提升 trust state；
- 直接生成生产权重或订单；
- 使用无引用结论进入 InvestmentView。

验收：每个 Agent 输出绑定模型、prompt、tool inputs、citations、原始响应和解析版本。

### SPEC-029：事件影响和供应链传播

`ImpactHypothesis` 包含 source event、affected entity/security、收入/成本/利润率/估值/风险路径、方向、幅度区间、期限、置信度和 invalidators。供应链边有来源和有效区间。

事件研究使用市场/行业/因子调整 AR/CAR、匹配样本、clustered/bootstrap SE、重叠事件和多重检验。

验收：情绪正负分不能单独成为事件 Alpha；上下游影响必须显示传播路径和不确定性。

## 10. 组合、风险和回测

### SPEC-030：组合输入与输出

组合输入仅限与目标用途相匹配且已获批的 `InvestmentView/SignalSnapshot`、`TimingForecast`、RiskModelVersion、CostModelVersion 和 PortfolioPolicy。严格研究回测可读取获批为 `research_backtest` 的版本；Paper/Limited Live 只能读取相应部署范围的版本。

若主动 Timing 尚在 Shadow，组合 MUST 使用获批静态/被动仓位基线，Shadow Forecast 只能并排记录，不能进入目标权重。未完成的事件分项不得伪装成零影响。

验收：目标权重总和、现金、约束、预期风险/收益、换手和版本闭合。

### SPEC-031：可配置产品政策

以下均为配置而非平台常量：benchmark、AUM、持仓数、单股/行业上限、现金、跟踪误差、换手、参与率、整手、再平衡和审批层级。

验收：同一研究信号可由不同 PortfolioPolicy 生成不同但可解释的组合。

### SPEC-032：风险模型分级

- R0：行业、Size、Beta、收缩协方差和基本约束；
- R1：自建 A 股行业/风格风险模型；
- R2：商业/外部模型对照。

验收：R0 不阻塞第一条黄金链路；每个目标组合显示 absolute 和 benchmark-relative 暴露、风险贡献和压力情景。

### SPEC-033：回测类型隔离

系统分别命名并存储：

- Data Replay Test；
- Factor Evaluation；
- Stock Selection Backtest；
- Timing Backtest；
- Event Study；
- Execution Simulation；
- Forecast Outcome Evaluation；
- Live Replay/Reconciliation。

验收：页面和 API 不允许统一叫“回测”而不显示类型；DSA 能力迁为 Forecast Outcome Evaluation。

### SPEC-034：现实 A 股回测

MUST 处理：次交易日成交、T+1 可卖库存、整手、佣金、最低佣金、印花税、过户费、滑点、参与率/冲击、停牌、涨跌停、ST、分红送转、配股、退市、现金和 benchmark。

同信号 SHOULD 在内部引擎和 RQAlpha/LEAN 之一运行，差异逐笔解释。

验收：不存在用盘后才生成的信号按当日收盘成交；被阻塞订单有原因且不会静默消失。

### SPEC-035：组合统计门

报告至少包括累计/年化收益、Alpha/Beta、Sharpe/Sortino/Calmar、最大回撤、TE/IR、换手、成本、容量、风险贡献、压力、bootstrap CI、PSR/DSR 和子期间。

验收：同时展示成本前/后与基准；统计显著但不可成交或经济无意义的结果不能晋级。

## 11. OMS、模拟盘和未来实盘

### SPEC-036：执行状态机

```text
TargetPortfolioSnapshot
→ OrderIntent
→ PreTradeRiskCheck
→ Approval
→ BrokerOrder
→ Acknowledgement/Reject
→ PartialFill/Fill/Cancel
→ Position/Cash Reconciliation
```

验收：状态转换合法、幂等、防重复下单；任何失败可恢复或人工处理。

### SPEC-037：研究与交易隔离

研究服务不能调用 Broker Adapter。只有 Execution Application Service 在权限、风险和审批通过后才能发送订单。默认环境为只读/模拟。

验收：Agent token 和 Researcher 权限无法调用下单接口；Live 需要独立配置、账户授权和 kill switch。

### SPEC-038：对账与执行归因

目标、订单、成交、持仓和现金 MUST 日内/日终对账；计算 implementation shortfall、滑点模型误差、成交率、拒单原因和费用偏差。

验收：账不平时停止新的自动订单并产生 Incident，不允许用人工修改数字掩盖。

## 12. 监控、归因与治理

### SPEC-039：闭合归因

收益归因至少分解：市场、行业、风格、选股、主动择时、事件、成本和执行。归因和实现组合收益在容差内闭合。

归因 schema 从第一版保留全部分项，但允许尚未参与某次策略的分项标记为 `not_applicable`；只有策略明确没有该暴露时才可记为 0。模块尚未实现或证据缺失时应标记 `unavailable`，不能用 0 掩盖。P6 的选股回测只能完成 core attribution；包含 Timing、事件和真实执行后的 unified attribution 才满足本 Spec 的完整验收。

验收：无法闭合时标记 failed，不发布“解释性”图表冒充闭合归因。

### SPEC-040：漂移和失效监控

监控：数据覆盖/新鲜度、特征分布、IC、预测校准、风险暴露、换手/成本、事件模型、Agent 解析、订单/对账和系统 SLO。

验收：告警有 owner、severity、首次时间、影响对象、处置状态和 runbook。

### SPEC-041：版本、审批和 Artifact

所有生产发布冻结：DatasetVersion、UniverseVersion、FeatureSnapshot、ModelVersion、Risk/Cost Model、PortfolioPolicy、代码、环境、ValidationReport、Approval 和 Artifact hash。

验收：失败实验保留；生产版本不可原地修改；审计可以重放某日结论。

## 13. 前端详细规格

前端交付必须同时区分：

- `Design Parity`：与精确 Figma node 或批准的响应式合同一致；
- `Runtime Product`：真实 API 驱动 loading/error/empty/partial/unavailable/ready，且权限、证据和上下文正确；
- `Domain/Capability`：对应领域、存储、API、工作流和真实小样本满足阶段 Gate。

一个结论通过不自动提升另外两个。当前差距审计和跨阶段计划分别见
`docs/22-prototype-runtime-gap-audit.md` 与 `docs/plans/track-00-prototype-runtime-delivery.md`。

### SPEC-042：前端技术栈

采用用户原项目技术栈：

- React 19 + TypeScript；
- Vite 7；
- Ant Design 6 + ProTable；
- TanStack Query；
- Zustand；
- Less Modules；
- Recharts。

不引入 Next.js、第二套 Design System 或来源仓库运行时依赖。旧 `frontend.md` 中“Chart.js”描述被实际 package 和现有 Recharts 实现取代。

任何目标页面设计到代码前 MUST 读取精确 Figma node 的 design context，检查并复用现有组件/token，
再适配为本项目 React/AntD/Less 实现。Figma 参考代码不是可直接复制的运行时代码。精确节点不可读时，
除仓库已有对应可恢复 SVG 外，不得仅凭缩放截图宣称高保真实现完成。

验收：单一应用、单一 token 系统、单一数据请求和本地状态边界；目标页面记录 Figma file/node、
viewport、状态和允许差异。

### SPEC-043：视觉令牌真源

采用用户原工作树最新 `tokens.less`：

| 角色 | 值 |
|---|---|
| Primary | `#2F5EA8` |
| Primary hover | `#244C8A` |
| Layout | `#F3F5F7` |
| Container | `#FFFFFF` |
| Elevated | `#F7F8FA` |
| Subtle | `#ECEFF3` |
| Border | `#C8CDD4` |
| Secondary border | `#DEE2E7` |
| Text | `#18202A` |
| Secondary text | `#4E5968` |
| Tertiary text | `#727D8B` |
| Radius | `3px` |
| Font | `PingFang SC, ui-sans-serif, system-ui, sans-serif` |

语义色分四组：数据质量、审批、A 股涨跌、告警严重度。颜色不能跨组复用语义，也不能只靠颜色传达状态。

验收：页面不能私自定义业务色；无全局卡片阴影；圆角 0–4px；红色只用于 A 股上涨、严重风险或破坏性操作的明确语义。

### SPEC-044：机构级页面密度

- 表格、列表和时间线优先于大卡片；
- 单屏桌面 SHOULD 展示至少 12–15 条核心记录；
- 数字使用 `NumericCell`、tabular nums、右对齐；
- Card/PageHeading 不使用装饰性图标；
- ProTable 提供列设置、密度、刷新、排序和筛选；
- 可分享状态写入 URL query；个人偏好可写 local storage；
- 所有空状态说明真实原因和启用条件，不展示假数据。

验收：静态合同测试和 320/768/1024/1440 视觉回归通过；1440 有独立高保真 Frame 时必须做精确
设计对照，不能只检查无溢出或“风格接近”。三档没有独立 Figma Frame 时按批准的响应式合同验收，
并明确记录这是运行时重排证据而非 Figma Frame parity。

### SPEC-045：全局 Shell

- 品牌：`FQ / Fundamental Quant / 基本面量化研究平台`；
- 桌面侧栏展开 280px，收起 72px，状态持久化；
- 移动端使用独立 Drawer；
- Header 显示全局证券搜索、研究时点、运行模式、股票池/范围和环境；
- Header 将 `data_mode` 与 `deployment_stage` 分开显示，不能合成一个含糊的模式标签；
- 内容区无页面级横向溢出，宽表只在自身容器滚动；
- 键盘可操作，有可访问名称和焦点状态。

验收：刷新恢复侧栏；移动 Drawer 不受桌面折叠状态影响；测试股票不做默认选择。

### SPEC-046：六项一级导航

一级导航固定为：

1. 今日工作台 `/desk`；
2. 研究 `/research`；
3. 因子 `/factors`；
4. 组合 `/portfolios`；
5. 监控 `/monitoring`；
6. 数据与管理 `/system`。

报告/Artifact 作为各上下文操作，不设置一级“报告中心”。Agent 属于数据与管理，不设独立一级入口。

验收：一级菜单恰好六项；旧路径使用显式 redirect，不出现 404。

### SPEC-047：工作台与研究页面

`/desk` 高密度展示：数据健康、最新信号/排名变化、Timing Shadow、重大事件、组合偏离、待审批和 Incident。

`/research` tabs：

- Universe & Screen；
- Security；
- Events；
- Watchlists/Cases。

Desk 的最终产品结构 MUST 消费服务端聚合 projection；硬编码 P0–P11 工程能力状态表只可作为历史技术壳，
不能作为原型实现或最终 Desk。

验收：从股票池/排名/事件能进入精确证券和 Research Case；普通股票更新不自动触发昂贵 Agent 深度研究；
Desk 与 Research 分别通过其高保真节点的 1440 对照和三档响应式验收。

### SPEC-048：因子、组合和监控页面

`/factors` tabs：Catalog、Alpha Model、Timing Lab、Experiments、Correlation Monitor、Production。

`/portfolios` tabs：Construction、Backtests、Risk、Scenarios、Attribution。

`/monitoring` tabs：Signals、Portfolios、Timing、Drift、Rebalance、Execution、Incidents。

验收：每个 tab 有 loading/error/empty/partial/unavailable/ready；Backtests 必须标注具体回测类型；
Timing Lab 与生产 Timing Monitor 分离；通用 `WorkspaceUnavailable` 占位不构成对应产品页完成。

### SPEC-049：数据与管理页面

`/system` tabs：Catalog、Quality、Lineage、Jobs、Entitlements、Users、Agents、Approvals。

验收：未实现 RBAC、授权或审批 API 时显示明确未启用原因；不能把本地 human 字符串冒充身份认证；
通用不可用壳不构成该 tab 的 Design Parity 或 Runtime Product 完成。

### SPEC-050：可信状态和证据展示

关键数字旁可查看：as_of、system_as_of、trust、freshness、coverage、dataset/model/run version、source/evidence 和 warning。

验收：`normalized_current` 与 `pit_verified` 不只靠颜色区分；严格回测不可用时显示所有阻断原因。

## 14. API 合同

### SPEC-051：统一响应信封

生产研究 API SHOULD 返回：

```json
{
  "data": {},
  "context": {
    "as_of": "2026-08-10T15:00:00+08:00",
    "system_as_of": "2026-08-10T16:00:00+08:00",
    "data_mode": "current_research",
    "deployment_stage": "shadow",
    "trust_state": "normalized_current",
    "dataset_version_ids": [],
    "model_version_ids": [],
    "run_id": "run:...",
    "coverage": {},
    "warnings": []
  }
}
```

验收：缺失字段不返回虚假 0；错误区分 invalid request、unavailable、permission denied、quality blocked、conflict 和 internal error。

### SPEC-052：主要资源 API

资源至少包括：securities、universes、datasets、facts、features、factors、experiments、investment-views、timing-forecasts、events、signals、portfolios、backtests、risk、orders、fills、attribution、incidents、approvals 和 artifacts。

写 API 需要身份、权限、幂等和审计；数据摄取、模型晋级和真实订单不能作为匿名接口。

## 15. 非功能规格

### SPEC-053：可复现与确定性

数值核心确定性；LLM 输出保存完整调用证据。所有时间、随机种子、排序 tie-break 和浮点容差明确。

### SPEC-054：性能基线

第一版目标：

- 常用读 API p95 < 500ms（不含冷启动大实验）；
- 单证券研究页 p95 < 2s，慢域可渐进加载；
- 5000 股票日频截面因子在开发机 < 10 分钟；
- 页面首屏压缩后 JS SHOULD < 1MB，路由级拆包；
- 长任务异步并可查看进度、取消和重试。

性能目标不是以牺牲 PIT 和审计为代价。

### SPEC-055：可靠性与恢复

摄取/计算幂等、断点续传、失败隔离；定义 RPO/RTO；PostgreSQL、对象和 Artifact 备份并演练恢复。实盘前必须有 kill switch 和降级运行手册。

### SPEC-056：安全

密钥不入库；最小权限；RBAC；网络/工具 allowlist；依赖和镜像扫描；敏感日志脱敏；订单和审批不可抵赖审计。

### SPEC-057：可访问性与国际化

目标 WCAG 2.1 AA；键盘导航、焦点、对比度、表格语义和非颜色状态。第一版中文，字段 code 和专业英文可保留；时间和数字格式明确。

### SPEC-058：测试层级

- 领域单元测试；
- 数据 contract/property/leakage 测试；
- Repository integration；
- API contract；
- 前端 component/contract；
- 回测 golden fixture 和双引擎 reconciliation；
- E2E；
- 视觉回归；
- Shadow/Paper soak；
- 恢复和 kill-switch 演练。

验收：测试通过不替代科学验证；科学验证通过也不替代软件和执行测试。

## 16. 第一条 Golden Path 验收

### SPEC-059：最小端到端闭环

```text
A 股 PIT 股票池
→ 三个基本面因子
→ 正式统计验证
→ InvestmentView
→ Top-N 等权
→ 次交易日现实成交
→ T+1/停牌/涨跌停/费用
→ 基准与归因
→ 前端可追溯展示
```

验收：真实数据小切片跑通；任意数字和交易可追溯；结果可以诚实为负；禁止 fixture 冒充生产结果。

这是“核心选股 Golden Path”，用于尽早验证前三个公司问题、组合和现实回测，不代表六问平台已经完成。事件、主动 Timing、Paper OMS 和实盘分别由 SPEC-026–029、036–041 及后续 Gate 验收；本链路中的未接分项必须显示 `unavailable/not_applicable`，不能展示伪造的完整能力。

## 17. 尚待用户或调研确定、但不改变架构的配置

| 决策 | 何时必须确定 | 当前处理 |
|---|---|---|
| 第一主数据供应商 | P2 批量数据接入前 | 先做来源/许可/覆盖 spike |
| 第一历史股票池/benchmark | 因子实验前 | PortfolioPolicy/UniverseVersion 可配置 |
| 第一再平衡频率 | 组合回测前 | 月度作为研究基线，不固化平台 |
| 第一 Paper/Live 券商 | OMS adapter 前 | Broker port 先独立定义 |
| 主动择时生产仓位最大影响 | Timing 晋级前 | Shadow 阶段为 0 |
| 风险预算与组合上限 | 组合产品定义前 | 平台参数化，不按本金写死 |

这些是产品配置或供应商决策，不是当前 Spec 的逻辑缺口。
