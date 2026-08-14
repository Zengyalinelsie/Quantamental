# ADR-0007：严格 PIT 主源资格探针与失败关闭策略

- 状态：Accepted
- 日期：2026-08-14
- 用户批准：按推荐默认冻结；免费/current 来源不得提升为 PIT

## 背景

现有 BaoStock、AkShare、Futu、CNInfo 和 current 财务批次支持私人本地研究，但不能证明完整的历史首次披露、修订和当时可知时间。P4/P5 strict 路径需要重新选择合格主源，而用户拥有 Wind、同花顺内部 Factor Service 和三表抽取服务等潜在资产。

## 决策

1. strict PIT 主源不按品牌预设，必须先做字段级资格探针。
2. 探针优先顺序为用户已有 Wind、同花顺内部 Factor Service/数据服务、内部三表抽取服务；根据财务/公告/历史成分/行情等域分别评估，不强求单一供应商覆盖全部字段。
3. 每个候选源必须验证：认证、字段定义、单位、报告期、首次披露、修订、published/available time、历史成分有效期、退市覆盖、保存许可、用途许可、限流和可恢复性。
4. 只有探针证据和许可均通过的字段才可进入新的 Accepted source ADR 和 `pit_verified` importer。
5. 若全部候选均不合格，对应 strict domain 保持 unavailable；不得从 current 值推断历史修订或补造 `available_at`。
6. BaoStock/AkShare/Futu/CNInfo 继续遵守 ADR-0002/0003/0004 的字段与用途上限。

## 执行门

- 探针默认 read-only/dry-run，不得批量保存未批准数据；
- 不在凭证、许可和字段资格未知时启动 bulk backfill；
- probe 结果写入 `docs/14-data-source-catalog-and-agent-routing.md`，主源选择另写 Accepted ADR；
- 多源冲突必须保留 observation 和选择证据，不得静默混值。

## 结果

Step 2 的资格探针可以立即开发和执行安全的只读检查，但 strict 批量 importer 仍以“字段主源 ADR Accepted”为前置 Gate。这个外部事实依赖不是计划缺口。
