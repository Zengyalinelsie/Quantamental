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
