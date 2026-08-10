import { WorkspaceState } from './WorkspaceState'

interface WorkspaceUnavailableProps {
  reason: string
  title?: string
}

export function WorkspaceUnavailable({ reason, title }: WorkspaceUnavailableProps) {
  return <WorkspaceState state="blocked" reason={reason} title={title} />
}
