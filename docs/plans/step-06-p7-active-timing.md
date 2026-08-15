# Step 06 Spec / Plan：P7 主动 Timing Lab

> 状态：`dependency_blocked`（决策已冻结，等待 P6）  
> 对应：Plan P7-W01–W05/Gate、Roadmap Step 6  
> 关联 SPEC：007、026、035、040、048  
> 依赖：P3 Timing ledger、P6 benchmark/cost/portfolio framework

## Spec

### 目标与非目标

建立主动预测市场收益/方向/下行风险的研究与不可回填 Shadow 链路，并与 static、moving-average、volatility-target 基线比较。

非目标：被动风险控仓不能冒充主动预测；Capability Gate 不自动产生非零仓位影响；不承诺模型有效。

### 领域合同

- `TimingTargetDefinition`：benchmark/proxy、1/5/20/60 sessions、return/direction/drawdown/tail、overlap policy；
- `TimingFeatureSnapshot`：PIT macro/valuation/breadth/trend/liquidity/volatility/risk-appetite 和 availability；
- `TimingExperiment`：split/model/baseline/code/data/seed/metrics/artifact；
- `TimingForecast`：forecast time、horizon、probability/distribution、active adjustment、evidence/hash；
- `TimingOutcome` 和 `CalibrationSnapshot` append-only；
- `TimingPromotionReview`：scope、max impact、expiry、rollback；
- production adjustment 在审批前固定 0，无法由请求参数提升。

### 验证合同

- expanding/rolling walk-forward，无随机未来泄漏；
- overlapping horizon 使用 HAC/合适 block bootstrap；
- Brier/log loss/calibration、AUC/balanced accuracy、return/error distribution；
- net utility、turnover、drawdown 和成本后结果；
- regime/subperiod、static/passive baselines；
- Shadow 与 historical backtest 分屏展示，不能合并曲线。

### 决策

- ADR-0006 已冻结 benchmark/proxy 与 P6 policy 对齐；
- 宏观发布时间和修订 source 资格未过时，对应 feature unavailable；
- 最大影响为 D2，Shadow 固定 0。

### 验收

- 至少一个简单逻辑/线性主动模型真实存在；
- 每日 forecast no edit/no backfill；
- outcome/calibration 到期追加；
- 科学失败保存且影响 0；
- Timing Lab/Shadow/Monitor 四视口验收。

## Plan

### Task 1：目标、标签和 PIT feature 合同

预计新增 `domain/timing_research.py`、`application/timing_features.py`、tests；先标签 session/overlap/可知时间，label repository 与 serving API 隔离。

### Task 2：基线与主动模型

在 provider-neutral model port 上实现 static/MA/vol target 和 logistic/linear baseline；每个模型有 deterministic fixture、版本和无未来输入测试。

### Task 3：验证引擎

新增 walk-forward/calibration/HAC/DM/net utility 模块和独立 statsmodels/sklearn 对照；不根据结果临时改 metric。

### Task 4：Shadow ledger、Outcome 和 Review

扩展已有 timing ledger：唯一 natural key、append-only trigger、no-backfill clock guard、mature outcome worker、promotion scope/max impact/rollback。

### Task 5：API 和页面

新增 Timing Experiment/Forecast/Outcome/Calibration/Review API；实现 Timing Lab、Desk latest Shadow、Monitoring Timing、Portfolio active/passive split。
对应产品面、精确原型对照和四档浏览器验收按 PUI-06 执行；historical/OOS/forward 必须分屏，未晋级
主动模型的运行时组合影响继续为 0。

### Task 6：前瞻运行与 Gate

先 dry-run，再本地 research Shadow；记录真实日序列。历史回放不能冒充前瞻天数；Gate Evidence 分别报告 historical/OOS/forward。

### 验证

定向测试覆盖 label leakage、overlap、calibration、no-backfill、scope escalation；阶段收口执行全量、独立统计、migration、API、四视口浏览器。Evidence 文件按最新编号新增。
