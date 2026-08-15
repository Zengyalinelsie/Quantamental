# Fundamental Quant 产品蓝图与原型真源

> 状态：产品原型阶段，2026-08-14
> Figma：<https://www.figma.com/design/mrt216q7X7NGqFhRjwQS3f/Fundamental-Quant-%E2%80%94-%E4%BA%A7%E5%93%81%E8%93%9D%E5%9B%BE%E4%B8%8E%E9%AB%98%E4%BF%9D%E7%9C%9F%E5%8E%9F%E5%9E%8B?node-id=9-238&t=R538S55yXyPUxZr9-0>
> 本文定义产品信息架构和交互逻辑，不改变 `docs/07-detailed-system-spec.md` 的可信、PIT、审批和安全约束。

## 1. 原型目标

现有前端是领域合同和 API 的技术验证壳，不是最终产品。新的产品原型按研究员工作流组织，而不是按 P0、P1、P2 等工程阶段展示：

```text
发现变化
→ 建立公司研究 Case
→ 回答质量、估值、改善、事件四问
→ 编译 InvestmentView
→ Reviewer 按用途审批
→ 生成不可变 SignalSnapshot
→ 构建组合
→ 现实 A 股回测与风险验证
→ Timing Shadow / 组合监控
→ Outcome、归因和漂移学习
```

原型中的证券、收益、组合和回测数字全部是 `DESIGN FIXTURE`，仅用于表达版式与交互，不进入运行时数据库，不代表 `pit_verified`，不构成模型科学有效证据。

## 2. 来源与取舍

| 来源 | 借鉴内容 | 明确不迁移 |
|---|---|---|
| `sources/legacy_quant_platform` | 公司研究密度、行业/公司定位、质量、估值、情景、催化剂、失效条件和同业对比 | 不复制整套报告，不接受 LLM 生成权威财务或价格数值 |
| `sources/daily_stock_analysis` | 每日任务、新闻聚合、任务进度、历史报告、Watchlist 和通知意识 | 不迁移“买卖建议”产品定位，不把方向命中评估当组合回测 |
| 当前 Spec/Plan | PIT、双时间、版本、证据、审批、InvestmentView、组合、风险、归因、Shadow | 不为了视觉完整加入运行时假数据，不降低 Gate |

视觉约束沿用 SPEC-043–045：主色 `#2F5EA8`，机构级高密度表格，0–4px 圆角，无渐变、玻璃拟态和全局卡片阴影；Data Mode 与 Deployment Stage 始终分轴显示。

## 3. 六个一级工作区与 31 个页面

### 3.1 今日工作台

| 页面 | 页面内容 | 核心操作 | Gate |
|---|---|---|---|
| 今日工作台 | 数据健康、Screen 排名变化、重大事件、组合偏离、Timing、审批和 Incident | 进入 Security、任务、审批或异常 | 普通刷新不触发昂贵 Agent；不提供下单 |

### 3.2 研究

| 页面 | 输入与处理 | 输出与主要操作 | Gate |
|---|---|---|---|
| Universe & Screen | Universe、行业、质量/估值/改善、流动性和排除条件；资格过滤、行业内标准化、稳定排序 | 版本化 Screen、rank change；保存、加入 Watchlist、进入 Security | Current/Strict 分离；浏览器不重算排名 |
| Security | Security Master、财务、价格、行业、事件和证据；按行业模板回答四问 | 公司研究页、同业、Case 和 InvestmentView 草稿 | 缺失分项 `unavailable`；LLM 不产权威数值 |
| Events | 公告、新闻、研报、舆情和引用；去重、实体、事实、冲突、影响路径 | EventFact、EventImpact；关联 Security/Case、人工确认 | 无引用结论不能进入 InvestmentView |
| Watchlists / Cases | 候选、事件、假设和证据变化；建立负责人、期限和检查点 | 可审计 Research Case 历史 | 普通更新不得自动启动深度 Agent |

### 3.3 因子

| 页面 | 输入与处理 | 输出与主要操作 | Gate |
|---|---|---|---|
| Factor Catalog | FactorDefinition、公式、单位、缺失策略和行业适用；登记、实验、验证、Review | 不可变 FactorVersion 和 PromotionReview | 测试通过不代表科学有效 |
| Alpha Model | 获批 FactorVersion/Review、InvestmentView 和 Universe；绑定、约束、score、rank | 不可变 SignalSnapshot；资格审计、提交模型审查 | 无 PIT/用途审批时真实 Snapshot 为 0 |
| Timing Lab | PIT 特征、标签、静态/均线/波动率基线和成本；walk-forward、校准、净效用 | TimingExperiment 和 Artifact；申请 Shadow | 主动模型必须真实存在；未晋级影响 0% |
| Experiments | 数据/代码/参数/seed；预检、执行、统计、交叉验证 | Run、指标、日志、Artifact；Qlib 交换 | 负结果保留；current 不晋级 strict |
| Correlation Monitor | 获批因子截面与历史窗口；相关性、共同暴露和容量监控 | 相关矩阵和 Review 触发 | 不自动修改因子权重或审批 |
| Production | 冻结对象、用途、部署范围和 Artifact | 用途隔离的 serving registry | Research/Shadow/Paper 不能相互提升 |

### 3.4 组合

| 页面 | 输入与处理 | 输出与主要操作 | Gate |
|---|---|---|---|
| Construction | Snapshot、PortfolioPolicy、prior portfolio、Risk/Cost；权重和约束求解 | TargetPortfolioSnapshot、blocked intents | 无合格信号失败关闭；无真实账户和下单 |
| Backtests | Signal/Target、交易日历、行情、公司行动和成本；T+1、停牌、涨跌停、lot、成交和现金 | Trade ledger、equity curve、blocked orders、双引擎 diff | 盘后信号不能当日收盘成交 |
| Risk | Target、benchmark、exposure、covariance；industry/Size/Beta 和 shrinkage | RiskModelDecisionRecord、边际/成分/总风险 | 风险贡献闭合并绑定版本、用途 |
| Scenarios | 历史/假设冲击、exposure 和 invalidator；冲击、传导、覆盖、闭合 | 情景损益和不可用分项 | 未映射暴露 `unavailable`，不得填 0 |
| Attribution | 组合、基准、交易、成本和 View outcome；market/industry/style/selection/cost/residual | 闭合归因和学习输入 | Timing/Event/Execution 按事实标记 `not_applicable` 或 `unavailable` |

### 3.5 监控

| 页面 | 页面作用 | Gate |
|---|---|---|
| Signals | Snapshot 新鲜度、覆盖、失效和排名变化 | 无真实 Snapshot 时计数必须为 0 |
| Portfolios | 目标与观测持仓、风险、现金和限制偏离 | 无真实账户连接；Intent 不是 Order |
| Timing | 每日冻结 Forecast、Outcome 和 Calibration | `no edit/no backfill`；晋级前组合影响 0% |
| Drift | dataset/feature/model/calibration 的 coverage、PSI、IC decay 和 Brier | 只阻断或创建 Review，不静默改模型 |
| Rebalance | Signal/Risk/Policy 变化形成原因链和研究意图 | T+1 等规则生效；没有下单按钮 |
| Execution | Paper Intent、状态机、Fill、Fee 和 reconciliation | 真实账户未连接且不可配置 |
| Incidents | Data/Model/Portfolio/Jobs 异常的 owner、缓解、恢复和复盘 | 严重质量问题阻断下游 |

### 3.6 数据与管理

| 页面 | 页面作用 | Gate |
|---|---|---|
| Catalog | Raw/Observation/Canonical/Research/Serving 资产、owner、SLA 和 trust ceiling | current 源不得提升为 PIT |
| Quality | 完整性、唯一性、时间、映射、覆盖、冲突和传播 | 非空但全 unmapped 不是合法空期 |
| Lineage | 从页面数字追到公式、模型、run、dataset 和 raw evidence | 关键证据断链即 fail closed |
| Jobs | 摄取、规范化、特征、实验、Screen 和 Shadow 任务 | source quota 必须在网络调用前拒绝 |
| Entitlements | 服务端角色、dataset/use/stage policy | 前端隐藏不是权限；真实交易拒绝 |
| Users | 真实身份、团队、角色、MFA/session | 未启用时不得显示伪用户 |
| Agents | 工具 allowlist、数据资格、Prompt、schema 和引用 | Agent 无审批、权威数值和交易权限 |
| Approvals | 因子、模型、View、Timing 和用途审批 | 证据不足禁用；修改产生新版本与新审查 |

## 4. 每个工作页的固定逻辑区

每个工作页底部固定展示五段，不允许只展示漂亮结果：

1. `INPUT`：读取哪些版本化对象和数据资格；
2. `PROCESS`：服务端或领域核心执行什么确定性处理；
3. `OUTPUT`：产生什么不可变对象、投影或 Artifact；
4. `ACTION`：用户能执行什么安全操作；
5. `GATE`：哪些条件使页面或动作 `blocked/unavailable`。

前端不得自己计算 InvestmentView 闭合、Screen 排名、rank change、组合权重、风险贡献或审批资格。

## 5. 端到端黄金路径

| 步骤 | 输入 | 输出 | 失败关闭行为 |
|---|---|---|---|
| Screen 发现 | Universe + 因子版本 | 候选排名 | strict 缺 PIT 时阻断 |
| 公司四问 | 质量、估值、改善、事件 | Research Case | 四态精确表达，缺失不填 0 |
| InvestmentView | 分布、四分项、residual | 20/60/120D Frozen View | 闭合、证据或 invalidator 不完整时不可提交 |
| Reviewer | View/Factor/Model + scope | ApprovalReview | 证据不足禁用，scope 不可提升 |
| Signal Snapshot | 获批版本 + Universe/cutoff | immutable score/rank/hash | 无合格 PIT/审批时真实数量为 0 |
| Portfolio | Snapshot + Policy + Risk/Cost | TargetPortfolio / blocked intents | 无信号失败关闭；Timing 未晋级影响 0% |
| Realistic Backtest | Target + A 股交易规则 | Trade ledger / curve / diff | T+1、停牌、涨跌停、lot、成本必须生效 |
| Shadow / Attribution | Forecast/outcome/trade/evidence | 前瞻 ledger 和闭合学习 | no edit/no backfill；历史预测不修改 |

任一步失败都保存 blocker、证据和版本；不得填 0、伪造成功或提升 trust。修复后必须产生新版本重新运行。

## 6. Figma 当前画布清单

已存在的独立高保真或可编辑工作页：

1. Foundations & Product Map；
2. 今日工作台；
3. Universe & Screen；
4. Security Overview（旧版，保留作对照）；
5. Security Overview 融合版；
6. Alpha Model；
7. Portfolio Construction；
8. Realistic Backtest；
9. Risk & Scenarios；
10. Attribution；
11. Events；
12. Timing Lab；
13. Timing Shadow Monitor；
14. Data Quality & Lineage；
15. Approvals；
16. 31 页完整产品蓝图；
17. 黄金路径与失败关闭状态机。

`InvestmentView` Frame 在后续导入 31 页蓝图时被误覆盖。其可编辑恢复真源保存为
`docs/assets/prototype/investment-view.svg`，已完成 XML 校验和 1440 px 本地渲染复验，并于
2026-08-13 通过当前已登录且具有文件 owner 权限的 Chrome/Figma 会话重新导入。云端顶层 Frame
命名为 `security-investmentview`，尺寸 `1440 × 1200`，位置 `X=4868, Y=-900`。它明确展示四种
状态语义、显式 residual、Decimal 闭合、不可用不填零、证据/版本、催化剂/失效条件和禁用的审批
提交；所有示例数字均标识为 `DESIGN FIXTURE / 非生产数据`。

2026-08-14 新增个股研究融合页。可恢复真源为
`docs/assets/prototype/security-overview-fused.svg`，将现有平台的研究上下文、四问、证据覆盖、
blocker、审批 Gate 和 InvestmentView 就绪度，与只读 `stock-analysis` 示例 HTML 的结论置顶、
公司画像、价值链、财务轨迹、Catalysts/Invalidators、同业对比和持续跟踪结构合并。HTML 中的
买卖建议、仓位建议和目标价承诺没有迁入。云端顶层 Frame 为
`security-overview-600519-fused-v2`，尺寸 `1440 × 1900`，位置 `X=21148, Y=-900`，节点
`24:400`。旧版 `security-overview-600519` 未删除；`research-universe-screen` 的主路径目标已改为
融合页，融合页顶层单击继续进入 `security-investmentview`。页面明确展示
`DESIGN FIXTURE / 非生产数据`、分轴的 Data Mode / Deployment Stage、
`normalized_current` 但非 PIT 验证、`UNAVAILABLE · —`、`NOT_APPLICABLE` 语义和证据不完整时
禁用提交；本次原型验收不代表模型科学有效。

同一次会话确认并删除了唯一明显无用途的顶层 `Rectangle`：它位于画布原点、尺寸为
`1440 × 40`、无子层且不属于产品 Frame。14 个关键页已整理在 `Y=-900` 的业务行；会与 Risk、
Data Quality、Attribution、Approvals 重叠的 `15-golden-path-state-machine` 已移到 `Y=2200`，
`product-blueprint-31-pages` 已移到 `Y=4200`。移动只修改顶层 X/Y，不改变页面内部内容。

## 7. 原型验收标准

- 六个一级导航严格一致；
- 所有示例页明确标记 `DESIGN FIXTURE / 非生产数据`；
- Data Mode 与 Deployment Stage 始终分开；
- 页面含 loading、error、empty、partial、unavailable、ready 的产品状态；
- `normalized_current` 与 `pit_verified` 不只靠颜色区分；
- InvestmentView 四态和 residual 闭合可见；
- 不出现真实账户连接和真实下单入口；
- Reviewer 和权限由服务端拥有；
- 关键页面能沿黄金路径跳转，并能打开证据与 blocker；
- 320/768/1024/1440 视觉检查通过；
- 原型通过只证明产品设计可实现，不证明模型科学有效。

### 7.0 截至 2026-08-14 的验收状态

| 验收项 | 状态 | 证据/限制 |
|---|---|---|
| Chrome/Figma 已登录连接与精确节点 | `ready` | 已使用当前 owner 会话打开并编辑目标文件；浏览器控制复验正常 |
| 现有 14 个关键高保真页与 31 页蓝图 | `ready`（1440） | 14 个关键页均完成视觉检查；大型状态机移至 `Y=2200`，31 页蓝图移至 `Y=4200`，不再覆盖业务页 |
| `security-investmentview` 云端恢复 | `ready`（1440） | 可编辑 SVG 已导入并命名为 `security-investmentview`，尺寸 `1440 × 1200`，位置 `X=4868, Y=-900` |
| `security-overview-600519-fused-v2` 融合页 | `ready`（1440） | 可编辑 SVG 已导入，尺寸 `1440 × 1900`，位置 `X=21148, Y=-900`；旧页保留；本地 1900 px 渲染和 Chrome/Figma 演示截图均已复验 |
| 顶层孤立 Rectangle 清理 | `ready` | 唯一 `1440 × 40`、无子层、位于原点的 Rectangle 已删除；未删除产品 Frame |
| 黄金路径 Prototype 连线 | `ready` | 保留唯一 `Flow 2`，起点为 `desk-daily-workstation`；Universe 已改连融合页，融合页再进入 InvestmentView；后续路径保持不变，节点序列见 7.3 |
| evidence/blocker/run/lineage 往返 | `ready`（代表入口） | InvestmentView 的 evidence、Backtest 的 blocker 卡片与 InvestmentView 的 run id 均可进入 `13-data-quality-lineage`；Lineage 顶层单击执行 Back |
| 1440 桌面版视觉 | `ready` | 关键业务 Frame 均为 1440 宽，InvestmentView 与主路径首尾已完成云端截图验收 |
| 320/768/1024 响应式 Frame | `not_started` | 顶层画布未发现这些宽度的独立关键页 Frame；只存在本文的重排合同，不能由 1440 推断通过 |

`partial`、`blocked` 和 `not_started` 不是通过。尤其不能用 1440 桌面截图推断 320、768、1024
三档符合响应式合同；没有对应 Frame 或运行时视觉证据时必须保持未验收。

### 7.1 六态产品合同

页面级状态由服务端合同决定，不由前端根据“有没有行”猜测。高保真页至少要有 ready 状态，
31 页蓝图和实现合同共同覆盖以下六态：

| 状态 | 页面必须展示 | 禁止行为 |
|---|---|---|
| `loading` | 正在读取的对象类型、scope 和可取消/重试条件 | 不显示上一份数据冒充当前结果 |
| `error` | 错误类型、run/request id、发生时间、可安全重试动作 | 不用空表吞掉异常 |
| `empty` | 查询确实成功、合法空期原因和筛选条件 | 非空但全 unmapped 不得归类为空 |
| `partial` | 已有部分、缺失部分、trust、影响范围和 blocker | 不把缺失分项填 0，不开放不合格动作 |
| `unavailable` | 无权限/无数据/时间不可信/尚未实施等明确原因 | 不渲染 fixture，不假装 loading 后会成功 |
| `ready` | cutoff、data mode、deployment stage、version、run/hash | 不隐藏仍有效的 warning |

`InvestmentComponent.status` 另有四态：`quantified` 有可追溯数值；`constrained` 有数值但受明确
约束；`unavailable` 无法可靠量化；`not_applicable` 在当前期限、行业或口径明确不适用。后两者
不贡献数值，二者都不能自动填零。显式 `residual` 是独立闭合项，不是第五个 InvestmentComponent。

### 7.2 响应式重排合同

原型优先表达 1440 桌面研究工作台；工程实现还必须按下表重排，而不是等比缩小桌面 Frame：

| 视口 | 导航与上下文 | 主内容 | 表格/图表 | 主要操作 |
|---|---|---|---|---|
| 1440 | 224 px 左导航；完整 Data Mode/Stage/Time/Universe | 12 列，高密度双栏或四栏 | 完整列、证据侧栏 | 页内右上与底部 Gate 均可见 |
| 1024 | 左导航收至 72 px；上下文保持文字标签 | 8 列，四栏改二栏 | 低优先列进入详情抽屉 | 操作保持文字，不只留颜色图标 |
| 768 | 抽屉导航；上下文变两行粘性条 | 单栏，关键摘要在详情前 | 表格横向滚动并冻结首列 | 主操作粘底，阻断原因在按钮旁 |
| 320 | 单一页面标题；Mode/Stage/Trust 可展开且默认显示文本值 | 单栏；INPUT–GATE 折叠但 Gate 默认展开 | 图表提供数值表，表格转记录列表 | 只保留一个主操作；危险或越权动作不存在 |

> 待裁决冲突（2026-08-14）：本表 1440 原型记录为 224 px 左导航，但权威 SPEC-045 要求桌面展开
> 280 px、收起 72 px。当前工程实现遵守 SPEC-045 的 280/72 px；224 px 只保留为原型差异，不构成
> Spec 变更。若采用 224 px，必须先由用户批准并同步更新 Spec 与本蓝图。

所有视口中 `normalized_current`/`pit_verified`、`current_research`/`strict_historical` 和
`research`/`shadow`/`paper` 都保留原始文本标签，不仅依赖颜色或 tooltip。

### 7.3 原型交互连线验收

Figma Prototype 模式需要按以下 frame id 连成一条可演示主路径；每次跳转保留 Research Time、
Data Mode、Deployment Stage 和 Universe 上下文：

```text
desk-daily-workstation
→ research-universe-screen
→ security-overview-600519-fused-v2
→ security-investmentview
→ 14-approvals-reviewer-queue
→ factors-alpha-model
→ portfolios-construction
→ portfolios-realistic-backtest
→ 12-timing-shadow-monitor
→ portfolios-attribution
```

辅助入口必须从当前页打开 evidence、blocker、run 和 lineage 详情，并能返回来源页。严格路径被
阻断时留在当前页显示原因，不跳到伪成功页。2026-08-14 已完成的主路径运行节点为：

```text
3:398 → 3:726 → 24:400 → 15:2 → 9:883
→ 7:5 → 7:303 → 7:712 → 9:431 → 7:1348
```

对应 Desk → Universe → Security 融合页 → InvestmentView → Approvals → Alpha → Construction →
Realistic Backtest → Timing Shadow → Attribution。InvestmentView 的 evidence、Backtest 的 blocker
卡片与 InvestmentView 的 run id 均已连接到 Data Quality & Lineage，并使用 `Click → Back` 返回
各自来源页；误加的 `Drag → Back` 已删除。这些是四类详情的代表入口，不表示每一个静态标签都已
设置热点。Free/Starter 方案对同一对象的多动作有限制，主路径采用顶层 Frame 整页点击；这只是
原型演示约束，不是运行时交互合同。

融合页精确设计节点：
<https://www.figma.com/design/mrt216q7X7NGqFhRjwQS3f/Fundamental-Quant-%E2%80%94-%E4%BA%A7%E5%93%81%E8%93%9D%E5%9B%BE%E4%B8%8E%E9%AB%98%E4%BF%9D%E7%9C%9F%E5%8E%9F%E5%9E%8B?node-id=24-400&t=R538S55yXyPUxZr9-0>。
完整产品演示入口从 `desk-daily-workstation` 开始：
<https://www.figma.com/proto/mrt216q7X7NGqFhRjwQS3f/Fundamental-Quant-%E2%80%94-%E4%BA%A7%E5%93%81%E8%93%9D%E5%9B%BE%E4%B8%8E%E9%AB%98%E4%BF%9D%E7%9C%9F%E5%8E%9F%E5%9E%8B?node-id=3-398&t=R538S55yXyPUxZr9-0&scaling=min-zoom&content-scaling=fixed&page-id=0%3A1&starting-point-node-id=3%3A398>。
直接打开 Universe 的演示 URL 也可验证新版个股页：
<https://www.figma.com/proto/mrt216q7X7NGqFhRjwQS3f/Fundamental-Quant-%E2%80%94-%E4%BA%A7%E5%93%81%E8%93%9D%E5%9B%BE%E4%B8%8E%E9%AB%98%E4%BF%9D%E7%9C%9F%E5%8E%9F%E5%9E%8B?node-id=3-726&t=R538S55yXyPUxZr9-0&scaling=min-zoom&content-scaling=fixed&page-id=0%3A1&starting-point-node-id=3%3A398>。

## 8. 原型确认后的实施顺序

1. 用原型替换当前 Desk 的工程能力表；
2. 按 P5 完成 Security、估值/改善、InvestmentView、Alpha Model 和 Screen；
3. 按 P6 完成 Construction、Backtests、Risk、Scenarios 和 core Attribution；
4. 按 P7 完成 Timing Lab、Shadow 和 Timing Monitor；
5. P8/P9 补 Events、Cases、全监控和统一归因；
6. 每个页面按合同测试 → API 测试 → 前端测试 → 浏览器验收执行 TDD；
7. PIT 暂缺时相关严格路径继续失败关闭，不阻塞其他工程能力开发。

## 9. P5–P7 原型到 TDD 工作包映射

### 9.1 P5

| TDD 切片 | 领域/API 先行测试 | 前端合同测试 | 浏览器验收 |
|---|---|---|---|
| P5-UI-01 Security Master | PostgreSQL Security/Listing/Industry reader；不存在名称时不推断 | Header、研究时点、trust、四问状态 | 从 Screen 精确进入 Security；无公司名时诚实显示代码 |
| P5-UI-02 估值与改善 | 冻结 bundle、cutoff、formula/dataset/version、缺失 blocker | 行业口径、同业、隐含预期、改善/一次性项目 | current partial 与 strict blocked 在视觉和文案上可区分 |
| P5-UI-03 InvestmentView | 四态、distribution、downside、residual 闭合、hash、append-only | 20/60/120D、瀑布、证据、catalyst/invalidator、Frozen Artifact | Security → View → Evidence → Submit Review；未生成 Artifact 不伪造 ID |
| P5-UI-04 Alpha Model | exact FactorVersion/Review/View/Universe binding；Snapshot research/forward 隔离 | 权重、资格、coverage、相关性、Snapshot empty | 无 PIT 时 Snapshot=0，页面仍完整显示所有 blocker |
| P5-UI-05 Reviewer | 服务端身份、用途、批准/拒绝/撤回与 append-only | pending/approved/rejected/blocked 和禁用原因 | 提交 View → Approvals → 返回结果；参数不能提升 scope |

### 9.2 P6

| TDD 切片 | 领域/API 先行测试 | 前端合同测试 | 浏览器验收 |
|---|---|---|---|
| P6-UI-01 Construction | Top-N/ER 权重、prior portfolio、现金、单股/行业/换手/参与率约束 | Policy、持仓、约束诊断、blocked intents | Alpha → Construction；无 Snapshot 时不生成伪持仓 |
| P6-UI-02 Realistic Backtest | signal time、next tradable、T+1、lot、费用、滑点、停牌/涨跌停/ST/退市、公司行动 | equity curve、trade ledger、blocked order drill-down | 盘后信号不能当日收盘成交；所有阻断可钻取 |
| P6-UI-03 Dual Engine | Internal/RQAlpha 相同 signal/target export 与 reconciliation | 逐日/逐笔 diff、分类、容差 | 从 Backtest 打开 diff，差异不被汇总数字掩盖 |
| P6-UI-04 Risk R0 | exposure、shrinkage、specific/total、benchmark relative、component closure | exposure、贡献、限额、RiskModelDecisionRecord | Construction → Risk；贡献与总风险闭合 |
| P6-UI-05 Scenarios | 历史/假设情景、传导、coverage、unavailable | 情景表、损益分解、InvestmentView invalidator | 未映射暴露不显示 0 |
| P6-UI-06 Attribution | market/industry/style/selection/cost/residual 闭合 | 瀑布、状态、evidence、outcome | core-only 明确；Timing/Event/Execution 不伪装完整 |

### 9.3 P7

| TDD 切片 | 领域/API 先行测试 | 前端合同测试 | 浏览器验收 |
|---|---|---|---|
| P7-UI-01 Labels/Features | PIT 时间、overlap、标签与生产隔离 | feature/label readiness 和 blocker | 缺宏观发布时间时 strict 明确阻断 |
| P7-UI-02 Active Model | 静态、MA、Vol Target、逻辑/线性主动模型；distribution/adjustment | 模型与基线对照，主动模型真实存在 | Timing Lab 不把被动控仓冒充主动预测 |
| P7-UI-03 Validation | walk-forward、Brier/log loss/calibration、HAC、DM、net utility | 校准、子期、regime、成本后对照 | 样本外和前瞻结果严格分开展示 |
| P7-UI-04 Shadow | immutable daily forecast、no backfill/edit、outcome evaluator | ledger、outcome、drift、PromotionReview | Lab → Shadow；未晋级对组合影响为 0% |
| P7-UI-05 Monitoring | drift/calibration/incident 与撤回 | Timing Monitor、告警、审查入口 | 失败只阻断或创建 Review，不静默调整模型 |

每个切片的完成定义仍包括领域单元、Repository integration、API contract、前端测试、构建和浏览器证据；页面截图或 Figma 视觉相似不能替代运行时合同验证。
