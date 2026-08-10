# A-Share Platform Next

一个面向 A 股多头选股、主动市场择时、事件研究、组合回测和未来实盘的研究平台。

本项目不是把两个来源仓库直接拼在一起。它采用“干净核心 + 适配器迁移”的方式：

- `daily_stock_analysis` 提供日常研究产品形态、工作台、Agent 编排、报告、通知和多数据源接入经验；
- `legacy_quant_platform` 提供 PIT 数据、证据链、版本对象、因子治理、信号、组合和现实回测合同；
- 新平台重新定义统一的决策语言、科学验证门和实盘边界。

## 当前状态

P0 领域合同已在提交 `0c32725` 完成；P1 工程底座、治理账本、设计系统、六导航应用 Shell 和只读 API 骨架已在提交 `ebbe025` 通过 Capability Gate。P2 数据底座已在提交 `923f678` 完成；当前已增加显式 ack 的私人本地 `normalized_current` 行情/日历回填路径，但 320/768/1024/1440 浏览器视觉证据和真实全范围回填仍未完成，因此暂不宣称 P2 Capability Gate 通过。P3-W01–W03 已建立不可变官方披露证据链、Canonical Metric Registry 和双时间 PIT Financial Repository，P3-W04–W06 仍在进行。

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
- [A 股数据源资格 ADR](docs/adr/0002-a-share-data-source-qualification.md)
- [私人本地研究持久化 ADR](docs/adr/0003-private-local-research-persistence.md)

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

默认命令仍是只读 dry-run。真实执行仅支持显式小范围 `normalized_current` 数据，并要求本地 ack、symbols、domains、数据库和 Parquet 路径。以下命令只展示调用格式，不应在未确认供应商具体保存条款、未完成 migration 和 Security Master 映射前直接扩大范围：

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
  --database-url postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_dev \
  --parquet-root ./var/private-research/parquet \
  --private-local-research-ack --execute
```

上面的 execute 示例先回填不依赖 Listing FK 的交易日历。raw 日线必须先存在对应 symbol 在各日期唯一有效的 Security Master/Listing 映射，否则 canonical sink 会 fail closed。Futu 可将 provider 改为 `futu_quote`，但当前只支持 `raw_daily_bar`，且只使用 `OpenQuoteContext`。这些数据禁止外部分发、`strict_historical`、生产决策和 `pit_verified`；测试没有替用户执行真实下载或入库。

本地 PostgreSQL 使用专用主机端口 `55432`，避免与机器上已有的 PostgreSQL `5432` 冲突：

```bash
cd platform
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
docker compose up -d postgres
PYTHONPATH=src "$PYTHON_BIN" -m a_share_platform.adapters.postgres.cli
PYTHONPATH=src "$PYTHON_BIN" -m uvicorn a_share_platform.api.app:app --reload
```

另开终端启动前端，浏览器访问 <http://127.0.0.1:5173/>：

```bash
cd platform/frontend
npm ci
PYTHON_BIN=python3.11 npm run generate:api  # 可替换为任一 Python 3.11+
npm run dev
```

运行当前全量验证；若要包含真实 PostgreSQL migration smoke，显式传入本地验证库 URL：

```bash
cd platform
PYTHON_BIN="$PWD/.venv/bin/python" \
ASP_DATABASE_URL=postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_dev \
./ci/verify.sh
npm --prefix frontend audit --audit-level=low
```

项目采用模块化单体起步。数据、研究、组合、交易和 Agent 有清晰边界，但第一版不拆微服务。
