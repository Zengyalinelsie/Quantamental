# 来源仓库审计

## 1. 审计范围与基线

| 来源 | 本地路径 | 审计提交 |
|---|---|---|
| `ZhuLinsen/daily_stock_analysis` | `sources/daily_stock_analysis` | `396d43a4c76ffa940e2b9aea7bbe8686343c694a`（2026-08-09） |
| 用户原量化平台已提交基线 | `sources/legacy_quant_platform` | `844fb4fffbab394a45056a6e734f3c8a6d9cbb5d`（2026-07-26） |

用户原目录存在未提交修改，本项目没有复制、覆盖或重置这些修改。来源目录视为只读。

## 2. 先给结论

`daily_stock_analysis` 是很好的“每日股票研究产品外壳”，但不是严格意义上的基本面量化平台。它最值得借鉴的是用户体验、Agent 组织、报告、通知、多市场数据接入和持续运行能力；最不能直接继承的是把当前数据、启发式评分、LLM 重排和报告命中评估当成科学选股与组合回测。

用户原项目不是一无是处，恰恰拥有 DSA 最缺的底层纪律：双时间、可信状态、不可变数据、版本化研究对象、PIT fail-closed、信号/组合合同和现实交易回测原型。它的问题是主线太重、产品体验较弱，而且真实数据仍偏港股 current-only，科学检验也只完成了骨架。

因此新平台不做代码库级合并：

> DSA 做体验与研究入口，legacy 做可信与治理供体，新核心重新定义统一决策和科学验证。

## 3. `daily_stock_analysis` 的强项

### 3.1 产品完成度高

- FastAPI、Web、Electron、CLI、定时任务和 GitHub Actions 入口齐全；
- 支持多个市场、多个行情源和搜索源；
- 报告历史、任务进度、配置、通知、导入、持仓跟踪已经产品化；
- 失败降级、数据源健康、代码别名和市场阶段处理有大量测试；
- Agent 策略具备结构化 opinion、invalid diagnostics、保守修订和结果跟踪；
- 新闻情报表保存 `published_at` 与 `fetched_at`，比只保留一段摘要可靠；
- 根仓库为 MIT；筛选模块明确注明派生自 AlphaSift 并保留 Apache-2.0 许可证。

这些能力能显著缩短“每天真的有人使用”所需的时间。

### 3.2 它的定位本来就不是机构级量化

README 明确描述主流程为行情、技术指标、新闻、LLM 分析、报告和推送，也明确把 AlphaEvo 称为策略验证项目。因此下面的科学性缺口更多是“与我们的目标不匹配”，不应简单理解为 DSA 原项目质量差。

## 4. `daily_stock_analysis` 的关键缺口

### 4.1 名为回测，实质是报告预测的事后评分

代码证据：

- `src/core/backtest_engine.py:158` 的 `evaluate_single` 输入是 `operation_advice`、一个起点价格和未来 K 线；
- `src/core/backtest_engine.py:367` 汇总方向准确率、胜率和平均收益，没有资金曲线、基准超额、组合权重或风险调整统计；
- `src/services/backtest_service.py:184` 用 `start_bar.close` 作为模拟入场价；
- `src/core/backtest_engine.py:688` 仅用日线 high/low 判断止盈止损，若同日同时触发则假设止损先发生；
- 全回测路径没有佣金、印花税、滑点、成交量冲击、涨跌停、停牌、T+1、退市和组合资金约束。

更严重的语义问题是：`resolve_historical_daily_bar_date` 返回“报告当时能消费的最后一根已完成日线”，而回测又用这根 K 线的收盘价作为入场价。盘后生成的报告不可能回到当天收盘价成交。这个结果适合称为 `ForecastOutcomeEvaluation`，不应称为权威交易回测。

应该保留该能力，但改名并降级为“预测校准/报告结果评估”。

### 4.2 没有严格 PIT 基本面

代码证据：

- `src/storage.py:278` 的 `FundamentalSnapshot` 注释明确写着 P0 write-only；字段只有 payload、source chain、coverage 和 `created_at`；
- 没有财务事实级的 `available_at`、修订序号、系统知识有效区间和历史查询合同；
- `data_provider/yfinance_fundamental_adapter.py:257` 保存报告期，但没有可靠公告可用时间；
- AkShare 基本面接入主要服务当前分析，允许 partial/fail-open。

因此它能回答“今天看到的基本面是什么”，不能可靠回答“2021-04-15 当时能看到哪一版财报”。

### 4.3 “质量选股”仍以启发式快照评分为主

筛选因子主要是：value、liquidity、momentum、reversal、activity、stability、size、theme heat 和 topic alignment。所谓 `quality_value`、`momentum_quality` 的硬筛选主要使用 PE、PB、市值、成交额和当日/技术特征，并未系统使用 ROIC、应计质量、现金转换、利润率稳定性、杠杆、行业经营指标或财报修正。

这使它更接近“候选发现器”，不是经过统计验证的行业化基本面 Alpha。

### 4.4 缺少因子统计和多重研究控制

仓库没有形成以下权威检验链：

- 日度 IC/Rank IC 的 HAC 或 block-bootstrap 不确定性；
- Fama–MacBeth 截面回归与风险暴露控制；
- 行业/市值中性后的增量信息；
- 多重假设检验和 False Discovery Rate；
- Walk-forward、purged/embargo、完全样本外；
- 参数稳定性、子期间、市场状态和容量检验；
- Deflated/Probabilistic Sharpe 等策略选择偏差控制。

大量单元测试证明软件行为稳定，不等于投资假设在统计上成立。

### 4.5 LLM 可以重排，但缺少生产级模型治理

筛选管线先做确定性评分，再把 Top-K 交给 LLM 重排。这对交互研究有价值，但若进入生产信号，需要额外冻结：

- 模型供应商、模型版本、prompt hash、工具结果版本；
- temperature/seed 等采样参数；
- 原始响应和结构化解析结果；
- 不使用未来新闻的历史重放方案；
- 同一输入重复运行的一致性指标；
- LLM 增量相对确定性基线的样本外检验。

在这些门槛前，LLM 排名只能是研究建议或 Shadow 信号。

### 4.6 新闻适合当前研究，不适合直接历史重放

`published_at` 与 `fetched_at` 是良好起点，但严格事件研究还缺：

- 首次可交易时间和交易所时区标准化；
- 原文内容哈希、版本、撤回/更正；
- 公司/证券/供应链实体消歧；
- 同事件跨来源聚类；
- 事实、推断、市场观点和传闻分层；
- 历史 LLM 模型是否已经见过事后结果的污染控制；
- 事件冲击的 Event Study、匹配样本和因子调整异常收益。

所以“如何处理新闻”不是伪问题，但不能简单做情绪正负分。

### 4.7 持仓跟踪不是组合构建和 OMS

DSA 已有账户、交易流水、快照、公司行动和风险提醒，适合个人持仓管理；但它没有从预期收益、风险、成本生成受约束目标权重的正式优化器，也没有订单意图、审批、幂等、成交回报和券商对账的完整状态机。

### 4.8 主动择时尚未成为可验证预测问题

市场阶段、热点和结构分析很丰富，但尚未定义统一的预测标签、期限、概率校准、基线、样本外门槛和仓位映射。市场状态描述不等于主动择时模型。

## 5. 用户原项目可贡献什么

| 能力 | 已有价值 | 如何迁移 |
|---|---|---|
| `raw / normalized_current / pit_verified` | 防止当前数据误入回测 | 原样保留语义，重写为更小领域合同 |
| 双时间 PIT | `available_at` 与 system time 分开 | 成为数据层公理 |
| ODS 与哈希证据 | 原始响应不可变、可追溯 | 迁移 ODS envelope 与 lineage 思想 |
| Dataset/Feature/Experiment 版本 | 可复现和回滚 | 收敛字段后迁移 |
| FactorDefinition/Version 生命周期 | 防止试验因子直接生产 | 保留，但补正式统计门 |
| SignalSnapshot | 信号冻结且绑定因子运行 | 作为生产信号唯一入口 |
| PortfolioDefinition/TargetSnapshot | 区分策略、组合和目标权重 | 保留并扩展优化器、风险模型版本 |
| BacktestReadiness | 缺历史池、退市、PIT 时 fail-closed | 作为所有严格回测前置门 |
| realistic_backtest 原型 | 次日执行、成本、整手、停牌、涨跌停、退市 | 迁移为领域规则测试基线，再与成熟引擎对照 |
| Research Case/Event/Evidence | 让 Agent 结论可追踪 | 融入事件和研究工作台 |
| Qlib 适配边界 | 治理数据导出，结果回写 | 保留“适配器而非权威库”定位 |

## 6. 用户原项目也不能原样搬运

- 主线仍偏 Futu 与港股 current-only；
- 100 家 current 覆盖不是 A 股历史股票池；
- 当前因子检验只有 IC、Rank IC、分层、衰减、换手和简单 walk-forward 骨架；
- 没有 HAC t 值、Fama–MacBeth、多重检验、bootstrap 和策略选择偏差控制；
- 组合构建主要是等权/得分权加约束，不是完整优化和风险贡献体系；
- 现实回测是有价值的原型，还未覆盖 A 股公司行动、精确 T+1 库存、成交队列和双引擎一致性；
- 治理对象很多，第一条 A 股黄金链路尚未真正跑通；
- 产品入口和日常使用体验不如 DSA。

## 7. 融合判断矩阵

| 能力 | DSA | Legacy | 新平台决策 |
|---|---|---|---|
| 每日研究体验 | 强 | 弱 | 借鉴 DSA |
| Web/API/任务/通知 | 强 | 有骨架 | DSA 体验，重新接新核心 |
| 多源行情 fallback | 强 | Futu 强 | Provider adapter 复用思想，不让 fallback 改变事实语义 |
| Agent 编排 | 强 | 权限治理较强 | DSA 交互 + legacy 权限边界 |
| 新闻研究 | 当前研究强 | 证据对象强 | 建 Event Ledger 与历史可用时间 |
| PIT 财务 | 弱 | 合同强、真实覆盖不足 | 以 legacy 语义为权威，建设 A 股数据 |
| 因子研究 | 启发式评分 | 基础统计骨架 | 重建正式 Factor Lab |
| 报告结果评估 | 强 | 弱 | 保留并改名 |
| 组合策略回测 | 不足 | 现实原型 | 迁移、扩展并双引擎验证 |
| 主动择时 | 市场描述强 | 未正式实现 | 新建 Timing Lab |
| 实盘 | 持仓跟踪 | OMS 合同设想 | 新建隔离 OMS，最后接入 |

## 8. 验证说明

- 已对 DSA 的关键 Python 文件做 Python 3.12 编译检查，成功；
- 尝试运行目标 pytest，但可用 Python 环境缺少 DSA 的 `httpx` 依赖，因此未安装依赖、未声称测试已运行；
- Legacy 此前选定因子、Signal、回测和 Qlib 适配测试在原审计中通过；本次没有重跑其全量测试；
- 本文判断来自代码路径，不以 README 宣传作为科学能力证据。

## 9. A 股数据源二次只读审计

为 ADR-0003 的私人本地数据回填再次只读检查 donor，未修改来源文件、未发网络请求：

- `data_provider/akshare_fetcher.py` 的 A 股历史日线依次 fallback 到东财、新浪、腾讯，但三路均显式传入 `qfq`；它们不能进入新平台 raw/unadjusted bar；
- 新浪/腾讯分支在缺少涨跌幅时用查询窗口内 `pct_change`，首行 `fillna(0)`；这会把缺失和窗口边界伪装为 0，新平台拒绝迁移该行为；
- donor 的 normalize 结果没有把真实 endpoint winner、adjustment、retrieved_at、cutoff 和单位完整绑定到每批数据；异常捕获也会混合 schema drift、限流和质量错误；
- `src/data/stock_index_loader.py` 读取的是 current code/name/active alias 文件，以文件新旧和远程缓存选择，不含经济有效区间或 `available_at`，不是历史 Security Master 或 CSI300/CSI500 Universe；
- `screening/dsa_provider.py` 是最多 5 个候选的 current quote/fundamental/news enrichment，不是权威数据层。

可借鉴但必须窄重写的模式包括：确定性 fallback 顺序、空结果继续、有界 retry+jitter、限流/熔断、可终止的第三方调用、临时文件原子替换、last-good fallback、代码/市场别名规范化和 enrichment 的显式 unavailable/warnings。

许可证边界不变：donor 根 MIT 和 screening 的 Apache-2.0 只覆盖代码，不证明东财、新浪、腾讯、Tushare 或 Futu 数据可保存/再分发。若未来迁移具体 screening 代码，必须保留 AlphaSift Apache 归因和修改记录；当前实现只参考模式，没有复制这些 fetcher。
