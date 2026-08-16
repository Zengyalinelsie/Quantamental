# P-4 前端 Factor 与 System 页产品化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Factor 六页（Catalog / Alpha Model / Timing Lab / Experiments / Correlation Monitor / Production）与 System 四页（Catalog / Quality / Lineage / Jobs）从工程验证卡片重排为原型信息架构，全部消费已存在的真实端点，并修掉 `/factors` 在 320 视口的页面级水平溢出。

**Architecture:** 复用 PUI-01 已建立的 `DeskSection` 分区合同（`features/desk/DeskSection.tsx` + `deskState.ts`）与 `WorkspaceState` 六态组件，**不新建第二套分区模式**。后端**不新增能力**：十页全部映射到 `api/app.py` 已注册的只读端点，缺口只以服务端投影（projection）方式补齐，不新增领域数学、不新增写接口。

**Tech Stack:** React 19 + TypeScript 5.8 + Vite 7 + AntD 6 + Less、`@tanstack/react-query` 5、Vitest 3 + Testing Library、Playwright（`platform/.venv/bin/python`，Chrome channel）

## Global Constraints

继承 `AGENTS.md`、`docs/07-detailed-system-spec.md`、`docs/plans/track-00-prototype-runtime-delivery.md` 与已接受 ADR，**每个 Task 都适用**：

- 前端只消费服务端投影；**不在浏览器重算排名、score、trust、审批资格或生命周期状态**
- **runtime 无默认 fixture**；contract fixture 只允许存在于 `*.test.tsx` 中
- 缺失、不可比、不可用必须显式表达（`—` + 保留 status），**禁止填 0**
- `empty` 与 `unavailable` 语义不可合并：empty 表示能力可用但无记录，unavailable 表示能力/存储缺失
- **失败 Experiment 必须保留可见**，不得折叠、隐藏或改写为成功
- **真实分页必须保留**：`SystemScreen` 的 `useClientPage` 已按 20 行分页并保留 `total`，不得为视觉整齐改成 `pagination={false}`
- Correlation Monitor、Users、Entitlements、Agents、通用 Approvals 属 **P9**，必须保持分区 `unavailable` 并显示阶段 blocker，**不得伪造**
- `design_status` 只有在存在精确 Figma node 并完成 1440 逐区对照后才能改；**没有 Frame 的页面永久保持 `missing`**，只记录设计假设
- 三轴（Design Parity / Runtime Product / Domain Capability）分别报告，一轴通过不推出另一轴
- Design Parity 不等于 Capability Gate；本 plan **不改变 P2/P4/P5 任何 Gate 状态**
- 侧栏 280 px（展开）/ 72 px（收起）为已裁决值；Figma 的 248/224 px 是**已批准的设计差异**，不得改回
- 响应式断点复用 `app/shell.less` 已有的 1280 / 820 / 420，**不新增断点**
- 未经用户明确授权不 commit、不 push

## 前置条件

**无。** 本 plan 属产品线，不依赖 P-1 数据摄取或 P-2 因子编排。十页在当前空/不可用运行态即可完成产品结构与六态验收 —— 这正是 PUI 轨道与数据轨道可并行的原因。

本地需要：

```bash
cd platform
docker compose up -d postgres   # 可选；无库时端点返回 503，属被验收状态之一
PYTHONPATH=src .venv/bin/python -m uvicorn a_share_platform.api.app:app \
  --host 127.0.0.1 --port 8010 --reload
# 另一终端
cd platform/frontend && npm run dev     # 5173
```

## 现状事实（2026-08-16 逐文件核实）

### 审计原文（`docs/22-prototype-runtime-gap-audit.md` §5，逐字引用）

| # | 工作区 / 页面 | 当前运行时 | 独立高保真参照 | 能力阶段 | 原型轨道 |
|---:|---|---|---|---:|---|
| 6 | Factors / Catalog | `runtime_partial` | 31 页蓝图 | P4 | PUI-04 |
| 7 | Factors / Alpha Model | `runtime_partial`：readiness/blocker，真实 Snapshot 为 0 | `factors-alpha-model` | P5/P9 | PUI-04 |
| 8 | Factors / Timing Lab | `runtime_partial`：被动 baseline | `11-timing-lab` | P7 | PUI-06 |
| 9 | Factors / Experiments | `runtime_partial`：真实失败 Experiment | 31 页蓝图 | P4 | PUI-04 |
| 10 | Factors / Correlation Monitor | `placeholder`/空合同 | 31 页蓝图 | P9 | PUI-08 |
| 11 | Factors / Production | `runtime_partial`：生命周期/空生产态 | 31 页蓝图 | P4/P9 | PUI-04/PUI-08 |
| 24 | System / Catalog | `runtime_partial`：Dataset/Financial Evidence | 31 页蓝图 | P1–P3 | PUI-04 |
| 25 | System / Quality | `runtime_partial` | `13-data-quality-lineage` | P1–P3/P9 | PUI-04/PUI-08 |
| 26 | System / Lineage | `runtime_partial` | `13-data-quality-lineage` | P1–P5/P9 | PUI-04/PUI-08 |
| 27 | System / Jobs | `runtime_partial` | 31 页蓝图 | P1–P3/P9 | PUI-04/PUI-08 |

注意审计已把第 8 行（Timing Lab）归给 **PUI-06**、第 10 行（Correlation Monitor）归给 **PUI-08**。
本 plan 仍需触碰这两页，但**只把它们改成诚实的阶段 blocker 分区**，不实现 P7/P9 能力。

### 十页真实 API 与设计输入对照

| 页面 | 路由 | 当前实现 | 真实端点 | Figma Frame | design_status |
|---|---|---|---|---|---|
| Factors / Catalog | `/factors?tab=catalog` | `FactorWorkspace.tsx` 中 **20 行硬编码 `factorDefinitions` 常量**（第 94–113 行） | 无专用端点 → 需 projection | **无** | `missing` |
| Factors / Alpha Model | `/factors?tab=alpha-model` | 一句 `WorkspaceState state="blocked"`（第 462–467 行）；**未复用已有 `AlphaModelReadinessPanel`** | `GET /api/research/workspace` → `alpha_model` | **有** `7:5` | 可 → `ready` |
| Factors / Timing Lab | `/factors?tab=timing-lab` | `TimingPanel`，`snapshot.timingBaseline` 恒为 `null`（第 188 行硬写） | 无（Timing 属 P7；`app.state.timing_repository` 仅供 Desk） | 有 `9:238`，但属 PUI-06 | `missing`（本 plan 不做 parity） |
| Factors / Experiments | `/factors?tab=experiments` | `ExperimentsPanel` 真实接线，失败 Experiment 保留 | `GET /api/experiments/runs` | **无** | `missing` |
| Factors / Correlation Monitor | `/factors?tab=correlation-monitor` | `CorrelationPanel`，`correlationPairs` 恒为 `[]`（第 189 行硬写） | 无（P9） | **无** | `missing` |
| Factors / Production | `/factors?tab=production` | `ProductionPanel`，`productionVersions` 恒为 `[]`（第 190 行硬写） | `GET /api/factors/reviews` | **无** | `missing` |
| System / Catalog | `/system?tab=catalog` | `SystemCatalogWorkspace` → `SystemScreen section="catalog"` + `SystemEvidenceScreen` | `GET /api/system/catalog` | **无** | `missing` |
| System / Quality | `/system?tab=quality` | `SystemScreen section="quality"`，`QualityTable` 6 列 | `GET /api/system/quality` | **有** `9:661` | 可 → `ready` |
| System / Lineage | `/system?tab=lineage` | `SystemScreen section="lineage"`，`LineageTable` 3 列 | `GET /api/system/lineage` | **有** `9:661` | 可 → `ready` |
| System / Jobs | `/system?tab=jobs` | `SystemScreen section="jobs"`，`JobCards` + coverage/checkpoint 双分页 | `GET /api/system/jobs` | **无** | `missing` |

**结论：10 页中只有 3 页（Alpha Model、Quality、Lineage）有独立高保真 Frame；7 页只有 31 页蓝图 `3:1569`。**
（若把归属 PUI-06 的 Timing Lab 也算进来，则 4 页有 Frame、6 页没有；但 Timing Lab 的 parity 属 PUI-06，本 plan 不认领。）

### `api/app.py` 已注册的相关端点（逐行 grep 得到的完整清单，不得发明新的）

```text
GET  /api/experiments/runs                    → 实验列表（本 plan 消费）
GET  /api/experiments/runs/{run_id}           → 单个实验（钻取用）
POST /api/experiments/runs                    → 需 CREATE_EXPERIMENT 权限；本 plan 不调用
GET  /api/factors/reviews                     → FactorPromotionReview 列表（Production 用）
GET  /api/factors/reviews/{review_id}         → 单个 Review（钻取用）
POST /api/factors/reviews                     → 写审批；本 plan 不调用
GET  /api/research/workspace                  → 含 alpha_model readiness（Alpha Model 用）
GET  /api/desk                                → 七分区（已由 PUI-01 消费）
GET  /api/system/catalog                      → DatasetCatalogEntry[]
GET  /api/system/quality                      → QualityReportEntry[]
GET  /api/system/lineage                      → LineageCatalogEntry[]
GET  /api/system/jobs                         → IngestionJobEntry[]（内嵌 checkpoints / quality / coverage）
GET  /api/system/disclosures                  → 披露时间线
GET  /api/system/facts/revisions               → 双时间事实修订
GET  /api/system/facts/compare                → current / strict 对比
GET  /api/system/mismatches                   → mismatch queue
GET  /api/system/evidence/{raw_object_id}     → 原始证据元数据
GET  /api/datasets, /api/runs                 → 治理账本（Lineage 钻取可用）
```

后端改动上限：**只允许新增只读 projection**（Factor Catalog 与 Production 各一个），
不新增领域数学、不新增写接口、不改任何 Gate。

### 已确认的可复用前端资产

```text
features/desk/DeskSection.tsx      59 行，props: {section, loading?, error?, subtitle?, extra?, children?}
features/desk/deskState.ts         resolveSectionState / noticeReason / coverageText / metricsFromPayload / coverageMetrics
features/desk/DeskMetricList.tsx   15 行，metrics: {label, value}[]
features/desk/deskTypes.ts         从 api/client 再导出 DeskSection / DeskBlocker / DeskSectionStatus
components/WorkspaceState.tsx      六态 + blocked 兼容别名；partial 会同时渲染 notice 与 children
components/PageHeading.tsx         {title, description, eyebrow?, extra?}
components/NumericCell.tsx         数值单元格
features/screen/AlphaModelReadinessPanel.tsx  已实现 ready / unavailable 双分支（当前未被 /factors 使用）
app/shell.less                     断点 1280 / 820 / 420；deskGrid = minmax(0,740fr) minmax(0,380fr)
scripts/verify_desk_browser.py     177 行 Playwright 四视口验收模板
```

### Figma 实测布局（本 plan 唯一两份可用的 Factor/System 高保真真源）

**`7:5` factors-alpha-model**，1440 × 1200（SVG viewBox 1440 × 1224）：

```text
sidebar        248 × 1200   VERTICAL gap 24（运行时用 280，已批准差异）
main-content  1192 × 1200
  topbar      1192 × 64     HORIZONTAL（left 385 / right 779，gap 16）
  workspace   1192 × 1160   VERTICAL gap 20
    metrics-row   1144 × 114  HORIZONTAL gap 16，4 张 kpi-card
                  实测矩形：x=272/562/852/1142, y=88, w=273, h≈113
    layout-columns 1144 × 978 HORIZONTAL gap 20
      left-col   x=272 w=723
        factor-weight-card   y=222  723 × 280（内表 x=292 w=683 h=207）
        snapshots-card       y=524  723 × 528（warning banner 683 × 38；empty-table 683 × 400，12 空行）
        flow-diagram-card    y=1072 723 × 127（5 个 flow-box 112 × 54，x=292/435/578/721/864）
      right-col  x=1016 w=399
        readiness-card       y=222  399 × 364（big-badge 359 × 40 + 5 项 checklist）
```

文本内容（决定信息架构，全部为 DESIGN FIXTURE，**不得进入运行时**）：

```text
KPI 四张：当前研究模型 DRAFT ALPHA-V0.8 / 激活绑定因子数 6 / 真实合格 Snapshot 数 0（缺少PIT验证，流程已阻断）
          / 生产运行主动影响 0%（降级为静态满仓基线模式）
因子权重配置表 6 列：因子 | 权重 | 版本 | Review ID | 用途 | 相关性警告
          示例行：质量 Quality 35% v2.1 RVW-041 长期选股 — / 估值 30% v1.8 RVW-038 价值发现 ⚠与质量相关 0.42
                  / 改善 25% v1.5 RVW-035 动量捕捉 — / 风险 10% v0.9 RVW-029 风险调整 ⚠DRAFT
                  / 总计 Total 100% 权重完整，符合配比约束
候选 Snapshot 表 7 列：Snapshot ID | 日期 | Universe | 覆盖 | 因子版本 | PIT状态 | 审批
          全部 12 行为 `—`（原型自己就画的是空态）
flow 五段：1. INPUT Factor + Universe → 2. PROCESS Score & Rank → 3. OUTPUT Immutable Snapshot
          → 4. ACTION 提交模型审查 → 5. GATE 阻断 (无PIT可用)
PIT Readiness 面板：PIT NOT READY 大徽章 + 5 项 checklist
          历史 Universe 截面 ✗缺失 / 季度财务 ✗缺失 / TTM 财务 ✗缺失
          / 个股价格 available_at ✓可用 / 行业分类 lineage ⚠部分可用
```

**`9:661` 13-data-quality-lineage**，1440 × 1200：

```text
sidebar     x=0   w=224（深色 #18202A；运行时 280，已批准差异）
topbar      x=224 w=1216 h=64（搜索框 380 × 32 at x=246；RESEARCH TIME / DATA MODE / DEPLOYMENT / UNIVERSE）
tabbar      x=224 w=1216 h=64  → 8 个 tab：Catalog | Quality | Lineage | Jobs | Entitlements | Users | Agents | Approvals
                                （Quality 带 110 × 3 下划线，即当前选中）
KPI 四张    y=196 w=264 h=92，x=246/524/802/1080
            Checks 184（13 suites）/ Passed 169（92%）/ Warned 12（传播到 current 页面）/ Blocked 3（禁止 strict 下游）
主表        x=246 w=790：标题条 h=42「质量报告与阻断传播」+ 表头 h=34 + 10 行 × h=39
            8 列：Check | Dataset | 规则 | 结果 | 影响 | 报告版本 | Run | 时间
            示例：Q-1300 financials Coverage Passed "Current warning" QR-v1 RUN-1400 08-13 8:00
右栏        x=1052 w=362：y=316 h=394「Quality / Lineage」四条规则 + y=726 h=96「可信使用边界」
            规则四条（badge + 说明）：
              阻断传播 BLOCKER    严重错误阻止 Factor/View/Backtest
              警告传播 ATTENTION  关键数字旁展示 warning 与 evidence
              双时间血缘 READY    effective/period 与 available_at 分开
              空期守卫 READY      有原始行但全 unmapped 不是合法空期
            可信使用边界：Current source 的 trust ceiling 不能提升；关键 evidence 断链即 fail closed。
底部五段    y=1062 w=214 h=102 × 5，x=246/470/694/918/1142
            INPUT 规则/数据版本·双时间与 raw hash | PROCESS 检查→报告→传播·血缘路径审计
            | OUTPUT QualityReport·Evidence/Lineage | ACTION 运行检查·从数字钻取证据
            | GATE 全 unmapped 非空期·断链 fail closed
```

`9:661` 同时是 **Quality 与 Lineage 两页的参照**（审计 §5 第 25、26 行都指向它）。
它的信息架构给出 `docs/18` §4 要求的固定五段（INPUT/PROCESS/OUTPUT/ACTION/GATE）—— 这是
本 plan 对**所有十页**的统一底部结构来源，包括没有 Frame 的七页。

### 已实测复现的既有缺陷

`/factors` 在 320 视口存在页面级水平溢出。2026-08-16 用 Playwright 实测：

```text
/factors     320 → scrollWidth 652, clientWidth 320   ← 溢出 332 px
/system      320 → scrollWidth 320, clientWidth 320   OK
/research    320 → scrollWidth 320, clientWidth 320   OK
/desk        320 → scrollWidth 320, clientWidth 320   OK
/portfolios  320 → scrollWidth 320, clientWidth 320   OK
/monitoring  320 → scrollWidth 320, clientWidth 320   OK
/factors    1440 → scrollWidth 1440                   OK（仅 320 复现）
```

**根因已定位，与 `docs/plans/track-00` 记录的「pageHeading 溢出」不同 —— `pageHeading` 是受害者而不是原因：**

```text
.workspacePage / .factorWorkspace  display: grid, grid-template-columns: 642.125px  ← 被内容撑开
.pageHeading                       w=642 right=652   （min-content 仅 187 px）
.factorGateAlert                   w=642 right=652
.ant-tabs                          w=642             （min-content 642 px ← 真正的撑宽者）
```

`.factorWorkspace` 在 `shell.less` 第 170–177 行声明 `display: grid; gap: 16px` 但**没有声明
`grid-template-columns`**，于是隐式列宽退化为 `auto`（= max-content），由 AntD Tabs 的
min-content 642 px 决定；`pageHeading`、`factorGateAlert` 作为同一网格的其他行被拉到同宽。
`.deskGrid`（第 349–354 行）显式用 `minmax(0, …fr)` 所以不受影响 —— 这也是 `/desk` 320 通过的原因。

单条 CSS 覆盖实验（浏览器内注入，逐条隔离）：

```text
.workspacePage{grid-template-columns:minmax(0,1fr)}      → 320  ✅
.factorWorkspace{grid-template-columns:minmax(0,1fr)}    → 320  ✅
.factorWorkspace > .ant-tabs{min-width:0}                → 320  ✅
.factorGateAlert{display:none}                           → 652  ❌（证明 alert 不是原因）
.pageHeading{display:none}                               → 652  ❌（证明 heading 不是原因）
.factorDefinitionGrid{display:none}                      → 652  ❌
```

修复后 320 仍有 `.ant-tabs-nav-list` 超出视口右边界，但 `.ant-tabs-nav-wrap` 的
`overflow: hidden` 使其在自身容器内滚动，页面级 `scrollWidth === clientWidth` 成立。
**这与未触碰的 `/monitoring` 320 行为完全一致**（同样实测确认），属 PUI-02 已记录的既有可接受行为。

### 页面三轴目标（本 plan 结束时的允许结论）

| 页面 | Design Parity 目标 | Runtime Product 目标 | Capability 目标 |
|---|---|---|---|
| Factors / Catalog | `missing`（记录设计假设） | `verified` | `blocked`（P4） |
| Factors / Alpha Model | `parity_verified_with_known_deviation`（node `7:5`） | `verified` | `blocked`（P4/P5） |
| Factors / Timing Lab | `missing`（parity 属 PUI-06） | `verified`（诚实 P7 blocker） | `blocked`（P7） |
| Factors / Experiments | `missing`（记录设计假设） | `verified` | `blocked`（P4） |
| Factors / Correlation Monitor | `missing` | `verified`（诚实 P9 blocker） | `blocked`（P9） |
| Factors / Production | `missing`（记录设计假设） | `verified` | `blocked`（P4/P9） |
| System / Catalog | `missing`（记录设计假设） | `verified` | `partial`（P1–P3 已有真实数据） |
| System / Quality | `parity_verified_with_known_deviation`（node `9:661`） | `verified` | `partial` |
| System / Lineage | `parity_verified_with_known_deviation`（node `9:661`） | `verified` | `partial` |
| System / Jobs | `missing`（记录设计假设） | `verified` | `partial` |

**七页 design_status 保持 `missing` 是本 plan 的正确结果，不是失败。** 没有精确 Frame 就不能声称 parity；
能做的是按 31 页蓝图 `3:1569` 的信息架构 + `9:661` 的五段固定结构开发，并把每条设计假设写进 Evidence 等用户验收。

---

### Task 1: 修复 `/factors` 320 视口页面级水平溢出（既有缺陷）

`docs/plans/track-00-prototype-runtime-delivery.md` §待修复的既有缺陷把它登记为「`pageHeading` 溢出」。
2026-08-16 实测确认 **`pageHeading` 是受害者不是原因**：`.factorWorkspace` 声明了 `display: grid`
却没声明 `grid-template-columns`，隐式列退化为 max-content，被 AntD Tabs 的 642 px min-content 撑开，
同网格的 `pageHeading` / `factorGateAlert` 被拉到同宽。

先修这一条，因为后续九个 Task 都要跑 320 验收 —— 带着已知溢出做 parity 对照会掩盖新引入的溢出。

**Files:**
- Modify: `platform/frontend/src/app/shell.less`（`.factorWorkspace`，第 170–177 行附近）
- Create: `platform/frontend/src/app/layoutGrid.test.ts`
- Create: `platform/scripts/verify_factor_system_browser.py`

**Interfaces:**
- Consumes: 已有 `.deskGrid` 的 `minmax(0, …fr)` 模式（`shell.less` 第 349–354 行）
- Produces: `/factors` 四视口 `document.documentElement.scrollWidth === clientWidth`

- [ ] **Step 1: 用真实浏览器复现缺陷并记录数值**

两个服务必须已在跑（见「前置条件」）。

```bash
cd platform
.venv/bin/python - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    for name, w, h in (("1440", 1440, 900), ("1024", 1024, 768), ("768", 768, 1024), ("320", 320, 640)):
        c = b.new_context(viewport={"width": w, "height": h})
        page = c.new_page()
        page.goto("http://127.0.0.1:5173/factors", wait_until="networkidle")
        page.wait_for_timeout(1200)
        m = page.evaluate("""() => ({
            scrollWidth: document.documentElement.scrollWidth,
            clientWidth: document.documentElement.clientWidth,
        })""")
        print(name, m, "OVERFLOW" if m["scrollWidth"] > m["clientWidth"] else "ok")
        c.close()
    b.close()
PY
```

Expected（2026-08-16 实测基线，必须先看到它才动手）：

```text
1440 {'scrollWidth': 1440, 'clientWidth': 1440} ok
1024 {'scrollWidth': 1024, 'clientWidth': 1024} ok
768  {'scrollWidth': 768,  'clientWidth': 768}  ok
320  {'scrollWidth': 652,  'clientWidth': 320}  OVERFLOW
```

若 320 已经不溢出，**停下来**：说明有人已修或环境不同，先查清再决定是否还需本 Task。

- [ ] **Step 2: 定位真正的撑宽者（不要照抄 track-00 的「pageHeading」结论）**

```bash
cd platform
.venv/bin/python - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    c = b.new_context(viewport={"width": 320, "height": 640})
    page = c.new_page()
    page.goto("http://127.0.0.1:5173/factors", wait_until="networkidle")
    page.wait_for_timeout(1200)
    # Isolate one override at a time; a fix that works only in combination
    # hides which declaration is actually wrong.
    for name, css in (
        (".workspacePage 1fr", ".workspacePage{grid-template-columns:minmax(0,1fr)}"),
        (".factorWorkspace 1fr", ".factorWorkspace{grid-template-columns:minmax(0,1fr)}"),
        ("tabs min-width:0", ".factorWorkspace > .ant-tabs{min-width:0}"),
        ("hide gate alert", ".factorGateAlert{display:none}"),
        ("hide pageHeading", ".pageHeading{display:none}"),
    ):
        width = page.evaluate("""(css) => {
            const style = document.createElement('style')
            style.textContent = css
            document.head.appendChild(style)
            const width = document.documentElement.scrollWidth
            style.remove()
            return width
        }""", css)
        print(f"{name:24s} scrollWidth={width}")
    c.close()
    b.close()
PY
```

Expected（实测）：前三条各自把 652 降到 320；后两条仍是 652。
**这证明 `pageHeading` 与 `factorGateAlert` 都不是原因** —— 它们只是被同一网格拉宽的行。

- [ ] **Step 3: 写红测 —— 网格声明不变量**

Less 无法在 jsdom 里做布局断言，所以断言的对象是**源文件里的声明本身**：任何用于承载
AntD Tabs 或表格的 `display: grid` 容器都必须显式声明 `minmax(0, …)` 列，否则隐式 max-content
列会被子树的 min-content 撑开。这条不变量能挡住同类回归（下一个人再加一个 grid 容器时）。

```ts
// platform/frontend/src/app/layoutGrid.test.ts
/**
 * Grid containers that hold a Tabs or a table must declare bounded columns.
 *
 * A `display: grid` container without `grid-template-columns` gets an implicit
 * max-content column, so the widest descendant sets the page width.  On
 * /factors that descendant is the AntD Tabs nav (min-content 642 px), which
 * pushed the 320 viewport to scrollWidth 652 — a page-level horizontal
 * overflow.  `.deskGrid` already declares `minmax(0, …fr)` and is why /desk
 * never had the bug.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const shell = readFileSync(fileURLToPath(new URL('./shell.less', import.meta.url)), 'utf8')

function block(selector: string): string {
  const start = shell.indexOf(selector)
  if (start < 0) throw new Error(`selector not found in shell.less: ${selector}`)
  const open = shell.indexOf('{', start)
  const close = shell.indexOf('}', open)
  return shell.slice(open, close)
}

describe('shell.less grid containers', () => {
  it.each([
    '.factorWorkspace,',
    '.workspacePage {',
  ])('%s bounds its columns so a wide child cannot widen the page', (selector) => {
    const declarations = block(selector)
    if (!declarations.includes('display: grid')) return
    expect(declarations).toMatch(/grid-template-columns:\s*minmax\(0,/)
  })

  it('keeps the deskGrid ratio columns that PUI-01 verified', () => {
    // Regression guard: the 740fr/380fr ratio absorbs the 280 vs 248 px sider
    // difference.  Replacing it with fixed px would reintroduce overflow.
    expect(block('.deskGrid {')).toContain('minmax(0, 740fr) minmax(0, 380fr)')
  })
})
```

- [ ] **Step 4: 运行确认红测**

Run: `cd platform && npm --prefix frontend test -- --run src/app/layoutGrid.test.ts`

Expected: FAIL —— `.factorWorkspace` 的声明块里有 `display: grid` 但没有
`grid-template-columns: minmax(0, …)`。把真实失败文本抄进 Evidence。

- [ ] **Step 5: 最小实现**

在 `shell.less` 第 170–177 行的规则里补一行显式列声明，并留下解释性注释：

```less
.factorWorkspace,
.factorCatalog,
.experimentList,
.correlationList,
.productionList {
  display: grid;
  // An implicit grid column is max-content, so the AntD Tabs nav (min-content
  // 642 px) would set the page width and overflow the 320 viewport.  Bounding
  // the column at minmax(0, 1fr) lets the tab strip scroll inside its own
  // container instead — the same reason .deskGrid declares ratio tracks.
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}
```

`.correlationList` 与 `.productionList` 在第 268–271 行另有 `repeat(auto-fit, minmax(260px, 1fr))`
覆盖，`auto-fit` 已是有界列，**不要动它**。

- [ ] **Step 6: 转绿**

Run: `cd platform && npm --prefix frontend test -- --run src/app/layoutGrid.test.ts`
Expected: PASS

- [ ] **Step 7: 建立本 plan 专用的四视口验收脚本**

照抄 `platform/scripts/verify_desk_browser.py` 的结构（177 行，已验证可用），把 URL 换成
`/factors` 与 `/system` 的六个 tab，`DESIGN_FIXTURES` 换成 `7:5` 与 `9:661` 的示例值。

```python
# platform/scripts/verify_factor_system_browser.py
"""PUI-04 four-viewport acceptance for the Factor and System workspaces.

Not part of the test suite.  Component tests cannot see page-level horizontal
overflow, right-edge clipping or console errors, and curl cannot see layout at
all — so this drives the installed Chrome against a live API and dev server.

`DESIGN_FIXTURES` holds the sample values drawn in Figma nodes 7:5 and 9:661.
They must never reach the runtime: the prototype's 35%/30%/25%/10% weights and
its 184/169/12/3 check counts are design fixtures, not platform facts.
"""

from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

PAGES = (
    ("factors-catalog", "http://127.0.0.1:5173/factors?tab=catalog"),
    ("factors-alpha-model", "http://127.0.0.1:5173/factors?tab=alpha-model"),
    ("factors-timing-lab", "http://127.0.0.1:5173/factors?tab=timing-lab"),
    ("factors-experiments", "http://127.0.0.1:5173/factors?tab=experiments"),
    ("factors-correlation", "http://127.0.0.1:5173/factors?tab=correlation-monitor"),
    ("factors-production", "http://127.0.0.1:5173/factors?tab=production"),
    ("system-catalog", "http://127.0.0.1:5173/system?tab=catalog"),
    ("system-quality", "http://127.0.0.1:5173/system?tab=quality"),
    ("system-lineage", "http://127.0.0.1:5173/system?tab=lineage"),
    ("system-jobs", "http://127.0.0.1:5173/system?tab=jobs"),
)
VIEWPORTS = (("1440", 1440, 900), ("1024", 1024, 768), ("768", 768, 1024), ("320", 320, 640))
DESIGN_FIXTURES = (
    "ALPHA-V0.8", "RVW-041", "RVW-038", "RVW-035", "RVW-029",
    "35%", "0.42", "Q-1300", "RUN-1400", "QR-v1", "13 suites", "92%",
)
# The tab strip scrolls inside .ant-tabs-nav-wrap (overflow: hidden) at 320.
# That is pre-existing, matches the untouched /monitoring page, and does not
# widen the document, so it is excluded from the clipping check.
ALLOWED_CLIP_PREFIXES = ("DIV.ant-tabs-nav-list", "DIV.ant-tabs-tab")


def run() -> int:
    results: dict[str, dict[str, object]] = {}
    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        for label, url in PAGES:
            for name, width, height in VIEWPORTS:
                context = browser.new_context(viewport={"width": width, "height": height})
                page = context.new_page()
                console: list[str] = []
                requests: list[str] = []
                page.on("console", lambda m: console.append(f"{m.type}: {m.text}")
                        if m.type in ("error", "warning") else None)
                page.on("response", lambda r: requests.append(f"{r.status} {r.url}")
                        if r.status >= 400 and "/api/" not in r.url else None)
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(1200)

                metrics = page.evaluate("""() => ({
                    scrollWidth: document.documentElement.scrollWidth,
                    clientWidth: document.documentElement.clientWidth,
                })""")
                overflow = metrics["scrollWidth"] > metrics["clientWidth"]
                clipped = page.evaluate(
                    """(width) => Array.from(document.querySelectorAll('*'))
                        .filter((node) => {
                            const box = node.getBoundingClientRect()
                            return box.width > 0 && box.right > width + 1
                        })
                        .slice(0, 8)
                        .map((node) => `${node.tagName}.${node.className}`.slice(0, 80))""",
                    width,
                )
                clipped = [
                    value for value in clipped
                    if not value.startswith(ALLOWED_CLIP_PREFIXES)
                ]
                leaked = [v for v in DESIGN_FIXTURES if v in page.inner_text("body")]

                key = f"{label}@{name}"
                results[key] = {
                    "scrollWidth": metrics["scrollWidth"],
                    "clientWidth": metrics["clientWidth"],
                    "page_level_overflow": overflow,
                    "clipped_elements": clipped,
                    "design_fixture_leaks": leaked,
                    "console_errors_warnings": console,
                    "http_4xx_5xx": requests,
                }
                if overflow:
                    failures.append(f"{key}: page-level horizontal overflow")
                if clipped:
                    failures.append(f"{key}: right-edge clipping {clipped}")
                if leaked:
                    failures.append(f"{key}: DESIGN FIXTURE leak {leaked}")
                if console:
                    failures.append(f"{key}: console {console}")
                if requests:
                    failures.append(f"{key}: network {requests}")
                page.screenshot(path=f"/tmp/pui04-{label}-{name}.png", full_page=True)
                context.close()
        browser.close()
    print(json.dumps(results, ensure_ascii=False, indent=1))
    if failures:
        print("\nFAILURES:", file=sys.stderr)
        for item in failures:
            print(f" - {item}", file=sys.stderr)
        return 1
    print("\nALL VIEWPORT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
```

`/api/` 的 4xx/5xx 被排除在失败之外，因为无库运行时 `503` 是**被验收的真实状态**；
非 API 的 4xx/5xx（缺失资源、坏 chunk）仍然失败。

- [ ] **Step 8: 跑一次，确认 320 溢出已消除**

Run: `cd platform && .venv/bin/python scripts/verify_factor_system_browser.py`

此时会有其他 FAILURES（DESIGN FIXTURE 尚未接线、控制台警告等），**只需确认
`page_level_overflow` 全为 `false`**。剩余项由后续 Task 逐个消除。

- [ ] **Step 9: 全量验证并提交**

```bash
cd platform
npm --prefix frontend test -- --run
npm --prefix frontend run lint
npm --prefix frontend run build
cd .. && git add platform/frontend/src/app/shell.less \
  platform/frontend/src/app/layoutGrid.test.ts \
  platform/scripts/verify_factor_system_browser.py
git commit -m "fix: bound the factor workspace grid column so 320 stops overflowing

The defect was logged as a pageHeading overflow, but the heading was the victim.
.factorWorkspace declared display:grid without grid-template-columns, so the
implicit column resolved to max-content and the AntD Tabs nav — min-content
642 px — set the page width.  Every other row of that grid, heading included,
was then stretched to 642 px inside a 320 px viewport.

Bounding the track at minmax(0, 1fr) lets the tab strip scroll inside its own
overflow:hidden wrapper, which is what /desk has always done and why /desk never
showed the bug.  The test asserts the declaration rather than the layout: jsdom
cannot measure grids, but a grid container that forgets to bound its columns is
exactly the mistake worth catching in the next contributor's diff."
```

---

### Task 2: 把 Factor 工作区拆成分区并复用 PUI-01 的 `DeskSection` 合同

当前 `FactorWorkspace.tsx` 是 496 行的单文件，把六个 tab 的面板、图表、映射函数和硬编码定义全塞在
一起。九个 Task 都要改它，先拆分再逐页填内容 —— 否则每个 Task 的 diff 都会互相冲突。

关键约束：**复用 `features/desk/DeskSection.tsx`，不要发明第二套分区组件。** 它已经把
「服务端四态 + 客户端 loading/error + blocker 列表 + coverage 说明 + 可访问 region 名」做对了，
并有 `DeskSection.test.tsx` 的 8 个测试守着。

**Files:**
- Create: `platform/frontend/src/features/factors/factorSections.tsx`
- Create: `platform/frontend/src/features/factors/factorTypes.ts`
- Create: `platform/frontend/src/features/factors/factorSections.test.tsx`
- Modify: `platform/frontend/src/pages/FactorWorkspace.tsx`
- Modify: `platform/frontend/src/pages/FactorWorkspace.test.tsx`

**Interfaces:**
- Consumes: `features/desk/DeskSection.tsx`、`features/desk/deskState.ts`、`features/desk/DeskMetricList.tsx`
- Produces:
  ```ts
  // features/factors/factorTypes.ts — 复用 desk 的分区形状，不重新声明
  export type { DeskBlocker as FactorBlocker, DeskSectionStatus as FactorSectionStatus } from '../../api/client'
  export interface FactorSection {
    key: FactorSectionKey
    status: FactorSectionStatus
    title: string
    blockers: FactorBlocker[]
    coverage: Record<string, unknown>
    payload: unknown
  }
  export type FactorSectionKey =
    | 'catalog' | 'alpha_model' | 'timing_lab'
    | 'experiments' | 'correlation_monitor' | 'production'
  ```

- [ ] **Step 1: 读现有分区合同，确认 props 与状态解析规则**

```bash
cd platform/frontend/src
sed -n 1,60p features/desk/DeskSection.tsx
sed -n 20,55p features/desk/deskState.ts
grep -n "WorkspaceStateKind" -A12 components/WorkspaceState.tsx
```

要点（不要改这些）：`resolveSectionState` 里 `loading` 与 `error` 由客户端提供，
其余状态**原样透传服务端**；`partial` 会同时渲染 notice 与 children；
`unavailable` / `partial` 才渲染 blocker 列表。

- [ ] **Step 2: 写红测 —— 分区在 unavailable 时仍渲染，且必须带阶段 blocker**

这是 PUI-02 浏览器验收踩过的坑：原实现在 workspace `unavailable` 时**整体跳过构建器分支**，
页面退化成一条泛化提示。分区必须永远存在。

```tsx
// platform/frontend/src/features/factors/factorSections.test.tsx
/**
 * The six factor sections keep their structure in every state.
 *
 * PUI-02 shipped a builder that skipped its whole branch when the workspace was
 * unavailable, and the page collapsed into one generic notice.  A section that
 * disappears reads as "nothing to report"; a section that stays and states its
 * blocker reads as "this is not built yet", which is the truth.
 */
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { CorrelationMonitorSection, ProductionSection, TimingLabSection } from './factorSections'
import type { FactorSection } from './factorTypes'

function section(overrides: Partial<FactorSection> = {}): FactorSection {
  return {
    key: 'correlation_monitor',
    status: 'unavailable',
    title: '因子相关性监控',
    blockers: [{
      code: 'P9_CORRELATION_MONITOR_NOT_IMPLEMENTED',
      reason: '获批因子截面相关性与容量监控属 P9，尚未实现。',
      affected_binding: 'factor.correlation_monitor',
      evidence_ids: [],
    }],
    coverage: {},
    payload: null,
    ...overrides,
  }
}

describe('factor sections', () => {
  afterEach(cleanup)

  it('keeps the correlation section present and names its P9 blocker', () => {
    render(<CorrelationMonitorSection section={section()} />)
    expect(screen.getByRole('region', { name: '因子相关性监控' })).toBeInTheDocument()
    expect(screen.getByText('P9_CORRELATION_MONITOR_NOT_IMPLEMENTED')).toBeInTheDocument()
    expect(screen.getByText(/属 P9，尚未实现/)).toBeInTheDocument()
  })

  it('never renders a zero correlation for an absent pair', () => {
    render(<CorrelationMonitorSection section={section()} />)
    expect(screen.queryByText('0')).not.toBeInTheDocument()
    expect(screen.queryByText('0.00')).not.toBeInTheDocument()
  })

  it('states the P7 stage blocker on the timing section rather than a fake baseline', () => {
    render(<TimingLabSection section={section({
      key: 'timing_lab',
      title: 'Timing Lab',
      blockers: [{
        code: 'P7_ACTIVE_TIMING_NOT_IMPLEMENTED',
        reason: '主动 Timing 模型属 P7；被动 baseline 不冒充主动预测。',
        affected_binding: 'timing.active_model',
        evidence_ids: [],
      }],
    })} />)
    expect(screen.getByText('P7_ACTIVE_TIMING_NOT_IMPLEMENTED')).toBeInTheDocument()
    expect(screen.getByText(/不冒充主动预测/)).toBeInTheDocument()
  })

  it('shows an empty production section as "no approved version", not as unavailable', () => {
    // Empty and unavailable are different facts: the approval ledger works and
    // holds no approved version, which is not the same as having no ledger.
    render(<ProductionSection section={section({
      key: 'production',
      status: 'empty',
      title: '生产因子',
      blockers: [],
    })} />)
    expect(screen.getByText('暂无记录')).toBeInTheDocument()
    expect(screen.queryByText('能力未启用')).not.toBeInTheDocument()
  })

  it('renders a request error without substituting content', () => {
    render(<ProductionSection error="读取失败：503" section={section({
      key: 'production', title: '生产因子', blockers: [],
    })} />)
    expect(screen.getByText('读取失败：503')).toBeInTheDocument()
  })
})
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform && npm --prefix frontend test -- --run src/features/factors/factorSections.test.tsx`
Expected: FAIL —— `features/factors/factorSections` 不存在。

- [ ] **Step 4: 最小实现 —— 六个分区壳，全部委托给 `DeskSection`**

```tsx
// 形态示例；每个分区只做「取 payload → 交给 DeskSection」
export function CorrelationMonitorSection({ section, loading, error }: FactorSectionProps) {
  // P9 capability.  The server declares it unavailable and the card shows the
  // blocker; no correlation matrix is ever synthesised in the browser.
  return <DeskSection error={error} loading={loading} section={section} subtitle="Correlation Monitor" />
}
```

`DeskSection` 的 `section` prop 类型是 `api/client` 的 `DeskSection`，而 `FactorSection` 与它
**结构相同但 `key` 域不同**。不要为此放宽 `DeskSection` 的类型 —— 把 `DeskSection` 的 props 抽成
一个不含 `key` 枚举约束的 `GovernedSection` 接口（同文件内），两个 feature 各自窄化。
这一步只改类型，不改行为，`DeskSection.test.tsx` 必须继续全绿。

- [ ] **Step 5: 转绿并确认 desk 没有回归**

```bash
cd platform
npm --prefix frontend test -- --run src/features/factors/factorSections.test.tsx
npm --prefix frontend test -- --run src/features/desk src/pages/DeskPage.test.tsx
```
Expected: 两者都 PASS。若 desk 测试红了，说明类型抽取动到了行为，回退重做。

- [ ] **Step 6: 把 `FactorWorkspace.tsx` 改成只做路由与分区装配**

删除 `CatalogPanel` / `ExperimentsPanel` / `CorrelationPanel` / `TimingPanel` / `ProductionPanel`
的内联定义，改为从 `features/factors/factorSections` 导入。**保留** `mapExperiment`、
`failureSummary`、`failureBlockerCount` 的行为（有测试覆盖），只是移动位置。

`FactorWorkspace.test.tsx` 的 6 个现有测试**必须继续全绿**，特别是：

- `keeps failed experiments visible with OOS and multiple-testing evidence`
- `summarizes persisted qualification failures without hiding immutable details`
- `does not turn absent correlation or production data into numeric zero`

若某个断言因为文案调整而失败，**改断言前先确认新文案没有削弱信息**（比如把
「失败保留」改成「已归档」就是削弱，不允许）。

- [ ] **Step 7: 全量前端验证并提交**

```bash
cd platform
npm --prefix frontend test -- --run
npm --prefix frontend run lint
npm --prefix frontend run build
cd .. && git add platform/frontend/src/features/factors/ \
  platform/frontend/src/pages/FactorWorkspace.tsx \
  platform/frontend/src/pages/FactorWorkspace.test.tsx \
  platform/frontend/src/features/desk/DeskSection.tsx
git commit -m "refactor: give the factor workspace the PUI-01 section contract

FactorWorkspace was 496 lines holding six panels, their charts, their mapping
functions and a hard-coded definition list.  Every remaining PUI-04 task needs
to touch it, so it is split first: the page now routes and assembles, and each
section is its own component.

The sections delegate to the desk's DeskSection rather than getting a second
section pattern.  That component already resolves the four server states plus
the client's loading and error, renders blockers for unavailable and partial,
and names its region for screen readers — all covered by its own tests.  A
parallel implementation would drift from it within one task.

The shared props are lifted into an interface without a key enum so both
features can narrow it, which keeps DeskSection's own tests green."
```

---

### Task 3: Factor Catalog —— 用服务端投影替换 20 行硬编码定义

`FactorWorkspace.tsx` 第 94–113 行的 `factorDefinitions` 是前端常量，写着
「行业模板和 4 家手算已实现」这类工程说明。这与 PUI-01 删掉 `capabilityRows` 是同一个问题：
**页面在讲自己的实现进度，而不是展示受治理对象。**

`docs/18` §3.2 对 Catalog 的定义是：FactorDefinition、公式、单位、缺失策略和行业适用；
不可变 FactorVersion 和 PromotionReview；Gate 为「测试通过不代表科学有效」。

**Files:**
- Create: `platform/src/a_share_platform/application/factor_catalog.py`
- Create: `platform/tests/test_factor_catalog_projection.py`
- Modify: `platform/src/a_share_platform/api/app.py`（新增 `GET /api/factors/catalog`）
- Modify: `platform/tests/test_factor_api.py`（若无此文件则按现有命名新建）
- Modify: `platform/frontend/src/api/client.ts`
- Modify: `platform/frontend/src/features/factors/factorSections.tsx`
- Test: `platform/frontend/src/features/factors/factorCatalog.test.tsx`

**Interfaces:**
- Consumes: 已有 `ports/factor_reviews.FactorReviewRepository`、`domain/factor_lifecycle.FactorVersion`
  （字段：`factor_version_id`、`factor_id`、`semantic_version`、`definition_hash`、`code_sha`、
  `dataset_version_ids`、`feature_version_ids`、`model_version_ids`、`status`、`created_at`、`content_hash`）
- Produces: `FactorCatalogProjectionService.project() -> dict`，形状与 desk 分区一致
  （`status` / `blockers` / `coverage` / `payload`）

- [ ] **Step 1: 确认 FactorVersion 与 lifecycle 的真实字段**

```bash
cd platform
grep -n "class FactorLifecycleStatus" -A10 src/a_share_platform/domain/factor_lifecycle.py
grep -n "class FactorVersion" -A20 src/a_share_platform/domain/factor_lifecycle.py
grep -n "class FactorPromotionReview" -A15 src/a_share_platform/domain/factor_reviews.py
cat src/a_share_platform/ports/factor_reviews.py
```

已核实：`FactorLifecycleStatus` 七值 `draft / research / shadow / candidate / production /
suspended / retired`；`FactorPromotionReview.__post_init__` **强制 `candidate` 状态**，
所以 Review 列表天然只含候选版本。**以代码为准**，若字段与此处不同，改本 plan 的后续步骤。

- [ ] **Step 2: 写后端红测 —— 空账本产出 empty 而非 unavailable**

```python
# platform/tests/test_factor_catalog_projection.py
"""Factor catalog as a server projection, not a frontend constant.

The page previously listed its own implementation progress from a hard-coded
array.  This projection lists governed objects instead, and it must distinguish
two facts the old constant could not express: a reachable ledger holding no
factor version (empty) and no ledger at all (unavailable).  Conflating them
tells the researcher to wait for data when nothing is configured.
"""

from __future__ import annotations

import unittest

from a_share_platform.application.factor_catalog import FactorCatalogProjectionService
from a_share_platform.ports.factor_reviews import FactorReviewStoreUnavailable


class EmptyLedger:
    def list_reviews(self) -> tuple[object, ...]:
        return ()


class OfflineLedger:
    def list_reviews(self) -> tuple[object, ...]:
        raise FactorReviewStoreUnavailable("ASP_DATABASE_URL is not configured")


class FactorCatalogProjectionTest(unittest.TestCase):
    def test_reachable_but_empty_ledger_is_empty_not_unavailable(self) -> None:
        projection = FactorCatalogProjectionService(factor_reviews=EmptyLedger()).project()
        self.assertEqual(projection["status"], "empty")
        self.assertEqual(projection["blockers"], [])

    def test_offline_ledger_is_unavailable_with_a_reason(self) -> None:
        projection = FactorCatalogProjectionService(factor_reviews=OfflineLedger()).project()
        self.assertEqual(projection["status"], "unavailable")
        self.assertEqual(len(projection["blockers"]), 1)
        self.assertIn("ASP_DATABASE_URL", projection["blockers"][0]["reason"])

    def test_projection_never_reports_a_scientific_verdict(self) -> None:
        """Lifecycle status is governance; it is not evidence of edge."""
        projection = FactorCatalogProjectionService(factor_reviews=EmptyLedger()).project()
        serialised = repr(projection)
        self.assertNotIn("scientifically_valid", serialised)
        self.assertNotIn("effective", serialised)

    def test_projection_does_not_invent_a_definition_the_ledger_lacks(self) -> None:
        """The old hard-coded list named three factors the ledger never held."""
        projection = FactorCatalogProjectionService(factor_reviews=EmptyLedger()).project()
        serialised = repr(projection)
        for invented in ("Quality V0", "Valuation Expectation Gap V0", "Fundamental Improvement V0"):
            self.assertNotIn(invented, serialised)
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_factor_catalog_projection -v`
Expected: FAIL —— `application.factor_catalog` 不存在。抄真实错误进 Evidence。

- [ ] **Step 4: 最小实现 + 接 API**

投影只做「读账本 → 分组 → 报状态」。**不算任何统计量**，`scientific_status` 若有则原样透传。
`api/app.py` 新增：

```python
@app.get("/api/factors/catalog", response_model=Envelope)
def factor_catalog(
    context: Annotated[RunContext, Depends(fixed_read_context)],
) -> Envelope:
    return envelope(factor_catalog_service.project(), context)
```

照抄同文件 `system_datasets` 的写法（第 1090 行附近），复用已有 `envelope` 与 `fixed_read_context`。

- [ ] **Step 5: 转绿并同步 OpenAPI 类型**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest tests.test_factor_catalog_projection -v
PYTHON_BIN=../.venv/bin/python npm --prefix frontend run generate:api
git diff --stat platform/frontend/src/api
```

- [ ] **Step 6: 写前端红测 —— 硬编码常量必须消失**

```tsx
// platform/frontend/src/features/factors/factorCatalog.test.tsx
/**
 * The catalog renders governed objects, never the old frontend constant.
 *
 * `factorDefinitions` was 20 lines of local text describing the platform's own
 * build progress ("行业模板和 4 家手算已实现").  PUI-01 removed the same pattern
 * from the desk.  These assertions fail if any of it survives.
 */
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { CatalogSection } from './factorSections'
import type { FactorSection } from './factorTypes'

function catalogSection(overrides: Partial<FactorSection> = {}): FactorSection {
  return {
    key: 'catalog',
    status: 'empty',
    title: '因子目录',
    blockers: [],
    coverage: {},
    payload: null,
    ...overrides,
  }
}

describe('CatalogSection', () => {
  afterEach(cleanup)

  it('no longer renders the hard-coded engineering definition list', () => {
    render(<CatalogSection section={catalogSection()} />)
    expect(screen.queryByText('Quality V0')).not.toBeInTheDocument()
    expect(screen.queryByText('Valuation Expectation Gap V0')).not.toBeInTheDocument()
    expect(screen.queryByText('Fundamental Improvement V0')).not.toBeInTheDocument()
    expect(screen.queryByText(/行业模板和 4 家手算已实现/)).not.toBeInTheDocument()
    expect(screen.queryByText(/没有注入运行时演示结果/)).not.toBeInTheDocument()
  })

  it('renders a served factor version with its lifecycle and hashes', () => {
    render(<CatalogSection section={catalogSection({
      status: 'ready',
      payload: {
        versions: [{
          factor_version_id: 'factor-version:quality:v0',
          factor_id: 'factor:quality',
          semantic_version: '0.1.0',
          definition_hash: 'a'.repeat(64),
          code_sha: 'b'.repeat(40),
          status: 'draft',
          dataset_version_ids: ['dataset:csi500-financials:v1'],
        }],
      },
    })} />)
    expect(screen.getByText('factor-version:quality:v0')).toBeInTheDocument()
    expect(screen.getByText('draft')).toBeInTheDocument()
    expect(screen.getByText('a'.repeat(64))).toBeInTheDocument()
  })

  it('shows the lifecycle status without implying scientific validity', () => {
    render(<CatalogSection section={catalogSection({
      status: 'ready',
      payload: {
        versions: [{
          factor_version_id: 'factor-version:quality:v0',
          factor_id: 'factor:quality',
          semantic_version: '0.1.0',
          definition_hash: 'a'.repeat(64),
          code_sha: 'b'.repeat(40),
          status: 'draft',
          dataset_version_ids: [],
        }],
      },
    })} />)
    // A draft version shown without this caveat reads as a validated factor.
    expect(screen.getByText(/生命周期状态不代表科学有效/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 7: 实现前端 → 转绿 → 四视口验收**

```bash
cd platform
npm --prefix frontend test -- --run src/features/factors
.venv/bin/python scripts/verify_factor_system_browser.py
```

必须：`factors-catalog@320` 无页面级溢出、无 DESIGN FIXTURE 泄漏、无控制台 error/warning。

- [ ] **Step 8: 记录设计假设（本页无 Figma Frame）**

在 Evidence 中明确写：Factor Catalog **没有独立高保真 Frame**，`design_status` 保持 `missing`。
本页布局假设逐条列出（至少）：

1. 沿用 `9:661` 的四张 KPI 卡片 + 主表 + 右栏规则 + 底部五段结构；
2. KPI 四项选为：FactorVersion 总数 / candidate 数 / production 数 / 已通过科学门数；
3. 主表列选为：FactorVersion | Factor | 语义版本 | 生命周期 | definition hash | DatasetVersion 数；
4. 底部五段按 `docs/18` §4 固定文案，不自创。

**这些是假设，不是 parity。** 等用户验收后才可能升级。

- [ ] **Step 9: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
npm --prefix frontend test -- --run && npm --prefix frontend run lint && npm --prefix frontend run build
cd .. && git add platform/src/a_share_platform/application/factor_catalog.py \
  platform/src/a_share_platform/api/app.py \
  platform/tests/test_factor_catalog_projection.py \
  platform/frontend/src/api/ platform/frontend/src/features/factors/
git commit -m "feat: serve the factor catalog as a projection instead of a frontend constant

The catalog listed three factors from a 20-line local array that described the
platform's own build progress — 行业模板和 4 家手算已实现 — which is the same
mistake PUI-01 removed from the desk.  A page that narrates its implementation
cannot show a governed object, and the three names it printed were never in the
ledger at all.

The projection separates two facts the constant could not express: a reachable
review ledger holding no factor version is empty, while no ledger is
unavailable.  Telling a researcher to wait for data when nothing is configured
wastes the one thing the page exists to protect — trust in what it shows.

Lifecycle status ships with the caveat that it is governance, not evidence of
edge.  A draft version rendered bare reads as a validated factor."
```

---

### Task 4: Alpha Model —— 对 Figma node `7:5` 做 1440 结构对照

这是本 plan **唯一一页 Factor 侧有精确 Frame** 的页面，也是唯一可能达到
`parity_verified_with_known_deviation` 的 Factor 页。

当前 `/factors?tab=alpha-model` 只渲染一句 `WorkspaceState state="blocked"`
（`FactorWorkspace.tsx` 第 462–467 行），而 `features/screen/AlphaModelReadinessPanel.tsx`
**已经实现了完整的 ready / unavailable 双分支并有测试** —— 它只是没被 `/factors` 用上。
所以本 Task 主要是接线 + 按 `7:5` 补齐四张 KPI、权重表、Snapshot 表与 readiness 面板的结构。

**Files:**
- Modify: `platform/frontend/src/features/factors/factorSections.tsx`
- Create: `platform/frontend/src/features/factors/AlphaModelWorkspace.tsx`
- Create: `platform/frontend/src/features/factors/AlphaModelWorkspace.test.tsx`
- Create: `platform/frontend/src/features/factors/factors.less`
- Modify: `platform/frontend/src/app/shell.less`（引入 `factors.less`，不在 shell 里堆样式）

**Interfaces:**
- Consumes: `GET /api/research/workspace` → `data.alpha_model`，类型
  `AlphaModelReadinessProjection`（已在 `features/screen/screenProjection.ts` 第 169–184 行定义：
  `status: 'unavailable' | 'ready'`，unavailable 分支带 `blocked_reasons[]`，
  ready 分支带 `model{model_version_id, code_version, environment_id, investment_view_id,
  investment_view_hash}` 与 `factors[]`）
- Produces: 按 `7:5` 结构组织的 Alpha 工作区；不新增任何客户端计算

- [ ] **Step 1: 读 Figma `7:5` 的精确结构，再读已有面板**

```bash
cd /Users/casiezhou/personal/Quantamental
platform/.venv/bin/python - <<'PY'
import json
frames = json.load(open('docs/assets/prototype/figma-node-summary.json'))['frames']
def walk(node, depth=0):
    text = node.get('text')
    print('  ' * depth + f"{node.get('name')} [{node.get('type')}] "
          f"{node.get('w')}x{node.get('h')} layout={node.get('layout')} gap={node.get('gap')}"
          + (f" {text!r}" if text else ""))
    for child in node.get('children') or ():
        walk(child, depth + 1)
walk(frames['7:5']['summary'])
PY
grep -n '<rect x=' docs/assets/prototype/factors-alpha-model.svg | head -40
```

```bash
cd platform/frontend/src
sed -n 1,115p features/screen/AlphaModelReadinessPanel.tsx
sed -n 160,185p features/screen/screenProjection.ts
```

`7:5` 的实测网格（本 plan §Figma 实测布局 已抄录）：`metrics-row` 1144 × 114 四卡 gap 16；
`layout-columns` 1144 × 978 = left 723 + gap 20 + right 399。

- [ ] **Step 2: 写红测 —— Figma 示例值绝不进入运行时**

```tsx
// platform/frontend/src/features/factors/AlphaModelWorkspace.test.tsx
/**
 * The Alpha workspace follows Figma node 7:5's structure and none of its data.
 *
 * That frame is drawn with DESIGN FIXTURE values: an ALPHA-V0.8 model, four
 * weights of 35/30/25/10, review ids RVW-041 through RVW-029 and a 0.42
 * correlation warning.  None of it exists in the platform.  Rendering any of it
 * would turn a design mock into an apparent model binding — the single most
 * damaging kind of leak on this page, because a weight table reads as authority.
 *
 * The frame also draws its own empty state: all twelve candidate-snapshot rows
 * are em dashes with "无合格 PIT 截面，不能生成 Snapshot".  So the honest runtime
 * and the design agree here, and the structure can be verified without data.
 */
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { AlphaModelReadinessProjection } from '../screen/screenProjection'
import { AlphaModelWorkspace } from './AlphaModelWorkspace'

const unavailable: AlphaModelReadinessProjection = {
  status: 'unavailable',
  requested_scope: 'research_backtest',
  data_mode: 'current_research',
  deployment_stage: 'research',
  checked_at: '2026-08-16T02:00:00Z',
  blocked_reasons: [{
    code: 'no_approved_factor_version',
    reason: '没有通过科学门并绑定 research_backtest 审批的 FactorVersion。',
    affected_binding: 'alpha_model.factors',
    evidence_ids: [],
  }],
}

describe('AlphaModelWorkspace', () => {
  afterEach(cleanup)

  it('renders the four KPI regions from node 7:5 even when unavailable', () => {
    render(<AlphaModelWorkspace projection={unavailable} />)
    expect(screen.getByRole('region', { name: '当前研究模型' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '激活绑定因子数' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '真实合格 Snapshot 数' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '生产运行主动影响' })).toBeInTheDocument()
  })

  it('leaks none of the frame\'s design fixture values', () => {
    render(<AlphaModelWorkspace projection={unavailable} />)
    for (const fixture of ['ALPHA-V0.8', 'RVW-041', 'RVW-038', 'RVW-035', 'RVW-029', '35%', '0.42']) {
      expect(screen.queryByText(fixture)).not.toBeInTheDocument()
    }
  })

  it('shows an unbound KPI as an em dash, never as zero', () => {
    render(<AlphaModelWorkspace projection={unavailable} />)
    const model = screen.getByRole('region', { name: '当前研究模型' })
    expect(model).toHaveTextContent('—')
    // 0% active influence is a real claim about a running model; there is none.
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
  })

  it('renders every server blocker with its code and affected binding', () => {
    render(<AlphaModelWorkspace projection={unavailable} />)
    expect(screen.getByText('no_approved_factor_version')).toBeInTheDocument()
    expect(screen.getByText('alpha_model.factors')).toBeInTheDocument()
    expect(screen.getByText(/没有通过科学门/)).toBeInTheDocument()
  })

  it('renders the weight table headers with no rows rather than sample weights', () => {
    render(<AlphaModelWorkspace projection={unavailable} />)
    // Structure without data: the columns exist so the shape is verifiable, and
    // the absence of rows is the truth about the current binding.
    expect(screen.getByRole('columnheader', { name: '因子' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '权重' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Review ID' })).toBeInTheDocument()
    expect(screen.getByText(/没有已绑定权重的获批因子/)).toBeInTheDocument()
  })

  it('renders the fixed five-段 INPUT/PROCESS/OUTPUT/ACTION/GATE strip', () => {
    render(<AlphaModelWorkspace projection={unavailable} />)
    for (const stage of ['INPUT', 'PROCESS', 'OUTPUT', 'ACTION', 'GATE']) {
      expect(screen.getByRole('region', { name: stage })).toBeInTheDocument()
    }
  })

  it('delegates the ready branch to the existing readiness panel', () => {
    const ready: AlphaModelReadinessProjection = {
      status: 'ready',
      requested_scope: 'research_backtest',
      data_mode: 'current_research',
      deployment_stage: 'research',
      checked_at: '2026-08-16T02:00:00Z',
      model: {
        model_version_id: 'model-version:alpha:v0',
        code_version: 'c'.repeat(40),
        environment_id: 'env:research',
        investment_view_id: 'investment-view:600519:v1',
        investment_view_hash: 'd'.repeat(64),
      },
      factors: [],
    }
    render(<AlphaModelWorkspace projection={ready} />)
    // Reuse, not a second implementation: AlphaModelReadinessPanel already
    // renders exact approval bindings and carries its own tests.
    expect(screen.getByTestId('approved-alpha-model')).toBeInTheDocument()
    expect(screen.getByText('model-version:alpha:v0')).toBeInTheDocument()
  })
})
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform && npm --prefix frontend test -- --run src/features/factors/AlphaModelWorkspace.test.tsx`
Expected: FAIL —— 模块不存在。

- [ ] **Step 4: 实现 —— 结构来自 `7:5`，数据来自服务端，ready 分支委托已有面板**

Less 用比例声明列，让 280 px 侧栏造成的 32 px 差异被吸收（与 `deskGrid` 同一手法）：

```less
// features/factors/factors.less
// Figma node 7:5: workspace 1144 wide, columns 723 / 399 with a 20 gap.
// Runtime keeps the SPEC-045 280 px sider, so the content column is 1160 rather
// than 1192; ratio tracks absorb the 32 px instead of overflowing the page.
.alphaWorkspaceGrid {
  display: grid;
  align-items: start;
  gap: 20px;
  grid-template-columns: minmax(0, 723fr) minmax(0, 399fr);
}

.alphaKpiRow {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}
```

`shell.less` 已有的 1280 / 820 / 420 断点里追加：1280 → `alphaWorkspaceGrid` 单列；
820 → `alphaKpiRow` 两列；420 → `alphaKpiRow` 单列。**不新增断点。**

- [ ] **Step 5: 接进 Factor 工作区并转绿**

`factorSections.tsx` 的 `AlphaModelSection` 用 `getResearchWorkspace()` 取 `alpha_model`，
外层仍用 `DeskSection` 承载六态，内层是 `AlphaModelWorkspace`。

```bash
cd platform
npm --prefix frontend test -- --run src/features/factors
npm --prefix frontend test -- --run src/features/screen   # 已有面板不得回归
```

- [ ] **Step 6: 1440 逐区对照 node `7:5`**

```bash
cd platform
.venv/bin/python - <<'PY'
from playwright.sync_api import sync_playwright
import json
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    c = b.new_context(viewport={"width": 1440, "height": 1200})
    page = c.new_page()
    page.goto("http://127.0.0.1:5173/factors?tab=alpha-model", wait_until="networkidle")
    page.wait_for_timeout(1500)
    boxes = page.evaluate("""() => {
        const pick = (sel) => {
            const node = document.querySelector(sel)
            if (!node) return [sel, null]
            const box = node.getBoundingClientRect()
            return [sel, {x: Math.round(box.x), y: Math.round(box.y),
                          w: Math.round(box.width), h: Math.round(box.height)}]
        }
        return ['.alphaWorkspaceGrid', '.alphaKpiRow', '.alphaWeightCard',
                '.alphaSnapshotCard', '.alphaFlowStrip', '.alphaReadinessPanel'].map(pick)
    }""")
    print(json.dumps(boxes, ensure_ascii=False, indent=1))
    page.screenshot(path="/tmp/pui04-alpha-1440.png", full_page=True)
    c.close(); b.close()
PY
```

对照 `7:5` 实测值并把差异逐条记录：

```text
Figma            → 期望运行时（1160 内容宽，比例换算）
metrics-row 1144 → 1112（四卡 273 → 265）
left-col     723 → 703
right-col    399 → 389
gap           20 → 20（不缩放）
```

差异必须落在「侧栏 280 vs 248 的已批准差异」范围内。**出现结构性差异（分栏数、卡片顺序、
列数不同）必须修，不得只写「风格相近」。**

- [ ] **Step 7: 四视口验收**

Run: `cd platform && .venv/bin/python scripts/verify_factor_system_browser.py`

必须：`factors-alpha-model` 四个视口全部无溢出、无 DESIGN FIXTURE 泄漏、无控制台 error/warning。

- [ ] **Step 8: 提交**

```bash
cd platform
npm --prefix frontend test -- --run && npm --prefix frontend run lint && npm --prefix frontend run build
cd .. && git add platform/frontend/src/features/factors/ platform/frontend/src/app/shell.less
git commit -m "feat: build the Alpha Model workspace against Figma node 7:5

The tab rendered one blocked notice while AlphaModelReadinessPanel — which
already handles both the ready and unavailable branches and carries its own
tests — sat unused in features/screen.  This wires it up and adds the structure
the frame specifies around it: four KPI cards, the weight table, the candidate
snapshot table, the readiness checklist and the fixed five-stage strip.

None of the frame's numbers cross over.  ALPHA-V0.8, the 35/30/25/10 weights and
review ids RVW-041 to RVW-029 are design fixtures, and a weight table is exactly
the surface where invented data would read as an authoritative model binding.
The frame draws its own empty snapshot table, so structure and honesty agree
here: the columns exist, the rows say why there are none.

An unbound KPI shows an em dash rather than 0%, because 0% active influence is a
real claim about a model that is running, and none is.

Columns are declared as 723fr/399fr ratios so the 32 px the 280 px sider costs
against Figma's 248 is absorbed by the tracks, the same way the desk grid does
it."
```

---

### Task 5: Experiments —— 保留失败实验，补齐钻取与真实分页

`ExperimentsPanel` 是当前 `/factors` 唯一真正接线的面板，审计记为
`runtime_partial：真实失败 Experiment`。它已经做对了三件必须保留的事：

1. 失败 Experiment 以 `失败保留` 标签保留可见；
2. `FactorStudyNotReady` 归纳为「PIT 输入资格未通过」，同时用 `<details>` 保留**完整不可变原文**；
3. 缺失统计量显示 `—`，`quantiles`/`decay` 未绑定时明确说明「不会从 artifact hash 生成图表」。

本 Task 只补三处：分区化（Task 2 已备好）、钻取到 `GET /api/experiments/runs/{run_id}`、
以及和 System 表一致的真实分页。**不得为了页面整齐折叠失败项。**

**Files:**
- Modify: `platform/frontend/src/features/factors/factorSections.tsx`
- Create: `platform/frontend/src/features/factors/ExperimentDrawer.tsx`
- Modify: `platform/frontend/src/api/client.ts`（新增 `getExperimentRun(runId)`）
- Modify: `platform/frontend/src/pages/FactorWorkspace.test.tsx`
- Create: `platform/frontend/src/features/factors/experimentPagination.test.tsx`

**Interfaces:**
- Consumes: `GET /api/experiments/runs`、`GET /api/experiments/runs/{run_id}`、
  已有 `ExperimentRunEntry`（`run_id` / `status` / `spec{spec_id, research_question, run_context,
  feature_bindings, parameters?}` / `metrics[]` / `failure{stage, error_type, message,
  occurred_at, retryable} | null`）
- Produces: 分页的实验列表 + 单个 Run 的证据抽屉；**不新增写接口**

- [ ] **Step 1: 确认真实分页模式（照抄 System，不自创）**

```bash
cd platform/frontend/src
sed -n 50,76p pages/SystemScreen.tsx          # useClientPage
sed -n 113,149p pages/SystemScreen.pagination.test.tsx   # 分页测试模式
```

`useClientPage` 的关键性质：`Table` 只收当前页行，但 `pagination.total` 是**全量长度**。
这让 20 行以上的失败实验不会被静默截断。把它从 `SystemScreen.tsx` 提到共享位置
（如 `components/useClientPage.ts`），两处共用，**不要复制第二份**。

- [ ] **Step 2: 写红测 —— 失败实验跨页不丢，且 total 反映真实数量**

```tsx
// platform/frontend/src/features/factors/experimentPagination.test.tsx
/**
 * Failed experiments survive pagination.
 *
 * The gate this guards is quiet truncation: if the list rendered only the first
 * twenty runs and reported twenty as the total, a failed run on page three would
 * vanish from the record.  Failed runs are the most important rows on this page —
 * they are the evidence that the qualification gate did not pass — so the total
 * must be the real count and every page must be reachable.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ExperimentsSection } from './factorSections'

const context = {
  as_of: '2026-08-16T02:00:00Z',
  system_as_of: '2026-08-16T02:00:10Z',
  data_mode: 'current_research',
  deployment_stage: 'research',
  trust_state: 'normalized_current',
  dataset_version_ids: [],
  model_version_ids: [],
  run_id: null,
  coverage: {},
  warnings: [],
}

function failedRun(index: number) {
  return {
    run_id: `experiment-run:quality:failed-${String(index).padStart(3, '0')}`,
    status: 'failed',
    spec: {
      spec_id: 'experiment-spec:quality:v1',
      research_question: 'Does Quality V0 pass the frozen PIT input gate?',
      run_context: { data_mode: 'strict_historical', deployment_stage: 'research' },
      feature_bindings: [
        { feature_id: 'factor:quality:v0', version: 'v0', definition_hash: 'a'.repeat(64) },
      ],
    },
    metrics: [],
    failure: {
      stage: 'data_preparation',
      error_type: 'FactorStudyNotReady',
      message: 'historical_universe is unavailable | forward_return_label is unavailable',
      occurred_at: '2026-08-16T01:00:00Z',
      retryable: false,
    },
  }
}

function renderSection(runs: unknown[]) {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true, status: 200, json: async () => ({ data: runs, context }),
  }) as Response))
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><ExperimentsSection /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ExperimentsSection pagination', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('reports the real total rather than the page size', async () => {
    renderSection(Array.from({ length: 45 }, (_, index) => failedRun(index)))
    expect(await screen.findByText(/45/)).toBeInTheDocument()
  })

  it('keeps every failed run reachable instead of truncating the list', async () => {
    renderSection(Array.from({ length: 45 }, (_, index) => failedRun(index)))
    await screen.findByText('experiment-run:quality:failed-000')
    expect(screen.queryByText('experiment-run:quality:failed-020')).not.toBeInTheDocument()
    fireEvent.click(screen.getByTitle('2'))
    await waitFor(() =>
      expect(screen.getByText('experiment-run:quality:failed-020')).toBeInTheDocument())
  })

  it('never collapses a failed run into a success or a silent skip', async () => {
    renderSection([failedRun(0)])
    expect(await screen.findByText('失败保留')).toBeInTheDocument()
    expect(screen.getByText('PIT 输入资格未通过')).toBeInTheDocument()
    expect(screen.getByText('2 项阻断 · data_preparation')).toBeInTheDocument()
  })

  it('opens the full immutable failure text rather than only the summary', async () => {
    renderSection([failedRun(0)])
    const summary = await screen.findByText('查看完整失败证据')
    // Summarised, not truncated: the original message must still be in the DOM.
    expect(screen.getByText(/historical_universe is unavailable/)).not.toBeVisible()
    fireEvent.click(summary)
    expect(screen.getByText(/historical_universe is unavailable/)).toBeVisible()
  })
})
```

- [ ] **Step 3: 运行确认红测 → 实现 → 转绿**

```bash
cd platform
npm --prefix frontend test -- --run src/features/factors/experimentPagination.test.tsx
```

Expected FAIL（`ExperimentsSection` 未导出或未分页）→ 实现 → PASS。
**每个断言先红后绿，不要一次实现四条。**

- [ ] **Step 4: 加钻取抽屉（Evidence / run / dataset / definition 往返）**

PUI-04 的任务清单要求「Evidence、run、dataset、definition 和 review 可钻取」。
复用 `SystemEvidenceScreen.tsx` 里已有的 `EvidenceDrawer` 模式（第 58–91 行：
`Drawer` + `useQuery` + 六态 + `redistribution_allowed` 提示）。

红测至少覆盖：

```tsx
// platform/frontend/src/features/factors/ExperimentDrawer.test.tsx
function renderDrawer(response: () => Response) {
  vi.stubGlobal('fetch', vi.fn(async () => response()))
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <ExperimentDrawer
          onClose={() => undefined}
          runId="experiment-run:quality:failed-000"
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

it('drills from a run into its spec, dataset versions and definition hashes', async () => {
  // This is the chain that makes a number reproducible: spec id, run context and
  // the feature binding's definition hash.  The drawer shows what the server
  // returned and nothing else — a synthesised dataset id would break lineage.
  const requests: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: unknown) => {
    requests.push(String(input))
    return {
      ok: true, status: 200,
      json: async () => ({ data: failedRun(0), context }),
    } as Response
  }))
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <ExperimentDrawer onClose={() => undefined} runId="experiment-run:quality:failed-000" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(await screen.findByText('experiment-spec:quality:v1')).toBeInTheDocument()
  expect(screen.getByText('a'.repeat(64))).toBeInTheDocument()
  expect(screen.getByText('strict_historical')).toBeInTheDocument()
  expect(requests.some((url) =>
    url.includes('/api/experiments/runs/experiment-run:quality:failed-000'))).toBe(true)
})

it('shows an explicit reason when the run detail request fails', async () => {
  // A drawer that opens empty reads as "no evidence", not "could not fetch".
  renderDrawer(() => ({
    ok: false, status: 503,
    json: async () => ({ detail: 'ASP_DATABASE_URL is not configured for experiment persistence' }),
  }) as Response)
  expect(await screen.findByText(/ASP_DATABASE_URL/)).toBeInTheDocument()
  expect(screen.queryByText('暂无记录')).not.toBeInTheDocument()
})
```

- [ ] **Step 5: 四视口验收**

Run: `cd platform && .venv/bin/python scripts/verify_factor_system_browser.py`

320 视口特别检查：失败证据的 `<details>` 展开后长文本必须在容器内换行
（`.factorFailureDetails p` 已有 `overflow-wrap: anywhere`，确认仍生效），不产生页面级溢出。

- [ ] **Step 6: 记录设计假设并提交**

Experiments **无独立 Frame**，`design_status` 保持 `missing`。假设逐条写进 Evidence：
沿用 `9:661` 的 KPI + 主表 + 五段结构；KPI 选为 Run 总数 / 失败数 / 已绑定 OOS 样本数 /
多重检验 family 数；失败详情用 `<details>` 折叠但不截断。

```bash
cd platform
npm --prefix frontend test -- --run && npm --prefix frontend run lint && npm --prefix frontend run build
cd .. && git add platform/frontend/src/features/factors/ platform/frontend/src/api/client.ts \
  platform/frontend/src/components/ platform/frontend/src/pages/
git commit -m "feat: paginate experiments and let a run drill into its own evidence

The list rendered every run at once.  With 45 failed runs a page-three failure
would have been invisible, and a failed run is the most load-bearing row here:
it is the record that the qualification gate did not pass.  Pagination now
reports the real total and keeps every page reachable, reusing the same
useClientPage helper the System tables use rather than a second implementation.

The failure summary stays a summary and not a truncation — the full immutable
message remains in the DOM behind a details element, because a shortened blocker
list would understate how much is missing.

Drilling into a run reaches its spec, its dataset versions and its feature
definition hashes, which is the chain that makes the number reproducible.  A
failed detail request says so instead of opening an empty drawer that reads as
'no evidence'."
```

---

### Task 6: Production —— 接 `GET /api/factors/reviews`，替换恒为空的硬写数组

`mapExperimentEnvelope`（`FactorWorkspace.tsx` 第 179–191 行）把 `productionVersions`
硬写成 `[]`，所以 Production 面板**永远**显示「无获批生产因子」，无论账本里有什么。
这是假的诚实：它看起来在报告空态，实际上根本没查。

`GET /api/factors/reviews` 已存在并返回 `FactorPromotionReview[]`。领域约束已核实：
`FactorPromotionReview.__post_init__` 强制 `factor_lifecycle_status is CANDIDATE`，
且携带 `approval: PromotionApproval`（`scope` ∈ `research_backtest / shadow / paper /
limited_live`，`decision` ∈ `approved / rejected / request_changes`）。

**这意味着一条 Review 存在 ≠ 该因子已进入 production。** Production 页必须按
scope 与 decision 分别展示，不得把 `research_backtest` 的批准显示成生产就绪。

**Files:**
- Modify: `platform/frontend/src/features/factors/factorSections.tsx`
- Modify: `platform/frontend/src/api/client.ts`（新增 `getFactorReviews()` 与类型）
- Create: `platform/frontend/src/features/factors/ProductionSection.test.tsx`

**Interfaces:**
- Consumes: `GET /api/factors/reviews`
- Produces: 按 `approval.scope` 分组的 Review 列表；scope 之间**不互相隐含**

- [ ] **Step 1: 确认审批域的真实字段与约束**

```bash
cd platform
grep -n "class ApprovalScope" -A10 src/a_share_platform/domain/factor_lifecycle.py
grep -n "class ApprovalDecision" -A6 src/a_share_platform/domain/factor_lifecycle.py
grep -n "class PromotionApproval" -A15 src/a_share_platform/domain/factor_lifecycle.py
grep -n "class FactorPromotionReview" -A28 src/a_share_platform/domain/factor_reviews.py
```

- [ ] **Step 2: 写红测 —— scope 不互相隐含**

```tsx
// platform/frontend/src/features/factors/ProductionSection.test.tsx
/**
 * A research approval is not a production approval.
 *
 * Review scopes do not imply one another: research_backtest, shadow, paper and
 * limited_live are separate authorisations, and a FactorVersion cleared for
 * research must not appear on this page as production-ready.  The page also
 * previously hard-coded productionVersions to [], so it always showed an empty
 * state without ever querying the ledger — a false honesty that would keep
 * showing "none" after a real approval landed.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ProductionSection } from './factorSections'

const context = {
  as_of: '2026-08-16T02:00:00Z',
  system_as_of: '2026-08-16T02:00:10Z',
  data_mode: 'current_research',
  deployment_stage: 'research',
  trust_state: 'normalized_current',
  dataset_version_ids: [],
  model_version_ids: [],
  run_id: null,
  coverage: {},
  warnings: [],
}

function review(scope: string, decision = 'approved') {
  return {
    review_id: `factor-review:quality:${scope}`,
    factor_version_id: 'factor-version:quality:v0',
    factor_version_hash: 'a'.repeat(64),
    factor_lifecycle_status: 'candidate',
    validation_report_id: 'validation-report:quality:v0',
    validation_report_hash: 'b'.repeat(64),
    scientific_gate_passed: true,
    approval: {
      approval_id: `approval:quality:${scope}`,
      factor_version_id: 'factor-version:quality:v0',
      validation_report_id: 'validation-report:quality:v0',
      validation_report_hash: 'b'.repeat(64),
      scope,
      decision,
      actor_id: 'reviewer:1',
      actor_role: 'reviewer',
      decided_at: '2026-08-16T01:00:00Z',
      reason: 'frozen OOS window met the pre-registered threshold',
      evidence_hashes: ['c'.repeat(64)],
    },
  }
}

function renderSection(reviews: unknown[]) {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true, status: 200, json: async () => ({ data: reviews, context }),
  }) as Response))
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><ProductionSection /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ProductionSection', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('actually queries the review ledger instead of assuming an empty list', async () => {
    const requests: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: unknown) => {
      requests.push(String(input))
      return { ok: true, status: 200, json: async () => ({ data: [], context }) } as Response
    }))
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><ProductionSection /></MemoryRouter>
      </QueryClientProvider>,
    )
    await screen.findByText(/暂无记录|没有/)
    expect(requests.some((url) => url.includes('/api/factors/reviews'))).toBe(true)
  })

  it('does not present a research_backtest approval as production ready', async () => {
    renderSection([review('research_backtest')])
    expect(await screen.findByText('research_backtest')).toBeInTheDocument()
    expect(screen.queryByText(/已进入生产/)).not.toBeInTheDocument()
    expect(screen.queryByText(/paper/)).not.toBeInTheDocument()
    expect(screen.queryByText(/limited_live/)).not.toBeInTheDocument()
  })

  it('keeps a rejected review visible rather than filtering it out', async () => {
    // Removing rejections would make the ledger look like a list of successes.
    renderSection([review('shadow', 'rejected')])
    expect(await screen.findByText('rejected')).toBeInTheDocument()
    expect(screen.getByText('factor-review:quality:shadow')).toBeInTheDocument()
  })

  it('shows the candidate lifecycle status alongside the approval', async () => {
    renderSection([review('research_backtest')])
    expect(await screen.findByText('candidate')).toBeInTheDocument()
  })

  it('reports an unreachable ledger as unavailable, not as no approvals', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false, status: 503,
      json: async () => ({ detail: 'ASP_DATABASE_URL is not configured for factor review persistence' }),
    }) as Response))
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><ProductionSection /></MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByText(/ASP_DATABASE_URL/)).toBeInTheDocument()
    expect(screen.queryByText('暂无记录')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 3: 运行确认红测 → 实现 → 转绿**

Run: `cd platform && npm --prefix frontend test -- --run src/features/factors/ProductionSection.test.tsx`

实现时把 `mapExperimentEnvelope` 里 `productionVersions: []` 与 `correlationPairs: []`
的硬写删掉 —— `FactorWorkspaceSnapshot` 不该同时承载六个 tab 的数据。

- [ ] **Step 4: 四视口验收并提交**

```bash
cd platform
.venv/bin/python scripts/verify_factor_system_browser.py
npm --prefix frontend test -- --run && npm --prefix frontend run lint && npm --prefix frontend run build
cd .. && git add platform/frontend/src/features/factors/ platform/frontend/src/api/client.ts
git commit -m "feat: read the real approval ledger on the Production tab

productionVersions was hard-coded to an empty array, so the tab always rendered
'no approved factor' without ever asking the server.  That is false honesty: the
page would keep saying none after a real approval landed, and the operator would
have no way to tell the difference between an empty ledger and an unqueried one.

Scopes are now shown separately because they do not imply one another.  A
FactorVersion cleared for research_backtest is not production-ready, and
rendering it as such is how an approval boundary gets crossed by accident.
Rejected reviews stay visible; filtering them would turn an audit ledger into a
list of successes.

An unreachable ledger reports the connection reason rather than an empty state."
```

---

### Task 7: Timing Lab 与 Correlation Monitor —— 保持诚实的阶段 blocker

这两页的能力分别属 **P7** 与 **P9**，本 plan **不实现它们**。但当前实现是
「硬写 `null` / `[]` → 面板显示空态」，读起来像「能力已就绪但暂无数据」——
这是错的：不是没数据，是没能力。

`docs/18` 对两页的 Gate 写得很明确：

- Timing Lab：「主动模型必须真实存在；未晋级影响 0%」
- Correlation Monitor：「不自动修改因子权重或审批」

`DeskSection` 的 `unavailable` 分支强制要求 blocker（`domain/desk.py` 第 114–117 行：
`section is unavailable and must declare a blocker`）。本 Task 就是让这两页走这条路径。

**Files:**
- Modify: `platform/frontend/src/features/factors/factorSections.tsx`
- Modify: `platform/frontend/src/features/factors/factorSections.test.tsx`

**Interfaces:**
- Consumes: 无新端点。blocker 文案与 code 由**前端常量**提供 —— 这是允许的例外，
  因为它描述的是「本仓库尚未实现某阶段」这一**代码事实**，不是数据事实。
  与之相对，任何**数据状态**（有几条记录、覆盖多少）都必须来自服务端。

- [ ] **Step 1: 确认 blocker 的现有命名惯例**

```bash
cd platform
grep -rn "NOT_IMPLEMENTED" src/a_share_platform/application/desk_projection.py
grep -rn "P6_PORTFOLIO_TRACKING_NOT_IMPLEMENTED\|P8_EVENT_FEED_NOT_IMPLEMENTED" src/ frontend/src/
```

照抄 `P6_PORTFOLIO_TRACKING_NOT_IMPLEMENTED` / `P8_EVENT_FEED_NOT_IMPLEMENTED` 的形状：
`P{n}_{DOMAIN}_NOT_IMPLEMENTED` + 中文 reason + `affected_binding`。

- [ ] **Step 2: 写红测 —— 阶段 blocker 而非空态**

```tsx
// 追加到 factorSections.test.tsx
describe('stage-blocked factor sections', () => {
  afterEach(cleanup)

  it('declares Timing Lab unavailable at P7 rather than empty', () => {
    render(<TimingLabSection />)
    expect(screen.getByRole('region', { name: 'Timing Lab' })).toBeInTheDocument()
    expect(screen.getByText('P7_ACTIVE_TIMING_NOT_IMPLEMENTED')).toBeInTheDocument()
    // "No record yet" would imply the capability exists and is merely idle.
    expect(screen.queryByText('暂无记录')).not.toBeInTheDocument()
  })

  it('does not present the passive baseline as an active timing forecast', () => {
    render(<TimingLabSection />)
    expect(screen.getByText(/被动 baseline 不冒充主动预测/)).toBeInTheDocument()
    expect(screen.queryByText(/目标仓位|预测方向/)).not.toBeInTheDocument()
  })

  it('states that an unpromoted timing model contributes zero portfolio influence', () => {
    render(<TimingLabSection />)
    // docs/18: 主动模型必须真实存在；未晋级影响 0%.  That is a claim about the
    // absence of influence, which is safe; a claim about a forecast is not.
    expect(screen.getByText(/未晋级模型对组合影响为 0/)).toBeInTheDocument()
  })

  it('declares Correlation Monitor unavailable at P9 and never edits weights', () => {
    render(<CorrelationMonitorSection />)
    expect(screen.getByText('P9_CORRELATION_MONITOR_NOT_IMPLEMENTED')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /调整权重|重新审批/ })).not.toBeInTheDocument()
  })

  it('renders no correlation cell at all rather than a zero or a dash grid', () => {
    render(<CorrelationMonitorSection />)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByText('0.00')).not.toBeInTheDocument()
  })
})
```

注意第五条：Correlation Monitor **不渲染空矩阵**。一个全是 `—` 的相关性矩阵会让人以为
「因子对已确定、只是数值待算」，而真实情况是连获批因子都没有。

- [ ] **Step 3: 运行确认红测 → 实现 → 转绿**

Run: `cd platform && npm --prefix frontend test -- --run src/features/factors/factorSections.test.tsx`

实现时删除 `TimingBaselineView` 与 `CorrelationPairView` 这两个**从未被填充过**的
前端接口（`FactorWorkspace.tsx` 第 64–76 行），以及 `mapExperimentEnvelope` 里对应的硬写。

- [ ] **Step 4: 四视口验收并提交**

```bash
cd platform
.venv/bin/python scripts/verify_factor_system_browser.py
npm --prefix frontend test -- --run && npm --prefix frontend run lint
cd .. && git add platform/frontend/src/features/factors/
git commit -m "fix: state the stage blockers on Timing Lab and Correlation Monitor

Both tabs hard-coded their data to null and an empty array, so both rendered an
empty state.  That reads as 'the capability works and holds no record', when the
truth is that active timing is P7 and correlation monitoring is P9 — neither is
built.  Those are different facts and the operator needs the second one.

Correlation Monitor renders no matrix at all rather than a grid of dashes.  A
dash grid would suggest the factor pairs are settled and only the numbers are
pending, when in fact there is not one approved factor version to correlate.

Timing Lab says an unpromoted model contributes zero portfolio influence, which
is a safe claim about absence.  It does not show a target weight or a direction,
because the passive volatility baseline is not an active forecast and must never
be dressed as one."
```

---

### Task 8: System Quality 与 Lineage —— 对 Figma node `9:661` 做 1440 结构对照

`9:661` `13-data-quality-lineage` 是审计 §5 第 25、26 行**共同指向**的 Frame，
所以两页共用一份高保真真源，也是本 plan 唯一可达 parity 的 System 页。

当前 `SystemScreen.tsx` 的 `QualityTable`（6 列）与 `LineageTable`（3 列）是裸表：
没有 KPI 行、没有右栏规则说明、没有底部五段。`9:661` 三者都有，且右栏四条规则
（阻断传播 / 警告传播 / 双时间血缘 / 空期守卫）**正是这两页的产品价值所在** ——
它解释了「一个 warning 会传播到 current 页面」和「一个 blocked 会禁止 strict 下游」。

`9:661` 的表是 8 列（Check | Dataset | 规则 | 结果 | 影响 | 报告版本 | Run | 时间），
当前 `QualityReportEntry` 提供 `quality_report_id / dataset_version_id / job_id / status /
checks_passed / checks_failed / issue_counts / warnings / created_at`。
**「规则」与「影响」两列没有对应字段** —— 这是必须记录的设计与 API 差距，
不得靠前端推断「影响」（那等于在浏览器里决定阻断传播）。

**Files:**
- Modify: `platform/frontend/src/pages/SystemScreen.tsx`
- Create: `platform/frontend/src/features/system/SystemQualityWorkspace.tsx`
- Create: `platform/frontend/src/features/system/SystemLineageWorkspace.tsx`
- Create: `platform/frontend/src/features/system/system.less`
- Create: `platform/frontend/src/features/system/SystemQualityWorkspace.test.tsx`
- Create: `platform/frontend/src/features/system/SystemLineageWorkspace.test.tsx`
- Modify: `platform/frontend/src/app/shell.less`

**Interfaces:**
- Consumes: `GET /api/system/quality` → `QualityReportEntry[]`；
  `GET /api/system/lineage` → `LineageCatalogEntry[]`（`upstream_id` / `downstream_id` / `relation`）
- Produces: KPI 行 + 主表 + 右栏规则 + 五段的两页；**保留 `useClientPage` 真实分页**

- [ ] **Step 1: 读 `9:661` 的精确坐标与文本**

```bash
cd /Users/casiezhou/personal/Quantamental
platform/.venv/bin/python - <<'PY'
import json
frames = json.load(open('docs/assets/prototype/figma-node-summary.json'))['frames']
def walk(node, depth=0):
    text = node.get('text')
    print(' ' * depth + f"{node.get('name')} [{node.get('type')}] "
          f"{node.get('w')}x{node.get('h')}" + (f" {text!r}" if text else ""))
    for child in node.get('children') or ():
        walk(child, depth + 1)
walk(frames['9:661']['summary'])
PY
platform/.venv/bin/python - <<'PY'
import re
raw = open('docs/assets/prototype/13-data-quality-lineage.svg', encoding='utf-8').read()
for match in re.finditer(r'<path id="(Vector[_0-9]*)" d="M([\d.]+) ([\d.]+)([^"]*)"', raw):
    name, x, y, rest = match.groups()
    numbers = [float(value) for value in re.findall(r'-?\d+\.?\d*', rest)]
    if not numbers:
        continue
    xs = [float(x)] + numbers[0::2]
    ys = [float(y)] + numbers[1::2]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    if width > 150 and height > 30:
        print(f"{name}: x={min(xs):.0f} y={min(ys):.0f} w={width:.0f} h={height:.0f}")
PY
```

实测结果（本 plan §Figma 实测布局 已抄录）：KPI 四张 264 × 92 at x=246/524/802/1080, y=196；
主表 x=246 w=790（标题 42 + 表头 34 + 10 行 × 39）；右栏 x=1052 w=362（规则 394 + 边界 96）；
底部五段 214 × 102 at x=246/470/694/918/1142。

- [ ] **Step 2: 写红测 —— 结构存在、阻断传播语义正确、缺失列不伪造**

```tsx
// platform/frontend/src/features/system/SystemQualityWorkspace.test.tsx
/**
 * Quality against Figma node 9:661, structure only.
 *
 * The frame's own numbers — 184 checks, 169 passed, 12 warned, 3 blocked, rows
 * Q-1300 to Q-1309 with RUN-1400 onwards — are DESIGN FIXTURE and must not
 * appear.  Its right column is the part worth keeping: four rules explaining
 * that a warning propagates to current pages while a blocked check forbids
 * strict downstream use.  Those are governance facts, not sample data, so they
 * are the one thing this page may state without a server record.
 *
 * The frame's table has 规则 and 影响 columns that QualityReportEntry has no
 * field for.  They are rendered as explicitly unavailable rather than inferred:
 * deciding in the browser whether a check blocks downstream use would move a
 * governance decision into the client.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SystemQualityWorkspace } from './SystemQualityWorkspace'

const context = {
  as_of: '2026-08-16T02:00:00Z',
  system_as_of: '2026-08-16T02:00:10Z',
  data_mode: 'current_research',
  deployment_stage: 'research',
  trust_state: 'normalized_current',
  dataset_version_ids: [],
  model_version_ids: [],
  run_id: null,
  coverage: {},
  warnings: [],
}

function report(index: number, status: 'passed' | 'warned' | 'failed') {
  return {
    quality_report_id: `quality-report:financials:${String(index).padStart(3, '0')}`,
    dataset_version_id: 'dataset:csi500-financials:v1',
    job_id: `ingestion-job:financials:${index}`,
    status,
    checks_passed: status === 'passed' ? 4 : 2,
    checks_failed: status === 'failed' ? 2 : 0,
    issue_counts: status === 'failed' ? { time_cutoff: 2 } : {},
    warnings: status === 'warned' ? ['legal empty period kept empty, not zero-filled'] : [],
    created_at: '2026-08-16T01:00:00Z',
  }
}

function renderQuality(rows: unknown[]) {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true, status: 200, json: async () => ({ data: rows, context }),
  }) as Response))
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><SystemQualityWorkspace /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SystemQualityWorkspace', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('renders the four KPI regions from node 9:661', async () => {
    renderQuality([report(0, 'passed'), report(1, 'warned'), report(2, 'failed')])
    expect(await screen.findByRole('region', { name: 'Checks' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Passed' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Warned' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Blocked' })).toBeInTheDocument()
  })

  it('counts KPI values from the served rows, not from the frame', async () => {
    renderQuality([report(0, 'passed'), report(1, 'warned'), report(2, 'failed')])
    const checks = await screen.findByRole('region', { name: 'Checks' })
    expect(checks).toHaveTextContent('3')
    for (const fixture of ['184', '169', '13 suites', '92%', 'Q-1300', 'RUN-1400', 'QR-v1']) {
      expect(screen.queryByText(fixture)).not.toBeInTheDocument()
    }
  })

  it('states the four propagation rules the frame specifies', async () => {
    renderQuality([report(0, 'passed')])
    expect(await screen.findByText('阻断传播')).toBeInTheDocument()
    expect(screen.getByText(/严重错误阻止 Factor\/View\/Backtest/)).toBeInTheDocument()
    expect(screen.getByText('警告传播')).toBeInTheDocument()
    expect(screen.getByText('双时间血缘')).toBeInTheDocument()
    expect(screen.getByText('空期守卫')).toBeInTheDocument()
    expect(screen.getByText(/有原始行但全 unmapped 不是合法空期/)).toBeInTheDocument()
  })

  it('states the trust ceiling boundary rather than implying it can be raised', async () => {
    renderQuality([report(0, 'passed')])
    expect(await screen.findByText(/Current source 的 trust ceiling 不能提升/)).toBeInTheDocument()
    expect(screen.getByText(/关键 evidence 断链即 fail closed/)).toBeInTheDocument()
  })

  it('marks the 规则 and 影响 columns unavailable instead of inferring them', async () => {
    renderQuality([report(2, 'failed')])
    const row = (await screen.findByText('quality-report:financials:002')).closest('tr')
    // Two of the frame's eight columns have no field in QualityReportEntry.
    // Inferring "Strict downstream" from a failed status would decide
    // propagation in the browser, which belongs to the server.
    expect(row).toHaveTextContent('—')
    expect(screen.getByText(/规则与影响列尚无服务端字段/)).toBeInTheDocument()
  })

  it('keeps the existing 20-row client pagination and the real total', async () => {
    renderQuality(Array.from({ length: 45 }, (_, index) => report(index, 'warned')))
    expect(await screen.findByTitle('3')).toBeInTheDocument()   // 45 rows → 3 pages
  })

  it('renders the fixed five-段 strip', async () => {
    renderQuality([report(0, 'passed')])
    for (const stage of ['INPUT', 'PROCESS', 'OUTPUT', 'ACTION', 'GATE']) {
      expect(await screen.findByRole('region', { name: stage })).toBeInTheDocument()
    }
  })
})
```

Lineage 的红测同形，另加两条：

```tsx
// platform/frontend/src/features/system/SystemLineageWorkspace.test.tsx
function edge(upstream: string, downstream: string, relation = 'derived_from') {
  return { upstream_id: upstream, downstream_id: downstream, relation }
}

function renderLineage(rows: unknown[]) {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true, status: 200, json: async () => ({ data: rows, context }),
  }) as Response))
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><SystemLineageWorkspace /></MemoryRouter>
    </QueryClientProvider>,
  )
}

it('lets a lineage edge drill into its upstream dataset', async () => {
  // docs/18: 从页面数字追到公式、模型、run、dataset 和 raw evidence.  The link is
  // built from the served id prefix, not from a client-side guess about what the
  // id refers to.
  renderLineage([edge('dataset:csi500-financials:v1', 'quality-report:financials:001')])
  const link = await screen.findByRole('link', { name: 'dataset:csi500-financials:v1' })
  expect(link.getAttribute('href')).toContain('tab=catalog')
})

it('does not link an id whose kind it cannot resolve', async () => {
  renderLineage([edge('unknown:opaque-id', 'quality-report:financials:001')])
  expect(await screen.findByText('unknown:opaque-id')).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'unknown:opaque-id' })).not.toBeInTheDocument()
})

it('reports a broken evidence chain as fail-closed rather than as a gap', async () => {
  // docs/18 Gate: 关键证据断链即 fail closed.  A missing upstream is not a blank
  // cell; it invalidates the downstream claim and must say so.
  renderLineage([edge('', 'quality-report:financials:001')])
  expect(await screen.findByText(/上游缺失，下游结论 fail closed/)).toBeInTheDocument()
})
```

- [ ] **Step 3: 运行确认红测**

```bash
cd platform
npm --prefix frontend test -- --run src/features/system
```
Expected: FAIL —— 两个模块都不存在。

- [ ] **Step 4: 实现 —— 按 `9:661` 比例声明栅格**

```less
// features/system/system.less
// Figma node 9:661: content 1194 wide (x=246..1440), main table 790 and right
// column 362 with a 20 gap.  Runtime content is 1160 because of the 280 px
// sider, so ratio tracks absorb the difference rather than overflowing.
.systemWorkspaceGrid {
  display: grid;
  align-items: start;
  gap: 20px;
  grid-template-columns: minmax(0, 790fr) minmax(0, 362fr);
}

.systemKpiRow {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

// The 8-column quality table exceeds 320 and 768; it scrolls inside its own
// wrapper.  Page-level scrollWidth must stay equal to clientWidth.
.systemTableScroll {
  min-width: 0;
  overflow-x: auto;
}
```

**KPI 计数在服务端还是客户端？** 计数是纯聚合、无治理语义，且服务端已返回全量行，
所以在客户端按 `status` 分组计数是允许的 —— 但**必须只用服务端返回的 `status` 字段**，
不得由 `checks_failed > 0` 之类推断出一个新状态。测试第二条守着这一点。

- [ ] **Step 5: 转绿并确认现有 System 测试无回归**

```bash
cd platform
npm --prefix frontend test -- --run src/features/system
npm --prefix frontend test -- --run src/pages/SystemScreen.test.tsx src/pages/SystemScreen.pagination.test.tsx
```

`SystemScreen.pagination.test.tsx` 的三条参数化测试（catalog / quality / lineage）
**必须继续全绿** —— 它们守着「Table 只收当前页但 total 是全量」这条不变量。

- [ ] **Step 6: 1440 逐区对照 node `9:661`**

```bash
cd platform
.venv/bin/python - <<'PY'
from playwright.sync_api import sync_playwright
import json
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    for tab in ("quality", "lineage"):
        c = b.new_context(viewport={"width": 1440, "height": 1200})
        page = c.new_page()
        page.goto(f"http://127.0.0.1:5173/system?tab={tab}", wait_until="networkidle")
        page.wait_for_timeout(1500)
        boxes = page.evaluate("""() => {
            const pick = (sel) => {
                const node = document.querySelector(sel)
                if (!node) return [sel, null]
                const box = node.getBoundingClientRect()
                return [sel, {x: Math.round(box.x), y: Math.round(box.y),
                              w: Math.round(box.width), h: Math.round(box.height)}]
            }
            return ['.systemKpiRow', '.systemWorkspaceGrid', '.systemTableScroll',
                    '.systemRuleColumn', '.systemStageStrip'].map(pick)
        }""")
        print(tab, json.dumps(boxes, ensure_ascii=False, indent=1))
        page.screenshot(path=f"/tmp/pui04-system-{tab}-1440.png", full_page=True)
        c.close()
    b.close()
PY
```

对照并记录（期望值按 1160/1194 比例换算）：

```text
Figma          → 期望运行时
KPI 卡 264 × 92 → 约 257 × 92（四卡 gap 16）
主表      790   → 约 767
右栏      362   → 约 352
五段  214 × 102 → 约 208 × 102
```

- [ ] **Step 7: 四视口验收**

Run: `cd platform && .venv/bin/python scripts/verify_factor_system_browser.py`

768 与 320 特别检查：8 列质量表必须在 `.systemTableScroll` 内滚动，
页面级 `scrollWidth === clientWidth`；右栏规则在 1280 以下移到主表下方而非压缩到不可读。

- [ ] **Step 8: 记录设计与 API 差距并提交**

Evidence 必须写清楚：

1. `9:661` 是 Quality 与 Lineage **共用**的 Frame，Lineage 没有自己的独立 Frame，
   因此 Lineage 的 parity 结论是「按共用 Frame 的结构对照」，弱于 Quality；
2. `9:661` 表的「规则」与「影响」两列**在 `QualityReportEntry` 中无对应字段**，
   运行时显示 `—` 并说明原因，**不由前端推断**；
3. `9:661` 的 tab 条有 8 项（含 Entitlements / Users / Agents / Approvals），
   运行时这四项仍是 `placeholder`（P9/P10），本 plan 不动；
4. 侧栏 224（Figma）vs 280（运行时）为已批准差异；
5. 320/768/1024 无独立 Frame。

```bash
cd platform
npm --prefix frontend test -- --run && npm --prefix frontend run lint && npm --prefix frontend run build
cd .. && git add platform/frontend/src/features/system/ platform/frontend/src/pages/SystemScreen.tsx \
  platform/frontend/src/app/shell.less
git commit -m "feat: build Quality and Lineage against Figma node 9:661

Both pages were bare tables.  The frame they share adds four KPI cards, a right
column of propagation rules and the fixed five-stage strip — and the right column
is the part that carries the product value: it states that a warning propagates
to current pages while a blocked check forbids strict downstream use.  Those are
governance facts rather than sample data, which is why they may appear without a
server record.

Two of the frame's eight table columns, 规则 and 影响, have no field in
QualityReportEntry.  They render as explicitly unavailable with the reason.
Inferring 'strict downstream' from a failed status would move a propagation
decision into the browser, and that decision is the server's.

KPI counts group the served status field and nothing else.  Deriving a status
from checks_failed would invent a fifth state the server never reported.

The frame's numbers stay out: 184 checks, 169 passed, Q-1300, RUN-1400 and the
92% pass rate are design fixtures."
```

---

### Task 9: System Catalog 与 Jobs —— 按 Task 8 的结构统一，保留双层分页

Catalog 与 Jobs **都没有独立 Frame**，`design_status` 保持 `missing`。
做法是复用 Task 8 已经按 `9:661` 建好的 `systemWorkspaceGrid` / `systemKpiRow` /
`systemStageStrip`，让四个 System tab 结构一致 —— 这比每页各自发挥更接近蓝图意图，
且能明确记录「结构假设来自 `9:661`，不是本页自己的 Frame」。

Jobs 有一处必须保护：`JobCards` 里 **coverage 与 checkpoint 各自有独立分页**
（`SystemScreen.tsx` 第 146–210 行，`CoverageEvidence` / `CheckpointEvidence` 各用一次
`useClientPage` 并显示 `{rows.length} TOTAL`），外层 job 列表还有第三层分页。
一个 job 可能有上千个 checkpoint，把它们摊平会让页面无法使用；把它们截断会隐藏失败证据。

**Files:**
- Modify: `platform/frontend/src/pages/SystemScreen.tsx`
- Create: `platform/frontend/src/features/system/SystemJobsWorkspace.tsx`
- Create: `platform/frontend/src/features/system/SystemCatalogSection.tsx`
- Create: `platform/frontend/src/features/system/SystemJobsWorkspace.test.tsx`
- Modify: `platform/frontend/src/pages/SystemCatalogWorkspace.tsx`

**Interfaces:**
- Consumes: `GET /api/system/catalog` → `DatasetCatalogEntry[]`；
  `GET /api/system/jobs` → `IngestionJobEntry[]`（内嵌 `checkpoints[]` / `quality_reports[]` /
  `coverage_reports[]`，且带 `failure_reasons[]` 与 `output_trust_state`）
- Produces: 结构统一的两页；**三层分页与 `{n} TOTAL` 计数全部保留**

- [ ] **Step 1: 确认三层分页的现有行为**

```bash
cd platform/frontend/src
sed -n 146,248p pages/SystemScreen.tsx
```

确认：`CoverageEvidence` 与 `CheckpointEvidence` 都用 `hideOnSinglePage size="small"`，
标题栏显示 `{rows.length} TOTAL`；外层 `JobCards` 用 `hideOnSinglePage`。

- [ ] **Step 2: 写红测 —— 分页与失败原因不可被结构重排破坏**

```tsx
// platform/frontend/src/features/system/SystemJobsWorkspace.test.tsx
/**
 * Job evidence keeps three independent pagers.
 *
 * One ingestion job can carry thousands of checkpoints.  Flattening them makes
 * the page unusable; truncating them hides the rejected rows and the errors,
 * which are the only reason to open this page after a failed backfill.  So the
 * job list, the coverage reports and the checkpoints each paginate on their own
 * and each states its real total.
 *
 * A restructure is exactly when this quietly breaks, so the totals are asserted
 * rather than assumed.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SystemJobsWorkspace } from './SystemJobsWorkspace'

const context = {
  as_of: '2026-08-16T02:00:00Z',
  system_as_of: '2026-08-16T02:00:10Z',
  data_mode: 'current_research',
  deployment_stage: 'research',
  trust_state: 'normalized_current',
  dataset_version_ids: [],
  model_version_ids: [],
  run_id: null,
  coverage: {},
  warnings: [],
}

function checkpoint(index: number) {
  return {
    checkpoint_key: `checkpoint:financials:${String(index).padStart(4, '0')}`,
    scope_id: 'scope:csi500',
    data_domain: 'financial_statement',
    market: 'XSHG',
    status: index % 7 === 0 ? 'failed' : 'succeeded',
    processed_rows: 120,
    rejected_rows: index % 7 === 0 ? 12 : 0,
    provider_id: 'akshare',
    updated_at: '2026-08-16T01:00:00Z',
    error: index % 7 === 0 ? 'provider returned a partial response' : null,
    warnings: [],
  }
}

function job(overrides: Record<string, unknown> = {}) {
  return {
    job_id: 'ingestion-job:financials:001',
    plan_id: 'ingestion-plan:csi500-financials:2026-08-16',
    provider_id: 'akshare',
    status: 'failed',
    output_trust_state: 'normalized_current',
    start_date: '2018-01-01',
    end_date: '2025-12-31',
    created_at: '2026-08-16T00:00:00Z',
    updated_at: '2026-08-16T01:00:00Z',
    dataset_version_id: null,
    failure_reasons: ['provider quota exhausted', 'checkpoint 0007 rejected 12 rows'],
    checkpoints: Array.from({ length: 55 }, (_, index) => checkpoint(index)),
    quality_reports: [],
    coverage_reports: Array.from({ length: 31 }, (_, index) => ({
      coverage_report_id: `coverage-report:financials:${index}`,
      dataset_version_id: 'dataset:csi500-financials:v1',
      job_id: 'ingestion-job:financials:001',
      scope_id: 'scope:csi500',
      data_domain: 'financial_statement',
      start_date: '2018-01-01',
      end_date: '2025-12-31',
      expected_rows: 12_000,
      observed_rows: 11_922,
      coverage_ratio: 0.9935,
      warnings: ['78 legal empty periods kept empty rather than zero-filled'],
      created_at: '2026-08-16T01:00:00Z',
    })),
    ...overrides,
  }
}

function renderJobs(rows: unknown[]) {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true, status: 200, json: async () => ({ data: rows, context }),
  }) as Response))
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><SystemJobsWorkspace /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SystemJobsWorkspace', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('states the real coverage and checkpoint totals, not the page size', async () => {
    renderJobs([job()])
    expect(await screen.findByText('31 TOTAL')).toBeInTheDocument()
    expect(screen.getByText('55 TOTAL')).toBeInTheDocument()
  })

  it('names both checkpoint and coverage groups for a screen reader', async () => {
    renderJobs([job()])
    expect(await screen.findByRole('region', {
      name: 'ingestion-job:financials:001 checkpoints',
    })).toBeInTheDocument()
    expect(screen.getByRole('region', {
      name: 'ingestion-job:financials:001 coverage reports',
    })).toBeInTheDocument()
  })

  it('keeps every failure reason visible rather than showing only the first', async () => {
    renderJobs([job()])
    expect(await screen.findByText(/provider quota exhausted/)).toBeInTheDocument()
    expect(screen.getByText(/checkpoint 0007 rejected 12 rows/)).toBeInTheDocument()
  })

  it('shows an unknown expected row count as 未知 rather than as zero', async () => {
    renderJobs([job({
      coverage_reports: [{
        coverage_report_id: 'coverage-report:financials:0',
        dataset_version_id: 'dataset:csi500-financials:v1',
        job_id: 'ingestion-job:financials:001',
        scope_id: 'scope:csi500',
        data_domain: 'financial_statement',
        start_date: '2018-01-01',
        end_date: '2025-12-31',
        expected_rows: null,
        observed_rows: 11_922,
        coverage_ratio: null,
        warnings: [],
        created_at: '2026-08-16T01:00:00Z',
      }],
    })])
    expect(await screen.findByText(/11922 \/ 未知/)).toBeInTheDocument()
    expect(screen.queryByText('11922 / 0')).not.toBeInTheDocument()
  })

  it('shows the output trust state so a free source is never read as PIT', async () => {
    renderJobs([job()])
    expect(await screen.findByText('normalized_current')).toBeInTheDocument()
    expect(screen.queryByText('pit_verified')).not.toBeInTheDocument()
  })

  it('reports a job with no DatasetVersion as 未生成 rather than blank', async () => {
    renderJobs([job()])
    expect(await screen.findByText('未生成')).toBeInTheDocument()
  })
})
```

- [ ] **Step 3: 运行确认红测 → 实现 → 转绿**

```bash
cd platform
npm --prefix frontend test -- --run src/features/system/SystemJobsWorkspace.test.tsx
```

实现时把 `CoverageEvidence` / `CheckpointEvidence` 从 `SystemScreen.tsx` 搬到
`features/system/`，**逐字保留** `{rows.length} TOTAL`、`aria-label`、
`expected_rows ?? '未知'` 与 `dataset_version_id ?? '未生成'` 的处理。

- [ ] **Step 4: Catalog 保留 Financial Evidence 子 tab**

`SystemCatalogWorkspace.tsx` 目前是 `Dataset Versions` + `Financial Evidence` 两个子 tab，
后者是 `SystemEvidenceScreen`（264 行，含披露时间线 / 事实修订 / current-strict 对比 /
mismatch queue 四个视图 + 原始证据抽屉）。**这是全仓库最完整的诚实诊断页，不要重排它。**
只需给外层套上 Task 8 的 KPI + 五段结构。

红测：

```tsx
// platform/frontend/src/pages/SystemCatalogWorkspace.test.tsx
function renderCatalog() {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true, status: 200, json: async () => ({ data: [], context }),
  }) as Response))
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><SystemCatalogWorkspace /></MemoryRouter>
    </QueryClientProvider>,
  )
}

it('keeps the financial evidence diagnostics reachable from Catalog', async () => {
  // SystemEvidenceScreen holds the disclosure chain, the bitemporal revisions,
  // the current/strict comparison and the mismatch queue.  A restructure that
  // buried it would remove the only surface that shows why a value is or is not
  // point-in-time.
  renderCatalog()
  fireEvent.click(await screen.findByRole('tab', { name: 'Financial Evidence' }))
  expect(await screen.findByRole('tab', { name: '披露时间线' })).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: '事实修订' })).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: 'Current / Strict' })).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: 'Mismatch Queue' })).toBeInTheDocument()
})

it('does not present a current/strict comparison as a trust upgrade', async () => {
  renderCatalog()
  fireEvent.click(await screen.findByRole('tab', { name: 'Financial Evidence' }))
  expect(await screen.findByText(
    /current 数据不会被当作 PIT/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('tab', { name: 'Current / Strict' }))
  expect(await screen.findByText(
    /对比不会把 normalized_current 提升为 PIT/)).toBeInTheDocument()
})
```

- [ ] **Step 5: 四视口验收**

Run: `cd platform && .venv/bin/python scripts/verify_factor_system_browser.py`

320 特别检查：Jobs 的 `Descriptions column={{ xs: 1, sm: 2, lg: 4 }}` 在 xs 下必须单列；
三层 Pagination 在 320 下必须 `size="small"` 且不溢出。

- [ ] **Step 6: 记录设计假设并提交**

Evidence 写明：Catalog 与 Jobs **无独立 Frame**，`design_status` 保持 `missing`；
结构假设「复用 `9:661` 的 KPI + 主表/卡片 + 右栏 + 五段」；
Catalog KPI 假设为 DatasetVersion 总数 / 有质量报告数 / 最新入库时间 / trust ceiling 分布；
Jobs KPI 假设为 job 总数 / failed 数 / blocked 数 / 最新更新时间。

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
npm --prefix frontend test -- --run && npm --prefix frontend run lint && npm --prefix frontend run build
cd .. && git add platform/frontend/src/features/system/ platform/frontend/src/pages/
git commit -m "feat: give System Catalog and Jobs the shared 9:661 structure

Neither page has its own high-fidelity frame, so instead of improvising per page
they reuse the grid, KPI row and five-stage strip built for Quality against node
9:661.  That keeps the four System tabs consistent and, more importantly, makes
the design provenance recordable: the structure is an assumption borrowed from a
sibling frame, not a parity claim about these two pages.

Jobs keeps three independent pagers.  A single backfill can carry thousands of
checkpoints; flattening them makes the page unusable and truncating them hides
the rejected rows and provider errors, which are the only reason anyone opens
this page after a failed run.  Each pager states its real total.

An unknown expected row count still reads 未知 and a job without a DatasetVersion
still reads 未生成.  Both would be a zero or a blank if the restructure had been
careless, and either would misreport coverage.

The financial evidence diagnostics stay reachable from Catalog untouched — the
disclosure chain, the bitemporal revisions, the current/strict comparison and the
mismatch queue are the only surface that shows why a value is not
point-in-time."
```

---

### Task 10: Evidence、Track 状态更新与明确否认

**Files:**
- Create: `docs/26-pui-04-factor-system-evidence.md`
- Modify: `docs/plans/track-00-prototype-runtime-delivery.md`（PUI-04 状态 + 删除已修缺陷条目）
- Modify: `docs/22-prototype-runtime-gap-audit.md`（追加增量更新一节，**不改写原审计事实**）

- [ ] **Step 1: 记录真实红绿测**

每个 Task 的**真实**失败文本与转绿结果。`npm test` 与 `unittest` 的输出原样抄录，
**不编造命令输出**。Task 1 必须包含 320 视口 `scrollWidth 652 → 320` 的实测前后值。

- [ ] **Step 2: 逐页登记三轴状态**

按本 plan §页面三轴目标 的表格填写**实际达到的**结论。允许的写法：

```text
design_status:     missing | ready | parity_verified_with_known_deviation
runtime_status:    placeholder | partial | verified
capability_status: blocked | partial | verified
```

**七页 `design_status` 必须写 `missing`。** 若某页写成 `ready` 或 `parity_verified`，
必须能指出它的精确 Figma node id —— 除 `7:5`（Alpha Model）与 `9:661`（Quality、Lineage）
之外**没有别的 node 可指**。

- [ ] **Step 3: 逐页记录设计假设（无 Frame 的七页）**

每页至少记录：结构来源（借自哪个 Frame 的哪一部分）、KPI 选择理由、列选择理由、
以及哪些 Figma 元素**故意没有实现**及原因。这是等用户验收的清单，不是完成声明。

- [ ] **Step 4: 记录设计与 API 的差距**

至少包含：

1. `9:661` 表的「规则」「影响」列在 `QualityReportEntry` 无字段 → 运行时 `—` + 说明；
2. `7:5` 的权重表需要「因子权重配置」，但当前没有任何已获批 FactorVersion → 空表 + blocker；
3. `7:5` 的 Snapshot 表需要合格 `SignalSnapshot`，当前为 0（P5 阻断）；
4. `9:661` tab 条的 Entitlements / Users / Agents / Approvals 四项仍为 `placeholder`（P9/P10）。

- [ ] **Step 5: 写明确否认声明**

必须逐字包含：

> 本 plan 只交付**前端产品结构与真实六态**。它**不代表**：
>
> - P2、P4 或 P5 Gate 通过 —— 三者的数据与科学阻断完全未变；
> - 任何因子科学有效 —— 页面显示的 lifecycle 与 approval 是治理事实，不是有效性证据；
> - 31 页 Design Parity 完成 —— 十页中七页无独立高保真 Frame，`design_status` 保持 `missing`，
>   完全逐像素 parity 计数仍为 **0/31**；
> - Timing 或 Correlation 能力存在 —— 两者分别属 P7 与 P9，本 plan 只让它们诚实报告未实现；
> - 平台具备可盈利策略、Paper-ready 或实盘能力。
>
> Design Parity、Runtime Product 与 Domain Capability 是三条独立轴。本 plan 只推进前两条，
> 且第一条只在两个有精确 Frame 的页面上推进。

- [ ] **Step 6: 更新 Track 与审计**

`docs/plans/track-00-prototype-runtime-delivery.md`：

- PUI-04 状态从 `ready_for_implementation` 改为 `in_progress` 或 `verified`（按实际结果）；
- 逐页三轴结论表（照 PUI-01/PUI-02 的格式）；
- 「与 Figma 的已知差异」小节；
- **§待修复的既有缺陷 中 `/factors` 320 溢出那一条改为已修复，并记录真实根因是
  `.factorWorkspace` 缺 `grid-template-columns`，不是 `pageHeading`** —— 原记录的归因是错的，
  这里要纠正而不是照抄。

`docs/22-prototype-runtime-gap-audit.md`：追加「2026-08-16 PUI-04 完成后的增量更新」一节，
**保留原 §5 矩阵不改写**（它记录审计时点事实），在增量节里说明十页的新状态与
「完全 parity 计数仍为 0/31」。

- [ ] **Step 7: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
npm --prefix frontend test -- --run
npm --prefix frontend run lint
npm --prefix frontend run build
.venv/bin/python scripts/verify_factor_system_browser.py
git diff --check
cd .. && git add docs/26-pui-04-factor-system-evidence.md \
  docs/plans/track-00-prototype-runtime-delivery.md \
  docs/22-prototype-runtime-gap-audit.md
git commit -m "docs: record PUI-04 evidence and correct the /factors overflow attribution

Three axes reported separately for all ten pages.  Seven of them keep
design_status missing because they have no dedicated high-fidelity frame — only
the 31-page blueprint — so their layout rests on documented assumptions awaiting
your review, not on a parity claim.  Only Alpha Model (node 7:5), Quality and
Lineage (both node 9:661) had a frame to compare against, and the full
pixel-parity count across the 31 pages stays 0/31.

The track recorded the /factors 320 defect as a pageHeading overflow.  That
attribution was wrong and is corrected here: the heading was stretched by a grid
container that never bounded its columns.  Leaving the wrong root cause in place
would send the next person to the wrong file.

Two gaps between the frames and the API are recorded rather than papered over:
9:661 draws 规则 and 影响 columns that QualityReportEntry has no field for, and
7:5 draws a factor weight table for approvals that do not exist.  Both render as
explicitly unavailable.

Neither the P2, P4 nor P5 gate moves, and nothing here is evidence that any
factor works."
```

---

## 完成定义

1. `/factors` 四视口页面级 `scrollWidth === clientWidth`，且 `layoutGrid.test.ts` 守住网格声明不变量（Task 1）；
2. Factor 六分区复用 `DeskSection` 合同，`DeskSection.test.tsx` 与 `DeskPage.test.tsx` 无回归（Task 2）；
3. Factor Catalog 消费 `GET /api/factors/catalog` 投影，20 行硬编码 `factorDefinitions` 已删除（Task 3）；
4. Alpha Model 按 node `7:5` 完成 1440 结构对照，复用已有 `AlphaModelReadinessPanel`，
   `ALPHA-V0.8` / `RVW-*` / `35%` / `0.42` 等示例值零泄漏（Task 4）；
5. Experiments 真实分页，失败 Experiment 跨页可达、`失败保留` 标签与完整不可变失败文本均保留，
   可钻取到 run / spec / dataset / definition（Task 5）；
6. Production 真实读取 `GET /api/factors/reviews`，四个 scope 分别展示且互不隐含，
   rejected review 保留可见（Task 6）；
7. Timing Lab 报 `P7_ACTIVE_TIMING_NOT_IMPLEMENTED`，Correlation Monitor 报
   `P9_CORRELATION_MONITOR_NOT_IMPLEMENTED`，且后者不渲染空相关性矩阵（Task 7）；
8. Quality 与 Lineage 按 node `9:661` 完成 1440 结构对照，四条传播规则与 trust ceiling 边界已展示，
   「规则」「影响」两列显式不可用（Task 8）；
9. Catalog 与 Jobs 结构统一，Jobs 三层分页与 `{n} TOTAL` 计数保留，
   Financial Evidence 诊断页可达且未被重排（Task 9）；
10. Evidence 逐页记录三轴、设计假设、设计-API 差距与明确否认；Track 与审计已更新，
    `/factors` 溢出的错误归因已纠正（Task 10）；
11. 后端 unittest / compileall / ruff / mypy 全过；前端 Vitest / lint / build 全过；
12. `verify_factor_system_browser.py` 40 个（10 页 × 4 视口）检查点全部无页面级溢出、
    无 DESIGN FIXTURE 泄漏、无控制台 error/warning、无非 API 的 4xx/5xx；
13. `git diff --check` 干净，一个 Task 一个独立提交。

## 明确不在本 plan 范围

- **主动 Timing 能力** —— 属 P7 / PUI-06；本 plan 只让 Timing Lab 诚实报告未实现；
- **相关性监控能力** —— 属 P9 / PUI-08；本 plan 只让它诚实报告未实现；
- **Users / Entitlements / Agents / 通用 Approvals 四页** —— 属 P9/P10 / PUI-08/PUI-09，
  保持 `placeholder`，本 plan 不触碰；
- **可编辑因子权重与「运行 Screen」类动作** —— 需 P4 资格门通过与 ADR-0012 第二阶段；
- **真实 IC / RankIC 数值** —— 属 P-2（`2026-08-16-p2-factor-research-orchestration.md` Task 6
  会把真实 IC 接到 Alpha 页；本 plan 只把 Alpha 页的结构建好）；
- **合格 SignalSnapshot / InvestmentView / FactorVersion 晋级** —— 属 P4/P5 数据与科学门；
- **320/768/1024 的 Figma 视觉验收** —— 三档无独立 Frame，只按 `docs/18` 响应式合同重排；
- **截图 diff 工具** —— 需用户先批准基线与容差（`docs/plans/track-00` PUI-00 已记录）；
- **新增任何后端写接口** —— 本 plan 只新增一个只读投影端点。

## 本 plan 完成后仍然成立的限制

- **十页中七页 `design_status` 保持 `missing`** —— Catalog、Timing Lab、Experiments、
  Correlation Monitor、Production、System Catalog、System Jobs 都没有独立高保真 Frame，
  只有 31 页蓝图 `3:1569`。它们的布局是**已记录的设计假设**，等用户验收；
- Lineage 与 Quality 共用 `9:661`，Lineage 没有专属 Frame，其 parity 结论弱于 Quality；
- **31 页完全逐像素 parity 计数仍为 0/31**；
- 侧栏 280 px 使 1440 内容区为 1160 px 而非 Figma 的 1192/1216 px，属已批准差异；
- 320 视口 AntD tab 条在自身容器内滚动，与未触碰的 `/monitoring` 一致，属既有可接受行为；
- Vite 的 AntD large-chunk warning 仍然存在，**不得隐藏也不得写成已修复**；
- 无库运行时所有 System / Experiment / Review 端点返回 `503`，页面显示真实 unavailable ——
  这是被验收的状态之一，不是缺陷；
- **P2、P4、P5 Gate 全部未通过**，本 plan 不改变任何一条；
- 页面上出现的 lifecycle、approval、scope 是**治理事实**，不是因子有效性证据；
- 不得据本 plan 声称平台具备可盈利策略、Paper-ready 或实盘能力。
