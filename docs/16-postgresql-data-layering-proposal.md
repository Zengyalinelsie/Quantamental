# PostgreSQL 数据分层方案（待批准）

- 状态：Proposed，**尚未批准、尚未实施**
- 日期：2026-08-11
- 范围：`platform/` 的 PostgreSQL 表、迁移、repository 和只读 API

## 1. 问题判断

当前 49 张持久表基本都在 `public`：原始证据、供应商 observation、canonical 事实、任务状态、
质量/血缘、因子实验和审批混在同一命名空间。单表合同大多清楚，但数据库使用者无法从 schema
判断数据职责，DBeaver 中也很难看出“能否用于 PIT”“是权威事实还是摄取中间态”“是研究
产物还是服务视图”。这个问题值得治理。

纯粹照搬传统 `ods/dwd/dws/ads` 不够合适。本平台最重要的不只是加工层级，还有：

- 原始证据与 canonical 事实不能混淆；
- `raw / normalized_current / pit_verified` 是可信状态，不是 Bronze/Silver/Gold 的别名；
- 同一 canonical 领域可能同时保存 current-only 和 PIT 版本；
- 研究 label、失败实验、审批和生产只读视图有不同权限边界；
- DatasetVersion、质量、血缘和运行记录必须横跨所有数据层。

因此建议使用“**职责 schema + 跨层可信状态**”，而不是只用加工深度命名。

## 2. 推荐的六个 schema

```text
provider
   │
   ▼
evidence ──► observation ──► canonical ──► research ──► serving
   └────────────── governance 贯穿所有层 ──────────────┘
```

| Schema | 职责 | 现有对象示例 | 约束 |
|---|---|---|---|
| `governance` | 版本、血缘、质量、摄取运行、映射、审批 | `dataset_versions`、`lineage_edges`、`artifacts`、`run_records`、`dataset_*_reports`、`ingestion_*`、`financial_backfill_*`、metric/mapping/authority、`factor_promotion_reviews` | 不承载供应商业务值；append-only 对象继续不可改写 |
| `evidence` | 不可变原始证据及披露索引 | `raw_objects`、`official_disclosures` | DB 保存元数据/hash；大对象字节仍在对象存储；不直接供因子计算 |
| `observation` | 保留供应商语义的清洗 observation | `normalized_current_financial_observations`、`share_capital_observations`、`corporate_action_observations`、`timing_benchmark_bars`、market partition/state | 必须保留 provider、retrieved/system time、DatasetVersion、trust；不得在此层隐式解决冲突 |
| `canonical` | 权威身份、有效期和治理后的事实 | Company/Security/Listing/identifier、Universe、industry、calendar、price limit、`financial_fact_observations`、`share_capital_periods`、`corporate_actions` | 实体和单位明确；双时间和修订可重放；只有治理流程可晋升 PIT |
| `research` | 可复现研究输入、标签、实验、验证 | `feature_snapshots`、`research_labels`、`experiment_*`、`factor_qualification_audits`、`factor_validation_reports`、`timing_forecasts` | label 与生产 feature 物理隔离；失败结果同样保留；禁止拥有交易权限 |
| `serving` | 面向 API/前端的稳定只读 projection | Dataset Catalog、PIT-qualified universe、Factor Workspace/安全页读模型等 views | V1 只放 view/materialized view；不是权威写入层，不得在 view 中提升 trust 或填假数据 |

传统数仓术语可以这样近似理解，但不作为正式合同：`evidence ≈ ODS raw`，`observation ≈ ODS
clean`，`canonical ≈ DWD`，`research ≈ DWS`，`serving ≈ ADS`；`governance` 是传统四层之外
必须独立存在的控制平面。

## 3. 可信状态与物理层正交

`raw`、`normalized_current`、`pit_verified` 继续沿用现有语义，不能由 schema 名推断：

| 可信状态 | 允许出现的层 | 关键规则 |
|---|---|---|
| `raw` | `evidence`，少量 `observation` envelope | 未标准化；只能追溯，不能直接用于生产数字 |
| `normalized_current` | `observation`、`canonical`、受限 `research` | 只可 current research；不得用于 strict historical |
| `pit_verified` | `canonical`、`research` | 必须有 DatasetVersion、available-at、修订、质量和 lineage 证据 |

任何 `observation → canonical` 或 `canonical → research` 处理都必须产生新的 DatasetVersion 和
LineageEdge。移动 schema 本身不改变数据可信状态，也不构成 promotion。

## 4. 权限建议

| 角色 | 最小权限 |
|---|---|
| ingestion worker | 写 `evidence/observation` 和自己的 `governance` job/checkpoint；不能写 PIT promotion |
| data curator | 读 evidence/observation，按获批流程写 `canonical` 和治理记录 |
| research worker | 只读合格 canonical，写 `research`；不能写审批或账户数据 |
| reviewer | 读研究证据，仅写 `governance.factor_promotion_reviews` 的受控服务路径 |
| API/前端 | 默认只读 `serving` 和获准的治理目录；无 schema 写权限 |

V1 可以先用应用层 repository 和数据库 grant 双重约束，不引入微服务。

## 5. 实施方式

若批准，建议拆成六个可独立回滚、每包都跑全量测试的工作包：

1. **ADR 与守卫**：确认 schema 名称/表归属；新增“所有持久 SQL 必须 schema-qualified”测试，
   不移动数据。
2. **Schema/role bootstrap**：创建六个 schema、显式 migration table 路径和最小 grant；业务表
   仍留在 `public`。
3. **Governance + Evidence**：用事务内 `ALTER TABLE ... SET SCHEMA` 移动第一批表并更新
   repository；该操作保留 PostgreSQL object identity 和 FK，不复制数据。
4. **Observation + Canonical**：按 identity/universe、market、financial 三个小批次迁移，每批
   更新 SQL、FK/trigger 测试和 PIT replay。
5. **Research**：迁移 feature/label/experiment/validation/review 对象，复验 append-only、RBAC、
   Qlib exchange 和失败实验可见性。
6. **Serving + 收口**：建立稳定只读 views，API 改读 `serving`；一个兼容窗口后删除 `public`
   compatibility views。

明确禁止：一次性搬完 49 张表、复制表后长期双写、用 view 自动填零/改 trust、在同一提交同时
改数据语义和物理层、为了 DBeaver 好看重命名领域术语。

## 6. 每个迁移包的验收证据

- 迁移首次执行成功、二次幂等；
- 移动前后逐表 row count、主键集合/内容摘要一致；
- FK、unique/check、append-only trigger、index、sequence 和 grant 完整；
- repository 不依赖 `search_path`，所有 SQL 使用 schema-qualified 名；
- strict PIT leakage suite、API/OpenAPI、后端/前端全量测试通过；
- 没有数据 trust 晋级、没有测试 fixture/运行时假数据入库；
- DBeaver 中只需展开六个 schema 即可理解职责，`public` 最终只保留必要 extension 或兼容入口。

## 7. 建议决策

建议批准上述六层命名和“先 schema-qualified repository，再逐域 `ALTER TABLE SET SCHEMA`，最后
serving views”的迁移路线。不建议把层直接命名为 `ods/dwd/dws/ads`，因为那会掩盖本平台最
关键的 evidence、PIT trust、research label 和 governance 边界。

本文件获批前不得创建 schema、搬表、双写或修改运行时连接的 `search_path`。
