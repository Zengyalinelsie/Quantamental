import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SystemScreen } from './SystemScreen'

const context = {
  as_of: '2026-08-10T12:00:00Z',
  system_as_of: '2026-08-10T12:01:00Z',
  data_mode: 'current_research',
  deployment_stage: 'research',
  trust_state: 'normalized_current',
  dataset_version_ids: [],
  model_version_ids: [],
  run_id: null,
  coverage: {},
  warnings: [],
}

function response(data: unknown) {
  return { ok: true, status: 200, json: async () => ({ data, context }) } as Response
}

function renderScreen(section: 'catalog' | 'quality' | 'lineage' | 'jobs') {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <SystemScreen section={section} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SystemScreen', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows an honest empty state without runtime demo rows', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response([])))
    renderScreen('catalog')
    expect(await screen.findByText('尚无 DatasetVersion')).toBeInTheDocument()
    expect(screen.queryByText('dataset:demo:v1')).not.toBeInTheDocument()
  })

  it('renders failed jobs with trust, coverage and blocking reasons', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response([{
      job_id: 'job:xshe:v1',
      plan_id: 'private-local:csi800-identity:xshe:v1',
      provider_id: 'a_share_identity_universe',
      status: 'failed',
      output_trust_state: 'normalized_current',
      start_date: '2018-01-01',
      end_date: '2026-08-10',
      created_at: '2026-08-10T11:00:00Z',
      updated_at: '2026-08-10T12:00:00Z',
      dataset_version_id: null,
      failure_reasons: ['missing_symbols=SZ.302132'],
      checkpoints: [{
        checkpoint_key: 'security_master:XSHE',
        scope_id: 'a-share:security-master',
        data_domain: 'security_master',
        market: 'XSHE',
        status: 'failed',
        processed_rows: 330,
        rejected_rows: 0,
        provider_id: 'a_share_identity_universe',
        updated_at: '2026-08-10T12:00:00Z',
        error: 'missing_symbols=SZ.302132',
        warnings: [],
      }],
      quality_reports: [],
      coverage_reports: [{
        coverage_report_id: 'coverage:xshe:v1',
        dataset_version_id: 'dataset:xshe:v1',
        job_id: 'job:xshe:v1',
        scope_id: 'a-share:security-master',
        data_domain: 'security_master',
        start_date: '2018-01-01',
        end_date: '2026-08-10',
        expected_rows: 331,
        observed_rows: 330,
        coverage_ratio: 330 / 331,
        warnings: ['code history unresolved'],
        created_at: '2026-08-10T12:00:00Z',
      }],
    }])))
    renderScreen('jobs')
    expect(await screen.findByText('private-local:csi800-identity:xshe:v1')).toBeInTheDocument()
    expect(screen.getByText('normalized_current')).toBeInTheDocument()
    expect(screen.getAllByText(/missing_symbols=SZ.302132/).length).toBeGreaterThan(0)
    expect(screen.getByText('330 / 331')).toBeInTheDocument()
  })

  it('distinguishes an API error from an empty catalog', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status: 503,
      json: async () => ({ detail: 'database unavailable' }),
    } as Response)))
    renderScreen('quality')
    expect(await screen.findByText('质量报告读取失败')).toBeInTheDocument()
    expect(screen.getByText(/database unavailable/)).toBeInTheDocument()
  })
})
