# Step 04 Spec / Plan：P5 真实冻结产物 Gate

> 状态：`gate_blocked`  
> 对应：Plan P5 Gate、Roadmap Step 4  
> 关联 SPEC：018–019、024–025、030、041、047、050–052  
> 依赖：Step 1 工程完成、Step 2 数据合格、Step 3 至少一个获批输入版本

## Spec

### 目标

在一个真实决策日生成首条完整的 frozen valuation bundle → InvestmentView → Review → SignalSnapshot → Frozen Artifact 链，并保持 Outcome 后续只能追加。

### 不变量

- strict 路径固定 `strict_historical + research + pit_verified`；
- financial/price/share-capital/comparable 均来自 exact frozen bundle；
- quality/valuation/revision/scenario 必须量化，event 在 P8 前明确 unavailable；
- DatasetVersion、definition hash、model/factor review、bundle version、availability 闭合；
- View 的 component、distribution、downside、confidence 和 residual 由领域核心产生；
- Reviewer 身份和 scope 由服务端拥有；
- Snapshot 只绑定对当前 use case 获批的不可变版本；
- preview 零写入，ensure 幂等，冲突失败；
- 组合层只读 Snapshot/View，不读新闻文本或页面字段。

### 验收

- 至少一个真实 security/decision time/horizon 完整通过；
- 不合格 current、partial、future availability、缺 lineage、scope mismatch 全部零写入；
- View、Review、Snapshot、Artifact 和 lineage 可从 API/页面互相追踪；
- 到期前 Outcome pending，到期后 append-only；
- 页面四视口展示真实对象或 blocker。

## Plan

### Task 1：选择真实 Gate candidate

从 Step 3 已获批版本选择 security、decision time、UniverseVersion 和 horizon，形成只读 manifest；不得挑选未来可见数据或在运行后改候选规则。

### Task 2：编译 frozen bundle

运行 valuation input worker dry-run，审计三域 coverage/lineage/availability；通过后显式 execute 并记录 bundle hash。失败则保存 blocker 并停止下游写入。

### Task 3：编译和审查 InvestmentView

用 approved model output adapter 调用 `investment_view_compilation`；生成 Artifact；通过服务端 Reviewer 路径提交用途审查。任何人工修改产生新版本，不能改原 View。

### Task 4：生成 SignalSnapshot

复用 signal application/repository，验证 exact review scope、Universe/cutoff/trust 和 rank inputs；research 与 forward serving view 隔离。

### Task 5：端到端 API/浏览器证据

按 Screen → Security → View → Evidence → Approvals → Alpha Model 路径验收；无对象时保持真实 0，不导入原型数字。
高保真结构、InvestmentView 独立详情、四档视觉对照和页面六态按 PUI-03 执行。真实 P5 Artifact Gate
与 PUI-03 的 Design Parity/Runtime Product 分别报告，任何一项不得代替另一项。

### 定向验证

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest tests.test_postgres_valuation_inputs tests.test_investment_view_compilation tests.test_postgres_expected_return tests.test_postgres_signals -v
PYTHONPATH=src .venv/bin/python -m unittest tests.test_research_workspace_api tests.test_signal_snapshots -v
npm --prefix frontend test -- --run ResearchP5Screen WorkspacePage.research
```

新增 P5 Evidence 文档，记录真实 candidate、DatasetVersion、run/hash、失败项和数据库行数。通过 Gate 不代表模型科学有效。
