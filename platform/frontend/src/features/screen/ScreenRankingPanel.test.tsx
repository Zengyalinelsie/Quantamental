import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ScreenRankingPanel } from './ScreenRankingPanel'
import type { ScreenRankingProjection } from './screenProjection'

const projection: ScreenRankingProjection = {
  screen_id: 'screen:csi500:2026-08-11:60d:v1',
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
  factor_version_ids: ['factor-version:quality:v1', 'factor-version:valuation:v1'],
  dataset_version_ids: ['dataset:financials:v1', 'dataset:prices:v1'],
  feature_version_ids: ['feature:quality:v0', 'feature:valuation:v0'],
  rows: [
    {
      snapshot_id: 'signal-snapshot:second-server-row',
      security: {
        security_id: 'security:CN:600066:XSHG',
        symbol: '600066',
        display_name: '宇通客车',
        exchange: 'XSHG',
      },
      industry: { code: 'CI005012', display_name: '商用车' },
      rank: { value: 2, display: '2' },
      previous_rank: { value: 80, display: '80', unavailable_reason: null },
      // Deliberately differs from previous_rank - rank. The serving projection owns it.
      rank_change: { value: 99, display: '↑ 99', direction: 'up', unavailable_reason: null },
      score: { raw: '1.921', display: '1.921' },
      expected_return: { raw: '0.086', display: '+8.60%' },
      confidence: { raw: '0.71', display: '0.71' },
      investment_view_id: 'investment-view:600066:v1',
      trust_state: 'pit_verified',
      content_hash: 'a'.repeat(64),
      selected: true,
    },
    {
      snapshot_id: 'signal-snapshot:first-rank-server-row',
      security: {
        security_id: 'security:CN:600039:XSHG',
        symbol: '600039',
        display_name: '四川路桥',
        exchange: 'XSHG',
      },
      industry: { code: 'CI005012', display_name: '商用车' },
      rank: { value: 1, display: '1' },
      previous_rank: {
        value: null,
        display: null,
        unavailable_reason: '上一冻结截面不存在该证券。',
      },
      rank_change: {
        value: null,
        display: null,
        direction: 'unavailable',
        unavailable_reason: '缺少 previous_rank，不能计算排名变化。',
      },
      score: { raw: '1.802', display: '1.802' },
      expected_return: { raw: '0.074', display: '+7.40%' },
      confidence: { raw: '0.66', display: '0.66' },
      investment_view_id: 'investment-view:600039:v1',
      trust_state: 'pit_verified',
      content_hash: 'b'.repeat(64),
      selected: false,
    },
  ],
  selected_security: {
    security_id: 'security:CN:600066:XSHG',
    snapshot_id: 'signal-snapshot:second-server-row',
    display_name: '宇通客车',
    symbol: '600066',
    industry: { code: 'CI005012', display_name: '商用车' },
  },
  industry_peers: [
    {
      security_id: 'security:CN:600686:XSHG',
      display_name: '金龙汽车',
      symbol: '600686',
      rank: { value: 17, display: '17' },
      expected_return: { raw: '0.041', display: '+4.10%' },
      snapshot_id: 'signal-snapshot:peer-1',
    },
    {
      security_id: 'security:CN:000951:XSHE',
      display_name: '中国重汽',
      symbol: '000951',
      rank: { value: 23, display: '23' },
      expected_return: { raw: '0.035', display: '+3.50%' },
      snapshot_id: 'signal-snapshot:peer-2',
    },
  ],
  warnings: [],
}

describe('ScreenRankingPanel', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('keeps server row order and server-owned rank change without sorting or recomputing', () => {
    render(<ScreenRankingPanel projection={projection} />)

    const rows = screen.getAllByRole('row', { name: /^screen-ranking-row-/ })
    expect(within(rows[0]).getByText('宇通客车')).toBeInTheDocument()
    expect(within(rows[0]).getByText('↑ 99')).toBeInTheDocument()
    expect(within(rows[1]).getByText('四川路桥')).toBeInTheDocument()
    expect(within(rows[0]).queryByText('↑ 78')).not.toBeInTheDocument()
  })

  it('shows unavailable previous rank and change without manufacturing numeric zero', () => {
    render(<ScreenRankingPanel projection={projection} />)

    const row = screen.getByRole('row', {
      name: 'screen-ranking-row-signal-snapshot:first-rank-server-row',
    })
    expect(within(row).getByLabelText('上一冻结截面不存在该证券。')).toHaveTextContent('—')
    expect(within(row).getByLabelText('缺少 previous_rank，不能计算排名变化。')).toHaveTextContent('—')
    expect(within(row).queryByText('0')).not.toBeInTheDocument()
  })

  it('renders selected Security and server-projected industry peers', () => {
    render(<ScreenRankingPanel projection={projection} />)

    const selected = screen.getByTestId('selected-screen-security')
    expect(within(selected).getByText('宇通客车 · 600066')).toBeInTheDocument()
    expect(within(selected).getByText('商用车 · CI005012')).toBeInTheDocument()
    const peers = screen.getByTestId('industry-peer-list')
    expect(within(peers).getByText('金龙汽车')).toBeInTheDocument()
    expect(within(peers).getByText('中国重汽')).toBeInTheDocument()
    expect(within(peers).getByText('+4.10%')).toBeInTheDocument()
  })

  it('keeps universe cutoff trust scope and frozen versions visible', () => {
    render(<ScreenRankingPanel projection={projection} />)

    expect(screen.getByText('中证 500 · 500')).toBeInTheDocument()
    expect(screen.getByText('universe:csi500:2026-08-11:v1')).toBeInTheDocument()
    expect(screen.getByText('2026-08-11T07:55:00Z')).toBeInTheDocument()
    expect(screen.getByText('严格历史研究')).toBeInTheDocument()
    expect(screen.getByText('PIT 已验证')).toBeInTheDocument()
    expect(screen.getByText('research_backtest')).toBeInTheDocument()
    expect(screen.getByText('expected-return-compiler:v0')).toBeInTheDocument()
    expect(screen.getByText('factor-version:quality:v1')).toBeInTheDocument()
    expect(screen.getByText('dataset:financials:v1')).toBeInTheDocument()
  })

  it('provides a 320px record-list projection without recomputing server fields', () => {
    render(<ScreenRankingPanel projection={projection} />)

    const list = screen.getByTestId('screen-mobile-record-list')
    const records = within(list).getAllByRole('listitem', { hidden: true })
    expect(within(records[0]).getByText('宇通客车 · 600066')).toBeInTheDocument()
    expect(within(records[0]).getByText('↑ 99')).toBeInTheDocument()
    expect(within(records[0]).getByText('Previous 80')).toBeInTheDocument()
    expect(within(records[0]).getByText('Score 1.921')).toBeInTheDocument()
    expect(within(records[0]).getByText('Trust pit_verified')).toBeInTheDocument()
    expect(within(records[0]).getByText('investment-view:600066:v1')).toBeInTheDocument()
    expect(within(records[0]).getByText('a'.repeat(64))).toBeInTheDocument()
    expect(within(records[1]).getByText('四川路桥 · 600039')).toBeInTheDocument()
    expect(within(records[1]).getByLabelText('上一冻结截面不存在该证券。'))
      .toHaveTextContent('—')
    expect(within(records[1]).getByLabelText('缺少 previous_rank，不能计算排名变化。'))
      .toHaveTextContent('—')
  })

  it('moves low-priority 1024 fields into a textual detail drawer', async () => {
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
      matches: query === '(max-width: 1100px) and (min-width: 821px)',
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })))

    render(<ScreenRankingPanel projection={projection} />)

    const firstRow = screen.getAllByRole('row', { name: /^screen-ranking-row-/ })[0]
    expect(within(firstRow).queryByText('商用车')).not.toBeInTheDocument()
    fireEvent.click(within(firstRow).getByRole('button', { name: '查看宇通客车详情' }))

    const drawer = await screen.findByRole('dialog', { name: '宇通客车 · 600066' })
    expect(within(drawer).getByText('CI005012')).toBeInTheDocument()
    expect(within(drawer).getByText('investment-view:600066:v1')).toBeInTheDocument()
    expect(within(drawer).getByText('a'.repeat(64))).toBeInTheDocument()
  })

  it('keeps an open detail drawer bound to the latest server projection', async () => {
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
      matches: query === '(max-width: 1100px) and (min-width: 821px)',
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })))
    const { rerender } = render(<ScreenRankingPanel projection={projection} />)
    const firstRow = screen.getAllByRole('row', { name: /^screen-ranking-row-/ })[0]
    fireEvent.click(within(firstRow).getByRole('button', { name: '查看宇通客车详情' }))
    const drawer = await screen.findByRole('dialog', { name: '宇通客车 · 600066' })
    expect(within(drawer).getByText('a'.repeat(64))).toBeInTheDocument()

    const refreshed: ScreenRankingProjection = {
      ...projection,
      rows: projection.rows.map((row) => row.snapshot_id === 'signal-snapshot:second-server-row'
        ? { ...row, content_hash: 'c'.repeat(64), investment_view_id: 'investment-view:600066:v2' }
        : row),
    }
    rerender(<ScreenRankingPanel projection={refreshed} />)

    expect(within(drawer).getByText('c'.repeat(64))).toBeInTheDocument()
    expect(within(drawer).getByText('investment-view:600066:v2')).toBeInTheDocument()
    expect(within(drawer).queryByText('a'.repeat(64))).not.toBeInTheDocument()

    rerender(<ScreenRankingPanel projection={{ ...refreshed, rows: refreshed.rows.slice(1) }} />)
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '宇通客车 · 600066' }))
        .not.toBeInTheDocument()
    })
  })

  it('freezes the first table column for horizontal tablet scrolling', () => {
    render(<ScreenRankingPanel projection={projection} />)

    expect(screen.getByRole('columnheader', { name: 'Rank' }))
      .toHaveClass('ant-table-cell-fix-start')
  })
})

describe('ScreenRankingPanel factor dimension columns', () => {
  afterEach(cleanup)

  const withComponents: ScreenRankingProjection = {
    ...projection,
    rows: projection.rows.map((row, index) => ({
      ...row,
      components: [
        {
          component: 'quality' as const,
          label: '公司质量',
          status: 'quantified' as const,
          contribution: { raw: '0.018', display: '+1.80%' },
          display: '+1.80%',
          reason: null,
          evidence_ids: ['evidence:quality:v1'],
        },
        {
          component: 'valuation' as const,
          label: '估值预期差',
          status: 'quantified' as const,
          contribution: { raw: '0.021', display: '+2.10%' },
          display: '+2.10%',
          reason: null,
          evidence_ids: [],
        },
        {
          component: 'revision' as const,
          label: '基本面改善',
          status: 'constrained' as const,
          contribution: null,
          display: '—',
          reason: '改善分项受输入区间约束，未量化。',
          evidence_ids: [],
        },
        {
          component: 'event' as const,
          label: '事件调整',
          status: 'unavailable' as const,
          contribution: null,
          display: '—',
          reason: '没有合格事件证据链。',
          evidence_ids: [],
        },
      ],
      expected_return_interval: index === 0
        ? {
          horizon_trading_days: 60,
          lower: { raw: '0.05', display: '+5.00%' },
          upper: { raw: '0.12', display: '+12.00%' },
          display: '[+5.00%, +12.00%]',
          unavailable_reason: null,
        }
        : {
          horizon_trading_days: 60,
          lower: null,
          upper: null,
          display: null,
          unavailable_reason: '该行没有绑定的冻结 InvestmentView，无法给出区间。',
        },
    })),
  }

  it('renders the three factor dimensions the prototype table declares', () => {
    render(<ScreenRankingPanel projection={withComponents} />)

    expect(screen.getByRole('columnheader', { name: '质量' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '估值预期差' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '改善' })).toBeInTheDocument()
  })

  it('renders the horizon expected-return interval column', () => {
    render(<ScreenRankingPanel projection={withComponents} />)

    expect(screen.getByRole('columnheader', { name: '60日预期收益区间' })).toBeInTheDocument()
    expect(screen.getByText('[+5.00%, +12.00%]')).toBeInTheDocument()
  })

  it('shows the server display value and never zero-fills a non-quantified dimension', () => {
    render(<ScreenRankingPanel projection={withComponents} />)

    expect(screen.getAllByText('+1.80%').length).toBeGreaterThan(0)
    expect(screen.getAllByText('+2.10%').length).toBeGreaterThan(0)
    // constrained and unavailable both render an em dash, never 0 or 0.00%.
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
    expect(screen.queryByText('0.00%')).not.toBeInTheDocument()
    expect(screen.queryByText('+0.00%')).not.toBeInTheDocument()
  })

  it('keeps constrained distinguishable from unavailable for audit', () => {
    render(<ScreenRankingPanel projection={withComponents} />)

    // The prototype table carries 质量 / 估值预期差 / 改善 only; the event
    // dimension belongs to the InvestmentView detail, not this table.  For the
    // dimensions that are shown, an em dash must still carry its reason so that
    // "bounded but unquantified" does not read the same as "missing".
    expect(screen.getAllByTitle(/改善分项受输入区间约束/).length).toBeGreaterThan(0)
  })

  it('states why an interval is missing instead of showing a bare dash', () => {
    render(<ScreenRankingPanel projection={withComponents} />)

    expect(screen.getAllByTitle(/没有绑定的冻结 InvestmentView/).length).toBeGreaterThan(0)
  })

  it('tolerates a projection without component fields', () => {
    // Older snapshots have no bound view; the table must still render.
    render(<ScreenRankingPanel projection={projection} />)

    expect(screen.getByRole('columnheader', { name: '质量' })).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })
})
