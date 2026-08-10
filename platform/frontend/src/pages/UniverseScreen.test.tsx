import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { UniverseScreen } from './UniverseScreen'

const context = {
  as_of: '2020-05-21T16:00:00Z',
  system_as_of: '2026-08-10T04:00:00Z',
  data_mode: 'current_research',
  deployment_stage: 'research',
  trust_state: null,
  dataset_version_ids: [],
  model_version_ids: [],
  run_id: null,
  coverage: {},
  warnings: [],
}

function response(data: unknown) {
  return { ok: true, status: 200, json: async () => ({ data, context }) } as Response
}

function renderScreen(entry: string) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[entry]}>
        <UniverseScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('UniverseScreen', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows an honest empty state when the runtime API has no universe versions', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response([])))
    renderScreen('/research?tab=universe-screen')
    expect(await screen.findByText('尚无可用的 UniverseVersion')).toBeInTheDocument()
    expect(screen.queryByText('退市美都')).not.toBeInTheDocument()
  })

  it('renders historical members including delisting and non-tradable evidence', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/universes') {
        return response([{
          universe_version_id: 'universe-version:core-a-share:v1',
          definition_id: 'universe:core-a-share',
          dataset_version_id: 'dataset:p2-contract-fixture:v1',
          created_at: '2026-08-10T04:00:00Z',
        }])
      }
      if (url.includes('/coverage')) {
        return response({
          universe_version_id: 'universe-version:core-a-share:v1',
          as_of: '2020-05-22',
          total_members: 1,
          identity_resolved: 1,
          research_eligible: 1,
          tradable_eligible: 0,
          identity_coverage: 1,
        })
      }
      return response({
        universe_version_id: 'universe-version:core-a-share:v1',
        dataset_version_id: 'dataset:p2-contract-fixture:v1',
        as_of: '2020-05-22',
        rows: [{
          listing_id: 'listing:meidu:xshg',
          company_id: 'company:meidu',
          security_id: 'security:meidu:a',
          exchange: 'XSHG',
          board: 'main',
          code: '600175',
          name: '退市美都',
          listed_on: '1999-04-08',
          delisted_on: '2020-08-14',
          industry_name: '房地产业',
          listing_state: 'active',
          special_treatment: 'star_st',
          research_eligible: true,
          tradable_eligible: false,
          inclusion_reasons: ['a_share', 'listed'],
          exclusion_reasons: ['special_treatment'],
          benchmark_member: false,
          identity_resolved: true,
        }],
      })
    }))
    renderScreen(
      '/research?tab=universe-screen&universe=universe-version%3Acore-a-share%3Av1'
      + '&point=historical&as_of=2020-05-22',
    )
    expect(await screen.findByText('退市美都')).toBeInTheDocument()
    expect(screen.getByText('退市日 2020-08-14')).toBeInTheDocument()
    expect(screen.getByText('不可交易')).toBeInTheDocument()
    expect(screen.getByText('*ST')).toBeInTheDocument()
    expect(screen.getByText(/不是 strict_historical/)).toBeInTheDocument()
    expect(screen.getByText('dataset:p2-contract-fixture:v1')).toBeInTheDocument()
  })
})
