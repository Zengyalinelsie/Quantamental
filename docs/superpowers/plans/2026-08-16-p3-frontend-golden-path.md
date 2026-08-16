# P-3 前端黄金路径实现计划（PUI-03）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 P5 黄金路径的四个页面做成原型结构：Security 融合总览（Figma `24:400`，1440 × 1900）、InvestmentView 独立详情路由（`15:2`，1440 × 1200）、Approvals Reviewer 队列（`9:883`，1440 × 1200）与 Alpha Model（`7:5`，1440 × 1200）。真实对象不存在时保持完整版式并显示服务端 blocker，不注入 DESIGN FIXTURE 数字。

**Architecture:** 复用 PUI-01 建立的分区合同（`domain/desk.py` 的四态 + `features/desk/DeskSection.tsx` + `deskState.ts`）与 PUI-02 的只读投影纪律。新增两个服务端投影（Security 融合总览、Approvals 队列）与一个受权限门控的写入端点（提交 Review）。前端只消费投影：不重算 rank、不推断 trust、不推断审批资格。Security 融合页 1900 px 拆成多个聚焦组件文件，不写成一个巨型文件。

**Tech Stack:** React 19 + TypeScript + Vite、AntD 6、@tanstack/react-query 5、zustand 5、Vitest + @testing-library/react；后端 FastAPI + Pydantic v2（`api/schemas.py` 的 `StrictResponse`）、Python 3.11+

## Global Constraints

以下每条继承自 `AGENTS.md`、`docs/07-detailed-system-spec.md` 与已接受 ADR，**每个 Task 都适用**：

- **前端只消费服务端投影**：不得在浏览器里重算 rank、rank change、score、闭合校验、trust 提升或审批资格
- **不得注入 runtime fixture**：测试 fixture 只允许存在于 `*.test.tsx` 中，不得进入 runtime bundle 或默认 API 响应
- **Figma DESIGN FIXTURE 值不得进入运行时**：`¥1,856.20`、`+1.2%`、`1,505.6`、`747.3`、`30.2%`、`682.1`、`32.4x`、`18.2x`、`REV-1500`–`REV-1510`、`User-1`/`Reviewer-2`、`ALPHA-V0.8`、`35%/30%/25%/10%`、`Evidence coverage 18/24` 全部是设计示例
- **缺失、不可比、无权限必须显式表达，禁止填零**：`constrained` / `unavailable` / `not_applicable` 三态都显示 `—`，但 status 各自保留
- **一个域被阻断不得让页面塌掉**（PUI-01/PUI-02 的教训）：分区级隔离，保留原型骨架并在该分区显示 blocker
- **侧栏 280 px 已裁决**（SPEC-045，2026-08-15）：1440 下主内容区为 1160 px 而非 Figma 的 1192/1216 px；两栏以比例声明吸收差异，**不得为对齐 Figma 而改回 224/248 px**
- **320/768/1024 没有 Figma Frame**：三档按 `docs/18` 响应式合同重排，只能声明为合同验收，不得声称 Figma 视觉验收
- **审批是服务端拥有的写操作**：前端隐藏按钮不能替代权限校验；anonymous identity 只有 `read_public`，因此 Review 提交在当前运行时必然被拒绝，页面必须显示**服务端返回的**禁用原因
- **`RunContext` 固定 `(current_research, research)`**：`fixed_read_context` 已拒绝 query 参数提升，新端点必须复用它
- **不得声称 P2/P4/P5 Gate 通过，不得声称任何模型科学有效**
- 未经用户明确授权不 commit、不 push

## 现状事实（2026-08-16 逐文件核实）

### 已存在、本 plan 直接复用（不重建）

| 资产 | 真实路径 | 关键内容 |
|---|---|---|
| 六态组件 | `platform/frontend/src/components/WorkspaceState.tsx` | `WorkspaceStateKind = loading \| error \| empty \| partial \| unavailable \| ready \| blocked`；`blocked` 是 `unavailable` 的兼容别名；`partial` 同时渲染 notice 与 children |
| 分区合同（前端） | `platform/frontend/src/features/desk/DeskSection.tsx` | `DeskSectionProps { section, loading?, error?, subtitle?, extra?, children? }`；`unavailable`/`partial` 时渲染 `deskSection__blockers` |
| 分区状态解析 | `platform/frontend/src/features/desk/deskState.ts` | `resolveSectionState(section, { loading, error })`、`noticeReason(section, error)`、`coverageText`、`metricsFromPayload(payload, fields)` |
| 分区合同（后端） | `platform/src/a_share_platform/domain/desk.py` | `DeskSectionStatus = READY\|PARTIAL\|EMPTY\|UNAVAILABLE`；`partial` 必须声明 coverage 或 blocker；`unavailable` 必须声明 blocker；`ready`/`partial` 必须有 payload，其余必须无 payload |
| InvestmentView 组件族 | `platform/frontend/src/features/investment-view/` | `InvestmentViewSummary.tsx`、`ExpectedReturnDistribution.tsx`、`InvestmentComponentWaterfall.tsx`、`InvestmentEvidencePanel.tsx`、`FrozenArtifactPanel.tsx`、`investmentViewProjection.ts`、`investmentViewSummary.less` |
| Alpha 面板 | `platform/frontend/src/features/screen/AlphaModelReadinessPanel.tsx` | `props: { projection: AlphaModelReadinessProjection }`；`status === 'unavailable'` 分支渲染 `blocked_reasons`，ready 分支渲染 `data-testid="approved-alpha-model"` |
| P5 研究页 | `platform/frontend/src/pages/ResearchP5Screen.tsx` | `props: { section: 'universe-screen' \| 'security' }`；已实现 unavailable 保结构、`ResearchBlockers`、`AlphaModelReadinessPanel` 尾挂 |
| Artifact 权限门 | `platform/frontend/src/features/investment-view/FrozenArtifactPanel.tsx` | 先查 `getIdentity()`，`permissions.includes('read_artifact')` 才 enable metadata 查询；缺 `permissions` 字段时**失败关闭** |
| 权限策略 | `platform/src/a_share_platform/application/permissions.py` | `Principal.anonymous()` 只有 `READ_PUBLIC`；`Role.REVIEWER` 才有 `APPROVE_RESEARCH` |

### 已存在的服务端 schema（本 plan 消费，不改字段语义）

`platform/src/a_share_platform/api/schemas.py` 的真实定义：

```python
class InvestmentComponentProjection(StrictResponse):
    component: InvestmentComponentName        # "quality" | "valuation" | "revision" | "event"
    label: str
    status: InvestmentComponentStatus         # "quantified"|"constrained"|"unavailable"|"not_applicable"
    contribution: ScreenProjectedValue | None # {raw: str, display: str}
    reason: str
    evidence_ids: list[str]
    visual: WaterfallVisualProjection | None  # {start_percent, width_percent, direction}

class ResidualProjection(StrictResponse):
    status: InvestmentComponentStatus
    contribution: ScreenProjectedValue | None
    reason: str
    evidence_ids: list[str]
    visual: WaterfallVisualProjection | None

class ClosureProjection(StrictResponse):
    status: Literal["passed", "failed", "unavailable"]
    displayed_total: str | None
    tolerance: str
    difference: str | None
    checked_by: str

class InvestmentViewProjection(StrictResponse):
    view_id: str
    security: InvestmentSecurityProjection    # security_id/symbol/exchange/display_name
    decision_time: datetime
    horizon: str                              # 投影为 "60D"（_project_investment_view）
    data_mode: DataMode
    trust_state: Literal["normalized_current", "pit_verified"]
    trust_reason: str
    distribution: ExpectedReturnDistributionProjection  # point/p10/p50/p90/downside
    components: list[InvestmentComponentProjection]
    residual: ResidualProjection
    closure: ClosureProjection
    confidence: ScreenProjectedValue
    catalysts: list[CatalystProjection]       # catalyst_id/summary/horizon/evidence_ids
    invalidators: list[InvalidatorProjection] # invalidator_id/summary/evidence_ids
    evidence: list[InvestmentEvidenceProjection]
    versions: InvestmentViewVersionsProjection  # ...artifact_id: str | None
    warnings: list[str]

class ResearchWorkspaceData(StrictResponse):
    status: Literal["ready", "partial", "unavailable"]
    blockers: list[ResearchWorkspaceBlocker]  # code/reason/affected_binding/evidence_ids
    screen: ScreenRankingProjection | None
    investment_view: InvestmentViewProjection | None
    alpha_model: AlphaModelReadinessProjection  # discriminated on "status"
```

### 必须新建（当前完全不存在）

| 缺口 | 核实方式 | 影响 |
|---|---|---|
| **Approvals API** | `grep "@app\.\(get\|post\)" api/app.py` 只有 `GET /api/factors/reviews`、`GET /api/factors/reviews/{review_id}`、`POST /api/factors/reviews`。**没有** `/api/approvals` 队列端点，没有跨对象类型（Factor / Alpha Model / InvestmentView / Timing）的统一队列 | Figma `9:883` 的 4 个计数卡与 11 行队列表没有数据源 |
| **Approvals 前端页** | `pages/WorkspacePage.tsx` 的 `activationReasons.approvals` 是一句静态文案「服务端审批工作流尚未启用」 | `/system?tab=approvals` 是一条泛化提示，没有原型结构 |
| **Security 融合总览投影** | `application/research_workspace.py` 只投影 screen / investment_view / alpha_model 三块 | Figma `24:400` 的公司画像、价值链、四问、财务轨迹、同业、Catalysts、跟踪计划、公告时间线全部无投影 |
| **InvestmentView 独立路由** | `app/AppShell.tsx` 只有 6 条一级路由；`ResearchP5Screen` 的 `section='security'` 内嵌渲染 View | Figma `15:2` 的 8 个 tab 与「打开证据」往返没有独立 URL 状态 |
| **提交 Review 的写入路径** | `POST /api/factors/reviews` 只接受 `FactorReviewInput`（FactorVersion + ValidationReport），**不接受 InvestmentView** | `docs/18` §9.1 P5-UI-05「提交 View → Approvals → 返回结果」无端点 |
| **Alpha 页真实产品化** | `pages/FactorWorkspace.tsx` 的 `alpha-model` tab 是一个 `WorkspaceState state="blocked"` | Figma `7:5` 的 4 个 metric 卡 + 因子权重表 + PIT Readiness 面板 + Snapshot 表 + 5 段流转全无结构 |

### Figma 真实布局（`figma-node-summary.json` + SVG 实测）

`figma-node-summary.json` 只记录 `name` / `type` / `w` / `h` / `text` / `font{size,weight,family}`，**不含 `layoutMode` 与 `itemSpacing`**（`grep` 计数为 0）。因此栏宽与间距由 SVG 路径 bbox 实测得出。

**node `24:400` security-overview-600519-fused-v2，1440 × 1900**（237 个直接子节点：157 TEXT / 75 VECTOR / 5 GROUP；无嵌套 FRAME）

侧栏 224 px（深色 `#17212D`），主内容 x=224 起、宽 1216。顶部三条：topbar 72 px、identity 带 124 px、tab 条 52 px。卡片区从 y=268 开始，左右两栏在四个纵段中比例不同：

| y | 左栏 | 右栏 | 实测 section 标题 |
|---:|---|---|---|
| 268 | x=246 w=746 h=294 | x=1012 w=402 h=294 | `DECISION BRIEF · CORE CONTRADICTION`（含三条 46 px 行 `必须成立 ① 品牌与渠道` / `② 盈利质量` / `③ 事件验证`）｜ `InvestmentView 就绪度` |
| 582 | x=246 w=560 h=258 | x=826 w=588 h=258 | `公司画像与价值链定位` ｜ `Catalysts / Invalidators / 证据变化`（两个 148 px 子卡 `核心催化剂` `失效条件`） |
| 860 | x=246 w=746 h=300 | x=1012 w=402 h=300 | `财务轨迹 · 5Y（可追溯摘要）` ｜ `公司质地评分 · 与交易评分分离` |
| 1180 | x=246 w=560 h=300 | x=826 w=588 h=300 | `估值预期差与情景区间`（三个情景 `压力/基准/改善`）｜ `行业同业对比 · Peer Analysis`（表头 34 px + 4 行 38/40 px） |
| 1500 | x=246 w=560 h=306 | x=826 w=588 h=306 | `跟踪计划 · 从静态研报到持续 Research Case`（三行 52 px `高频/季度/事件`）｜ `最新公告与证据时间线 · Security Feeds`（四行 44 px） |
| 1824 | x=246 w=1168 h=54 | — | 底部 `PROTOTYPE ONLY` 说明条 |

Tab 条 12 个（12 px）：`概览`（bold）`公司质量` `估值` `边际改善` `事件` `财务` `证据` `产业链` `情景` `对标` `跟踪` `InvestmentView`。

字号层级：24 bold 页标题、18 bold 命题、15 bold section 标题、12 bold 行标题、12 normal 正文、10 normal 辅助、9 normal 元数据、8 normal 状态徽标。

**node `15:2` security-investmentview，1440 × 1200**（7 个 GROUP）

侧栏 224 px（`#18202A`），topbar 64 + 64。主体：

| y | 卡片 | 实测标题 |
|---:|---|---|
| 212 | x=246 w=1168 h=50 | 期限选择条 `期限` + `20D` / `60D` / `120D`，右侧 `VIEW STATUS` + `PARTIAL · NOT APPROVED` |
| 278 | x=246 w=570 h=184 ｜ x=832 w=582 h=184 | `Expected Return Distribution · 60D` ｜ `闭合校验与版本绑定`（`分项合计` / `Residual` / `Point Estimate` 三行 + `✓ 5.8% + 0.1% = 5.9%，Decimal 闭合通过`） |
| 478 | x=246 w=1168 h=182 | `四分项瀑布与状态语义`，x 轴 `Start` `Quality` `Valuation` `Improvement` `Event` `Constraints` `Residual` |
| 676 | 4 × 278/292 w，h=214 | `公司质量` `估值预期差` `基本面改善` `事件影响`，各带 8 px 状态徽标 `QUANTIFIED`/`QUANTIFIED`/`CONSTRAINED`/`UNAVAILABLE` |
| 906 | x=246 w=760 h=134 ｜ x=1022 w=392 h=134 | `催化剂、失效条件与证据` ｜ `Frozen Artifact`（`未生成 · 不伪造 Artifact ID`，`证据不完整 · 禁止提交`） |
| 1056 | 5 × 214/272 w，h=100 | `INPUT · 输入` `PROCESS · 处理` `OUTPUT · 输出` `ACTION · 操作` `GATE · 门禁` |

Tab 条 8 个（13 px）：`概览` `公司质量` `估值` `改善` `事件` `财务` `证据` `InvestmentView`（bold）。

**node `9:883` 14-approvals-reviewer-queue，1440 × 1200**（229 个直接子节点，无嵌套 FRAME）

| y | 布局 | 实测内容 |
|---:|---|---|
| 196 | 4 × 264 w，h=92，间距 14 | `Pending`(7) `Approved Research`(6) `Rejected`(4) `Production`(0)；副文案 `Factor3 · View4` / `仅 research_backtest` / `保留完整理由` / `无 Shadow/Paper 晋级` |
| 316 | 左 x=246 w=790（42 标题 + 34 表头 + 11 × 39 行）｜ 右 x=1052 w=362 h=394 | `审批队列 · server-owned reviewer path` ｜ `审批规则` |
| 726 | 右 x=1052 w=362 h=96 `#FFF9E9` | `可信使用边界`：`前端隐藏按钮不能替代权限校验；` `当前无真实账户或 Limited Live 授权。` |
| 1062 | 5 × 214 w，h=102 | `INPUT · 输入` … `GATE · 门禁` |

表头 8 列（10 px）：`Review` `对象` `版本` `用途` `提交人` `证据` `Reviewer` `状态`。审批规则 5 条（12 px bold + 10 px 说明）：`服务端决定`／`批准/拒绝/撤回有身份、时间和理由`、`用途精确`／`research/shadow/paper 不可提升`、`证据不足`／`禁用决定并列出全部 blocker`、`版本不可变`／`修改产生新版本与新审查`。

**node `7:5` factors-alpha-model，1440 × 1200**（唯一有真实嵌套 FRAME 的节点）

```
factors-alpha-model 1440×1200
  viewport-wrap 1440×1200
    sidebar 248×1200 → brand 216×36, nav-list 216×236 (6 × nav-item 216×36), sidebar-footer 216×30
    main-content 1192×1200 → topbar 1192×64 (topbar-left 385×28, topbar-right 779×25)
                            workspace 1192×1160 → metrics-row 1144×114, layout-columns 1144×978
```

实测 rect：4 个 metric 卡 273 × 112/113（x=272.5/562.5/852.5/1142.5，y=88.5）；左栏 723 w（因子权重卡 y=222.5 h=280、Snapshot 卡 y=523.5 h=528、流转卡 y=1072.5 h=127）；右栏 399 w（PIT Readiness 卡 y=222.5 h=364）。

实测文案：metric 卡 `当前研究模型` / `激活绑定因子数` / `真实合格 Snapshot 数` / `生产运行主动影响`；`因子权重配置 / Factor Weight Configuration` 表头 6 列 `因子` `权重` `版本` `Review ID` `用途` `相关性警告`；`PIT Readiness 诊断 / PIT Readiness Panel` + 徽标 `PIT NOT READY`，5 行 `历史 Universe 截面` `季度财务 (Quarterly)` `TTM 财务` `个股价格 available_at` `行业分类 lineage`，状态 `✗ 缺失` × 3 / `✓ 可用` / `⚠ 部分可用`；`候选 Signal Snapshot / Candidate Snapshots` 表头 7 列 `Snapshot ID` `日期` `Universe` `覆盖` `因子版本` `PIT状态` `审批`，11 行全为 `—`；流转 5 段 `1. INPUT` … `5. GATE`，标签 `Factor + Universe` → `Score & Rank` → `Immutable Snapshot` → `提交模型审查` → `阻断 (无PIT可用)`。

关键说明文字（必须原样进入运行时，因为它是产品承诺而非示例值）：

> 说明: 本机制只依据物理落库时间进行因数时点回测归因，*不显示假 IC/收益数据*，坚决阻断由于数据前瞻导致的过拟合信号偏误。

### 与既有合同的冲突（必须先报告，不得自行裁决）

| 冲突 | Figma | 既有合同 | 本 plan 处理 |
|---|---|---|---|
| 侧栏宽度 | `24:400`/`15:2`/`9:883` 实测 224 px；`7:5` 的 `sidebar` FRAME 为 248 px | SPEC-045 + 2026-08-15 裁决：280 px 展开 / 72 px 收起 | **保持 280 px**。主内容区 1160 px，两栏按 Figma 比例声明。Figma 内部 248 与 224 自相矛盾，两者都不采用 |
| 因子权重可编辑 | `7:5` 权重列 `35%/30%/25%/10%` + `总计 Total 100%` + `权重完整，符合配比约束` | ADR-0012：构建器只读，权重输入需落为版本化 `ScreenDefinition` + `Run` 记录，且 P4 门未通过 | 权重表**只读投影**，无输入控件、无「运行」按钮；无绑定时逐行显示缺失原因 |
| InvestmentView tab 数 | `24:400` 12 个 tab；`15:2` 8 个 tab | 同一产品对象的两张稿 tab 集合不一致 | 以 `24:400` 的 12 个为融合页 tab 源；`15:2` 的 8 个作为 InvestmentView 详情页自身 tab。两者不合并，差异记入 Evidence |
| 审批对象类型 | `9:883` 队列含 `Factor` / `Alpha Model` / `InvestmentView` / `Timing` 四类 | 后端只有 `FactorPromotionReview`（`domain/factor_reviews.py`），且强制 `factor_lifecycle_status is CANDIDATE` | 队列投影**只投 Factor 一类**，其余三类由服务端声明 `unavailable` + P9 blocker，不伪造行 |
| Snapshot 表 11 行 `—` | `7:5` 渲染 11 行占位 | 真实运行时 Snapshot 数为 0 | 用 `empty` 态而非 11 行 `—`：11 行破折号会被误读为「有 11 个 Snapshot 但字段缺失」 |

---

### Task 1: Security 融合总览的服务端分区合同

Figma `24:400` 有 11 个内容分区，成熟度天差地别：`InvestmentView 就绪度` 有真实账本，`产业链` 与
`公告时间线` 属 P8，`同业对比` 需合格 comparable-set。因此必须先建**分区级**合同，
而不是让一个 `unavailable` 把 1900 px 页面塌成一条提示。复用 `domain/desk.py` 已验证的四态规则。

**Files:**
- Create: `platform/src/a_share_platform/domain/security_overview.py`
- Test: `platform/tests/test_security_overview_domain.py`

**Interfaces:**
- Consumes: 无（纯领域合同；不导入 FastAPI / provider / 前端概念）
- Produces:
  ```python
  class SecurityOverviewSectionKey(StrEnum):
      DECISION_BRIEF = "decision_brief"
      VIEW_READINESS = "view_readiness"
      COMPANY_PROFILE = "company_profile"
      CATALYSTS = "catalysts"
      FINANCIAL_TRAJECTORY = "financial_trajectory"
      QUALITY_SCORE = "quality_score"
      VALUATION_SCENARIOS = "valuation_scenarios"
      INDUSTRY_PEERS = "industry_peers"
      TRACKING_PLAN = "tracking_plan"
      SECURITY_FEEDS = "security_feeds"

  SECTION_ORDER: tuple[SecurityOverviewSectionKey, ...]   # 10 项，1440 版式顺序

  @dataclass(frozen=True)
  class SecurityOverviewSection:
      key: SecurityOverviewSectionKey
      status: DeskSectionStatus          # 复用，不新建第二套状态枚举
      title: str
      blockers: tuple[DeskBlocker, ...] = ()
      coverage: dict[str, Any] = field(default_factory=dict)
      payload: Any | None = None

  @dataclass(frozen=True)
  class SecurityOverviewProjection:
      security_id: str
      sections: tuple[SecurityOverviewSection, ...]   # 恒为 10 项
  ```

- [ ] **Step 1: 先读已验证的分区合同，确认要复用哪些不变量**

Run:
```bash
cd platform
grep -n "class DeskSectionStatus" -A 8 src/a_share_platform/domain/desk.py
grep -n "is DeskSectionStatus.PARTIAL and not" -A 6 src/a_share_platform/domain/desk.py
grep -n "must carry all seven sections" -B 6 src/a_share_platform/domain/desk.py
```

四条不变量必须照搬：`partial` 必须声明 coverage 或 blocker；`unavailable` 必须声明 blocker；
`ready`/`partial` 必须有 payload；其余状态**不得**携带 payload。分区集合恒定、缺一即报错。
**不要新建第二套状态枚举** —— 复用 `DeskSectionStatus` 与 `DeskBlocker`。

- [ ] **Step 2: 写失败测试**

```python
# platform/tests/test_security_overview_domain.py
"""Security fused-overview section contract.

The 1900 px Figma page mixes eleven domains that mature at different phases:
the InvestmentView readiness card has a real ledger, the value chain and the
announcement timeline belong to P8.  The contract therefore makes every section
carry its own status and its own reason, so a blocked domain degrades one card
instead of collapsing the page — the lesson from PUI-01 and PUI-02.

Status semantics are reused from domain/desk.py rather than redeclared: two
enums for the same four facts would drift.
"""

from __future__ import annotations

import unittest

from a_share_platform.domain.desk import DeskBlocker, DeskSectionStatus
from a_share_platform.domain.security_overview import (
    SECTION_ORDER,
    SecurityOverviewProjection,
    SecurityOverviewSection,
    SecurityOverviewSectionKey,
)

SECURITY = "security:CN:600519:XSHG"


def blocker(code: str = "P8_VALUE_CHAIN_NOT_IMPLEMENTED") -> DeskBlocker:
    return DeskBlocker(
        code=code,
        reason="产业链证据链属 P8 事件与文档管道，尚未实现。",
        affected_binding="security.value_chain",
        evidence_ids=(),
    )


def section(
    key: SecurityOverviewSectionKey = SecurityOverviewSectionKey.COMPANY_PROFILE,
    status: DeskSectionStatus = DeskSectionStatus.UNAVAILABLE,
    *,
    blockers: tuple[DeskBlocker, ...] = (blocker(),),
    coverage: dict[str, object] | None = None,
    payload: object | None = None,
) -> SecurityOverviewSection:
    return SecurityOverviewSection(
        key=key,
        status=status,
        title="公司画像与价值链定位",
        blockers=blockers,
        coverage=dict(coverage or {}),
        payload=payload,
    )


class SectionContractTest(unittest.TestCase):
    def test_unavailable_section_must_declare_a_blocker(self) -> None:
        with self.assertRaises(ValueError):
            section(blockers=())

    def test_partial_section_must_declare_coverage_or_a_blocker(self) -> None:
        """A bare "partial" tells the operator nothing actionable."""
        with self.assertRaises(ValueError):
            SecurityOverviewSection(
                key=SecurityOverviewSectionKey.FINANCIAL_TRAJECTORY,
                status=DeskSectionStatus.PARTIAL,
                title="财务轨迹 · 5Y（可追溯摘要）",
                blockers=(),
                coverage={},
                payload={"years": []},
            )

    def test_unavailable_section_must_not_carry_a_payload(self) -> None:
        """A payload under an unavailable status is how fixtures leak in."""
        with self.assertRaises(ValueError):
            section(payload={"core_business": "高端白酒"})

    def test_ready_section_requires_a_payload(self) -> None:
        with self.assertRaises(ValueError):
            section(status=DeskSectionStatus.READY, blockers=(), payload=None)


class ProjectionContractTest(unittest.TestCase):
    def all_sections(self) -> tuple[SecurityOverviewSection, ...]:
        return tuple(
            SecurityOverviewSection(
                key=key,
                status=DeskSectionStatus.UNAVAILABLE,
                title=key.value,
                blockers=(blocker(f"SECTION_{key.value.upper()}_UNAVAILABLE"),),
            )
            for key in SECTION_ORDER
        )

    def test_projection_carries_every_section_in_prototype_order(self) -> None:
        projection = SecurityOverviewProjection(
            security_id=SECURITY,
            sections=tuple(reversed(self.all_sections())),
        )
        self.assertEqual(
            tuple(item.key for item in projection.sections),
            SECTION_ORDER,
        )

    def test_a_missing_section_fails_rather_than_silently_shrinking_the_page(self) -> None:
        """A page that quietly loses a card reads as "nothing to report"."""
        with self.assertRaises(ValueError):
            SecurityOverviewProjection(
                security_id=SECURITY,
                sections=self.all_sections()[:-1],
            )

    def test_duplicate_sections_are_refused(self) -> None:
        sections = self.all_sections()
        with self.assertRaises(ValueError):
            SecurityOverviewProjection(
                security_id=SECURITY,
                sections=sections + (sections[0],),
            )

    def test_empty_security_id_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            SecurityOverviewProjection(security_id="  ", sections=self.all_sections())
```

- [ ] **Step 3: 运行并记录真实红测原因**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_security_overview_domain -v`

Expected: FAIL —— `ModuleNotFoundError: No module named 'a_share_platform.domain.security_overview'`。
把真实错误文本抄进 Evidence。

- [ ] **Step 4: 最小实现**

按 `domain/desk.py` 的结构实现 `security_overview.py`：`StrEnum` + 两个 frozen dataclass +
`__post_init__` 校验。**从 `domain.desk` 导入 `DeskSectionStatus` 与 `DeskBlocker`**，
不复制粘贴。`SECTION_ORDER` 按 Figma 版式顺序：`DECISION_BRIEF`、`VIEW_READINESS`、
`COMPANY_PROFILE`、`CATALYSTS`、`FINANCIAL_TRAJECTORY`、`QUALITY_SCORE`、
`VALUATION_SCENARIOS`、`INDUSTRY_PEERS`、`TRACKING_PLAN`、`SECURITY_FEEDS`。

- [ ] **Step 5: 运行定向测试转绿**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_security_overview_domain -v`
Expected: PASS，8 个测试全过。

- [ ] **Step 6: 静态检查并提交**

```bash
cd platform
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/domain/security_overview.py \
  platform/tests/test_security_overview_domain.py
git commit -m "feat: add the security fused-overview section contract

The 1900 px fused overview mixes ten domains at very different maturities: the
InvestmentView readiness card reads a real ledger while the value chain and the
announcement timeline belong to P8.  A single page-level status would collapse
the whole layout the moment one of them is missing, which is exactly the failure
PUI-01 and PUI-02 had to fix twice.

Status semantics are imported from domain/desk.py rather than redeclared, so the
four data facts cannot drift into two definitions.  The section set is fixed at
ten: a section reports unavailable, it never disappears, because a page that
quietly loses a card reads as nothing to report."
```

---

### Task 2: Security 融合总览投影服务

分区骨架有了，现在按真实账本填充。**只读已有账本**：`ExpectedReturnLedgerRepository`（View）、
`SignalSnapshotRepository`（Screen 与同业）、`SecurityMaster`（身份与行业）。
没有账本的分区返回 `unavailable` + 阶段 blocker，**不生成演示公司画像或财务数字**。

**Files:**
- Create: `platform/src/a_share_platform/application/security_overview_projection.py`
- Test: `platform/tests/test_security_overview_projection.py`

**Interfaces:**
- Consumes:
  - `ports/expected_return.py` 的 `ExpectedReturnLedgerRepository.list_views()`
  - `ports/signals.py` 的 `SignalSnapshotRepository`
  - `domain/security_master.py` 的 `SecurityMaster.snapshots(as_of: date)`
  - `application/research_workspace.py` 的 `ResearchWorkspaceProjectionService`（复用其 `_identity` 语义，不重写身份解析）
- Produces:
  ```python
  class SecurityOverviewProjectionService:
      def __init__(self, *, expected_return_repository, signal_snapshot_repository,
                   security_master) -> None: ...
      def project(self, *, security_query: str | None, now: datetime
                  ) -> SecurityOverviewProjection
  ```

- [ ] **Step 1: 读现有投影服务的账本失败处理**

Run:
```bash
cd platform
grep -n "ExpectedReturnLedgerUnavailable\|SignalSnapshotLedgerUnavailable" -A 10 \
  src/a_share_platform/application/research_workspace.py | head -30
grep -n "def _identity" -A 28 src/a_share_platform/application/research_workspace.py
```

`ResearchWorkspaceProjectionService.project()` 捕获自己的 repository 异常并转为 blocker，
不向上抛。**照抄这个模式** —— desk 投影已经依赖它（`_store_unavailable_blockers`
按 `code.endswith("_store_unavailable")` 识别）。

- [ ] **Step 2: 写失败测试 —— 账本不可用时的分区隔离**

```python
# platform/tests/test_security_overview_projection.py
"""Fused-overview projection over the real P5 ledgers.

Two properties make it trustworthy: an unreachable ledger degrades only the
sections that need it, and no section ever invents the company profile,
financial trajectory or peer comparison that the Figma page shows as sample
values.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from a_share_platform.adapters.memory.expected_return import (
    InMemoryExpectedReturnLedgerRepository,
)
from a_share_platform.adapters.memory.signals import InMemorySignalSnapshotRepository
from a_share_platform.application.security_overview_projection import (
    SecurityOverviewProjectionService,
)
from a_share_platform.application.signal_snapshots import SignalSnapshotLedgerService
from a_share_platform.domain.desk import DeskSectionStatus
from a_share_platform.domain.factor_lifecycle import ApprovalScope
from a_share_platform.domain.security_master import SecurityMaster
from a_share_platform.domain.security_overview import (
    SECTION_ORDER,
    SecurityOverviewSectionKey,
)
from a_share_platform.ports.expected_return import ExpectedReturnLedgerUnavailable
from tests.test_signal_snapshot_ledger import snapshot_for
from tests.test_signal_snapshots import investment_view

NOW = datetime(2026, 8, 16, 1, 30, tzinfo=UTC)


class FailingViewLedger:
    """A ledger that is configured but unreachable."""

    def list_views(self):
        raise ExpectedReturnLedgerUnavailable("expected return ledger is not configured")


class SectionIsolationTest(unittest.TestCase):
    def service(self, *, views=None, signals=None) -> SecurityOverviewProjectionService:
        return SecurityOverviewProjectionService(
            expected_return_repository=views or InMemoryExpectedReturnLedgerRepository(),
            signal_snapshot_repository=signals or InMemorySignalSnapshotRepository(),
            security_master=SecurityMaster.empty(),
        )

    def test_projection_always_carries_all_ten_sections(self) -> None:
        projection = self.service().project(security_query=None, now=NOW)
        self.assertEqual(tuple(item.key for item in projection.sections), SECTION_ORDER)

    def test_unreachable_view_ledger_blocks_only_the_view_sections(self) -> None:
        projection = self.service(views=FailingViewLedger()).project(
            security_query=None, now=NOW
        )
        readiness = next(
            item for item in projection.sections
            if item.key is SecurityOverviewSectionKey.VIEW_READINESS
        )
        self.assertEqual(readiness.status, DeskSectionStatus.UNAVAILABLE)
        codes = {blocker.code for blocker in readiness.blockers}
        self.assertTrue(any(code.endswith("_store_unavailable") for code in codes))
        # The value chain does not depend on the view ledger, so its reason must
        # be its own phase blocker rather than the ledger failure.
        profile = next(
            item for item in projection.sections
            if item.key is SecurityOverviewSectionKey.COMPANY_PROFILE
        )
        self.assertNotIn("expected return ledger", " ".join(
            blocker.reason for blocker in profile.blockers
        ))

    def test_no_section_invents_the_figma_sample_values(self) -> None:
        """1,505.6 / 747.3 / 30.2% / 32.4x are DESIGN FIXTURE, not data."""
        projection = self.service().project(security_query=None, now=NOW)
        rendered = repr(projection)
        for fixture in ("1,505.6", "747.3", "32.4x", "18.2x", "1856.20", "五粮液"):
            self.assertNotIn(fixture, rendered)

    def test_unimplemented_domains_report_their_owning_phase(self) -> None:
        projection = self.service().project(security_query=None, now=NOW)
        feeds = next(
            item for item in projection.sections
            if item.key is SecurityOverviewSectionKey.SECURITY_FEEDS
        )
        self.assertEqual(feeds.status, DeskSectionStatus.UNAVAILABLE)
        self.assertTrue(any("P8" in blocker.code for blocker in feeds.blockers))


class ReadySectionTest(unittest.TestCase):
    def test_view_readiness_reports_the_frozen_view_status_unchanged(self) -> None:
        views = InMemoryExpectedReturnLedgerRepository()
        signals = InMemorySignalSnapshotRepository()
        view = investment_view()
        views.append_view(view)
        SignalSnapshotLedgerService(signals).record_snapshot(
            snapshot_for(ApprovalScope.RESEARCH_BACKTEST)
        )
        service = SecurityOverviewProjectionService(
            expected_return_repository=views,
            signal_snapshot_repository=signals,
            security_master=SecurityMaster.empty(),
        )

        projection = service.project(security_query=view.security_id, now=NOW)

        readiness = next(
            item for item in projection.sections
            if item.key is SecurityOverviewSectionKey.VIEW_READINESS
        )
        self.assertIn(readiness.status, (DeskSectionStatus.READY, DeskSectionStatus.PARTIAL))
        self.assertEqual(readiness.payload["view_id"], view.view_id)
        # Component statuses pass through: a constrained component must not be
        # rendered as quantified, and none may be shown as zero.
        statuses = {item["status"] for item in readiness.payload["components"]}
        self.assertTrue(statuses.issubset(
            {"quantified", "constrained", "unavailable", "not_applicable"}
        ))

    def test_industry_peers_come_from_snapshots_not_from_a_static_list(self) -> None:
        """Peer rows must be traceable to a frozen snapshot id."""
        views = InMemoryExpectedReturnLedgerRepository()
        signals = InMemorySignalSnapshotRepository()
        views.append_view(investment_view())
        SignalSnapshotLedgerService(signals).record_snapshot(
            snapshot_for(ApprovalScope.RESEARCH_BACKTEST)
        )
        service = SecurityOverviewProjectionService(
            expected_return_repository=views,
            signal_snapshot_repository=signals,
            security_master=SecurityMaster.empty(),
        )

        projection = service.project(security_query=None, now=NOW)

        peers = next(
            item for item in projection.sections
            if item.key is SecurityOverviewSectionKey.INDUSTRY_PEERS
        )
        if peers.status in (DeskSectionStatus.READY, DeskSectionStatus.PARTIAL):
            for row in peers.payload["peers"]:
                self.assertTrue(row["snapshot_id"])
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_security_overview_projection -v`
Expected: FAIL —— `application.security_overview_projection` 不存在。

- [ ] **Step 4: 最小实现 —— 先只做全 unavailable 的十分区**

十个分区全部返回 `UNAVAILABLE` + 各自 blocker，让 `test_projection_always_carries_all_ten_sections`
与 `test_unimplemented_domains_report_their_owning_phase` 转绿。**不要一次实现所有分区的数据**。

各分区的 blocker code 与归属阶段：

| 分区 | blocker code | 归属 |
|---|---|---|
| `decision_brief` | `P5_DECISION_BRIEF_SOURCE_UNAVAILABLE` | 需人工研究命题源，无账本 |
| `view_readiness` | `investment_view_store_unavailable` / `investment_view_unavailable` | P5，有账本 |
| `company_profile` | `P8_VALUE_CHAIN_NOT_IMPLEMENTED` | P8 |
| `catalysts` | 来自 View 的 `catalysts`/`invalidators` | P5，有账本 |
| `financial_trajectory` | `P2_QUARTERLY_FINANCIALS_UNAVAILABLE` | P2，仅年末 current |
| `quality_score` | `P4_FACTOR_QUALIFICATION_FAILED` | P4 |
| `valuation_scenarios` | `P5_VALUATION_SCENARIO_INPUTS_UNAVAILABLE` | P5 |
| `industry_peers` | `research_signal_snapshot_unavailable` | P5，有账本 |
| `tracking_plan` | `P8_RESEARCH_CASE_NOT_IMPLEMENTED` | P8 |
| `security_feeds` | `P8_EVENT_FEED_NOT_IMPLEMENTED` | P8 |

- [ ] **Step 5: 逐分区接真实账本（每个分区先红测再实现）**

顺序：`view_readiness` → `catalysts` → `industry_peers`。这三个有真实账本，其余七个保持
`unavailable`。每个分区至少覆盖：

- 账本可读且有对象 → `ready`，payload 字段与 View/Snapshot **完全一致**
- 账本可读但无匹配对象 → `empty`，无 payload
- 账本不可读 → `unavailable` + `*_store_unavailable` blocker
- component 的 `constrained` / `unavailable` **原样透传**，不改写为 `quantified`，不填 0

- [ ] **Step 6: 转绿并全量验证**

Run:
```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest tests.test_security_overview_projection -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
```

- [ ] **Step 7: 提交**

```bash
cd .. && git add platform/src/a_share_platform/application/security_overview_projection.py \
  platform/tests/test_security_overview_projection.py
git commit -m "feat: project the security fused overview from the real P5 ledgers

Three of the ten sections have a ledger behind them today — InvestmentView
readiness, catalysts and industry peers — and they read it directly.  The other
seven report the phase that owns them: the value chain and the announcement
timeline are P8, quarterly financials are P2, the quality score waits on the P4
qualification gate.

An unreachable ledger degrades only the sections that need it.  Nothing fills a
gap with the Figma sample values: 1,505.6 revenue, 32.4x PE and the 五粮液 peer
row are design fixtures, and a test asserts they never appear in a projection."
```

---

### Task 3: Security 融合总览 API 端点与 schema

投影服务要经 API 暴露。复用既有 `Envelope` / `ResponseContext` / `fixed_read_context`，
schema 用 `StrictResponse`（`extra="forbid"`），**不新建第二套 envelope**。

**Files:**
- Modify: `platform/src/a_share_platform/api/schemas.py`
- Modify: `platform/src/a_share_platform/api/app.py`
- Test: `platform/tests/test_security_overview_api.py`

**Interfaces:**
- Consumes: Task 2 的 `SecurityOverviewProjectionService.project()`、既有 `fixed_read_context`
- Produces:
  ```python
  # api/schemas.py
  SecurityOverviewSectionKeyLiteral = Literal[
      "decision_brief", "view_readiness", "company_profile", "catalysts",
      "financial_trajectory", "quality_score", "valuation_scenarios",
      "industry_peers", "tracking_plan", "security_feeds",
  ]

  class SecurityOverviewSectionProjection(StrictResponse):
      key: SecurityOverviewSectionKeyLiteral
      status: Literal["ready", "partial", "empty", "unavailable"]
      title: str
      blockers: list[ResearchWorkspaceBlocker]
      coverage: dict[str, JsonValue]
      payload: JsonValue | None

  class SecurityOverviewData(StrictResponse):
      security_id: str
      sections: list[SecurityOverviewSectionProjection]

  class SecurityOverviewEnvelope(StrictResponse):
      data: SecurityOverviewData
      context: ResponseContext
  ```
- Produces: `GET /api/research/security-overview?security_id=<optional>`

- [ ] **Step 1: 读 desk 端点如何把领域投影转成 envelope**

Run:
```bash
cd platform
grep -n '@app.get("/api/desk"' -A 30 src/a_share_platform/api/app.py
grep -n "class DeskSectionProjection" -A 20 src/a_share_platform/api/schemas.py
```

`/api/desk` 的模式是：`asdict(blocker)` + `section.key.value` + `section.status.value`，
然后 `DeskEnvelope.model_validate(response.model_dump())`。**照抄**。

- [ ] **Step 2: 写失败测试**

```python
# platform/tests/test_security_overview_api.py
"""GET /api/research/security-overview.

An unconfigured runtime must answer 200 with an honest ten-section skeleton, not
404 and not a fabricated company.  The strict schema is the second line of
defence: an extra field would mean the projection grew a value the contract never
agreed to serve.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from a_share_platform.adapters.memory.expected_return import (
    InMemoryExpectedReturnLedgerRepository,
)
from a_share_platform.adapters.memory.signals import InMemorySignalSnapshotRepository
from a_share_platform.api.app import create_app
from a_share_platform.application.signal_snapshots import SignalSnapshotLedgerService
from a_share_platform.domain.factor_lifecycle import ApprovalScope
from tests.test_signal_snapshot_ledger import snapshot_for
from tests.test_signal_snapshots import investment_view

EXPECTED_KEYS = [
    "decision_brief",
    "view_readiness",
    "company_profile",
    "catalysts",
    "financial_trajectory",
    "quality_score",
    "valuation_scenarios",
    "industry_peers",
    "tracking_plan",
    "security_feeds",
]


class SecurityOverviewApiTest(unittest.TestCase):
    def test_unconfigured_runtime_returns_ten_honest_sections(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = TestClient(create_app())

        response = client.get("/api/research/security-overview")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            [item["key"] for item in payload["data"]["sections"]],
            EXPECTED_KEYS,
        )
        for section in payload["data"]["sections"]:
            if section["status"] in ("unavailable", "empty"):
                self.assertIsNone(section["payload"])
            if section["status"] == "unavailable":
                self.assertTrue(section["blockers"])
        self.assertEqual(payload["context"]["data_mode"], "current_research")
        self.assertEqual(payload["context"]["deployment_stage"], "research")

    def test_run_context_cannot_be_promoted_by_query_parameters(self) -> None:
        """The one request that would silently turn current data into PIT."""
        with patch.dict(os.environ, {}, clear=True):
            client = TestClient(create_app())

        response = client.get(
            "/api/research/security-overview",
            params={"data_mode": "strict_historical"},
        )

        self.assertEqual(response.status_code, 403)

    def test_unknown_security_keeps_the_skeleton_instead_of_404(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = TestClient(create_app())

        response = client.get(
            "/api/research/security-overview",
            params={"security_id": "security:CN:000001:XSHE"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]["sections"]), 10)

    def test_bound_view_surfaces_its_exact_view_id(self) -> None:
        views = InMemoryExpectedReturnLedgerRepository()
        signals = InMemorySignalSnapshotRepository()
        view = investment_view()
        views.append_view(view)
        SignalSnapshotLedgerService(signals).record_snapshot(
            snapshot_for(ApprovalScope.RESEARCH_BACKTEST)
        )
        client = TestClient(
            create_app(
                expected_return_repository=views,
                signal_snapshot_repository=signals,
            )
        )

        response = client.get(
            "/api/research/security-overview",
            params={"security_id": view.security_id},
        )

        self.assertEqual(response.status_code, 200)
        readiness = next(
            item for item in response.json()["data"]["sections"]
            if item["key"] == "view_readiness"
        )
        self.assertEqual(readiness["payload"]["view_id"], view.view_id)
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_security_overview_api -v`
Expected: FAIL —— 第一个测试拿到 404，因为端点不存在。

- [ ] **Step 4: 实现 schema 与端点 → 转绿**

在 `create_app()` 中新建 `SecurityOverviewProjectionService`，复用已解析的
`expected_return_repository` / `signal_snapshot_repository` / `master`，**不要第二次
从 DSN 构造 repository**。

- [ ] **Step 5: 重新生成前端类型**

```bash
cd platform/frontend
PYTHON_BIN=../.venv/bin/python npm run generate:api
git diff --stat src/api/
```

Expected: `openapi.json` 与 `schema.d.ts` 出现新路径 `/api/research/security-overview`。
`export_openapi.py` 按 GET 路径自动生成 `ReadOperation` 条目，无需手改脚本。

- [ ] **Step 6: 全量后端验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/api/schemas.py \
  platform/src/a_share_platform/api/app.py \
  platform/tests/test_security_overview_api.py \
  platform/frontend/src/api/openapi.json platform/frontend/src/api/schema.d.ts
git commit -m "feat: serve the security fused overview as a ten-section projection

An unconfigured runtime answers 200 with the honest skeleton rather than 404: the
operator needs to see which ten domains exist and why nine of them are blocked,
and a 404 would read as "no such security".

The strict schema is the second line of defence.  An extra field would mean the
projection started serving a value the contract never agreed to, which is how a
design fixture reaches a product surface.  Query parameters still cannot promote
the run context — that request is the one that would silently turn current data
into PIT."
```

---

### Task 4: Security 融合总览前端 —— 拆成聚焦组件

1900 px、10 个分区不能写成一个文件。按 Figma 的纵段拆成 6 个组件 + 1 个页面容器，
每个组件只吃自己那个分区的 `SecurityOverviewSection`，状态解析全部走已验证的
`DeskSection` + `deskState.ts`。

**Files:**
- Create: `platform/frontend/src/features/security-overview/securityOverviewProjection.ts`
- Create: `platform/frontend/src/features/security-overview/SecurityOverviewSection.tsx`
- Create: `platform/frontend/src/features/security-overview/DecisionBriefCard.tsx`
- Create: `platform/frontend/src/features/security-overview/ViewReadinessCard.tsx`
- Create: `platform/frontend/src/features/security-overview/CompanyProfileCard.tsx`
- Create: `platform/frontend/src/features/security-overview/CatalystInvalidatorCard.tsx`
- Create: `platform/frontend/src/features/security-overview/FinancialTrajectoryCard.tsx`
- Create: `platform/frontend/src/features/security-overview/PeerComparisonCard.tsx`
- Create: `platform/frontend/src/features/security-overview/securityOverview.less`
- Create: `platform/frontend/src/pages/SecurityOverviewScreen.tsx`
- Test: `platform/frontend/src/features/security-overview/SecurityOverviewSection.test.tsx`
- Test: `platform/frontend/src/features/security-overview/ViewReadinessCard.test.tsx`
- Test: `platform/frontend/src/pages/SecurityOverviewScreen.test.tsx`
- Modify: `platform/frontend/src/api/client.ts`（新增 `getSecurityOverview`）

**Interfaces:**
- Consumes: Task 3 的 `GET /api/research/security-overview`、既有 `WorkspaceState`、`resolveSectionState`、`noticeReason`
- Produces:
  ```ts
  // securityOverviewProjection.ts
  export type SecurityOverviewSectionKey =
    | 'decision_brief' | 'view_readiness' | 'company_profile' | 'catalysts'
    | 'financial_trajectory' | 'quality_score' | 'valuation_scenarios'
    | 'industry_peers' | 'tracking_plan' | 'security_feeds'

  export interface SecurityOverviewSectionData {
    key: SecurityOverviewSectionKey
    status: 'ready' | 'partial' | 'empty' | 'unavailable'
    title: string
    blockers: ResearchWorkspaceBlocker[]
    coverage: Record<string, unknown>
    payload: unknown
  }

  export interface SecurityOverviewData {
    security_id: string
    sections: SecurityOverviewSectionData[]
  }

  // client.ts
  export function getSecurityOverview(securityId?: string, signal?: AbortSignal):
    Promise<Envelope<SecurityOverviewData>>
  ```

- [ ] **Step 1: 读 DeskSection 的 props 与 DeskPage 的缺分区兜底**

Run:
```bash
cd platform/frontend
grep -n "interface DeskSectionProps" -A 14 src/features/desk/DeskSection.tsx
grep -n "function sectionFor" -A 20 src/pages/DeskPage.tsx
```

`sectionFor()` 在服务端漏返回某分区时构造一个 `unavailable` + `DESK_SECTION_MISSING` 兜底。
**照抄这个模式**：融合页有 10 个分区，任何一个漏掉都必须显式 unavailable，而不是少一张卡。

- [ ] **Step 2: 写失败测试 —— 分区壳与缺分区兜底**

```tsx
// platform/frontend/src/features/security-overview/SecurityOverviewSection.test.tsx
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { SecurityOverviewSection } from './SecurityOverviewSection'
import type { SecurityOverviewSectionData } from './securityOverviewProjection'

function section(
  overrides: Partial<SecurityOverviewSectionData> = {},
): SecurityOverviewSectionData {
  return {
    key: 'company_profile',
    status: 'unavailable',
    title: '公司画像与价值链定位',
    blockers: [{
      code: 'P8_VALUE_CHAIN_NOT_IMPLEMENTED',
      reason: '产业链证据链属 P8 事件与文档管道，尚未实现。',
      affected_binding: 'security.value_chain',
      evidence_ids: [],
    }],
    coverage: {},
    payload: null,
    ...overrides,
  }
}

describe('SecurityOverviewSection', () => {
  afterEach(cleanup)

  it('names the region after the server title so the layout survives a blocker', () => {
    render(<SecurityOverviewSection section={section()} />)
    expect(screen.getByRole('region', { name: '公司画像与价值链定位' })).toBeInTheDocument()
  })

  it('renders the blocker code, reason and affected binding', () => {
    render(<SecurityOverviewSection section={section()} />)
    expect(screen.getByText('P8_VALUE_CHAIN_NOT_IMPLEMENTED')).toBeInTheDocument()
    expect(screen.getByText(/产业链证据链属 P8/)).toBeInTheDocument()
    expect(screen.getByText('security.value_chain')).toBeInTheDocument()
  })

  it('never substitutes the Figma sample profile for a missing one', () => {
    render(<SecurityOverviewSection section={section()} />)
    expect(screen.queryByText('高端白酒 / 茅台酒')).not.toBeInTheDocument()
    expect(screen.queryByText('品牌方 · 渠道定价锚')).not.toBeInTheDocument()
  })

  it('shows partial content beside the coverage gap rather than hiding it', () => {
    render(
      <SecurityOverviewSection
        section={section({
          key: 'financial_trajectory',
          status: 'partial',
          title: '财务轨迹 · 5Y（可追溯摘要）',
          coverage: { years_available: 8, quarters_available: 0 },
          payload: { years: [] },
        })}
      >
        <span>真实局部内容</span>
      </SecurityOverviewSection>,
    )
    expect(screen.getByText('真实局部内容')).toBeInTheDocument()
    expect(screen.getByText(/years_available/)).toBeInTheDocument()
  })

  it('distinguishes empty from unavailable', () => {
    render(<SecurityOverviewSection section={section({ status: 'empty', blockers: [] })} />)
    expect(screen.getByText('暂无记录')).toBeInTheDocument()
    expect(screen.queryByText('能力未启用')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform/frontend && npm test -- --run src/features/security-overview/SecurityOverviewSection.test.tsx`
Expected: FAIL —— `Failed to resolve import "./SecurityOverviewSection"`。

- [ ] **Step 4: 实现分区壳 → 转绿**

`SecurityOverviewSection.tsx` 是 `DeskSection.tsx` 的同构体：调用 `resolveSectionState` 与
`noticeReason`（从 `../desk/deskState` 导入，**不复制**），渲染 `WorkspaceState` +
blocker 列表 + coverage 行。类型用 `securityOverviewProjection.ts` 的本地类型，
不依赖 desk 的 `DeskSectionKey`。

- [ ] **Step 5: 写 ViewReadinessCard 红测（唯一有真实数据的卡）**

```tsx
// platform/frontend/src/features/security-overview/ViewReadinessCard.test.tsx
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ViewReadinessCard } from './ViewReadinessCard'
import type { SecurityOverviewSectionData } from './securityOverviewProjection'

/**
 * Component statuses come from the server unchanged.  The card must render a
 * constrained dimension as an em dash with its own label — never as a zero and
 * never promoted to quantified.
 */
const readySection: SecurityOverviewSectionData = {
  key: 'view_readiness',
  status: 'partial',
  title: 'InvestmentView 就绪度',
  blockers: [{
    code: 'P5_EVENT_COMPONENT_UNAVAILABLE',
    reason: '事件影响链属 P8，未实施；不得用 0 表示没有影响。',
    affected_binding: 'investment_view.component.event',
    evidence_ids: [],
  }],
  coverage: { components_quantified: 2, components_total: 4 },
  payload: {
    view_id: 'investment-view:600519:v1',
    view_status: 'partial',
    horizon: '60D',
    components: [
      { component: 'quality', label: '公司质量', status: 'quantified', display: '+2.1%' },
      { component: 'valuation', label: '估值预期差', status: 'quantified', display: '+3.1%' },
      { component: 'revision', label: '边际改善', status: 'constrained', display: '—' },
      { component: 'event', label: '事件影响', status: 'unavailable', display: '—' },
    ],
    submit_enabled: false,
    submit_disabled_reason: '证据不完整 · 禁止提交',
  },
}

describe('ViewReadinessCard', () => {
  afterEach(cleanup)

  it('shows every component with its own status label', () => {
    render(<ViewReadinessCard section={readySection} />)
    expect(screen.getByText('公司质量')).toBeInTheDocument()
    expect(screen.getByText('+2.1%')).toBeInTheDocument()
    expect(screen.getByText('CONSTRAINED')).toBeInTheDocument()
    expect(screen.getByText('UNAVAILABLE')).toBeInTheDocument()
  })

  it('renders a non-quantified component as an em dash, never as zero', () => {
    render(<ViewReadinessCard section={readySection} />)
    expect(screen.queryByText('0.0%')).not.toBeInTheDocument()
    expect(screen.queryByText('+0.0%')).not.toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2)
  })

  it('disables the submit action with the server reason, not a client guess', () => {
    render(<ViewReadinessCard section={readySection} />)
    const submit = screen.getByRole('button', { name: '进入 InvestmentView' })
    expect(submit).not.toBeDisabled()
    expect(screen.getByText('证据不完整 · 禁止提交')).toBeInTheDocument()
  })

  it('keeps the card structure when no view exists at all', () => {
    render(
      <ViewReadinessCard
        section={{
          key: 'view_readiness',
          status: 'unavailable',
          title: 'InvestmentView 就绪度',
          blockers: [{
            code: 'investment_view_unavailable',
            reason: '没有符合当前筛选条件的冻结 InvestmentView；系统不会生成演示收益。',
            affected_binding: 'latest_research_investment_view',
            evidence_ids: [],
          }],
          coverage: {},
          payload: null,
        }}
      />,
    )
    expect(screen.getByRole('region', { name: 'InvestmentView 就绪度' })).toBeInTheDocument()
    expect(screen.getByText(/不会生成演示收益/)).toBeInTheDocument()
    expect(screen.queryByText('+5.9%')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 6: 实现 ViewReadinessCard → 转绿，再逐卡补齐**

顺序：`ViewReadinessCard` → `CatalystInvalidatorCard` → `PeerComparisonCard` →
`DecisionBriefCard` → `CompanyProfileCard` → `FinancialTrajectoryCard`。
每卡先红测再实现。后三张当前必然是 `unavailable`，因此测试重点是
**结构在无数据时不塌**，且不出现对应的 Figma 示例值。

- [ ] **Step 7: 写页面容器红测（十分区骨架 + 缺分区兜底）**

```tsx
// platform/frontend/src/pages/SecurityOverviewScreen.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SecurityOverviewScreen } from './SecurityOverviewScreen'

function envelope(sections: unknown[]) {
  return {
    ok: true,
    status: 200,
    json: async () => ({
      data: { security_id: 'security:CN:600519:XSHG', sections },
      context: {
        as_of: '2026-08-16T01:30:00Z',
        system_as_of: '2026-08-16T01:30:00Z',
        data_mode: 'current_research',
        deployment_stage: 'research',
        trust_state: null,
        dataset_version_ids: [],
        model_version_ids: [],
        run_id: null,
        coverage: {},
        warnings: [],
      },
    }),
  } as Response
}

function unavailableSection(key: string, title: string) {
  return {
    key,
    status: 'unavailable',
    title,
    blockers: [{
      code: `SECTION_${key.toUpperCase()}_UNAVAILABLE`,
      reason: '该分区所依赖的能力尚未实现。',
      affected_binding: `security.${key}`,
      evidence_ids: [],
    }],
    coverage: {},
    payload: null,
  }
}

const TEN = [
  ['decision_brief', 'DECISION BRIEF · CORE CONTRADICTION'],
  ['view_readiness', 'InvestmentView 就绪度'],
  ['company_profile', '公司画像与价值链定位'],
  ['catalysts', 'Catalysts / Invalidators / 证据变化'],
  ['financial_trajectory', '财务轨迹 · 5Y（可追溯摘要）'],
  ['quality_score', '公司质地评分 · 与交易评分分离'],
  ['valuation_scenarios', '估值预期差与情景区间'],
  ['industry_peers', '行业同业对比 · Peer Analysis'],
  ['tracking_plan', '跟踪计划 · 从静态研报到持续 Research Case'],
  ['security_feeds', '最新公告与证据时间线 · Security Feeds'],
] as const

function renderScreen() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={['/research/security/security:CN:600519:XSHG']}>
        <SecurityOverviewScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SecurityOverviewScreen', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('renders all ten prototype sections even when every one is blocked', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => envelope(
      TEN.map(([key, title]) => unavailableSection(key, title)),
    )))

    renderScreen()

    for (const [, title] of TEN) {
      expect(await screen.findByRole('region', { name: title })).toBeInTheDocument()
    }
  })

  it('shows an explicit unavailable card when the server omits a section', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => envelope(
      TEN.slice(0, 9).map(([key, title]) => unavailableSection(key, title)),
    )))

    renderScreen()

    expect(await screen.findByText('SECURITY_OVERVIEW_SECTION_MISSING')).toBeInTheDocument()
  })

  it('surfaces a request failure without substituting content', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status: 503,
      json: async () => ({ detail: 'security overview store unavailable' }),
    } as Response)))

    renderScreen()

    expect(await screen.findByText(/security overview store unavailable/))
      .toBeInTheDocument()
    expect(screen.queryByText('600519.SH 贵州茅台')).not.toBeInTheDocument()
  })

  it('does not render any Figma design fixture value', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => envelope(
      TEN.map(([key, title]) => unavailableSection(key, title)),
    )))

    renderScreen()
    await screen.findByRole('region', { name: 'InvestmentView 就绪度' })

    for (const fixture of ['¥1,856.20', '1,505.6', '747.3', '32.4x', '五粮液', '18/24']) {
      expect(screen.queryByText(fixture)).not.toBeInTheDocument()
    }
  })
})
```

- [ ] **Step 8: 实现页面容器 → 转绿**

`SecurityOverviewScreen.tsx` 负责：`useQuery` 拉取、`sectionFor()` 兜底、按
`SECTION_ORDER` 渲染 6 个具名卡 + 4 个通用 `SecurityOverviewSection`。
两栏网格在 `securityOverview.less` 中按 Figma 比例声明：

```less
// Figma 24:400 纵段实测：746/402、560/588、746/402、560/588、560/588，gap 20。
// 侧栏 280 px 使主内容为 1160 px（非 Figma 的 1216），因此按比例声明让差异被两栏吸收。
.securityOverviewRow--wide { grid-template-columns: minmax(0, 746fr) minmax(0, 402fr); }
.securityOverviewRow--even { grid-template-columns: minmax(0, 560fr) minmax(0, 588fr); }
@media (max-width: 1280px) { /* 单栏堆叠 */ }
```

- [ ] **Step 9: 接入路由与导航**

在 `app/AppShell.tsx` 新增 `<Route path="/research/security/:securityId" element={<SecurityOverviewScreen />} />`，
并让 `features/screen/ScreenRankingPanel.tsx` 的行点击导航到该路由（PUI-02 遗留项
「行点击进入精确 Security 的上下文传递（依赖 PUI-03）」）。
导航必须保留 Research Time、Data Mode、Deployment Stage、Universe —— 这些在
`state/workspace.ts` 的 store 与 URL search params 中，**不得清空**。

- [ ] **Step 10: 全量前端验证并提交**

```bash
cd platform/frontend
npm test -- --run
npm run lint
npm run build
cd .. && git diff --check
cd .. && git add platform/frontend/src/features/security-overview/ \
  platform/frontend/src/pages/SecurityOverviewScreen.tsx \
  platform/frontend/src/pages/SecurityOverviewScreen.test.tsx \
  platform/frontend/src/api/client.ts \
  platform/frontend/src/app/AppShell.tsx \
  platform/frontend/src/features/screen/ScreenRankingPanel.tsx
git commit -m "feat: build the security fused overview as ten focused section cards

The 1900 px page is decomposed into six named cards and four generic ones rather
than one file, because a single component for ten domains at ten different
maturities would make every future change touch everything.

State resolution is imported from features/desk/deskState.ts, so the six-state
semantics have one implementation.  A section the server omits renders as an
explicit unavailable card: a page that quietly drops a domain reads as nothing to
report, which is the bug PUI-01 fixed and PUI-02 hit again in the builder column.

Ranking rows now navigate to the exact security while keeping research time, data
mode, deployment stage and universe — the PUI-02 follow-up that was waiting on
this route to exist."
```

---

### Task 5: InvestmentView 独立详情路由与期限切换

当前 View 只作为 `ResearchP5Screen section='security'` 的内嵌块存在，没有自己的 URL。
Figma `15:2` 要求：独立页面、期限条（20D/60D/120D）、VIEW STATUS 徽标、
`打开证据` 往返、Frozen Artifact 卡与五段 INPUT/PROCESS/OUTPUT/ACTION/GATE。

**期限切换的关键约束**：`InvestmentView.horizon_trading_days` 只允许 `{20, 60, 120}`
（`domain/investment_view.py` 实测），且每个期限是**独立的冻结对象**。因此期限条
**不是客户端过滤器**，而是「选择另一个已冻结 View」。没有该期限的冻结 View 时，
该期限必须禁用并说明原因，**不得插值或复用 60D 的数字**。

**Files:**
- Create: `platform/frontend/src/pages/InvestmentViewScreen.tsx`
- Create: `platform/frontend/src/features/investment-view/HorizonSelector.tsx`
- Create: `platform/frontend/src/features/investment-view/ViewStatusBadge.tsx`
- Create: `platform/frontend/src/features/investment-view/GoldenPathStages.tsx`
- Test: `platform/frontend/src/features/investment-view/HorizonSelector.test.tsx`
- Test: `platform/frontend/src/pages/InvestmentViewScreen.test.tsx`
- Modify: `platform/frontend/src/app/AppShell.tsx`
- Modify: `platform/frontend/src/features/investment-view/investmentViewSummary.less`

**Interfaces:**
- Consumes: 既有 `InvestmentViewProjection`（`view_id`/`horizon`/`components`/`residual`/`closure`/`versions.artifact_id`）、既有 `InvestmentViewSummary`、`FrozenArtifactPanel`
- Produces:
  ```ts
  export interface HorizonOption {
    horizon: '20D' | '60D' | '120D'
    view_id: string | null            // null = 该期限没有冻结 View
    unavailable_reason: string | null // 服务端给出的原因，客户端不编造
  }

  interface HorizonSelectorProps {
    options: HorizonOption[]
    active: string
    onSelect: (viewId: string) => void
  }
  ```

- [ ] **Step 1: 确认期限的真实约束与投影字段**

Run:
```bash
cd platform
grep -n "horizon_trading_days must be" -B 6 src/a_share_platform/domain/investment_view.py
grep -n '"horizon": f"{value.horizon_trading_days}D"' -B 4 -A 4 \
  src/a_share_platform/application/research_workspace.py
```

投影把 `horizon` 输出为 `"60D"` 形式的字符串。**期限条必须由服务端列出可选项**，
因为客户端不知道哪些期限有冻结 View。若 `ResearchWorkspaceData` 当前只返回单个
`investment_view`，本 Task 需在 Task 3 的端点上追加 `horizon_options` 字段（先写后端红测）。

- [ ] **Step 2: 写 HorizonSelector 失败测试**

```tsx
// platform/frontend/src/features/investment-view/HorizonSelector.test.tsx
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { HorizonSelector } from './HorizonSelector'
import type { HorizonOption } from './HorizonSelector'

/**
 * Each horizon is a separate frozen InvestmentView, not a filter over one.
 * A horizon with no frozen view must be disabled with the server's reason:
 * interpolating it, or reusing the 60D numbers, would fabricate a decision
 * object that was never compiled or hashed.
 */
const options: HorizonOption[] = [
  { horizon: '20D', view_id: null, unavailable_reason: '该期限没有冻结 InvestmentView。' },
  { horizon: '60D', view_id: 'investment-view:600519:60d:v1', unavailable_reason: null },
  { horizon: '120D', view_id: null, unavailable_reason: '该期限没有冻结 InvestmentView。' },
]

describe('HorizonSelector', () => {
  afterEach(cleanup)

  it('offers exactly the three domain-permitted horizons', () => {
    render(<HorizonSelector active="60D" onSelect={vi.fn()} options={options} />)
    expect(screen.getByRole('radio', { name: '20D' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: '60D' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: '120D' })).toBeInTheDocument()
    expect(screen.getAllByRole('radio')).toHaveLength(3)
  })

  it('disables a horizon with no frozen view and states the server reason', () => {
    render(<HorizonSelector active="60D" onSelect={vi.fn()} options={options} />)
    expect(screen.getByRole('radio', { name: '20D' })).toBeDisabled()
    expect(screen.getByRole('radio', { name: '60D' })).not.toBeDisabled()
    expect(screen.getAllByText('该期限没有冻结 InvestmentView。')).toHaveLength(2)
  })

  it('emits the exact frozen view id rather than the horizon label', () => {
    const onSelect = vi.fn()
    render(<HorizonSelector active="20D" onSelect={onSelect} options={options} />)
    screen.getByRole('radio', { name: '60D' }).click()
    expect(onSelect).toHaveBeenCalledWith('investment-view:600519:60d:v1')
  })

  it('never calls onSelect for a horizon without a view', () => {
    const onSelect = vi.fn()
    render(<HorizonSelector active="60D" onSelect={onSelect} options={options} />)
    screen.getByRole('radio', { name: '120D' }).click()
    expect(onSelect).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform/frontend && npm test -- --run src/features/investment-view/HorizonSelector.test.tsx`
Expected: FAIL —— `Failed to resolve import "./HorizonSelector"`。

- [ ] **Step 4: 实现 HorizonSelector → 转绿**

用 AntD `Radio.Group` + `Radio.Button`，`disabled={option.view_id === null}`。
每个禁用项旁边渲染 `unavailable_reason`。**不要用 `title` 属性藏原因** ——
屏幕阅读器与截图验收都读不到。

- [ ] **Step 5: 写页面失败测试**

```tsx
// platform/frontend/src/pages/InvestmentViewScreen.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { InvestmentViewScreen } from './InvestmentViewScreen'

function renderScreen(path = '/research/investment-view/investment-view:600519:v1') {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[path]}>
        <InvestmentViewScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const context = {
  as_of: '2026-08-16T01:30:00Z',
  system_as_of: '2026-08-16T01:30:00Z',
  data_mode: 'current_research',
  deployment_stage: 'research',
  trust_state: null,
  dataset_version_ids: [],
  model_version_ids: [],
  run_id: null,
  coverage: {},
  warnings: [],
}

function response(data: unknown) {
  return { ok: true, status: 200, json: async () => ({ data, context }) } as Response
}

describe('InvestmentViewScreen', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('keeps the prototype structure when no frozen view exists', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({
      status: 'unavailable',
      blockers: [{
        code: 'investment_view_unavailable',
        reason: '没有符合当前筛选条件的冻结 InvestmentView；系统不会生成演示收益。',
        affected_binding: 'latest_research_investment_view',
        evidence_ids: [],
      }],
      screen: null,
      investment_view: null,
      alpha_model: {
        status: 'unavailable',
        requested_scope: 'research_backtest',
        data_mode: 'current_research',
        deployment_stage: 'research',
        checked_at: '2026-08-16T01:30:00Z',
        blocked_reasons: [],
      },
    })))

    renderScreen()

    // The five golden-path stages describe the contract, not the data, so they
    // must survive an unavailable view rather than the page collapsing.
    expect(await screen.findByText('INPUT · 输入')).toBeInTheDocument()
    expect(screen.getByText('PROCESS · 处理')).toBeInTheDocument()
    expect(screen.getByText('OUTPUT · 输出')).toBeInTheDocument()
    expect(screen.getByText('ACTION · 操作')).toBeInTheDocument()
    expect(screen.getByText('GATE · 门禁')).toBeInTheDocument()
    expect(screen.getByText(/不会生成演示收益/)).toBeInTheDocument()
    expect(screen.queryByText('+5.9%')).not.toBeInTheDocument()
  })

  it('shows the server view status verbatim rather than deriving it', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({
      status: 'partial',
      blockers: [],
      screen: null,
      investment_view: {
        view_id: 'investment-view:600519:v1',
        security: {
          security_id: 'security:CN:600519:XSHG',
          symbol: '600519',
          exchange: 'XSHG',
          display_name: '贵州茅台',
        },
        decision_time: '2026-08-13T07:30:00Z',
        horizon: '60D',
        data_mode: 'current_research',
        trust_state: 'normalized_current',
        trust_reason: '可信但非 PIT 验证',
        distribution: {
          point: { raw: '0.059', display: '+5.9%' },
          p10: { raw: '-0.082', display: '-8.2%' },
          p50: { raw: '0.058', display: '+5.8%' },
          p90: { raw: '0.186', display: '+18.6%' },
          downside: { raw: '0.082', display: '8.2%' },
        },
        components: [
          {
            component: 'event',
            label: '事件影响',
            status: 'unavailable',
            contribution: null,
            reason: 'P8 事件影响链尚未实施；不得用 0 表示没有影响。',
            evidence_ids: [],
            visual: null,
          },
        ],
        residual: {
          status: 'quantified',
          contribution: { raw: '0.001', display: '+0.1%' },
          reason: '显式 residual',
          evidence_ids: [],
          visual: null,
        },
        closure: {
          status: 'passed',
          displayed_total: '+5.9%',
          tolerance: '0.0001',
          difference: '0',
          checked_by: 'expected-return-compiler:v0',
        },
        confidence: { raw: '0.61', display: '0.61' },
        catalysts: [],
        invalidators: [],
        evidence: [],
        versions: {
          dataset_version_ids: ['dataset:financial-normalized-current:v3'],
          feature_version_ids: ['formula:quality:v8'],
          model_version_id: 'expected-return-compiler:v0',
          run_id: 'run:iv-20260813-001',
          code_version: '1'.repeat(40),
          environment_id: 'environment:p5:research:v1',
          content_hash: '8'.repeat(64),
          artifact_id: null,
        },
        warnings: [],
      },
      alpha_model: {
        status: 'unavailable',
        requested_scope: 'research_backtest',
        data_mode: 'current_research',
        deployment_stage: 'research',
        checked_at: '2026-08-16T01:30:00Z',
        blocked_reasons: [],
      },
    })))

    renderScreen()

    expect(await screen.findByText('贵州茅台 · 600519')).toBeInTheDocument()
    expect(screen.getByText('可信但非 PIT 验证')).toBeInTheDocument()
    expect(screen.getByText(/不得用 0 表示没有影响/)).toBeInTheDocument()
    // An unavailable component must not render a contribution figure.
    expect(screen.queryByText('+0.0%')).not.toBeInTheDocument()
  })

  it('reports a not-generated artifact without inventing an id', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({
      status: 'unavailable',
      blockers: [],
      screen: null,
      investment_view: null,
      alpha_model: {
        status: 'unavailable',
        requested_scope: 'research_backtest',
        data_mode: 'current_research',
        deployment_stage: 'research',
        checked_at: '2026-08-16T01:30:00Z',
        blocked_reasons: [],
      },
    })))

    renderScreen()

    expect(await screen.findByText(/Frozen Artifact/)).toBeInTheDocument()
    expect(screen.queryByText(/artifact:investment-view/)).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 6: 实现页面 → 转绿**

`InvestmentViewScreen.tsx` 组装：`HorizonSelector` + `ViewStatusBadge` +
既有 `InvestmentViewSummary`（**不重写**）+ `FrozenArtifactPanel` + `GoldenPathStages`。
`GoldenPathStages` 是静态合同文案（Figma `15:2` y=1056 五卡），它描述的是**合同而非数据**，
因此在 unavailable 时也必须渲染。

- [ ] **Step 7: 接入路由并从融合页跳转**

`<Route path="/research/investment-view/:viewId" element={<InvestmentViewScreen />} />`。
Task 4 的 `ViewReadinessCard` 的 `进入 InvestmentView` 按钮导航到此。

- [ ] **Step 8: 全量前端验证并提交**

```bash
cd platform/frontend && npm test -- --run && npm run lint && npm run build
cd ../.. && git add platform/frontend/src/pages/InvestmentViewScreen.tsx \
  platform/frontend/src/pages/InvestmentViewScreen.test.tsx \
  platform/frontend/src/features/investment-view/HorizonSelector.tsx \
  platform/frontend/src/features/investment-view/HorizonSelector.test.tsx \
  platform/frontend/src/features/investment-view/ViewStatusBadge.tsx \
  platform/frontend/src/features/investment-view/GoldenPathStages.tsx \
  platform/frontend/src/features/investment-view/investmentViewSummary.less \
  platform/frontend/src/app/AppShell.tsx
git commit -m "feat: give InvestmentView its own route with a real horizon selector

The view was reachable only as a block inside the security tab, so an operator
could not link to a specific decision object.  It now has its own URL keyed by
view id.

The horizon strip is not a client-side filter.  20D, 60D and 120D are three
separate frozen views — the domain restricts horizon_trading_days to exactly
those three — so a horizon with no compiled view is disabled with the server's
reason next to it.  Interpolating it, or reusing the 60D distribution under a
different label, would fabricate a decision object that was never compiled or
hashed.

The five INPUT/PROCESS/OUTPUT/ACTION/GATE stages describe the contract rather
than the data, so they render even when the view is unavailable."
```

---

### Task 6: Approvals 队列投影与 API（含跨类型的诚实缺口）

Figma `9:883` 的队列有四类对象（Factor / Alpha Model / InvestmentView / Timing），
后端只有 `FactorPromotionReview` 一类，且强制 `factor_lifecycle_status is CANDIDATE`。
本 Task **只投 Factor 一类**，另外三类由服务端声明 `unavailable` + P9 blocker，
**不伪造队列行**。

**Files:**
- Create: `platform/src/a_share_platform/application/approval_queue.py`
- Modify: `platform/src/a_share_platform/api/schemas.py`
- Modify: `platform/src/a_share_platform/api/app.py`
- Test: `platform/tests/test_approval_queue_projection.py`
- Test: `platform/tests/test_approval_queue_api.py`

**Interfaces:**
- Consumes: `ports/factor_reviews.py` 的 `FactorReviewRepository.list_reviews()`、`FactorReviewStoreUnavailable`；`application/permissions.py` 的 `PermissionPolicy`、`Principal`、`Permission.APPROVE_RESEARCH`
- Produces:
  ```python
  class ApprovalQueueProjectionService:
      def __init__(self, *, factor_review_repository,
                   permission_policy: PermissionPolicy | None = None) -> None: ...
      def project(self, *, principal: Principal, now: datetime) -> Projection
      # {
      #   "counts": {"pending": int, "approved_research": int,
      #              "rejected": int, "production": int},
      #   "rows": [ {review_id, object_kind, version, scope, submitted_by,
      #              evidence_status, reviewer, decision, decided_at,
      #              review_hash} ],
      #   "actor": {"subject_id": str, "can_approve_research": bool,
      #             "disabled_reason": str | None},
      #   "unsupported_object_kinds": [ {code, reason, affected_binding} ],
      #   "blockers": [...],
      # }
      ```

- [ ] **Step 1: 读现有 Review 账本与权限门的真实语义**

Run:
```bash
cd platform
grep -n "class FactorPromotionReview" -A 12 src/a_share_platform/domain/factor_reviews.py
grep -n "class PromotionApproval" -A 14 src/a_share_platform/domain/factor_lifecycle.py
grep -n "if principal.subject_id == \"anonymous\"" -A 3 \
  src/a_share_platform/application/permissions.py
```

真实字段：`review_id` / `factor_version_id` / `factor_version_hash` /
`factor_lifecycle_status` / `validation_report_id` / `validation_report_hash` /
`scientific_gate_passed` / `approval` / `content_hash`；
`PromotionApproval` 提供 `scope` / `decision` / `actor_id` / `actor_role` /
`decided_at` / `reason` / `evidence_hashes`。
`PermissionPolicy.allows()` 对 `anonymous` **只放行 `READ_PUBLIC`** —— 这是硬编码短路，
不是角色查表。

- [ ] **Step 2: 写失败测试**

```python
# platform/tests/test_approval_queue_projection.py
"""Approvals queue projection.

Two properties matter.  First, the queue reports only the object kind that has a
ledger — factor promotions — and names the missing three rather than fabricating
rows for them.  Second, the ability to decide is the server's answer, computed
from the identity the server resolved, never inferred from a client flag.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from a_share_platform.adapters.memory.factor_reviews import InMemoryFactorReviewRepository
from a_share_platform.application.approval_queue import ApprovalQueueProjectionService
from a_share_platform.application.permissions import Principal, Role
from a_share_platform.domain.factor_lifecycle import ApprovalScope
from a_share_platform.ports.factor_reviews import FactorReviewStoreUnavailable
from tests.test_signal_snapshots import approved_factor_package

NOW = datetime(2026, 8, 16, 1, 30, tzinfo=UTC)


class FailingReviewStore:
    def list_reviews(self):
        raise FactorReviewStoreUnavailable("factor review ledger is not configured")


class ActorAuthorityTest(unittest.TestCase):
    def service(self, repository=None) -> ApprovalQueueProjectionService:
        return ApprovalQueueProjectionService(
            factor_review_repository=repository or InMemoryFactorReviewRepository(),
        )

    def test_anonymous_cannot_approve_and_the_reason_comes_from_the_server(self) -> None:
        projection = self.service().project(principal=Principal.anonymous(), now=NOW)
        self.assertFalse(projection["actor"]["can_approve_research"])
        self.assertIn("approve_research", projection["actor"]["disabled_reason"])

    def test_a_reviewer_principal_can_approve_research_only(self) -> None:
        reviewer = Principal("user:reviewer-01", frozenset({Role.REVIEWER}))
        projection = self.service().project(principal=reviewer, now=NOW)
        self.assertTrue(projection["actor"]["can_approve_research"])

    def test_a_trader_principal_cannot_approve_research(self) -> None:
        """send_order authority is not review authority."""
        trader = Principal("user:trader-01", frozenset({Role.TRADER}))
        projection = self.service().project(principal=trader, now=NOW)
        self.assertFalse(projection["actor"]["can_approve_research"])


class QueueContentTest(unittest.TestCase):
    def service(self, repository=None) -> ApprovalQueueProjectionService:
        return ApprovalQueueProjectionService(
            factor_review_repository=repository or InMemoryFactorReviewRepository(),
        )

    def test_empty_ledger_yields_zero_counts_not_the_figma_numbers(self) -> None:
        """Pending 7 / Approved 6 / Rejected 4 are DESIGN FIXTURE values."""
        projection = self.service().project(principal=Principal.anonymous(), now=NOW)
        self.assertEqual(
            projection["counts"],
            {"pending": 0, "approved_research": 0, "rejected": 0, "production": 0},
        )
        self.assertEqual(projection["rows"], [])

    def test_unreachable_ledger_is_unavailable_not_empty(self) -> None:
        projection = self.service(FailingReviewStore()).project(
            principal=Principal.anonymous(), now=NOW
        )
        codes = {item["code"] for item in projection["blockers"]}
        self.assertTrue(any(code.endswith("_store_unavailable") for code in codes))

    def test_the_three_unimplemented_object_kinds_are_named_not_faked(self) -> None:
        projection = self.service().project(principal=Principal.anonymous(), now=NOW)
        bindings = {item["affected_binding"] for item in projection["unsupported_object_kinds"]}
        self.assertEqual(
            bindings,
            {"approval.alpha_model", "approval.investment_view", "approval.timing"},
        )
        for row in projection["rows"]:
            self.assertEqual(row["object_kind"], "factor")

    def test_a_real_review_projects_its_exact_hashes_and_scope(self) -> None:
        repository = InMemoryFactorReviewRepository()
        _factor, review = approved_factor_package(ApprovalScope.RESEARCH_BACKTEST)
        repository.save_review(review)

        projection = self.service(repository).project(
            principal=Principal.anonymous(), now=NOW
        )

        self.assertEqual(len(projection["rows"]), 1)
        row = projection["rows"][0]
        self.assertEqual(row["review_id"], review.review_id)
        self.assertEqual(row["version"], review.factor_version_id)
        self.assertEqual(row["scope"], review.approval.scope.value)
        self.assertEqual(row["review_hash"], review.content_hash)
        self.assertEqual(row["submitted_by"], review.approval.actor_id)
        self.assertNotIn("User-1", str(row))
        self.assertNotIn("REV-1500", str(row))

    def test_scope_counts_never_collapse_research_into_production(self) -> None:
        """research_backtest approval is not production readiness."""
        repository = InMemoryFactorReviewRepository()
        _factor, review = approved_factor_package(ApprovalScope.RESEARCH_BACKTEST)
        repository.save_review(review)

        projection = self.service(repository).project(
            principal=Principal.anonymous(), now=NOW
        )

        self.assertEqual(projection["counts"]["approved_research"], 1)
        self.assertEqual(projection["counts"]["production"], 0)
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_approval_queue_projection -v`
Expected: FAIL —— `application.approval_queue` 不存在。

- [ ] **Step 4: 实现投影 → 转绿**

`disabled_reason` 必须由服务端产生，形如
`subject anonymous 未获授予 approve_research 权限，因此无法作出审批决定。`
**不要在前端拼这句话** —— 那会让前端成为权限语义的第二真源。

- [ ] **Step 5: 写 API 红测并实现 `GET /api/approvals`**

```python
# platform/tests/test_approval_queue_api.py
"""GET /api/approvals.

The endpoint answers the queue plus the caller's real authority.  With no trusted
identity provider the caller is anonymous, so it must answer 200 with
can_approve_research false and the reason — not 403, because the operator still
needs to see the queue and why they cannot act on it.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from a_share_platform.adapters.memory.factor_reviews import InMemoryFactorReviewRepository
from a_share_platform.api.app import create_app
from a_share_platform.domain.factor_lifecycle import ApprovalScope
from tests.test_signal_snapshots import approved_factor_package


class ApprovalQueueApiTest(unittest.TestCase):
    def test_anonymous_caller_sees_the_queue_and_the_disabled_reason(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = TestClient(create_app())

        response = client.get("/api/approvals")

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["actor"]["subject_id"], "anonymous")
        self.assertFalse(payload["actor"]["can_approve_research"])
        self.assertIn("approve_research", payload["actor"]["disabled_reason"])

    def test_counts_start_at_zero_rather_than_the_prototype_numbers(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = TestClient(create_app())

        payload = client.get("/api/approvals").json()["data"]

        self.assertEqual(payload["counts"]["pending"], 0)
        self.assertEqual(payload["rows"], [])

    def test_a_header_cannot_grant_review_authority(self) -> None:
        """Headers never create a principal (api/app.py anonymous_principal)."""
        with patch.dict(os.environ, {}, clear=True):
            client = TestClient(create_app())

        response = client.get(
            "/api/approvals",
            headers={"X-Subject-Id": "user:reviewer-01", "X-Roles": "reviewer"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["actor"]["can_approve_research"])

    def test_a_stored_review_appears_with_its_exact_scope(self) -> None:
        repository = InMemoryFactorReviewRepository()
        _factor, review = approved_factor_package(ApprovalScope.RESEARCH_BACKTEST)
        repository.save_review(review)
        client = TestClient(create_app(factor_review_repository=repository))

        payload = client.get("/api/approvals").json()["data"]

        self.assertEqual(len(payload["rows"]), 1)
        self.assertEqual(payload["rows"][0]["scope"], "research_backtest")
```

- [ ] **Step 6: 转绿，重新生成前端类型，全量后端验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest tests.test_approval_queue_api -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd frontend && PYTHON_BIN=../.venv/bin/python npm run generate:api
cd ../.. && git add platform/src/a_share_platform/application/approval_queue.py \
  platform/src/a_share_platform/api/schemas.py platform/src/a_share_platform/api/app.py \
  platform/tests/test_approval_queue_projection.py \
  platform/tests/test_approval_queue_api.py \
  platform/frontend/src/api/openapi.json platform/frontend/src/api/schema.d.ts
git commit -m "feat: project the approvals queue with server-owned decision authority

The prototype queue lists four object kinds; only factor promotion has a ledger
today.  The projection serves that one and names the other three as unavailable
with the phase that owns them, because a fabricated Alpha Model row would imply a
review workflow that does not exist.

Whether the caller may decide is the server's answer, carried as
can_approve_research plus the reason it is false.  With no trusted identity
provider every caller is anonymous, and PermissionPolicy short-circuits anonymous
to read_public — so the honest response is 200 with the queue visible and the
action refused, not 403 that hides the queue entirely.  A header still cannot
create a principal.

research_backtest approval is counted separately from production: collapsing them
would let a research-only approval read as production readiness."
```

---

### Task 7: Approvals 前端页与真实写操作（禁用原因来自服务端）

Figma `9:883` 的四计数卡 + 8 列队列表 + 审批规则栏 + 可信使用边界。
**唯一的真实写操作**：`POST /api/factors/reviews`。当前 anonymous 必然被
`FactorReviewDenied → PermissionDenied` 拒绝，页面必须显示**服务端返回的** 403 detail，
而不是前端猜的文案。

**Files:**
- Create: `platform/frontend/src/features/approvals/approvalQueueProjection.ts`
- Create: `platform/frontend/src/features/approvals/ApprovalCountCards.tsx`
- Create: `platform/frontend/src/features/approvals/ApprovalQueueTable.tsx`
- Create: `platform/frontend/src/features/approvals/ApprovalRulesPanel.tsx`
- Create: `platform/frontend/src/features/approvals/ApprovalDecisionForm.tsx`
- Create: `platform/frontend/src/features/approvals/approvals.less`
- Create: `platform/frontend/src/pages/ApprovalsScreen.tsx`
- Test: `platform/frontend/src/features/approvals/ApprovalDecisionForm.test.tsx`
- Test: `platform/frontend/src/pages/ApprovalsScreen.test.tsx`
- Modify: `platform/frontend/src/api/client.ts`（新增 `getApprovals` 与 `postFactorReview`）
- Modify: `platform/frontend/src/pages/WorkspacePage.tsx`（`approvals` tab 改为渲染 `ApprovalsScreen`）

**Interfaces:**
- Consumes: Task 6 的 `GET /api/approvals`、既有 `POST /api/factors/reviews`、既有 `ApiError`
- Produces:
  ```ts
  export interface ApprovalActor {
    subject_id: string
    can_approve_research: boolean
    disabled_reason: string | null
  }

  export interface ApprovalQueueRow {
    review_id: string
    object_kind: 'factor'
    version: string
    scope: 'research_backtest' | 'shadow' | 'paper' | 'limited_live'
    submitted_by: string
    evidence_status: 'complete' | 'missing'
    reviewer: string | null
    decision: 'approved' | 'rejected' | 'request_changes' | 'pending'
    decided_at: string | null
    review_hash: string
  }

  export interface ApprovalQueueData {
    counts: { pending: number; approved_research: number; rejected: number; production: number }
    rows: ApprovalQueueRow[]
    actor: ApprovalActor
    unsupported_object_kinds: ResearchWorkspaceBlocker[]
    blockers: ResearchWorkspaceBlocker[]
  }

  // client.ts —— 第一个非 GET helper
  export async function postJson<T>(path: string, body: unknown, signal?: AbortSignal):
    Promise<Envelope<T>>
  ```

- [ ] **Step 1: 读服务端拒绝路径的真实响应形状**

Run:
```bash
cd platform
grep -n "except FactorReviewDenied" -A 4 src/a_share_platform/api/app.py
grep -n "PermissionDenied" -A 12 src/a_share_platform/api/app.py | grep -n "exception_handler" -A 12
grep -n "class ProblemDetails" -A 8 src/a_share_platform/api/schemas.py
```

拒绝返回 `ProblemDetails`（`type`/`title`/`status`/`detail`/`instance`），
前端 `getEnvelope` 已用 `payload.detail` 构造 `ApiError`。`postJson` 必须**照抄**同一处理。

- [ ] **Step 2: 写 ApprovalDecisionForm 失败测试**

```tsx
// platform/frontend/src/features/approvals/ApprovalDecisionForm.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApprovalDecisionForm } from './ApprovalDecisionForm'
import type { ApprovalActor, ApprovalQueueRow } from './approvalQueueProjection'

const row: ApprovalQueueRow = {
  review_id: 'approval:alpha:research-backtest:v1',
  object_kind: 'factor',
  version: 'factor-version:alpha:v1',
  scope: 'research_backtest',
  submitted_by: 'user:researcher-01',
  evidence_status: 'complete',
  reviewer: null,
  decision: 'pending',
  decided_at: null,
  review_hash: 'a'.repeat(64),
}

function anonymous(): ApprovalActor {
  return {
    subject_id: 'anonymous',
    can_approve_research: false,
    disabled_reason: 'subject anonymous 未获授予 approve_research 权限，因此无法作出审批决定。',
  }
}

function reviewer(): ApprovalActor {
  return { subject_id: 'user:reviewer-01', can_approve_research: true, disabled_reason: null }
}

function renderForm(actor: ApprovalActor) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ApprovalDecisionForm actor={actor} row={row} />
    </QueryClientProvider>,
  )
}

describe('ApprovalDecisionForm', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('disables the decision with the server reason, not a client-side guess', () => {
    renderForm(anonymous())
    expect(screen.getByRole('button', { name: '批准' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '拒绝' })).toBeDisabled()
    expect(screen.getByText(/未获授予 approve_research 权限/)).toBeInTheDocument()
  })

  it('never offers a scope the reviewer did not receive', () => {
    /* research_backtest approval must not present shadow or paper as options:
     * scopes do not imply one another. */
    renderForm(reviewer())
    expect(screen.getByText('research_backtest')).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'shadow' })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'paper' })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'limited_live' })).not.toBeInTheDocument()
  })

  it('sends no request at all when the actor cannot approve', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    renderForm(anonymous())
    screen.getByRole('button', { name: '批准' }).click()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('surfaces the server rejection verbatim instead of a generic failure', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status: 403,
      json: async () => ({
        detail: 'subject anonymous has no factor review authority',
      }),
    } as Response)))

    renderForm(reviewer())
    screen.getByRole('button', { name: '批准' }).click()

    await waitFor(() => {
      expect(screen.getByText(/has no factor review authority/)).toBeInTheDocument()
    })
    // A refused write must not optimistically flip the row to approved.
    expect(screen.queryByText('已批准')).not.toBeInTheDocument()
  })

  it('requires a reason before enabling submission', () => {
    /* PromotionApproval.__post_init__ rejects an empty reason, so the form must
     * not send a request the domain will refuse. */
    renderForm(reviewer())
    expect(screen.getByRole('button', { name: '批准' })).toBeDisabled()
  })
})
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform/frontend && npm test -- --run src/features/approvals/ApprovalDecisionForm.test.tsx`
Expected: FAIL —— 模块不存在。

- [ ] **Step 4: 实现 postJson 与 ApprovalDecisionForm → 转绿**

`postJson` 加到 `client.ts`，与 `getEnvelope` 同构：`ApiError(status, payload.detail ?? ...)`。
表单**不做乐观更新** —— 审批是治理写操作，成功与否只能由服务端 201 决定。

- [ ] **Step 5: 写页面失败测试**

```tsx
// platform/frontend/src/pages/ApprovalsScreen.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApprovalsScreen } from './ApprovalsScreen'

const context = {
  as_of: '2026-08-16T01:30:00Z',
  system_as_of: '2026-08-16T01:30:00Z',
  data_mode: 'current_research',
  deployment_stage: 'research',
  trust_state: null,
  dataset_version_ids: [],
  model_version_ids: [],
  run_id: null,
  coverage: {},
  warnings: [],
}

const emptyQueue = {
  counts: { pending: 0, approved_research: 0, rejected: 0, production: 0 },
  rows: [],
  actor: {
    subject_id: 'anonymous',
    can_approve_research: false,
    disabled_reason: 'subject anonymous 未获授予 approve_research 权限，因此无法作出审批决定。',
  },
  unsupported_object_kinds: [
    {
      code: 'P9_ALPHA_MODEL_APPROVAL_NOT_IMPLEMENTED',
      reason: 'Alpha Model 用途审批属 P9 治理泛化，尚未实现。',
      affected_binding: 'approval.alpha_model',
      evidence_ids: [],
    },
  ],
  blockers: [],
}

function renderScreen(data: unknown = emptyQueue) {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ data, context }),
  } as Response)))
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ApprovalsScreen />
    </QueryClientProvider>,
  )
}

describe('ApprovalsScreen', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('keeps the four count cards and the rules panel on an empty queue', async () => {
    renderScreen()
    expect(await screen.findByText('Pending')).toBeInTheDocument()
    expect(screen.getByText('Approved Research')).toBeInTheDocument()
    expect(screen.getByText('Rejected')).toBeInTheDocument()
    expect(screen.getByText('Production')).toBeInTheDocument()
    expect(screen.getByText('审批规则')).toBeInTheDocument()
    expect(screen.getByText('服务端决定')).toBeInTheDocument()
    expect(screen.getByText('用途精确')).toBeInTheDocument()
  })

  it('shows real zeros rather than the prototype counts', async () => {
    renderScreen()
    await screen.findByText('Pending')
    expect(screen.queryByText('7')).not.toBeInTheDocument()
    expect(screen.queryByText('REV-1500')).not.toBeInTheDocument()
    expect(screen.queryByText('Reviewer-2')).not.toBeInTheDocument()
  })

  it('names the object kinds that have no approval workflow yet', async () => {
    renderScreen()
    expect(await screen.findByText('P9_ALPHA_MODEL_APPROVAL_NOT_IMPLEMENTED')).toBeInTheDocument()
    expect(screen.getByText('approval.alpha_model')).toBeInTheDocument()
  })

  it('always states the trust-boundary notice', async () => {
    renderScreen()
    expect(await screen.findByText(/前端隐藏按钮不能替代权限校验/)).toBeInTheDocument()
    expect(screen.getByText(/当前无真实账户或 Limited Live 授权/)).toBeInTheDocument()
  })

  it('renders the empty queue as no records, not as a broken capability', async () => {
    renderScreen()
    expect(await screen.findByText('暂无记录')).toBeInTheDocument()
    expect(screen.queryByText('能力未启用')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 6: 实现页面 → 转绿 → 接线到 `/system?tab=approvals`**

在 `pages/WorkspacePage.tsx` 让 `key === 'approvals' && title === '数据与管理'` 渲染
`<ApprovalsScreen />`，并**删除** `activationReasons.approvals` 那条静态文案 ——
它已被真实投影取代。

- [ ] **Step 7: 全量前端验证并提交**

```bash
cd platform/frontend && npm test -- --run && npm run lint && npm run build
cd ../.. && git add platform/frontend/src/features/approvals/ \
  platform/frontend/src/pages/ApprovalsScreen.tsx \
  platform/frontend/src/pages/ApprovalsScreen.test.tsx \
  platform/frontend/src/api/client.ts \
  platform/frontend/src/pages/WorkspacePage.tsx
git commit -m "feat: build the approvals reviewer queue with a server-owned decision gate

The tab was a single sentence saying the workflow was not enabled.  It is now the
prototype's four count cards, eight-column queue, rules panel and trust-boundary
notice, driven by the real review ledger — which today holds nothing, so the
counts are honest zeros rather than the prototype's 7/6/4/0.

The decision buttons carry the server's disabled_reason and send no request when
the actor cannot approve, but the reason is displayed, not invented: hiding a
button is not authorisation, and the operator needs to know which permission is
missing.  A refused write does not optimistically flip the row — approval is a
governance fact the server owns.

Scopes are never offered beyond the one under review: research_backtest does not
imply shadow, paper or limited_live."
```

---

### Task 8: Alpha Model 页产品化

`pages/FactorWorkspace.tsx` 的 `alpha-model` tab 当前是一个 `WorkspaceState state="blocked"`。
Figma `7:5` 要求 4 个 metric 卡 + 因子权重表（只读，ADR-0012）+ PIT Readiness 面板 +
候选 Snapshot 表 + 5 段流转。数据源是**已存在的** `AlphaModelReadinessProjection`。

**Files:**
- Create: `platform/frontend/src/features/screen/AlphaMetricCards.tsx`
- Create: `platform/frontend/src/features/screen/FactorWeightTable.tsx`
- Create: `platform/frontend/src/features/screen/PitReadinessPanel.tsx`
- Create: `platform/frontend/src/features/screen/CandidateSnapshotTable.tsx`
- Create: `platform/frontend/src/features/screen/AlphaModelWorkspace.tsx`
- Test: `platform/frontend/src/features/screen/AlphaModelWorkspace.test.tsx`
- Test: `platform/frontend/src/features/screen/FactorWeightTable.test.tsx`
- Modify: `platform/frontend/src/pages/FactorWorkspace.tsx`
- Modify: `platform/frontend/src/features/screen/screen.less`

**Interfaces:**
- Consumes: 既有 `AlphaModelReadinessProjection`（`status`/`requested_scope`/`data_mode`/`deployment_stage`/`checked_at`/`blocked_reasons` 或 `model`+`factors`）、既有 `AlphaModelReadinessPanel`（作为 blocker 明细区复用，不重写）
- Produces:
  ```ts
  interface AlphaModelWorkspaceProps {
    projection: AlphaModelReadinessProjection
    screen: ScreenRankingProjection | null   // 权重表与 Snapshot 表的绑定来源
  }
  ```

- [ ] **Step 1: 确认 Alpha 投影当前能提供什么、不能提供什么**

Run:
```bash
cd platform
grep -n "class AlphaModelReadyProjection" -A 6 src/a_share_platform/api/schemas.py
grep -n "class ApprovedAlphaFactorProjection" -A 12 src/a_share_platform/api/schemas.py
grep -n "weight\|correlation" src/a_share_platform/api/schemas.py | head
```

`ApprovedAlphaFactorProjection` 提供 `factor_version_id` / `factor_version_hash` /
`lifecycle_status` / `review_id` / `review_hash` / `validation_report_id` /
`validation_report_hash` / `scientific_gate_passed` / `approval`。
**没有 `weight`，也没有 `correlation`** —— 因此权重列与相关性警告列必须显示
「服务端未提供该绑定」，不得用 Figma 的 35%/30%/25%/10% 或 `⚠ 与质量相关 0.42`。
若要真实权重，需先有 `ScreenDefinition` 版本对象（ADR-0012 第二阶段），**不在本 plan 范围**。

- [ ] **Step 2: 写 FactorWeightTable 失败测试**

```tsx
// platform/frontend/src/features/screen/FactorWeightTable.test.tsx
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { FactorWeightTable } from './FactorWeightTable'
import type { AlphaModelReadinessProjection } from './screenProjection'

/**
 * The weight column has no server binding: ApprovedAlphaFactorProjection carries
 * versions, hashes and approvals but no weight, because a weight only becomes a
 * governed number once it lives in a versioned ScreenDefinition (ADR-0012).  The
 * table therefore states the gap instead of showing the prototype's 35/30/25/10.
 */
const unavailable: AlphaModelReadinessProjection = {
  status: 'unavailable',
  requested_scope: 'research_backtest',
  data_mode: 'current_research',
  deployment_stage: 'research',
  checked_at: '2026-08-16T01:30:00Z',
  blocked_reasons: [
    {
      code: 'approved_factor_unavailable',
      reason: '没有 research_backtest scope 的冻结 SignalSnapshot。',
      affected_binding: 'approval_scope:research_backtest',
      evidence_ids: [],
    },
  ],
}

describe('FactorWeightTable', () => {
  afterEach(cleanup)

  it('renders the six prototype columns even with no approved factor', () => {
    render(<FactorWeightTable projection={unavailable} />)
    expect(screen.getByText('因子')).toBeInTheDocument()
    expect(screen.getByText('权重')).toBeInTheDocument()
    expect(screen.getByText('版本')).toBeInTheDocument()
    expect(screen.getByText('Review ID')).toBeInTheDocument()
    expect(screen.getByText('用途')).toBeInTheDocument()
    expect(screen.getByText('相关性警告')).toBeInTheDocument()
  })

  it('never shows the prototype weights or the sample correlation warning', () => {
    render(<FactorWeightTable projection={unavailable} />)
    for (const fixture of ['35%', '30%', '25%', '10%', '100%', '⚠ 与质量相关 0.42']) {
      expect(screen.queryByText(fixture)).not.toBeInTheDocument()
    }
  })

  it('states that weights have no server binding rather than leaving the cell blank', () => {
    render(<FactorWeightTable projection={unavailable} />)
    expect(screen.getByText(/权重未由服务端绑定/)).toBeInTheDocument()
  })

  it('offers no weight input and no run action', () => {
    /* ADR-0012: an editable weight here would produce a ranking with no
     * definition version, no Run record and no approval scope. */
    render(<FactorWeightTable projection={unavailable} />)
    expect(screen.queryByRole('slider')).not.toBeInTheDocument()
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /运行/ })).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 3: 运行确认红测 → 实现 → 转绿**

Run: `cd platform/frontend && npm test -- --run src/features/screen/FactorWeightTable.test.tsx`
Expected: FAIL —— 模块不存在。实现后再跑一次转绿。

- [ ] **Step 4: 写 AlphaModelWorkspace 失败测试**

```tsx
// platform/frontend/src/features/screen/AlphaModelWorkspace.test.tsx
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { AlphaModelWorkspace } from './AlphaModelWorkspace'
import type { AlphaModelReadinessProjection } from './screenProjection'

const unavailable: AlphaModelReadinessProjection = {
  status: 'unavailable',
  requested_scope: 'research_backtest',
  data_mode: 'current_research',
  deployment_stage: 'research',
  checked_at: '2026-08-16T01:30:00Z',
  blocked_reasons: [
    {
      code: 'approved_factor_unavailable',
      reason: '没有 research_backtest scope 的冻结 SignalSnapshot。',
      affected_binding: 'approval_scope:research_backtest',
      evidence_ids: [],
    },
  ],
}

describe('AlphaModelWorkspace', () => {
  afterEach(cleanup)

  it('keeps all five prototype regions when the model is unavailable', () => {
    render(<AlphaModelWorkspace projection={unavailable} screen={null} />)
    expect(screen.getByText(/因子权重配置/)).toBeInTheDocument()
    expect(screen.getByText(/PIT Readiness 诊断/)).toBeInTheDocument()
    expect(screen.getByText(/候选 Signal Snapshot/)).toBeInTheDocument()
    expect(screen.getByText('1. INPUT')).toBeInTheDocument()
    expect(screen.getByText('5. GATE')).toBeInTheDocument()
  })

  it('reports zero qualified snapshots as empty, not as eleven dash rows', () => {
    /* Eleven rows of em dashes would read as "eleven snapshots with missing
     * fields" rather than "no snapshot was ever compiled". */
    render(<AlphaModelWorkspace projection={unavailable} screen={null} />)
    expect(screen.getByText('暂无记录')).toBeInTheDocument()
    expect(screen.queryAllByRole('row')).toHaveLength(0)
  })

  it('shows the real metric values, never ALPHA-V0.8', () => {
    render(<AlphaModelWorkspace projection={unavailable} screen={null} />)
    expect(screen.getByText('真实合格 Snapshot 数')).toBeInTheDocument()
    expect(screen.queryByText('ALPHA-V0.8')).not.toBeInTheDocument()
    expect(screen.queryByText('6')).not.toBeInTheDocument()
  })

  it('states the no-fake-IC commitment as product copy', () => {
    /* This sentence is a product promise, not a sample value, so it belongs in
     * the runtime unchanged. */
    render(<AlphaModelWorkspace projection={unavailable} screen={null} />)
    expect(screen.getByText(/不显示假 IC/)).toBeInTheDocument()
    expect(screen.getByText(/阻断由于数据前瞻导致的过拟合信号偏误/)).toBeInTheDocument()
  })

  it('renders every server blocker through the existing readiness panel', () => {
    render(<AlphaModelWorkspace projection={unavailable} screen={null} />)
    expect(screen.getByText('approved_factor_unavailable')).toBeInTheDocument()
    expect(screen.getByText('approval_scope:research_backtest')).toBeInTheDocument()
  })
})
```

- [ ] **Step 5: 实现 AlphaModelWorkspace → 转绿**

`AlphaModelWorkspace` 组装四个新组件 + 复用 `AlphaModelReadinessPanel` 作为 blocker 明细区。
PIT Readiness 面板的五行来自 Figma，但每行状态必须来自服务端 blocker 的
`affected_binding` 匹配，**不硬编码 `✗ 缺失` / `✓ 可用`**。当前无对应 blocker 时，
该行显示「服务端未报告该维度状态」。

- [ ] **Step 6: 接线到 `/factors?tab=alpha-model`**

替换 `pages/FactorWorkspace.tsx` 中 `alpha-model` 的 `WorkspaceState state="blocked"` 分支。
`FactorWorkspace` 当前不拉 `/api/research/workspace`，需新增该 query 以取得
`alpha_model` 与 `screen` —— 复用 `getResearchWorkspace()`，**不新建端点**。

- [ ] **Step 7: 全量前端验证并提交**

```bash
cd platform/frontend && npm test -- --run && npm run lint && npm run build
cd ../.. && git add platform/frontend/src/features/screen/AlphaMetricCards.tsx \
  platform/frontend/src/features/screen/FactorWeightTable.tsx \
  platform/frontend/src/features/screen/FactorWeightTable.test.tsx \
  platform/frontend/src/features/screen/PitReadinessPanel.tsx \
  platform/frontend/src/features/screen/CandidateSnapshotTable.tsx \
  platform/frontend/src/features/screen/AlphaModelWorkspace.tsx \
  platform/frontend/src/features/screen/AlphaModelWorkspace.test.tsx \
  platform/frontend/src/features/screen/screen.less \
  platform/frontend/src/pages/FactorWorkspace.tsx
git commit -m "feat: productise the Alpha Model page over the existing readiness projection

The tab was one blocked notice.  It now carries the prototype's metric row, weight
table, PIT readiness panel, candidate snapshot table and the five-stage flow —
all driven by AlphaModelReadinessProjection, which already existed.

The weight column has no server binding and says so.  ApprovedAlphaFactorProjection
carries versions, hashes and approvals but no weight, because a weight only
becomes a governed number once it lives in a versioned ScreenDefinition with a Run
record (ADR-0012).  Showing 35/30/25/10 would present a design fixture as
configuration.

Zero qualified snapshots render as an empty state rather than the prototype's
eleven em-dash rows: those would read as eleven snapshots with missing fields
instead of no snapshot ever compiled.  The no-fake-IC sentence is product copy,
not a sample value, so it ships unchanged."
```

---

### Task 9: 四视口响应式合同与真实浏览器验收

四个新页面都必须做 1440/1024/768/320 真实 Chrome 验收。
`docs/plans/track-00` §PUI-00 明确：**17 个 Frame 全部为 1440 宽，320/768/1024 没有独立
Figma Frame**，因此三档只能声明为「按 `docs/18` 响应式合同重排」，不得声称 Figma 视觉验收。

**Files:**
- Create: `platform/frontend/src/features/security-overview/securityOverviewLayoutContract.test.ts`
- Create: `platform/frontend/src/features/approvals/approvalsLayoutContract.test.ts`
- Create: `platform/scripts/verify_golden_path_browser.py`
- Modify: `platform/frontend/src/features/security-overview/securityOverview.less`
- Modify: `platform/frontend/src/features/approvals/approvals.less`

**Interfaces:**
- Consumes: 既有 `app/responsiveLayoutContract.test.ts` 的 `readFileSync` + 正则模式、既有 `scripts/verify_desk_browser.py` 的 playwright 结构
- Produces: 可重跑的四视口验收脚本，产出 `/tmp/golden-path-<page>-<viewport>.png`

- [ ] **Step 1: 读已有的两个验收资产**

Run:
```bash
cd platform
sed -n '1,32p' frontend/src/app/responsiveLayoutContract.test.ts
sed -n '1,34p' scripts/verify_desk_browser.py
```

合同测试读 `.less` 源文件断言 CSS 规则；浏览器脚本用 `p.chromium.launch(channel="chrome")`
遍历四视口并检查 `scrollWidth === clientWidth`、console error/warning、4xx/5xx。
**照抄这两个结构**，不自创第三种验收方式。

- [ ] **Step 2: 写布局合同失败测试**

```ts
// platform/frontend/src/features/security-overview/securityOverviewLayoutContract.test.ts
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const styles = readFileSync('src/features/security-overview/securityOverview.less', 'utf8')

function rule(selector: string) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = styles.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`))
  expect(match, `missing CSS rule for ${selector}`).not.toBeNull()
  return match?.[1] ?? ''
}

describe('security fused overview layout contract', () => {
  it('declares the two Figma column ratios rather than fixed pixel widths', () => {
    // 1440 with a 280 px sider leaves 1160 px, not Figma's 1216: ratios absorb
    // the 56 px difference instead of overflowing the page.
    expect(rule('.securityOverviewRow--wide'))
      .toContain('minmax(0, 746fr) minmax(0, 402fr)')
    expect(rule('.securityOverviewRow--even'))
      .toContain('minmax(0, 560fr) minmax(0, 588fr)')
  })

  it('stacks to a single column below the two-column breakpoint', () => {
    expect(styles).toContain('@media (max-width: 1280px)')
    expect(styles).toMatch(/grid-template-columns:\s*minmax\(0,\s*1fr\)/)
  })

  it('lets long ids and hashes wrap instead of clipping the right edge', () => {
    expect(rule('.securityOverviewCard code')).toContain('overflow-wrap: anywhere')
  })

  it('keeps every grid child able to shrink', () => {
    // A grid child without min-width: 0 is the single most common cause of
    // page-level horizontal overflow at 320.
    expect(styles).toContain('min-width: 0')
  })
})
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform/frontend && npm test -- --run src/features/security-overview/securityOverviewLayoutContract.test.ts`
Expected: FAIL —— `missing CSS rule for .securityOverviewRow--wide`。

- [ ] **Step 4: 实现 less 规则 → 转绿；Approvals 同法**

Approvals 的合同：4 个计数卡在 1440 为四列、1024 为两列、768/320 为一列；
队列表在 768 以下用容器内滚动（`overflow-x: auto`），页面级 `scrollWidth === clientWidth` 仍成立
（PUI-02 已确认这是既有可接受行为）。

- [ ] **Step 5: 写四视口浏览器验收脚本**

```python
# platform/scripts/verify_golden_path_browser.py
"""PUI-03 golden-path browser verification against the real runtime.

Not part of the test suite: this is the four-viewport acceptance run required by
`docs/plans/track-00-prototype-runtime-delivery.md`.  It drives the installed
Chrome against a live API and dev server, so it needs both running and is invoked
manually.  Component tests and curl cannot replace it: page-level overflow,
right-edge clipping and console errors only appear in a real browser.
"""

from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

PAGES = (
    ("security-overview", "http://127.0.0.1:5173/research/security/security:CN:600519:XSHG"),
    ("investment-view", "http://127.0.0.1:5173/research/investment-view/unknown"),
    ("approvals", "http://127.0.0.1:5173/system?tab=approvals"),
    ("alpha-model", "http://127.0.0.1:5173/factors?tab=alpha-model"),
)
VIEWPORTS = (
    ("1440", 1440, 900),
    ("1024", 1024, 768),
    ("768", 768, 1024),
    ("320", 320, 640),
)
# Figma sample values that must never reach the runtime.
DESIGN_FIXTURES = (
    "1,856.20", "1,505.6", "747.3", "682.1", "32.4x", "18.2x", "16.1x", "22.5x",
    "五粮液", "泸州老窖", "山西汾酒", "18/24",
    "REV-1500", "REV-1501", "Reviewer-2", "User-1",
    "ALPHA-V0.8", "RVW-041", "与质量相关 0.42",
)
REQUIRED_TEXT = {
    "security-overview": ("InvestmentView 就绪度", "公司画像与价值链定位"),
    "investment-view": ("INPUT · 输入", "GATE · 门禁"),
    "approvals": ("Pending", "审批规则"),
    "alpha-model": ("PIT Readiness", "不显示假 IC"),
}


def run() -> int:
    results: dict[str, dict[str, object]] = {}
    failures: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        for page_name, url in PAGES:
            for viewport, width, height in VIEWPORTS:
                key = f"{page_name}@{viewport}"
                context = browser.new_context(viewport={"width": width, "height": height})
                page = context.new_page()
                console: list[str] = []
                bad_responses: list[str] = []
                page.on(
                    "console",
                    lambda message: console.append(f"{message.type}: {message.text}")
                    if message.type in ("error", "warning")
                    else None,
                )
                page.on(
                    "response",
                    lambda response: bad_responses.append(f"{response.status} {response.url}")
                    if response.status >= 400
                    else None,
                )
                page.goto(url, wait_until="networkidle")

                metrics = page.evaluate(
                    "() => ({ scrollWidth: document.documentElement.scrollWidth,"
                    " clientWidth: document.documentElement.clientWidth })"
                )
                body = page.inner_text("body")
                leaked = [value for value in DESIGN_FIXTURES if value in body]
                missing = [
                    value for value in REQUIRED_TEXT[page_name] if value not in body
                ]
                page.screenshot(path=f"/tmp/golden-path-{page_name}-{viewport}.png",
                                full_page=True)

                results[key] = {
                    "scrollWidth": metrics["scrollWidth"],
                    "clientWidth": metrics["clientWidth"],
                    "console": console,
                    "bad_responses": bad_responses,
                    "leaked_fixtures": leaked,
                    "missing_required_text": missing,
                }
                if metrics["scrollWidth"] != metrics["clientWidth"]:
                    failures.append(f"{key}: page-level horizontal overflow")
                if console:
                    failures.append(f"{key}: console error or warning")
                if bad_responses:
                    failures.append(f"{key}: {bad_responses[0]}")
                if leaked:
                    failures.append(f"{key}: design fixture leaked {leaked}")
                if missing:
                    failures.append(f"{key}: required text absent {missing}")
                context.close()
        browser.close()

    print(json.dumps({"results": results, "failures": failures},
                     ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
```

- [ ] **Step 6: 启动真实运行时并执行验收**

终端 1：
```bash
cd platform
docker compose up -d postgres
ASP_DATABASE_URL=postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_layered_dev \
PYTHONPATH=src .venv/bin/python -m uvicorn a_share_platform.api.app:app \
  --host 127.0.0.1 --port 8010 --reload
```

终端 2：
```bash
cd platform/frontend && npm run dev
```

终端 3：
```bash
cd platform && .venv/bin/python scripts/verify_golden_path_browser.py
```

Expected: 退出码 0，16 个组合（4 页 × 4 视口）全部 `scrollWidth === clientWidth`、
无 console error/warning、无 4xx/5xx、无 fixture 泄漏。
**任一失败都必须修，不得放宽断言。** 特别注意：`docs/plans/track-00` 已登记
`/factors` 在 320 存在页面级水平溢出（`pageHeading` 溢出），该缺陷登记给 PUI-04；
若本 Task 的 alpha-model@320 因此失败，**在 Evidence 中如实记录并标注归属 PUI-04**，
不要在本 plan 顺手改 `PageHeading`。

- [ ] **Step 7: 提交**

```bash
cd .. && git add platform/frontend/src/features/security-overview/securityOverviewLayoutContract.test.ts \
  platform/frontend/src/features/security-overview/securityOverview.less \
  platform/frontend/src/features/approvals/approvalsLayoutContract.test.ts \
  platform/frontend/src/features/approvals/approvals.less \
  platform/scripts/verify_golden_path_browser.py
git commit -m "test: pin the golden-path responsive contract and add browser acceptance

Column ratios are asserted against the stylesheet rather than trusted, because the
280 px sider leaves 1160 px where Figma drew 1216: fixed pixel widths would
overflow, and ratios make the difference land in the columns.

The browser script covers four pages across 1440/1024/768/320 and fails on
page-level overflow, any console error or warning, any 4xx, and any leaked design
fixture.  Component tests cannot see those.  The three narrow viewports have no
Figma frame, so passing this script is a contract result, not visual parity."
```

---

### Task 10: Evidence 与三轴结论

**Files:**
- Create: `docs/26-pui-03-golden-path-evidence.md`
- Modify: `docs/plans/track-00-prototype-runtime-delivery.md`（PUI-03 状态）

- [ ] **Step 1: 按 PUI-02 Evidence 的结构写三轴表**

照 `docs/24-pui-02-universe-screen-evidence.md` §1 的格式，逐页给出：

| 页面 | Design Parity | Runtime Product | Domain/Capability |
|---|---|---|---|
| Security 融合总览 `24:400` | ? | ? | `blocked`（10 分区中 7 个依赖未实现能力） |
| InvestmentView `15:2` | ? | ? | `blocked`（无合格 qualified frozen View） |
| Approvals `9:883` | ? | ? | `blocked`（4 类对象只有 1 类有账本） |
| Alpha Model `7:5` | ? | ? | `blocked`（P4 资格门未通过） |

Design Parity 只能是 `parity_verified_with_known_deviation`（因为 280 px 侧栏与
只读权重表是已批准差异）或更低。**不得填 `parity_verified`。**

- [ ] **Step 2: 记录真实红绿测**

每个 Task 的真实失败文本与转绿计数。**不编造命令输出。**
运行一次完整验证并抄录真实数字：

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests 2>&1 | tail -5
npm --prefix frontend test -- --run 2>&1 | tail -8
```

（交接基线为 Backend 817/817、Frontend 73/73；本 plan 会增加，记录**真实新数字**。）

- [ ] **Step 3: 逐条记录与 Figma 的已知差异**

至少包含本 plan §现状事实 的六条冲突，每条写明：Figma 值、既有合同、采用哪个、理由、
是否已批准。**侧栏 224 vs 248 vs 280 的三方矛盾必须写清**：
Figma 自身在 `24:400`/`15:2`/`9:883`（224 px）与 `7:5`（`sidebar` FRAME 248 px）之间不一致，
运行时按 SPEC-045 用 280 px，这是已批准差异而非待决冲突。

- [ ] **Step 4: 记录 320/768/1024 的验收性质**

原样写明：三档没有独立 Figma Frame，因此本次通过的是
`docs/18` 响应式合同 + 页面级无溢出 + 无 console error，**不是 Figma 视觉验收**。

- [ ] **Step 5: 写明确否认**

必须包含：

> 本工作包只改变**产品结构与状态诚实度**，不改变任何数据、模型或治理事实。
> 具体地：不代表 P2、P4 或 P5 Gate 通过；不代表任何因子或 Expected Return 模型科学有效；
> 不代表平台具备可盈利策略、Paper-ready 或实盘能力；Approvals 页存在决策按钮
> **不代表任何审批已发生** —— 当前 anonymous identity 只有 `read_public`，
> 所有写入被服务端拒绝，且拒绝原因原样展示。
> 融合页 10 个分区中 7 个显示 blocker，Alpha 页合格 Snapshot 数为 0，
> Approvals 队列计数为 0 —— 这些都是**真实运行态**，不是加载失败。

- [ ] **Step 6: 更新 track-00 的 PUI-03 状态**

把 `状态：ready_for_implementation` 改为 `in_progress` 并补三轴表与已知差异，
格式与 PUI-01/PUI-02 一致。**不得写成 verified** —— Domain/Capability 轴仍是 `blocked`。
同时把 PUI-02 遗留项「行点击进入精确 Security 的上下文传递（依赖 PUI-03）」标记为已完成。

- [ ] **Step 7: 提交**

```bash
git add docs/26-pui-03-golden-path-evidence.md \
  docs/plans/track-00-prototype-runtime-delivery.md
git commit -m "docs: record PUI-03 golden-path evidence with explicit denials

Four pages, three axes each.  Design parity is verified-with-known-deviation
rather than verified, because the 280 px sider and the read-only weight table are
approved departures from the Figma frames — and because Figma itself is internally
inconsistent, drawing a 224 px sider on three pages and a 248 px one on the fourth.

The denial section states what the work package does not change.  Structure and
state honesty improved; no data, model or governance fact moved.  Ten sections
with seven blockers, zero qualified snapshots and a zero-count approvals queue are
the real runtime, not a load failure.  A visible decision button is not evidence
that any approval occurred: anonymous holds read_public only, every write is
refused server-side, and the refusal is shown verbatim."
```

---

## 完成定义

1. `domain/security_overview.py` 的十分区合同复用 `DeskSectionStatus`，四条不变量有测试（Task 1）；
2. 融合总览投影按真实账本填 `view_readiness`/`catalysts`/`industry_peers`，其余七分区声明归属阶段（Task 2）；
3. `GET /api/research/security-overview` 在未配置运行时返回 200 + 十分区骨架，query 不能提升 RunContext（Task 3）；
4. 融合页拆成 6 个具名卡 + 4 个通用分区，缺分区显式 unavailable；Screen 行点击进入精确 Security 且保留四轴上下文（Task 4）；
5. InvestmentView 有独立路由；期限条按「另一个冻结 View」语义工作，无 View 的期限禁用并给原因（Task 5）；
6. `GET /api/approvals` 返回队列 + `actor.can_approve_research` + 服务端 `disabled_reason`；header 不能授权（Task 6）；
7. Approvals 页保留四计数卡与规则栏；决策按钮显示服务端禁用原因，被拒写入不做乐观更新（Task 7）；
8. Alpha 页五个区域齐全；权重列显示「未由服务端绑定」而非 35/30/25/10；零 Snapshot 为 empty 态（Task 8）；
9. 两个布局合同测试通过；`verify_golden_path_browser.py` 16 个组合退出码 0（Task 9）；
10. Evidence 含三轴表、真实红绿测、六条 Figma 差异与明确否认；track-00 PUI-03 更新为 `in_progress`（Task 10）；
11. 后端 unittest / compileall / ruff / mypy 全过；前端 Vitest / lint / build 全过；`git diff --check` 干净。

## 明确不在本 plan 范围

- **可编辑因子权重与「运行 Screen」**：需 `ScreenDefinition` 版本对象 + `Run` 记录，属 ADR-0012 第二阶段，且 P4 门未通过；
- **InvestmentView 提交审批的专用端点**：`POST /api/factors/reviews` 只接受 FactorVersion + ValidationReport；把 View 纳入审批需先有 `InvestmentViewReview` 领域对象，属 P9 审批泛化；
- **Alpha Model / Timing 的审批工作流**：同上，属 P9；
- **产业链图、公告时间线、Research Case 跟踪**：属 P8 事件与文档管道；
- **季度财务轨迹**：当前只有 2018–2025 年末 `normalized_current`，季度需 P-1 阶段二付费源；
- **真实 IC / RankIC 显示**：属 P-2 Task 6；
- **`/factors` 320 视口 `pageHeading` 溢出修复**：`track-00` 已登记归属 PUI-04；
- **截图 diff 工具与像素基线**：`track-00` §PUI-00 要求先由用户批准基线与容差；
- **身份提供者接入**：无 `IdentityProvider` 实现，因此所有调用者恒为 anonymous；接入需单独授权。

## 本 plan 完成后仍然成立的限制

- 四个页面的**结构**符合原型，**数据**几乎全为 blocker —— 这是真实运行态的诚实呈现，不是完成度；
- Design Parity 最高只能到 `parity_verified_with_known_deviation`；31 页完全 parity 仍为 0/31；
- 320/768/1024 只有合同验收，**没有 Figma 视觉证据**；
- Approvals 页的决策按钮在当前运行时**永远被服务端拒绝**，因为没有身份提供者；
- 不得声称 P2、P4 或 P5 Gate 通过；
- 不得声称任何因子或 Expected Return 模型科学有效；
- 不得声称平台具备可盈利策略、Paper-ready 或实盘能力。
