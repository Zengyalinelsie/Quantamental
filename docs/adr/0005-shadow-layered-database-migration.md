# ADR-0005：影子库 PostgreSQL 职责分层迁移

- 状态：Accepted
- 日期：2026-08-11
- 范围：本地开发 PostgreSQL；不授权生产切换、数据分发或任何交易能力

## 背景

现有 49 张平台业务表、原始证据、供应商 observation、canonical 事实、研究产物和治理记录都在
`public`。表内已有 `raw / normalized_current / pit_verified` 信任合同，但物理命名空间没有表达
职责边界，运维审计和 DBeaver 浏览困难。传统 `ods/dwd/dws/ads` 不能准确表达原始证据、PIT、
研究标签和跨层治理。

旧库已有真实私人本地研究数据，不能用原地迁移冒险，也不能把 schema 位置误当成数据可信度。

## 决策

1. 新开发库固定为 `a_share_platform_layered_dev`；旧库 `a_share_platform_dev` 保持只读不变，
   作为回滚源。两者使用同一台本地 PostgreSQL 17 服务。
2. 采用六个职责 schema：`governance`、`evidence`、`observation`、`canonical`、`research`、
   `serving`。49 张表必须且只能有一个归属；`public.schema_migrations` 是 bootstrap ledger 例外。
3. 迁移先做一致性 dump/restore，再只在影子库执行 migration 0029。对象使用 PostgreSQL
   `SET SCHEMA` 保留 identity、FK、index、trigger 和 sequence 依赖，不复制表、不长期双写。
4. 所有运行时持久 SQL 必须显式 schema-qualified，不允许用 `search_path` 隐式路由。动态表名只
   能从受控表归属映射生成。
5. schema 只表示职责，不表示信任。迁移不得更新业务行、重写 DatasetVersion、补造 available-at，
   或把 `normalized_current` 晋升为 `pit_verified`。
6. 切换前必须比较 49 张表行数和内容摘要、DatasetVersion/trust 分布、约束、索引、触发器、函数
   与 view，并在真实 PostgreSQL 上验证首次迁移、二次幂等和 append-only 行为。
7. 旧库中的 stale job/checkpoint 状态按原值迁移并显式记录；物理迁移无权静默修复业务状态。
8. 本轮不创建新的登录凭证或假装完成最小权限 RBAC。独立 ingestion/research/reviewer/API role
   需要后续获批的凭证轮换与部署工作包；当前本地开发 role 的高权限是已知风险。

## 结果

开发 API 可以在验证后显式切到分层影子库，DBeaver 可按职责浏览数据；旧库仍可用于只读对账和
快速回滚。代价是本地保留两份数据库空间，迁移窗口内禁止并发写入，且 RBAC 仍需后续治理。

该决策只证明物理职责和迁移可审计，不证明任何数据已达到 PIT、任何因子/模型科学有效，也不
授权连接真实账户或执行交易。
