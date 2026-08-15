import { useQuery } from '@tanstack/react-query'

import { getDesk } from '../api/client'
import { PageHeading } from '../components/PageHeading'
import { WorkspaceState } from '../components/WorkspaceState'
import {
  ActiveFailureSection,
  DataHealthSection,
  EventFeedSection,
  PendingTaskSection,
  PortfolioTrackingSection,
  ScreenShiftSection,
  TimingShadowSection,
} from '../features/desk/deskSections'
import type { DeskSection, DeskSectionKey } from '../features/desk/deskTypes'

const SECTION_ORDER: DeskSectionKey[] = [
  'data_health',
  'screen_shifts',
  'portfolio_tracking',
  'timing_shadow',
  'event_feed',
  'pending_tasks',
  'active_failures',
]

const FALLBACK_TITLES: Record<DeskSectionKey, string> = {
  data_health: '数据健康',
  screen_shifts: '最新 Screen 排名变化',
  portfolio_tracking: '组合偏离与风险',
  timing_shadow: 'Timing Shadow',
  event_feed: '重大事件/公告流',
  pending_tasks: '因子审核与待处理',
  active_failures: '运行异常',
}

/**
 * Resolve one section, tolerating a server that omitted it.
 *
 * The contract guarantees all seven, but if one is ever missing the page shows
 * an explicit unavailable card rather than silently dropping a domain: a desk
 * that quietly loses a section would read as "nothing to report".
 */
function sectionFor(sections: DeskSection[] | undefined, key: DeskSectionKey): DeskSection {
  const found = sections?.find((item) => item.key === key)
  if (found) return found
  return {
    key,
    status: 'unavailable',
    title: FALLBACK_TITLES[key],
    blockers: [{
      code: 'DESK_SECTION_MISSING',
      reason: '服务端未返回该分区，无法确认其真实状态。',
      affected_binding: `desk.${key}`,
      evidence_ids: [],
    }],
    coverage: {},
    payload: null,
  }
}

export function DeskPage() {
  const desk = useQuery({
    queryKey: ['desk'],
    queryFn: ({ signal }) => getDesk(signal),
  })

  const sections = desk.data?.data.sections
  const loading = desk.isPending
  const error = desk.error ? String((desk.error as Error).message ?? desk.error) : undefined
  const context = desk.data?.context
  const shared = { loading, error }

  if (loading) {
    return (
      <div className="workspacePage">
        <PageHeading
          description="服务端 Desk 投影正在读取七个分区的真实状态。"
          eyebrow="FUNDAMENTAL QUANT"
          title="今日工作台"
        />
        <WorkspaceState
          reason="正在读取七个分区的服务端状态。"
          state="loading"
          title="正在加载今日工作台"
        />
      </div>
    )
  }  if (error) {
    return (
      <div className="workspacePage">
        <PageHeading
          description="服务端 Desk 投影读取失败；页面不会用示例数据替代真实状态。"
          eyebrow="FUNDAMENTAL QUANT"
          title="今日工作台"
        />
        <WorkspaceState reason={error} state="error" title="今日工作台读取失败" />
      </div>
    )
  }

  return (
    <div className="workspacePage">
      <PageHeading
        description="七个分区各自报告真实状态，不可用的能力显示明确原因，不展示模拟数据。"
        eyebrow="FUNDAMENTAL QUANT"
        title="今日工作台"
      />
      <section aria-label="今日研究态势" className="deskBanner">
        <h2>今日研究态势 / Platform Pulse</h2>
        {context ? (
          <p>
            {`数据模式 ${context.data_mode} · 部署阶段 ${context.deployment_stage} · 系统时间 ${context.system_as_of}`}
          </p>
        ) : null}
      </section>
      <div className="deskGrid">
        <div className="deskColumn">
          <ScreenShiftSection section={sectionFor(sections, 'screen_shifts')} {...shared} />
          <DataHealthSection section={sectionFor(sections, 'data_health')} {...shared} />
          <div className="deskMetricRow">
            <PortfolioTrackingSection
              section={sectionFor(sections, 'portfolio_tracking')}
              {...shared}
            />
            <TimingShadowSection section={sectionFor(sections, 'timing_shadow')} {...shared} />
          </div>
        </div>
        <div className="deskColumn">
          <EventFeedSection section={sectionFor(sections, 'event_feed')} {...shared} />
          <PendingTaskSection section={sectionFor(sections, 'pending_tasks')} {...shared} />
          <ActiveFailureSection section={sectionFor(sections, 'active_failures')} {...shared} />
        </div>
      </div>
    </div>
  )
}

export { SECTION_ORDER }
