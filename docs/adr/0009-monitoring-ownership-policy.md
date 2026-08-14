# ADR-0009：监控与 Incident 责任边界

- 状态：Accepted
- 日期：2026-08-14

## 背景

P9 的告警必须指向可行动 owner。若所有异常都归为“系统错误”，无法形成数据、研究、组合和执行的职责分离，也无法验证升级和恢复。

## 决策

第一版使用四类服务端 owner scope：

- `data`：来源、摄取、映射、coverage、freshness、PIT 和 lineage；
- `research`：feature/factor/model/View/Timing/Event/Agent 和科学验证；
- `portfolio`：policy、target、risk、capacity、backtest 和非执行归因；
- `execution`：Paper OMS、broker event、fill/position/cash、reconciliation 和 kill switch。

跨域 Incident 可以有一个 primary owner 和多个 contributors，但只能由权限策略允许的主体确认、转派、缓解和关闭。阈值、升级时限和通知渠道配置化并绑定版本；前端不能改变 owner scope 或严重度规则。

## 结果

P9 可以实现确定的 Alert/Incident 路由、职责分离和故障注入测试。真实组织人员、值班表和通知渠道在 Gate 前配置，不进入领域核心。
