# PUI-02 Universe & Screen 实施 Evidence

> 记录日期：2026-08-15
>
> 起始基线：`96f0d6a docs: settle the sidebar width conflict at 280 px`
>
> 工作包：`docs/plans/track-00-prototype-runtime-delivery.md` PUI-02
>
> 设计真源：Figma `research-universe-screen`，node `3:726`，1440 × 1460
>
> 关键决策：`docs/adr/0012-screen-builder-readonly-projection.md`
>
> 性质：只记录已发生的事实。不修改 Spec，不提升任何 Gate 状态。

## 1. 三轴结论

| 轴 | 结论 | 不能据此推出 |
|---|---|---|
| Design Parity | `parity_verified_with_known_deviation` | 不代表逐像素一致；31 页完全 parity 仍为 0/31 |
| Runtime Product | `verified` | 不代表数据可信或模型有效 |
| Domain/Capability | `blocked` | 无合格 Screen/Snapshot；P2/P4/P5 Gate 未通过 |

**明确否认**：本工作包不代表 P2、P4 或 P5 Gate 通过，不代表任何因子科学有效，
不代表平台具备可盈利策略、Paper-ready 或实盘能力。

## 2. 核心架构决策：构建器只读（ADR-0012）

### 2.1 冲突

Figma `screen-builder`（320 × 584）包含权重配比（Quality 40% / Valuation 30% / Improvement 30%）、
流动性门槛（> 5000 万 CNY）、排除硬性条件，以及「运行 Screen（计算因数重排）」按钮。

当前后端只读**已冻结、已绑定审批 scope 的 `SignalSnapshot`**。原型的运行按钮意味着
「随手改权重 → 立即得到新排名」，该产物没有定义版本、没有 Run 记录、没有审批用途，
违反 `AGENTS.md` 的可追溯性要求。

更实质的问题：**P4 因子资格门未通过**，最新三条 `ExperimentRun` 均失败，`FactorVersion` 保持
draft，没有合格 factor score / IC / RankIC。即使实现权重输入，后端也没有合格因子可用于重算。

### 2.2 决策

采用机构量化平台标准做法 **read model / write model 分离**，分两阶段：

- **第一阶段（本工作包）**：构建器按 Figma 布局存在，但语义为**只读展示该已冻结 Screen 的实际
  参数**；不渲染权重输入与运行按钮；
- **第二阶段（P4 之后，另行实施）**：引入 scratch / governed 双通道。ADR-0012 已记录 6 条强制
  要求，包括权重必须落为 `ScreenDefinition` 版本对象、必须产生 `Run` 记录、scratch 产物必须被
  服务端拒绝用于组合/回测/paper 路径、scratch 与 governed 不得同一视觉层级并列。

否决的备选方案及理由见 ADR-0012 §备选方案。

## 3. 逐行分项列的合法来源

Figma 排名表含 `质量 / 估值预期差 / 改善 / 60日预期收益区间`，原 `ScreenRankingRowProjection`
没有这些字段。

**它们不需要新建数据**：`InvestmentView.components` 已含
`InvestmentComponent(name, status, expected_return_contribution, evidence_ids, status_reason)`，
`expected_return.p10/p90` 已含分布区间，且 `SignalSnapshot.investment_view_id` /
`investment_view_hash` 已绑定到具体已冻结 View。

实现要点：以 **view id 与 content hash 双重匹配**取得绑定 View：

```python
bound_views = {(item.view_id, item.content_hash): item for item in views}
view = bound_views.get((value.investment_view_id, value.investment_view_hash))
```

双重匹配确保同证券的**新版 View 不会串入**旧 Snapshot 的行 —— 这一点已有既有测试
`test_selected_view_is_the_exact_snapshot_binding_not_a_newer_same_security_view` 守护同类语义。

无绑定 View 时，`components` 为空列表、区间显式 `unavailable_reason`，**不退化为点估计**
（那会高估精度）。

## 4. 四态语义与「不填零」

`InvestmentComponentStatus` 四态在表格中的呈现：

| 状态 | 显示 | 含义 |
|---|---|---|
| `quantified` | `+1.80%` | 已量化，有贡献值 |
| `constrained` | `—` | **有界但未量化**（域合同规定其 contribution 为 None） |
| `unavailable` | `—` | 不可用 |
| `not_applicable` | `—` | 不适用 |

后三者均显示 `—`，但 `status` 各自保留，且 `reason` 进入 `title` 属性，使审计可区分
「有界未量化」与「缺失」。**没有任何一项填 0。** 测试显式断言页面不含 `0.00%` / `+0.00%`。

**过程记录**：首版测试错误地断言「非 unavailable 即有 contribution」，实际 `constrained` 合法地
没有数值。这是测试的错误而非实现的错误，已修正并补测
`test_constrained_and_unavailable_are_distinguishable`。

## 5. 红测与绿测证据

### 5.1 后端逐行分项（红）

```
KeyError: 'expected_return_interval'
AssertionError: 'components' not found in {...}
Ran 5 tests — FAILED (failures=1, errors=3)
```

实现后 `tests.test_research_workspace_projection`：**13 tests OK**。

### 5.2 前端表格列（红）

```
× renders the three factor dimensions the prototype table declares
× renders the horizon expected-return interval column
× shows the server display value and never zero-fills a non-quantified dimension
× keeps constrained distinguishable from unavailable for audit
× states why an interval is missing instead of showing a bare dash
× tolerates a projection without component fields
Tests  6 failed | 8 passed (14)
```

实现后：**14 tests OK**。

### 5.3 只读构建器（红）

```
Error: Failed to resolve import "./ScreenBuilderPanel"
Tests  no tests
```

实现后 `ScreenBuilderPanel.test.tsx`：**8 tests OK**，其中包括断言**不存在**
slider / spinbutton / textbox / 运行按钮，以及不含 Figma 示例值。

### 5.4 浏览器验收发现的真实缺陷（红→绿）

四视口验收对真实运行时执行时发现：**workspace 为 `unavailable` 时构建器完全不渲染**
（`builder=0`），整页退化为一条泛化提示。

这与 PUI-01 建立的原则冲突 —— 构建器正是操作者了解「缺哪些绑定」的地方，必须在 unavailable
状态下存活，就像 Desk 的七个分区不会因某个域不可用而消失。

红测：
```
× keeps the prototype two-column shape when the workspace is unavailable
  → Unable to find role="region" and name "Screen 构建器"
```

修复后四视口 `builder=1`。

## 6. 四视口真实浏览器验收

工具：Playwright 驱动 Chrome 151。运行时：真实 API（`127.0.0.1:8010`）+ Vite
（`127.0.0.1:5173`），**无 runtime fixture**，未配置数据库、无合格数据。
URL：`/research?tab=universe-screen`。

| 视口 | scrollWidth/clientWidth | 页面级溢出 | 构建器 | 右侧裁切 | console error/warning | 4xx/5xx | DESIGN FIXTURE 泄漏 |
|---|---|---|---|---|---|---|---|
| 1440×900 | 1440/1440 | 无 | 1 | 0 | 0 | 0 | 0 |
| 1024×768 | 1024/1024 | 无 | 1 | 0 | 0 | 0 | 0 |
| 768×1024 | 768/768 | 无 | 1 | 0 | 0 | 0 | 0 |
| 320×640 | 320/320 | 无 | 1 | 3（见下） | 0 | 0 | 0 |

DESIGN FIXTURE 检查覆盖：`94.2`、`贵州茅台`、`五粮液`、`40%`、`96.3`、`5000`、`wind_terminal`
—— DOM 中均不存在。

截图：`/tmp/universe-1440.png`、`/tmp/universe-1024.png`、`/tmp/universe-768.png`、
`/tmp/universe-320.png`。

### 6.1 320 裁切元素的归属核实

320 视口报告 3 个越界元素：`ant-tabs-nav-list`、`ant-tabs-tab`、`ant-tabs-tab-btn`。

对照未触碰的 `/monitoring` 同视口：**同样存在完全相同的三个元素**。因此这是 AntD tab 条在自身
容器内横向滚动的既有行为，不是本工作包引入，且页面级 `scrollWidth === clientWidth` 成立。

### 6.2 新发现的既有缺陷（未修复，已登记）

`/factors` 在 320 视口存在**真实页面级水平溢出**（`pageOverflow=True`，溢出元素为
`pageHeading`）。该缺陷早于本工作包、与 Screen 无关，已登记至 `track-00` 与 `docs/22`
待 PUI-04 处理。**本工作包不顺手修复无关缺陷。**

## 7. 与 Figma 的已知差异

1. **构建器为只读**：无权重滑块、无流动性阈值输入、无排除条件勾选、无「运行 Screen」按钮
   （ADR-0012 第一阶段）；
2. **行业多选、流动性门槛、排除条件三个分区未展示**：服务端不存在对应配置来源，
   宁可不展示也不填示例值；
3. Figma 示例值（40%/30%/30%、96.3%、> 5000 万 CNY）**不进入运行时**；无绑定时显示缺失原因；
4. 侧栏 280 px 决定使 1440 主内容区为 1160 px 而非 1192 px，栅格以比例（320fr/800fr）吸收；
5. 320/768/1024 无独立 Figma Frame，按 `docs/18` 响应式合同重排，非 Figma 视觉验收。

## 8. 全量验证结果

```text
Backend unittest:  867 passed（861 → 867，+6 分项投影测试）
compileall:        passed
Ruff:              passed
mypy:              passed（177 source files）
Frontend Vitest:   106 passed（91 → 106，+15）
Frontend lint:     passed
Frontend build:    passed
git diff --check:  passed
PostgreSQL smoke:  未运行（本机无 docker/psql）
```

Vite 仍有既有 AntD large-chunk warning。**未隐藏，也未声称已修复。**

## 9. 新增与修改文件

新增：

- `docs/adr/0012-screen-builder-readonly-projection.md`
- `platform/frontend/src/features/screen/ScreenBuilderPanel.tsx`
- `platform/frontend/src/features/screen/ScreenBuilderPanel.test.tsx`

修改：

- `platform/src/a_share_platform/application/research_workspace.py`
  （`_project_screen` 接收 views；新增 `_project_row_components`、`_project_return_interval`）
- `platform/src/a_share_platform/api/schemas.py`
  （新增 `ScreenRowComponentProjection`、`ScreenReturnIntervalProjection`；
  `ScreenRankingRowProjection.model_rebuild()` 解析前向引用）
- `platform/tests/test_research_workspace_projection.py`
- `platform/frontend/src/features/screen/{screenProjection.ts,ScreenRankingPanel.tsx,ScreenRankingPanel.test.tsx}`
- `platform/frontend/src/pages/{ResearchP5Screen.tsx,ResearchP5Screen.test.tsx,ResearchP5Screen.less}`
- `platform/frontend/src/api/openapi.json`
- `docs/plans/track-00-prototype-runtime-delivery.md`、`docs/22-prototype-runtime-gap-audit.md`

未触碰 `sources/` 两个只读来源仓库。

## 10. 未完成项与阻断

- **可编辑构建器**：等待 P4 因子资格门与 ADR-0012 第二阶段；
- **行业多选 / 流动性门槛 / 排除条件**：服务端无配置来源，需先定义 `ScreenDefinition`；
- **行点击进入精确 Security**：依赖 PUI-03 目标页；
- **1440 高密度排名表与 320 记录卡的视觉验收**：需真实 Screen 数据才能完成；
- **真实排名内容**：当前无合格 Snapshot，页面显示真实 unavailable + blocker；
- `/factors` 320 页面级溢出（既有缺陷，登记待 PUI-04）；
- **PostgreSQL 验证**：本机无 docker/psql，未运行；
- **31 页 parity**：仍为 0/31 完全 parity。
