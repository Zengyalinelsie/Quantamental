# Step 01 Spec / Plan：P5 工程能力收口

> 状态：`in_progress`；Task 1–3、Task 4A 已验证，Task 4B 待完成，Task 5 `implemented_unverified`
> 对应：Plan P5-W01/W02/W04、Roadmap Step 1  
> 关联 SPEC：018–019、024–025、041、047、050–052  
> 前端：Security、InvestmentView、Universe & Screen、Alpha Model、Approvals

## Spec

### 目标与非目标

完成 P5 中不需要伪造真实 PIT 产物的工程能力：Frozen Artifact、Outcome 到期流程、估值/改善服务边界和 P5 响应式产品页。当前不合格数据库仍应产生稳定 blocker 和零真实 SignalSnapshot。

非目标：不制造 PIT、不批准未验证因子、不从页面推导排名/闭合、不声称预期收益科学有效。

### 领域与应用合同

- Frozen Artifact 是 InvestmentView canonical JSON 的 content-addressed、不可变导出；
- envelope 至少包含 `artifact_schema_version`、`investment_view_content_hash`、完整 View；
- 导出前必须存在精确 View 和 `succeeded` Run；失败时不得先写 object；
- View → Artifact、Run/Model/Dataset/Feature → Artifact lineage 完整；
- 重复导出返回同一 Artifact，`writes_performed=false`；
- Outcome worker 只编排成熟 View 和 provider-neutral outcome source，不在应用层猜测价格；
- 未到期、价格不可用、公司行动不完整和 source 资格不足分别表达 pending/unavailable；
- Outcome append-only，view/security/time/horizon 必须一致；
- 估值与改善输出必须绑定 frozen input、公式版本、行业模板、单位、币种和 availability；
- 无法量化时使用 `unavailable/constrained`，不得填零。

### 存储、API 与页面

- 对象存储复用 `RawObjectStore`/`LocalRawObjectStore`；治理 Artifact/Lineage 复用 P1 账本；
- Outcome 复用 `research.investment_view_outcomes`，如需新增 source policy/version 字段只能通过 append-only migration；
- 增加 Artifact 下载/元数据只读 API；写操作由服务端权限和用途拥有；
- P5 页面必须覆盖 loading/error/empty/partial/unavailable/ready；
- 320/768/1024/1440 按原型重排，不等比缩小；
- strict/current、trust、decision time、deployment stage 始终显示文本。

### 待决策

- `P5-D1-01` Outcome 价格政策：不阻塞 provider-neutral worker；阻塞真实 price source adapter；
- `P5-D1-02` 估值工程公式：已由 ADR-0011 冻结；改变公式、端点组合或负值政策必须升版；
- 分析师修正无合格来源时保持 unavailable，不阻塞其他 P5 服务。

### 验收

- Artifact 成功、幂等、缺 View、非成功 Run、hash 冲突和 lineage 测试通过；
- Outcome pending/unavailable/mature/idempotent/mismatch 测试通过；
- P5 API 和前端只消费服务端投影；
- 四个视口浏览器验收通过；
- 真实当前库不合格时无 View/Snapshot/Artifact 写入。

## Plan

### Task 1：Frozen Artifact 红绿闭环

状态：`verified`。TDD、全量验证和限制见 `docs/21-p5-implementation-evidence.md`。

预计文件：

- `platform/tests/test_investment_view_artifacts.py`；
- `platform/src/a_share_platform/application/investment_view_artifacts.py`；
- `platform/src/a_share_platform/application/governance_ledger.py`；
- 必要时 `platform/src/a_share_platform/ports/governance.py`。

步骤：先运行现有红测确认缺模块；实现 canonical encoder、preflight、object write、Artifact 和 lineage；补幂等/hash conflict；运行定向测试。

### Task 2：Artifact PostgreSQL/API

状态：`verified`。PostgreSQL repository、0032–0034 数据库约束、精确 lookup、Artifact+lineage 单事务、
私有 metadata/download API、严格 OpenAPI、受控本地 reader 和真实 PostgreSQL rollback smoke 已完成。
页面入口由 Task 5 接入；四档浏览器视觉证据仍 pending，不以 API 或组件测试冒充 UI 验收。

预计文件：

- `platform/tests/test_research_workspace_api.py` 或新增 `test_investment_view_artifact_api.py`；
- `platform/src/a_share_platform/api/app.py`、`api/schemas.py`；
- `platform/src/a_share_platform/adapters/postgres/governance.py`（若现有能力不足）；
- Task 5 的前端 client 和页面入口（通过 server permission 后才开放下载）。

先写缺失、无权限、成功读取和 immutable cache/header 合同，再接只读元数据/下载入口。

实现补充：匿名在对象查找前拒绝；metadata 不暴露 `storage_uri`，并返回 producer RunContext；
missing producer Run、路径越界、symlink/非普通文件、超限和 hash mismatch 均失败关闭；
Viewer 因缺少发布/审批绑定而拒绝，Run 列表也鉴权并限定 research；limited-live Artifact 因 P11
未授权而拒绝。等价并发 CAS/object/DB winner 可幂等恢复。对象存储与 PostgreSQL 无跨系统原子事务，CAS 对象先写而
DB 事务失败时可能留下不可下载的孤儿对象，后续由对象清理任务处理，不能据此登记 Artifact。

### Task 3：Outcome source 与 worker

状态：`verified`。已完成 provider-neutral maturity source、明确的 pending/unavailable/mature、
research-only 扫描、dry-run 默认、execute ack、append-only 幂等写入和 identity mismatch 拒绝。
`0035_outcome_source_policy.sql` 强制冻结 source policy/version 和 source availability；迁移遇到既有
Outcome 时拒绝猜测回填。默认运行时 source 因 `P5-D1-01` 未批准而返回 `source_unqualified`，不制造
价格或收益；真实价格 adapter 仍待决策。

预计文件：

- `platform/tests/test_investment_view_outcome_worker.py`；
- `platform/src/a_share_platform/ports/expected_return.py`；
- `platform/src/a_share_platform/application/investment_view_outcomes.py`；
- `platform/src/a_share_platform/workers/investment_view_outcomes.py`。

先实现 provider-neutral source、成熟度扫描、dry-run 默认、execute ack、幂等和 mismatch 拒绝。真实价格 adapter 等 `P5-D1-01`。

### Task 4A：估值/改善纯领域模型

状态：`verified`（仅纯领域工程模型）。ADR-0011 已冻结 provider-neutral V0 公式；相对估值、FCF/银行
锚定、隐含增长/ROE、分析师修正资格门和四期改善输入编译器均有手算与异常值测试。新模型只在
domain 提供纯函数，没有新增 application 输入源；运行时仍只允许现有 frozen bundle source 和
orchestration。价格、每股基本面、假设 provenance 与单位分别闭合；合并结果另保留各输入的
method/version lineage。分析师 current/prior 快照分别绑定 provider/provenance，且必须与 attestation
provider 一致；领域对象不替代治理 registry lookup。缺 anchor、缺三类相对参考或缺分析师
attestation 时显式 unavailable。PostgreSQL compiler 对未知基数效应/一次性项目显式生成 unavailable，
不再携带看似可量化的数字。

### Task 4B：估值模型 frozen runtime 接线

状态：`pending`。当前 `ValuationImprovementInputBundle`、持久化文档和 orchestration 尚未携带或调用
Task 4A 的 relative reference、anchor 和 analyst revision 模型。真实 historical/industry/peer 分布、
FCF 和分析师来源也尚未通过资格。完成时必须扩展现有 exact frozen bundle、qualification/compiler、
append-only persistence 和 orchestration；不得另建可绕过 bundle ID/decision time/mode/trust 的输入入口。
在此之前 Task 4 整体和 P5 Gate 都不能标记完成。

预计文件：

- `platform/tests/test_valuation_improvement_service.py` 及新增 model tests；
- `platform/src/a_share_platform/domain/valuation_*.py`；
- `platform/src/a_share_platform/application/valuation_improvement.py`；
- frozen bundle compiler/qualification 相关文件。

按行业口径、相对估值、锚定估值、隐含预期、趋势/加速度、一次性项目逐个纯函数红绿；每项含单位、缺失、异常值和手算 fixture。

### Task 5：P5 产品页和响应式

状态：`implemented_unverified`。Artifact ID 为 null 时显示未生成；非空时先读取服务端 identity 的
`read_artifact` 权限，再读取 exact metadata，只有权限、元数据和响应/请求 Artifact ID 完全一致才
暴露 download URL。Identity 使用严格 OpenAPI Envelope，前端消费生成类型；匿名默认保持禁用，不能
用会返回 403 的链接冒充可下载。Screen 在 320 px 使用 server-projected 等价记录卡，不重排或重算
rank change，并保留 score/previous rank/trust/InvestmentView/hash；1024 使用文字详情抽屉承载低
优先字段，768 横向滚动并冻结首列。1024/768/320 已实现导航、上下文文字保留、表格/记录卡和
InvestmentView 重排，空/部分态显式保留 Trust。组件/API 合同测试已通过；当前浏览器控制没有可
操作页面 tab，因此 1440/1024/768/320 运行时视觉验收仍为 `pending`，不能把实现或构建通过写成
浏览器验收通过。

待裁决：SPEC-045 的桌面展开侧栏为 280 px，产品蓝图响应式表为 224 px。本轮运行时遵守权威 Spec
并保留 280 px，1024 窄桌面使用真实 72 px collapsed state；采用 224 px 前必须先批准并统一文档。

预计文件：

- `platform/frontend/src/pages/ResearchP5Screen.tsx/.less/.test.tsx`；
- `platform/frontend/src/features/investment-view/*`；
- `platform/frontend/src/features/screen/*`；
- Approvals 相关页面/组件；
- 浏览器 Evidence 文档。

逐页按 API contract test → component test → 1440 → 1024 → 768 → 320 验收。禁止 runtime fixture。

### 定向验证

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest tests.test_investment_view_artifacts -v
PYTHONPATH=src .venv/bin/python -m unittest tests.test_investment_view_compilation tests.test_expected_return_ledger tests.test_research_workspace_api -v
PYTHONPATH=src .venv/bin/python -m unittest tests.test_valuation_models tests.test_fundamental_improvement tests.test_postgres_valuation_input_qualification tests.test_valuation_improvement_service -v
npm --prefix frontend test -- --run ResearchP5Screen InvestmentViewSummary WorkspacePage.research
```

收口时执行 `docs/plans/README.md` 全量命令，更新 `docs/08-detailed-implementation-plan.md` 和 P5 Evidence，并按 Task/工作包独立提交。
