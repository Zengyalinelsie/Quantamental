import type { ReactNode } from 'react'

import { coverageText, noticeReason, resolveSectionState } from './deskState'
import type { DeskSection as DeskSectionData } from './deskTypes'
import { WorkspaceState } from '../../components/WorkspaceState'

interface DeskSectionProps {
  section: DeskSectionData
  /** Request in flight.  Owned by the client, never by the server. */
  loading?: boolean
  /** Request failed.  Owned by the client, never by the server. */
  error?: string
  subtitle?: string
  extra?: ReactNode
  children?: ReactNode
}

export function DeskSection({
  section,
  loading,
  error,
  subtitle,
  extra,
  children,
}: DeskSectionProps) {
  const state = resolveSectionState(section, { loading, error })
  const showCoverage =
    state === 'partial' && Object.keys(section.coverage).length > 0 && section.blockers.length > 0

  return (
    <section aria-label={section.title} className="deskSection">
      <div className="sectionHeading">
        <div>
          <h2>{section.title}</h2>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        {extra}
      </div>
      <div className="deskSection__body">
        <WorkspaceState reason={noticeReason(section, error)} state={state}>
          {children}
        </WorkspaceState>
        {showCoverage ? (
          <p className="deskSection__coverage">覆盖范围：{coverageText(section.coverage)}</p>
        ) : null}
        {state === 'unavailable' || state === 'partial' ? (
          <dl className="deskSection__blockers">
            {section.blockers.map((item) => (
              <div className="deskSection__blocker" key={item.code}>
                <dt>{item.code}</dt>
                <dd>{item.affected_binding}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </div>
    </section>
  )
}
