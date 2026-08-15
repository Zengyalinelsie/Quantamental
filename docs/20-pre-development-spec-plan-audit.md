# P5–P11 开发前 Spec / Plan 完整性审计

> 审计日期：2026-08-15
>
> 审计基线：`f703d08`
>
> 目的：在继续功能开发前，明确哪些设计已经冻结、哪些计划只是阶段清单、哪些决策仍会改变实现。
>
> 方法参考：借鉴 Superpowers 的“设计 Spec 与可执行 Plan 分离、精确文件、TDD 小步、逐任务验证”思想；不安装、不依赖 Superpowers 或其插件。

## 1. 结论

现有文档已经具备完整的顶层框架，但尚不能说“后面只是写代码”：

- `07-detailed-system-spec.md` 已覆盖 P0–P11 的 59 条系统需求；
- `08-detailed-implementation-plan.md` 已覆盖 P0–P11 的阶段、工作包、依赖和 Gate；
- `18-product-blueprint-and-prototype.md` 已定义六工作区、31 页、黄金路径和页面六态；
- `19-end-to-end-product-roadmap.md` 已说明从当前状态到最终产品的 10 个执行步骤；
- `22-prototype-runtime-gap-audit.md` 已确认当前 31 页中约 12 页局部接线、19 页占位、0 页完成
  精确 Figma node 的运行时 Design Parity；
- P5–P11 仍缺逐步骤的实现级设计：具体领域对象、端口、表、API、前端状态、测试文件、验证命令和提交边界；
- 仍有若干产品/供应商决策必须在对应代码开始前或 Gate 前冻结。

因此 `docs/plans/` 除 Roadmap Step 包外，新增跨阶段 PUI 原型运行时轨道。它不替代 Spec 和总 Plan，
分别把领域 Gate 与产品页面展开到 implementation-ready 所需粒度。

## 2. 文档职责

| 层级 | 文件 | 回答的问题 |
|---|---|---|
| 产品边界 | `00-product-vision.md` | 为什么做、明确不做什么 |
| 系统 Spec | `07-detailed-system-spec.md` | 系统必须满足什么 |
| 总实施 Plan | `08-detailed-implementation-plan.md` | P0–P11 如何分阶段和过 Gate |
| 一致性审查 | `09-spec-plan-consistency-review.md` | Spec 与 Plan 是否冲突 |
| 产品原型 | `18-product-blueprint-and-prototype.md` | 用户在 31 页中看到什么、如何操作 |
| 原型运行时差距 | `22-prototype-runtime-gap-audit.md` | 当前页面与 Figma/产品能力实际差多少 |
| 全局路线图 | `19-end-to-end-product-roadmap.md` | 从现在到最终产品的顺序和里程碑 |
| 步骤 Spec / Plan | `docs/plans/step-*.md` | 该步骤具体改什么文件、先写什么测试、如何验收 |
| PUI 跨阶段 Plan | `docs/plans/track-00-prototype-runtime-delivery.md` | Figma 如何逐页变成真实运行时产品 |
| ADR | `docs/adr/*.md` | 重大或难以逆转的选择为什么这样定 |
| Evidence | `docs/*-implementation-evidence.md` | 实际做了什么、测试和真实证据是什么 |

后续不得把 Evidence 反过来当 Spec，也不得因为实现已经存在就静默改写 Spec。

## 3. Planning Definition of Ready

一个 Roadmap Step 只有同时满足以下条件才允许标记 `ready_for_implementation`：

1. 关联 SPEC、总 Plan 工作包和原型页面已列出；
2. 范围与非目标清楚；
3. 领域对象、状态机、单位、时区、版本和不变量清楚；
4. 数据来源资格、存储层、append-only/可变边界和 lineage 清楚；
5. API 资源、读写权限、幂等和错误合同清楚；
6. 页面六态、操作、Gate 和响应式行为清楚；
7. 前端页面有精确 Figma node 或明确标记缺少独立高保真 Frame；Design Parity、Runtime Product、
   Domain/Capability 三轴分开；
8. 失败关闭和“不填零”语义清楚；
9. TDD 任务写到预计文件和测试文件；
10. 定向、全量、数据库、浏览器和科学交叉验证命令清楚；
11. migration、rollback/restore、证据文档和提交边界清楚；
12. 没有未解决的 `D0` 决策；
13. 用户未授权的外部写入、数据许可或交易动作不在执行范围。

计划状态：

- `draft`：正在形成；
- `decision_blocked`：文档完整，但存在必须先裁决的 `D0`；
- `ready_for_implementation`：可以按 TDD 执行；
- `dependency_blocked`：Spec/Plan/决策已就绪，但上游 Gate 尚未完成；
- `in_progress`：已有红测或实现；
- `verified`：实现、验证和 Evidence 均完成；
- `gate_blocked`：工程完成，但真实数据、科学或用途 Gate 未过。

## 4. 决策分级

| 等级 | 含义 | 处理 |
|---|---|---|
| D0 | 会改变领域/API/存储主合同 | 开始该部分代码前必须 ADR/用户批准 |
| D1 | 不改变核心架构，但改变研究结果或 adapter | 集成或真实运行前冻结 |
| D2 | 可配置默认值、阈值或展示偏好 | Gate 前冻结；代码不得写死 |
| AUTH | 涉及许可、外部写入、账户或交易权限 | 必须取得明确新授权，不能用技术默认替代 |

## 5. 当前完整性矩阵

| Roadmap Step | 顶层 Spec | 总 Plan | 原型 | 实现级 Spec/Plan | 当前状态 |
|---|---|---|---|---|---|
| PUI 原型运行时轨道 | SPEC-042–050 | 有 | 14 个关键 1440 + 31 页蓝图 | `track-00` | `in_progress`；Design Parity 0/31 |
| 1 P5 工程收口 | 有 | 有 | 有 | `step-01` | `verified`；不等于 P5 Gate 或原型 parity |
| 2 P2/PIT 数据补齐 | 有 | 有 | 数据治理页有 | 本轮补充 | `ready_for_implementation`；先做资格探针，bulk importer 仍需字段主源 ADR |
| 3 P4 真实 Gate | 有 | 有 | Factor Workspace 有 | 本轮补充 | `gate_blocked`；等待 Step 2 |
| 4 P5 真实产物 Gate | 有 | 有 | P5 黄金路径有 | 本轮补充 | `gate_blocked`；等待 Step 2/3 |
| 5 P6 核心选股 MVP | 有 | 有但偏清单 | 有 | 本轮补充 | `dependency_blocked`；决策已由 ADR-0006 冻结 |
| 6 P7 主动 Timing | 有 | 有但偏清单 | 有 | 本轮补充 | `dependency_blocked`；决策已由 ADR-0006 冻结 |
| 7 P8 事件/Agent | 有 | 有但偏清单 | 有 | 本轮补充 | `dependency_blocked`；保存边界已由 ADR-0008 冻结 |
| 8 P9 治理闭环 | 有 | 有但偏清单 | 有 | 本轮补充 | `dependency_blocked`；owner 已由 ADR-0009 冻结 |
| 9 P10 Paper OMS | 有 | 有但偏清单 | 有 | 本轮补充 | `dependency_blocked`；Paper adapter 已由 ADR-0010 冻结 |
| 10 P11 Limited Live | 有边界 | 有条件计划 | 只定义受限入口 | 本轮只补 readiness | `AUTH`；不允许执行 |

## 6. 尚需冻结的决策

### 已冻结的 D0/关键默认

| ID | 决策 | 推荐默认 | 最迟时点 |
|---|---|---|---|
| PUI-D0-01 | 非关键页和 320/768/1024 缺独立高保真 Frame 时如何验收 | 先用 14 个关键页建立设计系统；每个缺失页先补精确设计或记录用户批准的推导方案 | 对应页面视觉编码前 |
| DATA-D0-01 | strict PIT 财务/公告/历史成分的合格主源与保存许可 | ADR-0007：先探针 Wind/同花顺内部服务等；字段主源资格不通过则失败关闭 | Step 2 strict importer 前 |
| P6-D0-01 | 第一研究 benchmark | ADR-0006：CSI800，总体之外保留 CSI300/CSI500 分组 | 已冻结 |
| P6-D0-02 | 第一外部回测引擎 | ADR-0006：RQAlpha adapter | 已冻结 |
| P10-D0-01 | Paper 是否完全内部模拟或对接券商模拟环境 | ADR-0010：确定性内部 Paper Broker，不连接任何真实账户 | 已冻结 |
| P11-AUTH-01 | 是否进入 Limited Live | 无默认；当前明确为不授权 | P11 任何实现前 |

### 已冻结的 D1

| ID | 决策 | 推荐默认 | 最迟时点 |
|---|---|---|---|
| P5-D1-01 | Outcome entry/exit session、价格、复权和公司行动政策 | ADR-0006 | 已冻结；实际 source 仍需资格 |
| P5-D1-02 | P5 相对估值、FCF/银行锚定、隐含预期和负值政策 | ADR-0011：区间模型、保留负隐含增长、分析师来源先过资格门 | 已冻结；科学状态仍为 `not_evaluated` |
| P6-D1-01 | 第一再平衡频率 | ADR-0006：月度，周度仅敏感度 | 已冻结 |
| P6-D1-02 | 第一成本/成交参考 | ADR-0006：versioned next-session VWAP/cost | 已冻结 |
| P7-D1-01 | Timing 预测 benchmark/可交易对象 | ADR-0006：与 P6 对齐，必要时绑定 proxy | 已冻结 |
| P8-D1-01 | 文档/新闻/研报来源许可与原文保存策略 | ADR-0008 | 已冻结框架；逐源许可仍需登记 |
| P9-D1-01 | Incident owner 与职责映射 | ADR-0009 | 已冻结 |

### D2：配置化，不阻塞领域骨架

- 风险预算、单股/行业/换手/参与率上限；
- 主动 Timing 最大组合影响，Shadow 阶段固定 0；
- 监控 SLO、PSI、IC decay、calibration 和 residual 阈值；
- Agent 模型、预算、通知渠道；
- P10 soak 时长和演练频率。

## 7. “规划齐全”仍不能消除的非开发风险

即使全部 Spec/Plan 获批，后续也不可能只剩机械编码：

- 数据供应商可能没有合法可保存的历史 PIT、修订或精确可知时间；
- 因子、Timing 或事件模型可能科学失败；
- 外部回测引擎和数据口径可能产生需要解释的真实差异；
- Paper soak 必须经过日历时间，不能用单元测试压缩；
- Limited Live 永远需要新的用户授权、安全和法律决策。

可以做到的是：这些失败不再迫使架构返工，而是被既定合同保存为 blocker、负结果、Review 或 Incident。

## 8. 本轮规划完成条件

- `docs/plans/README.md` 定义执行纪律和索引；
- Roadmap Step 1–10 均有独立 Spec/Plan 包；
- 原型到运行时有独立 PUI Track、31 页差距矩阵和三轴完成定义；
- 每个包列出精确关联、对象、存储/API/UI、TDD 任务、命令和 Evidence；
- D0/D1/D2/AUTH 决策集中登记；
- README 增加规划入口；
- 不修改 `platform/` 实现，不安装 Superpowers，不执行任何外部写入或交易动作。
