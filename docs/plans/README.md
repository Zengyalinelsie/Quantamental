# Roadmap Step Spec / Plan 包

本目录把 `docs/19-end-to-end-product-roadmap.md` 的 10 个 Step 展开为实现级 Spec/Plan，并用
`track-00-prototype-runtime-delivery.md` 管理跨 P5–P10 的原型运行时产品轨道。它借鉴“先设计、后计划、
再按 TDD 小步执行”的方法，但不依赖或安装 Superpowers。

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

## 两条当前执行队列

当前不能再把“下一步”写成只有数据工作：

1. **Data/Gate 队列**：`step-02-p2-pit-data-remediation.md` Task 1，strict-PIT 数据源资格探针；
2. **Prototype/Product 队列**：`track-00-prototype-runtime-delivery.md`。PUI-00 设计基线、
   PUI-01 Desk、PUI-02 Universe/Screen **已于 2026-08-15 完成**；下一个是 PUI-03 P5 黄金路径。

**2026-08-16 更新**：以上两条队列的可执行展开已收口为 9 份实现级 plan，见
`docs/superpowers/plans/2026-08-16-roadmap-complete-platform.md`。该路线图基于逐文件代码审计，
纠正了若干文档描述与真实代码状态的差异，并覆盖 P6–P10 完整平台能力。
本目录的 step Plan 继续作为阶段 Spec 真源；新 plan 是它们的可执行展开，不替代其 Spec 与 Gate 定义。

两条队列可以作为不同 work package 并行。PUI 不需要等待假数据，可以实现真实
empty/partial/unavailable/blocked 产品状态；它不能生成 ready 数据或提升 Gate。Data/Gate 通过也不会自动
使页面与 Figma 一致。

每个页面分别报告 `Design Parity`、`Runtime Product` 和 `Domain/Capability`。通用占位、无溢出测试或
四视口响应式通过，不能单独写成“原型页面完成”。

## 索引

| Step | Spec / Plan | 状态 |
|---:|---|---|
| PUI | `track-00-prototype-runtime-delivery.md` | `in_progress`（Design Parity 0/31） |
| 1 | `step-01-p5-engineering-completion.md` | `verified`（仅工程范围；P5 Gate 仍阻断） |
| 2 | `step-02-p2-pit-data-remediation.md` | `ready_for_implementation`（先做资格探针） |
| 3 | `step-03-p4-real-qualification-gate.md` | `gate_blocked` |
| 3A | `step-03a-current-only-factor-research.md` | `ready_for_implementation`（current-only 轨道，不替代 Step 3） |
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

前端改动必须先读取目标 Figma node 的 design context，再做 1440 精确设计对照和 320/768/1024
响应式浏览器验证。目标没有独立高保真/响应式 Frame 时必须记录设计缺口或用户批准的推导方案。
统计与回测结果必须执行对应计划中的独立库/外部引擎对照；全量测试、视觉相似或原型通过都不代表
模型科学有效。
