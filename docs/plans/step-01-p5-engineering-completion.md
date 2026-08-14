# Step 01 Spec / Plan：P5 工程能力收口

> 状态：`in_progress`；Task 1 application export 已验证
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

预计文件：

- `platform/tests/test_research_workspace_api.py` 或新增 `test_investment_view_artifact_api.py`；
- `platform/src/a_share_platform/api/app.py`、`api/schemas.py`；
- `platform/src/a_share_platform/adapters/postgres/governance.py`（若现有能力不足）；
- `platform/frontend/src/api/client.ts` 和生成 schema。

先写缺失、无权限、成功读取和 immutable cache/header 合同，再接只读元数据/下载入口。

### Task 3：Outcome source 与 worker

预计文件：

- `platform/tests/test_investment_view_outcome_worker.py`；
- `platform/src/a_share_platform/ports/expected_return.py`；
- `platform/src/a_share_platform/application/investment_view_outcomes.py`；
- `platform/src/a_share_platform/workers/investment_view_outcomes.py`。

先实现 provider-neutral source、成熟度扫描、dry-run 默认、execute ack、幂等和 mismatch 拒绝。真实价格 adapter 等 `P5-D1-01`。

### Task 4：估值/改善剩余服务

预计文件：

- `platform/tests/test_valuation_improvement_service.py` 及新增 model tests；
- `platform/src/a_share_platform/domain/valuation_*.py`；
- `platform/src/a_share_platform/application/valuation_improvement.py`；
- frozen bundle compiler/qualification 相关文件。

按行业口径、相对估值、锚定估值、隐含预期、趋势/加速度、一次性项目逐个纯函数红绿；每项含单位、缺失、异常值和手算 fixture。

### Task 5：P5 产品页和响应式

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
npm --prefix frontend test -- --run ResearchP5Screen InvestmentViewSummary WorkspacePage.research
```

收口时执行 `docs/plans/README.md` 全量命令，更新 `docs/08-detailed-implementation-plan.md` 和 P5 Evidence，并按 Task/工作包独立提交。
