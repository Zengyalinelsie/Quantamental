# A-Share Platform Next

一个面向 A 股多头选股、主动市场择时、事件研究、组合回测和未来实盘的研究平台。

本项目不是把两个来源仓库直接拼在一起。它采用“干净核心 + 适配器迁移”的方式：

- `daily_stock_analysis` 提供日常研究产品形态、工作台、Agent 编排、报告、通知和多数据源接入经验；
- `legacy_quant_platform` 提供 PIT 数据、证据链、版本对象、因子治理、信号、组合和现实回测合同；
- 新平台重新定义统一的决策语言、科学验证门和实盘边界。

## 当前状态

目前完成的是 Phase 0：来源审计、目标架构和第一批核心合同。尚未声称已经具备可盈利策略或可连接真实账户的能力。

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

## 开发入口

```bash
cd platform
PYTHON_BIN="${PYTHON_BIN:-python3.11}"  # 任一 Python 3.11+；本机可设为 python3.12
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 11), sys.version'
PYTHONPATH=src "$PYTHON_BIN" -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache "$PYTHON_BIN" -m compileall -q src
```

项目采用模块化单体起步。数据、研究、组合、交易和 Agent 有清晰边界，但第一版不拆微服务。
