# P5 实现与验证证据

> 状态快照：2026-08-14  
> 范围：P5 当前工程进度；本次新增 Frozen InvestmentView Artifact application export  
> Gate：P5 Capability Gate 仍未通过

## 1. Frozen InvestmentView Artifact application export

本工作包实现 provider-neutral 的确定性 Frozen Artifact 导出器，复用现有
`ExpectedReturnLedgerService`、`GovernanceLedger` 和 `RawObjectStore`，没有建立第二套 View、Run、
Artifact 或对象存储合同。

实现行为：

- 只从 append-only Expected Return ledger 精确读取 `InvestmentView`；
- 对象写入前要求对应 `RunRecord.status=succeeded`；
- naive `created_at`、早于成功 Run、缺 View、缺/非成功 Run 均在对象写入前失败；
- 生成 deterministic、sort-key、紧凑 UTF-8 canonical JSON；
- envelope schema 为 `investment-view:v1`，绑定 View content hash 和完整 View document；
- payload SHA-256 同时决定 content-addressed storage 和 deterministic Artifact ID；
- View → Artifact 使用 `frozen_as`；Dataset/Feature/Model/Run/evidence 均登记 direct lineage；
- 重复导出返回相同 Artifact 且 `writes_performed=false`；
- 已存在相同 content hash 的不同 Artifact owner 会在对象写入前失败，不留下孤儿文件；
- 已存在 Artifact 但 lineage 不完整时可幂等补齐缺失边。

## 2. TDD 证据

首次定向执行结果：

```text
ModuleNotFoundError:
a_share_platform.application.investment_view_artifacts
```

最小实现后，补充 created-at 和治理 content-hash conflict 边界。最终定向结果：

```text
Ran 4 tests in 0.003s
OK
```

覆盖：canonical/content-addressed export、完整 lineage、幂等、缺 View、非成功 Run、无效时间和
治理 hash 冲突零对象写入。

## 3. 全量验证

```text
Backend unittest: 743/743 passed
Ruff: passed
mypy: 171 source files passed
compileall: passed
git diff --check: passed
Frontend Vitest: 59/59 passed
Frontend lint: passed
Frontend build: passed
```

Vite 仍报告既有 AntD 大 chunk warning；本工作包没有修改前端 bundle，也没有把 warning 隐藏或
改成通过项。

## 4. 文件

- `platform/src/a_share_platform/application/investment_view_artifacts.py`；
- `platform/src/a_share_platform/application/governance_ledger.py`；
- `platform/tests/test_investment_view_artifacts.py`。

## 5. 未完成和 Gate 边界

本工作包只完成 application/port-compatible export。以下仍未完成：

- durable PostgreSQL Governance Repository 的 Run/Artifact/Lineage 实现；
- Artifact metadata/download API、权限和 OpenAPI；
- Research/InvestmentView 页面查看或下载入口；
- Outcome 到期 worker；
- P5 估值/改善剩余服务和 320/768/1024 最终浏览器验收；
- 真实 qualified PIT bundle、InvestmentView、Review 和 SignalSnapshot。

因此 P5 Capability Gate 仍未通过。自动测试证明工程合同按预期工作，不证明 Expected Return、
InvestmentView、因子或策略科学有效。
