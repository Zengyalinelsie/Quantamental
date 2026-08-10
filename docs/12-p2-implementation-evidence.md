# P2 实现与验证证据

日期：2026-08-10

范围：`docs/08-detailed-implementation-plan.md` 的 P2-W01 至 P2-W05。

结论：五个工作包的代码、迁移、自动化测试和真实 HTTP 接线已经完成；P2 Capability Gate 暂不宣称通过。当前浏览器控制没有可用实例，阶段交付清单要求的 320/768/1024/1440 截图与视觉回归仍待补齐。

该结论不证明任何因子、择时、组合或投资模型科学有效，不代表可盈利，也不授权真实交易、真实下单或真实账户连接。

## 1. 工作包交付

| 工作包 | 交付证据 |
|---|---|
| P2-W01 | Provider Registry、字段级用途限制、免费源信任上限、主源/备用源/权威核验源、ADR-0002 和字段覆盖矩阵 |
| P2-W02 | Company/Security/Listing、历史标识、上市状态、ST、行业有效区间、映射 API 和 `0002_security_master.sql` |
| P2-W03 | UniverseDefinition/Version/Membership、研究与可交易资格分离、原因、基准、历史快照、diff/coverage API 和 `0003_universe.sql` |
| P2-W04 | 原始行情、独立复权因子、市场状态、涨跌停、股本、市值、公司行动、日历、冲突报告、Baostock JSON normalizer、真实 DuckDB/Parquet 和 `0004_market_data.sql` |
| P2-W05 | Research / Universe & Screen、当前/历史日期、覆盖率、成员/原因/行业/版本、ST/不可交易/退市展示、ProTable 列配置与 URL view |

## 2. 数据资格与 PIT 边界

- Baostock/a-share-mcp 是沪深本地原型主源，AkShare 是北交所和缺失字段备用源，三家交易所是权威核验源；
- 免费源禁止 strict historical、生产决策、通用 `raw_bulk_persistence` 和外部分发；ADR-0003 仅增加显式 ack 的 `private_local_research` 本地保存例外；
- 私人本地例外只能输出 `normalized_current`，供应商或具体端点明确禁止 retention 时仍 fail closed；
- 免费源观察只能生成 `normalized_current`，provider adapter 无法直接生成 `pit_verified`；
- 当前 Security Master 的 identifier `valid_from` 保留真实检索日，绝不回写成上市日来伪造历史 PIT。仅在 `normalized_current` canonical sink 中，历史行情或 Universe 无法按 identifier 有效期解析时，才允许按交易所与确定性 Listing ID 回溯；候选还必须满足 `listed_on <= as_of`、未在该日之前退市且结果唯一。该路径会向质量与覆盖率报告写入 `current-known identity mapping` warning，严格 PIT 消费者不得使用；
- 历史日期页面保持 API 返回的 `data_mode=current_research`，并明确提示它不是 `strict_historical`、也不代表 PIT verified；
- fallback 生成独立来源观察；来源冲突保留并阻断选值，不静默覆盖。

完整决定和探针结果见 `docs/adr/0002-a-share-data-source-qualification.md` 与 `docs/11-p2-data-source-coverage-matrix.md`。

## 3. TDD 与自动化证据

每个工作包先建立失败测试或失败验证，再实现代码并回归。最终自动化结果：

```text
Python unittest：102 passed
Python compileall：passed
Ruff：passed
mypy：passed，35 source files
前端 Vitest：21 passed，9 test files
ESLint：passed
TypeScript + Vite build：passed
npm audit：0 vulnerabilities
```

前端测试覆盖运行时空状态和显式 fixture 两条路径。默认 `create_app()` 的 security master、universe 和 market data 均为空；测试 fixture 只通过构造参数注入，不进入生产前端或默认 API。

## 4. PostgreSQL migration

本地隔离 PostgreSQL 17 位于 `127.0.0.1:55432`。P2 迁移验证结果：

```text
首次执行 P2-W04：0004_market_data
第二次执行：无输出、退出码 0
migrations=0001_governance_ledger,0002_security_master,0003_universe,0004_market_data
market_data_partitions=0
daily_market_states=0
price_limits=0
share_capital_periods=0
corporate_actions=0
exchange_calendar_days=0
```

P2-W02 和 P2-W03 已分别验证首次执行与二次幂等。所有新表保持 0 行，未用 fixture 填充开发数据库。

迁移只有 forward runner，没有自动 downgrade。需要回退时应保留数据库备份并使用经审查的 forward migration 或恢复备份；不能直接删除生产表。本轮没有删除数据卷或表。

## 5. Parquet 与样本核算

`ParquetMarketDataStore` 使用 DuckDB 1.5.5 写入真实 Parquet：测试检查文件头和文件尾均为 `PAR1`。日线按 DatasetVersion/交易所/年份分区，复权因子按 DatasetVersion/年份独立分区；已存在分区会拒绝静默覆盖。

合同 fixture 样本通过：

- 日线只保存原始 `unadjusted` OHLCV/amount；
- `12.30 × 0.5 = 6.150` 的复权收盘价由独立因子重建；
- `12.30 × 666,961,416 = 8,203,625,416.80 CNY` 的历史总市值使用当时总股本；
- 自由流通股本缺失保持 `None`，不填 0；
- 退市美都样本的 `0.47` 一字跌停识别为 `locked_down`；
- 停牌空行情只生成状态，不生成 0 价格日线。

这些是合同与算术核验，不是模型科学有效性证据。

## 6. API、前端与 HTTP 证据

新增只读资源包括证券身份、公司映射、Universe 版本/快照/diff/coverage、市场日线/摘要/质量/公司行动和下一交易日。OpenAPI 仍没有 POST/PUT/PATCH/DELETE。

测试专用只读 API 注入明确 fixture，Vite 通过可配置代理完成真实 HTTP 请求。对 `2020-05-22` 的响应返回 4 个成员，并包含：

- `600175 退市美都`；
- `delisted_on=2020-08-14`；
- `special_treatment=star_st`；
- `tradable_eligible=false`；
- `dataset_version_ids=[dataset:p2-contract-fixture:v1]`；
- `data_mode=current_research`。

由此证明前端请求路径与只读 API 可接通，但 HTTP JSON 不能替代浏览器视觉回归。

## 7. 浏览器证据缺口

浏览器运行时报告可用实例列表为空，因此本轮无法生成或检查 320/768/1024/1440 的真实页面截图。没有使用 jsdom、源码检查或 HTTP 响应冒充视觉证据。

待浏览器实例可用后必须验证：

1. `/research?tab=universe-screen&universe=universe-version%3Acore-a-share%3Av1&point=historical&as_of=2020-05-22`；
2. 退市美都、退市日期、`*ST` 和“不可交易”在表格中可见；
3. current_research/PIT 警告、DatasetVersion 和 SYSTEM AS OF 可见；
4. 320/768/1024/1440 无页面级横向溢出，移动导航可用；
5. 筛选、排序和列显示变化可回写 URL 并在刷新后恢复。

## 8. P2 Gate 判断与未完成项

自动化证据已覆盖：任意 fixture 历史日重建、研究/可交易池分离、行业/挂牌、退市/ST/停牌/代码名称变化、价格/复权/市值抽样，以及组件测试中页面不隐藏退市样本。

尚未完成：多尺寸真实浏览器视觉回归及截图、完整历史 Universe、XBSE、2018+
全范围行情、股本和公司行动。因此 P2 Capability Gate 当前为待验证，不是通过。

此外，P2 没有 PIT 财务、公告修订、因子、估值、改善、择时、组合、回测、事件 Agent、Paper OMS 或真实执行；这些属于 P3 及以后阶段。新闻模块按计划在 P8 接入，本阶段没有提前加入新闻情绪或 Agent 新闻信号。

## 9. 沪深 300 / 中证 500 回填准备扩展

用户要求的真实数据范围已被固化为 provider-neutral `BackfillPlan`：

- A 股全市场 Security Master（XSHG/XSHE/XBSE）；
- 沪深 300 `000300` 与中证 500 `000905` 历史 Universe；
- 2018-01-01 起的原始不复权行情、股本、公司行动和交易日历；
- 年度确定性 checkpoint、失败状态、断点恢复键；
- 复用既有 `dataset_versions`，并新增 ingestion job/event/checkpoint、质量报告和覆盖率持久化；
- checkpoint 保存真实 provider、`retrieved_at`、provider cutoff、`unadjusted` 口径、单位和 warnings。

默认命令只生成计划，不访问网络、不写数据库：

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.backfill --end 2026-08-08
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.backfill --provider futu_quote --end 2026-08-08
```

通用 `--execute` 仍会 fail closed：当前没有 provider 获得所有目标字段的 `raw_bulk_persistence` 资格。ADR-0003 另行允许显式、小范围的 `private_local_research` 执行，且必须同时提供 ack、symbols、domains、本地 PostgreSQL DSN 和 Parquet root。首批 executable source/sink 为：

- `baostock_sdk`：沪深 raw 日线和交易日历；测试锁定 `frequency="d"` 与 `adjustflag="3"`；
- `futu_quote`：沪深 raw 日线；只创建 `OpenQuoteContext`、使用 `AuType.NONE`，代码级测试继续禁止任何账户或交易上下文；
- `a_share_identity_universe`：BaoStock 当前挂牌/行业 + AkShare CNInfo 法定名称，以及带日期的 CSI300/500 每交易日成员；只允许 `--all-a-share` 的 `security_master`/`universe`；
- canonical sink：先注册 DatasetVersion，再写 raw bar Parquet、partition manifest、daily market state、calendar、checkpoint、质量和覆盖率；优先按 identifier 有效期严格解析 Listing。只有 `normalized_current` 可以使用受控的 current-known identity mapping，且缺失、上市/退市区间不兼容或非唯一结果都会阻断；strict PIT 不会进入该 fallback；
- 断点恢复跳过已经成功的 checkpoint，不重复请求或写入该 checkpoint；CLI 重启时沿用数据库中首次计划的 `created_at`；
- PostgreSQL 只接受 loopback/Unix socket，Parquet 只允许写入 `platform/var/private-research/`；
- UniverseVersion 持久化 `normalized_current`、provider/source、retrieved/system time 和 DatasetVersion lineage，严格 PIT view 不接收该数据；
- CSI 每日快照要求非空、合理成分数量、合理日变化和可信 `updateDate`；Security Master 设最低行数/法定名覆盖率，并对重复代码和 CNInfo 代码不匹配 fail closed；所有真实请求有显式限流和单次超时。

执行门示例见 README。默认 dry-run 无网络和数据库写入；本轮自动化全部使用 fake SDK/connection，没有替用户下载真实行情或写真实数据库。

最初回填规划扩展新增 14 个定向单元测试；ADR-0003 执行扩展又增加 14 个定向测试，覆盖私人用途/retention 硬门、显式 symbol/domain 计划、BaoStock raw/calendar、Futu quote-only staging、DatasetVersion FK 顺序、canonical sink、CLI ack/DSN 门和成功 checkpoint 恢复。该代码提交时尚未执行真实批量回填，因此当时业务数据行和 Parquet 增量均为 0；后续真实运行证据见本文件第 11 节。

该自动采集能力提交时尚未替用户执行真实下载或入库。当前 Security Master 执行范围仍仅 XSHG/XSHE，XBSE、完整历史代码/名称、2018+ 股本和公司行动仍未完成；CSI 历史成员是检索时获得的带日期快照，固定为 `normalized_current`，且历史可交易状态未验证前 `tradable_eligible=false`。donor 的 AkShare 历史价三路均为 qfq，current stock index 也不是历史 Universe，因此没有为追求表面覆盖而接入 raw/PIT。后续 CSI800 当前身份真实运行不改变这些边界，也不证明任何模型科学有效。

恢复边界保持显式：成功并已提交的 checkpoint 可跨 CLI 重启跳过；若 source 在 DatasetVersion 注册和 batch 落库前失败，本次尚未成功的 fetch 会重取。真实 CSI 长区间因此建议按年度使用独立 plan id 执行，避免把“有 checkpoint 键”误写成任意故障点都具有 payload staging。

本工作包最终验证：Python unittest `166 passed`，compileall 通过，Ruff 通过，mypy `62 source files` 通过。所有 provider、数据库和 CLI execute 测试使用 fake/injected runtime；这些测试证明合同与程序行为，不证明供应商稳定性、真实数据覆盖或模型科学有效。

主代理在本机隔离 PostgreSQL `127.0.0.1:55432` 复验：首次运行 migration 输出 `0005_data_backfill`，二次运行无输出且退出码为 0。`ingestion_jobs`、`ingestion_checkpoints`、`dataset_quality_reports` 和 `dataset_coverage_reports` 均为 0 行，说明 schema 已持久化，但没有用 fixture 或未获许可数据填充开发库。

ADR-0004 组合身份/Universe 与审查修复后的自动化结果为：Python unittest `195 passed`，compileall 通过，Ruff 通过，mypy `63 source files` 通过，`git diff --check` 通过。新增 dry-run 生成 20 个 work units（2 个当前 Security Master 市场快照 + 2 个指数 × 9 个年度区间），明确输出 XSHG/XSHE、`normalized_current`、`private_local_research` 和 `writes_performed=false`。隔离开发 PostgreSQL 已验证到 `0009_nullable_industry_code`；`0010_canonical_universe_lineage` 的实库 smoke 与真实 backfill 仍将在本提交之后单独执行并记录。本轮代码提交前没有执行 backfill `--execute`，没有发真实供应商请求，也没有写入真实业务数据。

## 10. BaoStock 供应商安全 guard

真实 XSHG 身份回填结束后，供应商补充了每日不超过 50,000 次、禁止并发连接、
首次黑名单/限流至少冻结 6 小时且重复信号累加的运行约束。平台采用更保守的
40,000 次硬上限，为同机平台外调用保留 20% 余量，并新增：

- 跨进程非阻塞文件锁与同进程互斥锁，保证一个本地 BaoStock 会话；
- `Asia/Shanghai` 自然日 SQLite 调用账本，分别记录真实供应商调用与被阻断尝试；
- 默认 0.25 秒最小调用间隔；
- 黑名单/限流响应识别、至少 6 小时冻结与重复信号累加；
- `BaostockBackfillSource` 和 `IdentityUniverseBackfillSource` 的全部
  `login/query/logout` 接线；
- Identity/Universe 超时后等待活跃 SDK 调用真正退出，再执行 `logout`，禁止
  超时线程与清理调用并发；
- 只用 OS 文件锁判断会话活性，不把数据库遗留 `running` 状态当作活进程。

TDD 红灯先证明 guard 模块不存在及两个 source 尚不接受 guard；绿灯定向验证
`24 tests`。本工作包最终验证为：Python unittest `230 passed`、Ruff `src tests`
通过、mypy `67 source files` 通过、compileall 通过、`git diff --check` 通过。
测试覆盖跨进程争锁、上海日界、调用额度、阻断计数、调用间隔、冻结累加、
两个 source 的 ledger operation 序列及 timeout/logout 不并发。

guard 启用前没有调用账本，因此此前真实日调用数无法精确追溯，不会用估算值
补造历史。XSHE 失败计划在本安全提交前没有重启；恢复时仍必须单会话运行，并对
供应商遗漏的目标代码（包括 `SZ.302132`）保留明确错误与原始返回证据，不得静默
剔除。该工作包只改变后端供应商运行安全，没有可见 UI 变化，因而没有用截图冒充
验证；它也不改变 P2 浏览器证据缺口，更不证明任何模型科学有效。

选源边界保持不变：`financial-data-hub` 负责路由和交叉核验，Futu 只允许
`OpenQuoteContext` 行情，`sources/daily_stock_analysis` 永久只读且仅借鉴容错模式。
所有免费源输出最多为 `normalized_current`，不得冒充 PIT。

## 11. CSI800 当前 Security Master 真实运行证据

在用户明确批准免费源和 Futu 仅用于私人本地研究批量持久化、固定
`normalized_current` 且禁止外部分发、strict historical、生产决策和 `pit_verified`
之后，主代理在本机隔离 PostgreSQL 执行 CSI300 + CSI500 去重后的 800 个目标代码。
所有 BaoStock 请求都在第 10 节 guard 下单会话运行。

最终数据库核验：

- XSHG 目标批：469/469，job/checkpoint 均 `succeeded`，processed/rejected 为 469/0；
- XSHE 验收批：30/30，job/checkpoint 均 `succeeded`，processed/rejected 为 30/0；
- XSHE 主批：300/300，job/checkpoint 均 `succeeded`，processed/rejected 为 300/0；
- 三批 quality 均 `passed`，coverage 均为 1.0；
- 以原始两个 target plan 的 800 个代码与开放 code identifier 做 SQL 反连接，精确覆盖为
  799/800，唯一缺失 `SZ.302132`；
- 数据库当前 listings 为 XSHG 479、XSHE 330，共 809。XSHG 的 479 包含此前样本及 10 家
  非本次 CSI800 目标，不能把 809 或 479 冒充 CSI800 目标完成数；
- guard 当日持久化 11 次 `login/query/logout` 调用，blocked attempt 为 0、无 cooldown，
  每个 worker 都正常 logout。

`SZ.302132` 没有被静默删除。原始 XSHE 331 家 job 保留失败状态和
`missing_count=1; missing_symbols=SZ.302132`；后续两个成功 batch 是显式隔离异常标的的
30 + 300 工作单元，专门的代码变更 bucket 仍未完成。

独立来源与官方公告已经证明该标的不是错码：CNInfo 公司概况返回中航成飞、当前代码
302132、上市日 2010-08-27；巨潮公告 `1222544408`（2025-02-15 发布）明确同一上市主体
旧简称/代码为中航电测/300114，自 2025-02-17 起启用中航成飞/302132。当前 staged
payload 只能表达单个 current code/name，canonical sink 又按 current code 派生 Listing ID；
若直接补当前值，会把同一 Listing 拆成两个，违反 SPEC-010。该 Spec/现有代码冲突已按规则
报告并暂停，未擅自选择稳定 ID 策略或推断旧 identifier 的 `valid_from`。

因此当前事实是“CSI800 当前身份目标 799/800，唯一代码变更案例待合同决策”，不是
Security Master、历史 Universe、2018+ 行情、股本或公司行动全部完成。所有已入库身份仍是
`normalized_current`，不能用于 strict historical 或被晋升为 `pit_verified`。这些覆盖与质量
证据只证明这三个 ingestion batch 的工程运行结果，不证明供应商数据科学正确、策略盈利或
模型科学有效。

## 12. CSI500 当日 Universe 成功与历史范围阻断

为不让 CSI300 或长时间段中的单点身份错误阻止独立合法的范围，CLI 已支持
`--benchmarks 000300/000905` 显式分片。该参数只收窄用户选择的 benchmark，不会放宽质量、
许可、身份或 PIT 门。

2026-08-10 单日 CSI500 真实运行成功：

- 任务 `job:private-local:a_share_identity_universe:7a76b4bb2bf71c0f15d1` 为 `succeeded`；
- 实际落库 UniverseVersion 含 500 个成员，与该日供应商返回的 500 个成员一致；
- quality report 为 `passed`、`checks_passed=1`、`checks_failed=0`；
- UniverseVersion、DatasetVersion 和 lineage 已持久化，信任上限仍为
  `normalized_current`，成员默认 `tradable_eligible=false`。

同时，两个 2026 年长范围运行按 fail-closed 失败并保留原因：

- CSI300：成员返回包含 `SZ.302132`，它与旧代码 `SZ.300114` 属同一上市主体，
  现有 current code 派生 Listing ID 与 SPEC-010 稳定 Listing ID 冲突；任务未静默剔除该成员；
- CSI500：历史退出成员 `SH.600079` 在 2026-01-05 无唯一可兼容 current-known identity，
  canonical sink 失败并整事务回滚，没有留下部分年度 Universe。

因此当前准确状态是：CSI800 当前 Security Master 目标 799/800；CSI500 当日 Universe
500/500；完整历史 CSI300/CSI500 Universe 仍未完成。单日成功记录可供 P3 当日被动 Timing
baseline 绑定，但不能代替历史 Universe，更不能用于 `strict_historical`。

## 13. 股本、公司行动与 XBSE staging 工作包

在不选择 SPEC-010 稳定 Listing ID 方案、不访问交易账户且不写数据库的前提下，P2 新增了
一个 provider-neutral staging 工作包。它只解决“如何诚实接住来源观察”，没有把来源升级为
可执行全量 backfill 或 canonical 数据：

- `StagedShareCapitalObservation/ShareCapitalPayload` 保存证券代码、交易所、股本变动日、
  date-only 公告日、总股本、已流通、流通受限、自由流通缺失、来源和稳定 provider record ID；
- `StagedCorporateActionObservation/CorporateActionPayload` 分开保存每股现金、送股、转增和
  配股经济条款，不把送股与转增静默合并；
- `CninfoMarketStructureNormalizer` 是不访问网络的纯转换层，可把已经取得的
  `stock_share_change_cninfo` 和 `stock_dividend_cninfo` 记录转换为上述 payload；CNInfo 的
  每十股分配口径使用 `Decimal` 显式换算为每股口径；
- provider 返回的零分配不会被写成数值为 0 的公司行动；缺失自由流通股本保持 `None`；
- 不可能的股本分项、代码错配、重复 provider record、缺失经济条款和不完整配股条款均
  fail closed；
- payload 合同接受 `BJ.* + Exchange.XBSE`，证明 XBSE 市场结构观察可以进入同一 staging
  边界；这不等于已经实现北交所 Security Master source、法定名称映射或 canonical 入库。

同日只读最小探针取得的来源形状为：

- `stock_share_change_cninfo(000858, 2018–2026)`：18 行，包含变动日期、公告日期、总股本、
  已流通股份、流通受限股份和变动原因；
- `stock_dividend_cninfo(000858)`：28 行，包含实施方案公告日期、送股比例、转增比例、
  派息比例、股权登记日和除权日；
- `stock_info_bj_name_code()`：333 行，包含北交所证券代码、简称、总股本、流通股本、
  上市日期、行业和报告日期。

这些行数只证明探针当时返回了可解析结果，不证明全市场/2018+ 覆盖、端点稳定性、许可、
修订连续性或 PIT。探针结果没有写入平台数据库。staging 中的 `announced_on` 仍只是 date
精度字段，不生成或推断 `available_at`；所有免费源结果最多为 `normalized_current`。

TDD 证据：先以缺失 payload/normalizer 的 import error 建立红灯，再完成最小实现。定向
`12 tests` 通过；当时共享分支全量 `311 tests` 通过，Ruff 通过、mypy `91 source files`
通过、compileall 和 `git diff --check` 通过。全量计数包含同期其他工作包，不能把 311 全部
归因于本工作包。

尚未完成且继续阻断 durable 链路：

1. `CanonicalBackfillSink` 尚不接收这两类 payload，Provider Registry 和执行 CLI 也未开放；
2. `corporate_actions` 现有 schema 没有完整 DatasetVersion/trust 和“送股/转增分别保存”合同，
   本工作包没有用 migration 猜测最终 schema；
3. `SZ.302132/SZ.300114` 仍证明 current-code 派生 Listing ID 违反 SPEC-010 的稳定身份要求；
4. `SH.600079` 仍缺唯一历史身份，完整 CSI300/CSI500 Universe 不能据此继续；
5. 北交所 333 行只是 current 列表探针，缺历史代码/名称、退市、法定公司身份和有效区间。

因此本节证明的是 staging 和 fail-closed 转换能力，不是股本/公司行动/XBSE 已真实入库，
不改变 P2 Capability Gate 的待验证结论，也不证明任何数据、因子或模型科学有效。
