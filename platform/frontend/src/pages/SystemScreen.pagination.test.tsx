import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { SystemSection } from '../api/client'
import { SystemScreen } from './SystemScreen'

interface CapturedPagination {
  current?: number
  pageSize?: number
  showSizeChanger?: boolean
  total?: number
  onChange?: (page: number, pageSize: number) => void
}

interface CapturedTableProps {
  dataSource?: Array<Record<string, unknown>>
  pagination?: CapturedPagination | false
}

const tableSpy = vi.hoisted(() => vi.fn())

vi.mock('antd', async (importOriginal) => {
  const actual = await importOriginal<typeof import('antd')>()
  return {
    ...actual,
    Table: (props: CapturedTableProps) => {
      tableSpy(props)
      const pagination = props.pagination && typeof props.pagination === 'object'
        ? props.pagination
        : undefined
      return (
        <button
          aria-label="go to second client page"
          onClick={() => pagination?.onChange?.(2, pagination.pageSize ?? 20)}
          type="button"
        >
          page 2
        </button>
      )
    },
  }
})

const context = {
  as_of: '2026-08-11T08:00:00Z',
  system_as_of: '2026-08-11T08:01:00Z',
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

function renderScreen(section: SystemSection) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <SystemScreen section={section} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function catalogRows(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    dataset_version_id: `dataset:${String(index).padStart(2, '0')}`,
    content_hash: String(index).repeat(64).slice(0, 64),
    created_at: '2026-08-11T08:00:00Z',
    schema_version: 'v1',
    metadata: {},
  }))
}

function qualityRows(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    quality_report_id: `quality:${String(index).padStart(2, '0')}`,
    dataset_version_id: `dataset:${String(index).padStart(2, '0')}`,
    job_id: `job:${index}`,
    status: 'passed',
    checks_passed: 1,
    checks_failed: 0,
    issue_counts: {},
    warnings: [],
    created_at: '2026-08-11T08:00:00Z',
  }))
}

function lineageRows(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    upstream_id: `upstream:${String(index).padStart(2, '0')}`,
    downstream_id: `downstream:${String(index).padStart(2, '0')}`,
    relation: 'derived_from',
  }))
}

function lastTableProps(): CapturedTableProps {
  const call = tableSpy.mock.calls.at(-1)
  if (!call) throw new Error('Table was not rendered')
  return call[0] as CapturedTableProps
}

describe('SystemScreen client pagination', () => {
  afterEach(() => {
    cleanup()
    tableSpy.mockClear()
    vi.unstubAllGlobals()
  })

  it.each([
    ['catalog', catalogRows(45), 'dataset:20'],
    ['quality', qualityRows(45), 'quality:20'],
    ['lineage', lineageRows(45), 'upstream:20'],
  ] as const)(
    'passes only the active %s page to Table while preserving the full total',
    async (section, rows, expectedSecondPageId) => {
      vi.stubGlobal('fetch', vi.fn(async () => response(rows)))
      renderScreen(section)

      await waitFor(() => expect(tableSpy).toHaveBeenCalled())
      const firstPage = lastTableProps()
      expect(firstPage.dataSource).toHaveLength(20)
      expect(firstPage.pagination).toMatchObject({
        current: 1,
        pageSize: 20,
        showSizeChanger: false,
        total: 45,
      })

      fireEvent.click(screen.getByRole('button', { name: 'go to second client page' }))

      await waitFor(() => expect(lastTableProps().pagination).toMatchObject({ current: 2 }))
      const secondPage = lastTableProps()
      expect(secondPage.dataSource).toHaveLength(20)
      expect(Object.values(secondPage.dataSource?.[0] ?? {})).toContain(expectedSecondPageId)
      expect(secondPage.pagination).toMatchObject({ total: 45 })
    },
  )
})
