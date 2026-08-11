import { Tabs } from 'antd'
import { useSearchParams } from 'react-router-dom'

import { PageHeading } from '../components/PageHeading'
import { WorkspaceUnavailable } from '../components/WorkspaceUnavailable'
import { SystemCatalogWorkspace } from './SystemCatalogWorkspace'
import { SystemScreen } from './SystemScreen'
import { ResearchP5Screen } from './ResearchP5Screen'
import { UniverseScreen } from './UniverseScreen'

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
      children: title === '研究' && key === 'universe-screen'
        ? (
          <div className="researchUniverseWorkspace">
            <section className="researchUniverseModule">
              <header>
                <p>HISTORICAL MEMBERSHIP</p>
                <h2>Universe Explorer</h2>
                <span>按真实 UniverseVersion 与 AS OF 查看成员、身份覆盖和研究资格。</span>
              </header>
              <UniverseScreen />
            </section>
            <section className="researchUniverseModule">
              <header>
                <p>GOVERNED RANKING</p>
                <h2>Screen 与 Alpha</h2>
                <span>只展示服务端冻结、用途获批且版本闭合的排名与模型绑定。</span>
              </header>
              <ResearchP5Screen section="universe-screen" />
            </section>
          </div>
        )
        : title === '研究' && key === 'security'
          ? <ResearchP5Screen section="security" />
        : key === 'catalog' && title === '数据与管理'
          ? <SystemCatalogWorkspace />
        : ['catalog', 'quality', 'lineage', 'jobs'].includes(key) && title === '数据与管理'
          ? <SystemScreen section={key as 'catalog' | 'quality' | 'lineage' | 'jobs'} />
        : <WorkspaceUnavailable reason={reason} />,
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
