# ADR-0003：私人本地研究数据持久化边界

- 状态：Accepted
- 日期：2026-08-10
- 修订关系：在私人本地研究这一窄用途上补充 ADR-0002；不改变其对通用批量保存、外部分发、严格历史和生产决策的禁止

后续修订：ADR-0004 只为组合式沪深 Security Master/CSI 历史成分增加 `--all-a-share` 明示例外；本 ADR 的 retention、可信状态、生产和外部分发限制继续有效。

## 背景

ADR-0002 在供应商数据条款尚未完成商业审查时，默认阻断免费源的通用批量持久化。用户随后明确批准：可在本人本地研究环境中保存免费源和 Futu 的真实 A 股数据，但只能标记为 `normalized_current`，不得外部分发、不得用于 `strict_historical` 或生产决策，也不得提升为 `pit_verified`。该批准不是法律意见；如果供应商或具体端点条款明确禁止保存，仍必须拒绝。

`sources/daily_stock_analysis` 只读审计还确认：其 AkShare A 股历史价 fallback 全部使用 `qfq`，缺少完整 adjustment/provenance；其 `stocks.index.json` 是 current 代码名称索引，不是历史沪深 300/中证 500 Universe。因此 donor 只能提供容错模式参考，不能直接成为 raw bar 或 PIT 真源。

## 决策

1. 新增独立用途 `private_local_research`。它不等于 `raw_bulk_persistence`，也不会隐式获得外部分发、生产或历史回测资格。
2. 该用途的输出必须严格为 `normalized_current`；`retrieved_at`、文件时间和数据库写入时间均不能充当历史 `available_at`。
3. 执行 CLI 默认 dry-run。真实执行必须同时提供：
   - `--private-local-research-ack`；
   - 显式 provider、symbols、domains；
   - 显式本地 PostgreSQL DSN 和 Parquet root；
   - Provider Registry 对每个字段和市场的许可。
4. `retention_prohibited=true` 是更高优先级的硬阻断。用户 ack 不能覆盖供应商明确的保存禁令。
5. 首批可执行能力仅包括：
   - `baostock_sdk`：沪深 raw/unadjusted 日线与交易日历；日线必须 `frequency="d"`、`adjustflag="3"`；
   - `futu_quote`：显式沪深标的 raw/unadjusted 日线；只允许 `OpenQuoteContext`，不创建或查询任何账户、交易、订单或持仓上下文。
6. 直接 BaoStock SDK 与 a-share-mcp/BaoStock 使用不同 provider ID，避免把传输路径和资格混为一谈。`financial-data-hub` 用于来源路由和对照，不作为绕过平台 provider contract 的隐式运行时后门。
7. source adapter 先转换为 provider-neutral staged payload，再由 canonical sink：
   - 注册不可变 DatasetVersion；
   - 写 raw bar Parquet；
   - 写 PostgreSQL partition manifest、daily market state、calendar、checkpoint、质量和覆盖率；
   - 使用有效日期代码映射解析现有 Listing，缺失或歧义时 fail closed。
8. BaoStock/AkShare/Futu 不能补齐的 Security Master、历史 Universe、股本和公司行动保持 unavailable，不填零、不伪造、不用 current 索引冒充历史成员。
9. donor AkShare 的 qfq 结果不得写入 raw bar。未来接入 AkShare 时必须按真实上游端点拆 provider ID，记录实际 winner、请求参数、adjustment、单位、retrieved_at、cutoff 和 warning；fallback 不能无痕覆盖主观察。

## 结果

优点：

- 私人研究可以小范围、可恢复、可追溯地保存真实行情，同时不降低 PIT 和生产门槛；
- Futu 能作为显式只读行情备用源，不引入账户或交易能力；
- 明确区分“本地个人保存”与“通用 raw bulk/再分发授权”。

代价与剩余缺口：

- 该决定不提供任何商业使用或再分发权保证；
- 沪深 300/中证 500 历史成员、全市场 Security Master、历史股本和公司行动仍需独立合格来源；
- 当前实现和测试没有下载真实数据，也没有写真实数据库；真实运行必须由 Data Operator 在本地显式执行并检查条款、覆盖率和质量报告；
- `normalized_current` 数据不能用于严格历史回测，因而不能证明模型科学有效。

## 被否决方案

- 把用户本地保存批准扩大成通用 `raw_bulk_persistence` 或外部分发许可；
- 使用 donor 的 qfq 历史价填充 raw/unadjusted 表；
- 使用 current 股票代码索引重建历史 CSI Universe；
- 因 Futu SDK 同时包含交易接口而引入账户或执行上下文；
- 为让页面或覆盖率完整而填入假数据、零值或推断的 PIT 时间。
