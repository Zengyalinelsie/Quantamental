# P1 实现与验证证据

日期：2026-08-10

范围：`docs/08-detailed-implementation-plan.md` 的 P1-W01 至 P1-W05
结论：P1 Capability Gate 通过；P2 未开始。

此结论只证明工程底座、治理合同、只读 API 和前端 Shell 按 P1 范围工作。它不证明因子、择时、组合或任何投资模型科学有效，不代表可盈利，也不授权真实交易、真实下单或真实账户连接。

## 1. 工作包交付

| 工作包 | 交付证据 |
|---|---|
| P1-W01 | `domain/application/ports/adapters/api/workers` 边界、环境 settings、JSON logging、trace/run context、Compose、migration runner、统一验证脚本 |
| P1-W02 | `DatasetVersion`、`RunRecord`、`Artifact`、`LineageEdge`，内容 hash 冲突、幂等写、失败保留与状态机 |
| P1-W03 | React 19、Vite 7、AntD 6、Pro Components、Less token、语义色、`NumericCell`、页面标题、证据抽屉与五态组件 |
| P1-W04 | 六项路由、280/72 侧栏、移动 Drawer、双轴运行标签、Universe/Portfolio、双时点、只读环境、旧路由 redirect、URL 筛选/排序 |
| P1-W05 | FastAPI 只读 API、统一 envelope、Problem Details、OpenAPI 类型生成、匿名身份、deny-by-default 权限和越权负向测试 |

## 2. TDD 证据

每个工作包先建立失败测试或失败验证命令，再实现最小代码并回归。最终测试分布如下：

- Python：54 个测试，覆盖领域、架构依赖、治理账本、migration runner、settings、observability、权限和 API 合同；
- 前端：13 个测试，覆盖 token、数值显示、五态、workspace 状态、路由和应用 Shell；
- 额外红绿证据：本机 `5432` 冲突先由 settings 测试复现，再切换 Compose/default URL 到 `55432`；ESLint 9 缺失 flat config 先由 `npm run lint` 失败暴露，再补配置并纳入统一验证脚本。

测试数据只存在于单元测试或 contract fixture。生产运行时页面和 API 没有注入 demo 股票、行情、财务、组合或研究数值。

## 3. PostgreSQL migration

本地 Compose PostgreSQL 17 使用 `127.0.0.1:55432`，容器内部仍为 5432。空库验证结果：

```text
首次执行：0001_governance_ledger
第二次执行：无输出、退出码 0
schema_migrations：0001_governance_ledger
dataset_versions：0 行
run_records：0 行
artifacts：0 行
lineage_edges：0 行
```

迁移在事务内执行，失败会 rollback；成功版本不可重复应用。当前没有自动 downgrade migration。若已应用的环境需要回退，必须先保留数据库备份并采用经过审查的 forward migration 或从备份恢复，不能直接删生产表。P1 本地空库可重新创建，但本轮没有执行数据卷删除。

## 4. API 与安全边界

只读端点：

- `/api/health`
- `/api/version`
- `/api/capabilities`
- `/api/identity`
- `/api/datasets`
- `/api/runs`
- `/api/artifacts`

OpenAPI 中没有 POST/PUT/PATCH/DELETE。请求 query 不能提升 `data_mode` 或 `deployment_stage`；`X-Role` 不能冒充已认证身份。P1 没有可信身份提供者，因此实际请求主体固定为匿名只读；角色矩阵只是服务端合同，不等于身份系统已经上线。Researcher 和 Agent 没有下单权限，API 也没有账户或订单入口。

## 5. 前端、来源与浏览器验证

视觉来源只读参考：

```text
repository: /Users/macbook/agent-agnostic-stock-skills-clean
reference commit: 844fb4fffbab394a45056a6e734f3c8a6d9cbb5d
files: quant-platform/frontend/src/styles/tokens.less
       quant-platform/frontend/src/styles/global.less
       quant-platform/frontend/src/components/NumericCell.tsx
```

参考工作树中的这些文件存在未提交状态；本轮没有修改该工作树，也没有整文件复制。新平台在 `platform/frontend` 中按目标合同重写。

浏览器验证矩阵：

| 视口宽度 | 结果 |
|---:|---|
| 1440 | 桌面侧栏、表格和全局上下文正常，无页面级横向溢出 |
| 1024 | 桌面布局正常，无页面级横向溢出 |
| 768 | 切换移动导航 Drawer，路由可用，无页面级横向溢出 |
| 320 | 单列紧凑布局和移动 Drawer 可用，无页面级横向溢出 |

六个导航路由、旧路由 redirect、桌面和移动导航均已点击验证。全局证券搜索为空，Universe、Portfolio、AS OF 不做默认选择。未接能力逐项给出 unavailable/未启用原因。

生产构建的 gzip JavaScript 总量约 592.49 KB，低于 SPEC 的 1 MB SHOULD。Ant Design vendor 原始 chunk 为 1.41 MB，Vite 仍给出单 chunk 超过 500 KB 的优化提示；该提示被保留为后续性能优化项。

## 6. 最终命令与结果

验证解释器为 Python 3.12.13，满足项目 Python 3.11+ 合同。当前机器没有名为 `python3.11` 的可执行文件，因此没有声称本轮在 Python 3.11 上执行过。

```bash
cd platform
env PYTHON_BIN=/absolute/path/to/python-3.11-or-later \
  ASP_DATABASE_URL=postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_dev \
  ./ci/verify.sh

cd frontend
npm audit --audit-level=low
```

结果：

```text
Python unittest: 54 passed
compileall: passed
Ruff: passed
mypy: passed, 26 source files
PostgreSQL migration smoke: passed
ESLint: passed
Vitest: 13 passed in 6 test files
TypeScript + Vite production build: passed
npm audit: 0 vulnerabilities
```

## 7. P1 未完成项与后续边界

- 没有 A 股 security master、历史股票池、行情或公司行动；属于 P2；
- 没有正式 PIT 财务、公告和修订数据；属于 P3；
- 没有因子、估值、改善、择时、组合、回测或科学 Promotion Gate 结果；属于 P4–P7；
- 没有事件 Agent、完整治理 UI、Paper OMS 或真实执行；属于 P8–P10；
- P11 Limited Live 仍需 P10 长期稳定以及用户另行明确授权，本轮绝不进入；
- API 当前使用内存治理 read adapter 返回真实空集合；PostgreSQL 持久化读写 adapter 的业务接线留给后续工作包；
- 前端目前是完整 P1 Shell，不是所有业务能力已经接满的最终系统。

因此，P1 Capability Gate 通过与“模型科学有效”是两个不同结论；本文件只给出前者。
