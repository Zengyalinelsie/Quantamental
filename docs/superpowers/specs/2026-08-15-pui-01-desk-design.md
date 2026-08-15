# PUI-01 Desk 设计：服务端 Desk Projection 与原型 Platform Pulse

> 设计日期：2026-08-15
>
> 代码基线：`f703d08 docs: add Claude Code project handoff`（`main`，工作树干净）
>
> 对应轨道：`docs/plans/track-00-prototype-runtime-delivery.md` PUI-00 → PUI-01
>
> 差距审计：`docs/22-prototype-runtime-gap-audit.md`
>
> 性质：实现级设计。不替代 `AGENTS.md`、`docs/07-detailed-system-spec.md`、Accepted ADR
> 或 `docs/18-product-blueprint-and-prototype.md`。

## 1. 目标与非目标

### 目标

用服务端 Desk projection 替换 `platform/frontend/src/pages/DeskPage.tsx` 中 16 行硬编码
`capabilityRows` 工程能力表，按 Figma `desk-daily-workstation`（node `3:398`）的信息架构和布局
实现研究员每日工作台，七个分区各自独立报告真实状态。

本设计同时为后续 PUI-02–PUI-09 建立**可复用的分区状态契约**。Desk 是第一个消费者，不是唯一
消费者；契约设计以「31 页复用」为准，不以「Desk 够用」为准。

### 非目标

- 不实现 P6 组合能力、P8 事件能力；这两个分区由服务端明确声明 unavailable。
- 不把 Figma DESIGN FIXTURE 数字（`94.2%`、`+3.2%`、贵州茅台 `#3` 等）写进任何运行时代码路径。
- 不在浏览器重算排名、状态、审批结果或研究结论。
- 不声称 P2/P4/P5 Gate 通过，不声称任何模型科学有效。
- 不改变侧栏运行时宽度（见 §7 已裁决冲突）。
- 不引入 runtime fixture、demo 模式或默认假数据。

## 2. 设计输入（已解除 PUI-00 阻断）

`docs/22` §2.2 记录 2026-08-15 Figma MCP 额度用尽，设计输入被阻断。本设计通过 **Figma REST API**
（Personal Access Token，`File content: read`）取得了结构化 design context，该阻断已解除。

取得的资产（当前位于 `/tmp/figma_text/`，入库位置见 §8 Task 0）：

| 资产 | 内容 |
|---|---|
| 17 个关键 Frame 的 SVG，合计 1.0 MB | 保留图层 id 与**可读文字**，可作为可恢复视觉真源 |
| `all-nodes.json`（5.0 MB） | 完整节点树：尺寸、间距、`layoutMode`、字号、字重、颜色、图层命名 |
| `file-frames.json` | 18 个顶层 Frame 的 node id 清单 |

导出参数至关重要，必须记录以便复现：

```
GET /v1/images/{key}?ids={ids}&format=svg
    &svg_include_id=true        # 保留图层 id，可与节点树对照
    &svg_outline_text=false     # 保留 <text> 元素而非转矢量路径
    &svg_simplify_stroke=true
```

`svg_outline_text=false` 是关键参数。默认导出会把文字转成矢量路径，单页 1.7 MB（17 页共 33 MB）
且文字不可读、不可搜索，对实现毫无参考价值；保留文字后单页约 40–88 KB，17 页共 1.0 MB，
每页含 91–221 个可读 `<text>` 元素。首次导出误用默认参数，已修正。

file key：`mrt216q7X7NGqFhRjwQS3f`

完整 node id 清单（PUI-00 Task 1 要求的「冻结 file key 与 node id」，本设计一次性补齐）：

| node id | Frame | 1440 尺寸 | 对应轨道 |
|---|---|---|---|
| `3:7` | `foundations-product-map` | 1440×2231 | PUI-00 |
| `3:398` | `desk-daily-workstation` | 1440×1238 | **PUI-01（本设计）** |
| `3:726` | `research-universe-screen` | 1440×1460 | PUI-02 |
| `3:1248` | `security-overview-600519` | 1440×1529 | PUI-03（旧版对照） |
| `3:1569` | `product-blueprint-31-pages` | 1440×1200 | PUI-00 |
| `7:5` | `factors-alpha-model` | 1440×1200 | PUI-04 |
| `7:303` | `portfolios-construction` | 1440×1200 | PUI-05 |
| `7:712` | `portfolios-realistic-backtest` | 1440×1367 | PUI-05 |
| `7:1060` | `portfolios-risk-scenarios` | 1440×1271 | PUI-05 |
| `7:1348` | `portfolios-attribution` | 1440×1300 | PUI-05 |
| `9:2` | `10-events-intelligence` | 1440×1200 | PUI-07 |
| `9:238` | `11-timing-lab` | 1440×1200 | PUI-06 |
| `9:431` | `12-timing-shadow-monitor` | 1440×1200 | PUI-06 |
| `9:661` | `13-data-quality-lineage` | 1440×1200 | PUI-04 |
| `9:883` | `14-approvals-reviewer-queue` | 1440×1200 | PUI-03 |
| `15:2` | `security-investmentview` | 1440×1200 | PUI-03 |
| `24:400` | `security-overview-600519-fused-v2` | 1440×1900 | PUI-03 |
| `9:1114` | `15-golden-path-state-machine` | 6400×1700 | 状态机参考，非页面 |

`docs/22` §2.3 的边界仍然成立：这 17 个 Frame **全部为 1440 宽**，320/768/1024 没有独立 Figma
Frame，三档仍只有文档级响应式合同，不是已通过的视觉证据。

## 3. Desk 精确布局（从 node `3:398` 节点树实测）

```
desk-daily-workstation                     1440 × 1238   bg #F3F5F7
├─ sidebar                                  248 × 1238        ← 与 SPEC-045 冲突，见 §7
│   ├─ brand                                216 × 36
│   │   ├─ "Fundamental Quant"                    16px / 700
│   │   └─ "A股基本面量化研究平台"                 11px / 400
│   ├─ Line                                 216 × 0
│   ├─ nav-list                             216 × 236     6 项 × 36px，间距 40px
│   │   └─ 今日工作台(13/600) 研究 因子 组合 监控 数据与管理 (13/500)
│   └─ sidebar-footer                       248 × 30
│       └─ "SPEC V2.4.0" / "Fund Quant Lab © 2026"   11px / 400
└─ main-content                             1192 × 1238
    ├─ topbar                               1192 × 64
    │   ├─ topbar-left                       379 × 28    证券搜索 13px/400
    │   └─ topbar-right                      807 × 25    研究时点 / CURRENT RESEARCH /
    │                                                    STRICT HISTORICAL / STAGE: RESEARCH /
    │                                                    股票池 / PROD ENV / 原型示例数据标识
    └─ content-body                          1192 × 1174   padding 24
        ├─ today-banner                      1144 × 73
        │   ├─ "今日研究态势 / Platform Pulse"        18px / 600
        │   ├─ 副标题                                  12px / 400
        │   └─ 3 个指标：数据更新 / A股基本面覆盖 / 待处理审批  (11/400 标签 + 13/600 值)
        └─ grid                              1144 × 1029   HORIZONTAL, NO_WRAP, gap 24
            ├─ grid-left                      740 × 535    gap 24
            │   ├─ card-rankings              740 × 350
            │   │   ├─ card-title-row  "最新 Screen 排名变化 / Universe Shift Tracker" 14/600
            │   │   └─ table  704 宽，7 列：代码 公司 行业 综合排名 排名变化 置信度 鲜度 (11/600)
            │   └─ row-metrics                740 × 161
            │       ├─ card-risk              358    "组合偏离与风险 / Portfolio Tracking" 14/600
            │       │                                4 指标：Active Share / HHI / Max Position / VaR
            │       └─ card-shadow            358    "Timing Shadow / 影子跟踪" 14/600
            │                                        4 指标：累计超额 / 本周超额 / 持仓数 / 换手率
            └─ grid-right                     380 × 1029   gap 24
                ├─ card-events                380 × 489   "重大事件/公告流 / Basic Feeds" 14/600
                │                                          feed-list 344 宽，条目含时间/来源/摘要/sha256
                ├─ card-pending               380 × 273   "因子审核与待处理 / Pending Tasks" 14/600
                │                                          pending-list 344 宽，条目含首字母/标题/描述/优先级
                └─ card-exceptions            380 × 219   "运行异常 / Active Failures" 14/600
                                                           exception-list 344 宽，条目含描述/来源/时间
```

字体族为 Inter。字号层级实测只用到 `10 / 11 / 12 / 13 / 14 / 16 / 18`，字重只用到
`400 / 500 / 600 / 700`。这是一套克制的层级，实现时不得引入 Figma 未出现的字号。

`grid` 为 `NO_WRAP`，因此 1440 下左右两栏不换行；三档响应式的换行规则由 §6 定义，不由 Figma 提供。

### 3.1 设计 token（从节点树实测，非推测）

| Token | 值 | 用途 | 出现次数 |
|---|---|---|---:|
| 主文字 | `#18202A` | 标题、数值 | 45 |
| 次文字 | `#4E5968` | 标签、描述、说明 | 60 |
| 品牌蓝 | `#2F5EA8` | 强调、链接、正向标签 | 42 |
| 浅蓝底 | `#EAF2FC` | 蓝色标签背景 | 11 |
| 页面底色 | `#F3F5F7` | 画布 | 16 |
| 卡片底色 | `#FFFFFF` | 卡片 | 15 |
| 边框 | `#DEE2E7`（主）/ `#C8CDD4`（次） | 分割线、卡片描边 | 14 |
| 警示红 | `#A64045`；深 `#7A1C20`；底 `#FCECEE` / `#FCEAEB` | 异常、下跌、紧急 | 15 |
| 成功绿 | `#2E7660` | 正常、上涨 | 7 |
| 警告黄 | `#B87A14`；底 `#FDF8E2` | partial、待处理、审批中 | 8 |

圆角：仅 `1 / 2 / 3 / 12` px（`3` 为主，`12` 用于 pill 标签）。
内距：仅 `2 / 6 / 8 / 10 / 12` px（`8` 为主）。
分区间距：`24` px（`grid`、`grid-left`、`grid-right` 的 `itemSpacing` 均为 24）。

**红绿语义注意**：`#A64045` 与 `#2E7660` 是低饱和度的暗红/暗绿，符合机构审慎风格。实现时
**不得**使用 AntD 默认的 `#ff4d4f` / `#52c41a` 等高饱和度状态色，否则视觉密度与原型明显不符。
状态区分必须同时使用非颜色手段（图标、文字标签），满足可访问性要求。

## 4. 架构与数据流

### 4.1 分层

遵守 `CLAUDE.md` §3.2 依赖方向，不让 `domain/` 感知 Web/DB/provider。

```
domain/desk.py                    纯值对象：DeskSection、DeskSectionStatus、DeskBlocker
   ↑
application/desk_projection.py    DeskProjectionService：编排 7 个已有 port/service
   ↑
api/app.py  GET /api/desk         Envelope<DeskProjection> + ResponseContext
   ↑
frontend/src/api/client.ts        getDesk()
   ↑
frontend/src/features/desk/*      7 个分区组件
   ↑
frontend/src/pages/DeskPage.tsx   仅编排与布局，不含业务判断
```

### 4.2 核心架构决定：分区级隔离

**每个分区独立持有自己的 status 和 blockers；任一分区的数据源不可用，不影响其余六个分区。**

理由：Desk 的产品职责是「态势总览」。若采用整页单一 status，则七个来源中任何一个失败都会让整页
变成错误页，与产品意图相反。这也是 `docs/22` §4「三轴不能互相替代」在页面内部的自然延伸——
分区之间同样不能互相替代。

实现约束：`DeskProjectionService.project()` 内部对每个分区使用独立的 `try/except`，捕获该分区
对应的 `*Unavailable` 异常，转为该分区的 unavailable 状态 + blocker，**不向上抛出**。此模式与现有
`ResearchWorkspaceProjectionService.project()`（`application/research_workspace.py:110-136`）
一致，属于既有代码风格的延续，不是新发明。

### 4.3 七分区的服务端来源（全部复用现有代码）

| # | 分区 | Figma 卡片 | 复用的现有接口 | 预期真实状态 |
|---:|---|---|---|---|
| 1 | 数据健康 | `today-banner` | `SystemCatalogReader.list_quality_reports()` / `.list_datasets()` | `partial` |
| 2 | Screen 排名变化 | `card-rankings` | `ResearchWorkspaceProjectionService.project()` → screen | `empty` |
| 3 | 组合偏离与风险 | `card-risk` | **无实现** → 声明 unavailable | `unavailable` |
| 4 | Timing Shadow | `card-shadow` | `TimingShadowLedger` / `TimingForecastRepository` | `empty` 或 `partial` |
| 5 | 重大事件流 | `card-events` | **无实现** → 声明 unavailable | `unavailable` |
| 6 | 因子审核与待处理 | `card-pending` | `FactorReviewService.list_reviews()` | `partial` |
| 7 | 运行异常 | `card-exceptions` | `SystemCatalogReader.list_jobs()` → `failure_reasons` | `partial` |

分区 3 与 5 的 unavailable 由**服务端**声明，附 blocker code `P6_PORTFOLIO_TRACKING_NOT_IMPLEMENTED`
与 `P8_EVENT_FEED_NOT_IMPLEMENTED`。前端因此不需要任何阶段知识（不需要知道 P6/P8 是什么），
符合 `CLAUDE.md` §11「不用前端重算状态」。

分区 6 为 `partial` 而非 `ready`：`FactorReviewService` 只覆盖 factor promotion review，
Figma 原型的「中报延迟修正」「数据源注册」「未来数据拦截」属于通用审批工作流（P9），尚不存在。
partial 必须附 coverage 说明这一缺口（见 §5.3）。

### 4.4 读路径纯净性

`GET /api/desk` **只读现有 repository**，不触发计算、摄取、Agent 或 LLM 调用。这是 track-00
PUI-01 TDD 切片第 3 条「普通刷新不触发昂贵 Agent」的落地方式，将由测试断言保证（§8 Task 4）。

### 4.5 权限与运行上下文

复用现有 `anonymous_principal()` 与 `fixed_read_context()`（`api/app.py:127-151`）。Desk 为只读
投影，所需权限为 `read_public`。运行上下文（`data_mode`、`deployment_stage`、`as_of`）由服务端
通过既有 `ResponseContext` 下发，前端不构造、不推断、不覆盖。

## 5. 分区状态契约（本设计最关键部分）

### 5.1 现状矛盾

| 位置 | 现有定义 | 问题 |
|---|---|---|
| `components/WorkspaceState.tsx:4` | `'loading' \| 'error' \| 'empty' \| 'blocked' \| 'ready'` | 五值；缺 `partial`；用 `blocked` 而非 `unavailable` |
| `schemas.py` `ResearchWorkspaceData.status` | `"ready" \| "partial" \| "unavailable"` | 三值；缺 `empty` |
| track-00 要求 | `loading / error / empty / partial / unavailable / ready` | 六值 |

### 5.2 决定：按知识归属分离，不强行统一为单一枚举

这六个状态来自两个不同源头。强行合并为一个枚举会掩盖这一事实，并迫使某一侧表达它不可能知道的
状态。

```
服务端知道（数据事实）          前端知道（请求生命周期）
├─ ready                        ├─ loading   请求进行中
├─ partial                      └─ error     请求失败 / 网络错误 / 非 2xx
├─ empty
└─ unavailable
```

服务端无法知道「loading」；前端无法知道「partial」。因此：

**后端** 新增 `DeskSectionStatus`，四值：

```python
DeskSectionStatus = Literal["ready", "partial", "empty", "unavailable"]
```

比 `ResearchWorkspaceData.status` 多一个 `empty`。这个区分是产品必需的：

- `empty` = 功能已实现、数据源可达、但当前没有记录 → 「等数据」
- `unavailable` = 功能尚未实现或数据源不可达 → 「等功能」

对使用者而言这是两件完全不同的事，合并会丢失关键信息。Screen 分区（功能在、库里空）与组合分区
（功能不存在）必须可区分。

**前端** 将 `WorkspaceStateKind` 扩展为六值，并保留 `blocked` 作为 `unavailable` 的向后兼容别名：

```typescript
export type WorkspaceStateKind =
  | 'loading' | 'error' | 'empty' | 'partial' | 'unavailable' | 'ready'
  | 'blocked'   // deprecated alias of 'unavailable'; existing call sites
```

保留 `blocked` 是为了把本轮 diff 限制在 Desk 范围内，不波及 `WorkspaceUnavailable` 等现有调用点。
别名的清理属于 PUI-04 范围，届时统一处理。

前端状态合成规则（唯一允许的前端状态判断，因为它只关乎请求生命周期）：

```typescript
function resolveSectionState(
  query: { isLoading: boolean; error: unknown },
  section: DeskSection | undefined,
): WorkspaceStateKind {
  if (query.isLoading) return 'loading'
  if (query.error) return 'error'
  return section?.status ?? 'unavailable'
}
```

### 5.3 partial 必须自证缺口

单独一个「部分可用」标签没有信息量。因此契约要求：

**`status === "partial"` 的分区必须至少提供 `coverage` 或一条 `blocker`，否则视为契约违规。**
此约束由后端测试断言（§8 Task 3），不依赖实现者自觉。

`coverage` 复用 `ResponseContext.coverage: dict[str, Any]` 的既有惯例，在分区级重复该形状，
例如数据健康分区：`{"datasets_total": 42, "datasets_with_quality_report": 12}`。

### 5.4 blocker 结构

直接复用现有 `ResearchWorkspaceBlocker`（`schemas.py:124-128`），不新造类型：

```python
code: str                  # 机器可读，如 "P6_PORTFOLIO_TRACKING_NOT_IMPLEMENTED"
reason: str                # 人类可读，直接呈现给使用者
affected_binding: str      # 受影响的绑定，如 "portfolio.tracking"
evidence_ids: list[str]    # 可为空
```

在 Desk 语境下复用时命名为 `DeskBlocker`（同结构，独立类型名，避免 Desk 与 Research workspace
的语义耦合）。

### 5.5 分区契约

```python
class DeskSection(StrictResponse):
    key: DeskSectionKey            # 七个固定键，见下
    status: DeskSectionStatus
    title: str                     # 服务端下发，与 Figma 标题一致
    blockers: list[DeskBlocker]
    coverage: dict[str, Any]
    payload: <每分区专属类型> | None   # status 非 ready/partial 时为 None

DeskSectionKey = Literal[
    "data_health", "screen_shifts", "portfolio_tracking",
    "timing_shadow", "event_feed", "pending_tasks", "active_failures",
]

class DeskProjection(StrictResponse):
    sections: list[DeskSection]     # 恒为 7 项，顺序固定，缺失即契约违规
```

**`sections` 恒为 7 项**：分区不因不可用而消失。这保证页面骨架稳定——你打开 Desk 永远看到七个
分区，只是其中几个诚实地说「还没有」。这与「不得退化为一段泛化的能力未启用占满整页」
（track-00 §六态与运行时数据）一致。

## 6. 响应式合同

1440 有精确 Figma 依据；其余三档 Figma 无独立 Frame，按以下合同重排（不等比缩小）：

| 视口 | 侧栏 | grid 布局 |
|---|---|---|
| 1440 | 280 px 展开（见 §7） | 左 740 / 右 380，gap 24，不换行 |
| 1024 | 72 px 收起 | 单列纵向：banner → rankings → risk+shadow 并排 → events → pending → exceptions |
| 768 | 移动 Drawer | 单列；rankings 表格在自身容器内横向滚动；risk/shadow 转为上下堆叠 |
| 320 | 移动 Drawer | 单列；rankings 表格转为等价记录卡（每证券一卡），不横向滚动 |

硬约束（延续 P5 已验收标准）：页面级 `document.scrollWidth === document.clientWidth`，宽表只在
自身容器滚动，顶部运行上下文可断行不裁切。

320 档把排名表转为记录卡而非横向滚动，因为 7 列在 320 宽下横滚会使「排名变化」等关键列长期不可见，
违背该分区的产品意图。

## 7. 已裁决冲突：侧栏宽度

发现三值冲突（本设计新增第三个数据点）：

| 来源 | 值 | 优先级 |
|---|---|---|
| SPEC-045（`docs/07-detailed-system-spec.md`） | 280 px | 最高 |
| `docs/18-product-blueprint-and-prototype.md` 响应式表 | 224 px | 较低 |
| Figma `desk-daily-workstation` node `3:398` 实测 | **248 px** | 视觉真源 |
| 当前运行时 | 280 px / 收起 72 px | — |

**用户裁决（2026-08-15）：运行时继续使用 280 px，将差异登记为已知差异，不修改任何真源。**

后果，必须在 Evidence 中如实记录：

- 1440 下主内容区为 1160 px，而非 Figma 的 1192 px，差 32 px；
- 因此 Desk 的 1440 Design Parity **不能记为 `parity_verified`**，只能记为
  `parity_verified_with_known_deviation`，并明确列出侧栏 280 vs 248 这一项；
- 内部卡片按比例自适应，不硬编码 740/380，改用比例约束（左右约 66% / 34%，gap 24），
  使 32 px 差异被吸收在两栏宽度上而非产生水平溢出；
- 三值冲突本身**保持未裁决状态**记录在 `docs/22`，等待你未来对 SPEC-045 / docs/18 / Figma
  三者做一次统一决定。本设计不代替那个决定。

## 8. 实施计划（TDD，一个 Task 一个可验证行为）

前置事实：本机环境已于 2026-08-15 完成 bootstrap，基线已复现为绿：
后端 817/817 passed、前端 Vitest 73/73 passed、ruff passed、mypy 175 files passed、
compileall passed、frontend lint passed、frontend build passed（AntD large-chunk warning 为既有）。

环境记录（与 `CLAUDE.md` §10 描述的开发机不同，需在 Evidence 中说明）：
Python 3.12.12（`platform/.venv`，`pyproject.toml` 要求 `>=3.11`，满足）、Node v22.23.1、
pip 需使用镜像源（`files.pythonhosted.org` 在本机 Python 中 TLS 失败）、
未安装 docker/psql，因此 PostgreSQL migration smoke **本轮不运行**，不改写为默认通过。

### Task 0：设计资产入库（解除全部 PUI 设计输入阻断）

将 17 个保留文字的 SVG（合计 1.0 MB）从 `/tmp/figma_text/` 移入 `docs/assets/prototype/`，并入库
节点树结构化摘要（各 Frame 的层级、尺寸、字号、字重、颜色；非全量 5 MB 原始 JSON）。

更新 `docs/assets/prototype/README.md`：记录 REST API 取得方式与**完整导出参数**（含
`svg_outline_text=false` 的必要性）、file key、全部 18 个 node id、取得日期，并保留
「Figma 示例数字始终是 DESIGN FIXTURE，严禁进入运行时」的既有声明。

体积评估已完成：仓库 `.git` 当前 1.5 MB，新增 1.0 MB 可接受；不需要 Git LFS。原始 33 MB 的
矢量化版本**不入库**。

此 Task 的价值超出 PUI-01：它一次性为 PUI-02–PUI-09 全部提供可恢复的精确视觉真源，使
`docs/22` §2.2 记录的 Figma MCP 额度阻断不再是任何 PUI 工作包的前置条件。

### Task 1：红测——Desk 不再渲染 capabilityRows

改写 `pages/DeskPage.test.tsx`：断言页面**不含**工程能力表特征（`P3 · RESEARCH EVIDENCE`、
`能力与数据就绪度`、`合同就绪` 等），且**包含**七个分区标题。

预期红测原因：当前 `DeskPage.tsx` 仍渲染 `capabilityRows`，断言「不含」失败。

### Task 2：领域契约

新增 `domain/desk.py`：`DeskSectionKey`、`DeskSectionStatus`、`DeskBlocker`、`DeskSection`。
纯值对象，不导入 FastAPI / SQLAlchemy / provider SDK。先写 `tests/test_desk_domain.py` 断言
`partial` 必须携带 coverage 或 blocker、`sections` 恒 7 项、非 ready/partial 时 payload 为 None。

### Task 3：DeskProjectionService

新增 `application/desk_projection.py`。先写 `tests/test_desk_projection.py`，逐分区断言：

- 每个数据源不可用时，**只有该分区**变 unavailable，其余六个分区不受影响；
- 组合与事件分区恒为 unavailable，带正确 blocker code；
- Screen 无记录时为 `empty` 而非 `unavailable`；
- 所有 `partial` 分区都携带 coverage 或 blocker；
- 不出现任何 Figma DESIGN FIXTURE 数值。

### Task 4：API 端点

`GET /api/desk`，复用 `envelope()` 与 `fixed_read_context()`。测试断言：
七分区齐全、Envelope 形状正确、**只读**（用 spy/fake 断言未调用任何写入或计算方法）。

### Task 5：OpenAPI 与前端类型同步

运行 `npm --prefix frontend run generate:api`（需 `PYTHON_BIN=../.venv/bin/python`，因本机无
`python3.11`），更新 `api/openapi.json` 与 `schema.d.ts`，在 `client.ts` 增加 `getDesk()`。

### Task 6：分区状态基础设施

扩展 `WorkspaceStateKind` 至六值 + `blocked` 别名；新增 `features/desk/DeskSection.tsx` 通用外壳
（标题 + 状态 + blocker + coverage 渲染）。先写组件测试覆盖全部六态。

### Task 7：七个分区组件

按 §3 布局逐个实现，复用现有 AntD/ProTable 与 Less token。每个分区一个组件测试，覆盖六态。

### Task 8：DeskPage 组装

替换 `DeskPage.tsx`：删除 `capabilityRows`，改为消费 `getDesk()` 并按 §6 布局排列七分区。
Task 1 的红测应在此转绿。

### Task 9：四视口真实浏览器验收

1440/1024/768/320。检查页面级水平溢出、右侧裁切、导航、Research Time / Data Mode /
Deployment Stage / Universe、六态、键盘与焦点、可访问名称、控制台 error/warning、
网络 4xx/5xx、一次显式失败与恢复。1440 与 `desk-daily-workstation` 逐区对照并记录全部差异。

### Task 10：文档与 Evidence

更新 `docs/plans/track-00-prototype-runtime-delivery.md`（PUI-00 设计输入阻断解除、PUI-01 状态）、
`docs/22-prototype-runtime-gap-audit.md`（Desk 行三轴状态、侧栏三值冲突升级为三方）、
对应 Evidence（红测/绿测真实输出、环境差异、侧栏已知差异、未完成项）。

### Task 11：全量验证

后端 unittest、compileall、ruff、mypy、前端 Vitest、lint、build、`git diff --check`。
PostgreSQL migration smoke 本轮不适用，如实标注而非改为通过。

## 9. 完成后必须分别报告的三轴状态

| 轴 | 本轮预期结论 |
|---|---|
| Design Parity | `parity_verified_with_known_deviation`（侧栏 280 vs 248；320/768/1024 无 Figma Frame 依据） |
| Runtime Product | `verified`（七分区六态由真实 API 驱动，无 runtime fixture） |
| Domain/Capability | `blocked`（组合 P6、事件 P8 未实现；P2/P4/P5 Gate 未通过） |

**不得用任何一轴的通过替代其余两轴。** 特别是：Runtime Product 通过不代表 Desk 上显示的数字
科学有效，也不代表 P2/P4/P5 Gate 通过。

## 10. 已知限制

- 组合偏离与风险、重大事件流两个分区在本轮结束后仍为 unavailable，需 P6/P8 能力才能变为 ready。
- 因子审核与待处理仅覆盖 factor promotion review，通用审批工作流属 P9。
- 运行异常仅覆盖摄取作业失败，通用 Incident 账本属 P9/P10。
- Timing Shadow 仅被动波动率 baseline，主动 Timing 属 P7。
- 320/768/1024 三档无独立 Figma Frame，视觉依据为文档级响应式合同，非 Figma 验收。
- 侧栏三值冲突未最终裁决，本轮仅登记差异。
- 本机未安装 PostgreSQL，涉及真实数据库的验证本轮未运行。
