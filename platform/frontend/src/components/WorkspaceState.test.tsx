import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { WorkspaceState } from './WorkspaceState'

describe('WorkspaceState', () => {
  afterEach(cleanup)

  it.each([
    ['loading', '正在读取权威数据'],
    ['error', '服务暂时不可用'],
    ['empty', '尚无符合条件的记录'],
    ['blocked', 'PIT 资格检查未通过'],
    ['partial', '仅 12/500 个 dataset 有质量报告'],
    ['unavailable', '组合跟踪能力属 P6，尚未实现'],
  ] as const)('renders the %s state with an explicit reason', (state, reason) => {
    render(<WorkspaceState state={state} reason={reason} />)
    expect(screen.getByText(reason)).toBeInTheDocument()
  })

  it('renders children only for ready state', () => {
    render(
      <WorkspaceState state="ready" reason="">
        <span>真实结果</span>
      </WorkspaceState>,
    )
    expect(screen.getByText('真实结果')).toBeInTheDocument()
  })

  it('renders children alongside the notice for partial state', () => {
    // Partial means some real data exists; hiding it would lose information.
    render(
      <WorkspaceState state="partial" reason="仅覆盖 1/3 dataset">
        <span>真实局部结果</span>
      </WorkspaceState>,
    )
    expect(screen.getByText('真实局部结果')).toBeInTheDocument()
    expect(screen.getByText('仅覆盖 1/3 dataset')).toBeInTheDocument()
  })

  it('distinguishes empty from unavailable in the default label', () => {
    const { unmount } = render(<WorkspaceState state="empty" reason="库中没有记录" />)
    expect(screen.getByText('暂无记录')).toBeInTheDocument()
    unmount()
    render(<WorkspaceState state="unavailable" reason="能力尚未实现" />)
    expect(screen.getByText('能力未启用')).toBeInTheDocument()
  })

  it('announces errors assertively and other states politely', () => {
    const { unmount } = render(<WorkspaceState state="error" reason="读取失败" />)
    expect(screen.getByRole('alert')).toHaveAttribute('aria-live', 'assertive')
    unmount()
    render(<WorkspaceState state="empty" reason="库中没有记录" />)
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite')
  })
})
