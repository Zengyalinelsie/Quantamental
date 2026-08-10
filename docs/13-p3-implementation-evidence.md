# P3 实现与验证证据

日期：2026-08-10

范围：`docs/08-detailed-implementation-plan.md` 的 P3-W01 至 P3-W06。本文件随每个工作包追加；在 Gate 证据完整前不宣称 P3 完成。

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

本工作包仍未取得合法新凭证、真实三表响应、本地批量保存许可、3–5 家真实公司人工期望值
或两个修订案例，因此 Factor Service 保持 candidate，P3-W04 和 P3 Gate 均未完成。

工作包完成时证据：定向 `8 passed`；共享工作树全量 `225 passed`；compileall、Ruff、mypy
（66 source files）通过，`git diff --check` 通过。测试通过只证明 adapter/probe 合同，不证明
同花顺当前可达、字段值正确、覆盖完整、许可已批准或模型科学有效。

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

当前限制保持显式：开发库 `timing_forecasts=0`。本地只有 2018 年 30 家个股样本行情，
没有可绑定的 CSI300/CSI500 benchmark 行情 DatasetVersion，因此没有用测试值或临时网络值
伪造第一条每日 Shadow 记录。P3-W06 的“每日记录”仍未完成；需要先把真实 benchmark
raw bars、波动率定义版本和 scheduler 接线后再开始追加。P7 才实现、验证和晋级主动择时。
本工作包不证明主动模型存在、择时有效、策略可盈利或模型科学有效。

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
