import { Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import { DeskMetricList } from './DeskMetricList'
import { DeskSection } from './DeskSection'
import { metricsFromPayload } from './deskState'
import type { DeskSection as DeskSectionData } from './deskTypes'

interface SectionProps {
  section: DeskSectionData
  loading?: boolean
  error?: string
}

/**
 * Screen shift rows as projected by the server.
 *
 * Ranks, rank changes and trust labels are all computed server-side; this table
 * only formats them.  Recomputing any of it in the browser would create a second
 * source of truth for a governed number.
 */
interface ScreenRow {
  security_id?: string
  symbol?: string
  display_name?: string
  industry?: string
  rank?: { display?: string }
  rank_change?: { display?: string; direction?: string }
  trust_state?: string
  freshness?: string
}

function screenRows(payload: unknown): ScreenRow[] {
  if (payload === null || typeof payload !== 'object') return []
  const screen = (payload as Record<string, unknown>).screen
  if (screen === null || typeof screen !== 'object') return []
  const rows = (screen as Record<string, unknown>).rows
  return Array.isArray(rows) ? (rows as ScreenRow[]) : []
}

export function DataHealthSection({ section, loading, error }: SectionProps) {
  const metrics = metricsFromPayload(section.payload, [
    { key: 'datasets_total', label: 'Dataset 总数' },
    { key: 'datasets_with_quality_report', label: '已有质量报告' },
    { key: 'quality_reports_failed', label: '质量检查失败' },
    { key: 'latest_dataset_created_at', label: '最新入库时间' },
  ])
  return (
    <DeskSection error={error} loading={loading} section={section} subtitle="Data Health">
      <DeskMetricList metrics={metrics} />
    </DeskSection>
  )
}

export function ScreenShiftSection({ section, loading, error }: SectionProps) {
  const rows = screenRows(section.payload)
  const columns: ColumnsType<ScreenRow> = [
    { title: '代码', dataIndex: 'symbol', width: 96 },
    { title: '公司', dataIndex: 'display_name', width: 120 },
    { title: '行业', dataIndex: 'industry', width: 96 },
    {
      title: '综合排名',
      key: 'rank',
      width: 90,
      render: (_, row) => row.rank?.display ?? '—',
    },
    {
      title: '排名变化',
      key: 'rank_change',
      width: 90,
      // An unavailable change shows an em dash, never a zero.
      render: (_, row) => row.rank_change?.display ?? '—',
    },
    { title: '置信度', dataIndex: 'trust_state', width: 96 },
    { title: '鲜度', dataIndex: 'freshness', width: 72 },
  ]
  return (
    <DeskSection
      error={error}
      loading={loading}
      section={section}
      subtitle="Universe Shift Tracker"
    >
      <div className="deskTableScroll">
        <Table<ScreenRow>
          columns={columns}
          dataSource={rows}
          pagination={false}
          rowKey={(row) => row.security_id ?? row.symbol ?? String(row.display_name)}
          size="small"
        />
      </div>
    </DeskSection>
  )
}

export function PortfolioTrackingSection({ section, loading, error }: SectionProps) {
  // P6 capability; the server declares it unavailable and the card shows the
  // blocker.  No simulated active share, HHI or VaR is ever rendered.
  return (
    <DeskSection
      error={error}
      loading={loading}
      section={section}
      subtitle="Portfolio Tracking"
    />
  )
}

export function TimingShadowSection({ section, loading, error }: SectionProps) {
  const metrics = metricsFromPayload(section.payload, [
    { key: 'forecasts_total', label: 'Shadow 记录数' },
    { key: 'latest_effective_session', label: '最新生效交易日' },
    { key: 'latest_model_lifecycle', label: '模型生命周期' },
    { key: 'latest_passive_exposure_ratio', label: '被动敞口比例' },
  ])
  return (
    <DeskSection error={error} loading={loading} section={section} subtitle="影子跟踪">
      <DeskMetricList metrics={metrics} />
    </DeskSection>
  )
}

export function EventFeedSection({ section, loading, error }: SectionProps) {
  // P8 capability; unavailable until the event evidence chain exists.  LLM or
  // unverified text must never appear here as an authoritative event.
  return (
    <DeskSection error={error} loading={loading} section={section} subtitle="Basic Feeds" />
  )
}

interface PendingReview {
  review_id?: string
  factor_version_id?: string
  decision?: string
  scope?: string
  decided_at?: string
}

export function PendingTaskSection({ section, loading, error }: SectionProps) {
  const payload = section.payload
  const reviews: PendingReview[] =
    payload !== null && typeof payload === 'object' && Array.isArray(
      (payload as Record<string, unknown>).reviews,
    )
      ? ((payload as Record<string, unknown>).reviews as PendingReview[])
      : []
  return (
    <DeskSection error={error} loading={loading} section={section} subtitle="Pending Tasks">
      <ul className="deskFeed">
        {reviews.map((item) => (
          <li className="deskFeed__item" key={item.review_id}>
            <p className="deskFeed__title">{item.factor_version_id}</p>
            <div className="deskFeed__meta">
              <span>{item.decision}</span>
              <span>{item.scope}</span>
              <span>{item.decided_at}</span>
            </div>
          </li>
        ))}
      </ul>
    </DeskSection>
  )
}

interface ActiveFailure {
  job_id?: string
  provider_id?: string
  status?: string
  failure_reasons?: string[]
  updated_at?: string
}

export function ActiveFailureSection({ section, loading, error }: SectionProps) {
  const payload = section.payload
  const failures: ActiveFailure[] =
    payload !== null && typeof payload === 'object' && Array.isArray(
      (payload as Record<string, unknown>).failures,
    )
      ? ((payload as Record<string, unknown>).failures as ActiveFailure[])
      : []
  return (
    <DeskSection error={error} loading={loading} section={section} subtitle="Active Failures">
      <ul className="deskFeed">
        {failures.map((item) => (
          <li className="deskFeed__item" key={item.job_id}>
            <p className="deskFeed__title">
              {(item.failure_reasons ?? []).join('；') || item.status}
            </p>
            <div className="deskFeed__meta">
              <span>{item.provider_id}</span>
              <span>{item.job_id}</span>
              <span>{item.updated_at}</span>
            </div>
          </li>
        ))}
      </ul>
    </DeskSection>
  )
}
