import { LoadingOutlined, SafetyCertificateOutlined, StopOutlined } from '@ant-design/icons'
import type { ReactNode } from 'react'

export type WorkspaceStateKind = 'loading' | 'error' | 'empty' | 'blocked' | 'ready'

interface WorkspaceStateProps {
  state: WorkspaceStateKind
  reason: string
  children?: ReactNode
  title?: string
}

const labels: Record<Exclude<WorkspaceStateKind, 'ready'>, string> = {
  loading: '正在加载',
  error: '读取失败',
  empty: '暂无记录',
  blocked: '能力未启用',
}

function StateIcon({ state }: { state: Exclude<WorkspaceStateKind, 'ready'> }) {
  if (state === 'loading') return <LoadingOutlined spin aria-hidden />
  if (state === 'blocked') return <StopOutlined aria-hidden />
  return <SafetyCertificateOutlined aria-hidden />
}

export function WorkspaceState({ state, reason, children, title }: WorkspaceStateProps) {
  if (state === 'ready') return <>{children}</>
  return (
    <section
      aria-live={state === 'error' ? 'assertive' : 'polite'}
      className={`workspaceState workspaceState--${state}`}
      role={state === 'error' || state === 'blocked' ? 'alert' : 'status'}
    >
      <div className="workspaceState__inner">
        <StateIcon state={state} />
        <p className="workspaceState__label">{title ?? labels[state]}</p>
        <p className="workspaceState__reason">{reason}</p>
      </div>
    </section>
  )
}
