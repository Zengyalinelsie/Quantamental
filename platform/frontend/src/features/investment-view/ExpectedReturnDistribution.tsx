import type { ExpectedReturnDistributionProjection } from './investmentViewProjection'

interface ExpectedReturnDistributionProps {
  distribution: ExpectedReturnDistributionProjection
  confidence: string
  horizon: string
}

const distributionFields = [
  ['point', '点估计'],
  ['p10', 'P10'],
  ['p50', 'P50'],
  ['p90', 'P90'],
  ['downside', 'Downside'],
] as const

export function ExpectedReturnDistribution({
  confidence,
  distribution,
  horizon,
}: ExpectedReturnDistributionProps) {
  return (
    <section aria-labelledby="expected-return-heading" className="investmentViewSection">
      <header className="investmentViewSection__heading">
        <div>
          <p className="investmentViewSection__eyebrow">EXPECTED RETURN</p>
          <h3 id="expected-return-heading">收益分布</h3>
        </div>
        <div className="investmentViewSection__meta">
          <span>{horizon}</span>
          <span>置信度 {confidence}</span>
        </div>
      </header>
      <div className="returnDistributionGrid">
        {distributionFields.map(([field, label]) => (
          <article className={`returnMetric returnMetric--${field}`} key={field}>
            <span>{label}</span>
            <strong>{distribution[field].display}</strong>
            <code>{distribution[field].raw}</code>
          </article>
        ))}
      </div>
    </section>
  )
}
