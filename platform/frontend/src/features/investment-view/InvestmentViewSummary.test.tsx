import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { InvestmentViewSummary } from './InvestmentViewSummary'
import type { InvestmentViewProjection } from './investmentViewProjection'

const projection: InvestmentViewProjection = {
  view_id: 'investment-view:600519:2026-08-11:60d:v1',
  security: {
    security_id: 'security:XSHG:600519',
    symbol: '600519',
    exchange: 'XSHG',
    display_name: '贵州茅台',
  },
  decision_time: '2026-08-11T07:00:00Z',
  horizon: '60D',
  data_mode: 'strict_historical',
  trust_state: 'pit_verified',
  trust_reason: '所有量化输入均通过 available_at 与修订链检查。',
  distribution: {
    point: { display: '+8.20%', raw: '0.0820' },
    p10: { display: '-6.50%', raw: '-0.0650' },
    p50: { display: '+7.60%', raw: '0.0760' },
    p90: { display: '+24.10%', raw: '0.2410' },
    downside: { display: '-11.30%', raw: '-0.1130' },
  },
  components: [
    {
      component: 'quality',
      label: '公司质量',
      status: 'quantified',
      contribution: { display: '+2.10%', raw: '0.0210' },
      reason: '行业模板和证据完整。',
      evidence_ids: ['evidence:quality'],
      visual: { start_percent: '50', width_percent: '10', direction: 'positive' },
    },
    {
      component: 'valuation',
      label: '估值预期差',
      status: 'quantified',
      contribution: { display: '+4.40%', raw: '0.0440' },
      reason: '相对估值与基本面锚定估值已统一到 60D。',
      evidence_ids: ['evidence:valuation'],
      visual: { start_percent: '60', width_percent: '21', direction: 'positive' },
    },
    {
      component: 'revision',
      label: '基本面改善',
      status: 'constrained',
      contribution: null,
      reason: '最近一期现金流可比性不足，只影响置信度。',
      evidence_ids: ['evidence:revision'],
      visual: null,
    },
    {
      component: 'event',
      label: '事件调整',
      status: 'unavailable',
      contribution: null,
      reason: 'P8 事件模型尚未启用，不能解释为零影响。',
      evidence_ids: [],
      visual: null,
    },
  ],
  residual: {
    status: 'quantified',
    contribution: { display: '+1.70%', raw: '0.0170' },
    reason: '统一期限校准残差。',
    evidence_ids: ['artifact:compiler-residual-policy:v0'],
    visual: { start_percent: '81', width_percent: '8', direction: 'positive' },
  },
  closure: {
    status: 'passed',
    displayed_total: '+8.20%',
    tolerance: '0.000001',
    difference: '0.000000',
    checked_by: 'expected-return-compiler:v1',
  },
  confidence: { display: '中等 · 0.64', raw: '0.64' },
  catalysts: [
    { catalyst_id: 'catalyst:1', summary: '渠道库存改善', horizon: '60D', evidence_ids: ['evidence:1'] },
  ],
  invalidators: [
    { invalidator_id: 'invalidator:1', summary: '批价连续四周低于阈值', evidence_ids: ['evidence:2'] },
  ],
  evidence: [
    {
      evidence_id: 'evidence:1',
      title: '2025 年年度报告',
      source_kind: 'official_disclosure',
      available_at: '2026-03-31T10:00:00Z',
      version: 'disclosure:v3',
      source_url: 'https://example.invalid/disclosure/1',
    },
    {
      evidence_id: 'evidence:2',
      title: '经营指标观察',
      source_kind: 'structured_provider',
      available_at: '2026-08-10T09:00:00Z',
      version: 'observation:v7',
      source_url: null,
    },
  ],
  versions: {
    dataset_version_ids: ['dataset:financial:pit:v8', 'dataset:market:pit:v4'],
    feature_version_ids: ['feature:quality:v0', 'feature:valuation:v0'],
    model_version_id: 'expected-return-model:v1',
    run_id: 'run:investment-view:600519:v1',
    code_version: '0123456789abcdef0123456789abcdef01234567',
    environment_id: 'environment:p5:research:v1',
    content_hash: 'a'.repeat(64),
    artifact_id: 'artifact:investment-view:600519:v1',
  },
  warnings: [],
}

describe('InvestmentViewSummary', () => {
  afterEach(cleanup)

  it('renders the server projection with explicit strict PIT trust and versions', () => {
    render(<InvestmentViewSummary projection={projection} />)

    expect(screen.getByRole('heading', { name: '贵州茅台 · 600519' })).toBeInTheDocument()
    expect(screen.getByText('严格历史研究')).toBeInTheDocument()
    expect(screen.getByText('PIT 已验证')).toBeInTheDocument()
    expect(screen.getByText('+8.20%')).toBeInTheDocument()
    expect(screen.getByText('artifact:investment-view:600519:v1')).toBeInTheDocument()
    expect(screen.getByText('run:investment-view:600519:v1')).toBeInTheDocument()
    expect(screen.getByText('feature:quality:v0')).toBeInTheDocument()
    expect(screen.getByText('feature:valuation:v0')).toBeInTheDocument()
    expect(screen.getByText('environment:p5:research:v1')).toBeInTheDocument()
    expect(screen.getByText('a'.repeat(64))).toBeInTheDocument()
  })

  it('never presents constrained or unavailable components as numeric zero', () => {
    render(<InvestmentViewSummary projection={projection} />)

    const revision = screen.getByTestId('investment-component-revision')
    const event = screen.getByTestId('investment-component-event')
    expect(within(revision).getByText('受约束')).toBeInTheDocument()
    expect(within(revision).getByText(/只影响置信度/)).toBeInTheDocument()
    expect(within(event).getByText('不可用')).toBeInTheDocument()
    expect(within(event).getByText(/不能解释为零影响/)).toBeInTheDocument()
    expect(within(revision).queryByText('0')).not.toBeInTheDocument()
    expect(within(event).queryByText('0')).not.toBeInTheDocument()
  })

  it('displays the server closure verdict and residual without recomputing them', () => {
    const deliberatelyServerOwned = {
      ...projection,
      distribution: {
        ...projection.distribution,
        point: { display: '+99.00%', raw: '0.9900' },
      },
    }
    render(<InvestmentViewSummary projection={deliberatelyServerOwned} />)

    const closure = screen.getByTestId('investment-view-closure')
    expect(within(closure).getByText('服务端闭合通过')).toBeInTheDocument()
    expect(within(closure).getByText('expected-return-compiler:v1')).toBeInTheDocument()
    expect(screen.getByText('+1.70%')).toBeInTheDocument()
    expect(screen.queryByText(/前端重算/)).not.toBeInTheDocument()
  })

  it('uses only precomputed waterfall coordinates supplied by the projection', () => {
    render(<InvestmentViewSummary projection={projection} />)

    const qualityBar = screen.getByTestId('waterfall-bar-quality')
    const residualBar = screen.getByTestId('waterfall-bar-residual')
    expect(qualityBar).toHaveStyle({
      '--waterfall-start': '50%',
      '--waterfall-width': '10%',
    })
    expect(residualBar).toHaveStyle({
      '--waterfall-start': '81%',
      '--waterfall-width': '8%',
    })
  })

  it('keeps catalysts, invalidators and evidence bindings visible', () => {
    render(<InvestmentViewSummary projection={projection} />)

    expect(screen.getByText('渠道库存改善')).toBeInTheDocument()
    expect(screen.getByText('批价连续四周低于阈值')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '2025 年年度报告' })).toHaveAttribute(
      'href',
      'https://example.invalid/disclosure/1',
    )
    expect(screen.getByText('disclosure:v3')).toBeInTheDocument()
    expect(screen.getByText('observation:v7')).toBeInTheDocument()
    expect(
      within(screen.getByTestId('investment-component-quality')).getByText('evidence:quality'),
    ).toBeInTheDocument()
    expect(
      within(screen.getByTestId('investment-component-revision')).getByText('evidence:revision'),
    ).toBeInTheDocument()
    expect(
      within(screen.getByTestId('investment-component-residual')).getByText(
        'artifact:compiler-residual-policy:v0',
      ),
    ).toBeInTheDocument()
  })

  it('labels current-only trust in words and renders server warnings', () => {
    render(
      <InvestmentViewSummary
        projection={{
          ...projection,
          data_mode: 'current_research',
          trust_state: 'normalized_current',
          trust_reason: '供应商 current observation 不具备历史 available_at。',
          warnings: ['禁止用于 strict_historical 或生产决策。'],
        }}
      />,
    )

    expect(screen.getByText('当前研究')).toBeInTheDocument()
    expect(screen.getByText('规范化当前数据')).toBeInTheDocument()
    expect(screen.getByText(/不具备历史 available_at/)).toBeInTheDocument()
    expect(screen.getByText('禁止用于 strict_historical 或生产决策。')).toBeInTheDocument()
  })
})
