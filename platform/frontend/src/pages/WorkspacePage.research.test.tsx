import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { workspaceDefinitions } from '../navigation/routes'
import { WorkspacePage } from './WorkspacePage'

describe('WorkspacePage P5 research wiring', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('keeps the real Universe browser while wiring Screen and Security to P5', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => ({
      ok: true,
      status: 200,
      json: async () => String(input) === '/api/universes' ? ({
        data: [],
        context: {
          as_of: '2026-08-11T08:00:00Z', system_as_of: '2026-08-11T08:05:00Z',
          data_mode: 'current_research', deployment_stage: 'research', trust_state: null,
          dataset_version_ids: [], model_version_ids: [], run_id: null, coverage: {}, warnings: [],
        },
      }) : ({
        data: {
          status: 'partial',
          blockers: [],
          screen: null,
          investment_view: null,
          alpha_model: {
            status: 'unavailable',
            requested_scope: 'research_backtest',
            data_mode: 'current_research',
            deployment_stage: 'research',
            checked_at: '2026-08-11T08:05:00Z',
            blocked_reasons: [{
              code: 'NO_APPROVED_FACTOR_VERSION', reason: '尚无获批因子。',
              affected_binding: 'factor-version:*', evidence_ids: [],
            }],
          },
        },
        context: {
          as_of: '2026-08-11T08:00:00Z', system_as_of: '2026-08-11T08:05:00Z',
          data_mode: 'current_research', deployment_stage: 'research', trust_state: 'normalized_current',
          dataset_version_ids: [], model_version_ids: [], run_id: null, coverage: {}, warnings: [],
        },
      }),
    } as Response))
    vi.stubGlobal('fetch', fetchMock)
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/research?tab=universe-screen']}>
          <WorkspacePage {...workspaceDefinitions.research} />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('尚无可展示的 Screen ranking')).toBeInTheDocument()
    expect(await screen.findByText('尚无可用的 UniverseVersion')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Universe Explorer' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Screen 与 Alpha' })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/universes',
      expect.objectContaining({ headers: { Accept: 'application/json' } }),
    )
    fireEvent.click(screen.getByRole('tab', { name: 'Security' }))
    expect(await screen.findByText('尚无可展示的 InvestmentView')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/research/workspace',
      expect.objectContaining({ headers: { Accept: 'application/json' } }),
    )
  })
})
