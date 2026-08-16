# P-9 Paper OMS 与执行闭环 P10 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从零建立 OMS 领域核心（`OrderIntent` / `Order` / `Fill` / `PositionLot` / `CashLedger` / `ReconciliationBreak` / `KillSwitchState`）、pre-trade risk 与职责分离审批、ADR-0010 冻结的确定性内部 Paper Broker、T+1 持仓与现金账本、日终对账与 break 队列、replay/恢复/soak 演练，并按 PUI-09 交付 Paper preview / orders / fills / positions / cash / breaks / kill switch 七个执行产品面。

**Architecture:** 本 plan **几乎全部从零新建**。2026-08-16 逐文件核实：`domain/oms.py`、`application/order_intents.py`、`ports/broker.py`、`adapters/paper/` **全部不存在**；`grep -rln "OrderIntent\|KillSwitch\|ReconciliationBreak\|CashLedger\|PositionLot\|kill_switch" src tests` 返回 **0 行**。因此订单、成交、持仓、现金、对账、break 与 kill switch 在当前代码里**完全没有任何实现**。已存在且本 plan 只消费不改写的输入合同是：`domain/market_data.py`（`DailyBar` / `DailyMarketState` / `PriceLimit` / `PriceLimitStatus` / `CorporateAction` / `ExchangeCalendar` / `CalendarDay`）、`domain/signals.py`（`SignalSnapshot`）、`domain/run_context.py`（`RunContext` / `DataMode` / `DeploymentStage`）、`application/permissions.py`（8 角色 × 8 权限矩阵，**原样保留，不加第 9 个权限**）、P-5 的 `domain/execution_rules.py` 与 `domain/portfolio.py`、P-8 的 `domain/approvals.py` 与 `domain/incidents.py`。worker 的 dry-run/ack 模板照抄 `workers/timing_baseline.py`。

**Tech Stack:** Python 3.11+（本机 3.12.12）、Decimal 全程（价格/金额/费用）、`int` 全程（股数，A 股无碎股）、PostgreSQL 17（端口 55432，append-only trigger + 唯一索引强制幂等）、React 19 + TypeScript 5.8 + Vite 7 + AntD 6、Vitest 3、Playwright（Chrome channel）

## Global Constraints

继承 `AGENTS.md`、`docs/07-detailed-system-spec.md`（SPEC-004、031、036–039、055–056、058）、
**ADR-0010（Accepted，2026-08-14，授权边界「仅 Paper；P11 继续不授权」）** 与
`docs/plans/step-09-p10-paper-oms.md` 的冻结 Spec，**每个 Task 都适用**：

- `domain/` 不导入 FastAPI / SQLAlchemy / psycopg / provider SDK / 前端概念
  （`tests/test_architecture_contract.py` 的 `forbidden_roots` 已强制）
- **不安装或导入任何真实交易 SDK，不保存任何账户凭证，不开放任何真实 order endpoint**
  （ADR-0010 决策 5）。`forbidden_roots` 已含 `futu`；本 plan **必须**再加入所有真实券商/交易
  SDK 根名，并新增一个测试断言 `platform/` 整个源码树内不存在任何交易 SDK import
- **命令幂等是本 plan 的第一属性**，不是优化。每个写命令都要 client 提供的 idempotency key，
  重复提交产生**同一个**对象而不是第二个（Step 09 Spec：「命令幂等」；SPEC-036 验收：
  「状态转换合法、幂等、防重复下单」）
- **非法状态转移必须拒绝并记账，不得容忍。** 已成交订单不可撤销，已拒绝订单不可成交
- **kill switch 在 intent 层阻断，不是隐藏按钮。** 前端隐藏不是权限（`docs/18` §3.6 逐字）
- **material reconciliation break 阻断新订单**，且**不得自动改数字**（SPEC-038 验收：
  「账不平时停止新的自动订单并产生 Incident，不允许用人工修改数字掩盖」）
- 金额一律 `Decimal` + ISO 4217 currency；股数一律 `int`；所有时间 timezone-aware
- **缺失、不可用、被阻断必须显式表达，禁止填零**
- **研究服务不能调用 Broker Adapter**（SPEC-037）。只有 Execution Application Service 在
  权限、风险与审批通过后才能发单；`Role.AGENT` 与 `Role.RESEARCHER` 在任何路径上都没有下单能力
- **职责分离**：提交 intent 的主体不能批准自己的 intent。`Role.TRADER` 有 `SEND_ORDER`
  但**没有** `APPROVE_PORTFOLIO`；这不是巧合，是 SoD 已经写在权限矩阵里
- 费用（佣金、最低佣金、印花税、过户费）**必须版本化**；改费率等于新版本（ADR-0006 决策 6）
- Order / Fill / PositionLot / CashLedgerEntry / ReconciliationBreak / KillSwitchState /
  BrokerEvent / 审计全部 append-only：重复写幂等，same ID / different semantics 冲突关闭，
  失败与被拒转移的记录不可删除或改写为成功
- 前端只消费服务端投影，**不在浏览器计算持仓、现金、盈亏、对账差额或 break 严重度**
- **全局始终显示 `deployment_stage=paper`；不存在请求参数、URL、header 或前端开关提升到 Live**
  （ADR-0010 决策 4）
- runtime 无默认 fixture；Figma 示例值零泄漏；测试 fixture 不得进入 runtime bundle
- worker 默认 dry-run，真实写入需 `--private-local-research-ack --execute`
- 未经用户明确授权不 commit、不 push

## ADR-0010 是本 plan 的宪法（Accepted，逐字引用）

`docs/adr/0010-deterministic-internal-paper-broker.md` 状态 `Accepted`、日期 2026-08-14、
授权边界「仅 Paper；P11 继续不授权」。**六条决策原文**如下，每个 Task 都回来对照：

> 1. P10 第一版使用确定性内部 Paper Broker adapter，不连接任何真实或券商模拟账户。
> 2. Paper/未来 Live 共享 Target、Intent、Risk、Approval、OMS、Position、Cash 和 Reconciliation 核心；broker adapter 独立。
> 3. Paper fill policy 复用 ADR-0006 的 session/VWAP/费用/公司行动版本，并支持 ack/reject/partial fill/delay/disconnect 的确定性故障 fixture。
> 4. 全局显式显示 `deployment_stage=paper`；不存在请求参数、URL、header 或前端开关提升到 Live。
> 5. 不安装或导入真实交易 SDK，不保存账户凭证，不开放真实 order endpoint。
> 6. P11 只有在新的明确授权和 Broker/Security ADR 后才能开始。

结果段原文：

> P10 可以在安全边界内完成连续 soak、恢复、replay、日终对账和执行归因。Paper 测试结果不构成真实交易授权或模型有效证据。

六条各自落在哪里，以及**哪个测试锁住它**：

| ADR 决策 | 落地位置 | 可执行断言 |
|---|---|---|
| 1 | `adapters/paper/broker.py`，无网络、无凭据、注入时钟 | `test_paper_broker_makes_no_network_call_and_holds_no_credential` |
| **2** | `domain/oms.py` 只依赖 `ports/broker.py` 抽象；`Order` 无 broker 字段 | `test_the_oms_core_does_not_import_any_broker_adapter` |
| 3 | `PaperFillPolicy` 消费 ADR-0006 的 `execution_price_policy_id` 与 `CostModel` | `test_fill_policy_hash_covers_the_adr_0006_versions` |
| **4** | API 固定 `paper_read_context()`；无 query/header/URL 提升路径 | `test_no_request_shape_can_promote_paper_to_limited_live` |
| **5** | `forbidden_roots` 扩展 + 全树 import 扫描 | `test_no_real_trading_sdk_is_imported_anywhere_in_the_platform` |
| 6 | `ApprovalScope.LIMITED_LIVE` 在本 plan 全部服务层被拒 | `test_limited_live_scope_is_refused_by_every_execution_service` |

决策 2 是最容易被违反的一条，因为它是「未来 Live 复用」的唯一保障：一旦 `Order` 上出现
`broker_order_id` 之外的 broker 特定字段，或 OMS 服务里出现 `if broker == "paper"`，
Paper 与 Live 就不再共享核心，而 P11 会变成重写而不是换 adapter。

## 前置条件（两条硬依赖，缺一不可）

### 依赖 P-8（监控治理 P9）—— 审批、Incident 与统一归因

三个具体接点，不是排序偏好：

1. **审批**：`OrderIntent` 的批准走 P-8 Task 4 的 `ApprovalReview` 与
   `ApprovalSubjectKind`，本 plan 只**新增一个 subject kind**（`ORDER_INTENT`），
   **不造第三套审批**。P-8 已经把 SoD（`ApprovalSubject.submitted_by`）、expiry
   （`expires_at`）与 supersede（`supersedes_review_id`）做进 `authorizes()`；
   本 plan 的 Trader-cannot-approve 测试建立在它之上。
   **没有 P-8，`ApprovalReview` 不存在，Task 2 的第一行写不出来。**
2. **Incident**：material reconciliation break 必须产生 Incident（SPEC-038 验收）。
   P-8 Task 3 的 `domain/incidents.py` 提供 `dedupe_key`、六态状态机与 owner scope 路由；
   ADR-0009 的四个 owner scope 里 `execution` 那一个在 P-8 完成时**已定义但无事件可路由**
   —— 本 plan 是它第一次有真实事件。
3. **统一归因**：P-8 Task 1 的 `UnifiedAttributionSnapshot` 的 `execution` 分项在 Paper
   之前恒为 `not_applicable`。本 plan 把它变成真实数值，这是 P9 Gate「每日和累计归因闭合」
   在 P-8 里**不可能通过**的那一项。

### 依赖 P-5（组合与回测 P6）—— 订单的来源与 A 股规则

**订单不能凭空产生。** `OrderIntent` 的唯一合法来源是已批准的
`TargetPortfolioSnapshot`（SPEC-036 的状态机第一行逐字就是
`TargetPortfolioSnapshot → OrderIntent`）。同时：

- `domain/execution_rules.py` 的 `ExecutionRuleSet` / `CostModel` / `OrderSide` /
  `BlockReason` / `FillStatus` / `SellableInventory` / `evaluate_eligibility()` /
  `cap_by_participation()` / `compute_costs()` 是 Paper fill policy 的**基础**，
  本 plan 消费不重写。**在 Paper 里第二次实现 T+1 或印花税，等于制造第二真源**；
- `PortfolioPolicy` 是 pre-trade risk 的限额来源（单股上限、行业上限、换手、参与率、现金）；
- `domain/backtest.py` 的 `InventoryState` 是 Paper `PositionLot` 的**设计参照**，
  但两者不是同一对象：回测的库存是模拟状态，Paper 的持仓是账本事实（见「陷阱五」）。

### 校验命令

```bash
cd platform && source /tmp/asp_env.sh
.venv/bin/python - <<'PY'
import os, psycopg
TABLES = (
    # P-5
    "research.target_portfolio_snapshots", "research.backtest_runs",
    "research.attribution_snapshots",
    # P-8
    "governance.approval_reviews", "governance.incidents",
    "governance.serving_registrations",
)
with psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True) as c:
    for t in TABLES:
        try:
            print(t, c.execute(f"select count(*) from {t}").fetchone()[0])
        except Exception as error:
            print(t, "MISSING:", type(error).__name__)
PY
cd platform
.venv/bin/python - <<'PY'
import importlib
for module in ("a_share_platform.domain.execution_rules",
               "a_share_platform.domain.portfolio",
               "a_share_platform.domain.approvals",
               "a_share_platform.domain.incidents"):
    try:
        importlib.import_module(module)
        print(module, "present")
    except ModuleNotFoundError as error:
        print(module, "MISSING:", error)
PY
```

**判断规则**：

- `domain/execution_rules.py` 缺失 → **停下来先做 P-5**。Task 3 的 fill policy 无从复用，
  在 Paper 里重写 A 股规则会制造第二真源。
- `domain/approvals.py` 缺失 → **停下来先做 P-8**。Task 2 无法开始。
- `domain/incidents.py` 缺失 → Task 4 的 break 只能产出 `ReconciliationBreak` 值对象，
  **不能**创建 Incident。可以继续（用 P-8 里那个「值对象先行，Incident 后接」的破解办法），
  但必须在 Evidence 写明 break→Incident 链未闭合。
- `research.target_portfolio_snapshots` 存在但计数为 0 → **Task 1–7 全部可做**
  （纯状态机与工程合同，用测试 fixture 驱动），只有真实 Paper soak 会在
  「无真实 target 可下单」处诚实停下。**这是允许且正确的结果。**

### 科学性与授权的前置声明（必须先读）

> **OMS 正确 ≠ 可以实盘。** 本 plan 产出的状态机、幂等、T+1、对账、kill switch 与 soak
> 全部是**软件与执行正确性证据**，不是策略有效性证据，**更不是真实交易授权**。
> ADR-0010 结果段原文：「Paper 测试结果不构成真实交易授权或模型有效证据」。
> P11 需要用户针对**券商、账户、市场、标的、单笔/单日金额、有效期和允许动作**的
> 新的明确授权（`docs/plans/step-10-p11-limited-live-readiness.md` 的「强制前提」）。

这决定了 Task 7 的验收标准：**soak 跑通就算过，盈亏数字好坏不算过也不算不过。**

## 已存在的接口（本 plan 消费，不重写）

经 2026-08-16 逐行核实的真实签名。**以代码为准；若实现与下文不同，改本 plan，不改代码去迁就 plan。**

### `application/permissions.py`（76 行，全部已实现）—— 本 plan 的权限基石

**8 个角色**（`Role(str, Enum)`）：`VIEWER` / `RESEARCHER` / `DATA_OPERATOR` / `REVIEWER` /
`PORTFOLIO_MANAGER` / `TRADER` / `ADMINISTRATOR` / `AGENT`。

**8 个权限**（`Permission(str, Enum)`）：`READ_PUBLIC` / `READ_ARTIFACT` /
`CREATE_EXPERIMENT` / `MANAGE_DATA` / `APPROVE_RESEARCH` / `APPROVE_PORTFOLIO` /
`SEND_ORDER` / `ADMINISTER`。

与本 plan 直接相关的**四行逐字**：

```text
Role.PORTFOLIO_MANAGER: read
| artifact_read
| {Permission.APPROVE_PORTFOLIO},
Role.TRADER: read | {Permission.SEND_ORDER},
Role.ADMINISTRATOR: frozenset(Permission),
Role.AGENT: read,
```

以及 `allows()` 的 anonymous 短路（逐字）：

```python
def allows(self, principal: Principal, permission: Permission | str) -> bool:
    try:
        requested = Permission(permission)
    except ValueError:
        return False
    if principal.subject_id == "anonymous":
        return requested is Permission.READ_PUBLIC
    return any(requested in self.grants.get(role, ()) for role in principal.roles)
```

**从这四行可以直接读出本 plan 最重要的四个治理事实，Task 2 全部要变成测试：**

1. **`Role.TRADER` 的完整权限集是 `{READ_PUBLIC, SEND_ORDER}`。**
   它**没有** `APPROVE_PORTFOLIO`，**没有** `APPROVE_RESEARCH`，甚至**没有**
   `READ_ARTIFACT`。所以「Trader 不能批准自己的 intent」**不是本 plan 发明的规则，
   它已经写在权限矩阵里了** —— Task 2 只是把它变成一个显式的、会失败的测试。
   一个只检查 `SEND_ORDER` 就放行的实现会通过 Trader 自批，因为 Trader 确实有 `SEND_ORDER`；
   审批门必须查 `APPROVE_PORTFOLIO`，那是 Trader 永远不会有的权限。
2. **`Role.PORTFOLIO_MANAGER` 有 `APPROVE_PORTFOLIO` 但没有 `SEND_ORDER`。**
   这是 SoD 的另一半：批准的人不能发单，发单的人不能批准。
   Step 09 Spec 逐字：「PM 提交 target，Reviewer/PM 按 policy 审批，Trader 处理 Paper order，
   Admin 管权限；同一主体不能越过 SoD」。
3. **`Role.AGENT` 只有 `READ_PUBLIC`。** 它没有 `READ_ARTIFACT`（连证据都读不到）、
   没有 `SEND_ORDER`、没有任何 approve 权限。Step 09 Spec 逐字：
   「Agent 和研究服务没有 order command 权限」。**Agent 完全没有执行路径**，
   而不是「有路径但会被拒」—— Task 2 与 Task 6 各有一个测试锁住这一点，
   因为给 Agent 加一行权限是一次单行改动。
4. **`Role.ADMINISTRATOR` 拿 `frozenset(Permission)` —— 全部 8 个，包括 `SEND_ORDER`
   和 `APPROVE_PORTFOLIO`。** 这是本 plan 最危险的一行：**Administrator 是唯一一个
   在权限矩阵层面能同时提交与批准同一个 intent 的角色。** 因此 SoD 不能只靠权限矩阵，
   必须在服务层比较 `submitted_by` 与 `actor_id`，且**对 Administrator 同样生效**。
   P-8 Task 4 已经为审批建了这条规则；本 plan 必须验证它在 `ORDER_INTENT` 上也成立。

**本 plan 不新增 `Permission` 枚举值，不改 `PermissionPolicy.default()`。**
理由与 P-8 相同：新增 `APPROVE_ORDER` 会让「谁能批准订单」变成两处真源。
Task 2 有一个测试逐行断言 `default()` 的 grants 未变。

### `domain/run_context.py`（56 行）—— 阶段隔离

```python
class DataMode(str, Enum):
    CURRENT_RESEARCH = "current_research"
    STRICT_HISTORICAL = "strict_historical"


class DeploymentStage(str, Enum):
    """Whether and how a run may affect an account."""

    RESEARCH = "research"
    SHADOW = "shadow"
    PAPER = "paper"
    LIMITED_LIVE = "limited_live"


_ALLOWED_STAGES_BY_DATA_MODE: dict[DataMode, frozenset[DeploymentStage]] = {
    DataMode.CURRENT_RESEARCH: frozenset(DeploymentStage),
    DataMode.STRICT_HISTORICAL: frozenset({DeploymentStage.RESEARCH}),
}
```

**`PAPER` 与 `LIMITED_LIVE` 是两个独立值，不是一个连续刻度。** 枚举里没有任何
「提升」操作，也没有序关系。本 plan 的 Task 1 与 Task 5 各有一个测试断言：
不存在任何函数、参数、header 或字段能把一个 `paper` 对象变成 `limited_live` 对象。

注意 `_ALLOWED_STAGES_BY_DATA_MODE` 允许 `(current_research, paper)`
—— 这是本 plan 的 `RunContext`。`(strict_historical, paper)` 会 raise
`InvalidRunContextError`，Task 1 要有测试确认这条既有守卫仍然成立。

### `domain/market_data.py`（477 行）—— fill policy 的输入合同

`DailyBar` 的 14 个字段（逐字）：

```python
@dataclass(frozen=True)
class DailyBar:
    listing_id: str
    exchange: Exchange
    session_date: date
    currency: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    previous_close: Decimal
    volume_shares: int
    amount: Decimal
    adjustment: PriceAdjustment
    source_id: str
    dataset_version_id: str
    trust_state: DataTrustState
```

已被 `__post_init__` 强制的三条事实，fill policy 要**利用而不是重复实现**：
`high >= max(open, low, close)`；`low <= min(open, high, close)`；
`adjustment is not PriceAdjustment.UNADJUSTED` 时 raise
（「`DailyBar` stores only raw unadjusted prices」）。**Paper 成交价必须用未复权价**，
因为账本记的是真实现金流；复权价只属于研究。

`DailyMarketState` 的 9 个字段与两条守卫：

```python
@dataclass(frozen=True)
class DailyMarketState:
    listing_id: str
    session_date: date
    is_trading: bool
    is_suspended: bool
    source_id: str
    dataset_version_id: str
    trust_state: DataTrustState
    listing_state: ListingState | None
    special_treatment: SpecialTreatment | None
```

守卫：`is_trading and is_suspended` 同真时 raise；
`listing_state is ListingState.TERMINATED and is_trading` 时 raise。

`PriceLimit` 与它的四值判定（逐字）：

```python
@dataclass(frozen=True)
class PriceLimit:
    listing_id: str
    session_date: date
    lower: Decimal
    upper: Decimal
    source_id: str

    def status_for(self, bar: DailyBar) -> PriceLimitStatus:
        if bar.close == self.upper:
            if bar.low == self.upper and bar.high == self.upper:
                return PriceLimitStatus.LOCKED_UP
            return PriceLimitStatus.LIMIT_UP
        if bar.close == self.lower:
            if bar.low == self.lower and bar.high == self.lower:
                return PriceLimitStatus.LOCKED_DOWN
            return PriceLimitStatus.LIMIT_DOWN
        return PriceLimitStatus.NOT_AT_LIMIT
```

`LOCKED_UP` 与 `LIMIT_UP` 的区别在 Paper 里比在回测里更重要：回测里它影响统计，
Paper 里它决定一张真实提交的订单收到 `ack` 还是 `reject`，而那个结果会进入
可审计账本。

`CorporateAction` 的 10 个字段（Task 4 的公司行动测试全部基于它）：

```python
@dataclass(frozen=True)
class CorporateAction:
    action_id: str
    listing_id: str
    action_type: CorporateActionType
    ex_date: date
    record_date: date
    cash_per_share: Decimal | None
    share_ratio: Decimal | None
    subscription_price: Decimal | None
    currency: str
    source_id: str
```

`CorporateActionType` 五值：`CASH_DIVIDEND` / `BONUS_SHARE` / `SPLIT` /
`REVERSE_SPLIT` / `RIGHTS_ISSUE`。已被强制：现金分红必须有 `cash_per_share`；
送股/拆股/并股必须有 `share_ratio`；**配股必须同时有 `share_ratio` 与
`subscription_price`**；`record_date > ex_date` 时 raise。

`ExchangeCalendar` 的两个方法是 T+1 与日界推进的唯一日期真源：

```python
def is_session(self, calendar_date: date) -> bool:
    day = next((item for item in self.days if item.calendar_date == calendar_date), None)
    if day is None:
        raise MarketDataUnavailable(f"calendar has no observation for {calendar_date}")
    return day.is_open

def next_session(self, after: date) -> date:
    candidates = sorted(
        item.calendar_date
        for item in self.days
        if item.is_open and item.calendar_date > after
    )
    if not candidates:
        raise MarketDataUnavailable(f"calendar has no known session after {after}")
    return candidates[0]
```

**两者都 raise 而不是返回默认值。** T+1 的可卖日必须由 `next_session()` 计算，
**不得**用 `session + timedelta(days=1)` —— 那会在周末与长假上错，而错的方向是
「让今天买的股票明天可卖」，即**高估流动性**。

### `domain/signals.py`（`SignalSnapshot`，43 个字段）

本 plan 只用它的 `snapshot_id` / `content_hash` / `approval_scope` / `run_context`
做溯源链的上游锚点。`OrderIntent` **不直接消费** `SignalSnapshot`
—— 中间必须经过 `TargetPortfolioSnapshot`，否则就绕过了组合约束与 PM 审批。

哈希工具的既有模式（`domain/signals.py` 第 62 行）：

```python
def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
```

本 plan 的所有 `content_hash` 照抄这个模式（64 位小写 hex，无 `sha256:` 前缀；
注意数据库层的 `governance` 约束用的是 `'^sha256:[0-9a-f]{64}$'` 带前缀格式，
Task 5 的 migration 要与既有列格式一致，**先读 `migrations/0032_governance_integrity.sql` 确认**）。

### `workers/timing_baseline.py`（144 行）—— dry-run/ack 模板，照抄不自创

```python
parser.add_argument("--private-local-research-ack", action="store_true")
parser.add_argument("--execute", action="store_true")
...
if not args.execute:
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0

blockers: list[str] = []
if not args.private_local_research_ack:
    blockers.append("private-local research ack is required")
if not _postgres_endpoint_is_private_local(args.database_url):
    blockers.append("database must use a loopback or Unix socket endpoint")
output["blockers"] = blockers
if blockers:
    output["execution_status"] = "blocked"
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 2
```

退出码语义：`0` dry-run 或成功、`1` 执行失败、`2` 被 blocker 拒绝。
本 plan 的三个 worker（`paper_session`、`paper_reconciliation`、`paper_replay`）
**必须**照这个形状，并**额外**加一个 blocker：`deployment_stage` 不是 `paper` 时拒绝。

### `api/app.py` 的 `fixed_read_context()`（第 147 行）—— 阶段不可提升的既有模式

```python
def fixed_read_context(
    data_mode: Annotated[str | None, Query()] = None,
    deployment_stage: Annotated[str | None, Query()] = None,
) -> RunContext:
    if data_mode is not None or deployment_stage is not None:
        raise RunContextOverrideDenied(
            "run context is fixed by the server use case and cannot be promoted by query parameters"
        )
    return RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.RESEARCH)
```

**这个函数就是 ADR-0010 决策 4 的现成实现模板。** Task 5 新增一个
`paper_read_context()`，形状完全相同但返回
`RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.PAPER)`，
且**同样拒绝任何 query 参数**。`RunContextOverrideDenied` 的 400 handler 已存在
（第 313 行），直接复用。

### `frontend/src/app/AppShell.tsx` 第 151–158 行 —— 全局运行上下文条

```tsx
<div aria-label="运行上下文" className="runContext">
  ...
  <Tag>current_research</Tag>
  ...
  <Tag color="blue">research</Tag>
```

当前**硬编码**为 `research`。Task 6 必须让 Execution 工作区的页面显示 `paper`
而其余页面继续显示 `research`，且**这个值来自服务端 envelope 的
`context.deployment_stage`，不是前端字符串常量**。理由：如果它是前端常量，
那么「当前在哪个阶段」就有两个真源，而其中一个可以被一次前端改动改成 `limited_live`。

### `frontend/src/navigation/routes.tsx` 与 `WorkspacePage.tsx` 的既有 blocker

`routes.tsx` 的 `monitoring.tabs` 已登记七项（逐字）：

```ts
tabs: ['Signals', 'Portfolios', 'Timing', 'Drift', 'Rebalance', 'Execution', 'Incidents'],
```

`WorkspacePage.tsx` 第 23 行的 `activationReasons.execution`（逐字）：

```ts
execution: '执行监控将在 Paper OMS 启用后开放；当前没有连接账户或券商。',
```

**Task 6 移除这一条**，而**保留** `users` / `entitlements`（无 IdP）。
移除它是本 plan 唯一一个「让一个页面从 blocked 变成可用」的前端动作，
所以它必须在真实 API 就绪之后，不能提前。

## 原型参照：`design_status` 全部为 `missing`

`docs/assets/prototype/figma-node-summary.json` 的 `frames` 是 dict，键为 node id。
**全部 17 个 frame 逐一核对，没有任何一个是 Paper 执行页：**

```text
3:7      foundations-product-map
3:398    desk-daily-workstation
3:726    research-universe-screen
3:1248   security-overview-600519
3:1569   product-blueprint-31-pages     ← 本 plan 的唯一参照
7:5      factors-alpha-model
7:303    portfolios-construction
7:712    portfolios-realistic-backtest
7:1060   portfolios-risk-scenarios
7:1348   portfolios-attribution
9:2      10-events-intelligence
9:238    11-timing-lab
9:431    12-timing-shadow-monitor
9:661    13-data-quality-lineage
9:883    14-approvals-reviewer-queue
15:2     security-investmentview
24:400   security-overview-600519-fused-v2
```

因此**本 plan 七个页面的 `design_status` 全部永久为 `missing`**，
没有一页可以声称 parity。P-4 已立此规：没有 Frame 就不能声称 parity。

### `3:1569` = `product-blueprint-31-pages` 的真实结构

1440×1200，`layout: HORIZONTAL`，两个顶层子节点：

```text
product-blueprint-31-pages [FRAME] w=1440 h=1200
 sidebar        [FRAME] w=248  h=1200  layout=VERTICAL gap=24
   brand        [FRAME] w=216  h=36
   Line         [LINE]  w=216  h=0
   nav-list     [FRAME] w=216  h=236   gap=4   （6 个 nav-item，各 w=216 h=36 gap=12）
   sidebar-footer [FRAME] w=216 h=30
 main-content   [FRAME] w=1192 h=1200
   topbar             [FRAME] w=1192 h=64
   company-header-band [FRAME] w=1192 h=88
   workspace          [FRAME] w=1192 h=581
   bottom-action-bar  [FRAME] w=1192 h=56
   footer             [FRAME] w=1192 h=41
```

全部 TEXT 节点（17 个，逐字提取）：

| 区域 | 真实文本 |
|---|---|
| brand | `Fundamental Quant` / `A股基本面量化研究平台` |
| nav-list（6 项） | `今日工作台` `研究` `因子` `组合` `监控` `数据与管理` |
| sidebar-footer | `SPEC V2.4.0` / `Fund Quant Lab © 2026` |
| workspace | `定量回测时限与多维情景预测` / `当前情景分布由 质量、估值、改善 四维度截面回归计算拟合。…` |
| bottom-action-bar | `版本 v1.2` / `最后更新: 2024-12-06 09:35` / `Submit for Review (提交量化中心初审)` |
| footer | `Fund Quant Asset Design Spec © 2026 Fundamental Quant Research Lab. All Rights Reserved.` / `CONFIDENTIAL · 内部机密` |

**从这个 frame 只能得到三件事，其余全部是本 plan 的设计假设：**

1. **一级导航恰好六项**，`监控` 是第五项。Execution 页属于 `监控` 工作区的二级 tab
   （`routes.tsx` 已如此登记），**不是第七个一级工作区**。这一点有原型依据。
2. **`bottom-action-bar` 是一个 56 px 高的独立底部动作条**，`workspace` 高 581 px。
   本 plan 的危险操作（提交 intent、撤单、拉 kill switch）**放在这个条里**，
   而不是散在表格行内 —— 有原型依据的信息架构决定，理由见「陷阱七」。
3. `版本 v1.2` / `最后更新: 2024-12-06 09:35` / `Submit for Review (提交量化中心初审)`
   **全部是 design fixture**，零泄漏。`定量回测时限与多维情景预测` 那段文案属
   InvestmentView，与本 plan 无关。

**必须逐条记录的设计假设（Task 6 Step 1 写入 Evidence，共七条）：**

```text
1. Execution 作为 monitoring 工作区的第 6 个 tab（有 routes.tsx 依据，无 Frame）
2. 七个执行面板（preview/orders/fills/positions/cash/breaks/kill-switch）
   的分区顺序按 SPEC-036 状态机顺序排列，不按字母或重要性
3. 危险操作集中在 bottom-action-bar（借 3:1569 的 56 px 动作条结构）
4. paper 标签的位置沿用 AppShell 既有 runContext 条（无 Frame，借既有实现）
5. breaks 表的列结构借 9:661 的 `Check/Dataset/规则/结果/影响/报告版本/Run/时间`
   八列语言，替换为 `Break/对象/规则/差额/严重度/状态/Run/时间`
6. kill switch 的视觉借 9:883 的「可信使用边界」卡片语言，不发明新组件
7. 六态复用 WorkspaceState 的 loading/error/empty/partial/unavailable/ready，
   不为执行新增第七态
```

## 七个必须先想清楚的设计陷阱

本 plan 的多数篇幅在防这七件事。它们不是实现细节，而是决定这个 OMS 是不是一个
可以被信任的账本的前提。

### 陷阱一：幂等被当成异常路径，于是网络重试变成重复下单

**这是本 plan 最重要的一条。**

一个 HTTP 请求超时，客户端不知道服务端是否已处理。正确行为是重试。
如果重试产生第二张订单，那么**一次网络抖动就是一次重复下单**，
而重复下单在真实市场里是直接的金钱损失。

危险在于这件事在测试里"看不见"：单元测试调用一次命令，断言产生一个订单，通过。
集成测试调用一次命令，断言数据库有一行，通过。**没有任何一个测试重试过。**

而生产里重试是**常态而非例外**：客户端超时重试、负载均衡器重试、
worker 崩溃后 checkpoint 续跑、用户双击提交按钮、浏览器刷新重发 POST。

SPEC-036 的验收原文把它列在第二位：「状态转换合法、幂等、防重复下单」。
Step 09 Spec 的领域合同段落最后一句逐字：「状态转换、账本、broker event 和审计
append-only；命令幂等。」

**防线有四层，Task 1 与 Task 5 各两层：**

1. **每个命令都有 client 提供的 `idempotency_key`（必填，不可为空）。**
   不是服务端生成 —— 服务端生成的 key 在重试时会不同，那等于没有 key。
2. **`(command_kind, idempotency_key)` 上有唯一索引**（Task 5 的 migration）。
   幂等不能只靠应用层的「先查再写」—— 两个并发请求会同时查到空然后同时写。
   **数据库唯一索引是唯一能在并发下成立的保证。**
3. **重复命令返回原对象，不 raise。** 这一点容易做错成 409：
   如果重试拿到 409，客户端会认为失败并进入错误处理，而订单其实已经建了。
   正确语义是**幂等重放**：返回第一次的结果与同一个 `order_id`。
4. **same key / different payload 必须冲突关闭。** 如果同一个 key 带着不同的数量
   或不同的证券再来一次，那不是重试，是 bug 或攻击。此时 raise，
   因为返回第一次的结果会让调用方以为它的新指令被接受了。

Task 1 Step 2 的第一个红测就是重复命令，**在任何状态机代码之前**。
理由：如果幂等是后加的，它会被加在服务层的入口处，而领域层的
`Order` 仍然可以被构造两次 —— 那么任何绕过服务层的路径（worker、replay、
migration 修数据）都会产生重复。

### 陷阱二：非法转移被容忍，于是账本状态失去意义

`Order` 有九个状态（Step 09 Spec 逐字列出）。九个状态之间有 72 个有向对，
其中合法的只有 17 个（下方 `_LEGAL_TRANSITIONS` 逐条列出）。**如果实现只检查「目标状态是不是一个合法枚举值」，
那么 72 个转移全部允许**，而账本上会出现「已成交后被撤销」这种物理上不可能的历史。

危险的具体形状：一个撤单命令在成交回报之前发出，但在成交回报之后到达。
如果 `cancel()` 不检查当前状态，订单从 `FILLED` 变成 `CANCELLED`，
**而那 30,000 股已经成交了**。持仓与订单从此永久不一致，而对账会把它
报成一个 break —— 一个由 OMS 自己制造的 break。

**防线**：Task 1 定义一张**显式的转移表**（`_LEGAL_TRANSITIONS`），
`OrderState` 的每一次变化都必须查表；表外的转移 raise
`IllegalOrderTransition` 并**记入审计**（被拒的转移是重要事实，不是无事发生）。
Task 1 Step 4 有一个测试**穷举全部 81 个 (from, to) 组合**（9×9，含自环），
逐个断言合法或被拒 —— 不是抽查几个。

穷举的理由：抽查会漏。而漏掉的那一个，正好是生产里最难复现的那一个。

### 陷阱三：kill switch 只挡 UI，于是它在真正需要时不存在

kill switch 最常见的实现是把按钮变灰，或在 API 层加一个 `if killed: return 403`。
两者都不够：前者是前端状态，后者只挡「通过那个 API 的请求」，
而 worker、replay、恢复流程、以及任何新加的第二个 endpoint 都绕过它。

更隐蔽的问题：**kill switch 必须能拦住一个已经通过风险与审批的 intent。**
如果它只在风险检查之前生效，那么一个昨天获批的 intent 今天仍然可以下单
—— 而 kill switch 存在的场合正是「昨天的判断今天不再有效」。

`docs/18` §3.6 的 Entitlements 行逐字：「前端隐藏不是权限；真实交易拒绝」。
`SPEC-055` 逐字：「实盘前必须有 kill switch 和降级运行手册」。

**防线**：Task 2 把 kill switch 放在 `OrderIntentService.submit_order()` 的
**最后一道门**，在权限、风险、审批**全部通过之后**。Task 2 Step 8 的核心测试
构造一个「风险通过 + 审批通过 + 未过期 + scope 正确」的 intent，
然后开 kill switch，断言下单被拒且理由指名 kill switch，
**并且断言那个 intent 的审批记录没有被改写**（拒绝不是撤销审批）。

同时 Task 4 有第二条独立路径：**material reconciliation break 也阻断新订单**，
机制与 kill switch 相同但触发源不同。两条路径不共用一个布尔标志
—— 那会让「为什么停了」失去区分度。

### 陷阱四：break 被自动修正，于是不一致的证据被销毁

对账发现目标 5,000 股、订单 5,000 股、成交 4,800 股、持仓 5,000 股。
**最自然的实现是把持仓改成 4,800。** 那是错的，而且是不可逆的错。

理由：`5,000 vs 4,800` 这个差额**本身就是唯一的证据**，它指向一个具体的缺陷
——可能是 partial fill 没有更新持仓，可能是一条成交回报丢了，
可能是 fill policy 算错了。把持仓改成 4,800 之后，账平了，
**而那个缺陷仍然存在且再也查不到了**，下一次它会以另一个数字出现。

SPEC-038 的验收原文：「账不平时停止新的自动订单并产生 Incident，
**不允许用人工修改数字掩盖**」。

**防线**：Task 4 的 `ReconciliationService` 只能**产出** `ReconciliationBreak`，
它的签名里**没有任何可写入持仓或现金的对象**（与 P-8 的 drift calculator 同一手法）。
`ReconciliationBreak` 是 frozen 且 append-only，它的 `resolution` 字段只能记录
「人做了什么」，不能改变差额本身。Task 4 Step 6 有一个测试断言：
一次对账运行之后，全部 `PositionLot` 与 `CashLedgerEntry` 的 hash
**逐个字节相同** —— 对账是只读的。

### 陷阱五：把回测库存当成 Paper 持仓，于是账本变成模拟

P-5 的 `InventoryState` 是一个**模拟状态**：它由 `advance_session()` 从上一个状态
纯函数地推出，可以随时重算。Paper 的 `PositionLot` 是一个**账本事实**：
它由真实发生过的 `Fill` 累积而成，**不能重算，只能重放**。

混同的具体后果：如果持仓是「从成交重算出来的视图」，那么一次 fill policy 的
版本升级会**追溯改变历史持仓**，而历史持仓已经被用于历史对账与历史归因。
账本的定义就是它不会因为代码变化而变化。

**防线**：`PositionLot` 与 `CashLedgerEntry` 是 append-only 事件累积，
每一条都携带产生它的 `fill_id` 或 `corporate_action_id` 与
`cost_model_version_id`。Task 4 有一个测试断言：升级 `CostModel` 版本
**不改变**任何既有 `CashLedgerEntry` 的金额或 hash；新费率只影响新成交。

### 陷阱六：费用被当成常量，于是历史成本无法解释

佣金 0.08%、印花税 0.1% 看起来像常识（P-5 原型的 design value 就是这两个数）。
但费率会变：2008 年印花税从 0.3% 降到 0.1%，过户费的口径也调整过多次。
如果费率写在代码里，那么某天有人改了它，**昨天的成交成本今天算出不同的数字**，
而两次计算在任何账本里看不出差别。

更隐蔽的版本：费率在配置里但不进 hash。此时同一个 `order_id` 的成本
在不同时间算会不同，而 `order_id` 本该唯一确定它的现金流。

ADR-0006 决策 6 逐字：「费用、滑点、冲击、参与率、价格口径和日历版本
进入 Run/Artifact hash」。

**防线**：复用 P-5 的 `CostModel`（它已经是 content-addressed，
有 `cost_model_version_id` 与 `content_hash`）。Task 4 Step 4 有一个测试断言
改任一费率产生新 hash，**且**一个 `CashLedgerEntry` 引用的
`cost_model_version_id` 一旦写入就不可变。**A 股印花税只在卖出侧**
—— 在买入侧也收会让每次买入成本高 0.1%，这个测试 P-5 已经有了，
本 plan 在 Paper 路径上再断言一次（同一规则的两个消费者各自验证）。

### 陷阱七：危险操作与查看操作长得一样，于是误操作只是时间问题

一个「撤销全部订单」按钮和一个「刷新」按钮如果在同一行、同样大小、同样颜色，
那么误点是必然的，只是时间问题。而 Paper 的误点是演练，Live 的误点是钱。

Step 09 Task 6 逐字：「危险操作需明确权限和确认；Agent 视图无操作」。

**防线**：Task 6 定义三级操作等级，且**等级由服务端投影声明，不由前端判断**：

```text
read          任何 principal（含 anonymous 的 read_public 部分）
guarded       需要 SEND_ORDER；点击后有一次确认
irreversible  需要 SEND_ORDER + 二次确认 + 输入对象 id 确认
```

`kill switch` 与 `cancel all` 属 `irreversible`。Agent 视图**不渲染**任何
`guarded` 或 `irreversible` 控件 —— 不是渲染后禁用，而是**投影里就没有这些动作**。
理由：禁用的按钮仍然在 DOM 里，而 DOM 可以被改；投影里没有的动作，
前端无从构造。

## Task 排序的理由（严格 TDD 可行性）

```text
Task 1  domain/oms.py            九态状态机 + 幂等 + 阶段隔离   ← 无 I/O，可 100% 单测
Task 2  application/order_intents.py  风险 + SoD 审批 + kill switch ← 依赖 P-8 审批合同
Task 3  ports/broker.py + adapters/paper/broker.py  确定性 broker  ← 第一次出现 adapter
Task 4  positions / cash / reconciliation / breaks               ← 依赖 Task 1+3 的成交
Task 5  migration + repository + command/read API                ← 第一次出现数据库
Task 6  PUI-09 七个执行面板                                       ← 依赖 Task 5 的投影
Task 7  replay / 恢复 / 日界 / backup-restore / 真实日历 soak      ← 依赖全部
```

**为什么状态机与幂等必须排最前**：它们是纯逻辑，输入完全由测试构造。
如果先建 repository，第一个红测的失败原因会是「数据库没连上」
而不是「已成交订单被撤销了」—— 那就失去了 TDD 的诊断价值。

**为什么 kill switch 排在 Task 2 而不是 Task 5（API 层）**：它必须在 intent 层生效
（陷阱三）。如果它在 API 层，那么 Task 7 的 replay worker 会绕过它。

**为什么 broker adapter 排在持仓现金之前**：持仓与现金的输入是 `Fill`，
而 `Fill` 由 broker 产生。先做持仓会导致用手写的 `Fill` fixture 测试，
而真实 broker 产生的 `Fill` 形状可能不同 —— 那种不一致只在接线时才暴露。

**为什么 soak 排最后且不能被单测替代**：Step 09 Task 7 逐字：
「真实日历 soak 证据不能用快速单测替代」。理由在 Task 7 展开。

---

### Task 1: `domain/oms.py` —— 九态状态机、命令幂等与阶段隔离

对应 Step 09 Task 1 逐字：「遵守 `docs/adr/0010-deterministic-internal-paper-broker.md`，
新增 `domain/oms.py` 和状态机/幂等 tests。先非法 transition 和 duplicate command 红测。」

**冻结 Plan 明确要求「先非法 transition 和 duplicate command 红测」，本 Task 严格照办：
Step 2 是重复命令，Step 4 是非法转移，两者都在任何"正常路径"实现之前。**

理由：正常路径（创建 → 批准 → 提交 → 成交）会自然被后续 Task 覆盖；
而幂等与非法转移一旦漏了，就再也不会有人回来补，因为"功能已经能用了"。

**Files:**
- Create: `platform/src/a_share_platform/domain/oms.py`
- Test: `platform/tests/test_oms_idempotency.py`
- Test: `platform/tests/test_oms_state_machine.py`
- Test: `platform/tests/test_oms_stage_isolation.py`
- Modify: `platform/tests/test_architecture_contract.py`（扩 `forbidden_roots`）

**Interfaces:**
- Consumes: `domain/run_context.py`（`RunContext` / `DataMode` / `DeploymentStage`）、
  `domain/execution_rules.py`（`OrderSide` / `BlockReason` / `FillStatus` / `CostModel`，P-5 已建）、
  `domain/pit.py`（`DataTrustState`）
- Produces:
  ```python
  class OrderState(StrEnum):
      """Step 09 Spec 的九个状态，逐字对应
      created/approved/submitted/acknowledged/partially_filled/
      filled/cancelled/rejected/expired."""
      CREATED = "created"
      APPROVED = "approved"
      SUBMITTED = "submitted"
      ACKNOWLEDGED = "acknowledged"
      PARTIALLY_FILLED = "partially_filled"
      FILLED = "filled"
      CANCELLED = "cancelled"
      REJECTED = "rejected"
      EXPIRED = "expired"

  TERMINAL_STATES: frozenset[OrderState] = frozenset({
      OrderState.FILLED, OrderState.CANCELLED,
      OrderState.REJECTED, OrderState.EXPIRED,
  })

  # 显式转移表。表外的一切都被拒绝。
  _LEGAL_TRANSITIONS: Mapping[OrderState, frozenset[OrderState]] = {
      OrderState.CREATED: frozenset({
          OrderState.APPROVED, OrderState.REJECTED, OrderState.EXPIRED}),
      OrderState.APPROVED: frozenset({
          OrderState.SUBMITTED, OrderState.CANCELLED, OrderState.EXPIRED}),
      OrderState.SUBMITTED: frozenset({
          OrderState.ACKNOWLEDGED, OrderState.REJECTED, OrderState.EXPIRED}),
      OrderState.ACKNOWLEDGED: frozenset({
          OrderState.PARTIALLY_FILLED, OrderState.FILLED,
          OrderState.CANCELLED, OrderState.EXPIRED}),
      OrderState.PARTIALLY_FILLED: frozenset({
          OrderState.PARTIALLY_FILLED, OrderState.FILLED,
          OrderState.CANCELLED, OrderState.EXPIRED}),
      OrderState.FILLED: frozenset(),
      OrderState.CANCELLED: frozenset(),
      OrderState.REJECTED: frozenset(),
      OrderState.EXPIRED: frozenset(),
  }
  # PARTIALLY_FILLED 到自身是唯一的合法自环：第二次部分成交。
  # 四个终态的出边集合为空 —— 这是"已成交不可撤销"的机械保证。

  class TimeInForce(StrEnum):
      DAY = "day"                 # A 股当日有效，收盘未成交则 EXPIRED

  class OrderType(StrEnum):
      LIMIT = "limit"
      MARKET = "market"

  class IllegalOrderTransition(RuntimeError):
      """A transition outside the explicit table.  Recorded, never tolerated."""

  class IdempotencyConflict(RuntimeError):
      """Same idempotency key, different command payload."""

  class ExecutionStageViolation(PermissionError):
      """An execution object was constructed outside deployment_stage=paper."""

  @dataclass(frozen=True)
  class IdempotencyKey:
      """Client-supplied, because a server-generated key differs on retry."""
      command_kind: str
      key: str
      payload_hash: str            # 64-hex sha256 of the canonical command payload

  @dataclass(frozen=True)
  class OrderIntent:
      """Step 09 Spec 逐字：target/policy/security/side/qty/limit/tif/reason/
      idempotency/approval."""
      intent_id: str
      target_id: str               # TargetPortfolioSnapshot —— 唯一合法来源
      target_hash: str
      policy_id: str
      policy_hash: str
      security_id: str
      listing_id: str
      side: OrderSide              # P-5 的枚举，不重新定义
      requested_shares: int
      order_type: OrderType
      limit_price: Decimal | None   # MARKET 时必须为 None，LIMIT 时必填
      time_in_force: TimeInForce
      reason: str                   # 非空：为什么下这一单
      idempotency: IdempotencyKey
      submitted_by: str             # SoD 的一半
      submitted_at: datetime
      approval_review_id: str | None  # P-8 的 ApprovalReview；未批准时 None
      run_context: RunContext        # 必须是 (current_research, paper)
      content_hash: str = field(init=False)

  @dataclass(frozen=True)
  class Fill:
      """Step 09 Spec 逐字：qty/price/fee/time/source."""
      fill_id: str
      order_id: str
      filled_shares: int            # 必须 > 0；零股成交不是成交
      price: Decimal                # 未复权成交价
      currency: str
      commission: Decimal
      stamp_duty: Decimal           # 卖出侧才可能非零
      transfer_fee: Decimal
      cost_model_version_id: str
      filled_at: datetime
      source: str                   # 'paper_broker'；未来 Live 换值不换结构
      broker_event_id: str
      content_hash: str = field(init=False)

  @dataclass(frozen=True)
  class Order:
      order_id: str
      intent_id: str
      intent_hash: str
      state: OrderState
      requested_shares: int
      filled_shares: int            # 必须 <= requested_shares
      average_fill_price: Decimal | None
      broker_order_id: str | None    # 唯一的 broker 特定字段（ADR-0010 决策 2）
      rejection_reason: str | None   # REJECTED 时必填
      block_reasons: tuple[BlockReason, ...]  # P-5 的枚举
      run_context: RunContext
      created_at: datetime
      updated_at: datetime
      content_hash: str = field(init=False)

      def can_transition_to(self, target: OrderState) -> bool: ...
      def transition_to(self, target: OrderState, *, at: datetime,
                        reason: str | None = None) -> Order: ...

  @dataclass(frozen=True)
  class RejectedTransition:
      """A refused transition, as a value.  Task 5 persists it to the audit log."""
      order_id: str
      from_state: OrderState
      to_state: OrderState
      attempted_at: datetime
      actor_id: str
      reason: str

  @dataclass(frozen=True)
  class KillSwitchState:
      """Step 09 Spec 逐字：scope/reason/actor/time/effective state."""
      kill_switch_id: str
      scope: str                    # 'global' | 'policy:<id>' | 'security:<id>'
      engaged: bool
      reason: str                   # 非空，engage 与 release 都要理由
      actor_id: str
      effective_at: datetime
      released_at: datetime | None
      content_hash: str = field(init=False)

      def blocks(self, *, policy_id: str, security_id: str,
                 at: datetime) -> bool: ...
  ```

- [ ] **Step 1: 先读被消费合同的真实字段（不要凭记忆）**

```bash
cd platform
sed -n 1,56p src/a_share_platform/domain/run_context.py
grep -n "class OrderSide" -A6 src/a_share_platform/domain/execution_rules.py
grep -n "class BlockReason" -A16 src/a_share_platform/domain/execution_rules.py
grep -n "class FillStatus" -A6 src/a_share_platform/domain/execution_rules.py
grep -n "class CostModel" -A14 src/a_share_platform/domain/execution_rules.py
grep -n "class TargetPortfolioSnapshot" -A24 src/a_share_platform/domain/portfolio.py
sed -n 58,80p src/a_share_platform/domain/signals.py     # _canonical_hash 模板
```

**若 P-5 的字段名与本 plan 不同，改本 plan 的后续步骤，不要改 P-5 的代码去迁就本 plan。**
特别注意 `OrderSide` / `BlockReason` / `FillStatus` **必须从 `execution_rules` 导入**，
不得在 `oms.py` 里重新定义 —— 两个同名枚举是最难发现的一类缺陷。

- [ ] **Step 2: 写第一个红测 —— 重复命令（在任何状态机代码之前）**

```python
# platform/tests/test_oms_idempotency.py
"""Command idempotency, which is the property this OMS exists to have.

A network timeout does not tell the client whether the server processed the
command, so the client retries.  If the retry creates a second order then one
network hiccup is one duplicate order, and duplicate orders cost real money.

Retries are normal rather than exceptional here: clients time out, load balancers
retry, workers resume from a checkpoint after a crash, users double-click, and a
browser refresh resends a POST.  So the duplicate case is tested first, before any
happy path exists to be tested at all.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal

from a_share_platform.domain.oms import (
    IdempotencyConflict,
    IdempotencyKey,
    OrderIntent,
    OrderState,
    OrderType,
    TimeInForce,
    build_order,
)
from a_share_platform.domain.execution_rules import OrderSide
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext

PAPER = RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.PAPER)
NOW = datetime(2026, 8, 17, 1, 30, tzinfo=UTC)


def intent(
    *,
    key: str = "client-key-0001",
    shares: int = 5_000,
    intent_id: str = "intent:0001",
) -> OrderIntent:
    return OrderIntent(
        intent_id=intent_id,
        target_id="target:csi500:2026-08-14",
        target_hash="a" * 64,
        policy_id="policy.core",
        policy_hash="b" * 64,
        security_id="security:CN:600519:XSHG",
        listing_id="listing:CN:600519:XSHG",
        side=OrderSide.BUY,
        requested_shares=shares,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("1450.00"),
        time_in_force=TimeInForce.DAY,
        reason="rebalance to approved target weight",
        idempotency=IdempotencyKey(
            command_kind="submit_order",
            key=key,
            payload_hash="c" * 64,
        ),
        submitted_by="subject:pm-1",
        submitted_at=NOW,
        approval_review_id=None,
        run_context=PAPER,
    )


class DuplicateCommandTest(unittest.TestCase):
    def test_the_same_command_twice_produces_one_order(self) -> None:
        """The single most important assertion in this plan."""
        ledger: dict[tuple[str, str], object] = {}
        first = build_order(intent(), ledger=ledger, at=NOW)
        second = build_order(intent(), ledger=ledger, at=NOW)
        self.assertEqual(first.order_id, second.order_id)
        self.assertEqual(len(ledger), 1)

    def test_a_replayed_command_returns_the_original_rather_than_raising(self) -> None:
        """409 would be wrong: the client would enter error handling for an order
        that actually exists, and would either retry forever or report a failure
        that did not happen."""
        ledger: dict[tuple[str, str], object] = {}
        first = build_order(intent(), ledger=ledger, at=NOW)
        replay = build_order(intent(), ledger=ledger, at=NOW)
        self.assertIs(replay.state, first.state)
        self.assertEqual(replay.content_hash, first.content_hash)

    def test_the_same_key_with_a_different_payload_is_a_conflict(self) -> None:
        """This is not a retry.  Returning the first result would tell the caller
        its new instruction was accepted."""
        ledger: dict[tuple[str, str], object] = {}
        build_order(intent(shares=5_000), ledger=ledger, at=NOW)
        with self.assertRaises(IdempotencyConflict):
            build_order(
                intent(shares=9_000, intent_id="intent:0002"),
                ledger=ledger,
                at=NOW,
            )

    def test_different_keys_produce_different_orders(self) -> None:
        """Idempotency must not collapse two genuinely different commands."""
        ledger: dict[tuple[str, str], object] = {}
        one = build_order(intent(key="client-key-0001"), ledger=ledger, at=NOW)
        two = build_order(
            intent(key="client-key-0002", intent_id="intent:0002"),
            ledger=ledger,
            at=NOW,
        )
        self.assertNotEqual(one.order_id, two.order_id)
        self.assertEqual(len(ledger), 2)

    def test_an_empty_idempotency_key_is_refused(self) -> None:
        """A blank key silently disables idempotency for that call site."""
        with self.assertRaises(ValueError):
            IdempotencyKey(command_kind="submit_order", key="   ", payload_hash="c" * 64)

    def test_the_key_is_scoped_by_command_kind(self) -> None:
        """A cancel and a submit that happen to share a client key are not the same
        command; scoping by kind keeps a cancel from being answered with an order."""
        cancel = IdempotencyKey(
            command_kind="cancel_order", key="client-key-0001", payload_hash="c" * 64
        )
        submit = IdempotencyKey(
            command_kind="submit_order", key="client-key-0001", payload_hash="c" * 64
        )
        self.assertNotEqual(
            (cancel.command_kind, cancel.key), (submit.command_kind, submit.key)
        )
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_oms_idempotency -v`

Expected: FAIL —— `a_share_platform.domain.oms` 不存在
（`ModuleNotFoundError: No module named 'a_share_platform.domain.oms'`）。
**把真实错误文本抄进 Evidence，不要复述本 plan 的预期。**

- [ ] **Step 4: 最小实现 —— 只做幂等，不做状态机**

`build_order()` 只需：校验 `IdempotencyKey` 非空、查 ledger、命中则比对 `payload_hash`
（不同则 raise `IdempotencyConflict`，相同则返回原对象）、未命中则构造
`state=OrderState.CREATED` 的 `Order` 并写入 ledger。

**不要**在这一步实现任何转移。转移是 Step 6 的事。

- [ ] **Step 5: 转绿**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_oms_idempotency -v`
Expected: PASS（6 个测试）

- [ ] **Step 6: 写第二个红测 —— 穷举全部 81 个转移**

```python
# platform/tests/test_oms_state_machine.py
"""The nine order states and every edge between them, enumerated.

Nine states admit eighty-one ordered pairs and only seventeen of them are legal.
An implementation that merely checks 'is the target a valid enum member' allows all
eighty-one, and the ledger then contains histories that are physically impossible —
an order cancelled after it filled, an order filling after it was rejected.

The concrete failure is a cancel sent before a fill report and delivered after it.
Without a state check the order goes FILLED → CANCELLED while the shares really did
trade, positions and orders disagree permanently, and reconciliation reports a break
that the OMS itself created.

Every pair is enumerated rather than sampled, because sampling misses one, and the
one it misses is the one that is hardest to reproduce in production.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from a_share_platform.domain.oms import (
    TERMINAL_STATES,
    IllegalOrderTransition,
    OrderState,
    legal_transitions,
)

NOW = datetime(2026, 8, 17, 2, 0, tzinfo=UTC)

LEGAL: frozenset[tuple[OrderState, OrderState]] = frozenset({
    (OrderState.CREATED, OrderState.APPROVED),
    (OrderState.CREATED, OrderState.REJECTED),
    (OrderState.CREATED, OrderState.EXPIRED),
    (OrderState.APPROVED, OrderState.SUBMITTED),
    (OrderState.APPROVED, OrderState.CANCELLED),
    (OrderState.APPROVED, OrderState.EXPIRED),
    (OrderState.SUBMITTED, OrderState.ACKNOWLEDGED),
    (OrderState.SUBMITTED, OrderState.REJECTED),
    (OrderState.SUBMITTED, OrderState.EXPIRED),
    (OrderState.ACKNOWLEDGED, OrderState.PARTIALLY_FILLED),
    (OrderState.ACKNOWLEDGED, OrderState.FILLED),
    (OrderState.ACKNOWLEDGED, OrderState.CANCELLED),
    (OrderState.ACKNOWLEDGED, OrderState.EXPIRED),
    (OrderState.PARTIALLY_FILLED, OrderState.PARTIALLY_FILLED),
    (OrderState.PARTIALLY_FILLED, OrderState.FILLED),
    (OrderState.PARTIALLY_FILLED, OrderState.CANCELLED),
    (OrderState.PARTIALLY_FILLED, OrderState.EXPIRED),
})


class ExhaustiveTransitionTest(unittest.TestCase):
    def test_every_ordered_pair_is_either_declared_legal_or_refused(self) -> None:
        for source in OrderState:
            for target in OrderState:
                with self.subTest(source=source, target=target):
                    allowed = target in legal_transitions(source)
                    self.assertEqual(allowed, (source, target) in LEGAL)

    def test_there_are_exactly_nine_states(self) -> None:
        """Adding a tenth state without adding its edges would leave it unreachable
        or, worse, reachable from everywhere."""
        self.assertEqual(len(tuple(OrderState)), 9)

    def test_the_four_terminal_states_have_no_outgoing_edges(self) -> None:
        """This is the mechanical guarantee that a filled order cannot be cancelled."""
        self.assertEqual(
            TERMINAL_STATES,
            frozenset({
                OrderState.FILLED, OrderState.CANCELLED,
                OrderState.REJECTED, OrderState.EXPIRED,
            }),
        )
        for state in TERMINAL_STATES:
            with self.subTest(state=state):
                self.assertEqual(legal_transitions(state), frozenset())

    def test_partially_filled_is_the_only_legal_self_loop(self) -> None:
        """A second partial fill is a real event; every other self-loop is a bug
        that would let an order be acknowledged twice."""
        for state in OrderState:
            with self.subTest(state=state):
                self.assertEqual(
                    state in legal_transitions(state),
                    state is OrderState.PARTIALLY_FILLED,
                )


class RefusedTransitionTest(unittest.TestCase):
    def test_a_filled_order_cannot_be_cancelled(self) -> None:
        order = _order(state=OrderState.FILLED, filled=5_000, requested=5_000)
        with self.assertRaises(IllegalOrderTransition):
            order.transition_to(OrderState.CANCELLED, at=NOW, reason="late cancel")

    def test_a_rejected_order_cannot_fill(self) -> None:
        order = _order(state=OrderState.REJECTED, filled=0, requested=5_000)
        with self.assertRaises(IllegalOrderTransition):
            order.transition_to(OrderState.PARTIALLY_FILLED, at=NOW)

    def test_an_order_cannot_be_submitted_before_it_is_approved(self) -> None:
        order = _order(state=OrderState.CREATED, filled=0, requested=5_000)
        with self.assertRaises(IllegalOrderTransition):
            order.transition_to(OrderState.SUBMITTED, at=NOW)

    def test_a_refused_transition_leaves_the_order_unchanged(self) -> None:
        """The order is frozen, so this also proves transition_to returns a new
        object rather than mutating."""
        order = _order(state=OrderState.FILLED, filled=5_000, requested=5_000)
        before = order.content_hash
        with self.assertRaises(IllegalOrderTransition):
            order.transition_to(OrderState.CANCELLED, at=NOW, reason="late cancel")
        self.assertEqual(order.content_hash, before)

    def test_a_refused_transition_is_expressible_as_an_auditable_value(self) -> None:
        """A refused command is a fact worth keeping: it usually means two systems
        disagree about the order's state."""
        from a_share_platform.domain.oms import RejectedTransition

        record = RejectedTransition(
            order_id="order:0001",
            from_state=OrderState.FILLED,
            to_state=OrderState.CANCELLED,
            attempted_at=NOW,
            actor_id="subject:trader-1",
            reason="cancel arrived after the fill report",
        )
        self.assertIs(record.from_state, OrderState.FILLED)
        self.assertTrue(record.reason)


class FillAccountingTest(unittest.TestCase):
    def test_filled_shares_cannot_exceed_requested_shares(self) -> None:
        """An overfill is not a state-machine question but it is caught here because
        the state and the quantity must agree in the same object."""
        with self.assertRaises(ValueError):
            _order(state=OrderState.FILLED, filled=6_000, requested=5_000)

    def test_the_filled_state_requires_the_full_quantity(self) -> None:
        with self.assertRaises(ValueError):
            _order(state=OrderState.FILLED, filled=4_800, requested=5_000)

    def test_partially_filled_requires_a_nonzero_incomplete_quantity(self) -> None:
        with self.assertRaises(ValueError):
            _order(state=OrderState.PARTIALLY_FILLED, filled=0, requested=5_000)

    def test_a_rejected_order_has_a_reason(self) -> None:
        with self.assertRaises(ValueError):
            _order(state=OrderState.REJECTED, filled=0, requested=5_000, reason=None)
```

（`_order()` 辅助函数按 Step 1 读到的真实 `Order` 签名构造，
`reason` 参数映射到 `rejection_reason`。）

- [ ] **Step 7: 运行确认红测 → 实现转移表 → 转绿**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_oms_state_machine -v`

Expected FAIL 原因至少两类：`legal_transitions` 不存在；`transition_to` 不存在。
逐个转绿，**先做 `legal_transitions()` 与穷举测试，再做 `transition_to()`**。

- [ ] **Step 8: 写第三个红测 —— 阶段隔离（`paper` 不可提升为 `limited_live`）**

```python
# platform/tests/test_oms_stage_isolation.py
"""paper and limited_live are two values, not two points on a scale.

DeploymentStage has no ordering and no promotion operation, and ADR-0010 decision 4
requires that no request parameter, URL, header or frontend switch can promote paper
to Live.  The domain half of that guarantee is that an execution object simply
cannot be constructed with limited_live at all in this plan, so there is nothing for
a request to reach.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from a_share_platform.domain.oms import ExecutionStageViolation, OrderIntent
from a_share_platform.domain.run_context import (
    DataMode,
    DeploymentStage,
    InvalidRunContextError,
    RunContext,
)


class StageIsolationTest(unittest.TestCase):
    def test_deployment_stage_has_four_values_and_no_ordering(self) -> None:
        self.assertEqual(
            [stage.value for stage in DeploymentStage],
            ["research", "shadow", "paper", "limited_live"],
        )
        with self.assertRaises(TypeError):
            _ = DeploymentStage.PAPER < DeploymentStage.LIMITED_LIVE  # type: ignore[operator]

    def test_an_intent_in_limited_live_is_refused_outright(self) -> None:
        """P11 needs a new explicit authorisation and its own broker/security ADR;
        until then this branch does not exist."""
        with self.assertRaises(ExecutionStageViolation):
            _intent(context=RunContext(
                DataMode.CURRENT_RESEARCH, DeploymentStage.LIMITED_LIVE))

    def test_an_intent_in_research_or_shadow_is_refused(self) -> None:
        """An execution object in a research run would be a research service holding
        an order, which SPEC-037 forbids."""
        for stage in (DeploymentStage.RESEARCH, DeploymentStage.SHADOW):
            with self.subTest(stage=stage):
                with self.assertRaises(ExecutionStageViolation):
                    _intent(context=RunContext(DataMode.CURRENT_RESEARCH, stage))

    def test_strict_historical_paper_is_still_refused_by_run_context(self) -> None:
        """An existing guard, asserted here so this plan cannot weaken it."""
        with self.assertRaises(InvalidRunContextError):
            RunContext(DataMode.STRICT_HISTORICAL, DeploymentStage.PAPER)

    def test_no_function_promotes_an_intent_across_stages(self) -> None:
        """The absence of a promotion path is the guarantee, so it is asserted as an
        absence: nothing in the OMS module exposes one."""
        import a_share_platform.domain.oms as oms

        names = [name.lower() for name in dir(oms)]
        for forbidden in ("promote", "to_live", "set_stage", "escalate", "upgrade"):
            with self.subTest(forbidden=forbidden):
                self.assertFalse([name for name in names if forbidden in name])
```

- [ ] **Step 9: 转绿 —— `__post_init__` 拒绝非 paper 阶段**

`OrderIntent` / `Order` / `Fill` 的 `__post_init__` 统一调用一个
`_require_paper_stage(context)`，非 `PAPER` 时 raise `ExecutionStageViolation`。

**这一条不是「暂时限制」。** 当 P11 获得授权时，正确改法是**新增**一个显式的
`limited_live` 分支并配套新的 ADR 与测试，而不是放宽这个守卫。

- [ ] **Step 10: 扩 `forbidden_roots` 并新增全树 SDK 扫描（ADR-0010 决策 5）**

```bash
cd platform
grep -n "forbidden_roots" -A 14 tests/test_architecture_contract.py
```

现有集合含 `futu`。**在其中追加所有真实交易/券商 SDK 根名**，并新增一个测试：

```python
# platform/tests/test_architecture_contract.py
# 两个方法追加到既有的 ArchitectureContractTest 中，复用它已有的
# 模块级 `import ast` 与 `PACKAGE_ROOT`，不新建测试文件也不新建 class。


class ArchitectureContractTest(unittest.TestCase):  # 既有 class，此处仅示意缩进层级
    def test_no_real_trading_sdk_is_imported_anywhere_in_the_platform(self) -> None:
        """ADR-0010 decision 5: no real trading SDK installed or imported, no account
        credentials stored, no real order endpoint.

        The domain guard only covers domain/.  A broker SDK imported from an adapter
        would satisfy that guard and still violate the ADR, and the violation would
        be one `pip install` plus one import away — small enough to arrive in a diff
        nobody reads closely.
        """
        trading_sdks = {
            "futu", "futuquant", "easytrader", "vnpy", "tqsdk", "ths_trader",
            "ctpwrapper", "xtquant", "rqalpha_mod_trade", "ibapi", "ib_insync",
            "alpaca", "tigeropen", "longport", "adata_trade",
        }
        violations: list[str] = []
        for path in sorted(PACKAGE_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                modules: tuple[str, ...] = ()
                if isinstance(node, ast.Import):
                    modules = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = (node.module,)
                for module in modules:
                    root = module.split(".")[0]
                    if root in trading_sdks:
                        violations.append(f"{path.name}:{node.lineno}:{module}")
        self.assertEqual(violations, [])

    def test_no_account_credential_field_names_exist_in_the_source_tree(self) -> None:
        """The second half of decision 5.  A credential field is how a paper adapter
        becomes a live adapter without anyone deciding to make it one."""
        forbidden = (
            "trade_password", "trading_password", "account_password",
            "broker_secret", "trade_token", "unlock_password",
        )
        hits: list[str] = []
        for path in sorted(PACKAGE_ROOT.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for needle in forbidden:
                if needle in text:
                    hits.append(f"{path.name}:{needle}")
        self.assertEqual(hits, [])
```

- [ ] **Step 11: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
git diff --check
cd .. && git add platform/src/a_share_platform/domain/oms.py \
  platform/tests/test_oms_idempotency.py \
  platform/tests/test_oms_state_machine.py \
  platform/tests/test_oms_stage_isolation.py \
  platform/tests/test_architecture_contract.py
git commit -m "feat: add the OMS core with client-supplied idempotency and an explicit state table

Idempotency is the property this module exists to have, so the duplicate command is
the first test written, before any happy path exists to be tested.  A network
timeout does not tell the client whether the server processed the command, so the
client retries — and retries are normal here rather than exceptional, since load
balancers retry, workers resume from checkpoints, users double-click and a browser
refresh resends a POST.  One hiccup must not become one duplicate order.

The key is supplied by the client because a server-generated key differs on every
retry, which is the same as having no key.  A replay returns the original order
instead of a conflict: answering a retry with 409 sends the caller into error
handling for an order that actually exists, so it either retries forever or reports
a failure that did not happen.  The same key carrying a different payload is a
conflict, though, because returning the first result would tell the caller its new
instruction had been accepted.

The nine states admit eighty-one ordered pairs and only seventeen are legal, so the
transitions live in an explicit table and every pair is enumerated in the test
rather than sampled.  Sampling misses one, and the one it misses is the one that is
hardest to reproduce in production.  The concrete case this prevents is a cancel
sent before a fill report and delivered after it: without the table the order goes
FILLED to CANCELLED while the shares really traded, positions and orders disagree
permanently, and reconciliation reports a break the OMS created itself.  The four
terminal states have empty edge sets, which is what makes 'a filled order cannot be
cancelled' mechanical rather than a matter of care.  Refused transitions are values,
not silence, because a refused command usually means two systems disagree.

Execution objects refuse every deployment stage other than paper, including
limited_live.  DeploymentStage has no ordering and no promotion operation, and this
module exposes no name containing promote, escalate or set_stage — the absence is
asserted, because ADR-0010 decision 4 requires that nothing can promote paper to
Live and the strongest form of that is having nothing to reach.  When P11 is
authorised the correct change is a new explicit branch with its own ADR, not a
relaxation of this guard.

The architecture guard now scans the whole package rather than only domain/ for
trading SDK imports and account credential field names.  The domain guard would
have been satisfied by a broker SDK imported from an adapter, and that violation is
one pip install plus one import away."
```

---

### Task 2: `application/order_intents.py` —— pre-trade risk、SoD 审批与 kill switch

对应 Step 09 Task 2 逐字：「新增 `application/order_intents.py`、permission policies 和 audit；
复用 P9 approval，测试 SoD、expired/scope mismatch/kill switch denial。」

**本 Task 是整个平台里唯一一条能让一个决定影响账户的路径，因此它的测试全部是负向测试优先。**

四条设计约束：

1. **不新增 `Permission` 枚举值，不改 `PermissionPolicy.default()`。** 泛化在服务层做。
2. **不新造审批合同。** 复用 P-8 的 `ApprovalReview`，只加一个
   `ApprovalSubjectKind.ORDER_INTENT`。
3. **pre-trade risk 只消费已批准的 target/policy 与市场状态，不消费页面字段**
   （Step 09 Spec 逐字）。风险函数的签名里没有任何来自 HTTP 请求的原始值。
4. **kill switch 是最后一道门**，在权限、风险、审批全部通过之后（陷阱三）。

**Files:**
- Create: `platform/src/a_share_platform/application/order_intents.py`
- Create: `platform/src/a_share_platform/domain/pre_trade_risk.py`
- Test: `platform/tests/test_pre_trade_risk.py`
- Test: `platform/tests/test_order_intent_segregation_of_duties.py`
- Test: `platform/tests/test_order_intent_kill_switch.py`
- Test: `platform/tests/test_order_intent_permission_matrix.py`

**Interfaces:**
- Consumes: `application/permissions.py`（原样）、P-8 的 `domain/approvals.py`
  （`ApprovalReview` / `ApprovalSubject` / `ApprovalSubjectKind` / `SUBJECT_PERMISSION`）、
  `domain/factor_lifecycle.py` 的 `ApprovalScope`（原样复用四值枚举）、
  P-5 的 `PortfolioPolicy` / `evaluate_eligibility()`、Task 1 的 `domain/oms.py`
- Produces:
  ```python
  class RiskCheckStatus(StrEnum):
      PASSED = "passed"
      BREACHED = "breached"
      UNAVAILABLE = "unavailable"   # 缺输入无法判定，禁止当作 passed

  class DenialReason(StrEnum):
      """Why an order was not sent.  Each value is a distinct, auditable cause."""
      MISSING_SEND_ORDER_PERMISSION = "missing_send_order_permission"
      RISK_BREACHED = "risk_breached"
      RISK_UNAVAILABLE = "risk_unavailable"
      NOT_APPROVED = "not_approved"
      APPROVAL_EXPIRED = "approval_expired"
      APPROVAL_SCOPE_MISMATCH = "approval_scope_mismatch"
      APPROVAL_SUPERSEDED = "approval_superseded"
      SELF_APPROVAL = "self_approval"
      KILL_SWITCH_ENGAGED = "kill_switch_engaged"
      MATERIAL_RECONCILIATION_BREAK = "material_reconciliation_break"
      TARGET_HASH_MISMATCH = "target_hash_mismatch"

  @dataclass(frozen=True)
  class PreTradeRiskCheck:
      """SPEC-036 的第三步，作为值对象。"""
      check_id: str
      intent_id: str
      policy_id: str
      policy_hash: str
      status: RiskCheckStatus
      limit_diagnostics: tuple[ConstraintDiagnostic, ...]   # P-5 的类型
      unavailable_reasons: tuple[str, ...]                  # UNAVAILABLE 时必填
      market_state_session: date
      checked_at: datetime
      content_hash: str = field(init=False)

  @dataclass(frozen=True)
  class OrderDecision:
      """The outcome of submit_order(): either an order, or a reason there is none."""
      order: Order | None
      denial_reasons: tuple[DenialReason, ...]
      detail: tuple[str, ...]
      risk_check: PreTradeRiskCheck | None
      audit_entry_id: str          # 允许与拒绝都要有审计条目

  class OrderIntentService:
      def __init__(self, *, permission_policy: PermissionPolicy,
                   approval_repository: ApprovalReviewRepository,
                   kill_switch_repository: KillSwitchRepository,
                   break_repository: ReconciliationBreakRepository,
                   broker: BrokerPort,
                   audit: ExecutionAuditPort,
                   clock: Callable[[], datetime]) -> None: ...

      def submit_order(self, *, principal: Principal, intent: OrderIntent,
                       ) -> OrderDecision: ...
      def cancel_order(self, *, principal: Principal, order_id: str,
                       idempotency: IdempotencyKey) -> OrderDecision: ...
  ```

- [ ] **Step 1: 先读 P-8 的审批合同与本仓库权限矩阵的真实形状**

```bash
cd platform
grep -n "class ApprovalSubjectKind" -A 12 src/a_share_platform/domain/approvals.py
grep -n "class ApprovalSubject" -A 20 src/a_share_platform/domain/approvals.py
grep -n "def authorizes" -A 20 src/a_share_platform/domain/approvals.py
grep -n "SUBJECT_PERMISSION" -A 12 src/a_share_platform/domain/approvals.py
sed -n 46,77p src/a_share_platform/application/permissions.py
grep -n "class ApprovalScope" -A 8 src/a_share_platform/domain/factor_lifecycle.py
```

**已核实的现状（2026-08-16，`application/permissions.py` 逐字）**：

```text
Role.TRADER: read | {Permission.SEND_ORDER},
Role.PORTFOLIO_MANAGER: read | artifact_read | {Permission.APPROVE_PORTFOLIO},
Role.ADMINISTRATOR: frozenset(Permission),
Role.AGENT: read,
```

即：`Role.TRADER` 的完整权限集是 `{READ_PUBLIC, SEND_ORDER}` —— **没有任何 approve 权限**；
`Role.AGENT` 的完整权限集是 `{READ_PUBLIC}` —— 没有 `READ_ARTIFACT`、没有 `SEND_ORDER`；
`Role.ADMINISTRATOR` 拿全部 8 个，**是唯一一个能同时提交与批准的角色**。

- [ ] **Step 2: 写第一个红测 —— Trader 不能批准自己的 intent**

```python
# platform/tests/test_order_intent_segregation_of_duties.py
"""Separation of duties on the only path that can affect an account.

Two halves, and the permission matrix already contains both.  Role.TRADER holds
exactly {READ_PUBLIC, SEND_ORDER} — no APPROVE_PORTFOLIO, no APPROVE_RESEARCH, not
even READ_ARTIFACT — so a trader approving an order intent is not a policy choice
this plan invents, it is a permission the trader does not have.  Role.PORTFOLIO_
MANAGER is the mirror image: APPROVE_PORTFOLIO but no SEND_ORDER.

The failure mode this guards is specific.  An implementation that gates the approval
step on 'can this principal send orders' passes a trader through, because a trader
genuinely can send orders.  The approval gate must ask for APPROVE_PORTFOLIO, which
is the permission a trader will never hold.

Role.ADMINISTRATOR is the dangerous case: frozenset(Permission) means it holds both
SEND_ORDER and APPROVE_PORTFOLIO, so it is the one role that can submit and approve
the same intent through the permission matrix alone.  Separation of duties therefore
cannot live in the matrix; it lives in the service, comparing submitted_by against
actor_id, and it applies to Administrator too.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from a_share_platform.application.order_intents import (
    DenialReason,
    OrderIntentService,
)
from a_share_platform.application.permissions import (
    Permission,
    PermissionPolicy,
    Principal,
    Role,
)

NOW = datetime(2026, 8, 17, 5, 0, tzinfo=UTC)
TRADER = Principal("subject:trader-1", frozenset({Role.TRADER}))
PM = Principal("subject:pm-1", frozenset({Role.PORTFOLIO_MANAGER}))
ADMIN = Principal("subject:admin-1", frozenset({Role.ADMINISTRATOR}))
AGENT = Principal("subject:agent-1", frozenset({Role.AGENT}))
RESEARCHER = Principal("subject:researcher-1", frozenset({Role.RESEARCHER}))


class PermissionMatrixFactsTest(unittest.TestCase):
    """Read straight off the matrix, so a one-line change to it breaks a test."""

    def setUp(self) -> None:
        self.policy = PermissionPolicy.default()

    def test_trader_can_send_orders_but_cannot_approve_anything(self) -> None:
        self.assertTrue(self.policy.allows(TRADER, Permission.SEND_ORDER))
        self.assertFalse(self.policy.allows(TRADER, Permission.APPROVE_PORTFOLIO))
        self.assertFalse(self.policy.allows(TRADER, Permission.APPROVE_RESEARCH))
        self.assertFalse(self.policy.allows(TRADER, Permission.READ_ARTIFACT))

    def test_portfolio_manager_can_approve_but_cannot_send(self) -> None:
        self.assertTrue(self.policy.allows(PM, Permission.APPROVE_PORTFOLIO))
        self.assertFalse(self.policy.allows(PM, Permission.SEND_ORDER))

    def test_administrator_holds_every_permission_including_both_halves(self) -> None:
        """Documented as a test because it is why SoD cannot rely on the matrix."""
        for permission in Permission:
            with self.subTest(permission=permission):
                self.assertTrue(self.policy.allows(ADMIN, permission))

    def test_agent_holds_read_public_only(self) -> None:
        self.assertTrue(self.policy.allows(AGENT, Permission.READ_PUBLIC))
        for permission in Permission:
            if permission is Permission.READ_PUBLIC:
                continue
            with self.subTest(permission=permission):
                self.assertFalse(self.policy.allows(AGENT, permission))

    def test_the_default_grants_are_unchanged_by_this_plan(self) -> None:
        """Generalisation happens in the service layer; two sources of truth for
        'who may approve an order' would eventually disagree."""
        grants = PermissionPolicy.default().grants
        self.assertEqual(grants[Role.TRADER], frozenset({
            Permission.READ_PUBLIC, Permission.SEND_ORDER}))
        self.assertEqual(grants[Role.AGENT], frozenset({Permission.READ_PUBLIC}))
        self.assertEqual(grants[Role.ADMINISTRATOR], frozenset(Permission))
        self.assertEqual(len(tuple(Permission)), 8)


class SelfApprovalTest(unittest.TestCase):
    def test_a_trader_cannot_approve_the_intent_it_submitted(self) -> None:
        service = _service(kill_switch=None, breaks=())
        decision = service.submit_order(
            principal=TRADER,
            intent=_intent(
                submitted_by=TRADER.subject_id,
                approval=_approval(actor_id=TRADER.subject_id,
                                   actor_role="trader"),
            ),
        )
        self.assertIsNone(decision.order)
        self.assertIn(DenialReason.SELF_APPROVAL, decision.denial_reasons)

    def test_an_administrator_cannot_approve_its_own_intent_either(self) -> None:
        """The one role the permission matrix would allow through."""
        service = _service(kill_switch=None, breaks=())
        decision = service.submit_order(
            principal=ADMIN,
            intent=_intent(
                submitted_by=ADMIN.subject_id,
                approval=_approval(actor_id=ADMIN.subject_id,
                                   actor_role="administrator"),
            ),
        )
        self.assertIsNone(decision.order)
        self.assertIn(DenialReason.SELF_APPROVAL, decision.denial_reasons)

    def test_an_approval_from_a_role_without_approve_portfolio_is_refused(self) -> None:
        """Asking for SEND_ORDER at the approval gate would let a trader through."""
        service = _service(kill_switch=None, breaks=())
        decision = service.submit_order(
            principal=TRADER,
            intent=_intent(
                submitted_by=PM.subject_id,
                approval=_approval(actor_id="subject:trader-2",
                                   actor_role="trader"),
            ),
        )
        self.assertIsNone(decision.order)
        self.assertIn(DenialReason.NOT_APPROVED, decision.denial_reasons)

    def test_a_pm_approved_intent_submitted_by_a_trader_is_accepted(self) -> None:
        """The positive case, so the negatives above are not passing vacuously."""
        service = _service(kill_switch=None, breaks=())
        decision = service.submit_order(
            principal=TRADER,
            intent=_intent(
                submitted_by=PM.subject_id,
                approval=_approval(actor_id=PM.subject_id,
                                   actor_role="portfolio_manager"),
            ),
        )
        self.assertIsNotNone(decision.order)
        self.assertEqual(decision.denial_reasons, ())

    def test_a_denial_is_audited_with_the_same_rigour_as_an_acceptance(self) -> None:
        """A denied order is the more interesting record of the two."""
        service = _service(kill_switch=None, breaks=())
        decision = service.submit_order(
            principal=TRADER,
            intent=_intent(submitted_by=TRADER.subject_id,
                           approval=_approval(actor_id=TRADER.subject_id,
                                              actor_role="trader")),
        )
        self.assertTrue(decision.audit_entry_id)


class NoExecutionPathTest(unittest.TestCase):
    def test_an_agent_has_no_execution_path_at_all(self) -> None:
        """Step 09 Spec: 'Agent 和研究服务没有 order command 权限'.  Denied at the
        first gate, before risk, approval or the broker are consulted — an Agent must
        not even cause a risk check to run."""
        service = _service(kill_switch=None, breaks=())
        decision = service.submit_order(principal=AGENT, intent=_intent())
        self.assertIsNone(decision.order)
        self.assertEqual(
            decision.denial_reasons,
            (DenialReason.MISSING_SEND_ORDER_PERMISSION,),
        )
        self.assertIsNone(decision.risk_check)

    def test_a_researcher_has_no_execution_path_either(self) -> None:
        """SPEC-037: research services cannot call the broker adapter."""
        service = _service(kill_switch=None, breaks=())
        decision = service.submit_order(principal=RESEARCHER, intent=_intent())
        self.assertIsNone(decision.order)
        self.assertIn(
            DenialReason.MISSING_SEND_ORDER_PERMISSION, decision.denial_reasons
        )

    def test_an_agent_never_reaches_the_broker(self) -> None:
        """Asserted on the broker itself: the permission check is upstream of it."""
        broker = _recording_broker()
        service = _service(kill_switch=None, breaks=(), broker=broker)
        service.submit_order(principal=AGENT, intent=_intent())
        self.assertEqual(broker.submitted, [])

    def test_an_agent_mixed_with_a_trader_role_is_still_a_trader(self) -> None:
        """Deny-by-default is per-permission, not per-principal, so a mixed
        principal is allowed — and that is the correct reading of the matrix.  This
        test exists to state it explicitly rather than leave it ambiguous, and to
        record that entitlement hygiene is an administration concern, not a
        service-layer one."""
        mixed = Principal("subject:mixed-1", frozenset({Role.AGENT, Role.TRADER}))
        self.assertTrue(PermissionPolicy.default().allows(mixed, Permission.SEND_ORDER))

    def test_an_anonymous_principal_cannot_submit(self) -> None:
        service = _service(kill_switch=None, breaks=())
        decision = service.submit_order(
            principal=Principal.anonymous(), intent=_intent()
        )
        self.assertIsNone(decision.order)
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_order_intent_segregation_of_duties -v`

Expected: FAIL —— `application.order_intents` 不存在。抄真实错误进 Evidence。

**注意 `PermissionMatrixFactsTest` 那一组应当立刻通过**（它只读既有矩阵）。
若它失败，说明权限矩阵在本 plan 之前已被改动 —— **停下来查清**，不要顺手改回。

- [ ] **Step 4: 最小实现 —— 只做权限门与 SoD，不做风险与 kill switch**

顺序固定为：权限 → 风险 → 审批（含 SoD/expiry/scope/supersede）→ kill switch → break。
本步只实现第一与第三段，风险返回 `UNAVAILABLE` 占位。

**返回 `UNAVAILABLE` 时必须拒绝下单**（`DenialReason.RISK_UNAVAILABLE`），
不得当作通过 —— 那是「缺输入即放行」，是本 plan 最危险的默认值。

- [ ] **Step 5: 转绿 → 写风险红测**

```python
# platform/tests/test_pre_trade_risk.py
"""Pre-trade risk consumes approved targets and market state, never page fields.

Step 09 Spec: 'pre-trade risk 消费 approved target/policy/market state，不消费页面字段'.
The reason is concrete: a limit supplied by the caller is a limit the caller can
choose, so the check would validate the request against itself.  The function
signature therefore takes a PortfolioPolicy and a market state and nothing that
originated in an HTTP body.

The second discipline is that UNAVAILABLE is not PASSED.  A missing market state
means the check could not be performed, and an implementation that treats that as a
pass turns every data outage into an unchecked order.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from decimal import Decimal

from a_share_platform.domain.pre_trade_risk import (
    RiskCheckStatus,
    check_pre_trade_risk,
)


class RiskInputDisciplineTest(unittest.TestCase):
    def test_a_missing_market_state_is_unavailable_not_passed(self) -> None:
        result = check_pre_trade_risk(
            intent=_intent(), policy=_policy(), market_state=None,
            bar=_bar(), price_limit=_limit(), positions=(), cash=_cash(),
            checked_at=NOW,
        )
        self.assertIs(result.status, RiskCheckStatus.UNAVAILABLE)
        self.assertTrue(result.unavailable_reasons)

    def test_the_signature_accepts_no_caller_supplied_limit(self) -> None:
        """A limit the caller can choose is not a limit."""
        import inspect

        parameters = set(inspect.signature(check_pre_trade_risk).parameters)
        for forbidden in ("limit", "max_weight", "override", "requested_limit"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, parameters)

    def test_a_single_name_limit_breach_is_reported_with_the_observed_value(self) -> None:
        """A breach without the number is not actionable."""
        result = check_pre_trade_risk(
            intent=_intent(shares=500_000), policy=_policy(
                single_name_weight_limit=Decimal("0.05")),
            market_state=_state(), bar=_bar(), price_limit=_limit(),
            positions=(), cash=_cash(), checked_at=NOW,
        )
        self.assertIs(result.status, RiskCheckStatus.BREACHED)
        breached = [d for d in result.limit_diagnostics if d.observed is not None]
        self.assertTrue(breached)

    def test_a_suspended_listing_breaches_rather_than_silently_zeroing(self) -> None:
        result = check_pre_trade_risk(
            intent=_intent(), policy=_policy(),
            market_state=_state(is_trading=False, is_suspended=True),
            bar=_bar(), price_limit=_limit(), positions=(), cash=_cash(),
            checked_at=NOW,
        )
        self.assertIs(result.status, RiskCheckStatus.BREACHED)

    def test_insufficient_cash_breaches_and_names_the_shortfall(self) -> None:
        result = check_pre_trade_risk(
            intent=_intent(shares=100_000), policy=_policy(),
            market_state=_state(), bar=_bar(), price_limit=_limit(),
            positions=(), cash=_cash(available=Decimal("1000.00")),
            checked_at=NOW,
        )
        self.assertIs(result.status, RiskCheckStatus.BREACHED)

    def test_the_check_reuses_the_p5_eligibility_rules_rather_than_reimplementing(self) -> None:
        """A second T+1 implementation in the paper path would be a second source of
        truth for a rule that decides whether an order can legally exist."""
        import a_share_platform.domain.pre_trade_risk as module
        source = inspect.getsource(module)
        self.assertIn("evaluate_eligibility", source)

    def test_the_check_hash_covers_the_policy_hash(self) -> None:
        """Two checks under different policies must never share a hash."""
        strict = check_pre_trade_risk(
            intent=_intent(), policy=_policy(single_name_weight_limit=Decimal("0.05")),
            market_state=_state(), bar=_bar(), price_limit=_limit(),
            positions=(), cash=_cash(), checked_at=NOW,
        )
        loose = check_pre_trade_risk(
            intent=_intent(), policy=_policy(single_name_weight_limit=Decimal("0.10")),
            market_state=_state(), bar=_bar(), price_limit=_limit(),
            positions=(), cash=_cash(), checked_at=NOW,
        )
        self.assertNotEqual(strict.content_hash, loose.content_hash)

    def test_a_target_hash_mismatch_refuses_before_any_limit_is_evaluated(self) -> None:
        """If the intent does not match the approved target it is not the approved
        order, whatever its numbers look like."""
        result = check_pre_trade_risk(
            intent=_intent(target_hash="f" * 64), policy=_policy(),
            market_state=_state(), bar=_bar(), price_limit=_limit(),
            positions=(), cash=_cash(), checked_at=NOW,
            expected_target_hash="a" * 64,
        )
        self.assertIs(result.status, RiskCheckStatus.BREACHED)
```

- [ ] **Step 6: 实现风险检查 → 转绿**

**必须调用 P-5 的 `evaluate_eligibility()`**，不得重新实现停牌/涨跌停/T+1/整手判定。

- [ ] **Step 7: 写审批 expiry / scope / supersede 红测**

至少四个断言，全部复用 P-8 的 `ApprovalReview.authorizes()`：

```python
class ApprovalGateTest(unittest.TestCase):
    def test_an_expired_approval_does_not_authorise(self) -> None:
        """Including the boundary instant: an approval that expires at T does not
        authorise at T."""
        ...   # 断言 DenialReason.APPROVAL_EXPIRED

    def test_a_research_backtest_scope_does_not_authorise_a_paper_order(self) -> None:
        """SPEC-023: the four scopes do not imply one another.  research_backtest is
        the scope most likely to be present, which makes it the most likely to be
        accepted by mistake."""
        ...   # 断言 DenialReason.APPROVAL_SCOPE_MISMATCH

    def test_a_shadow_scope_does_not_authorise_a_paper_order(self) -> None:
        ...   # 断言 DenialReason.APPROVAL_SCOPE_MISMATCH

    def test_a_limited_live_scope_is_refused_rather_than_treated_as_stronger(self) -> None:
        """ADR-0010 decision 6: P11 needs a new explicit authorisation.  A
        limited_live approval appearing in a paper service is a governance anomaly,
        not a superset, so it is refused and audited rather than accepted."""
        ...   # 断言 DenialReason.APPROVAL_SCOPE_MISMATCH 且审计条目存在

    def test_a_superseded_approval_does_not_authorise(self) -> None:
        ...   # 断言 DenialReason.APPROVAL_SUPERSEDED

    def test_an_intent_with_no_approval_is_refused(self) -> None:
        ...   # approval_review_id is None → DenialReason.NOT_APPROVED
```

第四个断言（`limited_live` 被拒而非当作更强）是 ADR-0010 决策 6 的可执行形式。
把 `limited_live` 当成「比 paper 更高所以也能用」的实现，正是那种一行改动
就打开真实交易的形状。

- [ ] **Step 8: 写 kill switch 红测（本 Task 最重要的一组）**

```python
# platform/tests/test_order_intent_kill_switch.py
"""The kill switch blocks at the intent layer, not in the UI.

Greying out a button is a frontend state, and `if killed: return 403` in one endpoint
only stops requests that pass through that endpoint — workers, replay, recovery and
any second endpoint added later all bypass it.  docs/18 §3.6 states it plainly:
前端隐藏不是权限.

The load-bearing case is the one below: a kill switch must deny an intent that has
already passed risk and approval.  If it only ran before those gates, an intent
approved yesterday would still reach the broker today — and 'yesterday's judgement is
no longer valid' is precisely the situation a kill switch exists for.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from a_share_platform.application.order_intents import DenialReason
from a_share_platform.domain.oms import KillSwitchState

NOW = datetime(2026, 8, 17, 5, 0, tzinfo=UTC)


class KillSwitchDenialTest(unittest.TestCase):
    def test_a_kill_switch_denies_an_intent_that_already_passed_risk_and_approval(
        self,
    ) -> None:
        """The single assertion that makes this a kill switch rather than a hidden
        button."""
        service = _service(kill_switch=_engaged(scope="global"), breaks=())
        decision = service.submit_order(
            principal=TRADER,
            intent=_intent(submitted_by=PM.subject_id,
                           approval=_approval(actor_id=PM.subject_id,
                                              actor_role="portfolio_manager")),
        )
        self.assertIsNone(decision.order)
        self.assertIn(DenialReason.KILL_SWITCH_ENGAGED, decision.denial_reasons)
        # Risk really did run and really did pass: the switch is the last gate.
        self.assertIsNotNone(decision.risk_check)
        self.assertIs(decision.risk_check.status, RiskCheckStatus.PASSED)

    def test_the_kill_switch_does_not_revoke_the_approval_it_blocked(self) -> None:
        """Blocking is not un-approving.  Rewriting the approval would destroy the
        record of what was approved and when."""
        approval = _approval(actor_id=PM.subject_id, actor_role="portfolio_manager")
        before = approval.content_hash
        service = _service(kill_switch=_engaged(scope="global"), breaks=())
        service.submit_order(
            principal=TRADER,
            intent=_intent(submitted_by=PM.subject_id, approval=approval),
        )
        self.assertEqual(approval.content_hash, before)

    def test_the_kill_switch_never_reaches_the_broker(self) -> None:
        broker = _recording_broker()
        service = _service(kill_switch=_engaged(scope="global"), breaks=(),
                           broker=broker)
        service.submit_order(
            principal=TRADER,
            intent=_intent(submitted_by=PM.subject_id,
                           approval=_approval(actor_id=PM.subject_id,
                                              actor_role="portfolio_manager")),
        )
        self.assertEqual(broker.submitted, [])

    def test_a_policy_scoped_switch_blocks_that_policy_only(self) -> None:
        service = _service(kill_switch=_engaged(scope="policy:policy.core"), breaks=())
        blocked = service.submit_order(
            principal=TRADER, intent=_intent(policy_id="policy.core",
                                             submitted_by=PM.subject_id,
                                             approval=_pm_approval()),
        )
        allowed = service.submit_order(
            principal=TRADER, intent=_intent(policy_id="policy.satellite",
                                             submitted_by=PM.subject_id,
                                             approval=_pm_approval(),
                                             key="client-key-0002"),
        )
        self.assertIsNone(blocked.order)
        self.assertIsNotNone(allowed.order)

    def test_a_security_scoped_switch_blocks_that_security_only(self) -> None:
        ...

    def test_a_released_switch_stops_blocking(self) -> None:
        service = _service(kill_switch=_released(), breaks=())
        decision = service.submit_order(
            principal=TRADER, intent=_intent(submitted_by=PM.subject_id,
                                             approval=_pm_approval()))
        self.assertIsNotNone(decision.order)

    def test_engaging_a_switch_requires_a_reason_and_an_actor(self) -> None:
        """An unexplained kill switch cannot be reviewed afterwards."""
        with self.assertRaises(ValueError):
            KillSwitchState(
                kill_switch_id="kill:0001", scope="global", engaged=True,
                reason="   ", actor_id="subject:admin-1", effective_at=NOW,
                released_at=None,
            )

    def test_releasing_a_switch_also_requires_a_reason(self) -> None:
        ...

    def test_a_cancel_command_is_not_blocked_by_the_kill_switch(self) -> None:
        """The switch stops new risk being taken; it must not trap existing orders.
        Blocking cancels during a kill switch would be the worst possible behaviour:
        the operator has decided to stop and cannot unwind."""
        service = _service(kill_switch=_engaged(scope="global"), breaks=())
        decision = service.cancel_order(
            principal=TRADER, order_id="order:0001",
            idempotency=_key("cancel_order", "client-key-9001"),
        )
        self.assertNotIn(DenialReason.KILL_SWITCH_ENGAGED, decision.denial_reasons)

    def test_a_material_break_blocks_through_a_separate_reason(self) -> None:
        """SPEC-038 requires new orders to stop on an unbalanced book.  It is a
        distinct DenialReason from the kill switch so that 'why did trading stop'
        keeps its answer."""
        service = _service(kill_switch=None, breaks=(_material_break(),))
        decision = service.submit_order(
            principal=TRADER, intent=_intent(submitted_by=PM.subject_id,
                                             approval=_pm_approval()))
        self.assertIn(
            DenialReason.MATERIAL_RECONCILIATION_BREAK, decision.denial_reasons
        )

    def test_an_immaterial_break_does_not_block(self) -> None:
        """Otherwise every rounding difference halts the desk and the stop loses
        meaning."""
        ...
```

- [ ] **Step 9: 转绿 → 补审计**

允许与拒绝**都**写审计条目（`ExecutionAuditPort`）。审计条目至少含：
principal、intent id、全部 `DenialReason`、risk check id、approval review id、
kill switch id（若命中）、时间与 `content_hash`。**审计不可删除。**

- [ ] **Step 10: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/application/order_intents.py \
  platform/src/a_share_platform/domain/pre_trade_risk.py \
  platform/tests/test_pre_trade_risk.py \
  platform/tests/test_order_intent_segregation_of_duties.py \
  platform/tests/test_order_intent_kill_switch.py \
  platform/tests/test_order_intent_permission_matrix.py
git commit -m "feat: gate order intents on risk, separated approval and a kill switch

The permission matrix already contained both halves of separation of duties, so this
service makes them enforceable rather than inventing them.  Role.TRADER holds exactly
READ_PUBLIC and SEND_ORDER — no approval permission and not even READ_ARTIFACT —
while Role.PORTFOLIO_MANAGER holds APPROVE_PORTFOLIO and no SEND_ORDER.  The trap is
gating the approval step on 'can this principal send orders', which lets a trader
approve its own intent because a trader genuinely can send orders; the gate asks for
APPROVE_PORTFOLIO instead, which a trader will never hold.

Role.ADMINISTRATOR is the case that proves the matrix is not enough.  It receives
frozenset(Permission), so it holds both halves and could submit and approve the same
intent on permissions alone.  Separation of duties therefore compares submitted_by
against actor_id in the service, and it applies to Administrator like everyone else.

An Agent has no execution path at all rather than a path that is refused late.  It is
denied at the first gate, before risk runs and before the broker is consulted, and a
test asserts on the broker itself that nothing arrived.  A researcher is denied the
same way, which is SPEC-037's rule that research services cannot call the broker
adapter.

Risk consumes an approved policy and a market state and nothing that originated in a
request body, because a limit the caller can supply is a limit the caller can choose,
and the check would then validate the request against itself.  A missing market state
reports unavailable, and unavailable denies the order: treating it as a pass would
turn every data outage into an unchecked order.  The check calls P-5's
evaluate_eligibility rather than re-deriving T+1 or price limits, since a second
implementation of a rule that decides whether an order may legally exist is a second
source of truth.

The kill switch is the last gate, after risk and approval have both passed, and the
test that matters constructs exactly that situation: approved yesterday, risk green
today, switch engaged, order denied.  A switch that ran before those gates would let
an intent approved yesterday reach the broker today, which is the one situation a
kill switch exists for.  It blocks new orders and deliberately does not block cancels
— trapping existing orders while the operator has decided to stop would be the worst
available behaviour.  Blocking also does not revoke the approval it blocked, because
rewriting the approval would destroy the record of what was approved and when.

A material reconciliation break stops new orders through its own denial reason rather
than sharing the kill switch's, so 'why did trading stop' keeps a distinct answer.  An
immaterial break does not stop anything, or every rounding difference would halt the
desk and the stop would lose its meaning.

A limited_live approval reaching this service is refused and audited rather than
treated as a stronger form of paper.  ADR-0010 decision 6 requires a new explicit
authorisation for P11, and 'higher scope therefore also valid' is exactly the
one-line reading that would open real trading."
```

---

### Task 3: `ports/broker.py` + `adapters/paper/broker.py` —— 确定性内部 Paper Broker

对应 Step 09 Task 3 逐字：「新增 `ports/broker.py`、`adapters/paper/broker.py`、
clock/quote/fill policy tests；支持 ack/reject/partial/delay/disconnect 场景，
**禁止导入真实交易 SDK**。」

ADR-0010 决策 1 与 3 逐字：「P10 第一版使用确定性内部 Paper Broker adapter，
不连接任何真实或券商模拟账户」；「Paper fill policy 复用 ADR-0006 的
session/VWAP/费用/公司行动版本，并支持 ack/reject/partial fill/delay/disconnect 的
确定性故障 fixture」。

**「确定性」是这个 adapter 的全部价值。** 同一输入序列必须产生逐字节相同的
事件序列，否则 Task 7 的 replay 与恢复演练无法验证任何东西
—— 你无法区分「恢复错了」与「broker 这次答得不一样」。

**Files:**
- Create: `platform/src/a_share_platform/ports/broker.py`
- Create: `platform/src/a_share_platform/adapters/paper/__init__.py`
- Create: `platform/src/a_share_platform/adapters/paper/broker.py`
- Create: `platform/src/a_share_platform/adapters/paper/fill_policy.py`
- Create: `platform/src/a_share_platform/adapters/paper/fixtures.py`（故障场景，非 runtime fixture）
- Test: `platform/tests/test_broker_port_contract.py`
- Test: `platform/tests/test_paper_broker_determinism.py`
- Test: `platform/tests/test_paper_fill_policy.py`
- Test: `platform/tests/test_paper_broker_failure_scenarios.py`

**Interfaces:**
- Consumes: Task 1 的 `domain/oms.py`、P-5 的 `execution_rules`
  （`ExecutionRuleSet` / `CostModel` / `evaluate_eligibility` / `cap_by_participation` /
  `compute_costs`）、`domain/market_data.py`（`DailyBar` / `DailyMarketState` /
  `PriceLimit` / `ExchangeCalendar`）
- Produces:
  ```python
  # ports/broker.py —— provider-neutral，Paper 与未来 Live 共用（ADR-0010 决策 2）
  class BrokerEventKind(StrEnum):
      ACKNOWLEDGED = "acknowledged"
      REJECTED = "rejected"
      PARTIALLY_FILLED = "partially_filled"
      FILLED = "filled"
      CANCELLED = "cancelled"
      EXPIRED = "expired"
      DISCONNECTED = "disconnected"

  @dataclass(frozen=True)
  class BrokerEvent:
      event_id: str
      broker_order_id: str
      client_order_id: str          # 我方 order_id，用于对齐
      kind: BrokerEventKind
      sequence: int                 # broker 侧单调序号，用于乱序检测
      occurred_at: datetime
      fill: Fill | None             # 仅成交类事件非空
      reject_reason: str | None      # REJECTED 时必填
      content_hash: str = field(init=False)

  class BrokerUnavailable(RuntimeError):
      """The broker connection is down.  Never a silent no-op."""

  class BrokerPort(Protocol):
      def submit(self, *, order: Order, intent: OrderIntent,
                 idempotency: IdempotencyKey) -> tuple[BrokerEvent, ...]: ...
      def cancel(self, *, broker_order_id: str,
                 idempotency: IdempotencyKey) -> tuple[BrokerEvent, ...]: ...
      def poll(self, *, since_sequence: int) -> tuple[BrokerEvent, ...]: ...

  # adapters/paper/fill_policy.py
  @dataclass(frozen=True)
  class PaperFillPolicy:
      """ADR-0010 decision 3: reuses the ADR-0006 session / VWAP / fee /
      corporate-action versions rather than defining its own."""
      policy_id: str
      version: str
      execution_price_policy_id: str    # ADR-0006 决策 4 的 VWAP 口径
      cost_model: CostModel             # P-5 的 content-addressed 费用模型
      rule_set: ExecutionRuleSet        # P-5 的 lot/participation/settlement
      calendar_version_id: str
      corporate_action_policy_version: str
      content_hash: str = field(init=False)

  # adapters/paper/fixtures.py
  class PaperScenario(StrEnum):
      """Deterministic failure fixtures required by ADR-0010 decision 3."""
      ACK_THEN_FILL = "ack_then_fill"
      IMMEDIATE_REJECT = "immediate_reject"
      PARTIAL_THEN_EXPIRE = "partial_then_expire"
      DELAYED_ACK = "delayed_ack"
      DISCONNECT_BEFORE_ACK = "disconnect_before_ack"
      DISCONNECT_AFTER_FILL = "disconnect_after_fill"
      DUPLICATE_FILL_EVENT = "duplicate_fill_event"
      OUT_OF_ORDER_EVENTS = "out_of_order_events"
  ```

- [ ] **Step 1: 写 port 合同红测（先定合同，再定实现）**

```python
# platform/tests/test_broker_port_contract.py
"""The broker port is provider-neutral so that P11 is an adapter swap, not a rewrite.

ADR-0010 decision 2: Paper and a future Live share the Target, Intent, Risk,
Approval, OMS, Position, Cash and Reconciliation core, with only the broker adapter
differing.  That promise is only kept if the port carries nothing paper-specific and
the OMS carries nothing broker-specific, so both directions are asserted.
"""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from a_share_platform.ports import broker as broker_port

PACKAGE_ROOT = Path(broker_port.__file__).resolve().parents[1]


class PortNeutralityTest(unittest.TestCase):
    def test_the_port_module_imports_no_adapter(self) -> None:
        source = inspect.getsource(broker_port)
        self.assertNotIn("adapters", source)

    def test_the_oms_core_does_not_import_any_broker_adapter(self) -> None:
        """If the OMS knew about the paper adapter, swapping it would be a rewrite."""
        tree = ast.parse((PACKAGE_ROOT / "domain" / "oms.py").read_text(encoding="utf-8"))
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
        self.assertEqual(
            [m for m in modules if "adapters" in m or "broker" in m], []
        )

    def test_the_order_carries_exactly_one_broker_specific_field(self) -> None:
        """broker_order_id is unavoidable; anything more means the core has learnt
        about a specific broker."""
        from dataclasses import fields

        from a_share_platform.domain.oms import Order

        names = {field.name for field in fields(Order)}
        broker_specific = {name for name in names if "broker" in name}
        self.assertEqual(broker_specific, {"broker_order_id"})

    def test_no_execution_service_branches_on_the_broker_identity(self) -> None:
        """`if broker == "paper"` is how a shared core quietly stops being shared."""
        hits: list[str] = []
        for relative in ("application/order_intents.py", "domain/oms.py"):
            text = (PACKAGE_ROOT / relative).read_text(encoding="utf-8")
            for needle in ('== "paper"', "== 'paper'", 'is_paper', 'if broker'):
                if needle in text:
                    hits.append(f"{relative}:{needle}")
        self.assertEqual(hits, [])

    def test_broker_unavailable_is_an_exception_not_an_empty_result(self) -> None:
        """An empty event tuple reads as 'nothing happened', which is the one thing a
        disconnect does not mean."""
        self.assertTrue(issubclass(broker_port.BrokerUnavailable, RuntimeError))
```

- [ ] **Step 2: 运行确认红测 → 实现 port → 转绿**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_broker_port_contract -v`

- [ ] **Step 3: 写确定性红测**

```python
# platform/tests/test_paper_broker_determinism.py
"""The paper broker is deterministic, which is the whole reason it exists.

ADR-0010 decision 1 chose an internal deterministic adapter over a broker's own
simulation environment because an account, a network, a clock and a vendor's state
all reduce test determinism and blur the line with real trading authorisation.

Determinism is load-bearing rather than tidy: Task 7 replays event sequences and
restores from backups, and if the broker answered differently on a second run there
would be no way to tell a broken recovery from a broker that simply said something
else this time.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal

from a_share_platform.adapters.paper.broker import DeterministicPaperBroker
from a_share_platform.adapters.paper.fixtures import PaperScenario
from a_share_platform.ports.broker import BrokerEventKind

NOW = datetime(2026, 8, 17, 5, 30, tzinfo=UTC)


def broker(scenario: PaperScenario = PaperScenario.ACK_THEN_FILL) -> DeterministicPaperBroker:
    return DeterministicPaperBroker(
        fill_policy=_policy(),
        market=_market(),
        scenario=scenario,
        clock=lambda: NOW,          # injected: never datetime.now()
    )


class DeterminismTest(unittest.TestCase):
    def test_the_same_order_twice_yields_byte_identical_events(self) -> None:
        first = broker().submit(order=_order(), intent=_intent(), idempotency=_key())
        second = broker().submit(order=_order(), intent=_intent(), idempotency=_key())
        self.assertEqual(
            [event.content_hash for event in first],
            [event.content_hash for event in second],
        )

    def test_the_broker_reads_no_wall_clock(self) -> None:
        """A wall clock makes every event hash different on every run."""
        import inspect

        import a_share_platform.adapters.paper.broker as module

        source = inspect.getsource(module)
        self.assertNotIn("datetime.now", source)
        self.assertNotIn("time.time", source)

    def test_the_broker_makes_no_network_call_and_holds_no_credential(self) -> None:
        """ADR-0010 decision 5, asserted structurally rather than by review."""
        import inspect

        import a_share_platform.adapters.paper.broker as module

        source = inspect.getsource(module)
        for forbidden in ("requests", "httpx", "urllib", "socket", "aiohttp",
                          "password", "token", "secret", "api_key"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_a_resubmitted_idempotency_key_returns_the_original_events(self) -> None:
        """Broker-level idempotency, which is separate from OMS-level idempotency: a
        retry that reaches the broker must not create a second broker order."""
        adapter = broker()
        first = adapter.submit(order=_order(), intent=_intent(), idempotency=_key())
        second = adapter.submit(order=_order(), intent=_intent(), idempotency=_key())
        self.assertEqual(
            [event.event_id for event in first], [event.event_id for event in second]
        )

    def test_broker_sequence_numbers_are_strictly_increasing(self) -> None:
        """Out-of-order detection in Task 7 depends on this."""
        events = broker(PaperScenario.PARTIAL_THEN_EXPIRE).submit(
            order=_order(), intent=_intent(), idempotency=_key()
        )
        sequences = [event.sequence for event in events]
        self.assertEqual(sequences, sorted(set(sequences)))

    def test_every_event_names_the_client_order_it_belongs_to(self) -> None:
        """Without this the OMS cannot align a broker event to its own order, and
        alignment by timestamp is exactly how fills get attached to the wrong order."""
        events = broker().submit(order=_order(order_id="order:0042"),
                                intent=_intent(), idempotency=_key())
        for event in events:
            with self.subTest(event=event.event_id):
                self.assertEqual(event.client_order_id, "order:0042")
```

- [ ] **Step 4: 实现 broker → 转绿**

关键实现约束：

- 时钟通过 `clock: Callable[[], datetime]` 注入，**adapter 内不出现 `datetime.now()`**；
- `event_id` 由 `(client_order_id, sequence, kind)` 派生的确定性 hash，**不用 uuid4**；
- broker 侧幂等表以 `(command_kind, key)` 为键，与 OMS 侧独立
  —— 两层幂等各自失效的场景不同（OMS 侧防重复建单，broker 侧防重复发送）。

- [ ] **Step 5: 写 fill policy 红测（复用 ADR-0006 版本）**

```python
# platform/tests/test_paper_fill_policy.py
"""The paper fill policy reuses ADR-0006's versions rather than choosing its own.

ADR-0010 decision 3 requires it, and the reason is comparability: if the paper fill
reference differed from the backtest fill reference, then a paper result and a
backtest result on the same signal would differ for two reasons at once — the model
and the fill assumption — and neither could be isolated.

ADR-0006 decision 4 fixes the reference: an after-hours decision fills at a
configurable VWAP on the next tradable session.  Decision 6 puts fees, slippage,
impact, participation, price convention and calendar version into the run hash.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from decimal import Decimal

from a_share_platform.adapters.paper.fill_policy import PaperFillPolicy


class PolicyVersioningTest(unittest.TestCase):
    def test_the_policy_hash_covers_the_adr_0006_versions(self) -> None:
        """Changing any one of them must change the hash, or two runs with different
        fill assumptions become indistinguishable."""
        base = _policy()
        for changed in (
            _policy(execution_price_policy_id="price.vwap.first_30min"),
            _policy(calendar_version_id="calendar:XSHG:v2"),
            _policy(corporate_action_policy_version="ca.total_return.v2"),
            _policy(cost_model=_cost_model(commission_rate=Decimal("0.0010"))),
            _policy(rule_set=_rule_set(participation_limit=Decimal("0.10"))),
        ):
            with self.subTest(changed=changed.content_hash[:8]):
                self.assertNotEqual(base.content_hash, changed.content_hash)

    def test_a_fee_schedule_change_is_a_new_version(self) -> None:
        """Not an edit.  Stamp duty went from 0.3% to 0.1% in 2008; a rate edited in
        place would silently change what yesterday's fills cost, and the two
        computations would be indistinguishable in every ledger."""
        old = _cost_model(stamp_duty_rate_sell=Decimal("0.003"))
        new = _cost_model(stamp_duty_rate_sell=Decimal("0.001"))
        self.assertNotEqual(old.content_hash, new.content_hash)
        self.assertNotEqual(old.cost_model_version_id, new.cost_model_version_id)


class FillReferenceTest(unittest.TestCase):
    def test_an_after_hours_decision_fills_on_the_next_tradable_session(self) -> None:
        """ADR-0006 decision 4.  Filling at today's close on a signal generated after
        today's close is look-ahead in the most direct possible form."""
        fill = _policy().resolve_fill(
            intent=_intent(), decided_at=datetime(2026, 8, 17, 8, 0, tzinfo=UTC),
            market=_market(), calendar=_calendar(),
        )
        self.assertEqual(fill.session, date(2026, 8, 18))

    def test_the_next_session_comes_from_the_calendar_not_from_arithmetic(self) -> None:
        """session + one day is wrong across weekends and holidays, and it is wrong
        in the dangerous direction: it makes today's purchase sellable tomorrow, so it
        overstates liquidity."""
        import inspect

        import a_share_platform.adapters.paper.fill_policy as module

        source = inspect.getsource(module)
        self.assertIn("next_session", source)
        self.assertNotIn("timedelta(days=1)", source)

    def test_a_locked_limit_up_refuses_a_buy_rather_than_filling_it(self) -> None:
        """PriceLimit.status_for already distinguishes LOCKED_UP (low == high ==
        upper, no trade below the cap all day) from LIMIT_UP (closed at the cap after
        trading lower).  Collapsing them systematically misstates fill rates, and in
        paper it also produces a ledger entry for a trade that could not have
        happened."""
        events = _broker_locked_up().submit(
            order=_order(), intent=_intent(side="buy"), idempotency=_key()
        )
        kinds = [event.kind for event in events]
        self.assertIn(BrokerEventKind.REJECTED, kinds)

    def test_a_limit_up_close_that_traded_lower_can_fill(self) -> None:
        ...

    def test_the_fill_price_is_unadjusted(self) -> None:
        """DailyBar already refuses anything but PriceAdjustment.UNADJUSTED.  The
        ledger records real cash flows; adjusted prices belong to research only."""
        ...

    def test_participation_capping_reuses_the_p5_function(self) -> None:
        """A second participation implementation would diverge from the backtest's."""
        import inspect

        import a_share_platform.adapters.paper.fill_policy as module

        self.assertIn("cap_by_participation", inspect.getsource(module))

    def test_costs_come_from_compute_costs_rather_than_inline_arithmetic(self) -> None:
        ...

    def test_a_missing_bar_yields_unavailable_rather_than_a_zero_price(self) -> None:
        """A zero fill price would enter the cash ledger as free shares."""
        with self.assertRaises(MarketDataUnavailable):
            _policy().resolve_fill(
                intent=_intent(), decided_at=NOW, market=_market(bars=()),
                calendar=_calendar(),
            )
```

- [ ] **Step 6: 转绿 → 写六个故障场景红测**

```python
# platform/tests/test_paper_broker_failure_scenarios.py
"""ADR-0010 decision 3's deterministic ack / reject / partial / delay / disconnect
fixtures.

These are not edge cases; they are the normal weather of order routing.  An OMS
tested only against ack-then-fill is an OMS that has never been tested.
"""


class ScenarioTest(unittest.TestCase):
    def test_ack_then_fill_produces_two_events_in_order(self) -> None:
        ...

    def test_an_immediate_reject_produces_a_reason(self) -> None:
        """A rejection without a reason cannot be acted on, and Order.rejection_reason
        is a required field when the state is REJECTED."""
        ...

    def test_a_partial_fill_then_expiry_leaves_the_partial_quantity_settled(self) -> None:
        """The half that traded really traded.  An implementation that discards the
        partial on expiry loses shares that exist."""
        ...

    def test_a_delayed_ack_arrives_after_the_submit_call_returns(self) -> None:
        """submit() returning no events is not the same as a rejection, and the OMS
        must keep the order in SUBMITTED rather than assuming failure."""
        events = broker(PaperScenario.DELAYED_ACK).submit(
            order=_order(), intent=_intent(), idempotency=_key()
        )
        self.assertEqual(events, ())
        later = broker(PaperScenario.DELAYED_ACK).poll(since_sequence=0)
        self.assertTrue(later)

    def test_a_disconnect_before_ack_raises_rather_than_returning_nothing(self) -> None:
        """The dangerous ambiguity: did the order reach the broker or not?  Raising
        forces the caller to treat it as unknown; an empty tuple would read as 'not
        sent' and invite a resubmit that becomes a duplicate."""
        with self.assertRaises(BrokerUnavailable):
            broker(PaperScenario.DISCONNECT_BEFORE_ACK).submit(
                order=_order(), intent=_intent(), idempotency=_key()
            )

    def test_a_disconnect_after_fill_still_exposes_the_fill_on_the_next_poll(self) -> None:
        """The worst real-world case: the money moved and the connection dropped
        before we heard.  Recovery must find the fill, not conclude nothing happened."""
        ...

    def test_a_resubmit_after_a_disconnect_does_not_create_a_second_broker_order(self) -> None:
        """This is why broker-level idempotency exists separately from OMS-level."""
        ...

    def test_a_duplicate_fill_event_is_recognised_by_event_id(self) -> None:
        """Task 7 depends on this: replay must not double-count a fill."""
        ...

    def test_out_of_order_events_are_detectable_by_sequence(self) -> None:
        ...
```

- [ ] **Step 7: 转绿 → 确认 `adapters/paper/` 不进 runtime 默认路径**

```bash
cd platform
grep -rn "DeterministicPaperBroker\|adapters.paper" src/a_share_platform/api/ src/a_share_platform/application/ | grep -v order_intents
```

Expected: 除 `application/order_intents.py` 的类型注解外**无命中**。
Paper broker 只能由显式配置的 execution service 注入，**不得成为任何 API 的默认依赖**。

- [ ] **Step 8: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/ports/broker.py \
  platform/src/a_share_platform/adapters/paper/ \
  platform/tests/test_broker_port_contract.py \
  platform/tests/test_paper_broker_determinism.py \
  platform/tests/test_paper_fill_policy.py \
  platform/tests/test_paper_broker_failure_scenarios.py
git commit -m "feat: add a deterministic internal paper broker behind a neutral port

ADR-0010 decision 1 chose an internal deterministic adapter over a broker's own
simulation environment, and determinism is the reason rather than convenience.  Task 7
replays event sequences and restores from backups; if the broker answered differently
on a second run there would be no way to distinguish a broken recovery from a broker
that simply said something else this time.  So the clock is injected, event ids are
derived from the client order id, sequence and kind rather than from uuid4, and a test
asserts the module contains no datetime.now and no network or credential vocabulary at
all.

The port carries nothing paper-specific and the OMS carries nothing broker-specific,
which is decision 2's promise that P11 is an adapter swap rather than a rewrite.  Both
directions are asserted: Order has exactly one field containing 'broker', the OMS
imports no adapter, and neither the OMS nor the intent service contains a branch on
the broker's identity — `if broker == "paper"` is how a shared core quietly stops
being shared.

The fill policy reuses ADR-0006's session, VWAP, fee and corporate-action versions
instead of choosing its own, so a paper result and a backtest result on the same signal
differ for one reason rather than two.  Changing any of those versions changes the
policy hash, and a fee schedule change is a new version rather than an edit: stamp duty
went from 0.3% to 0.1% in 2008, and a rate edited in place would silently change what
yesterday's fills cost with nothing in any ledger to show it.  The next tradable
session comes from the calendar rather than from adding a day, because arithmetic is
wrong across weekends and wrong in the dangerous direction — it makes today's purchase
sellable tomorrow and so overstates liquidity.

LOCKED_UP and LIMIT_UP stay distinct.  PriceLimit.status_for already separates a cap
that never traded below it all day from a close at the cap after trading lower, and
merging them would both misstate fill rates and, in paper, write a ledger entry for a
trade that could not have happened.

The six failure fixtures are the normal weather of order routing rather than edge
cases: an OMS tested only against ack-then-fill has not been tested.  A disconnect
raises rather than returning an empty tuple, because an empty tuple reads as 'not
sent' and invites a resubmit that becomes a duplicate, while raising forces the caller
to treat the outcome as unknown.  A disconnect after a fill still surfaces the fill on
the next poll, which is the worst real case: the money moved and the line dropped
before we heard about it, and recovery must find it rather than conclude nothing
happened.

Broker-level idempotency is kept separate from OMS-level idempotency because the two
protect different things — one stops a second order object being created, the other
stops a second order being sent after a disconnect of unknown outcome."
```

---

### Task 4: 持仓、现金、T+1、公司行动与对账 break 队列

对应 Step 09 Task 4 逐字：「新增 position/cash ledgers、reconciliation service 和 break queue；
测试 T+1、fee、corporate action、cash freeze/release、material stop。」

**本 Task 的核心纪律是账本与视图的区别（陷阱五）。** `PositionLot` 与 `CashLedgerEntry`
是事件累积的**事实**，不是从成交重算出的视图。对账**只读**，只产出 break。

**A 股现金与股份的结算规则不对称，这是最容易写错的一点：**
卖出所得资金**当日可用**（可以立刻买入其他股票），而买入的股份**T+1 才可卖**。
钱的规则与股的规则不同。一个把两者都按 T+1 处理的实现会低估资金可用性；
一个把两者都按 T+0 处理的实现会**高估流动性并允许当日买入当日卖出**
—— 后者在 A 股是违规操作，且会让回测/Paper 结果系统性偏乐观。

**Files:**
- Create: `platform/src/a_share_platform/domain/positions.py`
- Create: `platform/src/a_share_platform/domain/cash.py`
- Create: `platform/src/a_share_platform/domain/reconciliation.py`
- Create: `platform/src/a_share_platform/application/paper_ledgers.py`
- Create: `platform/src/a_share_platform/application/reconciliation_service.py`
- Create: `platform/src/a_share_platform/ports/execution_ledgers.py`
- Create: `platform/src/a_share_platform/adapters/memory/execution_ledgers.py`
- Test: `platform/tests/test_position_lots_t_plus_one.py`
- Test: `platform/tests/test_cash_ledger.py`
- Test: `platform/tests/test_position_corporate_actions.py`
- Test: `platform/tests/test_reconciliation_breaks.py`

**Interfaces:**
- Consumes: Task 1 的 `Fill`、Task 3 的 `BrokerEvent`、`domain/market_data.py` 的
  `CorporateAction` / `CorporateActionType` / `ExchangeCalendar`、P-5 的 `CostModel`、
  P-8 的 `domain/incidents.py`
- Produces:
  ```python
  @dataclass(frozen=True)
  class PositionLot:
      """Step 09 Spec 逐字：trade date/sellable date/qty/cost."""
      lot_id: str
      security_id: str
      listing_id: str
      trade_date: date
      sellable_date: date          # 由 ExchangeCalendar.next_session() 计算
      quantity: int                # 剩余股数；卖出后减少但 lot 不删除（见下）
      original_quantity: int
      cost_per_share: Decimal      # 含费用的持仓成本
      currency: str
      fill_id: str | None          # 由成交产生
      corporate_action_id: str | None   # 由公司行动产生
      cost_model_version_id: str
      created_at: datetime
      content_hash: str = field(init=False)

      def is_sellable_on(self, session: date) -> bool: ...

  class CashEntryReason(StrEnum):
      """Step 09 Spec 逐字：entry reason."""
      BUY_SETTLEMENT = "buy_settlement"
      SELL_PROCEEDS = "sell_proceeds"
      COMMISSION = "commission"
      STAMP_DUTY = "stamp_duty"
      TRANSFER_FEE = "transfer_fee"
      CASH_DIVIDEND = "cash_dividend"
      RIGHTS_SUBSCRIPTION = "rights_subscription"
      OPENING_BALANCE = "opening_balance"
      ORDER_FREEZE = "order_freeze"
      ORDER_RELEASE = "order_release"

  @dataclass(frozen=True)
  class CashLedgerEntry:
      """Step 09 Spec 逐字：currency/available/frozen/settled/entry reason."""
      entry_id: str
      session: date
      reason: CashEntryReason
      currency: str
      available_delta: Decimal     # 可正可负
      frozen_delta: Decimal
      settled_delta: Decimal
      fill_id: str | None
      order_id: str | None
      corporate_action_id: str | None
      cost_model_version_id: str | None
      occurred_at: datetime
      content_hash: str = field(init=False)

  @dataclass(frozen=True)
  class CashBalance:
      currency: str
      available: Decimal
      frozen: Decimal
      settled: Decimal
      as_of_session: date

      def __post_init__(self) -> None: ...   # available/frozen 不得为负

  class BreakKind(StrEnum):
      """Step 09 Spec 逐字：target/order/fill/position/cash mismatch."""
      TARGET_VS_ORDER = "target_vs_order"
      ORDER_VS_FILL = "order_vs_fill"
      FILL_VS_POSITION = "fill_vs_position"
      POSITION_VS_STATEMENT = "position_vs_statement"
      CASH_VS_STATEMENT = "cash_vs_statement"

  class BreakSeverity(StrEnum):
      IMMATERIAL = "immaterial"    # 记录，不阻断
      MATERIAL = "material"        # 阻断新订单 + 创建 Incident
      CRITICAL = "critical"        # 阻断 + Incident + 建议 kill switch

  class BreakState(StrEnum):
      OPEN = "open"
      ACKNOWLEDGED = "acknowledged"
      EXPLAINED = "explained"      # 有解释，差额仍在
      RESOLVED = "resolved"        # 上游修正后重新对账通过
      # 没有 CORRECTED —— 见陷阱四

  @dataclass(frozen=True)
  class ReconciliationBreak:
      """Step 09 Spec 逐字：target/order/fill/position/cash mismatch、severity、
      resolution."""
      break_id: str
      kind: BreakKind
      severity: BreakSeverity
      state: BreakState
      subject_id: str              # 涉及的 target/order/position/security
      expected: Decimal            # 保留原值，永不改写
      observed: Decimal            # 保留原值，永不改写
      difference: Decimal          # observed - expected
      tolerance: Decimal
      session: date
      owner_scope: str             # 必须是 'execution'（ADR-0009 四值之一）
      detected_at: datetime
      resolution_note: str | None   # 人做了什么；不改变差额
      resolved_at: datetime | None
      incident_id: str | None       # MATERIAL 以上必填
      content_hash: str = field(init=False)
  ```

- [ ] **Step 1: 写第一个红测 —— T+1 结算（钱与股的规则不同）**

```python
# platform/tests/test_position_lots_t_plus_one.py
"""A-share settlement is asymmetric, and that asymmetry is the first test.

Sale proceeds are usable the same day — the cash can buy something else this
afternoon — while shares bought today settle T+1 and cannot be sold until the next
trading session.  The money rule and the share rule are different rules.

An implementation that applies T+1 to both understates available cash, which is
merely wrong.  An implementation that applies T+0 to both overstates liquidity and
permits buying and selling the same shares on the same day, which is not permitted on
A-shares at all and makes every paper result systematically optimistic.

The next sellable session comes from the exchange calendar, never from adding a day.
Arithmetic is wrong across weekends and long holidays, and wrong in the direction that
makes today's purchase sellable tomorrow.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from decimal import Decimal

from a_share_platform.domain.market_data import (
    CalendarDay,
    ExchangeCalendar,
    MarketDataUnavailable,
)
from a_share_platform.domain.positions import PositionLot, lots_from_fill
from a_share_platform.domain.security_master import Exchange

NOW = datetime(2026, 8, 17, 7, 0, tzinfo=UTC)


def calendar() -> ExchangeCalendar:
    # Friday 2026-08-14 is a session; the weekend is closed; Monday reopens.
    days = (
        CalendarDay(Exchange.XSHG, date(2026, 8, 14), True, None, "source:calendar"),
        CalendarDay(Exchange.XSHG, date(2026, 8, 15), False, "weekend", "source:calendar"),
        CalendarDay(Exchange.XSHG, date(2026, 8, 16), False, "weekend", "source:calendar"),
        CalendarDay(Exchange.XSHG, date(2026, 8, 17), True, None, "source:calendar"),
    )
    return ExchangeCalendar(Exchange.XSHG, days)


class SettlementTest(unittest.TestCase):
    def test_a_friday_purchase_is_sellable_on_monday_not_saturday(self) -> None:
        """The single assertion that catches `trade_date + timedelta(days=1)`."""
        lot = lots_from_fill(
            fill=_fill(filled_at=datetime(2026, 8, 14, 6, 0, tzinfo=UTC)),
            trade_date=date(2026, 8, 14),
            calendar=calendar(),
            settlement_days=1,
        )[0]
        self.assertEqual(lot.sellable_date, date(2026, 8, 17))

    def test_shares_bought_today_are_not_sellable_today(self) -> None:
        lot = lots_from_fill(
            fill=_fill(), trade_date=date(2026, 8, 14),
            calendar=calendar(), settlement_days=1,
        )[0]
        self.assertFalse(lot.is_sellable_on(date(2026, 8, 14)))
        self.assertTrue(lot.is_sellable_on(date(2026, 8, 17)))

    def test_a_missing_calendar_day_refuses_rather_than_guessing(self) -> None:
        """ExchangeCalendar.next_session already raises MarketDataUnavailable when it
        has no known session after a date.  Guessing here would invent liquidity."""
        empty = ExchangeCalendar(Exchange.XSHG, ())
        with self.assertRaises(MarketDataUnavailable):
            lots_from_fill(fill=_fill(), trade_date=date(2026, 8, 14),
                           calendar=empty, settlement_days=1)

    def test_the_settlement_days_come_from_the_rule_set_not_a_constant(self) -> None:
        """T+1 is an exchange rule with a version, not a mathematical constant."""
        import inspect

        signature = inspect.signature(lots_from_fill)
        self.assertIn("settlement_days", signature.parameters)

    def test_sale_proceeds_are_available_the_same_session(self) -> None:
        """The asymmetry.  Cash from a sale can buy something this afternoon even
        though the shares themselves settle T+1."""
        entries = _cash_entries_from_fill(_fill(side="sell", filled_shares=5_000))
        proceeds = [e for e in entries if e.reason is CashEntryReason.SELL_PROCEEDS]
        self.assertEqual(len(proceeds), 1)
        self.assertGreater(proceeds[0].available_delta, Decimal("0"))
        self.assertEqual(proceeds[0].session, _fill(side="sell").filled_at.date())

    def test_selling_reduces_the_oldest_sellable_lot_first(self) -> None:
        """A declared, testable lot selection rule.  Without one, cost basis depends
        on dictionary ordering and is therefore not reproducible."""
        ...

    def test_selling_more_than_the_sellable_quantity_is_refused(self) -> None:
        """The unsettled portion is not available, and the refusal must name T+1
        rather than reporting a generic shortfall."""
        ...

    def test_a_reduced_lot_is_appended_rather_than_edited(self) -> None:
        """The ledger is append-only.  Editing a lot's quantity in place would erase
        the record of what was held before the sale."""
        ...
```

- [ ] **Step 2: 运行确认红测 → 实现 → 转绿**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_position_lots_t_plus_one -v`

Expected: FAIL —— `domain.positions` 不存在。

- [ ] **Step 3: 写现金账本红测（含 freeze/release 与费用版本）**

```python
# platform/tests/test_cash_ledger.py
"""Cash as an append-only ledger of reasons, not a running number.

A single mutable balance answers 'how much cash is there' and nothing else.  When the
balance disagrees with the broker statement, a number cannot say why, whereas a ledger
of reasons can name the entry that differs.

Fees are versioned rather than constant.  Commission around 0.08% and stamp duty at
0.1% look like common knowledge, but stamp duty was 0.3% before 2008 and the transfer
fee convention has changed several times.  A rate edited in place changes what
yesterday's trades cost, and the two computations are indistinguishable in every
ledger — which is precisely the property a ledger exists to prevent.
"""


class FeeVersioningTest(unittest.TestCase):
    def test_a_fee_schedule_change_produces_a_new_version_not_an_edit(self) -> None:
        old = _cost_model(stamp_duty_rate_sell=Decimal("0.003"))
        new = _cost_model(stamp_duty_rate_sell=Decimal("0.001"))
        self.assertNotEqual(old.cost_model_version_id, new.cost_model_version_id)
        self.assertNotEqual(old.content_hash, new.content_hash)

    def test_an_existing_entry_keeps_its_original_cost_model_version(self) -> None:
        """Upgrading the cost model must not retroactively restate history."""
        entry = _entry(cost_model_version_id="cost.v1")
        before = entry.content_hash
        _upgrade_cost_model_to("cost.v2")
        self.assertEqual(entry.cost_model_version_id, "cost.v1")
        self.assertEqual(entry.content_hash, before)

    def test_stamp_duty_appears_on_sells_only(self) -> None:
        """A-share stamp duty is one-sided.  Charging it on buys makes every purchase
        0.1% more expensive than it was, permanently and invisibly."""
        buy = _entries_from_fill(_fill(side="buy"))
        sell = _entries_from_fill(_fill(side="sell"))
        self.assertNotIn(CashEntryReason.STAMP_DUTY, [e.reason for e in buy])
        self.assertIn(CashEntryReason.STAMP_DUTY, [e.reason for e in sell])

    def test_the_commission_minimum_dominates_a_small_order(self) -> None:
        """Reused from P-5's CostModel; asserted again on the paper path because a
        rule with two consumers needs verifying at both."""
        ...

    def test_a_partial_fill_pays_fees_on_the_filled_quantity_only(self) -> None:
        ...


class FreezeReleaseTest(unittest.TestCase):
    def test_submitting_a_buy_freezes_cash_before_the_fill(self) -> None:
        """Without a freeze, two concurrent orders can each pass a cash check against
        the same balance and together overdraw it."""
        entries = _entries_from_order_submission(_order(side="buy", shares=5_000))
        freeze = [e for e in entries if e.reason is CashEntryReason.ORDER_FREEZE][0]
        self.assertLess(freeze.available_delta, Decimal("0"))
        self.assertGreater(freeze.frozen_delta, Decimal("0"))
        self.assertEqual(freeze.available_delta + freeze.frozen_delta, Decimal("0"))

    def test_a_rejected_order_releases_the_frozen_cash(self) -> None:
        ...

    def test_a_cancelled_order_releases_only_the_unfilled_portion(self) -> None:
        """A partial fill consumed part of the freeze; releasing all of it would
        create cash that does not exist."""
        ...

    def test_an_expired_order_releases_the_freeze(self) -> None:
        ...

    def test_the_available_balance_can_never_go_negative(self) -> None:
        """A negative available balance means the freeze accounting is broken, and the
        correct response is to refuse the entry rather than record an impossible
        state."""
        with self.assertRaises(ValueError):
            CashBalance(currency="CNY", available=Decimal("-1.00"),
                        frozen=Decimal("0"), settled=Decimal("0"),
                        as_of_session=date(2026, 8, 17))

    def test_freeze_and_release_net_to_zero_across_an_order_lifecycle(self) -> None:
        """The property that makes freezes auditable: every freeze is eventually
        matched by a release or a settlement, and the sum is exactly zero."""
        ...

    def test_a_missing_currency_is_refused_rather_than_defaulted_to_cny(self) -> None:
        ...
```

- [ ] **Step 4: 转绿 → 写公司行动红测**

```python
# platform/tests/test_position_corporate_actions.py
"""Corporate actions during a holding period change share counts and cash.

This is not an edge case: over a 2018–2025 holding period the corporate action ledger
already holds 8,059 observations across 777 of 800 listings.  A position that ignores
them drifts away from the broker's record within one dividend season, and the drift
appears as a reconciliation break with no explanation.

CorporateAction already enforces the required fields — a cash dividend needs
cash_per_share, bonus and split need share_ratio, and a rights issue needs both
share_ratio and subscription_price — so these tests assert the position and cash
effects rather than re-validating the input.
"""


class CashDividendTest(unittest.TestCase):
    def test_a_cash_dividend_adds_cash_and_leaves_the_share_count_unchanged(self) -> None:
        lots, entries = apply_corporate_action(
            lots=(_lot(quantity=10_000),),
            action=_action(CorporateActionType.CASH_DIVIDEND,
                           cash_per_share=Decimal("2.50")),
            calendar=_calendar(),
        )
        self.assertEqual(sum(lot.quantity for lot in lots), 10_000)
        dividend = [e for e in entries
                    if e.reason is CashEntryReason.CASH_DIVIDEND][0]
        self.assertEqual(dividend.available_delta, Decimal("25000.00"))

    def test_the_dividend_entry_names_the_corporate_action(self) -> None:
        """Otherwise a cash movement of unknown origin appears in the ledger, and
        reconciliation cannot attribute it."""
        ...

    def test_a_dividend_on_an_ex_date_before_the_lot_existed_is_not_paid(self) -> None:
        """Record date discipline: shares bought after the record date do not receive
        the dividend, and paying it would create cash from nothing."""
        ...


class BonusIssueTest(unittest.TestCase):
    def test_a_bonus_issue_increases_shares_and_reduces_cost_per_share(self) -> None:
        """10-for-10: quantity doubles, total cost is unchanged, so cost per share
        halves.  An implementation that adds shares without restating cost per share
        reports a fictitious gain of exactly 50%."""
        lots, entries = apply_corporate_action(
            lots=(_lot(quantity=10_000, cost_per_share=Decimal("20.00")),),
            action=_action(CorporateActionType.BONUS_SHARE,
                           share_ratio=Decimal("1.0")),
            calendar=_calendar(),
        )
        self.assertEqual(sum(lot.quantity for lot in lots), 20_000)
        total_cost = sum(lot.quantity * lot.cost_per_share for lot in lots)
        self.assertEqual(total_cost, Decimal("200000.00"))
        self.assertEqual(entries, ())          # no cash moves on a bonus issue

    def test_bonus_shares_carry_their_own_sellable_date(self) -> None:
        """They arrive on the ex-date, not on the original trade date."""
        ...

    def test_a_bonus_issue_producing_a_fractional_share_is_refused_not_rounded(self) -> None:
        """A-shares have no fractional shares.  Silent rounding invents or destroys a
        share, and which one depends on the rounding mode."""
        ...


class RightsIssueTest(unittest.TestCase):
    def test_a_subscribed_rights_issue_adds_shares_and_debits_cash(self) -> None:
        """Rights are the only action of the three that requires a decision and moves
        cash outward, so it is the one most likely to be modelled wrongly."""
        lots, entries = apply_corporate_action(
            lots=(_lot(quantity=10_000, cost_per_share=Decimal("20.00")),),
            action=_action(CorporateActionType.RIGHTS_ISSUE,
                           share_ratio=Decimal("0.3"),
                           subscription_price=Decimal("12.00")),
            calendar=_calendar(),
            subscribed=True,
        )
        self.assertEqual(sum(lot.quantity for lot in lots), 13_000)
        debit = [e for e in entries
                 if e.reason is CashEntryReason.RIGHTS_SUBSCRIPTION][0]
        self.assertEqual(debit.available_delta, Decimal("-36000.00"))

    def test_an_unsubscribed_rights_issue_changes_nothing_but_is_recorded(self) -> None:
        """Declining is a decision, and the absence of a record makes it look like the
        action was missed rather than declined."""
        ...

    def test_a_rights_issue_with_insufficient_cash_raises_a_break_not_a_negative_balance(
        self,
    ) -> None:
        ...

    def test_an_action_with_a_missing_ratio_or_price_is_unavailable_not_assumed(self) -> None:
        """CorporateAction already refuses to construct in this case; the assertion
        here is that the ledger surfaces it as unavailable rather than skipping the
        action silently."""
        ...
```

- [ ] **Step 5: 转绿 → 写对账 break 红测（本 Task 最重要的一组）**

```python
# platform/tests/test_reconciliation_breaks.py
"""Reconciliation raises and queues breaks; it never corrects them.

The tempting implementation is the destructive one.  Target 5,000, order 5,000, fills
4,800, position 5,000 — the obvious fix is to set the position to 4,800.  But the
5,000 versus 4,800 difference is the only evidence that exists, and it points at a
specific defect: a partial fill that did not update the position, a lost fill report,
or a fill policy that computed the wrong quantity.  Setting the position to 4,800
balances the book and destroys the evidence, so the defect survives and reappears next
week as a different number.

SPEC-038 states it directly: 账不平时停止新的自动订单并产生 Incident，不允许用人工修改数字掩盖.

The structural defence is that ReconciliationService's signature contains nothing it
could write a position or a cash entry through, which is the same technique P-8 used
for drift calculators.
"""

from __future__ import annotations

import inspect
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal

from a_share_platform.application.reconciliation_service import (
    ReconciliationService,
    reconcile_session,
)
from a_share_platform.domain.reconciliation import (
    BreakKind,
    BreakSeverity,
    BreakState,
    ReconciliationBreak,
)


class BreakIsRaisedNotCorrectedTest(unittest.TestCase):
    def test_a_quantity_mismatch_raises_a_break(self) -> None:
        result = reconcile_session(
            session=date(2026, 8, 17),
            targets=(_target(shares=5_000),),
            orders=(_order(requested=5_000, filled=4_800),),
            fills=(_fill(filled_shares=4_800),),
            lots=(_lot(quantity=5_000),),
            cash=_balance(),
            statement=_statement(shares=4_800),
            tolerances=_tolerances(),
            detected_at=NOW,
        )
        breaks = result.breaks
        self.assertEqual(len(breaks), 1)
        self.assertIs(breaks[0].kind, BreakKind.FILL_VS_POSITION)
        self.assertEqual(breaks[0].expected, Decimal("4800"))
        self.assertEqual(breaks[0].observed, Decimal("5000"))
        self.assertEqual(breaks[0].difference, Decimal("200"))

    def test_reconciliation_does_not_modify_any_position_or_cash_entry(self) -> None:
        """Asserted by hash, over every object, before and after."""
        lots = (_lot(quantity=5_000), _lot(quantity=3_000))
        entries = (_entry(), _entry(reason=CashEntryReason.COMMISSION))
        before = [obj.content_hash for obj in (*lots, *entries)]
        reconcile_session(
            session=date(2026, 8, 17), targets=(_target(shares=5_000),),
            orders=(_order(requested=5_000, filled=4_800),),
            fills=(_fill(filled_shares=4_800),), lots=lots, cash=_balance(),
            statement=_statement(shares=4_800), tolerances=_tolerances(),
            detected_at=NOW,
        )
        after = [obj.content_hash for obj in (*lots, *entries)]
        self.assertEqual(before, after)

    def test_the_service_signature_cannot_write_a_ledger(self) -> None:
        """Structural rather than behavioural: there is no repository, connection or
        session in the signature, so there is nothing to write through."""
        parameters = set(inspect.signature(reconcile_session).parameters)
        for forbidden in ("repository", "connection", "session_factory", "store",
                          "ledger_writer"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, parameters)

    def test_there_is_no_corrected_break_state(self) -> None:
        """EXPLAINED keeps the difference and adds a reason; RESOLVED means a later
        reconciliation genuinely balanced after an upstream fix.  A CORRECTED state
        would be a place to record 'we changed the number', which is the behaviour
        SPEC-038 forbids."""
        self.assertEqual(
            {state.value for state in BreakState},
            {"open", "acknowledged", "explained", "resolved"},
        )

    def test_an_explained_break_keeps_its_original_difference(self) -> None:
        raised = _break(expected=Decimal("4800"), observed=Decimal("5000"))
        explained = raised.explain(note="fill report lost in a provider outage",
                                   at=NOW)
        self.assertEqual(explained.difference, raised.difference)
        self.assertEqual(explained.expected, raised.expected)
        self.assertEqual(explained.observed, raised.observed)
        self.assertIs(explained.state, BreakState.EXPLAINED)

    def test_a_resolved_break_requires_a_later_balanced_reconciliation(self) -> None:
        """Resolution is a fact about a later run, not a claim someone can type."""
        ...


class SeverityAndStopTest(unittest.TestCase):
    def test_a_difference_within_tolerance_is_immaterial(self) -> None:
        """Otherwise every rounding difference halts the desk."""
        ...

    def test_a_material_break_creates_an_incident(self) -> None:
        """SPEC-038: 账不平时停止新的自动订单并产生 Incident."""
        result = reconcile_session(...)
        self.assertIsNotNone(result.breaks[0].incident_id)

    def test_an_immaterial_break_does_not_create_an_incident(self) -> None:
        """500 incidents from rounding differences is how the incident list becomes
        unreadable, and a genuine second fault then hides in the noise."""
        ...

    def test_every_break_is_owned_by_the_execution_scope(self) -> None:
        """ADR-0009 fixed four owner scopes.  This plan is the first time the
        execution scope has any real event to route."""
        ...

    def test_the_break_queue_is_ordered_by_severity_then_detection_time(self) -> None:
        """Server-side ordering: the frontend must not decide what is urgent."""
        ...

    def test_a_break_id_is_stable_for_the_same_disagreement(self) -> None:
        """Re-running reconciliation on the same unresolved disagreement must not
        create a second break — that is the same deduplication problem P-8 solved for
        alerts, and the same failure mode: 500 rows nobody reads."""
        first = reconcile_session(...)
        second = reconcile_session(...)
        self.assertEqual(first.breaks[0].break_id, second.breaks[0].break_id)

    def test_the_break_records_how_many_times_it_was_detected(self) -> None:
        """Deduplication must not hide scale, exactly as in P-8's alert contract."""
        ...


class FiveMismatchKindsTest(unittest.TestCase):
    def test_target_versus_order_mismatch_is_detected(self) -> None:
        ...

    def test_order_versus_fill_mismatch_is_detected(self) -> None:
        ...

    def test_fill_versus_position_mismatch_is_detected(self) -> None:
        ...

    def test_position_versus_statement_mismatch_is_detected(self) -> None:
        ...

    def test_cash_versus_statement_mismatch_is_detected(self) -> None:
        ...

    def test_a_balanced_session_produces_no_breaks_and_says_so(self) -> None:
        """An empty break tuple plus an explicit 'balanced' status, because an empty
        list is also what a reconciliation that never ran would return."""
        result = reconcile_session(...)
        self.assertEqual(result.breaks, ())
        self.assertTrue(result.balanced)
        self.assertEqual(result.checks_performed, 5)

    def test_a_missing_statement_yields_unavailable_rather_than_balanced(self) -> None:
        """No statement means the check could not run.  Reporting 'balanced' would be
        the most dangerous possible output of a reconciliation system."""
        result = reconcile_session(..., statement=None)
        self.assertFalse(result.balanced)
        self.assertTrue(result.unavailable_reasons)
```

- [ ] **Step 6: 转绿 → 日终闭合断言**

Step 09 验收逐字：「target/order/fill/position/cash 日终闭合」。
增加一个独立测试断言五者的**数量与金额双向闭合**：
`sum(fills) == position delta` 且 `sum(cash entries) == cash balance delta`。
**闭合失败必须 fail，不得吸收进任何 `other` 分项**（与 P-8 的归因残差同一纪律）。

- [ ] **Step 7: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/domain/positions.py \
  platform/src/a_share_platform/domain/cash.py \
  platform/src/a_share_platform/domain/reconciliation.py \
  platform/src/a_share_platform/application/paper_ledgers.py \
  platform/src/a_share_platform/application/reconciliation_service.py \
  platform/src/a_share_platform/ports/execution_ledgers.py \
  platform/src/a_share_platform/adapters/memory/execution_ledgers.py \
  platform/tests/test_position_lots_t_plus_one.py \
  platform/tests/test_cash_ledger.py \
  platform/tests/test_position_corporate_actions.py \
  platform/tests/test_reconciliation_breaks.py
git commit -m "feat: add T+1 position lots, a reasoned cash ledger and a break queue

A-share settlement is asymmetric and the asymmetry is the first test.  Sale proceeds
are usable the same session while shares bought today settle T+1, so the money rule and
the share rule are different rules.  Applying T+1 to both merely understates cash;
applying T+0 to both overstates liquidity and permits same-day round trips that are not
allowed on A-shares at all, which makes every paper result optimistic in a way no
summary statistic reveals.  The next sellable session comes from the exchange calendar
rather than from adding a day, because arithmetic is wrong across weekends and wrong in
the direction that invents liquidity.

Positions and cash are append-only ledgers of events rather than views recomputed from
fills.  The distinction is load-bearing: a recomputed position would change
retroactively when the fill policy version changes, and historical positions have
already been used for historical reconciliation.  A ledger entry keeps the cost model
version it was written under, so upgrading fees affects new fills only.

Fees are versioned because they change.  Stamp duty was 0.3% before 2008 and it applies
to sells only — charging it on buys makes every purchase 0.1% more expensive
permanently and invisibly.  A rate edited in place would restate what yesterday's trades
cost with nothing in any ledger to show it, which is the exact property a ledger exists
to prevent.

Cash is frozen at submission rather than at fill, because without a freeze two
concurrent orders can each pass a cash check against the same balance and together
overdraw it.  A cancel releases only the unfilled portion — releasing the whole freeze
after a partial fill would create cash that does not exist — and the available balance
refuses to go negative rather than recording an impossible state.

Corporate actions are not an edge case: the ledger already holds 8,059 observations
across 777 of 800 listings for 2018–2025, so a position that ignores them drifts from
the broker's record within one dividend season and the drift arrives as an unexplained
break.  A bonus issue restates cost per share as well as quantity, since adding shares
without restating cost reports a fictitious gain of exactly the bonus ratio.  A
fractional share is refused rather than rounded, because rounding invents or destroys a
share depending on the mode.  A rights issue is the only one of the three that requires
a decision and moves cash outward, and declining is recorded rather than left absent —
absence looks like the action was missed.

Reconciliation raises breaks and never corrects them.  Target 5,000 against fills 4,800
tempts the destructive fix of setting the position to 4,800, but that difference is the
only evidence that exists and it points at a specific defect: a partial fill that did
not update the position, a lost report, or a wrong quantity.  Balancing the book
destroys the evidence, the defect survives, and it returns next week as a different
number.  So the service's signature contains no repository, connection or store —
there is nothing to write through — and a test compares every position and cash hash
before and after a run.  There is deliberately no CORRECTED break state: EXPLAINED
keeps the difference and adds a reason, and RESOLVED is a fact about a later balanced
run rather than a claim someone can type.

Breaks deduplicate on the disagreement rather than the run, because re-running
reconciliation on an unresolved break must not produce a second row; the detection
count is kept so deduplication does not hide scale.  A material break creates an
Incident and stops new orders, an immaterial one does neither — 500 incidents from
rounding differences is how an incident list becomes unreadable and how a genuine
second fault hides in the noise.  A missing statement reports unavailable rather than
balanced, since 'balanced' is the most dangerous output a reconciliation system can
produce when it did not actually check."
```

---

### Task 5: migration、repository、command/read API 与 statement Artifact

对应 Step 09 Task 5 逐字：「新增 execution schema 或经 ADR 选择的职责 schema、
append-only triggers、command/read API、cursor pagination、statement Artifact。」

Step 09 Spec 的 API 段逐字：「command API 使用 authenticated subject、idempotency key、
problem details 和审计；read API 提供 intents/orders/fills/positions/cash/breaks/statements」。

**schema 归属决策（必须先做，不能默认）**：`docs/16-postgresql-data-layering-proposal.md`
定义的六个职责 schema 是 `governance / evidence / observation / canonical / research / serving`。
**Paper 执行数据不属于其中任何一个。** 三个候选：

```text
A. 新增 execution schema          清晰，但增加第七个 schema，需 ADR
B. 放进 serving                   serving 是"用途隔离的 serving registry"，语义不合
C. 放进 research                  最危险：把 paper 账本与研究数据混在一个投影里
```

**本 plan 选 A，并要求先写 ADR-0014**（`docs/adr/0014-paper-execution-schema-ownership.md`）。
理由：`AGENTS.md` 明确要求「用途隔离」，而 Paper 账本与研究数据的用途、
保留期、审计要求、可变性都不同。选 C 会直接违反「不得为了方便查询把 current、strict、
research、paper 数据混在一个无资格投影里」。**ADR 未 Accepted 前不建表。**

**Files:**
- Create: `docs/adr/0014-paper-execution-schema-ownership.md`（先 `Proposed`，用户批准后 `Accepted`）
- Create: `platform/migrations/00NN_p10_execution_schema.sql`（编号见 Step 1）
- Create: `platform/migrations/00NN+1_p10_execution_integrity.sql`
- Create: `platform/src/a_share_platform/adapters/postgres/execution.py`
- Create: `platform/src/a_share_platform/application/execution_workspace.py`
- Modify: `platform/src/a_share_platform/api/app.py`
- Modify: `platform/src/a_share_platform/api/schemas.py`
- Test: `platform/tests/test_p10_migrations.py`
- Test: `platform/tests/test_execution_api_contract.py`
- Test: `platform/tests/test_execution_command_idempotency_api.py`
- Test: `platform/tests/test_execution_workspace_projection.py`
- Test: `platform/tests/test_paper_stage_cannot_be_promoted.py`

**Interfaces:**
- Consumes: Task 1–4 全部；已有 `Envelope` / `response_context` / `ProblemDetails` /
  `RunContextOverrideDenied` handler / P-8 的 cursor pagination（`encode_cursor` /
  `decode_cursor` / `CursorPage`）
- Produces:
  ```text
  GET  /api/execution/intents      ?cursor=&limit=&state=
  GET  /api/execution/orders       ?cursor=&limit=&state=&session=
  GET  /api/execution/orders/{order_id}
  GET  /api/execution/fills        ?cursor=&limit=&session=
  GET  /api/execution/positions    ?session=
  GET  /api/execution/cash         ?session=
  GET  /api/execution/breaks       ?cursor=&limit=&severity=&state=
  GET  /api/execution/statements   ?cursor=&limit=
  GET  /api/execution/kill-switch
  GET  /api/execution/workspace                 # 七分区投影
  POST /api/execution/orders                    # 受控写，需 SEND_ORDER + idempotency
  POST /api/execution/orders/{order_id}/cancel  # 受控写
  POST /api/execution/kill-switch               # 受控写，irreversible
  POST /api/execution/breaks/{break_id}/transitions  # 受控写
  ```

- [ ] **Step 1: 先确认真实 migration 编号与既有约束模式**

```bash
cd platform
ls migrations/ | tail -8
sed -n 1,60p migrations/0032_governance_integrity.sql
grep -n "CREATE SCHEMA" migrations/*.sql | head
grep -n "encode_cursor\|decode_cursor\|class CursorPage" -A 8 \
  src/a_share_platform/application/monitoring_workspace.py
```

**已核实（2026-08-16）**：现有最大编号为 `0036_p5_valuation_bundle_v2.sql`（共 35 个文件）。
P-5 声明 `0037`，P-6 声明 `0037`/`0038`，P-7 声明 `0039`–`0043`，P-8 声明 `0039`–`0041`。
**这些声明互相冲突**（P-7 与 P-8 都要 `0039`–`0041`）。

**本 Task 的正确做法**：执行时先 `ls migrations/` 读真实最大编号再顺延，
**不要沿用本 plan 写的编号**。若发现 P-7 与 P-8 的编号已经冲突，
先报告冲突再继续 —— 那是两份 plan 的问题，不是本 plan 能单方面解决的。

既有 hash 列格式是 `'^sha256:[0-9a-f]{64}$'`（带前缀），而 `domain/signals.py` 的
`_canonical_hash()` 返回**不带前缀**的 64 位 hex。**两者必须在 adapter 层显式转换**，
不能让两种格式同时进同一列。

- [ ] **Step 2: 写 ADR-0014 草案（状态 `Proposed`，不是 `Accepted`）**

内容至少：三个候选方案与理由、为什么 `research` 不可接受（用途隔离）、
新 schema 的表清单、append-only 边界、retention 与备份要求、
以及明确声明「本 ADR 不授权真实交易」。

**状态保持 `Proposed`。** 新增第七个职责 schema 是结构性决定，需用户批准。

- [ ] **Step 3: 写 migration 红测**

```python
# platform/tests/test_p10_migrations.py
"""The execution schema, its append-only triggers and its idempotency indexes.

Two of these constraints cannot live in the application layer and be correct.

Append-only: an application-level guard is bypassed by any second code path — a
worker, a replay, a manual fix during an incident — and an incident is exactly when
someone will reach for a manual fix.  The trigger holds regardless of who connects.

Idempotency: the unique index is the only mechanism that works under concurrency.  An
application that checks-then-writes has a window between the two in which a second
concurrent request also finds nothing and also writes, and network retries make
concurrent duplicates the common case rather than the rare one.
"""

from __future__ import annotations

import os
import unittest


@unittest.skipUnless(os.environ.get("ASP_DATABASE_URL"), "needs a local database")
class ExecutionSchemaTest(unittest.TestCase):
    def test_the_migration_applies_to_an_empty_database(self) -> None:
        ...

    def test_the_migration_is_idempotent(self) -> None:
        ...

    def test_execution_tables_live_outside_research(self) -> None:
        """AGENTS.md forbids mixing current, strict, research and paper data in one
        unqualified projection, and a paper ledger in the research schema is exactly
        that."""
        import psycopg

        with psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True) as conn:
            rows = conn.execute("""
                select table_schema, table_name from information_schema.tables
                where table_name in ('orders', 'fills', 'position_lots',
                                     'cash_ledger_entries', 'reconciliation_breaks',
                                     'kill_switch_states')
            """).fetchall()
        for schema, table in rows:
            with self.subTest(table=table):
                self.assertNotIn(schema, {"research", "serving", "canonical"})

    def test_orders_reject_update_and_delete_at_the_database_level(self) -> None:
        ...

    def test_fills_reject_update_and_delete_at_the_database_level(self) -> None:
        ...

    def test_cash_entries_reject_update_and_delete_at_the_database_level(self) -> None:
        ...

    def test_a_duplicate_idempotency_key_is_rejected_by_a_unique_index(self) -> None:
        """The application-level check is not enough under concurrency."""
        import psycopg

        with psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True) as conn:
            conn.execute(_insert_command("submit_order", "client-key-0001"))
            with self.assertRaises(psycopg.errors.UniqueViolation):
                conn.execute(_insert_command("submit_order", "client-key-0001"))

    def test_the_same_key_under_a_different_command_kind_is_allowed(self) -> None:
        ...

    def test_the_deployment_stage_column_admits_paper_only(self) -> None:
        """A CHECK constraint, so that no code path — including a manual UPDATE during
        an incident — can write limited_live into the execution ledger."""
        import psycopg

        with psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True) as conn:
            with self.assertRaises(psycopg.errors.CheckViolation):
                conn.execute(_insert_order(deployment_stage="limited_live"))

    def test_order_state_is_constrained_to_the_nine_values(self) -> None:
        ...

    def test_filled_shares_cannot_exceed_requested_shares_at_the_database_level(self) -> None:
        """The domain enforces it, and so does the table, because the domain can be
        bypassed by an import or a repair script."""
        ...

    def test_one_open_break_per_disagreement_is_enforced_by_a_partial_unique_index(
        self,
    ) -> None:
        """Same technique P-8 used for one open incident per dedupe key."""
        ...

    def test_a_break_row_cannot_have_its_expected_or_observed_value_updated(self) -> None:
        """The whole point of SPEC-038's prohibition, expressed as a trigger."""
        ...

    def test_an_immaterial_break_cannot_carry_an_incident_id(self) -> None:
        """And a material one must.  Both directions, as CHECK constraints."""
        ...
```

- [ ] **Step 4: 运行（有库时）→ 写 migration → 转绿**

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m unittest tests.test_p10_migrations -v
```

**若本机无库，测试 skip 是正确行为**，但 Evidence 必须写明 skip 而非声称通过。

- [ ] **Step 5: 写 API 阶段隔离红测（ADR-0010 决策 4 的可执行形式）**

```python
# platform/tests/test_paper_stage_cannot_be_promoted.py
"""ADR-0010 decision 4: no request parameter, URL, header or frontend switch promotes
paper to Live.

The existing fixed_read_context already refuses a data_mode or deployment_stage query
parameter and raises RunContextOverrideDenied, which the app maps to a 400.  This test
extends that guarantee across every shape a request can take, because the guarantee is
only as strong as its weakest entry point and new endpoints arrive over time.
"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

READ_PATHS = (
    "/api/execution/intents",
    "/api/execution/orders",
    "/api/execution/fills",
    "/api/execution/positions",
    "/api/execution/cash",
    "/api/execution/breaks",
    "/api/execution/statements",
    "/api/execution/kill-switch",
    "/api/execution/workspace",
)


class StagePromotionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(_app())

    def test_every_read_endpoint_reports_paper(self) -> None:
        for path in READ_PATHS:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertIn(response.status_code, (200, 503))
                if response.status_code == 200:
                    self.assertEqual(
                        response.json()["context"]["deployment_stage"], "paper"
                    )

    def test_a_deployment_stage_query_parameter_is_refused(self) -> None:
        for path in READ_PATHS:
            with self.subTest(path=path):
                response = self.client.get(
                    path, params={"deployment_stage": "limited_live"}
                )
                self.assertEqual(response.status_code, 400)

    def test_a_data_mode_query_parameter_is_refused(self) -> None:
        ...

    def test_a_deployment_stage_header_is_ignored_rather_than_honoured(self) -> None:
        """Headers are the entry point most likely to be forgotten, because they do
        not appear in the OpenAPI schema."""
        response = self.client.get(
            "/api/execution/orders",
            headers={"X-Deployment-Stage": "limited_live",
                     "X-ASP-Stage": "limited_live"},
        )
        if response.status_code == 200:
            self.assertEqual(
                response.json()["context"]["deployment_stage"], "paper"
            )

    def test_a_command_body_cannot_carry_a_deployment_stage(self) -> None:
        """StrictInput forbids extra fields, so this returns 422 rather than silently
        ignoring the field — and 422 is better, because silent ignoring lets a client
        believe it set the stage."""
        response = self.client.post(
            "/api/execution/orders",
            json={**_valid_command(), "deployment_stage": "limited_live"},
        )
        self.assertEqual(response.status_code, 422)

    def test_no_route_path_contains_live(self) -> None:
        """A /api/live/... route added later would bypass every check above, so its
        absence is asserted rather than assumed."""
        paths = [route.path for route in _app().routes]
        for path in paths:
            with self.subTest(path=path):
                self.assertNotIn("/live", path)

    def test_the_openapi_schema_exposes_no_limited_live_enum_value_on_execution(
        self,
    ) -> None:
        """The generated TypeScript types are produced from this schema, so an enum
        value here becomes a value the frontend can construct."""
        ...

    def test_the_paper_context_helper_refuses_parameters_like_the_research_one(
        self,
    ) -> None:
        """Same shape as the existing fixed_read_context, deliberately."""
        from a_share_platform.api.app import RunContextOverrideDenied, paper_read_context

        with self.assertRaises(RunContextOverrideDenied):
            paper_read_context(data_mode="current_research", deployment_stage=None)
```

- [ ] **Step 6: 写 command API 幂等红测（HTTP 层，与 Task 1 的领域层互补）**

```python
# platform/tests/test_execution_command_idempotency_api.py
"""Idempotency at the HTTP boundary, which is where retries actually originate.

Task 1 tested the domain; this tests the wire.  They are not the same test: a domain
that is idempotent can still be exposed by an endpoint that generates its own key per
request, and then every retry creates an order while every unit test passes.
"""


class CommandIdempotencyTest(unittest.TestCase):
    def test_posting_the_same_command_twice_returns_the_same_order_id(self) -> None:
        payload = _valid_command(idempotency_key="client-key-0001")
        first = self.client.post("/api/execution/orders", json=payload)
        second = self.client.post("/api/execution/orders", json=payload)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)          # replay, not created
        self.assertEqual(
            first.json()["data"]["order_id"], second.json()["data"]["order_id"]
        )

    def test_a_replay_is_200_rather_than_409(self) -> None:
        """409 would send a retrying client into error handling for an order that
        exists."""
        ...

    def test_a_missing_idempotency_key_is_422_not_a_generated_key(self) -> None:
        """A server-generated key differs on each retry, which is the same as no key
        at all — and it fails silently, since the endpoint appears to work."""
        payload = _valid_command()
        del payload["idempotency_key"]
        response = self.client.post("/api/execution/orders", json=payload)
        self.assertEqual(response.status_code, 422)

    def test_the_same_key_with_a_different_body_is_409_with_problem_details(self) -> None:
        ...

    def test_a_denied_command_returns_problem_details_naming_the_reason(self) -> None:
        """Step 09 Spec requires problem details.  'Forbidden' with no reason makes a
        governance denial indistinguishable from a bug."""
        response = self.client.post("/api/execution/orders", json=_valid_command())
        self.assertEqual(response.status_code, 403)
        problem = response.json()
        self.assertIn("detail", problem)
        self.assertTrue(problem["detail"])

    def test_an_anonymous_subject_cannot_post_a_command(self) -> None:
        """The runtime's only principal is anonymous with read_public, so in practice
        every command is denied today — and the API must say so honestly rather than
        appear to work."""
        ...

    def test_the_kill_switch_command_requires_send_order_and_a_confirmation_token(
        self,
    ) -> None:
        """An irreversible operation needs more than a permission: a stray POST from a
        retry or a script must not engage or release it by accident."""
        ...

    def test_every_command_writes_an_audit_entry_whether_allowed_or_denied(self) -> None:
        ...
```

- [ ] **Step 7: 写投影红测（服务端聚合，七分区）**

七个分区复用 P-8 的 `DeskSection`/`WorkspaceState` 四态语义，**不新增第五态**：

```python
class ExecutionWorkspaceProjectionTest(unittest.TestCase):
    def test_the_projection_has_exactly_seven_sections_in_state_machine_order(self) -> None:
        """preview → orders → fills → positions → cash → breaks → kill_switch.
        The order follows SPEC-036's state machine rather than alphabet or importance,
        so the page reads in the direction the data actually flows."""
        ...

    def test_counts_are_computed_on_the_server(self) -> None:
        """If the browser counts open breaks then 'how many breaks are open' has two
        answers, and the page is the one people act on."""
        ...

    def test_the_summary_covers_the_whole_ledger_not_the_current_page(self) -> None:
        ...

    def test_an_empty_ledger_is_empty_rather_than_unavailable(self) -> None:
        """Empty means the capability works and holds no record; unavailable means the
        capability or its store is missing.  Collapsing them hides whether the operator
        is waiting on data or on implementation."""
        ...

    def test_a_missing_execution_store_is_unavailable_rather_than_empty(self) -> None:
        ...

    def test_the_projection_states_paper_in_every_section(self) -> None:
        ...

    def test_the_projection_declares_the_permitted_actions_per_section(self) -> None:
        """Three levels — read, guarded, irreversible — declared by the server.  A
        disabled button still exists in the DOM and the DOM can be edited; an action
        absent from the projection cannot be constructed."""
        ...

    def test_an_agent_principal_receives_no_guarded_or_irreversible_actions(self) -> None:
        ...

    def test_pnl_is_computed_on_the_server_or_reported_unavailable(self) -> None:
        """Never computed in the browser: two different P&L numbers on the same screen
        is worse than one missing number."""
        ...
```

- [ ] **Step 8: 转绿 → statement Artifact**

日终 statement 走已有 Artifact 合同（content-addressed + lineage）。
断言：statement 的 `content_hash` 覆盖 target/order/fill/position/cash 全部输入，
且**统一归因的 `execution` 分项引用它** —— 这是 P-8 的 `execution` 分项从
`not_applicable` 变成真实数值的接点。

- [ ] **Step 9: 同步 OpenAPI 与前端类型**

```bash
cd platform
.venv/bin/python scripts/export_openapi.py
cd frontend && PYTHON_BIN=../.venv/bin/python npm run generate:api
git diff --stat src/api/openapi.json
```

**检查生成的类型里没有 `limited_live`** 出现在任何执行相关的 schema 上。

- [ ] **Step 10: 全量验证并提交（本 Task 分三个提交）**

三个提交：ADR + migration、repository + read API、command API + 投影。
理由：migration 是不可逆的结构变更，与 API 混在一个提交里会让回滚变成二选一。

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add docs/adr/0014-paper-execution-schema-ownership.md \
  platform/migrations/00NN_p10_execution_schema.sql \
  platform/migrations/00NN+1_p10_execution_integrity.sql \
  platform/tests/test_p10_migrations.py
git commit -m "feat: add the paper execution schema with database-level append-only and idempotency

Paper execution data does not belong to any of the six existing responsibility schemas,
so ADR-0014 records the choice rather than letting a table land somewhere by default.
The research schema was the tempting option and the disqualifying one: AGENTS.md
forbids mixing current, strict, research and paper data in one unqualified projection,
and a paper ledger among research tables is exactly that mixture.  The ADR stays
Proposed until approved, because a seventh responsibility schema is a structural
decision.

Two constraints live in the database because they cannot be correct in the application.
Append-only guards at the application layer are bypassed by any second code path — a
worker, a replay, a manual repair during an incident — and an incident is precisely
when someone reaches for a manual repair; the trigger holds regardless of who connects.
Idempotency needs a unique index because check-then-write has a window in which a
second concurrent request also finds nothing and also writes, and network retries make
concurrent duplicates ordinary rather than rare.

The deployment_stage column admits paper only, as a CHECK constraint, so that no path
at all — including a hand-written UPDATE during an incident — can put limited_live into
an execution ledger.  A break row's expected and observed values cannot be updated,
which is SPEC-038's prohibition on covering an imbalance by editing numbers, expressed
as a trigger rather than as a convention."
```

---

### Task 6: PUI-09 —— 七个执行面板，全局 `paper`，危险操作分级

对应 Step 09 Task 6 逐字：「实现 Paper preview、orders/fills/positions/cash/breaks/
kill switch 状态；危险操作需明确权限和确认；Agent 视图无操作。Paper Execution、
Rebalance、Incidents 和 kill switch 产品面按 PUI-09 执行；全局必须保持 `paper`，
不得出现 Live 切换、真实账户入口或由前端推断的执行状态。」

**七个面板全部 `design_status = missing`。** 17 个 Figma frame 里没有任何一个是执行页
（逐一核对见「原型参照」一节）。因此本 Task 的信息架构来自：
`docs/18` §3.5 的 Execution 行（`Paper Intent、状态机、Fill、Fee 和 reconciliation`，
Gate 是「真实账户未连接且不可配置」）、`routes.tsx` 已登记的 tab、
以及 `3:1569` 的 `bottom-action-bar` 结构。**七条设计假设逐条记录，不声称 parity。**

**Files:**
- Create: `platform/frontend/src/pages/ExecutionWorkspace.tsx`
- Create: `platform/frontend/src/features/execution/ExecutionPreview.tsx`
- Create: `platform/frontend/src/features/execution/OrdersPanel.tsx`
- Create: `platform/frontend/src/features/execution/FillsPanel.tsx`
- Create: `platform/frontend/src/features/execution/PositionsPanel.tsx`
- Create: `platform/frontend/src/features/execution/CashPanel.tsx`
- Create: `platform/frontend/src/features/execution/BreaksPanel.tsx`
- Create: `platform/frontend/src/features/execution/KillSwitchPanel.tsx`
- Create: `platform/frontend/src/features/execution/DangerousAction.tsx`
- Create: `platform/frontend/src/features/execution/executionTypes.ts`
- Modify: `platform/frontend/src/app/AppShell.tsx`（阶段标签来自服务端）
- Modify: `platform/frontend/src/pages/WorkspacePage.tsx`（移除 `execution` blocker）
- Create: `platform/scripts/verify_execution_browser.py`
- Test: `platform/frontend/src/features/execution/*.test.tsx`（七个面板）
- Test: `platform/frontend/src/features/execution/DangerousAction.test.tsx`
- Test: `platform/frontend/src/app/AppShell.test.tsx`（扩展：阶段标签）

**Interfaces:**
- Consumes: Task 5 的九个只读 endpoint 与投影；已有 `WorkspaceState` 六态、
  `PageHeading`、`NumericCell`、`EvidenceDrawer`
- Produces: 七个面板 + 一个 `DangerousAction` 包装组件

- [ ] **Step 1: 记录七条设计假设（在写任何组件之前）**

把「原型参照」一节的七条假设写进 `docs/29-p9-paper-execution-evidence.md` 的
设计假设小节，每条含：假设内容、依据（哪个 frame 的哪个结构，或"无依据，工程判断"）、
以及若将来有了 Frame 需要重新对照的部分。

**不得跳过这一步。** 没有 Frame 时，未记录的设计假设会在下一次审计里
被误当成"曾经对照过设计"。

- [ ] **Step 2: 写第一个前端红测 —— 全局 `paper` 且来自服务端**

```tsx
// platform/frontend/src/app/AppShell.test.tsx（扩展）
/**
 * The stage tag comes from the server envelope, not from a frontend constant.
 *
 * AppShell currently hard-codes `<Tag color="blue">research</Tag>`.  If the execution
 * pages hard-code `paper` in the same way, then "which stage am I in" has two sources
 * of truth and one of them can be changed to limited_live by a single frontend edit —
 * which is exactly what ADR-0010 decision 4 forbids.
 */

it('shows the stage reported by the server rather than a literal', async () => {
  renderWithApi({ context: { deployment_stage: 'paper', data_mode: 'current_research' } })
  expect(await screen.findByText('paper')).toBeInTheDocument()
})

it('never renders limited_live even if the server sends it', async () => {
  /**
   * Defence in depth.  The API cannot produce limited_live (Task 5 asserts that), and
   * this asserts the frontend would not display it either — because the value the user
   * sees is the value the user trusts, and a Live label on a paper desk is worse than
   * no label at all.
   */
  renderWithApi({ context: { deployment_stage: 'limited_live', data_mode: 'current_research' } })
  expect(await screen.findByRole('alert')).toBeInTheDocument()
  expect(screen.queryByText('limited_live')).not.toBeInTheDocument()
})

it('has no stage switcher control anywhere in the shell', () => {
  render(<AppShell />)
  expect(screen.queryByRole('combobox', { name: /stage|阶段|环境/ })).toBeNull()
  expect(screen.queryByRole('switch', { name: /live|实盘/ })).toBeNull()
})

it('has no real account entry point', () => {
  /** docs/18 §3.5 Execution gate: 真实账户未连接且不可配置. */
  render(<AppShell />)
  for (const label of [/账户/, /券商/, /broker/i, /connect/i]) {
    expect(screen.queryByRole('button', { name: label })).toBeNull()
  }
})
```

- [ ] **Step 3: 运行确认红测 → 实现 → 转绿**

```bash
cd platform && npm --prefix frontend test -- --run src/app/AppShell.test.tsx
```

- [ ] **Step 4: 写 `DangerousAction` 红测（三级操作等级）**

```tsx
// platform/frontend/src/features/execution/DangerousAction.test.tsx
/**
 * Three action levels, declared by the server and enforced by one component.
 *
 * Step 09 Task 6: 危险操作需明确权限和确认；Agent 视图无操作.
 *
 * A "cancel all orders" control that looks like a "refresh" control will be clicked by
 * mistake; it is only a question of when.  In paper that is a drill, in Live it is
 * money.  So the level is not a styling choice made per call site — it comes from the
 * projection, and one component renders all three.
 *
 * The Agent case is absence rather than disablement: a disabled button is still in the
 * DOM, and the DOM can be edited.  An action missing from the projection cannot be
 * constructed by the client at all.
 */

it('renders a read action without any confirmation', () => { ... })

it('requires one confirmation for a guarded action', async () => { ... })

it('requires a typed object id for an irreversible action', async () => {
  /**
   * Engaging or releasing a kill switch and cancelling every order are irreversible.
   * Typing the id is the cheapest available guard that a stray click cannot pass.
   */
  render(<DangerousAction level="irreversible" objectId="kill:0001" onConfirm={onConfirm} />)
  await userEvent.click(screen.getByRole('button', { name: /确认/ }))
  expect(onConfirm).not.toHaveBeenCalled()
  await userEvent.type(screen.getByRole('textbox'), 'kill:0001')
  await userEvent.click(screen.getByRole('button', { name: /确认/ }))
  expect(onConfirm).toHaveBeenCalledTimes(1)
})

it('does not render an action absent from the projection', () => {
  /** The Agent view, expressed as the general rule it is a case of. */
  render(<OrdersPanel projection={{ ...projection, permitted_actions: [] }} />)
  expect(screen.queryByRole('button', { name: /撤单|cancel/i })).toBeNull()
})

it('shows a denial reason rather than a silently inert button', async () => {
  /**
   * A control that does nothing when clicked reads as a bug.  A control that explains
   * why it is unavailable reads as governance — and governance is what it is.
   */
  ...
})

it('does not infer the permitted level from the principal in the browser', () => {
  /**
   * The frontend must not derive authority.  If it computed "this user is a trader so
   * show the cancel button", then the permission check would exist in two places and
   * the browser copy would be the editable one.
   */
  const source = DangerousAction.toString()
  expect(source).not.toMatch(/role|permission|trader/i)
})
```

- [ ] **Step 5: 逐面板红测 → 实现（七个面板，每个独立一轮）**

每个面板至少覆盖：六态、服务端数值原样显示、无前端聚合、Figma fixture 零泄漏。
各面板的专属断言：

```tsx
// ExecutionPreview.test.tsx
it('shows the approved target and the derived intents, not editable numbers', () => {})
it('states that an intent is not an order', () => {
  /** docs/18 §3.5 Portfolios gate: 无真实账户连接；Intent 不是 Order.  The
   *  distinction is the whole safety model, so it is on the page in words. */
})
it('shows the pre-trade risk status including unavailable', () => {})
it('disables submission when the approval is missing or expired, with the reason', () => {})

// OrdersPanel.test.tsx
it('shows all nine states with distinct non-colour indicators', () => {
  /** SPEC-057: non-colour status.  Nine states cannot be distinguished by hue alone. */
})
it('shows block reasons for a rejected order rather than an empty cell', () => {})
it('does not offer cancel on a terminal order', () => {
  /** The UI mirrors the state table rather than relying on the server to refuse. */
})
it('shows the idempotency key of each command', () => {
  /** Operationally essential during an incident: it is how an operator tells a retry
   *  from a second order. */
})

// FillsPanel.test.tsx
it('decomposes fees into commission, stamp duty and transfer fee', () => {
  /** A single "fee" column cannot be reconciled against a broker statement. */
})
it('shows the cost model version alongside the fees', () => {})
it('shows unadjusted prices and labels them as such', () => {})

// PositionsPanel.test.tsx
it('separates settled from unsettled quantity', () => {
  /** A single quantity column hides the T+1 constraint, and the operator then plans a
   *  sale that will be refused. */
})
it('shows the sellable date per lot', () => {})
it('shows corporate-action-created lots with their action id', () => {})

// CashPanel.test.tsx
it('shows available, frozen and settled as three separate figures', () => {
  /** Collapsing them into "cash" makes an overdraw impossible to see coming. */
})
it('lists ledger entries with their reason', () => {})
it('does not compute a balance in the browser', () => {})

// BreaksPanel.test.tsx
it('shows expected, observed and the difference, all three', () => {
  /** The difference alone is not actionable; the two sides name what disagreed. */
})
it('offers acknowledge and explain but never correct', () => {
  /** SPEC-038.  There is no control that changes a number, because there is no such
   *  operation in the domain. */
  expect(screen.queryByRole('button', { name: /修正|correct|调整/ })).toBeNull()
})
it('shows the incident id for a material break', () => {})
it('shows the detection count so deduplication does not hide scale', () => {})

// KillSwitchPanel.test.tsx
it('shows the current state, scope, actor, reason and time', () => {})
it('requires an irreversible confirmation to engage', () => {})
it('requires an irreversible confirmation to release', () => {
  /** Releasing is as dangerous as engaging: it resumes trading. */
})
it('states that this switch governs paper only', () => {})
```

- [ ] **Step 6: 移除 `execution` blocker（本 plan 唯一的 blocker 移除）**

```bash
cd platform
grep -n "activationReasons" -A 10 frontend/src/pages/WorkspacePage.tsx
```

删除第 23 行 `execution: '执行监控将在 Paper OMS 启用后开放；当前没有连接账户或券商。'`，
**保留** `users` / `entitlements`（无 IdP）与其余各条。

**这一步必须在 Task 5 的真实 API 可用之后。** 提前移除会让页面显示
"能力已就绪"而实际上没有数据 —— 那正是 runtime fixture 想让人看到的效果。

- [ ] **Step 7: 四视口真实浏览器验收**

```bash
cd platform && .venv/bin/python scripts/verify_execution_browser.py
```

`verify_execution_browser.py` 照抄 `scripts/verify_desk_browser.py` 的形状
（`VIEWPORTS = (("1440",1440,900),("1024",1024,768),("768",768,1024),("320",320,640))`，
`document.documentElement.scrollWidth > clientWidth` 判定溢出）。

**28 个检查点（7 面板 × 4 视口）**，每个视口检查：

```text
1. document.scrollWidth === document.clientWidth（无页面级水平溢出）
2. 全局 paper 标签可见，且不存在 limited_live 文本
3. 不存在 stage 切换器、Live 开关或账户/券商入口
4. 七个面板标题均可见（1440）或可通过 tab 到达（320/768）
5. 危险操作控件带确认，且 Agent 投影下不渲染
6. 控制台无 error/warning
7. 正常重载无 4xx/5xx
8. Figma fixture 零泄漏（版本 v1.2 / 最后更新: 2024-12-06 09:35 /
   Submit for Review (提交量化中心初审) / 贵州茅台 / 600519.SH）
```

**当前真实运行时预期结果**：数据库无真实 target/order/fill 时，
七个面板全部显示 `empty` 或 `unavailable`，**这是正确的验收结果**。
**不得注入 fixture 让页面看起来 ready。**

- [ ] **Step 8: 全量验证并提交（本 Task 分三个提交）**

三个提交：shell 与 DangerousAction、四个只读面板、breaks 与 kill switch。

```bash
cd platform
npm --prefix frontend test -- --run
npm --prefix frontend run lint
npm --prefix frontend run build
.venv/bin/python scripts/verify_execution_browser.py
git diff --check
cd .. && git add platform/frontend/src/features/execution/ \
  platform/frontend/src/pages/ExecutionWorkspace.tsx \
  platform/frontend/src/pages/WorkspacePage.tsx \
  platform/frontend/src/app/AppShell.tsx \
  platform/scripts/verify_execution_browser.py
git commit -m "feat: deliver the seven paper execution panels with server-declared action levels

None of the seventeen Figma frames is an execution page, so every panel here carries
design_status missing and the information architecture comes from docs/18 §3.5, the tab
already registered in routes.tsx, and the 56px bottom action bar in node 3:1569.  Seven
design assumptions are recorded individually in the evidence, because an unrecorded
assumption is read by the next audit as a design that was once compared.

The stage tag comes from the server envelope rather than a frontend literal.  AppShell
hard-codes research today, and hard-coding paper the same way would give 'which stage am
I in' two sources of truth with the editable one in the browser — which is the situation
ADR-0010 decision 4 exists to prevent.  The shell also contains no stage switcher, no
Live toggle and no account or broker entry point, and their absence is asserted rather
than assumed.

Dangerous operations go through one component with three server-declared levels.  A
'cancel all orders' control that looks like a 'refresh' control will be clicked by
mistake eventually; in paper that is a drill and in Live it is money.  Irreversible
actions — engaging or releasing the kill switch, cancelling everything — require the
object id to be typed, which is the cheapest guard a stray click cannot pass.  Releasing
the switch is treated as irreversible too, since it resumes trading.

The Agent view is an absence rather than a disablement.  A disabled button is still in
the DOM and the DOM can be edited, so actions the principal may not perform are missing
from the projection entirely and the client has nothing to construct.  For the same
reason the component derives no authority from the principal: a permission check in the
browser would be a second copy of the rule, and the editable one.

Each panel keeps the distinctions that make the numbers usable.  Positions separate
settled from unsettled, because a single quantity column hides T+1 and the operator then
plans a sale that will be refused.  Cash shows available, frozen and settled separately,
because collapsing them makes an overdraw impossible to see coming.  Fills decompose
commission, stamp duty and transfer fee, because a single fee column cannot be reconciled
against a statement.  Breaks show expected, observed and the difference — the difference
alone does not say what disagreed — and offer acknowledge and explain but no correct
control at all, since SPEC-038 forbids the operation and the domain therefore does not
have it.

The execution activation blocker is removed only now that a real API exists behind it.
Removing it earlier would have shown a page that claims a capability with no data behind
it, which is precisely the effect a runtime fixture produces.  With no real targets or
orders in the database all seven panels report empty or unavailable, and that is the
accepted result rather than a gap to paper over."
```

---

### Task 7: replay、恢复、日界、backup-restore 与真实日历 soak

对应 Step 09 Task 7 逐字：「建立 duplicate/out-of-order/provider outage/delayed fill/
restart/day-boundary/backup restore 测试；**真实日历 soak 证据不能用快速单测替代**。」

Step 09 验收逐字：「故障注入和 restore/replay 一致」「连续 soak 和日终 Artifact 完成」。

**冻结 Plan 明确要求两者都要，不是二选一。** 这不是冗余，两者证明的是不同的事：

| | 快速单测（七类事件） | 真实日历 soak |
|---|---|---|
| 证明 | 每一类异常事件被正确处理 | 系统在真实时间流里连续正确 |
| 覆盖 | 已枚举的七类 | 未枚举的组合、时序与积累效应 |
| 不能证明 | 组合与积累 | 具体某一类事件的处理逻辑 |
| 时长 | 秒级 | 多个真实交易日 |

单测无法覆盖的具体东西：**跨日累积**（第 5 天的 T+1 库存依赖第 4 天的结算）、
**真实交易日历的不规则性**（长假、调休）、**重启与时钟推进的交互**、
**账本随时间增长后的对账性能与正确性**。这些只有让时间真的流过才会出现。

**Files:**
- Create: `platform/src/a_share_platform/workers/paper_session.py`
- Create: `platform/src/a_share_platform/workers/paper_reconciliation.py`
- Create: `platform/src/a_share_platform/workers/paper_replay.py`
- Test: `platform/tests/test_paper_event_replay.py`
- Test: `platform/tests/test_paper_recovery_and_day_boundary.py`
- Test: `platform/tests/test_paper_workers_dry_run.py`
- Create: `docs/29-p9-paper-execution-evidence.md`

**Interfaces:**
- Consumes: Task 1–5 全部
- Produces: 三个 dry-run 默认 worker + 一份 soak Evidence

- [ ] **Step 1: 写七类事件 replay 红测**

```python
# platform/tests/test_paper_event_replay.py
"""Replaying broker events must converge on the same ledger, whatever the order.

Event delivery is not a solved problem even against a deterministic broker: the OMS
polls, the poll can return the same event twice, a delayed event can arrive after a
later one, and a process can die between reading an event and writing its effect.  The
ledger must be a function of the set of events, not of the sequence in which they were
processed.

The reason this matters more than it sounds: the effect of double-counting a fill is a
position that is too large, and the effect of that is a sell order for shares that do
not exist — which the broker rejects, which produces a break, which stops the desk.
One duplicated event ends the trading day.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime

from a_share_platform.application.paper_ledgers import apply_broker_events


class DuplicateEventTest(unittest.TestCase):
    def test_the_same_fill_event_applied_twice_changes_nothing(self) -> None:
        """Idempotency at the event level, distinct from command idempotency."""
        once = apply_broker_events(ledger=_empty(), events=(_fill_event(),))
        twice = apply_broker_events(ledger=once, events=(_fill_event(),))
        self.assertEqual(_hashes(once), _hashes(twice))

    def test_a_duplicate_is_recognised_by_event_id_not_by_content(self) -> None:
        """Two genuinely separate partial fills of the same size at the same price are
        not duplicates, and content-based deduplication would silently drop one."""
        first = _fill_event(event_id="event:0001", sequence=1, shares=2_000)
        second = _fill_event(event_id="event:0002", sequence=2, shares=2_000)
        ledger = apply_broker_events(ledger=_empty(), events=(first, second))
        self.assertEqual(_total_shares(ledger), 4_000)

    def test_a_duplicate_is_recorded_as_observed_rather_than_ignored(self) -> None:
        """Silently dropping it hides that the broker or the poller is misbehaving."""
        ...


class OutOfOrderTest(unittest.TestCase):
    def test_events_applied_in_reverse_order_reach_the_same_ledger(self) -> None:
        forward = apply_broker_events(
            ledger=_empty(), events=(_ack(), _partial(), _fill())
        )
        backward = apply_broker_events(
            ledger=_empty(), events=(_fill(), _partial(), _ack())
        )
        self.assertEqual(_hashes(forward), _hashes(backward))

    def test_a_fill_arriving_before_its_ack_is_buffered_not_refused(self) -> None:
        """The OMS state machine forbids ACKNOWLEDGED after FILLED, but that is a rule
        about our state, not about delivery order.  Refusing the fill would lose a
        trade that really happened."""
        ...

    def test_an_out_of_order_arrival_is_recorded_for_review(self) -> None:
        ...

    def test_a_gap_in_the_sequence_is_detected_rather_than_assumed_empty(self) -> None:
        """Sequences 1, 2, 4 means event 3 exists and we do not have it.  Proceeding as
        if 3 were empty is how a fill goes missing quietly."""
        ...


class ProviderOutageTest(unittest.TestCase):
    def test_an_outage_mid_session_leaves_the_ledger_consistent(self) -> None:
        ...

    def test_events_missed_during_an_outage_are_recovered_by_poll(self) -> None:
        ...

    def test_an_outage_of_unknown_outcome_does_not_resubmit_blindly(self) -> None:
        """The disconnect-before-ack case: we do not know whether the order arrived.
        Resubmitting on the same idempotency key is safe; resubmitting on a new one is
        a duplicate order."""
        ...


class DelayedFillTest(unittest.TestCase):
    def test_a_fill_arriving_after_the_session_closed_is_attributed_to_its_own_session(
        self,
    ) -> None:
        """Attributing it to the session in which it was received would move a trade
        between days, and both days' reconciliations would then break."""
        ...

    def test_a_fill_arriving_after_expiry_is_a_break_not_a_silent_position(self) -> None:
        """We already declared the order expired.  Accepting the fill silently makes
        our record disagree with the broker's; raising a break makes the disagreement
        visible, which is the whole point."""
        ...
```

- [ ] **Step 2: 运行确认红测 → 实现 → 转绿**

- [ ] **Step 3: 写重启、日界与 backup-restore 红测**

```python
# platform/tests/test_paper_recovery_and_day_boundary.py
"""Restart, day boundary and restore must not change the final ledger.

Step 09 Spec: restart、day boundary、backup/restore 不改变最终账本.

Each of the three fails differently.  A restart mid-session can lose in-flight state
if any state lives only in memory.  A day boundary advances T+1 settlement, and an
implementation that advances it on wall-clock midnight rather than on a calendar
session will settle shares on a Sunday.  A restore replays from a checkpoint, and
anything that is not idempotent double-applies.
"""


class RestartTest(unittest.TestCase):
    def test_a_restart_mid_session_recovers_every_open_order(self) -> None:
        ...

    def test_a_restart_between_reading_an_event_and_writing_its_effect_does_not_lose_it(
        self,
    ) -> None:
        """The narrowest and most likely window.  It is why events are polled from a
        durable cursor rather than consumed destructively."""
        ...

    def test_no_execution_state_lives_only_in_memory(self) -> None:
        """Asserted structurally: the service holds repositories, not dictionaries of
        orders.  In-memory state is state a restart destroys."""
        ...

    def test_a_restart_does_not_resubmit_an_order_that_was_already_sent(self) -> None:
        ...


class DayBoundaryTest(unittest.TestCase):
    def test_settlement_advances_on_a_calendar_session_not_on_midnight(self) -> None:
        """Advancing on wall-clock midnight settles Friday's purchase on Saturday, and
        the position then appears sellable on a day the exchange is closed."""
        ...

    def test_an_unfilled_day_order_expires_at_the_session_close(self) -> None:
        ...

    def test_a_day_boundary_releases_the_freeze_on_expired_orders(self) -> None:
        ...

    def test_crossing_two_boundaries_settles_two_days_of_lots_correctly(self) -> None:
        """Accumulation, which is the thing single-session tests cannot see."""
        ...

    def test_a_long_holiday_delays_settlement_to_the_next_open_session(self) -> None:
        """The concrete case the calendar exists for: a purchase before a week-long
        holiday is not sellable during it."""
        ...


class BackupRestoreTest(unittest.TestCase):
    def test_restoring_a_backup_and_replaying_reaches_the_identical_ledger(self) -> None:
        """Compared by hash across every order, fill, lot and cash entry."""
        original = _run_full_session()
        restored = _replay_from_backup(_backup_after_n_events(3))
        self.assertEqual(_hashes(original), _hashes(restored))

    def test_replay_after_restore_does_not_double_apply_committed_effects(self) -> None:
        ...

    def test_a_restore_to_a_point_before_a_break_re_detects_the_same_break(self) -> None:
        """The break id is stable, so a restore does not manufacture a second break for
        the same disagreement."""
        ...

    def test_a_restore_never_resurrects_a_deleted_failure_record(self) -> None:
        """There are none to resurrect: failure records cannot be deleted.  The test
        states it because a restore is the one moment someone might try."""
        ...
```

- [ ] **Step 4: 写三个 worker 的 dry-run 红测**

```python
# platform/tests/test_paper_workers_dry_run.py
"""Three workers, dry-run by default, with an extra stage blocker.

A worker that writes by default is a worker that writes by accident, and these workers
write to an order ledger.  So they copy the timing_baseline shape exactly — plan as
JSON with exit 0, --execute without the ack exits 2 with the reason — and add one
blocker the research workers do not need: a deployment stage that is not paper is
refused outright.
"""


class DryRunDefaultTest(unittest.TestCase):
    def test_paper_session_without_execute_writes_nothing(self) -> None:
        from a_share_platform.workers import paper_session

        code = paper_session.main([
            "--session", "2026-08-17", "--policy-id", "policy.core",
            "--database-url", "postgresql://user:pw@127.0.0.1:55432/db",
            "--code-version", "test",
        ])
        self.assertEqual(code, 0)

    def test_execute_without_the_ack_exits_two_with_the_reason(self) -> None:
        ...

    def test_a_non_loopback_database_endpoint_is_blocked(self) -> None:
        """Reused from the existing _postgres_endpoint_is_private_local guard."""
        ...

    def test_a_deployment_stage_other_than_paper_is_blocked(self) -> None:
        """The blocker the research workers do not have.  A paper session worker
        pointed at a limited_live stage is the single most dangerous invocation in this
        repository, so it fails before it reads anything."""
        ...

    def test_the_dry_run_plan_states_the_stage_and_the_kill_switch_state(self) -> None:
        """An operator reading the plan needs to know both before deciding to execute."""
        ...

    def test_the_replay_worker_cannot_write_a_new_order(self) -> None:
        """Replay reconstructs from existing events.  A replay tool that can create an
        order can create one that was never approved."""
        ...

    def test_the_reconciliation_worker_cannot_write_a_position_or_cash_entry(self) -> None:
        """Same structural guard as Task 4, asserted again at the CLI boundary."""
        ...
```

- [ ] **Step 5: 真实日历 soak（不可用单测替代）**

**这是本 Task 唯一需要真实时间的步骤，也是 Step 09 明确要求的那一项。**

soak 时长在 Step 09 Spec 里是 D2 决策（「soak 时长、告警和值班频率为 D2，
但 Gate 前冻结」）。**本 plan 建议 10 个连续交易日**并要求用户批准：

```text
理由：10 个交易日覆盖至少两个周末边界（两次 T+1 跨周末结算）、
一次月内换手周期，且足以让账本增长到能暴露对账性能问题。
少于 5 个交易日无法覆盖两次周末；多于 20 个交易日会把 P10 Gate
无谓地推迟数周而不增加新的失败模式。
D2 决策，需用户批准后才是冻结值。
```

每个交易日执行：

```bash
cd platform && source /tmp/asp_env.sh
# 1. 日内：从已批准 target 生成 intent 并走完整链路
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.paper_session \
  --session $(date +%F) --policy-id policy.core \
  --database-url "$ASP_DATABASE_URL" --code-version "$(git rev-parse --short HEAD)" \
  --private-local-research-ack --execute

# 2. 日终：对账并产出 statement Artifact
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.paper_reconciliation \
  --session $(date +%F) --database-url "$ASP_DATABASE_URL" \
  --code-version "$(git rev-parse --short HEAD)" \
  --private-local-research-ack --execute
```

**每日必须记录到 Evidence（不得只记最终结论）**：

```text
session / 是否交易日 / intents 数 / orders 数 / 各状态计数 /
fills 数与总股数 / 费用三项合计 / 现金 available/frozen/settled /
lots 数与 settled/unsettled 拆分 / 公司行动数 /
breaks 数与各 severity 计数 / 日终是否闭合 / statement artifact id /
遇到的异常与处理 / 重启次数
```

**若 soak 期间出现 break，如实记录并查清原因，不得为了让 soak"通过"而调整容差、
跳过某一天或重置账本。** 一次真实 break 是本 Task 最有价值的产出。

**当前真实预期**：数据库若无已批准 `TargetPortfolioSnapshot`，
soak 的每一天都会诚实地在「无可下单 target」处停下，产出 0 intent / 0 order。
**这是允许且正确的结果**，但 Evidence 必须写明 soak 验证的是
「链路在真实日历上连续运行不出错」而**不是**「Paper 交易已被验证」。

- [ ] **Step 6: 至少一次真实重启与一次真实 restore 演练**

soak 期间**必须**做一次进程重启（在有 open order 时）与一次
备份恢复演练，并记录：重启前后账本 hash 对比、恢复后 replay 的一致性、
以及 RPO/RTO 实测值（SPEC-055 要求「定义 RPO/RTO」）。

**演练不能只在测试里做。** 单测里的"重启"是构造一个新对象；
真实重启涉及连接池、未提交事务、文件句柄与操作系统缓冲。

- [ ] **Step 7: 写 Evidence（十节）**

```text
# docs/29-p9-paper-execution-evidence.md
## 1. ADR-0010 六条决策的落地与对应断言（逐条）
## 2. 红绿测记录（每个 Task 的真实失败文本与转绿结果）
## 3. 81 个状态转移的实测表（合法 17 / 被拒 64，逐个）
## 4. 幂等实测（OMS 层 / broker 层 / HTTP 层 / 数据库唯一索引，四层各自结果）
## 5. 七类 replay 事件的实测结果（注入 → 处理 → 最终账本 hash）
## 6. 真实日历 soak 逐日记录（每个交易日一行，含 0 intent 的日子）
## 7. 重启与 backup-restore 演练结果（含 RPO/RTO 实测）
## 8. 权限矩阵实测（8 角色 × 4 个执行命令的允许/拒绝表，共 32 格）
## 9. 七个页面三轴状态与七条设计假设
## 10. 明确否认
```

第 3 节的 81 格与第 8 节的 32 格是本 Evidence 最重要的两张表：
它们是状态机完整性与治理边界的可审计快照。

第 6 节**必须包含 0 intent 的日子**。只记录"有交易的日子"会让 soak 看起来
比实际覆盖的更充分。

- [ ] **Step 8: 写明确否认声明（必须逐字包含）**

> 本 plan 交付 **OMS 状态机、命令幂等、pre-trade risk、职责分离审批、
> 确定性内部 Paper Broker、T+1 持仓与现金账本、对账与 break 队列、kill switch、
> replay/恢复演练与 PUI-09 七个执行页面的工程实现**。它**不代表**：
>
> - **P10 Gate 通过** —— Gate 要求「连续 soak 和日终 Artifact 完成」，
>   而真实 soak 需要真实已批准 `TargetPortfolioSnapshot`；无真实 target 时
>   soak 只证明「链路在真实日历上连续运行不出错」，**不证明 Paper 交易已被验证**；
> - **平台获准实盘（Limited Live / P11）** —— ADR-0010 决策 6 逐字：
>   「P11 只有在新的明确授权和 Broker/Security ADR 后才能开始」。
>   本 plan **不授权**任何真实账户读取、下单、撤单或改单；
> - **Paper 测试结果可推出 Live 安全** —— ADR-0010 结果段逐字：
>   「Paper 测试结果不构成真实交易授权或模型有效证据」。
>   确定性内部 Broker **刻意**不含真实券商的网络、时钟、限流、部分成交微结构、
>   报盘拒绝码、席位规则与结算差异。**在确定性 Broker 上全绿，
>   对真实券商行为不构成任何证据**；
> - P2、P4、P5、P6、P7、P8 或 P9 任何 Gate 通过 —— 本 plan 不改变其中任何一条；
> - 任何因子、模型或策略科学有效 —— 一个完全无效的策略也可以被完美执行。
>   Paper 的盈亏数字**不是**策略证据，理由：输入是 `normalized_current`、
>   无 PIT 验证、无样本外、无多重检验校正、样本期为 soak 天数；
> - 有真实身份系统 —— 无 identity provider，运行时唯一 principal 是
>   `Principal.anonymous()`（仅 `read_public`）。因此**职责分离在生产中
>   尚未被两个真实用户验证**：它有测试，但没有两个人；
> - 对账已被真实对手方验证 —— statement 由内部 Paper Broker 产生，
>   **不是**券商对账单。真正的对账差异只有接入真实只读账户后才会出现，
>   而那属 P11 的 `broker_read_only` 级；
> - soak 通过等于生产可靠 —— soak 覆盖的是 soak 期间真实发生的事件。
>   未在 soak 期间出现的故障（涨跌停封板、临时停牌、券商报盘拒绝、
>   长假前后的结算特例）仍可能完全未被验证。
>
> **P10 完成不授权实盘。** P11 需要用户针对券商、账户、市场、标的、
> 单笔/单日金额、有效期和允许动作的**新的明确授权**，以及一份新的
> Broker/Security ADR。本 plan 没有安装任何真实交易 SDK、
> 没有保存任何账户凭证、没有开放任何真实 order endpoint，
> 且以上三点各有一个会失败的测试守着。

- [ ] **Step 9: 更新冻结 Plan、Track 与 Gap Audit 的真实状态**

`docs/plans/step-09-p10-paper-oms.md`：状态从 `dependency_blocked` 改为
**按实际** `in_progress` 或 `capability_complete_gate_blocked`。
**不得改为 Gate 通过** —— Spec 验收要求「连续 soak 和日终 Artifact 完成」，
而真实 soak 需要真实 target。

`docs/plans/track-00-prototype-runtime-delivery.md`：PUI-09 状态与三轴结论表。

`docs/22-prototype-runtime-gap-audit.md`：**追加**「2026-08-16 PUI-09 完成后的增量更新」，
更新第 16、21、22、23、28、29、31 行的原型轨道结论；
原 §5 矩阵的审计时点事实**保留不改**。

**明确不得改动**：`docs/plans/step-10-p11-limited-live-readiness.md` 的 `AUTH` 状态。
它只能由用户的新授权改变。

- [ ] **Step 10: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
npm --prefix frontend test -- --run
npm --prefix frontend run lint
npm --prefix frontend run build
.venv/bin/python scripts/verify_execution_browser.py
git diff --check
cd .. && git add platform/src/a_share_platform/workers/paper_session.py \
  platform/src/a_share_platform/workers/paper_reconciliation.py \
  platform/src/a_share_platform/workers/paper_replay.py \
  platform/tests/test_paper_event_replay.py \
  platform/tests/test_paper_recovery_and_day_boundary.py \
  platform/tests/test_paper_workers_dry_run.py \
  docs/29-p9-paper-execution-evidence.md \
  docs/plans/step-09-p10-paper-oms.md \
  docs/plans/track-00-prototype-runtime-delivery.md \
  docs/22-prototype-runtime-gap-audit.md
git commit -m "test: replay seven event faults, drill recovery and soak on the real calendar

The frozen plan asks for both fast fault tests and a real-calendar soak, and they prove
different things rather than duplicating each other.  The unit tests prove each
enumerated anomaly is handled; the soak proves the system stays correct while real time
passes, which is where the unenumerated combinations live — accumulation across days
where day five's T+1 inventory depends on day four's settlement, the irregularity of a
real holiday calendar, the interaction between a restart and a clock that has moved, and
reconciliation on a ledger that has grown.

Replay convergence is the property that matters most.  A ledger must be a function of
the set of events, not the order they were processed in, because polling can return the
same event twice and a delayed event can arrive after a later one.  The stakes are
concrete: double-counting a fill leaves a position that is too large, which produces a
sell order for shares that do not exist, which the broker rejects, which raises a break,
which stops the desk.  One duplicated event ends a trading day.

Deduplication is by event id rather than by content, because two genuine partial fills
of the same size at the same price are not duplicates and content matching would drop
one.  A gap in the sequence is detected rather than treated as empty: 1, 2, 4 means
event 3 exists and we do not have it, and proceeding is how a fill disappears quietly.
A fill arriving after we declared the order expired raises a break instead of quietly
becoming a position, because our record and the broker's now disagree and the whole
purpose of a break is to make that visible.

Settlement advances on a calendar session rather than on wall-clock midnight, or a
Friday purchase settles on Saturday and appears sellable while the exchange is closed.
A purchase before a week-long holiday is not sellable during it, which is the case the
calendar exists for and the case arithmetic gets wrong.

The three workers copy the timing_baseline dry-run shape and add one blocker the
research workers do not need: a deployment stage other than paper is refused before
anything is read.  A paper session worker pointed at limited_live would be the single
most dangerous invocation in this repository.  The replay worker cannot create an order
— a replay tool that can create an order can create one nobody approved — and the
reconciliation worker cannot write a position or a cash entry, which is Task 4's
structural guard asserted again at the CLI boundary.

The soak records every session including the ones with zero intents, because reporting
only the days that traded would make the coverage look broader than it was.  A break
encountered during the soak is recorded and investigated rather than tolerance-adjusted
away; a real break is the most valuable output this task can produce.

The denial section states plainly that P10 completion does not authorise live trading
and that paper results cannot be used to infer live safety.  The deterministic broker
deliberately omits a real broker's network, clock, rate limits, partial-fill
microstructure, rejection codes, seat rules and settlement differences, so being green
against it is evidence about this platform and no evidence at all about a real
counterparty.  ADR-0010 decision 6 requires a new explicit authorisation and a new
broker/security ADR before P11 begins, and the three guards behind that — no trading
SDK, no stored credential, no real order endpoint — each have a test that fails if
someone removes them."
```

---

## 完成定义

1. `OrderState` 恰好九值；81 个 (from, to) 组合逐个断言（合法 17 / 被拒 64）；四个终态出边为空；
   `PARTIALLY_FILLED` 是唯一合法自环；被拒转移可表达为审计值（Task 1）；
2. **同一命令两次产生一个订单**；重放返回原对象而非 409；same key / different payload
   冲突关闭；空 key 被拒；key 按 `command_kind` 分域（Task 1）；
3. 执行对象拒绝 `research` / `shadow` / `limited_live` 三个阶段；
   `oms.py` 内无任何含 `promote` / `escalate` / `set_stage` 的名字（Task 1）；
4. `forbidden_roots` 扩展至全部真实交易 SDK；**全包扫描无交易 SDK import**；
   无账户凭证字段名（Task 1）；
5. `Role.TRADER` 无法批准自己的 intent；**`Role.ADMINISTRATOR` 同样无法**；
   审批门查 `APPROVE_PORTFOLIO` 而非 `SEND_ORDER`；
   `PermissionPolicy.default()` 的 grants 逐行断言未变；`Permission` 仍是 8 值（Task 2）；
6. **`Role.AGENT` 完全没有执行路径**：在第一道门被拒，risk 未运行，broker 未被调用；
   `Role.RESEARCHER` 同样（Task 2）；
7. pre-trade risk 签名不含任何 caller-supplied limit；`UNAVAILABLE` 拒绝下单而非放行；
   复用 P-5 的 `evaluate_eligibility()`；hash 覆盖 policy hash（Task 2）；
8. **kill switch 拒绝一个已通过 risk 与审批的 intent**；不改写被它阻断的审批；
   不阻断撤单；scope 分级生效；engage/release 均需理由（Task 2）；
9. 过期 / scope 不符 / 被取代审批均不授权；`limited_live` scope 被拒并记账（Task 2）；
10. Paper broker 确定性：同输入逐字节相同事件；无 `datetime.now`；
    无网络与凭证词汇；broker 层幂等独立于 OMS 层；sequence 严格递增（Task 3）；
11. `Order` 恰好一个含 `broker` 的字段；OMS 不 import 任何 adapter；
    无 `if broker == "paper"` 分支（Task 3）；
12. fill policy hash 覆盖 ADR-0006 五个版本；**费率变更是新版本**；
    次交易日成交来自日历而非 `timedelta(days=1)`；`LOCKED_UP` 拒绝买单（Task 3）；
13. 六个故障 fixture 全部可确定性复现；disconnect raise 而非返回空；
    disconnect-after-fill 在下次 poll 暴露成交（Task 3）；
14. **周五买入周一可卖**（跨周末，来自日历）；当日买入当日不可卖；
    **卖出所得当日可用**；`settlement_days` 来自 rule set（Task 4）；
15. 印花税只在卖出侧；费用版本化且既有条目不被追溯改写；
    freeze/release 跨生命周期净为零；available 不可为负（Task 4）；
16. 现金分红加现金不改股数；送股改股数**并**重算 cost per share；
    配股加股数并扣现金，未认购也记录；碎股拒绝而非四舍五入（Task 4）；
17. **对账只产出 break，从不修正**：签名无 repository/connection/store；
    运行前后全部持仓与现金 hash 相同；**无 `CORRECTED` 状态**；
    `EXPLAINED` 保留原差额（Task 4）；
18. material break 创建 Incident 并阻断新订单；immaterial 不创建不阻断；
    break_id 对同一分歧稳定；检测次数不被去重掩盖；owner scope 为 `execution`（Task 4）；
19. 五类 mismatch 各一测试；日终 target/order/fill/position/cash 闭合；
    缺 statement 报 `unavailable` 而非 `balanced`（Task 4）；
20. ADR-0014 存在且状态明确；执行表不在 `research`/`serving`/`canonical`；
    数据库层 append-only trigger；唯一索引强制幂等；
    `deployment_stage` CHECK 只许 `paper`；break 的 expected/observed 不可 UPDATE（Task 5）；
21. 九个只读 endpoint 全部报 `paper`；query/header/body/route 四种形状均不能提升；
    OpenAPI 与生成类型中执行相关 schema 无 `limited_live`（Task 5）；
22. HTTP 层幂等：重复 POST 返回同一 order_id 且第二次为 200；
    缺 key 为 422；same key/different body 为 409；拒绝带 problem details 理由（Task 5）；
23. 七分区投影按状态机顺序；服务端聚合；`empty` 与 `unavailable` 区分；
    动作等级由服务端声明；Agent 投影无 guarded/irreversible 动作（Task 5）；
24. 阶段标签来自服务端 envelope 而非前端常量；无 stage 切换器、Live 开关、账户入口；
    `limited_live` 即使被发送也不渲染（Task 6）；
25. `DangerousAction` 三级；irreversible 需输入对象 id；
    Agent 投影下动作**不渲染**而非禁用；组件不从 principal 推断权限（Task 6）；
26. Breaks 面板**无任何"修正"控件**；九态非颜色区分；持仓分 settled/unsettled；
    现金分 available/frozen/settled；费用分三项（Task 6）；
27. `verify_execution_browser.py` 28 个检查点（7 面板 × 4 视口）全过；
    无页面级溢出；Figma fixture 零泄漏（Task 6）；
28. 七类 replay 事件全部收敛到同一账本 hash；重复按 event_id 识别；
    sequence gap 被检测（Task 7）；
29. restart / day boundary / backup-restore 三者均不改变最终账本；
    **至少一次真实进程重启与一次真实 restore 演练**，含 RPO/RTO 实测（Task 7）；
30. 三个 worker dry-run 默认；非 `paper` 阶段被拒；replay 不能建单；
    reconciliation 不能写账本（Task 7）；
31. 真实日历 soak 完成（时长经用户批准）；**逐日记录含 0 intent 的日子**（Task 7）；
32. Evidence 十节含 81 格转移表（17 合法 / 64 被拒）、32 格权限表、四层幂等结果、逐日 soak 与明确否认（Task 7）；
33. 后端 unittest / compileall / ruff / mypy 全过；前端 Vitest / lint / build 全过；
    `git diff --check` 干净；一个 Task 一个独立提交（Task 5 三个、Task 6 三个）。

## 明确不在本 plan 范围

- **任何真实券商连接、真实账户读取、真实下单/撤单/改单** —— ADR-0010 决策 1/5/6；
  需 P11 的新授权；
- **真实交易 SDK 安装** —— 决策 5 明确禁止，且有两个测试守着；
- **账户凭证存储、secret manager、2FA/unlock** —— 属 P11 的强制前提；
- **券商模拟环境（simulation account）** —— ADR-0010 决策 1 刻意不选它，
  理由是账户、网络、时钟与供应商状态会降低确定性并模糊真实交易授权的边界；
- **真实券商对账单对账** —— statement 由内部 Paper Broker 产生；
  真实只读对账属 P11 的 `broker_read_only` 级；
- **算法执行（TWAP/VWAP 拆单、智能路由）** —— fill policy 是单笔参考价成交，
  拆单算法需独立设计与 ADR；
- **限价单簿模拟、排队优先级、逐笔撮合** —— 确定性 fixture 不模拟微结构；
- **改单（replace/amend）** —— Step 09 验收提到 `cancel/replace`，
  本 plan 只实现 cancel；replace 在 A 股实践中是撤单重下，
  作为一个复合命令实现需要它自己的幂等与状态语义，属后续工作；
- **多账户、多币种、融资融券、期权、可转债** —— 单账户单币种（CNY）现货；
- **实时行情与盘中撮合** —— fill policy 消费日线与 ADR-0006 的 VWAP 口径；
- **通知发送（邮件/IM/webhook）** —— P-8 已声明通知渠道未获批准；
- **真实身份提供者** —— System/Users 页保持 `unavailable`；
- **`strict_historical` 执行** —— `RunContext` 已在构造时拒绝该组合；
- **soak 时长的最终冻结值** —— D2 决策，本 plan 建议 10 个交易日，需用户批准。

## 本 plan 完成后仍然成立的限制

- **P10 Gate 未通过。** Gate 要求「连续 soak 和日终 Artifact 完成」，
  而真实 soak 需要真实已批准 `TargetPortfolioSnapshot`；无真实 target 时
  soak 只证明链路连续运行不出错；
- **P10 完成不授权实盘，Paper 测试结果不能推出 Live 安全。**
  ADR-0010 结果段逐字：「Paper 测试结果不构成真实交易授权或模型有效证据」。
  P11 需用户针对券商、账户、市场、标的、金额、有效期与允许动作的新的明确授权，
  以及一份新的 Broker/Security ADR；
- P2、P4、P5、P6、P7、P8、P9 全部 Gate **不因本 plan 改变**；
- **确定性 Broker 不代表真实券商行为** —— 它刻意不含网络、时钟、限流、
  微结构、报盘拒绝码、席位规则与结算差异；在它上面全绿是关于本平台的证据，
  不是关于任何真实对手方的证据；
- **职责分离有测试但没有两个真实用户** —— 无 identity provider，
  运行时唯一 principal 是 `Principal.anonymous()`（仅 `read_public`）。
  因此每一个执行命令在当前运行时都会被诚实拒绝；
- **对账未被真实对手方验证** —— statement 是内部产物，不是券商对账单；
- **Paper 盈亏不是策略证据** —— 输入为 `normalized_current`，
  无 PIT 验证、无样本外、无多重检验校正，样本期仅为 soak 天数；
- **七个页面 `design_status` 全部为 `missing`** —— 17 个 Figma frame 中
  没有任何执行页；31 页逐像素 parity 计数**仍为 0/31**；
- 侧栏 280 px（SPEC-045）与 `3:1569` 的 248 px sidebar / 1192 px main-content
  存在已知差异，属已批准差异，**不得改回**；
- Vite 的 AntD large-chunk warning 仍然存在，**不得隐藏也不得写成已修复**；
- **soak 只覆盖 soak 期间真实发生的事件** —— 未出现的故障（封板、临时停牌、
  报盘拒绝、长假结算特例）仍可能完全未被验证；
- **ADR-0014 若保持 `Proposed`，Task 5 的建表不得执行** ——
  新增第七个职责 schema 需用户批准。
