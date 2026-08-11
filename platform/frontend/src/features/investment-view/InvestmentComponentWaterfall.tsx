import { Alert, Tag } from 'antd'
import type { CSSProperties } from 'react'

import type {
  ClosureProjection,
  InvestmentComponentProjection,
  InvestmentComponentStatus,
  ResidualProjection,
  WaterfallVisualProjection,
} from './investmentViewProjection'

interface InvestmentComponentWaterfallProps {
  closure: ClosureProjection
  components: InvestmentComponentProjection[]
  residual: ResidualProjection
}

const statusLabels: Record<InvestmentComponentStatus, string> = {
  quantified: '已量化',
  constrained: '受约束',
  unavailable: '不可用',
  not_applicable: '不适用',
}

const statusColors: Record<InvestmentComponentStatus, string> = {
  quantified: 'blue',
  constrained: 'gold',
  unavailable: 'default',
  not_applicable: 'default',
}

function visualStyle(visual: WaterfallVisualProjection): CSSProperties {
  return {
    '--waterfall-start': `${visual.start_percent}%`,
    '--waterfall-width': `${visual.width_percent}%`,
  } as CSSProperties
}

function EvidenceIds({ evidenceIds }: { evidenceIds: string[] }) {
  if (evidenceIds.length === 0) {
    return <span className="waterfallRow__evidenceEmpty">未绑定证据</span>
  }
  return (
    <span className="waterfallRow__evidence">
      {evidenceIds.map((id) => <code key={id}>{id}</code>)}
    </span>
  )
}

function WaterfallRow({
  component,
}: {
  component: InvestmentComponentProjection
}) {
  return (
    <article
      className={`waterfallRow waterfallRow--${component.status}`}
      data-testid={`investment-component-${component.component}`}
    >
      <div className="waterfallRow__identity">
        <strong>{component.label}</strong>
        <Tag color={statusColors[component.status]}>{statusLabels[component.status]}</Tag>
      </div>
      <div className="waterfallTrack" aria-hidden>
        {component.visual ? (
          <span
            className={`waterfallBar waterfallBar--${component.visual.direction}`}
            data-testid={`waterfall-bar-${component.component}`}
            style={visualStyle(component.visual)}
          />
        ) : null}
      </div>
      <div className="waterfallRow__value">
        {component.status === 'quantified' && component.contribution
          ? <strong>{component.contribution.display}</strong>
          : <span aria-label={`${component.label}没有数值贡献`}>—</span>}
      </div>
      <p>{component.reason}</p>
      <EvidenceIds evidenceIds={component.evidence_ids} />
    </article>
  )
}

function ResidualRow({ residual }: { residual: ResidualProjection }) {
  return (
    <article
      className={`waterfallRow waterfallRow--residual waterfallRow--${residual.status}`}
      data-testid="investment-component-residual"
    >
      <div className="waterfallRow__identity">
        <strong>Residual</strong>
        <Tag color={statusColors[residual.status]}>{statusLabels[residual.status]}</Tag>
      </div>
      <div className="waterfallTrack" aria-hidden>
        {residual.visual ? (
          <span
            className={`waterfallBar waterfallBar--residual waterfallBar--${residual.visual.direction}`}
            data-testid="waterfall-bar-residual"
            style={visualStyle(residual.visual)}
          />
        ) : null}
      </div>
      <div className="waterfallRow__value">
        {residual.status === 'quantified' && residual.contribution
          ? <strong>{residual.contribution.display}</strong>
          : <span aria-label="Residual 没有数值贡献">—</span>}
      </div>
      <p>{residual.reason}</p>
      <EvidenceIds evidenceIds={residual.evidence_ids} />
    </article>
  )
}

function ClosureResult({ closure }: { closure: ClosureProjection }) {
  const title = closure.status === 'passed'
    ? '服务端闭合通过'
    : closure.status === 'failed'
      ? '服务端闭合失败'
      : '服务端闭合不可用'
  const type = closure.status === 'passed' ? 'success' : closure.status === 'failed' ? 'error' : 'warning'
  return (
    <Alert
      className="investmentViewClosure"
      data-testid="investment-view-closure"
      description={(
        <span>
          检查器 <code>{closure.checked_by}</code>
          {' · '}差异 {closure.difference ?? '不可用'}
          {' · '}容差 {closure.tolerance}
          {closure.displayed_total ? ` · 闭合点估计 ${closure.displayed_total}` : ''}
        </span>
      )}
      showIcon
      title={title}
      type={type}
    />
  )
}

export function InvestmentComponentWaterfall({
  closure,
  components,
  residual,
}: InvestmentComponentWaterfallProps) {
  return (
    <section aria-labelledby="waterfall-heading" className="investmentViewSection">
      <header className="investmentViewSection__heading">
        <div>
          <p className="investmentViewSection__eyebrow">SERVER-COMPILED</p>
          <h3 id="waterfall-heading">分项贡献与闭合</h3>
        </div>
        <span className="investmentViewSection__note">坐标、贡献和闭合均来自冻结服务端投影</span>
      </header>
      <div className="waterfallScale" aria-hidden>
        <span>负向</span><span>0</span><span>正向</span>
      </div>
      <div className="waterfallRows">
        {components.map((component) => (
          <WaterfallRow component={component} key={component.component} />
        ))}
        <ResidualRow residual={residual} />
      </div>
      <ClosureResult closure={closure} />
    </section>
  )
}
