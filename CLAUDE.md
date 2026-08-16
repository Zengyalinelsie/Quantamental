# Claude Code 项目交接与开发指南

> 最后核对日期：2026-08-15
>
> 当前代码基线：`f703d08 docs: add Claude Code project handoff`
>
> 当前分支：`main`

本文件用于帮助 Claude Code 快速理解项目、恢复开发上下文并选择下一项工作。它是操作指南，
不是新的需求真源，也不能覆盖 `AGENTS.md`、系统 Spec、已接受 ADR 或实施 Plan。

本次修订把“按原型交付真实运行时产品”提升为与 Data/Gate 并行的强制轨道。旧版只要求继续
Step 02 Task 1；只完成那项数据探针不会重做前端，也不会实现原型表达的全部能力。

## 0. 开始任何工作前

必须完整阅读以下文件，并按顺序解决冲突：

1. `AGENTS.md`：仓库、安全、数据、交易和协作边界的最高优先级真源；
2. `docs/07-detailed-system-spec.md`：系统 MUST/SHOULD/MAY 合同；
3. `docs/adr/` 中所有与当前任务相关且状态为 Accepted 的 ADR；
4. `docs/08-detailed-implementation-plan.md`：阶段、工作包和 Gate；
5. `docs/18-product-blueprint-and-prototype.md`：产品信息架构与交互合同；
6. `docs/22-prototype-runtime-gap-audit.md`：31 页当前运行时差距和三轴状态；
7. `docs/plans/README.md` 和对应 `docs/plans/step-*.md`：阶段实现级 Spec/Plan；
8. `docs/plans/track-00-prototype-runtime-delivery.md`：PUI-00–PUI-09 原型运行时交付轨道；
9. `docs/*-implementation-evidence.md`：只记录已发生的事实，不能反向修改需求。

发现这些材料互相冲突时，不要自行选一个“看起来更合理”的版本。先报告冲突，暂停冲突部分；
安全且不受冲突影响的工作可以继续。

侧栏宽度冲突已于 2026-08-15 裁决，不再是待决项：

- 桌面展开侧栏统一为 **280 px**，收起 72 px，与 `SPEC-045` 一致；
- `docs/18` 响应式表已同步更新为 280 px，原先的 224 px 不再有效；
- Figma `desk-daily-workstation`（node `3:398`）实测为 248 px，属**已批准的设计差异**：
  1440 下主内容区为 1160 px 而非 Figma 的 1192 px，页面栅格以比例声明吸收该 32 px 差异；
- 实现精确 Figma 页面时按此比例换算，不得为对齐 1192 px 而改回 248 px。

设计输入限制已解除（2026-08-15）：全部 17 个关键 1440 Frame 的精确 SVG（保留可读文字）与结构化
节点摘要已入库 `docs/assets/prototype/`，通过 Figma REST API 取得，不再依赖 Starter MCP 配额。
任何 PUI 工作包都可直接使用这些资产作为视觉真源，复现命令见该目录 `README.md`。

仍然成立的边界：31 页蓝图不等于 31 个独立高保真 Frame；320/768/1024 **没有**独立 Figma Frame，
三档只有 `docs/18` 的文档级响应式合同，不是已通过的视觉证据；不得凭缩放截图猜测页面并声称
“与 Figma 一致”。

## 1. 项目是什么

这是一个面向 A 股多头选股、主动市场择时、事件研究、组合回测、Paper 执行和未来可选受限实盘的
可审计研究平台。核心目标是把“历史决策时点当时真正可知的数据”转换为可验证、可追溯、可冻结、
可审批的投资判断，并让研究、回测、Shadow、Paper 和未来 Limited Live 尽量共用同一决策与组合代码。

它首先是研究与决策基础设施，不是自动荐股机器人，也不是自主交易 Agent。平台不承诺盈利，
不把页面完成、自动测试通过、统计显著或一条成功样本等同于模型科学有效。

平台回答六个产品问题：

1. 哪些公司值得投资？
2. 当前价格是否有吸引力？
3. 公司是否正在改善或恶化？
4. 新事件改变了什么？
5. 当前整体股票仓位应是多少？
6. 研究结论能否真实执行？

统一公司决策对象是 `InvestmentView`。它必须包含证券、决策时间、期限、预期收益分布、下行风险、
质量/估值/改善/事件分项、置信度、催化剂、失效条件，以及完整的数据/公式/模型/代码/证据版本。
它不是“准确目标价”，也不能由 LLM 文本或前端字段临时拼成。

## 2. 产品完成线

不要用一个模糊的“项目已完成”覆盖不同阶段：

| 完成线 | 阶段 | 可交付能力 | 明确不代表 |
|---|---:|---|---|
| 核心研究 MVP | P6 | Screen → Security → InvestmentView → Portfolio → 现实回测 → Risk → 核心归因 | 不含成熟 Timing、事件 Agent、统一运营监控 |
| 成熟研究产品 | P9 | 研究、因子、组合、事件、Timing、监控、治理和审批形成日常工作流 | 尚未完成 Paper 执行职责闭环 |
| Paper-ready | P10 | 模拟订单、成交、持仓、现金、对账、Incident、恢复和 kill switch 闭环 | 不代表获准实盘 |
| Limited Live | P11 | 只在单独授权下逐级开放只读对账和人工批准的最小真实执行 | 不代表策略盈利或无人值守交易 |

P11 是可选项目。没有用户针对券商、账户、标的、金额和操作范围的新的明确授权，不得开始真实账户写入、
下单、撤单或改单。

### 2.1 原型完成线

“页面像原型”和“原型表达的能力已实现”是两个不同问题：

- 关键页视觉交付：按 PUI-00–PUI-04 先实现 Shell、Desk、Universe/Screen、Security、InvestmentView、
  Approvals、Alpha，以及已有 Factor/System API 的产品化；
- 核心研究 MVP：P6 + PUI-05；
- 成熟研究产品：P9 + PUI-06–PUI-08；
- 31 页完整非实盘/Paper-ready 产品：P10 + PUI-09；
- P11 Limited Live 不属于“把原型做完”，必须另行授权。

所以不能承诺“执行本文件的第一项任务后，全部能力就完成”。只有相应 P5–P10 领域、数据、API、治理、
页面和真实 Gate 分别满足，才能说原型表达的完整非实盘能力已落地。

## 3. 架构与技术栈

### 3.1 总体架构

- Python 3.11+ 模块化单体；
- FastAPI 后端；
- React 19 + TypeScript + Vite 前端；
- PostgreSQL 保存治理、证据、规范化事实、研究和 serving 数据；
- Parquet 与 DuckDB/Polars 适合价格、特征、标签和回测面板；
- 本地文件系统或 S3/MinIO 兼容对象存储保存原始证据与冻结 Artifact；
- worker 负责摄取、资格检查、计算、Shadow 和导出；
- 第一版不拆微服务，不引入 Spark/Kubernetes 作为默认复杂度。

### 3.2 Python 依赖方向

```text
platform/src/a_share_platform/
  domain/       # 纯领域对象、值对象、状态机和数学合同；不依赖 Web/DB/provider SDK
  application/  # 用例编排；依赖 domain 和 ports，不直接依赖具体供应商
  ports/        # repository、source、governance、execution 等抽象合同
  adapters/     # PostgreSQL、Parquet、对象存储、provider、Qlib 等实现
  api/          # FastAPI 只读/受控写 API、schema 和权限边界
  workers/      # dry-run 优先的任务入口
  validation/   # 统计与独立实现交叉检查
```

领域核心必须保持 provider-neutral、框架无关。不要让 `domain/` 导入 FastAPI、SQLAlchemy、
PostgreSQL client、供应商 SDK 或前端概念。

### 3.3 PostgreSQL 分层

开发库按职责分为：

```text
governance / evidence / observation / canonical / research / serving
```

`public` 只保留 migration ledger。任何新增表或字段都要尊重职责分层、不可变/append-only 合同和
用途隔离，不能为了方便查询把 current、strict、research、paper 数据混在一个无资格投影里。

### 3.4 前端结构

```text
platform/frontend/src/
  api/          # OpenAPI 快照、生成类型和 client
  app/          # Shell、路由和全局上下文
  components/   # 通用设计系统组件
  features/     # InvestmentView、Screen 等业务组件
  pages/        # 工作区页面
  navigation/   # 一级/二级导航
  state/        # 明确受控的客户端状态
  test/         # 测试工具与合同
```

前端只能消费服务端投影。不能在浏览器里重算排名、提升 trust、推断审批状态或拼装 InvestmentView。

## 4. 必须始终分开的治理轴

### 4.1 数据模式

- `current_research`：允许 `normalized_current` 或更高可信度，适合今天的私人研究；
- `strict_historical`：只允许 `pit_verified`，且每条输入必须满足 `available_at <= decision_time`。

给 current 数据补一个时间戳不能把它升级为 PIT。可信状态只能由明确的数据治理流程提升，
不能由 Agent、模型、API 或页面提升。

### 4.2 部署阶段

- `research`
- `shadow`
- `paper`
- `limited_live`

数据模式与部署阶段是两条独立轴，不能把 `current_research`、`research`、`shadow` 混为一种状态。

### 4.3 可信状态

- `raw`：原始抓取，尚未规范化；
- `normalized_current`：可用于今天的研究，但未证明历史可用时间；
- `pit_verified`：来源、首次披露/修订、`available_at` 和系统时间已经验证。

### 4.4 时间语义

至少明确区分：

- 经济/报告期时间；
- 发布或首次公开时间；
- 市场可用时间 `available_at`；
- 决策时间 `decision_time`；
- 系统获取/知识时间；
- 修订有效区间。

所有时间必须 timezone-aware。严格历史查询遇到时间倒置、歧义或证据缺失时必须失败关闭。

### 4.5 用途与审批

Research、Shadow、Paper、Limited Live 的审批 scope 不互相隐含。一个 FactorVersion、ModelVersion、
Artifact 或 Snapshot 被允许用于 research，不代表它可用于 paper 或 live。科学失败也不能通过行政审批
覆盖成成功。

### 4.6 不可变性与追溯

生产数字必须追溯到 DatasetVersion、UniverseVersion、定义/公式/模型版本、代码版本、Run、Artifact、
hash、lineage 和审批用途。重复写必须幂等；same ID/different semantics 必须冲突关闭；失败记录不能删除
或改写成成功。

### 4.7 页面完成三轴

每个页面必须分别报告，不能只写一个 `done` 或 `verified`：

| 轴 | 含义 | 当前全局事实 |
|---|---|---|
| Design Parity | 精确 Figma/批准响应式合同、视觉结构和交互对照 | 0/31 verified |
| Runtime Product | 真实 API 驱动六态、权限、错误、上下文、网络和控制台正确 | 约 12 页 partial，19 页 placeholder |
| Domain/Capability | 领域、存储、API、工作流和阶段 Gate | 按 P2–P10 分别记录 |

任何一轴通过都不能自动提升另一轴，更不能推出模型科学有效、Promotion Approval、Paper-ready 或
Limited Live。

## 5. 仓库边界

```text
sources/
  daily_stock_analysis/     # 只读产品形态、Agent/报告/通知、多源接入供体
  legacy_quant_platform/    # 只读 PIT、版本、因子、信号、组合、现实回测合同供体
docs/                       # 权威设计、Plan、ADR、迁移判断与 Evidence
platform/                   # 所有新实现
```

硬边界：

- 不直接修改 `sources/daily_stock_analysis` 或 `sources/legacy_quant_platform`；
- 不把来源仓库整目录复制进新平台；迁移前先写 ADR、许可证判断和目标合同；
- 不触碰 `/Users/macbook/agent-agnostic-stock-skills-clean` 的未提交工作树；
- 新实现只进入 `platform/`，权威决策与迁移说明进入 `docs/`；
- 不使用 LLM 文本作为价格、财务数值、公告时间或交易结果的权威来源；
- Agent 可提取、分类、解释和提出假设，但不能绕过数据、风险、审批或交易权限门。

## 6. 当前开发进度

### 6.1 总体判断

当前准确位置是：**P5 工程能力已经收口，但真实 P5 产物 Gate 没有通过；根本依赖仍在 P2/P4。**

后续不能直接把 P6 当成下一项领域实现，但也不能继续忽略前端。现在有两个独立、可并行的正确队列：

1. **Data/Gate**：`docs/plans/step-02-p2-pit-data-remediation.md` Task 1，D0 strict-PIT 数据源资格探针；
2. **Prototype/Product**：PUI-00 设计基线，然后 PUI-01 Desk、PUI-02 Universe/Screen、PUI-03 P5
   黄金路径。

Data 队列决定真实对象何时能 ready；PUI 队列决定产品是否按原型呈现真实六态。两者共享合同但提交、
状态和证据分开，任何一方都不能用 fixture 绕过另一方。

### 6.2 阶段状态

| 阶段 | 当前状态 | 已完成的主要能力 | 仍缺或阻断 |
|---:|---|---|---|
| P0 | 核心合同已实现；权威文档状态仍有历史冲突 | DataMode、DeploymentStage、RunContext、双时间、InvestmentView 四态和 residual 等 | `docs/08` 仍写 `in_progress`，不要擅自改为 Gate 通过 |
| P1 | Capability Gate 已通过 | 工程骨架、账本、权限骨架、API envelope、前端 Shell、CI/架构守卫 | 后续阶段继续扩充真实业务，不重做底座 |
| P2 | 工程能力较完整，Gate 未通过 | 当前 Security Master/Universe、provider/sink、质量、覆盖和 lineage 链 | 2018+ 完整历史 Universe、XBSE、全范围行情、股本、公司行动和严格 PIT 资格 |
| P3 | 小样本 Capability Gate 已通过 | 4 家公司、8 份官方 PDF、2 条修订链、双时间事实、真实诊断页、被动 Timing Shadow baseline | 不等于全市场 PIT 财务或主动 Timing |
| P3.5 | current-only 财务扩容完成 | CSI500 500 家 × 2018–2025 年末三表，12,000/12,000 UoW，35,505 条 observation；另有 CSI300 30 家 pilot | 仍是 `normalized_current`，不能用于 strict historical；78 个合法空期保持空而非填零 |
| P4 | W00–W06 工程能力完成，Gate 未通过 | 三类 company-level baseline、统计引擎与独立库交叉验证、Experiment/Reviewer、Qlib exchange、Factor Workspace | 没有合格 PIT 截面/forward labels；最新真实资格审计失败，没有 score/IC/RankIC 或晋级 |
| P5 | Step 1 工程范围 `verified`；真实 Gate 未通过 | InvestmentView/Signal 合同、append-only ledger、研究 API/UI、Frozen Artifact、Outcome worker、估值模型与 bundle v2、当前运行态四视口响应式 | 没有真实 qualified bundle/View/Review/SignalSnapshot/Artifact；P5 黄金路径尚未完成原型一致性 |
| P6 | dependency blocked | Spec/Plan 已存在 | 依赖真实 P5 冻结输入 |
| P7 | dependency blocked | Spec/Plan 已存在 | 依赖数据、P6 和主动 Timing 研究 |
| P8 | dependency blocked | Spec/Plan 已存在 | 依赖合格事件/文档来源和受治理 Agent 链 |
| P9 | dependency blocked | Spec/Plan 已存在 | 依赖 P6–P8 稳定输出 |
| P10 | dependency blocked | Spec/Plan 已存在 | 依赖成熟研究产品和 Paper OMS 安全闭环 |
| P11 | `AUTH` | 只有 Spec/Plan | 需要新的、明确的真实账户授权 |

### 6.3 最近完成的 P5 工作

交接前最后一个功能提交是 `768fd4f`，完成了 P5 Task 5 的响应式 TDD 和真实 Chrome 验收：

- 1440/1024/768/320 四个 CSS 视口；
- 1440 使用 280 px 展开侧栏，1024 自动收为 72 px，768/320 使用移动 Drawer；
- 每个视口均验证 `document.scrollWidth === document.clientWidth`，没有页面级水平溢出；
- 顶部运行上下文可断行，Universe 控件可换行且不再右侧裁切；
- 验证导航、current/historical Universe、历史日期警告、Security 搜索、Screen、InvestmentView、
  Alpha blocker、空态和一次显式网络失败/恢复；
- 正常重载没有 4xx/5xx，控制台没有 error/warning；
- 没有注入 runtime fixture；真实运行时只有空 Universe 和 unavailable P5 blocker；
- 因数据库没有 ready/partial Screen 或 InvestmentView，浏览器验收不包含伪造的 ready 产物。

最近完整验证基线：

```text
Backend unittest: 817/817 passed
Frontend Vitest: 73/73 passed
Ruff: passed
mypy: 175 source files passed
compileall: passed
Frontend lint: passed
Frontend build: passed
```

Vite 仍有既有 AntD large-chunk warning。不要隐藏 warning 或把它误写为已修复。

详细事实见 `docs/21-p5-implementation-evidence.md`。

### 6.4 当前原型/前端事实

最新审计见 `docs/22-prototype-runtime-gap-audit.md`：

- 31 个页面位约 12 个只有不同程度的合同/API 接线；
- 19 个仍是通用 unavailable 占位；
- Design Parity 为 0/31；
- `/desk` 是硬编码的 16 行工程能力表，不是原型 `desk-daily-workstation` 的 Platform Pulse；
- `/research` 是 Universe/Screen/P5 blocker 的纵向技术页，不是原型双栏高密度工作台；
- `/portfolios`、`/monitoring` 的主要页面仍未实现；
- P5 四视口证据只证明当前 empty/unavailable 运行态没有页面级溢出或明显裁切，不证明 Figma parity。

前端现在没有按原型全面改，根因不是原型“不重要”，而是旧执行队列没有跨阶段 PUI work package，
阶段 Plan 又只在末尾写笼统的“API 和页面”。现在以 PUI Track 修正这个计划缺口。

### 6.5 当前真实运行态

运行时没有默认 fixture。未配置持久化、合格数据或身份提供者时，页面诚实显示 empty/unavailable/blocked：

- `/api/universes` 可能返回空集合；
- `/api/research/workspace` 会给出真实 blocker；
- anonymous identity 只有 `read_public`；
- InvestmentView、SignalSnapshot、Frozen Artifact 不能用 CLI 参数或 demo 值补造；
- 测试 fixture 只允许存在于测试合同中，不能进入 runtime bundle 或默认 API。

私人本地 PostgreSQL、Parquet、对象文件和供应商凭据不会随 Git 仓库自动复制到另一台机器。
Claude Code 拉取代码后，应先确认本机实际拥有的 DSN、migration、数据、SDK 和凭据，不能把本交接文档
描述的开发机事实假定为新环境事实。

## 7. 当前 Gate 阻断

### P2 数据阻断

- strict-PIT 字段主源和许可尚未通过新的 D0 qualification probe/ADR；
- 2018 至今 CSI300/CSI500 历史 Universe 不完整；
- XBSE、退市/代码变化、全范围行情、股本、公司行动覆盖不足；
- 财务首次披露、修订、`available_at`、保存条款和用途资格尚未形成可批量使用的主源闭环；
- current-only 数据不能升级为 `pit_verified`。

### P4 真实资格阻断

- 冻结窗口没有同时满足 `pit_verified`、coverage、`available_at` 和 lineage 的真实截面；
- 三条最新 ExperimentRun 失败，ValidationReport 不可晋级，FactorVersion 保持 draft；
- 没有真实 factor score、IC、RankIC、样本外和成本后证据。

### P5 真实产物阻断

- 没有合格 historical/industry/peer reference、FCF 政策和分析师来源；
- Outcome 的真实价格/日历/公司行动 source policy `P5-D1-01` 尚未批准；
- 没有真实 qualified frozen bundle → InvestmentView → Review → SignalSnapshot → Artifact 链；
- 真实 ready/partial 页面只能等数据库中存在合法对象后验收。

因此，任何人都不得声称：

- P2、P4 或 P5 Gate 已通过；
- 三类因子科学有效；
- Expected Return/InvestmentView 模型科学有效；
- 平台已具备可盈利策略、Paper-ready 或实盘能力。

## 8. 下一工作：Data/Gate 与 Prototype/Product 双轨

### 8.1 队列选择规则

- 若任务目标是数据资格、真实 Gate 或为 ready 对象建立可信输入，选择 Data/Gate；
- 若任务目标是页面结构、视觉、交互、六态或黄金路径，选择 PUI；
- 两个 work package 可以并行，但不要混在一个提交；
- PUI 可以在真实对象缺失时完成 empty/partial/unavailable 产品结构，不能制造 ready；
- Data/Gate 通过不能自动标记 Design Parity；PUI 通过不能自动标记 Capability/Gate；
- 未被指派时，默认从两条队列各报告一个下一候选，不能再宣称 Step 02 Task 1 是“唯一下一工作”。

### 8.2 Data/Gate 当前候选：Step 02 Task 1

#### 8.2.1 任务范围

先只做 `docs/plans/step-02-p2-pit-data-remediation.md` 的 **Task 1：D0 数据源资格探针与 ADR**。
不要同时开始 Task 2–6，不要在字段主源 ADR Accepted 前进行 bulk import。

预期改动边界：

- provider probe：`platform/src/a_share_platform/adapters/providers/`；
- probe tests：`platform/tests/test_*_probe.py`；
- 数据源目录：`docs/14-data-source-catalog-and-agent-routing.md`；
- 资格政策：遵守 `docs/adr/0007-strict-pit-source-qualification-policy.md`；
- 只有探针证据足够后，才新增字段主源 ADR；草案不能冒充 Accepted；
- 更新 `docs/plans/step-02-p2-pit-data-remediation.md` 的事实状态和对应 Evidence；若尚无专用 Evidence，
  先按现有文档纪律选择位置，不要让 Evidence 覆盖 Spec。

#### 8.2.2 探针必须验证什么

至少对候选来源逐项获得可复现证据：

1. 认证方式、当前环境是否实际可用、失败时的明确错误；
2. 所需字段是否真实存在，单位、币种、代码和语义是否明确；
3. 首次披露时间、修订链、历史版本和市场可用时间；
4. 历史指数成分、纳入/剔除、退市、代码/名称变化；
5. 2018 至今的实际可用范围、缺口和 retention；
6. 许可证、私人本地保存、缓存、派生和再分发限制；
7. 速率限制、并发限制、分页、重试、熔断和每日调用预算；
8. 未授权、字段缺失、部分响应、时间歧义、限流、网络错误和 provider schema 变化的失败语义；
9. 是否能支持 `pit_verified`，或只能停留在 `normalized_current`；
10. source priority 如何按字段声明，冲突如何显式暴露，禁止静默 fallback。

如果当前没有凭据或供应商不可用，探针应稳定返回“不可资格/不可评估”的结构化结果并保留证据，
而不是使用假响应、默认通过或把缺失字段填零。

#### 8.2.3 Data TDD 顺序

每个可验证行为都按以下顺序执行：

1. 先读对应 Spec/Plan/ADR 和已有 provider 合同；
2. 写一个最小、明确的失败测试；
3. 运行它并记录预期红测原因；
4. 写最小 provider-neutral 实现；
5. 运行定向测试转绿；
6. 增加失败语义、时间、许可、限流和 schema drift 边界测试；
7. 重构但保持绿色；
8. 运行适用集成、静态和全量验证；
9. 更新目录、ADR/Plan/Evidence，记录事实、限制和未通过项；
10. 审查 diff，保持一个 work package 一个提交。

不要先写实现再补“覆盖它的测试”。Evidence 中应记录真实红测和绿测结果，不编造命令输出。

#### 8.2.4 Task 1 的退出条件

Task 1 完成至少需要：

- probe 合同和失败语义有测试；
- 真实候选来源的小范围探针可复现；
- 字段、时间、许可、retention、限流、历史范围和缺口有证据；
- 数据源目录已更新；
- 字段主源 ADR 有明确状态和理由；
- 资格失败不会触发下载、批量写入或 trust 提升；
- 全量适用验证通过；
- 没有误宣称 P2/P4/P5 Gate 或模型有效。

即使所有工程测试通过，只要真实来源资格证据不足，Task 1 的正确结果仍可以是“未获资格”。

### 8.3 Prototype/Product 当前候选

优先顺序：

1. **PUI-00**：冻结 14 个关键 Frame 的 file key/node id/尺寸/状态，恢复可取得的结构化 design context，
   为缺少独立高保真 Frame 的页面登记 `design_status=missing`；
2. **PUI-01**：以服务端 Desk projection 替换硬编码工程能力表，按 `desk-daily-workstation` 实现
   Platform Pulse；
3. **PUI-02**：把 `/research` 改为左侧 Universe/Factor Builder + 右侧排名表，保留真实 blocker；
4. **PUI-03**：完成 Universe → Security fused overview → InvestmentView → Evidence → Approvals →
   Alpha 的 P5 原型黄金路径。

### 8.4 UI TDD 与设计到代码顺序

每个 PUI 切片必须：

1. 先读 PUI Track、目标 Step Plan、`docs/18` 和 `docs/22`；
2. 取得精确 Figma file key/node id，并按 Figma design-to-code 流程读取结构化 design context；
3. 若 context 因权限/限额失败，记录阻断；只有 Security/InvestmentView 可改用仓库精确 SVG；
4. 先写会失败的 API/component/layout/interaction 测试，并运行确认真实红测；
5. 建服务端 projection/类型，再做 React 页面；前端不重算业务结果；
6. 同一结构覆盖 loading/error/empty/partial/unavailable/ready，runtime 无默认 fixture；
7. 1440 对照精确节点，1024/768/320 按批准合同重排；
8. 检查水平溢出、右侧裁切、键盘/焦点、控制台、网络和错误恢复；
9. 分别更新 Design Parity、Runtime Product、Capability 和 Evidence；
10. 一个可验证 PUI 切片一个独立提交，只有当前用户明确授权时 commit/push。

PUI-00 不是无限期只写清单。design context 一旦可用，优先交付用户可见的 PUI-01 Desk；若精确 Desk
节点仍受工具阻断，可继续完成服务端 projection、六态合同红测和无 fixture 边界，但不能宣称视觉完成。

## 9. 开发方式

### 9.1 开始前检查

```bash
git status -sb
git log -5 --oneline
git diff --check
```

先确认工作树是否已有用户改动。不要覆盖、清理、reset 或提交与当前工作包无关的文件。

### 9.2 TDD 与最小改动

- 一个 task 只覆盖一个可验证行为；
- 先红后绿，记录真实失败原因；
- 优先复用已有 domain/port/repository，不建立第二输入真源；
- 新 provider 细节留在 adapter；
- 缺失、无权限、冲突、时间不可信必须显式表达，禁止自动填零；
- worker 默认 dry-run；任何真实写入需要已有合同规定的 ack、用途、DSN、domain/date/shard；
- 真实网络调用、数据保存和许可必须符合 Accepted ADR；规划文档本身不构成下载授权。
- 前端测试 fixture 只用于 contract/layout 测试，不得进入默认 dev/prod bundle 或 API；
- UI 改动必须有目标 Figma node/批准设计、四档浏览器证据和三轴状态，不能凭主观“更好看”验收。

### 9.3 文档纪律

代码改变行为时同步更新：

- 对应 `docs/plans/step-*.md` 的 task 状态；
- 阶段 Evidence 中的红测、绿测、真实运行、限制和未完成项；
- 数据源变化更新 `docs/14-data-source-catalog-and-agent-routing.md`；
- 重大、不可逆或涉及许可/主源的决定写 ADR；
- 只有事实和 Gate 条件完全满足时才改变 Gate 状态。

不要只更新 `README.md` 而遗漏权威 Plan/Evidence，也不要用 Evidence 文档偷偷改变 Spec。

### 9.4 Git 纪律

- 一个 task/work package 一个独立提交；
- 明确 stage 文件，不对混合工作树使用无差别 `git add -A`；
- 提交前检查 `git diff --cached`；
- 未经当前用户明确授权，不 commit、不 push；
- 即使允许 commit/push，也不要把本地数据、数据库 dump、凭据、对象存储或供应商缓存提交；
- 不修改 donor 仓库，不提交与任务无关的格式化噪声。

## 10. 常用命令

### 10.1 Python 与完整验证

从仓库根目录执行：

```bash
cd platform
PYTHON_BIN="$PWD/.venv/bin/python"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 11), sys.version'
PYTHONPATH=src "$PYTHON_BIN" -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache "$PYTHON_BIN" -m compileall -q src
"$PYTHON_BIN" -m ruff check src tests
"$PYTHON_BIN" -m mypy src
npm --prefix frontend test -- --run
npm --prefix frontend run lint
npm --prefix frontend run build
git diff --check
```

也可使用统一验证脚本；真实 PostgreSQL migration smoke 只有在明确提供本地验证库 URL 时运行：

```bash
cd platform
PYTHON_BIN="$PWD/.venv/bin/python" \
ASP_DATABASE_URL=postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_layered_dev \
./ci/verify.sh
```

不要因为本机缺少私人数据库或 provider 凭据，就把依赖真实环境的断言改成默认通过。

### 10.2 本地 PostgreSQL、API 和前端

项目固定使用 PostgreSQL 主机端口 55432、API 端口 8010、前端端口 5173，不占用另一个项目常用的 8000。

终端 1：

```bash
cd platform
docker compose up -d postgres
PYTHONPATH=src .venv/bin/python -m a_share_platform.adapters.postgres.cli
ASP_DATABASE_URL=postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_layered_dev \
PYTHONPATH=src .venv/bin/python -m uvicorn a_share_platform.api.app:app \
  --host 127.0.0.1 --port 8010 --reload
```

终端 2：

```bash
cd platform/frontend
npm ci
PYTHON_BIN=../.venv/bin/python npm run generate:api
npm run dev
```

浏览器入口：

- 前端：`http://127.0.0.1:5173/`
- P5 研究页：`http://127.0.0.1:5173/research`
- API：`http://127.0.0.1:8010/`

Vite 默认把 `/api` 代理到 `http://127.0.0.1:8010`。前端改动必须另外做 320/768/1024/1440
真实浏览器验收，检查水平溢出、右侧裁切、导航、六态、控制台和网络错误。组件测试或 curl 不能替代
浏览器证据。

## 11. 常见错误

- 把 `normalized_current` 当作 `pit_verified`；
- 只看 report period，不检查首次披露、修订和 `available_at`；
- 用今天的成分股回填历史 Universe；
- 用当前 500/800 家有数据行宣称历史覆盖完成；
- 把缺失字段、无权限或不可比值填成 0；
- 在 application/domain 中直接调用供应商 SDK；
- 用前端重算 rank、score、审批或信任等级；
- 用 runtime fixture 让页面看起来 ready；
- 把测试 fixture 数字写成真实模型产物；
- 把统计引擎与独立库数值一致写成因子有效；
- 把 Capability Gate 与 Promotion Gate 混淆；
- 为追求通过而改变冻结窗口、样本、阈值或过滤规则；
- 隐藏失败 Experiment、质量冲突或 provider 限流；
- 在没有 Accepted ADR 时批量下载、保存或宣称主源已选定；
- 在没有新授权时接账户或执行交易写操作。

## 12. Claude Code 首次接手清单

1. 拉取最新 `main`，确认 HEAD 和工作树；
2. 完整阅读本文件第 0 节列出的真源；
3. 对照 `docs/22` 复核当前 12 partial / 19 placeholder / 0 parity，不得声称现前端匹配原型；
4. 阅读 Data Step 02、ADR-0007 和 PUI Track，向用户分别报告两个下一候选；
5. 检查 Python、Node、PostgreSQL、provider/Figma 权限和凭据，不假设开发机私有状态已迁移；
6. 若接 Data 任务：只选 Step 02 Task 1 的一个最小 probe 行为，先红测；
7. 若接前端任务：先取精确 Figma design context，再选 PUI-01/02/03 的一个最小垂直切片，先红测；
8. 最小实现转绿，补齐失败、空、部分、不可用和权限语义；
9. 更新对应 Track/Step Plan/Evidence，分别报告三轴；
10. 运行定向和完整适用验证；UI 另做 1440/1024/768/320 真实浏览器验收；
11. 检查 diff，只提交当前工作包；没有当前用户授权则停在未提交状态。

如果真实探针需要新的供应商凭据、付费许可、保存授权或会产生外部副作用，先报告具体缺口并等待用户。
不要用替代假数据跨过 D0 决策门。

如果 Figma 结构化节点读取仍受 Starter/View seat 配额阻断，报告具体 node 和错误。不要用截图猜测未有
仓库精确资产的页面并写成“还原完成”；可以继续不依赖视觉猜测的 API projection、类型、六态红测和
运行时无 fixture 约束。

## 13. 建议给 Claude Code 的首轮指令

下面这段用于 Claude Code 拉取本次文档提交后的第一轮工作；它不会授权 commit/push、外部付费数据或
任何交易写操作：

```text
先完整阅读 AGENTS.md、CLAUDE.md、docs/07、docs/08、docs/18、docs/22、
docs/plans/README.md 和 docs/plans/track-00-prototype-runtime-delivery.md。

不要把当前前端描述成已匹配原型：当前约 12/31 页面局部接线、19/31 占位、Design Parity 0/31。
本轮以原型驱动前端为主任务，从 PUI-00 → PUI-01 做一个可独立验收的垂直切片：

1. 先确认 desk-daily-workstation 的精确 Figma file key/node id，按 design-to-code 流程取得
   结构化 design context；若受权限或配额阻断，记录真实错误，不凭截图宣称高保真。
2. 检查 Desk 当前硬编码 capabilityRows、路由、Shell、token、API 和测试，先补红测证明 Desk
   不能继续渲染工程阶段表，并为服务端 Desk projection/页面六态写合同红测。
3. 最小实现 Platform Pulse：数据健康、Screen shifts、重大事件、组合、Timing、待办/审批、
   Active Failures 分区。尚未实现的域由真实 API 返回 unavailable，禁止 runtime fixture 和原型数字。
4. 1440 对照精确 Desk node；1024/768/320 按响应式合同验收水平溢出、右侧裁切、导航、运行上下文、
   六态、键盘/焦点、控制台、网络和错误恢复。
5. 分别报告 Design Parity、Runtime Product、Domain/Capability；PUI 通过不代表 P2/P4/P5 Gate、
   模型科学有效或 Paper-ready。
6. 更新 PUI Track、docs/22 和对应 Evidence，运行定向测试、后端全量、前端测试、ruff、mypy、
   compileall、lint、build 和 git diff --check。
7. 只保留本工作包改动。未经我当前明确授权，不 commit、不 push。

Data/Gate 的 Step 02 Task 1 是另一条独立队列，不要删除或降级，但不要把它和本 PUI 提交混在一起。
发现文档/设计/API 冲突时先列出精确证据；不受冲突影响的工作继续。
```
