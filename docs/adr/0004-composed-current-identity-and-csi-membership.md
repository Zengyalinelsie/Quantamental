# ADR-0004：组合式当前身份与 CSI 历史成分回填

- 状态：Accepted
- 日期：2026-08-10
- 修订关系：仅对 ADR-0003 的显式 symbols 限制增加一个窄例外；不改变 retention、PIT、生产和外部分发禁令

## 背景

用户明确批准在私人本地研究环境中补充真实 Security Master，以及 2018 年以来的沪深 300/中证 500 成分。ADR-0003 原先要求所有可执行计划都提供显式 symbols，并把这两个域保持为 unavailable；该要求无法表达“扫描供应商支持的全部沪深 A 股身份”。

只读 donor 审计同时确认：`sources/daily_stock_analysis` 的 current code/name 索引不是历史 Security Master，它的东财/新浪/腾讯历史价均为 `qfq`。donor 只能提供有界 retry、限流、熔断、原子缓存和 last-good fallback 的重写参考，不能成为本适配器的数据真源。

## 决策

1. 新增组合 provider `a_share_identity_universe`，其 Provider Registry 能力仅包括 `security_identity`、`identifier_history`、`listing_status`、`industry_membership` 和 `benchmark_membership`。
2. 该 provider 只允许 `private_local_research`，信任上限固定为 `normalized_current`。禁止 `strict_historical`、`pit_verified`、生产决策、通用 bulk persistence 和外部分发。
3. CLI 新增与 `--symbols` 互斥的 `--all-a-share` 明示开关。该例外只允许 `security_master` 和 `universe`，仍必须提供 ack、domains、本地 PostgreSQL DSN 和 Parquet root。
4. 当前可执行市场固定为 XSHG/XSHE；`--all-a-share` 表示扫描该 provider 当前声明的全部市场，不得解读为 XBSE 已覆盖。北交所 Security Master 仍是显式缺口。
5. Security Master 组合来源为：
   - BaoStock `query_stock_basic`：代码、简称、上市/退市日期和当前挂牌状态；
   - BaoStock `query_stock_industry`：当前证监会行业名称和分类体系；
   - AkShare `stock_profile_cninfo`：公司法定名称。法定名称不可用时拒绝该行，不用证券简称冒充。
6. 当前代码、简称、状态和行业的 `observed_on` 必须使用真实检索日，不得改写成计划起始日或历史 PIT 日期。供应商未给行业代码时保存 `NULL`，不得制造 sentinel 或填零。
7. 沪深 300 `000300` 和中证 500 `000905` 使用 BaoStock 的带日期成员接口逐交易日取快照，并压缩为不重叠的半开有效区间。该“历史成员日期”不等于当时可用时间，结果仍为 `normalized_current`。
8. 写入的指数成员默认 `research_eligible=true`、`benchmark_member=true`；在历史停牌、ST、涨跌停和挂牌状态尚未联合验证前，必须保存 `tradable_eligible=false` 和 `tradability_not_evaluated`。
9. 当前身份使用确定性 Company/Security/Listing ID。历史成分代码仅可回退匹配上市区间兼容的当前 Listing；代码变化、代码复用或身份缺失无法确认时 fail closed，不猜测合并。
10. `financial-data-hub` 继续用于来源选择与交叉核验，Futu 继续只提供 `OpenQuoteContext` raw 行情；二者都不能绕过本 provider 合同。没有引入账户、持仓、订单或交易上下文。
11. Canonical UniverseVersion 必须保存 `trust_state`、provider/source、`retrieved_at`、`system_as_of` 和 DatasetVersion；`normalized_current` 的 `available_at` 必须为 `NULL`，严格 PIT consumer/view 只能读取 `pit_verified`。
12. 每日指数快照必须通过非空、成分数量、日变化率和 provider `updateDate` 质量门；当前 Security Master 必须通过最低行数和法定名称覆盖率，重复/错配身份直接 fail closed。真实 provider 调用必须有显式限流和单次超时。
13. 成功并提交的 checkpoint 可恢复；尚未落库的 fetch payload 不宣称 durable staging。长区间真实运行按年度独立 plan 执行，失败只重取未成功年度。

## 结果

平台获得了按成功 checkpoint 恢复、可审计的沪深当前身份与 CSI 历史成分采集/持久化能力，并保留 DatasetVersion、checkpoint、质量和覆盖率。代价是 CNInfo 逐证券查询成本较高，免费端点结构和限流可能变化，北交所、可靠代码/名称历史、fetch payload staging 和历史可交易状态仍未解决。

自动化测试只使用 fake SDK/connection；本 ADR 和代码提交不表示真实数据已经下载或数据库已经填充，也不证明供应商稳定性、数据科学有效性或任何模型有效性。
