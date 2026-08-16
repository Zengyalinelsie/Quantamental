# P-8 监控、统一归因与治理闭环 P9 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 P6 的 core attribution 扩成含 Timing/Event 的 `UnifiedAttribution`，新建版本化阈值驱动的漂移监控、去重的 Alert/Incident 状态机，把当前只覆盖因子的审批合同泛化到 Alpha/Timing/Risk/Portfolio 并强制职责分离，最后按 PUI-08 交付 Monitoring 六页（Signals / Portfolios / Timing / Drift / Rebalance / Incidents）与 Factors/System 五页（Correlation / Production / Users / Entitlements / Approvals）。

**Architecture:** 三块新建、一块泛化。**新建**：`domain/attribution.py` 的 unified 扩展、`domain/monitoring.py`、`domain/incidents.py`（2026-08-16 逐文件核实：三者全部不存在）。**泛化**：`domain/factor_reviews.py` 的 `FactorPromotionReview` 与 `domain/factor_lifecycle.py` 的 `PromotionApproval` 是**已存在且经过测试的审批模板**，本 plan 从它们抽出 subject-agnostic 的 `ApprovalReview`，**不重写身份系统**，也不放宽 `FactorPromotionReview` 的任何守卫。`application/permissions.py` 的 8 角色 × 8 权限矩阵原样保留，新增职责分离与 expiry 是**服务层规则**，不是权限矩阵的第 9 行。`application/desk_projection.py` 的 `_pending_tasks()` 与 `_active_failures()` 已各留一个 P9 blocker code，本 plan 的 Task 3/4 就是它们的兑现。

**Tech Stack:** Python 3.11+（本机 3.12.12）、Decimal 全程（贡献/阈值/统计量）、NumPy 2.5.2 + SciPy 1.18.0（PSI/KS 独立交叉验证）、PostgreSQL 17（端口 55432，append-only trigger）、React 19 + TypeScript 5.8 + Vite 7 + AntD 6、Vitest 3、Playwright（Chrome channel）

## Global Constraints

继承 `AGENTS.md`、`docs/07-detailed-system-spec.md`（SPEC-023、039–041、048–050、055–058）、
**ADR-0009（Accepted，2026-08-14）** 与 `docs/plans/step-08-p9-monitoring-governance.md` 的冻结 Spec，
**每个 Task 都适用**：

- `domain/` 不导入 FastAPI / SQLAlchemy / psycopg / provider SDK / numpy / scipy / 前端概念
  （`tests/test_architecture_contract.py` 的 `forbidden_roots` 已强制）
- **监控不得静默改模型或权重**。Step 08 Spec 原文：「告警只能阻断、请求 Review 或按已批准 rollback 执行，
  不能自行晋级」。反向也成立：告警也不能自行降级、改权重、改阈值或改 `FactorLifecycleStatus`
- **归因残差超容差必须产生 blocker/Incident，不得吸收进 "other"**。Step 08 Spec 原文：
  「residual 超阈值创建 blocker/Incident，不被"其他"吞掉」
- **阈值必须版本化、按 subject/version 配置**（Step 08 决策：「SLO、PSI、IC decay、calibration、
  residual 阈值为 D2，按 subject/version 配置」）。任何硬编码阈值都是缺陷：改阈值等于改
  「什么算 Incident」，而它必须留下版本痕迹
- **owner scope 只有四个**，ADR-0009 已冻结：`data` / `research` / `portfolio` / `execution`。
  前端不能改 owner scope 或严重度规则
- **职责分离（SoD）：提交人不能批准自己提交的对象。** `Role.AGENT` 永远不能批准任何 scope
- **审批 scope 不互相隐含**：`ApprovalScope` 的 `research_backtest` / `shadow` / `paper` /
  `limited_live` 四值继续互不推出（SPEC-023）
- **execution 分项在 Paper 之前必须是 `not_applicable`**，不是 0，也不是 `unavailable`
  （Step 08 Spec：「P9 execution 分项在 Paper 前为 not_applicable」）
- Alert/Incident/ApprovalReview/ServingRegistration 全部 append-only：重复写幂等，
  same ID / different semantics 冲突关闭，失败与非法转移记录不可删除
- **前端不聚合**。Monitoring 页面的计数、分组、去重、严重度排序全部服务端完成；
  cursor pagination，不用 offset（Step 08 Task 5：「增加 cursor pagination 和服务端聚合」）
- 缺失、不可评估、不可比必须显式表达，**禁止填零**
- runtime 无默认 fixture；Figma 示例值（`REV-1500`、`Q-1300`、`RUN-1400`、`User-1`、`184`、`169` 等）零泄漏
- worker 默认 dry-run，真实写入需 `--private-local-research-ack --execute`
- 未经用户明确授权不 commit、不 push

## 前置条件（三条硬依赖，缺一不可）

**P-8 监控的是 P-5、P-6、P-7 的输出。监控一个不存在的东西是不可测的。**

这不是排序偏好，是可测性问题。逐条说明为什么：

### 依赖 P-5（组合与回测 P6）

`UnifiedAttribution` 是从 P-5 Task 7 的 `domain/attribution.py` **扩展**而来，不是新写一份。
P-5 交付的是 `scope == "core_only"` 的 `AttributionSnapshot`：market / industry / style /
selection / cost 五个 quantified 分项，加上 timing 的 `NOT_APPLICABLE` 与 events / execution
的 `UNAVAILABLE`。本 plan 的 Task 1 做的事是把 timing 从 `NOT_APPLICABLE` 变成真实数值
（当 P-7 有获批模型时）、把 events 从 `UNAVAILABLE` 变成真实数值（当 P-7 事件模型获批时），
并把 `scope` 从 `core_only` 提升为 `unified`。

**没有 P-5 就没有 `attribute_session()`、没有 `ClosureStatus`、没有 `AttributionComponentStatus`，
Task 1 的第一行代码都写不出来。**

同时，Drift 的 exposure / cost / capacity 三组指标的被监控对象是 `TargetPortfolioSnapshot`
与 `RiskModelDecisionRecord`；Monitoring/Portfolios 页与 Monitoring/Rebalance 页的数据源
也是它们。

### 依赖 P-6（主动 Timing P7）

Drift 的 calibration 组监控 `TimingCalibration`；Monitoring/Timing 页读 P-6 Task 4 的
forward shadow ledger；`ApprovalReview` 泛化的四个 subject 里 `timing` 那一个的
被审批对象是 P-6 的 `TimingModelVersion`。

**关键一点**：P-6 已经建立了 `TimingPromotionReview`（Task 4）。本 plan 的 Task 4 必须
**把它与 `FactorPromotionReview` 一起抽象**，而不是造第三套。如果 P-6 未完成，
Task 4 就只有一个模板，抽象出来的接口几乎必然错。

### 依赖 P-7（事件与 Agent P8）

Drift 的 Agent parse / citation 组监控 `AgentRun`；`UnifiedAttribution` 的 event 分项
需要 P-7 的 `EventStudy` 与 `ImpactHypothesis`；Task 6 故障注入里的 `citation failure`
必须注入到真实 `AgentRun` 路径上。

**没有 P-7，Task 6 的七类故障里有一类无法注入，Task 1 的 event 分项永久 `unavailable`。**
那不是失败——诚实报告 `unavailable` 是正确行为——但它意味着 P9 Gate 的
「统一归因闭合」验收项**不可能通过**，只能通过 core 部分。

### 校验命令

```bash
cd platform && source /tmp/asp_env.sh
.venv/bin/python - <<'PY'
import os, psycopg
TABLES = (
    # P-5
    "research.target_portfolio_snapshots", "research.risk_model_decisions",
    "research.backtest_runs", "research.attribution_snapshots",
    # P-6
    "research.timing_experiments", "research.timing_forecasts",
    "research.timing_calibrations",
    # P-7
    "evidence.document_versions", "research.event_clusters",
    "governance.agent_runs",
)
with psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True) as c:
    for t in TABLES:
        try:
            print(t, c.execute(f"select count(*) from {t}").fetchone()[0])
        except Exception as error:
            print(t, "MISSING:", type(error).__name__)
PY
```

**判断规则**：

- `research.attribution_snapshots` 表不存在 → **停下来先做 P-5**。Task 1 无法开始。
- P-6 的三张表不存在 → Task 1 的 timing 分项永久 `not_applicable`，Task 4 只有一个模板。
  可以继续，但必须在 Evidence 里写明抽象是从单一样本推的。
- P-7 的三张表不存在 → Task 1 的 event 分项永久 `unavailable`，Task 6 少一类故障。
  可以继续，Gate 的统一归因项不通过。
- 全部存在但计数为 0 → **Task 1–5 全部可做**（纯数学与工程合同，用测试 fixture 驱动），
  Task 6 的故障注入可做（注入的是人工构造的异常），只有真实数值为空。
  **这是允许且正确的结果。**

## 已存在的接口（本 plan 消费与泛化，不重写）

经 2026-08-16 逐行核实的真实签名。**以代码为准；若实现与下文不同，改本 plan，不改代码去迁就 plan。**

### `application/permissions.py`（76 行，全部已实现）

这是本 plan Task 4 的基石。**8 个角色**：

```python
class Role(str, Enum):
    VIEWER = "viewer"
    RESEARCHER = "researcher"
    DATA_OPERATOR = "data_operator"
    REVIEWER = "reviewer"
    PORTFOLIO_MANAGER = "portfolio_manager"
    TRADER = "trader"
    ADMINISTRATOR = "administrator"
    AGENT = "agent"
```

**8 个权限**：

```python
class Permission(str, Enum):
    READ_PUBLIC = "read_public"
    READ_ARTIFACT = "read_artifact"
    CREATE_EXPERIMENT = "create_experiment"
    MANAGE_DATA = "manage_data"
    APPROVE_RESEARCH = "approve_research"
    APPROVE_PORTFOLIO = "approve_portfolio"
    SEND_ORDER = "send_order"
    ADMINISTER = "administer"
```

**完整的 `PermissionPolicy.default()` 映射（逐字）**：

```python
@classmethod
def default(cls) -> PermissionPolicy:
    read = frozenset({Permission.READ_PUBLIC})
    artifact_read = frozenset({Permission.READ_ARTIFACT})
    return cls(
        {
            Role.VIEWER: read,
            Role.RESEARCHER: read | artifact_read | {Permission.CREATE_EXPERIMENT},
            Role.DATA_OPERATOR: read | artifact_read | {Permission.MANAGE_DATA},
            Role.REVIEWER: read | artifact_read | {Permission.APPROVE_RESEARCH},
            Role.PORTFOLIO_MANAGER: read
            | artifact_read
            | {Permission.APPROVE_PORTFOLIO},
            Role.TRADER: read | {Permission.SEND_ORDER},
            Role.ADMINISTRATOR: frozenset(Permission),
            Role.AGENT: read,
        }
    )

def allows(self, principal: Principal, permission: Permission | str) -> bool:
    try:
        requested = Permission(permission)
    except ValueError:
        return False
    if principal.subject_id == "anonymous":
        return requested is Permission.READ_PUBLIC
    return any(requested in self.grants.get(role, ()) for role in principal.roles)
```

**从这份矩阵可以直接读出四个事实，Task 4 全部要变成测试**：

1. `Role.AGENT` 只有 `READ_PUBLIC`。它**没有** `READ_ARTIFACT`，因此连证据都读不到，
   更不可能批准。这是 deny-by-default 的正确结果，但**必须有测试锁住**——
   给 Agent 加一行权限是一次单行改动，而它会让 Agent 获得审批权。
2. `Role.REVIEWER` 有 `APPROVE_RESEARCH` 但**没有** `APPROVE_PORTFOLIO`；
   `Role.PORTFOLIO_MANAGER` 反之。所以 Alpha/Timing/Risk 属研究侧、Portfolio 属组合侧
   这条映射不是本 plan 的发明，**它已经写在权限矩阵里了**。Task 4 只是把它显式化。
3. `Role.ADMINISTRATOR` 拿 `frozenset(Permission)` —— **全部 8 个权限，包括 `SEND_ORDER`**。
   这是本 plan 最需要小心的一行（见下文「最可能被误用的治理漏洞」）。
4. `Role.VIEWER` 与 `Role.TRADER` 都**没有** `READ_ARTIFACT`。Trader 能下单但看不到私有
   Artifact，这是刻意的。

**本 plan 不新增 Permission 枚举值，不改 `default()`。** 泛化在服务层做，理由：
新增 `APPROVE_TIMING` / `APPROVE_RISK` 会让「Reviewer 能批准什么」变成两处真源
（枚举 + 服务规则），而两处真源迟早不一致。

### `domain/factor_lifecycle.py`（660 行）—— 审批模板

`ApprovalScope`（4 值）与 `ApprovalDecision`（3 值）：

```python
class ApprovalScope(str, Enum):
    RESEARCH_BACKTEST = "research_backtest"
    SHADOW = "shadow"
    PAPER = "paper"
    LIMITED_LIVE = "limited_live"


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    REQUEST_CHANGES = "request_changes"
```

`PromotionApproval` 的**全部 11 个 init 字段 + 1 个 `init=False`**：

```python
@dataclass(frozen=True)
class PromotionApproval:
    approval_id: str
    factor_version_id: str              # ← Task 4 要泛化的字段：硬绑定到 factor
    validation_report_id: str
    validation_report_hash: str         # 必须是 64 位小写 sha256
    scope: ApprovalScope
    decision: ApprovalDecision
    actor_id: str
    actor_role: str                     # 必须属 _FACTOR_REVIEW_ROLES
    decided_at: datetime                # 必须 timezone-aware
    reason: str                         # 非空
    evidence_hashes: tuple[str, ...]    # 非空、唯一、全部 sha256、排序后存储
    content_hash: str = field(init=False)
```

其中 `_FACTOR_REVIEW_ROLES = frozenset({"reviewer", "administrator"})`（第 22 行），
构造时若 `actor_role` 不在其中直接 `raise PermissionError`。

`authorizes()` 是**授权判定的现成模板**，Task 4 要泛化它：

```python
def authorizes(
    self, *, factor_version_id: str, validation_report: ValidationReport,
    scope: ApprovalScope | str,
) -> bool:
    ...
    return (
        self.decision is ApprovalDecision.APPROVED
        and self.factor_version_id == factor_version_id
        and self.validation_report_id == validation_report.report_id
        and self.validation_report_hash == validation_report.content_hash
        and self.scope is requested_scope
        and validation_report.factor_version_id == factor_version_id
        and validation_report.passes_promotion_gate
    )
```

**注意它现在没有 expiry 检查，也没有 supersede 检查。** 这不是遗漏——P4 时还没有这两个概念。
Step 08 Spec 明确要求 `ApprovalReview` 含 `expiry` 与 `supersedes`，所以 Task 4 泛化时
**必须补上这两条判定**，并且**不能**回改 `PromotionApproval.authorizes()`
（那会让 P4 的既有 Review 记录突然全部过期）。

`FactorLifecycleStatus`（7 值）与合法转移集合：

```python
class FactorLifecycleStatus(str, Enum):
    DRAFT = "draft"
    RESEARCH = "research"
    SHADOW = "shadow"
    CANDIDATE = "candidate"
    PRODUCTION = "production"
    SUSPENDED = "suspended"
    RETIRED = "retired"


_ALLOWED_TRANSITIONS = frozenset({
    (DRAFT, RESEARCH), (RESEARCH, SHADOW), (SHADOW, CANDIDATE),
    (CANDIDATE, PRODUCTION), (PRODUCTION, SUSPENDED),
    (SUSPENDED, PRODUCTION), (SUSPENDED, RETIRED),
})
```

**这个状态机是 Task 3 Incident 状态机的形状参照**（同样的 frozenset-of-pairs 手法），
也是 Task 2 「drift alert 不能改生命周期」测试的断言对象。
注意 `RETIRED` 是终态，`PRODUCTION → RETIRED` **不合法**——必须先 `SUSPENDED`。

### `domain/factor_reviews.py`（150 行）—— 要泛化的评审合同

`FactorPromotionReview` 的**全部 8 个 init 字段 + 1 个 `init=False`**：

```python
@dataclass(frozen=True)
class FactorPromotionReview:
    """Append-only audit record; it never grants broker or order authority."""

    review_id: str
    factor_version_id: str
    factor_version_hash: str            # sha256
    factor_lifecycle_status: FactorLifecycleStatus
    validation_report_id: str
    validation_report_hash: str         # sha256
    scientific_gate_passed: bool
    approval: PromotionApproval
    content_hash: str = field(init=False)
```

`__post_init__` 的守卫，逐条（这些是泛化时必须保住的语义）：

```python
status = FactorLifecycleStatus(self.factor_lifecycle_status)
if status is not FactorLifecycleStatus.CANDIDATE:
    raise ValueError("factor promotion review requires candidate lifecycle status")
if type(self.scientific_gate_passed) is not bool:
    raise TypeError("scientific_gate_passed must be a boolean")
if self.review_id != self.approval.approval_id:
    raise ValueError("review_id must equal approval_id")
if self.factor_version_id != self.approval.factor_version_id:
    raise ValueError("review and approval target different FactorVersions")
if self.validation_report_id != self.approval.validation_report_id:
    raise ValueError("review and approval target different ValidationReports")
if self.validation_report_hash != self.approval.validation_report_hash:
    raise ValueError("review and approval bind different ValidationReport hashes")
if self.approval.actor_role not in {"reviewer", "administrator"}:
    raise PermissionError(
        "factor review service requires Reviewer or Administrator authority"
    )
if (self.approval.decision is ApprovalDecision.APPROVED
        and not self.scientific_gate_passed):
    raise ValueError("approval cannot override a failed scientific gate")
```

以及两个恒假属性：

```python
@property
def grants_account_access(self) -> bool: return False
@property
def grants_order_authority(self) -> bool: return False
```

**`factor_lifecycle_status is CANDIDATE` 这条硬要求是泛化的核心难点。**
它对 factor 是对的（SPEC-023 的生命周期里 `CANDIDATE → PRODUCTION` 是唯一的晋级边），
但对 Portfolio 或 Risk Model 没有对应概念——`PortfolioPolicy` 没有生命周期枚举。
Task 4 的设计必须让 subject-specific 的前置条件**由 subject 自己声明**，
而不是在通用合同里写一个对 3/4 的 subject 都错的检查。

### `application/factor_reviews.py`（116 行）—— 要泛化的服务

```python
class FactorReviewDenied(PermissionError):
    """The principal is not a human Reviewer for this use case."""

class InvalidFactorReview(ValueError):
    """The requested decision violates evidence, scope, or lifecycle contracts."""

class FactorReviewService:
    def __init__(self, repository: FactorReviewRepository,
                 permission_policy: PermissionPolicy | None = None) -> None: ...

    def record_review(self, *, factor_version: FactorVersion,
        validation_report: ValidationReport, approval_id: str,
        scope: ApprovalScope | str, decision: ApprovalDecision | str,
        principal: Principal, decided_at: datetime, reason: str,
        evidence_hashes: tuple[str, ...],
    ) -> FactorPromotionReview: ...

    def get_review(self, review_id: str) -> FactorPromotionReview | None: ...
    def list_reviews(self) -> tuple[FactorPromotionReview, ...]: ...
```

`FactorReviewDenied` 的**完整触发路径**（第 53–61 行，逐字）：

```python
review_roles = principal.roles.intersection({Role.REVIEWER, Role.ADMINISTRATOR})
if not review_roles or not self._permission_policy.allows(
    principal, Permission.APPROVE_RESEARCH
):
    raise FactorReviewDenied(
        f"subject {principal.subject_id} has no factor review authority"
    )
```

**两个条件是 AND**：既要有角色，又要有权限。这是好设计——角色集合与权限矩阵互为
交叉校验，任一处被误改都不足以打开门。Task 4 的泛化版必须保持这个 AND 结构。

服务层的其余检查（Task 4 要按 subject 泛化的部分）：

```python
if factor_version.status is not FactorLifecycleStatus.CANDIDATE:
    raise InvalidFactorReview("factor promotion review requires candidate lifecycle")
if validation_report.factor_version_id != factor_version.factor_version_id:
    raise InvalidFactorReview("validation report targets another FactorVersion")
if (selected_decision is ApprovalDecision.APPROVED
        and not validation_report.passes_promotion_gate):
    raise InvalidFactorReview("approval cannot override failed scientific validation")
if decided_at < validation_report.created_at:
    raise InvalidFactorReview("review decision cannot precede ValidationReport")
```

**注意：这里没有职责分离检查。** `principal.subject_id` 只被写进
`PromotionApproval.actor_id`，**从来没有和「谁提交的」比较过**——因为
`FactorVersion.created_by` 存在（第 491 行）但服务从不读它。
这是本 plan 要补的第一个真实漏洞，见 Task 4 Step 2。

### `domain/desk.py` 与 `application/desk_projection.py` —— 两个待兑现的 P9 blocker

`DeskSectionKey` 的**七个值，逐字**：

```python
class DeskSectionKey(StrEnum):
    """The seven prototype sections, ordered as they appear in the 1440 design."""
    DATA_HEALTH = "data_health"
    SCREEN_SHIFTS = "screen_shifts"
    PORTFOLIO_TRACKING = "portfolio_tracking"
    TIMING_SHADOW = "timing_shadow"
    EVENT_FEED = "event_feed"
    PENDING_TASKS = "pending_tasks"
    ACTIVE_FAILURES = "active_failures"
```

`_pending_tasks()` 当前只读因子审核（第 267–307 行），并挂着这个 blocker：

```python
_blocker(
    "P9_GENERAL_APPROVAL_QUEUE_NOT_IMPLEMENTED",
    "当前只覆盖因子晋级审核；通用审批与任务队列属 P9，尚未实现。",
    "governance.approval_queue",
)
```

`_active_failures()` 当前只读摄取作业失败（第 309–349 行），挂着：

```python
_blocker(
    "P9_INCIDENT_LEDGER_NOT_IMPLEMENTED",
    "当前只覆盖摄取作业失败；通用 Incident 账本属 P9，尚未实现。",
    "observation.incidents",
)
```

**这两个 blocker code 就是本 plan 的两个验收锚点。** Task 3 完成后
`P9_INCIDENT_LEDGER_NOT_IMPLEMENTED` 必须消失；Task 4 完成后
`P9_GENERAL_APPROVAL_QUEUE_NOT_IMPLEMENTED` 必须消失。
**它们消失的条件是真实实现，不是把字符串删掉。**

同时注意 `_active_failures()` 现在的筛选逻辑：

```python
failing = tuple(job for job in jobs if job.failure_reasons or job.status == "failed")
```

这是**逐条列举**，没有去重。500 个作业因同一个 provider 限流失败会显示 500 行。
Task 3 的 dedupe 正是要解决这个——但要注意 desk 分区的 `coverage` 必须同时保留
`jobs_failing` 的**原始计数**与去重后的 Incident 数，否则去重会看起来像故障消失了。

`DeskSectionStatus` 四值与 `DeskSection.__post_init__` 的三条强制规则（Task 5 复用）：

```python
if self.status is DeskSectionStatus.PARTIAL and not (self.coverage or blockers):
    raise ValueError(f"section {self.key.value} is partial and must declare coverage or a blocker")
if self.status is DeskSectionStatus.UNAVAILABLE and not blockers:
    raise ValueError(f"section {self.key.value} is unavailable and must declare a blocker")
if self.status in (READY, PARTIAL) and self.payload is None:
    raise ValueError(...)
elif self.payload is not None:
    raise ValueError(...)   # empty / unavailable 不得带 payload
```

### `ports/system_catalog.py`（23 行）—— Drift 的数据侧输入

```python
class SystemCatalogReader(Protocol):
    def list_datasets(self) -> tuple[DatasetCatalogEntry, ...]: ...
    def list_quality_reports(self) -> tuple[QualityReportEntry, ...]: ...
    def list_lineage(self) -> tuple[LineageCatalogEntry, ...]: ...
    def list_jobs(self) -> tuple[IngestionJobEntry, ...]: ...
```

### `domain/metrics.py` —— 已有的质量语义，不要重造

```python
class QualitySeverity(str, Enum):
    WARNING = "warning"
    BLOCK = "block"

class QualityStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
```

**Task 3 的 `AlertSeverity` 不能直接复用 `QualitySeverity`**（两值不足以表达 ADR-0009
要求的升级时限分级），但 `UNAVAILABLE` 这个第三态的设计语言必须保持一致。

### 确认不存在（本 plan 新建）

```text
domain/monitoring.py                    # DriftObservation、ThresholdPolicy、监控计算
domain/incidents.py                     # Alert、Incident、状态机
domain/approvals.py                     # 泛化的 ApprovalReview、ApprovalSubject
domain/serving.py                       # ServingRegistration、rollback target
application/unified_attribution.py      # 归因编排（Timing/Event 接入）
application/drift_monitoring.py          # 漂移编排
application/incident_service.py         # Alert → Incident 编排
application/approval_service.py         # 泛化审批服务（SoD、expiry、supersede）
application/serving_registry.py         # 用途隔离的 serving 注册
application/monitoring_workspace.py     # Monitoring 六页投影
application/governance_workspace.py     # Users/Entitlements/Approvals 三页投影
ports/monitoring.py                     # drift / alert / incident repository
ports/approvals.py                      # 泛化 review repository
ports/serving.py
adapters/memory/monitoring.py           # + Unavailable* 变体
adapters/memory/approvals.py
adapters/postgres/monitoring.py
adapters/postgres/approvals.py
validation/monitoring_crosscheck.py     # PSI / KS 的 scipy 对照
workers/drift_monitoring.py
workers/fault_injection.py              # Task 6，只写 research stage
migrations/0039_p9_unified_attribution.sql
migrations/0040_p9_monitoring_and_incidents.sql
migrations/0041_p9_generalised_approvals.sql
frontend/src/pages/MonitoringWorkspace.tsx
frontend/src/features/monitoring/*      # 六页
frontend/src/features/governance/*      # 三页
scripts/verify_monitoring_browser.py
```

## 原型参照（真实文本，逐字提取）

`docs/assets/prototype/figma-node-summary.json` 的 `frames` 是 dict，键为 node id。
本 plan 的 11 页中**只有两页有精确 Frame**：`9:883`（Approvals）与 `9:661`（Quality/Lineage，
本 plan 只借它的血缘钻取语言）。**Monitoring 六页、Correlation、Production、Users、
Entitlements 全部无独立 Frame**，故 `design_status` 永久保持 `missing`，只记录设计假设。

两个 Frame 均为 1440×1200。

### `9:883` = `14-approvals-reviewer-queue`

从 summary 的 TEXT 节点逐字提取：

| 区域 | 真实文本 |
|---|---|
| 面包屑 | `SYSTEM / P4-P9 · GOVERNANCE` |
| 标题 | `Approvals · Reviewer Queue` / `因子、模型、InvestmentView、Timing 与用途审批集中处理` |
| 四张摘要卡 | `Pending` `7` `Factor3 · View4`；`Approved Research` `6` `仅 research_backtest`；`Rejected` `4` `保留完整理由`；`Production` `0` `无 Shadow/Paper 晋级` |
| 队列标题 | `审批队列 · server-owned reviewer path` |
| 队列列（8 列） | `Review` `对象` `版本` `用途` `提交人` `证据` `Reviewer` `状态` |
| 对象类型（4 类） | `Factor` `Alpha Model` `InvestmentView` `Timing` |
| 用途值（3 类） | `research_backtest` `shadow` `paper` |
| 提交人 | `User-1` `User-2` `User-3` |
| 证据 | `完整` / `缺失` |
| Reviewer | `Unassigned` / `Reviewer-1` / `Reviewer-2` |
| 状态（4 值） | `Pending` `Approved` `Rejected` `Blocked` |
| 规则卡标题 | `审批规则` |
| 四条规则 | `服务端决定` READY `批准/拒绝/撤回有身份、时间和理由`；`用途精确` READY `research/shadow/paper 不可提升`；`证据不足` BLOCKER `禁用决定并列出全部 blocker`；`版本不可变` ATTENTION `修改产生新版本与新审查` |
| 边界卡 | `可信使用边界` / `前端隐藏按钮不能替代权限校验；` / `当前无真实账户或 Limited Live 授权。` |
| 五段流程条 | `INPUT · 输入` `对象版本/用途` `证据/身份`；`PROCESS · 处理` `Reviewer决定` `理由→scope→撤回`；`OUTPUT · 输出` `append-only Review` `用途审批记录`；`ACTION · 操作` `批准/拒绝/撤回` `打开证据抽屉`；`GATE · 门禁` `证据不足禁用` `版本修改重审` |
| 页脚 | `Prototype Notes · P4/P5/P7/P9 服务端治理 · 测试通过不等于模型科学有效` |

**三个设计洞察，Task 4/5 必须处理：**

1. **原型的 `提交人` 列是本 plan 最重要的设计输入。** 它证明设计者本来就打算区分
   提交人与 Reviewer——`User-1` 提交、`Reviewer-2` 审批。而当前代码里
   `FactorReviewService` **从不比较这两者**。原型比实现更严格，这次要照原型做。
2. **状态有第四个值 `Blocked`**，而 `ApprovalDecision` 只有三值
   （`APPROVED` / `REJECTED` / `REQUEST_CHANGES`）。`Blocked` 不是一个决定，
   是「证据不足所以不能做决定」的**队列状态**。Task 5 的投影必须把它算成
   `pending + evidence_incomplete`，**不得**新增 `ApprovalDecision.BLOCKED`——
   那会让「系统拒绝」与「人拒绝」变成同一个值。
3. `REV-1500`–`REV-1510`、`User-1`–`User-3`、`Reviewer-1`/`Reviewer-2`、
   `Pending 7`/`Approved 6`/`Rejected 4`/`Production 0` **全部是 design fixture**。
   Frame 自己标了 `PROTOTYPE ONLY` `DESIGN FIXTURE` `非生产数据`
   `不代表 PIT / 科学有效`。零泄漏。

### `9:661` = `13-data-quality-lineage`

本 plan 只借它的两条语言（Drift 页的 blocker 传播文案要与之一致）：

| 区域 | 真实文本 |
|---|---|
| 面包屑 | `SYSTEM / P2-P3 · DATA TRUST` |
| 四条状态 | `阻断传播` BLOCKER `严重错误阻止 Factor/View/Backtest`；`警告传播` ATTENTION `关键数字旁展示 warning 与 evidence`；`双时间血缘` READY `effective/period 与 available_at 分开`；`空期守卫` READY `有原始行但全 unmapped 不是合法空期` |
| 边界卡 | `可信使用边界` / `Current source 的 trust ceiling 不能提升；` / `关键 evidence 断链即 fail closed。` |
| 表列 | `Check` `Dataset` `规则` `结果` `影响` `报告版本` `Run` `时间` |
| `影响` 两值 | `Current warning` / `Strict downstream` |

`Q-1300`–`Q-1309`、`RUN-1400`–`RUN-1409`、`184`/`169`/`12`/`3` 是 design fixture。

### `docs/18` §3.5 的 Monitoring 七页 Gate（逐字，Task 5 的验收条款）

| 页面 | 页面作用 | Gate |
|---|---|---|
| Signals | Snapshot 新鲜度、覆盖、失效和排名变化 | 无真实 Snapshot 时计数必须为 0 |
| Portfolios | 目标与观测持仓、风险、现金和限制偏离 | 无真实账户连接；Intent 不是 Order |
| Timing | 每日冻结 Forecast、Outcome 和 Calibration | `no edit/no backfill`；晋级前组合影响 0% |
| Drift | dataset/feature/model/calibration 的 coverage、PSI、IC decay 和 Brier | 只阻断或创建 Review，不静默改模型 |
| Rebalance | Signal/Risk/Policy 变化形成原因链和研究意图 | T+1 等规则生效；没有下单按钮 |
| Execution | Paper Intent、状态机、Fill、Fee 和 reconciliation | 真实账户未连接且不可配置 |
| Incidents | Data/Model/Portfolio/Jobs 异常的 owner、缓解、恢复和复盘 | 严重质量问题阻断下游 |

**Execution 属 P10，本 plan 不实现**，保持阶段 blocker。

## 四个必须先想清楚的设计陷阱

本 plan 的多数篇幅在防这四件事。它们不是实现细节，是决定监控系统是装饰品还是真工具的前提。

### 陷阱一：残差被吸收，归因悄悄变成虚构

归因分解的分项和永远不会精确等于实测主动收益。差额（residual）有三种可能来源：
数值精度、模型不完备、以及**实现缺陷**。第三种是唯一重要的那种。

如果实现里有一个 `other` 或 `unexplained` 分项，残差就永远等于 0——因为它被定义成
「剩下的那部分」。此时归因**永远闭合**，闭合检查**永远通过**，
而闭合这件事本身**不再携带任何信息**。

这不是理论风险。它是归因系统最常见的失效方式，且失效后毫无症状：
瀑布图漂亮、总和精确、每次运行都绿。**唯一能发现它的方法是断言 `other` 分项不存在。**

P-5 已经在 core attribution 里立了规矩（`ClosureStatus.FAILED`）。本 plan 的风险更高，
因为 unified 加了 timing 与 event 两个分项，而这两个的贡献本身就难算——
把算不准的部分丢进 residual、再把 residual 丢进 other，是极自然的滑坡。

**Task 1 的防线有三层**：

1. `UnifiedAttributionSnapshot` 的分项集合是**封闭枚举**，没有 `other`，
   且有一个测试直接断言枚举里不含任何 catch-all 名字；
2. residual 是**独立字段**，不是分项，且必须携带 `residual_evidence_ids`
   （这个模式 `InvestmentView` 已经用了，见 `domain/investment_view.py` 的
   `reconciled_expected_return` 与 `residual_evidence_ids`）；
3. residual 超 `ThresholdPolicy` 的容差 → `ClosureStatus.FAILED` **且**创建 Incident。
   Task 1 Step 8 有一个测试直接断言 Incident 被创建，而不只是状态被标红。

### 陷阱二：阈值硬编码，于是「什么算 Incident」可以无痕改变

`psi > 0.25` 写在代码里，看起来像常识（0.25 是行业惯用的 PSI 显著阈值）。
但它意味着：某天有人把它改成 0.35，昨天的 Incident 今天不再是 Incident，
**而两次运行在任何账本里都看不出差别**。

更隐蔽的版本：阈值写在配置文件里但配置不进 hash。此时同一个 `run_id`
在不同时间跑会给出不同的 Incident 集合，而 `run_id` 本该唯一确定输出。

Step 08 的决策把这条写得很清楚：「SLO、PSI、IC decay、calibration、residual 阈值为 D2，
按 subject/version 配置」。**D2 意味着可配置，不意味着可无痕修改。**

**Task 2 的防线**：`ThresholdPolicy` 是 content-addressed 值对象，
`content_hash` 覆盖全部阈值；`DriftObservation` 携带 `threshold_policy_hash`；
有一个测试断言改任何一个阈值都产生新 hash；还有一个测试断言
两个 `DriftObservation` 若 `threshold_policy_hash` 不同则**不可比较**
（比较会 raise，而不是返回 False）。

### 陷阱三：同一根因刷 500 条 Incident，于是没人看 Incident

一次 provider 限流会让 500 个作业同时失败。一次 dataset 陈旧会让 12 个特征同时漂移。
如果每个失败都是一条 Incident，Incident 列表在第一次真实故障后就永久不可用——
而且这时**真正的第二个故障会被埋在噪声里**。

当前 `_active_failures()` 就是这个形状：`for job in jobs if job.failure_reasons`。

去重的难点不是实现，是**去重键的选择**。键太粗（比如只用 `owner_scope`）会把两个
不相关的故障合并，掩盖第二个；键太细（比如含时间戳）等于不去重。

**Task 3 的设计**：`Alert.dedupe_key` 由 `(subject_id, subject_version, metric_name,
owner_scope)` 组成，**不含时间**、**不含具体数值**。同一 key 的第 2 到第 500 次触发
递增 `occurrence_count` 并更新 `last_seen_at`，**不创建新 Incident**。
`first_seen_at` 永不改变（SPEC-040 要求「告警有 owner、severity、首次时间」）。

**但去重不得掩盖规模。** 500 次触发的 Incident 必须显示 `occurrence_count == 500`，
否则去重就变成了信息丢失。Task 3 有一个测试专门断言这一点。

### 陷阱四：监控偷偷修模型，于是没人知道生产在跑什么

这是本 plan 唯一的**不可逆**风险，也是 Step 08 Spec 唯一用「非目标」措辞强调的一条：
「监控不静默改模型/权重」。

诱惑很具体：IC 衰减了，把因子权重调低一点；校准漂了，把概率做个 recalibration；
exposure 超限了，把目标权重截一下。每一个都「显然是对的」，
每一个都让生产在跑的东西与被批准的东西不一致，
而**审计追溯会指向那个已批准的版本**——追溯本身变成了谎言。

**Task 2 的防线是结构性的，不是纪律性的**：漂移计算函数是纯函数，
签名里根本没有可写入的对象；`DriftObservation` 是 frozen dataclass；
Alert 的动作枚举只有三个值：

```python
class AlertAction(StrEnum):
    BLOCK_DOWNSTREAM = "block_downstream"
    REQUEST_REVIEW = "request_review"
    EXECUTE_APPROVED_ROLLBACK = "execute_approved_rollback"
```

没有 `ADJUST_WEIGHT`，没有 `RECALIBRATE`，没有 `SUSPEND_MODEL`。
第三个值 `EXECUTE_APPROVED_ROLLBACK` 是唯一能改变运行时行为的动作，
且它要求一个**已存在的、已批准的、未过期的** `ServingRegistration.rollback_target`——
它执行的是别人早先批准的决定，不是它自己的判断。

Task 2 Step 9 有两个测试直接断言：drift alert 不能改 `FactorVersion`，
不能改 `TargetPortfolioSnapshot`。

---

### Task 1: `UnifiedAttribution` —— 从 core 扩到 Timing/Event，residual 产生 Incident

对应 Step 08 Task 1：「预计新增 `domain/attribution.py`、application/ports/repositories/
migration/tests；从 P6 core 扩展 Timing/Event，execution 保持 not_applicable；
先 daily，再 cumulative，再 residual Incident。」

**顺序不能变：daily → cumulative → residual Incident。** P-5 的 plan 已经解释过前两步的
顺序理由（累计闭合可以在日度不闭合的情况下成立，因为误差抵消）。本 plan 加第三步的理由是：
residual Incident 依赖 Task 3 的 Incident 合同，而 Task 3 又要用 Task 1 的残差做第一个真实
Alert 源。**破解办法**：Task 1 Step 8 只定义 residual 超限时**应当发出的信号**
（一个纯值对象 `AttributionClosureBreach`），Task 3 再把它接到 Incident 上。
这样两个 Task 都可以独立 TDD，且没有循环依赖。

**Files:**
- Modify: `platform/src/a_share_platform/domain/attribution.py`（P-5 已建，本 plan 扩展）
- Create: `platform/src/a_share_platform/application/unified_attribution.py`
- Create: `platform/src/a_share_platform/ports/monitoring.py`（含 attribution repository）
- Test: `platform/tests/test_unified_attribution.py`
- Test: `platform/tests/test_unified_attribution_orchestration.py`

**Interfaces:**
- Consumes: P-5 的 `AttributionComponent` / `AttributionComponentStatus` / `ClosureStatus` /
  `attribute_session()` / `accumulate_attribution()`；P-6 的 `TimingForecast`；P-7 的 `EventStudy`
- Produces:
  ```python
  class AttributionScope(StrEnum):
      CORE_ONLY = "core_only"        # P-5 产出的那个字符串，保持兼容
      UNIFIED = "unified"

  UNIFIED_COMPONENTS: tuple[str, ...] = (
      "market", "industry", "style", "selection",
      "timing", "event", "cost", "execution",
  )
  # SPEC-039 的八分项，逐字对应「市场、行业、风格、选股、主动择时、事件、成本和执行」。
  # 注意这里没有 "other" / "unexplained" / "residual" —— residual 是快照上的独立字段。

  @dataclass(frozen=True)
  class AttributionLayer(StrEnum):
      FORECAST_VS_REALIZED = "forecast_vs_realized"
      MODEL_VS_PORTFOLIO = "model_vs_portfolio"
  # Step 08 Spec：「forecast vs realized、model vs portfolio 两层归因」

  @dataclass(frozen=True)
  class AttributionClosureBreach:
      """A closure failure, as a value.  Task 3 turns this into an Incident."""
      snapshot_id: str
      layer: AttributionLayer
      session: date | None            # None 表示累计层面
      residual: Decimal
      tolerance: Decimal
      threshold_policy_hash: str
      owner_scope: str                # 必须是 ADR-0009 四值之一
      evidence_ids: tuple[str, ...]

  @dataclass(frozen=True)
  class UnifiedAttributionSnapshot:
      snapshot_id: str
      scope: AttributionScope
      layer: AttributionLayer
      components: tuple[AttributionComponent, ...]   # 恰好 8 个，顺序固定
      residual: Decimal
      residual_evidence_ids: tuple[str, ...]
      closure_status: ClosureStatus
      breach: AttributionClosureBreach | None
      threshold_policy_hash: str
      content_hash: str = field(init=False)

  def attribute_session_unified(...) -> UnifiedAttributionSnapshot
  def accumulate_unified_attribution(...) -> UnifiedAttributionSnapshot
  ```

- [ ] **Step 1: 先读 P-5 交付的真实 attribution 合同**

```bash
cd platform
grep -n "^class \|^def \|^@dataclass" src/a_share_platform/domain/attribution.py
grep -n "class AttributionComponentStatus" -A8 src/a_share_platform/domain/attribution.py
grep -n "class ClosureStatus" -A6 src/a_share_platform/domain/attribution.py
grep -n "def attribute_session" -A20 src/a_share_platform/domain/attribution.py
grep -n "core_only" -r src/ tests/
```

**以代码为准。** P-5 的 plan 声明了 `AttributionComponent` / `ClosureStatus` /
`attribute_session` / `accumulate_attribution`，但字段可能与 plan 描述不同。
若不同，改本 Task 的后续步骤。

若 `domain/attribution.py` **不存在** → 回到前置条件，先做 P-5。

- [ ] **Step 2: 写红测 —— 没有 catch-all 分项（本 Task 最重要的一个测试）**

```python
# platform/tests/test_unified_attribution.py
"""Unified attribution: eight named components, one residual, no catch-all.

The single most damaging failure mode of an attribution system is an 'other'
bucket.  With one, the residual is always zero by construction, the closure check
always passes, and closure stops carrying any information at all — while the
waterfall chart looks perfect and every run is green.  There are no symptoms.

So the component set is a closed tuple and a test asserts no catch-all name is in
it.  The residual is a separate field carrying its own evidence, the way
InvestmentView already does it, so an unexplained remainder is visible as a
remainder rather than dressed up as a factor.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from a_share_platform.domain.attribution import (
    UNIFIED_COMPONENTS,
    AttributionComponentStatus,
    AttributionLayer,
    AttributionScope,
    ClosureStatus,
    UnifiedAttributionSnapshot,
    accumulate_unified_attribution,
    attribute_session_unified,
)


class ComponentSchemaTest(unittest.TestCase):
    def test_the_component_set_has_no_catch_all_bucket(self) -> None:
        """This is the test that keeps attribution honest.

        Any of these names would make the residual zero by definition, which is
        the same as deleting the closure check while leaving it looking green.
        """
        forbidden = {
            "other", "others", "unexplained", "unattributed", "misc",
            "residual", "remainder", "balance", "plug", "adjustment",
        }
        self.assertEqual(set(UNIFIED_COMPONENTS) & forbidden, set())

    def test_the_component_set_is_exactly_the_spec_039_eight(self) -> None:
        """SPEC-039 逐字：市场、行业、风格、选股、主动择时、事件、成本和执行."""
        self.assertEqual(
            UNIFIED_COMPONENTS,
            ("market", "industry", "style", "selection",
             "timing", "event", "cost", "execution"),
        )

    def test_every_snapshot_carries_all_eight_components(self) -> None:
        """SPEC-039: 归因 schema 从第一版保留全部分项.

        A component that disappears when it has nothing to say makes its absence
        indistinguishable from a projection bug.
        """
        snapshot = attribute_session_unified(**_closing_session_inputs())
        self.assertEqual(
            tuple(item.name for item in snapshot.components), UNIFIED_COMPONENTS
        )

    def test_residual_is_a_field_not_a_component(self) -> None:
        snapshot = attribute_session_unified(**_closing_session_inputs())
        self.assertNotIn("residual", {item.name for item in snapshot.components})
        self.assertIsInstance(snapshot.residual, Decimal)

    def test_a_nonzero_residual_requires_evidence_ids(self) -> None:
        """An unexplained remainder with no pointer to what produced it cannot be
        investigated, so it would be permanently tolerated."""
        with self.assertRaises(ValueError):
            UnifiedAttributionSnapshot(
                snapshot_id="attribution:unified:test",
                scope=AttributionScope.UNIFIED,
                layer=AttributionLayer.MODEL_VS_PORTFOLIO,
                components=_eight_components(),
                residual=Decimal("0.0004"),
                residual_evidence_ids=(),
                closure_status=ClosureStatus.CLOSED,
                breach=None,
                threshold_policy_hash="0" * 64,
            )
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_unified_attribution -v`

Expected: FAIL —— `ImportError: cannot import name 'UNIFIED_COMPONENTS'`。
把真实错误文本抄进 Evidence。

- [ ] **Step 4: 最小实现 —— 只做分项集合与快照校验**

**不要**一次实现两层归因与累计。只让 Step 2 的五个测试转绿。

- [ ] **Step 5: daily 闭合（红测先行）**

```python
SESSION = date(2026, 8, 14)
ACTIVE_RETURN = Decimal("0.0246")

# The hand computation quoted in the first test, as data.  Seven quantified
# contributions; execution is absent on purpose because the function declares it
# not_applicable until Paper exists.
CLOSING_CONTRIBUTIONS: tuple[tuple[str, str], ...] = (
    ("market", "0.0182"),
    ("industry", "0.0031"),
    ("style", "-0.0012"),
    ("selection", "0.0048"),
    ("timing", "0.0021"),
    ("event", "-0.0006"),
    ("cost", "-0.0018"),
)


def _inputs(
    *,
    active_return: Decimal = ACTIVE_RETURN + Decimal("0.0004"),
    tolerance: Decimal = Decimal("0.0005"),
    contributions: tuple[tuple[str, str], ...] = CLOSING_CONTRIBUTIONS,
) -> dict[str, object]:
    """Keyword inputs for attribute_session_unified.

    The default leaves a residual of exactly 0.0004 — small enough to close
    under a loose tolerance and large enough to fail under a tight one — so the
    tolerance tests vary one argument and nothing else.
    """
    return {
        "snapshot_id": f"attribution:unified:{active_return}:{tolerance}",
        "layer": AttributionLayer.MODEL_VS_PORTFOLIO,
        "session": SESSION,
        "measured_active_return": active_return,
        "contributions": tuple(
            (name, Decimal(value)) for name, value in contributions
        ),
        "residual_evidence_ids": ("evidence:portfolio-series:2026-08-14",),
        "evidence_ids": tuple(f"evidence:{name}:2026-08-14" for name, _ in contributions),
        "tolerance": tolerance,
    }


def _closing_session_inputs() -> dict[str, object]:
    """Residual exactly zero: the seven contributions sum to the active return."""
    return _inputs(active_return=ACTIVE_RETURN)


def _breaching_session_inputs() -> dict[str, object]:
    """Residual 0.0031 against a 0.0005 tolerance."""
    return _inputs(active_return=ACTIVE_RETURN + Decimal("0.0031"))


class DailyClosureTest(unittest.TestCase):
    def test_daily_components_plus_residual_reconcile_to_active_return(self) -> None:
        """Hand computation: market +0.0182, industry +0.0031, style -0.0012,
        selection +0.0048, timing +0.0021, event -0.0006, cost -0.0018 sums to
        +0.0246 against a measured active return of +0.0246, residual zero.

        Timing and event are non-zero here because P7/P8 delivered promoted
        models; when they have not, the two components are not_applicable and
        unavailable respectively and the sum has five terms.
        """
        snapshot = attribute_session_unified(**_closing_session_inputs())
        quantified = tuple(
            item
            for item in snapshot.components
            if item.status is AttributionComponentStatus.QUANTIFIED
        )
        self.assertEqual(len(quantified), 7)
        self.assertEqual(
            sum((item.contribution for item in quantified), Decimal(0)),
            Decimal("0.0246"),
        )
        self.assertEqual(snapshot.residual, Decimal(0))
        self.assertEqual(snapshot.closure_status, ClosureStatus.CLOSED)

    def test_a_daily_residual_within_tolerance_closes(self) -> None:
        snapshot = attribute_session_unified(**_inputs(tolerance=Decimal("0.001")))
        self.assertEqual(snapshot.residual, Decimal("0.0004"))
        self.assertEqual(snapshot.closure_status, ClosureStatus.CLOSED)
        self.assertIsNone(snapshot.breach)

    def test_a_daily_residual_over_tolerance_fails_that_session(self) -> None:
        """SPEC-039 acceptance 逐字：无法闭合时标记 failed，
        不发布"解释性"图表冒充闭合归因."""
        snapshot = attribute_session_unified(**_breaching_session_inputs())
        self.assertEqual(snapshot.closure_status, ClosureStatus.FAILED)

    def test_tolerance_comes_from_the_threshold_policy_not_a_constant(self) -> None:
        """A hardcoded tolerance means changing what counts as a closure failure
        leaves no trace.  Two snapshots under different tolerances must be
        distinguishable by their policy hash."""
        tight = attribute_session_unified(**_inputs(tolerance=Decimal("0.00001")))
        loose = attribute_session_unified(**_inputs(tolerance=Decimal("0.01")))
        self.assertNotEqual(tight.threshold_policy_hash, loose.threshold_policy_hash)
        self.assertEqual(tight.closure_status, ClosureStatus.FAILED)
        self.assertEqual(loose.closure_status, ClosureStatus.CLOSED)
```

- [ ] **Step 6: 三种「无贡献」在 unified 层继续可区分（红测先行）**

P-5 已经为 core 建立了这条规矩；unified 层要**继承而不是重新发明**，
并且要为 execution 立一条新的硬规则。

```python
def _without(*names: str) -> tuple[tuple[str, str], ...]:
    """CLOSING_CONTRIBUTIONS minus the named components.

    Dropping a name means the caller did not supply a contribution for it, which
    is how the function is told to resolve that component's non-quantified
    status from its own rules rather than from a zero.
    """
    excluded = set(names)
    return tuple(
        (name, value) for name, value in CLOSING_CONTRIBUTIONS if name not in excluded
    )


def _snapshot_with(**overrides: object) -> UnifiedAttributionSnapshot:
    """Build a snapshot directly, bypassing attribute_session_unified.

    The constructor is the guard under test in this class, so the tests must be
    able to hand it a combination the orchestrating function would never emit.
    """
    inputs = dict(_closing_session_inputs())
    inputs.update(overrides)
    return UnifiedAttributionSnapshot(**inputs)  # type: ignore[arg-type]


class NonContributionSemanticsTest(unittest.TestCase):
    def test_execution_is_not_applicable_before_paper_never_unavailable(self) -> None:
        """Step 08 Spec 逐字：P9 execution 分项在 Paper 前为 not_applicable.

        This is a deliberate change from P6, where execution read unavailable
        because the module did not exist.  In P9 the module still does not exist,
        but the *reason* is different and the Spec names it: no execution has
        happened, so there is nothing to attribute.  unavailable would say the
        evidence is missing, which would imply it should be chased.
        """
        snapshot = attribute_session_unified(**_closing_session_inputs())
        execution = snapshot.component("execution")
        self.assertEqual(execution.status, AttributionComponentStatus.NOT_APPLICABLE)
        self.assertIsNone(execution.contribution)
        self.assertIsNotNone(execution.status_reason)

    def test_execution_cannot_be_zero_filled(self) -> None:
        """Zero would assert execution ran and cost nothing, which is a claim
        about a system that has not been built."""
        with self.assertRaises(ValueError):
            _snapshot_with(execution_contribution=Decimal(0),
                           execution_status=AttributionComponentStatus.QUANTIFIED)

    def test_timing_is_not_applicable_while_no_model_is_promoted(self) -> None:
        """ADR-0006 decision 7 fixes Shadow timing's portfolio impact at zero, so
        there is genuinely no timing contribution to attribute — as opposed to an
        unmeasured one."""
        snapshot = attribute_session_unified(
            **_inputs(contributions=_without("timing", "event"))
        )
        timing = snapshot.component("timing")
        self.assertEqual(timing.status, AttributionComponentStatus.NOT_APPLICABLE)
        self.assertIsNone(timing.contribution)
        self.assertIn("promoted", timing.status_reason.lower())

    def test_event_is_unavailable_when_p8_has_no_qualified_study(self) -> None:
        """Here unavailable is right: an event contribution exists in principle
        and the evidence to compute it is missing."""
        snapshot = attribute_session_unified(
            **_inputs(contributions=_without("timing", "event"))
        )
        event = snapshot.component("event")
        self.assertEqual(event.status, AttributionComponentStatus.UNAVAILABLE)
        self.assertIsNone(event.contribution)
        self.assertIsNotNone(event.status_reason)

    def test_a_quantified_component_requires_evidence_ids(self) -> None:
        with self.assertRaises(ValueError):
            _snapshot_with(
                market_contribution=Decimal("0.0182"),
                market_status=AttributionComponentStatus.QUANTIFIED,
                market_evidence_ids=(),
            )
```

- [ ] **Step 7: cumulative 闭合与两层归因（红测先行）**

```python
class CumulativeClosureTest(unittest.TestCase):
    def test_cumulative_components_compound_rather_than_sum(self) -> None:
        """Daily contributions do not add across periods any more than returns
        do.  The cross-product has to go somewhere and it must be named."""
        first = attribute_session_unified(**_inputs(active_return=ACTIVE_RETURN))
        second = attribute_session_unified(
            **_inputs(active_return=ACTIVE_RETURN, contributions=CLOSING_CONTRIBUTIONS)
        )
        cumulative = accumulate_unified_attribution(
            snapshot_id="attribution:unified:cumulative:2026-08-14..15",
            snapshots=(first, second),
            tolerance=Decimal("0.0005"),
        )
        market = cumulative.component("market").contribution
        naive_sum = Decimal("0.0182") + Decimal("0.0182")
        compounded = (Decimal(1) + Decimal("0.0182")) ** 2 - Decimal(1)
        self.assertNotEqual(market, naive_sum)
        self.assertEqual(market.quantize(Decimal("0.000001")),
                         compounded.quantize(Decimal("0.000001")))

    def test_a_failed_session_is_named_in_the_cumulative_result(self) -> None:
        """One failing session must not be averaged away by twenty good ones."""
        good = attribute_session_unified(**_closing_session_inputs())
        bad = attribute_session_unified(**_breaching_session_inputs())
        cumulative = accumulate_unified_attribution(
            snapshot_id="attribution:unified:cumulative:with-failure",
            snapshots=(good, bad),
            tolerance=Decimal("0.0005"),
        )
        self.assertEqual(cumulative.closure_status, ClosureStatus.FAILED)
        self.assertIsNotNone(cumulative.breach)
        self.assertIn(bad.snapshot_id, cumulative.breach.evidence_ids)

    def test_cumulative_closure_is_checked_independently_of_daily(self) -> None:
        # Two sessions whose residuals each pass their daily tolerance but whose
        # signs agree, so the cumulative residual is twice as large.
        drifting = _inputs(active_return=ACTIVE_RETURN + Decimal("0.0004"),
                           tolerance=Decimal("0.0005"))
        first = attribute_session_unified(**drifting)
        second = attribute_session_unified(**drifting)
        self.assertEqual(first.closure_status, ClosureStatus.CLOSED)
        self.assertEqual(second.closure_status, ClosureStatus.CLOSED)
        cumulative = accumulate_unified_attribution(
            snapshot_id="attribution:unified:cumulative:drifting",
            snapshots=(first, second),
            tolerance=Decimal("0.0005"),
        )
        self.assertEqual(cumulative.closure_status, ClosureStatus.FAILED)


class TwoLayerAttributionTest(unittest.TestCase):
    def test_forecast_vs_realized_and_model_vs_portfolio_are_separate_snapshots(
        self,
    ) -> None:
        """Step 08 Spec: forecast vs realized、model vs portfolio 两层归因.

        They answer different questions — was the prediction right, and did the
        portfolio express the prediction — and a single blended snapshot cannot
        distinguish a good model implemented badly from a bad model implemented
        well.  Those two situations need opposite responses.
        """
        forecast = attribute_session_unified(
            **{
                **_closing_session_inputs(),
                "snapshot_id": "attribution:unified:forecast:2026-08-14",
                "layer": AttributionLayer.FORECAST_VS_REALIZED,
            }
        )
        portfolio = attribute_session_unified(
            **{
                **_closing_session_inputs(),
                "snapshot_id": "attribution:unified:portfolio:2026-08-14",
                "layer": AttributionLayer.MODEL_VS_PORTFOLIO,
            }
        )
        self.assertNotEqual(forecast.snapshot_id, portfolio.snapshot_id)
        self.assertNotEqual(forecast.content_hash, portfolio.content_hash)

    def test_each_layer_closes_independently(self) -> None:
        """A closing portfolio layer says nothing about the forecast layer."""
        inputs = dict(_closing_session_inputs())
        portfolio = attribute_session_unified(
            **{**inputs, "layer": AttributionLayer.MODEL_VS_PORTFOLIO}
        )
        forecast = attribute_session_unified(
            **{
                **_breaching_session_inputs(),
                "layer": AttributionLayer.FORECAST_VS_REALIZED,
            }
        )
        self.assertEqual(portfolio.closure_status, ClosureStatus.CLOSED)
        self.assertEqual(forecast.closure_status, ClosureStatus.FAILED)

    def test_a_layer_with_no_forecast_reports_unavailable_not_closed(self) -> None:
        """No InvestmentView means the forecast layer cannot be computed.  Calling
        that closed would assert a decomposition that was never attempted."""
        snapshot = attribute_session_unified(
            **{
                **_closing_session_inputs(),
                "layer": AttributionLayer.FORECAST_VS_REALIZED,
                "measured_active_return": None,
            }
        )
        self.assertEqual(snapshot.closure_status, ClosureStatus.UNAVAILABLE)
        self.assertIsNone(snapshot.breach)
        for component in snapshot.components:
            with self.subTest(component=component.name):
                self.assertIsNone(component.contribution)
```

- [ ] **Step 8: residual breach 成为可传递的值（红测先行）**

**这一步不接 Incident**，只产出 `AttributionClosureBreach`。Task 3 消费它。

```python
class ClosureBreachTest(unittest.TestCase):
    def test_a_failed_closure_produces_a_breach_value(self) -> None:
        """Step 08 Spec 逐字：residual 超阈值创建 blocker/Incident，
        不被"其他"吞掉.

        The breach is emitted as a value rather than written as an Incident here,
        so this task and the incident state machine can be built and tested
        independently.  Task 3 consumes it.
        """
        snapshot = attribute_session_unified(**_breaching_session_inputs())
        self.assertEqual(snapshot.closure_status, ClosureStatus.FAILED)
        self.assertIsNotNone(snapshot.breach)
        self.assertEqual(snapshot.breach.residual, snapshot.residual)

    def test_a_closed_snapshot_carries_no_breach(self) -> None:
        snapshot = attribute_session_unified(**_closing_session_inputs())
        self.assertEqual(snapshot.closure_status, ClosureStatus.CLOSED)
        self.assertIsNone(snapshot.breach)

    def test_the_breach_names_an_adr_0009_owner_scope(self) -> None:
        """ADR-0009: 非执行归因归 portfolio owner.

        An unrouted breach is a breach nobody owns, and the ADR exists precisely
        because 'system error' is not an actionable owner.
        """
        snapshot = attribute_session_unified(**_breaching_session_inputs())
        self.assertEqual(snapshot.breach.owner_scope, "portfolio")

    def test_a_breach_cannot_be_constructed_without_a_tolerance(self) -> None:
        """A breach that does not state what it exceeded cannot be reproduced."""
        with self.assertRaises(ValueError):
            AttributionClosureBreach(
                snapshot_id="attribution:unified:test",
                layer=AttributionLayer.MODEL_VS_PORTFOLIO,
                session=SESSION,
                residual=Decimal("0.0031"),
                tolerance=None,
                threshold_policy_hash="0" * 64,
                owner_scope="portfolio",
                evidence_ids=("evidence:portfolio-series:2026-08-14",),
            )

    def test_the_breach_carries_the_threshold_policy_hash(self) -> None:
        """Otherwise re-running under a looser policy makes the breach vanish
        with nothing recording that the rule changed rather than the data."""
        snapshot = attribute_session_unified(**_breaching_session_inputs())
        self.assertEqual(
            snapshot.breach.threshold_policy_hash, snapshot.threshold_policy_hash
        )
        self.assertRegex(snapshot.breach.threshold_policy_hash, r"^[0-9a-f]{64}$")
```

- [ ] **Step 9: 编排层（红测先行）—— 只搬运，不算术**

```python
# platform/tests/test_unified_attribution_orchestration.py
"""The unified attribution orchestrator moves data; it never computes.

Arithmetic here would create a second source of truth for a governed number.  The
orchestrator's job is to fetch the portfolio series, the timing forecast and the
event study, hand them to the pure functions, and persist what comes back.
"""

class OrchestrationTest(unittest.TestCase):
    def test_a_missing_timing_repository_yields_not_applicable_not_an_error(self) -> None:
        """P7 may not be built.  That is a component status, not a failure of the
        whole attribution."""
        snapshot = _service(timing_repository=None).attribute(session=SESSION)
        timing = snapshot.component("timing")
        self.assertEqual(timing.status, AttributionComponentStatus.NOT_APPLICABLE)
        self.assertIsNone(timing.contribution)
        self.assertEqual(snapshot.component("market").status,
                         AttributionComponentStatus.QUANTIFIED)

    def test_an_unreachable_event_store_yields_unavailable_with_a_reason(self) -> None:
        """Store down and no records are different answers; only the first one is
        a defect."""
        unreachable = _service(event_store=_unreachable_event_store())
        empty = _service(event_store=_empty_event_store())
        down = unreachable.attribute(session=SESSION).component("event")
        quiet = empty.attribute(session=SESSION).component("event")
        self.assertEqual(down.status, AttributionComponentStatus.UNAVAILABLE)
        self.assertIn("unreachable", down.status_reason.lower())
        self.assertEqual(quiet.status, AttributionComponentStatus.NOT_APPLICABLE)
        self.assertNotEqual(down.status_reason, quiet.status_reason)

    def test_the_orchestrator_performs_no_arithmetic(self) -> None:
        """Asserted structurally: the module's AST contains no BinOp on Decimal
        values outside of test helpers."""
        import ast, inspect
        from a_share_platform.application import unified_attribution
        tree = ast.parse(inspect.getsource(unified_attribution))
        divisions = [n for n in ast.walk(tree) if isinstance(n, ast.BinOp)]
        self.assertEqual(divisions, [], "orchestration must not compute")

    def test_strict_historical_is_refused(self) -> None:
        """Unified attribution over current-only inputs cannot claim strict
        historical provenance."""
        with self.assertRaises(PermissionError):
            _service(data_mode=DataMode.STRICT_HISTORICAL)
```

- [ ] **Step 10: 独立库交叉验证（复用既有合同）**

在 `validation/statistical_crosscheck.py` 增加
`cross_check_unified_attribution_closure(...)`，用 NumPy 独立重算八分项和与残差。
**报告结构复用 `StatisticalCrossCheckReport`。** 输入必须与主实现**完全一致**——
在不同输入上做交叉验证什么也证明不了（P-2 已立此规）。

- [ ] **Step 11: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/domain/attribution.py \
  platform/src/a_share_platform/application/unified_attribution.py \
  platform/src/a_share_platform/ports/monitoring.py \
  platform/src/a_share_platform/validation/statistical_crosscheck.py \
  platform/tests/test_unified_attribution.py \
  platform/tests/test_unified_attribution_orchestration.py
git commit -m "feat: extend attribution from core to unified with a residual that cannot hide

The most important test in this change asserts that no component is named other,
unexplained, unattributed or residual.  An attribution system with a catch-all
bucket has a residual of zero by construction: the closure check passes on every
run, the waterfall looks perfect, and closure stops carrying any information at
all.  That failure mode has no symptoms, which is why it needs a test rather than
a convention.  The residual is a separate field carrying its own evidence ids, the
way InvestmentView already handles the same problem.

Execution changes status from unavailable in P6 to not_applicable here, and the
distinction is the point.  In P6 the module did not exist so its evidence was
missing; in P9 the module still does not exist, but the reason recorded is that no
execution has happened, so there is nothing to attribute.  unavailable would
imply the evidence should be chased.  A separate test refuses a zero contribution
for execution outright, because zero asserts that execution ran and cost nothing.

The two layers are separate snapshots with separate hashes.  forecast-vs-realized
asks whether the prediction was right and model-vs-portfolio asks whether the
portfolio expressed it; blended into one number, a good model implemented badly
is indistinguishable from a bad model implemented well, and those two need
opposite responses.

Tolerances come from a content-addressed threshold policy rather than a constant,
so loosening one produces a different hash.  A breach that vanished after a
re-run would otherwise leave nothing recording that the rule changed rather than
the data.  The breach is emitted as a value here and turned into an Incident in
the next task, which keeps the two testable independently."
```

---

### Task 2: `domain/monitoring.py` —— 版本化阈值与九组漂移指标

对应 Step 08 Task 2：「新增 `domain/monitoring.py` 和 subject-specific calculators；
threshold policy 配置化并绑定版本。使用人工 shift fixture 和真实小样本交叉验证。」

**先做 `ThresholdPolicy`，再做任何 calculator。** 顺序理由：如果先写 calculator，
阈值必然作为参数默认值出现，之后再抽出去是一次跨全模块的重构；而先立版本化阈值，
每个 calculator 从第一行起就只能从 policy 读。

**Files:**
- Create: `platform/src/a_share_platform/domain/monitoring.py`
- Create: `platform/src/a_share_platform/application/drift_monitoring.py`
- Create: `platform/src/a_share_platform/validation/monitoring_crosscheck.py`
- Modify: `platform/src/a_share_platform/ports/monitoring.py`
- Test: `platform/tests/test_monitoring_threshold_policy.py`
- Test: `platform/tests/test_drift_observations.py`
- Test: `platform/tests/test_drift_monitoring_orchestration.py`

**Interfaces:**
- Consumes: `ports/system_catalog.py` 的四个 list 方法、P-2 的 `CorrelationResult`、
  P-6 的 `TimingCalibration`、P-5 的 `TargetPortfolioSnapshot`、P-7 的 `AgentRun`
- Produces:
  ```python
  class MonitoringSubjectKind(StrEnum):
      DATASET = "dataset"
      FEATURE = "feature"
      FACTOR = "factor"
      MODEL = "model"
      PORTFOLIO = "portfolio"
      AGENT = "agent"
      JOB = "job"

  class DriftMetric(StrEnum):
      """SPEC-040 的九组，逐字对应."""
      COVERAGE = "coverage"
      FRESHNESS = "freshness"
      FEATURE_DISTRIBUTION_PSI = "feature_distribution_psi"
      INFORMATION_COEFFICIENT = "information_coefficient"
      IC_DECAY = "ic_decay"
      CALIBRATION_BRIER = "calibration_brier"
      RISK_EXPOSURE = "risk_exposure"
      TURNOVER_COST = "turnover_cost"
      CAPACITY = "capacity"
      AGENT_PARSE_RATE = "agent_parse_rate"
      AGENT_CITATION_RATE = "agent_citation_rate"
      JOB_FAILURE_RATE = "job_failure_rate"
      API_SLO = "api_slo"

  class DriftSeverity(StrEnum):
      INFO = "info"
      WARNING = "warning"
      MAJOR = "major"
      CRITICAL = "critical"

  class DriftStatus(StrEnum):
      WITHIN_THRESHOLD = "within_threshold"
      BREACHED = "breached"
      UNAVAILABLE = "unavailable"      # 不可评估，不是「没漂移」

  @dataclass(frozen=True)
  class MetricThreshold:
      metric: DriftMetric
      warning_at: Decimal | None
      major_at: Decimal | None
      critical_at: Decimal | None
      direction: ThresholdDirection      # ABOVE / BELOW
      minimum_sample_size: int
      owner_scope: str                   # ADR-0009 四值

  @dataclass(frozen=True)
  class ThresholdPolicy:
      policy_id: str
      version: str
      subject_kind: MonitoringSubjectKind
      subject_id: str | None             # None = 该 kind 的默认策略
      thresholds: tuple[MetricThreshold, ...]
      escalation_minutes: Mapping[DriftSeverity, int]
      approved_by: str
      approved_at: datetime
      content_hash: str = field(init=False)

  @dataclass(frozen=True)
  class DriftObservation:
      observation_id: str
      subject_kind: MonitoringSubjectKind
      subject_id: str
      subject_version: str
      window_start: datetime
      window_end: datetime
      metric: DriftMetric
      baseline_value: Decimal | None
      observed_value: Decimal | None
      status: DriftStatus
      severity: DriftSeverity | None
      threshold_policy_hash: str
      owner_scope: str
      sample_size: int
      evidence_ids: tuple[str, ...]
      unavailable_reason: str | None
      content_hash: str = field(init=False)

  # 纯函数 calculators，无 I/O、无时钟
  def population_stability_index(*, baseline, observed, spec) -> Decimal
  def coverage_ratio(...) -> Decimal | None      # None = 不可评估，不是 100%
  def freshness_lag_sessions(...) -> int | None  # None = 无交易日历，不猜
  def evaluate_drift(observation_inputs, *, policy) -> DriftObservation
  ```

- [ ] **Step 1: 写红测 —— 阈值版本化（本 Task 的第一约束）**

```python
# platform/tests/test_monitoring_threshold_policy.py
"""Drift thresholds live in a versioned, content-addressed, approved policy.

A threshold is not a tuning parameter; it is the definition of what counts as an
incident.  psi > 0.25 written in code looks like common sense — 0.25 is the
conventional PSI significance level — but it means someone can change it to 0.35
and yesterday's incident silently stops being one, with no record anywhere that
the rule moved rather than the data.

Step 08's decision says the SLO, PSI, IC-decay, calibration and residual
thresholds are D2, configured per subject and version.  D2 means configurable, not
untraceable.  So the policy is hashed, the hash travels on every observation, and
observations under different policies refuse to be compared.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal

from a_share_platform.domain.monitoring import (
    DriftMetric,
    DriftSeverity,
    MetricThreshold,
    MonitoringSubjectKind,
    ThresholdDirection,
    ThresholdPolicy,
)

APPROVED_AT = datetime(2026, 8, 16, 1, 0, tzinfo=UTC)


def psi_threshold(warning: str = "0.10", major: str = "0.25") -> MetricThreshold:
    return MetricThreshold(
        metric=DriftMetric.FEATURE_DISTRIBUTION_PSI,
        warning_at=Decimal(warning),
        major_at=Decimal(major),
        critical_at=Decimal("0.40"),
        direction=ThresholdDirection.ABOVE,
        minimum_sample_size=200,
        owner_scope="research",
    )


def policy(warning: str = "0.10", major: str = "0.25") -> ThresholdPolicy:
    return ThresholdPolicy(
        policy_id="monitoring.policy.feature",
        version="v0",
        subject_kind=MonitoringSubjectKind.FEATURE,
        subject_id=None,
        thresholds=(psi_threshold(warning, major),),
        escalation_minutes={
            DriftSeverity.INFO: 0,
            DriftSeverity.WARNING: 1440,
            DriftSeverity.MAJOR: 240,
            DriftSeverity.CRITICAL: 30,
        },
        approved_by="subject:reviewer-1",
        approved_at=APPROVED_AT,
    )


class PolicyVersioningTest(unittest.TestCase):
    def test_policy_is_content_addressed(self) -> None:
        self.assertEqual(policy().content_hash, policy().content_hash)
        self.assertEqual(len(policy().content_hash), 64)

    def test_changing_one_threshold_changes_the_hash(self) -> None:
        """The load-bearing assertion of this file.

        Without it, loosening PSI from 0.25 to 0.35 makes historical breaches
        disappear and nothing records whether the world changed or the rule did.
        """
        self.assertNotEqual(policy().content_hash, policy(major="0.35").content_hash)

    def test_changing_an_escalation_window_changes_the_hash(self) -> None:
        """ADR-0009 puts 升级时限 in the same配置化 sentence as thresholds, so a
        four-hour major becoming a four-day major is also a rule change."""
        slow = ThresholdPolicy(
            policy_id="monitoring.policy.feature", version="v0",
            subject_kind=MonitoringSubjectKind.FEATURE, subject_id=None,
            thresholds=(psi_threshold(),),
            escalation_minutes={
                DriftSeverity.INFO: 0, DriftSeverity.WARNING: 1440,
                DriftSeverity.MAJOR: 5760, DriftSeverity.CRITICAL: 30,
            },
            approved_by="subject:reviewer-1", approved_at=APPROVED_AT,
        )
        self.assertNotEqual(policy().content_hash, slow.content_hash)

    def test_an_unapproved_policy_cannot_be_constructed(self) -> None:
        """Step 08 决策：retention 和通知渠道必须在部署前批准.  A threshold set
        with no approver is a rule nobody agreed to."""
        with self.assertRaises(ValueError):
            ThresholdPolicy(
                policy_id="monitoring.policy.feature", version="v0",
                subject_kind=MonitoringSubjectKind.FEATURE, subject_id=None,
                thresholds=(psi_threshold(),),
                escalation_minutes={DriftSeverity.WARNING: 1440},
                approved_by="   ", approved_at=APPROVED_AT,
            )

    def test_severity_thresholds_must_be_monotonic(self) -> None:
        """A major threshold below the warning threshold makes severity
        non-deterministic: the same value satisfies both and the answer depends on
        evaluation order."""
        with self.assertRaises(ValueError):
            MetricThreshold(
                metric=DriftMetric.FEATURE_DISTRIBUTION_PSI,
                warning_at=Decimal("0.30"), major_at=Decimal("0.10"),
                critical_at=Decimal("0.40"),
                direction=ThresholdDirection.ABOVE,
                minimum_sample_size=200, owner_scope="research",
            )

    def test_owner_scope_must_be_one_of_the_four_adr_0009_scopes(self) -> None:
        """ADR-0009 逐字：data / research / portfolio / execution.

        A fifth scope, or a free-text one, reintroduces the '系统错误' bucket the
        ADR exists to remove.
        """
        for scope in ("data", "research", "portfolio", "execution"):
            with self.subTest(scope=scope):
                MetricThreshold(
                    metric=DriftMetric.COVERAGE, warning_at=Decimal("0.95"),
                    major_at=Decimal("0.90"), critical_at=Decimal("0.80"),
                    direction=ThresholdDirection.BELOW,
                    minimum_sample_size=1, owner_scope=scope,
                )
        with self.assertRaises(ValueError):
            MetricThreshold(
                metric=DriftMetric.COVERAGE, warning_at=Decimal("0.95"),
                major_at=Decimal("0.90"), critical_at=Decimal("0.80"),
                direction=ThresholdDirection.BELOW,
                minimum_sample_size=1, owner_scope="platform",
            )

    def test_a_metric_with_no_threshold_in_the_policy_is_unavailable(self) -> None:
        """Not 'within threshold'.  An unmonitored metric that reads green is
        worse than one that reads unknown, because green invites reliance."""
        # policy() configures FEATURE_DISTRIBUTION_PSI only.
        configured = policy()
        self.assertEqual(
            tuple(item.metric for item in configured.thresholds),
            (DriftMetric.FEATURE_DISTRIBUTION_PSI,),
        )
        self.assertIsNone(configured.threshold_for(DriftMetric.COVERAGE))
        for metric in DriftMetric:
            if metric is DriftMetric.FEATURE_DISTRIBUTION_PSI:
                continue
            with self.subTest(metric=metric):
                self.assertIsNone(configured.threshold_for(metric))
```

- [ ] **Step 2: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_monitoring_threshold_policy -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'a_share_platform.domain.monitoring'`。

- [ ] **Step 3: 实现 `ThresholdPolicy` 与 `MetricThreshold` → 转绿**

**不实现任何 calculator。** 只做值对象。

- [ ] **Step 4: `DriftObservation` 合同（红测先行）**

```python
# platform/tests/test_drift_observations.py
"""A drift observation states what it measured, against what, and under which rule.

The three states are deliberately three, not two.  within_threshold means the
metric was computed and is fine; breached means computed and not fine; unavailable
means it could not be computed.  Folding unavailable into within_threshold is how
a monitoring system reports all-clear on a dataset it never read.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from a_share_platform.domain.monitoring import (
    DriftMetric,
    DriftObservation,
    DriftSeverity,
    DriftStatus,
    MonitoringSubjectKind,
    evaluate_drift,
)

from tests.test_monitoring_threshold_policy import policy, psi_threshold

WINDOW_START = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 8, 16, 0, 0, tzinfo=UTC)


def observation(
    *,
    observation_id: str = "drift:0001",
    metric: DriftMetric = DriftMetric.FEATURE_DISTRIBUTION_PSI,
    observed_value: Decimal | None = Decimal("0.04"),
    status: DriftStatus = DriftStatus.WITHIN_THRESHOLD,
    severity: DriftSeverity | None = None,
    sample_size: int = 500,
    threshold_policy_hash: str | None = None,
    unavailable_reason: str | None = None,
    window_start: datetime = WINDOW_START,
    window_end: datetime = WINDOW_END,
) -> DriftObservation:
    return DriftObservation(
        observation_id=observation_id,
        subject_kind=MonitoringSubjectKind.FEATURE,
        subject_id="feature:quality.roe",
        subject_version="v3",
        window_start=window_start,
        window_end=window_end,
        metric=metric,
        baseline_value=Decimal("0.00"),
        observed_value=observed_value,
        status=status,
        severity=severity,
        threshold_policy_hash=threshold_policy_hash or policy().content_hash,
        owner_scope="research",
        sample_size=sample_size,
        evidence_ids=("evidence:feature-panel:2026-08-16",),
        unavailable_reason=unavailable_reason,
    )


def tight_observation() -> DriftObservation:
    return observation(threshold_policy_hash=policy(major="0.25").content_hash)


def loose_observation() -> DriftObservation:
    return observation(threshold_policy_hash=policy(major="0.35").content_hash)


def _psi_inputs(
    *, observed_value: Decimal, sample_size: int
) -> dict[str, object]:
    """Raw inputs for evaluate_drift, before the policy assigns status/severity."""
    return {
        "observation_id": f"drift:psi:{sample_size}",
        "subject_kind": MonitoringSubjectKind.FEATURE,
        "subject_id": "feature:quality.roe",
        "subject_version": "v3",
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "metric": DriftMetric.FEATURE_DISTRIBUTION_PSI,
        "baseline_value": Decimal("0.00"),
        "observed_value": observed_value,
        "sample_size": sample_size,
        "evidence_ids": ("evidence:feature-panel:2026-08-16",),
    }


class ObservationContractTest(unittest.TestCase):
    def test_an_unavailable_observation_carries_no_value_and_a_reason(self) -> None:
        record = observation(
            status=DriftStatus.UNAVAILABLE,
            observed_value=None,
            unavailable_reason="feature panel store unreachable",
        )
        self.assertIsNone(record.observed_value)
        self.assertIsNone(record.severity)
        self.assertEqual(record.unavailable_reason, "feature panel store unreachable")
        with self.assertRaises(ValueError):
            observation(status=DriftStatus.UNAVAILABLE, observed_value=Decimal("0.04"))
        with self.assertRaises(ValueError):
            observation(
                status=DriftStatus.UNAVAILABLE,
                observed_value=None,
                unavailable_reason=None,
            )

    def test_an_unavailable_observation_is_not_within_threshold(self) -> None:
        """The distinction this whole enum exists for."""
        record = observation(
            status=DriftStatus.UNAVAILABLE,
            observed_value=None,
            unavailable_reason="no baseline window",
        )
        self.assertIsNot(record.status, DriftStatus.WITHIN_THRESHOLD)
        self.assertIs(record.status, DriftStatus.UNAVAILABLE)

    def test_a_breached_observation_requires_a_severity(self) -> None:
        with self.assertRaises(ValueError):
            observation(
                status=DriftStatus.BREACHED,
                observed_value=Decimal("0.31"),
                severity=None,
            )
        record = observation(
            status=DriftStatus.BREACHED,
            observed_value=Decimal("0.31"),
            severity=DriftSeverity.MAJOR,
        )
        self.assertIs(record.severity, DriftSeverity.MAJOR)

    def test_a_within_threshold_observation_has_no_severity(self) -> None:
        self.assertIsNone(observation().severity)
        with self.assertRaises(ValueError):
            observation(severity=DriftSeverity.WARNING)

    def test_below_the_minimum_sample_size_reports_unavailable(self) -> None:
        """A PSI from 12 observations is a number, not an estimate.  Reporting it
        as within_threshold would make a small sample look like evidence of
        stability."""
        # psi_threshold() declares minimum_sample_size=200.
        self.assertEqual(psi_threshold().minimum_sample_size, 200)
        record = evaluate_drift(
            _psi_inputs(observed_value=Decimal("0.04"), sample_size=12),
            policy=policy(),
        )
        self.assertIs(record.status, DriftStatus.UNAVAILABLE)
        self.assertIsNone(record.observed_value)
        self.assertIn("sample", record.unavailable_reason.lower())

    def test_the_observation_carries_the_threshold_policy_hash(self) -> None:
        self.assertEqual(observation().threshold_policy_hash, policy().content_hash)
        self.assertRegex(observation().threshold_policy_hash, r"^[0-9a-f]{64}$")

    def test_two_observations_under_different_policies_refuse_comparison(self) -> None:
        """Raising rather than returning False.

        A silent False reads as 'no change detected', which is exactly the wrong
        conclusion when the rule changed underneath.
        """
        with self.assertRaises(ValueError):
            tight_observation().compare_to(loose_observation())

    def test_window_end_must_not_precede_window_start(self) -> None:
        with self.assertRaises(ValueError):
            observation(window_start=WINDOW_END, window_end=WINDOW_START)

    def test_both_window_bounds_must_be_timezone_aware(self) -> None:
        with self.assertRaises(ValueError):
            observation(window_start=datetime(2026, 8, 1, 0, 0))
        with self.assertRaises(ValueError):
            observation(window_end=datetime(2026, 8, 16, 0, 0))
```

- [ ] **Step 5: 运行 → 实现 → 转绿**

- [ ] **Step 6: PSI 与 coverage/freshness calculator（红测先行，含手算 fixture）**

```python
def psi_spec(bin_edges: tuple[str, ...] = ("0", "0.25", "0.50", "0.75", "1")) -> PsiSpec:
    """The binning is part of the metric's identity, so it is a versioned value.

    Two runs under different edges produce different numbers on the same data,
    which is why the spec carries its own hash rather than being a bare tuple.
    """
    return PsiSpec(
        spec_id="monitoring.psi.equal_width_4",
        version="v1",
        bin_edges=tuple(Decimal(edge) for edge in bin_edges),
    )


class PopulationStabilityIndexTest(unittest.TestCase):
    def test_identical_distributions_give_zero(self) -> None:
        """Hand computation: sum of (p - q) * ln(p / q) over identical bins is
        exactly zero, term by term."""
        self.assertEqual(
            population_stability_index(
                baseline=(Decimal("0.25"),) * 4,
                observed=(Decimal("0.25"),) * 4,
                spec=psi_spec(),
            ),
            Decimal(0),
        )

    def test_a_known_shift_matches_the_hand_computation(self) -> None:
        """baseline (0.4, 0.3, 0.2, 0.1) vs observed (0.1, 0.2, 0.3, 0.4).
        Hand: 0.3*ln4 + 0.1*ln1.5 + (-0.1)*ln(2/3) + (-0.3)*ln(0.25)
            = 0.41589 + 0.04055 + 0.04055 + 0.41589 = 0.91288.
        Checked to 5 decimal places; the crosscheck in Step 8 verifies more."""
        value = population_stability_index(
            baseline=(Decimal("0.4"), Decimal("0.3"), Decimal("0.2"), Decimal("0.1")),
            observed=(Decimal("0.1"), Decimal("0.2"), Decimal("0.3"), Decimal("0.4")),
            spec=psi_spec(),
        )
        self.assertEqual(value.quantize(Decimal("0.00001")), Decimal("0.91288"))

    def test_an_empty_baseline_bin_refuses_rather_than_substituting_epsilon(self) -> None:
        """Adding a small epsilon to a zero bin is the standard workaround and it
        silently caps PSI at a value determined by the epsilon, not by the data.
        A zero baseline bin means the binning is wrong, which is worth knowing."""
        with self.assertRaises(ValueError):
            population_stability_index(
                baseline=(Decimal("0.5"), Decimal("0.5"), Decimal(0)),
                observed=(Decimal("0.3"), Decimal("0.3"), Decimal("0.4")),
                spec=psi_spec(),
            )

    def test_bin_edges_are_part_of_the_spec_version(self) -> None:
        """PSI is entirely determined by the binning.  Ten equal-width bins and
        ten equal-frequency bins give different numbers on the same data, so two
        runs under different binning must not be comparable."""
        equal_width = psi_spec()
        equal_frequency = psi_spec(bin_edges=("0", "0.10", "0.35", "0.80", "1"))
        self.assertNotEqual(equal_width.content_hash, equal_frequency.content_hash)
        with self.assertRaises(ValueError):
            equal_width.assert_comparable(equal_frequency)

    def test_mismatched_bin_counts_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            population_stability_index(
                baseline=(Decimal("0.5"), Decimal("0.5")),
                observed=(Decimal("0.3"), Decimal("0.3"), Decimal("0.4")),
                spec=psi_spec(),
            )


class CoverageAndFreshnessTest(unittest.TestCase):
    def test_coverage_is_covered_over_expected_not_covered_over_present(self) -> None:
        """480 of 500 expected securities is 96% coverage.  Dividing by the 480
        that are present gives 100% and makes every gap invisible — this is the
        single most common way a coverage metric becomes decorative."""
        self.assertEqual(
            coverage_ratio(covered=480, expected=500), Decimal("0.96")
        )
        self.assertNotEqual(coverage_ratio(covered=480, expected=500), Decimal(1))

    def test_a_zero_expected_denominator_is_unavailable_not_one_hundred_percent(
        self,
    ) -> None:
        self.assertIsNone(coverage_ratio(covered=0, expected=0))

    def test_freshness_is_measured_in_sessions_not_calendar_days(self) -> None:
        """A Friday dataset read on Monday is one session stale, not three days.
        Calendar-day freshness fires every weekend and gets muted, after which it
        never fires again."""
        # 2026-08-14 is a Friday; 2026-08-17 is the next Monday.
        lag = freshness_lag_sessions(
            last_loaded_session=date(2026, 8, 14),
            as_of_session=date(2026, 8, 17),
            calendar=_trading_calendar(),
        )
        self.assertEqual(lag, 1)
        self.assertNotEqual(lag, 3)

    def test_freshness_without_a_calendar_is_unavailable(self) -> None:
        """Guessing a session count would produce a number that looks precise."""
        self.assertIsNone(
            freshness_lag_sessions(
                last_loaded_session=date(2026, 8, 14),
                as_of_session=date(2026, 8, 17),
                calendar=None,
            )
        )
```

- [ ] **Step 7: 十三个指标逐组接线（每组一个红测再实现）**

顺序：`data` owner 组先（coverage / freshness / job_failure_rate），
再 `research` 组（PSI / IC / IC decay / calibration / agent parse / agent citation），
再 `portfolio` 组（exposure / turnover_cost / capacity），最后 `api_slo`（`data`）。

每组至少覆盖：

- 正常值 → `WITHIN_THRESHOLD`，无 severity；
- 越界值 → `BREACHED` + 正确 severity + **正确 owner_scope**；
- 输入缺失 → `UNAVAILABLE` + 原因，**不是** `WITHIN_THRESHOLD`；
- 样本不足 → `UNAVAILABLE`；
- owner 路由正确（这是 ADR-0009 的可测部分，Task 6 会再端到端验一次）。

**IC decay 组有一个特殊约束**：它消费 P-2 的 `CorrelationResult`，
而 `CorrelationResult` 带 `scientific_status`。若 `scientific_status` 为
`not_evaluated`，IC decay 观测必须是 `UNAVAILABLE` —— 一个未经科学验证的 IC
的「衰减」不是可解释的量。**不得**把它当数值用。

- [ ] **Step 8: PSI 独立库交叉验证**

`validation/monitoring_crosscheck.py` 用 scipy/numpy 独立重算 PSI 与 KS。
输入必须与主实现**完全一致**。缺库时报 `unavailable`，**不是** agreement
（P-2 已立此规：「缺库时报 unavailable 而非一致」）。

- [ ] **Step 9: 监控不得改模型或组合（红测先行，本 Task 最关键的两个测试）**

```python
class MonitoringCannotMutateTest(unittest.TestCase):
    """Step 08 Spec 非目标逐字：监控不静默改模型/权重.

    The temptation is concrete and each instance looks obviously right: IC decayed,
    so lower the weight; calibration drifted, so recalibrate; exposure breached, so
    clip the target.  Every one of them makes what production runs differ from what
    was approved, while the audit trail still points at the approved version — so
    the trail itself becomes a lie.

    The defence is structural rather than disciplinary.  The calculators are pure
    functions with no writable object in their signatures, DriftObservation is
    frozen, and AlertAction has exactly three values with no ADJUST_WEIGHT among
    them.  These two tests lock that down.
    """

    def test_a_drift_alert_cannot_mutate_a_factor_version(self) -> None:
        from a_share_platform.domain.factor_lifecycle import FactorLifecycleStatus

        version = _production_factor_version()
        before = version.content_hash
        before_status = version.status
        observation = evaluate_drift(_decayed_ic_inputs(), policy=_research_policy())
        self.assertEqual(observation.status, DriftStatus.BREACHED)
        # The alert may only block, request review, or execute an approved
        # rollback.  None of those changes the version in place.
        self.assertEqual(version.content_hash, before)
        self.assertIs(version.status, before_status)
        self.assertIs(version.status, FactorLifecycleStatus.PRODUCTION)

    def test_a_drift_alert_cannot_mutate_a_portfolio_target(self) -> None:
        target = _target_portfolio_snapshot()
        before = target.content_hash
        observation = evaluate_drift(_breached_exposure_inputs(), policy=_portfolio_policy())
        self.assertEqual(observation.status, DriftStatus.BREACHED)
        self.assertEqual(target.content_hash, before)

    def test_the_alert_action_enum_has_no_mutating_value(self) -> None:
        """Asserted on the enum rather than on behaviour, because a fourth value
        added later would pass every behavioural test until someone used it."""
        from a_share_platform.domain.incidents import AlertAction

        self.assertEqual(
            {item.value for item in AlertAction},
            {"block_downstream", "request_review", "execute_approved_rollback"},
        )

    def test_a_calculator_signature_accepts_no_repository(self) -> None:
        """A pure function cannot write.  Asserted by inspecting the signature, so
        adding a repository parameter fails here rather than in review."""
        import inspect
        from a_share_platform.domain import monitoring

        for name in ("population_stability_index", "coverage_ratio",
                     "freshness_lag_sessions", "evaluate_drift"):
            with self.subTest(name=name):
                signature = inspect.signature(getattr(monitoring, name))
                for parameter in signature.parameters.values():
                    self.assertNotIn("repository", parameter.name)
                    self.assertNotIn("session", parameter.name)
                    self.assertNotIn("connection", parameter.name)
```

（`AlertAction` 属 Task 3。此处引用它意味着 Task 2 的这三个测试**在 Task 3 之后才能全绿**——
这是可接受的：先写、先红、在 Task 3 Step 4 转绿，并在 Evidence 里记录这个跨 Task 的红→绿。
**不要**为了让本 Task 全绿而在 Task 2 里提前造一个 `AlertAction`。）

- [ ] **Step 10: 编排层（红测先行）**

```python
# platform/tests/test_drift_monitoring_orchestration.py
"""The drift orchestrator reads, computes through pure functions, and appends.

Its only interesting behaviour is failure isolation: one unreachable store must
degrade one subject kind, not the whole monitoring run.  A monitoring run that
fails closed on the first missing dataset never reports on the other twelve
metrics, which is how one data gap hides an unrelated model failure.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from a_share_platform.adapters.memory.monitoring import (
    InMemoryDriftObservationRepository,
    UnavailableMonitoringStore,
)
from a_share_platform.application.drift_monitoring import DriftMonitoringService
from a_share_platform.domain.monitoring import DriftMetric, DriftStatus

from tests.test_monitoring_threshold_policy import policy

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _unavailable_store() -> object:
    """A store that raises rather than returning nothing.

    Returning () would make 'store down' and 'no records' the same answer, which
    is the failure this whole test module exists to prevent.
    """

    class _Store:
        def read_window(self, **_: object) -> tuple[object, ...]:
            raise UnavailableMonitoringStore("feature panel store unreachable")

    return _Store()


def _service(
    *,
    feature_store: object | None = None,
    repository: InMemoryDriftObservationRepository | None = None,
    policies: tuple[object, ...] = (),
) -> DriftMonitoringService:
    return DriftMonitoringService(
        repository=repository or InMemoryDriftObservationRepository(),
        feature_store=feature_store,
        policies=policies or (policy(),),
    )


class OrchestrationTest(unittest.TestCase):
    def test_one_unreachable_store_degrades_one_subject_kind(self) -> None:
        result = _service(feature_store=_unavailable_store()).run(now=NOW)
        self.assertTrue(any(o.status is DriftStatus.UNAVAILABLE for o in result.observations))
        self.assertTrue(any(o.status is DriftStatus.WITHIN_THRESHOLD for o in result.observations))

    def test_the_run_reports_which_metrics_it_could_not_evaluate(self) -> None:
        """A silent omission is indistinguishable from a pass."""
        result = _service(feature_store=_unavailable_store()).run(now=NOW)
        # Every metric the run was asked about appears in exactly one of the two
        # buckets, so nothing can be dropped without the totals disagreeing.
        self.assertIn(DriftMetric.FEATURE_DISTRIBUTION_PSI, result.unevaluated_metrics)
        self.assertEqual(
            set(result.evaluated_metrics) | set(result.unevaluated_metrics),
            set(result.requested_metrics),
        )
        self.assertEqual(
            set(result.evaluated_metrics) & set(result.unevaluated_metrics), set()
        )
        self.assertIn(
            "unreachable",
            result.unevaluated_metrics[DriftMetric.FEATURE_DISTRIBUTION_PSI].lower(),
        )

    def test_observations_are_append_only_and_idempotent(self) -> None:
        """Re-running the same window must not double-count, and must not
        overwrite: the first evaluation is evidence even if a later one differs."""
        repository = InMemoryDriftObservationRepository()
        service = _service(repository=repository)
        first = service.run(now=NOW)
        second = service.run(now=NOW)
        self.assertEqual(
            tuple(o.observation_id for o in first.observations),
            tuple(o.observation_id for o in second.observations),
        )
        self.assertEqual(len(repository.list_observations()), len(first.observations))
        self.assertEqual(
            tuple(o.content_hash for o in repository.list_observations()),
            tuple(o.content_hash for o in first.observations),
        )

    def test_a_rerun_with_a_different_policy_creates_a_new_observation(self) -> None:
        """Not an update.  Both evaluations are facts and the pair is exactly the
        evidence that a threshold change altered the verdict."""
        repository = InMemoryDriftObservationRepository()
        tight = _service(repository=repository, policies=(policy(major="0.25"),))
        loose = _service(repository=repository, policies=(policy(major="0.35"),))
        tight.run(now=NOW)
        loose.run(now=NOW)
        stored = repository.list_observations()
        hashes = {o.threshold_policy_hash for o in stored}
        self.assertEqual(len(hashes), 2)
        self.assertEqual(len(stored), 2)
        self.assertEqual(len({o.observation_id for o in stored}), 2)
```

- [ ] **Step 11: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/domain/monitoring.py \
  platform/src/a_share_platform/application/drift_monitoring.py \
  platform/src/a_share_platform/validation/monitoring_crosscheck.py \
  platform/src/a_share_platform/ports/monitoring.py \
  platform/tests/test_monitoring_threshold_policy.py \
  platform/tests/test_drift_observations.py \
  platform/tests/test_drift_monitoring_orchestration.py
git commit -m "feat: add versioned drift thresholds and thirteen monitored metrics

A threshold is not a tuning parameter, it is the definition of what counts as an
incident.  psi > 0.25 in code looks like common sense, and that is the problem:
changing it to 0.35 makes yesterday's incident stop being one with nothing
recording that the rule moved rather than the data.  So the policy is
content-addressed, its hash travels on every observation, escalation windows enter
the hash alongside the thresholds, and two observations under different policies
raise on comparison instead of quietly reporting no change.

Three drift states rather than two.  within_threshold means computed and fine,
breached means computed and not fine, unavailable means it could not be computed.
Folding the third into the first is how monitoring reports all-clear on a dataset
it never read, and a metric with no threshold configured reads unavailable rather
than green — green invites reliance.

Two tests assert that a breached alert leaves a FactorVersion and a
TargetPortfolioSnapshot byte-identical, and a third asserts the AlertAction enum
contains only block, request-review and execute-approved-rollback.  The enum is
asserted directly rather than through behaviour because a fourth value added later
would pass every behavioural test until someone used it.  A fourth test inspects
the calculator signatures for repository or connection parameters: a pure function
cannot write, and this fails at the signature rather than in review.

An empty PSI baseline bin refuses rather than substituting an epsilon.  The
epsilon workaround caps PSI at a value determined by the epsilon rather than the
data, and a zero baseline bin means the binning is wrong, which is the more useful
thing to learn.  Coverage divides by expected rather than by present, because
dividing by present yields 100% on every gap."
```

---

### Task 3: `domain/incidents.py` —— Alert 去重与 Incident 状态机

对应 Step 08 Task 3：「新增 `domain/incidents.py`、application service、append-only repository；
测试 dedupe、severity、owner、非法 transition、reopen、runbook 和 audit。」

**每一个转移一个红测。** 状态机的形状照 `domain/factor_lifecycle.py` 的
`_ALLOWED_TRANSITIONS`（frozenset of pairs）—— 那个模式已在本仓库验证过，
不发明第二种。

**Files:**
- Create: `platform/src/a_share_platform/domain/incidents.py`
- Create: `platform/src/a_share_platform/application/incident_service.py`
- Create: `platform/src/a_share_platform/adapters/memory/monitoring.py`
- Modify: `platform/src/a_share_platform/ports/monitoring.py`
- Test: `platform/tests/test_alert_dedupe.py`
- Test: `platform/tests/test_incident_state_machine.py`
- Test: `platform/tests/test_incident_service.py`

**Interfaces:**
- Consumes: Task 1 的 `AttributionClosureBreach`、Task 2 的 `DriftObservation`、
  `application/permissions.py`、`ports/system_catalog.py` 的 `IngestionJobEntry`
- Produces:
  ```python
  class AlertAction(StrEnum):
      """The only three things an alert may do.  See Task 2 Step 9."""
      BLOCK_DOWNSTREAM = "block_downstream"
      REQUEST_REVIEW = "request_review"
      EXECUTE_APPROVED_ROLLBACK = "execute_approved_rollback"

  class AlertSource(StrEnum):
      DRIFT_OBSERVATION = "drift_observation"
      ATTRIBUTION_CLOSURE = "attribution_closure"
      INGESTION_JOB = "ingestion_job"
      API_SLO = "api_slo"
      AGENT_RUN = "agent_run"

  @dataclass(frozen=True)
  class Alert:
      alert_id: str
      dedupe_key: str                  # init=False，从四元组派生
      subject_kind: MonitoringSubjectKind
      subject_id: str
      subject_version: str
      metric: DriftMetric
      severity: DriftSeverity
      owner_scope: str                 # ADR-0009 四值
      source: AlertSource
      source_ids: tuple[str, ...]
      runbook_id: str                  # 非空：SPEC-040 要求 runbook
      first_seen_at: datetime          # 永不改变
      last_seen_at: datetime
      occurrence_count: int            # >= 1
      permitted_actions: frozenset[AlertAction]
      content_hash: str = field(init=False)

  class IncidentState(StrEnum):
      OPEN = "open"
      ACKNOWLEDGED = "acknowledged"
      MITIGATING = "mitigating"
      RESOLVED = "resolved"
      POSTMORTEM = "postmortem"
      CLOSED = "closed"

  _ALLOWED_INCIDENT_TRANSITIONS: frozenset[tuple[IncidentState, IncidentState]]

  class IllegalIncidentTransition(ValueError): ...

  @dataclass(frozen=True)
  class IncidentTransition:
      transition_id: str
      from_state: IncidentState
      to_state: IncidentState
      actor_id: str
      actor_role: str
      occurred_at: datetime
      reason: str                      # 非空
      evidence_ids: tuple[str, ...]

  @dataclass(frozen=True)
  class Incident:
      incident_id: str
      dedupe_key: str
      state: IncidentState
      severity: DriftSeverity
      primary_owner_scope: str
      contributor_owner_scopes: tuple[str, ...]
      runbook_id: str
      alerts: tuple[Alert, ...]
      transitions: tuple[IncidentTransition, ...]   # append-only，时间有序
      opened_at: datetime
      reopen_count: int
      content_hash: str = field(init=False)

      def apply(self, transition: IncidentTransition) -> Incident: ...
      # Severity may only be raised.  A downgrade in place is how a critical
      # becomes a warning retroactively, which makes escalation SLOs unauditable.
      def escalate_severity(self, severity: DriftSeverity, *, actor_id: str,
                            actor_role: str, occurred_at: datetime,
                            reason: str) -> Incident: ...
  ```

- [ ] **Step 1: 写红测 —— 去重键（先做这个，因为它决定 Incident 的粒度）**

```python
# platform/tests/test_alert_dedupe.py
"""One root cause is one incident, however many times it fires.

A provider rate limit fails 500 jobs at once; a stale dataset drifts 12 features at
once.  If each failure were its own incident, the list becomes permanently unusable
after the first real outage — and worse, the genuinely unrelated second failure is
buried in the noise.  The current desk does exactly this: _active_failures() lists
`for job in jobs if job.failure_reasons` with no grouping.

The hard part is the key, not the grouping.  Too coarse — say owner_scope alone —
merges two unrelated failures and hides the second.  Too fine — anything including
a timestamp or a measured value — is not deduplication at all.  The key is
(subject_id, subject_version, metric, owner_scope): what broke, which version of
it, what measurement says so, and who owns it.

Deduplication must not hide scale.  A key that fired 500 times shows 500, because
'one incident' and 'one occurrence' are different claims.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from a_share_platform.domain.incidents import Alert, AlertAction, AlertSource
from a_share_platform.domain.monitoring import (
    DriftMetric,
    DriftSeverity,
    MonitoringSubjectKind,
)

FIRST = datetime(2026, 8, 16, 1, 0, tzinfo=UTC)


def alert(
    *,
    alert_id: str = "alert:0001",
    subject_id: str = "feature:quality.roe:v3",
    subject_version: str = "v3",
    metric: DriftMetric = DriftMetric.FEATURE_DISTRIBUTION_PSI,
    owner_scope: str = "research",
    runbook_id: str = "runbook.feature-drift.v1",
    seen_at: datetime = FIRST,
    occurrences: int = 1,
) -> Alert:
    return Alert(
        alert_id=alert_id,
        subject_kind=MonitoringSubjectKind.FEATURE,
        subject_id=subject_id,
        subject_version=subject_version,
        metric=metric,
        severity=DriftSeverity.MAJOR,
        owner_scope=owner_scope,
        source=AlertSource.DRIFT_OBSERVATION,
        source_ids=("drift:0001",),
        runbook_id=runbook_id,
        first_seen_at=FIRST,
        last_seen_at=seen_at,
        occurrence_count=occurrences,
        permitted_actions=frozenset({AlertAction.REQUEST_REVIEW}),
    )


class DedupeKeyTest(unittest.TestCase):
    def test_the_same_root_cause_has_the_same_key(self) -> None:
        self.assertEqual(
            alert(alert_id="alert:0001").dedupe_key,
            alert(alert_id="alert:0500", seen_at=FIRST + timedelta(hours=3)).dedupe_key,
        )

    def test_the_key_excludes_time(self) -> None:
        """A key containing a timestamp deduplicates nothing."""
        self.assertEqual(
            alert(seen_at=FIRST).dedupe_key,
            alert(seen_at=FIRST + timedelta(days=2)).dedupe_key,
        )

    def test_the_key_excludes_the_occurrence_count(self) -> None:
        self.assertEqual(alert(occurrences=1).dedupe_key, alert(occurrences=500).dedupe_key)

    def test_a_different_subject_version_is_a_different_incident(self) -> None:
        """v3 drifting and v4 drifting are two facts.  Merging them would let a
        fixed problem look like a continuing one, or vice versa."""
        self.assertNotEqual(
            alert(subject_id="feature:quality.roe:v3", subject_version="v3").dedupe_key,
            alert(subject_id="feature:quality.roe:v4", subject_version="v4").dedupe_key,
        )

    def test_a_different_metric_on_the_same_subject_is_a_different_incident(self) -> None:
        """A feature that both drifted in distribution and lost coverage has two
        problems, and they have different fixes."""
        self.assertNotEqual(
            alert(metric=DriftMetric.FEATURE_DISTRIBUTION_PSI).dedupe_key,
            alert(metric=DriftMetric.COVERAGE).dedupe_key,
        )

    def test_owner_scope_alone_does_not_merge_unrelated_subjects(self) -> None:
        """The coarse-key failure mode: everything owned by research collapsing
        into one incident, so the second real problem is invisible."""
        self.assertNotEqual(
            alert(subject_id="feature:quality.roe:v3").dedupe_key,
            alert(subject_id="feature:valuation.ep:v3").dedupe_key,
        )

    def test_the_key_is_stable_across_processes(self) -> None:
        """A key derived from id() or hash() of a tuple changes between runs under
        PYTHONHASHSEED randomisation, which would silently defeat deduplication in
        production while passing every in-process test."""
        self.assertEqual(len(alert().dedupe_key), 64)
        self.assertRegex(alert().dedupe_key, r"^[0-9a-f]{64}$")


class OccurrenceAccountingTest(unittest.TestCase):
    def test_first_seen_at_never_moves(self) -> None:
        """SPEC-040 逐字：告警有 owner、severity、首次时间、影响对象、处置状态和 runbook.

        A first-seen time that follows the latest occurrence loses the age of the
        problem, which is the single most useful number for triage.
        """
        repeated = alert().observe_again(at=FIRST + timedelta(hours=6))
        self.assertEqual(repeated.first_seen_at, FIRST)
        self.assertEqual(repeated.last_seen_at, FIRST + timedelta(hours=6))
        self.assertEqual(repeated.occurrence_count, 2)

    def test_five_hundred_occurrences_report_five_hundred(self) -> None:
        """Deduplication that hides scale has turned into information loss.  One
        incident and one occurrence are different claims."""
        current = alert()
        for index in range(499):
            current = current.observe_again(at=FIRST + timedelta(minutes=index + 1))
        self.assertEqual(current.occurrence_count, 500)

    def test_an_earlier_occurrence_is_refused(self) -> None:
        """Clock going backwards means the ledger cannot be trusted; better to
        fail than to record an impossible ordering."""
        with self.assertRaises(ValueError):
            alert().observe_again(at=FIRST - timedelta(minutes=1))

    def test_an_alert_requires_a_runbook(self) -> None:
        """SPEC-040 makes the runbook part of the alert contract.  An alert with
        no runbook routes to an owner who has no stated first action."""
        with self.assertRaises(ValueError):
            alert(runbook_id="   ")

    def test_an_alert_owner_scope_must_be_one_of_the_four(self) -> None:
        for scope in ("data", "research", "portfolio", "execution"):
            with self.subTest(scope=scope):
                self.assertEqual(alert(owner_scope=scope).owner_scope, scope)
        for scope in ("platform", "system", "unknown", ""):
            with self.subTest(scope=scope):
                with self.assertRaises(ValueError):
                    alert(owner_scope=scope)
```

- [ ] **Step 2: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_alert_dedupe -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'a_share_platform.domain.incidents'`。

- [ ] **Step 3: 实现 `Alert` 与 `dedupe_key` → 转绿**

`dedupe_key` 用 `_canonical_hash({subject_id, subject_version, metric, owner_scope})`。
**不用** Python 内置 `hash()` —— `PYTHONHASHSEED` 随机化会让键在进程间不稳定，
而进程内测试全绿。

- [ ] **Step 4: 实现 `AlertAction` 三值 → Task 2 Step 9 的三个跨 Task 红测转绿**

回到 `tests/test_drift_observations.py`（或 Task 2 建的文件）跑一次，
确认 `test_the_alert_action_enum_has_no_mutating_value` 转绿。
**在 Evidence 里记录这个跨 Task 的红→绿。**

- [ ] **Step 5: 状态机六态与合法转移（逐转移红测）**

```python
# platform/tests/test_incident_state_machine.py
"""The incident lifecycle as an explicit transition set.

open → acknowledged → mitigating → resolved → postmortem → closed, plus reopen
edges.  Each legal transition gets its own test and each illegal one is asserted
refused, because the damaging bugs here are asymmetric: allowing an illegal
transition loses the audit chain, while forbidding a legal one just blocks work
until someone notices.

The shape follows domain/factor_lifecycle.py's _ALLOWED_TRANSITIONS — a frozenset
of (from, to) pairs — rather than inventing a second state-machine idiom in the
same codebase.
"""

from __future__ import annotations

import itertools
import unittest
from datetime import UTC, datetime, timedelta

from a_share_platform.domain.incidents import (
    Alert,
    AlertAction,
    AlertSource,
    IllegalIncidentTransition,
    Incident,
    IncidentState,
    IncidentTransition,
)
from a_share_platform.domain.monitoring import (
    DriftMetric,
    DriftSeverity,
    MonitoringSubjectKind,
)

OPENED = datetime(2026, 8, 16, 1, 0, tzinfo=UTC)

# Transitions must be strictly time-ordered, so the default occurred_at comes
# from a monotonic counter rather than a constant.  A shared constant would make
# every two-transition test fail on ordering rather than on the rule under test.
_MINUTES = itertools.count(1)


def _alert(severity: DriftSeverity = DriftSeverity.MAJOR) -> Alert:
    return Alert(
        alert_id="alert:0001",
        subject_kind=MonitoringSubjectKind.FEATURE,
        subject_id="feature:quality.roe",
        subject_version="v3",
        metric=DriftMetric.FEATURE_DISTRIBUTION_PSI,
        severity=severity,
        owner_scope="research",
        source=AlertSource.DRIFT_OBSERVATION,
        source_ids=("drift:0001",),
        runbook_id="runbook.feature-drift.v1",
        first_seen_at=OPENED,
        last_seen_at=OPENED,
        occurrence_count=1,
        permitted_actions=frozenset({AlertAction.REQUEST_REVIEW}),
    )


def _transition(
    from_state: IncidentState,
    to_state: IncidentState,
    *,
    reason: str = "triage note recorded by the owning desk",
    at: datetime | None = None,
    actor_id: str = "subject:reviewer-1",
    actor_role: str = "reviewer",
) -> IncidentTransition:
    occurred_at = at if at is not None else OPENED + timedelta(minutes=next(_MINUTES))
    return IncidentTransition(
        transition_id=(
            f"transition:{from_state.value}:{to_state.value}:{occurred_at.isoformat()}"
        ),
        from_state=from_state,
        to_state=to_state,
        actor_id=actor_id,
        actor_role=actor_role,
        occurred_at=occurred_at,
        reason=reason,
        evidence_ids=("evidence:drift:0001",),
    )


def _open_incident(severity: DriftSeverity = DriftSeverity.MAJOR) -> Incident:
    return Incident(
        incident_id="incident:0001",
        dedupe_key="d" * 64,
        state=IncidentState.OPEN,
        severity=severity,
        primary_owner_scope="research",
        contributor_owner_scopes=(),
        runbook_id="runbook.feature-drift.v1",
        alerts=(_alert(severity),),
        transitions=(),
        opened_at=OPENED,
        reopen_count=0,
    )


def _walk(*states: IncidentState, severity: DriftSeverity = DriftSeverity.MAJOR) -> Incident:
    """Apply the given path from OPEN, one legal transition at a time."""
    incident = _open_incident(severity)
    current = IncidentState.OPEN
    for target in states:
        incident = incident.apply(_transition(current, target))
        current = target
    return incident


def _acknowledged_incident() -> Incident:
    return _walk(IncidentState.ACKNOWLEDGED)


def _mitigating_incident() -> Incident:
    return _walk(IncidentState.ACKNOWLEDGED, IncidentState.MITIGATING)


def _resolved_incident() -> Incident:
    return _walk(
        IncidentState.ACKNOWLEDGED, IncidentState.MITIGATING, IncidentState.RESOLVED
    )


def _postmortem_incident() -> Incident:
    return _resolved_incident().apply(
        _transition(IncidentState.RESOLVED, IncidentState.POSTMORTEM)
    )


def _closed_incident() -> Incident:
    return _postmortem_incident().apply(
        _transition(IncidentState.POSTMORTEM, IncidentState.CLOSED)
    )


class LegalTransitionTest(unittest.TestCase):
    def test_open_to_acknowledged(self) -> None:
        incident = _open_incident().apply(
            _transition(IncidentState.OPEN, IncidentState.ACKNOWLEDGED)
        )
        self.assertIs(incident.state, IncidentState.ACKNOWLEDGED)

    def test_acknowledged_to_mitigating(self) -> None:
        incident = _acknowledged_incident().apply(
            _transition(IncidentState.ACKNOWLEDGED, IncidentState.MITIGATING)
        )
        self.assertIs(incident.state, IncidentState.MITIGATING)

    def test_mitigating_to_resolved(self) -> None:
        incident = _mitigating_incident().apply(
            _transition(IncidentState.MITIGATING, IncidentState.RESOLVED)
        )
        self.assertIs(incident.state, IncidentState.RESOLVED)

    def test_resolved_to_postmortem(self) -> None:
        incident = _resolved_incident().apply(
            _transition(IncidentState.RESOLVED, IncidentState.POSTMORTEM)
        )
        self.assertIs(incident.state, IncidentState.POSTMORTEM)

    def test_postmortem_to_closed(self) -> None:
        incident = _postmortem_incident().apply(
            _transition(IncidentState.POSTMORTEM, IncidentState.CLOSED)
        )
        self.assertIs(incident.state, IncidentState.CLOSED)

    def test_open_straight_to_mitigating_is_legal_for_a_critical(self) -> None:
        """A critical incident where someone starts fixing before acknowledging is
        normal operational behaviour; forbidding it would make the ledger lie about
        what actually happened."""
        incident = _open_incident(DriftSeverity.CRITICAL).apply(
            _transition(IncidentState.OPEN, IncidentState.MITIGATING,
                        reason="paging the data desk; mitigation started immediately")
        )
        self.assertIs(incident.state, IncidentState.MITIGATING)
        self.assertEqual(len(incident.transitions), 1)


class IllegalTransitionTest(unittest.TestCase):
    def test_open_cannot_jump_to_closed(self) -> None:
        """Closing without resolving loses the entire question of what was done.
        This is the transition someone reaches for at the end of a long day."""
        with self.assertRaises(IllegalIncidentTransition):
            _open_incident().apply(
                _transition(IncidentState.OPEN, IncidentState.CLOSED)
            )

    def test_open_cannot_jump_to_resolved(self) -> None:
        """Resolved means a mitigation was applied.  Straight from open, nothing
        was applied, so the claim is false."""
        with self.assertRaises(IllegalIncidentTransition):
            _open_incident().apply(
                _transition(IncidentState.OPEN, IncidentState.RESOLVED)
            )

    def test_closed_cannot_transition_to_anything(self) -> None:
        """Closed is terminal.  A recurrence opens a new incident or reopens
        through the audited reopen path; silently continuing a closed one makes the
        postmortem describe a different event than the one that closed."""
        closed = _closed_incident()
        for target in IncidentState:
            with self.subTest(target=target):
                with self.assertRaises(IllegalIncidentTransition):
                    closed.apply(_transition(IncidentState.CLOSED, target))

    def test_a_transition_from_a_state_the_incident_is_not_in_is_refused(self) -> None:
        """The from_state must match reality, otherwise a concurrent pair of
        updates both succeed and the second overwrites the first."""
        acknowledged = _open_incident().apply(
            _transition(IncidentState.OPEN, IncidentState.ACKNOWLEDGED)
        )
        with self.assertRaises(IllegalIncidentTransition):
            acknowledged.apply(
                _transition(IncidentState.OPEN, IncidentState.MITIGATING)
            )

    def test_resolved_cannot_skip_postmortem_to_closed_for_major_and_above(self) -> None:
        """A major incident closed without a postmortem is a lesson deliberately
        not learned.  Info and warning may close directly."""
        for severity in (DriftSeverity.MAJOR, DriftSeverity.CRITICAL):
            with self.subTest(severity=severity):
                resolved = _walk(
                    IncidentState.ACKNOWLEDGED,
                    IncidentState.MITIGATING,
                    IncidentState.RESOLVED,
                    severity=severity,
                )
                with self.assertRaises(IllegalIncidentTransition):
                    resolved.apply(
                        _transition(IncidentState.RESOLVED, IncidentState.CLOSED)
                    )
        for severity in (DriftSeverity.INFO, DriftSeverity.WARNING):
            with self.subTest(severity=severity):
                resolved = _walk(
                    IncidentState.ACKNOWLEDGED,
                    IncidentState.MITIGATING,
                    IncidentState.RESOLVED,
                    severity=severity,
                )
                closed = resolved.apply(
                    _transition(IncidentState.RESOLVED, IncidentState.CLOSED)
                )
                self.assertIs(closed.state, IncidentState.CLOSED)

    def test_an_illegal_transition_attempt_is_still_recorded(self) -> None:
        """AGENTS.md: 失败记录不可删除.  A refused transition is evidence about
        who tried what, and it is exactly the evidence an audit wants."""
        incident = _open_incident()
        with self.assertRaises(IllegalIncidentTransition):
            incident.apply(_transition(IncidentState.OPEN, IncidentState.CLOSED))
        # The domain object is frozen and unchanged; the service records the
        # attempt.  Asserted in test_incident_service.py.
        self.assertIs(incident.state, IncidentState.OPEN)


class ReopenTest(unittest.TestCase):
    def test_resolved_can_reopen_with_a_reason(self) -> None:
        """A mitigation that did not hold is the normal case, not an exception.
        Forcing a new incident id would break the link to the original
        investigation."""
        reopened = _resolved_incident().apply(
            _transition(IncidentState.RESOLVED, IncidentState.OPEN,
                        reason="mitigation did not hold; PSI back above 0.25")
        )
        self.assertIs(reopened.state, IncidentState.OPEN)
        self.assertEqual(reopened.reopen_count, 1)

    def test_reopen_requires_a_reason(self) -> None:
        with self.assertRaises(ValueError):
            _resolved_incident().apply(
                _transition(IncidentState.RESOLVED, IncidentState.OPEN, reason="   ")
            )

    def test_reopen_preserves_the_whole_earlier_transition_history(self) -> None:
        """The audit chain is the point.  A reopen that truncates history makes the
        second investigation start blind."""
        reopened = _resolved_incident().apply(
            _transition(IncidentState.RESOLVED, IncidentState.OPEN, reason="regressed")
        )
        self.assertEqual(
            tuple(t.to_state for t in reopened.transitions)[:3],
            (IncidentState.ACKNOWLEDGED, IncidentState.MITIGATING, IncidentState.RESOLVED),
        )

    def test_reopen_count_increments_and_never_decrements(self) -> None:
        """Three reopens is a signal about the quality of the mitigations, and it
        is lost if the counter resets."""
        incident = _resolved_incident()
        for round_number in range(1, 4):
            incident = incident.apply(
                _transition(IncidentState.RESOLVED, IncidentState.OPEN,
                            reason=f"regression {round_number}")
            )
            self.assertEqual(incident.reopen_count, round_number)
            incident = incident.apply(
                _transition(IncidentState.OPEN, IncidentState.MITIGATING)
            )
            incident = incident.apply(
                _transition(IncidentState.MITIGATING, IncidentState.RESOLVED)
            )
            self.assertEqual(incident.reopen_count, round_number)

    def test_a_closed_incident_cannot_reopen(self) -> None:
        """Closed is terminal by design; a recurrence after closure is a new
        incident with a link to the old one."""
        with self.assertRaises(IllegalIncidentTransition):
            _closed_incident().apply(
                _transition(IncidentState.CLOSED, IncidentState.OPEN,
                            reason="it came back")
            )


class TransitionRecordTest(unittest.TestCase):
    def test_transitions_are_time_ordered(self) -> None:
        acknowledged = _acknowledged_incident()
        with self.assertRaises(ValueError):
            acknowledged.apply(
                _transition(IncidentState.ACKNOWLEDGED, IncidentState.MITIGATING,
                            at=OPENED - timedelta(minutes=1))
            )
        occurred = [t.occurred_at for t in _closed_incident().transitions]
        self.assertEqual(occurred, sorted(occurred))

    def test_a_transition_requires_an_actor_and_a_reason(self) -> None:
        with self.assertRaises(ValueError):
            _transition(IncidentState.OPEN, IncidentState.ACKNOWLEDGED, actor_id="   ")
        with self.assertRaises(ValueError):
            _transition(IncidentState.OPEN, IncidentState.ACKNOWLEDGED, reason="   ")

    def test_transitions_are_append_only(self) -> None:
        """Incident is frozen and apply() returns a new value; the tuple grows and
        no element is ever replaced."""
        acknowledged = _acknowledged_incident()
        before = acknowledged.transitions
        mitigating = acknowledged.apply(
            _transition(IncidentState.ACKNOWLEDGED, IncidentState.MITIGATING)
        )
        self.assertIsNot(mitigating, acknowledged)
        self.assertEqual(acknowledged.transitions, before)
        self.assertEqual(mitigating.transitions[: len(before)], before)
        self.assertEqual(len(mitigating.transitions), len(before) + 1)

    def test_severity_can_be_raised_but_the_original_is_kept(self) -> None:
        """Downgrading severity in place is how a critical becomes a warning
        retroactively, which makes escalation-time SLOs unauditable."""
        incident = _open_incident(DriftSeverity.WARNING)
        escalated = incident.escalate_severity(
            DriftSeverity.CRITICAL,
            actor_id="subject:reviewer-1",
            actor_role="reviewer",
            occurred_at=OPENED + timedelta(hours=2),
            reason="a second provider began failing on the same key",
        )
        self.assertIs(escalated.severity, DriftSeverity.CRITICAL)
        self.assertIs(incident.severity, DriftSeverity.WARNING)
        # The originating alert keeps the severity it fired with.
        self.assertIs(escalated.alerts[0].severity, DriftSeverity.WARNING)
        with self.assertRaises(ValueError):
            escalated.escalate_severity(
                DriftSeverity.WARNING,
                actor_id="subject:reviewer-1",
                actor_role="reviewer",
                occurred_at=OPENED + timedelta(hours=3),
                reason="looks less serious now",
            )
```

- [ ] **Step 6: 运行 → 逐转移实现 → 转绿**

**一个转移一次实现，不要一次写完 `_ALLOWED_INCIDENT_TRANSITIONS`。**
第一个失败的转移会掩盖后面的。

- [ ] **Step 7: owner 路由与跨域 Incident（红测先行）**

```python
def _cross_domain_incident(
    *,
    primary: str = "data",
    contributors: tuple[str, ...] = ("research",),
) -> Incident:
    """A stale dataset that broke a factor: data owns it, research contributes."""
    return Incident(
        incident_id="incident:0002",
        dedupe_key="e" * 64,
        state=IncidentState.OPEN,
        severity=DriftSeverity.MAJOR,
        primary_owner_scope=primary,
        contributor_owner_scopes=contributors,
        runbook_id="runbook.stale-dataset.v1",
        alerts=(_alert(),),
        transitions=(),
        opened_at=OPENED,
        reopen_count=0,
    )


class OwnerRoutingTest(unittest.TestCase):
    """ADR-0009 逐字：跨域 Incident 可以有一个 primary owner 和多个 contributors,
    但只能由权限策略允许的主体确认、转派、缓解和关闭.
    """

    def test_a_cross_domain_incident_has_one_primary_and_many_contributors(self) -> None:
        """A stale dataset that broke a factor is owned by data with research as a
        contributor.  Two primaries means neither acts."""
        incident = _cross_domain_incident(contributors=("research", "portfolio"))
        self.assertEqual(incident.primary_owner_scope, "data")
        self.assertEqual(incident.contributor_owner_scopes, ("research", "portfolio"))
        self.assertIsInstance(incident.primary_owner_scope, str)

    def test_the_primary_owner_is_not_also_listed_as_a_contributor(self) -> None:
        with self.assertRaises(ValueError):
            _cross_domain_incident(primary="data", contributors=("data", "research"))

    def test_a_contributor_cannot_close_the_incident(self) -> None:
        """ADR-0009 restricts acknowledge, reassign, mitigate and close to
        permitted subjects; a contributor closing an incident they do not own is
        how a data problem gets closed by the research team that only saw the
        symptom."""
        incident = _cross_domain_incident()
        with self.assertRaises(PermissionError):
            incident.assert_may_close(owner_scope="research")
        incident.assert_may_close(owner_scope="data")

    def test_reassigning_the_primary_owner_is_an_audited_transition(self) -> None:
        """Not a field update.  A silent reassignment makes the escalation clock
        restart with nothing recording why."""
        incident = _cross_domain_incident()
        reassigned = incident.reassign_primary_owner(
            "research",
            actor_id="subject:admin-1",
            actor_role="administrator",
            occurred_at=OPENED + timedelta(hours=1),
            reason="root cause is the feature definition, not the source data",
        )
        self.assertEqual(reassigned.primary_owner_scope, "research")
        self.assertEqual(incident.primary_owner_scope, "data")
        self.assertEqual(len(reassigned.transitions), len(incident.transitions) + 1)
        self.assertIn("root cause", reassigned.transitions[-1].reason)
        with self.assertRaises(ValueError):
            incident.reassign_primary_owner(
                "research",
                actor_id="subject:admin-1",
                actor_role="administrator",
                occurred_at=OPENED + timedelta(hours=1),
                reason="   ",
            )

    def test_an_incident_with_no_owner_cannot_be_constructed(self) -> None:
        """The '系统错误' bucket ADR-0009 exists to remove."""
        for primary in ("", "   ", "system", "unknown"):
            with self.subTest(primary=primary):
                with self.assertRaises(ValueError):
                    _cross_domain_incident(primary=primary)
```

- [ ] **Step 8: 编排服务（红测先行）—— Alert → Incident**

```python
# platform/tests/test_incident_service.py
"""Alert intake, deduplication and the audited transition path.

The service is where dedupe meets persistence, so it owns the one behaviour the
pure domain cannot express: the 500th occurrence of a key must find the existing
incident rather than create a new one, and it must do so idempotently under a
retried worker run.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from a_share_platform.adapters.memory.monitoring import (
    InMemoryIncidentRepository,
    UnavailableIncidentRepository,
    UnavailableMonitoringStore,
)
from a_share_platform.application.incident_service import IncidentService
from a_share_platform.application.permissions import (
    PermissionPolicy,
    Principal,
    Role,
)
from a_share_platform.domain.attribution import (
    AttributionClosureBreach,
    AttributionLayer,
)
from a_share_platform.domain.incidents import AlertSource, IncidentState

FIRST = datetime(2026, 8, 16, 1, 0, tzinfo=UTC)

# tests/test_alert_dedupe.py already defines the Alert fixture; reusing it keeps
# one definition of an Alert in the suite rather than two that can drift apart.
from tests.test_alert_dedupe import alert as _build_alert  # noqa: E402


def _at(index: int) -> datetime:
    return FIRST + timedelta(minutes=index)


def _alert(*, alert_id: str = "alert:0001", at: datetime = FIRST) -> object:
    return _build_alert(alert_id=alert_id, seen_at=at)


def _service(
    *, repository: object | None = None, incidents: tuple[object, ...] = ()
) -> IncidentService:
    return IncidentService(
        repository=repository or InMemoryIncidentRepository(incidents=incidents),
        permission_policy=PermissionPolicy.default(),
    )


def _reviewer() -> Principal:
    return Principal("subject:reviewer-1", frozenset({Role.REVIEWER}))


def _agent() -> Principal:
    return Principal("subject:agent-1", frozenset({Role.AGENT}))


def _viewer() -> Principal:
    return Principal("subject:viewer-1", frozenset({Role.VIEWER}))


def _closure_breach(
    *, residual: Decimal, tolerance: Decimal
) -> AttributionClosureBreach:
    return AttributionClosureBreach(
        snapshot_id="attribution:unified:2026-08-14",
        layer=AttributionLayer.MODEL_VS_PORTFOLIO,
        session=FIRST.date(),
        residual=residual,
        tolerance=tolerance,
        threshold_policy_hash="f" * 64,
        owner_scope="portfolio",
        evidence_ids=("evidence:portfolio-series:2026-08-14",),
    )


class IntakeTest(unittest.TestCase):
    def test_the_first_alert_of_a_key_opens_an_incident(self) -> None:
        service = _service()
        incident = service.ingest_alert(_alert())
        self.assertIs(incident.state, IncidentState.OPEN)
        self.assertEqual(incident.dedupe_key, _alert().dedupe_key)
        self.assertEqual(len(service.list_incidents()), 1)

    def test_the_five_hundredth_alert_of_a_key_opens_no_new_incident(self) -> None:
        service = _service()
        for index in range(500):
            service.ingest_alert(_alert(alert_id=f"alert:{index:04d}", at=_at(index)))
        incidents = service.list_incidents()
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0].alerts[-1].occurrence_count, 500)

    def test_an_alert_for_a_resolved_incident_reopens_it_with_audit(self) -> None:
        """A recurrence after resolution is the same problem returning, and the
        link to the first investigation is the most valuable thing about it."""
        service = _service()
        opened = service.ingest_alert(_alert())
        for target in (
            IncidentState.ACKNOWLEDGED,
            IncidentState.MITIGATING,
            IncidentState.RESOLVED,
        ):
            service.transition(
                incident_id=opened.incident_id, to_state=target,
                principal=_reviewer(), reason=f"moving to {target.value}",
                occurred_at=_at(len(service.list_audit_events()) + 1),
            )
        reopened = service.ingest_alert(_alert(alert_id="alert:0002", at=_at(60)))
        self.assertEqual(reopened.incident_id, opened.incident_id)
        self.assertIs(reopened.state, IncidentState.OPEN)
        self.assertEqual(reopened.reopen_count, 1)
        self.assertEqual(len(service.list_incidents()), 1)

    def test_an_alert_for_a_closed_incident_opens_a_new_linked_incident(self) -> None:
        service = _service()
        first = service.ingest_alert(_alert())
        service.close_for_test(first.incident_id, principal=_reviewer())
        second = service.ingest_alert(_alert(alert_id="alert:0002", at=_at(120)))
        self.assertNotEqual(second.incident_id, first.incident_id)
        self.assertEqual(second.dedupe_key, first.dedupe_key)
        self.assertEqual(second.preceding_incident_id, first.incident_id)
        self.assertEqual(len(service.list_incidents()), 2)

    def test_ingesting_the_same_alert_id_twice_is_idempotent(self) -> None:
        """A retried worker run must not double the occurrence count, or the
        count stops meaning anything."""
        service = _service()
        service.ingest_alert(_alert(alert_id="alert:0001"))
        service.ingest_alert(_alert(alert_id="alert:0001"))
        incidents = service.list_incidents()
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0].alerts[-1].occurrence_count, 1)

    def test_an_attribution_closure_breach_becomes_an_incident(self) -> None:
        """Task 1 Step 8 emits AttributionClosureBreach as a value; this is where
        Step 08's '残差超阈值创建 blocker/Incident' actually happens.  Without this
        wiring the breach is a field nobody reads."""
        breach = _closure_breach(residual=Decimal("0.0031"), tolerance=Decimal("0.0005"))
        incident = _service().ingest_closure_breach(breach)
        self.assertIs(incident.state, IncidentState.OPEN)
        self.assertEqual(incident.primary_owner_scope, "portfolio")
        self.assertEqual(incident.alerts[0].source, AlertSource.ATTRIBUTION_CLOSURE)

    def test_a_closure_breach_incident_names_the_threshold_policy(self) -> None:
        """So a later re-run under a looser tolerance cannot make the incident
        look like it was a false positive."""
        breach = _closure_breach(residual=Decimal("0.0031"), tolerance=Decimal("0.0005"))
        incident = _service().ingest_closure_breach(breach)
        alert = incident.alerts[0]
        self.assertIn(breach.threshold_policy_hash, alert.source_ids)
        self.assertIn(breach.snapshot_id, alert.source_ids)


class PermissionTest(unittest.TestCase):
    def test_agent_cannot_acknowledge_or_close(self) -> None:
        """Role.AGENT holds only READ_PUBLIC in PermissionPolicy.default().  An
        agent that could close incidents would be able to silence the monitoring
        of its own outputs."""
        from a_share_platform.application.permissions import Principal, Role

        agent = Principal("subject:agent-1", frozenset({Role.AGENT}))
        with self.assertRaises(PermissionError):
            _service().transition(
                incident_id="incident:0001", to_state=IncidentState.ACKNOWLEDGED,
                principal=agent, reason="handled", occurred_at=_at(1),
            )

    def test_viewer_cannot_transition(self) -> None:
        service = _service()
        incident = service.ingest_alert(_alert())
        with self.assertRaises(PermissionError):
            service.transition(
                incident_id=incident.incident_id,
                to_state=IncidentState.ACKNOWLEDGED,
                principal=_viewer(), reason="looks fine to me",
                occurred_at=_at(1),
            )
        self.assertIs(
            service.get_incident(incident.incident_id).state, IncidentState.OPEN
        )

    def test_a_refused_transition_is_recorded_as_an_audit_event(self) -> None:
        """AGENTS.md: 失败记录不可删除或改写为成功.  The attempt is the evidence."""
        service = _service()
        incident = service.ingest_alert(_alert())
        with self.assertRaises(PermissionError):
            service.transition(
                incident_id=incident.incident_id,
                to_state=IncidentState.ACKNOWLEDGED,
                principal=_agent(), reason="agent transition attempt",
                occurred_at=_at(1),
            )
        self.assertEqual(len(service.list_audit_events()), 1)
        self.assertEqual(service.list_audit_events()[0].outcome, "denied")


class UnavailableStoreTest(unittest.TestCase):
    def test_an_unconfigured_store_is_unavailable_not_empty(self) -> None:
        """Following the UnavailableFactorReviewRepository pattern already in
        adapters/memory/factor_reviews.py: raising a named error, so 'no store'
        and 'no incidents' stay different answers."""
        unconfigured = _service(repository=UnavailableIncidentRepository())
        with self.assertRaises(UnavailableMonitoringStore):
            unconfigured.list_incidents()
        self.assertEqual(_service().list_incidents(), ())
```

- [ ] **Step 9: Desk `_active_failures()` 接真实 Incident（红测先行）**

```python
# 扩展 platform/tests/test_desk_projection.py
from datetime import UTC, date, datetime

from a_share_platform.adapters.memory.monitoring import InMemoryIncidentLedger
from a_share_platform.adapters.memory.system_catalog import StaticSystemCatalogReader
from a_share_platform.application.system_catalog import IngestionJobEntry
from a_share_platform.domain.desk import DeskSectionKey, DeskSectionStatus

JOB_AT = datetime(2026, 8, 16, 1, 0, tzinfo=UTC)


def _catalog_with_failing_jobs(*, count: int) -> StaticSystemCatalogReader:
    """`count` failed ingestion jobs sharing one failure reason.

    One reason across all of them is the real shape of a provider rate limit, and
    it is the case dedupe exists for: 500 rows, one root cause.
    """
    return StaticSystemCatalogReader(
        jobs=tuple(
            IngestionJobEntry(
                job_id=f"job:{index:04d}",
                plan_id="plan:eod-prices",
                provider_id="provider:example",
                status="failed",
                output_trust_state="raw",
                start_date=date(2026, 8, 14),
                end_date=date(2026, 8, 14),
                created_at=JOB_AT,
                updated_at=JOB_AT,
                dataset_version_id=None,
                failure_reasons=("provider rate limit exceeded",),
                checkpoints=(),
                quality_reports=(),
                coverage_reports=(),
            )
            for index in range(count)
        )
    )


def _desk_with_incidents(
    *, jobs_failing: int = 500, incidents: tuple[object, ...] | None = None
):
    """A desk whose job catalog reports `jobs_failing` failures behind one incident.

    Both numbers are fixture facts, so the coverage assertions below are about the
    projection rather than about an incidental count.
    """
    from tests.test_incident_state_machine import _open_incident

    ledger = InMemoryIncidentLedger(
        incidents=(_open_incident(),) if incidents is None else incidents
    )
    return DeskProjectionService(
        system_catalog=_catalog_with_failing_jobs(count=jobs_failing),
        incidents=ledger,
    )


class ActiveFailureIncidentTest(unittest.TestCase):
    def test_the_p9_incident_blocker_is_gone_once_the_ledger_exists(self) -> None:
        """The blocker code P9_INCIDENT_LEDGER_NOT_IMPLEMENTED is this task's
        acceptance anchor.  It disappears because a real ledger exists, not
        because the string was deleted."""
        projection = _desk_with_incidents().project(now=NOW)
        section = projection.section(DeskSectionKey.ACTIVE_FAILURES)
        codes = {blocker.code for blocker in section.blockers}
        self.assertNotIn("P9_INCIDENT_LEDGER_NOT_IMPLEMENTED", codes)

    def test_coverage_keeps_both_the_raw_failure_count_and_the_incident_count(
        self,
    ) -> None:
        """Deduplication that only reports the incident count looks like the
        failures went away.  500 failing jobs behind 1 incident must show both
        numbers, or the desk under-reports a real outage by 499."""
        section = _desk_with_incidents().project(now=NOW).section(
            DeskSectionKey.ACTIVE_FAILURES
        )
        self.assertEqual(section.coverage["jobs_failing"], 500)
        self.assertEqual(section.coverage["incidents_open"], 1)

    def test_an_empty_incident_ledger_with_failing_jobs_is_still_partial(self) -> None:
        """Jobs failing while no incident exists means intake has not run, which
        is itself worth surfacing rather than showing a clean desk."""
        section = _desk_with_incidents(jobs_failing=500, incidents=()).project(
            now=NOW
        ).section(DeskSectionKey.ACTIVE_FAILURES)
        self.assertIs(section.status, DeskSectionStatus.PARTIAL)
        self.assertEqual(section.coverage["jobs_failing"], 500)
        self.assertEqual(section.coverage["incidents_open"], 0)
        codes = {blocker.code for blocker in section.blockers}
        self.assertIn("INCIDENT_INTAKE_HAS_NOT_RUN", codes)
```

- [ ] **Step 10: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/domain/incidents.py \
  platform/src/a_share_platform/application/incident_service.py \
  platform/src/a_share_platform/adapters/memory/monitoring.py \
  platform/src/a_share_platform/ports/monitoring.py \
  platform/src/a_share_platform/application/desk_projection.py \
  platform/tests/test_alert_dedupe.py \
  platform/tests/test_incident_state_machine.py \
  platform/tests/test_incident_service.py \
  platform/tests/test_desk_projection.py
git commit -m "feat: add alert deduplication and an audited incident state machine

One root cause is one incident however many times it fires.  A provider rate limit
fails five hundred jobs at once and the desk currently lists all five hundred:
_active_failures() iterates jobs with no grouping.  After the first real outage
that list is unusable, and the genuinely unrelated second failure is buried in it.

The key is the hard part, not the grouping.  owner_scope alone would merge
unrelated subjects and hide the second problem; anything containing a timestamp or
a measured value deduplicates nothing.  The key is subject id, subject version,
metric and owner scope — what broke, which version of it, what measurement says
so, and who owns it.  It is a sha256 of the canonical form rather than a tuple
hash, because PYTHONHASHSEED randomisation would defeat deduplication in
production while every in-process test stayed green.

Deduplication must not hide scale, so the desk keeps both numbers: five hundred
failing jobs behind one incident shows five hundred and one.  Reporting only the
incident count would under-report a real outage by four hundred and ninety-nine
and look like the failures went away.

Every transition has its own test and every illegal one is asserted refused.  The
asymmetry justifies the verbosity: allowing an illegal transition loses the audit
chain permanently, while forbidding a legal one merely blocks work until someone
notices.  open-to-closed is called out specifically because it is the one someone
reaches for at the end of a long day, and it discards the entire question of what
was done.  Closed is terminal; a recurrence reopens through the audited path or
opens a new linked incident, and a reopen preserves the whole earlier history
because the second investigation otherwise starts blind.

Refused transitions are recorded rather than discarded.  A denied attempt is
evidence about who tried what, which is precisely what an audit is looking for.
Role.AGENT is denied acknowledge and close outright: an agent able to close
incidents could silence the monitoring of its own output.

Attribution closure breaches enter here as alerts, which is where Step 08's
requirement that an over-tolerance residual creates an incident actually happens.
Without this wiring the breach would be a field nobody reads."
```

---

### Task 4: 审批泛化 —— 从 factor-only 到 Alpha/Timing/Risk/Portfolio，加 SoD、expiry、supersede

对应 Step 08 Task 4：「复用 P1/P4 权限和 review 合同，泛化到 Alpha/Timing/Risk/Portfolio；
不重写身份系统。测试 SoD、expiry、supersede、rollback 和 Agent denial。」

**这是本 plan 风险最高的 Task，因为它改的是唯一一条能让某个版本影响生产的路径。**

三条设计约束，理由都在后面展开：

1. **不新增 `Permission` 枚举值，不改 `PermissionPolicy.default()`。** 泛化在服务层做。
2. **不放宽 `FactorPromotionReview` 的任何守卫。** 它保留 `factor_lifecycle_status is CANDIDATE`
   的硬要求，新的通用合同**并行存在**，因子路径可以后续迁移，但本 plan 不迁移。
3. **`PromotionApproval.authorizes()` 不回改。** 加 expiry/supersede 会让 P4 的既有 Review
   记录突然全部过期——那是改写历史。新的 `ApprovalReview.authorizes()` 有这两条判定。

**Files:**
- Create: `platform/src/a_share_platform/domain/approvals.py`
- Create: `platform/src/a_share_platform/domain/serving.py`
- Create: `platform/src/a_share_platform/application/approval_service.py`
- Create: `platform/src/a_share_platform/application/serving_registry.py`
- Create: `platform/src/a_share_platform/ports/approvals.py`
- Create: `platform/src/a_share_platform/ports/serving.py`
- Create: `platform/src/a_share_platform/adapters/memory/approvals.py`
- Test: `platform/tests/test_approval_generalisation.py`
- Test: `platform/tests/test_approval_segregation_of_duties.py`
- Test: `platform/tests/test_approval_expiry_and_supersede.py`
- Test: `platform/tests/test_serving_registry.py`

**Interfaces:**
- Consumes: `application/permissions.py`（原样）、`domain/factor_lifecycle.py` 的
  `ApprovalScope` / `ApprovalDecision`（原样复用两个枚举）、
  `domain/factor_reviews.py`（作为模板，不修改）
- Produces:
  ```python
  class ApprovalSubjectKind(StrEnum):
      """Step 08 Task 4 逐字：泛化到 Alpha/Timing/Risk/Portfolio."""
      FACTOR = "factor"
      ALPHA_MODEL = "alpha_model"
      INVESTMENT_VIEW = "investment_view"
      TIMING_MODEL = "timing_model"
      RISK_MODEL = "risk_model"
      PORTFOLIO_POLICY = "portfolio_policy"

  # 每个 subject kind 需要哪个 Permission —— 直接读自现有权限矩阵，不新增枚举值。
  SUBJECT_PERMISSION: Mapping[ApprovalSubjectKind, Permission] = {
      ApprovalSubjectKind.FACTOR: Permission.APPROVE_RESEARCH,
      ApprovalSubjectKind.ALPHA_MODEL: Permission.APPROVE_RESEARCH,
      ApprovalSubjectKind.INVESTMENT_VIEW: Permission.APPROVE_RESEARCH,
      ApprovalSubjectKind.TIMING_MODEL: Permission.APPROVE_RESEARCH,
      ApprovalSubjectKind.RISK_MODEL: Permission.APPROVE_PORTFOLIO,
      ApprovalSubjectKind.PORTFOLIO_POLICY: Permission.APPROVE_PORTFOLIO,
  }

  # 每个 subject kind 的角色集合 —— 与 FactorReviewService 的 AND 结构一致。
  SUBJECT_ROLES: Mapping[ApprovalSubjectKind, frozenset[Role]] = {
      ...FACTOR / ALPHA_MODEL / INVESTMENT_VIEW / TIMING_MODEL:
          frozenset({Role.REVIEWER, Role.ADMINISTRATOR}),
      ...RISK_MODEL / PORTFOLIO_POLICY:
          frozenset({Role.PORTFOLIO_MANAGER, Role.ADMINISTRATOR}),
  }

  @dataclass(frozen=True)
  class ApprovalSubject:
      """What is being approved, and its own precondition.

      The precondition is subject-declared rather than checked centrally, because
      FactorPromotionReview's `factor_lifecycle_status is CANDIDATE` requirement is
      correct for a factor and meaningless for a PortfolioPolicy, which has no
      lifecycle enum at all.
      """
      kind: ApprovalSubjectKind
      subject_id: str
      subject_version: str
      subject_hash: str                     # sha256
      submitted_by: str                     # ← SoD 的另一半，现有代码没有
      submitted_at: datetime
      precondition_satisfied: bool
      precondition_reason: str | None       # 未满足时必填

  @dataclass(frozen=True)
  class ApprovalReview:
      review_id: str
      subject: ApprovalSubject
      validation_evidence_id: str
      validation_evidence_hash: str         # sha256
      scientific_gate_passed: bool
      scope: ApprovalScope                  # 复用，不新建
      decision: ApprovalDecision            # 复用，不新建
      actor_id: str
      actor_role: str
      decided_at: datetime
      reason: str
      evidence_hashes: tuple[str, ...]
      expires_at: datetime | None           # ← 新增
      supersedes_review_id: str | None       # ← 新增
      content_hash: str = field(init=False)

      def authorizes(self, *, subject: ApprovalSubject, scope: ApprovalScope,
                     at: datetime, superseded_by: tuple[str, ...] = ()) -> bool: ...

      @property
      def grants_account_access(self) -> bool: return False
      @property
      def grants_order_authority(self) -> bool: return False

  @dataclass(frozen=True)
  class ServingRegistration:
      registration_id: str
      subject: ApprovalSubject
      review_id: str
      scope: ApprovalScope
      effective_from: datetime
      effective_until: datetime | None
      rollback_target_registration_id: str | None
      content_hash: str = field(init=False)
  ```

- [ ] **Step 1: 先读现有两个模板的真实差异**

```bash
cd platform
grep -n "class FactorPromotionReview" -A 100 src/a_share_platform/domain/factor_reviews.py
grep -n "class TimingPromotionReview" -A 60 src/a_share_platform/domain/timing_research.py \
  src/a_share_platform/application/timing_promotion.py 2>/dev/null
grep -n "created_by" src/a_share_platform/domain/factor_lifecycle.py
grep -rn "submitted_by\|submitter\|requested_by" src/a_share_platform/
```

**已核实的现状（2026-08-16）**：

- `FactorVersion.created_by` **存在**（`domain/factor_lifecycle.py` 第 491 行）；
- `FactorReviewService.record_review()` **从不读它**；
- `grep -rn "submitted_by\|submitter\|requested_by" src/` 返回 **0 行**。

**因此职责分离在当前代码里完全不存在。** 这是本 Task 要补的第一个真实漏洞。
如果 P-6 已完成，还要读它的 `TimingPromotionReview` —— 两个模板才能推出正确的抽象。

- [ ] **Step 2: 写红测 —— 职责分离（用真实类，可直接运行）**

```python
# platform/tests/test_approval_segregation_of_duties.py
"""The person who submits cannot approve.

This is not currently enforced anywhere.  FactorVersion carries created_by and
FactorReviewService never reads it; a grep for submitted_by, submitter or
requested_by across src/ returns nothing.  So today a Reviewer who registers a
FactorVersion can approve it in the next call, and the resulting
FactorPromotionReview is indistinguishable from one a second person signed.

The prototype was stricter than the implementation: Figma node 9:883 draws a
提交人 column next to a Reviewer column, with User-1 submitting and Reviewer-2
approving.  This test makes the implementation catch up with the design.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from a_share_platform.application.approval_service import (
    ApprovalDenied,
    ApprovalService,
    SegregationOfDutiesViolation,
)
from a_share_platform.application.permissions import (
    Permission,
    PermissionPolicy,
    Principal,
    Role,
)
from a_share_platform.domain.approvals import ApprovalSubject, ApprovalSubjectKind
from a_share_platform.domain.factor_lifecycle import ApprovalDecision, ApprovalScope
from a_share_platform.adapters.memory.approvals import InMemoryApprovalRepository

SUBMITTED_AT = datetime(2026, 8, 16, 1, 0, tzinfo=UTC)
DECIDED_AT = datetime(2026, 8, 16, 3, 0, tzinfo=UTC)
EVIDENCE_HASH = "a" * 64
SUBJECT_HASH = "b" * 64


def subject(
    *,
    kind: ApprovalSubjectKind = ApprovalSubjectKind.ALPHA_MODEL,
    submitted_by: str = "subject:researcher-1",
) -> ApprovalSubject:
    return ApprovalSubject(
        kind=kind,
        subject_id="alpha-model:composite",
        subject_version="v2",
        subject_hash=SUBJECT_HASH,
        submitted_by=submitted_by,
        submitted_at=SUBMITTED_AT,
        precondition_satisfied=True,
        precondition_reason=None,
    )


def service() -> ApprovalService:
    return ApprovalService(
        repository=InMemoryApprovalRepository(),
        permission_policy=PermissionPolicy.default(),
    )


def reviewer(subject_id: str = "subject:reviewer-1") -> Principal:
    return Principal(subject_id=subject_id, roles=frozenset({Role.REVIEWER}))


def portfolio_manager(subject_id: str = "subject:pm-1") -> Principal:
    return Principal(subject_id=subject_id, roles=frozenset({Role.PORTFOLIO_MANAGER}))


def administrator(subject_id: str = "subject:admin-1") -> Principal:
    return Principal(subject_id=subject_id, roles=frozenset({Role.ADMINISTRATOR}))


class SegregationOfDutiesTest(unittest.TestCase):
    def test_a_reviewer_cannot_approve_what_they_submitted(self) -> None:
        """The core assertion of this file."""
        with self.assertRaises(SegregationOfDutiesViolation):
            service().record_review(
                subject=subject(submitted_by="subject:reviewer-1"),
                validation_evidence_id="validation:0001",
                validation_evidence_hash=EVIDENCE_HASH,
                scientific_gate_passed=True,
                review_id="review:0001",
                scope=ApprovalScope.RESEARCH_BACKTEST,
                decision=ApprovalDecision.APPROVED,
                principal=reviewer("subject:reviewer-1"),
                decided_at=DECIDED_AT,
                reason="self approval attempt",
                evidence_hashes=(EVIDENCE_HASH,),
                expires_at=None,
                supersedes_review_id=None,
            )

    def test_a_different_reviewer_may_approve_the_same_subject(self) -> None:
        review = service().record_review(
            subject=subject(submitted_by="subject:researcher-1"),
            validation_evidence_id="validation:0001",
            validation_evidence_hash=EVIDENCE_HASH,
            scientific_gate_passed=True,
            review_id="review:0001",
            scope=ApprovalScope.RESEARCH_BACKTEST,
            decision=ApprovalDecision.APPROVED,
            principal=reviewer("subject:reviewer-1"),
            decided_at=DECIDED_AT,
            reason="evidence complete; IC and cross-check attached",
            evidence_hashes=(EVIDENCE_HASH,),
            expires_at=None,
            supersedes_review_id=None,
        )
        self.assertEqual(review.decision, ApprovalDecision.APPROVED)
        self.assertEqual(review.actor_id, "subject:reviewer-1")
        self.assertEqual(review.subject.submitted_by, "subject:researcher-1")

    def test_an_administrator_cannot_self_approve_either(self) -> None:
        """Administrator holds frozenset(Permission) — all eight, including
        SEND_ORDER.  If separation of duties had an exemption anywhere, this is the
        role it would be granted to, and it is the one role where it matters most.
        """
        with self.assertRaises(SegregationOfDutiesViolation):
            service().record_review(
                subject=subject(submitted_by="subject:admin-1"),
                validation_evidence_id="validation:0001",
                validation_evidence_hash=EVIDENCE_HASH,
                scientific_gate_passed=True,
                review_id="review:0002",
                scope=ApprovalScope.RESEARCH_BACKTEST,
                decision=ApprovalDecision.APPROVED,
                principal=administrator("subject:admin-1"),
                decided_at=DECIDED_AT,
                reason="admin self approval attempt",
                evidence_hashes=(EVIDENCE_HASH,),
                expires_at=None,
                supersedes_review_id=None,
            )

    def test_self_rejection_is_also_refused(self) -> None:
        """Rejecting your own submission looks harmless, but allowing it means the
        SoD check is decision-dependent — and a decision-dependent check is one
        conditional away from being bypassed by approving in two steps.
        """
        with self.assertRaises(SegregationOfDutiesViolation):
            service().record_review(
                subject=subject(submitted_by="subject:reviewer-1"),
                validation_evidence_id="validation:0001",
                validation_evidence_hash=EVIDENCE_HASH,
                scientific_gate_passed=True,
                review_id="review:0003",
                scope=ApprovalScope.RESEARCH_BACKTEST,
                decision=ApprovalDecision.REJECTED,
                principal=reviewer("subject:reviewer-1"),
                decided_at=DECIDED_AT,
                reason="self rejection attempt",
                evidence_hashes=(EVIDENCE_HASH,),
                expires_at=None,
                supersedes_review_id=None,
            )

    def test_the_violation_is_recorded_as_a_denied_audit_event(self) -> None:
        """AGENTS.md: 失败记录不可删除或改写为成功.  A self-approval attempt is
        exactly the event an audit is looking for, so discarding it defeats the
        purpose of having the check.
        """
        instance = service()
        with self.assertRaises(SegregationOfDutiesViolation):
            instance.record_review(
                subject=subject(submitted_by="subject:reviewer-1"),
                validation_evidence_id="validation:0001",
                validation_evidence_hash=EVIDENCE_HASH,
                scientific_gate_passed=True,
                review_id="review:0004",
                scope=ApprovalScope.RESEARCH_BACKTEST,
                decision=ApprovalDecision.APPROVED,
                principal=reviewer("subject:reviewer-1"),
                decided_at=DECIDED_AT,
                reason="self approval attempt",
                evidence_hashes=(EVIDENCE_HASH,),
                expires_at=None,
                supersedes_review_id=None,
            )
        events = instance.list_audit_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].outcome, "denied")
        self.assertIn("segregation", events[0].reason.lower())
        self.assertEqual(instance.list_reviews(), ())

    def test_a_subject_with_no_submitter_cannot_be_constructed(self) -> None:
        """Without a submitter the SoD check has nothing to compare against, and
        it would silently pass on every subject that omitted the field."""
        with self.assertRaises(ValueError):
            ApprovalSubject(
                kind=ApprovalSubjectKind.ALPHA_MODEL,
                subject_id="alpha-model:composite",
                subject_version="v2",
                subject_hash=SUBJECT_HASH,
                submitted_by="   ",
                submitted_at=SUBMITTED_AT,
                precondition_satisfied=True,
                precondition_reason=None,
            )


class AgentDenialTest(unittest.TestCase):
    """Role.AGENT holds exactly frozenset({Permission.READ_PUBLIC}).

    That is the correct deny-by-default result, and it needs a test precisely
    because it is one line away from being wrong: adding artifact_read or an
    approve permission to the AGENT row of PermissionPolicy.default() is a
    single-line diff that would pass every other test in the suite.

    Note the agent does not even hold READ_ARTIFACT, so it cannot read the
    evidence it would be approving against.  Both facts are asserted.
    """

    def test_agent_has_only_read_public_in_the_default_policy(self) -> None:
        policy = PermissionPolicy.default()
        agent = Principal("subject:agent-1", frozenset({Role.AGENT}))
        self.assertTrue(policy.allows(agent, Permission.READ_PUBLIC))
        for permission in Permission:
            if permission is Permission.READ_PUBLIC:
                continue
            with self.subTest(permission=permission):
                self.assertFalse(policy.allows(agent, permission))

    def test_agent_cannot_approve_any_subject_kind(self) -> None:
        agent = Principal("subject:agent-1", frozenset({Role.AGENT}))
        for kind in ApprovalSubjectKind:
            with self.subTest(kind=kind):
                with self.assertRaises(ApprovalDenied):
                    service().record_review(
                        subject=subject(kind=kind),
                        validation_evidence_id="validation:0001",
                        validation_evidence_hash=EVIDENCE_HASH,
                        scientific_gate_passed=True,
                        review_id=f"review:agent:{kind.value}",
                        scope=ApprovalScope.RESEARCH_BACKTEST,
                        decision=ApprovalDecision.APPROVED,
                        principal=agent,
                        decided_at=DECIDED_AT,
                        reason="agent approval attempt",
                        evidence_hashes=(EVIDENCE_HASH,),
                        expires_at=None,
                        supersedes_review_id=None,
                    )

    def test_agent_with_a_human_role_attached_is_still_denied(self) -> None:
        """The realistic escalation path is a service account that accumulates a
        second role rather than a bare agent principal.  AGENT is a disqualifying
        role, not merely an insufficient one — otherwise the union of roles in
        PermissionPolicy.allows() (any(...) over roles) would grant the human
        permission and let the agent through.
        """
        hybrid = Principal(
            "subject:agent-2", frozenset({Role.AGENT, Role.REVIEWER})
        )
        self.assertTrue(
            PermissionPolicy.default().allows(hybrid, Permission.APPROVE_RESEARCH),
            "the permission matrix grants this via REVIEWER; the service must not",
        )
        with self.assertRaises(ApprovalDenied):
            service().record_review(
                subject=subject(),
                validation_evidence_id="validation:0001",
                validation_evidence_hash=EVIDENCE_HASH,
                scientific_gate_passed=True,
                review_id="review:hybrid",
                scope=ApprovalScope.RESEARCH_BACKTEST,
                decision=ApprovalDecision.APPROVED,
                principal=hybrid,
                decided_at=DECIDED_AT,
                reason="hybrid principal approval attempt",
                evidence_hashes=(EVIDENCE_HASH,),
                expires_at=None,
                supersedes_review_id=None,
            )

    def test_the_review_never_grants_order_or_account_authority(self) -> None:
        """Mirrors the two properties FactorPromotionReview already declares."""
        review = service().record_review(
            subject=subject(),
            validation_evidence_id="validation:0001",
            validation_evidence_hash=EVIDENCE_HASH,
            scientific_gate_passed=True,
            review_id="review:0010",
            scope=ApprovalScope.RESEARCH_BACKTEST,
            decision=ApprovalDecision.APPROVED,
            principal=reviewer(),
            decided_at=DECIDED_AT,
            reason="evidence complete",
            evidence_hashes=(EVIDENCE_HASH,),
            expires_at=None,
            supersedes_review_id=None,
        )
        self.assertFalse(review.grants_order_authority)
        self.assertFalse(review.grants_account_access)
```

- [ ] **Step 3: 运行确认红测**

Run:
```bash
cd platform && PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_approval_segregation_of_duties -v
```
Expected: FAIL —— `ModuleNotFoundError: No module named
'a_share_platform.application.approval_service'`。抄真实错误进 Evidence。

- [ ] **Step 4: 最小实现 —— 只做 SoD 与 Agent denial → 转绿**

服务层的授权检查**保持 `FactorReviewService` 的 AND 结构**（角色集合 ∩ 权限矩阵），
并加两条前置：

```python
if Role.AGENT in principal.roles:
    # A disqualifying role, not an insufficient one.  PermissionPolicy.allows()
    # unions over roles, so a hybrid principal would otherwise pass.
    raise ApprovalDenied(...)
required_roles = SUBJECT_ROLES[subject.kind]
required_permission = SUBJECT_PERMISSION[subject.kind]
if not principal.roles.intersection(required_roles) or not self._policy.allows(
    principal, required_permission
):
    raise ApprovalDenied(...)
if principal.subject_id == subject.submitted_by:
    self._record_denial(...)          # 先记账，再抛
    raise SegregationOfDutiesViolation(...)
```

- [ ] **Step 5: 四类 subject 的权限映射（红测先行）**

```python
# platform/tests/test_approval_generalisation.py
"""Four approval domains mapped onto the eight-permission matrix that already exists.

No new Permission enum value and no change to PermissionPolicy.default().  Adding
APPROVE_TIMING and APPROVE_RISK would create two sources of truth for 'what may a
Reviewer approve' — the enum and the service rule — and two sources of truth
diverge.

The mapping is not an invention either.  The matrix already says REVIEWER holds
APPROVE_RESEARCH and not APPROVE_PORTFOLIO, and PORTFOLIO_MANAGER the reverse.
Alpha, Timing and View are research-side; Risk and Portfolio are portfolio-side.
This task only makes that explicit and testable.
"""

from __future__ import annotations

import itertools
import unittest
from datetime import UTC, datetime, timedelta

from a_share_platform.application.approval_service import (
    ApprovalDenied,
    InvalidApprovalReview,
)
from a_share_platform.application.permissions import Permission, PermissionPolicy, Role
from a_share_platform.domain.approvals import (
    ApprovalReview,
    ApprovalSubject,
    ApprovalSubjectKind,
)
from a_share_platform.domain.factor_lifecycle import ApprovalDecision, ApprovalScope

# The subject / service / reviewer / portfolio_manager / administrator builders and
# the two hash constants come from the SoD test module.  One definition of an
# ApprovalSubject in the suite, not two that can drift apart.
from tests.test_approval_segregation_of_duties import (  # noqa: E402
    DECIDED_AT,
    EVIDENCE_HASH,
    SUBJECT_HASH,
    SUBMITTED_AT,
    administrator,
    portfolio_manager,
    reviewer,
    service,
    subject,
)

_REVIEW_IDS = itertools.count(1)


def _record(instance, **overrides):
    """Call record_review with a complete, valid argument set.

    Every test in this file varies one or two arguments.  Spelling out the other
    eleven each time would bury the argument under test, and defaulting them
    inside the service would hide a missing-field bug behind a fixture.
    """
    arguments = {
        "subject": subject(),
        "validation_evidence_id": "validation:0001",
        "validation_evidence_hash": EVIDENCE_HASH,
        "scientific_gate_passed": True,
        "review_id": f"review:{next(_REVIEW_IDS):04d}",
        "scope": ApprovalScope.RESEARCH_BACKTEST,
        "decision": ApprovalDecision.APPROVED,
        "principal": reviewer(),
        "decided_at": DECIDED_AT,
        "reason": "evidence complete; cross-check attached",
        "evidence_hashes": (EVIDENCE_HASH,),
        "expires_at": None,
        "supersedes_review_id": None,
    }
    arguments.update(overrides)
    return instance.record_review(**arguments)


def _subject_with_unmet_precondition(*, reason: str) -> ApprovalSubject:
    return ApprovalSubject(
        kind=ApprovalSubjectKind.FACTOR,
        subject_id="factor:quality.roe",
        subject_version="v3",
        subject_hash=SUBJECT_HASH,
        submitted_by="subject:researcher-1",
        submitted_at=SUBMITTED_AT,
        precondition_satisfied=False,
        precondition_reason=reason,
    )


def _approved_review(
    *,
    review_id: str = "review:0001",
    scope: ApprovalScope = ApprovalScope.RESEARCH_BACKTEST,
    expires_at: datetime | None = None,
    supersedes_review_id: str | None = None,
) -> ApprovalReview:
    return _review(
        review_id=review_id,
        scope=scope,
        decision=ApprovalDecision.APPROVED,
        expires_at=expires_at,
        supersedes_review_id=supersedes_review_id,
    )


def _review(
    *,
    review_id: str = "review:0001",
    scope: ApprovalScope = ApprovalScope.RESEARCH_BACKTEST,
    decision: ApprovalDecision = ApprovalDecision.APPROVED,
    expires_at: datetime | None = None,
    supersedes_review_id: str | None = None,
) -> ApprovalReview:
    """Construct the domain value directly, bypassing the service.

    The authorizes() tests are about the value object's own judgement, so they
    must be able to build a review the service would have refused to record.
    """
    return ApprovalReview(
        review_id=review_id,
        subject=subject(),
        validation_evidence_id="validation:0001",
        validation_evidence_hash=EVIDENCE_HASH,
        scientific_gate_passed=True,
        scope=scope,
        decision=decision,
        actor_id="subject:reviewer-1",
        actor_role="reviewer",
        decided_at=DECIDED_AT,
        reason="evidence complete; cross-check attached",
        evidence_hashes=(EVIDENCE_HASH,),
        expires_at=expires_at,
        supersedes_review_id=supersedes_review_id,
    )


def subject_at_version(version: str) -> ApprovalSubject:
    return ApprovalSubject(
        kind=ApprovalSubjectKind.ALPHA_MODEL,
        subject_id="alpha-model:composite",
        subject_version=version,
        subject_hash=SUBJECT_HASH,
        submitted_by="subject:researcher-1",
        submitted_at=SUBMITTED_AT,
        precondition_satisfied=True,
        precondition_reason=None,
    )


def subject_with_hash(subject_hash: str) -> ApprovalSubject:
    return ApprovalSubject(
        kind=ApprovalSubjectKind.ALPHA_MODEL,
        subject_id="alpha-model:composite",
        subject_version="v2",
        subject_hash=subject_hash,
        submitted_by="subject:researcher-1",
        submitted_at=SUBMITTED_AT,
        precondition_satisfied=True,
        precondition_reason=None,
    )


class PermissionMappingTest(unittest.TestCase):
    def test_reviewer_may_approve_factor_alpha_view_and_timing(self) -> None:
        for kind in (
            ApprovalSubjectKind.FACTOR,
            ApprovalSubjectKind.ALPHA_MODEL,
            ApprovalSubjectKind.INVESTMENT_VIEW,
            ApprovalSubjectKind.TIMING_MODEL,
        ):
            with self.subTest(kind=kind):
                review = _record(
                    service(), subject=subject(kind=kind), principal=reviewer()
                )
                self.assertEqual(review.decision, ApprovalDecision.APPROVED)

    def test_reviewer_may_not_approve_risk_or_portfolio(self) -> None:
        """PermissionPolicy.default() does not grant REVIEWER
        APPROVE_PORTFOLIO.  The service must respect that rather than treating
        'approver' as one undifferentiated role."""
        for kind in (
            ApprovalSubjectKind.RISK_MODEL,
            ApprovalSubjectKind.PORTFOLIO_POLICY,
        ):
            with self.subTest(kind=kind):
                with self.assertRaises(ApprovalDenied):
                    _record(
                        service(), subject=subject(kind=kind), principal=reviewer()
                    )

    def test_portfolio_manager_may_approve_risk_and_portfolio_only(self) -> None:
        for kind in (
            ApprovalSubjectKind.RISK_MODEL,
            ApprovalSubjectKind.PORTFOLIO_POLICY,
        ):
            with self.subTest(kind=kind, allowed=True):
                review = _record(
                    service(),
                    subject=subject(kind=kind),
                    principal=portfolio_manager(),
                )
                self.assertEqual(review.decision, ApprovalDecision.APPROVED)
        for kind in (
            ApprovalSubjectKind.FACTOR,
            ApprovalSubjectKind.ALPHA_MODEL,
            ApprovalSubjectKind.INVESTMENT_VIEW,
            ApprovalSubjectKind.TIMING_MODEL,
        ):
            with self.subTest(kind=kind, allowed=False):
                with self.assertRaises(ApprovalDenied):
                    _record(
                        service(),
                        subject=subject(kind=kind),
                        principal=portfolio_manager(),
                    )

    def test_no_new_permission_enum_value_was_added(self) -> None:
        """Locks the design decision in place.  A future APPROVE_TIMING would make
        the mapping in this module and the enum two answers to one question."""
        self.assertEqual(
            {item.value for item in Permission},
            {"read_public", "read_artifact", "create_experiment", "manage_data",
             "approve_research", "approve_portfolio", "send_order", "administer"},
        )

    def test_the_default_policy_grants_are_unchanged(self) -> None:
        """Asserted against the literal matrix, so any edit to default() surfaces
        here rather than as a silently widened approval path."""
        grants = PermissionPolicy.default().grants
        self.assertEqual(grants[Role.VIEWER], frozenset({Permission.READ_PUBLIC}))
        self.assertEqual(
            grants[Role.REVIEWER],
            frozenset({Permission.READ_PUBLIC, Permission.READ_ARTIFACT,
                       Permission.APPROVE_RESEARCH}),
        )
        self.assertEqual(
            grants[Role.PORTFOLIO_MANAGER],
            frozenset({Permission.READ_PUBLIC, Permission.READ_ARTIFACT,
                       Permission.APPROVE_PORTFOLIO}),
        )
        self.assertEqual(grants[Role.AGENT], frozenset({Permission.READ_PUBLIC}))
        self.assertEqual(grants[Role.ADMINISTRATOR], frozenset(Permission))


class SubjectPreconditionTest(unittest.TestCase):
    def test_the_precondition_is_declared_by_the_subject_not_checked_centrally(
        self,
    ) -> None:
        """FactorPromotionReview hard-requires factor_lifecycle_status is
        CANDIDATE.  That is right for a factor — SPEC-023 makes candidate-to-
        production the only promotion edge — and meaningless for a PortfolioPolicy,
        which has no lifecycle enum at all.  A central check would therefore be
        wrong for three of the six subject kinds.
        """
        import inspect

        from a_share_platform.application import approval_service
        from a_share_platform.domain import approvals

        # The precondition is a field on the subject, not a lifecycle check in the
        # generic contract or the service.
        self.assertIn("precondition_satisfied", ApprovalSubject.__annotations__)
        for module in (approvals, approval_service):
            with self.subTest(module=module.__name__):
                source = inspect.getsource(module)
                self.assertNotIn("FactorLifecycleStatus", source)
                self.assertNotIn("CANDIDATE", source)
        # A PortfolioPolicy with no lifecycle enum still approves cleanly.
        review = _record(
            service(),
            subject=subject(kind=ApprovalSubjectKind.PORTFOLIO_POLICY),
            principal=portfolio_manager(),
        )
        self.assertEqual(review.decision, ApprovalDecision.APPROVED)

    def test_an_unsatisfied_precondition_blocks_approval_with_its_own_reason(
        self,
    ) -> None:
        with self.assertRaises(InvalidApprovalReview) as caught:
            _record(
                service(),
                subject=_subject_with_unmet_precondition(
                    reason="factor lifecycle is research, not candidate"
                ),
                decision=ApprovalDecision.APPROVED,
            )
        self.assertIn("not candidate", str(caught.exception))

    def test_an_unsatisfied_precondition_requires_a_reason(self) -> None:
        with self.assertRaises(ValueError):
            _subject_with_unmet_precondition(reason="   ")

    def test_request_changes_is_allowed_despite_an_unmet_precondition(self) -> None:
        """Blocking request_changes would leave the submitter with no feedback
        path and force the reviewer to either approve or stay silent."""
        review = _record(
            service(),
            subject=_subject_with_unmet_precondition(
                reason="factor lifecycle is research, not candidate"
            ),
            decision=ApprovalDecision.REQUEST_CHANGES,
            reason="promote to candidate first, then resubmit",
        )
        self.assertEqual(review.decision, ApprovalDecision.REQUEST_CHANGES)
        self.assertFalse(
            review.authorizes(
                subject=review.subject,
                scope=ApprovalScope.RESEARCH_BACKTEST,
                at=DECIDED_AT,
            )
        )

    def test_approval_cannot_override_a_failed_scientific_gate(self) -> None:
        """Carried over verbatim from FactorPromotionReview:
        'approval cannot override a failed scientific gate'.  It is the single most
        important rule in the whole approval contract and it must not be lost in
        the generalisation.
        """
        with self.assertRaises(InvalidApprovalReview):
            _record(
                service(),
                subject=subject(),
                scientific_gate_passed=False,
                decision=ApprovalDecision.APPROVED,
            )


class ScopeIsolationTest(unittest.TestCase):
    def test_the_four_scopes_do_not_imply_one_another(self) -> None:
        """SPEC-023 逐字：获准研究回测不等于获准模拟盘或实盘."""
        review = _approved_review(scope=ApprovalScope.RESEARCH_BACKTEST)
        self.assertTrue(review.authorizes(
            subject=subject(), scope=ApprovalScope.RESEARCH_BACKTEST, at=DECIDED_AT))
        for scope in (ApprovalScope.SHADOW, ApprovalScope.PAPER,
                      ApprovalScope.LIMITED_LIVE):
            with self.subTest(scope=scope):
                self.assertFalse(review.authorizes(
                    subject=subject(), scope=scope, at=DECIDED_AT))

    def test_a_scope_cannot_be_widened_by_a_request_parameter(self) -> None:
        """Mirrors the fixed_read_context guard already in api/app.py, which
        raises RunContextOverrideDenied on a data_mode query parameter."""
        review = _record(service(), scope=ApprovalScope.RESEARCH_BACKTEST)
        self.assertIs(review.scope, ApprovalScope.RESEARCH_BACKTEST)
        # authorizes() takes the requested scope as an argument and compares it;
        # it never falls back to "the widest scope this review could imply".
        for scope in (ApprovalScope.SHADOW, ApprovalScope.PAPER):
            with self.subTest(scope=scope):
                self.assertFalse(
                    review.authorizes(
                        subject=review.subject, scope=scope, at=DECIDED_AT
                    )
                )
        with self.assertRaises(ValueError):
            review.authorizes(
                subject=review.subject, scope="research_backtest_or_shadow",
                at=DECIDED_AT,
            )

    def test_limited_live_scope_requires_an_explicit_authorisation_record(self) -> None:
        """AGENTS.md: P11 需新的明确授权.  No such record exists, so a
        limited_live approval is refused outright rather than merely unused."""
        with self.assertRaises(InvalidApprovalReview):
            _record(
                service(),
                subject=subject(),
                scope=ApprovalScope.LIMITED_LIVE,
                decision=ApprovalDecision.APPROVED,
                principal=administrator(),
            )
```

- [ ] **Step 6: expiry 与 supersede（红测先行）**

```python
# platform/tests/test_approval_expiry_and_supersede.py
"""An expired approval does not authorise, and a superseded one does not either.

Neither concept exists in PromotionApproval.authorizes() today — it checks the
decision, the ids, the hashes, the scope and the promotion gate, and nothing about
time or replacement.  That is not an oversight in P4: expiry and supersede only
became requirements in Step 08's ApprovalReview contract, which lists
subject/version/use/stage/decision/evidence/reviewer/expiry/supersedes.

PromotionApproval.authorizes() is deliberately not changed.  Adding an expiry
check there would make every existing P4 review expire retroactively, which is
rewriting history rather than tightening a rule.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from a_share_platform.domain.approvals import ApprovalReview, ApprovalSubjectKind
from a_share_platform.domain.factor_lifecycle import ApprovalDecision, ApprovalScope

# _approved_review / _review / subject / subject_at_version / subject_with_hash are
# defined once in the generalisation test module; the ledger fixtures come from the
# in-memory adapter so "stays in the ledger" is asserted against a real repository.
from a_share_platform.adapters.memory.approvals import InMemoryApprovalRepository
from tests.test_approval_generalisation import (  # noqa: E402
    _approved_review,
    _review,
    subject,
    subject_at_version,
    subject_with_hash,
)

DECIDED_AT = datetime(2026, 8, 16, 3, 0, tzinfo=UTC)
EXPIRES_AT = DECIDED_AT + timedelta(days=90)


class ExpiryTest(unittest.TestCase):
    def test_an_approval_authorises_before_its_expiry(self) -> None:
        review = _approved_review(expires_at=EXPIRES_AT)
        self.assertTrue(review.authorizes(
            subject=subject(), scope=ApprovalScope.RESEARCH_BACKTEST,
            at=EXPIRES_AT - timedelta(days=1)))

    def test_an_expired_approval_does_not_authorise(self) -> None:
        """The load-bearing assertion.  Without it a 90-day approval silently
        becomes permanent, which is the same as having no expiry field while
        displaying one on the page."""
        review = _approved_review(expires_at=EXPIRES_AT)
        self.assertFalse(review.authorizes(
            subject=subject(), scope=ApprovalScope.RESEARCH_BACKTEST,
            at=EXPIRES_AT + timedelta(seconds=1)))

    def test_expiry_is_inclusive_of_its_own_instant(self) -> None:
        """Ambiguity at the boundary is how two components disagree about whether
        an approval is live, which is worse than either answer."""
        review = _approved_review(expires_at=EXPIRES_AT)
        self.assertTrue(review.authorizes(
            subject=subject(), scope=ApprovalScope.RESEARCH_BACKTEST, at=EXPIRES_AT))

    def test_an_approval_with_no_expiry_authorises_indefinitely(self) -> None:
        """Allowed, but it must be an explicit None rather than an omitted field,
        so a permanent approval is a decision someone made."""
        review = _approved_review(expires_at=None)
        self.assertIsNone(review.expires_at)
        self.assertTrue(review.authorizes(
            subject=subject(), scope=ApprovalScope.RESEARCH_BACKTEST,
            at=DECIDED_AT + timedelta(days=3650)))
        with self.assertRaises(TypeError):
            ApprovalReview(  # type: ignore[call-arg]
                review_id="review:0099",
                subject=subject(),
                validation_evidence_id="validation:0001",
                validation_evidence_hash="a" * 64,
                scientific_gate_passed=True,
                scope=ApprovalScope.RESEARCH_BACKTEST,
                decision=ApprovalDecision.APPROVED,
                actor_id="subject:reviewer-1",
                actor_role="reviewer",
                decided_at=DECIDED_AT,
                reason="omitted expiry",
                evidence_hashes=("a" * 64,),
                supersedes_review_id=None,
            )

    def test_an_expiry_before_the_decision_time_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            _approved_review(expires_at=DECIDED_AT - timedelta(days=1))

    def test_a_naive_expiry_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            _approved_review(expires_at=datetime(2026, 11, 14, 3, 0))

    def test_an_expired_approval_is_not_deleted(self) -> None:
        """It stays in the ledger as the record of a decision that was once live.
        Deleting expired approvals would make the audit trail depend on when it is
        read."""
        repository = InMemoryApprovalRepository()
        review = _approved_review(expires_at=EXPIRES_AT)
        repository.append(review)
        after_expiry = EXPIRES_AT + timedelta(days=1)
        self.assertEqual(repository.list_reviews(), (review,))
        self.assertEqual(repository.get_review(review.review_id), review)
        self.assertFalse(review.authorizes(
            subject=subject(), scope=ApprovalScope.RESEARCH_BACKTEST, at=after_expiry))


class SupersedeTest(unittest.TestCase):
    def test_a_superseded_approval_does_not_authorise(self) -> None:
        """The second load-bearing assertion.  Two live approvals for the same
        subject and scope is an ambiguous authorisation, and ambiguity resolves in
        whichever direction the reader's loop happens to iterate."""
        old = _approved_review(review_id="review:0001")
        self.assertFalse(old.authorizes(
            subject=subject(), scope=ApprovalScope.RESEARCH_BACKTEST,
            at=DECIDED_AT, superseded_by=("review:0002",)))

    def test_the_superseding_approval_authorises(self) -> None:
        new = _approved_review(review_id="review:0002",
                               supersedes_review_id="review:0001")
        self.assertTrue(new.authorizes(
            subject=subject(), scope=ApprovalScope.RESEARCH_BACKTEST, at=DECIDED_AT))

    def test_a_review_cannot_supersede_itself(self) -> None:
        with self.assertRaises(ValueError):
            _approved_review(review_id="review:0001",
                             supersedes_review_id="review:0001")

    def test_superseding_a_review_for_a_different_subject_is_refused(self) -> None:
        """Otherwise a Timing approval could supersede a Risk approval and quietly
        withdraw an authorisation in an unrelated domain."""
        repository = InMemoryApprovalRepository()
        timing = _approved_review(review_id="review:0001")
        repository.append(timing)
        risk = _review(review_id="review:0002", supersedes_review_id="review:0001")
        with self.assertRaises(ValueError):
            repository.assert_supersede_targets_same_subject(
                risk, subject_kind=ApprovalSubjectKind.RISK_MODEL
            )

    def test_a_superseded_review_stays_in_the_ledger(self) -> None:
        """append-only.  The chain old-to-new is the audit answer to 'why did this
        change', and deleting the old link erases the question."""
        repository = InMemoryApprovalRepository()
        old = _approved_review(review_id="review:0001")
        new = _approved_review(review_id="review:0002",
                               supersedes_review_id="review:0001")
        repository.append(old)
        repository.append(new)
        self.assertEqual(
            tuple(item.review_id for item in repository.list_reviews()),
            ("review:0001", "review:0002"),
        )
        self.assertEqual(
            repository.get_review("review:0002").supersedes_review_id, "review:0001"
        )

    def test_a_supersede_chain_of_three_leaves_only_the_last_authorising(self) -> None:
        first = _approved_review(review_id="review:0001")
        second = _approved_review(review_id="review:0002",
                                  supersedes_review_id="review:0001")
        third = _approved_review(review_id="review:0003",
                                 supersedes_review_id="review:0002")
        superseded = ("review:0001", "review:0002")
        for review in (first, second):
            with self.subTest(review_id=review.review_id):
                self.assertFalse(review.authorizes(
                    subject=subject(), scope=ApprovalScope.RESEARCH_BACKTEST,
                    at=DECIDED_AT, superseded_by=superseded))
        self.assertTrue(third.authorizes(
            subject=subject(), scope=ApprovalScope.RESEARCH_BACKTEST,
            at=DECIDED_AT, superseded_by=superseded))

    def test_a_rejected_review_cannot_supersede_an_approved_one_silently(self) -> None:
        """A rejection that withdraws a live approval is a withdrawal and must be
        recorded as one, with the downstream serving registration ended.  Asserted
        end-to-end in test_serving_registry.py."""
        withdrawal = _review(review_id="review:0002",
                             decision=ApprovalDecision.REJECTED,
                             supersedes_review_id="review:0001")
        # The rejection itself never authorises, so the subject is left with no
        # live authorisation rather than with the old one.
        self.assertFalse(withdrawal.authorizes(
            subject=subject(), scope=ApprovalScope.RESEARCH_BACKTEST, at=DECIDED_AT))
        old = _approved_review(review_id="review:0001")
        self.assertFalse(old.authorizes(
            subject=subject(), scope=ApprovalScope.RESEARCH_BACKTEST,
            at=DECIDED_AT, superseded_by=("review:0002",)))
        self.assertTrue(withdrawal.withdraws_authorisation)


class VersionExactnessTest(unittest.TestCase):
    def test_an_approval_for_v2_does_not_authorise_v3(self) -> None:
        """SPEC-041: 生产版本不可原地修改.  Figma node 9:883 says the same thing in
        its rules card: 版本不可变 / 修改产生新版本与新审查."""
        review = _approved_review()
        self.assertFalse(review.authorizes(
            subject=subject_at_version("v3"),
            scope=ApprovalScope.RESEARCH_BACKTEST, at=DECIDED_AT))

    def test_an_approval_does_not_authorise_a_changed_subject_hash(self) -> None:
        """Same version string, different content.  This is the case a version
        check alone misses, and it is the one that matters: an edited definition
        keeping its version number is exactly what the immutability rule forbids.
        """
        review = _approved_review()
        self.assertFalse(review.authorizes(
            subject=subject_with_hash("c" * 64),
            scope=ApprovalScope.RESEARCH_BACKTEST, at=DECIDED_AT))

    def test_a_rejected_review_never_authorises(self) -> None:
        review = _review(decision=ApprovalDecision.REJECTED)
        self.assertFalse(review.authorizes(
            subject=subject(), scope=ApprovalScope.RESEARCH_BACKTEST, at=DECIDED_AT))

    def test_request_changes_never_authorises(self) -> None:
        review = _review(decision=ApprovalDecision.REQUEST_CHANGES)
        self.assertFalse(review.authorizes(
            subject=subject(), scope=ApprovalScope.RESEARCH_BACKTEST, at=DECIDED_AT))
```

- [ ] **Step 7: 运行 → 实现 → 转绿**

- [ ] **Step 8: `ServingRegistration` 与 rollback（红测先行）**

```python
# platform/tests/test_serving_registry.py
"""Serving registration: the only path from an approval to runtime behaviour.

Step 08 Spec: ServingRegistration carries approved exact version / scope /
effective interval / rollback target.  The rollback target is what makes
AlertAction.EXECUTE_APPROVED_ROLLBACK safe: it executes a decision someone already
approved, rather than a judgement the monitoring system formed on its own.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from a_share_platform.adapters.memory.approvals import (
    InMemoryApprovalRepository,
    InMemoryServingRepository,
)
from a_share_platform.application.serving_registry import (
    InvalidServingRegistration,
    ServingRegistry,
)
from a_share_platform.domain.factor_lifecycle import ApprovalDecision, ApprovalScope
from a_share_platform.domain.incidents import AlertAction

from tests.test_approval_generalisation import (  # noqa: E402
    DECIDED_AT,
    _approved_review,
    _review,
    administrator,
    portfolio_manager,
    reviewer,
)

EFFECTIVE_FROM = DECIDED_AT + timedelta(hours=1)
EXPIRES_AT = DECIDED_AT + timedelta(days=90)


def _registry(*reviews) -> ServingRegistry:
    approvals = InMemoryApprovalRepository()
    for review in reviews:
        approvals.append(review)
    return ServingRegistry(
        approvals=approvals,
        registrations=InMemoryServingRepository(),
    )


def _register(registry, *, review, scope=None, effective_from=EFFECTIVE_FROM,
              registration_id="registration:0001", principal=None,
              rollback_target_registration_id=None):
    return registry.register(
        registration_id=registration_id,
        subject=review.subject,
        review_id=review.review_id,
        scope=scope or review.scope,
        effective_from=effective_from,
        effective_until=None,
        rollback_target_registration_id=rollback_target_registration_id,
        principal=principal or reviewer(),
    )


class RegistrationTest(unittest.TestCase):
    def test_registration_requires_an_authorising_review(self) -> None:
        approved = _approved_review(review_id="review:0001")
        registration = _register(_registry(approved), review=approved)
        self.assertEqual(registration.review_id, "review:0001")
        self.assertIs(registration.scope, ApprovalScope.RESEARCH_BACKTEST)
        rejected = _review(review_id="review:0002",
                           decision=ApprovalDecision.REJECTED)
        with self.assertRaises(InvalidServingRegistration):
            _register(_registry(rejected), review=rejected,
                      registration_id="registration:0002")

    def test_registration_refuses_an_expired_review(self) -> None:
        expired = _approved_review(review_id="review:0001", expires_at=EXPIRES_AT)
        with self.assertRaises(InvalidServingRegistration):
            _register(
                _registry(expired),
                review=expired,
                effective_from=EXPIRES_AT + timedelta(seconds=1),
            )

    def test_registration_refuses_a_superseded_review(self) -> None:
        old = _approved_review(review_id="review:0001")
        new = _approved_review(review_id="review:0002",
                               supersedes_review_id="review:0001")
        registry = _registry(old, new)
        with self.assertRaises(InvalidServingRegistration):
            _register(registry, review=old)
        self.assertEqual(
            _register(registry, review=new,
                      registration_id="registration:0002").review_id,
            "review:0002",
        )

    def test_registration_scope_must_equal_the_review_scope(self) -> None:
        """A research_backtest approval registered for shadow serving is scope
        escalation with extra steps."""
        approved = _approved_review(review_id="review:0001",
                                    scope=ApprovalScope.RESEARCH_BACKTEST)
        with self.assertRaises(InvalidServingRegistration):
            _register(_registry(approved), review=approved,
                      scope=ApprovalScope.SHADOW)

    def test_two_overlapping_registrations_for_one_scope_are_refused(self) -> None:
        """Which version is serving must have exactly one answer at any instant."""
        approved = _approved_review(review_id="review:0001")
        registry = _registry(approved)
        _register(registry, review=approved, registration_id="registration:0001")
        with self.assertRaises(InvalidServingRegistration):
            _register(
                registry,
                review=approved,
                registration_id="registration:0002",
                effective_from=EFFECTIVE_FROM + timedelta(hours=1),
            )

    def test_a_registration_can_be_ended_but_not_edited(self) -> None:
        """SPEC-041: 生产版本不可原地修改，只能产生新版本或回滚."""
        approved = _approved_review(review_id="review:0001")
        registry = _registry(approved)
        registration = _register(registry, review=approved)
        ended = registry.end(
            registration_id=registration.registration_id,
            effective_until=EFFECTIVE_FROM + timedelta(days=1),
            principal=reviewer(),
            reason="superseded by v3",
        )
        self.assertEqual(ended.effective_until, EFFECTIVE_FROM + timedelta(days=1))
        self.assertIsNone(registration.effective_until)
        self.assertNotEqual(ended.content_hash, registration.content_hash)
        self.assertEqual(len(registry.list_registrations()), 2)
        with self.assertRaises(AttributeError):
            registration.scope = ApprovalScope.SHADOW  # frozen


class RollbackTest(unittest.TestCase):
    def test_a_rollback_target_must_itself_be_an_approved_registration(self) -> None:
        """Rolling back to something unapproved is a promotion wearing the word
        rollback."""
        approved = _approved_review(review_id="review:0001")
        registry = _registry(approved)
        with self.assertRaises(InvalidServingRegistration):
            registry.execute_rollback(
                registration_id="registration:0002",
                rollback_target_registration_id="registration:does-not-exist",
                occurred_at=EFFECTIVE_FROM + timedelta(hours=2),
                principal=reviewer(),
                reason="ic decay beyond the major threshold",
            )

    def test_a_drift_alert_can_execute_an_approved_rollback(self) -> None:
        """The one action that changes runtime behaviour, and it changes it to a
        state a human already approved."""
        v2 = _approved_review(review_id="review:0001")
        registry = _registry(v2)
        previous = _register(registry, review=v2, registration_id="registration:0001")
        rolled_back = registry.execute_rollback(
            registration_id="registration:0002",
            rollback_target_registration_id=previous.registration_id,
            occurred_at=EFFECTIVE_FROM + timedelta(hours=2),
            principal=reviewer(),
            reason="ic decay beyond the major threshold",
            action=AlertAction.EXECUTE_APPROVED_ROLLBACK,
        )
        self.assertEqual(
            rolled_back.rollback_target_registration_id, previous.registration_id
        )
        self.assertEqual(rolled_back.review_id, previous.review_id)

    def test_a_drift_alert_cannot_register_a_new_version(self) -> None:
        """This is the difference between monitoring and self-modification."""
        approved = _approved_review(review_id="review:0001")
        registry = _registry(approved)
        for action in (AlertAction.BLOCK_DOWNSTREAM, AlertAction.REQUEST_REVIEW,
                       AlertAction.EXECUTE_APPROVED_ROLLBACK):
            with self.subTest(action=action):
                with self.assertRaises(PermissionError):
                    registry.register(
                        registration_id=f"registration:{action.value}",
                        subject=approved.subject,
                        review_id=approved.review_id,
                        scope=approved.scope,
                        effective_from=EFFECTIVE_FROM,
                        effective_until=None,
                        rollback_target_registration_id=None,
                        principal=reviewer(),
                        alert_action=action,
                    )

    def test_a_rollback_leaves_both_registrations_in_the_ledger(self) -> None:
        """SPEC-041: rollback 有审计和可重放 Artifact."""
        approved = _approved_review(review_id="review:0001")
        registry = _registry(approved)
        previous = _register(registry, review=approved)
        registry.execute_rollback(
            registration_id="registration:0002",
            rollback_target_registration_id=previous.registration_id,
            occurred_at=EFFECTIVE_FROM + timedelta(hours=2),
            principal=reviewer(),
            reason="ic decay beyond the major threshold",
        )
        ids = tuple(item.registration_id for item in registry.list_registrations())
        self.assertIn("registration:0001", ids)
        self.assertIn("registration:0002", ids)

    def test_a_rollback_to_a_retired_registration_is_refused(self) -> None:
        approved = _approved_review(review_id="review:0001")
        registry = _registry(approved)
        previous = _register(registry, review=approved)
        registry.retire(
            registration_id=previous.registration_id,
            occurred_at=EFFECTIVE_FROM + timedelta(hours=1),
            principal=administrator(),
            reason="definition withdrawn",
        )
        with self.assertRaises(InvalidServingRegistration):
            registry.execute_rollback(
                registration_id="registration:0002",
                rollback_target_registration_id=previous.registration_id,
                occurred_at=EFFECTIVE_FROM + timedelta(hours=2),
                principal=reviewer(),
                reason="ic decay beyond the major threshold",
            )

    def test_suspend_and_retire_are_audited_transitions_not_deletions(self) -> None:
        """Step 08 Task 4 lists rollback alongside suspend and retire.  A deleted
        registration makes 'what was serving on 2026-08-10' unanswerable."""
        approved = _approved_review(review_id="review:0001")
        registry = _registry(approved)
        registration = _register(registry, review=approved)
        suspended = registry.suspend(
            registration_id=registration.registration_id,
            occurred_at=EFFECTIVE_FROM + timedelta(hours=1),
            principal=portfolio_manager(),
            reason="exposure breach pending review",
        )
        retired = registry.retire(
            registration_id=registration.registration_id,
            occurred_at=EFFECTIVE_FROM + timedelta(hours=2),
            principal=administrator(),
            reason="definition withdrawn",
        )
        self.assertEqual(
            registry.registration_serving_at(EFFECTIVE_FROM).registration_id,
            registration.registration_id,
        )
        for event in (suspended, retired):
            with self.subTest(event=event.transition_id):
                self.assertTrue(event.reason.strip())
                self.assertIsNotNone(event.actor_id)
        self.assertIsNotNone(registry.get_registration(registration.registration_id))
        with self.assertRaises(AttributeError):
            registry.delete  # no deletion path exists at all
```

- [ ] **Step 9: Desk `_pending_tasks()` 接通用审批队列（红测先行）**

```python
# 扩展 platform/tests/test_desk_projection.py
from datetime import timedelta

from a_share_platform.adapters.memory.approvals import InMemoryApprovalRepository
from a_share_platform.adapters.memory.factor_reviews import (
    InMemoryFactorReviewRepository,
)
from a_share_platform.domain.approvals import ApprovalSubjectKind
from a_share_platform.domain.desk import DeskSectionKey


def _pending_subjects(*, count: int) -> tuple[object, ...]:
    """`count` submitted-but-undecided subjects, cycling the six subject kinds."""
    from tests.test_approval_generalisation import subject

    kinds = tuple(ApprovalSubjectKind)
    return tuple(
        subject(kind=kinds[index % len(kinds)]) for index in range(count)
    )


def _factor_reviews(*, count: int) -> tuple[object, ...]:
    """`count` P4-era FactorPromotionReview records, unchanged by this plan.

    Built through FactorPromotionReview.from_evidence with the existing
    tests/test_factor_lifecycle.py fixtures, so the desk merges genuine P4 objects
    rather than a lookalike shaped for this test.
    """
    from a_share_platform.domain.factor_lifecycle import (
        ApprovalDecision,
        ApprovalScope,
        PromotionApproval,
    )
    from a_share_platform.domain.factor_reviews import FactorPromotionReview
    from tests.test_factor_lifecycle import NOW, candidate, digest, report

    version = candidate()
    validation = report()
    return tuple(
        FactorPromotionReview.from_evidence(
            factor_version=version,
            validation_report=validation,
            approval=PromotionApproval(
                approval_id=f"approval:factor:{index}",
                factor_version_id=version.factor_version_id,
                validation_report_id=validation.report_id,
                validation_report_hash=validation.content_hash,
                scope=ApprovalScope.RESEARCH_BACKTEST,
                decision=ApprovalDecision.APPROVED,
                actor_id="user:reviewer-01",
                actor_role="reviewer",
                decided_at=NOW + timedelta(minutes=5 + index),
                reason="Reviewed the frozen evidence pack for this exact use.",
                evidence_hashes=(digest("c"),),
            ),
        )
        for index in range(count)
    )


def _desk_with_approvals(
    *,
    pending_general: int = 4,
    pending_factor_reviews: int = 2,
):
    """A desk fed by both ledgers: the new general queue and P4's factor reviews.

    Two ledgers is the point of this step — the plan does not migrate the factor
    path, so the section has to merge them without either one shadowing the other.
    """
    return DeskProjectionService(
        approvals=InMemoryApprovalRepository(
            pending=_pending_subjects(count=pending_general)
        ),
        factor_reviews=InMemoryFactorReviewRepository(
            reviews=_factor_reviews(count=pending_factor_reviews)
        ),
    )


class PendingApprovalQueueTest(unittest.TestCase):
    def test_the_p9_approval_queue_blocker_is_gone(self) -> None:
        """P9_GENERAL_APPROVAL_QUEUE_NOT_IMPLEMENTED is this task's acceptance
        anchor.  It disappears because a real queue exists across six subject
        kinds, not because the string was removed."""
        section = _desk_with_approvals().project(now=NOW).section(
            DeskSectionKey.PENDING_TASKS
        )
        codes = {blocker.code for blocker in section.blockers}
        self.assertNotIn("P9_GENERAL_APPROVAL_QUEUE_NOT_IMPLEMENTED", codes)

    def test_factor_reviews_still_appear_alongside_the_general_queue(self) -> None:
        """The existing FactorPromotionReview path is not migrated by this plan, so
        both ledgers feed the section.  Dropping the old one would make P4's
        evidence vanish from the desk."""
        section = _desk_with_approvals(
            pending_general=4, pending_factor_reviews=2
        ).project(now=NOW).section(DeskSectionKey.PENDING_TASKS)
        sources = {row["source"] for row in section.payload["rows"]}
        self.assertEqual(sources, {"approval_review", "factor_promotion_review"})
        self.assertEqual(section.coverage["pending_general"], 4)
        self.assertEqual(section.coverage["pending_factor_reviews"], 2)
        self.assertEqual(len(section.payload["rows"]), 6)

    def test_pending_counts_are_server_computed(self) -> None:
        """The frontend must not count; a client-side tally can disagree with the
        server about what is pending, and the page is the thing people act on."""
        section = _desk_with_approvals(
            pending_general=4, pending_factor_reviews=2
        ).project(now=NOW, limit=3).section(DeskSectionKey.PENDING_TASKS)
        # The page is truncated; the count is not.
        self.assertEqual(len(section.payload["rows"]), 3)
        self.assertEqual(section.payload["summary"]["pending_total"], 6)
        self.assertEqual(section.coverage["pending_total"], 6)
```

- [ ] **Step 10: 全量验证并提交（分两个 commit）**

审批泛化与 serving registry 是两个独立可验证行为。

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src

cd .. && git add platform/src/a_share_platform/domain/approvals.py \
  platform/src/a_share_platform/application/approval_service.py \
  platform/src/a_share_platform/ports/approvals.py \
  platform/src/a_share_platform/adapters/memory/approvals.py \
  platform/tests/test_approval_generalisation.py \
  platform/tests/test_approval_segregation_of_duties.py \
  platform/tests/test_approval_expiry_and_supersede.py
git commit -m "feat: generalise approval from factor-only to six subject kinds with real separation of duties

Separation of duties did not exist before this change.  FactorVersion carries
created_by, FactorReviewService never reads it, and a grep for submitted_by,
submitter or requested_by across src returned nothing at all.  So a Reviewer who
registered a FactorVersion could approve it in the next call and the resulting
review was indistinguishable from one a second person signed.  The prototype was
stricter than the implementation the whole time: Figma node 9:883 draws a 提交人
column beside a Reviewer column, User-1 submitting and Reviewer-2 approving.

Self-rejection is refused too.  It looks harmless, but a decision-dependent SoD
check is one conditional away from being bypassed by approving in two steps, and
the Administrator gets no exemption either — that role holds all eight permissions
including SEND_ORDER, so it is the one role where an exemption would matter most.
The refused attempt is written to the audit log before the exception is raised,
because a self-approval attempt is precisely the event an audit is looking for.

No new Permission enum value and no change to PermissionPolicy.default().  An
APPROVE_TIMING would create two answers to 'what may a Reviewer approve' — the
enum and the service mapping — and two answers diverge.  The mapping is not
invented either: the matrix already grants REVIEWER approve_research and not
approve_portfolio, with PORTFOLIO_MANAGER the reverse, so Alpha, Timing and View
land research-side while Risk and Portfolio land portfolio-side.  A test asserts
the literal grants so any edit to default() surfaces here rather than as a
silently widened approval path.

Role.AGENT is treated as disqualifying rather than merely insufficient.
PermissionPolicy.allows() unions over roles, so a service account that accumulated
a REVIEWER role alongside AGENT would otherwise pass — and that accumulation is
the realistic escalation path, not a bare agent principal.  A test asserts the
matrix does grant the hybrid the permission while the service still refuses.

Expiry and supersede are new here and are deliberately not backported into
PromotionApproval.authorizes().  Adding an expiry check there would expire every
existing P4 review retroactively, which is rewriting history rather than
tightening a rule.  An approval past its expiry does not authorise, and one that
has been superseded does not either: two live approvals for the same subject and
scope is an ambiguous authorisation, and ambiguity resolves in whichever direction
the reader's loop happens to iterate.  Both stay in the ledger; deleting them
would make the audit trail depend on when it is read.

Version exactness is checked on the hash and not only on the version string.  Same
version, different content is the case a version check misses, and an edited
definition keeping its number is exactly what SPEC-041 immutability forbids.

The subject declares its own precondition instead of the contract checking one
centrally.  FactorPromotionReview hard-requires candidate lifecycle status, which
is right for a factor and meaningless for a PortfolioPolicy that has no lifecycle
enum — a central check would be wrong for three of the six kinds.  What does carry
over verbatim is that an approval cannot override a failed scientific gate."

git add platform/src/a_share_platform/domain/serving.py \
  platform/src/a_share_platform/application/serving_registry.py \
  platform/src/a_share_platform/ports/serving.py \
  platform/src/a_share_platform/application/desk_projection.py \
  platform/tests/test_serving_registry.py \
  platform/tests/test_desk_projection.py
git commit -m "feat: add the serving registry as the only path from approval to runtime

The rollback target is what makes EXECUTE_APPROVED_ROLLBACK the one alert action
allowed to change runtime behaviour: it executes a decision a human already
approved rather than a judgement the monitoring system formed on its own.  A
rollback target that is not itself an approved registration would be a promotion
wearing the word rollback, so that is refused.

Two overlapping registrations for one scope are refused because 'which version is
serving' must have exactly one answer at any instant.  Registrations end rather
than being edited or deleted, since a deleted one makes 'what was serving on
2026-08-10' unanswerable — and answering that is the entire point of SPEC-041's
replayable audit.

The desk's pending-tasks blocker P9_GENERAL_APPROVAL_QUEUE_NOT_IMPLEMENTED is gone
because a real queue now spans six subject kinds.  The existing factor review
ledger keeps feeding the same section: this plan does not migrate that path, and
dropping it would make P4's evidence disappear from the desk."
```

---

### Task 5: API、cursor pagination、服务端聚合与 PUI-08 十一页

对应 Step 08 Task 5：「增加 cursor pagination 和服务端聚合；实现 Monitoring、Desk、
Correlation、Production、Users、Entitlements、Approvals 页面及六态。成熟 Desk、Monitoring、
Governance 和统一 Attribution 的页面交付按 PUI-08 执行；这里只能在对应 Capability/API 和
PUI 三轴证据分别满足后更新各自状态，不能用"31 页已画出"替代 P9 Gate。」

**cursor pagination 与服务端聚合是第一约束，不是性能优化。**

理由：Incident 与 DriftObservation 是 append-only 且高频（每次监控运行写十三个指标 ×
每个 subject）。offset 分页在这种表上有两个具体缺陷：第 N 页在插入发生后会**重复或跳过**行，
而 append-only 表随时在插入；`OFFSET 50000` 在 PostgreSQL 里是全扫描。
更重要的是——如果前端聚合，那么「有几个 open incident」就有两个答案，
而页面是人实际据以行动的东西。

**Files:**
- Modify: `platform/src/a_share_platform/api/app.py`（新增 11 个只读 + 3 个受控写）
- Modify: `platform/src/a_share_platform/api/schemas.py`
- Create: `platform/src/a_share_platform/application/monitoring_workspace.py`
- Create: `platform/src/a_share_platform/application/governance_workspace.py`
- Create: `platform/src/a_share_platform/adapters/postgres/monitoring.py`
- Create: `platform/src/a_share_platform/adapters/postgres/approvals.py`
- Create: `platform/migrations/0039_p9_unified_attribution.sql`
- Create: `platform/migrations/0040_p9_monitoring_and_incidents.sql`
- Create: `platform/migrations/0041_p9_generalised_approvals.sql`
- Create: `platform/frontend/src/pages/MonitoringWorkspace.tsx`
- Create: `platform/frontend/src/features/monitoring/{MonitoringSignals,MonitoringPortfolios,MonitoringTiming,MonitoringDrift,MonitoringRebalance,MonitoringIncidents}.tsx`
- Create: `platform/frontend/src/features/governance/{ApprovalQueue,UsersPanel,EntitlementsPanel}.tsx`
- Create: `platform/frontend/src/features/monitoring/{FactorCorrelation,FactorProduction}.tsx`
- Create: `platform/frontend/src/features/monitoring/monitoringTypes.ts`
- Modify: `platform/frontend/src/pages/WorkspacePage.tsx`（移除 6 个 `activationReasons` 条目）
- Create: `platform/scripts/verify_monitoring_browser.py`
- Test: `platform/tests/test_monitoring_api.py`
- Test: `platform/tests/test_cursor_pagination.py`
- Test: `platform/tests/test_monitoring_workspace_projection.py`
- Test: `platform/tests/test_governance_workspace_projection.py`
- Test: `platform/tests/test_p9_migrations.py`
- Test: `platform/frontend/src/features/monitoring/*.test.tsx`（六页）
- Test: `platform/frontend/src/features/governance/*.test.tsx`（三页）

**Interfaces:**
- Consumes: Task 1–4 全部；已有 `Envelope` / `fixed_read_context` / `response_context` /
  `WorkspaceState` 六态 / `DeskSection` 分区合同
- Produces:
  ```text
  GET  /api/monitoring/signals
  GET  /api/monitoring/portfolios
  GET  /api/monitoring/timing
  GET  /api/monitoring/drift            ?cursor=&limit=&severity=&owner_scope=
  GET  /api/monitoring/rebalance
  GET  /api/monitoring/incidents        ?cursor=&limit=&state=&owner_scope=
  GET  /api/monitoring/incidents/{incident_id}
  GET  /api/attribution/unified         ?cursor=&limit=&layer=
  GET  /api/factors/correlation
  GET  /api/factors/production
  GET  /api/governance/approvals        ?cursor=&limit=&subject_kind=&status=
  GET  /api/governance/users
  GET  /api/governance/entitlements
  POST /api/governance/approvals                # 受控写
  POST /api/monitoring/incidents/{id}/transitions  # 受控写
  POST /api/serving/registrations               # 受控写
  ```

- [ ] **Step 1: 先读现有 API 与前端的真实形状**

```bash
cd platform
grep -n "fixed_read_context\|def response_context\|def envelope" -A12 src/a_share_platform/api/app.py | head -60
grep -n "activationReasons" -A12 frontend/src/pages/WorkspacePage.tsx
grep -n "monitoring" frontend/src/navigation/routes.tsx
grep -n "useClientPage\|TABLE_PAGE_SIZE" -A20 frontend/src/pages/SystemScreen.tsx
ls migrations/ | tail -5
```

**已核实的现状（2026-08-16）**：

- `routes.tsx` 的 `workspaceDefinitions.monitoring.tabs` 已登记七项：
  `['Signals', 'Portfolios', 'Timing', 'Drift', 'Rebalance', 'Execution', 'Incidents']`；
- `WorkspacePage.tsx` 的 `activationReasons` 有六条阻断文案，本 plan 要移除其中
  `users` / `entitlements` / `approvals` 三条，**保留** `events`（P8）与 `execution`（P10）
  与 `agents`（P8）；
- `SystemScreen.tsx` 的 `useClientPage` 是**客户端**分页（第 52 行起），
  `TABLE_PAGE_SIZE = 20`。它对 Catalog 那种小表可以，对 Incident/Drift **不行**——
  它先取全量再切片。本 Task 的 Monitoring 页**不复用它**，新建 cursor hook；
- 现有 migration 到 `0036_p5_valuation_bundle_v2.sql`，故新增从 `0039` 起
  （`0037`/`0038` 留给 P-5/P-6）。

- [ ] **Step 2: 写 cursor pagination 红测（先做这个，它决定所有投影的形状）**

```python
# platform/tests/test_cursor_pagination.py
"""Cursor pagination over append-only ledgers.

Offset pagination is wrong here for a specific reason, not a general one.  The
incident and drift ledgers are append-only and written continuously — thirteen
metrics per subject per monitoring run — so a row inserted between two page
requests shifts every subsequent offset, and page two either repeats a row from
page one or skips one entirely.  Skipping is the dangerous half: the skipped row is
an incident nobody saw.

A cursor encodes a position in a stable sort rather than a count of rows before it,
so an insertion does not move it.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from a_share_platform.adapters.memory.monitoring import InMemoryIncidentLedger
from a_share_platform.application.monitoring_workspace import (
    MAX_PAGE_LIMIT,
    CursorPage,
    decode_cursor,
    encode_cursor,
)

from tests.test_incident_state_machine import OPENED, _open_incident


def _incident(*, incident_id: str, opened_at: datetime | None = None):
    """One ledger row.  opened_at plus incident_id is the total sort key."""
    import dataclasses

    return dataclasses.replace(
        _open_incident(),
        incident_id=incident_id,
        opened_at=opened_at or OPENED,
        dedupe_key=f"{incident_id:>064}".replace(" ", "0")[:64],
    )


def _ledger_with(*, count: int) -> InMemoryIncidentLedger:
    """`count` incidents, one minute apart, in insertion order."""
    return InMemoryIncidentLedger(
        incidents=tuple(
            _incident(
                incident_id=f"incident:{index:04d}",
                opened_at=OPENED + timedelta(minutes=index),
            )
            for index in range(count)
        )
    )


class CursorContractTest(unittest.TestCase):
    def test_a_cursor_round_trips(self) -> None:
        cursor = encode_cursor(sort_key=("2026-08-16T01:00:00Z", "incident:0042"))
        self.assertEqual(
            decode_cursor(cursor), ("2026-08-16T01:00:00Z", "incident:0042")
        )

    def test_a_cursor_is_opaque_to_the_client(self) -> None:
        """A readable cursor invites clients to construct one, which couples them
        to the sort key and makes changing the sort a breaking change."""
        cursor = encode_cursor(sort_key=("2026-08-16T01:00:00Z", "incident:0042"))
        self.assertNotIn("incident:0042", cursor)

    def test_a_tampered_cursor_is_refused(self) -> None:
        """Not silently reset to the first page: a client that receives page one
        when it asked for page five will loop forever."""
        with self.assertRaises(ValueError):
            decode_cursor("not-a-cursor")

    def test_an_insertion_between_pages_does_not_skip_a_row(self) -> None:
        """The assertion that justifies cursors over offsets.  With OFFSET this
        test fails by omitting exactly one row, and the omitted row is an incident
        nobody saw."""
        store = _ledger_with(count=50)
        first = store.page(cursor=None, limit=20)
        store.append(_incident(incident_id="incident:new"))
        second = store.page(cursor=first.next_cursor, limit=20)
        seen = [row.incident_id for row in (*first.rows, *second.rows)]
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(len(seen), 40)

    def test_the_sort_key_is_total(self) -> None:
        """Two incidents with the same timestamp need the id as a tiebreak, or the
        cursor position is ambiguous and pagination becomes non-deterministic."""
        simultaneous = InMemoryIncidentLedger(
            incidents=tuple(
                _incident(incident_id=f"incident:{index:04d}", opened_at=OPENED)
                for index in range(4)
            )
        )
        first = simultaneous.page(cursor=None, limit=2)
        second = simultaneous.page(cursor=first.next_cursor, limit=2)
        self.assertEqual(
            [row.incident_id for row in first.rows],
            ["incident:0000", "incident:0001"],
        )
        self.assertEqual(
            [row.incident_id for row in second.rows],
            ["incident:0002", "incident:0003"],
        )
        self.assertEqual(
            decode_cursor(first.next_cursor)[1], "incident:0001"
        )

    def test_the_last_page_has_a_null_next_cursor(self) -> None:
        store = _ledger_with(count=25)
        first = store.page(cursor=None, limit=20)
        last = store.page(cursor=first.next_cursor, limit=20)
        self.assertIsNotNone(first.next_cursor)
        self.assertIsNone(last.next_cursor)
        self.assertEqual(len(last.rows), 5)

    def test_a_limit_above_the_maximum_is_clamped_not_rejected(self) -> None:
        """Rejecting would break a client that guessed high; clamping and stating
        the effective limit in the response does not."""
        page = _ledger_with(count=500).page(cursor=None, limit=10_000)
        self.assertIsInstance(page, CursorPage)
        self.assertEqual(page.limit, MAX_PAGE_LIMIT)
        self.assertEqual(len(page.rows), MAX_PAGE_LIMIT)

    def test_the_page_reports_the_total_separately_from_the_rows(self) -> None:
        """The frontend must be able to say '20 of 4,312' without fetching 4,312.
        This is the same discipline SystemScreen already follows by preserving
        `total` while paging."""
        page = _ledger_with(count=4312).page(cursor=None, limit=20)
        self.assertEqual(len(page.rows), 20)
        self.assertEqual(page.total, 4312)
```

- [ ] **Step 3: 运行确认红测 → 实现 → 转绿**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_cursor_pagination -v`

- [ ] **Step 4: 写服务端聚合红测**

```python
# platform/tests/test_monitoring_workspace_projection.py
"""Monitoring projections aggregate on the server.

Step 08 Task 5 requires server-side aggregation, and the reason is not
performance.  If the browser counts open incidents, then 'how many incidents are
open' has two answers — the server's and the client's — and they diverge the moment
pagination, filtering or a stale cache is involved.  The page is what people act
on, so it must not be the one that is wrong.

The six sections reuse the DeskSection contract rather than inventing a second
status vocabulary: ready / partial / empty / unavailable are server-owned, loading
and error belong to the client.
"""

from __future__ import annotations

import dataclasses
import inspect
import unittest
from datetime import UTC, datetime, timedelta

from a_share_platform.adapters.memory.monitoring import (
    InMemoryIncidentLedger,
    UnavailableIncidentRepository,
)
from a_share_platform.application.monitoring_workspace import MonitoringWorkspaceService
from a_share_platform.domain.desk import DeskSectionStatus
from a_share_platform.domain.incidents import IncidentState
from a_share_platform.domain.monitoring import DriftSeverity

from tests.test_incident_state_machine import OPENED, _open_incident

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)

# The summary numbers asserted below are properties of this fixture, so the fixture
# states them explicitly: 12 open, 8 acknowledged, 20 owned by data, 50 in total.
_STATE_COUNTS: tuple[tuple[IncidentState, int], ...] = (
    (IncidentState.OPEN, 12),
    (IncidentState.ACKNOWLEDGED, 8),
    (IncidentState.MITIGATING, 10),
    (IncidentState.RESOLVED, 10),
    (IncidentState.POSTMORTEM, 6),
    (IncidentState.CLOSED, 4),
)
_OWNER_SCOPES: tuple[tuple[str, int], ...] = (
    ("data", 20),
    ("research", 20),
    ("portfolio", 10),
)


def _fifty_incidents() -> tuple[object, ...]:
    states = [state for state, count in _STATE_COUNTS for _ in range(count)]
    scopes = [scope for scope, count in _OWNER_SCOPES for _ in range(count)]
    assert len(states) == len(scopes) == 50
    severities = (
        DriftSeverity.CRITICAL, DriftSeverity.MAJOR,
        DriftSeverity.WARNING, DriftSeverity.INFO,
    )
    return tuple(
        dataclasses.replace(
            _open_incident(),
            incident_id=f"incident:{index:04d}",
            state=state,
            severity=severities[index % len(severities)],
            primary_owner_scope=scope,
            opened_at=OPENED + timedelta(minutes=index),
            dedupe_key=f"{index:064d}",
        )
        for index, (state, scope) in enumerate(zip(states, scopes, strict=True))
    )


def _service(
    *,
    incidents: tuple[object, ...] | None = None,
    incident_repository: object | None = None,
    signals: tuple[object, ...] = (),
) -> MonitoringWorkspaceService:
    return MonitoringWorkspaceService(
        incidents=incident_repository
        or InMemoryIncidentLedger(incidents=incidents or ()),
        signals=signals,
    )


class ServerAggregationTest(unittest.TestCase):
    def test_the_incident_summary_counts_come_from_the_server(self) -> None:
        projection = _service(incidents=_fifty_incidents()).project(now=NOW)
        summary = projection.section("incidents").payload["summary"]
        self.assertEqual(summary["open"], 12)
        self.assertEqual(summary["acknowledged"], 8)
        self.assertEqual(summary["by_owner_scope"]["data"], 20)

    def test_the_summary_counts_the_whole_ledger_not_the_current_page(self) -> None:
        """A summary computed over one page says '20 open' whatever the truth is,
        and it changes as the user pages, which is worse than being merely wrong."""
        projection = _service(incidents=_fifty_incidents()).project(now=NOW, limit=20)
        self.assertEqual(len(projection.section("incidents").payload["rows"]), 20)
        self.assertEqual(projection.section("incidents").payload["summary"]["total"], 50)

    def test_severity_ordering_is_server_owned(self) -> None:
        """Sorting in the browser means two clients with different locales can
        order severities differently, and a critical can appear below a warning."""
        rows = (
            _service(incidents=_fifty_incidents())
            .project(now=NOW, limit=50)
            .section("incidents")
            .payload["rows"]
        )
        rank = {"critical": 0, "major": 1, "warning": 2, "info": 3}
        severities = [rank[row["severity"]] for row in rows]
        self.assertEqual(severities, sorted(severities))
        self.assertEqual(rows[0]["severity"], "critical")

    def test_dedupe_is_not_reapplied_in_the_projection(self) -> None:
        """Deduplication belongs to Task 3's domain layer.  Doing it again here
        would be a second answer to 'is this the same problem'."""
        from a_share_platform.application import monitoring_workspace

        source = inspect.getsource(monitoring_workspace)
        self.assertNotIn("dedupe_key", source)
        # Two incidents that share a dedupe key are both projected; collapsing them
        # here would silently disagree with the ledger's own count.
        base = _open_incident()
        pair = (
            dataclasses.replace(base, incident_id="incident:0001",
                                state=IncidentState.CLOSED),
            dataclasses.replace(base, incident_id="incident:0002"),
        )
        rows = (
            _service(incidents=pair)
            .project(now=NOW)
            .section("incidents")
            .payload["rows"]
        )
        self.assertEqual(len(rows), 2)


class SectionStateTest(unittest.TestCase):
    def test_an_unconfigured_incident_store_is_unavailable_not_empty(self) -> None:
        """Following the pattern desk_projection.py already uses: each section
        resolves in its own try block so one broken store degrades one section."""
        projection = _service(
            incident_repository=UnavailableIncidentRepository()
        ).project(now=NOW)
        incidents = projection.section("incidents")
        self.assertIs(incidents.status, DeskSectionStatus.UNAVAILABLE)
        self.assertTrue(incidents.blockers)
        self.assertIsNone(incidents.payload)
        # One broken store degrades one section, not the page.
        self.assertIs(projection.section("drift").status, DeskSectionStatus.EMPTY)

    def test_a_configured_empty_store_is_empty(self) -> None:
        incidents = _service(incidents=()).project(now=NOW).section("incidents")
        self.assertIs(incidents.status, DeskSectionStatus.EMPTY)
        self.assertEqual(incidents.blockers, ())
        self.assertIsNone(incidents.payload)

    def test_the_signals_section_reports_zero_with_no_snapshot(self) -> None:
        """docs/18 §3.5 Gate 逐字：无真实 Snapshot 时计数必须为 0."""
        projection = _service(signals=()).project(now=NOW)
        self.assertEqual(projection.section("signals").status.value, "empty")

    def test_the_portfolios_section_states_that_intent_is_not_order(self) -> None:
        """docs/18 §3.5 Gate 逐字：无真实账户连接；Intent 不是 Order."""
        section = _service().project(now=NOW).section("portfolios")
        codes = {blocker.code for blocker in section.blockers}
        self.assertIn("NO_REAL_ACCOUNT_CONNECTION", codes)
        reasons = " ".join(blocker.reason for blocker in section.blockers)
        self.assertIn("Intent", reasons)
        self.assertIn("Order", reasons)

    def test_the_timing_section_reports_zero_portfolio_impact(self) -> None:
        """docs/18 §3.5 Gate 逐字：no edit/no backfill；晋级前组合影响 0%."""
        projection = _service().project(now=NOW)
        self.assertEqual(
            projection.section("timing").payload["portfolio_impact_ratio"], "0"
        )

    def test_the_drift_section_states_it_only_blocks_or_requests_review(self) -> None:
        """docs/18 §3.5 Gate 逐字：只阻断或创建 Review，不静默改模型.

        The page states the guarantee that Task 2 enforces, so a reader does not
        have to infer it from the absence of a button.
        """
        actions = _service().project(now=NOW).section("drift").payload["permitted_actions"]
        self.assertEqual(
            set(actions),
            {"block_downstream", "request_review", "execute_approved_rollback"},
        )

    def test_the_rebalance_section_has_no_order_action(self) -> None:
        """docs/18 §3.5 Gate 逐字：T+1 等规则生效；没有下单按钮."""
        payload = _service().project(now=NOW).section("rebalance").payload
        self.assertEqual(payload["actions"], [])
        self.assertNotIn("send_order", str(payload))
        self.assertTrue(payload["settlement_rules"]["t_plus_1"])

    def test_the_execution_section_stays_unavailable_with_a_p10_blocker(self) -> None:
        """Execution is P10 and this plan does not implement it.  The section
        reports a stage blocker rather than being hidden, because a hidden tab and
        an unimplemented one are different facts."""
        section = _service().project(now=NOW).section("execution")
        self.assertEqual(section.status.value, "unavailable")
        self.assertTrue(
            any("P10" in blocker.code for blocker in section.blockers)
        )
```

- [ ] **Step 5: 治理页投影红测**

```python
# platform/tests/test_governance_workspace_projection.py
"""Users, Entitlements and Approvals projections.

Users and Entitlements have a hard constraint the other pages do not: SPEC-049 says
不能把本地 human 字符串冒充身份认证.  There is no identity provider configured, so
the runtime has exactly one principal — Principal.anonymous() with read_public —
and the page must say so rather than listing a plausible-looking user table.
"""

from __future__ import annotations

import inspect
import unittest
from datetime import UTC, datetime, timedelta

from a_share_platform.adapters.memory.approvals import InMemoryApprovalRepository
from a_share_platform.application.governance_workspace import (
    GovernanceWorkspaceService,
)
from a_share_platform.application.permissions import (
    Permission,
    PermissionPolicy,
    Principal,
    Role,
)
from a_share_platform.domain.approvals import ApprovalSubjectKind
from a_share_platform.domain.desk import DeskSectionStatus
from a_share_platform.domain.factor_lifecycle import ApprovalDecision, ApprovalScope

from tests.test_approval_generalisation import (  # noqa: E402
    DECIDED_AT,
    _approved_review,
    _subject_with_unmet_precondition,
    subject,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _governance_service(
    *,
    reviews: tuple[object, ...] = (),
    identity_provider: object | None = None,
) -> GovernanceWorkspaceService:
    repository = InMemoryApprovalRepository()
    for review in reviews:
        repository.append(review)
    return GovernanceWorkspaceService(
        approvals=repository,
        permission_policy=PermissionPolicy.default(),
        identity_provider=identity_provider,
        principal=Principal.anonymous(),
    )


def _blocked_queue_row() -> dict[str, object]:
    """A submitted subject whose evidence is incomplete: queued, not decided."""
    pending = _governance_service(
        reviews=()
    ).enqueue_for_test(
        subject=_subject_with_unmet_precondition(reason="validation evidence missing"),
        scope=ApprovalScope.RESEARCH_BACKTEST,
    )
    return pending


class UsersProjectionTest(unittest.TestCase):
    def test_with_no_identity_provider_the_page_reports_unavailable(self) -> None:
        """SPEC-049 逐字：未启用时不得显示伪用户.  api/app.py's
        anonymous_principal() docstring already states the rule: 'headers never
        create a principal'."""
        section = _governance_service().project(now=NOW).section("users")
        self.assertEqual(section.status.value, "unavailable")

    def test_the_page_never_lists_a_fabricated_user(self) -> None:
        """Figma node 9:883 draws User-1, User-2, User-3 and Reviewer-1,
        Reviewer-2.  All five are design fixtures and none may reach the runtime."""
        payload = _governance_service().project(now=NOW).section("users").payload
        self.assertIsNone(payload)

    def test_the_anonymous_principal_is_shown_as_the_real_current_identity(self) -> None:
        """Honest rather than empty: there is a principal, it just has one
        permission.  GET /api/identity already returns exactly this."""
        section = _governance_service().project(now=NOW).section("users")
        self.assertEqual(section.coverage["current_subject_id"], "anonymous")
        self.assertEqual(section.coverage["current_permissions"], ["read_public"])
        self.assertEqual(section.coverage["current_roles"], [])
        for fixture in ("User-1", "User-2", "User-3", "Reviewer-1", "Reviewer-2"):
            with self.subTest(fixture=fixture):
                self.assertNotIn(fixture, str(section.coverage))


class EntitlementsProjectionTest(unittest.TestCase):
    def test_the_projection_reflects_the_real_permission_matrix(self) -> None:
        """Eight roles by eight permissions, read from PermissionPolicy.default()
        rather than restated in the projection.  A restated matrix is a second
        source of truth for who may approve what."""
        rows = _governance_service().project(now=NOW).section("entitlements").payload["rows"]
        self.assertEqual(len(rows), 8)
        agent = next(row for row in rows if row["role"] == "agent")
        self.assertEqual(agent["permissions"], ["read_public"])

    def test_the_projection_states_that_hiding_a_button_is_not_a_permission(self) -> None:
        """Figma node 9:883 边界卡 逐字：前端隐藏按钮不能替代权限校验."""
        payload = _governance_service().project(now=NOW).section("entitlements").payload
        self.assertIn("前端隐藏按钮不能替代权限校验", payload["boundary_notes"])

    def test_the_projection_is_read_only(self) -> None:
        """Editing entitlements needs an identity provider and an approval path;
        neither exists, so the page has no write action at all."""
        from a_share_platform.application import governance_workspace

        payload = _governance_service().project(now=NOW).section("entitlements").payload
        self.assertEqual(payload["actions"], [])
        source = inspect.getsource(governance_workspace)
        for verb in ("def grant", "def revoke", "def set_role", "def update_"):
            with self.subTest(verb=verb):
                self.assertNotIn(verb, source)


class ApprovalQueueProjectionTest(unittest.TestCase):
    def test_the_queue_spans_all_six_subject_kinds(self) -> None:
        reviews = tuple(
            _approved_review(review_id=f"review:{index:04d}")
            for index, _ in enumerate(ApprovalSubjectKind, start=1)
        )
        rows = (
            _governance_service(reviews=reviews)
            .project(now=NOW)
            .section("approvals")
            .payload["rows"]
        )
        self.assertEqual(
            {row["subject_kind"] for row in rows},
            {kind.value for kind in ApprovalSubjectKind},
        )

    def test_blocked_is_a_queue_state_not_an_approval_decision(self) -> None:
        """Figma node 9:883 draws four statuses — Pending, Approved, Rejected,
        Blocked — while ApprovalDecision has three values.  Blocked is 'evidence
        incomplete so no decision may be made', which is not a decision.  Adding
        ApprovalDecision.BLOCKED would make 'the system refused' and 'a person
        refused' the same value, and only one of those is someone's judgement.
        """
        from a_share_platform.domain.factor_lifecycle import ApprovalDecision

        self.assertEqual(
            {item.value for item in ApprovalDecision},
            {"approved", "rejected", "request_changes"},
        )
        row = _blocked_queue_row()
        self.assertEqual(row["status"], "blocked")
        self.assertIsNone(row["decision"])
        self.assertTrue(row["blockers"])

    def test_the_submitter_and_the_reviewer_are_separate_columns(self) -> None:
        """The prototype's 提交人 / Reviewer pair, now backed by Task 4's SoD."""
        review = _approved_review(review_id="review:0001")
        row = (
            _governance_service(reviews=(review,))
            .project(now=NOW)
            .section("approvals")
            .payload["rows"][0]
        )
        self.assertEqual(row["submitted_by"], "subject:researcher-1")
        self.assertEqual(row["reviewer_id"], "subject:reviewer-1")
        self.assertNotEqual(row["submitted_by"], row["reviewer_id"])

    def test_an_evidence_incomplete_row_disables_the_decision_action(self) -> None:
        """Figma 审批规则 逐字：证据不足 BLOCKER 禁用决定并列出全部 blocker.

        Disabled in the projection, not only in the button: a disabled button is a
        rendering choice and the API must refuse independently.
        """
        row = _blocked_queue_row()
        self.assertFalse(row["decision_enabled"])
        self.assertGreaterEqual(len(row["blockers"]), 1)
        self.assertIn("evidence", " ".join(row["blockers"]).lower())

    def test_expired_and_superseded_reviews_are_shown_as_such_not_as_approved(
        self,
    ) -> None:
        """An approval that no longer authorises but still reads 'Approved' on the
        page is the most misleading cell this table can contain."""
        expired = _approved_review(
            review_id="review:0001", expires_at=DECIDED_AT + timedelta(days=90)
        )
        superseded = _approved_review(review_id="review:0002")
        superseding = _approved_review(
            review_id="review:0003", supersedes_review_id="review:0002"
        )
        rows = {
            row["review_id"]: row
            for row in _governance_service(
                reviews=(expired, superseded, superseding)
            )
            .project(now=DECIDED_AT + timedelta(days=91))
            .section("approvals")
            .payload["rows"]
        }
        self.assertEqual(rows["review:0001"]["status"], "expired")
        self.assertEqual(rows["review:0002"]["status"], "superseded")
        self.assertEqual(rows["review:0003"]["status"], "approved")
        self.assertFalse(rows["review:0001"]["authorizes_now"])
        self.assertFalse(rows["review:0002"]["authorizes_now"])
```

- [ ] **Step 6: API 合同红测**

```python
# platform/tests/test_monitoring_api.py
"""Eleven reads and three gated writes.

The three writes are the only P9 endpoints that can change what the platform will
do, so each needs an entitlement check that matches the service layer rather than
duplicating its logic — and each must be impossible to escalate through in one
step.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from a_share_platform.adapters.memory.monitoring import UnavailableIncidentRepository
from a_share_platform.api.app import create_app

READ_ENDPOINTS: tuple[str, ...] = (
    "/api/monitoring/signals",
    "/api/monitoring/portfolios",
    "/api/monitoring/timing",
    "/api/monitoring/drift",
    "/api/monitoring/rebalance",
    "/api/monitoring/incidents",
    "/api/attribution/unified",
    "/api/factors/correlation",
    "/api/factors/production",
    "/api/governance/approvals",
    "/api/governance/users",
    "/api/governance/entitlements",
)

CONTEXT_KEYS: tuple[str, ...] = (
    "as_of", "system_as_of", "data_mode", "deployment_stage",
    "trust_state", "dataset_version_ids", "run_id", "warnings",
)


def _client(**overrides: object) -> TestClient:
    """Same shape as tests/test_desk_api.py: a real app over empty environment."""
    with patch.dict(os.environ, {}, clear=True):
        return TestClient(create_app(**overrides))  # type: ignore[arg-type]


class ReadEndpointTest(unittest.TestCase):
    def test_every_read_endpoint_returns_the_standard_envelope(self) -> None:
        """SPEC-051: data plus context with as_of, system_as_of, data_mode,
        deployment_stage, trust_state, dataset_version_ids, run_id, warnings."""
        client = _client()
        for path in READ_ENDPOINTS:
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertIn("data", payload)
                for key in CONTEXT_KEYS:
                    self.assertIn(key, payload["context"])
                self.assertEqual(payload["context"]["data_mode"], "current_research")
                self.assertEqual(payload["context"]["deployment_stage"], "research")

    def test_a_data_mode_query_parameter_is_refused(self) -> None:
        """fixed_read_context already raises RunContextOverrideDenied.  Asserted
        on the new endpoints so none of them accidentally accepts one."""
        client = _client()
        for path in READ_ENDPOINTS:
            with self.subTest(path=path):
                response = client.get(path, params={"data_mode": "strict_historical"})
                self.assertEqual(response.status_code, 400)
                self.assertIn("data_mode", response.json()["detail"])

    def test_incident_detail_returns_404_for_an_unknown_id(self) -> None:
        response = _client().get("/api/monitoring/incidents/incident:does-not-exist")
        self.assertEqual(response.status_code, 404)

    def test_drift_endpoint_filters_by_owner_scope_server_side(self) -> None:
        client = _client()
        response = client.get(
            "/api/monitoring/drift", params={"owner_scope": "data", "limit": 20}
        )
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]["rows"]
        self.assertTrue(all(row["owner_scope"] == "data" for row in rows))
        # An unknown scope is rejected rather than silently returning everything.
        self.assertEqual(
            client.get(
                "/api/monitoring/drift", params={"owner_scope": "platform"}
            ).status_code,
            400,
        )

    def test_an_unavailable_store_returns_503_with_a_reason(self) -> None:
        client = _client(incident_repository=UnavailableIncidentRepository())
        response = client.get("/api/monitoring/incidents")
        self.assertEqual(response.status_code, 503)
        self.assertTrue(response.json()["detail"].strip())


class WriteEndpointTest(unittest.TestCase):
    def test_approval_write_requires_the_matching_permission(self) -> None:
        """With no identity provider the runtime principal is anonymous, so this is
        a 403 today.  That is the correct current behaviour and the test records
        it rather than mocking a principal into existence."""
        response = _client().post(
            "/api/governance/approvals",
            json={
                "review_id": "review:0001",
                "subject_kind": "alpha_model",
                "subject_id": "alpha-model:composite",
                "subject_version": "v2",
                "scope": "research_backtest",
                "decision": "approved",
                "reason": "anonymous approval attempt",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_approval_write_refuses_self_approval_at_the_api_boundary(self) -> None:
        """Task 4 enforces SoD in the service.  Asserted again here because the
        API is the reachable surface, and a future endpoint that constructed the
        review differently would bypass the service check."""
        # A reviewer principal cannot be forged through headers, so the escalation
        # this test guards against is refused before SoD is even reached; when an
        # identity provider exists the same request must fail with 409, never 201.
        response = _client().post(
            "/api/governance/approvals",
            json={
                "review_id": "review:0002",
                "subject_kind": "alpha_model",
                "subject_id": "alpha-model:composite",
                "subject_version": "v2",
                "scope": "research_backtest",
                "decision": "approved",
                "reason": "self approval attempt",
                "submitted_by": "subject:reviewer-1",
                "actor_id": "subject:reviewer-1",
            },
        )
        self.assertIn(response.status_code, (403, 409))
        self.assertNotEqual(response.status_code, 201)

    def test_incident_transition_write_refuses_an_illegal_transition_with_409(
        self,
    ) -> None:
        response = _client().post(
            "/api/monitoring/incidents/incident:0001/transitions",
            json={"to_state": "closed", "reason": "end of day"},
        )
        self.assertIn(response.status_code, (403, 409))

    def test_serving_registration_write_refuses_limited_live_scope(self) -> None:
        """AGENTS.md: P11 需新的明确授权.  There is no authorisation record, so
        the endpoint refuses rather than accepting and never acting."""
        response = _client().post(
            "/api/serving/registrations",
            json={
                "registration_id": "registration:0001",
                "review_id": "review:0001",
                "scope": "limited_live",
            },
        )
        self.assertIn(response.status_code, (403, 409))
        self.assertNotEqual(response.status_code, 201)

    def test_no_endpoint_grants_order_authority(self) -> None:
        """Mirrors the grants_order_authority property that FactorPromotionReview
        already declares False."""
        paths = {
            route.path for route in _client().app.routes if hasattr(route, "path")
        }
        for fragment in ("order", "trade", "broker", "execute"):
            with self.subTest(fragment=fragment):
                self.assertEqual(
                    [path for path in paths if fragment in path.lower()], []
                )
```

- [ ] **Step 7: migration 与 PostgreSQL repository**

三个 migration，全部 append-only trigger（照 `0027_factor_promotion_reviews.sql`
第 43–54 行的 `reject_..._mutation()` + `BEFORE UPDATE OR DELETE` 模式）：

```sql
-- 0040_p9_monitoring_and_incidents.sql 的关键约束（照领域不变量写）
CREATE TABLE research.drift_observations (
    observation_id TEXT PRIMARY KEY CHECK (observation_id <> ''),
    content_hash TEXT NOT NULL UNIQUE CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    threshold_policy_hash TEXT NOT NULL CHECK (threshold_policy_hash ~ '^[0-9a-f]{64}$'),
    owner_scope TEXT NOT NULL CHECK (
        owner_scope IN ('data', 'research', 'portfolio', 'execution')
    ),
    status TEXT NOT NULL CHECK (
        status IN ('within_threshold', 'breached', 'unavailable')
    ),
    severity TEXT CHECK (severity IN ('info', 'warning', 'major', 'critical')),
    observed_value NUMERIC,
    unavailable_reason TEXT,
    -- unavailable carries no value and needs a reason; breached needs a severity.
    CHECK (status <> 'unavailable' OR (observed_value IS NULL AND unavailable_reason <> '')),
    CHECK (status <> 'breached' OR severity IS NOT NULL),
    CHECK (status <> 'within_threshold' OR severity IS NULL),
    ...
);

CREATE UNIQUE INDEX incidents_one_open_per_dedupe_key
ON observation.incidents (dedupe_key)
WHERE state NOT IN ('closed');
-- One live incident per root cause, enforced by the database rather than only by
-- the intake service: a second writer would otherwise create a duplicate.
```

- [ ] **Step 8: migration 红测 —— 空库 + 幂等**

```python
# platform/tests/test_p9_migrations.py
"""The three P9 migrations against a real local database.

Skipped without ASP_DATABASE_URL: a green result from a skipped test would be a
false claim that append-only is enforced in PostgreSQL rather than only in Python.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

import psycopg

from a_share_platform.adapters.postgres.migrations import (
    apply_migrations,
    discover_migrations,
)

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
P9_FILES = (
    "0039_p9_unified_attribution.sql",
    "0040_p9_monitoring_and_incidents.sql",
    "0041_p9_generalised_approvals.sql",
)


@unittest.skipUnless(os.environ.get("ASP_DATABASE_URL"), "needs a local database")
class P9MigrationTest(unittest.TestCase):
    def connection(self) -> psycopg.Connection:
        return psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True)

    def test_migrations_apply_to_an_empty_database(self) -> None:
        names = {path.name for path in discover_migrations(MIGRATIONS)}
        for filename in P9_FILES:
            with self.subTest(filename=filename):
                self.assertIn(filename, names)
        with self.connection() as connection:
            applied = apply_migrations(connection, MIGRATIONS)
            for filename in P9_FILES:
                with self.subTest(filename=filename):
                    self.assertIn(filename, applied)
            for table in (
                "research.unified_attribution_snapshots",
                "research.drift_observations",
                "observation.incidents",
                "observation.incident_transitions",
                "governance.approval_reviews",
                "governance.serving_registrations",
            ):
                with self.subTest(table=table):
                    connection.execute(f"select count(*) from {table}")

    def test_migrations_are_idempotent(self) -> None:
        with self.connection() as connection:
            apply_migrations(connection, MIGRATIONS)
            second = apply_migrations(connection, MIGRATIONS)
        # The ledger already recorded them, so a second pass applies nothing.
        for filename in P9_FILES:
            with self.subTest(filename=filename):
                self.assertNotIn(filename, second)

    def test_an_update_to_an_incident_transition_is_rejected(self) -> None:
        """append-only enforced in the database, not only in Python.  A repository
        bug or a psql session must not be able to rewrite an audit trail."""
        with self.connection() as connection:
            apply_migrations(connection, MIGRATIONS)
            self._insert_open_incident(connection, incident_id="incident:mig:0001")
            connection.execute(
                """
                insert into observation.incident_transitions (
                    transition_id, incident_id, from_state, to_state,
                    actor_id, actor_role, occurred_at, reason
                ) values (
                    'transition:mig:0001', 'incident:mig:0001', 'open',
                    'acknowledged', 'subject:reviewer-1', 'reviewer', now(),
                    'acknowledged by the owning desk'
                )
                """
            )
            with self.assertRaises(psycopg.errors.RaiseException):
                connection.execute(
                    "update observation.incident_transitions "
                    "set reason = 'rewritten' where transition_id = 'transition:mig:0001'"
                )
            with self.assertRaises(psycopg.errors.RaiseException):
                connection.execute(
                    "delete from observation.incident_transitions "
                    "where transition_id = 'transition:mig:0001'"
                )

    def test_two_open_incidents_with_one_dedupe_key_are_rejected(self) -> None:
        with self.connection() as connection:
            apply_migrations(connection, MIGRATIONS)
            self._insert_open_incident(
                connection, incident_id="incident:mig:0002", dedupe_key="a" * 64
            )
            with self.assertRaises(psycopg.errors.UniqueViolation):
                self._insert_open_incident(
                    connection, incident_id="incident:mig:0003", dedupe_key="a" * 64
                )

    def test_an_unavailable_drift_observation_with_a_value_is_rejected(self) -> None:
        """The zero-fill prohibition, expressed as a database constraint."""
        with self.connection() as connection:
            apply_migrations(connection, MIGRATIONS)
            with self.assertRaises(psycopg.errors.CheckViolation):
                connection.execute(
                    """
                    insert into research.drift_observations (
                        observation_id, content_hash, threshold_policy_hash,
                        owner_scope, status, severity, observed_value,
                        unavailable_reason
                    ) values (
                        'drift:mig:0001', %s, %s, 'research', 'unavailable',
                        null, 0, 'feature panel store unreachable'
                    )
                    """,
                    ("b" * 64, "c" * 64),
                )

    def _insert_open_incident(
        self,
        connection: psycopg.Connection,
        *,
        incident_id: str,
        dedupe_key: str = "d" * 64,
    ) -> None:
        connection.execute(
            """
            insert into observation.incidents (
                incident_id, dedupe_key, state, severity, primary_owner_scope,
                runbook_id, opened_at, reopen_count, content_hash
            ) values (
                %s, %s, 'open', 'major', 'research',
                'runbook.feature-drift.v1', now(), 0, encode(sha256(%s), 'hex')
            )
            """,
            (incident_id, dedupe_key, incident_id.encode("utf-8")),
        )
```

- [ ] **Step 9: 前端 —— Monitoring 六页（每页红测先行）**

**复用** `features/desk/DeskSection.tsx` 与 `components/WorkspaceState.tsx` 的六态，
**不新建**第二套分区模式（P-4 已立此规）。

**新建** cursor hook，不复用 `SystemScreen.tsx` 的 `useClientPage`——
后者先取全量再切片，对 Incident/Drift 表不可用。

```tsx
// platform/frontend/src/features/monitoring/MonitoringIncidents.test.tsx
/**
 * The incident table never aggregates.
 *
 * Counts, severity ordering and owner grouping all arrive from the server.  A
 * client-side tally disagrees with the server the moment pagination or a stale
 * cache is involved, and the page is the artefact people act on.
 */
describe('MonitoringIncidents', () => {
  it('renders the server summary without recomputing it', () => {
    // Assert the rendered "12 open" comes from payload.summary.open and that no
    // filter/reduce over rows appears in the component.
  })

  it('shows 20 of 4,312 without fetching 4,312', () => {
    // total from the server, rows from the page.
  })

  it('keeps a critical above a warning in the order the server sent', () => {
    // No client-side sort: a locale-dependent sort can put critical below warning.
  })

  it('shows the occurrence count so deduplication does not hide scale', () => {
    // 500 occurrences behind one incident renders 500.
  })

  it('shows first-seen time, owner, severity, state and runbook', () => {
    // SPEC-040's six required fields, all present or the alert is incomplete.
  })

  it('offers no action that mutates a model or a weight', () => {
    // The three permitted actions only.
  })

  it('renders the six states from the shared WorkspaceState contract', () => {
  })

  it('leaks no Figma fixture value', () => {
    // REV-1500, Q-1300, RUN-1400, User-1, 184, 169, 12, 3, Reviewer-1, Reviewer-2
  })
})
```

其余五页各自的关键断言：

- **Signals**：无 Snapshot 时计数为 `0` 且状态 `empty`；不显示排名变化的推算值；
- **Portfolios**：显式文案「Intent 不是 Order」；无真实账户连接的 blocker；
- **Timing**：`组合影响` 恒为 `0%`；historical/OOS/forward **三分屏**（P-6 已立此规，
  本页只读 forward）；`no edit / no backfill` 文案；
- **Drift**：三个 permitted action 全部显示；PSI 值旁必须显示
  `threshold_policy_hash` 前 8 位与 `sample_size`；`unavailable` 行不显示 0；
- **Rebalance**：**无下单按钮**（一个测试直接断言 DOM 里没有任何 `type=submit`
  或 order 相关 action）；原因链可钻取。

- [ ] **Step 10: 前端 —— 治理三页与 Factors 两页（每页红测先行）**

- **Approvals**（唯一有精确 Frame，node `9:883`）：8 列逐列对照；
  四个摘要卡；`Blocked` 作为队列状态而非 decision；提交人与 Reviewer 分列；
  证据不足时决定按钮 disabled **且** API 独立拒绝；
- **Users**：`unavailable` + 真实原因（无 identity provider）；**不渲染任何用户行**；
- **Entitlements**：8 × 8 矩阵从 `/api/governance/entitlements` 读，
  只读，含「前端隐藏按钮不能替代权限校验」文案；
- **Factors/Correlation**：从 `unavailable` 转为真实相关矩阵（若有获批因子）
  或 `empty`（若无）；**一个测试断言页面不提供任何改权重的操作**
  （docs/18 §3.3 Gate 逐字：「不自动修改因子权重或审批」）；
- **Factors/Production**：`ServingRegistration` 列表；用途隔离可见；
  **一个测试断言 research/shadow/paper 三个 scope 的行不合并展示**
  （docs/18 §3.3 Gate 逐字：「Research/Shadow/Paper 不能相互提升」）。

- [ ] **Step 11: 移除三条 `activationReasons` 并四视口验收**

```bash
cd platform
# 三条移除：users / entitlements / approvals
# 三条保留：events（P8）、agents（P8）、execution（P10）
npm --prefix frontend test -- --run
npm --prefix frontend run lint
npm --prefix frontend run build
.venv/bin/python scripts/verify_monitoring_browser.py
```

`verify_monitoring_browser.py` 照 `scripts/verify_desk_browser.py` 的形状写，
**44 个检查点（11 页 × 4 视口）**，每个视口断言：

- `document.scrollWidth === document.clientWidth`（无页面级水平溢出）；
- 六态渲染正确；
- 控制台无 error/warning；
- 正常重载无 4xx/5xx；
- **Figma fixture 零泄漏**：`REV-1500`–`REV-1510`、`User-1`–`User-3`、
  `Reviewer-1`/`Reviewer-2`、`Q-1300`–`Q-1309`、`RUN-1400`–`RUN-1409`、
  `184`、`169`、`Pending 7`、`Approved Research 6`、`Rejected 4`。

- [ ] **Step 12: 全量验证并提交（分四个 commit）**

四个独立可验证行为：cursor/聚合、API/migration、Monitoring 六页、治理五页。

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
npm --prefix frontend test -- --run && npm --prefix frontend run lint
npm --prefix frontend run build
git diff --check

cd .. && git add platform/src/a_share_platform/application/monitoring_workspace.py \
  platform/src/a_share_platform/application/governance_workspace.py \
  platform/tests/test_cursor_pagination.py \
  platform/tests/test_monitoring_workspace_projection.py \
  platform/tests/test_governance_workspace_projection.py
git commit -m "feat: add cursor pagination and server-side aggregation for the monitoring ledgers

Offset pagination is wrong here for a specific reason rather than a general one.
The incident and drift ledgers are append-only and written continuously — thirteen
metrics per subject per run — so a row inserted between two page requests shifts
every later offset and page two either repeats a row or skips one.  Skipping is the
dangerous half: the skipped row is an incident nobody saw.  A test asserts exactly
that scenario, and it fails by omitting one row under OFFSET.

The cursor is opaque and a tampered one raises rather than resetting to page one,
because a client that receives page one when it asked for page five will loop.  The
sort key is total — timestamp plus id — since two incidents sharing a timestamp
would otherwise make the cursor position ambiguous.

Aggregation is server-side and the reason is not performance.  If the browser
counts open incidents then 'how many are open' has two answers, and they diverge
the moment pagination, filtering or a stale cache is involved.  The summary covers
the whole ledger rather than the current page: a page-scoped summary always reports
the page size and changes as the user pages, which is worse than being merely
wrong.  Severity ordering is server-owned too, since a locale-dependent client sort
can place a critical below a warning.

Users and Entitlements report unavailable with the real reason.  No identity
provider is configured, so the runtime has one principal — anonymous with
read_public — and SPEC-049 forbids dressing a local string up as authentication.
The entitlement matrix is read from PermissionPolicy.default() rather than restated
in the projection, because a restated matrix is a second source of truth for who
may approve what.

Blocked stays a queue state rather than becoming ApprovalDecision.BLOCKED.  The
prototype draws four statuses against three decisions, and the fourth means
'evidence incomplete so no decision may be made'.  Making it a decision value would
collapse 'the system refused' into 'a person refused', and only one of those is
someone's judgement."
```

（其余三个 commit 的 message 在执行时按同样标准写：解释为什么，不写要点墙。）

---

### Task 6: 故障注入与 Gate Evidence

对应 Step 08 Task 6：「注入 stale dataset、feature shift、IC decay、calibration drift、
cost deviation、citation failure、job failure；核对 Alert/Incident/Review/rollback 行为和 Evidence。」

**这个 Task 是必需的，不是可选的收尾。** 一个从未针对真实故障测试过的监控系统是装饰品：
它的每个单元测试都能绿，因为单元测试用的是为该断言构造的输入；
而真实故障走的是完整链路——provider → sink → dataset → feature → factor → model →
portfolio → alert → incident → owner → review。链路上任何一处没接上，
单元测试都发现不了，而故障发生时监控会安静地什么都不做。

七类故障对应 ADR-0009 的四个 owner scope，因此这个 Task 同时是 **owner 路由的端到端验证**。

**Files:**
- Create: `platform/src/a_share_platform/workers/fault_injection.py`
- Create: `platform/src/a_share_platform/workers/drift_monitoring.py`
- Test: `platform/tests/test_fault_injection.py`
- Test: `platform/tests/test_drift_monitoring_worker.py`
- Create: `docs/28-p8-monitoring-governance-evidence.md`
- Modify: `docs/plans/step-08-p9-monitoring-governance.md`（六个 Task 真实状态）
- Modify: `docs/plans/track-00-prototype-runtime-delivery.md`（PUI-08 三轴结论）
- Modify: `docs/22-prototype-runtime-gap-audit.md`（**追加增量节，不改写原 §5 矩阵**）

- [ ] **Step 1: 注入器的安全约束（红测先行）**

**故障注入器是本仓库最危险的一个 worker。** 它的职责是往库里写坏数据。
因此它的守卫必须比任何其他 worker 更严。

```python
# platform/tests/test_fault_injection.py
"""The fault injector writes bad data on purpose, so it needs the strictest guards
in the repository.

Three of them are unique to this worker.  It refuses any deployment stage other
than research, because injecting a stale dataset into a shadow or paper ledger
would corrupt evidence that cannot be reconstructed.  It marks every record it
writes with an injection run id, so no injected fault can ever be mistaken for a
real one in an evidence document.  And it refuses to run at all against a
non-loopback database, following the pattern in workers/timing_baseline.py.
"""

from __future__ import annotations

import unittest

from a_share_platform.workers import fault_injection


class SafetyGuardTest(unittest.TestCase):
    def test_dry_run_is_the_default(self) -> None:
        code = fault_injection.main([
            "--fault", "stale_dataset",
            "--database-url", "postgresql://user:pw@127.0.0.1:55432/db",
            "--code-version", "git:test",
        ])
        self.assertEqual(code, 0)

    def test_execute_without_ack_is_blocked(self) -> None:
        code = fault_injection.main([
            "--fault", "stale_dataset",
            "--database-url", "postgresql://user:pw@127.0.0.1:55432/db",
            "--code-version", "git:test", "--execute",
        ])
        self.assertEqual(code, 2)

    def test_a_non_loopback_database_is_blocked(self) -> None:
        code = fault_injection.main([
            "--fault", "stale_dataset",
            "--database-url", "postgresql://user:pw@db.example.com:5432/db",
            "--code-version", "git:test",
            "--private-local-research-ack", "--execute",
        ])
        self.assertEqual(code, 2)

    def test_any_stage_other_than_research_is_blocked(self) -> None:
        """The guard specific to this worker.

        Injecting a stale dataset into a shadow ledger corrupts forward evidence,
        and forward evidence cannot be reconstructed — it has to be waited for
        again.
        """
        for stage in ("shadow", "paper", "limited_live"):
            with self.subTest(stage=stage):
                code = fault_injection.main([
                    "--fault", "stale_dataset", "--deployment-stage", stage,
                    "--database-url", "postgresql://user:pw@127.0.0.1:55432/db",
                    "--code-version", "git:test",
                    "--private-local-research-ack", "--execute",
                ])
                self.assertEqual(code, 2)

    def test_every_injected_record_carries_an_injection_run_id(self) -> None:
        """So an injected fault can never be quoted as a real one in an evidence
        document, and so cleanup can find every row it wrote."""
        plan = fault_injection.plan_injection(
            fault="stale_dataset",
            injection_run_id="injection:2026-08-16:0001",
            code_version="git:test",
        )
        self.assertTrue(plan.records)
        for record in plan.records:
            with self.subTest(record=record.record_id):
                self.assertEqual(
                    record.injection_run_id, "injection:2026-08-16:0001"
                )
        with self.assertRaises(ValueError):
            fault_injection.plan_injection(
                fault="stale_dataset",
                injection_run_id="   ",
                code_version="git:test",
            )

    def test_an_unknown_fault_kind_is_refused(self) -> None:
        code = fault_injection.main([
            "--fault", "delete_production_factor",
            "--database-url", "postgresql://user:pw@127.0.0.1:55432/db",
            "--code-version", "git:test",
        ])
        self.assertEqual(code, 2)
        self.assertEqual(
            fault_injection.FAULT_KINDS,
            ("stale_dataset", "feature_shift", "ic_decay", "calibration_drift",
             "cost_deviation", "citation_failure", "job_failure",
             "attribution_residual_breach"),
        )
        # Step 08 names seven; the eighth is required by its own residual rule
        # (Task 1 Step 8), so it is declared here rather than left implicit.
        self.assertEqual(len(fault_injection.FAULT_KINDS), 8)

    def test_the_injector_cannot_write_an_approval_or_a_serving_registration(
        self,
    ) -> None:
        """It injects faults, not authorisations.  A tool that can write an
        approval is a tool that can promote a model."""
        import inspect

        source = inspect.getsource(fault_injection)
        for forbidden in (
            "approval_reviews", "serving_registrations", "ApprovalReview",
            "ServingRegistration", "ApprovalService", "ServingRegistry",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        for fault in fault_injection.FAULT_KINDS:
            with self.subTest(fault=fault):
                plan = fault_injection.plan_injection(
                    fault=fault,
                    injection_run_id="injection:2026-08-16:0001",
                    code_version="git:test",
                )
                for record in plan.records:
                    self.assertNotIn("approval", record.target_table)
                    self.assertNotIn("serving", record.target_table)
```

- [ ] **Step 2: 运行确认红测 → 实现守卫 → 转绿**

CLI 形状照 `workers/timing_baseline.py`：`blockers` 列表、
`_postgres_endpoint_is_private_local()`、`writes_performed`、JSON 输出、退出码 0/1/2。

- [ ] **Step 3: 七类故障逐一注入并核对（每类一个红测）**

**每一类都必须验证四件事**：Alert 是否产生、severity 是否正确、
**owner 是否路由到 ADR-0009 的正确 scope**、以及 Incident/Review/rollback 行为。

```python
# 同一文件 platform/tests/test_fault_injection.py 的第二组
from decimal import Decimal

from a_share_platform.domain.incidents import AlertAction, AlertSource, IncidentState
from a_share_platform.domain.monitoring import DriftMetric, DriftSeverity


def _inject_and_run(fault: str, *, count: int = 1):
    """Inject one fault into an in-memory research-stage stack and run monitoring.

    Returns a result object carrying the alert, the incident, the incident list and
    the before/after hashes of every governed object, so each test below can assert
    the whole chain — provider → observation → alert → incident → owner — rather
    than one link of it.
    """
    return fault_injection.inject_and_monitor(
        fault=fault,
        count=count,
        injection_run_id=f"injection:2026-08-16:{fault}",
        code_version="git:test",
        deployment_stage="research",
    )


def _inject_all():
    return fault_injection.inject_and_monitor_all(
        injection_run_id="injection:2026-08-16:all",
        code_version="git:test",
        deployment_stage="research",
    )


class FaultRoutingTest(unittest.TestCase):
    """Seven faults, four owner scopes.  This is the end-to-end verification of
    ADR-0009's routing, which the unit tests can only check one link at a time.
    """

    def test_stale_dataset_routes_to_data_owner(self) -> None:
        """Freshness lag beyond the policy.  ADR-0009: 来源、摄取、映射、coverage、
        freshness、PIT 和 lineage 归 data."""
        result = _inject_and_run("stale_dataset")
        self.assertEqual(result.incident.primary_owner_scope, "data")
        self.assertEqual(result.alert.metric, DriftMetric.FRESHNESS)
        self.assertTrue(result.alert.runbook_id)

    def test_feature_shift_routes_to_research_owner(self) -> None:
        """PSI above the major threshold.  ADR-0009: feature/factor/model/View/
        Timing/Event/Agent 和科学验证 归 research."""
        result = _inject_and_run("feature_shift")
        self.assertEqual(result.incident.primary_owner_scope, "research")
        self.assertEqual(result.alert.metric, DriftMetric.FEATURE_DISTRIBUTION_PSI)
        self.assertIn(result.alert.severity, (DriftSeverity.MAJOR, DriftSeverity.CRITICAL))
        self.assertGreater(result.observation.observed_value, Decimal("0.25"))
        self.assertTrue(result.alert.runbook_id)

    def test_ic_decay_routes_to_research_owner_and_requests_review(self) -> None:
        """The action must be REQUEST_REVIEW, never a weight change.  This is the
        end-to-end version of Task 2 Step 9's structural assertion."""
        result = _inject_and_run("ic_decay")
        self.assertIn(AlertAction.REQUEST_REVIEW, result.alert.permitted_actions)
        self.assertNotIn("adjust", str(result.alert.permitted_actions).lower())
        self.assertEqual(result.factor_version_hash_before,
                         result.factor_version_hash_after)

    def test_calibration_drift_routes_to_research_and_leaves_timing_impact_zero(
        self,
    ) -> None:
        """A drifting Shadow timing model must not change portfolio exposure, and
        it must not be silently recalibrated either."""
        result = _inject_and_run("calibration_drift")
        self.assertEqual(result.incident.primary_owner_scope, "research")
        self.assertEqual(result.alert.metric, DriftMetric.CALIBRATION_BRIER)
        # ADR-0006 decision 7: Shadow timing's portfolio impact is fixed at zero.
        self.assertEqual(result.timing_portfolio_impact_ratio, Decimal(0))
        self.assertEqual(result.timing_model_hash_before, result.timing_model_hash_after)
        self.assertNotIn(
            AlertAction.EXECUTE_APPROVED_ROLLBACK, result.alert.permitted_actions
        )

    def test_cost_deviation_routes_to_portfolio_owner(self) -> None:
        """ADR-0009: policy、target、risk、capacity、backtest 和非执行归因 归
        portfolio."""
        result = _inject_and_run("cost_deviation")
        self.assertEqual(result.incident.primary_owner_scope, "portfolio")
        self.assertEqual(result.alert.metric, DriftMetric.TURNOVER_COST)
        self.assertEqual(
            result.target_portfolio_hash_before, result.target_portfolio_hash_after
        )

    def test_citation_failure_routes_to_research_and_quarantines_the_agent_output(
        self,
    ) -> None:
        """P8 already quarantines uncited agent output.  Here the monitoring half
        is verified: the quarantine also raises an alert, because a silent
        quarantine means nobody learns the agent is failing."""
        result = _inject_and_run("citation_failure")
        self.assertEqual(result.incident.primary_owner_scope, "research")
        self.assertEqual(result.alert.metric, DriftMetric.AGENT_CITATION_RATE)
        self.assertTrue(result.agent_output_quarantined)
        self.assertIsNotNone(result.alert)

    def test_job_failure_routes_to_data_owner_and_dedupes(self) -> None:
        """Inject 500 job failures from one provider limit.  One incident,
        occurrence count 500, and the desk shows both numbers."""
        result = _inject_and_run("job_failure", count=500)
        self.assertEqual(len(result.incidents), 1)
        self.assertEqual(result.incidents[0].alerts[-1].occurrence_count, 500)

    def test_a_cross_domain_fault_names_one_primary_and_lists_contributors(
        self,
    ) -> None:
        """Stale dataset breaking a factor: data is primary, research contributes.
        Two primaries means neither acts."""
        result = _inject_and_run("stale_dataset")
        incident = result.incident
        self.assertEqual(incident.primary_owner_scope, "data")
        self.assertIn("research", incident.contributor_owner_scopes)
        self.assertNotIn("data", incident.contributor_owner_scopes)
        self.assertIsInstance(incident.primary_owner_scope, str)

    def test_an_attribution_residual_breach_creates_a_portfolio_incident(self) -> None:
        """The eighth injection, not in Step 08's list but required by its own
        residual rule.  This closes the loop Task 1 Step 8 left open as a value."""
        result = _inject_and_run("attribution_residual_breach")
        self.assertEqual(result.incident.primary_owner_scope, "portfolio")
        self.assertEqual(result.alert.source, AlertSource.ATTRIBUTION_CLOSURE)
        self.assertIs(result.incident.state, IncidentState.OPEN)
        # The residual is not absorbed into a component.
        self.assertNotIn("other", {c.name for c in result.attribution.components})
        self.assertGreater(result.attribution.residual, result.attribution_tolerance)

    def test_no_injected_fault_changed_any_model_or_target(self) -> None:
        """The single most important assertion in this file.

        After all seven injections, every FactorVersion, TimingModelVersion,
        TargetPortfolioSnapshot and ServingRegistration hash is unchanged.  If any
        moved, monitoring modified production, and every audit trail that points at
        an approved version has become a lie.
        """
        result = _inject_all()
        self.assertEqual(result.hashes_before, result.hashes_after)
```

- [ ] **Step 4: 监控 worker dry-run 与真实执行**

```bash
cd platform && source /tmp/asp_env.sh
# dry-run：打印计划的 subject × metric 矩阵与 blockers
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.drift_monitoring \
  --window-days 20 --database-url "$ASP_DATABASE_URL" \
  --code-version "git:$(git rev-parse --short HEAD)"

# 真实执行
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.drift_monitoring \
  --window-days 20 --database-url "$ASP_DATABASE_URL" \
  --code-version "git:$(git rev-parse --short HEAD)" \
  --private-local-research-ack --execute
```

Expected（当前数据下极可能）：大量 `UNAVAILABLE` 观测。
**这是正确输出**，不是失败——没有 PIT 数据、没有获批模型、没有真实组合，
十三个指标里能算的只有 coverage / freshness / job_failure_rate 三组。
**如实记录每个指标的真实状态。**

- [ ] **Step 5: 真实故障注入序列**

```bash
cd platform && source /tmp/asp_env.sh
for fault in stale_dataset feature_shift ic_decay calibration_drift \
             cost_deviation citation_failure job_failure; do
  PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.fault_injection \
    --fault "$fault" --deployment-stage research \
    --database-url "$ASP_DATABASE_URL" \
    --code-version "git:$(git rev-parse --short HEAD)" \
    --private-local-research-ack --execute
done
```

每一类都必须记录：注入内容、产生的 Alert、severity、routed owner、
Incident id 与状态、采取的 action、以及**注入前后所有模型/组合 hash 的对比**。

**若某一类故障没有产生 Alert，这是链路缺陷，必须查清并修复，不得写成「该指标不适用」。**

- [ ] **Step 6: 注入数据清理并验证清理彻底**

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.fault_injection \
  --cleanup --injection-run-id <真实 id> \
  --database-url "$ASP_DATABASE_URL" \
  --private-local-research-ack --execute
```

**清理必须只删注入的行，不删由注入产生的 Incident。**
Incident 是真实发生的记录（虽然起因是人为的），删除它会违反 append-only。
正确做法：Incident 保留，并携带 `injection_run_id` 标记，
Evidence 里明确写「这 N 个 Incident 由故障注入产生，不代表真实故障」。

- [ ] **Step 7: 写 Evidence，八节结构**

`docs/28-p8-monitoring-governance-evidence.md`：

```markdown
## 1. 红绿测记录（含 Task 2 → Task 3 的跨 Task 红→绿）
## 2. 统一归因真实闭合结果（daily / cumulative / 两层，逐项）
## 3. 十三个漂移指标的真实状态（可算 / unavailable，逐个说明原因）
## 4. 七类故障注入结果（注入内容 → Alert → severity → owner → Incident → action）
## 5. 注入前后模型与组合 hash 对比（必须全部相同）
## 6. 审批泛化的权限矩阵实测（8 角色 × 6 subject kind 的允许/拒绝表）
## 7. 十一页三轴状态与与原型的已知差异
## 8. 明确否认
```

第 5 节是本 Evidence 最重要的一节。它是「监控没有改模型」的**唯一实证**。

第 6 节要给出完整的 48 格（8 × 6）实测表，每格是 `allowed` / `denied`。
**这张表就是治理边界的可审计快照。**

- [ ] **Step 8: 十一页三轴状态登记**

```text
                          design_status   runtime_status   capability_status
Monitoring / Signals      missing         verified         <按实际>
Monitoring / Portfolios   missing         verified         <按实际>
Monitoring / Timing       missing         verified         <按实际>
                          （node 9:431 属 PUI-06，本 plan 不重复 parity）
Monitoring / Drift        missing         verified         <按实际>
Monitoring / Rebalance    missing         verified         <按实际>
Monitoring / Incidents    missing         verified         <按实际>
Monitoring / Execution    missing         placeholder      blocked（P10）
Factors / Correlation     missing         verified         <按实际>
Factors / Production      missing         verified         <按实际>
System / Users            missing         verified         blocked（无 IdP）
System / Entitlements     missing         verified         <按实际>
System / Approvals        parity_verified_with_known_deviation  verified  <按实际>
                          （node 9:883，1440 逐区对照）
```

**十一页中只有 Approvals 有精确 Frame。** 其余十页 `design_status` **必须写 `missing`**——
P-4 已立此规：没有 Frame 就不能声称 parity。

Approvals 也**不得**写 `ready`：summary JSON 在第 4 层截断为 `children_count`
且无 `layoutMode`/`itemSpacing`，列宽只能从 SVG 坐标推断。推断不是 parity。

- [ ] **Step 9: 逐条记录与原型的已知差异**

至少六条：

```text
1. 侧栏 280 px（运行时，SPEC-045）vs 224 px（node 9:883 的 Vector w=224）
   → 内容区 1160 vs 1216，已批准差异（P-4 plan 已登记，不得改回）
2. node 9:883 的四个摘要卡数字（7/6/4/0）与 8 列表格 11 行全部是 design fixture
   → 运行时按真实队列渲染，空队列显示 empty
3. 原型状态第四值 Blocked 不是 ApprovalDecision 值
   → 运行时作为队列状态（pending + evidence_incomplete）
4. 原型无「过期」与「被取代」状态
   → 运行时新增两个显示状态，因为 Step 08 Spec 要求 expiry 与 supersedes
5. 原型的 Reviewer 列有 Unassigned 值，暗示分派功能
   → 本 plan 不实现分派；无 identity provider 时该列显示真实的「无」
6. Monitoring 六页与 Correlation/Production/Users/Entitlements 无独立 Frame
   → 信息架构按 docs/18 §3.5 与 §3.6 的表推导，设计假设逐条记录在 Evidence
```

- [ ] **Step 10: 写明确否认声明（必须逐字包含）**

> 本 plan 交付**统一归因、漂移监控、Alert/Incident 状态机、泛化审批与 serving 注册的
> 工程实现**，以及 **PUI-08 的十一个产品页**。它**不代表**：
>
> - **P9 Gate 通过** —— Gate 要求「每日和累计归因闭合」，而闭合需要真实组合与真实执行；
>   `execution` 分项在 Paper 前恒为 `not_applicable`，因此完整的统一归因验收
>   **在 P10 之前不可能通过**；
> - P2、P4、P5、P6、P7 或 P8 任何 Gate 通过 —— 本 plan 不改变其中任何一条；
> - 任何因子、模型或策略科学有效 —— 监控能力与模型有效性无关；
>   一个完全无效的模型也可以被完美监控；
> - **平台 Paper-ready** —— OMS、订单、成交、持仓、现金、对账与 kill switch 全属 P10。
>   本 plan 的 Incident 状态机是研究运营工具，**不是**交易事故响应系统；
>   `execution` owner scope 已在 ADR-0009 中定义但**没有任何真实 execution 事件可路由**；
> - 故障注入通过等于生产可靠 —— 注入的是七类**已知**故障。
>   一个监控系统对已知故障全绿，对未预见的故障仍可能完全静默；
> - 有真实身份系统 —— 无 identity provider，运行时唯一 principal 是
>   `Principal.anonymous()`（仅 `read_public`）。因此**职责分离在生产中尚未被真人验证**：
>   它有测试，但没有两个真实用户；
> - 阈值已被批准 —— `ThresholdPolicy` 的具体数值（PSI 0.10/0.25/0.40 等）
>   是**工程默认值**，需用户批准后才是生产阈值。Step 08 决策明确要求
>   「retention 和通知渠道必须在部署前批准」；
> - 通知渠道就绪 —— 本 plan **不实现任何通知发送**。
>
> 本 plan 产出的 `ServingRegistration` 只在 `research_backtest` 与（若 P-6/P-7 已批准）
> `shadow` scope 内有效。**`paper` 与 `limited_live` scope 的注册被服务层拒绝。**
>
> **P9 完成不代表平台 Paper-ready。** 这两件事之间隔着整个 P10：
> OrderIntent 与 Order 的区别、确定性 Paper Broker、持仓与现金对账、
> ReconciliationBreak、kill switch 与恢复演练。本 plan 一个都没做。

- [ ] **Step 11: 更新冻结 Plan 与 Track 的真实状态**

`docs/plans/step-08-p9-monitoring-governance.md`：状态从 `dependency_blocked` 改为
**按实际** `in_progress` 或 `capability_complete_gate_blocked`。
**不得改为 Gate 通过** —— Spec 验收要求「每日和累计归因闭合」，
而 `execution` 分项在 Paper 前恒为 `not_applicable`。

`docs/plans/track-00-prototype-runtime-delivery.md`：PUI-08 状态与三轴结论表。

`docs/22-prototype-runtime-gap-audit.md`：**追加**「2026-08-16 PUI-08 完成后的增量更新」，
原 §5 矩阵（第 10、11、17–23、25–29、31 行）**保留不改** —— 它记录审计时点事实。

- [ ] **Step 12: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
npm --prefix frontend test -- --run
npm --prefix frontend run lint
npm --prefix frontend run build
.venv/bin/python scripts/verify_monitoring_browser.py
git diff --check
cd .. && git add platform/src/a_share_platform/workers/fault_injection.py \
  platform/src/a_share_platform/workers/drift_monitoring.py \
  platform/tests/test_fault_injection.py \
  platform/tests/test_drift_monitoring_worker.py \
  docs/28-p8-monitoring-governance-evidence.md \
  docs/plans/step-08-p9-monitoring-governance.md \
  docs/plans/track-00-prototype-runtime-delivery.md \
  docs/22-prototype-runtime-gap-audit.md
git commit -m "test: inject seven real faults and verify the monitoring chain actually fires

A monitoring system never tested against real faults is decoration.  Every unit
test in this plan passes on inputs constructed for its own assertion, while a real
fault travels the whole chain — provider, sink, dataset, feature, factor, model,
portfolio, alert, incident, owner, review.  Any missing link is invisible to unit
tests and silent when the fault arrives.

The seven faults cover ADR-0009's four owner scopes, so this is also the only
end-to-end verification of routing: a stale dataset lands on data, a feature shift
and an IC decay on research, a cost deviation on portfolio, and a cross-domain
fault names one primary with contributors rather than two primaries, since two
primaries means neither acts.

The most important assertion compares every FactorVersion, TimingModelVersion,
TargetPortfolioSnapshot and ServingRegistration hash before and after all seven
injections.  If any of them moved, monitoring modified production, and every audit
trail pointing at an approved version has become a lie.  The IC-decay case asserts
the same thing at the level of the individual alert: the permitted action is
request-review, and the factor hash is byte-identical afterwards.

The injector itself needed the strictest guards in the repository, because its job
is writing bad data.  It refuses any deployment stage other than research —
injecting into a shadow ledger corrupts forward evidence, which cannot be rebuilt,
only waited for again — it stamps every row with an injection run id so no injected
fault can be quoted as a real one, and it cannot write an approval or a serving
registration at all, since a tool that can write an approval can promote a model.

Cleanup removes the injected rows and deliberately keeps the incidents they
produced.  Those incidents really happened, and deleting them would break
append-only; they carry the injection run id and the evidence says plainly that
they are synthetic.

Most of the thirteen drift metrics report unavailable on the current data, and that
is the correct output rather than a failure: with no PIT inputs, no promoted model
and no real portfolio, only coverage, freshness and job failure rate can be
computed.  The evidence records each metric's real state instead of implying
thirteen green checks.

The denial section states that P9 completion does not make the platform
Paper-ready.  Between the two sits the whole of P10: the distinction between an
OrderIntent and an Order, a deterministic paper broker, position and cash
reconciliation, ReconciliationBreak, a kill switch and a recovery drill.  None of
that is in this plan.  It also states that separation of duties has tests but no
two real users, because no identity provider is configured and the runtime's only
principal is anonymous with read_public."
```

---

## 完成定义

1. `UnifiedAttribution` 八分项无 catch-all；residual 是独立字段且带证据；
   `execution` 恒为 `not_applicable`（不是 0，不是 `unavailable`）；
   daily 闭合先于 cumulative；两层归因分离且各自独立闭合（Task 1）；
2. residual 超容差产生 `AttributionClosureBreach`，含 `owner_scope == "portfolio"`
   与 `threshold_policy_hash`（Task 1）；
3. `ThresholdPolicy` content-addressed，改任一阈值或升级时限均产生新 hash；
   无批准人的 policy 不可构造；不同 policy 的观测比较时 raise（Task 2）；
4. 十三个漂移指标各自有正常/越界/缺失/样本不足四类测试，owner 路由正确；
   `UNAVAILABLE` 不等于 `WITHIN_THRESHOLD`；PSI 空 bin 拒绝而非补 epsilon；
   coverage 分母是 expected 而非 present（Task 2）；
5. drift alert 无法改 `FactorVersion` 或 `TargetPortfolioSnapshot`；
   `AlertAction` 恰好三值；calculator 签名不含 repository/session/connection（Task 2）；
6. `dedupe_key` 由 `(subject_id, subject_version, metric, owner_scope)` 派生，
   是 64 位 sha256（进程间稳定）；500 次触发 → 1 个 Incident + `occurrence_count == 500`；
   `first_seen_at` 永不移动（Task 3）；
7. Incident 六态、全部合法转移各一测试、全部非法转移断言拒绝；
   `CLOSED` 终态；reopen 保留完整历史且 `reopen_count` 单调递增；
   被拒转移记入审计（Task 3）；
8. **提交人不能批准**：Reviewer、Administrator 自批与自拒全部拒绝，且拒绝被记账（Task 4）；
9. `Role.AGENT` 对全部 6 个 subject kind 拒绝；**含 REVIEWER 的混合 principal 仍拒绝**；
   `Permission` 枚举未新增值；`PermissionPolicy.default()` 的 grants 逐行断言未变（Task 4）；
10. 过期审批不授权（边界含自身瞬间）；被取代审批不授权；版本 hash 变化不授权；
    `PromotionApproval.authorizes()` **未被回改**（Task 4）；
11. `ServingRegistration` 单 scope 无重叠；rollback target 必须是已批准注册；
    `paper` / `limited_live` scope 被拒；suspend/retire 是审计转移而非删除（Task 4）；
12. 两个 P9 blocker code 因真实实现而消失：`P9_INCIDENT_LEDGER_NOT_IMPLEMENTED`（Task 3）、
    `P9_GENERAL_APPROVAL_QUEUE_NOT_IMPLEMENTED`（Task 4）；
    desk `coverage` 同时保留原始失败计数与 Incident 计数（Task 3）；
13. cursor pagination：插入不跳行、cursor 不可读、篡改 raise、sort key 全序、
    total 与 rows 分离（Task 5）；
14. 服务端聚合：summary 覆盖全账本而非当前页；severity 排序服务端；
    前端零聚合（Task 5）；
15. 三个 migration 空库 + 幂等通过；append-only trigger 在数据库层拒绝 UPDATE/DELETE；
    单 dedupe_key 单 open incident 由唯一索引强制；`unavailable` 带数值被约束拒绝（Task 5）；
16. 十一页复用 `WorkspaceState` 六态；`verify_monitoring_browser.py` 44 个检查点
    （11 页 × 4 视口）全过；无页面级溢出；Figma fixture 零泄漏；
    Rebalance 页无下单按钮；Correlation 页无改权重操作（Task 5）；
17. 七类故障全部注入并核对 Alert/severity/owner/Incident/action；
    **注入前后所有模型与组合 hash 相同**（Task 6）；
18. 注入器拒绝非 research stage、非 loopback DSN、无 ack；不能写 approval 或
    serving registration；每行带 `injection_run_id`（Task 6）；
19. Evidence 八节含 48 格权限实测表、十三指标真实状态、hash 对比与明确否认（Task 6）；
20. 后端 unittest / compileall / ruff / mypy 全过；前端 Vitest / lint / build 全过；
    `git diff --check` 干净；一个 Task 一个独立提交（Task 4 两个、Task 5 四个）。

## 明确不在本 plan 范围

- **OMS、订单、成交、持仓现金对账、kill switch、恢复演练** —— 属 P10 / SPEC-036–038、055；
  Monitoring/Execution 页保持阶段 blocker；
- **真实 execution 归因** —— 需真实执行事件，`execution` 分项恒 `not_applicable`；
- **通知发送（邮件/IM/webhook）** —— Step 08 决策要求「通知渠道必须在部署前批准」，
  未批准；本 plan 只产生 Incident，不发送；
- **真实身份提供者、MFA、session 管理** —— 需外部 IdP 与用户批准；
  System/Users 页保持 `unavailable`；
- **Entitlement 写操作** —— 需 IdP 与审批路径，两者都不存在；
- **审批分派（Reviewer assignment）** —— 原型的 `Unassigned` 暗示此功能，本 plan 不做；
- **`FactorPromotionReview` 迁移到通用合同** —— 两条路径并行存在，迁移属后续工作；
- **`PromotionApproval.authorizes()` 加 expiry/supersede** —— 会追溯失效 P4 既有记录；
- **`paper` / `limited_live` 的 ServingRegistration** —— 前者需 P10，后者需 P11 新授权；
- **阈值数值的生产批准** —— 本 plan 的数值是工程默认值，需用户批准；
- **Risk R1/R2 的漂移监控** —— SPEC-032 分级，只有 R0 存在；
- **截图 diff 工具** —— 需用户先批准基线与容差；
- **`strict_historical` 监控** —— 需 `pit_verified` 数据。

## 本 plan 完成后仍然成立的限制

- **P9 Gate 未通过。** Gate 要求「每日和累计归因闭合」，而完整的统一归因含 `execution`；
  `execution` 在 Paper 之前恒为 `not_applicable`，因此**完整验收在 P10 之前不可能通过**。
  可通过的部分是 core + timing + event 的闭合；
- P2、P4、P5、P6、P7、P8 全部 Gate **不因本 plan 改变**；
- 十三个漂移指标中**多数在当前数据上报 `UNAVAILABLE`** ——
  没有 PIT 数据、没有获批模型、没有真实组合。这是被验收的状态，不是缺陷；
- **职责分离有测试但没有两个真实用户** —— 无 identity provider，
  运行时唯一 principal 是 `Principal.anonymous()`（仅 `read_public`）。
  因此 SoD 在生产中尚未被真人验证；
- **阈值数值是工程默认值，不是已批准的生产阈值**；
- **通知渠道不存在** —— Incident 产生后不会通知任何人；
- 十一页中**十页 `design_status` 保持 `missing`** —— 无独立高保真 Frame；
  Approvals 一页为 `parity_verified_with_known_deviation`，**不是 `ready`**；
  31 页完全逐像素 parity 计数**仍为 0/31**；
- 侧栏 280 px 使 1440 内容区为 1160 px 而非 node `9:883` 的 1216 px，属已批准差异；
- Vite 的 AntD large-chunk warning 仍然存在，**不得隐藏也不得写成已修复**；
- **故障注入只覆盖七类已知故障** —— 对未预见的故障，监控仍可能完全静默；
- **P9 完成不代表 Paper-ready，更不代表可实盘。** P10 是独立工作，
  P11 需用户新的明确授权。本 plan **不授权**任何真实账户操作。
