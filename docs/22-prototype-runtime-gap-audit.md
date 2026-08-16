# 原型到运行时产品差距审计

> 审计日期：2026-08-15
>
> 代码基线：`f703d08 docs: add Claude Code project handoff`
>
> 审计对象：Figma 高保真原型、31 页产品蓝图、当前 React 运行时、Spec、总 Plan、Roadmap、Step Plans 与 Evidence
>
> 性质：当前事实审计；不替代 `docs/07-detailed-system-spec.md` 或 `docs/18-product-blueprint-and-prototype.md`

## 1. 结论

当前运行时前端不是高保真原型的实现完成态，而是领域合同、真实 API、失败关闭和响应式规则的技术验证壳。

截至本次审计：

- 31 个一级工作区页面位中，12 个具有不同程度的运行时合同/API 接线；
- 19 个仍是通用 `WorkspaceUnavailable` 或等价占位；
- 0 个页面完成了“对精确 Figma 节点的 1440 视觉一致性验收”；
- P5 已完成的 1440/1024/768/320 浏览器验收，范围是当前 empty/unavailable 运行态的布局、交互、
  网络和控制台，不是 Figma 视觉一致性 Gate；
- `/desk` 仍显示硬编码的工程能力表，和 `desk-daily-workstation` 原型的研究员工作台完全不同（**此条为 2026-08-15 审计时点事实；PUI-01 已于同日完成替换，见 §1 增量更新**）；
- `/portfolios`、`/monitoring` 的所有主要页仍是占位；
- P5–P10 的领域、数据、API、审批、组合、Timing、事件、监控和 Paper OMS 能力没有因为 Figma
  原型完成而自动存在。

**2026-08-15 PUI-01 完成后的增量更新**（上表为审计时点事实，保留不改写）：

- `/desk` 已改为消费服务端 `GET /api/desk`，七分区各自报告真实六态，硬编码 `capabilityRows`
  已删除；
- Desk 的 Design Parity 为 `parity_verified_with_known_deviation`，**不是** `parity_verified`：
  侧栏 280 px vs Figma 248 px 的差异已登记，320/768/1024 无 Figma Frame 依据；
- 因此 31 页的「完全逐像素 parity」计数仍为 **0/31**；Desk 是第一个完成结构级对照并显式记录
  差异的页面，不能据此宣称 parity 已通过；
- 设计输入阻断已解除（见 §2.2.1），17 个关键页均有仓库内精确视觉真源。

**2026-08-15 PUI-02 完成后的增量更新**：

- `/research?tab=universe-screen` 已改为 Figma 双栏结构：左侧只读 Screen 构建器 + 右侧排名表；
- 排名表补齐 `质量 / 估值预期差 / 改善 / 60日预期收益区间` 四列，投影自已冻结
  `InvestmentView.components`，以 view id **与** hash 双重匹配，不新建计算；
- 构建器为只读，不含权重输入与「运行 Screen」按钮，依据 `ADR-0012`；
- Universe & Screen 的 Design Parity 同为 `parity_verified_with_known_deviation`
  （构建器只读、Figma 示例值不入运行时），完全 parity 计数仍为 **0/31**；
- 新发现待修既有缺陷：`/factors` 在 320 视口存在页面级水平溢出，早于本工作包，登记待 PUI-04。

因此：

1. 只完成 `CLAUDE.md` 原先指定的 Step 02 Task 1，不会让前端接近完整原型；
2. 只做视觉页面，也不会获得原型表达的真实业务能力；
3. “完整 31 页非实盘产品”仍以 P10 为完成线；
4. 原型到运行时必须成为一条与数据/Gate 并行、但不绕过数据/Gate 的正式交付轨道。

对应实施计划：`docs/plans/track-00-prototype-runtime-delivery.md`。

## 2. 审计证据与限制

### 2.1 使用的真源

- 产品和安全合同：`docs/07-detailed-system-spec.md`；
- 产品信息架构、31 页、六态和黄金路径：`docs/18-product-blueprint-and-prototype.md`；
- Figma 文件：`mrt216q7X7NGqFhRjwQS3f`；
- 当前运行时：`http://127.0.0.1:5173/`，默认无 runtime fixture；
- 当前路由和页面：`platform/frontend/src/navigation/routes.tsx`、`app/AppShell.tsx`、`pages/`、`features/`；
- 实现事实：`docs/10`、`12`、`13`、`15`、`17`、`21` Evidence。

### 2.2 Figma 检查限制

2026-08-15 尝试通过 Figma `get_design_context` 读取以下精确节点：

- `3:398` `desk-daily-workstation`；
- `3:726` `research-universe-screen`；
- `24:400` `security-overview-600519-fused-v2`；
- `15:2` `security-investmentview`。

Figma Starter 方案返回 MCP 调用额度已用尽；当前账号为 Starter/View seat，无法取得新的参考代码和
结构化节点上下文。本次没有假装这些调用成功。已连接 Chrome 仍能打开同一文件并核对 1440 Frame：

- Desk 原型是 Platform Pulse、Screen 变化、重大事件、组合跟踪、Timing、待办和故障的复合工作台；
- Universe 原型是左侧筛选/因子构建器与右侧高密度排名表；
- 当前运行时 `/desk` 是单一工程能力表（**审计时点事实；PUI-01 已完成替换**）；
- 当前 `/research` 是 Universe 查询、空态和 P5 blocker 的纵向技术页。

仓库内只有两份可恢复的精确 SVG：

- `docs/assets/prototype/security-overview-fused.svg`；
- `docs/assets/prototype/investment-view.svg`。

真正开始某个 Figma 页面设计到代码时，仍必须先恢复该精确节点的 `get_design_context`；只有上述两页可在
工具受限时使用仓库 SVG 作为结构与视觉真源。不能用一张缩放截图猜其余页面的尺寸和组件细节。

### 2.2.1 设计输入阻断已解除（2026-08-15 更新）

§2.2 的 MCP 配额限制**已通过 Figma REST API 解决**；上节保留作为事实历史，不改写。

改用 `GET /v1/files/{key}/nodes` 与 `GET /v1/images/{key}`（Personal Access Token，scope 仅
`File content: read`）取得全部 17 个业务 Frame 的结构化节点树与精确 SVG，已入库
`docs/assets/prototype/`：

- 17 个 SVG 保留图层 id 与**可读文字**，合计 1.0 MB；
- `figma-node-summary.json` 含层级、尺寸、`layoutMode`、`itemSpacing`、文字、字号、字重、字体族；
- 导出参数、全部 18 个 node id 与复现命令见 `docs/assets/prototype/README.md`。

关键参数 `svg_outline_text=false`：默认导出把文字转成矢量路径，单页约 1.7 MB（17 页共 33 MB）
且文字不可读、不可搜索，对实现没有参考价值。

因此「除 Security/InvestmentView 外不得开始视觉编码」的限制不再适用于任何页面：
**17 个关键页现在都有仓库内精确视觉真源**，不依赖 Figma 会话或配额。

仍然成立：320/768/1024 没有独立 Figma Frame（见 §2.3），三档只有文档级响应式合同。

### 2.3 原型自身的覆盖边界

Figma 当前有 14 个关键 1440 高保真业务 Frame，以及一个 31 页完整产品蓝图。两者不是同一完成度：

- 14 个关键页可以作为独立页面的精确 1440 视觉参照；
- 31 页蓝图为全部页面提供信息架构和内容意图，但不是每页都有独立高保真 Frame；
- 320、768、1024 没有独立 Figma Frame；这三档只有响应式重排合同；
- `security-investmentview` 是 Security 的详情/黄金路径页面，不是六工作区 31 个 tab 中的一个独立 tab；
- 侧栏宽度：**2026-08-15 已裁决统一为 280 px**（展开）/ 72 px（收起）。冲突一度为三值——
  SPEC-045 = 280、`docs/18` 原写 224、Figma node `3:398` 实测 248；用户明确裁决采用 280，
  `docs/18` 与 `CLAUDE.md` 已同步。Figma 的 248 px 保留为**已批准的设计差异**：1440 下主内容区
  为 1160 px 而非 1192 px，栅格以比例吸收该 32 px。

所以，在补齐非关键页高保真设计和三档响应式设计前，不能承诺“31 页四视口逐像素与 Figma 一致”。
可以承诺的是：按已存在的高保真节点、设计系统和响应式合同开发，并对每个没有精确 Frame 的推导页
明确记录设计假设和用户验收结果。

## 3. 为什么当前前端没有按原型全面改

### 3.1 执行队列只表达数据 Gate，没有表达产品 UI 队列

`docs/plans/README.md` 把下一动作写成 Step 02 的 strict-PIT 数据源资格探针。这是数据和科学 Gate 的
正确优先级，但它没有同时登记一条原型到运行时产品轨道。Claude Code 按原 `CLAUDE.md` 执行时会继续
数据工作，不会主动重做 Desk 或 31 页。

### 3.2 总 Plan 有承诺，但没有跨阶段可执行工作包

`docs/08-detailed-implementation-plan.md` 已写明：

- 前端不是最后一次性建设；
- 现有 Desk 工程状态表应在原型确认后被真正每日工作台替换；
- `docs/18` 是 31 页与黄金路径真源。

但原有 Step Plans 只在每个阶段末尾放一个笼统的“API 和页面”Task，没有：

- 当前 31 页逐页状态；
- Figma node → route/component/API 的映射；
- Desk 先行替换任务；
- 视觉一致性与业务能力两套独立 Gate；
- 可在数据阻断时继续实现的 honest empty/partial/unavailable 页面范围。

### 3.3 “响应式通过”被错误地接近理解成“原型通过”

P5 Task 5 的真实 Chrome 验收是有效工程证据，但验收对象是当前运行态：

- 无页面级水平溢出；
- 无右侧裁切；
- 导航、上下文、Universe 控件和错误恢复可用；
- 控制台和正常网络无错误；
- 不注入 runtime fixture。

它没有对 `desk-daily-workstation`、`research-universe-screen` 或其他精确 Figma Frame 做结构、密度、
排版、组件和视觉差异验收。两类验收必须拆开记录。

### 3.4 当前 Desk 还包含过时的硬编码状态

`platform/frontend/src/pages/DeskPage.tsx` 的 16 行状态是本地常量，不是服务端 Desk projection。
其中仍写“等待 P4 统计引擎”“等待服务端身份与审批工作流”等已经被后续工程能力部分覆盖的旧说明。
即使这些文字全部更新，它仍不符合原型的研究员日常工作流，因此正确修复是替换产品结构和 API，
不是继续维护这张工程状态表。

## 4. 三类完成不能再混用

每个页面必须分别记录三个结论：

| 轴 | 完成条件 | 不能推出 |
|---|---|---|
| Design Parity | 精确 Figma/批准的响应式合同、视觉对照和交互路径通过 | API、数据和业务能力已完成 |
| Runtime Product | 六态由真实 API 驱动，权限、错误、证据和上下文正确，无 runtime fixture | 数据/模型已过科学或用途 Gate |
| Domain/Capability | 领域、存储、API、工作流和真实小样本满足阶段 Gate | 视觉与交互已经匹配原型 |

科学有效、Promotion Approval、Paper-ready 和 Limited Live 继续是额外独立结论。

页面状态建议只使用：

- `placeholder`：只有通用 unavailable 壳；
- `runtime_partial`：已有专用组件/API，但未覆盖页面合同或真实状态；
- `design_ready`：精确设计上下文和验收标准已齐；
- `design_parity_verified`：与批准设计完成真实浏览器对照；
- `runtime_verified`：六态、权限、网络、控制台和响应式通过；
- `capability_blocked` / `capability_verified`：只描述对应阶段业务能力。

不得用一个 `verified` 同时代替以上所有轴。

## 5. 31 页当前差距矩阵

下表的“当前运行时”基于 2026-08-15 代码与无 fixture 浏览器检查。`runtime_partial` 不等于视觉完成。

| # | 工作区 / 页面 | 当前运行时 | 独立高保真参照 | 能力阶段 | 原型轨道 |
|---:|---|---|---|---:|---|
| 1 | Desk / 今日工作台 | `runtime_verified`：服务端 Desk projection 七分区六态（2026-08-15） | `desk-daily-workstation` | P9 聚合；P2–P8 渐进 | PUI-01 |
| 2 | Research / Universe & Screen | `runtime_verified`：双栏构建器+12 列排名表，六态真实（2026-08-15） | `research-universe-screen` | P2/P5 | PUI-02 |
| 3 | Research / Security | `runtime_partial`：P5 View 组件接线，缺融合页信息架构 | `security-overview-600519-fused-v2` | P5/P8 | PUI-03 |
| 4 | Research / Events | `placeholder` | `10-events-intelligence` | P8 | PUI-07 |
| 5 | Research / Watchlists/Cases | `placeholder` | 31 页蓝图 | P8/P9 | PUI-07/PUI-08 |
| 6 | Factors / Catalog | `runtime_partial` | 31 页蓝图 | P4 | PUI-04 |
| 7 | Factors / Alpha Model | `runtime_partial`：readiness/blocker，真实 Snapshot 为 0 | `factors-alpha-model` | P5/P9 | PUI-04 |
| 8 | Factors / Timing Lab | `runtime_partial`：被动 baseline | `11-timing-lab` | P7 | PUI-06 |
| 9 | Factors / Experiments | `runtime_partial`：真实失败 Experiment | 31 页蓝图 | P4 | PUI-04 |
| 10 | Factors / Correlation Monitor | `placeholder`/空合同 | 31 页蓝图 | P9 | PUI-08 |
| 11 | Factors / Production | `runtime_partial`：生命周期/空生产态 | 31 页蓝图 | P4/P9 | PUI-04/PUI-08 |
| 12 | Portfolios / Construction | `placeholder` | `portfolios-construction` | P6 | PUI-05 |
| 13 | Portfolios / Backtests | `placeholder` | `portfolios-realistic-backtest` | P6 | PUI-05 |
| 14 | Portfolios / Risk | `placeholder` | `portfolios-risk-scenarios` | P6 | PUI-05 |
| 15 | Portfolios / Scenarios | `placeholder` | `portfolios-risk-scenarios` | P6/P9 | PUI-05/PUI-08 |
| 16 | Portfolios / Attribution | `placeholder` | `portfolios-attribution` | P6/P9/P10 | PUI-05/PUI-08/PUI-09 |
| 17 | Monitoring / Signals | `placeholder` | 31 页蓝图 | P5/P9 | PUI-08 |
| 18 | Monitoring / Portfolios | `placeholder` | 31 页蓝图 | P6/P9 | PUI-08 |
| 19 | Monitoring / Timing | `placeholder` | `12-timing-shadow-monitor` | P7/P9 | PUI-06/PUI-08 |
| 20 | Monitoring / Drift | `placeholder` | 31 页蓝图 | P9 | PUI-08 |
| 21 | Monitoring / Rebalance | `placeholder` | 31 页蓝图 | P9/P10 | PUI-08/PUI-09 |
| 22 | Monitoring / Execution | `placeholder` | 31 页蓝图 | P10 | PUI-09 |
| 23 | Monitoring / Incidents | `placeholder` | 31 页蓝图 | P9/P10 | PUI-08/PUI-09 |
| 24 | System / Catalog | `runtime_partial`：Dataset/Financial Evidence | 31 页蓝图 | P1–P3 | PUI-04 |
| 25 | System / Quality | `runtime_partial` | `13-data-quality-lineage` | P1–P3/P9 | PUI-04/PUI-08 |
| 26 | System / Lineage | `runtime_partial` | `13-data-quality-lineage` | P1–P5/P9 | PUI-04/PUI-08 |
| 27 | System / Jobs | `runtime_partial` | 31 页蓝图 | P1–P3/P9 | PUI-04/PUI-08 |
| 28 | System / Entitlements | `placeholder` | 31 页蓝图 | P9/P10 | PUI-08/PUI-09 |
| 29 | System / Users | `placeholder` | 31 页蓝图 | P9/P10 | PUI-08/PUI-09 |
| 30 | System / Agents | `placeholder` | 31 页蓝图 | P8/P9 | PUI-07/PUI-08 |
| 31 | System / Approvals | `placeholder`：已有最小服务端审批能力但无通用产品页 | `14-approvals-reviewer-queue` | P4/P5/P9/P10 | PUI-03/PUI-08/PUI-09 |

黄金路径额外详情页：

| 页面 | 当前运行时 | 高保真参照 | 原型轨道 |
|---|---|---|---|
| Security / InvestmentView | `runtime_partial`：Summary、distribution、waterfall、evidence、Artifact 权限入口 | `security-investmentview` + 仓库 SVG | PUI-03 |

## 6. 需要修正的文档口径

| 文件 | 审计发现 | 统一方式 |
|---|---|---|
| `README.md` | 仍写 P5 四视口未验收；未说明 31 页视觉差距 | 更新当前事实并增加原型轨道入口 |
| `docs/07-detailed-system-spec.md` | 页首仍把“用户原工作树”写成完整视觉真源 | 原工作树只保留 token/组件 provenance；产品/交互/页面视觉以 docs/18 + 精确 Figma 节点为真源 |
| `docs/08-detailed-implementation-plan.md` | 写了 Desk 要替换，但没有跨阶段可执行任务 | 增加 T-D/PUI 原型运行时轨道和三轴完成定义 |
| `docs/18-product-blueprint-and-prototype.md` | 原型和运行时状态容易混读 | 明确 14 个 1440 高保真、31 页蓝图、三档响应式缺口和当前 0/31 parity |
| `docs/19-end-to-end-product-roadmap.md` | 当前状态和近期队列停留在旧 P5 红测 | 更新为 P5 工程 Step 已 verified、数据和 PUI 双轨并行 |
| `docs/20-pre-development-spec-plan-audit.md` | 没有跨阶段 UI Plan 完整性行 | 增加 PUI readiness 和设计输入缺口 |
| `docs/plans/README.md` | 只有 Gate 轨道索引 | 增加 PUI 跨阶段计划和双队列规则 |
| `docs/plans/step-01...` | `verified` 容易被理解成原型视觉完成 | 明确只验证当前真实运行态和响应式，不是 design parity |
| `docs/21-p5-implementation-evidence.md` | 浏览器证据完整，但未单列“非原型 parity” | 增加范围澄清，保留原事实 |
| `CLAUDE.md` | 把 Step 02 Task 1 写成唯一下一工作 | 改为 Data/Gate 与 Prototype/Product 两条并行轨道 |

历史 Evidence 继续记录当时事实，不因为新产品计划而重写成“原型已完成”。

## 7. 审计后的交付判断

### 7.1 什么时候可以说“页面和原型一致”

仅当目标页面同时满足：

- 精确 Figma 节点或用户批准的响应式设计存在；
- `get_design_context`/可恢复 SVG 的结构、token、组件和资产已落实；
- 1440 真实浏览器与设计逐区对照，无未批准结构差异；
- 1024/768/320 按批准重排合同验收；
- loading/error/empty/partial/unavailable/ready 六态都符合同一产品结构；
- 正常和故障路径的控制台、网络、可访问性和水平溢出通过；
- Evidence 保存节点、运行时 URL、viewport、数据状态和已知差异。

### 7.2 什么时候可以说“原型表达的能力全部实现”

需要 P5–P10 领域/API/数据/治理和运行时页面全部完成：

- P6：核心研究 MVP；
- P9：成熟研究产品；
- P10：包含 Paper OMS 的完整非实盘产品。

视觉完成不能把尚未实现的能力标成 ready。没有真实数据时，页面仍可完成视觉和六态产品结构，
但运行时必须展示真实 `empty/partial/unavailable/blocked`，不得装入 Figma 的 DESIGN FIXTURE。

P11 Limited Live 始终是另行授权项目，不是原型页面完整的前提。
