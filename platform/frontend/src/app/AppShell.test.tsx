import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'

import { AppShell } from './AppShell'
import { useWorkspaceStore } from '../state/workspace'

describe('AppShell', () => {
  beforeEach(() => {
    useWorkspaceStore.getState().reset()
  })

  it('shows brand, blank security search, and separate run axes', async () => {
    render(
      <MemoryRouter initialEntries={['/research?tab=events']}>
        <AppShell />
      </MemoryRouter>,
    )
    expect(screen.getAllByText('Fundamental Quant').length).toBeGreaterThan(0)
    expect(screen.getByRole('searchbox', { name: '全局证券搜索' })).toHaveValue('')
    expect(screen.getByText('current_research')).toBeInTheDocument()
    expect(screen.getByText('research')).toBeInTheDocument()
    expect(screen.getByText('AS OF')).toBeInTheDocument()
    expect(screen.getByText('SYSTEM AS OF')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: '研究' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Events' })).toHaveAttribute('aria-selected', 'true')
  })

  it('redirects legacy dashboard route explicitly', async () => {
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <AppShell />
      </MemoryRouter>,
    )
    expect(await screen.findByRole('heading', { name: '今日工作台' })).toBeInTheDocument()
  })
})
