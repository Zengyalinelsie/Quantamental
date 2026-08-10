# 能力融合与迁移地图

## 1. 迁移原则

每项能力只有四种处理方式：

- `Adopt`：语义正确且边界清晰，迁移后只做适配；
- `Adapt`：思想/实现有价值，但需符合新合同；
- `Reference`：只借鉴体验或测试案例，不迁代码；
- `Reject`：不进入权威路径。

## 2. 从 DSA 迁移

| 模块 | 决策 | 原因 | 目标位置/阶段 |
|---|---|---|---|
| FastAPI/Web 工作台信息架构 | Reference/Adapt | 产品体验成熟，领域模型不同 | P6 后接新 API |
| 任务进度、历史报告 | Adapt | 需要绑定 Run/Artifact 版本 | P4–P6 |
| 通知渠道 | Adapt | 渠道能力成熟，消息必须引用冻结快照 | P6 |
| 数据源 fallback | Adapt | 稳定性好，但不同源不能无痕混值 | P1 |
| 市场代码与交易日历测试 | Adapt | 多市场边界和测试丰富 | P1/P4 |
| 新闻搜索与 RSS 情报 | Adapt | 当前研究好用，需补原文 hash 和事件账本 | P6 |
| Agent orchestrator/opinion | Adapt | 结构化与保守修订有价值 | P6 |
| 策略 YAML | Reference | 适合研究 playbook，不是已验证 Alpha | P2/P3 |
| screening scorer | Reference | 可作为启发式基线，不能直接生产 | P2 |
| LLM candidate reranker | Shadow only | 必须先做版本冻结和增量样本外检验 | P6 |
| backtest engine | Rename/Adapt | 保留为 `ForecastOutcomeEvaluator` | P3 |
| portfolio ledger/risk alerts | Adapt | 适合账户视图，不等于组合/OMS | P7 |
| 多通知/桌面端 | Defer | 对第一条科学黄金链路没有阻塞作用 | P8+ |

## 3. 从 Legacy 迁移

| 模块 | 决策 | 迁移前修改 |
|---|---|---|
| DataTrustState/DataMode/DeploymentStage/RunContext | Adopt | 双轴独立枚举并 fail closed 校验组合 |
| ODS envelope/hash/lineage | Adapt | 去除 Futu 偏置，统一 provider 合同 |
| PIT financial query | Adopt | 补 A 股公告、修订和可用时间来源 |
| Security master | Adapt | 增加 A 股公司/证券/挂牌、历史行业、退市 |
| Dataset/Feature/Experiment objects | Adapt | 减少重复字段，统一 Artifact 引用 |
| FactorDefinition/Version lifecycle | Adopt/Extend | 增加统计门、研究族和 FDR |
| SignalSnapshot | Adopt | 输入改为 InvestmentView/AlphaModel 输出 |
| PortfolioDefinition/Target | Adapt | 增加风险/成本模型版本与优化器 |
| BacktestReadiness | Adopt | 增加标签生成和成交时间检查 |
| realistic_backtest | Adapt | 完整 A 股 T+1、公司行动、退市、benchmark |
| Research Case/Evidence | Adapt | 与 Event Ledger 合并语义 |
| Qlib adapter | Adopt boundary | 保持导出/回写，不做真源 |
| Futu-specific operational chain | Reference | 可做未来港股 adapter，不进 A 股主线 |
| 16 模块一次性全建 | Reject as first path | 先打通六问黄金链路 |

## 4. 许可证与来源记录

- DSA 根项目为 MIT；迁移任何代码必须保留版权和 MIT 声明；
- DSA `src/services/screening` 标注来自 AlphaSift，目录内有 Apache-2.0 许可证；若迁移具体代码，必须保留 Apache NOTICE/版权信息并记录原始 revision；
- Legacy 内含多个社区 skill，不能因为在用户仓库里就默认拥有重新许可权；
- 新平台默认先重写领域合同。每个真正复制的模块必须新增 provenance 记录，包含来源路径、提交、许可证、修改说明；
- 在许可证盘点完成前不添加新平台总 LICENSE，避免错误覆盖第三方条款。

## 5. 反重复造轮子清单

| 问题 | 优先使用 | 自研部分 |
|---|---|---|
| 表格计算 | Polars/DuckDB/Pandas | PIT join 与领域校验 |
| 统计回归 | statsmodels/linearmodels/arch | 统一结果合同和质量门 |
| 机器学习实验 | Qlib/sklearn/LightGBM | 治理、数据版本和生产编译 |
| 组合优化 | cvxpy | A 股政策、目标对象和审批 |
| 外部回测对照 | RQAlpha/LEAN | 权威 A 股规则和差异解释 |
| 市场日历 | exchange-calendars + 交易所数据 | 异常/临时休市治理 |
| API | FastAPI/Pydantic | 领域应用服务 |
| 调度 | Prefect/Dagster/Temporal 评估后选一 | Job/Run/Dataset 业务状态 |
| 可观测性 | OpenTelemetry/Prometheus | 投资模型漂移和归因指标 |
| Agent | 可插拔 LLM/tool runtime | 证据合同、权限和审计 |

## 6. 禁止的“融合”方式

- 不让新平台 import 两个来源仓库的内部包形成永久耦合；
- 不把 DSA SQLite schema 当成 PIT 仓库；
- 不把 legacy 的港股 current 数据改个市场字段就当 A 股历史数据；
- 不把 prompt 中的加减分规则包装成统计因子；
- 不把报告方向命中率作为策略收益；
- 不让 UI 为了显示完整而生成占位数字；
- 不在没有数据版本、代码版本和参数 hash 时展示“已回测”。
