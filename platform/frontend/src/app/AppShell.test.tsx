import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppShell } from './AppShell'
import { useWorkspaceStore } from '../state/workspace'

describe('AppShell', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

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
    expect(await screen.findByRole('heading', { name: '研究' }, { timeout: 3_000 }))
      .toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Events' })).toHaveAttribute('aria-selected', 'true')
  })

  it('redirects legacy dashboard route explicitly', async () => {
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <AppShell />
      </MemoryRouter>,
    )
    expect(await screen.findByRole('heading', { name: '今日工作台' }, { timeout: 3_000 }))
      .toBeInTheDocument()
  })

  it('reflects URL universe and historical as-of without relabelling the data mode', async () => {
    render(
      <MemoryRouter initialEntries={[
        '/research?tab=events&universe=universe-version%3Acore-a-share%3Av1'
        + '&point=historical&as_of=2020-05-22',
      ]}>
        <AppShell />
      </MemoryRouter>,
    )
    expect(await screen.findByRole('heading', { name: '研究' }, { timeout: 3_000 }))
      .toBeInTheDocument()
    expect(screen.getByText('universe-version:core-a-share:v1')).toBeInTheDocument()
    expect(screen.getByText('2020-05-22')).toBeInTheDocument()
    expect(screen.getByText('current_research')).toBeInTheDocument()
  })

  it('uses the real collapsed navigation contract at the 1024 breakpoint', async () => {
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

    const { container } = render(
      <MemoryRouter initialEntries={['/research?tab=events']}>
        <AppShell />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: '研究' }, { timeout: 3_000 }))
      .toBeInTheDocument()
    expect(container.querySelector('.desktopSider')).toHaveClass('ant-layout-sider-collapsed')
    expect(screen.getByLabelText('较窄屏幕自动收起')).toHaveTextContent('AUTO')
    expect(screen.getByText('UNIVERSE').closest('.contextItem'))
      .toHaveClass('contextItem--responsive-required')
    expect(screen.getByText('AS OF').closest('.contextItem'))
      .toHaveClass('contextItem--responsive-required')
    expect(screen.getByText('SYSTEM AS OF').closest('.contextItem'))
      .toHaveClass('contextItem--responsive-required')
  })
})
