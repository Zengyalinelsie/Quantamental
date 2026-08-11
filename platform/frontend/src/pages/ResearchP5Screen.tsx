import { useQuery } from '@tanstack/react-query'
import { Alert, Tag } from 'antd'
import { useEffect } from 'react'

import {
  getResearchWorkspace,
  type ResearchWorkspaceBlocker,
} from '../api/client'
import { WorkspaceState } from '../components/WorkspaceState'
import { InvestmentViewSummary } from '../features/investment-view/InvestmentViewSummary'
import { AlphaModelReadinessPanel } from '../features/screen/AlphaModelReadinessPanel'
import { ScreenRankingPanel } from '../features/screen/ScreenRankingPanel'
import { useWorkspaceStore } from '../state/workspace'
import './ResearchP5Screen.less'

interface ResearchP5ScreenProps {
  section: 'universe-screen' | 'security'
}

function ResearchBlockers({ blockers }: { blockers: ResearchWorkspaceBlocker[] }) {
  if (blockers.length === 0) return null
  return (
    <section aria-label="P5 研究工作区阻断" className="researchP5Blockers">
      {blockers.map((blocker) => (
        <article key={`${blocker.code}:${blocker.affected_binding}`}>
          <header>
            <Tag color="error">{blocker.code}</Tag>
            <code>{blocker.affected_binding}</code>
          </header>
          <p>{blocker.reason}</p>
          {blocker.evidence_ids.length === 0 ? (
            <span>未绑定阻断证据</span>
          ) : (
            <div>{blocker.evidence_ids.map((id) => <code key={id}>{id}</code>)}</div>
          )}
        </article>
      ))}
    </section>
  )
}

export function ResearchP5Screen({ section }: ResearchP5ScreenProps) {
  const securityQuery = useWorkspaceStore((state) => state.securityQuery)
  const setSystemAsOf = useWorkspaceStore((state) => state.setSystemAsOf)
  const query = useQuery({
    queryKey: ['research-p5-workspace', securityQuery],
    queryFn: ({ signal }) => getResearchWorkspace(
      securityQuery === '' ? undefined : securityQuery,
      signal,
    ),
  })

  useEffect(() => {
    if (query.data?.context.system_as_of) {
      setSystemAsOf(query.data.context.system_as_of)
    }
  }, [query.data, setSystemAsOf])

  if (query.isLoading) {
    return (
      <WorkspaceState
        reason="正在读取冻结 Screen、InvestmentView 与 Alpha 审批绑定。"
        state="loading"
        title="正在加载 P5 研究工作区"
      />
    )
  }
  if (query.isError) {
    return (
      <WorkspaceState
        reason={String(query.error)}
        state="error"
        title="P5 研究工作区读取失败"
      />
    )
  }
  if (!query.data) {
    return (
      <WorkspaceState
        reason="API 未返回 Envelope；页面没有可安全展示的数据。"
        state="empty"
        title="P5 研究工作区无响应"
      />
    )
  }

  const { context, data } = query.data
  const requestedProjection = section === 'universe-screen'
    ? data.screen
    : data.investment_view
  const emptyTitle = section === 'universe-screen'
    ? '尚无可展示的 Screen ranking'
    : '尚无可展示的 InvestmentView'
  const emptyReason = section === 'universe-screen'
    ? '服务端没有返回冻结 SignalSnapshot 排名；页面不会从 Universe 成员自行计算排序。'
    : '请在全局证券搜索输入真实代码或名称；前端会原样交给服务端解析。'

  return (
    <div className="researchP5Screen">
      <section aria-label="P5 API 查询用途" className="researchP5Context">
        <strong>API 查询用途</strong>
        <Tag>{data.status}</Tag>
        <Tag>{context.data_mode}</Tag>
        <Tag>{context.deployment_stage}</Tag>
        <span>SYSTEM AS OF {context.system_as_of}</span>
      </section>

      {context.warnings.map((warning) => (
        <Alert key={warning} showIcon title={warning} type="warning" />
      ))}

      {data.status === 'unavailable' ? (
        <WorkspaceState
          reason="服务端 readiness 判定为 unavailable；以下保留完整阻断与审批证据。"
          state="blocked"
          title="P5 研究工作区不可用"
        />
      ) : data.status === 'partial' ? (
        <Alert
          description="可用投影继续展示；缺失能力不会用零、演示模型或页面计算补齐。"
          showIcon
          title="P5 研究工作区仅部分可用"
          type="warning"
        />
      ) : null}

      <ResearchBlockers blockers={data.blockers} />

      {data.status !== 'unavailable' ? (
        requestedProjection ? (
          section === 'universe-screen'
            ? <ScreenRankingPanel projection={data.screen!} />
            : <InvestmentViewSummary projection={data.investment_view!} />
        ) : (
          <WorkspaceState reason={emptyReason} state="empty" title={emptyTitle} />
        )
      ) : null}

      <AlphaModelReadinessPanel projection={data.alpha_model} />
    </div>
  )
}
