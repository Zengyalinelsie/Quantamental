import {
  ExclamationCircleOutlined,
  LoadingOutlined,
  SafetyCertificateOutlined,
  StopOutlined,
} from '@ant-design/icons'
import type { ReactNode } from 'react'

/**
 * The six states a governed surface can be in.
 *
 * Four of them are server-owned data facts (`ready`, `partial`, `empty`,
 * `unavailable`); `loading` and `error` describe the request lifecycle and are
 * resolved by the client.  `empty` and `unavailable` are deliberately distinct:
 * empty means the capability works and holds no record, unavailable means the
 * capability or its store is missing.
 *
 * `blocked` is a deprecated alias of `unavailable` kept for existing call
 * sites; new code should use `unavailable`.
 */
export type WorkspaceStateKind =
  | 'loading'
  | 'error'
  | 'empty'
  | 'partial'
  | 'unavailable'
  | 'ready'
  | 'blocked'

type NoticeKind = Exclude<WorkspaceStateKind, 'ready'>

interface WorkspaceStateProps {
  state: WorkspaceStateKind
  reason: string
  children?: ReactNode
  title?: string
}

const labels: Record<NoticeKind, string> = {
  loading: '正在加载',
  error: '读取失败',
  empty: '暂无记录',
  partial: '部分可用',
  unavailable: '能力未启用',
  blocked: '能力未启用',
}

function StateIcon({ state }: { state: NoticeKind }) {
  if (state === 'loading') return <LoadingOutlined spin aria-hidden />
  if (state === 'blocked' || state === 'unavailable') return <StopOutlined aria-hidden />
  if (state === 'partial') return <ExclamationCircleOutlined aria-hidden />
  return <SafetyCertificateOutlined aria-hidden />
}

export function WorkspaceState({ state, reason, children, title }: WorkspaceStateProps) {
  if (state === 'ready') return <>{children}</>
  const assertive = state === 'error'
  const notice = (
    <section
      aria-live={assertive ? 'assertive' : 'polite'}
      className={`workspaceState workspaceState--${state}`}
      role={state === 'error' || state === 'blocked' || state === 'unavailable' ? 'alert' : 'status'}
    >
      <div className="workspaceState__inner">
        <StateIcon state={state} />
        <p className="workspaceState__label">{title ?? labels[state]}</p>
        <p className="workspaceState__reason">{reason}</p>
      </div>
    </section>
  )
  // Partial carries real data next to the caveat; hiding it would lose
  // information the server did manage to serve.
  if (state === 'partial') {
    return (
      <>
        {notice}
        {children}
      </>
    )
  }
  return notice
}
