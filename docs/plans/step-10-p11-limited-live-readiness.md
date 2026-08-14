# Step 10 Spec / Plan：P11 Limited Live Readiness

> 状态：`AUTH`  
> 对应：Plan P11-W01–W03/Gate、Roadmap Step 10  
> 关联 SPEC：036–038、055–056  
> 当前结论：只允许规划和只读准备；不授权实现真实交易 adapter、连接账户或下单

## Spec

### 目标

定义未来从 Paper 到 read-only broker reconciliation、human-approved minimal live 和 limited automation 的安全门。此文件不是交易授权，也不是券商选择结果。

### 强制前提

- 用户另行明确授权券商、账户、市场、标的、单笔/单日金额、有效期和允许动作；
- P10 长期 soak、对账、恢复、kill switch 和权限 Gate 稳定；
- 券商 API、A 股权限、许可、行情/交易时钟、rate limit、重连和法律/合规审查完成；
- secret manager、2FA/unlock、审计、值班和 incident response 就绪；
- read-only reconciliation 先于任何 order command；
- Agent 永远不获得账户密钥、审批权或直接交易权限。

### 分级状态

```text
paper_verified
→ broker_read_only
→ live_preview_only
→ human_approved_minimal_live
→ policy_limited_automation
→ suspended/rolled_back
```

每一级有独立 Approval、effective interval、limits、health criteria 和 rollback。环境不能由 URL/header/前端开关提升。

### Live 合同

- Paper/Live 共享 Target/Intent/Risk/Approval/OMS 核心；只有 broker adapter 和凭证不同；
- final preview 明确 account/side/security/qty/price/amount/fees/limits；
- per-order/day/security/account limits 在服务端和 broker 侧双重检查；
- idempotency、broker order id、fill/position/cash reconciliation 完整；
- material break、stale market data、permission/clock mismatch、disconnect 立即失败关闭；
- kill switch 可在不依赖 Agent/模型的路径触发。

### 当前允许的交付

- broker capability/许可评估模板；
- security threat model；
- authorization checklist；
- read-only reconciliation 合同和 fake adapter tests；
- 不含凭证、不发网络命令的 preview schema。

### 当前禁止的交付

- 真实 broker order endpoint adapter；
- 账户登录、unlock、2FA 或 secret 保存；
- 真实下单、撤单、改单；
- 自动化 Live 开关；
- 用 Paper 测试结果推断 Live 已安全。

## Plan（取得新授权后才能激活）

### Task 0：授权与 Broker ADR

新增明确记录授权范围和失效条件的 ADR；完成 capability/license/security spike。没有 Accepted ADR 时后续 Task 均不得开始。

### Task 1：read-only reconciliation

在独立凭证/网络边界内读取账户快照，与 Paper/内部 ledger 对账；先 fake/contract test，再受控真实只读 smoke test。

### Task 2：preview-only adapter

构造 broker request 但物理禁止发送；校验 symbol/side/qty/price/account/limits/idempotency 和审批链。

### Task 3：human-approved minimal live

每笔双重人工确认、极小限额、单一账户/标的白名单、实时监控和即时 kill switch；任何异常回退 read-only/Paper。

### Task 4：有限自动化评审

只有累计 live evidence、零重大 reconciliation break、恢复演练和新 Approval 后才评估；默认保持关闭。

### Gate Evidence

授权文件、ADR、安全审查、Paper soak、read-only reconciliation、preview、人工批准记录、limits、kill switch 演练、incident/on-call 和 rollback 全部可审计。测试通过或策略表现都不能替代授权。
