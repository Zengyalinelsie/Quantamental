# Step 08 Spec / Plan：P9 监控、统一归因与治理闭环

> 状态：`dependency_blocked`（owner 已冻结，等待 P6/P7/P8）  
> 对应：Plan P9-W01–W03/Gate、Roadmap Step 8  
> 关联 SPEC：023、039–041、048–050、055–058  
> 依赖：P6、P7、P8 输出 schema 稳定

## Spec

### 目标与非目标

把数据、因子、View、Timing、事件、组合和任务统一为可监控、可归因、可审批、可回滚的日常研究运营系统。

非目标：不执行订单；监控不静默改模型/权重；报警阈值不能替代数据/模型版本；P9 execution 分项在 Paper 前为 not_applicable。

### 领域合同

- `UnifiedAttribution`：selection/timing/event/market/industry/style/cost/execution/residual，daily/cumulative closure；
- `DriftObservation`：subject/version/window/metric/baseline/value/threshold/severity/evidence；
- `Alert`：dedupe key/severity/owner/state/source/runbook；
- `Incident`：open/ack/mitigating/resolved/postmortem，append-only transitions；
- `ApprovalReview`：subject/version/use/stage/decision/evidence/reviewer/expiry/supersedes；
- `ServingRegistration`：approved exact version/scope/effective interval/rollback target；
- 用户、角色、entitlement、职责分离由服务端身份拥有。

### 监控与归因

- coverage/freshness、PSI/distribution、IC/decay、calibration、exposure/cost/capacity、Agent parse/citation、job/API/SLO；
- forecast vs realized、model vs portfolio 两层归因；
- residual 超阈值创建 blocker/Incident，不被“其他”吞掉；
- 告警只能阻断、请求 Review 或按已批准 rollback 执行，不能自行晋级。

### API 与产品

- Monitoring Signals/Portfolios/Timing/Drift/Rebalance/Incidents；
- System Users/Entitlements/Approvals 和 Factors Correlation/Production；
- Desk 聚合服务端 projection，普通刷新不触发昂贵 Agent；
- evidence/run/dataset/model/artifact 均可钻取。

### 决策

- ADR-0009 已冻结 Data/Research/Portfolio/Execution owner scope；
- SLO、PSI、IC decay、calibration、residual 阈值为 D2，按 subject/version 配置；
- retention 和通知渠道必须在部署前批准。

### 验收

- 每日和累计归因闭合；
- 人工注入 data/model/portfolio/job 异常路由到正确 owner；
- approve/reject/request changes/suspend/rollback/retire 可审计；
- 越权、scope escalation、前端伪身份均拒绝；
- P9 页面四视口与浏览器工作流通过。

## Plan

### Task 1：统一 Attribution v1

预计新增 `domain/attribution.py`、application/ports/repositories/migration/tests；从 P6 core 扩展 Timing/Event，execution 保持 not_applicable；先 daily，再 cumulative，再 residual Incident。

### Task 2：Drift observations 和 policies

新增 `domain/monitoring.py` 和 subject-specific calculators；threshold policy 配置化并绑定版本。使用人工 shift fixture 和真实小样本交叉验证。

### Task 3：Alert/Incident 状态机

新增 `domain/incidents.py`、application service、append-only repository；测试 dedupe、severity、owner、非法 transition、reopen、runbook 和 audit。

### Task 4：Approval/Serving 治理扩展

复用 P1/P4 权限和 review 合同，泛化到 Alpha/Timing/Risk/Portfolio；不重写身份系统。测试 SoD、expiry、supersede、rollback 和 Agent denial。

### Task 5：API 和 31 页研究/治理面

增加 cursor pagination 和服务端聚合；实现 Monitoring、Desk、Correlation、Production、Users、Entitlements、Approvals 页面及六态。

### Task 6：故障注入和 Gate

注入 stale dataset、feature shift、IC decay、calibration drift、cost deviation、citation failure、job failure；核对 Alert/Incident/Review/rollback 行为和 Evidence。

### 验证

定向测试覆盖 attribution closure、monitoring policy、incident transitions、permission matrix；阶段收口执行全量、migration、故障注入、API 性能和四视口浏览器。更新新的 P9 Evidence。
