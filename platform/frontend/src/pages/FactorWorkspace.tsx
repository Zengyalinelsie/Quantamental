import {
  Alert,
  Card,
  Descriptions,
  Divider,
  Tabs,
  Tag,
} from 'antd'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useSearchParams } from 'react-router-dom'

import { PageHeading } from '../components/PageHeading'
import { WorkspaceState } from '../components/WorkspaceState'

type FactorRunStatus = 'planned' | 'running' | 'succeeded' | 'failed'

interface FactorStatisticView {
  rankIc: string | null
  confidenceInterval: [string, string] | null
  turnover: string | null
  coverage: string | null
}

interface QuantilePoint {
  label: string
  returnValue: string
}

interface DecayPoint {
  horizon: string
  rankIc: string
}

export interface FactorExperimentView {
  experimentId: string
  factorName: string
  status: FactorRunStatus
  failureReason: string | null
  sampleLabel: 'in_sample' | 'validation' | 'out_of_sample'
  multipleTestingFamily: string
  statistics: FactorStatisticView
  quantiles: QuantilePoint[]
  decay: DecayPoint[]
}

interface TimingBaselineView {
  forecastId: string
  session: string
  status: 'baseline'
  dataMode: 'current_research'
  deploymentStage: 'shadow'
}

interface CorrelationPairView {
  leftFactor: string
  rightFactor: string
  correlation: string | null
}

interface ProductionFactorView {
  factorVersionId: string
  approvalId: string
  approvedScope: 'research_backtest' | 'shadow' | 'paper' | 'limited_live'
}

export interface FactorWorkspaceSnapshot {
  systemAsOf: string
  dataMode: 'current_research' | 'strict_historical'
  deploymentStage: 'research' | 'shadow' | 'paper' | 'limited_live'
  experiments: FactorExperimentView[]
  timingBaseline: TimingBaselineView | null
  correlationPairs: CorrelationPairView[]
  productionVersions: ProductionFactorView[]
}

const factorDefinitions = [
  {
    id: 'factor:quality:v0',
    name: 'Quality V0',
    state: 'partial',
    detail: '行业模板和 4 家手算已实现；稀释、审计/监管、退市与财务异常仍是 coverage gap。',
  },
  {
    id: 'factor:valuation-expectation-gap:v0',
    name: 'Valuation Expectation Gap V0',
    state: 'partial',
    detail: '行业适用相对估值与预期区间合同已实现；真实 PIT 截面、同业分布和情景敏感度未完成。',
  },
  {
    id: 'factor:fundamental-improvement:v0',
    name: 'Fundamental Improvement V0',
    state: 'baseline',
    detail: 'level / trend / acceleration / breadth / confidence 纯函数已实现；尚无合格 PIT 截面结果。',
  },
] as const

const tabLabels = [
  ['catalog', 'Catalog'],
  ['alpha-model', 'Alpha Model'],
  ['timing-lab', 'Timing Lab'],
  ['experiments', 'Experiments'],
  ['correlation-monitor', 'Correlation Monitor'],
  ['production', 'Production'],
] as const

function CatalogPanel({ snapshot }: { snapshot?: FactorWorkspaceSnapshot }) {
  return (
    <div className="factorCatalog">
      <Alert
        title={snapshot
          ? `读取到 ${snapshot.experiments.length} 个持久化实验视图；SYSTEM AS OF ${snapshot.systemAsOf}`
          : '当前只展示已提交的工程定义；没有注入运行时演示结果。'}
        showIcon
        type={snapshot ? 'info' : 'warning'}
      />
      <div className="factorDefinitionGrid">
        {factorDefinitions.map((definition) => (
          <Card key={definition.id} size="small" title={definition.name}>
            <div className="factorDefinitionMeta">
              <Tag>{definition.state}</Tag>
              <Tag color="gold">not_evaluated</Tag>
            </div>
            <code>{definition.id}</code>
            <p>{definition.detail}</p>
          </Card>
        ))}
      </div>
    </div>
  )
}

function ExperimentCharts({ experiment }: { experiment: FactorExperimentView }) {
  const quantiles = experiment.quantiles.map((point) => ({
    name: point.label,
    value: Number(point.returnValue),
  }))
  const decay = experiment.decay.map((point) => ({
    name: point.horizon,
    value: Number(point.rankIc),
  }))
  return (
    <div className="factorChartGrid">
      <section aria-label="分位数组合收益图" className="factorChart" role="img">
        <h4>Quantile return</h4>
        <ResponsiveContainer height={190} width="100%">
          <BarChart data={quantiles}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="name" />
            <YAxis width={54} />
            <Tooltip />
            <Bar dataKey="value" fill="#3157a4" />
          </BarChart>
        </ResponsiveContainer>
      </section>
      <section aria-label="Rank IC 衰减图" className="factorChart" role="img">
        <h4>Rank IC decay</h4>
        <ResponsiveContainer height={190} width="100%">
          <LineChart data={decay}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="name" />
            <YAxis width={54} />
            <Tooltip />
            <Line dataKey="value" dot stroke="#3157a4" type="monotone" />
          </LineChart>
        </ResponsiveContainer>
      </section>
    </div>
  )
}

function ExperimentsPanel({ snapshot }: { snapshot?: FactorWorkspaceSnapshot }) {
  if (!snapshot || snapshot.experiments.length === 0) {
    return (
      <WorkspaceState
        reason="尚无持久化 ExperimentRun。页面不会生成 IC、置信区间、分位数或换手率演示值。"
        state="empty"
        title="尚无实验记录"
      />
    )
  }
  return (
    <div className="experimentList">
      {snapshot.experiments.map((experiment) => (
        <Card
          extra={experiment.status === 'failed'
            ? <Tag color="error">失败保留</Tag>
            : <Tag color="processing">{experiment.status}</Tag>}
          key={experiment.experimentId}
          title={experiment.factorName}
        >
          <code>{experiment.experimentId}</code>
          <Descriptions
            column={{ xs: 1, sm: 2, lg: 4 }}
            items={[
              { key: 'sample', label: '样本标识', children: experiment.sampleLabel },
              {
                key: 'family',
                label: '多重检验 family',
                children: experiment.multipleTestingFamily,
              },
              {
                key: 'rank-ic',
                label: 'Rank IC',
                children: experiment.statistics.rankIc ?? '—',
              },
              {
                key: 'ci',
                label: '置信区间',
                children: experiment.statistics.confidenceInterval
                  ? `[${experiment.statistics.confidenceInterval.join(', ')}]`
                  : '—',
              },
              {
                key: 'turnover',
                label: 'Turnover',
                children: experiment.statistics.turnover ?? '—',
              },
              {
                key: 'coverage',
                label: 'Coverage',
                children: experiment.statistics.coverage ?? '—',
              },
            ]}
            size="small"
          />
          {experiment.failureReason ? (
            <Alert showIcon title={experiment.failureReason} type="error" />
          ) : null}
          <Divider />
          <ExperimentCharts experiment={experiment} />
        </Card>
      ))}
    </div>
  )
}

function CorrelationPanel({ snapshot }: { snapshot?: FactorWorkspaceSnapshot }) {
  if (!snapshot || snapshot.correlationPairs.length === 0) {
    return (
      <WorkspaceState
        reason="尚无通过数据资格门的因子对；不会把缺失相关系数显示为 0。"
        state="empty"
        title="尚无相关性矩阵"
      />
    )
  }
  return (
    <div className="correlationList">
      {snapshot.correlationPairs.map((pair) => (
        <Card key={`${pair.leftFactor}:${pair.rightFactor}`} size="small">
          <strong>{pair.leftFactor} × {pair.rightFactor}</strong>
          <span>{pair.correlation ?? '不可用'}</span>
        </Card>
      ))}
    </div>
  )
}

function TimingPanel({ snapshot }: { snapshot?: FactorWorkspaceSnapshot }) {
  if (!snapshot?.timingBaseline) {
    return (
      <WorkspaceState
        reason="没有可供此工作区读取的 Timing baseline 视图；不会显示模拟仓位或预测。"
        state="empty"
        title="Timing baseline 未连接"
      />
    )
  }
  const baseline = snapshot.timingBaseline
  return (
    <Card title="被动波动率 baseline">
      <Descriptions
        items={[
          { key: 'id', label: 'Forecast', children: baseline.forecastId },
          { key: 'session', label: 'Session', children: baseline.session },
          { key: 'mode', label: 'Data mode', children: baseline.dataMode },
          { key: 'stage', label: 'Deployment', children: baseline.deploymentStage },
        ]}
      />
    </Card>
  )
}

function ProductionPanel({ snapshot }: { snapshot?: FactorWorkspaceSnapshot }) {
  if (!snapshot || snapshot.productionVersions.length === 0) {
    return (
      <WorkspaceState
        reason="没有经服务端审批晋级的 FactorVersion。研究代码和测试通过不会自动进入 Production。"
        state="blocked"
        title="无获批生产因子"
      />
    )
  }
  return (
    <div className="productionList">
      {snapshot.productionVersions.map((version) => (
        <Card key={version.factorVersionId} size="small" title={version.factorVersionId}>
          <p>Approval: {version.approvalId}</p>
          <Tag>{version.approvedScope}</Tag>
        </Card>
      ))}
    </div>
  )
}

export function FactorWorkspace({ snapshot }: { snapshot?: FactorWorkspaceSnapshot }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const requested = searchParams.get('tab')
  const allowed = tabLabels.map(([key]) => key)
  const activeKey = requested && allowed.includes(requested as (typeof allowed)[number])
    ? requested
    : 'catalog'
  const items = tabLabels.map(([key, label]) => ({
    key,
    label,
    children: key === 'catalog'
      ? <CatalogPanel snapshot={snapshot} />
      : key === 'experiments'
        ? <ExperimentsPanel snapshot={snapshot} />
        : key === 'correlation-monitor'
          ? <CorrelationPanel snapshot={snapshot} />
          : key === 'timing-lab'
            ? <TimingPanel snapshot={snapshot} />
            : key === 'production'
              ? <ProductionPanel snapshot={snapshot} />
              : (
                <WorkspaceState
                  reason="当前没有通过科学验证并获批的因子，Alpha Model 保持空状态。"
                  state="blocked"
                  title="Alpha Model 未启用"
                />
              ),
  }))
  return (
    <div className="workspacePage factorWorkspace">
      <PageHeading
        description="审查定义、实验、统计不确定性与晋级状态。失败结果保留，current score 不冒充历史结果。"
        extra={<Tag color="processing">P4 · ENGINEERING BASELINE</Tag>}
        eyebrow="FACTOR LAB"
        title="因子"
      />
      <Alert
        className="factorGateAlert"
        title="P4 Capability Gate 尚未通过"
        description="当前实现属于工程 baseline；完整 PIT 截面、独立统计交叉验证、审批生命周期和真实广覆盖数据仍未齐备。"
        showIcon
        type="warning"
      />
      <Tabs
        activeKey={activeKey}
        items={items}
        onChange={(next) => {
          const updated = new URLSearchParams(searchParams)
          updated.set('tab', next)
          setSearchParams(updated, { replace: true })
        }}
      />
    </div>
  )
}
