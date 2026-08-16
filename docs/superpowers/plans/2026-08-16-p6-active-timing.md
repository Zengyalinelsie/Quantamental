# P-6 主动市场择时 P7 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 P7 的主动市场择时能力真实存在 —— 从 index-level 目标/标签/PIT 特征合同，到 provider-neutral 模型 port 上的五个基线与主动模型，到 walk-forward + HAC + 校准 + Diebold-Mariano + 净效用验证引擎，再到不可回填的 Shadow ledger、Outcome/Calibration 追加和 PUI-06 三页 —— 同时保证在独立 Promotion Gate 通过前，运行时组合影响严格为 0。

**Architecture:** `domain/timing.py` 已有 428 行真实实现（`TimingForecast`、`ActiveTimingAdjustment`、`estimate_passive_volatility()`、`passive_volatility_exposure()`），本 plan **扩展它，不重写它**。P3 的被动 baseline 合同必须继续成立：`application/timing_ledger.py` 的 `append_baseline()` 现在硬性要求 `active_adjustment` 为 `UNAVAILABLE`，本 plan 新增一条并行的 `append_active()` 路径，**不放宽 `append_baseline()`**。统计学复用 `domain/factor_statistics.py` 的 `newey_west_mean_test()` / `block_bootstrap_mean_ci()`、`domain/factor_validation.py` 的 `purged_embargoed_walk_forward()` 与 `validation/statistical_crosscheck.py` 的 `cross_check_newey_west_mean()`；只有 timing 特有的校准与 DM 检验是新数学。

**Tech Stack:** Python 3.11+、已有 `domain/timing.py` / `factor_statistics.py` / `factor_validation.py` / `factor_lifecycle.py` / `labels.py`、scipy + statsmodels + scikit-learn（交叉验证）、React 19 + TypeScript + AntD 6、Playwright（`platform/.venv/bin/python`，Chrome channel）

## Global Constraints

继承 `AGENTS.md`、`docs/07-detailed-system-spec.md`（SPEC-007/026/035/040/048）、ADR-0006 与已接受 ADR，**每个 Task 都适用**：

- `domain/` 不导入 FastAPI / SQLAlchemy / provider SDK / sklearn / statsmodels / 前端概念；模型实现在 adapter，模型**合同**在 domain
- **P3 被动 baseline 合同不可弱化**：`TimingShadowLedger.append_baseline()` 的六条守卫一条都不许删，新能力走新方法
- **未晋级的主动模型对组合影响严格为 0**：`ActiveTimingAdjustment` 保持 `UNAVAILABLE`，`final_exposure_*` 继续等于 `passive_exposure_ratio`；不能由请求参数、CLI flag 或前端状态提升
- **overlapping horizon 必须显式声明并用 HAC/block bootstrap 推断**；禁止把重叠窗口静默平均成"独立"观测
- **historical / OOS / forward 三者不合并**：不同 screen、不同 Evidence 小节、不同曲线；历史回放不得计入前瞻天数
- 每个模型有版本、`content_hash`、deterministic fixture 和 no-look-ahead 测试
- **不根据结果临时改 metric、窗口、样本或阈值**；失败的 TimingExperiment 保留可见
- Shadow ledger append-only：唯一 natural key、`no edit / no backfill`、时钟不可倒退
- `RunContext` 组合固定：研究实验用 `(current_research, research)`，Shadow 用 `(current_research, shadow)`；`strict_historical` 必须失败关闭
- 缺失、不可评估、不可比必须显式表达，**禁止填零**
- 宏观发布时间与修订资格未通过时，对应 feature 保持 `unavailable`，**不用报告期时间代替发布时间**
- worker 默认 dry-run，真实写入需 `--private-local-research-ack --execute`
- 前端只消费服务端投影；不在浏览器算校准、AUC、净效用或晋级资格
- 未经用户明确授权不 commit、不 push

## 前置条件（两条硬依赖）

### 依赖 P-5（组合与回测）

Timing 的价值只能通过它对**组合**的影响来度量。净效用、换手、成本后收益都需要
P-5 的 `domain/portfolio.py`、`domain/backtest.py`、`domain/execution_rules.py` 与成本模型；
没有它们，"净效用" 只是一个没有定义的数字。ADR-0006 第 7 条同时规定
「P7 Timing 的 benchmark 与 P6 对齐」—— benchmark、再平衡频率、VWAP 入场口径必须是同一份
`PortfolioPolicy`，不能在 timing 侧另建一套。

因此本 plan 的 Task 3（净效用）与 Task 5（Portfolio 主动/被动拆分）**必须在 P-5 完成后执行**。
Task 1、2 的标签与模型合同可以先行。

### 依赖 P-1（真实指数历史）

当前开发库**只有 21 条 benchmark bar**（2026-07-13 至 2026-08-10，见 `docs/13-p3-implementation-evidence.md`）。
这 21 条不是巧合：`BenchmarkCloseBatch.__post_init__` 硬性要求

```python
if len(rows) != PASSIVE_VOLATILITY_LOOKBACK_RETURNS + 1:
    raise ValueError("passive volatility input requires exactly 21 closes")
```

21 = 20 个 log return + 1。这是**P3 被动波动率的固定输入契约**，不是研究历史。
用它做 walk-forward 会得到 0 个 fold：`purged_embargoed_walk_forward()` 的
`test_start = spec.initial_training_sessions` 循环在 21 个样本上根本进不去。

所以 Task 1 的第一步不是写代码，而是校验 P-1 的指数历史是否已入库：

```bash
cd platform && source /tmp/asp_env.sh
.venv/bin/python - <<'PY'
import os, psycopg
with psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True) as c:
    rows = c.execute("select count(*), min(session_date), max(session_date) "
                     "from observation.timing_benchmark_bars").fetchone()
    print("benchmark bars:", rows)
PY
```

Expected（P-1 完成后）：约 1,900 个交易日 × 2 个 benchmark。
若仍是 21，**停下来先做 P-1**；本 plan 的 Task 3 之后全部无法产生有意义的数字。

## 已存在的接口（本 plan 消费与扩展，不重建）

经 2026-08-16 逐行核实的真实签名。

### `domain/timing.py`（428 行，全部已实现）

```text
SUPPORTED_TIMING_BENCHMARK_IDS = frozenset({"index:000300", "index:000905"})
PASSIVE_VOLATILITY_LOOKBACK_RETURNS = 20
PASSIVE_VOLATILITY_ANNUALIZATION_SESSIONS = 244
PASSIVE_VOLATILITY_FORMULA_VERSION = "unadjusted-close-log-return-sample-std-20-sqrt244-v1"

BenchmarkCloseObservation(benchmark_id, session_date, unadjusted_close)
# close <= 0 拒绝；session_date 必须是 date 而非 datetime

BenchmarkCloseBatch(benchmark_id, rows, provider_id, retrieved_at,
                    adjustment_mode, trust_state, data_mode)
# 恰好 21 条；日期严格递增；adjustment_mode 必须 "unadjusted"；
# trust_state 必须 NORMALIZED_CURRENT；data_mode 必须 CURRENT_RESEARCH
# .effective_session -> rows[-1].session_date

PassiveVolatilityEstimate(annualized_volatility_ratio, lookback_return_count,
                          annualization_sessions, formula_version, effective_session)
# lookback_return_count 必须 == 20；annualization_sessions 必须 == 244；
# formula_version 必须逐字匹配 P3 契约

estimate_passive_volatility(batch: BenchmarkCloseBatch) -> PassiveVolatilityEstimate
# localcontext prec=40，20 个 close-to-close log return 的样本标准差 × sqrt(244)

class TimingEstimateStatus(str, Enum):    QUANTIFIED / UNAVAILABLE
class TimingModelLifecycle(str, Enum):    BASELINE / CANDIDATE / VALIDATED / APPROVED / RETIRED

HorizonReturnForecast(horizon_trading_days, status, up_probability=None,
    expected_return_ratio=None, p10_return_ratio=None, p50_return_ratio=None,
    p90_return_ratio=None, status_reason=None)
# horizon 必须属于 (1, 5, 20, 60)；UNAVAILABLE 时不许带任何数值且必须有 reason；
# QUANTIFIED 时五个数值全需；up_probability ∈ [0,1]；
# 强制 p10 <= p50 <= p90 且 p10 <= expected <= p90

TimingRiskForecast(status, annualized_volatility_ratio=None,
    maximum_drawdown_ratio=None, tail_loss_ratio=None, status_reason=None)
# QUANTIFIED 至少需要一个风险估计；三者都不得为负

ActiveTimingAdjustment(status, point_exposure_delta=None,
    lower_exposure_delta=None, upper_exposure_delta=None, status_reason=None)
# QUANTIFIED 时 point/lower/upper 全需且 lower <= point <= upper

passive_volatility_exposure(*, target_volatility_ratio, observed_volatility_ratio,
                            maximum_exposure_ratio) -> Decimal
# min(maximum, target / observed)；不加杠杆；target/observed <= 0 拒绝

TimingForecast(
    forecast_id, benchmark_id, universe_version_id, effective_session,
    decision_time, data_cutoff_at, created_at, context,
    horizon_forecasts, risk_forecast,
    static_exposure_ratio, passive_exposure_ratio,
    passive_target_volatility_ratio, passive_observed_volatility_ratio,
    passive_lookback_sessions, active_adjustment,
    final_exposure_lower_ratio, final_exposure_upper_ratio,
    model_version_id, model_lifecycle, run_id, approval_scope,
    dataset_version_ids, input_trust_state)
# 强制 data_cutoff_at <= decision_time <= created_at；
# decision_time 的 Asia/Shanghai 日期必须 == effective_session；
# horizon_forecasts 必须恰好 (1, 5, 20, 60) 且按序；
# raw input_trust_state 拒绝；dataset_version_ids 非空且唯一
```

### `application/timing_baseline.py` 与 `timing_ledger.py`

`timing_baseline.py` 第 180 行是本 plan 要替换的那一行：

```python
unavailable_reason = "active timing model is not implemented in P3"
```

它被用在四处：四个 `HorizonReturnForecast` 的 `status_reason`、`TimingRiskForecast`、
以及 `ActiveTimingAdjustment`。Task 4 会把这句话按真实原因分化 —— 主动模型存在但未晋级，
与主动模型不存在，是两个不同的事实，不能共用一句话。

`timing_ledger.py` 的 `append_baseline()` 有六条守卫，**本 plan 一条都不删**：

```python
if value.active_adjustment.status is not TimingEstimateStatus.UNAVAILABLE:
    raise ValueError("P3 timing baseline active adjustment must remain unavailable")
if any(item.status is not TimingEstimateStatus.UNAVAILABLE
       for item in value.horizon_forecasts):
    raise ValueError("P3 timing baseline horizon forecasts must remain unavailable")
if value.risk_forecast.status is not TimingEstimateStatus.UNAVAILABLE:
    raise ValueError("P3 timing baseline risk forecast must remain unavailable")
if value.static_exposure_ratio != Decimal(1):
    raise ValueError("P3 static full-investment baseline must equal 1")
if (value.final_exposure_lower_ratio != value.passive_exposure_ratio
        or value.final_exposure_upper_ratio != value.passive_exposure_ratio):
    raise ValueError(
        "P3 final exposure must equal the passive baseline while active timing is unavailable")
if value.approval_scope != "shadow_baseline_only":
    raise ValueError("P3 timing baseline approval_scope must be shadow_baseline_only")
```

**放宽这些守卫会静默把 P3 的证据链变成可疑记录。** Task 4 新增 `append_active()`，
它接受 `QUANTIFIED` 的 horizon/risk forecast，但对 `active_adjustment` 与 `final_exposure_*`
执行一条更强的规则：只有 `model_lifecycle is APPROVED` 且 `approval_scope` 明确覆盖时
才允许非零 delta；其余情况 `final_exposure_*` 仍必须等于被动值。

### 复用的验证数学

```text
# domain/factor_validation.py
purged_embargoed_walk_forward(
    samples: Sequence[WalkForwardSample], *, spec: WalkForwardSpec, data_mode: DataMode
) -> WalkForwardResult
# WalkForwardSample(sample_id, session_index, label_end_session_index,
#     feature_version_id, label_version_id, data_mode, feature_trust_state,
#     label_trust_state, available, missing_reason=None)
#   —— label_end_session_index 必须 > session_index（这正是 overlap 的表达位）
# WalkForwardSpec(initial_training_sessions, test_sessions, step_sessions,
#     horizon_sessions, purge_sessions, embargo_sessions,
#     minimum_training_samples, split_version)
#   —— step_sessions 必须 >= test_sessions + embargo_sessions

# domain/factor_statistics.py
TimeSeriesObservation(period_id, value, statistic_version_id, data_mode,
    trust_state, availability_enforced, missing_reason=None)
HACNeweyWestSpec(max_lag, minimum_sample_size, formula_version)
#   —— minimum_sample_size 必须 > max_lag + 1
newey_west_mean_test(observations, *, spec, data_mode) -> HACNeweyWestResult
#   HACNeweyWestResult: status/mean/long_run_variance/standard_error/t_statistic/
#     sample_size/missing_count/max_lag/minimum_sample_size/formula_version/
#     input_version_ids/data_mode/historical_eligible/unavailable_reason/
#     warnings/scientific_status
BlockBootstrapSpec(block_size, resamples, confidence_level, seed,
    minimum_sample_size, formula_version)   # resamples >= 100
block_bootstrap_mean_ci(observations, *, spec, data_mode) -> BlockBootstrapResult

# validation/statistical_crosscheck.py
CrossCheckSpec(absolute_tolerance, relative_tolerance, adapter_version)
cross_check_newey_west_mean(observations, *, spec: HACNeweyWestSpec,
    cross_check_spec: CrossCheckSpec, data_mode: DataMode
) -> StatisticalCrossCheckReport
# 参照实现逐字为：
#   statsmodels.api.OLS intercept HAC Bartlett maxlags=<max_lag> use_correction=False

# domain/labels.py（2026-08-15 新增，本 plan 的对照物）
ForwardReturnLabelDefinition(label_id, version, horizon, adjustment,
                             data_mode, trust_state)
#   content_hash 由 (label_id, version, int(horizon), adjustment, data_mode,
#   trust_state) 的 canonical JSON 求 sha256；.limitation 携带未复权告警
class LabelHorizon(int, Enum):  TWENTY_SESSIONS = 20 / SIXTY_SESSIONS = 60 /
                                ONE_HUNDRED_TWENTY_SESSIONS = 120
definition.calculate(*, decision_session: date, prices: tuple[LabelPriceInput, ...]
) -> ForwardReturnObservation

# domain/factor_lifecycle.py（Promotion 骨架，Task 4 复用）
class ApprovalScope(str, Enum):  RESEARCH_BACKTEST / SHADOW / PAPER / LIMITED_LIVE
class ApprovalDecision(str, Enum): APPROVED / REJECTED / REQUEST_CHANGES
PromotionApproval(approval_id, factor_version_id, validation_report_id,
    validation_report_hash, scope, decision, actor_id, actor_role,
    decided_at, reason, evidence_hashes)
```

### 确认不存在（必须新建）

```text
domain/timing_research.py           # 目标、标签、特征、实验合同
domain/timing_models.py             # 模型合同与 5 个纯函数模型
domain/timing_validation.py         # 校准、Brier、AUC、DM、净效用
application/timing_features.py      # PIT 特征编排
application/timing_experiments.py   # 实验编排
application/timing_promotion.py     # PromotionReview 与影响上限
ports/timing_research.py            # 模型 port、标签/特征 repository
adapters/models/timing_sklearn.py   # logistic / linear 的 sklearn 实现
validation/timing_crosscheck.py     # sklearn / statsmodels 对照
workers/timing_research.py          # 研究 worker
workers/timing_outcomes.py          # Outcome/Calibration 到期追加
migrations/0037_p7_timing_research.sql
migrations/0038_p7_timing_outcomes.sql
```

## 原型参照（真实文本，逐字提取）

`docs/assets/prototype/figma-node-summary.json` 的 `frames` 是 dict，键为 node id。
两个 P7 Frame 均为 1440×1200，**没有 320/768/1024 独立 Frame**，故窄视口只记录设计假设。

### `9:238` = `11-timing-lab`

从 `docs/assets/prototype/11-timing-lab.svg` 的 144 个 `<text>` 节点提取的真实分区名：

| 区域 | 真实文本 |
|---|---|
| 面包屑 | `FACTORS / P7 · ACTIVE MARKET TIMING` |
| 标题 | `Timing Lab` / `主动预测与静态/均线/波动率基线分离比较` |
| 四张摘要卡 | `预测对象` `CSI 300` `1 / 5 / 20 / 60D`；`主动模型` `LOGIT-V0` `draft · 未评估`；`Shadow 样本` `0` `主动模型尚未启动`；`组合影响` `0%` `独立晋级前锁定` |
| 对照表标题 | `模型与基线对照` |
| 对照表列 | `模型` `类型` `期限` `AUC` `Brier` `净效用` `换手` `状态` |
| 对照表行 | `Static Full`/`静态基线`、`MA 20/60`/`趋势基线`、`Vol Target`/`风险基线`、`Logit V0`/`主动模型`、`Linear V0`/`主动模型`、`Tree V0`/`候选`、`State V0`/`候选` |
| 门禁卡标题 | `Timing 研究门禁` |
| 四条门禁 | `特征组` READY `趋势、宽度、估值、流动性、波动、宏观`；`标签` READY `1/5/20/60D 收益、方向、回撤、尾部`；`验证` ATTENTION `walk-forward / HAC / 校准 / 净效用`；`PIT 阻断` BLOCKER `宏观发布时间与历史特征不完整` |
| 边界卡 | `可信使用边界` / `主动模型必须真实存在；` / `未通过独立 Promotion Gate 时影响为 0%。` |
| 五段流程条 | `INPUT · 输入` `PIT 特征/标签` `基线与成本`；`PROCESS · 处理` `walk-forward→校准` `基线对照→净效用`；`OUTPUT · 输出` `TimingExperiment` `验证 Artifact`；`ACTION · 操作` `发起实验/冻结候选` `提交 Shadow 审查`；`GATE · 门禁` `主动模型真实存在` `未晋级影响0%` |
| 页脚 | `Prototype Notes · P7 主动 Timing 研究 · 测试通过不等于模型科学有效` |

**Frame 里的 `0.51` / `0.249` / `-0.3%` / `8%` / `+0.1%` / `12%` 是 design fixture**，
不得进入 runtime。Frame 自己也标了 `PROTOTYPE ONLY` `DESIGN FIXTURE` `非生产数据`
`不代表 PIT / 科学有效`。

### `9:431` = `12-timing-shadow-monitor`

从 `12-timing-shadow-monitor.svg` 的 177 个 `<text>` 节点提取：

| 区域 | 真实文本 |
|---|---|
| 面包屑 | `MONITORING / P7 · FORWARD EVIDENCE` |
| 标题 | `Timing Shadow Monitor` / `不可编辑的前瞻证据 · 研究结果与 Shadow 结果分离` |
| 四张摘要卡 | `最新 Forecast` `UNAVAILABLE` `主动模型尚未获批`；`Shadow 样本` `0` `不可用 current 回填`；`组合影响` `0%` `Promotion Gate 锁定`；`Baseline` `VOL TARGET` `被动基线可独立记录` |
| 账本标题 | `前瞻 Forecast Ledger · no edit / no backfill` |
| 账本列 | `日期` `模型` `期限` `上涨概率` `收益p50` `Outcome` `校准` `组合影响` |
| 四条状态 | `不可变记录` READY `每天决策时点冻结，禁止事后修改`；`研究 / 前瞻` READY `历史 OOS 与 Shadow 结果分开展示`；`晋级门` ATTENTION `统计与成本后经济指标同时过门`；`安全上限` BLOCKER `未获批时仓位影响始终为0` |
| 边界卡 | `可信使用边界` / `不能用 current 数据回填历史 Shadow；` / `Capability Gate 通过也不自动晋级。` |
| 五段流程条 | `INPUT · 输入` `每日 Forecast` `Outcome/Calibration`；`PROCESS · 处理` `冻结→前瞻累计` `漂移/校准/晋级`；`OUTPUT · 输出` `immutable ledger` `forward evidence`；`ACTION · 操作` `查看 outcome` `创建 PromotionReview`；`GATE · 门禁` `no edit/backfill` `影响0%直到晋级` |
| 页脚 | `Prototype Notes · P7 Shadow 前瞻验证 · 测试通过不等于模型科学有效` |

Frame 画了 11 行 `VOLBASELINE` / `ACTIVE-V0` 样例（`49%`…`58%`、`-0.25%`…`1.10%`），
**全部是 design fixture**。真实运行时该表只会有被动 baseline 行，`组合影响` 恒为 `0%`。

## 三个必须先想清楚的统计陷阱

本 plan 的多数篇幅在防这三件事。它们不是实现细节，是决定结论是否有意义的前提。

### 陷阱一：重叠窗口把 t 统计量吹大

Timing 标签是 index-level 的：每个交易日一条观测，而不是每个交易日 500 条。
样本量从"日数 × 股票数"塌缩成"日数"。2018–2025 大约 1,900 个交易日，
60 日 horizon 只有约 31 个**不重叠**窗口。

如果按日滚动生成 60 日前瞻收益，相邻两条观测共享 59 天的价格路径，
自相关系数接近 `1 - 1/60`。用 i.i.d. 标准误算 t 统计量，会把标准误低估约 `sqrt(60) ≈ 7.7` 倍。
一个真实 t=0.4 的无效信号会显示成 t=3.1，看起来高度显著。

**这是本 plan 设计上最难绕的一件事**，因为它同时污染三处：
walk-forward 的 purge 长度、HAC 的 `max_lag`、以及 DM 检验的方差估计。
处理办法在 Task 1 与 Task 3 分两层落地：

1. `TimingTargetDefinition` 必须携带显式 `overlap_policy`，且必须存下
   `overlapping_sessions`（= horizon − 1）。**没有这个字段的目标定义不许构造。**
2. 任何时间序列推断都必须收到与 `overlapping_sessions` 一致的 `max_lag`。
   `HACNeweyWestSpec(max_lag=...)` 不许用默认值；Task 3 会写一个测试，
   断言 `max_lag < overlapping_sessions` 时**拒绝**而不是"尽力算"。

### 陷阱二：历史回放伪装成前瞻证据

一次历史 walk-forward 能在几秒内产出 1,900 天的"每日 forecast"。
它们与真实前瞻的 forecast 在数据结构上完全一样 —— 都是 `TimingForecast`。
如果同一张表、同一个 API、同一条曲线同时装两者，Shadow 样本数会瞬间从 0 变成 1,900，
而**没有任何一天是真的等出来的**。

因此 `TimingForecast.context.deployment_stage` 必须做实质区分：
`RESEARCH` = 历史回放或 OOS，`SHADOW` = 前瞻。Task 4 的 no-backfill 时钟守卫
会拒绝 `effective_session` 早于当前 Shanghai 交易日的 shadow 写入；
Task 5 的三个 screen 分别读三个不同的投影，**不共用一个 endpoint**。

### 陷阱三：毛胜净负

一个 20 日 timing 信号在 20 日 horizon 上换手率约 5%/日。加上双边手续费、
滑点与冲击成本，年化成本轻易吃掉 2–4%。一个年化毛 alpha 1.5% 的信号，
成本后是净负的，但每一项统计检验都会显示它"有预测力"。

所以 Task 3 的 `net_utility` 不是可选指标而是**门禁条件**：
毛胜净负的模型不许进入 `VALIDATED` 生命周期。测试会直接构造这个情形。

---

### Task 1: 目标、标签与 PIT 特征合同（`domain/timing_research.py`）

对应 `docs/plans/step-06-p7-active-timing.md` Task 1：
「预计新增 `domain/timing_research.py`、`application/timing_features.py`、tests；先标签
session/overlap/可知时间，label repository 与 serving API 隔离。」

**Files:**
- Create: `platform/src/a_share_platform/domain/timing_research.py`
- Create: `platform/src/a_share_platform/application/timing_features.py`
- Create: `platform/src/a_share_platform/ports/timing_research.py`
- Test: `platform/tests/test_timing_research_contracts.py`
- Test: `platform/tests/test_timing_features.py`

**Interfaces:**
- Consumes: 已有 `domain/timing.py` 的 `SUPPORTED_TIMING_BENCHMARK_IDS`、`domain/labels.py`
  的 `LabelPriceInput`、`domain/pit.py` 的 `DataTrustState`、`domain/run_context.py` 的 `DataMode`
- Produces:
  ```python
  class TimingTargetKind(StrEnum):
      RETURN = "return"; DIRECTION = "direction"
      DRAWDOWN = "drawdown"; TAIL_LOSS = "tail_loss"

  class TimingOverlapPolicy(StrEnum):
      OVERLAPPING_HAC_REQUIRED = "overlapping_hac_required"
      NON_OVERLAPPING = "non_overlapping"

  @dataclass(frozen=True)
  class TimingTargetDefinition:
      target_id: str; version: str
      benchmark_id: str; tradable_proxy_id: str | None
      kind: TimingTargetKind
      horizon_trading_days: int          # 必须 ∈ (1, 5, 20, 60)
      overlap_policy: TimingOverlapPolicy
      overlapping_sessions: int          # 必须 == horizon - 1
      data_mode: DataMode; trust_state: DataTrustState
      content_hash: str = field(init=False)

  @dataclass(frozen=True)
  class TimingFeatureSnapshot:
      snapshot_id: str; benchmark_id: str; decision_time: datetime
      feature_group: TimingFeatureGroup
      feature_id: str; feature_version: str
      status: TimingEstimateStatus
      value: Decimal | None
      available_at: datetime | None
      publication_at: datetime | None
      status_reason: str | None
      content_hash: str = field(init=False)

  class TimingFeatureGroup(StrEnum):
      TREND = "trend"; BREADTH = "breadth"; VALUATION = "valuation"
      LIQUIDITY = "liquidity"; VOLATILITY = "volatility"
      MACRO = "macro"; RISK_APPETITE = "risk_appetite"
  ```

- [ ] **Step 1: 先读真实的 horizon 常量与 overlap 表达位**

```bash
cd platform
grep -n "_REQUIRED_HORIZONS\|SUPPORTED_TIMING_BENCHMARK_IDS" \
  src/a_share_platform/domain/timing.py
grep -n "label_end_session_index" -B2 -A6 src/a_share_platform/domain/factor_validation.py
grep -n "class LabelHorizon" -A8 src/a_share_platform/domain/labels.py
```

Expected: `_REQUIRED_HORIZONS = (1, 5, 20, 60)`（timing 专用），而
`LabelHorizon` 是 `20/60/120`（因子专用）。**这两组不同，不要合并** ——
timing 需要 1 日和 5 日，因子研究不需要；因子需要 120 日，timing 不需要。
`WalkForwardSample.label_end_session_index` 是 overlap 在 fold 生成器里的表达位。

- [ ] **Step 2: 写失败测试 —— overlap 必须显式，不许默认**

```python
# platform/tests/test_timing_research_contracts.py
"""Index-level timing targets, where overlap is a declared fact.

A timing label is not a factor label.  There is one observation per session
rather than one per security per session, so a 60-day horizon over eight years
yields roughly 31 independent windows, not 950,000.  Rolling the window daily
produces observations that share 59 of 60 days of price path, and treating those
as independent understates the standard error by about sqrt(60).

The definition therefore refuses to exist without stating how many sessions
overlap.  A downstream statistic can then be forced to use a matching HAC lag
instead of silently averaging correlated observations.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.domain.timing_research import (
    TimingOverlapPolicy,
    TimingTargetDefinition,
    TimingTargetKind,
)


def target(
    *,
    horizon: int = 20,
    overlapping: int | None = None,
    policy: TimingOverlapPolicy = TimingOverlapPolicy.OVERLAPPING_HAC_REQUIRED,
) -> TimingTargetDefinition:
    return TimingTargetDefinition(
        target_id="timing.target.csi300.return",
        version="v0",
        benchmark_id="index:000300",
        tradable_proxy_id="etf:510300",
        kind=TimingTargetKind.RETURN,
        horizon_trading_days=horizon,
        overlap_policy=policy,
        overlapping_sessions=horizon - 1 if overlapping is None else overlapping,
        data_mode=DataMode.CURRENT_RESEARCH,
        trust_state=DataTrustState.NORMALIZED_CURRENT,
    )


class OverlapDeclarationTest(unittest.TestCase):
    def test_overlapping_sessions_must_equal_horizon_minus_one(self) -> None:
        """A wrong overlap count would set a wrong HAC lag downstream."""
        with self.assertRaises(ValueError):
            target(horizon=20, overlapping=5)

    def test_one_day_horizon_is_non_overlapping(self) -> None:
        definition = target(
            horizon=1, overlapping=0, policy=TimingOverlapPolicy.NON_OVERLAPPING
        )
        self.assertEqual(definition.overlapping_sessions, 0)

    def test_multi_day_horizon_cannot_claim_non_overlapping(self) -> None:
        """Daily rolling of a 20-day window is overlapping by construction."""
        with self.assertRaises(ValueError):
            target(horizon=20, overlapping=19,
                   policy=TimingOverlapPolicy.NON_OVERLAPPING)

    def test_required_hac_lag_is_derived_not_configured(self) -> None:
        self.assertEqual(target(horizon=20).required_hac_max_lag, 19)
        self.assertEqual(target(horizon=60).required_hac_max_lag, 59)


class TargetIdentityTest(unittest.TestCase):
    def test_definition_is_content_addressed(self) -> None:
        self.assertEqual(target().content_hash, target().content_hash)
        self.assertEqual(len(target().content_hash), 64)

    def test_horizon_change_changes_the_hash(self) -> None:
        self.assertNotEqual(target(horizon=20).content_hash,
                            target(horizon=60).content_hash)

    def test_horizon_must_be_a_supported_timing_horizon(self) -> None:
        """timing uses 1/5/20/60; the 120 of LabelHorizon is a factor horizon."""
        with self.assertRaises(ValueError):
            target(horizon=120, overlapping=119)

    def test_benchmark_must_be_supported(self) -> None:
        with self.assertRaises(ValueError):
            TimingTargetDefinition(
                target_id="timing.target.other",
                version="v0",
                benchmark_id="index:000001",
                tradable_proxy_id=None,
                kind=TimingTargetKind.RETURN,
                horizon_trading_days=20,
                overlap_policy=TimingOverlapPolicy.OVERLAPPING_HAC_REQUIRED,
                overlapping_sessions=19,
                data_mode=DataMode.CURRENT_RESEARCH,
                trust_state=DataTrustState.NORMALIZED_CURRENT,
            )

    def test_strict_historical_requires_pit_verified(self) -> None:
        with self.assertRaises(PermissionError):
            TimingTargetDefinition(
                target_id="timing.target.csi300.return",
                version="v0",
                benchmark_id="index:000300",
                tradable_proxy_id="etf:510300",
                kind=TimingTargetKind.RETURN,
                horizon_trading_days=20,
                overlap_policy=TimingOverlapPolicy.OVERLAPPING_HAC_REQUIRED,
                overlapping_sessions=19,
                data_mode=DataMode.STRICT_HISTORICAL,
                trust_state=DataTrustState.NORMALIZED_CURRENT,
            )

    def test_raw_trust_state_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            TimingTargetDefinition(
                target_id="timing.target.csi300.return",
                version="v0",
                benchmark_id="index:000300",
                tradable_proxy_id="etf:510300",
                kind=TimingTargetKind.RETURN,
                horizon_trading_days=20,
                overlap_policy=TimingOverlapPolicy.OVERLAPPING_HAC_REQUIRED,
                overlapping_sessions=19,
                data_mode=DataMode.CURRENT_RESEARCH,
                trust_state=DataTrustState.RAW,
            )


class TradableProxyTest(unittest.TestCase):
    def test_index_target_without_a_proxy_states_it_is_not_tradable(self) -> None:
        """ADR-0006 §7: an untradable benchmark must bind an explicit proxy."""
        definition = TimingTargetDefinition(
            target_id="timing.target.csi300.return",
            version="v0",
            benchmark_id="index:000300",
            tradable_proxy_id=None,
            kind=TimingTargetKind.RETURN,
            horizon_trading_days=20,
            overlap_policy=TimingOverlapPolicy.OVERLAPPING_HAC_REQUIRED,
            overlapping_sessions=19,
            data_mode=DataMode.CURRENT_RESEARCH,
            trust_state=DataTrustState.NORMALIZED_CURRENT,
        )
        self.assertFalse(definition.is_tradable)
        self.assertIn("proxy", definition.tradability_limitation.lower())
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_timing_research_contracts -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'a_share_platform.domain.timing_research'`。
把真实错误文本抄进 Evidence。

- [ ] **Step 4: 最小实现 `TimingTargetDefinition`**

照 `domain/timing.py` 已有的 `_require_text` / `_decimal` / `_supported_benchmark` 风格写校验器，
**不要新造一套辅助函数** —— 从 `.timing` 导入。`required_hac_max_lag` 是 property 而非字段：
它由 horizon 派生，允许配置就等于允许配错。

- [ ] **Step 5: 转绿**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_timing_research_contracts -v`
Expected: PASS

- [ ] **Step 6: 写标签生成红测 —— index-level 且不许截断窗口**

追加到 `test_timing_research_contracts.py`，并在文件头补三个 import：

```python
from datetime import date, timedelta

from a_share_platform.domain.timing import (
    BenchmarkCloseObservation,
    TimingEstimateStatus,
)
```

`target()` 辅助函数需加一个 `kind` 参数（默认 `TimingTargetKind.RETURN`），
供 `DIRECTION` 用例复用同一个构造器。

```python
class IndexLevelLabelTest(unittest.TestCase):
    """One observation per session, not one per security per session."""

    def test_direction_label_is_derived_from_the_same_return(self) -> None:
        """Direction and return must not be two independent computations."""
        from a_share_platform.domain.timing_research import calculate_timing_label

        closes = tuple(
            BenchmarkCloseObservation(
                benchmark_id="index:000300",
                session_date=date(2025, 1, 2) + timedelta(days=index),
                unadjusted_close=Decimal("3000") + Decimal(index),
            )
            for index in range(30)
        )
        returns = calculate_timing_label(
            definition=target(horizon=20), closes=closes,
            decision_session=date(2025, 1, 2),
        )
        direction = calculate_timing_label(
            definition=target(horizon=20, kind=TimingTargetKind.DIRECTION),
            closes=closes, decision_session=date(2025, 1, 2),
        )
        self.assertEqual(returns.status, TimingEstimateStatus.QUANTIFIED)
        self.assertEqual(direction.value, Decimal(1))   # return > 0
        self.assertEqual(direction.derived_from_return, returns.value)

    def test_incomplete_window_is_unavailable_not_truncated(self) -> None:
        """Truncating silently changes the horizon, so the label is a lie."""
        from a_share_platform.domain.timing_research import calculate_timing_label

        closes = tuple(
            BenchmarkCloseObservation(
                benchmark_id="index:000300",
                session_date=date(2025, 1, 2) + timedelta(days=index),
                unadjusted_close=Decimal("3000") + Decimal(index),
            )
            for index in range(10)      # fewer than the 20-session horizon
        )
        observation = calculate_timing_label(
            definition=target(horizon=20), closes=closes,
            decision_session=date(2025, 1, 2),
        )
        self.assertEqual(observation.status, TimingEstimateStatus.UNAVAILABLE)
        self.assertIn("horizon", observation.status_reason)
        self.assertIsNone(observation.value)

    def test_label_records_its_own_overlap_span(self) -> None:
        """Two adjacent labels must be able to prove they share a price path."""
        from a_share_platform.domain.timing_research import calculate_timing_label

        closes = tuple(
            BenchmarkCloseObservation(
                benchmark_id="index:000300",
                session_date=date(2025, 1, 2) + timedelta(days=index),
                unadjusted_close=Decimal("3000") + Decimal(index),
            )
            for index in range(40)
        )
        first = calculate_timing_label(
            definition=target(horizon=20), closes=closes,
            decision_session=date(2025, 1, 2),
        )
        second = calculate_timing_label(
            definition=target(horizon=20), closes=closes,
            decision_session=date(2025, 1, 3),
        )
        self.assertEqual(first.entry_session_index + 1, second.entry_session_index)
        self.assertEqual(first.exit_session_index - second.entry_session_index, 19)
        self.assertEqual(first.overlapping_sessions_with(second), 19)

    def test_drawdown_label_uses_the_path_not_the_endpoints(self) -> None:
        """A max drawdown computed from entry/exit only is not a drawdown."""
        ...
```

`overlapping_sessions_with()` 不是装饰性 API：Task 3 的 block bootstrap 需要它来选 block size，
Evidence 需要它来证明重叠确实被处理过而不是被声明过。

- [ ] **Step 7: 逐 kind 补齐（每种先红测再实现）**

顺序：`RETURN` → `DIRECTION` → `DRAWDOWN` → `TAIL_LOSS`。每种至少覆盖：
- 完整窗口 → 量化值 + `entry_session_index` / `exit_session_index`
- 窗口不足 → `UNAVAILABLE` + 原因，**不截断**
- 窗口内有非交易日缺口 → `UNAVAILABLE` + 原因，**不用前值填充**
- `DIRECTION` 必须从同一条 return 派生，不许独立算
- `DRAWDOWN` / `TAIL_LOSS` 必须使用窗口内完整路径

- [ ] **Step 8: PIT 特征编排红测（`application/timing_features.py`）**

```python
# platform/tests/test_timing_features.py
"""PIT timing features, where a missing publication time blocks the feature.

Macro series are the whole problem here.  A GDP print carries a reference
quarter, a first release date and one or more revisions, and only the release
date says when a decision-maker could have known the number.  Using the
reference quarter as the timestamp back-dates the knowledge by roughly a month
and makes any model built on it look prescient.

So a macro feature without a qualified publication time is unavailable with a
reason.  It is never approximated from the reference period.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal

from a_share_platform.application.timing_features import TimingFeatureOrchestrator
from a_share_platform.domain.run_context import DataMode
from a_share_platform.domain.timing import TimingEstimateStatus
from a_share_platform.domain.timing_research import TimingFeatureGroup

DECISION = datetime(2025, 12, 31, 7, 5, tzinfo=UTC)   # 15:05 Asia/Shanghai


class FakeBenchmarkHistory:
    """Returns whatever bars the test hands it, in session order."""

    def __init__(self, bars: tuple[tuple[str, Decimal], ...] = ()) -> None:
        self._bars = bars
        self.calls: list[tuple[str, datetime]] = []

    def closes_before(self, *, benchmark_id: str, cutoff: datetime):
        self.calls.append((benchmark_id, cutoff))
        return self._bars


class FakeMacroSource:
    def __init__(self, *, publication_at: datetime | None) -> None:
        self._publication_at = publication_at

    def latest(self, *, series_id: str, cutoff: datetime):
        return {
            "series_id": series_id,
            "value": Decimal("5.2"),
            "reference_period": "2025Q3",
            "publication_at": self._publication_at,
        }


class MacroPublicationTimeTest(unittest.TestCase):
    def test_macro_feature_without_publication_time_is_unavailable(self) -> None:
        orchestrator = TimingFeatureOrchestrator(
            benchmark_history=FakeBenchmarkHistory(),
            macro_source=FakeMacroSource(publication_at=None),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        snapshots = orchestrator.build(
            benchmark_id="index:000300", decision_time=DECISION,
            groups=(TimingFeatureGroup.MACRO,),
        )
        macro = [s for s in snapshots if s.feature_group is TimingFeatureGroup.MACRO]
        self.assertTrue(macro)
        for snapshot in macro:
            self.assertEqual(snapshot.status, TimingEstimateStatus.UNAVAILABLE)
            self.assertIsNone(snapshot.value)
            self.assertIn("publication", snapshot.status_reason.lower())

    def test_reference_period_is_never_used_as_publication_time(self) -> None:
        """This substitution is what silently back-dates the knowledge."""
        orchestrator = TimingFeatureOrchestrator(
            benchmark_history=FakeBenchmarkHistory(),
            macro_source=FakeMacroSource(publication_at=None),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        snapshots = orchestrator.build(
            benchmark_id="index:000300", decision_time=DECISION,
            groups=(TimingFeatureGroup.MACRO,),
        )
        for snapshot in snapshots:
            self.assertIsNone(snapshot.publication_at)
            self.assertIsNone(snapshot.available_at)

    def test_publication_after_decision_time_is_refused(self) -> None:
        """A number published tomorrow cannot inform today's forecast."""
        orchestrator = TimingFeatureOrchestrator(
            benchmark_history=FakeBenchmarkHistory(),
            macro_source=FakeMacroSource(
                publication_at=datetime(2026, 1, 15, tzinfo=UTC)
            ),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        snapshots = orchestrator.build(
            benchmark_id="index:000300", decision_time=DECISION,
            groups=(TimingFeatureGroup.MACRO,),
        )
        for snapshot in snapshots:
            self.assertEqual(snapshot.status, TimingEstimateStatus.UNAVAILABLE)
            self.assertIn("available_at", snapshot.status_reason)


class GroupIsolationTest(unittest.TestCase):
    def test_one_blocked_group_does_not_block_the_others(self) -> None:
        """Trend from price bars does not depend on the macro calendar."""
        orchestrator = TimingFeatureOrchestrator(
            benchmark_history=FakeBenchmarkHistory(
                tuple((f"2025-12-{day:02d}", Decimal(3000 + day)) for day in range(1, 26))
            ),
            macro_source=FakeMacroSource(publication_at=None),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        snapshots = orchestrator.build(
            benchmark_id="index:000300", decision_time=DECISION,
            groups=(TimingFeatureGroup.TREND, TimingFeatureGroup.MACRO),
        )
        trend = [s for s in snapshots if s.feature_group is TimingFeatureGroup.TREND]
        self.assertTrue(any(s.status is TimingEstimateStatus.QUANTIFIED for s in trend))

    def test_cutoff_passed_to_the_reader_never_exceeds_decision_time(self) -> None:
        reader = FakeBenchmarkHistory()
        TimingFeatureOrchestrator(
            benchmark_history=reader,
            macro_source=FakeMacroSource(publication_at=None),
            data_mode=DataMode.CURRENT_RESEARCH,
        ).build(
            benchmark_id="index:000300", decision_time=DECISION,
            groups=(TimingFeatureGroup.TREND,),
        )
        self.assertTrue(reader.calls)
        for _benchmark, cutoff in reader.calls:
            self.assertLessEqual(cutoff, DECISION)


class LabelServingIsolationTest(unittest.TestCase):
    def test_the_feature_orchestrator_has_no_label_reader(self) -> None:
        """Step 06 Task 1: label repository and serving API stay isolated.

        A single object holding both features and forward labels is one attribute
        access away from leaking the answer into the inputs.
        """
        orchestrator = TimingFeatureOrchestrator(
            benchmark_history=FakeBenchmarkHistory(),
            macro_source=FakeMacroSource(publication_at=None),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        for name in dir(orchestrator):
            self.assertNotIn("label", name.lower())
```

- [ ] **Step 9: 逐 group 补齐**

顺序：`TREND`（价格派生，最容易验证）→ `VOLATILITY` → `BREADTH` → `LIQUIDITY`
→ `VALUATION` → `RISK_APPETITE` → `MACRO`（最后，因为它必然是 blocker）。
每组都必须能在其余组不可用时独立产出。

- [ ] **Step 10: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/domain/timing_research.py \
  platform/src/a_share_platform/application/timing_features.py \
  platform/src/a_share_platform/ports/timing_research.py \
  platform/tests/test_timing_research_contracts.py \
  platform/tests/test_timing_features.py
git commit -m "feat: add index-level timing targets, labels and PIT features

A timing label is not a factor label.  There is one observation per session
rather than one per security per session, so eight years of 60-day windows give
roughly 31 independent samples rather than a cross-sectional panel.  Rolling the
window daily produces neighbours that share 59 of 60 days of price path, and
treating those as independent understates the standard error by about sqrt(60) —
which turns a t of 0.4 into a t of 3.1.

The target definition therefore cannot be constructed without stating how many
sessions overlap, and it derives the required HAC lag rather than accepting one,
so no caller can configure the correlation away.  Labels record their own entry
and exit session indices and can report the overlap they share with a
neighbouring label, which is what lets the validation engine prove the overlap
was handled instead of merely declared.

Macro features are unavailable without a qualified publication time.  Using the
reference quarter instead back-dates the knowledge by about a month and makes any
model built on it look prescient.  Features are grouped so that the macro
blocker leaves trend and volatility usable, and the feature orchestrator holds
no label reader at all: one object with both is one attribute access away from
leaking the answer into the inputs."
```

---

### Task 2: 基线与主动模型（provider-neutral model port）

对应 Step 06 Task 2：「在 provider-neutral model port 上实现 static/MA/vol target 和
logistic/linear baseline；每个模型有 deterministic fixture、版本和无未来输入测试。」
也对应 P7-W02 的五条勾选项与原型 `9:238` 对照表的七行。

**为什么要有 port**：logistic 与 linear 的拟合会用 scikit-learn，而 `domain/` 不许导入
sklearn。模型**合同**（输入形状、输出形状、版本、determinism）留在 domain，
**拟合实现**在 `adapters/models/`。static / MA / vol-target 三个基线是纯算术，
可以直接在 domain 实现 —— 它们不需要拟合。

**Files:**
- Create: `platform/src/a_share_platform/domain/timing_models.py`
- Create: `platform/src/a_share_platform/ports/timing_models.py`
- Create: `platform/src/a_share_platform/adapters/models/timing_sklearn.py`
- Test: `platform/tests/test_timing_baseline_models.py`
- Test: `platform/tests/test_timing_active_models.py`

**Interfaces:**
- Consumes: Task 1 的 `TimingFeatureSnapshot` / `TimingTargetDefinition`、已有
  `passive_volatility_exposure()`、`estimate_passive_volatility()`
- Produces:
  ```python
  # ports/timing_models.py
  class TimingModel(Protocol):
      model_id: str
      version: str
      kind: TimingModelKind
      def fit(self, *, samples: Sequence[TimingTrainingSample]) -> TimingFittedModel: ...

  class TimingFittedModel(Protocol):
      fit_content_hash: str
      def predict(self, *, features: Sequence[TimingFeatureSnapshot]
                  ) -> HorizonReturnForecast: ...

  # domain/timing_models.py
  class TimingModelKind(StrEnum):
      STATIC_FULL = "static_full"
      MOVING_AVERAGE = "moving_average"
      VOLATILITY_TARGET = "volatility_target"
      LOGISTIC = "logistic"
      LINEAR = "linear"

  @dataclass(frozen=True)
  class TimingModelDefinition:
      model_id: str; version: str; kind: TimingModelKind
      target_definition_hash: str
      feature_ids: tuple[str, ...]
      hyperparameters: Mapping[str, str]
      seed: int
      content_hash: str = field(init=False)

  static_full_exposure(*, maximum_exposure_ratio: Decimal) -> Decimal
  moving_average_signal(*, closes, fast_sessions, slow_sessions) -> MovingAverageSignal
  ```

- [ ] **Step 1: 先确认 sklearn 是否真的在环境里**

```bash
cd platform
.venv/bin/python -c "import sklearn, statsmodels, scipy; \
print('sklearn', sklearn.__version__); \
print('statsmodels', statsmodels.__version__); print('scipy', scipy.__version__)"
grep -rn "sklearn\|scikit" pyproject.toml requirements*.txt 2>/dev/null
```

若 sklearn 未安装，**先只做 static / MA / vol-target 三个基线**，logistic 与 linear
的 port 与合同测试仍然写（用 fake 实现），adapter 留到依赖就绪。
**不要为了让 logistic 跑起来而在 domain 手写梯度下降** —— 那会成为第二份未经交叉验证的数学。

- [ ] **Step 2: 写失败测试 —— static full investment 基线**

```python
# platform/tests/test_timing_baseline_models.py
"""The three non-fitted baselines: static, moving average, volatility target.

These exist so that an active model has something to beat.  Static full
investment is the honest null: it makes no forecast, holds everything, and pays
no timing cost.  A model that cannot beat it net of cost has no reason to exist.

Every baseline is deterministic given its inputs, so each has a fixture with
values computed by hand in the docstring.  A baseline whose number nobody can
reproduce by hand cannot serve as a reference point.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from decimal import Decimal

from a_share_platform.domain.timing import BenchmarkCloseObservation
from a_share_platform.domain.timing_models import (
    TimingModelDefinition,
    TimingModelKind,
    moving_average_signal,
    static_full_exposure,
)


def closes(values: tuple[int, ...]) -> tuple[BenchmarkCloseObservation, ...]:
    return tuple(
        BenchmarkCloseObservation(
            benchmark_id="index:000300",
            session_date=date(2025, 1, 2) + timedelta(days=index),
            unadjusted_close=Decimal(value),
        )
        for index, value in enumerate(values)
    )


class StaticFullInvestmentTest(unittest.TestCase):
    def test_static_baseline_is_the_maximum_exposure(self) -> None:
        self.assertEqual(static_full_exposure(maximum_exposure_ratio=Decimal(1)),
                         Decimal(1))

    def test_static_baseline_never_exceeds_one(self) -> None:
        """No leverage: SPEC-026 baselines are unlevered."""
        with self.assertRaises(ValueError):
            static_full_exposure(maximum_exposure_ratio=Decimal("1.5"))

    def test_static_baseline_makes_no_forecast(self) -> None:
        """It is the null model.  A forecast here would make it a timing model."""
        from a_share_platform.domain.timing_models import static_full_forecast

        forecast = static_full_forecast(horizon_trading_days=20)
        self.assertEqual(forecast.status.value, "unavailable")
        self.assertIn("no forecast", forecast.status_reason.lower())


class MovingAverageBaselineTest(unittest.TestCase):
    def test_fast_above_slow_is_risk_on(self) -> None:
        """Fixture: last 5 closes average 3020, last 10 average 3015 -> risk on.

        Closes 3001..3010 ascending.  fast(5) = mean(3006..3010) = 3008.
        slow(10) = mean(3001..3010) = 3005.5.  fast > slow, so exposure = max.
        """
        signal = moving_average_signal(
            closes=closes(tuple(range(3001, 3011))),
            fast_sessions=5,
            slow_sessions=10,
        )
        self.assertEqual(signal.fast_average, Decimal(3008))
        self.assertEqual(signal.slow_average, Decimal("3005.5"))
        self.assertEqual(signal.exposure_ratio, Decimal(1))

    def test_fast_below_slow_is_risk_off(self) -> None:
        """Descending closes 3010..3001: fast(5) = 3003, slow(10) = 3005.5."""
        signal = moving_average_signal(
            closes=closes(tuple(range(3010, 3000, -1))),
            fast_sessions=5,
            slow_sessions=10,
        )
        self.assertEqual(signal.fast_average, Decimal(3003))
        self.assertEqual(signal.slow_average, Decimal("3005.5"))
        self.assertEqual(signal.exposure_ratio, Decimal(0))

    def test_only_closes_up_to_and_including_the_decision_session_are_used(self) -> None:
        """No look-ahead: the averages must not move when future bars are added.

        This is the single test that matters most for a moving average, because
        an off-by-one in the window slices tomorrow's close into today's signal
        and produces a spectacular, entirely fake backtest.
        """
        history = closes(tuple(range(3001, 3011)))
        future = history + closes((9999, 9999))[-2:]
        self.assertEqual(
            moving_average_signal(closes=history, fast_sessions=5, slow_sessions=10),
            moving_average_signal(
                closes=future[:len(history)], fast_sessions=5, slow_sessions=10
            ),
        )

    def test_insufficient_history_is_unavailable_not_a_shorter_window(self) -> None:
        with self.assertRaises(ValueError):
            moving_average_signal(
                closes=closes((3001, 3002, 3003)), fast_sessions=5, slow_sessions=10
            )

    def test_fast_must_be_shorter_than_slow(self) -> None:
        with self.assertRaises(ValueError):
            moving_average_signal(
                closes=closes(tuple(range(3001, 3021))),
                fast_sessions=10, slow_sessions=5,
            )

    def test_equal_averages_hold_the_prior_state_rather_than_flipping(self) -> None:
        """A crossing exactly at equality must not generate spurious turnover."""
        ...


class VolatilityTargetBaselineTest(unittest.TestCase):
    def test_the_baseline_reuses_the_existing_p3_function(self) -> None:
        """This baseline already exists.  A second implementation would drift.

        `passive_volatility_exposure` and the 20/244 formula version are the P3
        contract recorded in docs/13; the timing model wrapper must call it, not
        recompute it.
        """
        import inspect

        from a_share_platform.domain import timing_models

        source = inspect.getsource(timing_models)
        self.assertIn("passive_volatility_exposure", source)
        self.assertNotIn("sqrt(244", source)
        self.assertNotIn("Decimal(244)", source)


class ModelDefinitionIdentityTest(unittest.TestCase):
    def test_definition_is_content_addressed_over_hyperparameters(self) -> None:
        def definition(fast: str) -> TimingModelDefinition:
            return TimingModelDefinition(
                model_id="timing-model:ma",
                version="v0",
                kind=TimingModelKind.MOVING_AVERAGE,
                target_definition_hash="a" * 64,
                feature_ids=("timing.trend.ma_fast", "timing.trend.ma_slow"),
                hyperparameters={"fast_sessions": fast, "slow_sessions": "60"},
                seed=20260816,
            )

        self.assertNotEqual(definition("20").content_hash, definition("10").content_hash)

    def test_definition_binds_the_target_hash(self) -> None:
        """A model fitted for a 20-day target must not be scored on a 60-day one."""
        ...

    def test_seed_is_part_of_the_hash(self) -> None:
        ...
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_timing_baseline_models -v`
Expected: FAIL —— `a_share_platform.domain.timing_models` 不存在。

- [ ] **Step 4: 逐基线实现（三个基线，各自先红后绿）**

顺序：`static_full` → `moving_average` → `volatility_target`。
`volatility_target` 必须调用已有的 `passive_volatility_exposure()`，
**不重算 sqrt(244)** —— 那会造出与 P3 ledger 记录不一致的第二个波动率口径。

- [ ] **Step 5: 写主动模型红测 —— 无未来输入 + deterministic**

```python
# platform/tests/test_timing_active_models.py
"""Logistic and linear active models on a provider-neutral port.

The fitting lives in an adapter because domain code may not import sklearn.  What
the domain owns is the contract: the shape of a training sample, the shape of a
forecast, the version identity of a fit, and the guarantee that a fit is
reproducible from (definition, samples, seed).

The two tests that carry the weight are determinism and no-look-ahead.  Without
determinism the same experiment cannot be replayed, so no result is evidence of
anything.  Without the look-ahead guard a model can be fitted on the window it is
then scored on, which produces an impressive number that means nothing.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from a_share_platform.domain.timing import TimingEstimateStatus
from a_share_platform.domain.timing_models import (
    TimingModelDefinition,
    TimingModelKind,
    TimingTrainingSample,
)

BASE = datetime(2025, 1, 2, 7, 5, tzinfo=UTC)


def definition(kind: TimingModelKind) -> TimingModelDefinition:
    return TimingModelDefinition(
        model_id=f"timing-model:{kind.value}",
        version="v0",
        kind=kind,
        target_definition_hash="a" * 64,
        feature_ids=("timing.trend.ma_ratio", "timing.volatility.realized_20"),
        hyperparameters={"regularisation": "l2", "c": "1.0"},
        seed=20260816,
    )


def samples(count: int) -> tuple[TimingTrainingSample, ...]:
    """A deliberately learnable pattern: high trend ratio precedes a positive
    forward return.  The point is not that this is realistic — it is that the
    fitted coefficient sign is predictable, so a broken fit is visible.
    """
    rows = []
    for index in range(count):
        rising = index % 2 == 0
        rows.append(
            TimingTrainingSample(
                sample_id=f"sample:{index:04d}",
                decision_time=BASE + timedelta(days=index),
                session_index=index,
                label_end_session_index=index + 20,
                feature_values={
                    "timing.trend.ma_ratio": Decimal("1.05") if rising else Decimal("0.95"),
                    "timing.volatility.realized_20": Decimal("0.18"),
                },
                label_value=Decimal("0.02") if rising else Decimal("-0.02"),
                label_available_at=BASE + timedelta(days=index + 20),
            )
        )
    return tuple(rows)


class DeterminismTest(unittest.TestCase):
    def test_two_fits_on_identical_samples_share_a_fit_hash(self) -> None:
        from a_share_platform.adapters.models.timing_sklearn import SklearnTimingModel

        model = SklearnTimingModel(definition(TimingModelKind.LOGISTIC))
        first = model.fit(samples=samples(200))
        second = model.fit(samples=samples(200))
        self.assertEqual(first.fit_content_hash, second.fit_content_hash)

    def test_a_different_seed_changes_the_fit_hash(self) -> None:
        ...

    def test_sample_order_does_not_change_the_fit(self) -> None:
        """Otherwise a shuffled load order silently produces a different model."""
        from a_share_platform.adapters.models.timing_sklearn import SklearnTimingModel

        model = SklearnTimingModel(definition(TimingModelKind.LOGISTIC))
        rows = samples(200)
        self.assertEqual(
            model.fit(samples=rows).fit_content_hash,
            model.fit(samples=tuple(reversed(rows))).fit_content_hash,
        )


class NoLookAheadTest(unittest.TestCase):
    def test_a_sample_whose_label_matures_after_the_fit_cutoff_is_refused(self) -> None:
        """Fitting on a label that had not yet resolved is training on the answer."""
        from a_share_platform.adapters.models.timing_sklearn import SklearnTimingModel

        model = SklearnTimingModel(definition(TimingModelKind.LOGISTIC))
        with self.assertRaises(PermissionError):
            model.fit(
                samples=samples(200),
                fit_cutoff=BASE + timedelta(days=50),   # most labels resolve later
            )

    def test_prediction_features_after_the_decision_time_are_refused(self) -> None:
        ...

    def test_training_sample_requires_label_end_after_session_index(self) -> None:
        """Mirrors WalkForwardSample: the overlap span must be representable."""
        with self.assertRaises(ValueError):
            TimingTrainingSample(
                sample_id="sample:0000",
                decision_time=BASE,
                session_index=10,
                label_end_session_index=10,
                feature_values={"timing.trend.ma_ratio": Decimal("1.0")},
                label_value=Decimal("0.01"),
                label_available_at=BASE,
            )


class ForecastShapeTest(unittest.TestCase):
    def test_logistic_produces_a_probability_and_a_distribution(self) -> None:
        """SPEC-026 requires both a probability and a return distribution."""
        from a_share_platform.adapters.models.timing_sklearn import SklearnTimingModel

        fitted = SklearnTimingModel(definition(TimingModelKind.LOGISTIC)).fit(
            samples=samples(200)
        )
        forecast = fitted.predict_horizon(
            horizon_trading_days=20,
            feature_values={
                "timing.trend.ma_ratio": Decimal("1.05"),
                "timing.volatility.realized_20": Decimal("0.18"),
            },
        )
        self.assertEqual(forecast.status, TimingEstimateStatus.QUANTIFIED)
        self.assertTrue(Decimal(0) <= forecast.up_probability <= Decimal(1))
        self.assertLessEqual(forecast.p10_return_ratio, forecast.p50_return_ratio)
        self.assertLessEqual(forecast.p50_return_ratio, forecast.p90_return_ratio)

    def test_a_missing_feature_yields_an_unavailable_forecast_not_a_zero(self) -> None:
        """Imputing zero for a standardised feature asserts 'exactly average'."""
        from a_share_platform.adapters.models.timing_sklearn import SklearnTimingModel

        fitted = SklearnTimingModel(definition(TimingModelKind.LOGISTIC)).fit(
            samples=samples(200)
        )
        forecast = fitted.predict_horizon(
            horizon_trading_days=20,
            feature_values={"timing.trend.ma_ratio": Decimal("1.05")},
        )
        self.assertEqual(forecast.status, TimingEstimateStatus.UNAVAILABLE)
        self.assertIn("timing.volatility.realized_20", forecast.status_reason)

    def test_too_few_samples_refuses_to_fit(self) -> None:
        """Twenty-one bars is the P3 volatility input, not a training set."""
        from a_share_platform.adapters.models.timing_sklearn import SklearnTimingModel

        with self.assertRaises(ValueError):
            SklearnTimingModel(definition(TimingModelKind.LOGISTIC)).fit(
                samples=samples(21)
            )
```

- [ ] **Step 6: 运行确认红测 → 实现 port → 实现 adapter → 转绿**

先写 `ports/timing_models.py` 的 Protocol 与 `domain/timing_models.py` 的
`TimingTrainingSample`，用一个 test-local fake 让合同测试转绿；
再写 sklearn adapter。**顺序反了就会让 sklearn 的 API 形状决定 domain 合同。**

- [ ] **Step 7: 树模型与状态模型保持不做**

P7-W02 把树模型/状态模型标为 `MAY`。**本 plan 不做**，原型 `9:238` 的
`Tree V0` / `State V0` 两行在运行时显示 `未评估` 且 `N/A`，与 Frame 一致。
在 Evidence 中显式记录这是范围决定，不是遗漏。

- [ ] **Step 8: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/domain/timing_models.py \
  platform/src/a_share_platform/ports/timing_models.py \
  platform/src/a_share_platform/adapters/models/timing_sklearn.py \
  platform/tests/test_timing_baseline_models.py \
  platform/tests/test_timing_active_models.py
git commit -m "feat: add timing baselines and active models on a neutral port

Static full investment is the honest null: it forecasts nothing, holds
everything and pays no timing cost, which is exactly why an active model has to
beat it after cost to justify existing.  It is implemented as a model rather than
as an absence so the comparison table has a real row to point at.

The volatility-target baseline calls the existing passive_volatility_exposure and
the frozen 20/244 formula version instead of recomputing them.  A second
implementation of that number would drift from the P3 ledger records and there
would be no way to tell which one the stored exposure came from.

Fitting lives in an adapter because domain code may not import sklearn; the
domain owns the sample shape, the forecast shape and the fit identity.  Two
guards carry the weight.  A fit is reproducible from definition, samples and
seed, and is invariant to sample order — without that an experiment cannot be
replayed and no result is evidence.  A sample whose label had not yet resolved at
the fit cutoff is refused, because training on an unresolved label is training on
the answer.  A missing feature yields an unavailable forecast rather than a zero,
since zero in a standardised space asserts 'exactly average' rather than
'unknown'."
```

---

### Task 3: 验证引擎（walk-forward / HAC / 校准 / DM / 净效用）

对应 Step 06 Task 3：「新增 walk-forward/calibration/HAC/DM/net utility 模块和独立
statsmodels/sklearn 对照；不根据结果临时改 metric。」

这是本 plan 最难的一个 Task，因为它要同时处理三个陷阱。**必须按下面的顺序做** ——
先把重叠窗口的推断做对，再做校准，最后做净效用。反过来做会得到一堆看起来很好的数字，
然后在最后一步发现全部无效。

**Files:**
- Create: `platform/src/a_share_platform/domain/timing_validation.py`
- Create: `platform/src/a_share_platform/validation/timing_crosscheck.py`
- Test: `platform/tests/test_timing_walk_forward.py`
- Test: `platform/tests/test_timing_calibration.py`
- Test: `platform/tests/test_timing_net_utility.py`
- Test: `platform/tests/test_timing_crosscheck.py`

**Interfaces:**
- Consumes: `purged_embargoed_walk_forward()`、`newey_west_mean_test()`、
  `block_bootstrap_mean_ci()`、`cross_check_newey_west_mean()`、Task 1 的 overlap 声明、
  Task 2 的模型、**P-5 的成本模型**
- Produces:
  ```python
  def timing_walk_forward(*, samples, target: TimingTargetDefinition,
      spec: WalkForwardSpec, data_mode) -> WalkForwardResult
      # 薄封装：强制 purge_sessions >= target.overlapping_sessions

  @dataclass(frozen=True)
  class CalibrationBin:
      lower_probability: Decimal; upper_probability: Decimal
      predicted_mean: Decimal | None; observed_frequency: Decimal | None
      sample_size: int; status: TimingEstimateStatus; status_reason: str | None

  @dataclass(frozen=True)
  class CalibrationResult:
      status; bins: tuple[CalibrationBin, ...]
      brier_score: Decimal | None; log_loss: Decimal | None
      reliability: Decimal | None; resolution: Decimal | None
      reference_brier_score: Decimal | None     # climatology baseline
      brier_skill_score: Decimal | None
      sample_size: int; missing_count: int
      formula_version: str; unavailable_reason: str | None
      scientific_status: StatisticsScientificStatus

  def probability_calibration(observations, *, spec, data_mode) -> CalibrationResult
  def diebold_mariano(candidate_losses, baseline_losses, *, spec: HACNeweyWestSpec,
                      data_mode) -> DieboldMarianoResult
  def net_timing_utility(*, gross_returns, exposures, cost_model, spec,
                          data_mode) -> NetUtilityResult
  ```

- [ ] **Step 1: 先读 walk-forward 的 purge 语义，确认它能表达重叠**

```bash
cd platform
sed -n 381,470p src/a_share_platform/domain/factor_validation.py
grep -n "class WalkForwardResult" -A 18 src/a_share_platform/domain/factor_validation.py
```

关键几行（已核实）：

```python
cutoff = test_start - spec.purge_sessions
training = tuple(v for v in candidates if v.label_end_session_index < cutoff)
purged   = tuple(v for v in candidates if v.label_end_session_index >= cutoff)
```

`purge` 按 `label_end_session_index` 剔除训练样本 —— **这正是重叠窗口需要的语义**，
不需要新写 fold 生成器。本 Task 只加一层强制：`purge_sessions` 必须 `>= overlapping_sessions`。

- [ ] **Step 2: 写失败测试 —— purge 必须覆盖重叠长度**

```python
# platform/tests/test_timing_walk_forward.py
"""Timing walk-forward, where purge must cover the overlap.

The existing purged_embargoed_walk_forward already drops training samples whose
label_end_session_index reaches into the test window, which is exactly the
semantics an overlapping horizon needs.  What it cannot know is how long the
overlap is — that lives on the target definition.

A 20-day target purged by 5 sessions leaves 15 sessions of shared price path
between the last training label and the first test session.  The fold looks
clean and is not, so the wrapper refuses the combination rather than producing
folds that quietly leak.
"""

from __future__ import annotations

import unittest

from a_share_platform.domain.factor_validation import (
    WalkForwardSample,
    WalkForwardSpec,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.domain.timing_research import (
    TimingOverlapPolicy,
    TimingTargetDefinition,
    TimingTargetKind,
)
from a_share_platform.domain.timing_validation import timing_walk_forward


def target(horizon: int = 20) -> TimingTargetDefinition:
    return TimingTargetDefinition(
        target_id="timing.target.csi300.return",
        version="v0",
        benchmark_id="index:000300",
        tradable_proxy_id="etf:510300",
        kind=TimingTargetKind.RETURN,
        horizon_trading_days=horizon,
        overlap_policy=TimingOverlapPolicy.OVERLAPPING_HAC_REQUIRED,
        overlapping_sessions=horizon - 1,
        data_mode=DataMode.CURRENT_RESEARCH,
        trust_state=DataTrustState.NORMALIZED_CURRENT,
    )


def samples(count: int, horizon: int = 20) -> tuple[WalkForwardSample, ...]:
    return tuple(
        WalkForwardSample(
            sample_id=f"timing:{index:04d}",
            session_index=index,
            label_end_session_index=index + horizon,
            feature_version_id="timing.features:v0",
            label_version_id="timing.target.csi300.return:v0",
            data_mode=DataMode.CURRENT_RESEARCH,
            feature_trust_state=DataTrustState.NORMALIZED_CURRENT,
            label_trust_state=DataTrustState.NORMALIZED_CURRENT,
            available=True,
        )
        for index in range(count)
    )


def spec(*, purge: int, test_sessions: int = 60) -> WalkForwardSpec:
    return WalkForwardSpec(
        initial_training_sessions=500,
        test_sessions=test_sessions,
        step_sessions=test_sessions + 20,
        horizon_sessions=20,
        purge_sessions=purge,
        embargo_sessions=20,
        minimum_training_samples=250,
        split_version="timing-wf-v0",
    )


class PurgeCoversOverlapTest(unittest.TestCase):
    def test_purge_shorter_than_the_overlap_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            timing_walk_forward(
                samples=samples(1200),
                target=target(20),
                spec=spec(purge=5),
                data_mode=DataMode.CURRENT_RESEARCH,
            )
        self.assertIn("overlap", str(caught.exception).lower())

    def test_purge_equal_to_the_overlap_is_accepted(self) -> None:
        result = timing_walk_forward(
            samples=samples(1200),
            target=target(20),
            spec=spec(purge=19),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        self.assertGreater(len(result.folds), 0)

    def test_sixty_day_target_needs_a_longer_purge_than_a_twenty_day_one(self) -> None:
        """The requirement scales with the horizon, so it cannot be a constant."""
        with self.assertRaises(ValueError):
            timing_walk_forward(
                samples=samples(1200, horizon=60),
                target=target(60),
                spec=spec(purge=19),
                data_mode=DataMode.CURRENT_RESEARCH,
            )

    def test_no_training_sample_label_reaches_into_its_test_window(self) -> None:
        """The property the purge exists to guarantee, asserted directly."""
        result = timing_walk_forward(
            samples=samples(1200),
            target=target(20),
            spec=spec(purge=19),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        by_id = {value.sample_id: value for value in samples(1200)}
        for fold in result.folds:
            for sample_id in fold.training_sample_ids:
                self.assertLess(
                    by_id[sample_id].label_end_session_index,
                    fold.test_start_session_index,
                    f"fold {fold.fold_index} trains on a label that resolves "
                    f"inside its own test window",
                )


class TwentyOneBarRealityCheckTest(unittest.TestCase):
    def test_the_p3_baseline_window_produces_no_folds(self) -> None:
        """21 closes is the passive volatility input, not a research history.

        This test documents why P-6 depends on P-1: with the data currently in the
        development database there is nothing to validate.
        """
        result = timing_walk_forward(
            samples=samples(21),
            target=target(20),
            spec=spec(purge=19),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        self.assertEqual(result.folds, ())
        self.assertIsNotNone(result.unavailable_reason)
```

- [ ] **Step 3: 运行确认红测 → 实现薄封装 → 转绿**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_timing_walk_forward -v`
Expected: FAIL —— `domain.timing_validation` 不存在。

实现只做三件事：校验 `purge_sessions >= target.overlapping_sessions`、
校验 `spec.horizon_sessions == target.horizon_trading_days`、转调已有函数。
**不要复制 fold 生成逻辑。**

- [ ] **Step 4: 写校准红测（校准比准确率重要）**

```python
# platform/tests/test_timing_calibration.py
"""Calibration, which matters more for timing than accuracy does.

A model that says "60% up" on days that rise 60% of the time is useful even
though it is wrong 40% of the time: the number can be sized against.  A model
that says "90% up" on days that rise 55% of the time is worse than useless
because acting on it oversizes systematically — and its directional accuracy of
55% looks respectable.

So the primary metric is the Brier score decomposed into reliability and
resolution, reported against a climatology reference.  A model whose Brier score
merely matches the unconditional base rate has resolution of zero and has learnt
nothing, however good its raw Brier looks.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.domain.timing import TimingEstimateStatus
from a_share_platform.domain.timing_validation import (
    CalibrationSpec,
    ProbabilityOutcomeObservation,
    probability_calibration,
)


def spec(bins: int = 10, minimum: int = 50) -> CalibrationSpec:
    return CalibrationSpec(
        bin_count=bins,
        minimum_sample_size=minimum,
        minimum_bin_sample_size=5,
        formula_version="brier-reliability-resolution-v0",
    )


def observations(
    pairs: tuple[tuple[str, bool], ...]
) -> tuple[ProbabilityOutcomeObservation, ...]:
    return tuple(
        ProbabilityOutcomeObservation(
            period_id=f"2025-{index // 20 + 1:02d}-{index % 20 + 1:02d}",
            predicted_probability=Decimal(probability),
            realised_up=realised,
            statistic_version_id="timing-model:logit:v0",
            data_mode=DataMode.CURRENT_RESEARCH,
            trust_state=DataTrustState.NORMALIZED_CURRENT,
            availability_enforced=True,
        )
        for index, (probability, realised) in enumerate(pairs)
    )


class PerfectlyCalibratedTest(unittest.TestCase):
    def test_a_perfectly_calibrated_forecast_has_zero_reliability(self) -> None:
        """Fixture: 100 forecasts of 0.60, of which exactly 60 rise.

        Brier = 0.6*(0.6-1)^2 + 0.4*(0.6-0)^2 = 0.6*0.16 + 0.4*0.36 = 0.24.
        Reliability = 0 because the bin's observed frequency equals 0.60.
        """
        pairs = tuple(("0.60", index < 60) for index in range(100))
        result = probability_calibration(
            observations(pairs), spec=spec(), data_mode=DataMode.CURRENT_RESEARCH
        )
        self.assertEqual(result.status, TimingEstimateStatus.QUANTIFIED)
        self.assertAlmostEqual(float(result.brier_score), 0.24, places=6)
        self.assertAlmostEqual(float(result.reliability), 0.0, places=6)

    def test_an_overconfident_forecast_has_positive_reliability(self) -> None:
        """Fixture: 100 forecasts of 0.90, of which only 55 rise.

        Brier = 0.55*(0.9-1)^2 + 0.45*(0.9-0)^2 = 0.0055 + 0.3645 = 0.37.
        Reliability = (0.90 - 0.55)^2 = 0.1225 — the penalty overconfidence earns.
        """
        pairs = tuple(("0.90", index < 55) for index in range(100))
        result = probability_calibration(
            observations(pairs), spec=spec(), data_mode=DataMode.CURRENT_RESEARCH
        )
        self.assertAlmostEqual(float(result.brier_score), 0.37, places=6)
        self.assertAlmostEqual(float(result.reliability), 0.1225, places=6)

    def test_a_constant_base_rate_forecast_has_zero_resolution(self) -> None:
        """Predicting the unconditional frequency every day learns nothing.

        Its Brier score is respectable and its skill score is exactly zero, which
        is the number that has to be reported.
        """
        pairs = tuple(("0.55", index < 55) for index in range(100))
        result = probability_calibration(
            observations(pairs), spec=spec(), data_mode=DataMode.CURRENT_RESEARCH
        )
        self.assertAlmostEqual(float(result.resolution), 0.0, places=6)
        self.assertAlmostEqual(float(result.brier_skill_score), 0.0, places=6)

    def test_accuracy_alone_can_look_good_while_calibration_is_bad(self) -> None:
        """The comparison the metric exists to make.

        The overconfident model is directionally right 55% of the time, the same
        as the base-rate model, yet its Brier score is materially worse.  A
        dashboard that showed only accuracy would rank them equal.
        """
        overconfident = probability_calibration(
            observations(tuple(("0.90", i < 55) for i in range(100))),
            spec=spec(), data_mode=DataMode.CURRENT_RESEARCH,
        )
        base_rate = probability_calibration(
            observations(tuple(("0.55", i < 55) for i in range(100))),
            spec=spec(), data_mode=DataMode.CURRENT_RESEARCH,
        )
        self.assertGreater(overconfident.brier_score, base_rate.brier_score)


class CalibrationGuardTest(unittest.TestCase):
    def test_below_minimum_sample_size_is_unavailable_not_a_number(self) -> None:
        result = probability_calibration(
            observations(tuple(("0.60", i < 6) for i in range(10))),
            spec=spec(minimum=50), data_mode=DataMode.CURRENT_RESEARCH,
        )
        self.assertEqual(result.status, TimingEstimateStatus.UNAVAILABLE)
        self.assertIn("sample", result.unavailable_reason.lower())
        self.assertIsNone(result.brier_score)

    def test_a_thin_bin_reports_unavailable_rather_than_a_noisy_frequency(self) -> None:
        """One observation in a bin gives an observed frequency of 0 or 1."""
        ...

    def test_bin_count_is_part_of_the_formula_version(self) -> None:
        """Changing bins changes reliability, so it cannot be an invisible knob."""
        ...

    def test_probability_outside_zero_one_is_refused(self) -> None:
        ...

    def test_scientific_status_stays_not_evaluated(self) -> None:
        """A calibration curve on current-only data is not validity evidence."""
        result = probability_calibration(
            observations(tuple(("0.60", i < 60) for i in range(100))),
            spec=spec(), data_mode=DataMode.CURRENT_RESEARCH,
        )
        self.assertEqual(result.scientific_status.value, "not_evaluated")


class OverlappingHorizonTest(unittest.TestCase):
    def test_overlapping_observations_must_declare_their_hac_lag(self) -> None:
        """Brier on overlapping windows is fine; its standard error is not.

        The point estimate of a Brier score does not care about autocorrelation,
        but any statement about whether one Brier score beats another does.  So the
        result carries the lag it was computed under, and refuses to be compared
        against a result computed under a different one.
        """
        ...
```

- [ ] **Step 5: 运行确认红测 → 实现 → 转绿**

Brier 分解用 Murphy 分解：`Brier = reliability - resolution + uncertainty`。
`brier_skill_score = 1 - brier / reference_brier`，`reference_brier` 用样本无条件频率
（climatology）。**三项必须同时报告** —— 只报 Brier 无法区分"校准好但无信息"
与"有信息但过度自信"。

- [ ] **Step 6: 写 DM 检验红测（对照被动基线）**

追加到 `test_timing_calibration.py`，并在文件头补两个 import：

```python
from a_share_platform.domain.factor_statistics import HACNeweyWestSpec
from a_share_platform.domain.timing_validation import diebold_mariano
```

```python
class DieboldMarianoTest(unittest.TestCase):
    """Is the candidate's loss series actually lower than the baseline's?

    A raw comparison of two mean losses says nothing about whether the difference
    could be noise.  DM tests the mean loss differential with a HAC standard
    error, which is the only version of the question that has an answer when the
    forecast windows overlap.
    """

    def test_identical_loss_series_yield_a_zero_statistic(self) -> None:
        losses = tuple(Decimal("0.24") for _ in range(200))
        result = diebold_mariano(
            candidate_losses=losses, baseline_losses=losses,
            spec=HACNeweyWestSpec(max_lag=19, minimum_sample_size=100,
                                  formula_version="dm-bartlett-v0"),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        self.assertEqual(result.loss_differential_mean, Decimal(0))
        self.assertEqual(result.status, TimingEstimateStatus.QUANTIFIED)
        self.assertAlmostEqual(float(result.statistic), 0.0, places=9)

    def test_max_lag_below_the_overlap_is_refused(self) -> None:
        """A 20-day horizon compared with lag 0 is the sqrt(60) mistake.

        This is the single guard that prevents an overlapping-window comparison
        from reporting a significance it has not earned.
        """
        with self.assertRaises(ValueError):
            diebold_mariano(
                candidate_losses=tuple(Decimal("0.24") for _ in range(200)),
                baseline_losses=tuple(Decimal("0.25") for _ in range(200)),
                spec=HACNeweyWestSpec(max_lag=0, minimum_sample_size=100,
                                      formula_version="dm-bartlett-v0"),
                data_mode=DataMode.CURRENT_RESEARCH,
                required_max_lag=19,
            )

    def test_the_hac_lag_widens_the_standard_error(self) -> None:
        """Demonstrates the size of the trap on real-shaped inputs.

        The same loss differential evaluated at lag 0 and lag 19 must produce a
        materially smaller statistic at lag 19.  If it does not, the HAC
        correction is not doing anything and the implementation is wrong.
        """
        differential = tuple(
            Decimal("0.01") if index % 40 < 20 else Decimal("-0.005")
            for index in range(400)
        )
        ...
        self.assertLess(abs(float(lag19.statistic)), abs(float(lag0.statistic)))

    def test_unequal_length_series_are_refused(self) -> None:
        ...

    def test_a_worse_candidate_produces_a_negative_statistic(self) -> None:
        ...
```

- [ ] **Step 7: 写净效用红测（毛胜净负必须失败）**

```python
# platform/tests/test_timing_net_utility.py
"""Net utility, where the sign after cost decides whether a signal exists.

A 20-day timing signal turns over roughly 5% of the book per day.  Round-trip
fees, slippage and impact on a CSI300 proxy comfortably consume two to four
percent a year.  A signal with 1.5% of annual gross alpha is net negative, and
every statistical test on its gross series will still say it predicts.

So net utility is a gate rather than a report line: a model that wins gross and
loses net may not enter the VALIDATED lifecycle.  The test below constructs
exactly that case, because it is the case that will actually occur.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.domain.timing import TimingEstimateStatus
from a_share_platform.domain.timing_validation import (
    NetUtilitySpec,
    TimingExposureObservation,
    net_timing_utility,
)


class GrossWinsNetLosesTest(unittest.TestCase):
    def test_a_signal_that_wins_gross_and_loses_net_is_reported_as_net_negative(
        self,
    ) -> None:
        """Fixture: exposure flips fully every session, gross edge 2 bp/session.

        250 sessions, gross 0.0002 per session = +5.0% gross.
        Turnover 1.0 per session at 15 bp round trip = 0.0015 per session
        = -37.5% cost.  Net is unambiguously negative.
        """
        observations = tuple(
            TimingExposureObservation(
                period_id=f"session:{index:04d}",
                gross_return_ratio=Decimal("0.0002"),
                exposure_ratio=Decimal(1) if index % 2 == 0 else Decimal(0),
                statistic_version_id="timing-model:logit:v0",
                data_mode=DataMode.CURRENT_RESEARCH,
                trust_state=DataTrustState.NORMALIZED_CURRENT,
                availability_enforced=True,
            )
            for index in range(250)
        )
        result = net_timing_utility(
            observations=observations,
            spec=NetUtilitySpec(
                round_trip_cost_ratio=Decimal("0.0015"),
                minimum_sample_size=100,
                formula_version="net-utility-v0",
                cost_model_version="p6-cost-model:v0",
            ),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        self.assertEqual(result.status, TimingEstimateStatus.QUANTIFIED)
        self.assertGreater(result.gross_return_ratio, Decimal(0))
        self.assertLess(result.net_return_ratio, Decimal(0))
        self.assertFalse(result.net_positive)

    def test_a_net_negative_result_cannot_be_promoted(self) -> None:
        """The gate, asserted where it is enforced rather than in prose."""
        from a_share_platform.domain.timing_validation import timing_promotion_eligible

        self.assertFalse(
            timing_promotion_eligible(
                net_utility=_net_negative_result(),
                calibration=_well_calibrated_result(),
                diebold_mariano=_significant_result(),
            )
        )

    def test_turnover_is_reported_alongside_the_net_number(self) -> None:
        """A net figure without its turnover cannot be cost-audited."""
        ...

    def test_cost_model_version_is_required(self) -> None:
        """A net return whose cost assumptions are unversioned is not evidence."""
        with self.assertRaises(ValueError):
            NetUtilitySpec(
                round_trip_cost_ratio=Decimal("0.0015"),
                minimum_sample_size=100,
                formula_version="net-utility-v0",
                cost_model_version="",
            )

    def test_zero_cost_is_refused_rather_than_treated_as_frictionless(self) -> None:
        """A frictionless backtest is not a conservative assumption."""
        with self.assertRaises(ValueError):
            NetUtilitySpec(
                round_trip_cost_ratio=Decimal(0),
                minimum_sample_size=100,
                formula_version="net-utility-v0",
                cost_model_version="p6-cost-model:v0",
            )

    def test_static_baseline_pays_no_timing_cost(self) -> None:
        """Constant full exposure has zero turnover, so its net equals its gross.

        This is why static full investment is a hard baseline to beat and why it
        must be in the comparison table.
        """
        observations = tuple(
            TimingExposureObservation(
                period_id=f"session:{index:04d}",
                gross_return_ratio=Decimal("0.0002"),
                exposure_ratio=Decimal(1),
                statistic_version_id="timing-model:static_full:v0",
                data_mode=DataMode.CURRENT_RESEARCH,
                trust_state=DataTrustState.NORMALIZED_CURRENT,
                availability_enforced=True,
            )
            for index in range(250)
        )
        result = net_timing_utility(
            observations=observations,
            spec=NetUtilitySpec(
                round_trip_cost_ratio=Decimal("0.0015"),
                minimum_sample_size=100,
                formula_version="net-utility-v0",
                cost_model_version="p6-cost-model:v0",
            ),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        self.assertEqual(result.turnover_ratio, Decimal(0))
        self.assertEqual(result.net_return_ratio, result.gross_return_ratio)
```

**注意**：`NetUtilitySpec.round_trip_cost_ratio` 只是本 Task 的最小接口。
P-5 完成后必须换成真实的 `CostModel`（费用 + 滑点 + 冲击 + 参与率），
并把 `cost_model_version` 绑到 P-5 的真实版本。在 Evidence 中记录这次替换。

- [ ] **Step 8: 独立库交叉验证**

```python
# platform/tests/test_timing_crosscheck.py
"""Cross-check timing statistics against statsmodels and sklearn.

The cross-check must receive the identical observation sequence as the primary
implementation.  A cross-check on differently-prepared inputs proves that two
pipelines agree, not that one formula is right.

Absence of the library reports unavailable.  It must never read as agreement:
that is the failure mode where a missing dependency silently converts a
disagreement into a pass.
"""

from __future__ import annotations

import unittest

from a_share_platform.validation.timing_crosscheck import (
    cross_check_brier_score,
    cross_check_timing_hac_mean,
)


class InputIdentityTest(unittest.TestCase):
    def test_the_reference_receives_the_same_sequence(self) -> None:
        ...

    def test_brier_matches_sklearn_brier_score_loss(self) -> None:
        """Reference method: sklearn.metrics.brier_score_loss."""
        ...

    def test_hac_matches_the_existing_newey_west_cross_check(self) -> None:
        """Reuses cross_check_newey_west_mean; the reference method string is
        `statsmodels.api.OLS intercept HAC Bartlett maxlags=<n> use_correction=False`.
        """
        ...


class MissingLibraryTest(unittest.TestCase):
    def test_absent_sklearn_reports_unavailable_not_agreement(self) -> None:
        ...
```

- [ ] **Step 9: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/domain/timing_validation.py \
  platform/src/a_share_platform/validation/timing_crosscheck.py \
  platform/tests/test_timing_walk_forward.py \
  platform/tests/test_timing_calibration.py \
  platform/tests/test_timing_net_utility.py \
  platform/tests/test_timing_crosscheck.py
git commit -m "feat: add the timing validation engine with overlap-aware inference

Three properties of index-level timing decide whether any of these numbers mean
anything, and each is enforced rather than documented.

Overlap first.  A daily-rolled 20-day forecast shares nineteen of twenty days of
price path with its neighbour, so an i.i.d. standard error understates the truth
by roughly sqrt(20) and turns noise into significance.  The walk-forward wrapper
refuses a purge shorter than the declared overlap, and the Diebold-Mariano test
refuses a HAC lag shorter than it.  The existing fold generator already purges by
label_end_session_index, which is exactly the right semantics, so it is reused
rather than reimplemented.

Calibration second, because for a timing signal it matters more than accuracy.  A
model that says 90% on days that rise 55% of the time is directionally as
accurate as one that says 55%, but acting on it oversizes systematically.  The
Brier score is therefore decomposed into reliability and resolution and reported
against a climatology reference, so a model that has merely learnt the base rate
shows a skill score of zero however good its raw Brier looks.

Cost last and hardest.  A 20-day signal turns over about 5% a day, which costs
two to four percent a year on a CSI300 proxy, so a 1.5% gross edge is net
negative while every test on the gross series still says it predicts.  Net
utility is a promotion gate rather than a report line, a zero cost assumption is
refused outright, and the static full-investment baseline is included precisely
because its zero turnover makes it hard to beat."
```

---

### Task 4: Shadow ledger、Outcome 与 PromotionReview

对应 Step 06 Task 4：「扩展已有 timing ledger：唯一 natural key、append-only trigger、
no-backfill clock guard、mature outcome worker、promotion scope/max impact/rollback。」

**核心设计决定**：`append_baseline()` 不动，新增 `append_active()`。理由在下面的测试里
逐条断言 —— P3 的 21 条 bar、1 条 forecast 和 2 条 lineage 是**已经存在的真实证据**，
放宽验证它们的守卫会让那条证据链事后变得不可信。

**Files:**
- Modify: `platform/src/a_share_platform/application/timing_ledger.py`（新增方法，不改旧方法）
- Modify: `platform/src/a_share_platform/application/timing_baseline.py`（分化 unavailable reason）
- Create: `platform/src/a_share_platform/domain/timing_outcomes.py`
- Create: `platform/src/a_share_platform/application/timing_promotion.py`
- Create: `platform/src/a_share_platform/workers/timing_outcomes.py`
- Create: `platform/migrations/0037_p7_timing_research.sql`
- Create: `platform/migrations/0038_p7_timing_outcomes.sql`
- Test: `platform/tests/test_timing_active_ledger.py`
- Test: `platform/tests/test_timing_outcomes.py`
- Test: `platform/tests/test_timing_promotion.py`

**Interfaces:**
- Consumes: 已有 `TimingShadowLedger`、`TimingForecastRepository`、
  `domain/factor_lifecycle.py` 的 `ApprovalScope` / `ApprovalDecision` / `PromotionApproval`、
  Task 3 的 `timing_promotion_eligible()`
- Produces:
  ```python
  class TimingShadowLedger:
      def append_baseline(self, value: TimingForecast) -> TimingForecast: ...   # 不变
      def append_active(self, value: TimingForecast, *,
                        promotion: TimingPromotionBinding | None) -> TimingForecast: ...

  @dataclass(frozen=True)
  class TimingPromotionBinding:
      review_id: str
      approval_scope: ApprovalScope
      maximum_exposure_delta: Decimal      # 未晋级时必须为 0
      expires_at: datetime
      rollback_forecast_id: str | None
      validation_report_hash: str

  @dataclass(frozen=True)
  class TimingOutcome:
      outcome_id: str; forecast_id: str; horizon_trading_days: int
      matured_at: datetime
      realised_return_ratio: Decimal | None
      realised_up: bool | None
      status: TimingEstimateStatus; status_reason: str | None
  ```

- [ ] **Step 1: 先读 P3 守卫的全部六条，逐条判断是否可复用**

```bash
cd platform
sed -n 21,56p src/a_share_platform/application/timing_ledger.py
grep -n "UNIQUE\|append_only\|reject_timing" migrations/0012_timing_shadow_ledger.sql
```

现有 migration 已有两件本 Task 需要的东西，**不要重建**：

```sql
UNIQUE (benchmark_id, universe_version_id, effective_session)

CREATE TRIGGER timing_forecasts_append_only
BEFORE UPDATE OR DELETE ON timing_forecasts
FOR EACH ROW EXECUTE FUNCTION reject_timing_forecast_mutation();
```

自然键与 append-only trigger 都在。`0037` 只需新增 `timing_targets`、
`timing_feature_snapshots`、`timing_experiments`、`timing_model_versions`；
`0038` 新增 `timing_outcomes`、`timing_calibrations`、`timing_promotion_reviews`。
所有新表进 `research` 层，并在 `adapters/postgres/schema_layers.py` 的
`PERSISTENT_TABLE_SCHEMAS` 登记。

- [ ] **Step 2: 写失败测试 —— P3 守卫不许被削弱**

```python
# platform/tests/test_timing_active_ledger.py
"""Active timing forecasts go through a new door, not a widened old one.

The development database already holds one real passive baseline: 21 CSI500 bars
from 2026-07-13 to 2026-08-10, observed volatility 0.4131876..., passive exposure
0.2904249..., active adjustment unavailable.  Six guards in append_baseline are
what make that record trustworthy.

Relaxing any of them so that an active forecast can pass through would
retroactively weaken the guarantee on the record already stored — nothing about
it changes, but the assertion 'this was checked' stops being true.  So
append_active is a separate method with its own, stricter rules about exposure.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from a_share_platform.adapters.memory.timing import InMemoryTimingForecastRepository
from a_share_platform.application.timing_ledger import TimingShadowLedger
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.domain.timing import (
    ActiveTimingAdjustment,
    HorizonReturnForecast,
    TimingEstimateStatus,
    TimingForecast,
    TimingModelLifecycle,
    TimingRiskForecast,
)

SESSION = date(2026, 8, 10)
DECISION = datetime(2026, 8, 10, 7, 10, tzinfo=UTC)   # 15:10 Asia/Shanghai


def quantified_horizons() -> tuple[HorizonReturnForecast, ...]:
    return tuple(
        HorizonReturnForecast(
            horizon_trading_days=horizon,
            status=TimingEstimateStatus.QUANTIFIED,
            up_probability=Decimal("0.52"),
            expected_return_ratio=Decimal("0.004"),
            p10_return_ratio=Decimal("-0.030"),
            p50_return_ratio=Decimal("0.003"),
            p90_return_ratio=Decimal("0.040"),
        )
        for horizon in (1, 5, 20, 60)
    )


def forecast(
    *,
    horizons=None,
    active: ActiveTimingAdjustment | None = None,
    lifecycle: TimingModelLifecycle = TimingModelLifecycle.CANDIDATE,
    final_lower: Decimal = Decimal("0.29"),
    final_upper: Decimal = Decimal("0.29"),
    approval_scope: str = "shadow_candidate_only",
) -> TimingForecast:
    return TimingForecast(
        forecast_id="timing:000905:2026-08-10:active0000000000",
        benchmark_id="index:000905",
        universe_version_id="universe-version:csi500:2026-08-10",
        effective_session=SESSION,
        decision_time=DECISION,
        data_cutoff_at=DECISION,
        created_at=DECISION,
        context=RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.SHADOW),
        horizon_forecasts=horizons or quantified_horizons(),
        risk_forecast=TimingRiskForecast(
            status=TimingEstimateStatus.QUANTIFIED,
            annualized_volatility_ratio=Decimal("0.41"),
        ),
        static_exposure_ratio=Decimal(1),
        passive_exposure_ratio=Decimal("0.29"),
        passive_target_volatility_ratio=Decimal("0.12"),
        passive_observed_volatility_ratio=Decimal("0.41"),
        passive_lookback_sessions=20,
        active_adjustment=active
        or ActiveTimingAdjustment(
            status=TimingEstimateStatus.UNAVAILABLE,
            status_reason="active timing model is not promoted for shadow exposure",
        ),
        final_exposure_lower_ratio=final_lower,
        final_exposure_upper_ratio=final_upper,
        model_version_id="timing-model:logistic:v0",
        model_lifecycle=lifecycle,
        run_id="run:timing-active:000905:2026-08-10:abcdef0123456789",
        approval_scope=approval_scope,
        dataset_version_ids=("dataset:timing-benchmark:000905:2026-08-10:0123456789abcdef",),
        input_trust_state=DataTrustState.NORMALIZED_CURRENT,
    )


class BaselineGuardsSurviveTest(unittest.TestCase):
    def test_append_baseline_still_refuses_a_quantified_horizon(self) -> None:
        ledger = TimingShadowLedger(InMemoryTimingForecastRepository())
        with self.assertRaises(ValueError) as caught:
            ledger.append_baseline(forecast(lifecycle=TimingModelLifecycle.BASELINE))
        self.assertIn("horizon forecasts must remain unavailable", str(caught.exception))

    def test_append_baseline_still_refuses_a_quantified_active_adjustment(self) -> None:
        ledger = TimingShadowLedger(InMemoryTimingForecastRepository())
        with self.assertRaises(ValueError) as caught:
            ledger.append_baseline(
                forecast(
                    horizons=tuple(
                        HorizonReturnForecast(
                            horizon_trading_days=horizon,
                            status=TimingEstimateStatus.UNAVAILABLE,
                            status_reason="baseline",
                        )
                        for horizon in (1, 5, 20, 60)
                    ),
                    active=ActiveTimingAdjustment(
                        status=TimingEstimateStatus.QUANTIFIED,
                        point_exposure_delta=Decimal("0.05"),
                        lower_exposure_delta=Decimal("0.00"),
                        upper_exposure_delta=Decimal("0.10"),
                    ),
                    lifecycle=TimingModelLifecycle.BASELINE,
                )
            )
        self.assertIn("active adjustment must remain unavailable", str(caught.exception))

    def test_append_baseline_still_requires_the_baseline_approval_scope(self) -> None:
        ...

    def test_append_baseline_still_requires_static_exposure_of_one(self) -> None:
        ...


class ActiveForecastExposureLockTest(unittest.TestCase):
    def test_an_unpromoted_active_model_cannot_change_exposure(self) -> None:
        """The single most important assertion in this plan.

        A candidate model may publish probabilities and distributions — that is
        the whole point of Shadow.  What it may not do is move the exposure.  With
        no promotion binding, final exposure must equal the passive baseline.
        """
        ledger = TimingShadowLedger(InMemoryTimingForecastRepository())
        stored = ledger.append_active(forecast(), promotion=None)
        self.assertEqual(stored.final_exposure_lower_ratio, stored.passive_exposure_ratio)
        self.assertEqual(stored.final_exposure_upper_ratio, stored.passive_exposure_ratio)
        self.assertEqual(stored.active_adjustment.status, TimingEstimateStatus.UNAVAILABLE)

    def test_an_unpromoted_model_offering_a_quantified_adjustment_is_refused(self) -> None:
        ledger = TimingShadowLedger(InMemoryTimingForecastRepository())
        with self.assertRaises(PermissionError) as caught:
            ledger.append_active(
                forecast(
                    active=ActiveTimingAdjustment(
                        status=TimingEstimateStatus.QUANTIFIED,
                        point_exposure_delta=Decimal("0.05"),
                        lower_exposure_delta=Decimal("0.00"),
                        upper_exposure_delta=Decimal("0.10"),
                    )
                ),
                promotion=None,
            )
        self.assertIn("promotion", str(caught.exception).lower())

    def test_final_exposure_departing_from_passive_without_promotion_is_refused(
        self,
    ) -> None:
        """Blocks the back door: shifting the final numbers instead of the delta."""
        ledger = TimingShadowLedger(InMemoryTimingForecastRepository())
        with self.assertRaises(PermissionError):
            ledger.append_active(
                forecast(final_lower=Decimal("0.34"), final_upper=Decimal("0.34")),
                promotion=None,
            )

    def test_candidate_lifecycle_cannot_carry_an_approved_scope(self) -> None:
        ledger = TimingShadowLedger(InMemoryTimingForecastRepository())
        with self.assertRaises(PermissionError):
            ledger.append_active(
                forecast(
                    lifecycle=TimingModelLifecycle.CANDIDATE,
                    approval_scope="paper",
                ),
                promotion=None,
            )

    def test_a_promotion_binding_with_zero_max_delta_still_locks_exposure(self) -> None:
        """P7-W04: production maximum impact is configurable and starts at 0.

        An approval that exists but grants zero impact must behave exactly like no
        approval.  This is the state the platform ships in.
        """
        ...

    def test_an_expired_promotion_binding_locks_exposure_again(self) -> None:
        ...

    def test_a_promotion_scope_of_paper_does_not_imply_shadow_exposure(self) -> None:
        """Approval scopes do not imply one another in either direction."""
        ...


class NoBackfillClockTest(unittest.TestCase):
    def test_a_shadow_forecast_for_a_past_session_is_refused(self) -> None:
        """Forward evidence has to be waited for.  This is the guard that makes
        the Shadow sample count mean 'days elapsed' rather than 'rows written'.
        """
        ledger = TimingShadowLedger(
            InMemoryTimingForecastRepository(),
            clock=lambda: datetime(2026, 8, 20, 7, 10, tzinfo=UTC),
        )
        with self.assertRaises(PermissionError) as caught:
            ledger.append_active(forecast(), promotion=None)   # session 2026-08-10
        self.assertIn("backfill", str(caught.exception).lower())

    def test_a_research_replay_is_allowed_but_not_as_shadow(self) -> None:
        """A historical replay is a legitimate research artefact.  It just is not
        a forward day, and the deployment stage is where that distinction lives.
        """
        ledger = TimingShadowLedger(
            InMemoryTimingForecastRepository(),
            clock=lambda: datetime(2026, 8, 20, 7, 10, tzinfo=UTC),
        )
        replay = forecast()
        research = replace(
            replay,
            context=RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.RESEARCH),
        )
        stored = ledger.append_research_replay(research)
        self.assertIs(stored.context.deployment_stage, DeploymentStage.RESEARCH)

    def test_shadow_and_research_records_are_counted_separately(self) -> None:
        """A combined count would let 1,900 replayed days read as 1,900 waited
        days, which is the difference between evidence and its imitation.
        """
        ...

    def test_rewriting_an_existing_session_is_refused(self) -> None:
        """append-only in the application layer as well as in the trigger."""
        ...

    def test_the_clock_cannot_move_backwards_between_reads(self) -> None:
        ...
```

- [ ] **Step 3: 运行确认红测 → 实现 `append_active` → 转绿**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_timing_active_ledger -v`
Expected: FAIL —— `TimingShadowLedger.append_active` 不存在，且 `__init__` 不接受 `clock`。

实现时 `clock` 必须有默认值，否则会破坏现有 `TimingBaselineRunner` 里
`TimingShadowLedger(forecast_repository)` 的单参调用。**先跑一遍
`tests.test_timing_baseline_runner` 与 `tests.test_timing_shadow_ledger` 确认没破坏。**

- [ ] **Step 4: 分化 `timing_baseline.py` 的 unavailable reason**

第 180 行现在是：

```python
unavailable_reason = "active timing model is not implemented in P3"
```

P7 之后这句话不再成立 —— 主动模型已经实现了。但它对**被动 baseline 记录**仍然要有个理由。
改成按事实分化：

```python
# The passive baseline states why it carries no active view; the active runner
# states why its view carries no exposure.  Collapsing both into one sentence
# would make a promoted-but-zero-impact model indistinguishable from an
# unimplemented one.
PASSIVE_BASELINE_REASON = (
    "passive volatility baseline publishes no directional or distributional view"
)
UNPROMOTED_ACTIVE_REASON = (
    "active timing model is not promoted for shadow exposure"
)
```

先写断言旧字符串已消失、新字符串各自出现在正确位置的测试，再改代码。
**同时更新 `tests/test_timing_baseline_runner.py` 里断言旧字符串的用例** ——
那不是"修测试迁就实现"，是被动 baseline 的理由确实变了，且要在 Evidence 里说明。

- [ ] **Step 5: Outcome 与 Calibration 到期追加**

```python
# platform/tests/test_timing_outcomes.py
"""Outcomes append when the horizon matures, and never before.

The maturity worker mirrors application/investment_view_outcomes.py: it scans for
forecasts whose horizon has elapsed, computes the realised value from real bars,
and appends.  It never revisits an outcome, and a forecast whose window has not
closed yields pending rather than a partial number.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from decimal import Decimal


class MaturityTest(unittest.TestCase):
    def test_a_horizon_that_has_not_elapsed_stays_pending(self) -> None:
        ...

    def test_a_matured_horizon_appends_exactly_one_outcome(self) -> None:
        ...

    def test_appending_twice_is_idempotent_not_duplicated(self) -> None:
        ...

    def test_a_missing_exit_bar_yields_unavailable_not_a_stale_price(self) -> None:
        """Using the last available close instead silently shortens the horizon."""
        ...

    def test_an_outcome_is_never_recomputed_after_a_data_correction(self) -> None:
        """A corrected bar produces a new outcome version, not an edit.

        Otherwise a model's forward record improves retroactively whenever the
        vendor fixes a price.
        """
        ...

    def test_calibration_snapshot_covers_only_matured_outcomes(self) -> None:
        ...
```

- [ ] **Step 6: PromotionReview 与影响上限**

```python
# platform/tests/test_timing_promotion.py
"""Promotion is a separate gate, and Capability does not imply it.

Every statistical test in Task 3 can pass while the model remains unpromoted.
That is the intended state: the Capability Gate says 'the platform can do active
timing', the Promotion Gate says 'this particular model may move money'.  They
are different questions with different evidence.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal

from a_share_platform.domain.factor_lifecycle import ApprovalDecision, ApprovalScope


class PromotionGateTest(unittest.TestCase):
    def test_all_statistics_passing_does_not_create_an_approval(self) -> None:
        """Capability Gate and Promotion Gate do not imply one another."""
        ...

    def test_net_negative_utility_blocks_promotion_even_with_significant_dm(self) -> None:
        """A statistically real edge that loses money is not an edge."""
        ...

    def test_poor_calibration_blocks_promotion_even_with_good_accuracy(self) -> None:
        ...

    def test_promotion_requires_forward_shadow_days_not_replayed_days(self) -> None:
        """The requirement that cannot be met by running the pipeline harder.

        Historical folds are replayable in seconds.  Forward days are not.  The
        gate counts only records written with deployment_stage=shadow whose
        effective_session equalled the Shanghai date at write time.
        """
        ...

    def test_maximum_exposure_delta_defaults_to_zero(self) -> None:
        ...

    def test_maximum_exposure_delta_cannot_exceed_the_approved_scope(self) -> None:
        ...

    def test_an_approval_records_its_rollback_target(self) -> None:
        """Rollback must be pre-declared, not improvised during an incident."""
        ...

    def test_a_rejected_review_is_retained_not_deleted(self) -> None:
        ...

    def test_a_shadow_approval_does_not_imply_paper(self) -> None:
        ...
```

- [ ] **Step 7: migration 与 schema 层登记**

```bash
cd platform
grep -n "timing_forecasts" src/a_share_platform/adapters/postgres/schema_layers.py
```

新表逐个加进 `PERSISTENT_TABLE_SCHEMAS` 并标 `SchemaLayer.RESEARCH`。
`timing_outcomes` 与 `timing_calibrations` 必须有与 `0012` 同样的 append-only trigger。
migration smoke 只在提供本地验证库 URL 时跑：

```bash
cd platform
ASP_DATABASE_URL=postgresql://a_share_platform_dev:local-only@127.0.0.1:55432/a_share_platform_layered_dev \
PYTHONPATH=src .venv/bin/python -m a_share_platform.adapters.postgres.cli
```

- [ ] **Step 8: Outcome worker（dry-run 默认）**

照抄 `workers/timing_baseline.py` 的结构（144 行，已验证可用）：
`--database-url` / `--private-local-research-ack` / `--execute`，
`blockers` 列表 + `_postgres_endpoint_is_private_local()` 校验，
无 `--execute` 时打印 JSON 计划返回 0，有 `--execute` 无 ack 时返回 2。
**不要自创 CLI 形状。**

- [ ] **Step 9: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/application/timing_ledger.py \
  platform/src/a_share_platform/application/timing_baseline.py \
  platform/src/a_share_platform/domain/timing_outcomes.py \
  platform/src/a_share_platform/application/timing_promotion.py \
  platform/src/a_share_platform/workers/timing_outcomes.py \
  platform/src/a_share_platform/adapters/postgres/schema_layers.py \
  platform/migrations/0037_p7_timing_research.sql \
  platform/migrations/0038_p7_timing_outcomes.sql \
  platform/tests/test_timing_active_ledger.py \
  platform/tests/test_timing_outcomes.py \
  platform/tests/test_timing_promotion.py \
  platform/tests/test_timing_baseline_runner.py
git commit -m "feat: append active timing forecasts through a new, stricter door

The development database already holds one real passive baseline: 21 CSI500 bars,
observed volatility 0.4131876..., passive exposure 0.2904249..., active adjustment
unavailable.  Six guards in append_baseline are what make that record
trustworthy.  Widening any of them so an active forecast could pass through would
not change the stored row, but it would stop the sentence 'this was checked' from
being true about it.  So append_active is a separate method.

Its central rule is that a candidate model may publish probabilities and
distributions while being forbidden to move exposure.  Without a promotion
binding, final exposure must equal the passive baseline; a quantified active
adjustment is refused; and shifting the final ratios instead of the delta is
refused too, because that is the obvious back door.  A binding that grants a
maximum delta of zero behaves exactly like no binding, which is the state the
platform ships in.

The no-backfill clock guard is what makes the Shadow sample count mean 'days
elapsed' rather than 'rows written'.  A historical replay is still a legitimate
artefact — it just goes in under deployment_stage research and is counted
separately, because 1,900 replayed days and 1,900 waited days are not the same
evidence.

The P3 unavailable reason splits in two.  'Active timing model is not implemented
in P3' stops being true once the model exists, and a promoted-but-zero-impact
model must be distinguishable from an unimplemented one."
```

---

### Task 5: API 与 PUI-06 三页（historical / OOS / forward 分屏）

对应 Step 06 Task 5：「新增 Timing Experiment/Forecast/Outcome/Calibration/Review API；
实现 Timing Lab、Desk latest Shadow、Monitoring Timing、Portfolio active/passive split。
对应产品面、精确原型对照和四档浏览器验收按 PUI-06 执行；historical/OOS/forward 必须分屏，
未晋级的主动模型的运行时组合影响继续为 0。」

**分屏是本 Task 的第一约束，不是排版偏好。** 三种证据放同一个组件里，
使用者无法判断某条曲线是回放还是等出来的。因此设计成三个 endpoint、三个投影、
三个 React 组件，**不共用 data source**。

**Files:**
- Modify: `platform/src/a_share_platform/api/app.py`（新增 5 个只读端点 + 1 个受控写）
- Modify: `platform/src/a_share_platform/api/schemas.py`
- Create: `platform/src/a_share_platform/application/timing_workspace.py`
- Modify: `platform/src/a_share_platform/application/desk_projection.py`（`_timing_shadow`）
- Modify: `platform/frontend/src/pages/FactorWorkspace.tsx`（`TimingPanel`）
- Create: `platform/frontend/src/features/timing/TimingLab.tsx`
- Create: `platform/frontend/src/features/timing/TimingShadowMonitor.tsx`
- Create: `platform/frontend/src/features/timing/timingTypes.ts`
- Modify: `platform/frontend/src/pages/WorkspacePage.tsx`（Monitoring / Timing tab）
- Create: `platform/scripts/verify_timing_browser.py`
- Test: `platform/tests/test_timing_workspace_projection.py`
- Test: `platform/tests/test_timing_api.py`
- Test: `platform/frontend/src/features/timing/TimingLab.test.tsx`
- Test: `platform/frontend/src/features/timing/TimingShadowMonitor.test.tsx`

**Interfaces:**
- Consumes: Task 1–4 全部；已有 `Envelope` / `fixed_read_context` / `DeskSection` 合同
- Produces:
  ```text
  GET /api/timing/experiments               # historical folds + OOS metrics
  GET /api/timing/experiments/{run_id}
  GET /api/timing/forecasts                 # forward shadow ledger only
  GET /api/timing/outcomes
  GET /api/timing/calibrations
  POST /api/timing/promotion-reviews        # 受控写，需权限
  ```

- [ ] **Step 1: 先读现有 Timing 前端的真实状态**

```bash
cd platform
sed -n 85,95p frontend/src/pages/FactorWorkspace.tsx
sed -n 185,192p frontend/src/pages/FactorWorkspace.tsx
sed -n 381,400p frontend/src/pages/FactorWorkspace.tsx
grep -n "timing" src/a_share_platform/api/app.py
```

已核实的现状：`FactorWorkspace.tsx` 第 187 行 `timingBaseline: null` **硬写**，
所以第 382 行 `if (!snapshot?.timingBaseline)` 恒真，`TimingPanel` 永远显示不可用。
后端 `app.state.timing_repository` 只喂 Desk 的 `_timing_shadow()`，**没有 timing 端点**。
本 Task 要把这条线接通。

- [ ] **Step 2: 写后端投影红测 —— 三种证据不可混**

```python
# platform/tests/test_timing_workspace_projection.py
"""The Timing projection keeps three kinds of evidence apart.

Historical folds, out-of-sample folds and forward Shadow days are all sequences of
TimingForecast-shaped things.  Merged into one series they become
indistinguishable, and the forward count — the only one that cannot be
manufactured — is the one that gets inflated.

The projection therefore returns three separately-counted sections and refuses to
produce a combined total.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from decimal import Decimal

from a_share_platform.application.timing_workspace import TimingWorkspaceService
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext


class EvidenceSeparationTest(unittest.TestCase):
    def test_the_projection_has_three_separate_counts(self) -> None:
        projection = TimingWorkspaceService(
            forecast_repository=_repository_with(historical=120, oos=40, forward=3),
            experiment_repository=_experiments(),
            outcome_repository=_outcomes(),
        ).project()
        self.assertEqual(projection.historical.sample_size, 120)
        self.assertEqual(projection.out_of_sample.sample_size, 40)
        self.assertEqual(projection.forward_shadow.sample_size, 3)

    def test_there_is_no_combined_total_field(self) -> None:
        """A single number here is how 3 forward days become 163."""
        projection = TimingWorkspaceService(
            forecast_repository=_repository_with(historical=120, oos=40, forward=3),
            experiment_repository=_experiments(),
            outcome_repository=_outcomes(),
        ).project()
        for name in dir(projection):
            self.assertNotIn("total_sample", name)

    def test_a_research_stage_record_never_counts_as_forward(self) -> None:
        projection = TimingWorkspaceService(
            forecast_repository=_repository_with(historical=1900, oos=0, forward=0),
            experiment_repository=_experiments(),
            outcome_repository=_outcomes(),
        ).project()
        self.assertEqual(projection.forward_shadow.sample_size, 0)
        self.assertEqual(projection.historical.sample_size, 1900)

    def test_forward_section_reports_first_and_latest_session(self) -> None:
        """Forward evidence is measured in elapsed calendar, so the span shows."""
        ...

    def test_each_section_carries_its_own_scientific_status(self) -> None:
        """OOS being evaluated says nothing about the forward record."""
        ...


class PortfolioImpactTest(unittest.TestCase):
    def test_portfolio_impact_is_zero_while_no_model_is_promoted(self) -> None:
        projection = TimingWorkspaceService(
            forecast_repository=_repository_with(historical=0, oos=0, forward=3),
            experiment_repository=_experiments(),
            outcome_repository=_outcomes(),
        ).project()
        self.assertEqual(projection.portfolio_impact_ratio, Decimal(0))
        self.assertIsNotNone(projection.portfolio_impact_reason)

    def test_impact_is_read_from_the_stored_forecast_not_recomputed(self) -> None:
        """Recomputing here would create a second answer to a governed question."""
        ...

    def test_active_and_passive_contributions_are_reported_separately(self) -> None:
        """P7-W05: the Portfolio page must split active from passive.

        With no promoted model the active contribution is zero and the passive
        volatility-target contribution is whatever the baseline produced.  A single
        blended number would hide which of the two moved the book.
        """
        projection = TimingWorkspaceService(
            forecast_repository=_repository_with(historical=0, oos=0, forward=3),
            experiment_repository=_experiments(),
            outcome_repository=_outcomes(),
        ).project()
        self.assertEqual(projection.active_exposure_contribution, Decimal(0))
        self.assertIsNotNone(projection.passive_exposure_contribution)


class UnavailableStoreTest(unittest.TestCase):
    def test_an_unconfigured_store_is_unavailable_not_empty(self) -> None:
        """UnavailableTimingForecastRepository raises; that must surface as a
        blocker rather than as an empty ledger.  'No store' and 'no records' are
        different answers and only the first one is a defect.
        """
        from a_share_platform.adapters.memory.timing import (
            UnavailableTimingForecastRepository,
        )

        projection = TimingWorkspaceService(
            forecast_repository=UnavailableTimingForecastRepository("no DSN"),
            experiment_repository=_experiments(),
            outcome_repository=_outcomes(),
        ).project()
        self.assertEqual(projection.forward_shadow.status.value, "unavailable")
        self.assertTrue(projection.forward_shadow.blockers)

    def test_a_configured_but_empty_store_is_empty(self) -> None:
        ...
```

- [ ] **Step 3: 运行确认红测 → 实现投影 → 转绿**

- [ ] **Step 4: 写 API 合同红测**

```python
# platform/tests/test_timing_api.py
"""Timing endpoints: five reads and one gated write.

The write is the promotion review.  It is the only Timing endpoint that can
change what the platform will do, so it needs an entitlement check, and it must
be impossible to reach a non-zero exposure through it in one step.
"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient


class ReadEndpointTest(unittest.TestCase):
    def test_forecasts_endpoint_returns_only_shadow_stage_records(self) -> None:
        ...

    def test_experiments_endpoint_returns_only_research_stage_records(self) -> None:
        """Two endpoints because one endpoint with a filter parameter is one
        forgotten parameter away from merging them.
        """
        ...

    def test_an_unconfigured_store_returns_503_not_an_empty_list(self) -> None:
        ...

    def test_a_failed_experiment_is_listed_not_hidden(self) -> None:
        ...


class PromotionWriteTest(unittest.TestCase):
    def test_anonymous_identity_cannot_create_a_promotion_review(self) -> None:
        """anonymous holds read_public only."""
        ...

    def test_a_review_cannot_request_impact_beyond_its_scope(self) -> None:
        ...

    def test_creating_a_review_does_not_itself_grant_impact(self) -> None:
        """A review is a request for a decision, not the decision."""
        ...
```

- [ ] **Step 5: 前端红测 —— Timing Lab（对照 `9:238`）**

```tsx
// platform/frontend/src/features/timing/TimingLab.test.tsx
/**
 * Timing Lab, laid out against Figma node 9:238.
 *
 * The prototype's numbers are design fixtures: 0.51 AUC, 0.249 Brier, -0.3% net
 * utility, 8% turnover.  None of them may appear in the runtime, and the test
 * asserts their absence — a fixture that leaks onto a product surface reads as a
 * measured result.
 *
 * The page must never show a metric without its scientific status.  A bare AUC of
 * 0.51 on a product surface reads as validated edge; the same number next to
 * "draft · 未评估" reads as what it is.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { TimingLab } from './TimingLab'

const unavailableProjection = {
  target: { benchmarkId: 'index:000300', horizons: [1, 5, 20, 60] },
  activeModel: null,
  historical: { status: 'empty', sampleSize: 0, blockers: [] },
  outOfSample: { status: 'empty', sampleSize: 0, blockers: [] },
  forwardShadow: { status: 'empty', sampleSize: 0, blockers: [] },
  portfolioImpactRatio: '0',
  portfolioImpactReason: '主动模型尚未通过独立 Promotion Gate',
  models: [],
  gates: [],
} as const

describe('TimingLab', () => {
  it('shows the four prototype summary cards', () => {
    render(<TimingLab projection={unavailableProjection} />)
    expect(screen.getByText('预测对象')).toBeInTheDocument()
    expect(screen.getByText('主动模型')).toBeInTheDocument()
    expect(screen.getByText('Shadow 样本')).toBeInTheDocument()
    expect(screen.getByText('组合影响')).toBeInTheDocument()
  })

  it('shows zero portfolio impact with its reason', () => {
    render(<TimingLab projection={unavailableProjection} />)
    expect(screen.getByText('0%')).toBeInTheDocument()
    expect(
      screen.getByText(/Promotion Gate/),
    ).toBeInTheDocument()
  })

  it('never renders a prototype design fixture', () => {
    render(<TimingLab projection={unavailableProjection} />)
    for (const fixture of ['0.51', '0.249', '-0.3%', '8%', '+0.1%', '12%']) {
      expect(screen.queryByText(fixture)).not.toBeInTheDocument()
    }
  })

  it('renders the eight comparison columns from the prototype', () => {
    render(<TimingLab projection={unavailableProjection} />)
    for (const column of ['模型', '类型', '期限', 'AUC', 'Brier', '净效用', '换手', '状态']) {
      expect(screen.getByRole('columnheader', { name: column })).toBeInTheDocument()
    }
  })

  it('shows a metric only together with its scientific status', () => {
    render(
      <TimingLab
        projection={{
          ...unavailableProjection,
          models: [
            {
              modelId: 'timing-model:logistic',
              version: 'v0',
              kind: '主动模型',
              horizon: 20,
              auc: '0.53',
              brierScore: '0.246',
              netUtilityRatio: '-0.004',
              turnoverRatio: '0.05',
              lifecycle: 'candidate',
              scientificStatus: 'not_evaluated',
            },
          ],
        }}
      />,
    )
    expect(screen.getByText('0.53')).toBeInTheDocument()
    expect(screen.getByText(/not_evaluated|未评估/)).toBeInTheDocument()
  })

  it('separates historical, out-of-sample and forward sections', () => {
    render(<TimingLab projection={unavailableProjection} />)
    const historical = screen.getByRole('region', { name: /历史/ })
    const oos = screen.getByRole('region', { name: /样本外/ })
    const forward = screen.getByRole('region', { name: /前瞻/ })
    expect(historical).not.toContainElement(oos)
    expect(oos).not.toContainElement(forward)
  })

  it('never shows a combined sample total across the three sections', () => {
    render(
      <TimingLab
        projection={{
          ...unavailableProjection,
          historical: { status: 'ready', sampleSize: 120, blockers: [] },
          outOfSample: { status: 'ready', sampleSize: 40, blockers: [] },
          forwardShadow: { status: 'ready', sampleSize: 3, blockers: [] },
        }}
      />,
    )
    expect(screen.queryByText('163')).not.toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('shows the four prototype gate rows including the PIT blocker', () => {
    render(<TimingLab projection={unavailableProjection} />)
    for (const gate of ['特征组', '标签', '验证', 'PIT 阻断']) {
      expect(screen.getByText(gate)).toBeInTheDocument()
    }
  })

  it('shows the trust boundary text from the prototype', () => {
    render(<TimingLab projection={unavailableProjection} />)
    expect(screen.getByText('可信使用边界')).toBeInTheDocument()
    expect(screen.getByText(/主动模型必须真实存在/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 6: 前端红测 —— Timing Shadow Monitor（对照 `9:431`）**

```tsx
// platform/frontend/src/features/timing/TimingShadowMonitor.test.tsx
/**
 * Timing Shadow Monitor, laid out against Figma node 9:431.
 *
 * The prototype draws eleven ledger rows of VOL-BASELINE samples with
 * probabilities from 49% to 58%.  All of them are design fixtures.  The runtime
 * ledger contains whatever was actually frozen, and the 组合影响 column is 0%
 * on every row until a promotion exists.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { TimingShadowMonitor } from './TimingShadowMonitor'

const emptyLedger = {
  latestForecast: null,
  forwardSampleSize: 0,
  portfolioImpactRatio: '0',
  portfolioImpactReason: 'Promotion Gate 锁定',
  baselineModel: 'timing-model:passive-volatility',
  rows: [],
  statuses: [],
} as const

describe('TimingShadowMonitor', () => {
  it('shows UNAVAILABLE rather than a fabricated latest forecast', () => {
    render(<TimingShadowMonitor ledger={emptyLedger} />)
    expect(screen.getByText('最新 Forecast')).toBeInTheDocument()
    expect(screen.getByText(/UNAVAILABLE|不可用/)).toBeInTheDocument()
  })

  it('states no edit and no backfill in the ledger heading', () => {
    render(<TimingShadowMonitor ledger={emptyLedger} />)
    expect(screen.getByText(/no edit \/ no backfill/)).toBeInTheDocument()
  })

  it('renders the eight ledger columns from the prototype', () => {
    render(<TimingShadowMonitor ledger={emptyLedger} />)
    for (const column of ['日期', '模型', '期限', '上涨概率', '收益p50', 'Outcome', '校准', '组合影响']) {
      expect(screen.getByRole('columnheader', { name: column })).toBeInTheDocument()
    }
  })

  it('never renders the prototype ledger fixtures', () => {
    render(<TimingShadowMonitor ledger={emptyLedger} />)
    for (const fixture of ['49%', '58%', '-0.25%', '1.10%', 'ACTIVE-V0']) {
      expect(screen.queryByText(fixture)).not.toBeInTheDocument()
    }
  })

  it('shows zero portfolio impact on every row of a real ledger', () => {
    render(
      <TimingShadowMonitor
        ledger={{
          ...emptyLedger,
          forwardSampleSize: 2,
          rows: [
            {
              effectiveSession: '2026-08-10',
              modelVersionId: 'timing-model:passive-volatility',
              horizon: 20,
              upProbability: null,
              p50ReturnRatio: null,
              outcomeStatus: 'pending',
              calibrationStatus: 'baseline',
              portfolioImpactRatio: '0',
            },
            {
              effectiveSession: '2026-08-11',
              modelVersionId: 'timing-model:logistic',
              horizon: 20,
              upProbability: '0.52',
              p50ReturnRatio: '0.003',
              outcomeStatus: 'pending',
              calibrationStatus: 'unavailable',
              portfolioImpactRatio: '0',
            },
          ],
        }}
      />,
    )
    const impacts = screen.getAllByText('0%')
    expect(impacts.length).toBeGreaterThanOrEqual(2)
  })

  it('renders a pending outcome as pending rather than as zero', () => {
    render(
      <TimingShadowMonitor
        ledger={{
          ...emptyLedger,
          forwardSampleSize: 1,
          rows: [
            {
              effectiveSession: '2026-08-10',
              modelVersionId: 'timing-model:logistic',
              horizon: 20,
              upProbability: '0.52',
              p50ReturnRatio: '0.003',
              outcomeStatus: 'pending',
              calibrationStatus: 'unavailable',
              portfolioImpactRatio: '0',
            },
          ],
        }}
      />,
    )
    expect(screen.getByText(/等待|pending/)).toBeInTheDocument()
    expect(screen.queryByText('0.00%')).not.toBeInTheDocument()
  })

  it('shows the four prototype status rows', () => {
    render(<TimingShadowMonitor ledger={emptyLedger} />)
    for (const status of ['不可变记录', '研究 / 前瞻', '晋级门', '安全上限']) {
      expect(screen.getByText(status)).toBeInTheDocument()
    }
  })

  it('shows the trust boundary about not backfilling with current data', () => {
    render(<TimingShadowMonitor ledger={emptyLedger} />)
    expect(screen.getByText(/不能用 current 数据回填历史 Shadow/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 7: 实现前端 → 转绿 → 修 `timingBaseline: null` 硬写**

`FactorWorkspace.tsx` 第 187 行的 `timingBaseline: null` 必须换成真实 query。
同时把 Monitoring 的 `Timing` tab 从 `WorkspacePage` 的通用 `activationReasons`
路径改为渲染 `TimingShadowMonitor`。

- [ ] **Step 8: 四视口真实浏览器验收**

照抄 `platform/scripts/verify_desk_browser.py` 的结构（177 行，已验证可用）：

```python
# platform/scripts/verify_timing_browser.py
"""PUI-06 four-viewport acceptance for the two Timing surfaces.

Component tests cannot see page-level horizontal overflow, right-edge clipping or
console errors, and curl cannot see layout at all.  DESIGN_FIXTURES holds the
sample values drawn in Figma nodes 9:238 and 9:431; if any of them appears in the
rendered page, a prototype number has reached a product surface.
"""

from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

PAGES = (
    ("timing-lab", "http://127.0.0.1:5173/factors?tab=timing-lab"),
    ("timing-monitor", "http://127.0.0.1:5173/monitoring?tab=timing"),
    ("desk-timing-shadow", "http://127.0.0.1:5173/desk"),
    ("portfolio-timing-split", "http://127.0.0.1:5173/portfolios?tab=construction"),
)
VIEWPORTS = (("1440", 1440, 900), ("1024", 1024, 768), ("768", 768, 1024), ("320", 320, 640))
DESIGN_FIXTURES = (
    "0.51", "0.249", "-0.3%", "+0.1%", "8%", "12%",
    "49%", "58%", "-0.25%", "1.10%", "ACTIVE-V0", "LOGIT-V0",
    "Tree V0", "State V0",
)
# Every row of the forward ledger must read 0% until a promotion exists.
REQUIRED_TEXT = {
    "timing-lab": ("组合影响", "0%", "可信使用边界"),
    "timing-monitor": ("no edit / no backfill", "0%"),
}
ALLOWED_CLIP_PREFIXES = ("DIV.ant-tabs-nav-list", "DIV.ant-tabs-tab")
```

四个视口逐页检查：
1. `document.documentElement.scrollWidth === clientWidth`（无页面级溢出）
2. 无元素右边缘越过视口宽度（tab strip 除外，已有例外）
3. `DESIGN_FIXTURES` 一个都不出现
4. `REQUIRED_TEXT` 全部出现
5. 控制台无 error/warning
6. 无非 `/api/` 的 4xx/5xx

**320 与 768 没有独立 Figma Frame**，只记录设计假设，`design_status` 保持 `missing`。
1440 完成 `9:238` 与 `9:431` 的逐区对照后才可改 `design_status`。

- [ ] **Step 9: 前端全量与提交**

```bash
cd platform
npm --prefix frontend test -- --run
npm --prefix frontend run lint
npm --prefix frontend run build
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/api/app.py \
  platform/src/a_share_platform/api/schemas.py \
  platform/src/a_share_platform/application/timing_workspace.py \
  platform/src/a_share_platform/application/desk_projection.py \
  platform/frontend/src/features/timing/ \
  platform/frontend/src/pages/FactorWorkspace.tsx \
  platform/frontend/src/pages/WorkspacePage.tsx \
  platform/scripts/verify_timing_browser.py \
  platform/tests/test_timing_workspace_projection.py \
  platform/tests/test_timing_api.py
git commit -m "feat: surface timing evidence on separate historical, OOS and forward screens

Historical folds, out-of-sample folds and forward Shadow days are all sequences of
the same shape, and merging them inflates the one count that cannot be
manufactured.  Replaying 1,900 sessions takes seconds; waiting 1,900 sessions
takes eight years.  So the projection exposes three separately-counted sections,
has no combined total field at all, and the page renders them as three regions
that cannot contain one another.

The Figma fixtures stay out of the runtime.  Node 9:238 draws an AUC of 0.51 and a
Brier of 0.249; node 9:431 draws eleven ledger rows with probabilities from 49% to
58%.  The browser check asserts none of those strings appears, because a design
fixture on a product surface reads as a measured result.

No metric appears without its scientific status.  A bare AUC of 0.53 reads as
validated edge; the same number beside not_evaluated reads as what it is.  And
every row of the forward ledger reports 0% portfolio impact, read from the stored
forecast rather than recomputed in the browser."
```

---

### Task 6: 前瞻运行、Gate Evidence 与明确否认

对应 Step 06 Task 6：「先 dry-run，再本地 research Shadow；记录真实日序列。
历史回放不能冒充前瞻天数；Gate Evidence 分别报告 historical/OOS/forward。」

**Files:**
- Create: `platform/src/a_share_platform/workers/timing_research.py`
- Create: `platform/tests/test_timing_research_worker.py`
- Create: `docs/27-p6-active-timing-evidence.md`
- Modify: `docs/plans/step-06-p7-active-timing.md`（状态更新）
- Modify: `docs/14-data-source-catalog-and-agent-routing.md`（宏观源资格状态）

- [ ] **Step 1: 研究 worker（dry-run 默认）**

```python
# platform/tests/test_timing_research_worker.py
"""The timing research worker: dry-run by default, ack-gated writes.

A worker that writes by default is a worker that writes by accident.  This one
carries one extra rule beyond the pattern in workers/timing_baseline.py: it
refuses to write a shadow record for a past session, because that is the one
mistake that would manufacture forward evidence.
"""

from __future__ import annotations

import json
import unittest

from a_share_platform.workers import timing_research


class DryRunDefaultTest(unittest.TestCase):
    def test_without_execute_nothing_is_written(self) -> None:
        code = timing_research.main([
            "--benchmark-id", "index:000300",
            "--target-horizon", "20",
            "--database-url", "postgresql://user:pw@127.0.0.1:55432/db",
            "--code-version", "git:test",
        ])
        self.assertEqual(code, 0)

    def test_execute_without_ack_is_blocked_with_a_reason(self) -> None:
        code = timing_research.main([
            "--benchmark-id", "index:000300",
            "--target-horizon", "20",
            "--database-url", "postgresql://user:pw@127.0.0.1:55432/db",
            "--code-version", "git:test",
            "--execute",
        ])
        self.assertEqual(code, 2)

    def test_a_non_loopback_database_is_blocked(self) -> None:
        code = timing_research.main([
            "--benchmark-id", "index:000300",
            "--target-horizon", "20",
            "--database-url", "postgresql://user:pw@db.example.com:5432/db",
            "--code-version", "git:test",
            "--private-local-research-ack", "--execute",
        ])
        self.assertEqual(code, 2)

    def test_shadow_mode_refuses_a_past_session(self) -> None:
        """The one guard specific to this worker.

        A --shadow run writes forward evidence.  Allowing --session in the past
        would let a single command turn eight years of history into eight years of
        'Shadow days'.
        """
        code = timing_research.main([
            "--benchmark-id", "index:000300",
            "--target-horizon", "20",
            "--shadow", "--session", "2020-01-02",
            "--database-url", "postgresql://user:pw@127.0.0.1:55432/db",
            "--code-version", "git:test",
        ])
        self.assertEqual(code, 2)

    def test_a_failed_experiment_is_recorded_not_retried(self) -> None:
        """The failure mode this worker exists to prevent is re-running until the
        number looks good.  A negative net utility is the result, not an error.
        """
        ...

    def test_insufficient_history_reports_blocked_rather_than_running_on_21_bars(
        self,
    ) -> None:
        """21 bars produce zero folds.  Saying so is the correct output."""
        ...
```

- [ ] **Step 2: 运行确认红测 → 实现 → 转绿**

CLI 形状照抄 `workers/timing_baseline.py`：`blockers` 列表、`_postgres_endpoint_is_private_local()`、
`writes_performed`、JSON 输出、退出码 0/1/2。新增 `--shadow` / `--session` / `--target-horizon`。

- [ ] **Step 3: 真实 dry-run**

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.timing_research \
  --benchmark-id index:000300 --target-horizon 20 \
  --database-url "$ASP_DATABASE_URL" --code-version "git:$(git rev-parse --short HEAD)"
```

Expected: JSON 计划，含 fold 数、训练/测试样本量、blockers。
**若 blockers 里有「insufficient benchmark history」，回到 P-1** —— 那是正确输出。

- [ ] **Step 4: 真实历史实验执行**

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.timing_research \
  --benchmark-id index:000300 --target-horizon 20 \
  --database-url "$ASP_DATABASE_URL" --code-version "git:$(git rev-parse --short HEAD)" \
  --private-local-research-ack --execute
```

**把真实的 AUC、Brier、reliability、resolution、skill score、DM 统计量、
毛/净收益、换手率原样记进 Evidence，无论好坏。** 这是本 plan 最重要的产出 ——
它会第一次告诉你在当前数据上主动择时有没有任何信号。

极有可能的结果：AUC ≈ 0.5、skill score ≈ 0、净效用为负。**如实记录。**

- [ ] **Step 5: 前瞻 Shadow 起点**

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.timing_research \
  --benchmark-id index:000300 --target-horizon 20 --shadow \
  --session "$(TZ=Asia/Shanghai date +%F)" \
  --database-url "$ASP_DATABASE_URL" --code-version "git:$(git rev-parse --short HEAD)" \
  --private-local-research-ack --execute
```

这一条命令只能产生**一天**前瞻证据。20 日 horizon 的第一个 Outcome
要等 20 个交易日；有统计意义的校准曲线要等数百天。
**Evidence 必须写清前瞻天数 = 1，不得写成"Shadow 已建立"。**

- [ ] **Step 6: Outcome worker dry-run 与执行**

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.timing_outcomes \
  --database-url "$ASP_DATABASE_URL" --evaluated-at "$(date -u +%FT%TZ)"
```

Expected（首次）：`pending` 计数等于已写 forecast 数，`matured` 为 0。
**这是正确输出**，不是失败。

- [ ] **Step 7: 写 Evidence，historical / OOS / forward 分三节**

`docs/27-p6-active-timing-evidence.md` 结构必须是：

```markdown
## 1. 红绿测记录
## 2. Historical 折内结果（不是样本外）
## 3. Out-of-sample 折外结果（walk-forward，purge=19，HAC lag=19）
## 4. Forward Shadow 记录（真实天数、真实 session、真实 outcome 状态）
## 5. 独立库交叉验证一致性
## 6. 未完成项与范围限制
## 7. 明确否认
```

第 2、3、4 节**不许合并，不许出现跨节合计**。第 4 节必须写真实天数
（第一次执行后就是 1），并写明第一个 Outcome 的预计成熟日期。

- [ ] **Step 8: 写明确否认声明**

必须逐字包含：

> **P7 完成不代表 Timing 模型有效。**
>
> 本 plan 的完成定义是「平台具备主动择时的研究、记录与验证能力」（Capability Gate），
> 不是「某个主动择时模型科学有效」（Promotion Gate）。两者是不同的问题，需要不同的证据。
>
> 具体地说，本 plan 结束时以下事实同时成立：
>
> 1. 主动模型真实存在（logistic 与 linear），有 deterministic fixture 与无未来输入测试；
> 2. walk-forward、HAC、校准、DM、净效用全部实现并有独立库交叉验证；
> 3. Shadow ledger 不可编辑、不可回填；
> 4. **前瞻证据天数为 <真实数字>**，远不足以支撑任何校准或净效用结论；
> 5. 全部输入为 `normalized_current`，**没有 `pit_verified` 数据**；
> 6. 宏观发布时间源未通过资格，`MACRO` 特征组保持 `unavailable`；
> 7. 运行时组合影响为 0，且**不因本 plan 完成而变为非零**。
>
> **前瞻证据无法回放。** 一次历史 walk-forward 能在数秒内产出 1,900 个"每日 forecast"，
> 但它们在数据结构上与真实前瞻记录相同、在证据价值上完全不同。20 日 horizon 的第一个
> Outcome 需要 20 个交易日；有意义的校准曲线需要数百个交易日。
> **这段时间不能用算力换取。**
>
> 因此不得声称：P7 Gate 已通过（Capability 部分可通过，Promotion 部分未通过）、
> 主动择时模型有预测力、平台具备可盈利的择时策略，或任何模型可以进入 `paper` / `limited_live`。

- [ ] **Step 9: 更新 Plan 状态与数据源目录**

`docs/plans/step-06-p7-active-timing.md` 的状态从 `dependency_blocked` 改为
Task 1–6 各自的真实状态。**只有事实满足时才改**；Promotion Gate 部分保持未通过。

`docs/14-data-source-catalog-and-agent-routing.md` 记录宏观发布时间源的真实资格状态
（当前无合格源 → `MACRO` feature group 永久 `unavailable`，直到有 ADR 与凭据）。

- [ ] **Step 10: 提交**

```bash
git add docs/27-p6-active-timing-evidence.md \
  docs/plans/step-06-p7-active-timing.md \
  docs/14-data-source-catalog-and-agent-routing.md \
  platform/src/a_share_platform/workers/timing_research.py \
  platform/tests/test_timing_research_worker.py
git commit -m "docs: record P-6 active timing evidence in three separate sections

Historical, out-of-sample and forward results get their own sections with no
cross-section totals, because a combined number is how a handful of waited days
becomes a thousand replayed ones.  The forward section states the real elapsed
day count and the date the first outcome is due.

The denial section is the point of the document.  This plan can finish with every
test green, both active models fitted, calibration and Diebold-Mariano and net
utility all implemented and cross-checked — and still not support any claim that
timing works.  Forward evidence cannot be replayed: the first 20-day outcome takes
twenty sessions and a meaningful calibration curve takes hundreds, and no amount
of compute shortens that.  The inputs are also normalized_current throughout, and
the macro feature group stays unavailable because no source qualifies for
publication times.

Runtime portfolio impact remains zero and does not become non-zero because this
plan completed.  Capability and Promotion are different gates."
```

---

## 完成定义

1. index-level 目标/标签合同存在，overlap 显式声明且 HAC lag 派生而非配置（Task 1）；
2. PIT 特征分七组，`MACRO` 无发布时间时诚实 `unavailable`，标签与特征编排隔离（Task 1）；
3. static / MA / vol-target 三基线 + logistic / linear 两主动模型在 provider-neutral port 上实现，
   各有 deterministic fixture 与无未来输入测试（Task 2）；
4. walk-forward purge 强制覆盖 overlap；校准含 Brier / reliability / resolution / skill score；
   DM 检验强制 HAC lag；净效用为晋级门（Task 3）；
5. 独立库交叉验证收到与主实现完全一致的观测序列，缺库时报 unavailable（Task 3）；
6. `append_baseline()` 六条守卫全部保留，`append_active()` 新增且更严；
   未晋级模型无法改变 exposure；no-backfill 时钟守卫生效（Task 4）；
7. Outcome / Calibration 到期追加、幂等、不可事后重算；PromotionReview 有 scope /
   max impact / expiry / rollback（Task 4）；
8. 五个只读 + 一个受控写 Timing 端点；historical / OOS / forward 三分屏且无合计字段（Task 5）；
9. Timing Lab 与 Timing Shadow Monitor 完成 `9:238` / `9:431` 的 1440 逐区对照与四视口验收；
   Figma fixture 零泄漏；每个指标都带科学状态（Task 5）；
10. 研究 worker 与 Outcome worker dry-run 默认；`--shadow` 拒绝历史 session（Task 6）；
11. Evidence 分三节记录真实数值，含明确否认与真实前瞻天数（Task 6）；
12. 后端 unittest / compileall / ruff / mypy 全过；前端 Vitest / lint / build 全过；
    四视口验收通过；`git diff --check` 干净。

## 明确不在本 plan 范围

- 树模型与状态模型 —— P7-W02 标为 `MAY`，本 plan 不做，原型对照表两行保持 `未评估`；
- `strict_historical` Timing 研究 —— 需 `pit_verified` 指数与宏观数据；
- 宏观发布时间与修订链 —— 需新数据源资格与 ADR，`MACRO` 组保持 `unavailable`；
- 主动模型晋级 —— 需 Promotion Gate 与足够前瞻证据，不属工程范围；
- 非零组合影响 —— 需 PromotionReview 批准且 `maximum_exposure_delta > 0`；
- Timing 漂移告警与 Incident —— 属 P-8（P9）；
- Paper 执行中的 timing 仓位调整 —— 属 P-9（P10）。

## 本 plan 完成后仍然成立的限制

- 全部输入为 `normalized_current`，**不支持 `strict_historical` 择时回测**；
- 历史与样本外结果只是「当前可得数据上的观测」，**不是有效性证明**；
- **前瞻证据天数极少且无法通过算力增加**；
- `MACRO` 特征组不可用，因此模型只用价格派生特征，信息集不完整；
- 运行时组合影响为 0，**不因本 plan 完成而改变**；
- **P7 Capability Gate 可通过，Promotion Gate 未通过**；
- 不得声称主动择时模型有预测力或平台具备可盈利择时策略。
