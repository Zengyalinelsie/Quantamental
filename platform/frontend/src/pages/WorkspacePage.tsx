import { Tabs } from 'antd'
import { useSearchParams } from 'react-router-dom'

import { PageHeading } from '../components/PageHeading'
import { WorkspaceUnavailable } from '../components/WorkspaceUnavailable'

interface WorkspacePageProps {
  title: string
  description: string
  tabs: readonly string[]
}

function tabKey(label: string) {
  return label.toLowerCase().replaceAll(' & ', '-').replaceAll('/', '-').replaceAll(' ', '-')
}

const activationReasons: Record<string, string> = {
  events: '事件账本将在 P8 接入；当前不生成新闻情绪或事件收益假值。',
  execution: '执行监控将在 Paper OMS 启用后开放；当前没有连接账户或券商。',
  users: '身份提供方尚未配置，不能用本地字符串冒充用户身份。',
  entitlements: '字段授权与身份服务尚未接入，权限状态保持不可用。',
  agents: 'Agent runtime 尚未启用，且 Agent 永远没有交易权限。',
  approvals: '服务端审批工作流尚未启用，前端不会模拟审批结果。',
}

export function WorkspacePage({ title, description, tabs }: WorkspacePageProps) {
  const [searchParams, setSearchParams] = useSearchParams()
  const keys = tabs.map(tabKey)
  const requested = searchParams.get('tab')
  const activeKey = requested && keys.includes(requested) ? requested : keys[0]
  const items = tabs.map((label, index) => {
    const key = keys[index]
    const reason = activationReasons[key]
      ?? `${label} 将在对应领域 API 和权威数据版本就绪后启用；当前不注入运行时演示数据。`
    return {
      key,
      label,
      children: <WorkspaceUnavailable reason={reason} />,
    }
  })
  return (
    <div className="workspacePage">
      <PageHeading title={title} description={description} eyebrow="RESEARCH WORKSPACE" />
      <Tabs
        activeKey={activeKey}
        items={items}
        onChange={(next) => {
          const updated = new URLSearchParams(searchParams)
          updated.set('tab', next)
          setSearchParams(updated, { replace: true })
        }}
      />
    </div>
  )
}
