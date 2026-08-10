# AGENTS.md

本文件是 `a-share-platform-next` 的协作规则真源。

## 不可违反的边界

- `sources/daily_stock_analysis` 和 `sources/legacy_quant_platform` 是只读来源，不直接修改。
- 新实现只进入 `platform/`；权威决策记录和迁移说明进入 `docs/`。
- 不把来源仓库整目录复制进新平台。先写迁移 ADR、明确许可证和目标合同，再逐模块迁移。
- 不触碰 `/Users/macbook/agent-agnostic-stock-skills-clean` 的未提交工作树。
- 未经用户明确要求，不执行 `git commit`、`git push`、下单、撤单或账户写操作。
- 不把 LLM 文本当成价格、财务数值、公告时间或交易结果的权威来源。
- 严格历史回测只允许消费 `pit_verified` 数据，并强制检查 `available_at <= decision_time`。
- 回测、模拟盘和实盘共用同一决策与组合代码；执行适配器可以不同。
- Agent 可以提取、分类、解释和提出假设，不能绕过风险门、审批门或直接拥有交易权限。

## 工程原则

- Python 3.11+，模块化单体，领域核心不依赖 Web 框架和供应商 SDK。
- 金额、比例、股数和时间必须有明确单位、币种、时区和含义。
- 数据缺失、无权限、时间不可信和冲突必须显式表达，禁止自动填零。
- 所有生产数字可追溯到数据版本、公式/模型版本、代码版本和运行记录。
- 先建立简单基线，再增加模型复杂度。
- 任何“科学有效”声明必须有样本外结果、统计不确定性、成本后结果和可复现产物。

## 默认验证

```bash
cd platform
PYTHONPATH=src python3.11 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache python3.11 -m compileall -q src
```

## 文档纪律

- 产品目标和非目标：`docs/00-product-vision.md`
- 来源代码证据与判断：`docs/01-donor-audit.md`
- 权威目标架构：`docs/02-target-architecture.md`
- 迁移取舍：`docs/03-migration-map.md`
- 阶段、门槛和完成定义：`docs/04-execution-roadmap.md`
- 重大且不可逆的技术决策：`docs/adr/`
