# P5 实现与验证证据

> 状态快照：2026-08-15
> 范围：P5 当前工程进度；Frozen Artifact、Outcome worker、估值/改善工程模型、P5 产品页
> Gate：P5 Capability Gate 仍未通过

## 1. Frozen InvestmentView Artifact application export

本工作包实现 provider-neutral 的确定性 Frozen Artifact 导出器，复用现有
`ExpectedReturnLedgerService`、`GovernanceLedger` 和 `RawObjectStore`，没有建立第二套 View、Run、
Artifact 或对象存储合同。

实现行为：

- 只从 append-only Expected Return ledger 精确读取 `InvestmentView`；
- 对象写入前要求对应 `RunRecord.status=succeeded`；
- naive `created_at`、早于成功 Run、缺 View、缺/非成功 Run 均在对象写入前失败；
- 生成 deterministic、sort-key、紧凑 UTF-8 canonical JSON；
- envelope schema 为 `investment-view:v1`，绑定 View content hash 和完整 View document；
- payload SHA-256 同时决定 content-addressed storage 和 deterministic Artifact ID；
- View → Artifact 使用 `frozen_as`；Dataset/Feature/Model/Run/evidence 均登记 direct lineage；
- 重复导出返回相同 Artifact 且 `writes_performed=false`；
- 已存在相同 content hash 的不同 Artifact owner 会在对象写入前失败，不留下孤儿文件；
- 已存在 Artifact 但 lineage 不完整时可幂等补齐缺失边。

## 2. Durable PostgreSQL Governance 与私有 API

本工作包新增 `PostgresGovernanceRepository` 并在 `ASP_DATABASE_URL` 存在时由 API 自动 composition：

- Dataset/Run/Artifact/Lineage 全部使用 schema-qualified `governance.*`；
- RunContext、终态和失败原因完整 round-trip，OperationalError 映射为显式 503；
- Artifact 要求 producer Run 存在，ID/hash 双重不可变；Dataset 同 hash 冲突映射为领域冲突；
- exporter 改为 Artifact ID/hash 和 downstream lineage 精确查询，不再全表扫描；
- Artifact 与完整 lineage 在一个数据库事务中登记；
- `0032_governance_integrity.sql` 在数据库层约束 hash、合法 RunContext/状态/时间，并阻止
  Dataset/Artifact/Lineage 更新删除；Run 只允许 pending→running 或 running→terminal；0033 以
  `coalesce` 关闭 failed Run 的 NULL reason 三值逻辑旁路；0034 阻止 Run/Lineage 空白字段；
- `GET /api/artifacts`、metadata 和 download 全部要求私有 Artifact 权限，匿名在对象查找前 403；
- Viewer 因 Artifact 尚无“已发布/已审批”绑定而不获私有读取权；`/api/runs` 同样鉴权并只列 research；
- metadata 使用 strict schema，不暴露 `storage_uri`，并携带 producer RunContext 和 Artifact 时间；
- 下载只读取已登记 Artifact，限定 research stage；P11/limited-live 显式拒绝；
- 本地 reader 只接受受控根下 `sha256/<digest>` 普通文件，使用 root/sha256 dirfd 和逐段
  `O_NOFOLLOW`，拒绝 scheme/percent/path/symlink 越界，16 MiB 上限，同一 file descriptor 读取并
  重新计算 SHA-256；
- 下载提供 ETag、conditional 304、private immutable cache、nosniff 和安全文件名；
- producer Run 缺失、路径或 hash 不一致使用 409；对象/DB 不可用使用 503。
- exporter/本地 CAS 对等价并发 winner 幂等恢复；不兼容 winner 继续冲突关闭；
- 前端 `openapi.json` 和 `schema.d.ts` 已刷新，identity、metadata、download bytes、304 和错误响应有显式类型。

页面侧新增 Frozen Artifact 权限入口：Artifact ID 缺失时明确“尚未生成”且不发请求；存在 ID 时
先从 `/api/identity` 读取服务端权限，只有 `read_artifact` 后才读取 exact metadata 并显示下载 URL。
Identity 使用 strict Envelope，前端消费生成的权限类型；角色请求头不能提升匿名主体。匿名主体只有
`read_public`，按钮保持禁用。metadata 失败或响应 Artifact ID 与请求不一致时，不暴露未经校验的
下载链接。

对象存储和 PostgreSQL 不能形成跨系统事务：CAS 写入成功、DB 事务失败时可能留下无法由 API 发现或
下载的孤儿对象。数据库侧 Artifact+lineage 已原子；孤儿对象清理仍是后续运维工作，不允许用孤儿对象
冒充已登记 Artifact。PostgreSQL 保存 Run 当前状态投影并强制单向 transition；独立 append-only Run
state event history 尚未成为 port 合同。

## 3. Provider-neutral Outcome maturity worker

本工作包没有选择或连接真实价格供应商。新增 `InvestmentViewOutcomeSource` port，由 adapter 负责
交易日历、到期日、复权收益和公司行动完整性；应用层不按自然日猜成熟度，也不计算价格：

- source 返回 `pending / unavailable / mature`；
- 未到期固定为 `horizon_not_reached`；价格缺失、公司行动不完整、来源未获资格使用三个不同
  unavailable reason，均不得生成数值零；
- source 返回的 view/security/decision time/horizon/evaluated-at 任一不闭合即零写入失败；
- 只扫描 research-stage View；P11 的 paper/limited-live View 不进入 source；
- 默认 CLI 是 dry-run；`--execute` 还要求 private-local research ack；
- mature Outcome 使用 frozen View hash 的确定性 ID，重复扫描先读取既有 Outcome，不改写、不再访问 source；
- Outcome 继续 append-only，并新增 `source_policy_version`、`source_available_at` 到领域 hash、PostgreSQL
  列和 JSON 文档；0035 若发现旧 Outcome 会拒绝猜测政策后再迁移；
- 默认 unavailable adapter 明确报告 `P5-D1-01` 未批准，绝不注入 runtime 假价格或假收益。

## 4. TDD 证据

首次定向执行结果：

```text
ModuleNotFoundError:
a_share_platform.application.investment_view_artifacts
```

最小实现后，补充 created-at 和治理 content-hash conflict 边界。最终定向结果：

```text
Ran 4 tests in 0.003s
OK
```

覆盖：canonical/content-addressed export、完整 lineage、幂等、缺 View、非成功 Run、无效时间和
治理 hash 冲突零对象写入。

Task 2 首次定向执行按预期失败：

```text
ModuleNotFoundError: a_share_platform.adapters.postgres.governance
ImportError: cannot import name 'LocalArtifactReader'
```

随后分别增加权限、OpenAPI、P11 scope、producer provenance、reader resource guard、精确 lookup、
单事务、adapter 一致性和并发 winner 红测；最终核心 Artifact 相关 57 项定向测试通过。

Task 3 首次执行按预期失败：

```text
ModuleNotFoundError:
a_share_platform.application.investment_view_outcomes
```

实现后 Outcome、Expected Return ledger、PostgreSQL adapter 和 migration 共 58 项定向测试通过。

Task 4 首次执行按预期失败：

```text
ImportError: cannot import name 'ValuationModelSuiteInput'
ImportError: cannot import name 'FundamentalImprovementInputCompilerV0'
```

实现过程中新增的 mode/trust 混合参考集红测再次先失败，随后补齐同一 reference set 的
mode/trust/decision-time 门。只读复审发现草案 suite 没有真正读取 frozen bundle，可能形成第二输入
真源，因此在提交前删除该 application 入口；运行时继续只使用既有 exact bundle orchestration。
复审还推动补齐：分析师 provider/use/license/approval/time attestation、预测目标与 snapshot 可比轴、
current/prior provider/provenance 与 attested provider 的一致性、资格生效/过期/trust ceiling 测试、
价格/每股基本面/假设分离 provenance 和单位、缺 anchor unavailable、三类参考必须逐项表达，以及
P/B<1 时银行隐含 ROE 的全端点包络。合并模型结果保留输入 method/version lineage，不只合并
DatasetVersion/observation/hash。ADR-0011 同步冻结这些边界；全部仍为 `not_evaluated`。真实
compiler 没有一次性项目或基数效应证据时输出无数值 unavailable，不填零、不用 reported 数字冒充
adjusted 数字。

第二轮只读复审确认，新模型尚未进入现有 frozen bundle/persistence/orchestration，Task 4 因此拆为
4A 纯领域模型和 4B 安全 frozen runtime 接线。4B 继续扩展原 `ValuationImprovementInputBundle`，没有
建立第二套输入真源：legacy v1 保持原 JSON/hash 只读兼容但执行失败关闭；v2 冻结 industry policy、
每个适用 metric 的 historical/industry/peer reference、anchor raw input、analyst input、四个模型版本
和 compiler 版本。v2 不保存或信任旧的预计算 market-implied/fundamental-anchor 区间，orchestration
运行时调用 relative、anchor、implied、analyst、improvement 和 scenario，再把合法模型结果临时转换为
既有 gap engine 所需区间。分析师 unavailable 只令内部 suite 为 partial，不增加第五种
`InvestmentComponent` status，也不阻断其他合法核心服务。

PostgreSQL compiler 没有真实 reference、FCF/折现率/增长率政策或合格分析师来源时，生成显式
unavailable input，不制造数值、provider、snapshot、available-at 或 provenance。`0036` 增加显式 v2
schema 与 DatasetVersion child links；新写入只接受 v2，same ID/different semantics 保持 immutable
conflict，freeze 要求 qualification datasets 与 bundle datasets 完全相等。Task 4B 定向测试 `79/79`
通过；领域 fixture 中的数值和 attestation 只验证合同，不是治理 registry 的真实资格记录。Task 4
工程能力至此 `verified`，但真实数据资格和 P5 Gate 仍未完成。

Task 5 先增加 Artifact ID 串链测试：metadata 返回另一 Artifact 时，旧实现按预期错误地生成了另一
下载 URL；加入 exact identity guard 和缺 permissions 失败关闭后，6 项 Frozen Artifact 定向测试
通过。Identity OpenAPI 红测要求
`IdentityEnvelope` 和 `extra=forbid` 的 `IdentityProjection`，实现严格 response model、重新生成
OpenAPI/TypeScript 类型后，3 项 Identity 定向测试通过。响应式复审继续发现 1024 详情抽屉、768
冻结首列、320 等价字段和空态 Trust 缺口；补红测后四个相关组件文件共 23/23 通过。组件和 API
测试不替代浏览器视觉验收。最终复审还发现详情抽屉缓存整行会在后台刷新后显示旧版本；新增
rerender 红测后改为只保存 `snapshot_id` 并从最新 projection 派生，行消失时自动关闭，相关组件
合计 24/24 通过。

2026-08-15 的 Task 5 浏览器验收续作先把桌面截图中的疑似右侧裁切收敛为响应式 CSS 合同：固定侧栏
后的主内容宽度必须与视口闭合，运行上下文长标识必须可收缩断行，Universe 控件必须允许换行且子控件
不得超过容器。旧样式定向执行 `3/3` 按预期失败；最小修复为 280/72 px 侧栏分别显式计算主内容宽度、
长上下文使用 `overflow-wrap:anywhere`、Universe 控件启用 wrap 并限制 Select/Segmented/input。修复后
P5 相关组件和布局合同定向测试 `31/31` 通过，全量前端测试增加到 `73/73`。该合同用于防回归，仍不
替代真实浏览器的几何、截图、交互、控制台或网络验收。

### Task 5 真实 Chrome 验收

内置 Browser 不可用后，用户明确批准切换到已连接 Chrome。Chrome 当前站点缩放为 90%，所以按
`devicePixelRatio=0.9` 校准外层窗口，并以页面报告的 CSS `window.innerWidth` 为验收真值；前三档
CSS 高度为 1000，320 档为 844：

| CSS 视口 | 导航 | 页面宽度证据 | 结果 |
|---:|---|---|---|
| 1440 | 280 px 展开侧栏 | `clientWidth=scrollWidth=1440` | 顶部上下文完整；Universe 的 AS OF 在空间不足时换到下一行，无右侧裁切 |
| 1024 | 自动收为 72 px | `clientWidth=scrollWidth=1024` | 上下文标签和值完整；Universe Select 独占一行，其余控件在容器内重排 |
| 768 | 移动 Drawer | `clientWidth=scrollWidth=768` | Drawer 打开/关闭与一级导航可用；上下文两行、Universe 单列，无页面级溢出 |
| 320 | 移动 Drawer | `clientWidth=scrollWidth=320` | 上下文文本值保留；Tabs 在自身容器提供省略入口；Universe/Security/P5 context 均未撑宽页面 |

真实交互覆盖：Universe current/historical 切换、历史日期警告、空 UniverseVersion、移动 Drawer、
Universe & Screen/Security tab、全局搜索 `600066` 原样形成真实 API 请求、Screen/InvestmentView/
Alpha 的 unavailable blockers 和 Trust 文本。当前运行时没有 ready/partial Screen、InvestmentView 或
Frozen Artifact，故没有用 fixture 伪造浏览器 ready 态；这部分仍受真实 P5 Gate 阻断。

网络失败态通过 CDP 临时阻断一次 `/api/research/workspace` 请求，页面显示
`P5 研究工作区读取失败 / TypeError: Failed to fetch`；清除阻断后下一证券查询恢复 200。正常整页重载
记录 68 个 response，0 个 4xx/5xx；React Query 在 Strict Mode 取消的 `/api/universes` 和
`/api/research/workspace` 初始重复请求标记为 `canceled=true / ERR_ABORTED`，同 URL 后续请求均为
200。页面控制台 error/warning 列表为空。故障注入已完全恢复，未改变运行时业务数据。

## 5. 真实 PostgreSQL 证据

迁移前只读预检：

```text
DatasetVersion: 13,314
RunRecord: 1
Artifact: 0
LineageEdge: 77,639
invalid_dataset_hash=0, blank_dataset_fields=0, invalid_runs=0
blank_run_fields=0, blank_lineage_fields=0
```

`0032_governance_integrity`、`0033_failed_run_reason_guard` 和
`0034_governance_nonblank_fields` 已应用到本地开发库。随后在外层事务中完成真实 Dataset/Run/
Artifact+lineage round-trip、exact lookup、同 hash 冲突、Artifact UPDATE 拒绝和终态 Run 再变更拒绝；
smoke 事务整体回滚，测试行未留库，迁移记录保留。另以真实 CHECK violation 验证
`failed + NULL failure_reason`、空白 lineage 被拒绝，并验证 pending→running→terminal；均未留记录。

Outcome 迁移前 `research.investment_view_outcomes=0`；`0035_outcome_source_policy` 已应用。真实
PostgreSQL 事务 smoke 成功写入并读取 source policy/source availability，随后整体 rollback，临时
View/Outcome 均为 0。真实库 dry-run maturity scan 返回 `items=[]`、`writes_performed=false`；这只
证明安全运行路径，不代表已有真实 Outcome。

`0036_p5_valuation_bundle_v2` 已应用到同一本地开发库。迁移时库内 legacy/v2 valuation bundle 均为
0，因此没有可声称的真实 legacy 行样本；legacy 原 JSON/hash 不改写由 migration contract 与 v1
round-trip/hash 测试覆盖。随后在外层强制 rollback 事务中完成真实 v2 append/load、重复 append 幂等、
same-ID/different-semantics 冲突和三个 DatasetVersion child links 验证；退出后临时 bundle 为 0，未污染
业务数据。

## 6. 全量验证

```text
Backend unittest: 817/817 passed
Ruff: passed
mypy: 175 source files passed
compileall: passed
git diff --check: passed
Frontend Vitest: 73/73 passed
Frontend lint: passed
Frontend build: passed
```

Vite 仍报告既有 AntD 大 chunk warning；本工作包没有把 warning 隐藏或改成通过项。
`ci/verify.sh` 现在先隔离 `ASP_DATABASE_URL` 再运行默认空运行时测试，仅在 migration
阶段重新注入真实本地 URL；对应回归测试已覆盖，避免真实 13,314 条 DatasetVersion 污染 fixture-free
API 合同。

## 7. 主要文件

- `platform/src/a_share_platform/application/investment_view_artifacts.py`；
- `platform/src/a_share_platform/application/governance_ledger.py`；
- `platform/src/a_share_platform/adapters/postgres/governance.py`；
- `platform/src/a_share_platform/adapters/object_store/local.py`；
- `platform/src/a_share_platform/api/app.py`、`api/schemas.py`；
- `platform/migrations/0032_governance_integrity.sql`；
- `platform/migrations/0033_failed_run_reason_guard.sql`；
- `platform/migrations/0034_governance_nonblank_fields.sql`；
- `platform/scripts/export_openapi.py`、`platform/frontend/src/api/openapi.json`、`schema.d.ts`；
- `platform/tests/test_investment_view_artifacts.py`；
- `platform/tests/test_postgres_governance.py`；
- `platform/tests/test_investment_view_artifact_api.py`；
- `platform/src/a_share_platform/application/investment_view_outcomes.py`；
- `platform/src/a_share_platform/workers/investment_view_outcomes.py`；
- `platform/migrations/0035_outcome_source_policy.sql`；
- `platform/tests/test_investment_view_outcome_worker.py`；
- `platform/src/a_share_platform/domain/valuation_models.py`；
- `platform/src/a_share_platform/domain/fundamental_improvement.py`；
- `platform/src/a_share_platform/ports/valuation_inputs.py`；
- `platform/src/a_share_platform/application/valuation_improvement.py`；
- `platform/src/a_share_platform/application/valuation_input_freeze.py`；
- `platform/src/a_share_platform/adapters/memory/valuation_inputs.py`；
- `platform/src/a_share_platform/adapters/postgres/valuation_inputs.py`；
- `platform/src/a_share_platform/adapters/postgres/valuation_input_qualification.py`；
- `platform/migrations/0036_p5_valuation_bundle_v2.sql`；
- `platform/tests/test_valuation_models.py`、`test_fundamental_improvement.py`；
- `platform/tests/test_valuation_improvement_service.py`、`test_postgres_valuation_inputs.py`；
- `platform/frontend/src/features/investment-view/FrozenArtifactPanel.tsx` 及测试；
- `platform/frontend/src/pages/ResearchP5Screen.tsx/.less/.test.tsx`；
- `platform/frontend/src/features/screen/ScreenRankingPanel.tsx/.test.tsx`、`screen.less`；
- `platform/frontend/src/app/AppShell.tsx`、`shell.less`、`responsiveLayoutContract.test.ts`；
- `docs/adr/0011-valuation-model-engineering-defaults.md`；
- `platform/ci/verify.sh`、`platform/tests/test_architecture_contract.py`。

## 8. 未完成和 Gate 边界

Frozen Artifact application、durable PostgreSQL 和 API 工程链路已完成。以下仍未完成：

- 获批的真实 Outcome price/calendar/corporate-action adapter 与真实到期产物；
- 真实 historical/industry/peer、FCF、合格分析师输入 adapter/产物；
- 真实 ready/partial Screen、InvestmentView 和 Frozen Artifact 浏览器产物；
- 真实 qualified PIT bundle、InvestmentView、Review 和 SignalSnapshot。

2026-08-15 的后续原型运行时审计进一步澄清：Task 5 的 `verified` 只覆盖当前
empty/unavailable 技术壳/合同页的响应式、交互、网络和控制台，不是精确 Figma node 的 Design Parity。
当前 Desk 仍是硬编码工程能力表，Universe/Security 尚未实现高保真 Frame 的完整信息架构，Portfolio、
Monitoring 和多个 System tab 仍是通用占位。31 页逐页事实见
`docs/22-prototype-runtime-gap-audit.md`；后续视觉产品化进入
`docs/plans/track-00-prototype-runtime-delivery.md`，不能倒改本 Evidence 已验证的工程事实。

因此 P5 Capability Gate 仍未通过。自动测试证明工程合同按预期工作，不证明 Expected Return、
InvestmentView、因子或策略科学有效。

本轮真实 HTTP 确认 `http://127.0.0.1:5173/research` 与 `/api/health` 均为 200。运行时
`/api/universes` 返回空集合，`/api/research/workspace` 因未配置持久化且没有真实 InvestmentView、
SignalSnapshot 和获批 Alpha Model 而显式返回 `unavailable` blockers，匿名 identity 只有
`read_public`；没有注入 runtime fixture。

用户明确指定的内置 `@Browser` 当前不可用；用户随后明确批准改用已连接 Chrome，以上四档截图、
导航/控件交互、页面级 `scrollWidth`、右侧边界、控制台和网络证据均来自真实 Chrome 页面，不是
组件测试或 HTTP 替代。当前真实 unavailable/empty/error 运行态已通过；不存在的 ready 产物没有被
冒充为已验收。

另有一项未裁决的设计冲突：SPEC-045 固定桌面展开侧栏为 280 px，产品蓝图响应式表写 224 px。
本轮实现恢复并保持权威 Spec 的 280 px，窄桌面收起宽度为 72 px；没有擅自修改 Spec 或把 224 px
写入运行时。该差异需用户批准后统一文档，不能由测试通过替代决策。
