# ADR-0010：确定性内部 Paper Broker

- 状态：Accepted
- 日期：2026-08-14
- 授权边界：仅 Paper；P11 继续不授权

## 背景

P10 需要验证 OMS、订单状态、成交、持仓现金、对账、恢复和 kill switch。直接接券商模拟环境会引入账户、网络、时钟和供应商状态，降低测试确定性，并容易与真实交易授权混淆。

## 决策

1. P10 第一版使用确定性内部 Paper Broker adapter，不连接任何真实或券商模拟账户。
2. Paper/未来 Live 共享 Target、Intent、Risk、Approval、OMS、Position、Cash 和 Reconciliation 核心；broker adapter 独立。
3. Paper fill policy 复用 ADR-0006 的 session/VWAP/费用/公司行动版本，并支持 ack/reject/partial fill/delay/disconnect 的确定性故障 fixture。
4. 全局显式显示 `deployment_stage=paper`；不存在请求参数、URL、header 或前端开关提升到 Live。
5. 不安装或导入真实交易 SDK，不保存账户凭证，不开放真实 order endpoint。
6. P11 只有在新的明确授权和 Broker/Security ADR 后才能开始。

## 结果

P10 可以在安全边界内完成连续 soak、恢复、replay、日终对账和执行归因。Paper 测试结果不构成真实交易授权或模型有效证据。
