import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SystemEvidenceScreen } from './SystemEvidenceScreen'

const context = {
  as_of: '2026-08-10T12:00:00Z',
  system_as_of: '2026-08-10T12:01:00Z',
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

function renderScreen() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <SystemEvidenceScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SystemEvidenceScreen', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('shows disclosure versions and opens raw evidence metadata without fake content', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/evidence/')) return response({
        raw_object_id: 'raw:cninfo:1',
        source_url: 'https://www.cninfo.com.cn/disclosure/1.pdf',
        content_hash: `sha256:${'a'.repeat(64)}`,
        provider_id: 'cninfo',
        retrieved_at: '2026-08-10T12:00:00Z',
        media_type: 'application/pdf',
        storage_uri: 'object://sha256/aa/test',
        license_id: 'cninfo-public-disclosure',
        retention_policy: 'metadata_only',
        retention_until: null,
        redistribution_allowed: false,
        object_kind: 'file',
      })
      return response([{
        disclosure_id: 'disclosure:1:v1',
        document_key: 'cninfo:annual:600519:2024',
        external_document_id: '1',
        company_id: 'company:600519',
        security_id: 'security:600519',
        source_system: 'cninfo',
        title: '2024 年年度报告（更正后）',
        document_type: 'annual_report',
        report_period_end: '2024-12-31',
        published_at: '2026-08-10T12:00:00Z',
        available_at: '2026-08-10T12:00:00Z',
        first_tradable_at: '2026-08-10T12:00:00Z',
        version_sequence: 1,
        status: 'corrected',
        raw_object_id: 'raw:cninfo:1',
        supersedes_disclosure_id: 'disclosure:1:v0',
        status_reason: '官方更正',
      }])
    }))
    renderScreen()
    fireEvent.change(screen.getByLabelText('公司 ID'), { target: { value: 'company:600519' } })
    fireEvent.click(screen.getByRole('button', { name: '查询披露' }))
    expect(await screen.findByText('2024 年年度报告（更正后）')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '查看原始证据' }))
    expect(await screen.findByText('metadata_only')).toBeInTheDocument()
    expect(screen.getByText(/不允许再分发/)).toBeInTheDocument()
  })

  it('makes unavailable strict comparison visibly different from current data', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({
      company_id: 'company:600519',
      security_id: 'security:600519',
      metric_code: 'income.revenue',
      report_period_end: '2024-12-31',
      period_type: 'annual',
      statement_type: 'income_statement',
      decision_time: '2026-08-10T12:00:00Z',
      system_time: '2026-08-10T12:00:00Z',
      authority_rule_version: 'authority:official:v1',
      current: {
        status: 'selected',
        selected: { value: '174144000000', trust_state: 'normalized_current' },
        conflicting_fact_ids: [], quality_issue_ids: [], blocks_downstream: false, reason: null,
      },
      strict: {
        status: 'unavailable', selected: null, conflicting_fact_ids: [],
        quality_issue_ids: ['issue:no-pit-verified-observation'], blocks_downstream: true,
        reason: 'no pit_verified observation is eligible',
      },
    })))
    renderScreen()
    fireEvent.click(screen.getByRole('tab', { name: 'Current / Strict' }))
    fireEvent.change(screen.getByLabelText('对比公司 ID'), { target: { value: 'company:600519' } })
    fireEvent.change(screen.getByLabelText('对比证券 ID'), { target: { value: 'security:600519' } })
    fireEvent.change(screen.getByLabelText('对比指标代码'), { target: { value: 'income.revenue' } })
    fireEvent.change(screen.getByLabelText('报告期'), { target: { value: '2024-12-31' } })
    fireEvent.change(screen.getByLabelText('Authority Rule'), { target: { value: 'authority:official:v1' } })
    fireEvent.click(screen.getByRole('button', { name: '执行对比' }))
    expect(await screen.findByText('normalized_current')).toBeInTheDocument()
    expect(screen.getByText('strict_historical：不可用')).toBeInTheDocument()
    expect(screen.getByText(/no pit_verified/)).toBeInTheDocument()
  })
})
