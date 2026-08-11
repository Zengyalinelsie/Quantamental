# A-Share Platform Next

一个面向 A 股多头选股、主动市场择时、事件研究、组合回测和未来实盘的研究平台。

本项目不是把两个来源仓库直接拼在一起。它采用“干净核心 + 适配器迁移”的方式：

- `daily_stock_analysis` 提供日常研究产品形态、工作台、Agent 编排、报告、通知和多数据源接入经验；
- `legacy_quant_platform` 提供 PIT 数据、证据链、版本对象、因子治理、信号、组合和现实回测合同；
- 新平台重新定义统一的决策语言、科学验证门和实盘边界。

## 当前状态

P0 领域合同和 P1 工程底座已通过 Capability Gate。P2 代码底座已完成，真实库已有
CSI800 当前 Security Master 799/800、CSI500 当日 Universe 500/500 和私人本地
`normalized_current` 数据；但多尺寸浏览器证据、完整历史 Universe、XBSE、2018+ 全范围行情、
股本和公司行动仍未完成，因此不宣称 P2 Gate 通过。P3 已完成 4 家公司、8 份官方 PDF、
2 条修订链、双时财务、真实数据诊断页面和首条 CSI500 被动波动率 Shadow baseline，
Capability Gate 通过。主动 Timing 仍 `unavailable`；P3.5 已完成 CSI500 当前 500 家、
2018–2025 年末三表的 12,000/12,000 工作单元，写入 35,505 条 `normalized_current` 观测，
其中 78 个合法空期显式保存且未填零。另有 CSI300 中 30 家的 720/720 工作单元和 2,120 条
观测；这些 current-only 批次不能用于 strict historical，也不代表 CSI300+CSI500 去重后的
700–800 家扩容或 PIT 治理完成。P4 W00–W06 的工程能力已完成：三类 company-level baseline、
统计引擎及独立库交叉验证、Experiment/Reviewer 生命周期、Qlib exchange 和完整 Factor
Workspace 均已接线。真实开发库的三因子资格审计已失败关闭；冻结窗口缺合格 `pit_verified`
输入，因此没有计算因子 score/IC/RankIC、没有晋级，P4 Gate 仍未通过。

运行时 API 没有默认 fixture，页面会诚实显示空状态；合同 fixture 只用于测试。免费原型源的可信上限为 `normalized_current`，不能冒充 `pit_verified`。当前状态不代表已经具备可盈利策略、模型科学有效、真实交易或真实账户连接能力。

```text
sources/                     # 只读来源仓库
  daily_stock_analysis/
  legacy_quant_platform/
docs/                        # 权威设计与迁移决策
platform/                    # 新平台代码，只在这里实现新能力
```

## 六个产品问题

1. 哪些公司值得投资？
2. 当前价格是否有吸引力？
3. 公司是否正在改善或恶化？
4. 新事件改变了什么？
5. 当前整体股票仓位应是多少？
6. 研究结论能否真实执行？

平台内部还必须回答四个支撑问题：

1. 当时究竟知道什么，数据可信吗？
2. 前四个判断如何合成为统一的预期收益、下行风险和置信度？
3. 历史结果为何与预期不同？
4. 模型、数据和执行是否正在失效？

## 文档入口

- [产品目标与边界](docs/00-product-vision.md)
- [两个来源仓库的代码审计](docs/01-donor-audit.md)
- [目标架构与领域对象](docs/02-target-architecture.md)
- [能力融合与迁移地图](docs/03-migration-map.md)
- [实施路线图](docs/04-execution-roadmap.md)
- [术语表](docs/05-glossary.md)
- [第一条黄金链路](docs/06-first-vertical-slice.md)
- [详细系统 Spec](docs/07-detailed-system-spec.md)
- [详细实施 Plan](docs/08-detailed-implementation-plan.md)
- [Spec 与 Plan 一致性审查](docs/09-spec-plan-consistency-review.md)
- [P1 实现与验证证据](docs/10-p1-implementation-evidence.md)
- [P2 数据来源覆盖矩阵](docs/11-p2-data-source-coverage-matrix.md)
- [P2 实现与验证证据](docs/12-p2-implementation-evidence.md)
- [P3 实现与验证证据](docs/13-p3-implementation-evidence.md)
- [数据源总清单与 Agent 选择路由](docs/14-data-source-catalog-and-agent-routing.md)
- [P4 实现与验证证据](docs/15-p4-implementation-evidence.md)
- [PostgreSQL 数据分层方案（待批准）](docs/16-postgresql-data-layering-proposal.md)
- [A 股数据源资格 ADR](docs/adr/0002-a-share-data-source-qualification.md)
- [私人本地研究持久化 ADR](docs/adr/0003-private-local-research-persistence.md)
- [组合式当前身份与 CSI 历史成分 ADR](docs/adr/0004-composed-current-identity-and-csi-membership.md)

## 开发入口

```bash
cd platform
PYTHON_BIN="${PYTHON_BIN:-python3.11}"  # 任一 Python 3.11+；本机可设为 python3.12
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 11), sys.version'
PYTHONPATH=src "$PYTHON_BIN" -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache "$PYTHON_BIN" -m compileall -q src
"$PYTHON_BIN" -m ruff check src tests
"$PYTHON_BIN" -m mypy src
```

### 私人本地真实数据回填

默认命令仍是只读 dry-run。真实执行只允许 `normalized_current`，并要求本地 ack、domains、数据库和 Parquet 路径。行情必须给显式 symbols；身份/Universe 另有与 symbols 互斥的 `--all-a-share` 明示门。以下命令只展示调用格式，不应在未确认供应商具体保存条款和未完成 migration 前执行：

```bash
cd platform
PYTHON_BIN="$PWD/.venv/bin/python"
# 需要真实 source 时显式安装；默认测试不要求 provider SDK 或网络
"$PYTHON_BIN" -m pip install -e '.[data]'
PYTHONPATH=src "$PYTHON_BIN" -m a_share_platform.workers.backfill \
  --provider baostock_sdk \
  --start 2018-01-01 --end 2018-12-31 \
  --symbols SH.600519 SZ.000001 \
  --domains raw_daily_bar trading_calendar

PYTHONPATH=src "$PYTHON_BIN" -m a_share_platform.workers.backfill \
  --provider baostock_sdk \
  --start 2018-01-01 --end 2018-12-31 \
  --symbols SH.600519 SZ.000001 \
  --domains trading_calendar \
  --database-url postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_layered_dev \
  --parquet-root ./var/private-research/parquet \
  --private-local-research-ack --execute

# 可独立分片：沪深当前 Security Master + 当日 CSI500；不含 XBSE，仍非 PIT
PYTHONPATH=src "$PYTHON_BIN" -m a_share_platform.workers.backfill \
  --provider a_share_identity_universe \
  --start 2026-08-10 --end 2026-08-10 \
  --all-a-share \
  --benchmarks 000905 \
  --domains security_master universe \
  --database-url postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_layered_dev \
  --parquet-root ./var/private-research/parquet \
  --private-local-research-ack --execute

# 快速安全链路：只为显式研究标的建立当前身份/Listing FK；Universe 仍禁止此模式
PYTHONPATH=src "$PYTHON_BIN" -m a_share_platform.workers.backfill \
  --provider a_share_identity_universe \
  --start 2018-01-01 --end 2026-08-10 \
  --symbols SH.600519 SZ.000001 \
  --domains security_master \
  --database-url postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_layered_dev \
  --parquet-root ./var/private-research/parquet \
  --private-local-research-ack --execute
```

第一个 execute 示例先回填不依赖 Listing FK 的交易日历。raw 日线必须先存在对应 symbol 在各日期唯一有效的 Security Master/Listing 映射，否则 canonical sink 会 fail closed。组合身份命令会逐证券查询 CNInfo 法定名称，可能较慢；显式 symbols 快速路径要求每个请求代码都存在且法定名全部通过，不允许用于 Universe。缺法定名称、代码复用或挂牌区间不兼容会显式失败/拒绝。历史指数成员默认仅可研究，`tradable_eligible=false`。Futu 可将 provider 改为 `futu_quote`，但当前只支持 `raw_daily_bar`，且只使用 `OpenQuoteContext`。这些数据禁止外部分发、`strict_historical`、生产决策和 `pit_verified`；测试没有替用户执行真实下载或入库。

两个直接使用 BaoStock SDK 的 source 共用本机 fail-closed guard：同一时刻只允许一个会话，所有 `login/query/logout` 都进入按上海自然日持久化的调用账本；平台每日硬上限 40,000 次、默认最小间隔 0.25 秒，供应商黑名单/限流信号触发至少 6 小时冻结并在重复信号后累加。guard 只以 OS 文件锁判断活会话，不会被数据库里遗留的 `running` 状态误阻断。guard 启用前的历史调用量无法精确追溯，不得补造。运行定向安全测试：

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_baostock_guard \
  tests.test_baostock_backfill_source \
  tests.test_identity_universe_backfill_source -v
```

多个已完成财务计划可以用 cohort audit 合并核对。命令默认只读；只有增加本地研究确认和
`--execute` 才持久化不可变 audit DatasetVersion 与 component/mapping/Universe lineage：

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.financial_cohort_audit \
  --job-ids \
    job:financial-backfill:csi500:akshare-pilot-3:2018-2025:v1 \
    job:financial-backfill:csi500:akshare-remaining-497:2018-2025:v1 \
  --expected-security-count 500 \
  --database-url postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_layered_dev
```

该审计同时核对 checkpoint/receipt、normalized observations、12,000 份 coverage report、
12,000 份 quality report、证券并集、拒绝行和显式空期。非空 provider rows 若全部未映射会
失败关闭，不能伪装成合法空期。

P3 Timing Shadow Ledger 已以真实 CSI500 当日 Universe 和 21 条 BaoStock 未复权收盘价
追加首条 `current_research + shadow + normalized_current` 被动波动率 baseline。worker 默认
dry-run，且同日重跑不再访问供应商或写库；它是可调度入口，不代表本仓库已配置常驻调度器。

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.timing_baseline \
  --benchmark-id index:000905 \
  --universe-version-id '<persisted-universe-version-id>' \
  --session 2026-08-10 \
  --target-volatility-ratio 0.12 \
  --database-url postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_layered_dev \
  --code-version git:<commit>
```

上述命令不带 `--execute`时不写数据；真实本地执行还要加
`--private-local-research-ack --execute`。主动预测、风险预测和主动调仓仍显式 `unavailable`。定向验证：

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_timing_shadow_ledger \
  tests.test_postgres_timing \
  tests.test_timing_baseline_math \
  tests.test_timing_baseline_runner \
  tests.test_timing_baseline_persistence \
  tests.test_timing_baseline_cli \
  tests.test_migrations -v
```

本地 PostgreSQL 使用专用主机端口 `55432`，避免与机器上已有的 PostgreSQL `5432` 冲突：

开发默认库现为 `a_share_platform_layered_dev`，按 `governance / evidence / observation /
canonical / research / serving` 六个职责 schema 分层；`public` 只保留 migration ledger。旧库
`a_share_platform_dev` 保持不变用于只读对账和回滚，不要在旧库执行 migration 0029。DBeaver
继续使用用户 `a_share_platform_dev`、密码 `local-only`、主机 `127.0.0.1`、端口 `55432`，把
Database 改为 `a_share_platform_layered_dev` 即可浏览新分层。

```bash
cd platform
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
docker compose up -d postgres
PYTHONPATH=src "$PYTHON_BIN" -m a_share_platform.adapters.postgres.cli
ASP_DATABASE_URL=postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_layered_dev \
PYTHONPATH=src "$PYTHON_BIN" -m uvicorn a_share_platform.api.app:app \
  --host 127.0.0.1 --port 8010 --reload
```

另开终端启动前端，浏览器访问 <http://127.0.0.1:5173/>：

```bash
cd platform/frontend
npm ci
PYTHON_BIN=../.venv/bin/python npm run generate:api
npm run dev
```

本项目固定使用前端 `5173`、后端 `8010`；不占用本机其他项目的 `8000`。Vite 默认把
`/api` 代理到 `http://127.0.0.1:8010`，需要覆盖时显式设置 `VITE_API_PROXY`。

P4 三因子资格命令默认 dry-run；只有显式本地研究确认才持久化 append-only 失败/成功审计：

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.factor_qualification \
  --database-url postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_layered_dev \
  --evaluated-at 2026-08-11T18:00:00+08:00 \
  --code-sha git:<commit>
```

当前数据库会正确返回资格失败；不要添加 `--execute` 期待生成因子数值。恢复真实 PIT 输入后，
仍须先 dry-run 审查 role DatasetVersion、覆盖和 lineage。

运行当前全量验证；若要包含真实 PostgreSQL migration smoke，显式传入本地验证库 URL：

```bash
cd platform
PYTHON_BIN="$PWD/.venv/bin/python" \
ASP_DATABASE_URL=postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_layered_dev \
./ci/verify.sh
npm --prefix frontend audit --audit-level=low
```

项目采用模块化单体起步。数据、研究、组合、交易和 Agent 有清晰边界，但第一版不拆微服务。
