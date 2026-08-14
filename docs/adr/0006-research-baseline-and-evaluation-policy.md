# ADR-0006：首个研究基线与 Outcome 评价口径

- 状态：Accepted
- 日期：2026-08-14
- 用户批准：按推荐默认冻结，P11 继续不授权

## 背景

P5 Outcome、P6 组合/回测和 P7 Timing 必须共享明确的 benchmark、再平衡、成交参考和公司行动口径。若把这些选择留到实现时临场决定，会使相同 Signal 在不同模块产生不可解释结果，也会诱发根据结果修改评价口径。

## 决策

1. 首个总体研究 benchmark 使用 CSI800；同时分别报告 CSI300 和 CSI500 分组结果。benchmark 是 `PortfolioPolicy`/`UniverseVersion` 配置，不写死在领域核心。
2. 第一再平衡频率为月度；周度只作为预先登记的敏感度分析。平台支持参数化，不以日频结果替换月度基线。
3. 第一外部回测对照引擎选择 RQAlpha，通过 adapter 隔离；若资格 spike 证明不可用，再以新 ADR 选择 LEAN，不修改内部领域合同。
4. 盘后决策的 Outcome/回测默认在下一可交易 session 使用可配置 VWAP 作为入场参考，在第 N 个可交易 session 使用相同口径退出。
5. 分红、送转、拆股、配股和退市现金流通过 total-return 公司行动账本处理；不得用无记录的前复权价格替代公司行动。
6. 费用、滑点、冲击、参与率、价格口径和日历版本进入 Run/Artifact hash。
7. P7 Timing 的 benchmark 与 P6 对齐；若 benchmark 不可交易，必须显式绑定可交易 proxy。Shadow 阶段对组合影响固定为 0。

## 边界

- 以上是第一条可复现研究基线，不是最优参数或盈利声明；
- strict 回测仍只消费 `pit_verified`；current 数据不能因采用本口径而获得严格资格；
- 实际 VWAP source 必须单独通过数据、许可、coverage 和 availability 资格；不可用时 Outcome 保持 pending/unavailable；
- 敏感度分析必须预先登记，不得选择性只展示有利结果；
- 本 ADR 不授权 Paper 或 Live 交易。

## 结果

P5 Outcome source、P6 PortfolioPolicy/realistic backtest/RQAlpha reconciliation 和 P7 labels 可以按统一合同实现。任何后续口径变更产生新 policy/version/ADR，不回写历史 View、Outcome 或 BacktestRun。
