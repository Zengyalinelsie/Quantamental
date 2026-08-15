# Step 07 Spec / Plan：P8 新闻、事件 Agent 与供应链

> 状态：`dependency_blocked`（保存边界已冻结，等待 P5/P3 输入）  
> 对应：Plan P8-W01–W05/Gate、Roadmap Step 7  
> 关联 SPEC：024、027–029、047、053、056  
> 依赖：P3 文档证据、P5 InvestmentView；可与 P6/P7 部分并行

## Spec

### 目标与非目标

把公告、新闻、研报和供应链事实变成可追溯的 Document/Event/Claim/Impact 链，并在统计与用途审批后以新版本增强 InvestmentView。

非目标：LLM 不提供权威价格/财务/时间；无引用输出不能进入决策；Agent 无审批、信任提升或交易权限；不复制 donor 的买卖建议定位。

### 领域合同

- `DocumentVersion`：source/license/hash/published/fetched/available/correction/retraction；
- `EventCluster`：taxonomy/entities/documents/dedupe/version；
- `EventClaim`：fact/inference/opinion/rumor、citations、confidence、conflict；
- `ImpactHypothesis`：affected security/path/horizon/distribution/invalidator/status；
- `SupplyChainEdge`：node/relationship/effective interval/source/confidence/staleness；
- `AgentRun`：model/prompt/tools/schema/budget/deadline/retry/input/output/citations/audit；
- `EventStudy`：window/expected-return model/AR/CAR/SE/control/FDR/overlap；
- event contribution 修改时生成新的 Compiler/View/Review，不回写 P5 历史 View。

### 数据、权限和通知

- 公告原文优先保存；新闻/研报按许可保存原文或 hash/metadata；
- near-duplicate 和聚类不删除原文版本；
- correction/retraction 产生新状态和下游 review；
- tool allowlist deny-by-default，网络/预算/timeout 明确；
- 通知只引用 frozen Artifact，不在消息中重新生成数值结论。

### 决策

- ADR-0008 已冻结来源许可/原文保存框架；每个商业来源仍需逐源登记；
- LLM provider、预算、通知渠道为 D2，可替换且不进入领域核心；
- 第一事件 taxonomy 需要在 adapter 前冻结 version 0。

### 验收

- 任意事件可追 document/version/time/entity；
- citation invalid/duplicate/conflict/retraction 测试通过；
- Agent 无引用或 schema invalid 输出被隔离；
- Event Study 诚实成功或失败；
- 未晋级 event 保持 evidence/constrained/Shadow，不进入数值贡献。

## Plan

### Task 1：来源/许可 ADR 与 Document ledger

新增来源 ADR、`domain/documents.py`、ports/object store/repository/migration/tests。先 hash/version/time/correction/retraction，再 adapter。

### Task 2：Event/entity/dedup pipeline

新增 `domain/events.py`、entity linker/deduper ports 和 deterministic baseline；真实小样本用公告/新闻重复、冲突和更正案例。

### Task 3：Agent runtime

新增 `domain/agent_research.py`、`application/agent_runtime.py`、model/tool ports 和 audit repository；先 fake adapters 测 allowlist、预算、timeout、schema/citation，再接批准 provider。

### Task 4：供应链图

新增 `domain/supply_chain.py`、graph repository、effective interval/stale/double-count tests；关系不确定时不推断为事实。

### Task 5：Event Study 和 View v2

实现 expected return/AR/CAR/clustered or bootstrap SE/matched controls/FDR；独立库交叉验证；通过 review 后调用新 CompilerVersion 生成新 View。

### Task 6：API、Events/Cases 和通知

实现 Document/Event/Claim/Impact/SupplyChain/AgentRun 只读/受权写 API；前端 badges、drill-down、invalidators、pending verification；通知 adapter 只发送 frozen Artifact 链接。
Events、Cases、Agents 和 Security event enhancement 的页面交付按 PUI-07 执行；Design Parity 不提升
引用资格，缺引用或 schema invalid 的 Agent 输出仍必须隔离。

### 验证

定向测试覆盖 document time/version、dedupe、citation、Agent 权限/预算、graph interval、event statistics；阶段收口执行全量、独立统计、真实小样本和四视口浏览器。不得用 LLM 文本证明数值正确。
