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

尚未完成：多尺寸真实浏览器视觉回归及截图。因此 P2 Capability Gate 当前为待验证，不是通过。

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
- canonical sink：先注册 DatasetVersion，再写 raw bar Parquet、partition manifest、daily market state、calendar、checkpoint、质量和覆盖率；Listing 代码映射缺失/歧义会阻断；
- 断点恢复跳过已经成功的 checkpoint，不重复请求或写入该 checkpoint。

执行门示例见 README。默认 dry-run 无网络和数据库写入；本轮自动化全部使用 fake SDK/connection，没有替用户下载真实行情或写真实数据库。

最初回填规划扩展新增 14 个定向单元测试；ADR-0003 执行扩展又增加 14 个定向测试，覆盖私人用途/retention 硬门、显式 symbol/domain 计划、BaoStock raw/calendar、Futu quote-only staging、DatasetVersion FK 顺序、canonical sink、CLI ack/DSN 门和成功 checkpoint 恢复。当前仍未执行真实批量回填，因此业务数据行和 Parquet 增量均为 0；这不是用 fixture 冒充真实数据。

仍未完成的真实数据域：A 股全市场 Security Master、沪深 300/中证 500 历史 Universe、2018+ 股本和公司行动。donor 的 AkShare 历史价三路均为 qfq，current stock index 也不是历史 Universe，因此没有为追求表面覆盖而接入。该能力不改变前述 P2 Gate 判断，也不证明任何模型科学有效。

本工作包最终验证：Python unittest `166 passed`，compileall 通过，Ruff 通过，mypy `62 source files` 通过。所有 provider、数据库和 CLI execute 测试使用 fake/injected runtime；这些测试证明合同与程序行为，不证明供应商稳定性、真实数据覆盖或模型科学有效。

主代理在本机隔离 PostgreSQL `127.0.0.1:55432` 复验：首次运行 migration 输出 `0005_data_backfill`，二次运行无输出且退出码为 0。`ingestion_jobs`、`ingestion_checkpoints`、`dataset_quality_reports` 和 `dataset_coverage_reports` 均为 0 行，说明 schema 已持久化，但没有用 fixture 或未获许可数据填充开发库。
