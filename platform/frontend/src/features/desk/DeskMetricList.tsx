import type { DeskMetric } from './deskState'

export function DeskMetricList({ metrics }: { metrics: DeskMetric[] }) {
  if (metrics.length === 0) return null
  return (
    <dl className="deskMetrics">
      {metrics.map((metric) => (
        <div className="deskMetric" key={metric.label}>
          <dt className="deskMetric__label">{metric.label}</dt>
          <dd className="deskMetric__value">{metric.value}</dd>
        </div>
      ))}
    </dl>
  )
}
