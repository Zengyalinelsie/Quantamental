import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ResearchWorkspaceData, ResponseContext } from '../api/client'
import type { InvestmentViewProjection } from '../features/investment-view/investmentViewProjection'
import type {
  AlphaModelReadinessProjection,
  ScreenRankingProjection,
} from '../features/screen/screenProjection'
import { useWorkspaceStore } from '../state/workspace'
import { ResearchP5Screen } from './ResearchP5Screen'

const context: ResponseContext = {
  as_of: '2026-08-11T08:00:00Z',
  system_as_of: '2026-08-11T08:05:00Z',
  data_mode: 'strict_historical',
  deployment_stage: 'research',
  trust_state: 'pit_verified',
  dataset_version_ids: ['dataset:financials:v1'],
  model_version_ids: [],
  run_id: null,
  coverage: {},
  warnings: [],
}

const alphaUnavailable: AlphaModelReadinessProjection = {
  status: 'unavailable',
  requested_scope: 'research_backtest',
  data_mode: 'strict_historical',
  deployment_stage: 'research',
  checked_at: '2026-08-11T08:05:00Z',
  blocked_reasons: [{
    code: 'NO_APPROVED_FACTOR_VERSION',
    reason: '真实 PIT 因子资格门未通过。',
    affected_binding: 'factor-version:*',
    evidence_ids: ['artifact:p4:failed:v1'],
  }],
}

const alphaReady: AlphaModelReadinessProjection = {
  status: 'ready',
  requested_scope: 'research_backtest',
  data_mode: 'strict_historical',
  deployment_stage: 'research',
  checked_at: '2026-08-11T08:05:00Z',
  model: {
    model_version_id: 'expected-return-compiler:v0',
    code_version: '1'.repeat(40),
    environment_id: 'environment:p5:research:v1',
    investment_view_id: 'investment-view:600066:v1',
    investment_view_hash: 'a'.repeat(64),
  },
  factors: [{
    factor_version_id: 'factor-version:quality:v1',
    factor_version_hash: 'b'.repeat(64),
    lifecycle_status: 'production',
    review_id: 'approval:quality:v1',
    review_hash: 'c'.repeat(64),
    validation_report_id: 'validation-report:quality:v1',
    validation_report_hash: 'd'.repeat(64),
    scientific_gate_passed: true,
    approval: {
      approval_id: 'approval:quality:v1',
      approval_hash: 'e'.repeat(64),
      scope: 'research_backtest',
      decision: 'approved',
      reviewer_id: 'user:reviewer-01',
      reviewer_role: 'reviewer',
      decided_at: '2026-08-11T07:30:00Z',
      reason: '只批准研究回测。',
    },
  }],
}

const screenProjection: ScreenRankingProjection = {
  screen_id: 'screen:csi500:2026-08-11:v1',
  universe: {
    universe_version_id: 'universe:csi500:2026-08-11:v1',
    display_name: '中证 500',
    universe_size: 500,
  },
  decision_time: '2026-08-11T08:00:00Z',
  data_cutoff: '2026-08-11T07:55:00Z',
  data_mode: 'strict_historical',
  trust_state: 'pit_verified',
  approval_scope: 'research_backtest',
  model_version_id: 'expected-return-compiler:v0',
  factor_version_ids: ['factor-version:quality:v1'],
  dataset_version_ids: ['dataset:financials:v1'],
  feature_version_ids: ['feature:quality:v0'],
  rows: [{
    snapshot_id: 'signal-snapshot:600066:v1',
    security: {
      security_id: 'security:CN:600066:XSHG',
      symbol: '600066',
      display_name: '宇通客车',
      exchange: 'XSHG',
    },
    industry: { code: 'CI005012', display_name: '商用车' },
    rank: { value: 2, display: '2' },
    previous_rank: { value: 4, display: '4', unavailable_reason: null },
    rank_change: { value: 2, display: '↑ 2', direction: 'up', unavailable_reason: null },
    score: { raw: '1.921', display: '1.921' },
    expected_return: { raw: '0.086', display: '+8.60%' },
    confidence: { raw: '0.71', display: '0.71' },
    investment_view_id: 'investment-view:600066:v1',
    trust_state: 'pit_verified',
    content_hash: 'f'.repeat(64),
    selected: true,
  }],
  selected_security: {
    security_id: 'security:CN:600066:XSHG',
    snapshot_id: 'signal-snapshot:600066:v1',
    display_name: '宇通客车',
    symbol: '600066',
    industry: { code: 'CI005012', display_name: '商用车' },
  },
  industry_peers: [],
  warnings: [],
}

const investmentView: InvestmentViewProjection = {
  view_id: 'investment-view:600066:v1',
  security: {
    security_id: 'security:CN:600066:XSHG',
    symbol: '600066',
    exchange: 'XSHG',
    display_name: '宇通客车',
  },
  decision_time: '2026-08-11T08:00:00Z',
  horizon: '60D',
  data_mode: 'strict_historical',
  trust_state: 'pit_verified',
  trust_reason: 'PIT available_at 与修订链已验证。',
  distribution: {
    point: { raw: '0.086', display: '+8.60%' },
    p10: { raw: '-0.10', display: '-10.00%' },
    p50: { raw: '0.08', display: '+8.00%' },
    p90: { raw: '0.22', display: '+22.00%' },
    downside: { raw: '-0.15', display: '-15.00%' },
  },
  components: [
    {
      component: 'quality', label: '公司质量', status: 'quantified',
      contribution: { raw: '0.03', display: '+3.00%' }, reason: '已量化。',
      evidence_ids: ['evidence:quality'], visual: null,
    },
    {
      component: 'valuation', label: '估值预期差', status: 'quantified',
      contribution: { raw: '0.04', display: '+4.00%' }, reason: '已量化。',
      evidence_ids: ['evidence:valuation'], visual: null,
    },
    {
      component: 'revision', label: '基本面改善', status: 'constrained',
      contribution: null, reason: '只影响置信度。', evidence_ids: ['evidence:revision'], visual: null,
    },
    {
      component: 'event', label: '事件调整', status: 'unavailable',
      contribution: null, reason: 'P8 前不可用。', evidence_ids: [], visual: null,
    },
  ],
  residual: {
    status: 'quantified', contribution: { raw: '0.016', display: '+1.60%' },
    reason: '显式 residual。', evidence_ids: ['artifact:residual:v1'], visual: null,
  },
  closure: {
    status: 'passed', displayed_total: '+8.60%', tolerance: '0.000001',
    difference: '0', checked_by: 'expected-return-compiler:v0',
  },
  confidence: { raw: '0.71', display: '0.71' },
  catalysts: [],
  invalidators: [{ invalidator_id: 'invalidator:1', summary: '现金流下修', evidence_ids: ['evidence:quality'] }],
  evidence: [],
  versions: {
    dataset_version_ids: ['dataset:financials:v1'],
    feature_version_ids: ['feature:quality:v0'],
    model_version_id: 'expected-return-compiler:v0',
    run_id: 'run:p5:v1',
    code_version: '1'.repeat(40),
    environment_id: 'environment:p5:v1',
    content_hash: '9'.repeat(64),
    artifact_id: 'artifact:investment-view:v1',
  },
  warnings: [],
}

function payload(data: ResearchWorkspaceData, ok = true, detail = ''): Response {
  return {
    ok,
    status: ok ? 200 : 503,
    json: async () => ok ? { data, context } : { detail },
  } as Response
}

function renderResearch(section: 'universe-screen' | 'security') {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <ResearchP5Screen section={section} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ResearchP5Screen', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    useWorkspaceStore.getState().reset()
  })

  it('renders a professional loading state while the real API is pending', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)))
    renderResearch('universe-screen')
    expect(screen.getByText('正在加载 P5 研究工作区')).toBeInTheDocument()
  })

  it('renders the API error without replacing it with fixture data', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => payload({
      status: 'unavailable', blockers: [], screen: null, investment_view: null,
      alpha_model: alphaUnavailable,
    }, false, 'research workspace database unavailable')))
    renderResearch('universe-screen')
    expect(await screen.findByText('P5 研究工作区读取失败')).toBeInTheDocument()
    expect(screen.getByText(/database unavailable/)).toBeInTheDocument()
    expect(screen.queryByText('宇通客车')).not.toBeInTheDocument()
  })

  it('shows an honest Security empty state when no InvestmentView is returned', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => payload({
      status: 'partial',
      blockers: [{ code: 'SECURITY_NOT_SELECTED', reason: '尚未选择证券。', affected_binding: 'security_id', evidence_ids: [] }],
      screen: screenProjection,
      investment_view: null,
      alpha_model: alphaUnavailable,
    })))
    renderResearch('security')
    expect(await screen.findByText('尚无可展示的 InvestmentView')).toBeInTheDocument()
    expect(screen.getByText('TRUST pit_verified')).toBeInTheDocument()
    expect(screen.getByText(/全局证券搜索输入真实代码或名称/)).toBeInTheDocument()
    expect(screen.getByText('Alpha Model 当前不可用')).toBeInTheDocument()
  })

  it('renders partial Screen data alongside all server blockers and Alpha readiness', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => payload({
      status: 'partial',
      blockers: [{
        code: 'INVESTMENT_VIEW_UNAVAILABLE', reason: '选中证券无合格 PIT InvestmentView。',
        affected_binding: 'investment_view', evidence_ids: ['artifact:view:failed:v1'],
      }],
      screen: screenProjection,
      investment_view: null,
      alpha_model: alphaUnavailable,
    })))
    renderResearch('universe-screen')
    expect(await screen.findByText('P5 研究工作区仅部分可用')).toBeInTheDocument()
    expect(screen.getByText('API 查询用途')).toBeInTheDocument()
    expect(screen.getByText('INVESTMENT_VIEW_UNAVAILABLE')).toBeInTheDocument()
    expect(screen.getByText('artifact:view:failed:v1')).toBeInTheDocument()
    expect(screen.getByText('中证 500 · 500')).toBeInTheDocument()
    expect(screen.getByText('Alpha Model 当前不可用')).toBeInTheDocument()
  })

  it('renders a ready InvestmentView and exact approved Alpha package', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => (
      String(input) === '/api/identity'
        ? {
          ok: true,
          status: 200,
          json: async () => ({
            data: { subject_id: 'anonymous', roles: [], permissions: ['read_public'] },
            context,
          }),
        } as Response
        : payload({
          status: 'ready', blockers: [], screen: screenProjection,
          investment_view: investmentView, alpha_model: alphaReady,
        })
    )))
    renderResearch('security')
    expect(await screen.findByRole('heading', { name: '宇通客车 · 600066' })).toBeInTheDocument()
    expect(screen.getByTestId('approved-alpha-model')).toBeInTheDocument()
    expect(screen.getByText('factor-version:quality:v1')).toBeInTheDocument()
    expect(await screen.findByText('Frozen Artifact 下载受限')).toBeInTheDocument()
  })

  it('passes the global securityQuery unchanged for server-side parsing', async () => {
    useWorkspaceStore.getState().setSecurityQuery(' 贵州 茅台/600519 ')
    const fetchMock = vi.fn(async () => payload({
      status: 'unavailable', blockers: [], screen: null, investment_view: null,
      alpha_model: alphaUnavailable,
    }))
    vi.stubGlobal('fetch', fetchMock)
    renderResearch('security')
    await screen.findByText('P5 研究工作区不可用')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/research/workspace?security_id=%20%E8%B4%B5%E5%B7%9E%20%E8%8C%85%E5%8F%B0%2F600519%20',
      expect.objectContaining({ headers: { Accept: 'application/json' } }),
    )
  })

  it('keeps the prototype two-column shape when the workspace is unavailable', async () => {
    // The builder is where an operator learns which bindings are missing, so it
    // must survive an unavailable workspace instead of the page collapsing to a
    // single generic notice.
    vi.stubGlobal('fetch', vi.fn(async () => payload({
      status: 'unavailable', blockers: [], screen: null, investment_view: null,
      alpha_model: alphaUnavailable,
    })))
    renderResearch('universe-screen')

    expect(await screen.findByRole('region', { name: 'Screen 构建器' })).toBeInTheDocument()
    expect(screen.getByText(/没有合格的冻结 Screen/)).toBeInTheDocument()
    expect(screen.getByText('P5 研究工作区不可用')).toBeInTheDocument()
    // Still no prototype sample values.
    expect(screen.queryByText('CSI500')).not.toBeInTheDocument()
    expect(screen.queryByText('40%')).not.toBeInTheDocument()
  })
})
