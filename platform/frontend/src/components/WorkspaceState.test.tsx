import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { WorkspaceState } from './WorkspaceState'

describe('WorkspaceState', () => {
  it.each([
    ['loading', '正在读取权威数据'],
    ['error', '服务暂时不可用'],
    ['empty', '尚无符合条件的记录'],
    ['blocked', 'PIT 资格检查未通过'],
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
})
