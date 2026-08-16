import type { DeskSection as DeskSectionData, WorkspaceStateKind } from './deskTypes'

export interface DeskMetric {
  label: string
  value: string
}

export interface MetricField {
  key: string
  label: string
  format?: (value: unknown) => string
}

/**
 * Resolve the six-state view for one section.
 *
 * The client contributes only what it knows — whether the request is in flight
 * or failed.  Everything else is the server's data fact, passed through
 * untouched: the browser must not upgrade, downgrade or infer a status.
 */
export function resolveSectionState(
  section: DeskSectionData | undefined,
  { loading, error }: { loading?: boolean; error?: string },
): WorkspaceStateKind {
  if (loading) return 'loading'
  if (error) return 'error'
  return section?.status ?? 'unavailable'
}

export function coverageText(coverage: Record<string, unknown>): string {
  return Object.entries(coverage)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(' · ')
}

/**
 * Reason text for a non-ready section.
 *
 * Server blockers win: they are the authoritative explanation.  Coverage is the
 * fallback for a partial section, because a bare "partial" label would tell the
 * operator nothing actionable.
 */
export function noticeReason(section: DeskSectionData | undefined, error?: string): string {
  if (error) return error
  if (!section) return '服务端未返回该分区。'
  if (section.blockers.length > 0) {
    return section.blockers.map((item) => item.reason).join(' ')
  }
  if (section.status === 'partial' && Object.keys(section.coverage).length > 0) {
    return `覆盖范围：${coverageText(section.coverage)}`
  }
  if (section.status === 'empty') return '该能力可用，但当前没有符合条件的记录。'
  return ''
}

/**
 * Read a metric list out of an untyped section payload.
 *
 * The payload is `unknown` on purpose: its shape belongs to the server, and the
 * client must not assume fields exist.  A missing or malformed value yields no
 * metric rather than a zero, because a fabricated zero would read as real data.
 */
export function metricsFromPayload(
  payload: unknown,
  fields: ReadonlyArray<MetricField>,
): DeskMetric[] {
  if (payload === null || typeof payload !== 'object') return []
  const source = payload as Record<string, unknown>
  const metrics: DeskMetric[] = []
  for (const field of fields) {
    const value = source[field.key]
    if (value === undefined || value === null) continue
    metrics.push({
      label: field.label,
      value: field.format ? field.format(value) : String(value),
    })
  }
  return metrics
}

export function coverageMetrics(section: DeskSectionData): DeskMetric[] {
  return Object.entries(section.coverage).map(([key, value]) => ({
    label: key,
    value: String(value),
  }))
}
