# P-1 数据层实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 CSI300/CSI500 研究所需的行情、历史成分股与复权因子，并建好 strict-PIT 主源的升级路径，使因子研究（P-2）具备可执行的数据基础。

**Architecture:** 复用已有领域合同（`ShareCapital`、`CorporateAction`、`AdjustmentFactor`、`ExchangeCalendar` 全部已存在）与已有 provider adapter（BaoStock、AkShare）。本 plan **不新建领域数学**，只补摄取执行、修复一个已知阻断（SZ.302132 代码变更冲突）、新增复权因子重建，并建立付费 PIT 源的迁移骨架。

**Tech Stack:** Python 3.11+（本机 3.12.12）、PostgreSQL 17（端口 55432）、DuckDB/Parquet、BaoStock SDK、AkShare、psycopg 3

## Global Constraints

以下每条继承自 `AGENTS.md` 与已接受 ADR，**每个 Task 都适用**：

- `domain/` 不导入 FastAPI / SQLAlchemy / provider SDK / 前端概念
- 金额、比例、股数、时间必须有明确单位、币种、时区；所有时间 timezone-aware
- **缺失、无权限、时间不可信、冲突必须显式表达，禁止填零**
- `strict_historical` 只消费 `pit_verified`，且强制 `available_at <= decision_time`
- 免费源（BaoStock / AkShare）信任上限为 `normalized_current`，**永远不得自动提升为 `pit_verified`**
- 生产数字可追溯到 DatasetVersion / 公式版本 / 代码版本 / Run / lineage
- 失败记录不可删除或改写为成功；重复写必须幂等；same ID / different semantics 必须冲突关闭
- worker 默认 dry-run，真实写入需显式 ack（复用 `--private-local-research-ack --execute` 模式）
- 不修改 `sources/` 两个只读来源仓库
- 未经用户明确授权不 commit、不 push
- BaoStock 单次会话需 login/logout 配对，受限流约束；worker 必须支持 checkpoint 续跑

## 现状事实（2026-08-16 核实，来自 Evidence 文档）

**已在原开发机持久化的数据**：

| 域 | 数量 | 范围 | trust |
|---|---|---|---|
| Security Master (CSI800 当前身份) | 799/800 | 当前 | `normalized_current` |
| CSI500 当前 Universe | 500/500 | 仅 2026-08-10 单日 | `normalized_current` |
| CSI500 财务三表 | 35,505 observation / 12,000 UoW | 2018–2025 年末 | `normalized_current` |
| **股本** | **24,951 observation** | 2018–2026，800/800 Listing | `normalized_current` |
| **公司行动** | **8,059 observation** | 2018–2026，777/800 有行动 + 23 显式零观测 | `normalized_current` |
| 官方披露小样本 | 8 PDF / 11 raw object / 2 修订链 | 4 家公司 | `pit_verified`（仅这 13 条） |
| Timing baseline | 1 forecast / 21 benchmark bar | 仅 2026-08-10 | `normalized_current` |
| 质量与覆盖报告 | 12,000 + 12,000 | CSI500 | — |

**确认缺失**：

| 缺口 | 现状 | 影响 |
|---|---|---|
| 2018+ 全范围日线 | **仅 21 条**（2026-07-13 至 08-10），`market_data_partitions=0` | **阻断标签生成 → 阻断 IC 计算** |
| 历史 CSI300/CSI500 成分股 | 仅单日快照 | 阻断历史截面 |
| CSI300 当前 Universe | **完全失败** —— SZ.302132 代码变更冲突 | 阻断 CSI300 全部研究 |
| 复权因子 | 表为空 | 跨除权日收益失真 |
| 日度交易状态（停牌/ST/涨跌停） | 表为空 | 标签无法判定可交易性 |
| XBSE | 仅 333 行当前探针，未入库 | 不影响 CSI300/500 |
| strict-PIT 主源 | Wind 无许可 / Factor Service 无凭据 / iFinD 401 | 阻断可信历史回测 |

**设计评估结论**：领域合同与表结构**无需修改**。`ShareCapital` 含自由流通股本并有大小关系校验；
`CorporateAction` 含 `RIGHTS_ISSUE`（配股）；`observation.*` 与 `canonical.*` 分层正确。
缺口全部是「数据未摄取」或「一个已知阻断未修」。

---

### Task 1: 修复 SZ.302132 代码变更冲突（解除 CSI300 阻断）

CSI300 当前完全无法摄取，根因是中航电测 `300114` 于 2025-02-17 更名并换码为中航成飞 `302132`。
现有实现从 current code 派生 Listing ID，导致同一 Listing 被要求拆成两个，任务失败关闭
（这是**正确**行为 —— 不静默剔除成员）。修法是让身份层承认代码变更区间。

**Files:**
- Modify: `platform/src/a_share_platform/domain/security_master.py`
- Test: `platform/tests/test_security_master_code_change.py`（新建）
- Modify: `platform/src/a_share_platform/adapters/providers/a_share_identity_universe.py`（确认真实文件名后再改）

**Interfaces:**
- Consumes: 已有 `SecurityMaster`、`SecurityIdentitySnapshot`、`Listing`
- Produces: `SecurityMaster.resolve_listing_id(symbol, as_of) -> str`，对同一法定主体的历史与当前代码返回**同一** Listing ID

- [ ] **Step 1: 先读现有身份合同，确认真实类名与字段**

Run:
```bash
cd platform
grep -n "^class \|def resolve\|listing_id" src/a_share_platform/domain/security_master.py | head -40
grep -rn "302132\|code_change\|identifier_history" src/a_share_platform/ --include=*.py | head -20
```

不要凭本 plan 的假设改代码。若真实字段名与下文不同，以代码为准并同步修正本 Task 的后续步骤。

- [ ] **Step 2: 写失败测试**

```python
# platform/tests/test_security_master_code_change.py
"""A renamed and re-coded listing must stay one listing.

中航电测 300114 became 中航成飞 302132 on 2025-02-17.  Deriving the listing id
from the current code splits one legal entity into two, which fails the whole
CSI300 ingestion closed.  Both codes must resolve to the same listing.
"""

from __future__ import annotations

import unittest
from datetime import date

from a_share_platform.domain.security_master import SecurityMaster


class ListingCodeChangeTest(unittest.TestCase):
    def test_old_and_new_code_resolve_to_one_listing(self) -> None:
        master = SecurityMaster.empty()  # replace with the real builder found in Step 1
        before = master.resolve_listing_id("300114", as_of=date(2025, 1, 1))
        after = master.resolve_listing_id("302132", as_of=date(2025, 3, 1))
        self.assertEqual(before, after)

    def test_a_code_reused_by_a_different_entity_is_not_merged(self) -> None:
        """Shenzhen recycles delisted codes, so equal code is not equal entity."""
        master = SecurityMaster.empty()
        with self.assertRaises(LookupError):
            master.resolve_listing_id("300114", as_of=date(2010, 1, 1))
```

- [ ] **Step 3: 运行并记录真实红测原因**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_security_master_code_change -v`

Expected: FAIL —— `resolve_listing_id` 不存在，或返回两个不同 ID。把真实错误文本抄进 Evidence。

- [ ] **Step 4: 最小实现**

在 `domain/security_master.py` 增加基于 `identifier_history` 区间的解析。**不要**在此处
调用任何 provider —— 领域层只消费已规范化的区间记录。

- [ ] **Step 5: 运行定向测试转绿**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_security_master_code_change -v`
Expected: PASS

- [ ] **Step 6: dry-run 验证 CSI300 不再失败**

Run:
```bash
cd platform
source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.backfill \
  --end 2026-08-10 --all-a-share --benchmarks 000300 --domains universe --markets XSHG XSHE
```
Expected: dry-run 计划中 CSI300 成员数为 300，无 Listing ID 冲突 blocker。

- [ ] **Step 7: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/domain/security_master.py \
  platform/tests/test_security_master_code_change.py
git commit -m "fix: resolve one listing across a code change so CSI300 can ingest

中航电测 300114 became 中航成飞 302132 on 2025-02-17.  Deriving the listing id
from the current code split one legal entity in two and failed the whole CSI300
ingestion closed — correct behaviour, wrong root cause.  Identity now resolves
both codes to one listing through the identifier history intervals.

A code reused by a different entity after delisting still refuses to merge:
equal code is not equal entity on Shenzhen."
```

---

### Task 2: 摄取 2018+ 全范围日线（最大阻断）

当前只有 21 条日线，标签生成器（`domain/labels.py`，已实现）没有数据可算。
本 Task 只**执行**摄取，不改代码 —— worker 已存在。

**Files:**
- 无代码改动；产出为 Parquet 分区 + `observation.market_data_partitions` 记录
- Evidence: `docs/12-p2-implementation-evidence.md` 追加真实计数

**Interfaces:**
- Consumes: `workers/backfill.py --domains raw_daily_bar`
- Produces: `observation.market_data_partitions` 非零；Parquet 分区按 DatasetVersion/Exchange/Year

- [ ] **Step 1: 确认前置数据齐备**

```bash
cd platform && source /tmp/asp_env.sh
.venv/bin/python - <<'PY'
import os, psycopg
with psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True) as c:
    for t in ("canonical.securities","canonical.listings","canonical.universe_versions",
              "canonical.exchange_calendar_days"):
        print(t, c.execute(f"select count(*) from {t}").fetchone()[0])
PY
```
Expected: 四者均非零。若 `exchange_calendar_days` 为 0，先跑 `--domains trading_calendar`，
因为日线摄取需要交易日历判定缺口。

- [ ] **Step 2: 先摄 30 家验证全链（递进纪律）**

Step 02 Plan 要求「3–5 → 30 → 全量」。**不要直接跑全量。**

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.backfill \
  --start 2018-01-01 --end 2025-12-31 \
  --symbols SH.600519 SZ.000858 SH.601318 SZ.000333 SH.600036 \
  --domains raw_daily_bar --parquet-root ./data/parquet
```
先 dry-run（不加 `--execute`），确认计划的 UoW 数与日期范围正确。

- [ ] **Step 3: 执行 5 家真实摄取**

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.backfill \
  --start 2018-01-01 --end 2025-12-31 \
  --symbols SH.600519 SZ.000858 SH.601318 SZ.000333 SH.600036 \
  --domains raw_daily_bar --parquet-root ./data/parquet \
  --private-local-research-ack --execute
```
Expected: 退出码 0；每只约 1,900 个交易日；`market_data_partitions` 出现记录。

- [ ] **Step 4: 验证摄取正确性**

```bash
cd platform && source /tmp/asp_env.sh
.venv/bin/python - <<'PY'
import os, psycopg
with psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True) as c:
    print("partitions:", c.execute("select count(*) from observation.market_data_partitions").fetchone()[0])
    print("jobs:", c.execute("select status, count(*) from governance.ingestion_jobs group by status").fetchall())
    print("failed reasons:", c.execute(
        "select failure_reasons from governance.ingestion_jobs where status='failed' limit 5").fetchall())
PY
```
必须：0 个 failed job；若有 failed，**先查清原因再继续**，不得跳过。

- [ ] **Step 5: 用真实数据跑标签生成器**

这是本 Task 的真正验收 —— 标签能否算出来。

```bash
cd platform && PYTHONPATH=src .venv/bin/python - <<'PY'
# Read one security's real bars from Parquet and compute a 20-session label.
# Replace the reader call with the real Parquet adapter API found in
# adapters/parquet/market_data.py.
from datetime import date
from decimal import Decimal
from a_share_platform.domain.labels import (
    ForwardReturnLabelDefinition, LabelHorizon, LabelPriceInput)
from a_share_platform.domain.market_data import PriceAdjustment
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode

definition = ForwardReturnLabelDefinition(
    label_id="label.forward_return", version="v0",
    horizon=LabelHorizon.TWENTY_SESSIONS,
    adjustment=PriceAdjustment.UNADJUSTED,
    data_mode=DataMode.CURRENT_RESEARCH,
    trust_state=DataTrustState.NORMALIZED_CURRENT,
)
print("definition hash:", definition.content_hash)
print("limitation:", definition.limitation)
PY
```

- [ ] **Step 6: 扩到 30 家，再验一次**

同 Step 3，把 `--symbols` 换成 30 只（从 CSI500 成员取）。确认限流与 checkpoint 行为正常。

- [ ] **Step 7: 全量摄取 CSI500**

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.backfill \
  --start 2018-01-01 --end 2025-12-31 --all-a-share --benchmarks 000905 \
  --domains raw_daily_bar --markets XSHG XSHE --parquet-root ./data/parquet \
  --private-local-research-ack --execute
```

耗时可能数小时。BaoStock 有限流；worker 有 checkpoint，中断后重跑会续。
**不要为了快而并发多进程** —— 会触发 provider 封禁，且 `baostock_guard.py` 会拦。

- [ ] **Step 8: 记录真实计数到 Evidence 并提交**

在 `docs/12-p2-implementation-evidence.md` 追加一节，记录：分区数、job 数、失败数、
实际交易日范围、每只均值行数、耗时、遇到的限流。**如实记录失败项，不美化。**

```bash
git add docs/12-p2-implementation-evidence.md
git commit -m "docs: record 2018+ CSI500 daily bar ingestion counts"
```

---

### Task 3: 摄取历史成分股（解除历史截面阻断）

当前只有 2026-08-10 单日快照。因子研究需要每个决策截面当时的真实成分股，
否则会用今天的成分回填历史 —— `CLAUDE.md` §11 明确禁止。

**Files:**
- 无代码改动（worker 支持 `--domains universe --universe-observation-mode`）
- Evidence: `docs/12-p2-implementation-evidence.md`

**Interfaces:**
- Consumes: `workers/backfill.py --domains universe`
- Produces: `canonical.universe_memberships` 覆盖 2018+ 多个观测日

- [ ] **Step 1: 确认观测模式语义**

```bash
cd platform
grep -n "class UniverseObservationMode" -A8 src/a_share_platform/domain/backfill.py
```

`CONTINUOUS_DAILY` 查每个交易日；`DISCRETE_MONTH_END` 只存已观测的月末快照并显式记录缺口。
CSI 指数每半年调整一次，**月末模式足够且调用量小两个数量级**，推荐月末。

- [ ] **Step 2: dry-run 月末模式**

```bash
cd platform && source /tmp/asp_env.sh
PYTHONPATH=src .venv/bin/python -m a_share_platform.workers.backfill \
  --start 2018-01-01 --end 2025-12-31 --all-a-share --benchmarks 000905 \
  --domains universe --universe-observation-mode discrete_month_end --markets XSHG XSHE
```
Expected: 约 96 个月末观测点（2018–2025）。

- [ ] **Step 3: 执行 CSI500 历史成分股摄取**

同上加 `--private-local-research-ack --execute`。

- [ ] **Step 4: 执行 CSI300（需 Task 1 已修复）**

把 `--benchmarks 000905` 换成 `000300`。若仍报 Listing 冲突，回到 Task 1 —— **不要绕过**。

- [ ] **Step 5: 验证历史成分股可查**

```bash
cd platform && source /tmp/asp_env.sh
.venv/bin/python - <<'PY'
import os, psycopg
with psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True) as c:
    print("versions:", c.execute("select count(*) from canonical.universe_versions").fetchone()[0])
    print("memberships:", c.execute("select count(*) from canonical.universe_memberships").fetchone()[0])
    print("date span:", c.execute(
        "select min(as_of_date), max(as_of_date) from canonical.universe_versions").fetchone())
PY
```
必须：观测日跨越 2018–2025，不是单日。

- [ ] **Step 6: 记录并提交**

```bash
git add docs/12-p2-implementation-evidence.md
git commit -m "docs: record historical CSI300/CSI500 universe membership ingestion"
```

---

### Task 4: 摄取日度交易状态（标签正确性前置）

标签需要判定「入场/出场当日是否可交易」。`observation.daily_market_states` 现为空，
意味着 `LabelPriceInput.tradable` 只能靠猜 —— 那会产出错误标签。

**Files:**
- 无代码改动（`DailyMarketState`、`PriceLimit` 领域合同已存在）
- Evidence: `docs/12-p2-implementation-evidence.md`

**Interfaces:**
- Consumes: BaoStock 日线中的 `tradestatus`、`isST` 字段
- Produces: `observation.daily_market_states` 非零；供标签生成器判定 `tradable`

- [ ] **Step 1: 确认 provider 覆盖哪些状态字段**

```bash
cd platform
grep -n "tradestatus\|isST\|trade_status\|special_treatment" \
  src/a_share_platform/adapters/providers/baostock_market_data.py | head -20
```

- [ ] **Step 2: 确认涨跌停的处理口径**

`docs/11-p2-data-source-coverage-matrix.md` 记录：BaoStock **无独立涨跌停字段**，
需按规则版本计算并保存计算证据。本 Task **不实现涨跌停推算** ——
只摄取 provider 直接提供的停牌与 ST 标记，涨跌停留待付费源或规则 ADR。

在 Evidence 中显式记录这个范围限制。

- [ ] **Step 3: 执行摄取（随日线域一并产生，或单独域）**

若 `daily_market_states` 由 `raw_daily_bar` 域顺带写入，Task 2 完成后即非零 —— 先查：

```bash
cd platform && source /tmp/asp_env.sh
.venv/bin/python -c "
import os, psycopg
with psycopg.connect(os.environ['ASP_DATABASE_URL'], autocommit=True) as c:
    print('daily_market_states:', c.execute('select count(*) from observation.daily_market_states').fetchone()[0])
"
```

为零则需在 provider adapter 增加该域的 sink 接线；此时新增测试再改代码，不要直接改。

- [ ] **Step 4: 提交**

```bash
git commit -m "docs: record daily trading state coverage and the price-limit scope limit"
```

---

### Task 5: 复权因子重建（跨除权日收益正确性）

`domain/labels.py` 当前声明 `adjustment=unadjusted` 并携带限制说明。
公司行动数据**已有 8,059 条**，因此可以重建复权因子，让标签跨除权日不失真。

**Files:**
- Create: `platform/src/a_share_platform/domain/adjustment.py`
- Test: `platform/tests/test_adjustment_factors.py`
- Modify: `platform/src/a_share_platform/domain/labels.py`（支持 `adjustment=back_adjusted`）

**Interfaces:**
- Consumes: 已有 `CorporateAction`（`CASH_DIVIDEND`/`BONUS_SHARE`/`SPLIT`/`REVERSE_SPLIT`/`RIGHTS_ISSUE`）、`AdjustmentFactor`
- Produces: `rebuild_adjustment_factors(actions, bars) -> tuple[AdjustmentFactor, ...]`

- [ ] **Step 1: 先读 AdjustmentFactor 与 CorporateAction 真实字段**

```bash
cd platform
grep -n "class AdjustmentFactor" -A20 src/a_share_platform/domain/market_data.py
grep -n "class CorporateAction" -A46 src/a_share_platform/domain/market_data.py
```

以真实字段为准。若 `CorporateAction` 缺重建所需字段（如每股派现、送股比例、配股价与比例），
**先补领域字段并单独提交**，再做重建。

- [ ] **Step 2: 写失败测试 —— 现金分红**

```python
# platform/tests/test_adjustment_factors.py
"""Back-adjustment factors rebuilt from corporate actions.

Without these, a return spanning an ex-rights date is wrong: the price drops by
the dividend or the split ratio and an unadjusted label reads that as a loss.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from a_share_platform.domain.adjustment import rebuild_adjustment_factors


class CashDividendAdjustmentTest(unittest.TestCase):
    def test_cash_dividend_scales_prior_prices(self) -> None:
        # 10.00 close, 0.50 per-share dividend, ex-date 2024-06-20.
        # Back-adjusted factor before the ex-date is (10.00 - 0.50) / 10.00.
        factors = rebuild_adjustment_factors(
            actions=(_cash_dividend(date(2024, 6, 20), Decimal("0.50")),),
            previous_close=Decimal("10.00"),
        )
        self.assertEqual(len(factors), 1)
        self.assertEqual(factors[0].factor, Decimal("0.95"))

    def test_missing_previous_close_refuses_rather_than_assuming_one(self) -> None:
        with self.assertRaises(ValueError):
            rebuild_adjustment_factors(
                actions=(_cash_dividend(date(2024, 6, 20), Decimal("0.50")),),
                previous_close=None,
            )
```

（`_cash_dividend` 辅助函数按 Step 1 读到的真实 `CorporateAction` 签名构造。）

- [ ] **Step 3: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_adjustment_factors -v`
Expected: FAIL —— `a_share_platform.domain.adjustment` 不存在。

- [ ] **Step 4: 实现现金分红重建**

只做现金分红，最小实现。其余行动类型下一步补。

- [ ] **Step 5: 转绿后逐类补齐**

依次为 `BONUS_SHARE`（送股）、`SPLIT`/`REVERSE_SPLIT`（拆并股）、`RIGHTS_ISSUE`（配股）
各写红测再实现。**送股与转增不得静默合并**（`docs/14` 明确要求分别保存）。
配股需要配股价与配股比例；缺任一则该因子 `unavailable`，**不猜**。

- [ ] **Step 6: 让标签支持后复权**

在 `domain/labels.py` 增加 `PriceAdjustment.BACK_ADJUSTED` 支路。
注意：`PriceAdjustment` 当前只有 `UNADJUSTED` 一个值，需先扩枚举并检查所有现有用法。

- [ ] **Step 7: 交叉验证**

用 5 只有已知分红送转历史的股票，把重建因子与 BaoStock `adjustflag=1`（后复权）
返回的价格对照。差异超过容差要查清原因，**不得放宽容差了事**。

- [ ] **Step 8: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/domain/adjustment.py \
  platform/src/a_share_platform/domain/labels.py \
  platform/tests/test_adjustment_factors.py
git commit -m "feat: rebuild back-adjustment factors from corporate actions

Corporate action data already covers 800/800 listings with 8,059 observations,
so adjustment factors can be rebuilt rather than bought.  Without them a label
spanning an ex-rights date reads the mechanical price drop as a loss.

Bonus shares and capitalisation issues stay separate rather than merged.  A
rights issue with a missing subscription price or ratio yields an unavailable
factor instead of a guess."
```

---

### Task 6: strict-PIT 主源资格探针与升级路径（不下载，只建骨架）

免费源信任上限是 `normalized_current`，**永远到不了 `pit_verified`**，因为它们不提供
「这条数据在历史上哪一刻可用」。本 Task 建好探针与迁移骨架，你什么时候买许可就能直接接上。

**Files:**
- Create: `platform/src/a_share_platform/adapters/providers/pit_source_probe.py`
- Test: `platform/tests/test_pit_source_probe.py`
- Create: `docs/adr/0013-strict-pit-field-primary-source.md`（草案，状态 `Proposed`）
- Modify: `docs/14-data-source-catalog-and-agent-routing.md`

**Interfaces:**
- Consumes: `ports/` 已有 provider 抽象
- Produces: `probe_pit_source(config) -> PitSourceProbeResult`，无凭据时返回结构化「不可评估」

- [ ] **Step 1: 读 ADR-0007 的资格政策**

```bash
grep -n "" docs/adr/0007-strict-pit-source-qualification-policy.md | head -60
```

探针必须验证的项在该 ADR 中已定义，**照它做，不自行发明标准**。

- [ ] **Step 2: 写失败测试 —— 无凭据时的行为**

```python
# platform/tests/test_pit_source_probe.py
"""A probe with no credentials reports "cannot evaluate", never "qualified".

The most dangerous failure mode is a probe that silently passes because it never
reached the provider.  Absence of evidence must not read as evidence of absence
of problems.
"""

from __future__ import annotations

import unittest

from a_share_platform.adapters.providers.pit_source_probe import (
    PitSourceProbeStatus,
    probe_pit_source,
)


class UnavailableCredentialTest(unittest.TestCase):
    def test_missing_credential_is_not_evaluable_not_qualified(self) -> None:
        result = probe_pit_source(provider_id="wind", credential=None)
        self.assertEqual(result.status, PitSourceProbeStatus.NOT_EVALUABLE)
        self.assertIn("credential", result.reason.lower())

    def test_probe_never_returns_qualified_without_field_evidence(self) -> None:
        result = probe_pit_source(provider_id="wind", credential=None)
        self.assertNotEqual(result.status, PitSourceProbeStatus.QUALIFIED)

    def test_probe_does_not_download_when_not_evaluable(self) -> None:
        """A failed qualification must not trigger bulk download."""
        result = probe_pit_source(provider_id="wind", credential=None)
        self.assertEqual(result.rows_fetched, 0)
```

- [ ] **Step 3: 运行确认红测**

Run: `cd platform && PYTHONPATH=src .venv/bin/python -m unittest tests.test_pit_source_probe -v`
Expected: FAIL —— 模块不存在。

- [ ] **Step 4: 实现探针骨架**

`PitSourceProbeStatus` 至少三值：`QUALIFIED` / `NORMALIZED_CURRENT_ONLY` / `NOT_EVALUABLE`。
**不实现任何真实网络调用** —— 那需要你先有凭据和许可。

- [ ] **Step 5: 补齐 ADR-0007 要求的 10 项验证维度测试**

认证方式、字段存在性与单位、首次披露与修订链、历史指数成分、2018+ 可用范围、
许可与本地保存权、限流与配额、失败语义、能否支撑 `pit_verified`、字段级主源优先与冲突暴露。
每项一个测试，**用 fake provider**，不联网。

- [ ] **Step 6: 写 ADR 草案（状态 Proposed，不是 Accepted）**

`docs/adr/0013-strict-pit-field-primary-source.md`，逐字段列出候选主源、备源、冲突暴露规则。
**明确标注状态为 `Proposed`** —— 没有真实探针证据不得 Accept。

- [ ] **Step 7: 更新数据源目录**

在 `docs/14-data-source-catalog-and-agent-routing.md` 记录：探针已就绪、
三个候选源当前均为 `not_evaluable`（无凭据）、以及买到许可后的接入步骤。

- [ ] **Step 8: 全量验证并提交**

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src
cd .. && git add platform/src/a_share_platform/adapters/providers/pit_source_probe.py \
  platform/tests/test_pit_source_probe.py \
  docs/adr/0013-strict-pit-field-primary-source.md \
  docs/14-data-source-catalog-and-agent-routing.md
git commit -m "feat: add strict-PIT source qualification probe skeleton

Free sources cap at normalized_current because they do not state when a value
first became knowable.  The probe makes that ceiling explicit rather than
letting a silent pass imply qualification: with no credential it reports
not_evaluable, never qualified, and fetches nothing.

ADR-0013 stays Proposed.  Accepting a field primary source needs real probe
evidence, which needs a licence."
```

---

### Task 7: 数据完整性 Gate 与 Evidence 收口

**Files:**
- Create: `platform/tests/test_data_readiness_gate.py`
- Modify: `docs/11-p2-data-source-coverage-matrix.md`
- Modify: `docs/12-p2-implementation-evidence.md`

**Interfaces:**
- Consumes: 全部前序 Task 的产出
- Produces: 一个可重跑的就绪度检查，供 P-2 前置校验

- [ ] **Step 1: 写就绪度检查测试**

```python
# platform/tests/test_data_readiness_gate.py
"""P-2 preconditions, as an executable check rather than a document claim.

This test is skipped without a database, so it never fails CI on a machine that
has no data — but on the machine that does, it states plainly whether factor
research can start.
"""

from __future__ import annotations

import os
import unittest


@unittest.skipUnless(os.environ.get("ASP_DATABASE_URL"), "needs a local database")
class DataReadinessGateTest(unittest.TestCase):
    def test_daily_bars_cover_more_than_one_window(self) -> None:
        import psycopg

        with psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True) as conn:
            partitions = conn.execute(
                "select count(*) from observation.market_data_partitions"
            ).fetchone()[0]
        # 21 bars was the passive-timing baseline, not a research history.
        self.assertGreater(partitions, 1, "daily bars are still baseline-only")

    def test_universe_history_spans_more_than_one_observation_date(self) -> None:
        import psycopg

        with psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True) as conn:
            dates = conn.execute(
                "select count(distinct as_of_date) from canonical.universe_versions"
            ).fetchone()[0]
        self.assertGreater(dates, 1, "universe is still a single-day snapshot")

    def test_no_ingestion_job_failed_silently(self) -> None:
        import psycopg

        with psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True) as conn:
            failed = conn.execute(
                "select count(*) from governance.ingestion_jobs where status = 'failed'"
            ).fetchone()[0]
        self.assertEqual(failed, 0, "a failed ingestion job must be resolved, not ignored")

    def test_nothing_claims_pit_verified_from_a_free_source(self) -> None:
        """The trust ceiling must hold in the data, not only in the docs."""
        import psycopg

        with psycopg.connect(os.environ["ASP_DATABASE_URL"], autocommit=True) as conn:
            leaked = conn.execute("""
                select count(*) from observation.normalized_current_financial_observations
                where trust_state = 'pit_verified'
            """).fetchone()[0]
        self.assertEqual(leaked, 0, "a free source was promoted to pit_verified")
```

- [ ] **Step 2: 运行（有库时）**

Run: `cd platform && source /tmp/asp_env.sh && PYTHONPATH=src .venv/bin/python -m unittest tests.test_data_readiness_gate -v`

在数据摄取完成前，前两项**应该失败** —— 这正是它的用途。

- [ ] **Step 3: 更新覆盖矩阵为真实状态**

逐行更新 `docs/11-p2-data-source-coverage-matrix.md`：每个域的真实计数、来源、信任上限、
剩余缺口。**不得把"表结构已建"写成"数据已覆盖"**。

- [ ] **Step 4: 写 P-1 Evidence 并提交**

记录：每个 Task 的真实红绿测、摄取计数、耗时、限流事件、失败与处理、
未完成项（XBSE、涨跌停、strict-PIT），以及明确声明：**本 plan 产出全部为
`normalized_current`，不支持可信历史回测，不得声称任何策略有效**。

```bash
git add platform/tests/test_data_readiness_gate.py \
  docs/11-p2-data-source-coverage-matrix.md docs/12-p2-implementation-evidence.md
git commit -m "test: make P-2 data preconditions an executable gate

The coverage matrix was a document claim; this is a check that fails on the
machine that actually holds the data.  It also asserts the trust ceiling in the
data rather than only in prose: no free-source observation may carry
pit_verified."
```

---

## 完成定义

1. Task 1 使 CSI300 摄取不再失败关闭；
2. `observation.market_data_partitions` 覆盖 2018–2025 CSI500（Task 2）；
3. `canonical.universe_versions` 跨多个观测日，含 CSI300 与 CSI500（Task 3）；
4. 日度交易状态可供标签判定可交易性，涨跌停范围限制已记录（Task 4）；
5. 复权因子可从已有公司行动重建，并与 BaoStock 后复权价交叉验证（Task 5）；
6. strict-PIT 探针就绪，ADR-0013 为 `Proposed`，无凭据时返回 `not_evaluable`（Task 6）；
7. 就绪度 Gate 可重跑；覆盖矩阵与 Evidence 反映真实状态（Task 7）；
8. 后端 unittest / compileall / ruff / mypy 全过；`git diff --check` 干净。

## 明确不在本 plan 范围

- XBSE（北交所）历史身份与行情 —— 不影响 CSI300/500 研究；
- 涨跌停状态推算 —— 需规则版本 ADR 或付费源；
- 财务季度数据 —— 当前仅 2018–2025 年末，季度需付费源或另行摄取；
- 任何 `pit_verified` 数据 —— 需付费许可；
- 因子计算与 IC —— 属 P-2。

## 本 plan 完成后仍然成立的限制

- 全部数据为 `normalized_current`，**不支持 `strict_historical` 回测**；
- 因此 P-2 算出的 IC 只是「当前可得数据上的相关性观测」，**不是样本外证据**；
- 不得据此声称任何因子或策略科学有效；
- P2 Gate 与 P4 Gate 均**不因本 plan 通过**。
