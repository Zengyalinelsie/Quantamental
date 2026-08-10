# Spec 与 Plan 一致性审查

> 文档状态：Ready for User Review  
> 审查版本：Spec 0.9.1 / Plan 0.9.1  
> 日期：2026-08-10  
> 审查对象：`07-detailed-system-spec.md`、`08-detailed-implementation-plan.md`，并检查它们与产品目标、Golden Path、架构 ADR 和来源边界的兼容性

## 1. 结论

审查后，没有发现仍会阻止实施的逻辑矛盾。发现的 12 个实质冲突已经修订；另有 8 组看似冲突但实际是分层设计的决策，本文明确了边界。

当前结论不是“所有产品参数都已确定”。数据供应商、首个 benchmark、再平衡频率、券商、风险预算和主动择时最大仓位影响仍需后续调研或用户选择，但它们已经被隔离为配置或 ADR，不会迫使核心架构返工。

本轮没有批准大规模实现、没有修改两个来源仓库、没有修改用户原项目工作树、没有授权真实交易。

现有 P0 Python 合同早于本次 0.9.1 修订：它们的 13 个测试通过，但尚未实现新的双轴 `RunContext` 和 InvestmentComponent status。Plan 已把这两项明确列回 P0 剩余工作，因此“测试通过”不被误写成“Spec 已实现”。

## 2. 真源与优先级

出现冲突时按以下顺序解释：

1. `07-detailed-system-spec.md`：需求、语义和验收真源；
2. `08-detailed-implementation-plan.md`：实现顺序、工作包和阶段 Gate 真源；
3. ADR：重大架构取舍；
4. `00–06`：背景、审计、迁移和早期路线说明；
5. donor 代码：可借鉴资产，不是新平台需求真源。

Plan 不能降低 Spec。旧文档若与 07/08 冲突，应更新旧文档或明确被替代，不能让开发者自行猜测。

## 3. 审查方法

本次逐项检查：

- SPEC-001–059 是否连续、唯一并有计划落点；
- 同一术语在需求、API、前端和运行账本中的含义是否一致；
- P0–P11 是否存在循环依赖或“后置能力被前置阶段暗中依赖”；
- 阶段 Gate 是否把“平台能力完成”和“模型有效/获准上线”混为一谈；
- Golden Path 是否被误写成六问平台全部完成；
- 前端导航是否能容纳所有后台模块；
- Current、Strict、Shadow、Paper、Live 是否会发生权限或数据资格提升；
- Event、Timing、Agent、组合和 OMS 是否有越权通道；
- donor 的“基础”含义是否与干净核心 ADR 冲突；
- 尚未决定的供应商、账户和产品参数是否泄漏为平台常量。

## 4. 已发现并修复的实质冲突

### C-01：数据资格和部署阶段被混成一个 mode

原问题：Spec 把 Current、Strict、Shadow、Paper/Live 称为“四种运行模式”，Plan 和前端却列出 current/strict/shadow/paper/live。Current/Strict 回答“数据能否用于历史研究”，Shadow/Paper/Live 回答“输出能否影响账户”，两者不是同一个维度。

风险：会出现 `strict` 和 `shadow` 二选一、历史回放被冒充为前瞻 Shadow、或前端切换参数提升数据资格。

修复：

- `data_mode = current_research | strict_historical`；
- `deployment_stage = research | shadow | paper | limited_live`；
- 服务端定义有效组合并 fail closed；
- API envelope、Header 和运行账本分别保存两个字段。

修改位置：SPEC-005、SPEC-045、SPEC-051；Plan P1-W04/W05/Gate；同步更新 `00-product-vision.md`。

状态：已解决。

### C-02：完成平台阶段被误解为模型必须有效

原问题：多个阶段写“统计门通过”，可能导致团队为了过阶段而隐藏失败结果；也可能让一个诚实但无效的因子永远阻塞工程能力完成。

修复：明确两类 Gate：

- Capability Gate 验证数据、代码、流程和失败保存是否正确；
- Promotion Gate 验证某个对象能否进入 research backtest、Shadow、Paper 或 Limited Live。

模型可以失败，能力阶段仍可完成；失败对象不能晋级。

修改位置：Spec 阅读方法；Plan 第 0 节、P4、P7、P8。

状态：已解决。

### C-03：P5 在事件能力完成前要求完整四分项 InvestmentView

原问题：P5 先构建 InvestmentView，P8 才构建新闻、Agent、事件研究和供应链。如果 P5 强制 event adjustment 为数值，只能填假值或错误地填 0。

修复：InvestmentView 每个分项具有：

```text
quantified | constrained | unavailable | not_applicable
```

P5 的 quality、valuation、revision 接真实结果；event 在 P8 前标记 `unavailable`。P8 产生新的 Compiler/InvestmentView 版本，不能回写 P5 历史对象。事件只有通过对应用途 Promotion Gate 才能成为数值贡献。

修改位置：SPEC-024、SPEC-030；Plan P5-W02/W04、P8-W04/Gate；同步更新产品示例和 Golden Path。

状态：已解决。

### C-04：P6 把核心选股归因误写成完整统一归因

原问题：P6 尚无主动 Timing、正式事件模型或 Paper 执行，却声称 SPEC-039 全部通过。

修复：

- P6 只验收 market/industry/style/selection/cost 的 core attribution；
- timing/event/execution 字段从一开始存在，但按事实为 `not_applicable` 或 `unavailable`；
- P9 完成研究和 Shadow 统一归因；
- P10 将 Paper execution 并入闭合归因。

修改位置：SPEC-039；Plan P6-W05/Gate、P9 Gate、P10 Gate、追踪矩阵。

状态：已解决。

### C-05：Golden Path 被误写成六问平台完成

原问题：P6 的 “Golden Path 完整跑通”容易被理解为新闻、主动择时、OMS 和实盘都已经完成。

修复：改名为 `Core Selection Golden Path`，明确它只尽早验证 PIT、三个基本面因子、InvestmentView、Top-N、现实 A 股回测和核心归因。六问平台仍需 P7–P11。

修改位置：SPEC-059；Plan P6 Gate、追踪矩阵。

状态：已解决。

### C-06：早期模型晋级需要审批，但 RBAC 被排到 P9/P10

原问题：P4/P5 要求获批因子和 Signal，完整用户/权限能力却在后期，形成依赖循环；若用本地 `human` 字符串绕过，又违反 SPEC-004/049。

修复采用渐进能力而非重复实现：

- P1 建 AuthN/AuthZ ports、deny-by-default 权限矩阵和审计主体；
- P4 启用最小 Reviewer 服务端审批及用途范围；
- P9 完善用户、授权、证据包和治理 UI；
- P10 完成 PM/Trader/Admin 的交易职责分离。

修改位置：Plan P1-W05/Gate、P4-W05/Gate、P9-W03、P10-W01/Gate。

状态：已解决。

### C-07：一次“批准”被所有环境复用

原问题：研究回测通过不应自动获得 Shadow、Paper 或 Live 权限。

修复：Approval 必须带用途范围：

```text
research_backtest → shadow → paper → limited_live
```

用途升级需要独立验证和审批，不能继承为更高权限。

修改位置：SPEC-023、SPEC-030；Plan P4-W05、P6-W01。

状态：已解决。

### C-08：主动 Timing 的 Shadow 输出和组合输入存在歧义

原问题：SPEC-030 接受 TimingForecast，但 SPEC-026 又规定主动模型过门前不能影响仓位。

修复：P7 前和主动模型未晋级时，组合使用获批静态/被动基线；主动 TimingForecast 仅并排 Shadow 记录。只有独立 Promotion Gate 允许将影响上限从 0 调为非零。

修改位置：SPEC-030；Plan P6-W01、P7-W04/Gate。

状态：已解决。

### C-09：P3/P4 对估值和改善的完成声明超出实际工作包

原问题：P3 只建 PIT 数据，P4 只建特征和因子，却在覆盖范围或 Gate 中像是已经完整满足 SPEC-018–019。

修复：

- P3 仅提供数据前提；
- P4 完成可复用特征层；
- P5 才完整验收相对/锚定估值、隐含预期、情景敏感度、趋势/加速度和一次性调整。

修改位置：Plan P3/P4/P5 覆盖和 Gate。

状态：已解决。

### C-10：P5 对 SPEC-030 的完成声明过早

原问题：P5 只有组合输入对象，尚未产生受约束 TargetPortfolioSnapshot，却写 SPEC-030 通过。

修复：P5 只完成输入合同，P6 完成组合输出、约束闭合和正式验收。

修改位置：Plan P5 Gate、P6 Gate。

状态：已解决。

### C-11：数据供应商决定时间与阶段编号不一致

原问题：Spec 待决表写“P1 数据接入前”，Plan 把来源/许可 spike 放在 P2-W01。

修复：改成“P2 批量数据接入前”。P1 只建 provider port 和工程骨架，P2-W01 在任何批量回填前完成 ADR。

修改位置：Spec 第 17 节。

状态：已解决。

### C-12：API 和前端会继续使用含糊 mode 字段

原问题：即使文档解释分层，API 示例仍只有 `mode=current_research`，前端 Header 仍写“运行模式”。

修复：API 示例改为 `data_mode` 和 `deployment_stage`，Header 明确双标签，Plan 要求非法组合服务端拒绝。

修改位置：SPEC-045、SPEC-051；Plan P1-W04/Gate。

状态：已解决。

## 5. 看似矛盾、实际不矛盾的决策

### N-01：用户说“以 DSA 为基础”，但架构采用独立干净核心

“基础”被精确定义为产品体验和可迁移能力的供体，不是直接在 DSA 的 SQLite、报告模型和运行时上继续堆功能。

```text
DSA：工作台、研究流程、Agent UX、报告、通知、provider 经验
Legacy：PIT、版本、因子、Signal、组合、现实回测合同
New Core：统一领域语义、验证门、权限和执行边界
```

这仍然最大化复用，但避免继承与严格 PIT 和未来实盘冲突的核心假设。ADR-0001 已锁定此解释。

### N-02：P1 先做前端，但业务 API 要到 P2–P10 才完成

P1 只做设计系统、六项 Shell、只读骨架和诚实空状态。后续每个阶段接入真实 API。运行时禁止 demo 数据，因此不会形成“假完成”。

### N-03：只有六项一级导航，却有十六条后台工作流

一级导航是用户心智模型，不等于服务模块数量。Timing Lab 是 Factors 的研究 tab，Timing 生产表现是 Monitoring tab；Agent 是 System tab；报告是上下文 Artifact。后台工作流无需各占一个一级入口。

### N-04：没有一级“报告中心”，但大量地方需要报告

报告是某次研究、事件、回测、组合、审批或对账的冻结 Artifact。它从上下文生成和打开，比独立报告仓库更容易保留来源、版本和权限。全局搜索/Artifact API 可找回报告，不需要一级菜单。

### N-05：内部回测引擎与 RQAlpha/LEAN 同时存在

内部引擎是 A 股领域规则和逐笔解释的权威实现；外部引擎是交叉验证器。二者结果不同并非自动失败，无法解释差异才失败。外部引擎不能替代 PIT 数据权威。

### N-06：模块化单体却使用 PostgreSQL、Parquet、对象存储和可选 Redis

“单体”描述部署和代码依赖边界，不要求所有数据塞进一个数据库。不同存储按职责使用，但权威标识、版本和 lineage 在一个治理合同下。Redis 不是账本。

### N-07：P3 先记录 Timing baseline，P7 才做主动 Timing

这是有意设计。P3 从早期就积累不可修改的真实时钟基线和 cutoff；P7 才研究主动模型。这样避免模型完成后回填“前瞻”预测。P3 不宣称主动预测已经完成。

### N-08：Current Research 可以用 normalized_current，严格回测只允许 PIT

这是不同用途的显式资格，不是标准不一致。当前研究可以在明确警告下使用尚未达到严格历史资格的数据；任何 Strict/Paper/Live use case 都不能靠 UI 切换绕过服务端资格门。

## 6. Spec 内部一致性结果

| 检查项 | 结果 | 说明 |
|---|---|---|
| 产品目标与非目标 | 通过 | 六问与“不承诺盈利、不让 LLM 下单”兼容 |
| 时间语义 | 通过 | 经济、可用、系统时间分离；数据模式另轴 |
| 公司质量标准 | 通过 | 通用底线、行业模板、公司例外，不强求全市场同公式 |
| 因子与组合 | 通过 | 因子科学门、统一 InvestmentView、用途审批后进入组合 |
| Timing | 通过 | 主动预测必做；被动基线不替代；未晋级不影响仓位 |
| 事件与 Agent | 通过 | Agent 形成假设和证据，不能提升 trust 或直接给权重/订单 |
| 回测与实盘 | 通过 | 严格数据、现实规则、OMS、对账分层且共享决策代码 |
| 前端 | 通过 | 用户原项目视觉真源、六项导航、无假数据、证据可追溯 |
| API | 通过 | 双轴 mode、统一 context、写操作身份/权限/幂等/审计 |
| NFR | 通过 | 性能目标不压过 PIT，安全和恢复在实盘前为硬门 |
| Golden Path | 通过 | 明确只是 core selection，不虚构事件/Timing/OMS 完成 |

## 7. Plan 内部一致性结果

阶段主依赖为：

```text
P0 合同
→ P1 工程/权限骨架/前端 Shell
→ P2 身份/股票池/行情
→ P3 PIT 财务/公告/Timing 基线账本
→ P4 特征/因子/实验/最小审批
→ P5 估值/改善/InvestmentView/Signal
→ P6 组合/R0 风险/现实回测
→ P7 主动 Timing
→ P8 事件/Agent/供应链
→ P9 统一监控/归因/治理
→ P10 Paper OMS
→ P11 Limited Live
```

P7 与 P8 在数据和 P6/P5 基础具备后可以并行研究，但 P9 需要两者的输出 schema 和监控能力。P7/P8 的模型可以科学失败并停留在 Shadow；P9/P10 可继续使用静态/被动 Timing 和无事件数值贡献的获批基线，不得假装失败模型已生产化。

没有发现阶段循环。关键前置关系如下：

| 消费方 | 必要前置 | 审查结果 |
|---|---|---|
| 严格因子实验 | Security/Universe + PIT facts | P2/P3 → P4，正确 |
| InvestmentView | 特征/因子 + 估值/改善服务 | P4 → P5，正确 |
| 事件增强 View | P5 View + P3 文档证据 | P3/P5 → P8，新版本写入，正确 |
| 组合回测 | Signal + Policy + R0/Cost | P5 → P6，正确 |
| 主动 Timing | PIT 市场/宏观 + 成本/组合框架 | P3/P6 → P7，正确 |
| Paper OMS | 组合、监控、审批、恢复 | P6/P9 → P10，正确 |
| Limited Live | Paper soak + 用户明确授权 | P10 → P11，正确 |

## 8. Spec 与 Plan 覆盖检查

SPEC-001–059 均有主要阶段和最终 Gate。需要注意的跨阶段需求：

| Spec | 不能一次完成的原因 | 分阶段完成方式 |
|---|---|---|
| SPEC-004 权限 | 研究与交易权限出现时间不同 | P1 骨架、P4 最小审批、P9 治理、P10 交易职责分离 |
| SPEC-018–019 | 数据、特征和服务分层 | P3 数据、P4 特征、P5 完整服务 |
| SPEC-024 | event 分项晚于核心 View | P5 三项量化 + event unavailable；P8 新版本增强 |
| SPEC-026 | 需要先积累真实时间记录 | P3 baseline ledger；P7 主动模型和验证 |
| SPEC-027–029 | 正式公告早于全事件 Agent | P3 公告文档；P8 完整事件/供应链 |
| SPEC-030 | 输入对象早于组合构建 | P5 输入合同；P6 TargetPortfolioSnapshot |
| SPEC-039 | 归因分项随策略/执行增加 | P6 core、P9 unified research/Shadow、P10 Paper execution |
| SPEC-042–050 | Shell 先于真实业务 | P1 空状态，P2–P10 逐步接 API |
| SPEC-051–052 | 统一合同先于资源实现 | P1 envelope，资源随领域阶段上线 |
| SPEC-053–058 | 横切非功能需求 | 各阶段持续验证，P10/P11 执行与恢复硬门 |

## 9. 前端风格一致性检查

前端明确采用用户原项目最新本地工作树，而不是 DSA 的 Streamlit/Web 风格：

- React 19、TypeScript、Vite 7；
- Ant Design 6、ProTable；
- TanStack Query、Zustand、Less Modules；
- Recharts；
- 主色 `#2F5EA8`、背景 `#F3F5F7`；
- 3px 圆角、无装饰性卡片阴影；
- 高密度表格、数字右对齐和 tabular nums；
- 280/72px 桌面侧栏、移动 Drawer；
- 六项一级导航。

已明确废止的旧描述：

- 旧 10px 圆角；
- 旧 Chart.js 说明；
- 独立一级报告中心；
- Agent 或 Timing 各自占一个一级菜单。

迁移必须记录 provenance 和许可证。用户原项目工作树保持只读；新平台可重建相同 token、布局和交互合同，但不能无记录覆盖或搬运未提交内容。

## 10. 仍待决定，但不是逻辑矛盾

| 决策 | 最迟时点 | 默认占位 |
|---|---|---|
| A 股第一主数据供应商 | P2 批量接入前 | P2-W01 spike + ADR |
| 第一 benchmark/历史股票池 | P4 因子实验前 | Universe/Policy 参数 |
| 第一再平衡频率 | P6 回测前 | 月度研究基线 |
| 第一外部回测引擎 | P6-W04 前 | RQAlpha 或 LEAN 对照 |
| Paper/Live 券商 | P10 adapter 前 | Broker port，不提前绑定 |
| 主动 Timing 最大仓位影响 | 模型 Promotion 前 | Shadow 为 0 |
| 风险预算和组合上限 | P6 产品政策冻结前 | 参数化，不按本金写死 |
| 身份提供方/部署方式 | 首次非本地写 API 前 | Auth port + deny-by-default |

这些选择可能改变 adapter、费用、覆盖率或默认参数，不改变 Company/Security/PIT/InvestmentView/Portfolio/OMS 的核心合同。

## 11. 尚存风险，不属于文档自相矛盾

### R-01：A 股 PIT 数据的可得性和许可

这是最大外部风险。若免费源没有历史公告时间、修订、退市或合法长期缓存权，严格回测范围必须缩小或采购数据，不能降低 PIT 标准。

### R-02：主动 Timing 的统计功效

1/5/20/60 日标签重叠、制度变化和宏观发布修订会显著降低有效样本。平台必须实现主动预测能力，但不保证主动模型能通过 Promotion Gate。

### R-03：事件和供应链数值化容易产生伪精确

Agent 输出默认是假设，不是事实。很多事件最终可能只能作为 constraint、confidence 或 invalidator，不能为了闭合而硬生成收益点数。

### R-04：双引擎无法做到逐项完全相同

交易日历、公司行动和撮合细节会造成差异。目标是逐笔解释、分类和设置容差，不是强制收益曲线位级相等。

### R-05：完整平台范围很大

P0–P11 是平台路线，不是一个短 Sprint。核心选股 Golden Path 是最早的价值验证点，不能因为最终范围很大而跳过它，也不能把它包装成最终产品。

## 12. 用户审查清单

建议用户重点确认以下非技术决策：

- 是否同意“以 DSA 为基础”解释为产品体验/能力供体，而不是直接 fork 其运行时；
- 是否接受用户原项目最新机构风格作为唯一前端视觉真源；
- 是否接受六项一级导航，报告作为上下文 Artifact；
- 是否接受核心选股 Golden Path 先完成，但主动 Timing 必须在 P7 真正实现主动预测；
- 是否接受事件在 P5 明确 unavailable，到 P8 才形成可验证数值增强；
- 是否接受任何模型可以诚实失败，失败不阻塞平台能力建设但绝不晋级；
- 是否接受 Paper/Live 必须另行授权，当前文档不构成下单授权。

若以上均同意，Spec 和 Plan 可以从 Draft 升为 Approved Baseline；后续重大语义修改应通过 ADR 和版本号，而不是直接覆盖历史决策。
