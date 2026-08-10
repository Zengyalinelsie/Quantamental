# P3 实现与验证证据

日期：2026-08-10

范围：`docs/08-detailed-implementation-plan.md` 的 P3-W01 至 P3-W06。本文件保留每个工作包完成时的历史证据；当前 Gate 结论见文末。

该阶段建立 PIT 财务、官方披露和数据证据链。Capability 测试通过不代表因子、估值、择时或投资模型科学有效，不代表可盈利，也不授权真实交易、真实下单或真实账户连接。

## P3-W01：RawObject 与官方披露

已实现：

- `RawObject` 区分 request、response 和 file，绑定 SHA-256、原 URL、provider、`retrieved_at`、media type、storage URI、license 和 retention policy；
- 本地开发对象存储按 SHA-256 内容寻址，重复写幂等，磁盘内容与地址冲突时阻断；`metadata_only` 许可在写入 payload 前失败关闭；
- 官方披露保存巨潮、上交所、深交所、北交所和公司公告来源标识、外部文档 ID、公司/证券、报告期、发布时间、公开可用时间和首个可交易时间；
- 原始版本、更正和撤回组成严格连续的不可变版本链；更正/撤回必须给出原因并只能替换最新版本；
- `0006_disclosure_evidence.sql` 持久化 raw object 和官方披露索引，包含时间顺序、状态、许可和版本约束。

TDD 红灯首先表现为 disclosure/object-store 模块不存在；版本时间倒流测试随后先失败，再加入版本链时钟约束。工作包最终验证命令：

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest tests.test_disclosure tests.test_raw_object_store -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/ruff check src tests
.venv/bin/mypy src
```

限制：本工作包实现证据合同、对象存储适配器和数据库 schema，没有把测试 payload 或公告 fixture 注入运行时，也没有声称已经回填真实公告。真实公司样本、修订案例和人工期望值属于 P3-W04；页面原文追踪属于 P3-W05。

工作包完成时证据：Python 全量 `116 passed`；compileall、Ruff、mypy（41 source files）通过。PostgreSQL 首次应用输出 `0006_disclosure_evidence`，第二次无输出且退出码为 0；`raw_objects=0`、`official_disclosures=0`、migration 记录为 1。开发库保持空表，没有用测试数据填充运行时。

## P3-W02：Canonical Metric Registry

已实现：

- canonical metric 明确区分资产负债表、利润表和现金流量表，并为每个 code 保存名称、单位、币种要求、符号约定和说明；
- provider field mapping 绑定 provider、报表、原字段、canonical code 和不可变 mapping version；同一版本中一个来源字段只能有一个映射；
- fuzzy mapping 在领域构造时禁止标为 production，解析服务在生产路径再次失败关闭；公式映射必须保存显式公式；
- 财务质量方程保存带系数的 canonical terms、容差和 warning/block severity，可表达资产负债平衡与跨表现金勾稽；缺少任一输入返回 `unavailable`，不按 0 参与方程；
- 未识别字段进入带原始对象证据的 unmapped queue，解析结果为 `None`，不会生成伪造事实；
- `0007_canonical_metrics.sql` 持久化 metric、mapping version、provider mapping、quality rule 和 unmapped queue，数据库约束重复执行生产/fuzzy 和单位/币种不变量。

TDD 红灯首先表现为 metrics repository 模块不存在；随后显式 mapping、生产 fuzzy 阻断、未知字段排队、版本不可变、资产负债平衡、跨表缺失输入等 9 个定向测试转绿。

限制：registry 当前不预装运行时示例指标或 provider 映射；真实映射内容必须由后续治理运行从官方定义和原始对象生成并版本化。质量方程通过只证明账务勾稽合同工作，不证明财务数据正确或模型科学有效。

工作包完成时证据：Python 全量 `140 passed`；compileall、Ruff、mypy（52 source files）通过。PostgreSQL 首次应用输出 `0007_canonical_metrics`，第二次无输出且退出码为 0；`canonical_metrics`、`provider_field_mappings` 和 `unmapped_metric_fields` 均为 0 行，未预装运行时假指标或假映射。

## P3-W03：PIT Financial Repository

已实现：

- `FactObservation` 保存 company/security、canonical metric、typed value、unit/currency、报告期/期间类型/报表类型、公开与可用时间、公开修订序号、半开系统时间区间、provider/source field、raw hash、trust/quality、mapping、DatasetVersion 和质量问题 IDs；
- `current_research` 与 `strict_historical` 共用双时间查询；Strict 仍只接受 `pit_verified` 且强制 `available_at <= decision_time`，Current 不能借查询参数提升为 PIT；
- 同一 provider 的公开修订按 `available_at` 生效；同一公开修订的系统更正只关闭上一条系统区间，不重写旧 system-time；
- 多来源事实并存，`AuthorityRule` 保存显式版本和唯一 provider 优先级；权威值可以用于诊断，但只要其他来源语义值冲突，`blocks_downstream=true`；
- `blocked`/`unavailable` 质量结果必须绑定质量问题，不能静默回退为 0 或旧修订；warning 和 issue IDs 随选择结果传播；
- ingest 在写入前核验 RawObject provider/hash、canonical metric unit/statement、唯一生产 mapping 和 DatasetVersion，并注册 evidence、mapping、dataset 三类 lineage；
- 内存和 PostgreSQL repository 实现相同端口；`0008_financial_facts.sql` 持久化双时间事实与版本化 authority rule，并以部分唯一索引禁止一个 provider revision 同时存在多个开放系统版本。

TDD 红灯首先是 `DataQualityState`、`FinancialPeriodType`、`AuthorityRule`、repository 和 service 不存在；加入 PostgreSQL 合同后，`0008` 缺失及 adapter 导入失败继续保持红灯。实现后定向测试覆盖公开修订、系统更正、后入库隔离、Strict/Current、同修订重复、跨来源冲突、质量阻断、lineage 和 PostgreSQL 字段往返。

验证命令：

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_pit_contract \
  tests.test_pit_financial_repository \
  tests.test_postgres_financial_facts \
  tests.test_migrations -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/ruff check src tests
PYTHONPATH=src .venv/bin/mypy src
```

工作包完成时证据：Python 全量 `151 passed`；compileall、Ruff、mypy通过。隔离 PostgreSQL 首次应用输出 `0008_financial_facts`，二次运行无输出且退出码为 0；`financial_fact_observations=0`、`financial_authority_rules=0`、对应 migration 记录为 1。没有把测试事实、映射或 authority rule 注入运行时。

限制：本工作包证明仓储、双时间和选择合同成立，但还没有 P3-W04 的 3–5 家真实公司及两组人工核验修订案例，也没有 P3-W05 页面。它不证明财务数据正确、因子有效、模型科学有效或能够盈利。

## P3-W04a：财务来源资格与路由合同

结合 Wind、Factor Service/iFinD/THS、SneAgent 和官方披露资料，先完成真实 fixture
摄取前的 fail-closed 领域合同：

- `FinancialSourceProfile` 保存版本、角色、市场/三表覆盖、访问模式、资格、信任上限、
  retention/bulk 权限、修订链和精确可用时间能力；候选源不能被当成已批准源；
- PIT 批准必须同时具备 `pit_verified` 信任上限、精确 `available_at` 和修订历史，
  current 来源不能因调用参数变成 strict historical；
- `read_through_cache` 是显式访问模式，调用方未单独确认时失败关闭；retention 未批准时
  bulk persistence 失败关闭；
- `ProviderFinancialRow` 在映射前保存供应商 table/record/field、合并/母公司、累计/单季、
  原始/更正/重述、公告/可用/更新时间、单位缩放、币种和 raw evidence；金额和缩放只接受
  有限 `Decimal`，禁止 float；
- 精确 provider/官方时间、保守 retrieval time 和 unavailable 使用不同枚举；保守检索时间
  不能获得 strict-time 资格；
- current 路由的假设性获批示例顺序为 Factor Service/iFinD/THS 主源、Wind 备用、官方披露
  裁决；实际已知 Factor Service 和 Wind profile 都保持 candidate，不能进入该路由；fallback
  必须给出非空失败原因；strict 路由只接受 PIT authority；
- 领域层没有导入 Wind、HTTP、Factor Service 或 SneAgent SDK。

来源层级、大规模入库切片、容量和上线顺序记录在
`docs/14-data-source-catalog-and-agent-routing.md`。Factor Service 是第一资格候选，但在 live
接口、样例、本地持久化许可和 read-through cache 副作用通过前仍是 candidate/fail-closed；
Wind 在取得接口、样例和许可前同样是 candidate，不能自动成为 fallback；官方公告版本链
负责 PIT 资格；SneAgent 只做 PDF/notes 补漏，其内部 `verified` 不等于平台
`pit_verified`。任何包含过明文凭证的内部文档都不得成为代码、fixture 或仓库文档内容。

TDD 红灯首先是 `a_share_platform.domain.financial_sources` 不存在；实现后定向测试覆盖
Decimal、口径、时间方法、更正序号、PIT 资格、缓存/retention 权限、candidate 阻断和
current/strict 主备路由，并明确验证未获批 Factor Service/Wind 无法被选中。W04a 不包含
真实供应商 HTTP adapter、运行时假数据、3–5 家真实公司
fixture 或 PIT 晋升；这些属于 W04b。

验证命令：

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest tests.test_financial_source_contract -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/ruff check src tests
PYTHONPATH=src .venv/bin/mypy src
```

测试通过只证明来源权限、口径和路由合同按预期失败关闭，不证明供应商长期稳定、财务数据
正确、因子有效或模型科学有效。

工作包完成时证据：定向 9 tests、Python 全量 `216 passed`；compileall、Ruff、mypy
（64 source files）通过。Factor Service 与 Wind 的已知 profile 在测试中保持 candidate；
只有名字明确为“假设性获批”的路由 fixture 才验证未来主备顺序。

## P3-W04b：Factor Service adapter 与资格探针

同花顺/iFinD/THS 作为第一资格候选，已实现不依赖领域核心的 provider-edge adapter：

- 覆盖 v1 `health`、`factor/list`、`table/list`、`factor/query`，以及 v2 `health`、
  `meta/schema`、`metadata`、`tables`、`table/detail`、`columns/search`、`table/count`、
  `table/query`；
- 同时接受开发文档的业务成功码 `0` 和生产样例的 `20000`，其他 HTTP/业务码失败关闭；
- Bearer token 只从环境注入，不进入 client/request repr；provider 和 transport 错误在抛出前
  脱敏；代码、fixture 和文档都不包含 PDF 中的旧 token；
- JSON 小数直接解码为 `Decimal`，不让财务值先经过二进制 float；非有限 JSON 数字失败；
- query 明确要求 `allow_read_through_cache`，没有确认时发出 HTTP 前失败；count 保持只读；
- v2 单页强制不超过 5,000 行，iterator 先 count 后分页，空页、超报数和非法 offset 阻断；
- 对“通用文档称 primary key 必填、生产宏观样例省略主键”的冲突不做静默选择：默认要求
  主键，只有 live metadata 明确允许 date-only 时调用方才能显式放开；三张 A 股财务表始终
  以 `scode` 作为主键；
- 可重复资格探针覆盖全部接口、三张 A 股报表的 detail/search/count，并只在显式确认缓存
  副作用后执行单股票、单报告期 query；输出只含状态和数量，不打印原始财务数值或凭证。

TDD 红灯先后为 adapter import 不存在、probe import 不存在、JSON 财务小数仍为 float；实现后
定向 8 tests 通过。实时无凭证探针仍显示：开发地址所有入口约 5 秒被对端 reset；生产地址
经当前网络路由返回 404；iFinD `edb_service` 无新 token 返回 401。它们是连接/鉴权证据，
不是来源资格通过或数据正确证据。

新凭证由本地 secret manager/环境注入后，复测命令为：

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m \
  a_share_platform.adapters.providers.factor_service_probe \
  --symbol 601089 \
  --report-period-end 2024-12-31 \
  --allow-read-through-cache
```

要求预先设置 `FACTOR_SERVICE_BASE_URL` 和 `FACTOR_SERVICE_BEARER_TOKEN`；不得把 token 写进
命令行、仓库或 fixture。未加 `--allow-read-through-cache` 时 query 显式 skipped，进程以 2
退出，不能被误当成完整 qualification。

本工作包完成时仍未取得合法新凭证、真实三表响应或本地批量保存许可，因此
Factor Service 仍保持 candidate。后续 W04c 以官方披露完成了 4 家真实小样本和两个修订
链，但没有因此将 Factor Service 晋升为合格批量主源。

工作包完成时证据：定向 `8 passed`；共享工作树全量 `225 passed`；compileall、Ruff、mypy
（66 source files）通过，`git diff --check` 通过。测试通过只证明 adapter/probe 合同，不证明
同花顺当前可达、字段值正确、覆盖完整、许可已批准或模型科学有效。

## P3-W04c：真实 PIT 小样本与修订链

在不将 current 供应商值冒充 PIT 的前提下，已建立可重放的真实小样本包：

- 4 家公司：平安银行、五粮液、赛隆药业和立华股份；
- 8 份巨潮官方 PDF，每份保存 source URL、SHA-256、publication/available/
  first-tradable/retrieval time、时间精度和 retention；
- 五粮液和立华股份各 1 条原始/更正链，同一报告期旧版不被覆盖；
- 覆盖正常盘后年报、盘前可用、周末公告、财报更正、同期多版、单位/币种冲突、
  缺失字段、一次性项目和供应商/官方不一致九类场景；
- 时间元数据明确分为 5 条 `exact` 和 3 条 `date_only`；`date_only` 不伪造盘前或
  盘后精确时刻；
- 12 条官方观察为 `pit_verified/passed`；1 条来自 AkShare/Sina 的当前供应商
  观察为 `normalized_current/blocked`，不能进入 strict historical；
- 五粮液 2025 Q1 营业收入 current 因供应商时间/精度/单位冲突显式 blocked，
  strict 从官方更正版选中 `17085765657.95 CNY`。

真实开发库读取结果为 `raw_objects=11`、`official_disclosures=8`、
`financial_fact_observations=13`、`lineage_edges=55`、`dataset_versions=13`、
`dataset_quality_reports=28`、`ingestion_jobs=19`。fixture import 要求显式私人本地研究确认和
loopback PostgreSQL；原文只保存在 `platform/var/private-research/`，禁止外分发，没有加入
默认运行时演示数据。

本工作包解除的是 W04 真实样本与泄漏套件门；它不代表 700–800 家财务回填已完成，
也不会将未通过资格审查的 Factor Service、Wind、BaoStock 或 Futu 数值晋升为
`pit_verified`。

## P3-W05a：Catalog / Quality / Lineage / Jobs

已实现 System 数据管理的第一组真实只读页面和 API：

- 新增与 Web/数据库解耦的 System Catalog read models 和 reader port；
- `/api/system/catalog`、`quality`、`lineage`、`jobs` 只有 GET 方法，并沿用固定
  `current_research + research` envelope；
- PostgreSQL reader 每次读取都显式执行 `SET TRANSACTION READ ONLY`，不会通过 System API
  修改 DatasetVersion、报告、血缘、任务或 checkpoint；DSN 不出现在 repr；
- 未配置 `ASP_DATABASE_URL` 时返回真实空集合，不注入 demo DatasetVersion 或任务；
- Jobs 页面同时展示 status、`output_trust_state`、coverage、processed/rejected、checkpoint
  error 和完整失败原因，`normalized_current` 不被视觉或 API 提升为 `pit_verified`；
- Catalog/Quality/Lineage/Jobs 都有 loading/error/empty/ready；Lineage 当前 0 行时显示真实空态；
- 本项目开发端口固定为前端 `5173`、后端 `8010`，不再与用户另一个 `8000` 服务冲突。

TDD 红灯先表现为后端 System reader 模块和前端 `SystemScreen` 不存在。实现后的定向测试为
后端 7 项、前端 3 项；全量验证为 Python `249 passed`、前端 `24 passed`，Ruff、mypy
（76 source files）、compileall、TypeScript build 和 `git diff --check` 通过。真实开发库只读
验证返回 `catalog=9`、`quality=26`、`lineage=0`、`jobs=14`；库内另有 26 份 coverage 和
35 个 checkpoint，由 Jobs payload 聚合展示。

浏览器技能连接列表当前为空，因此没有把 jsdom、构建成功或源码检查冒充 320/768/1024/1440
真实浏览器视觉证据。W05a 的 API/组件/真实数据库接线完成，视觉截图与 W05b 的
Disclosure/Fact timeline、current/strict 对比、mismatch queue、原始证据 Drawer 仍待完成。
这些测试不证明数据库内容正确、数据具备 PIT 资格、策略有效或模型科学有效。

验证命令：

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_system_api tests.test_postgres_system_catalog -v
npm --prefix frontend test -- --run src/pages/SystemScreen.test.tsx
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
npm --prefix frontend test -- --run
npm --prefix frontend run build
.venv/bin/ruff check src tests
PYTHONPATH=src .venv/bin/mypy src
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
```

## P3-W05b：财务证据诊断与双时间对比

在 System → Catalog → Financial Evidence 中完成：

- 官方披露 timeline 展示 publication、available、first tradable、公开版本序号、
  corrected/withdrawn 状态、替代关系和原因；
- Fact revision timeline 同时展示 public revision 和半开 system-time interval，不把两种
  “修订”混在一起；
- Current / Strict 对同一经济事实分别执行选择；`normalized_current` 只能出现在 current，
  strict 无 `pit_verified` 观察时显式 `unavailable + blocks_downstream`；
- Mismatch Queue 合并 pending unmapped field、blocked/unavailable quality 和当前多供应商语义值
  冲突；冲突保留全部 provider/fact ID，不静默覆盖；
- Raw Evidence Drawer 展示 source URL、hash、provider、retrieved_at、media type、license 和
  retention；不向匿名只读 API 暴露内部 `storage_uri`，禁止再分发时不回传文档内容；
- 新 API 全部为 GET，PostgreSQL 每次查询均显式 `READ ONLY`；没有 `ASP_DATABASE_URL` 时
  使用真实空 reader，不注入测试公告、财务值或 Authority Rule；
- API 和页面查询需要显式 company/fact identity，不默认选公司，也不使用运行时演示数据。

TDD 红灯先表现为 financial evidence reader 和 `SystemEvidenceScreen` 不存在；随后加入纯选择、
多源冲突、PostgreSQL 只读事务、API、Drawer 和 UI current/strict 负向测试。工作包初次完成时，
全量验证为 Python `256 passed`、前端 `26 passed`，Ruff、mypy（80 source files）、compileall、
生产构建和 `git diff --check` 通过；当时开发库为真实空表。

后续 W04c 完成真实小样本导入后，已在真实浏览器复验 Dataset Catalog、五粮液披露时间线、
`date_only/exact`、事实修订、current blocked / strict selected、2 条 blocking mismatch、Raw Evidence
Drawer 和 W04/Timing lineage。Drawer 只展示 hash/provider/license/retention/source 治理元数据，
禁止再分发时不回传 PDF 内容。开发端口是前端 `5173`、后端 `8010`，没有占用用户的
`8000`。这些证据证明页面与真实小样本链路可读，不证明财务数据全市场覆盖、因子有效、
策略盈利或模型科学有效。

## P3-W06a：Timing Shadow Ledger 合同与持久化

已实现 P3 baseline 所需的 immutable 领域合同和 append-only ledger：

- `TimingForecast` 固定包含 benchmark、UniverseVersion、交易日、decision/cutoff/created
  三个时间、1/5/20/60 日 horizon slots、风险预测、静态满仓、被动波动率仓位、主动调整、
  最终仓位区间、model lifecycle、run、approval scope、DatasetVersion 和输入 trust；
- 尚未实现的 horizon、风险预测和主动调整必须显式为 `unavailable` 并保存原因；
  `unavailable` 不能携带数值，P3 不以 0 或伪预测补齐 schema；
- 波动率目标仓位只接受有限 `Decimal`，使用
  `min(static_exposure, target_volatility / observed_volatility)`，P3 静态满仓固定为 1；
- `TimingShadowLedger.append_baseline` 只接受
  `data_mode=current_research + deployment_stage=shadow`、`model_lifecycle=baseline` 和
  `approval_scope=shadow_baseline_only`；主动输出必须保持 unavailable，最终区间必须等于
  被动基线；
- 内存 repository 对 forecast ID 和 benchmark/Universe/交易日键都做不可变冲突检查；
- PostgreSQL `0012_timing_shadow_ledger.sql` 保存完整字段，以唯一键禁止同日重复，且通过
  `BEFORE UPDATE OR DELETE` trigger 拒绝修改或删除历史记录；
- cutoff 必须不晚于 decision time，created time 必须不早于 decision time；输入只允许
  `normalized_current` 或 `pit_verified`，raw 不能进入 TimingForecast。

TDD 红灯先表现为 timing domain、repository 和 `0012` migration 均不存在；实现后 21 项
定向测试通过。全量验证为 `242 passed`，Ruff、mypy（72 source files）、compileall 和
`git diff --check` 通过。本机隔离 PostgreSQL 首次应用输出
`0012_timing_shadow_ledger`，二次运行无输出；migration 记录为 1、append-only trigger
存在。

本工作包初次完成时开发库 `timing_forecasts=0`，因为当时尚无可绑定的真实 CSI benchmark
行情 DatasetVersion；没有用测试值或临时网络值伪造第一条 Shadow 记录。后续 W06b 已接入
真实 raw bars、固定波动率公式版本和可重运 CLI，并追加首条 baseline。P7 才实现、验证和晋级
主动择时；W06a/W06b 均不证明主动模型存在、择时有效、策略可盈利或模型科学有效。

验证命令：

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_timing_shadow_ledger \
  tests.test_postgres_timing \
  tests.test_migrations -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/ruff check src tests
PYTHONPATH=src .venv/bin/mypy src
```

## P3-W06b：真实 CSI 被动波动率 baseline

在 W06a 不可变 ledger 之上，已补齐真实输入和日运行链路：

- `0015_timing_benchmark_bars.sql` 持久化 CSI300/CSI500 未复权收盘价，仅接受
  `normalized_current + current_research`，UPDATE/DELETE trigger 禁止修改；
- 公式版本固定为 `unadjusted-close-log-return-sample-std-20-sqrt244-v1`：21 个正收盘价
  得到 20 个对数收益，使用样本标准差乘 `sqrt(244)`；
- 运行前验证 UniverseVersion 属于请求的 benchmark，且至少一个成员在该交易日的
  `[valid_from, valid_to)` 区间内有效；错配在访问供应商前阻断；
- `normalized_current` 不能回填旧日 baseline；只允许当日上海时间 15:05 后运行，并强制
  `decision_time >= retrieved_at`；
- 每条记录绑定 DatasetVersion、运行环境/代码版本、RunRecord 和两条 lineage；
- 同一 benchmark/Universe/交易日第二次运行在供应商访问前返回已有记录，CLI 如实输出
  `created=false` 和 `writes_performed=false`。

真实开发库首条记录绑定 2026-08-10 的 CSI500 UniverseVersion，该版本含 500 个有效成员；
BaoStock 输入为 2026-07-13 至 2026-08-10 的 21 条未复权收盘价。实际 ledger 值：

```text
benchmark=index:000905
effective_session=2026-08-10
observed_volatility=0.4131876026996083818592030658211309651764
passive_exposure=0.2904249769740580256028179546
active_adjustment=unavailable
data_mode=current_research
deployment_stage=shadow
input_trust_state=normalized_current
code_version=git:b6f9634
```

开发库含 21 条 benchmark bars、1 条 TimingForecast、1 条 run 和 2 条对应 lineage。BaoStock
guard 当日账本为 185 次真实供应商调用、0 次 blocked attempt；11 次 login 和 11 次 logout
均正常完成，没有并发连接或 cooldown。

范围阻断仍保持可见：2026 年 CSI300 因 `SZ.302132` 代码变更/唯一 Listing 冲突失败；
2026 年 CSI500 因历史退出成员 `SH.600079` 缺当时可用 Security Master 失败并整事务回滚。
首条 baseline 只使用已合法落库的当日 CSI500 Universe，没有忽略这两个错误。

真实运行命令仍默认 dry-run：

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.timing_baseline \
  --benchmark-id index:000905 \
  --universe-version-id '<persisted-universe-version-id>' \
  --session 2026-08-10 \
  --target-volatility-ratio 0.12 \
  --database-url postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_dev \
  --code-version git:<commit>
```

只有加上 `--private-local-research-ack --execute` 才会写本地数据库；禁止用于生产决策、真实交易
或账户连接。主动收益、风险预测和主动仓位调整仍显式 `unavailable`，P7 前不得影响生产仓位。

## P3 Capability Gate 结论

截至 2026-08-10，P3 Capability Gate 通过：

- 4 家真实公司、8 份官方 PDF、2 条修订链和九类泄漏/冲突场景可重放；
- RawObject、Canonical Metric、双时事实、authority/conflict 和 current/strict 选择可追溯；
- Catalog、Quality、Lineage、Jobs、披露/事实时间线、Mismatch Queue 和 Raw Evidence
  Drawer 已在真实浏览器对真实小样本验证；
- 首条真实 `current_research + shadow` 被动 Timing baseline 已追加且不可修改；
- 数据类型、质量、来源、时间精度、版本、运行和血缘的阻断信息没有被默认值或页面演示数据隐藏。

该 Gate 只证明 P3 的证据、双时、诊断和被动 baseline 工程能力达到阶段要求。它不证明
700–800 家财务覆盖已完成，不证明任何财务数据、因子、估值、Timing、组合或策略科学有效，
不授权真实交易、下单、撤单或账户连接。P2 的多尺寸视觉证据、完整历史 Universe、XBSE、
2018+ 全范围行情、股本和公司行动仍是独立未完成项。
