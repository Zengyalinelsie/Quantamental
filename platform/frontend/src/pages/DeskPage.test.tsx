import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { DeskProjection } from '../api/client'
import type { ResponseContext } from '../api/client'
import { DeskPage } from './DeskPage'

const context: ResponseContext = {
  as_of: '2026-08-15T01:35:00Z',
  system_as_of: '2026-08-15T01:35:10Z',
  data_mode: 'current_research',
  deployment_stage: 'research',
  trust_state: 'normalized_current',
  dataset_version_ids: [],
  model_version_ids: [],
  run_id: null,
  coverage: {},
  warnings: [],
}

/**
 * Every desk projection in these tests is an explicit contract fixture.  The
 * runtime never ships one: the seven sections are always resolved from the
 * server.  Values here are deliberately unlike the Figma DESIGN FIXTURE
 * numbers so a leak of prototype sample data would fail the assertions below.
 */
function projection(overrides: Partial<DeskProjection> = {}): DeskProjection {
  return {
    sections: [
      { key: 'data_health', status: 'unavailable', title: '数据健康', blockers: [], coverage: {}, payload: null },
      { key: 'screen_shifts', status: 'unavailable', title: '最新 Screen 排名变化', blockers: [], coverage: {}, payload: null },
      { key: 'portfolio_tracking', status: 'unavailable', title: '组合偏离与风险', blockers: [], coverage: {}, payload: null },
      { key: 'timing_shadow', status: 'unavailable', title: 'Timing Shadow', blockers: [], coverage: {}, payload: null },
      { key: 'event_feed', status: 'unavailable', title: '重大事件/公告流', blockers: [], coverage: {}, payload: null },
      { key: 'pending_tasks', status: 'unavailable', title: '因子审核与待处理', blockers: [], coverage: {}, payload: null },
      { key: 'active_failures', status: 'unavailable', title: '运行异常', blockers: [], coverage: {}, payload: null },
    ],
    ...overrides,
  }
}

function payload(data: DeskProjection, ok = true, detail = ''): Response {
  return {
    ok,
    status: ok ? 200 : 503,
    json: async () => (ok ? { data, context } : { detail }),
  } as Response
}

function renderDesk() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <DeskPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DeskPage prototype Platform Pulse', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('no longer renders the hard-coded engineering capability table', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => payload(projection())))
    renderDesk()
    expect(await screen.findByText('今日研究态势 / Platform Pulse')).toBeInTheDocument()
    // The pre-PUI-01 desk was a local capabilityRows constant, not a server
    // projection.  None of its markers may survive.
    expect(screen.queryByText('P3 · RESEARCH EVIDENCE')).not.toBeInTheDocument()
    expect(screen.queryByText('能力与数据就绪度')).not.toBeInTheDocument()
    expect(screen.queryByText('合同就绪')).not.toBeInTheDocument()
    expect(screen.queryByText(/16 项核心能力/)).not.toBeInTheDocument()
    expect(screen.queryByText('双轴 RunContext')).not.toBeInTheDocument()
    expect(screen.queryByText('PIT 时间与可信状态')).not.toBeInTheDocument()
  })

  it('renders all seven prototype sections from the server projection', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => payload(projection())))
    renderDesk()
    expect(await screen.findByRole('region', { name: '数据健康' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '最新 Screen 排名变化' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '组合偏离与风险' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Timing Shadow' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '重大事件/公告流' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '因子审核与待处理' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '运行异常' })).toBeInTheDocument()
  })

  it('requests the desk projection instead of computing state in the browser', async () => {
    const requests: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: unknown) => {
      requests.push(String(input))
      return payload(projection())
    }))
    renderDesk()
    await screen.findByText('今日研究态势 / Platform Pulse')
    expect(requests.some((url) => url.includes('/api/desk'))).toBe(true)
  })

  it('renders a loading state while the desk projection is pending', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)))
    renderDesk()
    expect(screen.getByText('正在加载今日工作台')).toBeInTheDocument()
  })

  it('surfaces a real API failure without substituting prototype data', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => payload(projection(), false, 'desk projection store unavailable')))
    renderDesk()
    expect(await screen.findByText('今日工作台读取失败')).toBeInTheDocument()
    expect(screen.getByText(/desk projection store unavailable/)).toBeInTheDocument()
    // Figma DESIGN FIXTURE values must never appear in the runtime.
    expect(screen.queryByText('94.2%')).not.toBeInTheDocument()
    expect(screen.queryByText('贵州茅台')).not.toBeInTheDocument()
    expect(screen.queryByText('+3.2 %')).not.toBeInTheDocument()
  })

  it('shows each section status independently so one blocked domain does not blank the page', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => payload(projection({
      sections: [
        {
          key: 'data_health',
          status: 'partial',
          title: '数据健康',
          blockers: [],
          coverage: { datasets_total: 3, datasets_with_quality_report: 1 },
          payload: { metrics: [] },
        },
        { key: 'screen_shifts', status: 'empty', title: '最新 Screen 排名变化', blockers: [], coverage: {}, payload: null },
        {
          key: 'portfolio_tracking',
          status: 'unavailable',
          title: '组合偏离与风险',
          blockers: [{
            code: 'P6_PORTFOLIO_TRACKING_NOT_IMPLEMENTED',
            reason: '组合跟踪能力属 P6，尚未实现。',
            affected_binding: 'portfolio.tracking',
            evidence_ids: [],
          }],
          coverage: {},
          payload: null,
        },
        { key: 'timing_shadow', status: 'empty', title: 'Timing Shadow', blockers: [], coverage: {}, payload: null },
        {
          key: 'event_feed',
          status: 'unavailable',
          title: '重大事件/公告流',
          blockers: [{
            code: 'P8_EVENT_FEED_NOT_IMPLEMENTED',
            reason: '事件与公告流能力属 P8，尚未实现。',
            affected_binding: 'event.feed',
            evidence_ids: [],
          }],
          coverage: {},
          payload: null,
        },
        { key: 'pending_tasks', status: 'empty', title: '因子审核与待处理', blockers: [], coverage: {}, payload: null },
        { key: 'active_failures', status: 'empty', title: '运行异常', blockers: [], coverage: {}, payload: null },
      ],
    }))))
    renderDesk()
    expect(await screen.findByRole('region', { name: '数据健康' })).toBeInTheDocument()
    // An unavailable P6/P8 domain must not collapse the rest of the desk.
    expect(screen.getByRole('region', { name: '最新 Screen 排名变化' })).toBeInTheDocument()
    expect(screen.getByText('P6_PORTFOLIO_TRACKING_NOT_IMPLEMENTED')).toBeInTheDocument()
    expect(screen.getByText('P8_EVENT_FEED_NOT_IMPLEMENTED')).toBeInTheDocument()
    expect(screen.getByText(/组合跟踪能力属 P6/)).toBeInTheDocument()
  })
})
