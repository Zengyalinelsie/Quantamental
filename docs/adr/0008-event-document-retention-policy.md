# ADR-0008：事件文档来源与保存边界

- 状态：Accepted
- 日期：2026-08-14

## 背景

P8 需要公告、新闻、研报和其他事件证据。不同来源的原文保存、再分发和模型处理权限不同，不能为了 Agent 检索方便把所有内容永久复制进平台。

## 决策

1. 交易所、上市公司和依法允许保存的正式公告优先保存合格原文、hash、published/fetched/available time 和修订关系。
2. 新闻、研报和商业数据库内容逐源检查许可：允许保存时进入受限 raw evidence；不允许保存时只保留许可允许的 metadata、stable reference、hash 或短期缓存。
3. 原文不可保存不等于可以让 LLM 复述后长期保存；Agent 输出仍受原来源许可和引用合同约束。
4. correction/retraction 不覆盖旧版本，必须追加新版本并触发下游 Review。
5. 通知只引用 Frozen Artifact 和许可允许的摘要/链接，不重新生成权威数值。

## 结果

P8 Document/Event/Agent 领域核心保持 provider-neutral。每个 adapter 在批量摄取前仍需字段和许可登记；未通过时失败关闭。
