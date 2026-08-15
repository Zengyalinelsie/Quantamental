# P-2 因子研究编排实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立从已入库财务事实到真实 IC/RankIC 的编排层，使质量、估值、改善三类因子在 CSI300/CSI500 上产出可追溯的真实分数与统计量。

**Architecture:** 全部数学**已经存在且经代码审计确认可在 `current_research` 模式下运行**。本 plan 只建编排层：把财务事实喂给已有纯函数，把分数与标签拼成 `CrossSectionObservation`，调用已有 `information_coefficient()`，把结果写入已有 `ExperimentRun` 账本。**不新建任何数学**。

**Tech Stack:** Python 3.11+、已有 `domain/quality_factor.py` / `fundamental_improvement.py` / `valuation_models.py` / `factor_statistics.py` / `factor_panel_statistics.py` / `labels.py`、scipy + statsmodels（交叉验证）

## Global Constraints

继承 `AGENTS.md` 与已接受 ADR，**每个 Task 都适用**：

- `domain/` 不导入 FastAPI / SQLAlchemy / provider SDK / 前端概念
- **编排层不得重新实现任何数学** —— 只做数据搬运与状态传递
- `RunContext` 固定 `(current_research, research)`；构造 `strict_historical` 必须失败关闭
- **缺失、不可比、不可用必须显式表达，禁止填零**
- 权重来自版本化定义对象，**不得硬编码在编排代码里**
- 产出的 `FactorVersion` 保持 `draft`，**不申请 promotion，不进入任何 approval scope**
- 独立库交叉验证的输入必须与主统计器**完全一致**（同一份 observation 序列）
- **IC 为负或接近零时照实记录，不重跑、不改窗口、不筛样本**
- 失败 Experiment 不可删除或改写为成功
- worker 默认 dry-run，真实写入需显式 ack
- 未经用户明确授权不 commit、不 push

## 前置条件

P-1 必须完成，特别是：

- `observation.market_data_partitions` 非零（否则无标签）
- `canonical.universe_versions` 跨多个观测日（否则无历史截面）
- 日度交易状态可用（否则标签的 `tradable` 靠猜）

用 P-1 Task 7 的就绪度 Gate 校验：

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m unittest tests.test_data_readiness_gate -v
```

## 已存在的接口（本 plan 消费，不重建）

经 2026-08-16 逐文件核实的真实签名：

```text
# domain/quality_factor.py
QualityComponentInput(feature_id, value, unit, period, resolved_feature)
definition.calculate(values: Mapping[str, QualityComponentInput], *,
                     exposures: QualityFactorExposures) -> QualityFactorResult

# domain/fundamental_improvement.py — data_mode 门禁只拦 strict_historical
definition.calculate(values, *, exposures, data_mode=DataMode.CURRENT_RESEARCH)

# domain/valuation_models.py
RelativeValuationModelV0 / FundamentalAnchorModelV0 / ImpliedExpectationModelV0
# AnalystRevisionModelV0 需要 AnalystSourceAttestation —— 本 plan 不用

# domain/labels.py（2026-08-15 新增）
ForwardReturnLabelDefinition(label_id, version, horizon, adjustment,
                             data_mode, trust_state)
definition.calculate(*, decision_session: date,
                     prices: tuple[LabelPriceInput, ...]) -> ForwardReturnObservation

# domain/factor_statistics.py
CrossSectionObservation(entity_id, score, forward_return, score_version_id,
    label_version_id, data_mode, score_trust_state, label_trust_state,
    decision_time, score_available_at, label_outcome_at, missing_reason=None)
CorrelationSpec(kind, minimum_sample_size, formula_version, rank_version)
information_coefficient(observations, *, spec, data_mode) -> CorrelationResult
# CorrelationResult 含 status/value/sample_size/missing_count/historical_eligible/
# scientific_status/warnings/unavailable_reason

# domain/factor_panel_statistics.py
fama_macbeth(...)  # 逐期 + 聚合推断
regime_subperiod_robustness(...)

# validation/statistical_crosscheck.py
cross_check_information_coefficient(...)  # scipy
cross_check_fama_macbeth(...)             # statsmodels
cross_check_newey_west_mean(...)          # statsmodels
```

---

### Task 1: 特征输入编排（财务事实 → 三维度输入）

**Files:**
- Create: `platform/src/a_share_platform/application/factor_features.py`
- Test: `platform/tests/test_factor_features.py`

**Interfaces:**
- Consumes: `ports/financial_facts.py` 的读接口、`domain/quality_factor.py`、`domain/fundamental_improvement.py`
- Produces:
  ```python
  class FactorFeatureOrchestrator:
      def build_quality_inputs(self, *, security_id: str, decision_time: datetime
          ) -> dict[str, QualityComponentInput]
      def build_improvement_inputs(self, *, security_id: str, decision_time: datetime
          ) -> dict[str, ImprovementComponentInput]
      def unavailable_reasons(self) -> tuple[str, ...]
  ```

- [ ] **Step 1: 读真实财务事实读接口**

```bash
cd platform
grep -n "class \|def " src/a_share_platform/ports/financial_facts.py
grep -n "class ImprovementComponentInput" -A20 src/a_share_platform/domain/fundamental_improvement.py
grep -n "class ResolvedTemplateFeature" -A14 src/a_share_platform/domain/industry_templates.py
```

**以代码为准。** 若字段名与本 plan 不同，改本 plan 的后续步骤，不要改领域代码去迁就 plan。

- [ ] **Step 2: 写失败测试**

```python
# platform/tests/test_factor_features.py
"""Financial facts to factor model inputs.

The orchestrator only moves data and carries status forward.  It must not
compute a ratio, fill a gap, or upgrade a trust state — those all belong to the
domain functions it feeds.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from a_share_platform.application.factor_features import FactorFeatureOrchestrator
from a_share_platform.domain.run_context import DataMode

DECISION = datetime(2025, 12, 31, 8, 0, tzinfo=UTC)


class FakeFinancialFacts:
    """Minimal reader; returns whatever the test hands it."""

    def __init__(self, facts: dict[str, object] | None = None) -> None:
        self._facts = facts or {}
        self.calls: list[str] = []

    def latest_for(self, *, security_id: str, as_of: datetime) -> dict[str, object]:
        self.calls.append(security_id)
        return self._facts


class QualityInputOrchestrationTest(unittest.TestCase):
    def test_missing_facts_yield_no_inputs_and_an_explicit_reason(self) -> None:
        orchestrator = FactorFeatureOrchestrator(
            financial_facts=FakeFinancialFacts({}),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        inputs = orchestrator.build_quality_inputs(
            security_id="security:CN:600519:XSHG", decision_time=DECISION
        )
        self.assertEqual(inputs, {})
        self.assertTrue(orchestrator.unavailable_reasons())

    def test_strict_historical_is_refused(self) -> None:
        """This track is current-only; strict inputs need pit_verified facts."""
        with self.assertRaises(PermissionError):
            FactorFeatureOrchestrator(
                financial_facts=FakeFinancialFacts({}),
                data_mode=DataMode.STRICT_HISTORICAL,
            )

    def test_orchestrator_reads_but_never_computes(self) -> None:
        """A ratio computed here would be a second source of truth."""
        reader = FakeFinancialFacts({})
        orchestrator = FactorFeatureOrchestrator(
            financial_facts=reader, data_mode=DataMode.CURRENT_RESEARCH
        )
        orchestrator.build_quality_inputs(
            security_id="security:CN:600519:XSHG", decision_time=DECISION
        )
        self.assertEqual(reader.calls, ["security:CN:600519:XSHG"])
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_factor_features -v`
Expected: FAIL —— `application.factor_features` 不存在。抄真实错误进 Evidence。

- [ ] **Step 4: 最小实现**

只实现 `__init__` 的 `strict_historical` 拒绝 + 空事实返回空输入 + 记录原因。
**不要**一次写完所有维度。

- [ ] **Step 5: 转绿**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_factor_features -v`
Expected: PASS

- [ ] **Step 6: 逐维度补齐（每维度先红测再实现）**

顺序：质量 → 改善 → 估值。每个维度至少覆盖：
- 完整事实 → 完整输入
- 部分字段缺失 → 该分项 `unavailable` 且带原因，**其余分项继续**
- 单位或币种不一致 → 拒绝，不静默换算

- [ ] **Step 7: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/application/factor_features.py \
  platform/tests/test_factor_features.py
git commit -m "feat: orchestrate financial facts into factor model inputs

The maths for quality, improvement and valuation already exists and is ungated
in current_research mode; what was missing is the layer that feeds it.  This
orchestrator only moves data and carries status forward: computing a ratio here
would create a second source of truth for a governed number.

A missing field makes one component unavailable with a reason while the others
continue, and strict_historical is refused outright since it needs pit_verified
facts."
```

---

### Task 2: 因子分数与截面排名

**Files:**
- Create: `platform/src/a_share_platform/domain/factor_scoring.py`（版本化定义对象）
- Create: `platform/src/a_share_platform/application/factor_scoring.py`（编排）
- Test: `platform/tests/test_factor_scoring.py`

**Interfaces:**
- Consumes: Task 1 的三维度结果、`domain/feature_transforms.py`
- Produces:
  ```python
  @dataclass(frozen=True)
  class FactorScoreDefinition:
      definition_id: str
      version: str
      weights: Mapping[str, Decimal]       # 维度名 → 权重，和为 1
      missing_policy: MissingDimensionPolicy
      content_hash: str                    # init=False

  class MissingDimensionPolicy(StrEnum):
      RENORMALISE = "renormalise"          # 剩余维度重新归一
      UNAVAILABLE = "unavailable"          # 整体不可用

  def score_cross_section(rows, *, definition) -> tuple[FactorScoreRow, ...]
  ```

- [ ] **Step 1: 写失败测试 —— 权重来自定义而非硬编码**

```python
# platform/tests/test_factor_scoring.py
"""Composite factor score from the three dimensions.

Weights live in a versioned, content-addressed definition rather than in the
orchestration code, so a change of weighting is a change of version with its own
hash — otherwise two runs with different weights would be indistinguishable.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from a_share_platform.domain.factor_scoring import (
    FactorScoreDefinition,
    MissingDimensionPolicy,
)


def definition(
    policy: MissingDimensionPolicy = MissingDimensionPolicy.UNAVAILABLE,
) -> FactorScoreDefinition:
    return FactorScoreDefinition(
        definition_id="factor.composite",
        version="v0",
        weights={
            "quality": Decimal("0.4"),
            "valuation": Decimal("0.3"),
            "improvement": Decimal("0.3"),
        },
        missing_policy=policy,
    )


class DefinitionContractTest(unittest.TestCase):
    def test_definition_is_content_addressed(self) -> None:
        self.assertEqual(definition().content_hash, definition().content_hash)
        self.assertEqual(len(definition().content_hash), 64)

    def test_weights_must_sum_to_one(self) -> None:
        with self.assertRaises(ValueError):
            FactorScoreDefinition(
                definition_id="factor.composite",
                version="v0",
                weights={"quality": Decimal("0.5"), "valuation": Decimal("0.2")},
                missing_policy=MissingDimensionPolicy.UNAVAILABLE,
            )

    def test_different_weights_change_the_hash(self) -> None:
        other = FactorScoreDefinition(
            definition_id="factor.composite",
            version="v1",
            weights={
                "quality": Decimal("0.5"),
                "valuation": Decimal("0.25"),
                "improvement": Decimal("0.25"),
            },
            missing_policy=MissingDimensionPolicy.UNAVAILABLE,
        )
        self.assertNotEqual(definition().content_hash, other.content_hash)

    def test_negative_weight_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            FactorScoreDefinition(
                definition_id="factor.composite",
                version="v0",
                weights={
                    "quality": Decimal("1.2"),
                    "valuation": Decimal("-0.2"),
                    "improvement": Decimal("0"),
                },
                missing_policy=MissingDimensionPolicy.UNAVAILABLE,
            )
```

- [ ] **Step 2: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_factor_scoring -v`
Expected: FAIL —— 模块不存在。

- [ ] **Step 3: 实现定义对象**

- [ ] **Step 4: 补缺失维度策略测试再实现**

```python
class MissingDimensionPolicyTest(unittest.TestCase):
    def test_unavailable_policy_makes_the_whole_score_unavailable(self) -> None:
        """Default is conservative: an incomplete score is not a score."""
        # 断言：任一维度缺失 → 该行 score 为 None 且带原因，不是部分分数

    def test_renormalise_policy_records_which_dimensions_were_dropped(self) -> None:
        """Renormalising silently would hide that the score means something else."""
        # 断言：重新归一后必须记录被丢弃的维度名与新权重
```

**默认策略必须是 `UNAVAILABLE`** —— 不完整的分数不是分数。`RENORMALISE` 只在显式选择时启用，
且必须记录被丢弃的维度。

- [ ] **Step 5: 截面排名（复用 feature_transforms）**

```bash
cd platform
grep -n "^def \|^class " src/a_share_platform/domain/feature_transforms.py
```

排名必须：稳定（同输入同输出）、可复现、`content_hash` 覆盖全部输入。
**不可用的行不参与排名，也不排在末位** —— 那会被误读为"最差"。

- [ ] **Step 6: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/domain/factor_scoring.py \
  platform/src/a_share_platform/application/factor_scoring.py \
  platform/tests/test_factor_scoring.py
git commit -m "feat: add versioned composite factor scoring and cross-section ranking

Weights live in a content-addressed definition, so changing them changes the
version hash: two runs with different weightings can never be confused.

The default missing-dimension policy is UNAVAILABLE rather than renormalise,
because an incomplete score is not a score.  Renormalising is available but must
record which dimensions were dropped, otherwise the number silently means
something other than what it claims.  Unavailable rows do not rank last — that
would read as 'worst' rather than 'unknown'."
```

---

### Task 3: 标签数据集生成（把 P-1 行情变成标签）

**Files:**
- Create: `platform/src/a_share_platform/application/label_datasets.py`
- Test: `platform/tests/test_label_datasets.py`

**Interfaces:**
- Consumes: `domain/labels.py`（已实现）、Parquet 行情读取、`observation.daily_market_states`
- Produces:
  ```python
  class LabelDatasetBuilder:
      def build(self, *, definition: ForwardReturnLabelDefinition,
                universe_version_id: str, decision_sessions: tuple[date, ...]
                ) -> LabelDataset   # 含 observations + coverage + dataset_version_id
  ```

- [ ] **Step 1: 读 Parquet 行情读取接口**

```bash
cd platform
grep -n "^class \|def read\|def query" src/a_share_platform/adapters/parquet/market_data.py | head -20
```

- [ ] **Step 2: 写失败测试**

```python
# platform/tests/test_label_datasets.py
"""Turn real bars into a versioned label dataset.

Coverage is reported, not assumed: a security whose window runs past the end of
history yields an unavailable observation with a reason, and the dataset states
how many of those there were.  A dataset that silently drops them would overstate
its own completeness.
"""

from __future__ import annotations

import unittest
from datetime import date

from a_share_platform.application.label_datasets import LabelDatasetBuilder


class CoverageReportingTest(unittest.TestCase):
    def test_dataset_reports_unavailable_count_rather_than_dropping_rows(self) -> None:
        # 5 securities, 2 of which lack a full forward window.
        # Expect: 5 observations, 3 quantified, 2 unavailable with reasons.
        ...

    def test_empty_universe_yields_an_empty_dataset_not_an_error(self) -> None:
        ...

    def test_dataset_version_id_covers_definition_and_universe(self) -> None:
        """Two datasets from different label versions must not share an id."""
        ...
```

补全断言时用真实读取接口构造 fake，**不要联网**。

- [ ] **Step 3: 运行确认红测 → 实现 → 转绿**

每个断言先红后绿，不要批量实现。

- [ ] **Step 4: 用真实数据跑一次（需 P-1 完成）**

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python - <<'PY'
# Build 20-session labels for one real universe version and print coverage.
# Replace the reader construction with the real Parquet adapter API.
print("run after P-1 Task 2 completes")
PY
```

真实覆盖率必须记录到 Evidence。**若覆盖率很低，如实记录并查明原因，不要调窗口凑数。**

- [ ] **Step 5: 提交**

```bash
cd .. && git add platform/src/a_share_platform/application/label_datasets.py \
  platform/tests/test_label_datasets.py
git commit -m "feat: build versioned forward-return label datasets from real bars

Coverage is reported rather than assumed: a security whose forward window runs
past the end of history yields an unavailable observation with a reason, and the
dataset states how many.  Dropping those rows silently would overstate the
dataset's completeness and bias every statistic computed from it."
```

---

### Task 4: IC / RankIC 实跑与独立库交叉验证

**Files:**
- Create: `platform/src/a_share_platform/application/factor_evaluation.py`
- Test: `platform/tests/test_factor_evaluation.py`

**Interfaces:**
- Consumes: Task 2 的分数、Task 3 的标签、`domain/factor_statistics.py`、`validation/statistical_crosscheck.py`
- Produces:
  ```python
  class FactorEvaluationService:
      def evaluate(self, *, scores, labels, spec: CorrelationSpec
                   ) -> FactorEvaluationResult
      # FactorEvaluationResult 含 CorrelationResult + 交叉验证报告 + 观测计数
  ```

- [ ] **Step 1: 写失败测试 —— 分数与标签的对齐**

```python
# platform/tests/test_factor_evaluation.py
"""Join scores to labels and compute IC through the existing statistics engine.

The join is where look-ahead leaks in, so it is tested directly: a label whose
outcome time precedes the score's availability must be refused rather than
quietly included.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from a_share_platform.application.factor_evaluation import FactorEvaluationService
from a_share_platform.domain.factor_statistics import CorrelationKind, CorrelationSpec
from a_share_platform.domain.run_context import DataMode


def spec(kind: CorrelationKind = CorrelationKind.SPEARMAN) -> CorrelationSpec:
    return CorrelationSpec(
        kind=kind,
        minimum_sample_size=3,
        formula_version="v0",
        rank_version="average" if kind is CorrelationKind.SPEARMAN else None,
    )


class LookAheadGuardTest(unittest.TestCase):
    def test_label_outcome_before_score_availability_is_refused(self) -> None:
        """This is the one bug that silently invents skill."""
        service = FactorEvaluationService(data_mode=DataMode.CURRENT_RESEARCH)
        with self.assertRaises(ValueError):
            service.evaluate(
                scores=[_score(available_at=datetime(2025, 6, 30, tzinfo=UTC))],
                labels=[_label(outcome_at=datetime(2025, 6, 1, tzinfo=UTC))],
                spec=spec(),
            )

    def test_unmatched_entities_are_counted_not_dropped(self) -> None:
        """missing_count must reflect reality for the sample-size gate to work."""
        ...

    def test_below_minimum_sample_size_reports_unavailable_not_a_number(self) -> None:
        ...


class CrossCheckTest(unittest.TestCase):
    def test_independent_library_sees_the_identical_observation_sequence(self) -> None:
        """A cross-check on different inputs proves nothing."""
        ...

    def test_cross_check_unavailable_when_scipy_is_absent(self) -> None:
        """Absence of the library must not read as agreement."""
        ...
```

- [ ] **Step 2: 运行确认红测 → 实现 → 转绿**

- [ ] **Step 3: 用真实数据跑真实 IC**

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.factor_research \
  --universe-version <真实 id> --horizon 20 --dry-run
```

（worker 在 Task 5 建立；此步在 Task 5 后回来执行。）

- [ ] **Step 4: 提交**

```bash
cd .. && git add platform/src/a_share_platform/application/factor_evaluation.py \
  platform/tests/test_factor_evaluation.py
git commit -m "feat: evaluate factor IC through the existing statistics engine

The score-to-label join is where look-ahead leaks in, so it is guarded
directly: a label whose outcome time precedes the score's availability is
refused rather than quietly included.  That single bug is what silently invents
skill in a backtest.

Unmatched entities are counted rather than dropped, because the sample-size gate
is only meaningful if missing_count reflects reality.  The independent
cross-check receives the identical observation sequence — a cross-check on
different inputs proves nothing — and reports unavailable rather than agreement
when scipy is absent."
```

---

### Task 5: 因子研究 worker 与 Experiment 接线

**Files:**
- Create: `platform/src/a_share_platform/workers/factor_research.py`
- Test: `platform/tests/test_factor_research_worker.py`

**Interfaces:**
- Consumes: Task 1–4 全部、`application/experiments.py`（已有账本）
- Produces: CLI worker，dry-run 默认；真实运行写入 `research.experiment_runs`

- [ ] **Step 1: 读现有 worker 的 dry-run/ack 模式**

```bash
cd platform
grep -n "add_argument\|execute\|ack\|blockers" src/a_share_platform/workers/timing_baseline.py | head -25
```

**照抄这个模式**，不要自创。

- [ ] **Step 2: 写失败测试**

```python
# platform/tests/test_factor_research_worker.py
"""The factor research worker: dry-run by default, ack-gated writes.

A worker that writes by default is a worker that writes by accident.  The dry-run
output is the plan, printed as JSON, with exit code 0 and nothing persisted.
"""

from __future__ import annotations

import json
import unittest

from a_share_platform.workers import factor_research


class DryRunDefaultTest(unittest.TestCase):
    def test_without_execute_nothing_is_written(self) -> None:
        code = factor_research.main(["--universe-version", "universe-version:csi500:v1"])
        self.assertEqual(code, 0)

    def test_execute_without_ack_is_blocked_with_a_reason(self) -> None:
        code = factor_research.main([
            "--universe-version", "universe-version:csi500:v1", "--execute",
        ])
        self.assertEqual(code, 2)

    def test_negative_ic_is_recorded_not_retried(self) -> None:
        """The failure mode this guards is re-running until the number looks good."""
        ...
```

- [ ] **Step 3: 运行确认红测 → 实现 → 转绿**

- [ ] **Step 4: 真实 dry-run**

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.factor_research \
  --universe-version <真实 id> --horizon 20
```

- [ ] **Step 5: 真实执行并记录 IC**

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.factor_research \
  --universe-version <真实 id> --horizon 20 \
  --private-local-research-ack --execute
```

**把真实 IC 数值原样记进 Evidence，无论好坏。** 这是本 plan 最重要的产出 ——
它会第一次告诉你这三类因子在当前数据上是否有任何信号。

- [ ] **Step 6: 提交**

```bash
cd .. && git add platform/src/a_share_platform/workers/factor_research.py \
  platform/tests/test_factor_research_worker.py
git commit -m "feat: add the factor research worker with ack-gated writes

Dry-run is the default because a worker that writes by default is a worker that
writes by accident.  The plan prints as JSON with exit 0 and nothing persisted;
--execute without the research ack exits 2 with the reason.

A negative or near-zero IC is recorded as the result, not treated as a failed
run to retry.  Re-running until the number looks good is the failure mode this
worker exists to prevent."
```

---

### Task 6: Alpha 页显示真实因子指标

**Files:**
- Modify: `platform/src/a_share_platform/application/research_workspace.py`
- Modify: `platform/frontend/src/features/screen/AlphaModelReadinessPanel.tsx`
- Test: `platform/tests/test_research_workspace_projection.py`（扩展）
- Test: `platform/frontend/src/features/screen/AlphaModelReadinessPanel.test.tsx`

**Interfaces:**
- Consumes: Task 4 的 `CorrelationResult`
- Produces: Alpha readiness 投影含真实 IC/RankIC/样本量/交叉验证状态

- [ ] **Step 1: 写后端红测**

断言 Alpha 投影包含：IC 值、RankIC 值、样本量、缺失计数、`scientific_status`、
`historical_eligible`、交叉验证状态。**`scientific_status` 必须原样透传**，
不得在投影层改写。

- [ ] **Step 2: 实现后端投影 → 转绿**

- [ ] **Step 3: 前端红测**

断言页面显示真实 IC 且**同时显示** `scientific_status`（当前必为 `not_evaluated`）
与 `current_research` 标记。**不得只显示 IC 数值而隐藏其科学状态** ——
那会让使用者误以为这是已验证的有效性证据。

- [ ] **Step 4: 实现前端 → 转绿 → 四视口验收**

- [ ] **Step 5: 提交**

```bash
git commit -m "feat: surface real factor IC on the Alpha page with its scientific status

The IC value never appears alone.  It ships with scientific_status
(not_evaluated), historical_eligible (false) and the current_research data-mode
tag, because a bare correlation shown on a product surface reads as validated
edge — which current-only data cannot support."
```

---

### Task 7: Evidence 与明确否认

**Files:**
- Create: `docs/25-p2-factor-research-evidence.md`
- Modify: `docs/plans/step-03a-current-only-factor-research.md`（状态更新）

- [ ] **Step 1: 记录真实红绿测**

每个 Task 的真实失败文本与转绿结果，**不编造命令输出**。

- [ ] **Step 2: 记录真实 IC 数值**

三个维度 × 三个 horizon（20/60/120）的真实 IC、RankIC、样本量、缺失计数、
交叉验证一致性。**负结果与接近零的结果同样完整记录。**

- [ ] **Step 3: 写明确否认声明**

必须包含：

> 本 plan 产出的 IC 是「在 `normalized_current` 数据上的相关性观测」，**不是样本外证据**。
> 它不构成任何因子科学有效的证明，理由：输入未经 PIT 验证、无法证明历史可用时间、
> 未做成本后分析、未做多重检验校正、未做样本外验证。
> P2 Gate 与 P4 Gate 均**不因本 plan 通过**。
> 产出的 FactorVersion 保持 `draft`，不得用于组合构建以外的任何用途，
> 不得进入 `shadow` / `paper` / `limited_live`。

- [ ] **Step 4: 提交**

```bash
git add docs/25-p2-factor-research-evidence.md \
  docs/plans/step-03a-current-only-factor-research.md
git commit -m "docs: record P-2 factor research evidence with explicit denials

Real IC values for three dimensions across three horizons, negative and
near-zero results included unchanged.  The denial section states why these
numbers are not scientific evidence: inputs are not PIT-verified, historical
knowability is unproven, and there is no cost-adjusted, multiple-testing-
corrected, out-of-sample result.  Neither the P2 nor the P4 gate passes."
```

---

## 完成定义

1. 财务事实经编排层产出三维度真实输入，缺失显式（Task 1）；
2. 综合分数与截面排名可复现，权重版本化（Task 2）；
3. 真实行情产出版本化标签数据集，覆盖率如实报告（Task 3）；
4. 真实 IC/RankIC 算出，独立库交叉验证输入一致（Task 4）；
5. worker dry-run 默认，真实运行记入 Experiment 账本（Task 5）；
6. Alpha 页显示真实 IC 且同时显示科学状态（Task 6）；
7. Evidence 含真实数值与明确否认（Task 7）；
8. 后端 unittest / compileall / ruff / mypy 全过；前端 Vitest / lint / build 全过；四视口验收通过。

## 明确不在本 plan 范围

- 分析师修正维度 —— 需 `AnalystSourceAttestation`（付费数据）；
- `strict_historical` 因子研究 —— 需 `pit_verified` 数据；
- FactorVersion 晋级 —— 需 P4 科学门；
- 组合构建与回测 —— 属 P-5。

## 本 plan 完成后仍然成立的限制

- 全部 IC 基于 `normalized_current`，**不是样本外证据**；
- 不得声称任何因子科学有效；
- P2 与 P4 Gate 均未通过；
- FactorVersion 保持 `draft`。
