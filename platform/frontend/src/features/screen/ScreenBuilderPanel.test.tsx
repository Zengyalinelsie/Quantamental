import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ScreenBuilderPanel } from './ScreenBuilderPanel'
import type { ScreenRankingProjection } from './screenProjection'

const projection = {
  screen_id: 'screen:csi500:2026-08-11:60d:v1',
  universe: {
    universe_version_id: 'universe-version:csi500:v3',
    display_name: 'CSI500',
    universe_size: 500,
  },
  decision_time: '2026-08-11T07:00:00Z',
  data_cutoff: '2026-08-10T08:00:00Z',
  data_mode: 'strict_historical',
  trust_state: 'pit_verified',
  approval_scope: 'research_backtest',
  model_version_id: 'expected-return-compiler:v0',
  factor_version_ids: ['factor-version:quality:v1', 'factor-version:valuation:v1'],
  dataset_version_ids: ['dataset:financials:v1'],
  feature_version_ids: ['feature:quality:v1'],
  rows: [],
  selected_security: null,
  industry_peers: [],
  warnings: [],
} as unknown as ScreenRankingProjection

describe('ScreenBuilderPanel', () => {
  afterEach(cleanup)

  it('names itself after the prototype builder', () => {
    render(<ScreenBuilderPanel projection={projection} />)

    expect(screen.getByRole('region', { name: 'Screen 构建器' })).toBeInTheDocument()
    expect(screen.getByText('Screen 构建器 / Factor Builder')).toBeInTheDocument()
  })

  it('reports the frozen universe binding rather than an editable selector', () => {
    render(<ScreenBuilderPanel projection={projection} />)

    expect(screen.getByText('CSI500')).toBeInTheDocument()
    expect(screen.getByText('universe-version:csi500:v3')).toBeInTheDocument()
    expect(screen.getByText('500')).toBeInTheDocument()
  })

  it('lists the exact factor versions the frozen screen used', () => {
    render(<ScreenBuilderPanel projection={projection} />)

    expect(screen.getByText('factor-version:quality:v1')).toBeInTheDocument()
    expect(screen.getByText('factor-version:valuation:v1')).toBeInTheDocument()
  })

  it('reports the approval scope, trust state and model version', () => {
    render(<ScreenBuilderPanel projection={projection} />)

    expect(screen.getByText('research_backtest')).toBeInTheDocument()
    expect(screen.getByText('pit_verified')).toBeInTheDocument()
    expect(screen.getByText('expected-return-compiler:v0')).toBeInTheDocument()
  })

  it('offers no weight inputs and no run action', () => {
    // ADR-0012: an editable builder would produce numbers with no definition
    // version, no Run record and no approval scope.  It arrives after the P4
    // factor gate, behind the scratch/governed split.
    render(<ScreenBuilderPanel projection={projection} />)

    expect(screen.queryByRole('button', { name: /运行 Screen/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('slider')).not.toBeInTheDocument()
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('never shows the prototype sample weights or thresholds', () => {
    render(<ScreenBuilderPanel projection={projection} />)
    const text = screen.getByRole('region', { name: 'Screen 构建器' }).textContent ?? ''

    // Figma DESIGN FIXTURE values: 40% / 30% / 30%, 96.3%, > 5000 万 CNY.
    expect(text).not.toContain('40%')
    expect(text).not.toContain('30%')
    expect(text).not.toContain('96.3')
    expect(text).not.toContain('5000')
  })

  it('explains that the parameters are frozen, not editable', () => {
    render(<ScreenBuilderPanel projection={projection} />)

    expect(screen.getByText(/已冻结/)).toBeInTheDocument()
  })

  it('renders an honest unavailable state when no screen is bound', () => {
    render(<ScreenBuilderPanel projection={null} />)

    expect(screen.getByRole('region', { name: 'Screen 构建器' })).toBeInTheDocument()
    expect(screen.getByText(/没有合格的冻结 Screen/)).toBeInTheDocument()
    // Absent parameters must not be replaced by prototype defaults.
    expect(screen.queryByText('CSI500')).not.toBeInTheDocument()
    expect(screen.queryByText('40%')).not.toBeInTheDocument()
  })
})
