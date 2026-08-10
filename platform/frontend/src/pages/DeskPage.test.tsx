import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { DeskPage } from './DeskPage'

describe('DeskPage P2 status', () => {
  it('shows P2 identity universe and market-data capability without claiming PIT', async () => {
    render(
      <MemoryRouter>
        <DeskPage />
      </MemoryRouter>,
    )
    expect(screen.getByText('P2 · READ ONLY')).toBeInTheDocument()
    expect(screen.getByText('历史股票池')).toBeInTheDocument()
    expect(screen.getByText('市场基础数据')).toBeInTheDocument()
    expect(screen.getByText(/normalized_current/)).toBeInTheDocument()
  })
})
