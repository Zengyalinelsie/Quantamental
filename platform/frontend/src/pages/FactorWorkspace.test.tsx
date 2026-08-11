import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'

import {
  FactorWorkspace,
  type FactorWorkspaceSnapshot,
} from './FactorWorkspace'

const failedSnapshot: FactorWorkspaceSnapshot = {
  systemAsOf: '2026-08-11T08:00:00Z',
  dataMode: 'strict_historical',
  deploymentStage: 'research',
  experiments: [
    {
      experimentId: 'experiment:quality:csi300:v1',
      factorName: 'Quality V0',
      status: 'failed',
      failureReason: '样本外 Rank IC 置信区间跨越 0，未通过晋级门。',
      sampleLabel: 'out_of_sample',
      multipleTestingFamily: 'fundamental-v0-family:v1',
      statistics: {
        rankIc: '0.012',
        confidenceInterval: ['-0.018', '0.039'],
        turnover: '0.42',
        coverage: '0.91',
      },
      quantiles: [
        { label: 'Q1', returnValue: '-0.011' },
        { label: 'Q2', returnValue: '-0.004' },
        { label: 'Q3', returnValue: '0.001' },
        { label: 'Q4', returnValue: '0.006' },
        { label: 'Q5', returnValue: '0.009' },
      ],
      decay: [
        { horizon: '20D', rankIc: '0.012' },
        { horizon: '60D', rankIc: '0.004' },
      ],
    },
  ],
  timingBaseline: null,
  correlationPairs: [],
  productionVersions: [],
}

describe('FactorWorkspace', () => {
  afterEach(cleanup)

  it('shows real engineering definitions and an honest no-result state by default', () => {
    render(
      <MemoryRouter initialEntries={['/factors?tab=catalog']}>
        <FactorWorkspace />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: '因子' })).toBeInTheDocument()
    expect(screen.getByText('Quality V0')).toBeInTheDocument()
    expect(screen.getByText('Valuation Expectation Gap V0')).toBeInTheDocument()
    expect(screen.getByText('Fundamental Improvement V0')).toBeInTheDocument()
    expect(screen.getAllByText('not_evaluated')).toHaveLength(3)
    expect(screen.getByText(/没有注入运行时演示结果/)).toBeInTheDocument()
  })

  it('keeps failed experiments visible with OOS and multiple-testing evidence', () => {
    render(
      <MemoryRouter initialEntries={['/factors?tab=experiments']}>
        <FactorWorkspace snapshot={failedSnapshot} />
      </MemoryRouter>,
    )

    expect(screen.getByRole('tab', { name: 'Experiments' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByText('experiment:quality:csi300:v1')).toBeInTheDocument()
    expect(screen.getByText('失败保留')).toBeInTheDocument()
    expect(screen.getByText('out_of_sample')).toBeInTheDocument()
    expect(screen.getByText('fundamental-v0-family:v1')).toBeInTheDocument()
    expect(screen.getByText(/置信区间跨越 0/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '分位数组合收益图' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Rank IC 衰减图' })).toBeInTheDocument()
  })

  it('does not turn absent correlation or production data into numeric zero', () => {
    render(
      <MemoryRouter initialEntries={['/factors?tab=correlation-monitor']}>
        <FactorWorkspace />
      </MemoryRouter>,
    )

    expect(screen.getByText('尚无相关性矩阵')).toBeInTheDocument()
    expect(screen.getByText(/不会把缺失相关系数显示为 0/)).toBeInTheDocument()
    expect(screen.queryByText('0.00')).not.toBeInTheDocument()
  })
})
