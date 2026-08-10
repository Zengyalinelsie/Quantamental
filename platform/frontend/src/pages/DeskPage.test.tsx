import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { DeskPage } from './DeskPage'

describe('DeskPage P3 status', () => {
  it('shows the real P3 evidence baseline without claiming full-market or active-model readiness', async () => {
    render(
      <MemoryRouter>
        <DeskPage />
      </MemoryRouter>,
    )
    expect(screen.getByText('P3 · RESEARCH EVIDENCE')).toBeInTheDocument()
    expect(screen.getByText('历史股票池')).toBeInTheDocument()
    expect(screen.getByText('市场基础数据')).toBeInTheDocument()
    expect(screen.getByText(/4 家真实样本、8 份官方 PDF、2 条修订链/)).toBeInTheDocument()
    expect(screen.getByText(/被动波动率 Shadow baseline 已开始追加/)).toBeInTheDocument()
    expect(screen.getByText(/normalized_current/)).toBeInTheDocument()
    expect(screen.queryByText('等待 P3 正式接入')).not.toBeInTheDocument()
  })
})
