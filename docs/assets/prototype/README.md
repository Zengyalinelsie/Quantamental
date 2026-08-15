# Figma 原型可恢复资产

本目录保存可重新导入 Figma 的原型资产，避免浏览器会话或 Figma Agent 配额导致关键 Frame 无法恢复。

当前只有下表两页具有仓库内可恢复的精确 SVG。它们不能代表 14 个关键 1440 Frame 全部已有本地资产，
更不能代表 31 页和 320/768/1024 三档已有逐页高保真设计。逐页现状见
`docs/22-prototype-runtime-gap-audit.md`，运行时交付计划见
`docs/plans/track-00-prototype-runtime-delivery.md`。

| 文件 | Figma Frame | 状态 |
|---|---|---|
| `investment-view.svg` | `security-investmentview` | XML 与 1440 px 本地渲染已复验；2026-08-13 已作为可编辑矢量导入云端 Figma，Frame 为 `1440 × 1200`，位置 `X=4868, Y=-900` |
| `security-overview-fused.svg` | `security-overview-600519-fused-v2` | XML 与本地渲染已复验；2026-08-14 已作为可编辑矢量导入云端 Figma，Frame 为 `1440 × 1900`，位置 `X=21148, Y=-900`，节点 `24:400` |

导入后保持 `DESIGN FIXTURE / 非生产数据` 标识；示例数字不连接运行时 API 或数据库，也不代表
`pit_verified` 或模型科学有效。

## 2026-08-13 Chrome/Figma 验收

- 使用当前已登录且具有 owner 权限的 Chrome/Figma 会话打开精确节点；
- 顶层 Frame 已命名为 `security-investmentview`，并保留 quantified、constrained、unavailable、
  not_applicable、显式 residual、Decimal 闭合和审批禁用语义；
- Data Mode 与 Deployment Stage 分轴展示；unavailable/not_applicable 未填 0；
- 唯一明显孤立的顶层 `Rectangle`（`1440 × 40`、位于原点、无子层）已删除；
- 14 个关键业务页在 `Y=-900` 排列；大型状态机移到 `Y=2200`，31 页蓝图移到 `Y=4200`，
  不再覆盖关键业务页；
- Prototype 只保留从 `desk-daily-workstation` 开始的 `Flow 2`；黄金路径已连续运行至
  `portfolios-attribution`；
- InvestmentView 的“打开证据”进入 `13-data-quality-lineage`，该页使用单击 Back 返回来源页；
  错误的 `Drag → Back` 已清除；
- Backtest 的 blocker 卡片与 InvestmentView 的 run id 均可进入 `13-data-quality-lineage`，并复用
  已验证的 Back 返回；这些是代表入口，不表示每一个静态标签都设置了热点；
- 关键高保真页均为 1440 宽。未发现 320、768、1024 独立 Frame，三档响应式仍是文档合同，
  不是已通过的 Figma 视觉证据。

Figma 精确节点：<https://www.figma.com/design/mrt216q7X7NGqFhRjwQS3f/Fundamental-Quant-%E2%80%94-%E4%BA%A7%E5%93%81%E8%93%9D%E5%9B%BE%E4%B8%8E%E9%AB%98%E4%BF%9D%E7%9C%9F%E5%8E%9F%E5%9E%8B?node-id=9-238&t=R538S55yXyPUxZr9-0>

## 2026-08-14 Security Overview 融合页

- 只读参考 `stock-analysis` 示例 HTML，把结论置顶改写为可证伪研究命题，并吸收公司画像、
  价值链、财务轨迹、Catalysts/Invalidators、同业对比和持续跟踪；未迁入买卖、仓位或目标价承诺；
- 保留现有平台的 Research Time、Data Mode、Deployment Stage、Universe、四问、Evidence coverage、
  blocker、审批 Gate 和 InvestmentView readiness；Data Mode 与 Deployment Stage 分轴；
- 示例数值全部标识 `DESIGN FIXTURE / 非生产数据`；`normalized_current` 明确不是 PIT 验证；
  `UNAVAILABLE` 显示 `—`，`NOT_APPLICABLE` 不作为缺失替代；证据不完整时“提交”保持禁用；
- 旧 `security-overview-600519` 保留作对照；`research-universe-screen` 的 Prototype 目标已改为
  `security-overview-600519-fused-v2`，其顶层单击再进入 `security-investmentview`；两段跳转已在
  Chrome/Figma 演示模式实际运行；
- 云端 Frame 为 `1440 × 1900`。未制作 320、768、1024 独立 Frame，因此三档仍未通过响应式视觉验收；
- 原型和测试通过不代表模型科学有效。

融合页精确节点：<https://www.figma.com/design/mrt216q7X7NGqFhRjwQS3f/Fundamental-Quant-%E2%80%94-%E4%BA%A7%E5%93%81%E8%93%9D%E5%9B%BE%E4%B8%8E%E9%AB%98%E4%BF%9D%E7%9C%9F%E5%8E%9F%E5%9E%8B?node-id=24-400&t=R538S55yXyPUxZr9-0>

## 2026-08-15 运行时差距说明

- 当前运行时 Design Parity 为 0/31；P5 的四视口验收只覆盖已有 empty/unavailable 页面合同；
- 开发任何目标页前应先取得精确 Figma node 的结构化 design context；本目录两份 SVG 仅是工具受限时
  对应 Security/InvestmentView 的可恢复真源；
- Figma Starter/View seat 的 MCP 调用额度已用尽，本轮没有取得新的结构化节点上下文；该限制必须作为
  PUI-00 的设计输入阻断保留，不能用缩放截图推测其余页面并声称高保真；
- Figma 中的示例数字始终是 DESIGN FIXTURE，严禁进入开发或生产运行时。
