# P-7 事件、Agent 与供应链 P8 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把公告、新闻、研报和供应链事实变成可追溯的 Document → Event → Claim → Impact 链；建立一个**只能解释、不能拥有真值**的受治理 Agent 运行时；实现带 clustered/bootstrap SE、matched controls 与 FDR 的事件研究；在通过独立 Review 后由一个**新的** CompilerVersion 产出带 event 分项的 InvestmentView v2；并交付 PUI-07 的 Events / Cases / Agents 三个产品面。

**Architecture:** `domain/disclosure.py`（188 行）与 `application/disclosure_ledger.py` 已经**成熟**：`RawObject` 覆盖 hash / license / retention / redistribution / parent 链，`OfficialDisclosure` 覆盖 published/available/first-tradable 三时间、`version_sequence`、`supersedes_disclosure_id` 与 `publication_time_precision`；`adapters/object_store/local.py` 已能内容寻址地保存 PDF 并防符号链接逃逸。本 plan **复用它们，一个字段都不重建**。新建的只有它们确实没有的四块：非官方来源的 `DocumentVersion` 许可包裹层、`domain/events.py`（实体链接与去重）、`domain/agent_research.py` + `application/agent_runtime.py`（受治理 Agent）、`domain/supply_chain.py`（带有效区间的关系图）、`domain/event_study.py`（AR/CAR 统计）。统计学复用 `domain/factor_statistics.py` 的 `block_bootstrap_mean_ci()` 与 `domain/factor_validation.py` 的 `benjamini_hochberg()`；只有 clustered SE 与 matched controls 是新数学。

**Tech Stack:** Python 3.11+、已有 `domain/disclosure.py` / `factor_statistics.py` / `factor_validation.py` / `expected_return.py` / `investment_view.py` / `governance.py`、`adapters/object_store/local.py`、PostgreSQL 17（端口 55432）、scipy + statsmodels（交叉验证）、React 19 + TypeScript + AntD 6、Playwright（`platform/.venv/bin/python`，Chrome channel）

## Global Constraints

继承 `AGENTS.md`、`docs/07-detailed-system-spec.md`（SPEC-024、027–029、047、053、056）、**ADR-0008（Accepted）**与其余已接受 ADR，**每个 Task 都适用**：

- `domain/` 不导入 FastAPI / SQLAlchemy / provider SDK / LLM SDK / HTTP 客户端 / 前端概念；
  模型与检索实现在 adapter，模型**合同**在 domain
- **Agent 是抽取器与假设生成器，永远不是权威**：LLM 文本不得成为价格、财务数值、
  公告时间或交易结果的来源；Agent 不得提升 trust state、不得修改 published/available time、
  不得生成权重或订单、不得审批
- **无引用的 Agent 输出不能进入 `InvestmentView`**；schema invalid 的输出必须隔离而非部分接受
- **去重不删除任何原文版本**：near-duplicate 必须记录"保留哪一条为权威、丢弃了什么、为什么"
- **correction/retraction 追加新版本并触发下游 Review**（ADR-0008 决策 4），
  绝不覆盖旧版本，绝不静默更新已发布的下游结论
- 重叠事件窗口造成横截面相关，**标准误必须 clustered 或 bootstrap**；
  跨事件类型的多重检验必须做 FDR 控制；两者缺一即为制造显著性
- 供应链关系多为文本推断，**不确定的关系不得断言为事实**；每条边必须有有效区间
- **`ExpectedReturnCompilerV0` 的 `event must remain unavailable before P8` 守卫不可放宽**；
  event 分项走**新的** CompilerVersion，与 P-6 的 `append_active()` 同一模式
- 缺失、不可评估、不可比、许可不允许必须显式表达，**禁止填零**
- `RunContext` 固定：研究实验用 `(current_research, research)`；`strict_historical` 必须失败关闭
- 通知只引用 Frozen Artifact 与许可允许的摘要/链接，**不在消息里重新生成权威数值**（ADR-0008 决策 5）
- worker 默认 dry-run，真实写入需 `--private-local-research-ack --execute`
- 前端只消费服务端投影；不在浏览器做去重、实体解析、置信度提升或引用资格判定
- **不调用任何真实 LLM provider**，直到用户就成本与许可给出明确授权
- 未经用户明确授权不 commit、不 push

## 前置条件（两条硬依赖）

### 依赖 P-1（文档来源）

事件链的第一环是文档。当前真实小样本是 P3-W04c 的 8 份官方 PDF（下节逐条引用），
**没有任何新闻、研报或搜索来源入库**。`docs/14-data-source-catalog-and-agent-routing.md` §12
已冻结顺序：

> 1. 公司公告和财务修订：巨潮/交易所/公司披露；
> 2. current 公司新闻：经资格审查的 AkShare 新闻或 Futu 只读资讯 adapter；
> 3. 行业/宏观新闻：经资格审查的搜索 provider；
> 4. donor 只贡献查询构造、缓存、超时、官方域名优先和相关性排序模式；
> 5. P8 前不把新闻情绪或 LLM 摘要写成事件 Alpha。

因此本 plan 的 Task 1 第一步是**逐源许可登记**，不是写代码。没有已登记许可的来源，
Task 2 的去重就只有一个来源可去重 —— 那不是去重，是恒等映射。

### 依赖 P-5（组合）

事件影响只有落到组合上才能度量。"这个事件值多少" 的答案是
「把它计入 InvestmentView 后，组合的成本后收益变了多少」，而组合、成本模型与现实回测
在 P-5。没有它们，事件研究的 CAR 只是一个未扣成本的横截面平均，
**不能回答"事件贡献是否有增量价值"**。

因此 Task 5 的增量价值检验与 Task 6 的 Desk 事件分区**必须在 P-5 完成后执行**。
Task 1–4 的文档、事件、Agent 与图合同可以先行。

校验依赖是否就绪：

```bash
cd platform && source /tmp/asp_env.sh
.venv/bin/python - <<'PY'
import os, psycopg
with psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True) as c:
    for table in ("evidence.raw_objects", "evidence.official_disclosures",
                  "research.investment_views", "research.signal_snapshots"):
        try:
            print(table, c.execute(f"select count(*) from {table}").fetchone()[0])
        except Exception as error:      # noqa: BLE001 - report, do not hide
            print(table, "MISSING:", error)
PY
```

Expected（P-1/P-5 完成后）：`raw_objects >= 11`、`official_disclosures >= 8`、
组合与信号表存在。若 `investment_views = 0`，Task 5 的增量价值一节只能产出
`unavailable + reason`，**不得用 fixture 数字冒充**。

## ADR-0008 是本 plan 的骨架（Accepted，逐字引用）

`docs/adr/0008-event-document-retention-policy.md` 状态 `Accepted`、日期 2026-08-14。
五条决策**原文**如下，本 plan 每个 Task 都回来对照：

> 1. 交易所、上市公司和依法允许保存的正式公告优先保存合格原文、hash、published/fetched/available time 和修订关系。
> 2. 新闻、研报和商业数据库内容逐源检查许可：允许保存时进入受限 raw evidence；不允许保存时只保留许可允许的 metadata、stable reference、hash 或短期缓存。
> 3. 原文不可保存不等于可以让 LLM 复述后长期保存；Agent 输出仍受原来源许可和引用合同约束。
> 4. correction/retraction 不覆盖旧版本，必须追加新版本并触发下游 Review。
> 5. 通知只引用 Frozen Artifact 和许可允许的摘要/链接，不重新生成权威数值。

结果段原文：

> P8 Document/Event/Agent 领域核心保持 provider-neutral。每个 adapter 在批量摄取前仍需字段和许可登记；未通过时失败关闭。

这五条各自落在哪里：

| ADR 决策 | 落地位置 | 可执行断言 |
|---|---|---|
| 1 | 复用 `RawObject` + `OfficialDisclosure`（已实现） | Task 1 Step 2 的回归守卫 |
| 2 | 新增 `DocumentVersion` + `SourceLicenceProfile` | `test_metadata_only_source_stores_hash_but_never_the_body` |
| **3** | `AgentClaim.derived_retention_ceiling` | `test_llm_restatement_cannot_outlive_its_source_licence` |
| **4** | `DocumentVersion.supersedes_*` + `DownstreamReviewRequest` | `test_corrected_document_invalidates_rather_than_updates` |
| 5 | `ports/notifications.py` + `NotificationPayload` | `test_notification_carries_no_numeric_conclusion` |

决策 3 是最容易被绕过的一条，所以它有专属字段与专属测试。让 LLM 读一篇不可保存的研报、
然后把"摘要"永久存进平台，是对来源许可的规避；ADR 明确禁止，本 plan 用
`derived_retention_ceiling = min(源 retention, 派生 retention)` 在类型层面阻断。

## 已存在的接口（本 plan 消费与复用，不重建）

经 2026-08-16 逐行核实的真实签名。**任何与下文不一致的地方以代码为准**，
并同步修正本 plan 的后续步骤，不要改领域代码去迁就 plan。

### `domain/disclosure.py`（188 行，全部已实现）

```python
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")

class RawObjectKind(str, Enum):
    REQUEST = "request"; RESPONSE = "response"; FILE = "file"

class RetentionPolicy(str, Enum):
    INDEFINITE = "indefinite"; UNTIL_DATE = "until_date"; METADATA_ONLY = "metadata_only"

class DisclosureStatus(str, Enum):
    PUBLISHED = "published"; CORRECTED = "corrected"; WITHDRAWN = "withdrawn"

class DisclosureSource(str, Enum):
    CNINFO = "cninfo"; SSE = "sse"; SZSE = "szse"; BSE = "bse"; COMPANY = "company"

class PublicationTimePrecision(str, Enum):
    """Precision supplied by the official index, never inferred from a clock value."""
    EXACT = "exact"; DATE_ONLY = "date_only"

@dataclass(frozen=True)
class RawObject:
    """One immutable request, response, or document body plus its usage policy."""
    raw_object_id: str
    object_kind: RawObjectKind
    content_hash: str                    # 必须匹配 sha256:<64 hex>
    source_url: str                      # 必须是 http(s)
    provider_id: str
    retrieved_at: datetime               # 必须 timezone-aware
    media_type: str
    storage_uri: str
    license_id: str
    retention_policy: RetentionPolicy
    retention_until: date | None          # 只有 until_date 允许非 None，且必填
    redistribution_allowed: bool          # 必须是 bool，不接受真值等价物
    parent_raw_object_id: str | None = None   # 不得等于自身

@dataclass(frozen=True)
class OfficialDisclosure:
    """One public version in an official disclosure document chain."""
    disclosure_id: str
    document_key: str
    external_document_id: str
    company_id: str
    security_id: str | None
    source_system: DisclosureSource
    title: str
    document_type: str
    report_period_end: date | None
    published_at: datetime
    available_at: datetime               # >= published_at
    first_tradable_at: datetime          # >= available_at
    version_sequence: int                # >= 0
    status: DisclosureStatus
    raw_object_id: str
    supersedes_disclosure_id: str | None
    status_reason: str | None
    publication_time_precision: PublicationTimePrecision = PublicationTimePrecision.EXACT
```

`OfficialDisclosure.__post_init__` 的四条不变量**已经是本 plan 想要的语义**，
不需要重写，只需要在新对象上镜像：

1. `date_only` 精度必须使用本地午夜 —— 不允许把日期伪造成盘前/盘后精确时刻；
2. `available_at >= published_at >= ...` 时间序不可倒置；
3. `version_sequence == 0` 必须 `published`、不得 `supersedes`、不得带 `status_reason`；
4. `version_sequence > 0` **必须** `corrected` 或 `withdrawn`、必须有
   `supersedes_disclosure_id` 与 `status_reason` —— 即 ADR-0008 决策 4 的一半已经在类型里。

### `application/disclosure_ledger.py`（64 行，全部已实现）

```text
class DisclosureLedger:
    def __init__(self, repository: DisclosureRepository, object_store: RawObjectStore) -> None
    def capture_raw_object(self, *, raw_object_id, object_kind, payload: bytes,
        source_url, provider_id, retrieved_at, media_type, license_id,
        retention_policy, redistribution_allowed,
        retention_until=None, parent_raw_object_id=None) -> RawObject
    def register_disclosure(self, value: OfficialDisclosure) -> OfficialDisclosure
```

`capture_raw_object` 的第一行守卫是本 plan 的基石：

```python
if retention_policy is RetentionPolicy.METADATA_ONLY:
    raise PermissionError("metadata_only policy forbids payload persistence")
```

**它必须继续成立。** 不可保存的新闻正文不能走这条路径 —— Task 1 会新增一条
只登记 hash 与 stable reference 的并行路径，而不是放宽这个守卫。

`ports/disclosure.py`：

```python
class DisclosureRepository(Protocol):
    def register_raw_object(self, value: RawObject) -> RawObject: ...
    def get_raw_object(self, raw_object_id: str) -> RawObject | None: ...
    def list_raw_objects(self) -> tuple[RawObject, ...]: ...
    def register_disclosure(self, value: OfficialDisclosure) -> OfficialDisclosure: ...
    def timeline(self, document_key: str) -> tuple[OfficialDisclosure, ...]: ...

class RawObjectStore(Protocol):
    def put(self, payload: bytes) -> str: ...
```

### `adapters/object_store/local.py`（143 行，PDF 已可保存）

```text
class LocalRawObjectStore:
    def __init__(self, root: Path) -> None          # root 被 resolve()
    def put(self, payload: bytes) -> str            # 返回 file:// URI
```

`put()` 的安全检查（逐条已核实）：非 `bytes` 抛 `TypeError`；路径固定为
`root/sha256/<digest>`；已存在且**内容不同**时抛 `RuntimeError("content-addressed object mismatch")`；
写入用 `open("xb")` 独占创建，`FileExistsError` 时再比对一次内容。
即：同 hash 同内容幂等，同路径不同内容冲突关闭。

```text
class LocalArtifactReader:
    def __init__(self, root: Path, *, max_bytes: int = 16 * 1024 * 1024) -> None
    def read(self, value: Artifact) -> bytes
```

`read()` 的安全检查（逐条已核实，本 plan 的 Artifact 引用全部经它）：

- 非 `Artifact` → `TypeError`；
- `storage_uri` 必须 `file://` 且无 netloc/query/fragment，否则 `ArtifactIntegrityError`；
- 路径必须 `relative_to(root)`，逃逸 → `ArtifactIntegrityError`；
- 相对路径必须**恰好**是 `("sha256", digest)`，否则 `ArtifactIntegrityError`；
- 用 `O_NOFOLLOW` + `dir_fd` 逐级打开，`ELOOP/ENOTDIR` → "unsafe link" `ArtifactIntegrityError`；
- `fstat` 必须是 regular file；超过 `max_bytes` → `ArtifactIntegrityError`；
- 读完后重算 sha256，与 `Artifact.content_hash` 不符 → `ArtifactIntegrityError`。

**PDF 已经能存了。** 本 plan 不需要新的对象存储，`media_type="application/pdf"` 直接可用。

### `validation/gates.py` —— `ResearchKind.EVENT` 的要求已经写好

```text
class ResearchKind(str, Enum):
    FACTOR = "factor"; STOCK_SELECTION = "stock_selection"
    MARKET_TIMING = "market_timing"; EVENT = "event"
    PORTFOLIO = "portfolio"; EXECUTION = "execution"

ResearchKind.EVENT: ValidationPolicy(
    ResearchKind.EVENT,
    _requirements(
        ("event_time_integrity", "prove event publication and tradable availability time"),
        ("abnormal_return_model", "remove market, industry, and factor movement"),
        ("event_window_car", "measure cumulative abnormal returns"),
        ("clustered_or_bootstrap_se", "handle dependence and event clustering"),
        ("matched_controls", "compare similar non-event firms"),
        ("overlap_and_multiple_testing", "control overlapping events and discovery bias"),
    ),
),
```

**这六项不是本 plan 发明的，是已经声明的需求。** 本 plan 实现它们，
并让 `ValidationPolicy.missing(completed_keys)` 在缺任一项时返回非空 —— 那就是 Gate 不通过。
Task 5 的六个小节与这六个 key 一一对应，**不增不减不改名**。

### `application/permissions.py` —— `Role.AGENT` 是只读的

```text
class Role(str, Enum):
    VIEWER; RESEARCHER; DATA_OPERATOR; REVIEWER
    PORTFOLIO_MANAGER; TRADER; ADMINISTRATOR; AGENT = "agent"

class Permission(str, Enum):
    READ_PUBLIC; READ_ARTIFACT; CREATE_EXPERIMENT; MANAGE_DATA
    APPROVE_RESEARCH; APPROVE_PORTFOLIO; SEND_ORDER; ADMINISTER

# PermissionPolicy.default() 中：
read = frozenset({Permission.READ_PUBLIC})
...
Role.AGENT: read,          # ← 只有 READ_PUBLIC，连 READ_ARTIFACT 都没有
```

`Role.AGENT` 的授权集是 `{READ_PUBLIC}` —— **比 `VIEWER` 还窄的等价物，且连
`READ_ARTIFACT` 都不包含**。本 plan 不修改这一行。Task 3 会写一个测试，
逐个断言 Agent 对其余七个 Permission 全部为 `False`，这样将来任何人放宽它都会红。

### 确认不存在（必须从零建，2026-08-16 核实）

```bash
ls src/a_share_platform/domain/events.py          # 不存在
ls src/a_share_platform/domain/agent_research.py  # 不存在
ls src/a_share_platform/domain/supply_chain.py    # 不存在
grep -rn "entity_link\|dedup\|anthropic\|openai" src/   # 无匹配
```

没有实体链接、没有去重、没有任何 LLM 客户端。这是好事：意味着
**本 plan 可以在第一个 fake model port 上把治理边界钉死，再谈接哪个 provider**。

## 真实小样本：P3-W04c（本 plan 的唯一真实文档基础）

`docs/13-p3-implementation-evidence.md` §P3-W04c 原文事实：

> - 4 家公司：平安银行、五粮液、赛隆药业和立华股份；
> - 8 份巨潮官方 PDF，每份保存 source URL、SHA-256、publication/available/
>   first-tradable/retrieval time、时间精度和 retention；
> - 五粮液和立华股份各 1 条原始/更正链，同一报告期旧版不被覆盖；
> - 覆盖正常盘后年报、盘前可用、周末公告、财报更正、同期多版、单位/币种冲突、
>   缺失字段、一次性项目和供应商/官方不一致九类场景；
> - 时间元数据明确分为 5 条 `exact` 和 3 条 `date_only`；`date_only` 不伪造盘前或
>   盘后精确时刻；
> - 12 条官方观察为 `pit_verified/passed`；1 条来自 AkShare/Sina 的当前供应商
>   观察为 `normalized_current/blocked`，不能进入 strict historical；
> - 五粮液 2025 Q1 营业收入 current 因供应商时间/精度/单位冲突显式 blocked，
>   strict 从官方更正版选中 `17085765657.95 CNY`。

真实开发库读取结果：`raw_objects=11`、`official_disclosures=8`、
`financial_fact_observations=13`、`lineage_edges=55`、`dataset_versions=13`、
`dataset_quality_reports=28`、`ingestion_jobs=19`。

`platform/fixtures/p3/pit_fixture_pack.v1.json` 的真实内容（已核实）：
`company_codes` 4 个（`000001` 平安银行股份有限公司、`000858` 宜宾五粮液股份有限公司、
`002898` 赛隆药业集团股份有限公司、`300761` 江苏立华食品集团股份有限公司）、
`evidence` 8 条、`revision_chains` 2 条、`provider_conflicts` 2 条。

五粮液修订链是本 plan 最重要的真实案例，因为它同时是 ADR-0008 决策 4 的样本：

```json
{"chain_id": "cninfo:000858:2025-q1:revision-20260430",
 "original":  {"external_document_id": "1223311586",
               "available_at": "2025-04-28T09:15:00+08:00",
               "expected_facts": {"income.operating_revenue": "36940356116.35 CNY"}},
 "corrected": {"external_document_id": "1225273125",
               "available_at": "2026-04-30T18:20:27+08:00",
               "expected_facts": {"income.operating_revenue": "17085765657.95 CNY"},
               "supersedes_external_document_id": "1223311586"}}
```

同一报告期营业收入从 `369.4 亿` 更正为 `170.9 亿` —— 差 2.16 倍。
**任何在更正前基于原版建立的事件结论都必须失效重审，不能悄悄改数字。**
Task 5 的 `test_corrected_document_invalidates_rather_than_updates` 直接用这两个 ID。

**本 plan 不得扩大这个小样本的含义。** 8 份 PDF 是 4 家公司的财报与更正，
**不是一个事件研究样本**：它没有足够的事件数做横截面推断。因此 Task 5 的真实运行
会诚实产出 "sample_size below minimum" 的 `unavailable`，而这是被验收的结果。

## 原型参照（真实文本，逐字提取）

`docs/assets/prototype/figma-node-summary.json` 的 `frames` 是 dict，键为 node id。
`9:2` = `10-events-intelligence`，`1440×1200`，**没有 320/768/1024 独立 Frame**，
故窄视口只记录设计假设。SVG 共 182 个 `<text>` 节点。

| 区域 | 真实文本 |
|---|---|
| 二级 Tab | `Universe & Screen` `Security` `Events` `Watchlists/Cases`（`Events` 为选中态） |
| 面包屑 | `RESEARCH / P8 · EVENT INTELLIGENCE` |
| 标题 | `Events · 公告与新闻` / `事实先于解释 · 双时间排序 · 影响路径可审计` |
| 四张摘要卡 | `新增材料` `128` `公告31 · 新闻97`；`已归并事件` `26` `去重与实体解析完成`；`待人工确认` `9` `影响路径或时点不确定`；`进入 View` `0` `P8 前保持 unavailable` |
| 事件表标题 | `事件流与证据资格` |
| 事件表列（8 列） | `时间` `证券` `类型` `标题` `来源` `信任` `影响` `Case` |
| 类型枚举（表内出现） | `公告` `业绩` `供应链` `政策` |
| 来源枚举（表内出现） | `CNInfo` `交易所` `新闻源` `官方部门` |
| 信任枚举（表内出现） | `高` `中` `待确认` |
| 影响枚举（表内出现） | `待评估` `未进入 View` |
| 状态卡标题 | `事件处理状态` |
| 四条状态 | `事件归并` READY `同证券 / 同主题 / 相近时点聚类`；`冲突事实` BLOCKER `3 组来源说法不一致`；`Agent 摘要` ATTENTION `只解释，不拥有数值和时间真值`；`P8 Gate` BLOCKER `引用、影响路径、失效条件、增量价值` |
| 边界卡 | `可信使用边界` / `无引用结论不能进入 InvestmentView；` / `事件链未实施时分项保持 unavailable。` |
| 五段流程条 | `INPUT · 输入` `公告/新闻/研报/舆情` `引用与双时间`；`PROCESS · 处理` `去重→实体→事实` `冲突→影响路径`；`OUTPUT · 输出` `EventFact/Impact` `引用与不确定性`；`ACTION · 操作` `关联 Security/Case` `请求人工确认`；`GATE · 门禁` `无引用不得入 View` `缺失不填0` |
| 页脚 | `Prototype Notes · P8 事件 Agent 与供应链 · 测试通过不等于模型科学有效` |

**Frame 里 12 行事件（`EVT-101`…`EVT-112`）与四个计数 `128` / `26` / `9` / `0` 全部是
design fixture**，涉及 `600519 贵州茅台`、`300750 宁德时代`、`000333 美的集团`、
`600036 招商银行` —— 这四家**都不在** P3-W04c 的真实四家里。Frame 自己标了
`PROTOTYPE ONLY` `DESIGN FIXTURE` `非生产数据` `不代表 PIT / 科学有效`。
`verify_events_browser.py` 会把这些字符串当作**禁止出现**的字面量来断言。

唯一可以照抄进 runtime 的数字是 `进入 View` 的 `0` —— 而且原因必须是真实的
`P8 前保持 unavailable`，不是硬编码的 0。

原型侧栏画 224 px；**运行时按更高优先级的 SPEC-045 使用 280 px**（`CLAUDE.md` §0
记录的未裁决冲突）。本 plan 不改运行时，也不改任一真源，只在 Evidence 记录该差异。

`docs/22-prototype-runtime-gap-audit.md` §5 当前把三行记为 `placeholder`：

| # | 页面 | 当前运行时 | 参照 | 阶段 | 轨道 |
|---:|---|---|---|---:|---|
| 4 | Research / Events | `placeholder` | `10-events-intelligence` | P8 | PUI-07 |
| 5 | Research / Watchlists/Cases | `placeholder` | 31 页蓝图 | P8/P9 | PUI-07/PUI-08 |
| 30 | System / Agents | `placeholder` | 31 页蓝图 | P8/P9 | PUI-07/PUI-08 |

`frontend/src/pages/WorkspacePage.tsx` 的 `activationReasons` 现在写死：

```ts
events: '事件账本将在 P8 接入；当前不生成新闻情绪或事件收益假值。',
agents: 'Agent runtime 尚未启用，且 Agent 永远没有交易权限。',
```

Task 6 替换前两条为真实组件；**`agents` 那句关于交易权限的话必须保留在页面上**，
因为它不是"尚未启用"的临时说明，而是一条永久成立的边界。

## 五个必须先想清楚的陷阱

本 plan 的多数篇幅在防这五件事。它们不是实现细节，是决定结论是否有意义的前提。

### 陷阱一：去重是静默数据丢失的高发地

同一份业绩预告会同时从巨潮（官方 PDF，`available_at` 精确）和某新闻源
（转述，措辞不同，`published_at` 晚 40 分钟且可能只有日期精度）到达。
朴素去重会按"相似度 > 阈值就合并，保留先到的那条"处理 —— 于是：

- 若新闻先入库，**权威版本被当成重复丢弃**，事件时间变成新闻时间，晚了 40 分钟；
- 若两条措辞差异大到低于阈值，**同一件事变成两个事件**，事件数虚增，
  横截面样本里出现两条高度相关的观测；
- 无论哪种，被丢弃的那一条**没有留下记录**，事后无法发现错误。

因此 `EventCluster` 的设计不是"合并成一条"，而是
**"选一条为权威 + 完整列出全部重复及其差异 + 记录选择理由"**：

```python
authoritative_document_version_id: str
duplicate_document_version_ids: tuple[str, ...]     # 不得为空即不得静默
selection_rule_version: str
selection_reason: str
```

并且当两个候选**权威等级相同**时，必须返回 `CONFLICT` 而不是按时间或字典序挑一个。
"任意挑一个" 是所有静默丢失里最难查的一种。

### 陷阱二：Agent 成为事实来源

Agent 输出的结构和人工录入的结构一样：都是一段带数字的 JSON。
一旦它进入同一张表、同一个 API、同一个前端字段，
「谁说的」这个信息就消失了，而这是唯一重要的信息。

三层防线：

1. **类型层**：`AgentClaim.claim_kind ∈ {FACT, INFERENCE, OPINION, RUMOR}` 必填；
   `FACT` 类 claim 若其 `field_id` 落在 `GOVERNED_FIELD_DENY_LIST`
   （价格、财务数值、公告时间、成交结果）则**构造即拒绝**；
2. **引用层**：任何 claim 必须至少一条 `Citation`，且每条 citation 必须解析到
   一个已登记的 `DocumentVersion` + 字符区间；无引用 claim 不能进入 View；
3. **权限层**：`Role.AGENT` 只有 `READ_PUBLIC`，连 `READ_ARTIFACT` 都没有；
   Agent 无法写、无法批、无法下单。

三层各有独立测试，因为绕过任一层的方式都不同。

### 陷阱三：更正被当成"更新"

五粮液营业收入从 `369.4 亿` 更正为 `170.9 亿`。如果实现把它当成一次
`UPDATE ... SET value = ...`，那么：

- 更正前建立的所有事件结论**会在数据上变得看起来正确**（因为底层数字已改），
  而它们当时用的是错的输入；
- 无法回答"我们在 2025-05-01 相信了什么"；
- 已冻结的 Artifact 与数据库不一致，而**Artifact 才是真的**。

因此 correction 的唯一合法处理是：追加新 `DocumentVersion`（`version_sequence + 1`，
状态 `corrected`，`supersedes_*` 指向旧版），并**为每个依赖旧版的下游对象生成一条
`DownstreamReviewRequest`**。旧 View 保持不变且保持可读，新 View 是另一个 `view_id`。

### 陷阱四：重叠事件窗口制造显著性

事件研究的横截面看起来样本很大：500 家公司 × 每年 4 次业绩预告 = 2,000 个事件。
但事件不是独立的：

- 业绩预告集中在 1 月与 7 月，**同一天有几百个事件**，它们共享当天的市场冲击；
- 一个 `[-5, +20]` 的窗口跨 26 个交易日，同一公司相邻两次事件窗口会重叠；
- 政策类事件对整个行业同时生效，行业内所有公司的 AR 高度相关。

用 i.i.d. 标准误算 t 统计量，会把标准误低估到 `sqrt(每日事件数)` 分之一。
一天 100 个事件时低估 10 倍：真实 t=0.3 的噪声显示成 t=3.0。

**这是本 plan 统计部分的核心约束**，落地为两条硬规则：

1. `EventStudySpec` 必须携带 `se_method ∈ {CLUSTERED_BY_EVENT_DATE, BLOCK_BOOTSTRAP}`，
   **没有 `IID` 这个选项**（枚举里根本不定义它，所以无法被配置成它）；
2. 当同一日历日的事件数 > 1 时，`clustered_by_event_date` 是**必需**而非可选；
   Task 5 会写一个测试断言这种输入下要求 `BLOCK_BOOTSTRAP` 之外的方法会被拒绝。

再叠加多重检验：如果对 12 种事件类型 × 3 个窗口 = 36 个假设各做一次检验，
α=0.05 下期望有 1.8 个假阳性。所以必须走已有的
`benjamini_hochberg(hypotheses, spec=BHFamilySpec(...), data_mode=...)`，
且 `BHFamilySpec.family_id/family_version` 必须**在看结果之前冻结**。

忽略这两件事不是"精度略低"，而是**制造显著性**。

### 陷阱五：供应链关系是推断出来的，而且经常是错的或过期的

"A 是 B 的供应商" 这句话的来源通常是：年报里的一句"前五大客户"（不点名）、
一篇券商研报的产业链图、或者一次 LLM 从新闻里的抽取。它们的问题分别是：

- **不点名**：只知道占比，不知道对象 —— 这是"不确定"，不是"未知对象的确定关系"；
- **研报产业链图**：往往是编制时的快照，两年后可能已换供应商；
- **LLM 抽取**：把"某公司为特斯拉产业链概念股"读成"是特斯拉的供应商"。

因此每条边必须有 `effective_from` / `effective_to`（半开区间）、
`evidence_kind`（`DISCLOSED_NAMED` / `DISCLOSED_UNNAMED_SHARE` / `THIRD_PARTY_RESEARCH` /
`INFERRED_FROM_TEXT`）、`confidence` 与 `staleness_limit_days`。
**`INFERRED_FROM_TEXT` 的边不允许 `status = ASSERTED`** —— 它只能是 `HYPOTHESIS`，
不进入传播计算。

还有一个纯图论问题：**两条路径重复计数**。若 A→B 与 A→C→B 同时存在，
把两条路径的影响相加会把一次冲击算两遍。Task 4 要检测出这种情形并拒绝求和，
而不是"大概问题不大"。

## Task 排序的理由

`docs/plans/step-07-p8-events-agents-supply-chain.md` 的六个 Task 顺序是：
来源/许可 ADR 与 Document ledger → Event/entity/dedup → Agent runtime → 供应链图 →
Event Study 和 View v2 → API/页面/通知。本 plan 保持这个顺序并追加一个 Evidence Task，
理由是每一步都是下一步的输入类型：

- Task 2 的去重需要 Task 1 的 `SourceAuthority`，否则"哪条是权威"无法回答；
- Task 3 的 citation 需要 Task 1 的 `DocumentVersion` 与 Task 2 的 `EventCluster`；
- Task 5 的事件研究需要 Task 2 的事件时间与 Task 3 的 claim 分类；
- Task 6 的页面需要前五个 Task 的投影，且必须在 P-5 之后才能算增量价值。

**不要把 Task 3 提前。** 先建 Agent 再建引用目标，会让"引用"退化成自由文本。

---

### Task 1: 来源许可登记与 `DocumentVersion`（不可保存来源的第一等公民路径）

对应 Step 07 Task 1：「新增来源 ADR、`domain/documents.py`、ports/object store/repository/
migration/tests。先 hash/version/time/correction/retraction，再 adapter。」

**Files:**
- Create: `platform/src/a_share_platform/domain/documents.py`
- Create: `platform/src/a_share_platform/ports/documents.py`
- Create: `platform/src/a_share_platform/application/document_ledger.py`
- Create: `platform/migrations/0039_p8_document_ledger.sql`（执行前先 `ls migrations/` 确认真实最大编号再顺延；现有最大为 `0036`，P-5 与 P-6 分别声明 `0037`/`0038`）
- Create: `platform/tests/test_document_versions.py`
- Create: `platform/tests/test_document_ledger.py`
- Create: `platform/tests/test_disclosure_ledger_regression.py`
- Create: `docs/adr/0014-event-source-licence-registry.md`（状态取决于逐源登记结果）
- Modify: `docs/14-data-source-catalog-and-agent-routing.md`（§12 追加逐源登记表）
- Modify: `docs/plans/step-07-p8-events-agents-supply-chain.md`（Task 1：`dependency_blocked` → `in_progress`）
- Create: `docs/28-p8-events-agents-evidence.md`（编号顺延；执行前 `ls docs/*.md` 确认）

**Interfaces:**
- Consumes: 已有 `domain/disclosure.py` 全部、`application/disclosure_ledger.py`、
  `adapters/object_store/local.py` 的 `LocalRawObjectStore.put()`
- Produces:
  ```python
  class DocumentSourceClass(StrEnum):
      OFFICIAL_DISCLOSURE = "official_disclosure"   # 走已有 OfficialDisclosure
      REGULATOR_PUBLICATION = "regulator_publication"
      NEWS = "news"
      SELL_SIDE_RESEARCH = "sell_side_research"
      COMMERCIAL_DATABASE = "commercial_database"

  class SourceAuthority(IntEnum):
      """Ordering used to pick the authoritative version of one event."""
      OFFICIAL = 3          # 交易所 / 上市公司 / 依法允许保存的正式公告
      REGULATOR = 2         # 官方部门发布
      LICENSED_THIRD_PARTY = 1
      UNVERIFIED = 0

  class DocumentBodyDisposition(StrEnum):
      STORED = "stored"                 # 原文已保存，有 raw_object_id
      HASH_AND_REFERENCE_ONLY = "hash_and_reference_only"
      SHORT_TERM_CACHE = "short_term_cache"

  @dataclass(frozen=True)
  class SourceLicenceProfile:
      licence_id: str
      source_class: DocumentSourceClass
      authority: SourceAuthority
      body_storage_allowed: bool
      redistribution_allowed: bool
      retention_policy: RetentionPolicy          # 复用 disclosure.RetentionPolicy
      retention_until: date | None
      derived_text_retention_policy: RetentionPolicy   # ADR-0008 决策 3
      registered_at: datetime
      registration_evidence_id: str
      content_hash: str = field(init=False)

  @dataclass(frozen=True)
  class DocumentVersion:
      document_version_id: str
      document_key: str
      external_document_id: str
      source_class: DocumentSourceClass
      licence_id: str
      authority: SourceAuthority
      title: str
      language: str
      content_hash: str                  # sha256:<64hex>，即使不保存原文也必须有
      canonical_url: str
      body_disposition: DocumentBodyDisposition
      raw_object_id: str | None          # STORED 必填，其余必须为 None
      published_at: datetime
      fetched_at: datetime
      available_at: datetime
      publication_time_precision: PublicationTimePrecision
      version_sequence: int
      status: DisclosureStatus           # 复用 published/corrected/withdrawn
      supersedes_document_version_id: str | None
      status_reason: str | None
      company_ids: tuple[str, ...]
      security_ids: tuple[str, ...]
      version_hash: str = field(init=False)
  ```

- [ ] **Step 1: 先逐源登记许可，不写代码**

ADR-0008 决策 2 要求「新闻、研报和商业数据库内容**逐源**检查许可」。
在 `docs/14-data-source-catalog-and-agent-routing.md` §12 之后追加一张表，
每个候选源一行，至少记录：认证方式与当前是否可用、条款 URL 与查阅日期、
是否允许保存原文、是否允许本地缓存及时长、是否允许再分发、是否允许 LLM 派生文本长期保存、
速率限制、以及**当前结论**（`registered` / `metadata_only` / `not_permitted` / `not_evaluated`）。

候选源按 §12 的既定顺序：巨潮/交易所/公司披露、AkShare 新闻、Futu 只读资讯、
搜索 provider（Tavily / SerpAPI / Bocha / Anspire / MiniMax / Brave / SearXNG —— 
`docs/14` 已记录这些来自 donor 且「多数需要独立 key/条款，当前没有迁移为新平台 runtime，
也没有因 donor 存在而自动获批」）。

**大概率的真实结论是：官方披露 `registered`，其余全部 `not_evaluated` 或
`metadata_only`。** 这不是失败，这是 Task 1 的合法产出 —— 它决定了 Task 2 的去重
在真实数据上只有一个来源可比，因此 Task 2 的多源去重只能在测试合同里验证。
**如实记录，不要为了让 Task 2 有数据而假设某个源已获批。**

- [ ] **Step 2: 先写回归守卫 —— 已成熟的合同不许被弱化**

在动任何新代码之前，先把 `disclosure.py` 的现有不变量钉死。这不是多余的：
本 Task 会新增一条"不保存原文"的路径，最容易的错误实现方式就是放宽
`capture_raw_object` 的 `metadata_only` 守卫。

```python
# platform/tests/test_disclosure_ledger_regression.py
"""Guards on contracts that already work, before P8 adds a parallel path.

`DisclosureLedger.capture_raw_object` refuses METADATA_ONLY outright.  P8 needs a
way to register a document whose body may not be stored, and the tempting
shortcut is to relax that refusal.  These tests make the shortcut fail loudly, so
the new capability has to arrive as a new path rather than as a widened hole.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from a_share_platform.adapters.object_store.local import LocalRawObjectStore
from a_share_platform.application.disclosure_ledger import DisclosureLedger
from a_share_platform.domain.disclosure import (
    DisclosureSource,
    DisclosureStatus,
    OfficialDisclosure,
    PublicationTimePrecision,
    RawObject,
    RawObjectKind,
    RetentionPolicy,
)


class _Repository:
    def __init__(self) -> None:
        self.raw_objects: list[RawObject] = []
        self.disclosures: list[OfficialDisclosure] = []

    def register_raw_object(self, value: RawObject) -> RawObject:
        self.raw_objects.append(value)
        return value

    def get_raw_object(self, raw_object_id: str) -> RawObject | None:
        return next(
            (item for item in self.raw_objects if item.raw_object_id == raw_object_id),
            None,
        )

    def list_raw_objects(self) -> tuple[RawObject, ...]:
        return tuple(self.raw_objects)

    def register_disclosure(self, value: OfficialDisclosure) -> OfficialDisclosure:
        self.disclosures.append(value)
        return value

    def timeline(self, document_key: str) -> tuple[OfficialDisclosure, ...]:
        return tuple(
            sorted(
                (item for item in self.disclosures if item.document_key == document_key),
                key=lambda item: item.version_sequence,
            )
        )


class MetadataOnlyRefusalTest(unittest.TestCase):
    def test_metadata_only_payload_capture_is_still_refused(self) -> None:
        with TemporaryDirectory() as root:
            ledger = DisclosureLedger(_Repository(), LocalRawObjectStore(Path(root)))
            with self.assertRaises(PermissionError):
                ledger.capture_raw_object(
                    raw_object_id="raw:news:1",
                    object_kind=RawObjectKind.RESPONSE,
                    payload=b"a news body we are not allowed to keep",
                    source_url="https://news.example.com/a",
                    provider_id="news_provider",
                    retrieved_at=datetime(2026, 8, 16, 1, 0, tzinfo=UTC),
                    media_type="text/html",
                    license_id="licence:news:unverified",
                    retention_policy=RetentionPolicy.METADATA_ONLY,
                    redistribution_allowed=False,
                )

    def test_an_official_pdf_can_still_be_stored(self) -> None:
        """P3-W04c stores 8 cninfo PDFs through exactly this path."""
        with TemporaryDirectory() as root:
            ledger = DisclosureLedger(_Repository(), LocalRawObjectStore(Path(root)))
            stored = ledger.capture_raw_object(
                raw_object_id="raw:cninfo:1223311586",
                object_kind=RawObjectKind.FILE,
                payload=b"%PDF-1.4 wuliangye 2025 q1",
                source_url=(
                    "https://static.cninfo.com.cn/finalpage/2025-04-26/1223311586.PDF"
                ),
                provider_id="cninfo",
                retrieved_at=datetime(2026, 8, 10, 12, 35, tzinfo=UTC),
                media_type="application/pdf",
                license_id="licence:cninfo:official",
                retention_policy=RetentionPolicy.INDEFINITE,
                redistribution_allowed=False,
            )
            self.assertTrue(stored.content_hash.startswith("sha256:"))
            self.assertEqual(len(stored.content_hash), len("sha256:") + 64)
            self.assertTrue(stored.storage_uri.startswith("file://"))


class CorrectionChainInvariantTest(unittest.TestCase):
    """version_sequence > 0 already forces corrected/withdrawn plus a reason."""

    def _disclosure(
        self,
        *,
        sequence: int,
        status: DisclosureStatus,
        supersedes: str | None,
        reason: str | None,
    ) -> OfficialDisclosure:
        return OfficialDisclosure(
            disclosure_id=f"cninfo:000858:2025-q1:v{sequence}",
            document_key="cninfo:000858:2025-q1",
            external_document_id="1225273125" if sequence else "1223311586",
            company_id="company:CN:000858",
            security_id="security:CN:000858:XSHE",
            source_system=DisclosureSource.CNINFO,
            title="五粮液2025年第一季度报告",
            document_type="quarterly_report",
            report_period_end=date(2025, 3, 31),
            published_at=datetime(2025, 4, 26, tzinfo=UTC),
            available_at=datetime(2025, 4, 28, 1, 15, tzinfo=UTC),
            first_tradable_at=datetime(2025, 4, 28, 1, 30, tzinfo=UTC),
            version_sequence=sequence,
            status=status,
            raw_object_id="raw:cninfo:1223311586",
            supersedes_disclosure_id=supersedes,
            status_reason=reason,
        )

    def test_a_second_version_cannot_claim_to_be_published(self) -> None:
        with self.assertRaises(ValueError):
            self._disclosure(
                sequence=1,
                status=DisclosureStatus.PUBLISHED,
                supersedes="cninfo:000858:2025-q1:v0",
                reason="restated revenue",
            )

    def test_a_correction_must_name_what_it_supersedes(self) -> None:
        with self.assertRaises(ValueError):
            self._disclosure(
                sequence=1,
                status=DisclosureStatus.CORRECTED,
                supersedes=None,
                reason="restated revenue",
            )

    def test_a_correction_must_state_a_reason(self) -> None:
        with self.assertRaises(ValueError):
            self._disclosure(
                sequence=1,
                status=DisclosureStatus.CORRECTED,
                supersedes="cninfo:000858:2025-q1:v0",
                reason=None,
            )

    def test_a_valid_correction_is_accepted(self) -> None:
        value = self._disclosure(
            sequence=1,
            status=DisclosureStatus.CORRECTED,
            supersedes="cninfo:000858:2025-q1:v0",
            reason="operating revenue restated from 36940356116.35 to 17085765657.95 CNY",
        )
        self.assertEqual(value.version_sequence, 1)
        self.assertEqual(value.status, DisclosureStatus.CORRECTED)


class DateOnlyPrecisionTest(unittest.TestCase):
    def test_date_only_precision_refuses_an_invented_clock_time(self) -> None:
        """3 of the 8 P3-W04c PDFs are date_only; a fake 09:15 would be a lie."""
        with self.assertRaises(ValueError):
            OfficialDisclosure(
                disclosure_id="cninfo:000858:2025-q1:v0",
                document_key="cninfo:000858:2025-q1",
                external_document_id="1223311586",
                company_id="company:CN:000858",
                security_id="security:CN:000858:XSHE",
                source_system=DisclosureSource.CNINFO,
                title="五粮液2025年第一季度报告",
                document_type="quarterly_report",
                report_period_end=date(2025, 3, 31),
                published_at=datetime(2025, 4, 26, 9, 15, tzinfo=UTC),
                available_at=datetime(2025, 4, 28, 1, 15, tzinfo=UTC),
                first_tradable_at=datetime(2025, 4, 28, 1, 30, tzinfo=UTC),
                version_sequence=0,
                status=DisclosureStatus.PUBLISHED,
                raw_object_id="raw:cninfo:1223311586",
                supersedes_disclosure_id=None,
                status_reason=None,
                publication_time_precision=PublicationTimePrecision.DATE_ONLY,
            )
```

- [ ] **Step 3: 运行回归守卫，确认全绿**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_disclosure_ledger_regression -v`

Expected: **PASS**，因为它守卫的是已实现行为。这是本 plan 唯一一个一开始就该绿的测试文件。
若有任何一项红，说明 `disclosure.py` 与本 plan 的理解不一致 —— **停下来先查清楚**，
不要修改测试去迁就。把真实结果抄进 Evidence。

- [ ] **Step 4: 写 `DocumentVersion` 红测 —— 不可保存来源的行为**

```python
# platform/tests/test_document_versions.py
"""Documents from sources whose body may not be stored.

ADR-0008 decision 2 splits sources in two: official announcements may keep the
body, while news, sell-side research and commercial databases need a per-source
licence check and may end up as hash plus reference only.  Both halves still need
a version chain and dual timestamps, so the contract has to carry a body
disposition rather than assuming a stored body exists.

Decision 3 is the one that needs a field of its own: being unable to keep the
original does not license keeping an LLM restatement of it forever.  The derived
retention ceiling therefore travels with the licence, not with the model output.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime

from a_share_platform.domain.disclosure import (
    DisclosureStatus,
    PublicationTimePrecision,
    RetentionPolicy,
)
from a_share_platform.domain.documents import (
    DocumentBodyDisposition,
    DocumentSourceClass,
    DocumentVersion,
    SourceAuthority,
    SourceLicenceProfile,
)

HASH = "sha256:" + "a" * 64
PUBLISHED = datetime(2026, 8, 13, 2, 20, tzinfo=UTC)
FETCHED = datetime(2026, 8, 13, 2, 40, tzinfo=UTC)
AVAILABLE = datetime(2026, 8, 13, 2, 20, tzinfo=UTC)


def licence(
    *,
    source_class: DocumentSourceClass = DocumentSourceClass.NEWS,
    body_storage_allowed: bool = False,
    retention: RetentionPolicy = RetentionPolicy.METADATA_ONLY,
    derived: RetentionPolicy = RetentionPolicy.METADATA_ONLY,
    retention_until: date | None = None,
) -> SourceLicenceProfile:
    return SourceLicenceProfile(
        licence_id="licence:news:example",
        source_class=source_class,
        authority=SourceAuthority.UNVERIFIED,
        body_storage_allowed=body_storage_allowed,
        redistribution_allowed=False,
        retention_policy=retention,
        retention_until=retention_until,
        derived_text_retention_policy=derived,
        registered_at=datetime(2026, 8, 16, tzinfo=UTC),
        registration_evidence_id="docs/14-data-source-catalog-and-agent-routing.md#news",
    )


def document(
    *,
    disposition: DocumentBodyDisposition = DocumentBodyDisposition.HASH_AND_REFERENCE_ONLY,
    raw_object_id: str | None = None,
    source_class: DocumentSourceClass = DocumentSourceClass.NEWS,
    authority: SourceAuthority = SourceAuthority.UNVERIFIED,
    sequence: int = 0,
    status: DisclosureStatus = DisclosureStatus.PUBLISHED,
    supersedes: str | None = None,
    reason: str | None = None,
    available_at: datetime = AVAILABLE,
    precision: PublicationTimePrecision = PublicationTimePrecision.EXACT,
) -> DocumentVersion:
    return DocumentVersion(
        document_version_id="document-version:news:example:1",
        document_key="news:example:2026-08-13:earnings-preview",
        external_document_id="example-9931",
        source_class=source_class,
        licence_id="licence:news:example",
        authority=authority,
        title="半年度业绩预告转述",
        language="zh-Hans",
        content_hash=HASH,
        canonical_url="https://news.example.com/9931",
        body_disposition=disposition,
        raw_object_id=raw_object_id,
        published_at=PUBLISHED,
        fetched_at=FETCHED,
        available_at=available_at,
        publication_time_precision=precision,
        version_sequence=sequence,
        status=status,
        supersedes_document_version_id=supersedes,
        status_reason=reason,
        company_ids=("company:CN:000858",),
        security_ids=("security:CN:000858:XSHE",),
    )


class BodyDispositionTest(unittest.TestCase):
    def test_hash_only_document_must_not_carry_a_raw_object(self) -> None:
        """A raw object id here would mean the body was stored after all."""
        with self.assertRaises(ValueError):
            document(
                disposition=DocumentBodyDisposition.HASH_AND_REFERENCE_ONLY,
                raw_object_id="raw:news:9931",
            )

    def test_stored_document_requires_a_raw_object(self) -> None:
        with self.assertRaises(ValueError):
            document(disposition=DocumentBodyDisposition.STORED, raw_object_id=None)

    def test_hash_is_required_even_when_the_body_is_not_kept(self) -> None:
        """Without a hash there is no way to prove two sources saw one text."""
        with self.assertRaises(ValueError):
            DocumentVersion(
                document_version_id="document-version:news:example:1",
                document_key="news:example:2026-08-13:earnings-preview",
                external_document_id="example-9931",
                source_class=DocumentSourceClass.NEWS,
                licence_id="licence:news:example",
                authority=SourceAuthority.UNVERIFIED,
                title="半年度业绩预告转述",
                language="zh-Hans",
                content_hash="",
                canonical_url="https://news.example.com/9931",
                body_disposition=DocumentBodyDisposition.HASH_AND_REFERENCE_ONLY,
                raw_object_id=None,
                published_at=PUBLISHED,
                fetched_at=FETCHED,
                available_at=AVAILABLE,
                publication_time_precision=PublicationTimePrecision.EXACT,
                version_sequence=0,
                status=DisclosureStatus.PUBLISHED,
                supersedes_document_version_id=None,
                status_reason=None,
                company_ids=("company:CN:000858",),
                security_ids=("security:CN:000858:XSHE",),
            )

    def test_hash_must_be_the_sha256_prefixed_form(self) -> None:
        """Same regex as disclosure.RawObject: sha256:<64 lowercase hex>."""
        with self.assertRaises(ValueError):
            DocumentVersion(
                document_version_id="document-version:news:example:1",
                document_key="news:example:2026-08-13:earnings-preview",
                external_document_id="example-9931",
                source_class=DocumentSourceClass.NEWS,
                licence_id="licence:news:example",
                authority=SourceAuthority.UNVERIFIED,
                title="半年度业绩预告转述",
                language="zh-Hans",
                content_hash="a" * 64,
                canonical_url="https://news.example.com/9931",
                body_disposition=DocumentBodyDisposition.HASH_AND_REFERENCE_ONLY,
                raw_object_id=None,
                published_at=PUBLISHED,
                fetched_at=FETCHED,
                available_at=AVAILABLE,
                publication_time_precision=PublicationTimePrecision.EXACT,
                version_sequence=0,
                status=DisclosureStatus.PUBLISHED,
                supersedes_document_version_id=None,
                status_reason=None,
                company_ids=("company:CN:000858",),
                security_ids=("security:CN:000858:XSHE",),
            )


class TimeSemanticsTest(unittest.TestCase):
    def test_available_at_cannot_precede_published_at(self) -> None:
        """Mirrors OfficialDisclosure; a news item is not knowable before it exists."""
        with self.assertRaises(ValueError):
            document(available_at=datetime(2026, 8, 13, 1, 0, tzinfo=UTC))

    def test_naive_timestamps_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            DocumentVersion(
                document_version_id="document-version:news:example:1",
                document_key="news:example:2026-08-13:earnings-preview",
                external_document_id="example-9931",
                source_class=DocumentSourceClass.NEWS,
                licence_id="licence:news:example",
                authority=SourceAuthority.UNVERIFIED,
                title="半年度业绩预告转述",
                language="zh-Hans",
                content_hash=HASH,
                canonical_url="https://news.example.com/9931",
                body_disposition=DocumentBodyDisposition.HASH_AND_REFERENCE_ONLY,
                raw_object_id=None,
                published_at=datetime(2026, 8, 13, 2, 20),
                fetched_at=FETCHED,
                available_at=AVAILABLE,
                publication_time_precision=PublicationTimePrecision.EXACT,
                version_sequence=0,
                status=DisclosureStatus.PUBLISHED,
                supersedes_document_version_id=None,
                status_reason=None,
                company_ids=("company:CN:000858",),
                security_ids=("security:CN:000858:XSHE",),
            )

    def test_date_only_precision_refuses_a_fabricated_clock_time(self) -> None:
        with self.assertRaises(ValueError):
            document(precision=PublicationTimePrecision.DATE_ONLY)


class CorrectionChainTest(unittest.TestCase):
    def test_a_later_version_cannot_be_published(self) -> None:
        """ADR-0008 decision 4: a correction appends, it does not re-publish."""
        with self.assertRaises(ValueError):
            document(
                sequence=1,
                status=DisclosureStatus.PUBLISHED,
                supersedes="document-version:news:example:0",
                reason="retracted paragraph three",
            )

    def test_a_retraction_must_name_its_predecessor_and_reason(self) -> None:
        with self.assertRaises(ValueError):
            document(
                sequence=1,
                status=DisclosureStatus.WITHDRAWN,
                supersedes=None,
                reason="retracted",
            )

    def test_version_zero_cannot_supersede_anything(self) -> None:
        with self.assertRaises(ValueError):
            document(sequence=0, supersedes="document-version:news:example:0")


class AuthorityTest(unittest.TestCase):
    def test_authority_is_ordered_so_one_version_can_be_chosen(self) -> None:
        self.assertGreater(SourceAuthority.OFFICIAL, SourceAuthority.REGULATOR)
        self.assertGreater(SourceAuthority.REGULATOR, SourceAuthority.LICENSED_THIRD_PARTY)
        self.assertGreater(SourceAuthority.LICENSED_THIRD_PARTY, SourceAuthority.UNVERIFIED)

    def test_a_news_document_cannot_declare_official_authority(self) -> None:
        """Authority follows the source class, not the caller's preference."""
        with self.assertRaises(ValueError):
            document(
                source_class=DocumentSourceClass.NEWS,
                authority=SourceAuthority.OFFICIAL,
            )

    def test_version_hash_is_content_addressed(self) -> None:
        self.assertEqual(document().version_hash, document().version_hash)
        self.assertEqual(len(document().version_hash), 64)

    def test_a_different_content_hash_changes_the_version_hash(self) -> None:
        other = DocumentVersion(**{
            **{
                field: getattr(document(), field)
                for field in (
                    "document_version_id", "document_key", "external_document_id",
                    "source_class", "licence_id", "authority", "title", "language",
                    "canonical_url", "body_disposition", "raw_object_id",
                    "published_at", "fetched_at", "available_at",
                    "publication_time_precision", "version_sequence", "status",
                    "supersedes_document_version_id", "status_reason",
                    "company_ids", "security_ids",
                )
            },
            "content_hash": "sha256:" + "b" * 64,
        })
        self.assertNotEqual(document().version_hash, other.version_hash)


class DerivedRetentionTest(unittest.TestCase):
    def test_derived_retention_cannot_exceed_the_source_retention(self) -> None:
        """ADR-0008 decision 3, stated as a type rule.

        A source that only permits metadata cannot permit indefinite storage of an
        LLM restatement of the same text.  Letting the model launder the licence is
        the single easiest way to breach this ADR, so the profile refuses to exist.
        """
        with self.assertRaises(ValueError):
            licence(
                retention=RetentionPolicy.METADATA_ONLY,
                derived=RetentionPolicy.INDEFINITE,
            )

    def test_equal_retention_is_allowed(self) -> None:
        profile = licence(
            retention=RetentionPolicy.METADATA_ONLY,
            derived=RetentionPolicy.METADATA_ONLY,
        )
        self.assertEqual(profile.derived_text_retention_policy, RetentionPolicy.METADATA_ONLY)

    def test_until_date_retention_requires_a_date(self) -> None:
        """Same rule as RawObject: until_date without a date is not a policy."""
        with self.assertRaises(ValueError):
            licence(retention=RetentionPolicy.UNTIL_DATE, retention_until=None)

    def test_a_licence_forbidding_body_storage_cannot_produce_a_stored_document(
        self,
    ) -> None:
        profile = licence(body_storage_allowed=False)
        with self.assertRaises(PermissionError):
            profile.authorise_disposition(DocumentBodyDisposition.STORED)
```

- [ ] **Step 5: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_document_versions -v`

Expected: FAIL —— `a_share_platform.domain.documents` 不存在。把真实
`ModuleNotFoundError` 文本抄进 `docs/28-p8-events-agents-evidence.md`。

- [ ] **Step 6: 最小实现 `domain/documents.py`**

顺序：`DocumentSourceClass` → `SourceAuthority` → `DocumentBodyDisposition` →
`SourceLicenceProfile`（含 `authorise_disposition`）→ `DocumentVersion`。

复用 `disclosure.py` 的 `_SHA256`、`_text`、`_aware` 三个私有 helper 的**语义**
（不要 import 私有名；在 `documents.py` 里写同语义的等价校验，或先把它们提取到
一个共享的 `domain/_validation.py` 并单独提交那次重构）。

`source_class` → 允许的 `authority` 映射必须在领域层写死：

```text
OFFICIAL_DISCLOSURE   → {OFFICIAL}
REGULATOR_PUBLICATION → {REGULATOR}
NEWS                  → {LICENSED_THIRD_PARTY, UNVERIFIED}
SELL_SIDE_RESEARCH    → {LICENSED_THIRD_PARTY, UNVERIFIED}
COMMERCIAL_DATABASE   → {LICENSED_THIRD_PARTY, UNVERIFIED}
```

- [ ] **Step 7: 转绿**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_document_versions -v`
Expected: PASS

- [ ] **Step 8: `application/document_ledger.py` —— 三条互斥路径**

```python
# platform/tests/test_document_ledger.py
"""Registering a document through the path its licence permits.

There are three paths and the licence picks which one is legal: store the body,
keep hash and reference only, or keep a short-lived cache.  The ledger refuses to
be talked into the wrong one, because the alternative is a caller passing
retention_policy by hand and getting it wrong once.
"""

from __future__ import annotations

import hashlib
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from a_share_platform.adapters.object_store.local import LocalRawObjectStore
from a_share_platform.application.document_ledger import DocumentLedger
from a_share_platform.domain.disclosure import RetentionPolicy
from a_share_platform.domain.documents import (
    DocumentBodyDisposition,
    DocumentSourceClass,
    SourceAuthority,
)

BODY = "巨潮公告全文".encode()


class LicenceDrivenPathTest(unittest.TestCase):
    def test_a_metadata_only_licence_stores_no_bytes_but_records_the_hash(self) -> None:
        with TemporaryDirectory() as root:
            store = LocalRawObjectStore(Path(root))
            ledger = DocumentLedger(_repository(), store, _licences())
            version = ledger.register(
                licence_id="licence:news:example",
                document_key="news:example:2026-08-13:earnings-preview",
                external_document_id="example-9931",
                title="半年度业绩预告转述",
                language="zh-Hans",
                canonical_url="https://news.example.com/9931",
                body=BODY,
                published_at=datetime(2026, 8, 13, 2, 20, tzinfo=UTC),
                fetched_at=datetime(2026, 8, 13, 2, 40, tzinfo=UTC),
                available_at=datetime(2026, 8, 13, 2, 20, tzinfo=UTC),
                company_ids=("company:CN:000858",),
                security_ids=("security:CN:000858:XSHE",),
            )
            self.assertEqual(
                version.body_disposition,
                DocumentBodyDisposition.HASH_AND_REFERENCE_ONLY,
            )
            self.assertIsNone(version.raw_object_id)
            self.assertEqual(
                version.content_hash,
                "sha256:" + hashlib.sha256(BODY).hexdigest(),
            )
            # The decisive assertion: nothing landed on disk.
            self.assertEqual(list(Path(root).rglob("*")), [])

    def test_an_official_licence_stores_the_body_and_links_the_raw_object(self) -> None:
        ...

    def test_the_caller_cannot_override_the_disposition(self) -> None:
        """Passing a disposition would move the decision out of the licence."""
        ...

    def test_registering_the_same_body_twice_is_idempotent(self) -> None:
        """Same hash, same content: one object, one version, no conflict."""
        ...

    def test_the_same_document_key_with_different_content_appends_a_version(self) -> None:
        ...

    def test_an_unregistered_licence_id_is_refused_before_any_fetch(self) -> None:
        """ADR-0008 result clause: unregistered source fails closed."""
        ...
```

补全 `...` 的断言时，用真实的 `LocalRawObjectStore` 与内存 repository，**不要联网**。

- [ ] **Step 9: migration `0039`**

三张表进 `evidence` schema（与 `raw_objects` / `official_disclosures` 同层）：
`evidence.source_licence_profiles`、`evidence.document_versions`、
`evidence.document_version_lineage`。约束必须覆盖领域不变量：

```sql
-- 关键约束（照领域不变量写，不要只写 NOT NULL）
CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$')
CHECK (available_at >= published_at)
CHECK (version_sequence >= 0)
CHECK (
    (body_disposition = 'stored' AND raw_object_id IS NOT NULL)
    OR (body_disposition <> 'stored' AND raw_object_id IS NULL)
)
CHECK (
    (version_sequence = 0 AND status = 'published'
        AND supersedes_document_version_id IS NULL AND status_reason IS NULL)
    OR (version_sequence > 0 AND status IN ('corrected', 'withdrawn')
        AND supersedes_document_version_id IS NOT NULL
        AND btrim(status_reason) <> '')
)
```

外键 `raw_object_id → evidence.raw_objects(raw_object_id)`。
append-only：加一个 `BEFORE UPDATE OR DELETE` 触发器 raise，
照 `migrations/0032_governance_integrity.sql` 的既有模式。

- [ ] **Step 10: 空库 + 幂等 migration smoke**

```bash
cd platform
ASP_DATABASE_URL=postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_layered_dev \
PYTHONPATH=src .venv/bin/python -m a_share_platform.adapters.postgres.cli
# 再跑一次，确认幂等
ASP_DATABASE_URL=... PYTHONPATH=src .venv/bin/python -m a_share_platform.adapters.postgres.cli
```

- [ ] **Step 11: 写 ADR-0014 与数据源目录**

`docs/adr/0014-event-source-licence-registry.md`：逐源列出 Step 1 的登记结论。
**状态由证据决定**：若只有官方披露一源通过，状态可为 `Accepted` 但适用范围只写官方源，
其余明确记为 `not_evaluated`；**不得把"框架已建"写成"来源已获批"**。

ADR 必须明确：一个源的 `registered` 结论**不隐含**允许 LLM 派生文本长期保存
（决策 3），那需要一条独立的 `derived_text_retention_policy` 登记。

- [ ] **Step 12: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
git diff --check
cd .. && git add platform/src/a_share_platform/domain/documents.py \
  platform/src/a_share_platform/ports/documents.py \
  platform/src/a_share_platform/application/document_ledger.py \
  platform/migrations/0039_p8_document_ledger.sql \
  platform/tests/test_document_versions.py \
  platform/tests/test_document_ledger.py \
  platform/tests/test_disclosure_ledger_regression.py \
  docs/adr/0014-event-source-licence-registry.md \
  docs/14-data-source-catalog-and-agent-routing.md \
  docs/28-p8-events-agents-evidence.md \
  docs/plans/step-07-p8-events-agents-supply-chain.md
git commit -m "feat: register event documents through the path their licence permits

The disclosure ledger already does the hard part for official announcements:
immutable raw objects with a sha256 hash, three timestamps, a version chain and a
retention policy, plus an object store that refuses symlink escapes and mismatched
content.  None of that is rebuilt here.

What was missing is the other half of ADR-0008 decision 2.  A news item or a piece
of sell-side research may arrive under a licence that forbids keeping the body, and
the existing capture path refuses METADATA_ONLY outright — correctly, because a
ledger that silently stores what it may not store is worse than one that fails.  So
this adds a parallel path where the licence, not the caller, decides between
storing the body, keeping hash and reference only, and a short-lived cache.  The
hash is mandatory in all three, because without it there is no way to prove later
that two sources were looking at the same text.

Decision 3 gets a field rather than a paragraph.  A source that permits only
metadata cannot permit indefinite retention of a model's restatement of the same
text, so derived_text_retention_policy may not exceed the source policy and the
profile refuses to exist otherwise.  Laundering a licence through a summariser is
the easiest way to breach this ADR and the hardest to notice afterwards.

Authority follows the source class instead of the caller: a news document cannot
declare itself official.  That ordering is what lets the next task pick one
authoritative version of an event without guessing.

A regression file guards the contracts that already worked, including the four
correction-chain invariants and the date_only rule that stops a date being dressed
up as a pre-open timestamp.  It passes on the first run, which is the point: the
next change to disclosure.py has to prove it did not weaken them."
```

---

### Task 2: 实体链接与去重（`domain/events.py`）

对应 Step 07 Task 2：「新增 `domain/events.py`、entity linker/deduper ports 和
deterministic baseline；真实小样本用公告/新闻重复、冲突和更正案例。」

**本 Task 是整个 plan 里最容易造成静默数据丢失的一步**，所以它的测试比实现长。

**Files:**
- Create: `platform/src/a_share_platform/domain/events.py`
- Create: `platform/src/a_share_platform/ports/events.py`
- Create: `platform/src/a_share_platform/application/event_pipeline.py`
- Create: `platform/src/a_share_platform/adapters/memory/events.py`
- Create: `platform/migrations/0040_p8_event_ledger.sql`
- Test: `platform/tests/test_event_contracts.py`
- Test: `platform/tests/test_event_dedup.py`
- Test: `platform/tests/test_entity_linking.py`
- Test: `platform/tests/test_event_pipeline.py`

**Interfaces:**
- Consumes: Task 1 的 `DocumentVersion` / `SourceAuthority`、已有
  `domain/security_master.py` 的身份解析、`domain/run_context.py`
- Produces:
  ```python
  class EventTaxonomyVersion(StrEnum):
      V0 = "event-taxonomy:v0"          # Step 07 决策：adapter 前冻结 version 0

  class EventCategory(StrEnum):
      """Frozen taxonomy v0.  Prototype shows 公告/业绩/供应链/政策."""
      ANNOUNCEMENT = "announcement"
      EARNINGS = "earnings"
      SUPPLY_CHAIN = "supply_chain"
      POLICY = "policy"
      GOVERNANCE = "governance"
      CAPITAL_ACTION = "capital_action"
      OTHER = "other"

  class EntityLinkStatus(StrEnum):
      RESOLVED = "resolved"
      AMBIGUOUS = "ambiguous"
      UNRESOLVED = "unresolved"

  class DedupeVerdict(StrEnum):
      UNIQUE = "unique"
      DUPLICATE_OF = "duplicate_of"
      CONFLICT = "conflict"          # 同权威等级的两个候选，不许任意挑一个

  @dataclass(frozen=True)
  class EntityLink:
      mention_text: str
      mention_offset: int
      status: EntityLinkStatus
      company_id: str | None
      security_id: str | None
      candidate_ids: tuple[str, ...]
      resolver_version: str
      status_reason: str | None

  @dataclass(frozen=True)
  class EventCluster:
      event_id: str
      taxonomy_version: EventTaxonomyVersion
      category: EventCategory
      occurred_at: datetime               # 事件本身的时间
      first_available_at: datetime         # 权威版本的市场可用时间
      first_tradable_at: datetime
      authoritative_document_version_id: str
      authoritative_authority: SourceAuthority
      duplicate_document_version_ids: tuple[str, ...]
      duplicate_divergences: tuple[DuplicateDivergence, ...]
      selection_rule_version: str
      selection_reason: str
      entity_links: tuple[EntityLink, ...]
      status: EventClusterStatus          # active / superseded / retracted
      supersedes_event_id: str | None
      status_reason: str | None
      content_hash: str = field(init=False)

  @dataclass(frozen=True)
  class DuplicateDivergence:
      document_version_id: str
      field_name: str                     # "available_at" / "title" / "amount" ...
      authoritative_value: str
      duplicate_value: str
      material: bool
  ```

- [ ] **Step 1: 先冻结 taxonomy v0，再写代码**

Step 07 决策原文：「第一事件 taxonomy 需要在 adapter 前冻结 version 0。」

在 `docs/28-p8-events-agents-evidence.md` 写一节，逐类别定义：判定依据、
所需最小字段、以及"不属于本类"的反例。原型画的四类
（`公告` `业绩` `供应链` `政策`）是**显示标签**，不是完整 taxonomy —— 至少还需要
治理类（增减持、诉讼、高管变动）与资本行动类（回购、定增、分红），
原型第三行 `回购方案` 恰好被标成 `供应链` 类，那是 design fixture 的不一致，
**不要照抄成 taxonomy**。

冻结的含义是：v0 之后新增类别必须是 v1，且已有 `EventCluster` 不重新分类。

- [ ] **Step 2: 写实体链接红测 —— 歧义不是解析**

```python
# platform/tests/test_entity_linking.py
"""Linking a text mention to a governed identity.

The failure that matters is not "no match" but "one plausible match chosen from
several".  Shenzhen recycles delisted codes and companies rename — 中航电测 300114
became 中航成飞 302132 in 2025 — so a mention that matches two identities is
ambiguous, and ambiguous must stay ambiguous rather than becoming the first
candidate.
"""

from __future__ import annotations

import unittest

from a_share_platform.domain.events import EntityLink, EntityLinkStatus


class AmbiguityTest(unittest.TestCase):
    def test_ambiguous_link_carries_every_candidate_and_no_chosen_identity(self) -> None:
        link = EntityLink(
            mention_text="中航电测",
            mention_offset=42,
            status=EntityLinkStatus.AMBIGUOUS,
            company_id=None,
            security_id=None,
            candidate_ids=("company:CN:300114", "company:CN:302132"),
            resolver_version="entity-resolver:v0",
            status_reason="one legal name maps to two listed codes across a rename",
        )
        self.assertIsNone(link.company_id)
        self.assertEqual(len(link.candidate_ids), 2)

    def test_ambiguous_link_cannot_also_name_a_resolved_identity(self) -> None:
        """Filling company_id here is exactly the silent wrong answer."""
        with self.assertRaises(ValueError):
            EntityLink(
                mention_text="中航电测",
                mention_offset=42,
                status=EntityLinkStatus.AMBIGUOUS,
                company_id="company:CN:300114",
                security_id=None,
                candidate_ids=("company:CN:300114", "company:CN:302132"),
                resolver_version="entity-resolver:v0",
                status_reason="ambiguous",
            )

    def test_resolved_link_requires_exactly_one_candidate(self) -> None:
        with self.assertRaises(ValueError):
            EntityLink(
                mention_text="五粮液",
                mention_offset=0,
                status=EntityLinkStatus.RESOLVED,
                company_id="company:CN:000858",
                security_id="security:CN:000858:XSHE",
                candidate_ids=("company:CN:000858", "company:CN:000859"),
                resolver_version="entity-resolver:v0",
                status_reason=None,
            )

    def test_resolved_link_requires_an_identity(self) -> None:
        with self.assertRaises(ValueError):
            EntityLink(
                mention_text="五粮液",
                mention_offset=0,
                status=EntityLinkStatus.RESOLVED,
                company_id=None,
                security_id=None,
                candidate_ids=("company:CN:000858",),
                resolver_version="entity-resolver:v0",
                status_reason=None,
            )

    def test_unresolved_link_requires_a_reason(self) -> None:
        with self.assertRaises(ValueError):
            EntityLink(
                mention_text="某家白酒龙头",
                mention_offset=7,
                status=EntityLinkStatus.UNRESOLVED,
                company_id=None,
                security_id=None,
                candidate_ids=(),
                resolver_version="entity-resolver:v0",
                status_reason=None,
            )

    def test_a_concept_mention_does_not_resolve_to_a_company(self) -> None:
        """"白酒板块" is a sector, not an issuer; resolving it invents a subject."""
        link = EntityLink(
            mention_text="白酒板块",
            mention_offset=3,
            status=EntityLinkStatus.UNRESOLVED,
            company_id=None,
            security_id=None,
            candidate_ids=(),
            resolver_version="entity-resolver:v0",
            status_reason="sector mention is not a single issuer",
        )
        self.assertEqual(link.status, EntityLinkStatus.UNRESOLVED)

    def test_offset_must_be_non_negative(self) -> None:
        """The offset is what makes a citation checkable against the body."""
        with self.assertRaises(ValueError):
            EntityLink(
                mention_text="五粮液",
                mention_offset=-1,
                status=EntityLinkStatus.RESOLVED,
                company_id="company:CN:000858",
                security_id="security:CN:000858:XSHE",
                candidate_ids=("company:CN:000858",),
                resolver_version="entity-resolver:v0",
                status_reason=None,
            )
```

- [ ] **Step 3: 写去重红测 —— 本 plan 最重要的一组测试**

```python
# platform/tests/test_event_dedup.py
"""Deduplication that keeps the authoritative version and records the duplicate.

The same earnings preview arrives twice: once from cninfo as an official PDF with
an exact available_at, and once from a news source that paraphrases it, publishes
40 minutes later, and carries date-only precision.  Three ways to get this wrong:

1. keep whichever arrived first, so the news timestamp becomes the event time and
   the event moves 40 minutes later than it really was knowable;
2. treat the paraphrase as a separate event, so the cross-section gains two highly
   correlated observations and the event count inflates;
3. merge them and drop the loser without a record, so nobody can ever find the
   mistake.

The deduper therefore never returns a single merged document.  It returns one
authoritative id, every duplicate id, and the material divergences between them.
When two candidates have equal authority it returns CONFLICT rather than picking —
"pick one arbitrarily" is the hardest kind of data loss to diagnose later.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from a_share_platform.domain.documents import SourceAuthority
from a_share_platform.domain.events import (
    DedupeVerdict,
    EventCategory,
    EventTaxonomyVersion,
    deduplicate_documents,
)


def candidate(
    *,
    document_version_id: str,
    authority: SourceAuthority,
    available_at: datetime,
    title: str = "五粮液2026年半年度业绩预告",
    content_hash: str = "sha256:" + "a" * 64,
):
    from a_share_platform.domain.events import DedupeCandidate

    return DedupeCandidate(
        document_version_id=document_version_id,
        authority=authority,
        available_at=available_at,
        title=title,
        content_hash=content_hash,
        company_ids=("company:CN:000858",),
        category=EventCategory.EARNINGS,
    )


OFFICIAL = candidate(
    document_version_id="document-version:cninfo:000858:preview:0",
    authority=SourceAuthority.OFFICIAL,
    available_at=datetime(2026, 7, 14, 1, 15, tzinfo=UTC),
)
NEWS = candidate(
    document_version_id="document-version:news:example:0",
    authority=SourceAuthority.UNVERIFIED,
    available_at=datetime(2026, 7, 14, 1, 55, tzinfo=UTC),
    title="五粮液上半年业绩预告出炉",
    content_hash="sha256:" + "b" * 64,
)


class AuthoritativeSelectionTest(unittest.TestCase):
    def test_the_official_version_wins_regardless_of_arrival_order(self) -> None:
        for ordering in ((OFFICIAL, NEWS), (NEWS, OFFICIAL)):
            with self.subTest(ordering=[item.document_version_id for item in ordering]):
                result = deduplicate_documents(
                    ordering,
                    taxonomy_version=EventTaxonomyVersion.V0,
                    selection_rule_version="dedupe-rule:v0",
                )
                self.assertEqual(result.verdict, DedupeVerdict.DUPLICATE_OF)
                self.assertEqual(
                    result.authoritative_document_version_id,
                    OFFICIAL.document_version_id,
                )

    def test_the_duplicate_is_recorded_not_dropped(self) -> None:
        result = deduplicate_documents(
            (OFFICIAL, NEWS),
            taxonomy_version=EventTaxonomyVersion.V0,
            selection_rule_version="dedupe-rule:v0",
        )
        self.assertEqual(
            result.duplicate_document_version_ids,
            (NEWS.document_version_id,),
        )

    def test_the_event_time_comes_from_the_authoritative_version(self) -> None:
        """40 minutes of look-ahead is enough to change an event study result."""
        result = deduplicate_documents(
            (NEWS, OFFICIAL),
            taxonomy_version=EventTaxonomyVersion.V0,
            selection_rule_version="dedupe-rule:v0",
        )
        self.assertEqual(result.first_available_at, OFFICIAL.available_at)

    def test_a_material_timestamp_divergence_is_listed(self) -> None:
        result = deduplicate_documents(
            (OFFICIAL, NEWS),
            taxonomy_version=EventTaxonomyVersion.V0,
            selection_rule_version="dedupe-rule:v0",
        )
        divergences = {item.field_name: item for item in result.duplicate_divergences}
        self.assertIn("available_at", divergences)
        self.assertTrue(divergences["available_at"].material)

    def test_a_wording_difference_is_listed_as_immaterial(self) -> None:
        result = deduplicate_documents(
            (OFFICIAL, NEWS),
            taxonomy_version=EventTaxonomyVersion.V0,
            selection_rule_version="dedupe-rule:v0",
        )
        divergences = {item.field_name: item for item in result.duplicate_divergences}
        self.assertIn("title", divergences)
        self.assertFalse(divergences["title"].material)

    def test_the_selection_reason_names_the_rule_that_decided(self) -> None:
        result = deduplicate_documents(
            (OFFICIAL, NEWS),
            taxonomy_version=EventTaxonomyVersion.V0,
            selection_rule_version="dedupe-rule:v0",
        )
        self.assertIn("authority", result.selection_reason.lower())
        self.assertEqual(result.selection_rule_version, "dedupe-rule:v0")


class EqualAuthorityConflictTest(unittest.TestCase):
    def test_two_equally_authoritative_candidates_produce_a_conflict(self) -> None:
        """Picking by timestamp or id order here loses one version silently."""
        other_news = candidate(
            document_version_id="document-version:news:other:0",
            authority=SourceAuthority.UNVERIFIED,
            available_at=datetime(2026, 7, 14, 1, 56, tzinfo=UTC),
            title="五粮液业绩预告",
            content_hash="sha256:" + "c" * 64,
        )
        result = deduplicate_documents(
            (NEWS, other_news),
            taxonomy_version=EventTaxonomyVersion.V0,
            selection_rule_version="dedupe-rule:v0",
        )
        self.assertEqual(result.verdict, DedupeVerdict.CONFLICT)
        self.assertIsNone(result.authoritative_document_version_id)
        self.assertIsNotNone(result.conflict_reason)

    def test_a_conflict_still_lists_every_candidate(self) -> None:
        """A conflict that forgets its inputs cannot be resolved by a human."""
        ...

    def test_a_conflict_does_not_produce_an_event_cluster(self) -> None:
        """An unresolved conflict must not silently become one event."""
        ...


class NoSilentLossTest(unittest.TestCase):
    def test_every_input_appears_either_as_authoritative_or_as_duplicate(self) -> None:
        """The invariant that makes silent loss impossible by construction."""
        candidates = (OFFICIAL, NEWS, candidate(
            document_version_id="document-version:news:third:0",
            authority=SourceAuthority.LICENSED_THIRD_PARTY,
            available_at=datetime(2026, 7, 14, 2, 5, tzinfo=UTC),
            content_hash="sha256:" + "d" * 64,
        ))
        result = deduplicate_documents(
            candidates,
            taxonomy_version=EventTaxonomyVersion.V0,
            selection_rule_version="dedupe-rule:v0",
        )
        accounted = {result.authoritative_document_version_id,
                     *result.duplicate_document_version_ids}
        self.assertEqual(
            accounted,
            {item.document_version_id for item in candidates},
        )

    def test_identical_content_hash_is_the_same_document_not_a_duplicate_event(
        self,
    ) -> None:
        """Two fetches of one URL are one document version, not two."""
        ...

    def test_a_single_candidate_is_unique_not_a_duplicate_of_itself(self) -> None:
        result = deduplicate_documents(
            (OFFICIAL,),
            taxonomy_version=EventTaxonomyVersion.V0,
            selection_rule_version="dedupe-rule:v0",
        )
        self.assertEqual(result.verdict, DedupeVerdict.UNIQUE)
        self.assertEqual(result.duplicate_document_version_ids, ())

    def test_an_empty_candidate_set_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            deduplicate_documents(
                (),
                taxonomy_version=EventTaxonomyVersion.V0,
                selection_rule_version="dedupe-rule:v0",
            )

    def test_dedupe_is_deterministic_under_input_permutation(self) -> None:
        """A non-deterministic deduper makes every downstream hash unstable."""
        ...
```

- [ ] **Step 4: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_entity_linking tests.test_event_dedup -v`
Expected: FAIL —— `a_share_platform.domain.events` 不存在。

- [ ] **Step 5: 实现 `EntityLink` → `DedupeCandidate` → `deduplicate_documents`**

`deduplicate_documents` 必须是**纯函数**，不查库、不调 provider、不用 LLM。
第一版判定重复的规则只允许用确定性信号（Step 07 原文：「deterministic baseline」）：

```text
同一 company_ids 集合 + 同一 category + available_at 相差 <= 阈值（配置，非常量）
+ 标题归一化后的 token Jaccard >= 阈值
```

两个阈值都必须来自 `selection_rule_version` 绑定的参数对象，**不许写死在函数里** ——
改阈值必须改版本号，否则两次运行的结果无法区分。

**语义相似度、embedding、LLM 判重全部不在本 Task。** 它们需要 Task 3 的
Agent 治理边界，且必须作为**候选提示**而非判定，见 Task 3 Step 9。

- [ ] **Step 6: 转绿，再补 `EventCluster` 合同测试**

```python
# platform/tests/test_event_contracts.py（节选）
class EventClusterContractTest(unittest.TestCase):
    def test_first_available_at_cannot_precede_occurred_at(self) -> None:
        ...

    def test_first_tradable_at_cannot_precede_first_available_at(self) -> None:
        """Mirrors OfficialDisclosure so event windows cannot start early."""
        ...

    def test_a_cluster_with_an_ambiguous_entity_link_is_not_security_scoped(self) -> None:
        """An ambiguous subject cannot produce a security-level impact."""
        ...

    def test_content_hash_covers_the_duplicate_list(self) -> None:
        """Otherwise two clusters that discarded different versions look identical."""
        ...

    def test_taxonomy_version_is_part_of_the_hash(self) -> None:
        ...

    def test_a_retracted_cluster_keeps_its_documents_readable(self) -> None:
        """Retraction changes status; it does not erase what we believed."""
        ...
```

- [ ] **Step 7: `application/event_pipeline.py` 与 ports**

```python
# ports/events.py
class EntityResolver(Protocol):
    def resolve(self, *, text: str, as_of: datetime) -> tuple[EntityLink, ...]: ...

class EventRepository(Protocol):
    def register_cluster(self, value: EventCluster) -> EventCluster: ...
    def get_cluster(self, event_id: str) -> EventCluster | None: ...
    def clusters_for_document(self, document_version_id: str) -> tuple[EventCluster, ...]: ...
    def list_conflicts(self) -> tuple[DedupeConflict, ...]: ...
```

`event_pipeline.py` 只做编排：读 `DocumentVersion` → 调 `EntityResolver` →
调纯函数 `deduplicate_documents` → 写 `EventRepository`。
**编排层不做任何判定** —— 与 P-2 的 `FactorFeatureOrchestrator` 同一纪律。

pipeline 测试至少覆盖：
- `CONFLICT` 时不写 cluster，而是写一条 conflict 记录并返回 blocker；
- 同一份 document 重复处理是幂等的（同 `event_id`）；
- 任一 `EntityLink` 为 `AMBIGUOUS` 时 cluster 仍然生成，但不带 `security_ids`。

- [ ] **Step 8: migration `0040` 与真实小样本回放**

四张表进 `evidence`：`event_clusters`、`event_cluster_documents`、
`event_dedupe_conflicts`、`event_entity_links`。append-only 触发器同 Task 1。

用 P3-W04c 的真实 8 份 PDF 跑一次 pipeline dry-run：

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.event_pipeline \
  --taxonomy-version event-taxonomy:v0 --document-source cninfo
```

Expected: 8 份文档产出若干 cluster，其中五粮液与立华股份各有一条修订链
（`version_sequence` 0 与 1）。**真实结果里 `duplicate_document_version_ids`
很可能全部为空**，因为当前只有一个来源 —— 如实记录，
这正是 Task 1 Step 1 的许可登记结论的直接后果。

- [ ] **Step 9: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
git diff --check
cd .. && git add platform/src/a_share_platform/domain/events.py \
  platform/src/a_share_platform/ports/events.py \
  platform/src/a_share_platform/application/event_pipeline.py \
  platform/src/a_share_platform/adapters/memory/events.py \
  platform/migrations/0040_p8_event_ledger.sql \
  platform/tests/test_event_contracts.py \
  platform/tests/test_event_dedup.py \
  platform/tests/test_entity_linking.py \
  platform/tests/test_event_pipeline.py \
  docs/28-p8-events-agents-evidence.md
git commit -m "feat: deduplicate events by keeping the authoritative version and recording the rest

Deduplication is where this pipeline loses data silently, so it is built to make
that impossible rather than unlikely.  The same earnings preview arrives from
cninfo as an official filing with an exact availability time and from a news source
as a paraphrase forty minutes later with date-only precision.  Keeping whichever
landed first moves the event forty minutes into the future; treating the paraphrase
as its own event adds a second, near-perfectly correlated observation to the
cross-section; merging them and discarding the loser leaves no trace of either
mistake.

So the deduper never returns one merged document.  It returns the authoritative id,
every duplicate id, and the field-level divergences between them marked material or
not — a differing available_at is material, differing wording is not.  An invariant
test asserts every input appears either as the authoritative version or as a
recorded duplicate, which is what makes silent loss structurally impossible rather
than merely discouraged.

When two candidates carry equal authority the verdict is CONFLICT and no cluster is
written.  Breaking the tie by timestamp or by identifier order would be the worst
outcome available: it looks like a decision, it is reproducible, and it is wrong in
a way nobody will ever notice.

Entity links keep the same discipline one level down.  Ambiguous stays ambiguous
with every candidate listed and no identity chosen, because 中航电测 300114 became
中航成飞 302132 and Shenzhen reuses delisted codes, so one name really can mean two
issuers.  A sector mention resolves to nothing at all rather than to a
representative member.

Thresholds live in the versioned selection rule, not in the function.  Changing
what counts as a duplicate changes the rule version, so two runs under different
thresholds can never be mistaken for each other."
```

---

### Task 3: 受治理 Agent 运行时（先 fake model port，不接真 provider）

对应 Step 07 Task 3：「新增 `domain/agent_research.py`、`application/agent_runtime.py`、
model/tool ports 和 audit repository；先 fake adapters 测 allowlist、预算、timeout、
schema/citation，再接批准 provider。」

**「再接批准 provider」是一个决策门，不是一个后续步骤。** LLM provider 的选择涉及
成本（按 token 计费，事件抽取是高 token 场景）与许可（把不可保存的正文送进第三方模型，
本身可能违反来源条款）。两者都是用户决策。本 Task 完成后，平台**有能力**接 provider，
但**没有接**，且 `ports/agent_model.py` 的唯一实现是 `FakeAgentModel`。

**Files:**
- Create: `platform/src/a_share_platform/domain/agent_research.py`
- Create: `platform/src/a_share_platform/ports/agent_model.py`
- Create: `platform/src/a_share_platform/ports/agent_tools.py`
- Create: `platform/src/a_share_platform/application/agent_runtime.py`
- Create: `platform/src/a_share_platform/adapters/memory/agent_model.py`（`FakeAgentModel`）
- Create: `platform/migrations/0041_p8_agent_audit.sql`
- Test: `platform/tests/test_agent_claim_contracts.py`
- Test: `platform/tests/test_agent_authority_boundary.py`
- Test: `platform/tests/test_agent_runtime.py`
- Test: `platform/tests/test_agent_citations.py`

**Interfaces:**
- Consumes: Task 1 的 `DocumentVersion` / `SourceLicenceProfile`、Task 2 的 `EventCluster`、
  已有 `application/permissions.py` 的 `Role` / `Permission` / `PermissionPolicy` / `Principal`
- Produces:
  ```python
  class AgentClaimKind(StrEnum):
      FACT = "fact"
      INFERENCE = "inference"
      OPINION = "opinion"
      RUMOR = "rumor"

  # 治理字段黑名单：这些语义永远不能由 Agent 断言为 FACT。
  GOVERNED_FIELD_DENY_LIST: frozenset[str] = frozenset({
      "price", "close", "open", "vwap",
      "financial_value", "operating_revenue", "net_profit", "eps",
      "published_at", "available_at", "first_tradable_at",
      "trade_result", "fill_price", "position", "weight",
  })

  @dataclass(frozen=True)
  class Citation:
      document_version_id: str
      char_start: int
      char_end: int                 # > char_start
      quoted_hash: str              # 被引区间的 sha256，不保存正文
      licence_id: str

  @dataclass(frozen=True)
  class AgentClaim:
      claim_id: str
      event_id: str
      claim_kind: AgentClaimKind
      field_id: str | None          # FACT 必填；用于黑名单检查
      subject_company_id: str | None
      statement: str
      citations: tuple[Citation, ...]     # 不得为空
      confidence: Decimal | None          # FACT 不允许携带 confidence
      conflicts_with_claim_ids: tuple[str, ...]
      derived_retention_ceiling: RetentionPolicy   # ADR-0008 决策 3
      agent_run_id: str
      content_hash: str = field(init=False)

  @dataclass(frozen=True)
  class AgentRunBudget:
      max_input_tokens: int
      max_output_tokens: int
      max_tool_calls: int
      wall_clock_deadline_seconds: int
      max_retries: int

  @dataclass(frozen=True)
  class AgentRunRecord:
      """Append-only audit row.  It never grants write or approval authority."""
      agent_run_id: str
      principal_subject_id: str
      model_provider_id: str
      model_version_id: str
      prompt_template_id: str
      prompt_template_hash: str
      tool_allowlist: tuple[str, ...]        # deny-by-default
      budget: AgentRunBudget
      input_document_version_ids: tuple[str, ...]
      raw_response_hash: str
      parser_version: str
      status: AgentRunStatus                  # succeeded / schema_invalid /
                                              # citation_invalid / budget_exceeded /
                                              # deadline_exceeded / tool_denied / failed
      quarantined_output_hash: str | None
      status_reason: str | None
      run_context: RunContext
      started_at: datetime
      finished_at: datetime
      content_hash: str = field(init=False)
  ```

- [ ] **Step 1: 先读真实权限策略，确认 `Role.AGENT` 的授权集**

```bash
cd platform
grep -n "Role.AGENT" -B4 -A2 src/a_share_platform/application/permissions.py
grep -n "def allows" -A8 src/a_share_platform/application/permissions.py
```

Expected: `Role.AGENT: read`，其中 `read = frozenset({Permission.READ_PUBLIC})`。
注意 `allows()` 对 `subject_id == "anonymous"` 有一条特判：只允许 `READ_PUBLIC`。
Agent 不是 anonymous，但授权集恰好也只有 `READ_PUBLIC` —— **连 `READ_ARTIFACT` 都没有**。

**本 plan 不修改 `permissions.py`。** 下一步的测试把这个事实钉死。

- [ ] **Step 2: 写权限边界红测 —— Agent 永远不能写、不能批、不能下单**

```python
# platform/tests/test_agent_authority_boundary.py
"""The agent's authority, asserted permission by permission.

Role.AGENT already holds only READ_PUBLIC in the default policy.  This file exists
so that widening it fails a test rather than passing review.  An agent that can
write is an agent that can promote a trust state; an agent that can approve is an
agent that can approve its own output; an agent that can send an order needs no
further description.
"""

from __future__ import annotations

import unittest

from a_share_platform.application.permissions import (
    Permission,
    PermissionPolicy,
    Principal,
    Role,
)

AGENT = Principal("agent:event-extractor:v0", frozenset({Role.AGENT}))
POLICY = PermissionPolicy.default()


class AgentPermissionTest(unittest.TestCase):
    def test_agent_may_read_public(self) -> None:
        self.assertTrue(POLICY.allows(AGENT, Permission.READ_PUBLIC))

    def test_agent_may_not_read_artifacts(self) -> None:
        """Frozen artifacts are the governed output; the agent is upstream of them."""
        self.assertFalse(POLICY.allows(AGENT, Permission.READ_ARTIFACT))

    def test_agent_may_not_create_experiments(self) -> None:
        self.assertFalse(POLICY.allows(AGENT, Permission.CREATE_EXPERIMENT))

    def test_agent_may_not_manage_data(self) -> None:
        self.assertFalse(POLICY.allows(AGENT, Permission.MANAGE_DATA))

    def test_agent_may_not_approve_research(self) -> None:
        self.assertFalse(POLICY.allows(AGENT, Permission.APPROVE_RESEARCH))

    def test_agent_may_not_approve_portfolio(self) -> None:
        self.assertFalse(POLICY.allows(AGENT, Permission.APPROVE_PORTFOLIO))

    def test_agent_may_not_send_orders(self) -> None:
        self.assertFalse(POLICY.allows(AGENT, Permission.SEND_ORDER))

    def test_agent_may_not_administer(self) -> None:
        self.assertFalse(POLICY.allows(AGENT, Permission.ADMINISTER))

    def test_the_agent_grant_set_has_exactly_one_permission(self) -> None:
        """A count assertion catches an addition that the list above would miss."""
        self.assertEqual(POLICY.grants[Role.AGENT], frozenset({Permission.READ_PUBLIC}))

    def test_combining_agent_with_another_role_is_the_other_role_s_decision(self) -> None:
        """A human reviewer running an agent keeps their own authority, not the agent's."""
        reviewer_and_agent = Principal(
            "user:reviewer-1", frozenset({Role.REVIEWER, Role.AGENT})
        )
        self.assertTrue(POLICY.allows(reviewer_and_agent, Permission.APPROVE_RESEARCH))
        # But the agent run record must attribute the output to the agent identity,
        # not to the reviewer.  That is asserted in test_agent_runtime.py.
```

- [ ] **Step 3: 写 claim 合同红测 —— Agent 不能拥有治理数值**

```python
# platform/tests/test_agent_claim_contracts.py
"""What an agent may and may not assert.

SPEC-028 lists what the agent MAY do — extract entities, events, factual claims,
impact paths, propagation, horizons, confidence, counter-evidence and open
verification items — and what it MUST NOT: decide a financial value is true, modify
a publication or availability time, promote a trust state, produce production
weights or orders, or let an unsourced conclusion reach an InvestmentView.

Three of those five are enforced here, in the type.  A claim about a price, a
financial value, an announcement time or a trade result cannot be constructed as a
FACT at all, because the deny list is checked in __post_init__ rather than by a
reviewer reading the statement text.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from a_share_platform.domain.agent_research import (
    GOVERNED_FIELD_DENY_LIST,
    AgentClaim,
    AgentClaimKind,
    Citation,
)
from a_share_platform.domain.disclosure import RetentionPolicy

CITATION = Citation(
    document_version_id="document-version:cninfo:000858:preview:0",
    char_start=1204,
    char_end=1268,
    quoted_hash="sha256:" + "e" * 64,
    licence_id="licence:cninfo:official",
)


def claim(
    *,
    kind: AgentClaimKind = AgentClaimKind.INFERENCE,
    field_id: str | None = None,
    citations: tuple[Citation, ...] = (CITATION,),
    confidence: Decimal | None = Decimal("0.6"),
    ceiling: RetentionPolicy = RetentionPolicy.INDEFINITE,
) -> AgentClaim:
    return AgentClaim(
        claim_id="agent-claim:0001",
        event_id="event:000858:2026-07-14:earnings-preview",
        claim_kind=kind,
        field_id=field_id,
        subject_company_id="company:CN:000858",
        statement="预告区间的中值高于上一年同期，可能反映渠道补库",
        citations=citations,
        confidence=confidence,
        conflicts_with_claim_ids=(),
        derived_retention_ceiling=ceiling,
        agent_run_id="agent-run:0001",
    )


class DenyListTest(unittest.TestCase):
    def test_an_agent_cannot_assert_a_price_as_fact(self) -> None:
        with self.assertRaises(PermissionError):
            claim(kind=AgentClaimKind.FACT, field_id="price", confidence=None)

    def test_an_agent_cannot_assert_a_financial_value_as_fact(self) -> None:
        """The 五粮液 revenue restatement is exactly why: the number moved 2.16x."""
        with self.assertRaises(PermissionError):
            claim(
                kind=AgentClaimKind.FACT,
                field_id="operating_revenue",
                confidence=None,
            )

    def test_an_agent_cannot_assert_an_announcement_time_as_fact(self) -> None:
        with self.assertRaises(PermissionError):
            claim(kind=AgentClaimKind.FACT, field_id="available_at", confidence=None)

    def test_an_agent_cannot_assert_a_trade_result_as_fact(self) -> None:
        with self.assertRaises(PermissionError):
            claim(kind=AgentClaimKind.FACT, field_id="fill_price", confidence=None)

    def test_every_deny_listed_field_is_refused(self) -> None:
        """Loop the list so adding a field to it also adds coverage."""
        for field_id in sorted(GOVERNED_FIELD_DENY_LIST):
            with self.subTest(field_id=field_id):
                with self.assertRaises(PermissionError):
                    claim(
                        kind=AgentClaimKind.FACT,
                        field_id=field_id,
                        confidence=None,
                    )

    def test_the_same_field_may_be_discussed_as_an_inference(self) -> None:
        """The agent may reason about revenue; it may not certify a value."""
        value = claim(kind=AgentClaimKind.INFERENCE, field_id="operating_revenue")
        self.assertEqual(value.claim_kind, AgentClaimKind.INFERENCE)

    def test_a_fact_claim_requires_a_field_id(self) -> None:
        with self.assertRaises(ValueError):
            claim(kind=AgentClaimKind.FACT, field_id=None, confidence=None)

    def test_a_fact_claim_cannot_carry_confidence(self) -> None:
        """A fact with a probability attached is an inference wearing a costume."""
        with self.assertRaises(ValueError):
            claim(
                kind=AgentClaimKind.FACT,
                field_id="board_resolution_date",
                confidence=Decimal("0.9"),
            )

    def test_an_inference_requires_confidence(self) -> None:
        with self.assertRaises(ValueError):
            claim(kind=AgentClaimKind.INFERENCE, confidence=None)

    def test_a_rumor_cannot_claim_high_confidence(self) -> None:
        """A rumor at 0.95 confidence is the shape of a manufactured signal."""
        with self.assertRaises(ValueError):
            claim(kind=AgentClaimKind.RUMOR, confidence=Decimal("0.95"))


class CitationRequirementTest(unittest.TestCase):
    def test_a_claim_without_a_citation_cannot_exist(self) -> None:
        with self.assertRaises(ValueError):
            claim(citations=())

    def test_a_citation_range_must_be_non_empty(self) -> None:
        with self.assertRaises(ValueError):
            Citation(
                document_version_id="document-version:cninfo:000858:preview:0",
                char_start=1204,
                char_end=1204,
                quoted_hash="sha256:" + "e" * 64,
                licence_id="licence:cninfo:official",
            )

    def test_a_citation_stores_a_hash_rather_than_the_quoted_text(self) -> None:
        """Quoting the body of a no-store source would breach its licence."""
        self.assertFalse(hasattr(CITATION, "quoted_text"))
        self.assertTrue(CITATION.quoted_hash.startswith("sha256:"))

    def test_a_citation_carries_the_licence_of_the_document_it_points_at(self) -> None:
        self.assertEqual(CITATION.licence_id, "licence:cninfo:official")


class DerivedRetentionTest(unittest.TestCase):
    def test_a_claim_cannot_outlive_the_licence_of_its_citations(self) -> None:
        """ADR-0008 decision 3, at the claim level.

        "原文不可保存不等于可以让 LLM 复述后长期保存" — so a claim citing a
        metadata-only source cannot declare indefinite retention.  The ceiling is
        the minimum across every cited licence, and it is checked here rather than
        trusted to the caller.
        """
        metadata_only_citation = Citation(
            document_version_id="document-version:news:example:0",
            char_start=10,
            char_end=90,
            quoted_hash="sha256:" + "f" * 64,
            licence_id="licence:news:metadata-only",
        )
        with self.assertRaises(PermissionError):
            AgentClaim(
                claim_id="agent-claim:0002",
                event_id="event:000858:2026-07-14:earnings-preview",
                claim_kind=AgentClaimKind.INFERENCE,
                field_id=None,
                subject_company_id="company:CN:000858",
                statement="新闻称渠道库存下降",
                citations=(metadata_only_citation,),
                confidence=Decimal("0.4"),
                conflicts_with_claim_ids=(),
                derived_retention_ceiling=RetentionPolicy.INDEFINITE,
                agent_run_id="agent-run:0001",
            )

    def test_the_ceiling_is_the_minimum_across_mixed_citations(self) -> None:
        """One restricted source restricts the whole claim."""
        ...

    def test_content_hash_covers_the_citations(self) -> None:
        """Otherwise a claim could be re-pointed at a different source silently."""
        ...
```

`AgentClaim` 需要一个 licence 解析入口才能校验 ceiling。两种实现都可接受：
把 `licence_resolver: Mapping[str, RetentionPolicy]` 作为构造参数注入，
或在 application 层解析后由 domain 只校验"声明的 ceiling 不得比解析结果更宽"。
**必须有一个地方会因为 ceiling 过宽而抛错**；由实现者在 Step 5 选定并把选择写进 Evidence。

- [ ] **Step 4: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_agent_authority_boundary tests.test_agent_claim_contracts -v`

Expected: `test_agent_authority_boundary` **全绿**（守卫已实现行为）；
`test_agent_claim_contracts` 全红（`domain.agent_research` 不存在）。
两者的真实输出都抄进 Evidence —— 一个证明边界已在，一个证明合同待建。

- [ ] **Step 5: 实现 `domain/agent_research.py`**

顺序：`AgentClaimKind` → `GOVERNED_FIELD_DENY_LIST` → `Citation` →
`AgentClaim` → `AgentRunBudget` → `AgentRunStatus` → `AgentRunRecord`。

`AgentRunRecord.status` 必须能区分五种"没成功"：
`schema_invalid`（解析失败）、`citation_invalid`（引用指向不存在的文档或越界区间）、
`budget_exceeded`、`deadline_exceeded`、`tool_denied`。
**不许合并成一个 `failed`** —— 这五种对应五种不同的修法。

非 `succeeded` 的记录必须有 `status_reason`，且若有输出则必须有
`quarantined_output_hash`：隔离不是丢弃，输出要留着供人查，但不进入下游。

- [ ] **Step 6: 转绿，然后写 runtime 红测**

```python
# platform/tests/test_agent_runtime.py
"""Running an agent against a fake model, with deny-by-default tools.

No real provider is called anywhere in this plan.  The model port exists so that
budget, timeout, tool allowlist, schema validation and citation validation are all
proven against a deterministic fake before the question "which provider, at what
cost, under whose licence" is even asked — because that question is the user's, not
this plan's.
"""

from __future__ import annotations

import unittest

from a_share_platform.adapters.memory.agent_model import FakeAgentModel
from a_share_platform.application.agent_runtime import AgentRuntime
from a_share_platform.domain.agent_research import AgentRunBudget, AgentRunStatus
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext

CONTEXT = RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.RESEARCH)
BUDGET = AgentRunBudget(
    max_input_tokens=8000,
    max_output_tokens=2000,
    max_tool_calls=4,
    wall_clock_deadline_seconds=60,
    max_retries=1,
)


class ToolAllowlistTest(unittest.TestCase):
    def test_a_tool_outside_the_allowlist_is_denied(self) -> None:
        runtime = AgentRuntime(
            model=FakeAgentModel(tool_calls=("http_get",)),
            tool_allowlist=("read_document_version",),
            budget=BUDGET,
            run_context=CONTEXT,
        )
        record = runtime.run(
            prompt_template_id="prompt:event-extract:v0",
            document_version_ids=("document-version:cninfo:000858:preview:0",),
        )
        self.assertEqual(record.status, AgentRunStatus.TOOL_DENIED)
        self.assertIn("http_get", record.status_reason or "")

    def test_an_empty_allowlist_denies_every_tool(self) -> None:
        """Deny-by-default means the empty set is the safe default, not an error."""
        ...

    def test_network_access_is_not_a_tool_the_runtime_can_grant(self) -> None:
        """Fetching is the ingestion path's job, under a registered licence."""
        ...


class BudgetTest(unittest.TestCase):
    def test_exceeding_the_tool_call_budget_stops_the_run(self) -> None:
        ...

    def test_exceeding_the_deadline_records_deadline_exceeded_not_failed(self) -> None:
        """Different reasons need different fixes, so they need different statuses."""
        ...

    def test_a_budget_of_zero_retries_does_not_retry(self) -> None:
        ...

    def test_the_budget_is_recorded_on_the_run_even_when_unused(self) -> None:
        """Reproducing a run needs the limits it ran under, not just its output."""
        ...


class SchemaValidationTest(unittest.TestCase):
    def test_unparseable_output_is_quarantined_not_partially_accepted(self) -> None:
        runtime = AgentRuntime(
            model=FakeAgentModel(raw_response='{"claims": [ {"statement": '),
            tool_allowlist=("read_document_version",),
            budget=BUDGET,
            run_context=CONTEXT,
        )
        record = runtime.run(
            prompt_template_id="prompt:event-extract:v0",
            document_version_ids=("document-version:cninfo:000858:preview:0",),
        )
        self.assertEqual(record.status, AgentRunStatus.SCHEMA_INVALID)
        self.assertIsNotNone(record.quarantined_output_hash)
        self.assertEqual(runtime.accepted_claims(), ())

    def test_one_invalid_claim_does_not_admit_the_valid_ones(self) -> None:
        """Partial acceptance is how an unvalidated claim gets in beside good ones."""
        ...

    def test_the_raw_response_hash_is_always_recorded(self) -> None:
        """SPEC-028 acceptance: bind model, prompt, tools, citations, raw response."""
        ...

    def test_the_prompt_template_hash_is_recorded_not_the_prompt_text(self) -> None:
        ...


class AttributionTest(unittest.TestCase):
    def test_the_run_is_attributed_to_the_agent_identity(self) -> None:
        """A reviewer who launches an agent does not sign its output."""
        ...

    def test_the_run_cannot_use_a_deployment_stage_beyond_research(self) -> None:
        """An extraction run is research; it is not a shadow, paper or live run."""
        with self.assertRaises(PermissionError):
            AgentRuntime(
                model=FakeAgentModel(),
                tool_allowlist=(),
                budget=BUDGET,
                run_context=RunContext(
                    DataMode.CURRENT_RESEARCH, DeploymentStage.PAPER
                ),
            )


class NoRealProviderTest(unittest.TestCase):
    def test_no_llm_sdk_is_importable_from_the_platform(self) -> None:
        """The provider decision belongs to the user: cost plus source licence.

        This asserts the absence of a dependency, which is the only honest way to
        state "we did not quietly wire one up".
        """
        import importlib.util

        for module_name in ("anthropic", "openai", "google.generativeai"):
            with self.subTest(module=module_name):
                self.assertIsNone(
                    importlib.util.find_spec(module_name),
                    f"{module_name} is installed; a provider decision was skipped",
                )

    def test_the_only_registered_model_adapter_is_the_fake(self) -> None:
        ...
```

- [ ] **Step 7: 写引用校验红测**

```python
# platform/tests/test_agent_citations.py
"""Citations are checked against the document, not taken on trust.

An agent that cites a document it did not read, or cites a character range that
does not exist, produces output that looks sourced and is not.  The check is cheap
and it is the only thing standing between "extraction" and "generation".
"""

from __future__ import annotations

import unittest


class CitationValidationTest(unittest.TestCase):
    def test_a_citation_to_an_unregistered_document_is_invalid(self) -> None:
        ...

    def test_a_citation_range_beyond_the_document_length_is_invalid(self) -> None:
        ...

    def test_a_quoted_hash_that_does_not_match_the_range_is_invalid(self) -> None:
        """This is what catches a fabricated quotation of a real document."""
        ...

    def test_a_citation_to_a_document_not_in_the_run_input_is_invalid(self) -> None:
        """The agent may only cite what it was given, or it read something else."""
        ...

    def test_an_invalid_citation_quarantines_the_claim_not_the_whole_event(self) -> None:
        ...

    def test_a_claim_with_no_valid_citation_cannot_reach_an_investment_view(self) -> None:
        """The prototype states it as a boundary: 无引用结论不能进入 InvestmentView.

        Asserted here at the runtime level and again in Task 5 at the compiler
        level, because a single gate can be bypassed by a new call path.
        """
        ...
```

- [ ] **Step 8: migration `0041` 与 audit repository**

两张表：`governance.agent_run_records`（append-only，含 `raw_response_hash`、
`prompt_template_hash`、`tool_allowlist`、budget 各字段、`status`、`status_reason`、
`quarantined_output_hash`）与 `research.agent_claims`（append-only，含 citations JSONB
与 `derived_retention_ceiling`）。

约束：
```sql
CHECK (status = 'succeeded' OR btrim(status_reason) <> '')
CHECK (claim_kind <> 'fact' OR confidence IS NULL)
CHECK (claim_kind = 'fact' OR confidence IS NOT NULL)
CHECK (jsonb_array_length(citations) >= 1)
CHECK (run_context_deployment_stage = 'research')
```
最后一条把「抽取只发生在 research 阶段」写进数据库，而不只写在类型里。

- [ ] **Step 9: 明确 Agent 在去重中的角色（只提候选，不判定）**

Task 2 的 `deduplicate_documents` 是确定性的。Agent 可以**提出** "这两篇可能是同一件事"，
但那只是一条 `AgentClaimKind.INFERENCE` 的 claim，进入 `待人工确认` 队列，
**不改变 `DedupeVerdict`**。写一个测试断言这一点：

```python
def test_an_agent_similarity_claim_does_not_change_a_dedupe_verdict(self) -> None:
    """The agent may nominate a duplicate; only the deterministic rule decides."""
    ...
```

- [ ] **Step 10: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
git diff --check
cd .. && git add platform/src/a_share_platform/domain/agent_research.py \
  platform/src/a_share_platform/ports/agent_model.py \
  platform/src/a_share_platform/ports/agent_tools.py \
  platform/src/a_share_platform/application/agent_runtime.py \
  platform/src/a_share_platform/adapters/memory/agent_model.py \
  platform/migrations/0041_p8_agent_audit.sql \
  platform/tests/test_agent_claim_contracts.py \
  platform/tests/test_agent_authority_boundary.py \
  platform/tests/test_agent_runtime.py \
  platform/tests/test_agent_citations.py \
  docs/28-p8-events-agents-evidence.md
git commit -m "feat: run the research agent as an extractor with no authority of its own

The agent is an extractor and a hypothesis generator.  It is never an authority, and
the way to make that true is to put it in the type system rather than in a document
that a future call path can ignore.

A claim about a price, a financial value, an announcement time or a trade result
cannot be constructed as a FACT at all: the governed-field deny list is checked in
__post_init__.  The agent may still reason about revenue — that is the useful part —
but it does so as an INFERENCE carrying explicit confidence, and a FACT carrying
confidence is refused because a fact with a probability attached is an inference
wearing a costume.  The 五粮液 restatement is why this matters concretely: the same
reported revenue moved from 36.94bn to 17.09bn CNY, and a model that had certified
the first number would have been confidently wrong for a year.

Every claim needs at least one citation, and citations are validated rather than
trusted: the document must be registered, must have been in this run's input, the
character range must exist, and the quoted hash must match that range.  The last
check is the one that catches a fabricated quotation of a real document.  A claim
whose citations all fail is quarantined rather than dropped, because the output is
evidence about the agent even when it is not evidence about the company.

Retention travels with the citation.  A claim sourced only from a metadata-only
licence cannot declare indefinite retention, because ADR-0008 decision 3 says in so
many words that being unable to keep the original does not license keeping a model's
restatement of it forever.

Failure has five statuses, not one: schema_invalid, citation_invalid,
budget_exceeded, deadline_exceeded and tool_denied.  Collapsing them into 'failed'
would hide which of five different fixes is needed.  Tools are deny-by-default and
the empty allowlist is a valid configuration rather than an error.

No real provider is called.  A test asserts that no LLM SDK is even importable,
because the provider choice is a user decision about cost and about whether sending
a no-store document to a third party is permitted by its licence.  Everything above
is proven against a deterministic fake first, so the answer to that question changes
one adapter and nothing else."
```

---

### Task 4: 供应链图（`domain/supply_chain.py`）

对应 Step 07 Task 4：「新增 `domain/supply_chain.py`、graph repository、
effective interval/stale/double-count tests；关系不确定时不推断为事实。」

**Files:**
- Create: `platform/src/a_share_platform/domain/supply_chain.py`
- Create: `platform/src/a_share_platform/ports/supply_chain.py`
- Create: `platform/src/a_share_platform/application/supply_chain_graph.py`
- Create: `platform/src/a_share_platform/adapters/memory/supply_chain.py`
- Create: `platform/migrations/0042_p8_supply_chain.sql`
- Test: `platform/tests/test_supply_chain_edges.py`
- Test: `platform/tests/test_supply_chain_propagation.py`

**Interfaces:**
- Consumes: Task 1 的 `DocumentVersion`、Task 3 的 `AgentClaim`（作为 `INFERRED_FROM_TEXT` 证据）
- Produces:
  ```python
  class RelationshipKind(StrEnum):
      SUPPLIES_TO = "supplies_to"
      CUSTOMER_OF = "customer_of"
      SHARES_INPUT_WITH = "shares_input_with"
      COMPETES_WITH = "competes_with"
      OWNS_STAKE_IN = "owns_stake_in"

  class EdgeEvidenceKind(StrEnum):
      DISCLOSED_NAMED = "disclosed_named"                  # 年报点名披露
      DISCLOSED_UNNAMED_SHARE = "disclosed_unnamed_share"   # 只披露占比，不点名
      THIRD_PARTY_RESEARCH = "third_party_research"
      INFERRED_FROM_TEXT = "inferred_from_text"

  class EdgeStatus(StrEnum):
      ASSERTED = "asserted"        # 可用于传播计算
      HYPOTHESIS = "hypothesis"    # 只能显示，不参与计算
      REFUTED = "refuted"
      STALE = "stale"

  @dataclass(frozen=True)
  class SupplyChainEdge:
      edge_id: str
      upstream_company_id: str
      downstream_company_id: str
      relationship: RelationshipKind
      effective_from: date
      effective_to: date | None        # 半开区间；None = 至今
      evidence_kind: EdgeEvidenceKind
      evidence_document_version_ids: tuple[str, ...]
      revenue_share: Decimal | None     # 有则必须 (0, 1]
      confidence: Decimal              # (0, 1]
      staleness_limit_days: int
      observed_at: date
      status: EdgeStatus
      status_reason: str | None
      content_hash: str = field(init=False)
  ```

- [ ] **Step 1: 写边合同红测 —— 不确定的关系不能断言**

```python
# platform/tests/test_supply_chain_edges.py
"""Supply chain edges, which are usually inferred and often wrong.

Three ways a relationship in this graph is false while looking true:

- an annual report discloses "top five customers account for 41% of revenue"
  without naming them, so the share is known and the counterparty is not;
- a sell-side industry map was accurate when drawn and the supplier changed two
  years later, so the edge is stale rather than wrong;
- a model reads "concept stock in the Tesla supply chain" as "supplies to Tesla".

So an edge carries an effective interval, an evidence kind and a staleness limit,
and an edge inferred from text may not be ASSERTED at all — it can only be a
HYPOTHESIS, which is displayed and never propagated.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from a_share_platform.domain.supply_chain import (
    EdgeEvidenceKind,
    EdgeStatus,
    RelationshipKind,
    SupplyChainEdge,
)


def edge(
    *,
    evidence_kind: EdgeEvidenceKind = EdgeEvidenceKind.DISCLOSED_NAMED,
    status: EdgeStatus = EdgeStatus.ASSERTED,
    effective_from: date = date(2024, 1, 1),
    effective_to: date | None = None,
    revenue_share: Decimal | None = Decimal("0.18"),
    confidence: Decimal = Decimal("0.9"),
    staleness_limit_days: int = 540,
    observed_at: date = date(2025, 4, 26),
    reason: str | None = None,
    upstream: str = "company:CN:002898",
    downstream: str = "company:CN:000858",
) -> SupplyChainEdge:
    return SupplyChainEdge(
        edge_id="supply-chain-edge:0001",
        upstream_company_id=upstream,
        downstream_company_id=downstream,
        relationship=RelationshipKind.SUPPLIES_TO,
        effective_from=effective_from,
        effective_to=effective_to,
        evidence_kind=evidence_kind,
        evidence_document_version_ids=("document-version:cninfo:000858:annual:0",),
        revenue_share=revenue_share,
        confidence=confidence,
        staleness_limit_days=staleness_limit_days,
        observed_at=observed_at,
        status=status,
        status_reason=reason,
    )


class UncertaintyTest(unittest.TestCase):
    def test_a_text_inferred_edge_cannot_be_asserted(self) -> None:
        """"Tesla supply chain concept stock" is not "supplies to Tesla"."""
        with self.assertRaises(ValueError):
            edge(
                evidence_kind=EdgeEvidenceKind.INFERRED_FROM_TEXT,
                status=EdgeStatus.ASSERTED,
            )

    def test_a_text_inferred_edge_is_allowed_as_a_hypothesis(self) -> None:
        value = edge(
            evidence_kind=EdgeEvidenceKind.INFERRED_FROM_TEXT,
            status=EdgeStatus.HYPOTHESIS,
            confidence=Decimal("0.3"),
            reason="extracted from a news paraphrase; counterparty not confirmed",
        )
        self.assertEqual(value.status, EdgeStatus.HYPOTHESIS)

    def test_an_unnamed_share_disclosure_cannot_name_a_counterparty(self) -> None:
        """41% to unnamed top-five customers identifies a share, not a company."""
        with self.assertRaises(ValueError):
            edge(
                evidence_kind=EdgeEvidenceKind.DISCLOSED_UNNAMED_SHARE,
                status=EdgeStatus.ASSERTED,
            )

    def test_a_non_asserted_edge_requires_a_reason(self) -> None:
        with self.assertRaises(ValueError):
            edge(status=EdgeStatus.HYPOTHESIS, reason=None)

    def test_confidence_of_zero_is_refused(self) -> None:
        """A zero-confidence edge is an absence of a claim, not a claim."""
        with self.assertRaises(ValueError):
            edge(confidence=Decimal("0"))

    def test_revenue_share_above_one_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            edge(revenue_share=Decimal("1.4"))

    def test_a_self_edge_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            edge(upstream="company:CN:000858", downstream="company:CN:000858")


class EffectiveIntervalTest(unittest.TestCase):
    def test_effective_to_cannot_precede_effective_from(self) -> None:
        with self.assertRaises(ValueError):
            edge(effective_from=date(2025, 1, 1), effective_to=date(2024, 6, 1))

    def test_the_interval_is_half_open(self) -> None:
        """effective_to is exclusive, so two consecutive edges do not overlap."""
        value = edge(effective_from=date(2024, 1, 1), effective_to=date(2025, 1, 1))
        self.assertTrue(value.covers(date(2024, 12, 31)))
        self.assertFalse(value.covers(date(2025, 1, 1)))

    def test_an_edge_is_not_in_force_before_it_starts(self) -> None:
        value = edge(effective_from=date(2024, 1, 1))
        self.assertFalse(value.covers(date(2023, 12, 31)))

    def test_an_edge_observed_before_it_starts_is_refused(self) -> None:
        """You cannot have observed in 2023 a relationship effective from 2024."""
        with self.assertRaises(ValueError):
            edge(effective_from=date(2024, 1, 1), observed_at=date(2023, 6, 1))

    def test_a_non_date_effective_from_is_refused(self) -> None:
        """"They are a supplier" with no date cannot be used at a decision time."""
        with self.assertRaises(TypeError):
            edge(effective_from="2024-01-01")  # type: ignore[arg-type]


class StalenessTest(unittest.TestCase):
    def test_an_edge_past_its_staleness_limit_is_stale_at_the_decision_date(self) -> None:
        value = edge(observed_at=date(2023, 4, 26), staleness_limit_days=540)
        self.assertTrue(value.is_stale(as_of=date(2026, 8, 16)))

    def test_a_fresh_edge_is_not_stale(self) -> None:
        value = edge(observed_at=date(2026, 4, 26), staleness_limit_days=540)
        self.assertFalse(value.is_stale(as_of=date(2026, 8, 16)))

    def test_is_stale_requires_an_explicit_as_of(self) -> None:
        """Reading the clock here would make the same query answer differently."""
        with self.assertRaises(TypeError):
            edge().is_stale()  # type: ignore[call-arg]

    def test_staleness_limit_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            edge(staleness_limit_days=0)

    def test_a_stale_edge_cannot_be_used_for_propagation(self) -> None:
        """Stale is a different failure from refuted, and both stop propagation."""
        ...

    def test_a_third_party_research_edge_needs_a_shorter_default_limit(self) -> None:
        """An industry map ages faster than a named disclosure; state it, don't assume."""
        ...
```

- [ ] **Step 2: 运行确认红测 → 实现 → 转绿**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_supply_chain_edges -v`
Expected: FAIL —— `domain.supply_chain` 不存在。

实现顺序：三个枚举 → `SupplyChainEdge` → `covers()` → `is_stale()`。
`covers()` 与 `is_stale()` 都是纯函数，**不读时钟** —— `as_of` 必须显式传入，
否则测试不可复现且决策时点会漂移。

- [ ] **Step 3: 写传播红测 —— 双路径重复计数必须被检测**

```python
# platform/tests/test_supply_chain_propagation.py
"""Propagating one shock through the graph without counting it twice.

If A supplies B directly and also supplies B through C, then a shock at A reaches B
along two paths.  Summing both paths counts the same shock twice, and the error
grows with graph density — exactly where the graph is most interesting.

The propagator therefore refuses to sum over overlapping paths.  It reports the
paths, reports that they share an origin, and returns unavailable with a reason
rather than a number that is silently 1.8x too large.
"""

from __future__ import annotations

import unittest
from datetime import date

from a_share_platform.application.supply_chain_graph import (
    PropagationStatus,
    SupplyChainGraph,
)

AS_OF = date(2026, 8, 16)


class DoubleCountTest(unittest.TestCase):
    def test_two_paths_from_one_origin_are_detected(self) -> None:
        graph = SupplyChainGraph(_edges_a_to_b_direct_and_via_c())
        result = graph.propagate(
            origin_company_id="company:CN:AAA",
            as_of=AS_OF,
            max_depth=3,
        )
        self.assertEqual(result.status, PropagationStatus.AMBIGUOUS_PATHS)
        self.assertIsNone(result.total_impact_multiplier)
        self.assertEqual(len(result.paths_to("company:CN:BBB")), 2)

    def test_the_reason_names_the_shared_origin_and_the_target(self) -> None:
        ...

    def test_a_single_path_propagates_normally(self) -> None:
        ...

    def test_a_cycle_terminates_rather_than_recursing(self) -> None:
        """A→B→A exists in real filings when both sell to each other."""
        ...

    def test_max_depth_is_required_and_recorded(self) -> None:
        """An unbounded traversal on a dense graph is a hang, not an analysis."""
        ...


class EdgeEligibilityTest(unittest.TestCase):
    def test_a_hypothesis_edge_is_excluded_from_propagation(self) -> None:
        ...

    def test_a_stale_edge_is_excluded_and_reported(self) -> None:
        """Excluded silently, the result would look complete while missing a path."""
        ...

    def test_an_edge_outside_its_effective_interval_is_excluded(self) -> None:
        ...

    def test_excluded_edges_are_counted_in_the_result(self) -> None:
        """Coverage must be reported: a thin graph is a limitation, not a finding."""
        ...

    def test_a_propagation_with_no_eligible_edge_is_unavailable_not_zero(self) -> None:
        """Zero impact and unknown impact are different answers."""
        graph = SupplyChainGraph(())
        result = graph.propagate(
            origin_company_id="company:CN:AAA", as_of=AS_OF, max_depth=3
        )
        self.assertEqual(result.status, PropagationStatus.UNAVAILABLE)
        self.assertIsNone(result.total_impact_multiplier)
        self.assertIsNotNone(result.unavailable_reason)


class MagnitudeTest(unittest.TestCase):
    def test_propagated_magnitude_requires_a_revenue_share_on_every_edge(self) -> None:
        """Without a share there is no scale, and assuming 100% is a fabrication."""
        ...

    def test_confidence_compounds_along_the_path(self) -> None:
        """Two 0.7 edges do not make a 0.7 conclusion."""
        ...

    def test_a_path_confidence_below_the_floor_is_reported_not_dropped(self) -> None:
        ...
```

- [ ] **Step 4: 实现 `SupplyChainGraph.propagate()`**

必须是纯函数式遍历：输入边集合 + origin + `as_of` + `max_depth`，
输出 `PropagationResult`（含 `status`、`paths`、`excluded_edge_reasons`、
`coverage`、`total_impact_multiplier | None`、`unavailable_reason | None`）。

`PropagationStatus` 至少四值：`QUANTIFIED` / `AMBIGUOUS_PATHS` / `PARTIAL` / `UNAVAILABLE`。
**`AMBIGUOUS_PATHS` 时 `total_impact_multiplier` 必须为 `None`** ——
这是本 Task 的核心断言，不是可选的保守策略。

- [ ] **Step 5: migration `0042` 与提交**

一张表 `research.supply_chain_edges`，append-only。关键约束：

```sql
CHECK (upstream_company_id <> downstream_company_id)
CHECK (effective_to IS NULL OR effective_to > effective_from)
CHECK (observed_at >= effective_from)
CHECK (confidence > 0 AND confidence <= 1)
CHECK (revenue_share IS NULL OR (revenue_share > 0 AND revenue_share <= 1))
CHECK (staleness_limit_days > 0)
CHECK (status = 'asserted' OR btrim(status_reason) <> '')
CHECK (evidence_kind <> 'inferred_from_text' OR status <> 'asserted')
CHECK (evidence_kind <> 'disclosed_unnamed_share' OR status <> 'asserted')
```

最后两条把"不确定不得断言"写进数据库层。

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
git diff --check
cd .. && git add platform/src/a_share_platform/domain/supply_chain.py \
  platform/src/a_share_platform/ports/supply_chain.py \
  platform/src/a_share_platform/application/supply_chain_graph.py \
  platform/src/a_share_platform/adapters/memory/supply_chain.py \
  platform/migrations/0042_p8_supply_chain.sql \
  platform/tests/test_supply_chain_edges.py \
  platform/tests/test_supply_chain_propagation.py \
  docs/28-p8-events-agents-evidence.md
git commit -m "feat: model supply chain relationships as dated, graded claims rather than facts

Almost every edge in a supply chain graph is inferred, and a large fraction are
either wrong or were right once.  An annual report says the top five customers are
41% of revenue without naming them, which identifies a share and not a
counterparty.  A sell-side industry map was accurate when drawn and the supplier
changed the following year.  A model reads 'Tesla supply chain concept stock' and
produces 'supplies to Tesla'.

So an edge cannot exist without an effective interval, an evidence kind, a
confidence and a staleness limit, and two evidence kinds are barred from ASSERTED
entirely: text inference and unnamed share disclosure.  Both may exist as
HYPOTHESIS, which is displayed to a human and never propagated.  The database
carries the same two rules as check constraints, because a type invariant does not
protect rows inserted by a future import script.

Intervals are half-open so consecutive edges do not overlap, and covers() and
is_stale() both require an explicit as_of instead of reading a clock — a graph query
whose answer depends on when it ran is not reproducible.

The propagation rule is the part that would be easy to get quietly wrong.  When a
shock reaches one company along two paths from the same origin, summing them counts
it twice, and the overstatement grows with graph density.  The propagator returns
AMBIGUOUS_PATHS with a null multiplier and both paths listed, rather than a number
that happens to be too large.  An empty eligible edge set returns unavailable with a
reason rather than zero, because no known path and no impact are different claims."
```

---

### Task 5: 事件研究、更正触发 Review 与 InvestmentView v2

对应 Step 07 Task 5：「实现 expected return/AR/CAR/clustered or bootstrap SE/matched
controls/FDR；独立库交叉验证；通过 review 后调用新 CompilerVersion 生成新 View。」

本 Task 有两条并行线：**统计**（`validation/gates.py` 的六个 key）与
**治理**（ADR-0008 决策 4 的下游 Review）。它们必须同一个 Task，因为一个更正
既改变统计输入也改变已发布结论，分开做会出现"统计已重算但结论未重审"的中间态。

**Files:**
- Create: `platform/src/a_share_platform/domain/event_study.py`
- Create: `platform/src/a_share_platform/domain/event_impact.py`
- Create: `platform/src/a_share_platform/application/event_study_runner.py`
- Create: `platform/src/a_share_platform/application/downstream_review.py`
- Create: `platform/src/a_share_platform/domain/event_view_compiler.py`（`ExpectedReturnCompilerV1`）
- Modify: `platform/src/a_share_platform/validation/statistical_crosscheck.py`（新增 `cross_check_event_car`）
- Create: `platform/migrations/0043_p8_event_study_and_reviews.sql`
- Test: `platform/tests/test_event_study_statistics.py`
- Test: `platform/tests/test_event_study_gate.py`
- Test: `platform/tests/test_downstream_review.py`
- Test: `platform/tests/test_event_view_compiler.py`

**Interfaces:**
- Consumes: Task 2 的 `EventCluster`、Task 3 的 `AgentClaim`、Task 4 的 `PropagationResult`、
  已有 `domain/factor_statistics.py` 的 `BlockBootstrapSpec` / `block_bootstrap_mean_ci()`、
  `domain/factor_validation.py` 的 `HypothesisPValue` / `BHFamilySpec` / `benjamini_hochberg()`、
  `validation/gates.py` 的 `ResearchKind.EVENT` / `policy_for()`、
  `domain/expected_return.py` 的 `ExpectedReturnCompileRequest` / `InvestmentComponent`、
  **P-5** 的 `domain/portfolio.py` 成本模型（增量价值）
- Produces:
  ```python
  class AbnormalReturnModel(StrEnum):
      MARKET_ADJUSTED = "market_adjusted"
      MARKET_MODEL = "market_model"            # OLS alpha/beta on estimation window
      FAMA_FRENCH_STYLE = "fama_french_style"

  class StandardErrorMethod(StrEnum):
      """No IID member exists.  Overlapping windows make it inadmissible."""
      CLUSTERED_BY_EVENT_DATE = "clustered_by_event_date"
      BLOCK_BOOTSTRAP = "block_bootstrap"

  @dataclass(frozen=True)
  class EventWindow:
      pre_sessions: int            # <= 0，相对事件日
      post_sessions: int           # >= 0
      estimation_start_sessions: int
      estimation_end_sessions: int   # 必须早于 pre_sessions（估计窗不含事件窗）

  @dataclass(frozen=True)
  class EventStudySpec:
      study_id: str
      version: str
      category: EventCategory
      window: EventWindow
      abnormal_return_model: AbnormalReturnModel
      se_method: StandardErrorMethod
      matched_control_spec: MatchedControlSpec
      bh_family_spec: BHFamilySpec         # 复用已有类型
      minimum_events: int
      data_mode: DataMode
      trust_state: DataTrustState
      content_hash: str = field(init=False)

  @dataclass(frozen=True)
  class MatchedControlSpec:
      match_on: tuple[str, ...]     # e.g. ("industry", "size_decile", "book_to_market")
      controls_per_event: int
      exclude_own_event_window: bool     # 必须 True
      matcher_version: str

  @dataclass(frozen=True)
  class EventStudyResult:
      status: StatisticStatus
      spec_hash: str
      event_count: int
      clustered_event_dates: int
      max_events_on_one_date: int
      mean_car: float | None
      standard_error: float | None
      t_statistic: float | None
      p_value: float | None
      bh_adjusted_p_value: float | None
      matched_control_mean_car: float | None
      excluded_event_reasons: tuple[tuple[str, int], ...]
      unavailable_reason: str | None
      scientific_status: StatisticsScientificStatus
      warnings: tuple[str, ...]
  ```

- [ ] **Step 1: 先读已有统计与 Gate 的真实签名**

```bash
cd platform
grep -n "class BlockBootstrapSpec" -A22 src/a_share_platform/domain/factor_statistics.py
grep -n "def block_bootstrap_mean_ci" -A12 src/a_share_platform/domain/factor_statistics.py
grep -n "class TimeSeriesObservation" -A12 src/a_share_platform/domain/factor_statistics.py
grep -n "class BHFamilySpec" -A20 src/a_share_platform/domain/factor_validation.py
grep -n "def benjamini_hochberg" -A10 src/a_share_platform/domain/factor_validation.py
grep -n "ResearchKind.EVENT" -A12 src/a_share_platform/validation/gates.py
```

已核实的关键约束，直接影响 spec 设计：

- `BlockBootstrapSpec` 要求 `resamples >= 100`、`block_size > 0`、
  `0 < confidence_level < 1`、`seed >= 0`、`minimum_sample_size >= 2`；
- `HACNeweyWestSpec` 要求 `minimum_sample_size > max_lag + 1` —— 事件研究若用 HAC，
  这条会直接排除小样本；
- `BHFamilySpec` 要求 `minimum_hypotheses >= 2`，且
  `_validate_p_value_context` 强制**一个 family 只能冻结一个 `p_value_version_id`**；
- `benjamini_hochberg` 在任一 p 值缺失时返回
  `"missing p-values make the frozen multiple-testing family unavailable"` ——
  **它已经拒绝部分结果，本 Task 不要绕过它**。

`ResearchKind.EVENT` 的六个 key 逐字：
`event_time_integrity`、`abnormal_return_model`、`event_window_car`、
`clustered_or_bootstrap_se`、`matched_controls`、`overlap_and_multiple_testing`。

- [ ] **Step 2: 写 spec 合同红测 —— i.i.d. 不是一个选项**

```python
# platform/tests/test_event_study_statistics.py
"""Event study statistics under cross-sectional dependence.

Event studies look like large-sample problems and are not.  Earnings previews cluster
in January and July, so hundreds of events share one calendar day and therefore share
that day's market shock.  A [-5, +20] window spans 26 sessions, so consecutive events
for one issuer overlap.  A policy event applies to every firm in an industry at once.

Under i.i.d. standard errors the estimate of the standard error is too small by
roughly the square root of the number of events per day.  A hundred events on one day
understates it tenfold, turning a t of 0.3 into a t of 3.0.  That is not reduced
precision; it is manufactured significance, and it is indistinguishable from a real
result in the output.

So StandardErrorMethod has no IID member.  It cannot be configured, only chosen
between clustering by event date and a block bootstrap, and clustering becomes
mandatory as soon as any calendar day carries more than one event.
"""

from __future__ import annotations

import unittest
from datetime import date

from a_share_platform.domain.event_study import (
    AbnormalReturnModel,
    EventStudySpec,
    EventWindow,
    MatchedControlSpec,
    StandardErrorMethod,
)
from a_share_platform.domain.events import EventCategory
from a_share_platform.domain.factor_validation import BHFamilySpec
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode


def window(
    *,
    pre: int = -5,
    post: int = 20,
    estimation_start: int = -255,
    estimation_end: int = -21,
) -> EventWindow:
    return EventWindow(
        pre_sessions=pre,
        post_sessions=post,
        estimation_start_sessions=estimation_start,
        estimation_end_sessions=estimation_end,
    )


def controls(*, exclude_own: bool = True) -> MatchedControlSpec:
    return MatchedControlSpec(
        match_on=("industry", "size_decile"),
        controls_per_event=5,
        exclude_own_event_window=exclude_own,
        matcher_version="event-matcher:v0",
    )


def family() -> BHFamilySpec:
    return BHFamilySpec(
        family_id="event-study-family:earnings-preview",
        family_version="v0",
        alpha=0.05,
        minimum_hypotheses=2,
        method_version="benjamini-hochberg-step-up:v1",
        tie_break_version="hypothesis-id-ascending:v1",
    )


def spec(
    *,
    se_method: StandardErrorMethod = StandardErrorMethod.CLUSTERED_BY_EVENT_DATE,
    window_value: EventWindow | None = None,
    control_spec: MatchedControlSpec | None = None,
    minimum_events: int = 30,
    data_mode: DataMode = DataMode.CURRENT_RESEARCH,
    trust_state: DataTrustState = DataTrustState.NORMALIZED_CURRENT,
) -> EventStudySpec:
    return EventStudySpec(
        study_id="event-study:earnings-preview",
        version="v0",
        category=EventCategory.EARNINGS,
        window=window_value or window(),
        abnormal_return_model=AbnormalReturnModel.MARKET_MODEL,
        se_method=se_method,
        matched_control_spec=control_spec or controls(),
        bh_family_spec=family(),
        minimum_events=minimum_events,
        data_mode=data_mode,
        trust_state=trust_state,
    )


class StandardErrorMethodTest(unittest.TestCase):
    def test_there_is_no_iid_standard_error_option(self) -> None:
        """The safest way to prevent a choice is to not offer it."""
        members = {member.value for member in StandardErrorMethod}
        self.assertEqual(
            members,
            {"clustered_by_event_date", "block_bootstrap"},
        )
        self.assertNotIn("iid", members)

    def test_an_unknown_se_method_string_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            EventStudySpec(
                study_id="event-study:earnings-preview",
                version="v0",
                category=EventCategory.EARNINGS,
                window=window(),
                abnormal_return_model=AbnormalReturnModel.MARKET_MODEL,
                se_method="iid",  # type: ignore[arg-type]
                matched_control_spec=controls(),
                bh_family_spec=family(),
                minimum_events=30,
                data_mode=DataMode.CURRENT_RESEARCH,
                trust_state=DataTrustState.NORMALIZED_CURRENT,
            )


class EstimationWindowTest(unittest.TestCase):
    def test_the_estimation_window_must_end_before_the_event_window_starts(self) -> None:
        """Fitting alpha and beta on the event itself absorbs the abnormal return."""
        with self.assertRaises(ValueError):
            spec(window_value=window(estimation_end=-3, pre=-5))

    def test_the_event_window_must_include_the_event_day(self) -> None:
        with self.assertRaises(ValueError):
            spec(window_value=window(pre=2, post=20))

    def test_a_post_window_of_zero_is_allowed(self) -> None:
        """A same-day study is legitimate; it is simply a one-session window."""
        value = spec(window_value=window(pre=0, post=0))
        self.assertEqual(value.window.post_sessions, 0)

    def test_the_estimation_window_must_be_long_enough_to_fit_the_model(self) -> None:
        """A market model on 5 sessions produces a beta with no information."""
        with self.assertRaises(ValueError):
            spec(window_value=window(estimation_start=-25, estimation_end=-21))


class MatchedControlTest(unittest.TestCase):
    def test_a_control_may_not_be_in_its_own_event_window(self) -> None:
        """A control that is itself experiencing the event is not a control."""
        with self.assertRaises(ValueError):
            spec(control_spec=controls(exclude_own=False))

    def test_matching_requires_at_least_one_dimension(self) -> None:
        with self.assertRaises(ValueError):
            spec(
                control_spec=MatchedControlSpec(
                    match_on=(),
                    controls_per_event=5,
                    exclude_own_event_window=True,
                    matcher_version="event-matcher:v0",
                )
            )

    def test_zero_controls_per_event_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            spec(
                control_spec=MatchedControlSpec(
                    match_on=("industry",),
                    controls_per_event=0,
                    exclude_own_event_window=True,
                    matcher_version="event-matcher:v0",
                )
            )


class SpecIdentityTest(unittest.TestCase):
    def test_the_spec_is_content_addressed(self) -> None:
        self.assertEqual(spec().content_hash, spec().content_hash)
        self.assertEqual(len(spec().content_hash), 64)

    def test_changing_the_window_changes_the_hash(self) -> None:
        self.assertNotEqual(
            spec().content_hash,
            spec(window_value=window(post=60)).content_hash,
        )

    def test_changing_the_se_method_changes_the_hash(self) -> None:
        self.assertNotEqual(
            spec().content_hash,
            spec(se_method=StandardErrorMethod.BLOCK_BOOTSTRAP).content_hash,
        )

    def test_strict_historical_requires_pit_verified(self) -> None:
        with self.assertRaises(PermissionError):
            spec(
                data_mode=DataMode.STRICT_HISTORICAL,
                trust_state=DataTrustState.NORMALIZED_CURRENT,
            )
```

- [ ] **Step 3: 写 clustering 强制红测 —— 这是本 Task 的核心**

```python
# 追加到 platform/tests/test_event_study_statistics.py

class ClusteringRequirementTest(unittest.TestCase):
    def test_multiple_events_on_one_date_require_clustering_or_bootstrap(self) -> None:
        """Both admissible methods handle dependence; the point is that one is used.

        This test does not prefer clustering over bootstrapping.  It asserts the
        result reports which of the two ran and how much clustering there was, so a
        reader can judge whether the standard error is credible.
        """
        from a_share_platform.domain.event_study import run_event_study

        result = run_event_study(
            _events_with_dates([date(2026, 7, 14)] * 40 + [date(2026, 7, 15)] * 30),
            spec=spec(minimum_events=30),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        self.assertEqual(result.max_events_on_one_date, 40)
        self.assertEqual(result.clustered_event_dates, 2)

    def test_the_effective_sample_is_the_number_of_clusters_not_of_events(self) -> None:
        """70 events on 2 days is 2 independent observations, not 70."""
        from a_share_platform.domain.event_study import run_event_study

        result = run_event_study(
            _events_with_dates([date(2026, 7, 14)] * 40 + [date(2026, 7, 15)] * 30),
            spec=spec(minimum_events=30),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        self.assertEqual(result.status, StatisticStatus.UNAVAILABLE)
        assert result.unavailable_reason is not None
        self.assertIn("cluster", result.unavailable_reason.lower())

    def test_a_warning_states_the_clustering_ratio(self) -> None:
        """70 events / 2 dates = 35 per cluster.  The reader needs that number."""
        ...

    def test_overlapping_windows_for_one_issuer_are_detected(self) -> None:
        """Two events 10 sessions apart with a 26-session window overlap."""
        ...

    def test_overlapping_windows_are_excluded_with_a_counted_reason(self) -> None:
        """Silently keeping them would double-weight one price path."""
        ...

    def test_below_minimum_events_reports_unavailable_not_a_number(self) -> None:
        from a_share_platform.domain.event_study import run_event_study

        result = run_event_study(
            _events_with_dates([date(2026, 7, 14), date(2026, 8, 3)]),
            spec=spec(minimum_events=30),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        self.assertEqual(result.status, StatisticStatus.UNAVAILABLE)
        self.assertIsNone(result.mean_car)
        self.assertIsNone(result.t_statistic)

    def test_a_negative_car_is_reported_unchanged(self) -> None:
        """The result is the result.  Re-running until it turns positive is fraud."""
        ...


class MultipleTestingTest(unittest.TestCase):
    def test_the_bh_family_must_be_frozen_before_results_are_seen(self) -> None:
        """A family assembled after looking at p-values controls nothing."""
        ...

    def test_a_single_hypothesis_cannot_form_a_bh_family(self) -> None:
        """BHFamilySpec already requires minimum_hypotheses >= 2; assert we use it."""
        with self.assertRaises(ValueError):
            BHFamilySpec(
                family_id="event-study-family:single",
                family_version="v0",
                alpha=0.05,
                minimum_hypotheses=1,
                method_version="benjamini-hochberg-step-up:v1",
                tie_break_version="hypothesis-id-ascending:v1",
            )

    def test_the_adjusted_p_value_is_reported_alongside_the_raw_one(self) -> None:
        """Showing only the raw p-value across 36 tests is how 1.8 false positives
        become 'two significant event types'."""
        ...

    def test_a_missing_p_value_makes_the_whole_family_unavailable(self) -> None:
        """Reuses benjamini_hochberg's existing refusal rather than working around it."""
        ...

    def test_the_family_spans_every_tested_category_and_window(self) -> None:
        """Testing 12 categories x 3 windows and correcting within one category
        leaves the discovery bias in place."""
        ...


class CrossCheckTest(unittest.TestCase):
    def test_the_independent_library_receives_the_identical_car_series(self) -> None:
        """A cross-check on different inputs proves nothing — same rule as P-2."""
        ...

    def test_cross_check_reports_unavailable_when_statsmodels_is_absent(self) -> None:
        """Absence of the library must not read as agreement."""
        ...
```

- [ ] **Step 4: 运行确认红测 → 实现 → 转绿**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_event_study_statistics -v`
Expected: FAIL —— `domain.event_study` 不存在。

实现顺序，每步先红后绿：
1. `EventWindow` + `MatchedControlSpec` + `EventStudySpec`（纯校验，无数学）；
2. `abnormal_returns()` —— market-adjusted 先做，market model 次之；
3. `cumulative_abnormal_return()`；
4. clustered SE（按事件日聚类）；
5. block bootstrap SE —— **复用 `block_bootstrap_mean_ci()`**，
   把每个事件日的平均 CAR 作为一个 `TimeSeriesObservation`；
6. matched controls；
7. FDR —— **复用 `benjamini_hochberg()`**，不重写。

第 5 步是复用点：`block_bootstrap_mean_ci` 的输入是
`Sequence[TimeSeriesObservation]`，而 `TimeSeriesObservation` 已经强制
`strict_historical` 必须 `pit_verified` 且 `availability_enforced`。
把事件日聚类后的 CAR 装进它，治理约束自动继承。

- [ ] **Step 5: 写 Gate 红测 —— 六个 key 缺一不可**

```python
# platform/tests/test_event_study_gate.py
"""The event validation policy, exercised rather than quoted.

validation/gates.py already declares six requirements for ResearchKind.EVENT.  This
plan implements them; this file asserts that a run missing any one of them fails the
policy, so the gate cannot pass by having five of six.
"""

from __future__ import annotations

import unittest

from a_share_platform.validation.gates import ResearchKind, policy_for

REQUIRED = (
    "event_time_integrity",
    "abnormal_return_model",
    "event_window_car",
    "clustered_or_bootstrap_se",
    "matched_controls",
    "overlap_and_multiple_testing",
)


class EventPolicyTest(unittest.TestCase):
    def test_the_policy_requires_exactly_these_six_items(self) -> None:
        policy = policy_for(ResearchKind.EVENT)
        self.assertEqual(tuple(item.key for item in policy.requirements), REQUIRED)

    def test_each_missing_item_is_reported_individually(self) -> None:
        policy = policy_for(ResearchKind.EVENT)
        for key in REQUIRED:
            with self.subTest(missing=key):
                completed = set(REQUIRED) - {key}
                self.assertEqual(policy.missing(completed), (key,))

    def test_a_complete_run_has_nothing_missing(self) -> None:
        policy = policy_for(ResearchKind.EVENT)
        self.assertEqual(policy.missing(set(REQUIRED)), ())

    def test_an_unrelated_completed_key_does_not_satisfy_a_requirement(self) -> None:
        """Completing rank_ic does not complete matched_controls."""
        policy = policy_for(ResearchKind.EVENT)
        completed = (set(REQUIRED) - {"matched_controls"}) | {"rank_ic"}
        self.assertEqual(policy.missing(completed), ("matched_controls",))


class RunnerGateTest(unittest.TestCase):
    def test_the_runner_reports_which_of_the_six_it_completed(self) -> None:
        ...

    def test_a_bootstrap_se_satisfies_clustered_or_bootstrap_se(self) -> None:
        """The key names both methods; either one completes it."""
        ...

    def test_an_unavailable_car_does_not_complete_event_window_car(self) -> None:
        """A requirement is completed by a result, not by having attempted it."""
        ...

    def test_the_gate_result_is_recorded_even_when_it_fails(self) -> None:
        """A failed validation report must stay visible, per AGENTS.md."""
        ...
```

- [ ] **Step 6: 写更正触发下游 Review 的红测（ADR-0008 决策 4）**

```python
# platform/tests/test_downstream_review.py
"""A correction appends a version and invalidates what depended on the old one.

ADR-0008 decision 4: "correction/retraction 不覆盖旧版本，必须追加新版本并触发下游
Review."  Both halves matter and the second is the one that gets skipped.

The concrete case is in the repository already.  五粮液 2025 Q1 operating revenue was
first reported as 36,940,356,116.35 CNY in document 1223311586 and restated to
17,085,765,657.95 CNY in document 1225273125 — a factor of 2.16.  Any claim, event
impact or InvestmentView built on the first number was wrong for a year, and the
dangerous repair is to update the number in place: the old conclusions then look
correct while having been reached from different inputs, and nobody can reconstruct
what was believed on 2025-05-01.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from a_share_platform.application.downstream_review import (
    DownstreamReviewReason,
    DownstreamReviewService,
)

ORIGINAL = "document-version:cninfo:000858:2025-q1:0"   # external 1223311586
CORRECTED = "document-version:cninfo:000858:2025-q1:1"  # external 1225273125
ORIGINAL_REVENUE = Decimal("36940356116.35")
CORRECTED_REVENUE = Decimal("17085765657.95")


class CorrectionInvalidatesTest(unittest.TestCase):
    def test_a_correction_creates_a_review_request_for_each_dependent_claim(self) -> None:
        service = DownstreamReviewService(_repository_with_claims_citing(ORIGINAL, count=3))
        requests = service.on_document_corrected(
            superseded_document_version_id=ORIGINAL,
            correcting_document_version_id=CORRECTED,
        )
        self.assertEqual(len(requests), 3)
        self.assertTrue(
            all(item.reason is DownstreamReviewReason.SOURCE_CORRECTED
                for item in requests)
        )

    def test_the_old_claim_is_not_modified(self) -> None:
        """What we believed then stays readable, or the audit trail is fiction."""
        repository = _repository_with_claims_citing(ORIGINAL, count=1)
        before = repository.claims()[0]
        DownstreamReviewService(repository).on_document_corrected(
            superseded_document_version_id=ORIGINAL,
            correcting_document_version_id=CORRECTED,
        )
        self.assertEqual(repository.claims()[0], before)

    def test_the_old_claim_is_marked_pending_review_not_deleted(self) -> None:
        ...

    def test_a_dependent_investment_view_is_flagged_and_left_intact(self) -> None:
        """A new view is a new view_id; the old one is history, not a draft."""
        ...

    def test_no_numeric_value_is_propagated_into_the_old_view(self) -> None:
        """The failure mode: 36.9bn silently becomes 17.1bn in a frozen artifact."""
        ...

    def test_a_retraction_invalidates_without_offering_a_replacement_value(self) -> None:
        """A withdrawn document has no corrected number to substitute."""
        ...

    def test_review_requests_are_idempotent_per_dependency(self) -> None:
        """Re-processing the same correction must not create duplicate requests."""
        ...

    def test_a_correction_with_no_dependents_creates_no_requests_and_says_so(self) -> None:
        ...


class TransitiveInvalidationTest(unittest.TestCase):
    def test_an_event_impact_built_on_an_invalidated_claim_is_also_flagged(self) -> None:
        """Invalidation follows the citation graph, not one hop."""
        ...

    def test_a_supply_chain_edge_citing_the_corrected_document_is_flagged(self) -> None:
        ...

    def test_a_signal_snapshot_containing_a_flagged_view_is_reported(self) -> None:
        """P-5 consumes views; a correction upstream must surface downstream."""
        ...

    def test_the_flag_does_not_change_any_frozen_artifact(self) -> None:
        """The artifact is the record of what was frozen.  It is never edited."""
        ...
```

- [ ] **Step 7: 实现 `DownstreamReviewService`**

它是纯编排：给定被更正的 `document_version_id`，沿 citation 图找出全部依赖对象
（claims → impacts → views → snapshots → supply chain edges），
对每个生成一条 `DownstreamReviewRequest` 并写入 append-only 表。

**它不修改任何被依赖对象。** 唯一的写是新增 review request 与
在依赖对象上追加一条"pending review"标记（作为独立行，不是 UPDATE 字段）。

- [ ] **Step 8: 写 `ExpectedReturnCompilerV1` 红测 —— V0 的守卫不许放宽**

```python
# platform/tests/test_event_view_compiler.py
"""A second compiler version that may quantify the event component.

ExpectedReturnCompilerV0 contains one line that this plan must not touch:

    if event.status is not InvestmentComponentStatus.UNAVAILABLE:
        raise ValueError("event must remain unavailable before P8")

Relaxing it would let every existing call site start producing event contributions
the moment this module lands, including runs whose event chain was never reviewed.
So V0 keeps refusing and V1 is a new compiler with its own version id, exactly as
P-6 adds append_active() beside append_baseline() rather than loosening it.

V1 will only quantify the event component when the contribution traces to reviewed
evidence.  Every other case leaves it unavailable with a reason, which is the same
answer V0 gives — the difference is that V1 can say why it is not unavailable.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from a_share_platform.domain.event_view_compiler import ExpectedReturnCompilerV1
from a_share_platform.domain.expected_return import ExpectedReturnCompilerV0
from a_share_platform.domain.investment_view import (
    InvestmentComponent,
    InvestmentComponentStatus,
)


class V0RegressionTest(unittest.TestCase):
    def test_v0_still_refuses_a_quantified_event_component(self) -> None:
        """The guard that keeps P8 from leaking into every existing caller."""
        with self.assertRaisesRegex(ValueError, "event must remain unavailable"):
            ExpectedReturnCompilerV0().compile(_request_with_quantified_event())

    def test_v0_and_v1_are_different_model_version_ids(self) -> None:
        ...


class V1CitationGateTest(unittest.TestCase):
    def test_an_event_contribution_without_evidence_ids_is_refused(self) -> None:
        """InvestmentComponent already requires evidence for a quantified value;
        this asserts the event component is not an exception."""
        with self.assertRaises(ValueError):
            InvestmentComponent(
                name="event",
                status=InvestmentComponentStatus.QUANTIFIED,
                expected_return_contribution=Decimal("0.012"),
                evidence_ids=(),
            )

    def test_an_agent_claim_without_a_valid_citation_cannot_be_evidence(self) -> None:
        """Second gate for the same rule, at the compiler rather than the runtime."""
        ...

    def test_an_unreviewed_event_study_cannot_quantify_the_component(self) -> None:
        ...

    def test_a_pending_review_flag_on_the_evidence_blocks_quantification(self) -> None:
        """After a correction, the contribution is unavailable until re-reviewed."""
        ...

    def test_an_opinion_or_rumor_claim_cannot_become_a_contribution(self) -> None:
        """Sentiment polarity alone is not event alpha — SPEC-029 acceptance."""
        ...

    def test_an_ambiguous_entity_link_blocks_a_security_level_contribution(self) -> None:
        ...

    def test_a_hypothesis_supply_chain_edge_contributes_nothing(self) -> None:
        ...


class V1UnavailableReasonTest(unittest.TestCase):
    def test_an_unavailable_event_component_carries_a_specific_reason(self) -> None:
        """"not implemented" and "implemented, no qualified evidence" are different
        facts pointing at different work."""
        ...

    def test_an_unavailable_component_carries_no_number(self) -> None:
        """InvestmentComponent already enforces this; assert it for the event slot."""
        with self.assertRaises(ValueError):
            InvestmentComponent(
                name="event",
                status=InvestmentComponentStatus.UNAVAILABLE,
                expected_return_contribution=Decimal("0"),
                status_reason="no reviewed event evidence",
            )

    def test_zero_contribution_is_not_used_to_mean_unknown(self) -> None:
        """SPEC-030: 未完成的事件分项不得伪装成零影响."""
        ...


class V1IncrementalValueTest(unittest.TestCase):
    """Needs P-5: 'is it worth anything' is a question about a portfolio."""

    def test_incremental_value_is_measured_after_costs(self) -> None:
        ...

    def test_a_gross_positive_net_negative_event_contribution_is_refused(self) -> None:
        """Event signals are high-turnover by construction; costs decide."""
        ...

    def test_incremental_value_is_unavailable_without_a_cost_model_version(self) -> None:
        ...
```

- [ ] **Step 9: 实现 `ExpectedReturnCompilerV1`**

**不修改 `domain/expected_return.py`。** 新模块 `domain/event_view_compiler.py`
定义 `ExpectedReturnCompilerV1`，其 `compile()` 接受同一个
`ExpectedReturnCompileRequest`（`_CORE_COMPONENTS` 已含 `"event"`，不需改），
但把 V0 的 event 守卫替换为一条更严格的资格检查：

```text
event 分项可以 QUANTIFIED 当且仅当：
  1. 每个 evidence_id 解析到一条 AgentClaim 或 EventStudyResult；
  2. 每条 AgentClaim 的 claim_kind ∈ {FACT, INFERENCE}（OPINION / RUMOR 不行）；
  3. 每条 AgentClaim 的全部 citations 校验通过；
  4. 关联 EventStudyResult 的 ResearchKind.EVENT policy.missing() 为空；
  5. 关联的 PromotionReview 已通过且 scope 覆盖当前用途；
  6. 没有任何 evidence 带 pending review 标记；
  7. 成本后增量价值为正（需 P-5 的 cost model version）。
否则 UNAVAILABLE + 具体 reason。
```

七条里任一不满足 → `UNAVAILABLE`，且 reason 必须指出**是哪一条**。
"unavailable" 而不说原因，会让使用者无法判断是"没数据"还是"没通过"。

- [ ] **Step 10: 独立库交叉验证**

在 `validation/statistical_crosscheck.py` 新增 `cross_check_event_car()`，
照现有 `cross_check_newey_west_mean()` 的结构（`_load_reference` / `_version` /
`_unavailable_report` / `_comparison_report` 已存在，**复用它们**）。

输入必须是**与主统计器完全相同**的 CAR 序列 —— 与 P-2 同一条纪律。
statsmodels 缺失时返回 `unavailable`，**不返回 agreement**。

- [ ] **Step 11: 用真实小样本跑一次，如实记录**

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.event_study \
  --study-id event-study:earnings-preview --category earnings
```

**预期真实结果：`unavailable`，原因是事件数低于 `minimum_events`。**
P3-W04c 只有 4 家公司 8 份文档，且它们是财报与更正而非一个事件类型的横截面。
把真实输出原样抄进 Evidence。**不要降低 `minimum_events` 来让它出数** ——
那正是 `CLAUDE.md` §11 列的"为追求通过而改变冻结窗口、样本、阈值或过滤规则"。

- [ ] **Step 12: migration `0043` 与提交（本 Task 两个 commit）**

第一个 commit：统计与 Gate。

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/domain/event_study.py \
  platform/src/a_share_platform/domain/event_impact.py \
  platform/src/a_share_platform/application/event_study_runner.py \
  platform/src/a_share_platform/validation/statistical_crosscheck.py \
  platform/tests/test_event_study_statistics.py \
  platform/tests/test_event_study_gate.py
git commit -m "feat: measure event impact with dependence-aware standard errors

An event study looks like a large-sample problem and is not.  Earnings previews
cluster into two weeks of the year, so hundreds of events share one calendar day and
therefore one market shock.  A [-5, +20] window spans 26 sessions, so consecutive
events for the same issuer overlap.  A policy event hits every firm in an industry
simultaneously.  Under i.i.d. standard errors the standard error is understated by
roughly the square root of the events per day: a hundred events on one day turns a t
of 0.3 into a t of 3.0.

That is not a precision problem.  It is manufactured significance, and in the output
it is indistinguishable from a real result — which is why StandardErrorMethod has no
IID member.  The choice is between clustering by event date and a block bootstrap,
and the result reports the number of clustered dates and the maximum events on any
one date so a reader can judge the effective sample rather than the nominal one.
Seventy events on two days is two observations, and the runner says so.

The same argument applies across event types.  Twelve categories times three windows
is thirty-six tests, and at alpha 0.05 that is 1.8 expected false positives — enough
to produce 'two significant event types' from noise.  So the family goes through the
existing benjamini_hochberg, whose refusal to proceed on a partially populated family
is reused rather than worked around, and the family id and version are frozen before
any result is looked at.

The block bootstrap reuses block_bootstrap_mean_ci by wrapping each event date's mean
CAR as a TimeSeriesObservation, which also inherits that type's rule that
strict_historical inputs must be pit_verified with availability enforced.  The
estimation window must end before the event window starts, because fitting alpha and
beta across the event absorbs the very abnormal return being measured.

Run on the real sample this returns unavailable: four companies and eight filings is
not a cross-section.  Lowering minimum_events to produce a number would be the
canonical way to fake this result, so the honest unavailable is the recorded outcome."
```

第二个 commit：更正 Review 与 View v2。

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
git diff --check
cd .. && git add platform/src/a_share_platform/application/downstream_review.py \
  platform/src/a_share_platform/domain/event_view_compiler.py \
  platform/migrations/0043_p8_event_study_and_reviews.sql \
  platform/tests/test_downstream_review.py \
  platform/tests/test_event_view_compiler.py \
  docs/28-p8-events-agents-evidence.md
git commit -m "feat: let a correction invalidate downstream conclusions instead of updating them

ADR-0008 decision 4 has two halves and the second is the one that gets skipped: a
correction appends a version, and it triggers a downstream Review.  Appending alone
is not enough, because the conclusions built on the old version are still sitting
there looking valid.

The case is already in this repository.  五粮液 2025 Q1 operating revenue was first
reported as 36,940,356,116.35 CNY in cninfo document 1223311586 and restated to
17,085,765,657.95 CNY in 1225273125 — a factor of 2.16.  The tempting repair is to
update the number where it is stored, and it is the worst available option: every
conclusion reached from the old figure then reads as correct, and the question 'what
did we believe on 2025-05-01' becomes unanswerable.  Worse, the frozen artifact and
the database would disagree, and the artifact is the one that is true.

So nothing is updated.  The correction walks the citation graph, flags every
dependent claim, impact, view, snapshot and supply-chain edge as pending review, and
writes an append-only review request per dependency.  The old objects are byte-for-
byte unchanged and remain readable.  A new conclusion is a new identifier, not a
mutation of the old one.  Invalidation is transitive because citations are: a view
built on a claim built on the corrected document is two hops away and equally wrong.

The event component of an InvestmentView arrives through a second compiler rather
than by relaxing the first.  ExpectedReturnCompilerV0 refuses a quantified event
component outright, and that line stays: relaxing it would enable event contributions
for every existing call site the moment this module landed, including runs whose
event evidence was never reviewed.  V1 is a separate version with a seven-condition
gate — resolvable evidence, claim kinds excluding opinion and rumour, valid
citations, a complete EVENT validation policy, an approving review in scope, no
pending-review flag, and positive value after costs.  Failing any one yields
unavailable naming which one, because 'no data' and 'not approved' point at
different work.  An unavailable component still carries no number: SPEC-030 is
explicit that an incomplete event contribution must not masquerade as zero impact."
```

---

### Task 6: API、PUI-07 三页与通知 adapter

对应 Step 07 Task 6：「实现 Document/Event/Claim/Impact/SupplyChain/AgentRun 只读/受权写 API；
前端 badges、drill-down、invalidators、pending verification；通知 adapter 只发送 frozen
Artifact 链接。Events、Cases、Agents 和 Security event enhancement 的页面交付按 PUI-07 执行；
Design Parity 不提升引用资格，缺引用或 schema invalid 的 Agent 输出仍必须隔离。」

**Files:**
- Modify: `platform/src/a_share_platform/api/app.py`（新增 7 个只读端点 + 1 个受控写）
- Modify: `platform/src/a_share_platform/api/schemas.py`
- Create: `platform/src/a_share_platform/application/event_workspace.py`
- Create: `platform/src/a_share_platform/ports/notifications.py`
- Create: `platform/src/a_share_platform/adapters/memory/notifications.py`
- Modify: `platform/src/a_share_platform/application/desk_projection.py`（`_event_feed`）
- Create: `platform/frontend/src/features/events/EventsScreen.tsx`
- Create: `platform/frontend/src/features/events/EventEvidenceDrawer.tsx`
- Create: `platform/frontend/src/features/events/AgentRunPanel.tsx`
- Create: `platform/frontend/src/features/events/eventTypes.ts`
- Modify: `platform/frontend/src/pages/WorkspacePage.tsx`（`events` / `agents` tab）
- Create: `platform/scripts/verify_events_browser.py`
- Test: `platform/tests/test_event_workspace_projection.py`
- Test: `platform/tests/test_event_api.py`
- Test: `platform/tests/test_notifications.py`
- Test: `platform/frontend/src/features/events/EventsScreen.test.tsx`
- Test: `platform/frontend/src/features/events/AgentRunPanel.test.tsx`

**Interfaces:**
- Consumes: Task 1–5 全部；已有 `Envelope` / `fixed_read_context` / `PermissionPolicy` /
  `WorkspaceState` 六态 / `EvidenceDrawer` / `DeskSection`
- Produces:
  ```text
  GET  /api/events                             # 事件流，带 trust 与 impact 状态
  GET  /api/events/{event_id}
  GET  /api/events/{event_id}/documents         # 权威版本 + 全部重复 + 差异
  GET  /api/events/{event_id}/claims            # 只返回 citation 校验通过的
  GET  /api/events/conflicts                    # 待人工确认队列
  GET  /api/supply-chain/edges
  GET  /api/agents/runs                          # 含隔离输出的 hash 与原因
  POST /api/events/{event_id}/verification       # 受控写：人工确认，需 REVIEWER
  ```

- [ ] **Step 1: 先读现有前端与 Desk 的真实状态**

```bash
cd platform
grep -n "events:\|agents:" frontend/src/pages/WorkspacePage.tsx
grep -n "_event_feed" -A10 src/a_share_platform/application/desk_projection.py
grep -n "EventFeedSection" -A8 frontend/src/features/desk/deskSections.tsx
grep -n "export type WorkspaceStateKind" -A12 frontend/src/components/WorkspaceState.tsx
```

已核实的现状：
- `WorkspacePage.tsx` 的 `activationReasons` 有 `events` 与 `agents` 两条文案；
- `desk_projection.py` 的 `_event_feed()` 返回 blocker
  `P8_EVENT_FEED_NOT_IMPLEMENTED`，reason 是
  「事件与公告流能力属 P8，尚未实现；不展示未经证据链验证的事件。」；
- `deskSections.tsx` 的 `EventFeedSection` 注释写着
  「P8 capability; unavailable until the event evidence chain exists」；
- `WorkspaceStateKind` 六态已定义：`loading` / `error` / `empty` / `partial` /
  `unavailable` / `ready`（`blocked` 是 deprecated 别名，新代码用 `unavailable`）。

本 Task 把 `_event_feed()` 的 blocker code 从
`P8_EVENT_FEED_NOT_IMPLEMENTED` 改为 `P8_EVENT_FEED_NO_QUALIFIED_INPUT`
**当且仅当**能力已实现而数据为空。这两个 code 是不同事实，指向不同工作 ——
与 P-5 对 Desk portfolio 分区的处理同一模式。

- [ ] **Step 2: 写后端投影红测 —— 页面不重算任何东西**

```python
# platform/tests/test_event_workspace_projection.py
"""The Events projection is computed on the server and displayed unchanged.

The browser must not decide which of two documents is authoritative, whether a
citation is valid, or whether a claim may be shown as a fact.  Each of those is a
governed decision made in Tasks 1 to 5, and recomputing it in TypeScript would create
a second answer that no audit trail covers.

The projection therefore ships verdicts and reasons, not raw inputs.
"""

from __future__ import annotations

import unittest

from a_share_platform.application.event_workspace import EventWorkspaceService


class ProjectionShapeTest(unittest.TestCase):
    def test_each_row_carries_the_authoritative_document_and_the_duplicates(self) -> None:
        ...

    def test_each_row_carries_its_trust_state_verbatim(self) -> None:
        """normalized_current must not be rendered as verified anywhere."""
        ...

    def test_a_conflict_row_has_no_authoritative_document(self) -> None:
        """The prototype's 冲突事实 BLOCKER card counts exactly these."""
        ...

    def test_claims_without_a_valid_citation_are_absent_from_the_projection(self) -> None:
        """Quarantined output is reachable through the Agents view, not the event."""
        ...

    def test_the_impact_column_distinguishes_unknown_from_zero(self) -> None:
        """待评估 and 未进入 View are different states, as the prototype shows."""
        ...

    def test_the_counts_come_from_the_repository_not_from_a_constant(self) -> None:
        """The prototype's 128 / 26 / 9 / 0 are design fixtures."""
        ...

    def test_entered_view_count_is_zero_with_an_explicit_reason(self) -> None:
        """The one prototype number that will match reality — but the reason must
        be the real blocker, not a hardcoded zero."""
        projection = EventWorkspaceService(_empty_repositories()).project()
        self.assertEqual(projection.entered_view_count, 0)
        self.assertIsNotNone(projection.entered_view_reason)

    def test_an_empty_store_projects_empty_not_unavailable(self) -> None:
        """Empty means the capability works and holds no rows; they differ."""
        ...

    def test_a_missing_store_projects_unavailable_with_a_reason(self) -> None:
        ...


class NoRuntimeFixtureTest(unittest.TestCase):
    def test_the_projection_contains_no_prototype_identifier(self) -> None:
        """EVT-101..112 and 贵州茅台 are Figma fixtures; none is in the real sample."""
        projection = EventWorkspaceService(_empty_repositories()).project()
        rendered = repr(projection)
        for fixture in ("EVT-1", "贵州茅台", "宁德时代", "美的集团", "招商银行"):
            with self.subTest(fixture=fixture):
                self.assertNotIn(fixture, rendered)
```

- [ ] **Step 3: 写 API 红测 —— 只读为默认，写需权限**

```python
# platform/tests/test_event_api.py
"""Event endpoints: GET by default, one controlled write.

The single write is human verification of a conflict — the prototype's 请求人工确认
action.  It needs APPROVE_RESEARCH, so an agent identity cannot reach it: Role.AGENT
holds only READ_PUBLIC.
"""

from __future__ import annotations

import unittest


class ReadOnlyTest(unittest.TestCase):
    def test_every_event_endpoint_except_verification_is_get_only(self) -> None:
        ...

    def test_responses_use_the_fixed_current_research_envelope(self) -> None:
        ...

    def test_an_unconfigured_store_returns_an_empty_collection_not_a_demo_row(self) -> None:
        ...

    def test_the_evidence_endpoint_never_returns_a_body_it_may_not_redistribute(
        self,
    ) -> None:
        """Same rule W05b already applies to the disclosure drawer: governance
        metadata is public, the document body is not."""
        ...

    def test_internal_storage_uri_is_not_exposed(self) -> None:
        ...


class VerificationWriteTest(unittest.TestCase):
    def test_an_anonymous_caller_cannot_verify_a_conflict(self) -> None:
        ...

    def test_an_agent_principal_cannot_verify_a_conflict(self) -> None:
        """The agent may raise the conflict; only a human resolves it."""
        ...

    def test_a_reviewer_can_verify_and_the_decision_is_appended(self) -> None:
        ...

    def test_verification_records_who_decided_and_on_what_evidence(self) -> None:
        ...

    def test_verification_cannot_promote_a_trust_state(self) -> None:
        """Resolving a conflict says which version is authoritative.  It does not
        make a normalized_current observation pit_verified."""
        ...
```

- [ ] **Step 4: 写通知红测（ADR-0008 决策 5）**

```python
# platform/tests/test_notifications.py
"""Notifications reference frozen artifacts and restate nothing.

ADR-0008 decision 5: "通知只引用 Frozen Artifact 和许可允许的摘要/链接，不重新生成权威
数值."  A message that recomputes a number produces a second answer with no lineage,
and it is the copy the reader will act on.
"""

from __future__ import annotations

import unittest
from decimal import Decimal


class NotificationPayloadTest(unittest.TestCase):
    def test_a_payload_referencing_no_artifact_is_refused(self) -> None:
        ...

    def test_a_payload_carrying_a_numeric_conclusion_is_refused(self) -> None:
        """The whole point: the number lives in the artifact, not in the message."""
        ...

    def test_a_payload_may_carry_an_artifact_id_and_a_content_hash(self) -> None:
        ...

    def test_a_summary_from_a_no_redistribute_source_is_refused(self) -> None:
        """A licensed excerpt is not automatically a redistributable one."""
        ...

    def test_the_artifact_must_exist_before_a_notification_is_built(self) -> None:
        """Referencing an artifact id that was never frozen is a dangling promise."""
        ...

    def test_no_notification_is_sent_for_an_unavailable_result(self) -> None:
        """"We computed nothing" is not news, and sending it invites reading the
        absence as a zero."""
        ...
```

- [ ] **Step 5: 实现后端投影、API 与通知 port**

`event_workspace.py` 只读投影，**零算术**。
`ports/notifications.py` 定义 `NotificationSink` Protocol；
`adapters/memory/notifications.py` 是唯一实现（记录发送，不真发）。
**不接任何真实通知渠道** —— Step 07 已把它列为 D2。

- [ ] **Step 6: 写前端红测 —— Events 页**

```tsx
// platform/frontend/src/features/events/EventsScreen.test.tsx
/**
 * The Events screen renders server verdicts and never derives one.
 *
 * The Figma frame draws twelve events for four companies that are not in the real
 * sample, plus counts of 128 / 26 / 9 / 0.  All of it is labelled DESIGN FIXTURE in
 * the frame itself.  These tests assert the runtime shows the server's rows, the
 * server's counts and the server's reasons — including when all of those are empty.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { EventsScreen } from './EventsScreen'

describe('EventsScreen', () => {
  it('renders the six-state contract from the projection', () => {
    // unavailable with the real blocker reason, not a placeholder sentence
  })

  it('shows the trust state verbatim beside every row', () => {
    // 待确认 must not be rendered as 高
  })

  it('shows a conflict row without an authoritative document', () => {
    // and links to the 请求人工确认 action rather than picking a side
  })

  it('never displays an agent claim as an authoritative value', () => {
    // an INFERENCE renders with its confidence and its citation, never bare
  })

  it('does not render a quarantined agent output as a claim', () => {
    // it is reachable in the Agents view with its status reason
  })

  it('distinguishes 待评估 from 未进入 View in the impact column', () => {
  })

  it('renders zero entered-view count with the server reason', () => {
  })

  it('contains no prototype identifier', () => {
    // EVT-101, 贵州茅台, 宁德时代, 美的集团, 招商银行
  })

  it('does not sort or re-rank rows in the browser', () => {
    // the projection order is the governed order
  })
})
```

```tsx
// platform/frontend/src/features/events/AgentRunPanel.test.tsx
/**
 * The Agents panel shows what the agent did, including what was rejected.
 *
 * The prototype's status card says it plainly: Agent 摘要 ATTENTION
 * 只解释，不拥有数值和时间真值.  The panel therefore always shows the five failure
 * statuses distinctly and always shows the permanent boundary — the agent has no
 * write, approval or trading authority — rather than a "not yet enabled" note.
 */
describe('AgentRunPanel', () => {
  it('shows the five non-success statuses distinctly', () => {
    // schema_invalid / citation_invalid / budget_exceeded / deadline_exceeded /
    // tool_denied each render their own reason
  })

  it('shows the quarantined output hash without the output text', () => {
  })

  it('states the permanent authority boundary, not a temporary one', () => {
    // 'Agent 永远没有交易权限' survives the runtime landing
  })

  it('shows the model, prompt hash, tool allowlist and budget for each run', () => {
  })

  it('shows unavailable rather than empty when no provider is configured', () => {
    // no provider is authorised; that is a real state, not an error
  })
})
```

- [ ] **Step 7: 实现前端并接线 `WorkspacePage`**

替换 `activationReasons.events` 为真实组件；`agents` tab 接 `AgentRunPanel`。
**`agents` 那句「Agent runtime 尚未启用，且 Agent 永远没有交易权限」中的后半句
必须以永久边界的形式保留在页面上**，前半句随 runtime 落地而变。

复用 `WorkspaceState` 六态、`EvidenceDrawer`（已支持
`unavailable` / `normalized_current` / `pit_verified` 三态）、`NumericCell`。
**不新建设计系统组件。**

- [ ] **Step 8: 四视口浏览器验收**

```python
# platform/scripts/verify_events_browser.py
"""PUI-07 Events browser verification against the real runtime.

Not part of the test suite: the four-viewport acceptance run required by
`docs/plans/track-00-prototype-runtime-delivery.md`.  Copied from
verify_desk_browser.py (177 lines, already proven) with the event surfaces and the
prototype fixtures this page must never show.
"""

from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

URLS = (
    ("events", "http://127.0.0.1:5173/research?tab=events"),
    ("cases", "http://127.0.0.1:5173/research?tab=watchlists-cases"),
    ("agents", "http://127.0.0.1:5173/system?tab=agents"),
)
VIEWPORTS = (("1440", 1440, 900), ("1024", 1024, 768),
             ("768", 768, 1024), ("320", 320, 640))
# Figma sample values that must never reach the runtime.
DESIGN_FIXTURES = (
    "EVT-101", "EVT-112", "贵州茅台", "600519", "宁德时代", "300750",
    "美的集团", "000333", "招商银行", "600036",
    "128", "公告31 · 新闻97", "3 组来源说法不一致",
)
# Text that must be present because it is a permanent boundary, not a placeholder.
REQUIRED_TEXT = ("无引用", "InvestmentView")
```

必须逐视口检查：`document.scrollWidth === document.clientWidth`、
无右侧裁切、控制台无 error/warning、正常重载无 4xx/5xx、
键盘可达与焦点可见、`DESIGN_FIXTURES` 一个都不出现。

- [ ] **Step 9: Desk 事件分区状态按真实数据判定**

```python
def test_event_feed_blocker_changes_from_not_implemented_to_no_qualified_input(
    self,
) -> None:
    """Two different facts pointing at two different pieces of work."""
    ...

def test_event_feed_is_ready_only_when_a_reviewed_event_exists(self) -> None:
    ...
```

- [ ] **Step 10: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
PYTHON_BIN=../.venv/bin/python npm --prefix frontend run generate:api
npm --prefix frontend test -- --run
npm --prefix frontend run lint
npm --prefix frontend run build
.venv/bin/python scripts/verify_events_browser.py
git diff --check
cd .. && git add platform/src/a_share_platform/api/app.py \
  platform/src/a_share_platform/api/schemas.py \
  platform/src/a_share_platform/application/event_workspace.py \
  platform/src/a_share_platform/application/desk_projection.py \
  platform/src/a_share_platform/ports/notifications.py \
  platform/src/a_share_platform/adapters/memory/notifications.py \
  platform/frontend/src/features/events/ \
  platform/frontend/src/pages/WorkspacePage.tsx \
  platform/frontend/src/api/ \
  platform/scripts/verify_events_browser.py \
  platform/tests/test_event_workspace_projection.py \
  platform/tests/test_event_api.py \
  platform/tests/test_notifications.py
git commit -m "feat: surface events, cases and agent runs as server-owned projections

Every decision the Events page displays was made upstream: which of two documents is
authoritative, whether a citation resolves, whether a claim may appear as a fact.
Recomputing any of them in the browser would produce a second answer with no lineage,
and the browser's copy is the one a reader acts on.  So the projection ships verdicts
and reasons, the page renders them, and a test asserts the rows are not re-sorted
client-side because even ordering is a governed output here.

The prototype's twelve events belong to four companies that do not appear in the real
sample, and its counts of 128 new items, 26 clusters and 9 pending confirmations are
labelled DESIGN FIXTURE inside the frame.  The browser verification treats all of
them as strings that must never render.  The one prototype number that will match is
the zero for events entered into a view, and even that is read from the repository
with a real blocker reason rather than written as a constant.

The desk event section changes its blocker from P8_EVENT_FEED_NOT_IMPLEMENTED to
P8_EVENT_FEED_NO_QUALIFIED_INPUT.  Those are different facts and they point at
different work: the first meant write the pipeline, the second means the pipeline runs
and no reviewed event exists yet.

The Agents panel keeps the sentence about the agent never holding trading authority
even though the runtime has landed, because that half of the message was never a
placeholder.  It also shows the five failure statuses separately and shows the
quarantined output as a hash without its text, since output rejected for an invalid
citation is still evidence about the agent and still not evidence about the company.

Notifications reference a frozen artifact and restate nothing.  A payload carrying a
numeric conclusion is refused outright, and no notification is sent for an unavailable
result — 'we computed nothing' invites reading the absence as a zero."
```

---

### Task 7: Evidence、Gate 状态与明确否认

**Files:**
- Modify: `docs/28-p8-events-agents-evidence.md`
- Modify: `docs/plans/step-07-p8-events-agents-supply-chain.md`（Task 1–6 状态）
- Modify: `docs/plans/track-00-prototype-runtime-delivery.md`（PUI-07 状态）
- Modify: `docs/22-prototype-runtime-gap-audit.md`（新增一节，**不改 §5 原表**）
- Modify: `docs/14-data-source-catalog-and-agent-routing.md`（逐源登记最终状态）

- [ ] **Step 1: 记录真实红绿测**

每个 Task 的真实失败文本与转绿结果。**不编造命令输出。**
特别注意两个"一开始就绿"的文件（`test_disclosure_ledger_regression.py`、
`test_agent_authority_boundary.py`）—— 它们是回归守卫，
Evidence 要说明为什么它们不是"没写红测"。

- [ ] **Step 2: 记录真实事件链数字**

`docs/28-p8-events-agents-evidence.md` 结构必须是：

```text
## 1. 绑定决策（ADR-0008 五条逐字抄录）
## 2. 逐源许可登记结果（每源一行，含结论与理由）
## 3. 红绿测记录（含两个回归守卫的说明）
## 4. 真实事件链计数（document version / cluster / conflict / claim / edge / study）
## 5. Agent 运行统计（成功 / 五种失败各自计数 / 隔离输出数）
## 6. Event Study 真实结果（含 unavailable 的原因原文）
## 7. 更正 Review 真实记录（五粮液链的实际下游影响计数）
## 8. 独立库交叉验证一致性
## 9. 原型差异清单（含 224/280 px 侧栏差异）
## 10. 三轴状态（Design Parity / Runtime Product / Domain Capability）
## 11. 未完成项与范围限制
## 12. 明确否认
```

第 4 与第 6 节的真实数字**很可能是小的或为零**。如实记录。
特别是：若逐源登记结论是"只有官方披露一源"，那么 §4 的
`duplicate_document_version_ids` 总数为 0，而这需要写清楚
**去重能力已实现但缺少第二个来源来行使它**，不是去重没做。

- [ ] **Step 3: 写明确否认声明**

必须逐字包含：

> **P8 完成不使任何事件信号有效。**
>
> 本 plan 交付的是事件证据链、受治理 Agent 运行时、供应链图与事件研究**引擎**。
> 引擎正确不等于结论有效。具体地：
>
> 1. 全部输入为 `normalized_current`，**不是 `pit_verified`**，
>    因此任何事件研究结果都不是可信历史证据；
> 2. 真实文档样本为 4 家公司 8 份官方 PDF，**不构成任何事件类型的横截面**；
>    事件研究的真实结果为 `unavailable`，这是被验收的结果；
> 3. 新闻、研报与搜索来源**未获逐源许可批准**，因此多源去重能力
>    在真实数据上未被行使；
> 4. **未调用任何真实 LLM provider**；Agent 能力全部在 fake model port 上验证。
>    接入真实 provider 需要用户就成本与来源许可给出新的明确授权；
> 5. `ExpectedReturnCompilerV1` 的 event 分项在真实运行时保持 `unavailable`，
>    因为七条资格条件无一具备；
> 6. 供应链图在真实运行时为空；`AMBIGUOUS_PATHS` 检测能力已实现但无真实边可测；
> 7. 情绪正负分**不构成事件 Alpha**（SPEC-029 验收），本 plan 未实现情绪评分，
>    也不打算以它替代 AR/CAR；
> 8. **P2、P4、P5、P6、P8 Gate 全部未通过** —— 本 plan 不改变任何一条；
> 9. `ResearchKind.EVENT` 的六项要求已**实现**，但在真实数据上
>    `policy_for(ResearchKind.EVENT).missing(...)` 仍为非空；
> 10. 本 plan **不授权**任何真实账户操作，也不授权向任何第三方模型
>     发送受限来源正文。

- [ ] **Step 4: 提交**

```bash
cd /Users/casiezhou/personal/Quantamental
git add docs/28-p8-events-agents-evidence.md \
  docs/plans/step-07-p8-events-agents-supply-chain.md \
  docs/plans/track-00-prototype-runtime-delivery.md \
  docs/22-prototype-runtime-gap-audit.md \
  docs/14-data-source-catalog-and-agent-routing.md
git commit -m "docs: record P8 evidence separating a working event chain from a valid event signal

The most useful numbers in this document are the small ones and the zeros, and they
need their reasons attached or they will be misread twice over.

Duplicate document versions total zero, and that is not because deduplication was
skipped.  It is because the per-source licence registration produced exactly one
approved source, so there is no second version of any event to deduplicate.  The
capability is tested and unexercised, which is a different state from untested — and
it is the licence registry, not the code, that unblocks it.

The event study returns unavailable.  Four companies and eight filings is a
correction-chain sample, not a cross-section, and lowering minimum_events to produce
a number would be the textbook way to fake this result.  The recorded outcome is the
refusal.

No LLM provider was called and no LLM SDK is installed, which a test asserts.  Every
agent behaviour — deny-by-default tools, five distinct failure statuses, citation
validation against the document, the derived retention ceiling — is proven against a
deterministic fake.  Choosing a provider is a decision about token cost and about
whether a source licence permits sending its text to a third party, and neither is
this plan's to make.

Two test files pass on their first run, and the evidence says why rather than leaving
it looking like missing red tests.  Both are regression guards over contracts that
already worked: the disclosure ledger's refusal to persist a metadata-only payload,
and Role.AGENT holding exactly one permission.  Their job is to fail when someone
later widens them.

The denial section states the thing this document exists to prevent someone
concluding: a correct engine is not a valid conclusion.  P8 delivers an auditable
document-to-event-to-claim-to-impact chain and an event study that handles clustering
and multiple testing.  It says nothing whatsoever about whether any event carries
information, and no gate moves."
```

---

## 完成定义

1. `DocumentVersion` 支持三种 body disposition，许可决定路径，
   `derived_text_retention_policy` 不得超过来源 retention（Task 1）；
2. `DisclosureLedger` 的 `metadata_only` 拒绝与 `OfficialDisclosure`
   四条修订链不变量有回归守卫且通过（Task 1）；
3. 去重返回权威版本 + 全部重复 + 逐字段差异；同权威等级返回 `CONFLICT`；
   "每个输入都被记账"有不变量测试（Task 2）；
4. 实体链接的 `AMBIGUOUS` 不携带解析身份，`RESOLVED` 必须恰好一个候选（Task 2）；
5. Agent 无法把治理字段断言为 `FACT`；无有效引用的 claim 不能进入 View；
   `Role.AGENT` 八个 Permission 逐个断言（Task 3）；
6. Agent 五种失败状态可区分，隔离输出保留 hash；
   `test_no_llm_sdk_is_importable_from_the_platform` 通过（Task 3）；
7. 供应链边有半开有效区间与 staleness；`INFERRED_FROM_TEXT` 与
   `DISCLOSED_UNNAMED_SHARE` 在类型层与数据库层均不得 `ASSERTED`（Task 4）；
8. 双路径重复计数返回 `AMBIGUOUS_PATHS` 且 multiplier 为 `None`；
   空边集返回 `unavailable` 而非 0（Task 4）；
9. `StandardErrorMethod` 没有 `IID` 成员；聚类日数与单日最大事件数进入结果；
   FDR 走已有 `benjamini_hochberg()`（Task 5）；
10. 更正沿 citation 图生成 review request，被依赖对象逐字节不变，
    Frozen Artifact 不被修改（Task 5）；
11. `ExpectedReturnCompilerV0` 的 event 守卫未放宽；
    `ExpectedReturnCompilerV1` 七条资格缺一即 `unavailable` 且指明是哪一条（Task 5）；
12. 三页复用六态合同，四视口无页面级溢出，`DESIGN_FIXTURES` 零出现，
    Agents 页保留永久边界文案（Task 6）；
13. 通知只引用 Frozen Artifact，携带数值结论即拒绝（Task 6）；
14. Evidence 含真实计数、真实 `unavailable` 原因与十条明确否认（Task 7）；
15. 后端 unittest / compileall / ruff / mypy 全过；前端 Vitest / lint / build 全过；
    `verify_events_browser.py` 12 个检查点（3 页 × 4 视口）全过；
16. `git diff --check` 干净；一个 Task 一个独立提交（Task 5 两个 commit）。

## 明确不在本 plan 范围

- **真实 LLM provider 接入** —— 需用户就成本与来源许可给出新授权；
  本 plan 只交付 fake model port；
- **情绪评分与舆情指标** —— SPEC-029 明确「情绪正负分不能单独成为事件 Alpha」，
  且它需要 Task 1 未获批的新闻来源；
- **语义相似度 / embedding 去重** —— Task 2 只做确定性 baseline；
  语义判重必须以 Agent 候选提示形式进入人工确认队列；
- **搜索 provider 接入**（Tavily / SerpAPI / Bocha / Anspire / MiniMax / Brave / SearXNG）
  —— `docs/14` 记录它们需要独立 key 与条款，未获批；
- **统一监控与事件漂移** —— 属 P9 / PUI-08；
- **事件归因（把事件贡献拆进组合归因）** —— 属 P9 的 unified attribution；
  本 plan 只做 core 之外的事件分项，归因中仍标 `unavailable`；
- **真实通知渠道**（邮件 / IM / webhook）—— Step 07 列为 D2，只做 memory sink；
- **`strict_historical` 事件研究** —— 需 `pit_verified` 文档与行情，属付费源；
- **Watchlists/Cases 的完整案例管理工作流** —— 本 plan 只交付事件关联入口，
  完整 Case 生命周期属 P9 / PUI-08；
- **任何真实账户操作** —— P11 需用户新的明确授权。

## 本 plan 完成后仍然成立的限制

- **全部输入为 `normalized_current`**，事件研究结论**不是样本外证据**；
- 真实文档样本仍为 P3-W04c 的 4 家公司 8 份 PDF，
  **事件研究在真实数据上为 `unavailable`** —— 这是被验收的状态，不是缺陷；
- **多源去重能力未在真实数据上被行使**，因为只有一个来源获批；
- **未调用任何真实 LLM provider**，Agent 能力全部为 fake port 验证；
- `ExpectedReturnCompilerV1` 的 event 分项在真实运行时保持 `unavailable`；
- 供应链图在真实运行时为空；
- **P2、P4、P5、P6、P8 Gate 全部未通过** —— 本 plan 不改变任何一条；
- 三页 `design_status` 为 `parity_verified_with_known_deviation`，**不是 `ready`**：
  原型侧栏 224 px 与运行时 280 px 的差异属 `CLAUDE.md` §0 记录的未裁决冲突，
  **本 plan 不改任一真源**；且 `10-events-intelligence` 无 320/768/1024 独立 Frame；
- Vite 的 AntD large-chunk warning 仍然存在，**不得隐藏也不得写成已修复**；
- Agent 永远没有写、审批或交易权限；**本 plan 不修改 `permissions.py`**；
- 本 plan **不授权**向任何第三方模型发送受限来源正文，
  也**不授权**任何真实账户操作。

