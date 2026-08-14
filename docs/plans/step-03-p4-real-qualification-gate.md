# Step 03 Spec / Plan：P4 三因子真实资格 Gate

> 状态：`gate_blocked`  
> 对应：Plan P4-W00–W06/Gate、Roadmap Step 3  
> 关联 SPEC：016–023、042–044、048  
> 依赖：Step 2 合格 PIT 截面和 forward-return labels

## Spec

### 目标与非目标

用真实、冻结、合格的 PIT 截面运行质量、估值预期差和改善三类因子，保存成功或失败的科学结果并执行用途审批。

非目标：不保证因子有效；不为获得 IC 而放宽覆盖、改窗口或筛样本；不把 current qualification audit 当 strict experiment。

### 不变量

- Experiment 绑定 exact DatasetVersion/Universe/Feature/Factor/code/parameter/seed；
- label 与生产特征隔离；
- 截面覆盖、available time、行业/市值中性、缺失和 outlier policy 版本化；
- IC/RankIC、HAC/bootstrap、分层、单调性、衰减、换手、walk-forward/OOS 和多重检验完整；
- 独立库交叉验证的输入与主统计器完全一致；
- 失败 Experiment/Validation/Review 不可删除或改成成功；
- Capability Gate 与 Factor Promotion Gate 分离。

### 产物

- FactorPanel/FeatureSnapshot；
- ExperimentRun、ValidationReport、Artifact 和 lineage；
- FactorVersion 生命周期和 FactorPromotionReview；
- Qlib export/Recorder import 对照；
- Factor Workspace 展示真实指标或明确失败原因。

### 验收

- 三类因子各至少一个真实合格冻结窗口运行；
- 主统计器与独立库在既定容差内一致；
- 负结果完整保存；
- 只有通过科学门和用途审批的版本可供 Step 4 消费。

## Plan

### Task 1：PIT readiness 重跑

复用 `application/factor_qualification.py`、`workers/factor_qualification.py` 和 PostgreSQL audit。先对 Step 2 输出执行 dry-run；任何一项不合格则保存新的失败 audit，不进入分数计算。

### Task 2：冻结三类 panel

复用 features/factor baseline modules 和 repositories；新增真实窗口 fixture/manifest。检查行业模板、单位、coverage、neutralization 和 label cutoff。

### Task 3：统计与独立对照

复用 `domain/factor_statistics.py`、`factor_panel_statistics.py`、`factor_validation.py`、`validation/statistical_crosscheck.py`；扩展真实 panel 规模和边界测试，不修改统计定义追逐结果。

### Task 4：Experiment/Reviewer/Qlib 产物

复用 experiment、factor review 和 Qlib exchange；生成 exact Artifact 和 reviewer evidence pack。失败保持 draft/rejected；成功仍需用途 scope。

### Task 5：API、Workspace 和浏览器验收

真实 API 展示窗口、coverage、统计、交叉验证、review 和 blocker；刷新后无运行时 fixture 或控制台错误。

### 定向验证

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest tests.test_factor_qualification_audit tests.test_factor_panel_statistics tests.test_statistical_crosscheck -v
PYTHONPATH=src .venv/bin/python -m unittest tests.test_experiment_application tests.test_factor_review_application tests.test_qlib_experiment_exchange -v
npm --prefix frontend test -- --run FactorWorkspace
```

Gate 证据更新 `docs/15-p4-implementation-evidence.md`。科学失败不等于平台实现失败，也绝不能被表述为因子有效。
