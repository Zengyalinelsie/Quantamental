# PostgreSQL 分层影子库迁移证据

- 日期：2026-08-11
- 代码基线：`ee48430 feat: add layered PostgreSQL shadow schema`
- 旧库：`a_share_platform_dev`，保持不变，仅作为回滚和只读对账源
- 新库：`a_share_platform_layered_dev`，开发 API 当前使用该库

## 1. 迁移前审计

旧库为 PostgreSQL 17.10，包含 49 张平台业务表、`public.schema_migrations` 和 1 个 PIT view。
审计时没有活跃数据库会话、开放事务或超过 5 分钟的长事务。数据库约 377,845,427 bytes。

任务账本存在已知的历史状态收口问题：587 个 ingestion jobs 中 455 succeeded、131 failed、
1 running。唯一 running job 自 2026-08-10 10:23:32Z 后未更新，且数据库没有对应活跃连接；
另有 593 个 running checkpoints 属于 failed parent jobs。这些状态在影子迁移中原样保留，
没有静默修正，也没有被当作正在运行的抓取任务。

## 2. 一致性克隆

使用 `pg_dump --format=custom --no-owner --no-privileges` 对旧库取得一致性快照，再用
`pg_restore --single-transaction --exit-on-error` 恢复到新库。dump 大小约 18 MB，SHA-256：

```text
3df17f8045c0f197b913f3d28f923f8a0a780121eda08bc73795625be4152ddf
```

执行 0029 前，旧库和克隆库的 49 张业务表共 314,561 行；逐表使用排序后的 JSONB row hash
生成内容摘要，差异为 0。

## 3. 分层迁移与幂等性

只在新库执行 migration `0029_layered_schemas`。首次执行返回该版本，第二次执行无输出并正常
退出，证明 migration ledger 幂等跳过。旧库的最新版本仍是 0028。

迁移后对象分布：

| Schema | 表 | Sequence | View |
|---|---:|---:|---:|
| `governance` | 18 | 1 | 0 |
| `evidence` | 2 | 0 | 0 |
| `observation` | 6 | 1 | 0 |
| `canonical` | 16 | 8 | 0 |
| `research` | 7 | 0 | 0 |
| `serving` | 0 | 0 | 1 |
| `public` | 仅 `schema_migrations` | 0 | 0 |

## 4. 双库对账

- 49 张业务表、314,561 行，逐表 row count 和内容摘要差异均为 0；
- 49 表组合摘要：
  `17966eb327237c9f197145cb94bfd5a5af2ce5c22d5b3b73df0fbf721e73a980`；
- constraint、index、非内部 trigger 的逐表名称/类型/启用状态差异为 0；
- 10 个 sequence 名称集合一致；迁移后的 12 个 trigger functions 均位于职责 schema；
- `serving.strict_pit_universe_versions` 可查询，当前为 0 行，没有把 current Universe 冒充 PIT；
- DatasetVersion metadata 中显式 trust 分布前后一致：`normalized_current=14`、
  `pit_verified=2`、未在该 metadata key 表达的旧版本 13,298；迁移没有更新任何 DatasetVersion；
- `research.enforce_failed_factor_qualification_run()` 在真实 PostgreSQL 上执行了必然失败的
  transaction smoke test，返回预期领域错误并 rollback，未留下测试行。

新库大小约 355,915,443 bytes。与旧库体积不同来自 dump/restore 后物理页重写，不代表行缺失；
逻辑行数和内容摘要已经逐表闭合。

## 5. API 与浏览器证据

使用新库 DSN 启动只读 API 后，以下端点均返回 HTTP 200：

- Catalog 13,314 条；Quality 19,710 条；Lineage 77,639 条；Jobs 587 条；
- ExperimentRun 6 条；Factor review 0 条；空审批不是伪造完整度。

浏览器访问 `http://127.0.0.1:5173/desk`、`/system` 和 `/factors`：Dataset Catalog 可见真实
DatasetVersion，Factor Workspace 可见 6 个持久化失败实验、PIT 输入阻断和空指标，不用 hash
或缺失值生成图表。浏览器控制台无 error/warning。

Quality/Lineage 大集合的前端分页性能在本轮验收中单独发现并修复：表格只接收当前页切片，
Jobs 及每个 Job 的 coverage/checkpoint 也独立分页，分页总数仍使用真实完整数组长度；没有截断
证据或加入假数据。浏览器复验中 Quality 显示 20 行和 986 页，Jobs 显示 20 个任务和 30 页。

## 6. 边界与剩余风险

- 旧库未删除、未执行 0029、未双写；回滚方式是显式恢复旧 DSN；
- 当前本地开发登录 role 仍有高权限，独立 ingestion/research/reviewer/API role 与凭证轮换未实施；
- stale job/checkpoint 是待单独治理的数据状态问题；
- System API 仍一次传输完整 Catalog/Quality/Lineage/Jobs 集合；DOM 卡顿已解决，但初次加载仍可
  达数秒到十余秒，后续应增加保持审计总数的服务端 cursor pagination；
- P4 Capability Gate 仍未通过，因为缺合格 `pit_verified` 截面和 forward-return labels；
- 以上证据只证明物理分层、数据一致性和工程链路，不证明因子或模型科学有效。

## 7. P5 后续增量迁移

2026-08-11 在分层开发库执行 migration `0030_p5_investment_signal_ledgers`，对应代码提交
`e7e007a`。本次是 0029 切换完成后的增量建表，不改变第 2–4 节记录的“迁移时 49 表、314,561
行、0 差异”历史证据。

新增对象：

- `research.investment_views`、`research.investment_view_outcomes`、
  `research.expected_return_calibrations`、`research.signal_snapshots`；
- `serving.research_signal_snapshots` 和 `serving.production_signal_snapshots` 两个按 approval scope
  隔离的只读 view；
- 四张表均有 UPDATE/DELETE 阻断 trigger，并在数据库约束层保留 horizon、RunContext、trust、
  cutoff、自然键和 research/forward scope 约束。

执行后 migration ledger 存在该版本，四张新表行数均为 0。空表不是缺陷：P4 Gate 尚未通过，
当前没有满足用途审批的 factor/model，也没有可合法写入的真实 SignalSnapshot；本次未生成 demo
InvestmentView、伪 PIT 或生产信号。增量后的平台业务表为 53 张，`research` 为 11 张表，
`serving` 为 3 个 view。结构与自动测试通过只证明工程合同，不证明模型科学有效。

## 8. P5 frozen valuation input 增量迁移

2026-08-14 只在分层开发库执行 migration `0031_p5_frozen_valuation_inputs`；首次执行返回该版本，
第二次执行无输出且正常退出。旧库未修改。该 migration：

- 新增 `research.valuation_input_bundles`，按 security、decision time、data mode、trust 和 bundle
  version 精确保存完整 JSONB 文档、content hash 与 DatasetVersion lineage；
- 用数据库约束阻止 `strict_historical + normalized_current`、未来可用时间、空 DatasetVersion
  集合和文档/列身份不一致；UPDATE/DELETE 由 append-only trigger 阻断；
- 为 `canonical.industry_memberships` 增加 DatasetVersion、trust、observed/available 时间列。
  既有分类行全部保留 NULL lineage，migration 没有猜测或回填来源；后续新 Security Master
  观察才可写入完整 `normalized_current` lineage。

真实 dry-run 使用 `security:cn:XSHE:000009:a-share` 和
`2026-08-14T15:00:00+08:00`。数据库返回 72 条 current 财务观察，但相邻季度 YoY 改善窗口不完整；
近期价格/share-capital 联合输入和版本化 comparable 不可用。因此结果为 `qualified=false`、
`bundle_version_id=null`、`writes_performed=false`，`research.valuation_input_bundles` 仍为 0 行。
这证明失败关闭路径工作，不代表已有真实合格估值结果。

增量后的平台业务表为 54 张，`research` 为 12 张表，`serving` 仍为 3 个 view。migration、
Repository、qualification、compiler 和 CLI 的自动测试通过只证明工程合同，不证明估值模型、
InvestmentView 或任何投资策略科学有效。
