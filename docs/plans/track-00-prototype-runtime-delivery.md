# Track PUI Spec / Plan：原型驱动的运行时产品交付

> 状态：`in_progress`（现有 Shell/局部页面为技术验证；Design Parity 0/31）
>
> 对应：SPEC-042–050、`docs/18-product-blueprint-and-prototype.md`、Roadmap P5–P10
>
> 当前审计：`docs/22-prototype-runtime-gap-audit.md`
>
> 性质：跨阶段产品轨道；不改变 P2/P4/P5 数据、科学和用途 Gate

## Spec

### 目标

把 Figma 产品蓝图和高保真关键页逐步实现为真实 React 运行时产品，使页面的结构、密度、视觉、交互、
上下文、六态和黄金路径符合批准原型，同时只消费真实服务端投影，绝不把 DESIGN FIXTURE 注入运行时。

### 非目标

- 不用漂亮页面替代领域/API/数据实现；
- 不在浏览器重算排名、InvestmentView、组合、风险、归因或审批；
- 不为视觉完整伪造 ready、证券、收益、模型、组合、事件或账户；
- 不把 Design Parity 当 Capability Gate、科学有效、Promotion Approval 或 Paper-ready；
- 不在没有精确设计输入时由开发者随意发挥并宣称“与原型一致”。

### 设计与需求真源

冲突时按以下顺序执行：

1. `AGENTS.md` 的安全和仓库边界；
2. `docs/07-detailed-system-spec.md` 的可信、权限、技术栈、token、可访问性和 Shell 合同；
3. Accepted ADR；
4. `docs/18-product-blueprint-and-prototype.md` 的 31 页信息架构、交互、六态和黄金路径；
5. 目标页面的精确 Figma node；
6. 仓库 `docs/assets/prototype/` 中对应可恢复资产；
7. 本 Plan 的页面切片；
8. Evidence 只记录事实。

原工作树提供 token 和机构级组件 provenance，不再作为 31 页布局的替代真源。

### 设计到代码强制流程

每个页面编码前必须：

1. 确认精确 Figma file key 和 node id；
2. 通过 Figma design-to-code 工作流读取 `get_design_context`；
3. 若调用失败，先处理错误；除仓库已有精确 SVG 的页面外，不得只凭缩放截图编写并声称高保真；
4. 检查现有 React 组件、AntD 用法、Less token 和 Code Connect 映射，优先复用；
5. 将 Figma 参考代码适配到 React 19 + TypeScript + AntD 6 + Less，不复制 Tailwind 参考代码；
6. 精确资产必须来自 Figma export/仓库资产或运行时数据源，不手绘替代图标；
7. 记录 node id、viewport、目标状态和允许差异。

### 页面三轴状态

每页分别登记：

- `design_status`：`missing | ready | parity_verified`；
- `runtime_status`：`placeholder | partial | verified`；
- `capability_status`：`blocked | partial | verified`。

一个轴通过不得自动提升另一个轴。禁止只写一个含糊的 `done/verified`。

### 六态与运行时数据

页面必须在同一产品结构内覆盖：

- `loading`；
- `error`；
- `empty`；
- `partial`；
- `unavailable`；
- `ready`。

六态由服务端合同决定。测试可使用明确的 contract fixture 验证布局；生产/开发运行时不得有默认
fixture。没有真实对象时，用原型结构展示真实 blocker、缺失范围、trust、run/request id 和安全动作，
不能退化为一段泛化的“能力未启用”占满整个页面。

### 响应式与视觉验收

- 1440：对精确高保真 Figma node 做逐区视觉对照；
- 1024/768/320：按 `docs/18` 响应式合同重排，不等比缩小；
- SPEC-045 当前使用 280 px 展开、72 px 收起侧栏；
- 页面级 `scrollWidth === clientWidth`，宽表只在自己的容器滚动；
- 记录结构、字体层级、色彩、密度、间距、分栏、表格、状态和操作差异；
- 未经用户批准的明显差异必须修复，不能只写“风格相近”；
- 浏览器检查覆盖交互、键盘、控制台、网络、错误恢复和无障碍名称；
- 视觉验收不能只运行组件测试或 curl。

### 黄金路径

运行时目标路径：

```text
Desk
→ Universe & Screen
→ Security fused overview
→ InvestmentView
→ Approvals
→ Alpha Model
→ Portfolio Construction
→ Realistic Backtest
→ Timing Shadow Monitor
→ Attribution
```

每次跳转保留 Research Time、Data Mode、Deployment Stage、Universe、Security/Portfolio scope。
严格路径阻断时留在当前页展示 blocker，不跳转到假成功页。

## Plan

### PUI-00：设计基线、节点清单和视觉测试基础

状态：`verified`（2026-08-15；设计输入阻断已解除）。

2026-08-15 Figma Starter MCP 调用额度用尽后，改用 **Figma REST API**（Personal Access Token，
scope 仅 `File content: read`）取得结构化节点上下文与精确 SVG，并全部入库。因此后续任何 PUI
工作包都不再依赖 Figma 会话或配额。

已完成：

1. 全部 18 个顶层 Frame 的 file key、node id、Frame 名和 1440 尺寸已冻结，见
   `docs/assets/prototype/README.md`；
2. 17 个业务 Frame 的精确 SVG 已入库（保留图层 id 与可读文字，合计 1.0 MB）；
3. `docs/assets/prototype/figma-node-summary.json` 记录层级、尺寸、`layoutMode`、`itemSpacing`、
   文字内容、字号、字重和字体族；
4. 导出参数已记录并说明 `svg_outline_text=false` 的必要性：默认导出把文字转为矢量路径，
   17 页共 33 MB 且文字不可读、不可搜索，对实现没有参考价值；
5. 截图产物命名为 `/tmp/desk-<viewport>.png`，验收脚本为
   `platform/scripts/verify_desk_browser.py`。

仍然成立的边界：

- 17 个 Frame **全部为 1440 宽**；320/768/1024 没有独立 Figma Frame，三档仍只有文档级响应式
  合同，不是已通过的视觉证据；
- 31 页蓝图为全部页面提供信息架构，但不是每页都有独立高保真 Frame；
- 尚未引入截图 diff 工具；如需引入，先由用户批准基线和容差。

### PUI-01：全局 Shell 与今日工作台

状态：`in_progress`（2026-08-15 完成第一个垂直切片；三轴状态见下）。

三轴结论（不得互相替代）：

| 轴 | 结论 | 依据 |
|---|---|---|
| Design Parity | `parity_verified_with_known_deviation` | 结构、分栏、字号层级、token 对照 node `3:398`；已知差异见下 |
| Runtime Product | `verified` | 七分区六态由真实 `GET /api/desk` 驱动，四视口真实浏览器验收通过，无 runtime fixture |
| Domain/Capability | `blocked` | 组合跟踪属 P6、事件流属 P8，均未实现；P2/P4/P5 Gate 未通过 |

已完成：

- 删除 `DeskPage.tsx` 中 16 行硬编码 `capabilityRows`，改为消费服务端 Desk projection；
- 新增 `domain/desk.py` 分区契约：四个服务端状态（`ready`/`partial`/`empty`/`unavailable`），
  `partial` 必须声明 coverage 或 blocker，`sections` 恒为 7 项；
- 新增 `application/desk_projection.py`：分区级隔离，单一数据源不可用只降级该分区；
- 新增 `GET /api/desk`，复用既有 Envelope 与 `ResponseContext`；
- `WorkspaceStateKind` 扩展为六态并保留 `blocked` 作为 `unavailable` 的兼容别名；
- 组合跟踪（P6）与事件流（P8）由服务端声明 unavailable 并附阶段 blocker，不伪造持仓或事件。

与 Figma 的已知差异（必须保留记录，不得声称逐像素一致）：

1. **侧栏宽度**：Figma node `3:398` 实测 248 px，而侧栏宽度已于 2026-08-15 裁决统一为
   **280 px**（展开）/ 72 px（收起），与 SPEC-045 一致；`docs/18` 原先的 224 px 已同步更新。
   因此 1440 下主内容区为 1160 px 而非 Figma 的 1192 px。两栏以比例（740fr/380fr）声明，
   使 32 px 差异被两栏吸收而不产生水平溢出。这是**已批准的设计差异**，不是待决冲突；
   后续页面按同一比例换算，不得为对齐 1192 px 而改回 248 px；
2. **卡片高度与页面总高**：Figma 页面高 1238 px，当前运行时 1128 px。差异来自内容而非布局——
   Figma 卡片装的是 DESIGN FIXTURE（8 行排名、6 条事件），真实运行时装的是 blocker。
   不为了对齐设计稿高度而填充假数据；
3. **320/768/1024**：无独立 Figma Frame，按 `docs/18` 响应式合同重排，非 Figma 视觉验收。

本切片未覆盖（留待后续）：

- 顶部证券搜索、Universe 选择器等 Shell 控件沿用既有实现，未按 Figma `topbar` 逐项对照；
- 排名表在有真实 Screen 数据后才能验收 1440 高密度表格与 320 记录卡形态；
- 分区跳转（Desk → Universe/事件/审批/故障）待对应目标页在 PUI-02/PUI-03 落地后接线。

TDD 切片（原计划，已执行）：

1. 红测：Desk 不再渲染 `capabilityRows` 工程阶段表；
2. API contract：新增服务端 Desk projection，分别返回数据健康、Screen shifts、重大事件、组合跟踪、
   Timing、待审批/任务和 Active Failures；未实现域返回分区级 unavailable，不伪造项目；
3. 前端合同：各分区有 loading/error/empty/partial/unavailable/ready，普通刷新不触发昂贵 Agent；
4. 复用 Shell/token，按 1440 Desk node 实现层级、分栏和高密度；
5. 1024/768/320 重排，保留 Mode/Stage/Time/Universe 文本；
6. 真实浏览器验证 Desk → Universe/事件/审批/故障入口。

预计文件：

- `platform/frontend/src/pages/DeskPage.tsx` 及样式/测试；
- `platform/frontend/src/features/desk/*`；
- `platform/src/a_share_platform/api/` Desk projection；
- 对应 application query/ports/tests；
- OpenAPI 生成产物。

### PUI-02：Universe & Screen

状态：`ready_for_implementation`（视觉编码前读取 `research-universe-screen`）。

目标：从当前纵向技术页变为左侧 Universe/Factor Builder + 右侧受治理排名表，同时保留真实空态和 blocker。

TDD 切片：

1. 查询控件、filter builder、资格/排除条件和 URL 状态；
2. 服务端 Screen projection、stable order、rank change、trust/version/hash；
3. 1440 双栏高密度排名；
4. 1024 两栏压缩/详情，768 表格容器滚动，320 等价记录卡；
5. 行点击进入精确 Security，上下文不丢失；
6. 无 Universe/Snapshot 时仍保留原型结构并显示分区 blocker。

预计复用：`UniverseScreen`、`ScreenRankingPanel`、`screenProjection`；禁止建立第二套排名计算。

### PUI-03：Security、InvestmentView、Approvals 与 Alpha 黄金路径

状态：`ready_for_implementation`（Security/InvestmentView 有仓库 SVG；其余节点仍先取 design context）。

目标：实现 P5 黄金路径的高保真产品结构，不等待假 ready 数据。

TDD 切片：

1. Security fused overview：公司画像、价值链、四问、财务轨迹、同业、证据覆盖、Catalysts/Invalidators、
   blocker、View readiness；
2. InvestmentView 独立详情路由/状态，而不是只嵌在通用 tab；
3. Evidence/run/lineage 往返；
4. 服务端身份控制的 Review 提交、禁用原因和结果返回；
5. Alpha exact Factor/Review/View/Universe binding；
6. 1440 对 `24:400`、`security-investmentview`、Approvals、Alpha nodes；三档响应式按合同；
7. 真实对象不存在时保持完整布局和 blocker，不显示 DESIGN FIXTURE 数字。

### PUI-04：现有 Factor 与 System 页产品化

状态：`ready_for_implementation`（只覆盖已有 API/真实失败态，不提前实现 P9 能力）。

范围：Factor Catalog/Alpha/Timing baseline/Experiments/Production 与 System Catalog/Quality/Lineage/Jobs。

任务：

- 把当前工程卡片重排为原型信息架构；
- 保留失败 Experiment 和真实分页；
- Evidence、run、dataset、definition 和 review 可钻取；
- Correlation、Users、Entitlements、Agents、通用 Approvals 等未实现能力继续分区 unavailable；
- 逐页登记是否只有 31 页蓝图、是否缺独立高保真 Frame。

### PUI-05：P6 Portfolio 产品页

状态：`dependency_blocked`（等待 P6 domain/API；可先完成 design context 和六态合同测试）。

范围：Construction、Backtests、Risk、Scenarios、Attribution。对应 Step 05 Task 8。

不得用前端 fixture 在 runtime 生成持仓、曲线、风险或归因。真实 API 缺失时可以实现视觉壳和
contract fixture 测试，但页面运行时只能显示真实 blocker。

### PUI-06：P7 Timing 产品页

状态：`dependency_blocked`（等待 P7）。

范围：Timing Lab、Shadow、Monitoring Timing、Desk latest Shadow。必须分开 historical/OOS/forward，
主动模型未晋级时组合影响为 0。

### PUI-07：P8 Events、Cases 与 Agents 产品页

状态：`dependency_blocked`（等待 P8 文档/事件/Agent 合同）。

范围：Events、Watchlists/Cases、System Agents、Security event enhancement。无引用 Agent 输出不能进入
View；页面不得把 LLM 文本显示成权威价格或财务事实。

### PUI-08：P9 Monitoring 与 Governance 产品页

状态：`dependency_blocked`（等待 P6/P7/P8）。

范围：Signals、Portfolios、Drift、Rebalance、Incidents、Correlation、Production、Users、Entitlements、
Approvals、成熟 Desk 和统一 Attribution。

### PUI-09：P10 Paper Execution 产品页

状态：`dependency_blocked`（等待 P9/P10）。

范围：Paper preview、orders、fills、positions、cash、breaks、Execution、Rebalance、Incidents 和 kill switch。
全局必须显示 `paper`；不存在 Live 切换或真实账户入口。

## 每个 PUI 工作包完成定义

1. 精确 Figma node/批准的响应式合同已记录；
2. 先有失败的 API/component/layout/interaction 测试或明确设计缺口；
3. 最小实现复用现有组件和 token；
4. OpenAPI/TypeScript 类型同步；
5. 六态全部有合同测试；
6. runtime 无默认 fixture；
7. 1440 设计对照与 1024/768/320 真实浏览器验收；
8. 无页面级溢出、无未解释裁切、控制台无 error/warning、正常网络无 4xx/5xx；
9. 键盘、焦点、非颜色状态和可访问名称检查；
10. 更新本 Track、`docs/22` 和阶段 Evidence；
11. 分别报告 Design Parity、Runtime Product、Capability 状态；
12. 一个 PUI 切片一个独立提交，只有用户授权时 commit/push。

## 验证

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
npm --prefix frontend test -- --run
npm --prefix frontend run lint
npm --prefix frontend run build
git diff --check
```

前端工作包另执行目标组件测试、OpenAPI drift 检查、1440 Figma 对照和 1024/768/320 浏览器矩阵。
缺 Figma design context、独立高保真 Frame 或真实业务对象时，分别标记设计或能力阻断，不能合并成通过。
