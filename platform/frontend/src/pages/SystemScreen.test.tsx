import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
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
    cleanup()
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

  it('shows the second pre-sliced catalog page through the real Ant Table', async () => {
    const rows = Array.from({ length: 45 }, (_, index) => ({
      dataset_version_id: `dataset:${String(index).padStart(2, '0')}`,
      content_hash: String(index).repeat(64).slice(0, 64),
      created_at: '2026-08-10T12:00:00Z',
      schema_version: 'v1',
      metadata: {},
    }))
    vi.stubGlobal('fetch', vi.fn(async () => response(rows)))
    renderScreen('catalog')

    expect(await screen.findByText('dataset:00')).toBeInTheDocument()
    expect(screen.queryByText('dataset:20')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTitle('2'))

    expect(await screen.findByText('dataset:20')).toBeInTheDocument()
    expect(screen.queryByText('dataset:00')).not.toBeInTheDocument()
  })

  it('renders only the active jobs page while preserving the full pagination total', async () => {
    const rows = Array.from({ length: 45 }, (_, index) => ({
      job_id: `job:${String(index).padStart(2, '0')}`,
      plan_id: `plan:${String(index).padStart(2, '0')}`,
      provider_id: 'private-local-provider',
      status: 'succeeded',
      output_trust_state: 'normalized_current',
      start_date: '2018-01-01',
      end_date: '2026-08-10',
      created_at: '2026-08-10T11:00:00Z',
      updated_at: '2026-08-10T12:00:00Z',
      dataset_version_id: `dataset:${index}`,
      failure_reasons: [],
      checkpoints: [],
      quality_reports: [],
      coverage_reports: [],
    }))
    vi.stubGlobal('fetch', vi.fn(async () => response(rows)))
    renderScreen('jobs')

    expect(await screen.findByText('plan:00')).toBeInTheDocument()
    expect(screen.getByText('plan:19')).toBeInTheDocument()
    expect(screen.queryByText('plan:20')).not.toBeInTheDocument()
    expect(screen.getByTitle('3')).toBeInTheDocument()

    fireEvent.click(screen.getByTitle('2'))

    expect(await screen.findByText('plan:20')).toBeInTheDocument()
    expect(screen.queryByText('plan:00')).not.toBeInTheDocument()
  })

  it('paginates one job checkpoints and coverage independently with explicit totals', async () => {
    const coverageReports = Array.from({ length: 45 }, (_, index) => ({
      coverage_report_id: `coverage:${String(index).padStart(2, '0')}`,
      dataset_version_id: 'dataset:large-job',
      job_id: 'job:large',
      scope_id: 'csi500:financials',
      data_domain: `domain:${String(index).padStart(2, '0')}`,
      start_date: '2018-01-01',
      end_date: '2026-08-10',
      expected_rows: 1,
      observed_rows: 1,
      coverage_ratio: 1,
      warnings: [],
      created_at: '2026-08-10T12:00:00Z',
    }))
    const checkpoints = Array.from({ length: 45 }, (_, index) => ({
      checkpoint_key: `checkpoint:${String(index).padStart(2, '0')}`,
      scope_id: 'csi500:financials',
      data_domain: 'financial_statements',
      market: `M${String(index).padStart(2, '0')}`,
      status: 'succeeded',
      processed_rows: 1,
      rejected_rows: 0,
      provider_id: 'private-local-provider',
      updated_at: '2026-08-10T12:00:00Z',
      error: null,
      warnings: [],
    }))
    vi.stubGlobal('fetch', vi.fn(async () => response([{
      job_id: 'job:large',
      plan_id: 'plan:large-financial-job',
      provider_id: 'private-local-provider',
      status: 'succeeded',
      output_trust_state: 'normalized_current',
      start_date: '2018-01-01',
      end_date: '2026-08-10',
      created_at: '2026-08-10T11:00:00Z',
      updated_at: '2026-08-10T12:00:00Z',
      dataset_version_id: 'dataset:large-job',
      failure_reasons: [],
      checkpoints,
      quality_reports: [],
      coverage_reports: coverageReports,
    }])))
    renderScreen('jobs')

    const coverage = await screen.findByRole('region', {
      name: 'job:large coverage reports',
    })
    const checkpoint = screen.getByRole('region', { name: 'job:large checkpoints' })
    expect(within(coverage).getByText('45 TOTAL')).toBeInTheDocument()
    expect(within(checkpoint).getByText('45 TOTAL')).toBeInTheDocument()
    expect(within(coverage).getByText(/domain:19/)).toBeInTheDocument()
    expect(within(coverage).queryByText(/domain:20/)).not.toBeInTheDocument()
    expect(within(checkpoint).getByText(/M19/)).toBeInTheDocument()
    expect(within(checkpoint).queryByText(/M20/)).not.toBeInTheDocument()

    fireEvent.click(within(coverage).getByTitle('2'))
    expect(await within(coverage).findByText(/domain:20/)).toBeInTheDocument()
    expect(within(checkpoint).queryByText(/M20/)).not.toBeInTheDocument()

    fireEvent.click(within(checkpoint).getByTitle('2'))
    expect(await within(checkpoint).findByText(/M20/)).toBeInTheDocument()
  })
})
