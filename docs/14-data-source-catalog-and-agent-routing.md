# 平台数据源总清单与 Agent 选择路由

> 状态：平台可用、候选和只读 donor 数据资产的统一入口。本文帮助 Agent 选源，
> 不是 Data Source Qualification 通过记录，也不改变 ADR-0002/0003/0004 的门槛。
>
> 盘点日期：2026-08-10（Asia/Shanghai）。

## 1. Agent 强制选源流程

Agent 在请求任何数据前必须依次执行：

1. 明确市场、数据域、频率、标的范围、日期范围和新鲜度；
2. 明确 `data_mode`：`current_research` 还是 `strict_historical`；
3. 明确用途：临时查询、私人本地保存、内部展示、严格回测还是生产决策；
4. 从本文的领域路由选择一个主源，只在缺字段、空结果、超时或重大交叉核验时调用备源；
5. 查询 `ProviderRegistry` 和适用 ADR，本文不能替代运行时许可门；
6. 保存 provider、参数、cutoff、retrieved time、单位、币种、调整口径、warning 和许可；
7. 来源冲突形成并存观察和诊断，不静默覆盖；缺失不填 0；
8. `strict_historical` 只读取 `pit_verified` 且 `available_at <= decision_time` 的数据；
9. 任何免费源、Futu、Factor Service current 缓存或 Agent 抽取结果都不能自行晋升为
   `pit_verified`；
10. 所有行情/研究适配器只读，不连接真实交易账户，不下单、不撤单。

`financial-data-hub` 是统一选源入口，但它只负责路由与对照，不能绕过平台的
Provider Registry、许可、canonical sink 或 PIT 门。

## 2. 数据源总表

| 来源/Provider | 可覆盖数据域 | 当前接入状态 | 初始信任上限 | 允许/建议用途 | 硬限制 |
|---|---|---|---|---|---|
| `a_share_mcp_baostock` | 沪深身份探针、日历、日线、状态、行业、指数成员样本 | 原型查询可用 | `normalized_current` | 小样本、current 研究、交叉核验 | 无公告可用时间；不直接批量持久化 |
| `baostock_sdk` | 沪深 raw 日线、交易日历 | 已实现并真实落库日历 | `normalized_current` | 经显式 ack 的私人本地研究 | 日线必须 `adjustflag=3`；不含北交所和完整公司行动 |
| `a_share_identity_universe` | 沪深 Security Master、行业、CSI300/500 成分 | 代码收尾，尚未真实执行 | `normalized_current` | 经显式 ack 的私人本地研究 | current 身份和历史检索不等于 PIT；不含北交所 |
| `akshare` / CNInfo 网页端点 | 身份补充、指数、财务、宏观、新闻、公告候选 | fallback 候选；部分用于组合身份源 | `normalized_current` | current 研究、小型 fixture、补字段 | 网页结构/限流/端点条款逐项审查；不得接入 qfq 结果作为 raw bar |
| `futu_quote` | 沪深 raw 日线；未来可评估只读资讯 | raw 日线 adapter 已实现 | `normalized_current` | 私人本地研究备源 | 只允许 `OpenQuoteContext`；禁止账户、持仓、订单和交易上下文 |
| Wind | 身份、行情、三表、预期、行业、指数、公司行动等候选 | 用户有能力，接口和许可待提供 | 待资格审查 | 高优先级结构化候选 | 不因付费自动获得 PIT；需确认历史修订、可用时间和本地保存权 |
| Factor Service / iFinD/THS | A 股三表、日行情、股本、市值、汇率、宏观等 | 文档可用；live metadata 未验证 | `normalized_current` | 结构化 current 主候选、交叉对账 | 部分查询有 read-through cache 写入；字段数、覆盖和 PIT 时间存在冲突 |
| SneAgent | PDF 主表/notes 抽取，报告聚焦港股五表 | 内部服务候选 | `raw` / `normalized_current` | 缺字段、notes、复杂版式、冲突复核 | 内部 `verified` 不等于 `pit_verified`；单份约 7–13 分钟 |
| 巨潮/交易所/公司披露 | 公告、PDF、发布时间、更正/撤回、原始证据 | P3 官方证据合同已实现 | `raw`；治理后可形成 PIT 观察 | 公告与财务事实权威证据 | 保存/再分发逐站点审查；日期精度不可靠时用保守时间 |
| 上交所/深交所/北交所 | 身份、挂牌、日历、规则、公司行动 | 权威核验候选 | `raw` | 权威抽样和争议核验 | API/页面不统一，端点许可待审 |
| 中证指数公司 | CSI300/500 定义和成员 | 权威核验候选 | `raw` | Universe 版本核验 | 历史文件、下载许可和有效区间需固化 |
| XE（经 Factor Service） | HKD/CNY/USD 交叉汇率 | 文档称 2021–2026 已入库 | `normalized_current` | current 估值/换算候选 | 必须保存货币对、日期、source；不能把 current 汇率回填历史 |
| 官方宏观来源/Factor Service | 国债、LPR、Shibor、回购、GDP、CPI、社融、M2、投资、消费、贸易 | 部分内部表已入库 | `normalized_current` | current 宏观特征候选 | 需要 release/available time 才能进入 strict historical |
| `sources/daily_stock_analysis` donor | 多市场行情、基本面、新闻搜索、产品和容错模式 | 永久只读，不是 runtime provider | 不适用 | 借鉴 adapter/缓存/熔断/新闻产品模式 | 不复制 current/qfq/静默 fallback；不修改 donor |
| Tushare Pro | A 股结构化数据候选 | 未配置、未评审 | 待资格审查 | 未来商业备源 | 需要 token/积分/许可；当前不启用 |
| yfinance | 全球行情/财务候选 | 未接入新平台 | `normalized_current` | 非 A 股或全球交叉核验 | 非官方、限流、修订/PIT 不完备 |

## 3. 按数据域的 Agent 路由

| 数据需求 | 主源 | 备源/权威核验 | 当前可用模式 |
|---|---|---|---|
| 沪深 Security Master | `a_share_identity_universe` | 交易所、Wind、AkShare | `current_research` / 私人本地 |
| CSI300/500 成分 | 组合身份源 | 中证指数公司、Wind | `normalized_current`；历史 PIT 尚未证明 |
| 交易日历 | `baostock_sdk` | 交易所、AkShare | `normalized_current`；已落库 2018+ |
| raw 日线 OHLCV | `baostock_sdk` | Futu quote、Wind、交易所抽样 | 私人本地 `normalized_current` |
| 股本/自由流通/市值 | Factor Service 或 Wind | 公告/交易所 | 候选，尚未接入 canonical sink |
| 公司行动 | Wind 或官方交易所/公告 | AkShare/BaoStock 候选 | 当前缺口；不得填 0 |
| A 股三表 current | 通过资格审查的 Wind；否则 Factor Service | 官方公告抽样对账 | `normalized_current` |
| A 股三表 strict history | 具有修订和可用时间的结构化源 | 官方公告版本链 + 人工/程序核验 | 当前无通用合格源 |
| PDF notes/缺失字段 | SneAgent | 人工复核、官方 PDF | `raw` / `normalized_current` |
| 汇率 | Factor Service/XE 或 Wind | 官方中间价/市场来源 | current；历史需 release/cutoff 证据 |
| 国内宏观 | 官方来源或 Factor Service | Wind | current；严格历史需发布日期账本 |
| 公司公告 | 巨潮/交易所/公司披露 | 官方交叉核验 | P3 evidence ledger |
| 新闻/事件 | 官方公告优先，AkShare/Futu 只读资讯候选 | donor 的搜索路由模式 | P8 前仅公告；新闻 runtime 尚未迁移 |
| 全球行情/财务 | Wind 或 yfinance 候选 | 官方 filing | 当前不属于 A 股 P2 主链 |

## 4. 财务三表结论

A 股财务三表的生产摄取**不需要从 PDF 抽取起步**。当前更合适的分层是：

1. Wind 或结构化 Factor Service 负责批量获取三表候选观察；
2. 巨潮、交易所和公司公告负责原始证据、公告时间、修订链与争议核验；
3. SneAgent 作为 PDF/notes 的受控补漏和交叉验证工具，不作为未经核验的数值权威；
4. 所有来源各自产生 `FactObservation`，不得静默覆盖；只有完成时间、修订、许可、
   映射和质量治理的观察才可晋升为 `pit_verified`。

因此，PDF 仍然重要，但它主要承担“证据和修订真源”，不必承担每家公司、每期、
每个字段的首选结构化抽取。对当前两个内部服务的最诚实结论是：

- Factor Service 可以作为 A 股 `normalized_current` 候选适配器；现有文档不足以证明
  全市场、2018+ 或 strict PIT 覆盖；
- SneAgent 已具备复杂 PDF 与 notes 抽取能力，但发布报告聚焦港股五表，成本和延迟也
  不适合作为 A 股全市场批量主源；
- Wind 可能是更完整的结构化主源，但在取得接口、许可、历史修订和可用时间证据前，
  不能预先把它标为 `pit_verified`。

## 5. 本次盘点证据

本次只读取用户提供的本地文档，没有复制 PDF 到仓库，也没有记录 API key：

| 文档 | 页数 | SHA-256 | 用途 |
|---|---:|---|---|
| `202608-SneAgent财报三表抽取发布报告.pdf` | 4 | `ef2308c7e0327a865eb385ec3c28c8be670e66322e7a31a74fe6b2f9942c005c` | SneAgent 能力、验证口径和实验摘要 |
| `Factor Service 使用文档.pdf` | 23 | `bdd9b5460f633f340e9a5309477e35c92b0f7a403c40951eaabea8f1e2decc24` | 表、字段、查询 API、缓存和错误合同 |
| `Fin-Copliot - Agent数据需求.pdf` | 18 | `20b993a5cc7e045ec561eb209f2bd98f34cb8a2b4ddd18d775d7d162f5ec35ee` | 生产 Factor Service 元数据样例、股票/汇率/宏观资产与覆盖状态 |

2026-08-10 对文档所列开发服务执行了只读 `health`、`tables`、`table/detail` 探测，
三次连接均被服务端 reset。没有调用可能触发同花顺外部查询和本地缓存写入的
`factor/query` 或 `table/query`。因此本文区分“文档声明”和“已在线验证”，不把接口
示例当成当前可用性证据。

第三份文档包含明文 Factor Service Bearer token 和 iFinD access token。本文没有复制
任何凭证，也没有用这些凭证发请求。原凭证应立即吊销/轮换；源文档应替换为环境变量
占位符后再传播。Agent 不得从文档、聊天、Git、日志或 fixture 获取运行凭证。

## 6. 已知内部财务资产

### 6.1 Factor Service

文档声明服务提供统一 HTTP API，并接入以下财务表：

| 市场 | 逻辑表 | 文档声明字段/因子数 | 数据来源 | 当前判断 |
|---|---|---:|---|---|
| A 股 | `balance_sheet` | 使用文档 171；生产 meta 样例 133 | iFinD API 缓存 | `normalized_current` 候选；字段数待裁决 |
| A 股 | `income_statement` | 使用文档 115；生产 meta 样例未展示 | iFinD API 缓存 | `normalized_current` 候选；live meta 待取 |
| A 股 | `cash_flow` | 使用文档 141；生产 meta 样例 110 | iFinD API 缓存 | `normalized_current` 候选；字段数待裁决 |
| 港股 | `hk_balance_sheet` | 51 | INF `fin_db.ods` | 待资格审查 |
| 港股 | `hk_income_statement` | 38 | INF `fin_db.ods` | 待资格审查 |
| 港股 | `hk_cash_flow` | 25 | INF `fin_db.ods` | 待资格审查 |
| 港股 | 三张 `*_detail` KV 表 | 动态 | INF `fin_db.ods` | notes/非标准字段候选 |

服务能力包括：

- v1 按限定名 `table_name.factor_name` 或整表查询；
- v2 静态 metadata、表详情、字段搜索、表查询和计数；
- 股票代码使用纯数字，报告期使用 `report_period_end`；
- v2 查询显式选择一个主键和一个日期字段，支持分页，单次最多 5,000 行；
- 服务区分参数、表/字段、外部 API、THS API 和数据库错误。

但 A 股部分存在硬限制：文档明确写明 iFinD **未采购**，只缓存过近 5 年沪深 300
范围内的查询。这不覆盖中证 500、A 股全市场或完整 2018+ 数据，也没有证明退市公司、
修订前版本或历史可用时间的覆盖。

第三份文档还列出了以下已建或规划资产。勾选只代表该内部项目文档的状态，不等于本平台
已接入、数据许可已通过或历史语义已验证：

| 领域 | 表/资产 | 文档状态与范围 | 平台判断 |
|---|---|---|---|
| 外汇 | `ths_fx_exchange_rate` | XE；HKD/CNY/USD 两两换算；2021–2026 | current 候选；需核对缺口、时区和使用许可 |
| 股本 | `ths_stock_daily_capital` | 总股本、自由流通、流通、限售；文档称暂到 2025 | P2 股本候选；与示例查询 2026 的口径冲突待核 |
| 日行情 | `ths_stock_daily_quote` | OHLC、pre-close、VWAP、成交量额、换手 | P2 raw bar 备源候选；必须核对复权/原始口径 |
| 市值 | `ths_stock_daily_capital` | 总市值、流通市值；文档称暂到 2025 | current 估值候选；历史计算仍需当时股本 |
| 预期/评级/估值 | consensus、评级明细、预测估值 | 标为 P0 或只有标题，没有可执行样例 | 规划资产，不得当作已可用 |
| 其他个股 | 风险参数、估值、Z 值、分红、研发、财报新准则 | 只有标题或空代码块 | 未证实，不进入 Agent 自动路由 |
| 利率 | 国债收益率、LPR、Shibor、存款类机构回购、HIBOR | 文档勾选已接入 | current 宏观候选 |
| 宏观 | GDP、CPI、海关货运、社融、M2、固定资产投资、社零、进出口 | 多数表覆盖 2021 至 2026-06/07 | current 宏观候选；需补发布日期和修订账本 |
| 宏观 | PPI | 文档标记问号 | unavailable，禁止自动 fallback 为 0 |

文档给出的若干宏观表实际行数为 54–66 行，最早日期在 2021-01 至 2021-03，最新日期
为 2026-06。这个覆盖可以支撑 current 研究探针，但不能支撑 2018+ 全周期，也不能只凭
`period_end` 避免宏观发布日期前瞻。

### 6.2 SneAgent

发布报告描述的是港股财报主表和 notes 抽取 V2：支持五表抽取、notes 展开，并输出
业务 scratch Excel。调用形态为 PDF URL 加抽取请求；鉴权信息必须通过部署环境提供，
不得进入仓库。

报告给出的验证规则是：`status == pass`、`formula` 非空且 `warning` 为空时才算
verified。该规则有价值，但这里的 verified 是抽取流程内部状态，**不等于平台的
`pit_verified`**；后者还要求官方证据、可用时间、系统时间、修订连续性、字段映射、
许可和治理运行全部通过。

报告的 dev 实验使用“模型预打标 + 人工修正”的 GT，列出约 89.7%–92.8% 的全局
macro precision、约 83.2%–85.8% 的覆盖率，以及多个 micro 指标。单份文档没有给出
完整样本构成、置信区间、公司/年份分层和独立复现材料，因此这些结果只能用于工具选型，
不能用于声明科学有效或生产正确。

平均单份任务约 7–13 分钟，并伴随大量 token、agent 和 tool 调用。由此建议：

- 适合：结构化源缺字段、notes 展开、供应商冲突、复杂版式和人工复核队列；
- 不适合：A 股全市场所有历史报告的第一主链路；
- 输出默认先进入 `raw` 或 `normalized_current` 候选观察，并保留公式、warning、模型、
  prompt、工具输入、原始响应和解析版本。

### 6.3 Wind

用户确认已有 Wind 数据能力，但本次没有 Wind 接口文档、样例响应或许可条款，因此只登记
为高优先级候选，不推断其权限和 PIT 能力。接入前至少要回答：

- 使用 WindPy、终端导出、数据库还是内部代理服务；
- A 股、退市股、沪深 300/中证 500 和 2018+ 覆盖；
- 原始/更正报告、公告时间、实际可用时间和历史快照接口；
- 单季、累计、合并/母公司、调整前/调整后、单位和币种语义；
- 批量下载、速率、并发、本地持久化、保存期、回测和展示许可；
- 来源文档 ID、provider record ID、更新时间与修订序列；
- 是否允许保存原始响应或只能保存派生结果。

在这些问题回答前，Wind 数据不得因品牌或付费属性自动获得 `pit_verified` 标签。

### 6.4 官方公告/PDF

官方公告的优势是文档版本、发布时间、更正/撤回关系和原始披露语义；劣势是结构化成本高，
部分索引只提供日期精度，PDF 的保存和再分发也需要单独审查。

平台不要求每条结构化事实都实时重跑 PDF 抽取，但要求任一正式事实至少能够追到：

- 官方或获批供应商记录；
- 原始 URL、公告/文档 ID 和内容哈希；
- `announced_at`、保守且不前瞻的 `available_at`；
- 原始版本、更正版本和撤回关系；
- 对应的字段映射、质量结果和 DatasetVersion。

## 7. 当前不能合并裁决的冲突

以下冲突必须由服务元数据或负责人澄清，平台不得擅自选择：

1. Factor Service 概览写 `balance_sheet=171`、`cash_flow=141`，生产 meta 样例写
   `balance_sheet=133`、`cash_flow=110`；可能是版本差异、可查询字段子集或文档过期。
2. 第一份使用文档的业务成功码为 `0`，生产样例为 `20000`。adapter 必须按服务版本
   显式配置，不能把其中一个硬编码成所有环境的真值。
3. 文档说明 v2 可以按 `release_date` 等日期字段查询，但没有证明 A 股三表实际把
   `release_date`、`announced_at` 或 `available_at` 放入各自 `filter_dates`。
4. A 股三表因子总数为 427，连同文档列出的港股宽表 114 个正好是 541；但动态 KV
   表不计数。服务对“541 个因子”的版本边界应由 live metadata 固化。
5. Factor Service 的查询会在调用第三方 API 后写缓存。只读研究客户端必须明确哪些
   endpoint 纯读、哪些 endpoint 有 read-through write 副作用。
6. `ths_stock_daily_capital` 文本称暂时入库到 2025，示例日期却查询 2026-07；覆盖截止
   必须以只读 count/metadata 和 DatasetVersion 为准。
7. SneAgent 的内部 `verified` 与平台 `pit_verified` 名称相近但含义不同，接入时必须
   保留两个独立字段，禁止自动映射。

## 8. 财务来源路由

| 需求 | 首选 | 备选/核验 | 允许的初始信任状态 |
|---|---|---|---|
| A 股当前三表批量候选 | 通过资格审查的 Wind；否则 Factor Service 缓存 | 官方公告抽样对账 | `normalized_current` |
| A 股 strict historical | 具有修订与可用时间证据的结构化源 | 官方公告版本链 + 人工/程序核验 | 治理运行后才可 `pit_verified` |
| 缺失字段/notes | SneAgent | 人工复核、官方 PDF | `raw` / `normalized_current` |
| 供应商冲突 | 官方披露优先作为事实裁决证据 | Wind、Factor Service、SneAgent 观察并存 | 冲突解除前阻断 |
| 港股主表/notes | INF 宽表/KV + SneAgent | 官方港交所/公司披露 | 待单独资格审查 |

来源优先级不是静态覆盖规则。Fallback 必须生成新的来源观察；多源值不一致时保留全部
观察、质量问题和权威规则版本。

## 9. 财务数据接入合同

建议在 `platform/` 中分别实现只读 adapter，而不是把供应商 SDK 或 HTTP 细节放进领域层：

```text
Wind adapter ───────────────┐
Factor Service adapter ─────┼─> ProviderFinancialRow
SneAgent extraction adapter ┤        │
Official disclosure adapter ┘        v
                               mapping + quality
                                      │
                                      v
                               FactObservation
```

每条 `ProviderFinancialRow` 至少需要：

- provider、provider record ID、股票/公司标识；
- statement type、report period、period type、合并/母公司口径；
- provider field、原值、单位、币种和缩放；
- 原始/更正报告类型、revision sequence；
- `announced_at`、`available_at`、provider updated time、retrieved time；
- 原始文档/响应 URL、hash 或受限证据引用；
- license、retention、redistribution、backtest 和 display 权限；
- provider warning、抽取 verify 状态和 source quality。

接入后的固定规则：

1. provider 字段只通过版本化 Mapping Registry 进入 canonical metric；
2. 缺失、无权限、单位冲突和币种冲突不得填 0；
3. read-through cache 副作用必须在 port 中显式声明，单元测试只用录制 fixture；
4. current 摄取不能被历史回测读取；
5. PIT 晋升产生新治理记录，不回写或覆盖原观察；
6. SneAgent 不拥有权威选择、trust 晋升或交易权限。

## 10. 对 P3-W04 的调整

真实 PIT Fixture Pack 不需要把“每张报表都先从 PDF 抽取”作为完成条件。后续样例应采用：

- 3–5 家真实公司、至少两个真实更正链；
- 官方公告 URL/ID/hash/时间作为证据锚点；
- Wind 或 Factor Service 的结构化观察作为候选值（取得可重放样例和许可后）；
- SneAgent 只覆盖缺字段、notes、单位、一次性项目和复杂版式案例；
- current/strict 查询必须在修订前后产生预期差异；
- 供应商与官方不一致时保留冲突并阻断，而不是用 PDF 或供应商值静默覆盖另一方。

在 Factor Service live metadata、Wind 合同和可重放样例到位前，P3-W04 可以继续建设
adapter 合同、离线 TDD 和官方证据样例，但 P3 Capability Gate 不应宣称通过。

## 11. 下一步资产补齐

1. 获取 Wind 接口文档、字段字典、两只股票的原始/更正样例和本地保存许可；
2. 在可访问内部网络时冻结 Factor Service v2 的 `tables`、三表 `table/detail` 和
   `columns/search` 响应为测试 fixture，禁止在单元测试中触发第三方查询；
3. 确认 Factor Service 三表实际日期字段、当前字段数和近 5 年缓存的精确起止/成员范围；
4. 为 Factor Service、Wind、SneAgent 各写一份 provider qualification 记录；
5. 先用 3–5 家真实公司做交叉对账，再决定 A 股三表主源和 fallback 顺序；
6. 所有凭证只进入本地密钥管理或环境变量，不进入 Git、日志、fixture 或文档。

上述工作只证明来源和系统合同是否可用，不证明任何因子、模型或策略科学有效。

## 12. 新闻、公告和 Agent 数据边界

`daily_stock_analysis` 确实有完整的新闻搜索产品链：可路由 Tavily、SerpAPI、Bocha、
Anspire、MiniMax、Brave、SearXNG，并使用网页正文解析、缓存、超时、相关性排序、官方域名
优先和失败记录。该 donor 永久只读；这些 provider 多数需要独立 key/条款，当前没有迁移
为新平台 runtime，也没有因 donor 存在而自动获批。

新平台的顺序应为：

1. 公司公告和财务修订：巨潮/交易所/公司披露；
2. current 公司新闻：经资格审查的 AkShare 新闻或 Futu 只读资讯 adapter；
3. 行业/宏观新闻：经资格审查的搜索 provider；
4. donor 只贡献查询构造、缓存、超时、官方域名优先和相关性排序模式；
5. P8 前不把新闻情绪或 LLM 摘要写成事件 Alpha，LLM 文本也不能成为价格、财务数值、
   发布时间或交易结果的权威来源。

所有新闻条目至少需要 URL、source、published_at、fetched_at、available_at、hash、语言、
版本和许可；时间不可信时必须显式降级，文章更正或撤回不能覆盖旧版本。
