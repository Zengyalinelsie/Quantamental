# Roadmap Step Spec / Plan 包

本目录把 `docs/19-end-to-end-product-roadmap.md` 的 10 个 Step 展开为实现级 Spec/Plan。它借鉴“先设计、后计划、再按 TDD 小步执行”的方法，但不依赖或安装 Superpowers。

为减少成对文件漂移，每个 Step 使用一个文件，前半部分 `## Spec` 冻结行为和边界，后半部分
`## Plan` 只描述如何实现。Plan 不能覆盖 Spec；需要改变 Spec 时必须先修订 Spec/ADR 并重新审查。

## 权威顺序

冲突时按以下顺序处理，不能由实现者擅自选择：

1. `AGENTS.md` 的安全和仓库边界；
2. `docs/07-detailed-system-spec.md` 的 MUST/SHOULD/MAY；
3. 已接受 ADR；
4. `docs/08-detailed-implementation-plan.md` 的阶段和 Gate；
5. `docs/18-product-blueprint-and-prototype.md` 的产品合同；
6. 本目录的实现级展开；
7. Evidence 只记录事实，不反向修改需求。

发现冲突必须先报告并暂停冲突部分；安全的非冲突任务可以继续。

## 执行方式

每个 Plan task 必须：

1. 只覆盖一个可验证行为；
2. 先写或确认红测；
3. 运行并记录预期失败；
4. 写最小实现；
5. 运行定向测试转绿；
6. 必要时重构并保持绿色；
7. 运行该包规定的集成/静态/浏览器检查；
8. 更新 Evidence 和限制；
9. 在用户已授权 Git 操作时按 task/work package 独立提交。

Plan 中的“预计文件”用于控制改动边界。执行时若发现必须修改未列出的领域主合同，应先更新对应 Spec/Plan 或 ADR，不能悄悄扩张。

## 索引

| Step | Spec / Plan | 状态 |
|---:|---|---|
| 1 | `step-01-p5-engineering-completion.md` | `in_progress` |
| 2 | `step-02-p2-pit-data-remediation.md` | `ready_for_implementation`（先做资格探针） |
| 3 | `step-03-p4-real-qualification-gate.md` | `gate_blocked` |
| 4 | `step-04-p5-real-artifact-gate.md` | `gate_blocked` |
| 5 | `step-05-p6-core-selection.md` | `dependency_blocked` |
| 6 | `step-06-p7-active-timing.md` | `dependency_blocked` |
| 7 | `step-07-p8-events-agents-supply-chain.md` | `dependency_blocked` |
| 8 | `step-08-p9-monitoring-governance.md` | `dependency_blocked` |
| 9 | `step-09-p10-paper-oms.md` | `dependency_blocked` |
| 10 | `step-10-p11-limited-live-readiness.md` | `AUTH` |

状态定义和决策分级见 `docs/20-pre-development-spec-plan-audit.md`。

## 通用验证命令

每个工作包至少运行适用的定向测试，并在阶段收口时执行：

```bash
cd platform
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache .venv/bin/python -m compileall -q src
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
npm --prefix frontend test -- --run
npm --prefix frontend run lint
npm --prefix frontend run build
git diff --check
```

前端改动必须另做 320/768/1024/1440 浏览器验证。统计与回测结果必须执行对应计划中的独立库/外部引擎对照；全量测试通过不代表模型科学有效。
