# Step 02 Spec / Plan：P2/P3.5 历史数据与 PIT 资格补齐

> 状态：`ready_for_implementation`（先执行资格探针；strict bulk importer 仍需字段主源 ADR）  
> 对应：Plan P2-W03/W04/W06、P3.5、Roadmap Step 2  
> 关联 SPEC：010–015、031、034、053、055  
> D0/AUTH：strict PIT 主源、字段许可、保存与用途资格

## Spec

### 目标与非目标

补齐 2018 至今 CSI300/CSI500 历史 Universe、行情、交易状态、股本、公司行动、XBSE、财务披露/修订和 forward labels，使 P4/P5 可获得真实合格输入。

非目标：不把免费/current 数据升级为 PIT；不无痕混源；不以“800 家有行”代替历史覆盖、时间和质量。

### 数据合同

- Company/Security/Listing、UniverseMembership、IndustryMembership 均有有效区间；
- 行情保存原始不复权 OHLCV/amount，复权因子和公司行动独立版本化；
- 股本区分 total/free-float/float，单位和 available time 明确；
- 财务事实保存 period end、publish/available/system time、revision、source object/hash；
- DatasetVersion、QualityReport、CoverageReport、LineageEdge 持久化；
- source priority 按字段配置，冲突可见，不做静默 fallback；
- strict query 只接受 `pit_verified` 且 `available_at <= decision_time`；
- current-only 数据继续进入 private-local `normalized_current` 路径。

### 分层与执行合同

- evidence/ODS：原始文件或响应、hash、许可和抓取元数据；
- observation：供应商原始语义和时间；
- canonical：身份、口径、单位、冲突和有效区间；
- research：PIT features/labels/universe；
- serving：只读且用途隔离的合格投影；
- worker 默认 dry-run，执行需 private-local ack、显式 domain/date/shard；
- 限流在网络调用前生效，checkpoint 可恢复，失败保留；
- 同一 shard 重跑幂等，不删除旧证据。

### 待决策

- `DATA-D0-01` strict PIT 主源/许可必须先通过探针和 ADR；
- Wind、同花顺 Factor Service、内部三表服务只在凭证、字段、时间和许可实测后定主备；
- BaoStock/AkShare/Futu/CNInfo 仅按已接受 ADR 的用途和 trust ceiling 使用。

### 验收

- 任意抽样历史日可重建 Universe、已知财务和下一可交易 session；
- CSI300/CSI500 成分变更、退市和代码变化有 fixture/真实抽样；
- 价格/股本/公司行动闭合，复权可复算；
- 非空全 unmapped、时间倒置、来源冲突、覆盖不足均失败；
- current 与 PIT 的库、API、页面和 lineage 不混淆。

## Plan

### Task 1：D0 数据源资格探针与 ADR

预计文件：

- 更新 `docs/14-data-source-catalog-and-agent-routing.md`；
- 先遵守 `docs/adr/0007-strict-pit-source-qualification-policy.md`，探针通过后再新增字段主源 ADR；
- provider probe 只进入 `platform/src/.../adapters/providers/`；
- probe tests 进入 `platform/tests/test_*_probe.py`。

先验证认证、字段、首次披露/修订、历史成分、保存条款、限流和失败语义；不得在 ADR Accepted 前批量执行。

### Task 2：历史 Universe 与身份

复用/扩展 `domain/security_master.py`、`domain/universe.py`、identity/universe ports、PostgreSQL adapter 和 worker；先写纳入/剔除/退市/名称代码变化/幂等测试，再做分片 importer。

### Task 3：行情、日历、股本和公司行动

复用 `domain/market_data.py`、Parquet adapter、canonical sink；为 share-capital/corporate-action 增加明确 domain/port/migration，先写复权、交易状态、单位和跨源冲突测试。

### Task 4：PIT 财务/公告/修订

复用 `domain/pit.py`、financial evidence/facts ports 和 repository；实现合格 provider adapter、raw object capture、revision chain 和 available time；用真实小样本与手工公告时间核验。

### Task 5：质量、覆盖、lineage 和 serving

新增按 benchmark/date/domain 的 coverage gate；生成 versioned comparable、industry lineage 和 forward label；严格 serving view 只包含通过资格对象。

### Task 6：批量运行与对账

先 3–5 家/两个修订案例，再 30 家，再 benchmark shard；观察稳定写入、限流和恢复后才扩大。每个 shard 记录 receipt/checkpoint/quality，不以终端进程存活代替数据库证据。

### 定向验证

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest tests.test_security_master tests.test_universe tests.test_market_data tests.test_pit_contract -v
PYTHONPATH=src .venv/bin/python -m unittest tests.test_postgres_identity tests.test_postgres_market_structure tests.test_postgres_financial_facts -v
```

真实执行命令必须在 Accepted ADR 中给出显式 provider、日期、domains、DSN、retention 和 ack；规划文档不构成下载或许可授权。
