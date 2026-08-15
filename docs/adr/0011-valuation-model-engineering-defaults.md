# ADR-0011：P5 估值工程模型默认

- 状态：Accepted
- 日期：2026-08-14
- 决策 ID：`P5-D1-02`
- 授权：用户明确批准“推荐默认”

## 背景

`SPEC-018` 要求历史/行业/同业相对估值、基本面锚定估值、当前价格隐含预期、合格分析师修正和区间输出，但此前没有冻结会改变研究结果的具体工程公式。P5 需要一组 provider-neutral、可手算、可版本化且失败关闭的基线，才能继续实现；该基线不等于科学有效，也不能产生伪精确目标价。

## 决策

### 相对估值

- E/P、B/P、FCF yield 使用 `subject / reference - 1`；
- EV/EBIT 使用 `reference / subject - 1`，保持“正值表示相对更便宜”的方向；
- historical、industry、peer 分开保留，不合成未经验证的总分；
- subject/reference 非正、缺失、单位/metric/时点/trust 不一致时 `unavailable`，不得填零；
- 三类参考全部可用才是模型级 `quantified`，部分可用为模型级 `partial`。`partial` 不是第五种 `InvestmentComponent` status。

### 非金融基本面锚定

使用 FCF growing perpetuity 区间：

```text
V_low  = FCF_low  × (1 + g_low)  / (r_high - g_low)
V_high = FCF_high × (1 + g_high) / (r_low  - g_high)
```

要求 `r_low > g_high`、FCF/价格为正且全部参数有限。输出 fair-value 和 expected-return 区间，不输出单点目标价。

### 银行基本面锚定

使用 justified P/B。由于该式对增长率的单调方向取决于 ROE、折现率之间的关系，区间不是固定挑一组端点，而是对 `B/ROE/r/g` 的全部上下端点组合计算后取 `min/max`：

```text
V(B, ROE, r, g) = B × (ROE - g) / (r - g)
[V_low, V_high] = envelope(V over all declared interval endpoints)
```

要求 book value、价格为正，`r_low > g_high`，并且假设组合产生非负且有序区间。银行不使用 FCF/EV-EBIT 口径冒充可比估值。

### 当前价格隐含预期

非金融反解增长：

```text
g = (P × r - FCF) / (P + FCF)
```

银行反解 ROE，并同样对 `B/r/g` 全部端点取包络，覆盖 P/B 小于、等于或大于 1 时增长率方向变化：

```text
ROE = (P / B) × (r - g) + g
[ROE_low, ROE_high] = envelope(ROE over all declared interval endpoints)
```

区间使用保守参数端点。隐含增长为负时保留负值，不钳制为零；负值可能表达市场隐含衰退，隐藏它会改变语义。

### 分析师一致预期修正

仅当 adapter 已证明来源、用途、时间和许可合格时允许量化：

```text
revision_low  = current_low  - prior_high
revision_high = current_high - prior_low
midpoint_revision = midpoint(current) - midpoint(prior)
```

没有合格来源时必须 `unavailable`。非空 `source_policy_version` 本身不构成运行时资格证明。

## 版本、冻结与状态

- 公式版本为 `v0`，行业口径版本为 `industry-valuation-policy:v0`；
- 价格、每股基本面和利率/增长假设分别携带 provenance；价格和基本面明确使用 `CURRENCY_PER_SHARE`，利率使用 `RATIO`；输出 lineage 是三类 provenance 的闭合并集；
- 纯函数 fixture 可以单独手算，但不注册新的 application 输入入口。2026-08-15 的 runtime 实现继续以 `ValuationImprovementInputBundle` 为唯一真源：legacy v1 原 JSON/hash 只读兼容且不得继续执行；v2 冻结 relative reference、anchor raw input、analyst revision、industry policy、模型与 compiler 版本，并由既有 orchestration 运行时调用，不增加第二输入入口；
- 缺 FCF/book/价格/假设时使用显式 unavailable input/result，不允许为了调用公式而补数值；historical、industry、peer 三类参考必须各自提供数值或 unavailable reason，不能静默省略；
- 分析师数值必须携带 provider field policy、用途、许可证据、审批、有效期和 qualification 时间组成的 attestation，并冻结目标期、预测期限、current/prior snapshot 和 consensus definition version；current/prior 快照分别携带 provider ID 与 provenance，且两者必须与 attested provider 完全一致；
- 领域 dataclass 只能校验资格证据的结构与一致性，不能凭自身证明审批或许可证真实存在；未来 adapter 必须从治理 registry/repository 精确读取资格记录后才能构造数值输入；
- 全部模型固定 `scientific_status=not_evaluated`；测试通过只证明工程合同，不证明样本外、成本后或统计意义上的科学有效；
- P11 仍未授权，本决策不增加交易、账户或执行能力。

## 后果

- P5 已具备确定性区间、明确 unavailable/partial 状态和安全 frozen v2 runtime 接线的工程基线；
- 真实数据不满足 FCF、可比参考或分析师资格时，真实 bundle 继续失败关闭或保持分项 unavailable；
- 后续如改变公式、端点组合、非正值政策或行业适用范围，必须产生新公式版本、ADR 和新 frozen artifact，不能重写旧结果。
