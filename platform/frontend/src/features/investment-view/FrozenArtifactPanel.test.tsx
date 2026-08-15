import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { FrozenArtifactPanel } from './FrozenArtifactPanel'

function response(data: unknown, ok = true, detail = ''): Response {
  return {
    ok,
    status: ok ? 200 : 503,
    json: async () => ok ? { data, context: {} } : { detail },
  } as Response
}

function renderPanel(artifactId: string | null) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <FrozenArtifactPanel artifactId={artifactId} />
    </QueryClientProvider>,
  )
}

describe('FrozenArtifactPanel', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('shows an honest not-generated state without requesting or inventing an artifact', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    renderPanel(null)

    expect(screen.getByText('Frozen Artifact 尚未生成')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '下载不可变产物' })).not.toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('keeps download disabled when the server identity lacks read_artifact', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({
      subject_id: 'anonymous',
      roles: [],
      permissions: ['read_public'],
    })))

    renderPanel('artifact:investment-view:600519:v1')

    expect(await screen.findByText('Frozen Artifact 下载受限')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '下载不可变产物' })).toBeDisabled()
    expect(screen.getByText(/未授予 read_artifact/)).toBeInTheDocument()
  })

  it('fails closed when a stale identity response omits permissions', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({
      subject_id: 'anonymous',
      roles: [],
    })))

    renderPanel('artifact:investment-view:600519:v1')

    expect(await screen.findByText('Frozen Artifact 下载受限')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '下载不可变产物' })).toBeDisabled()
  })

  it('loads exact metadata before exposing the immutable download URL', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      if (path === '/api/identity') {
        return response({
          subject_id: 'subject:researcher',
          roles: ['researcher'],
          permissions: ['read_public', 'read_artifact'],
        })
      }
      return response({
        artifact_id: 'artifact:investment-view:600519:v1',
        run_id: 'run:investment-view:600519:v1',
        content_hash: `sha256:${'a'.repeat(64)}`,
        media_type: 'application/json',
        created_at: '2026-08-14T08:00:00Z',
        producer_context: {
          data_mode: 'strict_historical',
          deployment_stage: 'research',
        },
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPanel('artifact:investment-view:600519:v1')

    expect(await screen.findByText('Frozen Artifact 已验证')).toBeInTheDocument()
    expect(screen.getByText('run:investment-view:600519:v1')).toBeInTheDocument()
    expect(screen.getByText(`sha256:${'a'.repeat(64)}`)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '下载不可变产物' })).toHaveAttribute(
      'href',
      '/api/artifacts/artifact%3Ainvestment-view%3A600519%3Av1/download',
    )
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/artifacts/artifact%3Ainvestment-view%3A600519%3Av1',
      expect.objectContaining({ headers: { Accept: 'application/json' } }),
    )
  })

  it('shows metadata failure instead of exposing an unchecked download link', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => (
      String(input) === '/api/identity'
        ? response({
          subject_id: 'subject:researcher', roles: ['researcher'],
          permissions: ['read_public', 'read_artifact'],
        })
        : response(null, false, 'artifact integrity error')
    )))

    renderPanel('artifact:investment-view:600519:v1')

    expect(await screen.findByText('Frozen Artifact 元数据读取失败')).toBeInTheDocument()
    expect(screen.getByText(/artifact integrity error/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '下载不可变产物' })).not.toBeInTheDocument()
  })

  it('rejects metadata whose artifact identity differs from the requested artifact', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => (
      String(input) === '/api/identity'
        ? response({
          subject_id: 'subject:researcher', roles: ['researcher'],
          permissions: ['read_public', 'read_artifact'],
        })
        : response({
          artifact_id: 'artifact:investment-view:other:v1',
          run_id: 'run:investment-view:other:v1',
          content_hash: `sha256:${'b'.repeat(64)}`,
          media_type: 'application/json',
          created_at: '2026-08-14T08:00:00Z',
          producer_context: {
            data_mode: 'strict_historical',
            deployment_stage: 'research',
          },
        })
    )))

    renderPanel('artifact:investment-view:600519:v1')

    expect(await screen.findByText('Frozen Artifact 身份校验失败')).toBeInTheDocument()
    expect(screen.getByText(/返回的 Artifact ID 与请求不一致/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '下载不可变产物' })).not.toBeInTheDocument()
  })
})
