# P2 A 股数据源覆盖与权限矩阵

日期：2026-08-10

本矩阵落实 SPEC-015、ADR-0002、ADR-0003 和 ADR-0004。`可用于原型` 只指本地 current 研究、小型合同 fixture 和内部展示。另有受限的 `private_local_research`：仅在用户显式 ack、具体端点未明确禁止 retention、显式 symbols（或身份/Universe 专用 `--all-a-share`）、domains 和本地存储目标下允许保存 `normalized_current`。它不代表通用 `raw_bulk_persistence`、严格历史、对外分发或生产决策获批。

## 1. 来源资格

| 来源 | 角色 | 成本/凭据 | 客户端代码许可 | 数据条款状态 | 获批用途 |
|---|---|---|---|---|---|
| a-share-mcp / Baostock | P2 沪深探针主源 | 免费、无 key | PyPI：BSD | 上游数据保存/再分发权待审 | 本地原型、current 研究、小型 fixture、内部展示；不直接执行持久化 |
| Baostock Python SDK | 沪深本地回填执行源 | 免费、无 key | PyPI：BSD | 非商业/再分发与具体保存边界仍需操作者核对；明确禁止时 fail closed | 显式 ack 的私人本地 raw 日线/日历，`normalized_current` only |
| AkShare | 北交所与缺失字段备用候选 | 免费、无 key | PyPI：MIT | 各网页上游条款逐端点待审；存在限流和结构变化风险 | 本地原型、current 研究、小型 fixture、内部展示 |
| Futu OpenQuoteContext | 可选沪深行情只读候选 | 本地 OpenD、行情权限；不读取账户 | SDK/数据条款分离 | 行情权限、2018+ 覆盖、保存期限和再分发权仍需操作者核对；明确禁止时 fail closed | 显式 ack 的私人本地 raw 日线，`normalized_current` only；无账户/交易能力 |
| BaoStock + AkShare/CNInfo 组合身份源 | 沪深当前身份与 CSI 历史成分执行源 | 免费、无 key | 客户端分别为 BSD/MIT；数据条款分离 | CNInfo/BaoStock 端点保存边界、限流和结构变化仍需操作者核对 | `--all-a-share` + 显式 ack 的私人本地身份/Universe，`normalized_current` only |
| 上交所/深交所/北交所 | 身份、挂牌、日历、规则、公司行动权威核验 | 公开页面/API，频率不统一 | 不适用 | 保存期限和再分发条款待逐站点审查 | 权威核验、小样本证据 |
| 巨潮/交易所/公司披露 | P3 公告权威源 | 公开页面/API，频率不统一 | 不适用 | P3 建立 license/retention policy | P3 公告证据，不在 P2 冒充新闻或 PIT 财务 |
| Tushare Pro | 备用商业候选 | Token/积分/可能付费 | 客户端与数据条款分离 | 未评审、未配置 | 当前不启用 |
| 未来持牌供应商 | 生产候选 | 待采购 | 依合同 | 必须明确存储、回测、展示和生产权 | 当前不启用 |

## 2. 字段覆盖

| 字段 | Baostock 主源 | AkShare 备用 | 权威核验 | P2 资格/警告 |
|---|---|---|---|---|
| 公司/证券/挂牌当前身份 | 沪深可用 | 沪深北候选 | 三交易所 | `normalized_current`；历史名称需独立区间证据 |
| 上市/退市日期 | 沪深样本可用 | 候选 | 三交易所 | 退市美都样本通过；不得删除退市证券 |
| 代码/名称历史 | 部分日期可见但不保证快照语义 | 候选 | 三交易所公告 | 必须版本化；不能用当前名称回填历史 |
| 交易日历 | 2018+ 样本可用 | 候选 | 三交易所 | 临时休市仍需权威核验 |
| 原始日线 OHLCV/amount | 沪深 2018+ 样本可用 | 沪深北候选 | 交易所抽样 | 只允许 `adjust_flag=3` 进入 raw bar |
| 复权因子 | 2018 样本返回空 | 候选 | 公司行动重建 | partial；不得混用复权价格代替独立因子 |
| 停牌/ST | 日线字段可用 | 候选 | 交易所 | 停牌时零成交不是缺失，也不是可交易 |
| 涨跌停价/状态 | 无独立上下限字段 | 候选/规则计算 | 交易所规则 | 必须保存规则版本和计算证据 |
| 行业有效区间 | 证监会行业快照可用 | 多分类候选 | 分类发布方 | 分类体系、版本和生效区间必须显式 |
| 指数成员有效区间 | HS300/SZ50/ZZ500 快照可用 | 候选 | 指数公司 | 仅支持有日期证据的版本 |
| 股本/自由流通股本 | 当前探针不覆盖 | 候选 | 公告/交易所 | P2 缺口；不得自动填零 |
| 分红/送转/配股 | 分红接口部分覆盖 | 候选 | 公告/交易所 | 公司行动需统一事件合同和抽样核算 |
| 公告时间和修订 | 不满足 | 不视为权威 | 巨潮/交易所/公司 | 留到 P3；P2 不授予 `pit_verified` |

## 3. 明确禁止与私人本地例外

- `strict_historical`、生产决策、通用 `raw_bulk_persistence` 和外部分发当前均无合格免费源；
- `private_local_research` 只是受限本地例外：供应商/端点明确禁止 retention 时仍阻断，且永远不能产生 `pit_verified`；
- 当前数据、检索时间或数据库入库时间不得冒充历史 `available_at`；
- 复权因子、股本、停牌或退市缺失不得填 0；
- 免费源之间的 fallback 不得静默覆盖主源观察；
- 没有单独授权时不得把测试 fixture 扩大为全市场长期缓存。

## 4. Donor 与回填路由审计

只读审计 `sources/daily_stock_analysis/data_provider/` 后，确认 donor 对 A 股使用 AkShare、Tushare、Baostock 等来源，并具备按能力路由、可选凭据延迟启用、失败留痕和熔断经验。新平台只借鉴这些模式，不复制 fetcher，也不继承其面向 current 报告的静默 fallback：

- Tushare Token 是否存在不等于数据存储、历史回测或展示权已经获批；当前仍是未启用商业候选；
- AkShare/Baostock 的客户端开源许可不等于上游数据许可；
- donor 的 Futu 集成读取真实账户持仓，不属于本工作包允许范围，因此没有迁移；新适配器只允许 SDK `OpenQuoteContext` 行情读取，代码级测试禁止任何交易上下文；
- fallback 必须形成独立观察、warning 和 provenance，不能覆盖主源记录。

进一步的 endpoint 级审计发现：

- donor A 股历史日线按东财 → 新浪 → 腾讯 fallback，但三路都显式使用 `qfq`，因此不得写入平台 raw/unadjusted bar；
- 新浪/腾讯缺字段路径会用窗口内 `pct_change` 并对首行填 0，违反缺失显式表达原则；
- `stocks.index.json` 是 current code/name alias 索引，没有有效区间和 `available_at`，不能冒充 Security Master 历史或 CSI300/CSI500 Universe；
- 值得重写借鉴的仅是有界 retry+jitter、限流/熔断、可终止超时、临时文件原子替换和 last-good fallback；每次真实 winner、请求参数、调整口径和失败诊断仍必须进入本平台 provenance。

## 5. 当前可执行私人本地覆盖

| provider_id | 可执行域 | 市场 | 硬约束 | 仍不可用 |
|---|---|---|---|---|
| `baostock_sdk` | `raw_daily_bar`、`trading_calendar` | XSHG/XSHE | `frequency=d`、`adjustflag=3`、显式 ack/symbol/domain/DSN/Parquet root | XBSE、Security Master、历史 Universe、股本、公司行动 |
| `futu_quote` | `raw_daily_bar` | XSHG/XSHE | `OpenQuoteContext`、`AuType.NONE`、显式 ack/symbol/domain/DSN/Parquet root | 日历、Security Master、历史 Universe、股本、公司行动、所有账户与交易能力 |
| `a_share_identity_universe` | `security_master`、`universe` | XSHG/XSHE | `--all-a-share`、显式 ack/domain/DSN/Parquet root；法定名称缺失拒绝；当前字段用真实观察日 | XBSE、历史法定名称/代码证据、历史可交易状态、股本、公司行动、PIT 可用时间 |

`financial-data-hub` 是来源选择与对照入口；它不会绕过 `ProviderRegistry`、许可门或 canonical sink。AkShare 仅在组合身份源中调用 CNInfo 公司资料端点，没有把 donor 已审计的 qfq 历史价接入 raw sink。
