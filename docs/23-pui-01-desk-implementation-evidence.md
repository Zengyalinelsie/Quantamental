# PUI-01 Desk 实施 Evidence

> 记录日期：2026-08-15
>
> 起始基线：`f703d08 docs: add Claude Code project handoff`
>
> 工作包：`docs/plans/track-00-prototype-runtime-delivery.md` PUI-00 → PUI-01
>
> 设计：`docs/superpowers/specs/2026-08-15-pui-01-desk-design.md`
>
> 性质：只记录已发生的事实。不修改 Spec，不提升任何 Gate 状态。

## 1. 三轴结论

| 轴 | 结论 | 不能据此推出 |
|---|---|---|
| Design Parity | `parity_verified_with_known_deviation` | 不代表逐像素一致；31 页完全 parity 计数仍为 0/31 |
| Runtime Product | `verified` | 不代表数据可信、模型有效或 Gate 通过 |
| Domain/Capability | `blocked` | 组合跟踪属 P6、事件流属 P8，均未实现 |

**明确否认**：本工作包不代表 P2、P4 或 P5 Gate 通过，不代表任何因子或估值模型科学有效，
不代表平台具备可盈利策略、Paper-ready 或实盘能力。

## 2. 环境事实（与 `CLAUDE.md` §10 描述的开发机不同）

本机在本工作包开始时**尚未 bootstrap**，`CLAUDE.md` 记录的 817/817 基线在本机从未运行过。
实际环境：

| 项 | 本机事实 |
|---|---|
| Python | 3.12.12（`platform/.venv`，`pyproject.toml` 要求 `>=3.11`，满足；无 `python3.11`） |
| Node | v22.23.1，npm 10.9.8 |
| `platform/.venv` | 原不存在，本次创建 |
| `frontend/node_modules` | 原不存在，本次 `npm ci` 安装 |
| docker / psql | **均未安装** |
| pip 索引 | `files.pythonhosted.org` 在本机 Python 中 TLS 失败（`WRONG_VERSION_NUMBER`），curl 可达；改用清华镜像安装 |

### 2.1 未运行的验证

- **PostgreSQL migration smoke 未运行**：本机无 docker/psql，无法启动 55432 开发库。
  未将依赖真实数据库的断言改为默认通过，如实记录为未运行。
- 因此所有后端测试均在 in-memory / Unavailable 适配器下执行。

### 2.2 基线修复

首次运行 `unittest discover` 得到 **817 tests, 4 failures + 1 error**。逐项定位后确认均为
**依赖缺失**，非代码缺陷：

- 4 个 `test_statistical_crosscheck` 失败：缺 `validation` extra（numpy/scipy/statsmodels），
  交叉校验返回 `UNAVAILABLE` 而非 `MATCHED`。安装后转绿；
- 1 个 `test_financial_backfill_worker` error：缺 `requests`（`akshare` 传递依赖）。安装后转绿。

修复后基线 **817/817 OK**，与 `CLAUDE.md` 记录一致。

## 3. 设计输入：Figma REST API 完整捕获

`docs/22` §2.2 记录 Figma Starter MCP 配额用尽，设计输入被阻断。本工作包改用 **Figma REST API**
（Personal Access Token，scope 仅 `File content: read`）取得结构化上下文，阻断已解除。

取得并入库（`docs/assets/prototype/`）：

- 17 个业务 Frame 的精确 SVG，保留图层 id 与可读文字，合计 **1.0 MB**；
- `figma-node-summary.json`（466 KB）：层级、尺寸、`layoutMode`、`itemSpacing`、文字、字号、
  字重、字体族；
- README 记录 file key、全部 18 个 node id、导出参数与复现命令。

### 3.1 关键教训：`svg_outline_text=false`

首次导出使用默认参数，得到 **33 MB / 17 页**（单页约 1.7 MB），文字全部被转为矢量路径 ——
不可读、不可搜索、无法与实现逐条对照，对开发没有参考价值。

改用 `svg_outline_text=false` 后 **1.0 MB / 17 页**（单页 40–88 KB），每页含 91–221 个可读
`<text>` 节点。体积缩小 25 倍且信息量更大。此参数已写入 README，避免重复踩坑。

### 3.2 Desk 实测布局（node `3:398`）

```
desk-daily-workstation  1440 × 1238  bg #F3F5F7
├─ sidebar     248 × 1238        ← 与 SPEC-045 的 280 冲突，见 §6
└─ main-content 1192 × 1238
    ├─ topbar        1192 × 64
    └─ content-body  1192 × 1174  padding 24
        ├─ today-banner 1144 × 73
        └─ grid         1144 × 1029  HORIZONTAL NO_WRAP gap 24
            ├─ grid-left  740 × 535   card-rankings 350 + row-metrics 161
            └─ grid-right 380 × 1029  events 489 + pending 273 + exceptions 219
```

字号仅用 `10/11/12/13/14/16/18`，字重仅 `400/500/600/700`，圆角仅 `1/2/3/12`，内距仅
`2/6/8/10/12`。设计 token 与仓库现有 `design/tokens.less` **完全一致**（`@primary #2f5ea8`、
`@layout #f3f5f7`、`@market-up #a64045`、`@market-down #2e7660`），因此复用既有 token，未新建。

## 4. 红测与绿测证据

### 4.1 Task 1 前端红测

```
× DeskPage > no longer renders the hard-coded engineering capability table
× DeskPage > renders all seven prototype sections from the server projection
× DeskPage > requests the desk projection instead of computing state in the browser
× DeskPage > renders a loading state while the desk projection is pending
× DeskPage > surfaces a real API failure without substituting prototype data
× DeskPage > shows each section status independently so one blocked domain does not blank the page
Tests  6 failed (6)
```

真实失败原因：页面仍渲染 `capabilityRows` 的 ProTable，找不到七分区 region。

### 4.2 Task 2 领域红测

```
ModuleNotFoundError: No module named 'a_share_platform.domain.desk'
Ran 1 test — FAILED (errors=1)
```

实现后：**16 tests OK**。

### 4.3 Task 3 应用层红测

```
ModuleNotFoundError: No module named 'a_share_platform.application.desk_projection'
```

实现后：**19 tests OK**。

### 4.4 Task 4 API 红测

```
AssertionError: 404 != 200   （/api/desk 不存在）
Ran 7 tests — FAILED (failures=2, errors=4)
```

实现后：**7 tests OK**。

### 4.5 浏览器验收发现的真实缺陷（红→绿）

四视口验收对真实运行时执行时发现 **两个测试没能覆盖的真实缺陷**：

**缺陷 1：可达性判断错误。** `ResearchWorkspaceProjectionService` 把自身仓库故障
**捕获为 blocker 而非抛出**，因此 `_screen_shifts` 收到的是 `screen: None` 而非异常，
将「数据库未配置」误报为 `empty`（等数据）而非 `unavailable`（等配置）——
正是 empty/unavailable 区分要防止的混淆。

红测：
```
AssertionError: <DeskSectionStatus.EMPTY: 'empty'> != <DeskSectionStatus.UNAVAILABLE: 'unavailable'>
```
修复后运行时真实输出：
```
screen_shifts  unavailable  investment_view_store_unavailable,signal_snapshot_store_unavailable
```

**缺陷 2：favicon 404。** `index.html` 自 P1 起从未声明 favicon，也无 `public/` 目录，
浏览器无条件请求 `/favicon.ico` 导致每次加载都产生 404 console error。这会让**全部 31 页**
的 console 检查永久失败，不只 Desk。已补 `public/favicon.svg` 并在 `index.html` 声明。

## 5. 四视口真实浏览器验收

工具：`platform/scripts/verify_desk_browser.py`（Playwright 驱动已安装的 Chrome 151）。
运行时：真实 API（`127.0.0.1:8010`）+ Vite（`127.0.0.1:5173`），**无 runtime fixture**，
未配置数据库、无合格数据。

| 视口 | scrollWidth/clientWidth | 页面级溢出 | 分区 | 右侧裁切 | console error/warning | 4xx/5xx | DESIGN FIXTURE 泄漏 |
|---|---|---|---|---|---|---|---|
| 1440×900 | 1440/1440 | 无 | 7/7 | 0 | 0 | 0 | 0 |
| 1024×768 | 1024/1024 | 无 | 7/7 | 0 | 0 | 0 | 0 |
| 768×1024 | 768/768 | 无 | 7/7 | 0 | 0 | 0 | 0 |
| 320×640 | 320/320 | 无 | 7/7 | 0 | 0 | 0 | 0 |

其他检查：

- **显式失败与恢复**：路由 `/api/desk` 返回 503 → 渲染「今日工作台读取失败」并显示真实
  detail；解除拦截并重载 → 恢复正常。两者均为 `true`；
- **可访问性**：8 个具名 region；首个 Tab 到达一级导航；error 用 `role="alert"`，
  empty 用 `role="status"`，状态同时由图标与文字表达，不依赖颜色；
- **无 fixture**：DOM 中不含 `94.2`、`贵州茅台`、`600519.SH`、`五粮液`、`28.1`、`-1.62`、
  `wind_terminal` 等 Figma 示例值。

截图：`/tmp/desk-1440.png`、`/tmp/desk-1024.png`、`/tmp/desk-768.png`、`/tmp/desk-320.png`。

### 5.1 真实运行时七分区状态

未配置数据库、无合格数据时的诚实输出：

```
data_health          empty        -
screen_shifts        unavailable  investment_view_store_unavailable, signal_snapshot_store_unavailable
portfolio_tracking   unavailable  P6_PORTFOLIO_TRACKING_NOT_IMPLEMENTED
timing_shadow        unavailable  TIMING_SHADOW_LEDGER_UNAVAILABLE
event_feed           unavailable  P8_EVENT_FEED_NOT_IMPLEMENTED
pending_tasks        unavailable  PENDING_TASK_REVIEW_STORE_UNAVAILABLE
active_failures      empty        -
```

## 6. 与 Figma 的已知差异（不得声称逐像素一致）

### 6.1 侧栏宽度三值冲突（未最终裁决）

| 来源 | 值 |
|---|---|
| SPEC-045（`docs/07`，优先级最高） | 280 px |
| `docs/18` 响应式表 | 224 px |
| Figma node `3:398` 实测 | **248 px** |
| 当前运行时 | 280 px / 收起 72 px |

本工作包**新增了第三个数据点**，使原有两值冲突升级为三值。用户 2026-08-15 裁决：
运行时继续使用 280 px 并登记差异，不修改任何真源。

后果：1440 下主内容区为 **1160 px** 而非 Figma 的 1192 px，差 32 px。两栏以比例
`minmax(0, 740fr) minmax(0, 380fr)` 声明，使差异被两栏吸收而不产生水平溢出。
**因此 Desk 的 Design Parity 只能记为 `parity_verified_with_known_deviation`。**

三者的最终统一仍未裁决，需要未来一次显式决定。

### 6.2 卡片高度与页面总高

Figma 页面高 1238 px，当前运行时 **1128 px**。差异来源是**内容而非布局**：Figma 卡片装
DESIGN FIXTURE（8 行排名、6 条事件、4 组指标），真实运行时装 blocker 文本。

**未为对齐设计稿高度而填充假数据。** 这是有意的取舍。

### 6.3 三档响应式无 Figma 依据

320/768/1024 没有独立 Figma Frame，按 `docs/18` 响应式合同重排，不是 Figma 视觉验收。

### 6.4 本切片未覆盖

- 顶部证券搜索、Universe 选择器等 Shell 控件沿用既有实现，未按 Figma `topbar` 逐项对照；
- 排名表的 1440 高密度表格与 320 记录卡形态需真实 Screen 数据后才能验收；
- Desk → Universe/事件/审批/故障的跳转待 PUI-02/PUI-03 目标页落地后接线。

## 7. 全量验证结果

```text
Backend unittest:  861 passed（817 基线 + 44 新增）
compileall:        passed
Ruff:              passed
mypy:              passed（177 source files）
Frontend Vitest:   91 passed（73 基线 + 18 新增）
Frontend lint:     passed
Frontend build:    passed
git diff --check:  passed
PostgreSQL smoke:  未运行（本机无 docker/psql）
```

Vite 仍有既有 AntD large-chunk warning（`antd` chunk 约 1.44 MB）。**未隐藏该 warning，
也未声称已修复。**

## 8. 新增与修改文件

新增：

- `platform/src/a_share_platform/domain/desk.py`
- `platform/src/a_share_platform/application/desk_projection.py`
- `platform/tests/test_desk_domain.py`
- `platform/tests/test_desk_projection.py`
- `platform/tests/test_desk_api.py`
- `platform/scripts/verify_desk_browser.py`
- `platform/frontend/src/features/desk/{DeskSection,DeskMetricList,deskSections}.tsx`
- `platform/frontend/src/features/desk/{deskState.ts,deskTypes.ts}`
- `platform/frontend/src/features/desk/DeskSection.test.tsx`
- `platform/frontend/public/favicon.svg`
- `docs/assets/prototype/`：17 个 SVG + `figma-node-summary.json`
- `docs/superpowers/specs/2026-08-15-pui-01-desk-design.md`

修改：

- `platform/src/a_share_platform/api/{app.py,schemas.py}`
- `platform/src/a_share_platform/ports/timing.py`（新增 `TimingForecastStoreUnavailable`）
- `platform/src/a_share_platform/adapters/memory/timing.py`（新增 `UnavailableTimingForecastRepository`）
- `platform/frontend/src/pages/DeskPage.{tsx,test.tsx}`
- `platform/frontend/src/components/WorkspaceState.{tsx,test.tsx}`
- `platform/frontend/src/api/{client.ts,openapi.json,schema.d.ts}`
- `platform/frontend/src/app/{shell.less,AppShell.test.tsx}`
- `platform/frontend/index.html`
- `docs/22-prototype-runtime-gap-audit.md`、`docs/plans/track-00-prototype-runtime-delivery.md`
- `docs/assets/prototype/README.md`

未触碰 `sources/` 两个只读来源仓库。

## 9. 未完成项与阻断

- **组合偏离与风险**：需 P6 组合能力才能由 unavailable 变为 ready；
- **重大事件/公告流**：需 P8 事件证据链；
- **因子审核与待处理**：仅覆盖 factor promotion review，通用审批队列属 P9；
- **运行异常**：仅覆盖摄取作业失败，通用 Incident 账本属 P9/P10；
- **Timing Shadow**：仅被动波动率 baseline，主动 Timing 属 P7；
- **数据健康**：需真实 dataset 与质量报告才能从 empty 变为 partial/ready；
- **侧栏三值冲突**：未最终裁决；
- **PostgreSQL 验证**：本机无 docker/psql，未运行；
- **31 页 parity**：仍为 0/31 完全 parity；Desk 是第一个完成结构级对照并登记差异的页面。
