import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { DeskSection as DeskSectionData } from '../../api/client'
import { DeskSection } from './DeskSection'

function section(overrides: Partial<DeskSectionData> = {}): DeskSectionData {
  return {
    key: 'data_health',
    status: 'empty',
    title: '数据健康',
    blockers: [],
    coverage: {},
    payload: null,
    ...overrides,
  }
}

describe('DeskSection', () => {
  afterEach(cleanup)

  it('exposes an accessible region named after the server title', () => {
    render(<DeskSection section={section()} subtitle="Data Health" />)
    const region = screen.getByRole('region', { name: '数据健康' })
    expect(region).toBeInTheDocument()
    expect(screen.getByText('Data Health')).toBeInTheDocument()
  })

  it('renders the loading state without any section content', () => {
    render(
      <DeskSection section={section()} loading>
        <span>真实内容</span>
      </DeskSection>,
    )
    expect(screen.getByText('正在加载')).toBeInTheDocument()
    expect(screen.queryByText('真实内容')).not.toBeInTheDocument()
  })

  it('renders a request error without substituting content', () => {
    render(
      <DeskSection section={section()} error="读取失败：503">
        <span>真实内容</span>
      </DeskSection>,
    )
    expect(screen.getByText('读取失败：503')).toBeInTheDocument()
    expect(screen.queryByText('真实内容')).not.toBeInTheDocument()
  })

  it('renders the empty state as "no record yet", not as a missing capability', () => {
    render(<DeskSection section={section({ status: 'empty' })} />)
    expect(screen.getByText('暂无记录')).toBeInTheDocument()
    expect(screen.queryByText('能力未启用')).not.toBeInTheDocument()
  })

  it('renders every unavailable blocker code and reason', () => {
    render(
      <DeskSection
        section={section({
          key: 'portfolio_tracking',
          status: 'unavailable',
          title: '组合偏离与风险',
          blockers: [{
            code: 'P6_PORTFOLIO_TRACKING_NOT_IMPLEMENTED',
            reason: '组合构建、偏离与风险能力属 P6，尚未实现。',
            affected_binding: 'portfolio.tracking',
            evidence_ids: [],
          }],
        })}
      />,
    )
    expect(screen.getByText('P6_PORTFOLIO_TRACKING_NOT_IMPLEMENTED')).toBeInTheDocument()
    expect(screen.getByText(/组合构建、偏离与风险能力属 P6/)).toBeInTheDocument()
    expect(screen.getByText('portfolio.tracking')).toBeInTheDocument()
  })

  it('shows partial content together with the declared coverage gap', () => {
    render(
      <DeskSection
        section={section({
          status: 'partial',
          coverage: { datasets_total: 3, datasets_with_quality_report: 1 },
          payload: { metrics: [] },
        })}
      >
        <span>真实局部内容</span>
      </DeskSection>,
    )
    expect(screen.getByText('真实局部内容')).toBeInTheDocument()
    expect(screen.getByText(/datasets_total/)).toBeInTheDocument()
    expect(screen.getByText(/3/)).toBeInTheDocument()
  })

  it('renders ready content without a notice', () => {
    render(
      <DeskSection section={section({ status: 'ready', payload: { metrics: [] } })}>
        <span>真实完整内容</span>
      </DeskSection>,
    )
    expect(screen.getByText('真实完整内容')).toBeInTheDocument()
    expect(screen.queryByText('暂无记录')).not.toBeInTheDocument()
    expect(screen.queryByText('部分可用')).not.toBeInTheDocument()
  })

  it('conveys status by text, not by colour alone', () => {
    render(<DeskSection section={section({ status: 'empty' })} />)
    // A screen reader or a colour-blind operator must still get the state.
    expect(screen.getByRole('status')).toBeInTheDocument()
  })
})
