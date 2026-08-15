# Step 09 Spec / Plan：P10 Paper OMS 与执行闭环

> 状态：`dependency_blocked`（Paper adapter 已冻结，等待 P9）  
> 对应：Plan P10-W01–W05/Gate、Roadmap Step 9  
> 关联 SPEC：004、031、036–039、055–056、058  
> 依赖：P9 治理、审批、Incident 和统一归因

## Spec

### 目标与安全边界

实现完全不连接真实账户的 Paper OMS，验证订单意图、风险、审批、模拟成交、持仓现金、对账、恢复和 kill switch。

硬边界：第一版推荐确定性内部 Paper Broker；不调用真实券商交易 API，不保存真实账户凭证，不提供 Live 环境切换；Agent 和研究服务没有 order command 权限。

### 领域合同

- `OrderIntent`：target/policy/security/side/qty/limit/tif/reason/idempotency/approval；
- `Order`：created/approved/submitted/acknowledged/partially_filled/filled/cancelled/rejected/expired；
- `Fill`：qty/price/fee/time/source；
- `PositionLot`：trade date/sellable date/qty/cost；
- `CashLedger`：currency/available/frozen/settled/entry reason；
- `ReconciliationBreak`：target/order/fill/position/cash mismatch、severity、resolution；
- `KillSwitchState`：scope/reason/actor/time/effective state；
- 状态转换、账本、broker event 和审计 append-only；命令幂等。

### 风险、权限和恢复

- pre-trade risk 消费 approved target/policy/market state，不消费页面字段；
- PM 提交 target，Reviewer/PM 按 policy 审批，Trader 处理 Paper order，Admin 管权限；同一主体不能越过 SoD；
- duplicate/reorder/delayed events 可 replay；
- material reconciliation break 或 kill switch 阻止新订单；
- restart、day boundary、backup/restore 不改变最终账本；
- Paper execution 纳入统一归因。

### API 与页面

- command API 使用 authenticated subject、idempotency key、problem details 和审计；
- read API 提供 intents/orders/fills/positions/cash/breaks/statements；
- Portfolio 显示 approved target/order preview；Monitoring Execution/Rebalance/Incidents；System Users/Entitlements/Approvals；
- 全局始终显示 `paper`，不存在 Live 切换或真实账户入口。

### 决策

- ADR-0010 已冻结确定性内部 Paper Broker；
- 模拟成交参考复用 P6 费用/价格政策；
- soak 时长、告警和值班频率为 D2，但 Gate 前冻结。

### 验收

- 合法/非法状态转换、幂等、T+1、partial fill、cancel/replace、reject、disconnect/retry 通过；
- target/order/fill/position/cash 日终闭合；
- 故障注入和 restore/replay 一致；
- kill switch 和权限负向测试通过；
- 连续 soak 和日终 Artifact 完成；
- 无真实账户连接。

## Plan

### Task 1：Paper 安全 ADR 和 OMS domain

遵守 `docs/adr/0010-deterministic-internal-paper-broker.md`，新增 `domain/oms.py` 和状态机/幂等 tests。先非法 transition 和 duplicate command 红测。

### Task 2：pre-trade risk 与审批

新增 `application/order_intents.py`、permission policies 和 audit；复用 P9 approval，测试 SoD、expired/scope mismatch/kill switch denial。

### Task 3：确定性 Paper Broker

新增 `ports/broker.py`、`adapters/paper/broker.py`、clock/quote/fill policy tests；支持 ack/reject/partial/delay/disconnect 场景，禁止导入真实交易 SDK。

### Task 4：positions/cash/reconciliation

新增 position/cash ledgers、reconciliation service 和 break queue；测试 T+1、fee、corporate action、cash freeze/release、material stop。

### Task 5：migration/repository/API

新增 execution schema 或经 ADR 选择的职责 schema、append-only triggers、command/read API、cursor pagination、statement Artifact。

### Task 6：Execution UI

实现 Paper preview、orders/fills/positions/cash/breaks/kill switch 状态；危险操作需明确权限和确认；Agent 视图无操作。
Paper Execution、Rebalance、Incidents 和 kill switch 产品面按 PUI-09 执行；全局必须保持 `paper`，
不得出现 Live 切换、真实账户入口或由前端推断的执行状态。

### Task 7：replay、恢复和 soak

建立 duplicate/out-of-order/provider outage/delayed fill/restart/day-boundary/backup restore 测试；真实日历 soak 证据不能用快速单测替代。

### 验证

除全量命令外，执行状态机 property tests、PostgreSQL crash/replay、权限矩阵、故障注入、日终对账、浏览器四视口和 soak 日志。P10 Gate 不授予 P11 权限。
